from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from aidn_hypervisor.consensus.abci import AIDNABCIApplication
from aidn_hypervisor.consensus.admission import AdmissionValidator
from aidn_hypervisor.consensus.execution import ExecutionEngine
from aidn_hypervisor.ledger.service import LedgerOperationService


def _envelope(operation_type: str, payload: dict) -> bytes:
    value = {
        "operation_type": operation_type,
        "operation_version": "1.0.0",
        "protocol_version": "0.1",
        "origin_type": "protocol",
        "initiator_id": "registry-1",
        "sender_wallet": None,
        "sender_sequence": None,
        "fee_payer": None,
        "fee_class": "protocol_sponsored",
        "created_at": datetime.now(UTC).isoformat(),
        "expires_at": (datetime.now(UTC) + timedelta(hours=24)).isoformat(),
        "target_epoch": "7",
        "payload": payload,
        "evidence_references": ["sha256:evidence"],
        "signatures": ["ed25519:attestation"],
    }
    return json.dumps(value).encode()


def _payload() -> dict:
    return {
        "verification_report_id": "report:registry:1",
        "service_id": "registry-service-1",
        "service_type": "REGISTRY",
        "report_hash": "sha256:report",
        "evidence_root": "sha256:evidence",
        "verification_epoch": 7,
        "result_summary": {"eligible": True, "raw_weight_millionths": 990_000},
        "registry_reference": {"object_id": "sha256:registry-object"},
    }


def test_abci_applies_service_verification_commit_without_wallet_credit() -> None:
    ledger = LedgerOperationService()
    app = AIDNABCIApplication(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(
            current_time=datetime.now(UTC).isoformat()
        ),
    )

    result, tx_results = app.finalize_block_with_results(
        block_height=1,
        block_hash=b"A" * 32,
        txs=[_envelope("SERVICE_VERIFICATION_COMMIT", _payload())],
    )

    assert result.code == "ok"
    assert tx_results[0].code == "ok"
    assert ledger.wallet_q_atom_balance("wallet:registry-1") == 0
    assert ledger.snapshot_operations()[0]["operation_type"] == (
        "SERVICE_VERIFICATION_COMMIT"
    )


def test_execution_engine_rejects_service_commit_with_missing_evidence_root() -> None:
    ledger = LedgerOperationService()
    engine = ExecutionEngine(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(
            current_time=datetime.now(UTC).isoformat()
        ),
    )
    payload = _payload()
    payload.pop("evidence_root")

    result = engine.execute_block(
        block_height=1,
        block_hash=b"A" * 32,
        txs=[_envelope("SERVICE_VERIFICATION_COMMIT", payload)],
    )

    assert result.operations_executed == 0
    assert result.operations_rejected == 1
    assert "evidence_root" in (result.execution_events[0].error or "")
    assert ledger.snapshot_operations() == []


def test_consensus_service_commit_rejects_same_report_under_another_operation_id() -> None:
    ledger = LedgerOperationService()
    app = AIDNABCIApplication(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(
            current_time=datetime.now(UTC).isoformat()
        ),
    )
    first = _envelope("SERVICE_VERIFICATION_COMMIT", _payload())
    second_payload = {**_payload(), "result_summary": {"eligible": False}}
    second = _envelope("SERVICE_VERIFICATION_COMMIT", second_payload)

    first_result = app.finalize_block(
        block_height=1,
        block_hash=b"A" * 32,
        txs=[first],
    )
    second_result, tx_results = app.finalize_block_with_results(
        block_height=2,
        block_hash=b"B" * 32,
        txs=[second],
    )

    assert first_result.code == "ok"
    assert second_result.code == "ok"
    assert tx_results[0].code == "rejected"
    assert "already committed" in tx_results[0].log
    assert len(ledger.snapshot_operations()) == 1
