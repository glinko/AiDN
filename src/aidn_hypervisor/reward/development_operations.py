"""Typed ECO-0007 Ledger operation boundary.

Calculation envelopes are consensus-applicable as immutable evidence, pool
allocation/carryover envelopes are source-bound reserve records, bounty
envelopes apply a bounded lifecycle, reward reserve envelopes bind a calculated
schedule to that pool reserve, payment envelopes consume verified stages, and
unclaimed envelopes preserve stages without a Wallet. Claim envelopes consume
one unclaimed stage through an RFC-0068 signed Wallet binding. Finalized
commitment, cancellation and correction envelopes preserve the exact evidence
set without minting Q. Reward transitions are not aliases for ``REWARD_MINT``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from aidn_hypervisor.consensus.coverage import operation_coverage
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.reward.development_activation import (
    DevelopmentRewardActivationApproval,
    verify_development_reward_activation_approval,
)
from aidn_hypervisor.reward.development_adjustments import DevelopmentRewardStateSnapshot
from aidn_hypervisor.reward.development_bounty import (
    DevelopmentBounty,
    DevelopmentBountyExpiry,
    DevelopmentBountyRelease,
    DevelopmentBountyReservation,
)
from aidn_hypervisor.reward.development_cancellation import DevelopmentRewardCancellationRecord
from aidn_hypervisor.reward.development_carryover import DevelopmentPoolCarryoverRecord
from aidn_hypervisor.reward.development_claim import DevelopmentRewardWalletBindingProof
from aidn_hypervisor.reward.development_commitments import DevelopmentRewardCommitment
from aidn_hypervisor.reward.development_correction import DevelopmentRewardCorrectionRecord
from aidn_hypervisor.reward.development_distribution import (
    DevelopmentRewardCalculation,
    DevelopmentRole,
    canonical_hash,
)
from aidn_hypervisor.reward.development_finalized_commitments import (
    development_reward_finalized_commitment_id,
)
from aidn_hypervisor.reward.development_pool import (
    DEVELOPMENT_POOL_ID,
    build_development_pool_allocation,
)
from aidn_hypervisor.reward.development_reserve import build_development_reward_reserve
from aidn_hypervisor.reward.development_unclaimed import build_development_reward_unclaimed_record

DEVELOPMENT_REWARD_OPERATION_VERSION = "eco-0007-operation.v1"
DEVELOPMENT_REWARD_CONSENSUS_OPERATION_VERSION = "1.0.0"
DEVELOPMENT_REWARD_ENGINE_ID = "development-reward-engine"

DevelopmentRewardOperationType = Literal[
    "DEVELOPMENT_POOL_ALLOCATE",
    "DEVELOPMENT_POOL_CARRYOVER",
    "DEVELOPMENT_BOUNTY_CREATE",
    "DEVELOPMENT_BOUNTY_RESERVE",
    "DEVELOPMENT_BOUNTY_RELEASE",
    "DEVELOPMENT_BOUNTY_EXPIRE",
    "DEVELOPMENT_REWARD_CALCULATE",
    "DEVELOPMENT_REWARD_RESERVE",
    "DEVELOPMENT_REWARD_PAY_IMMEDIATE",
    "DEVELOPMENT_REWARD_PAY_MATURITY",
    "DEVELOPMENT_REWARD_MARK_UNCLAIMED",
    "DEVELOPMENT_REWARD_CLAIM",
    "DEVELOPMENT_REWARD_EXPIRE_UNCLAIMED",
    "DEVELOPMENT_REWARD_FINALIZE_COMMITMENT",
    "DEVELOPMENT_REWARD_CANCEL_UNVESTED",
    "DEVELOPMENT_REWARD_CORRECT",
]

_POOL_AMOUNT_OPERATIONS = {
    "DEVELOPMENT_POOL_ALLOCATE",
    "DEVELOPMENT_POOL_CARRYOVER",
}
_BOUNTY_OPERATIONS = {
    "DEVELOPMENT_BOUNTY_CREATE",
    "DEVELOPMENT_BOUNTY_RESERVE",
    "DEVELOPMENT_BOUNTY_RELEASE",
    "DEVELOPMENT_BOUNTY_EXPIRE",
}
_REWARD_AMOUNT_OPERATIONS = {
    "DEVELOPMENT_REWARD_RESERVE",
    "DEVELOPMENT_REWARD_PAY_IMMEDIATE",
    "DEVELOPMENT_REWARD_PAY_MATURITY",
    "DEVELOPMENT_REWARD_MARK_UNCLAIMED",
    "DEVELOPMENT_REWARD_CLAIM",
    "DEVELOPMENT_REWARD_EXPIRE_UNCLAIMED",
    "DEVELOPMENT_REWARD_CANCEL_UNVESTED",
}
_PAYMENT_OPERATIONS = {
    "DEVELOPMENT_REWARD_PAY_IMMEDIATE",
    "DEVELOPMENT_REWARD_PAY_MATURITY",
}
_UNCLAIMED_OPERATIONS = {
    "DEVELOPMENT_REWARD_MARK_UNCLAIMED",
}
_EXPIRY_OPERATIONS = {
    "DEVELOPMENT_REWARD_EXPIRE_UNCLAIMED",
}
_FINALIZED_COMMITMENT_OPERATIONS = {
    "DEVELOPMENT_REWARD_FINALIZE_COMMITMENT",
}
_CLAIM_OPERATIONS = {
    "DEVELOPMENT_REWARD_CLAIM",
}
_PAYMENT_EVIDENCE_OPERATIONS = _PAYMENT_OPERATIONS | _UNCLAIMED_OPERATIONS | _EXPIRY_OPERATIONS


class DevelopmentRewardOperationRequest(BaseModel, frozen=True):
    """Operation-specific data required to build a future catalog envelope."""

    operation_type: DevelopmentRewardOperationType
    created_at: str = Field(min_length=1)
    commitment: DevelopmentRewardCommitment
    activation_approval: DevelopmentRewardActivationApproval | None = None
    calculation: DevelopmentRewardCalculation | None = None
    target_epoch: int | None = Field(default=None, ge=0)
    pool_id: str = Field(default=DEVELOPMENT_POOL_ID, min_length=1)
    amount_q_atoms: int | None = Field(default=None, ge=0)
    calculation_operation_id: str | None = None
    source_epoch_transition_operation_id: str | None = None
    pool_budget_reference: str | None = None
    pool_allocation_id: str | None = None
    pool_allocation_operation_id: str | None = None
    reserve_id: str | None = None
    reserve_operation_id: str | None = None
    bounty_id: str | None = None
    bounty_hash: str | None = None
    bounty: DevelopmentBounty | None = None
    bounty_reservation: DevelopmentBountyReservation | None = None
    bounty_release: DevelopmentBountyRelease | None = None
    bounty_expiry: DevelopmentBountyExpiry | None = None
    pool_carryover: DevelopmentPoolCarryoverRecord | None = None
    reward_id: str | None = None
    contribution_id: str | None = None
    contributor_id: str | None = None
    recipient_wallet: str | None = None
    role: DevelopmentRole | None = None
    payment_hash: str | None = None
    unclaimed_id: str | None = None
    unclaimed_operation_id: str | None = None
    claim_epoch: int | None = Field(default=None, ge=0)
    expiry_epoch: int | None = Field(default=None, ge=0)
    return_destination: Literal["CARRYOVER"] | None = None
    finalization_epoch: int | None = Field(default=None, ge=0)
    reserve_operation_ids: list[str] = Field(default_factory=list)
    payment_operation_ids: list[str] = Field(default_factory=list)
    unclaimed_operation_ids: list[str] = Field(default_factory=list)
    claim_operation_ids: list[str] = Field(default_factory=list)
    expiry_operation_ids: list[str] = Field(default_factory=list)
    source_operation_root: str | None = None
    reserve_root: str | None = None
    payment_root: str | None = None
    unclaimed_root: str | None = None
    claim_root: str | None = None
    expiry_root: str | None = None
    wallet_binding: DevelopmentRewardWalletBindingProof | None = None
    payment_stage: (
        Literal[
            "IMMEDIATE",
            "MATURITY_STAGE_ONE",
            "MATURITY_STAGE_TWO",
        ]
        | None
    ) = None
    correction_id: str | None = None
    correction_delta_q_atoms: int | None = None
    reward_state_snapshot: DevelopmentRewardStateSnapshot | None = None
    reward_cancellation: DevelopmentRewardCancellationRecord | None = None
    reward_correction: DevelopmentRewardCorrectionRecord | None = None

    @model_validator(mode="after")
    def validate_operation_fields(self) -> DevelopmentRewardOperationRequest:
        if self.operation_type in {
            "DEVELOPMENT_REWARD_CALCULATE",
            "DEVELOPMENT_POOL_ALLOCATE",
            "DEVELOPMENT_REWARD_RESERVE",
            "DEVELOPMENT_REWARD_PAY_IMMEDIATE",
            "DEVELOPMENT_REWARD_PAY_MATURITY",
            "DEVELOPMENT_REWARD_MARK_UNCLAIMED",
            "DEVELOPMENT_REWARD_CLAIM",
            "DEVELOPMENT_REWARD_EXPIRE_UNCLAIMED",
            "DEVELOPMENT_REWARD_FINALIZE_COMMITMENT",
        }:
            if self.calculation is None:
                raise ValueError("DEVELOPMENT_OPERATION_CALCULATION_REQUIRED")
            if self.calculation.calculation_root != self.commitment.calculation_root:
                raise ValueError("DEVELOPMENT_OPERATION_CALCULATION_MISMATCH")
        if self.operation_type == "DEVELOPMENT_POOL_ALLOCATE":
            if self.amount_q_atoms is None or self.amount_q_atoms <= 0:
                raise ValueError("DEVELOPMENT_OPERATION_AMOUNT_REQUIRED")
            if not self.calculation_operation_id or not self.calculation_operation_id.strip():
                raise ValueError("DEVELOPMENT_OPERATION_CALCULATION_OPERATION_REQUIRED")
            if not self.source_epoch_transition_operation_id or not self.source_epoch_transition_operation_id.strip():
                raise ValueError("DEVELOPMENT_OPERATION_EPOCH_TRANSITION_REQUIRED")
            if not self.pool_budget_reference or not self.pool_budget_reference.strip():
                raise ValueError("DEVELOPMENT_OPERATION_POOL_BUDGET_REFERENCE_REQUIRED")
        if self.operation_type == "DEVELOPMENT_POOL_CARRYOVER":
            if self.pool_carryover is None:
                raise ValueError("DEVELOPMENT_OPERATION_CARRYOVER_REQUIRED")
            if self.amount_q_atoms != self.pool_carryover.carried_q_atoms:
                raise ValueError("DEVELOPMENT_OPERATION_CARRYOVER_AMOUNT_MISMATCH")
            if self.target_epoch is None or self.target_epoch != self.pool_carryover.target_epoch:
                raise ValueError("DEVELOPMENT_OPERATION_CARRYOVER_EPOCH_MISMATCH")
        if self.operation_type == "DEVELOPMENT_REWARD_RESERVE":
            if not self.calculation_operation_id or not self.calculation_operation_id.strip():
                raise ValueError("DEVELOPMENT_OPERATION_CALCULATION_OPERATION_REQUIRED")
            if not self.pool_allocation_id or not self.pool_allocation_id.strip():
                raise ValueError("DEVELOPMENT_OPERATION_POOL_ALLOCATION_REQUIRED")
            if not self.pool_allocation_operation_id or not self.pool_allocation_operation_id.strip():
                raise ValueError("DEVELOPMENT_OPERATION_POOL_ALLOCATION_OPERATION_REQUIRED")
        if self.operation_type in _POOL_AMOUNT_OPERATIONS and self.amount_q_atoms is None:
            raise ValueError("DEVELOPMENT_OPERATION_AMOUNT_REQUIRED")
        if self.operation_type in _BOUNTY_OPERATIONS:
            if not self.bounty_id or not self.bounty_id.strip():
                raise ValueError("DEVELOPMENT_OPERATION_BOUNTY_REQUIRED")
            if self.operation_type == "DEVELOPMENT_BOUNTY_CREATE" and (
                not self.bounty_hash or not self.bounty_hash.strip()
            ):
                raise ValueError("DEVELOPMENT_OPERATION_BOUNTY_HASH_REQUIRED")
            if self.operation_type != "DEVELOPMENT_BOUNTY_CREATE" and (
                self.amount_q_atoms is None or self.amount_q_atoms <= 0
            ):
                raise ValueError("DEVELOPMENT_OPERATION_AMOUNT_REQUIRED")
            record = {
                "DEVELOPMENT_BOUNTY_CREATE": self.bounty,
                "DEVELOPMENT_BOUNTY_RESERVE": self.bounty_reservation,
                "DEVELOPMENT_BOUNTY_RELEASE": self.bounty_release,
                "DEVELOPMENT_BOUNTY_EXPIRE": self.bounty_expiry,
            }[self.operation_type]
            if record is None:
                raise ValueError("DEVELOPMENT_OPERATION_BOUNTY_RECORD_REQUIRED")
            record_bounty_id = getattr(record, "bounty_id", None)
            if record_bounty_id != self.bounty_id:
                raise ValueError("DEVELOPMENT_OPERATION_BOUNTY_ID_MISMATCH")
            if self.operation_type == "DEVELOPMENT_BOUNTY_CREATE":
                if self.bounty_hash != self.bounty.bounty_hash:
                    raise ValueError("DEVELOPMENT_OPERATION_BOUNTY_HASH_MISMATCH")
            elif self.operation_type == "DEVELOPMENT_BOUNTY_RESERVE":
                if self.amount_q_atoms != self.bounty_reservation.amount_q_atoms:
                    raise ValueError("DEVELOPMENT_OPERATION_BOUNTY_AMOUNT_MISMATCH")
                if not self.pool_allocation_id or not self.pool_allocation_operation_id:
                    raise ValueError("DEVELOPMENT_OPERATION_BOUNTY_POOL_ALLOCATION_REQUIRED")
            elif self.operation_type == "DEVELOPMENT_BOUNTY_RELEASE":
                if self.amount_q_atoms != self.bounty_release.released_q_atoms:
                    raise ValueError("DEVELOPMENT_OPERATION_BOUNTY_AMOUNT_MISMATCH")
            elif self.operation_type == "DEVELOPMENT_BOUNTY_EXPIRE":
                if self.amount_q_atoms != self.bounty_expiry.returned_q_atoms:
                    raise ValueError("DEVELOPMENT_OPERATION_BOUNTY_AMOUNT_MISMATCH")
        if self.operation_type in _REWARD_AMOUNT_OPERATIONS:
            if not self.reward_id or not self.reward_id.strip():
                raise ValueError("DEVELOPMENT_OPERATION_REWARD_REQUIRED")
            if self.amount_q_atoms is None or self.amount_q_atoms <= 0:
                raise ValueError("DEVELOPMENT_OPERATION_AMOUNT_REQUIRED")
        if self.operation_type in _PAYMENT_OPERATIONS:
            if not self.contributor_id or not self.contributor_id.strip():
                raise ValueError("DEVELOPMENT_OPERATION_CONTRIBUTOR_REQUIRED")
            if not self.recipient_wallet or not self.recipient_wallet.strip():
                raise ValueError("DEVELOPMENT_OPERATION_WALLET_REQUIRED")
            expected_stage = "IMMEDIATE" if self.operation_type == "DEVELOPMENT_REWARD_PAY_IMMEDIATE" else None
            if expected_stage is not None and self.payment_stage != expected_stage:
                raise ValueError("DEVELOPMENT_OPERATION_PAYMENT_STAGE_INVALID")
            if self.operation_type == "DEVELOPMENT_REWARD_PAY_MATURITY" and self.payment_stage not in {
                "MATURITY_STAGE_ONE",
                "MATURITY_STAGE_TWO",
            }:
                raise ValueError("DEVELOPMENT_OPERATION_PAYMENT_STAGE_INVALID")
        if self.operation_type in {
            "DEVELOPMENT_REWARD_PAY_IMMEDIATE",
            "DEVELOPMENT_REWARD_PAY_MATURITY",
        }:
            if not self.calculation_operation_id or not self.calculation_operation_id.strip():
                raise ValueError("DEVELOPMENT_OPERATION_CALCULATION_OPERATION_REQUIRED")
            if not self.pool_allocation_id or not self.pool_allocation_id.strip():
                raise ValueError("DEVELOPMENT_OPERATION_POOL_ALLOCATION_REQUIRED")
            if not self.pool_allocation_operation_id or not self.pool_allocation_operation_id.strip():
                raise ValueError("DEVELOPMENT_OPERATION_POOL_ALLOCATION_OPERATION_REQUIRED")
            if not self.reserve_id or not self.reserve_id.strip():
                raise ValueError("DEVELOPMENT_OPERATION_REWARD_RESERVE_REQUIRED")
            if not self.reserve_operation_id or not self.reserve_operation_id.strip():
                raise ValueError("DEVELOPMENT_OPERATION_REWARD_RESERVE_OPERATION_REQUIRED")
            if not self.payment_hash or not self.payment_hash.strip():
                raise ValueError("DEVELOPMENT_OPERATION_PAYMENT_HASH_REQUIRED")
            if self.role is None:
                raise ValueError("DEVELOPMENT_OPERATION_ROLE_REQUIRED")
            if self.operation_type == "DEVELOPMENT_REWARD_PAY_MATURITY" and (
                not self.source_epoch_transition_operation_id or not self.source_epoch_transition_operation_id.strip()
            ):
                raise ValueError("DEVELOPMENT_OPERATION_EPOCH_TRANSITION_REQUIRED")
        if self.operation_type in _UNCLAIMED_OPERATIONS:
            if self.recipient_wallet is not None:
                raise ValueError("DEVELOPMENT_OPERATION_UNCLAIMED_WALLET_FORBIDDEN")
            if not self.contributor_id or not self.contributor_id.strip():
                raise ValueError("DEVELOPMENT_OPERATION_CONTRIBUTOR_REQUIRED")
            if not self.calculation_operation_id or not self.calculation_operation_id.strip():
                raise ValueError("DEVELOPMENT_OPERATION_CALCULATION_OPERATION_REQUIRED")
            if not self.pool_allocation_id or not self.pool_allocation_id.strip():
                raise ValueError("DEVELOPMENT_OPERATION_POOL_ALLOCATION_REQUIRED")
            if not self.pool_allocation_operation_id or not self.pool_allocation_operation_id.strip():
                raise ValueError("DEVELOPMENT_OPERATION_POOL_ALLOCATION_OPERATION_REQUIRED")
            if not self.reserve_id or not self.reserve_id.strip():
                raise ValueError("DEVELOPMENT_OPERATION_REWARD_RESERVE_REQUIRED")
            if not self.reserve_operation_id or not self.reserve_operation_id.strip():
                raise ValueError("DEVELOPMENT_OPERATION_REWARD_RESERVE_OPERATION_REQUIRED")
            if not self.payment_hash or not self.payment_hash.strip():
                raise ValueError("DEVELOPMENT_OPERATION_PAYMENT_HASH_REQUIRED")
            if self.role is None:
                raise ValueError("DEVELOPMENT_OPERATION_ROLE_REQUIRED")
            if self.payment_stage not in {
                "IMMEDIATE",
                "MATURITY_STAGE_ONE",
                "MATURITY_STAGE_TWO",
            }:
                raise ValueError("DEVELOPMENT_OPERATION_PAYMENT_STAGE_INVALID")
        if self.operation_type in _EXPIRY_OPERATIONS:
            if self.recipient_wallet is not None:
                raise ValueError("DEVELOPMENT_OPERATION_EXPIRY_WALLET_FORBIDDEN")
            if not self.unclaimed_id or not self.unclaimed_id.strip():
                raise ValueError("DEVELOPMENT_OPERATION_UNCLAIMED_REQUIRED")
            if not self.unclaimed_operation_id or not self.unclaimed_operation_id.strip():
                raise ValueError("DEVELOPMENT_OPERATION_UNCLAIMED_OPERATION_REQUIRED")
            if not self.source_epoch_transition_operation_id or not self.source_epoch_transition_operation_id.strip():
                raise ValueError("DEVELOPMENT_OPERATION_EPOCH_TRANSITION_REQUIRED")
            if self.expiry_epoch is None:
                raise ValueError("DEVELOPMENT_OPERATION_EXPIRY_EPOCH_REQUIRED")
            if self.return_destination != "CARRYOVER":
                raise ValueError("DEVELOPMENT_OPERATION_EXPIRY_DESTINATION_INVALID")
            if not self.contributor_id or not self.contributor_id.strip():
                raise ValueError("DEVELOPMENT_OPERATION_CONTRIBUTOR_REQUIRED")
            if not self.calculation_operation_id or not self.calculation_operation_id.strip():
                raise ValueError("DEVELOPMENT_OPERATION_CALCULATION_OPERATION_REQUIRED")
            if not self.pool_allocation_id or not self.pool_allocation_id.strip():
                raise ValueError("DEVELOPMENT_OPERATION_POOL_ALLOCATION_REQUIRED")
            if not self.pool_allocation_operation_id or not self.pool_allocation_operation_id.strip():
                raise ValueError("DEVELOPMENT_OPERATION_POOL_ALLOCATION_OPERATION_REQUIRED")
            if not self.reserve_id or not self.reserve_id.strip():
                raise ValueError("DEVELOPMENT_OPERATION_REWARD_RESERVE_REQUIRED")
            if not self.reserve_operation_id or not self.reserve_operation_id.strip():
                raise ValueError("DEVELOPMENT_OPERATION_REWARD_RESERVE_OPERATION_REQUIRED")
            if not self.payment_hash or not self.payment_hash.strip():
                raise ValueError("DEVELOPMENT_OPERATION_PAYMENT_HASH_REQUIRED")
            if self.role is None:
                raise ValueError("DEVELOPMENT_OPERATION_ROLE_REQUIRED")
            if self.payment_stage not in {
                "IMMEDIATE",
                "MATURITY_STAGE_ONE",
                "MATURITY_STAGE_TWO",
            }:
                raise ValueError("DEVELOPMENT_OPERATION_PAYMENT_STAGE_INVALID")
        if self.operation_type in _FINALIZED_COMMITMENT_OPERATIONS:
            if not self.calculation_operation_id or not self.calculation_operation_id.strip():
                raise ValueError("DEVELOPMENT_OPERATION_CALCULATION_OPERATION_REQUIRED")
            if not self.pool_allocation_id or not self.pool_allocation_id.strip():
                raise ValueError("DEVELOPMENT_OPERATION_POOL_ALLOCATION_REQUIRED")
            if not self.pool_allocation_operation_id or not self.pool_allocation_operation_id.strip():
                raise ValueError("DEVELOPMENT_OPERATION_POOL_ALLOCATION_OPERATION_REQUIRED")
            if not self.source_epoch_transition_operation_id or not self.source_epoch_transition_operation_id.strip():
                raise ValueError("DEVELOPMENT_OPERATION_EPOCH_TRANSITION_REQUIRED")
            if self.finalization_epoch is None:
                raise ValueError("DEVELOPMENT_OPERATION_FINALIZATION_EPOCH_REQUIRED")
            if not self.reserve_operation_ids:
                raise ValueError("DEVELOPMENT_OPERATION_RESERVE_OPERATIONS_REQUIRED")
            for field_name in (
                "source_operation_root",
                "reserve_root",
                "payment_root",
                "unclaimed_root",
                "claim_root",
                "expiry_root",
            ):
                value = getattr(self, field_name)
                if not value or not value.strip():
                    raise ValueError(f"DEVELOPMENT_OPERATION_{field_name.upper()}_REQUIRED")
        if self.operation_type in _CLAIM_OPERATIONS:
            if not self.contribution_id or not self.contribution_id.strip():
                raise ValueError("DEVELOPMENT_OPERATION_CONTRIBUTION_ID_REQUIRED")
            if not self.contributor_id or not self.contributor_id.strip():
                raise ValueError("DEVELOPMENT_OPERATION_CONTRIBUTOR_REQUIRED")
            if not self.recipient_wallet or not self.recipient_wallet.strip():
                raise ValueError("DEVELOPMENT_OPERATION_WALLET_REQUIRED")
            if not self.unclaimed_id or not self.unclaimed_id.strip():
                raise ValueError("DEVELOPMENT_OPERATION_UNCLAIMED_REQUIRED")
            if not self.unclaimed_operation_id or not self.unclaimed_operation_id.strip():
                raise ValueError("DEVELOPMENT_OPERATION_UNCLAIMED_OPERATION_REQUIRED")
            if not self.source_epoch_transition_operation_id or not self.source_epoch_transition_operation_id.strip():
                raise ValueError("DEVELOPMENT_OPERATION_EPOCH_TRANSITION_REQUIRED")
            if self.claim_epoch is None:
                raise ValueError("DEVELOPMENT_OPERATION_CLAIM_EPOCH_REQUIRED")
            if self.wallet_binding is None:
                raise ValueError("DEVELOPMENT_OPERATION_WALLET_BINDING_REQUIRED")
            if not self.calculation_operation_id or not self.calculation_operation_id.strip():
                raise ValueError("DEVELOPMENT_OPERATION_CALCULATION_OPERATION_REQUIRED")
            if not self.pool_allocation_id or not self.pool_allocation_id.strip():
                raise ValueError("DEVELOPMENT_OPERATION_POOL_ALLOCATION_REQUIRED")
            if not self.pool_allocation_operation_id or not self.pool_allocation_operation_id.strip():
                raise ValueError("DEVELOPMENT_OPERATION_POOL_ALLOCATION_OPERATION_REQUIRED")
            if not self.reserve_id or not self.reserve_id.strip():
                raise ValueError("DEVELOPMENT_OPERATION_REWARD_RESERVE_REQUIRED")
            if not self.reserve_operation_id or not self.reserve_operation_id.strip():
                raise ValueError("DEVELOPMENT_OPERATION_REWARD_RESERVE_OPERATION_REQUIRED")
            if not self.payment_hash or not self.payment_hash.strip():
                raise ValueError("DEVELOPMENT_OPERATION_PAYMENT_HASH_REQUIRED")
            if self.role is None:
                raise ValueError("DEVELOPMENT_OPERATION_ROLE_REQUIRED")
            if self.payment_stage not in {
                "IMMEDIATE",
                "MATURITY_STAGE_ONE",
                "MATURITY_STAGE_TWO",
            }:
                raise ValueError("DEVELOPMENT_OPERATION_PAYMENT_STAGE_INVALID")
        if self.operation_type == "DEVELOPMENT_REWARD_CORRECT":
            if not self.reward_id or not self.reward_id.strip():
                raise ValueError("DEVELOPMENT_OPERATION_REWARD_REQUIRED")
            if not self.correction_id or not self.correction_id.strip():
                raise ValueError("DEVELOPMENT_OPERATION_CORRECTION_REQUIRED")
            if self.correction_delta_q_atoms is None:
                raise ValueError("DEVELOPMENT_OPERATION_CORRECTION_DELTA_REQUIRED")
            if self.reward_state_snapshot is None or self.reward_correction is None:
                raise ValueError("DEVELOPMENT_OPERATION_CORRECTION_RECORD_REQUIRED")
            if self.reward_correction.correction_id != self.correction_id:
                raise ValueError("DEVELOPMENT_OPERATION_CORRECTION_ID_MISMATCH")
            if self.reward_correction.correction_delta_q_atoms != self.correction_delta_q_atoms:
                raise ValueError("DEVELOPMENT_OPERATION_CORRECTION_DELTA_MISMATCH")
            if self.reward_correction.reward_id != self.reward_id:
                raise ValueError("DEVELOPMENT_OPERATION_CORRECTION_REWARD_MISMATCH")
        if self.operation_type == "DEVELOPMENT_REWARD_CANCEL_UNVESTED":
            if self.reward_state_snapshot is None or self.reward_cancellation is None:
                raise ValueError("DEVELOPMENT_OPERATION_CANCELLATION_RECORD_REQUIRED")
            if self.reward_cancellation.reward_id != self.reward_id:
                raise ValueError("DEVELOPMENT_OPERATION_CANCELLATION_REWARD_MISMATCH")
            if self.amount_q_atoms != self.reward_cancellation.cancelled_q_atoms:
                raise ValueError("DEVELOPMENT_OPERATION_CANCELLATION_AMOUNT_MISMATCH")
        return self


class DevelopmentRewardOperationBuilder:
    """Build reviewable envelopes while preserving the strict execution gate."""

    @staticmethod
    def build(request: DevelopmentRewardOperationRequest) -> LedgerOperationEnvelope:
        if operation_coverage(request.operation_type) not in {
            "DECLARED_UNIMPLEMENTED",
            "IMPLEMENTED",
        }:
            raise ValueError("DEVELOPMENT_OPERATION_EXECUTION_BOUNDARY_INVALID")
        commitment = request.commitment
        if not commitment.verify_integrity():
            raise ValueError("DEVELOPMENT_OPERATION_COMMITMENT_INVALID")
        if commitment.activation_state != "ACTIVATION_VERIFIED":
            raise ValueError("DEVELOPMENT_OPERATION_ACTIVATION_REQUIRED")
        approval = request.activation_approval
        if approval is None:
            raise ValueError("DEVELOPMENT_OPERATION_ACTIVATION_APPROVAL_REQUIRED")
        try:
            verify_development_reward_activation_approval(approval)
        except ValueError as error:
            raise ValueError("DEVELOPMENT_OPERATION_ACTIVATION_INVALID") from error
        if (
            approval.activation_id != commitment.activation_id
            or approval.approval_hash != commitment.activation_approval_hash
            or approval.policy_hash != commitment.policy_hash
        ):
            raise ValueError("DEVELOPMENT_OPERATION_ACTIVATION_MISMATCH")

        target_epoch = request.target_epoch if request.target_epoch is not None else commitment.epoch
        if request.operation_type == "DEVELOPMENT_POOL_CARRYOVER":
            if request.pool_carryover is not None and request.pool_carryover.target_epoch != target_epoch:
                raise ValueError("DEVELOPMENT_OPERATION_CARRYOVER_EPOCH_MISMATCH")
            if request.pool_carryover is not None and request.pool_carryover.source_epoch != commitment.epoch:
                raise ValueError("DEVELOPMENT_OPERATION_CARRYOVER_SOURCE_EPOCH_INVALID")
        elif target_epoch != commitment.epoch:
            raise ValueError("DEVELOPMENT_OPERATION_TARGET_EPOCH_MISMATCH")
        calculation = request.calculation
        if calculation is not None:
            if not calculation.verify_integrity():
                raise ValueError("DEVELOPMENT_OPERATION_CALCULATION_INVALID")
            if calculation.calculation_root != commitment.calculation_root:
                raise ValueError("DEVELOPMENT_OPERATION_CALCULATION_MISMATCH")

        request_payload = request.model_dump(
            mode="json",
            exclude={"commitment", "activation_approval", "created_at", "target_epoch"},
            exclude_none=True,
        )
        payload = {
            "commitment_id": commitment.commitment_id,
            "commitment_hash": commitment.commitment_hash,
            "activation_id": approval.activation_id,
            "activation_approval_hash": approval.approval_hash,
            "development_operation_version": DEVELOPMENT_REWARD_OPERATION_VERSION,
            "policy_hash": commitment.policy_hash,
            "calculation_root": commitment.calculation_root,
            "epoch": commitment.epoch,
            "commitment": commitment.model_dump(mode="json"),
            "activation_approval": approval.model_dump(mode="json"),
            **request_payload,
        }
        if request.operation_type == "DEVELOPMENT_POOL_ALLOCATE":
            if calculation is None:
                raise ValueError("DEVELOPMENT_OPERATION_CALCULATION_REQUIRED")
            if request.calculation_operation_id is None:
                raise ValueError("DEVELOPMENT_OPERATION_CALCULATION_OPERATION_REQUIRED")
            if request.source_epoch_transition_operation_id is None:
                raise ValueError("DEVELOPMENT_OPERATION_EPOCH_TRANSITION_REQUIRED")
            if request.pool_budget_reference is None or request.amount_q_atoms is None:
                raise ValueError("DEVELOPMENT_OPERATION_POOL_BUDGET_REFERENCE_REQUIRED")
            allocation = build_development_pool_allocation(
                pool_id=request.pool_id,
                epoch=calculation.epoch,
                calculation_operation_id=request.calculation_operation_id,
                calculation_commitment_id=commitment.commitment_id,
                calculation_root=calculation.calculation_root,
                source_epoch_transition_operation_id=request.source_epoch_transition_operation_id,
                source_pool_budget_reference=request.pool_budget_reference,
                authorized_budget_q_atoms=request.amount_q_atoms,
                allocated_q_atoms=request.amount_q_atoms,
            )
            payload["pool_allocation"] = allocation.model_dump(mode="json")
        if request.operation_type == "DEVELOPMENT_REWARD_RESERVE":
            if calculation is None:
                raise ValueError("DEVELOPMENT_OPERATION_CALCULATION_REQUIRED")
            if request.calculation_operation_id is None:
                raise ValueError("DEVELOPMENT_OPERATION_CALCULATION_OPERATION_REQUIRED")
            if request.pool_allocation_id is None:
                raise ValueError("DEVELOPMENT_OPERATION_POOL_ALLOCATION_REQUIRED")
            if request.pool_allocation_operation_id is None:
                raise ValueError("DEVELOPMENT_OPERATION_POOL_ALLOCATION_OPERATION_REQUIRED")
            schedule = next(
                (item for item in calculation.schedules if item.reward_id == request.reward_id),
                None,
            )
            if schedule is None:
                raise ValueError("DEVELOPMENT_OPERATION_REWARD_NOT_FOUND")
            if request.amount_q_atoms != schedule.gross_reward_q_atoms:
                raise ValueError("DEVELOPMENT_OPERATION_REWARD_AMOUNT_MISMATCH")
            reserve = build_development_reward_reserve(
                pool_allocation_id=request.pool_allocation_id,
                pool_allocation_operation_id=request.pool_allocation_operation_id,
                calculation_operation_id=request.calculation_operation_id,
                calculation_commitment_id=commitment.commitment_id,
                calculation_root=calculation.calculation_root,
                schedule=schedule,
            )
            payload["reward_reserve"] = reserve.model_dump(mode="json")
        if request.operation_type in _PAYMENT_EVIDENCE_OPERATIONS:
            if calculation is None or request.payment_hash is None:
                raise ValueError("DEVELOPMENT_OPERATION_PAYMENT_REQUIRED")
            payment = next(
                (item for item in calculation.payments if item.payment_hash == request.payment_hash),
                None,
            )
            if payment is None:
                raise ValueError("DEVELOPMENT_OPERATION_PAYMENT_NOT_FOUND")
            expected = {
                "reward_id": request.reward_id,
                "contributor_id": request.contributor_id,
                "recipient_wallet": request.recipient_wallet,
                "role": request.role,
                "payment_stage": request.payment_stage,
                "amount_q_atoms": request.amount_q_atoms,
            }
            actual = {
                "reward_id": payment.reward_id,
                "contributor_id": payment.contributor_id,
                "recipient_wallet": payment.wallet_address,
                "role": payment.role,
                "payment_stage": payment.payment_stage,
                "amount_q_atoms": payment.amount_q_atoms,
            }
            if expected != actual:
                raise ValueError("DEVELOPMENT_OPERATION_PAYMENT_MISMATCH")
            payload["reward_payment"] = payment.model_dump(mode="json")
        if request.operation_type in _EXPIRY_OPERATIONS:
            if calculation is None or request.payment_hash is None:
                raise ValueError("DEVELOPMENT_OPERATION_PAYMENT_REQUIRED")
            payment = next(
                (item for item in calculation.payments if item.payment_hash == request.payment_hash),
                None,
            )
            if payment is None or payment.state != "UNCLAIMED" or payment.wallet_address is not None:
                raise ValueError("DEVELOPMENT_OPERATION_EXPIRY_PAYMENT_MISMATCH")
            expected = {
                "reward_id": request.reward_id,
                "contributor_id": request.contributor_id,
                "recipient_wallet": request.recipient_wallet,
                "role": request.role,
                "payment_stage": request.payment_stage,
                "amount_q_atoms": request.amount_q_atoms,
            }
            actual = {
                "reward_id": payment.reward_id,
                "contributor_id": payment.contributor_id,
                "recipient_wallet": payment.wallet_address,
                "role": payment.role,
                "payment_stage": payment.payment_stage,
                "amount_q_atoms": payment.amount_q_atoms,
            }
            if expected != actual:
                raise ValueError("DEVELOPMENT_OPERATION_EXPIRY_PAYMENT_MISMATCH")
            unclaimed = build_development_reward_unclaimed_record(
                reserve_id=request.reserve_id or "",
                reserve_operation_id=request.reserve_operation_id or "",
                pool_allocation_id=request.pool_allocation_id or "",
                pool_allocation_operation_id=request.pool_allocation_operation_id or "",
                calculation_operation_id=request.calculation_operation_id or "",
                calculation_commitment_id=commitment.commitment_id,
                calculation_root=calculation.calculation_root,
                payment=payment,
                distribution_epoch=calculation.epoch,
                claim_expiration_epoch=calculation.epoch + calculation.policy.claim_window_epochs,
            )
            if unclaimed.unclaimed_id != request.unclaimed_id:
                raise ValueError("DEVELOPMENT_OPERATION_UNCLAIMED_ID_MISMATCH")
            payload["calculation_commitment_id"] = commitment.commitment_id
            payload["reward_unclaimed"] = unclaimed.model_dump(mode="json")
            payload["return_destination"] = request.return_destination
            payload["expiry_epoch"] = request.expiry_epoch
        if request.operation_type in _CLAIM_OPERATIONS:
            if calculation is None or request.payment_hash is None:
                raise ValueError("DEVELOPMENT_OPERATION_PAYMENT_REQUIRED")
            payment = next(
                (item for item in calculation.payments if item.payment_hash == request.payment_hash),
                None,
            )
            if payment is None:
                raise ValueError("DEVELOPMENT_OPERATION_PAYMENT_NOT_FOUND")
            expected = {
                "reward_id": request.reward_id,
                "contribution_id": request.contribution_id,
                "contributor_id": request.contributor_id,
                "role": request.role,
                "payment_stage": request.payment_stage,
                "amount_q_atoms": request.amount_q_atoms,
            }
            actual = {
                "reward_id": payment.reward_id,
                "contribution_id": payment.contribution_id,
                "contributor_id": payment.contributor_id,
                "role": payment.role,
                "payment_stage": payment.payment_stage,
                "amount_q_atoms": payment.amount_q_atoms,
            }
            if payment.state != "UNCLAIMED" or payment.wallet_address is not None or expected != actual:
                raise ValueError("DEVELOPMENT_OPERATION_CLAIM_PAYMENT_MISMATCH")
            if request.wallet_binding is None or request.claim_epoch is None:
                raise ValueError("DEVELOPMENT_OPERATION_WALLET_BINDING_REQUIRED")
            request.wallet_binding.verify_signature()
            unclaimed = build_development_reward_unclaimed_record(
                reserve_id=request.reserve_id or "",
                reserve_operation_id=request.reserve_operation_id or "",
                pool_allocation_id=request.pool_allocation_id or "",
                pool_allocation_operation_id=request.pool_allocation_operation_id or "",
                calculation_operation_id=request.calculation_operation_id or "",
                calculation_commitment_id=commitment.commitment_id,
                calculation_root=calculation.calculation_root,
                payment=payment,
                distribution_epoch=calculation.epoch,
                claim_expiration_epoch=calculation.epoch + calculation.policy.claim_window_epochs,
            )
            if unclaimed.unclaimed_id != request.unclaimed_id:
                raise ValueError("DEVELOPMENT_OPERATION_UNCLAIMED_ID_MISMATCH")
            if request.wallet_binding.contributor_id != payment.contributor_id:
                raise ValueError("DEVELOPMENT_OPERATION_WALLET_BINDING_MISMATCH")
            if request.wallet_binding.wallet_address != request.recipient_wallet:
                raise ValueError("DEVELOPMENT_OPERATION_WALLET_BINDING_MISMATCH")
            payload["calculation_commitment_id"] = commitment.commitment_id
            payload["reward_payment"] = payment.model_dump(mode="json")
            payload["reward_unclaimed"] = unclaimed.model_dump(mode="json")
        if request.operation_type in _FINALIZED_COMMITMENT_OPERATIONS:
            if calculation is None:
                raise ValueError("DEVELOPMENT_OPERATION_CALCULATION_REQUIRED")
            calculation_commitment_id = commitment.commitment_id
            finalized_commitment_id = development_reward_finalized_commitment_id(
                calculation_operation_id=request.calculation_operation_id or "",
                calculation_commitment_id=calculation_commitment_id,
                calculation_root=calculation.calculation_root,
                pool_allocation_id=request.pool_allocation_id or "",
                pool_allocation_operation_id=request.pool_allocation_operation_id or "",
                source_epoch_transition_operation_id=request.source_epoch_transition_operation_id or "",
                reserve_operation_ids=request.reserve_operation_ids,
                payment_operation_ids=request.payment_operation_ids,
                unclaimed_operation_ids=request.unclaimed_operation_ids,
                claim_operation_ids=request.claim_operation_ids,
                expiry_operation_ids=request.expiry_operation_ids,
                source_operation_root=request.source_operation_root or "",
                reserve_root=request.reserve_root or "",
                payment_root=request.payment_root or "",
                unclaimed_root=request.unclaimed_root or "",
                claim_root=request.claim_root or "",
                expiry_root=request.expiry_root or "",
                finalization_epoch=request.finalization_epoch or 0,
            )
            payload["calculation_commitment_id"] = calculation_commitment_id
            payload["finalized_commitment_id"] = finalized_commitment_id
        payload["payload_hash"] = canonical_hash(payload)
        return LedgerOperationEnvelope(
            operation_type=request.operation_type,
            operation_version=DEVELOPMENT_REWARD_CONSENSUS_OPERATION_VERSION,
            origin_type="protocol",
            initiator_id=DEVELOPMENT_REWARD_ENGINE_ID,
            fee_class="protocol_sponsored",
            created_at=request.created_at,
            target_epoch=str(commitment.epoch),
            payload=payload,
            evidence_references=sorted(
                {
                    commitment.commitment_id,
                    commitment.commitment_hash,
                    commitment.calculation_root,
                    approval.activation_id,
                    approval.approval_hash,
                }
            ),
        )


def build_development_reward_operation(
    request: DevelopmentRewardOperationRequest,
) -> LedgerOperationEnvelope:
    return DevelopmentRewardOperationBuilder.build(request)


__all__ = [
    "DEVELOPMENT_REWARD_ENGINE_ID",
    "DEVELOPMENT_REWARD_OPERATION_VERSION",
    "DEVELOPMENT_REWARD_CONSENSUS_OPERATION_VERSION",
    "DevelopmentRewardOperationBuilder",
    "DevelopmentRewardOperationRequest",
    "DevelopmentRewardOperationType",
    "build_development_reward_operation",
]
