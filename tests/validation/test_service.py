import pytest

from aidn_hypervisor.state import HypervisorStateSnapshot
from aidn_hypervisor.validation.service import ValidationService
from aidn_hypervisor.validation.store import ValidationStore


class CountingBondEscrowAdapter:
    adapter_name = "counting_bond_escrow"

    def __init__(self) -> None:
        self.lock_calls = 0

    def lock_bond(self, owner_wallet: str, amount_q: float, purpose: dict):
        del owner_wallet, amount_q, purpose
        self.lock_calls += 1
        raise AssertionError("lock_bond should not be called for invalid input")


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
    assert result.snapshot.validation_status == "pending_initial"


def test_request_validation_rejects_negative_session_deposit_before_locking_bond() -> None:
    bond_escrow = CountingBondEscrowAdapter()
    service = ValidationService(ValidationStore(), bond_escrow=bond_escrow)

    with pytest.raises(ValueError, match="minimum_session_deposit_q"):
        service.request_validation(
            endpoint_id="ep-1",
            owner_wallet="wallet-1",
            configuration_hash="cfg-1",
            minimum_session_deposit_q=-1.0,
        )

    assert bond_escrow.lock_calls == 0


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
    assert resolved.snapshot.validation_status == "validated"
    assert resolved.bond.remaining_locked_q == 500.0


def test_submit_validation_report_with_certify_with_issues_marks_certified_with_issues() -> (
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
        recommendation="certify_with_issues",
        validator_label="validator-a",
        evidence_summary="operational with warnings",
        detected_issues=[{"severity": "warning", "code": "latency_spike"}],
    )

    assert resolved.snapshot.certification_status == "certified_with_issues"
    assert resolved.snapshot.validation_status == "validated"


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
    assert outcome.snapshot.validation_status == "validated"


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
    assert outcome.snapshot.certification_status == "revoked"
    assert outcome.snapshot.validation_status == "validated"
    assert outcome.snapshot.validated_at is None


def test_maintenance_report_with_critical_issue_revokes_certification() -> None:
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
        validated_at="2026-07-09T00:00:00+00:00",
    )

    outcome = service.resolve_maintenance(
        endpoint_id="ep-1",
        configuration_hash="cfg-1",
        recommendation="do_not_certify",
        validator_label="validator-a",
        evidence_summary="accounting mismatch",
        detected_issues=[{"severity": "critical", "code": "accounting_mismatch"}],
    )
    summary = service.validation_summary("ep-1", configuration_hash="cfg-1")

    assert outcome.snapshot.certification_status == "revoked"
    assert outcome.snapshot.validation_status == "validated"
    assert summary["validation_status"] == "validation_failed"
    assert summary["current_snapshot"]["certification_status"] == "revoked"
    assert summary["current_snapshot"]["validation_status"] == "validated"
    assert "status" not in summary["current_snapshot"]


def test_assign_epoch_requests_raises_when_queued_requests_exceed_share_capacity() -> None:
    service = ValidationService(ValidationStore())
    for index in range(3):
        service.request_validation(
            endpoint_id=f"ep-{index}",
            owner_wallet=f"wallet-{index}",
            configuration_hash=f"cfg-{index}",
            minimum_session_deposit_q=25.0,
        )

    with pytest.raises(ValueError, match="share capacity"):
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


