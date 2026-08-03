from __future__ import annotations

import json
from datetime import UTC, datetime

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
        "initiator_id": "validation-protocol",
        "sender_wallet": None,
        "sender_sequence": None,
        "fee_payer": None,
        "fee_class": "protocol_sponsored",
        "created_at": datetime.now(UTC).isoformat(),
        "expires_at": None,
        "target_epoch": "7",
        "payload": payload,
        "evidence_references": ["sha256:evidence"],
        "signatures": ["ed25519:attestation"],
    }
    return json.dumps(value).encode()


def _commit_payload() -> dict:
    return {
        "report_id": "report-1",
        "report_hash": "sha256:" + "a" * 64,
        "report_size": 128,
        "validation_request_id": "request-1",
        "assignment_id": "assignment-1",
        "endpoint_id": "endpoint-1",
        "endpoint_configuration_hash": "config-1",
        "validator_service_id": "validator-1",
        "conclusion_summary": "pass",
        "limitation_codes": [],
        "failure_codes": [],
        "observation_codes": [],
        "evidence_root": "sha256:" + "b" * 64,
        "evidence_access_class": "public",
        "report_locator": "aidn://endpoint/endpoint-1/validation/sha256:" + "a" * 64,
        "retention_policy_id": "validation-default",
        "storage_receipt_hash": None,
        "storage_failure_reference": None,
        "evidence_summary": "all checks passed",
    }


def _receipt_payload() -> dict:
    commit = _commit_payload()
    return {
        "receipt_id": "receipt-1",
        "validation_id": commit["validation_request_id"],
        "endpoint_id": commit["endpoint_id"],
        "endpoint_configuration_hash": commit["endpoint_configuration_hash"],
        "report_hash": commit["report_hash"],
        "report_size": commit["report_size"],
        "report_locator": commit["report_locator"],
        "retention_policy_id": commit["retention_policy_id"],
        "endpoint_public_key": "ed25519:" + "c" * 64,
        "receipt_hash": "sha256:" + "d" * 64,
    }


def test_validation_report_commit_and_receipt_are_consensus_evidence_only() -> None:
    ledger = LedgerOperationService()
    app = AIDNABCIApplication(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time=datetime.now(UTC).isoformat()),
    )

    first = app.finalize_block_with_results(
        block_height=1,
        block_hash=b"A" * 32,
        txs=[_envelope("VALIDATION_REPORT_COMMIT", _commit_payload())],
    )
    assert first[0].code == "ok"
    assert first[1][0].code == "ok"
    assert ledger.wallet_q_atom_balance("wallet:validation-protocol") == 0

    receipt = app.finalize_block_with_results(
        block_height=2,
        block_hash=b"B" * 32,
        txs=[_envelope("VALIDATION_REPORT_STORAGE_RECEIPT", _receipt_payload())],
    )
    assert receipt[0].code == "ok"
    assert receipt[1][0].code == "ok"
    assert [
        operation["operation_type"] for operation in ledger.snapshot_operations()
    ] == ["VALIDATION_REPORT_COMMIT", "VALIDATION_REPORT_STORAGE_RECEIPT"]


def test_validation_storage_failure_conflicts_with_receipt_and_wrong_scope_is_rejected() -> None:
    ledger = LedgerOperationService()
    engine = ExecutionEngine(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time=datetime.now(UTC).isoformat()),
    )
    commit = engine.execute_block(
        block_height=1,
        block_hash=b"A" * 32,
        txs=[_envelope("VALIDATION_REPORT_COMMIT", _commit_payload())],
    )
    assert commit.operations_executed == 1

    failure = {
        "failure_id": "failure-1",
        "validation_id": "request-1",
        "endpoint_id": "endpoint-1",
        "endpoint_configuration_hash": "config-1",
        "report_hash": _commit_payload()["report_hash"],
        "report_size": 128,
        "report_locator": _commit_payload()["report_locator"],
        "retention_policy_id": "validation-default",
        "failure_code": "storage_refused",
        "failure_evidence_root": "sha256:" + "e" * 64,
        "reported_by": "validator-1",
    }
    result = engine.execute_block(
        block_height=2,
        block_hash=b"B" * 32,
        txs=[_envelope("VALIDATION_REPORT_STORAGE_FAILURE", failure)],
    )
    assert result.operations_executed == 1

    wrong_scope = _receipt_payload()
    wrong_scope["endpoint_id"] = "other-endpoint"
    rejected = engine.execute_block(
        block_height=3,
        block_hash=b"C" * 32,
        txs=[_envelope("VALIDATION_REPORT_STORAGE_RECEIPT", wrong_scope)],
    )
    assert rejected.operations_executed == 0
    assert rejected.operations_rejected == 1
    assert "commitment" in (rejected.execution_events[0].error or "").lower()


