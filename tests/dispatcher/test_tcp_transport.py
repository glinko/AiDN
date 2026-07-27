"""Tests for the TCP transport adapter.

Covers:
- TCP send/receive round-trip via listener + transport pair
- Connection lifecycle (connect -> send -> disconnect)
- Error handling (invalid host, disconnected send, receive on closed)
- TransportGateway protocol conformance
- Multiple messages and bidirectional exchange
"""

from __future__ import annotations

import threading
from typing import Any

import pytest

from aidn_hypervisor.dispatcher.models import (
    NetworkMessage,
    NetworkSubject,
    canonical_payload_bytes,
    canonical_payload_hash,
)
from aidn_hypervisor.dispatcher.transport import (
    TransportGateway,
    TransportStatus,
)
from aidn_hypervisor.dispatcher.transport.tcp import (
    TcpListener,
    TcpTransport,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_message(**overrides: Any) -> NetworkMessage:
    """Build a valid NetworkMessage for testing."""
    payload = {"action": "test", "value": 123}
    encoded = canonical_payload_bytes(payload)
    base: dict[str, Any] = {
        "message_id": "msg-test",
        "message_type": "TEST",
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


@pytest.fixture
def listener() -> TcpListener:
    """Create a bound TcpListener on a random port."""
    tcp_listener = TcpListener(host="127.0.0.1", port=0)
    tcp_listener.bind()
    return tcp_listener


@pytest.fixture
def bound_port(listener: TcpListener) -> int:
    """Return the actual port the listener is bound to."""
    return listener.bound_port


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------

class TestTcpProtocolConformance:
    def test_satisfies_transport_gateway(self) -> None:
        t = TcpTransport("127.0.0.1", 0)
        assert isinstance(t, TransportGateway)

    def test_initial_status_disconnected(self) -> None:
        t = TcpTransport("127.0.0.1", 0)
        assert t.status == TransportStatus.DISCONNECTED


# ---------------------------------------------------------------------------
# Connection lifecycle
# ---------------------------------------------------------------------------

class TestConnectionLifecycle:
    def test_connect_disconnect(self, listener: TcpListener, bound_port: int) -> None:
        t = TcpTransport("127.0.0.1", bound_port, send_timeout=2.0, recv_timeout=2.0)
        assert t.status == TransportStatus.DISCONNECTED

        def _accept() -> None:
            listener.accept()

        accept_thread = threading.Thread(target=_accept, daemon=True)
        accept_thread.start()

        t.connect()
        accept_thread.join(timeout=3)
        assert t.status == TransportStatus.CONNECTED

        t.disconnect()
        assert t.status == TransportStatus.DISCONNECTED
        listener.close()

    def test_double_connect_is_idempotent(
        self, listener: TcpListener, bound_port: int
    ) -> None:
        t = TcpTransport("127.0.0.1", bound_port, send_timeout=2.0, recv_timeout=2.0)

        def _accept() -> None:
            listener.accept()

        accept_thread = threading.Thread(target=_accept, daemon=True)
        accept_thread.start()

        t.connect()
        accept_thread.join(timeout=3)
        t.connect()  # should not raise
        assert t.status == TransportStatus.CONNECTED

        t.disconnect()
        listener.close()

    def test_context_manager(self, listener: TcpListener, bound_port: int) -> None:
        def _accept() -> None:
            listener.accept()

        accept_thread = threading.Thread(target=_accept, daemon=True)
        accept_thread.start()

        with TcpTransport("127.0.0.1", bound_port, send_timeout=2.0, recv_timeout=2.0) as t:
            accept_thread.join(timeout=3)
            assert t.status == TransportStatus.CONNECTED

        assert t.status == TransportStatus.DISCONNECTED
        listener.close()

    def test_host_port_properties(self) -> None:
        t = TcpTransport("192.168.1.100", 8080)
        assert t.host == "192.168.1.100"
        assert t.port == 8080


# ---------------------------------------------------------------------------
# Send / receive round-trip
# ---------------------------------------------------------------------------

class TestTcpRoundTrip:
    def test_single_message_round_trip(self, listener: TcpListener, bound_port: int) -> None:
        """Client sends a message, listener receives it."""
        msg = _make_message(message_id="rt-001")

        def _accept() -> None:
            listener.accept()

        accept_thread = threading.Thread(target=_accept, daemon=True)
        accept_thread.start()

        t = TcpTransport("127.0.0.1", bound_port, send_timeout=2.0, recv_timeout=2.0)
        t.connect()
        accept_thread.join(timeout=3)

        wire = t.send(msg)
        assert isinstance(wire, bytes)
        assert len(wire) > 4  # length prefix + body

        received = listener.receive()
        assert received is not None
        assert received.message_id == msg.message_id
        assert received.payload == msg.payload

        t.disconnect()
        listener.close()

    def test_bidirectional_exchange(self, listener: TcpListener, bound_port: int) -> None:
        """Both sides send and receive messages."""
        client_msg = _make_message(message_id="client-msg")
        server_msg = _make_message(message_id="server-msg", message_type="SERVER_REPLY")

        def _accept_and_reply() -> None:
            listener.accept()
            got = listener.receive()
            assert got is not None
            assert got.message_id == "client-msg"
            listener.send(server_msg)

        accept_thread = threading.Thread(target=_accept_and_reply, daemon=True)
        accept_thread.start()

        t = TcpTransport("127.0.0.1", bound_port, send_timeout=2.0, recv_timeout=2.0)
        t.connect()
        accept_thread.join(timeout=3)

        t.send(client_msg)
        reply = t.receive()
        assert reply is not None
        assert reply.message_id == "server-msg"

        t.disconnect()
        listener.close()

    def test_multiple_messages(self, listener: TcpListener, bound_port: int) -> None:
        """Send several messages in sequence."""
        msgs = [_make_message(message_id=f"seq-{i}") for i in range(5)]

        def _accept() -> None:
            listener.accept()

        accept_thread = threading.Thread(target=_accept, daemon=True)
        accept_thread.start()

        t = TcpTransport("127.0.0.1", bound_port, send_timeout=2.0, recv_timeout=2.0)
        t.connect()
        accept_thread.join(timeout=3)

        for msg in msgs:
            t.send(msg)

        for msg in msgs:
            received = listener.receive()
            assert received is not None
            assert received.message_id == msg.message_id

        t.disconnect()
        listener.close()


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_connect_refused(self) -> None:
        """Connecting to a port with no listener raises ConnectionError."""
        t = TcpTransport("127.0.0.1", 59999, send_timeout=1.0, recv_timeout=1.0)
        with pytest.raises(ConnectionError):
            t.connect()
        assert t.status == TransportStatus.ERROR

    def test_send_when_disconnected(self) -> None:
        """Sending without connecting raises ConnectionError."""
        t = TcpTransport("127.0.0.1", 0)
        msg = _make_message()
        with pytest.raises(ConnectionError, match="not connected"):
            t.send(msg)

    def test_receive_when_disconnected(self) -> None:
        """Receiving without connecting returns None."""
        t = TcpTransport("127.0.0.1", 0)
        assert t.receive() is None

    def test_send_after_disconnect(self, listener: TcpListener, bound_port: int) -> None:
        """Sending after disconnect raises ConnectionError."""
        t = TcpTransport("127.0.0.1", bound_port, send_timeout=2.0, recv_timeout=2.0)

        def _accept() -> None:
            listener.accept()

        accept_thread = threading.Thread(target=_accept, daemon=True)
        accept_thread.start()

        t.connect()
        accept_thread.join(timeout=3)
        t.disconnect()

        msg = _make_message()
        with pytest.raises(ConnectionError, match="not connected"):
            t.send(msg)

        listener.close()

    def test_receive_after_peer_close(self, listener: TcpListener, bound_port: int) -> None:
        """Receiving after the listener closes returns None and transitions status."""
        t = TcpTransport("127.0.0.1", bound_port, send_timeout=2.0, recv_timeout=2.0)

        def _accept() -> None:
            listener.accept()

        accept_thread = threading.Thread(target=_accept, daemon=True)
        accept_thread.start()

        t.connect()
        accept_thread.join(timeout=3)

        # Close listener side — next receive should see EOF
        listener.close()
        result = t.receive()
        assert result is None
        assert t.status in (TransportStatus.DISCONNECTED, TransportStatus.ERROR)
