"""Tests for the Unix-domain-socket transport adapter.

Covers:
- IPC send/receive round-trip via listener + transport pair
- Connection lifecycle (connect → send → disconnect)
- Error handling (invalid path, disconnected send, receive on closed)
- TransportGateway protocol conformance
- register_remote_route sender-callback integration
"""

from __future__ import annotations

import socket
import threading
from pathlib import Path
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
from aidn_hypervisor.dispatcher.transport.unix_socket import (
    UnixSocketListener,
    UnixSocketTransport,
)

pytestmark = pytest.mark.skipif(
    not hasattr(socket, "AF_UNIX"),
    reason="Unix-domain sockets are unavailable on this platform",
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
def socket_path(tmp_path: Path) -> str:
    """Return a unique socket path in a temp directory."""
    return str(tmp_path / "test_ipc.sock")


@pytest.fixture
def listener(socket_path: str) -> UnixSocketListener:
    """Create a bound UnixSocketListener (non-blocking accept)."""
    socket_listener = UnixSocketListener(socket_path)
    socket_listener.bind()
    return socket_listener


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestUnixSocketProtocolConformance:
    def test_satisfies_transport_gateway(self) -> None:
        t = UnixSocketTransport("/tmp/nonexistent.sock")
        assert isinstance(t, TransportGateway)

    def test_initial_status_disconnected(self) -> None:
        t = UnixSocketTransport("/tmp/nonexistent.sock")
        assert t.status == TransportStatus.DISCONNECTED


# ---------------------------------------------------------------------------
# Connection lifecycle
# ---------------------------------------------------------------------------


class TestConnectionLifecycle:
    def test_connect_disconnect(self, socket_path: str, listener: UnixSocketListener) -> None:
        t = UnixSocketTransport(socket_path, send_timeout=2.0, recv_timeout=2.0)
        assert t.status == TransportStatus.DISCONNECTED

        t.connect()
        assert t.status == TransportStatus.CONNECTED

        t.disconnect()
        assert t.status == TransportStatus.DISCONNECTED

        listener.close()

    def test_double_connect_is_idempotent(self, socket_path: str, listener: UnixSocketListener) -> None:
        t = UnixSocketTransport(socket_path, send_timeout=2.0, recv_timeout=2.0)
        t.connect()
        t.connect()  # should not raise
        assert t.status == TransportStatus.CONNECTED

        t.disconnect()
        listener.close()

    def test_context_manager(self, socket_path: str, listener: UnixSocketListener) -> None:
        with UnixSocketTransport(socket_path, send_timeout=2.0, recv_timeout=2.0) as t:
            assert t.status == TransportStatus.CONNECTED

        assert t.status == TransportStatus.DISCONNECTED
        listener.close()

    def test_socket_path_property(self) -> None:
        t = UnixSocketTransport("/var/run/aidn.sock")
        assert t.socket_path == "/var/run/aidn.sock"


# ---------------------------------------------------------------------------
# Send / receive round-trip
# ---------------------------------------------------------------------------


class TestIPCRoundTrip:
    def test_single_message_round_trip(self, socket_path: str, listener: UnixSocketListener) -> None:
        """Client sends a message, listener receives it."""
        msg = _make_message(message_id="rt-001")

        # Accept client in background thread
        def _accept() -> None:
            listener.accept()

        accept_thread = threading.Thread(target=_accept, daemon=True)
        accept_thread.start()

        t = UnixSocketTransport(socket_path, send_timeout=2.0, recv_timeout=2.0)
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

    def test_bidirectional_exchange(self, socket_path: str, listener: UnixSocketListener) -> None:
        """Both sides send and receive messages."""
        client_msg = _make_message(message_id="client-msg")
        server_msg = _make_message(message_id="server-msg", message_type="SERVER_REPLY")

        def _accept_and_reply() -> None:
            listener.accept()
            # Receive from client
            got = listener.receive()
            assert got is not None
            assert got.message_id == "client-msg"
            # Reply
            listener.send(server_msg)

        accept_thread = threading.Thread(target=_accept_and_reply, daemon=True)
        accept_thread.start()

        t = UnixSocketTransport(socket_path, send_timeout=2.0, recv_timeout=2.0)
        t.connect()
        accept_thread.join(timeout=3)

        t.send(client_msg)
        reply = t.receive()
        assert reply is not None
        assert reply.message_id == "server-msg"

        t.disconnect()
        listener.close()

    def test_multiple_messages(self, socket_path: str, listener: UnixSocketListener) -> None:
        """Send several messages in sequence."""
        msgs = [_make_message(message_id=f"seq-{i}") for i in range(5)]

        def _accept() -> None:
            listener.accept()

        accept_thread = threading.Thread(target=_accept, daemon=True)
        accept_thread.start()

        t = UnixSocketTransport(socket_path, send_timeout=2.0, recv_timeout=2.0)
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
    def test_connect_invalid_path(self) -> None:
        """Connecting to a non-existent socket path raises ConnectionError."""
        t = UnixSocketTransport(
            "/tmp/aidn_nonexistent_socket_path.sock",
            send_timeout=1.0,
            recv_timeout=1.0,
        )
        with pytest.raises(ConnectionError):
            t.connect()
        assert t.status == TransportStatus.ERROR

    def test_send_when_disconnected(self) -> None:
        """Sending without connecting raises ConnectionError."""
        t = UnixSocketTransport("/tmp/unused.sock")
        msg = _make_message()
        with pytest.raises(ConnectionError, match="not connected"):
            t.send(msg)

    def test_receive_when_disconnected(self) -> None:
        """Receiving without connecting returns None."""
        t = UnixSocketTransport("/tmp/unused.sock")
        assert t.receive() is None

    def test_send_after_disconnect(self, socket_path: str, listener: UnixSocketListener) -> None:
        """Sending after disconnect raises ConnectionError."""
        t = UnixSocketTransport(socket_path, send_timeout=2.0, recv_timeout=2.0)

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

    def test_receive_after_peer_close(self, socket_path: str, listener: UnixSocketListener) -> None:
        """Receiving after the listener closes returns None and transitions status."""
        t = UnixSocketTransport(socket_path, send_timeout=2.0, recv_timeout=2.0)

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


# ---------------------------------------------------------------------------
# Sender callback integration
# ---------------------------------------------------------------------------


class TestSenderCallbackIntegration:
    def test_make_sender_callback(self, socket_path: str, listener: UnixSocketListener) -> None:
        """The _make_sender_callback returns a callable compatible with register_remote_route."""
        t = UnixSocketTransport(socket_path, send_timeout=2.0, recv_timeout=2.0)

        def _accept() -> None:
            listener.accept()

        accept_thread = threading.Thread(target=_accept, daemon=True)
        accept_thread.start()

        t.connect()
        accept_thread.join(timeout=3)

        sender = t._make_sender_callback()
        msg = _make_message(message_id="callback-msg")
        data = msg.model_dump()

        # The callback accepts a dict and sends it
        sender(data)

        received = listener.receive()
        assert received is not None
        assert received.message_id == "callback-msg"

        t.disconnect()
        listener.close()

    def test_sender_callback_raises_when_disconnected(self) -> None:
        """Sender callback raises ConnectionError when transport is not connected."""
        t = UnixSocketTransport("/tmp/unused.sock")
        sender = t._make_sender_callback()
        msg = _make_message()
        data = msg.model_dump()

        with pytest.raises(ConnectionError):
            sender(data)
