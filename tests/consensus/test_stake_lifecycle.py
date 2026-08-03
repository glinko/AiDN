from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from aidn_hypervisor.consensus.abci import AIDNABCIApplication
from aidn_hypervisor.consensus.admission import AdmissionValidator
from aidn_hypervisor.consensus.execution import ExecutionEngine
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.ledger.service import LedgerOperationService


def _timestamp(*, future_hours: int = 0) -> str:
    return (datetime.now(UTC) + timedelta(hours=future_hours)).isoformat()


def _envelope(
    operation_type: str,
    *,
    origin_type: str,
    sender_wallet: str | None = None,
    sender_sequence: int | None = None,
    fee_class: str | None = None,
    payload: dict,
    target_epoch: str | None = None,
) -> bytes:
    return json.dumps(
        {
            "operation_type": operation_type,
            "operation_version": "1.0.0",
            "protocol_version": "0.1",
            "origin_type": origin_type,
            "initiator_id": "operator-1",
            "sender_wallet": sender_wallet,
            "sender_sequence": sender_sequence,
            "fee_payer": sender_wallet,
            "fee_class": fee_class or ("standard" if sender_wallet else "protocol_sponsored"),
            "created_at": _timestamp(),
            "expires_at": _timestamp(future_hours=24),
            "target_epoch": target_epoch,
            "payload": payload,
            "evidence_references": [],
            "signatures": [],
        }
    ).encode()


def _stake_lock() -> bytes:
    return _envelope(
        "STAKE_LOCK",
        origin_type="wallet",
        sender_wallet="wallet:operator-1",
        sender_sequence=1,
        payload={
            "stake_id": "stake:validator-1",
            "stake_type": "CONSENSUS_STAKE",
            "amount": 300,
            "beneficiary_object_id": "service:validator-1",
            "lock_policy_version": "consensus-stake.v1",
        },
    )


def _unstake_request() -> bytes:
    return _envelope(
        "UNSTAKE_REQUEST",
        origin_type="wallet",
        sender_wallet="wallet:operator-1",
        sender_sequence=2,
        target_epoch="10",
        payload={
            "stake_id": "stake:validator-1",
            "request_epoch": 10,
        },
    )


def _stake_release(*, current_epoch: int) -> bytes:
    return _envelope(
        "STAKE_RELEASE",
        origin_type="protocol",
        target_epoch=str(current_epoch),
        payload={
            "stake_id": "stake:validator-1",
            "current_epoch": current_epoch,
        },
    )


def _abci() -> tuple[AIDNABCIApplication, LedgerOperationService]:
    ledger = LedgerOperationService()
    app = AIDNABCIApplication(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time=_timestamp()),
        genesis_accounts={"wallet:operator-1": 1_000},
    )
    return app, ledger


def _engine() -> tuple[ExecutionEngine, LedgerOperationService]:
    ledger = LedgerOperationService()
    ledger.credit_wallet_q_atoms(wallet_id="wallet:operator-1", amount_q_atoms=1_000)
    engine = ExecutionEngine(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time=_timestamp()),
    )
    return engine, ledger


def test_abci_stake_lifecycle_debits_then_releases_after_14_epochs() -> None:
    app, ledger = _abci()
    assert app.finalize_block(block_height=1, block_hash=b"A" * 32, txs=[_stake_lock()]).code == "ok"
    assert ledger.wallet_q_atom_balance("wallet:operator-1") == 700
    assert ledger.get_stake_record("stake:validator-1")["state"] == "LOCKED"

    unstake_result = app.finalize_block(
        block_height=2,
        block_hash=b"B" * 32,
        txs=[_unstake_request()],
    )
    assert unstake_result.code == "ok"
    stake = ledger.get_stake_record("stake:validator-1")
    assert stake["state"] == "UNBONDING"
    assert stake["release_epoch"] == 24
    assert ledger.wallet_q_atom_balance("wallet:operator-1") == 700

    release_result, release_tx_results = app.finalize_block_with_results(
        block_height=3,
        block_hash=b"C" * 32,
        txs=[_stake_release(current_epoch=24)],
    )
    assert release_result.code == "ok"
    assert release_tx_results[0].code == "ok"
    assert ledger.wallet_q_atom_balance("wallet:operator-1") == 1_000
    assert ledger.get_stake_record("stake:validator-1")["state"] == "RELEASED"


def test_abci_rejects_early_release_without_mutating_stake() -> None:
    app, ledger = _abci()
    app.finalize_block(block_height=1, block_hash=b"A" * 32, txs=[_stake_lock()])
    app.finalize_block(block_height=2, block_hash=b"B" * 32, txs=[_unstake_request()])

    result, tx_results = app.finalize_block_with_results(
        block_height=3,
        block_hash=b"C" * 32,
        txs=[_stake_release(current_epoch=23)],
    )

    assert result.code == "ok"
    assert tx_results[0].code == "rejected"
    assert "release epoch" in tx_results[0].log
    assert ledger.wallet_q_atom_balance("wallet:operator-1") == 700
    assert ledger.get_stake_record("stake:validator-1")["state"] == "UNBONDING"


def test_execution_engine_matches_abci_stake_lifecycle() -> None:
    engine, ledger = _engine()
    first = engine.execute_block(block_height=1, block_hash=b"A" * 32, txs=[_stake_lock()])
    second = engine.execute_block(block_height=2, block_hash=b"B" * 32, txs=[_unstake_request()])
    third = engine.execute_block(
        block_height=3,
        block_hash=b"C" * 32,
        txs=[_stake_release(current_epoch=24)],
    )

    assert first.operations_executed == 1
    assert second.operations_executed == 1
    assert third.operations_executed == 1
    assert ledger.wallet_q_atom_balance("wallet:operator-1") == 1_000
    assert ledger.get_stake_record("stake:validator-1")["state"] == "RELEASED"


def test_stake_release_operation_identity_is_not_reused() -> None:
    envelope = LedgerOperationEnvelope.model_validate(json.loads(_stake_release(current_epoch=24)))
    assert envelope.operation_type == "STAKE_RELEASE"
    assert envelope.operation_id


def test_abci_snapshot_restores_stake_and_unbonding_boundary() -> None:
    app, ledger = _abci()
    app.finalize_block(block_height=1, block_hash=b"A" * 32, txs=[_stake_lock()])
    app.finalize_block(block_height=2, block_hash=b"B" * 32, txs=[_unstake_request()])
    snapshot = app.prepare_snapshot()

    restored_ledger = LedgerOperationService()
    restored_app = AIDNABCIApplication(
        ledger_service=restored_ledger,
        admission_validator=AdmissionValidator(current_time=_timestamp()),
    )
    assert restored_app.apply_snapshot(snapshot).code == "ok"
    assert restored_ledger.wallet_q_atom_balance("wallet:operator-1") == 700
    assert restored_ledger.get_stake_record("stake:validator-1")["state"] == "UNBONDING"
    assert restored_ledger.get_stake_record("stake:validator-1")["release_epoch"] == 24
    assert restored_app.prepare_snapshot()["app_hash"] == snapshot["app_hash"]
