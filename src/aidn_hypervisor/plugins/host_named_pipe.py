"""Windows Named Pipe transport for bounded Plugin Host local IPC envelopes."""

import os
from multiprocessing.connection import Client, Listener
from threading import Event, Thread

from aidn_hypervisor.plugins.host import PluginHostJsonWireAdapter


class WindowsNamedPipePluginHostListener:
    def __init__(self, *, address: str, authkey: bytes, wire_adapter: PluginHostJsonWireAdapter) -> None:
        if os.name != "nt":
            raise RuntimeError("Windows Named Pipe transport requires Windows")
        if not address.startswith("\\\\.\\pipe\\"):
            raise ValueError("Named Pipe address must use the \\.\\pipe\\ prefix")
        if not authkey:
            raise ValueError("Named Pipe authkey must not be empty")
        self.address = address
        self.authkey = authkey
        self.wire_adapter = wire_adapter
        self._listener: Listener | None = None
        self._stop = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("Plugin Host Named Pipe listener is already started")
        self._listener = Listener(self.address, family="AF_PIPE", authkey=self.authkey)
        self._thread = Thread(target=self._serve, name="aidn-plugin-host-pipe", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._listener is not None:
            self._listener.close()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._listener = None
        self._thread = None

    def _serve(self) -> None:
        if self._listener is None:
            return
        while not self._stop.is_set():
            try:
                connection = self._listener.accept()
            except (OSError, EOFError):
                break
            with connection:
                try:
                    payload = connection.recv_bytes(self.wire_adapter.maximum_message_bytes)
                    connection.send_bytes(self.wire_adapter.receive_bytes(payload))
                except (OSError, EOFError):
                    continue


class WindowsNamedPipePluginHostClient:
    def __init__(self, *, address: str, authkey: bytes) -> None:
        self.address = address
        self.authkey = authkey

    def send(self, payload: bytes) -> bytes:
        with Client(self.address, family="AF_PIPE", authkey=self.authkey) as connection:
            connection.send_bytes(payload)
            return connection.recv_bytes()
