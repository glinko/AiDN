#!/usr/bin/env python3
"""Run a controlled one-validator-offline recovery drill over SSH.

The operator supplies explicit stop/start commands for a disposable validator
process. No credentials or destructive defaults are embedded in this tool.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib import request as urllib_request


def _rpc_get(endpoint: str, path: str) -> dict[str, Any]:
    with urllib_request.urlopen(f"{endpoint.rstrip('/')}{path}", timeout=5) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict) or payload.get("error"):
        raise RuntimeError(f"RPC request failed for {endpoint}{path}: {payload!r}")
    result = payload.get("result")
    if not isinstance(result, dict):
        raise RuntimeError(f"RPC result is invalid for {endpoint}{path}")
    return result


def _status(endpoint: str) -> dict[str, Any]:
    result = _rpc_get(endpoint, "/status")
    sync_info = result.get("sync_info")
    node_info = result.get("node_info")
    if not isinstance(sync_info, dict) or not isinstance(node_info, dict):
        raise RuntimeError(f"RPC status is incomplete for {endpoint}")
    return {
        "rpc_url": endpoint.rstrip("/"),
        "height": int(sync_info.get("latest_block_height") or 0),
        "app_hash": str(sync_info.get("latest_app_hash") or "").upper(),
        "node_id": str(node_info.get("id") or ""),
        "chain_id": str(node_info.get("network") or ""),
    }


def _converge(endpoints: list[str], *, timeout_seconds: int, greater_than: int) -> list[dict[str, Any]]:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            statuses = [_status(endpoint) for endpoint in endpoints]
            heights = {item["height"] for item in statuses}
            app_hashes = {item["app_hash"] for item in statuses}
            if len(heights) == 1 and len(app_hashes) == 1 and next(iter(heights)) > greater_than:
                return statuses
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
            last_error = error
        time.sleep(1)
    raise RuntimeError(f"RPC views did not converge beyond {greater_than}: {last_error}")


def _run_ssh(target: str, command: str) -> None:
    subprocess.run(["ssh", target, command], check=True)


def _wait_until_unreachable(endpoint: str, *, timeout_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            _status(endpoint)
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
            last_error = error
            return
        time.sleep(1)
    raise RuntimeError(f"offline validator RPC remained reachable: {endpoint}; last={last_error}")


def run_offline_drill(
    *,
    endpoints: list[str],
    target_endpoint: str,
    ssh_target: str,
    stop_command: str,
    start_command: str,
    timeout_seconds: int,
    minimum_progress_blocks: int,
) -> dict[str, Any]:
    normalized = [endpoint.rstrip("/") for endpoint in endpoints]
    target_endpoint = target_endpoint.rstrip("/")
    if target_endpoint not in normalized:
        raise ValueError("target RPC endpoint must be one of --rpc-url values")
    if len(set(normalized)) < 4:
        raise ValueError("offline drill requires at least four validator RPC endpoints")
    before = _converge(normalized, timeout_seconds=timeout_seconds, greater_than=0)
    before_height = before[0]["height"]
    survivors = [endpoint for endpoint in normalized if endpoint != target_endpoint]
    _run_ssh(ssh_target, stop_command)
    try:
        _wait_until_unreachable(target_endpoint, timeout_seconds=timeout_seconds)
        during = _converge(
            survivors,
            timeout_seconds=timeout_seconds,
            greater_than=before_height + minimum_progress_blocks,
        )
    finally:
        _run_ssh(ssh_target, start_command)
    after = _converge(
        normalized,
        timeout_seconds=timeout_seconds,
        greater_than=max(item["height"] for item in during),
    )
    report = {
        "schema_version": 1,
        "status": "PASS",
        "scope": "CONTROLLED_LAN_TESTNET",
        "drill": "ONE_VALIDATOR_OFFLINE",
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "ssh_target": ssh_target,
        "offline_rpc_url": target_endpoint,
        "validator_rpc_urls": normalized,
        "before": before,
        "during_offline": during,
        "after_recovery": after,
        "checks": {
            "survivor_quorum_progressed": True,
            "all_validators_reconverged": True,
            "offline_validator_rejoined": True,
        },
    }
    report["report_hash"] = "sha256:" + hashlib.sha256(
        json.dumps(report, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rpc-url", action="append", required=True)
    parser.add_argument("--target-rpc-url", required=True)
    parser.add_argument("--ssh-target", required=True, help="SSH target with an already configured key/agent")
    parser.add_argument("--stop-command", required=True)
    parser.add_argument("--start-command", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=90)
    parser.add_argument("--minimum-progress-blocks", type=int, default=2)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.timeout_seconds <= 0 or args.minimum_progress_blocks < 1:
        raise ValueError("drill timeouts and progress blocks must be positive")
    try:
        report = run_offline_drill(
            endpoints=args.rpc_url,
            target_endpoint=args.target_rpc_url,
            ssh_target=args.ssh_target,
            stop_command=args.stop_command,
            start_command=args.start_command,
            timeout_seconds=args.timeout_seconds,
            minimum_progress_blocks=args.minimum_progress_blocks,
        )
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as error:
        print(json.dumps({"status": "FAIL", "reason": str(error)}, sort_keys=True))
        return 2
    encoded = json.dumps(report, ensure_ascii=True, indent=2) + "\n"
    print(encoded, end="")
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
