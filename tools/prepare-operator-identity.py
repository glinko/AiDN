#!/usr/bin/env python3
"""Create or verify the local identity of one AiDN operator.

The private Ed25519 seed is generated on the operator host and never printed
or copied into a public bundle.  The JSON files contain only identity and
configuration metadata; the raw key remains mode 0600 in the same workspace.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

_IDENTIFIER = re.compile(r"^[A-Za-z0-9._-]+$")


def _write(path: Path, payload: bytes, *, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    os.chmod(path, mode)


def _public_key(private_key: Ed25519PrivateKey) -> str:
    raw = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return "ed25519:" + raw.hex()


def _load_key(path: Path) -> Ed25519PrivateKey:
    payload = path.read_bytes()
    if len(payload) != 32:
        raise ValueError("operator identity key must contain exactly 32 bytes")
    return Ed25519PrivateKey.from_private_bytes(payload)


def _validate_identifier(value: str, label: str) -> str:
    if not value or not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"{label} contains unsupported characters")
    return value


def init(args: argparse.Namespace) -> None:
    root = args.root.expanduser().resolve()
    operator_id = _validate_identifier(args.operator_id, "operator_id")
    peer_id = _validate_identifier(args.peer_id or operator_id, "peer_id")
    control_group_id = _validate_identifier(
        args.control_group_id or f"control-group-{operator_id}",
        "control_group_id",
    )
    if not args.host.strip():
        raise ValueError("host must not be empty")

    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(root, 0o700)
    key_path = root / "operator-attestation-key.raw"
    identity_path = root / "operator-identity.json"
    public_path = root / "operator-public-identity.json"

    if key_path.exists() or identity_path.exists() or public_path.exists():
        if not (key_path.is_file() and identity_path.is_file() and public_path.is_file()):
            raise ValueError(f"operator identity workspace is incomplete: {root}")
        private_key = _load_key(key_path)
        identity = json.loads(identity_path.read_text(encoding="utf-8"))
        if identity.get("operator_id") != operator_id or identity.get("peer_id") != peer_id:
            raise ValueError("existing operator identity belongs to another operator")
        expected_public_key = _public_key(private_key)
        if identity.get("operator_public_key") != expected_public_key:
            raise ValueError("existing operator identity key does not match its metadata")
        print(
            json.dumps(
                {
                    "status": "reused",
                    "operator_id": operator_id,
                    "peer_id": peer_id,
                    "control_group_id": identity.get("control_group_id"),
                    "operator_public_key": expected_public_key,
                    "identity": str(identity_path),
                    "public_identity": str(public_path),
                },
                sort_keys=True,
            )
        )
        return

    private_key = Ed25519PrivateKey.generate()
    public_key = _public_key(private_key)
    generated_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    identity = {
        "identity_version": 1,
        "operator_id": operator_id,
        "peer_id": peer_id,
        "control_group_id": control_group_id,
        "host": args.host,
        "network_id": args.network_id,
        "chain_id": args.chain_id,
        "network_revision": args.network_revision,
        "operator_public_key": public_key,
        "independence_status": "OUT_OF_BAND_DECLARED",
        "status": "READY_FOR_OUT_OF_BAND_ATTESTATION",
        "created_at": generated_at,
        "attestation_key_path": str(key_path),
    }
    public_identity = {
        key: value
        for key, value in identity.items()
        if key not in {"attestation_key_path", "status"}
    }
    _write(
        key_path,
        private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        ),
        mode=0o600,
    )
    encoded_identity = (json.dumps(identity, indent=2, sort_keys=True) + "\n").encode("utf-8")
    encoded_public = (json.dumps(public_identity, indent=2, sort_keys=True) + "\n").encode("utf-8")
    _write(identity_path, encoded_identity, mode=0o600)
    _write(public_path, encoded_public, mode=0o644)
    print(
        json.dumps(
            {
                "status": "created",
                "operator_id": operator_id,
                "peer_id": peer_id,
                "control_group_id": control_group_id,
                "operator_public_key": public_key,
                "identity": str(identity_path),
                "public_identity": str(public_path),
            },
            sort_keys=True,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    init_parser = subcommands.add_parser("init", help="create or verify a local operator identity")
    init_parser.add_argument("--root", type=Path, required=True)
    init_parser.add_argument("--operator-id", required=True)
    init_parser.add_argument("--peer-id")
    init_parser.add_argument("--control-group-id")
    init_parser.add_argument("--host", required=True)
    init_parser.add_argument("--network-id", default="aidn")
    init_parser.add_argument("--chain-id", default="aidn-testnet-1")
    init_parser.add_argument("--network-revision", default="1.0")
    init_parser.set_defaults(handler=init)
    args = parser.parse_args()
    try:
        args.handler(args)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
