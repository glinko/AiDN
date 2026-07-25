"""Tests for session_failure.models — RFC-0060 failure models."""

import pytest

from aidn_hypervisor.session_failure.models import (
    EvidenceLevel,
    FailureAttribution,
    FailureClass,
    FailureEvidenceRecord,
    FailureReport,
    RecoveryWindowConfig,
    ReputationEvent,
    SessionFailureEvent,
    is_failure_status,
    is_terminal_status,
)


class TestIsTerminalStatus:
    def test_closed_is_terminal(self):
        assert is_terminal_status("closed") is True

    def test_force_settled_is_terminal(self):
        assert is_terminal_status("force_settled") is True

    def test_rejected_is_terminal(self):
        assert is_terminal_status("rejected") is True

    def test_cancelled_is_terminal(self):
        assert is_terminal_status("cancelled") is True

    def test_expired_is_terminal(self):
        assert is_terminal_status("expired") is True

    def test_unrecoverable_is_terminal(self):
        assert is_terminal_status("unrecoverable") is True

    def test_active_is_not_terminal(self):
        assert is_terminal_status("active") is False

    def test_queued_is_not_terminal(self):
        assert is_terminal_status("queued") is False

    def test_recovering_is_not_terminal(self):
        assert is_terminal_status("recovering") is False

    def test_force_closing_is_not_terminal(self):
        assert is_terminal_status("force_closing") is False


class TestIsFailureStatus:
    def test_active_is_not_failure(self):
        assert is_failure_status("active") is False

    def test_queued_is_not_failure(self):
        assert is_failure_status("queued") is False

    def test_closed_is_not_failure(self):
        assert is_failure_status("closed") is False

    def test_recovering_is_failure(self):
        assert is_failure_status("recovering") is True

    def test_provider_unavailable_is_failure(self):
        assert is_failure_status("provider_unavailable") is True

    def test_deposit_exhausted_is_failure(self):
        assert is_failure_status("deposit_exhausted") is True

    def test_unrecoverable_is_failure(self):
        assert is_failure_status("unrecoverable") is True


class TestFailureClass:
    def test_all_classes_exist(self):
        expected = {
            "CONSUMER_DISCONNECTED",
            "PROVIDER_DISCONNECTED",
            "RUNTIME_FAILURE",
            "ENDPOINT_FAILURE",
            "UPSTREAM_PROXY_FAILURE",
            "ACCOUNTING_MISMATCH",
            "USAGE_REPORT_TIMEOUT",
            "ACKNOWLEDGEMENT_TIMEOUT",
            "DEPOSIT_EXHAUSTED",
            "SESSION_TIMEOUT",
            "IDLE_TIMEOUT",
            "CONSUMER_FORCE_CLOSE",
            "PROVIDER_FORCE_CLOSE",
            "PROTOCOL_INCOMPATIBILITY",
            "CONSENSUS_INTERRUPTION",
            "STATE_RECOVERY_FAILURE",
            "UNKNOWN_FAILURE",
        }
        actual = {m.value for m in FailureClass}
        assert actual == expected

    def test_member_values_are_strings(self):
        for member in FailureClass:
            assert isinstance(member, str)


class TestFailureAttribution:
    def test_all_attribution_values_exist(self):
        expected = {
            "CONSUMER_AT_FAULT",
            "PROVIDER_AT_FAULT",
            "BOTH_AT_FAULT",
            "EXTERNAL_FAILURE",
            "PROTOCOL_FAILURE",
            "INCONCLUSIVE",
        }
        actual = {m.value for m in FailureAttribution}
        assert actual == expected


class TestEvidenceLevel:
    def test_all_evidence_levels_exist(self):
        expected = {"CRYPTOGRAPHIC", "REPRODUCIBLE", "OBSERVATIONAL"}
        actual = {m.value for m in EvidenceLevel}
        assert actual == expected

    def test_cryptographic_has_greatest_weight(self):
        # Ordering: CRYPTOGRAPHIC > REPRODUCIBLE > OBSERVATIONAL
        levels = [m.value for m in EvidenceLevel]
        assert levels[0] == "CRYPTOGRAPHIC"
        assert levels[1] == "REPRODUCIBLE"
        assert levels[2] == "OBSERVATIONAL"


