"""Tests for registry anti-entropy protocol (RFC-0061 §§53-58)."""

from __future__ import annotations

import time

import pytest

from aidn_hypervisor.registry import (
    AntiEntropyEngine,
    AntiEntropyRound,
    ImmutableObjectStore,
    RegistryObjectEnvelope,
)
from aidn_hypervisor.registry.inventory import BloomFilter

# ─── Helpers ────────────────────────────────────────────────────────────────


def _make_envelope(
    *,
    obj_type: str = "test",
    payload: dict | None = None,
    object_id: str | None = None,
    created_epoch: int | None = None,
) -> RegistryObjectEnvelope:
    return RegistryObjectEnvelope.create(
        object_type=obj_type,
        payload=payload or {"key": "value"},
        object_id=object_id,
        created_epoch=created_epoch,
    )


def _store_with_objects(count: int = 3) -> ImmutableObjectStore:
    store = ImmutableObjectStore()
    for i in range(count):
        env = _make_envelope(
            object_id=f"obj-{i}",
            created_epoch=i + 1,
            payload={"index": i},
        )
        store.put(env)
    return store


# ─── AntiEntropyRound model ────────────────────────────────────────────────


class TestAntiEntropyRound:

    def test_anti_entropy_round_frozen(self) -> None:
        round_rec = AntiEntropyRound(
            round_id="test",
            peer_id="peer-1",
            status="pending",
        )
        with pytest.raises(Exception):
            round_rec.status = "completed"  # type: ignore


# ─── AntiEntropyEngine init ────────────────────────────────────────────────


class TestAntiEntropyEngineInit:

    def test_anti_entropy_init(self) -> None:
        store = ImmutableObjectStore()
        engine = AntiEntropyEngine(store)
        assert engine.get_rounds() == []
        assert engine.get_discrepancies() == []


# ─── Start Round ───────────────────────────────────────────────────────────


class TestStartRound:

    def test_start_round(self) -> None:
        store = _store_with_objects()
        engine = AntiEntropyEngine(store)

        round_rec = engine.start_round(peer_id="peer-1")

        assert round_rec.round_id != ""
        assert round_rec.peer_id == "peer-1"
        assert round_rec.status == "in_progress"
        assert round_rec.started_at > 0

    def test_round_id_unique(self) -> None:
        """Two rounds started at different times should have unique ids."""
        store = _store_with_objects()
        engine = AntiEntropyEngine(store)

        r1 = engine.start_round(peer_id="peer-1")
        time.sleep(0.01)
        r2 = engine.start_round(peer_id="peer-1")

        assert r1.round_id != r2.round_id


# ─── Compare Inventories ───────────────────────────────────────────────────


