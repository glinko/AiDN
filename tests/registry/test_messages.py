"""Tests for Registry Network Message Types (M9-S1)."""

from __future__ import annotations

import uuid

import pytest

from aidn_hypervisor.registry.messages import (
    AnnouncementPayload,
    BloomFilterPayload,
    ChallengePayload,
    InventoryRequestPayload,
    InventoryResponsePayload,
    ObjectRequestPayload,
    ObjectResponsePayload,
    RegistryChannelClass,
    RegistryMessageBuilder,
    RegistryMessageType,
    RegistryPayload,
    RepairPayload,
    SyncStatusPayload,
)

# ─── Enum Tests ─────────────────────────────────────────────────────────────


class TestRegistryMessageTypeEnum:

    def test_registry_message_type_enum(self) -> None:
        """All expected message types exist."""
        assert RegistryMessageType.INVENTORY_REQUEST == "registry_inventory_request"
        assert RegistryMessageType.INVENTORY_RESPONSE == "registry_inventory_response"
        assert RegistryMessageType.OBJECT_REQUEST == "registry_object_request"
        assert RegistryMessageType.OBJECT_RESPONSE == "registry_object_response"
        assert RegistryMessageType.BLOOM_FILTER == "registry_bloom_filter"
        assert RegistryMessageType.SYNC_STATUS == "registry_sync_status"
        assert RegistryMessageType.ANNOUNCEMENT == "registry_announcement"
        assert RegistryMessageType.CHALLENGE == "registry_challenge"
        assert RegistryMessageType.REPAIR == "registry_repair"
        assert RegistryMessageType.EPOCH_UPDATE == "registry_epoch_update"

    def test_registry_channel_class_enum(self) -> None:
        """All expected channel classes exist."""
        assert RegistryChannelClass.REGISTRY_REPLICATION == "registry_replication"
        assert RegistryChannelClass.REGISTRY_DISCOVERY == "registry_discovery"
        assert RegistryChannelClass.REGISTRY_CONTROL == "registry_control"


# ─── Base RegistryPayload ───────────────────────────────────────────────────


class TestRegistryPayloadBase:

    def test_registry_payload_base(self) -> None:
        """Base payload has all required fields."""
        p = RegistryPayload(registry_message_type="test_type")
        assert p.registry_message_type == "test_type"
        assert p.source_node_id == ""
        assert p.destination_node_id == ""
        assert p.sequence_number == 0
        assert p.payload_version == "1.0"
        assert isinstance(p.correlation_id, str) and len(p.correlation_id) == 36
        assert isinstance(p.created_at, float) and p.created_at > 0

    def test_registry_payload_frozen(self) -> None:
        """Payload models are frozen (immutable)."""
        p = RegistryPayload(registry_message_type="test_type")
        with pytest.raises(Exception):
            p.registry_message_type = "other"  # type: ignore


# ─── Specific Payload Types ─────────────────────────────────────────────────


class TestInventoryRequestPayload:

    def test_inventory_request_payload(self) -> None:
        """InventoryRequestPayload has correct type and fields."""
        p = InventoryRequestPayload(
            source_node_id="node-a",
            destination_node_id="node-b",
            requested_object_types=["reputation_profile"],
            epoch_range=(10, 20),
            include_bloom=False,
        )
        assert p.registry_message_type == RegistryMessageType.INVENTORY_REQUEST
        assert p.source_node_id == "node-a"
        assert p.destination_node_id == "node-b"
        assert p.requested_object_types == ["reputation_profile"]
        assert p.epoch_range == (10, 20)
        assert p.include_bloom is False

    def test_inventory_request_defaults(self) -> None:
        """InventoryRequestPayload defaults are correct."""
        p = InventoryRequestPayload()
        assert p.requested_object_types == []
        assert p.epoch_range == (0, 0)
        assert p.include_bloom is True


class TestInventoryResponsePayload:

    def test_inventory_response_payload(self) -> None:
        """InventoryResponsePayload has correct type and fields."""
        p = InventoryResponsePayload(
            source_node_id="node-a",
            destination_node_id="node-b",
            object_count=42,
            object_types={"reputation_profile": 10, "validation_report": 5},
            earliest_epoch=1,
            latest_epoch=100,
            bloom_filter_data=b"\x00\x01",
            inventory_root_hash="abc123",
        )
        assert p.registry_message_type == RegistryMessageType.INVENTORY_RESPONSE
        assert p.object_count == 42
        assert p.object_types == {"reputation_profile": 10, "validation_report": 5}
        assert p.earliest_epoch == 1
        assert p.latest_epoch == 100
        assert p.bloom_filter_data == b"\x00\x01"
        assert p.inventory_root_hash == "abc123"


