"""Object Announcements (RFC-0061 §27)."""

from __future__ import annotations

import time
from collections import defaultdict

from pydantic import BaseModel


class ObjectAnnouncement(BaseModel, frozen=True):
    """RFC-0061 §27 — Announcement of a new registry object."""

    object_id: str
    object_type: str
    content_hash: str
    content_size: int
    epoch: int | None = None
    block_height: int | None = None
    announced_at: float = 0.0
    source_peer_id: str = ""
    priority: int = 0  # 0=normal, 1=high (ledger-committed objects)


class AnnouncementBroadcaster:
    """
    RFC-0061 §27 — Broadcast object announcements to connected peers.
    """

    def __init__(self) -> None:
        self._announcements: list[ObjectAnnouncement] = []
        self._subscribers: list[str] = []  # peer_ids
        self._sent_to: dict[str, set[str]] = defaultdict(set)  # peer_id -> {object_ids sent}

    def announce(self, announcement: ObjectAnnouncement) -> None:
        """Record and broadcast an announcement."""
        ann = announcement.model_copy(
            update={"announced_at": time.time()}
        )
        self._announcements.append(ann)

    def subscribe(self, peer_id: str) -> None:
        """Register a peer as announcement subscriber."""
        if peer_id not in self._subscribers:
            self._subscribers.append(peer_id)

    def unsubscribe(self, peer_id: str) -> None:
        """Remove a peer from announcement subscribers."""
        self._subscribers.remove(peer_id)
        self._sent_to.pop(peer_id, None)

    def get_pending_for(self, peer_id: str) -> list[ObjectAnnouncement]:
        """Get announcements not yet sent to this peer."""
        sent = self._sent_to.get(peer_id, set())
        return [a for a in self._announcements if a.object_id not in sent]

    def mark_sent(self, peer_id: str, object_ids: list[str]) -> None:
        """Mark announcements as sent to a peer."""
        self._sent_to.setdefault(peer_id, set()).update(object_ids)

    def get_all_announcements(self) -> list[ObjectAnnouncement]:
        """Get all recorded announcements."""
        return list(self._announcements)

    def get_recent(
        self,
        *,
        seconds: float = 3600,
        object_type: str | None = None,
    ) -> list[ObjectAnnouncement]:
        """Get recent announcements, optionally filtered by type."""
        cutoff = time.time() - seconds
        recent = [a for a in self._announcements if a.announced_at >= cutoff]
        if object_type:
            recent = [a for a in recent if a.object_type == object_type]
        return recent


class AnnouncementCollector:
    """Collect and deduplicate announcements from remote peers."""

    def __init__(self) -> None:
        self._received: dict[str, ObjectAnnouncement] = {}  # object_id -> announcement
        self._sources: dict[str, set[str]] = defaultdict(set)  # object_id -> {peer_ids}

    def receive(self, announcement: ObjectAnnouncement) -> bool:
        """
        Receive an announcement. Returns True if new, False if duplicate.
        """
        oid = announcement.object_id
        if oid in self._received:
            existing = self._received[oid]
            if existing.content_hash != announcement.content_hash:
                # Conflict — keep first seen
                return False
            self._sources[oid].add(announcement.source_peer_id)
            return False

        self._received[oid] = announcement
        self._sources[oid].add(announcement.source_peer_id)
        return True

    def get_new_object_ids(self) -> list[str]:
        """Get all announced object ids."""
        return list(self._received.keys())

    def get_announcement(self, object_id: str) -> ObjectAnnouncement | None:
        """Get a specific announcement by object id."""
        return self._received.get(object_id)

    def get_sources(self, object_id: str) -> list[str]:
        """Get peers that announced this object."""
        return list(self._sources.get(object_id, set()))

    def count(self) -> int:
        """Total number of unique announcements received."""
        return len(self._received)
