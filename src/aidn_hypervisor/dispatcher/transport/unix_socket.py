"""Unix-domain-socket transport adapter for local IPC.

Implements the ``TransportGateway`` protocol over a Unix domain socket,
suitable for local hypervisor-to-runtime communication where both
endpoints run on the same host.

Wire format is length-prefixed JSON (``MessageFramer``) — one framed
message per ``send`` / ``receive`` call.
"""

from __future__ import annotations

import socket
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from aidn_hypervisor.dispatcher.models import NetworkMessage
from aidn_hypervisor.dispatcher.transport.abc import (
    MessageFramer,
    TransportGateway,
    TransportStatus,
)


# ---------------------------------------------------------------------------
# UnixSocketTransport
# ---------------------------------------------------------------------------

class UnixSocketTransport(TransportGateway):
    """TransportGateway implementation over a Unix domain socket.

    Parameters
    ----------
    socket_path : str
        Absolute filesystem path for the Unix socket.
    send_timeout : float
        Maximum seconds to block on ``send()``.  ``0`` means non-blocking.
    recv_timeout : float
        Maximum seconds to block on ``receive()``.  ``0`` means non-blocking.
    """

    def __init__(
        self,
        socket_path: str,
        *,
        send_timeout: float = 5.0,
        recv_timeout: float = 5.0,
    ) -> None:
        self._socket_path = socket_path
        self._send_timeout = send_timeout
        self._recv_timeout = recv_timeout
        self._socket: Optional[socket.socket] = None
        self._status = TransportStatus.DISCONNECTED
        self._lock = threading.Lock()
        self._recv_buffer: bytes = b""
        self._pending_messages: list[NetworkMessage] = []

    # -- lifecycle ----------------------------------------------------------

    def connect(self) -> None:
        """Create (if listening) or connect to the Unix socket at *socket_path*."""
        with self._lock:
            if self._status == TransportStatus.CONNECTED:
                return

            self._status = TransportStatus.CONNECTING
            try:
                self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                self._socket.settimeout(self._send_timeout)
                self._socket.connect(self._socket_path)
                self._socket.settimeout(self._recv_timeout)
                self._status = TransportStatus.CONNECTED
            except (OSError, ConnectionRefusedError, FileNotFoundError) as exc:
                self._status = TransportStatus.ERROR
                if self._socket:
                    self._socket.close()
                    self._socket = None
                raise ConnectionError(
                    f"cannot connect to Unix socket {self._socket_path!r}: {exc}"
                ) from exc

    def disconnect(self) -> None:
        """Gracefully close the Unix socket connection."""
        with self._lock:
            if self._socket is not None:
                try:
                    self._socket.shutdown(socket.SHUT_RDWR)
                except (OSError, Exception):
                    pass
                self._socket.close()
                self._socket = None
            self._status = TransportStatus.DISCONNECTED

    # -- messaging ----------------------------------------------------------

    def send(self, message: NetworkMessage) -> bytes:
        """Serialize and transmit a single ``NetworkMessage``.

        Returns the raw wire bytes that were written to the socket.

        Raises
        ------
        ConnectionError
            If the transport is not connected.
        """
        if self._status != TransportStatus.CONNECTED or self._socket is None:
            raise ConnectionError(
                "cannot send — transport is not connected "
                f"(status={self._status.value})"
            )

        wire = MessageFramer.encode(message)
        try:
            with self._lock:
                self._socket.sendall(wire)
        except (OSError, BrokenPipeError) as exc:
            self._status = TransportStatus.ERROR
            raise ConnectionError(f"send failed: {exc}") from exc

        return wire

    def receive(self) -> NetworkMessage | None:
        """Read and deserialize the next available framed message.

        Returns ``None`` when no complete message is available (e.g.
        non-blocking read with nothing pending).

        Incoming bytes are accumulated in an internal buffer so that
        multiple messages delivered in a single ``recv()`` are queued
        and returned one at a time across subsequent calls.
        """
        if self._status != TransportStatus.CONNECTED or self._socket is None:
            return None

        # Drain any previously buffered messages first
        if self._pending_messages:
            return self._pending_messages.pop(0)

        try:
            with self._lock:
                data = self._socket.recv(65536)
        except (OSError, ConnectionResetError):
            self._status = TransportStatus.ERROR
            return None

        if not data:
            # Peer closed the connection
            self._status = TransportStatus.DISCONNECTED
            return None

        # Append to buffer and decode all complete frames
        self._recv_buffer += data
        messages = MessageFramer.decode_stream(self._recv_buffer)

        # Remove consumed bytes from buffer
        consumed = sum(
            len(MessageFramer.encode(m)) for m in messages
        )
        self._recv_buffer = self._recv_buffer[consumed:]

        if not messages:
            return None

        # Return first, queue the rest
        first = messages[0]
        self._pending_messages = messages[1:]
        return first

    # -- state --------------------------------------------------------------

    @property
    def status(self) -> TransportStatus:
        return self._status

    @property
    def socket_path(self) -> str:
        return self._socket_path

    # -- helpers ------------------------------------------------------------

    def _make_sender_callback(
        self,
    ) -> Callable[[dict], object]:
        """Return a ``sender`` callback compatible with
        ``register_remote_route``.

        The callback accepts a ``dict`` (``NetworkMessage.model_dump()``)
        and writes the framed message to the socket.
        """

        def _sender(data: dict) -> None:
            msg = NetworkMessage(**data)
            self.send(msg)

        return _sender

    def __enter__(self) -> UnixSocketTransport:
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.disconnect()


