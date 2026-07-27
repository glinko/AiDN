"""Tests for registry/peer — Peer State Machine, Auth, Manager (RFC-0061 §§13-17)."""

from __future__ import annotations

import time

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from aidn_hypervisor.registry import (
    PeerAuthenticator,
    PeerManager,
    PeerState,
    RegistryPeer,
)
from aidn_hypervisor.registry.peer import peer_authentication_payload


def _peer_key() -> tuple[Ed25519PrivateKey, str]:
    private_key = Ed25519PrivateKey.generate()
    public_key = f"ed25519:{private_key.public_key().public_bytes_raw().hex()}"
    return private_key, public_key


def _peer_signature(
    private_key: Ed25519PrivateKey,
    *,
    peer_id: str,
    public_key: str,
    nonce: str,
    timestamp: float,
) -> str:
    return "ed25519:" + private_key.sign(
        peer_authentication_payload(
            peer_id=peer_id,
            public_key=public_key,
            nonce=nonce,
            timestamp=timestamp,
        )
    ).hex()


def _move_to_authenticating(manager: PeerManager, peer_id: str) -> None:
    assert manager.transition(peer_id, PeerState.CONNECTING)
    assert manager.transition(peer_id, PeerState.CONNECTED)
    assert manager.transition(peer_id, PeerState.AUTHENTICATING)


# ---------------------------------------------------------------------------
# RegistryPeer creation & properties
# ---------------------------------------------------------------------------

def test_peer_creation():
    peer = RegistryPeer(
        peer_id="peer-1",
        node_id="node-1",
        address="10.0.0.1:9000",
    )
    assert peer.peer_id == "peer-1"
    assert peer.node_id == "node-1"
    assert peer.address == "10.0.0.1:9000"
    assert peer.protocol_version == "1.0.0"
    assert peer.state == PeerState.DISCOVERED
    assert peer.registry_class == "full"
    assert peer.trust_score == 0.5
    assert peer.is_bootstrap is False


def test_peer_is_active():
    peer = RegistryPeer(
        peer_id="p1", node_id="n1", address="a:9000",
        state=PeerState.AUTHENTICATED,
    )
    assert peer.is_active is True

    for s in (
        PeerState.NEGOTIATED,
        PeerState.EXCHANGING_STATUS,
        PeerState.EXCHANGING_INVENTORY,
        PeerState.SYNCHRONIZING,
        PeerState.ANTI_ENTROPY,
        PeerState.IDLE,
    ):
        p = RegistryPeer(peer_id="p1", node_id="n1", address="a:9000", state=s)
        assert p.is_active is True, f"{s} should be active"

    for s in (
        PeerState.DISCOVERED,
        PeerState.CONNECTING,
        PeerState.CONNECTED,
        PeerState.AUTHENTICATING,
        PeerState.DRAINING,
        PeerState.DISCONNECTED,
        PeerState.FAILED,
    ):
        p = RegistryPeer(peer_id="p1", node_id="n1", address="a:9000", state=s)
        assert p.is_active is False, f"{s} should NOT be active"


def test_peer_is_available():
    peer = RegistryPeer(
        peer_id="p1", node_id="n1", address="a:9000",
        state=PeerState.IDLE,
    )
    assert peer.is_available is True

    p_disconnected = RegistryPeer(
        peer_id="p1", node_id="n1", address="a:9000",
        state=PeerState.DISCONNECTED,
    )
    assert p_disconnected.is_available is False

    p_failed = RegistryPeer(
        peer_id="p1", node_id="n1", address="a:9000",
        state=PeerState.FAILED,
    )
    assert p_failed.is_available is False


def test_peer_bootstrap():
    peer = RegistryPeer(
        peer_id="bootstrap-1",
        node_id="n1",
        address="10.0.0.1:9000",
        is_bootstrap=True,
    )
    assert peer.is_bootstrap is True


# ---------------------------------------------------------------------------
# PeerState enum
# ---------------------------------------------------------------------------

def test_peer_state_enum():
    assert PeerState.DISCOVERED.value == "discovered"
    assert PeerState.CONNECTING.value == "connecting"
    assert PeerState.CONNECTED.value == "connected"
    assert PeerState.FAILED.value == "failed"
    assert PeerState.IDLE.value == "idle"
    assert PeerState.SYNCHRONIZING.value == "synchronizing"
    assert PeerState.ANTI_ENTROPY.value == "anti_entropy"
    assert PeerState.DRAINING.value == "draining"
    assert PeerState.DISCONNECTED.value == "disconnected"


