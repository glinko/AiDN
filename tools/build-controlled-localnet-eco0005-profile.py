#!/usr/bin/env python3
"""Build the fixed ECO-0005 profile for a controlled localnet.

The command reads only public policy/document inputs. It does not create an
authority signature and does not submit a consensus transaction. The resulting
profile fixes the launch emission and ECO-0007 shares; no pool amount can be
passed as a command-line override.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aidn_hypervisor.consensus.epoch_result_evidence import (  # noqa: E402
    build_controlled_localnet_eco0005_profile,
)
from aidn_hypervisor.consensus.protocol_authority import ProtocolAuthorityPolicy  # noqa: E402


def _object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _source_version(document: str) -> str:
    match = re.search(r"^Version:\s*`([^`]+)`", document, flags=re.MULTILINE)
    if match is None:
        raise ValueError("ECO-0005 document version is not declared")
    return match.group(1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--network-id", required=True)
    parser.add_argument("--chain-id", required=True)
    parser.add_argument("--effective-epoch", required=True, type=int)
    parser.add_argument("--epoch-schedule-hash", required=True)
    parser.add_argument("--authority-policy", required=True, type=Path)
    parser.add_argument(
        "--eco0005-document",
        type=Path,
        default=ROOT / "docs/product/ECO-0005-q-emission-recycling-and-epoch-reward-allocation.md",
    )
    parser.add_argument(
        "--source-document-id",
        default="docs/product/ECO-0005-q-emission-recycling-and-epoch-reward-allocation.md",
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    policy = ProtocolAuthorityPolicy.from_mapping(_object(args.authority_policy))
    document_bytes = args.eco0005_document.read_bytes()
    document = document_bytes.decode("utf-8")
    profile = build_controlled_localnet_eco0005_profile(
        network_id=args.network_id,
        chain_id=args.chain_id,
        effective_epoch=args.effective_epoch,
        epoch_schedule_hash=args.epoch_schedule_hash,
        authority_policy_hash=policy.policy_hash,
        source_document=args.source_document_id,
        source_document_version=_source_version(document),
        source_document_hash="sha256:" + hashlib.sha256(document_bytes).hexdigest(),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(profile.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": "CREATED",
                "profile_hash": profile.profile_hash,
                "authority_policy_hash": policy.policy_hash,
                "source_document_version": profile.source_document_version,
                "source_document_hash": profile.source_document_hash,
                "derived_development_pool_q_atoms": 250_000_000,
                "output": str(args.output),
                "signed": False,
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
