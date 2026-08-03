"""Tests for the explicit Validation custody to Reputation projection."""

from __future__ import annotations

import pytest

from aidn_hypervisor.reputation_engine.engine import ReputationEngine
from aidn_hypervisor.reputation_engine.store import ReputationStore
from aidn_hypervisor.validation.custody_reputation import CustodyReputationAdapter
from aidn_hypervisor.validation.models import ValidationReportCustodyChallenge


def _challenge(
    *,
    outcome: str = "available",
    challenge_id: str = "challenge-1",
) -> ValidationReportCustodyChallenge:
    return ValidationReportCustodyChallenge(
        challenge_id=challenge_id,
        report_id="report-1",
        report_hash="sha256:" + "ab" * 32,
        endpoint_id="endpoint-1",
        configuration_hash="config-1",
        challenger_id="validator-1",
        requested_at="2026-08-02T00:00:00+00:00",
        checked_at="2026-08-02T00:01:00+00:00",
        outcome=outcome,
        observed_report_size=42 if outcome == "available" else None,
        evidence_root="sha256:" + "cd" * 32,
        independence_key="subject:validator-1",
    )


def _summary(challenge: ValidationReportCustodyChallenge) -> dict:
    return {
        "report_id": challenge.report_id,
        "report_hash": challenge.report_hash,
        "quorum_required": 2,
        "independent_observation_count": 2,
        "quorum_state": "confirmed",
    }


def test_projection_is_opt_in_and_does_not_create_profile() -> None:
    engine = ReputationEngine(ReputationStore())
    adapter = CustodyReputationAdapter(engine)

    projection = adapter.project_challenge(_challenge())

    assert len(projection.events) == 3
    assert {event.profile_dimension for event in projection.events} == {
        "VALIDATION_REPORT_AVAILABILITY",
        "VALIDATION_REPORT_RETENTION",
        "VALIDATION_REPORT_INTEGRITY",
    }
    assert engine.get_profile("ENDPOINT", "endpoint-1") is None


@pytest.mark.parametrize(
    ("outcome", "dimensions", "severity"),
    [
        (
            "temporarily_unavailable",
            {"VALIDATION_REPORT_AVAILABILITY"},
            "MINOR",
        ),
        (
            "lost",
            {"VALIDATION_REPORT_AVAILABILITY", "VALIDATION_REPORT_RETENTION"},
            "MAJOR",
        ),
        (
            "corrupted",
            {"VALIDATION_REPORT_INTEGRITY"},
            "CRITICAL",
        ),
        (
            "withheld",
            {"VALIDATION_REPORT_AVAILABILITY", "VALIDATION_DISCLOSURE_RELIABILITY"},
            "MAJOR",
        ),
        (
            "access_restricted",
            {"VALIDATION_DISCLOSURE_RELIABILITY"},
            "MAJOR",
        ),
    ],
)
def test_projection_maps_custody_outcomes(
    outcome: str,
    dimensions: set[str],
    severity: str,
) -> None:
    projection = CustodyReputationAdapter().project_challenge(
        _challenge(outcome=outcome, challenge_id=f"challenge-{outcome}")
    )

    assert {event.profile_dimension for event in projection.events} == dimensions
    assert {event.severity for event in projection.events} == {severity}
    assert all(event.direction == "NEGATIVE" for event in projection.events)


def test_confirmed_quorum_uses_multi_source_confidence() -> None:
    challenge = _challenge()
    projection = CustodyReputationAdapter().project_challenge(
        challenge,
        quorum_summary=_summary(challenge),
    )

    assert projection.quorum_state == "confirmed"
    assert all(event.evidence_confidence == "MULTI_SOURCE" for event in projection.events)


def test_apply_is_explicit_and_idempotent() -> None:
    engine = ReputationEngine(ReputationStore())
    adapter = CustodyReputationAdapter(engine)
    challenge = _challenge(outcome="corrupted")

    first = adapter.apply_challenge(challenge)
    second = adapter.apply_challenge(challenge)

    assert first.applied_event_ids == second.applied_event_ids
    assert engine.get_event_history("ENDPOINT", "endpoint-1")
    assert len(engine.get_event_history("ENDPOINT", "endpoint-1")) == 1


def test_quorum_summary_is_scope_bound() -> None:
    challenge = _challenge()
    summary = _summary(challenge)
    summary["report_hash"] = "sha256:" + "ef" * 32

    with pytest.raises(ValueError, match="hash does not match"):
        CustodyReputationAdapter().project_challenge(
            challenge,
            quorum_summary=summary,
        )
