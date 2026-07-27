"""Tests for Registry Route Binding (M9-S2).

Route binding helpers for registry replication messages.
"""

from __future__ import annotations

from aidn_hypervisor.registry.messages import (
    RegistryChannelClass,
    RegistryMessageType,
)
from aidn_hypervisor.registry.routes import (
    build_registry_broadcast_route,
    build_registry_route,
    create_default_registry_channels,
)

# ─── build_registry_route ────────────────────────────────────────────


class TestBuildRegistryRoute:

    def test_build_registry_route(self) -> None:
        """Default route has expected structure."""
        route = build_registry_route(destination_node_id="node-1")
        assert route["destination_type"] == "registry_node"
        assert route["destination_id"] == "node-1"
        assert route["route_type"] == "REGISTRY_REPLICATION"
        assert route["channel_class"] == RegistryChannelClass.REGISTRY_REPLICATION
        assert route["message_type_filter"] == RegistryMessageType.OBJECT_RESPONSE
        assert route["priority"] == 7
        assert route["max_hops"] == 2

    def test_route_destination_type(self) -> None:
        """Destination type is always registry_node."""
        route = build_registry_route(destination_node_id="node-X")
        assert route["destination_type"] == "registry_node"

    def test_route_channel_class(self) -> None:
        """Channel class can be customized."""
        route = build_registry_route(
            destination_node_id="node-1",
            channel_class=RegistryChannelClass.REGISTRY_CONTROL,
        )
        assert route["channel_class"] == RegistryChannelClass.REGISTRY_CONTROL

    def test_route_priority(self) -> None:
        """Route priority is 7 by default."""
        route = build_registry_route(destination_node_id="node-1")
        assert route["priority"] == 7

    def test_route_max_hops(self) -> None:
        """Route max_hops is 2 by default."""
        route = build_registry_route(destination_node_id="node-1")
        assert route["max_hops"] == 2

    def test_build_registry_route_custom_type(self) -> None:
        """Message type filter can be customized."""
        route = build_registry_route(
            destination_node_id="node-1",
            message_type=RegistryMessageType.SYNC_STATUS,
        )
        assert route["message_type_filter"] == RegistryMessageType.SYNC_STATUS

    def test_route_message_type_filter(self) -> None:
        """Message type filter is included in route."""
        route = build_registry_route(
            destination_node_id="node-1",
            message_type=RegistryMessageType.ANNOUNCEMENT,
        )
        assert "message_type_filter" in route
        assert route["message_type_filter"] == RegistryMessageType.ANNOUNCEMENT


# ─── build_registry_broadcast_route ──────────────────────────────────


class TestBuildRegistryBroadcastRoute:

    def test_build_registry_broadcast_route(self) -> None:
        """Broadcast route has expected structure."""
        route = build_registry_broadcast_route()
        assert route["destination_type"] == "registry_node"
        assert route["destination_id"] == "broadcast"
        assert route["route_type"] == "REGISTRY_BROADCAST"
        assert route["channel_class"] == RegistryChannelClass.REGISTRY_REPLICATION
        assert route["priority"] == 5
        assert route["max_hops"] == 3

    def test_broadcast_route_hops(self) -> None:
        """Broadcast routes have max_hops=3 (wider reach)."""
        route = build_registry_broadcast_route()
        assert route["max_hops"] == 3

    def test_broadcast_route_custom_channel_class(self) -> None:
        """Broadcast route channel class can be customized."""
        route = build_registry_broadcast_route(
            channel_class=RegistryChannelClass.REGISTRY_DISCOVERY,
        )
        assert route["channel_class"] == RegistryChannelClass.REGISTRY_DISCOVERY


# ─── create_default_registry_channels ────────────────────────────────


class TestCreateDefaultRegistryChannels:

    def test_create_default_registry_channels_integration(self) -> None:
        """Full integration: create channels, enqueue, dequeue."""
        mgr = create_default_registry_channels()
        channels = mgr.list_channels()
        assert len(channels) == 3

        # Replication channel should accept registry messages
        repl_ch = mgr.get_channel("registry:replication")
        assert repl_ch is not None
        assert repl_ch.max_queue_size == 2000
        assert repl_ch.priority == 7

        # Enqueue on replication channel
        msg = {"message_type": RegistryMessageType.SYNC_STATUS, "epoch": 42}
        ok = mgr.enqueue_message(
            channel_id="registry:replication",
            message=msg,
            source_peer="node-A",
        )
        assert ok is True
        assert mgr.get_queue_depth("registry:replication") == 1

        # Dequeue
        out = mgr.dequeue_message("registry:replication")
        assert out is not None
        assert out["epoch"] == 42

        # Control channel has higher priority
        ctrl_ch = mgr.get_channel("registry:control")
        assert ctrl_ch is not None
        assert ctrl_ch.priority == 9
        assert ctrl_ch.max_queue_size == 100

        # Discovery channel
        disc_ch = mgr.get_channel("registry:discovery")
        assert disc_ch is not None
        assert disc_ch.priority == 5
        assert disc_ch.max_queue_size == 500
