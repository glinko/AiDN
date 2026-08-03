#!/usr/bin/env python3
"""Run the non-emitting ECO-0007 launch simulation matrix."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from aidn_hypervisor.reward.development_scenarios import run_launch_simulation_matrix


def main() -> int:
    parser = argparse.ArgumentParser(description="Run ECO-0007 launch scenarios without writing to the Ledger.")
    parser.add_argument(
        "--output",
        type=Path,
        help="Write the JSON report to this path instead of stdout",
    )
    args = parser.parse_args()

    try:
        report = run_launch_simulation_matrix()
        encoded = json.dumps(report.model_dump(mode="json"), ensure_ascii=True, indent=2) + "\n"
        if args.output is None:
            sys.stdout.write(encoded)
        else:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(encoded, encoding="utf-8")
        return 0 if report.all_invariants_passed and report.verify_integrity() else 1
    except (OSError, TypeError, ValueError) as error:
        print(f"development reward scenario simulation failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
