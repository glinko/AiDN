#!/usr/bin/env python3
"""Create and attest one real controlled-localnet contribution.

By default this acceptance runner uses a disposable fixture Wallet.  A
controlled-localnet profile may instead supply an external contributor Wallet
key and its already verified public identity.  It creates a real protected
``main`` merge commit, records the Wallet binding, prepares the RFC-0068
intake package, signs it with the configured localnet authority quorum, and
finalizes the contribution after the challenge boundary.  It does not submit
Q or touch consensus; the resulting evidence store and pool input are passed
to the ECO-0007 production batch builder and executor.

Private contributor and authority keys are read from external paths and are
never copied into the repository or printed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aidn_hypervisor.consensus.epoch_transition import load_protocol_authority_private_key  # noqa: E402
from aidn_hypervisor.contributions.intake import (  # noqa: E402
    build_attestation_authority_signing_payloads,
    build_attestation_request,
    collect_merge_file_changes,
    read_and_verify_wallet_claim,
    validate_attestation_request_package,
)
from aidn_hypervisor.contributions.models import (  # noqa: E402
    ContributionFactorValues,
    ContributorIdentity,
    ContributorWalletClaim,
    EligibleRepository,
    PlatformAccount,
    RepositoryContributionProfile,
    canonical_hash,
)
from aidn_hypervisor.contributions.service import (  # noqa: E402
    ContributionAccountingService,
    contributor_wallet_binding_payload,
    contributor_wallet_claim_payload,
)
from aidn_hypervisor.contributions.store import ContributionEvidenceStore  # noqa: E402
from aidn_hypervisor.contributions.wallet_profile import (  # noqa: E402
    load_verified_contributor_wallet_key,
    public_key_for_private_key,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-source", type=Path, default=ROOT)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--evidence-store", required=True, type=Path)
    parser.add_argument("--authority-policy", required=True, type=Path)
    parser.add_argument("--authority-key-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--pool-input-output", required=True, type=Path)
    parser.add_argument("--contribution-epoch", type=int, default=1)
    parser.add_argument("--repository-id", default="controlled-localnet-aidn")
    parser.add_argument(
        "--source-platform-account",
        default="github:controlled-localnet-contributor",
    )
    parser.add_argument(
        "--wallet-address",
        help="use this existing contributor Wallet instead of an ephemeral fixture Wallet",
    )
    parser.add_argument(
        "--wallet-public-key",
        help="canonical ed25519 public key for --wallet-address",
    )
    parser.add_argument(
        "--wallet-private-key-file",
        type=Path,
        help="external PEM or 32-byte hex seed for --wallet-address; never store it in Git",
    )
    parser.add_argument(
        "--wallet-profile",
        type=Path,
        help="public JSON profile supplying the Wallet address and public key",
    )
    return parser


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _wallet_profile(path: Path | None, policy: dict[str, Any]) -> dict[str, str]:
    if path is None:
        return {}
    profile = _object(path)
    wallet_address = profile.get("wallet_address")
    wallet_public_key = profile.get("wallet_public_key")
    if not isinstance(wallet_address, str) or not wallet_address.strip():
        raise ValueError("Wallet profile must contain a non-empty wallet_address")
    if not isinstance(wallet_public_key, str) or not wallet_public_key.startswith("ed25519:"):
        raise ValueError("Wallet profile must contain an ed25519 wallet_public_key")
    profile_policy_hash = profile.get("authority_policy_hash")
    if profile_policy_hash is not None and profile_policy_hash != policy.get("policy_hash"):
        raise ValueError("Wallet profile authority policy hash does not match the supplied policy")
    return {
        "wallet_address": wallet_address,
        "wallet_public_key": wallet_public_key,
    }


def _resolve_wallet_profile_arguments(
    args: argparse.Namespace,
    profile: dict[str, str],
) -> tuple[str | None, str | None]:
    if profile:
        if args.wallet_address is not None and args.wallet_address != profile["wallet_address"]:
            raise ValueError("--wallet-address does not match the Wallet profile")
        if args.wallet_public_key is not None and args.wallet_public_key != profile["wallet_public_key"]:
            raise ValueError("--wallet-public-key does not match the Wallet profile")
    return (
        args.wallet_address or profile.get("wallet_address"),
        args.wallet_public_key or profile.get("wallet_public_key"),
    )


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _git(path: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=path,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _identity(contributor_id: str, platform_account: str) -> ContributorIdentity:
    platform, account_id = platform_account.split(":", 1)
    payload = {
        "contributor_id": contributor_id,
        "source_platform_accounts": [
            {"platform": platform, "account_id": account_id, "handle": account_id}
        ],
        "valid_from": "2026-08-13T00:00:00+00:00",
    }
    return ContributorIdentity(
        contributor_id=contributor_id,
        source_platform_accounts=[
            PlatformAccount(platform=platform, account_id=account_id, handle=account_id)
        ],
        valid_from=payload["valid_from"],
        identity_hash=canonical_hash(payload),
        contributor_signature=canonical_hash({"identity": payload, "mode": "CONTROLLED_LOCALNET"}),
    )


def _repository_registration(
    repository_id: str,
    policy: dict[str, Any],
) -> tuple[RepositoryContributionProfile, EligibleRepository]:
    profile = RepositoryContributionProfile(
        profile_id=f"{repository_id}-profile",
        repository_id=repository_id,
        path_weights_milli={"source": 1_000, "test": 1_000, "documentation": 1_000, "configuration": 1_000},
        generated_patterns=["**/generated/**"],
        vendor_patterns=["vendor/**"],
    ).with_hash()
    authority_keys = policy.get("authorities")
    if not isinstance(authority_keys, dict) or len(authority_keys) < 2:
        raise ValueError("controlled-localnet authority policy must expose at least two authorities")
    authority_ids = sorted(authority_keys)[:2]
    payload = {
        "repository_id": repository_id,
        "profile_hash": profile.profile_hash,
        "authority_ids": authority_ids,
        "branch": "main",
    }
    repository = EligibleRepository(
        repository_id=repository_id,
        repository_name="AiDN controlled-localnet acceptance",
        canonical_url="controlled-localnet://aidn",
        organization_id="controlled-localnet",
        default_branch="main",
        contribution_profile_id=profile.profile_id,
        attestation_policy_id="MAINTAINER_THRESHOLD",
        attestation_authority_ids=authority_ids,
        attestation_authority_public_keys={
            authority_id: authority_keys[authority_id] for authority_id in authority_ids
        },
        active_from_epoch=0,
        repository_hash=canonical_hash(payload),
        authorization_signature=canonical_hash({"repository": payload, "policy_hash": policy["policy_hash"]}),
    )
    return profile, repository


def _make_merge_commit(workspace: Path, claim: ContributorWalletClaim) -> tuple[str, str, str]:
    _git(workspace, "config", "user.email", "controlled-localnet@aidn.test")
    _git(workspace, "config", "user.name", "AiDN Controlled Localnet")
    _git(workspace, "checkout", "main")
    base_commit = _git(workspace, "rev-parse", "HEAD")
    feature_branch = "contribution/controlled-localnet-epoch-1"
    _git(workspace, "checkout", "-b", feature_branch)
    contribution_path = workspace / "docs" / "evidence" / "controlled-localnet-contribution.md"
    contribution_path.parent.mkdir(parents=True, exist_ok=True)
    contribution_path.write_text(
        "# Controlled Localnet Contribution\n\n"
        "This fixture documents the first RFC-0068 to ECO-0007 acceptance path.\n"
        "It is a real protected-branch contribution in the controlled test network.\n",
        encoding="utf-8",
    )
    claim_path = workspace / ".aidn" / "contributor-wallet.json"
    claim_path.parent.mkdir(parents=True, exist_ok=True)
    claim_path.write_text(json.dumps(claim.model_dump(mode="json"), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _git(workspace, "add", "docs/evidence/controlled-localnet-contribution.md", ".aidn/contributor-wallet.json")
    _git(workspace, "commit", "-m", "Add controlled localnet contribution claim")
    source_commit = _git(workspace, "rev-parse", "HEAD")
    _git(workspace, "checkout", "main")
    _git(workspace, "merge", "--no-ff", "--no-edit", feature_branch)
    merge_commit = _git(workspace, "rev-parse", "HEAD")
    if _git(workspace, "rev-parse", "HEAD^1") != base_commit:
        raise RuntimeError("controlled contribution merge first parent is not the protected base")
    return base_commit, source_commit, merge_commit


def _build_wallet_claim(
    service: ContributionAccountingService,
    contributor_id: str,
    platform_account: str,
    *,
    wallet_address: str | None = None,
    wallet_public_key: str | None = None,
    wallet_private_key_file: Path | None = None,
) -> ContributorWalletClaim:
    supplied_profile = [wallet_address, wallet_public_key, wallet_private_key_file]
    if any(value is not None for value in supplied_profile) and not all(
        value is not None for value in supplied_profile
    ):
        raise ValueError(
            "--wallet-address, --wallet-public-key and --wallet-private-key-file "
            "must be supplied together"
        )
    if wallet_private_key_file is None:
        wallet_key = Ed25519PrivateKey.generate()
        wallet_public_key = public_key_for_private_key(wallet_key)
        wallet_address = "wallet-" + hashlib.sha256(wallet_public_key.encode("utf-8")).hexdigest()[:12]
    else:
        wallet_key, wallet_public_key = load_verified_contributor_wallet_key(
            wallet_private_key_file,
            wallet_address=str(wallet_address),
            expected_public_key=str(wallet_public_key),
        )
    challenge = service.issue_wallet_binding_challenge(
        contributor_id=contributor_id,
        source_platform_account=platform_account,
        wallet_address=wallet_address,
    )
    binding_payload = contributor_wallet_binding_payload(
        contributor_id=contributor_id,
        source_platform_account=platform_account,
        wallet_address=wallet_address,
        wallet_public_key=wallet_public_key,
        challenge_id=challenge.challenge_id,
        challenge_hash=challenge.challenge_hash,
        binding_version=1,
    )
    binding = service.bind_wallet(
        challenge_id=challenge.challenge_id,
        wallet_public_key=wallet_public_key,
        wallet_signature="ed25519:" + wallet_key.sign(binding_payload).hex(),
        source_platform_confirmation_hash=canonical_hash(
            {"source": "controlled-localnet", "account": platform_account}
        ),
    )
    unsigned = ContributorWalletClaim(
        contributor_id=contributor_id,
        source_platform_account=platform_account,
        wallet_address=wallet_address,
        wallet_public_key=wallet_public_key,
        wallet_signature="ed25519:pending",
        binding_id=binding.binding_id,
        binding_hash=binding.binding_hash,
        claim_hash="sha256:pending",
    )
    signed = unsigned.model_copy(
        update={"wallet_signature": "ed25519:" + wallet_key.sign(contributor_wallet_claim_payload(unsigned)).hex()}
    )
    claim = signed.model_copy(update={"claim_hash": signed.expected_claim_hash()})
    return claim


def main() -> int:
    args = _parser().parse_args()
    if args.contribution_epoch < 0:
        raise ValueError("--contribution-epoch must be non-negative")
    workspace = args.workspace.resolve()
    if args.wallet_private_key_file is not None:
        wallet_private_key_file = args.wallet_private_key_file.expanduser().resolve()
        try:
            wallet_private_key_file.relative_to(ROOT.resolve())
        except ValueError:
            pass
        else:
            raise ValueError(
                "contributor Wallet private key must remain outside the repository"
            )
    else:
        wallet_private_key_file = None
    if workspace.exists():
        shutil.rmtree(workspace)
    source = args.repository_source.resolve()
    source_head = _git(source, "rev-parse", "HEAD")
    workspace.parent.mkdir(parents=True, exist_ok=True)
    clone = subprocess.run(
        ["git", "clone", "--no-local", "--no-hardlinks", str(source), str(workspace)],
        cwd=workspace.parent,
        capture_output=True,
        text=True,
        check=False,
    )
    if clone.returncode != 0:
        raise RuntimeError(f"git clone failed: {clone.stderr.strip()}")
    if _git(workspace, "rev-parse", "HEAD") != source_head:
        raise RuntimeError("acceptance clone does not match the source HEAD")

    policy = _object(args.authority_policy)
    profile_wallet = _wallet_profile(args.wallet_profile, policy)
    wallet_address, wallet_public_key = _resolve_wallet_profile_arguments(args, profile_wallet)
    if args.wallet_profile is not None and args.wallet_private_key_file is None:
        raise ValueError("--wallet-profile requires --wallet-private-key-file")
    contributor_id = f"controlled-localnet-contributor-epoch-{args.contribution_epoch}"
    service = ContributionAccountingService(ContributionEvidenceStore(args.evidence_store))
    profile, repository = _repository_registration(args.repository_id, policy)
    service.register_profile(profile)
    service.register_repository(repository)
    service.register_contributor(_identity(contributor_id, args.source_platform_account))
    claim = _build_wallet_claim(
        service,
        contributor_id,
        args.source_platform_account,
        wallet_address=wallet_address,
        wallet_public_key=wallet_public_key,
        wallet_private_key_file=wallet_private_key_file,
    )
    _base_commit, source_commit, merge_commit = _make_merge_commit(workspace, claim)
    verifier = service.git_verifier
    diff_base, file_changes = collect_merge_file_changes(
        workspace,
        merge_commit_hash=merge_commit,
        diff_base=_git(workspace, "rev-parse", "HEAD^1"),
        verifier=verifier,
    )
    merged_at = verifier._output(workspace, "show", "-s", "--format=%cI", merge_commit)
    authority_keys = policy["authorities"]
    authority_ids = sorted(authority_keys)[:2]
    authorities = [
        {"authority_id": authority_id, "authority_role": "maintainer", "signature": "PENDING"}
        for authority_id in authority_ids
    ]
    source_evidence_hash = canonical_hash(
        {"source": "controlled-localnet", "merge_commit": merge_commit, "repository": args.repository_id}
    )
    request_package = build_attestation_request(
        repository_id=args.repository_id,
        pull_request_id=f"controlled-localnet-epoch-{args.contribution_epoch}",
        merge_commit_hash=merge_commit,
        base_branch="main",
        source_commit_hash=source_commit,
        merged_at=merged_at,
        merge_actor="controlled-localnet-maintainer",
        pull_request_author=args.source_platform_account,
        primary_contributor_id=contributor_id,
        contribution_epoch=args.contribution_epoch,
        contribution_class="DOCUMENTATION",
        source_platform_evidence_hash=source_evidence_hash,
        repository_path=workspace,
        attestation_authorities=authorities,
        file_changes=file_changes,
        diff_base=diff_base,
        wallet_claim=read_and_verify_wallet_claim(
            workspace,
            merge_commit_hash=merge_commit,
            contributor_id=contributor_id,
            evidence_store=service.store,
            verifier=verifier,
        ),
        wallet_claim_path=".aidn/contributor-wallet.json",
        factor_values=ContributionFactorValues(
            complexity_milli=1_000,
            priority_milli=1_200,
            quality_milli=1_100,
            impact_expectation_milli=1_000,
            independence_milli=1_000,
        ),
        logical_deliverable="RFC-0068 to ECO-0007 controlled-localnet acceptance",
    )
    request_package["git_evidence"] = verifier.verify(
        workspace,
        merge_commit_hash=merge_commit,
        base_branch="main",
        allowed_branches={"main"},
        source_commit_hash=source_commit,
    )
    prepared = service.prepare_attestation_context(
        repository_id=args.repository_id,
        pull_request_id=request_package["request"]["pull_request_id"],
        merge_commit_hash=merge_commit,
        base_branch="main",
        source_commit_hash=source_commit,
        merged_at=merged_at,
        merge_actor="controlled-localnet-maintainer",
        pull_request_author=args.source_platform_account,
        primary_contributor_id=contributor_id,
        contribution_epoch=args.contribution_epoch,
        contribution_class="DOCUMENTATION",
        file_changes=file_changes,
        source_platform_evidence_hash=source_evidence_hash,
        repository_path=workspace,
        factor_values=ContributionFactorValues.model_validate(request_package["request"]["factor_values"]),
        logical_deliverable="RFC-0068 to ECO-0007 controlled-localnet acceptance",
        reward_metadata={"wallet_claim_path": ".aidn/contributor-wallet.json"},
    )
    signing_context = {
        "contribution_id": prepared["contribution_id"],
        "source_evidence_root": prepared["source_evidence_root"],
        "scoring_evidence_root": prepared["scoring_evidence_root"],
        "role_allocations": [item.model_dump(mode="json") for item in prepared["allocations"]],
    }
    request_package["attestation_context"] = signing_context
    request_package["attestation_context_hash"] = canonical_hash(signing_context)
    _write(args.output.with_name("rfc0068-intake-prepared.json"), request_package)
    payloads = build_attestation_authority_signing_payloads(
        repository_id=args.repository_id,
        contribution_id=prepared["contribution_id"],
        pull_request_id=request_package["request"]["pull_request_id"],
        merge_commit_hash=merge_commit,
        contribution_epoch=args.contribution_epoch,
        contribution_class="DOCUMENTATION",
        source_evidence_root=prepared["source_evidence_root"],
        scoring_evidence_root=prepared["scoring_evidence_root"],
        role_allocations=signing_context["role_allocations"],
        authorities=authorities,
    )
    signed_authorities = []
    for authority in authorities:
        authority_id = authority["authority_id"]
        key_path = args.authority_key_dir / f"{authority_id}.seed"
        private_key = load_protocol_authority_private_key(key_path)
        payload = bytes.fromhex(payloads[authority_id]["payload_hex"])
        signed_authorities.append(
            {
                "authority_id": authority_id,
                "authority_role": authority["authority_role"],
                "signature": "ed25519:" + private_key.sign(payload).hex(),
            }
        )
    request_package["mode"] = "SIGNED_REQUEST_READY_FOR_SUBMISSION"
    request_package["request"]["attestation_authorities"] = signed_authorities
    request_package["evidence"]["attestation_authorities"] = signed_authorities
    request_package["evidence_root"] = canonical_hash(request_package["evidence"])
    request_package["signed_authority_ids"] = authority_ids
    _write(args.output.with_name("rfc0068-intake-signed.json"), request_package)
    request = validate_attestation_request_package(request_package)
    attestation = service.attest_merge(**request)
    finalized = service.finalize_contribution(
        contribution_id=attestation.contribution_id,
        current_epoch=args.contribution_epoch + 2,
    )
    pool_input = {
        "epoch": args.contribution_epoch,
        "distributable_epoch_emission_q_atoms": 5_000_000_000,
        "carryover_in_q_atoms": 0,
        "dedicated_development_grants_q_atoms": 0,
        "returned_unclaimed_rewards_q_atoms": 0,
        "returned_cancelled_rewards_q_atoms": 0,
        "maturity_reserve_in_q_atoms": 0,
        "approved_bounty_reservations_q_atoms": 0,
    }
    _write(args.pool_input_output, pool_input)
    summary = {
        "status": "RFC0068_FINALIZED",
        "mode": "CONTROLLED_LOCALNET_ACCEPTANCE",
        "repository_id": args.repository_id,
        "repository_path": str(workspace),
        "base_commit_hash": _base_commit,
        "source_commit_hash": source_commit,
        "merge_commit_hash": merge_commit,
        "contribution_id": finalized.contribution_id,
        "attestation_hash": finalized.attestation_hash,
        "source_evidence_root": finalized.source_evidence_root,
        "scoring_evidence_root": finalized.scoring_evidence_root,
        "wallet_address": claim.wallet_address,
        "wallet_public_key": claim.wallet_public_key,
        "wallet_binding_id": claim.binding_id,
        "wallet_binding_hash": claim.binding_hash,
        "wallet_claim_hash": claim.claim_hash,
        "authority_ids": authority_ids,
        "authority_signature_state": finalized.authority_signature_state,
        "wallet_state": finalized.wallet_state,
        "wallet_profile": (
            "EXTERNAL_VERIFIED"
            if wallet_private_key_file is not None
            else "EPHEMERAL_FIXTURE"
        ),
        "eligibility_state": finalized.eligibility_state,
        "challenge_until_epoch": finalized.challenge_until_epoch,
        "finalization_epoch": args.contribution_epoch + 2,
        "contribution_units_milli": finalized.contribution_units_milli,
        "evidence_store": str(args.evidence_store.resolve()),
        "prepared_intake": str(args.output.with_name("rfc0068-intake-prepared.json").resolve()),
        "signed_intake": str(args.output.with_name("rfc0068-intake-signed.json").resolve()),
        "pool_input": str(args.pool_input_output.resolve()),
        "private_keys_exported": False,
        "consensus_submitted": False,
    }
    _write(args.output, summary)
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "BLOCKED", "error": str(error)}, sort_keys=True))
        raise SystemExit(2) from error