def test_validation_availability_commit_binds_report_and_challenge_identity() -> None:
    ledger = LedgerOperationService()
    app = AIDNABCIApplication(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time=datetime.now(UTC).isoformat()),
    )
    commit = app.finalize_block(
        block_height=1,
        block_hash=b"A" * 32,
        txs=[_envelope("VALIDATION_REPORT_COMMIT", _commit_payload())],
    )
    assert commit.code == "ok"
    payload = _commit_payload()
    availability = {
        "report_id": payload["report_id"],
        "report_hash": payload["report_hash"],
        "endpoint_id": payload["endpoint_id"],
        "endpoint_configuration_hash": payload["endpoint_configuration_hash"],
        "report_size": payload["report_size"],
        "report_locator": payload["report_locator"],
        "retention_policy_id": payload["retention_policy_id"],
        "custody_status": "available",
        "failure_streak": 0,
        "challenge_id": "challenge-1",
    }
    first = app.finalize_block(
        block_height=2,
        block_hash=b"B" * 32,
        txs=[_envelope("VALIDATION_REPORT_AVAILABILITY_COMMIT", availability)],
    )
    assert first.code == "ok"

    changed = {**availability, "custody_status": "corrupted"}
    second = app.finalize_block_with_results(
        block_height=3,
        block_hash=b"C" * 32,
        txs=[_envelope("VALIDATION_REPORT_AVAILABILITY_COMMIT", changed)],
    )
    assert second[0].code == "ok"
    assert second[1][0].code == "rejected"
    assert "conflicting Validation custody challenge" in (second[1][0].log or "")

    replay = app.finalize_block_with_results(
        block_height=4,
        block_hash=b"D" * 32,
        txs=[_envelope("VALIDATION_REPORT_AVAILABILITY_COMMIT", availability)],
    )
    assert replay[0].code == "ok"
    assert replay[1][0].code == "rejected"
    # A byte-identical retry is stopped by admission; a semantically identical
    # retry with a fresh envelope reaches the evidence-specific guard.
    assert replay[1][0].log in {
        "duplicate_operation_id",
        "Validation custody challenge is already committed",
    }


def test_validation_custody_release_preserves_commitment_history() -> None:
    ledger = LedgerOperationService()
    app = AIDNABCIApplication(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time=datetime.now(UTC).isoformat()),
    )
    payload = _commit_payload()
    assert app.finalize_block(
        block_height=1,
        block_hash=b"A" * 32,
        txs=[_envelope("VALIDATION_REPORT_COMMIT", payload)],
    ).code == "ok"
    release = {
        "report_id": payload["report_id"],
        "report_hash": payload["report_hash"],
        "endpoint_id": payload["endpoint_id"],
        "endpoint_configuration_hash": payload["endpoint_configuration_hash"],
        "report_size": payload["report_size"],
        "report_locator": payload["report_locator"],
        "retention_policy_id": payload["retention_policy_id"],
        "release_reason": "retirement_grace_expired",
        "released_at": "2030-01-01T00:00:00Z",
    }
    result, tx_results = app.finalize_block_with_results(
        block_height=2,
        block_hash=b"B" * 32,
        txs=[_envelope("VALIDATION_REPORT_CUSTODY_RELEASE", release)],
    )
    assert result.code == "ok"
    assert tx_results[0].code == "ok"
    assert [
        operation["operation_type"] for operation in ledger.snapshot_operations()
    ] == ["VALIDATION_REPORT_COMMIT", "VALIDATION_REPORT_CUSTODY_RELEASE"]
    assert ledger.validation_report_commitment(payload["report_id"]) is not None
