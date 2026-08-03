"""Consensus tests for RFC-0059 REPUTATION_PROFILE_UPDATE."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from aidn_hypervisor.consensus.abci import AIDNABCIApplication
from aidn_hypervisor.consensus.admission import AdmissionValidator
from aidn_hypervisor.consensus.execution import ExecutionEngine
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.ledger.service import LedgerOperationService


def _envelope(
    operation_type: str,
    payload: dict,
    *,
    evidence_references: list[str] | None = None,
    target_epoch: str = "7",
    created_at: str | None = None,
) -> bytes:
    value = {
        "operation_type": operation_type,
        "operation_version": "1.0.0",
        "protocol_version": "0.1",
        "origin_type": "protocol",
        "initiator_id": "reputation-scheduler",
        "sender_wallet": None,
        "sender_sequence": None,
        "fee_payer": None,
        "fee_class": "protocol_sponsored",
        "created_at": created_at or datetime.now(UTC).isoformat(),
        "expires_at": None,
        "target_epoch": target_epoch,
        "payload": payload,
        "evidence_references": evidence_references or ["sha256:external-evidence"],
        "signatures": ["ed25519:protocol-attestation"],
    }
    return json.dumps(value).encode()


def _operation_id(tx: bytes) -> str:
    return LedgerOperationEnvelope.model_validate(json.loads(tx)).operation_id


def _verification_tx() -> bytes:
    return _envelope(
        "SERVICE_VERIFICATION_COMMIT",
        {
            "verification_report_id": "verification-1",
            "service_id": "endpoint-1",
            "service_type": "ENDPOINT",
            "report_hash": "sha256:" + "a" * 64,
            "evidence_root": "sha256:" + "b" * 64,
            "verification_epoch": 7,
            "result_summary": {"eligible": True},
            "registry_reference": {"object_id": "sha256:" + "c" * 64},
        },
    )


def _profile_payload(
    *,
    previous_profile_hash: str = "sha256:" + "0" * 64,
    new_profile_hash: str = "sha256:" + "d" * 64,
    effective_epoch: int = 7,
) -> dict:
    return {
        "object_id": "endpoint:endpoint-1",
        "object_type": "reputation_profile",
        "previous_profile_hash": previous_profile_hash,
        "new_profile_hash": new_profile_hash,
        "metric_deltas": {
            "VALIDATION_REPORT_AVAILABILITY": {
                "positive_mass_milli": 300,
                "negative_mass_milli": 0,
                "event_count": 1,
            }
        },
        "evidence_root": "sha256:" + "e" * 64,
        "effective_epoch": effective_epoch,
        "formula_version": "reputation.v1",
    }


def test_abci_commits_profile_root_only_after_finalized_evidence() -> None:
    ledger = LedgerOperationService()
    app = AIDNABCIApplication(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(
            current_time=datetime.now(UTC).isoformat()
        ),
    )
    evidence_tx = _verification_tx()
    evidence_result = app.finalize_block_with_results(
        block_height=1,
        block_hash=b"A" * 32,
        txs=[evidence_tx],
    )
    assert evidence_result[0].code == "ok"
    assert evidence_result[1][0].code == "ok"

    profile_tx = _envelope(
        "REPUTATION_PROFILE_UPDATE",
        _profile_payload(),
        evidence_references=[_operation_id(evidence_tx)],
    )
    profile_result = app.finalize_block_with_results(
        block_height=2,
        block_hash=b"B" * 32,
        txs=[profile_tx],
    )

    assert profile_result[0].code == "ok"
    assert profile_result[1][0].code == "ok"
    assert ledger.wallet_q_atom_balance("wallet:reputation-scheduler") == 0
    assert ledger.snapshot_operations()[-1]["operation_type"] == (
        "REPUTATION_PROFILE_UPDATE"
    )


def test_execution_engine_commits_profile_root_and_exposes_state_change() -> None:
    ledger = LedgerOperationService()
    engine = ExecutionEngine(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(
            current_time=datetime.now(UTC).isoformat()
        ),
    )
    evidence_tx = _verification_tx()
    first = engine.execute_block(
        block_height=1,
        block_hash=b"A" * 32,
        txs=[evidence_tx],
    )
    assert first.operations_executed == 1

    profile_tx = _envelope(
        "REPUTATION_PROFILE_UPDATE",
        _profile_payload(),
        evidence_references=[_operation_id(evidence_tx)],
    )
    second = engine.execute_block(
        block_height=2,
        block_hash=b"B" * 32,
        txs=[profile_tx],
    )

    assert second.operations_executed == 1
    assert second.operations_rejected == 0
    assert second.execution_events[0].emitted_events == [
        "ReputationProfileUpdated"
    ]
    assert second.state_changes[0].entity_type == "reputation_profile"


def test_profile_update_rejects_unfinalized_evidence() -> None:
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
        txs=[
            _envelope(
                "REPUTATION_PROFILE_UPDATE",
                _profile_payload(),
                evidence_references=["missing-operation-id"],
            )
        ],
    )

    assert result.code == "ok"
    assert tx_results[0].code == "rejected"
    assert "not finalized" in (tx_results[0].log or "")
    assert ledger.snapshot_operations() == []


def test_profile_update_rejects_duplicate_epoch_and_broken_root_chain() -> None:
    ledger = LedgerOperationService()
    app = AIDNABCIApplication(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(
            current_time=datetime.now(UTC).isoformat()
        ),
    )
    evidence_tx = _verification_tx()
    app.finalize_block(
        block_height=1,
        block_hash=b"A" * 32,
        txs=[evidence_tx],
    )
    evidence_id = _operation_id(evidence_tx)
    first_tx = _envelope(
        "REPUTATION_PROFILE_UPDATE",
        _profile_payload(),
        evidence_references=[evidence_id],
        created_at="2026-08-02T00:00:00+00:00",
    )
    first = app.finalize_block_with_results(
        block_height=2,
        block_hash=b"B" * 32,
        txs=[first_tx],
    )
    assert first[0].code == "ok"
    assert first[1][0].code == "ok"

    duplicate = app.finalize_block_with_results(
        block_height=3,
        block_hash=b"C" * 32,
        txs=[
            _envelope(
                "REPUTATION_PROFILE_UPDATE",
                _profile_payload(),
                evidence_references=[evidence_id],
                created_at="2026-08-02T00:00:01+00:00",
            )
        ],
    )
    assert duplicate[1][0].code == "rejected"
    assert "epoch is not increasing" in (duplicate[1][0].log or "")

    broken_chain = app.finalize_block_with_results(
        block_height=4,
        block_hash=b"D" * 32,
        txs=[
            _envelope(
                "REPUTATION_PROFILE_UPDATE",
                _profile_payload(
                    previous_profile_hash="sha256:" + "f" * 64,
                    new_profile_hash="sha256:" + "1" * 64,
                    effective_epoch=8,
                ),
                evidence_references=[evidence_id],
                target_epoch="8",
                created_at="2026-08-02T00:00:02+00:00",
            )
        ],
    )
    assert broken_chain[1][0].code == "rejected"
    assert "previous root does not match" in (broken_chain[1][0].log or "")


def test_profile_update_rejects_non_fixed_point_metric_delta() -> None:
    ledger = LedgerOperationService()
    app = AIDNABCIApplication(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(
            current_time=datetime.now(UTC).isoformat()
        ),
    )
    evidence_tx = _verification_tx()
    app.finalize_block(
        block_height=1,
        block_hash=b"A" * 32,
        txs=[evidence_tx],
    )
    payload = _profile_payload()
    payload["metric_deltas"]["VALIDATION_REPORT_AVAILABILITY"][
        "positive_mass_milli"
    ] = 0.5
    result, tx_results = app.finalize_block_with_results(
        block_height=2,
        block_hash=b"B" * 32,
        txs=[
            _envelope(
                "REPUTATION_PROFILE_UPDATE",
                payload,
                evidence_references=[_operation_id(evidence_tx)],
            )
        ],
    )

    assert result.code == "ok"
    assert tx_results[0].code == "rejected"
    assert "metric delta is invalid" in (tx_results[0].log or "")
