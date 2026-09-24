"""Bounded, thread-safe buffer for parsed EEG samples."""

from __future__ import annotations

import threading
from collections import deque

import numpy as np


class EEGBuffer:
    def __init__(self, *, channels: int, capacity: int) -> None:
        if channels <= 0 or capacity <= 0:
            raise ValueError("EEG buffer channels and capacity must be positive")
        self._channels = channels
        self._samples: deque[np.ndarray] = deque(maxlen=capacity)
        self._timestamps: deque[float] = deque(maxlen=capacity)
        self._new_samples: deque[np.ndarray] = deque()
        self._new_timestamps: deque[float] = deque()
        self._lock = threading.Lock()

    def append(self, sample: np.ndarray, timestamp: float) -> None:
        if sample.shape != (self._channels,):
            raise ValueError(f"Unexpected EMOTIV sample shape: {sample.shape}")
        with self._lock:
            self._samples.append(sample.copy())
            self._timestamps.append(timestamp)
            self._new_samples.append(sample.copy())
            self._new_timestamps.append(timestamp)

    def read_new(self) -> tuple[np.ndarray, np.ndarray]:
        with self._lock:
            if not self._new_samples:
                return np.empty((self._channels, 0), dtype=np.float64), np.empty(0, dtype=np.float64)
            samples = np.column_stack(self._new_samples)
            timestamps = np.asarray(self._new_timestamps, dtype=np.float64)
            self._new_samples.clear()
            self._new_timestamps.clear()
            return samples, timestamps

    def latest(self, count: int) -> tuple[np.ndarray, np.ndarray]:
        with self._lock:
            samples = list(self._samples)[-count:]
            timestamps = list(self._timestamps)[-count:]
        if not samples:
            return np.empty((self._channels, 0), dtype=np.float64), np.empty(0, dtype=np.float64)
        return np.column_stack(samples), np.asarray(timestamps, dtype=np.float64)
