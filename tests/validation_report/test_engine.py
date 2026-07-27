"""M11-S6: Validation Report Engine — unit tests."""

from __future__ import annotations

from aidn_hypervisor.validation_report.engine import ValidationReportEngine
from aidn_hypervisor.validation_report.models import (
    CertificationStatus,
    EvidenceType,
    ReportEvidence,
    ValidationRecommendation,
)


class TestReportCreation:
    def test_create_certify_report(self):
        engine = ValidationReportEngine()
        report = engine.create_report(
            endpoint_id="ep-1",
            validator_id="val-1",
            epoch=1,
            recommendation=ValidationRecommendation.CERTIFY,
            evidence=[],
        )
        assert report.certification_status == CertificationStatus.CERTIFIED
        assert report.endpoint_id == "ep-1"

    def test_create_decertify_report(self):
        engine = ValidationReportEngine()
        report = engine.create_report(
            endpoint_id="ep-1",
            validator_id="val-1",
            epoch=1,
            recommendation=ValidationRecommendation.DE_CERTIFY,
            evidence=[],
        )
        assert report.certification_status == CertificationStatus.DE_CERTIFIED

    def test_create_conditional_report(self):
        engine = ValidationReportEngine()
        report = engine.create_report(
            endpoint_id="ep-1",
            validator_id="val-1",
            epoch=1,
            recommendation=ValidationRecommendation.CONDITIONAL,
            evidence=[],
        )
        # Conditional maps to CERTIFIED
        assert report.certification_status == CertificationStatus.CERTIFIED

    def test_with_evidence(self):
        engine = ValidationReportEngine()
        evidence = [
            ReportEvidence(
                evidence_type=EvidenceType.PERFORMANCE_METRIC,
                description="Latency OK",
                value=0.85,
                threshold=0.70,
                passed=True,
                timestamp_epoch=1,
            ),
        ]
        report = engine.create_report(
            endpoint_id="ep-1",
            validator_id="val-1",
            epoch=1,
            recommendation=ValidationRecommendation.CERTIFY,
            evidence=evidence,
        )
        assert report.evidence_count == 1


class TestReportQueries:
    def test_get_report(self):
        engine = ValidationReportEngine()
        report = engine.create_report(
            endpoint_id="ep-1",
            validator_id="val-1",
            epoch=1,
            recommendation=ValidationRecommendation.CERTIFY,
            evidence=[],
        )
        fetched = engine.get_report(report.report_id)
        assert fetched is not None
        assert fetched.report_id == report.report_id

    def test_get_report_not_found(self):
        engine = ValidationReportEngine()
        fetched = engine.get_report("nonexistent")
        assert fetched is None

    def test_get_reports_for_endpoint(self):
        engine = ValidationReportEngine()
        engine.create_report(
            endpoint_id="ep-1",
            validator_id="val-1",
            epoch=1,
            recommendation=ValidationRecommendation.CERTIFY,
            evidence=[],
        )
        engine.create_report(
            endpoint_id="ep-1",
            validator_id="val-2",
            epoch=2,
            recommendation=ValidationRecommendation.CERTIFY,
            evidence=[],
        )
        reports = engine.get_reports_for_endpoint("ep-1")
        assert len(reports) == 2

    def test_get_latest_report(self):
        engine = ValidationReportEngine()
        engine.create_report(
            endpoint_id="ep-1",
            validator_id="val-1",
            epoch=1,
            recommendation=ValidationRecommendation.CERTIFY,
            evidence=[],
        )
        engine.create_report(
            endpoint_id="ep-1",
            validator_id="val-1",
            epoch=5,
            recommendation=ValidationRecommendation.DE_CERTIFY,
            evidence=[],
        )
        latest = engine.get_latest_report("ep-1")
        assert latest is not None
        assert latest.epoch == 5

    def test_get_latest_none(self):
        engine = ValidationReportEngine()
        latest = engine.get_latest_report("unknown")
        assert latest is None


class TestCertificationStatus:
    def test_default_unvalidated(self):
        engine = ValidationReportEngine()
        status = engine.get_certification_status("ep-1")
        assert status == CertificationStatus.UNVALIDATED

    def test_status_from_latest(self):
        engine = ValidationReportEngine()
        engine.create_report(
            endpoint_id="ep-1",
            validator_id="val-1",
            epoch=1,
            recommendation=ValidationRecommendation.CERTIFY,
            evidence=[],
        )
        status = engine.get_certification_status("ep-1")
        assert status == CertificationStatus.CERTIFIED

    def test_status_overwrites(self):
        engine = ValidationReportEngine()
        engine.create_report(
            endpoint_id="ep-1",
            validator_id="val-1",
            epoch=1,
            recommendation=ValidationRecommendation.CERTIFY,
            evidence=[],
        )
        engine.create_report(
            endpoint_id="ep-1",
            validator_id="val-1",
            epoch=2,
            recommendation=ValidationRecommendation.DE_CERTIFY,
            evidence=[],
        )
        status = engine.get_certification_status("ep-1")
        assert status == CertificationStatus.DE_CERTIFIED

    def test_report_count(self):
        engine = ValidationReportEngine()
        engine.create_report(
            endpoint_id="ep-1",
            validator_id="val-1",
            epoch=1,
            recommendation=ValidationRecommendation.CERTIFY,
            evidence=[],
        )
        engine.create_report(
            endpoint_id="ep-1",
            validator_id="val-2",
            epoch=2,
            recommendation=ValidationRecommendation.CERTIFY,
            evidence=[],
        )
        count = engine.get_endpoint_report_count("ep-1")
        assert count == 2
