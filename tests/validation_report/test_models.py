"""M11-S6: Validation report models — unit tests."""

from __future__ import annotations

from aidn_hypervisor.validation_report.models import (
    CertificationStatus,
    EndpointValidationState,
    EvidenceType,
    MaintenanceTrigger,
    MaintenanceTriggerType,
    ReportEvidence,
    ValidationRecommendation,
    ValidationReport,
)


class TestCertificationStatus:
    def test_all_statuses(self):
        assert len(CertificationStatus) == 5


class TestValidationRecommendation:
    def test_all_recommendations(self):
        assert len(ValidationRecommendation) == 3


class TestMaintenanceTriggerType:
    def test_all_trigger_types(self):
        assert len(MaintenanceTriggerType) == 6


class TestEvidenceType:
    def test_all_evidence_types(self):
        assert len(EvidenceType) == 6


class TestReportEvidence:
    def test_create(self):
        e = ReportEvidence(
            evidence_type=EvidenceType.PERFORMANCE_METRIC,
            description="Latency check",
            value=0.85,
            threshold=0.70,
            passed=True,
            timestamp_epoch=1,
        )
        assert e.passed is True


class TestValidationReport:
    def test_create(self):
        r = ValidationReport(
            report_id="vr-1",
            endpoint_id="ep-1",
            validator_id="val-1",
            epoch=1,
            recommendation=ValidationRecommendation.CERTIFY,
            certification_status=CertificationStatus.CERTIFIED,
            signed_at_epoch=1,
        )
        assert r.evidence_count == 0

    def test_evidence_counts(self):
        evidence = [
            ReportEvidence(
                evidence_type=EvidenceType.PERFORMANCE_METRIC,
                description="p1",
                passed=True,
                timestamp_epoch=1,
            ),
            ReportEvidence(
                evidence_type=EvidenceType.LATENCY_MEASUREMENT,
                description="p2",
                passed=False,
                timestamp_epoch=1,
            ),
        ]
        r = ValidationReport(
            report_id="vr-1",
            endpoint_id="ep-1",
            validator_id="val-1",
            epoch=1,
            recommendation=ValidationRecommendation.CONDITIONAL,
            evidence=evidence,
            certification_status=CertificationStatus.CERTIFIED,
            signed_at_epoch=1,
        )
        assert r.evidence_count == 2
        assert r.passing_evidence_count == 1
        assert r.failing_evidence_count == 1


class TestEndpointValidationState:
    def test_create(self):
        s = EndpointValidationState(
            endpoint_id="ep-1",
            certification_status=CertificationStatus.CERTIFIED,
            last_validation_epoch=5,
        )
        assert s.success_rate == 1.0

    def test_success_rate(self):
        s = EndpointValidationState(
            endpoint_id="ep-1",
            certification_status=CertificationStatus.CERTIFIED,
            last_validation_epoch=5,
            validation_count=10,
            successful_validations=8,
            failed_validations=2,
        )
        assert s.success_rate == 0.8

    def test_success_rate_zero_validations(self):
        s = EndpointValidationState(
            endpoint_id="ep-1",
            certification_status=CertificationStatus.UNVALIDATED,
            last_validation_epoch=0,
        )
        assert s.success_rate == 1.0


class TestMaintenanceTrigger:
    def test_create(self):
        t = MaintenanceTrigger(
            trigger_type=MaintenanceTriggerType.DECREASING_REPUTATION,
            endpoint_id="ep-1",
            epoch_detected=5,
            severity=0.7,
        )
        assert t.severity == 0.7
