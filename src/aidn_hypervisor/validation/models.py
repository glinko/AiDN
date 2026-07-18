import hashlib
import json
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator

ValidationRequestStatus = Literal[
    "draft",
    "bond_locked",
    "queued",
    "assigned",
    "authorization_issued",
    "report_submitted",
    "passed",
    "failed",
    "superseded",
    "revoked",
    "forfeited",
]
CertificationStatus = Literal[
    "uncertified",
    "pending_initial",
    "certified",
    "certified_with_issues",
    "maintenance_due",
    "maintenance_in_progress",
    "revoked",
    "superseded",
]
ValidationSnapshotStatus = Literal[
    "unvalidated",
    "pending_initial",
    "validated",
]
ValidationRequestKind = Literal["initial", "maintenance"]
ValidationBondStatus = Literal[
    "locked",
    "partially_released",
    "released",
    "forfeited",
]
ValidationReportRecommendation = Literal[
    "certify",
    "certify_with_issues",
    "do_not_certify",
]
ValidationEpochStatus = Literal["open", "assigned", "closed"]
ValidationAuthorizationStatus = Literal["issued", "consumed", "expired"]
EvidenceScalar = str | int | float | bool | None
EvidenceMap = dict[str, EvidenceScalar]
ValidationEvidenceAccessClass = Literal[
    "public",
    "encrypted",
    "restricted",
    "hash_committed",
]
ValidationCustodyStatus = Literal[
    "available",
    "temporarily_unavailable",
    "withheld",
    "lost",
    "corrupted",
    "access_restricted",
]


def expected_validation_status_for(
    certification_status: CertificationStatus,
) -> ValidationSnapshotStatus:
    if certification_status == "uncertified":
        return "unvalidated"
    if certification_status == "pending_initial":
        return "pending_initial"
    return "validated"


class ValidationRequest(BaseModel):
    request_id: str
    endpoint_id: str
    configuration_hash: str
    owner_wallet: str
    minimum_session_deposit_q: float = Field(default=0.0, ge=0.0)
    request_kind: ValidationRequestKind = "initial"
    status: ValidationRequestStatus
    created_at: str
    bond_id: str
    epoch_id: str | None = None
    assignment_id: str | None = None
    authorization_id: str | None = None
    superseded_at: str | None = None


class ValidationBond(BaseModel):
    bond_id: str
    owner_wallet: str
    endpoint_id: str
    configuration_hash: str
    amount_q: float = Field(ge=0.0)
    remaining_locked_q: float = Field(ge=0.0)
    released_q: float = Field(ge=0.0)
    forfeited_q: float = Field(ge=0.0)
    escrow_adapter: str
    escrow_reference: str
    status: ValidationBondStatus

    @model_validator(mode="after")
    def _validate_totals(self):
        total = sum(
            Decimal(str(value))
            for value in (
                self.remaining_locked_q,
                self.released_q,
                self.forfeited_q,
            )
        )
        amount = Decimal(str(self.amount_q))
        if total > amount:
            raise ValueError("bond allocations cannot exceed amount_q")
        return self


class ValidationDetectedIssue(BaseModel):
    issue_id: str
    severity: str | None = None
    summary: str | None = None
    details: EvidenceMap = Field(default_factory=dict)


class ValidationReport(BaseModel):
    report_id: str
    request_id: str
    endpoint_id: str
    configuration_hash: str
    report_kind: ValidationRequestKind
    validator_id: str | None = None
    validator_label: str
    capability_id: str | None = None
    test_description: str | None = None
    request_summary: str | None = None
    response_summary: str | None = None
    observations: list[str] = Field(default_factory=list)
    measured_metrics: EvidenceMap = Field(default_factory=dict)
    protocol_compliance: EvidenceMap = Field(default_factory=dict)
    accounting_verification: EvidenceMap = Field(default_factory=dict)
    detected_issues: list[ValidationDetectedIssue] = Field(default_factory=list)
    critical_issue_count: int = Field(default=0, ge=0)
    warning_issue_count: int = Field(default=0, ge=0)
    recommendation: ValidationReportRecommendation
    evidence_summary: str
    signed_payload: EvidenceMap = Field(default_factory=dict)
    created_at: str


def canonical_validation_report_body(report: ValidationReport) -> dict:
    """Returns the immutable report body without local identity or signature wrappers."""
    body = report.model_dump(mode="json")
    for field_name in ("report_id", "signed_payload"):
        body.pop(field_name, None)
    return body


def canonical_validation_report_bytes(report: ValidationReport) -> bytes:
    return json.dumps(
        canonical_validation_report_body(report),
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_validation_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def validation_report_integrity(report: ValidationReport) -> tuple[str, int]:
    encoded = canonical_validation_report_bytes(report)
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}", len(encoded)