class TestFailureEvidenceRecord:
    def test_create_minimal_record(self):
        record = FailureEvidenceRecord(
            session_id="sess-001",
            evidence_level=EvidenceLevel.OBSERVATIONAL,
            category="transport_timeout",
            detail="Connection to provider timed out after 300s",
            recorded_at="2026-07-25T10:00:00+00:00",
        )
        assert record.session_id == "sess-001"
        assert record.source == "hypervisor"

    def test_create_with_custom_source(self):
        record = FailureEvidenceRecord(
            session_id="sess-001",
            evidence_level=EvidenceLevel.CRYPTOGRAPHIC,
            category="signed_termination",
            detail="Provider signed termination message",
            recorded_at="2026-07-25T10:00:00+00:00",
            source="provider",
        )
        assert record.source == "provider"

    def test_rejects_empty_session_id(self):
        with pytest.raises(ValueError):
            FailureEvidenceRecord(
                session_id="",
                evidence_level=EvidenceLevel.OBSERVATIONAL,
                category="test",
                detail="test",
                recorded_at="2026-07-25T10:00:00+00:00",
            )


class TestFailureReport:
    def test_create_report(self):
        report = FailureReport(
            session_id="sess-001",
            failure_class=FailureClass.PROVIDER_DISCONNECTED,
            attribution=FailureAttribution.EXTERNAL_FAILURE,
            evidence_ids=["ev-001", "ev-002"],
            failure_timestamp="2026-07-25T10:00:00+00:00",
            previous_status="active",
            resulting_status="recovering",
        )
        assert report.failure_class == FailureClass.PROVIDER_DISCONNECTED
        assert report.attribution == FailureAttribution.EXTERNAL_FAILURE
        assert len(report.evidence_ids) == 2
        assert report.secondary_causes == []

    def test_default_attribution_is_inconclusive(self):
        report = FailureReport(
            session_id="sess-001",
            failure_class=FailureClass.UNKNOWN_FAILURE,
            failure_timestamp="2026-07-25T10:00:00+00:00",
            previous_status="active",
            resulting_status="unrecoverable",
        )
        assert report.attribution == FailureAttribution.INCONCLUSIVE

    def test_with_secondary_causes(self):
        report = FailureReport(
            session_id="sess-001",
            failure_class=FailureClass.RUNTIME_FAILURE,
            failure_timestamp="2026-07-25T10:00:00+00:00",
            previous_status="active",
            resulting_status="force_closing",
            secondary_causes=["OOM_KILL", "CONTAINER_CRASH"],
        )
        assert len(report.secondary_causes) == 2


class TestRecoveryWindowConfig:
    def test_defaults(self):
        config = RecoveryWindowConfig()
        assert config.consumer_reconnect_timeout_seconds == 300
        assert config.consumer_acknowledgement_timeout_seconds == 120
        assert config.provider_reconnect_timeout_seconds == 300
        assert config.provider_runtime_restart_timeout_seconds == 180
        assert config.session_maximum_duration_seconds == 3600

    def test_custom_values(self):
        config = RecoveryWindowConfig(
            consumer_reconnect_timeout_seconds=60,
            provider_reconnect_timeout_seconds=120,
        )
        assert config.consumer_reconnect_timeout_seconds == 60
        assert config.provider_reconnect_timeout_seconds == 120

    def test_rejects_negative_timeout(self):
        with pytest.raises(ValueError):
            RecoveryWindowConfig(consumer_reconnect_timeout_seconds=-1)


class TestSessionFailureEvent:
    def test_create_event(self):
        event = SessionFailureEvent(
            session_id="sess-001",
            event_type="failure_detected",
            failure_class=FailureClass.PROVIDER_DISCONNECTED,
            previous_status="active",
            new_status="recovering",
            timestamp="2026-07-25T10:00:00+00:00",
        )
        assert event.event_type == "failure_detected"
        assert event.details == {}


class TestReputationEvent:
    def test_create_event(self):
        evt = ReputationEvent(
            session_id="sess-001",
            target_wallet="wallet-provider",
            failure_class=FailureClass.PROVIDER_DISCONNECTED,
            attribution=FailureAttribution.PROVIDER_AT_FAULT,
            evidence_level=EvidenceLevel.CRYPTOGRAPHIC,
            penalty_hint=0.3,
            timestamp="2026-07-25T10:00:00+00:00",
        )
        assert evt.penalty_hint == 0.3

    def test_penalty_hint_bounded(self):
        with pytest.raises(ValueError):
            ReputationEvent(
                session_id="sess-001",
                target_wallet="wallet-x",
                failure_class=FailureClass.UNKNOWN_FAILURE,
                attribution=FailureAttribution.INCONCLUSIVE,
                evidence_level=EvidenceLevel.OBSERVATIONAL,
                penalty_hint=1.5,
                timestamp="2026-07-25T10:00:00+00:00",
            )

    def test_default_penalty_hint_is_zero(self):
        evt = ReputationEvent(
            session_id="sess-001",
            target_wallet="wallet-x",
            failure_class=FailureClass.UNKNOWN_FAILURE,
            attribution=FailureAttribution.INCONCLUSIVE,
            evidence_level=EvidenceLevel.OBSERVATIONAL,
            timestamp="2026-07-25T10:00:00+00:00",
        )
        assert evt.penalty_hint == 0.0
