"""M11-S4: Reward Distribution models."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, computed_field

# ── Constants ──────────────────────────────────────────────────────

# ECO-0005 §3: Base emission per epoch in q-atoms
BASE_EMISSION_Q_ATOMS: int = 5_000_000_000  # 5000Q

# ECO-0005 §12: Pool shares
CONSENSUS_POOL_SHARE: float = 0.30
REGISTRY_POOL_SHARE: float = 0.30
VALIDATION_POOL_SHARE: float = 0.30
FAUCET_POOL_SHARE: float = 0.10

# ECO-0004 §26: Minimum reward
MIN_REWARD_Q_ATOMS: int = 10_000  # 0.01Q

# ECO-0004 §21: Target independent groups
TARGET_CONSENSUS_GROUPS: int = 5
TARGET_REGISTRY_GROUPS: int = 5
TARGET_VALIDATION_GROUPS: int = 3


# ── Enums ─────────────────────────────────────────────────────────


class ServicePool(str, Enum):
    """Service reward pools."""

    CONSENSUS = "consensus"
    REGISTRY = "registry"
    VALIDATION = "validation"
    FAUCET = "faucet"


class MintStatus(str, Enum):
    """Mint operation status."""

    PENDING = "pending"
    EXECUTED = "executed"
    FAILED = "failed"


# ── Pool Configuration ───────────────────────────────────────────


class PoolConfig(BaseModel, frozen=True):
    """Configuration for service pool allocation."""

    consensus_share: float = CONSENSUS_POOL_SHARE
    registry_share: float = REGISTRY_POOL_SHARE
    validation_share: float = VALIDATION_POOL_SHARE
    faucet_share: float = FAUCET_POOL_SHARE
    target_consensus_groups: int = TARGET_CONSENSUS_GROUPS
    target_registry_groups: int = TARGET_REGISTRY_GROUPS
    target_validation_groups: int = TARGET_VALIDATION_GROUPS
    minimum_group_share_cap: float = 0.20

    @computed_field  # type: ignore[misc]
    @property
    def shares_sum(self) -> float:
        """Sum of all pool shares (should be 1.0)."""
        return (
            self.consensus_share
            + self.registry_share
            + self.validation_share
            + self.faucet_share
        )


# ── Reward Calculation ───────────────────────────────────────────


class RewardCalculation(BaseModel, frozen=True):
    """Individual reward calculation for a participant."""

    epoch: int
    participant_id: str
    service_pool: ServicePool
    raw_weight: float
    quality_factor: float
    maturity_factor: float
    health_factor: float
    duty_proof_factor: float
    reliability_factor: float
    final_reward: int  # q-atoms
    kcg_id: str | None = None
    kcg_share_percentage: float = 0.0

    @computed_field  # type: ignore[misc]
    @property
    def effective_weight(self) -> float:
        """Weight after quality factor applied."""
        return self.raw_weight * self.quality_factor


# ── Diversity Factor ─────────────────────────────────────────────


class DiversityFactor(BaseModel, frozen=True):
    """Diversity factor for a service pool."""

    service_pool: ServicePool
    independent_group_count: int
    target_independent_groups: int
    factor: float  # 0.0 - 1.0
    nominal_budget: int
    distributable_budget: int


# ── Group Concentration ──────────────────────────────────────────


class GroupConcentration(BaseModel, frozen=True):
    """Concentration info for a Known Control Group."""

    group_id: str
    service_pool: ServicePool
    group_share: float  # percentage of pool
    max_allowed_share: float  # concentration cap
    is_capped: bool
    capped_amount: int = 0
    redistributed_amount: int = 0


# ── Mint Operation ───────────────────────────────────────────────


class MintRecipient(BaseModel, frozen=True):
    """Single recipient in a mint operation."""

    participant_id: str
    wallet: str
    amount: int  # q-atoms
    service_pool: ServicePool


class MintOperation(BaseModel, frozen=True):
    """Deterministic mint operation for an epoch."""

    mint_id: str
    epoch: int
    total_minted: int
    base_emission: int
    recyclable_amount: int
    recipients: list[MintRecipient] = Field(default_factory=list)
    status: MintStatus = MintStatus.PENDING
    consensus_pool_used: int = 0
    registry_pool_used: int = 0
    validation_pool_used: int = 0
    faucet_pool_used: int = 0
    unused_consensus: int = 0
    unused_registry: int = 0
    unused_validation: int = 0
    unused_faucet: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)

    @computed_field  # type: ignore[misc]
    @property
    def recipient_count(self) -> int:
        return len(self.recipients)

    @computed_field  # type: ignore[misc]
    @property
    def total_allocated(self) -> int:
        """Total amount allocated to recipients."""
        return sum(r.amount for r in self.recipients)


# ── Epoch Reward Budget ─────────────────────────────────────────


class EpochRewardBudget(BaseModel, frozen=True):
    """Budget for an epoch's reward distribution."""

    epoch: int
    base_emission: int = BASE_EMISSION_Q_ATOMS
    recyclable_amount: int = 0
    consensus_pool: int = 0
    registry_pool: int = 0
    validation_pool: int = 0
    faucet_pool: int = 0

    @computed_field  # type: ignore[misc]
    @property
    def total_budget(self) -> int:
        return self.base_emission + self.recyclable_amount

    @computed_field  # type: ignore[misc]
    @property
    def pool_total(self) -> int:
        return (
            self.consensus_pool
            + self.registry_pool
            + self.validation_pool
            + self.faucet_pool
        )
