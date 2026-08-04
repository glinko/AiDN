from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aidn_hypervisor.evidence import verify_public_evidence_bundle

ROOT = Path(__file__).resolve().parents[1]
BUILDER_PATH = ROOT / "tools/build-public-evidence-bundle.py"
SPEC = importlib.util.spec_from_file_location("public_evidence_builder", BUILDER_PATH)
assert SPEC is not None and SPEC.loader is not None
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)


def test_public_evidence_builder_signs_bundle_without_copying_key(tmp_path: Path) -> None:
    private_key = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
    key_path = tmp_path / "operator.key"
    key_path.write_bytes(
        private_key.private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
            serialization.NoEncryption(),
        )
    )
    source_path = tmp_path / "source.json"
    source_path.write_text('{"status":"ok"}\n', encoding="utf-8")
    bundle_path = tmp_path / "bundle"

    result = BUILDER.build_bundle(
        output=bundle_path,
        network_id="testnet",
        release_version="0.1.0-test",
        profile_id="profile-test",
        operator_id="operator-a",
        control_group_id="group-a",
        independence_status="OUT_OF_BAND_DECLARED",
        private_key_path=key_path,
        artifacts=[(source_path, "network/status.json")],
    )

    assert result["status"] == "ok"
    assert not (bundle_path / "operator.key").exists()
    attestation = json.loads(
        (bundle_path / "attestations/operator-attestation.json").read_text(encoding="utf-8")
    )
    assert attestation["control_group_id"] == "group-a"
    assert verify_public_evidence_bundle(bundle_path).attestation_verified is True
