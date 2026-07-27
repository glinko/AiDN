"""Channel multiplexing layer (RFC-0042 §44-47).

One physical connection MAY carry several logical channels.
Each channel is individually authorized per route.
"""

import asyncio
import logging
from collections import defaultdict
from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, Field

from aidn_hypervisor.dispatcher.models import ChannelClass

logger = logging.getLogger(__name__)


# ── Channel state machine ─────────────────────────────────────────────────

class ChannelState(str, Enum):
    OPENING = "OPENING"
    OPEN = "OPEN"
    DRAINING = "DRAINING"
    CLOSED = "CLOSED"


# ── Channel identity (RFC-0042 §46) ───────────────────────────────────────

class ChannelIdentity(BaseModel):
    """Logical channel identity within a physical connection."""

    channel_id: str
    channel_class: ChannelClass
    connection_id: str
    source_subject_type: str
    source_subject_id: str
    destination_subject_type: str
    destination_subject_id: str
    protocol_profile: str = "default"
    version: str = "1"
    priority: int = 3  # 0=highest, 5=lowest
    state: ChannelState = ChannelState.OPENING
    opened_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
    closed_at: str | None = None
    message_count: int = 0
    byte_count: int = 0


class ChannelAuthorization(BaseModel):
    """Per-channel authorization metadata."""

    channel_id: str
    authorized: bool = True
    authorized_by: str = "ROUTE"  # ROUTE, EXPLICIT, REVOKED
    allowed_channel_classes: set[ChannelClass] = Field(default_factory=set)
    allowed_message_types: set[str] = Field(default_factory=set)
    rate_limit_per_sec: int = 100
    max_queue_depth: int = 256


# ── Channel queue ─────────────────────────────────────────────────────────

class ChannelQueue:
    """Bounded priority queue for a single channel.

    Supports priority classes: CRITICAL_CONTROL(0), HIGH(1), INTERACTIVE(2),
    NORMAL(3), BULK(4), BACKGROUND(5). FIFO within each priority.
    """

    def __init__(self, channel_id: str, max_depth: int = 256) -> None:
        self.channel_id = channel_id
        self.max_depth = max_depth
        self._queues: dict[int, asyncio.Queue] = {
            p: asyncio.Queue(maxsize=max_depth) for p in range(6)
        }
        self._total_size: int = 0
        self._lock = asyncio.Lock()

    @property
    def depth(self) -> int:
        return self._total_size

    @property
    def is_full(self) -> bool:
        return self._total_size >= self.max_depth

    async def enqueue(self, data: bytes, priority: int = 3) -> bool:
        """Enqueue data at given priority. Returns False if full (backpressure)."""
        priority = max(0, min(5, priority))
        async with self._lock:
            if self._total_size >= self.max_depth:
                return False  # backpressure
            await self._queues[priority].put(data)
            self._total_size += 1
            return True

    async def dequeue(self) -> bytes | None:
        """Dequeue highest-priority item. Returns None if empty."""
        async with self._lock:
            for p in range(6):  # 0=highest priority
                if not self._queues[p].empty():
                    item = self._queues[p].get_nowait()
                    self._total_size -= 1
                    return item
        return None

    async def drain(self) -> list[bytes]:
        """Drain all items in priority order."""
        items: list[bytes] = []
        async with self._lock:
            for p in range(6):
                while not self._queues[p].empty():
                    try:
                        items.append(self._queues[p].get_nowait())
                        self._total_size -= 1
                    except asyncio.QueueEmpty:
                        break
        return items


# ── Channel manager ───────────────────────────────────────────────────────

