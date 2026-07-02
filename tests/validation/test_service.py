from aidn_hypervisor.validation.service import ValidationService
from aidn_hypervisor.validation.store import ValidationStore


def test_request_validation_locks_operator_bond_and_sets_pending_status() -> None:
    service = ValidationService(ValidationStore())

    result = service.request_validation(
        endpoint_id="ep-1",
        owner_wallet="wallet-1",
        configuration_hash="cfg-1",
        minimum_session_deposit_q=25.0,
    )

    assert result.request.status == "queued"
    assert result.bond.amount_q == 500.0
    assert result.bond.remaining_locked_q == 500.0
    assert result.snapshot.status == "pending_initial"


def test_submit_validation_report_with_pass_marks_validated_without_releasing_initial_bond() -> (
    None
):
    service = ValidationService(ValidationStore())
    requested = service.request_validation(
        endpoint_id="ep-1",
        owner_wallet="wallet-1",
        configuration_hash="cfg-1",
        minimum_session_deposit_q=25.0,
    )
    service.assign_epoch_requests(
        epoch_id="epoch-1",
        validator_entries=[
            {
                "validator_id": "val-1",
                "validator_label": "validator-a",
                "shares": 1,
                "capability_profiles": ["llm_text"],
                "contribution_q": 500.0,
            }
        ],
        seed="seed-1",
    )

    resolved = service.submit_validation_report(
        request_id=requested.request.request_id,
        outcome="pass",
        validator_label="validator-a",
        evidence_summary="all checks passed",
    )

    assert resolved.request.status == "passed"
    assert resolved.snapshot.status == "validated"
    assert resolved.bond.remaining_locked_q == 500.0


def test_maintenance_pass_refunds_half_of_remaining_locked_bond() -> None:
    service = ValidationService(ValidationStore())
    requested = service.request_validation(
        endpoint_id="ep-1",
        owner_wallet="wallet-1",
        configuration_hash="cfg-1",
        minimum_session_deposit_q=25.0,
    )
    service.force_mark_validated(
        request_id=requested.request.request_id,
        report_id="report-1",
        validated_at="2026-07-02T00:00:00+00:00",
    )

    outcome = service.resolve_maintenance(
        endpoint_id="ep-1",
        configuration_hash="cfg-1",
        outcome="pass",
        validator_label="validator-a",
        evidence_summary="healthy",
    )

    assert outcome.bond.remaining_locked_q == 250.0
    assert outcome.bond.released_q == 250.0
    assert outcome.snapshot.status == "validated"


def test_maintenance_fail_forfeits_remaining_locked_bond() -> None:
    service = ValidationService(ValidationStore())
    requested = service.request_validation(
        endpoint_id="ep-1",
        owner_wallet="wallet-1",
        configuration_hash="cfg-1",
        minimum_session_deposit_q=25.0,
    )
    service.force_mark_validated(
        request_id=requested.request.request_id,
        report_id="report-1",
        validated_at="2026-07-02T00:00:00+00:00",
    )

    outcome = service.resolve_maintenance(
        endpoint_id="ep-1",
        configuration_hash="cfg-1",
        outcome="fail",
        validator_label="validator-a",
        evidence_summary="latency exceeded threshold",
    )

    assert outcome.bond.status == "forfeited"
    assert outcome.bond.remaining_locked_q == 0.0
    assert outcome.bond.forfeited_q == 500.0
    assert outcome.snapshot.status == "validation_failed"
