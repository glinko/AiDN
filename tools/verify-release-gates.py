#!/usr/bin/env python3
"""Run the machine-checkable subset of GATE-0001 without false positives."""

from __future__ import annotations

import argparse
import json
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
from aidn_hypervisor.evidence import EvidenceBundleError, verify_public_evidence_bundle


def _gate(status: str, *, reason: str | None = None, details: Any = None) -> dict[str, Any]:
    result: dict[str, Any] = {"status": status}
    if reason:
        result["reason"] = reason
    if details is not None:
        result["details"] = details
    return result


def _load_profile(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot load implementation profile: {error}") from error
    if not isinstance(value, dict):
        raise ValueError("implementation profile must be a JSON object")
    verify_implementation_profile(value)
    return value


def _run_g0(profile_path: Path) -> dict[str, Any]:
    try:
        profile = _load_profile(profile_path)
    except ValueError as error:
        return _gate("FAIL", reason=str(error))
    return _gate(
        "PASS",
        details={
            "profile_id": profile["profile_id"],
            "profile_version": profile["profile_version"],
            "profile_status": profile["status"],
            "activation_state": profile["activation_state"],
            "profile_commitment": profile["profile_commitment"],
        },
    )


def _run_g1(fixture_manifest: Path) -> dict[str, Any]:
    coverage_errors = {
        operation_type: strict_operation_coverage_error(operation_type)
        for operation_type in sorted(ACTIVE_OPERATION_TYPES)
        if strict_operation_coverage_error(operation_type) is not None
    }
    try:
        fixtures = run_fixture_set(fixture_manifest, strict=True)
    except FixtureError as error:
        return _gate(
            "FAIL",
            reason=str(error),
            details={"strict_operation_coverage_errors": coverage_errors},
        )
    if coverage_errors:
        return _gate(
            "INCOMPLETE",
            reason="known operation types remain outside strict consensus coverage",
            details={
                "strict_operation_coverage_errors": coverage_errors,
                "fixture_count": len(fixtures),
                "fixture_status": "PASS",
            },
        )
    return _gate(
        "PASS",
        details={
            "strict_operation_coverage": {
                "active": len(ACTIVE_OPERATION_TYPES),
                "supported": len(CONSENSUS_APPLIED_OPERATION_TYPES & ACTIVE_OPERATION_TYPES),
                "legacy_excluded": len(LEGACY_OPERATION_TYPES),
            },
            "fixture_count": len(fixtures),
        },
    )


def _not_run(reason: str) -> dict[str, Any]:
    return _gate("NOT_RUN", reason=reason)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile",
        type=Path,
        default=Path("profiles/aidn-mainnet-candidate-1.json"),
    )
    parser.add_argument("--fixture-manifest", type=Path, default=Path("fixtures/manifest.json"))
    parser.add_argument("--evidence-dir", type=Path)
    parser.add_argument("--require-evidence", action="append", default=[])
    parser.add_argument(
        "--allow-incomplete",
        action="store_true",
        help="return success for local development when operational gates are not complete",
    )
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    gates = {
        "G0": _run_g0(args.profile),
        "G1": _run_g1(args.fixture_manifest),
        "G2": _not_run("snapshot/state-sync operational evidence is not supplied"),
        "G3": _not_run("multi-node consensus evidence is not supplied"),
        "G4": _not_run("public networking evidence is not supplied"),
        "G5": _not_run("fault-recovery drill evidence is not supplied"),
        "G6": _not_run("independent operator attestations are not supplied"),
    }
    if args.evidence_dir is None:
        gates["G7"] = _not_run("use --evidence-dir to verify an EVD-0001 bundle")
    else:
        try:
            result = verify_public_evidence_bundle(
                args.evidence_dir,
                required_paths=args.require_evidence,
                require_attestation=True,
            )
        except EvidenceBundleError as error:
            gates["G7"] = _gate("FAIL", reason=str(error))
        else:
            gates["G7"] = _gate(
                "PASS",
                details={
                    "evidence_root": result.evidence_root,
                    "artifact_count": result.artifact_count,
                    "attestation_verified": result.attestation_verified,
                },
            )

    statuses = {name: value["status"] for name, value in gates.items()}
    if "FAIL" in statuses.values():
        overall_status = "FAIL"
        exit_code = 2
    elif all(status == "PASS" for status in statuses.values()):
        overall_status = "PASS"
        exit_code = 0
    else:
        overall_status = "INCOMPLETE"
        exit_code = 0 if args.allow_incomplete else 2
    payload = {
        "status": overall_status,
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "profile": str(args.profile),
        "fixture_manifest": str(args.fixture_manifest),
        "gates": gates,
    }
    encoded = json.dumps(payload, ensure_ascii=True, indent=2) + "\n"
    print(encoded, end="")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(encoded, encoding="utf-8")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
