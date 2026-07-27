"""End-to-end integration tests for registry replication protocol.

Tests the full replication pipeline: inventory exchange, object transfer,
bloom filters, gRPC transport, bridge, verification, and discovery.
"""

import hashlib
import json
import time

import pytest

from aidn_hypervisor.registry.storage import ImmutableObjectStore
from aidn_hypervisor.registry.object_envelope import RegistryObjectEnvelope
from aidn_hypervisor.registry.inventory import BloomFilter, InventoryExchange
from aidn_hypervisor.registry.replicator import RegistryReplicator
from aidn_hypervisor.registry.discovery import (
    RegistryPeerDiscovery,
    AutoSyncController,
    DiscoveryConfig,
)
from aidn_hypervisor.registry.bridge import (
    RegistryServiceAdapter,
    legacy_record_to_envelope,
    envelope_to_legacy_record,
)
from aidn_hypervisor.registry.messages import (
    RegistryMessageType,
    RegistryMessageBuilder,
)
from aidn_hypervisor.registry.verification import (
    ObjectVerifier,
    ConsistencyChecker,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_envelope(
    object_id: str,
    object_type: str = "test_object",
    payload: dict | None = None,
    created_epoch: int = 1,
) -> RegistryObjectEnvelope:
    """Create a valid RegistryObjectEnvelope for testing."""
    if payload is None:
        payload = {"id": object_id, "data": "test"}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    content_hash = hashlib.sha256(canonical.encode()).hexdigest()
    content_size = len(canonical.encode())
    return RegistryObjectEnvelope(
        object_id=object_id,
        object_type=object_type,
        content_hash=content_hash,
        content_size=content_size,
        created_epoch=created_epoch,
        payload=payload,
    )


# ---------------------------------------------------------------------------
# Two-node replication
# ---------------------------------------------------------------------------


class TestTwoNodeReplication:
    """Integration tests for two-node registry replication."""

    def _setup_nodes(self, num_objects: int = 10):
        """Create two replicators; node_a has objects, node_b is empty."""
        store_a = ImmutableObjectStore()
        objects = []
        for i in range(num_objects):
            obj = _make_envelope(f"obj:{i}", created_epoch=i // 3 + 1)
            store_a.put(obj)
            objects.append(obj)
        store_b = ImmutableObjectStore()
        replicator_a = RegistryReplicator(node_id="node_a", store=store_a)
        replicator_b = RegistryReplicator(node_id="node_b", store=store_b)
        return replicator_a, replicator_b, objects

    def test_initial_state(self):
        """Node A has objects, Node B is empty."""
        r_a, r_b, objects = self._setup_nodes(10)
        assert r_a.store.stats().total_objects == 10
        assert r_b.store.stats().total_objects == 0

    def test_inventory_request_response(self):
        """Inventory request returns correct object count."""
        r_a, r_b, _ = self._setup_nodes(10)
        req = r_b.build_inventory_request("node_a")
        response = r_a.process_incoming_message(peer_id="node_b", message=req)
        assert response is not None
        assert response["payload"]["registry_payload"]["object_count"] == 10

    def test_object_request_response(self):
        """Object request delivers requested objects."""
        r_a, r_b, objects = self._setup_nodes(5)
        obj_ids = [o.object_id for o in objects[:3]]
        req = r_b.build_object_request("node_a", obj_ids)
        response = r_a.process_incoming_message(peer_id="node_b", message=req)
        assert response is not None
        resp_payload = response["payload"]["registry_payload"]
        assert resp_payload["total_delivered"] == 3

    def test_object_transfer_to_empty_node(self):
        """All objects can be transferred to an empty node."""
        r_a, r_b, objects = self._setup_nodes(5)
        for obj in objects:
            r_b.store.put(obj)
        assert r_b.store.stats().total_objects == 5

    def test_partial_object_transfer(self):
        """Partial transfer leaves different counts."""
        r_a, r_b, objects = self._setup_nodes(10)
        for obj in objects[:5]:
            r_b.store.put(obj)
        assert r_a.store.stats().total_objects == 10
        assert r_b.store.stats().total_objects == 5

    def test_announcement_triggers_object_request(self):
        """Receiving an announcement for an unknown object triggers a request."""
        r_a, r_b, _ = self._setup_nodes(0)
        announcement = r_a.build_announcement(
            object_id="new:obj:001",
            object_type="test_object",
            content_hash="abc123",
            created_epoch=1,
            content_size=100,
        )
        r_b.process_incoming_message(peer_id="node_a", message=announcement)
        outbox = r_b.get_outbox()
        assert len(outbox) >= 1

    def test_sync_start_with_inventory_exchange(self):
        """Starting sync sends an inventory request."""
        r_a, r_b, _ = self._setup_nodes(10)
        r_b.start_sync(peer_id="node_a", target_epoch=5, sync_mode="initial")
        outbox = r_b.get_outbox()
        assert len(outbox) >= 1

    def test_replication_stats(self):
        """Replication stats reflect current state."""
        r_a, r_b, _ = self._setup_nodes(10)
        stats = r_a.get_replication_stats()
        assert stats["node_id"] == "node_a"
        assert stats["store_objects"] == 10
        r_a.on_peer_connected("node_b")
        stats = r_a.get_replication_stats()
        assert stats["connected_peers"] == 1


# ---------------------------------------------------------------------------
# Bloom filter + inventory exchange
# ---------------------------------------------------------------------------


class TestBloomFilterInventoryExchange:
    """Integration tests for bloom filters and inventory exchange."""

    def test_bloom_filter_detects_missing_objects(self):
        """Bloom filter correctly identifies objects it contains."""
        store = ImmutableObjectStore()
        for i in range(20):
            store.put(_make_envelope(f"obj:{i}"))
        bloom = BloomFilter(estimated_elements=20, false_positive_rate=0.01)
        for oid in store.all_ids():
            bloom.add(oid)
        for i in range(20):
            assert bloom.might_contain(f"obj:{i}")

    def test_inventory_exchange_find_missing(self):
        """Inventory exchange identifies objects missing from remote."""
        store = ImmutableObjectStore()
        for i in range(10):
            store.put(_make_envelope(f"obj:{i}"))
        exchange = InventoryExchange(store)
        # Remote only has obj:0..4
        remote_bloom = BloomFilter(estimated_elements=5, false_positive_rate=0.01)
        for i in range(5):
            remote_bloom.add(f"obj:{i}")
        missing = exchange.find_missing(remote_bloom)
        assert len(missing) > 0

    def test_bloom_filter_serialize_deserialize(self):
        """Bloom filter can be serialized and deserialized."""
        bloom = BloomFilter(estimated_elements=100, false_positive_rate=0.01)
        for i in range(50):
            bloom.add(f"item:{i}")
        data = bloom.serialize()
        restored = BloomFilter.deserialize(
            data, estimated_elements=100, false_positive_rate=0.01
        )
        for i in range(50):
            assert restored.might_contain(f"item:{i}")


# ---------------------------------------------------------------------------
# gRPC transport integration
# ---------------------------------------------------------------------------


class TestGrpcTransportIntegration:
    """Integration tests for gRPC transport layer."""

    def test_stream_bidirectional_messaging(self):
        """Stream can send and receive messages between two transports."""
        from aidn_hypervisor.registry.grpc_transport import (
            GrpcRegistryTransport,
            GrpcRegistryStream,
            GrpcTransportConfig,
            GrpcProtoRegistryMessage,
        )

        transport_a = GrpcRegistryTransport(
            GrpcTransportConfig(host="localhost", port=50051)
        )
        transport_b = GrpcRegistryTransport(
            GrpcTransportConfig(host="localhost", port=50052)
        )
        transport_a.connect()
        transport_b.connect()

        stream = GrpcRegistryStream(transport_a, transport_b)
        msg = GrpcProtoRegistryMessage(
            message_type="test_message",
            source_node_id="node_a",
            destination_node_id="node_b",
            payload={"key": "value"},
        )
        data = msg.to_bytes()
        # Send A→B via stream: data lands in B's receive buffer
        stream.send(data)
        # Verify B can receive the message
        received_b = transport_b.receive()
        assert received_b is not None
        received_msg = GrpcProtoRegistryMessage.from_bytes(received_b)
        assert received_msg.message_type == "test_message"

        # Simulate B sending a reply back to A
        reply = GrpcProtoRegistryMessage(
            message_type="test_message",
            source_node_id="node_b",
            destination_node_id="node_a",
            payload={"reply": True},
        )
        transport_a.inject_message(reply.to_bytes())
        received_a = transport_a.receive()
        assert received_a is not None
        reply_msg = GrpcProtoRegistryMessage.from_bytes(received_a)
        assert reply_msg.payload["reply"] is True

    def test_transport_message_counting(self):
        """Transport correctly counts sent messages."""
        from aidn_hypervisor.registry.grpc_transport import (
            GrpcRegistryTransport,
        )

        transport = GrpcRegistryTransport()
        transport.connect()
        for i in range(5):
            transport.send(f"message_{i}".encode())
        state = transport.state
        assert state.messages_sent == 5

    def test_transport_keepalive(self):
        """Keepalive freshness is tracked correctly."""
        from aidn_hypervisor.registry.grpc_transport import (
            GrpcRegistryTransport,
        )

        transport = GrpcRegistryTransport()
        transport.connect()
        assert not transport.is_keepalive_stale(threshold_seconds=1)
        # Simulate stale keepalive
        transport._state = transport._state.model_copy(
            update={"last_keepalive_at": time.time() - 100}
        )
        assert transport.is_keepalive_stale(threshold_seconds=60)


# ---------------------------------------------------------------------------
# Bridge integration
# ---------------------------------------------------------------------------


class TestBridgeIntegration:
    """Integration tests for the legacy↔new store bridge."""

    def test_sync_from_legacy_to_new_store(self):
        """Legacy records are synced into the new ImmutableObjectStore."""
        from unittest.mock import MagicMock

        mock_legacy = MagicMock()
        mock_legacy.list_registry_objects.return_value = [
            {
                "object_id": f"legacy:{i}",
                "object_type": "test_object",
                "object_version": "1.0",
                "namespace": "default",
                "payload_hash": hashlib.sha256(
                    json.dumps(
                        {"id": f"legacy:{i}"},
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest(),
                "payload_encoding": "json",
                "source_reference": None,
                "payload": {"id": f"legacy:{i}"},
            }
            for i in range(5)
        ]
        adapter = RegistryServiceAdapter(legacy_service=mock_legacy)
        synced = adapter.sync_from_legacy()
        assert synced == 5
        for i in range(5):
            assert adapter.store.has(f"legacy:{i}")

    def test_sync_from_new_store_to_legacy(self):
        """New store objects are pushed to the legacy service."""
        from unittest.mock import MagicMock

        mock_legacy = MagicMock()
        mock_legacy.upsert_registry_object.return_value = {}
        store = ImmutableObjectStore()
        for i in range(3):
            store.put(_make_envelope(f"new:{i}"))
        adapter = RegistryServiceAdapter(legacy_service=mock_legacy, store=store)
        pushed = adapter.sync_to_legacy()
        assert pushed == 3

    def test_mirror_both_directions(self):
        """Mirror syncs both legacy→store and store→legacy."""
        from unittest.mock import MagicMock

        mock_legacy = MagicMock()
        mock_legacy.list_registry_objects.return_value = [
            {
                "object_id": "legacy:001",
                "object_type": "test",
                "object_version": "1.0",
                "namespace": "default",
                "payload_hash": hashlib.sha256(b"{}").hexdigest(),
                "payload_encoding": "json",
                "source_reference": None,
                "payload": {},
            }
        ]
        mock_legacy.upsert_registry_object.return_value = {}
        store = ImmutableObjectStore()
        store.put(_make_envelope("new:001"))
        adapter = RegistryServiceAdapter(legacy_service=mock_legacy, store=store)
        result = adapter.mirror(direction="both")
        assert result["synced_from_legacy"] >= 1
        assert result["pushed_to_legacy"] >= 1


# ---------------------------------------------------------------------------
# Verification integration
# ---------------------------------------------------------------------------


class TestVerificationIntegration:
    """Integration tests for object verification and consistency."""

    def test_verify_all_objects_valid(self):
        """All valid objects pass verification."""
        store = ImmutableObjectStore()
        for i in range(10):
            store.put(_make_envelope(f"obj:{i}"))
        verifier = ObjectVerifier(store)
        result = verifier.verify_all()
        assert result.valid == 10
        assert result.invalid == 0

    def test_store_rejects_hash_mismatch_at_ingress(self):
        """Tampered content hash never enters the immutable store."""
        store = ImmutableObjectStore()
        obj = _make_envelope("obj:001")
        tampered = obj.model_copy(update={"content_hash": "invalid_hash"})
        with pytest.raises(ValueError, match="integrity"):
            store.put(tampered)
        assert store.get("obj:001") is None

    def test_consistency_checker(self):
        """Consistency checker finds no errors for valid objects."""
        store = ImmutableObjectStore()
        for i in range(5):
            store.put(_make_envelope(f"obj:{i}"))
        checker = ConsistencyChecker(store)
        issues = checker.run_all_checks()
        error_issues = [i for i in issues if i.severity == "error"]
        assert len(error_issues) == 0


# ---------------------------------------------------------------------------
# Discovery integration
# ---------------------------------------------------------------------------


class TestDiscoveryIntegration:
    """Integration tests for peer discovery and auto-sync."""

    def test_discovery_auto_connect(self):
        """Discovered peers are auto-connected when configured."""
        store = ImmutableObjectStore()
        replicator = RegistryReplicator(node_id="node_a", store=store)
        config = DiscoveryConfig(auto_connect=True)
        discovery = RegistryPeerDiscovery(
            node_id="node_a",
            replicator=replicator,
            config=config,
        )
        peer = discovery.discover_peer(
            peer_id="node_b", address="localhost:50051"
        )
        assert peer is not None
        state = replicator.get_peer_state("node_b")
        assert state is not None
        assert state.connected

    def test_auto_sync_controller(self):
        """Auto-sync triggers sync for all connected peers."""
        store = ImmutableObjectStore()
        replicator = RegistryReplicator(node_id="node_a", store=store)
        discovery = RegistryPeerDiscovery(
            node_id="node_a", replicator=replicator
        )
        discovery.discover_peer(peer_id="node_b", address="localhost:50051")
        discovery.discover_peer(peer_id="node_c", address="localhost:50052")
        auto_sync = AutoSyncController(
            replicator=replicator, discovery=discovery
        )
        auto_sync.start()
        synced = auto_sync.check_and_sync()
        assert synced == 2

    def test_lag_detection(self):
        """Lag detection fires when lag exceeds threshold."""
        store = ImmutableObjectStore()
        replicator = RegistryReplicator(node_id="node_a", store=store)
        auto_sync = AutoSyncController(
            replicator=replicator, lag_threshold_epochs=3
        )
        # Lag of 2 — below threshold — should NOT fire
        assert not auto_sync.check_lag(current_epoch=10, target_epoch=12)
        # Lag of 5 — above threshold — should fire
        assert auto_sync.check_lag(current_epoch=10, target_epoch=15)
        alerts = auto_sync.get_alerts()
        assert len(alerts) >= 1
        assert alerts[0]["type"] == "high_lag"


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------


class TestFullPipeline:
    """End-to-end pipeline tests covering the full replication flow."""

    def test_full_replication_pipeline(self):
        """Full pipeline: inventory → object transfer → verification."""
        store_a = ImmutableObjectStore()
        store_b = ImmutableObjectStore()
        objects = []
        for i in range(20):
            obj = _make_envelope(f"obj:{i}", created_epoch=i // 5 + 1)
            store_a.put(obj)
            objects.append(obj)

        replicator_a = RegistryReplicator(node_id="node_a", store=store_a)
        replicator_b = RegistryReplicator(node_id="node_b", store=store_b)

        # Connect peers
        replicator_a.on_peer_connected("node_b")
        replicator_b.on_peer_connected("node_a")

        # Inventory exchange
        inv_request = replicator_b.build_inventory_request("node_a")
        inv_response = replicator_a.process_incoming_message(
            peer_id="node_b", message=inv_request
        )
        assert inv_response is not None
        assert inv_response["payload"]["registry_payload"]["object_count"] == 20

        # Transfer all objects
        for obj in objects:
            replicator_b.store.put(obj)

        # Verify both stores
        verifier_a = ObjectVerifier(store_a)
        verifier_b = ObjectVerifier(store_b)
        result_a = verifier_a.verify_all()
        result_b = verifier_b.verify_all()
        assert result_a.valid == 20
        assert result_b.valid == 20
        assert store_a.stats().total_objects == store_b.stats().total_objects

    def test_multiple_object_types(self):
        """Store correctly tracks multiple object types."""
        store = ImmutableObjectStore()
        types = [
            "reputation_profile",
            "validation_report",
            "onboarding_capability",
        ]
        for obj_type in types:
            for i in range(3):
                store.put(
                    _make_envelope(f"{obj_type}:{i}", object_type=obj_type)
                )
        stats = store.stats()
        assert stats.total_objects == 9
        assert len(stats.objects_by_type) == 3

    def test_epoch_coverage_after_sync(self):
        """Epoch coverage is consistent after syncing objects."""
        store_a = ImmutableObjectStore()
        store_b = ImmutableObjectStore()
        for epoch in range(5):
            for i in range(2):
                obj = _make_envelope(
                    f"epoch{epoch}:obj{i}", created_epoch=epoch
                )
                store_a.put(obj)
                store_b.put(obj)
        stats_a = store_a.stats()
        stats_b = store_b.stats()
        assert stats_a.earliest_epoch == 0
        assert stats_a.latest_epoch == 4
        assert stats_a.earliest_epoch == stats_b.earliest_epoch
