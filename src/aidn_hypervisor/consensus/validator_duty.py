"""Deterministic ECO-0006 validator duty and unbonding policy."""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, model_validator

if TYPE_CHECKING:
    from aidn_hypervisor.consensus.models import LedgerOperationEnvelope


class DutyClassification(str, Enum):
    """Protocol classification derived from one finalized duty window."""

    NORMAL = "NORMAL"
    MINOR_DOWNTIME = "MINOR_DOWNTIME"
    MAJOR_DOWNTIME = "MAJOR_DOWNTIME"
    PERSISTENT_DOWNTIME = "PERSISTENT_DOWNTIME"
    CONSENSUS_ABANDONMENT = "CONSENSUS_ABANDONMENT"


class ValidatorDutyPolicy(BaseModel, frozen=True):
    """Versioned integer thresholds from ECO-0006."""

    normal_threshold_bps: int = Field(default=9_000, ge=0, le=10_000)
    reward_threshold_bps: int = Field(default=8_000, ge=0, le=10_000)
    retention_threshold_bps: int = Field(default=6_700, ge=0, le=10_000)
    persistent_epochs: int = Field(default=3, ge=1)
    suspension_epochs: int = Field(default=7, ge=1)
    abandonment_suspension_epochs: int = Field(default=14, ge=1)

    @model_validator(mode="after")
    def _validate_threshold_order(self) -> ValidatorDutyPolicy:
        if not (
            self.normal_threshold_bps
            >= self.reward_threshold_bps
            >= self.retention_threshold_bps
        ):
            raise ValueError("validator duty thresholds must be descending")
        return self


class ValidatorDutyEvidence(BaseModel, frozen=True):
    """Finalized, request-independent observations for one active Epoch."""

    node_id: str
    epoch: int = Field(ge=0)
    expected_votes: int = Field(gt=0)
    signed_votes: int = Field(ge=0)
    consecutive_below_retention_epochs: int = Field(default=0, ge=0)
    exit_requested: bool = False
    evidence_root: str

    @model_validator(mode="after")
    def _validate_evidence(self) -> ValidatorDutyEvidence:
        if not self.node_id.strip():
            raise ValueError("node_id is required")
        if self.signed_votes > self.expected_votes:
            raise ValueError("signed_votes cannot exceed expected_votes")
        if not self.evidence_root.strip():
            raise ValueError("evidence_root is required")
        return self


class ValidatorDutyDecision(BaseModel, frozen=True):
    """Deterministic state/reward decision for a duty evidence object."""

    node_id: str
    epoch: int
    evidence_root: str
    participation_bps: int = Field(ge=0, le=10_000)
    classification: DutyClassification
    reward_eligible: bool
    retention_eligible: bool
    remove_from_active_set: bool
    suspension_until_epoch: int | None = Field(default=None, ge=0)
    slash_authorized: bool = False


class UnbondingReleaseDecision(BaseModel, frozen=True):
    """Deterministic result of checking a Stake release boundary."""

    request_epoch: int = Field(ge=0)
    completion_epoch: int = Field(ge=0)
    state: str
    releasable: bool
    reason: str


def evaluate_validator_duty(
    evidence: ValidatorDutyEvidence,
    *,
    policy: ValidatorDutyPolicy | None = None,
) -> ValidatorDutyDecision:
    """Evaluate one Epoch without minting, slashing or mutating state."""
    policy = policy or ValidatorDutyPolicy()
    participation_bps = evidence.signed_votes * 10_000 // evidence.expected_votes

    if evidence.signed_votes == 0 and not evidence.exit_requested:
        classification = DutyClassification.CONSENSUS_ABANDONMENT
    elif participation_bps >= policy.normal_threshold_bps:
        classification = DutyClassification.NORMAL
    elif participation_bps >= policy.reward_threshold_bps:
        classification = DutyClassification.MINOR_DOWNTIME
    elif participation_bps >= policy.retention_threshold_bps:
        classification = DutyClassification.MAJOR_DOWNTIME
    elif (
        evidence.signed_votes == 0
        or evidence.exit_requested
        or evidence.consecutive_below_retention_epochs >= policy.persistent_epochs
    ):
        classification = DutyClassification.PERSISTENT_DOWNTIME
    else:
        classification = DutyClassification.MAJOR_DOWNTIME

    is_abandoned = classification == DutyClassification.CONSENSUS_ABANDONMENT
    is_persistent = classification == DutyClassification.PERSISTENT_DOWNTIME
    removed = is_abandoned or is_persistent
    suspension_until: int | None = None
    if is_abandoned:
        suspension_until = evidence.epoch + policy.abandonment_suspension_epochs
    elif is_persistent:
        suspension_until = evidence.epoch + policy.suspension_epochs

    return ValidatorDutyDecision(
        node_id=evidence.node_id,
        epoch=evidence.epoch,
        evidence_root=evidence.evidence_root,
        participation_bps=participation_bps,
        classification=classification,
        reward_eligible=participation_bps >= policy.reward_threshold_bps
        and not removed,
        retention_eligible=participation_bps >= policy.retention_threshold_bps
        and not removed,
        remove_from_active_set=removed,
        suspension_until_epoch=suspension_until,
        slash_authorized=False,
    )


