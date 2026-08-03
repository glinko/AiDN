from __future__ import annotations

import subprocess
from datetime import UTC, datetime

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aidn_hypervisor.contributions.models import (
    AttestationAuthority,
    ContributionFactorValues,
    ContributionFileChange,
    ContributorIdentity,
    EligibleRepository,
    PlatformAccount,
    RepositoryContributionProfile,
)
from aidn_hypervisor.contributions.service import (
    ContributionAccountingService,
    GitRepositoryMergeVerifier,
    contributor_wallet_binding_payload,
    score_contribution_changes,
)
from aidn_hypervisor.contributions.store import ContributionEvidenceStore


def _git(repo, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _repository() -> tuple[RepositoryContributionProfile, EligibleRepository]:
    profile = RepositoryContributionProfile(
        profile_id="profile-aidn",
        repository_id="repo-aidn",
        generated_patterns=["src/generated/**"],
        vendor_patterns=["vendor/**"],
    )
    repository = EligibleRepository(
        repository_id="repo-aidn",
        repository_name="AiDN",
        canonical_url="https://github.com/glinko/AiDN",
        organization_id="glinko",
        contribution_profile_id=profile.profile_id,
        repository_hash="sha256:repository",
        authorization_signature="ed25519:repository-authority",
    )
    return profile, repository


def _contributor() -> ContributorIdentity:
    return ContributorIdentity(
        contributor_id="contributor-alice",
        source_platform_accounts=[PlatformAccount(platform="github", account_id="alice", handle="alice")],
        valid_from="2026-08-01T00:00:00+00:00",
        identity_hash="sha256:identity",
        contributor_signature="ed25519:identity-attestation",
    )


def _service(tmp_path, *, now=None) -> ContributionAccountingService:
    profile, repository = _repository()
    service = ContributionAccountingService(
        ContributionEvidenceStore(tmp_path / "contribution-evidence.json"),
        now=now,
    )
    service.register_profile(profile)
    service.register_repository(repository)
    service.register_contributor(_contributor())
    return service


def _git_repository(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "alice@example.test")
    _git(repo, "config", "user.name", "Alice")
    (repo / "src").mkdir()
    (repo / "src" / "feature.py").write_text("return 1\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial")
    (repo / "src" / "feature.py").write_text("return 1\nreturn 2\nreturn 3\n", encoding="utf-8")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_feature.py").write_text("def test_feature(): pass\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "feature")
    return repo, _git(repo, "rev-parse", "HEAD"), _git(repo, "rev-parse", "HEAD^")


def test_scoring_is_fixed_point_and_excludes_generated_vendor_and_lockfiles():
    profile, _ = _repository()
    changes = [
        ContributionFileChange(path="src/a.py", added_lines=10, deleted_lines=2),
        ContributionFileChange(path="tests/test_a.py", added_lines=10),
        ContributionFileChange(path="docs/guide.md", added_lines=10),
        ContributionFileChange(path="src/generated/api.py", added_lines=1000),
        ContributionFileChange(path="vendor/lib.py", added_lines=1000),
        ContributionFileChange(path="uv.lock", added_lines=1000),
    ]
    factors = ContributionFactorValues()
    first = score_contribution_changes(changes, profile, factors)
    second = score_contribution_changes(reversed(changes), profile, factors)

    assert first == second
    assert first["effective_change_units_milli"] > 0
    assert first["size_score_milli"] <= profile.maximum_automatic_size_score_milli
    excluded_paths = {"src/generated/api.py", "vendor/lib.py", "uv.lock"}
    assert all(
        item["effective_change_units_milli"] == 0 for item in first["file_evidence"] if item["path"] in excluded_paths
    )
    assert first["contribution_units_milli"] == first["size_score_milli"]


def test_git_verifier_requires_protected_branch_ancestry(tmp_path):
    repo, merge_commit, source_commit = _git_repository(tmp_path)
    evidence = GitRepositoryMergeVerifier().verify(
        repo,
        merge_commit_hash=merge_commit,
        source_commit_hash=source_commit,
        base_branch="main",
        allowed_branches={"main"},
    )
    assert evidence["verification_method"] == "LOCAL_GIT_ANCESTOR"
    assert evidence["merge_commit_hash"] == merge_commit
    with pytest.raises(ValueError, match="CONTRIBUTION_BRANCH_NOT_ELIGIBLE"):
        GitRepositoryMergeVerifier().verify(
            repo,
            merge_commit_hash=merge_commit,
            base_branch="feature",
            allowed_branches={"main"},
        )


