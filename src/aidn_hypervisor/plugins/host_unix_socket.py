"""Unix domain socket transport for bounded Plugin Host local IPC envelopes."""

import os
import socket
import struct
from pathlib import Path
from threading import Event, Thread

from aidn_hypervisor.plugins.host import PluginHostJsonWireAdapter


class UnixSocketPluginHostListener:
    def __init__(self, *, address: str, wire_adapter: PluginHostJsonWireAdapter) -> None:
        if os.name == "nt":
            raise RuntimeError("Unix domain socket transport is unavailable on Windows")
        self.address = address
        self.wire_adapter = wire_adapter
        self._server: socket.socket | None = None
        self._stop = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("Plugin Host Unix socket listener is already started")
        if Path(self.address).exists():
            raise FileExistsError(f"Unix socket address already exists: {self.address}")
        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.bind(self.address)
        self._server.listen()
        self._thread = Thread(target=self._serve, name="aidn-plugin-host-unix", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._server is not None:
            self._server.close()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._server = None
        self._thread = None
        Path(self.address).unlink(missing_ok=True)

    def _serve(self) -> None:
        if self._server is None:
            return
        while not self._stop.is_set():
            try:
                connection, _ = self._server.accept()
            except OSError:
                break
            with connection:
                try:
                    payload = self._receive_frame(connection)
                    self._send_frame(connection, self.wire_adapter.receive_bytes(payload))
                except OSError:
                    continue

    def _receive_frame(self, connection: socket.socket) -> bytes:
        length = struct.unpack("!I", self._receive_exact(connection, 4))[0]
        if length > self.wire_adapter.maximum_message_bytes:
            raise OSError("Plugin Host frame exceeds configured limit")
        return self._receive_exact(connection, length)

    @staticmethod
    def _receive_exact(connection: socket.socket, length: int) -> bytes:
        data = b""
        while len(data) < length:
            chunk = connection.recv(length - len(data))
            if not chunk:
                raise OSError("Plugin Host socket closed")
            data += chunk
        return data

    @staticmethod
    def _send_frame(connection: socket.socket, payload: bytes) -> None:
        connection.sendall(struct.pack("!I", len(payload)) + payload)


class UnixSocketPluginHostClient:
    def __init__(self, *, address: str) -> None:
        self.address = address

    def send(self, payload: bytes) -> bytes:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.connect(self.address)
            UnixSocketPluginHostListener._send_frame(connection, payload)
            length = struct.unpack("!I", UnixSocketPluginHostListener._receive_exact(connection, 4))[0]
            return UnixSocketPluginHostListener._receive_exact(connection, length)
