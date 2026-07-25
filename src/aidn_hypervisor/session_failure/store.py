"""Session Failure Evidence Store — separate persistence for RFC-0060 evidence."""

from aidn_hypervisor.session_failure.models import (
    FailureEvidenceRecord,
    FailureReport,
)


class SessionFailureEvidenceStore:
    """In-memory store for failure evidence and reports.

    Separate from SessionStore so failure evidence can be audited
    independently of Session lifecycle state.
    """

    def __init__(self) -> None:
        # session_id -> list[FailureEvidenceRecord]
        self._evidence: dict[str, list[FailureEvidenceRecord]] = {}
        # session_id -> FailureReport
        self._reports: dict[str, FailureReport] = {}

    # ------------------------------------------------------------------
    # Evidence
    # ------------------------------------------------------------------

    def add_evidence(
        self, session_id: str, record: FailureEvidenceRecord
    ) -> FailureEvidenceRecord:
        """Persist a single evidence record for a session."""
        if session_id not in self._evidence:
            self._evidence[session_id] = []
        self._evidence[session_id].append(record)
        return record

    def get_evidence_for_session(
        self, session_id: str
    ) -> list[FailureEvidenceRecord]:
        """Return all evidence records for a session."""
        return list(self._evidence.get(session_id, []))

    def has_evidence(self, session_id: str) -> bool:
        """Return True when at least one evidence record exists."""
        return session_id in self._evidence and len(self._evidence[session_id]) > 0

    def evidence_count(self, session_id: str) -> int:
        """Return the number of evidence records for a session."""
        return len(self._evidence.get(session_id, []))

    # ------------------------------------------------------------------
    # Reports
    # ------------------------------------------------------------------

    def save_report(self, report: FailureReport) -> FailureReport:
        """Persist or update a failure report for a session."""
        self._reports[report.session_id] = report
        return report

    def get_report(self, session_id: str) -> FailureReport | None:
        """Return the failure report for a session, or None."""
        return self._reports.get(session_id)

    def has_report(self, session_id: str) -> bool:
        """Return True when a failure report exists for the session."""
        return session_id in self._reports

    # ------------------------------------------------------------------
    # Bulk / utility
    # ------------------------------------------------------------------

    def get_all_session_ids(self) -> list[str]:
        """Return all session IDs that have evidence or reports."""
        ids = set(self._evidence.keys()) | set(self._reports.keys())
        return sorted(ids)

    def clear_session(self, session_id: str) -> None:
        """Remove all evidence and reports for a session."""
        self._evidence.pop(session_id, None)
        self._reports.pop(session_id, None)

    def reset(self) -> None:
        """Clear all data (testing only)."""
        self._evidence.clear()
        self._reports.clear()
