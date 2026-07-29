from collections.abc import Callable

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aidn_hypervisor.dispatcher.models import NetworkMessage
from aidn_hypervisor.dispatcher.transport.abc import TransportStatus
from aidn_hypervisor.registry.listener import RegistryReplicationTlsListener
from aidn_hypervisor.registry.replication_peers import RegistryReplicationPeerController
from aidn_hypervisor.registry.replicator import RegistryReplicator
from aidn_hypervisor.registry.transport_session import RegistryReplicationTransportSession
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


def _listener(transport: _Transport, **network_config: str):
    local_key, signer = _key_pair()
    remote_key, remote_signer = _key_pair()
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
        **network_config,
    )
    return listener, local_key, remote_key, remote_signer


def test_listener_rejects_unverified_tls_peer() -> None:
    transport = _Transport(peer_verified=False)
    listener, _, _, _ = _listener(transport)

    with pytest.raises(ConnectionError, match="verified mTLS"):
        listener.accept_once()
    assert transport.status == TransportStatus.DISCONNECTED


def test_listener_disconnects_only_the_requested_peer() -> None:
    class _Session:
        def __init__(self) -> None:
            self.disconnected = False

        def disconnect(self) -> None:
            self.disconnected = True

    transport = _Transport()
    listener, _, _, _ = _listener(transport)
    session = _Session()
    listener._sessions["registry-b"] = session  # type: ignore[assignment]

    listener.disconnect_peer(peer_id="registry-b")

    assert listener.active_peer_ids() == []
    assert session.disconnected is True


def test_listener_uses_configured_network_identity_in_handshake_response() -> None:
    server_transport = _Transport()
    listener, local_key, remote_key, remote_signer = _listener(
        server_transport,
        network_id="aidn-lab",
        chain_id="registry-lab",
        network_revision="7",
    )
    client_registry = RegistryService()
    client_registry.upsert_replication_peer(peer_id="registry-a", public_key=local_key)
    client_transport = _Transport()
    client_session = RegistryReplicationTransportSession(
        local_peer_id="registry-b",
        peer_id="registry-a",
        transport=client_transport,
        peer_controller=RegistryReplicationPeerController(
            registry_service=client_registry,
            replicator=RegistryReplicator(node_id="registry-b", require_authenticated_peers=True),
        ),
        network_id="aidn-lab",
        chain_id="registry-lab",
        network_revision="7",
    )
    client_session.send_handshake(local_public_key=remote_key, signer=remote_signer)
    server_transport.incoming.append(client_transport.sent[0])

    assert listener.accept_once() == "registry-b"
    response = server_transport.sent[0]
    assert response.network_id == "aidn-lab"
    assert response.chain_id == "registry-lab"
    assert response.network_revision == "7"
