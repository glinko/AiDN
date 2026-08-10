from __future__ import annotations

import json

import pytest

from aidn_hypervisor.faucet_treasury import FaucetTreasuryManifest


def test_credential_generator_creates_secret_separated_manifest(tmp_path, monkeypatch) -> None:
    import runpy
    import sys

    output_dir = tmp_path / "credentials"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "create-faucet-credentials.py",
            "--output-dir",
            str(output_dir),
            "--treasury-id",
            "faucet-test-v1",
            "--network-id",
            "aidn-testnet-1",
            "--chain-id",
            "aidn-testnet-1",
            "--creator-recovery-wallet",
            "wallet-creator",
            "--policy-registry-hash",
            "sha256:" + ("ab" * 32),
        ],
    )
    with pytest.raises(SystemExit) as result:
        runpy.run_path("tools/create-faucet-credentials.py", run_name="__main__")
    assert result.value.code == 0

    manifest = FaucetTreasuryManifest.model_validate_json(
        (output_dir / "faucet-treasury.json").read_text(encoding="utf-8")
    )
    assert manifest.treasury_id == "faucet-test-v1"
    assert len((output_dir / "treasury.key").read_text(encoding="utf-8").strip()) == 64
    assert len((output_dir / "agent-token").read_text(encoding="utf-8").strip()) >= 40
    assert len((output_dir / "creator-token").read_text(encoding="utf-8").strip()) >= 40
    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["manifest_hash"] == manifest.manifest_hash
    assert "agent_token" not in summary
    assert "creator_token" not in summary


def test_credential_generator_requires_consensus_funding_id(tmp_path) -> None:
    import runpy
    import sys

    sys.argv = [
        "create-faucet-credentials.py",
        "--output-dir",
        str(tmp_path / "credentials"),
        "--treasury-id",
        "faucet-test-v1",
        "--network-id",
        "aidn-testnet-1",
        "--chain-id",
        "aidn-testnet-1",
        "--creator-recovery-wallet",
        "wallet-creator",
        "--policy-registry-hash",
        "sha256:" + ("ab" * 32),
        "--funding-mode",
        "CONSENSUS",
    ]
    with pytest.raises(SystemExit, match="funding-id"):
        runpy.run_path("tools/create-faucet-credentials.py", run_name="__main__")
