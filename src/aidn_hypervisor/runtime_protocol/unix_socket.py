"""Unix domain socket transport for authenticated RFC-0054 Local IPC events."""

import contextlib
import json
import os
import socket
import struct
from collections.abc import Callable
from pathlib import Path
from threading import Event, Thread
from typing import Any

from pydantic import BaseModel

from aidn_hypervisor.dispatcher import NetworkMessage
from aidn_hypervisor.runtime_protocol.service import RuntimeProtocolError


class UnixSocketRuntimeListener:
    """Accept length-prefixed JSON envelopes and route them through Local IPC ingress."""

    def __init__(
        self,
        *,
        address: str,
        ingress: Callable[[NetworkMessage], object],
        maximum_message_bytes: int = 1_048_576,
    ) -> None:
        if os.name == "nt":
            raise RuntimeError("Unix domain socket transport is unavailable on Windows")
        if not address:
            raise ValueError("Unix socket address must not be empty")
        if maximum_message_bytes <= 0:
            raise ValueError("maximum_message_bytes must be positive")
        self.address = address
        self.ingress = ingress
        self.maximum_message_bytes = maximum_message_bytes
        self._server: socket.socket | None = None
        self._stop = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("Unix socket listener is already started")
        path = Path(self.address)
        if path.exists():
            raise FileExistsError(f"Unix socket address already exists: {path}")
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(self.address)
        server.listen()
        self._server = server
        self._thread = Thread(target=self._serve, name="aidn-runtime-unix-socket", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        server = self._server
        if server is not None:
            server.close()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=5)
        self._server = None
        self._thread = None
        with contextlib.suppress(FileNotFoundError):
            Path(self.address).unlink()

    def _serve(self) -> None:
        server = self._server
        if server is None:
            return
        while not self._stop.is_set():
            try:
                connection, _ = server.accept()
            except OSError:
                break
            with connection:
                while not self._stop.is_set():
                    try:
                        payload = self._receive_frame(connection)
                    except (ConnectionError, OSError):
                        break
                    response = json.dumps(self._handle_payload(payload), separators=(",", ":")).encode("utf-8")
                    try:
                        self._send_frame(connection, response)
                    except (ConnectionError, OSError):
                        break

    def _receive_frame(self, connection: socket.socket) -> bytes:
        header = self._receive_exact(connection, 4)
        length = struct.unpack("!I", header)[0]
        if length > self.maximum_message_bytes:
            raise ConnectionError("Runtime Local IPC frame exceeds configured limit")
        return self._receive_exact(connection, length)

    @staticmethod
    def _receive_exact(connection: socket.socket, length: int) -> bytes:
        chunks: list[bytes] = []
        remaining = length
        while remaining:
            chunk = connection.recv(remaining)
            if not chunk:
                raise ConnectionError("Runtime Local IPC connection closed")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    @staticmethod
    def _send_frame(connection: socket.socket, payload: bytes) -> None:
        connection.sendall(struct.pack("!I", len(payload)) + payload)

    def _handle_payload(self, payload: bytes) -> dict[str, Any]:
        if len(payload) > self.maximum_message_bytes:
            return {"ok": False, "error": "MESSAGE_TOO_LARGE"}
        try:
            message = NetworkMessage.model_validate_json(payload)
            result = self.ingress(message)
        except RuntimeProtocolError as exc:
            return {"ok": False, "error": exc.code, "message": str(exc)}
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            return {"ok": False, "error": "RUNTIME_LOCAL_IPC_INVALID", "message": str(exc)}
        return {"ok": True, "result": self._json_value(result)}

    @staticmethod
    def _json_value(value: object) -> object:
        if isinstance(value, BaseModel):
            return value.model_dump(mode="json")
        return value


class UnixSocketRuntimeClient:
    """Small length-prefixed JSON client for Unix Runtime Adapter profiles."""

    def __init__(self, *, address: str, maximum_message_bytes: int = 1_048_576) -> None:
        if maximum_message_bytes <= 0:
            raise ValueError("maximum_message_bytes must be positive")
        self.address = address
        self.maximum_message_bytes = maximum_message_bytes

    def send(self, message: NetworkMessage) -> dict[str, Any]:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.connect(self.address)
            payload = message.model_dump_json().encode("utf-8")
            UnixSocketRuntimeListener._send_frame(connection, payload)
            header = UnixSocketRuntimeListener._receive_exact(connection, 4)
            response_length = struct.unpack("!I", header)[0]
            if response_length > self.maximum_message_bytes:
                raise ConnectionError("Runtime Local IPC response exceeds configured limit")
            response = UnixSocketRuntimeListener._receive_exact(
                connection,
                response_length,
            )
        return json.loads(response.decode("utf-8"))
