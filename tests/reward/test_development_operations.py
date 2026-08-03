import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aidn_hypervisor.consensus.abci import AIDNABCIApplication
from aidn_hypervisor.consensus.admission import AdmissionValidator
from aidn_hypervisor.consensus.coverage import (
    operation_coverage,
    strict_operation_coverage_error,
)
from aidn_hypervisor.consensus.execution import ExecutionEngine
from aidn_hypervisor.consensus.models import KNOWN_OPERATION_TYPES, LedgerOperationEnvelope
from aidn_hypervisor.consensus.state_store import ABCIStateStore
from aidn_hypervisor.contributions.models import canonical_hash as contribution_canonical_hash
from aidn_hypervisor.contributions.service import contributor_wallet_binding_payload
from aidn_hypervisor.ledger.service import LedgerOperationService
from aidn_hypervisor.reward.development_activation import (
    DevelopmentRewardApprovalSignature,
    DevelopmentRewardAuthority,
    activation_authorization_payload,
    build_development_reward_activation_approval,
    development_reward_policy_hash,
)
from aidn_hypervisor.reward.development_claim import DevelopmentRewardWalletBindingProof
from aidn_hypervisor.reward.development_commitments import build_development_reward_commitment
from aidn_hypervisor.reward.development_distribution import (
    DevelopmentContributionInput,
    DevelopmentPoolInput,
    DevelopmentRewardCalculator,
    DevelopmentRewardPolicy,
    DevelopmentRoleInput,
    canonical_hash,
)
from aidn_hypervisor.reward.development_operations import (
    DevelopmentRewardOperationRequest,
    build_development_reward_operation,
)
from aidn_hypervisor.reward.development_scenarios import (
    DEFAULT_DISTRIBUTABLE_EPOCH_EMISSION_Q_ATOMS,
    run_launch_simulation_matrix,
)
from aidn_hypervisor.reward.development_unclaimed import development_reward_unclaimed_id

DECLARED_OPERATION_TYPES = {
    "DEVELOPMENT_POOL_CARRYOVER",
    "DEVELOPMENT_BOUNTY_CREATE",
    "DEVELOPMENT_BOUNTY_RESERVE",
    "DEVELOPMENT_BOUNTY_RELEASE",
    "DEVELOPMENT_REWARD_CANCEL_UNVESTED",
    "DEVELOPMENT_REWARD_CORRECT",
}
IMPLEMENTED_OPERATION_TYPES = {
    "DEVELOPMENT_REWARD_CALCULATE",
    "DEVELOPMENT_POOL_ALLOCATE",
    "DEVELOPMENT_REWARD_RESERVE",
    "DEVELOPMENT_REWARD_PAY_IMMEDIATE",
    "DEVELOPMENT_REWARD_PAY_MATURITY",
    "DEVELOPMENT_REWARD_MARK_UNCLAIMED",
    "DEVELOPMENT_REWARD_CLAIM",
    "DEVELOPMENT_REWARD_EXPIRE_UNCLAIMED",
    "DEVELOPMENT_REWARD_FINALIZE_COMMITMENT",
}


def _approval(
    policy: DevelopmentRewardPolicy,
    *,
    authorized_operation_types: list[str] | None = None,
    economic_effect_profile: str = "EVIDENCE_ONLY",
):
    operation_types = authorized_operation_types or ["DEVELOPMENT_REWARD_CALCULATE"]
    entries = []
    for authority_id, seed in (("governance-a", 1), ("governance-b", 2)):
        private_key = Ed25519PrivateKey.from_private_bytes(bytes([seed]) * 32)
        authority = DevelopmentRewardAuthority(
            authority_id=authority_id,
            public_key="ed25519:" + private_key.public_key().public_bytes_raw().hex(),
        )
        entries.append((authority_id, private_key, authority))
    authorities = [item[2] for item in entries]
    policy_hash = development_reward_policy_hash(policy)
    unsigned = build_development_reward_activation_approval(
        policy_hash=policy_hash,
        effective_epoch=10,
        eligible_authorities=authorities,
        quorum_threshold=2,
        approvals=[],
        authorized_operation_types=operation_types,
        economic_effect_profile=economic_effect_profile,
    )
    approvals = [
        DevelopmentRewardApprovalSignature(
            authority_id=authority_id,
            signature="ed25519:"
            + private_key.sign(
                activation_authorization_payload(
                    activation_id=unsigned.activation_id,
                    policy_hash=policy_hash,
                    effective_epoch=10,
                    eligible_authorities=authorities,
                    quorum_threshold=2,
                    authority_id=authority_id,
                    authorized_operation_types=operation_types,
                    economic_effect_profile=economic_effect_profile,
                )
            ).hex(),
        )
        for authority_id, private_key, _ in entries
    ]
    return build_development_reward_activation_approval(
        policy_hash=policy_hash,
        effective_epoch=10,
        eligible_authorities=authorities,
        quorum_threshold=2,
        approvals=approvals,
        authorized_operation_types=operation_types,
        economic_effect_profile=economic_effect_profile,
    )


def _fixture():
    calculation = run_launch_simulation_matrix().scenarios[0].calculation
    approval = _approval(calculation.policy)
    commitment = build_development_reward_commitment(
        calculation,
        activation_approval=approval,
        current_epoch=20,
    )
    return calculation, approval, commitment


def _allocation_fixture():
    calculation = run_launch_simulation_matrix().scenarios[0].calculation
    approval = _approval(
        calculation.policy,
        authorized_operation_types=[
            "DEVELOPMENT_REWARD_CALCULATE",
            "DEVELOPMENT_POOL_ALLOCATE",
        ],
        economic_effect_profile="POOL_ALLOCATION",
    )
    commitment = build_development_reward_commitment(
        calculation,
        activation_approval=approval,
        current_epoch=20,
    )
    return calculation, approval, commitment


def _epoch_transition(calculation, *, opening_epoch: int | None = None) -> bytes:
    opening = calculation.epoch + 1 if opening_epoch is None else opening_epoch
    closing = opening - 1
    value = {
        "operation_type": "EPOCH_TRANSITION",
        "operation_version": "1.0.0",
        "protocol_version": "0.1",
        "origin_type": "protocol",
        "initiator_id": "epoch-engine",
        "sender_wallet": None,
        "sender_sequence": None,
        "fee_payer": None,
        "fee_class": "protocol_sponsored",
        "created_at": "2030-01-01T00:00:00Z",
        "expires_at": None,
        "target_epoch": str(closing),
        "payload": {
            "closing_epoch": closing,
            "opening_epoch": opening,
            "closing_state_root": "sha256:closing-state",
            "epoch_task_result_root": "sha256:epoch-tasks",
            "eligibility_snapshot_root": "sha256:eligibility",
            "reward_calculation_root": calculation.calculation_root,
            "next_protocol_parameters_hash": "sha256:next-parameters",
            "pool_budgets": {
                "GENERAL_DEVELOPMENT": calculation.pool.base_allocation_q_atoms,
            },
            "pool_budget_references": {
                "GENERAL_DEVELOPMENT": "epoch:20:GENERAL_DEVELOPMENT",
            },
        },
        "evidence_references": [],
        "signatures": [],
    }
    return json.dumps(value).encode("utf-8")


def _wallet_binding(
    *,
    contributor_id: str,
    wallet_address: str,
    seed: int = 7,
) -> DevelopmentRewardWalletBindingProof:
    private_key = Ed25519PrivateKey.from_private_bytes(bytes([seed]) * 32)
    wallet_public_key = "ed25519:" + private_key.public_key().public_bytes_raw().hex()
    challenge_id = "challenge-unclaimed"
    challenge_hash = "sha256:challenge-unclaimed"
    source_platform_account = "github:unclaimed"
    binding_version = 1
    signature = (
        "ed25519:"
        + private_key.sign(
            contributor_wallet_binding_payload(
                contributor_id=contributor_id,
                source_platform_account=source_platform_account,
                wallet_address=wallet_address,
                wallet_public_key=wallet_public_key,
                challenge_id=challenge_id,
                challenge_hash=challenge_hash,
                binding_version=binding_version,
            )
        ).hex()
    )
    unsigned = {
        "contributor_id": contributor_id,
        "source_platform_account": source_platform_account,
        "wallet_address": wallet_address,
        "wallet_public_key": wallet_public_key,
        "challenge_id": challenge_id,
        "challenge_hash": challenge_hash,
        "wallet_signature": signature,
        "source_platform_confirmation_hash": "sha256:source-confirmation",
        "valid_from": "2030-01-01T00:00:00Z",
        "binding_version": binding_version,
    }
    binding_hash = contribution_canonical_hash(unsigned)
    return DevelopmentRewardWalletBindingProof(
        binding_id=binding_hash,
        **unsigned,
        binding_hash=binding_hash,
    )


def _allocation_envelopes():
    calculation, approval, commitment = _allocation_fixture()
    epoch_tx = _epoch_transition(calculation)
    epoch_operation_id = LedgerOperationEnvelope.model_validate(json.loads(epoch_tx)).operation_id
    calculation_envelope = build_development_reward_operation(
        DevelopmentRewardOperationRequest(
            operation_type="DEVELOPMENT_REWARD_CALCULATE",
            created_at="2030-01-01T00:00:01Z",
            commitment=commitment,
            activation_approval=approval,
            calculation=calculation,
        )
    )
    allocation_envelope = build_development_reward_operation(
        DevelopmentRewardOperationRequest(
            operation_type="DEVELOPMENT_POOL_ALLOCATE",
            created_at="2030-01-01T00:00:02Z",
            commitment=commitment,
            activation_approval=approval,
            calculation=calculation,
            amount_q_atoms=calculation.pool.base_allocation_q_atoms,
            calculation_operation_id=calculation_envelope.operation_id,
            source_epoch_transition_operation_id=epoch_operation_id,
            pool_budget_reference="epoch:20:GENERAL_DEVELOPMENT",
        )
    )
    return calculation, approval, commitment, epoch_tx, calculation_envelope, allocation_envelope


def _reserve_envelopes():
    calculation = run_launch_simulation_matrix().scenarios[0].calculation
    approval = _approval(
        calculation.policy,
        authorized_operation_types=[
            "DEVELOPMENT_REWARD_CALCULATE",
            "DEVELOPMENT_POOL_ALLOCATE",
            "DEVELOPMENT_REWARD_RESERVE",
        ],
        economic_effect_profile="DEVELOPMENT_RESERVES",
    )
    commitment = build_development_reward_commitment(
        calculation,
        activation_approval=approval,
        current_epoch=20,
    )
    epoch_tx = _epoch_transition(calculation)
    epoch_operation_id = LedgerOperationEnvelope.model_validate(json.loads(epoch_tx)).operation_id
    calculation_envelope = build_development_reward_operation(
        DevelopmentRewardOperationRequest(
            operation_type="DEVELOPMENT_REWARD_CALCULATE",
            created_at="2030-01-01T00:00:01Z",
            commitment=commitment,
            activation_approval=approval,
            calculation=calculation,
        )
    )
    allocation_envelope = build_development_reward_operation(
        DevelopmentRewardOperationRequest(
            operation_type="DEVELOPMENT_POOL_ALLOCATE",
            created_at="2030-01-01T00:00:02Z",
            commitment=commitment,
            activation_approval=approval,
            calculation=calculation,
            amount_q_atoms=calculation.pool.base_allocation_q_atoms,
            calculation_operation_id=calculation_envelope.operation_id,
            source_epoch_transition_operation_id=epoch_operation_id,
            pool_budget_reference="epoch:20:GENERAL_DEVELOPMENT",
        )
    )
    schedule = calculation.schedules[0]
    reserve_envelope = build_development_reward_operation(
        DevelopmentRewardOperationRequest(
            operation_type="DEVELOPMENT_REWARD_RESERVE",
            created_at="2030-01-01T00:00:03Z",
            commitment=commitment,
            activation_approval=approval,
            calculation=calculation,
            amount_q_atoms=schedule.gross_reward_q_atoms,
            calculation_operation_id=calculation_envelope.operation_id,
            pool_allocation_id=allocation_envelope.payload["pool_allocation"]["allocation_id"],
            pool_allocation_operation_id=allocation_envelope.operation_id,
            reward_id=schedule.reward_id,
        )
    )
    return (
        calculation,
        approval,
        commitment,
        epoch_tx,
        calculation_envelope,
        allocation_envelope,
        reserve_envelope,
    )


def _payment_envelopes():
    calculation = run_launch_simulation_matrix().scenarios[0].calculation
    approval = _approval(
        calculation.policy,
        authorized_operation_types=[
            "DEVELOPMENT_REWARD_CALCULATE",
            "DEVELOPMENT_POOL_ALLOCATE",
            "DEVELOPMENT_REWARD_RESERVE",
            "DEVELOPMENT_REWARD_PAY_IMMEDIATE",
        ],
        economic_effect_profile="DEVELOPMENT_PAYMENTS",
    )
    commitment = build_development_reward_commitment(
        calculation,
        activation_approval=approval,
        current_epoch=20,
    )
    epoch_tx = _epoch_transition(calculation)
    epoch_operation_id = LedgerOperationEnvelope.model_validate(json.loads(epoch_tx)).operation_id
    calculation_envelope = build_development_reward_operation(
        DevelopmentRewardOperationRequest(
            operation_type="DEVELOPMENT_REWARD_CALCULATE",
            created_at="2030-01-01T00:00:01Z",
            commitment=commitment,
            activation_approval=approval,
            calculation=calculation,
        )
    )
    allocation_envelope = build_development_reward_operation(
        DevelopmentRewardOperationRequest(
            operation_type="DEVELOPMENT_POOL_ALLOCATE",
            created_at="2030-01-01T00:00:02Z",
            commitment=commitment,
            activation_approval=approval,
            calculation=calculation,
            amount_q_atoms=calculation.pool.base_allocation_q_atoms,
            calculation_operation_id=calculation_envelope.operation_id,
            source_epoch_transition_operation_id=epoch_operation_id,
            pool_budget_reference="epoch:20:GENERAL_DEVELOPMENT",
        )
    )
    schedule = calculation.schedules[0]
    reserve_envelope = build_development_reward_operation(
        DevelopmentRewardOperationRequest(
            operation_type="DEVELOPMENT_REWARD_RESERVE",
            created_at="2030-01-01T00:00:03Z",
            commitment=commitment,
            activation_approval=approval,
            calculation=calculation,
            amount_q_atoms=schedule.gross_reward_q_atoms,
            calculation_operation_id=calculation_envelope.operation_id,
            pool_allocation_id=allocation_envelope.payload["pool_allocation"]["allocation_id"],
            pool_allocation_operation_id=allocation_envelope.operation_id,
            reward_id=schedule.reward_id,
        )
    )
    payment = calculation.payments[0]
    payment_envelope = build_development_reward_operation(
        DevelopmentRewardOperationRequest(
            operation_type="DEVELOPMENT_REWARD_PAY_IMMEDIATE",
            created_at="2030-01-01T00:00:04Z",
            commitment=commitment,
            activation_approval=approval,
            calculation=calculation,
            calculation_operation_id=calculation_envelope.operation_id,
            pool_allocation_id=allocation_envelope.payload["pool_allocation"]["allocation_id"],
            pool_allocation_operation_id=allocation_envelope.operation_id,
            reserve_id=reserve_envelope.payload["reward_reserve"]["reserve_id"],
            reserve_operation_id=reserve_envelope.operation_id,
            reward_id=payment.reward_id,
            contributor_id=payment.contributor_id,
            recipient_wallet=payment.wallet_address,
            role=payment.role,
            payment_hash=payment.payment_hash,
            payment_stage=payment.payment_stage,
            amount_q_atoms=payment.amount_q_atoms,
        )
    )
    return (
        calculation,
        approval,
        commitment,
        epoch_tx,
        calculation_envelope,
        allocation_envelope,
        reserve_envelope,
        payment_envelope,
    )


