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


def _verify_ed25519_signature(
    *,
    public_key: str,
    signature: str,
    payload: bytes,
    required_message: str,
    invalid_message: str,
) -> None:
    if not public_key.startswith("ed25519:") or not signature.startswith("ed25519:"):
        raise ValueError(required_message)
    try:
        key = Ed25519PublicKey.from_public_bytes(
            bytes.fromhex(public_key.removeprefix("ed25519:"))
        )
        key.verify(bytes.fromhex(signature.removeprefix("ed25519:")), payload)
    except (ValueError, InvalidSignature) as error:
        raise ValueError(invalid_message) from error


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
    _verify_ed25519_signature(
        public_key=public_key,
        signature=signature,
        payload=wallet_identity_registration_payload(
            wallet_id=wallet_id,
            public_key=public_key,
            registration_nonce=registration_nonce,
        ),
        required_message="Wallet identity requires ed25519 public key and signature",
        invalid_message="Wallet identity registration signature is invalid",
    )
    return WalletIdentity(
        wallet_id=wallet_id,
        public_key=public_key,
        registered_at=datetime.now(timezone.utc).isoformat(),
        registration_nonce=registration_nonce,
    )


def session_open_authorization_payload(
    *, wallet_id: str, endpoint_id: str, endpoint_configuration_hash: str,
    deposit_q_atoms: int, fixed_price_q_atoms: int, network_fee_reserve_q_atoms: int,
    nonce: str, expires_at: str,
) -> bytes:
    return json.dumps({
        "domain": "aidn.session-open-authorization.v1", "wallet_id": wallet_id,
        "endpoint_id": endpoint_id, "endpoint_configuration_hash": endpoint_configuration_hash,
        "deposit_q_atoms": deposit_q_atoms, "fixed_price_q_atoms": fixed_price_q_atoms,
        "network_fee_reserve_q_atoms": network_fee_reserve_q_atoms, "nonce": nonce,
        "expires_at": expires_at,
    }, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")


def verify_session_open_authorization(*, public_key: str, signature: str, **payload: object) -> None:
    try:
        expires_at = datetime.fromisoformat(str(payload["expires_at"]))
        if expires_at <= datetime.now(timezone.utc):
            raise ValueError("Session-open authorization has expired")
    except (ValueError, InvalidSignature) as error:
        raise ValueError("Session-open authorization signature is invalid") from error
    _verify_ed25519_signature(
        public_key=public_key,
        signature=signature,
        payload=session_open_authorization_payload(**payload),
        required_message="Session-open authorization requires an Ed25519 signature",
        invalid_message="Session-open authorization signature is invalid",
    )


def wallet_identity_quorum_proposal_payload(
    *,
    wallet_id: str,
    chosen_object_id: str,
    chosen_payload_hash: str,
    proposer_node_id: str,
    eligible_voter_node_ids: list[str],
    quorum_threshold: int,
    operator_note: str | None,
) -> bytes:
    return json.dumps(
        {
            "domain": "aidn.wallet-identity.quorum-proposal.v1",
            "wallet_id": wallet_id,
            "chosen_object_id": chosen_object_id,
            "chosen_payload_hash": chosen_payload_hash,
            "proposer_node_id": proposer_node_id,
            "eligible_voter_node_ids": list(eligible_voter_node_ids),
            "quorum_threshold": quorum_threshold,
            "operator_note": operator_note,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def verify_wallet_identity_quorum_proposal(
    *,
    public_key: str,
    signature: str,
    wallet_id: str,
    chosen_object_id: str,
    chosen_payload_hash: str,
    proposer_node_id: str,
    eligible_voter_node_ids: list[str],
    quorum_threshold: int,
    operator_note: str | None,
) -> None:
    _verify_ed25519_signature(
        public_key=public_key,
        signature=signature,
        payload=wallet_identity_quorum_proposal_payload(
            wallet_id=wallet_id,
            chosen_object_id=chosen_object_id,
            chosen_payload_hash=chosen_payload_hash,
            proposer_node_id=proposer_node_id,
            eligible_voter_node_ids=eligible_voter_node_ids,
            quorum_threshold=quorum_threshold,
            operator_note=operator_note,
        ),
        required_message="Wallet-identity quorum proposal requires an Ed25519 signature",
        invalid_message="Wallet-identity quorum proposal signature is invalid",
    )


def wallet_identity_quorum_approval_payload(
    *,
    resolution_id: str,
    approver_node_id: str,
    approval_note: str | None,
) -> bytes:
    return json.dumps(
        {
            "domain": "aidn.wallet-identity.quorum-approval.v1",
            "resolution_id": resolution_id,
            "approver_node_id": approver_node_id,
            "approval_note": approval_note,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def verify_wallet_identity_quorum_approval(
    *,
    public_key: str,
    signature: str,
    resolution_id: str,
    approver_node_id: str,
    approval_note: str | None,
) -> None:
    _verify_ed25519_signature(
        public_key=public_key,
        signature=signature,
        payload=wallet_identity_quorum_approval_payload(
            resolution_id=resolution_id,
            approver_node_id=approver_node_id,
            approval_note=approval_note,
        ),
        required_message="Wallet-identity quorum approval requires an Ed25519 signature",
        invalid_message="Wallet-identity quorum approval signature is invalid",
    )
