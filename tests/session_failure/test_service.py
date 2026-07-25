"""Tests for session_failure.service — SessionFailureHandler (RFC-0060)."""

from datetime import datetime, timezone

import pytest

from aidn_hypervisor.session_failure.models import (
    EvidenceLevel,
    FailureAttribution,
    FailureClass,
    FailureEvidenceRecord,
    RecoveryWindowConfig,
    ReputationEvent,
    SessionFailureEvent,
)
from aidn_hypervisor.session_failure.service import SessionFailureHandler


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def handler():
    """Create a SessionFailureHandler with default recovery config."""
    config = RecoveryWindowConfig(
        consumer_reconnect_timeout_seconds=60,
        consumer_acknowledgement_timeout_seconds=30,
        provider_reconnect_timeout_seconds=60,
        provider_runtime_restart_timeout_seconds=30,
    )
    return SessionFailureHandler(recovery_config=config)


# ---------------------------------------------------------------------------
# classify_failure
# ---------------------------------------------------------------------------

class TestClassifyFailure:
    def test_classify_provider_disconnected_moves_to_recovering(self, handler):
        handler._session_states["sess-001"] = "active"
        handler.classify_failure(
            session_id="sess-001",
            failure_class=FailureClass.PROVIDER_DISCONNECTED,
        )
        assert handler.get_session_failure_status("sess-001") == "recovering"

    def test_classify_consumer_disconnected_moves_to_recovering(self, handler):
        handler._session_states["sess-001"] = "active"
        handler.classify_failure(
            session_id="sess-001",
            failure_class=FailureClass.CONSUMER_DISCONNECTED,
        )
        assert handler.get_session_failure_status("sess-001") == "recovering"

    def test_classify_runtime_failure_moves_to_recovering(self, handler):
        handler._session_states["sess-001"] = "active"
        handler.classify_failure(
            session_id="sess-001",
            failure_class=FailureClass.RUNTIME_FAILURE,
        )
        assert handler.get_session_failure_status("sess-001") == "recovering"

    def test_classify_deposit_exhausted_moves_to_deposit_exhausted(self, handler):
        handler._session_states["sess-001"] = "active"
        handler.classify_failure(
            session_id="sess-001",
            failure_class=FailureClass.DEPOSIT_EXHAUSTED,
        )
        assert handler.get_session_failure_status("sess-001") == "deposit_exhausted"

    def test_classify_accounting_mismatch_moves_to_accounting_mismatch(self, handler):
        handler._session_states["sess-001"] = "active"
        handler.classify_failure(
            session_id="sess-001",
            failure_class=FailureClass.ACCOUNTING_MISMATCH,
        )
        assert handler.get_session_failure_status("sess-001") == "accounting_mismatch"

    def test_classify_idle_timeout_moves_to_force_closing(self, handler):
        handler._session_states["sess-001"] = "active"
        handler.classify_failure(
            session_id="sess-001",
            failure_class=FailureClass.IDLE_TIMEOUT,
        )
        assert handler.get_session_failure_status("sess-001") == "force_closing"

    def test_classify_unknown_failure_moves_to_force_closing(self, handler):
        handler._session_states["sess-001"] = "active"
        handler.classify_failure(
            session_id="sess-001",
            failure_class=FailureClass.UNKNOWN_FAILURE,
        )
        assert handler.get_session_failure_status("sess-001") == "force_closing"

    def test_classify_proxy_failure_moves_to_recovering(self, handler):
        handler._session_states["sess-001"] = "active"
        handler.classify_failure(
            session_id="sess-001",
            failure_class=FailureClass.UPSTREAM_PROXY_FAILURE,
        )
        assert handler.get_session_failure_status("sess-001") == "recovering"

    def test_classify_rejects_terminal_session(self, handler):
        handler._session_states["sess-001"] = "closed"
        with pytest.raises(ValueError, match="terminal"):
            handler.classify_failure(
                session_id="sess-001",
                failure_class=FailureClass.PROVIDER_DISCONNECTED,
            )

    def test_classify_rejects_unknown_session(self, handler):
        with pytest.raises(ValueError, match="not tracked"):
            handler.classify_failure(
                session_id="unknown",
                failure_class=FailureClass.PROVIDER_DISCONNECTED,
            )