def test_assign_epoch_requests_expands_validator_shares_and_assigns_in_seed_order() -> (
    None
):
    service = ValidationService(ValidationStore())
    first = service.request_validation(
        endpoint_id="ep-1",
        owner_wallet="wallet-1",
        configuration_hash="cfg-1",
        minimum_session_deposit_q=25.0,
    )
    second = service.request_validation(
        endpoint_id="ep-2",
        owner_wallet="wallet-2",
        configuration_hash="cfg-2",
        minimum_session_deposit_q=35.0,
    )

    epoch = service.assign_epoch_requests(
        epoch_id="epoch-1",
        validator_entries=[
            {
                "validator_id": "val-a",
                "validator_label": "validator-a",
                "shares": 1,
                "capability_profiles": ["llm_text"],
                "contribution_q": 500.0,
            },
            {
                "validator_id": "val-b",
                "validator_label": "validator-b",
                "shares": 2,
                "capability_profiles": ["llm_text"],
                "contribution_q": 1000.0,
            },
        ],
        seed="seed-2",
    )

    updated_first = service.store.get_request(first.request.request_id)
    updated_second = service.store.get_request(second.request.request_id)

    assert epoch.epoch.seed == "seed-2"
    assert [item.validator_id for item in epoch.assignments] == ["val-b", "val-a"]
    assert all(item.authorization_id for item in [updated_first, updated_second])
    assert updated_first.status == "authorization_issued"
    assert updated_second.status == "authorization_issued"


def test_create_validation_epoch_assigns_queued_requests() -> None:
    service = ValidationService(ValidationStore())
    first = service.request_validation(
        endpoint_id="ep-1",
        owner_wallet="wallet-1",
        configuration_hash="cfg-1",
        minimum_session_deposit_q=25.0,
    )
    second = service.request_validation(
        endpoint_id="ep-2",
        owner_wallet="wallet-2",
        configuration_hash="cfg-2",
        minimum_session_deposit_q=30.0,
    )

    epoch = service.create_validation_epoch(
        epoch_id="epoch-1",
        seed="seed-2",
        validator_entries=[
            {
                "validator_id": "val-a",
                "validator_label": "validator-a",
                "shares": 1,
                "capability_profiles": ["llm_text"],
                "contribution_q": 500.0,
            },
            {
                "validator_id": "val-b",
                "validator_label": "validator-b",
                "shares": 2,
                "capability_profiles": ["llm_text"],
                "contribution_q": 1000.0,
            },
        ],
    )

    assert epoch.epoch.seed == "seed-2"
    assert len(epoch.assignments) == 2
    assert (
        service.store.get_request(first.request.request_id).status
        == "authorization_issued"
    )
    assert (
        service.store.get_request(second.request.request_id).status
        == "authorization_issued"
    )


def test_validation_summary_returns_spec_required_fields() -> None:
    service = ValidationService(ValidationStore())
    requested = service.request_validation(
        endpoint_id="ep-1",
        owner_wallet="wallet-1",
        configuration_hash="cfg-1",
        minimum_session_deposit_q=25.0,
    )

    summary = service.validation_summary("ep-1")

    assert summary["endpoint_id"] == "ep-1"
    assert summary["configuration_hash"] == "cfg-1"
    assert summary["validation_status"] == "pending_initial"
    assert summary["latest_request_id"] == requested.request.request_id
    assert summary["latest_report_id"] is None
    assert summary["bond_state"]["bond_id"] == requested.bond.bond_id
    assert summary["bond_state"]["status"] == "locked"
    assert summary["validated_at"] is None
    assert summary["superseded_at"] is None


def test_supersede_configuration_marks_old_snapshot_superseded_and_new_hash_unvalidated() -> (
    None
):
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

    service.supersede_configuration(
        endpoint_id="ep-1",
        previous_configuration_hash="cfg-1",
        replacement_configuration_hash="cfg-2",
        superseded_at="2026-07-02T01:00:00+00:00",
    )

    old_summary = service.validation_summary("ep-1", configuration_hash="cfg-1")
    new_summary = service.validation_summary("ep-1", configuration_hash="cfg-2")

    assert old_summary["validation_status"] == "superseded"
    assert old_summary["superseded_at"] == "2026-07-02T01:00:00+00:00"
    assert old_summary["latest_request_id"] == requested.request.request_id
    assert new_summary["configuration_hash"] == "cfg-2"
    assert new_summary["validation_status"] == "unvalidated"
    assert new_summary["latest_request_id"] is None
    assert new_summary["bond_state"] is None


