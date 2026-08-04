from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aidn_hypervisor.evidence import INDEPENDENCE_REVIEW_PATH

ROOT = Path(__file__).resolve().parents[1]
BUILDER_PATH = ROOT / "tools/build-public-evidence-bundle.py"
REVIEW_TOOL_PATH = ROOT / "tools/sign-independence-review.py"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BUILDER = _load_module("public_evidence_builder_for_review", BUILDER_PATH)
REVIEW_TOOL = _load_module("independence_review_signer", REVIEW_TOOL_PATH)


def _raw_key(path: Path, seed_start: int) -> Ed25519PrivateKey:
    key = Ed25519PrivateKey.from_private_bytes(bytes(range(seed_start, seed_start + 32)))
    path.write_bytes(
        key.private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
            serialization.NoEncryption(),
        )
    )
    return key


def test_independence_review_signer_binds_review_to_verified_bundle(tmp_path: Path) -> None:
    operator_key_path = tmp_path / "operator.key"
    _raw_key(operator_key_path, 1)
    source_path = tmp_path / "status.json"
    source_path.write_text('{"status":"ok"}\n', encoding="utf-8")
    evidence_dir = tmp_path / "evidence"

    built = BUILDER.build_bundle(
        output=evidence_dir,
        network_id="testnet",
        release_version="0.1.0-test",
        profile_id="profile-test",
        operator_id="operator-a",
        control_group_id="group-a",
        independence_status="OUT_OF_BAND_VERIFIED",
        private_key_path=operator_key_path,
        artifacts=[(source_path, "network/status.json")],
    )

    reviewer_key_path = tmp_path / "reviewer.key"
    reviewer_key = _raw_key(reviewer_key_path, 101)
    result = REVIEW_TOOL.sign_review(
        evidence_dir=evidence_dir,
        reviewer_id="release-reviewer",
        operator_id="operator-a",
        control_group_id="group-a",
        review_basis="independent test review",
        private_key_path=reviewer_key_path,
    )

    review_path = evidence_dir.joinpath(*Path(INDEPENDENCE_REVIEW_PATH).parts)
    review = json.loads(review_path.read_text(encoding="utf-8"))
    reviewer_public_key = reviewer_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )

    assert result["evidence_root"] == built["evidence_root"]
    assert review["reviewer_public_key"] == "ed25519:" + reviewer_public_key.hex()
    assert review["reviewed_operator_id"] == "operator-a"
    assert review["reviewed_control_group_id"] == "group-a"
    assert review["reviewed_evidence_root"] == built["evidence_root"]

    with pytest.raises(ValueError, match="review basis must not be empty"):
        REVIEW_TOOL.sign_review(
            evidence_dir=evidence_dir,
            reviewer_id="release-reviewer",
            operator_id="operator-a",
            control_group_id="group-a",
            review_basis=" ",
            private_key_path=reviewer_key_path,
        )
