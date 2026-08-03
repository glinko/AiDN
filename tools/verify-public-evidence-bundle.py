#!/usr/bin/env python3
"""Verify an EVD-0001 public evidence bundle."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from aidn_hypervisor.evidence import EvidenceBundleError, verify_public_evidence_bundle


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument(
        "--require",
        action="append",
        default=[],
        metavar="PATH",
        help="require an artifact path to be listed in the manifest (repeatable)",
    )
    parser.add_argument(
        "--allow-missing-attestation",
        action="store_true",
        help="verify the bundle without requiring operator-attestation.json",
    )
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        result = verify_public_evidence_bundle(
            args.evidence_dir,
            required_paths=args.require,
            require_attestation=not args.allow_missing_attestation,
        )
    except EvidenceBundleError as error:
        payload = {"status": "FAIL", "error": str(error)}
        exit_code = 2
    else:
        payload = {"status": "PASS", **asdict(result)}
        exit_code = 0
    encoded = json.dumps(payload, ensure_ascii=True, indent=2) + "\n"
    print(encoded, end="")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(encoded, encoding="utf-8")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
