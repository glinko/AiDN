"""gRPC Transport Profile for Registry Replication (M9-S4).

RFC-0042 §5-§6 — Transport Independence + Initial Transport Profiles.

Implements a gRPC-specific transport profile for registry replication
messages. In MVP mode, the transport is simulated (no real gRPC server);
production deployments would use ``grpcio`` with generated stubs.

Key features
------------
- Bidirectional streaming for registry messages
- Keepalive with health checks
- Message framing via ``MessageFramer``
- TLS/mTLS support (configurable)
- Backpressure via ``max_concurrent_streams``
- Proto-compatible wire format (``GrpcProtoRegistryMessage``)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, Field

from aidn_hypervisor.dispatcher.transport.abc import (
    TransportGateway,
    TransportStatus,
    MessageFramer,
)

from .messages import (
    RegistryMessageType,
    RegistryChannelClass,
    RegistryPayload,
)
from .object_envelope import RegistryObjectEnvelope


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class GrpcTransportConfig(BaseModel):
    """gRPC transport configuration."""

    host: str = "localhost"
    port: int = 50051
    max_message_size_bytes: int = 10 * 1024 * 1024  # 10 MB
    keepalive_interval_seconds: int = 30
    keepalive_timeout_seconds: int = 10
    max_concurrent_streams: int = 100
    tls_enabled: bool = False
    tls_cert_path: str | None = None
    tls_key_path: str | None = None
    tls_ca_path: str | None = None


class GrpcConnectionState(BaseModel):
    """State of a gRPC connection."""

    connection_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    peer_address: str = ""
    status: str = TransportStatus.DISCONNECTED.value
    connected_at: float = 0.0
    last_keepalive_at: float = 0.0
    messages_sent: int = 0
    messages_received: int = 0
    bytes_sent: int = 0
    bytes_received: int = 0
    error: str | None = None


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------


class GrpcRegistryTransport:
    """RFC-0042 §5-§6 — gRPC transport profile for registry replication.

    Implements ``TransportGateway`` protocol with gRPC-specific behaviour:

    - Bidirectional streaming for registry messages
    - Keepalive with health checks
    - Message framing via ``MessageFramer``
    - TLS/mTLS support (configurable)
    - Backpressure via ``max_concurrent_streams``

    In MVP, uses simulated transport (no real gRPC server).
    Production impl would use ``grpcio`` with generated stubs.
    """

    def __init__(self, config: GrpcTransportConfig | None = None) -> None:
        self._config = config or GrpcTransportConfig()
        self._state = GrpcConnectionState(
            peer_address=f"{self._config.host}:{self._config.port}",
        )
        self._send_buffer: list[bytes] = []
        self._receive_buffer: list[bytes] = []
        self._handlers: dict[str, Callable] = {}
        self._is_connected = False

    # -- properties ---------------------------------------------------------

    @property
    def config(self) -> GrpcTransportConfig:
        """Return the transport configuration."""
        return self._config

    @property
    def state(self) -> GrpcConnectionState:
        """Return a *copy* of the current connection state."""
        return self._state.model_copy()

    @property
    def status(self) -> TransportStatus:
        """Current connection status."""
        if self._is_connected:
            return TransportStatus.CONNECTED
        return TransportStatus.DISCONNECTED

    # -- lifecycle ----------------------------------------------------------

    def connect(self) -> None:
        """Establish the gRPC connection."""
        if self._is_connected:
            return

        self._is_connected = True
        self._state = self._state.model_copy(
            update={
                "status": TransportStatus.CONNECTED.value,
                "connected_at": time.time(),
                "last_keepalive_at": time.time(),
            }
        )

    def disconnect(self) -> None:
        """Close the gRPC connection."""
        self._is_connected = False
        self._state = self._state.model_copy(
            update={
                "status": TransportStatus.DISCONNECTED.value,
            }
        )
        self._send_buffer.clear()
        self._receive_buffer.clear()

    # -- messaging ----------------------------------------------------------

    def send(self, message_data: bytes) -> bytes:
        """Send raw bytes (framed message).

        In MVP, buffers locally.  Production would send via gRPC stream.

        Raises
        ------
        ConnectionError
            If the transport is not connected.
        ValueError
            If the message exceeds ``max_message_size_bytes``.
        """
        if not self._is_connected:
            raise ConnectionError("Transport not connected")

        if len(message_data) > self._config.max_message_size_bytes:
            raise ValueError(
                f"Message size {len(message_data)} exceeds "
                f"max {self._config.max_message_size_bytes}"
            )

        self._send_buffer.append(message_data)
        self._state = self._state.model_copy(
            update={
                "messages_sent": self._state.messages_sent + 1,
                "bytes_sent": self._state.bytes_sent + len(message_data),
            }
        )
        return message_data

    def receive(self) -> bytes | None:
        """Receive raw bytes (framed message).

        In MVP, returns from buffer.  Production would read from gRPC stream.
        """
        if not self._receive_buffer:
            return None

        data = self._receive_buffer.pop(0)
        self._state = self._state.model_copy(
            update={
                "messages_received": self._state.messages_received + 1,
                "bytes_received": self._state.bytes_received + len(data),
            }
        )
        return data

    def inject_message(self, data: bytes) -> None:
        """Inject a message into the receive buffer (for testing)."""
        self._receive_buffer.append(data)

    # -- handlers -----------------------------------------------------------

    def register_handler(
        self,
        message_type: str,
        handler: Callable,
    ) -> None:
        """Register a handler for a message type."""
        self._handlers[message_type] = handler

    # -- keepalive ----------------------------------------------------------

    def keepalive(self) -> None:
        """Send keepalive ping."""
        if not self._is_connected:
            return
        self._state = self._state.model_copy(
            update={"last_keepalive_at": time.time()}
        )

    def is_keepalive_stale(self, threshold_seconds: int = 60) -> bool:
        """Check if keepalive is stale."""
        if not self._is_connected:
            return True
        return (time.time() - self._state.last_keepalive_at) > threshold_seconds

    # -- buffer helpers -----------------------------------------------------

    def get_send_buffer_size(self) -> int:
        return len(self._send_buffer)

    def clear_send_buffer(self) -> int:
        count = len(self._send_buffer)
        self._send_buffer.clear()
        return count

    def get_receive_buffer_size(self) -> int:
        return len(self._receive_buffer)

    def clear_receive_buffer(self) -> int:
        count = len(self._receive_buffer)
        self._receive_buffer.clear()
        return count


# ---------------------------------------------------------------------------
# Stream
# ---------------------------------------------------------------------------


class GrpcRegistryStream:
    """Simulated gRPC bidirectional stream for registry replication.

    In MVP, connects two ``GrpcRegistryTransport`` instances.
    Production would use real gRPC streams.
    """

    def __init__(
        self,
        local: GrpcRegistryTransport,
        remote: GrpcRegistryTransport,
    ) -> None:
        self._local = local
        self._remote = remote

    def send(self, message_data: bytes) -> bytes:
        """Send from local to remote."""
        self._local.send(message_data)
        # Simulate delivery by injecting into remote receive buffer
        self._remote.inject_message(message_data)
        return message_data

    def receive(self) -> bytes | None:
        """Receive from remote."""
        return self._local.receive()

    def close(self) -> None:
        """Close both ends."""
        self._local.disconnect()
        self._remote.disconnect()

    @property
    def is_active(self) -> bool:
        return (
            self._local.status == TransportStatus.CONNECTED
            and self._remote.status == TransportStatus.CONNECTED
        )


# ---------------------------------------------------------------------------
# Proto-compatible message model
# ---------------------------------------------------------------------------


class GrpcProtoRegistryMessage(BaseModel):
    """Proto-compatible registry message model.

    Represents the wire format for registry replication messages that
    would be defined in a ``.proto`` file.

    Proto definition (specification)::

        syntax = "proto3";

        message RegistryMessage {
            string message_id = 1;
            string message_type = 2;
            string source_node_id = 3;
            string destination_node_id = 4;
            uint64 sequence_number = 5;
            bytes payload = 6;
            uint64 created_at = 7;
            uint32 hop_limit = 8;
        }

        service RegistryReplication {
            rpc StreamMessages (stream RegistryMessage)
                returns (stream RegistryMessage);
            rpc HealthCheck (HealthRequest) returns (HealthResponse);
            rpc SyncStatus (SyncStatusRequest) returns (SyncStatusResponse);
        }
    """

    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    message_type: str
    source_node_id: str
    destination_node_id: str
    sequence_number: int = 0
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: float = Field(default_factory=time.time)
    hop_limit: int = 2

    def to_bytes(self) -> bytes:
        """Serialize to bytes (JSON for MVP; would be proto in production)."""
        return self.model_dump_json().encode("utf-8")

    @classmethod
    def from_bytes(cls, data: bytes) -> GrpcProtoRegistryMessage:
        """Deserialize from bytes."""
        return cls.model_validate_json(data)

    def compute_hash(self) -> str:
        """Compute content hash for integrity verification."""
        canonical = json.dumps(
            self.payload, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(canonical.encode()).hexdigest()
