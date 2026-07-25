"""SessionFailureHandler — RFC-0060 failure classification and recovery.

Responsible for:
- Classifying Session failures into FailureClass + Attribution
- Managing recovery windows per RFC-0060 §20, §25
- Transitioning Session states through failure lifecycle
- Recording evidence in SessionFailureEvidenceStore
- Emitting SessionFailureEvents
- Calling ReputationEvent callbacks when attribution is conclusive
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from aidn_hypervisor.session_failure.models import (
    EvidenceLevel,
    FailureAttribution,
    FailureClass,
    FailureEvidenceRecord,
    FailureReport,
    RecoveryWindowConfig,
    ReputationEvent,
    SessionFailureEvent,
    is_terminal_status,
)
from aidn_hypervisor.session_failure.store import SessionFailureEvidenceStore


# FailureClass -> initial status transition map
_FAILURE_STATE_MAP: dict[FailureClass, str] = {
    # Disconnection failures -> recovery window
    FailureClass.CONSUMER_DISCONNECTED: "recovering",
    FailureClass.PROVIDER_DISCONNECTED: "recovering",
    FailureClass.RUNTIME_FAILURE: "recovering",
    FailureClass.ENDPOINT_FAILURE: "recovering",
    FailureClass.UPSTREAM_PROXY_FAILURE: "recovering",
    # Immediate terminal-path failures
    FailureClass.DEPOSIT_EXHAUSTED: "deposit_exhausted",
    FailureClass.ACCOUNTING_MISMATCH: "accounting_mismatch",
    # Timeouts -> force close path
    FailureClass.IDLE_TIMEOUT: "force_closing",
    FailureClass.SESSION_TIMEOUT: "force_closing",
    FailureClass.USAGE_REPORT_TIMEOUT: "force_closing",
    FailureClass.ACKNOWLEDGEMENT_TIMEOUT: "force_closing",
    # Force close requests
    FailureClass.CONSUMER_FORCE_CLOSE: "force_closing",
    FailureClass.PROVIDER_FORCE_CLOSE: "force_closing",
    # Protocol / consensus
    FailureClass.PROTOCOL_INCOMPATIBILITY: "unrecoverable",
    FailureClass.CONSENSUS_INTERRUPTION: "paused",
    FailureClass.STATE_RECOVERY_FAILURE: "unrecoverable",
    # Fallback
    FailureClass.UNKNOWN_FAILURE: "force_closing",
}

# FailureClass -> default attribution
_DEFAULT_ATTRIBUTION: dict[FailureClass, FailureAttribution] = {
    FailureClass.CONSUMER_DISCONNECTED: FailureAttribution.CONSUMER_AT_FAULT,
    FailureClass.PROVIDER_DISCONNECTED: FailureAttribution.PROVIDER_AT_FAULT,
    FailureClass.RUNTIME_FAILURE: FailureAttribution.PROVIDER_AT_FAULT,
    FailureClass.ENDPOINT_FAILURE: FailureAttribution.PROVIDER_AT_FAULT,
    FailureClass.UPSTREAM_PROXY_FAILURE: FailureAttribution.EXTERNAL_FAILURE,
    FailureClass.ACCOUNTING_MISMATCH: FailureAttribution.INCONCLUSIVE,
    FailureClass.USAGE_REPORT_TIMEOUT: FailureAttribution.PROVIDER_AT_FAULT,
    FailureClass.ACKNOWLEDGEMENT_TIMEOUT: FailureAttribution.CONSUMER_AT_FAULT,
    FailureClass.DEPOSIT_EXHAUSTED: FailureAttribution.EXTERNAL_FAILURE,
    FailureClass.SESSION_TIMEOUT: FailureAttribution.EXTERNAL_FAILURE,
    FailureClass.IDLE_TIMEOUT: FailureAttribution.EXTERNAL_FAILURE,
    FailureClass.CONSUMER_FORCE_CLOSE: FailureAttribution.EXTERNAL_FAILURE,
    FailureClass.PROVIDER_FORCE_CLOSE: FailureAttribution.EXTERNAL_FAILURE,
    FailureClass.PROTOCOL_INCOMPATIBILITY: FailureAttribution.PROTOCOL_FAILURE,
    FailureClass.CONSENSUS_INTERRUPTION: FailureAttribution.EXTERNAL_FAILURE,
    FailureClass.STATE_RECOVERY_FAILURE: FailureAttribution.PROTOCOL_FAILURE,
    FailureClass.UNKNOWN_FAILURE: FailureAttribution.INCONCLUSIVE,
}

# Attribution values that should NOT trigger reputation penalties
_NON_PUNISHABLE_ATTRIBUTIONS = {
    FailureAttribution.EXTERNAL_FAILURE,
    FailureAttribution.PROTOCOL_FAILURE,
    FailureAttribution.INCONCLUSIVE,
}


class SessionFailureHandler:
    """Handles Session failure classification, recovery windows, and state transitions.

    Designed as a separate component from SessionService (per architectural decision).
    Communicates with SessionService via callbacks and shared store references.
    """

    def __init__(
        self,
        *,
        recovery_config: RecoveryWindowConfig | None = None,
        evidence_store: SessionFailureEvidenceStore | None = None,
    ) -> None:
        self.recovery_config = recovery_config or RecoveryWindowConfig()
        self.evidence_store = evidence_store or SessionFailureEvidenceStore()

        # session_id -> current status (mirrors/extends SessionService status)
        self._session_states: dict[str, str] = {}

        # session_id -> ISO recovery deadline
        self._recovery_deadlines: dict[str, str] = {}

        # session_id -> list[SessionFailureEvent]
        self._events: dict[str, list[SessionFailureEvent]] = {}

        # Optional: callback for reputation events
        self._reputation_callback: Callable[[ReputationEvent], None] | None = None

        # Optional: callback to notify SessionService of status changes
        self._status_change_callback: (
            Callable[[str, str, str], None] | None
        ) = None  # (session_id, old_status, new_status)

    # ------------------------------------------------------------------
    # Session registration
    # ------------------------------------------------------------------

    def register_session(self, session_id: str, initial_status: str) -> None:
        """Register a session for failure monitoring."""
        self._session_states[session_id] = initial_status

    def unregister_session(self, session_id: str) -> bool:
        """Unregister a session. Returns True if it was tracked."""
        if session_id not in self._session_states:
            return False
        del self._session_states[session_id]
        self._recovery_deadlines.pop(session_id, None)
        return True

    def get_session_failure_status(self, session_id: str) -> str | None:
        """Get the current failure-tracked status for a session."""
        return self._session_states.get(session_id)

    def set_session_status(self, session_id: str, status: str) -> None:
        """Directly set a session status (used by SessionService sync)."""
        self._session_states[session_id] = status

    # ------------------------------------------------------------------
    # Failure classification
    # ------------------------------------------------------------------

    def classify_failure(
        self,
        *,
        session_id: str,
        failure_class: FailureClass,
        attribution: FailureAttribution | None = None,
        details: str = "",
    ) -> SessionFailureEvent:
        """Classify a failure and transition the session to the appropriate state.

        Args:
            session_id: Target session.
            failure_class: Primary failure classification.
            attribution: Optional override for fault attribution.
            details: Human-readable context.

        Returns:
            The emitted SessionFailureEvent.

        Raises:
            ValueError: If the session is not tracked or already terminal.
        """
        current_status = self._session_states.get(session_id)
        if current_status is None:
            raise ValueError(f"Session {session_id} is not tracked")
        if is_terminal_status(current_status):
            raise ValueError(
                f"Session {session_id} is already in terminal state: {current_status}"
            )

        # Determine attribution
        resolved_attribution = attribution or _DEFAULT_ATTRIBUTION.get(
            failure_class, FailureAttribution.INCONCLUSIVE
        )

        # Determine target status
        new_status = _FAILURE_STATE_MAP.get(failure_class, "force_closing")

        # Transition
        event = self._transition(
            session_id=session_id,
            new_status=new_status,
            event_type="failure_detected",
            failure_class=failure_class,
            details={
                "attribution": resolved_attribution.value,
                "details": details,
            },
        )

        # Record evidence
        now = datetime.now(timezone.utc).isoformat()
        evidence = FailureEvidenceRecord(
            session_id=session_id,
            evidence_level=EvidenceLevel.OBSERVATIONAL,
            category=failure_class.value,
            detail=details or f"Failure classified as {failure_class.value}",
            recorded_at=now,
            source="failure_handler",
        )
        self.evidence_store.add_evidence(session_id, evidence)

        # Save failure report
        report = FailureReport(
            session_id=session_id,
            failure_class=failure_class,
            attribution=resolved_attribution,
            evidence_ids=[evidence.recorded_at],  # placeholder ref
            failure_timestamp=now,
            previous_status=current_status,
            resulting_status=new_status,
        )
        self.evidence_store.save_report(report)

        # Set recovery deadline if entering recovering state
        if new_status == "recovering":
            self._set_recovery_deadline(session_id, failure_class)

        # Emit reputation event if attribution is conclusive
        if resolved_attribution not in _NON_PUNISHABLE_ATTRIBUTIONS:
            self._emit_reputation_event(
                session_id=session_id,
                failure_class=failure_class,
                attribution=resolved_attribution,
                evidence_level=EvidenceLevel.OBSERVATIONAL,
            )

        return event

    # ------------------------------------------------------------------
    # Recovery window
    # ------------------------------------------------------------------

    def _set_recovery_deadline(
        self, session_id: str, failure_class: FailureClass
    ) -> None:
        """Set the recovery deadline based on failure class and config."""
        from datetime import timedelta

        now = datetime.now(timezone.utc)
        if failure_class in {
            FailureClass.PROVIDER_DISCONNECTED,
            FailureClass.RUNTIME_FAILURE,
            FailureClass.ENDPOINT_FAILURE,
        }:
            delta = timedelta(
                seconds=self.recovery_config.provider_reconnect_timeout_seconds
            )
        elif failure_class == FailureClass.UPSTREAM_PROXY_FAILURE:
            # Proxy failures use provider timeout
            delta = timedelta(
                seconds=self.recovery_config.provider_reconnect_timeout_seconds
            )
        else:
            # Consumer disconnections, defaults
            delta = timedelta(
                seconds=self.recovery_config.consumer_reconnect_timeout_seconds
            )

        self._recovery_deadlines[session_id] = (now + delta).isoformat()

    def get_recovery_deadline(self, session_id: str) -> str | None:
        """Get the recovery deadline ISO string, or None."""
        return self._recovery_deadlines.get(session_id)

    def is_recovery_expired(self, session_id: str) -> bool:
        """Check if the recovery window has expired for a session."""
        deadline = self._recovery_deadlines.get(session_id)
        if deadline is None:
            return False
        current_status = self._session_states.get(session_id)
        if current_status != "recovering":
            return False
        try:
            deadline_dt = datetime.fromisoformat(deadline)
        except ValueError:
            return True
        return datetime.now(timezone.utc) >= deadline_dt

    def expire_recovery(self, session_id: str) -> SessionFailureEvent | None:
        """Expire a recovery window, transitioning to force_closing.

        Returns None if the session is not in recovering state or
        recovery has not expired.
        """
        current_status = self._session_states.get(session_id)
        if current_status != "recovering":
            return None
        if not self.is_recovery_expired(session_id):
            return None

        event = self._transition(
            session_id=session_id,
            new_status="force_closing",
            event_type="recovery_expired",
            details={"recovery_deadline": self._recovery_deadlines.get(session_id)},
        )

        # Update the failure report
        existing_report = self.evidence_store.get_report(session_id)
        if existing_report:
            existing_report.resulting_status = "force_closing"
            self.evidence_store.save_report(existing_report)

        return event

    def recover_session(self, session_id: str) -> SessionFailureEvent:
        """Transition a recovering session back to active.

        Raises:
            ValueError: If the session is not in recovering state.
        """
        current_status = self._session_states.get(session_id)
        if current_status is None:
            raise ValueError(f"Session {session_id} is not tracked")
        if current_status != "recovering":
            raise ValueError(
                f"Session {session_id} is not in recovering state: {current_status}"
            )

        event = self._transition(
            session_id=session_id,
            new_status="active",
            event_type="recovery_succeeded",
        )

        # Clear recovery deadline
        self._recovery_deadlines.pop(session_id, None)

        # Record evidence
        evidence = FailureEvidenceRecord(
            session_id=session_id,
            evidence_level=EvidenceLevel.OBSERVATIONAL,
            category="recovery_success",
            detail="Session recovered within recovery window",
            recorded_at=datetime.now(timezone.utc).isoformat(),
            source="failure_handler",
        )
        self.evidence_store.add_evidence(session_id, evidence)

        return event

    # ------------------------------------------------------------------
    # Proxy failure handling
    # ------------------------------------------------------------------

    def handle_proxy_failure(
        self,
        *,
        session_id: str,
        remote_endpoint_id: str,
        error: str = "",
    ) -> SessionFailureEvent:
        """Handle a Proxy Endpoint failure (RFC-0060 §90+).

        Transitions the session to recovering and records proxy-specific evidence.
        """
        now = datetime.now(timezone.utc).isoformat()

        # Record proxy-specific evidence
        evidence = FailureEvidenceRecord(
            session_id=session_id,
            evidence_level=EvidenceLevel.OBSERVATIONAL,
            category="proxy_failure",
            detail=f"Proxy failure for {remote_endpoint_id}: {error}",
            recorded_at=now,
            source="failure_handler",
        )
        self.evidence_store.add_evidence(session_id, evidence)

        return self.classify_failure(
            session_id=session_id,
            failure_class=FailureClass.UPSTREAM_PROXY_FAILURE,
            details=f"Proxy {remote_endpoint_id}: {error}",
        )

    # ------------------------------------------------------------------
    # Evidence
    # ------------------------------------------------------------------

    def add_evidence(
        self, session_id: str, record: FailureEvidenceRecord
    ) -> FailureEvidenceRecord:
        """Manually add an evidence record for a session."""
        return self.evidence_store.add_evidence(session_id, record)

    # ------------------------------------------------------------------
    # Failure reports
    # ------------------------------------------------------------------

    def get_failure_report(self, session_id: str) -> FailureReport | None:
        """Get the failure report for a session, if one exists."""
        return self.evidence_store.get_report(session_id)

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def get_events_for_session(
        self, session_id: str
    ) -> list[SessionFailureEvent]:
        """Get all failure events for a session."""
        return list(self._events.get(session_id, []))

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def set_reputation_callback(
        self, callback: Callable[[ReputationEvent], None]
    ) -> None:
        """Set the callback for reputation events."""
        self._reputation_callback = callback

    def set_status_change_callback(
        self, callback: Callable[[str, str, str], None]
    ) -> None:
        """Set the callback for status change notifications.

        Signature: callback(session_id, old_status, new_status)
        """
        self._status_change_callback = callback

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _transition(
        self,
        *,
        session_id: str,
        new_status: str,
        event_type: str,
        failure_class: FailureClass | None = None,
        details: dict | None = None,
    ) -> SessionFailureEvent:
        """Perform a state transition and emit an event."""
        old_status = self._session_states.get(session_id)
        if old_status is not None and is_terminal_status(old_status):
            raise ValueError(
                f"Cannot transition session {session_id} from terminal state {old_status}"
            )

        self._session_states[session_id] = new_status

        now = datetime.now(timezone.utc).isoformat()
        event = SessionFailureEvent(
            session_id=session_id,
            event_type=event_type,
            failure_class=failure_class,
            previous_status=old_status or "unknown",
            new_status=new_status,
            timestamp=now,
            details=details or {},
        )

        if session_id not in self._events:
            self._events[session_id] = []
        self._events[session_id].append(event)

        # Notify external listeners
        if self._status_change_callback and old_status is not None:
            try:
                self._status_change_callback(session_id, old_status, new_status)
            except Exception:
                pass  # Don't let callback failures break state transitions

        return event

    def _emit_reputation_event(
        self,
        *,
        session_id: str,
        failure_class: FailureClass,
        attribution: FailureAttribution,
        evidence_level: EvidenceLevel,
    ) -> None:
        """Emit a ReputationEvent if a callback is configured."""
        if self._reputation_callback is None:
            return

        # Determine target wallet based on attribution
        target_wallet = ""
        if attribution == FailureAttribution.CONSUMER_AT_FAULT:
            target_wallet = "consumer_wallet"  # Will be resolved by callback context
        elif attribution == FailureAttribution.PROVIDER_AT_FAULT:
            target_wallet = "provider_wallet"

        # Calculate penalty hint based on evidence level
        penalty_map = {
            EvidenceLevel.CRYPTOGRAPHIC: 0.3,
            EvidenceLevel.REPRODUCIBLE: 0.15,
            EvidenceLevel.OBSERVATIONAL: 0.05,
        }
        penalty_hint = penalty_map.get(evidence_level, 0.05)

        evt = ReputationEvent(
            session_id=session_id,
            target_wallet=target_wallet,
            failure_class=failure_class,
            attribution=attribution,
            evidence_level=evidence_level,
            penalty_hint=penalty_hint,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        try:
            self._reputation_callback(evt)
        except Exception:
            pass  # Don't let reputation failures break failure handling
