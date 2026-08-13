#!/usr/bin/env python3
"""Combine independent EPOCH_SCHEDULE_REBASE signature artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aidn_hypervisor.consensus.epoch_schedule_rebase_commit import (  # noqa: E402
    combine_epoch_schedule_rebase_signatures,
)
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope  # noqa: E402
from aidn_hypervisor.consensus.protocol_authority import ProtocolAuthorityPolicy  # noqa: E402


def _object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unsigned-envelope", required=True, type=Path)
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument("--signature", action="append", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    envelope = LedgerOperationEnvelope.model_validate_json(args.unsigned_envelope.read_text(encoding="utf-8"))
    policy = ProtocolAuthorityPolicy.from_mapping(_object(args.policy))
    signatures: dict[str, str] = {}
    for path in args.signature:
        artifact = _object(path)
        if artifact.get("operation_id") != envelope.operation_id or artifact.get("policy_hash") != policy.policy_hash:
            raise ValueError(f"signature artifact does not bind this envelope: {path}")
        authority_id, signature = artifact.get("authority_id"), artifact.get("signature")
        if not isinstance(authority_id, str) or not isinstance(signature, str) or authority_id in signatures:
            raise ValueError(f"signature artifact is invalid: {path}")
        signatures[authority_id] = signature
    signed = combine_epoch_schedule_rebase_signatures(envelope, policy=policy, signatures=signatures)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(signed.model_dump(mode="json"), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": "COMBINED",
                "operation_id": signed.operation_id,
                "authority_ids": sorted(signatures),
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
