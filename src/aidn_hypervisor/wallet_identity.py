import json
from datetime import datetime, timezone

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, Field


class WalletIdentity(BaseModel):
    wallet_id: str = Field(min_length=1)
    public_key: str = Field(min_length=1)
    registered_at: str = Field(min_length=1)
    registration_nonce: str = Field(min_length=1)


def wallet_identity_registration_payload(
    *, wallet_id: str, public_key: str, registration_nonce: str
) -> bytes:
    return json.dumps(
        {
            "domain": "aidn.wallet-identity.registration.v1",
            "wallet_id": wallet_id,
            "public_key": public_key,
            "registration_nonce": registration_nonce,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def verify_wallet_identity_registration(
    *, wallet_id: str, public_key: str, registration_nonce: str, signature: str
) -> WalletIdentity:
    if not public_key.startswith("ed25519:") or not signature.startswith("ed25519:"):
        raise ValueError("Wallet identity requires ed25519 public key and signature")
    try:
        key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key.removeprefix("ed25519:")))
        key.verify(
            bytes.fromhex(signature.removeprefix("ed25519:")),
            wallet_identity_registration_payload(
                wallet_id=wallet_id,
                public_key=public_key,
                registration_nonce=registration_nonce,
            ),
        )
    except (ValueError, InvalidSignature) as error:
        raise ValueError("Wallet identity registration signature is invalid") from error
    return WalletIdentity(
        wallet_id=wallet_id,
        public_key=public_key,
        registered_at=datetime.now(timezone.utc).isoformat(),
        registration_nonce=registration_nonce,
    )
