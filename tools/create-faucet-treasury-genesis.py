#!/usr/bin/env python3
"""Create or verify a secret-free Faucet Treasury Genesis manifest."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aidn_hypervisor.faucet_treasury import (  # noqa: E402
    FaucetTreasuryManifest,
    validate_faucet_treasury_manifest,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create", help="create a Genesis Treasury manifest")
    create.add_argument("--output", type=Path, required=True)
    create.add_argument("--treasury-id", required=True)
    create.add_argument("--network-id", required=True)
    create.add_argument("--chain-id", required=True)
    create.add_argument("--wallet-id", required=True)
    create.add_argument("--wallet-public-key", required=True)
    create.add_argument("--creator-recovery-wallet", required=True)
    create.add_argument("--policy-registry-hash", required=True)

    verify = subparsers.add_parser("verify", help="verify an existing manifest")
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("--network-id")
    verify.add_argument("--chain-id")
    return parser


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    args = _parser().parse_args()
    if args.command == "create":
        manifest = FaucetTreasuryManifest(
            treasury_id=args.treasury_id,
            network_id=args.network_id,
            chain_id=args.chain_id,
            wallet_id=args.wallet_id,
            wallet_public_key=args.wallet_public_key,
            creator_recovery_wallet=args.creator_recovery_wallet,
            genesis_allocation_q_atoms=10_000_000_000_000,
            policy_registry_hash=args.policy_registry_hash,
        )
        _write_json(args.output, manifest.model_dump(mode="json"))
        print(manifest.manifest_hash)
        return 0

    raw = json.loads(args.manifest.read_text(encoding="utf-8"))
    manifest = validate_faucet_treasury_manifest(
        FaucetTreasuryManifest.model_validate(raw),
        expected_network_id=args.network_id,
        expected_chain_id=args.chain_id,
    )
    print(json.dumps({"status": "ok", "manifest_hash": manifest.manifest_hash}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
