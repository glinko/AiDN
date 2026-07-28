"""
Registry Network Message Types (M9-S1).

Registry-specific message types for replication protocol, built on top of
the dispatcher's NetworkMessage envelope format.

RFC-0042 §50-§131 compliance for message envelope structure.
"""

from __future__ import annotations

import time
import uuid

from pydantic import BaseModel, ConfigDict, Field

from aidn_hypervisor.dispatcher.models import (
    canonical_payload_bytes,
    canonical_payload_hash,
)


class RegistryMessageType(str):
    """Registry replication message types."""
    INVENTORY_REQUEST = "registry_inventory_request"
    INVENTORY_RESPONSE = "registry_inventory_response"
    OBJECT_REQUEST = "registry_object_request"
    OBJECT_RESPONSE = "registry_object_response"
    BLOOM_FILTER = "registry_bloom_filter"
    SYNC_STATUS = "registry_sync_status"
    ANNOUNCEMENT = "registry_announcement"
    CHALLENGE = "registry_challenge"
    REPAIR = "registry_repair"
    EPOCH_UPDATE = "registry_epoch_update"


class RegistryChannelClass(str):
    """Channel class for registry traffic."""
    REGISTRY_REPLICATION = "registry_replication"
    REGISTRY_DISCOVERY = "registry_discovery"
    REGISTRY_CONTROL = "registry_control"


class RegistryPayload(BaseModel, frozen=True):
    """
    Base payload for all registry replication messages.

    Wraps registry-specific data for transport in NetworkMessage envelopes.
    """
    registry_message_type: str
    correlation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_node_id: str = ""
    destination_node_id: str = ""
    created_at: float = Field(default_factory=time.time)
    sequence_number: int = 0
    payload_version: str = "1.0"

    # Registry inventory payloads may contain Bloom-filter bytes. Encode them
    # deterministically before they enter the outer canonical NetworkMessage.
    model_config = ConfigDict(ser_json_bytes="base64", val_json_bytes="base64")


class InventoryRequestPayload(RegistryPayload):
    """Request for peer inventory summary."""
    registry_message_type: str = RegistryMessageType.INVENTORY_REQUEST
    requested_object_types: list[str] = Field(default_factory=list)
    epoch_range: tuple[int, int] = (0, 0)  # (start, end); (0,0) = all
    include_bloom: bool = True


class InventoryResponsePayload(RegistryPayload):
    """Response with inventory summary."""
    registry_message_type: str = RegistryMessageType.INVENTORY_RESPONSE
    object_count: int = 0
    object_types: dict[str, int] = Field(default_factory=dict)
    earliest_epoch: int = 0
    latest_epoch: int = 0
    bloom_filter_data: bytes | None = None
    inventory_root_hash: str = ""
    object_ids: list[str] = Field(default_factory=list)
    inventory_truncated: bool = False


class ObjectRequestPayload(RegistryPayload):
    """Request for specific registry objects."""
    registry_message_type: str = RegistryMessageType.OBJECT_REQUEST
    object_ids: list[str] = Field(default_factory=list)
    object_type: str = ""
    include_payload: bool = True


class ObjectResponsePayload(RegistryPayload):
    """Response with requested objects."""
    registry_message_type: str = RegistryMessageType.OBJECT_RESPONSE
    objects: list[dict] = Field(default_factory=list)
    missing_ids: list[str] = Field(default_factory=list)
    total_requested: int = 0
    total_delivered: int = 0


class BloomFilterPayload(RegistryPayload):
    """Bloom filter for inventory comparison."""
    registry_message_type: str = RegistryMessageType.BLOOM_FILTER
    filter_data: bytes = b""
    expected_items: int = 0
    false_positive_rate: float = 0.01
    hash_count: int = 0


class SyncStatusPayload(RegistryPayload):
    """Synchronization status update."""
    registry_message_type: str = RegistryMessageType.SYNC_STATUS
    sync_mode: str = "initial"  # initial | catch_up | live | repair
    current_epoch: int = 0
    target_epoch: int = 0
    objects_synced: int = 0
    bytes_synced: int = 0
    progress: float = 0.0
    error: str | None = None
    completed: bool = False


class AnnouncementPayload(RegistryPayload):
    """New object announcement."""
    registry_message_type: str = RegistryMessageType.ANNOUNCEMENT
    object_id: str = ""
    object_type: str = ""
    content_hash: str = ""
    created_epoch: int = 0
    content_size: int = 0


class ChallengePayload(RegistryPayload):
    """Registry challenge for completeness proof."""
    registry_message_type: str = RegistryMessageType.CHALLENGE
    challenge_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    challenge_type: str = "completeness"  # completeness | consistency | freshness
    target_object_ids: list[str] = Field(default_factory=list)
    target_epochs: list[int] = Field(default_factory=list)
    deadline_epoch: int = 0
    evidence_required: bool = True


