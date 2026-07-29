from __future__ import annotations

import ipaddress
import os
import socket
import time
from datetime import UTC, datetime, timedelta

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa
from cryptography.x509.oid import NameOID

from aidn_hypervisor.registry.deployment import (
    RegistryReplicationDeploymentConfig,
    build_registry_replication_runtime,
)
from aidn_hypervisor.registry.object_envelope import RegistryObjectEnvelope
from aidn_hypervisor.registry_service import RegistryService
from aidn_hypervisor.secrets import FileSecretManager


def _available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_until(predicate, *, timeout_seconds: float = 8.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition was not reached before timeout")


def _certificate_material(common_name: str, *, ca_key, ca_certificate) -> tuple[bytes, bytes]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_certificate.subject)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC) - timedelta(minutes=1))
        .not_valid_after(datetime.now(UTC) + timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName(common_name), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            ),
            critical=False,
        )
        .add_extension(
            x509.ExtendedKeyUsage(
                [
                    x509.oid.ExtendedKeyUsageOID.CLIENT_AUTH,
                    x509.oid.ExtendedKeyUsageOID.SERVER_AUTH,
                ]
            ),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    return (
        certificate.public_bytes(serialization.Encoding.PEM),
        private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
    )


def _make_secret_manager(tmp_path, *, prefix: str, certificate: bytes, private_key: bytes, ca: bytes):
    manager = FileSecretManager(
        path=tmp_path / f"{prefix}-secrets.json",
        master_key=os.urandom(32),
    )
    signing_key = ed25519.Ed25519PrivateKey.generate()
    raw_signing_key = signing_key.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    manager.put(handle=f"secret://{prefix}/signing-key", value=raw_signing_key)
    manager.put(handle=f"secret://{prefix}/certificate", value=certificate)
    manager.put(handle=f"secret://{prefix}/private-key", value=private_key)
    manager.put(handle=f"secret://{prefix}/ca", value=ca)
    public_key = "ed25519:" + signing_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    ).hex()
    return manager, public_key


def _config(*, peer_id: str, signing_prefix: str, port: int, listener: bool):
    tls = {
        "certificate_handle": f"secret://{signing_prefix}/certificate",
        "private_key_handle": f"secret://{signing_prefix}/private-key",
        "certificate_authority_handle": f"secret://{signing_prefix}/ca",
    }
    payload = {
        "local_peer_id": peer_id,
        "signing_key_handle": f"secret://{signing_prefix}/signing-key",
        "poll_interval_seconds": 0.01,
    }
    if listener:
        payload["listener"] = {"host": "127.0.0.1", "port": port, "tls": tls}
    else:
        payload["outbound_peers"] = [
            {"peer_id": "registry-server", "host": "127.0.0.1", "port": port, "tls": tls}
        ]
    return RegistryReplicationDeploymentConfig.model_validate(payload)


def test_mtls_runtime_replicates_an_object_between_independent_secret_stores(tmp_path) -> None:
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "aidn-test-ca")])
    ca_certificate = (
        x509.CertificateBuilder()
        .subject_name(ca_subject)
        .issuer_name(ca_subject)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC) - timedelta(minutes=1))
        .not_valid_after(datetime.now(UTC) + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    ca = ca_certificate.public_bytes(serialization.Encoding.PEM)
    server_certificate, server_private_key = _certificate_material(
        "registry-server", ca_key=ca_key, ca_certificate=ca_certificate
    )
    client_certificate, client_private_key = _certificate_material(
        "registry-client", ca_key=ca_key, ca_certificate=ca_certificate
    )
    server_secrets, server_public_key = _make_secret_manager(
        tmp_path,
        prefix="server",
        certificate=server_certificate,
        private_key=server_private_key,
        ca=ca,
    )
    client_secrets, client_public_key = _make_secret_manager(
        tmp_path,
        prefix="client",
        certificate=client_certificate,
        private_key=client_private_key,
        ca=ca,
    )
    server_registry = RegistryService()
    server_registry.upsert_replication_peer(
        peer_id="registry-client", public_key=client_public_key
    )
    client_registry = RegistryService()
    client_registry.upsert_replication_peer(
        peer_id="registry-server", public_key=server_public_key
    )
    port = _available_port()
    server_runtime = build_registry_replication_runtime(
        config=_config(
            peer_id="registry-server", signing_prefix="server", port=port, listener=True
        ),
        registry_service=server_registry,
        secret_manager=server_secrets,
    )
    client_runtime = build_registry_replication_runtime(
        config=_config(
            peer_id="registry-client", signing_prefix="client", port=port, listener=False
        ),
        registry_service=client_registry,
        secret_manager=client_secrets,
    )
    try:
        assert server_runtime.replicator is not None
        assert client_runtime.replicator is not None
        object_id = "registry-acceptance-object"
        server_runtime.replicator.store.put(
            RegistryObjectEnvelope.create(
                object_id=object_id,
                object_type="acceptance",
                payload={"object_id": object_id, "source": "registry-server"},
                created_epoch=1,
            )
        )
        server_runtime.start()
        client_runtime.start()
        _wait_until(
            lambda: client_runtime.status()["outbound_peers"][0]["authenticated"]
        )
        client_runtime.replicator.build_inventory_request("registry-server")
        try:
            _wait_until(lambda: client_runtime.replicator.store.has(object_id))
        except AssertionError as exc:
            raise AssertionError(
                f"replication did not complete: client={client_runtime.status()}, "
                f"server={server_runtime.status()}"
            ) from exc

        assert client_runtime.replicator.store.get(object_id) is not None
        assert server_runtime.status()["inbound_active_peer_ids"] == ["registry-client"]
    finally:
        client_runtime.stop()
        server_runtime.stop()