def _maturity_envelopes():
    calculation = run_launch_simulation_matrix().scenarios[0].calculation
    approval = _approval(
        calculation.policy,
        authorized_operation_types=[
            "DEVELOPMENT_REWARD_CALCULATE",
            "DEVELOPMENT_POOL_ALLOCATE",
            "DEVELOPMENT_REWARD_RESERVE",
            "DEVELOPMENT_REWARD_PAY_MATURITY",
        ],
        economic_effect_profile="DEVELOPMENT_PAYMENTS",
    )
    commitment = build_development_reward_commitment(
        calculation,
        activation_approval=approval,
        current_epoch=20,
    )
    epoch_tx = _epoch_transition(calculation)
    epoch_operation_id = LedgerOperationEnvelope.model_validate(json.loads(epoch_tx)).operation_id
    calculation_envelope = build_development_reward_operation(
        DevelopmentRewardOperationRequest(
            operation_type="DEVELOPMENT_REWARD_CALCULATE",
            created_at="2030-01-01T00:00:01Z",
            commitment=commitment,
            activation_approval=approval,
            calculation=calculation,
        )
    )
    allocation_envelope = build_development_reward_operation(
        DevelopmentRewardOperationRequest(
            operation_type="DEVELOPMENT_POOL_ALLOCATE",
            created_at="2030-01-01T00:00:02Z",
            commitment=commitment,
            activation_approval=approval,
            calculation=calculation,
            amount_q_atoms=calculation.pool.base_allocation_q_atoms,
            calculation_operation_id=calculation_envelope.operation_id,
            source_epoch_transition_operation_id=epoch_operation_id,
            pool_budget_reference="epoch:20:GENERAL_DEVELOPMENT",
        )
    )
    schedule = calculation.schedules[0]
    reserve_envelope = build_development_reward_operation(
        DevelopmentRewardOperationRequest(
            operation_type="DEVELOPMENT_REWARD_RESERVE",
            created_at="2030-01-01T00:00:03Z",
            commitment=commitment,
            activation_approval=approval,
            calculation=calculation,
            amount_q_atoms=schedule.gross_reward_q_atoms,
            calculation_operation_id=calculation_envelope.operation_id,
            pool_allocation_id=allocation_envelope.payload["pool_allocation"]["allocation_id"],
            pool_allocation_operation_id=allocation_envelope.operation_id,
            reward_id=schedule.reward_id,
        )
    )

    def build_maturity_payment(payment, created_at: str):
        return build_development_reward_operation(
            DevelopmentRewardOperationRequest(
                operation_type="DEVELOPMENT_REWARD_PAY_MATURITY",
                created_at=created_at,
                commitment=commitment,
                activation_approval=approval,
                calculation=calculation,
                calculation_operation_id=calculation_envelope.operation_id,
                pool_allocation_id=allocation_envelope.payload["pool_allocation"]["allocation_id"],
                pool_allocation_operation_id=allocation_envelope.operation_id,
                reserve_id=reserve_envelope.payload["reward_reserve"]["reserve_id"],
                reserve_operation_id=reserve_envelope.operation_id,
                source_epoch_transition_operation_id=epoch_operation_id,
                reward_id=payment.reward_id,
                contributor_id=payment.contributor_id,
                recipient_wallet=payment.wallet_address,
                role=payment.role,
                payment_hash=payment.payment_hash,
                payment_stage=payment.payment_stage,
                amount_q_atoms=payment.amount_q_atoms,
            )
        )

    return (
        calculation,
        approval,
        commitment,
        epoch_tx,
        calculation_envelope,
        allocation_envelope,
        reserve_envelope,
        build_maturity_payment(calculation.payments[1], "2030-01-01T00:00:04Z"),
        build_maturity_payment(calculation.payments[2], "2030-01-01T00:00:05Z"),
    )


def _unclaimed_envelopes():
    calculation = DevelopmentRewardCalculator().calculate(
        DevelopmentPoolInput(
            epoch=20,
            distributable_epoch_emission_q_atoms=DEFAULT_DISTRIBUTABLE_EPOCH_EMISSION_Q_ATOMS,
        ),
        [
            DevelopmentContributionInput(
                contribution_id="unclaimed-contribution",
                contribution_epoch=10,
                contribution_units_milli=10_000,
                contribution_class="CODE",
                role_allocations=[
                    DevelopmentRoleInput(
                        contributor_id="unclaimed-contributor",
                        role="AUTHOR",
                        allocation_basis_points=10_000,
                        wallet_address=None,
                    )
                ],
            )
        ],
    )
    approval = _approval(
        calculation.policy,
        authorized_operation_types=[
            "DEVELOPMENT_REWARD_CALCULATE",
            "DEVELOPMENT_POOL_ALLOCATE",
            "DEVELOPMENT_REWARD_RESERVE",
            "DEVELOPMENT_REWARD_MARK_UNCLAIMED",
            "DEVELOPMENT_REWARD_CLAIM",
            "DEVELOPMENT_REWARD_EXPIRE_UNCLAIMED",
            "DEVELOPMENT_REWARD_FINALIZE_COMMITMENT",
        ],
        economic_effect_profile="DEVELOPMENT_PAYMENTS",
    )
    commitment = build_development_reward_commitment(
        calculation,
        activation_approval=approval,
        current_epoch=20,
    )
    epoch_tx = _epoch_transition(calculation)
    epoch_operation_id = LedgerOperationEnvelope.model_validate(json.loads(epoch_tx)).operation_id
    calculation_envelope = build_development_reward_operation(
        DevelopmentRewardOperationRequest(
            operation_type="DEVELOPMENT_REWARD_CALCULATE",
            created_at="2030-01-01T00:00:01Z",
            commitment=commitment,
            activation_approval=approval,
            calculation=calculation,
        )
    )
    allocation_envelope = build_development_reward_operation(
        DevelopmentRewardOperationRequest(
            operation_type="DEVELOPMENT_POOL_ALLOCATE",
            created_at="2030-01-01T00:00:02Z",
            commitment=commitment,
            activation_approval=approval,
            calculation=calculation,
            amount_q_atoms=calculation.pool.base_allocation_q_atoms,
            calculation_operation_id=calculation_envelope.operation_id,
            source_epoch_transition_operation_id=epoch_operation_id,
            pool_budget_reference="epoch:20:GENERAL_DEVELOPMENT",
        )
    )
    schedule = calculation.schedules[0]
    reserve_envelope = build_development_reward_operation(
        DevelopmentRewardOperationRequest(
            operation_type="DEVELOPMENT_REWARD_RESERVE",
            created_at="2030-01-01T00:00:03Z",
            commitment=commitment,
            activation_approval=approval,
            calculation=calculation,
            amount_q_atoms=schedule.gross_reward_q_atoms,
            calculation_operation_id=calculation_envelope.operation_id,
            pool_allocation_id=allocation_envelope.payload["pool_allocation"]["allocation_id"],
            pool_allocation_operation_id=allocation_envelope.operation_id,
            reward_id=schedule.reward_id,
        )
    )
    payment = next(item for item in calculation.payments if item.payment_stage == "IMMEDIATE")
    unclaimed_envelope = build_development_reward_operation(
        DevelopmentRewardOperationRequest(
            operation_type="DEVELOPMENT_REWARD_MARK_UNCLAIMED",
            created_at="2030-01-01T00:00:04Z",
            commitment=commitment,
            activation_approval=approval,
            calculation=calculation,
            calculation_operation_id=calculation_envelope.operation_id,
            pool_allocation_id=allocation_envelope.payload["pool_allocation"]["allocation_id"],
            pool_allocation_operation_id=allocation_envelope.operation_id,
            reserve_id=reserve_envelope.payload["reward_reserve"]["reserve_id"],
            reserve_operation_id=reserve_envelope.operation_id,
            reward_id=payment.reward_id,
            contributor_id=payment.contributor_id,
            role=payment.role,
            payment_hash=payment.payment_hash,
            payment_stage=payment.payment_stage,
            amount_q_atoms=payment.amount_q_atoms,
        )
    )
    return (
        calculation,
        approval,
        commitment,
        epoch_tx,
        calculation_envelope,
        allocation_envelope,
        reserve_envelope,
        unclaimed_envelope,
    )


def _claim_envelopes():
    (
        calculation,
        approval,
        commitment,
        epoch_tx,
        calculation_envelope,
        allocation_envelope,
        reserve_envelope,
        unclaimed_envelope,
    ) = _unclaimed_envelopes()
    payment = calculation.payments[0]
    reserve_id = reserve_envelope.payload["reward_reserve"]["reserve_id"]
    unclaimed_id = development_reward_unclaimed_id(
        reserve_id=reserve_id,
        payment_hash=payment.payment_hash,
        payment_stage=payment.payment_stage,
    )
    binding = _wallet_binding(
        contributor_id=payment.contributor_id,
        wallet_address="q1claimed",
    )
    claim_epoch = calculation.epoch + 1
    claim = build_development_reward_operation(
        DevelopmentRewardOperationRequest(
            operation_type="DEVELOPMENT_REWARD_CLAIM",
            created_at="2030-01-01T00:00:05Z",
            commitment=commitment,
            activation_approval=approval,
            calculation=calculation,
            calculation_operation_id=calculation_envelope.operation_id,
            pool_allocation_id=allocation_envelope.payload["pool_allocation"]["allocation_id"],
            pool_allocation_operation_id=allocation_envelope.operation_id,
            reserve_id=reserve_id,
            reserve_operation_id=reserve_envelope.operation_id,
            unclaimed_id=unclaimed_id,
            unclaimed_operation_id=unclaimed_envelope.operation_id,
            source_epoch_transition_operation_id=LedgerOperationEnvelope.model_validate(
                json.loads(epoch_tx)
            ).operation_id,
            reward_id=payment.reward_id,
            contribution_id=payment.contribution_id,
            contributor_id=payment.contributor_id,
            recipient_wallet=binding.wallet_address,
            role=payment.role,
            payment_hash=payment.payment_hash,
            payment_stage=payment.payment_stage,
            amount_q_atoms=payment.amount_q_atoms,
            claim_epoch=claim_epoch,
            wallet_binding=binding,
        )
    )
    return (
        calculation,
        approval,
        commitment,
        epoch_tx,
        calculation_envelope,
        allocation_envelope,
        reserve_envelope,
        unclaimed_envelope,
        claim,
        binding,
    )


def _expiry_envelopes():
    (
        calculation,
        approval,
        commitment,
        epoch_tx,
        calculation_envelope,
        allocation_envelope,
        reserve_envelope,
        unclaimed_envelope,
    ) = _unclaimed_envelopes()
    payment = next(item for item in calculation.payments if item.state == "UNCLAIMED")
    unclaimed_id = development_reward_unclaimed_id(
        reserve_id=reserve_envelope.payload["reward_reserve"]["reserve_id"],
        payment_hash=payment.payment_hash,
        payment_stage=payment.payment_stage,
    )
    expiry_epoch = calculation.epoch + calculation.policy.claim_window_epochs + 1
    expiry_epoch_tx = _epoch_transition(calculation, opening_epoch=expiry_epoch)
    expiry_epoch_id = LedgerOperationEnvelope.model_validate(json.loads(expiry_epoch_tx)).operation_id
    expiry = build_development_reward_operation(
        DevelopmentRewardOperationRequest(
            operation_type="DEVELOPMENT_REWARD_EXPIRE_UNCLAIMED",
            created_at="2030-01-01T00:00:05Z",
            commitment=commitment,
            activation_approval=approval,
            calculation=calculation,
            calculation_operation_id=calculation_envelope.operation_id,
            pool_allocation_id=allocation_envelope.payload["pool_allocation"]["allocation_id"],
            pool_allocation_operation_id=allocation_envelope.operation_id,
            reserve_id=reserve_envelope.payload["reward_reserve"]["reserve_id"],
            reserve_operation_id=reserve_envelope.operation_id,
            unclaimed_id=unclaimed_id,
            unclaimed_operation_id=unclaimed_envelope.operation_id,
            source_epoch_transition_operation_id=expiry_epoch_id,
            reward_id=payment.reward_id,
            contribution_id=payment.contribution_id,
            contributor_id=payment.contributor_id,
            role=payment.role,
            payment_hash=payment.payment_hash,
            payment_stage=payment.payment_stage,
            amount_q_atoms=payment.amount_q_atoms,
            expiry_epoch=expiry_epoch,
            return_destination="CARRYOVER",
        )
    )
    return (
        calculation,
        approval,
        commitment,
        epoch_tx,
        calculation_envelope,
        allocation_envelope,
        reserve_envelope,
        unclaimed_envelope,
        expiry_epoch_tx,
        expiry,
    )


def _build_payment_retry(
    calculation,
    approval,
    commitment,
    allocation_envelope,
    reserve_envelope,
    payment_envelope,
    *,
    created_at: str,
):
    payload = payment_envelope.payload
    return build_development_reward_operation(
        DevelopmentRewardOperationRequest(
            operation_type="DEVELOPMENT_REWARD_PAY_IMMEDIATE",
            created_at=created_at,
            commitment=commitment,
            activation_approval=approval,
            calculation=calculation,
            calculation_operation_id=payload["calculation_operation_id"],
            pool_allocation_id=payload["pool_allocation_id"],
            pool_allocation_operation_id=allocation_envelope.operation_id,
            reserve_id=payload["reserve_id"],
            reserve_operation_id=reserve_envelope.operation_id,
            reward_id=payload["reward_id"],
            contributor_id=payload["contributor_id"],
            recipient_wallet=payload["recipient_wallet"],
            role=payload["role"],
            payment_hash=payload["payment_hash"],
            payment_stage=payload["payment_stage"],
            amount_q_atoms=payload["amount_q_atoms"],
        )
    )


