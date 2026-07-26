"""Registry Peer Discovery + Auto Sync (M9-S5).

Discovers registry peers, manages connection lifecycle,
and coordinates with the replicator for sync operations.
"""

from __future__ import annotations

import time
from typing import Any, Callable

from pydantic import BaseModel, Field

from .peer import PeerManager, RegistryPeer, PeerState
from .replicator import RegistryReplicator
from .messages import RegistryChannelClass


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class DiscoveryConfig(BaseModel, frozen=True):
    """Configuration for peer discovery."""

    enabled: bool = True
    discovery_interval_seconds: int = 60
    max_peers: int = 20
    bootstrap_peers: list[str] = Field(default_factory=list)
    auto_connect: bool = True
    require_signed_records: bool = False
    peer_ttl_seconds: int = 3600
    min_sync_interval_seconds: int = 30


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


class PeerDiscoveryEvent(BaseModel, frozen=True):
    """Event from the discovery system."""

    event_type: str  # peer_found | peer_connected | peer_lost | peer_synced
    peer_id: str
    timestamp: float = Field(default_factory=time.time)
    details: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Peer Discovery
# ---------------------------------------------------------------------------


class RegistryPeerDiscovery:
    """
    Registry peer discovery and management.

    Discovers registry peers, manages connection lifecycle,
    and coordinates with the replicator for sync operations.
    """

    def __init__(
        self,
        *,
        node_id: str,
        replicator: RegistryReplicator | None = None,
        config: DiscoveryConfig | None = None,
    ) -> None:
        self._node_id = node_id
        self._replicator = replicator
        self._config = config or DiscoveryConfig()
        self._peer_manager = PeerManager()
        self._discovered_peers: dict[str, RegistryPeer] = {}
        self._events: list[PeerDiscoveryEvent] = []
        self._callbacks: list[Callable] = []
        self._last_discovery_at: float = 0.0

    @property
    def peer_manager(self) -> PeerManager:
        return self._peer_manager

    @property
    def config(self) -> DiscoveryConfig:
        return self._config

    def register_callback(self, callback: Callable) -> None:
        """Register a callback for discovery events."""
        self._callbacks.append(callback)

    def _emit_event(self, event: PeerDiscoveryEvent) -> None:
        """Emit a discovery event."""
        self._events.append(event)
        for cb in self._callbacks:
            try:
                cb(event)
            except Exception:
                pass

    def add_bootstrap_peer(self, peer_address: str) -> None:
        """Add a bootstrap peer address."""
        if peer_address not in self._config.bootstrap_peers:
            updated = self._config.model_copy(
                update={"bootstrap_peers": [*self._config.bootstrap_peers, peer_address]}
            )
            object.__setattr__(self, "_config", updated)

    def discover_peer(
        self,
        *,
        peer_id: str,
        address: str,
        peer_info: dict[str, Any] | None = None,
    ) -> RegistryPeer | None:
        """
        Discover and register a new peer.

        Returns the registered peer or None if rejected.
        """
        # Check peer limit
        if len(self._discovered_peers) >= self._config.max_peers:
            return None

        # Check for duplicate
        if peer_id in self._discovered_peers:
            existing = self._discovered_peers[peer_id]
            # Update last seen
            updated = existing.model_copy(
                update={"last_seen_at": time.time()}
            )
            self._discovered_peers[peer_id] = updated
            return updated

        peer = RegistryPeer(
            peer_id=peer_id,
            node_id=self._node_id,
            address=address,
            state=PeerState.CONNECTED if self._config.auto_connect else PeerState.CONNECTING,
            last_seen_at=time.time(),
            inventory_summary=peer_info or {},
        )

        self._discovered_peers[peer_id] = peer
        self._peer_manager.add_peer(peer)

        self._emit_event(
            PeerDiscoveryEvent(
                event_type="peer_found",
                peer_id=peer_id,
                details={"address": address},
            )
        )

        # Auto-connect if configured
        if self._config.auto_connect and self._replicator:
            self._replicator.on_peer_connected(peer_id)
            self._emit_event(
                PeerDiscoveryEvent(
                    event_type="peer_connected",
                    peer_id=peer_id,
                )
            )

        return peer

    def lose_peer(self, peer_id: str) -> None:
        """Mark a peer as lost."""
        if peer_id in self._discovered_peers:
            peer = self._discovered_peers[peer_id]
            updated = peer.model_copy(update={"state": PeerState.DISCONNECTED})
            self._discovered_peers[peer_id] = updated

            if self._replicator:
                self._replicator.on_peer_disconnected(peer_id)

            self._emit_event(
                PeerDiscoveryEvent(
                    event_type="peer_lost",
                    peer_id=peer_id,
                )
            )

    def get_peer(self, peer_id: str) -> RegistryPeer | None:
        """Get a discovered peer."""
        return self._discovered_peers.get(peer_id)

    def get_all_peers(self) -> list[RegistryPeer]:
        """Get all discovered peers."""
        return list(self._discovered_peers.values())

    def get_connected_peers(self) -> list[RegistryPeer]:
        """Get connected peers."""
        return [
            p for p in self._discovered_peers.values()
            if p.state in (PeerState.CONNECTED, PeerState.SYNCHRONIZING)
        ]

    def get_discovery_events(self) -> list[PeerDiscoveryEvent]:
        """Get all discovery events."""
        return list(self._events)

    def get_discovery_stats(self) -> dict[str, Any]:
        """Get discovery statistics."""
        return {
            "total_discovered": len(self._discovered_peers),
            "connected": len(self.get_connected_peers()),
            "bootstrap_peers": len(self._config.bootstrap_peers),
            "events": len(self._events),
            "last_discovery_at": self._last_discovery_at,
        }

    def run_discovery_cycle(self) -> int:
        """
        Run a discovery cycle.

        In MVP, this is a no-op that just updates the timestamp.
        Production would query a discovery service or broadcast.

        Returns the number of newly discovered peers.
        """
        self._last_discovery_at = time.time()
        return 0


