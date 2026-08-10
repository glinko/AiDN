"""Hash-bound public models for the external Faucet service."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from aidn_hypervisor.faucet_treasury import FaucetTreasuryActivationProof

Q_ATOMS_PER_Q = 1_000_000
FAUCET_POLICY_VERSION = "aidn.faucet-policy.v1"


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value)).hexdigest()


def wallet_id_for_public_key(public_key: str) -> str:
    if not isinstance(public_key, str) or not public_key.startswith("ed25519:"):
        raise ValueError("wallet public key must use ed25519:<hex>")
    try:
        raw = bytes.fromhex(public_key.removeprefix("ed25519:"))
    except ValueError as error:
        raise ValueError("wallet public key is not hexadecimal") from error
    if len(raw) != 32:
        raise ValueError("wallet public key must contain 32 bytes")
    return "wallet-" + hashlib.sha256(public_key.encode("utf-8")).hexdigest()[:12]


class FaucetChallengeRequest(BaseModel, frozen=True):
    wallet_id: str = Field(min_length=1)
    wallet_public_key: str = Field(min_length=1)


class FaucetChallenge(BaseModel, frozen=True):
    challenge_id: str = Field(min_length=1)
    wallet_id: str = Field(min_length=1)
    challenge: str = Field(min_length=1)
    issued_at: str = Field(min_length=1)
    expires_at: str = Field(min_length=1)

    def signing_bytes(self) -> bytes:
        return canonical_json(
            {
                "domain": "aidn.faucet-wallet-proof.v1",
                "challenge_id": self.challenge_id,
                "wallet_id": self.wallet_id,
                "challenge": self.challenge,
            }
        )


class FaucetClaimRequest(BaseModel, frozen=True):
    request_id: str = Field(min_length=1, max_length=256)
    wallet_id: str = Field(min_length=1)
    wallet_public_key: str = Field(min_length=1)
    challenge_id: str = Field(min_length=1)
    wallet_signature: str = Field(min_length=1)


class PolicyDecision(BaseModel, frozen=True):
    policy_id: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    quota_key: str = Field(min_length=1)
    amount_q_atoms: int = Field(gt=0)
    decision_hash: str = Field(min_length=1)
    state_after_success: dict[str, Any] = Field(default_factory=dict)


class TransferSubmission(BaseModel, frozen=True):
    operation_id: str = Field(min_length=1)
    status: Literal["FINALIZED", "ADMITTED", "REJECTED", "UNKNOWN"]
    detail: str | None = None
    transaction_hash: str | None = None


class FaucetClaimResponse(BaseModel, frozen=True):
    request_id: str
    claim_id: str | None = None
    status: Literal[
        "APPROVED",
        "PENDING_FINALITY",
        "SUBMISSION_REJECTED",
        "SUBMISSION_UNKNOWN",
        "ALREADY_CLAIMED",
        "QUOTA_EXHAUSTED",
        "POOL_EMPTY",
    ]
    amount_q_atoms: int = 0
    operation_id: str | None = None
    transaction_hash: str | None = None
    policy_id: str
    policy_version: str
    detail: str | None = None


class FaucetStatus(BaseModel, frozen=True):
    service_id: str
    treasury_id: str
    treasury_wallet_id: str
    policy_id: str
    policy_version: str
    policy_registry_id: str | None = None
    policy_registry_hash: str | None = None
    policy_release_hash: str | None = None
    policy_release_sequence: int | None = None
    policy_effective_from: str | None = None
    agent_auth_required: bool
    paused: bool = False
    pause_reason: str | None = None
    low_balance_watermark_q_atoms: int = 0
    low_balance_blocked: bool = False
    treasury_balance_q_atoms: int | None = None
    treasury_activation_state: Literal["ACTIVE", "UNVERIFIED", "DEGRADED", "DISABLED"] = (
        "UNVERIFIED"
    )
    treasury_activation_reason: str | None = None
    treasury_activation_proof: FaucetTreasuryActivationProof | None = None


class FaucetPauseRequest(BaseModel, frozen=True):
    reason: str = Field(min_length=1, max_length=512)


class FaucetLowBalanceRequest(BaseModel, frozen=True):
    watermark_q_atoms: int = Field(ge=0)
