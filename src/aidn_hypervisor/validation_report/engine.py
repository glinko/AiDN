"""M11-S6: Validation Report Engine — report creation, certification."""

from __future__ import annotations

import hashlib

from aidn_hypervisor.validation_report.models import (
    CertificationStatus,
    ValidationRecommendation,
    ValidationReport,
)


class ValidationReportEngine:
    """Creates and manages validation reports.

    Report lifecycle:
    1. Validator creates report with evidence
    2. Engine derives certification status from recommendation
    3. Report is stored and queryable
    """

    def __init__(self) -> None:
        # report_id → ValidationReport
        self._reports: dict[str, ValidationReport] = {}
        # endpoint_id → list of report_ids
        self._endpoint_reports: dict[str, list[str]] = {}

    def create_report(
        self,
        *,
        endpoint_id: str,
        validator_id: str,
        epoch: int,
        recommendation: ValidationRecommendation,
        evidence: list,
        notes: str = "",
    ) -> ValidationReport:
        """Create a validation report.

        Args:
            endpoint_id: Endpoint being validated.
            validator_id: Validator creating the report.
            epoch: Epoch of validation.
            recommendation: Validator recommendation.
            evidence: List of ReportEvidence items.
            notes: Optional notes.

        Returns:
            ValidationReport with derived certification status.
        """
        report_id = self._generate_report_id(
            endpoint_id, validator_id, epoch
        )
        status = self._derive_status(recommendation)

        report = ValidationReport(
            report_id=report_id,
            endpoint_id=endpoint_id,
            validator_id=validator_id,
            epoch=epoch,
            recommendation=recommendation,
            evidence=evidence,
            certification_status=status,
            signed_at_epoch=epoch,
            notes=notes,
        )

        self._reports[report_id] = report
        self._endpoint_reports.setdefault(endpoint_id, []).append(report_id)

        return report

    def get_report(
        self, report_id: str
    ) -> ValidationReport | None:
        """Get a report by ID."""
        return self._reports.get(report_id)

    def get_reports_for_endpoint(
        self, endpoint_id: str
    ) -> list[ValidationReport]:
        """Get all reports for an endpoint."""
        report_ids = self._endpoint_reports.get(endpoint_id, [])
        return [
            self._reports[rid]
            for rid in report_ids
            if rid in self._reports
        ]

    def get_latest_report(
        self, endpoint_id: str
    ) -> ValidationReport | None:
        """Get the latest report for an endpoint."""
        reports = self.get_reports_for_endpoint(endpoint_id)
        if not reports:
            return None
        return max(reports, key=lambda r: r.epoch)

    def get_certification_status(
        self, endpoint_id: str
    ) -> CertificationStatus:
        """Get current certification status for an endpoint.

        Based on the latest report's certification status.
        """
        latest = self.get_latest_report(endpoint_id)
        if latest is None:
            return CertificationStatus.UNVALIDATED
        return latest.certification_status

    def get_endpoint_report_count(
        self, endpoint_id: str
    ) -> int:
        """Get number of reports for an endpoint."""
        return len(self._endpoint_reports.get(endpoint_id, []))

    # ── Internal ───────────────────────────────────────────────

    @staticmethod
    def _derive_status(
        recommendation: ValidationRecommendation,
    ) -> CertificationStatus:
        """Derive certification status from recommendation."""
        mapping = {
            ValidationRecommendation.CERTIFY: CertificationStatus.CERTIFIED,
            ValidationRecommendation.DE_CERTIFY: CertificationStatus.DE_CERTIFIED,
            ValidationRecommendation.CONDITIONAL: CertificationStatus.CERTIFIED,
        }
        return mapping.get(recommendation, CertificationStatus.CERTIFIED)

    @staticmethod
    def _generate_report_id(
        endpoint_id: str, validator_id: str, epoch: int
    ) -> str:
        """Generate deterministic report ID."""
        raw = f"vr:{endpoint_id}:{validator_id}:{epoch}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]