class TestCompareInventories:

    def test_compare_inventories_empty(self) -> None:
        store = ImmutableObjectStore()
        engine = AntiEntropyEngine(store)

        local_bf = BloomFilter(estimated_elements=100)
        remote_bf = BloomFilter(estimated_elements=100)

        local_missing, remote_missing = engine.compare_inventories(
            local_bloom=local_bf,
            remote_bloom=remote_bf,
        )

        assert local_missing == []
        assert remote_missing == []

    def test_compare_inventories(self) -> None:
        store = _store_with_objects(count=3)
        engine = AntiEntropyEngine(store)

        local_bf = BloomFilter(estimated_elements=100)
        for oid in store.all_ids():
            local_bf.add(oid)

        # Remote has fewer objects
        remote_bf = BloomFilter(estimated_elements=100)
        remote_bf.add("obj-0")

        local_missing, remote_missing = engine.compare_inventories(
            local_bloom=local_bf,
            remote_bloom=remote_bf,
        )

        # Remote is missing obj-1 and obj-2
        assert len(remote_missing) >= 2
        assert local_missing == []

    def test_compare_inventories_with_objects(self) -> None:
        store = _store_with_objects(count=5)
        engine = AntiEntropyEngine(store)

        local_bf = BloomFilter(estimated_elements=100)
        for oid in store.all_ids():
            local_bf.add(oid)

        # Remote has no objects
        remote_bf = BloomFilter(estimated_elements=100)

        local_missing, remote_missing = engine.compare_inventories(
            local_bloom=local_bf,
            remote_bloom=remote_bf,
        )

        # All local objects should be reported as remote-missing
        assert len(remote_missing) == 5

    def test_compare_bloom_discrepancy(self) -> None:
        """Bloom filter discrepancy detection."""
        store = _store_with_objects(count=3)
        engine = AntiEntropyEngine(store)

        local_bf = BloomFilter(estimated_elements=100)
        for oid in store.all_ids():
            local_bf.add(oid)

        # Remote bloom has an extra object
        remote_bf = BloomFilter(estimated_elements=100)
        remote_bf.add("obj-0")
        remote_bf.add("obj-1")
        remote_bf.add("obj-2")
        remote_bf.add("extra-obj")

        local_missing, remote_missing = engine.compare_inventories(
            local_bloom=local_bf,
            remote_bloom=remote_bf,
        )

        # Remote has everything we have, so remote_missing should be empty
        # (bloom filter says remote might have all our objects)
        assert remote_missing == []


# ─── Verify Discrepancies ──────────────────────────────────────────────────


class TestVerifyDiscrepancies:

    def test_verify_discrepancies(self) -> None:
        store = _store_with_objects(count=2)
        engine = AntiEntropyEngine(store)

        invalid = engine.verify_discrepancies(["obj-0", "obj-1", "nonexistent"])

        assert "nonexistent" in invalid
        assert "obj-0" not in invalid
        assert "obj-1" not in invalid

    def test_verify_discrepancies_all_valid(self) -> None:
        store = _store_with_objects(count=3)
        engine = AntiEntropyEngine(store)

        invalid = engine.verify_discrepancies(
            ["obj-0", "obj-1", "obj-2"]
        )

        assert invalid == []

    def test_discrepancies_accumulate(self) -> None:
        """Discrepancies should accumulate across calls."""
        store = _store_with_objects(count=1)
        engine = AntiEntropyEngine(store)

        engine.verify_discrepancies(["nonexistent-1"])
        engine.verify_discrepancies(["nonexistent-2"])

        discrepancies = engine.get_discrepancies()
        assert "nonexistent-1" in discrepancies
        assert "nonexistent-2" in discrepancies


# ─── Repair Object ─────────────────────────────────────────────────────────


class TestRepairObject:

    def test_repair_object_replacement(self) -> None:
        store = _store_with_objects(count=1)
        engine = AntiEntropyEngine(store)

        replacement = _make_envelope(
            object_id="obj-0-repaired",
            payload={"key": "repaired"},
        )
        result = engine.repair_object(
            object_id="obj-0-repaired",
            replacement=replacement,
        )
        assert result is True
        assert store.has("obj-0-repaired")

    def test_repair_replacement_success(self) -> None:
        """Repair with replacement should store the replacement."""
        store = ImmutableObjectStore()
        engine = AntiEntropyEngine(store)

        replacement = _make_envelope(
            object_id="new-obj",
            payload={"restored": True},
        )
        result = engine.repair_object(
            object_id="new-obj",
            replacement=replacement,
        )
        assert result is True
        obj = store.get("new-obj")
        assert obj is not None
        assert obj.payload == {"restored": True}

    def test_repair_object_tombstone(self) -> None:
        store = _store_with_objects(count=1)
        engine = AntiEntropyEngine(store)

        result = engine.repair_object(object_id="obj-0")
        assert result is True
        assert store.has("obj-0") is False

    def test_repair_object_not_found(self) -> None:
        store = _store_with_objects(count=1)
        engine = AntiEntropyEngine(store)

        result = engine.repair_object(object_id="nonexistent")
        assert result is False

    def test_repair_invalid_object(self) -> None:
        """Repairing an invalid object should tombstone it."""
        store = _store_with_objects(count=1)
        engine = AntiEntropyEngine(store)

        # Verify first to populate discrepancies
        engine.verify_discrepancies(["obj-0", "nonexistent"])
        invalid = engine.get_discrepancies()
        assert "nonexistent" in invalid

        # Repair the nonexistent one (should fail)
        result = engine.repair_object(object_id="nonexistent")
        assert result is False

    def test_repair_and_verify(self) -> None:
        """After repair, object should be gone and verification should reflect."""
        store = _store_with_objects(count=1)
        engine = AntiEntropyEngine(store)

        engine.repair_object(object_id="obj-0")
        assert store.has("obj-0") is False

        # Verify the repaired object — should report not_found
        invalid = engine.verify_discrepancies(["obj-0"])
        assert "obj-0" in invalid


