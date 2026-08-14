#!/usr/bin/env python3
"""Verify one authority policy across the controlled-localnet RPC quorum."""

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

DEFAULT_RPC_URLS = (
    "http://192.168.88.128:26657",
    "http://192.168.88.129:26657",
    "http://192.168.88.130:26657",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authority-policy", required=True, type=Path)
    parser.add_argument("--rpc-url", action="append", dest="rpc_urls")
    parser.add_argument("--timeout-seconds", type=float, default=5.0)
    return parser


def _read_policy(rpc_url: str, timeout_seconds: float) -> tuple[dict, str | None]:
    query = urlencode(
        {
            "path": json.dumps("protocol/authority-policy", separators=(",", ":")),
            "prove": "false",
        }
    )
    with urlopen(f"{rpc_url.rstrip('/')}/abci_query?{query}", timeout=timeout_seconds) as response:
        envelope = json.load(response)
    query_response = envelope.get("result", {}).get("response", {})
    if int(query_response.get("code", -1)) != 0:
        raise ValueError(f"authority policy query rejected by {rpc_url}")
    encoded = query_response.get("value")
    if not isinstance(encoded, str) or not encoded:
        raise ValueError(f"authority policy is missing on {rpc_url}")
    value = json.loads(base64.b64decode(encoded, validate=True).decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"authority policy response is not an object on {rpc_url}")
    return value, str(query_response.get("height") or "")


def main() -> int:
    args = _parser().parse_args()
    try:
        expected = json.loads(args.authority_policy.read_text(encoding="utf-8"))
        if not isinstance(expected, dict):
            raise ValueError("authority policy must be a JSON object")
        urls = tuple(args.rpc_urls or DEFAULT_RPC_URLS)
        observations = []
        for rpc_url in urls:
            policy, height = _read_policy(rpc_url, args.timeout_seconds)
            comparable = {
                key: policy.get(key)
                for key in ("policy_hash", "threshold", "authority_count", "version")
            }
            expected_comparable = {
                "policy_hash": expected.get("policy_hash"),
                "threshold": expected.get("threshold"),
                "authority_count": len(expected.get("authorities", {})),
                "version": expected.get("version"),
            }
            if comparable != expected_comparable:
                raise ValueError(f"authority policy mismatch at {rpc_url}")
            observations.append({"rpc_url": rpc_url, "height": height, **comparable})
        result = {
            "status": "VERIFIED",
            "policy_hash": expected.get("policy_hash"),
            "threshold": expected.get("threshold"),
            "authority_count": len(expected.get("authorities", {})),
            "rpc_observations": observations,
            "private_keys_exported": False,
        }
    except (OSError, ValueError, json.JSONDecodeError, UnicodeDecodeError) as error:
        print(json.dumps({"status": "BLOCKED", "error": str(error)}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
