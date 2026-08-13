#!/usr/bin/env python3
"""Read-only quorum preflight for an ECO-0007 production reward batch."""

from __future__ import annotations

import argparse
import json
import sys

from aidn_hypervisor.reward.development_preflight_quorum import (
    collect_development_reward_preflight,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rpc-url", action="append", required=True, help="CometBFT RPC URL; repeat per validator")
    parser.add_argument("--pool-id", default="GENERAL_DEVELOPMENT")
    parser.add_argument("--quorum", type=int)
    args = parser.parse_args()
    try:
        report = collect_development_reward_preflight(
            rpc_urls=args.rpc_url,
            pool_id=args.pool_id,
            quorum=args.quorum,
        )
    except ValueError as error:
        print(json.dumps({"status": "ERROR", "error": str(error)}, sort_keys=True))
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "READY" else 2


if __name__ == "__main__":
    sys.exit(main())
