#!/usr/bin/env python3
"""Create the signed immutable policy registry root for one Faucet Treasury."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "aidn-faucet" / "src"))
sys.path.insert(0, str(ROOT / "src"))

from aidn_faucet.models import wallet_id_for_public_key  # noqa: E402
from aidn_faucet.policy_registry import (  # noqa: E402
    FaucetPolicyRegistryRoot,
    load_ed25519_private_key,
    public_key_for_private_key,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--creator-private-key", type=Path, required=True)
    parser.add_argument("--creator-wallet", type=Path, required=True)
    parser.add_argument("--registry-id", required=True)
    parser.add_argument("--network-id", required=True)
    parser.add_argument("--chain-id", required=True)
    parser.add_argument("--treasury-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--created-at", default=datetime.now(UTC).isoformat())
    return parser


def main() -> int:
    args = _parser().parse_args()
    identity = json.loads(args.creator_wallet.read_text(encoding="utf-8"))
    key = load_ed25519_private_key(str(args.creator_private_key))
    public_key = public_key_for_private_key(key)
    wallet_id = wallet_id_for_public_key(public_key)
    if identity.get("wallet_id") != wallet_id or identity.get("public_key", "").lower() != public_key.lower():
        raise ValueError("creator private key does not match the supplied public wallet identity")
    root = FaucetPolicyRegistryRoot.create_signed(
        registry_id=args.registry_id,
        network_id=args.network_id,
        chain_id=args.chain_id,
        treasury_id=args.treasury_id,
        creator_recovery_wallet=wallet_id,
        creator_private_key=key,
        created_at=args.created_at,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(root.model_dump(mode="json"), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"registry_hash": root.root_hash, "output": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
