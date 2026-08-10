#!/usr/bin/env python3
"""Generate local Faucet Treasury credentials and a public manifest.

This tool creates secrets on the Faucet host. It never prints private key
material or bearer tokens and never commits them to the repository.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from pathlib import Path
from shlex import quote as shell_quote

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aidn_hypervisor.faucet_treasury import (  # noqa: E402
    FaucetTreasuryManifest,
    wallet_id_for_public_key,
)


def _write(path: Path, content: str, *, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    os.chmod(path, mode)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--treasury-id", required=True)
    parser.add_argument("--network-id", required=True)
    parser.add_argument("--chain-id", required=True)
    parser.add_argument("--creator-recovery-wallet", required=True)
    parser.add_argument("--policy-registry-hash", required=True)
    parser.add_argument("--funding-mode", choices=("GENESIS", "CONSENSUS"), default="GENESIS")
    parser.add_argument("--funding-operation-id")
    parser.add_argument(
        "--force",
        action="store_true",
        help="replace an existing generated credential directory",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    output_dir = args.output_dir.expanduser().resolve()
    if args.funding_mode == "CONSENSUS" and not args.funding_operation_id:
        raise ValueError("--funding-operation-id is required for CONSENSUS funding")
    if args.funding_mode == "GENESIS" and args.funding_operation_id:
        raise ValueError("--funding-operation-id is only valid for CONSENSUS funding")
    if output_dir.exists() and any(output_dir.iterdir()) and not args.force:
        raise ValueError(f"refusing to overwrite non-empty credential directory: {output_dir}")
    output_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(output_dir, 0o700)

    private_key = Ed25519PrivateKey.generate()
    raw_seed = private_key.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    public_key = "ed25519:" + private_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    ).hex()
    wallet_id = wallet_id_for_public_key(public_key)
    manifest = FaucetTreasuryManifest(
        treasury_id=args.treasury_id,
        network_id=args.network_id,
        chain_id=args.chain_id,
        wallet_id=wallet_id,
        wallet_public_key=public_key,
        creator_recovery_wallet=args.creator_recovery_wallet,
        genesis_allocation_q_atoms=10_000_000_000_000,
        funding_mode=args.funding_mode,
        funding_operation_id=args.funding_operation_id,
        policy_registry_hash=args.policy_registry_hash,
    )
    agent_token = secrets.token_urlsafe(32)
    creator_token = secrets.token_urlsafe(32)

    _write(output_dir / "treasury.key", raw_seed.hex() + "\n", mode=0o600)
    _write(
        output_dir / "faucet-treasury.json",
        json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        mode=0o644,
    )
    _write(output_dir / "agent-token", agent_token + "\n", mode=0o600)
    _write(output_dir / "creator-token", creator_token + "\n", mode=0o600)
    _write(
        output_dir / "faucet.env",
        "\n".join(
            (
                f"AIDN_FAUCET_AGENT_TOKEN={shell_quote(agent_token)}",
                f"AIDN_FAUCET_CREATOR_TOKEN={shell_quote(creator_token)}",
                "AIDN_FAUCET_HOST=127.0.0.1",
            )
        )
        + "\n",
        mode=0o600,
    )
    _write(
        output_dir / "summary.json",
        json.dumps(
            {
                "treasury_id": manifest.treasury_id,
                "wallet_id": manifest.wallet_id,
                "wallet_public_key": manifest.wallet_public_key,
                "network_id": manifest.network_id,
                "chain_id": manifest.chain_id,
                "funding_mode": manifest.funding_mode,
                "funding_operation_id": manifest.funding_operation_id,
                "manifest_hash": manifest.manifest_hash,
                "files": {
                    "manifest": str(output_dir / "faucet-treasury.json"),
                    "treasury_key": str(output_dir / "treasury.key"),
                    "agent_token": str(output_dir / "agent-token"),
                    "creator_token": str(output_dir / "creator-token"),
                    "environment": str(output_dir / "faucet.env"),
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        mode=0o644,
    )
    print(
        json.dumps(
            {
                "status": "ok",
                "treasury_id": manifest.treasury_id,
                "wallet_id": manifest.wallet_id,
                "manifest_hash": manifest.manifest_hash,
                "output_dir": str(output_dir),
                "secret_values_written": True,
                "secret_values_printed": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as error:
        raise SystemExit(f"error: {error}") from error
