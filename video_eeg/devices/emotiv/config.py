"""Strict EMOTIV configuration parsing."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import EmotivConfigurationError


@dataclass(frozen=True, slots=True)
class EmotivConfig:
    model: str
    headset_id: str
    client_id: str
    client_secret: str
    url: str
    request_timeout_sec: float
    discovery_timeout_sec: float
    buffer_sec: float
    expected_sfreq: float | None
    expected_channels: tuple[str, ...] | None
    mapping: dict[str, str] | None
    record_enabled: bool
    record_title: str
    markers_enabled: bool
    clock_sync_enabled: bool


def _required_environment(variable: str) -> str:
    value = os.environ.get(variable)
    if not value:
        raise EmotivConfigurationError(f"Required credential environment variable {variable} is not set")
    return value


def _load_mapping(
    path_value: object, mapping_profile: object, *, project_dir: Path
) -> dict[str, str] | None:
    if path_value is not None and mapping_profile is not None:
        raise EmotivConfigurationError("Set only one of mapping_file and mapping_profile")
    if mapping_profile is not None:
        profile = str(mapping_profile).strip()
        if not profile or Path(profile).name != profile:
            raise EmotivConfigurationError("mapping_profile must be a plain profile name")
        path_value = project_dir / "video_eeg" / "config" / "emotiv" / "mappings" / f"{profile}.yaml"
    if path_value is None:
        return None
    path = Path(str(path_value))
    if not path.is_absolute():
        path = project_dir / path
    if not path.is_file():
        raise EmotivConfigurationError(f"EMOTIV mapping file does not exist: {path}")
    try:
        import yaml
    except ImportError as exc:
        raise EmotivConfigurationError("PyYAML is required to load an EMOTIV mapping") from exc
    data = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict) or not data or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in data.items()
    ):
        raise EmotivConfigurationError(f"EMOTIV mapping must be a non-empty string mapping: {path}")
    if "CMS" not in data or "DRL" not in data:
        raise EmotivConfigurationError(f"EMOTIV Flex mapping must contain CMS and DRL: {path}")
    return dict(data)


def parse_config(raw: dict[str, Any], *, project_dir: Path, buffer_sec: float) -> EmotivConfig:
    if not isinstance(raw, dict):
        raise EmotivConfigurationError("device.emotiv must be a mapping")
    client_id_env = str(raw.get("client_id_env", "EMOTIV_CLIENT_ID"))
    client_secret_env = str(raw.get("client_secret_env", "EMOTIV_CLIENT_SECRET"))
    validation = raw.get("validation", {})
    if not isinstance(validation, dict):
        raise EmotivConfigurationError("device.emotiv.validation must be a mapping")
    expected_channels_raw = validation.get("expected_channels")
    expected_channels = None
    if expected_channels_raw is not None:
        if not isinstance(expected_channels_raw, list) or not expected_channels_raw or not all(
            isinstance(item, str) and item for item in expected_channels_raw
        ):
            raise EmotivConfigurationError("expected_channels must be a non-empty list of names or null")
        expected_channels = tuple(expected_channels_raw)
    expected_sfreq_raw = validation.get("expected_sfreq")
    expected_sfreq = None if expected_sfreq_raw is None else float(expected_sfreq_raw)
    if expected_sfreq is not None and expected_sfreq <= 0:
        raise EmotivConfigurationError("expected_sfreq must be positive or null")
    timeout = float(raw.get("request_timeout_sec", 10.0))
    discovery_timeout = float(raw.get("discovery_timeout_sec", 25.0))
    if timeout <= 0 or discovery_timeout <= 0 or buffer_sec <= 0:
        raise EmotivConfigurationError("EMOTIV timeouts and buffer_sec must be positive")
    record = raw.get("record", {})
    markers = raw.get("markers", {})
    clock_sync = raw.get("clock_sync", {})
    for name, value in (("record", record), ("markers", markers), ("clock_sync", clock_sync)):
        if not isinstance(value, dict):
            raise EmotivConfigurationError(f"device.emotiv.{name} must be a mapping")
    return EmotivConfig(
        model=str(raw.get("model", "auto")),
        headset_id=str(raw.get("headset_id", "auto")),
        client_id=_required_environment(client_id_env),
        client_secret=_required_environment(client_secret_env),
        url=str(raw.get("url", "wss://localhost:6868")),
        request_timeout_sec=timeout,
        discovery_timeout_sec=discovery_timeout,
        buffer_sec=float(buffer_sec),
        expected_sfreq=expected_sfreq,
        expected_channels=expected_channels,
        mapping=_load_mapping(
            raw.get("mapping_file"), raw.get("mapping_profile"), project_dir=project_dir
        ),
        record_enabled=bool(record.get("enabled", True)),
        record_title=str(record.get("title", "visual-video-task")),
        markers_enabled=bool(markers.get("enabled", True)),
        clock_sync_enabled=bool(clock_sync.get("enabled", True)),
    )
