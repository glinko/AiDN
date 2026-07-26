"""Tests for gRPC Transport Profile (M9-S4).

Covers:
- GrpcTransportConfig (defaults, custom values, TLS fields)
- GrpcConnectionState model
- GrpcRegistryTransport (lifecycle, messaging, keepalive, buffers)
- GrpcRegistryStream (bidirectional stream simulation)
- GrpcProtoRegistryMessage (serialization, deserialization, hashing)
"""

from __future__ import annotations

import time
import uuid

import pytest

from aidn_hypervisor.dispatcher.transport.abc import TransportStatus
from aidn_hypervisor.registry.grpc_transport import (
    GrpcConnectionState,
    GrpcProtoRegistryMessage,
    GrpcRegistryStream,
    GrpcRegistryTransport,
    GrpcTransportConfig,
)
from aidn_hypervisor.registry.grpc_proto_spec import PROTO_SPEC


# ─── Config tests ──────────────────────────────────────────────────────────


class TestGrpcTransportConfig:

    def test_grpc_config_defaults(self) -> None:
        """Config defaults match RFC-0042 §6."""
        cfg = GrpcTransportConfig()
        assert cfg.host == "localhost"
        assert cfg.port == 50051
        assert cfg.max_message_size_bytes == 10 * 1024 * 1024
        assert cfg.keepalive_interval_seconds == 30
        assert cfg.keepalive_timeout_seconds == 10
        assert cfg.max_concurrent_streams == 100
        assert cfg.tls_enabled is False
        assert cfg.tls_cert_path is None
        assert cfg.tls_key_path is None
        assert cfg.tls_ca_path is None

    def test_grpc_config_custom(self) -> None:
        """Custom config values are respected."""
        cfg = GrpcTransportConfig(
            host="10.0.0.1",
            port=50052,
            max_message_size_bytes=5 * 1024 * 1024,
            keepalive_interval_seconds=15,
            keepalive_timeout_seconds=5,
            max_concurrent_streams=50,
        )
        assert cfg.host == "10.0.0.1"
        assert cfg.port == 50052
        assert cfg.max_message_size_bytes == 5 * 1024 * 1024
        assert cfg.keepalive_interval_seconds == 15
        assert cfg.keepalive_timeout_seconds == 5
        assert cfg.max_concurrent_streams == 50

    def test_config_tls_fields(self) -> None:
        """TLS configuration fields."""
        cfg = GrpcTransportConfig(
            tls_enabled=True,
            tls_cert_path="/etc/ssl/cert.pem",
            tls_key_path="/etc/ssl/key.pem",
            tls_ca_path="/etc/ssl/ca.pem",
        )
        assert cfg.tls_enabled is True
        assert cfg.tls_cert_path == "/etc/ssl/cert.pem"
        assert cfg.tls_key_path == "/etc/ssl/key.pem"
        assert cfg.tls_ca_path == "/etc/ssl/ca.pem"


# ─── Connection state tests ────────────────────────────────────────────────


class TestGrpcConnectionState:

    def test_grpc_connection_state_model(self) -> None:
        """Connection state model has correct defaults."""
        state = GrpcConnectionState()
        assert isinstance(state.connection_id, str)
        assert len(state.connection_id) > 0
        assert state.peer_address == ""
        assert state.status == TransportStatus.DISCONNECTED.value
        assert state.connected_at == 0.0
        assert state.last_keepalive_at == 0.0
        assert state.messages_sent == 0
        assert state.messages_received == 0
        assert state.bytes_sent == 0
        assert state.bytes_received == 0
        assert state.error is None

    def test_connection_state_custom(self) -> None:
        """Custom connection state values."""
        state = GrpcConnectionState(
            peer_address="10.0.0.1:50051",
            status=TransportStatus.CONNECTED.value,
            connected_at=100.0,
            error="some error",
        )
        assert state.peer_address == "10.0.0.1:50051"
        assert state.status == TransportStatus.CONNECTED.value
        assert state.connected_at == 100.0
        assert state.error == "some error"


