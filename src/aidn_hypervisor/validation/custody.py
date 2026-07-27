"""M5 Phase 3: Validation Report Custody & Event Finalization.

RFC-0041 §69A: Endpoint custody Reputation distinguishes:
- one temporary retrieval outage (Health only)
- repeated unavailability (reduces availability confidence)
- report loss after migration (reduces retention reliability)
- deliberate withholding (strong negative disclosure event)
- content hash failure (critical integrity event)
- successful restoration (repairs availability without erasing history)

RFC-0041 §102: Event Finalization Delay — confirmation/challenge period.
RFC-0041 §103: Event Challenge — participant may challenge processing errors.
RFC-0041 §104: Corrections — new correction event, not silent rewrite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any

# ---------------------------------------------------------------------------
# Custody Configuration
# ---------------------------------------------------------------------------

class CustodyConfig:
    """Configuration for report custody tracking."""

    def __init__(
        self,
        grace_period_seconds: int = 300,          # 5 min grace window
        minimum_retention_seconds: int = 86400,   # 24h minimum retention
        max_failure_streak: int = 5,             # cap on streak counter
        check_interval_seconds: int = 60,        # sweep interval
    ):
        if grace_period_seconds <= 0:
            raise ValueError("grace_period_seconds must be positive")
        if minimum_retention_seconds <= 0:
            raise ValueError("minimum_retention_seconds must be positive")
        if max_failure_streak <= 0:
            raise ValueError("max_failure_streak must be positive")
        if check_interval_seconds <= 0:
            raise ValueError("check_interval_seconds must be positive")

        self.grace_period_seconds = grace_period_seconds
        self.minimum_retention_seconds = minimum_retention_seconds
        self.max_failure_streak = max_failure_streak
        self.check_interval_seconds = check_interval_seconds


# ---------------------------------------------------------------------------
# Custody State Machine
# ---------------------------------------------------------------------------

class CustodyStatus(str, Enum):
    AVAILABLE = "available"
    GRACE_PERIOD = "grace_period"
    CUSTODY_FAILED = "custody_failed"
    RETENTION_VIOLATED = "retention_violated"


class CustodyAction(str, Enum):
    NONE = "none"
    START_GRACE = "start_grace"
    CONTINUE_GRACE = "continue_grace"
    EMIT_PENALTY = "emit_penalty"
    RESTORE = "restore"
    RETENTION_VIOLATION = "retention_violation"


@dataclass
class CustodyCheckResult:
    report_hash: str
    status: CustodyStatus
    action: CustodyAction
    failure_streak: int
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @property
    def ok(self) -> bool:
        """Whether custody is healthy (no failure, no penalty)."""
        return self.status == CustodyStatus.AVAILABLE and self.action == CustodyAction.NONE


@dataclass
class CustodyState:
    """Per-report custody tracking state."""

    report_hash: str
    endpoint_id: str
    stored_at: str

    _status: CustodyStatus = CustodyStatus.AVAILABLE
    failure_streak: int = 0
    total_failure_count: int = 0
    last_checked_at: str | None = None
    last_available_at: str | None = None
    grace_expires_at: str | None = None

    def __post_init__(self):
        self.last_available_at = self.stored_at

    @property
    def status(self) -> CustodyStatus:
        return self._status

    @status.setter
    def status(self, value: CustodyStatus):
        self._status = value

    def mark_unavailable(self, grace_seconds: int = 300) -> None:
        """Mark report as unavailable, starting or extending grace period."""
        self.failure_streak += 1
        self.total_failure_count += 1
        self.last_checked_at = datetime.now(UTC).isoformat()

        if self._status == CustodyStatus.AVAILABLE:
            self._status = CustodyStatus.GRACE_PERIOD
            self.grace_expires_at = (
                datetime.now(UTC) + timedelta(seconds=grace_seconds)
            ).isoformat()
        elif self._status == CustodyStatus.GRACE_PERIOD:
            # Extend grace but increment streak
            self.grace_expires_at = (
                datetime.now(UTC) + timedelta(seconds=grace_seconds)
            ).isoformat()

    def mark_available(self) -> None:
        """Mark report as available again (restoration)."""
        self.failure_streak = 0
        self._status = CustodyStatus.AVAILABLE
        self.last_available_at = datetime.now(UTC).isoformat()
        self.last_checked_at = datetime.now(UTC).isoformat()
        self.grace_expires_at = None

    def check_grace_expired(self) -> bool:
        """Check if grace period has expired."""
        if self.grace_expires_at is None:
            return False
        expires = datetime.fromisoformat(self.grace_expires_at)
        return datetime.now(UTC) > expires


# ---------------------------------------------------------------------------
# Custody Store (in-memory)
# ---------------------------------------------------------------------------

class CustodyStore:
    """In-memory store for custody states."""

    def __init__(self) -> None:
        self._states: dict[str, CustodyState] = {}

    def add(self, state: CustodyState) -> None:
        self._states[state.report_hash] = state

    def get(self, report_hash: str) -> CustodyState | None:
        return self._states.get(report_hash)

    def remove(self, report_hash: str) -> None:
        self._states.pop(report_hash, None)

    def list_by_endpoint(self, endpoint_id: str) -> list[CustodyState]:
        return [s for s in self._states.values() if s.endpoint_id == endpoint_id]

    def list_all(self) -> list[CustodyState]:
        return list(self._states.values())

    def clear(self) -> None:
        self._states.clear()


# ---------------------------------------------------------------------------
# Custody Service
# ---------------------------------------------------------------------------

class CustodyService:
    """Manages validation report custody lifecycle."""

    def __init__(self, store: CustodyStore, config: CustodyConfig) -> None:
        self.store = store
        self.config = config

    def check_custody(self, report_hash: str, available: bool) -> CustodyCheckResult:
        """Check custody status for a report."""
        state = self.store.get(report_hash)
        if state is None:
            return CustodyCheckResult(
                report_hash=report_hash,
                status=CustodyStatus.CUSTODY_FAILED,
                action=CustodyAction.EMIT_PENALTY,
                failure_streak=0,
            )

        state.last_checked_at = datetime.now(UTC).isoformat()

        if available:
            prev_failed = state._status == CustodyStatus.CUSTODY_FAILED
            state.mark_available()
            action = CustodyAction.RESTORE if prev_failed else CustodyAction.NONE
            return CustodyCheckResult(
                report_hash=report_hash,
                status=CustodyStatus.AVAILABLE,
                action=action,
                failure_streak=0,
            )

        # Report unavailable
        if state._status == CustodyStatus.AVAILABLE:
            state.mark_unavailable(self.config.grace_period_seconds)
            return CustodyCheckResult(
                report_hash=report_hash,
                status=CustodyStatus.GRACE_PERIOD,
                action=CustodyAction.START_GRACE,
                failure_streak=state.failure_streak,
            )

        if state._status == CustodyStatus.GRACE_PERIOD:
            if state.check_grace_expired():
                state._status = CustodyStatus.CUSTODY_FAILED
                # Cap streak
                state.failure_streak = min(
                    state.failure_streak, self.config.max_failure_streak
                )
                return CustodyCheckResult(
                    report_hash=report_hash,
                    status=CustodyStatus.CUSTODY_FAILED,
                    action=CustodyAction.EMIT_PENALTY,
                    failure_streak=state.failure_streak,
                )
            # Extend grace
            state.mark_unavailable(self.config.grace_period_seconds)
            return CustodyCheckResult(
                report_hash=report_hash,
                status=CustodyStatus.GRACE_PERIOD,
                action=CustodyAction.CONTINUE_GRACE,
                failure_streak=state.failure_streak,
            )

        # Already failed
        state.failure_streak = min(state.failure_streak + 1, self.config.max_failure_streak)
        return CustodyCheckResult(
            report_hash=report_hash,
            status=CustodyStatus.CUSTODY_FAILED,
            action=CustodyAction.EMIT_PENALTY,
            failure_streak=state.failure_streak,
        )

    def check_retention(self, report_hash: str) -> CustodyCheckResult:
        """Check if a report meets minimum retention requirements."""
        state = self.store.get(report_hash)
        if state is None:
            return CustodyCheckResult(
                report_hash=report_hash,
                status=CustodyStatus.CUSTODY_FAILED,
                action=CustodyAction.EMIT_PENALTY,
                failure_streak=0,
            )

        stored = datetime.fromisoformat(state.stored_at)
        age_seconds = (datetime.now(UTC) - stored).total_seconds()

        if age_seconds < self.config.minimum_retention_seconds:
            return CustodyCheckResult(
                report_hash=report_hash,
                status=state._status,
                action=CustodyAction.NONE,
                failure_streak=state.failure_streak,
            )

        # Report has been retained long enough — OK
        return CustodyCheckResult(
            report_hash=report_hash,
            status=state._status,
            action=CustodyAction.NONE,
            failure_streak=state.failure_streak,
        )

    def sweep(self) -> int:
        """Sweep expired grace periods. Returns count of expired reports."""
        expired = 0
        for state in self.store.list_all():
            if state._status == CustodyStatus.GRACE_PERIOD and state.check_grace_expired():
                state._status = CustodyStatus.CUSTODY_FAILED
                state.failure_streak = min(
                    state.failure_streak, self.config.max_failure_streak
                )
                expired += 1
        return expired


# ---------------------------------------------------------------------------
# Challenge Models
# ---------------------------------------------------------------------------

class ChallengeState(str, Enum):
    PENDING = "pending"
    RESOLVED = "resolved"
    EXPIRED = "expired"


class ChallengeOutcome(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class ChallengeReason(str, Enum):
    WRONG_SUBJECT = "wrong_subject"
    DUPLICATE_EVENT = "duplicate_event"
    INVALID_EVIDENCE = "invalid_evidence"
    WRONG_EVENT_CLASS = "wrong_event_class"
    INCORRECT_PROPAGATION = "incorrect_propagation"
    INCORRECT_FORMULA = "incorrect_formula"
    CUSTODY_ERROR = "custody_error"


@dataclass
class Challenge:
    """Challenge against a reputation or custody event."""

    challenge_id: str
    event_id: str
    challenger_id: str
    reason: str

    state: ChallengeState = ChallengeState.PENDING
    outcome: ChallengeOutcome | None = None
    resolution_note: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    resolved_at: str | None = None

    def resolve(
        self,
        outcome: ChallengeOutcome,
        note: str | None = None,
    ) -> None:
        """Resolve this challenge."""
        if self.state != ChallengeState.PENDING:
            raise ValueError(f"Cannot resolve challenge in state {self.state}")
        self.state = ChallengeState.RESOLVED
        self.outcome = outcome
        self.resolution_note = note
        self.resolved_at = datetime.now(UTC).isoformat()


# ---------------------------------------------------------------------------
# Correction Models
# ---------------------------------------------------------------------------

@dataclass
class Correction:
    """Correction event for a processing error.

    RFC-0041 §104: Finalized Reputation history SHALL not be silently rewritten.
    An error is corrected through a new correction event.
    """

    correction_id: str
    original_event_id: str
    error_class: str
    corrected_values: dict[str, Any]

    resulting_score_adjustment: float | None = None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


# ---------------------------------------------------------------------------
# Event Finalization
# ---------------------------------------------------------------------------

class EventFinalizationState(str, Enum):
    PENDING = "pending"
    CHALLENGED = "challenged"
    FINALIZED = "finalized"
    CORRECTED = "corrected"


@dataclass
class ReputationEventRecord:
    """Track finalization state for a reputation event."""

    event_id: str
    subject_id: str
    dimension: str
    direction: str
    score_delta: float

    finalization_state: EventFinalizationState = EventFinalizationState.PENDING
    challenge_id: str | None = None
    correction_id: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    finalized_at: str | None = None

    def finalize(self) -> None:
        """Finalize this event (no further challenges allowed)."""
        if self.finalization_state == EventFinalizationState.FINALIZED:
            return  # idempotent
        if self.finalization_state == EventFinalizationState.CHALLENGED:
            raise ValueError("Cannot finalize challenged event without resolution")
        self.finalization_state = EventFinalizationState.FINALIZED
        self.finalized_at = datetime.now(UTC).isoformat()

    def challenge(self, challenge_id: str) -> None:
        """Place this event under challenge."""
        if self.finalization_state == EventFinalizationState.FINALIZED:
            raise ValueError("Cannot challenge finalized event")
        self.finalization_state = EventFinalizationState.CHALLENGED
        self.challenge_id = challenge_id


# ---------------------------------------------------------------------------
# Finalization Store & Service
# ---------------------------------------------------------------------------

class FinalizationStore:
    """In-memory store for event finalization tracking."""

    def __init__(self) -> None:
        self._events: dict[str, ReputationEventRecord] = {}
        self._corrections: dict[str, Correction] = {}
        self._challenges: dict[str, Challenge] = {}

    def add_event(self, event: ReputationEventRecord) -> None:
        self._events[event.event_id] = event

    def get_event(self, event_id: str) -> ReputationEventRecord | None:
        return self._events.get(event_id)

    def add_correction(self, correction: Correction) -> None:
        self._corrections[correction.original_event_id] = correction

    def get_correction(self, event_id: str) -> Correction | None:
        return self._corrections.get(event_id)

    def add_challenge(self, challenge: Challenge) -> None:
        self._challenges[challenge.challenge_id] = challenge

    def get_challenge(self, challenge_id: str) -> Challenge | None:
        return self._challenges.get(challenge_id)

    def list_pending(self) -> list[ReputationEventRecord]:
        return [
            e for e in self._events.values()
            if e.finalization_state == EventFinalizationState.PENDING
        ]

    def clear(self) -> None:
        self._events.clear()
        self._corrections.clear()
        self._challenges.clear()


class FinalizationService:
    """Manages event finalization, challenges, and corrections."""

    DEFAULT_FINALIZATION_HOURS = 24  # auto-finalize after 24h if no challenge

    def __init__(
        self,
        store: FinalizationStore,
        finalization_hours: int | None = None,
    ) -> None:
        self.store = store
        self.finalization_hours = finalization_hours or self.DEFAULT_FINALIZATION_HOURS

    def add_event(self, event: ReputationEventRecord) -> None:
        """Add a new event for finalization tracking."""
        self.store.add_event(event)

    def get_event(self, event_id: str) -> ReputationEventRecord | None:
        return self.store.get_event(event_id)

    def get_correction(self, event_id: str) -> Correction | None:
        return self.store.get_correction(event_id)

    def finalize_event(self, event_id: str) -> bool:
        """Manually finalize an event."""
        event = self.store.get_event(event_id)
        if event is None:
            return False
        try:
            event.finalize()
            return True
        except ValueError:
            return False

    def challenge_event(self, event_id: str, challenge_id: str) -> bool:
        """Challenge an event before finalization."""
        event = self.store.get_event(event_id)
        if event is None:
            return False
        try:
            event.challenge(challenge_id)
            return True
        except ValueError:
            return False

    def apply_correction(self, correction: Correction) -> bool:
        """Apply a correction to an event."""
        event = self.store.get_event(correction.original_event_id)
        if event is None:
            return False
        self.store.add_correction(correction)
        event.correction_id = correction.correction_id
        event.finalization_state = EventFinalizationState.CORRECTED
        return True

    def resolve_challenge(
        self,
        challenge_id: str,
        outcome: ChallengeOutcome,
        note: str | None = None,
    ) -> bool:
        """Resolve a challenge."""
        challenge = self.store.get_challenge(challenge_id)
        if challenge is None:
            return False
        try:
            challenge.resolve(outcome, note)
            # If accepted, the event should be corrected or removed
            # If rejected, the event can proceed to finalization
            return True
        except ValueError:
            return False

    def sweep(self) -> int:
        """Auto-finalize old pending events. Returns count finalized."""
        finalized = 0
        cutoff = datetime.now(UTC) - timedelta(hours=self.finalization_hours)

        for event in self.store.list_pending():
            created = datetime.fromisoformat(event.created_at)
            if created < cutoff:
                try:
                    event.finalize()
                    finalized += 1
                except ValueError:
                    pass  # challenged events skipped

        return finalized
