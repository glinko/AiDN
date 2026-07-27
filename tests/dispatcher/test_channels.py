"""Tests for channel multiplexing (RFC-0042 §44-47)."""

import pytest

from aidn_hypervisor.dispatcher.channels import (
    ChannelIdentity,
    ChannelManager,
    ChannelQueue,
    ChannelState,
)

# ── ChannelIdentity tests ────────────────────────────────────────────────

class TestChannelIdentity:
    def test_create_channel_identity(self):
        identity = ChannelIdentity(
            channel_id="ch-001",
            channel_class="CONTROL",
            connection_id="conn-001",
            source_subject_type="HYPERVISOR",
            source_subject_id="hv-001",
            destination_subject_type="HYPERVISOR",
            destination_subject_id="hv-002",
        )
        assert identity.channel_id == "ch-001"
        assert identity.channel_class == "CONTROL"
        assert identity.state == ChannelState.OPENING
        assert identity.message_count == 0
        assert identity.byte_count == 0

    def test_channel_defaults(self):
        identity = ChannelIdentity(
            channel_id="ch-001",
            channel_class="RUNTIME",
            connection_id="conn-001",
            source_subject_type="ENDPOINT",
            source_subject_id="ep-001",
            destination_subject_type="RUNTIME",
            destination_subject_id="rt-001",
        )
        assert identity.version == "1"
        assert identity.priority == 3
        assert identity.protocol_profile == "default"


# ── ChannelQueue tests ───────────────────────────────────────────────────

class TestChannelQueue:
    @pytest.mark.asyncio
    async def test_enqueue_dequeue(self):
        q = ChannelQueue("ch-001", max_depth=10)
        assert await q.enqueue(b"hello", priority=3)
        item = await q.dequeue()
        assert item == b"hello"

    @pytest.mark.asyncio
    async def test_priority_ordering(self):
        q = ChannelQueue("ch-001", max_depth=10)
        # Enqueue in reverse priority order
        await q.enqueue(b"normal", priority=3)
        await q.enqueue(b"critical", priority=0)
        await q.enqueue(b"background", priority=5)

        # Should dequeue in priority order
        assert await q.dequeue() == b"critical"
        assert await q.dequeue() == b"normal"
        assert await q.dequeue() == b"background"

    @pytest.mark.asyncio
    async def test_backpressure_when_full(self):
        q = ChannelQueue("ch-001", max_depth=2)
        assert await q.enqueue(b"msg1")
        assert await q.enqueue(b"msg2")
        # Third should fail (backpressure)
        assert not await q.enqueue(b"msg3")

    @pytest.mark.asyncio
    async def test_drain(self):
        q = ChannelQueue("ch-001", max_depth=10)
        await q.enqueue(b"msg1")
        await q.enqueue(b"msg2")
        await q.enqueue(b"msg3")
        items = await q.drain()
        assert len(items) == 3
        assert items[0] == b"msg1"
        # Queue should be empty after drain
        assert await q.dequeue() is None

    @pytest.mark.asyncio
    async def test_fifo_within_priority(self):
        q = ChannelQueue("ch-001", max_depth=10)
        await q.enqueue(b"first", priority=3)
        await q.enqueue(b"second", priority=3)
        await q.enqueue(b"third", priority=3)

        assert await q.dequeue() == b"first"
        assert await q.dequeue() == b"second"
        assert await q.dequeue() == b"third"

    @pytest.mark.asyncio
    async def test_depth_tracking(self):
        q = ChannelQueue("ch-001", max_depth=10)
        assert q.depth == 0
        assert not q.is_full
        await q.enqueue(b"msg1")
        assert q.depth == 1
        await q.dequeue()
        assert q.depth == 0


# ── ChannelManager tests ─────────────────────────────────────────────────