def test_peer_model_copy():
    peer = RegistryPeer(
        peer_id="p1", node_id="n1", address="a:9000",
        state=PeerState.DISCOVERED,
    )
    updated = peer.model_copy(update={"state": PeerState.CONNECTING})
    assert updated.state == PeerState.CONNECTING
    assert peer.state == PeerState.DISCOVERED  # original unchanged


# ---------------------------------------------------------------------------
# PeerAuthenticator
# ---------------------------------------------------------------------------

def test_authenticator_register_key():
    auth = PeerAuthenticator()
    _private_key, public_key = _peer_key()
    auth.register_key("peer-1", public_key)
    assert auth._known_keys["peer-1"] == public_key


def test_authenticate_valid():
    auth = PeerAuthenticator()
    private_key, public_key = _peer_key()
    auth.register_key("peer-1", public_key)
    timestamp = time.time()
    result = auth.authenticate(
        peer_id="peer-1",
        claimed_public_key=public_key,
        signature=_peer_signature(
            private_key,
            peer_id="peer-1",
            public_key=public_key,
            nonce="nonce-1",
            timestamp=timestamp,
        ),
        nonce="nonce-1",
        timestamp=timestamp,
    )
    assert result is True


def test_authenticate_unknown():
    auth = PeerAuthenticator()
    private_key, public_key = _peer_key()
    timestamp = time.time()
    result = auth.authenticate(
        peer_id="unknown-peer",
        claimed_public_key=public_key,
        signature=_peer_signature(
            private_key,
            peer_id="unknown-peer",
            public_key=public_key,
            nonce="nonce-1",
            timestamp=timestamp,
        ),
        nonce="nonce-1",
        timestamp=timestamp,
    )
    assert result is False


def test_authenticate_wrong_key():
    auth = PeerAuthenticator()
    _registered_private_key, registered_public_key = _peer_key()
    private_key, public_key = _peer_key()
    auth.register_key("peer-1", registered_public_key)
    timestamp = time.time()
    result = auth.authenticate(
        peer_id="peer-1",
        claimed_public_key=public_key,
        signature=_peer_signature(
            private_key,
            peer_id="peer-1",
            public_key=public_key,
            nonce="nonce-1",
            timestamp=timestamp,
        ),
        nonce="nonce-1",
        timestamp=timestamp,
    )
    assert result is False


def test_is_authenticated():
    auth = PeerAuthenticator()
    private_key, public_key = _peer_key()
    auth.register_key("peer-1", public_key)
    assert auth.is_authenticated("peer-1") is False
    timestamp = time.time()
    auth.authenticate(
        peer_id="peer-1",
        claimed_public_key=public_key,
        signature=_peer_signature(
            private_key,
            peer_id="peer-1",
            public_key=public_key,
            nonce="nonce-1",
            timestamp=timestamp,
        ),
        nonce="nonce-1",
        timestamp=timestamp,
    )
    assert auth.is_authenticated("peer-1") is True


def test_authenticate_rejects_tampered_signature() -> None:
    _private_key, public_key = _peer_key()
    timestamp = 100.0
    auth = PeerAuthenticator(clock=lambda: timestamp)
    auth.register_key("peer-1", public_key)
    assert auth.authenticate(
        peer_id="peer-1",
        claimed_public_key=public_key,
        signature="ed25519:" + "00" * 64,
        nonce="nonce-1",
        timestamp=timestamp,
    ) is False


def test_authenticate_rejects_stale_or_replayed_challenge() -> None:
    now = 100.0
    auth = PeerAuthenticator(clock=lambda: now)
    private_key, public_key = _peer_key()
    auth.register_key("peer-1", public_key)
    stale_timestamp = now - 61.0
    assert auth.authenticate(
        peer_id="peer-1",
        claimed_public_key=public_key,
        signature=_peer_signature(
            private_key,
            peer_id="peer-1",
            public_key=public_key,
            nonce="nonce-stale",
            timestamp=stale_timestamp,
        ),
        nonce="nonce-stale",
        timestamp=stale_timestamp,
    ) is False

    timestamp = now
    signature = _peer_signature(
        private_key,
        peer_id="peer-1",
        public_key=public_key,
        nonce="nonce-once",
        timestamp=timestamp,
    )
    assert auth.authenticate(
        peer_id="peer-1",
        claimed_public_key=public_key,
        signature=signature,
        nonce="nonce-once",
        timestamp=timestamp,
    ) is True
    assert auth.authenticate(
        peer_id="peer-1",
        claimed_public_key=public_key,
        signature=signature,
        nonce="nonce-once",
        timestamp=timestamp,
    ) is False


