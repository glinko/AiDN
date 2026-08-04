from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aidn_hypervisor.evidence import (
    EvidenceBundleError,
    canonical_json_bytes,
    evidence_root,
    verify_public_evidence_bundle,
)


def _write_bundle(root: Path, *, with_attestation: bool = True) -> str:
    artifacts = {
        "release/version.json": '{"release":"test"}\n',
        "network/status.json": '{"height":7,"app_hash":"abc"}\n',
    }
    hashes: list[tuple[str, str]] = []
    for relative, content in artifacts.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        hashes.append((relative, hashlib.sha256(path.read_bytes()).hexdigest()))
    root_hash = evidence_root(hashes)
    manifest = {
        "evidence_format_version": 1,
        "network_id": "testnet",
        "release_version": "0.1.0-test",
        "profile_id": "test-profile",
        "generated_at": "2030-01-01T00:00:00Z",
        "artifacts": [
            {"path": relative, "sha256": digest} for relative, digest in sorted(hashes)
        ],
        "evidence_root": root_hash,
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    if with_attestation:
        private_key = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
        public_key = private_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        attestation = {
            "attestation_version": 1,
            "operator_id": "operator-test-1",
            "operator_public_key": "ed25519:" + public_key.hex(),
            "evidence_root": root_hash,
            "signed_at": "2030-01-01T00:00:01Z",
        }
        attestation["signature"] = "ed25519:" + private_key.sign(
            canonical_json_bytes(attestation)
        ).hex()
        attestation_path = root / "attestations/operator-attestation.json"
        attestation_path.parent.mkdir(parents=True, exist_ok=True)
        attestation_path.write_text(
            json.dumps(attestation, indent=2) + "\n",
            encoding="utf-8",
        )
    return root_hash


def test_public_evidence_bundle_verifies_hashes_root_and_attestation(tmp_path: Path) -> None:
    expected_root = _write_bundle(tmp_path)

    result = verify_public_evidence_bundle(
        tmp_path,
        required_paths=("release/version.json", "network/status.json"),
    )

    assert result.evidence_root == expected_root
    assert result.artifact_count == 2
    assert result.attestation_verified is True


def test_public_evidence_bundle_rejects_mutated_artifact(tmp_path: Path) -> None:
    _write_bundle(tmp_path)
    (tmp_path / "release/version.json").write_text('{"release":"tampered"}\n', encoding="utf-8")

    with pytest.raises(EvidenceBundleError, match="artifact hash mismatch"):
        verify_public_evidence_bundle(tmp_path)


def test_public_evidence_bundle_rejects_traversal(tmp_path: Path) -> None:
    _write_bundle(tmp_path, with_attestation=False)
    manifest_path = tmp_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"][0]["path"] = "../outside.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(EvidenceBundleError, match="traverse"):
        verify_public_evidence_bundle(tmp_path, require_attestation=False)


def test_public_evidence_bundle_rejects_unlisted_files(tmp_path: Path) -> None:
    _write_bundle(tmp_path)
    (tmp_path / "network/extra.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(EvidenceBundleError, match="unlisted files"):
        verify_public_evidence_bundle(tmp_path)


def test_public_evidence_bundle_allows_release_gate_control_file(tmp_path: Path) -> None:
    _write_bundle(tmp_path)
    gate_path = tmp_path / "gates/release-gate-result.json"
    gate_path.parent.mkdir(parents=True, exist_ok=True)
    gate_path.write_text('{"status":"PASS"}\n', encoding="utf-8")

    result = verify_public_evidence_bundle(tmp_path)

    assert result.attestation_verified is True


def test_public_evidence_bundle_can_be_checked_before_attestation(tmp_path: Path) -> None:
    _write_bundle(tmp_path, with_attestation=False)

    with pytest.raises(EvidenceBundleError, match="attestation is required"):
        verify_public_evidence_bundle(tmp_path)

    result = verify_public_evidence_bundle(tmp_path, require_attestation=False)
    assert result.attestation_verified is False


def test_public_evidence_bundle_rejects_sensitive_content(tmp_path: Path) -> None:
    _write_bundle(tmp_path, with_attestation=False)
    secret_path = tmp_path / "network/secret.json"
    secret_path.write_text('{"api_key":"not-public"}\n', encoding="utf-8")
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    manifest["artifacts"].append(
        {
            "path": "network/secret.json",
            "sha256": hashlib.sha256(secret_path.read_bytes()).hexdigest(),
        }
    )
    pairs = [(item["path"], item["sha256"]) for item in manifest["artifacts"]]
    manifest["evidence_root"] = evidence_root(pairs)
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(EvidenceBundleError, match="sensitive-looking"):
        verify_public_evidence_bundle(tmp_path, require_attestation=False)
