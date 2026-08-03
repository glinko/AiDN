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
    payload: dict,
    evidence_references: list[str] | None = None,
    target_epoch: str | None = None,
) -> bytes:
    return json.dumps(
        {
            "operation_type": operation_type,
            "operation_version": "1.0.0",
            "protocol_version": "0.1",
            "origin_type": origin_type,
            "initiator_id": "consensus-policy",
            "sender_wallet": None,
            "sender_sequence": None,
            "fee_payer": None,
            "fee_class": "protocol_sponsored",
            "created_at": _timestamp(),
            "expires_at": _timestamp(future_hours=24),
            "target_epoch": target_epoch,
            "payload": payload,
            "evidence_references": evidence_references or [],
            "signatures": [],
        }
    ).encode()


def _evidence(root: str) -> tuple[bytes, str]:
    data = _envelope(
        "REGISTRY_UPSERT",
        origin_type="protocol",
        payload={"evidence_root": root},
        evidence_references=[root],
    )
    return data, LedgerOperationEnvelope.model_validate(json.loads(data)).operation_id


def _suspend(evidence_id: str, evidence_root: str) -> bytes:
    return _envelope(
        "PARTICIPANT_SUSPEND",
        origin_type="evidence_triggered",
        target_epoch="10",
        evidence_references=[evidence_id, evidence_root],
        payload={
            "target_id": "service:validator-1",
            "target_type": "CONSENSUS_SERVICE",
            "scope": "CONSENSUS",
            "reason_code": "PERSISTENT_DOWNTIME",
            "evidence_root": evidence_root,
            "evidence_operation_id": evidence_id,
            "effective_epoch": 10,
            "minimum_recovery_epoch": 17,
        },
    )


def _reinstate(evidence_id: str, evidence_root: str) -> bytes:
    return _envelope(
        "PARTICIPANT_REINSTATE",
        origin_type="protocol",
        target_epoch="17",
        evidence_references=[evidence_id, evidence_root],
        payload={
            "target_id": "service:validator-1",
            "current_epoch": 17,
            "recovery_evidence_root": evidence_root,
            "recovery_evidence_operation_id": evidence_id,
        },
    )


def _abci() -> tuple[AIDNABCIApplication, LedgerOperationService]:
    ledger = LedgerOperationService()
    app = AIDNABCIApplication(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time=_timestamp()),
    )
    return app, ledger


def test_abci_suspension_requires_prior_evidence_and_reinstatement_boundary() -> None:
    app, ledger = _abci()
    evidence, evidence_id = _evidence("sha256:downtime")
    app.finalize_block(block_height=1, block_hash=b"A" * 32, txs=[evidence])

    suspended = app.finalize_block(
        block_height=2,
        block_hash=b"B" * 32,
        txs=[_suspend(evidence_id, "sha256:downtime")],
    )
    assert suspended.code == "ok"
    assert ledger.get_participant_suspension("service:validator-1")["state"] == "SUSPENDED"

    recovery, recovery_id = _evidence("sha256:recovery")
    app.finalize_block(block_height=3, block_hash=b"C" * 32, txs=[recovery])
    reinstated = app.finalize_block(
        block_height=4,
        block_hash=b"D" * 32,
        txs=[_reinstate(recovery_id, "sha256:recovery")],
    )
    assert reinstated.code == "ok"
    assert ledger.get_participant_suspension("service:validator-1")["state"] == "ACTIVE"


def test_abci_rejects_same_block_suspension_and_early_reinstatement() -> None:
    app, ledger = _abci()
    evidence, evidence_id = _evidence("sha256:downtime")
    same_block, tx_results = app.finalize_block_with_results(
        block_height=1,
        block_hash=b"A" * 32,
        txs=[evidence, _suspend(evidence_id, "sha256:downtime")],
    )
    assert same_block.code == "ok"
    assert [item.code for item in tx_results] == ["ok", "rejected"]
    assert ledger.participant_suspensions() == {}

    app.finalize_block(block_height=2, block_hash=b"B" * 32, txs=[_suspend(evidence_id, "sha256:downtime")])
    recovery, recovery_id = _evidence("sha256:recovery")
    app.finalize_block(block_height=3, block_hash=b"C" * 32, txs=[recovery])
    result, tx_results = app.finalize_block_with_results(
        block_height=4,
        block_hash=b"D" * 32,
        txs=[
            _envelope(
                "PARTICIPANT_REINSTATE",
                origin_type="protocol",
                target_epoch="16",
                evidence_references=[recovery_id, "sha256:recovery"],
                payload={
                    "target_id": "service:validator-1",
                    "current_epoch": 16,
                    "recovery_evidence_root": "sha256:recovery",
                    "recovery_evidence_operation_id": recovery_id,
                },
            )
        ],
    )
    assert result.code == "ok"
    assert tx_results[0].code == "rejected"
    assert "minimum recovery" in tx_results[0].log
    assert ledger.get_participant_suspension("service:validator-1")["state"] == "SUSPENDED"


def test_execution_engine_matches_suspension_state_transition() -> None:
    ledger = LedgerOperationService()
    engine = ExecutionEngine(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time=_timestamp()),
    )
    evidence, evidence_id = _evidence("sha256:downtime")
    first = engine.execute_block(block_height=1, block_hash=b"A" * 32, txs=[evidence])
    second = engine.execute_block(
        block_height=2,
        block_hash=b"B" * 32,
        txs=[_suspend(evidence_id, "sha256:downtime")],
    )

    assert first.operations_executed == 1
    assert second.operations_executed == 1
    assert ledger.get_participant_suspension("service:validator-1")["minimum_recovery_epoch"] == 17


def test_abci_snapshot_restores_participant_suspension_state() -> None:
    app, ledger = _abci()
    evidence, evidence_id = _evidence("sha256:downtime")
    app.finalize_block(block_height=1, block_hash=b"A" * 32, txs=[evidence])
    app.finalize_block(
        block_height=2,
        block_hash=b"B" * 32,
        txs=[_suspend(evidence_id, "sha256:downtime")],
    )
    snapshot = app.prepare_snapshot()

    restored_ledger = LedgerOperationService()
    restored_app = AIDNABCIApplication(
        ledger_service=restored_ledger,
        admission_validator=AdmissionValidator(current_time=_timestamp()),
    )
    assert restored_app.apply_snapshot(snapshot).code == "ok"
    restored = restored_ledger.get_participant_suspension("service:validator-1")
    assert restored["state"] == "SUSPENDED"
    assert restored["minimum_recovery_epoch"] == 17
    assert restored_app.prepare_snapshot()["app_hash"] == snapshot["app_hash"]
