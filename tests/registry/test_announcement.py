"""Tests for registry announcements (M8-S3)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from aidn_hypervisor.registry.announcement import (
    AnnouncementBroadcaster,
    AnnouncementCollector,
    ObjectAnnouncement,
)

# ─── ObjectAnnouncement ────────────────────────────────────────────────────


class TestObjectAnnouncement:

    def test_creation(self) -> None:
        ann = ObjectAnnouncement(
            object_id="obj-1",
            object_type="finalized_block",
            content_hash="abc123",
            content_size=1024,
        )
        assert ann.object_id == "obj-1"
        assert ann.priority == 0
        assert ann.epoch is None

    def test_frozen(self) -> None:
        ann = ObjectAnnouncement(
            object_id="obj-1",
            object_type="finalized_block",
            content_hash="abc",
            content_size=100,
        )
        with pytest.raises(ValidationError):
            ann.object_id = "obj-2"  # type: ignore

    def test_priority(self) -> None:
        ann = ObjectAnnouncement(
            object_id="obj-1",
            object_type="finalized_block",
            content_hash="abc",
            content_size=100,
            priority=1,
        )
        assert ann.priority == 1

    def test_source_peer(self) -> None:
        ann = ObjectAnnouncement(
            object_id="obj-1",
            object_type="finalized_block",
            content_hash="abc",
            content_size=100,
            source_peer_id="peer-X",
        )
        assert ann.source_peer_id == "peer-X"


# ─── AnnouncementBroadcaster ───────────────────────────────────────────────


class TestAnnouncementBroadcaster:

    def test_announce(self) -> None:
        bc = AnnouncementBroadcaster()
        ann = ObjectAnnouncement(
            object_id="obj-1",
            object_type="finalized_block",
            content_hash="abc",
            content_size=100,
        )
        bc.announce(ann)
        assert len(bc.get_all_announcements()) == 1

    def test_subscribe(self) -> None:
        bc = AnnouncementBroadcaster()
        bc.subscribe("peer-1")
        # Should not duplicate
        bc.subscribe("peer-1")

    def test_unsubscribe(self) -> None:
        bc = AnnouncementBroadcaster()
        bc.subscribe("peer-1")
        bc.unsubscribe("peer-1")

    def test_get_pending(self) -> None:
        bc = AnnouncementBroadcaster()
        bc.subscribe("peer-1")
        bc.announce(
            ObjectAnnouncement(
                object_id="obj-1",
                object_type="finalized_block",
                content_hash="abc",
                content_size=100,
            )
        )
        pending = bc.get_pending_for("peer-1")
        assert len(pending) == 1
        assert pending[0].object_id == "obj-1"

    def test_mark_sent(self) -> None:
        bc = AnnouncementBroadcaster()
        bc.subscribe("peer-1")
        bc.announce(
            ObjectAnnouncement(
                object_id="obj-1",
                object_type="finalized_block",
                content_hash="abc",
                content_size=100,
            )
        )
        bc.mark_sent("peer-1", ["obj-1"])
        pending = bc.get_pending_for("peer-1")
        assert len(pending) == 0

    def test_get_all(self) -> None:
        bc = AnnouncementBroadcaster()
        for i in range(3):
            bc.announce(
                ObjectAnnouncement(
                    object_id=f"obj-{i}",
                    object_type="finalized_block",
                    content_hash=f"hash-{i}",
                    content_size=100,
                )
            )
        assert len(bc.get_all_announcements()) == 3

    def test_get_recent(self) -> None:
        bc = AnnouncementBroadcaster()
        bc.announce(
            ObjectAnnouncement(
                object_id="obj-1",
                object_type="finalized_block",
                content_hash="abc",
                content_size=100,
            )
        )
        recent = bc.get_recent(seconds=60)
        assert len(recent) == 1

    def test_get_recent_by_type(self) -> None:
        bc = AnnouncementBroadcaster()
        bc.announce(
            ObjectAnnouncement(
                object_id="obj-1",
                object_type="finalized_block",
                content_hash="abc",
                content_size=100,
            )
        )
        bc.announce(
            ObjectAnnouncement(
                object_id="obj-2",
                object_type="ledger_operation",
                content_hash="def",
                content_size=200,
            )
        )
        recent = bc.get_recent(seconds=60, object_type="finalized_block")
        assert len(recent) == 1
        assert recent[0].object_type == "finalized_block"

    def test_pending_after_mark_sent(self) -> None:
        bc = AnnouncementBroadcaster()
        bc.subscribe("peer-1")
        bc.announce(
            ObjectAnnouncement(
                object_id="obj-1",
                object_type="finalized_block",
                content_hash="abc",
                content_size=100,
            )
        )
        bc.announce(
            ObjectAnnouncement(
                object_id="obj-2",
                object_type="ledger_operation",
                content_hash="def",
                content_size=200,
            )
        )
        bc.mark_sent("peer-1", ["obj-1"])
        pending = bc.get_pending_for("peer-1")
        assert len(pending) == 1
        assert pending[0].object_id == "obj-2"


# ─── AnnouncementCollector ─────────────────────────────────────────────────


class TestAnnouncementCollector:

    def _make_announcement(
        self,
        object_id: str = "obj-1",
        content_hash: str = "abc123",
        source_peer_id: str = "peer-1",
    ) -> ObjectAnnouncement:
        return ObjectAnnouncement(
            object_id=object_id,
            object_type="finalized_block",
            content_hash=content_hash,
            content_size=1024,
            source_peer_id=source_peer_id,
        )

    def test_receive_new(self) -> None:
        col = AnnouncementCollector()
        result = col.receive(self._make_announcement())
        assert result is True
        assert col.count() == 1

    def test_receive_duplicate(self) -> None:
        col = AnnouncementCollector()
        ann = self._make_announcement()
        col.receive(ann)
        result = col.receive(ann)
        assert result is False
        assert col.count() == 1

    def test_receive_conflict(self) -> None:
        col = AnnouncementCollector()
        ann1 = self._make_announcement(content_hash="hash-a")
        ann2 = self._make_announcement(content_hash="hash-b")
        col.receive(ann1)
        result = col.receive(ann2)
        assert result is False
        # First seen wins
        stored = col.get_announcement("obj-1")
        assert stored is not None
        assert stored.content_hash == "hash-a"

    def test_get_new_ids(self) -> None:
        col = AnnouncementCollector()
        col.receive(self._make_announcement(object_id="obj-1"))
        col.receive(self._make_announcement(object_id="obj-2"))
        ids = col.get_new_object_ids()
        assert len(ids) == 2
        assert "obj-1" in ids
        assert "obj-2" in ids

    def test_get_announcement(self) -> None:
        col = AnnouncementCollector()
        ann = self._make_announcement(object_id="obj-5")
        col.receive(ann)
        result = col.get_announcement("obj-5")
        assert result is not None
        assert result.object_id == "obj-5"

    def test_get_sources(self) -> None:
        col = AnnouncementCollector()
        col.receive(self._make_announcement(source_peer_id="peer-A"))
        col.receive(
            self._make_announcement(object_id="obj-1", source_peer_id="peer-B")
        )
        sources = col.get_sources("obj-1")
        assert "peer-A" in sources
        assert "peer-B" in sources

    def test_count(self) -> None:
        col = AnnouncementCollector()
        assert col.count() == 0
        col.receive(self._make_announcement(object_id="a"))
        col.receive(self._make_announcement(object_id="b"))
        col.receive(self._make_announcement(object_id="a"))  # duplicate
        assert col.count() == 2
