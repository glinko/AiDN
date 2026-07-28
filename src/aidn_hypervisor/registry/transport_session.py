"""Authenticated Registry replication over a secure TransportGateway."""

from __future__ import annotations

import secrets
import time
import uuid
from collections.abc import Callable
from typing import Any

from aidn_hypervisor.dispatcher.models import (
    NetworkMessage,
    NetworkSubject,
    canonical_payload_bytes,
    canonical_payload_hash,
)
from aidn_hypervisor.dispatcher.transport.abc import TransportGateway, TransportStatus

from .peer import peer_authentication_payload
from .replication_peers import RegistryReplicationPeerController

REGISTRY_PEER_HANDSHAKE = "registry_peer_handshake"


class RegistryReplicationTransportSession:
    """Bind one approved Registry peer to one encrypted transport connection.

    The TLS transport protects bytes in transit; the signed handshake binds
    that connection to the operator-configured Registry peer identity. A new
    transport connection always needs a new handshake before replication data
    may flow.
    """

    def __init__(
        self,
        *,
        local_peer_id: str,
        peer_id: str,
        transport: TransportGateway,
        peer_controller: RegistryReplicationPeerController,
        network_id: str = "aidn",
        chain_id: str = "main",
        network_revision: str = "1.0",
        clock: Callable[[], float] = time.time,
        nonce_factory: Callable[[], str] = lambda: secrets.token_urlsafe(24),
        transport_is_secure: Callable[[TransportGateway], bool] | None = None,
    ) -> None:
        if not local_peer_id or not peer_id:
            raise ValueError("local_peer_id and peer_id are required")
        self._local_peer_id = local_peer_id
        self._peer_id = peer_id
        self._transport = transport
        self._peer_controller = peer_controller
        self._network_id = network_id
        self._chain_id = chain_id
        self._network_revision = network_revision
        self._clock = clock
        self._nonce_factory = nonce_factory
        self._transport_is_secure = transport_is_secure or (
            lambda candidate: bool(getattr(candidate, "tls_established", False))
            and bool(getattr(candidate, "peer_verified", False))
        )
        self._outbound_sequence = 0
        self._last_inbound_sequence = -1

    @property
    def is_authenticated(self) -> bool:
        state = self._peer_controller.replicator.get_peer_state(self._peer_id)
        return bool(state and state.connected)

    @property
    def replicator(self):
        """The strict Registry replicator bound to this transport session."""
        return self._peer_controller.replicator

    def connect(self) -> None:
        """Open and verify an encrypted transport; peer auth remains pending."""
        self._transport.connect()
        handshake = getattr(self._transport, "handshake", None)
        if callable(handshake) and not getattr(self._transport, "tls_established", False):
            handshake()
        if not self._transport_is_secure(self._transport):
            self._transport.disconnect()
            raise ConnectionError("Registry replication requires an encrypted transport")

    def disconnect(self) -> None:
        """Invalidate peer authorization before closing the transport."""
        self._peer_controller.disconnect_peer(self._peer_id)
        self._transport.disconnect()

    def reconnect(self) -> None:
        """Replace the transport session; caller must send a fresh handshake."""
        self.disconnect()
        self.connect()

    def send_handshake(
        self,
        *,
        local_public_key: str,
        signer: Callable[[bytes], str],
    ) -> NetworkMessage:
        """Send proof of the local Registry identity for this connection."""
        timestamp = self._clock()
        nonce = self._nonce_factory()
        signature = signer(
            peer_authentication_payload(
                peer_id=self._local_peer_id,
                public_key=local_public_key,
                nonce=nonce,
                timestamp=timestamp,
            )
        )
        if not isinstance(signature, str) or not signature.startswith("ed25519:"):
            raise ValueError("Registry peer signer must return an ed25519 signature")
        message = self._build_message(
            message_type=REGISTRY_PEER_HANDSHAKE,
            payload={
                "peer_handshake": {
                    "peer_id": self._local_peer_id,
                    "public_key": local_public_key,
                    "signature": signature,
                    "nonce": nonce,
                    "timestamp": timestamp,
                }
            },
        )
        self._transport.send(message)
        return message

    def receive_once(self) -> dict[str, Any] | None:
        """Process one secure transport frame and flush protocol responses."""
        message = self._transport.receive()
        if message is None:
            return None
        self._validate_incoming_envelope(message)

        if message.message_type == REGISTRY_PEER_HANDSHAKE:
            handshake = message.payload.get("peer_handshake")
            if not isinstance(handshake, dict):
                raise ValueError("Registry peer handshake payload is invalid")
            authenticated = self._peer_controller.authenticate_peer(
                peer_id=self._peer_id,
                claimed_public_key=str(handshake.get("public_key") or ""),
                signature=str(handshake.get("signature") or ""),
                nonce=str(handshake.get("nonce") or ""),
                timestamp=handshake.get("timestamp"),
            )
            if handshake.get("peer_id") != self._peer_id:
                self._peer_controller.disconnect_peer(self._peer_id)
                raise ValueError("Registry peer handshake identity does not match transport peer")
            return {"event": "peer_handshake", "authenticated": authenticated}

        if not self.is_authenticated:
            raise PermissionError("Registry replication peer is not authenticated")
        registry_payload = message.payload.get("registry_payload")
        if not isinstance(registry_payload, dict):
            raise ValueError("Registry replication payload is invalid")
        if registry_payload.get("registry_message_type") != message.message_type:
            raise ValueError("Registry replication message type does not match payload")
        response = self._peer_controller.replicator.process_incoming_message(
            peer_id=self._peer_id,
            message=message.model_dump(mode="json"),
        )
        sent = self.flush_outbox()
        return {"event": "registry_message", "response": response is not None, "sent": sent}

    def flush_outbox(self) -> int:
        """Send all queued Registry protocol messages after authenticated admission."""
        if not self.is_authenticated:
            raise PermissionError("Registry replication peer is not authenticated")
        pending = self._peer_controller.replicator.get_outbox()
        for raw_message in pending:
            message = NetworkMessage.model_validate(raw_message)
            # The Registry builder may also be used through local queues. The
            # transport session owns the single outer sequence shared with its
            # handshake frames, so re-envelope that message before transmission.
            self._outbound_sequence += 1
            message = message.model_copy(
                update={
                    "source_sequence": self._outbound_sequence,
                    "authentication": {
                        "transport": "TLS",
                        "peer_authentication": "ed25519",
                    },
                }
            )
            self._transport.send(message)
        if pending:
            self._peer_controller.replicator.clear_outbox()
        return len(pending)

    def _build_message(self, *, message_type: str, payload: dict[str, Any]) -> NetworkMessage:
        self._outbound_sequence += 1
        now = self._clock()
        return NetworkMessage(
            message_id=str(uuid.uuid4()),
            message_type=message_type,
            network_id=self._network_id,
            chain_id=self._chain_id,
            network_revision=self._network_revision,
            channel_id="registry:replication",
            channel_class="REGISTRY",
            source_subject=NetworkSubject(
                subject_type="registry_node",
                subject_id=self._local_peer_id,
            ),
            destination_subject=NetworkSubject(
                subject_type="registry_node",
                subject_id=self._peer_id,
            ),
            source_sequence=self._outbound_sequence,
            route_generation=1,
            created_at=str(now),
            expiration=str(now + 300),
            hop_limit=1,
            payload_hash=canonical_payload_hash(payload),
            payload_length=len(canonical_payload_bytes(payload)),
            payload=payload,
            authentication={"transport": "TLS", "peer_authentication": "ed25519"},
        )

    def _validate_incoming_envelope(self, message: NetworkMessage) -> None:
        if self._transport.status != TransportStatus.CONNECTED:
            raise ConnectionError("Registry replication transport is not connected")
        if message.network_id != self._network_id or message.chain_id != self._chain_id:
            raise ValueError("Registry replication network identity mismatch")
        if message.network_revision != self._network_revision:
            raise ValueError("Registry replication network revision mismatch")
        if message.channel_class != "REGISTRY" or message.channel_id != "registry:replication":
            raise ValueError("Registry replication channel is invalid")
        if (
            message.source_subject.subject_type != "registry_node"
            or message.source_subject.subject_id != self._peer_id
            or message.destination_subject.subject_type != "registry_node"
            or message.destination_subject.subject_id != self._local_peer_id
        ):
            raise ValueError("Registry replication peer identity is invalid")
        if message.source_sequence <= self._last_inbound_sequence:
            raise ValueError("Registry replication transport sequence is stale")
        self._last_inbound_sequence = message.source_sequence
