import json
from typing import Protocol

from aidn_hypervisor.validation.models import ValidationReportStorageReceipt

try:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
        Ed25519PublicKey,
    )

    _ED25519_AVAILABLE = True
except Exception:  # pragma: no cover - dependency is optional for import safety
    Ed25519PrivateKey = None
    Ed25519PublicKey = None
    InvalidSignature = Exception
    _ED25519_AVAILABLE = False


def storage_receipt_signing_payload(receipt: ValidationReportStorageReceipt) -> bytes:
    payload = receipt.model_dump(mode="json", exclude={"endpoint_signature"})
    return json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


class ValidationReportCustodySigner(Protocol):
    @property
    def public_key(self) -> str: ...

    def sign(self, payload: bytes) -> str: ...


class Ed25519ValidationReportCustodySigner:
    def __init__(self, private_key_hex: str) -> None:
        if not _ED25519_AVAILABLE:
            raise RuntimeError("Ed25519 support is unavailable")
        try:
            self._private_key = Ed25519PrivateKey.from_private_bytes(
                bytes.fromhex(private_key_hex)
            )
        except ValueError as error:
            raise ValueError("Custody signing key must be 32 bytes of hex") from error

    @property
    def public_key(self) -> str:
        return f"ed25519:{self._private_key.public_key().public_bytes_raw().hex()}"

    def sign(self, payload: bytes) -> str:
        return f"ed25519:{self._private_key.sign(payload).hex()}"


def verify_storage_receipt(receipt: ValidationReportStorageReceipt) -> None:
    if not _ED25519_AVAILABLE:
        raise RuntimeError("Ed25519 support is unavailable")
    if not receipt.endpoint_public_key.startswith("ed25519:"):
        raise ValueError("Endpoint public key must use ed25519:<32-byte hex> form")
    if not receipt.endpoint_signature.startswith("ed25519:"):
        raise ValueError("Endpoint signature must use ed25519:<64-byte hex> form")
    try:
        public_key = Ed25519PublicKey.from_public_bytes(
            bytes.fromhex(receipt.endpoint_public_key.removeprefix("ed25519:"))
        )
        public_key.verify(
            bytes.fromhex(receipt.endpoint_signature.removeprefix("ed25519:")),
            storage_receipt_signing_payload(receipt),
        )
    except (ValueError, InvalidSignature) as error:
        raise ValueError("Validation report storage receipt signature is invalid") from error
