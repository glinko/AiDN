"""Bridge finalized RFC-0068 evidence into the ECO-0007 reward engine.

This module deliberately separates calculation from economic execution. A
merged repository file can identify the intended wallet, but it cannot mint
Q by itself. A payout plan must still carry a valid ECO-0007 activation and a
source-bound epoch pool operation before it can be submitted to consensus.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field

from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.contributions.models import ContributionAttestation
from aidn_hypervisor.contributions.service import ContributionAccountingService
from aidn_hypervisor.reward.development_activation import DevelopmentRewardActivationApproval
from aidn_hypervisor.reward.development_commitments import (
    DevelopmentRewardCommitment,
    build_development_reward_commitment,
)
from aidn_hypervisor.reward.development_distribution import (
    DevelopmentContributionInput,
    DevelopmentPoolInput,
    DevelopmentRewardCalculation,
    DevelopmentRewardCalculator,
    DevelopmentRewardPolicy,
    canonical_hash,
    contribution_input_from_attestation,
)
from aidn_hypervisor.reward.development_operations import (
    DevelopmentRewardOperationRequest,
    build_development_reward_operation,
)

DEVELOPMENT_REWARD_PLAN_VERSION = "aidn.eco-0007-contribution-plan.v1"


class DevelopmentRewardPreview(BaseModel, frozen=True):
    """Hash-bound calculation and wallet provenance, without Ledger effects."""

    plan_version: str = DEVELOPMENT_REWARD_PLAN_VERSION
    mode: Literal["PREVIEW_ONLY"] = "PREVIEW_ONLY"
    epoch: int = Field(ge=0)
    contribution_ids: list[str] = Field(min_length=0)
    source_attestation_hashes: list[str] = Field(min_length=0)
    wallet_provenance: dict[str, str] = Field(default_factory=dict)
    calculation: DevelopmentRewardCalculation
    commitment: DevelopmentRewardCommitment
    preview_hash: str = Field(min_length=1)


class DevelopmentRewardOperationPlan(BaseModel, frozen=True):
    """Ordered consensus envelopes for one activated ECO-0007 batch."""

    plan_version: str = DEVELOPMENT_REWARD_PLAN_VERSION
    mode: Literal["CONSENSUS_GATED"] = "CONSENSUS_GATED"
    epoch: int = Field(ge=0)
    commitment: DevelopmentRewardCommitment
    envelopes: list[LedgerOperationEnvelope] = Field(min_length=1)
    plan_hash: str = Field(min_length=1)

    def unsigned_payload(self) -> dict:
        return {
            "plan_version": self.plan_version,
            "mode": self.mode,
            "epoch": self.epoch,
            "commitment_hash": self.commitment.commitment_hash,
            "operation_ids": [item.operation_id for item in self.envelopes],
        }

    def verify_integrity(self) -> bool:
        return self.plan_hash == canonical_hash(self.unsigned_payload())


class DevelopmentContributionRewardService:
    """Calculate and assemble rewards from finalized contribution evidence."""

    def __init__(
        self,
        contribution_service: ContributionAccountingService,
        *,
        calculator: DevelopmentRewardCalculator | None = None,
    ) -> None:
        self.contribution_service = contribution_service
        self.calculator = calculator or DevelopmentRewardCalculator()

    def _attestations_for_batch(
        self,
        *,
        epoch: int,
        contribution_ids: Sequence[str] | None,
    ) -> list[ContributionAttestation]:
        if contribution_ids is None:
            selected = [
                item
                for item in self.contribution_service.list_attestations()
                if item.contribution_epoch == epoch
            ]
        else:
            requested = list(dict.fromkeys(contribution_ids))
            selected = []
            by_id = {item.contribution_id: item for item in self.contribution_service.list_attestations()}
            for contribution_id in requested:
                item = by_id.get(contribution_id)
                if item is None:
                    raise ValueError("CONTRIBUTION_NOT_FOUND")
                selected.append(item)
        if not selected:
            raise ValueError("DEVELOPMENT_REWARD_NO_CONTRIBUTIONS")
        for item in selected:
            if item.eligibility_state != "FINALIZED":
                raise ValueError("DEVELOPMENT_CONTRIBUTION_NOT_FINALIZED")
            if item.contribution_epoch > epoch:
                raise ValueError("DEVELOPMENT_CONTRIBUTION_EPOCH_INVALID")
        return sorted(selected, key=lambda item: item.contribution_id)

    def _input_for_attestation(
        self,
        attestation: ContributionAttestation,
    ) -> tuple[DevelopmentContributionInput, dict[str, str]]:
        wallets: dict[str, str | None] = {}
        provenance: dict[str, str] = {}
        for allocation in attestation.role_allocations:
            contributor = self.contribution_service.store.contributors.get(allocation.contributor_id)
            if contributor is None:
                raise ValueError("CONTRIBUTOR_NOT_REGISTERED")
            wallets[allocation.contributor_id] = contributor.current_wallet_address
            if contributor.current_wallet_address:
                provenance[allocation.contributor_id] = "REGISTERED_WALLET_BINDING"
            else:
                provenance[allocation.contributor_id] = "UNCLAIMED"

        claim = attestation.wallet_claim
        if claim is not None:
            wallets[claim.contributor_id] = claim.wallet_address
            provenance[claim.contributor_id] = "MERGED_COMMIT_WALLET_CLAIM"

        return (
            contribution_input_from_attestation(
                attestation,
                wallet_by_contributor=wallets,
                control_group_by_contributor={
                    contributor_id: self.contribution_service.store.contributors[contributor_id].known_control_group
                    for contributor_id in wallets
                    if contributor_id in self.contribution_service.store.contributors
                },
            ),
            provenance,
        )

    def preview(
        self,
        *,
        pool_input: DevelopmentPoolInput,
        contribution_ids: Sequence[str] | None = None,
        policy: DevelopmentRewardPolicy | None = None,
    ) -> DevelopmentRewardPreview:
        """Build an idempotent reward calculation from finalized attestations."""

        attestations = self._attestations_for_batch(
            epoch=pool_input.epoch,
            contribution_ids=contribution_ids,
        )
        inputs: list[DevelopmentContributionInput] = []
        provenance: dict[str, str] = {}
        for attestation in attestations:
            contribution_input, attestation_provenance = self._input_for_attestation(attestation)
            inputs.append(contribution_input)
            for contributor_id, source in attestation_provenance.items():
                provenance.setdefault(contributor_id, source)

        calculator = (
            self.calculator
            if policy is None or policy == self.calculator.policy
            else DevelopmentRewardCalculator(policy)
        )
        calculation = calculator.calculate(pool_input, inputs)
        commitment = build_development_reward_commitment(calculation)
        payload = {
            "plan_version": DEVELOPMENT_REWARD_PLAN_VERSION,
            "mode": "PREVIEW_ONLY",
            "epoch": pool_input.epoch,
            "contribution_ids": [item.contribution_id for item in attestations],
            "source_attestation_hashes": [item.attestation_hash for item in attestations],
            "wallet_provenance": provenance,
            "calculation_root": calculation.calculation_root,
            "commitment_hash": commitment.commitment_hash,
        }
        return DevelopmentRewardPreview(
            epoch=pool_input.epoch,
            contribution_ids=payload["contribution_ids"],
            source_attestation_hashes=payload["source_attestation_hashes"],
            wallet_provenance=provenance,
            calculation=calculation,
            commitment=commitment,
            preview_hash=canonical_hash(payload),
        )

    @staticmethod
    def _created_at(created_at: str, offset: int) -> str:
        """Keep operation timestamps deterministic while preserving ISO input."""

        parsed = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return (parsed.astimezone(UTC) + timedelta(seconds=offset)).isoformat().replace("+00:00", "Z")

    def build_consensus_plan(
        self,
        preview: DevelopmentRewardPreview,
        *,
        activation_approval: DevelopmentRewardActivationApproval,
        current_epoch: int,
        source_epoch_transition_operation_id: str,
        pool_budget_reference: str,
        created_at: str,
    ) -> DevelopmentRewardOperationPlan:
        """Build the canonical operation sequence; do not submit it here."""

        calculation = preview.calculation
        if preview.commitment.calculation_root != calculation.calculation_root:
            raise ValueError("DEVELOPMENT_REWARD_PREVIEW_COMMITMENT_MISMATCH")
        if calculation.pool.pool_in_q_atoms != calculation.pool.base_allocation_q_atoms:
            raise ValueError("DEVELOPMENT_REWARD_POOL_INPUT_SOURCE_UNSUPPORTED")
        commitment = build_development_reward_commitment(
            calculation,
            activation_approval=activation_approval,
            current_epoch=current_epoch,
        )
        envelopes: list[LedgerOperationEnvelope] = []
        calculation_envelope = build_development_reward_operation(
            DevelopmentRewardOperationRequest(
                operation_type="DEVELOPMENT_REWARD_CALCULATE",
                created_at=self._created_at(created_at, 0),
                commitment=commitment,
                activation_approval=activation_approval,
                calculation=calculation,
            )
        )
        envelopes.append(calculation_envelope)
        if calculation.accepted_gross_reward_q_atoms <= 0:
            return self._plan(preview, commitment, envelopes)

        allocation_envelope = build_development_reward_operation(
            DevelopmentRewardOperationRequest(
                operation_type="DEVELOPMENT_POOL_ALLOCATE",
                created_at=self._created_at(created_at, 1),
                commitment=commitment,
                activation_approval=activation_approval,
                calculation=calculation,
                amount_q_atoms=calculation.pool.base_allocation_q_atoms,
                calculation_operation_id=calculation_envelope.operation_id,
                source_epoch_transition_operation_id=source_epoch_transition_operation_id,
                pool_budget_reference=pool_budget_reference,
            )
        )
        envelopes.append(allocation_envelope)
        pool_allocation = allocation_envelope.payload.get("pool_allocation") or {}
        pool_allocation_id = pool_allocation.get("allocation_id")
        if not isinstance(pool_allocation_id, str) or not pool_allocation_id:
            raise ValueError("DEVELOPMENT_REWARD_POOL_ALLOCATION_EVIDENCE_INVALID")

        reserve_operations: dict[str, LedgerOperationEnvelope] = {}
        for index, schedule in enumerate(calculation.schedules, start=2):
            if schedule.gross_reward_q_atoms <= 0:
                continue
            reserve_envelope = build_development_reward_operation(
                DevelopmentRewardOperationRequest(
                    operation_type="DEVELOPMENT_REWARD_RESERVE",
                    created_at=self._created_at(created_at, index),
                    commitment=commitment,
                    activation_approval=activation_approval,
                    calculation=calculation,
                    amount_q_atoms=schedule.gross_reward_q_atoms,
                    calculation_operation_id=calculation_envelope.operation_id,
                    pool_allocation_id=pool_allocation_id,
                    pool_allocation_operation_id=allocation_envelope.operation_id,
                    reward_id=schedule.reward_id,
                )
            )
            envelopes.append(reserve_envelope)
            reserve_operations[schedule.reward_id] = reserve_envelope

        offset = len(envelopes)
        for payment in calculation.payments:
            if payment.amount_q_atoms <= 0:
                continue
            if payment.state == "RESERVED":
                # Maturity stages are paid only after their epoch boundary.
                continue
            if payment.state != "PAYABLE" and not (
                payment.state == "UNCLAIMED" and payment.wallet_address is None
            ):
                raise ValueError("DEVELOPMENT_REWARD_PAYMENT_STATE_INVALID")
            reserve_envelope = reserve_operations.get(payment.reward_id)
            if reserve_envelope is None:
                raise ValueError("DEVELOPMENT_REWARD_RESERVE_NOT_FOUND")
            reserve_id = (reserve_envelope.payload.get("reward_reserve") or {}).get("reserve_id")
            if not isinstance(reserve_id, str) or not reserve_id:
                raise ValueError("DEVELOPMENT_REWARD_RESERVE_EVIDENCE_INVALID")
            operation_type = (
                "DEVELOPMENT_REWARD_PAY_IMMEDIATE"
                if payment.state == "PAYABLE" and payment.payment_stage == "IMMEDIATE"
                else "DEVELOPMENT_REWARD_MARK_UNCLAIMED"
            )
            envelope = build_development_reward_operation(
                DevelopmentRewardOperationRequest(
                    operation_type=operation_type,
                    created_at=self._created_at(created_at, offset),
                    commitment=commitment,
                    activation_approval=activation_approval,
                    calculation=calculation,
                    amount_q_atoms=payment.amount_q_atoms,
                    calculation_operation_id=calculation_envelope.operation_id,
                    pool_allocation_id=pool_allocation_id,
                    pool_allocation_operation_id=allocation_envelope.operation_id,
                    reserve_id=reserve_id,
                    reserve_operation_id=reserve_envelope.operation_id,
                    reward_id=payment.reward_id,
                    contribution_id=payment.contribution_id,
                    contributor_id=payment.contributor_id,
                    recipient_wallet=payment.wallet_address,
                    role=payment.role,
                    payment_hash=payment.payment_hash,
                    payment_stage=payment.payment_stage,
                )
            )
            envelopes.append(envelope)
            offset += 1

        return self._plan(preview, commitment, envelopes)

    @staticmethod
    def _plan(
        preview: DevelopmentRewardPreview,
        commitment: DevelopmentRewardCommitment,
        envelopes: list[LedgerOperationEnvelope],
    ) -> DevelopmentRewardOperationPlan:
        payload = {
            "plan_version": DEVELOPMENT_REWARD_PLAN_VERSION,
            "mode": "CONSENSUS_GATED",
            "epoch": preview.epoch,
            "commitment_hash": commitment.commitment_hash,
            "operation_ids": [item.operation_id for item in envelopes],
        }
        return DevelopmentRewardOperationPlan(
            epoch=preview.epoch,
            commitment=commitment,
            envelopes=envelopes,
            plan_hash=canonical_hash(payload),
        )


__all__ = [
    "DEVELOPMENT_REWARD_PLAN_VERSION",
    "DevelopmentContributionRewardService",
    "DevelopmentRewardOperationPlan",
    "DevelopmentRewardPreview",
]
