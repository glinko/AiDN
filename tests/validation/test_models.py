import pytest
from pydantic import ValidationError

from aidn_hypervisor.endpoints.models import EndpointValidationState
from aidn_hypervisor.validation.models import (
    ValidationBond,
    ValidationReport,
    ValidationStatusSnapshot,
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


def test_endpoint_validation_state_rejects_unknown_certification_fields() -> None:
    with pytest.raises(ValidationError):
        EndpointValidationState(
            certification_status="maybe",
            validation_status="half_validated",
            latest_recommendation="shrug",
        )
