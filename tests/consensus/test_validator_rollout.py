from __future__ import annotations

import base64
import json

from aidn_hypervisor.consensus.abci import AIDNABCIApplication
from aidn_hypervisor.consensus.admission import AdmissionValidator
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.consensus.validator_schedule import (
    ValidatorCandidate,
    ValidatorScheduleBuilder,
    ValidatorScheduleConfig,
    compute_eligibility_evidence_root,
)
from aidn_hypervisor.eligibility.models import EligibilitySnapshot, EligibilityState
from aidn_hypervisor.ledger.service import LedgerOperationService


def _candidate(index: int) -> ValidatorCandidate:
    node_id = f"node-{index}"
    public_key = base64.b64encode(bytes([index]) * 32).decode("ascii")
    return ValidatorCandidate(
        node_id=node_id,
        operator_id=f"operator-{index}",
        consensus_address=f"sha256:{node_id}",
        consensus_public_key=f"ed25519:{public_key}",
        stake=500_000_000,
        kcg_id=f"kcg-{index}",
    )


def _snapshot(index: int) -> EligibilitySnapshot:
    return EligibilitySnapshot(
        epoch=1,
        service_id=f"node-{index}",
        state=EligibilityState.ACTIVE,
        rating_score=0.95,
        health_score=0.99,
        kcg_id=f"kcg-{index}",
        activation_age=10,
        has_duty_proof=True,
    )


def _transition() -> bytes:
    envelope = LedgerOperationEnvelope(
        operation_type="EPOCH_TRANSITION",
        origin_type="protocol",
        initiator_id="epoch-engine",
        created_at="2030-01-01T00:00:00Z",
        expires_at="2030-01-02T00:00:00Z",
        target_epoch="1",
        payload={
            "closing_epoch": 1,
            "opening_epoch": 2,
            "closing_state_root": "sha256:closing-1",
            "epoch_task_result_root": "sha256:tasks-1",
            "eligibility_snapshot_root": "sha256:eligibility-1",
            "reward_calculation_root": "sha256:rewards-1",
            "next_protocol_parameters_hash": "sha256:params-2",
            "pool_budgets": {"registry": 0},
            "pool_budget_references": {"registry": "epoch:1:registry"},
        },
        evidence_references=["sha256:eligibility-1"],
        signatures=["ed25519:epoch-engine"],
    )
    return json.dumps(envelope.model_dump(mode="json")).encode("utf-8")


def test_four_abci_instances_apply_the_same_snapshot_derived_rollout() -> None:
    candidates = {f"node-{index}": _candidate(index) for index in range(1, 5)}
    snapshots = [_snapshot(index) for index in range(1, 5)]
    evidence_root = compute_eligibility_evidence_root(
        snapshots=snapshots,
        candidate_metadata=candidates,
    )
    schedule = ValidatorScheduleBuilder(
        ValidatorScheduleConfig(
            target_validator_count=4,
            minimum_stake=500_000_000,
            max_validators_per_kcg=1,
            retained_active_fraction_numerator=0,
            retained_active_fraction_denominator=1,
            equal_voting_power=1,
        )
    ).build_schedule_from_eligibility_snapshots(
        snapshots=snapshots,
        candidate_metadata=candidates,
        active_validator_set={},
        activation_epoch=2,
        selection_seed="sha256:rollout-seed-2",
        eligibility_evidence_root=evidence_root,
    )
    schedule_envelope = schedule.to_envelope(
        created_at="2030-01-01T00:00:00Z",
        expires_at="2030-01-02T00:00:00Z",
        signatures=["ed25519:epoch-engine"],
    )
    schedule_tx = json.dumps(schedule_envelope.model_dump(mode="json")).encode("utf-8")

    observations: list[tuple[list[dict], dict, str]] = []
    for _ in range(4):
        ledger = LedgerOperationService()
        app = AIDNABCIApplication(
            ledger_service=ledger,
            admission_validator=AdmissionValidator(
                current_time="2030-01-01T00:00:00Z"
            ),
        )
        scheduled = app.finalize_block(
            block_height=1,
            block_hash=b"A" * 32,
            txs=[schedule_tx],
        )
        activated, tx_results = app.finalize_block_with_results(
            block_height=2,
            block_hash=b"B" * 32,
            txs=[_transition()],
        )

        assert scheduled.code == "ok"
        assert activated.code == "ok"
        assert tx_results[0].code == "ok"
        observations.append(
            (
                activated.validator_updates,
                ledger.active_validator_set(),
                str(app.prepare_snapshot()["app_hash"]),
            )
        )

    assert all(observation == observations[0] for observation in observations)
    assert len(observations[0][0]) == 4
    assert all(item["power"] == 1 for item in observations[0][0])
