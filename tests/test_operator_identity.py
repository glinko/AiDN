"""Regression coverage for the host-local operator bootstrap identity."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def _run_identity(root: Path, operator_id: str = "operator-test-1") -> dict:
    result = subprocess.run(
        [
            sys.executable,
            "tools/prepare-operator-identity.py",
            "init",
            "--root",
            str(root),
            "--operator-id",
            operator_id,
            "--peer-id",
            operator_id,
            "--host",
            "192.0.2.10",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_operator_identity_is_host_local_and_public_export_has_no_key_path(tmp_path: Path) -> None:
    root = tmp_path / "identity"
    result = _run_identity(root)

    assert result["status"] == "created"
    private_key_path = root / "operator-attestation-key.raw"
    private_key = Ed25519PrivateKey.from_private_bytes(private_key_path.read_bytes())
    public_key = "ed25519:" + private_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    ).hex()
    identity = json.loads((root / "operator-identity.json").read_text(encoding="utf-8"))
    public_identity = json.loads(
        (root / "operator-public-identity.json").read_text(encoding="utf-8")
    )

    assert identity["operator_public_key"] == public_key
    assert public_identity["operator_public_key"] == public_key
    assert "attestation_key_path" not in public_identity
    assert "status" not in public_identity
    assert result["operator_public_key"] == public_key


def test_operator_identity_reuse_does_not_rotate_key(tmp_path: Path) -> None:
    root = tmp_path / "identity"
    first = _run_identity(root)
    key_before = (root / "operator-attestation-key.raw").read_bytes()

    second = _run_identity(root)

    assert first["operator_public_key"] == second["operator_public_key"]
    assert second["status"] == "reused"
    assert (root / "operator-attestation-key.raw").read_bytes() == key_before
