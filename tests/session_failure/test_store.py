"""Tests for session_failure.store — RFC-0060 evidence store."""

import pytest

from aidn_hypervisor.session_failure.models import (
    EvidenceLevel,
    FailureAttribution,
    FailureClass,
    FailureEvidenceRecord,
    FailureReport,
)
from aidn_hypervisor.session_failure.store import SessionFailureEvidenceStore


@pytest.fixture
def store():
    return SessionFailureEvidenceStore()


class TestEvidenceCRUD:
    def test_add_and_get_evidence(self, store):
        record = FailureEvidenceRecord(
            session_id="sess-001",
            evidence_level=EvidenceLevel.OBSERVATIONAL,
            category="transport_timeout",
            detail="Connection lost",
            recorded_at="2026-07-25T10:00:00+00:00",
        )
        store.add_evidence("sess-001", record)
        evidence = store.get_evidence_for_session("sess-001")
        assert len(evidence) == 1
        assert evidence[0].category == "transport_timeout"

    def test_add_multiple_evidence_records(self, store):
        for i in range(3):
            store.add_evidence(
                "sess-001",
                FailureEvidenceRecord(
                    session_id="sess-001",
                    evidence_level=EvidenceLevel.OBSERVATIONAL,
                    category=f"event_{i}",
                    detail=f"Detail {i}",
                    recorded_at="2026-07-25T10:00:00+00:00",
                ),
            )
        assert store.evidence_count("sess-001") == 3

    def test_get_evidence_for_unknown_session(self, store):
        evidence = store.get_evidence_for_session("nonexistent")
        assert evidence == []

    def test_has_evidence_true(self, store):
        store.add_evidence(
            "sess-001",
            FailureEvidenceRecord(
                session_id="sess-001",
                evidence_level=EvidenceLevel.OBSERVATIONAL,
                category="test",
                detail="test",
                recorded_at="2026-07-25T10:00:00+00:00",
            ),
        )
        assert store.has_evidence("sess-001") is True

    def test_has_evidence_false(self, store):
        assert store.has_evidence("sess-001") is False

    def test_evidence_count_zero(self, store):
        assert store.evidence_count("sess-001") == 0


class TestReportCRUD:
    def test_save_and_get_report(self, store):
        report = FailureReport(
            session_id="sess-001",
            failure_class=FailureClass.PROVIDER_DISCONNECTED,
            attribution=FailureAttribution.EXTERNAL_FAILURE,
            failure_timestamp="2026-07-25T10:00:00+00:00",
            previous_status="active",
            resulting_status="recovering",
        )
        store.save_report(report)
        retrieved = store.get_report("sess-001")
        assert retrieved is not None
        assert retrieved.failure_class == FailureClass.PROVIDER_DISCONNECTED

    def test_get_report_unknown_session(self, store):
        assert store.get_report("nonexistent") is None

    def test_has_report_true(self, store):
        store.save_report(
            FailureReport(
                session_id="sess-001",
                failure_class=FailureClass.UNKNOWN_FAILURE,
                failure_timestamp="2026-07-25T10:00:00+00:00",
                previous_status="active",
                resulting_status="unrecoverable",
            )
        )
        assert store.has_report("sess-001") is True

    def test_has_report_false(self, store):
        assert store.has_report("sess-001") is False

    def test_save_report_overwrites(self, store):
        store.save_report(
            FailureReport(
                session_id="sess-001",
                failure_class=FailureClass.PROVIDER_DISCONNECTED,
                failure_timestamp="2026-07-25T10:00:00+00:00",
                previous_status="active",
                resulting_status="recovering",
            )
        )
        store.save_report(
            FailureReport(
                session_id="sess-001",
                failure_class=FailureClass.RUNTIME_FAILURE,
                failure_timestamp="2026-07-25T11:00:00+00:00",
                previous_status="recovering",
                resulting_status="force_closing",
            )
        )
        report = store.get_report("sess-001")
        assert report.failure_class == FailureClass.RUNTIME_FAILURE


class TestBulkOperations:
    def test_get_all_session_ids_empty(self, store):
        assert store.get_all_session_ids() == []

    def test_get_all_session_ids_mixed(self, store):
        store.add_evidence(
            "sess-001",
            FailureEvidenceRecord(
                session_id="sess-001",
                evidence_level=EvidenceLevel.OBSERVATIONAL,
                category="test",
                detail="test",
                recorded_at="2026-07-25T10:00:00+00:00",
            ),
        )
        store.save_report(
            FailureReport(
                session_id="sess-002",
                failure_class=FailureClass.UNKNOWN_FAILURE,
                failure_timestamp="2026-07-25T10:00:00+00:00",
                previous_status="active",
                resulting_status="unrecoverable",
            )
        )
        ids = store.get_all_session_ids()
        assert "sess-001" in ids
        assert "sess-002" in ids

    def test_clear_session(self, store):
        store.add_evidence(
            "sess-001",
            FailureEvidenceRecord(
                session_id="sess-001",
                evidence_level=EvidenceLevel.OBSERVATIONAL,
                category="test",
                detail="test",
                recorded_at="2026-07-25T10:00:00+00:00",
            ),
        )
        store.save_report(
            FailureReport(
                session_id="sess-001",
                failure_class=FailureClass.UNKNOWN_FAILURE,
                failure_timestamp="2026-07-25T10:00:00+00:00",
                previous_status="active",
                resulting_status="unrecoverable",
            )
        )
        store.clear_session("sess-001")
        assert not store.has_evidence("sess-001")
        assert not store.has_report("sess-001")

    def test_reset(self, store):
        store.add_evidence(
            "sess-001",
            FailureEvidenceRecord(
                session_id="sess-001",
                evidence_level=EvidenceLevel.OBSERVATIONAL,
                category="test",
                detail="test",
                recorded_at="2026-07-25T10:00:00+00:00",
            ),
        )
        store.reset()
        assert not store.has_evidence("sess-001")
        assert store.get_all_session_ids() == []
