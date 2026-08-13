#!/usr/bin/env python3
"""Sign one unsigned EPOCH_RESULT_MANIFEST_COMMIT as one authority."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aidn_hypervisor.consensus.epoch_result_manifest_commit import (  # noqa: E402
    load_protocol_authority_private_key,
    sign_epoch_result_manifest_commit_signature,
)
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope  # noqa: E402
from aidn_hypervisor.consensus.protocol_authority import ProtocolAuthorityPolicy  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unsigned-envelope", required=True, type=Path)
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument("--authority-id", required=True)
    parser.add_argument("--private-key", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    envelope = LedgerOperationEnvelope.model_validate_json(args.unsigned_envelope.read_text(encoding="utf-8"))
    policy = ProtocolAuthorityPolicy.from_mapping(json.loads(args.policy.read_text(encoding="utf-8")))
    signature = sign_epoch_result_manifest_commit_signature(
        envelope,
        policy=policy,
        authority_id=args.authority_id,
        private_key=load_protocol_authority_private_key(args.private_key),
    )
    artifact = {
        "artifact_version": "aidn.epoch-result-manifest-signature.v1",
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
