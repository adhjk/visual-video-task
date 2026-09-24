"""Behavior-only device profiles; runtime metadata remains authoritative."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import EmotivConfigurationError


@dataclass(frozen=True, slots=True)
class DeviceProfile:
    name: str
    family: str
    requires_mapping: bool


DEVICE_PROFILES = {
    "epoc_x": DeviceProfile("epoc_x", "epoc", False),
    "insight": DeviceProfile("insight", "insight", False),
    "epoc_flex": DeviceProfile("epoc_flex", "flex", True),
    "flex_2": DeviceProfile("flex_2", "flex", True),
}


def detect_model(headset: dict[str, object]) -> str:
    """Resolve only model identities exposed by Cortex headset identifiers."""

    headset_id = str(headset.get("id", "")).upper()
    if headset_id.startswith("INSIGHT-"):
        return "insight"
    if headset_id.startswith(("EPOCPLUS-", "EPOCX-")):
        return "epoc_x"
    if headset_id.startswith("EPOCFLEX-"):
        return "epoc_flex"
    if headset_id.startswith("FLEX-"):
        return "flex_2"
    raise EmotivConfigurationError(
        f"Cannot identify a supported EMOTIV model from headset id {headset_id!r}"
    )


def resolve_profile(configured_model: str, headset: dict[str, object]) -> DeviceProfile:
    configured = configured_model.strip().lower()
    if configured not in {"auto", *DEVICE_PROFILES}:
        raise EmotivConfigurationError(f"Unsupported EMOTIV model: {configured!r}")
    detected = detect_model(headset)
    if configured != "auto" and configured != detected:
        raise EmotivConfigurationError(
            f"Configured EMOTIV model {configured!r} does not match detected model {detected!r}"
        )
    return DEVICE_PROFILES[detected]