def test_development_operations_have_explicit_consensus_coverage():
    assert DECLARED_OPERATION_TYPES | IMPLEMENTED_OPERATION_TYPES <= KNOWN_OPERATION_TYPES
    assert all(operation_coverage(item) == "IMPLEMENTED" for item in DECLARED_OPERATION_TYPES)
    assert operation_coverage("DEVELOPMENT_REWARD_CALCULATE") == "IMPLEMENTED"
    assert operation_coverage("DEVELOPMENT_POOL_ALLOCATE") == "IMPLEMENTED"
    assert operation_coverage("DEVELOPMENT_REWARD_RESERVE") == "IMPLEMENTED"
    assert operation_coverage("DEVELOPMENT_REWARD_PAY_IMMEDIATE") == "IMPLEMENTED"
    assert operation_coverage("DEVELOPMENT_REWARD_PAY_MATURITY") == "IMPLEMENTED"
    assert operation_coverage("DEVELOPMENT_REWARD_MARK_UNCLAIMED") == "IMPLEMENTED"
    assert all(strict_operation_coverage_error(item) is None for item in DECLARED_OPERATION_TYPES)
    assert strict_operation_coverage_error("DEVELOPMENT_REWARD_CALCULATE") is None


def test_builder_emits_deterministic_payment_envelope_without_ledger_write():
    _, approval, commitment, _, _, _, _, payment = _payment_envelopes()
    first = payment
    second = payment.model_copy()

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.operation_type == "DEVELOPMENT_REWARD_PAY_IMMEDIATE"
    assert first.origin_type == "protocol"
    assert first.sender_wallet is None
    assert first.payload["activation_id"] == approval.activation_id
    assert first.payload["activation_approval_hash"] == approval.approval_hash
    assert first.payload["commitment"]["commitment_hash"] == commitment.commitment_hash
    assert first.payload["activation_approval"]["approval_hash"] == approval.approval_hash
    assert commitment.calculation_root in first.evidence_references
    assert first.payload["payload_hash"].startswith("sha256:")
    assert strict_operation_coverage_error(first.operation_type) is None
    assert LedgerOperationService().list_operations() == []


def test_strict_execution_applies_source_bound_immediate_payment():
    calculation, _, _, epoch_tx, calculation_envelope, allocation_envelope, reserve_envelope, payment = (
        _payment_envelopes()
    )
    ledger = LedgerOperationService()
    engine = ExecutionEngine(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        strict_operation_coverage=True,
    )

    for height, tx in (
        (1, epoch_tx),
        (2, json.dumps(calculation_envelope.model_dump(mode="json")).encode("utf-8")),
        (3, json.dumps(allocation_envelope.model_dump(mode="json")).encode("utf-8")),
        (4, json.dumps(reserve_envelope.model_dump(mode="json")).encode("utf-8")),
    ):
        result = engine.execute_block(block_height=height, block_hash=bytes([height + 30]) * 32, txs=[tx])
        assert result.operations_executed == 1
        assert result.operations_rejected == 0
    result = engine.execute_block(
        block_height=5,
        block_hash=b"D" * 32,
        txs=[json.dumps(payment.model_dump(mode="json")).encode("utf-8")],
    )

    assert result.operations_executed == 1
    assert result.operations_rejected == 0
    assert result.execution_events[0].emitted_events == ["DevelopmentRewardPaidImmediate"]
    assert ledger.wallet_q_atom_balance("q1scenario") == calculation.payments[0].amount_q_atoms
    payment_id = ledger.snapshot_settlement_state()["development_reward_payment_records"][0]["payment_id"]
    record = ledger.development_reward_payment(payment_id)
    assert record is not None
    assert record["reserve_remaining_q_atoms"] == (
        calculation.schedules[0].gross_reward_q_atoms - calculation.payments[0].amount_q_atoms
    )
    assert record["pool_remaining_q_atoms"] == (
        calculation.pool.base_allocation_q_atoms - calculation.schedules[0].gross_reward_q_atoms
    )


def test_reward_payment_rejects_same_block_dependencies():
    _, _, _, epoch_tx, calculation_envelope, allocation_envelope, reserve_envelope, payment = _payment_envelopes()
    ledger = LedgerOperationService()
    engine = ExecutionEngine(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        strict_operation_coverage=True,
    )

    result = engine.execute_block(
        block_height=1,
        block_hash=b"E" * 32,
        txs=[
            epoch_tx,
            json.dumps(calculation_envelope.model_dump(mode="json")).encode("utf-8"),
            json.dumps(allocation_envelope.model_dump(mode="json")).encode("utf-8"),
            json.dumps(reserve_envelope.model_dump(mode="json")).encode("utf-8"),
            json.dumps(payment.model_dump(mode="json")).encode("utf-8"),
        ],
    )

    assert result.operations_executed == 2
    assert result.operations_rejected == 3
    assert result.execution_events[4].error == "DEVELOPMENT_REWARD_PAYMENT_CALCULATION_NOT_FINALIZED"
    assert ledger.snapshot_settlement_state()["development_reward_payment_records"] == []
    assert ledger.wallet_q_atom_balance("q1scenario") == 0


def test_reward_payment_rejects_tampered_recipient_binding_after_sources_finalize():
    _, _, _, epoch_tx, calculation_envelope, allocation_envelope, reserve_envelope, payment = _payment_envelopes()
    ledger = LedgerOperationService()
    engine = ExecutionEngine(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        strict_operation_coverage=True,
    )
    for height, tx in (
        (1, epoch_tx),
        (2, json.dumps(calculation_envelope.model_dump(mode="json")).encode("utf-8")),
        (3, json.dumps(allocation_envelope.model_dump(mode="json")).encode("utf-8")),
        (4, json.dumps(reserve_envelope.model_dump(mode="json")).encode("utf-8")),
    ):
        result = engine.execute_block(block_height=height, block_hash=bytes([height + 70]) * 32, txs=[tx])
        assert result.operations_executed == 1

    from aidn_hypervisor.reward.development_distribution import canonical_hash

    tampered_payload = payment.payload.copy()
    tampered_payload["recipient_wallet"] = "q1attacker"
    unsigned_payload = tampered_payload.copy()
    unsigned_payload.pop("payload_hash", None)
    tampered_payload["payload_hash"] = canonical_hash(unsigned_payload)
    tampered_data = payment.model_dump(mode="json")
    tampered_data["payload"] = tampered_payload
    tampered_data.pop("operation_id", None)
    tampered = LedgerOperationEnvelope.model_validate(tampered_data)

    result = engine.execute_block(
        block_height=5,
        block_hash=b"F" * 32,
        txs=[json.dumps(tampered.model_dump(mode="json")).encode("utf-8")],
    )

    assert result.operations_executed == 0
    assert result.operations_rejected == 1
    assert result.execution_events[0].error == "DEVELOPMENT_REWARD_PAYMENT_BINDING_INVALID"
    assert ledger.snapshot_settlement_state()["development_reward_payment_records"] == []
    assert ledger.wallet_q_atom_balance("q1attacker") == 0


def test_abci_reward_payment_replay_and_snapshot_restore(tmp_path):
    (
        calculation,
        approval,
        commitment,
        epoch_tx,
        calculation_envelope,
        allocation_envelope,
        reserve_envelope,
        payment,
    ) = _payment_envelopes()
    store = ABCIStateStore(tmp_path / "abci", chunk_size=128)
    app = AIDNABCIApplication(
        ledger_service=LedgerOperationService(),
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        state_store=store,
        strict_operation_coverage=True,
    )
    for height, tx in (
        (1, epoch_tx),
        (2, json.dumps(calculation_envelope.model_dump(mode="json")).encode("utf-8")),
        (3, json.dumps(allocation_envelope.model_dump(mode="json")).encode("utf-8")),
        (4, json.dumps(reserve_envelope.model_dump(mode="json")).encode("utf-8")),
        (5, json.dumps(payment.model_dump(mode="json")).encode("utf-8")),
    ):
        result = app.finalize_block(
            block_height=height,
            block_hash=bytes([height + 80]) * 32,
            txs=[tx],
        )
        assert result.code == "ok"

    retry = _build_payment_retry(
        calculation,
        approval,
        commitment,
        allocation_envelope,
        reserve_envelope,
        payment,
        created_at="2030-01-01T00:00:05Z",
    )
    retry_result, retry_tx_results = app.finalize_block_with_results(
        block_height=6,
        block_hash=b"G" * 32,
        txs=[json.dumps(retry.model_dump(mode="json")).encode("utf-8")],
    )
    restored = AIDNABCIApplication(
        ledger_service=LedgerOperationService(),
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        state_store=store,
        strict_operation_coverage=True,
    )

    payment_id = app.ledger.snapshot_settlement_state()["development_reward_payment_records"][0]["payment_id"]
    assert retry.operation_id != payment.operation_id
    assert retry_result.code == "ok"
    assert retry_tx_results[0].code == "rejected"
    assert retry_tx_results[0].log == "DEVELOPMENT_REWARD_PAYMENT_DUPLICATE"
    assert app.ledger.wallet_q_atom_balance("q1scenario") == calculation.payments[0].amount_q_atoms
    assert restored.info().last_block_height == 6
    assert restored.info().last_block_app_hash == app.info().last_block_app_hash
    assert restored.ledger.development_reward_payment(payment_id) == app.ledger.development_reward_payment(payment_id)
    assert restored.ledger.snapshot_operations() == app.ledger.snapshot_operations()
    assert restored.ledger.wallet_q_atom_balance("q1scenario") == calculation.payments[0].amount_q_atoms


def test_builder_emits_source_bound_maturity_payment_envelope():
    _, approval, commitment, epoch_tx, _, _, _, stage_one, _ = _maturity_envelopes()

    assert stage_one.operation_type == "DEVELOPMENT_REWARD_PAY_MATURITY"
    assert stage_one.payload["payment_stage"] == "MATURITY_STAGE_ONE"
    assert stage_one.payload["source_epoch_transition_operation_id"] == (
        LedgerOperationEnvelope.model_validate(json.loads(epoch_tx)).operation_id
    )
    assert stage_one.payload["activation_id"] == approval.activation_id
    assert stage_one.payload["commitment"]["commitment_hash"] == commitment.commitment_hash
    assert strict_operation_coverage_error(stage_one.operation_type) is None


def test_strict_execution_applies_maturity_payment_after_boundary():
    calculation, _, _, epoch_tx, calculation_envelope, allocation_envelope, reserve_envelope, stage_one, _ = (
        _maturity_envelopes()
    )
    ledger = LedgerOperationService()
    engine = ExecutionEngine(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        strict_operation_coverage=True,
    )

    for height, tx in (
        (1, epoch_tx),
        (2, json.dumps(calculation_envelope.model_dump(mode="json")).encode("utf-8")),
        (3, json.dumps(allocation_envelope.model_dump(mode="json")).encode("utf-8")),
        (4, json.dumps(reserve_envelope.model_dump(mode="json")).encode("utf-8")),
    ):
        result = engine.execute_block(block_height=height, block_hash=bytes([height + 90]) * 32, txs=[tx])
        assert result.operations_executed == 1
        assert result.operations_rejected == 0

    result = engine.execute_block(
        block_height=5,
        block_hash=b"V" * 32,
        txs=[json.dumps(stage_one.model_dump(mode="json")).encode("utf-8")],
    )

    assert result.operations_executed == 1
    assert result.operations_rejected == 0
    assert result.execution_events[0].emitted_events == ["DevelopmentRewardPaidMaturity"]
    assert ledger.wallet_q_atom_balance("q1scenario") == calculation.payments[1].amount_q_atoms
    payment_id = ledger.snapshot_settlement_state()["development_reward_payment_records"][0]["payment_id"]
    record = ledger.development_reward_payment(payment_id)
    assert record is not None
    assert record["payment_stage"] == "MATURITY_STAGE_ONE"
    assert record["reserve_remaining_q_atoms"] == (
        calculation.schedules[0].gross_reward_q_atoms - calculation.payments[1].amount_q_atoms
    )
    assert record["pool_remaining_q_atoms"] == (
        calculation.pool.base_allocation_q_atoms - calculation.schedules[0].gross_reward_q_atoms
    )


def test_maturity_payment_rejects_same_block_dependencies():
    _, _, _, epoch_tx, calculation_envelope, allocation_envelope, reserve_envelope, stage_one, _ = _maturity_envelopes()
    ledger = LedgerOperationService()
    engine = ExecutionEngine(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        strict_operation_coverage=True,
    )

    result = engine.execute_block(
        block_height=1,
        block_hash=b"W" * 32,
        txs=[
            epoch_tx,
            json.dumps(calculation_envelope.model_dump(mode="json")).encode("utf-8"),
            json.dumps(allocation_envelope.model_dump(mode="json")).encode("utf-8"),
            json.dumps(reserve_envelope.model_dump(mode="json")).encode("utf-8"),
            json.dumps(stage_one.model_dump(mode="json")).encode("utf-8"),
        ],
    )

    assert result.operations_executed == 2
    assert result.operations_rejected == 3
    assert result.execution_events[4].error == "DEVELOPMENT_REWARD_PAYMENT_CALCULATION_NOT_FINALIZED"
    assert ledger.snapshot_settlement_state()["development_reward_payment_records"] == []
    assert ledger.wallet_q_atom_balance("q1scenario") == 0


def test_maturity_payment_rejects_stage_two_before_boundary():
    _, _, _, epoch_tx, calculation_envelope, allocation_envelope, reserve_envelope, _, stage_two = _maturity_envelopes()
    ledger = LedgerOperationService()
    engine = ExecutionEngine(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        strict_operation_coverage=True,
    )
    for height, tx in (
        (1, epoch_tx),
        (2, json.dumps(calculation_envelope.model_dump(mode="json")).encode("utf-8")),
        (3, json.dumps(allocation_envelope.model_dump(mode="json")).encode("utf-8")),
        (4, json.dumps(reserve_envelope.model_dump(mode="json")).encode("utf-8")),
    ):
        result = engine.execute_block(block_height=height, block_hash=bytes([height + 100]) * 32, txs=[tx])
        assert result.operations_executed == 1

    result = engine.execute_block(
        block_height=5,
        block_hash=b"X" * 32,
        txs=[json.dumps(stage_two.model_dump(mode="json")).encode("utf-8")],
    )

    assert result.operations_executed == 0
    assert result.operations_rejected == 1
    assert result.execution_events[0].error == "DEVELOPMENT_REWARD_MATURITY_NOT_REACHED"
    assert ledger.snapshot_settlement_state()["development_reward_payment_records"] == []
    assert ledger.wallet_q_atom_balance("q1scenario") == 0


