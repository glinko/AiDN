"""QUIC/TLS transport layer (RFC-0042 §6-9).

Provides authenticated, encrypted transport for AiDN peer-to-peer
communication. QUIC_TLS is the preferred public transport profile.
"""

import asyncio
import logging
from abc import ABC, abstractmethod

from aidn_hypervisor.dispatcher.handshake import (
    ConnectionIdentity,
    ConnectionState,
    HandshakeProtocol,
    TransportProfile,
)

logger = logging.getLogger(__name__)

# ── Transport profiles (RFC-0042 §6) ──────────────────────────────────────

DEFAULT_QUIC_PORT: int = 443
QUIC_MAX_CONCURRENT_STREAMS: int = 100
TLS_MIN_VERSION: str = "TLSv1.3"


# ── Base transport interface ──────────────────────────────────────────────

class TransportProfileBase(ABC):
    """Abstract transport profile (RFC-0042 §6).

    All public connections SHALL use authenticated encryption.
    """

    profile: TransportProfile

    @abstractmethod
    async def connect(self, host: str, port: int) -> ConnectionIdentity:
        """Establish an authenticated connection to a remote peer."""

    @abstractmethod
    async def send(self, connection_id: str, data: bytes) -> None:
        """Send encrypted data over an established connection."""

    @abstractmethod
    async def recv(self, connection_id: str, max_bytes: int = 65536) -> bytes:
        """Receive encrypted data from a connection."""

    @abstractmethod
    async def close(self, connection_id: str) -> None:
        """Gracefully close a connection."""

    @abstractmethod
    async def listen(self, port: int) -> None:
        """Start listening for inbound connections."""

    @abstractmethod
    async def stop_listening(self) -> None:
        """Stop accepting new inbound connections."""


# ── QUIC/TLS transport (RFC-0042 §6) ─────────────────────────────────────

