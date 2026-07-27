"""Tests for registry inventory exchange + Bloom filters (M8-S3)."""

from __future__ import annotations

import pytest

from aidn_hypervisor.registry.inventory import (
    BloomFilter,
    InventoryEntry,
    InventoryExchange,
    InventorySummary,
    RetrievalPlan,
)
from aidn_hypervisor.registry.object_envelope import RegistryObjectEnvelope
from aidn_hypervisor.registry.storage import ImmutableObjectStore

# ─── BloomFilter ────────────────────────────────────────────────────────────


class TestBloomFilter:

    def test_add_might_contain(self) -> None:
        bf = BloomFilter(estimated_elements=100)
        bf.add("object-1")
        assert bf.might_contain("object-1") is True

    def test_definitely_not(self) -> None:
        bf = BloomFilter(estimated_elements=100)
        bf.add("object-1")
        assert bf.definitely_not_contains("object-2") is True

    def test_false_positive_rate(self) -> None:
        """With 1000 elements and 1% FPR, false positives should be rare."""
        bf = BloomFilter(estimated_elements=1000, false_positive_rate=0.01)
        for i in range(1000):
            bf.add(f"item-{i}")

        # Check items that were NOT added
        false_positives = 0
        for i in range(10000, 11000):
            if bf.might_contain(f"item-{i}"):
                false_positives += 1

        # Should be roughly 1% or less
        rate = false_positives / 1000
        assert rate < 0.05, f"False positive rate {rate:.3f} too high"

    def test_serialize_deserialize(self) -> None:
        bf = BloomFilter(estimated_elements=100)
        bf.add("test-obj")
        data = bf.serialize()
        restored = BloomFilter.deserialize(
            data, estimated_elements=100, false_positive_rate=0.01
        )
        assert restored.might_contain("test-obj") is True
        assert restored.definitely_not_contains("other-obj") is True

    def test_merge(self) -> None:
        bf1 = BloomFilter(estimated_elements=100, false_positive_rate=0.01)
        bf2 = BloomFilter(estimated_elements=100, false_positive_rate=0.01)
        bf1.add("obj-a")
        bf2.add("obj-b")
        bf1.merge(bf2)
        assert bf1.might_contain("obj-a")
        assert bf1.might_contain("obj-b")

    def test_merge_size_mismatch(self) -> None:
        bf1 = BloomFilter(estimated_elements=100, false_positive_rate=0.01)
        bf2 = BloomFilter(estimated_elements=5000, false_positive_rate=0.01)
        with pytest.raises(ValueError, match="size mismatch"):
            bf1.merge(bf2)

    def test_default_params(self) -> None:
        bf = BloomFilter()
        assert bf._estimated_elements == 1000
        assert bf._false_positive_rate == 0.01
        assert bf.bit_count >= 64

    def test_custom_params(self) -> None:
        bf = BloomFilter(estimated_elements=50000, false_positive_rate=0.001)
        assert bf._estimated_elements == 50000
        assert bf._false_positive_rate == 0.001
        assert bf.bit_count > bf.hash_count * 10

    def test_element_count(self) -> None:
        bf = BloomFilter(estimated_elements=100)
        assert bf.element_count == 0
        bf.add("a")
        assert bf.element_count == 1
        bf.add("b")
        assert bf.element_count == 2

    def test_bit_count(self) -> None:
        bf = BloomFilter(estimated_elements=1000, false_positive_rate=0.01)
        assert bf.bit_count > 0
        assert bf.hash_count >= 2

    def test_many_elements(self) -> None:
        bf = BloomFilter(estimated_elements=5000, false_positive_rate=0.01)
        for i in range(5000):
            bf.add(f"elem-{i}")
        assert bf.element_count == 5000
        # All added items should be found
        for i in range(5000):
            assert bf.might_contain(f"elem-{i}")

    def test_deterministic(self) -> None:
        """Same inputs should produce same filter state."""
        bf1 = BloomFilter(estimated_elements=100, false_positive_rate=0.01)
        bf2 = BloomFilter(estimated_elements=100, false_positive_rate=0.01)
        for item in ["a", "b", "c", "d", "e"]:
            bf1.add(item)
            bf2.add(item)
        assert bf1.serialize() == bf2.serialize()


# ─── InventoryEntry ─────────────────────────────────────────────────────────


class TestInventoryEntry:

    def test_creation(self) -> None:
        entry = InventoryEntry(
            object_id="obj-1",
            object_type="finalized_block",
            content_hash="abc123",
            content_size=1024,
        )
        assert entry.object_id == "obj-1"
        assert entry.epoch is None

    def test_with_epoch(self) -> None:
        entry = InventoryEntry(
            object_id="obj-1",
            object_type="ledger_operation",
            content_hash="def456",
            content_size=512,
            epoch=42,
            block_height=100,
        )
        assert entry.epoch == 42
        assert entry.block_height == 100

    def test_frozen(self) -> None:
        entry = InventoryEntry(
            object_id="obj-1",
            object_type="finalized_block",
            content_hash="abc",
            content_size=100,
        )
        with pytest.raises(Exception):
            entry.object_id = "obj-2"  # type: ignore


# ─── InventorySummary ───────────────────────────────────────────────────────


