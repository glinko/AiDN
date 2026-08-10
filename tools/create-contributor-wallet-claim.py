#!/usr/bin/env python3
"""Create the signed RFC-0068 Wallet claim committed with a contribution."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from aidn_hypervisor.contributions.models import ContributorWalletClaim  # noqa: E402
from aidn_hypervisor.contributions.service import (  # noqa: E402
    contributor_wallet_claim_payload,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create .aidn/contributor-wallet.json for an AiDN contribution"
    )
    parser.add_argument("--contributor-id", required=True)
    parser.add_argument("--source-platform-account", required=True)
    parser.add_argument("--wallet-address", required=True)
    parser.add_argument("--binding-id")
    parser.add_argument("--binding-hash")
    parser.add_argument(
        "--private-key-file",
        type=Path,
        help="file containing a 32-byte Ed25519 seed as hex or ed25519:<hex>",
    )
    parser.add_argument(
        "--private-key-hex",
        help="32-byte Ed25519 seed as hex; prefer --private-key-file or the environment",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".aidn/contributor-wallet.json"),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite an existing file; use only before committing a new revision",
    )
    return parser


def _key_material(args: argparse.Namespace) -> bytes:
    supplied = [
        args.private_key_file is not None,
        args.private_key_hex is not None,
        bool(os.environ.get("AIDN_CONTRIBUTOR_PRIVATE_KEY_HEX")),
    ]
    if sum(supplied) != 1:
        raise ValueError(
            "provide exactly one of --private-key-file, --private-key-hex, "
            "or AIDN_CONTRIBUTOR_PRIVATE_KEY_HEX"
        )
    if args.private_key_file is not None:
        value = args.private_key_file.read_text(encoding="utf-8").strip()
    elif args.private_key_hex is not None:
        value = args.private_key_hex.strip()
    else:
        value = os.environ["AIDN_CONTRIBUTOR_PRIVATE_KEY_HEX"].strip()
    if value.startswith("ed25519:"):
        value = value.removeprefix("ed25519:")
    try:
        seed = bytes.fromhex(value)
    except ValueError as error:
        raise ValueError("Ed25519 private key must be hexadecimal") from error
    if len(seed) != 32:
        raise ValueError("Ed25519 private key must contain exactly 32 bytes")
    return seed


def create_claim(args: argparse.Namespace) -> ContributorWalletClaim:
    if args.output.exists() and not args.force:
        raise ValueError(
            f"refusing to overwrite existing Wallet claim: {args.output}; "
            "use --force only while preparing a new contribution revision"
        )
    private_key = Ed25519PrivateKey.from_private_bytes(_key_material(args))
    public_key = "ed25519:" + private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()
    unsigned = ContributorWalletClaim(
        contributor_id=args.contributor_id,
        source_platform_account=args.source_platform_account,
        wallet_address=args.wallet_address,
        wallet_public_key=public_key,
        wallet_signature="ed25519:pending",
        binding_id=args.binding_id,
        binding_hash=args.binding_hash,
        claim_hash="sha256:pending",
    )
    signature = "ed25519:" + private_key.sign(contributor_wallet_claim_payload(unsigned)).hex()
    signed = unsigned.model_copy(update={"wallet_signature": signature})
    return signed.model_copy(update={"claim_hash": signed.expected_claim_hash()})


def main() -> int:
    args = _parser().parse_args()
    try:
        claim = create_claim(args)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(claim.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(f"created {args.output}")
    print(f"wallet_public_key: {claim.wallet_public_key}")
    print(f"claim_hash: {claim.claim_hash}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
