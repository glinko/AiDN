"""Tests for registry/discovery — Registry Peer Discovery + Auto Sync (M9-S5)."""

from __future__ import annotations

import time

import pytest

from aidn_hypervisor.registry import ImmutableObjectStore
from aidn_hypervisor.registry.discovery import (
    AutoSyncController,
    DiscoveryConfig,
    PeerDiscoveryEvent,
    RegistryPeerDiscovery,
)
from aidn_hypervisor.registry.peer import PeerState
from aidn_hypervisor.registry.replicator import RegistryReplicator

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_store() -> ImmutableObjectStore:
    return ImmutableObjectStore()


def _make_replicator(
    node_id: str = "node-a",
    store: ImmutableObjectStore | None = None,
) -> RegistryReplicator:
    return RegistryReplicator(
        node_id=node_id,
        store=store or _make_store(),
    )


def _make_discovery(
    *,
    node_id: str = "node-a",
    replicator: RegistryReplicator | None = None,
    config: DiscoveryConfig | None = None,
) -> RegistryPeerDiscovery:
    return RegistryPeerDiscovery(
        node_id=node_id,
        replicator=replicator,
        config=config,
    )


# ---------------------------------------------------------------------------
# DiscoveryConfig tests
# ---------------------------------------------------------------------------


class TestDiscoveryConfig:
    def test_discovery_config_defaults(self) -> None:
        cfg = DiscoveryConfig()
        assert cfg.enabled is True
        assert cfg.discovery_interval_seconds == 60
        assert cfg.max_peers == 20
        assert cfg.bootstrap_peers == []
        assert cfg.auto_connect is True
        assert cfg.require_signed_records is False
        assert cfg.peer_ttl_seconds == 3600
        assert cfg.min_sync_interval_seconds == 30

    def test_discovery_config_custom(self) -> None:
        cfg = DiscoveryConfig(
            enabled=False,
            max_peers=10,
            bootstrap_peers=["10.0.0.1:50051"],
            auto_connect=False,
        )
        assert cfg.enabled is False
        assert cfg.max_peers == 10
        assert cfg.bootstrap_peers == ["10.0.0.1:50051"]
        assert cfg.auto_connect is False

    def test_discovery_config_frozen(self) -> None:
        cfg = DiscoveryConfig()
        with pytest.raises(Exception):
            cfg.enabled = False  # type: ignore


# ---------------------------------------------------------------------------
# PeerDiscoveryEvent tests
# ---------------------------------------------------------------------------


class TestPeerDiscoveryEvent:
    def test_discovery_event_model(self) -> None:
        event = PeerDiscoveryEvent(
            event_type="peer_found",
            peer_id="peer-1",
            details={"address": "10.0.0.1:50051"},
        )
        assert event.event_type == "peer_found"
        assert event.peer_id == "peer-1"
        assert event.details["address"] == "10.0.0.1:50051"
        assert event.timestamp > 0

    def test_discovery_event_defaults(self) -> None:
        event = PeerDiscoveryEvent(
            event_type="peer_connected",
            peer_id="peer-2",
        )
        assert event.details == {}
        assert event.timestamp > 0


# ---------------------------------------------------------------------------
# RegistryPeerDiscovery tests
# ---------------------------------------------------------------------------


