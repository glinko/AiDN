import hashlib
import json
from datetime import UTC, datetime

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
        registered_at=datetime.now(UTC).isoformat(),
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
        if expires_at <= datetime.now(UTC):
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


def wallet_identity_governance_certificate_payload(
    *,
    certificate_id: str,
    resolution_id: str,
    wallet_id: str,
    chosen_object_id: str,
    chosen_payload_hash: str,
    governance_policy_hash: str,
    eligible_voter_node_ids: list[str],
    voter_authorities: list[dict[str, str]],
    quorum_threshold: int,
    approvals: list[dict[str, str | None]],
) -> bytes:
    """Build the portable, signed-evidence commitment for a quorum decision."""
    return json.dumps(
        {
            "domain": "aidn.wallet-identity.governance-certificate.v1",
            "resolution_id": resolution_id,
            "wallet_id": wallet_id,
            "chosen_object_id": chosen_object_id,
            "chosen_payload_hash": chosen_payload_hash,
            "governance_policy_hash": governance_policy_hash,
            "eligible_voter_node_ids": list(eligible_voter_node_ids),
            "voter_authorities": list(voter_authorities),
            "quorum_threshold": quorum_threshold,
            "approvals": list(approvals),
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def verify_wallet_identity_governance_certificate(
    *,
    certificate_id: str,
    resolution_id: str,
    wallet_id: str,
    chosen_object_id: str,
    chosen_payload_hash: str,
    governance_policy_hash: str,
    eligible_voter_node_ids: list[str],
    voter_authorities: list[dict[str, str]],
    quorum_threshold: int,
    approvals: list[dict[str, str | None]],
) -> None:
    """Verify quorum evidence without consulting the certificate issuer's state."""
    if quorum_threshold < 1:
        raise ValueError("Wallet-identity governance certificate quorum threshold is invalid")
    eligible_voters = set(eligible_voter_node_ids)
    authorities = {
        str(item.get("node_id") or ""): str(item.get("public_key") or "")
        for item in voter_authorities
    }
    if set(authorities) != eligible_voters or not all(authorities.values()):
        raise ValueError("Wallet-identity governance certificate authority set is invalid")

    seen_approvers: set[str] = set()
    for approval in approvals:
        approver_node_id = str(approval.get("approver_node_id") or "")
        signature = approval.get("approval_signature")
        approval_note = approval.get("approval_note")
        approval_kind = str(approval.get("approval_kind") or "approval")
        if approver_node_id not in eligible_voters or approver_node_id in seen_approvers:
            raise ValueError("Wallet-identity governance certificate approval set is invalid")
        if not isinstance(signature, str):
            raise ValueError("Wallet-identity governance certificate approval is unsigned")
        if approval_kind == "proposal":
            verify_wallet_identity_quorum_proposal(
                public_key=authorities[approver_node_id],
                signature=signature,
                wallet_id=wallet_id,
                chosen_object_id=chosen_object_id,
                chosen_payload_hash=chosen_payload_hash,
                proposer_node_id=approver_node_id,
                eligible_voter_node_ids=eligible_voter_node_ids,
                quorum_threshold=quorum_threshold,
                operator_note=approval_note if isinstance(approval_note, str) else None,
            )
        elif approval_kind == "approval":
            verify_wallet_identity_quorum_approval(
                public_key=authorities[approver_node_id],
                signature=signature,
                resolution_id=resolution_id,
                approver_node_id=approver_node_id,
                approval_note=approval_note if isinstance(approval_note, str) else None,
            )
        else:
            raise ValueError("Wallet-identity governance certificate approval kind is invalid")
        seen_approvers.add(approver_node_id)
    if len(seen_approvers) < quorum_threshold:
        raise ValueError("Wallet-identity governance certificate lacks quorum")

    expected_payload = wallet_identity_governance_certificate_payload(
        certificate_id=certificate_id,
        resolution_id=resolution_id,
        wallet_id=wallet_id,
        chosen_object_id=chosen_object_id,
        chosen_payload_hash=chosen_payload_hash,
        governance_policy_hash=governance_policy_hash,
        eligible_voter_node_ids=eligible_voter_node_ids,
        voter_authorities=voter_authorities,
        quorum_threshold=quorum_threshold,
        approvals=approvals,
    )
    expected_id = "sha256:" + hashlib.sha256(expected_payload).hexdigest()
    if certificate_id != expected_id:
        raise ValueError("Wallet-identity governance certificate identity is invalid")