# ─── Complete Round ────────────────────────────────────────────────────────


class TestCompleteRound:

    def test_complete_round(self) -> None:
        store = _store_with_objects()
        engine = AntiEntropyEngine(store)

        round_rec = engine.start_round(peer_id="peer-1")

        completed = engine.complete_round(
            round_id=round_rec.round_id,
            objects_compared=10,
            discrepancies_found=2,
            objects_repaired=1,
            status="completed",
        )

        assert completed is not None
        assert completed.status == "completed"
        assert completed.objects_compared == 10
        assert completed.discrepancies_found == 2
        assert completed.objects_repaired == 1
        assert completed.completed_at > 0

    def test_complete_round_not_found(self) -> None:
        store = _store_with_objects()
        engine = AntiEntropyEngine(store)

        completed = engine.complete_round(
            round_id="nonexistent-round",
            objects_compared=0,
            discrepancies_found=0,
            objects_repaired=0,
        )

        assert completed is None

    def test_round_status_failed(self) -> None:
        store = _store_with_objects()
        engine = AntiEntropyEngine(store)

        round_rec = engine.start_round(peer_id="peer-1")

        completed = engine.complete_round(
            round_id=round_rec.round_id,
            objects_compared=5,
            discrepancies_found=0,
            objects_repaired=0,
            status="failed",
        )

        assert completed is not None
        assert completed.status == "failed"

    def test_round_completed_at(self) -> None:
        """completed_at should be after started_at."""
        store = _store_with_objects()
        engine = AntiEntropyEngine(store)

        round_rec = engine.start_round(peer_id="peer-1")
        time.sleep(0.01)
        completed = engine.complete_round(
            round_id=round_rec.round_id,
            objects_compared=1,
            discrepancies_found=0,
            objects_repaired=0,
        )

        assert completed is not None
        assert completed.completed_at >= round_rec.started_at

    def test_complete_round_updates(self) -> None:
        """Complete round should update the stored record."""
        store = _store_with_objects()
        engine = AntiEntropyEngine(store)

        round_rec = engine.start_round(peer_id="peer-1")
        engine.complete_round(
            round_id=round_rec.round_id,
            objects_compared=5,
            discrepancies_found=1,
            objects_repaired=1,
        )

        rounds = engine.get_rounds()
        assert len(rounds) == 1
        assert rounds[0].status == "completed"
        assert rounds[0].objects_compared == 5


# ─── Getters ────────────────────────────────────────────────────────────────


class TestGetters:

    def test_get_rounds(self) -> None:
        store = _store_with_objects()
        engine = AntiEntropyEngine(store)

        engine.start_round(peer_id="peer-1")
        engine.start_round(peer_id="peer-2")

        rounds = engine.get_rounds()
        assert len(rounds) == 2

    def test_get_discrepancies(self) -> None:
        store = _store_with_objects(count=1)
        engine = AntiEntropyEngine(store)

        engine.verify_discrepancies(["nonexistent"])
        discrepancies = engine.get_discrepancies()
        assert "nonexistent" in discrepancies

    def test_clear_discrepancies(self) -> None:
        store = _store_with_objects(count=1)
        engine = AntiEntropyEngine(store)

        engine.verify_discrepancies(["nonexistent"])
        engine.clear_discrepancies()
        assert engine.get_discrepancies() == []