def test_abci_maturity_payment_replay_and_snapshot_restore(tmp_path):
    (
        calculation,
        approval,
        commitment,
        epoch_tx,
        calculation_envelope,
        allocation_envelope,
        reserve_envelope,
        stage_one,
        _,
    ) = _maturity_envelopes()
    store = ABCIStateStore(tmp_path / "abci", chunk_size=128)
    app = AIDNABCIApplication(
        ledger_service=LedgerOperationService(),
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        state_store=store,
        strict_operation_coverage=True,
    )
    for height, tx in (
        (1, epoch_tx),
        (2, json.dumps(calculation_envelope.model_dump(mode="json")).encode("utf-8")),
        (3, json.dumps(allocation_envelope.model_dump(mode="json")).encode("utf-8")),
        (4, json.dumps(reserve_envelope.model_dump(mode="json")).encode("utf-8")),
        (5, json.dumps(stage_one.model_dump(mode="json")).encode("utf-8")),
    ):
        result = app.finalize_block(
            block_height=height,
            block_hash=bytes([height + 110]) * 32,
            txs=[tx],
        )
        assert result.code == "ok"

    payload = stage_one.payload
    retry = build_development_reward_operation(
        DevelopmentRewardOperationRequest(
            operation_type="DEVELOPMENT_REWARD_PAY_MATURITY",
            created_at="2030-01-01T00:00:06Z",
            commitment=commitment,
            activation_approval=approval,
            calculation=calculation,
            calculation_operation_id=payload["calculation_operation_id"],
            pool_allocation_id=payload["pool_allocation_id"],
            pool_allocation_operation_id=allocation_envelope.operation_id,
            reserve_id=payload["reserve_id"],
            reserve_operation_id=reserve_envelope.operation_id,
            source_epoch_transition_operation_id=payload["source_epoch_transition_operation_id"],
            reward_id=payload["reward_id"],
            contributor_id=payload["contributor_id"],
            recipient_wallet=payload["recipient_wallet"],
            role=payload["role"],
            payment_hash=payload["payment_hash"],
            payment_stage=payload["payment_stage"],
            amount_q_atoms=payload["amount_q_atoms"],
        )
    )
    retry_result, retry_tx_results = app.finalize_block_with_results(
        block_height=6,
        block_hash=b"Y" * 32,
        txs=[json.dumps(retry.model_dump(mode="json")).encode("utf-8")],
    )
    restored = AIDNABCIApplication(
        ledger_service=LedgerOperationService(),
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        state_store=store,
        strict_operation_coverage=True,
    )

    payment_id = app.ledger.snapshot_settlement_state()["development_reward_payment_records"][0]["payment_id"]
    assert retry.operation_id != stage_one.operation_id
    assert retry_result.code == "ok"
    assert retry_tx_results[0].code == "rejected"
    assert retry_tx_results[0].log == "DEVELOPMENT_REWARD_PAYMENT_DUPLICATE"
    assert app.ledger.wallet_q_atom_balance("q1scenario") == calculation.payments[1].amount_q_atoms
    assert restored.info().last_block_height == 6
    assert restored.info().last_block_app_hash == app.info().last_block_app_hash
    assert restored.ledger.development_reward_payment(payment_id) == app.ledger.development_reward_payment(payment_id)
    assert restored.ledger.snapshot_operations() == app.ledger.snapshot_operations()
    assert restored.ledger.wallet_q_atom_balance("q1scenario") == calculation.payments[1].amount_q_atoms


def test_builder_emits_source_bound_unclaimed_envelope_without_wallet():
    _, approval, commitment, _, _, _, _, unclaimed = _unclaimed_envelopes()

    assert unclaimed.operation_type == "DEVELOPMENT_REWARD_MARK_UNCLAIMED"
    assert "recipient_wallet" not in unclaimed.payload
    assert unclaimed.payload["reward_payment"]["state"] == "UNCLAIMED"
    assert unclaimed.payload["reward_payment"]["wallet_address"] is None
    assert unclaimed.payload["activation_id"] == approval.activation_id
    assert unclaimed.payload["commitment"]["commitment_hash"] == commitment.commitment_hash
    assert strict_operation_coverage_error(unclaimed.operation_type) is None


def test_strict_execution_records_unclaimed_stage_without_consuming_reserve():
    (
        calculation,
        _,
        _,
        epoch_tx,
        calculation_envelope,
        allocation_envelope,
        reserve_envelope,
        unclaimed,
    ) = _unclaimed_envelopes()
    ledger = LedgerOperationService()
    engine = ExecutionEngine(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        strict_operation_coverage=True,
    )

    for height, tx in (
        (1, epoch_tx),
        (2, json.dumps(calculation_envelope.model_dump(mode="json")).encode("utf-8")),
        (3, json.dumps(allocation_envelope.model_dump(mode="json")).encode("utf-8")),
        (4, json.dumps(reserve_envelope.model_dump(mode="json")).encode("utf-8")),
    ):
        result = engine.execute_block(block_height=height, block_hash=bytes([height + 120]) * 32, txs=[tx])
        assert result.operations_executed == 1
        assert result.operations_rejected == 0

    reserve_before = ledger.snapshot_settlement_state()["development_reward_reserves"][0]
    result = engine.execute_block(
        block_height=5,
        block_hash=b"U" * 32,
        txs=[json.dumps(unclaimed.model_dump(mode="json")).encode("utf-8")],
    )

    assert result.operations_executed == 1
    assert result.operations_rejected == 0
    assert result.execution_events[0].emitted_events == ["DevelopmentRewardMarkedUnclaimed"]
    assert ledger.wallet_q_atom_balance("unclaimed-contributor") == 0
    state = ledger.snapshot_settlement_state()
    assert state["development_reward_payment_records"] == []
    assert state["development_reward_reserves"][0] == reserve_before
    assert len(state["development_reward_unclaimed_records"]) == 1
    unclaimed_id = state["development_reward_unclaimed_records"][0]["unclaimed_id"]
    record = ledger.development_reward_unclaimed(unclaimed_id)
    assert record is not None
    assert record["state"] == "UNCLAIMED"
    assert record["claim_expiration_epoch"] == calculation.epoch + calculation.policy.claim_window_epochs
    assert record["amount_q_atoms"] == calculation.payments[0].amount_q_atoms


def test_builder_emits_expiry_return_envelope_without_wallet():
    calculation, approval, commitment, _, _, _, _, _, _, expiry = _expiry_envelopes()

    assert expiry.operation_type == "DEVELOPMENT_REWARD_EXPIRE_UNCLAIMED"
    assert "recipient_wallet" not in expiry.payload
    assert expiry.payload["return_destination"] == "CARRYOVER"
    assert expiry.payload["expiry_epoch"] == (calculation.epoch + calculation.policy.claim_window_epochs + 1)
    assert expiry.payload["reward_payment"]["state"] == "UNCLAIMED"
    assert expiry.payload["reward_unclaimed"]["unclaimed_id"] == expiry.payload["unclaimed_id"]
    assert expiry.payload["activation_id"] == approval.activation_id
    assert expiry.payload["commitment"]["commitment_hash"] == commitment.commitment_hash
    assert strict_operation_coverage_error(expiry.operation_type) is None


def test_strict_execution_returns_expired_unclaimed_stage_to_carryover():
    (
        calculation,
        _,
        _,
        epoch_tx,
        calculation_envelope,
        allocation_envelope,
        reserve_envelope,
        unclaimed,
        expiry_epoch_tx,
        expiry,
    ) = _expiry_envelopes()
    ledger = LedgerOperationService()
    engine = ExecutionEngine(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        strict_operation_coverage=True,
    )

    for height, tx in (
        (1, epoch_tx),
        (2, json.dumps(calculation_envelope.model_dump(mode="json")).encode("utf-8")),
        (3, json.dumps(allocation_envelope.model_dump(mode="json")).encode("utf-8")),
        (4, json.dumps(reserve_envelope.model_dump(mode="json")).encode("utf-8")),
        (5, json.dumps(unclaimed.model_dump(mode="json")).encode("utf-8")),
        (6, expiry_epoch_tx),
    ):
        result = engine.execute_block(block_height=height, block_hash=bytes([height + 180]) * 32, txs=[tx])
        assert result.operations_executed == 1
        assert result.operations_rejected == 0

    result = engine.execute_block(
        block_height=7,
        block_hash=b"V" * 32,
        txs=[json.dumps(expiry.model_dump(mode="json")).encode("utf-8")],
    )

    assert result.operations_executed == 1
    assert result.operations_rejected == 0
    assert result.execution_events[0].emitted_events == ["DevelopmentRewardExpiredReturned"]
    assert ledger.wallet_q_atom_balance("unclaimed-contributor") == 0
    state = ledger.snapshot_settlement_state()
    assert len(state["development_reward_expiry_records"]) == 1
    expiry_record = state["development_reward_expiry_records"][0]
    assert expiry_record["state"] == "EXPIRED_RETURNED"
    assert expiry_record["amount_q_atoms"] == calculation.payments[0].amount_q_atoms
    assert expiry_record["expiry_epoch"] == expiry.payload["expiry_epoch"]
    assert expiry_record["pool_remaining_q_atoms"] == (
        allocation_envelope.payload["pool_allocation"]["allocated_q_atoms"]
        - reserve_envelope.payload["reward_reserve"]["reserved_q_atoms"]
        + calculation.payments[0].amount_q_atoms
    )


def test_expiry_return_rejects_same_block_dependencies():
    (
        _,
        _,
        _,
        epoch_tx,
        calculation_envelope,
        allocation_envelope,
        reserve_envelope,
        unclaimed,
        expiry_epoch_tx,
        expiry,
    ) = _expiry_envelopes()
    ledger = LedgerOperationService()
    engine = ExecutionEngine(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        strict_operation_coverage=True,
    )

    result = engine.execute_block(
        block_height=1,
        block_hash=b"W" * 32,
        txs=[
            epoch_tx,
            json.dumps(calculation_envelope.model_dump(mode="json")).encode("utf-8"),
            json.dumps(allocation_envelope.model_dump(mode="json")).encode("utf-8"),
            json.dumps(reserve_envelope.model_dump(mode="json")).encode("utf-8"),
            json.dumps(unclaimed.model_dump(mode="json")).encode("utf-8"),
            expiry_epoch_tx,
            json.dumps(expiry.model_dump(mode="json")).encode("utf-8"),
        ],
    )

    assert result.operations_executed == 3
    assert result.operations_rejected == 4
    assert result.execution_events[6].error == "DEVELOPMENT_REWARD_EXPIRY_CALCULATION_NOT_FINALIZED"
    assert ledger.snapshot_settlement_state()["development_reward_expiry_records"] == []


def test_reward_claim_is_rejected_after_expiry_return():
    (
        calculation,
        approval,
        commitment,
        epoch_tx,
        calculation_envelope,
        allocation_envelope,
        reserve_envelope,
        unclaimed,
        expiry_epoch_tx,
        expiry,
    ) = _expiry_envelopes()
    payment = calculation.payments[0]
    binding = _wallet_binding(contributor_id=payment.contributor_id, wallet_address="q1expired")
    claim = build_development_reward_operation(
        DevelopmentRewardOperationRequest(
            operation_type="DEVELOPMENT_REWARD_CLAIM",
            created_at="2030-01-01T00:00:06Z",
            commitment=commitment,
            activation_approval=approval,
            calculation=calculation,
            calculation_operation_id=calculation_envelope.operation_id,
            pool_allocation_id=allocation_envelope.payload["pool_allocation"]["allocation_id"],
            pool_allocation_operation_id=allocation_envelope.operation_id,
            reserve_id=reserve_envelope.payload["reward_reserve"]["reserve_id"],
            reserve_operation_id=reserve_envelope.operation_id,
            unclaimed_id=expiry.payload["unclaimed_id"],
            unclaimed_operation_id=unclaimed.operation_id,
            source_epoch_transition_operation_id=LedgerOperationEnvelope.model_validate(
                json.loads(epoch_tx)
            ).operation_id,
            reward_id=payment.reward_id,
            contribution_id=payment.contribution_id,
            contributor_id=payment.contributor_id,
            recipient_wallet=binding.wallet_address,
            role=payment.role,
            payment_hash=payment.payment_hash,
            payment_stage=payment.payment_stage,
            amount_q_atoms=payment.amount_q_atoms,
            claim_epoch=calculation.epoch + 1,
            wallet_binding=binding,
        )
    )
    ledger = LedgerOperationService()
    engine = ExecutionEngine(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        strict_operation_coverage=True,
    )
    for height, tx in (
        (1, epoch_tx),
        (2, json.dumps(calculation_envelope.model_dump(mode="json")).encode("utf-8")),
        (3, json.dumps(allocation_envelope.model_dump(mode="json")).encode("utf-8")),
        (4, json.dumps(reserve_envelope.model_dump(mode="json")).encode("utf-8")),
        (5, json.dumps(unclaimed.model_dump(mode="json")).encode("utf-8")),
        (6, expiry_epoch_tx),
        (7, json.dumps(expiry.model_dump(mode="json")).encode("utf-8")),
    ):
        result = engine.execute_block(block_height=height, block_hash=bytes([height + 190]) * 32, txs=[tx])
        assert result.operations_executed == 1

    result = engine.execute_block(
        block_height=8,
        block_hash=b"X" * 32,
        txs=[json.dumps(claim.model_dump(mode="json")).encode("utf-8")],
    )

    assert result.operations_executed == 0
    assert result.operations_rejected == 1
    assert result.execution_events[0].error == "DEVELOPMENT_REWARD_CLAIM_EXPIRED_RETURNED"
    assert ledger.wallet_q_atom_balance(binding.wallet_address) == 0


def test_abci_expiry_return_replay_and_snapshot_restore(tmp_path):
    (
        calculation,
        approval,
        commitment,
        epoch_tx,
        calculation_envelope,
        allocation_envelope,
        reserve_envelope,
        unclaimed,
        expiry_epoch_tx,
        expiry,
    ) = _expiry_envelopes()
    payload = expiry.payload
    retry = build_development_reward_operation(
        DevelopmentRewardOperationRequest(
            operation_type="DEVELOPMENT_REWARD_EXPIRE_UNCLAIMED",
            created_at="2030-01-01T00:00:08Z",
            commitment=commitment,
            activation_approval=approval,
            calculation=calculation,
            calculation_operation_id=payload["calculation_operation_id"],
            pool_allocation_id=payload["pool_allocation_id"],
            pool_allocation_operation_id=allocation_envelope.operation_id,
            reserve_id=payload["reserve_id"],
            reserve_operation_id=reserve_envelope.operation_id,
            unclaimed_id=payload["unclaimed_id"],
            unclaimed_operation_id=unclaimed.operation_id,
            source_epoch_transition_operation_id=payload["source_epoch_transition_operation_id"],
            reward_id=payload["reward_id"],
            contribution_id=payload["contribution_id"],
            contributor_id=payload["contributor_id"],
            role=payload["role"],
            payment_hash=payload["payment_hash"],
            payment_stage=payload["payment_stage"],
            amount_q_atoms=payload["amount_q_atoms"],
            expiry_epoch=payload["expiry_epoch"],
            return_destination=payload["return_destination"],
        )
    )
    store = ABCIStateStore(tmp_path / "abci", chunk_size=128)
    app = AIDNABCIApplication(
        ledger_service=LedgerOperationService(),
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        state_store=store,
        strict_operation_coverage=True,
    )
    for height, tx in (
        (1, epoch_tx),
        (2, json.dumps(calculation_envelope.model_dump(mode="json")).encode("utf-8")),
        (3, json.dumps(allocation_envelope.model_dump(mode="json")).encode("utf-8")),
        (4, json.dumps(reserve_envelope.model_dump(mode="json")).encode("utf-8")),
        (5, json.dumps(unclaimed.model_dump(mode="json")).encode("utf-8")),
        (6, expiry_epoch_tx),
        (7, json.dumps(expiry.model_dump(mode="json")).encode("utf-8")),
    ):
        result = app.finalize_block(block_height=height, block_hash=bytes([height + 200]) * 32, txs=[tx])
        assert result.code == "ok"

    retry_result, retry_tx_results = app.finalize_block_with_results(
        block_height=8,
        block_hash=b"Y" * 32,
        txs=[json.dumps(retry.model_dump(mode="json")).encode("utf-8")],
    )
    restored = AIDNABCIApplication(
        ledger_service=LedgerOperationService(),
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        state_store=store,
        strict_operation_coverage=True,
    )

    expiry_id = app.ledger.snapshot_settlement_state()["development_reward_expiry_records"][0]["expiry_id"]
    assert retry.operation_id != expiry.operation_id
    assert retry_result.code == "ok"
    assert retry_tx_results[0].code == "rejected"
    assert retry_tx_results[0].log == "DEVELOPMENT_REWARD_EXPIRY_DUPLICATE"
    assert app.ledger.wallet_q_atom_balance("unclaimed-contributor") == 0
    assert restored.info().last_block_height == 8
    assert restored.info().last_block_app_hash == app.info().last_block_app_hash
    assert restored.ledger.development_reward_expiry(expiry_id) == app.ledger.development_reward_expiry(expiry_id)
    assert restored.ledger.snapshot_operations() == app.ledger.snapshot_operations()
    assert (
        restored.ledger.snapshot_settlement_state()["development_reward_expiry_records"]
        == (app.ledger.snapshot_settlement_state()["development_reward_expiry_records"])
    )