class TestObjectRequestPayload:

    def test_object_request_payload(self) -> None:
        """ObjectRequestPayload has correct type and fields."""
        p = ObjectRequestPayload(
            source_node_id="node-a",
            destination_node_id="node-b",
            object_ids=["id-1", "id-2"],
            object_type="reputation_profile",
            include_payload=True,
        )
        assert p.registry_message_type == RegistryMessageType.OBJECT_REQUEST
        assert p.object_ids == ["id-1", "id-2"]
        assert p.object_type == "reputation_profile"
        assert p.include_payload is True


class TestObjectResponsePayload:

    def test_object_response_payload(self) -> None:
        """ObjectResponsePayload has correct type and fields."""
        objs = [{"object_id": "id-1", "data": "test"}]
        p = ObjectResponsePayload(
            source_node_id="node-a",
            destination_node_id="node-b",
            objects=objs,
            missing_ids=["id-3"],
            total_requested=3,
            total_delivered=1,
        )
        assert p.registry_message_type == RegistryMessageType.OBJECT_RESPONSE
        assert len(p.objects) == 1
        assert p.missing_ids == ["id-3"]
        assert p.total_requested == 3
        assert p.total_delivered == 1

    def test_object_response_missing_ids(self) -> None:
        """ObjectResponsePayload missing_ids defaults to empty list."""
        p = ObjectResponsePayload()
        assert p.missing_ids == []
        assert p.objects == []
        assert p.total_requested == 0
        assert p.total_delivered == 0


class TestBloomFilterPayload:

    def test_bloom_filter_payload(self) -> None:
        """BloomFilterPayload has correct type and fields."""
        data = b"\x00\x01\x02\x03"
        p = BloomFilterPayload(
            source_node_id="node-a",
            filter_data=data,
            expected_items=100,
            false_positive_rate=0.01,
            hash_count=5,
        )
        assert p.registry_message_type == RegistryMessageType.BLOOM_FILTER
        assert p.filter_data == data
        assert p.expected_items == 100
        assert p.false_positive_rate == 0.01
        assert p.hash_count == 5


class TestSyncStatusPayload:

    def test_sync_status_payload(self) -> None:
        """SyncStatusPayload has correct type and fields."""
        p = SyncStatusPayload(
            source_node_id="node-a",
            destination_node_id="node-b",
            sync_mode="catch_up",
            current_epoch=50,
            target_epoch=100,
            progress=0.5,
            objects_synced=200,
            bytes_synced=10240,
            error=None,
            completed=False,
        )
        assert p.registry_message_type == RegistryMessageType.SYNC_STATUS
        assert p.sync_mode == "catch_up"
        assert p.current_epoch == 50
        assert p.target_epoch == 100
        assert p.progress == 0.5
        assert p.objects_synced == 200
        assert p.bytes_synced == 10240

    def test_sync_status_completed(self) -> None:
        """SyncStatusPayload can mark sync as completed."""
        p = SyncStatusPayload(
            source_node_id="node-a",
            destination_node_id="node-b",
            sync_mode="live",
            current_epoch=100,
            target_epoch=100,
            progress=1.0,
            completed=True,
        )
        assert p.completed is True
        assert p.progress == 1.0


class TestAnnouncementPayload:

    def test_announcement_payload(self) -> None:
        """AnnouncementPayload has correct type and fields."""
        p = AnnouncementPayload(
            source_node_id="node-a",
            object_id="obj-1",
            object_type="reputation_profile",
            content_hash="sha256:abc",
            created_epoch=42,
            content_size=1024,
        )
        assert p.registry_message_type == RegistryMessageType.ANNOUNCEMENT
        assert p.object_id == "obj-1"
        assert p.object_type == "reputation_profile"
        assert p.content_hash == "sha256:abc"
        assert p.created_epoch == 42
        assert p.content_size == 1024


class TestChallengePayload:

    def test_challenge_payload(self) -> None:
        """ChallengePayload has correct type and fields."""
        p = ChallengePayload(
            source_node_id="node-a",
            destination_node_id="node-b",
            challenge_id="ch-1",
            challenge_type="completeness",
            target_object_ids=["id-1", "id-2"],
            target_epochs=[10, 20],
            deadline_epoch=100,
            evidence_required=True,
        )
        assert p.registry_message_type == RegistryMessageType.CHALLENGE
        assert p.challenge_id == "ch-1"
        assert p.challenge_type == "completeness"
        assert p.target_object_ids == ["id-1", "id-2"]
        assert p.evidence_required is True

    def test_challenge_payload_defaults(self) -> None:
        """ChallengePayload defaults are correct."""
        p = ChallengePayload()
        assert p.challenge_type == "completeness"
        assert p.target_object_ids == []
        assert p.target_epochs == []
        assert p.deadline_epoch == 0
        assert p.evidence_required is True
        assert isinstance(p.challenge_id, str) and len(p.challenge_id) == 36


