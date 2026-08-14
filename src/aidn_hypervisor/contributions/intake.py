"""Read-only RFC-0068 merge evidence preparation.

This module turns an exact protected-branch merge into an attestation request,
but deliberately stops before writing the evidence store or touching the
Ledger.  A maintainer still has to submit the request through the RFC-0068
service and provide the repository-specific authority evidence.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from aidn_hypervisor.contributions.models import (
    ContributionFactorValues,
    ContributionFileChange,
    ContributionRoleAllocation,
    ContributorWalletClaim,
    canonical_hash,
)
from aidn_hypervisor.contributions.service import (
    GitRepositoryMergeVerifier,
    _verify_wallet_signature,
    contribution_attestation_authorization_payload,
    contributor_wallet_claim_payload,
)
from aidn_hypervisor.contributions.store import ContributionEvidenceStore

_COMMITMENT_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_AUTHORITY_SIGNATURE_RE = re.compile(r"^ed25519:[0-9a-f]{128}$")


def _require_commitment(value: str, *, label: str) -> str:
    normalized = value.strip().lower()
    if not _COMMITMENT_RE.fullmatch(normalized):
        raise ValueError(f"{label} must be sha256:<64 lowercase hex characters>")
    return normalized


def _parse_numstat(value: str) -> tuple[int, int, bool]:
    try:
        added, deleted = value.split("\t", 1)
    except ValueError as error:
        raise ValueError("CONTRIBUTION_DIFF_INVALID") from error
    if added == "-" or deleted == "-":
        return 0, 0, True
    try:
        return int(added), int(deleted), False
    except ValueError as error:
        raise ValueError("CONTRIBUTION_DIFF_INVALID") from error


def collect_merge_file_changes(
    repository_path: Path | str,
    *,
    merge_commit_hash: str,
    diff_base: str | None = None,
    verifier: GitRepositoryMergeVerifier | None = None,
) -> tuple[str, list[ContributionFileChange]]:
    """Collect deterministic changed-file counts from one exact merge.

    The default diff base is the first parent of the merge commit.  This is
    the protected-branch side of a normal merge and avoids accidentally
    scoring a source branch against itself.  Squash/fast-forward workflows
    should pass their explicit protected-branch base.
    """

    git = verifier or GitRepositoryMergeVerifier()
    repository = Path(repository_path)
    git._validate_commit(merge_commit_hash)
    resolved_merge = git._output(repository, "rev-parse", "--verify", f"{merge_commit_hash}^{{commit}}")
    resolved_base = (
        git._output(repository, "rev-parse", "--verify", f"{diff_base}^{{commit}}")
        if diff_base is not None
        else git._output(repository, "rev-parse", "--verify", f"{resolved_merge}^1")
    )
    output = git._output(
        repository,
        "diff",
        "--no-renames",
        "--numstat",
        resolved_base,
        resolved_merge,
        "--",
    )
    changes: list[ContributionFileChange] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        try:
            added, deleted, path = line.split("\t", 2)
        except ValueError as error:
            raise ValueError("CONTRIBUTION_DIFF_INVALID") from error
        added, deleted, binary = _parse_numstat(f"{added}\t{deleted}")
        changes.append(
            ContributionFileChange(
                path=path.replace("\\", "/"),
                added_lines=added,
                deleted_lines=deleted,
                binary=binary,
            )
        )
    if not changes:
        raise ValueError("CONTRIBUTION_DIFF_EMPTY")
    return resolved_base, sorted(changes, key=lambda item: item.path)


def read_and_verify_wallet_claim(
    repository_path: Path | str,
    *,
    merge_commit_hash: str,
    contributor_id: str,
    evidence_store: ContributionEvidenceStore,
    claim_path: str = ".aidn/contributor-wallet.json",
    verifier: GitRepositoryMergeVerifier | None = None,
) -> ContributorWalletClaim:
    """Verify the merged claim and its historical registered Wallet binding."""

    git = verifier or GitRepositoryMergeVerifier()
    raw = git.read_file_at_commit(
        repository_path,
        commit_hash=merge_commit_hash,
        path=claim_path,
    )
    if raw is None:
        raise ValueError("CONTRIBUTION_WALLET_CLAIM_MISSING")
    try:
        claim = ContributorWalletClaim.model_validate(json.loads(raw))
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("CONTRIBUTION_WALLET_CLAIM_INVALID") from error
    if claim.contributor_id != contributor_id:
        raise ValueError("CONTRIBUTION_WALLET_CLAIM_CONTRIBUTOR_MISMATCH")
    if claim.claim_hash != claim.expected_claim_hash():
        raise ValueError("CONTRIBUTION_WALLET_CLAIM_HASH_INVALID")
    _verify_wallet_signature(
        public_key=claim.wallet_public_key,
        signature=claim.wallet_signature,
        payload=contributor_wallet_claim_payload(claim),
    )
    binding = next(
        (
            item
            for item in evidence_store.wallet_bindings.values()
            if item.contributor_id == claim.contributor_id
            and item.source_platform_account == claim.source_platform_account
            and item.wallet_address == claim.wallet_address
            and item.wallet_public_key == claim.wallet_public_key
        ),
        None,
    )
    if binding is None:
        raise ValueError("CONTRIBUTION_WALLET_BINDING_REQUIRED")
    if claim.binding_id is not None and claim.binding_id != binding.binding_id:
        raise ValueError("CONTRIBUTION_WALLET_CLAIM_BINDING_MISMATCH")
    if claim.binding_hash is not None and claim.binding_hash != binding.binding_hash:
        raise ValueError("CONTRIBUTION_WALLET_CLAIM_BINDING_MISMATCH")
    return claim


def build_attestation_request(
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
    contribution_class: str,
    source_platform_evidence_hash: str,
    repository_path: Path | str,
    attestation_authorities: list[dict[str, str]],
    file_changes: list[ContributionFileChange],
    diff_base: str,
    wallet_claim: ContributorWalletClaim,
    wallet_claim_path: str,
    coauthors: list[str] | None = None,
    contribution_group_id: str | None = None,
    logical_deliverable: str | None = None,
    factor_values: ContributionFactorValues | None = None,
    git_evidence: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build the JSON accepted by the RFC-0068 attestation endpoint."""

    evidence = {
        "repository_id": repository_id,
        "pull_request_id": pull_request_id,
        "merge_commit_hash": merge_commit_hash,
        "base_branch": base_branch,
        "source_commit_hash": source_commit_hash,
        "merged_at": merged_at,
        "merge_actor": merge_actor,
        "pull_request_author": pull_request_author,
        "primary_contributor_id": primary_contributor_id,
        "contribution_epoch": contribution_epoch,
        "contribution_class": contribution_class,
        "source_platform_evidence_hash": _require_commitment(
            source_platform_evidence_hash,
            label="source_platform_evidence_hash",
        ),
        "repository_path": str(Path(repository_path).resolve()),
        "attestation_authorities": attestation_authorities,
        "file_changes": [item.model_dump(mode="json") for item in file_changes],
        "diff_base": diff_base,
        "wallet_claim_path": wallet_claim_path,
        "wallet_claim_hash": wallet_claim.claim_hash,
        "coauthors": list(coauthors or []),
        "contribution_group_id": contribution_group_id,
        "logical_deliverable": logical_deliverable,
        "factor_values": (factor_values or ContributionFactorValues()).model_dump(mode="json"),
        "git_evidence": dict(git_evidence or {}),
    }
    request = {
        "repository_id": repository_id,
        "pull_request_id": pull_request_id,
        "merge_commit_hash": merge_commit_hash,
        "base_branch": base_branch,
        "source_commit_hash": source_commit_hash,
        "merged_at": merged_at,
        "merge_actor": merge_actor,
        "pull_request_author": pull_request_author,
        "primary_contributor_id": primary_contributor_id,
        "contribution_epoch": contribution_epoch,
        "contribution_class": contribution_class,
        "file_changes": [item.model_dump(mode="json") for item in file_changes],
        "attestation_authorities": attestation_authorities,
        "source_platform_evidence_hash": _require_commitment(
            source_platform_evidence_hash,
            label="source_platform_evidence_hash",
        ),
        "repository_path": str(Path(repository_path).resolve()),
        "coauthors": list(coauthors or []),
        "contribution_group_id": contribution_group_id,
        "reward_metadata": {"wallet_claim_path": wallet_claim_path},
        "factor_values": (factor_values or ContributionFactorValues()).model_dump(mode="json"),
        "logical_deliverable": logical_deliverable,
    }
    return {
        "schema_version": "aidn.rfc-0068-attestation-intake.v1",
        "mode": "READ_ONLY_PREPARED_REQUEST",
        "request": request,
        "wallet_claim": wallet_claim.model_dump(mode="json"),
        "evidence": evidence,
        "evidence_root": canonical_hash(evidence),
    }


