"""
Registry Route Binding (M9-S2).

Route binding helpers for registry replication messages, compatible with
the dispatcher's DispatcherRoute format.
"""

from __future__ import annotations

from .channel import DEFAULT_REGISTRY_CHANNELS, RegistryChannelManager
from .messages import RegistryChannelClass, RegistryMessageType


def create_default_registry_channels() -> RegistryChannelManager:
    """Create default registry channels from configuration."""
    manager = RegistryChannelManager()
    for config in DEFAULT_REGISTRY_CHANNELS.values():
        manager.create_channel(**config)
    return manager


def build_registry_route(
    *,
    destination_node_id: str,
    channel_class: str = RegistryChannelClass.REGISTRY_REPLICATION,
    message_type: str = RegistryMessageType.OBJECT_RESPONSE,
) -> dict:
    """
    Build a route record for registry messages.

    Compatible with DispatcherRoute format.
    """
    return {
        "destination_type": "registry_node",
        "destination_id": destination_node_id,
        "route_type": "REGISTRY_REPLICATION",
        "channel_class": channel_class,
        "message_type_filter": message_type,
        "priority": 7,
        "max_hops": 2,
    }


def build_registry_broadcast_route(
    *,
    channel_class: str = RegistryChannelClass.REGISTRY_REPLICATION,
) -> dict:
    """Build a broadcast route for registry announcements."""
    return {
        "destination_type": "registry_node",
        "destination_id": "broadcast",
        "route_type": "REGISTRY_BROADCAST",
        "channel_class": channel_class,
        "priority": 5,
        "max_hops": 3,
    }
