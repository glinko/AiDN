#!/usr/bin/env python3
"""Run the checked-in FIX-0001 consensus fixture manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from aidn_hypervisor.consensus.fixture_runner import FixtureError, run_fixture_set


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--strict", action="store_true", help="require executable fixture blocks")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        results = run_fixture_set(args.manifest, strict=args.strict)
    except FixtureError as error:
        payload = {"status": "FAIL", "error": str(error)}
        print(json.dumps(payload, indent=2))
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return 2
    payload = {
        "status": "PASS",
        "fixture_count": len(results),
        "fixtures": [
            {
                "fixture_id": item.fixture_id,
                "operation_ids": list(item.operation_ids),
                "result_codes": list(item.result_codes),
                "post_app_hash": item.post_app_hash,
            }
            for item in results
        ],
    }
    encoded = json.dumps(payload, indent=2) + "\n"
    print(encoded, end="")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(encoded, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