# ---------------------------------------------------------------------------
# UnixSocketListener — helper for the listening / server side
# ---------------------------------------------------------------------------

class UnixSocketListener:
    """Minimal listening wrapper for Unix domain sockets.

    Accepts a single client connection and exposes a ``UnixSocketTransport``
    on the accepted socket so that both sides share the same framing logic.

    Intended for local IPC where the hypervisor listens and the runtime
    connects (or vice-versa).
    """

    def __init__(self, socket_path: str, *, backlog: int = 5) -> None:
        self._socket_path = socket_path
        self._backlog = backlog
        self._server: Optional[socket.socket] = None
        self._client: Optional[socket.socket] = None
        self._status = TransportStatus.DISCONNECTED
        self._recv_buffer: bytes = b""
        self._pending_messages: list[NetworkMessage] = []

    # -- lifecycle ----------------------------------------------------------

    def bind(self) -> None:
        """Bind the server socket and start listening."""
        path = Path(self._socket_path)
        if path.exists():
            path.unlink()

        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.bind(self._socket_path)
        self._server.listen(self._backlog)
        self._server.settimeout(5.0)
        self._status = TransportStatus.CONNECTING

    def accept(self) -> None:
        """Block until a client connects."""
        if self._server is None:
            raise RuntimeError("call bind() before accept()")

        try:
            self._client, _addr = self._server.accept()
            self._client.settimeout(5.0)
            self._status = TransportStatus.CONNECTED
        except (OSError, socket.timeout) as exc:
            self._status = TransportStatus.ERROR
            raise ConnectionError(f"accept failed: {exc}") from exc

    def close(self) -> None:
        """Shut down the listener and clean up the socket file."""
        if self._client is not None:
            try:
                self._client.shutdown(socket.SHUT_RDWR)
                self._client.close()
            except (OSError, Exception):
                pass
            self._client = None

        if self._server is not None:
            self._server.close()
            self._server = None

        path = Path(self._socket_path)
        if path.exists():
            path.unlink()

        self._status = TransportStatus.DISCONNECTED

    @property
    def status(self) -> TransportStatus:
        return self._status

    # -- messaging ----------------------------------------------------------

    def send(self, message: NetworkMessage) -> bytes:
        """Send a framed message to the connected client."""
        if self._status != TransportStatus.CONNECTED or self._client is None:
            raise ConnectionError(
                f"cannot send — listener not connected (status={self._status.value})"
            )

        wire = MessageFramer.encode(message)
        self._client.sendall(wire)
        return wire

    def receive(self) -> NetworkMessage | None:
        """Read the next framed message from the connected client.

        Incoming bytes are accumulated in an internal buffer so that
        multiple messages delivered in a single ``recv()`` are queued
        and returned one at a time across subsequent calls.
        """
        if self._status != TransportStatus.CONNECTED or self._client is None:
            return None

        # Drain any previously buffered messages first
        if self._pending_messages:
            return self._pending_messages.pop(0)

        try:
            data = self._client.recv(65536)
        except (OSError, ConnectionResetError):
            self._status = TransportStatus.ERROR
            return None

        if not data:
            self._status = TransportStatus.DISCONNECTED
            return None

        # Append to buffer and decode all complete frames
        self._recv_buffer += data
        messages = MessageFramer.decode_stream(self._recv_buffer)

        # Remove consumed bytes from buffer
        consumed = sum(
            len(MessageFramer.encode(m)) for m in messages
        )
        self._recv_buffer = self._recv_buffer[consumed:]

        if not messages:
            return None

        # Return first, queue the rest
        first = messages[0]
        self._pending_messages = messages[1:]
        return first

    def __enter__(self) -> UnixSocketListener:
        self.bind()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
