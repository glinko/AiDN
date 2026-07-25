"""Tests for handshake protocol (RFC-0042 §20-24)."""

import pytest
from aidn_hypervisor.dispatcher.handshake import (
    ClientHello,
    ConnectionIdentity,
    ConnectionState,
    HandshakeError,
    HandshakeProtocol,
    PROTOCOL_VERSION,
    ServerHello,
    SUPPORTED_VERSIONS,
)


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def handshake_protocol():
    return HandshakeProtocol(
        local_hypervisor_id="hv-local-001",
        network_id="aidn-mainnet",
        chain_id="chain-001",
        network_revision="rev-1",
    )


@pytest.fixture
def client_hello(handshake_protocol):
    return handshake_protocol.create_client_hello()


# ── ClientHello tests ────────────────────────────────────────────────────

class TestClientHello:
    def test_create_client_hello(self, handshake_protocol):
        hello = handshake_protocol.create_client_hello()
        assert hello.network_id == "aidn-mainnet"
        assert hello.chain_id == "chain-001"
        assert hello.network_revision == "rev-1"
        assert hello.local_hypervisor_id == "hv-local-001"
        assert hello.transport_profile == "QUIC_TLS"
        assert hello.protocol_version == PROTOCOL_VERSION
        assert len(hello.nonce) == 64  # 32 bytes hex

    def test_hello_hash_is_deterministic(self, client_hello):
        h1 = client_hello.compute_hello_hash()
        h2 = client_hello.compute_hello_hash()
        assert h1 == h2
        assert h1.startswith("sha256:") is False  # raw hex, not prefixed
        assert len(h1) == 64

    def test_hello_hash_differs_with_different_nonce(self, handshake_protocol):
        h1 = handshake_protocol.create_client_hello()
        h2 = handshake_protocol.create_client_hello()
        assert h1.nonce != h2.nonce
        assert h1.compute_hello_hash() != h2.compute_hello_hash()

    def test_custom_transport_profile(self, handshake_protocol):
        hello = handshake_protocol.create_client_hello(transport_profile="TCP_TLS")
        assert hello.transport_profile == "TCP_TLS"


# ── ServerHello tests ────────────────────────────────────────────────────

class TestServerHello:
    def test_create_server_hello(self, handshake_protocol, client_hello):
        server_hello = handshake_protocol.create_server_hello(
            client_hello,
            remote_hypervisor_id="hv-remote-002",
        )
        assert server_hello.protocol_version == PROTOCOL_VERSION
        assert server_hello.network_id == "aidn-mainnet"
        assert server_hello.remote_hypervisor_id == "hv-remote-002"
        assert len(server_hello.challenge) == 64
        assert server_hello.domain_matches is True


# ── Domain validation tests ──────────────────────────────────────────────

class TestDomainValidation:
    def test_rejects_wrong_network_id(self, handshake_protocol):
        bad_hello = ClientHello(
            network_id="wrong-network",
            chain_id="chain-001",
            network_revision="rev-1",
            local_hypervisor_id="hv-bad",
        )
        with pytest.raises(HandshakeError) as exc:
            handshake_protocol.validate_client_hello(bad_hello)
        assert exc.value.code == "NETWORK_ID_MISMATCH"

    def test_rejects_wrong_chain_id(self, handshake_protocol):
        bad_hello = ClientHello(
            network_id="aidn-mainnet",
            chain_id="wrong-chain",
            network_revision="rev-1",
            local_hypervisor_id="hv-bad",
        )
        with pytest.raises(HandshakeError) as exc:
            handshake_protocol.validate_client_hello(bad_hello)
        assert exc.value.code == "CHAIN_ID_MISMATCH"

    def test_rejects_wrong_network_revision(self, handshake_protocol):
        bad_hello = ClientHello(
            network_id="aidn-mainnet",
            chain_id="chain-001",
            network_revision="wrong-rev",
            local_hypervisor_id="hv-bad",
        )
        with pytest.raises(HandshakeError) as exc:
            handshake_protocol.validate_client_hello(bad_hello)
        assert exc.value.code == "NETWORK_REVISION_MISMATCH"

    def test_rejects_unsupported_version(self, handshake_protocol):
        bad_hello = ClientHello(
            protocol_version="99.0.0",
            network_id="aidn-mainnet",
            chain_id="chain-001",
            network_revision="rev-1",
            local_hypervisor_id="hv-bad",
        )
        with pytest.raises(HandshakeError) as exc:
            handshake_protocol.validate_client_hello(bad_hello)
        assert exc.value.code == "UNSUPPORTED_VERSION"

    def test_accepts_valid_hello(self, handshake_protocol, client_hello):
        # Should not raise
        handshake_protocol.validate_client_hello(client_hello)


