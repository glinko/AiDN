#!/usr/bin/env python3
"""Run the controlled local G2 snapshot and State Sync acceptance harness."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from aidn_hypervisor.consensus.snapshot_acceptance import (
    SnapshotAcceptanceError,
    run_snapshot_acceptance,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, help="write the machine-readable G2 report")
    args = parser.parse_args()
    try:
        payload = run_snapshot_acceptance()
    except SnapshotAcceptanceError as error:
        payload = {"status": "FAIL", "error": str(error)}
        exit_code = 2
    else:
        exit_code = 0 if payload["status"] == "PASS" else 2

    encoded = json.dumps(payload, ensure_ascii=True, indent=2) + "\n"
    print(encoded, end="")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(encoded, encoding="utf-8")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