class TestRegistryPeerDiscovery:
    def test_discovery_init(self) -> None:
        disc = _make_discovery()
        assert disc._node_id == "node-a"
        assert disc._replicator is None
        assert disc.config.enabled is True
        assert disc.get_all_peers() == []
        assert disc.get_discovery_events() == []

    def test_discovery_init_with_replicator(self) -> None:
        repl = _make_replicator()
        disc = _make_discovery(replicator=repl)
        assert disc._replicator is repl

    def test_register_callback(self) -> None:
        disc = _make_discovery()
        events: list[PeerDiscoveryEvent] = []
        disc.register_callback(events.append)
        assert len(disc._callbacks) == 1

    def test_emit_event(self) -> None:
        disc = _make_discovery()
        received: list[PeerDiscoveryEvent] = []
        disc.register_callback(received.append)

        event = PeerDiscoveryEvent(
            event_type="peer_found",
            peer_id="peer-1",
        )
        disc._emit_event(event)

        assert len(received) == 1
        assert received[0].peer_id == "peer-1"
        assert len(disc._events) == 1

    def test_add_bootstrap_peer(self) -> None:
        disc = _make_discovery()
        disc.add_bootstrap_peer("10.0.0.1:50051")
        assert "10.0.0.1:50051" in disc.config.bootstrap_peers
        assert len(disc.config.bootstrap_peers) == 1

    def test_add_bootstrap_peer_duplicate(self) -> None:
        disc = _make_discovery()
        disc.add_bootstrap_peer("10.0.0.1:50051")
        disc.add_bootstrap_peer("10.0.0.1:50051")
        assert len(disc.config.bootstrap_peers) == 1

    def test_discover_peer(self) -> None:
        disc = _make_discovery()
        peer = disc.discover_peer(
            peer_id="peer-1",
            address="10.0.0.1:50051",
        )
        assert peer is not None
        assert peer.peer_id == "peer-1"
        assert peer.address == "10.0.0.1:50051"
        # Auto-connect enabled → state is CONNECTED
        assert peer.state == PeerState.CONNECTED

    def test_discover_peer_no_auto_connect(self) -> None:
        cfg = DiscoveryConfig(auto_connect=False)
        disc = _make_discovery(config=cfg)
        peer = disc.discover_peer(
            peer_id="peer-1",
            address="10.0.0.1:50051",
        )
        assert peer is not None
        assert peer.state == PeerState.CONNECTING

    def test_discover_peer_duplicate(self) -> None:
        disc = _make_discovery()
        p1 = disc.discover_peer(peer_id="peer-1", address="10.0.0.1:50051")
        time.sleep(0.01)
        p2 = disc.discover_peer(peer_id="peer-1", address="10.0.0.2:50051")
        assert p2 is not None
        assert p2.last_seen_at > p1.last_seen_at
        # Still only one in the dict
        assert len(disc.get_all_peers()) == 1

    def test_discover_peer_max_reached(self) -> None:
        cfg = DiscoveryConfig(max_peers=2)
        disc = _make_discovery(config=cfg)
        disc.discover_peer(peer_id="peer-1", address="10.0.0.1:50051")
        disc.discover_peer(peer_id="peer-2", address="10.0.0.2:50051")
        result = disc.discover_peer(peer_id="peer-3", address="10.0.0.3:50051")
        assert result is None

    def test_discover_peer_auto_connect(self) -> None:
        repl = _make_replicator()
        disc = _make_discovery(replicator=repl)
        disc.discover_peer(peer_id="peer-1", address="10.0.0.1:50051")
        # Peer should be connected in replicator
        state = repl.get_peer_state("peer-1")
        assert state is not None
        assert state.connected is True

    def test_lose_peer(self) -> None:
        disc = _make_discovery()
        disc.discover_peer(peer_id="peer-1", address="10.0.0.1:50051")
        disc.lose_peer("peer-1")
        peer = disc.get_peer("peer-1")
        assert peer is not None
        assert peer.state == PeerState.DISCONNECTED

    def test_lose_unknown_peer(self) -> None:
        disc = _make_discovery()
        disc.lose_peer("nonexistent")
        # Should not raise
        assert disc.get_all_peers() == []

    def test_lose_peer_with_replicator(self) -> None:
        repl = _make_replicator()
        disc = _make_discovery(replicator=repl)
        disc.discover_peer(peer_id="peer-1", address="10.0.0.1:50051")
        disc.lose_peer("peer-1")
        state = repl.get_peer_state("peer-1")
        assert state is not None
        assert state.connected is False

    def test_get_peer(self) -> None:
        disc = _make_discovery()
        disc.discover_peer(peer_id="peer-1", address="10.0.0.1:50051")
        peer = disc.get_peer("peer-1")
        assert peer is not None
        assert peer.peer_id == "peer-1"

    def test_get_peer_not_found(self) -> None:
        disc = _make_discovery()
        assert disc.get_peer("nonexistent") is None

    def test_get_all_peers(self) -> None:
        disc = _make_discovery()
        disc.discover_peer(peer_id="peer-1", address="10.0.0.1:50051")
        disc.discover_peer(peer_id="peer-2", address="10.0.0.2:50051")
        peers = disc.get_all_peers()
        assert len(peers) == 2

    def test_get_connected_peers(self) -> None:
        disc = _make_discovery()
        disc.discover_peer(peer_id="peer-1", address="10.0.0.1:50051")
        disc.discover_peer(peer_id="peer-2", address="10.0.0.2:50051")
        disc.lose_peer("peer-2")
        connected = disc.get_connected_peers()
        assert len(connected) == 1
        assert connected[0].peer_id == "peer-1"

    def test_get_discovery_events(self) -> None:
        disc = _make_discovery()
        disc.discover_peer(peer_id="peer-1", address="10.0.0.1:50051")
        events = disc.get_discovery_events()
        assert len(events) >= 1
        assert events[0].event_type == "peer_found"

    def test_get_discovery_stats(self) -> None:
        disc = _make_discovery()
        disc.discover_peer(peer_id="peer-1", address="10.0.0.1:50051")
        stats = disc.get_discovery_stats()
        assert stats["total_discovered"] == 1
        assert stats["connected"] == 1
        assert stats["bootstrap_peers"] == 0
        assert stats["events"] >= 1

    def test_run_discovery_cycle(self) -> None:
        disc = _make_discovery()
        result = disc.run_discovery_cycle()
        assert result == 0
        assert disc._last_discovery_at > 0

    def test_discovery_with_peer_info(self) -> None:
        disc = _make_discovery()
        peer = disc.discover_peer(
            peer_id="peer-1",
            address="10.0.0.1:50051",
            peer_info={"version": "1.0", "role": "full"},
        )
        assert peer is not None
        assert peer.inventory_summary == {"version": "1.0", "role": "full"}

    def test_discovery_callback_receives_events(self) -> None:
        disc = _make_discovery()
        received: list[PeerDiscoveryEvent] = []
        disc.register_callback(received.append)

        disc.discover_peer(peer_id="peer-1", address="10.0.0.1:50051")

        types = [e.event_type for e in received]
        assert "peer_found" in types

    def test_discovery_callback_exception_handling(self) -> None:
        disc = _make_discovery()

        def bad_callback(event: PeerDiscoveryEvent) -> None:
            raise ValueError("boom")

        disc.register_callback(bad_callback)
        # Should not raise
        disc.discover_peer(peer_id="peer-1", address="10.0.0.1:50051")


