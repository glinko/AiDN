"""Registry Replication Controller (M9-S3).

High-level controller that coordinates inventory exchange, object retrieval,
sync status tracking, and announcement broadcasting across the registry
replication network transport.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from .channel import RegistryChannelManager
from .inventory import BloomFilter
from .messages import (
    InventoryResponsePayload,
    ObjectResponsePayload,
    RegistryMessageBuilder,
    RegistryMessageType,
)
from .object_envelope import RegistryObjectEnvelope
from .peer import PeerAuthenticator
from .replication import ReplicationEngine
from .routes import create_default_registry_channels
from .storage import ImmutableObjectStore
from .sync import SyncController, SyncMode

# ---------------------------------------------------------------------------
# Peer replication state
# ---------------------------------------------------------------------------


class ReplicationState(BaseModel):
    """Current replication state for a peer connection."""

    peer_id: str
    connected: bool = False
    inventory_exchanged: bool = False
    objects_pending: int = 0
    objects_transferred: int = 0
    bytes_transferred: int = 0
    last_activity_at: float = 0.0
    error: str | None = None


# ---------------------------------------------------------------------------
# Registry Replicator
# ---------------------------------------------------------------------------


class RegistryReplicator:
    """
    High-level registry replication controller.

    Coordinates:
    - Inventory exchange (bloom filter comparison)
    - Object retrieval and transfer
    - Sync status tracking
    - Announcement broadcasting
    - Channel management and message routing

    Uses ReplicationEngine + SyncController internally and exposes
    a clean API for transport integration.
    """

    def __init__(
        self,
        *,
        node_id: str,
        store: ImmutableObjectStore | None = None,
        network_id: str = "aidn",
        chain_id: str = "main",
        network_revision: str = "1.0",
        maximum_inventory_object_ids: int = 500,
        peer_authenticator: PeerAuthenticator | None = None,
        require_authenticated_peers: bool = False,
    ):
        if maximum_inventory_object_ids < 1:
            raise ValueError("maximum_inventory_object_ids must be at least one")
        self._node_id = node_id
        self._store = store or ImmutableObjectStore()
        self._engine = ReplicationEngine(self._store)
        self._sync = SyncController(self._store)
        self._channel_manager = create_default_registry_channels()
        self._builder = RegistryMessageBuilder(
            node_id=node_id,
            network_id=network_id,
            chain_id=chain_id,
            network_revision=network_revision,
        )
        self._peer_states: dict[str, ReplicationState] = {}
        self._message_handlers: dict[str, Callable] = {}
        self._object_handlers: dict[str, list[Callable]] = {}
        self._outbox: list[dict] = []
        self._callbacks: list[Callable] = []
        self._maximum_inventory_object_ids = maximum_inventory_object_ids
        self._require_authenticated_peers = require_authenticated_peers
        self._peer_authenticator = peer_authenticator or (
            PeerAuthenticator() if require_authenticated_peers else None
        )

    @property
    def store(self) -> ImmutableObjectStore:
        return self._store

    @property
    def engine(self) -> ReplicationEngine:
        return self._engine

    @property
    def sync_controller(self) -> SyncController:
        return self._sync

    @property
    def channel_manager(self) -> RegistryChannelManager:
        return self._channel_manager

    @property
    def requires_authenticated_peers(self) -> bool:
        """Whether replication traffic is gated by a signed peer handshake."""
        return self._require_authenticated_peers

    # -- handler / callback registration ---------------------------------

    def register_handler(
        self,
        message_type: str,
        handler: Callable,
    ) -> None:
        """Register a handler for a registry message type."""
        self._message_handlers[message_type] = handler

    def register_callback(self, callback: Callable) -> None:
        """Register a callback for replication events."""
        self._callbacks.append(callback)

    def register_object_handler(self, object_type: str, handler: Callable) -> None:
        """Run a local projection after a verified object is stored.

        ``*`` registers a projection for every object type. Deployment uses it
        to durably project verified replicated envelopes into RegistryService.
        """
        if not object_type:
            raise ValueError("object_type is required")
        handlers = self._object_handlers.setdefault(object_type, [])
        if handler not in handlers:
            handlers.append(handler)

    def register_peer_identity(self, *, peer_id: str, public_key: str) -> None:
        """Bind a Registry peer identifier to its expected Ed25519 public key."""
        if self._peer_authenticator is None:
            self._peer_authenticator = PeerAuthenticator()
        self._peer_authenticator.register_key(peer_id, public_key)

    def authenticate_peer(
        self,
        *,
        peer_id: str,
        claimed_public_key: str,
        signature: str,
        nonce: str,
        timestamp: float,
    ) -> bool:
        """Authorize a peer only after a fresh signed Registry handshake."""
        if self._peer_authenticator is None:
            return False
        if not self._peer_authenticator.authenticate(
            peer_id=peer_id,
            claimed_public_key=claimed_public_key,
            signature=signature,
            nonce=nonce,
            timestamp=timestamp,
        ):
            state = self.get_or_create_peer_state(peer_id)
            state.error = "peer_authentication_failed"
            return False
        return self.on_peer_connected(peer_id)

    def revoke_peer_authentication(self, peer_id: str) -> None:
        """Drop an authenticated connection after key rotation or transport loss."""
        if self._peer_authenticator is not None:
            self._peer_authenticator.revoke(peer_id)
        self.on_peer_disconnected(peer_id)

    def _emit_event(self, event_type: str, **kwargs: Any) -> None:
        """Emit a replication event to all callbacks."""
        for cb in self._callbacks:
            try:
                cb(event_type, **kwargs)
            except Exception:
                pass

    # -- peer state management -------------------------------------------

    def get_or_create_peer_state(self, peer_id: str) -> ReplicationState:
        """Get or create replication state for a peer."""
        if peer_id not in self._peer_states:
            self._peer_states[peer_id] = ReplicationState(peer_id=peer_id)
        return self._peer_states[peer_id]

    def list_peer_states(self) -> list[ReplicationState]:
        """Return a stable, read-only view of observed peer replication state."""
        return [
            self._peer_states[peer_id].model_copy(deep=True)
            for peer_id in sorted(self._peer_states)
        ]

    def on_peer_connected(self, peer_id: str) -> bool:
        """Handle peer connection event."""
        state = self.get_or_create_peer_state(peer_id)
        if not self._peer_is_authorized(peer_id):
            state.connected = False
            state.error = "peer_authentication_required"
            self._emit_event("peer_connection_rejected", peer_id=peer_id)
            return False
        state.connected = True
        state.error = None
        state.last_activity_at = time.time()
        self._channel_manager.authorize_peer(
            "registry:replication", peer_id
        )
        self._emit_event("peer_connected", peer_id=peer_id)
        return True

    def on_peer_disconnected(self, peer_id: str) -> None:
        """Handle peer disconnection event."""
        state = self.get_or_create_peer_state(peer_id)
        state.connected = False
        self._emit_event("peer_disconnected", peer_id=peer_id)

    def _peer_is_authorized(self, peer_id: str) -> bool:
        return not self._require_authenticated_peers or (
            self._peer_authenticator is not None
            and self._peer_authenticator.is_authenticated(peer_id)
        )

    def _reject_unauthenticated_peer(self, peer_id: str) -> bool:
        if self._peer_is_authorized(peer_id):
            return False
        state = self.get_or_create_peer_state(peer_id)
        state.error = "peer_authentication_required"
        self._emit_event("peer_message_rejected", peer_id=peer_id)
        return True

    # -- inventory -------------------------------------------------------

    def build_inventory_request(
        self,
        peer_id: str,
        *,
        object_types: list[str] | None = None,
        epoch_range: tuple[int, int] = (0, 0),
    ) -> dict:
        """Build an inventory request message for a peer."""
        if self._reject_unauthenticated_peer(peer_id):
            raise ValueError("Registry peer authentication is required")
        state = self.get_or_create_peer_state(peer_id)
        state.last_activity_at = time.time()

        msg = self._builder.build_inventory_request(
            destination_node_id=peer_id,
            object_types=object_types,
            epoch_range=epoch_range,
        )
        self._channel_manager.enqueue_message(
            channel_id="registry:replication",
            message=msg,
            source_peer=self._node_id,
        )
        self._outbox.append(msg)
        return msg

    def handle_inventory_request(
        self,
        *,
        peer_id: str,
        message: dict,
    ) -> dict | None:
        """Handle an incoming inventory request."""
        state = self.get_or_create_peer_state(peer_id)
        state.last_activity_at = time.time()

        stats = self._store.stats()
        request_payload = message.get("payload", {}).get("registry_payload", {})
        requested_types = set(request_payload.get("requested_object_types") or [])
        object_ids = [
            object_id
            for object_id in self._store.all_ids()
            if not requested_types
            or (
                (envelope := self._store.get(object_id)) is not None
                and envelope.object_type in requested_types
            )
        ]
        inventory_truncated = len(object_ids) > self._maximum_inventory_object_ids
        object_ids = object_ids[: self._maximum_inventory_object_ids]

        # Build bloom filter
        bloom = BloomFilter(
            estimated_elements=max(1, stats.total_objects),
            false_positive_rate=0.01,
        )
        for oid in self._store.all_ids():
            bloom.add(oid)

        response = InventoryResponsePayload(
            source_node_id=self._node_id,
            destination_node_id=peer_id,
            correlation_id=message.get("payload", {}).get(
                "registry_payload", {}
            ).get("correlation_id", ""),
            object_count=stats.total_objects,
            object_types=dict(stats.objects_by_type),
            earliest_epoch=stats.earliest_epoch or 0,
            latest_epoch=stats.latest_epoch or 0,
            bloom_filter_data=bloom.serialize(),
            inventory_root_hash=hashlib.sha256(
                json.dumps(
                    sorted(self._store.all_ids()),
                    sort_keys=True,
                ).encode()
            ).hexdigest(),
            object_ids=object_ids,
            inventory_truncated=inventory_truncated,
        )

        msg = self._builder.build(response, destination_node_id=peer_id)
        self._outbox.append(msg)
        return msg

    def handle_inventory_response(
        self,
        *,
        peer_id: str,
        inventory: dict,
    ) -> dict | None:
        """Request verified objects advertised by a peer's bounded inventory."""
        state = self.get_or_create_peer_state(peer_id)
        try:
            payload = InventoryResponsePayload.model_validate(inventory)
        except ValueError:
            state.error = "inventory_response_invalid"
            return None
        if payload.source_node_id and payload.source_node_id != peer_id:
            state.error = "inventory_source_mismatch"
            return None
        if len(payload.object_ids) > self._maximum_inventory_object_ids:
            state.error = "inventory_object_ids_exceeded"
            return None
        object_ids = list(dict.fromkeys(payload.object_ids))
        if len(object_ids) != len(payload.object_ids) or any(not object_id for object_id in object_ids):
            state.error = "inventory_object_ids_invalid"
            return None
        missing_ids = [object_id for object_id in object_ids if not self._store.has(object_id)]
        state.inventory_exchanged = True
        state.objects_pending = len(missing_ids)
        self._emit_event(
            "inventory_received",
            peer_id=peer_id,
            object_count=payload.object_count,
            advertised_object_count=len(object_ids),
            inventory_truncated=payload.inventory_truncated,
        )
        if not missing_ids:
            return None
        return self.build_object_request(peer_id, missing_ids)

    # -- object requests -------------------------------------------------

    def build_object_request(
        self,
        peer_id: str,
        object_ids: list[str],
        *,
        include_payload: bool = True,
    ) -> dict:
        """Build an object request for specific objects."""
        if self._reject_unauthenticated_peer(peer_id):
            raise ValueError("Registry peer authentication is required")
        if len(object_ids) > self._maximum_inventory_object_ids:
            raise ValueError("object request exceeds the configured object limit")
        state = self.get_or_create_peer_state(peer_id)
        state.last_activity_at = time.time()
        state.objects_pending = len(object_ids)

        msg = self._builder.build_object_request(
            destination_node_id=peer_id,
            object_ids=object_ids,
            include_payload=include_payload,
        )
        self._channel_manager.enqueue_message(
            channel_id="registry:replication",
            message=msg,
            source_peer=self._node_id,
        )
        self._outbox.append(msg)
        return msg

    def handle_object_request(
        self,
        *,
        peer_id: str,
        object_ids: list[str],
        include_payload: bool = True,
    ) -> dict | None:
        """Handle an incoming object request."""
        state = self.get_or_create_peer_state(peer_id)
        state.last_activity_at = time.time()
        if len(object_ids) > self._maximum_inventory_object_ids:
            state.error = "object_request_limit_exceeded"
            return None

        delivered = []
        missing = []

        for oid in object_ids:
            obj = self._store.get(oid)
            if obj:
                delivered.append(obj.model_dump())
            else:
                missing.append(oid)

        response = ObjectResponsePayload(
            source_node_id=self._node_id,
            destination_node_id=peer_id,
            objects=delivered,
            missing_ids=missing,
            total_requested=len(object_ids),
            total_delivered=len(delivered),
        )

        msg = self._builder.build(response, destination_node_id=peer_id)
        self._outbox.append(msg)

        state.objects_transferred += len(delivered)
        state.objects_pending = len(missing)

        return msg

    def handle_object_response(
        self,
        *,
        peer_id: str,
        response: dict,
    ) -> dict:
        """Validate and store received objects before applying local projections."""
        state = self.get_or_create_peer_state(peer_id)
        result = {"stored": 0, "duplicates": 0, "invalid": 0, "handler_errors": 0}
        try:
            payload = ObjectResponsePayload.model_validate(response)
        except ValueError:
            state.error = "object_response_invalid"
            result["invalid"] = 1
            return result
        if payload.source_node_id and payload.source_node_id != peer_id:
            state.error = "object_response_source_mismatch"
            result["invalid"] = len(payload.objects)
            return result
        if len(payload.objects) > self._maximum_inventory_object_ids:
            state.error = "object_response_limit_exceeded"
            result["invalid"] = len(payload.objects)
            return result
        for raw_object in payload.objects:
            try:
                envelope = RegistryObjectEnvelope.model_validate(raw_object)
                if not envelope.verify_integrity():
                    raise ValueError("envelope integrity check failed")
                existing = self._store.get(envelope.object_id)
                if existing is not None:
                    if existing != envelope:
                        raise ValueError("object identity conflicts with local object")
                    result["duplicates"] += 1
                    continue
                if not self._store.put(envelope):
                    raise ValueError("object storage rejected envelope")
            except (TypeError, ValueError):
                result["invalid"] += 1
                continue
            result["stored"] += 1
            state.objects_transferred += 1
            state.bytes_transferred += envelope.content_size
            handlers = [
                *self._object_handlers.get(envelope.object_type, []),
                *self._object_handlers.get("*", []),
            ]
            for handler in handlers:
                try:
                    handler(peer_id, envelope)
                except Exception:
                    result["handler_errors"] += 1
            self._emit_event(
                "object_received",
                peer_id=peer_id,
                object_id=envelope.object_id,
                object_type=envelope.object_type,
            )
        state.objects_pending = max(0, state.objects_pending - result["stored"])
        if result["invalid"]:
            state.error = "object_response_contains_invalid_objects"
        elif result["handler_errors"]:
            state.error = "object_response_handler_failed"
        return result

    # -- announcements ---------------------------------------------------

    def build_announcement(
        self,
        *,
        object_id: str,
        object_type: str,
        content_hash: str,
        created_epoch: int,
        content_size: int,
    ) -> dict:
        """Build an announcement for a new object."""
        msg = self._builder.build_announcement(
            object_id=object_id,
            object_type=object_type,
            content_hash=content_hash,
            created_epoch=created_epoch,
            content_size=content_size,
        )
        self._outbox.append(msg)
        return msg

    def handle_announcement(
        self,
        *,
        peer_id: str,
        announcement: dict,
    ) -> None:
        """Handle an incoming object announcement."""
        state = self.get_or_create_peer_state(peer_id)
        state.last_activity_at = time.time()

        obj_id = announcement.get("object_id", "")

        # If we don't have this object, request it
        if not self._store.has(obj_id):
            self.build_object_request(peer_id, [obj_id])

        self._emit_event(
            "announcement_received",
            peer_id=peer_id,
            object_id=obj_id,
        )

    # -- outbox ----------------------------------------------------------

    def get_outbox(self) -> list[dict]:
        """Get pending messages from the outbox."""
        return list(self._outbox)

    def clear_outbox(self) -> int:
        """Clear the outbox and return message count."""
        count = len(self._outbox)
        self._outbox.clear()
        return count

    # -- peer queries ----------------------------------------------------

    def get_peer_state(self, peer_id: str) -> ReplicationState | None:
        return self._peer_states.get(peer_id)

    def get_all_peer_states(self) -> list[ReplicationState]:
        return list(self._peer_states.values())

    def get_connected_peers(self) -> list[str]:
        return [
            pid for pid, s in self._peer_states.items()
            if s.connected
        ]

    # -- message processing ----------------------------------------------

    def process_incoming_message(
        self,
        *,
        peer_id: str,
        message: dict,
    ) -> dict | None:
        """
        Process an incoming registry message and return a response if needed.
        """
        if self._reject_unauthenticated_peer(peer_id):
            return None
        payload_data = message.get("payload", {})
        registry_payload = payload_data.get("registry_payload", {})
        msg_type = registry_payload.get("registry_message_type", "")

        state = self.get_or_create_peer_state(peer_id)
        state.last_activity_at = time.time()

        if msg_type == RegistryMessageType.INVENTORY_REQUEST:
            return self.handle_inventory_request(peer_id=peer_id, message=message)

        elif msg_type == RegistryMessageType.OBJECT_REQUEST:
            obj_ids = registry_payload.get("object_ids", [])
            include = registry_payload.get("include_payload", True)
            return self.handle_object_request(
                peer_id=peer_id,
                object_ids=obj_ids,
                include_payload=include,
            )

        elif msg_type == RegistryMessageType.INVENTORY_RESPONSE:
            return self.handle_inventory_response(peer_id=peer_id, inventory=registry_payload)

        elif msg_type == RegistryMessageType.OBJECT_RESPONSE:
            self.handle_object_response(peer_id=peer_id, response=registry_payload)
            return None

        elif msg_type == RegistryMessageType.ANNOUNCEMENT:
            self.handle_announcement(peer_id=peer_id, announcement=registry_payload)
            return None

        elif msg_type == RegistryMessageType.SYNC_STATUS:
            self._emit_event(
                "sync_status_received",
                peer_id=peer_id,
                status=registry_payload,
            )
            return None

        # For unknown types, try registered handler
        handler = self._message_handlers.get(msg_type)
        if handler:
            return handler(peer_id, message)

        return None

    # -- sync -----------------------------------------------------------

    def start_sync(
        self,
        *,
        peer_id: str,
        target_epoch: int,
        sync_mode: str = "initial",
    ) -> None:
        """Start synchronization with a peer."""
        if not self.on_peer_connected(peer_id):
            return

        mode_map = {
            "initial": SyncMode.INITIAL,
            "catch_up": SyncMode.CATCH_UP,
            "live": SyncMode.LIVE,
            "repair": SyncMode.REPAIR,
        }

        mode = mode_map.get(sync_mode, SyncMode.INITIAL)

        if mode == SyncMode.INITIAL:
            self._sync.start_initial_sync(
                peer_id=peer_id,
                target_epoch=target_epoch,
            )
        elif mode == SyncMode.CATCH_UP:
            self._sync.start_catch_up_sync(
                peer_id=peer_id,
                from_epoch=0,
                target_epoch=target_epoch,
            )
        elif mode == SyncMode.LIVE:
            self._sync.start_live_sync(peer_id=peer_id)

        # Send initial inventory request
        self.build_inventory_request(peer_id)

        self._emit_event(
            "sync_started",
            peer_id=peer_id,
            mode=sync_mode,
            target_epoch=target_epoch,
        )

    # -- stats -----------------------------------------------------------

    def get_replication_stats(self) -> dict[str, Any]:
        """Get replication statistics."""
        return {
            "node_id": self._node_id,
            "store_objects": self._store.stats().total_objects,
            "connected_peers": len(self.get_connected_peers()),
            "total_peers": len(self._peer_states),
            "outbox_size": len(self._outbox),
            "active_transfers": self._engine.active_transfers,
        }
