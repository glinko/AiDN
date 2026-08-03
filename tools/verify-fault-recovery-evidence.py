#!/usr/bin/env python3
"""Validate the machine-readable G5 fault-recovery evidence contract.

The command combines the signed/hashed controlled-local G2 report with a
separately collected live fault report.  It never turns missing operator
observations into a successful drill.
"""

from __future__ import annotations

import argparse
import json
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


def _load_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot load {label}: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _pass_drill(name: str, evidence_reference: str) -> dict[str, str]:
    if not evidence_reference:
        raise ValueError(f"{name} evidence reference must not be empty")
    return {"status": "PASS", "evidence_reference": evidence_reference}


def _verify_live_drills(path: Path) -> dict[str, dict[str, Any]]:
    report = _load_object(path, label="live fault report")
    if report.get("status") != "PASS":
        raise ValueError("live fault report status must be PASS")
    drills = report.get("drills")
    if not isinstance(drills, dict):
        raise ValueError("live fault report must contain a drills object")
    result: dict[str, dict[str, Any]] = {}
    for name in REQUIRED_LIVE_DRILLS:
        value = drills.get(name)
        if not isinstance(value, dict) or value.get("status") != "PASS":
            raise ValueError(f"live fault drill is not PASS: {name}")
        reference = value.get("evidence_reference")
        if not isinstance(reference, str) or not reference:
            raise ValueError(f"live fault drill lacks evidence_reference: {name}")
        result[name] = value
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
        return {
            "schema_version": 1,
            "status": "INCOMPLETE",
            "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "g2_report": str(g2_report_path),
            "g2_report_hash": g2_report["report_hash"],
            "drills": g2_drills,
            "missing_live_drills": list(REQUIRED_LIVE_DRILLS),
        }

    live_drills = _verify_live_drills(live_report_path)
    return {
        "schema_version": 1,
        "status": "PASS",
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "g2_report": str(g2_report_path),
        "g2_report_hash": g2_report["report_hash"],
        "live_report": str(live_report_path),
        "drills": {**g2_drills, **live_drills},
    }


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
