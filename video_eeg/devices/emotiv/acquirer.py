"""Unified Cortex-compatible acquisition backend for EMOTIV headsets."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from video_eeg.devices.base import AbstractAcquirer, AcquirerMetadata, EEGChunk

from .buffer import EEGBuffer
from .clock_sync import ClockSync
from .config import EmotivConfig, parse_config
from .cortex_client import CortexClient, authenticate, select_headset, wait_until_connected
from .errors import CortexProtocolError, EmotivConfigurationError, EmotivError
from .marker_backend import EmotivCortexMarkerBackend
from .profiles import DeviceProfile, resolve_profile
from .record_manager import RecordManager
from .stream_parser import StreamParser


class EmotivAcquirer(AbstractAcquirer):
    def __init__(
        self,
        *,
        emotiv_config: dict[str, Any],
        project_dir: str | Path,
        buffer_sec: float,
    ) -> None:
        self.config: EmotivConfig = parse_config(
            emotiv_config, project_dir=Path(project_dir), buffer_sec=buffer_sec
        )
        self.client = CortexClient(self.config.url, request_timeout_sec=self.config.request_timeout_sec)
        self.clock = ClockSync()
        self.token = ""
        self.session_id = ""
        self.headset: dict[str, Any] = {}
        self.profile: DeviceProfile
        self.parser: StreamParser
        self.buffer: EEGBuffer
        self.record_manager: RecordManager
        self._stream_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._stream_error: BaseException | None = None
        self._started = False
        self._auxiliary_latest: dict[str, Any] = {}
        self._sample_count = 0
        self._interpolated_count = 0
        self._counter_discontinuities = 0
        self._previous_counter: int | None = None
        self._connect_and_subscribe()

    def _connect_and_subscribe(self) -> None:
        self.client.open()
        try:
            self.token = authenticate(
                self.client,
                client_id=self.config.client_id,
                client_secret=self.config.client_secret,
            )
            self.client.request("controlDevice", {"command": "refresh"})
            self.headset = self._discover_headset()
            self.profile = resolve_profile(self.config.model, self.headset)
            if self.profile.requires_mapping and self.config.mapping is None:
                raise EmotivConfigurationError(
                    f"EMOTIV model {self.profile.name} requires device.emotiv.mapping_file"
                )
            if self.headset.get("status") != "connected":
                params: dict[str, Any] = {"command": "connect", "headset": self.headset["id"]}
                if self.profile.requires_mapping:
                    params["mappings"] = self.config.mapping
                self.client.request("controlDevice", params)
                self.headset = wait_until_connected(
                    self.client,
                    str(self.headset["id"]),
                    timeout_sec=self.config.discovery_timeout_sec,
                )
            if self.profile.requires_mapping:
                flex_mappings = self.headset.get("flexMappings")
                detected_mapping = (
                    flex_mappings.get("mappings")
                    if isinstance(flex_mappings, dict)
                    else None
                )
                if detected_mapping != self.config.mapping:
                    raise EmotivConfigurationError(
                        "Cortex Flex mapping does not match the configured mapping: "
                        f"configured={self.config.mapping}, detected={detected_mapping}, "
                        f"headset={self.headset['id']}"
                    )
            settings = self.headset.get("settings")
            sfreq = settings.get("eegRate") if isinstance(settings, dict) else None
            if not isinstance(sfreq, (int, float)) or sfreq <= 0:
                raise CortexProtocolError(f"Headset has no valid settings.eegRate: {self.headset}")
            if self.config.expected_sfreq is not None and float(sfreq) != self.config.expected_sfreq:
                raise EmotivConfigurationError(
                    f"EMOTIV sampling rate mismatch: configured={self.config.expected_sfreq:g}, detected={float(sfreq):g}, headset={self.headset['id']}"
                )
            session = self.client.request(
                "createSession",
                {"cortexToken": self.token, "headset": self.headset["id"], "status": "active"},
            )
            session_id = session.get("id") if isinstance(session, dict) else None
            if not isinstance(session_id, str) or not session_id:
                raise CortexProtocolError(f"createSession returned no session id: {session}")
            self.session_id = session_id
            self.client.register_stream("eeg")
            subscription = self.client.request(
                "subscribe",
                {"cortexToken": self.token, "session": self.session_id, "streams": ["eeg"]},
            )
            self.parser = self._parser_from_subscription(subscription)
            if (
                self.config.expected_channels is not None
                and self.parser.channel_names != self.config.expected_channels
            ):
                raise EmotivConfigurationError(
                    f"EMOTIV channel mismatch: configured={list(self.config.expected_channels)}, detected={list(self.parser.channel_names)}, headset={self.headset['id']}"
                )
            self.buffer = EEGBuffer(
                channels=len(self.parser.channel_names),
                capacity=max(1, int(float(sfreq) * self.config.buffer_sec)),
            )
            self.metadata = AcquirerMetadata(
                name="emotiv",
                sfreq=float(sfreq),
                n_channels=len(self.parser.channel_names),
                eeg_channel_count=len(self.parser.channel_names),
                channel_names=self.parser.channel_names,
                auxiliary_channel_names=self.parser.auxiliary_names,
            )
            self.record_manager = RecordManager(
                self.client, token=self.token, session_id=self.session_id
            )
        except BaseException:
            self.client.close()
            raise

    def _discover_headset(self) -> dict[str, Any]:
        deadline = time.monotonic() + self.config.discovery_timeout_sec
        last_result: Any = []
        while time.monotonic() < deadline:
            params = {"includeFlexMappings": True}
            if self.config.headset_id != "auto":
                params["id"] = self.config.headset_id
            last_result = self.client.request("queryHeadsets", params)
            if last_result:
                return select_headset(last_result, self.config.headset_id)
            time.sleep(0.2)
        raise EmotivError(f"No EMOTIV headset discovered before timeout; last result={last_result}")

    @staticmethod
    def _parser_from_subscription(subscription: Any) -> StreamParser:
        if not isinstance(subscription, dict):
            raise CortexProtocolError(f"subscribe returned an invalid result: {subscription}")
        failures = subscription.get("failure")
        if failures:
            raise EmotivError(f"Cortex rejected EEG subscription: {failures}")
        successes = subscription.get("success")
        matches = (
            [item for item in successes if isinstance(item, dict) and item.get("streamName") == "eeg"]
            if isinstance(successes, list)
            else []
        )
        if len(matches) != 1 or not isinstance(matches[0].get("cols"), list):
            raise CortexProtocolError(f"subscribe returned no unique EEG cols: {subscription}")
        return StreamParser(matches[0]["cols"])

    def marker_backend(self) -> Any:
        if not self.config.markers_enabled:
            from video_eeg.utils.markers import NoOpMarkerBackend

            return NoOpMarkerBackend()
        return EmotivCortexMarkerBackend(
            self.client,
            token=self.token,
            session_id=self.session_id,
            clock=self.clock,
            enabled=True,
        )

    def start_stream(self) -> None:
        if self._started:
            raise EmotivError("EMOTIV EEG stream is already started")
        if self.config.markers_enabled and not self.config.record_enabled:
            raise EmotivConfigurationError("Cortex markers require record.enabled=true")
        if self.config.clock_sync_enabled:
            self.clock.synchronize(self.client, str(self.headset["id"]))
        elif self.config.markers_enabled:
            raise EmotivConfigurationError("Cortex markers require clock_sync.enabled=true")
        if self.config.record_enabled:
            self.record_manager.start(self.config.record_title)
        self._stop_event.clear()
        self._stream_error = None
        self._stream_thread = threading.Thread(
            target=self._consume_stream, name="emotiv-eeg-stream", daemon=True
        )
        self._stream_thread.start()
        self._started = True

    def _consume_stream(self) -> None:
        try:
            while not self._stop_event.is_set():
                packet = self.client.next_stream_packet("eeg", timeout_sec=0.2)
                if packet is None:
                    continue
                if packet.get("sid") != self.session_id:
                    raise CortexProtocolError(
                        f"EEG packet session mismatch: expected={self.session_id}, actual={packet.get('sid')}"
                    )
                parsed = self.parser.parse(packet)
                self._auxiliary_latest = parsed.auxiliary
                self._update_quality_statistics(parsed.auxiliary)
                self.buffer.append(parsed.eeg, parsed.timestamp)
        except BaseException as exc:
            if not self._stop_event.is_set():
                self._stream_error = exc

    def _update_quality_statistics(self, auxiliary: dict[str, Any]) -> None:
        self._sample_count += 1
        interpolated = auxiliary.get("INTERPOLATED")
        if interpolated not in (None, 0, 1):
            raise CortexProtocolError(f"Invalid INTERPOLATED value: {interpolated!r}")
        if interpolated == 1:
            self._interpolated_count += 1
        counter = auxiliary.get("COUNTER")
        if counter is None:
            return
        if not isinstance(counter, (int, float)) or int(counter) != counter:
            raise CortexProtocolError(f"Invalid COUNTER value: {counter!r}")
        current = int(counter)
        if self._previous_counter is not None:
            expected = (self._previous_counter + 1) % int(self.metadata.sfreq)
            if current != expected:
                self._counter_discontinuities += 1
        self._previous_counter = current

    def stop_stream(self) -> None:
        if not self._started:
            raise EmotivError("EMOTIV EEG stream is not started")
        self._stop_event.set()
        assert self._stream_thread is not None
        self._stream_thread.join(timeout=2.0)
        if self._stream_thread.is_alive():
            raise EmotivError("EMOTIV EEG stream thread did not stop")
        self._stream_thread = None
        self._raise_stream_error()
        if self.record_manager.record_id is not None:
            self.record_manager.stop()
        self.client.request(
            "unsubscribe",
            {"cortexToken": self.token, "session": self.session_id, "streams": ["eeg"]},
        )
        self.client.request(
            "updateSession",
            {"cortexToken": self.token, "session": self.session_id, "status": "close"},
        )
        self.client.close()
        self._started = False

    def _raise_stream_error(self) -> None:
        self.client.raise_if_failed()
        if self._stream_error is not None:
            raise EmotivError(f"EMOTIV EEG stream failed: {self._stream_error}") from self._stream_error

    def get_new_samples(self) -> EEGChunk:
        self._raise_stream_error()
        return self.buffer.read_new()

    def get_chunk(self, window_sec: float) -> EEGChunk:
        if window_sec <= 0:
            raise ValueError("window_sec must be positive")
        self._raise_stream_error()
        return self.buffer.latest(max(1, int(self.metadata.sfreq * window_sec)))

    @property
    def runtime_metadata(self) -> dict[str, Any]:
        return {
            "headset_id": self.headset["id"],
            "model": self.profile.name,
            "channel_names": list(self.parser.channel_names),
            "auxiliary_channel_names": list(self.parser.auxiliary_names),
            "clock_adjustment_sec": self.clock.adjustment_sec,
            "cortex_record_id": self.record_manager.last_record_id,
            "latest_auxiliary": dict(self._auxiliary_latest),
            "quality_statistics": {
                "sample_count": self._sample_count,
                "interpolated_count": self._interpolated_count,
                "interpolated_ratio": (
                    self._interpolated_count / self._sample_count
                    if self._sample_count
                    else None
                ),
                "counter_discontinuities": self._counter_discontinuities,
            },
        }
