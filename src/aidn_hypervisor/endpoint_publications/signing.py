"""Ed25519 signing helpers for public Endpoint configuration records."""

from __future__ import annotations

import json

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


def publication_signing_payload(payload: dict) -> bytes:
    """Serialize a publication record under its dedicated signature domain."""
    return json.dumps(
        {
            "domain": "aidn.endpoint-configuration-publication.v1",
            "publication": payload,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def public_key_for_private_key(private_key: str) -> str:
    raw_private_key = _private_key_bytes(private_key)
    public_key = Ed25519PrivateKey.from_private_bytes(raw_private_key).public_key()
    return "ed25519:" + public_key.public_bytes(Encoding.Raw, PublicFormat.Raw).hex()


def sign_publication_payload(*, private_key: str, payload: dict) -> str:
    signature = Ed25519PrivateKey.from_private_bytes(
        _private_key_bytes(private_key)
    ).sign(publication_signing_payload(payload))
    return "ed25519:" + signature.hex()


def sign_consensus_bytes(*, private_key: str, payload: bytes) -> str:
    """Sign a canonical Ledger envelope without changing its domain."""
    signature = Ed25519PrivateKey.from_private_bytes(
        _private_key_bytes(private_key)
    ).sign(payload)
    return "ed25519:" + signature.hex()


def verify_publication_signature(
    *, public_key: str, signature: str, payload: dict
) -> None:
    if not public_key.startswith("ed25519:") or not signature.startswith("ed25519:"):
        raise ValueError("Endpoint publication requires an Ed25519 key and signature")
    try:
        key = Ed25519PublicKey.from_public_bytes(
            bytes.fromhex(public_key.removeprefix("ed25519:"))
        )
        key.verify(
            bytes.fromhex(signature.removeprefix("ed25519:")),
            publication_signing_payload(payload),
        )
    except (ValueError, InvalidSignature) as error:
        raise ValueError("Endpoint publication signature is invalid") from error


def _private_key_bytes(private_key: str) -> bytes:
    if not private_key.startswith("ed25519:"):
        raise ValueError("Endpoint publication private key must use ed25519:<32-byte hex>")
    try:
        raw_private_key = bytes.fromhex(private_key.removeprefix("ed25519:"))
    except ValueError as error:
        raise ValueError(
            "Endpoint publication private key must use ed25519:<32-byte hex>"
        ) from error
    if len(raw_private_key) != 32:
        raise ValueError("Endpoint publication private key must be 32 bytes")
    return raw_private_key
