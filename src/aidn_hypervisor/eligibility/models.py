"""M11-S3: Participant Eligibility + Anti-Sybil models."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, computed_field

# ── Constants ──────────────────────────────────────────────────────

# ECO-0006 §8: Minimum activation age in epochs
ACTIVATION_AGE_EPOCHS: int = 10

# ECO-0004 §15: Minimum service health threshold
MIN_SERVICE_HEALTH: float = 0.70

# ECO-0004 §23: Minimum group share cap
MIN_GROUP_SHARE_CAP: float = 0.20

# ECO-0004 §21: Target independent groups per pool
TARGET_CONSENSUS_GROUPS: int = 5
TARGET_REGISTRY_GROUPS: int = 5
TARGET_VALIDATION_GROUPS: int = 3


# ── Enums ──────────────────────────────────────────────────────────


class EligibilityState(str, Enum):
    """Participant eligibility state machine."""

    PENDING = "pending"
    ACTIVE = "active"
    INELIGIBLE = "ineligible"
    SUSPENDED = "suspended"
    RETIRED = "retired"


class IneligibilityReason(str, Enum):
    """Reasons a participant can become ineligible."""

    INSUFFICIENT_STAKE = "insufficient_stake"
    HEALTH_BELOW_THRESHOLD = "health_below_threshold"
    ACTIVATION_AGE_NOT_MET = "activation_age_not_met"
    SUSPENDED = "suspended"
    DUTY_PROOF_MISSING = "duty_proof_missing"
    PROTOCOL_VERSION_MISMATCH = "protocol_version_mismatch"
    BOND_FORFEITED = "bond_forfeited"


# ── Activation Record ─────────────────────────────────────────────


class ActivationRecord(BaseModel, frozen=True):
    """Records when a participant activated their service."""

    service_id: str
    activated_at_epoch: int
    operator_wallet: str
    initial_stake: int


# ── Eligibility Gate Result ───────────────────────────────────────


class GateCheck(BaseModel, frozen=True):
    """Result of a single eligibility gate."""

    gate_name: str
    passed: bool
    detail: str = ""


class EligibilityGateResult(BaseModel, frozen=True):
    """Result of running all eligibility gates for a participant."""

    service_id: str
    epoch: int
    eligible: bool
    checks: list[GateCheck]
    ineligibility_reasons: list[IneligibilityReason] = Field(default_factory=list)

    @computed_field  # type: ignore[misc]
    @property
    def passed_count(self) -> int:
        return sum(1 for c in self.checks if c.passed)

    @computed_field  # type: ignore[misc]
    @property
    def failed_count(self) -> int:
        return sum(1 for c in self.checks if not c.passed)


# ── Known Control Group (KCG) ─────────────────────────────────────


class KnownControlGroup(BaseModel, frozen=True):
    """Group of services controlled by the same entity (anti-Sybil).

    Detected via shared reward beneficiary wallets, operator wallets,
    or explicit declarations.
    """

    group_id: str
    reward_beneficiary: str
    member_service_ids: list[str] = Field(default_factory=list)
    total_stake: int = 0
    aggregate_weight: float = 0.0
    concentration_percentage: float = 0.0
    detected_at_epoch: int
    last_updated_epoch: int

    @computed_field  # type: ignore[misc]
    @property
    def member_count(self) -> int:
        return len(self.member_service_ids)

    @computed_field  # type: ignore[misc]
    @property
    def exceeds_concentration_cap(self) -> bool:
        """Whether this group exceeds the minimum group share cap."""
        return self.concentration_percentage > (100.0 * (1 - MIN_GROUP_SHARE_CAP))


class KCGMembership(BaseModel, frozen=True):
    """Membership of a service in a Known Control Group."""

    service_id: str
    group_id: str
    joined_at_epoch: int
    stake_contribution: int


# ── Eligibility Snapshot ──────────────────────────────────────────


class EligibilitySnapshot(BaseModel, frozen=True):
    """Frozen eligibility state for an epoch."""

    epoch: int
    service_id: str
    state: EligibilityState
    rating_score: float
    health_score: float
    kcg_id: str | None = None
    activation_age: int
    has_duty_proof: bool
    notes: dict[str, Any] = Field(default_factory=dict)
