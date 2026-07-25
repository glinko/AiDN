"""Tests for peer discovery (RFC-0042 §27-32)."""

import pytest
from aidn_hypervisor.dispatcher.discovery import (
    DiscoveryManager,
    PeerAddress,
    PeerRecord,
    TrustState,
)


# ── PeerRecord tests ─────────────────────────────────────────────────────

class TestPeerRecord:
    def test_new_peer_untrusted(self):
        peer = PeerRecord(
            peer_id="test-001",
            hypervisor_id="hv-001",
            discovery_source="STATIC_CONFIGURATION",
        )
        assert peer.trust_state == "UNVERIFIED"
        assert not peer.is_trusted
        assert not peer.is_blocked
        assert peer.success_rate == 0.0

    def test_success_rate_calculation(self):
        peer = PeerRecord(
            peer_id="test-001",
            hypervisor_id="hv-001",
            connection_success_count=8,
            connection_failure_count=2,
        )
        assert peer.success_rate == 0.8

    def test_authenticated_peer_is_trusted(self):
        peer = PeerRecord(
            peer_id="test-001",
            hypervisor_id="hv-001",
            trust_state="AUTHENTICATED",
        )
        assert peer.is_trusted

    def test_established_peer_is_trusted(self):
        peer = PeerRecord(
            peer_id="test-001",
            hypervisor_id="hv-001",
            trust_state="ESTABLISHED",
        )
        assert peer.is_trusted

    def test_quarantined_peer_is_blocked(self):
        peer = PeerRecord(
            peer_id="test-001",
            hypervisor_id="hv-001",
            trust_state="QUARANTINED",
        )
        assert peer.is_blocked

    def test_revoked_peer_is_blocked(self):
        peer = PeerRecord(
            peer_id="test-001",
            hypervisor_id="hv-001",
            trust_state="REVOKED",
        )
        assert peer.is_blocked


# ── DiscoveryManager tests ───────────────────────────────────────────────

class TestDiscoveryManager:
    @pytest.fixture
    def manager(self):
        return DiscoveryManager()

    def test_add_static_peers(self, manager):
        addresses = [
            PeerAddress(host="192.168.1.1", port=443),
            PeerAddress(host="10.0.0.1", port=443, address_class="PRIVATE_DIRECT"),
        ]
        manager.add_static_peers(addresses)
        assert manager.peer_count == 2
        assert manager.discovery_diversity >= 1

    def test_add_static_seed(self, manager):
        manager.add_static_seed("seed1.example.com", 443)
        assert manager.peer_count == 1
        peer = manager.list_peers()[0]
        assert peer.discovery_source == "STATIC_CONFIGURATION"

    def test_duplicate_static_peer_not_added(self, manager):
        manager.add_static_seed("192.168.1.1", 443)
        manager.add_static_seed("192.168.1.1", 443)
        assert manager.peer_count == 1

    def test_operator_add_peer(self, manager):
        addresses = [PeerAddress(host="operator-peer.local", port=443)]
        peer = manager.operator_add_peer(
            peer_id="op-001",
            addresses=addresses,
            hypervisor_id="hv-operator",
        )
        assert peer.peer_id == "op-001"
        assert peer.discovery_source == "OPERATOR_INPUT"
        assert peer.hypervisor_id == "hv-operator"

    def test_peer_exchange(self, manager):
        addresses = [
            PeerAddress(host="pex-peer1.example.com", port=443),
            PeerAddress(host="pex-peer2.example.com", port=443),
        ]
        records = manager.peer_exchange(
            addresses,
            recommended_by="hv-friend",
        )
        assert len(records) == 2
        assert manager.peer_count == 2
        for r in records:
            assert r.recommended_by == "hv-friend"
            assert r.discovery_source == "PEER_EXCHANGE"

    def test_list_peers_filter_by_trust_state(self, manager):
        manager.add_static_seed("peer1.example.com", 443)
        manager.add_static_seed("peer2.example.com", 443)
        manager.update_trust_state(
            f"static:peer1.example.com:443",
            "AUTHENTICATED",
        )
        trusted = manager.list_peers(trust_state="AUTHENTICATED")
        assert len(trusted) == 1
        untrusted = manager.list_peers(trust_state="DISCOVERED")
        assert len(untrusted) == 1

    def test_list_trusted_peers(self, manager):
        manager.add_static_seed("peer1.example.com", 443)
        manager.add_static_seed("peer2.example.com", 443)
        manager.update_trust_state(
            f"static:peer1.example.com:443",
            "ESTABLISHED",
        )
        trusted = manager.list_trusted_peers()
        assert len(trusted) == 1

    def test_list_untrusted_peers(self, manager):
        manager.add_static_seed("peer1.example.com", 443)
        manager.add_static_seed("peer2.example.com", 443)
        manager.update_trust_state(
            f"static:peer1.example.com:443",
            "ESTABLISHED",
        )
        untrusted = manager.list_untrusted_peers()
        assert len(untrusted) == 1

    def test_update_trust_state(self, manager):
        manager.add_static_seed("peer1.example.com", 443)
        peer_id = f"static:peer1.example.com:443"
        manager.update_trust_state(peer_id, "HANDSHAKE_PENDING")
        peer = manager.get_peer(peer_id)
        assert peer.trust_state == "HANDSHAKE_PENDING"
        assert peer.last_seen is not None

    def test_record_connection_success(self, manager):
        manager.add_static_seed("peer1.example.com", 443)
        peer_id = f"static:peer1.example.com:443"
        manager.record_connection_success(peer_id)
        manager.record_connection_success(peer_id)
        peer = manager.get_peer(peer_id)
        assert peer.connection_success_count == 2
        assert peer.success_rate == 1.0

    def test_record_connection_failure(self, manager):
        manager.add_static_seed("peer1.example.com", 443)
        peer_id = f"static:peer1.example.com:443"
        manager.record_connection_success(peer_id)
        manager.record_connection_failure(peer_id)
        peer = manager.get_peer(peer_id)
        assert peer.success_rate == 0.5

    def test_quarantine_peer(self, manager):
        manager.add_static_seed("peer1.example.com", 443)
        peer_id = f"static:peer1.example.com:443"
        manager.quarantine_peer(peer_id)
        peer = manager.get_peer(peer_id)
        assert peer.trust_state == "QUARANTINED"
        assert peer.is_blocked

    def test_revoke_peer(self, manager):
        manager.add_static_seed("peer1.example.com", 443)
        peer_id = f"static:peer1.example.com:443"
        manager.revoke_peer(peer_id)
        peer = manager.get_peer(peer_id)
        assert peer.trust_state == "REVOKED"
        assert peer.is_blocked

    def test_discovery_diversity(self, manager):
        # Initially 0 sources
        assert manager.discovery_diversity == 0
        manager.add_static_seed("peer1.example.com", 443)
        assert manager.discovery_diversity >= 1
        manager.operator_add_peer(
            "op-001",
            [PeerAddress(host="op.local", port=443)],
        )
        assert manager.discovery_diversity >= 2

    def test_get_nonexistent_peer(self, manager):
        result = manager.get_peer("nonexistent")
        assert result is None
