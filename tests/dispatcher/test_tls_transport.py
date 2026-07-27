"""Tests for the TLS-wrapped TCP transport adapter.

Covers:
- TLS connect / disconnect lifecycle
- Message round-trip over TLS
- Bidirectional exchange over TLS
- Certificate validation (verify=True rejects bad certs)
- Fallback to plain TCP when TLS handshake fails
- TransportGateway protocol conformance
- Context manager support
- Error handling (send when disconnected)
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
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
from aidn_hypervisor.dispatcher.transport.tls import (
    TlsListener,
    TlsTransport,
)

# ---------------------------------------------------------------------------
# Helpers — generate self-signed certs on the fly
# ---------------------------------------------------------------------------

def _generate_self_signed_cert(tmp_dir: str) -> tuple[str, str]:
    """Create a self-signed certificate and key in *tmp_dir*.

    Returns ``(cert_path, key_path)``.
    """
    cert_path = os.path.join(tmp_dir, "server.crt")
    key_path = os.path.join(tmp_dir, "server.key")

    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048",
            "-keyout", key_path, "-out", cert_path,
            "-days", "1", "-nodes",
            "-subj", "/CN=localhost",
        ],
        capture_output=True,
        check=True,
    )
    return cert_path, key_path


# ---------------------------------------------------------------------------
# Helpers — message factory
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
def tls_certs(tmp_path: Any) -> tuple[str, str]:
    """Generate self-signed cert + key, return paths."""
    return _generate_self_signed_cert(str(tmp_path))


@pytest.fixture
def tls_listener(tls_certs: tuple[str, str]) -> TlsListener:
    """Create a bound TLS listener on a random port."""
    cert_path, key_path = tls_certs
    tls_listener = TlsListener(
        host="127.0.0.1",
        port=0,
        certfile=cert_path,
        keyfile=key_path,
    )
    tls_listener.bind()
    return tls_listener


@pytest.fixture
def tls_bound_port(tls_listener: TlsListener) -> int:
    """Return the actual port the TLS listener is bound to."""
    return tls_listener.bound_port


def _connect_pair(
    tls_listener: TlsListener,
    tls_bound_port: int,
    verify: bool = False,
) -> TlsTransport:
    """Helper: accept on listener first, then connect + handshake client.

    Returns the connected ``TlsTransport`` instance with TLS established.
    """
    ready = threading.Event()

    def _accept() -> None:
        tls_listener.accept()
        ready.set()

    accept_thread = threading.Thread(target=_accept, daemon=True)
    accept_thread.start()

    # Step 1 — TCP connect (no TLS yet)
    t = TlsTransport(
        "127.0.0.1", tls_bound_port,
        verify=verify,
        send_timeout=2.0,
        recv_timeout=2.0,
    )
    t.connect()

    # Step 2 — wait for server to accept before TLS handshake
    ready.wait(timeout=3)

    # Step 3 — TLS handshake
    t.handshake()

    return t


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------

class TestTlsProtocolConformance:
    def test_satisfies_transport_gateway(self) -> None:
        """TlsTransport implements the TransportGateway protocol."""
        t = TlsTransport("127.0.0.1", 0)
        assert isinstance(t, TransportGateway)

    def test_initial_status_disconnected(self) -> None:
        """Transport starts in DISCONNECTED state."""
        t = TlsTransport("127.0.0.1", 0)
        assert t.status == TransportStatus.DISCONNECTED
        assert t.tls_established is False


# ---------------------------------------------------------------------------
# TLS connect / disconnect
# ---------------------------------------------------------------------------

class TestTlsConnection:
    def test_tls_connect_disconnect(
        self, tls_listener: TlsListener, tls_bound_port: int
    ) -> None:
        """Client connects over TLS, then disconnects cleanly."""
        t = _connect_pair(tls_listener, tls_bound_port)

        assert t.status == TransportStatus.CONNECTED
        assert t.tls_established is True

        t.disconnect()
        assert t.status == TransportStatus.DISCONNECTED
        assert t.tls_established is False

        tls_listener.close()

    def test_context_manager_tls(
        self, tls_listener: TlsListener, tls_bound_port: int
    ) -> None:
        """TLS transport works as a context manager (connect + handshake)."""
        ready = threading.Event()

        def _accept() -> None:
            tls_listener.accept()
            ready.set()

        accept_thread = threading.Thread(target=_accept, daemon=True)
        accept_thread.start()

        with TlsTransport(
            "127.0.0.1", tls_bound_port,
            verify=False,
            send_timeout=2.0,
            recv_timeout=2.0,
        ) as t:
            ready.wait(timeout=3)
            assert t.status == TransportStatus.CONNECTED
            assert t.tls_established is True

        assert t.status == TransportStatus.DISCONNECTED
        tls_listener.close()


# ---------------------------------------------------------------------------
# Message exchange over TLS
# ---------------------------------------------------------------------------

class TestTlsMessageExchange:
    def test_single_message_round_trip(
        self, tls_listener: TlsListener, tls_bound_port: int
    ) -> None:
        """Client sends a message over TLS, listener receives it."""
        msg = _make_message(message_id="tls-001")
        t = _connect_pair(tls_listener, tls_bound_port)

        wire = t.send(msg)
        assert isinstance(wire, bytes)
        assert len(wire) > 4

        # Allow data to traverse the network buffer
        time.sleep(0.2)

        received = tls_listener.receive()
        assert received is not None
        assert received.message_id == msg.message_id
        assert received.payload == msg.payload

        t.disconnect()
        tls_listener.close()

    def test_bidirectional_tls_exchange(
        self, tls_listener: TlsListener, tls_bound_port: int
    ) -> None:
        """Both sides send and receive messages over TLS."""
        client_msg = _make_message(message_id="tls-client")
        server_msg = _make_message(message_id="tls-server", message_type="REPLY")

        ready = threading.Event()

        def _accept_and_reply() -> None:
            tls_listener.accept()
            ready.set()
            got = tls_listener.receive()
            assert got is not None
            assert got.message_id == "tls-client"
            tls_listener.send(server_msg)

        accept_thread = threading.Thread(target=_accept_and_reply, daemon=True)
        accept_thread.start()

        t = TlsTransport(
            "127.0.0.1", tls_bound_port,
            verify=False,
            send_timeout=2.0,
            recv_timeout=2.0,
        )
        t.connect()
        ready.wait(timeout=3)
        t.handshake()

        t.send(client_msg)
        reply = t.receive()
        assert reply is not None
        assert reply.message_id == "tls-server"

        t.disconnect()
        tls_listener.close()


# ---------------------------------------------------------------------------
# Certificate validation
# ---------------------------------------------------------------------------

class TestCertificateValidation:
    def test_verify_true_rejects_self_signed(
        self, tls_listener: TlsListener, tls_bound_port: int
    ) -> None:
        """verify=True should fail for self-signed certs without CA."""
        accept_errors: list[ConnectionError] = []

        def _accept() -> None:
            try:
                tls_listener.accept()
            except ConnectionError as error:
                accept_errors.append(error)

        accept_thread = threading.Thread(target=_accept, daemon=True)
        accept_thread.start()

        t = TlsTransport(
            "127.0.0.1", tls_bound_port,
            verify=True,  # strict verification — no CA provided
            send_timeout=2.0,
            recv_timeout=2.0,
        )
        t.connect()

        # Self-signed cert should fail verification during handshake
        with pytest.raises(ConnectionError, match="TLS handshake failed"):
            t.handshake()

        accept_thread.join(timeout=3)
        assert accept_errors
        assert "TLS accept failed" in str(accept_errors[0])
        t.disconnect()
        tls_listener.close()


# ---------------------------------------------------------------------------
# Fallback to plain TCP
# ---------------------------------------------------------------------------

class TestFallbackToPlainTcp:
    def test_plain_tcp_without_handshake(self, tls_certs: tuple[str, str]) -> None:
        """TlsTransport can operate as plain TCP when handshake() is skipped."""
        import socket

        raw_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        raw_server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        raw_server.bind(("127.0.0.1", 0))
        raw_server.listen(5)
        raw_server.settimeout(5.0)
        port = raw_server.getsockname()[1]

        ready = threading.Event()

        def _accept() -> None:
            raw_server.accept()
            ready.set()

        accept_thread = threading.Thread(target=_accept, daemon=True)
        accept_thread.start()

        t = TlsTransport(
            "127.0.0.1", port,
            verify=False,
            send_timeout=2.0,
            recv_timeout=2.0,
        )
        t.connect()
        ready.wait(timeout=3)

        # Connection should succeed; TLS not established (no handshake called)
        assert t.status == TransportStatus.CONNECTED
        assert t.tls_established is False

        t.disconnect()
        raw_server.close()


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestTlsErrors:
    def test_send_when_disconnected(self) -> None:
        """Sending without connecting raises ConnectionError."""
        t = TlsTransport("127.0.0.1", 0)
        msg = _make_message()
        with pytest.raises(ConnectionError, match="not connected"):
            t.send(msg)

    def test_connect_refused(self) -> None:
        """Connecting to a port with no listener raises ConnectionError."""
        t = TlsTransport("127.0.0.1", 59998, send_timeout=1.0, recv_timeout=1.0)
        with pytest.raises(ConnectionError):
            t.connect()
        assert t.status == TransportStatus.ERROR