class TestRepairPayload:

    def test_repair_payload(self) -> None:
        """RepairPayload has correct type and fields."""
        replacements = [{"object_id": "id-1", "data": "fixed"}]
        p = RepairPayload(
            source_node_id="node-a",
            destination_node_id="node-b",
            repair_id="rep-1",
            gap_type="missing_objects",
            replacement_objects=replacements,
            removal_ids=["id-bad"],
        )
        assert p.registry_message_type == RegistryMessageType.REPAIR
        assert p.repair_id == "rep-1"
        assert p.gap_type == "missing_objects"
        assert len(p.replacement_objects) == 1
        assert p.removal_ids == ["id-bad"]

    def test_repair_payload_defaults(self) -> None:
        """RepairPayload defaults are correct."""
        p = RepairPayload()
        assert p.gap_type == "missing_objects"
        assert p.replacement_objects == []
        assert p.removal_ids == []
        assert isinstance(p.repair_id, str) and len(p.repair_id) == 36


# ─── RegistryMessageBuilder ─────────────────────────────────────────────────


class TestMessageBuilderInit:

    def test_message_builder_init(self) -> None:
        """Builder initializes with correct defaults."""
        b = RegistryMessageBuilder(node_id="node-a")
        assert b._node_id == "node-a"
        assert b._network_id == "aidn"
        assert b._chain_id == "main"
        assert b._network_revision == "1.0"
        assert b._sequence_counter == 0

    def test_message_builder_network_id(self) -> None:
        """Builder accepts custom network_id."""
        b = RegistryMessageBuilder(node_id="node-a", network_id="testnet")
        assert b._network_id == "testnet"


# ─── Builder: build() ───────────────────────────────────────────────────────


class TestBuildMessage:

    def test_build_inventory_request(self) -> None:
        """build_inventory_request produces a valid message dict."""
        b = RegistryMessageBuilder(node_id="node-a")
        msg = b.build_inventory_request(
            destination_node_id="node-b",
            object_types=["reputation_profile"],
        )
        assert msg["message_type"] == RegistryMessageType.INVENTORY_REQUEST
        assert msg["source_subject"]["subject_id"] == "node-a"
        assert msg["destination_subject"]["subject_id"] == "node-b"

    def test_build_object_request(self) -> None:
        """build_object_request produces a valid message dict."""
        b = RegistryMessageBuilder(node_id="node-a")
        msg = b.build_object_request(
            destination_node_id="node-b",
            object_ids=["id-1", "id-2"],
        )
        assert msg["message_type"] == RegistryMessageType.OBJECT_REQUEST
        assert msg["source_subject"]["subject_id"] == "node-a"

    def test_build_sync_status(self) -> None:
        """build_sync_status produces a valid message dict."""
        b = RegistryMessageBuilder(node_id="node-a")
        msg = b.build_sync_status(
            destination_node_id="node-b",
            sync_mode="catch_up",
            current_epoch=50,
            target_epoch=100,
            progress=0.5,
        )
        assert msg["message_type"] == RegistryMessageType.SYNC_STATUS
        payload = msg["payload"]["registry_payload"]
        assert payload["sync_mode"] == "catch_up"
        assert payload["current_epoch"] == 50

    def test_build_announcement(self) -> None:
        """build_announcement produces a valid message dict."""
        b = RegistryMessageBuilder(node_id="node-a")
        msg = b.build_announcement(
            object_id="obj-1",
            object_type="reputation_profile",
            content_hash="sha256:abc",
            created_epoch=42,
            content_size=1024,
        )
        assert msg["message_type"] == RegistryMessageType.ANNOUNCEMENT
        payload = msg["payload"]["registry_payload"]
        assert payload["object_id"] == "obj-1"
        assert payload["content_size"] == 1024

    def test_build_message_fields(self) -> None:
        """Built message has all required NetworkMessage-compatible fields."""
        b = RegistryMessageBuilder(node_id="node-a")
        msg = b.build_inventory_request(destination_node_id="node-b")

        required_fields = [
            "message_id", "message_type", "message_version",
            "network_id", "chain_id", "network_revision",
            "channel_id", "channel_class",
            "source_subject", "destination_subject",
            "source_sequence", "priority_class", "route_generation",
            "created_at", "expiration", "hop_limit",
            "payload_hash", "payload_length", "payload_encoding",
            "payload",
        ]
        for field in required_fields:
            assert field in msg, f"Missing field: {field}"

    def test_build_message_payload_hash(self) -> None:
        """payload_hash is sha256: prefix followed by 64 hex chars."""
        b = RegistryMessageBuilder(node_id="node-a")
        msg = b.build_inventory_request(destination_node_id="node-b")
        assert msg["payload_hash"].startswith("sha256:")
        hex_part = msg["payload_hash"][7:]
        assert len(hex_part) == 64
        int(hex_part, 16)  # valid hex

    def test_sequence_counter_increments(self) -> None:
        """Sequence counter increments with each build."""
        b = RegistryMessageBuilder(node_id="node-a")
        msg1 = b.build_inventory_request(destination_node_id="node-b")
        msg2 = b.build_inventory_request(destination_node_id="node-b")
        assert msg2["source_sequence"] == msg1["source_sequence"] + 1

    def test_build_default_expiration(self) -> None:
        """Default expiration is 300 seconds from creation."""
        b = RegistryMessageBuilder(node_id="node-a")
        msg = b.build_inventory_request(destination_node_id="node-b")
        created = float(msg["created_at"])
        expires = float(msg["expiration"])
        assert 299 <= (expires - created) <= 301

    def test_build_custom_destination(self) -> None:
        """Custom destination_node_id overrides payload destination."""
        b = RegistryMessageBuilder(node_id="node-a")
        msg = b.build_inventory_request(
            destination_node_id="node-c",
        )
        assert msg["destination_subject"]["subject_id"] == "node-c"

    def test_payload_correlation_id(self) -> None:
        """Each message gets a unique correlation_id."""
        b = RegistryMessageBuilder(node_id="node-a")
        msg1 = b.build_inventory_request(destination_node_id="node-b")
        msg2 = b.build_inventory_request(destination_node_id="node-b")
        cid1 = msg1["payload"]["registry_payload"]["correlation_id"]
        cid2 = msg2["payload"]["registry_payload"]["correlation_id"]
        assert cid1 != cid2
        uuid.UUID(cid1)  # valid UUID
        uuid.UUID(cid2)

    def test_build_broadcast_destination(self) -> None:
        """Announcement messages broadcast (no explicit destination)."""
        b = RegistryMessageBuilder(node_id="node-a")
        msg = b.build_announcement(
            object_id="obj-1",
            object_type="reputation_profile",
            content_hash="sha256:abc",
            created_epoch=42,
            content_size=1024,
        )
        assert msg["destination_subject"]["subject_id"] == "broadcast"

    def test_build_channel_class_override(self) -> None:
        """Channel class can be overridden per message."""
        b = RegistryMessageBuilder(node_id="node-a")
        p = InventoryRequestPayload(
            source_node_id="node-a",
            destination_node_id="node-b",
        )
        msg = b.build(
            p,
            channel_class=RegistryChannelClass.REGISTRY_DISCOVERY,
            destination_node_id="node-b",
        )
        assert msg["channel_class"] == RegistryChannelClass.REGISTRY_DISCOVERY
        assert RegistryChannelClass.REGISTRY_DISCOVERY in msg["channel_id"]

    def test_build_message_source_subject(self) -> None:
        """Source subject type is registry_node."""
        b = RegistryMessageBuilder(node_id="node-a")
        msg = b.build_inventory_request(destination_node_id="node-b")
        assert msg["source_subject"]["subject_type"] == "registry_node"
        assert msg["source_subject"]["subject_id"] == "node-a"
        assert msg["destination_subject"]["subject_type"] == "registry_node"


