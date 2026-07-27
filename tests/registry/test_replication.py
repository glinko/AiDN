"""Tests for registry/replication — Replication Engine (RFC-0061 §§28-31)."""

from __future__ import annotations

from aidn_hypervisor.registry import ImmutableObjectStore, RegistryObjectEnvelope
from aidn_hypervisor.registry.replication import (
    ReplicationEngine,
    TransferProgress,
    TransferState,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_envelope(
    object_id: str | None = None,
    object_type: str = "test",
    payload: dict | None = None,
    created_epoch: int | None = None,
) -> RegistryObjectEnvelope:
    return RegistryObjectEnvelope.create(
        object_type=object_type,
        payload=payload or {"data": "test"},
        object_id=object_id,
        created_epoch=created_epoch,
    )


def _make_store() -> ImmutableObjectStore:
    return ImmutableObjectStore()


def _make_engine(store: ImmutableObjectStore | None = None) -> ReplicationEngine:
    return ReplicationEngine(store or _make_store())


def _receive_all_chunks(engine: ReplicationEngine, *, object_id: str, total_chunks: int) -> None:
    for chunk_index in range(total_chunks):
        assert (
            engine.receive_chunk(
                object_id=object_id,
                chunk_index=chunk_index,
                chunk_data=f"chunk-{chunk_index}".encode(),
            )
            is not None
        )


# ---------------------------------------------------------------------------
# TransferState enum
# ---------------------------------------------------------------------------


def test_transfer_state_enum():
    """TransferState has all expected values."""
    assert TransferState.PENDING == "pending"
    assert TransferState.IN_PROGRESS == "in_progress"
    assert TransferState.COMPLETED == "completed"
    assert TransferState.FAILED == "failed"
    assert TransferState.RESUMED == "resumed"


# ---------------------------------------------------------------------------
# TransferProgress model
# ---------------------------------------------------------------------------


def test_transfer_progress_model():
    """TransferProgress creates with defaults."""
    tp = TransferProgress(object_id="obj-1")
    assert tp.object_id == "obj-1"
    assert tp.state == TransferState.PENDING
    assert tp.chunks_total == 0
    assert tp.chunks_received == 0
    assert tp.bytes_received == 0
    assert tp.error is None


# ---------------------------------------------------------------------------
# ReplicationEngine init
# ---------------------------------------------------------------------------


def test_replication_engine_init():
    """Engine initializes with empty state."""
    store = _make_store()
    engine = _make_engine(store)
    assert engine.active_transfers == 0
    assert engine.get_transfer("nonexistent") is None
    assert engine.get_completed_transfers() == []
    assert engine.get_failed_transfers() == []


# ---------------------------------------------------------------------------
# §28 — Single object retrieval
# ---------------------------------------------------------------------------


def test_retrieve_single():
    """Retrieve an existing object."""
    store = _make_store()
    env = _make_envelope(object_id="obj-1")
    store.put(env)

    engine = _make_engine(store)
    result = engine.retrieve_single(object_id="obj-1", source_peer_id="peer-a")
    assert result is not None
    assert result.object_id == "obj-1"


def test_retrieve_single_missing():
    """Retrieve a non-existent object returns None."""
    engine = _make_engine()
    result = engine.retrieve_single(object_id="no-such-object")
    assert result is None


# ---------------------------------------------------------------------------
# §29 — Range retrieval
# ---------------------------------------------------------------------------


def test_retrieve_range():
    """Retrieve objects across epoch range."""
    store = _make_store()
    store.put(_make_envelope(object_id="e1", created_epoch=5))
    store.put(_make_envelope(object_id="e2", created_epoch=5))
    store.put(_make_envelope(object_id="e3", created_epoch=6))
    store.put(_make_envelope(object_id="e4", created_epoch=7))

    engine = _make_engine(store)
    results = engine.retrieve_range(start_epoch=5, end_epoch=6)
    assert len(results) == 3
    ids = {r.object_id for r in results}
    assert ids == {"e1", "e2", "e3"}


def test_retrieve_range_single_epoch():
    """Retrieve objects for a single epoch."""
    store = _make_store()
    store.put(_make_envelope(object_id="e1", created_epoch=10))
    store.put(_make_envelope(object_id="e2", created_epoch=10))
    store.put(_make_envelope(object_id="e3", created_epoch=11))

    engine = _make_engine(store)
    results = engine.retrieve_range(start_epoch=10, end_epoch=10)
    assert len(results) == 2
    ids = {r.object_id for r in results}
    assert ids == {"e1", "e2"}


def test_retrieve_range_multi_epoch():
    """Retrieve objects spanning multiple epochs."""
    store = _make_store()
    store.put(_make_envelope(object_id="e1", created_epoch=1))
    store.put(_make_envelope(object_id="e2", created_epoch=2))
    store.put(_make_envelope(object_id="e3", created_epoch=3))

    engine = _make_engine(store)
    results = engine.retrieve_range(start_epoch=1, end_epoch=3)
    assert len(results) == 3


def test_retrieve_range_empty():
    """Retrieve range with no objects returns empty list."""
    engine = _make_engine()
    results = engine.retrieve_range(start_epoch=1, end_epoch=10)
    assert results == []


# ---------------------------------------------------------------------------
# §30 — Chunked transfer
# ---------------------------------------------------------------------------


def test_start_chunked_transfer():
    """Start a chunked transfer."""
    engine = _make_engine()
    progress = engine.start_chunked_transfer(
        object_id="big-obj",
        total_chunks=5,
        content_size=10000,
    )
    assert progress.object_id == "big-obj"
    assert progress.state == TransferState.IN_PROGRESS
    assert progress.chunks_total == 5
    assert progress.chunks_received == 0


def test_receive_chunk():
    """Receive individual chunks."""
    engine = _make_engine()
    engine.start_chunked_transfer(object_id="obj-1", total_chunks=3)

    p = engine.receive_chunk(
        object_id="obj-1",
        chunk_index=0,
        chunk_data=b"chunk0-data",
    )
    assert p is not None
    assert p.chunks_received == 1
    assert p.bytes_received == 11  # len("chunk0-data")


def test_receive_chunk_requires_verified_envelope_to_complete():
    """Chunks alone do not complete a transfer before envelope verification."""
    engine = _make_engine()
    engine.start_chunked_transfer(object_id="obj-1", total_chunks=2)

    engine.receive_chunk(object_id="obj-1", chunk_index=0, chunk_data=b"aa")
    p = engine.receive_chunk(object_id="obj-1", chunk_index=1, chunk_data=b"bb")

    assert p is not None
    assert p.state == TransferState.IN_PROGRESS
    assert p.chunks_received == 2
    assert p.completed_at is None


def test_receive_chunk_unknown_object():
    """Receiving chunk for unknown object returns None."""
    engine = _make_engine()
    p = engine.receive_chunk(
        object_id="no-such-obj",
        chunk_index=0,
        chunk_data=b"data",
    )
    assert p is None


def test_chunk_data_bytes():
    """Chunk data is tracked as bytes."""
    engine = _make_engine()
    engine.start_chunked_transfer(object_id="obj-1", total_chunks=1)

    data = b"x" * 100
    p = engine.receive_chunk(object_id="obj-1", chunk_index=0, chunk_data=data)
    assert p is not None
    assert p.bytes_received == 100


# ---------------------------------------------------------------------------
# Complete transfer
# ---------------------------------------------------------------------------


def test_complete_transfer_success():
    """Completing a transfer stores the object."""
    store = _make_store()
    engine = _make_engine(store)
    engine.start_chunked_transfer(object_id="obj-1", total_chunks=2)
    _receive_all_chunks(engine, object_id="obj-1", total_chunks=2)

    env = _make_envelope(object_id="obj-1")
    ok = engine.complete_transfer(object_id="obj-1", envelope=env)
    assert ok is True
    assert store.has("obj-1")


def test_complete_transfer_fail():
    """Completing a transfer fails if object already exists."""
    store = _make_store()
    env = _make_envelope(object_id="obj-1")
    store.put(env)

    engine = _make_engine(store)
    engine.start_chunked_transfer(object_id="obj-1", total_chunks=1)
    _receive_all_chunks(engine, object_id="obj-1", total_chunks=1)

    ok = engine.complete_transfer(object_id="obj-1", envelope=env)
    assert ok is False

    transfer = engine.get_transfer("obj-1")
    assert transfer is not None
    assert transfer.state == TransferState.FAILED
    assert transfer.error == "storage_failed"


def test_complete_transfer_not_in_transfers():
    """Completing a transfer for unknown object returns False."""
    engine = _make_engine()
    env = _make_envelope(object_id="obj-1")
    ok = engine.complete_transfer(object_id="obj-1", envelope=env)
    assert ok is False


def test_complete_transfer_rejects_incomplete_chunks():
    engine = _make_engine()
    engine.start_chunked_transfer(object_id="obj-1", total_chunks=2)
    engine.receive_chunk(object_id="obj-1", chunk_index=0, chunk_data=b"first")
    envelope = _make_envelope(object_id="obj-1")

    assert engine.complete_transfer(object_id="obj-1", envelope=envelope) is False
    transfer = engine.get_transfer("obj-1")
    assert transfer is not None
    assert transfer.error == "transfer_incomplete"


def test_complete_transfer_rejects_object_id_mismatch():
    store = _make_store()
    engine = _make_engine(store)
    engine.start_chunked_transfer(object_id="expected", total_chunks=1)
    _receive_all_chunks(engine, object_id="expected", total_chunks=1)

    assert (
        engine.complete_transfer(
            object_id="expected",
            envelope=_make_envelope(object_id="different"),
        )
        is False
    )
    assert store.has("different") is False
    transfer = engine.get_transfer("expected")
    assert transfer is not None
    assert transfer.error == "object_id_mismatch"


def test_duplicate_chunk_is_idempotent_and_invalid_index_fails():
    engine = _make_engine()
    engine.start_chunked_transfer(object_id="obj-1", total_chunks=2)
    first = engine.receive_chunk(object_id="obj-1", chunk_index=0, chunk_data=b"one")
    duplicate = engine.receive_chunk(object_id="obj-1", chunk_index=0, chunk_data=b"one")
    assert first is not None
    assert duplicate is not None
    assert duplicate.chunks_received == 1
    assert duplicate.bytes_received == 3

    invalid = engine.receive_chunk(object_id="obj-1", chunk_index=2, chunk_data=b"bad")
    assert invalid is not None
    assert invalid.state == TransferState.FAILED
    assert invalid.error == "chunk_index_invalid"


# ---------------------------------------------------------------------------
# §31 — Transfer resumption
# ---------------------------------------------------------------------------


def test_resume_transfer():
    """Resume a failed transfer."""
    store = _make_store()
    engine = _make_engine(store)
    engine.start_chunked_transfer(object_id="obj-1", total_chunks=3)
    _receive_all_chunks(engine, object_id="obj-1", total_chunks=3)

    env = _make_envelope(object_id="obj-1")
    store.put(env)  # pre-exists to force failure
    engine.complete_transfer(object_id="obj-1", envelope=env)

    # Now resume
    resumed = engine.resume_transfer(object_id="obj-1", from_chunk=1)
    assert resumed is not None
    assert resumed.state == TransferState.IN_PROGRESS
    assert resumed.chunks_received == 1
    assert resumed.error is None


def test_resume_failed_transfer():
    """Resume specifically sets state from FAILED to IN_PROGRESS."""
    store = _make_store()
    engine = _make_engine(store)
    engine.start_chunked_transfer(object_id="obj-1", total_chunks=2)
    _receive_all_chunks(engine, object_id="obj-1", total_chunks=2)
    # Force failure by storing duplicate
    env = _make_envelope(object_id="obj-1")
    store.put(env)
    engine.complete_transfer(object_id="obj-1", envelope=env)

    transfer = engine.get_transfer("obj-1")
    assert transfer.state == TransferState.FAILED

    resumed = engine.resume_transfer(object_id="obj-1", from_chunk=0)
    assert resumed is not None
    assert resumed.state == TransferState.IN_PROGRESS


def test_resume_transfer_new():
    """Resuming a non-existent transfer returns None."""
    engine = _make_engine()
    resumed = engine.resume_transfer(object_id="no-such-obj")
    assert resumed is None


# ---------------------------------------------------------------------------
# Transfer queries
# ---------------------------------------------------------------------------


def test_get_transfer():
    """Get current transfer by object id."""
    engine = _make_engine()
    engine.start_chunked_transfer(object_id="obj-1", total_chunks=4)

    t = engine.get_transfer("obj-1")
    assert t is not None
    assert t.object_id == "obj-1"
    assert t.chunks_total == 4


def test_get_completed_transfers():
    """Query completed transfers from log."""
    store = _make_store()
    engine = _make_engine(store)

    engine.start_chunked_transfer(object_id="obj-1", total_chunks=1)
    _receive_all_chunks(engine, object_id="obj-1", total_chunks=1)
    env1 = _make_envelope(object_id="obj-1")
    engine.complete_transfer(object_id="obj-1", envelope=env1)

    completed = engine.get_completed_transfers()
    assert len(completed) >= 1
    assert any(t.object_id == "obj-1" for t in completed)


def test_get_failed_transfers():
    """Query failed transfers from log."""
    store = _make_store()
    env = _make_envelope(object_id="obj-1")
    store.put(env)

    engine = _make_engine(store)
    engine.start_chunked_transfer(object_id="obj-1", total_chunks=1)
    _receive_all_chunks(engine, object_id="obj-1", total_chunks=1)
    engine.complete_transfer(object_id="obj-1", envelope=env)

    failed = engine.get_failed_transfers()
    assert len(failed) >= 1
    assert any(t.object_id == "obj-1" for t in failed)


def test_active_transfers_count():
    """Count active (IN_PROGRESS) transfers."""
    engine = _make_engine()
    engine.start_chunked_transfer(object_id="a", total_chunks=3)
    engine.start_chunked_transfer(object_id="b", total_chunks=2)
    engine.start_chunked_transfer(object_id="c", total_chunks=1)

    assert engine.active_transfers == 3

    # Complete one
    engine.receive_chunk(object_id="c", chunk_index=0, chunk_data=b"x")
    assert engine.active_transfers == 3


# ---------------------------------------------------------------------------
# Transfer error state
# ---------------------------------------------------------------------------


def test_transfer_error_state():
    """Failed transfer records error message."""
    store = _make_store()
    env = _make_envelope(object_id="obj-1")
    store.put(env)

    engine = _make_engine(store)
    engine.start_chunked_transfer(object_id="obj-1", total_chunks=1)
    _receive_all_chunks(engine, object_id="obj-1", total_chunks=1)
    engine.complete_transfer(object_id="obj-1", envelope=env)

    t = engine.get_transfer("obj-1")
    assert t.state == TransferState.FAILED
    assert t.error == "storage_failed"


# ---------------------------------------------------------------------------
# Full chunked transfer flow
# ---------------------------------------------------------------------------


def test_chunked_transfer_full_flow():
    """End-to-end chunked transfer: start → chunks → complete."""
    store = _make_store()
    engine = _make_engine(store)

    # Start
    engine.start_chunked_transfer(object_id="big-obj", total_chunks=3)

    # Receive chunks
    engine.receive_chunk(object_id="big-obj", chunk_index=0, chunk_data=b"aaa")
    engine.receive_chunk(object_id="big-obj", chunk_index=1, chunk_data=b"bbb")
    engine.receive_chunk(object_id="big-obj", chunk_index=2, chunk_data=b"ccc")

    # Chunks are only progress; the envelope is the final integrity proof.
    t = engine.get_transfer("big-obj")
    assert t.state == TransferState.IN_PROGRESS
    assert t.chunks_received == 3
    assert t.bytes_received == 9

    # Complete by storing
    env = _make_envelope(object_id="big-obj")
    ok = engine.complete_transfer(object_id="big-obj", envelope=env)
    assert ok is True
    assert store.has("big-obj")


# ---------------------------------------------------------------------------
# Multiple parallel transfers
# ---------------------------------------------------------------------------


def test_multiple_transfers_parallel():
    """Multiple transfers can be tracked simultaneously."""
    engine = _make_engine()

    engine.start_chunked_transfer(object_id="obj-a", total_chunks=5)
    engine.start_chunked_transfer(object_id="obj-b", total_chunks=3)
    engine.start_chunked_transfer(object_id="obj-c", total_chunks=2)

    assert engine.active_transfers == 3

    # Progress on obj-a
    engine.receive_chunk(object_id="obj-a", chunk_index=0, chunk_data=b"data")
    a = engine.get_transfer("obj-a")
    assert a.chunks_received == 1

    # obj-b untouched
    b = engine.get_transfer("obj-b")
    assert b.chunks_received == 0


# ---------------------------------------------------------------------------
# Transfer log
# ---------------------------------------------------------------------------


def test_transfer_log():
    """Completed and failed transfers are logged."""
    store = _make_store()
    engine = _make_engine(store)

    # Successful transfer
    engine.start_chunked_transfer(object_id="ok-1", total_chunks=1)
    _receive_all_chunks(engine, object_id="ok-1", total_chunks=1)
    env_ok = _make_envelope(object_id="ok-1")
    engine.complete_transfer(object_id="ok-1", envelope=env_ok)

    # Failed transfer
    env_fail = _make_envelope(object_id="fail-1")
    store.put(env_fail)
    engine.start_chunked_transfer(object_id="fail-1", total_chunks=1)
    _receive_all_chunks(engine, object_id="fail-1", total_chunks=1)
    engine.complete_transfer(object_id="fail-1", envelope=env_fail)

    completed = engine.get_completed_transfers()
    failed = engine.get_failed_transfers()

    assert len(completed) >= 1
    assert len(failed) >= 1