class RepairPayload(RegistryPayload):
    """Repair data for detected gaps."""
    registry_message_type: str = RegistryMessageType.REPAIR
    repair_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    gap_type: str = "missing_objects"  # missing_objects | stale_objects | inconsistent
    replacement_objects: list[dict] = Field(default_factory=list)
    removal_ids: list[str] = Field(default_factory=list)


# Registry-specific message builder
class RegistryMessageBuilder:
    """
    Build NetworkMessage envelopes from registry payloads.

    Bridges registry replication messages with the dispatcher's
    NetworkMessage envelope format.
    """

    def __init__(
        self,
        *,
        node_id: str,
        network_id: str = "aidn",
        chain_id: str = "main",
        network_revision: str = "1.0",
    ):
        self._node_id = node_id
        self._network_id = network_id
        self._chain_id = chain_id
        self._network_revision = network_revision
        self._sequence_counter = 0

    def build(
        self,
        payload: RegistryPayload,
        *,
        channel_class: str = RegistryChannelClass.REGISTRY_REPLICATION,
        destination_node_id: str | None = None,
        expiration_seconds: int = 300,
    ) -> dict:
        """
        Build a NetworkMessage-compatible dict from a registry payload.

        Returns a dict suitable for NetworkMessage construction.
        """
        self._sequence_counter += 1
        now = time.time()
        registry_payload = payload.model_dump(mode="json")
        outer_payload = {"registry_payload": registry_payload}
        payload_bytes = canonical_payload_bytes(outer_payload)

        dest = destination_node_id or payload.destination_node_id or "broadcast"

        return {
            "message_id": str(uuid.uuid4()),
            "message_type": payload.registry_message_type,
            "message_version": "1",
            "network_id": self._network_id,
            "chain_id": self._chain_id,
            "network_revision": self._network_revision,
            "channel_id": self._channel_id(channel_class),
            "channel_class": "REGISTRY",
            "source_subject": {
                "subject_type": "registry_node",
                "subject_id": self._node_id,
            },
            "destination_subject": {
                "subject_type": "registry_node",
                "subject_id": dest,
            },
            "source_sequence": self._sequence_counter,
            "priority_class": "NORMAL",
            "route_generation": 1,
            "created_at": str(now),
            "expiration": str(now + expiration_seconds),
            "hop_limit": 2,
            "payload_hash": canonical_payload_hash(outer_payload),
            "payload_length": len(payload_bytes),
            "payload_encoding": "CANONICAL_JSON",
            "payload": outer_payload,
        }

    @staticmethod
    def _channel_id(channel_class: str) -> str:
        channel_ids = {
            RegistryChannelClass.REGISTRY_REPLICATION: "registry:replication",
            RegistryChannelClass.REGISTRY_DISCOVERY: "registry:discovery",
            RegistryChannelClass.REGISTRY_CONTROL: "registry:control",
        }
        try:
            return channel_ids[channel_class]
        except KeyError as error:
            raise ValueError(f"Unsupported Registry channel class: {channel_class}") from error

    def build_inventory_request(
        self,
        *,
        destination_node_id: str,
        object_types: list[str] | None = None,
        epoch_range: tuple[int, int] = (0, 0),
    ) -> dict:
        """Build an inventory request message."""
        payload = InventoryRequestPayload(
            source_node_id=self._node_id,
            destination_node_id=destination_node_id,
            requested_object_types=object_types or [],
            epoch_range=epoch_range,
        )
        return self.build(payload, destination_node_id=destination_node_id)

    def build_object_request(
        self,
        *,
        destination_node_id: str,
        object_ids: list[str],
        include_payload: bool = True,
    ) -> dict:
        """Build an object request message."""
        payload = ObjectRequestPayload(
            source_node_id=self._node_id,
            destination_node_id=destination_node_id,
            object_ids=object_ids,
            include_payload=include_payload,
        )
        return self.build(payload, destination_node_id=destination_node_id)

    def build_sync_status(
        self,
        *,
        destination_node_id: str,
        sync_mode: str,
        current_epoch: int,
        target_epoch: int,
        progress: float,
        objects_synced: int = 0,
        bytes_synced: int = 0,
        error: str | None = None,
    ) -> dict:
        """Build a sync status message."""
        payload = SyncStatusPayload(
            source_node_id=self._node_id,
            destination_node_id=destination_node_id,
            sync_mode=sync_mode,
            current_epoch=current_epoch,
            target_epoch=target_epoch,
            progress=progress,
            objects_synced=objects_synced,
            bytes_synced=bytes_synced,
            error=error,
        )
        return self.build(payload, destination_node_id=destination_node_id)

    def build_announcement(
        self,
        *,
        object_id: str,
        object_type: str,
        content_hash: str,
        created_epoch: int,
        content_size: int,
    ) -> dict:
        """Build an announcement message."""
        payload = AnnouncementPayload(
            source_node_id=self._node_id,
            object_id=object_id,
            object_type=object_type,
            content_hash=content_hash,
            created_epoch=created_epoch,
            content_size=content_size,
        )
        return self.build(payload)
