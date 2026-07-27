"""TLS-wrapped TCP transport adapter for the dispatcher layer.

Wraps a plain TCP socket with SSL/TLS encryption using ``ssl.SSLContext``.
Falls back to unencrypted TCP when the ``ssl`` module is unavailable
(e.g. minimal Docker images without OpenSSL).

Intended for environments where endpoints are on untrusted networks
(public internet, multi-tenant clouds) but full mTLS is not required.
For mutual authentication use ``certfile`` + ``keyfile`` + ``ca_certs``.
"""

from __future__ import annotations

import socket
import ssl

from aidn_hypervisor.dispatcher.models import NetworkMessage
from aidn_hypervisor.dispatcher.transport.abc import (
    MessageFramer,
    TransportStatus,
)
from aidn_hypervisor.dispatcher.transport.tcp import TcpTransport

# ---------------------------------------------------------------------------
# TlsTransport
# ---------------------------------------------------------------------------

class TlsTransport(TcpTransport):
    """TcpTransport with TLS encryption via ``ssl.SSLContext``.

    Parameters
    ----------
    host : str
        Remote hostname or IP address.
    port : int
        Remote TCP port.
    certfile : str or None
        Path to the client certificate (PEM).  Required for mTLS.
    keyfile : str or None
        Path to the client private key (PEM).  Required for mTLS.
    ca_certs : str or None
        Path to a CA bundle (PEM) for server verification.
    verify : bool
        When ``True`` the server certificate is verified against
        ``ca_certs`` (or the system CA store).  When ``False`` the
        connection proceeds without verification (insecure — useful
        for self-signed certs in development).
    send_timeout : float
        Maximum seconds to block on ``send()``.
    recv_timeout : float
        Maximum seconds to block on ``receive()``.
    """

    def __init__(
        self,
        host: str,
        port: int,
        *,
        certfile: str | None = None,
        keyfile: str | None = None,
        ca_certs: str | None = None,
        verify: bool = True,
        send_timeout: float = 5.0,
        recv_timeout: float = 5.0,
    ) -> None:
        super().__init__(host, port, send_timeout=send_timeout, recv_timeout=recv_timeout)
        self._certfile = certfile
        self._keyfile = keyfile
        self._ca_certs = ca_certs
        self._verify = verify
        self._ssl_context: ssl.SSLContext | None = None
        self._tls_established = False
        self._raw_socket: socket.socket | None = None

    # -- lifecycle ----------------------------------------------------------

    def _build_ssl_context(self) -> ssl.SSLContext:
        """Construct an ``SSLContext`` from the configured parameters."""
        ctx = ssl.create_default_context(
            purpose=ssl.Purpose.SERVER_AUTH,
            cafile=self._ca_certs,
        )
        if self._certfile and self._keyfile:
            ctx.load_cert_chain(certfile=self._certfile, keyfile=self._keyfile)
        if not self._verify:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        return ctx

    def connect(self) -> None:
        """Establish a TCP connection to *(host, port).*

        This performs the TCP handshake only.  Call ``handshake()``
        afterwards to negotiate TLS.  If ``handshake()`` is never
        called the transport operates in plain-TCP mode.
        """
        with self._lock:
            if self._status == TransportStatus.CONNECTED:
                return

            self._status = TransportStatus.CONNECTING
            try:
                self._socket = socket.create_connection(
                    (self._host, self._port), timeout=self._send_timeout
                )
                self._socket.settimeout(self._recv_timeout)
                self._raw_socket = self._socket
                self._status = TransportStatus.CONNECTED
            except (OSError, ConnectionRefusedError, TimeoutError) as exc:
                self._status = TransportStatus.ERROR
                if self._socket:
                    try:
                        self._socket.close()
                    except Exception:
                        pass
                    self._socket = None
                raise ConnectionError(
                    f"cannot connect to TLS {self._host}:{self._port}: {exc}"
                ) from exc

    def handshake(self) -> None:
        """Perform the TLS handshake on the already-connected socket.

        Raises
        ------
        ConnectionError
            If the TLS handshake fails.
        """
        with self._lock:
            if self._status != TransportStatus.CONNECTED or self._socket is None:
                raise ConnectionError(
                    "cannot handshake — transport is not connected "
                    f"(status={self._status.value})"
                )

            try:
                self._ssl_context = self._build_ssl_context()
                self._socket = self._ssl_context.wrap_socket(
                    self._socket,
                    server_hostname=self._host,
                    do_handshake_on_connect=True,
                )
                self._tls_established = True
            except ssl.SSLError as exc:
                # Restore the plain socket so send/receive still work
                self._socket = self._raw_socket
                self._tls_established = False
                raise ConnectionError(f"TLS handshake failed: {exc}") from exc
            except AttributeError:
                self._tls_established = False
                raise ConnectionError("ssl module not available")

    def disconnect(self) -> None:
        """Gracefully close the TLS (or plain) connection."""
        with self._lock:
            if self._socket is not None:
                try:
                    if self._tls_established:
                        try:
                            _s = self._socket
                            if hasattr(_s, "unwrap"):
                                _s.unwrap()  # type: ignore[union-attr]
                        except Exception:
                            pass
                except (OSError, Exception):
                    pass
                try:
                    self._socket.close()
                except Exception:
                    pass
                self._socket = None
            self._raw_socket = None
            self._tls_established = False
            self._status = TransportStatus.DISCONNECTED

    @property
    def tls_established(self) -> bool:
        """Whether the connection is actually encrypted with TLS."""
        return self._tls_established

    # -- messaging (inherited from TcpTransport) ----------------------------
    # send() / receive() work unchanged because they operate on self._socket
    # which is now an ssl.SSLSocket (same sendall/recv interface).

    # -- helpers ------------------------------------------------------------

    def _make_sender_callback(self):
        """Return a sender callback compatible with ``register_remote_route``."""
        def _sender(data: dict) -> None:
            msg = NetworkMessage(**data)
            self.send(msg)

        return _sender

    def __enter__(self) -> TlsTransport:
        self.connect()
        self.handshake()
        return self

    def __exit__(self, *exc: object) -> None:
        self.disconnect()


