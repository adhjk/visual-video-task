"""Cortex marker backend shared by every supported EMOTIV profile."""

from __future__ import annotations

import time

from video_eeg.utils.markers import MarkerBackend

from .clock_sync import ClockSync
from .cortex_client import CortexClient
from .errors import EmotivError


class EmotivCortexMarkerBackend(MarkerBackend):
    def __init__(
        self,
        client: CortexClient,
        *,
        token: str,
        session_id: str,
        clock: ClockSync,
        enabled: bool,
    ) -> None:
        self._client = client
        self._token = token
        self._session_id = session_id
        self._clock = clock
        self._enabled = enabled

    def send(self, label: int, timestamp: float | None = None) -> None:
        self._inject(label, str(label), timestamp)

    def send_event(self, event_name: str, timestamp: float | None = None) -> None:
        from video_eeg.utils.markers import PROTOCOL_EVENT_CODES

        if event_name not in PROTOCOL_EVENT_CODES:
            raise ValueError(f"Unknown protocol event: {event_name}")
        self._inject(PROTOCOL_EVENT_CODES[event_name], event_name, timestamp)

    def _inject(self, value: int, label: str, timestamp: float | None) -> None:
        if not self._enabled:
            raise EmotivError("Cortex marker injection is disabled by configuration")
        monotonic_time = time.monotonic() if timestamp is None else float(timestamp)
        self._client.request(
            "injectMarker",
            {
                "cortexToken": self._token,
                "session": self._session_id,
                "time": self._clock.cortex_time_ms(monotonic_time),
                "value": int(value),
                "label": label,
                "port": "Software",
            },
        )
