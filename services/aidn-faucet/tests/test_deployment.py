from __future__ import annotations

import json
from argparse import Namespace
from dataclasses import dataclass

import pytest
from aidn_faucet import deployment

from aidn_hypervisor.faucet_treasury import FaucetTreasuryManifest, wallet_id_for_public_key


@dataclass(frozen=True)
class _RuntimeConfig:
    rpc_endpoints: tuple[str, ...] = ("http://rpc-a", "http://rpc-b")
    minimum_agreement: int = 2
    chain_id: str = "aidn-testnet-1"
    timeout_seconds: int = 7


class _DeploymentConfig:
    chain_id = "aidn-testnet-1"

    def runtime_config(self) -> _RuntimeConfig:
        return _RuntimeConfig()


def _manifest(path, *, chain_id: str = "aidn-testnet-1") -> None:
    public_key = "ed25519:" + ("a" * 64)
    manifest = FaucetTreasuryManifest(
        treasury_id="treasury-test-v1",
        network_id="aidn-testnet-1",
        chain_id=chain_id,
        wallet_id=wallet_id_for_public_key(public_key),
        wallet_public_key=public_key,
        creator_recovery_wallet="wallet-creator",
        genesis_allocation_q_atoms=10_000_000_000_000,
        policy_registry_hash="sha256:" + ("b" * 64),
    )
    path.write_text(json.dumps(manifest.model_dump()), encoding="utf-8")


def test_default_factory_binds_manifest_and_quorum(tmp_path, monkeypatch) -> None:
    manifest_path = tmp_path / "faucet-treasury.json"
    _manifest(manifest_path)
    calls: dict[str, object] = {}

    monkeypatch.setattr(
        deployment,
        "load_cometbft_finality_deployment_config",
        lambda path: _DeploymentConfig(),
    )
    monkeypatch.setattr(
        deployment,
        "build_cometbft_multi_rpc_finality_source",
        lambda **kwargs: calls.setdefault("finality", kwargs) or object(),
    )
    monkeypatch.setattr(
        deployment,
        "build_http_cometbft_faucet_submitter",
        lambda **kwargs: calls.setdefault("submitter", kwargs) or object(),
    )

    result = deployment.build_cometbft_submitter(
        Namespace(manifest=manifest_path, finality_config=tmp_path / "finality.json")
    )

    assert result is not None
    assert calls["finality"]["config"].chain_id == "aidn-testnet-1"
    assert calls["submitter"]["rpc_endpoints"] == ("http://rpc-a", "http://rpc-b")
    assert calls["submitter"]["sequence_quorum"] == 2
    assert calls["submitter"]["timeout_seconds"] == 7
    assert calls["submitter"]["treasury_wallet_id"] == wallet_id_for_public_key(
        "ed25519:" + ("a" * 64)
    )


def test_default_factory_rejects_missing_finality_config(tmp_path) -> None:
    manifest_path = tmp_path / "faucet-treasury.json"
    _manifest(manifest_path)

    with pytest.raises(ValueError, match="--finality-config"):
        deployment.build_cometbft_submitter(Namespace(manifest=manifest_path))


def test_default_factory_rejects_manifest_chain_mismatch(tmp_path, monkeypatch) -> None:
    manifest_path = tmp_path / "faucet-treasury.json"
    _manifest(manifest_path, chain_id="aidn-other-chain")
    monkeypatch.setattr(
        deployment,
        "load_cometbft_finality_deployment_config",
        lambda path: _DeploymentConfig(),
    )

    with pytest.raises(ValueError, match="different chains"):
        deployment.build_cometbft_submitter(
            Namespace(manifest=manifest_path, finality_config=tmp_path / "finality.json")
        )
