from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


def _release_builder_module():
    path = Path(__file__).parents[1] / "tools" / "build-release-integrity-report.py"
    spec = importlib.util.spec_from_file_location("release_integrity_builder", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_public_release_binding_requires_independent_profile_trust_input() -> None:
    module = _release_builder_module()

    with pytest.raises(ValueError, match="requires --network-profile"):
        module._public_network_release_binding(
            profile_path=None,
            trusted_signers_path=None,
            required=True,
        )


def test_public_release_binding_records_verified_profile_facts(monkeypatch, tmp_path: Path) -> None:
    module = _release_builder_module()
    profile_path = tmp_path / "network-profile.toml"
    signer_path = tmp_path / "trusted-signers.json"
    profile_path.write_text("profile", encoding="utf-8")
    signer_path.write_text("{}", encoding="utf-8")
    (tmp_path / "public-network.json").write_text("{}", encoding="utf-8")
    profile = SimpleNamespace(
        network=SimpleNamespace(
            network_id="aidn-testnet",
            chain_id="aidn-testnet-1",
            environment="testnet",
            protocol_version="0.1",
            genesis_file="genesis.json",
            genesis_sha256="sha256:" + "a" * 64,
            public_profile_file="public-network.json",
            public_profile_sha256="sha256:" + "b" * 64,
        ),
        consensus_binding_hash="sha256:" + "c" * 64,
    )
    monkeypatch.setattr(module, "load_network_profile_signers", lambda _: {"authority": "ed25519:key"})
    monkeypatch.setattr(module, "verify_network_profile", lambda *_args, **_kwargs: SimpleNamespace(valid=True, errors=[]))
    monkeypatch.setattr(module, "load_network_profile", lambda _: profile)
    monkeypatch.setattr(module, "_sha256_file", lambda _: "sha256:" + "d" * 64)
    monkeypatch.setattr(
        module.PublicMultiValidatorNetworkProfile,
        "model_validate_json",
        lambda _: SimpleNamespace(
            profile_hash="sha256:" + "e" * 64,
            validator_manifests=[SimpleNamespace(genesis_hash="sha256:" + "a" * 64)],
        ),
    )

    binding = module._public_network_release_binding(
        profile_path=profile_path,
        trusted_signers_path=signer_path,
        required=True,
    )

    assert binding == {
        "network_id": "aidn-testnet",
        "chain_id": "aidn-testnet-1",
        "environment": "testnet",
        "protocol_version": "0.1",
        "consensus_binding_hash": "sha256:" + "c" * 64,
        "network_profile_sha256": "sha256:" + "d" * 64,
        "genesis_file": "genesis.json",
        "genesis_sha256": "sha256:" + "a" * 64,
        "public_profile_file": "public-network.json",
        "public_profile_sha256": "sha256:" + "b" * 64,
        "public_profile_hash": "sha256:" + "e" * 64,
    }
