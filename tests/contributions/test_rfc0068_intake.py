from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aidn_hypervisor.contributions.intake import (
    build_attestation_authority_signing_payloads,
    build_attestation_request,
    collect_merge_file_changes,
    read_and_verify_wallet_claim,
    validate_attestation_request_package,
)
from aidn_hypervisor.contributions.models import (
    ContributionFileChange,
    ContributorIdentity,
    ContributorWalletBinding,
    ContributorWalletClaim,
    PlatformAccount,
)
from aidn_hypervisor.contributions.service import (
    contribution_attestation_authorization_payload,
    contributor_wallet_claim_payload,
    verify_attestation_authority_signatures,
)
from aidn_hypervisor.contributions.store import ContributionEvidenceStore


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def test_intake_derives_first_parent_diff_and_verifies_exact_wallet_claim(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "contributor@example.test")
    _git(repo, "config", "user.name", "Contributor")
    (repo / "src").mkdir()
    (repo / "src" / "feature.py").write_text("return 1\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "base")
    private_key = Ed25519PrivateKey.generate()
    public_key = "ed25519:" + private_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    ).hex()
    claim_template = ContributorWalletClaim(
        contributor_id="contributor-real",
        source_platform_account="github:real",
        wallet_address="q1real",
        wallet_public_key=public_key,
        wallet_signature="ed25519:pending",
        claim_hash="sha256:pending",
    )
    signature = "ed25519:" + private_key.sign(contributor_wallet_claim_payload(claim_template)).hex()
    claim = claim_template.model_copy(update={"wallet_signature": signature})
    claim = claim.model_copy(update={"claim_hash": claim.expected_claim_hash()})
    (repo / ".aidn").mkdir()
    (repo / ".aidn" / "contributor-wallet.json").write_text(
        json.dumps(claim.model_dump(mode="json")), encoding="utf-8"
    )
    (repo / "src" / "feature.py").write_text("return 1\nreturn 2\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "accepted contribution")
    merge_commit = _git(repo, "rev-parse", "HEAD")

    store = ContributionEvidenceStore()
    store.put(
        store.contributors,
        "contributor-real",
        ContributorIdentity(
            contributor_id="contributor-real",
            source_platform_accounts=[
                PlatformAccount(platform="github", account_id="real", handle="real")
            ],
            valid_from="2026-08-01T00:00:00Z",
            identity_hash="sha256:identity",
            contributor_signature="ed25519:identity",
        ),
    )
    store.put(
        store.wallet_bindings,
        "binding-real",
        ContributorWalletBinding(
            binding_id="binding-real",
            contributor_id="contributor-real",
            source_platform_account="github:real",
            wallet_address="q1real",
            wallet_public_key=public_key,
            challenge_id="challenge-real",
            challenge_hash="sha256:challenge",
            wallet_signature="ed25519:binding",
            source_platform_confirmation_hash="sha256:source-confirmation",
            valid_from="2026-08-01T00:00:00Z",
            binding_version=1,
            binding_hash="sha256:binding",
        ),
    )
    diff_base, changes = collect_merge_file_changes(repo, merge_commit_hash=merge_commit)
    verified_claim = read_and_verify_wallet_claim(
        repo,
        merge_commit_hash=merge_commit,
        contributor_id="contributor-real",
        evidence_store=store,
    )

    assert diff_base == _git(repo, "rev-parse", f"{merge_commit}^1")
    assert {item.path for item in changes} == {".aidn/contributor-wallet.json", "src/feature.py"}
    assert verified_claim.wallet_address == "q1real"


def test_attestation_request_root_binds_git_ancestry_evidence(tmp_path: Path) -> None:
    claim = ContributorWalletClaim(
        contributor_id="contributor-real",
        source_platform_account="github:real",
        wallet_address="q1real",
        wallet_public_key="ed25519:" + "00" * 32,
        wallet_signature="ed25519:" + "00" * 64,
        claim_hash="sha256:" + "00" * 32,
    )
    request = build_attestation_request(
        repository_id="repo",
        pull_request_id="1",
        merge_commit_hash="a" * 40,
        base_branch="main",
        source_commit_hash=None,
        merged_at="2026-08-13T00:00:00Z",
        merge_actor="github:maintainer",
        pull_request_author="github:real",
        primary_contributor_id="contributor-real",
        contribution_epoch=1,
        contribution_class="CODE",
        source_platform_evidence_hash="sha256:" + "11" * 32,
        repository_path=tmp_path,
        attestation_authorities=[
            {"authority_id": "maintainer-1", "authority_role": "maintainer", "signature": "sig"}
        ],
        file_changes=[],
        diff_base="b" * 40,
        wallet_claim=claim,
        wallet_claim_path=".aidn/contributor-wallet.json",
        git_evidence={
            "merge_commit_hash": "a" * 40,
            "protected_branch_tip": "c" * 40,
            "verification_method": "LOCAL_GIT_ANCESTOR",
        },
    )

    assert request["evidence"]["git_evidence"]["protected_branch_tip"] == "c" * 40
    assert request["evidence_root"].startswith("sha256:")


def test_prepare_tool_rejects_non_commitment_source_evidence(tmp_path: Path) -> None:
    # The read-only intake validates the evidence reference before producing a
    # request, so a UI/Forge placeholder cannot silently enter RFC-0068.
    from aidn_hypervisor.contributions.intake import build_attestation_request
    from aidn_hypervisor.contributions.models import ContributionFileChange

    claim = ContributorWalletClaim(
        contributor_id="c",
        source_platform_account="github:c",
        wallet_address="q1c",
        wallet_public_key="ed25519:" + "00" * 32,
        wallet_signature="ed25519:" + "00" * 64,
        claim_hash="sha256:" + "00" * 32,
    )
    try:
        build_attestation_request(
            repository_id="repo",
            pull_request_id="1",
            merge_commit_hash="a" * 40,
            base_branch="main",
            source_commit_hash=None,
            merged_at="2026-08-13T00:00:00Z",
            merge_actor="maintainer",
            pull_request_author="github:c",
            primary_contributor_id="c",
            contribution_epoch=1,
            contribution_class="CODE",
            source_platform_evidence_hash="github-event",
            repository_path=tmp_path,
            attestation_authorities=[{"authority_id": "m", "authority_role": "maintainer", "signature": "sig"}],
            file_changes=[ContributionFileChange(path="src/a.py", added_lines=1)],
            diff_base="b" * 40,
            wallet_claim=claim,
            wallet_claim_path=".aidn/contributor-wallet.json",
        )
    except ValueError as error:
        assert "source_platform_evidence_hash" in str(error)
    else:
        raise AssertionError("invalid source evidence hash was accepted")


def test_production_authority_signatures_use_repository_key_registry() -> None:
    from aidn_hypervisor.contributions.models import AttestationAuthority, EligibleRepository

    private_key = Ed25519PrivateKey.generate()
    public_key = "ed25519:" + private_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    ).hex()
    repository = EligibleRepository(
        repository_id="repo",
        repository_name="AiDN",
        canonical_url="https://github.com/glinko/AiDN",
        organization_id="glinko",
        contribution_profile_id="profile",
        attestation_authority_ids=["maintainer-1"],
        attestation_authority_public_keys={"maintainer-1": public_key},
        repository_hash="sha256:repo",
        authorization_signature="ed25519:repository",
    )
    allocations = []
    payload = contribution_attestation_authorization_payload(
        repository_id="repo",
        contribution_id="sha256:" + "01" * 32,
        pull_request_id="1",
        merge_commit_hash="a" * 40,
        contribution_epoch=1,
        contribution_class="CODE",
        source_evidence_root="sha256:" + "02" * 32,
        scoring_evidence_root="sha256:" + "03" * 32,
        role_allocations=allocations,
        authority_id="maintainer-1",
    )
    signature = "ed25519:" + private_key.sign(payload).hex()
    verify_attestation_authority_signatures(
        repository=repository,
        contribution_id="sha256:" + "01" * 32,
        pull_request_id="1",
        merge_commit_hash="a" * 40,
        contribution_epoch=1,
        contribution_class="CODE",
        source_evidence_root="sha256:" + "02" * 32,
        scoring_evidence_root="sha256:" + "03" * 32,
        role_allocations=allocations,
        authorities=[
            AttestationAuthority(
                authority_id="maintainer-1",
                authority_role="maintainer",
                signature=signature,
            )
        ],
    )


