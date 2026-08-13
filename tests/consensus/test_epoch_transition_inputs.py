from __future__ import annotations

import json

import pytest

from aidn_hypervisor.consensus.abci import AIDNABCIApplication
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
    )

    assert report.status == "READY"
    payload = report.transition_payload(protocol_authority_policy_hash="sha256:policy")
    assert payload["closing_epoch"] == 20
    assert payload["pool_budgets"] == {"GENERAL_DEVELOPMENT": 250_000}
    assert payload["protocol_authority_policy_hash"] == "sha256:policy"


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
