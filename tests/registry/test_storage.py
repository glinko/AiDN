"""Tests for registry/storage — Immutable Object Store (RFC-0061 §4)."""

from __future__ import annotations

import pytest

from aidn_hypervisor.registry import ImmutableObjectStore, RegistryObjectEnvelope


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_envelope(
    obj_type: str = "test",
    payload: dict | None = None,
    object_id: str | None = None,
    created_epoch: int | None = None,
    created_block_height: int | None = None,
) -> RegistryObjectEnvelope:
    return RegistryObjectEnvelope.create(
        object_type=obj_type,
        payload=payload or {"key": "value"},
        object_id=object_id,
        created_epoch=created_epoch,
        created_block_height=created_block_height,
    )


# ---------------------------------------------------------------------------
# test_put_object
# ---------------------------------------------------------------------------

def test_put_object():
    store = ImmutableObjectStore()
    env = _make_envelope(object_id="obj-1")
    assert store.put(env) is True
    assert store.has("obj-1")


# ---------------------------------------------------------------------------
# test_get_object
# ---------------------------------------------------------------------------

def test_get_object():
    store = ImmutableObjectStore()
    env = _make_envelope(object_id="obj-1")
    store.put(env)
    retrieved = store.get("obj-1")
    assert retrieved is not None
    assert retrieved.object_id == "obj-1"


# ---------------------------------------------------------------------------
# test_get_missing
# ---------------------------------------------------------------------------

def test_get_missing():
    store = ImmutableObjectStore()
    assert store.get("nonexistent") is None


# ---------------------------------------------------------------------------
# test_put_duplicate_returns_false
# ---------------------------------------------------------------------------

def test_put_duplicate_returns_false():
    store = ImmutableObjectStore()
    env = _make_envelope(object_id="obj-1")
    assert store.put(env) is True
    assert store.put(env) is False  # duplicate


# ---------------------------------------------------------------------------
# test_put_conflict_returns_false
# ---------------------------------------------------------------------------

def test_put_conflict_returns_false():
    store = ImmutableObjectStore()
    env1 = _make_envelope(object_id="obj-1", payload={"a": 1})
    env2 = _make_envelope(object_id="obj-1", payload={"a": 2})
    assert store.put(env1) is True
    assert store.put(env2) is False  # same id, different hash


# ---------------------------------------------------------------------------
# test_put_after_tombstone_returns_false
# ---------------------------------------------------------------------------

def test_put_after_tombstone_returns_false():
    store = ImmutableObjectStore()
    env = _make_envelope(object_id="obj-1")
    store.put(env)
    store.tombstone("obj-1")
    assert store.put(env) is False  # tombstoned


# ---------------------------------------------------------------------------
# test_list_by_type
# ---------------------------------------------------------------------------

def test_list_by_type():
    store = ImmutableObjectStore()
    store.put(_make_envelope(obj_type="type_a", object_id="a1"))
    store.put(_make_envelope(obj_type="type_a", object_id="a2"))
    store.put(_make_envelope(obj_type="type_b", object_id="b1"))
    results = store.list_by_type("type_a")
    assert len(results) == 2
    ids = {r.object_id for r in results}
    assert ids == {"a1", "a2"}


# ---------------------------------------------------------------------------
# test_list_by_epoch
# ---------------------------------------------------------------------------

def test_list_by_epoch():
    store = ImmutableObjectStore()
    store.put(_make_envelope(object_id="e1", created_epoch=10))
    store.put(_make_envelope(object_id="e2", created_epoch=10))
    store.put(_make_envelope(object_id="e3", created_epoch=11))
    results = store.list_by_epoch(10)
    assert len(results) == 2
    ids = {r.object_id for r in results}
    assert ids == {"e1", "e2"}


# ---------------------------------------------------------------------------
# test_list_with_limit
# ---------------------------------------------------------------------------

def test_list_with_limit():
    store = ImmutableObjectStore()
    store.put(_make_envelope(obj_type="type_a", object_id="a1"))
    store.put(_make_envelope(obj_type="type_a", object_id="a2"))
    store.put(_make_envelope(obj_type="type_a", object_id="a3"))
    results = store.list_by_type("type_a", limit=2)
    assert len(results) == 2


# ---------------------------------------------------------------------------
# test_has_existing
# ---------------------------------------------------------------------------

def test_has_existing():
    store = ImmutableObjectStore()
    store.put(_make_envelope(object_id="obj-1"))
    assert store.has("obj-1") is True


# ---------------------------------------------------------------------------
# test_has_missing
# ---------------------------------------------------------------------------

def test_has_missing():
    store = ImmutableObjectStore()
    assert store.has("nonexistent") is False


# ---------------------------------------------------------------------------
# test_has_tombstoned
# ---------------------------------------------------------------------------

def test_has_tombstoned():
    store = ImmutableObjectStore()
    store.put(_make_envelope(object_id="obj-1"))
    store.tombstone("obj-1")
    assert store.has("obj-1") is False


