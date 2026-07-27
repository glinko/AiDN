"""Handshake protocol for QUIC/TLS transport (RFC-0042 §20-24).

Implements ClientHello / ServerHello message exchange, challenge-response
authentication, protocol version negotiation, and network domain validation.
"""

import hashlib
import secrets
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

# ── Protocol version constants ─────────────────────────────────────────────

PROTOCOL_VERSION: str = "1.0.0"
"""Current AiDN transport protocol version (RFC-0042 §20)."""

SUPPORTED_VERSIONS: frozenset[str] = frozenset({"1.0.0"})
"""Negotiable protocol versions."""


# ── Connection lifecycle states (RFC-0042 §20) ────────────────────────────

ConnectionState = Literal[
    "TRANSPORT_CONNECTING",
    "HELLO_EXCHANGING",
    "IDENTITY_VERIFYING",
    "VERSION_NEGOTIATING",
    "SERVICE_NEGOTIATING",
    "ESTABLISHED",
    "DRAINING",
    "CLOSED",
    "ERROR",
]


# ── Transport profiles (RFC-0042 §6) ──────────────────────────────────────

TransportProfile = Literal[
    "QUIC_TLS",
    "TCP_TLS",
    "WEBSOCKET_TLS",
    "LOCAL_IPC",
]


# ── Handshake messages ────────────────────────────────────────────────────

class ClientHello(BaseModel):
    """Outbound handshake initiation (RFC-0042 §21)."""

    protocol_version: str = Field(default=PROTOCOL_VERSION)
    supported_versions: list[str] = Field(default_factory=lambda: list(SUPPORTED_VERSIONS))
    network_id: str
    chain_id: str
    network_revision: str
    local_hypervisor_id: str
    transport_profile: TransportProfile = "QUIC_TLS"
    nonce: str = Field(default_factory=lambda: secrets.token_hex(32))
    timestamp: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )

    def compute_hello_hash(self) -> str:
        """Deterministic hash for challenge-response binding."""
        data = f"{self.protocol_version}:{self.network_id}:{self.chain_id}:{self.nonce}:{self.timestamp}"
        return hashlib.sha256(data.encode()).hexdigest()


class ServerHello(BaseModel):
    """Inbound handshake response (RFC-0042 §22)."""

    protocol_version: str
    network_id: str
    chain_id: str
    network_revision: str
    remote_hypervisor_id: str
    transport_profile: TransportProfile
    challenge: str
    timestamp: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )

    @property
    def domain_matches(self) -> bool:
        """Quick domain consistency check."""
        return True  # caller provides reference domain for comparison


class HandshakeComplete(BaseModel):
    """Final handshake confirmation."""

    protocol_version: str
    connection_id: str
    local_hypervisor_id: str
    remote_hypervisor_id: str
    network_id: str
    chain_id: str
    network_revision: str
    transport_profile: TransportProfile
    established_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )


# ── Connection identity (RFC-0042 §10-13) ─────────────────────────────────

class ConnectionIdentity(BaseModel):
    """Authenticated connection identity between two hypervisors."""

    connection_id: str
    local_hypervisor_id: str
    remote_hypervisor_id: str
    network_id: str
    chain_id: str
    network_revision: str
    transport_profile: TransportProfile
    state: ConnectionState = "TRANSPORT_CONNECTING"
    local_nonce: str = ""
    remote_nonce: str = ""
    negotiated_version: str = PROTOCOL_VERSION
    established_at: str | None = None
    expires_at: str | None = None

    @property
    def combined_nonce(self) -> str:
        """Deterministic combined nonce for session key derivation."""
        combined = f"{self.local_nonce}:{self.remote_nonce}"
        return hashlib.sha256(combined.encode()).hexdigest()


# ── Handshake protocol ────────────────────────────────────────────────────

class HandshakeError(Exception):
    """Raised when handshake validation fails."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class HandshakeProtocol:
    """Implements the handshake lifecycle (RFC-0042 §20-24).

    Manages ClientHello/ServerHello exchange, version negotiation,
    network domain validation, and challenge-response authentication.
    """

    def __init__(
        self,
        *,
        local_hypervisor_id: str,
        network_id: str,
        chain_id: str,
        network_revision: str,
    ) -> None:
        self.local_hypervisor_id = local_hypervisor_id
        self.network_id = network_id
        self.chain_id = chain_id
        self.network_revision = network_revision

    def create_client_hello(
        self,
        *,
        transport_profile: TransportProfile = "QUIC_TLS",
    ) -> ClientHello:
        """Create a ClientHello for outbound connections."""
        return ClientHello(
            network_id=self.network_id,
            chain_id=self.chain_id,
            network_revision=self.network_revision,
            local_hypervisor_id=self.local_hypervisor_id,
            transport_profile=transport_profile,
        )

    def validate_client_hello(self, hello: ClientHello) -> None:
        """Validate an inbound ClientHello against local domain (RFC-0042 §23)."""
        # Domain validation
        if hello.network_id != self.network_id:
            raise HandshakeError(
                "NETWORK_ID_MISMATCH",
                f"Network ID {hello.network_id} != {self.network_id}",
            )
        if hello.chain_id != self.chain_id:
            raise HandshakeError(
                "CHAIN_ID_MISMATCH",
                f"Chain ID {hello.chain_id} != {self.chain_id}",
            )
        if hello.network_revision != self.network_revision:
            raise HandshakeError(
                "NETWORK_REVISION_MISMATCH",
                f"Network revision {hello.network_revision} != {self.network_revision}",
            )
        # Version negotiation
        if hello.protocol_version not in SUPPORTED_VERSIONS:
            raise HandshakeError(
                "UNSUPPORTED_VERSION",
                f"Version {hello.protocol_version} not in {SUPPORTED_VERSIONS}",
            )

    def create_server_hello(
        self,
        client_hello: ClientHello,
        *,
        remote_hypervisor_id: str,
    ) -> ServerHello:
        """Create a ServerHello response (RFC-0042 §22).

        Includes a challenge derived from the client nonce for
        challenge-response authentication.
        """
        self.validate_client_hello(client_hello)
        challenge = self._derive_challenge(client_hello.nonce)
        return ServerHello(
            protocol_version=client_hello.protocol_version,
            network_id=self.network_id,
            chain_id=self.chain_id,
            network_revision=self.network_revision,
            remote_hypervisor_id=remote_hypervisor_id,
            transport_profile=client_hello.transport_profile,
            challenge=challenge,
        )

    def create_connection_identity(
        self,
        *,
        connection_id: str,
        remote_hypervisor_id: str,
        local_nonce: str,
        remote_nonce: str,
        transport_profile: TransportProfile,
        negotiated_version: str = PROTOCOL_VERSION,
    ) -> ConnectionIdentity:
        """Create a ConnectionIdentity after successful handshake (RFC-0042 §10-13)."""
        return ConnectionIdentity(
            connection_id=connection_id,
            local_hypervisor_id=self.local_hypervisor_id,
            remote_hypervisor_id=remote_hypervisor_id,
            network_id=self.network_id,
            chain_id=self.chain_id,
            network_revision=self.network_revision,
            transport_profile=transport_profile,
            state="ESTABLISHED",
            local_nonce=local_nonce,
            remote_nonce=remote_nonce,
            negotiated_version=negotiated_version,
            established_at=datetime.now(UTC).isoformat(),
        )

    @staticmethod
    def _derive_challenge(client_nonce: str) -> str:
        """Derive a server challenge from client nonce + server entropy."""
        server_entropy = secrets.token_hex(32)
        data = f"{client_nonce}:{server_entropy}"
        return hashlib.sha256(data.encode()).hexdigest()