def build_participant_suspension_envelope(
    decision: ValidatorDutyDecision,
    *,
    evidence_operation_id: str,
    created_at: str,
    expires_at: str | None = None,
    initiator_id: str = "epoch-engine",
    protocol_version: str = "0.1",
    target_type: str = "CONSENSUS_SERVICE",
    scope: str = "CONSENSUS",
) -> LedgerOperationEnvelope:
    """Translate a finalized duty decision into a typed suspension operation."""
    if not decision.remove_from_active_set or decision.suspension_until_epoch is None:
        raise ValueError("duty decision does not require suspension")
    if not evidence_operation_id.strip():
        raise ValueError("evidence operation ID is required")
    if not created_at.strip() or not initiator_id.strip():
        raise ValueError("suspension envelope identity is required")
    if not target_type.strip() or not scope.strip():
        raise ValueError("suspension target scope is required")

    from aidn_hypervisor.consensus.models import LedgerOperationEnvelope

    evidence_references = sorted({evidence_operation_id, decision.evidence_root})
    return LedgerOperationEnvelope(
        operation_type="PARTICIPANT_SUSPEND",
        operation_version="1.0.0",
        protocol_version=protocol_version,
        origin_type="evidence_triggered",
        initiator_id=initiator_id,
        created_at=created_at,
        expires_at=expires_at,
        target_epoch=str(decision.epoch),
        payload={
            "target_id": decision.node_id,
            "target_type": target_type,
            "scope": scope,
            "reason_code": decision.classification.value,
            "evidence_root": decision.evidence_root,
            "effective_epoch": decision.epoch,
            "minimum_recovery_epoch": decision.suspension_until_epoch,
            "evidence_operation_id": evidence_operation_id,
        },
        evidence_references=evidence_references,
    )


def evaluate_unbonding_release(
    *,
    request_epoch: int,
    current_epoch: int,
    unresolved_misconduct: bool,
    obligations_complete: bool,
    unbonding_period_epochs: int = 14,
) -> UnbondingReleaseDecision:
    """Check whether a previously removed Validator may release Stake."""
    if isinstance(request_epoch, bool) or request_epoch < 0:
        raise ValueError("request_epoch is invalid")
    if isinstance(current_epoch, bool) or current_epoch < request_epoch:
        raise ValueError("current_epoch is invalid")
    if isinstance(unbonding_period_epochs, bool) or unbonding_period_epochs <= 0:
        raise ValueError("unbonding_period_epochs is invalid")

    completion_epoch = request_epoch + unbonding_period_epochs
    if current_epoch < completion_epoch:
        return UnbondingReleaseDecision(
            request_epoch=request_epoch,
            completion_epoch=completion_epoch,
            state="UNBONDING",
            releasable=False,
            reason="unbonding period has not completed",
        )
    if unresolved_misconduct:
        return UnbondingReleaseDecision(
            request_epoch=request_epoch,
            completion_epoch=completion_epoch,
            state="UNBONDING",
            releasable=False,
            reason="unresolved misconduct evidence blocks release",
        )
    if not obligations_complete:
        return UnbondingReleaseDecision(
            request_epoch=request_epoch,
            completion_epoch=completion_epoch,
            state="UNBONDING",
            releasable=False,
            reason="outstanding protocol obligations block release",
        )
    return UnbondingReleaseDecision(
        request_epoch=request_epoch,
        completion_epoch=completion_epoch,
        state="RELEASED",
        releasable=True,
        reason="unbonding period and release conditions completed",
    )
