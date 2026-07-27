"""M11-S5: Epoch Transition + Recycling models."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ── Enums ─────────────────────────────────────────────────────────


class RecyclingSource(str, Enum):
    """Sources of recyclable Q."""

    NETWORK_FEE = "network_fee"
    VALIDATOR_PENALTY = "validator_penalty"
    BOND_FORFEIT = "bond_forfeit"
    CONSENSUS_SLASH = "consensus_slash"
    UNUSED_REWARD = "unused_reward"


class RecyclingStatus(str, Enum):
    """Recyclable Q status."""

    PENDING = "pending"
    RECYCLED = "recycled"
    EXPIRED = "expired"


class FaucetConstraint(str, Enum):
    """Anti-Sybil constraints for Faucet allocation."""

    PER_WALLET_LIMIT = "per_wallet_limit"
    PER_KCG_LIMIT = "per_kcg_limit"
    EPOCH_COOLDOWN = "epoch_cooldown"


# ── Recyclable Record ───────────────────────────────────────────


class RecyclableRecord(BaseModel, frozen=True):
    """Tracks Q entering the recycling pipeline."""

    source: RecyclingSource
    amount: int  # q-atoms
    epoch_removed: int
    epoch_recycled: int | None = None
    status: RecyclingStatus = RecyclingStatus.PENDING
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Faucet Allocation ───────────────────────────────────────────


class FaucetAllocation(BaseModel, frozen=True):
    """Faucet allocation for an epoch."""

    epoch: int
    total_faucet_budget: int
    allocated_amount: int
    unallocated_amount: int
    per_wallet_limit: int
    per_kcg_limit: int
    cooldown_epochs: int = 1
    allocations: list[FaucetRecipient] = Field(default_factory=list)


class FaucetRecipient(BaseModel, frozen=True):
    """Single faucet recipient."""

    wallet: str
    amount: int
    kcg_id: str | None = None


# ── Emission Record ─────────────────────────────────────────────


class EmissionRecord(BaseModel, frozen=True):
    """Auditable emission record for an epoch."""

    epoch: int
    base_emission: int
    recyclable_amount: int = 0
    total_budget: int = 0
    consensus_allocated: int = 0
    registry_allocated: int = 0
    validation_allocated: int = 0
    faucet_allocated: int = 0
    total_minted: int = 0
    unused_base: int = 0
    unused_recyclable: int = 0


# ── Epoch Transition State ──────────────────────────────────────


class EpochTransitionState(str, Enum):
    """States of an epoch transition."""

    IN_PROGRESS = "in_progress"
    EVIDENCE_FROZEN = "evidence_frozen"
    REWARDS_CALCULATED = "rewards_calculated"
    MINT_GENERATED = "mint_generated"
    MINT_EXECUTED = "mint_executed"
    COMPLETE = "complete"
    FAILED = "failed"


class EpochTransitionRecord(BaseModel, frozen=True):
    """Immutable record of an epoch transition."""

    epoch: int
    started_at_epoch: int
    state: EpochTransitionState
    budget: EmissionRecord
    participant_count: int = 0
    reward_recipient_count: int = 0
    recyclable_records_count: int = 0
    notes: dict[str, Any] = Field(default_factory=dict)