# ---------------------------------------------------------------------------
# Auto Sync Controller
# ---------------------------------------------------------------------------


class AutoSyncController:
    """
    Automatic synchronization controller.

    Periodically checks sync status, triggers inventory exchange,
    and monitors lag.
    """

    def __init__(
        self,
        *,
        replicator: RegistryReplicator,
        discovery: RegistryPeerDiscovery | None = None,
        sync_interval_seconds: int = 30,
        lag_threshold_epochs: int = 5,
    ) -> None:
        self._replicator = replicator
        self._discovery = discovery
        self._sync_interval = sync_interval_seconds
        self._lag_threshold = lag_threshold_epochs
        self._last_sync_at: float = 0.0
        self._sync_count: int = 0
        self._alerts: list[dict[str, Any]] = []
        self._active = False

    @property
    def is_active(self) -> bool:
        return self._active

    def start(self) -> None:
        """Start automatic sync."""
        self._active = True
        self._last_sync_at = time.time()

    def stop(self) -> None:
        """Stop automatic sync."""
        self._active = False

    def check_and_sync(self) -> int:
        """
        Check if sync is needed and trigger it.

        Returns the number of peers synced.
        """
        if not self._active:
            return 0

        synced = 0

        if self._discovery:
            peers = self._discovery.get_connected_peers()
        else:
            peers = []
            # Fallback: check replicator peer states
            for state in self._replicator.get_all_peer_states():
                if state.connected:
                    peers.append(state)

        for peer in peers:
            peer_id = getattr(peer, "peer_id", str(peer))
            self._trigger_sync(peer_id)
            synced += 1

        self._sync_count += 1
        self._last_sync_at = time.time()

        return synced

    def _trigger_sync(self, peer_id: str) -> None:
        """Trigger sync with a specific peer."""
        state = self._replicator.get_peer_state(peer_id)
        if not state or not state.connected:
            return

        # Send inventory request
        self._replicator.build_inventory_request(peer_id)

    def check_lag(
        self,
        *,
        current_epoch: int,
        target_epoch: int,
    ) -> bool:
        """
        Check if lag exceeds threshold.

        Returns True if lag is critical.
        """
        lag = target_epoch - current_epoch
        if lag > self._lag_threshold:
            self._alerts.append(
                {
                    "type": "high_lag",
                    "lag_epochs": lag,
                    "current_epoch": current_epoch,
                    "target_epoch": target_epoch,
                    "timestamp": time.time(),
                }
            )
            return True
        return False

    def get_alerts(self) -> list[dict[str, Any]]:
        """Get all alerts."""
        return list(self._alerts)

    def clear_alerts(self) -> None:
        """Clear all alerts."""
        self._alerts.clear()

    def get_stats(self) -> dict[str, Any]:
        """Get auto-sync statistics."""
        return {
            "active": self._active,
            "sync_count": self._sync_count,
            "last_sync_at": self._last_sync_at,
            "alert_count": len(self._alerts),
            "sync_interval_seconds": self._sync_interval,
        }
