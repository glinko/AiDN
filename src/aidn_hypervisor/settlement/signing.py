import json

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from aidn_hypervisor.settlement.models import SessionSettlementAcceptance


def settlement_acceptance_signing_payload(
    acceptance: SessionSettlementAcceptance,
) -> bytes:
    """Create the stable consumer-authorized settlement acceptance payload."""
    payload = acceptance.model_dump(mode="json", exclude={"consumer_signature", "acceptance_hash"})
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )


def verify_settlement_acceptance(
    acceptance: SessionSettlementAcceptance,
    *,
    consumer_public_key: str,
) -> None:
    if not consumer_public_key.startswith("ed25519:"):
        raise ValueError("Consumer public key must use ed25519:<32-byte hex> form")
    if not acceptance.consumer_signature.startswith("ed25519:"):
        raise ValueError("Consumer signature must use ed25519:<64-byte hex> form")
    try:
        public_key = Ed25519PublicKey.from_public_bytes(
            bytes.fromhex(consumer_public_key.removeprefix("ed25519:"))
        )
        public_key.verify(
            bytes.fromhex(acceptance.consumer_signature.removeprefix("ed25519:")),
            settlement_acceptance_signing_payload(acceptance),
        )
    except (ValueError, InvalidSignature) as error:
        raise ValueError("Consumer Settlement Acceptance signature is invalid") from error
