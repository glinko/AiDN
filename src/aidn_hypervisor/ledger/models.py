from typing import Literal

from pydantic import BaseModel, Field

LedgerOriginType = Literal["wallet", "multi_party", "protocol", "evidence_triggered"]
LedgerFeeClass = Literal[
    "standard",
    "session",
    "protocol_sponsored",
    "onboarding_exempt",
    "faucet_exempt",
]
LedgerOperationStatus = Literal["applied", "rejected", "no_op"]


class LedgerOperationResult(BaseModel):
    status: LedgerOperationStatus
    error_code: str | None = None
    error_details_hash: str | None = None
    fee_charged: bool = False
    state_changes_root: str
    emitted_events: list[str] = Field(default_factory=list)


class LedgerOperationRecord(BaseModel):
    sequence_id: int = Field(ge=1)
    operation_id: str = Field(min_length=1)
    operation_type: str = Field(min_length=1)
    operation_version: str = Field(min_length=1)
    protocol_version: str = Field(min_length=1)
    origin_type: LedgerOriginType
    initiator_id: str | None = None
    sender_wallet: str | None = None
    sender_sequence: int | None = Field(default=None, ge=1)
    fee_class: LedgerFeeClass
    fee_payer: str | None = None
    created_at: str = Field(min_length=1)
    expires_at: str | None = None
    target_epoch: str | None = None
    payload: dict = Field(default_factory=dict)
    evidence_references: list[str] = Field(default_factory=list)
    signatures: list[str] = Field(default_factory=list)
    # Persist the exact CometBFT transaction identity when this record was
    # admitted from a consensus envelope. Local-only projections leave it
    # unset and must never be treated as externally finalized.
    transaction_hash: str | None = None
    result: LedgerOperationResult
    wallet_next_sequence: int | None = Field(default=None, ge=1)
