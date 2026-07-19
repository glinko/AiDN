"""Windows Named Pipe transport for authenticated RFC-0054 Local IPC events."""

import json
import os
from collections.abc import Callable
from multiprocessing.connection import Client, Listener
from threading import Event, Thread
from typing import Any

from pydantic import BaseModel

from aidn_hypervisor.dispatcher import NetworkMessage
from aidn_hypervisor.runtime_protocol.service import RuntimeProtocolError


class WindowsNamedPipeRuntimeListener:
    """Accept bounded JSON envelopes and route them through Local IPC ingress."""

    def __init__(
        self,
        *,
        address: str,
        authkey: bytes,
        ingress: Callable[[NetworkMessage], object],
        maximum_message_bytes: int = 1_048_576,
    ) -> None:
        if os.name != "nt":
            raise RuntimeError("Windows Named Pipe transport requires Windows")
        if not address.startswith("\\\\.\\pipe\\"):
            raise ValueError("Named Pipe address must use the \\.\\pipe\\ prefix")
        if not authkey:
            raise ValueError("Named Pipe authkey must not be empty")
        if maximum_message_bytes <= 0:
            raise ValueError("maximum_message_bytes must be positive")
        self.address = address
        self.authkey = authkey
        self.ingress = ingress
        self.maximum_message_bytes = maximum_message_bytes
        self._listener: Listener | None = None
        self._stop = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("Named Pipe listener is already started")
        self._listener = Listener(self.address, family="AF_PIPE", authkey=self.authkey)
        self._thread = Thread(target=self._serve, name="aidn-runtime-named-pipe", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        listener = self._listener
        if listener is not None:
            listener.close()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=5)
        self._listener = None
        self._thread = None

    def _serve(self) -> None:
        listener = self._listener
        if listener is None:
            return
        while not self._stop.is_set():
            try:
                connection = listener.accept()
            except (OSError, EOFError):
                break
            with connection:
                while not self._stop.is_set():
                    try:
                        payload = connection.recv_bytes(self.maximum_message_bytes)
                    except EOFError:
                        break
                    response = self._handle_payload(payload)
                    try:
                        connection.send_bytes(json.dumps(response, separators=(",", ":")).encode("utf-8"))
                    except (BrokenPipeError, EOFError, OSError):
                        break

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


class WindowsNamedPipeRuntimeClient:
    """Small byte-oriented client for Runtime Adapter Local IPC profiles."""

    def __init__(self, *, address: str, authkey: bytes) -> None:
        self.address = address
        self.authkey = authkey

    def send(self, message: NetworkMessage) -> dict[str, Any]:
        with Client(self.address, family="AF_PIPE", authkey=self.authkey) as connection:
            connection.send_bytes(message.model_dump_json().encode("utf-8"))
            return json.loads(connection.recv_bytes().decode("utf-8"))
