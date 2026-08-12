#!/usr/bin/env python3
"""Rotate a CometBFT finality checkpoint from a matching RPC quorum."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from aidn_hypervisor.consensus.checkpoint_rotation import rotate_checkpoint_file


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--height", type=int, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        help="write a new config instead of replacing --config atomically",
    )
    args = parser.parse_args()
    try:
        report = rotate_checkpoint_file(
            path=args.config,
            height=args.height,
            output=args.output,
        )
    except (OSError, ValueError) as error:
        print(json.dumps({"status": "REJECTED", "error": str(error)}, sort_keys=True))
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
