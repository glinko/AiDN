import pytest
from pydantic import ValidationError

from aidn_hypervisor.endpoints.models import EndpointValidationState
from aidn_hypervisor.validation.models import (
    ValidationBond,
    ValidationReport,
    ValidationReportCommitment,
    ValidationStatusSnapshot,
    validation_report_integrity,
)


def test_validation_bond_preserves_balanced_totals() -> None:
    bond = ValidationBond(
        bond_id="bond-1",
        owner_wallet="wallet-1",
        endpoint_id="ep-1",
        configuration_hash="cfg-1",
        amount_q=500.0,
        remaining_locked_q=500.0,
        released_q=0.0,
        forfeited_q=0.0,
        escrow_adapter="adapter-1",
        escrow_reference="escrow-1",
        status="locked",
    )

    assert bond.amount_q == 500.0
    assert bond.remaining_locked_q == 500.0
    assert bond.released_q == 0.0
    assert bond.forfeited_q == 0.0

def test_validation_bond_accepts_balanced_fractional_totals() -> None:
    bond = ValidationBond(
        bond_id="bond-1",
        owner_wallet="wallet-1",
        endpoint_id="ep-1",
        configuration_hash="cfg-1",
        amount_q=0.6,
        remaining_locked_q=0.1,
        released_q=0.2,
        forfeited_q=0.3,
        escrow_adapter="adapter-1",
        escrow_reference="escrow-1",
        status="locked",
    )

    assert bond.amount_q == 0.6
    assert bond.remaining_locked_q == 0.1
    assert bond.released_q == 0.2
    assert bond.forfeited_q == 0.3


def test_validation_bond_accepts_balanced_fractional_totals() -> None:
    bond = ValidationBond(
        bond_id="bond-1",
        owner_wallet="wallet-1",
        endpoint_id="ep-1",
        configuration_hash="cfg-1",
        amount_q=0.6,
        remaining_locked_q=0.1,
        released_q=0.2,
        forfeited_q=0.3,
        escrow_adapter="adapter-1",
        escrow_reference="escrow-1",
        status="locked",
    )

    assert bond.amount_q == 0.6
    assert bond.remaining_locked_q == 0.1
    assert bond.released_q == 0.2
    assert bond.forfeited_q == 0.3


def test_validation_status_snapshot_requires_request_for_validated_status() -> None:
    with pytest.raises(ValidationError):
        ValidationStatusSnapshot(
            endpoint_id="ep-1",
            configuration_hash="cfg-1",
            validation_status="validated",
            latest_request_id=None,
            latest_report_id="report-1",
        )


def test_validation_status_snapshot_rejects_blank_request_for_validated_status() -> None:
    with pytest.raises(ValidationError):
        ValidationStatusSnapshot(
            endpoint_id="ep-1",
            configuration_hash="cfg-1",
            validation_status="validated",
            latest_request_id="",
            latest_report_id="report-1",
        )


def test_validation_status_snapshot_accepts_certified_with_issues() -> None:
    snapshot = ValidationStatusSnapshot(
        endpoint_id="ep-1",
        configuration_hash="cfg-1",
        certification_status="certified_with_issues",
        latest_request_id="req-1",
        latest_report_id="report-1",
    )

    assert snapshot.certification_status == "certified_with_issues"
    assert snapshot.validation_status == "validated"


def test_validation_status_snapshot_rejects_contradictory_certification_pair() -> None:
    with pytest.raises(ValidationError):
        ValidationStatusSnapshot(
            endpoint_id="ep-1",
            configuration_hash="cfg-1",
            certification_status="certified",
            validation_status="pending_initial",
            latest_request_id="req-1",
        )


def test_validation_report_requires_recommendation_and_issue_counts() -> None:
    report = ValidationReport(
        report_id="report-1",
        request_id="req-1",
        endpoint_id="ep-1",
        configuration_hash="cfg-1",
        report_kind="initial",
        validator_label="validator-a",
        recommendation="certify_with_issues",
        critical_issue_count=0,
        warning_issue_count=2,
        evidence_summary="operational with warnings",
        created_at="2026-07-09T00:00:00+00:00",
    )

    assert report.recommendation == "certify_with_issues"
    assert report.warning_issue_count == 2


def test_validation_report_rejects_unstructured_issue_rows() -> None:
    with pytest.raises(ValidationError):
        ValidationReport(
            report_id="report-1",
            request_id="req-1",
            endpoint_id="ep-1",
            configuration_hash="cfg-1",
            report_kind="initial",
            validator_label="validator-a",
            recommendation="certify_with_issues",
            critical_issue_count=0,
            warning_issue_count=1,
            detected_issues=[{"issue_id": "issue-1", "details": {"nested": {"bad": "nope"}}}],
            evidence_summary="operational with warnings",
            created_at="2026-07-09T00:00:00+00:00",
        )


def test_validation_report_integrity_ignores_local_id_and_signature_wrapper() -> None:
    base = {
        "request_id": "req-1",
        "endpoint_id": "ep-1",
        "configuration_hash": "cfg-1",
        "report_kind": "initial",
        "validator_label": "validator-a",
        "recommendation": "certify",
        "evidence_summary": "all checks passed",
        "created_at": "2026-07-18T00:00:00+00:00",
        "measured_metrics": {"latency_ms": 20, "success": True},
    }
    first = ValidationReport(
        report_id="report-1",
        signed_payload={"signature": "one"},
        **base,
    )
    second = ValidationReport(
        report_id="report-2",
        signed_payload={"signature": "two"},
        **base,
    )

    assert validation_report_integrity(first) == validation_report_integrity(second)


def test_validation_report_commitment_rejects_receipt_and_failure_together() -> None:
    with pytest.raises(ValidationError, match="mutually exclusive"):
        ValidationReportCommitment(
            commitment_id="vcommit-1",
            report_id="report-1",
            report_hash="sha256:" + "a" * 64,
            report_size=10,
            request_id="req-1",
            endpoint_id="ep-1",
            configuration_hash="cfg-1",
            conclusion="certify",
            evidence_root="sha256:" + "b" * 64,
            report_locator="aidn://endpoint/ep-1/validation/test",
            storage_receipt_hash="sha256:" + "c" * 64,
            storage_failure_reference="failure-1",
            created_at="2026-07-18T00:00:00+00:00",
        )


def test_endpoint_validation_state_rejects_unknown_certification_fields() -> None:
    with pytest.raises(ValidationError):
        EndpointValidationState(
            certification_status="maybe",
            validation_status="half_validated",
            latest_recommendation="shrug",
        )


def test_endpoint_validation_state_rejects_contradictory_certification_pair() -> None:
    with pytest.raises(ValidationError):
        EndpointValidationState(
            certification_status="certified_with_issues",
            validation_status="unvalidated",
        )


def test_endpoint_validation_state_requires_request_for_validated_status() -> None:
    with pytest.raises(ValidationError):
        EndpointValidationState(
            certification_status="certified",
            validation_status="validated",
            latest_request_id=None,
            latest_report_id="report-1",
        )
