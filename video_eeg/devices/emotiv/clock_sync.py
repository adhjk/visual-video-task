"""Application monotonic clock to Cortex headset clock conversion."""

from __future__ import annotations

import time
from dataclasses import dataclass

from .cortex_client import CortexClient
from .errors import CortexProtocolError, EmotivError


@dataclass(slots=True)
class ClockSync:
    adjustment_sec: float | None = None

    def synchronize(self, client: CortexClient, headset_id: str) -> float:
        monotonic_time = time.monotonic()
        system_time = time.time()
        result = client.request(
            "syncWithHeadsetClock",
            {"headset": headset_id, "monotonicTime": monotonic_time, "systemTime": system_time},
        )
        if not isinstance(result, dict) or result.get("headset") != headset_id:
            raise CortexProtocolError(f"Invalid syncWithHeadsetClock result: {result}")
        adjustment = result.get("adjustment")
        if not isinstance(adjustment, (int, float)):
            raise CortexProtocolError(f"Clock adjustment is not numeric: {adjustment!r}")
        self.adjustment_sec = float(adjustment)
        return self.adjustment_sec

    def cortex_time_ms(self, monotonic_time: float) -> float:
        if self.adjustment_sec is None:
            raise EmotivError("Cortex clock has not been synchronized")
        return (float(monotonic_time) + self.adjustment_sec) * 1000.0
