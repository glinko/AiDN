#!/usr/bin/env python3
"""Validate the tamper-evident evidence bundle produced by acceptance tooling."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


class AcceptanceEvidenceError(ValueError):
    """The acceptance evidence bundle is incomplete or has been modified."""


_CHECKSUM_RE = re.compile(r"^(?P<digest>[0-9a-fA-F]{64})  (?P<name>[^/\\]+)$")


def validate_acceptance_evidence(
    evidence_dir: Path,
    *,
    checksum_file: Path | None = None,
) -> dict[str, Any]:
    """Verify checksums and the minimum independent-operator evidence shape."""
    root = evidence_dir.expanduser().resolve()
    if not root.is_dir():
        raise AcceptanceEvidenceError(f"evidence directory does not exist: {root}")
    manifest = checksum_file or _latest_checksum_file(root)
    manifest = manifest.expanduser().resolve()
    if manifest.parent != root:
        raise AcceptanceEvidenceError("checksum manifest must be inside evidence directory")
    if manifest.is_symlink() or not manifest.is_file():
        raise AcceptanceEvidenceError("checksum manifest must be a regular file")
    try:
        lines = manifest.read_text(encoding="ascii").splitlines()
    except OSError as error:
        raise AcceptanceEvidenceError("checksum manifest cannot be read") from error
    if not lines:
        raise AcceptanceEvidenceError("checksum manifest is empty")

    reports: dict[str, dict[str, Any]] = {}
    verified_files: list[str] = []
    seen_names: set[str] = set()
    for line in lines:
        match = _CHECKSUM_RE.fullmatch(line.strip())
        if match is None:
            raise AcceptanceEvidenceError("checksum manifest contains an invalid entry")
        name = match.group("name")
        if name in seen_names:
            raise AcceptanceEvidenceError(f"checksum manifest contains duplicate entry: {name}")
        seen_names.add(name)
        path = root / name
        if path.resolve().parent != root or path.is_symlink() or not path.is_file():
            raise AcceptanceEvidenceError(f"checksum target is missing or escapes bundle: {name}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual.lower() != match.group("digest").lower():
            raise AcceptanceEvidenceError(f"checksum mismatch: {name}")
        verified_files.append(name)
        if name.startswith("registry-replication-") and name.endswith(".json"):
            if "registry" in reports:
                raise AcceptanceEvidenceError("checksum manifest contains duplicate registry reports")
            reports["registry"] = _load_report(path, name)
        elif name.startswith("external-finality-") and name.endswith(".json"):
            if "finality" in reports:
                raise AcceptanceEvidenceError("checksum manifest contains duplicate external-finality reports")
            reports["finality"] = _load_report(path, name)

    if set(reports) != {"registry", "finality"}:
        raise AcceptanceEvidenceError(
            "checksum manifest must contain one registry and one external-finality report"
        )

    registry = reports["registry"]
    finality = reports["finality"]
    _require_ok_report(registry, "registry")
    _require_ok_report(finality, "external-finality")
    registry_evidence = registry.get("technical_evidence")
    if not isinstance(registry_evidence, dict):
        raise AcceptanceEvidenceError("registry report lacks technical_evidence")
    peer_ids = registry_evidence.get("authenticated_peer_ids")
    if not isinstance(peer_ids, list) or not peer_ids or any(not isinstance(item, str) for item in peer_ids):
        raise AcceptanceEvidenceError("registry report lacks authenticated peer evidence")
    finality_evidence = finality.get("finality_evidence")
    if not isinstance(finality_evidence, dict):
        raise AcceptanceEvidenceError("external-finality report lacks finality_evidence")
    for field in ("operation_id", "chain_id", "block_height", "block_id", "app_hash", "commit_hash"):
        if field not in finality_evidence:
            raise AcceptanceEvidenceError(f"external-finality evidence lacks {field}")

    ownership_statuses = {
        registry["ownership_evidence"]["status"],
        finality["ownership_evidence"]["status"],
    }
    if ownership_statuses != {"NOT_PROVEN_BY_PROTOCOL"}:
        raise AcceptanceEvidenceError("evidence bundle contains an unsupported ownership claim")

    return {
        "status": "ok",
        "checksum_manifest": manifest.name,
        "verified_files": sorted(verified_files),
        "registry_peer_ids": sorted(peer_ids),
        "finality": {
            "operation_id": finality_evidence["operation_id"],
            "chain_id": finality_evidence["chain_id"],
            "block_height": finality_evidence["block_height"],
            "block_id": finality_evidence["block_id"],
            "app_hash": finality_evidence["app_hash"],
            "commit_hash": finality_evidence["commit_hash"],
        },
        "ownership_evidence": "NOT_PROVEN_BY_PROTOCOL",
    }


def _latest_checksum_file(root: Path) -> Path:
    manifests = sorted(root.glob("SHA256SUMS-*"))
    if not manifests:
        raise AcceptanceEvidenceError("evidence directory has no SHA256SUMS manifest")
    return manifests[-1]


def _load_report(path: Path, name: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AcceptanceEvidenceError(f"report is not valid JSON: {name}") from error
    if not isinstance(value, dict):
        raise AcceptanceEvidenceError(f"report is not a JSON object: {name}")
    return value


def _require_ok_report(report: dict[str, Any], label: str) -> None:
    if report.get("status") != "ok":
        raise AcceptanceEvidenceError(f"{label} report is not successful")
    ownership = report.get("ownership_evidence")
    if not isinstance(ownership, dict):
        raise AcceptanceEvidenceError(f"{label} report lacks ownership evidence")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument("--checksum-file", type=Path)
    args = parser.parse_args(argv)
    try:
        result = validate_acceptance_evidence(
            args.evidence_dir,
            checksum_file=args.checksum_file,
        )
    except (OSError, ValueError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}, sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