# ─── Full Flow ──────────────────────────────────────────────────────────────


class TestFullMessageFlow:

    def test_full_message_flow(self) -> None:
        """End-to-end: build, serialize, deserialize, verify."""
        builder = RegistryMessageBuilder(node_id="node-a")

        # Build an inventory request
        msg = builder.build_inventory_request(
            destination_node_id="node-b",
            object_types=["reputation_profile", "validation_report"],
            epoch_range=(10, 50),
        )

        # Verify structure
        assert msg["message_type"] == RegistryMessageType.INVENTORY_REQUEST
        assert msg["network_id"] == "aidn"
        assert msg["chain_id"] == "main"
        assert msg["channel_class"] == RegistryChannelClass.REGISTRY_REPLICATION

        # Verify payload roundtrip
        payload_data = msg["payload"]["registry_payload"]
        assert payload_data["registry_message_type"] == RegistryMessageType.INVENTORY_REQUEST
        assert payload_data["requested_object_types"] == ["reputation_profile", "validation_report"]
        assert tuple(payload_data["epoch_range"]) == (10, 50)
        assert payload_data["source_node_id"] == "node-a"
        assert payload_data["destination_node_id"] == "node-b"

        # Verify raw_bytes present
        assert "raw_bytes" in msg["payload"]

        # Verify payload_length is positive
        assert msg["payload_length"] > 0

        # Verify message_id is valid UUID
        uuid.UUID(msg["message_id"])

        # Build object request and verify sequence incremented
        msg2 = builder.build_object_request(
            destination_node_id="node-b",
            object_ids=["id-1"],
        )
        assert msg2["source_sequence"] == msg["source_sequence"] + 1
        assert msg2["message_type"] == RegistryMessageType.OBJECT_REQUEST
