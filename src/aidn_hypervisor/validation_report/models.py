"""M11-S6: Validation Report + Certification models."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


# ── Enums ─────────────────────────────────────────────────────────


class CertificationStatus(str, Enum):
    """Endpoint certification status."""

    UNVALIDATED = "unvalidated"
    VALIDATION_PENDING = "validation_pending"
    CERTIFIED = "certified"
    DE_CERTIFIED = "de_certified"
    UNDER_REVALIDATION = "under_revalidation"


class ValidationRecommendation(str, Enum):
    """Validator recommendation."""

    CERTIFY = "certify"
    DE_CERTIFY = "de_certify"
    CONDITIONAL = "conditional"


class MaintenanceTriggerType(str, Enum):
    """Types of maintenance validation triggers."""

    DECREASING_REPUTATION = "decreasing_reputation"
    INCREASED_LATENCY = "increased_latency"
    INCREASED_ERROR_RATE = "increased_error_rate"
    SUSPICIOUS_BEHAVIOR = "suspicious_behavior"
    RANDOM_EPOCH = "random_epoch"
    PERIODIC = "periodic"


class EvidenceType(str, Enum):
    """Types of validation evidence."""

    PERFORMANCE_METRIC = "performance_metric"
    RESPONSE_SAMPLE = "response_sample"
    LATENCY_MEASUREMENT = "latency_measurement"
    ERROR_RATE = "error_rate"
    REPUTATION_SCORE = "reputation_score"
    BEHAVIORAL_ANOMALY = "behavioral_anomaly"


# ── Report Evidence ─────────────────────────────────────────────


class ReportEvidence(BaseModel, frozen=True):
    """Single piece of evidence in a validation report."""

    evidence_type: EvidenceType
    description: str
    value: float | None = None
    threshold: float | None = None
    passed: bool | None = None
    timestamp_epoch: int


# ── Validation Report ───────────────────────────────────────────


class ValidationReport(BaseModel, frozen=True):
    """Validation report for an endpoint."""

    report_id: str
    endpoint_id: str
    validator_id: str
    epoch: int
    recommendation: ValidationRecommendation
    evidence: list[ReportEvidence] = Field(default_factory=list)
    certification_status: CertificationStatus
    signed_at_epoch: int
    notes: str = ""

    @property
    def evidence_count(self) -> int:
        return len(self.evidence)

    @property
    def passing_evidence_count(self) -> int:
        return sum(
            1 for e in self.evidence
            if e.passed is True
        )

    @property
    def failing_evidence_count(self) -> int:
        return sum(
            1 for e in self.evidence
            if e.passed is False
        )


# ── Maintenance Trigger ────────────────────────────────────────


class MaintenanceTrigger(BaseModel, frozen=True):
    """Trigger for maintenance validation."""

    trigger_type: MaintenanceTriggerType
    endpoint_id: str
    epoch_detected: int
    severity: float  # 0.0 - 1.0
    metric_value: float | None = None
    metric_threshold: float | None = None
    description: str = ""


# ── Endpoint Validation State ─────────────────────────────────


class EndpointValidationState(BaseModel, frozen=True):
    """Current validation state of an endpoint."""

    endpoint_id: str
    certification_status: CertificationStatus
    last_validation_epoch: int
    next_scheduled_epoch: int | None = None
    validation_count: int = 0
    successful_validations: int = 0
    failed_validations: int = 0
    last_report_id: str | None = None
    trigger_count: int = 0

    @property
    def success_rate(self) -> float:
        """Calculate validation success rate."""
        if self.validation_count == 0:
            return 1.0
        return self.successful_validations / self.validation_count
