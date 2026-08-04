#!/usr/bin/env python3
"""Build an EVD-0001 release bundle only after G0-G6 pass.

This is the safe release path.  It deliberately separates gate evaluation
from bundle creation so an incomplete public-network or operator-quorum
report cannot be turned into a misleading G7 artifact.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
GATE_TOOL = ROOT / "tools" / "verify-release-gates.py"
BUNDLE_TOOL = ROOT / "tools" / "build-public-evidence-bundle.py"
GATE_NAMES = tuple(f"G{index}" for index in range(8))
PRE_BUNDLE_GATES = tuple(f"G{index}" for index in range(7))


def _artifact_spec(value: str) -> tuple[Path, str]:
    source, separator, relative = value.partition("=")
    if not separator or not source or not relative:
        raise argparse.ArgumentTypeError("artifact must use SOURCE=relative/path")
    parsed = PurePosixPath(relative)
    if (
        parsed.is_absolute()
        or not parsed.parts
        or any(part in {".", ".."} for part in parsed.parts)
        or "\\" in relative
        or ":" in relative
        or relative in {"manifest.json", "attestations/operator-attestation.json", "gates/release-gate-result.json"}
    ):
        raise argparse.ArgumentTypeError("artifact destination must be a safe non-control POSIX path")
    return Path(source).expanduser(), relative


def _load_profile(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("profile_id"), str):
        raise ValueError("implementation profile must be a JSON object with profile_id")
    return value


def _gate_status(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and isinstance(value.get("status"), str):
        return value["status"]
    return None


def _python_environment() -> dict[str, str]:
    environment = os.environ.copy()
    source_path = str(ROOT / "src")
    current = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = source_path if not current else source_path + os.pathsep + current
    return environment


def _run_gate_verifier(
    args: argparse.Namespace,
    *,
    evidence_dir: Path | None,
    allow_incomplete: bool,
) -> dict[str, Any]:
    command = [
        sys.executable,
        str(GATE_TOOL),
        "--profile",
        str(args.profile),
        "--fixture-manifest",
        str(args.fixture_manifest),
    ]
    if allow_incomplete:
        command.append("--allow-incomplete")
    report_options = {
        "--g0-report": args.g0_report,
        "--g1-report": args.g1_report,
        "--g2-report": args.g2_report,
        "--g3-report": args.g3_report,
        "--g4-report": args.g4_report,
        "--g5-report": args.g5_report,
    }
    for option, report in report_options.items():
        if report is not None:
            command.extend([option, str(report)])
    for operator_dir in args.g6_evidence_dir:
        command.extend(["--g6-evidence-dir", str(operator_dir)])
    for reviewer_key in args.g6_review_key:
        command.extend(["--g6-review-key", reviewer_key])
    if evidence_dir is not None:
        command.extend(["--evidence-dir", str(evidence_dir)])
        for _, relative in args.artifact:
            command.extend(["--require-evidence", relative])

    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=_python_environment(),
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(
            "release gate verifier did not return JSON: "
            + (completed.stderr.strip() or completed.stdout.strip())
        ) from error
    if not isinstance(payload, dict) or not isinstance(payload.get("gates"), dict):
        raise RuntimeError("release gate verifier returned an invalid result")
    payload["verifier_exit_code"] = completed.returncode
    if completed.stderr.strip():
        payload["verifier_stderr"] = completed.stderr.strip()
    return payload


def _require_pre_bundle_pass(gate_result: dict[str, Any]) -> None:
    gates = gate_result["gates"]
    statuses = {name: _gate_status(gates.get(name)) for name in PRE_BUNDLE_GATES}
    failed = sorted(name for name, status in statuses.items() if status != "PASS")
    if failed:
        raise RuntimeError(
            "refusing to build release evidence bundle; G0-G6 are not all PASS: "
            + ", ".join(f"{name}={statuses[name]}" for name in failed)
        )


def _validate_g6_context(
    evidence_dirs: list[Path],
    *,
    network_id: str,
    release_version: str,
    profile_id: str,
) -> None:
    expected = {
        "network_id": network_id,
        "release_version": release_version,
        "profile_id": profile_id,
    }
    for evidence_dir in evidence_dirs:
        try:
            manifest = json.loads((evidence_dir / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ValueError(f"cannot load G6 evidence manifest: {error}") from error
        if not isinstance(manifest, dict):
            raise ValueError("G6 evidence manifest must be a JSON object")
        actual = {field: manifest.get(field) for field in expected}
        if actual != expected:
            raise ValueError(
                "G6 evidence bundle context does not match the requested release: "
                + json.dumps({"expected": expected, "actual": actual}, sort_keys=True)
            )


def _validate_g4_context(
    report_path: Path,
    *,
    network_id: str,
    release_version: str,
    profile_id: str,
) -> None:
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot load G4 report: {error}") from error
    if not isinstance(report, dict):
        raise ValueError("G4 report must be a JSON object")
    expected = {
        "network_id": network_id,
        "release_version": release_version,
        "profile_id": profile_id,
    }
    actual = {field: report.get(field) for field in expected}
    if actual != expected:
        raise ValueError(
            "G4 report context does not match the requested release: "
            + json.dumps({"expected": expected, "actual": actual}, sort_keys=True)
        )


def _build_bundle(args: argparse.Namespace, profile_id: str) -> dict[str, Any]:
    command = [
        sys.executable,
        str(BUNDLE_TOOL),
        "--output",
        str(args.output),
        "--network-id",
        args.network_id,
        "--release-version",
        args.release_version,
        "--profile-id",
        profile_id,
        "--operator-id",
        args.operator_id,
        "--control-group-id",
        args.control_group_id,
        "--independence-status",
        args.independence_status,
        "--private-key",
        str(args.private_key),
    ]
    for source, relative in args.artifact:
        command.extend(["--artifact", f"{source}={relative}"])
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=_python_environment(),
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(
            "EVD-0001 builder did not return JSON: "
            + (completed.stderr.strip() or completed.stdout.strip())
        ) from error
    if completed.returncode != 0 or payload.get("status") != "ok":
        raise RuntimeError("EVD-0001 builder failed: " + json.dumps(payload, sort_keys=True))
    return payload


def _write_gate_control(
    output: Path,
    *,
    gate_result: dict[str, Any],
    bundle_result: dict[str, Any],
    profile_id: str,
    network_id: str,
    release_version: str,
) -> Path:
    source_gates = gate_result["gates"]
    gates: dict[str, dict[str, Any]] = {
        name: {"status": "PASS"} for name in PRE_BUNDLE_GATES
    }
    gates["G7"] = {
        "status": "PASS",
        "evidence_root": bundle_result["evidence_root"],
        "artifact_count": bundle_result["artifact_count"],
    }
    control = {
        "schema_version": 1,
        "status": "PASS",
        "network_id": network_id,
        "release": release_version,
        "profile_id": profile_id,
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "gates": gates,
        "source_gate_statuses": {
            name: _gate_status(source_gates.get(name)) for name in PRE_BUNDLE_GATES
        },
        "evidence_root": bundle_result["evidence_root"],
    }
    path = output / "gates" / "release-gate-result.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(control, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return path


def _validate_paths(args: argparse.Namespace) -> None:
    output = args.output.expanduser().resolve()
    private_key = args.private_key.expanduser().resolve()
    if output == private_key or output in private_key.parents:
        raise ValueError("private signing key must not be inside the output bundle")
    destinations = [relative for _, relative in args.artifact]
    if len(destinations) != len(set(destinations)):
        raise ValueError("artifact destinations must be unique")
    for source, _ in args.artifact:
        resolved_source = source.expanduser().resolve()
        if output == resolved_source or output in resolved_source.parents:
            raise ValueError("artifact sources must not be inside the output bundle")
        if not resolved_source.is_file() or resolved_source.is_symlink():
            raise ValueError(f"artifact source is not a regular file: {resolved_source}")
    if not args.artifact:
        raise ValueError("at least one publishable artifact is required")
    if len(args.g6_evidence_dir) < 2:
        raise ValueError("at least two G6 operator evidence bundles are required")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--network-id", required=True)
    parser.add_argument("--release-version", required=True)
    parser.add_argument("--profile", type=Path, default=Path("profiles/aidn-mainnet-candidate-1.json"))
    parser.add_argument("--fixture-manifest", type=Path, default=Path("fixtures/manifest.json"))
    parser.add_argument("--g0-report", type=Path, required=True)
    parser.add_argument("--g1-report", type=Path, required=True)
    parser.add_argument("--g2-report", type=Path, required=True)
    parser.add_argument("--g3-report", type=Path, required=True)
    parser.add_argument("--g4-report", type=Path, required=True)
    parser.add_argument("--g5-report", type=Path, required=True)
    parser.add_argument("--g6-evidence-dir", action="append", type=Path, default=[])
    parser.add_argument(
        "--g6-review-key",
        action="append",
        default=[],
        metavar="REVIEWER_ID=ed25519:<64-hex>",
    )
    parser.add_argument("--operator-id", required=True)
    parser.add_argument("--control-group-id", required=True)
    parser.add_argument(
        "--independence-status",
        choices=("OUT_OF_BAND_DECLARED", "OUT_OF_BAND_VERIFIED"),
        default="OUT_OF_BAND_DECLARED",
    )
    parser.add_argument("--private-key", type=Path, required=True)
    parser.add_argument("--artifact", action="append", type=_artifact_spec, default=[])
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    try:
        _validate_paths(args)
        profile = _load_profile(args.profile)
        gate_result = _run_gate_verifier(args, evidence_dir=None, allow_incomplete=True)
        _require_pre_bundle_pass(gate_result)
        _validate_g6_context(
            args.g6_evidence_dir,
            network_id=args.network_id,
            release_version=args.release_version,
            profile_id=profile["profile_id"],
        )
        _validate_g4_context(
            args.g4_report,
            network_id=args.network_id,
            release_version=args.release_version,
            profile_id=profile["profile_id"],
        )
        bundle_result = _build_bundle(args, profile["profile_id"])
        _write_gate_control(
            args.output.expanduser().resolve(),
            gate_result=gate_result,
            bundle_result=bundle_result,
            profile_id=profile["profile_id"],
            network_id=args.network_id,
            release_version=args.release_version,
        )
        final_result = _run_gate_verifier(
            args,
            evidence_dir=args.output.expanduser().resolve(),
            allow_incomplete=False,
        )
        if final_result.get("status") != "PASS" or any(
            _gate_status(final_result["gates"].get(name)) != "PASS" for name in GATE_NAMES
        ):
            raise RuntimeError(
                "final G7 verification did not PASS: "
                + json.dumps(final_result, ensure_ascii=True, sort_keys=True)
            )
        result = {
            "status": "PASS",
            "evidence_dir": str(args.output.expanduser().resolve()),
            "evidence_root": bundle_result["evidence_root"],
            "artifact_count": bundle_result["artifact_count"],
            "gates": dict.fromkeys(GATE_NAMES, "PASS"),
        }
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        result = {"status": "INCOMPLETE", "reason": str(error)}
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(result, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=True, sort_keys=True))
        return 2

    encoded = json.dumps(result, ensure_ascii=True, indent=2) + "\n"
    print(encoded, end="")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(encoded, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
