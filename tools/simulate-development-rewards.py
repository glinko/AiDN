#!/usr/bin/env python3
"""Run the non-emitting ECO-0007 development reward simulation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow a source checkout to run the tool before the package is installed.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aidn_hypervisor.reward.development_distribution import (
    DevelopmentContributionInput,
    DevelopmentPoolInput,
    DevelopmentRewardCalculator,
    DevelopmentRewardPolicy,
)


def _example() -> dict:
    return {
        "pool": {
            "epoch": 20,
            "distributable_epoch_emission_q_atoms": 5_000_000_000,
        },
        "contributions": [
            {
                "contribution_id": "example-runtime-fix",
                "contribution_epoch": 10,
                "contribution_units_milli": 100_000,
                "contribution_class": "CODE",
                "role_allocations": [
                    {
                        "contributor_id": "contributor-alice",
                        "role": "AUTHOR",
                        "allocation_basis_points": 10_000,
                        "wallet_address": "q1alice",
                    }
                ],
            },
            {
                "contribution_id": "example-tests",
                "contribution_epoch": 10,
                "contribution_units_milli": 60_000,
                "contribution_class": "TESTS",
                "role_allocations": [
                    {
                        "contributor_id": "contributor-bob",
                        "role": "TEST_AUTHOR",
                        "allocation_basis_points": 10_000,
                        "wallet_address": None,
                    }
                ],
            },
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Calculate an ECO-0007 proposal without writing to the Ledger.")
    parser.add_argument(
        "--input",
        type=Path,
        help="JSON file containing pool, optional policy, and contributions",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write the JSON result to this path instead of stdout",
    )
    args = parser.parse_args()

    try:
        payload = json.loads(args.input.read_text(encoding="utf-8")) if args.input is not None else _example()
        policy = DevelopmentRewardPolicy.model_validate(payload.get("policy", {}))
        pool = DevelopmentPoolInput.model_validate(payload["pool"])
        contributions = [DevelopmentContributionInput.model_validate(item) for item in payload.get("contributions", [])]
        calculation = DevelopmentRewardCalculator(policy).calculate(
            pool,
            contributions,
        )
        result = {
            "simulation_only": True,
            "emits_q": False,
            "ledger_writes": False,
            "calculation": calculation.model_dump(mode="json"),
        }
        encoded = json.dumps(result, ensure_ascii=True, indent=2) + "\n"
        if args.output is None:
            sys.stdout.write(encoded)
        else:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(encoded, encoding="utf-8")
        return 0
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"development reward simulation failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
