#!/usr/bin/env python3
"""Sign one unsigned EPOCH_TRANSITION as one protocol authority."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aidn_hypervisor.consensus.epoch_transition import (  # noqa: E402
    load_protocol_authority_private_key,
    sign_epoch_transition_signature,
)
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope  # noqa: E402
from aidn_hypervisor.consensus.protocol_authority import ProtocolAuthorityPolicy  # noqa: E402
from aidn_hypervisor.ledger.service import LedgerOperationService  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unsigned-envelope", required=True, type=Path)
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument("--authority-id", required=True)
    parser.add_argument("--private-key", required=True, type=Path)
    parser.add_argument(
        "--quorum-report",
        type=Path,
        help="required for a quorum-bound envelope",
    )
    parser.add_argument("--expected-chain-id")
    parser.add_argument("--output", required=True, type=Path)
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
    policy = ProtocolAuthorityPolicy.from_mapping(
        json.loads(args.policy.read_text(encoding="utf-8"))
    )
    if envelope.signatures:
        raise ValueError("signer input envelope must not already contain signatures")
    quorum_report = _object(args.quorum_report) if args.quorum_report is not None else None
    if quorum_report is None and any(
        key in envelope.payload
        for key in (
            "epoch_transition_quorum_version",
            "epoch_transition_quorum_hash",
        )
    ):
        raise ValueError("--quorum-report is required for a quorum-bound envelope")
    if quorum_report is None:
        LedgerOperationService().validate_consensus_epoch_transition(envelope)
    signature = sign_epoch_transition_signature(
        envelope,
        policy=policy,
        authority_id=args.authority_id,
        private_key=load_protocol_authority_private_key(args.private_key),
        quorum_report=quorum_report,
        expected_chain_id=args.expected_chain_id,
    )
    artifact = {
        "artifact_version": "aidn.epoch-transition-signature.v1",
        "operation_id": envelope.operation_id,
        "policy_hash": policy.policy_hash,
        "authority_id": args.authority_id,
        "signature": signature,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "SIGNED",
                "operation_id": envelope.operation_id,
                "authority_id": args.authority_id,
                "output": str(args.output),
                "private_key_exported": False,
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
