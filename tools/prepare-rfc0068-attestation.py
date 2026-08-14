#!/usr/bin/env python3
"""Prepare a read-only RFC-0068 merge attestation request.

The command verifies a protected-branch merge, derives deterministic file
change counts, verifies the signed Wallet claim from the exact merged commit,
and writes a request for the existing RFC-0068 API. It never writes the
evidence store, signs maintainer authority data, transfers Q, or submits
consensus transactions.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from aidn_hypervisor.contributions.intake import (  # noqa: E402
    build_attestation_authority_signing_payloads,
    build_attestation_request,
    collect_merge_file_changes,
    read_and_verify_wallet_claim,
)
from aidn_hypervisor.contributions.models import ContributionFactorValues, canonical_hash  # noqa: E402
from aidn_hypervisor.contributions.service import (  # noqa: E402
    ContributionAccountingService,
    GitRepositoryMergeVerifier,
)
from aidn_hypervisor.contributions.store import ContributionEvidenceStore  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-path", required=True, type=Path)
    parser.add_argument("--evidence-store", required=True, type=Path)
    parser.add_argument("--repository-id", required=True)
    parser.add_argument("--pull-request-id", required=True)
    parser.add_argument("--merge-commit-hash", required=True)
    parser.add_argument("--base-branch", required=True)
    parser.add_argument("--source-commit-hash")
    parser.add_argument("--diff-base", help="protected-branch diff base; defaults to merge first parent")
    parser.add_argument("--merged-at")
    parser.add_argument("--merge-actor", required=True)
    parser.add_argument("--pull-request-author", required=True)
    parser.add_argument("--primary-contributor-id", required=True)
    parser.add_argument("--contribution-epoch", required=True, type=int)
    parser.add_argument("--contribution-class", required=True)
    parser.add_argument("--source-platform-evidence-hash", required=True)
    parser.add_argument(
        "--attestation-authority",
        action="append",
        metavar="AUTHORITY_ID|ROLE|SIGNATURE",
        help="repeat for an authority with an existing signature",
    )
    parser.add_argument(
        "--attestation-authority-id",
        action="append",
        default=[],
        metavar="AUTHORITY_ID|ROLE",
        help="repeat for an authority whose exact signing payload will be emitted",
    )
    parser.add_argument("--wallet-claim-path", default=".aidn/contributor-wallet.json")
    parser.add_argument("--coauthor", action="append", default=[])
    parser.add_argument("--contribution-group-id")
    parser.add_argument("--logical-deliverable")
    parser.add_argument("--factor-values", type=Path, help="JSON ContributionFactorValues object")
    parser.add_argument("--output", required=True, type=Path)
    return parser


def _authorities(signed_values: list[str], signer_values: list[str]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for value in signed_values:
        parts = value.split("|", 2)
        if len(parts) != 3 or any(not item.strip() for item in parts):
            raise ValueError("--attestation-authority must be AUTHORITY_ID|ROLE|SIGNATURE")
        result.append(
            {
                "authority_id": parts[0].strip(),
                "authority_role": parts[1].strip(),
                "signature": parts[2].strip(),
            }
        )
    for value in signer_values:
        parts = value.split("|", 1)
        if len(parts) != 2 or any(not item.strip() for item in parts):
            raise ValueError("--attestation-authority-id must be AUTHORITY_ID|ROLE")
        result.append(
            {
                "authority_id": parts[0].strip(),
                "authority_role": parts[1].strip(),
                "signature": "PENDING",
            }
        )
    if not result:
        raise ValueError("at least one attestation authority is required")
    if len({item["authority_id"] for item in result}) != len(result):
        raise ValueError("duplicate attestation authority")
    return result


def main() -> int:
    args = _parser().parse_args()
    try:
        verifier = GitRepositoryMergeVerifier()
        git_evidence = verifier.verify(
            args.repository_path,
            merge_commit_hash=args.merge_commit_hash,
            base_branch=args.base_branch,
            allowed_branches={args.base_branch},
            source_commit_hash=args.source_commit_hash,
        )
        diff_base, file_changes = collect_merge_file_changes(
            args.repository_path,
            merge_commit_hash=git_evidence["merge_commit_hash"],
            diff_base=args.diff_base,
            verifier=verifier,
        )
        evidence_store = ContributionEvidenceStore(args.evidence_store)
        wallet_claim = read_and_verify_wallet_claim(
            args.repository_path,
            merge_commit_hash=git_evidence["merge_commit_hash"],
            contributor_id=args.primary_contributor_id,
            evidence_store=evidence_store,
            claim_path=args.wallet_claim_path,
            verifier=verifier,
        )
        merged_at = args.merged_at or verifier._output(
            args.repository_path,
            "show",
            "-s",
            "--format=%cI",
            git_evidence["merge_commit_hash"],
        )
        factor_values = ContributionFactorValues()
        if args.factor_values is not None:
            factor_values = ContributionFactorValues.model_validate_json(
                args.factor_values.read_text(encoding="utf-8")
            )
        authorities = _authorities(args.attestation_authority, args.attestation_authority_id)
        package = build_attestation_request(
            repository_id=args.repository_id,
            pull_request_id=args.pull_request_id,
            merge_commit_hash=git_evidence["merge_commit_hash"],
            base_branch=args.base_branch,
            source_commit_hash=args.source_commit_hash,
            merged_at=merged_at,
            merge_actor=args.merge_actor,
            pull_request_author=args.pull_request_author,
            primary_contributor_id=args.primary_contributor_id,
            contribution_epoch=args.contribution_epoch,
            contribution_class=args.contribution_class,
            source_platform_evidence_hash=args.source_platform_evidence_hash,
            repository_path=args.repository_path,
            attestation_authorities=authorities,
            file_changes=file_changes,
            diff_base=diff_base,
            wallet_claim=wallet_claim,
            wallet_claim_path=args.wallet_claim_path,
            coauthors=args.coauthor,
            contribution_group_id=args.contribution_group_id,
            logical_deliverable=args.logical_deliverable,
            factor_values=factor_values,
            git_evidence=git_evidence,
        )
        package["git_evidence"] = git_evidence
        accounting_service = ContributionAccountingService(
            evidence_store,
            git_verifier=verifier,
        )
        prepared = accounting_service.prepare_attestation_context(
            repository_id=args.repository_id,
            pull_request_id=args.pull_request_id,
            merge_commit_hash=git_evidence["merge_commit_hash"],
            base_branch=args.base_branch,
            source_commit_hash=args.source_commit_hash,
            merged_at=merged_at,
            merge_actor=args.merge_actor,
            pull_request_author=args.pull_request_author,
            primary_contributor_id=args.primary_contributor_id,
            contribution_epoch=args.contribution_epoch,
            contribution_class=args.contribution_class,
            file_changes=file_changes,
            source_platform_evidence_hash=args.source_platform_evidence_hash,
            repository_path=args.repository_path,
            coauthors=args.coauthor,
            contribution_group_id=args.contribution_group_id,
            reward_metadata={"wallet_claim_path": args.wallet_claim_path},
            factor_values=factor_values,
            logical_deliverable=args.logical_deliverable,
        )
        signing_payloads = build_attestation_authority_signing_payloads(
            repository_id=args.repository_id,
            contribution_id=prepared["contribution_id"],
            pull_request_id=args.pull_request_id,
            merge_commit_hash=prepared["git_evidence"]["merge_commit_hash"],
            contribution_epoch=args.contribution_epoch,
            contribution_class=args.contribution_class,
            source_evidence_root=prepared["source_evidence_root"],
            scoring_evidence_root=prepared["scoring_evidence_root"],
            role_allocations=[item.model_dump(mode="json") for item in prepared["allocations"]],
            authorities=authorities,
        )
        signing_context = {
            "contribution_id": prepared["contribution_id"],
            "source_evidence_root": prepared["source_evidence_root"],
            "scoring_evidence_root": prepared["scoring_evidence_root"],
            "role_allocations": [item.model_dump(mode="json") for item in prepared["allocations"]],
            "authority_signing_payloads": signing_payloads,
        }
        package["attestation_context"] = signing_context
        package["attestation_context_hash"] = canonical_hash(signing_context)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(package, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    authority_signatures_pending = any(
        item["signature"] == "PENDING" for item in package["request"]["attestation_authorities"]
    )
    print(
        json.dumps(
            {
                "status": (
                    "ready_for_authority_signing"
                    if authority_signatures_pending
                    else "ready_for_rfc0068_attestation"
                ),
                "evidence_root": package["evidence_root"],
                "merge_commit_hash": package["git_evidence"]["merge_commit_hash"],
                "file_change_count": len(package["request"]["file_changes"]),
                "wallet_claim_hash": package["wallet_claim"]["claim_hash"],
                "authority_signatures_pending": authority_signatures_pending,
                "output": str(args.output),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
