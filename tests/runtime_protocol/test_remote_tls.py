from datetime import datetime, timedelta, timezone
import ssl

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from aidn_hypervisor.dispatcher import NetworkMessage, canonical_payload_hash
from aidn_hypervisor.dispatcher.models import canonical_payload_bytes
from aidn_hypervisor.runtime_protocol import TlsRuntimeClient, TlsRuntimeListener


def _message() -> NetworkMessage:
    payload = {"event_type": "RUNTIME_HEALTH", "event": {"state": "HEALTHY"}}
    now = datetime.now(timezone.utc)
    return NetworkMessage(
        message_id="remote-tls-message-1",
        message_type="RUNTIME_HEALTH",
        network_id="aidn-test",
        chain_id="chain-test",
        network_revision="revision-1",
        connection_id="runtime-connection-1",
        channel_id="runtime-remote-tls",
        channel_class="RUNTIME",
        source_subject={"subject_type": "RUNTIME", "subject_id": "runtime-1"},
        destination_subject={
            "subject_type": "HYPERVISOR_RUNTIME_INGRESS",
            "subject_id": "runtime-1",
        },
        source_sequence=1,
        route_generation=1,
        runtime_generation=1,
        created_at=now.isoformat(),
        expiration=(now + timedelta(minutes=1)).isoformat(),
        payload_hash=canonical_payload_hash(payload),
        payload_length=len(canonical_payload_bytes(payload)),
        payload=payload,
        authentication={"transport": "REMOTE_TLS"},
    )


def _write_certificate_pair(tmp_path, name: str, ca_key, ca_certificate, *, server: bool) -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_certificate.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc) - timedelta(minutes=1))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage(
                [x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]
                if server
                else [x509.oid.ExtendedKeyUsageOID.CLIENT_AUTH]
            ),
            critical=False,
        )
    )
    if server:
        builder = builder.add_extension(
            x509.SubjectAlternativeName([x509.DNSName("localhost")]),
            critical=False,
        )
    certificate = builder.sign(ca_key, hashes.SHA256())
    certificate_path = tmp_path / f"{name}.cert.pem"
    key_path = tmp_path / f"{name}.key.pem"
    certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return str(certificate_path), str(key_path)


def _tls_contexts(tmp_path) -> tuple[ssl.SSLContext, ssl.SSLContext]:
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "aidn-test-ca")])
    ca_certificate = (
        x509.CertificateBuilder()
        .subject_name(ca_subject)
        .issuer_name(ca_subject)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc) - timedelta(minutes=1))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
        .add_extension(
            x509.KeyUsage(
                digital_signature=False,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )
    ca_path = tmp_path / "ca.pem"
    ca_path.write_bytes(ca_certificate.public_bytes(serialization.Encoding.PEM))
    server_certificate, server_key = _write_certificate_pair(
        tmp_path, "server", ca_key, ca_certificate, server=True
    )
    client_certificate, client_key = _write_certificate_pair(
        tmp_path, "client", ca_key, ca_certificate, server=False
    )

    server_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    server_context.minimum_version = ssl.TLSVersion.TLSv1_2
    server_context.load_cert_chain(server_certificate, server_key)
    server_context.load_verify_locations(cafile=str(ca_path))
    server_context.verify_mode = ssl.CERT_REQUIRED

    client_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=str(ca_path))
    client_context.minimum_version = ssl.TLSVersion.TLSv1_2
    client_context.load_cert_chain(client_certificate, client_key)
    return server_context, client_context


def test_remote_tls_routes_network_messages_with_mutual_tls(tmp_path) -> None:
    server_context, client_context = _tls_contexts(tmp_path)
    received: list[NetworkMessage] = []
    listener = TlsRuntimeListener(
        host="127.0.0.1",
        port=0,
        server_context=server_context,
        ingress=lambda message: received.append(message) or {"accepted": message.message_id},
    )
    listener.start()
    try:
        response = TlsRuntimeClient(
            host=listener.host,
            port=listener.port,
            client_context=client_context,
            server_hostname="localhost",
        ).send(_message())
    finally:
        listener.stop()

    assert response == {"ok": True, "result": {"accepted": "remote-tls-message-1"}}
    assert [message.message_id for message in received] == ["remote-tls-message-1"]


def test_remote_tls_listener_requires_client_certificates() -> None:
    insecure_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)

    with pytest.raises(ValueError, match="require client certificates"):
        TlsRuntimeListener(
            host="127.0.0.1",
            port=0,
            server_context=insecure_context,
            ingress=lambda message: message,
        )
