from __future__ import annotations

import os

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aidn_hypervisor.registry.deployment import (
    RegistryReplicationDeploymentConfig,
    build_registry_replication_runtime,
)
from aidn_hypervisor.registry_service import RegistryService
from aidn_hypervisor.secrets import FileSecretManager


def _secret_manager(tmp_path) -> tuple[FileSecretManager, bytes]:
    manager = FileSecretManager(path=tmp_path / "secrets.json", master_key=os.urandom(32))
    signing_key = Ed25519PrivateKey.generate()
    raw_signing_key = signing_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    manager.put(handle="secret://registry/signing-key", value=raw_signing_key)
    for handle in ("certificate", "private-key", "ca"):
        manager.put(handle=f"secret://registry/{handle}", value=b"test-only-tls-material")
    return manager, raw_signing_key


def _config() -> RegistryReplicationDeploymentConfig:
    return RegistryReplicationDeploymentConfig.model_validate(
        {
            "local_peer_id": "registry-a",
            "signing_key_handle": "secret://registry/signing-key",
            "outbound_peers": [
                {
                    "peer_id": "registry-b",
                    "host": "registry-b.example",
                    "port": 443,
                    "tls": {
                        "certificate_handle": "secret://registry/certificate",
                        "private_key_handle": "secret://registry/private-key",
                        "certificate_authority_handle": "secret://registry/ca",
                    },
                }
            ],
        }
    )


def _remote_public_key() -> str:
    private_key = Ed25519PrivateKey.generate()
    raw = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return "ed25519:" + raw.hex()


def test_deployment_runtime_requires_operator_approved_outbound_peer(tmp_path) -> None:
    manager, _ = _secret_manager(tmp_path)

    with pytest.raises(ValueError, match="not locally approved"):
        build_registry_replication_runtime(
            config=_config(),
            registry_service=RegistryService(),
            secret_manager=manager,
        )


def test_deployment_runtime_uses_secret_handles_and_cleans_material(tmp_path) -> None:
    manager, signing_key = _secret_manager(tmp_path)
    registry = RegistryService()
    registry.upsert_replication_peer(peer_id="registry-b", public_key=_remote_public_key())

    runtime = build_registry_replication_runtime(
        config=_config(),
        registry_service=registry,
        secret_manager=manager,
    )

    assert runtime.status()["outbound_peers"][0]["peer_id"] == "registry-b"
    runtime.stop()
    assert runtime.is_running is False
    assert len(signing_key) == 32


def test_deployment_runtime_projects_registry_objects_and_uses_configured_network(tmp_path) -> None:
    manager, _ = _secret_manager(tmp_path)
    registry = RegistryService()
    registry.upsert_replication_peer(peer_id="registry-b", public_key=_remote_public_key())
    registry.upsert_registry_object(
        {
            "object_id": "persisted-object",
            "object_type": "advertisement",
            "object_version": "1.0",
            "namespace": "controlled-lan",
            "payload": {"endpoint_id": "endpoint-a"},
        }
    )
    config_payload = _config().model_dump(mode="json")
    config_payload.update(
        {
            "network_id": "aidn-controlled-lan",
            "chain_id": "registry-lab-v1",
            "network_revision": "2.0",
        }
    )

    runtime = build_registry_replication_runtime(
        config=RegistryReplicationDeploymentConfig.model_validate(config_payload),
        registry_service=registry,
        secret_manager=manager,
    )

    assert runtime.replicator is not None
    assert runtime.replicator.store.has("persisted-object")
    builder = runtime.replicator._builder
    assert builder._network_id == "aidn-controlled-lan"
    assert builder._chain_id == "registry-lab-v1"
    assert builder._network_revision == "2.0"
    runtime.stop()


def test_deployment_config_rejects_duplicate_outbound_peer_ids() -> None:
    payload = _config().model_dump(mode="json")
    payload["outbound_peers"].append(payload["outbound_peers"][0])

    with pytest.raises(ValueError, match="must be unique"):
        RegistryReplicationDeploymentConfig.model_validate(payload)