# ─── Transport lifecycle tests ─────────────────────────────────────────────


class TestGrpcTransportLifecycle:

    def test_transport_init(self) -> None:
        """Transport starts disconnected."""
        transport = GrpcRegistryTransport()
        assert transport.status == TransportStatus.DISCONNECTED
        assert transport.get_send_buffer_size() == 0
        assert transport.get_receive_buffer_size() == 0

    def test_connect(self) -> None:
        """Connect transitions to CONNECTED."""
        transport = GrpcRegistryTransport()
        transport.connect()
        assert transport.status == TransportStatus.CONNECTED

    def test_connect_idempotent(self) -> None:
        """Calling connect twice is safe."""
        transport = GrpcRegistryTransport()
        transport.connect()
        before = transport.state.connected_at
        time.sleep(0.01)
        transport.connect()
        assert transport.state.connected_at == before

    def test_disconnect(self) -> None:
        """Disconnect transitions to DISCONNECTED."""
        transport = GrpcRegistryTransport()
        transport.connect()
        transport.disconnect()
        assert transport.status == TransportStatus.DISCONNECTED

    def test_state_copy(self) -> None:
        """state property returns a copy, not the internal object."""
        transport = GrpcRegistryTransport()
        s1 = transport.state
        s2 = transport.state
        assert s1 is not s2
        assert s1.connection_id == s2.connection_id

    def test_transport_status_property(self) -> None:
        """Status property reflects connection state."""
        transport = GrpcRegistryTransport()
        assert transport.status == TransportStatus.DISCONNECTED
        transport.connect()
        assert transport.status == TransportStatus.CONNECTED
        transport.disconnect()
        assert transport.status == TransportStatus.DISCONNECTED


# ─── Transport messaging tests ─────────────────────────────────────────────


class TestGrpcTransportMessaging:

    def test_send_message(self) -> None:
        """Send buffers a message and updates counters."""
        transport = GrpcRegistryTransport()
        transport.connect()
        data = b"hello"
        transport.send(data)
        assert transport.get_send_buffer_size() == 1
        state = transport.state
        assert state.messages_sent == 1
        assert state.bytes_sent == 5

    def test_send_unconnected(self) -> None:
        """Send raises ConnectionError when disconnected."""
        transport = GrpcRegistryTransport()
        with pytest.raises(ConnectionError, match="not connected"):
            transport.send(b"data")

    def test_send_too_large(self) -> None:
        """Send raises ValueError for oversized messages."""
        cfg = GrpcTransportConfig(max_message_size_bytes=100)
        transport = GrpcRegistryTransport(config=cfg)
        transport.connect()
        with pytest.raises(ValueError, match="exceeds"):
            transport.send(b"x" * 101)

    def test_receive_message(self) -> None:
        """Receive returns injected data and updates counters."""
        transport = GrpcRegistryTransport()
        transport.connect()
        data = b"world"
        transport.inject_message(data)
        result = transport.receive()
        assert result == data
        state = transport.state
        assert state.messages_received == 1
        assert state.bytes_received == 5

    def test_receive_empty(self) -> None:
        """Receive returns None when buffer is empty."""
        transport = GrpcRegistryTransport()
        transport.connect()
        assert transport.receive() is None

    def test_multiple_sends(self) -> None:
        """Multiple sends accumulate in buffer."""
        transport = GrpcRegistryTransport()
        transport.connect()
        transport.send(b"a")
        transport.send(b"bb")
        transport.send(b"ccc")
        assert transport.get_send_buffer_size() == 3
        state = transport.state
        assert state.messages_sent == 3
        assert state.bytes_sent == 6

    def test_register_handler(self) -> None:
        """Handler registration works."""
        transport = GrpcRegistryTransport()

        def dummy_handler(data: bytes) -> None:
            pass

        transport.register_handler("test_type", dummy_handler)
        assert "test_type" in transport._handlers


