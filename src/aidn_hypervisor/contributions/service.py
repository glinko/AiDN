"""RFC-0068 contribution evidence lifecycle.

The service intentionally stops before ECO-0007: it verifies evidence,
attributes work, scores it with integer arithmetic, and records maturity or
challenge decisions.  It has no Q balance and no Ledger write capability.
"""

from __future__ import annotations

import fnmatch
import re
import secrets
import subprocess
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from math import isqrt
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from aidn_hypervisor.contributions.models import (
    BASIS_POINTS,
    FIXED_POINT_SCALE,
    AttestationAuthority,
    ChallengeResolution,
    ContributionAttestation,
    ContributionChallenge,
    ContributionChallengeResolution,
    ContributionClass,
    ContributionFactorValues,
    ContributionFileChange,
    ContributionGroup,
    ContributionMaturityRecord,
    ContributionMergeEvent,
    ContributionRoleAllocation,
    ContributorIdentity,
    ContributorWalletBinding,
    ContributorWalletBindingChallenge,
    EligibleRepository,
    RepositoryContributionProfile,
    RevertClassification,
    canonical_hash,
    canonical_json,
)
from aidn_hypervisor.contributions.store import ContributionEvidenceStore

_COMMIT_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")
_BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]+$")


class ContributionNotFoundError(KeyError):
    """A referenced evidence object does not exist."""


class ContributionConflictError(ValueError):
    """An idempotency key was reused with different evidence."""


def contributor_wallet_binding_payload(
    *,
    contributor_id: str,
    source_platform_account: str,
    wallet_address: str,
    wallet_public_key: str,
    challenge_id: str,
    challenge_hash: str,
    binding_version: int,
) -> bytes:
    """Return the exact bytes a contributor signs for wallet ownership."""

    return canonical_json(
        {
            "domain": "aidn.contributor-wallet-binding.v1",
            "contributor_id": contributor_id,
            "source_platform_account": source_platform_account,
            "wallet_address": wallet_address,
            "wallet_public_key": wallet_public_key,
            "challenge_id": challenge_id,
            "challenge_hash": challenge_hash,
            "binding_version": binding_version,
        }
    ).encode("utf-8")


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _prefixed_hex(value: str, *, label: str, size: int) -> bytes:
    if not value.startswith("ed25519:"):
        raise ValueError(f"{label} must use ed25519:<hex> format")
    try:
        decoded = bytes.fromhex(value.removeprefix("ed25519:"))
    except ValueError as error:
        raise ValueError(f"{label} is not valid hexadecimal") from error
    if len(decoded) != size:
        raise ValueError(f"{label} has an invalid length")
    return decoded


def _verify_wallet_signature(*, public_key: str, signature: str, payload: bytes) -> None:
    try:
        key = Ed25519PublicKey.from_public_bytes(_prefixed_hex(public_key, label="wallet public key", size=32))
        key.verify(
            _prefixed_hex(signature, label="wallet signature", size=64),
            payload,
        )
    except (InvalidSignature, ValueError, TypeError) as error:
        raise ValueError("CONTRIBUTOR_WALLET_SIGNATURE_INVALID") from error


