from __future__ import annotations

import json

import pytest

from aidn_hypervisor.consensus.abci import AIDNABCIApplication
from aidn_hypervisor.consensus.epoch_schedule import build_epoch_schedule
from aidn_hypervisor.consensus.epoch_transition_inputs import (
    EPOCH_TRANSITION_INPUTS_NOT_READY,
    EpochTransitionInputReport,
    build_epoch_transition_input_report,
)
from aidn_hypervisor.ledger.service import LedgerOperationService


def test_report_is_blocked_without_epoch_engine_artifacts() -> None:
    report = build_epoch_transition_input_report(
        closing_height=10,
        closing_block_hash="sha256:block",
        closing_state_root="sha256:state",
        source_app_hash="sha256:app",
    )

    assert report.status == "BLOCKED"
    assert report.reason_code == EPOCH_TRANSITION_INPUTS_NOT_READY
    assert "closing_epoch" in report.missing_inputs
    assert "epoch_task_result_root" in report.missing_inputs
    assert report.report_hash.startswith("sha256:")


def test_ready_report_can_build_transition_payload() -> None:
    schedule = build_epoch_schedule(
        genesis_start_time="2030-01-01T00:00:00Z",
        epoch_duration_seconds=60,
        parameter_version="params-v1",
        task_set_version="tasks-v1",
        protocol_version="0.1",
    )
    report = build_epoch_transition_input_report(
        closing_epoch=20,
        opening_epoch=21,
        closing_height=200,
        closing_block_hash="sha256:block",
        closing_state_root="sha256:state",
        epoch_task_result_root="sha256:tasks",
        eligibility_snapshot_root="sha256:eligibility",
        reward_calculation_root="sha256:rewards",
        next_protocol_parameters_hash="sha256:params",
        pool_budgets={"GENERAL_DEVELOPMENT": 250_000},
        pool_budget_references={"GENERAL_DEVELOPMENT": "epoch:20:GENERAL_DEVELOPMENT"},
        source_app_hash="sha256:app",
        epoch_schedule_version=schedule.schema_version,
        epoch_schedule_hash=schedule.schedule_hash,
        canonical_block_time="2030-01-01T00:01:00Z",
        scheduled_end_time="2030-01-01T00:01:00Z",
        epoch_boundary_reached=True,
    )

    assert report.status == "READY"
    payload = report.transition_payload(protocol_authority_policy_hash="sha256:policy")
    assert payload["closing_epoch"] == 20
    assert payload["pool_budgets"] == {"GENERAL_DEVELOPMENT": 250_000}
    assert payload["epoch_schedule_hash"] == schedule.schedule_hash
    assert payload["canonical_block_time"] == "2030-01-01T00:01:00Z"
    assert payload["next_epoch_start_time"] == "2030-01-01T00:01:00Z"
    assert payload["protocol_authority_policy_hash"] == "sha256:policy"


def test_transition_payload_binds_finalized_schedule_reference() -> None:
    report = build_epoch_transition_input_report(
        closing_epoch=20,
        opening_epoch=21,
        closing_height=200,
        closing_block_hash="sha256:block",
        closing_state_root="sha256:state",
        epoch_task_result_root="sha256:tasks",
        eligibility_snapshot_root="sha256:eligibility",
        reward_calculation_root="sha256:rewards",
        next_protocol_parameters_hash="sha256:params",
        pool_budgets={"GENERAL_DEVELOPMENT": 250_000},
        pool_budget_references={"GENERAL_DEVELOPMENT": "epoch:20:GENERAL_DEVELOPMENT"},
        source_app_hash="sha256:app",
        epoch_schedule_version="aidn.epoch-schedule.v1",
        epoch_schedule_hash="sha256:schedule",
        epoch_schedule_commit_operation_id="schedule-operation-1",
        epoch_schedule_commit_sequence_id=3,
        epoch_schedule_commit_record_digest="sha256:schedule-record",
        canonical_block_time="2030-01-01T00:01:00Z",
        scheduled_end_time="2030-01-01T00:01:00Z",
        epoch_boundary_reached=True,
    )

    payload = report.transition_payload(protocol_authority_policy_hash="sha256:policy")

    assert payload["epoch_schedule_commit_operation_id"] == "schedule-operation-1"
    assert payload["epoch_schedule_commit_sequence_id"] == 3
    assert payload["epoch_schedule_commit_record_digest"] == "sha256:schedule-record"


