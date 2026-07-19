"""Mutually authenticated TLS transport for remote RFC-0054 Runtime events."""

import json
import socket
import ssl
import struct
from collections.abc import Callable
from threading import Event, Thread
from typing import Any

from pydantic import BaseModel

from aidn_hypervisor.dispatcher import NetworkMessage
from aidn_hypervisor.runtime_protocol.service import RuntimeProtocolError


class TlsRuntimeListener:
    """Accept mTLS length-prefixed JSON Runtime envelopes on a TCP listener."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        server_context: ssl.SSLContext,
        ingress: Callable[[NetworkMessage], object],
        maximum_message_bytes: int = 1_048_576,
    ) -> None:
        if not host:
            raise ValueError("TLS Runtime host must not be empty")
        if not 0 <= port <= 65535:
            raise ValueError("TLS Runtime port must be in range 0..65535")
        if server_context.verify_mode != ssl.CERT_REQUIRED:
            raise ValueError("TLS Runtime server context must require client certificates")
        if server_context.minimum_version < ssl.TLSVersion.TLSv1_2:
            raise ValueError("TLS Runtime server context must require TLS 1.2 or newer")
        if maximum_message_bytes <= 0:
            raise ValueError("maximum_message_bytes must be positive")
        self.host = host
        self.port = port
        self.server_context = server_context
        self.ingress = ingress
        self.maximum_message_bytes = maximum_message_bytes
        self._server: socket.socket | None = None
        self._stop = Event()
        self._thread: Thread | None = None

    @property
    def address(self) -> tuple[str, int]:
        return self.host, self.port

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("TLS Runtime listener is already started")
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((self.host, self.port))
        server.listen()
        self.host, self.port = server.getsockname()
        self._server = server
        self._thread = Thread(target=self._serve, name="aidn-runtime-tls", daemon=True)
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

    def _serve(self) -> None:
        server = self._server
        if server is None:
            return
        while not self._stop.is_set():
            try:
                raw_connection, _ = server.accept()
            except OSError:
                break
            try:
                connection = self.server_context.wrap_socket(raw_connection, server_side=True)
            except ssl.SSLError:
                raw_connection.close()
                continue
            with connection:
                while not self._stop.is_set():
                    try:
                        payload = self._receive_frame(connection)
                    except (ConnectionError, OSError, ssl.SSLError):
                        break
                    response = json.dumps(self._handle_payload(payload), separators=(",", ":")).encode("utf-8")
                    try:
                        self._send_frame(connection, response)
                    except (ConnectionError, OSError, ssl.SSLError):
                        break

    def _receive_frame(self, connection: socket.socket) -> bytes:
        header = self._receive_exact(connection, 4)
        length = struct.unpack("!I", header)[0]
        if length > self.maximum_message_bytes:
            raise ConnectionError("Runtime TLS frame exceeds configured limit")
        return self._receive_exact(connection, length)

    @staticmethod
    def _receive_exact(connection: socket.socket, length: int) -> bytes:
        chunks: list[bytes] = []
        remaining = length
        while remaining:
            chunk = connection.recv(remaining)
            if not chunk:
                raise ConnectionError("Runtime TLS connection closed")
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
            return {"ok": False, "error": "RUNTIME_REMOTE_TLS_INVALID", "message": str(exc)}
        return {"ok": True, "result": self._json_value(result)}

    @staticmethod
    def _json_value(value: object) -> object:
        if isinstance(value, BaseModel):
            return value.model_dump(mode="json")
        return value


class TlsRuntimeClient:
    """mTLS client for remote Runtime Adapter profiles."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        client_context: ssl.SSLContext,
        server_hostname: str,
        maximum_message_bytes: int = 1_048_576,
    ) -> None:
        if not host:
            raise ValueError("TLS Runtime host must not be empty")
        if not 0 <= port <= 65535:
            raise ValueError("TLS Runtime port must be in range 0..65535")
        if client_context.verify_mode != ssl.CERT_REQUIRED:
            raise ValueError("TLS Runtime client context must verify server certificates")
        if client_context.minimum_version < ssl.TLSVersion.TLSv1_2:
            raise ValueError("TLS Runtime client context must require TLS 1.2 or newer")
        if not server_hostname:
            raise ValueError("TLS Runtime server hostname must not be empty")
        if maximum_message_bytes <= 0:
            raise ValueError("maximum_message_bytes must be positive")
        self.host = host
        self.port = port
        self.client_context = client_context
        self.server_hostname = server_hostname
        self.maximum_message_bytes = maximum_message_bytes

    def send(self, message: NetworkMessage) -> dict[str, Any]:
        with socket.create_connection((self.host, self.port)) as raw_connection:
            with self.client_context.wrap_socket(
                raw_connection,
                server_hostname=self.server_hostname,
            ) as connection:
                payload = message.model_dump_json().encode("utf-8")
                TlsRuntimeListener._send_frame(connection, payload)
                header = TlsRuntimeListener._receive_exact(connection, 4)
                response_length = struct.unpack("!I", header)[0]
                if response_length > self.maximum_message_bytes:
                    raise ConnectionError("Runtime TLS response exceeds configured limit")
                response = TlsRuntimeListener._receive_exact(connection, response_length)
        return json.loads(response.decode("utf-8"))
