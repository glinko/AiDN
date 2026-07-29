#!/usr/bin/env python3
"""Verify a controlled private-LAN CometBFT testnet through all RPC nodes."""

from __future__ import annotations

import argparse
import json
import time
from typing import Any
from urllib import request as urllib_request

from aidn_hypervisor.consensus.lab_readiness import (
    CometBftLabObservation,
    CometBftLanTestnetConfig,
    validate_cometbft_lab_quorum,
)


def _rpc_get(endpoint: str, path: str) -> dict[str, Any]:
    with urllib_request.urlopen(f"{endpoint}{path}", timeout=5) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict) or payload.get("error"):
        raise RuntimeError(f"CometBFT RPC request failed for {endpoint}{path}: {payload!r}")
    result = payload.get("result")
    if not isinstance(result, dict):
        raise RuntimeError(f"CometBFT RPC result is invalid for {endpoint}{path}")
    return result


def _observation(endpoint: str) -> CometBftLabObservation:
    status = _rpc_get(endpoint, "/status")
    net_info = _rpc_get(endpoint, "/net_info")
    node_info = status.get("node_info")
    sync_info = status.get("sync_info")
    if not isinstance(node_info, dict) or not isinstance(sync_info, dict):
        raise RuntimeError(f"CometBFT status is incomplete for {endpoint}")
    return CometBftLabObservation(
        endpoint=endpoint,
        node_id=str(node_info.get("id") or ""),
        chain_id=str(node_info.get("network") or ""),
        height=int(sync_info.get("latest_block_height") or 0),
        app_hash=str(sync_info.get("latest_app_hash") or ""),
        catching_up=bool(sync_info.get("catching_up")),
        peer_count=int(net_info.get("n_peers") or 0),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rpc-url",
        action="append",
        required=True,
        help="One private-LAN CometBFT RPC root URL; repeat for every validator.",
    )
    parser.add_argument("--expected-validators", type=int, default=4)
    parser.add_argument("--maximum-height-lag", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=int, default=30)
    args = parser.parse_args()
    if args.timeout_seconds <= 0:
        raise ValueError("timeout-seconds must be positive")
    config = CometBftLanTestnetConfig(
        rpc_endpoints=args.rpc_url,
        expected_validators=args.expected_validators,
        maximum_height_lag=args.maximum_height_lag,
        allow_insecure_private_http=True,
    )
    deadline = time.monotonic() + args.timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            result = validate_cometbft_lab_quorum(
                config=config,
                observations=[_observation(endpoint) for endpoint in config.rpc_endpoints],
            )
            print(json.dumps(result, sort_keys=True))
            return
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
            last_error = error
            time.sleep(1)
    raise RuntimeError(f"controlled LAN testnet did not converge: {last_error}")


if __name__ == "__main__":
    main()
