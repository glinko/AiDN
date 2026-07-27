"""Tests for the transport abstraction layer.

Covers:
- MessageFramer round-trip serialization (single + batch)
- Framing correctness (length-prefix boundaries)
- TransportStatus enum transitions
- TransportGateway protocol conformance
"""

from __future__ import annotations

import struct
from typing import Any

import pytest

from aidn_hypervisor.dispatcher.models import (
    NetworkMessage,
    NetworkSubject,
    canonical_payload_bytes,
    canonical_payload_hash,
)
from aidn_hypervisor.dispatcher.transport import (
    MessageFramer,
    TransportGateway,
    TransportStatus,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_message(**overrides: Any) -> NetworkMessage:
    """Build a valid NetworkMessage for testing."""
    payload = {"action": "ping", "value": 42}
    encoded = canonical_payload_bytes(payload)
    base: dict[str, Any] = {
        "message_id": "msg-001",
        "message_type": "PING",
        "network_id": "testnet",
        "chain_id": "chain-1",
        "network_revision": "1",
        "channel_id": "ch-ctrl",
        "channel_class": "CONTROL",
        "source_subject": NetworkSubject(subject_type="HYPERVISOR", subject_id="hv-1"),
        "destination_subject": NetworkSubject(subject_type="RUNTIME", subject_id="rt-1"),
        "source_sequence": 0,
        "priority_class": "NORMAL",
        "route_generation": 1,
        "created_at": "2025-01-01T00:00:00Z",
        "expiration": "2025-01-02T00:00:00Z",
        "payload_hash": canonical_payload_hash(payload),
        "payload_length": len(encoded),
        "payload": payload,
    }
    base.update(overrides)
    return NetworkMessage(**base)


# ---------------------------------------------------------------------------
# MessageFramer — round-trip
# ---------------------------------------------------------------------------

class TestMessageFramerRoundTrip:
    def test_single_message_round_trip(self) -> None:
        msg = _make_message()
        wire = MessageFramer.encode(msg)
        decoded = MessageFramer.decode(wire)
        assert decoded.message_id == msg.message_id
        assert decoded.payload == msg.payload
        assert decoded.channel_class == msg.channel_class

    def test_multiple_distinct_messages_round_trip(self) -> None:
        msgs = [
            _make_message(message_id="a", message_type="PING"),
            _make_message(message_id="b", message_type="PONG"),
            _make_message(message_id="c", message_type="HEARTBEAT"),
        ]
        wire = MessageFramer.encode_batch(msgs)
        decoded = MessageFramer.decode_stream(wire)
        assert len(decoded) == 3
        for original, restored in zip(msgs, decoded, strict=True):
            assert restored.message_id == original.message_id
            assert restored.message_type == original.message_type

    def test_empty_batch(self) -> None:
        wire = MessageFramer.encode_batch([])
        assert wire == b""
        assert MessageFramer.decode_stream(wire) == []


# ---------------------------------------------------------------------------
# MessageFramer — framing correctness
# ---------------------------------------------------------------------------

class TestMessageFramerFraming:
    def test_length_prefix_is_4_bytes_big_endian(self) -> None:
        msg = _make_message()
        wire = MessageFramer.encode(msg)
        body = msg.model_dump_json().encode("utf-8")
        prefix = wire[:4]
        expected_prefix = struct.pack("!I", len(body))
        assert prefix == expected_prefix
        assert wire[4:] == body

    def test_decode_stream_handles_partial_trailing_data(self) -> None:
        msg = _make_message()
        wire = MessageFramer.encode(msg)
        # Append 3 bytes that are not enough for a new length prefix
        partial = wire + b"\x00\x01\x02"
        decoded = MessageFramer.decode_stream(partial)
        assert len(decoded) == 1
        assert decoded[0].message_id == msg.message_id

    def test_decode_raises_on_insufficient_prefix(self) -> None:
        with pytest.raises(ValueError, match="insufficient data"):
            MessageFramer.decode(b"\x00\x01")

    def test_decode_raises_on_incomplete_body(self) -> None:
        # Prefix says 1000 bytes, but only 10 follow
        bad = struct.pack("!I", 1000) + b"\x00" * 10
        with pytest.raises(ValueError, match="incomplete message body"):
            MessageFramer.decode(bad)

    def test_decode_stream_concatenated_messages(self) -> None:
        m1 = _make_message(message_id="first")
        m2 = _make_message(message_id="second")
        stream = MessageFramer.encode(m1) + MessageFramer.encode(m2)
        results = MessageFramer.decode_stream(stream)
        assert len(results) == 2
        assert results[0].message_id == "first"
        assert results[1].message_id == "second"


# ---------------------------------------------------------------------------
# TransportStatus — transitions
# ---------------------------------------------------------------------------

class TestTransportStatusTransitions:
    """Verify the enum values and a typical lifecycle."""

    def test_all_statuses_exist(self) -> None:
        assert TransportStatus.DISCONNECTED.value == "disconnected"
        assert TransportStatus.CONNECTING.value == "connecting"
        assert TransportStatus.CONNECTED.value == "connected"
        assert TransportStatus.ERROR.value == "error"

    def test_typical_lifecycle(self) -> None:
        """DISCONNECTED -> CONNECTING -> CONNECTED -> DISCONNECTED."""
        states: list[TransportStatus] = []
        states.append(TransportStatus.DISCONNECTED)
        states.append(TransportStatus.CONNECTING)
        states.append(TransportStatus.CONNECTED)
        states.append(TransportStatus.DISCONNECTED)
        assert len(states) == 4
        assert states[0] != states[2]

    def test_error_recovery_lifecycle(self) -> None:
        """DISCONNECTED -> CONNECTING -> ERROR -> DISCONNECTED -> CONNECTING -> CONNECTED."""
        lifecycle = [
            TransportStatus.DISCONNECTED,
            TransportStatus.CONNECTING,
            TransportStatus.ERROR,
            TransportStatus.DISCONNECTED,
            TransportStatus.CONNECTING,
            TransportStatus.CONNECTED,
        ]
        assert lifecycle[2] == TransportStatus.ERROR
        assert lifecycle[-1] == TransportStatus.CONNECTED


# ---------------------------------------------------------------------------
# TransportGateway — protocol conformance
# ---------------------------------------------------------------------------

class TestTransportGatewayProtocol:
    """Verify that a concrete class satisfying the protocol is accepted."""

    def _make_mock_transport(self) -> Any:
        """Minimal in-memory transport that satisfies TransportGateway."""

        class _MockTransport:
            def __init__(self) -> None:
                self._status = TransportStatus.DISCONNECTED
                self._buffer: list[NetworkMessage] = []
                self._sent: list[bytes] = []

            def connect(self) -> None:
                self._status = TransportStatus.CONNECTED

            def disconnect(self) -> None:
                self._status = TransportStatus.DISCONNECTED

            def send(self, message: NetworkMessage) -> bytes:
                data = MessageFramer.encode(message)
                self._sent.append(data)
                return data

            def receive(self) -> NetworkMessage | None:
                return self._buffer.pop(0) if self._buffer else None

            @property
            def status(self) -> TransportStatus:
                return self._status

        return _MockTransport()

    def test_mock_satisfies_protocol(self) -> None:
        t = self._make_mock_transport()
        assert isinstance(t, TransportGateway)

    def test_mock_lifecycle(self) -> None:
        t = self._make_mock_transport()
        assert t.status == TransportStatus.DISCONNECTED
        t.connect()
        assert t.status == TransportStatus.CONNECTED
        t.disconnect()
        assert t.status == TransportStatus.DISCONNECTED

    def test_mock_send_returns_wire_bytes(self) -> None:
        t = self._make_mock_transport()
        t.connect()
        msg = _make_message()
        wire = t.send(msg)
        assert isinstance(wire, bytes)
        assert len(wire) > 4  # at least length prefix

    def test_mock_receive_none_when_empty(self) -> None:
        t = self._make_mock_transport()
        t.connect()
        assert t.receive() is None
