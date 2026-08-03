from __future__ import annotations

import base64
import hashlib
import json

import pytest

from aidn_hypervisor.consensus.abci_finality import ABCICommittedFinalitySource
from aidn_hypervisor.consensus.cometbft_crypto import Zip215CometBftEd25519Backend
from aidn_hypervisor.consensus.deployment import (
    CometBftFinalityDeploymentConfig,
    load_cometbft_finality_deployment_config,
)
from aidn_hypervisor.consensus.finality import QuorumConsensusFinalitySource
from aidn_hypervisor.consensus.light_client import (
    CometBftValidator,
    CometBftValidatorSet,
)
from aidn_hypervisor.main import build_app


def _deployment_payload() -> dict:
    raw_public_key = b"checkpoint-public-key-32-bytes!!"
    public_key = base64.b64encode(raw_public_key).decode("ascii")
    validator_address = hashlib.sha256(raw_public_key).digest()[:20].hex().upper()
    validator_set = CometBftValidatorSet(
        (
            CometBftValidator(
                address=validator_address,
                public_key=f"ed25519:{public_key}",
                voting_power=1,
            ),
        )
    )
    validator_set_hash = Zip215CometBftEd25519Backend().validator_set_hash(
        validator_set
    )
    return {
        "rpc_endpoints": [
            "https://validator-a.example",
            "https://validator-b.example/",
        ],
        "minimum_agreement": 2,
        "chain_id": "aidn-testnet-1",
        "verifier_id": "operator-finality-1",
        "trust_period_seconds": 86_400,
        "trusted_checkpoint": {
            "height": 10,
            "block_id": "A" * 64,
            "app_hash": "B" * 64,
            "header_time": "2030-01-01T00:00:00Z",
            "validator_set_hash": validator_set_hash,
            "next_validator_set_hash": validator_set_hash,
            "validators": [
                {
                    "address": validator_address,
                    "public_key": f"ed25519:{public_key}",
                    "voting_power": 1,
                }
            ],
        },
    }


def test_finality_deployment_config_normalizes_endpoints_and_builds_runtime_config():
    config = CometBftFinalityDeploymentConfig.model_validate(_deployment_payload())

    assert config.rpc_endpoints == [
        "https://validator-a.example",
        "https://validator-b.example",
    ]
    runtime = config.runtime_config()
    assert runtime.rpc_endpoints == tuple(config.rpc_endpoints)
    assert runtime.trusted_checkpoint.chain_id == "aidn-testnet-1"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("rpc_endpoints", ["https://only-one.example"], "at least 2"),
        ("rpc_endpoints", ["https://user:pass@example", "https://b.example"], "credential-free"),
        ("rpc_endpoints", ["http://a.example/path", "https://b.example"], "credential-free"),
        ("minimum_agreement", 3, "must not exceed"),
    ],
)
def test_finality_deployment_config_rejects_unsafe_or_ambiguous_values(
    field: str,
    value: object,
    message: str,
) -> None:
    payload = _deployment_payload()
    payload[field] = value

    with pytest.raises(ValueError, match=message):
        CometBftFinalityDeploymentConfig.model_validate(payload)


def test_finality_deployment_config_loader_fails_closed(tmp_path):
    path = tmp_path / "finality.json"
    path.write_text(json.dumps(_deployment_payload()), encoding="utf-8")

    loaded = load_cometbft_finality_deployment_config(path)

    assert loaded.verifier_id == "operator-finality-1"


def test_build_app_binds_configured_non_validator_finality_source(monkeypatch, tmp_path):
    path = tmp_path / "finality.json"
    path.write_text(json.dumps(_deployment_payload()), encoding="utf-8")
    monkeypatch.setenv("AIDN_COMETBFT_FINALITY_CONFIG", str(path))
    monkeypatch.setenv("AIDN_CONSENSUS_MODE", "non_validator")

    app = build_app()

    assert isinstance(app.state.consensus_finality_source, QuorumConsensusFinalitySource)
    assert app.state.hypervisor_service.consensus_finality_source is app.state.consensus_finality_source


def test_build_app_binds_validator_finality_to_the_hypervisor_abci(monkeypatch, tmp_path):
    path = tmp_path / "finality.json"
    path.write_text(json.dumps(_deployment_payload()), encoding="utf-8")
    monkeypatch.setenv("AIDN_COMETBFT_FINALITY_CONFIG", str(path))
    monkeypatch.setenv("AIDN_CONSENSUS_MODE", "validator")
    monkeypatch.setenv("AIDN_HYPERVISOR_STATE_PATH", str(tmp_path / "hypervisor.json"))
    monkeypatch.setenv("AIDN_COMETBFT_ABCI_STATE_PATH", str(tmp_path / "abci"))
    monkeypatch.setenv("AIDN_COMETBFT_ABCI_PORT", "0")

    app = build_app()

    source = app.state.consensus_finality_source
    assert isinstance(source, ABCICommittedFinalitySource)
    assert source._abci_application is app.state.consensus_service.abci


def test_finality_config_requires_enabled_consensus(monkeypatch, tmp_path):
    path = tmp_path / "finality.json"
    path.write_text(json.dumps(_deployment_payload()), encoding="utf-8")
    monkeypatch.setenv("AIDN_COMETBFT_FINALITY_CONFIG", str(path))
    monkeypatch.delenv("AIDN_CONSENSUS_MODE", raising=False)

    with pytest.raises(ValueError, match="enabled ConsensusService"):
        build_app()