# ─── Integration / Flow Tests ──────────────────────────────────────────────


class TestAntiEntropyIntegration:

    def test_full_round_flow(self) -> None:
        """Complete anti-entropy round: start → compare → verify → repair → complete."""
        store = _store_with_objects(count=3)
        engine = AntiEntropyEngine(store)

        # Start round
        round_rec = engine.start_round(peer_id="peer-1")

        # Build bloom filters
        local_bf = BloomFilter(estimated_elements=100)
        for oid in store.all_ids():
            local_bf.add(oid)

        remote_bf = BloomFilter(estimated_elements=100)

        # Compare
        local_missing, remote_missing = engine.compare_inventories(
            local_bloom=local_bf,
            remote_bloom=remote_bf,
        )

        # Verify discrepancies
        invalid = engine.verify_discrepancies(remote_missing)

        # Repair
        repaired = 0
        for oid in remote_missing:
            if store.has(oid):
                engine.repair_object(object_id=oid)
                repaired += 1

        # Complete
        completed = engine.complete_round(
            round_id=round_rec.round_id,
            objects_compared=len(remote_missing),
            discrepancies_found=len(invalid),
            objects_repaired=repaired,
            status="completed",
        )

        assert completed is not None
        assert completed.status == "completed"

    def test_multiple_rounds(self) -> None:
        """Multiple anti-entropy rounds with different peers."""
        store = _store_with_objects(count=3)
        engine = AntiEntropyEngine(store)

        r1 = engine.start_round(peer_id="peer-1")
        r2 = engine.start_round(peer_id="peer-2")

        engine.complete_round(
            round_id=r1.round_id,
            objects_compared=3,
            discrepancies_found=0,
            objects_repaired=0,
        )
        engine.complete_round(
            round_id=r2.round_id,
            objects_compared=3,
            discrepancies_found=1,
            objects_repaired=1,
        )

        rounds = engine.get_rounds()
        assert len(rounds) == 2
        assert rounds[0].peer_id == "peer-1"
        assert rounds[1].peer_id == "peer-2"

    def test_multiple_peers_rounds(self) -> None:
        """Each peer gets its own round."""
        store = _store_with_objects(count=2)
        engine = AntiEntropyEngine(store)

        peers = ["peer-a", "peer-b", "peer-c"]
        rounds = []
        for peer in peers:
            r = engine.start_round(peer_id=peer)
            rounds.append(r)

        assert len(rounds) == 3
        peer_ids = {r.peer_id for r in rounds}
        assert peer_ids == {"peer-a", "peer-b", "peer-c"}

    def test_anti_entropy_integration(self) -> None:
        """End-to-end: store objects, run anti-entropy, verify consistency."""
        store = _store_with_objects(count=5)
        engine = AntiEntropyEngine(store)

        # All objects should verify clean initially
        round_rec = engine.start_round(peer_id="self-check")

        local_bf = BloomFilter(estimated_elements=100)
        for oid in store.all_ids():
            local_bf.add(oid)

        # Compare against identical bloom (no discrepancies expected)
        _, remote_missing = engine.compare_inventories(
            local_bloom=local_bf,
            remote_bloom=local_bf,
        )

        assert remote_missing == []

        invalid = engine.verify_discrepancies(store.all_ids())
        assert invalid == []

        completed = engine.complete_round(
            round_id=round_rec.round_id,
            objects_compared=5,
            discrepancies_found=0,
            objects_repaired=0,
        )
        assert completed.status == "completed"
