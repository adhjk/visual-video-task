"""Dynamic Cortex EEG stream parsing based on subscribe labels."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from .errors import CortexProtocolError

AUXILIARY_LABELS = frozenset({"COUNTER", "INTERPOLATED", "RAW_CQ", "MARKER_HARDWARE", "MARKERS"})


@dataclass(frozen=True, slots=True)
class ParsedSample:
    eeg: np.ndarray
    timestamp: float
    auxiliary: dict[str, Any]


class StreamParser:
    def __init__(self, labels: list[str]) -> None:
        if not labels or not all(isinstance(label, str) and label for label in labels):
            raise CortexProtocolError("Cortex EEG subscription returned invalid cols")
        if len(set(labels)) != len(labels):
            raise CortexProtocolError(f"Cortex EEG cols contain duplicates: {labels}")
        self.labels = tuple(labels)
        self.channel_names = tuple(label for label in labels if label not in AUXILIARY_LABELS)
        self.auxiliary_names = tuple(label for label in labels if label in AUXILIARY_LABELS)
        if not self.channel_names:
            raise CortexProtocolError(f"Cortex EEG cols contain no EEG channels: {labels}")
        self._channel_indexes = tuple(labels.index(label) for label in self.channel_names)
        self._aux_indexes = {label: labels.index(label) for label in self.auxiliary_names}

    def parse(self, packet: dict[str, Any]) -> ParsedSample:
        values = packet.get("eeg")
        timestamp = packet.get("time")
        if not isinstance(values, list) or len(values) != len(self.labels):
            raise CortexProtocolError(
                f"EEG packet length does not match subscription cols: values={len(values) if isinstance(values, list) else type(values).__name__}, cols={len(self.labels)}"
            )
        if not isinstance(timestamp, (int, float)):
            raise CortexProtocolError(f"EEG packet has invalid Cortex timestamp: {timestamp!r}")
        try:
            eeg = np.asarray([values[index] for index in self._channel_indexes], dtype=np.float64)
        except (TypeError, ValueError) as exc:
            raise CortexProtocolError("EEG packet contains a non-numeric channel value") from exc
        if not np.all(np.isfinite(eeg)):
            raise CortexProtocolError("EEG packet contains a non-finite channel value")
        return ParsedSample(
            eeg=eeg,
            timestamp=float(timestamp),
            auxiliary={label: values[index] for label, index in self._aux_indexes.items()},
        )