# ---------------------------------------------------------------------------
# register / unregister sessions
# ---------------------------------------------------------------------------

class TestSessionRegistration:
    def test_register_session(self, handler):
        handler.register_session("sess-001", "active")
        assert handler.get_session_failure_status("sess-001") == "active"

    def test_unregister_session(self, handler):
        handler.register_session("sess-001", "active")
        handler.unregister_session("sess-001")
        assert handler.get_session_failure_status("sess-001") is None

    def test_unregister_unknown_session_returns_false(self, handler):
        assert handler.unregister_session("unknown") is False


# ---------------------------------------------------------------------------
# Recovery window
# ---------------------------------------------------------------------------

class TestRecoveryWindow:
    def test_recovery_started_emits_event(self, handler):
        handler.register_session("sess-001", "active")
        handler.classify_failure(
            session_id="sess-001",
            failure_class=FailureClass.PROVIDER_DISCONNECTED,
        )
        events = handler.get_events_for_session("sess-001")
        assert len(events) >= 1
        assert any(e.new_status == "recovering" for e in events)

    def test_recovery_deadline_set_on_failure(self, handler):
        handler.register_session("sess-001", "active")
        handler.classify_failure(
            session_id="sess-001",
            failure_class=FailureClass.PROVIDER_DISCONNECTED,
        )
        deadline = handler.get_recovery_deadline("sess-001")
        assert deadline is not None

    def test_recovery_expired_returns_false_when_not_recovering(self, handler):
        handler.register_session("sess-001", "active")
        assert handler.is_recovery_expired("sess-001") is False

    def test_recovery_expired_returns_true_after_timeout(self, handler):
        handler.register_session("sess-001", "active")
        handler.classify_failure(
            session_id="sess-001",
            failure_class=FailureClass.PROVIDER_DISCONNECTED,
        )
        # Manually set deadline to the past
        past = datetime.now(timezone.utc).isoformat()
        # We need to simulate the deadline being in the past
        handler._recovery_deadlines["sess-001"] = "2020-01-01T00:00:00+00:00"
        assert handler.is_recovery_expired("sess-001") is True


# ---------------------------------------------------------------------------
# Evidence recording
# ---------------------------------------------------------------------------

class TestEvidenceRecording:
    def test_classify_failure_records_evidence(self, handler):
        handler.register_session("sess-001", "active")
        handler.classify_failure(
            session_id="sess-001",
            failure_class=FailureClass.PROVIDER_DISCONNECTED,
        )
        evidence = handler.evidence_store.get_evidence_for_session("sess-001")
        assert len(evidence) >= 1
        assert evidence[0].evidence_level == EvidenceLevel.OBSERVATIONAL

    def test_add_evidence_manually(self, handler):
        handler.register_session("sess-001", "active")
        record = FailureEvidenceRecord(
            session_id="sess-001",
            evidence_level=EvidenceLevel.CRYPTOGRAPHIC,
            category="signed_termination",
            detail="Provider signed termination",
            recorded_at=datetime.now(timezone.utc).isoformat(),
            source="provider",
        )
        handler.add_evidence("sess-001", record)
        evidence = handler.evidence_store.get_evidence_for_session("sess-001")
        assert any(e.evidence_level == EvidenceLevel.CRYPTOGRAPHIC for e in evidence)


# ---------------------------------------------------------------------------
# Failure report
# ---------------------------------------------------------------------------

class TestFailureReport:
    def test_report_created_after_classify(self, handler):
        handler.register_session("sess-001", "active")
        handler.classify_failure(
            session_id="sess-001",
            failure_class=FailureClass.PROVIDER_DISCONNECTED,
        )
        report = handler.get_failure_report("sess-001")
        assert report is not None
        assert report.failure_class == FailureClass.PROVIDER_DISCONNECTED
        assert report.previous_status == "active"

    def test_no_report_for_healthy_session(self, handler):
        handler.register_session("sess-001", "active")
        report = handler.get_failure_report("sess-001")
        assert report is None


