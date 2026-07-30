from __future__ import annotations

import time
from collections.abc import Callable

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aidn_hypervisor.dispatcher.models import NetworkMessage
from aidn_hypervisor.dispatcher.transport.abc import TransportStatus
from aidn_hypervisor.registry.replication_peers import RegistryReplicationPeerController
from aidn_hypervisor.registry.replicator import RegistryReplicator
from aidn_hypervisor.registry.transport_session import RegistryReplicationTransportSession
from aidn_hypervisor.registry_service import RegistryService


class _MemoryTlsTransport:
    def __init__(self) -> None:
        self.status = TransportStatus.DISCONNECTED
        self.tls_established = False
        self.peer_verified = False
        self.sent: list[NetworkMessage] = []
        self.incoming: list[NetworkMessage] = []

    def connect(self) -> None:
        self.status = TransportStatus.CONNECTED

    def handshake(self) -> None:
        self.tls_established = True
        self.peer_verified = True

    def disconnect(self) -> None:
        self.status = TransportStatus.DISCONNECTED
        self.tls_established = False
        self.peer_verified = False

    def send(self, message: NetworkMessage) -> bytes:
        if self.status != TransportStatus.CONNECTED:
            raise ConnectionError("transport disconnected")
        self.sent.append(message)
        return b"sent"

    def receive(self) -> NetworkMessage | None:
        return self.incoming.pop(0) if self.incoming else None


def _key_pair() -> tuple[Ed25519PrivateKey, str, Callable[[bytes], str]]:
    private_key = Ed25519PrivateKey.generate()
    public_key = "ed25519:" + private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()
    return private_key, public_key, lambda payload: "ed25519:" + private_key.sign(payload).hex()


def _session_pair() -> tuple[
    RegistryReplicationTransportSession,
    RegistryReplicationTransportSession,
    Callable[[bytes], str],
    Callable[[bytes], str],
    str,
    str,
    _MemoryTlsTransport,
    _MemoryTlsTransport,
]:
    _, key_a, signer_a = _key_pair()
    _, key_b, signer_b = _key_pair()
    service_a = RegistryService()
    service_a.upsert_replication_peer(peer_id="registry-b", public_key=key_b)
    service_b = RegistryService()
    service_b.upsert_replication_peer(peer_id="registry-a", public_key=key_a)
    transport_a = _MemoryTlsTransport()
    transport_b = _MemoryTlsTransport()
    session_a = RegistryReplicationTransportSession(
        local_peer_id="registry-a",
        peer_id="registry-b",
        transport=transport_a,
        peer_controller=RegistryReplicationPeerController(
            registry_service=service_a,
            replicator=RegistryReplicator(
                node_id="registry-a", require_authenticated_peers=True
            ),
        ),
    )
    session_b = RegistryReplicationTransportSession(
        local_peer_id="registry-b",
        peer_id="registry-a",
        transport=transport_b,
        peer_controller=RegistryReplicationPeerController(
            registry_service=service_b,
            replicator=RegistryReplicator(
                node_id="registry-b", require_authenticated_peers=True
            ),
        ),
    )
    session_a.connect()
    session_b.connect()
    return (
        session_a,
        session_b,
        signer_a,
        signer_b,
        key_a,
        key_b,
        transport_a,
        transport_b,
    )


def test_transport_session_requires_encryption() -> None:
    _, key, _ = _key_pair()
    service = RegistryService()
    service.upsert_replication_peer(peer_id="registry-b", public_key=key)
    transport = _MemoryTlsTransport()
    session = RegistryReplicationTransportSession(
        local_peer_id="registry-a",
        peer_id="registry-b",
        transport=transport,
        peer_controller=RegistryReplicationPeerController(
            registry_service=service,
            replicator=RegistryReplicator(
                node_id="registry-a", require_authenticated_peers=True
            ),
        ),
        transport_is_secure=lambda _: False,
    )

    with pytest.raises(ConnectionError, match="encrypted transport"):
        session.connect()
    assert transport.status == TransportStatus.DISCONNECTED


def test_transport_session_requires_verified_peer_by_default() -> None:
    _, key, _ = _key_pair()
    service = RegistryService()
    service.upsert_replication_peer(peer_id="registry-b", public_key=key)
    transport = _MemoryTlsTransport()
    transport.handshake = lambda: setattr(transport, "tls_established", True)
    session = RegistryReplicationTransportSession(
        local_peer_id="registry-a",
        peer_id="registry-b",
        transport=transport,
        peer_controller=RegistryReplicationPeerController(
            registry_service=service,
            replicator=RegistryReplicator(
                node_id="registry-a", require_authenticated_peers=True
            ),
        ),
    )

    with pytest.raises(ConnectionError, match="encrypted transport"):
        session.connect()


