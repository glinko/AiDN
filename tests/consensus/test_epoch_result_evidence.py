from __future__ import annotations

import pytest

from aidn_hypervisor.consensus.epoch_result_evidence import (
    CONTROLLED_LOCALNET_ECO_0005,
    CONTROLLED_LOCALNET_NO_WORK,
    ControlledLocalnetEco0005Profile,
    EpochResultEvidenceBundle,
    build_controlled_localnet_eco0005_evidence,
    build_controlled_localnet_eco0005_profile,
    build_controlled_localnet_no_work_evidence,
    build_manifest_from_evidence,
)
from aidn_hypervisor.consensus.epoch_transition_inputs import (
    build_epoch_transition_input_report,
)


def _report():
    return build_epoch_transition_input_report(
        closing_epoch=0,
        opening_epoch=1,
        closing_height=100,
        closing_block_hash="sha256:block",
        closing_state_root="sha256:state",
        source_app_hash="sha256:app",
        epoch_schedule_version="aidn.epoch-schedule.v1",
        epoch_schedule_hash="sha256:schedule",
        epoch_schedule_commit_operation_id="schedule-op",
        epoch_schedule_commit_sequence_id=1,
        epoch_schedule_commit_record_digest="schedule-record",
        canonical_block_time="2026-08-13T00:01:00Z",
        scheduled_end_time="2026-08-13T00:01:00Z",
        epoch_boundary_reached=True,
        additional_missing_inputs=(
            "epoch_task_result_root",
            "eligibility_snapshot_root",
            "reward_calculation_root",
            "next_protocol_parameters_hash",
            "epoch_result_manifest",
            "pool_budgets",
        ),
    )


def _schedule():
    return {
        "schema_version": "aidn.epoch-schedule.v1",
        "schedule_hash": "sha256:schedule",
        "epoch_duration_seconds": 60,
        "protocol_version": "0.1-controlled-localnet",
        "parameter_version": "controlled-localnet-parameters-v1",
        "task_set_version": "controlled-localnet-task-set-v1",
    }


def test_controlled_no_work_bundle_is_hash_bound_and_zero_budget() -> None:
    bundle = build_controlled_localnet_no_work_evidence(
        report=_report(),
        network_id="aidn-localnet-1",
        chain_id="chain-test",
        start_height=40,
        start_time="2026-08-13T00:00:00Z",
        epoch_schedule=_schedule(),
    )

    assert bundle.source_kind == CONTROLLED_LOCALNET_NO_WORK
    assert bundle.pool_budgets == {"GENERAL_DEVELOPMENT": 0}
    assert bundle.verify_integrity()
    assert EpochResultEvidenceBundle.model_validate(bundle.model_dump()).bundle_hash == bundle.bundle_hash


def test_manifest_is_bound_to_the_observed_boundary() -> None:
    bundle = build_controlled_localnet_no_work_evidence(
        report=_report(),
        network_id="aidn-localnet-1",
        chain_id="chain-test",
        start_height=40,
        start_time="2026-08-13T00:00:00Z",
        epoch_schedule=_schedule(),
    )

    manifest = build_manifest_from_evidence(bundle, _report())
    assert manifest.epoch_number == 0
    assert manifest.closing_height == 100
    assert manifest.pool_budgets == {"GENERAL_DEVELOPMENT": 0}


def test_controlled_eco0005_profile_derives_the_fixed_development_budget() -> None:
    profile = build_controlled_localnet_eco0005_profile(
        network_id="aidn-localnet-1",
        chain_id="chain-test",
        effective_epoch=0,
        epoch_schedule_hash="sha256:schedule",
        authority_policy_hash="sha256:authority",
        source_document="docs/product/ECO-0005.md",
        source_document_version="0.3",
        source_document_hash="sha256:eco0005",
    )
    bundle = build_controlled_localnet_eco0005_evidence(
        report=_report(),
        profile=profile,
        start_height=40,
        start_time="2026-08-13T00:00:00Z",
        epoch_schedule=_schedule(),
    )

    assert bundle.source_kind == CONTROLLED_LOCALNET_ECO_0005
    assert bundle.pool_budgets == {"GENERAL_DEVELOPMENT": 250_000_000}
    assert bundle.verify_integrity()
    assert any(item.startswith("controlled-localnet:eco-0005:") for item in bundle.source_references)


def test_controlled_eco0005_profile_rejects_unapproved_pool_inputs() -> None:
    profile = build_controlled_localnet_eco0005_profile(
        network_id="aidn-localnet-1",
        chain_id="chain-test",
        effective_epoch=0,
        epoch_schedule_hash="sha256:schedule",
        authority_policy_hash="sha256:authority",
        source_document="docs/product/ECO-0005.md",
        source_document_version="0.3",
        source_document_hash="sha256:eco0005",
    )

    with pytest.raises(ValueError, match="CONTROLLED_LOCALNET_ECO_0005_UNAPPROVED_POOL_INPUT"):
        ControlledLocalnetEco0005Profile.model_validate(
            profile.model_dump(mode="json") | {"carryover_in_q_atoms": 1}
        )


def test_no_work_builder_rejects_unrelated_missing_inputs() -> None:
    report = build_epoch_transition_input_report(
        closing_epoch=0,
        opening_epoch=1,
        closing_height=100,
        closing_block_hash="sha256:block",
        closing_state_root="sha256:state",
        source_app_hash="sha256:app",
        epoch_schedule_version="aidn.epoch-schedule.v1",
        epoch_schedule_hash="sha256:schedule",
        canonical_block_time="2026-08-13T00:01:00Z",
        scheduled_end_time="2026-08-13T00:01:00Z",
        epoch_boundary_reached=True,
        additional_missing_inputs=("epoch_schedule_commit_operation",),
    )

    try:
        build_controlled_localnet_no_work_evidence(
            report=report,
            network_id="aidn-localnet-1",
            chain_id="chain-test",
            start_height=40,
            start_time="2026-08-13T00:00:00Z",
            epoch_schedule=_schedule(),
        )
    except ValueError as error:
        assert str(error) == "EPOCH_RESULT_EVIDENCE_REPORT_HAS_UNSUPPORTED_MISSING_INPUTS"
    else:
        raise AssertionError("expected unsupported missing input rejection")
