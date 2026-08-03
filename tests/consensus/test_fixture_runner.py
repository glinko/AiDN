from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from aidn_hypervisor.consensus.fixture_runner import (
    FixtureError,
    run_fixture,
    run_fixture_set,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "fixtures/valid/wallet-transfer-001.json"
MANIFEST = ROOT / "fixtures/manifest.json"


def test_checked_in_fixture_manifest_executes_strictly() -> None:
    results = run_fixture_set(MANIFEST, strict=True)

    assert len(results) == 1
    assert results[0].fixture_id == "wallet-transfer-001"
    assert results[0].result_codes == ("ok",)
    assert results[0].post_app_hash == (
        "b19273f7b2c8707e93390960a0364ee5220410dc206935ac637182deb5948777"
    )


def test_fixture_runner_rejects_changed_operation_identity(tmp_path: Path) -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    fixture["operation"]["payload"]["amount"] = 26
    mutated = tmp_path / FIXTURE.name
    mutated.write_text(json.dumps(fixture), encoding="utf-8")

    with pytest.raises(
        FixtureError,
        match="operation envelope is invalid|canonical operation mismatch|operation ID mismatch",
    ):
        run_fixture(mutated, strict=True)


def test_fixture_runner_rejects_manifest_fixture_profile_mismatch(tmp_path: Path) -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    fixture["profile_id"] = "other-profile"
    fixture_path = tmp_path / FIXTURE.name
    fixture_path.write_text(json.dumps(fixture), encoding="utf-8")
    digest = hashlib.sha256(fixture_path.read_bytes()).hexdigest()
    manifest = {
        "fixture_set_version": 1,
        "profile_id": "aidn-mainnet-candidate-1",
        "fixture_count": 1,
        "files": [{"path": fixture_path.name, "sha256": digest}],
    }
    canonical = json.dumps(manifest, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    manifest["manifest_hash"] = "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(FixtureError, match="fixture profile mismatch"):
        run_fixture_set(manifest_path, strict=True)
