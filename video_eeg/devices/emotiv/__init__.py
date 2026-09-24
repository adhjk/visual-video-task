"""Unified EMOTIV Cortex acquisition package."""

from .acquirer import EmotivAcquirer
from .marker_backend import EmotivCortexMarkerBackend

__all__ = ["EmotivAcquirer", "EmotivCortexMarkerBackend"]