class GitRepositoryMergeVerifier:
    """Verify that a merge commit is reachable from a protected local branch."""

    def __init__(self, *, git_binary: str = "git", timeout_seconds: int = 15) -> None:
        self.git_binary = git_binary
        self.timeout_seconds = timeout_seconds

    def _validate_branch(self, branch: str) -> None:
        if not branch or not _BRANCH_RE.fullmatch(branch) or branch.startswith("-") or ".." in branch or "@{" in branch:
            raise ValueError("CONTRIBUTION_BRANCH_INVALID")

    def _validate_commit(self, commit: str) -> None:
        if not _COMMIT_RE.fullmatch(commit):
            raise ValueError("CONTRIBUTION_COMMIT_INVALID")

    def _run(self, repository_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                [self.git_binary, *args],
                cwd=repository_path,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ValueError("CONTRIBUTION_GIT_VERIFICATION_FAILED") from error

    def _output(self, repository_path: Path, *args: str) -> str:
        result = self._run(repository_path, *args)
        if result.returncode != 0:
            raise ValueError("CONTRIBUTION_GIT_VERIFICATION_FAILED")
        return result.stdout.strip()

    def verify(
        self,
        repository_path: Path | str,
        *,
        merge_commit_hash: str,
        base_branch: str,
        allowed_branches: set[str],
        source_commit_hash: str | None = None,
    ) -> dict[str, str]:
        path = Path(repository_path)
        if not path.is_dir():
            raise ValueError("CONTRIBUTION_REPOSITORY_NOT_FOUND")
        self._validate_branch(base_branch)
        self._validate_commit(merge_commit_hash)
        if source_commit_hash is not None:
            self._validate_commit(source_commit_hash)
        if base_branch not in allowed_branches:
            raise ValueError("CONTRIBUTION_BRANCH_NOT_ELIGIBLE")
        if self._output(path, "rev-parse", "--is-inside-work-tree") != "true":
            raise ValueError("CONTRIBUTION_REPOSITORY_INVALID")

        resolved_merge = self._output(path, "rev-parse", "--verify", f"{merge_commit_hash}^{{commit}}")
        branch_ref = f"refs/heads/{base_branch}"
        branch_result = self._run(path, "rev-parse", "--verify", branch_ref)
        if branch_result.returncode != 0:
            branch_ref = f"refs/remotes/origin/{base_branch}"
            branch_result = self._run(path, "rev-parse", "--verify", branch_ref)
        if branch_result.returncode != 0:
            raise ValueError("CONTRIBUTION_PROTECTED_BRANCH_NOT_FOUND")
        protected_branch_tip = branch_result.stdout.strip()

        ancestor = self._run(
            path,
            "merge-base",
            "--is-ancestor",
            resolved_merge,
            protected_branch_tip,
        )
        if ancestor.returncode != 0:
            raise ValueError("CONTRIBUTION_MERGE_NOT_REACHABLE")
        if source_commit_hash is not None:
            self._output(path, "rev-parse", "--verify", f"{source_commit_hash}^{{commit}}")
        return {
            "merge_commit_hash": resolved_merge,
            "protected_branch_tip": protected_branch_tip,
            "verification_method": "LOCAL_GIT_ANCESTOR",
        }


DEFAULT_CHANGE_WEIGHTS_MILLI = {
    "source": {"added": 1_000, "modified": 1_000, "deleted": 700},
    "test": {"added": 850, "modified": 850, "deleted": 500},
    "documentation": {"added": 350, "modified": 350, "deleted": 350},
    "configuration": {"added": 400, "modified": 400, "deleted": 400},
}


def _matches_path(path: str, patterns: Iterable[str]) -> bool:
    normalized = path.replace("\\", "/")
    for pattern in patterns:
        candidate = pattern.replace("\\", "/")
        if fnmatch.fnmatchcase(normalized, candidate) or normalized.startswith(candidate.rstrip("/") + "/"):
            return True
    return False


def classify_contribution_path(path: str, profile: RepositoryContributionProfile) -> str:
    """Classify a path for scoring without inspecting executable contents."""

    normalized = path.replace("\\", "/")
    if _matches_path(normalized, profile.excluded_paths):
        return "excluded"
    if _matches_path(normalized, profile.generated_patterns):
        return "generated"
    if _matches_path(normalized, profile.vendor_patterns):
        return "vendor"
    if normalized.rsplit("/", 1)[-1] in set(profile.lockfile_names):
        return "lockfile"
    lower = normalized.lower()
    if (
        "/test" in f"/{lower}"
        or lower.startswith("test/")
        or lower.startswith("tests/")
        or ".test." in lower
        or ".spec." in lower
    ):
        return "test"
    if lower.endswith((".md", ".rst", ".txt")) or lower.startswith("docs/"):
        return "documentation"
    if lower.endswith((".json", ".toml", ".yaml", ".yml", ".ini", ".cfg")):
        return "configuration"
    return "source"


def score_contribution_changes(
    changes: Iterable[ContributionFileChange],
    profile: RepositoryContributionProfile,
    factors: ContributionFactorValues,
) -> dict[str, Any]:
    """Calculate ECU, sublinear size score, and CU with integer arithmetic."""

    normalized_changes = sorted(
        [
            item if isinstance(item, ContributionFileChange) else ContributionFileChange.model_validate(item)
            for item in changes
        ],
        key=lambda item: item.path.replace("\\", "/"),
    )
    effective_change_units_milli = 0
    evidence: list[dict[str, Any]] = []
    for change in normalized_changes:
        kind = classify_contribution_path(change.path, profile)
        path_weight = profile.path_weights_milli.get(kind, 1_000)
        excluded = kind in {"excluded", "generated", "vendor", "lockfile"} or change.binary or change.formatting_only
        if excluded:
            effective = 0
            modified = added_only = deleted_only = 0
        else:
            modified = min(change.added_lines, change.deleted_lines)
            added_only = change.added_lines - modified
            deleted_only = change.deleted_lines - modified
            weights = DEFAULT_CHANGE_WEIGHTS_MILLI[kind]
            effective = (
                path_weight
                * (modified * weights["modified"] + added_only * weights["added"] + deleted_only * weights["deleted"])
                // FIXED_POINT_SCALE
            )
            effective_change_units_milli += effective
        evidence.append(
            {
                "path": change.path.replace("\\", "/"),
                "classification": kind,
                "path_weight_milli": path_weight,
                "modified_lines": modified,
                "added_only_lines": added_only,
                "deleted_only_lines": deleted_only,
                "effective_change_units_milli": effective,
            }
        )

    size_score_milli = min(
        isqrt(effective_change_units_milli * FIXED_POINT_SCALE),
        profile.maximum_automatic_size_score_milli,
    )
    numerator = size_score_milli
    for factor in (
        factors.complexity_milli,
        factors.priority_milli,
        factors.quality_milli,
        factors.impact_expectation_milli,
        factors.independence_milli,
    ):
        numerator *= factor
    contribution_units_milli = numerator // (FIXED_POINT_SCALE**5)
    return {
        "effective_change_units_milli": effective_change_units_milli,
        "size_score_milli": size_score_milli,
        "contribution_units_milli": contribution_units_milli,
        "file_evidence": evidence,
    }


class ContributionAccountingService:
    """Record RFC-0068 evidence while keeping economics explicitly disabled."""

    def __init__(
        self,
        store: ContributionEvidenceStore | None = None,
        *,
        now: Callable[[], datetime] | None = None,
        git_verifier: GitRepositoryMergeVerifier | None = None,
    ) -> None:
        self.store = store or ContributionEvidenceStore()
        self._now = now or (lambda: datetime.now(UTC))
        self.git_verifier = git_verifier or GitRepositoryMergeVerifier()

    @property
    def mode(self) -> str:
        return "EVIDENCE_ONLY"

    def _now_iso(self) -> str:
        return _iso(self._now())

    def register_profile(self, profile: RepositoryContributionProfile) -> RepositoryContributionProfile:
        normalized = profile.with_hash()
        if profile.profile_hash and profile.profile_hash != normalized.profile_hash:
            raise ValueError("CONTRIBUTION_PROFILE_HASH_INVALID")
        existing = self.store.profiles.get(normalized.profile_id)
        if existing is not None:
            if existing.profile_hash != normalized.profile_hash:
                raise ContributionConflictError("CONTRIBUTION_PROFILE_CONFLICT")
            return existing
        self.store.put(self.store.profiles, normalized.profile_id, normalized)
        return normalized

    def register_repository(self, repository: EligibleRepository) -> EligibleRepository:
        profile = self.store.profiles.get(repository.contribution_profile_id)
        if profile is None:
            raise ContributionNotFoundError("CONTRIBUTION_PROFILE_NOT_FOUND")
        if profile.repository_id != repository.repository_id:
            raise ValueError("CONTRIBUTION_PROFILE_REPOSITORY_MISMATCH")
        existing = self.store.repositories.get(repository.repository_id)
        if existing is not None:
            if existing.model_dump(mode="json") != repository.model_dump(mode="json"):
                raise ContributionConflictError("REPOSITORY_REGISTRATION_CONFLICT")
            return existing
        self.store.put(self.store.repositories, repository.repository_id, repository)
        return repository

    def register_contributor(self, contributor: ContributorIdentity) -> ContributorIdentity:
        existing = self.store.contributors.get(contributor.contributor_id)
        if existing is not None:
            if existing.model_dump(mode="json") != contributor.model_dump(mode="json"):
                raise ContributionConflictError("CONTRIBUTOR_IDENTITY_CONFLICT")
            return existing
        self.store.put(self.store.contributors, contributor.contributor_id, contributor)
        return contributor

    def issue_wallet_binding_challenge(
        self,
        *,
        contributor_id: str,
        source_platform_account: str,
        wallet_address: str,
        expires_at: str | None = None,
    ) -> ContributorWalletBindingChallenge:
        contributor = self.store.contributors.get(contributor_id)
        if contributor is None:
            raise ContributionNotFoundError("CONTRIBUTOR_NOT_REGISTERED")
        if not contributor.has_platform_account(source_platform_account):
            raise ValueError("CONTRIBUTOR_PLATFORM_ACCOUNT_MISMATCH")
        issued = self._now()
        expires = _parse_datetime(expires_at) if expires_at else issued + timedelta(days=1)
        if expires <= issued:
            raise ValueError("CONTRIBUTOR_WALLET_CHALLENGE_EXPIRED")
        challenge_id = "challenge-" + secrets.token_hex(16)
        challenge_hash = canonical_hash(
            {
                "domain": "aidn.contributor-wallet-challenge.v1",
                "challenge_id": challenge_id,
                "contributor_id": contributor_id,
                "source_platform_account": source_platform_account,
                "wallet_address": wallet_address,
                "issued_at": _iso(issued),
                "expires_at": _iso(expires),
            }
        )
        challenge = ContributorWalletBindingChallenge(
            challenge_id=challenge_id,
            contributor_id=contributor_id,
            source_platform_account=source_platform_account,
            wallet_address=wallet_address,
            issued_at=_iso(issued),
            expires_at=_iso(expires),
            challenge_hash=challenge_hash,
        )
        self.store.put(self.store.wallet_challenges, challenge_id, challenge)
        return challenge

    def bind_wallet(
        self,
        *,
        challenge_id: str,
        wallet_public_key: str,
        wallet_signature: str,
        source_platform_confirmation_hash: str,
        valid_from: str | None = None,
    ) -> ContributorWalletBinding:
        challenge = self.store.wallet_challenges.get(challenge_id)
        if challenge is None:
            raise ContributionNotFoundError("CONTRIBUTOR_WALLET_CHALLENGE_NOT_FOUND")
        contributor = self.store.contributors.get(challenge.contributor_id)
        if contributor is None:
            raise ContributionNotFoundError("CONTRIBUTOR_NOT_REGISTERED")
        if challenge.used:
            existing = next(
                (item for item in self.store.wallet_bindings.values() if item.challenge_id == challenge_id),
                None,
            )
            if existing is not None:
                return existing
            raise ValueError("CONTRIBUTOR_WALLET_CHALLENGE_REPLAY")
        if _parse_datetime(challenge.expires_at) <= self._now().astimezone(UTC):
            raise ValueError("CONTRIBUTOR_WALLET_CHALLENGE_EXPIRED")
        binding_version = contributor.wallet_binding_version + 1
        payload = contributor_wallet_binding_payload(
            contributor_id=challenge.contributor_id,
            source_platform_account=challenge.source_platform_account,
            wallet_address=challenge.wallet_address,
            wallet_public_key=wallet_public_key,
            challenge_id=challenge.challenge_id,
            challenge_hash=challenge.challenge_hash,
            binding_version=binding_version,
        )
        _verify_wallet_signature(
            public_key=wallet_public_key,
            signature=wallet_signature,
            payload=payload,
        )
        if not source_platform_confirmation_hash.strip():
            raise ValueError("CONTRIBUTOR_SOURCE_CONFIRMATION_REQUIRED")
        binding_payload = {
            "contributor_id": challenge.contributor_id,
            "source_platform_account": challenge.source_platform_account,
            "wallet_address": challenge.wallet_address,
            "wallet_public_key": wallet_public_key,
            "challenge_id": challenge.challenge_id,
            "challenge_hash": challenge.challenge_hash,
            "wallet_signature": wallet_signature,
            "source_platform_confirmation_hash": source_platform_confirmation_hash,
            "valid_from": valid_from or self._now_iso(),
            "binding_version": binding_version,
        }
        binding = ContributorWalletBinding(
            binding_id=canonical_hash(binding_payload),
            **binding_payload,
            binding_hash=canonical_hash(binding_payload),
        )
        challenge = challenge.model_copy(update={"used": True})
        self.store.put(self.store.wallet_challenges, challenge.challenge_id, challenge)
        self.store.put(self.store.wallet_bindings, binding.binding_id, binding)
        identity_payload = contributor.model_dump(mode="json")
        identity_payload.update(
            {
                "current_wallet_address": binding.wallet_address,
                "wallet_binding_version": binding.binding_version,
            }
        )
        updated_contributor = contributor.model_copy(
            update={
                "current_wallet_address": binding.wallet_address,
                "wallet_binding_version": binding.binding_version,
                "identity_hash": canonical_hash(identity_payload),
            }
        )
        self.store.put(
            self.store.contributors,
            updated_contributor.contributor_id,
            updated_contributor,
        )
        return binding

    def attest_merge(
        self,
        *,
        repository_id: str,
        pull_request_id: str,
        merge_commit_hash: str,
        base_branch: str,
        source_commit_hash: str | None,
        merged_at: str | None,
        merge_actor: str,
        pull_request_author: str,
        primary_contributor_id: str,
        contribution_epoch: int,
        contribution_class: ContributionClass,
        file_changes: list[ContributionFileChange],
        attestation_authorities: list[AttestationAuthority],
        source_platform_evidence_hash: str,
        repository_path: Path | str,
        coauthors: list[str] | None = None,
        contribution_group_id: str | None = None,
        reward_metadata: dict[str, Any] | None = None,
        factor_values: ContributionFactorValues | None = None,
        role_allocations: list[ContributionRoleAllocation] | None = None,
        logical_deliverable: str | None = None,
    ) -> ContributionAttestation:
        repository = self.store.repositories.get(repository_id)
        if repository is None:
            raise ContributionNotFoundError("REPOSITORY_NOT_ELIGIBLE")
        if not repository.is_active(contribution_epoch):
            raise ValueError("REPOSITORY_REWARD_WINDOW_INVALID")
        profile = self.store.profiles.get(repository.contribution_profile_id)
        if profile is None:
            raise ContributionNotFoundError("CONTRIBUTION_PROFILE_NOT_FOUND")
        primary = self.store.contributors.get(primary_contributor_id)
        if primary is None:
            raise ContributionNotFoundError("CONTRIBUTOR_NOT_REGISTERED")
        if not primary.has_platform_account(pull_request_author):
            raise ValueError("CONTRIBUTOR_AUTHOR_ACCOUNT_MISMATCH")
        git_evidence = self.git_verifier.verify(
            repository_path,
            merge_commit_hash=merge_commit_hash,
            base_branch=base_branch,
            allowed_branches=repository.protected_branches(),
            source_commit_hash=source_commit_hash,
        )
        normalized_changes = [
            item if isinstance(item, ContributionFileChange) else ContributionFileChange.model_validate(item)
            for item in file_changes
        ]
        factors = factor_values or ContributionFactorValues()
        scoring = score_contribution_changes(normalized_changes, profile, factors)
        coauthors = list(coauthors or [])
        reward_metadata = dict(reward_metadata or {})
        merge_payload = {
            "repository_id": repository_id,
            "pull_request_id": pull_request_id,
            "merge_commit_hash": git_evidence["merge_commit_hash"],
            "base_branch": base_branch,
            "source_commit_hash": source_commit_hash,
            "merged_at": merged_at or self._now_iso(),
            "merge_actor": merge_actor,
            "pull_request_author": pull_request_author,
            "coauthors": coauthors,
            "contribution_group_id": contribution_group_id,
            "reward_metadata": reward_metadata,
            "source_platform_evidence_hash": source_platform_evidence_hash,
            "protected_branch_tip": git_evidence["protected_branch_tip"],
            "verification_method": git_evidence["verification_method"],
        }
        merge_event_hash = canonical_hash(merge_payload)
        merge_event = ContributionMergeEvent(
            merge_event_id=canonical_hash(
                {
                    "repository_id": repository_id,
                    "pull_request_id": pull_request_id,
                    "merge_commit_hash": git_evidence["merge_commit_hash"],
                }
            ),
            **merge_payload,
            merge_event_hash=merge_event_hash,
        )
        existing_event = self.store.merge_events.get(merge_event.merge_event_id)
        if existing_event is not None and existing_event.merge_event_hash != merge_event_hash:
            raise ContributionConflictError("CONTRIBUTION_MERGE_EVENT_CONFLICT")

        contribution_id = canonical_hash(
            {
                "repository_id": repository_id,
                "merge_commit_hash": git_evidence["merge_commit_hash"],
                "contribution_group_id": contribution_group_id,
            }
        )
        authorities = list(attestation_authorities)
        required_authorities = (
            2
            if (
                contribution_class == "SECURITY"
                or repository.attestation_policy_id in {"MAINTAINER_THRESHOLD", "GOVERNANCE_COMMITTEE"}
            )
            else 1
        )
        if len({item.authority_id for item in authorities}) < required_authorities:
            raise ValueError("REPOSITORY_ATTESTATION_THRESHOLD_NOT_MET")
        if repository.attestation_authority_ids and not {item.authority_id for item in authorities}.issubset(
            set(repository.attestation_authority_ids)
        ):
            raise ValueError("REPOSITORY_ATTESTATION_AUTHORITY_INVALID")

        allocations = self._normalize_allocations(
            role_allocations=role_allocations,
            primary_contributor_id=primary_contributor_id,
            contribution_id=contribution_id,
        )
        self._validate_role_allocations(allocations)
        for allocation in allocations:
            contributor = self.store.contributors.get(allocation.contributor_id)
            if contributor is None:
                raise ContributionNotFoundError("CONTRIBUTOR_NOT_REGISTERED")
            if contributor.identity_state != "ACTIVE":
                raise ValueError("CONTRIBUTOR_IDENTITY_NOT_ACTIVE")
        allocation_total = sum(item.allocation_basis_points for item in allocations)
        if allocation_total > BASIS_POINTS:
            raise ValueError("CONTRIBUTION_ALLOCATION_INVALID")

        source_evidence_root = canonical_hash(
            {
                "merge_event": merge_event.model_dump(mode="json"),
                "git_evidence": git_evidence,
                "file_changes": [item.model_dump(mode="json") for item in normalized_changes],
            }
        )
        if contribution_id in self.store.attestations:
            existing = self.store.attestations[contribution_id]
            if existing.source_evidence_root == source_evidence_root:
                return existing
            raise ContributionConflictError("CONTRIBUTION_ALREADY_ATTESTED")
        scoring_evidence_root = canonical_hash(
            {
                "profile_hash": profile.profile_hash,
                "scoring": scoring,
                "factors": factors.model_dump(mode="json"),
            }
        )
        wallet_state = "VERIFIED" if primary.current_wallet_address else "UNCLAIMED"
        attestation_payload = {
            "contribution_id": contribution_id,
            "repository_id": repository_id,
            "pull_request_id": pull_request_id,
            "merge_commit_hash": git_evidence["merge_commit_hash"],
            "contribution_epoch": contribution_epoch,
            "contribution_class": contribution_class,
            "contribution_group_id": contribution_group_id,
            "effective_change_units_milli": scoring["effective_change_units_milli"],
            "size_score_milli": scoring["size_score_milli"],
            "factor_values": factors.model_dump(mode="json"),
            "contribution_units_milli": scoring["contribution_units_milli"],
            "file_changes": [item.model_dump(mode="json") for item in normalized_changes],
            "repository_profile_hash": profile.profile_hash,
            "role_allocations": [item.model_dump(mode="json") for item in allocations],
            "eligibility_state": "ELIGIBLE",
            "wallet_state": wallet_state,
            "challenge_until_epoch": contribution_epoch + 1,
            "maturity_stage_one_epoch": contribution_epoch + 4,
            "maturity_stage_two_epoch": contribution_epoch + 12,
            "exclusion_reasons": [],
            "source_evidence_root": source_evidence_root,
            "scoring_evidence_root": scoring_evidence_root,
            "attestation_authorities": [item.model_dump(mode="json") for item in authorities],
            "merge_event_hash": merge_event_hash,
            "attested_at": self._now_iso(),
        }
        attestation = ContributionAttestation(
            **attestation_payload,
            attestation_hash=canonical_hash(attestation_payload),
        )
        self._update_group(
            repository=repository,
            contribution_group_id=contribution_group_id,
            contribution_id=contribution_id,
            logical_deliverable=logical_deliverable,
        )
        self.store.put(self.store.merge_events, merge_event.merge_event_id, merge_event)
        self.store.record_attestation(attestation)
        return attestation

    @staticmethod
    def _normalize_allocations(
        *,
        role_allocations: list[ContributionRoleAllocation] | None,
        primary_contributor_id: str,
        contribution_id: str,
    ) -> list[ContributionRoleAllocation]:
        if role_allocations:
            return role_allocations
        evidence_hash = canonical_hash(
            {
                "contribution_id": contribution_id,
                "contributor_id": primary_contributor_id,
                "role": "AUTHOR",
            }
        )
        return [
            ContributionRoleAllocation(
                contributor_id=primary_contributor_id,
                role="AUTHOR",
                allocation_basis_points=BASIS_POINTS,
                evidence_hash=evidence_hash,
            )
        ]

    def _update_group(
        self,
        *,
        repository: EligibleRepository,
        contribution_group_id: str | None,
        contribution_id: str,
        logical_deliverable: str | None,
    ) -> None:
        if contribution_group_id is None:
            return
        existing = self.store.groups.get(contribution_group_id)
        if existing is not None:
            if existing.repository_id != repository.repository_id:
                raise ContributionConflictError("CONTRIBUTION_GROUP_REPOSITORY_MISMATCH")
            if contribution_id in existing.contribution_ids:
                return
            ids = [*existing.contribution_ids, contribution_id]
            payload = {
                "contribution_group_id": existing.contribution_group_id,
                "repository_id": existing.repository_id,
                "logical_deliverable": existing.logical_deliverable,
                "contribution_ids": ids,
            }
            updated = existing.model_copy(update={"contribution_ids": ids, "group_hash": canonical_hash(payload)})
            self.store.put(self.store.groups, contribution_group_id, updated)
            return
        if not logical_deliverable or not logical_deliverable.strip():
            raise ValueError("CONTRIBUTION_GROUP_REQUIRED")
        payload = {
            "contribution_group_id": contribution_group_id,
            "repository_id": repository.repository_id,
            "logical_deliverable": logical_deliverable,
            "contribution_ids": [contribution_id],
        }
        self.store.put(
            self.store.groups,
            contribution_group_id,
            ContributionGroup(**payload, group_hash=canonical_hash(payload)),
        )

    def get_attestation(self, contribution_id: str) -> ContributionAttestation:
        attestation = self.store.attestations.get(contribution_id)
        if attestation is None:
            raise ContributionNotFoundError("CONTRIBUTION_NOT_FOUND")
        return attestation

    def finalize_contribution(self, *, contribution_id: str, current_epoch: int) -> ContributionAttestation:
        current = self.get_attestation(contribution_id)
        if current.eligibility_state == "FINALIZED":
            return current
        if current.eligibility_state == "INELIGIBLE":
            raise ValueError("CONTRIBUTION_NOT_REWARD_ELIGIBLE")
        if current_epoch <= current.challenge_until_epoch:
            raise ValueError("CONTRIBUTION_CHALLENGE_WINDOW_OPEN")
        if any(item.state == "OPEN" for item in self.store.list_challenges(contribution_id)):
            raise ValueError("CONTRIBUTION_ACTIVE_CHALLENGE")
        payload = current.model_dump(
            mode="json",
            exclude={"attestation_hash", "finalized_at", "supersedes_attestation_hash", "eligibility_state"},
        )
        payload.update(
            {
                "eligibility_state": "FINALIZED",
                "finalized_at": self._now_iso(),
                "supersedes_attestation_hash": current.attestation_hash,
            }
        )
        updated = ContributionAttestation(
            **payload,
            attestation_hash=canonical_hash(payload),
        )
        self.store.record_attestation(updated, previous=current)
        return updated

    def open_challenge(
        self,
        *,
        contribution_id: str,
        challenger_id: str,
        challenge_class: str,
        claimed_error: str,
        evidence_root: str,
        challenger_signature: str,
        current_epoch: int,
        challenge_id: str | None = None,
    ) -> ContributionChallenge:
        attestation = self.get_attestation(contribution_id)
        challenger = self.store.contributors.get(challenger_id)
        if challenger is None:
            raise ContributionNotFoundError("CONTRIBUTOR_NOT_REGISTERED")
        if challenger.identity_state != "ACTIVE":
            raise ValueError("CONTRIBUTOR_IDENTITY_NOT_ACTIVE")
        if current_epoch > attestation.challenge_until_epoch:
            raise ValueError("CONTRIBUTION_CHALLENGE_EXPIRED")
        payload = {
            "contribution_id": contribution_id,
            "challenger_id": challenger_id,
            "challenge_class": challenge_class,
            "claimed_error": claimed_error,
            "evidence_root": evidence_root,
            "challenger_signature": challenger_signature,
            "challenge_until_epoch": attestation.challenge_until_epoch,
        }
        resolved_id = challenge_id or canonical_hash(payload)
        challenge_hash = canonical_hash({"challenge_id": resolved_id, **payload})
        existing = self.store.challenges.get(resolved_id)
        if existing is not None:
            if existing.challenge_hash != challenge_hash:
                raise ContributionConflictError("CONTRIBUTION_CHALLENGE_CONFLICT")
            return existing
        challenge = ContributionChallenge(
            challenge_id=resolved_id,
            **payload,
            opened_at=self._now_iso(),
            state="OPEN",
            challenge_hash=challenge_hash,
        )
        self.store.put(self.store.challenges, challenge.challenge_id, challenge)
        updated_payload = attestation.model_dump(
            mode="json",
            exclude={"attestation_hash", "eligibility_state", "supersedes_attestation_hash"},
        )
        updated_payload.update(
            {
                "eligibility_state": "CHALLENGED",
                "supersedes_attestation_hash": attestation.attestation_hash,
            }
        )
        updated = ContributionAttestation(
            **updated_payload,
            attestation_hash=canonical_hash(updated_payload),
        )
        self.store.record_attestation(updated, previous=attestation)
        return challenge

    def resolve_challenge(
        self,
        *,
        challenge_id: str,
        resolution: ChallengeResolution,
        resolved_by: str,
        evidence_root: str,
        resolver_signature: str,
        corrected_factors: ContributionFactorValues | None = None,
        corrected_role_allocations: list[ContributionRoleAllocation] | None = None,
    ) -> ContributionChallengeResolution:
        challenge = self.store.challenges.get(challenge_id)
        if challenge is None:
            raise ContributionNotFoundError("CONTRIBUTION_CHALLENGE_NOT_FOUND")
        if challenge.state != "OPEN":
            if challenge.resolution_id is not None:
                return self.store.challenge_resolutions[challenge.resolution_id]
            raise ValueError("CONTRIBUTION_CHALLENGE_ALREADY_CLOSED")
        attestation = self.get_attestation(challenge.contribution_id)
        resolution_id = canonical_hash(
            {
                "challenge_id": challenge_id,
                "resolution": resolution,
                "resolved_by": resolved_by,
                "evidence_root": evidence_root,
            }
        )
        resolution_payload = {
            "resolution_id": resolution_id,
            "challenge_id": challenge_id,
            "contribution_id": challenge.contribution_id,
            "resolution": resolution,
            "resolved_by": resolved_by,
            "resolved_at": self._now_iso(),
            "evidence_root": evidence_root,
            "resolver_signature": resolver_signature,
        }
        resolution_record = ContributionChallengeResolution(
            **resolution_payload,
            resolution_hash=canonical_hash(resolution_payload),
        )
        updated_payload = attestation.model_dump(
            mode="json",
            exclude={
                "attestation_hash",
                "eligibility_state",
                "supersedes_attestation_hash",
                "factor_values",
                "role_allocations",
                "effective_change_units_milli",
                "size_score_milli",
                "contribution_units_milli",
            },
        )
        updated_payload["supersedes_attestation_hash"] = attestation.attestation_hash
        if resolution == "ATTESTATION_CONFIRMED":
            updated_payload["eligibility_state"] = "ELIGIBLE"
        elif resolution == "CONTRIBUTION_EXCLUDED":
            updated_payload["eligibility_state"] = "INELIGIBLE"
            updated_payload["exclusion_reasons"] = [
                *attestation.exclusion_reasons,
                challenge.challenge_class,
            ]
        elif resolution == "WALLET_BINDING_REQUIRED":
            updated_payload["eligibility_state"] = "ELIGIBLE"
            updated_payload["wallet_state"] = "UNCLAIMED"
        elif resolution == "SECURITY_REVIEW_REQUIRED":
            updated_payload["eligibility_state"] = "CHALLENGED"
        else:
            updated_payload["eligibility_state"] = "ELIGIBLE"
        if resolution == "ATTRIBUTION_CORRECTED":
            if not corrected_role_allocations:
                raise ValueError("CONTRIBUTION_ALLOCATION_INVALID")
            self._validate_role_allocations(corrected_role_allocations)
            updated_payload["role_allocations"] = [item.model_dump(mode="json") for item in corrected_role_allocations]
        else:
            updated_payload["role_allocations"] = [
                item.model_dump(mode="json") for item in attestation.role_allocations
            ]
        if resolution == "SCORE_CORRECTED":
            if corrected_factors is None:
                raise ValueError("CONTRIBUTION_SCORE_INVALID")
            profile = self.store.profiles.get(
                self.store.repositories[attestation.repository_id].contribution_profile_id
            )
            if profile is None:
                raise ContributionNotFoundError("CONTRIBUTION_PROFILE_NOT_FOUND")
            scoring = score_contribution_changes(attestation.file_changes, profile, corrected_factors)
            updated_payload.update(
                {
                    "factor_values": corrected_factors.model_dump(mode="json"),
                    "effective_change_units_milli": scoring["effective_change_units_milli"],
                    "size_score_milli": scoring["size_score_milli"],
                    "contribution_units_milli": scoring["contribution_units_milli"],
                    "scoring_evidence_root": canonical_hash(
                        {
                            "profile_hash": profile.profile_hash,
                            "scoring": scoring,
                            "factors": corrected_factors.model_dump(mode="json"),
                        }
                    ),
                }
            )
        else:
            updated_payload.update(
                {
                    "factor_values": attestation.factor_values.model_dump(mode="json"),
                    "effective_change_units_milli": attestation.effective_change_units_milli,
                    "size_score_milli": attestation.size_score_milli,
                    "contribution_units_milli": attestation.contribution_units_milli,
                }
            )
        updated = ContributionAttestation(
            **updated_payload,
            attestation_hash=canonical_hash(updated_payload),
        )
        closed = challenge.model_copy(update={"state": "RESOLVED", "resolution_id": resolution_id})
        self.store.record_challenge_resolution(closed, resolution_record)
        self.store.record_attestation(updated, previous=attestation)
        return resolution_record

    @staticmethod
    def _validate_role_allocations(
        allocations: list[ContributionRoleAllocation],
    ) -> None:
        total = sum(item.allocation_basis_points for item in allocations)
        if total > BASIS_POINTS or not allocations:
            raise ValueError("CONTRIBUTION_ALLOCATION_INVALID")
        if len({(item.contributor_id, item.role) for item in allocations}) != len(allocations):
            raise ValueError("CONTRIBUTION_ALLOCATION_DUPLICATE")

    def record_maturity(
        self,
        *,
        contribution_id: str,
        stage: int,
        current_epoch: int,
        state: str,
        decision_by: str | None,
        decision_reason: str | None,
        evidence_root: str,
        revert_classification: RevertClassification | None = None,
    ) -> ContributionMaturityRecord:
        attestation = self.get_attestation(contribution_id)
        if stage not in {1, 2}:
            raise ValueError("CONTRIBUTION_MATURITY_STAGE_INVALID")
        due_epoch = attestation.maturity_stage_one_epoch if stage == 1 else attestation.maturity_stage_two_epoch
        if current_epoch < due_epoch:
            raise ValueError("CONTRIBUTION_MATURITY_NOT_REACHED")
        if state != "PENDING" and not decision_by:
            raise ValueError("CONTRIBUTION_MATURITY_DECISION_REQUIRED")
        maturity_id = canonical_hash(
            {
                "contribution_id": contribution_id,
                "stage": stage,
            }
        )
        record = ContributionMaturityRecord(
            maturity_id=maturity_id,
            contribution_id=contribution_id,
            stage=stage,  # type: ignore[arg-type]
            due_epoch=due_epoch,
            state=state,  # type: ignore[arg-type]
            revert_classification=revert_classification,
            decision_reason=decision_reason,
            evidence_root=evidence_root,
            decision_by=decision_by,
            decision_at=self._now_iso(),
            maturity_hash=canonical_hash(
                {
                    "maturity_id": maturity_id,
                    "contribution_id": contribution_id,
                    "stage": stage,
                    "due_epoch": due_epoch,
                    "state": state,
                    "revert_classification": revert_classification,
                    "decision_reason": decision_reason,
                    "evidence_root": evidence_root,
                    "decision_by": decision_by,
                }
            ),
        )
        existing = self.store.maturity_records.get(maturity_id)
        if existing is not None:
            if existing.maturity_hash != record.maturity_hash:
                raise ContributionConflictError("CONTRIBUTION_MATURITY_CONFLICT")
            return existing
        self.store.put(self.store.maturity_records, maturity_id, record)
        return record

    def list_attestations(self) -> list[ContributionAttestation]:
        return self.store.list_attestations()

    def list_repositories(self) -> list[EligibleRepository]:
        return list(self.store.repositories.values())

    def list_contributors(self) -> list[ContributorIdentity]:
        return list(self.store.contributors.values())
