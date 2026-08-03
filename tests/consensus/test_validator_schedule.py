from __future__ import annotations

import base64

import pytest

from aidn_hypervisor.consensus.admission import AdmissionValidator
from aidn_hypervisor.consensus.validator_schedule import (
    ValidatorCandidate,
    ValidatorScheduleBuilder,
    ValidatorScheduleConfig,
    compute_eligibility_evidence_root,
    compute_participant_suspension_root,
    derive_epoch_selection_seed,
)
from aidn_hypervisor.eligibility.engine import EligibilityEngine
from aidn_hypervisor.eligibility.models import EligibilitySnapshot, EligibilityState


def _candidate(
    node_id: str,
    *,
    kcg_id: str | None = None,
    eligible: bool = True,
    stake: int = 1_000,
    participant_id: str | None = None,
) -> ValidatorCandidate:
    public_key = base64.b64encode(node_id.encode().ljust(32, b"x")[:32]).decode("ascii")
    return ValidatorCandidate(
        node_id=node_id,
        operator_id=f"operator-{node_id}",
        consensus_address=f"sha256:{node_id}",
        consensus_public_key=f"ed25519:{public_key}",
        stake=stake,
        kcg_id=kcg_id,
        eligible=eligible,
        participant_id=participant_id,
    )


def _builder(target: int = 3) -> ValidatorScheduleBuilder:
    return ValidatorScheduleBuilder(
        ValidatorScheduleConfig(
            target_validator_count=target,
            minimum_stake=500,
            max_validators_per_kcg=1,
            retained_active_fraction_numerator=2,
            retained_active_fraction_denominator=3,
            equal_voting_power=1,
        )
    )


def test_selection_is_deterministic_and_uses_equal_voting_power() -> None:
    candidates = [_candidate(f"node-{index}") for index in range(5)]
    first = _builder().build_schedule(
        candidates=candidates,
        active_validator_set={},
        activation_epoch=7,
        selection_seed="sha256:seed-7",
        eligibility_evidence_root="sha256:evidence-7",
    )
    second = _builder().build_schedule(
        candidates=list(reversed(candidates)),
        active_validator_set={},
        activation_epoch=7,
        selection_seed="sha256:seed-7",
        eligibility_evidence_root="sha256:evidence-7",
    )

    assert first.selected_node_ids == second.selected_node_ids
    assert len(first.selected_node_ids) == 3
    assert first.payload == second.payload
    assert all(item["voting_power"] == 1 for item in first.payload["validator_additions"])
    assert first.payload["candidate_selection_seed"] == "sha256:seed-7"


def test_selection_enforces_one_active_slot_per_known_control_group() -> None:
    schedule = _builder(target=4).build_schedule(
        candidates=[
            _candidate("group-a-1", kcg_id="kcg-a"),
            _candidate("group-a-2", kcg_id="kcg-a"),
            _candidate("group-b", kcg_id="kcg-b"),
            _candidate("group-c", kcg_id="kcg-c"),
        ],
        active_validator_set={},
        activation_epoch=3,
        selection_seed="sha256:seed-3",
        eligibility_evidence_root="sha256:evidence-3",
    )

    selected_groups = {
        candidate.kcg_id
        for candidate in schedule.selected_candidates
        if candidate.kcg_id is not None
    }
    assert len(schedule.selected_node_ids) == 3
    assert "kcg-a" in selected_groups
    assert len([node for node in schedule.selected_node_ids if node.startswith("group-a-")]) == 1


def test_selection_honors_explicit_bootstrap_kcg_limit() -> None:
    builder = ValidatorScheduleBuilder(
        ValidatorScheduleConfig(
            target_validator_count=3,
            minimum_stake=500,
            max_validators_per_kcg=2,
            retained_active_fraction_numerator=2,
            retained_active_fraction_denominator=3,
            equal_voting_power=1,
        )
    )
    schedule = builder.build_schedule(
        candidates=[
            _candidate("group-a-1", kcg_id="kcg-a"),
            _candidate("group-a-2", kcg_id="kcg-a"),
            _candidate("group-a-3", kcg_id="kcg-a"),
            _candidate("group-b", kcg_id="kcg-b"),
        ],
        active_validator_set={},
        activation_epoch=3,
        selection_seed="sha256:seed-bootstrap-3",
        eligibility_evidence_root="sha256:evidence-bootstrap-3",
    )

    assert len([node for node in schedule.selected_node_ids if node.startswith("group-a-")]) == 2


def test_selection_retains_two_thirds_of_eligible_incumbents_then_fills_slots() -> None:
    candidates = [_candidate(f"node-{index}") for index in range(4)]
    active = {
        f"node-{index}": {
            "consensus_public_key": candidates[index].consensus_public_key,
            "voting_power": 1,
        }
        for index in range(3)
    }

    schedule = _builder().build_schedule(
        candidates=candidates,
        active_validator_set=active,
        activation_epoch=9,
        selection_seed="sha256:seed-9",
        eligibility_evidence_root="sha256:evidence-9",
    )

    assert len(schedule.retained_node_ids) == 2
    assert len(schedule.selected_node_ids) == 3
    assert "node-3" in schedule.selected_node_ids
    assert len(schedule.payload["validator_removals"]) == 1


