"""TCP transport adapter for the dispatcher layer.

Implements the ``TransportGateway`` protocol over a plain TCP socket
(no TLS, no authentication) using ``MessageFramer`` for length-prefixed
JSON framing of ``NetworkMessage`` objects.

Intended for environments where both endpoints trust the underlying
network (e.g. internal clusters, loopback, VPN).
"""

from __future__ import annotations

import socket
import threading
from collections.abc import Callable

from aidn_hypervisor.dispatcher.models import NetworkMessage
from aidn_hypervisor.dispatcher.transport.abc import (
    MessageFramer,
    TransportGateway,
    TransportStatus,
)

# ---------------------------------------------------------------------------
# TcpTransport
# ---------------------------------------------------------------------------

class TcpTransport(TransportGateway):
    """TransportGateway implementation over a plain TCP socket.

    Parameters
    ----------
    host : str
        Remote hostname or IP address to connect to.
    port : int
        Remote TCP port.
    send_timeout : float
        Maximum seconds to block on ``send()``.  ``0`` means non-blocking.
    recv_timeout : float
        Maximum seconds to block on ``receive()``.  ``0`` means non-blocking.
    """

    def __init__(
        self,
        host: str,
        port: int,
        *,
        send_timeout: float = 5.0,
        recv_timeout: float = 5.0,
    ) -> None:
        self._host = host
        self._port = port
        self._send_timeout = send_timeout
        self._recv_timeout = recv_timeout
        self._socket: socket.socket | None = None
        self._status = TransportStatus.DISCONNECTED
        self._lock = threading.Lock()
        self._recv_buffer: bytes = b""
        self._pending_messages: list[NetworkMessage] = []

    # -- lifecycle ----------------------------------------------------------

    def connect(self) -> None:
        """Establish a TCP connection to *(host, port).*"""
        with self._lock:
            if self._status == TransportStatus.CONNECTED:
                return

            self._status = TransportStatus.CONNECTING
            try:
                self._socket = socket.create_connection(
                    (self._host, self._port), timeout=self._send_timeout
                )
                self._socket.settimeout(self._recv_timeout)
                self._status = TransportStatus.CONNECTED
            except (OSError, ConnectionRefusedError, TimeoutError) as exc:
                self._status = TransportStatus.ERROR
                if self._socket:
                    self._socket.close()
                    self._socket = None
                raise ConnectionError(
                    f"cannot connect to TCP {self._host}:{self._port}: {exc}"
                ) from exc

    def disconnect(self) -> None:
        """Gracefully close the TCP connection."""
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
                if self._status != TransportStatus.CONNECTED or self._socket is None:
                    raise ConnectionError("cannot send - transport is not connected")
                self._socket.sendall(wire)
        except ConnectionError:
            raise
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
        with self._lock:
            if self._status != TransportStatus.CONNECTED or self._socket is None:
                return None

            # Drain any previously buffered messages first.
            if self._pending_messages:
                return self._pending_messages.pop(0)
            socket = self._socket

        try:
            # Do not hold the transport lock while waiting for inbound bytes.
            # Registry replication reads and writes from separate workers; a
            # blocking read must not prevent the outbox from being flushed.
            data = socket.recv(65536)
        except TimeoutError:
            return None
        except (OSError, ConnectionResetError):
            with self._lock:
                if self._socket is socket:
                    self._status = TransportStatus.ERROR
            return None

        if not data:
            # Peer closed the connection
            with self._lock:
                if self._socket is socket:
                    self._status = TransportStatus.DISCONNECTED
            return None

        with self._lock:
            if self._socket is not socket or self._status != TransportStatus.CONNECTED:
                return None
            # Append to buffer and decode all complete frames.
            self._recv_buffer += data
            messages = MessageFramer.decode_stream(self._recv_buffer)

            # Remove consumed bytes from buffer.
            consumed = sum(len(MessageFramer.encode(m)) for m in messages)
            self._recv_buffer = self._recv_buffer[consumed:]

            if not messages:
                return None

            # Return first, queue the rest.
            first = messages[0]
            self._pending_messages = messages[1:]
            return first

    # -- state --------------------------------------------------------------

    @property
    def status(self) -> TransportStatus:
        return self._status

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        return self._port

    # -- helpers ------------------------------------------------------------

    def _make_sender_callback(self) -> Callable[[dict], object]:
        """Return a ``sender`` callback compatible with
        ``register_remote_route``.

        The callback accepts a ``dict`` (``NetworkMessage.model_dump()``)
        and writes the framed message to the socket.
        """

        def _sender(data: dict) -> None:
            msg = NetworkMessage(**data)
            self.send(msg)

        return _sender

    def __enter__(self) -> TcpTransport:
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.disconnect()


# ---------------------------------------------------------------------------
# TcpListener — helper for the listening / server side
# ---------------------------------------------------------------------------

class TcpListener:
    """Minimal listening wrapper for TCP sockets.

    Binds to *(host, port)*, accepts a single client connection, and
    exposes ``send()`` / ``receive()`` with the same ``MessageFramer``
    wire protocol.

    Intended for test fixtures and local server-side endpoints.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 0,
        *,
        backlog: int = 5,
    ) -> None:
        self._host = host
        self._port = port
        self._backlog = backlog
        self._server: socket.socket | None = None
        self._client: socket.socket | None = None
        self._status = TransportStatus.DISCONNECTED
        self._recv_buffer: bytes = b""
        self._pending_messages: list[NetworkMessage] = []

    # -- lifecycle ----------------------------------------------------------

    def bind(self) -> None:
        """Bind the server socket and start listening."""
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind((self._host, self._port))
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
        except (TimeoutError, OSError) as exc:
            self._status = TransportStatus.ERROR
            raise ConnectionError(f"accept failed: {exc}") from exc

    def close(self) -> None:
        """Shut down the listener and close all sockets."""
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

        self._status = TransportStatus.DISCONNECTED

    @property
    def status(self) -> TransportStatus:
        return self._status

    @property
    def bound_port(self) -> int:
        """The actual port the listener is bound to (useful when port=0)."""
        if self._server is None:
            raise RuntimeError("not bound yet")
        return self._server.getsockname()[1]

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

    def __enter__(self) -> TcpListener:
        self.bind()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
