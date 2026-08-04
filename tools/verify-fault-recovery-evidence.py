#!/usr/bin/env python3
"""Validate the machine-readable G5 fault-recovery evidence contract.

The command combines the signed/hashed controlled-local G2 report with a
separately collected live fault report.  It never turns missing operator
observations into a successful drill.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aidn_hypervisor.consensus.snapshot_acceptance import (
    SnapshotAcceptanceError,
    load_and_verify_snapshot_acceptance_report,
)

REQUIRED_LIVE_DRILLS = (
    "graceful_restart",
    "abrupt_process_termination",
    "host_reboot",
    "stale_predecessor_rejected",
)
REQUIRED_G2_DRILLS = (
    "snapshot_restore",
    "state_sync",
    "invalid_snapshot_rejected",
)
_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def _load_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot load {label}: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _pass_drill(name: str, evidence_reference: str) -> dict[str, str]:
    if not _HASH_RE.fullmatch(evidence_reference):
        raise ValueError(f"{name} evidence reference must not be empty")
    return {"status": "PASS", "evidence_reference": evidence_reference}


def _report_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _finish_report(payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    result["report_hash"] = _report_hash(result)
    return result


def _validate_snapshot(snapshot: object, *, label: str) -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        raise ValueError(f"{label} must be an object")
    height = snapshot.get("height")
    app_hash = snapshot.get("app_hash")
    if (
        not isinstance(snapshot.get("rpc_url"), str)
        or not snapshot["rpc_url"]
        or not isinstance(height, int)
        or isinstance(height, bool)
        or height < 1
        or not isinstance(app_hash, str)
        or not re.fullmatch(r"[0-9A-Fa-f]{64}", app_hash)
        or not isinstance(snapshot.get("node_id"), str)
        or not snapshot["node_id"]
        or not isinstance(snapshot.get("chain_id"), str)
        or not snapshot["chain_id"]
    ):
        raise ValueError(f"{label} is invalid")
    if "catching_up" in snapshot and not isinstance(snapshot["catching_up"], bool):
        raise ValueError(f"{label} catching_up field is invalid")
    return snapshot


def _validate_snapshot_set(
    value: object,
    *,
    label: str,
    expected_urls: set[str],
) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) != len(expected_urls):
        raise ValueError(f"{label} must contain every validator snapshot exactly once")
    snapshots = [_validate_snapshot(item, label=f"{label}[{index}]") for index, item in enumerate(value)]
    urls = {item["rpc_url"].rstrip("/") for item in snapshots}
    if urls != expected_urls:
        raise ValueError(f"{label} does not match the declared validator RPC set")
    if len({item["node_id"] for item in snapshots}) != len(snapshots):
        raise ValueError(f"{label} contains duplicate validator identities")
    if len({item["chain_id"] for item in snapshots}) != 1:
        raise ValueError(f"{label} validators disagree on chain ID")
    if len({item["height"] for item in snapshots}) != 1:
        raise ValueError(f"{label} validators do not converge on one height")
    if len({item["app_hash"].upper() for item in snapshots}) != 1:
        raise ValueError(f"{label} validators do not converge on one AppHash")
    if any(item.get("catching_up") is True for item in snapshots):
        raise ValueError(f"{label} contains a validator still catching up")
    return snapshots


def _verify_action_drill(
    name: str,
    value: object,
    *,
    expected_urls: set[str],
    target_url: str,
) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("status") != "PASS":
        raise ValueError(f"live fault drill is not PASS: {name}")
    reference = value.get("evidence_reference")
    if not isinstance(reference, str) or not _HASH_RE.fullmatch(reference):
        raise ValueError(f"live fault drill lacks a valid evidence_reference: {name}")
    if not isinstance(value.get("command"), str) or not value["command"].strip():
        raise ValueError(f"live fault drill lacks a command: {name}")
    command_result = value.get("command_result")
    if not isinstance(command_result, dict):
        raise ValueError(f"live fault drill lacks command result: {name}")
    returncode = command_result.get("returncode")
    if returncode is not None and (not isinstance(returncode, int) or isinstance(returncode, bool) or returncode != 0):
        raise ValueError(f"live fault drill command failed: {name}")
    if not isinstance(value.get("outage_observed"), bool):
        raise ValueError(f"live fault drill outage observation is invalid: {name}")
    checks = value.get("checks")
    required_checks = {
        "all_validators_reconverged",
        "target_identity_preserved",
        "target_chain_preserved",
    }
    if not isinstance(checks, dict) or any(checks.get(check) is not True for check in required_checks):
        raise ValueError(f"live fault drill checks are incomplete: {name}")
    before = _validate_snapshot_set(value.get("before"), label=f"{name}.before", expected_urls=expected_urls)
    after = _validate_snapshot_set(value.get("after"), label=f"{name}.after", expected_urls=expected_urls)
    if min(item["height"] for item in after) <= max(item["height"] for item in before):
        raise ValueError(f"live fault drill did not advance after recovery: {name}")
    before_target = next(item for item in before if item["rpc_url"].rstrip("/") == target_url)
    after_target = next(item for item in after if item["rpc_url"].rstrip("/") == target_url)
    if before_target["node_id"] != after_target["node_id"]:
        raise ValueError(f"live fault drill changed target identity: {name}")
    if before_target["chain_id"] != after_target["chain_id"]:
        raise ValueError(f"live fault drill changed target chain: {name}")
    if name == "host_reboot":
        if value.get("outage_observed") is not True:
            raise ValueError("host_reboot did not prove an outage")
        recovery_command = value.get("recovery_command")
        recovery_result = value.get("recovery_result")
        if (
            not isinstance(recovery_command, str)
            or not recovery_command.strip()
            or not isinstance(recovery_result, dict)
            or recovery_result.get("returncode") != 0
        ):
            raise ValueError("host_reboot recovery command evidence is incomplete")
    return value


def _verify_stale_predecessor(value: object, *, target_url: str) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("status") != "PASS":
        raise ValueError("stale predecessor drill is not PASS")
    if value.get("scope") != "CONTROLLED_LAN_TESTNET" or value.get("drill") != "STALE_PREDECESSOR_REJECTED":
        raise ValueError("stale predecessor drill scope is invalid")
    reference = value.get("evidence_reference")
    if not isinstance(reference, str) or not _HASH_RE.fullmatch(reference):
        raise ValueError("stale predecessor drill lacks a valid evidence_reference")
    rpc_url = value.get("rpc_url")
    if not isinstance(rpc_url, str) or rpc_url.rstrip("/") != target_url:
        raise ValueError("stale predecessor drill target RPC does not match live report")
    before = _validate_snapshot(value.get("before"), label="stale_predecessor_rejected.before")
    after = _validate_snapshot(value.get("after"), label="stale_predecessor_rejected.after")
    if after["height"] <= before["height"]:
        raise ValueError("stale predecessor drill did not advance after rejection")
    if before["node_id"] != after["node_id"] or before["chain_id"] != after["chain_id"]:
        raise ValueError("stale predecessor drill changed validator identity")
    source_hash = value.get("source_transaction_hash")
    rejection = value.get("rejection")
    if (
        not isinstance(source_hash, str)
        or not re.fullmatch(r"[0-9A-Fa-f]{64}", source_hash)
        or not isinstance(rejection, dict)
        or not isinstance(rejection.get("transaction_hash"), str)
        or not re.fullmatch(r"[0-9A-Fa-f]{64}", rejection["transaction_hash"])
        or not isinstance(rejection.get("code"), int)
        or isinstance(rejection["code"], bool)
        or rejection["code"] == 0
        or not isinstance(rejection.get("log"), str)
        or not rejection["log"]
    ):
        raise ValueError("stale predecessor rejection evidence is invalid")
    checks = value.get("checks")
    if not isinstance(checks, dict) or any(
        checks.get(check) is not True
        for check in ("transaction_rejected", "funding_predecessor_error", "validator_identity_preserved")
    ):
        raise ValueError("stale predecessor checks are incomplete")
    return value


def _verify_live_drills(path: Path) -> dict[str, dict[str, Any]]:
    report = _load_object(path, label="live fault report")
    if report.get("schema_version") != 1 or report.get("status") != "PASS":
        raise ValueError("live fault report status must be PASS")
    if report.get("scope") != "CONTROLLED_LAN_TESTNET":
        raise ValueError("live fault report scope is invalid")
    validator_urls = report.get("validator_rpc_urls")
    if not isinstance(validator_urls, list) or len(validator_urls) < 4:
        raise ValueError("live fault report must declare at least four validator RPC URLs")
    if any(not isinstance(url, str) or not url.strip() for url in validator_urls):
        raise ValueError("live fault report validator RPC URLs are invalid")
    expected_urls = {url.rstrip("/") for url in validator_urls}
    if len(expected_urls) != len(validator_urls):
        raise ValueError("live fault report validator RPC URLs are invalid")
    target_url = report.get("target_rpc_url")
    if not isinstance(target_url, str) or target_url.rstrip("/") not in expected_urls:
        raise ValueError("live fault report target RPC URL is invalid")
    report_hash = report.get("report_hash")
    unsigned_report = dict(report)
    unsigned_report.pop("report_hash", None)
    if not isinstance(report_hash, str) or report_hash != _report_hash(unsigned_report):
        raise ValueError("live fault report hash is invalid")
    drills = report.get("drills")
    if not isinstance(drills, dict):
        raise ValueError("live fault report must contain a drills object")
    result: dict[str, dict[str, Any]] = {}
    for name in REQUIRED_LIVE_DRILLS[:-1]:
        result[name] = _verify_action_drill(
            name,
            drills.get(name),
            expected_urls=expected_urls,
            target_url=target_url.rstrip("/"),
        )
    result[REQUIRED_LIVE_DRILLS[-1]] = _verify_stale_predecessor(
        drills.get(REQUIRED_LIVE_DRILLS[-1]),
        target_url=target_url.rstrip("/"),
    )
    return result


def verify_fault_recovery_evidence(
    *,
    g2_report_path: Path,
    live_report_path: Path | None,
) -> dict[str, Any]:
    """Build a G5 report without accepting an incomplete recovery set."""
    try:
        g2_report = load_and_verify_snapshot_acceptance_report(g2_report_path)
    except SnapshotAcceptanceError as error:
        raise ValueError(f"G2 source report is invalid: {error}") from error

    checks = g2_report.get("checks")
    if not isinstance(checks, dict):
        raise ValueError("G2 source report does not contain checks")
    g2_drills: dict[str, dict[str, str]] = {}
    for name in REQUIRED_G2_DRILLS:
        check_name = {
            "snapshot_restore": "restore_yields_identical_app_hash",
            "state_sync": "state_sync_yields_identical_app_hash",
            "invalid_snapshot_rejected": "corrupt_snapshot_rejected",
        }[name]
        if checks.get(check_name) is not True:
            raise ValueError(f"G2 source report does not prove {name}")
        g2_drills[name] = _pass_drill(name, str(g2_report["report_hash"]))

    if live_report_path is None:
        return _finish_report({
            "schema_version": 1,
            "status": "INCOMPLETE",
            "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "g2_report": str(g2_report_path),
            "g2_report_hash": g2_report["report_hash"],
            "drills": g2_drills,
            "missing_live_drills": list(REQUIRED_LIVE_DRILLS),
        })

    live_drills = _verify_live_drills(live_report_path)
    live_report = _load_object(live_report_path, label="live fault report")
    return _finish_report({
        "schema_version": 1,
        "status": "PASS",
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "g2_report": str(g2_report_path),
        "g2_report_hash": g2_report["report_hash"],
        "live_report": str(live_report_path),
        "live_report_hash": live_report["report_hash"],
        "drills": {**g2_drills, **live_drills},
    })


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--g2-report", type=Path, required=True)
    parser.add_argument("--live-report", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = verify_fault_recovery_evidence(
            g2_report_path=args.g2_report,
            live_report_path=args.live_report,
        )
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
