"""Registry Replication Controller (M9-S3).

High-level controller that coordinates inventory exchange, object retrieval,
sync status tracking, and announcement broadcasting across the registry
replication network transport.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from .channel import RegistryChannelManager
from .failure import (
    NonResponseConfirmationEngine,
    RegistryFailureReport,
    RegistryNonResponseObservation,
    RegistryRequestEvidence,
)
from .inventory import BloomFilter
from .manifest import ManifestObjectEntry, RegistryInventoryManifest
from .messages import (
    InventoryResponsePayload,
    ObjectResponsePayload,
    RegistryMessageBuilder,
    RegistryMessageType,
)
from .object_envelope import RegistryObjectEnvelope
from .peer import PeerAuthenticator
from .proof import (
    ProofOfRegistryEngine,
    RegistryChallenge,
    RegistryChallengeResponse,
    challenge_signing_bytes,
    verify_ed25519_signature,
)
from .repair import (
    MultiPeerRepairPlan,
    MultiPeerRepairResult,
    RegistryRepairEngine,
    RegistryRepairPlan,
)
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
    remote_inventory_root: str | None = None
    remote_inventory_manifest_id: str | None = None
    repair_plan_id: str | None = None
    last_repair_status: str | None = None
    last_proof_challenge_id: str | None = None
    last_proof_status: str | None = None
    multi_peer_repair_plan_id: str | None = None
    last_failure_report_id: str | None = None
    last_failure_status: str | None = None


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
        registry_generation: int = 1,
        retention_policy_hash: str = "registry-replicator-default",
        proof_signer: Callable[[bytes], str] | None = None,
        failure_signer: Callable[[bytes], str] | None = None,
    ):
        if maximum_inventory_object_ids < 1:
            raise ValueError("maximum_inventory_object_ids must be at least one")
        self._node_id = node_id
        self._registry_generation = int(registry_generation)
        self._retention_policy_hash = retention_policy_hash
        self._store = store or ImmutableObjectStore()
        self._engine = ReplicationEngine(self._store)
        self._repair = RegistryRepairEngine(self._store)
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
        self._peer_public_keys: dict[str, str] = {}
        self._proof_signer = proof_signer
        self._failure_signer = failure_signer or proof_signer
        self._peer_inventory_manifests: dict[str, RegistryInventoryManifest] = {}
        self._proof_challenges: dict[str, RegistryChallenge] = {}
        self._multi_peer_repair_plans: dict[str, MultiPeerRepairPlan] = {}
        self._request_evidence: dict[str, RegistryRequestEvidence] = {}
        self._non_response_observations: dict[str, list[RegistryNonResponseObservation]] = {}
        self._failure_reports: dict[str, RegistryFailureReport] = {}
        self._proof = ProofOfRegistryEngine(
            registry_id=node_id,
            store=self._store,
            manifest_provider=self.build_inventory_manifest,
            signer=proof_signer,
        )
        self._failure = NonResponseConfirmationEngine(
            registry_id=node_id,
            signer=self._failure_signer,
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
        self._peer_public_keys[peer_id] = public_key

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

    def build_inventory_manifest(
        self,
        *,
        generated_at_epoch: int | None = None,
        object_ids: list[str] | None = None,
    ) -> RegistryInventoryManifest:
        """Build the deterministic payload-free inventory commitment."""
        selected_ids = object_ids or self._store.all_ids()
        objects = [
            self._store.get(object_id, include_expired=True)
            for object_id in selected_ids
        ]
        envelopes = [object_value for object_value in objects if object_value is not None]
        observed_epochs = [
            envelope.created_epoch
            for envelope in envelopes
            if envelope.created_epoch is not None
        ]
        return RegistryInventoryManifest.create(
            registry_service_id=self._node_id,
            generated_at_epoch=(
                int(generated_at_epoch)
                if generated_at_epoch is not None
                else max(observed_epochs, default=0)
            ),
            generation=self._registry_generation,
            retention_policy_hash=self._retention_policy_hash,
            objects=[ManifestObjectEntry.from_object(envelope) for envelope in envelopes],
        )

    def build_repair_plan(
        self,
        *,
        peer_id: str,
        mode: str = "catch_up",
    ) -> RegistryRepairPlan:
        """Compare the last remote manifest with local state."""
        remote = self._peer_inventory_manifests.get(peer_id)
        if remote is None:
            raise ValueError("peer inventory manifest is not available")
        plan = self._repair.build_plan(
            peer_id=peer_id,
            local_manifest=self.build_inventory_manifest(),
            remote_manifest=remote,
            mode=mode,
        )
        state = self.get_or_create_peer_state(peer_id)
        state.repair_plan_id = plan.plan_id
        state.last_repair_status = "planned"
        return plan

    def request_repair(
        self,
        *,
        peer_id: str,
        mode: str = "catch_up",
        batch_size: int | None = None,
    ) -> dict | None:
        """Request the next bounded missing-object batch from a peer."""
        plan = self.build_repair_plan(peer_id=peer_id, mode=mode)
        limit = self._maximum_inventory_object_ids if batch_size is None else int(batch_size)
        if limit < 1 or limit > self._maximum_inventory_object_ids:
            raise ValueError("repair batch size exceeds the configured object limit")
        if not plan.missing_object_ids:
            self.get_or_create_peer_state(peer_id).last_repair_status = "complete"
            return None
        return self.build_object_request(
            peer_id,
            plan.missing_object_ids[:limit],
            repair_plan_id=plan.plan_id,
            expected_inventory_root=plan.remote_inventory_root,
        )

    def build_multi_peer_repair_plan(
        self,
        *,
        peer_ids: list[str] | None = None,
        minimum_independent_sources: int = 2,
        known_control_groups: dict[str, str] | None = None,
        peer_priorities: dict[str, int] | None = None,
        mode: str = "multi_peer_repair",
    ) -> MultiPeerRepairPlan:
        """Build a quorum-bound repair plan from verified peer manifests."""
        selected_peers = sorted(peer_ids or self._peer_inventory_manifests)
        manifests = {
            peer_id: self._peer_inventory_manifests[peer_id]
            for peer_id in selected_peers
            if peer_id in self._peer_inventory_manifests
        }
        if len(manifests) != len(selected_peers):
            raise ValueError("one or more peer inventory manifests are unavailable")
        plan = self._repair.build_multi_peer_plan(
            local_manifest=self.build_inventory_manifest(),
            peer_manifests=manifests,
            minimum_independent_sources=minimum_independent_sources,
            known_control_groups=known_control_groups,
            peer_priorities=peer_priorities,
            mode=mode,
        )
        self._multi_peer_repair_plans[plan.plan_id] = plan
        for peer_id in plan.peer_ids:
            state = self.get_or_create_peer_state(peer_id)
            state.multi_peer_repair_plan_id = plan.plan_id
            state.last_repair_status = "quorum_planned"
        return plan

    def request_multi_peer_repair(
        self,
        *,
        plan: MultiPeerRepairPlan,
        batch_size: int | None = None,
    ) -> list[dict]:
        """Request each source's bounded portion of a quorum repair plan."""
        self._multi_peer_repair_plans[plan.plan_id] = plan
        limit = self._maximum_inventory_object_ids if batch_size is None else int(batch_size)
        if limit < 1 or limit > self._maximum_inventory_object_ids:
            raise ValueError("repair batch size exceeds the configured object limit")
        messages: list[dict] = []
        for peer_id in sorted(set(plan.source_by_object.values())):
            object_ids = [
                object_id
                for object_id in plan.target_object_ids
                if plan.source_by_object.get(object_id) == peer_id
            ][:limit]
            if not object_ids:
                continue
            messages.append(
                self.build_object_request(
                    peer_id,
                    object_ids,
                    repair_plan_id=plan.plan_id,
                    expected_inventory_root=plan.source_inventory_roots[peer_id],
                )
            )
        return messages

    def apply_multi_peer_repair_batch(
        self,
        *,
        plan: MultiPeerRepairPlan,
        source_peer_id: str,
        envelopes: list[RegistryObjectEnvelope],
    ) -> MultiPeerRepairResult:
        """Verify and store a source-bound quorum repair batch."""
        remote_manifest = self._peer_inventory_manifests.get(source_peer_id)
        if remote_manifest is None:
            raise ValueError("source peer inventory manifest is unavailable")
        result = self._repair.apply_multi_peer_batch(
            plan=plan,
            source_peer_id=source_peer_id,
            remote_manifest=remote_manifest,
            envelopes=envelopes,
        )
        state = self.get_or_create_peer_state(source_peer_id)
        state.last_repair_status = "complete" if result.completed else "in_progress"
        state.objects_pending = max(
            0,
            len(plan.target_object_ids)
            - len(result.accepted_object_ids)
            - len(result.duplicate_object_ids),
        )
        return result

    def issue_proof_challenge(
        self,
        *,
        peer_id: str,
        target_segment_id: str | None = None,
        challenge_type: str = "completeness",
        response_timeout_seconds: float = 300.0,
        challenge_nonce: str | None = None,
    ) -> RegistryChallenge:
        """Issue a deterministic Proof of Registry challenge to a peer."""
        if self._reject_unauthenticated_peer(peer_id):
            raise ValueError("Registry peer authentication is required")
        remote = self._peer_inventory_manifests.get(peer_id)
        if remote is None or not remote.verify():
            raise ValueError("peer inventory manifest is not available")
        challenge = self._proof.create_challenge(
            target_registry_id=peer_id,
            inventory_root=remote.inventory_root.root_hash,
            challenger_id=self._node_id,
            target_segment_id=target_segment_id,
            challenge_type=challenge_type,
            response_timeout_seconds=response_timeout_seconds,
            challenge_nonce=challenge_nonce,
        )
        if self._proof_signer is not None:
            signature = self._proof_signer(challenge_signing_bytes(challenge))
            if not isinstance(signature, str) or not signature.startswith("ed25519:"):
                raise ValueError("Registry proof signer must return an ed25519 signature")
            challenge = challenge.model_copy(update={"challenger_signature": signature})
        request_evidence = self._failure.create_request_evidence(challenge=challenge)
        self._request_evidence[challenge.challenge_id] = request_evidence
        self._proof_challenges[challenge.challenge_id] = challenge
        state = self.get_or_create_peer_state(peer_id)
        state.last_proof_challenge_id = challenge.challenge_id
        state.last_proof_status = "issued"
        message = self._builder.build_challenge(
            destination_node_id=peer_id,
            challenge=challenge.model_dump(mode="json"),
        )
        self._outbox.append(message)
        return challenge

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

        request_payload = message.get("payload", {}).get("registry_payload", {})
        requested_types = set(request_payload.get("requested_object_types") or [])
        epoch_range = request_payload.get("epoch_range") or (0, 0)
        start_epoch, end_epoch = (int(epoch_range[0]), int(epoch_range[1]))
        selected_objects = []
        for object_id in self._store.all_ids():
            envelope = self._store.get(object_id)
            if envelope is None:
                continue
            if requested_types and envelope.object_type not in requested_types:
                continue
            if (start_epoch or end_epoch) and envelope.created_epoch is not None:
                if start_epoch and envelope.created_epoch < start_epoch:
                    continue
                if end_epoch and envelope.created_epoch > end_epoch:
                    continue
            selected_objects.append(envelope)
        object_ids = [envelope.object_id for envelope in selected_objects]
        inventory_truncated = len(object_ids) > self._maximum_inventory_object_ids
        object_ids = object_ids[: self._maximum_inventory_object_ids]

        # Build bloom filter
        bloom = BloomFilter(
            estimated_elements=max(1, len(selected_objects)),
            false_positive_rate=0.01,
        )
        for oid in object_ids:
            bloom.add(oid)

        manifest = self.build_inventory_manifest(object_ids=[obj.object_id for obj in selected_objects])
        object_types: dict[str, int] = {}
        epochs = []
        for envelope in selected_objects:
            object_types[envelope.object_type] = object_types.get(envelope.object_type, 0) + 1
            if envelope.created_epoch is not None:
                epochs.append(envelope.created_epoch)

        response = InventoryResponsePayload(
            source_node_id=self._node_id,
            destination_node_id=peer_id,
            correlation_id=message.get("payload", {}).get(
                "registry_payload", {}
            ).get("correlation_id", ""),
            object_count=len(selected_objects),
            object_types=object_types,
            earliest_epoch=min(epochs, default=0),
            latest_epoch=max(epochs, default=0),
            bloom_filter_data=bloom.serialize(),
            inventory_root_hash=manifest.inventory_root.root_hash,
            inventory_manifest=manifest.model_dump(mode="json"),
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
        remote_manifest = None
        if payload.inventory_manifest is not None:
            try:
                remote_manifest = RegistryInventoryManifest.model_validate(
                    payload.inventory_manifest
                )
                if not remote_manifest.verify():
                    raise ValueError("remote inventory manifest is invalid")
                if remote_manifest.registry_service_id != peer_id:
                    raise ValueError("remote inventory manifest source mismatch")
                if remote_manifest.inventory_root.root_hash != payload.inventory_root_hash:
                    raise ValueError("remote inventory root mismatch")
            except (TypeError, ValueError):
                state.error = "inventory_manifest_invalid"
                return None
            self._peer_inventory_manifests[peer_id] = remote_manifest
            state.remote_inventory_root = remote_manifest.inventory_root.root_hash
            state.remote_inventory_manifest_id = remote_manifest.manifest_id
            try:
                plan = self._repair.build_plan(
                    peer_id=peer_id,
                    local_manifest=self.build_inventory_manifest(),
                    remote_manifest=remote_manifest,
                    mode="catch_up",
                )
                state.repair_plan_id = plan.plan_id
                state.last_repair_status = "planned"
                missing_ids = plan.missing_object_ids
            except ValueError:
                state.error = "repair_plan_invalid"
                return None
        state.inventory_exchanged = True
        state.objects_pending = len(missing_ids)
        self._emit_event(
            "inventory_received",
            peer_id=peer_id,
            object_count=payload.object_count,
            advertised_object_count=len(object_ids),
            inventory_truncated=payload.inventory_truncated,
            inventory_root_hash=payload.inventory_root_hash,
        )
        if not missing_ids:
            state.last_repair_status = "complete"
            return None
        return self.build_object_request(
            peer_id,
            missing_ids[: self._maximum_inventory_object_ids],
        )

    # -- object requests -------------------------------------------------

    def build_object_request(
        self,
        peer_id: str,
        object_ids: list[str],
        *,
        include_payload: bool = True,
        repair_plan_id: str = "",
        expected_inventory_root: str = "",
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
            repair_plan_id=repair_plan_id,
            expected_inventory_root=expected_inventory_root,
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
        repair_plan_id: str = "",
        expected_inventory_root: str = "",
    ) -> dict | None:
        """Handle an incoming object request."""
        state = self.get_or_create_peer_state(peer_id)
        state.last_activity_at = time.time()
        if len(object_ids) > self._maximum_inventory_object_ids:
            state.error = "object_request_limit_exceeded"
            return None
        if expected_inventory_root:
            current_root = self.build_inventory_manifest().inventory_root.root_hash
            if current_root != expected_inventory_root:
                state.error = "object_request_inventory_root_stale"
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
            repair_plan_id=repair_plan_id,
            source_inventory_root=expected_inventory_root,
        )

        msg = self._builder.build(response, destination_node_id=peer_id)
        self._outbox.append(msg)

        state.objects_transferred += len(delivered)
        state.objects_pending = len(missing)

        return msg

    def _project_received_object(
        self,
        peer_id: str,
        envelope: RegistryObjectEnvelope,
    ) -> int:
        """Run projections after an envelope has passed immutable storage."""
        handler_errors = 0
        handlers = [
            *self._object_handlers.get(envelope.object_type, []),
            *self._object_handlers.get("*", []),
        ]
        for handler in handlers:
            try:
                handler(peer_id, envelope)
            except Exception:
                handler_errors += 1
        self._emit_event(
            "object_received",
            peer_id=peer_id,
            object_id=envelope.object_id,
            object_type=envelope.object_type,
        )
        return handler_errors

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
        if payload.repair_plan_id:
            plan = self._multi_peer_repair_plans.get(payload.repair_plan_id)
            if plan is None:
                state.error = "multi_peer_repair_plan_not_found"
                result["invalid"] = len(payload.objects)
                return result
            if payload.source_inventory_root != plan.source_inventory_roots.get(peer_id):
                state.error = "multi_peer_repair_source_root_mismatch"
                result["invalid"] = len(payload.objects)
                return result
            try:
                envelopes = [RegistryObjectEnvelope.model_validate(raw) for raw in payload.objects]
                multi_result = self.apply_multi_peer_repair_batch(
                    plan=plan,
                    source_peer_id=peer_id,
                    envelopes=envelopes,
                )
            except (TypeError, ValueError):
                state.error = "multi_peer_repair_batch_invalid"
                result["invalid"] = len(payload.objects)
                return result
            result["stored"] = len(multi_result.accepted_object_ids)
            result["duplicates"] = len(multi_result.duplicate_object_ids)
            result["invalid"] = len(multi_result.rejected_object_ids)
            result["handler_errors"] = sum(
                self._project_received_object(
                    peer_id,
                    self._store.get(object_id, include_expired=True),
                )
                for object_id in multi_result.accepted_object_ids
                if self._store.get(object_id, include_expired=True) is not None
            )
            if multi_result.rejected_object_ids:
                state.error = "multi_peer_repair_batch_rejected"
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
            result["handler_errors"] += self._project_received_object(peer_id, envelope)
        state.objects_pending = max(0, state.objects_pending - result["stored"])
        if result["invalid"]:
            state.error = "object_response_contains_invalid_objects"
        elif result["handler_errors"]:
            state.error = "object_response_handler_failed"
        elif peer_id in self._peer_inventory_manifests:
            # Continue a bounded catch-up batch until the manifest-derived
            # plan is empty. Existing object requests remain idempotent.
            try:
                plan = self.build_repair_plan(peer_id=peer_id, mode="catch_up")
                remaining = [
                    object_id
                    for object_id in plan.missing_object_ids
                    if not self._store.has(object_id)
                ]
                state.objects_pending = len(remaining)
                if remaining:
                    state.last_repair_status = "in_progress"
                    self.build_object_request(
                        peer_id,
                        remaining[: self._maximum_inventory_object_ids],
                    )
                else:
                    state.last_repair_status = "complete"
            except (TypeError, ValueError):
                state.error = "repair_plan_invalid"
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

    def get_outbox(self, peer_id: str | None = None) -> list[dict]:
        """Get pending messages, optionally scoped to one destination peer."""
        if peer_id is None:
            return list(self._outbox)
        return [
            message
            for message in self._outbox
            if self._message_destination(message) == peer_id
        ]

    def clear_outbox(self, peer_id: str | None = None) -> int:
        """Remove pending messages, optionally scoped to one destination peer."""
        if peer_id is None:
            count = len(self._outbox)
            self._outbox.clear()
            return count

        pending = []
        cleared = 0
        for message in self._outbox:
            if self._message_destination(message) == peer_id:
                cleared += 1
            else:
                pending.append(message)
        self._outbox = pending
        return cleared

    @staticmethod
    def _message_destination(message: dict) -> str | None:
        destination = message.get("destination_subject")
        if not isinstance(destination, dict):
            return None
        subject_id = destination.get("subject_id")
        return subject_id if isinstance(subject_id, str) else None

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
                repair_plan_id=registry_payload.get("repair_plan_id", ""),
                expected_inventory_root=registry_payload.get("expected_inventory_root", ""),
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

        elif msg_type == RegistryMessageType.CHALLENGE:
            return self.handle_challenge(peer_id=peer_id, challenge=registry_payload)

        elif msg_type == RegistryMessageType.CHALLENGE_RESPONSE:
            self.handle_challenge_response(
                peer_id=peer_id,
                response=registry_payload,
            )
            return None

        elif msg_type == RegistryMessageType.NON_RESPONSE_OBSERVATION:
            self.handle_non_response_observation(
                peer_id=peer_id,
                observation=registry_payload.get("observation", {}),
            )
            return None

        elif msg_type == RegistryMessageType.FAILURE_REPORT:
            self.handle_failure_report(
                peer_id=peer_id,
                report=registry_payload.get("report", {}),
            )
            return None

        # For unknown types, try registered handler
        handler = self._message_handlers.get(msg_type)
        if handler:
            return handler(peer_id, message)

        return None

    def handle_challenge(
        self,
        *,
        peer_id: str,
        challenge: dict,
    ) -> dict | None:
        """Answer an authenticated peer's Proof of Registry challenge."""
        state = self.get_or_create_peer_state(peer_id)
        try:
            parsed = RegistryChallenge.model_validate(challenge)
            expected_key = self._peer_public_keys.get(peer_id)
            if parsed.challenger_signature and (
                expected_key is None
                or not verify_ed25519_signature(
                    public_key=expected_key,
                    signature=parsed.challenger_signature,
                    payload=challenge_signing_bytes(parsed),
                )
            ):
                raise ValueError("Registry challenge signature is invalid")
            response = self._proof.answer_challenge(parsed)
            message = self._builder.build_challenge_response(
                destination_node_id=peer_id,
                response=response.model_dump(mode="json"),
            )
        except (TypeError, ValueError) as error:
            state.last_proof_status = "failed"
            state.error = "proof_challenge_failed"
            self._emit_event(
                "proof_challenge_failed",
                peer_id=peer_id,
                error=str(error),
            )
            return None
        state.last_proof_challenge_id = parsed.challenge_id
        state.last_proof_status = "answered"
        self._outbox.append(message)
        self._emit_event(
            "proof_challenge_answered",
            peer_id=peer_id,
            challenge_id=parsed.challenge_id,
        )
        return message

    def handle_challenge_response(
        self,
        *,
        peer_id: str,
        response: dict,
    ) -> dict:
        """Verify a peer's Proof of Registry response."""
        state = self.get_or_create_peer_state(peer_id)
        try:
            parsed = RegistryChallengeResponse.model_validate(response)
        except (TypeError, ValueError):
            state.last_proof_status = "invalid"
            state.error = "proof_response_invalid"
            return {"valid": False, "reason": "proof_response_invalid"}
        challenge = self._proof_challenges.get(parsed.challenge_id)
        if challenge is None:
            state.last_proof_status = "unknown_challenge"
            state.error = "proof_challenge_not_found"
            return {"valid": False, "reason": "proof_challenge_not_found"}
        result = self._proof.verify_response(
            challenge=challenge,
            response=parsed,
            expected_inventory_manifest=self._peer_inventory_manifests.get(peer_id),
            expected_registry_public_key=self._peer_public_keys.get(peer_id),
            require_signature=True,
        )
        state.last_proof_status = "verified" if result.valid else "failed"
        if not result.valid:
            state.error = f"proof_verification_failed:{result.reason}"
        self._emit_event(
            "proof_challenge_verified" if result.valid else "proof_challenge_failed",
            peer_id=peer_id,
            challenge_id=parsed.challenge_id,
            result=result.model_dump(mode="json"),
        )
        return result.model_dump(mode="json")

    def create_non_response_observation(
        self,
        *,
        challenge: RegistryChallenge,
        request_evidence: RegistryRequestEvidence,
        response_received: bool = False,
        response_hash: str = "",
        transport_state: str = "no_response",
        network_condition: str = "healthy",
        observer_role: str = "independent_verifier",
        attempt_id: str | None = None,
    ) -> RegistryNonResponseObservation:
        """Create and retain a signed independent challenge observation."""
        observation = self._failure.create_observation(
            request_evidence=request_evidence,
            challenge=challenge,
            response_received=response_received,
            response_hash=response_hash,
            transport_state=transport_state,
            network_condition=network_condition,
            observer_role=observer_role,
            attempt_id=attempt_id,
        )
        self._non_response_observations.setdefault(challenge.challenge_id, []).append(observation)
        return observation

    def build_non_response_observation_message(
        self,
        *,
        destination_node_id: str,
        observation: RegistryNonResponseObservation,
    ) -> dict:
        """Build a wire message carrying one signed non-response observation."""
        message = self._builder.build_non_response_observation(
            destination_node_id=destination_node_id,
            observation=observation.model_dump(mode="json"),
        )
        self._outbox.append(message)
        return message

    def handle_non_response_observation(
        self,
        *,
        peer_id: str,
        observation: dict,
    ) -> bool:
        """Accept a structurally valid observation for later quorum review."""
        state = self.get_or_create_peer_state(peer_id)
        try:
            parsed = RegistryNonResponseObservation.model_validate(observation)
        except (TypeError, ValueError):
            state.last_failure_status = "observation_invalid"
            state.error = "non_response_observation_invalid"
            return False
        if parsed.observer_id != peer_id:
            state.last_failure_status = "observation_source_mismatch"
            state.error = "non_response_observation_source_mismatch"
            return False
        self._non_response_observations.setdefault(parsed.challenge_id, []).append(parsed)
        state.last_failure_status = "observation_received"
        self._emit_event(
            "non_response_observation_received",
            peer_id=peer_id,
            challenge_id=parsed.challenge_id,
            observation_id=parsed.observation_id,
        )
        return True

    def build_failure_report(
        self,
        *,
        challenge_id: str,
        known_control_groups: dict[str, str] | None = None,
        minimum_independent_observers: int = 2,
    ) -> RegistryFailureReport:
        """Finalize a signed failure report after independent confirmation."""
        challenge = self._proof_challenges.get(challenge_id)
        request_evidence = self._request_evidence.get(challenge_id)
        if challenge is None or request_evidence is None:
            raise ValueError("challenge evidence is not available")
        report = self._failure.build_failure_report(
            challenge=challenge,
            request_evidence=request_evidence,
            observations=self._non_response_observations.get(challenge_id, []),
            known_control_groups=known_control_groups,
            minimum_independent_observers=minimum_independent_observers,
        )
        self._failure_reports[report.report_id] = report
        state = self.get_or_create_peer_state(challenge.target_registry_id)
        state.last_failure_report_id = report.report_id
        state.last_failure_status = "confirmed_non_response"
        return report

    def build_failure_report_message(
        self,
        *,
        destination_node_id: str,
        report: RegistryFailureReport,
    ) -> dict:
        """Build a wire message carrying a signed Registry Failure Report."""
        message = self._builder.build_failure_report(
            destination_node_id=destination_node_id,
            report=report.model_dump(mode="json"),
        )
        self._outbox.append(message)
        return message

    def handle_failure_report(
        self,
        *,
        peer_id: str,
        report: dict,
        verifier_public_keys: dict[str, str] | None = None,
        known_control_groups: dict[str, str] | None = None,
        minimum_independent_observers: int = 2,
    ) -> dict:
        """Verify and retain a signed Registry Failure Report."""
        state = self.get_or_create_peer_state(peer_id)
        try:
            parsed = RegistryFailureReport.model_validate(report)
            challenge = self._proof_challenges.get(parsed.challenge_id)
            if challenge is None:
                raise ValueError("challenge evidence is not available")
            result = self._failure.verify_failure_report(
                challenge=challenge,
                report=parsed,
                verifier_public_keys=verifier_public_keys or self._peer_public_keys,
                known_control_groups=known_control_groups,
                minimum_independent_observers=minimum_independent_observers,
            )
        except (TypeError, ValueError) as error:
            state.last_failure_status = "report_invalid"
            state.error = "registry_failure_report_invalid"
            return {"valid": False, "reason": str(error)}
        state.last_failure_status = "verified" if result.valid else "rejected"
        if result.valid:
            self._failure_reports[parsed.report_id] = parsed
            state.last_failure_report_id = parsed.report_id
        else:
            state.error = f"registry_failure_report_rejected:{result.reason}"
        self._emit_event(
            "registry_failure_report_verified" if result.valid else "registry_failure_report_rejected",
            peer_id=peer_id,
            report_id=parsed.report_id,
            result=result.model_dump(mode="json"),
        )
        return result.model_dump(mode="json")

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
