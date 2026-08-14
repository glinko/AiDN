"""External Wallet key loading for RFC-0068 contribution evidence.

Contribution Wallet keys are operator secrets.  This module deliberately only
loads them from an external path, derives the public key, and fails closed when
the key does not match the Wallet identity supplied by the caller.
"""

from __future__ import annotations

from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def load_ed25519_private_key(path: Path) -> Ed25519PrivateKey:
    """Load a PEM or 32-byte hex Ed25519 seed without exposing its contents."""

    raw = path.expanduser().resolve().read_bytes()
    if raw.startswith(b"-----BEGIN"):
        key = serialization.load_pem_private_key(raw, password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("contributor Wallet private key must be Ed25519")
        return key

    value = raw.decode("ascii").strip()
    if value.startswith("ed25519:"):
        value = value.removeprefix("ed25519:")
    try:
        seed = bytes.fromhex(value)
    except ValueError as error:
        raise ValueError(
            "contributor Wallet private key must be a PEM key or 32-byte hex seed"
        ) from error
    if len(seed) != 32:
        raise ValueError("contributor Wallet private key hex seed must contain 32 bytes")
    return Ed25519PrivateKey.from_private_bytes(seed)


def public_key_for_private_key(private_key: Ed25519PrivateKey) -> str:
    """Return the canonical public-key representation used by RFC-0068."""

    return "ed25519:" + private_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    ).hex()


def load_verified_contributor_wallet_key(
    path: Path,
    *,
    wallet_address: str,
    expected_public_key: str,
) -> tuple[Ed25519PrivateKey, str]:
    """Load a Wallet key and verify it belongs to the declared Wallet identity."""

    if not wallet_address.strip():
        raise ValueError("contributor Wallet address is required")
    if not expected_public_key.startswith("ed25519:"):
        raise ValueError("contributor Wallet public key must use ed25519:<hex>")
    private_key = load_ed25519_private_key(path)
    public_key = public_key_for_private_key(private_key)
    if public_key != expected_public_key:
        raise ValueError("CONTRIBUTOR_WALLET_KEY_MISMATCH")
    return private_key, public_key


__all__ = [
    "load_ed25519_private_key",
    "load_verified_contributor_wallet_key",
    "public_key_for_private_key",
]
