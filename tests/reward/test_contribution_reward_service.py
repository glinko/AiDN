from __future__ import annotations

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aidn_hypervisor.contributions.models import (
    AttestationAuthority,
    ContributionAttestation,
    ContributionFactorValues,
    ContributionRoleAllocation,
    ContributorIdentity,
    ContributorWalletClaim,
    PlatformAccount,
)
from aidn_hypervisor.contributions.models import (
    canonical_hash as contribution_hash,
)
from aidn_hypervisor.contributions.service import ContributionAccountingService
from aidn_hypervisor.contributions.store import ContributionEvidenceStore
from aidn_hypervisor.reward.development_activation import (
    DevelopmentRewardApprovalSignature,
    DevelopmentRewardAuthority,
    activation_authorization_payload,
    build_development_reward_activation_approval,
    development_reward_policy_hash,
)
from aidn_hypervisor.reward.development_contribution_service import (
    DevelopmentContributionRewardService,
)
from aidn_hypervisor.reward.development_distribution import (
    DevelopmentPoolInput,
    DevelopmentRewardPolicy,
)


def _contributor() -> ContributorIdentity:
    return ContributorIdentity(
        contributor_id="contributor-alice",
        source_platform_accounts=[PlatformAccount(platform="github", account_id="alice", handle="alice")],
        valid_from="2030-01-01T00:00:00Z",
        identity_hash="sha256:identity",
        contributor_signature="ed25519:identity",
    )


def _attestation() -> ContributionAttestation:
    private_key = Ed25519PrivateKey.generate()
    public_key = "ed25519:" + private_key.public_key().public_bytes_raw().hex()
    claim = ContributorWalletClaim(
        contributor_id="contributor-alice",
        source_platform_account="github:alice",
        wallet_address="q1alice",
        wallet_public_key=public_key,
        wallet_signature="ed25519:claim",
        claim_hash="sha256:claim",
    )
    role = ContributionRoleAllocation(
        contributor_id="contributor-alice",
        role="AUTHOR",
        allocation_basis_points=10_000,
        evidence_hash="sha256:role",
    )
    payload = {
        "contribution_id": "contribution-1",
        "repository_id": "repo-aidn",
        "pull_request_id": "1",
        "merge_commit_hash": "a" * 40,
        "contribution_epoch": 0,
        "contribution_class": "CODE",
        "contribution_group_id": None,
        "effective_change_units_milli": 1_000,
        "size_score_milli": 1_000,
        "factor_values": ContributionFactorValues().model_dump(mode="json"),
        "contribution_units_milli": 1_000,
        "file_changes": [],
        "repository_profile_hash": "sha256:profile",
        "role_allocations": [role.model_dump(mode="json")],
        "wallet_claim": claim.model_dump(mode="json"),
        "eligibility_state": "FINALIZED",
        "wallet_state": "VERIFIED",
        "challenge_until_epoch": 1,
        "maturity_stage_one_epoch": 4,
        "maturity_stage_two_epoch": 12,
        "exclusion_reasons": [],
        "source_evidence_root": "sha256:source",
        "scoring_evidence_root": "sha256:scoring",
        "attestation_authorities": [
            AttestationAuthority(
                authority_id="maintainer-1",
                authority_role="maintainer",
                signature="ed25519:maintainer",
            ).model_dump(mode="json")
        ],
        "merge_event_hash": "sha256:merge",
        "attested_at": "2030-01-01T00:00:00Z",
        "finalized_at": "2030-01-03T00:00:00Z",
        "supersedes_attestation_hash": None,
    }
    return ContributionAttestation(**payload, attestation_hash=contribution_hash(payload))


def _approval(policy: DevelopmentRewardPolicy):
    operation_types = [
        "DEVELOPMENT_REWARD_CALCULATE",
        "DEVELOPMENT_POOL_ALLOCATE",
        "DEVELOPMENT_REWARD_RESERVE",
        "DEVELOPMENT_REWARD_PAY_IMMEDIATE",
        "DEVELOPMENT_REWARD_MARK_UNCLAIMED",
    ]
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
        effective_epoch=0,
        eligible_authorities=authorities,
        quorum_threshold=2,
        approvals=[],
        authorized_operation_types=operation_types,
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
                    authorized_operation_types=operation_types,
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
        authorized_operation_types=operation_types,
        economic_effect_profile="DEVELOPMENT_PAYMENTS",
    )


def test_preview_uses_wallet_claim_from_finalized_attestation(tmp_path):
    store = ContributionEvidenceStore(tmp_path / "evidence.json")
    contribution_service = ContributionAccountingService(store)
    contribution_service.register_contributor(_contributor())
    attestation = _attestation()
    store.record_attestation(attestation)
    planner = DevelopmentContributionRewardService(contribution_service)

    preview = planner.preview(
        pool_input=DevelopmentPoolInput(
            epoch=0,
            distributable_epoch_emission_q_atoms=5_000_000_000,
        ),
        contribution_ids=[attestation.contribution_id],
    )

    assert preview.wallet_provenance == {"contributor-alice": "MERGED_COMMIT_WALLET_CLAIM"}
    assert {item.wallet_address for item in preview.calculation.payments} == {"q1alice"}
    assert preview.commitment.activation_state == "SIMULATION_ONLY"


def test_build_consensus_plan_is_ordered_and_activation_gated(tmp_path):
    store = ContributionEvidenceStore(tmp_path / "evidence.json")
    contribution_service = ContributionAccountingService(store)
    contribution_service.register_contributor(_contributor())
    attestation = _attestation()
    store.record_attestation(attestation)
    planner = DevelopmentContributionRewardService(contribution_service)
    preview = planner.preview(
        pool_input=DevelopmentPoolInput(
            epoch=0,
            distributable_epoch_emission_q_atoms=5_000_000_000,
        ),
        contribution_ids=[attestation.contribution_id],
    )
    approval = _approval(preview.calculation.policy)

    plan = planner.build_consensus_plan(
        preview,
        activation_approval=approval,
        current_epoch=0,
        source_epoch_transition_operation_id="epoch-transition-0",
        pool_budget_reference="epoch:0:GENERAL_DEVELOPMENT",
        created_at="2030-01-03T00:00:00Z",
    )

    assert plan.commitment.activation_state == "ACTIVATION_VERIFIED"
    assert [item.operation_type for item in plan.envelopes] == [
        "DEVELOPMENT_REWARD_CALCULATE",
        "DEVELOPMENT_POOL_ALLOCATE",
        "DEVELOPMENT_REWARD_RESERVE",
        "DEVELOPMENT_REWARD_PAY_IMMEDIATE",
    ]
    assert plan.envelopes[0].operation_id != plan.envelopes[1].operation_id
    assert plan.plan_hash.startswith("sha256:")