# ---------------------------------------------------------------------------
# test_tombstone
# ---------------------------------------------------------------------------

def test_tombstone():
    store = ImmutableObjectStore()
    store.put(_make_envelope(object_id="obj-1"))
    assert store.tombstone("obj-1") is True
    assert store.get("obj-1") is None


# ---------------------------------------------------------------------------
# test_tombstone_nonexistent
# ---------------------------------------------------------------------------

def test_tombstone_nonexistent():
    store = ImmutableObjectStore()
    assert store.tombstone("nonexistent") is False


# ---------------------------------------------------------------------------
# test_delete
# ---------------------------------------------------------------------------

def test_delete():
    store = ImmutableObjectStore()
    store.put(_make_envelope(object_id="obj-1"))
    assert store.delete("obj-1") is True
    assert store.get("obj-1") is None
    assert "obj-1" not in store.all_ids()


# ---------------------------------------------------------------------------
# test_delete_nonexistent
# ---------------------------------------------------------------------------

def test_delete_nonexistent():
    store = ImmutableObjectStore()
    assert store.delete("nonexistent") is False


# ---------------------------------------------------------------------------
# test_all_ids
# ---------------------------------------------------------------------------

def test_all_ids():
    store = ImmutableObjectStore()
    store.put(_make_envelope(object_id="a"))
    store.put(_make_envelope(object_id="b"))
    store.put(_make_envelope(object_id="c"))
    assert store.all_ids() == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# test_all_ids_excludes_tombstoned
# ---------------------------------------------------------------------------

def test_all_ids_excludes_tombstoned():
    store = ImmutableObjectStore()
    store.put(_make_envelope(object_id="a"))
    store.put(_make_envelope(object_id="b"))
    store.put(_make_envelope(object_id="c"))
    store.tombstone("b")
    assert store.all_ids() == ["a", "c"]


# ---------------------------------------------------------------------------
# test_stats_empty
# ---------------------------------------------------------------------------

def test_stats_empty():
    store = ImmutableObjectStore()
    s = store.stats()
    assert s.total_objects == 0
    assert s.total_bytes == 0
    assert s.objects_by_type == {}
    assert s.earliest_epoch is None
    assert s.latest_epoch is None


# ---------------------------------------------------------------------------
# test_stats_with_objects
# ---------------------------------------------------------------------------

def test_stats_with_objects():
    store = ImmutableObjectStore()
    store.put(_make_envelope(object_id="o1", created_epoch=5))
    store.put(_make_envelope(object_id="o2", created_epoch=10))
    s = store.stats()
    assert s.total_objects == 2
    assert s.total_bytes > 0
    assert s.earliest_epoch == 5
    assert s.latest_epoch == 10


# ---------------------------------------------------------------------------
# test_stats_by_type
# ---------------------------------------------------------------------------

def test_stats_by_type():
    store = ImmutableObjectStore()
    store.put(_make_envelope(obj_type="A", object_id="a1"))
    store.put(_make_envelope(obj_type="A", object_id="a2"))
    store.put(_make_envelope(obj_type="B", object_id="b1"))
    s = store.stats()
    assert s.objects_by_type == {"A": 2, "B": 1}


# ---------------------------------------------------------------------------
# test_stats_epoch_range
# ---------------------------------------------------------------------------

def test_stats_epoch_range():
    store = ImmutableObjectStore()
    store.put(_make_envelope(object_id="o1", created_epoch=1))
    store.put(_make_envelope(object_id="o2", created_epoch=5))
    store.put(_make_envelope(object_id="o3", created_epoch=3))
    s = store.stats()
    assert s.earliest_epoch == 1
    assert s.latest_epoch == 5


# ---------------------------------------------------------------------------
# test_snapshot
# ---------------------------------------------------------------------------

def test_snapshot():
    store = ImmutableObjectStore()
    e1 = _make_envelope(object_id="o1")
    e2 = _make_envelope(object_id="o2")
    store.put(e1)
    store.put(e2)
    snap = store.snapshot()
    assert len(snap) == 2
    assert snap["o1"].object_id == "o1"
    assert snap["o2"].object_id == "o2"


# ---------------------------------------------------------------------------
# test_get_many
# ---------------------------------------------------------------------------

def test_get_many():
    store = ImmutableObjectStore()
    store.put(_make_envelope(object_id="a"))
    store.put(_make_envelope(object_id="b"))
    store.put(_make_envelope(object_id="c"))
    results = store.get_many(["a", "c", "nonexistent"])
    assert len(results) == 2
    ids = [r.object_id for r in results]
    assert ids == ["a", "c"]


# ---------------------------------------------------------------------------
# test_insertion_order_preserved
# ---------------------------------------------------------------------------

def test_insertion_order_preserved():
    store = ImmutableObjectStore()
    ids = ["first", "second", "third", "fourth"]
    for oid in ids:
        store.put(_make_envelope(object_id=oid))
    assert store.all_ids() == ids
