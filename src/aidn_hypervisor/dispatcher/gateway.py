"""Network Gateway (RFC-0042 §8-9).

Sits between physical transport and NetworkDispatcher.
Manages connection pool, incoming/outgoing message flow,
handshake lifecycle, and keepalives.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from aidn_hypervisor.dispatcher.handshake import (
    ConnectionIdentity,
    HandshakeProtocol,
    TransportProfile,
)
from aidn_hypervisor.dispatcher.models import NetworkMessage
from aidn_hypervisor.dispatcher.transport.quic import (
    QUICTransport,
    TransportProfileBase,
    create_transport,
)

logger = logging.getLogger(__name__)

# ── Gateway defaults ──────────────────────────────────────────────────────

DEFAULT_KEEPALIVE_INTERVAL_SECS: int = 30
DEFAULT_MAX_CONNECTIONS: int = 64
DEFAULT_SEND_BUFFER: int = 1024


# ── Gateway configuration ────────────────────────────────────────────────

class GatewayConfig:
    """Network gateway configuration."""

    def __init__(
        self,
        *,
        local_hypervisor_id: str,
        network_id: str,
        chain_id: str,
        network_revision: str,
        transport_profile: TransportProfile = "QUIC_TLS",
        listen_port: int = 443,
        max_connections: int = DEFAULT_MAX_CONNECTIONS,
        keepalive_interval: int = DEFAULT_KEEPALIVE_INTERVAL_SECS,
        send_buffer_size: int = DEFAULT_SEND_BUFFER,
    ) -> None:
        self.local_hypervisor_id = local_hypervisor_id
        self.network_id = network_id
        self.chain_id = chain_id
        self.network_revision = network_revision
        self.transport_profile = transport_profile
        self.listen_port = listen_port
        self.max_connections = max_connections
        self.keepalive_interval = keepalive_interval
        self.send_buffer_size = send_buffer_size


# ── Network Gateway ──────────────────────────────────────────────────────

class NetworkGateway:
    """Physical gateway between transport and NetworkDispatcher (RFC-0042 §8-9).

    Responsibilities:
    - Manage authenticated transport connections
    - Perform handshake for new connections
    - Pass validated messages to NetworkDispatcher
    - Send outgoing messages via remote routes
    - Handle keepalives and connection health
    - Manage connection pool with backpressure
    """

    def __init__(self, config: GatewayConfig) -> None:
        self.config = config
        self.handshake = HandshakeProtocol(
            local_hypervisor_id=config.local_hypervisor_id,
            network_id=config.network_id,
            chain_id=config.chain_id,
            network_revision=config.network_revision,
        )
        self.transport: TransportProfileBase = create_transport(
            profile=config.transport_profile,
            handshake=self.handshake,
        )
        self._connections: dict[str, ConnectionIdentity] = {}
        self._send_buffer: list[bytes] = []
        self._is_running: bool = False
        self._keepalive_task: asyncio.Task | None = None
        self._read_task: asyncio.Task | None = None

    @property
    def active_connection_count(self) -> int:
        return len(self._connections)

    @property
    def is_at_capacity(self) -> bool:
        return self.active_connection_count >= self.config.max_connections

    # ── Lifecycle ────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the gateway — begin listening for connections."""
        if self._is_running:
            return
        self._is_running = True
        await self.transport.listen(self.config.listen_port)
        logger.info(
            "Gateway started (profile=%s, port=%d)",
            self.config.transport_profile,
            self.config.listen_port,
        )
        # Start keepalive loop
        self._keepalive_task = asyncio.create_task(self._keepalive_loop())

    async def stop(self) -> None:
        """Stop the gateway — drain connections and shutdown."""
        if not self._is_running:
            return
        self._is_running = False
        # Cancel background tasks
        if self._keepalive_task:
            self._keepalive_task.cancel()
            try:
                await self._keepalive_task
            except asyncio.CancelledError:
                pass
        if self._read_task:
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass
        # Close all connections
        for conn_id in list(self._connections.keys()):
            await self.transport.close(conn_id)
        await self.transport.stop_listening()
        logger.info("Gateway stopped")

    # ── Outbound connections ────────────────────────────────────────

    async def connect_to_peer(self, host: str, port: int) -> str | None:
        """Establish an outbound connection to a remote peer.

        Returns connection_id on success, None on failure.
        """
        if self.is_at_capacity:
            logger.warning("Connection capacity reached (%d)", self.config.max_connections)
            return None

        try:
            identity = await self.transport.connect(host, port)
            self._connections[identity.connection_id] = identity
            logger.info(
                "Connected to %s:%d (conn=%s)",
                host, port, identity.connection_id,
            )
            return identity.connection_id
        except Exception as exc:
            logger.error("Connection failed to %s:%d: %s", host, port, exc)
            return None

    # ── Message sending ─────────────────────────────────────────────

    async def send_message(self, connection_id: str, message: NetworkMessage) -> bool:
        """Send a NetworkMessage to a remote peer via established connection."""
        identity = self._connections.get(connection_id)
        if identity is None:
            logger.error("No connection %s for message send", connection_id)
            return False

        if identity.state != "ESTABLISHED":
            logger.warning("Connection %s not established (state=%s)", connection_id, identity.state)
            return False

        # Serialize message
        data = message.model_dump_json().encode("utf-8")

        # Buffer if send buffer not full, otherwise send directly
        if len(self._send_buffer) < self.config.send_buffer_size:
            self._send_buffer.append(data)
        else:
            await self._flush_send_buffer()
            self._send_buffer.append(data)

        await self.transport.send(connection_id, data)
        return True

    async def _flush_send_buffer(self) -> None:
        """Flush the send buffer."""
        if self._send_buffer:
            combined = b"\n".join(self._send_buffer)
            # Would send combined buffer over transport
            self._send_buffer.clear()

    # ── Message receiving ───────────────────────────────────────────

    async def receive_message(self, connection_id: str) -> NetworkMessage | None:
        """Receive and deserialize a NetworkMessage from a connection."""
        data = await self.transport.recv(connection_id)
        if not data:
            return None
        # TODO: deserialize NetworkMessage from bytes
        return None

    # ── Keepalive ───────────────────────────────────────────────────

    async def _keepalive_loop(self) -> None:
        """Periodic keepalive to maintain connection health."""
        while self._is_running:
            try:
                await asyncio.sleep(self.config.keepalive_interval)
                await self._send_keepalives()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Keepalive error: %s", exc)

    async def _send_keepalives(self) -> None:
        """Send keepalive probes to all active connections."""
        for conn_id, identity in list(self._connections.items()):
            if identity.state == "ESTABLISHED":
                # TODO: send keepalive message
                pass

    # ── Connection management ───────────────────────────────────────

    def get_connection(self, connection_id: str) -> ConnectionIdentity | None:
        """Look up a connection by ID."""
        return self._connections.get(connection_id)

    def list_connections(self) -> list[ConnectionIdentity]:
        """List all managed connections."""
        return list(self._connections.values())

    async def disconnect(self, connection_id: str) -> None:
        """Disconnect a specific peer."""
        if connection_id in self._connections:
            await self.transport.close(connection_id)
            del self._connections[connection_id]
            logger.info("Disconnected: %s", connection_id)