class QUICTransport(TransportProfileBase):
    """QUIC-based TLS transport (RFC-0042 §6 — QUIC_TLS profile).

    Provides:
    - Encrypted transport via QUIC with TLS 1.3
    - Connection management with lifecycle state tracking
    - Stream multiplexing for logical channels
    - Graceful connection draining
    """

    profile: TransportProfile = "QUIC_TLS"

    def __init__(
        self,
        *,
        handshake: HandshakeProtocol,
        cert_file: str | None = None,
        key_file: str | None = None,
        port: int = DEFAULT_QUIC_PORT,
        max_concurrent_streams: int = QUIC_MAX_CONCURRENT_STREAMS,
    ) -> None:
        self.handshake = handshake
        self.cert_file = cert_file
        self.key_file = key_file
        self.port = port
        self.max_concurrent_streams = max_concurrent_streams

        # Connection state
        self._connections: dict[str, ConnectionIdentity] = {}
        self._is_listening: bool = False
        self._server: asyncio.Server | None = None
        self._incoming_cb: list[callable] = []

    @property
    def active_connections(self) -> list[ConnectionIdentity]:
        """List of currently established connections."""
        return [
            c for c in self._connections.values()
            if c.state in ("ESTABLISHED", "SERVICE_NEGOTIATING")
        ]

    async def connect(self, host: str, port: int) -> ConnectionIdentity:
        """Establish an authenticated QUIC connection (RFC-0042 §8).

        Performs:
        1. QUIC transport handshake
        2. AiDN protocol handshake (ClientHello/ServerHello)
        3. Connection identity derivation
        """
        import socket
        import uuid

        connection_id = str(uuid.uuid4())
        logger.info(
            "Connecting to %s:%d (conn=%s)", host, port, connection_id
        )

        # Resolve address
        try:
            _ = socket.getaddrinfo(host, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
        except socket.gaierror as exc:
            logger.error("DNS resolution failed for %s: %s", host, exc)
            raise ConnectionError(f"Cannot resolve {host}") from exc

        # Create connection identity in connecting state
        identity = ConnectionIdentity(
            connection_id=connection_id,
            local_hypervisor_id=self.handshake.local_hypervisor_id,
            remote_hypervisor_id="",  # populated after handshake
            network_id=self.handshake.network_id,
            chain_id=self.handshake.chain_id,
            network_revision=self.handshake.network_revision,
            transport_profile=self.profile,
            state="TRANSPORT_CONNECTING",
        )
        self._connections[connection_id] = identity

        # TODO: actual QUIC connection via aioquic
        # For now, stub the transport path
        logger.info(
            "QUIC connection established (stub) conn=%s", connection_id
        )
        return identity

    async def send(self, connection_id: str, data: bytes) -> None:
        """Send encrypted data over established connection."""
        identity = self._connections.get(connection_id)
        if identity is None:
            raise KeyError(f"Unknown connection {connection_id}")
        if identity.state != "ESTABLISHED":
            raise RuntimeError(
                f"Cannot send on connection in state {identity.state}"
            )
        # TODO: actual QUIC stream write
        logger.debug("Sending %d bytes on conn=%s", len(data), connection_id)

    async def recv(self, connection_id: str, max_bytes: int = 65536) -> bytes:
        """Receive encrypted data from connection."""
        identity = self._connections.get(connection_id)
        if identity is None:
            raise KeyError(f"Unknown connection {connection_id}")
        if identity.state != "ESTABLISHED":
            raise RuntimeError(
                f"Cannot recv on connection in state {identity.state}"
            )
        # TODO: actual QUIC stream read
        return b""

    async def close(self, connection_id: str) -> None:
        """Gracefully close a connection."""
        identity = self._connections.get(connection_id)
        if identity is None:
            return
        identity.state = "DRAINING"
        # TODO: QUIC connection close
        identity.state = "CLOSED"
        logger.info("Connection closed conn=%s", connection_id)

    async def listen(self, port: int) -> None:
        """Start listening for inbound QUIC connections (RFC-0042 §9)."""
        if self._is_listening:
            return
        self._is_listening = True
        logger.info("Listening on port %d (QUIC_TLS)", port)
        # TODO: actual QUIC listener via aioquic

    async def stop_listening(self) -> None:
        """Stop accepting new inbound connections."""
        self._is_listening = False
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        logger.info("Stopped listening")

    def register_incoming_callback(self, cb: callable) -> None:
        """Register a callback for new inbound connections."""
        self._incoming_cb.append(cb)

    def get_connection(self, connection_id: str) -> ConnectionIdentity | None:
        """Look up a connection by ID."""
        return self._connections.get(connection_id)

    def list_connections(self, state: ConnectionState | None = None) -> list[ConnectionIdentity]:
        """List connections, optionally filtered by state."""
        if state is None:
            return list(self._connections.values())
        return [c for c in self._connections.values() if c.state == state]


# ── TCP/TLS fallback transport ────────────────────────────────────────────

class TCPTLSTransport(TransportProfileBase):
    """TCP with TLS transport (fallback profile).

    Used when QUIC is unavailable (e.g., restrictive firewalls).
    """

    profile: TransportProfile = "TCP_TLS"

    def __init__(
        self,
        *,
        handshake: HandshakeProtocol,
        cert_file: str | None = None,
        key_file: str | None = None,
        port: int = 443,
    ) -> None:
        self.handshake = handshake
        self.cert_file = cert_file
        self.key_file = key_file
        self.port = port
        self._connections: dict[str, ConnectionIdentity] = {}
        self._is_listening: bool = False

    async def connect(self, host: str, port: int) -> ConnectionIdentity:
        raise NotImplementedError("TCP_TLS transport not yet implemented")

    async def send(self, connection_id: str, data: bytes) -> None:
        raise NotImplementedError("TCP_TLS transport not yet implemented")

    async def recv(self, connection_id: str, max_bytes: int = 65536) -> bytes:
        raise NotImplementedError("TCP_TLS transport not yet implemented")

    async def close(self, connection_id: str) -> None:
        raise NotImplementedError("TCP_TLS transport not yet implemented")

    async def listen(self, port: int) -> None:
        raise NotImplementedError("TCP_TLS transport not yet implemented")

    async def stop_listening(self) -> None:
        self._is_listening = False


# ── Transport factory ─────────────────────────────────────────────────────

def create_transport(
    profile: TransportProfile,
    *,
    handshake: HandshakeProtocol,
    **kwargs,
) -> TransportProfileBase:
    """Factory for transport profiles (RFC-0042 §6)."""
    factories: dict[TransportProfile, type[TransportProfileBase]] = {
        "QUIC_TLS": QUICTransport,
        "TCP_TLS": TCPTLSTransport,
    }
    # WEBSOCKET_TLS and LOCAL_IPC are stubs for now
    cls = factories.get(profile)
    if cls is None:
        raise ValueError(f"Unsupported transport profile: {profile}")
    return cls(handshake=handshake, **kwargs)
