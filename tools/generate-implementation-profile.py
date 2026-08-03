#!/usr/bin/env python3
"""Generate or verify the deterministic IMP-0001 candidate profile."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from aidn_hypervisor.consensus.implementation_profile import (
    DEFAULT_IMPLEMENTATION_PROFILE_ID,
    build_implementation_profile,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile-id", default=DEFAULT_IMPLEMENTATION_PROFILE_ID)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("profiles") / f"{DEFAULT_IMPLEMENTATION_PROFILE_ID}.json",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail unless the existing artifact exactly matches the current implementation",
    )
    args = parser.parse_args()
    profile = build_implementation_profile(profile_id=args.profile_id)
    encoded = json.dumps(profile, ensure_ascii=True, indent=2) + "\n"
    if args.check:
        try:
            current = args.output.read_text(encoding="utf-8")
        except OSError as error:
            print(f"profile check failed: {error}")
            return 2
        if current != encoded:
            print(f"profile is stale: {args.output}")
            return 2
        print(f"profile is current: {args.output}")
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(encoded, encoding="utf-8")
    print(f"generated {args.output}")
    print(profile["profile_commitment"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
