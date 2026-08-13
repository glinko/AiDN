#!/usr/bin/env python3
"""Build a signed protocol-authorized EPOCH_TRANSITION offline.

The command validates public policy, signer ownership, quorum, and canonical
Ledger payload rules. It never broadcasts, calls an RPC endpoint, or mutates a
Ledger. Keep private signer files outside the repository.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aidn_hypervisor.consensus.epoch_transition import (  # noqa: E402
    build_signed_epoch_transition,
    build_signed_epoch_transition_from_quorum,
    load_protocol_authority_private_key,
)
from aidn_hypervisor.consensus.protocol_authority import ProtocolAuthorityPolicy  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", required=True, type=Path, help="public authority policy JSON")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--payload",
        type=Path,
        help="JSON object containing the canonical epoch transition payload",
    )
    source.add_argument(
        "--quorum-report",
        type=Path,
        help="hash-bound READY quorum report produced by query-epoch-transition-inputs.py",
    )
    parser.add_argument(
        "--signer",
        action="append",
        required=True,
        metavar="AUTHORITY_ID=PRIVATE_KEY_FILE",
        help="repeat once per authority signer; private files stay outside the repo",
    )
    parser.add_argument("--created-at", required=True, help="canonical ISO-8601 creation time")
    parser.add_argument("--expires-at", help="optional canonical ISO-8601 expiry time")
    parser.add_argument("--initiator-id", default="epoch-engine")
    parser.add_argument("--expected-chain-id")
    parser.add_argument("--output", required=True, type=Path)
    return parser


def _load_json_object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _parse_signers(values: list[str]) -> dict[str, object]:
    signers: dict[str, object] = {}
    for value in values:
        authority_id, separator, raw_path = value.partition("=")
        if not separator or not authority_id.strip() or not raw_path.strip():
            raise ValueError("--signer must use AUTHORITY_ID=PRIVATE_KEY_FILE")
        if authority_id in signers:
            raise ValueError(f"duplicate --signer authority ID: {authority_id}")
        signers[authority_id] = load_protocol_authority_private_key(Path(raw_path))
    return signers


def main() -> int:
    args = _parser().parse_args()
    policy = ProtocolAuthorityPolicy.from_mapping(_load_json_object(args.policy))
    signers = _parse_signers(args.signer)
    if args.quorum_report is not None:
        envelope = build_signed_epoch_transition_from_quorum(
            policy=policy,
            quorum_report=_load_json_object(args.quorum_report),
            signers=signers,
            created_at=args.created_at,
            expires_at=args.expires_at,
            initiator_id=args.initiator_id,
            expected_chain_id=args.expected_chain_id,
        )
        source_name = "quorum_report"
    else:
        envelope = build_signed_epoch_transition(
            policy=policy,
            payload=_load_json_object(args.payload),
            signers=signers,
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
                "operation_id": envelope.operation_id,
                "policy_hash": policy.policy_hash,
                "signer_ids": sorted(signers),
                "output": str(args.output),
                "broadcast": False,
                "source": source_name,
                "quorum_bound": args.quorum_report is not None,
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