def test_authority_signing_payloads_are_deterministic_and_keyed_by_authority() -> None:
    authorities = [
        {"authority_id": "maintainer-1", "authority_role": "maintainer", "signature": "PENDING"},
        {"authority_id": "maintainer-2", "authority_role": "maintainer", "signature": "PENDING"},
    ]
    allocations = [
        {
            "contributor_id": "contributor-real",
            "role": "AUTHOR",
            "allocation_basis_points": 10_000,
            "evidence_hash": "sha256:" + "04" * 32,
        }
    ]
    first = build_attestation_authority_signing_payloads(
        repository_id="repo",
        contribution_id="sha256:" + "01" * 32,
        pull_request_id="1",
        merge_commit_hash="a" * 40,
        contribution_epoch=1,
        contribution_class="CODE",
        source_evidence_root="sha256:" + "02" * 32,
        scoring_evidence_root="sha256:" + "03" * 32,
        role_allocations=allocations,
        authorities=authorities,
    )
    second = build_attestation_authority_signing_payloads(
        repository_id="repo",
        contribution_id="sha256:" + "01" * 32,
        pull_request_id="1",
        merge_commit_hash="a" * 40,
        contribution_epoch=1,
        contribution_class="CODE",
        source_evidence_root="sha256:" + "02" * 32,
        scoring_evidence_root="sha256:" + "03" * 32,
        role_allocations=allocations,
        authorities=authorities,
    )

    assert first == second
    assert set(first) == {"maintainer-1", "maintainer-2"}
    assert all(item["encoding"] == "utf-8" for item in first.values())
    assert first["maintainer-1"]["payload_hex"] != first["maintainer-2"]["payload_hex"]