def test_finalized_commitment_closes_auditable_reward_evidence_set(tmp_path):
    (
        calculation,
        approval,
        commitment,
        epoch_tx,
        calculation_envelope,
        allocation_envelope,
        reserve_envelope,
        unclaimed,
        expiry_epoch_tx,
        expiry,
    ) = _expiry_envelopes()
    store = ABCIStateStore(tmp_path / "abci", chunk_size=128)
    app = AIDNABCIApplication(
        ledger_service=LedgerOperationService(),
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        state_store=store,
        strict_operation_coverage=True,
    )
    for height, tx in (
        (1, epoch_tx),
        (2, json.dumps(calculation_envelope.model_dump(mode="json")).encode("utf-8")),
        (3, json.dumps(allocation_envelope.model_dump(mode="json")).encode("utf-8")),
        (4, json.dumps(reserve_envelope.model_dump(mode="json")).encode("utf-8")),
        (5, json.dumps(unclaimed.model_dump(mode="json")).encode("utf-8")),
        (6, expiry_epoch_tx),
        (7, json.dumps(expiry.model_dump(mode="json")).encode("utf-8")),
    ):
        result = app.finalize_block(block_height=height, block_hash=bytes([height + 210]) * 32, txs=[tx])
        assert result.code == "ok"

    state = app.ledger.snapshot_settlement_state()
    source_epoch_id = LedgerOperationEnvelope.model_validate(json.loads(epoch_tx)).operation_id
    source_operation_ids = [
        calculation_envelope.operation_id,
        allocation_envelope.operation_id,
        source_epoch_id,
        reserve_envelope.operation_id,
        unclaimed.operation_id,
        expiry.operation_id,
    ]
    reserve_records = state["development_reward_reserves"]
    unclaimed_records = state["development_reward_unclaimed_records"]
    expiry_records = state["development_reward_expiry_records"]
    final_request = DevelopmentRewardOperationRequest(
        operation_type="DEVELOPMENT_REWARD_FINALIZE_COMMITMENT",
        created_at="2030-01-01T00:00:08Z",
        commitment=commitment,
        activation_approval=approval,
        calculation=calculation,
        calculation_operation_id=calculation_envelope.operation_id,
        pool_allocation_id=allocation_envelope.payload["pool_allocation"]["allocation_id"],
        pool_allocation_operation_id=allocation_envelope.operation_id,
        source_epoch_transition_operation_id=source_epoch_id,
        reserve_operation_ids=[reserve_envelope.operation_id],
        unclaimed_operation_ids=[unclaimed.operation_id],
        expiry_operation_ids=[expiry.operation_id],
        source_operation_root=canonical_hash(sorted(source_operation_ids)),
        reserve_root=canonical_hash(sorted(reserve_records, key=lambda item: item["reserve_id"])),
        payment_root=canonical_hash([]),
        unclaimed_root=canonical_hash(sorted(unclaimed_records, key=lambda item: item["unclaimed_id"])),
        claim_root=canonical_hash([]),
        expiry_root=canonical_hash(sorted(expiry_records, key=lambda item: item["expiry_id"])),
        finalization_epoch=expiry.payload["expiry_epoch"],
    )
    finalized = build_development_reward_operation(final_request)
    result = app.finalize_block(
        block_height=8,
        block_hash=b"K" * 32,
        txs=[json.dumps(finalized.model_dump(mode="json")).encode("utf-8")],
    )
    assert result.code == "ok"
    assert app.ledger.wallet_q_atom_balance("unclaimed-contributor") == 0
    final_state = app.ledger.snapshot_settlement_state()
    assert len(final_state["development_reward_finalized_commitments"]) == 1
    finalized_id = final_state["development_reward_finalized_commitments"][0]["finalized_commitment_id"]
    assert finalized.payload["finalized_commitment_id"] == finalized_id

    retry = build_development_reward_operation(final_request.model_copy(update={"created_at": "2030-01-01T00:00:09Z"}))
    retry_result, retry_tx_results = app.finalize_block_with_results(
        block_height=9,
        block_hash=b"L" * 32,
        txs=[json.dumps(retry.model_dump(mode="json")).encode("utf-8")],
    )
    restored = AIDNABCIApplication(
        ledger_service=LedgerOperationService(),
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        state_store=store,
        strict_operation_coverage=True,
    )

    assert retry.operation_id != finalized.operation_id
    assert retry_result.code == "ok"
    assert retry_tx_results[0].code == "rejected"
    assert retry_tx_results[0].log == "DEVELOPMENT_REWARD_FINALIZED_COMMITMENT_DUPLICATE"
    assert restored.info().last_block_height == 9
    assert restored.info().last_block_app_hash == app.info().last_block_app_hash
    assert restored.ledger.development_reward_finalized_commitment(finalized_id) == (
        app.ledger.development_reward_finalized_commitment(finalized_id)
    )


def test_unclaimed_reward_rejects_same_block_dependencies():
    _, _, _, epoch_tx, calculation_envelope, allocation_envelope, reserve_envelope, unclaimed = _unclaimed_envelopes()
    ledger = LedgerOperationService()
    engine = ExecutionEngine(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        strict_operation_coverage=True,
    )

    result = engine.execute_block(
        block_height=1,
        block_hash=b"T" * 32,
        txs=[
            epoch_tx,
            json.dumps(calculation_envelope.model_dump(mode="json")).encode("utf-8"),
            json.dumps(allocation_envelope.model_dump(mode="json")).encode("utf-8"),
            json.dumps(reserve_envelope.model_dump(mode="json")).encode("utf-8"),
            json.dumps(unclaimed.model_dump(mode="json")).encode("utf-8"),
        ],
    )

    assert result.operations_executed == 2
    assert result.operations_rejected == 3
    assert result.execution_events[4].error == "DEVELOPMENT_REWARD_PAYMENT_CALCULATION_NOT_FINALIZED"
    assert ledger.snapshot_settlement_state()["development_reward_unclaimed_records"] == []
    assert ledger.wallet_q_atom_balance("unclaimed-contributor") == 0


def test_abci_unclaimed_reward_replay_and_snapshot_restore(tmp_path):
    (
        calculation,
        approval,
        commitment,
        epoch_tx,
        calculation_envelope,
        allocation_envelope,
        reserve_envelope,
        unclaimed,
    ) = _unclaimed_envelopes()
    store = ABCIStateStore(tmp_path / "abci", chunk_size=128)
    app = AIDNABCIApplication(
        ledger_service=LedgerOperationService(),
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        state_store=store,
        strict_operation_coverage=True,
    )
    for height, tx in (
        (1, epoch_tx),
        (2, json.dumps(calculation_envelope.model_dump(mode="json")).encode("utf-8")),
        (3, json.dumps(allocation_envelope.model_dump(mode="json")).encode("utf-8")),
        (4, json.dumps(reserve_envelope.model_dump(mode="json")).encode("utf-8")),
        (5, json.dumps(unclaimed.model_dump(mode="json")).encode("utf-8")),
    ):
        result = app.finalize_block(block_height=height, block_hash=bytes([height + 130]) * 32, txs=[tx])
        assert result.code == "ok"

    payload = unclaimed.payload
    retry = build_development_reward_operation(
        DevelopmentRewardOperationRequest(
            operation_type="DEVELOPMENT_REWARD_MARK_UNCLAIMED",
            created_at="2030-01-01T00:00:06Z",
            commitment=commitment,
            activation_approval=approval,
            calculation=calculation,
            calculation_operation_id=payload["calculation_operation_id"],
            pool_allocation_id=payload["pool_allocation_id"],
            pool_allocation_operation_id=allocation_envelope.operation_id,
            reserve_id=payload["reserve_id"],
            reserve_operation_id=reserve_envelope.operation_id,
            reward_id=payload["reward_id"],
            contributor_id=payload["contributor_id"],
            role=payload["role"],
            payment_hash=payload["payment_hash"],
            payment_stage=payload["payment_stage"],
            amount_q_atoms=payload["amount_q_atoms"],
        )
    )
    retry_result, retry_tx_results = app.finalize_block_with_results(
        block_height=6,
        block_hash=b"Z" * 32,
        txs=[json.dumps(retry.model_dump(mode="json")).encode("utf-8")],
    )
    restored = AIDNABCIApplication(
        ledger_service=LedgerOperationService(),
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        state_store=store,
        strict_operation_coverage=True,
    )

    unclaimed_id = app.ledger.snapshot_settlement_state()["development_reward_unclaimed_records"][0]["unclaimed_id"]
    assert retry.operation_id != unclaimed.operation_id
    assert retry_result.code == "ok"
    assert retry_tx_results[0].code == "rejected"
    assert retry_tx_results[0].log == "DEVELOPMENT_REWARD_UNCLAIMED_DUPLICATE"
    assert app.ledger.wallet_q_atom_balance("unclaimed-contributor") == 0
    assert restored.info().last_block_height == 6
    assert restored.info().last_block_app_hash == app.info().last_block_app_hash
    assert restored.ledger.development_reward_unclaimed(unclaimed_id) == app.ledger.development_reward_unclaimed(
        unclaimed_id
    )
    assert restored.ledger.snapshot_operations() == app.ledger.snapshot_operations()
    assert (
        restored.ledger.snapshot_settlement_state()["development_reward_unclaimed_records"]
        == (app.ledger.snapshot_settlement_state()["development_reward_unclaimed_records"])
    )


def test_builder_emits_signed_wallet_claim_envelope():
    _, _, _, _, _, _, _, _, claim, binding = _claim_envelopes()

    assert claim.operation_type == "DEVELOPMENT_REWARD_CLAIM"
    assert claim.payload["recipient_wallet"] == binding.wallet_address
    assert claim.payload["wallet_binding"]["binding_id"] == binding.binding_id
    assert claim.payload["reward_payment"]["state"] == "UNCLAIMED"
    assert claim.payload["reward_unclaimed"]["state"] == "UNCLAIMED"
    assert claim.payload["reward_unclaimed"]["unclaimed_id"] == claim.payload["unclaimed_id"]
    binding.verify_signature()
    assert strict_operation_coverage_error(claim.operation_type) is None


def test_strict_execution_claims_unclaimed_stage_with_signed_wallet_binding():
    (
        calculation,
        _,
        _,
        epoch_tx,
        calculation_envelope,
        allocation_envelope,
        reserve_envelope,
        unclaimed,
        claim,
        binding,
    ) = _claim_envelopes()
    ledger = LedgerOperationService()
    engine = ExecutionEngine(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        strict_operation_coverage=True,
    )

    for height, tx in (
        (1, epoch_tx),
        (2, json.dumps(calculation_envelope.model_dump(mode="json")).encode("utf-8")),
        (3, json.dumps(allocation_envelope.model_dump(mode="json")).encode("utf-8")),
        (4, json.dumps(reserve_envelope.model_dump(mode="json")).encode("utf-8")),
        (5, json.dumps(unclaimed.model_dump(mode="json")).encode("utf-8")),
    ):
        result = engine.execute_block(block_height=height, block_hash=bytes([height + 140]) * 32, txs=[tx])
        assert result.operations_executed == 1
        assert result.operations_rejected == 0

    result = engine.execute_block(
        block_height=6,
        block_hash=b"C" * 32,
        txs=[json.dumps(claim.model_dump(mode="json")).encode("utf-8")],
    )

    assert result.operations_executed == 1
    assert result.operations_rejected == 0
    assert result.execution_events[0].emitted_events == ["DevelopmentRewardClaimed"]
    assert ledger.wallet_q_atom_balance(binding.wallet_address) == calculation.payments[0].amount_q_atoms
    state = ledger.snapshot_settlement_state()
    assert len(state["development_reward_unclaimed_records"]) == 1
    assert len(state["development_reward_claim_records"]) == 1
    claim_record = ledger.development_reward_claim(state["development_reward_claim_records"][0]["claim_id"])
    assert claim_record is not None
    assert claim_record["state"] == "CLAIMED"
    assert claim_record["wallet_address"] == binding.wallet_address
    assert claim_record["wallet_binding_id"] == binding.binding_id
    assert claim_record["reserve_remaining_q_atoms"] == (
        reserve_envelope.payload["reward_reserve"]["reserved_q_atoms"] - calculation.payments[0].amount_q_atoms
    )
    assert state["development_reward_payment_records"] == []


def test_reward_claim_rejects_same_block_dependencies():
    _, _, _, epoch_tx, calculation_envelope, allocation_envelope, reserve_envelope, unclaimed, claim, _ = (
        _claim_envelopes()
    )
    ledger = LedgerOperationService()
    engine = ExecutionEngine(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        strict_operation_coverage=True,
    )

    result = engine.execute_block(
        block_height=1,
        block_hash=b"D" * 32,
        txs=[
            epoch_tx,
            json.dumps(calculation_envelope.model_dump(mode="json")).encode("utf-8"),
            json.dumps(allocation_envelope.model_dump(mode="json")).encode("utf-8"),
            json.dumps(reserve_envelope.model_dump(mode="json")).encode("utf-8"),
            json.dumps(unclaimed.model_dump(mode="json")).encode("utf-8"),
            json.dumps(claim.model_dump(mode="json")).encode("utf-8"),
        ],
    )

    assert result.operations_executed == 2
    assert result.operations_rejected == 4
    assert result.execution_events[5].error == "DEVELOPMENT_REWARD_CLAIM_CALCULATION_NOT_FINALIZED"
    assert ledger.snapshot_settlement_state()["development_reward_claim_records"] == []
    assert ledger.wallet_q_atom_balance("q1claimed") == 0