# ─── Transport keepalive tests ─────────────────────────────────────────────


class TestGrpcTransportKeepalive:

    def test_keepalive(self) -> None:
        """Keepalive updates last_keepalive_at."""
        transport = GrpcRegistryTransport()
        transport.connect()
        before = transport.state.last_keepalive_at
        time.sleep(0.01)
        transport.keepalive()
        assert transport.state.last_keepalive_at > before

    def test_keepalive_disconnected_noop(self) -> None:
        """Keepalive is a no-op when disconnected."""
        transport = GrpcRegistryTransport()
        transport.keepalive()  # should not raise
        assert transport.state.last_keepalive_at == 0.0

    def test_is_keepalive_stale(self) -> None:
        """Stale check returns True after threshold."""
        transport = GrpcRegistryTransport()
        transport.connect()
        # Immediately after connect, should not be stale
        assert not transport.is_keepalive_stale(threshold_seconds=60)

    def test_keepalive_threshold(self) -> None:
        """Stale check returns True when threshold is small."""
        transport = GrpcRegistryTransport()
        transport.connect()
        # Very small threshold — should be stale (time passes between calls)
        # We set a tiny threshold to ensure staleness
        assert transport.is_keepalive_stale(threshold_seconds=0)

    def test_is_keepalive_stale_disconnected(self) -> None:
        """Disconnected transport is always stale."""
        transport = GrpcRegistryTransport()
        assert transport.is_keepalive_stale()


# ─── Buffer helper tests ───────────────────────────────────────────────────


class TestGrpcTransportBuffers:

    def test_buffer_sizes(self) -> None:
        """Buffer size getters return correct counts."""
        transport = GrpcRegistryTransport()
        transport.connect()
        transport.send(b"a")
        transport.send(b"b")
        transport.inject_message(b"c")
        assert transport.get_send_buffer_size() == 2
        assert transport.get_receive_buffer_size() == 1

    def test_clear_buffers(self) -> None:
        """Clear methods return counts and empty buffers."""
        transport = GrpcRegistryTransport()
        transport.connect()
        transport.send(b"a")
        transport.send(b"b")
        transport.inject_message(b"c")
        transport.inject_message(b"d")

        send_count = transport.clear_send_buffer()
        recv_count = transport.clear_receive_buffer()

        assert send_count == 2
        assert recv_count == 2
        assert transport.get_send_buffer_size() == 0
        assert transport.get_receive_buffer_size() == 0

    def test_clear_receive_buffer(self) -> None:
        """Clear receive buffer returns correct count."""
        transport = GrpcRegistryTransport()
        transport.connect()
        transport.inject_message(b"x")
        assert transport.clear_receive_buffer() == 1
        assert transport.get_receive_buffer_size() == 0


# ─── Stream tests ──────────────────────────────────────────────────────────


