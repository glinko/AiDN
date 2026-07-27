"""M7-S6: Snapshot sync — RFC-0047 §26."""

from __future__ import annotations

import pytest

from aidn_hypervisor.consensus.snapshot import (
    SnapshotConsumer,
    SnapshotFormat,
    SnapshotMetadata,
    SnapshotProducer,
)

# ── SnapshotMetadata ────────────────────────────────────────────────


def test_snapshot_metadata_creation() -> None:
    m = SnapshotMetadata(
        height=100,
        format=SnapshotFormat.JSON,
        chunks=1,
        hash="abc",
        timestamp=1700000000,
    )
    assert m.height == 100
    assert m.format == SnapshotFormat.JSON
    assert m.chunks == 1


def test_snapshot_metadata_frozen() -> None:
    m = SnapshotMetadata(
        height=100,
        format=SnapshotFormat.JSON,
        chunks=1,
        hash="abc",
        timestamp=1700000000,
    )
    with pytest.raises(Exception):
        m.height = 200  # type: ignore


def test_snapshot_app_version() -> None:
    m = SnapshotMetadata(
        height=100,
        format=SnapshotFormat.JSON,
        chunks=1,
        hash="abc",
        timestamp=1700000000,
    )
    assert m.app_version == "1.0.0"


def test_snapshot_chunk_count() -> None:
    m = SnapshotMetadata(
        height=100,
        format=SnapshotFormat.JSON,
        chunks=3,
        hash="abc",
        timestamp=1700000000,
    )
    assert m.chunks == 3


# ── SnapshotProducer ────────────────────────────────────────────────


def test_snapshot_producer_create() -> None:
    producer = SnapshotProducer()
    meta, payload = producer.create_snapshot(
        height=50,
        state_data={"wallets": {"A": 100}},
    )
    assert meta.height == 50
    assert len(payload) > 0


def test_snapshot_json_format() -> None:
    producer = SnapshotProducer()
    meta, payload = producer.create_snapshot(
        height=10,
        state_data={"x": 1},
        format=SnapshotFormat.JSON,
    )
    assert meta.format == SnapshotFormat.JSON
    import json
    data = json.loads(payload)
    assert data["x"] == 1


def test_snapshot_multiple() -> None:
    producer = SnapshotProducer()
    producer.create_snapshot(height=10, state_data={"a": 1})
    producer.create_snapshot(height=20, state_data={"b": 2})
    snaps = producer.get_snapshots()
    assert len(snaps) == 2
    assert snaps[0].height == 10
    assert snaps[1].height == 20


def test_snapshot_producer_snapshots_list() -> None:
    producer = SnapshotProducer()
    assert producer.get_snapshots() == []


# ── SnapshotConsumer ────────────────────────────────────────────────


def test_snapshot_consumer_validate() -> None:
    producer = SnapshotProducer()
    meta, payload = producer.create_snapshot(
        height=10,
        state_data={"a": 1},
    )
    consumer = SnapshotConsumer()
    assert consumer.validate_snapshot(meta, payload) is True


def test_snapshot_consumer_validate_invalid() -> None:
    producer = SnapshotProducer()
    meta, _ = producer.create_snapshot(
        height=10,
        state_data={"a": 1},
    )
    consumer = SnapshotConsumer()
    # Tamper with payload
    bad_payload = b"not the real payload"
    assert consumer.validate_snapshot(meta, bad_payload) is False


def test_snapshot_consumer_restore() -> None:
    producer = SnapshotProducer()
    meta, payload = producer.create_snapshot(
        height=30,
        state_data={"wallets": {"A": 500, "B": 200}},
    )
    consumer = SnapshotConsumer()
    state = consumer.restore_snapshot(meta, payload)
    assert state is not None
    assert state["wallets"]["A"] == 500


def test_snapshot_consumer_restore_invalid() -> None:
    producer = SnapshotProducer()
    meta, _ = producer.create_snapshot(
        height=10,
        state_data={"a": 1},
    )
    consumer = SnapshotConsumer()
    result = consumer.restore_snapshot(meta, b"bad data")
    assert result is None


def test_snapshot_restore_returns_state() -> None:
    producer = SnapshotProducer()
    state_data = {"key": "value", "count": 42}
    meta, payload = producer.create_snapshot(height=1, state_data=state_data)
    consumer = SnapshotConsumer()
    restored = consumer.restore_snapshot(meta, payload)
    assert restored == state_data


def test_snapshot_consumer_restored_list() -> None:
    producer = SnapshotProducer()
    meta1, pay1 = producer.create_snapshot(height=1, state_data={"a": 1})
    meta2, pay2 = producer.create_snapshot(height=2, state_data={"b": 2})
    consumer = SnapshotConsumer()
    consumer.restore_snapshot(meta1, pay1)
    consumer.restore_snapshot(meta2, pay2)
    restored = consumer.get_restored()
    assert len(restored) == 2


# ── Hash integrity ──────────────────────────────────────────────────


def test_snapshot_hash_integrity() -> None:
    producer = SnapshotProducer()
    meta, payload = producer.create_snapshot(
        height=5,
        state_data={"test": "data"},
    )
    import hashlib
    expected = hashlib.sha256(payload).hexdigest()
    assert meta.hash == expected
