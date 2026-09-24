"""Cortex native record lifecycle."""

from __future__ import annotations

from .cortex_client import CortexClient
from .errors import CortexProtocolError, EmotivError


class RecordManager:
    def __init__(self, client: CortexClient, *, token: str, session_id: str) -> None:
        self._client = client
        self._token = token
        self._session_id = session_id
        self.record_id: str | None = None
        self.last_record_id: str | None = None

    def start(self, title: str) -> str:
        if self.record_id is not None:
            raise EmotivError("Cortex record is already running")
        result = self._client.request(
            "createRecord",
            {"cortexToken": self._token, "session": self._session_id, "title": title},
        )
        record = result.get("record") if isinstance(result, dict) else None
        record_id = record.get("uuid") if isinstance(record, dict) else None
        if not isinstance(record_id, str) or not record_id:
            raise CortexProtocolError(f"createRecord returned no record uuid: {result}")
        self.record_id = record_id
        self.last_record_id = record_id
        return record_id

    def stop(self) -> None:
        if self.record_id is None:
            raise EmotivError("Cortex record is not running")
        self._client.request(
            "stopRecord", {"cortexToken": self._token, "session": self._session_id}
        )
        self.record_id = None