def test_selection_rejects_duplicate_consensus_keys() -> None:
    first = _candidate("node-1")
    duplicate = _candidate("node-2").model_copy(
        update={"consensus_public_key": first.consensus_public_key}
    )

    with pytest.raises(ValueError, match="public key"):
        _builder().build_schedule(
            candidates=[first, duplicate],
            active_validator_set={},
            activation_epoch=1,
            selection_seed="sha256:seed-1",
            eligibility_evidence_root="sha256:evidence-1",
        )


def test_ineligible_and_understaked_candidates_are_not_selected() -> None:
    schedule = _builder(target=2).build_schedule(
        candidates=[
            _candidate("inactive", eligible=False),
            _candidate("understaked", stake=499),
            _candidate("eligible-1"),
        ],
        active_validator_set={},
        activation_epoch=2,
        selection_seed="sha256:seed-2",
        eligibility_evidence_root="sha256:evidence-2",
    )

    assert schedule.selected_node_ids == ["eligible-1"]
    assert schedule.payload["validator_removals"] == []


def test_schedule_excludes_suspended_participant_and_commits_suspension_root() -> None:
    candidates = [
        _candidate("node-1", participant_id="service:node-1"),
        _candidate("node-2", participant_id="service:node-2"),
    ]
    suspensions = {
        "service:node-1": {
            "target_id": "service:node-1",
            "state": "SUSPENDED",
            "effective_epoch": 5,
            "minimum_recovery_epoch": 12,
            "reason_code": "PERSISTENT_DOWNTIME",
        }
    }

    schedule = _builder(target=2).build_schedule(
        candidates=candidates,
        active_validator_set={
            "node-1": {
                "consensus_public_key": candidates[0].consensus_public_key,
                "voting_power": 1,
            }
        },
        activation_epoch=7,
        selection_seed="sha256:seed-suspension-7",
        eligibility_evidence_root="sha256:evidence-suspension-7",
        participant_suspensions=suspensions,
    )

    assert schedule.selected_node_ids == ["node-2"]
    assert schedule.payload["participant_suspension_root"] == (
        compute_participant_suspension_root(suspensions)
    )
    assert schedule.payload["validator_removals"] == [{"node_id": "node-1"}]


def test_schedule_does_not_apply_future_suspension_before_effective_epoch() -> None:
    candidates = [_candidate("node-1", participant_id="service:node-1")]
    suspensions = {
        "service:node-1": {
            "target_id": "service:node-1",
            "state": "SUSPENDED",
            "effective_epoch": 9,
            "minimum_recovery_epoch": 16,
        }
    }

    schedule = _builder(target=1).build_schedule(
        candidates=candidates,
        active_validator_set={},
        activation_epoch=8,
        selection_seed="sha256:seed-future-suspension-8",
        eligibility_evidence_root="sha256:evidence-future-suspension-8",
        participant_suspensions=suspensions,
    )

    assert schedule.selected_node_ids == ["node-1"]


def test_schedule_wraps_into_protocol_envelope_without_local_commit() -> None:
    schedule = _builder(target=1).build_schedule(
        candidates=[_candidate("node-1")],
        active_validator_set={},
        activation_epoch=4,
        selection_seed="sha256:seed-4",
        eligibility_evidence_root="sha256:evidence-4",
    )

    envelope = schedule.to_envelope(
        created_at="2030-01-01T00:00:00Z",
        expires_at="2030-01-02T00:00:00Z",
        signatures=["ed25519:epoch-engine"],
    )

    assert envelope.operation_type == "CONSENSUS_VALIDATOR_SET_UPDATE"
    assert envelope.origin_type == "protocol"
    assert envelope.target_epoch == "4"
    assert envelope.payload == schedule.payload
    assert AdmissionValidator(current_time="2030-01-01T00:00:00Z").validate(
        envelope
    ).admitted


def test_epoch_selection_seed_is_derived_from_finalized_epoch_inputs() -> None:
    first = derive_epoch_selection_seed(
        previous_epoch_final_block_hash="sha256:block-6",
        previous_epoch_state_root="sha256:state-6",
        opening_epoch=7,
    )
    same = derive_epoch_selection_seed(
        previous_epoch_final_block_hash="sha256:block-6",
        previous_epoch_state_root="sha256:state-6",
        opening_epoch=7,
    )
    different_epoch = derive_epoch_selection_seed(
        previous_epoch_final_block_hash="sha256:block-6",
        previous_epoch_state_root="sha256:state-6",
        opening_epoch=8,
    )

    assert first == same
    assert first.startswith("sha256:")
    assert first != different_epoch


