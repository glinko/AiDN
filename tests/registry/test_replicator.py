"""Tests for registry/replicator — Registry Replication Controller (M9-S3)."""

from __future__ import annotations

import time
from typing import Any

from aidn_hypervisor.registry import ImmutableObjectStore, RegistryObjectEnvelope
from aidn_hypervisor.registry.messages import RegistryMessageType
from aidn_hypervisor.registry.replicator import (
    RegistryReplicator,
    ReplicationState,
)
from aidn_hypervisor.registry.sync import SyncMode

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_envelope(
    object_id: str | None = None,
    object_type: str = "test",
    payload: dict | None = None,
    created_epoch: int | None = None,
) -> RegistryObjectEnvelope:
    return RegistryObjectEnvelope.create(
        object_type=object_type,
        payload=payload or {"data": "test"},
        object_id=object_id,
        created_epoch=created_epoch,
    )


def _make_store() -> ImmutableObjectStore:
    return ImmutableObjectStore()


def _make_replicator(
    node_id: str = "node-a",
    store: ImmutableObjectStore | None = None,
) -> RegistryReplicator:
    return RegistryReplicator(
        node_id=node_id,
        store=store or _make_store(),
    )


# ---------------------------------------------------------------------------
# ReplicationState model
# ---------------------------------------------------------------------------


class TestReplicationStateModel:
    def test_default_values(self):
        state = ReplicationState(peer_id="peer-1")
        assert state.peer_id == "peer-1"
        assert state.connected is False
        assert state.inventory_exchanged is False
        assert state.objects_pending == 0
        assert state.objects_transferred == 0
        assert state.bytes_transferred == 0
        assert state.last_activity_at == 0.0
        assert state.error is None

    def test_custom_values(self):
        state = ReplicationState(
            peer_id="peer-2",
            connected=True,
            objects_pending=5,
            error="timeout",
        )
        assert state.connected is True
        assert state.objects_pending == 5
        assert state.error == "timeout"


# ---------------------------------------------------------------------------
# RegistryReplicator init / properties
# ---------------------------------------------------------------------------


class TestReplicatorInit:
    def test_replicator_init(self):
        r = _make_replicator()
        assert r._node_id == "node-a"
        assert r.store is not None
        assert r.engine is not None
        assert r.sync_controller is not None
        assert r.channel_manager is not None

    def test_replicator_properties(self):
        store = _make_store()
        r = _make_replicator(store=store)
        assert r.store is store
        assert r.engine is not None
        assert r.sync_controller is not None

    def test_replicator_store_access(self):
        """Store property returns the same store instance."""
        store = _make_store()
        r = _make_replicator(store=store)
        assert r.store is store
        assert r._store is store

    def test_custom_network_params(self):
        r = RegistryReplicator(
            node_id="node-x",
            network_id="testnet",
            chain_id="test",
            network_revision="2.0",
        )
        assert r._node_id == "node-x"
        assert r._builder._network_id == "testnet"
        assert r._builder._chain_id == "test"
        assert r._builder._network_revision == "2.0"


# ---------------------------------------------------------------------------
# Handler / callback registration
# ---------------------------------------------------------------------------


class TestHandlerRegistration:
    def test_register_handler(self):
        r = _make_replicator()
        handler_called = []

        def my_handler(peer_id, message):
            handler_called.append((peer_id, message))

        r.register_handler("custom_type", my_handler)
        assert "custom_type" in r._message_handlers

    def test_register_callback(self):
        r = _make_replicator()
        events: list[tuple] = []

        def cb(event_type, **kwargs):
            events.append((event_type, kwargs))

        r.register_callback(cb)
        assert len(r._callbacks) == 1

    def test_sync_callback_emitted(self):
        r = _make_replicator()
        events: list[tuple] = []

        def cb(event_type, **kwargs):
            events.append((event_type, kwargs))

        r.register_callback(cb)
        r.start_sync(peer_id="peer-1", target_epoch=10, sync_mode="initial")
        assert any(e[0] == "sync_started" for e in events)


# ---------------------------------------------------------------------------
# Peer state management
# ---------------------------------------------------------------------------


