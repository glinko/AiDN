import time

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aidn_hypervisor.registry.peer import peer_authentication_payload
from aidn_hypervisor.registry.replication_peers import RegistryReplicationPeerController
from aidn_hypervisor.registry.replicator import RegistryReplicator
from aidn_hypervisor.registry_service import RegistryService


def _key_pair() -> tuple[Ed25519PrivateKey, str]:
    private_key = Ed25519PrivateKey.generate()
    public_key = "ed25519:" + private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()
    return private_key, public_key


def _signature(
    private_key: Ed25519PrivateKey,
    *,
    peer_id: str,
    public_key: str,
    nonce: str,
    timestamp: float,
) -> str:
    return "ed25519:" + private_key.sign(
        peer_authentication_payload(
            peer_id=peer_id,
            public_key=public_key,
            nonce=nonce,
            timestamp=timestamp,
        )
    ).hex()


def test_registry_service_persists_replication_peer_configuration(tmp_path) -> None:
    _, public_key = _key_pair()
    snapshot_path = tmp_path / "registry.json"
    service = RegistryService(snapshot_path=snapshot_path)

    stored = service.upsert_replication_peer(
        peer_id="registry-a",
        public_key=public_key,
    )

    restarted = RegistryService(snapshot_path=snapshot_path)
    assert restarted.list_replication_peers() == [stored]


def test_replication_peer_controller_rejects_unconfigured_peer() -> None:
    private_key, public_key = _key_pair()
    service = RegistryService()
    replicator = RegistryReplicator(
        node_id="registry-local",
        require_authenticated_peers=True,
    )
    controller = RegistryReplicationPeerController(
        registry_service=service,
        replicator=replicator,
    )
    timestamp = time.time()

    assert not controller.authenticate_peer(
        peer_id="registry-unknown",
        claimed_public_key=public_key,
        signature=_signature(
            private_key,
            peer_id="registry-unknown",
            public_key=public_key,
            nonce="unknown-1",
            timestamp=timestamp,
        ),
        nonce="unknown-1",
        timestamp=timestamp,
    )
    assert replicator.get_peer_state("registry-unknown").connected is False


def test_replication_peer_controller_authenticates_and_revokes_rotated_key() -> None:
    private_key, public_key = _key_pair()
    service = RegistryService()
    service.upsert_replication_peer(peer_id="registry-a", public_key=public_key)
    replicator = RegistryReplicator(
        node_id="registry-local",
        require_authenticated_peers=True,
    )
    controller = RegistryReplicationPeerController(
        registry_service=service,
        replicator=replicator,
    )
    timestamp = time.time()

    assert controller.authenticate_peer(
        peer_id="registry-a",
        claimed_public_key=public_key,
        signature=_signature(
            private_key,
            peer_id="registry-a",
            public_key=public_key,
            nonce="registry-a-1",
            timestamp=timestamp,
        ),
        nonce="registry-a-1",
        timestamp=timestamp,
    )
    assert replicator.get_peer_state("registry-a").connected is True
    assert service.list_replication_peers()[0]["last_authenticated_at"] is not None

    _, replacement_key = _key_pair()
    service.upsert_replication_peer(
        peer_id="registry-a",
        public_key=replacement_key,
    )
    assert controller.reload_configured_peers() == 1
    assert replicator.get_peer_state("registry-a").connected is False


def test_replication_peer_controller_requires_strict_replicator() -> None:
    with pytest.raises(ValueError, match="strict peer auth"):
        RegistryReplicationPeerController(
            registry_service=RegistryService(),
            replicator=RegistryReplicator(node_id="registry-local"),
        )