def test_blocked_report_cannot_be_used_as_transition_payload() -> None:
    report = build_epoch_transition_input_report(source_app_hash="sha256:app")
    with pytest.raises(ValueError, match="EPOCH_TRANSITION_INPUTS_NOT_READY"):
        report.transition_payload(protocol_authority_policy_hash="sha256:policy")


def test_report_hash_is_verified() -> None:
    report = build_epoch_transition_input_report(source_app_hash="sha256:app")
    with pytest.raises(ValueError, match="hash does not match"):
        EpochTransitionInputReport.model_validate(
            {**report.model_dump(mode="json"), "report_hash": "sha256:" + "0" * 64}
        )


def test_abci_query_reports_observed_state_without_inventing_roots() -> None:
    app = AIDNABCIApplication(ledger_service=LedgerOperationService())
    app.finalize_block(block_height=1, block_hash=b"b" * 32, txs=[])

    response = app.query(path="epoch/transition-inputs")
    report = json.loads(response.value.decode("utf-8"))

    assert report["status"] == "BLOCKED"
    assert report["closing_height"] == 1
    assert report["closing_state_root"].startswith("sha256:")
    assert report["epoch_task_result_root"] is None
    assert "eligibility_snapshot_root" in report["missing_inputs"]


def test_abci_schedule_reports_epoch_boundary_from_canonical_block_time() -> None:
    app = AIDNABCIApplication(
        ledger_service=LedgerOperationService(),
        epoch_schedule=build_epoch_schedule(
            genesis_start_time="2030-01-01T00:00:00Z",
            epoch_duration_seconds=60,
            parameter_version="params-v1",
            task_set_version="tasks-v1",
            protocol_version="0.1",
        ),
    )
    app.finalize_block(
        block_height=60,
        block_hash=b"c" * 32,
        txs=[],
        time="2030-01-01T00:01:00Z",
    )

    report = app.epoch_transition_input_report()
    assert report["closing_epoch"] == 0
    assert report["opening_epoch"] == 1
    assert report["epoch_boundary_reached"] is True
    assert report["epoch_schedule_hash"].startswith("sha256:")
    assert "epoch_boundary" not in report["missing_inputs"]


def test_schedule_and_canonical_block_time_survive_snapshot() -> None:
    schedule = build_epoch_schedule(
        genesis_start_time="2030-01-01T00:00:00Z",
        epoch_duration_seconds=60,
        parameter_version="params-v1",
        task_set_version="tasks-v1",
        protocol_version="0.1",
    )
    source = AIDNABCIApplication(
        ledger_service=LedgerOperationService(),
        epoch_schedule=schedule,
    )
    source.finalize_block(
        block_height=1,
        block_hash=b"d" * 32,
        txs=[],
        time="2030-01-01T00:01:00Z",
    )

    restored = AIDNABCIApplication(ledger_service=LedgerOperationService())
    assert restored.apply_snapshot(source.prepare_snapshot()).code == "ok"
    report = restored.epoch_transition_input_report()
    assert report["epoch_schedule_hash"] == schedule.schedule_hash
    assert report["canonical_block_time"] == "2030-01-01T00:01:00Z"


def test_snapshot_rejects_a_different_configured_epoch_schedule() -> None:
    source_schedule = build_epoch_schedule(
        genesis_start_time="2030-01-01T00:00:00Z",
        epoch_duration_seconds=60,
        parameter_version="params-v1",
        task_set_version="tasks-v1",
        protocol_version="0.1",
    )
    destination_schedule = build_epoch_schedule(
        genesis_start_time="2030-01-01T00:00:00Z",
        epoch_duration_seconds=120,
        parameter_version="params-v1",
        task_set_version="tasks-v1",
        protocol_version="0.1",
    )
    source = AIDNABCIApplication(
        ledger_service=LedgerOperationService(),
        epoch_schedule=source_schedule,
    )
    destination = AIDNABCIApplication(
        ledger_service=LedgerOperationService(),
        epoch_schedule=destination_schedule,
    )

    result = destination.apply_snapshot(source.prepare_snapshot())

    assert result.code == "internal"
    assert "does not match configured schedule" in result.log
