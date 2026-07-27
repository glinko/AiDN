"""
Registry Channel Configuration (M9-S2).

RFC-0042 §44-§49 — Channel multiplexing, priorities, authorization,
and rate limiting for registry replication traffic.
"""

from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, Field

from .messages import (
    RegistryChannelClass,
    RegistryMessageType,
)


class RegistryChannelConfig(BaseModel):
    """
    RFC-0042 §44 — Channel configuration for registry replication traffic.

    Defines channel identity, priorities, rate limits, and authorization.
    """

    channel_id: str
    channel_class: str = RegistryChannelClass.REGISTRY_REPLICATION
    max_queue_size: int = 1000
    max_message_size_bytes: int = 10 * 1024 * 1024  # 10MB
    rate_limit_per_second: int = 100
    priority: int = 5  # 1-10, higher = more important
    allowed_message_types: list[str] = Field(default_factory=list)
    authorized_peers: list[str] = Field(default_factory=list)  # empty = all
    enabled: bool = True
    created_at: float = Field(default_factory=time.time)


class RegistryChannelManager:
    """
    RFC-0042 §44-§49 — Manage registry-specific channels.

    Handles channel creation, authorization, rate limiting, and message routing
    for registry replication traffic.
    """

    def __init__(self):
        self._channels: dict[str, RegistryChannelConfig] = {}
        self._channel_queues: dict[str, list[dict]] = {}
        self._message_counts: dict[str, int] = {}
        self._rate_windows: dict[str, list[float]] = {}

    def create_channel(
        self,
        *,
        channel_id: str,
        channel_class: str = RegistryChannelClass.REGISTRY_REPLICATION,
        **kwargs: Any,
    ) -> RegistryChannelConfig:
        """Create a new registry channel."""
        config = RegistryChannelConfig(
            channel_id=channel_id,
            channel_class=channel_class,
            **kwargs,
        )
        self._channels[channel_id] = config
        self._channel_queues[channel_id] = []
        self._message_counts[channel_id] = 0
        self._rate_windows[channel_id] = []
        return config

    def get_channel(self, channel_id: str) -> RegistryChannelConfig | None:
        return self._channels.get(channel_id)

    def list_channels(self) -> list[RegistryChannelConfig]:
        return list(self._channels.values())

    def enable_channel(self, channel_id: str) -> bool:
        config = self._channels.get(channel_id)
        if not config:
            return False
        updated = config.model_copy(update={"enabled": True})
        self._channels[channel_id] = updated
        return True

    def disable_channel(self, channel_id: str) -> bool:
        config = self._channels.get(channel_id)
        if not config:
            return False
        updated = config.model_copy(update={"enabled": False})
        self._channels[channel_id] = updated
        return True

    def authorize_peer(self, channel_id: str, peer_id: str) -> bool:
        """Authorize a peer on a channel."""
        config = self._channels.get(channel_id)
        if not config:
            return False
        if peer_id not in config.authorized_peers:
            updated = config.model_copy(
                update={"authorized_peers": [*config.authorized_peers, peer_id]}
            )
            self._channels[channel_id] = updated
        return True

    def check_authorization(self, channel_id: str, peer_id: str) -> bool:
        """Check if peer is authorized on channel."""
        config = self._channels.get(channel_id)
        if not config:
            return False
        if not config.enabled:
            return False
        # Empty authorized_peers means all peers allowed
        if not config.authorized_peers:
            return True
        return peer_id in config.authorized_peers

    def enqueue_message(
        self,
        *,
        channel_id: str,
        message: dict,
        source_peer: str,
    ) -> bool:
        """
        Enqueue a message on a channel.

        Checks authorization, rate limits, and queue capacity.
        """
        config = self._channels.get(channel_id)
        if not config or not config.enabled:
            return False

        # Authorization check
        if not self.check_authorization(channel_id, source_peer):
            return False

        # Queue capacity check
        queue = self._channel_queues.get(channel_id, [])
        if len(queue) >= config.max_queue_size:
            return False

        # Rate limit check
        if not self._check_rate_limit(channel_id, config.rate_limit_per_second):
            return False

        # Message type check
        if config.allowed_message_types:
            msg_type = message.get("message_type", "")
            if msg_type not in config.allowed_message_types:
                return False

        queue.append(
            {
                "message": message,
                "source_peer": source_peer,
                "enqueued_at": time.time(),
            }
        )
        self._message_counts[channel_id] = (
            self._message_counts.get(channel_id, 0) + 1
        )
        return True

    def dequeue_message(self, channel_id: str) -> dict | None:
        """Dequeue the next message from a channel."""
        queue = self._channel_queues.get(channel_id, [])
        if not queue:
            return None
        item = queue.pop(0)
        return item.get("message")

    def get_queue_depth(self, channel_id: str) -> int:
        return len(self._channel_queues.get(channel_id, []))

    def get_message_count(self, channel_id: str) -> int:
        return self._message_counts.get(channel_id, 0)

    def _check_rate_limit(self, channel_id: str, limit: int) -> bool:
        """Simple sliding window rate limit."""
        now = time.time()
        window = self._rate_windows.get(channel_id, [])
        # Remove entries older than 1 second
        window = [t for t in window if now - t < 1.0]
        if len(window) >= limit:
            return False
        window.append(now)
        self._rate_windows[channel_id] = window
        return True

    def reset_rate_windows(self) -> None:
        """Reset all rate limit windows."""
        self._rate_windows.clear()


# Default channel configurations
DEFAULT_REGISTRY_CHANNELS: dict[str, dict] = {
    "registry_replication": {
        "channel_id": "registry:replication",
        "channel_class": RegistryChannelClass.REGISTRY_REPLICATION,
        "max_queue_size": 2000,
        "rate_limit_per_second": 200,
        "priority": 7,
        "allowed_message_types": [
            RegistryMessageType.INVENTORY_REQUEST,
            RegistryMessageType.INVENTORY_RESPONSE,
            RegistryMessageType.OBJECT_REQUEST,
            RegistryMessageType.OBJECT_RESPONSE,
            RegistryMessageType.BLOOM_FILTER,
            RegistryMessageType.SYNC_STATUS,
            RegistryMessageType.ANNOUNCEMENT,
            RegistryMessageType.CHALLENGE,
            RegistryMessageType.REPAIR,
            RegistryMessageType.EPOCH_UPDATE,
        ],
    },
    "registry_discovery": {
        "channel_id": "registry:discovery",
        "channel_class": RegistryChannelClass.REGISTRY_DISCOVERY,
        "max_queue_size": 500,
        "rate_limit_per_second": 50,
        "priority": 5,
    },
    "registry_control": {
        "channel_id": "registry:control",
        "channel_class": RegistryChannelClass.REGISTRY_CONTROL,
        "max_queue_size": 100,
        "rate_limit_per_second": 20,
        "priority": 9,
    },
}
