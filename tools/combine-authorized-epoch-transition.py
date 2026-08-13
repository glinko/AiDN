#!/usr/bin/env python3
"""Combine independently signed EPOCH_TRANSITION signatures."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aidn_hypervisor.consensus.epoch_transition import (  # noqa: E402
    combine_epoch_transition_signatures,
)
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope  # noqa: E402
from aidn_hypervisor.consensus.protocol_authority import ProtocolAuthorityPolicy  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unsigned-envelope", required=True, type=Path)
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument(
        "--signature",
        action="append",
        required=True,
        type=Path,
        help="independent signature artifact; repeat until threshold is met",
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--quorum-report",
        type=Path,
        help="required for a quorum-bound envelope",
    )
    parser.add_argument("--expected-chain-id")
    return parser


def _object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def main() -> int:
    args = _parser().parse_args()
    envelope = LedgerOperationEnvelope.model_validate_json(
        args.unsigned_envelope.read_text(encoding="utf-8")
    )
    policy = ProtocolAuthorityPolicy.from_mapping(_object(args.policy))
    signatures: dict[str, str] = {}
    for path in args.signature:
        artifact = _object(path)
        if artifact.get("operation_id") != envelope.operation_id:
            raise ValueError(f"signature artifact operation ID does not match: {path}")
        if artifact.get("policy_hash") != policy.policy_hash:
            raise ValueError(f"signature artifact policy hash does not match: {path}")
        authority_id = artifact.get("authority_id")
        signature = artifact.get("signature")
        if not isinstance(authority_id, str) or not isinstance(signature, str):
            raise ValueError(f"signature artifact is incomplete: {path}")
        if authority_id in signatures:
            raise ValueError(f"duplicate authority signature: {authority_id}")
        signatures[authority_id] = signature
    quorum_report = _object(args.quorum_report) if args.quorum_report is not None else None
    if quorum_report is None and any(
        key in envelope.payload
        for key in (
            "epoch_transition_quorum_version",
            "epoch_transition_quorum_hash",
        )
    ):
        raise ValueError("--quorum-report is required for a quorum-bound envelope")
    signed = combine_epoch_transition_signatures(
        envelope,
        policy=policy,
        signatures=signatures,
        quorum_report=quorum_report,
        expected_chain_id=args.expected_chain_id,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(signed.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": "COMBINED",
                "operation_id": signed.operation_id,
                "policy_hash": policy.policy_hash,
                "authority_ids": sorted(signatures),
                "output": str(args.output),
                "broadcast": False,
                "quorum_bound": quorum_report is not None,
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