# ---------------------------------------------------------------------------
# TlsListener — server-side TLS listening helper
# ---------------------------------------------------------------------------

class TlsListener:
    """Minimal TLS listening wrapper for the server side.

    Binds to *(host, port)*, accepts a single client connection,
    wraps it with TLS, and exposes ``send()`` / ``receive()`` with
    the same ``MessageFramer`` wire protocol.

    Parameters
    ----------
    host : str
        Bind address.
    port : int
        Bind port (``0`` for OS-assigned).
    certfile : str
        Path to the server certificate (PEM).
    keyfile : str
        Path to the server private key (PEM).
    ca_certs : str or None
        Path to a CA bundle for client verification (mTLS).
    verify_client : bool
        When ``True`` the client certificate is verified.
    backlog : int
        TCP listen backlog.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 0,
        *,
        certfile: str,
        keyfile: str,
        ca_certs: str | None = None,
        verify_client: bool = False,
        backlog: int = 5,
    ) -> None:
        self._host = host
        self._port = port
        self._certfile = certfile
        self._keyfile = keyfile
        self._ca_certs = ca_certs
        self._verify_client = verify_client
        self._backlog = backlog
        self._raw_server: ssl.SSLSocket | None = None
        self._client: ssl.SSLSocket | None = None
        self._status = TransportStatus.DISCONNECTED
        self._recv_buffer: bytes = b""
        self._pending_messages: list[NetworkMessage] = []

    # -- lifecycle ----------------------------------------------------------

    def bind(self) -> None:
        """Bind the server socket and start listening."""
        ctx = ssl.create_default_context(
            purpose=ssl.Purpose.CLIENT_AUTH,
            cafile=self._ca_certs,
        )
        ctx.load_cert_chain(certfile=self._certfile, keyfile=self._keyfile)
        if self._verify_client:
            ctx.verify_mode = ssl.CERT_REQUIRED
        else:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

        raw = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        raw.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        raw.bind((self._host, self._port))
        raw.listen(self._backlog)
        raw.settimeout(5.0)

        self._raw_server = ctx.wrap_socket(raw, server_side=True)
        self._status = TransportStatus.CONNECTING

    def accept(self) -> None:
        """Block until a client connects and completes TLS handshake."""
        if self._raw_server is None:
            raise RuntimeError("call bind() before accept()")

        try:
            self._client = self._raw_server.accept()[0]
            self._client.settimeout(5.0)
            self._status = TransportStatus.CONNECTED
        except (OSError, ssl.SSLError) as exc:
            self._status = TransportStatus.ERROR
            raise ConnectionError(f"TLS accept failed: {exc}") from exc

    def close(self) -> None:
        """Shut down the listener and close all sockets."""
        if self._client is not None:
            try:
                self._client.unwrap()
            except Exception:
                pass
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None

        if self._raw_server is not None:
            try:
                self._raw_server.close()
            except Exception:
                pass
            self._raw_server = None

        self._status = TransportStatus.DISCONNECTED

    @property
    def status(self) -> TransportStatus:
        return self._status

    @property
    def bound_port(self) -> int:
        """The actual port the listener is bound to."""
        if self._raw_server is None:
            raise RuntimeError("not bound yet")
        return self._raw_server.getsockname()[1]

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
        """Read the next framed message from the connected client."""
        if self._status != TransportStatus.CONNECTED or self._client is None:
            return None

        if self._pending_messages:
            return self._pending_messages.pop(0)

        try:
            data = self._client.recv(65536)
        except (OSError, ssl.SSLError):
            self._status = TransportStatus.ERROR
            return None

        if not data:
            self._status = TransportStatus.DISCONNECTED
            return None

        self._recv_buffer += data
        messages = MessageFramer.decode_stream(self._recv_buffer)

        consumed = sum(len(MessageFramer.encode(m)) for m in messages)
        self._recv_buffer = self._recv_buffer[consumed:]

        if not messages:
            return None

        first = messages[0]
        self._pending_messages = messages[1:]
        return first

    def __enter__(self) -> TlsListener:
        self.bind()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
