import json
from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# RFC-0060: expanded Session status (15 states)
# Terminal: closed, rejected, cancelled, expired, force_settled, unrecoverable
SessionStatus = Literal[
    # ordinary lifecycle
    "queued",
    "active",
    "closed",
    # failure / recovery states
    "rejected",
    "cancelled",
    "expired",
    "recovering",
    "paused",
    "deposit_exhausted",
    "accounting_mismatch",
    "provider_unavailable",
    "consumer_unavailable",
    "force_closing",
    "force_settled",
    "unrecoverable",
]
CanonicalFundingStatus = Literal["UNBOUND", "PENDING_FINALITY", "FINALIZED"]
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
SessionAmendmentKind = Literal[
    "DEPOSIT_EXTENSION",
    "MAXIMUM_SESSION_CHARGE_INCREASE",
    "EXPIRATION_EXTENSION",
    "REQUEST_LIMIT_INCREASE",
    "ARTIFACT_LIMIT_INCREASE",
]


def _canonical_hash(payload: dict) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return f"sha256:{sha256(encoded).hexdigest()}"


class SessionContractAmendment(BaseModel):
    """One accepted, immutable version of a Session Contract.

    ``effective_terms_hash`` is a hash chain over contract terms.  The
    separate ``amendment_hash`` also commits identity, signatures and
    acceptance time, so a replay cannot substitute a different evidence
    object for the same terms transition.
    """

    amendment_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    sequence: int = Field(ge=1)
    previous_effective_terms_hash: str = Field(min_length=1)
    previous_amendment_hash: str | None = None
    amendment_kind: SessionAmendmentKind
    changes: dict = Field(min_length=1)
    affected_parties: list[str] = Field(min_length=1)
    consumer_signature: str = Field(min_length=1)
    endpoint_signature: str = Field(min_length=1)
    accepted_at: str = Field(min_length=1)
    effective_terms_hash: str = Field(min_length=1)
    amendment_hash: str = Field(min_length=1)
    object_id: str | None = None
    object_version: str = "session-amendment.v1"

    def terms_payload(self) -> dict:
        return {
            "previous_effective_terms_hash": self.previous_effective_terms_hash,
            "sequence": self.sequence,
            "amendment_kind": self.amendment_kind,
            "changes": self.changes,
        }

    def evidence_payload(self) -> dict:
        return self.model_dump(
            mode="json",
            exclude={"amendment_hash", "object_id"},
        )

    def signing_payload(self) -> bytes:
        payload = self.model_dump(
            mode="json",
            exclude={
                "consumer_signature",
                "endpoint_signature",
                "amendment_hash",
                "object_id",
            },
        )
        payload["domain"] = "aidn.session-amendment.v1"
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")

    @model_validator(mode="after")
    def _validate_hashes_and_chain(self):
        if self.sequence == 1 and self.previous_amendment_hash is not None:
            raise ValueError("first Session amendment cannot have a predecessor")
        if self.sequence > 1 and not self.previous_amendment_hash:
            raise ValueError("Session amendment predecessor is required")
        expected_terms_hash = _canonical_hash(self.terms_payload())
        if self.effective_terms_hash != expected_terms_hash:
            raise ValueError("effective_terms_hash does not match Session amendment")
        expected_amendment_hash = _canonical_hash(self.evidence_payload())
        if self.amendment_hash != expected_amendment_hash:
            raise ValueError("amendment_hash does not match Session amendment")
        return self