def test_authenticate_rejects_non_finite_timestamp() -> None:
    auth = PeerAuthenticator(clock=lambda: 100.0)
    private_key, public_key = _peer_key()
    auth.register_key("peer-1", public_key)
    assert auth.authenticate(
        peer_id="peer-1",
        claimed_public_key=public_key,
        signature=_peer_signature(
            private_key,
            peer_id="peer-1",
            public_key=public_key,
            nonce="nonce-1",
            timestamp=float("nan"),
        ),
        nonce="nonce-1",
        timestamp=float("nan"),
    ) is False


# ---------------------------------------------------------------------------
# PeerManager — basic operations
# ---------------------------------------------------------------------------

def test_peer_manager_add():
    mgr = PeerManager()
    peer = RegistryPeer(peer_id="p1", node_id="n1", address="a:9000")
    mgr.add_peer(peer)
    assert mgr.get_peer("p1") is not None


def test_peer_manager_get():
    mgr = PeerManager()
    peer = RegistryPeer(peer_id="p1", node_id="n1", address="a:9000")
    mgr.add_peer(peer)
    got = mgr.get_peer("p1")
    assert got is not None
    assert got.peer_id == "p1"
    assert mgr.get_peer("nonexistent") is None


def test_peer_manager_get_active():
    mgr = PeerManager()
    idle = RegistryPeer(peer_id="idle", node_id="n1", address="a:9000",
                        state=PeerState.IDLE)
    failed = RegistryPeer(peer_id="failed", node_id="n1", address="a:9000",
                         state=PeerState.FAILED)
    mgr.add_peer(idle)
    mgr.add_peer(failed)
    active = mgr.get_active_peers()
    assert len(active) == 1
    assert active[0].peer_id == "idle"


def test_peer_manager_get_available():
    mgr = PeerManager()
    idle = RegistryPeer(peer_id="idle", node_id="n1", address="a:9000",
                        state=PeerState.IDLE)
    disconnected = RegistryPeer(
        peer_id="disc", node_id="n1", address="a:9000",
        state=PeerState.DISCONNECTED,
    )
    mgr.add_peer(idle)
    mgr.add_peer(disconnected)
    avail = mgr.get_available_peers()
    assert len(avail) == 1
    assert avail[0].peer_id == "idle"


# ---------------------------------------------------------------------------
# PeerManager — state transitions
# ---------------------------------------------------------------------------

def test_peer_transition_valid():
    mgr = PeerManager()
    mgr.add_peer(RegistryPeer(peer_id="p1", node_id="n1", address="a:9000"))
    ok = mgr.transition("p1", PeerState.CONNECTING)
    assert ok is True
    assert mgr.get_peer("p1").state == PeerState.CONNECTING


def test_peer_transition_invalid():
    mgr = PeerManager()
    mgr.add_peer(RegistryPeer(peer_id="p1", node_id="n1", address="a:9000"))
    # DISCOVERED → IDLE is not allowed
    ok = mgr.transition("p1", PeerState.IDLE)
    assert ok is False
    assert mgr.get_peer("p1").state == PeerState.DISCOVERED


def test_peer_fail():
    mgr = PeerManager()
    mgr.add_peer(RegistryPeer(peer_id="p1", node_id="n1", address="a:9000"))
    ok = mgr.fail_peer("p1")
    assert ok is True
    assert mgr.get_peer("p1").state == PeerState.FAILED
    assert mgr.fail_peer("nonexistent") is False


def test_peer_disconnect():
    mgr = PeerManager()
    mgr.add_peer(RegistryPeer(peer_id="p1", node_id="n1", address="a:9000"))
    ok = mgr.disconnect_peer("p1")
    assert ok is True
    assert mgr.get_peer("p1").state == PeerState.DISCONNECTED
    assert mgr.disconnect_peer("nonexistent") is False


# ---------------------------------------------------------------------------
# PeerManager — authenticate_peer
# ---------------------------------------------------------------------------

def test_peer_authenticate_success():
    auth = PeerAuthenticator()
    private_key, public_key = _peer_key()
    auth.register_key("p1", public_key)
    mgr = PeerManager(authenticator=auth)
    mgr.add_peer(RegistryPeer(peer_id="p1", node_id="n1", address="a:9000"))
    _move_to_authenticating(mgr, "p1")
    timestamp = time.time()
    ok = mgr.authenticate_peer(
        peer_id="p1",
        claimed_public_key=public_key,
        signature=_peer_signature(
            private_key,
            peer_id="p1",
            public_key=public_key,
            nonce="nonce-1",
            timestamp=timestamp,
        ),
        nonce="nonce-1",
        timestamp=timestamp,
    )
    assert ok is True
    assert auth.is_authenticated("p1") is True
    assert mgr.get_peer("p1").state == PeerState.AUTHENTICATED


