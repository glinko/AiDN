"""Opt-in Reputation projection for Validation Report custody evidence.

Custody checks are evidence-producing operations. This adapter deliberately
keeps the policy boundary explicit: constructing a projection never changes
Certification, Settlement, Q or Reputation. Callers must invoke
``apply_challenge`` with an injected ReputationEngine when they want to turn
the projection into Reputation events.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aidn_hypervisor.reputation_engine.engine import ReputationEngine
from aidn_hypervisor.reputation_engine.models import ReputationEvent
from aidn_hypervisor.validation.models import (
    ValidationCustodyChallengeOutcome,
    ValidationReportCustodyChallenge,
    canonical_validation_hash,
)


@dataclass(frozen=True)
class CustodyReputationProjection:
    """Deterministic, unapplied Reputation evidence for one challenge."""

    challenge_id: str
    report_id: str
    report_hash: str
    endpoint_id: str
    outcome: ValidationCustodyChallengeOutcome
    quorum_state: str
    independent_observation_count: int
    required_quorum: int
    events: tuple[ReputationEvent, ...]

    @property
    def applied_event_ids(self) -> tuple[str, ...]:
        """Return stable event identities without exposing mutable engine state."""
        return tuple(event.event_id for event in self.events)


@dataclass(frozen=True)
class _EventSpec:
    dimension: str
    event_class: str
    direction: str
    severity: str


_OUTCOME_EVENT_SPECS: dict[ValidationCustodyChallengeOutcome, tuple[_EventSpec, ...]] = {
    "available": (
        _EventSpec(
            dimension="VALIDATION_REPORT_AVAILABILITY",
            event_class="AVAILABILITY_EVENT",
            direction="POSITIVE",
            severity="MINOR",
        ),
        _EventSpec(
            dimension="VALIDATION_REPORT_RETENTION",
            event_class="EVIDENCE_EVENT",
            direction="POSITIVE",
            severity="MINOR",
        ),
        _EventSpec(
            dimension="VALIDATION_REPORT_INTEGRITY",
            event_class="EVIDENCE_EVENT",
            direction="POSITIVE",
            severity="MINOR",
        ),
    ),
    "temporarily_unavailable": (
        _EventSpec(
            dimension="VALIDATION_REPORT_AVAILABILITY",
            event_class="AVAILABILITY_EVENT",
            direction="NEGATIVE",
            severity="MINOR",
        ),
    ),
    "withheld": (
        _EventSpec(
            dimension="VALIDATION_REPORT_AVAILABILITY",
            event_class="AVAILABILITY_EVENT",
            direction="NEGATIVE",
            severity="MAJOR",
        ),
        _EventSpec(
            dimension="VALIDATION_DISCLOSURE_RELIABILITY",
            event_class="PROTOCOL_EVENT",
            direction="NEGATIVE",
            severity="MAJOR",
        ),
    ),
    "lost": (
        _EventSpec(
            dimension="VALIDATION_REPORT_AVAILABILITY",
            event_class="AVAILABILITY_EVENT",
            direction="NEGATIVE",
            severity="MAJOR",
        ),
        _EventSpec(
            dimension="VALIDATION_REPORT_RETENTION",
            event_class="EVIDENCE_EVENT",
            direction="NEGATIVE",
            severity="MAJOR",
        ),
    ),
    "corrupted": (
        _EventSpec(
            dimension="VALIDATION_REPORT_INTEGRITY",
            event_class="EVIDENCE_EVENT",
            direction="NEGATIVE",
            severity="CRITICAL",
        ),
    ),
    "access_restricted": (
        _EventSpec(
            dimension="VALIDATION_DISCLOSURE_RELIABILITY",
            event_class="PROTOCOL_EVENT",
            direction="NEGATIVE",
            severity="MAJOR",
        ),
    ),
}


class CustodyReputationAdapter:
    """Project and optionally apply custody observations to Endpoint Reputation.

    The adapter does not subscribe to Validation events and is not called by
    ``ValidationService``. This prevents a local observation from silently
    changing a protocol reputation profile. A caller can inject a
    ``ReputationEngine`` and explicitly call ``apply_challenge``.
    """

    SOURCE_TYPE = "validation_report_custody"

    def __init__(self, engine: ReputationEngine | None = None) -> None:
        self.engine = engine

    def project_challenge(
        self,
        challenge: ValidationReportCustodyChallenge,
        *,
        quorum_summary: dict[str, Any] | None = None,
    ) -> CustodyReputationProjection:
        """Build deterministic Reputation events without ingesting them."""
        quorum = self._normalize_quorum_summary(challenge, quorum_summary)
        confidence = self._confidence_for(challenge.outcome, quorum)
        events = tuple(
            self._build_event(
                challenge=challenge,
                spec=spec,
                evidence_confidence=confidence,
            )
            for spec in _OUTCOME_EVENT_SPECS[challenge.outcome]
        )
        return CustodyReputationProjection(
            challenge_id=challenge.challenge_id,
            report_id=challenge.report_id,
            report_hash=challenge.report_hash,
            endpoint_id=challenge.endpoint_id,
            outcome=challenge.outcome,
            quorum_state=quorum["quorum_state"],
            independent_observation_count=quorum["independent_observation_count"],
            required_quorum=quorum["quorum_required"],
            events=events,
        )

    def apply_challenge(
        self,
        challenge: ValidationReportCustodyChallenge,
        *,
        quorum_summary: dict[str, Any] | None = None,
    ) -> CustodyReputationProjection:
        """Explicitly ingest a projection, replay-safe by deterministic event ID."""
        if self.engine is None:
            raise RuntimeError("ReputationEngine is required to apply custody evidence")
        projection = self.project_challenge(
            challenge,
            quorum_summary=quorum_summary,
        )
        existing_ids = {
            event.event_id
            for event in self.engine.get_event_history(
                "ENDPOINT",
                challenge.endpoint_id,
                limit=100_000,
            )
        }
        pending = [
            event for event in projection.events if event.event_id not in existing_ids
        ]
        if pending:
            self.engine.ingest_events(pending)
        return projection

    @staticmethod
    def _normalize_quorum_summary(
        challenge: ValidationReportCustodyChallenge,
        summary: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if summary is None:
            return {
                "quorum_state": "single_observation",
                "independent_observation_count": 1,
                "quorum_required": 1,
            }
        if summary.get("report_id") != challenge.report_id:
            raise ValueError("custody quorum summary report does not match challenge")
        if summary.get("report_hash") != challenge.report_hash:
            raise ValueError("custody quorum summary hash does not match challenge")
        try:
            observation_count = int(summary["independent_observation_count"])
            quorum_required = int(summary["quorum_required"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("custody quorum summary is incomplete") from exc
        if observation_count < 1 or quorum_required < 1:
            raise ValueError("custody quorum summary counts must be positive")
        quorum_state = summary.get("quorum_state")
        expected_state = (
            "confirmed" if observation_count >= quorum_required else "pending"
        )
        if quorum_state != expected_state:
            raise ValueError("custody quorum summary state is inconsistent")
        return {
            "quorum_state": quorum_state,
            "independent_observation_count": observation_count,
            "quorum_required": quorum_required,
        }

    @staticmethod
    def _confidence_for(
        outcome: ValidationCustodyChallengeOutcome,
        quorum: dict[str, Any],
    ) -> str:
        if quorum["quorum_state"] == "confirmed":
            return "MULTI_SOURCE"
        if outcome in {"available", "corrupted"}:
            return "REPRODUCIBLE"
        return "OBSERVATIONAL"

    def _build_event(
        self,
        *,
        challenge: ValidationReportCustodyChallenge,
        spec: _EventSpec,
        evidence_confidence: str,
    ) -> ReputationEvent:
        event_id = "custody-reputation-" + canonical_validation_hash(
            {
                "challenge_id": challenge.challenge_id,
                "report_id": challenge.report_id,
                "report_hash": challenge.report_hash,
                "endpoint_id": challenge.endpoint_id,
                "dimension": spec.dimension,
                "event_class": spec.event_class,
                "direction": spec.direction,
                "severity": spec.severity,
                "evidence_root": challenge.evidence_root,
            }
        ).removeprefix("sha256:")
        return ReputationEvent(
            subject_type="ENDPOINT",
            subject_id=challenge.endpoint_id,
            profile_dimension=spec.dimension,
            event_class=spec.event_class,
            direction=spec.direction,
            severity=spec.severity,
            evidence_confidence=evidence_confidence,
            source_type=self.SOURCE_TYPE,
            source_reference=challenge.challenge_id,
            evidence_root=challenge.evidence_root,
            observed_at=challenge.checked_at,
            event_id=event_id,
        )


__all__ = ["CustodyReputationAdapter", "CustodyReputationProjection"]
