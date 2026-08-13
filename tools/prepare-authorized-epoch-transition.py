#!/usr/bin/env python3
"""Prepare an unsigned, policy-bound EPOCH_TRANSITION for independent signers."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aidn_hypervisor.consensus.epoch_transition import (  # noqa: E402
    build_unsigned_epoch_transition,
    build_unsigned_epoch_transition_from_quorum,
)
from aidn_hypervisor.consensus.protocol_authority import ProtocolAuthorityPolicy  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", required=True, type=Path)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--payload", type=Path)
    source.add_argument(
        "--quorum-report",
        type=Path,
        help="hash-bound READY quorum report produced by query-epoch-transition-inputs.py",
    )
    parser.add_argument("--expected-chain-id")
    parser.add_argument("--created-at", required=True)
    parser.add_argument("--expires-at")
    parser.add_argument("--initiator-id", default="epoch-engine")
    parser.add_argument("--output", required=True, type=Path)
    return parser


def _object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def main() -> int:
    args = _parser().parse_args()
    policy = ProtocolAuthorityPolicy.from_mapping(_object(args.policy))
    if args.quorum_report is not None:
        envelope = build_unsigned_epoch_transition_from_quorum(
            policy=policy,
            quorum_report=_object(args.quorum_report),
            created_at=args.created_at,
            expires_at=args.expires_at,
            initiator_id=args.initiator_id,
            expected_chain_id=args.expected_chain_id,
        )
        source_name = "quorum_report"
    else:
        envelope = build_unsigned_epoch_transition(
            policy=policy,
            payload=_object(args.payload),
            created_at=args.created_at,
            expires_at=args.expires_at,
            initiator_id=args.initiator_id,
        )
        source_name = "payload"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(envelope.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": "CREATED",
                "operation_id": envelope.operation_id,
                "policy_hash": policy.policy_hash,
                "output": str(args.output),
                "signed": False,
                "broadcast": False,
                "source": source_name,
                "quorum_bound": bool(args.quorum_report),
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
