#!/usr/bin/env python3
"""Prepare an unsigned controlled-localnet EPOCH_SCHEDULE_REBASE offline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aidn_hypervisor.consensus.epoch_schedule_rebase import EpochScheduleRebase  # noqa: E402
from aidn_hypervisor.consensus.epoch_schedule_rebase_commit import (  # noqa: E402
    build_unsigned_epoch_schedule_rebase,
)
from aidn_hypervisor.consensus.protocol_authority import ProtocolAuthorityPolicy  # noqa: E402


def _object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument("--rebase", required=True, type=Path)
    parser.add_argument("--created-at", required=True)
    parser.add_argument("--expires-at")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    policy = ProtocolAuthorityPolicy.from_mapping(_object(args.policy))
    rebase = EpochScheduleRebase.model_validate(_object(args.rebase))
    envelope = build_unsigned_epoch_schedule_rebase(
        policy=policy, rebase=rebase, created_at=args.created_at, expires_at=args.expires_at
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(envelope.model_dump(mode="json"), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": "CREATED",
                "operation_id": envelope.operation_id,
                "rebase_hash": rebase.rebase_hash,
                "policy_hash": policy.policy_hash,
                "broadcast": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError) as error:
        print(json.dumps({"status": "BLOCKED", "error": str(error)}, sort_keys=True))
        raise SystemExit(2) from error