class TestGrpcRegistryStream:

    def test_grpc_stream_init(self) -> None:
        """Stream can be created with two transports."""
        local = GrpcRegistryTransport()
        remote = GrpcRegistryTransport()
        stream = GrpcRegistryStream(local, remote)
        assert stream._local is local
        assert stream._remote is remote

    def test_grpc_stream_send(self) -> None:
        """Send delivers message to remote receive buffer."""
        local = GrpcRegistryTransport()
        remote = GrpcRegistryTransport()
        local.connect()
        remote.connect()
        stream = GrpcRegistryStream(local, remote)

        data = b"stream test"
        stream.send(data)
        assert remote.get_receive_buffer_size() == 1

    def test_grpc_stream_receive(self) -> None:
        """Receive returns data from local receive buffer."""
        local = GrpcRegistryTransport()
        remote = GrpcRegistryTransport()
        local.connect()
        remote.connect()
        stream = GrpcRegistryStream(local, remote)

        data = b"incoming"
        local.inject_message(data)
        result = stream.receive()
        assert result == data

    def test_grpc_stream_close(self) -> None:
        """Close disconnects both ends."""
        local = GrpcRegistryTransport()
        remote = GrpcRegistryTransport()
        local.connect()
        remote.connect()
        stream = GrpcRegistryStream(local, remote)

        stream.close()
        assert local.status == TransportStatus.DISCONNECTED
        assert remote.status == TransportStatus.DISCONNECTED

    def test_grpc_stream_is_active(self) -> None:
        """is_active reflects both transports connected."""
        local = GrpcRegistryTransport()
        remote = GrpcRegistryTransport()
        stream = GrpcRegistryStream(local, remote)

        assert not stream.is_active

        local.connect()
        assert not stream.is_active

        remote.connect()
        assert stream.is_active

    def test_stream_bidirectional(self) -> None:
        """Full round-trip: send → receive on both sides."""
        local = GrpcRegistryTransport()
        remote = GrpcRegistryTransport()
        local.connect()
        remote.connect()
        stream = GrpcRegistryStream(local, remote)

        # Local → Remote
        data_lr = b"local to remote"
        stream.send(data_lr)
        assert remote.receive() == data_lr

        # Remote → Local (inject into local)
        data_rl = b"remote to local"
        local.inject_message(data_rl)
        assert stream.receive() == data_rl


# ─── Proto message tests ───────────────────────────────────────────────────


class TestGrpcProtoRegistryMessage:

    def test_proto_message_init(self) -> None:
        """Message can be created with required fields."""
        msg = GrpcProtoRegistryMessage(
            message_type="registry_sync_status",
            source_node_id="node-1",
            destination_node_id="node-2",
        )
        assert msg.message_type == "registry_sync_status"
        assert msg.source_node_id == "node-1"
        assert msg.destination_node_id == "node-2"

    def test_proto_message_defaults(self) -> None:
        """Default values are applied correctly."""
        msg = GrpcProtoRegistryMessage(
            message_type="test",
            source_node_id="src",
            destination_node_id="dst",
        )
        assert len(msg.message_id) > 0
        assert msg.sequence_number == 0
        assert msg.payload == {}
        assert msg.hop_limit == 2
        assert msg.created_at > 0

    def test_proto_message_serialize(self) -> None:
        """to_bytes produces valid JSON bytes."""
        msg = GrpcProtoRegistryMessage(
            message_type="registry_announcement",
            source_node_id="node-1",
            destination_node_id="node-2",
            payload={"key": "value"},
        )
        data = msg.to_bytes()
        assert isinstance(data, bytes)
        assert len(data) > 0

    def test_proto_message_deserialize(self) -> None:
        """from_bytes reconstructs the message."""
        original = GrpcProtoRegistryMessage(
            message_type="registry_object_request",
            source_node_id="node-a",
            destination_node_id="node-b",
            sequence_number=42,
            payload={"object_ids": ["abc", "def"]},
            hop_limit=5,
        )
        data = original.to_bytes()
        restored = GrpcProtoRegistryMessage.from_bytes(data)
        assert restored.message_type == original.message_type
        assert restored.source_node_id == original.source_node_id
        assert restored.destination_node_id == original.destination_node_id
        assert restored.sequence_number == original.sequence_number
        assert restored.payload == original.payload
        assert restored.hop_limit == original.hop_limit

    def test_proto_message_hash(self) -> None:
        """compute_hash produces deterministic SHA-256."""
        msg = GrpcProtoRegistryMessage(
            message_type="test",
            source_node_id="src",
            destination_node_id="dst",
            payload={"a": 1, "b": 2},
        )
        h1 = msg.compute_hash()
        h2 = msg.compute_hash()
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex length

    def test_proto_message_hash_empty_payload(self) -> None:
        """Hash works with empty payload."""
        msg = GrpcProtoRegistryMessage(
            message_type="test",
            source_node_id="src",
            destination_node_id="dst",
            payload={},
        )
        h = msg.compute_hash()
        assert len(h) == 64

    def test_proto_message_roundtrip_with_hash(self) -> None:
        """Hash survives serialization round-trip."""
        msg = GrpcProtoRegistryMessage(
            message_type="registry_sync_status",
            source_node_id="node-1",
            destination_node_id="node-2",
            payload={"epoch": 100, "progress": 0.75},
        )
        original_hash = msg.compute_hash()
        data = msg.to_bytes()
        restored = GrpcProtoRegistryMessage.from_bytes(data)
        restored_hash = restored.compute_hash()
        assert original_hash == restored_hash


