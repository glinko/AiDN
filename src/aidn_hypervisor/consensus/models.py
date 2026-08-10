"""RFC-0047 §7-§9 — Ledger Operation Envelope."""

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, Field

# Canonical operation types defined by the protocol.
# Custom handlers may register additional types dynamically.
KNOWN_OPERATION_TYPES = frozenset({
    "WALLET_TRANSFER",
    "OPERATOR_WALLET_BIND",
    "SESSION_OPEN",
    "SESSION_ACCEPT",
    "DEPOSIT_LOCK",
    "SESSION_ESCROW_LOCK",
    "SESSION_ESCROW_EXTEND",
    "SESSION_ESCROW_RELEASE",
    "SESSION_CHECKPOINT_COMMIT",
    "SESSION_SETTLEMENT_READY_COMMIT",
    "SESSION_FAILURE_EVIDENCE",
    "SESSION_SETTLEMENT_PROPOSE",
    "SESSION_SETTLEMENT_ACCEPT",
    "SESSION_SETTLEMENT_DISPUTE",
    "SESSION_SETTLEMENT_PARTIAL_FINALIZE",
    "SESSION_SETTLEMENT_CORRECT",
    "SESSION_SETTLEMENT_FINALIZE",
    "SESSION_FORCE_SETTLE",
    "SESSION_SETTLE",
    "ENDPOINT_PUBLISH",
    "VALIDATION_REQUEST",
    "VALIDATION_REPORT",
    "VALIDATOR_STAKE",
    "VALIDATOR_UNSTAKE",
    "STAKE_LOCK",
    "UNSTAKE_REQUEST",
    "STAKE_RELEASE",
    "PARTICIPANT_SUSPEND",
    "PARTICIPANT_REINSTATE",
    "REGISTRY_UPSERT",
    "SNAPSHOT_COMMIT",
    "EPOCH_TASK",
    "SETTLEMENT_PROPOSE",
    "SETTLEMENT_ACCEPT",
    "EPOCH_TRANSITION",
    "TREASURY_FUND",
    "REWARD_MINT",
    "DEVELOPMENT_POOL_ALLOCATE",
    "DEVELOPMENT_POOL_CARRYOVER",
    "DEVELOPMENT_BOUNTY_CREATE",
    "DEVELOPMENT_BOUNTY_RESERVE",
    "DEVELOPMENT_BOUNTY_RELEASE",
    "DEVELOPMENT_BOUNTY_EXPIRE",
    "DEVELOPMENT_REWARD_CALCULATE",
    "DEVELOPMENT_REWARD_RESERVE",
    "DEVELOPMENT_REWARD_PAY_IMMEDIATE",
    "DEVELOPMENT_REWARD_PAY_MATURITY",
    "DEVELOPMENT_REWARD_MARK_UNCLAIMED",
    "DEVELOPMENT_REWARD_CLAIM",
    "DEVELOPMENT_REWARD_EXPIRE_UNCLAIMED",
    "DEVELOPMENT_REWARD_FINALIZE_COMMITMENT",
    "DEVELOPMENT_REWARD_CANCEL_UNVESTED",
    "DEVELOPMENT_REWARD_CORRECT",
    "SERVICE_VERIFICATION_COMMIT",
    "REPUTATION_PROFILE_UPDATE",
    "VALIDATION_REPORT_COMMIT",
    "VALIDATION_REPORT_STORAGE_RECEIPT",
    "VALIDATION_REPORT_STORAGE_FAILURE",
    "VALIDATION_REPORT_AVAILABILITY_COMMIT",
    "VALIDATION_REPORT_CUSTODY_RELEASE",
    "CONSENSUS_VALIDATOR_SET_UPDATE",
    "PENALTY_APPLY",
})

OperationType = str  # extensible — any non-empty string accepted

LedgerOriginType = Literal["wallet", "multi_party", "protocol", "evidence_triggered"]

LedgerFeeClass = Literal[
    "standard",
    "session",
    "protocol_sponsored",
    "onboarding_exempt",
]


def _canonical_json(value: dict) -> str:
    """Deterministic JSON serialization — sorted keys, no whitespace."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _compute_operation_id(canonical: str) -> str:
    """SHA-256 of canonical serialization."""
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class LedgerOperationEnvelope(BaseModel):
    """RFC-0047 §7 — Common operation envelope."""

    operation_type: OperationType
    operation_version: str = "1.0.0"
    protocol_version: str = "0.1"
    origin_type: LedgerOriginType
    initiator_id: str | None = None
    sender_wallet: str | None = None
    sender_sequence: int | None = Field(default=None, ge=1)
    fee_payer: str | None = None
    fee_class: LedgerFeeClass = "standard"
    created_at: str  # ISO-8601
    expires_at: str | None = None
    target_epoch: str | None = None
    payload: dict = Field(default_factory=dict)
    evidence_references: list[str] = Field(default_factory=list)
    signatures: list[str] = Field(default_factory=list)

    # Computed fields
    operation_id: str = Field(default="")

    model_config = {"frozen": True}  # immutable after creation

    def model_post_init(self, __context):
        """Compute and verify the immutable operation identity."""
        computed_id = _compute_operation_id(self.canonical_bytes().decode("utf-8"))
        if self.operation_id and self.operation_id != computed_id:
            raise ValueError("operation_id does not match the canonical envelope")
        if not self.operation_id:
            object.__setattr__(self, "operation_id", computed_id)

    def canonical_bytes(self) -> bytes:
        """Return the canonical, unsigned operation identity preimage."""
        obj_dict = self.model_dump(mode="json")
        obj_dict["operation_id"] = ""  # exclude operation_id from its own hash
        # Signatures authorize an operation but cannot change its identity.
        obj_dict["signatures"] = []
        return _canonical_json(obj_dict).encode("utf-8")

    def signing_bytes(self) -> bytes:
        """Return the stable payload an authorization signature must cover."""
        obj_dict = self.model_dump(mode="json")
        obj_dict["signatures"] = []
        return _canonical_json(obj_dict).encode("utf-8")
