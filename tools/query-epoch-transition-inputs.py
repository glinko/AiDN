#!/usr/bin/env python3
"""Read-only multi-validator preflight for Epoch Engine transition inputs."""

from __future__ import annotations

import argparse
import json
import sys

from aidn_hypervisor.consensus.epoch_transition_quorum import (
    collect_epoch_transition_quorum,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rpc-url", action="append", required=True, help="Validator RPC URL; repeat per validator")
    parser.add_argument("--quorum", type=int, help="Required matching validator count; defaults to 2/3")
    args = parser.parse_args()
    try:
        result = collect_epoch_transition_quorum(
            rpc_urls=args.rpc_url,
            quorum=args.quorum,
        )
    except ValueError as error:
        result = {"status": "ERROR", "error": str(error)}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "READY" else 2


if __name__ == "__main__":
    sys.exit(main())