def build_attestation_authority_signing_payloads(
    *,
    repository_id: str,
    contribution_id: str,
    pull_request_id: str,
    merge_commit_hash: str,
    contribution_epoch: int,
    contribution_class: str,
    source_evidence_root: str,
    scoring_evidence_root: str,
    role_allocations: list[dict[str, Any]],
    authorities: list[dict[str, str]],
) -> dict[str, dict[str, str]]:
    """Expose exact authority-signing bytes without handling private keys."""

    allocations = [ContributionRoleAllocation.model_validate(item) for item in role_allocations]
    result: dict[str, dict[str, str]] = {}
    for authority in authorities:
        authority_id = authority["authority_id"]
        payload = contribution_attestation_authorization_payload(
            repository_id=repository_id,
            contribution_id=contribution_id,
            pull_request_id=pull_request_id,
            merge_commit_hash=merge_commit_hash,
            contribution_epoch=contribution_epoch,
            contribution_class=contribution_class,
            source_evidence_root=source_evidence_root,
            scoring_evidence_root=scoring_evidence_root,
            role_allocations=allocations,
            authority_id=authority_id,
        )
        result[authority_id] = {
            "encoding": "utf-8",
            "payload_hex": payload.hex(),
        }
    return result


def validate_attestation_request_package(package: dict[str, Any]) -> dict[str, Any]:
    """Validate the transport envelope before the service replays evidence."""

    if package.get("schema_version") != "aidn.rfc-0068-attestation-intake.v1":
        raise ValueError("CONTRIBUTION_INTAKE_SCHEMA_INVALID")
    if package.get("mode") != "SIGNED_REQUEST_READY_FOR_SUBMISSION":
        raise ValueError("REPOSITORY_ATTESTATION_SIGNATURES_PENDING")
    request = package.get("request")
    evidence = package.get("evidence")
    if not isinstance(request, dict) or not isinstance(evidence, dict):
        raise ValueError("CONTRIBUTION_INTAKE_PACKAGE_INVALID")
    if package.get("evidence_root") != canonical_hash(evidence):
        raise ValueError("CONTRIBUTION_INTAKE_EVIDENCE_ROOT_MISMATCH")
    request_authorities = request.get("attestation_authorities")
    evidence_authorities = evidence.get("attestation_authorities")
    if not isinstance(request_authorities, list) or request_authorities != evidence_authorities:
        raise ValueError("CONTRIBUTION_INTAKE_AUTHORITY_EVIDENCE_MISMATCH")
    authority_ids: set[str] = set()
    for authority in request_authorities:
        if not isinstance(authority, dict):
            raise ValueError("CONTRIBUTION_INTAKE_PACKAGE_INVALID")
        authority_id = authority.get("authority_id")
        signature = authority.get("signature")
        if not isinstance(authority_id, str) or authority_id in authority_ids:
            raise ValueError("REPOSITORY_ATTESTATION_AUTHORITY_DUPLICATE")
        if not isinstance(signature, str) or not _AUTHORITY_SIGNATURE_RE.fullmatch(signature):
            raise ValueError("REPOSITORY_ATTESTATION_SIGNATURE_INVALID")
        authority_ids.add(authority_id)
    for field in (
        "repository_id",
        "pull_request_id",
        "merge_commit_hash",
        "base_branch",
        "source_commit_hash",
        "merged_at",
        "merge_actor",
        "pull_request_author",
        "contribution_epoch",
        "contribution_class",
        "primary_contributor_id",
        "source_platform_evidence_hash",
        "file_changes",
        "coauthors",
        "contribution_group_id",
        "factor_values",
        "logical_deliverable",
        "repository_path",
    ):
        if request.get(field) != evidence.get(field):
            raise ValueError("CONTRIBUTION_INTAKE_REQUEST_EVIDENCE_MISMATCH")
    metadata = request.get("reward_metadata")
    if not isinstance(metadata, dict) or metadata.get("wallet_claim_path") != evidence.get("wallet_claim_path"):
        raise ValueError("CONTRIBUTION_INTAKE_WALLET_PATH_MISMATCH")
    wallet_claim = package.get("wallet_claim")
    if not isinstance(wallet_claim, dict) or wallet_claim.get("claim_hash") != evidence.get("wallet_claim_hash"):
        raise ValueError("CONTRIBUTION_INTAKE_WALLET_CLAIM_MISMATCH")
    context = package.get("attestation_context")
    context_hash = package.get("attestation_context_hash")
    if context is not None:
        if not isinstance(context, dict) or context_hash != canonical_hash(context):
            raise ValueError("CONTRIBUTION_INTAKE_CONTEXT_HASH_MISMATCH")
    return request


__all__ = [
    "build_attestation_request",
    "build_attestation_authority_signing_payloads",
    "collect_merge_file_changes",
    "read_and_verify_wallet_claim",
    "validate_attestation_request_package",
]