class TestPeerState:
    def test_get_or_create_peer_state(self):
        r = _make_replicator()
        state = r.get_or_create_peer_state("peer-1")
        assert state.peer_id == "peer-1"
        assert state in r._peer_states.values()

    def test_get_or_create_existing(self):
        r = _make_replicator()
        s1 = r.get_or_create_peer_state("peer-1")
        s2 = r.get_or_create_peer_state("peer-1")
        assert s1 is s2

    def test_on_peer_connected(self):
        r = _make_replicator()
        r.on_peer_connected("peer-1")
        state = r.get_peer_state("peer-1")
        assert state is not None
        assert state.connected is True
        assert state.last_activity_at > 0

    def test_on_peer_disconnected(self):
        r = _make_replicator()
        r.on_peer_connected("peer-1")
        r.on_peer_disconnected("peer-1")
        state = r.get_peer_state("peer-1")
        assert state is not None
        assert state.connected is False

    def test_channel_authorization_on_connect(self):
        r = _make_replicator()
        r.on_peer_connected("peer-1")
        # Peer should be authorized on the replication channel
        assert r.channel_manager.check_authorization(
            "registry:replication", "peer-1"
        ) is True

    def test_get_peer_state(self):
        r = _make_replicator()
        r.get_or_create_peer_state("peer-1")
        state = r.get_peer_state("peer-1")
        assert state is not None
        assert state.peer_id == "peer-1"

    def test_get_peer_state_missing(self):
        r = _make_replicator()
        assert r.get_peer_state("nonexistent") is None

    def test_get_connected_peers(self):
        r = _make_replicator()
        r.on_peer_connected("peer-1")
        r.on_peer_connected("peer-2")
        r.get_or_create_peer_state("peer-3")  # not connected
        connected = r.get_connected_peers()
        assert "peer-1" in connected
        assert "peer-2" in connected
        assert "peer-3" not in connected

    def test_multiple_peer_states(self):
        r = _make_replicator()
        r.on_peer_connected("peer-a")
        r.on_peer_connected("peer-b")
        r.on_peer_connected("peer-c")
        states = r.get_all_peer_states()
        assert len(states) == 3
        ids = {s.peer_id for s in states}
        assert ids == {"peer-a", "peer-b", "peer-c"}


# ---------------------------------------------------------------------------
# Inventory requests
# ---------------------------------------------------------------------------


class TestInventoryRequest:
    def test_build_inventory_request(self):
        r = _make_replicator()
        msg = r.build_inventory_request("peer-1")
        assert msg is not None
        assert msg["message_type"] == RegistryMessageType.INVENTORY_REQUEST
        assert len(r.get_outbox()) >= 1

    def test_build_inventory_request_with_types(self):
        r = _make_replicator()
        msg = r.build_inventory_request(
            "peer-1",
            object_types=["reputation_profile"],
            epoch_range=(1, 10),
        )
        reg_payload = msg["payload"]["registry_payload"]
        assert reg_payload["requested_object_types"] == ["reputation_profile"]
        assert reg_payload["epoch_range"] == (1, 10)

    def test_handle_inventory_request(self):
        store = _make_store()
        env = _make_envelope(object_id="obj-1", created_epoch=5)
        store.put(env)
        r = _make_replicator(store=store)

        response = r.handle_inventory_request(
            peer_id="peer-1",
            message={"payload": {"registry_payload": {"correlation_id": "corr-1"}}},
        )
        assert response is not None
        reg = response["payload"]["registry_payload"]
        assert reg["registry_message_type"] == RegistryMessageType.INVENTORY_RESPONSE
        assert reg["object_count"] == 1

    def test_handle_inventory_request_empty_store(self):
        r = _make_replicator()
        response = r.handle_inventory_request(
            peer_id="peer-1",
            message={"payload": {"registry_payload": {"correlation_id": ""}}},
        )
        assert response is not None
        assert response["payload"]["registry_payload"]["object_count"] == 0


# ---------------------------------------------------------------------------
# Object requests
# ---------------------------------------------------------------------------


