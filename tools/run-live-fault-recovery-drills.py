"""Collect controlled live validator fault-recovery evidence.

All state-changing actions are explicit operator-supplied commands. The tool
does not contain credentials or destructive defaults. It verifies that the
configured validator set reconverges after each action and that the target
validator keeps its identity and chain.
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
        "catching_up": bool(sync_info.get("catching_up")),
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


def _run_ssh(command: str, *, ssh_target: str, timeout_seconds: int, allow_disconnect: bool) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            ["ssh", ssh_target, command],
            check=False,
            capture_output=True,
            text=True,
            timeout=max(timeout_seconds, 10),
        )
        return {
            "returncode": completed.returncode,
            "stdout": completed.stdout[-4000:],
            "stderr": completed.stderr[-4000:],
            "disconnect_allowed": allow_disconnect,
        }
    except subprocess.TimeoutExpired as error:
        if not allow_disconnect:
            raise RuntimeError(f"SSH command timed out: {command}") from error
        return {
            "returncode": None,
            "stdout": str(error.stdout or "")[-4000:],
            "stderr": str(error.stderr or "")[-4000:],
            "disconnect_allowed": True,
            "timed_out": True,
        }


def _run_ssh_with_outage_observation(
    command: str,
    *,
    ssh_target: str,
    target_endpoint: str,
    timeout_seconds: int,
    allow_disconnect: bool,
) -> tuple[dict[str, Any], bool]:
    process = subprocess.Popen(
        ["ssh", ssh_target, command],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    outage_observed = False
    deadline = time.monotonic() + max(timeout_seconds, 10)
    while process.poll() is None:
        if not outage_observed:
            try:
                _status(target_endpoint)
            except (OSError, RuntimeError, ValueError, json.JSONDecodeError):
                outage_observed = True
        if time.monotonic() >= deadline:
            process.kill()
            stdout, stderr = process.communicate()
            raise RuntimeError(
                f"SSH command timed out: {command}; "
                f"stdout={stdout[-1000:]}; stderr={stderr[-1000:]}"
            )
        time.sleep(0.5)
    stdout, stderr = process.communicate()
    return {
        "returncode": process.returncode,
        "stdout": stdout[-4000:],
        "stderr": stderr[-4000:],
        "disconnect_allowed": allow_disconnect,
    }, outage_observed


def _observe_unreachable(endpoint: str, *, timeout_seconds: int) -> bool:
    deadline = time.monotonic() + min(timeout_seconds, 15)
    while time.monotonic() < deadline:
        try:
            _status(endpoint)
        except (OSError, RuntimeError, ValueError, json.JSONDecodeError):
            return True
        time.sleep(0.5)
    return False


def _run_live_action(
    *,
    name: str,
    command: str,
    ssh_target: str,
    endpoints: list[str],
    target_endpoint: str,
    timeout_seconds: int,
    allow_disconnect: bool,
    post_recovery_command: str | None = None,
) -> dict[str, Any]:
    before = _converge(endpoints, timeout_seconds=timeout_seconds, greater_than=0)
    before_target = next(item for item in before if item["rpc_url"] == target_endpoint)
    observe_during_command = name in {"graceful_restart", "abrupt_process_termination"}
    if observe_during_command:
        command_result, command_outage_observed = _run_ssh_with_outage_observation(
            command,
            ssh_target=ssh_target,
            target_endpoint=target_endpoint,
            timeout_seconds=timeout_seconds,
            allow_disconnect=allow_disconnect,
        )
    else:
        command_result = _run_ssh(
            command,
            ssh_target=ssh_target,
            timeout_seconds=timeout_seconds,
            allow_disconnect=allow_disconnect,
        )
        command_outage_observed = False
    if command_result.get("returncode") not in (0, None) and not allow_disconnect:
        raise RuntimeError(f"{name} command failed: {command_result}")
    outage_observed = command_outage_observed or _observe_unreachable(
        target_endpoint, timeout_seconds=timeout_seconds
    )
    if name == "host_reboot" and not outage_observed:
        raise RuntimeError("host_reboot did not make the target RPC unavailable")
    recovery_result: dict[str, Any] | None = None
    if post_recovery_command is not None:
        recovery_result = _run_ssh(
            post_recovery_command,
            ssh_target=ssh_target,
            timeout_seconds=timeout_seconds,
            allow_disconnect=False,
        )
        if recovery_result.get("returncode") != 0:
            raise RuntimeError(f"{name} recovery command failed: {recovery_result}")
    after = _converge(
        endpoints,
        timeout_seconds=timeout_seconds,
        greater_than=max(item["height"] for item in before),
    )
    after_target = next(item for item in after if item["rpc_url"] == target_endpoint)
    if after_target["node_id"] != before_target["node_id"]:
        raise RuntimeError(f"{name} changed the target validator node identity")
    if after_target["chain_id"] != before_target["chain_id"]:
        raise RuntimeError(f"{name} changed the target validator chain identity")
    result = {
        "status": "PASS",
        "evidence_reference": "pending",
        "command": command,
        "command_result": command_result,
        "command_outage_observed": command_outage_observed,
        "outage_observed": outage_observed,
        "recovery_command": post_recovery_command,
        "recovery_result": recovery_result,
        "before": before,
        "after": after,
        "checks": {
            "all_validators_reconverged": True,
            "target_identity_preserved": True,
            "target_chain_preserved": True,
        },
    }
    result["evidence_reference"] = "sha256:" + hashlib.sha256(
        json.dumps(result, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return result


def _run_stale_command(command: str) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        shell=True,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"stale predecessor command failed: {completed.stderr[-2000:] or completed.stdout[-2000:]}"
        )
    candidates = [completed.stdout.strip()]
    candidates.extend(
        line.strip() for line in completed.stdout.splitlines() if line.strip()
    )
    for line in reversed(candidates):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.get("status") == "PASS":
            reference = value.get("evidence_reference")
            if isinstance(reference, str) and reference:
                return value
    raise RuntimeError("stale predecessor command did not emit a PASS JSON report")


def run_live_fault_recovery_drills(
    *,
    endpoints: list[str],
    target_endpoint: str,
    ssh_target: str,
    graceful_command: str,
    abrupt_command: str,
    host_reboot_command: str,
    stale_predecessor_command: str,
    timeout_seconds: int,
    host_reboot_recovery_command: str,
) -> dict[str, Any]:
    normalized = [endpoint.rstrip("/") for endpoint in endpoints]
    if len(set(normalized)) < 4:
        raise ValueError("live G5 drill requires at least four validator RPC endpoints")
    target_endpoint = target_endpoint.rstrip("/")
    if target_endpoint not in normalized:
        raise ValueError("target RPC endpoint must be one of --rpc-url values")
    if not host_reboot_recovery_command.strip():
        raise ValueError("host reboot recovery command is required for live G5")
    drills: dict[str, Any] = {}
    drills["graceful_restart"] = _run_live_action(
        name="graceful_restart",
        command=graceful_command,
        ssh_target=ssh_target,
        endpoints=normalized,
        target_endpoint=target_endpoint,
        timeout_seconds=timeout_seconds,
        allow_disconnect=False,
    )
    drills["abrupt_process_termination"] = _run_live_action(
        name="abrupt_process_termination",
        command=abrupt_command,
        ssh_target=ssh_target,
        endpoints=normalized,
        target_endpoint=target_endpoint,
        timeout_seconds=timeout_seconds,
        allow_disconnect=False,
    )
    drills["host_reboot"] = _run_live_action(
        name="host_reboot",
        command=host_reboot_command,
        ssh_target=ssh_target,
        endpoints=normalized,
        target_endpoint=target_endpoint,
        timeout_seconds=timeout_seconds,
        allow_disconnect=True,
        post_recovery_command=host_reboot_recovery_command,
    )
    drills["stale_predecessor_rejected"] = _run_stale_command(stale_predecessor_command)
    report = {
        "schema_version": 1,
        "status": "PASS",
        "scope": "CONTROLLED_LAN_TESTNET",
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "ssh_target": ssh_target,
        "validator_rpc_urls": normalized,
        "target_rpc_url": target_endpoint,
        "drills": drills,
    }
    report["report_hash"] = "sha256:" + hashlib.sha256(
        json.dumps(report, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rpc-url", action="append", required=True)
    parser.add_argument("--target-rpc-url", required=True)
    parser.add_argument("--ssh-target", required=True)
    parser.add_argument("--graceful-command", required=True)
    parser.add_argument("--abrupt-command", required=True)
    parser.add_argument("--host-reboot-command", required=True)
    parser.add_argument("--stale-predecessor-command", required=True)
    parser.add_argument(
        "--host-reboot-recovery-command",
        required=True,
        help="Explicit command run after the host reboot outage before convergence is checked",
    )
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.timeout_seconds <= 0:
        raise ValueError("timeout-seconds must be positive")
    try:
        report = run_live_fault_recovery_drills(
            endpoints=args.rpc_url,
            target_endpoint=args.target_rpc_url,
            ssh_target=args.ssh_target,
            graceful_command=args.graceful_command,
            abrupt_command=args.abrupt_command,
            host_reboot_command=args.host_reboot_command,
            stale_predecessor_command=args.stale_predecessor_command,
            host_reboot_recovery_command=args.host_reboot_recovery_command,
            timeout_seconds=args.timeout_seconds,
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
