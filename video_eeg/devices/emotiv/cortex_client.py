"""Synchronous JSON-RPC client with a dedicated Cortex receive loop."""

from __future__ import annotations

import json
import queue
import ssl
import threading
import time
from typing import Any

from .errors import CortexProtocolError, EmotivError


class CortexClient:
    def __init__(self, url: str, *, request_timeout_sec: float) -> None:
        self.url = url
        self.request_timeout_sec = request_timeout_sec
        self._socket: Any | None = None
        self._reader: threading.Thread | None = None
        self._send_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._next_id = 1
        self._pending: dict[int, queue.Queue[dict[str, Any]]] = {}
        self._streams: dict[str, queue.Queue[dict[str, Any]]] = {}
        self._reader_error: BaseException | None = None
        self._closed = threading.Event()

    def open(self) -> None:
        if self._socket is not None:
            raise EmotivError("Cortex WebSocket is already open")
        try:
            import websocket
        except ImportError as exc:
            raise EmotivError("websocket-client is required for EMOTIV Cortex") from exc
        # Cortex documents a self-signed certificate on localhost.
        self._socket = websocket.create_connection(
            self.url,
            timeout=self.request_timeout_sec,
            sslopt={"cert_reqs": ssl.CERT_NONE},
        )
        self._closed.clear()
        self._reader_error = None
        self._reader = threading.Thread(target=self._read_loop, name="emotiv-cortex-reader", daemon=True)
        self._reader.start()

    def request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        self.raise_if_failed()
        if self._socket is None:
            raise EmotivError("Cortex WebSocket is not open")
        response_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        with self._state_lock:
            request_id = self._next_id
            self._next_id += 1
            self._pending[request_id] = response_queue
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            payload["params"] = params
        try:
            with self._send_lock:
                self._socket.send(json.dumps(payload, separators=(",", ":")))
            response = response_queue.get(timeout=self.request_timeout_sec)
        except queue.Empty as exc:
            self.raise_if_failed()
            raise EmotivError(f"Timed out waiting for Cortex method {method}") from exc
        finally:
            with self._state_lock:
                self._pending.pop(request_id, None)
        if "error" in response:
            error = response["error"]
            raise CortexProtocolError(f"Cortex method {method} failed: {error}")
        if "result" not in response:
            raise CortexProtocolError(f"Cortex method {method} returned no result: {response}")
        return response["result"]

    def next_stream_packet(self, stream: str, *, timeout_sec: float) -> dict[str, Any] | None:
        self.raise_if_failed()
        stream_queue = self._streams.setdefault(stream, queue.Queue())
        try:
            return stream_queue.get(timeout=timeout_sec)
        except queue.Empty:
            self.raise_if_failed()
            return None

    def close(self) -> None:
        self._closed.set()
        sock, self._socket = self._socket, None
        if sock is not None:
            sock.close()
        if self._reader is not None:
            self._reader.join(timeout=2.0)
            if self._reader.is_alive():
                raise EmotivError("Cortex reader thread did not stop")
            self._reader = None

    def raise_if_failed(self) -> None:
        if self._reader_error is not None:
            raise EmotivError(f"Cortex receive loop failed: {self._reader_error}") from self._reader_error

    def _read_loop(self) -> None:
        assert self._socket is not None
        try:
            while not self._closed.is_set():
                message = json.loads(self._socket.recv())
                if not isinstance(message, dict):
                    raise CortexProtocolError(f"Cortex message is not an object: {message!r}")
                if "id" in message:
                    request_id = message["id"]
                    with self._state_lock:
                        target = self._pending.get(request_id)
                    if target is None:
                        raise CortexProtocolError(f"Cortex returned unknown request id {request_id!r}")
                    target.put_nowait(message)
                    continue
                stream_names = [name for name in self._streams if name in message]
                if stream_names:
                    for name in stream_names:
                        self._streams[name].put_nowait(message)
                    continue
                # Asynchronous warnings are not request results or samples. They
                # remain observable through this queue instead of being discarded.
                if "warning" in message:
                    self._streams.setdefault("warning", queue.Queue()).put_nowait(message)
                    continue
                raise CortexProtocolError(f"Unrecognized asynchronous Cortex message: {message}")
        except BaseException as exc:
            if not self._closed.is_set():
                self._reader_error = exc

    def register_stream(self, stream: str) -> None:
        if stream in self._streams:
            raise EmotivError(f"Cortex stream {stream!r} is already registered")
        self._streams[stream] = queue.Queue()


def authenticate(client: CortexClient, *, client_id: str, client_secret: str) -> str:
    access = client.request("requestAccess", {"clientId": client_id, "clientSecret": client_secret})
    if not isinstance(access, dict) or access.get("accessGranted") is not True:
        message = access.get("message") if isinstance(access, dict) else access
        raise EmotivError(f"EMOTIV Launcher has not granted application access: {message}")
    authorization = client.request("authorize", {"clientId": client_id, "clientSecret": client_secret})
    if not isinstance(authorization, dict) or not isinstance(authorization.get("cortexToken"), str):
        raise CortexProtocolError(f"Cortex authorize returned an invalid result: {authorization}")
    return authorization["cortexToken"]


def select_headset(headsets: Any, configured_id: str) -> dict[str, Any]:
    if not isinstance(headsets, list) or not all(isinstance(item, dict) for item in headsets):
        raise CortexProtocolError(f"queryHeadsets returned an invalid result: {headsets}")
    if configured_id != "auto":
        matches = [item for item in headsets if item.get("id") == configured_id]
        if len(matches) != 1:
            available = [item.get("id") for item in headsets]
            raise EmotivError(f"Configured headset {configured_id!r} was not found; available={available}")
        return matches[0]
    if len(headsets) != 1:
        available = [item.get("id") for item in headsets]
        raise EmotivError(f"headset_id=auto requires exactly one headset; available={available}")
    return headsets[0]


def wait_until_connected(
    client: CortexClient,
    headset_id: str,
    *,
    timeout_sec: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        result = client.request("queryHeadsets", {"id": headset_id, "includeFlexMappings": True})
        headset = select_headset(result, headset_id)
        if headset.get("status") == "connected":
            return headset
        time.sleep(0.2)
    raise EmotivError(f"Timed out waiting for Cortex to connect headset {headset_id}")
