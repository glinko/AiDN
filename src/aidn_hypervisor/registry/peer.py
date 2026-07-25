"""Registry Peer State Machine (RFC-0061 §§13-15, 17)."""

from __future__ import annotations

import time
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class PeerState(str, Enum):
    """Registry peer connection lifecycle (RFC-0061 §14)."""

    DISCOVERED = "discovered"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    AUTHENTICATING = "authenticating"
    AUTHENTICATED = "authenticated"
    NEGOTIATING = "negotiating"
    NEGOTIATED = "negotiated"
    EXCHANGING_STATUS = "exchanging_status"
    EXCHANGING_INVENTORY = "exchanging_inventory"
    SYNCHRONIZING = "synchronizing"
    ANTI_ENTROPY = "anti_entropy"
    IDLE = "idle"
    DRAINING = "draining"
    DISCONNECTED = "disconnected"
    FAILED = "failed"


class RegistryPeer(BaseModel):
    """Registry peer representation."""

    peer_id: str  # unique registry service id
    node_id: str  # underlying hypervisor node
    address: str  # host:port
    protocol_version: str = "1.0.0"
    state: PeerState = PeerState.DISCOVERED
    last_seen_at: float = 0.0
    established_at: float = 0.0
    registry_class: str = "full"  # full | cache | archive
    supported_compression: list[str] = Field(default_factory=list)
    supported_formats: list[str] = Field(default_factory=list)
    max_object_size: int = 10 * 1024 * 1024  # 10 MB
    max_chunk_size: int = 1024 * 1024  # 1 MB
    inventory_summary: dict[str, Any] = Field(default_factory=dict)
    trust_score: float = Field(ge=0.0, le=1.0, default=0.5)
    is_bootstrap: bool = False

    @property
    def is_active(self) -> bool:
        return self.state in (
            PeerState.AUTHENTICATED,
            PeerState.NEGOTIATED,
            PeerState.EXCHANGING_STATUS,
            PeerState.EXCHANGING_INVENTORY,
            PeerState.SYNCHRONIZING,
            PeerState.ANTI_ENTROPY,
            PeerState.IDLE,
        )

    @property
    def is_available(self) -> bool:
        return self.state not in (
            PeerState.DISCONNECTED,
            PeerState.FAILED,
        )


class PeerAuthenticator:
    """
    RFC-0061 §17 — Peer authentication.

    Verifies possession of Registry Service key and claimed Service ID.
    """

    def __init__(self) -> None:
        self._known_keys: dict[str, str] = {}  # peer_id → public_key_hash
        self._authenticated: dict[str, float] = {}  # peer_id → timestamp

    def register_key(self, peer_id: str, public_key_hash: str) -> None:
        self._known_keys[peer_id] = public_key_hash

    def authenticate(
        self,
        *,
        peer_id: str,
        claimed_key_hash: str,
        signature: str,
        nonce: str,
    ) -> bool:
        """
        Authenticate a peer. In MVP, simplified: check key registration.
        Real impl would verify signature over (nonce + peer_id + timestamp).
        """
        expected = self._known_keys.get(peer_id)
        if not expected:
            return False
        if expected != claimed_key_hash:
            return False

        # In production: verify crypto signature
        # For MVP: registration = authenticated
        self._authenticated[peer_id] = time.time()
        return True

    def is_authenticated(self, peer_id: str) -> bool:
        return peer_id in self._authenticated


class PeerManager:
    """Manages registry peer connections and state transitions."""

    def __init__(self, authenticator: PeerAuthenticator | None = None) -> None:
        self._peers: dict[str, RegistryPeer] = {}
        self._authenticator = authenticator or PeerAuthenticator()

    def add_peer(self, peer: RegistryPeer) -> None:
        self._peers[peer.peer_id] = peer

    def get_peer(self, peer_id: str) -> RegistryPeer | None:
        return self._peers.get(peer_id)

    def get_active_peers(self) -> list[RegistryPeer]:
        return [p for p in self._peers.values() if p.is_active]

    def get_available_peers(self) -> list[RegistryPeer]:
        return [p for p in self._peers.values() if p.is_available]

    def transition(self, peer_id: str, new_state: PeerState) -> bool:
        """Transition a peer to a new state. Validates allowed transitions."""
        peer = self._peers.get(peer_id)
        if not peer:
            return False

        allowed = self._ALLOWED_TRANSITIONS.get(peer.state, set())
        if new_state not in allowed:
            return False

        updated = peer.model_copy(update={"state": new_state})
        if new_state in (PeerState.SYNCHRONIZING, PeerState.IDLE):
            updated = updated.model_copy(update={"last_seen_at": time.time()})
        self._peers[peer_id] = updated
        return True

    def fail_peer(self, peer_id: str) -> bool:
        peer = self._peers.get(peer_id)
        if not peer:
            return False
        updated = peer.model_copy(update={"state": PeerState.FAILED})
        self._peers[peer_id] = updated
        return True

    def disconnect_peer(self, peer_id: str) -> bool:
        peer = self._peers.get(peer_id)
        if not peer:
            return False
        updated = peer.model_copy(update={"state": PeerState.DISCONNECTED})
        self._peers[peer_id] = updated
        return True

    def authenticate_peer(
        self,
        *,
        peer_id: str,
        claimed_key_hash: str,
        signature: str,
        nonce: str,
    ) -> bool:
        if not self._authenticator.authenticate(
            peer_id=peer_id,
            claimed_key_hash=claimed_key_hash,
            signature=signature,
            nonce=nonce,
        ):
            self.fail_peer(peer_id)
            return False
        return True

    @staticmethod
    def _build_allowed_transitions() -> dict[PeerState, set[PeerState]]:
        return {
            PeerState.DISCOVERED: {PeerState.CONNECTING},
            PeerState.CONNECTING: {PeerState.CONNECTED, PeerState.FAILED},
            PeerState.CONNECTED: {PeerState.AUTHENTICATING},
            PeerState.AUTHENTICATING: {PeerState.AUTHENTICATED, PeerState.FAILED},
            PeerState.AUTHENTICATED: {PeerState.NEGOTIATING},
            PeerState.NEGOTIATING: {PeerState.NEGOTIATED, PeerState.FAILED},
            PeerState.NEGOTIATED: {PeerState.EXCHANGING_STATUS},
            PeerState.EXCHANGING_STATUS: {PeerState.EXCHANGING_INVENTORY},
            PeerState.EXCHANGING_INVENTORY: {PeerState.SYNCHRONIZING},
            PeerState.SYNCHRONIZING: {PeerState.ANTI_ENTROPY, PeerState.FAILED},
            PeerState.ANTI_ENTROPY: {PeerState.IDLE, PeerState.SYNCHRONIZING},
            PeerState.IDLE: {
                PeerState.SYNCHRONIZING,
                PeerState.ANTI_ENTROPY,
                PeerState.DRAINING,
            },
            PeerState.DRAINING: {PeerState.DISCONNECTED},
            PeerState.DISCONNECTED: {PeerState.DISCOVERED, PeerState.CONNECTING},
            PeerState.FAILED: {PeerState.DISCONNECTED, PeerState.DISCOVERED},
        }

    _ALLOWED_TRANSITIONS = _build_allowed_transitions()