def test_transport_session_authenticates_and_requires_new_handshake_after_reconnect() -> None:
    session_a, session_b, signer_a, signer_b, key_a, key_b, transport_a, transport_b = (
        _session_pair()
    )
    transport_a.incoming.append(session_b.send_handshake(local_public_key=key_b, signer=signer_b))
    transport_b.incoming.append(session_a.send_handshake(local_public_key=key_a, signer=signer_a))

    assert session_a.receive_once() == {"event": "peer_handshake", "authenticated": True}
    assert session_b.receive_once() == {"event": "peer_handshake", "authenticated": True}
    assert session_a.is_authenticated
    assert session_b.is_authenticated

    session_a.reconnect()

    assert not session_a.is_authenticated
    with pytest.raises(PermissionError, match="not authenticated"):
        session_a.flush_outbox()


def test_transport_session_resets_envelope_sequences_on_reconnect() -> None:
    session_a, session_b, signer_a, signer_b, key_a, key_b, transport_a, transport_b = (
        _session_pair()
    )
    transport_b.incoming.append(session_a.send_handshake(local_public_key=key_a, signer=signer_a))
    transport_a.incoming.append(session_b.send_handshake(local_public_key=key_b, signer=signer_b))
    assert session_b.receive_once() == {"event": "peer_handshake", "authenticated": True}
    assert session_a.receive_once() == {"event": "peer_handshake", "authenticated": True}

    session_a.reconnect()
    session_b.reconnect()
    renewed_handshake = session_a.send_handshake(local_public_key=key_a, signer=signer_a)

    assert renewed_handshake.source_sequence == 1
    transport_b.incoming.append(renewed_handshake)
    assert session_b.receive_once() == {"event": "peer_handshake", "authenticated": True}


def test_transport_session_rejects_stale_transport_sequence() -> None:
    session_a, session_b, signer_a, signer_b, key_a, key_b, transport_a, transport_b = (
        _session_pair()
    )
    handshake_a = session_a.send_handshake(local_public_key=key_a, signer=signer_a)
    handshake_b = session_b.send_handshake(local_public_key=key_b, signer=signer_b)
    transport_b.incoming.extend([handshake_a, handshake_a])
    transport_a.incoming.append(handshake_b)

    assert session_b.receive_once() == {"event": "peer_handshake", "authenticated": True}
    assert session_a.receive_once() == {"event": "peer_handshake", "authenticated": True}
    with pytest.raises(ValueError, match="sequence is stale"):
        session_b.receive_once()


def test_transport_session_rejects_expired_or_relayed_frames() -> None:
    session_a, session_b, signer_a, signer_b, key_a, key_b, transport_a, transport_b = (
        _session_pair()
    )
    handshake_a = session_a.send_handshake(local_public_key=key_a, signer=signer_a)
    handshake_b = session_b.send_handshake(local_public_key=key_b, signer=signer_b)
    transport_b.incoming.append(handshake_a)
    transport_a.incoming.append(handshake_b)
    assert session_b.receive_once() == {"event": "peer_handshake", "authenticated": True}
    assert session_a.receive_once() == {"event": "peer_handshake", "authenticated": True}

    expired = handshake_a.model_copy(
        update={
            "source_sequence": 2,
            "created_at": str(time.time() - 20),
            "expiration": str(time.time() - 10),
        }
    )
    transport_b.incoming.append(expired)
    with pytest.raises(ValueError, match="message is expired"):
        session_b.receive_once()

    relayed = handshake_a.model_copy(
        update={"source_sequence": 3, "hop_limit": 2}
    )
    transport_b.incoming.append(relayed)
    with pytest.raises(ValueError, match="direct one-hop"):
        session_b.receive_once()


def test_transport_session_forwards_authenticated_registry_messages() -> None:
    session_a, session_b, signer_a, signer_b, key_a, key_b, transport_a, transport_b = (
        _session_pair()
    )
    transport_b.incoming.append(session_a.send_handshake(local_public_key=key_a, signer=signer_a))
    transport_a.incoming.append(session_b.send_handshake(local_public_key=key_b, signer=signer_b))
    assert session_b.receive_once() == {"event": "peer_handshake", "authenticated": True}
    assert session_a.receive_once() == {"event": "peer_handshake", "authenticated": True}

    session_a.replicator.build_inventory_request("registry-b")
    assert session_a.flush_outbox() == 1
    transport_b.incoming.append(transport_a.sent[-1])

    result = session_b.receive_once()

    assert result == {"event": "registry_message", "response": True, "sent": 1}
    response = transport_b.sent[-1]
    assert response.channel_class == "REGISTRY"
    assert response.payload["registry_payload"]["registry_message_type"] == (
        "registry_inventory_response"
    )
