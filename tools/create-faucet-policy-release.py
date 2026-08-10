#!/usr/bin/env python3
"""Create a creator-signed Faucet policy release from an immutable root."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "aidn-faucet" / "src"))
sys.path.insert(0, str(ROOT / "src"))

from aidn_faucet.policy_registry import (  # noqa: E402
    FaucetPolicyRegistryRoot,
    FaucetPolicyRelease,
    load_ed25519_private_key,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry-root", type=Path, required=True)
    parser.add_argument("--creator-private-key", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sequence", type=int, required=True)
    parser.add_argument("--policy", choices=("fixed-daily", "accumulating-pool"), required=True)
    parser.add_argument("--policy-version", required=True)
    parser.add_argument("--effective-from", default=datetime.now(UTC).isoformat())
    parser.add_argument("--effective-until")
    parser.add_argument("--previous-policy")
    parser.add_argument("--daily-q", type=int, default=50)
    parser.add_argument("--rate-q", type=int, default=5)
    parser.add_argument("--interval-seconds", type=int, default=60)
    return parser


def main() -> int:
    args = _parser().parse_args()
    root = FaucetPolicyRegistryRoot.model_validate_json(args.registry_root.read_text(encoding="utf-8")).verify()
    previous_hash = None
    if args.previous_policy:
        previous_hash = FaucetPolicyRelease.model_validate_json(
            Path(args.previous_policy).read_text(encoding="utf-8")
        ).policy_hash
    parameters = (
        {"amount_q": args.daily_q}
        if args.policy == "fixed-daily"
        else {"rate_q": args.rate_q, "interval_seconds": args.interval_seconds}
    )
    release = FaucetPolicyRelease.create_signed(
        root=root,
        sequence=args.sequence,
        policy_id=args.policy,
        policy_version=args.policy_version,
        parameters=parameters,
        effective_from=args.effective_from,
        effective_until=args.effective_until,
        previous_policy_hash=previous_hash,
        creator_private_key=load_ed25519_private_key(str(args.creator_private_key)),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(release.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"policy_hash": release.policy_hash, "output": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
