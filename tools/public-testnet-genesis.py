#!/usr/bin/env python3
"""Run the public-only part of a four-validator CometBFT genesis ceremony.

This tool never reads or moves a validator private key.  Each validator first
uses ``extract`` locally to publish a small public manifest.  A release
coordinator then uses ``build`` with those four manifests to produce the one
immutable ``genesis.json`` shared by the founding validators.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _write_new(path: Path, payload: bytes) -> None:
    if path.exists():
        raise ValueError(f"refusing to replace existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _public_key(value: str) -> bytes:
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, base64.binascii.Error) as error:
        raise ValueError("CometBFT validator public key is not base64") from error
    if len(decoded) != 32:
        raise ValueError("CometBFT validator public key must be exactly 32 bytes")
    return decoded


def _address(key: bytes) -> str:
    return hashlib.sha256(key).digest()[:20].hex().upper()


def _identifier(value: str, *, label: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"{label} contains unsupported characters")
    return value


def _rfc3339(value: str) -> str:
    if not value.endswith("Z"):
        raise ValueError("genesis time must be UTC RFC3339 ending in Z")
    try:
        parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError as error:
        raise ValueError("genesis time must be UTC RFC3339") from error
    if parsed.tzinfo != UTC:
        raise ValueError("genesis time must be UTC")
    return parsed.isoformat(timespec="seconds").replace("+00:00", "Z")


def _canonical_json(document: Any) -> bytes:
    return json.dumps(document, indent=2, sort_keys=True).encode("utf-8") + b"\n"


def extract(args: argparse.Namespace) -> int:
    validator_id = _identifier(args.validator_id, label="validator id")
    source = json.loads(args.validator_key.read_text(encoding="utf-8"))
    key_value = source.get("pub_key", {}).get("value") if isinstance(source, dict) else None
    if not isinstance(key_value, str):
        raise ValueError("priv_validator_key.json has no public pub_key.value")
    key = _public_key(key_value)
    declared_address = source.get("address")
    address = _address(key)
    if isinstance(declared_address, str) and declared_address and declared_address.upper() != address:
        raise ValueError("validator key address does not match its public key")
    manifest = {
        "schema_version": "aidn.public-validator-genesis-manifest.v1",
        "validator_id": validator_id,
        "consensus_address": address,
        "consensus_public_key": "ed25519:" + key_value,
    }
    _write_new(args.output, _canonical_json(manifest))
    print(json.dumps({"status": "EXTRACTED", **manifest, "output": str(args.output)}, sort_keys=True))
    return 0


def _load_manifest(path: Path) -> dict[str, str]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("schema_version") != "aidn.public-validator-genesis-manifest.v1":
        raise ValueError(f"invalid validator manifest: {path}")
    validator_id = document.get("validator_id")
    public_key = document.get("consensus_public_key")
    address = document.get("consensus_address")
    if not all(isinstance(value, str) for value in (validator_id, public_key, address)):
        raise ValueError(f"invalid validator manifest: {path}")
    _identifier(validator_id, label="validator id")
    if not public_key.startswith("ed25519:"):
        raise ValueError(f"invalid validator public key: {path}")
    key = _public_key(public_key.removeprefix("ed25519:"))
    if address.upper() != _address(key):
        raise ValueError(f"validator manifest address mismatch: {path}")
    return {
        "validator_id": validator_id,
        "consensus_address": _address(key),
        "consensus_public_key": public_key,
    }


def build(args: argparse.Namespace) -> int:
    chain_id = _identifier(args.chain_id, label="chain id")
    genesis_time = _rfc3339(args.genesis_time)
    if len(args.validator_manifest) < 4:
        raise ValueError("a public testnet genesis requires at least four validator manifests")
    manifests = [_load_manifest(path) for path in args.validator_manifest]
    if len({item["validator_id"] for item in manifests}) != len(manifests):
        raise ValueError("validator IDs must be unique")
    if len({item["consensus_public_key"] for item in manifests}) != len(manifests):
        raise ValueError("validator consensus public keys must be unique")
    validators = [
        {
            "address": item["consensus_address"],
            "name": item["validator_id"],
            "power": "1",
            "pub_key": {
                "type": "tendermint/PubKeyEd25519",
                "value": item["consensus_public_key"].removeprefix("ed25519:"),
            },
        }
        for item in sorted(manifests, key=lambda item: item["validator_id"])
    ]
    genesis = {
        "genesis_time": genesis_time,
        "chain_id": chain_id,
        "initial_height": "1",
        "consensus_params": {
            "block": {"max_bytes": "22020096", "max_gas": "-1"},
            "evidence": {
                "max_age_num_blocks": "100000",
                "max_age_duration": "172800000000000",
                "max_bytes": "1048576",
            },
            "validator": {"pub_key_types": ["ed25519"]},
            "version": {},
        },
        "validators": validators,
        "app_hash": "",
        "app_state": {},
    }
    payload = _canonical_json(genesis)
    _write_new(args.output, payload)
    print(
        json.dumps(
            {
                "status": "BUILT",
                "chain_id": chain_id,
                "validator_count": len(validators),
                "genesis_sha256": "sha256:" + hashlib.sha256(payload).hexdigest(),
                "output": str(args.output),
            },
            sort_keys=True,
        )
    )
    return 0


def install(args: argparse.Namespace) -> int:
    """Install the ceremony Genesis only before the local chain has started."""

    if args.confirm_unstarted != "I_CONFIRM_NO_BLOCK_HAS_BEEN_PRODUCED":
        raise ValueError("--confirm-unstarted acknowledgement is required")
    source = args.genesis.resolve()
    if not source.is_file() or source.is_symlink():
        raise ValueError("--genesis must be a readable regular file")
    # Validate the document before modifying the local Comet home.
    document = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("chain_id"), str):
        raise ValueError("--genesis is not a CometBFT genesis document")
    home = args.comet_home.resolve()
    target = home / "config" / "genesis.json"
    private_key = home / "config" / "priv_validator_key.json"
    if not target.is_file() or not private_key.is_file():
        raise ValueError("CometBFT home has not been initialized")
    # These are created only after Comet begins producing or replaying chain
    # state.  Refuse to turn the founding ceremony into an accidental reset.
    started_markers = (
        home / "data" / "blockstore.db",
        home / "data" / "state.db",
        home / "data" / "cs.wal",
    )
    if any(marker.exists() for marker in started_markers):
        raise ValueError("refusing Genesis replacement after CometBFT state exists")
    payload = source.read_bytes()
    backup = target.with_name("genesis.initial-local.json")
    if backup.exists():
        raise ValueError("ceremony Genesis was already installed for this Comet home")
    os.replace(target, backup)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    digest = "sha256:" + hashlib.sha256(payload).hexdigest()
    (home / "config" / "aidn-genesis.sha256").write_text(digest + "\n", encoding="ascii")
    print(
        json.dumps(
            {
                "status": "INSTALLED",
                "chain_id": document["chain_id"],
                "genesis_sha256": digest,
                "comet_home": str(home),
            },
            sort_keys=True,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    extract_parser = commands.add_parser("extract", help="export public validator metadata")
    extract_parser.add_argument("--validator-id", required=True)
    extract_parser.add_argument("--validator-key", required=True, type=Path)
    extract_parser.add_argument("--output", required=True, type=Path)
    extract_parser.set_defaults(handler=extract)
    build_parser = commands.add_parser("build", help="build the shared immutable genesis")
    build_parser.add_argument("--chain-id", required=True)
    build_parser.add_argument("--genesis-time", required=True)
    build_parser.add_argument("--validator-manifest", required=True, type=Path, action="append")
    build_parser.add_argument("--output", required=True, type=Path)
    build_parser.set_defaults(handler=build)
    install_parser = commands.add_parser("install", help="install ceremony Genesis before first start")
    install_parser.add_argument("--genesis", required=True, type=Path)
    install_parser.add_argument("--comet-home", required=True, type=Path)
    install_parser.add_argument(
        "--confirm-unstarted",
        required=True,
        help="must be exactly I_CONFIRM_NO_BLOCK_HAS_BEEN_PRODUCED",
    )
    install_parser.set_defaults(handler=install)
    args = parser.parse_args()
    return args.handler(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "BLOCKED", "error": str(error)}, sort_keys=True))
        raise SystemExit(2) from error