class SessionContractExchange(BaseModel):
    """Portable, integrity-checked Session Contract evidence package.

    Importing this object stages immutable Registry evidence. It does not
    activate a Session or overwrite a local Session projection.
    """

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1)
    session_contract_object_id: str = Field(min_length=1)
    session_contract_object_version: str = "session-contract.v2"
    session_contract_namespace: str = "session"
    session_contract_hash: str = Field(min_length=1)
    session_contract: dict = Field(min_length=1)
    amendments: list[SessionContractAmendment] = Field(default_factory=list)
    amendment_sequence: int = Field(ge=0)
    effective_terms_hash: str = Field(min_length=1)
    exchange_hash: str | None = None

    @staticmethod
    def _registry_object_id(*, object_type: str, object_version: str, payload_hash: str) -> str:
        return _canonical_hash(
            {
                "object_type": object_type,
                "object_version": object_version,
                "payload_hash": payload_hash,
            }
        )

    def _exchange_payload(self) -> dict:
        return self.model_dump(mode="json", exclude={"exchange_hash"})

    @model_validator(mode="after")
    def _validate_exchange(self):
        if _canonical_hash(self.session_contract) != self.session_contract_hash:
            raise ValueError("Session Contract payload hash does not match exchange")
        expected_object_id = self._registry_object_id(
            object_type="session_contract",
            object_version=self.session_contract_object_version,
            payload_hash=self.session_contract_hash,
        )
        if self.session_contract_object_id != expected_object_id:
            raise ValueError("Session Contract object identity does not match exchange")
        if self.session_contract.get("session_id") != self.session_id:
            raise ValueError("Session Contract belongs to another Session")

        previous_terms_hash = self.session_contract_hash
        previous_amendment_hash: str | None = None
        for expected_sequence, amendment in enumerate(self.amendments, start=1):
            if amendment.session_id != self.session_id:
                raise ValueError("Session amendment belongs to another Session")
            if not amendment.object_id:
                raise ValueError("Session amendment object identity is missing")
            expected_amendment_object_id = self._registry_object_id(
                object_type="session_contract_amendment",
                object_version=amendment.object_version,
                payload_hash=amendment.amendment_hash,
            )
            if amendment.object_id != expected_amendment_object_id:
                raise ValueError("Session amendment object identity does not match exchange")
            if amendment.sequence != expected_sequence:
                raise ValueError("Session amendment sequence is not contiguous")
            if amendment.previous_effective_terms_hash != previous_terms_hash:
                raise ValueError("Session amendment predecessor terms hash mismatch")
            if amendment.previous_amendment_hash != previous_amendment_hash:
                raise ValueError("Session amendment predecessor hash mismatch")
            previous_terms_hash = amendment.effective_terms_hash
            previous_amendment_hash = amendment.amendment_hash
        if self.amendment_sequence != len(self.amendments):
            raise ValueError("Session amendment sequence does not match exchange")
        if self.effective_terms_hash != previous_terms_hash:
            raise ValueError("Session effective terms hash does not match exchange")
        expected_exchange_hash = _canonical_hash(self._exchange_payload())
        if self.exchange_hash is None:
            self.exchange_hash = expected_exchange_hash
        elif self.exchange_hash != expected_exchange_hash:
            raise ValueError("Session Contract exchange hash does not match exchange")
        return self


class SessionRuntimeTerminalEvidence(BaseModel):
    request_id: str = Field(min_length=1)
    runtime_binding_id: str = Field(min_length=1)
    runtime_id: str = Field(min_length=1)
    runtime_generation: int = Field(ge=1)
    runtime_configuration_hash: str = Field(min_length=1)
    route_generation: int = Field(ge=1)
    endpoint_id: str = Field(min_length=1)
    endpoint_configuration_hash: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    session_contract_hash: str = Field(min_length=1)
    effective_terms_hash: str | None = None
    accounting_contract_hash: str = Field(min_length=1)
    terminal_state: str = Field(min_length=1)
    result_hash: str = Field(min_length=1)
    final_usage_report_id: str = Field(min_length=1)
    final_usage_report_hash: str = Field(min_length=1)
    recorded_at: str = Field(min_length=1)


class EndpointSession(BaseModel):
    session_id: str
    endpoint_id: str
    client_wallet: str
    provider_wallet: str
    endpoint_payment_beneficiary: str = Field(min_length=1)
    consumer_refund_beneficiary: str = Field(min_length=1)
    consumer_authorization_public_key: str | None = None
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
    fixed_price_q_atoms: int | None = Field(default=None, ge=0)
    request_charge_ceiling_q_atoms: int | None = Field(default=None, ge=0)
    canonical_funding_state_hash: str | None = None
    canonical_funding_status: CanonicalFundingStatus = "UNBOUND"
    canonical_funding_operation_id: str | None = None
    canonical_funding_submission: dict = Field(default_factory=dict)
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
    effective_terms_hash: str | None = None
    session_amendment_sequence: int = Field(default=0, ge=0)
    session_amendment_chain: list[dict] = Field(default_factory=list)
    runtime_terminal_evidence: list[SessionRuntimeTerminalEvidence] = Field(
        default_factory=list
    )
    last_usage_report_snapshot: dict = Field(default_factory=dict)
    last_usage_acknowledgement_snapshot: dict = Field(default_factory=dict)
    accounting_status: SessionAccountingStatus = "open"
    usage_report_chain: list[dict] = Field(default_factory=list)
    usage_acknowledgement_chain: list[dict] = Field(default_factory=list)
    accounting_checkpoint: dict = Field(default_factory=dict)
    last_accepted_report_sequence: int | None = Field(default=None, ge=1)
    last_accepted_usage_charged_q: float = Field(default=0.0, ge=0.0)
    failure_class: str | None = None
    failure_attribution: str | None = None
    recovery_deadline_at: str | None = None
    close_reason: str | None = None
    settlement_snapshot: dict = Field(default_factory=dict)

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
        if not normalized.get("effective_terms_hash"):
            normalized["effective_terms_hash"] = normalized.get("session_contract_hash")
        if "canonical_funding_status" not in normalized:
            normalized["canonical_funding_status"] = (
                "FINALIZED"
                if normalized.get("canonical_funding_state_hash")
                else "UNBOUND"
            )
        amendment_chain = normalized.get("session_amendment_chain")
        if not isinstance(amendment_chain, list):
            amendment_chain = []
            normalized["session_amendment_chain"] = amendment_chain
        if "session_amendment_sequence" not in normalized:
            normalized["session_amendment_sequence"] = len(amendment_chain)
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
    failure_evidence_root: str | None = None
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
