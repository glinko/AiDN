"""Durable local-state and State Sync coverage for the ABCI application."""

from __future__ import annotations

import json

import pytest

from aidn_hypervisor.consensus.abci import AIDNABCIApplication
from aidn_hypervisor.consensus.admission import AdmissionValidator
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.consensus.state_store import ABCIStateStore, ABCIStateStoreError
from aidn_hypervisor.ledger.service import LedgerOperationService


def _app(store: ABCIStateStore | None = None) -> AIDNABCIApplication:
    return AIDNABCIApplication(
        ledger_service=LedgerOperationService(),
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        state_store=store,
    )


def _operation_bytes() -> bytes:
    envelope = LedgerOperationEnvelope(
        operation_type="REGISTRY_UPSERT",
        origin_type="protocol",
        created_at="2030-01-01T00:00:00Z",
        payload={"durable_state": True},
    )
    return json.dumps(envelope.model_dump(mode="json")).encode("utf-8")


def test_finalized_state_survives_application_restart(tmp_path) -> None:
    store = ABCIStateStore(tmp_path / "abci", chunk_size=64)
    application = _app(store)
    transaction = _operation_bytes()

    assert application.check_transaction(transaction).code == "ok"
    result = application.finalize_block(
        block_height=1,
        block_hash=b"a" * 32,
        txs=[transaction],
    )
    assert result.code == "ok"
    expected_hash = application.info().last_block_app_hash

    restored = _app(store)
    assert restored.info().last_block_height == 1
    assert restored.info().last_block_app_hash == expected_hash
    assert restored.commitment_at(1) is not None
    assert len(restored.ledger.snapshot_operations()) == 1


def test_persistence_failure_rolls_back_block_state(tmp_path, monkeypatch) -> None:
    store = ABCIStateStore(tmp_path / "abci")
    application = _app(store)
    monkeypatch.setattr(store, "persist", lambda state: (_ for _ in ()).throw(ABCIStateStoreError("disk full")))

    result = application.finalize_block(
        block_height=1,
        block_hash=b"b" * 32,
        txs=[],
    )

    assert result.code == "internal"
    assert application.info().last_block_height == 0
    assert application.commitment_at(1) is None


def test_hypervisor_checkpoint_failure_restores_durable_abci_snapshot(tmp_path) -> None:
    store = ABCIStateStore(tmp_path / "abci")

    def fail_checkpoint() -> None:
        raise OSError("hypervisor disk full")

    application = AIDNABCIApplication(
        ledger_service=LedgerOperationService(),
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        state_store=store,
        state_checkpoint_callback=fail_checkpoint,
    )
    result = application.finalize_block(
        block_height=1,
        block_hash=b"z" * 32,
        txs=[],
    )

    assert result.code == "internal"
    assert application.info().last_block_height == 0
    durable_snapshot = store.load_current()
    assert durable_snapshot is not None
    assert durable_snapshot["last_block_height"] == 0


def test_state_sync_import_validates_hash_and_restores_state(tmp_path) -> None:
    source_store = ABCIStateStore(tmp_path / "source", chunk_size=64)
    source = _app(source_store)
    source.finalize_block(block_height=1, block_hash=b"c" * 32, txs=[])
    metadata = source.list_state_snapshots()[0]

    destination_store = ABCIStateStore(tmp_path / "destination", chunk_size=64)
    destination = _app(destination_store)
    assert destination.offer_state_snapshot(metadata) == "accept"
    for index in range(metadata.chunks):
        status = destination.apply_state_snapshot_chunk(
            index=index,
            chunk=source.load_state_snapshot_chunk(
                height=metadata.height,
                format=metadata.format,
                chunk=index,
            ),
        )
        assert status == "accept"

    assert destination.info().last_block_height == source.info().last_block_height
    assert destination.info().last_block_app_hash == source.info().last_block_app_hash
    assert destination_store.load_current() is not None


def test_state_sync_rejects_offer_with_mismatched_app_hash(tmp_path) -> None:
    source_store = ABCIStateStore(tmp_path / "source")
    source = _app(source_store)
    source.finalize_block(block_height=1, block_hash=b"d" * 32, txs=[])
    metadata = source.list_state_snapshots()[0]
    bad_metadata = metadata.__class__(
        height=metadata.height,
        format=metadata.format,
        chunks=metadata.chunks,
        hash=metadata.hash,
        app_hash=b"x" * 32,
    )

    destination = _app(ABCIStateStore(tmp_path / "destination"))
    assert destination.offer_state_snapshot(bad_metadata) == "accept"
    assert destination.apply_state_snapshot_chunk(
        index=0,
        chunk=source.load_state_snapshot_chunk(
            height=metadata.height,
            format=metadata.format,
            chunk=0,
        ),
    ) == "reject_snapshot"


def test_state_sync_rolls_back_if_import_cannot_be_persisted(tmp_path, monkeypatch) -> None:
    source_store = ABCIStateStore(tmp_path / "source", chunk_size=64)
    source = _app(source_store)
    source.finalize_block(block_height=1, block_hash=b"f" * 32, txs=[])
    metadata = source.list_state_snapshots()[0]
    destination_store = ABCIStateStore(tmp_path / "destination", chunk_size=64)
    destination = _app(destination_store)
    monkeypatch.setattr(
        destination_store,
        "persist",
        lambda state: (_ for _ in ()).throw(ABCIStateStoreError("disk full")),
    )

    assert destination.offer_state_snapshot(metadata) == "accept"
    for index in range(metadata.chunks):
        status = destination.apply_state_snapshot_chunk(
            index=index,
            chunk=source.load_state_snapshot_chunk(
                height=metadata.height,
                format=metadata.format,
                chunk=index,
            ),
        )
    assert status == "abort"
    assert destination.info().last_block_height == 0


def test_corrupt_durable_state_fails_closed(tmp_path) -> None:
    store = ABCIStateStore(tmp_path / "abci")
    application = _app(store)
    application.finalize_block(block_height=1, block_hash=b"e" * 32, txs=[])
    snapshot = store.list_snapshots()[0]
    chunk = tmp_path / "abci" / "snapshots" / snapshot.identifier / "00000000.chunk"
    chunk.write_bytes(b"tampered")

    with pytest.raises(ABCIStateStoreError, match="corrupt"):
        _app(store)