def test_signed_intake_package_validates_request_evidence_and_root() -> None:
    signature = "ed25519:" + "ab" * 64
    authority = {"authority_id": "maintainer-1", "authority_role": "maintainer", "signature": signature}
    claim = ContributorWalletClaim(
        contributor_id="contributor-real",
        source_platform_account="github:real",
        wallet_address="q1real",
        wallet_public_key="ed25519:" + "00" * 32,
        wallet_signature="ed25519:" + "00" * 64,
        claim_hash="sha256:" + "00" * 32,
    )
    package = build_attestation_request(
        repository_id="repo",
        pull_request_id="1",
        merge_commit_hash="a" * 40,
        base_branch="main",
        source_commit_hash=None,
        merged_at="2026-08-13T00:00:00Z",
        merge_actor="github:maintainer",
        pull_request_author="github:real",
        primary_contributor_id="contributor-real",
        contribution_epoch=1,
        contribution_class="CODE",
        source_platform_evidence_hash="sha256:" + "11" * 32,
        repository_path=".",
        attestation_authorities=[authority],
        file_changes=[ContributionFileChange(path="src/a.py", added_lines=1)],
        diff_base="b" * 40,
        wallet_claim=claim,
        wallet_claim_path=".aidn/contributor-wallet.json",
        git_evidence={
            "merge_commit_hash": "a" * 40,
            "protected_branch_tip": "c" * 40,
            "verification_method": "LOCAL_GIT_ANCESTOR",
        },
    )
    package["mode"] = "SIGNED_REQUEST_READY_FOR_SUBMISSION"
    validated = validate_attestation_request_package(package)

    assert validated["merge_commit_hash"] == "a" * 40
    package["evidence_root"] = "sha256:" + "ff" * 32
    with pytest.raises(ValueError, match="CONTRIBUTION_INTAKE_EVIDENCE_ROOT_MISMATCH"):
        validate_attestation_request_package(package)
