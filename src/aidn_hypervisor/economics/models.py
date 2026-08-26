from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator

RecyclableRemovalCategory = Literal[
    "network_fee",
    "validation_bond_forfeiture",
    "penalty",
]


class RecyclableRemoval(BaseModel):
    sequence_id: int = Field(ge=1)
    removal_id: str = Field(min_length=1)
    category: RecyclableRemovalCategory
    amount_q: float = Field(ge=0.0)
    owner_id: str = Field(min_length=1)
    removed_at: str = Field(min_length=1)
    source_event_type: str = Field(min_length=1)
    source_reference: str = Field(min_length=1)
    source_epoch_id: str | None = None


class FaucetClaim(BaseModel):
    sequence_id: int = Field(ge=1)
    claim_id: str = Field(min_length=1)
    epoch_id: str = Field(min_length=1)
    wallet_id: str = Field(min_length=1)
    node_id: str = Field(min_length=1)
    operator_id: str = Field(min_length=1)
    amount_q: float = Field(ge=0.0)
    active_local_endpoint_count: int = Field(ge=0)
    claimed_at: str = Field(min_length=1)


class EpochRewardPoolShares(BaseModel):
    contribution: float = Field(ge=0.0, le=1.0)
    consensus: float = Field(ge=0.0, le=1.0)
    registry: float = Field(ge=0.0, le=1.0)
    validation: float = Field(ge=0.0, le=1.0)
    faucet: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _validate_total(self):
        total = sum(
            Decimal(str(value))
            for value in (
                self.contribution,
                self.consensus,
                self.registry,
                self.validation,
                self.faucet,
            )
        )
        if total != Decimal("1.0"):
            raise ValueError("epoch reward pool shares must sum to 1.0")
        return self


class EpochRewardBudget(BaseModel):
    epoch_id: str = Field(min_length=1)
    derived_at: str = "1970-01-01T00:00:00+00:00"
    base_emission_q: float = Field(ge=0.0)
    eligible_removed_q: float = Field(default=0.0, ge=0.0)
    recycle_backlog_q: float = Field(default=0.0, ge=0.0)
    recyclable_amount_q: float = Field(default=0.0, ge=0.0)
    faucet_carryover_q: float = Field(default=0.0, ge=0.0)
    total_authorized_q: float = Field(default=0.0, ge=0.0)
    contribution_budget_q: float = Field(default=0.0, ge=0.0)
    consensus_budget_q: float = Field(default=0.0, ge=0.0)
    registry_budget_q: float = Field(default=0.0, ge=0.0)
    validation_budget_q: float = Field(default=0.0, ge=0.0)
    faucet_budget_q: float = Field(default=0.0, ge=0.0)
    active_hypervisor_count: int = Field(default=0, ge=0)
    faucet_share_q: float = Field(default=0.0, ge=0.0)
    pool_shares: EpochRewardPoolShares

    @model_validator(mode="after")
    def _derive_values(self):
        recyclable_amount = round(self.eligible_removed_q + self.recycle_backlog_q, 6)
        total_authorized = round(self.base_emission_q + recyclable_amount, 6)
        contribution_budget = round(total_authorized * self.pool_shares.contribution, 6)
        consensus_budget = round(total_authorized * self.pool_shares.consensus, 6)
        registry_budget = round(total_authorized * self.pool_shares.registry, 6)
        validation_budget = round(total_authorized * self.pool_shares.validation, 6)
        faucet_budget = round(
            (total_authorized * self.pool_shares.faucet) + self.faucet_carryover_q,
            6,
        )
        faucet_share = (
            round(faucet_budget / self.active_hypervisor_count, 6)
            if self.active_hypervisor_count > 0
            else 0.0
        )
        self.recyclable_amount_q = recyclable_amount
        self.total_authorized_q = total_authorized
        self.contribution_budget_q = contribution_budget
        self.consensus_budget_q = consensus_budget
        self.registry_budget_q = registry_budget
        self.validation_budget_q = validation_budget
        self.faucet_budget_q = faucet_budget
        self.faucet_share_q = faucet_share
        return self