class TestObjectRequest:
    def test_build_object_request(self):
        r = _make_replicator()
        msg = r.build_object_request("peer-1", ["obj-1", "obj-2"])
        assert msg is not None
        assert msg["message_type"] == RegistryMessageType.OBJECT_REQUEST

    def test_handle_object_request(self):
        store = _make_store()
        env = _make_envelope(object_id="obj-1")
        store.put(env)
        r = _make_replicator(store=store)

        response = r.handle_object_request(
            peer_id="peer-1",
            object_ids=["obj-1"],
        )
        assert response is not None
        reg = response["payload"]["registry_payload"]
        assert reg["total_delivered"] == 1
        assert reg["total_requested"] == 1

    def test_handle_object_request_missing(self):
        r = _make_replicator()
        response = r.handle_object_request(
            peer_id="peer-1",
            object_ids=["nonexistent"],
        )
        assert response is not None
        reg = response["payload"]["registry_payload"]
        assert reg["total_delivered"] == 0
        assert "nonexistent" in reg["missing_ids"]

    def test_handle_object_request_partial(self):
        store = _make_store()
        env = _make_envelope(object_id="obj-1")
        store.put(env)
        r = _make_replicator(store=store)

        response = r.handle_object_request(
            peer_id="peer-1",
            object_ids=["obj-1", "obj-missing"],
        )
        assert response is not None
        reg = response["payload"]["registry_payload"]
        assert reg["total_delivered"] == 1
        assert reg["total_requested"] == 2
        assert "obj-missing" in reg["missing_ids"]

    def test_inventory_response_requests_missing_objects(self):
        source_store = _make_store()
        source_store.put(_make_envelope(object_id="obj-1"))
        source = _make_replicator(node_id="node-source", store=source_store)
        target = _make_replicator(node_id="node-target")

        inventory_request = target.build_inventory_request("node-source")
        inventory_response = source.process_incoming_message(
            peer_id="node-target", message=inventory_request
        )

        object_request = target.process_incoming_message(
            peer_id="node-source", message=inventory_response
        )

        assert object_request is not None
        assert object_request["payload"]["registry_payload"]["object_ids"] == ["obj-1"]
        assert target.get_peer_state("node-source").inventory_exchanged is True

    def test_object_response_stores_verified_objects(self):
        source_store = _make_store()
        source_store.put(_make_envelope(object_id="obj-1"))
        source = _make_replicator(node_id="node-source", store=source_store)
        target = _make_replicator(node_id="node-target")

        request = target.build_object_request("node-source", ["obj-1"])
        response = source.process_incoming_message(peer_id="node-target", message=request)

        assert response is not None
        assert target.process_incoming_message(peer_id="node-source", message=response) is None
        assert target.store.has("obj-1")
        state = target.get_peer_state("node-source")
        assert state is not None
        assert state.objects_transferred == 1


# ---------------------------------------------------------------------------
# Announcements
# ---------------------------------------------------------------------------


class TestAnnouncements:
    def test_build_announcement(self):
        r = _make_replicator()
        msg = r.build_announcement(
            object_id="new-obj",
            object_type="reputation_profile",
            content_hash="abc123",
            created_epoch=10,
            content_size=100,
        )
        assert msg is not None
        assert msg["message_type"] == RegistryMessageType.ANNOUNCEMENT
        assert len(r.get_outbox()) >= 1

    def test_handle_announcement(self):
        store = _make_store()
        env = _make_envelope(object_id="announced-obj")
        store.put(env)
        r = _make_replicator(store=store)

        r.handle_announcement(
            peer_id="peer-1",
            announcement={"object_id": "announced-obj"},
        )
        # Should not trigger object request since we already have it
        outbox = r.get_outbox()
        assert all(
            m.get("message_type") != RegistryMessageType.OBJECT_REQUEST
            for m in outbox
        )

    def test_handle_announcement_requests_missing(self):
        r = _make_replicator()
        r.handle_announcement(
            peer_id="peer-1",
            announcement={"object_id": "unknown-obj"},
        )
        # Should trigger object request for missing object
        outbox = r.get_outbox()
        obj_requests = [
            m for m in outbox
            if m.get("message_type") == RegistryMessageType.OBJECT_REQUEST
        ]
        assert len(obj_requests) >= 1


# ---------------------------------------------------------------------------
# Outbox
# ---------------------------------------------------------------------------


class TestOutbox:
    def test_get_outbox(self):
        r = _make_replicator()
        assert r.get_outbox() == []

    def test_clear_outbox(self):
        r = _make_replicator()
        r.build_inventory_request("peer-1")
        count = r.clear_outbox()
        assert count >= 1
        assert r.get_outbox() == []

    def test_outbox_message_format(self):
        r = _make_replicator()
        r.build_inventory_request("peer-1")
        msgs = r.get_outbox()
        assert len(msgs) >= 1
        msg = msgs[0]
        assert "message_id" in msg
        assert "message_type" in msg
        assert "payload" in msg
        assert "registry_payload" in msg["payload"]


# ---------------------------------------------------------------------------
# Message processing
# ---------------------------------------------------------------------------


