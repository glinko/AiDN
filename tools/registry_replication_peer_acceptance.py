#!/usr/bin/env python3
"""Cross-host, test-only Registry replication peer acceptance harness.

The server generates disposable mTLS and Ed25519 material into a private state
directory. Its client bootstrap bundle is intended only for an authenticated
test transfer such as SCP over SSH; never use it for an operator deployment.
"""

from __future__ import annotations

import argparse
import base64
import ipaddress
import json
import os
import signal
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

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


def _wait_until(predicate, *, timeout_seconds: float, failure_message: str | None = None) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise RuntimeError(failure_message or "acceptance condition was not reached before timeout")


def _encode(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _decode(value: str) -> bytes:
    return base64.b64decode(value.encode("ascii"), validate=True)


def _make_certificate(common_name: str, *, ca_key, ca_certificate) -> tuple[bytes, bytes]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_certificate.subject)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC) - timedelta(minutes=1))
        .not_valid_after(datetime.now(UTC) + timedelta(hours=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName(common_name),
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                ]
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
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(private_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
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


def _new_identity() -> tuple[bytes, str]:
    private_key = ed25519.Ed25519PrivateKey.generate()
    raw = private_key.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    public_key = "ed25519:" + private_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    ).hex()
    return raw, public_key


def _store_from_material(state_dir: Path, prefix: str, material: dict[str, bytes]) -> FileSecretManager:
    manager = FileSecretManager(
        path=state_dir / f"{prefix}-secrets.json",
        master_key=os.urandom(32),
    )
    for name, value in material.items():
        manager.put(handle=f"secret://acceptance/{prefix}/{name}", value=value)
    return manager


def _tls(prefix: str) -> dict[str, str]:
    return {
        "certificate_handle": f"secret://acceptance/{prefix}/certificate",
        "private_key_handle": f"secret://acceptance/{prefix}/private-key",
        "certificate_authority_handle": f"secret://acceptance/{prefix}/ca",
    }


def _server_config(port: int) -> RegistryReplicationDeploymentConfig:
    return RegistryReplicationDeploymentConfig.model_validate(
        {
            "local_peer_id": "registry-server",
            "signing_key_handle": "secret://acceptance/server/signing-key",
            "listener": {"host": "127.0.0.1", "port": port, "tls": _tls("server")},
            "poll_interval_seconds": 0.01,
        }
    )


def _client_config(host: str, port: int) -> RegistryReplicationDeploymentConfig:
    return RegistryReplicationDeploymentConfig.model_validate(
        {
            "local_peer_id": "registry-client",
            "signing_key_handle": "secret://acceptance/client/signing-key",
            "outbound_peers": [
                {
                    "peer_id": "registry-server",
                    "host": host,
                    "port": port,
                    "tls": _tls("client"),
                }
            ],
            "poll_interval_seconds": 0.01,
        }
    )


def run_server(*, state_dir: Path, port: int) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(state_dir, 0o700)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "aidn-acceptance-ca")])
    ca_certificate = (
        x509.CertificateBuilder()
        .subject_name(ca_subject)
        .issuer_name(ca_subject)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC) - timedelta(minutes=1))
        .not_valid_after(datetime.now(UTC) + timedelta(hours=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    ca = ca_certificate.public_bytes(serialization.Encoding.PEM)
    server_certificate, server_private_key = _make_certificate(
        "registry-server", ca_key=ca_key, ca_certificate=ca_certificate
    )
    client_certificate, client_private_key = _make_certificate(
        "registry-client", ca_key=ca_key, ca_certificate=ca_certificate
    )
    server_signing_key, server_public_key = _new_identity()
    client_signing_key, client_public_key = _new_identity()
    server_secrets = _store_from_material(
        state_dir,
        "server",
        {
            "signing-key": server_signing_key,
            "certificate": server_certificate,
            "private-key": server_private_key,
            "ca": ca,
        },
    )
    registry = RegistryService()
    registry.upsert_replication_peer(peer_id="registry-client", public_key=client_public_key)
    runtime = build_registry_replication_runtime(
        config=_server_config(port), registry_service=registry, secret_manager=server_secrets
    )
    assert runtime.replicator is not None
    object_id = "cross-host-registry-acceptance"
    runtime.replicator.store.put(
        RegistryObjectEnvelope.create(
            object_id=object_id,
            object_type="acceptance",
            payload={"object_id": object_id, "source": "registry-server"},
            created_epoch=1,
        )
    )
    bundle = {
        "server_public_key": server_public_key,
        "port": port,
        "object_id": object_id,
        "client_material": {
            "signing-key": _encode(client_signing_key),
            "certificate": _encode(client_certificate),
            "private-key": _encode(client_private_key),
            "ca": _encode(ca),
        },
    }
    bundle_path = state_dir / "client-bootstrap.json"
    bundle_path.write_text(json.dumps(bundle, sort_keys=True), encoding="utf-8")
    os.chmod(bundle_path, 0o600)
    runtime.start()
    print(json.dumps({"status": "ready", "bundle": str(bundle_path), "port": port}), flush=True)
    stopping = False
    status_requested = False

    def stop_handler(_signal, _frame) -> None:
        nonlocal stopping
        stopping = True

    def status_handler(_signal, _frame) -> None:
        nonlocal status_requested
        status_requested = True

    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)
    if hasattr(signal, "SIGUSR1"):
        signal.signal(signal.SIGUSR1, status_handler)
    try:
        while not stopping:
            if status_requested:
                status_requested = False
                print(json.dumps({"status": runtime.status()}, sort_keys=True), flush=True)
            time.sleep(0.2)
    finally:
        runtime.stop()


def run_client(
    *, bundle_path: Path, host: str, port: int, state_dir: Path, timeout_seconds: float
) -> dict:
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    material = {key: _decode(value) for key, value in bundle["client_material"].items()}
    secrets = _store_from_material(state_dir, "client", material)
    registry = RegistryService()
    registry.upsert_replication_peer(
        peer_id="registry-server", public_key=str(bundle["server_public_key"])
    )
    runtime = build_registry_replication_runtime(
        config=_client_config(host, port),
        registry_service=registry,
        secret_manager=secrets,
    )
    assert runtime.replicator is not None
    object_id = str(bundle["object_id"])
    try:
        runtime.start()
        _wait_until(
            lambda: runtime.status()["outbound_peers"][0]["authenticated"],
            timeout_seconds=timeout_seconds,
            failure_message=(
                "Registry peer authentication did not complete: "
                + json.dumps(runtime.status(), sort_keys=True)
            ),
        )
        runtime.replicator.build_inventory_request("registry-server")
        _wait_until(
            lambda: runtime.replicator is not None and runtime.replicator.store.has(object_id),
            timeout_seconds=timeout_seconds,
        )
        return {
            "status": "ok",
            "object_id": object_id,
            "outbound_peer": runtime.status()["outbound_peers"][0],
        }
    finally:
        runtime.stop()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("role", choices=("server", "client"))
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--port", type=int, default=9443)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--timeout", type=float, default=15)
    args = parser.parse_args()
    if args.role == "server":
        run_server(state_dir=args.state_dir, port=args.port)
        return
    if args.bundle is None:
        parser.error("client role requires --bundle")
    result = run_client(
        bundle_path=args.bundle,
        host=args.host,
        port=args.port,
        state_dir=args.state_dir,
        timeout_seconds=args.timeout,
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