# ---------------------------------------------------------------------------
# AutoSyncController tests
# ---------------------------------------------------------------------------


class TestAutoSyncController:
    def test_auto_sync_init(self) -> None:
        repl = _make_replicator()
        ctrl = AutoSyncController(replicator=repl)
        assert ctrl.is_active is False
        assert ctrl._sync_count == 0
        assert ctrl._alerts == []

    def test_auto_sync_start_stop(self) -> None:
        repl = _make_replicator()
        ctrl = AutoSyncController(replicator=repl)
        ctrl.start()
        assert ctrl.is_active is True
        ctrl.stop()
        assert ctrl.is_active is False

    def test_auto_sync_check_and_sync_inactive(self) -> None:
        repl = _make_replicator()
        ctrl = AutoSyncController(replicator=repl)
        result = ctrl.check_and_sync()
        assert result == 0

    def test_auto_sync_check_and_sync_with_discovery(self) -> None:
        repl = _make_replicator()
        disc = _make_discovery(replicator=repl)
        disc.discover_peer(peer_id="peer-1", address="10.0.0.1:50051")
        disc.discover_peer(peer_id="peer-2", address="10.0.0.2:50051")

        ctrl = AutoSyncController(replicator=repl, discovery=disc)
        ctrl.start()
        synced = ctrl.check_and_sync()

        assert synced == 2
        assert ctrl._sync_count == 1

    def test_auto_sync_check_and_sync_no_discovery(self) -> None:
        repl = _make_replicator()
        repl.on_peer_connected("peer-1")

        ctrl = AutoSyncController(replicator=repl)
        ctrl.start()
        synced = ctrl.check_and_sync()

        assert synced == 1

    def test_auto_sync_check_lag(self) -> None:
        repl = _make_replicator()
        ctrl = AutoSyncController(replicator=repl, lag_threshold_epochs=5)
        result = ctrl.check_lag(current_epoch=10, target_epoch=13)
        assert result is False  # lag=3, threshold=5

    def test_auto_sync_check_lag_critical(self) -> None:
        repl = _make_replicator()
        ctrl = AutoSyncController(replicator=repl, lag_threshold_epochs=5)
        result = ctrl.check_lag(current_epoch=10, target_epoch=16)
        assert result is True  # lag=6, threshold=5
        assert len(ctrl.get_alerts()) == 1
        alert = ctrl.get_alerts()[0]
        assert alert["type"] == "high_lag"
        assert alert["lag_epochs"] == 6

    def test_auto_sync_get_alerts(self) -> None:
        repl = _make_replicator()
        ctrl = AutoSyncController(replicator=repl)
        assert ctrl.get_alerts() == []

    def test_auto_sync_clear_alerts(self) -> None:
        repl = _make_replicator()
        ctrl = AutoSyncController(replicator=repl, lag_threshold_epochs=5)
        ctrl.check_lag(current_epoch=10, target_epoch=20)
        assert len(ctrl.get_alerts()) == 1
        ctrl.clear_alerts()
        assert ctrl.get_alerts() == []

    def test_auto_sync_stats(self) -> None:
        repl = _make_replicator()
        ctrl = AutoSyncController(replicator=repl, sync_interval_seconds=45)
        stats = ctrl.get_stats()
        assert stats["active"] is False
        assert stats["sync_count"] == 0
        assert stats["sync_interval_seconds"] == 45
        assert stats["alert_count"] == 0

    def test_auto_sync_stats_after_sync(self) -> None:
        repl = _make_replicator()
        repl.on_peer_connected("peer-1")
        ctrl = AutoSyncController(replicator=repl)
        ctrl.start()
        ctrl.check_and_sync()

        stats = ctrl.get_stats()
        assert stats["active"] is True
        assert stats["sync_count"] == 1
        assert stats["last_sync_at"] > 0