def test_authorization_hides_validator_wallet_and_share_count() -> None:
    service = ValidationService(ValidationStore())
    requested = service.request_validation(
        endpoint_id="ep-1",
        owner_wallet="wallet-1",
        configuration_hash="cfg-1",
        minimum_session_deposit_q=40.0,
    )

    epoch = service.assign_epoch_requests(
        epoch_id="epoch-1",
        validator_entries=[
            {
                "validator_id": "val-a",
                "validator_label": "validator-a",
                "shares": 3,
                "capability_profiles": ["llm_text"],
                "contribution_q": 1500.0,
            }
        ],
        seed="seed-2",
    )

    authorization = epoch.authorizations[0]
    authorization_payload = authorization.model_dump(mode="json")

    assert requested.request.request_id == epoch.assignments[0].request_id
    assert authorization.guarantee_q == 40.0
    assert authorization.status == "issued"
    assert "val-a" not in authorization.authorization_token
    assert set(authorization_payload) == {
        "authorization_id",
        "request_id",
        "epoch_id",
        "authorization_token",
        "guarantee_q",
        "issued_at",
        "expires_at",
        "status",
    }
    assert "validator_id" not in authorization_payload
    assert "validator_wallet" not in authorization_payload
    assert "shares" not in authorization_payload


def test_restore_round_trip_then_assign_epoch_requests_succeeds() -> None:
    service = ValidationService(ValidationStore())
    requested = service.request_validation(
        endpoint_id="ep-1",
        owner_wallet="wallet-1",
        configuration_hash="cfg-1",
        minimum_session_deposit_q=25.0,
    )
    snapshot = HypervisorStateSnapshot(
        validation_requests=service.store.list_requests(),
        validation_bonds=service.store.list_bonds(),
        validation_reports=service.store.list_reports(),
        validation_status_snapshots=service.store.list_snapshots(),
    )
    restored = ValidationStore()
    restored.restore(snapshot)
    restored_service = ValidationService(restored)

    assigned = restored_service.assign_epoch_requests(
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

    updated_request = restored.get_request(requested.request.request_id)

    assert len(assigned.assignments) == 1
    assert len(assigned.authorizations) == 1
    assert assigned.authorizations[0].guarantee_q == 25.0
    assert updated_request.status == "authorization_issued"


def test_submit_validation_report_on_unassigned_request_raises() -> None:
    service = ValidationService(ValidationStore())
    requested = service.request_validation(
        endpoint_id="ep-1",
        owner_wallet="wallet-1",
        configuration_hash="cfg-1",
        minimum_session_deposit_q=25.0,
    )

    with pytest.raises(ValueError, match="authorization_issued"):
        service.submit_validation_report(
            request_id=requested.request.request_id,
            outcome="pass",
            validator_label="validator-a",
            evidence_summary="all checks passed",
        )


def test_duplicate_terminal_validation_report_submission_raises() -> None:
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
    service.submit_validation_report(
        request_id=requested.request.request_id,
        outcome="pass",
        validator_label="validator-a",
        evidence_summary="all checks passed",
    )

    with pytest.raises(ValueError, match="terminal"):
        service.submit_validation_report(
            request_id=requested.request.request_id,
            outcome="pass",
            validator_label="validator-a",
            evidence_summary="duplicate report",
        )


def test_resolve_maintenance_before_validation_raises() -> None:
    service = ValidationService(ValidationStore())
    service.request_validation(
        endpoint_id="ep-1",
        owner_wallet="wallet-1",
        configuration_hash="cfg-1",
        minimum_session_deposit_q=25.0,
    )

    with pytest.raises(ValueError, match="validated"):
        service.resolve_maintenance(
            endpoint_id="ep-1",
            configuration_hash="cfg-1",
            outcome="pass",
            validator_label="validator-a",
            evidence_summary="healthy",
        )
