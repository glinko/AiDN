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
    origin_type: str = "protocol",
    payload: dict | None = None,
    evidence_references: list[str] | None = None,
) -> bytes:
    return json.dumps(
        {
            "operation_type": operation_type,
            "operation_version": "1.0.0",
            "protocol_version": "0.1",
            "origin_type": origin_type,
            "initiator_id": "evidence-engine",
            "sender_wallet": None,
            "sender_sequence": None,
            "fee_payer": None,
            "fee_class": "protocol_sponsored",
            "created_at": _timestamp(),
            "expires_at": _timestamp(future_hours=24),
            "target_epoch": "1",
            "payload": payload or {},
            "evidence_references": evidence_references or [],
            "signatures": [],
        }
    ).encode()


def _evidence() -> tuple[bytes, str, str]:
    evidence_root = "sha256:double-sign-evidence"
    data = _envelope(
        "REGISTRY_UPSERT",
        payload={"evidence_root": evidence_root, "subject": "validator-1"},
        evidence_references=[evidence_root],
    )
    return data, LedgerOperationEnvelope.model_validate(json.loads(data)).operation_id, evidence_root


def _penalty(
    evidence_operation_id: str,
    evidence_root: str,
    *,
    amount: int = 250,
    target: str = "wallet:validator-1",
) -> bytes:
    payload = {
        "penalty_id": "penalty:validator-1:double-sign:1",
        "target_wallet_or_lock": target,
        "penalty_type": "DOUBLE_SIGNING",
        "amount": amount,
        "evidence_root": evidence_root,
        "evidence_operation_id": evidence_operation_id,
        "recyclable": True,
    }
    return _envelope(
        "PENALTY_APPLY",
        origin_type="evidence_triggered",
        payload=payload,
        evidence_references=[evidence_operation_id, evidence_root],
    )


def _abci() -> tuple[AIDNABCIApplication, LedgerOperationService]:
    ledger = LedgerOperationService()
    app = AIDNABCIApplication(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time=_timestamp()),
        genesis_accounts={"wallet:validator-1": 1_000},
    )
    return app, ledger


def _engine() -> tuple[ExecutionEngine, LedgerOperationService]:
    ledger = LedgerOperationService()
    ledger.credit_wallet_q_atoms(wallet_id="wallet:validator-1", amount_q_atoms=1_000)
    engine = ExecutionEngine(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time=_timestamp()),
    )
    return engine, ledger


def test_abci_applies_evidence_bound_penalty_and_tracks_recycling() -> None:
    app, ledger = _abci()
    evidence, evidence_id, evidence_root = _evidence()
    assert app.finalize_block(block_height=1, block_hash=b"A" * 32, txs=[evidence]).code == "ok"

    result, tx_results = app.finalize_block_with_results(
        block_height=2,
        block_hash=b"B" * 32,
        txs=[_penalty(evidence_id, evidence_root)],
    )

    assert result.code == "ok"
    assert tx_results[0].code == "ok"
    assert ledger.wallet_q_atom_balance("wallet:validator-1") == 750
    assert ledger.recyclable_q_atom_balance() == 250
    assert ledger.burned_q_atom_balance() == 0
    assert ledger.snapshot_operations()[-1]["operation_type"] == "PENALTY_APPLY"


def test_abci_rejects_penalty_when_evidence_is_only_in_same_block() -> None:
    app, ledger = _abci()
    evidence, evidence_id, evidence_root = _evidence()

    result, tx_results = app.finalize_block_with_results(
        block_height=1,
        block_hash=b"A" * 32,
        txs=[evidence, _penalty(evidence_id, evidence_root)],
    )

    assert result.code == "ok"
    assert [item.code for item in tx_results] == ["ok", "rejected"]
    assert "not finalized" in tx_results[1].log
    assert ledger.wallet_q_atom_balance("wallet:validator-1") == 1_000
    assert ledger.recyclable_q_atom_balance() == 0
    assert [item["operation_type"] for item in ledger.snapshot_operations()] == [
        "REGISTRY_UPSERT"
    ]


def test_abci_rejects_unbound_penalty_and_does_not_change_state() -> None:
    app, ledger = _abci()
    _, evidence_id, evidence_root = _evidence()
    penalty = _penalty(evidence_id, evidence_root)

    result, tx_results = app.finalize_block_with_results(
        block_height=1,
        block_hash=b"A" * 32,
        txs=[penalty],
    )

    assert result.code == "ok"
    assert tx_results[0].code == "rejected"
    assert "not finalized" in tx_results[0].log
    assert ledger.wallet_q_atom_balance("wallet:validator-1") == 1_000
    assert ledger.snapshot_operations() == []


def test_execution_engine_applies_same_penalty_semantics() -> None:
    engine, ledger = _engine()
    evidence, evidence_id, evidence_root = _evidence()
    first = engine.execute_block(block_height=1, block_hash=b"A" * 32, txs=[evidence])
    second = engine.execute_block(
        block_height=2,
        block_hash=b"B" * 32,
        txs=[_penalty(evidence_id, evidence_root)],
    )

    assert first.operations_executed == 1
    assert second.operations_executed == 1
    assert ledger.wallet_q_atom_balance("wallet:validator-1") == 750
    assert ledger.recyclable_q_atom_balance() == 250


