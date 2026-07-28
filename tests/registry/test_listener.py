from collections.abc import Callable

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aidn_hypervisor.dispatcher.models import NetworkMessage
from aidn_hypervisor.dispatcher.transport.abc import TransportStatus
from aidn_hypervisor.registry.listener import RegistryReplicationTlsListener
from aidn_hypervisor.registry.replication_peers import RegistryReplicationPeerController
from aidn_hypervisor.registry.replicator import RegistryReplicator
from aidn_hypervisor.registry_service import RegistryService


class _Transport:
    def __init__(self, *, peer_verified: bool = True) -> None:
        self.status = TransportStatus.CONNECTED
        self.tls_established = True
        self.peer_verified = peer_verified
        self.incoming: list[NetworkMessage] = []
        self.sent: list[NetworkMessage] = []

    def connect(self) -> None:
        return None

    def disconnect(self) -> None:
        self.status = TransportStatus.DISCONNECTED

    def send(self, message: NetworkMessage) -> bytes:
        self.sent.append(message)
        return b"sent"

    def receive(self) -> NetworkMessage | None:
        return self.incoming.pop(0) if self.incoming else None


class _Acceptor:
    def __init__(self, transport: _Transport) -> None:
        self.transport = transport
        self.bound = False
        self.closed = False

    def bind(self) -> None:
        self.bound = True

    def close(self) -> None:
        self.closed = True

    def accept_transport(self) -> _Transport:
        return self.transport


def _key_pair() -> tuple[str, Callable[[bytes], str]]:
    private_key = Ed25519PrivateKey.generate()
    public_key = "ed25519:" + private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()
    return public_key, lambda payload: "ed25519:" + private_key.sign(payload).hex()


def _listener(transport: _Transport):
    local_key, signer = _key_pair()
    remote_key, _ = _key_pair()
    service = RegistryService()
    service.upsert_replication_peer(peer_id="registry-b", public_key=remote_key)
    listener = RegistryReplicationTlsListener(
        acceptor=_Acceptor(transport),
        local_peer_id="registry-a",
        local_public_key=local_key,
        signer=signer,
        peer_controller=RegistryReplicationPeerController(
            registry_service=service,
            replicator=RegistryReplicator(node_id="registry-a", require_authenticated_peers=True),
        ),
    )
    return listener, local_key, remote_key


def test_listener_rejects_unverified_tls_peer() -> None:
    transport = _Transport(peer_verified=False)
    listener, _, _ = _listener(transport)

    with pytest.raises(ConnectionError, match="verified mTLS"):
        listener.accept_once()
    assert transport.status == TransportStatus.DISCONNECTED