# ---------------------------------------------------------------------------
# Integration / full flow tests
# ---------------------------------------------------------------------------


class TestFullDiscoveryFlow:
    def test_full_discovery_flow(self) -> None:
        """End-to-end: discover peers, sync, lose peer, check stats."""
        repl = _make_replicator(node_id="node-a")
        disc = _make_discovery(node_id="node-a", replicator=repl)
        ctrl = AutoSyncController(replicator=repl, discovery=disc)

        # Discover two peers
        p1 = disc.discover_peer(peer_id="peer-1", address="10.0.0.1:50051")
        p2 = disc.discover_peer(peer_id="peer-2", address="10.0.0.2:50051")
        assert p1 is not None
        assert p2 is not None

        # Both connected
        stats = disc.get_discovery_stats()
        assert stats["total_discovered"] == 2
        assert stats["connected"] == 2

        # Start auto-sync and sync
        ctrl.start()
        synced = ctrl.check_and_sync()
        assert synced == 2

        # Lose one peer
        disc.lose_peer("peer-2")
        connected = disc.get_connected_peers()
        assert len(connected) == 1

        # Sync again — only one peer
        synced = ctrl.check_and_sync()
        assert synced == 1

        # Lag check — default threshold is 5
        assert ctrl.check_lag(current_epoch=10, target_epoch=13) is False  # lag=3
        assert ctrl.check_lag(current_epoch=10, target_epoch=50) is True  # lag=40

    def test_discovery_with_replicator_integration(self) -> None:
        """Discovery triggers replicator peer connection."""
        repl = _make_replicator()
        disc = _make_discovery(replicator=repl)

        disc.discover_peer(peer_id="peer-1", address="10.0.0.1:50051")

        # Replicator should know about the peer
        state = repl.get_peer_state("peer-1")
        assert state is not None
        assert state.connected is True

        # Disconnect
        disc.lose_peer("peer-1")
        state = repl.get_peer_state("peer-1")
        assert state.connected is False

    def test_auto_sync_triggers_inventory_request(self) -> None:
        """Auto sync should trigger inventory requests via replicator."""
        repl = _make_replicator()
        disc = _make_discovery(replicator=repl)
        disc.discover_peer(peer_id="peer-1", address="10.0.0.1:50051")

        ctrl = AutoSyncController(replicator=repl, discovery=disc)
        ctrl.start()
        ctrl.check_and_sync()

        # Outbox should contain messages
        outbox = repl.get_outbox()
        assert len(outbox) >= 1

    def test_multiple_sync_cycles(self) -> None:
        """Multiple sync cycles increment count correctly."""
        repl = _make_replicator()
        repl.on_peer_connected("peer-1")

        ctrl = AutoSyncController(replicator=repl)
        ctrl.start()

        for _ in range(3):
            ctrl.check_and_sync()

        assert ctrl._sync_count == 3
        stats = ctrl.get_stats()
        assert stats["sync_count"] == 3

    def test_discovery_events_accumulate(self) -> None:
        """Events accumulate across operations."""
        repl = _make_replicator()
        disc = _make_discovery(replicator=repl)

        disc.discover_peer(peer_id="peer-1", address="10.0.0.1:50051")
        disc.lose_peer("peer-1")

        events = disc.get_discovery_events()
        # peer_found + peer_connected + peer_lost
        assert len(events) >= 3

        types = [e.event_type for e in events]
        assert "peer_found" in types
        assert "peer_connected" in types
        assert "peer_lost" in types