class TestChannelManager:
    @pytest.fixture
    def manager(self):
        return ChannelManager(default_max_queue=128)

    def test_open_channel(self, manager):
        ch = manager.open_channel(
            channel_id="ch-001",
            channel_class="CONTROL",
            connection_id="conn-001",
            source_subject_type="HYPERVISOR",
            source_subject_id="hv-001",
            destination_subject_type="HYPERVISOR",
            destination_subject_id="hv-002",
        )
        assert ch.state == ChannelState.OPEN
        assert ch.channel_class == "CONTROL"
        assert manager.channel_count == 1

    def test_open_duplicate_channel_reopens(self, manager):
        ch1 = manager.open_channel(
            channel_id="ch-001",
            channel_class="CONTROL",
            connection_id="conn-001",
            source_subject_type="HYPERVISOR",
            source_subject_id="hv-001",
            destination_subject_type="HYPERVISOR",
            destination_subject_id="hv-002",
        )
        ch2 = manager.open_channel(
            channel_id="ch-001",
            channel_class="CONTROL",
            connection_id="conn-001",
            source_subject_type="HYPERVISOR",
            source_subject_id="hv-001",
            destination_subject_type="HYPERVISOR",
            destination_subject_id="hv-002",
        )
        assert ch1 is ch2
        assert manager.channel_count == 1

    def test_close_channel(self, manager):
        manager.open_channel(
            channel_id="ch-001",
            channel_class="RUNTIME",
            connection_id="conn-001",
            source_subject_type="HYPERVISOR",
            source_subject_id="hv-001",
            destination_subject_type="RUNTIME",
            destination_subject_id="rt-001",
        )
        manager.close_channel("ch-001")
        ch = manager.get_channel("ch-001")
        assert ch.state == ChannelState.CLOSED
        assert ch.closed_at is not None

    def test_get_channels_for_connection(self, manager):
        manager.open_channel(
            channel_id="ch-001",
            channel_class="CONTROL",
            connection_id="conn-001",
            source_subject_type="HYPERVISOR",
            source_subject_id="hv-001",
            destination_subject_type="HYPERVISOR",
            destination_subject_id="hv-002",
        )
        manager.open_channel(
            channel_id="ch-002",
            channel_class="RUNTIME",
            connection_id="conn-001",
            source_subject_type="HYPERVISOR",
            source_subject_id="hv-001",
            destination_subject_type="RUNTIME",
            destination_subject_id="rt-001",
        )
        manager.open_channel(
            channel_id="ch-003",
            channel_class="SESSION_CONTROL",
            connection_id="conn-002",  # Different connection
            source_subject_type="HYPERVISOR",
            source_subject_id="hv-001",
            destination_subject_type="SESSION",
            destination_subject_id="sess-001",
        )
        conn1_channels = manager.get_channels_for_connection("conn-001")
        assert len(conn1_channels) == 2
        conn2_channels = manager.get_channels_for_connection("conn-002")
        assert len(conn2_channels) == 1

    def test_authorize_channel(self, manager):
        manager.open_channel(
            channel_id="ch-001",
            channel_class="CONTROL",
            connection_id="conn-001",
            source_subject_type="HYPERVISOR",
            source_subject_id="hv-001",
            destination_subject_type="HYPERVISOR",
            destination_subject_id="hv-002",
        )
        manager.authorize_channel(
            "ch-001",
            allowed_channel_classes={"CONTROL", "SESSION_CONTROL"},
            allowed_message_types={"SESSION_ACCEPT", "SESSION_REJECT"},
        )
        assert manager.is_channel_authorized("ch-001", "CONTROL")
        assert manager.is_channel_authorized("ch-001", "SESSION_CONTROL")
        assert manager.is_channel_authorized("ch-001", "CONTROL", "SESSION_ACCEPT")

    def test_channel_authorization_denies_unauthorized_class(self, manager):
        manager.open_channel(
            channel_id="ch-001",
            channel_class="CONTROL",
            connection_id="conn-001",
            source_subject_type="HYPERVISOR",
            source_subject_id="hv-001",
            destination_subject_type="HYPERVISOR",
            destination_subject_id="hv-002",
        )
        manager.authorize_channel(
            "ch-001",
            allowed_channel_classes={"CONTROL"},  # Only CONTROL allowed
        )
        assert manager.is_channel_authorized("ch-001", "CONTROL")
        assert not manager.is_channel_authorized("ch-001", "RUNTIME")

    def test_channel_authorization_denies_unauthorized_message_type(self, manager):
        manager.open_channel(
            channel_id="ch-001",
            channel_class="CONTROL",
            connection_id="conn-001",
            source_subject_type="HYPERVISOR",
            source_subject_id="hv-001",
            destination_subject_type="HYPERVISOR",
            destination_subject_id="hv-002",
        )
        manager.authorize_channel(
            "ch-001",
            allowed_channel_classes={"CONTROL"},
            allowed_message_types={"SESSION_ACCEPT"},
        )
        assert manager.is_channel_authorized("ch-001", "CONTROL", "SESSION_ACCEPT")
        assert not manager.is_channel_authorized("ch-001", "CONTROL", "RUNTIME_EXECUTE")

    def test_no_explicit_auth_allows_by_default(self, manager):
        manager.open_channel(
            channel_id="ch-001",
            channel_class="CONTROL",
            connection_id="conn-001",
            source_subject_type="HYPERVISOR",
            source_subject_id="hv-001",
            destination_subject_type="HYPERVISOR",
            destination_subject_id="hv-002",
        )
        # No explicit authorization set — should allow
        assert manager.is_channel_authorized("ch-001", "RUNTIME")

    def test_revoke_channel(self, manager):
        manager.open_channel(
            channel_id="ch-001",
            channel_class="CONTROL",
            connection_id="conn-001",
            source_subject_type="HYPERVISOR",
            source_subject_id="hv-001",
            destination_subject_type="HYPERVISOR",
            destination_subject_id="hv-002",
        )
        manager.authorize_channel("ch-001")
        manager.revoke_channel("ch-001")
        assert not manager.is_channel_authorized("ch-001", "CONTROL")
        ch = manager.get_channel("ch-001")
        assert ch.state == ChannelState.CLOSED

    def test_update_stats(self, manager):
        manager.open_channel(
            channel_id="ch-001",
            channel_class="RUNTIME",
            connection_id="conn-001",
            source_subject_type="HYPERVISOR",
            source_subject_id="hv-001",
            destination_subject_type="RUNTIME",
            destination_subject_id="rt-001",
        )
        manager.update_stats("ch-001", 1024)
        manager.update_stats("ch-001", 2048)
        ch = manager.get_channel("ch-001")
        assert ch.message_count == 2
        assert ch.byte_count == 3072

    def test_open_channels_property(self, manager):
        manager.open_channel(
            channel_id="ch-001",
            channel_class="CONTROL",
            connection_id="conn-001",
            source_subject_type="HYPERVISOR",
            source_subject_id="hv-001",
            destination_subject_type="HYPERVISOR",
            destination_subject_id="hv-002",
        )
        manager.open_channel(
            channel_id="ch-002",
            channel_class="RUNTIME",
            connection_id="conn-001",
            source_subject_type="HYPERVISOR",
            source_subject_id="hv-001",
            destination_subject_type="RUNTIME",
            destination_subject_id="rt-001",
        )
        manager.close_channel("ch-001")
        assert len(manager.open_channels) == 1
