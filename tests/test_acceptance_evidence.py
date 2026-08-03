from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tools.validate_acceptance_evidence import (
    AcceptanceEvidenceError,
    validate_acceptance_evidence,
)


def _write_bundle(root: Path) -> tuple[Path, Path, Path]:
    registry = root / "registry-replication-20260802T000000Z.json"
    finality = root / "external-finality-20260802T000000Z.json"
    registry.write_text(
        json.dumps(
            {
                "status": "ok",
                "technical_evidence": {"authenticated_peer_ids": ["peer-1"]},
                "ownership_evidence": {"status": "NOT_PROVEN_BY_PROTOCOL"},
            }
        ),
        encoding="utf-8",
    )
    finality.write_text(
        json.dumps(
            {
                "status": "ok",
                "finality_evidence": {
                    "operation_id": "operation-1",
                    "chain_id": "chain-1",
                    "block_height": 42,
                    "block_id": "B" * 64,
                    "app_hash": "A" * 64,
                    "commit_hash": "C" * 64,
                },
                "ownership_evidence": {"status": "NOT_PROVEN_BY_PROTOCOL"},
            }
        ),
        encoding="utf-8",
    )
    manifest = root / "SHA256SUMS-20260802T000000Z"
    entries = []
    for path in (registry, finality):
        entries.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}")
    manifest.write_text("\n".join(entries) + "\n", encoding="ascii")
    return manifest, registry, finality


def test_acceptance_evidence_verifies_reports_and_checksums(tmp_path: Path) -> None:
    manifest, _, _ = _write_bundle(tmp_path)

    result = validate_acceptance_evidence(tmp_path, checksum_file=manifest)

    assert result["status"] == "ok"
    assert result["finality"]["operation_id"] == "operation-1"
    assert result["ownership_evidence"] == "NOT_PROVEN_BY_PROTOCOL"


def test_acceptance_evidence_rejects_checksum_mutation(tmp_path: Path) -> None:
    manifest, _, finality = _write_bundle(tmp_path)
    finality.write_text(finality.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    with pytest.raises(AcceptanceEvidenceError, match="checksum mismatch"):
        validate_acceptance_evidence(tmp_path, checksum_file=manifest)


def test_acceptance_evidence_rejects_protocol_ownership_claim(tmp_path: Path) -> None:
    manifest, registry, _ = _write_bundle(tmp_path)
    payload = json.loads(registry.read_text(encoding="utf-8"))
    payload["ownership_evidence"]["status"] = "PROVEN"
    registry.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(AcceptanceEvidenceError, match="checksum mismatch"):
        validate_acceptance_evidence(tmp_path, checksum_file=manifest)


def test_acceptance_evidence_rejects_duplicate_source_reports(tmp_path: Path) -> None:
    manifest, registry, finality = _write_bundle(tmp_path)
    duplicate = tmp_path / "registry-replication-20260802T000001Z.json"
    duplicate.write_bytes(registry.read_bytes())
    manifest.write_text(
        manifest.read_text(encoding="ascii")
        + f"{hashlib.sha256(duplicate.read_bytes()).hexdigest()}  {duplicate.name}\n",
        encoding="ascii",
    )

    with pytest.raises(AcceptanceEvidenceError, match="duplicate registry"):
        validate_acceptance_evidence(tmp_path, checksum_file=manifest)


def test_acceptance_evidence_rejects_missing_ownership_status(tmp_path: Path) -> None:
    manifest, registry, _ = _write_bundle(tmp_path)
    payload = json.loads(registry.read_text(encoding="utf-8"))
    payload["ownership_evidence"] = {}
    registry.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(AcceptanceEvidenceError, match="checksum mismatch"):
        validate_acceptance_evidence(tmp_path, checksum_file=manifest)


def test_acceptance_evidence_rejects_duplicate_manifest_entry(tmp_path: Path) -> None:
    manifest, _, _ = _write_bundle(tmp_path)
    first_line = manifest.read_text(encoding="ascii").splitlines()[0]
    manifest.write_text(manifest.read_text(encoding="ascii") + first_line + "\n", encoding="ascii")

    with pytest.raises(AcceptanceEvidenceError, match="duplicate entry"):
        validate_acceptance_evidence(tmp_path, checksum_file=manifest)
