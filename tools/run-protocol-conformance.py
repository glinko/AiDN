#!/usr/bin/env python3
"""Run the deterministic GATE-0001 protocol probes and emit a report."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aidn_hypervisor.consensus.coverage import (
    ACTIVE_OPERATION_TYPES,
    CONSENSUS_APPLIED_OPERATION_TYPES,
    LEGACY_OPERATION_TYPES,
    strict_operation_coverage_error,
)
from aidn_hypervisor.consensus.fixture_runner import FixtureError, run_fixture_set
from aidn_hypervisor.consensus.implementation_profile import verify_implementation_profile

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFORMANCE_TARGET = ROOT / "tests/consensus/test_release_conformance.py"
DEFAULT_UNIT_TARGETS = (
    "tests/consensus",
    "tests/settlement",
    "tests/ledger",
)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _load_object(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _run_pytest(targets: list[str]) -> dict[str, Any]:
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "--disable-warnings",
        "--no-cov",
        *targets,
    ]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    output = (completed.stdout + completed.stderr).strip()
    return {
        "status": "PASS" if completed.returncode == 0 else "FAIL",
        "return_code": completed.returncode,
        "command": command,
        "targets": targets,
        "output_tail": output[-4000:],
    }


def _check_fixture_and_coverage(manifest_path: Path) -> dict[str, Any]:
    coverage_errors = {
        operation_type: strict_operation_coverage_error(operation_type)
        for operation_type in sorted(ACTIVE_OPERATION_TYPES)
        if strict_operation_coverage_error(operation_type) is not None
    }
    try:
        fixtures = run_fixture_set(manifest_path, strict=True)
    except FixtureError as error:
        return {
            "status": "FAIL",
            "fixture_manifest_hash": _sha256_file(manifest_path),
            "strict_operation_coverage": {
                "status": "FAIL" if coverage_errors else "PASS",
                "active": len(ACTIVE_OPERATION_TYPES),
                "supported": len(CONSENSUS_APPLIED_OPERATION_TYPES & ACTIVE_OPERATION_TYPES),
                "legacy_excluded": len(LEGACY_OPERATION_TYPES),
                "errors": coverage_errors,
            },
            "fixture_count": 0,
            "error": str(error),
        }
    return {
        "status": "FAIL" if coverage_errors else "PASS",
        "fixture_manifest_hash": _sha256_file(manifest_path),
        "strict_operation_coverage": {
            "status": "FAIL" if coverage_errors else "PASS",
            "active": len(ACTIVE_OPERATION_TYPES),
            "supported": len(CONSENSUS_APPLIED_OPERATION_TYPES & ACTIVE_OPERATION_TYPES),
            "legacy_excluded": len(LEGACY_OPERATION_TYPES),
            "errors": coverage_errors,
        },
        "fixture_count": len(fixtures),
    }


def _status(*items: dict[str, Any]) -> str:
    return "PASS" if all(item.get("status") == "PASS" for item in items) else "FAIL"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile",
        type=Path,
        default=Path("profiles/aidn-mainnet-candidate-1.json"),
    )
    parser.add_argument("--fixture-manifest", type=Path, default=Path("fixtures/manifest.json"))
    parser.add_argument(
        "--unit-target",
        action="append",
        default=None,
        help="pytest target for the deterministic unit gate; repeat to override defaults",
    )
    parser.add_argument(
        "--conformance-target",
        type=Path,
        default=DEFAULT_CONFORMANCE_TARGET,
    )
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    try:
        profile = _load_object(args.profile, "implementation profile")
        verify_implementation_profile(profile)
        fixture_report = _check_fixture_and_coverage(args.fixture_manifest)
        conformance_target = str(args.conformance_target)
        conformance = _run_pytest([conformance_target])
        unit_targets = args.unit_target or list(DEFAULT_UNIT_TARGETS)
        unit = _run_pytest(unit_targets)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        payload: dict[str, Any] = {
            "schema_version": 1,
            "status": "FAIL",
            "error": str(error),
        }
    else:
        checks = {
            "unit_tests": unit,
            "fix_0001_fixtures": {
                "status": fixture_report["status"],
                "fixture_count": fixture_report.get("fixture_count", 0),
                "fixture_manifest_hash": fixture_report["fixture_manifest_hash"],
            },
            "strict_operation_coverage": fixture_report["strict_operation_coverage"],
            "unknown_operation_rejection": {
                "status": conformance["status"],
                "evidence": conformance_target,
            },
            "unsupported_operation_version": {
                "status": conformance["status"],
                "evidence": conformance_target,
            },
            "duplicate_operation_idempotency": {
                "status": conformance["status"],
                "evidence": conformance_target,
            },
            "predecessor_mismatch": {
                "status": conformance["status"],
                "evidence": conformance_target,
            },
            "monetary_boundaries": {
                "status": conformance["status"],
                "evidence": conformance_target,
            },
            "canonical_json_hash_vectors": {
                "status": conformance["status"],
                "evidence": conformance_target,
            },
        }
        payload = {
            "schema_version": 1,
            "status": _status(*checks.values()),
            "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "profile_id": profile["profile_id"],
            "profile_commitment": profile["profile_commitment"],
            "fixture_manifest": str(args.fixture_manifest),
            "fixture_manifest_hash": fixture_report["fixture_manifest_hash"],
            "checks": checks,
            "conformance_probe": conformance,
        }
    payload["report_hash"] = _sha256_bytes(_canonical_bytes(payload))
    encoded = json.dumps(payload, ensure_ascii=True, indent=2) + "\n"
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0 if payload["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
