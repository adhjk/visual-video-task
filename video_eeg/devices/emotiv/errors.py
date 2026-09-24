"""Explicit failures raised by the EMOTIV Cortex backend."""


class EmotivError(RuntimeError):
    """Base error for a failed or invalid Cortex operation."""


class CortexProtocolError(EmotivError):
    """Cortex returned malformed data or a JSON-RPC error."""


class EmotivConfigurationError(EmotivError):
    """The requested EMOTIV configuration is invalid."""
