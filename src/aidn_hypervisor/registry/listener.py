"""Inbound mTLS acceptor for approved Registry replication peers."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Protocol

from aidn_hypervisor.dispatcher.models import NetworkMessage

from .replication_peers import RegistryReplicationPeerController
from .transport_session import REGISTRY_PEER_HANDSHAKE, RegistryReplicationTransportSession


class _TlsAcceptor(Protocol):
    def bind(self) -> None: ...

    def close(self) -> None: ...

    def accept_transport(self): ...


class _PrefetchedTransport:
    def __init__(self, transport, first_message: NetworkMessage) -> None:
        self._transport = transport
        self._first_message = first_message

    def connect(self) -> None:
        self._transport.connect()

    def disconnect(self) -> None:
        self._transport.disconnect()

    @property
    def status(self):
        return self._transport.status

    @property
    def tls_established(self):
        return self._transport.tls_established

    @property
    def peer_verified(self):
        return self._transport.peer_verified

    def send(self, message: NetworkMessage):
        return self._transport.send(message)

    def receive(self):
        if self._first_message is not None:
            message = self._first_message
            self._first_message = None
            return message
        return self._transport.receive()


class RegistryReplicationTlsListener:
    """Accept many inbound mTLS links without trusting a peer before its handshake."""

    def __init__(
        self,
        *,
        acceptor: _TlsAcceptor,
        local_peer_id: str,
        local_public_key: str,
        signer: Callable[[bytes], str],
        peer_controller: RegistryReplicationPeerController,
        maximum_active_peers: int = 32,
        network_id: str = "aidn",
        chain_id: str = "main",
        network_revision: str = "1.0",
    ) -> None:
        if (
            not local_peer_id
            or not local_public_key
            or maximum_active_peers <= 0
            or not network_id
            or not chain_id
            or not network_revision
        ):
            raise ValueError("Registry replication listener configuration is invalid")
        self._acceptor = acceptor
        self._local_peer_id = local_peer_id
        self._local_public_key = local_public_key
        self._signer = signer
        self._peer_controller = peer_controller
        self._maximum_active_peers = maximum_active_peers
        self._network_id = network_id
        self._chain_id = chain_id
        self._network_revision = network_revision
        self._sessions: dict[str, RegistryReplicationTransportSession] = {}
        self._lock = threading.RLock()

    def bind(self) -> None:
        self._acceptor.bind()

    def close(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            session.disconnect()
        self._acceptor.close()

    def accept_once(self) -> str:
        with self._lock:
            if len(self._sessions) >= self._maximum_active_peers:
                raise ConnectionError("Registry replication peer limit reached")
        transport = self._acceptor.accept_transport()
        if not transport.tls_established or not transport.peer_verified:
            transport.disconnect()
            raise ConnectionError("Registry replication listener requires verified mTLS")
        first_message = transport.receive()
        if first_message is None:
            transport.disconnect()
            raise ConnectionError("Registry replication peer closed before handshake")
        if first_message.message_type != REGISTRY_PEER_HANDSHAKE:
            transport.disconnect()
            raise ValueError("Registry replication first message must be a peer handshake")
        peer_id = first_message.source_subject.subject_id
        with self._lock:
            if peer_id in self._sessions:
                transport.disconnect()
                raise ConnectionError("Registry replication peer already has an active session")
        session = RegistryReplicationTransportSession(
            local_peer_id=self._local_peer_id,
            peer_id=peer_id,
            transport=_PrefetchedTransport(transport, first_message),
            peer_controller=self._peer_controller,
            network_id=self._network_id,
            chain_id=self._chain_id,
            network_revision=self._network_revision,
        )
        result = session.receive_once()
        if result != {"event": "peer_handshake", "authenticated": True}:
            session.disconnect()
            raise PermissionError("Registry replication peer handshake was rejected")
        session.send_handshake(local_public_key=self._local_public_key, signer=self._signer)
        with self._lock:
            self._sessions[peer_id] = session
        return peer_id

    def receive_once(self, *, peer_id: str) -> dict | None:
        with self._lock:
            session = self._sessions[peer_id]
        return session.receive_once()

    def flush_outbox(self, *, peer_id: str) -> int:
        """Flush messages addressed to one authenticated inbound peer."""
        with self._lock:
            session = self._sessions[peer_id]
        return session.flush_outbox()

    def disconnect_peer(self, *, peer_id: str) -> None:
        """Close one inbound peer without affecting other accepted links."""
        with self._lock:
            session = self._sessions.pop(peer_id, None)
        if session is not None:
            session.disconnect()

    def peer_transport_connected(self, *, peer_id: str) -> bool:
        """Distinguish an idle receive timeout from a closed inbound transport."""
        with self._lock:
            session = self._sessions.get(peer_id)
        return bool(session and session.is_transport_connected)

    def active_peer_ids(self) -> list[str]:
        with self._lock:
            return sorted(self._sessions)
