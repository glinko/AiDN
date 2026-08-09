"""Durable local-state and State Sync coverage for the ABCI application."""

from __future__ import annotations

import base64
import hashlib
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


def test_legacy_snapshot_without_transaction_hash_remains_restorable(tmp_path) -> None:
    store = ABCIStateStore(tmp_path / "abci")
    application = _app(store)
    transaction = _operation_bytes()

    assert application.finalize_block(
        block_height=1,
        block_hash=b"l" * 32,
        txs=[transaction],
    ).code == "ok"
    legacy_snapshot = application.prepare_snapshot()
    for operation in legacy_snapshot["ledger_operations"]:
        operation.pop("transaction_hash", None)
    legacy_application = _app()
    legacy_application.ledger.restore(
        operations=legacy_snapshot["ledger_operations"],
        wallet_sequences=legacy_snapshot["wallet_sequences"],
    )
    legacy_snapshot["app_hash"] = legacy_application._compute_state_hash().hex()
    store.persist(legacy_snapshot)

    restored = _app(store)

    assert restored.info().last_block_height == 1
    assert restored.info().last_block_app_hash == bytes.fromhex(legacy_snapshot["app_hash"])


def test_transaction_hash_metadata_does_not_change_app_hash() -> None:
    application = _app()
    transaction = _operation_bytes()

    assert application.finalize_block(block_height=1, block_hash=b"h" * 32, txs=[transaction]).code == "ok"
    canonical_hash = application._compute_state_hash()

    application.ledger.snapshot_operations()[-1]["transaction_hash"] = "F" * 64

    assert application._compute_state_hash() == canonical_hash


def test_validator_bootstrap_migrates_metadata_inclusive_app_hash(tmp_path) -> None:
    store = ABCIStateStore(tmp_path / "abci")
    source = _app()
    transaction = _operation_bytes()
    assert source.finalize_block(block_height=1, block_hash=b"m" * 32, txs=[transaction]).code == "ok"

    legacy_snapshot = source.prepare_snapshot()
    legacy_snapshot["app_hash"] = source._compute_state_hash(
        include_transaction_hash_metadata=True
    ).hex()
    for commitment in legacy_snapshot["commitments"]:
        if commitment["height"] == 1:
            commitment["app_hash"] = legacy_snapshot["app_hash"]
    store.persist(legacy_snapshot)

    restored_ledger = LedgerOperationService()
    restored_ledger.restore(
        operations=legacy_snapshot["ledger_operations"],
        wallet_sequences=legacy_snapshot["wallet_sequences"],
    )
    restored = AIDNABCIApplication(
        ledger_service=restored_ledger,
        state_store=store,
        restore_state_from_store=False,
    )

    assert restored.restore_durable_state_if_matching_ledger()
    assert restored.info().last_block_app_hash == source._compute_state_hash()
    assert store.load_current()["app_hash"] == source._compute_state_hash().hex()


def test_reconcile_restores_missing_consensus_projection_from_durable_state(tmp_path) -> None:
    store = ABCIStateStore(tmp_path / "abci")
    source = _app()
    assert source.finalize_block(block_height=1, block_hash=b"r" * 32, txs=[]).code == "ok"
    source.ledger.restore_consensus_state(
        {
            "active_validator_set": {
                "node-1": {
                    "consensus_public_key": "ed25519:" + base64.b64encode(bytes(range(32))).decode("ascii"),
                    "voting_power": 1,
                }
            },
            "active_validator_set_epoch": 0,
            "activated_validator_set_epochs": [0],
        }
    )
    store.persist(source.prepare_snapshot())

    restored = AIDNABCIApplication(
        ledger_service=LedgerOperationService(),
        state_store=store,
        restore_state_from_store=False,
    )

    assert restored.reconcile_durable_state_to_canonical_ledger()
    assert restored.info().last_block_height == 1
    assert restored.ledger.active_validator_set() == source.ledger.active_validator_set()


