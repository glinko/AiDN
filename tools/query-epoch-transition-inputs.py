#!/usr/bin/env python3
"""Read-only multi-validator preflight for Epoch Engine transition inputs."""

from __future__ import annotations

import argparse
import base64
import json
import sys
from collections import Counter

from aidn_hypervisor.consensus.cometbft import HttpCometBftRpcTransport


def _query(rpc_url: str) -> dict:
    transport = HttpCometBftRpcTransport(rpc_url)
    response = transport.get(
        "/abci_query",
        params={"path": json.dumps("epoch/transition-inputs"), "prove": "false"},
        timeout_seconds=3,
    )
    result = response.get("result")
    if not isinstance(result, dict) or not isinstance(result.get("response"), dict):
        raise ValueError("ABCI query response is invalid")
    query_response = result["response"]
    if int(query_response.get("code", -1)) != 0:
        raise ValueError("ABCI epoch transition input query was rejected")
    encoded = query_response.get("value")
    if not isinstance(encoded, str) or not encoded:
        raise ValueError("validator returned an empty epoch transition input report")
    value = json.loads(base64.b64decode(encoded, validate=True).decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("epoch transition input report is not an object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rpc-url", action="append", required=True, help="Validator RPC URL; repeat per validator")
    parser.add_argument("--quorum", type=int, help="Required matching validator count; defaults to 2/3")
    args = parser.parse_args()
    quorum = args.quorum if args.quorum is not None else (len(args.rpc_url) // 2 + 1)
    if quorum < 1 or quorum > len(args.rpc_url):
        print(json.dumps({"status": "ERROR", "error": "invalid quorum"}, sort_keys=True))
        return 2

    observations: list[dict] = []
    failures: list[dict[str, str]] = []
    for rpc_url in args.rpc_url:
        try:
            report = _query(rpc_url)
            observations.append({"rpc_url": rpc_url, "report": report})
        except (ValueError, OSError, TimeoutError, json.JSONDecodeError) as error:
            failures.append({"rpc_url": rpc_url, "error": str(error)})

    hashes = Counter(
        observation["report"].get("report_hash")
        for observation in observations
        if observation["report"].get("report_hash")
    )
    matching_hash, matching_count = hashes.most_common(1)[0] if hashes else (None, 0)
    report = next(
        (
            observation["report"]
            for observation in observations
            if observation["report"].get("report_hash") == matching_hash
        ),
        None,
    )
    result = {
        "status": (
            report.get("status")
            if report is not None and matching_count >= quorum
            else "ERROR"
        ),
        "quorum": quorum,
        "matching_report_count": matching_count,
        "report": report,
        "observations": observations,
        "failures": failures,
    }
    if matching_count < quorum:
        result["error"] = "epoch transition input reports did not reach quorum"
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "READY" else 2


if __name__ == "__main__":
    sys.exit(main())