def test_reward_claim_rejects_after_claim_window():
    (
        calculation,
        _,
        _,
        epoch_tx,
        calculation_envelope,
        allocation_envelope,
        reserve_envelope,
        unclaimed,
        claim,
        binding,
    ) = _claim_envelopes()
    claim_payload = claim.payload
    expired_epoch = calculation.epoch + calculation.policy.claim_window_epochs + 1
    expired_epoch_tx = _epoch_transition(calculation, opening_epoch=expired_epoch)
    expired_epoch_id = LedgerOperationEnvelope.model_validate(json.loads(expired_epoch_tx)).operation_id
    expired_claim = build_development_reward_operation(
        DevelopmentRewardOperationRequest(
            operation_type="DEVELOPMENT_REWARD_CLAIM",
            created_at="2030-01-01T00:00:07Z",
            commitment=claim_payload["commitment"],
            activation_approval=claim_payload["activation_approval"],
            calculation=calculation,
            calculation_operation_id=claim_payload["calculation_operation_id"],
            pool_allocation_id=claim_payload["pool_allocation_id"],
            pool_allocation_operation_id=claim_payload["pool_allocation_operation_id"],
            reserve_id=claim_payload["reserve_id"],
            reserve_operation_id=claim_payload["reserve_operation_id"],
            unclaimed_id=claim_payload["unclaimed_id"],
            unclaimed_operation_id=claim_payload["unclaimed_operation_id"],
            source_epoch_transition_operation_id=expired_epoch_id,
            reward_id=claim_payload["reward_id"],
            contribution_id=claim_payload["contribution_id"],
            contributor_id=claim_payload["contributor_id"],
            recipient_wallet=binding.wallet_address,
            role=claim_payload["role"],
            payment_hash=claim_payload["payment_hash"],
            payment_stage=claim_payload["payment_stage"],
            amount_q_atoms=claim_payload["amount_q_atoms"],
            claim_epoch=expired_epoch,
            wallet_binding=binding,
        )
    )
    ledger = LedgerOperationService()
    engine = ExecutionEngine(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        strict_operation_coverage=True,
    )
    for height, tx in (
        (1, epoch_tx),
        (2, json.dumps(calculation_envelope.model_dump(mode="json")).encode("utf-8")),
        (3, json.dumps(allocation_envelope.model_dump(mode="json")).encode("utf-8")),
        (4, json.dumps(reserve_envelope.model_dump(mode="json")).encode("utf-8")),
        (5, json.dumps(unclaimed.model_dump(mode="json")).encode("utf-8")),
        (6, expired_epoch_tx),
    ):
        result = engine.execute_block(block_height=height, block_hash=bytes([height + 150]) * 32, txs=[tx])
        assert result.operations_executed == 1
        assert result.operations_rejected == 0

    result = engine.execute_block(
        block_height=7,
        block_hash=b"E" * 32,
        txs=[json.dumps(expired_claim.model_dump(mode="json")).encode("utf-8")],
    )
    assert result.operations_executed == 0
    assert result.operations_rejected == 1
    assert result.execution_events[0].error == "DEVELOPMENT_CLAIM_WINDOW_EXPIRED"
    assert ledger.snapshot_settlement_state()["development_reward_claim_records"] == []
    assert ledger.wallet_q_atom_balance(binding.wallet_address) == 0


def test_abci_reward_claim_replay_and_snapshot_restore(tmp_path):
    (
        calculation,
        approval,
        commitment,
        epoch_tx,
        calculation_envelope,
        allocation_envelope,
        reserve_envelope,
        unclaimed,
        claim,
        binding,
    ) = _claim_envelopes()
    store = ABCIStateStore(tmp_path / "abci", chunk_size=128)
    app = AIDNABCIApplication(
        ledger_service=LedgerOperationService(),
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        state_store=store,
        strict_operation_coverage=True,
    )
    for height, tx in (
        (1, epoch_tx),
        (2, json.dumps(calculation_envelope.model_dump(mode="json")).encode("utf-8")),
        (3, json.dumps(allocation_envelope.model_dump(mode="json")).encode("utf-8")),
        (4, json.dumps(reserve_envelope.model_dump(mode="json")).encode("utf-8")),
        (5, json.dumps(unclaimed.model_dump(mode="json")).encode("utf-8")),
        (6, json.dumps(claim.model_dump(mode="json")).encode("utf-8")),
    ):
        result = app.finalize_block(block_height=height, block_hash=bytes([height + 160]) * 32, txs=[tx])
        assert result.code == "ok"

    payload = claim.payload
    retry = build_development_reward_operation(
        DevelopmentRewardOperationRequest(
            operation_type="DEVELOPMENT_REWARD_CLAIM",
            created_at="2030-01-01T00:00:07Z",
            commitment=commitment,
            activation_approval=approval,
            calculation=calculation,
            calculation_operation_id=payload["calculation_operation_id"],
            pool_allocation_id=payload["pool_allocation_id"],
            pool_allocation_operation_id=allocation_envelope.operation_id,
            reserve_id=payload["reserve_id"],
            reserve_operation_id=reserve_envelope.operation_id,
            unclaimed_id=payload["unclaimed_id"],
            unclaimed_operation_id=unclaimed.operation_id,
            source_epoch_transition_operation_id=LedgerOperationEnvelope.model_validate(
                json.loads(epoch_tx)
            ).operation_id,
            reward_id=payload["reward_id"],
            contribution_id=payload["contribution_id"],
            contributor_id=payload["contributor_id"],
            recipient_wallet=payload["recipient_wallet"],
            role=payload["role"],
            payment_hash=payload["payment_hash"],
            payment_stage=payload["payment_stage"],
            amount_q_atoms=payload["amount_q_atoms"],
            claim_epoch=payload["claim_epoch"],
            wallet_binding=DevelopmentRewardWalletBindingProof.model_validate(payload["wallet_binding"]),
        )
    )
    retry_result, retry_tx_results = app.finalize_block_with_results(
        block_height=7,
        block_hash=b"F" * 32,
        txs=[json.dumps(retry.model_dump(mode="json")).encode("utf-8")],
    )
    restored = AIDNABCIApplication(
        ledger_service=LedgerOperationService(),
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        state_store=store,
        strict_operation_coverage=True,
    )

    state = app.ledger.snapshot_settlement_state()
    claim_id = state["development_reward_claim_records"][0]["claim_id"]
    assert retry.operation_id != claim.operation_id
    assert retry_result.code == "ok"
    assert retry_tx_results[0].code == "rejected"
    assert retry_tx_results[0].log == "DEVELOPMENT_REWARD_CLAIM_DUPLICATE"
    assert app.ledger.wallet_q_atom_balance(binding.wallet_address) == calculation.payments[0].amount_q_atoms
    assert restored.info().last_block_height == 7
    assert restored.info().last_block_app_hash == app.info().last_block_app_hash
    assert restored.ledger.development_reward_claim(claim_id) == app.ledger.development_reward_claim(claim_id)
    assert restored.ledger.snapshot_operations() == app.ledger.snapshot_operations()
    assert restored.ledger.wallet_q_atom_balance(binding.wallet_address) == calculation.payments[0].amount_q_atoms


def test_calculation_commit_is_consensus_evidence_only():
    calculation, approval, commitment = _fixture()
    envelope = build_development_reward_operation(
        DevelopmentRewardOperationRequest(
            operation_type="DEVELOPMENT_REWARD_CALCULATE",
            created_at="2030-01-01T00:00:00Z",
            commitment=commitment,
            activation_approval=approval,
            calculation=calculation,
        )
    )
    ledger = LedgerOperationService()
    engine = ExecutionEngine(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        strict_operation_coverage=True,
    )

    result = engine.execute_block(
        block_height=1,
        block_hash=b"C" * 32,
        txs=[json.dumps(envelope.model_dump(mode="json")).encode("utf-8")],
    )

    assert result.operations_executed == 1
    assert result.operations_rejected == 0
    assert result.execution_events[0].emitted_events == ["DevelopmentRewardCalculationCommitted"]
    assert ledger.list_operations()[0]["operation_type"] == "DEVELOPMENT_REWARD_CALCULATE"
    assert ledger.wallet_q_atom_balance("q1recipient") == 0


def test_pool_allocation_requires_finalized_sources_and_has_no_wallet_effect():
    calculation, approval, commitment = _allocation_fixture()
    calculation_envelope = build_development_reward_operation(
        DevelopmentRewardOperationRequest(
            operation_type="DEVELOPMENT_REWARD_CALCULATE",
            created_at="2030-01-01T00:00:01Z",
            commitment=commitment,
            activation_approval=approval,
            calculation=calculation,
        )
    )
    epoch_tx = _epoch_transition(calculation)
    epoch_operation_id = LedgerOperationEnvelope.model_validate(json.loads(epoch_tx)).operation_id
    calculation_operation_id = calculation_envelope.operation_id
    allocation_envelope = build_development_reward_operation(
        DevelopmentRewardOperationRequest(
            operation_type="DEVELOPMENT_POOL_ALLOCATE",
            created_at="2030-01-01T00:00:02Z",
            commitment=commitment,
            activation_approval=approval,
            calculation=calculation,
            amount_q_atoms=calculation.pool.base_allocation_q_atoms,
            calculation_operation_id=calculation_operation_id,
            source_epoch_transition_operation_id=epoch_operation_id,
            pool_budget_reference="epoch:20:GENERAL_DEVELOPMENT",
        )
    )
    ledger = LedgerOperationService()
    engine = ExecutionEngine(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        strict_operation_coverage=True,
    )

    first = engine.execute_block(block_height=1, block_hash=b"E" * 32, txs=[epoch_tx])
    second = engine.execute_block(
        block_height=2,
        block_hash=b"F" * 32,
        txs=[json.dumps(calculation_envelope.model_dump(mode="json")).encode("utf-8")],
    )
    third = engine.execute_block(
        block_height=3,
        block_hash=b"G" * 32,
        txs=[json.dumps(allocation_envelope.model_dump(mode="json")).encode("utf-8")],
    )

    assert first.operations_executed == 1
    assert second.operations_executed == 1
    assert third.operations_executed == 1
    assert third.execution_events[0].emitted_events == ["DevelopmentPoolAllocated"]
    allocation = ledger.development_pool_allocation(allocation_envelope.payload["pool_allocation"]["allocation_id"])
    assert allocation is not None
    assert allocation["remaining_q_atoms"] == calculation.pool.base_allocation_q_atoms
    assert ledger.wallet_q_atom_balance("q1recipient") == 0


def test_pool_allocation_rejects_same_block_or_wrong_budget_source():
    calculation, approval, commitment = _allocation_fixture()
    epoch_tx = _epoch_transition(calculation)
    epoch_operation_id = LedgerOperationEnvelope.model_validate(json.loads(epoch_tx)).operation_id
    calculation_envelope = build_development_reward_operation(
        DevelopmentRewardOperationRequest(
            operation_type="DEVELOPMENT_REWARD_CALCULATE",
            created_at="2030-01-01T00:00:01Z",
            commitment=commitment,
            activation_approval=approval,
            calculation=calculation,
        )
    )
    allocation_envelope = build_development_reward_operation(
        DevelopmentRewardOperationRequest(
            operation_type="DEVELOPMENT_POOL_ALLOCATE",
            created_at="2030-01-01T00:00:02Z",
            commitment=commitment,
            activation_approval=approval,
            calculation=calculation,
            amount_q_atoms=calculation.pool.base_allocation_q_atoms,
            calculation_operation_id=calculation_envelope.operation_id,
            source_epoch_transition_operation_id=epoch_operation_id,
            pool_budget_reference="epoch:20:GENERAL_DEVELOPMENT",
        )
    )
    ledger = LedgerOperationService()
    engine = ExecutionEngine(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        strict_operation_coverage=True,
    )
    same_block = engine.execute_block(
        block_height=1,
        block_hash=b"H" * 32,
        txs=[
            epoch_tx,
            json.dumps(calculation_envelope.model_dump(mode="json")).encode("utf-8"),
            json.dumps(allocation_envelope.model_dump(mode="json")).encode("utf-8"),
        ],
    )

    assert same_block.operations_executed == 2
    assert same_block.operations_rejected == 1
    assert "DEVELOPMENT_POOL_CALCULATION_NOT_FINALIZED" in (same_block.execution_events[2].error or "")
    assert ledger.development_pool_allocation(allocation_envelope.payload["pool_allocation"]["allocation_id"]) is None


def test_abci_pool_allocation_is_source_bound_and_replay_protected():
    calculation, approval, commitment, epoch_tx, calculation_envelope, allocation_envelope = _allocation_envelopes()
    ledger = LedgerOperationService()
    app = AIDNABCIApplication(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        strict_operation_coverage=True,
    )

    for height, tx in (
        (1, epoch_tx),
        (2, json.dumps(calculation_envelope.model_dump(mode="json")).encode("utf-8")),
        (3, json.dumps(allocation_envelope.model_dump(mode="json")).encode("utf-8")),
    ):
        result, tx_results = app.finalize_block_with_results(
            block_height=height,
            block_hash=bytes([height]) * 32,
            txs=[tx],
        )
        assert result.code == "ok"
        assert tx_results[0].code == "ok"

    retry = build_development_reward_operation(
        DevelopmentRewardOperationRequest(
            operation_type="DEVELOPMENT_POOL_ALLOCATE",
            created_at="2030-01-01T00:00:03Z",
            commitment=commitment,
            activation_approval=approval,
            calculation=calculation,
            amount_q_atoms=calculation.pool.base_allocation_q_atoms,
            calculation_operation_id=calculation_envelope.operation_id,
            source_epoch_transition_operation_id=LedgerOperationEnvelope.model_validate(
                json.loads(epoch_tx)
            ).operation_id,
            pool_budget_reference="epoch:20:GENERAL_DEVELOPMENT",
        )
    )
    retry_result, retry_tx_results = app.finalize_block_with_results(
        block_height=4,
        block_hash=b"I" * 32,
        txs=[json.dumps(retry.model_dump(mode="json")).encode("utf-8")],
    )

    assert retry_result.code == "ok"
    assert retry_tx_results[0].code == "rejected"
    assert retry_tx_results[0].log == "DEVELOPMENT_POOL_ALLOCATION_ALREADY_FINALIZED"
    allocation = ledger.development_pool_allocation(allocation_envelope.payload["pool_allocation"]["allocation_id"])
    assert allocation is not None
    assert allocation["allocated_q_atoms"] == calculation.pool.base_allocation_q_atoms
    assert ledger.wallet_q_atom_balance("q1recipient") == 0
    assert len(ledger.snapshot_operations()) == 3