def _snapshot(
    service_id: str,
    *,
    epoch: int = 6,
    state: EligibilityState = EligibilityState.ACTIVE,
    kcg_id: str | None = None,
    has_duty_proof: bool = True,
) -> EligibilitySnapshot:
    return EligibilitySnapshot(
        epoch=epoch,
        service_id=service_id,
        state=state,
        rating_score=0.95,
        health_score=0.99,
        kcg_id=kcg_id,
        activation_age=10,
        has_duty_proof=has_duty_proof,
    )


def test_schedule_uses_finalized_eligibility_snapshot_root() -> None:
    candidates = {
        "node-1": _candidate("node-1", kcg_id="kcg-1"),
        "node-2": _candidate("node-2", kcg_id="kcg-2"),
    }
    snapshots = [
        _snapshot("node-1", kcg_id="kcg-1"),
        _snapshot("node-2", kcg_id="kcg-2", state=EligibilityState.INELIGIBLE),
    ]
    evidence_root = compute_eligibility_evidence_root(
        snapshots=snapshots,
        candidate_metadata=candidates,
    )

    schedule = _builder(target=2).build_schedule_from_eligibility_snapshots(
        snapshots=snapshots,
        candidate_metadata=candidates,
        active_validator_set={},
        activation_epoch=7,
        selection_seed="sha256:seed-7",
        eligibility_evidence_root=evidence_root,
    )

    assert schedule.selected_node_ids == ["node-1"]
    assert schedule.payload["eligibility_snapshot_epoch"] == 6
    assert schedule.payload["eligibility_evidence_root"] == evidence_root


def test_snapshot_root_is_order_independent_and_mismatch_is_rejected() -> None:
    candidates = {
        "node-1": _candidate("node-1"),
        "node-2": _candidate("node-2"),
    }
    snapshots = [_snapshot("node-1"), _snapshot("node-2")]
    evidence_root = compute_eligibility_evidence_root(
        snapshots=snapshots,
        candidate_metadata=candidates,
    )
    assert evidence_root == compute_eligibility_evidence_root(
        snapshots=list(reversed(snapshots)),
        candidate_metadata=candidates,
    )

    with pytest.raises(ValueError, match="evidence root"):
        _builder().build_schedule_from_eligibility_snapshots(
            snapshots=snapshots,
            candidate_metadata=candidates,
            active_validator_set={},
            activation_epoch=7,
            selection_seed="sha256:seed-7",
            eligibility_evidence_root="sha256:wrong",
        )


def test_schedule_rejects_snapshot_boundary_and_candidate_metadata_mismatch() -> None:
    candidates = {"node-1": _candidate("node-1")}
    snapshots = [_snapshot("node-1", epoch=5)]
    evidence_root = compute_eligibility_evidence_root(
        snapshots=snapshots,
        candidate_metadata=candidates,
    )

    with pytest.raises(ValueError, match="epoch"):
        _builder(target=1).build_schedule_from_eligibility_snapshots(
            snapshots=snapshots,
            candidate_metadata=candidates,
            active_validator_set={},
            activation_epoch=7,
            selection_seed="sha256:seed-7",
            eligibility_evidence_root=evidence_root,
        )

    with pytest.raises(ValueError, match="KCG"):
        mismatched = [_snapshot("node-1", kcg_id="kcg-1")]
        mismatch_root = compute_eligibility_evidence_root(
            snapshots=mismatched,
            candidate_metadata=candidates,
        )
        _builder(target=1).build_schedule_from_eligibility_snapshots(
            snapshots=mismatched,
            candidate_metadata=candidates,
            active_validator_set={},
            activation_epoch=7,
            selection_seed="sha256:seed-7",
            eligibility_evidence_root=mismatch_root,
        )


def test_schedule_adapter_consumes_real_eligibility_engine_snapshot() -> None:
    eligibility = EligibilityEngine()
    eligibility.register_participant(
        "node-1",
        stake=500_000_000,
        activation_epoch=1,
        reward_beneficiary="wallet-1",
    )
    eligibility.set_duty_proof("node-1", True)
    assert eligibility.evaluate_gates("node-1", current_epoch=11).eligible
    snapshot = eligibility.create_snapshot("node-1", current_epoch=11)
    assert snapshot is not None

    candidates = {"node-1": _candidate("node-1", kcg_id=snapshot.kcg_id, stake=500_000_000)}
    evidence_root = compute_eligibility_evidence_root(
        snapshots=[snapshot],
        candidate_metadata=candidates,
    )
    schedule = _builder(target=1).build_schedule_from_eligibility_snapshots(
        snapshots=[snapshot],
        candidate_metadata=candidates,
        active_validator_set={},
        activation_epoch=12,
        selection_seed="sha256:seed-12",
        eligibility_evidence_root=evidence_root,
    )

    assert schedule.selected_node_ids == ["node-1"]
    assert schedule.payload["eligibility_snapshot_epoch"] == 11
