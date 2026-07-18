import base64

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from aidn_hypervisor.validation.models import (
    ValidationReportTransferEnvelope,
    canonical_validation_hash,
)


def transfer_envelope_signing_payload(
    envelope: ValidationReportTransferEnvelope,
) -> bytes:
    payload = envelope.model_dump(mode="json")
    payload.pop("validator_signature", None)
    return canonical_validation_hash(payload).encode("ascii")


class Ed25519ValidationReportTransferSigner:
    def __init__(self, private_key_hex: str) -> None:
        private_key = bytes.fromhex(private_key_hex)
        if len(private_key) != 32:
            raise ValueError("Ed25519 transfer private key must be 32 bytes")
        self._private_key = Ed25519PrivateKey.from_private_bytes(private_key)

    @property
    def public_key(self) -> str:
        raw_key = self._private_key.public_key().public_bytes_raw()
        return f"ed25519:{base64.b64encode(raw_key).decode('ascii')}"

    def sign(self, payload: bytes) -> str:
        signature = self._private_key.sign(payload)
        return f"ed25519:{base64.b64encode(signature).decode('ascii')}"


def verify_report_transfer_envelope(
    envelope: ValidationReportTransferEnvelope,
) -> None:
    if envelope.validator_public_key is None and envelope.validator_signature is None:
        return
    if not envelope.validator_public_key or not envelope.validator_signature:
        raise ValueError("Validation report transfer signature is incomplete")
    key_type, encoded_key = envelope.validator_public_key.split(":", 1)
    signature_type, encoded_signature = envelope.validator_signature.split(":", 1)
    if key_type != "ed25519" or signature_type != "ed25519":
        raise ValueError("Validation report transfer requires ed25519 signature")
    try:
        public_key = Ed25519PublicKey.from_public_bytes(base64.b64decode(encoded_key))
        public_key.verify(
            base64.b64decode(encoded_signature),
            transfer_envelope_signing_payload(envelope),
        )
    except (InvalidSignature, ValueError) as exc:
        raise ValueError("Validation report transfer signature is invalid") from exc
