#!/usr/bin/env python3
"""Run the machine-checkable subset of GATE-0001 without false positives."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from aidn_hypervisor.consensus.coverage import (
    ACTIVE_OPERATION_TYPES,
    CONSENSUS_APPLIED_OPERATION_TYPES,
    LEGACY_OPERATION_TYPES,
    strict_operation_coverage_error,
)
from aidn_hypervisor.consensus.finality import ConsensusFinalityEvidence
from aidn_hypervisor.consensus.fixture_runner import FixtureError, run_fixture_set
from aidn_hypervisor.consensus.implementation_profile import verify_implementation_profile
from aidn_hypervisor.consensus.snapshot_acceptance import (
    SnapshotAcceptanceError,
    load_and_verify_snapshot_acceptance_report,
)
from aidn_hypervisor.evidence import (
    ATTESTATION_PATH,
    GATE_RESULT_PATH,
    INDEPENDENCE_REVIEW_PATH,
    EvidenceBundleError,
    canonical_json_bytes,
    verify_public_evidence_bundle,
)

_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


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


def _load_g5_verifier() -> Any:
    path = Path(__file__).with_name("verify-fault-recovery-evidence.py")
    spec = importlib.util.spec_from_file_location("aidn_g5_fault_recovery_verifier", path)
    if spec is None or spec.loader is None:
        raise ValueError("G5 source verifier cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _resolve_g5_source_path(value: object, *, report_path: Path, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"G5 report {label} path is missing")
    candidates = [Path(value)]
    if not candidates[0].is_absolute():
        candidates.append(report_path.parent / candidates[0])
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise ValueError(f"G5 report {label} source file is missing: {value}")


def _verify_signed_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    payload = manifest.get("payload")
    payload_hash = manifest.get("payload_hash")
    public_key = manifest.get("signer_public_key")
    signature = manifest.get("signature")
    if not isinstance(payload, dict):
        raise ValueError("G0 release manifest payload is missing")
    if not isinstance(payload_hash, str) or payload_hash != _sha256_bytes(_canonical_bytes(payload)):
        raise ValueError("G0 release manifest payload hash is invalid")
    if (
        not isinstance(public_key, str)
        or not public_key.startswith("ed25519:")
        or not isinstance(signature, str)
        or not signature.startswith("ed25519:")
    ):
        raise ValueError("G0 release manifest signature fields are invalid")
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key[8:])).verify(
            bytes.fromhex(signature[8:]),
            _canonical_bytes(payload),
        )
    except (ValueError, InvalidSignature) as error:
        raise ValueError("G0 release manifest signature verification failed") from error
    return payload


def _run_g0(profile_path: Path, report_path: Path | None) -> dict[str, Any]:
    try:
        profile = _load_profile(profile_path)
    except ValueError as error:
        return _gate("FAIL", reason=str(error))
    profile_details = {
        "profile_id": profile["profile_id"],
        "profile_version": profile["profile_version"],
        "profile_status": profile["status"],
        "activation_state": profile["activation_state"],
        "profile_commitment": profile["profile_commitment"],
    }
    if report_path is None:
        return _gate(
            "INCOMPLETE",
            reason="implementation profile is valid but G0 release-integrity evidence is not supplied",
            details=profile_details,
        )
    try:
        report = _load_json_object(report_path, label="G0 release-integrity report")
        if report.get("schema_version") != 1:
            raise ValueError("G0 release-integrity report schema_version is unsupported")
        report_status = report.get("status")
        if report_status not in {"PASS", "FAIL"}:
            raise ValueError("G0 release-integrity report status is invalid")
        if report.get("profile_id") != profile["profile_id"]:
            raise ValueError("G0 report profile_id does not match the selected profile")
        if report.get("profile_commitment") != profile["profile_commitment"]:
            raise ValueError("G0 report profile_commitment does not match the selected profile")
        checks = report.get("checks")
        required_checks = {
            "provenance_build",
            "package_hashes",
            "signed_release_manifest",
            "implementation_profile",
            "operation_catalog",
            "fixture_manifest",
            "dependency_license_scan",
        }
        if not isinstance(checks, dict) or not required_checks.issubset(checks):
            raise ValueError("G0 report is missing required integrity checks")
        if any(checks[name] is not True for name in required_checks):
            return _gate(
                "FAIL" if report_status == "FAIL" else "INCOMPLETE",
                reason="G0 release-integrity checks are not all passed",
                details=report,
            )
        manifest_payload = _verify_signed_manifest(report.get("release_manifest", {}))
        if manifest_payload.get("profile_id") != profile["profile_id"]:
            raise ValueError("G0 release manifest profile_id does not match the selected profile")
        if manifest_payload.get("profile_commitment") != profile["profile_commitment"]:
            raise ValueError("G0 release manifest profile_commitment does not match the selected profile")
        expected_catalog_hash = profile["operation_catalog"]["operation_catalog_hash"]
        if manifest_payload.get("operation_catalog_hash") != expected_catalog_hash:
            raise ValueError("G0 release manifest operation catalog hash does not match the profile")
        fixture_manifest = Path(str(manifest_payload.get("fixture_manifest_path", "")))
        if not fixture_manifest.is_file():
            raise ValueError("G0 release manifest fixture manifest is missing")
        if manifest_payload.get("fixture_manifest_hash") != _sha256_file(fixture_manifest):
            raise ValueError("G0 release manifest fixture manifest hash is invalid")
        artifacts = manifest_payload.get("artifacts")
        if not isinstance(artifacts, list) or not artifacts:
            raise ValueError("G0 release manifest has no package artifacts")
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                raise ValueError("G0 release manifest artifact is invalid")
            path = Path(str(artifact.get("path", "")))
            if not path.is_file() or artifact.get("sha256") != _sha256_file(path):
                raise ValueError(f"G0 package artifact hash is invalid: {path}")
        report_hash = report.get("report_hash")
        unsigned_report = dict(report)
        unsigned_report.pop("report_hash", None)
        if report_hash != _sha256_bytes(_canonical_bytes(unsigned_report)):
            raise ValueError("G0 report_hash is invalid")
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        return _gate("FAIL", reason=str(error))
    if report_status == "FAIL":
        return _gate("FAIL", reason="G0 release-integrity report contains failed checks")
    return _gate(
        "PASS",
        details={**profile_details, "report": str(report_path)},
    )


def _run_g1(
    fixture_manifest: Path,
    profile: dict[str, Any],
    report_path: Path | None,
) -> dict[str, Any]:
    coverage_errors = {
        operation_type: strict_operation_coverage_error(operation_type)
        for operation_type in sorted(ACTIVE_OPERATION_TYPES)
        if strict_operation_coverage_error(operation_type) is not None
    }
    fixture_details: dict[str, Any]
    try:
        fixtures = run_fixture_set(fixture_manifest, strict=True)
    except FixtureError as error:
        return _gate(
            "FAIL",
            reason=str(error),
            details={"strict_operation_coverage_errors": coverage_errors},
        )
    fixture_details = {
        "strict_operation_coverage": {
            "active": len(ACTIVE_OPERATION_TYPES),
            "supported": len(CONSENSUS_APPLIED_OPERATION_TYPES & ACTIVE_OPERATION_TYPES),
            "legacy_excluded": len(LEGACY_OPERATION_TYPES),
        },
        "fixture_count": len(fixtures),
        "fixture_manifest_hash": _sha256_file(fixture_manifest),
    }
    if coverage_errors:
        return _gate(
            "INCOMPLETE",
            reason="known operation types remain outside strict consensus coverage",
            details={
                "strict_operation_coverage_errors": coverage_errors,
                **fixture_details,
                "fixture_status": "PASS",
            },
        )
    if report_path is None:
        return _gate(
            "INCOMPLETE",
            reason="fixtures and strict coverage pass but G1 conformance evidence is not supplied",
            details=fixture_details,
        )
    try:
        report = _load_json_object(report_path, label="G1 protocol-conformance report")
        if report.get("schema_version") != 1:
            raise ValueError("G1 protocol-conformance report schema_version is unsupported")
        report_status = report.get("status")
        if report_status not in {"PASS", "FAIL"}:
            raise ValueError("G1 protocol-conformance report status is invalid")
        if report.get("profile_id") != profile["profile_id"]:
            raise ValueError("G1 report profile_id does not match the selected profile")
        if report.get("profile_commitment") != profile["profile_commitment"]:
            raise ValueError("G1 report profile_commitment does not match the selected profile")
        if report.get("fixture_manifest_hash") != fixture_details["fixture_manifest_hash"]:
            raise ValueError("G1 report fixture manifest hash is invalid")
        checks = report.get("checks")
        required_checks = {
            "unit_tests",
            "fix_0001_fixtures",
            "strict_operation_coverage",
            "unknown_operation_rejection",
            "unsupported_operation_version",
            "duplicate_operation_idempotency",
            "predecessor_mismatch",
            "monetary_boundaries",
            "canonical_json_hash_vectors",
        }
        if not isinstance(checks, dict) or not required_checks.issubset(checks):
            raise ValueError("G1 report is missing required conformance checks")
        failed_checks = sorted(
            name
            for name in required_checks
            if not isinstance(checks[name], dict) or checks[name].get("status") != "PASS"
        )
        unsigned_report = dict(report)
        report_hash = unsigned_report.pop("report_hash", None)
        if report_hash != _sha256_bytes(_canonical_bytes(unsigned_report)):
            raise ValueError("G1 report_hash is invalid")
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        return _gate("FAIL", reason=str(error))
    if failed_checks or report_status == "FAIL":
        return _gate(
            "FAIL",
            reason="G1 protocol conformance checks are not all passed",
            details={"failed_checks": failed_checks, **fixture_details},
        )
    return _gate(
        "PASS",
        details={**fixture_details, "report": str(report_path)},
    )


def _not_run(reason: str) -> dict[str, Any]:
    return _gate("NOT_RUN", reason=reason)


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot load {label}: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _gate_result_status(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and isinstance(value.get("status"), str):
        return value["status"]
    return None


def _g4_check_passes(value: object) -> bool:
    return (
        isinstance(value, dict)
        and value.get("status") == "PASS"
        and isinstance(value.get("evidence_reference"), str)
        and _HASH_RE.fullmatch(value["evidence_reference"]) is not None
    )


def _valid_g4_rpc_endpoints(value: object) -> bool:
    if not isinstance(value, list) or len(value) < 2:
        return False
    normalized: list[str] = []
    for endpoint in value:
        if not isinstance(endpoint, str) or any(character.isspace() for character in endpoint):
            return False
        try:
            parsed = urlsplit(endpoint)
            hostname = parsed.hostname
        except ValueError:
            return False
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or not hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            return False
        normalized.append(endpoint.rstrip("/"))
    return len(set(normalized)) == len(normalized)


def _validate_g4_finality(value: object) -> ConsensusFinalityEvidence:
    if not isinstance(value, dict):
        raise ValueError("G4 finality_evidence must be an object")
    required = {
        "operation_id",
        "chain_id",
        "block_height",
        "block_id",
        "app_hash",
        "commit_hash",
        "finalized_at",
        "verifier_id",
        "proof_version",
    }
    if not required.issubset(value):
        raise ValueError("G4 finality_evidence is missing required fields")
    try:
        evidence = ConsensusFinalityEvidence(**value)
    except (AttributeError, TypeError, ValueError) as error:
        raise ValueError("G4 finality_evidence is invalid") from error
    for field in ("block_id", "app_hash", "commit_hash"):
        if re.fullmatch(r"[0-9A-Fa-f]{64}", getattr(evidence, field)) is None:
            raise ValueError(f"G4 finality_evidence {field} is not a 64-hex hash")
    return evidence


def _verify_gate_result_control(evidence_dir: Path, *, evidence_root: str) -> dict[str, Any]:
    """Verify the final gate decision stored as EVD control metadata."""
    gate_path = evidence_dir.joinpath(*GATE_RESULT_PATH.split("/"))
    result = _load_json_object(gate_path, label="G7 release-gate-result")
    if result.get("status") != "PASS":
        raise ValueError("G7 release-gate-result must have status PASS")
    gates = result.get("gates")
    if not isinstance(gates, dict):
        raise ValueError("G7 release-gate-result must contain gates")
    if result.get("evidence_root") != evidence_root:
        raise ValueError("G7 release-gate-result evidence_root does not match the Evidence Root")
    required = {f"G{index}" for index in range(8)}
    missing = sorted(required - gates.keys())
    if missing:
        raise ValueError("G7 release-gate-result is missing gates: " + ", ".join(missing))
    failed = sorted(
        name for name in required if _gate_result_status(gates.get(name)) != "PASS"
    )
    if failed:
        raise ValueError("G7 release-gate-result contains non-PASS gates: " + ", ".join(failed))
    manifest = _load_json_object(evidence_dir / "manifest.json", label="evidence manifest")
    if result.get("schema_version") != 1:
        raise ValueError("G7 release-gate-result schema_version is unsupported")
    expected_context = {
        "network_id": manifest.get("network_id"),
        "release": manifest.get("release_version"),
        "profile_id": manifest.get("profile_id"),
    }
    for field, expected in expected_context.items():
        if not isinstance(expected, str) or not expected:
            raise ValueError(f"evidence manifest {field} is missing")
        if result.get(field) != expected:
            raise ValueError(f"G7 release-gate-result {field} does not match the evidence manifest")
    return {
        "status": result["status"],
        "release": result.get("release"),
        "profile_id": result.get("profile_id"),
        "gate_count": len(gates),
    }


def _validate_validator_snapshots(
    snapshots: object,
    *,
    label: str,
    minimum_validators: int = 4,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not isinstance(snapshots, list) or len(snapshots) < minimum_validators:
        raise ValueError(f"{label} must contain at least {minimum_validators} validator snapshots")
    normalized: list[dict[str, Any]] = []
    for snapshot in snapshots:
        if not isinstance(snapshot, dict):
            raise ValueError(f"{label} contains a non-object snapshot")
        rpc_url = snapshot.get("rpc_url")
        height = snapshot.get("height")
        app_hash = snapshot.get("app_hash")
        node_id = snapshot.get("node_id")
        chain_id = snapshot.get("chain_id")
        if (
            not isinstance(rpc_url, str)
            or not rpc_url
            or not isinstance(height, int)
            or isinstance(height, bool)
            or height < 1
            or not isinstance(app_hash, str)
            or not re.fullmatch(r"[0-9A-Fa-f]{64}", app_hash)
            or not isinstance(node_id, str)
            or not node_id
            or not isinstance(chain_id, str)
            or not chain_id
        ):
            raise ValueError(f"{label} contains an invalid validator snapshot")
        normalized.append(snapshot)
    if len({item["rpc_url"] for item in normalized}) != len(normalized):
        raise ValueError(f"{label} contains duplicate RPC endpoints")
    heights = {item["height"] for item in normalized}
    app_hashes = {str(item["app_hash"]).upper() for item in normalized}
    if len(heights) != 1 or len(app_hashes) != 1:
        raise ValueError(f"{label} validators do not converge on one height and AppHash")
    node_ids = {item["node_id"] for item in normalized}
    if len(node_ids) != len(normalized):
        raise ValueError(f"{label} contains duplicate validator node IDs")
    chain_ids = {item["chain_id"] for item in normalized}
    if len(chain_ids) != 1:
        raise ValueError(f"{label} validators disagree on chain ID")
    return normalized, {
        "validator_count": len(normalized),
        "height": next(iter(heights)),
        "app_hash": next(iter(app_hashes)),
        "node_ids": sorted(node_ids),
        "chain_ids": sorted(chain_ids),
    }


def _run_g3(report_path: Path | None) -> dict[str, Any]:
    if report_path is None:
        return _not_run("multi-node consensus evidence is not supplied")
    try:
        report = _load_json_object(report_path, label="G3 report")
        if report.get("status") != "ok":
            raise ValueError("G3 report status is not ok")
        if report.get("scope") not in {None, "CONTROLLED_LAN_TESTNET"}:
            raise ValueError("G3 report must declare CONTROLLED_LAN_TESTNET scope")
        operations = report.get("operations")
        if not isinstance(operations, list) or len(operations) < 8:
            raise ValueError("G3 report must contain the complete eight-operation drill")
        transaction_hashes: set[str] = set()
        for operation in operations:
            if not isinstance(operation, dict):
                raise ValueError("G3 operation record must be an object")
            transaction_hash_value = operation.get("transaction_hash")
            if not isinstance(transaction_hash_value, str):
                raise ValueError("G3 operation record has an invalid transaction hash")
            transaction_hash = transaction_hash_value.upper()
            if not re.fullmatch(r"[0-9A-Fa-f]{64}", transaction_hash):
                raise ValueError("G3 operation record has an invalid transaction hash")
            if transaction_hash in transaction_hashes:
                raise ValueError("G3 operation records contain duplicate transaction hashes")
            transaction_hashes.add(transaction_hash)
            transaction_height = operation.get("transaction_height")
            if (
                not isinstance(transaction_height, int)
                or isinstance(transaction_height, bool)
                or transaction_height < 1
            ):
                raise ValueError("G3 operation record has no committed height")
        coverage = report.get("strict_operation_coverage_probe")
        if (
            not isinstance(coverage, dict)
            or not isinstance(coverage.get("code"), int)
            or isinstance(coverage["code"], bool)
            or coverage["code"] != 1
        ):
            raise ValueError("G3 strict unsupported-operation rejection probe is missing")
        _, before = _validate_validator_snapshots(
            report.get("validator_status_before"),
            label="G3 validator_status_before",
        )
        _, after_transactions = _validate_validator_snapshots(
            report.get("validator_status_after_transactions"),
            label="G3 validator_status_after_transactions",
        )
        _, after_restart = _validate_validator_snapshots(
            report.get("validator_status_after_restart"),
            label="G3 validator_status_after_restart",
        )
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        return _gate("FAIL", reason=str(error))
    if report.get("scope") is None:
        return _gate(
            "INCOMPLETE",
            reason="G3 report predates the controlled-network evidence schema",
            details={"before": before, "after_transactions": after_transactions, "after_restart": after_restart},
        )
    if report.get("restart_status") != "PASS":
        return _gate(
            "INCOMPLETE",
            reason="G3 transaction evidence is valid but validator restart evidence is missing",
            details={"before": before, "after_transactions": after_transactions, "after_restart": after_restart},
        )
    if report.get("offline_status") != "PASS":
        return _gate(
            "INCOMPLETE",
            reason="G3 transaction evidence is valid but one-validator-offline evidence is missing",
            details={"before": before, "after_transactions": after_transactions, "after_restart": after_restart},
        )
    return _gate(
        "PASS",
        details={
            "operations": len(operations),
            "before": before,
            "after_transactions": after_transactions,
            "after_restart": after_restart,
        },
    )


def _run_g4(report_path: Path | None) -> dict[str, Any]:
    if report_path is None:
        return _not_run("public networking evidence is not supplied")
    try:
        report = _load_json_object(report_path, label="G4 report")
        if report.get("schema_version") != 1:
            raise ValueError("G4 report schema_version is unsupported")
        if report.get("scope") != "PUBLIC_NETWORK":
            raise ValueError("G4 report must declare PUBLIC_NETWORK scope")
        g4_context = {
            field: report.get(field)
            for field in ("network_id", "release_version", "profile_id")
        }
        if any(not isinstance(value, str) or not value for value in g4_context.values()):
            raise ValueError("G4 report context fields must be non-empty strings")
        report_status = report.get("status")
        if report_status not in {"ok", "PASS", "INCOMPLETE"}:
            raise ValueError("G4 report status is invalid")
        if report_status == "INCOMPLETE":
            source_gate_status = "INCOMPLETE"
        else:
            source_gate_status = report.get("gate_status", "PASS")
        if source_gate_status not in {"PASS", "INCOMPLETE"}:
            raise ValueError("G4 report gate_status is invalid")
        endpoints = report.get("rpc_endpoints")
        if not _valid_g4_rpc_endpoints(endpoints):
            raise ValueError("G4 report must contain at least two credential-free HTTPS RPC endpoints")
        finality = _validate_g4_finality(report.get("finality_evidence"))
        ownership = report.get("ownership_evidence")
        if not isinstance(ownership, dict):
            raise ValueError("G4 report lacks ownership evidence status")
        checks = report.get("checks")
        required_checks = {
            "lan_acceptance",
            "public_p2p_acceptance",
            "bootstrap_diversity",
            "public_rpc_observable",
            "tls_validated",
        }
        if checks is not None and not isinstance(checks, dict):
            raise ValueError("G4 checks must be an object")
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        return _gate("FAIL", reason=str(error))
    if not isinstance(checks, dict) or not required_checks.issubset(checks):
        return _gate(
            "INCOMPLETE",
            reason="public finality is present but the complete G4 network checklist is missing",
            details={"rpc_endpoints": endpoints, "required_checks": sorted(required_checks)},
        )
    failed_checks = sorted(
        name for name in required_checks if not _g4_check_passes(checks.get(name))
    )
    if failed_checks:
        return _gate(
            "INCOMPLETE",
            reason="public network checks are not all passed",
            details={"failed_checks": failed_checks},
        )
    if source_gate_status == "INCOMPLETE":
        return _gate(
            "INCOMPLETE",
            reason="G4 report is structurally valid but its source gate is incomplete",
            details={"rpc_endpoints": endpoints, "ownership_evidence": ownership},
        )
    if ownership.get("status") != "OUT_OF_BAND_VERIFIED":
        return _gate(
            "INCOMPLETE",
            reason="public RPC finality is present but operator/control-group independence is not verified",
            details={"rpc_endpoints": endpoints, "ownership_evidence": ownership},
        )
    if not (
        isinstance(ownership.get("ownership_evidence_root"), str)
        and _HASH_RE.fullmatch(ownership["ownership_evidence_root"]) is not None
    ):
        return _gate(
            "INCOMPLETE",
            reason="verified public ownership evidence lacks ownership_evidence_root",
            details={"rpc_endpoints": endpoints, "ownership_evidence": ownership},
        )
    return _gate(
        "PASS",
        details={
            "rpc_endpoints": endpoints,
            "operation_id": finality.operation_id,
            "context": g4_context,
        },
    )


def _run_g5(report_path: Path | None) -> dict[str, Any]:
    if report_path is None:
        return _not_run("fault-recovery drill evidence is not supplied")
    try:
        report = _load_json_object(report_path, label="G5 report")
        if report.get("schema_version") != 1:
            raise ValueError("G5 report schema_version is unsupported")
        report_hash = report.get("report_hash")
        unsigned_report = dict(report)
        unsigned_report.pop("report_hash", None)
        if (
            not isinstance(report_hash, str)
            or not _HASH_RE.fullmatch(report_hash)
            or report_hash != _sha256_bytes(_canonical_bytes(unsigned_report))
        ):
            raise ValueError("G5 report hash is invalid")
        if report.get("status") not in {"PASS", "INCOMPLETE"}:
            raise ValueError("G5 report status must be PASS or INCOMPLETE")
        if report.get("status") == "PASS" and any(
            not isinstance(report.get(field), str) or not _HASH_RE.fullmatch(report[field])
            for field in ("g2_report_hash", "live_report_hash")
        ):
            raise ValueError("G5 PASS report is missing source report hashes")
        if report.get("status") == "PASS":
            g2_source = _resolve_g5_source_path(
                report.get("g2_report"),
                report_path=report_path,
                label="G2",
            )
            live_source = _resolve_g5_source_path(
                report.get("live_report"),
                report_path=report_path,
                label="live",
            )
            verifier = _load_g5_verifier()
            try:
                source_result = verifier.verify_fault_recovery_evidence(
                    g2_report_path=g2_source,
                    live_report_path=live_source,
                )
            except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
                raise ValueError(f"G5 source evidence is invalid: {error}") from error
            if source_result.get("status") != "PASS":
                raise ValueError("G5 source evidence did not produce PASS")
            if (
                source_result.get("g2_report_hash") != report.get("g2_report_hash")
                or source_result.get("live_report_hash") != report.get("live_report_hash")
                or source_result.get("drills") != report.get("drills")
            ):
                raise ValueError("G5 aggregate does not match validated source evidence")
        if report.get("status") == "INCOMPLETE":
            return _gate(
                "INCOMPLETE",
                reason="G5 source report is incomplete",
                details={
                    "drills": sorted(report.get("drills", {}))
                    if isinstance(report.get("drills"), dict)
                    else [],
                    "missing_live_drills": report.get("missing_live_drills", []),
                },
            )
        drills = report.get("drills")
        required = {
            "graceful_restart",
            "abrupt_process_termination",
            "host_reboot",
            "snapshot_restore",
            "state_sync",
            "invalid_snapshot_rejected",
            "stale_predecessor_rejected",
        }
        if not isinstance(drills, dict) or not required.issubset(drills):
            raise ValueError("G5 report does not contain all required recovery drills")
        failed = sorted(
            name
            for name in required
            if not isinstance(drills.get(name), dict)
            or drills[name].get("status") != "PASS"
            or not isinstance(drills[name].get("evidence_reference"), str)
            or not _HASH_RE.fullmatch(drills[name]["evidence_reference"])
        )
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        return _gate("FAIL", reason=str(error))
    if failed:
        return _gate("INCOMPLETE", reason="required recovery drills are not all passed", details={"failed": failed})
    return _gate("PASS", details={"drills": sorted(required)})


def _verify_g6_review(
    evidence_dir: Path,
    *,
    evidence_root: str,
    operator_id: str,
    control_group_id: str,
    reviewer_keys: dict[str, str],
) -> dict[str, str]:
    review_path = evidence_dir.joinpath(*INDEPENDENCE_REVIEW_PATH.split("/"))
    review = _load_json_object(review_path, label="G6 independence review")
    required = {
        "review_version",
        "reviewer_id",
        "reviewer_public_key",
        "review_status",
        "review_basis",
        "reviewed_operator_id",
        "reviewed_control_group_id",
        "reviewed_evidence_root",
        "reviewed_at",
        "signature",
    }
    if review.get("review_version") != 1 or not required.issubset(review):
        raise ValueError("G6 independence review is missing required fields")
    if not all(
        isinstance(review.get(field), str) and review[field]
        for field in ("review_basis", "reviewed_at")
    ):
        raise ValueError("G6 independence review basis and timestamp are invalid")
    reviewer_id = review["reviewer_id"]
    reviewer_public_key = review["reviewer_public_key"]
    if not isinstance(reviewer_id, str) or not reviewer_id:
        raise ValueError("G6 independence review reviewer_id is invalid")
    expected_public_key = reviewer_keys.get(reviewer_id)
    if expected_public_key is None or reviewer_public_key != expected_public_key:
        raise ValueError("G6 independence review reviewer key is not trusted")
    if review["review_status"] != "VERIFIED":
        raise ValueError("G6 independence review is not VERIFIED")
    if review["reviewed_operator_id"] != operator_id:
        raise ValueError("G6 independence review operator binding is invalid")
    if review["reviewed_control_group_id"] != control_group_id:
        raise ValueError("G6 independence review control-group binding is invalid")
    if review["reviewed_evidence_root"] != evidence_root:
        raise ValueError("G6 independence review evidence root is invalid")
    signature = review.get("signature")
    if not isinstance(signature, str) or not signature.startswith("ed25519:"):
        raise ValueError("G6 independence review signature is invalid")
    try:
        public_key = bytes.fromhex(reviewer_public_key.removeprefix("ed25519:"))
        signature_bytes = bytes.fromhex(signature.removeprefix("ed25519:"))
        Ed25519PublicKey.from_public_bytes(public_key).verify(
            signature_bytes,
            canonical_json_bytes({key: value for key, value in review.items() if key != "signature"}),
        )
    except (ValueError, InvalidSignature) as error:
        raise ValueError("G6 independence review signature verification failed") from error
    return {
        "reviewer_id": reviewer_id,
        "reviewer_public_key": reviewer_public_key,
        "reviewed_operator_id": operator_id,
        "reviewed_control_group_id": control_group_id,
        "reviewed_evidence_root": evidence_root,
    }


def _run_g6(evidence_dirs: list[Path], reviewer_keys: dict[str, str]) -> dict[str, Any]:
    if not evidence_dirs:
        return _not_run("independent operator attestations are not supplied")
    if not reviewer_keys:
        return _gate(
            "INCOMPLETE",
            reason="trusted G6 reviewer keys are not supplied",
        )
    identities: list[dict[str, str]] = []
    release_context: set[tuple[str, str, str]] = set()
    try:
        for evidence_dir in evidence_dirs:
            verified = verify_public_evidence_bundle(evidence_dir, require_attestation=True)
            manifest = _load_json_object(evidence_dir / "manifest.json", label="operator evidence manifest")
            attestation_path = evidence_dir.joinpath(*ATTESTATION_PATH.split("/"))
            attestation = _load_json_object(attestation_path, label="operator attestation")
            operator_id = attestation.get("operator_id")
            control_group_id = attestation.get("control_group_id")
            public_key = attestation.get("operator_public_key")
            independence_status = attestation.get("independence_status")
            if not all(isinstance(value, str) and value for value in (operator_id, control_group_id, public_key)):
                raise ValueError("G6 attestation must declare operator_id, control_group_id and operator_public_key")
            identities.append(
                {
                    "operator_id": operator_id,
                    "control_group_id": control_group_id,
                    "operator_public_key": public_key,
                    "evidence_root": verified.evidence_root,
                    "independence_status": independence_status or "MISSING",
                }
            )
            review = _verify_g6_review(
                evidence_dir,
                evidence_root=verified.evidence_root,
                operator_id=operator_id,
                control_group_id=control_group_id,
                reviewer_keys=reviewer_keys,
            )
            identities[-1]["reviewer_id"] = review["reviewer_id"]
            identities[-1]["reviewer_public_key"] = review["reviewer_public_key"]
            release_context.add(
                (
                    str(manifest["network_id"]),
                    str(manifest["release_version"]),
                    str(manifest["profile_id"]),
                )
            )
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError, EvidenceBundleError) as error:
        return _gate("FAIL", reason=str(error))
    if len({item["operator_public_key"] for item in identities}) < 2:
        return _gate("INCOMPLETE", reason="G6 requires at least two distinct operator keys")
    if len({item["operator_id"] for item in identities}) < 2:
        return _gate("INCOMPLETE", reason="G6 requires at least two distinct operator identities")
    if len({item["control_group_id"] for item in identities}) < 2:
        return _gate("INCOMPLETE", reason="G6 requires at least two distinct control groups")
    operator_ids = {item["operator_id"] for item in identities}
    operator_keys = {item["operator_public_key"] for item in identities}
    reviewer_ids = {item["reviewer_id"] for item in identities}
    reviewer_public_keys = {item["reviewer_public_key"] for item in identities}
    if operator_ids & reviewer_ids or operator_keys & reviewer_public_keys:
        return _gate(
            "FAIL",
            reason="G6 reviewer identity must be distinct from every operator identity and key",
            details={"attestations": identities},
        )
    if len(release_context) != 1:
        return _gate(
            "FAIL",
            reason="G6 operator bundles do not attest the same network, release and profile",
            details={"contexts": sorted(release_context)},
        )
    if any(item["independence_status"] != "OUT_OF_BAND_VERIFIED" for item in identities):
        return _gate(
            "INCOMPLETE",
            reason="G6 operator signatures are present but out-of-band independence is not verified",
            details={"attestations": identities},
        )
    return _gate("PASS", details={"attestations": identities})


def _run_g2(report_path: Path | None, profile: dict[str, Any]) -> dict[str, Any]:
    if report_path is None:
        return _not_run("snapshot/state-sync operational evidence is not supplied")
    try:
        report = load_and_verify_snapshot_acceptance_report(report_path)
    except SnapshotAcceptanceError as error:
        return _gate("FAIL", reason=str(error))
    if (
        report.get("profile_id") != profile.get("profile_id")
        or report.get("profile_commitment") != profile.get("profile_commitment")
    ):
        return _gate("FAIL", reason="G2 report does not match the selected implementation profile")
    return _gate(
        "PASS",
        details={
            "mode": report["mode"],
            "report_hash": report["report_hash"],
            "snapshot_height": report["snapshot"]["height"],
            "snapshot_chunks": report["snapshot"]["chunks"],
            "checks": report["checks"],
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile",
        type=Path,
        default=Path("profiles/aidn-mainnet-candidate-1.json"),
    )
    parser.add_argument("--fixture-manifest", type=Path, default=Path("fixtures/manifest.json"))
    parser.add_argument(
        "--g0-report",
        type=Path,
        help="verify the signed build/provenance evidence required by G0",
    )
    parser.add_argument(
        "--g1-report",
        type=Path,
        help="verify the deterministic protocol-conformance evidence required by G1",
    )
    parser.add_argument("--evidence-dir", type=Path)
    parser.add_argument(
        "--g2-report",
        type=Path,
        help="verify a deterministic local G2 snapshot/state-sync acceptance report",
    )
    parser.add_argument("--g3-report", type=Path, help="verify a controlled multi-validator G3 report")
    parser.add_argument("--g4-report", type=Path, help="verify a public-network G4 finality report")
    parser.add_argument("--g5-report", type=Path, help="verify a G5 fault-recovery report")
    parser.add_argument(
        "--g6-evidence-dir",
        action="append",
        type=Path,
        default=[],
        help="verify one EVD-0001 operator bundle; repeat for the G6 quorum",
    )
    parser.add_argument(
        "--g6-review-key",
        action="append",
        default=[],
        metavar="REVIEWER_ID=ed25519:<64-hex>",
        help="trusted reviewer key for G6 independence reviews; repeatable",
    )
    parser.add_argument("--require-evidence", action="append", default=[])
    parser.add_argument(
        "--allow-incomplete",
        action="store_true",
        help="return success for local development when operational gates are not complete",
    )
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    try:
        selected_profile = _load_profile(args.profile)
    except ValueError:
        selected_profile = None
    try:
        reviewer_keys: dict[str, str] = {}
        for value in args.g6_review_key:
            reviewer_id, separator, public_key = value.partition("=")
            if (
                not separator
                or not reviewer_id
                or not public_key.startswith("ed25519:")
                or len(public_key.removeprefix("ed25519:")) != 64
            ):
                raise ValueError("G6 reviewer key must use REVIEWER_ID=ed25519:<64-hex>")
            bytes.fromhex(public_key.removeprefix("ed25519:"))
            if reviewer_id in reviewer_keys:
                raise ValueError(f"duplicate G6 reviewer key: {reviewer_id}")
            reviewer_keys[reviewer_id] = public_key
    except ValueError as error:
        reviewer_keys = {}
        reviewer_key_error = str(error)
    else:
        reviewer_key_error = None

    gates = {
        "G0": _run_g0(args.profile, args.g0_report),
        "G1": (
            _run_g1(args.fixture_manifest, selected_profile, args.g1_report)
            if selected_profile is not None
            else _gate("FAIL", reason="cannot validate G1 without a valid implementation profile")
        ),
        "G2": (
            _run_g2(args.g2_report, selected_profile)
            if selected_profile is not None
            else _gate("FAIL", reason="cannot validate G2 without a valid implementation profile")
        ),
        "G3": _run_g3(args.g3_report),
        "G4": _run_g4(args.g4_report),
        "G5": _run_g5(args.g5_report),
        "G6": (
            _gate("FAIL", reason=reviewer_key_error)
            if reviewer_key_error is not None
            else _run_g6(args.g6_evidence_dir, reviewer_keys)
        ),
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
            gate_result = _verify_gate_result_control(
                args.evidence_dir,
                evidence_root=result.evidence_root,
            )
        except EvidenceBundleError as error:
            gates["G7"] = _gate("FAIL", reason=str(error))
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
            gates["G7"] = _gate("FAIL", reason=str(error))
        else:
            gates["G7"] = _gate(
                "PASS",
                details={
                    "evidence_root": result.evidence_root,
                    "artifact_count": result.artifact_count,
                    "attestation_verified": result.attestation_verified,
                    "gate_result": gate_result,
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