def test_pool_allocation_survives_abci_snapshot_restore(tmp_path):
    calculation, _, _, epoch_tx, calculation_envelope, allocation_envelope = _allocation_envelopes()
    store = ABCIStateStore(tmp_path / "abci", chunk_size=128)
    app = AIDNABCIApplication(
        ledger_service=LedgerOperationService(),
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        state_store=store,
        strict_operation_coverage=True,
    )
    for height, tx in (
        (1, epoch_tx),
        (2, json.dumps(calculation_envelope.model_dump(mode="json")).encode("utf-8")),
        (3, json.dumps(allocation_envelope.model_dump(mode="json")).encode("utf-8")),
    ):
        result = app.finalize_block(
            block_height=height,
            block_hash=bytes([height + 10]) * 32,
            txs=[tx],
        )
        assert result.code == "ok"

    restored = AIDNABCIApplication(
        ledger_service=LedgerOperationService(),
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        state_store=store,
        strict_operation_coverage=True,
    )

    allocation_id = allocation_envelope.payload["pool_allocation"]["allocation_id"]
    assert restored.info().last_block_height == 3
    assert restored.ledger.development_pool_allocation(allocation_id) == (
        app.ledger.development_pool_allocation(allocation_id)
    )
    assert restored.ledger.snapshot_operations() == app.ledger.snapshot_operations()
    assert restored.ledger.wallet_q_atom_balance("q1recipient") == 0
    assert calculation.calculation_root in restored.ledger.snapshot_operations()[1]["evidence_references"]


def test_pool_allocation_rejects_budget_mismatch_after_sources_finalize():
    calculation, approval, commitment, epoch_tx, calculation_envelope, _ = _allocation_envelopes()
    allocation_envelope = build_development_reward_operation(
        DevelopmentRewardOperationRequest(
            operation_type="DEVELOPMENT_POOL_ALLOCATE",
            created_at="2030-01-01T00:00:02Z",
            commitment=commitment,
            activation_approval=approval,
            calculation=calculation,
            amount_q_atoms=calculation.pool.base_allocation_q_atoms + 1,
            calculation_operation_id=calculation_envelope.operation_id,
            source_epoch_transition_operation_id=LedgerOperationEnvelope.model_validate(
                json.loads(epoch_tx)
            ).operation_id,
            pool_budget_reference="epoch:20:GENERAL_DEVELOPMENT",
        )
    )
    ledger = LedgerOperationService()
    engine = ExecutionEngine(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        strict_operation_coverage=True,
    )
    engine.execute_block(block_height=1, block_hash=b"J" * 32, txs=[epoch_tx])
    engine.execute_block(
        block_height=2,
        block_hash=b"K" * 32,
        txs=[json.dumps(calculation_envelope.model_dump(mode="json")).encode("utf-8")],
    )
    result = engine.execute_block(
        block_height=3,
        block_hash=b"L" * 32,
        txs=[json.dumps(allocation_envelope.model_dump(mode="json")).encode("utf-8")],
    )

    assert result.operations_executed == 0
    assert result.operations_rejected == 1
    assert result.execution_events[0].error == "DEVELOPMENT_POOL_ALLOCATION_BUDGET_MISMATCH"
    assert ledger.development_pool_allocation(allocation_envelope.payload["pool_allocation"]["allocation_id"]) is None


def test_pool_allocation_requires_pool_allocation_activation_scope():
    calculation, approval, commitment = _fixture()
    epoch_tx = _epoch_transition(calculation)
    epoch_operation_id = LedgerOperationEnvelope.model_validate(json.loads(epoch_tx)).operation_id
    calculation_envelope = build_development_reward_operation(
        DevelopmentRewardOperationRequest(
            operation_type="DEVELOPMENT_REWARD_CALCULATE",
            created_at="2030-01-01T00:00:01Z",
            commitment=commitment,
            activation_approval=approval,
            calculation=calculation,
        )
    )
    allocation_envelope = build_development_reward_operation(
        DevelopmentRewardOperationRequest(
            operation_type="DEVELOPMENT_POOL_ALLOCATE",
            created_at="2030-01-01T00:00:02Z",
            commitment=commitment,
            activation_approval=approval,
            calculation=calculation,
            amount_q_atoms=calculation.pool.base_allocation_q_atoms,
            calculation_operation_id=calculation_envelope.operation_id,
            source_epoch_transition_operation_id=epoch_operation_id,
            pool_budget_reference="epoch:20:GENERAL_DEVELOPMENT",
        )
    )
    ledger = LedgerOperationService()
    engine = ExecutionEngine(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        strict_operation_coverage=True,
    )
    engine.execute_block(block_height=1, block_hash=b"M" * 32, txs=[epoch_tx])
    engine.execute_block(
        block_height=2,
        block_hash=b"N" * 32,
        txs=[json.dumps(calculation_envelope.model_dump(mode="json")).encode("utf-8")],
    )
    result = engine.execute_block(
        block_height=3,
        block_hash=b"O" * 32,
        txs=[json.dumps(allocation_envelope.model_dump(mode="json")).encode("utf-8")],
    )

    assert result.operations_executed == 0
    assert result.execution_events[0].error == "DEVELOPMENT_REWARD_OPERATION_NOT_AUTHORIZED"


def test_reward_reserve_requires_finalized_sources_and_has_no_wallet_effect():
    calculation, _, _, epoch_tx, calculation_envelope, allocation_envelope, reserve_envelope = _reserve_envelopes()
    ledger = LedgerOperationService()
    engine = ExecutionEngine(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        strict_operation_coverage=True,
    )

    first = engine.execute_block(block_height=1, block_hash=b"P" * 32, txs=[epoch_tx])
    second = engine.execute_block(
        block_height=2,
        block_hash=b"Q" * 32,
        txs=[json.dumps(calculation_envelope.model_dump(mode="json")).encode("utf-8")],
    )
    third = engine.execute_block(
        block_height=3,
        block_hash=b"R" * 32,
        txs=[json.dumps(allocation_envelope.model_dump(mode="json")).encode("utf-8")],
    )
    fourth = engine.execute_block(
        block_height=4,
        block_hash=b"S" * 32,
        txs=[json.dumps(reserve_envelope.model_dump(mode="json")).encode("utf-8")],
    )

    assert first.operations_executed == 1
    assert second.operations_executed == 1
    assert third.operations_executed == 1
    assert fourth.operations_executed == 1
    assert fourth.execution_events[0].emitted_events == ["DevelopmentRewardReserved"]
    reserve = ledger.development_reward_reserve(reserve_envelope.payload["reward_reserve"]["reserve_id"])
    assert reserve is not None
    assert reserve["reserved_q_atoms"] == calculation.schedules[0].gross_reward_q_atoms
    assert reserve["remaining_q_atoms"] == reserve["reserved_q_atoms"]
    assert ledger.wallet_q_atom_balance("q1recipient") == 0


def test_reward_reserve_rejects_same_block_dependency():
    _, _, _, epoch_tx, calculation_envelope, allocation_envelope, reserve_envelope = _reserve_envelopes()
    ledger = LedgerOperationService()
    engine = ExecutionEngine(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        strict_operation_coverage=True,
    )
    result = engine.execute_block(
        block_height=1,
        block_hash=b"T" * 32,
        txs=[
            epoch_tx,
            json.dumps(calculation_envelope.model_dump(mode="json")).encode("utf-8"),
            json.dumps(allocation_envelope.model_dump(mode="json")).encode("utf-8"),
            json.dumps(reserve_envelope.model_dump(mode="json")).encode("utf-8"),
        ],
    )

    assert result.operations_executed == 2
    assert result.operations_rejected == 2
    assert result.execution_events[3].error == "DEVELOPMENT_REWARD_RESERVE_CALCULATION_NOT_FINALIZED"
    assert ledger.development_reward_reserve(reserve_envelope.payload["reward_reserve"]["reserve_id"]) is None


def test_abci_reward_reserve_replay_and_snapshot_restore(tmp_path):
    calculation, approval, commitment, epoch_tx, calculation_envelope, allocation_envelope, reserve_envelope = (
        _reserve_envelopes()
    )
    store = ABCIStateStore(tmp_path / "abci", chunk_size=128)
    app = AIDNABCIApplication(
        ledger_service=LedgerOperationService(),
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        state_store=store,
        strict_operation_coverage=True,
    )
    for height, tx in (
        (1, epoch_tx),
        (2, json.dumps(calculation_envelope.model_dump(mode="json")).encode("utf-8")),
        (3, json.dumps(allocation_envelope.model_dump(mode="json")).encode("utf-8")),
        (4, json.dumps(reserve_envelope.model_dump(mode="json")).encode("utf-8")),
    ):
        result = app.finalize_block(
            block_height=height,
            block_hash=bytes([height + 20]) * 32,
            txs=[tx],
        )
        assert result.code == "ok"

    schedule = calculation.schedules[0]
    retry = build_development_reward_operation(
        DevelopmentRewardOperationRequest(
            operation_type="DEVELOPMENT_REWARD_RESERVE",
            created_at="2030-01-01T00:00:04Z",
            commitment=commitment,
            activation_approval=approval,
            calculation=calculation,
            amount_q_atoms=schedule.gross_reward_q_atoms,
            calculation_operation_id=calculation_envelope.operation_id,
            pool_allocation_id=allocation_envelope.payload["pool_allocation"]["allocation_id"],
            pool_allocation_operation_id=allocation_envelope.operation_id,
            reward_id=schedule.reward_id,
        )
    )
    retry_result, retry_tx_results = app.finalize_block_with_results(
        block_height=5,
        block_hash=b"U" * 32,
        txs=[json.dumps(retry.model_dump(mode="json")).encode("utf-8")],
    )
    restored = AIDNABCIApplication(
        ledger_service=LedgerOperationService(),
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        state_store=store,
        strict_operation_coverage=True,
    )

    reserve_id = reserve_envelope.payload["reward_reserve"]["reserve_id"]
    assert retry_result.code == "ok"
    assert retry_tx_results[0].code == "rejected"
    assert retry_tx_results[0].log == "DEVELOPMENT_REWARD_RESERVE_ALREADY_FINALIZED"
    assert restored.info().last_block_height == 5
    assert restored.info().last_block_app_hash == app.info().last_block_app_hash
    assert restored.ledger.development_reward_reserve(reserve_id) == (app.ledger.development_reward_reserve(reserve_id))
    assert restored.ledger.snapshot_operations() == app.ledger.snapshot_operations()
    assert restored.ledger.wallet_q_atom_balance("q1recipient") == 0


def test_abci_calculation_commit_matches_deterministic_execution():
    calculation, approval, commitment = _fixture()
    envelope = build_development_reward_operation(
        DevelopmentRewardOperationRequest(
            operation_type="DEVELOPMENT_REWARD_CALCULATE",
            created_at="2030-01-01T00:00:00Z",
            commitment=commitment,
            activation_approval=approval,
            calculation=calculation,
        )
    )
    ledger = LedgerOperationService()
    app = AIDNABCIApplication(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        strict_operation_coverage=True,
    )

    result, tx_results = app.finalize_block_with_results(
        block_height=1,
        block_hash=b"A" * 32,
        txs=[json.dumps(envelope.model_dump(mode="json")).encode("utf-8")],
    )

    assert result.code == "ok"
    assert tx_results[0].code == "ok"
    assert ledger.snapshot_operations()[0]["operation_type"] == "DEVELOPMENT_REWARD_CALCULATE"
    assert ledger.wallet_q_atom_balance("q1recipient") == 0


def test_calculation_commit_rejects_validly_rehashed_nested_tampering():
    calculation, approval, commitment = _fixture()
    envelope = build_development_reward_operation(
        DevelopmentRewardOperationRequest(
            operation_type="DEVELOPMENT_REWARD_CALCULATE",
            created_at="2030-01-01T00:00:00Z",
            commitment=commitment,
            activation_approval=approval,
            calculation=calculation,
        )
    )
    tampered_payload = envelope.payload.copy()
    tampered_calculation = tampered_payload["calculation"].copy()
    tampered_calculation["accepted_gross_reward_q_atoms"] += 1
    tampered_payload["calculation"] = tampered_calculation
    from aidn_hypervisor.reward.development_distribution import canonical_hash

    unsigned_payload = tampered_payload.copy()
    unsigned_payload.pop("payload_hash", None)
    tampered_payload["payload_hash"] = canonical_hash(unsigned_payload)
    tampered = envelope.model_copy(update={"payload": tampered_payload})
    ledger = LedgerOperationService()

    with pytest.raises(ValueError, match="DEVELOPMENT_REWARD_CALCULATION_ROOT_INVALID"):
        ledger.validate_consensus_development_reward_calculate(tampered)


def test_abci_calculation_commit_is_replay_protected():
    calculation, approval, commitment = _fixture()
    request = DevelopmentRewardOperationRequest(
        operation_type="DEVELOPMENT_REWARD_CALCULATE",
        created_at="2030-01-01T00:00:00Z",
        commitment=commitment,
        activation_approval=approval,
        calculation=calculation,
    )
    first = build_development_reward_operation(request)
    retry = build_development_reward_operation(request.model_copy(update={"created_at": "2030-01-01T00:00:01Z"}))
    ledger = LedgerOperationService()
    app = AIDNABCIApplication(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        strict_operation_coverage=True,
    )
    first_result = app.finalize_block(
        block_height=1,
        block_hash=b"R" * 32,
        txs=[json.dumps(first.model_dump(mode="json")).encode("utf-8")],
    )
    second_result, retry_results = app.finalize_block_with_results(
        block_height=2,
        block_hash=b"S" * 32,
        txs=[json.dumps(retry.model_dump(mode="json")).encode("utf-8")],
    )

    assert first_result.code == "ok"
    assert second_result.code == "ok"
    assert retry_results[0].code == "rejected"
    assert retry_results[0].log == "DEVELOPMENT_REWARD_CALCULATION_ALREADY_FINALIZED"
    assert len(ledger.snapshot_operations()) == 1


def test_calculation_commit_survives_abci_snapshot_restore(tmp_path):
    calculation, approval, commitment = _fixture()
    envelope = build_development_reward_operation(
        DevelopmentRewardOperationRequest(
            operation_type="DEVELOPMENT_REWARD_CALCULATE",
            created_at="2030-01-01T00:00:00Z",
            commitment=commitment,
            activation_approval=approval,
            calculation=calculation,
        )
    )
    store = ABCIStateStore(tmp_path / "abci", chunk_size=128)
    app = AIDNABCIApplication(
        ledger_service=LedgerOperationService(),
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        state_store=store,
        strict_operation_coverage=True,
    )
    result = app.finalize_block(
        block_height=1,
        block_hash=b"Z" * 32,
        txs=[json.dumps(envelope.model_dump(mode="json")).encode("utf-8")],
    )
    restored = AIDNABCIApplication(
        ledger_service=LedgerOperationService(),
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        state_store=store,
        strict_operation_coverage=True,
    )

    assert result.code == "ok"
    assert restored.info().last_block_height == 1
    assert restored.info().last_block_app_hash == app.info().last_block_app_hash
    assert restored.ledger.snapshot_operations()[0]["payload"]["calculation_root"] == calculation.calculation_root