def test_wallet_binding_is_signed_and_one_use(tmp_path):
    service = _service(tmp_path)
    private_key = Ed25519PrivateKey.generate()
    public_key = (
        "ed25519:"
        + private_key.public_key()
        .public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        .hex()
    )
    challenge = service.issue_wallet_binding_challenge(
        contributor_id="contributor-alice",
        source_platform_account="github:alice",
        wallet_address="q1alice",
    )
    payload = contributor_wallet_binding_payload(
        contributor_id=challenge.contributor_id,
        source_platform_account=challenge.source_platform_account,
        wallet_address=challenge.wallet_address,
        wallet_public_key=public_key,
        challenge_id=challenge.challenge_id,
        challenge_hash=challenge.challenge_hash,
        binding_version=1,
    )
    signature = "ed25519:" + private_key.sign(payload).hex()
    binding = service.bind_wallet(
        challenge_id=challenge.challenge_id,
        wallet_public_key=public_key,
        wallet_signature=signature,
        source_platform_confirmation_hash="sha256:github-confirmation",
    )
    assert binding.wallet_address == "q1alice"
    assert service.list_contributors()[0].current_wallet_address == "q1alice"
    assert (
        service.bind_wallet(
            challenge_id=challenge.challenge_id,
            wallet_public_key=public_key,
            wallet_signature=signature,
            source_platform_confirmation_hash="sha256:github-confirmation",
        )
        == binding
    )


def test_attestation_challenge_finalization_maturity_and_persistence(tmp_path):
    clock = [datetime(2026, 8, 1, tzinfo=UTC)]
    service = _service(tmp_path, now=lambda: clock[0])
    repo, merge_commit, source_commit = _git_repository(tmp_path)
    attestation = service.attest_merge(
        repository_id="repo-aidn",
        pull_request_id="42",
        merge_commit_hash=merge_commit,
        source_commit_hash=source_commit,
        base_branch="main",
        merged_at="2026-08-01T12:00:00+00:00",
        merge_actor="maintainer",
        pull_request_author="github:alice",
        primary_contributor_id="contributor-alice",
        contribution_epoch=0,
        contribution_class="CODE",
        file_changes=[
            ContributionFileChange(path="src/feature.py", added_lines=2),
            ContributionFileChange(path="tests/test_feature.py", added_lines=1),
        ],
        attestation_authorities=[
            AttestationAuthority(
                authority_id="maintainer-1",
                authority_role="maintainer",
                signature="ed25519:maintainer",
            )
        ],
        source_platform_evidence_hash="sha256:github-event",
        repository_path=repo,
    )
    assert attestation.eligibility_state == "ELIGIBLE"
    assert attestation.wallet_state == "UNCLAIMED"
    assert attestation.challenge_until_epoch == 1
    challenge = service.open_challenge(
        contribution_id=attestation.contribution_id,
        challenger_id="contributor-alice",
        challenge_class="DIMENSION_VALUE",
        claimed_error="test evidence challenge",
        evidence_root="sha256:challenge-evidence",
        challenger_signature="ed25519:challenge",
        current_epoch=1,
    )
    with pytest.raises(ValueError, match="CONTRIBUTION_ACTIVE_CHALLENGE"):
        service.finalize_contribution(
            contribution_id=attestation.contribution_id,
            current_epoch=2,
        )
    service.resolve_challenge(
        challenge_id=challenge.challenge_id,
        resolution="ATTESTATION_CONFIRMED",
        resolved_by="maintainer-1",
        evidence_root="sha256:resolution",
        resolver_signature="ed25519:resolution",
    )
    finalized = service.finalize_contribution(
        contribution_id=attestation.contribution_id,
        current_epoch=2,
    )
    assert finalized.eligibility_state == "FINALIZED"
    maturity = service.record_maturity(
        contribution_id=attestation.contribution_id,
        stage=1,
        current_epoch=4,
        state="CONFIRMED",
        decision_by="maintainer-1",
        decision_reason="survived the first maturity window",
        evidence_root="sha256:maturity",
    )
    assert maturity.due_epoch == 4

    restored = ContributionAccountingService(ContributionEvidenceStore(tmp_path / "contribution-evidence.json"))
    assert restored.get_attestation(attestation.contribution_id).attestation_hash == finalized.attestation_hash
    assert restored.store.list_maturity(attestation.contribution_id)[0].maturity_hash == maturity.maturity_hash
