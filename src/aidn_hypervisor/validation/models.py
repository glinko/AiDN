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
ValidationSnapshotStatus = Literal[
    "unvalidated",
    "pending_initial",
    "validated",
    "maintenance_due",
    "maintenance_in_progress",
    "validation_failed",
    "revoked",
    "superseded",
]
ValidationRequestKind = Literal["initial", "maintenance"]
ValidationBondStatus = Literal[
    "locked",
    "partially_released",
    "released",
    "forfeited",
]
ValidationReportOutcome = Literal["pass", "fail"]
ValidationEpochStatus = Literal["open", "assigned", "closed"]
ValidationAuthorizationStatus = Literal["issued", "consumed", "expired"]


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


class ValidationReport(BaseModel):
    report_id: str
    request_id: str
    endpoint_id: str
    configuration_hash: str
    outcome: ValidationReportOutcome
    report_kind: ValidationRequestKind
    validator_label: str
    evidence_summary: str
    signed_payload: dict = Field(default_factory=dict)
    created_at: str


class ValidationStatusSnapshot(BaseModel):
    endpoint_id: str
    configuration_hash: str
    status: ValidationSnapshotStatus
    latest_request_id: str | None = None
    latest_report_id: str | None = None
    validated_at: str | None = None
    superseded_at: str | None = None
    maintenance_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _validate_validated_status(self):
        if self.status == "validated" and not (
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