class TestProcessIncoming:
    def _make_incoming(self, msg_type: str, **extra: Any) -> dict:
        return {
            "payload": {
                "registry_payload": {
                    "registry_message_type": msg_type,
                    **extra,
                }
            }
        }

    def test_process_incoming_inventory_request(self):
        r = _make_replicator()
        msg = self._make_incoming(RegistryMessageType.INVENTORY_REQUEST)
        response = r.process_incoming_message(peer_id="peer-1", message=msg)
        assert response is not None
        assert (
            response["payload"]["registry_payload"]["registry_message_type"]
            == RegistryMessageType.INVENTORY_RESPONSE
        )

    def test_process_incoming_object_request(self):
        store = _make_store()
        env = _make_envelope(object_id="obj-1")
        store.put(env)
        r = _make_replicator(store=store)

        msg = self._make_incoming(
            RegistryMessageType.OBJECT_REQUEST,
            object_ids=["obj-1"],
            include_payload=True,
        )
        response = r.process_incoming_message(peer_id="peer-1", message=msg)
        assert response is not None
        assert (
            response["payload"]["registry_payload"]["registry_message_type"]
            == RegistryMessageType.OBJECT_RESPONSE
        )

    def test_process_incoming_announcement(self):
        r = _make_replicator()
        msg = self._make_incoming(
            RegistryMessageType.ANNOUNCEMENT,
            object_id="new-obj",
        )
        response = r.process_incoming_message(peer_id="peer-1", message=msg)
        # Announcement processing returns None
        assert response is None

    def test_process_incoming_sync_status(self):
        r = _make_replicator()
        msg = self._make_incoming(
            RegistryMessageType.SYNC_STATUS,
            sync_mode="initial",
            progress=0.5,
        )
        response = r.process_incoming_message(peer_id="peer-1", message=msg)
        assert response is None

    def test_process_incoming_unknown_type(self):
        r = _make_replicator()
        msg = self._make_incoming("unknown_type")
        response = r.process_incoming_message(peer_id="peer-1", message=msg)
        assert response is None

    def test_process_message_updates_activity(self):
        r = _make_replicator()
        r.get_or_create_peer_state("peer-1")
        state_before = r.get_peer_state("peer-1")
        time.sleep(0.01)

        msg = self._make_incoming(RegistryMessageType.SYNC_STATUS)
        r.process_incoming_message(peer_id="peer-1", message=msg)

        state_after = r.get_peer_state("peer-1")
        assert state_after.last_activity_at >= state_before.last_activity_at

    def test_process_incoming_custom_handler(self):
        r = _make_replicator()
        handler_results: list[tuple] = []

        def custom_handler(peer_id, message):
            handler_results.append((peer_id, message))
            return {"handled": True}

        r.register_handler("custom_type", custom_handler)
        msg = self._make_incoming("custom_type")
        response = r.process_incoming_message(peer_id="peer-1", message=msg)
        assert response is not None
        assert response["handled"] is True
        assert len(handler_results) == 1


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------


class TestSync:
    def test_start_sync_initial(self):
        r = _make_replicator()
        r.start_sync(peer_id="peer-1", target_epoch=10, sync_mode="initial")
        sync_state = r.sync_controller.state
        assert sync_state.mode == SyncMode.INITIAL
        assert sync_state.target_epoch == 10
        assert sync_state.peer_id == "peer-1"

    def test_start_sync_catch_up(self):
        r = _make_replicator()
        r.start_sync(peer_id="peer-1", target_epoch=20, sync_mode="catch_up")
        sync_state = r.sync_controller.state
        assert sync_state.mode == SyncMode.CATCH_UP
        assert sync_state.target_epoch == 20

    def test_start_sync_live_mode(self):
        r = _make_replicator()
        r.start_sync(peer_id="peer-1", target_epoch=0, sync_mode="live")
        sync_state = r.sync_controller.state
        assert sync_state.mode == SyncMode.LIVE

    def test_start_sync_connects_peer(self):
        r = _make_replicator()
        r.start_sync(peer_id="peer-1", target_epoch=10)
        state = r.get_peer_state("peer-1")
        assert state is not None
        assert state.connected is True

    def test_start_sync_sends_inventory_request(self):
        r = _make_replicator()
        r.start_sync(peer_id="peer-1", target_epoch=10)
        outbox = r.get_outbox()
        inv_requests = [
            m for m in outbox
            if m.get("message_type") == RegistryMessageType.INVENTORY_REQUEST
        ]
        assert len(inv_requests) >= 1


# ---------------------------------------------------------------------------
# Replication stats
# ---------------------------------------------------------------------------


class TestReplicationStats:
    def test_get_replication_stats(self):
        store = _make_store()
        env = _make_envelope(object_id="obj-1")
        store.put(env)
        r = _make_replicator(store=store)
        r.on_peer_connected("peer-1")

        stats = r.get_replication_stats()
        assert stats["node_id"] == "node-a"
        assert stats["store_objects"] == 1
        assert stats["connected_peers"] == 1
        assert stats["total_peers"] == 1
        assert "outbox_size" in stats
        assert "active_transfers" in stats

    def test_stats_empty(self):
        r = _make_replicator()
        stats = r.get_replication_stats()
        assert stats["store_objects"] == 0
        assert stats["connected_peers"] == 0
        assert stats["total_peers"] == 0
