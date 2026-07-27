"""Registry Peer State Machine (RFC-0061 §§13-15, 17)."""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable
from enum import StrEnum
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, Field


class PeerState(StrEnum):
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


def peer_authentication_payload(
    *, peer_id: str, public_key: str, nonce: str, timestamp: float
) -> bytes:
    """Return the canonical payload signed for one Registry peer handshake."""
    return json.dumps(
        {
            "domain": "aidn.registry.peer-authentication.v1",
            "nonce": nonce,
            "peer_id": peer_id,
            "public_key": public_key,
            "timestamp": timestamp,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


class PeerAuthenticator:
    """
    RFC-0061 §17 — Peer authentication.

    Verifies possession of Registry Service key and claimed Service ID.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.time,
        max_clock_skew_seconds: float = 60.0,
        nonce_retention_seconds: float = 300.0,
    ) -> None:
        if max_clock_skew_seconds <= 0:
            raise ValueError("max_clock_skew_seconds must be positive")
        if nonce_retention_seconds < max_clock_skew_seconds:
            raise ValueError("nonce_retention_seconds must cover clock skew")
        self._clock = clock
        self._max_clock_skew_seconds = max_clock_skew_seconds
        self._nonce_retention_seconds = nonce_retention_seconds
        self._known_keys: dict[str, str] = {}  # peer_id -> ed25519 public key
        self._authenticated: dict[str, float] = {}  # peer_id → timestamp
        self._used_nonces: dict[tuple[str, str], float] = {}

    def register_key(self, peer_id: str, public_key: str) -> None:
        """Bind one Registry peer identity to an Ed25519 public key."""
        self._validate_public_key(public_key)
        self._known_keys[peer_id] = public_key

    def authenticate(
        self,
        *,
        peer_id: str,
        claimed_public_key: str,
        signature: str,
        nonce: str,
        timestamp: float,
    ) -> bool:
        """Authenticate a fresh Ed25519-signed peer handshake."""
        now = self._clock()
        expected = self._known_keys.get(peer_id)
        if expected is None or expected != claimed_public_key:
            return False
        if not nonce or len(nonce) > 256 or isinstance(timestamp, bool):
            return False
        if (
            not isinstance(timestamp, (int, float))
            or not math.isfinite(timestamp)
            or abs(now - timestamp) > self._max_clock_skew_seconds
        ):
            return False

        self._prune_expired_nonces(now)
        nonce_key = (peer_id, nonce)
        if nonce_key in self._used_nonces:
            return False
        if not self._verify_signature(
            public_key=claimed_public_key,
            signature=signature,
            payload=peer_authentication_payload(
                peer_id=peer_id,
                public_key=claimed_public_key,
                nonce=nonce,
                timestamp=timestamp,
            ),
        ):
            return False

        self._used_nonces[nonce_key] = now
        self._authenticated[peer_id] = now
        return True

    def is_authenticated(self, peer_id: str) -> bool:
        return peer_id in self._authenticated

    def revoke(self, peer_id: str) -> None:
        """Remove an authentication grant when its peer connection fails."""
        self._authenticated.pop(peer_id, None)

    @staticmethod
    def _validate_public_key(public_key: str) -> None:
        if not public_key.startswith("ed25519:"):
            raise ValueError("Registry peer key must use ed25519:<32-byte hex> form")
        try:
            Ed25519PublicKey.from_public_bytes(
                bytes.fromhex(public_key.removeprefix("ed25519:"))
            )
        except ValueError as error:
            raise ValueError("Registry peer key is invalid") from error

    @classmethod
    def _verify_signature(
        cls, *, public_key: str, signature: str, payload: bytes
    ) -> bool:
        try:
            cls._validate_public_key(public_key)
            if not signature.startswith("ed25519:"):
                return False
            Ed25519PublicKey.from_public_bytes(
                bytes.fromhex(public_key.removeprefix("ed25519:"))
            ).verify(bytes.fromhex(signature.removeprefix("ed25519:")), payload)
        except (InvalidSignature, ValueError):
            return False
        return True

    def _prune_expired_nonces(self, now: float) -> None:
        cutoff = now - self._nonce_retention_seconds
        self._used_nonces = {
            nonce_key: used_at
            for nonce_key, used_at in self._used_nonces.items()
            if used_at >= cutoff
        }


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
        self._authenticator.revoke(peer_id)
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
        claimed_public_key: str,
        signature: str,
        nonce: str,
        timestamp: float,
    ) -> bool:
        peer = self._peers.get(peer_id)
        if peer is None:
            return False
        if peer.state != PeerState.AUTHENTICATING:
            return False
        if not self._authenticator.authenticate(
            peer_id=peer_id,
            claimed_public_key=claimed_public_key,
            signature=signature,
            nonce=nonce,
            timestamp=timestamp,
        ):
            self.fail_peer(peer_id)
            return False
        return self.transition(peer_id, PeerState.AUTHENTICATED)

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