def test_execution_engine_rolls_back_penalty_and_pool_on_fatal_follow_up() -> None:
    engine, ledger = _engine()
    evidence, evidence_id, evidence_root = _evidence()
    engine.execute_block(block_height=1, block_hash=b"A" * 32, txs=[evidence])

    def fatal_handler(envelope, _ledger):
        raise RuntimeError("fatal: test rollback")

    engine.register_handler("WALLET_TRANSFER", fatal_handler, gas_cost=200)
    result = engine.execute_block(
        block_height=2,
        block_hash=b"B" * 32,
        txs=[_penalty(evidence_id, evidence_root), _envelope("WALLET_TRANSFER")],
    )

    assert result.error is not None
    assert "fatal" in result.error
    assert ledger.wallet_q_atom_balance("wallet:validator-1") == 1_000
    assert ledger.recyclable_q_atom_balance() == 0
    assert [item["operation_type"] for item in ledger.snapshot_operations()] == [
        "REGISTRY_UPSERT"
    ]


def test_abci_snapshot_restores_penalty_accounting_state() -> None:
    app, ledger = _abci()
    evidence, evidence_id, evidence_root = _evidence()
    app.finalize_block(block_height=1, block_hash=b"A" * 32, txs=[evidence])
    app.finalize_block(
        block_height=2,
        block_hash=b"B" * 32,
        txs=[_penalty(evidence_id, evidence_root)],
    )
    snapshot = app.prepare_snapshot()

    restored_ledger = LedgerOperationService()
    restored_app = AIDNABCIApplication(
        ledger_service=restored_ledger,
        admission_validator=AdmissionValidator(current_time=_timestamp()),
    )
    assert restored_app.apply_snapshot(snapshot).code == "ok"
    assert restored_ledger.wallet_q_atom_balance("wallet:validator-1") == 750
    assert restored_ledger.recyclable_q_atom_balance() == 250
    assert restored_ledger.burned_q_atom_balance() == 0
    assert restored_app.prepare_snapshot()["app_hash"] == snapshot["app_hash"]


def test_abci_applies_partial_penalty_to_locked_stake_without_double_debit() -> None:
    app, ledger = _abci()
    evidence, evidence_id, evidence_root = _evidence()
    app.finalize_block(block_height=1, block_hash=b"A" * 32, txs=[evidence])
    stake_lock = _envelope(
        "STAKE_LOCK",
        origin_type="wallet",
        payload={
            "stake_id": "stake:validator-1",
            "stake_type": "CONSENSUS_STAKE",
            "amount": 300,
            "beneficiary_object_id": "service:validator-1",
            "lock_policy_version": "consensus-stake.v1",
        },
    )
    # The helper defaults to a protocol-sponsored transaction; make the
    # wallet sequence and sender explicit for the stake-lock boundary.
    stake_lock = json.dumps(
        {
            **json.loads(stake_lock),
            "origin_type": "wallet",
            "sender_wallet": "wallet:validator-1",
            "sender_sequence": 1,
            "fee_payer": "wallet:validator-1",
            "fee_class": "standard",
        }
    ).encode()
    assert app.finalize_block(block_height=2, block_hash=b"B" * 32, txs=[stake_lock]).code == "ok"

    result, tx_results = app.finalize_block_with_results(
        block_height=3,
        block_hash=b"C" * 32,
        txs=[
            _penalty(
                evidence_id,
                evidence_root,
                amount=100,
                target="lock:stake:validator-1",
            )
        ],
    )

    assert result.code == "ok"
    assert tx_results[0].code == "ok"
    assert ledger.wallet_q_atom_balance("wallet:validator-1") == 700
    assert ledger.get_stake_record("stake:validator-1")["amount"] == 200
    assert ledger.get_stake_record("stake:validator-1")["state"] == "LOCKED"
    assert ledger.recyclable_q_atom_balance() == 100


def test_abci_snapshot_restores_slashed_stake_state() -> None:
    app, ledger = _abci()
    evidence, evidence_id, evidence_root = _evidence()
    app.finalize_block(block_height=1, block_hash=b"A" * 32, txs=[evidence])
    stake_lock = json.loads(
        _envelope(
            "STAKE_LOCK",
            origin_type="wallet",
            payload={
                "stake_id": "stake:validator-1",
                "stake_type": "CONSENSUS_STAKE",
                "amount": 300,
                "beneficiary_object_id": "service:validator-1",
                "lock_policy_version": "consensus-stake.v1",
            },
        )
    )
    stake_lock.update(
        {
            "sender_wallet": "wallet:validator-1",
            "sender_sequence": 1,
            "fee_payer": "wallet:validator-1",
            "fee_class": "standard",
        }
    )
    app.finalize_block(block_height=2, block_hash=b"B" * 32, txs=[json.dumps(stake_lock).encode()])
    app.finalize_block(
        block_height=3,
        block_hash=b"C" * 32,
        txs=[
            _penalty(
                evidence_id,
                evidence_root,
                amount=300,
                target="lock:stake:validator-1",
            )
        ],
    )
    snapshot = app.prepare_snapshot()

    restored_ledger = LedgerOperationService()
    restored_app = AIDNABCIApplication(
        ledger_service=restored_ledger,
        admission_validator=AdmissionValidator(current_time=_timestamp()),
    )
    assert restored_app.apply_snapshot(snapshot).code == "ok"
    assert restored_ledger.get_stake_record("stake:validator-1")["state"] == "SLASHED"
    assert restored_ledger.get_stake_record("stake:validator-1")["amount"] == 0
    assert restored_ledger.recyclable_q_atom_balance() == 300
    assert restored_app.prepare_snapshot()["app_hash"] == snapshot["app_hash"]
