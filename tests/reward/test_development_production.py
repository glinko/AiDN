from __future__ import annotations

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aidn_hypervisor.reward.development_activation import (
    DevelopmentRewardApprovalSignature,
    DevelopmentRewardAuthority,
    activation_authorization_payload,
    build_development_reward_activation_approval,
    development_reward_policy_hash,
)
from aidn_hypervisor.reward.development_commitments import build_development_reward_commitment
from aidn_hypervisor.reward.development_contribution_service import DevelopmentRewardOperationPlan
from aidn_hypervisor.reward.development_distribution import DevelopmentRewardPolicy, canonical_hash
from aidn_hypervisor.reward.development_operations import (
    DevelopmentRewardOperationRequest,
    build_development_reward_operation,
)
from aidn_hypervisor.reward.development_production import (
    build_development_reward_production_batch,
    build_development_reward_production_profile,
)
from aidn_hypervisor.reward.development_scenarios import run_launch_simulation_matrix

_OPERATIONS = [
    "DEVELOPMENT_REWARD_CALCULATE",
    "DEVELOPMENT_POOL_ALLOCATE",
    "DEVELOPMENT_REWARD_RESERVE",
    "DEVELOPMENT_REWARD_PAY_IMMEDIATE",
    "DEVELOPMENT_REWARD_MARK_UNCLAIMED",
]


def _approval(policy: DevelopmentRewardPolicy):
    entries = []
    for authority_id, seed in (("governance-a", 41), ("governance-b", 42)):
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
        effective_epoch=0,
        eligible_authorities=authorities,
        quorum_threshold=2,
        approvals=[],
        authorized_operation_types=_OPERATIONS,
        economic_effect_profile="DEVELOPMENT_PAYMENTS",
    )
    approvals = [
        DevelopmentRewardApprovalSignature(
            authority_id=authority_id,
            signature="ed25519:"
            + private_key.sign(
                activation_authorization_payload(
                    activation_id=unsigned.activation_id,
                    policy_hash=policy_hash,
                    effective_epoch=0,
                    eligible_authorities=authorities,
                    quorum_threshold=2,
                    authority_id=authority_id,
                    authorized_operation_types=_OPERATIONS,
                    economic_effect_profile="DEVELOPMENT_PAYMENTS",
                )
            ).hex(),
        )
        for authority_id, private_key, _authority in entries
    ]
    return build_development_reward_activation_approval(
        policy_hash=policy_hash,
        effective_epoch=0,
        eligible_authorities=authorities,
        quorum_threshold=2,
        approvals=approvals,
        authorized_operation_types=_OPERATIONS,
        economic_effect_profile="DEVELOPMENT_PAYMENTS",
    )


def _plan():
    calculation = run_launch_simulation_matrix().scenarios[0].calculation
    approval = _approval(calculation.policy)
    commitment = build_development_reward_commitment(
        calculation,
        activation_approval=approval,
        current_epoch=calculation.epoch,
    )
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
            source_epoch_transition_operation_id="epoch-transition-20",
            pool_budget_reference="epoch:20:GENERAL_DEVELOPMENT",
        )
    )
    allocation_id = allocation_envelope.payload["pool_allocation"]["allocation_id"]
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
            pool_allocation_id=allocation_id,
            pool_allocation_operation_id=allocation_envelope.operation_id,
            reward_id=schedule.reward_id,
        )
    )
    payment = next(item for item in calculation.payments if item.state == "PAYABLE" and item.amount_q_atoms > 0)
    payment_envelope = build_development_reward_operation(
        DevelopmentRewardOperationRequest(
            operation_type="DEVELOPMENT_REWARD_PAY_IMMEDIATE",
            created_at="2030-01-01T00:00:04Z",
            commitment=commitment,
            activation_approval=approval,
            calculation=calculation,
            amount_q_atoms=payment.amount_q_atoms,
            calculation_operation_id=calculation_envelope.operation_id,
            pool_allocation_id=allocation_id,
            pool_allocation_operation_id=allocation_envelope.operation_id,
            reserve_id=reserve_envelope.payload["reward_reserve"]["reserve_id"],
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
    envelopes = [calculation_envelope, allocation_envelope, reserve_envelope, payment_envelope]
    plan_payload = {
        "plan_version": "aidn.eco-0007-contribution-plan.v1",
        "mode": "CONSENSUS_GATED",
        "epoch": calculation.epoch,
        "commitment_hash": commitment.commitment_hash,
        "operation_ids": [item.operation_id for item in envelopes],
    }
    return (
        calculation,
        approval,
        DevelopmentRewardOperationPlan(
            epoch=calculation.epoch,
            commitment=commitment,
            envelopes=envelopes,
            plan_hash=canonical_hash(plan_payload),
        ),
    )


def test_production_profile_binds_network_and_activation():
    calculation, approval, plan = _plan()
    profile = build_development_reward_production_profile(
        network_id="aidn-localnet-1",
        chain_id="chain-test-1",
        effective_epoch=0,
        activation_approval=approval,
        policy=calculation.policy,
        max_batch_q_atoms=1_000_000_000,
        max_contributions=1,
        max_operations=8,
    )

    assert profile.verify_integrity()
    assert profile.activation_id == approval.activation_id
    assert profile.profile_id.startswith("sha256:")

    batch = build_development_reward_production_batch(
        profile=profile,
        activation_approval=approval,
        plan=plan,
        source_epoch_transition_operation_id="epoch-transition-20",
        pool_budget_reference="epoch:20:GENERAL_DEVELOPMENT",
    )

    assert batch.verify_integrity()
    assert batch.mode == "PRODUCTION_CONSENSUS_PLAN"
    assert batch.payout_operation_count == 1
    assert batch.accepted_reward_q_atoms > 0


def test_production_batch_rejects_amount_cap():
    calculation, approval, plan = _plan()
    profile = build_development_reward_production_profile(
        network_id="aidn-localnet-1",
        chain_id="chain-test-1",
        effective_epoch=0,
        activation_approval=approval,
        policy=calculation.policy,
        max_batch_q_atoms=1,
        max_contributions=1,
        max_operations=8,
    )

    with pytest.raises(ValueError, match="DEVELOPMENT_PRODUCTION_BATCH_AMOUNT_CAP_EXCEEDED"):
        build_development_reward_production_batch(
            profile=profile,
            activation_approval=approval,
            plan=plan,
            source_epoch_transition_operation_id="epoch-transition-20",
            pool_budget_reference="epoch:20:GENERAL_DEVELOPMENT",
        )