class ValidationReportCommitment(BaseModel):
    commitment_id: str
    report_id: str
    report_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    report_size: int = Field(ge=0)
    request_id: str
    assignment_id: str | None = None
    endpoint_id: str
    configuration_hash: str
    capability_id: str | None = None
    capability_version: str | None = None
    validator_service_id: str | None = None
    validation_epoch_id: str | None = None
    conclusion: ValidationReportRecommendation
    limitation_codes: list[str] = Field(default_factory=list)
    failure_codes: list[str] = Field(default_factory=list)
    observation_codes: list[str] = Field(default_factory=list)
    evidence_root: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    evidence_access_class: ValidationEvidenceAccessClass = "public"
    retention_policy_id: str = "legacy-local-state-v1"
    report_locator: str
    storage_receipt_hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    storage_failure_reference: str | None = None
    created_at: str

    @model_validator(mode="after")
    def _validate_storage_outcome(self):
        if self.storage_receipt_hash and self.storage_failure_reference:
            raise ValueError(
                "storage_receipt_hash and storage_failure_reference are mutually exclusive"
            )
        return self


class ValidationReportStorageReceipt(BaseModel):
    receipt_id: str
    validation_id: str
    endpoint_id: str
    endpoint_configuration_hash: str
    report_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    report_size: int = Field(ge=0)
    stored_at: str
    report_locator: str
    retention_policy_id: str
    endpoint_public_key: str
    endpoint_signature: str


class ValidationReportStorageFailure(BaseModel):
    failure_id: str
    validation_id: str
    endpoint_id: str
    endpoint_configuration_hash: str
    report_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    report_size: int = Field(ge=0)
    report_locator: str
    failure_code: str = Field(min_length=1, max_length=128)
    failure_evidence_root: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    reported_by: str | None = None
    attempted_at: str


class ValidationReportTransferEnvelope(BaseModel):
    transfer_id: str
    report_id: str
    request_id: str
    assignment_id: str
    authorization_id: str
    endpoint_id: str
    endpoint_configuration_hash: str
    report_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    report_size: int = Field(ge=0)
    report_locator: str
    created_at: str


class ValidationReportCustodyState(BaseModel):
    report_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    endpoint_id: str
    configuration_hash: str
    status: ValidationCustodyStatus
    last_checked_at: str | None = None
    last_available_at: str | None = None
    grace_expires_at: str | None = None
    failure_streak: int = Field(default=0, ge=0)
    latest_challenge_id: str | None = None
    mirror_available: bool | None = None


class ValidationReportCustodyObject(BaseModel):
    report_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    report_size: int = Field(ge=0)
    storage_relative_path: str
    stored_at: str

    @model_validator(mode="after")
    def _validate_relative_path(self):
        parts = self.storage_relative_path.replace("\\", "/").split("/")
        if not self.storage_relative_path or any(part in {"", ".", ".."} for part in parts):
            raise ValueError("storage_relative_path must be a safe relative path")
        return self


class ValidationStatusSnapshot(BaseModel):
    endpoint_id: str
    configuration_hash: str
    certification_status: CertificationStatus = "uncertified"
    validation_status: ValidationSnapshotStatus = "unvalidated"
    latest_request_id: str | None = None
    latest_report_id: str | None = None
    latest_report_at: str | None = None
    validated_at: str | None = None
    superseded_at: str | None = None
    maintenance_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _validate_validated_status(self):
        expected_status = expected_validation_status_for(self.certification_status)
        if "validation_status" not in self.model_fields_set:
            self.validation_status = expected_status
        elif self.validation_status != expected_status:
            raise ValueError(
                "validation_status must be consistent with certification_status"
            )
        if self.validation_status == "validated" and not (
            self.latest_request_id and self.latest_request_id.strip()
        ):
            raise ValueError("validated status requires latest_request_id")
        return self


class ValidationEpoch(BaseModel):
    epoch_id: str
    seed: str
    status: ValidationEpochStatus
    created_at: str


class ValidationValidatorEntry(BaseModel):
    validator_id: str
    validator_label: str
    shares: int = Field(ge=1)
    capability_profiles: list[str] = Field(default_factory=list)
    contribution_q: float = Field(default=0.0, ge=0.0)
    wallet_exposed: bool = False


class ValidationAssignment(BaseModel):
    assignment_id: str
    epoch_id: str
    request_id: str
    validator_id: str
    assigned_at: str


class ValidationAuthorization(BaseModel):
    authorization_id: str
    request_id: str
    epoch_id: str
    authorization_token: str
    guarantee_q: float = Field(ge=0.0)
    issued_at: str
    expires_at: str
    status: ValidationAuthorizationStatus
