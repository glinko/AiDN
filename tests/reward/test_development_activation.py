import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aidn_hypervisor.reward.development_activation import (
    DevelopmentRewardActivationGate,
    DevelopmentRewardApprovalSignature,
    DevelopmentRewardAuthority,
    activation_authorization_payload,
    build_development_reward_activation_approval,
    development_reward_policy_hash,
)
from aidn_hypervisor.reward.development_distribution import (
    Q_ATOMS_PER_Q,
    DevelopmentPoolInput,
    DevelopmentRewardCalculator,
    DevelopmentRewardPolicy,
)
from aidn_hypervisor.reward.development_rollout import (
    build_development_reward_rollout_profile,
    validate_development_reward_rollout,
)
from aidn_hypervisor.reward.development_scenarios import run_launch_simulation_matrix


def _authority(authority_id: str, seed: int):
    private_key = Ed25519PrivateKey.from_private_bytes(bytes([seed]) * 32)
    public_key = "ed25519:" + private_key.public_key().public_bytes_raw().hex()
    return (
        authority_id,
        private_key,
        DevelopmentRewardAuthority(
            authority_id=authority_id,
            public_key=public_key,
        ),
    )


def _calculation(policy: DevelopmentRewardPolicy | None = None, *, epoch: int = 20):
    return DevelopmentRewardCalculator(policy).calculate(
        DevelopmentPoolInput(
            epoch=epoch,
            distributable_epoch_emission_q_atoms=5_000_000_000,
        ),
        [],
    )


def _approval(
    policy: DevelopmentRewardPolicy,
    *,
    effective_epoch: int = 15,
    approvals_count: int = 2,
    state: str = "APPROVED",
    rollout_profile=None,
):
    authority_entries = [_authority("governance-a", 1), _authority("governance-b", 2)]
    authorities = [item[2] for item in authority_entries]
    policy_hash = development_reward_policy_hash(policy)
    unsigned = build_development_reward_activation_approval(
        policy_hash=policy_hash,
        effective_epoch=effective_epoch,
        eligible_authorities=authorities,
        quorum_threshold=2,
        approvals=[],
        rollout_profile=rollout_profile,
        state=state,
    )
    signatures = []
    for authority_id, private_key, _ in authority_entries[:approvals_count]:
        payload = activation_authorization_payload(
            activation_id=unsigned.activation_id,
            policy_hash=policy_hash,
            effective_epoch=effective_epoch,
            eligible_authorities=authorities,
            quorum_threshold=2,
            authority_id=authority_id,
            rollout_profile=rollout_profile,
        )
        signatures.append(
            DevelopmentRewardApprovalSignature(
                authority_id=authority_id,
                signature="ed25519:" + private_key.sign(payload).hex(),
                approval_note="approved for launch simulation",
            )
        )
    return build_development_reward_activation_approval(
        policy_hash=policy_hash,
        effective_epoch=effective_epoch,
        eligible_authorities=authorities,
        quorum_threshold=2,
        approvals=signatures,
        rollout_profile=rollout_profile,
        state=state,
    )


def test_activation_gate_accepts_exact_policy_and_quorum():
    policy = DevelopmentRewardPolicy(nominal_q_per_cu_q_atoms=Q_ATOMS_PER_Q)
    approval = _approval(policy)
    decision = DevelopmentRewardActivationGate.assert_active(
        calculation=_calculation(policy),
        approval=approval,
        current_epoch=20,
    )

    assert decision.state == "ACTIVE"
    assert decision.activation_id == approval.activation_id
    assert decision.policy_hash == development_reward_policy_hash(policy)
    assert decision.verify_integrity()
    assert approval.verify_integrity()


def test_activation_gate_rejects_missing_or_premature_approval():
    policy = DevelopmentRewardPolicy()
    calculation = _calculation(policy)

    with pytest.raises(ValueError, match="DEVELOPMENT_ACTIVATION_APPROVAL_REQUIRED"):
        DevelopmentRewardActivationGate.assert_active(
            calculation=calculation,
            approval=None,
            current_epoch=20,
        )

    approval = _approval(policy, effective_epoch=25)
    with pytest.raises(ValueError, match="DEVELOPMENT_ACTIVATION_NOT_EFFECTIVE"):
        DevelopmentRewardActivationGate.assert_active(
            calculation=calculation,
            approval=approval,
            current_epoch=20,
        )


