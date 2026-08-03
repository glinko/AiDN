"""Tests for registry/manifest — Segment Manifests + Inventory Roots (RFC-0061 §21-22)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from aidn_hypervisor.registry import (
    InventoryRoot,
    RegistryObjectEnvelope,
    SegmentManifest,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_envelope(
    object_id: str,
    payload: dict | None = None,
    created_epoch: int | None = None,
    created_block_height: int | None = None,
    obj_type: str = "test",
) -> RegistryObjectEnvelope:
    return RegistryObjectEnvelope.create(
        object_type=obj_type,
        payload=payload or {"key": "value"},
        object_id=object_id,
        created_epoch=created_epoch,
        created_block_height=created_block_height,
    )


# ---------------------------------------------------------------------------
# test_create_manifest
# ---------------------------------------------------------------------------

def test_create_manifest():
    objs = [
        _make_envelope("o1", created_epoch=1),
        _make_envelope("o2", created_epoch=2),
    ]
    manifest = SegmentManifest.create(
        segment_id="seg-1",
        start_epoch=1,
        end_epoch=2,
        objects=objs,
    )
    assert manifest.segment_id == "seg-1"
    assert manifest.start_epoch == 1
    assert manifest.end_epoch == 2
    assert manifest.object_count == 2
    assert manifest.total_bytes > 0
    assert len(manifest.manifest_hash) == 64


# ---------------------------------------------------------------------------
# test_manifest_deterministic
# ---------------------------------------------------------------------------

def test_manifest_deterministic():
    objs = [
        _make_envelope("o1", created_epoch=1),
        _make_envelope("o2", created_epoch=2),
    ]
    m1 = SegmentManifest.create(
        segment_id="seg-1", start_epoch=1, end_epoch=2, objects=objs,
    )
    m2 = SegmentManifest.create(
        segment_id="seg-1", start_epoch=1, end_epoch=2, objects=objs,
    )
    assert m1.manifest_hash == m2.manifest_hash


# ---------------------------------------------------------------------------
# test_manifest_sorting
# ---------------------------------------------------------------------------

def test_manifest_sorting():
    """Objects should be sorted by epoch → block → id."""
    objs = [
        _make_envelope("o2", created_epoch=2),
        _make_envelope("o1", created_epoch=1),
        _make_envelope("o3", created_epoch=1),
    ]
    manifest = SegmentManifest.create(
        segment_id="seg-1", start_epoch=1, end_epoch=2, objects=objs,
    )
    # o1 and o3 are epoch 1, o2 is epoch 2
    assert manifest.object_ids[0] in ("o1", "o3")
    assert manifest.object_ids[-1] == "o2"


# ---------------------------------------------------------------------------
# test_manifest_verify_valid
# ---------------------------------------------------------------------------

def test_manifest_verify_valid():
    objs = [
        _make_envelope("o1", created_epoch=1),
        _make_envelope("o2", created_epoch=2),
    ]
    manifest = SegmentManifest.create(
        segment_id="seg-1", start_epoch=1, end_epoch=2, objects=objs,
    )
    assert manifest.verify(objs) is True


# ---------------------------------------------------------------------------
# test_manifest_verify_invalid_count
# ---------------------------------------------------------------------------

def test_manifest_verify_invalid_count():
    objs = [
        _make_envelope("o1", created_epoch=1),
        _make_envelope("o2", created_epoch=2),
    ]
    manifest = SegmentManifest.create(
        segment_id="seg-1", start_epoch=1, end_epoch=2, objects=objs,
    )
    # Only provide one object
    assert manifest.verify([objs[0]]) is False


# ---------------------------------------------------------------------------
# test_manifest_verify_invalid_hash
# ---------------------------------------------------------------------------

def test_manifest_verify_invalid_hash():
    objs = [
        _make_envelope("o1", created_epoch=1),
        _make_envelope("o2", created_epoch=2),
    ]
    manifest = SegmentManifest.create(
        segment_id="seg-1", start_epoch=1, end_epoch=2, objects=objs,
    )
    # Provide different objects
    different = [
        _make_envelope("o1", payload={"different": True}, created_epoch=1),
        _make_envelope("o2", created_epoch=2),
    ]
    assert manifest.verify(different) is False


# ---------------------------------------------------------------------------
# test_manifest_empty_objects
# ---------------------------------------------------------------------------

def test_manifest_empty_objects():
    manifest = SegmentManifest.create(
        segment_id="seg-1", start_epoch=1, end_epoch=1, objects=[],
    )
    assert manifest.object_count == 0
    assert manifest.total_bytes == 0
    assert manifest.object_ids == []


# ---------------------------------------------------------------------------
# test_inventory_root_create
# ---------------------------------------------------------------------------

def test_inventory_root_create():
    objs = [_make_envelope("o1", created_epoch=1)]
    manifest = SegmentManifest.create(
        segment_id="seg-1", start_epoch=1, end_epoch=1, objects=objs,
    )
    root = InventoryRoot.create(epoch=1, manifests=[manifest])
    assert root.epoch == 1
    assert len(root.segment_hashes) == 1
    assert root.segment_hashes[0] == manifest.manifest_hash
    assert len(root.root_hash) == 64


# ---------------------------------------------------------------------------
# test_inventory_root_verify_valid
# ---------------------------------------------------------------------------

def test_inventory_root_verify_valid():
    objs = [_make_envelope("o1", created_epoch=1)]
    manifest = SegmentManifest.create(
        segment_id="seg-1", start_epoch=1, end_epoch=1, objects=objs,
    )
    root = InventoryRoot.create(epoch=1, manifests=[manifest])
    assert root.verify([manifest]) is True


# ---------------------------------------------------------------------------
# test_inventory_root_verify_invalid
# ---------------------------------------------------------------------------

def test_inventory_root_verify_invalid():
    objs = [_make_envelope("o1", created_epoch=1)]
    manifest = SegmentManifest.create(
        segment_id="seg-1", start_epoch=1, end_epoch=1, objects=objs,
    )
    root = InventoryRoot.create(epoch=1, manifests=[manifest])
    # Different manifest → should fail
    other_objs = [_make_envelope("o1", payload={"x": 1}, created_epoch=1)]
    other_manifest = SegmentManifest.create(
        segment_id="seg-1", start_epoch=1, end_epoch=1, objects=other_objs,
    )
    assert root.verify([other_manifest]) is False


# ---------------------------------------------------------------------------
# test_inventory_root_deterministic
# ---------------------------------------------------------------------------

def test_inventory_root_deterministic():
    objs = [_make_envelope("o1", created_epoch=1)]
    manifest = SegmentManifest.create(
        segment_id="seg-1", start_epoch=1, end_epoch=1, objects=objs,
    )
    r1 = InventoryRoot.create(epoch=1, manifests=[manifest])
    r2 = InventoryRoot.create(epoch=1, manifests=[manifest])
    assert r1.root_hash == r2.root_hash


# ---------------------------------------------------------------------------
# test_inventory_root_multiple_segments
# ---------------------------------------------------------------------------

def test_inventory_root_multiple_segments():
    objs1 = [_make_envelope("o1", created_epoch=1)]
    objs2 = [_make_envelope("o2", created_epoch=2)]
    m1 = SegmentManifest.create(
        segment_id="seg-1", start_epoch=1, end_epoch=1, objects=objs1,
    )
    m2 = SegmentManifest.create(
        segment_id="seg-2", start_epoch=2, end_epoch=2, objects=objs2,
    )
    root = InventoryRoot.create(epoch=2, manifests=[m1, m2])
    assert len(root.segment_hashes) == 2
    assert root.verify([m1, m2]) is True


# ---------------------------------------------------------------------------
# test_segment_with_blocks
# ---------------------------------------------------------------------------

def test_segment_with_blocks():
    objs = [
        _make_envelope("o1", created_epoch=1, created_block_height=100),
        _make_envelope("o2", created_epoch=1, created_block_height=200),
    ]
    manifest = SegmentManifest.create(
        segment_id="seg-1",
        start_epoch=1,
        end_epoch=1,
        objects=objs,
        start_block=100,
        end_block=200,
    )
    assert manifest.start_block == 100
    assert manifest.end_block == 200
    # o1 (block 100) should come before o2 (block 200)
    assert manifest.object_ids[0] == "o1"
    assert manifest.object_ids[1] == "o2"


# ---------------------------------------------------------------------------
# test_segment_hash_changes_with_order
# ---------------------------------------------------------------------------

def test_segment_hash_changes_with_order():
    """Different payloads → different hash even with same ids."""
    objs_a = [
        _make_envelope("o1", payload={"a": 1}, created_epoch=1),
    ]
    objs_b = [
        _make_envelope("o1", payload={"a": 2}, created_epoch=1),
    ]
    m_a = SegmentManifest.create(
        segment_id="seg-1", start_epoch=1, end_epoch=1, objects=objs_a,
    )
    m_b = SegmentManifest.create(
        segment_id="seg-1", start_epoch=1, end_epoch=1, objects=objs_b,
    )
    assert m_a.content_hash_root != m_b.content_hash_root
    assert m_a.manifest_hash != m_b.manifest_hash


def test_manifest_contains_content_roots_and_stable_identity():
    objects = [
        _make_envelope("o2", payload={"a": 2}, created_epoch=2, created_block_height=20),
        _make_envelope("o1", payload={"a": 1}, created_epoch=1, created_block_height=10),
    ]
    manifest = SegmentManifest.create(
        segment_id="seg-1",
        start_epoch=1,
        end_epoch=2,
        start_block=10,
        end_block=20,
        generation=3,
        objects=objects,
    )

    assert manifest.object_ids == ["o1", "o2"]
    assert len(manifest.object_id_root) == 64
    assert len(manifest.content_hash_root) == 64
    assert manifest.manifest_id.startswith("sha256:")
    assert manifest.verify(objects) is True


def test_manifest_verification_preserves_block_scope():
    objects = [_make_envelope("o1", created_epoch=1, created_block_height=10)]
    manifest = SegmentManifest.create(
        segment_id="seg-1",
        start_epoch=1,
        end_epoch=1,
        start_block=10,
        end_block=10,
        objects=objects,
    )
    altered_scope = manifest.model_copy(update={"end_block": 11})

    assert manifest.verify(objects) is True
    assert altered_scope.verify(objects) is False


# ---------------------------------------------------------------------------
# test_manifest_frozen
# ---------------------------------------------------------------------------

def test_manifest_frozen():
    manifest = SegmentManifest.create(
        segment_id="seg-1", start_epoch=1, end_epoch=1, objects=[],
    )
    with pytest.raises(ValidationError):
        manifest.segment_id = "other"  # type: ignore


# ---------------------------------------------------------------------------
# test_inventory_root_frozen
# ---------------------------------------------------------------------------

def test_inventory_root_frozen():
    root = InventoryRoot.create(epoch=1, manifests=[])
    with pytest.raises(ValidationError):
        root.epoch = 99  # type: ignore


# ---------------------------------------------------------------------------
# test_manifest_object_count
# ---------------------------------------------------------------------------

def test_manifest_object_count():
    objs = [
        _make_envelope("o1", created_epoch=1),
        _make_envelope("o2", created_epoch=1),
        _make_envelope("o3", created_epoch=1),
    ]
    manifest = SegmentManifest.create(
        segment_id="seg-1", start_epoch=1, end_epoch=1, objects=objs,
    )
    assert manifest.object_count == 3


# ---------------------------------------------------------------------------
# test_manifest_total_bytes
# ---------------------------------------------------------------------------

def test_manifest_total_bytes():
    objs = [
        _make_envelope("o1", created_epoch=1),
        _make_envelope("o2", created_epoch=1),
    ]
    manifest = SegmentManifest.create(
        segment_id="seg-1", start_epoch=1, end_epoch=1, objects=objs,
    )
    expected = sum(o.content_size for o in objs)
    assert manifest.total_bytes == expected


# ---------------------------------------------------------------------------
# test_inventory_root_epoch
# ---------------------------------------------------------------------------

def test_inventory_root_epoch():
    root = InventoryRoot.create(epoch=42, manifests=[])
    assert root.epoch == 42


# ---------------------------------------------------------------------------
# test_manifest_segment_id
# ---------------------------------------------------------------------------

def test_manifest_segment_id():
    manifest = SegmentManifest.create(
        segment_id="my-segment", start_epoch=1, end_epoch=1, objects=[],
    )
    assert manifest.segment_id == "my-segment"