# ---------------------------------------------------------------------------
# Reputation callback
# ---------------------------------------------------------------------------

class TestReputationCallback:
    def test_reputation_callback_invoked_on_at_fault(self, handler):
        handler.register_session("sess-001", "active")
        captured: list[ReputationEvent] = []
        handler.set_reputation_callback(lambda evt: captured.append(evt))
        handler.classify_failure(
            session_id="sess-001",
            failure_class=FailureClass.RUNTIME_FAILURE,
            attribution=FailureAttribution.PROVIDER_AT_FAULT,
        )
        assert len(captured) >= 1
        assert captured[0].attribution == FailureAttribution.PROVIDER_AT_FAULT

    def test_reputation_callback_not_invoked_when_inconclusive(self, handler):
        handler.register_session("sess-001", "active")
        captured: list[ReputationEvent] = []
        handler.set_reputation_callback(lambda evt: captured.append(evt))
        handler.classify_failure(
            session_id="sess-001",
            failure_class=FailureClass.PROVIDER_DISCONNECTED,
            attribution=FailureAttribution.INCONCLUSIVE,
        )
        # INCONCLUSIVE should NOT trigger reputation events
        assert len(captured) == 0

    def test_reputation_callback_not_invoked_when_external(self, handler):
        handler.register_session("sess-001", "active")
        captured: list[ReputationEvent] = []
        handler.set_reputation_callback(lambda evt: captured.append(evt))
        handler.classify_failure(
            session_id="sess-001",
            failure_class=FailureClass.EXTERNAL_FAILURE
            if hasattr(FailureClass, "EXTERNAL_FAILURE")
            else FailureClass.UNKNOWN_FAILURE,
            attribution=FailureAttribution.EXTERNAL_FAILURE,
        )
        assert len(captured) == 0


# ---------------------------------------------------------------------------
# State transitions
# ---------------------------------------------------------------------------

class TestStateTransitions:
    def test_recovering_to_force_closing_on_expiry(self, handler):
        handler.register_session("sess-001", "active")
        handler.classify_failure(
            session_id="sess-001",
            failure_class=FailureClass.PROVIDER_DISCONNECTED,
        )
        assert handler.get_session_failure_status("sess-001") == "recovering"
        # Simulate recovery expiry
        handler._recovery_deadlines["sess-001"] = "2020-01-01T00:00:00+00:00"
        handler.expire_recovery("sess-001")
        assert handler.get_session_failure_status("sess-001") == "force_closing"

    def test_cannot_transition_from_terminal(self, handler):
        handler.register_session("sess-001", "force_settled")
        with pytest.raises(ValueError, match="terminal"):
            handler.classify_failure(
                session_id="sess-001",
                failure_class=FailureClass.RUNTIME_FAILURE,
            )

    def test_recovering_to_active_on_recover(self, handler):
        handler.register_session("sess-001", "active")
        handler.classify_failure(
            session_id="sess-001",
            failure_class=FailureClass.PROVIDER_DISCONNECTED,
        )
        handler.recover_session("sess-001")
        assert handler.get_session_failure_status("sess-001") == "active"

    def test_cannot_recover_non_recovering_session(self, handler):
        handler.register_session("sess-001", "active")
        with pytest.raises(ValueError, match="not in recovering"):
            handler.recover_session("sess-001")


# ---------------------------------------------------------------------------
# Proxy failure
# ---------------------------------------------------------------------------

class TestProxyFailure:
    def test_proxy_failure_classifies_and_moves_to_recovering(self, handler):
        handler.register_session("sess-001", "active")
        handler.handle_proxy_failure(
            session_id="sess-001",
            remote_endpoint_id="remote-ep-1",
            error="upstream connection refused",
        )
        assert handler.get_session_failure_status("sess-001") == "recovering"
        report = handler.get_failure_report("sess-001")
        assert report.failure_class == FailureClass.UPSTREAM_PROXY_FAILURE