def test_peer_authenticate_fail():
    auth = PeerAuthenticator()
    _private_key, public_key = _peer_key()
    auth.register_key("p1", public_key)
    mgr = PeerManager(authenticator=auth)
    mgr.add_peer(RegistryPeer(peer_id="p1", node_id="n1", address="a:9000"))
    _move_to_authenticating(mgr, "p1")
    timestamp = time.time()
    ok = mgr.authenticate_peer(
        peer_id="p1",
        claimed_public_key=public_key,
        signature="ed25519:" + "00" * 64,
        nonce="nonce-1",
        timestamp=timestamp,
    )
    assert ok is False
    assert mgr.get_peer("p1").state == PeerState.FAILED


def test_peer_manager_rejects_authentication_outside_handshake_state() -> None:
    auth = PeerAuthenticator()
    private_key, public_key = _peer_key()
    auth.register_key("p1", public_key)
    mgr = PeerManager(authenticator=auth)
    mgr.add_peer(RegistryPeer(peer_id="p1", node_id="n1", address="a:9000"))
    timestamp = time.time()

    assert mgr.authenticate_peer(
        peer_id="p1",
        claimed_public_key=public_key,
        signature=_peer_signature(
            private_key,
            peer_id="p1",
            public_key=public_key,
            nonce="nonce-1",
            timestamp=timestamp,
        ),
        nonce="nonce-1",
        timestamp=timestamp,
    ) is False
    assert auth.is_authenticated("p1") is False


# ---------------------------------------------------------------------------
# PeerManager — full lifecycle
# ---------------------------------------------------------------------------

def test_peer_lifecycle_full():
    mgr = PeerManager()
    mgr.add_peer(RegistryPeer(peer_id="p1", node_id="n1", address="a:9000"))

    assert mgr.transition("p1", PeerState.CONNECTING) is True
    assert mgr.transition("p1", PeerState.CONNECTED) is True
    assert mgr.transition("p1", PeerState.AUTHENTICATING) is True
    assert mgr.transition("p1", PeerState.AUTHENTICATED) is True
    assert mgr.transition("p1", PeerState.NEGOTIATING) is True
    assert mgr.transition("p1", PeerState.NEGOTIATED) is True
    assert mgr.transition("p1", PeerState.EXCHANGING_STATUS) is True
    assert mgr.transition("p1", PeerState.EXCHANGING_INVENTORY) is True
    assert mgr.transition("p1", PeerState.SYNCHRONIZING) is True
    assert mgr.transition("p1", PeerState.ANTI_ENTROPY) is True
    assert mgr.transition("p1", PeerState.IDLE) is True


def test_peer_state_transitions():
    mgr = PeerManager()
    mgr.add_peer(RegistryPeer(peer_id="p1", node_id="n1", address="a:9000"))

    # DISCOVERED → CONNECTING → CONNECTED → AUTHENTICATING → AUTHENTICATED
    assert mgr.transition("p1", PeerState.CONNECTING)
    assert mgr.transition("p1", PeerState.CONNECTED)
    assert mgr.transition("p1", PeerState.AUTHENTICATING)
    assert mgr.transition("p1", PeerState.AUTHENTICATED)

    # AUTHENTICATED → NEGOTIATING → NEGOTIATED
    assert mgr.transition("p1", PeerState.NEGOTIATING)
    assert mgr.transition("p1", PeerState.NEGOTIATED)

    # NEGOTIATED → EXCHANGING_STATUS → EXCHANGING_INVENTORY → SYNCHRONIZING
    assert mgr.transition("p1", PeerState.EXCHANGING_STATUS)
    assert mgr.transition("p1", PeerState.EXCHANGING_INVENTORY)
    assert mgr.transition("p1", PeerState.SYNCHRONIZING)

    # SYNCHRONIZING → ANTI_ENTROPY → IDLE
    assert mgr.transition("p1", PeerState.ANTI_ENTROPY)
    assert mgr.transition("p1", PeerState.IDLE)

    # IDLE → SYNCHRONIZING (re-sync)
    assert mgr.transition("p1", PeerState.SYNCHRONIZING)

    # IDLE → DRAINING → DISCONNECTED
    assert mgr.transition("p1", PeerState.ANTI_ENTROPY)
    assert mgr.transition("p1", PeerState.IDLE)
    assert mgr.transition("p1", PeerState.DRAINING)
    assert mgr.transition("p1", PeerState.DISCONNECTED)


# ---------------------------------------------------------------------------
# PeerManager — last_seen_at update
# ---------------------------------------------------------------------------

