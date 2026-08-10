"""Canonical RFC-0068 evidence objects and fixed-point scoring primitives."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, Field

FIXED_POINT_SCALE = 1_000
BASIS_POINTS = 10_000
HASH_VERSION = "rfc-0068-evidence.v1"

ContributionClass = Literal[
    "CODE",
    "TESTS",
    "SECURITY",
    "DOCUMENTATION",
    "SPECIFICATION",
    "REVIEW",
    "BUG_TRIAGE",
    "RELEASE",
    "INFRASTRUCTURE",
    "DESIGN",
    "RESEARCH",
    "LOCALIZATION",
    "COMMUNITY_TOOLING",
]

ContributionRole = Literal[
    "AUTHOR",
    "COAUTHOR",
    "ISSUE_DESIGNER",
    "SPECIFICATION_AUTHOR",
    "PRIMARY_REVIEWER",
    "SECONDARY_REVIEWER",
    "SECURITY_REVIEWER",
    "TEST_AUTHOR",
    "RELEASE_INTEGRATOR",
]

ContributionEligibilityState = Literal[
    "PENDING",
    "ELIGIBLE",
    "INELIGIBLE",
    "CHALLENGED",
    "FINALIZED",
    "UNCLAIMED",
    "VESTING",
    "MATURED",
    "CANCELLED",
]

ContributionChallengeState = Literal["OPEN", "RESOLVED", "EXPIRED"]
ContributionMaturityState = Literal[
    "PENDING",
    "ELIGIBLE",
    "CONFIRMED",
    "REDUCED",
    "CANCELLED",
]

ChallengeResolution = Literal[
    "ATTESTATION_CONFIRMED",
    "ATTRIBUTION_CORRECTED",
    "SCORE_CORRECTED",
    "CONTRIBUTION_GROUPED",
    "CONTRIBUTION_EXCLUDED",
    "WALLET_BINDING_REQUIRED",
    "SECURITY_REVIEW_REQUIRED",
]

RevertClassification = Literal[
    "REQUIREMENT_CHANGE",
    "SUPERSEDED",
    "ORDINARY_DEFECT",
    "CRITICAL_DEFECT",
    "SECURITY_DEFECT",
    "INTENTIONAL_GAMING",
    "MALICIOUS",
]


def canonical_json(value: Any) -> str:
    """Serialize a JSON-compatible value with one protocol-defined ordering."""

    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def canonical_hash(value: Any) -> str:
    """Return a versioned SHA-256 commitment for a canonical JSON value."""

    payload = f"{HASH_VERSION}:{canonical_json(value)}".encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


class RepositoryContributionProfile(BaseModel):
    profile_id: str = Field(min_length=1)
    repository_id: str = Field(min_length=1)
    path_weights_milli: dict[str, int] = Field(
        default_factory=lambda: {
            "source": 1_000,
            "test": 1_000,
            "documentation": 1_000,
            "configuration": 1_000,
        }
    )
    excluded_paths: list[str] = Field(default_factory=list)
    generated_patterns: list[str] = Field(default_factory=list)
    vendor_patterns: list[str] = Field(default_factory=list)
    lockfile_names: list[str] = Field(
        default_factory=lambda: [
            "package-lock.json",
            "pnpm-lock.yaml",
            "poetry.lock",
            "uv.lock",
        ]
    )
    maximum_automatic_size_score_milli: int = Field(
        default=50_000,
        ge=0,
    )
    profile_version: str = Field(default="1", min_length=1)
    profile_hash: str = Field(default="")

    def unsigned_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"profile_hash"})

    def with_hash(self) -> RepositoryContributionProfile:
        return self.model_copy(update={"profile_hash": canonical_hash(self.unsigned_payload())})


class EligibleRepository(BaseModel):
    repository_id: str = Field(min_length=1)
    repository_name: str = Field(min_length=1)
    canonical_url: str = Field(min_length=1)
    organization_id: str = Field(min_length=1)
    default_branch: str = Field(default="main", min_length=1)
    additional_reward_branches: list[str] = Field(default_factory=list)
    contribution_profile_id: str = Field(min_length=1)
    attestation_policy_id: str = Field(
        default="AUTOMATION_PLUS_MAINTAINER",
        min_length=1,
    )
    attestation_authority_ids: list[str] = Field(default_factory=list)
    active_from_epoch: int = Field(default=0, ge=0)
    active_until_epoch: int | None = Field(default=None, ge=0)
    repository_hash: str = Field(min_length=1)
    authorization_signature: str = Field(min_length=1)

    def is_active(self, epoch: int) -> bool:
        return epoch >= self.active_from_epoch and (self.active_until_epoch is None or epoch <= self.active_until_epoch)

    def protected_branches(self) -> set[str]:
        return {self.default_branch, *self.additional_reward_branches}


class PlatformAccount(BaseModel):
    platform: str = Field(min_length=1)
    account_id: str = Field(min_length=1)
    handle: str = Field(min_length=1)

    @property
    def reference(self) -> str:
        return f"{self.platform}:{self.account_id}"


class ContributorIdentity(BaseModel):
    contributor_id: str = Field(min_length=1)
    source_platform_accounts: list[PlatformAccount] = Field(min_length=1)
    current_wallet_address: str | None = None
    wallet_binding_version: int = Field(default=0, ge=0)
    known_control_group: str | None = None
    identity_state: Literal["ACTIVE", "SUSPENDED", "REVOKED"] = "ACTIVE"
    valid_from: str = Field(min_length=1)
    valid_until: str | None = None
    identity_hash: str = Field(min_length=1)
    contributor_signature: str = Field(min_length=1)

    def has_platform_account(self, reference: str) -> bool:
        return reference in {account.reference for account in self.source_platform_accounts}


class ContributorWalletBindingChallenge(BaseModel):
    challenge_id: str = Field(min_length=1)
    contributor_id: str = Field(min_length=1)
    source_platform_account: str = Field(min_length=1)
    wallet_address: str = Field(min_length=1)
    issued_at: str = Field(min_length=1)
    expires_at: str = Field(min_length=1)
    challenge_hash: str = Field(min_length=1)
    used: bool = False


class ContributorWalletBinding(BaseModel):
    binding_id: str = Field(min_length=1)
    contributor_id: str = Field(min_length=1)
    source_platform_account: str = Field(min_length=1)
    wallet_address: str = Field(min_length=1)
    wallet_public_key: str = Field(min_length=1)
    challenge_id: str = Field(min_length=1)
    challenge_hash: str = Field(min_length=1)
    wallet_signature: str = Field(min_length=1)
    source_platform_confirmation_hash: str = Field(min_length=1)
    valid_from: str = Field(min_length=1)
    binding_version: int = Field(ge=1)
    binding_hash: str = Field(min_length=1)


class ContributorWalletClaim(BaseModel):
    """Signed wallet declaration committed in a merged repository revision."""

    schema_version: Literal["aidn.contributor-wallet.v1"] = "aidn.contributor-wallet.v1"
    contributor_id: str = Field(min_length=1)
    source_platform_account: str = Field(min_length=1)
    wallet_address: str = Field(min_length=1)
    wallet_public_key: str = Field(min_length=1)
    wallet_signature: str = Field(min_length=1)
    binding_id: str | None = None
    binding_hash: str | None = None
    claim_hash: str = Field(min_length=1)

    def unsigned_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"wallet_signature", "claim_hash"})

    def signed_payload(self) -> dict[str, Any]:
        return {
            "domain": "aidn.contributor-wallet-claim.v1",
            **self.unsigned_payload(),
        }

    def expected_claim_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="json", exclude={"claim_hash"}))


class ContributionGroup(BaseModel):
    contribution_group_id: str = Field(min_length=1)
    repository_id: str = Field(min_length=1)
    logical_deliverable: str = Field(min_length=1)
    contribution_ids: list[str] = Field(default_factory=list)
    group_hash: str = Field(min_length=1)


class ContributionMergeEvent(BaseModel):
    merge_event_id: str = Field(min_length=1)
    repository_id: str = Field(min_length=1)
    pull_request_id: str = Field(min_length=1)
    merge_commit_hash: str = Field(min_length=1)
    base_branch: str = Field(min_length=1)
    source_commit_hash: str | None = None
    merged_at: str = Field(min_length=1)
    merge_actor: str = Field(min_length=1)
    pull_request_author: str = Field(min_length=1)
    coauthors: list[str] = Field(default_factory=list)
    contribution_group_id: str | None = None
    reward_metadata: dict[str, Any] = Field(default_factory=dict)
    source_platform_evidence_hash: str = Field(min_length=1)
    protected_branch_tip: str = Field(min_length=1)
    verification_method: Literal["LOCAL_GIT_ANCESTOR"] = "LOCAL_GIT_ANCESTOR"
    merge_event_hash: str = Field(min_length=1)


class ContributionFileChange(BaseModel):
    path: str = Field(min_length=1)
    added_lines: int = Field(default=0, ge=0)
    deleted_lines: int = Field(default=0, ge=0)
    binary: bool = False
    generated: bool = False
    vendored: bool = False
    formatting_only: bool = False


class ContributionFactorValues(BaseModel):
    complexity_milli: int = Field(default=1_000, ge=0, le=2_000)
    priority_milli: int = Field(default=1_000, ge=0, le=2_000)
    quality_milli: int = Field(default=1_000, ge=0, le=2_000)
    impact_expectation_milli: int = Field(default=1_000, ge=0, le=2_000)
    independence_milli: int = Field(default=1_000, ge=0, le=2_000)


class AttestationAuthority(BaseModel):
    authority_id: str = Field(min_length=1)
    authority_role: str = Field(min_length=1)
    signature: str = Field(min_length=1)


class ContributionRoleAllocation(BaseModel):
    contributor_id: str = Field(min_length=1)
    role: ContributionRole
    allocation_basis_points: int = Field(ge=0, le=BASIS_POINTS)
    evidence_hash: str = Field(min_length=1)


class ContributionAttestation(BaseModel):
    contribution_id: str = Field(min_length=1)
    repository_id: str = Field(min_length=1)
    pull_request_id: str = Field(min_length=1)
    merge_commit_hash: str = Field(min_length=1)
    contribution_epoch: int = Field(ge=0)
    contribution_class: ContributionClass
    contribution_group_id: str | None = None
    effective_change_units_milli: int = Field(ge=0)
    size_score_milli: int = Field(ge=0)
    factor_values: ContributionFactorValues
    contribution_units_milli: int = Field(ge=0)
    file_changes: list[ContributionFileChange] = Field(default_factory=list)
    repository_profile_hash: str = Field(min_length=1)
    role_allocations: list[ContributionRoleAllocation] = Field(default_factory=list)
    wallet_claim: ContributorWalletClaim | None = None
    eligibility_state: ContributionEligibilityState = "PENDING"
    wallet_state: Literal["VERIFIED", "UNCLAIMED"] = "UNCLAIMED"
    challenge_until_epoch: int = Field(ge=0)
    maturity_stage_one_epoch: int = Field(ge=0)
    maturity_stage_two_epoch: int = Field(ge=0)
    exclusion_reasons: list[str] = Field(default_factory=list)
    source_evidence_root: str = Field(min_length=1)
    scoring_evidence_root: str = Field(min_length=1)
    attestation_authorities: list[AttestationAuthority] = Field(min_length=1)
    merge_event_hash: str = Field(min_length=1)
    attested_at: str = Field(min_length=1)
    finalized_at: str | None = None
    supersedes_attestation_hash: str | None = None
    attestation_hash: str = Field(min_length=1)


class ContributionChallenge(BaseModel):
    challenge_id: str = Field(min_length=1)
    contribution_id: str = Field(min_length=1)
    challenger_id: str = Field(min_length=1)
    challenge_class: str = Field(min_length=1)
    claimed_error: str = Field(min_length=1)
    evidence_root: str = Field(min_length=1)
    opened_at: str = Field(min_length=1)
    challenge_until_epoch: int = Field(ge=0)
    challenger_signature: str = Field(min_length=1)
    state: ContributionChallengeState = "OPEN"
    resolution_id: str | None = None
    challenge_hash: str = Field(min_length=1)


class ContributionChallengeResolution(BaseModel):
    resolution_id: str = Field(min_length=1)
    challenge_id: str = Field(min_length=1)
    contribution_id: str = Field(min_length=1)
    resolution: ChallengeResolution
    resolved_by: str = Field(min_length=1)
    resolved_at: str = Field(min_length=1)
    evidence_root: str = Field(min_length=1)
    resolver_signature: str = Field(min_length=1)
    resolution_hash: str = Field(min_length=1)


class ContributionMaturityRecord(BaseModel):
    maturity_id: str = Field(min_length=1)
    contribution_id: str = Field(min_length=1)
    stage: Literal[1, 2]
    due_epoch: int = Field(ge=0)
    state: ContributionMaturityState = "PENDING"
    revert_classification: RevertClassification | None = None
    decision_reason: str | None = None
    evidence_root: str = Field(min_length=1)
    decision_by: str | None = None
    decision_at: str = Field(min_length=1)
    maturity_hash: str = Field(min_length=1)