# ── Connection identity tests ────────────────────────────────────────────

class TestConnectionIdentity:
    def test_create_connection_identity(self, handshake_protocol):
        identity = handshake_protocol.create_connection_identity(
            connection_id="conn-001",
            remote_hypervisor_id="hv-remote-002",
            local_nonce="abc123",
            remote_nonce="def456",
            transport_profile="QUIC_TLS",
        )
        assert identity.connection_id == "conn-001"
        assert identity.local_hypervisor_id == "hv-local-001"
        assert identity.remote_hypervisor_id == "hv-remote-002"
        assert identity.state == "ESTABLISHED"
        assert identity.transport_profile == "QUIC_TLS"
        assert identity.established_at is not None

    def test_combined_nonce_is_deterministic(self, handshake_protocol):
        identity = handshake_protocol.create_connection_identity(
            connection_id="conn-001",
            remote_hypervisor_id="hv-remote-002",
            local_nonce="aaa",
            remote_nonce="bbb",
            transport_profile="QUIC_TLS",
        )
        n1 = identity.combined_nonce
        n2 = identity.combined_nonce
        assert n1 == n2
        assert len(n1) == 64

    def test_combined_nonce_differs_with_different_nonces(self, handshake_protocol):
        i1 = handshake_protocol.create_connection_identity(
            connection_id="conn-001",
            remote_hypervisor_id="hv-remote-002",
            local_nonce="aaa",
            remote_nonce="bbb",
            transport_profile="QUIC_TLS",
        )
        i2 = handshake_protocol.create_connection_identity(
            connection_id="conn-002",
            remote_hypervisor_id="hv-remote-002",
            local_nonce="ccc",
            remote_nonce="ddd",
            transport_profile="QUIC_TLS",
        )
        assert i1.combined_nonce != i2.combined_nonce


# ── Full handshake flow test ─────────────────────────────────────────────

class TestHandshakeFlow:
    def test_complete_handshake(self):
        # Alice initiates
        alice = HandshakeProtocol(
            local_hypervisor_id="hv-alice",
            network_id="aidn-testnet",
            chain_id="chain-test",
            network_revision="rev-test",
        )
        client_hello = alice.create_client_hello()

        # Bob responds
        bob = HandshakeProtocol(
            local_hypervisor_id="hv-bob",
            network_id="aidn-testnet",
            chain_id="chain-test",
            network_revision="rev-test",
        )
        server_hello = bob.create_server_hello(
            client_hello,
            remote_hypervisor_id="hv-alice",
        )

        # Validate exchange
        assert server_hello.protocol_version == client_hello.protocol_version
        assert server_hello.network_id == client_hello.network_id
        assert len(server_hello.challenge) == 64

        # Create connection identities
        alice_conn = alice.create_connection_identity(
            connection_id="conn-ab",
            remote_hypervisor_id="hv-bob",
            local_nonce=client_hello.nonce,
            remote_nonce=server_hello.challenge,
            transport_profile="QUIC_TLS",
        )
        bob_conn = bob.create_connection_identity(
            connection_id="conn-ab",
            remote_hypervisor_id="hv-alice",
            local_nonce=server_hello.challenge,
            remote_nonce=client_hello.nonce,
            transport_profile="QUIC_TLS",
        )

        assert alice_conn.state == "ESTABLISHED"
        assert bob_conn.state == "ESTABLISHED"
        assert alice_conn.remote_hypervisor_id == "hv-bob"
        assert bob_conn.remote_hypervisor_id == "hv-alice"

    def test_handshake_fails_on_domain_mismatch(self):
        alice = HandshakeProtocol(
            local_hypervisor_id="hv-alice",
            network_id="aidn-mainnet",
            chain_id="chain-001",
            network_revision="rev-1",
        )
        client_hello = alice.create_client_hello()

        bob = HandshakeProtocol(
            local_hypervisor_id="hv-bob",
            network_id="aidn-testnet",  # Different network!
            chain_id="chain-001",
            network_revision="rev-1",
        )
        with pytest.raises(HandshakeError) as exc:
            bob.create_server_hello(client_hello, remote_hypervisor_id="hv-alice")
        assert exc.value.code == "NETWORK_ID_MISMATCH"
