from typing import Literal

from pydantic import BaseModel, Field, model_validator

SessionStatus = Literal["queued", "active", "closed"]
DepositStatus = Literal["locked", "released"]
SessionAccountingStatus = Literal["open", "ack_pending", "mismatch", "force_settle_required"]
ProxySessionBindingStatus = Literal[
    "pending_open",
    "active",
    "degraded",
    "close_pending",
    "closed",
]
ProxySessionCloseStatus = Literal["not_requested", "closed", "pending_reconcile"]


class EndpointSession(BaseModel):
    session_id: str
    endpoint_id: str
    client_wallet: str
    provider_wallet: str
    endpoint_payment_beneficiary: str = Field(min_length=1)
    consumer_refund_beneficiary: str = Field(min_length=1)
    node_id: str
    status: SessionStatus
    created_at: str
    started_at: str | None = None
    last_activity_at: str | None = None
    expires_at: str
    idle_deadline_at: str
    deposit_locked_q: float = Field(gt=0.0)
    economic_profile: str | None = None
    deposit_locked_q_atoms: int | None = Field(default=None, gt=0)
    canonical_funding_state_hash: str | None = None
    request_count: int = Field(default=0, ge=0)
    reserved_slot_index: int | None = Field(default=None, ge=0)
    queue_policy_snapshot: str
    session_policy_snapshot: dict = Field(default_factory=dict)
    accounting_contract_snapshot: dict = Field(default_factory=dict)
    advertisement_id: str | None = None
    offer_id: str | None = None
    pricing_policy_hash: str | None = None
    accounting_contract_hash: str | None = None
    accounting_contract_object_id: str | None = None
    accounting_contract_object_version: str | None = None
    accounting_contract_namespace: str | None = None
    endpoint_configuration_hash: str | None = None
    session_contract_object_id: str | None = None
    session_contract_object_version: str | None = None
    session_contract_namespace: str | None = None
    session_contract_hash: str | None = None
    last_usage_report_snapshot: dict = Field(default_factory=dict)
    last_usage_acknowledgement_snapshot: dict = Field(default_factory=dict)
    accounting_status: SessionAccountingStatus = "open"
    usage_report_chain: list[dict] = Field(default_factory=list)
    usage_acknowledgement_chain: list[dict] = Field(default_factory=list)
    accounting_checkpoint: dict = Field(default_factory=dict)
    last_accepted_report_sequence: int | None = Field(default=None, ge=1)
    last_accepted_usage_charged_q: float = Field(default=0.0, ge=0.0)
    close_reason: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _populate_legacy_beneficiaries(cls, value):
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        if not normalized.get("endpoint_payment_beneficiary"):
            normalized["endpoint_payment_beneficiary"] = normalized.get(
                "provider_wallet"
            )
        if not normalized.get("consumer_refund_beneficiary"):
            normalized["consumer_refund_beneficiary"] = normalized.get(
                "client_wallet"
            )
        return normalized


class LockedDeposit(BaseModel):
    deposit_id: str
    session_id: str
    wallet_id: str
    locked_q: float = Field(gt=0.0)
    consumed_q: float = Field(default=0.0, ge=0.0)
    refunded_q: float = Field(default=0.0, ge=0.0)
    status: DepositStatus = "locked"

    @model_validator(mode="after")
    def _validate_balances(self):
        if self.consumed_q > self.locked_q:
            raise ValueError("consumed_q cannot exceed locked_q")
        if self.refunded_q > self.locked_q:
            raise ValueError("refunded_q cannot exceed locked_q")
        if self.consumed_q + self.refunded_q > self.locked_q:
            raise ValueError("consumed_q plus refunded_q cannot exceed locked_q")
        return self


class SessionSettlementSummary(BaseModel):
    settlement_evidence_root: str | None = None
    endpoint_payment_beneficiary: str | None = None
    consumer_refund_beneficiary: str | None = None
    usage_charged_q: float = Field(default=0.0, ge=0.0)
    idle_fee_charged_q: float = Field(default=0.0, ge=0.0)
    minimum_session_fee_q: float = Field(default=0.0, ge=0.0)
    network_fee_q: float = Field(default=0.0, ge=0.0)
    charged_q: float = Field(default=0.0, ge=0.0)
    refunded_q: float = Field(default=0.0, ge=0.0)
    endpoint_payment_q: float = Field(default=0.0, ge=0.0)
    payout_q: float = Field(default=0.0, ge=0.0)
    no_request: bool = False


class ProxySessionBinding(BaseModel):
    local_session_id: str
    remote_endpoint_id: str
    remote_session_id: str
    remote_node_id: str
    source_base_url: str
    status: ProxySessionBindingStatus
    opened_at: str
    last_error: str | None = None
    close_status: ProxySessionCloseStatus = "not_requested"


class SessionResult(BaseModel):
    session: EndpointSession
    deposit: LockedDeposit
    settlement: SessionSettlementSummary | None = None