# ─── Proto spec tests ──────────────────────────────────────────────────────


class TestGrpcProtoSpec:

    def test_proto_spec_exists(self) -> None:
        """Proto spec string is non-empty."""
        assert len(PROTO_SPEC) > 0

    def test_proto_spec_contains_service(self) -> None:
        """Proto spec defines RegistryReplication service."""
        assert "service RegistryReplication" in PROTO_SPEC

    def test_proto_spec_contains_message(self) -> None:
        """Proto spec defines RegistryMessage."""
        assert "message RegistryMessage" in PROTO_SPEC

    def test_proto_spec_contains_health(self) -> None:
        """Proto spec defines health check messages."""
        assert "message HealthRequest" in PROTO_SPEC
        assert "message HealthResponse" in PROTO_SPEC

    def test_proto_spec_contains_sync_status(self) -> None:
        """Proto spec defines sync status messages."""
        assert "message SyncStatusRequest" in PROTO_SPEC
        assert "message SyncStatusResponse" in PROTO_SPEC

    def test_proto_spec_contains_inventory(self) -> None:
        """Proto spec defines inventory exchange messages."""
        assert "message InventoryRequest" in PROTO_SPEC
        assert "message InventoryResponse" in PROTO_SPEC

    def test_proto_spec_contains_object_fetch(self) -> None:
        """Proto spec defines object fetch messages."""
        assert "message ObjectFetchRequest" in PROTO_SPEC
        assert "message ObjectFetchResponse" in PROTO_SPEC

    def test_proto_spec_contains_ack(self) -> None:
        """Proto spec defines acknowledgment message."""
        assert "message AckResponse" in PROTO_SPEC


# ─── Integration-style tests ───────────────────────────────────────────────


class TestGrpcTransportIntegration:

    def test_full_send_receive_cycle(self) -> None:
        """End-to-end: connect → send → inject → receive → disconnect."""
        transport = GrpcRegistryTransport()
        transport.connect()

        msg = GrpcProtoRegistryMessage(
            message_type="registry_announcement",
            source_node_id="node-1",
            destination_node_id="node-2",
            payload={"object_id": "test-obj"},
        )
        wire = msg.to_bytes()
        transport.send(wire)

        # Simulate remote echo
        transport.inject_message(wire)
        received = transport.receive()
        assert received == wire

        transport.disconnect()
        assert transport.status == TransportStatus.DISCONNECTED

    def test_config_propagation(self) -> None:
        """Config is accessible from transport."""
        cfg = GrpcTransportConfig(host="10.0.0.5", port=9999)
        transport = GrpcRegistryTransport(config=cfg)
        assert transport.config.host == "10.0.0.5"
        assert transport.config.port == 9999

    def test_counters_after_multiple_operations(self) -> None:
        """Counters accumulate correctly across operations."""
        transport = GrpcRegistryTransport()
        transport.connect()

        for i in range(5):
            transport.send(b"x" * (i + 1))

        state = transport.state
        assert state.messages_sent == 5
        assert state.bytes_sent == 1 + 2 + 3 + 4 + 5  # 15

        transport.inject_message(b"a")
        transport.inject_message(b"bb")
        transport.inject_message(b"ccc")

        transport.receive()
        transport.receive()
        transport.receive()

        state = transport.state
        assert state.messages_received == 3
        assert state.bytes_received == 1 + 2 + 3  # 6