class ChannelManager:
    """Manages channel lifecycle per physical connection (RFC-0042 §44).

    Responsibilities:
    - Open/close channels with state machine transitions
    - Authorize channels against route permissions
    - Manage per-channel queues
    - Track channel statistics
    """

    def __init__(self, default_max_queue: int = 256) -> None:
        self.default_max_queue = default_max_queue
        self._channels: dict[str, ChannelIdentity] = {}
        self._queues: dict[str, ChannelQueue] = {}
        self._authorizations: dict[str, ChannelAuthorization] = {}
        self._connections: dict[str, list[str]] = defaultdict(list)  # conn_id -> [channel_ids]

    @property
    def channel_count(self) -> int:
        return len(self._channels)

    @property
    def open_channels(self) -> list[ChannelIdentity]:
        return [c for c in self._channels.values() if c.state == ChannelState.OPEN]

    def open_channel(
        self,
        *,
        channel_id: str,
        channel_class: ChannelClass,
        connection_id: str,
        source_subject_type: str,
        source_subject_id: str,
        destination_subject_type: str,
        destination_subject_id: str,
        max_queue_depth: int | None = None,
    ) -> ChannelIdentity:
        """Open a new logical channel (RFC-0042 §45)."""
        if channel_id in self._channels:
            existing = self._channels[channel_id]
            if existing.state == ChannelState.OPEN:
                logger.warning("Channel %s already open", channel_id)
                return existing
            # Re-open a closed channel
            existing.state = ChannelState.OPENING
            existing.opened_at = datetime.now(UTC).isoformat()
            existing.closed_at = None
            existing.message_count = 0
            existing.byte_count = 0
        else:
            identity = ChannelIdentity(
                channel_id=channel_id,
                channel_class=channel_class,
                connection_id=connection_id,
                source_subject_type=source_subject_type,
                source_subject_id=source_subject_id,
                destination_subject_type=destination_subject_type,
                destination_subject_id=destination_subject_id,
                state=ChannelState.OPENING,
            )
            self._channels[channel_id] = identity
            self._connections[connection_id].append(channel_id)

        # Create queue
        depth = max_queue_depth or self.default_max_queue
        self._queues[channel_id] = ChannelQueue(channel_id, max_depth=depth)

        # Transition to OPEN
        identity = self._channels[channel_id]
        identity.state = ChannelState.OPEN
        logger.info("Channel opened: %s (class=%s, conn=%s)", channel_id, channel_class, connection_id)
        return identity

    def close_channel(self, channel_id: str, *, drain: bool = True) -> None:
        """Close a channel, optionally draining remaining messages."""
        identity = self._channels.get(channel_id)
        if identity is None:
            return
        if identity.state == ChannelState.CLOSED:
            return
        identity.state = ChannelState.DRAINING
        if drain:
            # In async context, would drain the queue
            pass
        identity.state = ChannelState.CLOSED
        identity.closed_at = datetime.now(UTC).isoformat()
        logger.info("Channel closed: %s", channel_id)

    def get_channel(self, channel_id: str) -> ChannelIdentity | None:
        """Look up a channel by ID."""
        return self._channels.get(channel_id)

    def get_channels_for_connection(self, connection_id: str) -> list[ChannelIdentity]:
        """Get all channels for a physical connection."""
        channel_ids = self._connections.get(connection_id, [])
        return [
            self._channels[cid]
            for cid in channel_ids
            if cid in self._channels
        ]

    def authorize_channel(
        self,
        channel_id: str,
        *,
        allowed_channel_classes: set[ChannelClass] | None = None,
        allowed_message_types: set[str] | None = None,
        rate_limit_per_sec: int = 100,
        max_queue_depth: int | None = None,
    ) -> ChannelAuthorization:
        """Set authorization for a channel (RFC-0042 §47)."""
        auth = ChannelAuthorization(
            channel_id=channel_id,
            authorized=True,
            allowed_channel_classes=allowed_channel_classes or set(),
            allowed_message_types=allowed_message_types or set(),
            rate_limit_per_sec=rate_limit_per_sec,
            max_queue_depth=max_queue_depth or self.default_max_queue,
        )
        self._authorizations[channel_id] = auth
        return auth

    def is_channel_authorized(
        self,
        channel_id: str,
        channel_class: ChannelClass,
        message_type: str | None = None,
    ) -> bool:
        """Check if a channel class/message type is authorized (RFC-0042 §47)."""
        auth = self._authorizations.get(channel_id)
        if auth is None:
            # No explicit authorization — allow by default
            return True
        if not auth.authorized:
            return False
        if auth.allowed_channel_classes and channel_class not in auth.allowed_channel_classes:
            return False
        if message_type and auth.allowed_message_types:
            if message_type not in auth.allowed_message_types:
                return False
        return True

    def revoke_channel(self, channel_id: str) -> None:
        """Revoke channel authorization."""
        auth = self._authorizations.get(channel_id)
        if auth:
            auth.authorized = False
            auth.authorized_by = "REVOKED"
        self.close_channel(channel_id, drain=False)

    def get_queue(self, channel_id: str) -> ChannelQueue | None:
        """Get the queue for a channel."""
        return self._queues.get(channel_id)

    def update_stats(self, channel_id: str, bytes_transferred: int) -> None:
        """Update channel transfer statistics."""
        identity = self._channels.get(channel_id)
        if identity:
            identity.message_count += 1
            identity.byte_count += bytes_transferred