def test_builder_requires_signed_activation_and_rejects_mismatched_evidence():
    calculation = run_launch_simulation_matrix().scenarios[0].calculation
    simulation_commitment = build_development_reward_commitment(calculation)
    with pytest.raises(ValueError, match="DEVELOPMENT_OPERATION_ACTIVATION_REQUIRED"):
        build_development_reward_operation(
            DevelopmentRewardOperationRequest(
                operation_type="DEVELOPMENT_REWARD_CALCULATE",
                created_at="2030-01-01T00:00:00Z",
                commitment=simulation_commitment,
                calculation=calculation,
            )
        )

    _, approval, commitment = _fixture()
    tampered_approval = approval.model_copy(
        update={
            "approvals": [
                approval.approvals[0].model_copy(update={"approval_note": "tampered"}),
                approval.approvals[1],
            ]
        }
    )
    with pytest.raises(ValueError, match="DEVELOPMENT_OPERATION_ACTIVATION_INVALID"):
        build_development_reward_operation(
            DevelopmentRewardOperationRequest(
                operation_type="DEVELOPMENT_REWARD_CALCULATE",
                created_at="2030-01-01T00:00:00Z",
                commitment=commitment,
                activation_approval=tampered_approval,
                calculation=calculation,
            )
        )


def test_operation_request_enforces_payment_fields_and_stage():
    calculation, approval, commitment, _, _, allocation, reserve, _ = _payment_envelopes()
    with pytest.raises(ValueError, match="DEVELOPMENT_OPERATION_WALLET_REQUIRED"):
        DevelopmentRewardOperationRequest(
            operation_type="DEVELOPMENT_REWARD_PAY_IMMEDIATE",
            created_at="2030-01-01T00:00:00Z",
            commitment=commitment,
            activation_approval=approval,
            calculation=calculation,
            calculation_operation_id="calculation-operation",
            pool_allocation_id=allocation.payload["pool_allocation"]["allocation_id"],
            pool_allocation_operation_id=allocation.operation_id,
            reserve_id=reserve.payload["reward_reserve"]["reserve_id"],
            reserve_operation_id=reserve.operation_id,
            reward_id="reward-1",
            contributor_id="contributor-1",
            payment_stage="IMMEDIATE",
            amount_q_atoms=1,
        )

    with pytest.raises(ValueError, match="DEVELOPMENT_OPERATION_PAYMENT_STAGE_INVALID"):
        DevelopmentRewardOperationRequest(
            operation_type="DEVELOPMENT_REWARD_PAY_MATURITY",
            created_at="2030-01-01T00:00:00Z",
            commitment=commitment,
            activation_approval=approval,
            calculation=calculation,
            reward_id="reward-1",
            contributor_id="contributor-1",
            recipient_wallet="q1recipient",
            payment_stage="IMMEDIATE",
            amount_q_atoms=1,
        )


def test_consensus_applies_pool_carryover_and_bounty_lifecycle():
    from aidn_hypervisor.reward.development_bounty import (
        build_development_bounty,
        build_development_bounty_expiry,
        build_development_bounty_release,
        build_development_bounty_reservation,
    )
    from aidn_hypervisor.reward.development_carryover import build_development_pool_carryover

    calculation = run_launch_simulation_matrix().scenarios[0].calculation
    approval = _approval(
        calculation.policy,
        authorized_operation_types=[
            "DEVELOPMENT_REWARD_CALCULATE",
            "DEVELOPMENT_POOL_ALLOCATE",
            "DEVELOPMENT_POOL_CARRYOVER",
            "DEVELOPMENT_BOUNTY_CREATE",
            "DEVELOPMENT_BOUNTY_RESERVE",
            "DEVELOPMENT_BOUNTY_RELEASE",
            "DEVELOPMENT_BOUNTY_EXPIRE",
        ],
        economic_effect_profile="DEVELOPMENT_RESERVES",
    )
    commitment = build_development_reward_commitment(
        calculation,
        activation_approval=approval,
        current_epoch=20,
    )
    epoch_tx = _epoch_transition(calculation)
    epoch_operation_id = LedgerOperationEnvelope.model_validate(json.loads(epoch_tx)).operation_id
    calculation_envelope = build_development_reward_operation(
        DevelopmentRewardOperationRequest(
            operation_type="DEVELOPMENT_REWARD_CALCULATE",
            created_at="2030-01-01T00:00:01Z",
            commitment=commitment,
            activation_approval=approval,
            calculation=calculation,
        )
    )
    allocation_envelope = build_development_reward_operation(
        DevelopmentRewardOperationRequest(
            operation_type="DEVELOPMENT_POOL_ALLOCATE",
            created_at="2030-01-01T00:00:02Z",
            commitment=commitment,
            activation_approval=approval,
            calculation=calculation,
            amount_q_atoms=calculation.pool.base_allocation_q_atoms,
            calculation_operation_id=calculation_envelope.operation_id,
            source_epoch_transition_operation_id=epoch_operation_id,
            pool_budget_reference="epoch:20:GENERAL_DEVELOPMENT",
        )
    )
    allocation_id = allocation_envelope.payload["pool_allocation"]["allocation_id"]
    carryover = build_development_pool_carryover(
        operation_id="carryover-record",
        source_pool_id="GENERAL_DEVELOPMENT",
        target_pool_id="GENERAL_DEVELOPMENT",
        source_epoch=20,
        target_epoch=21,
        source_pool_reference="epoch:20:GENERAL_DEVELOPMENT",
        target_pool_reference="epoch:21:GENERAL_DEVELOPMENT",
        source_pool_q_atoms=100,
        committed_q_atoms=20,
        uncommitted_q_atoms=80,
        carryover_limit_q_atoms=80,
        carried_q_atoms=80,
        returned_to_emission_reserve_q_atoms=0,
    )
    carryover_envelope = build_development_reward_operation(
        DevelopmentRewardOperationRequest(
            operation_type="DEVELOPMENT_POOL_CARRYOVER",
            created_at="2030-01-01T00:00:03Z",
            commitment=commitment,
            activation_approval=approval,
            target_epoch=21,
            amount_q_atoms=80,
            source_epoch_transition_operation_id=epoch_operation_id,
            pool_carryover=carryover,
        )
    )

    def bounty(name: str):
        return build_development_bounty(
            create_operation_id=f"{name}-create",
            created_epoch=20,
            title=name,
            acceptance_criteria_hash=f"sha256:{name}-criteria",
            eligible_repository_ids=("repo:aidn",),
            contribution_class="CODE",
            minimum_reward_q_atoms=10,
            maximum_reward_q_atoms=20,
            reserved_budget_q_atoms=20,
            priority_factor_millionths=1_000_000,
            reviewer_policy="MAINTAINER",
            opens_at_epoch=20,
            expires_at_epoch=25,
        )

    release_bounty = bounty("bounty-release")
    expiry_bounty = bounty("bounty-expiry")

    def create_envelope(item, created_at: str):
        return build_development_reward_operation(
            DevelopmentRewardOperationRequest(
                operation_type="DEVELOPMENT_BOUNTY_CREATE",
                created_at=created_at,
                commitment=commitment,
                activation_approval=approval,
                bounty_id=item.bounty_id,
                bounty_hash=item.bounty_hash,
                bounty=item,
            )
        )

    release_create = create_envelope(release_bounty, "2030-01-01T00:00:04Z")
    expiry_create = create_envelope(expiry_bounty, "2030-01-01T00:00:05Z")

    def reservation(item, operation_id: str):
        return build_development_bounty_reservation(
            bounty_id=item.bounty_id,
            operation_id=operation_id,
            source_pool_id="GENERAL_DEVELOPMENT",
            source_pool_reference=allocation_id,
            reservation_epoch=20,
            amount_q_atoms=10,
        )

    release_reservation = reservation(release_bounty, "release-reservation")
    expiry_reservation = reservation(expiry_bounty, "expiry-reservation")
    release_reserve = build_development_reward_operation(
        DevelopmentRewardOperationRequest(
            operation_type="DEVELOPMENT_BOUNTY_RESERVE",
            created_at="2030-01-01T00:00:06Z",
            commitment=commitment,
            activation_approval=approval,
            amount_q_atoms=10,
            bounty_id=release_bounty.bounty_id,
            bounty_reservation=release_reservation,
            pool_allocation_id=allocation_id,
            pool_allocation_operation_id=allocation_envelope.operation_id,
        )
    )
    expiry_reserve = build_development_reward_operation(
        DevelopmentRewardOperationRequest(
            operation_type="DEVELOPMENT_BOUNTY_RESERVE",
            created_at="2030-01-01T00:00:07Z",
            commitment=commitment,
            activation_approval=approval,
            amount_q_atoms=10,
            bounty_id=expiry_bounty.bounty_id,
            bounty_reservation=expiry_reservation,
            pool_allocation_id=allocation_id,
            pool_allocation_operation_id=allocation_envelope.operation_id,
        )
    )
    release = build_development_bounty_release(
        bounty=release_bounty,
        reservation=release_reservation,
        operation_id="release-event",
        contribution_id="contribution-release",
        release_epoch=20,
        released_q_atoms=10,
    )
    release_envelope = build_development_reward_operation(
        DevelopmentRewardOperationRequest(
            operation_type="DEVELOPMENT_BOUNTY_RELEASE",
            created_at="2030-01-01T00:00:08Z",
            commitment=commitment,
            activation_approval=approval,
            amount_q_atoms=10,
            bounty_id=release_bounty.bounty_id,
            bounty_release=release,
        )
    )
    expiry = build_development_bounty_expiry(
        bounty=expiry_bounty,
        reservations=(expiry_reservation,),
        operation_id="expiry-event",
        expiry_epoch=26,
    )
    expiry_envelope = build_development_reward_operation(
        DevelopmentRewardOperationRequest(
            operation_type="DEVELOPMENT_BOUNTY_EXPIRE",
            created_at="2030-01-01T00:00:09Z",
            commitment=commitment,
            activation_approval=approval,
            amount_q_atoms=10,
            bounty_id=expiry_bounty.bounty_id,
            bounty_expiry=expiry,
        )
    )

    ledger = LedgerOperationService()
    engine = ExecutionEngine(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        strict_operation_coverage=True,
    )
    envelopes = [
        calculation_envelope,
        allocation_envelope,
        carryover_envelope,
        release_create,
        expiry_create,
        release_reserve,
        expiry_reserve,
        release_envelope,
        expiry_envelope,
    ]
    result = engine.execute_block(
        block_height=1,
        block_hash=b"B" * 32,
        txs=[epoch_tx],
    )
    assert result.operations_executed == 1
    for height, envelope in enumerate(envelopes, start=2):
        result = engine.execute_block(
            block_height=height,
            block_hash=bytes([height]) * 32,
            txs=[json.dumps(envelope.model_dump(mode="json")).encode("utf-8")],
        )
        assert result.operations_executed == 1

    assert ledger.development_pool_carryover(carryover.carryover_id)["target_epoch"] == 21
    assert ledger.development_bounty_state(release_bounty.bounty_id)["state"] == "RELEASED"
    assert ledger.development_bounty_state(expiry_bounty.bounty_id)["state"] == "EXPIRED"


def test_consensus_applies_reward_cancellation_and_correction():
    from aidn_hypervisor.reward.development_adjustments import build_development_reward_state_snapshot
    from aidn_hypervisor.reward.development_cancellation import build_development_reward_cancellation
    from aidn_hypervisor.reward.development_correction import build_development_reward_correction

    calculation = run_launch_simulation_matrix().scenarios[0].calculation
    approval = _approval(
        calculation.policy,
        authorized_operation_types=[
            "DEVELOPMENT_REWARD_CALCULATE",
            "DEVELOPMENT_REWARD_CANCEL_UNVESTED",
            "DEVELOPMENT_REWARD_CORRECT",
        ],
        economic_effect_profile="DEVELOPMENT_RESERVES",
    )
    commitment = build_development_reward_commitment(
        calculation,
        activation_approval=approval,
        current_epoch=20,
    )
    schedule = calculation.schedules[0]
    source = build_development_reward_state_snapshot(
        schedule=schedule,
        source_commitment_id=commitment.commitment_id,
        source_record_hashes=("sha256:reserve", "sha256:payment"),
        paid_q_atoms=schedule.immediate_amount_q_atoms,
        unpaid_immediate_q_atoms=0,
        unpaid_maturity_stage_one_q_atoms=schedule.maturity_stage_one_amount_q_atoms,
        unpaid_maturity_stage_two_q_atoms=schedule.maturity_stage_two_amount_q_atoms,
        unclaimed_q_atoms=0,
    )
    cancellation = build_development_reward_cancellation(
        source=source,
        cancellation_operation_id="cancel-event",
        cancellation_epoch=20,
        reason="ORDINARY_DEFECT",
        cancelled_unpaid_maturity_stage_one_q_atoms=1,
    )
    correction = build_development_reward_correction(
        source=source,
        correction_operation_id="correction-event",
        correction_epoch=20,
        reason="ARITHMETIC_ERROR",
        authorization_reference="governance:correction",
        delta_unpaid_maturity_stage_two_q_atoms=-1,
    )
    cancellation_envelope = build_development_reward_operation(
        DevelopmentRewardOperationRequest(
            operation_type="DEVELOPMENT_REWARD_CANCEL_UNVESTED",
            created_at="2030-01-01T00:00:01Z",
            commitment=commitment,
            activation_approval=approval,
            reward_id=source.reward_id,
            amount_q_atoms=cancellation.cancelled_q_atoms,
            reward_state_snapshot=source,
            reward_cancellation=cancellation,
        )
    )
    correction_envelope = build_development_reward_operation(
        DevelopmentRewardOperationRequest(
            operation_type="DEVELOPMENT_REWARD_CORRECT",
            created_at="2030-01-01T00:00:02Z",
            commitment=commitment,
            activation_approval=approval,
            reward_id=source.reward_id,
            correction_id=correction.correction_id,
            correction_delta_q_atoms=correction.correction_delta_q_atoms,
            reward_state_snapshot=source,
            reward_correction=correction,
        )
    )
    calculation_envelope = build_development_reward_operation(
        DevelopmentRewardOperationRequest(
            operation_type="DEVELOPMENT_REWARD_CALCULATE",
            created_at="2030-01-01T00:00:03Z",
            commitment=commitment,
            activation_approval=approval,
            calculation=calculation,
        )
    )
    ledger = LedgerOperationService()
    engine = ExecutionEngine(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        strict_operation_coverage=True,
    )
    for height, envelope in enumerate(
        [calculation_envelope, cancellation_envelope, correction_envelope],
        start=1,
    ):
        result = engine.execute_block(
            block_height=height,
            block_hash=bytes([height + 20]) * 32,
            txs=[json.dumps(envelope.model_dump(mode="json")).encode("utf-8")],
        )
        assert result.operations_executed == 1

    state = ledger.snapshot_settlement_state()
    assert state["development_reward_cancellations"][0]["cancelled_q_atoms"] == 1
    assert state["development_reward_corrections"][0]["correction_delta_q_atoms"] == -1
    assert state["development_reward_adjustment_snapshots"][0]["snapshot_id"] == source.snapshot_id