def test_activation_gate_rejects_policy_mismatch_and_old_calculation():
    approved_policy = DevelopmentRewardPolicy()
    approval = _approval(approved_policy)
    changed_policy = DevelopmentRewardPolicy(nominal_q_per_cu_q_atoms=2 * Q_ATOMS_PER_Q)
    with pytest.raises(ValueError, match="DEVELOPMENT_ACTIVATION_POLICY_MISMATCH"):
        DevelopmentRewardActivationGate.assert_active(
            calculation=_calculation(changed_policy),
            approval=approval,
            current_epoch=20,
        )

    old_calculation = _calculation(approved_policy, epoch=10)
    with pytest.raises(ValueError, match="DEVELOPMENT_ACTIVATION_CALCULATION_BEFORE_EFFECTIVE_EPOCH"):
        DevelopmentRewardActivationGate.assert_active(
            calculation=old_calculation,
            approval=approval,
            current_epoch=20,
        )


def test_activation_gate_rejects_tampering_duplicate_or_revocation():
    policy = DevelopmentRewardPolicy()
    approval = _approval(policy)
    tampered = approval.model_copy(
        update={
            "approvals": [
                approval.approvals[0].model_copy(update={"approval_note": "changed"}),
                approval.approvals[1],
            ]
        }
    )
    with pytest.raises(ValueError, match="DEVELOPMENT_ACTIVATION_APPROVAL_HASH_INVALID"):
        DevelopmentRewardActivationGate.assert_active(
            calculation=_calculation(policy),
            approval=tampered,
            current_epoch=20,
        )

    revoked = _approval(policy, state="REVOKED")
    with pytest.raises(ValueError, match="DEVELOPMENT_ACTIVATION_REVOKED"):
        DevelopmentRewardActivationGate.assert_active(
            calculation=_calculation(policy),
            approval=revoked,
            current_epoch=20,
        )

    insufficient = _approval(policy, approvals_count=0)
    with pytest.raises(ValueError, match="DEVELOPMENT_ACTIVATION_QUORUM_MISSING"):
        DevelopmentRewardActivationGate.assert_active(
            calculation=_calculation(policy),
            approval=insufficient,
            current_epoch=20,
        )


def test_activation_model_rejects_threshold_above_authority_set():
    authority_entries = [_authority("governance-a", 1), _authority("governance-b", 2)]
    with pytest.raises(ValueError, match="DEVELOPMENT_ACTIVATION_QUORUM_INVALID"):
        build_development_reward_activation_approval(
            policy_hash=development_reward_policy_hash(DevelopmentRewardPolicy()),
            effective_epoch=15,
            eligible_authorities=[item[2] for item in authority_entries],
            quorum_threshold=3,
            approvals=[],
        )


def test_activation_rollout_profile_is_signed_and_enforced():
    calculation = run_launch_simulation_matrix().scenarios[0].calculation
    profile = build_development_reward_rollout_profile(
        effective_epoch=calculation.epoch,
        max_epoch_reward_q_atoms=calculation.accepted_gross_reward_q_atoms - 1,
        max_contributions=1,
    )
    approval = _approval(calculation.policy, effective_epoch=calculation.epoch, rollout_profile=profile)

    assert approval.rollout_profile == profile
    assert approval.verify_integrity()
    with pytest.raises(ValueError, match="DEVELOPMENT_REWARD_ROLLOUT_EPOCH_CAP_EXCEEDED"):
        DevelopmentRewardActivationGate.assert_active(
            calculation=calculation,
            approval=approval,
            current_epoch=calculation.epoch,
        )


def test_rollout_profile_enforces_contribution_and_contributor_caps():
    many_contributions = run_launch_simulation_matrix().scenarios[2].calculation
    count_profile = build_development_reward_rollout_profile(
        effective_epoch=many_contributions.epoch,
        max_epoch_reward_q_atoms=many_contributions.accepted_gross_reward_q_atoms,
        max_contributions=1,
    )
    with pytest.raises(ValueError, match="DEVELOPMENT_REWARD_ROLLOUT_CONTRIBUTION_COUNT_EXCEEDED"):
        validate_development_reward_rollout(many_contributions, count_profile)

    dominant = run_launch_simulation_matrix().scenarios[1].calculation
    contributor_totals = {}
    for allocation in dominant.allocations:
        for role_reward in allocation.role_rewards:
            contributor_totals[role_reward.contributor_id] = (
                contributor_totals.get(role_reward.contributor_id, 0)
                + role_reward.accepted_gross_q_atoms
            )
    max_contributor_reward = max(contributor_totals.values())
    contributor_profile = build_development_reward_rollout_profile(
        effective_epoch=dominant.epoch,
        max_epoch_reward_q_atoms=dominant.accepted_gross_reward_q_atoms,
        max_contributions=len(dominant.allocations),
        max_contributor_reward_q_atoms=max_contributor_reward - 1,
    )
    with pytest.raises(ValueError, match="DEVELOPMENT_REWARD_ROLLOUT_CONTRIBUTOR_CAP_EXCEEDED"):
        validate_development_reward_rollout(dominant, contributor_profile)