class TestInventorySummary:

    def test_creation(self) -> None:
        summary = InventorySummary(
            peer_id="peer-1",
            total_objects=10,
            total_bytes=1024,
        )
        assert summary.peer_id == "peer-1"
        assert summary.total_objects == 10

    def test_frozen(self) -> None:
        summary = InventorySummary(
            peer_id="peer-1",
            total_objects=10,
            total_bytes=1024,
        )
        with pytest.raises(Exception):
            summary.peer_id = "peer-2"  # type: ignore


# ─── InventoryExchange ──────────────────────────────────────────────────────


class TestInventoryExchange:

    def _make_store_with_objects(self, count: int = 5) -> ImmutableObjectStore:
        store = ImmutableObjectStore()
        for i in range(count):
            obj = RegistryObjectEnvelope.create(
                object_type="finalized_block",
                payload={"index": i},
                created_epoch=i + 1,
            )
            store.put(obj)
        return store

    def test_build_summary(self) -> None:
        store = self._make_store_with_objects(5)
        exchange = InventoryExchange(store)
        summary = exchange.build_summary(peer_id="local-peer")
        assert summary.peer_id == "local-peer"
        assert summary.total_objects == 5
        assert summary.total_bytes > 0
        assert summary.timestamp > 0

    def test_build_bloom(self) -> None:
        store = self._make_store_with_objects(5)
        exchange = InventoryExchange(store)
        bf = exchange.build_bloom_filter()
        for oid in store.all_ids():
            assert bf.might_contain(oid)

    def test_find_missing(self) -> None:
        store = self._make_store_with_objects(3)
        exchange = InventoryExchange(store)
        # Remote has nothing
        remote_bf = BloomFilter(estimated_elements=100)
        missing = exchange.find_missing(remote_bf)
        assert len(missing) == 3

    def test_find_local_gaps(self) -> None:
        store = self._make_store_with_objects(2)
        exchange = InventoryExchange(store)
        local_ids = store.all_ids()
        # Remote has 5 objects, 3 of which we don't have
        remote_ids = local_ids + ["remote-1", "remote-2", "remote-3"]
        gaps = exchange.find_local_gaps(remote_ids)
        assert len(gaps) == 3
        assert "remote-1" in gaps

    def test_find_local_gaps_empty(self) -> None:
        store = self._make_store_with_objects(5)
        exchange = InventoryExchange(store)
        gaps = exchange.find_local_gaps(store.all_ids())
        assert len(gaps) == 0

    def test_retrieval_plan(self) -> None:
        store = self._make_store_with_objects(2)
        exchange = InventoryExchange(store)
        local_ids = store.all_ids()
        remote_ids = local_ids + ["new-1", "new-2"]
        plan = exchange.build_retrieval_plan(remote_ids)
        assert plan.total_missing == 2
        assert "new-1" in plan.object_ids

    def test_retrieval_plan_empty(self) -> None:
        store = self._make_store_with_objects(3)
        exchange = InventoryExchange(store)
        plan = exchange.build_retrieval_plan(store.all_ids())
        assert plan.total_missing == 0
        assert len(plan.object_ids) == 0

    def test_inventory_with_empty_store(self) -> None:
        store = ImmutableObjectStore()
        exchange = InventoryExchange(store)
        summary = exchange.build_summary(peer_id="empty-peer")
        assert summary.total_objects == 0
        assert summary.total_bytes == 0
        bf = exchange.build_bloom_filter()
        assert bf.element_count == 0


# ─── RetrievalPlan model ────────────────────────────────────────────────────


class TestRetrievalPlan:

    def test_model(self) -> None:
        plan = RetrievalPlan(
            total_missing=3,
            object_ids=["a", "b", "c"],
            priority=["a"],
            normal=["b", "c"],
        )
        assert plan.total_missing == 3
        assert len(plan.priority) == 1
        assert len(plan.normal) == 2


# ─── Integration ────────────────────────────────────────────────────────────


class TestInventoryExchangeIntegration:

    def test_full_flow(self) -> None:
        """Simulate two peers exchanging inventories."""
        # Peer A has objects 0-4
        store_a = ImmutableObjectStore()
        for i in range(5):
            obj = RegistryObjectEnvelope.create(
                object_type="finalized_block",
                payload={"index": i, "peer": "A"},
                created_epoch=i + 1,
            )
            store_a.put(obj)

        # Peer B has objects 3-7
        store_b = ImmutableObjectStore()
        for i in range(3, 8):
            obj = RegistryObjectEnvelope.create(
                object_type="finalized_block",
                payload={"index": i, "peer": "B"},
                created_epoch=i + 1,
            )
            store_b.put(obj)

        exchange_a = InventoryExchange(store_a)
        exchange_b = InventoryExchange(store_b)

        # A builds bloom filter of its inventory
        bloom_a = exchange_a.build_bloom_filter()
        # B checks what A is missing
        b_missing_from_a = exchange_b.find_missing(bloom_a)
        # B should report objects 5, 6, 7 (which A doesn't have)
        assert len(b_missing_from_a) >= 2

        # A builds bloom filter of its inventory
        bloom_b = exchange_b.build_bloom_filter()
        # A checks what B is missing
        a_missing_from_b = exchange_a.find_missing(bloom_b)
        # A should report objects 0, 1, 2 (which B doesn't have)
        assert len(a_missing_from_b) >= 2
