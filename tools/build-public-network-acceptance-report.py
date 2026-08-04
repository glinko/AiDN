#!/usr/bin/env python3
"""Combine LAN, public-finality and deployment observations into G4 evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

REQUIRED_CHECKS = (
    "lan_acceptance",
    "public_p2p_acceptance",
    "bootstrap_diversity",
    "public_rpc_observable",
    "tls_validated",
)


def _load(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot load {label}: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _check_value(value: object, *, name: str) -> dict[str, str]:
    if isinstance(value, dict):
        if value.get("status") != "PASS":
            raise ValueError(f"G4 check must have status PASS: {name}")
        reference = value.get("evidence_reference")
        if not isinstance(reference, str) or not reference:
            raise ValueError(f"G4 check lacks evidence_reference: {name}")
        return {"status": "PASS", "evidence_reference": reference}
    raise ValueError(f"G4 check must be a PASS object with evidence_reference: {name}")


def _file_evidence_reference(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _credential_free_https_endpoints(value: object) -> list[str]:
    if not isinstance(value, list) or len(value) < 2:
        raise ValueError("G4 report must contain at least two credential-free HTTPS RPC endpoints")
    normalized: list[str] = []
    for endpoint in value:
        if not isinstance(endpoint, str) or any(character.isspace() for character in endpoint):
            raise ValueError("G4 report RPC endpoints must be credential-free HTTPS URLs")
        try:
            parsed = urlsplit(endpoint)
            hostname = parsed.hostname
        except ValueError as error:
            raise ValueError("G4 report RPC endpoints must be valid HTTPS URLs") from error
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
            raise ValueError("G4 report RPC endpoints must be credential-free HTTPS URLs without paths")
        normalized.append(endpoint.rstrip("/"))
    if len(set(normalized)) != len(normalized):
        raise ValueError("G4 report RPC endpoints must be unique")
    return normalized


def build_report(*, lan_path: Path, external_path: Path, deployment_path: Path) -> dict[str, Any]:
    lan = _load(lan_path, "LAN report")
    external = _load(external_path, "external finality report")
    deployment = _load(deployment_path, "public deployment report")
    if lan.get("status") != "ok" or lan.get("scope") != "CONTROLLED_LAN_TESTNET":
        raise ValueError("LAN report is not a valid controlled testnet acceptance")
    if external.get("status") != "ok":
        raise ValueError("external finality report is not ok")
    if (
        deployment.get("status") != "ok"
        or deployment.get("scope") != "PUBLIC_NETWORK_DEPLOYMENT"
    ):
        raise ValueError("public deployment report is not a verified deployment observation")
    endpoints = _credential_free_https_endpoints(external.get("rpc_endpoints"))
    finality = external.get("finality_evidence")
    if (
        not isinstance(finality, dict)
        or not finality.get("operation_id")
    ):
        raise ValueError("external report lacks two credential-free HTTPS finality endpoints")
    deployment_checks = deployment.get("checks")
    if not isinstance(deployment_checks, dict):
        raise ValueError("public deployment report must contain checks")
    checks: dict[str, dict[str, str]] = {
        "lan_acceptance": {
            "status": "PASS",
            "evidence_reference": _file_evidence_reference(lan_path),
        },
        "public_rpc_observable": {
            "status": "PASS",
            "evidence_reference": _file_evidence_reference(external_path),
        },
    }
    evidence: dict[str, Any] = {"lan": lan, "external": external, "deployment": deployment}
    for name in ("public_p2p_acceptance", "bootstrap_diversity", "tls_validated"):
        if name not in deployment_checks:
            raise ValueError(f"public deployment report lacks check: {name}")
        checks[name] = _check_value(deployment_checks[name], name=name)
    ownership = external.get("ownership_evidence")
    if not isinstance(ownership, dict):
        raise ValueError("external report lacks ownership evidence")
    if ownership.get("status") == "OUT_OF_BAND_VERIFIED" and not (
        isinstance(ownership.get("ownership_evidence_root"), str)
        and ownership["ownership_evidence_root"]
    ):
        raise ValueError(
            "verified ownership evidence must include ownership_evidence_root"
        )
    checks_pass = all(
        isinstance(check, dict)
        and check.get("status") == "PASS"
        and isinstance(check.get("evidence_reference"), str)
        and bool(check["evidence_reference"])
        for check in checks.values()
    )
    gate_status = "PASS" if checks_pass and ownership.get("status") == "OUT_OF_BAND_VERIFIED" else "INCOMPLETE"
    return {
        "schema_version": 1,
        "status": "ok",
        "gate_status": gate_status,
        "scope": "PUBLIC_NETWORK",
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "rpc_endpoints": endpoints,
        "finality_evidence": finality,
        "ownership_evidence": ownership,
        "checks": checks,
        "evidence": evidence,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lan-report", type=Path, required=True)
    parser.add_argument("--external-report", type=Path, required=True)
    parser.add_argument("--deployment-report", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = build_report(
            lan_path=args.lan_report,
            external_path=args.external_report,
            deployment_path=args.deployment_report,
        )
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "FAIL", "reason": str(error)}, sort_keys=True))
        return 2
    encoded = json.dumps(report, ensure_ascii=True, indent=2) + "\n"
    print(encoded, end="")
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    return 0 if report["gate_status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
