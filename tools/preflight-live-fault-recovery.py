#!/usr/bin/env python3
"""Run read-only preflight checks before controlled live G5 fault drills.

The preflight validates RPC reachability, SSH connectivity and operator-owned
read-only checks for every later state-changing command. It never executes the
declared drill or recovery commands themselves.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib import request as urllib_request

REQUIRED_DRILLS = (
    "graceful_restart",
    "abrupt_process_termination",
    "host_reboot",
    "stale_predecessor_rejected",
)
_ALLOWED_TRANSPORTS = {"local", "ssh"}


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _load_config(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot load preflight config: {error}") from error
    if not isinstance(value, dict):
        raise ValueError("preflight config must be a JSON object")
    return value


def _non_empty_string(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _validate_preflight(value: object, *, label: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    transport = _non_empty_string(value.get("transport"), label=f"{label}.transport")
    if transport not in _ALLOWED_TRANSPORTS:
        raise ValueError(f"{label}.transport must be local or ssh")
    command = _non_empty_string(value.get("command"), label=f"{label}.command")
    return {"transport": transport, "command": command}


def _validate_action(name: str, value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"commands.{name} must be an object")
    action = {
        "command": _non_empty_string(value.get("command"), label=f"commands.{name}.command"),
        "preflight": _validate_preflight(value.get("preflight"), label=f"commands.{name}.preflight"),
    }
    if name == "host_reboot":
        action["recovery_command"] = _non_empty_string(
            value.get("recovery_command"),
            label="commands.host_reboot.recovery_command",
        )
        action["recovery_preflight"] = _validate_preflight(
            value.get("recovery_preflight"),
            label="commands.host_reboot.recovery_preflight",
        )
    return action


def _validated_config(config: dict[str, Any]) -> dict[str, Any]:
    if config.get("schema_version") != 1:
        raise ValueError("preflight config schema_version is unsupported")
    if config.get("scope") != "CONTROLLED_LAN_TESTNET":
        raise ValueError("preflight config scope must be CONTROLLED_LAN_TESTNET")
    ssh_target = _non_empty_string(config.get("ssh_target"), label="ssh_target")
    urls = config.get("validator_rpc_urls")
    if not isinstance(urls, list) or len(urls) < 4:
        raise ValueError("validator_rpc_urls must contain at least four endpoints")
    normalized_urls = [_non_empty_string(url, label="validator_rpc_urls item").rstrip("/") for url in urls]
    if len(set(normalized_urls)) != len(normalized_urls):
        raise ValueError("validator_rpc_urls must be unique")
    target = _non_empty_string(config.get("target_rpc_url"), label="target_rpc_url").rstrip("/")
    if target not in normalized_urls:
        raise ValueError("target_rpc_url must be one of validator_rpc_urls")
    raw_commands = config.get("commands")
    if not isinstance(raw_commands, dict):
        raise ValueError("commands must be an object")
    commands = {name: _validate_action(name, raw_commands.get(name)) for name in REQUIRED_DRILLS}
    return {
        "scope": config["scope"],
        "ssh_target": ssh_target,
        "validator_rpc_urls": normalized_urls,
        "target_rpc_url": target,
        "commands": commands,
    }


def _rpc_status(endpoint: str) -> dict[str, Any]:
    try:
        with urllib_request.urlopen(f"{endpoint}/status", timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        return {"status": "FAIL", "rpc_url": endpoint, "reason": str(error)}
    if not isinstance(payload, dict) or payload.get("error"):
        return {"status": "FAIL", "rpc_url": endpoint, "reason": "RPC returned an error"}
    result = payload.get("result")
    if not isinstance(result, dict):
        return {"status": "FAIL", "rpc_url": endpoint, "reason": "RPC result is invalid"}
    sync_info = result.get("sync_info")
    node_info = result.get("node_info")
    if not isinstance(sync_info, dict) or not isinstance(node_info, dict):
        return {"status": "FAIL", "rpc_url": endpoint, "reason": "RPC status is incomplete"}
    try:
        height = int(sync_info.get("latest_block_height") or 0)
    except (TypeError, ValueError):
        return {"status": "FAIL", "rpc_url": endpoint, "reason": "RPC height is invalid"}
    node_id = node_info.get("id")
    chain_id = node_info.get("network")
    if height < 1 or not isinstance(node_id, str) or not node_id or not isinstance(chain_id, str) or not chain_id:
        return {"status": "FAIL", "rpc_url": endpoint, "reason": "RPC identity or height is invalid"}
    return {
        "status": "PASS",
        "rpc_url": endpoint,
        "height": height,
        "app_hash": str(sync_info.get("latest_app_hash") or "").upper(),
        "node_id": node_id,
        "chain_id": chain_id,
        "catching_up": bool(sync_info.get("catching_up")),
    }


def _run_probe(
    command: str,
    *,
    transport: str,
    ssh_target: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    argv = (
        ["ssh", ssh_target, "bash", "-lc", shlex.quote(command)]
        if transport == "ssh"
        else command
    )
    try:
        completed = subprocess.run(
            argv,
            shell=transport == "local",
            check=False,
            capture_output=True,
            text=True,
            timeout=max(timeout_seconds, 10),
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return {
            "status": "FAIL",
            "returncode": None,
            "timed_out": isinstance(error, subprocess.TimeoutExpired),
            "reason": type(error).__name__,
        }
    return {
        "status": "PASS" if completed.returncode == 0 else "FAIL",
        "returncode": completed.returncode,
        "stdout_present": bool(completed.stdout),
        "stderr_present": bool(completed.stderr),
        "stdout_hash": _canonical_hash(completed.stdout),
        "stderr_hash": _canonical_hash(completed.stderr),
    }


def _probe_record(
    command: str,
    preflight: dict[str, str],
    *,
    ssh_target: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    result = _run_probe(
        preflight["command"],
        transport=preflight["transport"],
        ssh_target=ssh_target,
        timeout_seconds=timeout_seconds,
    )
    return {
        "status": result["status"],
        "command_hash": _canonical_hash(command),
        "preflight_hash": _canonical_hash(preflight["command"]),
        "transport": preflight["transport"],
        "result": result,
    }


def run_preflight(*, config_path: Path, timeout_seconds: int = 30) -> dict[str, Any]:
    config = _validated_config(_load_config(config_path))
    rpc_statuses = [_rpc_status(url) for url in config["validator_rpc_urls"]]
    rpc_pass = all(item.get("status") == "PASS" for item in rpc_statuses)
    pass_statuses = [item for item in rpc_statuses if item.get("status") == "PASS"]
    common_chain = len({item["chain_id"] for item in pass_statuses}) == 1 if pass_statuses else False
    unique_nodes = len({item["node_id"] for item in pass_statuses}) == len(pass_statuses)
    not_catching_up = all(item.get("catching_up") is False for item in pass_statuses)

    ssh_probe = _run_probe(
        "printf '%s' aidn-g5-preflight",
        transport="ssh",
        ssh_target=config["ssh_target"],
        timeout_seconds=timeout_seconds,
    )
    commands: dict[str, Any] = {}
    command_pass = True
    for name in REQUIRED_DRILLS:
        action = config["commands"][name]
        record = _probe_record(
            action["command"],
            action["preflight"],
            ssh_target=config["ssh_target"],
            timeout_seconds=timeout_seconds,
        )
        if name == "host_reboot":
            record["recovery"] = _probe_record(
                action["recovery_command"],
                action["recovery_preflight"],
                ssh_target=config["ssh_target"],
                timeout_seconds=timeout_seconds,
            )
            if record["recovery"]["status"] != "PASS":
                command_pass = False
        commands[name] = record
        if record["status"] != "PASS":
            command_pass = False

    all_checks_pass = (
        rpc_pass
        and common_chain
        and unique_nodes
        and not_catching_up
        and ssh_probe["status"] == "PASS"
        and command_pass
    )
    status = "PASS" if all_checks_pass else "FAIL"
    report = {
        "schema_version": 1,
        "status": status,
        "scope": config["scope"],
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "ssh_target": config["ssh_target"],
        "validator_rpc_urls": config["validator_rpc_urls"],
        "target_rpc_url": config["target_rpc_url"],
        "rpc_statuses": rpc_statuses,
        "rpc_checks": {
            "all_reachable": rpc_pass,
            "common_chain": common_chain,
            "unique_node_ids": unique_nodes,
            "not_catching_up": not_catching_up,
        },
        "ssh_connectivity": ssh_probe,
        "commands": commands,
        "read_only": True,
    }
    report["report_hash"] = _canonical_hash(report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.timeout_seconds <= 0:
        raise ValueError("timeout-seconds must be positive")
    try:
        report = run_preflight(config_path=args.config, timeout_seconds=args.timeout_seconds)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "FAIL", "reason": str(error)}, sort_keys=True))
        return 2
    encoded = json.dumps(report, ensure_ascii=True, indent=2) + "\n"
    print(encoded, end="")
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
