from __future__ import annotations

from datetime import UTC, datetime

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from aidn_hypervisor.main import build_app
from aidn_hypervisor.snapshot.deployment import (
    RemoteTrustAnchorDeploymentConfig,
    RemoteTrustAnchorRuntime,
    load_remote_trust_anchor_deployment_config,
)
from aidn_hypervisor.snapshot.sync_mode import SyncModeConfig
from aidn_hypervisor.snapshot.trust_anchor import TrustAnchor, sign_trust_anchor


class _Client:
    def __init__(self, envelope) -> None:
        self.envelope = envelope
        self.sources: list[str] = []

    def fetch(self, source_url: str):
        self.sources.append(source_url)
        return self.envelope


def test_remote_trust_anchor_runtime_verifies_persists_and_projects_sync_config(tmp_path) -> None:
    private_key = Ed25519PrivateKey.generate()
    private_bytes = private_key.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    public_key = "ed25519:" + private_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    ).hex()
    now = datetime.now(UTC).isoformat()
    envelope = sign_trust_anchor(
        anchor=TrustAnchor(
            network_id="aidn-testnet",
            chain_id="aidn-testnet-1",
            network_revision=1,
            block_height=50,
            block_hash="block",
            application_state_hash="app",
            validator_set_hash="validators",
            protocol_version="1",
            source="remote_signed",
            created_at=now,
        ),
        signer_id="testnet-authority",
        issued_at=now,
        private_key=private_bytes,
    )
    config = RemoteTrustAnchorDeploymentConfig(
        source_url="https://anchors.example.test/aidn-testnet.json",
        storage_path=tmp_path / "anchors.json",
        trusted_signers={"testnet-authority": public_key},
        expected_network_id="aidn-testnet",
        expected_chain_id="aidn-testnet-1",
        expected_network_revision=1,
    )
    client = _Client(envelope)
    runtime = RemoteTrustAnchorRuntime(config=config, client=client)

    assert runtime.refresh() == envelope
    sync_config = runtime.apply_to_sync_mode_config(
        SyncModeConfig(has_local_state=False), current_height=55, current_time=now
    )

    assert client.sources == [config.source_url]
    assert runtime.latest() == envelope
    assert sync_config.trust_anchor_valid is True
    assert sync_config.trust_anchor_height == 50


def test_remote_trust_anchor_deployment_config_loads_from_json(tmp_path) -> None:
    path = tmp_path / "remote-anchor.json"
    path.write_text(
        """{
          "source_url": "https://anchors.example.test/aidn.json",
          "storage_path": "anchors.json",
          "trusted_signers": {"authority": "ed25519:0011"},
          "expected_network_id": "aidn-testnet",
          "expected_chain_id": "aidn-testnet-1",
          "expected_network_revision": 1
        }""",
        encoding="utf-8",
    )

    config = load_remote_trust_anchor_deployment_config(path)

    assert config.source_url == "https://anchors.example.test/aidn.json"
    assert config.storage_path.name == "anchors.json"


def test_remote_trust_anchor_deployment_config_rejects_non_https_source(tmp_path) -> None:
    with pytest.raises(ValueError, match="must use HTTPS"):
        RemoteTrustAnchorDeploymentConfig(
            source_url="http://anchors.example.test/aidn.json",
            storage_path=tmp_path / "anchors.json",
            trusted_signers={"authority": "ed25519:0011"},
            expected_network_id="aidn-testnet",
            expected_chain_id="aidn-testnet-1",
            expected_network_revision=1,
        )


def test_configured_remote_trust_anchor_refreshes_during_app_lifespan() -> None:
    class _Runtime:
        refresh_count = 0

        def refresh(self) -> None:
            self.refresh_count += 1

    runtime = _Runtime()
    app = build_app(remote_trust_anchor_runtime=runtime)

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200

    assert runtime.refresh_count == 1
    assert app.state.remote_trust_anchor_runtime is runtime