def test_peer_last_seen_update():
    mgr = PeerManager()
    peer = RegistryPeer(peer_id="p1", node_id="n1", address="a:9000")
    mgr.add_peer(peer)

    before = time.time()
    mgr.transition("p1", PeerState.CONNECTING)
    mgr.transition("p1", PeerState.CONNECTED)
    mgr.transition("p1", PeerState.AUTHENTICATING)
    mgr.transition("p1", PeerState.AUTHENTICATED)
    mgr.transition("p1", PeerState.NEGOTIATING)
    mgr.transition("p1", PeerState.NEGOTIATED)
    mgr.transition("p1", PeerState.EXCHANGING_STATUS)
    mgr.transition("p1", PeerState.EXCHANGING_INVENTORY)

    # SYNCHRONIZING should update last_seen_at
    mgr.transition("p1", PeerState.SYNCHRONIZING)
    after_sync = time.time()
    p = mgr.get_peer("p1")
    assert p is not None
    assert before <= p.last_seen_at <= after_sync

    # IDLE should also update last_seen_at
    mgr.transition("p1", PeerState.ANTI_ENTROPY)
    before_idle = time.time()
    mgr.transition("p1", PeerState.IDLE)
    after_idle = time.time()
    p = mgr.get_peer("p1")
    assert before_idle <= p.last_seen_at <= after_idle


# ---------------------------------------------------------------------------
# PeerManager — multiple peers
# ---------------------------------------------------------------------------

def test_multiple_peers():
    mgr = PeerManager()
    for i in range(5):
        mgr.add_peer(RegistryPeer(
            peer_id=f"p{i}",
            node_id=f"n{i}",
            address=f"10.0.0.{i}:9000",
        ))

    assert len(mgr._peers) == 5
    assert len(mgr.get_available_peers()) == 5
    assert len(mgr.get_active_peers()) == 0  # all DISCOVERED

    mgr.transition("p0", PeerState.CONNECTING)
    mgr.transition("p0", PeerState.CONNECTED)
    mgr.transition("p0", PeerState.AUTHENTICATING)
    mgr.transition("p0", PeerState.AUTHENTICATED)
    assert len(mgr.get_active_peers()) == 1


# ---------------------------------------------------------------------------
# PeerManager — trust score validation
# ---------------------------------------------------------------------------

def test_peer_trust_score():
    peer = RegistryPeer(
        peer_id="p1", node_id="n1", address="a:9000",
        trust_score=0.8,
    )
    assert peer.trust_score == 0.8

    with pytest.raises(ValidationError):
        RegistryPeer(
            peer_id="p1", node_id="n1", address="a:9000",
            trust_score=1.5,
        )

    with pytest.raises(ValidationError):
        RegistryPeer(
            peer_id="p1", node_id="n1", address="a:9000",
            trust_score=-0.1,
        )


# ---------------------------------------------------------------------------
# Disconnected → Discovered / Failed → Disconnected
# ---------------------------------------------------------------------------

def test_disconnected_to_discovered():
    mgr = PeerManager()
    mgr.add_peer(RegistryPeer(peer_id="p1", node_id="n1", address="a:9000"))
    mgr.transition("p1", PeerState.CONNECTING)
    mgr.transition("p1", PeerState.CONNECTED)
    mgr.transition("p1", PeerState.AUTHENTICATING)
    mgr.transition("p1", PeerState.AUTHENTICATED)
    mgr.transition("p1", PeerState.NEGOTIATING)
    mgr.transition("p1", PeerState.NEGOTIATED)
    mgr.transition("p1", PeerState.EXCHANGING_STATUS)
    mgr.transition("p1", PeerState.EXCHANGING_INVENTORY)
    mgr.transition("p1", PeerState.SYNCHRONIZING)
    mgr.transition("p1", PeerState.ANTI_ENTROPY)
    mgr.transition("p1", PeerState.IDLE)
    mgr.transition("p1", PeerState.DRAINING)
    mgr.transition("p1", PeerState.DISCONNECTED)

    # DISCONNECTED → DISCOVERED
    assert mgr.transition("p1", PeerState.DISCOVERED) is True
    assert mgr.get_peer("p1").state == PeerState.DISCOVERED


def test_failed_to_disconnected():
    mgr = PeerManager()
    mgr.add_peer(RegistryPeer(peer_id="p1", node_id="n1", address="a:9000"))
    mgr.transition("p1", PeerState.CONNECTING)
    mgr.transition("p1", PeerState.FAILED)

    assert mgr.transition("p1", PeerState.DISCONNECTED) is True
    assert mgr.get_peer("p1").state == PeerState.DISCONNECTED
