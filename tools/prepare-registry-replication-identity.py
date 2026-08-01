#!/usr/bin/env python3
"""Provision persistent, operator-local Registry replication testnet identity.

Each host generates its own signing key, CA, and mTLS certificate. Only the
public peer bundle is intended for exchange. This tool is for a controlled
testnet; production deployments should inject the master key from a KMS.
"""

from __future__ import annotations

import argparse
import base64
import ipaddress
import json
import os
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from aidn_hypervisor.registry_service import RegistryService
from aidn_hypervisor.secrets import FileSecretManager


def _write(path: Path, value: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)
    os.chmod(path, mode)


def _write_json(path: Path, value: dict) -> None:
    _write(path, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode())


def _master_key(root: Path) -> bytes:
    path = root / "master-key.b64"
    if path.exists():
        return base64.b64decode(path.read_text(encoding="ascii").strip(), validate=True)
    key = secrets.token_bytes(32)
    _write(path, (base64.b64encode(key).decode("ascii") + "\n").encode())
    return key


def _public_key(private_key: ed25519.Ed25519PrivateKey) -> str:
    return "ed25519:" + private_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    ).hex()


def _name(common_name: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])


def _san(host: str) -> x509.SubjectAlternativeName:
    try:
        value = x509.IPAddress(ipaddress.ip_address(host))
    except ValueError:
        value = x509.DNSName(host)
    return x509.SubjectAlternativeName([value])


def _make_identity(peer_id: str, host: str) -> tuple[bytes, bytes, bytes, bytes, str]:
    now = datetime.now(UTC)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_certificate = (
        x509.CertificateBuilder()
        .subject_name(_name(f"AiDN Registry Testnet CA {peer_id}"))
        .issuer_name(_name(f"AiDN Registry Testnet CA {peer_id}"))
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=1), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    leaf_certificate = (
        x509.CertificateBuilder()
        .subject_name(_name(peer_id))
        .issuer_name(ca_certificate.subject)
        .public_key(leaf_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=825))
        .add_extension(_san(host), critical=False)
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH, ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    signing_key = ed25519.Ed25519PrivateKey.generate()
    encode = serialization.Encoding.PEM
    ca_bytes = ca_certificate.public_bytes(encode)
    certificate_bytes = leaf_certificate.public_bytes(encode)
    private_bytes = leaf_key.private_bytes(
        encode, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    signing_bytes = signing_key.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
    )
    return ca_bytes, certificate_bytes, private_bytes, signing_bytes, _public_key(signing_key)


def _tls(peer_id: str) -> dict[str, str]:
    return {
        "certificate_handle": f"secret://registry/{peer_id}/certificate",
        "private_key_handle": f"secret://registry/{peer_id}/private-key",
        "certificate_authority_handle": f"secret://registry/{peer_id}/ca-bundle",
    }


def _load_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def init(args: argparse.Namespace) -> None:
    root = args.root.resolve()
    config_path = root / "registry-replication.json"
    bundle_path = root / "public-peer.json"
    if config_path.exists() and not args.force:
        raise ValueError(f"identity already exists at {root}; use --force only to replace it")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    master_key = _master_key(root)
    manager = FileSecretManager(path=root / "secrets.json", master_key=master_key)
    ca, certificate, private_key, signing_key, public_key = _make_identity(args.peer_id, args.host)
    handle_prefix = f"secret://registry/{args.peer_id}"
    manager.put(handle=f"{handle_prefix}/ca-bundle", value=ca)
    manager.put(handle=f"{handle_prefix}/certificate", value=certificate)
    manager.put(handle=f"{handle_prefix}/private-key", value=private_key)
    manager.put(handle=f"{handle_prefix}/ed25519", value=signing_key)
    tls = _tls(args.peer_id)
    config = {
        "local_peer_id": args.peer_id,
        "signing_key_handle": f"{handle_prefix}/ed25519",
        "listener": {"host": "0.0.0.0", "port": args.port, "tls": tls},
        "outbound_peers": [],
        "network_id": args.network_id,
        "chain_id": args.chain_id,
        "network_revision": args.network_revision,
    }
    bundle = {
        "peer_id": args.peer_id,
        "host": args.host,
        "port": args.port,
        "public_key": public_key,
        "ca_certificate_pem": ca.decode("ascii"),
        "created_at": datetime.now(UTC).isoformat(),
    }
    _write_json(config_path, config)
    _write_json(bundle_path, bundle)
    print(json.dumps({"status": "ok", "config": str(config_path), "public_bundle": str(bundle_path), "peer_id": args.peer_id}, sort_keys=True))


def add_peer(args: argparse.Namespace) -> None:
    root = args.root.resolve()
    config_path = root / "registry-replication.json"
    if not config_path.exists():
        raise ValueError("local identity is not initialized")
    bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
    required = {"peer_id", "host", "port", "public_key", "ca_certificate_pem"}
    if not required.issubset(bundle):
        raise ValueError("peer bundle is incomplete")
    config = _load_config(config_path)
    local_peer_id = str(config["local_peer_id"])
    manager = FileSecretManager(path=root / "secrets.json", master_key=_master_key(root))
    ca_handle = _tls(local_peer_id)["certificate_authority_handle"]
    current_ca = manager.get(ca_handle)
    remote_ca = str(bundle["ca_certificate_pem"]).encode("ascii")
    if remote_ca not in current_ca:
        manager.put(handle=ca_handle, value=current_ca.rstrip() + b"\n" + remote_ca)
    tls = _tls(local_peer_id)
    peers = [peer for peer in config.get("outbound_peers", []) if peer.get("peer_id") != bundle["peer_id"]]
    peers.append({"peer_id": bundle["peer_id"], "host": bundle["host"], "port": int(bundle["port"]), "tls": tls})
    config["outbound_peers"] = peers
    _write_json(config_path, config)
    snapshot = args.registry_snapshot or root / "registry-objects.json"
    registry = RegistryService(snapshot_path=snapshot)
    registry.upsert_replication_peer(peer_id=str(bundle["peer_id"]), public_key=str(bundle["public_key"]))
    print(json.dumps({"status": "ok", "config": str(config_path), "peer_id": bundle["peer_id"], "registry_snapshot": str(snapshot)}, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    init_parser = subs.add_parser("init")
    init_parser.add_argument("--root", type=Path, required=True)
    init_parser.add_argument("--peer-id", required=True)
    init_parser.add_argument("--host", required=True)
    init_parser.add_argument("--port", type=int, default=9444)
    init_parser.add_argument("--network-id", default="aidn")
    init_parser.add_argument("--chain-id", default="aidn-testnet-1")
    init_parser.add_argument("--network-revision", default="1.0")
    init_parser.add_argument("--force", action="store_true")
    init_parser.set_defaults(handler=init)
    add_parser = subs.add_parser("add-peer")
    add_parser.add_argument("--root", type=Path, required=True)
    add_parser.add_argument("--bundle", type=Path, required=True)
    add_parser.add_argument("--registry-snapshot", type=Path)
    add_parser.set_defaults(handler=add_peer)
    args = parser.parse_args()
    try:
        args.handler(args)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
