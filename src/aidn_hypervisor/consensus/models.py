"""RFC-0047 §7-§9 — Ledger Operation Envelope."""

from typing import Literal

import hashlib
import json

from pydantic import BaseModel, Field


# Canonical operation types defined by the protocol.
# Custom handlers may register additional types dynamically.
KNOWN_OPERATION_TYPES = frozenset({
    "WALLET_TRANSFER",
    "SESSION_OPEN",
    "DEPOSIT_LOCK",
    "SESSION_SETTLE",
    "ENDPOINT_PUBLISH",
    "VALIDATION_REQUEST",
    "VALIDATION_REPORT",
    "VALIDATOR_STAKE",
    "VALIDATOR_UNSTAKE",
    "REGISTRY_UPSERT",
    "SNAPSHOT_COMMIT",
    "EPOCH_TASK",
    "SETTLEMENT_PROPOSE",
    "SETTLEMENT_ACCEPT",
})

OperationType = str  # extensible — any non-empty string accepted

LedgerOriginType = Literal["wallet", "multi_party", "protocol", "evidence_triggered"]

LedgerFeeClass = Literal[
    "standard",
    "session",
    "protocol_sponsored",
    "onboarding_exempt",
    "faucet_exempt",
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
        """Compute operation_id from canonical serialization."""
        if not self.operation_id:
            obj_dict = self.model_dump(mode="json")
            obj_dict["operation_id"] = ""  # exclude operation_id from its own hash
            canonical = _canonical_json(obj_dict)
            object.__setattr__(self, "operation_id", _compute_operation_id(canonical))

    def canonical_bytes(self) -> bytes:
        """Return canonical serialized bytes for signing."""
        obj_dict = self.model_dump(mode="json")
        obj_dict["operation_id"] = ""
        return _canonical_json(obj_dict).encode("utf-8")
