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
from aidn_hypervisor.reward.development_scenarios import run_launch_simulation_matrix


def _calculation():
    report = run_launch_simulation_matrix()
    return report.scenarios[0].calculation


def _approval(policy):
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
    )


def test_dry_run_commitment_is_deterministic_and_non_emitting():
    calculation = _calculation()
    first = build_development_reward_commitment(calculation)
    second = build_development_reward_commitment(calculation)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.simulation_only is True
    assert first.emits_q is False
    assert first.ledger_writes is False
    assert first.activation_state == "SIMULATION_ONLY"
    assert first.verify_integrity()
    assert first.policy_hash == development_reward_policy_hash(calculation.policy)
    assert first.calculation_root == calculation.calculation_root


def test_dry_run_commitment_requires_and_binds_signed_activation_approval():
    calculation = _calculation()
    approval = _approval(calculation.policy)
    commitment = build_development_reward_commitment(
        calculation,
        activation_approval=approval,
        current_epoch=20,
    )

    assert commitment.activation_state == "ACTIVATION_VERIFIED"
    assert commitment.activation_id == approval.activation_id
    assert commitment.activation_approval_hash == approval.approval_hash
    assert commitment.verify_integrity()

    with pytest.raises(ValueError, match="DEVELOPMENT_COMMITMENT_CURRENT_EPOCH_REQUIRED"):
        build_development_reward_commitment(
            calculation,
            activation_approval=approval,
        )


def test_dry_run_commitment_rejects_tampered_or_unverified_inputs():
    calculation = _calculation()
    tampered = calculation.model_copy(update={"calculation_root": "sha256:tampered"})
    with pytest.raises(ValueError, match="DEVELOPMENT_COMMITMENT_CALCULATION_INVALID"):
        build_development_reward_commitment(tampered)

    approval = _approval(calculation.policy)
    tampered_approval = approval.model_copy(
        update={
            "approvals": [
                approval.approvals[0].model_copy(update={"approval_note": "tampered"}),
                approval.approvals[1],
            ]
        }
    )
    with pytest.raises(ValueError, match="DEVELOPMENT_ACTIVATION_APPROVAL_HASH_INVALID"):
        build_development_reward_commitment(
            calculation,
            activation_approval=tampered_approval,
            current_epoch=20,
        )
