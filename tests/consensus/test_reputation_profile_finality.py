"""Tests for the finality-bound Reputation profile projection."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from aidn_hypervisor.consensus.abci import AIDNABCIApplication
from aidn_hypervisor.consensus.finality import ConsensusFinalityEvidence
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.consensus.reputation_finality import ReputationProfileFinalityAdapter
from aidn_hypervisor.ledger.service import LedgerOperationService
from aidn_hypervisor.reputation_engine.engine import ReputationEngine
from aidn_hypervisor.reputation_engine.store import ReputationStore


def _envelope(
    operation_type: str,
    payload: dict,
    *,
    target_epoch: str = "7",
    evidence_references: list[str] | None = None,
) -> bytes:
    return json.dumps(
        {
            "operation_type": operation_type,
            "operation_version": "1.0.0",
            "protocol_version": "0.1",
            "origin_type": "protocol",
            "initiator_id": "reputation-scheduler",
            "sender_wallet": None,
            "sender_sequence": None,
            "fee_payer": None,
            "fee_class": "protocol_sponsored",
            "created_at": datetime.now(UTC).isoformat(),
            "expires_at": None,
            "target_epoch": target_epoch,
            "payload": payload,
            "evidence_references": evidence_references or ["sha256:external-evidence"],
            "signatures": ["ed25519:protocol-attestation"],
        }
    ).encode()


def _operation_id(transaction: bytes) -> str:
    return LedgerOperationEnvelope.model_validate(json.loads(transaction)).operation_id


def _profile_payload() -> dict:
    return {
        "object_id": "endpoint:endpoint-1",
        "object_type": "reputation_profile",
        "previous_profile_hash": "sha256:" + "0" * 64,
        "new_profile_hash": "sha256:" + "d" * 64,
        "metric_deltas": {
            "VALIDATION_REPORT_AVAILABILITY": {
                "positive_mass_milli": 300,
                "negative_mass_milli": 0,
                "event_count": 1,
            }
        },
        "evidence_root": "sha256:" + "e" * 64,
        "effective_epoch": 7,
        "formula_version": "reputation.v1",
    }


def _finalized_profile() -> tuple[LedgerOperationService, str, str]:
    ledger = LedgerOperationService()
    app = AIDNABCIApplication(ledger_service=ledger)
    evidence_tx = _envelope(
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
    evidence_result = app.finalize_block_with_results(
        block_height=1,
        block_hash=b"A" * 32,
        txs=[evidence_tx],
    )
    assert evidence_result[1][0].code == "ok"
    profile_tx = _envelope(
        "REPUTATION_PROFILE_UPDATE",
        _profile_payload(),
        evidence_references=[_operation_id(evidence_tx)],
    )
    profile_envelope = LedgerOperationEnvelope.model_validate(json.loads(profile_tx))
    profile_result = app.finalize_block_with_results(
        block_height=2,
        block_hash=b"B" * 32,
        txs=[profile_tx],
    )
    assert profile_result[1][0].code == "ok"
    return ledger, profile_envelope.operation_id, profile_envelope.payload["object_id"]


class _Source:
    def __init__(self, evidence: ConsensusFinalityEvidence | None) -> None:
        self.evidence = evidence

    def finality_evidence(self, operation_id: str):
        if self.evidence is None or self.evidence.operation_id != operation_id:
            return None
        return self.evidence


def _evidence(operation_id: str) -> ConsensusFinalityEvidence:
    return ConsensusFinalityEvidence(
        operation_id=operation_id,
        chain_id="aidn-testnet-1",
        block_height=2,
        block_id="block-2",
        app_hash="app-hash-2",
        commit_hash="commit-hash-2",
        finalized_at="2030-01-01T00:00:00Z",
        verifier_id="cometbft-verifier",
    )


def test_profile_root_is_exposed_only_with_matching_finality_evidence() -> None:
    ledger, operation_id, object_id = _finalized_profile()
    adapter = ReputationProfileFinalityAdapter(
        ledger_service=ledger,
        finality_source=_Source(_evidence(operation_id)),
    )

    result = adapter.resolve(object_id=object_id, effective_epoch=7)

    assert result is not None
    assert result.operation_id == operation_id
    assert result.new_profile_hash == "sha256:" + "d" * 64
    assert result.finality_evidence.block_height == 2
    assert result.metric_deltas["VALIDATION_REPORT_AVAILABILITY"]["event_count"] == 1


def test_profile_finality_gate_fails_closed_without_or_with_mismatched_evidence() -> None:
    ledger, operation_id, object_id = _finalized_profile()
    no_source = ReputationProfileFinalityAdapter(
        ledger_service=ledger,
        finality_source=None,
    )
    assert no_source.resolve(object_id=object_id) is None
    with pytest.raises(ValueError, match="finality is unavailable"):
        no_source.require(object_id=object_id)

    mismatched = ReputationProfileFinalityAdapter(
        ledger_service=ledger,
        finality_source=_Source(_evidence("another-operation")),
    )
    assert mismatched.resolve(object_id=object_id) is None


def test_finality_projection_does_not_ingest_a_local_reputation_score() -> None:
    ledger, operation_id, object_id = _finalized_profile()
    engine = ReputationEngine(ReputationStore())
    adapter = ReputationProfileFinalityAdapter(
        ledger_service=ledger,
        finality_source=_Source(_evidence(operation_id)),
    )

    assert adapter.require(object_id=object_id).object_id == object_id
    assert engine.get_profile("ENDPOINT", object_id) is None