def test_finalize_block_defers_durable_state_until_commit(tmp_path) -> None:
    store = ABCIStateStore(tmp_path / "abci")
    application = _app(store)

    result, _ = application.finalize_block_with_results(
        block_height=1,
        block_hash=b"p" * 32,
        txs=[],
    )

    assert result.code == "ok"
    assert store.load_current() is None
    preview = application.preview_commit()
    committed = application.commit()
    assert committed.data == preview.data
    durable_snapshot = store.load_current()
    assert durable_snapshot is not None
    assert durable_snapshot["last_block_height"] == 1


def test_commit_failure_restores_last_durable_block(tmp_path, monkeypatch) -> None:
    store = ABCIStateStore(tmp_path / "abci")
    application = _app(store)
    assert application.finalize_block(block_height=1, block_hash=b"a" * 32, txs=[]).code == "ok"

    original_persist = store.persist
    persist_calls = 0

    def fail_once(snapshot: dict) -> None:
        nonlocal persist_calls
        persist_calls += 1
        if persist_calls == 1:
            raise ABCIStateStoreError("disk full")
        original_persist(snapshot)

    monkeypatch.setattr(store, "persist", fail_once)
    result, _ = application.finalize_block_with_results(
        block_height=2,
        block_hash=b"b" * 32,
        txs=[],
    )

    assert result.code == "ok"
    with pytest.raises(ABCIStateStoreError, match="durable state persistence failed"):
        application.commit()
    assert application.info().last_block_height == 1
    durable_snapshot = store.load_current()
    assert durable_snapshot is not None
    assert durable_snapshot["last_block_height"] == 1


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


def test_snapshot_restore_rejects_mismatched_declared_state_root() -> None:
    source = _app()
    snapshot = source.prepare_snapshot()
    snapshot["state_root"] = "0" * 64

    restored = _app()
    result = restored.apply_snapshot(snapshot)

    assert result.code == "internal"
    assert "state root" in result.log


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


def test_state_sync_retention_keeps_a_bounded_transfer_window(tmp_path) -> None:
    store = ABCIStateStore(tmp_path / "abci", retained_snapshots=3)
    application = _app(store)

    for height in range(1, 5):
        result = application.finalize_block(
            block_height=height,
            block_hash=bytes([height]) * 32,
            txs=[],
        )
        assert result.code == "ok"

    assert [snapshot.height for snapshot in store.list_snapshots()] == [4, 3, 2]
    with pytest.raises(ABCIStateStoreError, match="unavailable"):
        store.load_snapshot_chunk(height=1, format=1, chunk=0)


def test_state_sync_lease_protects_snapshot_after_transfer_starts(tmp_path) -> None:
    store = ABCIStateStore(
        tmp_path / "abci",
        retained_snapshots=1,
        snapshot_lease_seconds=60,
    )
    application = _app(store)

    application.finalize_block(block_height=1, block_hash=b"a" * 32, txs=[])
    metadata = store.list_snapshots()[0]
    first_chunk = store.load_snapshot_chunk(
        height=metadata.height,
        format=metadata.format,
        chunk=0,
    )
    assert first_chunk

    application.finalize_block(block_height=2, block_hash=b"b" * 32, txs=[])
    assert any(item.height == 1 for item in store.list_snapshots())

    store.release_snapshot_lease(height=metadata.height, format=metadata.format)
    application.finalize_block(block_height=3, block_hash=b"c" * 32, txs=[])
    with pytest.raises(ABCIStateStoreError, match="unavailable"):
        store.load_snapshot_chunk(
            height=metadata.height,
            format=metadata.format,
            chunk=0,
        )


def test_empty_settlement_extensions_do_not_change_legacy_app_hash() -> None:
    application = _app()
    current = application.prepare_snapshot()
    legacy_state = {
        "operations": current["ledger_operations"],
        "wallet_sequences": current["wallet_sequences"],
        "settlement_state": {
            "wallet_q_atom_balances": {},
            "session_funding_accounts": [],
            "settlement_proposals": [],
            "settlement_acceptances": [],
            "settlement_transition_hashes": {},
        },
    }

    legacy_hash = hashlib.sha256(
        json.dumps(legacy_state, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    assert legacy_hash == current["app_hash"]
