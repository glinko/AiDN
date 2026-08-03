import json
from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from aidn_hypervisor.accounting.models import (
    AccountingMode,
    UnavailableValuePolicy,
    UsageAuthority,
    UsageDimensionEvidence,
)

FundingClass = Literal[
    "ESCROW_PREPAID",
    "TRUSTED_POSTPAID",
    "FREE",
    "INTERNAL",
    "VALIDATION",
]
FundingState = Literal[
    "UNFUNDED",
    "LOCK_PENDING",
    "LOCKED",
    "EXTENSION_PENDING",
    "PARTIALLY_RELEASED",
    "DISPUTE_RESERVED",
    "RELEASE_PENDING",
    "RELEASED",
    "REFUNDED",
    "FAILED",
]
RequestTerminalState = Literal[
    "COMPLETED",
    "PARTIAL",
    "CANCELLED",
    "REJECTED",
    "FAILED",
    "EXPIRED",
    "UNRECOVERABLE",
]
TerminalChargeMode = Literal[
    "NO_CHARGE",
    "ACCRUED_USAGE_ONLY",
    "FIXED_CHARGE",
    "PROPORTIONAL_BPS",
    "FULL_CHARGE",
    "DISPUTE_REVIEW",
]
SettlementMode = Literal[
    "COOPERATIVE_FINAL",
    "COOPERATIVE_ZERO",
    "PARTIAL_UNDISPUTED",
    "FORCED",
    "POSTPAID_OBLIGATION",
    "VALIDATION_ZERO",
    "CORRECTION",
]
RoundingMode = Literal["DOWN", "UP", "HALF_EVEN"]


def canonical_hash(payload: dict) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return f"sha256:{sha256(encoded).hexdigest()}"


class SessionFundingAccount(BaseModel):
    session_id: str = Field(min_length=1)
    session_contract_hash: str | None = None
    funding_class: FundingClass
    consumer_funding_account: str = Field(min_length=1)
    endpoint_payment_beneficiary: str = Field(min_length=1)
    consumer_refund_beneficiary: str = Field(min_length=1)
    total_locked_amount_q_atoms: int = Field(ge=0)
    endpoint_payment_reserve_q_atoms: int = Field(ge=0)
    network_fee_reserve_q_atoms: int = Field(ge=0)
    postpaid_credit_limit_q_atoms: int = Field(default=0, ge=0)
    active_dispute_reserve_q_atoms: int = Field(default=0, ge=0)
    released_to_endpoint_q_atoms: int = Field(default=0, ge=0)
    consumer_payment_refund_q_atoms: int = Field(default=0, ge=0)
    consumed_network_fees_q_atoms: int = Field(default=0, ge=0)
    consumer_fee_refund_q_atoms: int = Field(default=0, ge=0)
    unsettled_payment_reserve_q_atoms: int = Field(default=0, ge=0)
    unsettled_fee_reserve_q_atoms: int = Field(default=0, ge=0)
    funding_state: FundingState = "LOCKED"
    funding_state_hash: str | None = None

    @model_validator(mode="after")
    def _validate_conservation(self):
        if self.total_locked_amount_q_atoms != (
            self.endpoint_payment_reserve_q_atoms
            + self.network_fee_reserve_q_atoms
        ):
            raise ValueError("locked amount must equal payment plus fee reserves")
        payment_total = (
            self.released_to_endpoint_q_atoms
            + self.consumer_payment_refund_q_atoms
            + self.active_dispute_reserve_q_atoms
            + self.unsettled_payment_reserve_q_atoms
        )
        if payment_total != self.endpoint_payment_reserve_q_atoms:
            raise ValueError("Endpoint Payment Reserve conservation failed")
        fee_total = (
            self.consumed_network_fees_q_atoms
            + self.consumer_fee_refund_q_atoms
            + self.unsettled_fee_reserve_q_atoms
        )
        if fee_total != self.network_fee_reserve_q_atoms:
            raise ValueError("Network Fee Reserve conservation failed")
        payload = self.model_dump(mode="json", exclude={"funding_state_hash"})
        expected = canonical_hash(payload)
        if self.funding_state_hash is None:
            self.funding_state_hash = expected
        elif self.funding_state_hash != expected:
            raise ValueError("funding_state_hash does not match Funding Account")
        return self


class TerminalChargePolicy(BaseModel):
    mode: TerminalChargeMode
    fixed_charge_q_atoms: int | None = Field(default=None, ge=0)
    proportional_basis_points: int | None = Field(default=None, ge=0, le=10_000)

    @model_validator(mode="after")
    def _validate_policy(self):
        if self.mode == "FIXED_CHARGE" and self.fixed_charge_q_atoms is None:
            raise ValueError("FIXED_CHARGE requires fixed_charge_q_atoms")
        if self.mode == "PROPORTIONAL_BPS" and self.proportional_basis_points is None:
            raise ValueError("PROPORTIONAL_BPS requires proportional_basis_points")
        return self


class SettlementChargeComponent(BaseModel):
    component_id: str = Field(min_length=1)
    dimension_id: str | None = None
    fixed_amount_q_atoms: int | None = Field(default=None, ge=0)
    unit_price_q_atoms: int = Field(default=0, ge=0)
    unit_divisor: int = Field(default=1, ge=1)
    source_value_scale: int = Field(default=1, ge=1)
    rounding: RoundingMode = "DOWN"
    required_authority: UsageAuthority | None = None
    unavailable_value_policy: UnavailableValuePolicy | Literal["DISPUTE_REVIEW"] = (
        "REQUEST_REJECTED_BEFORE_EXECUTION"
    )
    fallback_amount_q_atoms: int | None = Field(default=None, ge=0)
    fallback_dimension_id: str | None = None

    @model_validator(mode="after")
    def _validate_component(self):
        if self.dimension_id is None:
            if self.fixed_amount_q_atoms is None:
                raise ValueError("fixed component requires fixed_amount_q_atoms")
            if self.required_authority is not None:
                raise ValueError("fixed component cannot require Usage authority")
        elif self.fixed_amount_q_atoms is not None:
            raise ValueError("variable component cannot also be fixed")
        if self.dimension_id is None and self.source_value_scale != 1:
            raise ValueError("fixed component cannot scale a Usage value")
        if (
            self.unavailable_value_policy == "FIXED_FALLBACK"
            and self.fallback_amount_q_atoms is None
        ):
            raise ValueError("FIXED_FALLBACK requires fallback_amount_q_atoms")
        if (
            self.unavailable_value_policy == "OBSERVABLE_FALLBACK"
            and self.fallback_dimension_id is None
        ):
            raise ValueError("OBSERVABLE_FALLBACK requires fallback_dimension_id")
        return self


class SettlementAccountingTerms(BaseModel):
    accounting_contract_hash: str = Field(min_length=1)
    accounting_mode: AccountingMode
    components: list[SettlementChargeComponent] = Field(default_factory=list)
    minimum_charge_q_atoms: int = Field(default=0, ge=0)
    terminal_policies: dict[RequestTerminalState, TerminalChargePolicy] = Field(
        default_factory=dict
    )
    terms_version: str = Field(default="settlement-terms.v1", min_length=1)
    terms_hash: str | None = None

    @model_validator(mode="after")
    def _validate_terms_hash(self):
        component_ids = [item.component_id for item in self.components]
        if len(component_ids) != len(set(component_ids)):
            raise ValueError("Settlement component IDs must be unique")
        payload = self.model_dump(mode="json", exclude={"terms_hash"})
        expected = canonical_hash(payload)
        if self.terms_hash is None:
            self.terms_hash = expected
        elif self.terms_hash != expected:
            raise ValueError("terms_hash does not match Settlement terms")
        return self


class RequestSettlementInput(BaseModel):
    session_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    request_charge_ceiling_q_atoms: int = Field(ge=0)
    effective_terms_hash: str | None = None
    accounting_contract_hash: str = Field(min_length=1)
    terminal_state: RequestTerminalState
    result_reference: str | None = None
    final_usage_report_id: str | None = None
    final_usage_report_hash: str | None = None
    usage_sequence: int | None = Field(default=None, ge=1)
    usage_chain_valid: bool = True
    usage_chain_conflicted: bool = False
    dimensions: list[UsageDimensionEvidence] = Field(default_factory=list)
    minimum_charge_eligible: bool = True
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_usage_identity(self):
        if (self.final_usage_report_id is None) != (
            self.final_usage_report_hash is None
        ):
            raise ValueError("Final Usage Report ID and Hash must appear together")
        if self.final_usage_report_id is None and self.terminal_state != "REJECTED":
            self.limitations = [*self.limitations, "Final Usage Report missing"]
        dimension_ids = [item.dimension_id for item in self.dimensions]
        if len(dimension_ids) != len(set(dimension_ids)):
            raise ValueError("Usage dimensions must be unique per Request")
        return self


class BillableComponentResult(BaseModel):
    component_id: str = Field(min_length=1)
    dimension_id: str | None = None
    source_value: int | None = Field(default=None, ge=0)
    charge_q_atoms: int = Field(ge=0)
    disputed: bool = False
    limitation: str | None = None


class RequestSettlementRecord(BaseModel):
    session_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    request_charge_ceiling_q_atoms: int = Field(ge=0)
    effective_terms_hash: str | None = None
    accounting_contract_hash: str = Field(min_length=1)
    terminal_state: RequestTerminalState
    result_reference: str | None = None
    final_usage_report_id: str | None = None
    final_usage_report_hash: str | None = None
    raw_calculated_charge_q_atoms: int = Field(ge=0)
    policy_adjusted_charge_q_atoms: int = Field(ge=0)
    capped_request_charge_q_atoms: int = Field(ge=0)
    endpoint_absorbed_amount_q_atoms: int = Field(ge=0)
    disputed_amount_q_atoms: int = Field(default=0, ge=0)
    billable_components: list[BillableComponentResult] = Field(default_factory=list)
    nonbillable_components: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    dispute_state: Literal["NONE", "DISPUTED"] = "NONE"
    record_hash: str | None = None

    @model_validator(mode="after")
    def _validate_record(self):
        if self.capped_request_charge_q_atoms > self.request_charge_ceiling_q_atoms:
            raise ValueError("Request charge exceeds Request Charge Ceiling")
        payload = self.model_dump(mode="json", exclude={"record_hash"})
        expected = canonical_hash(payload)
        if self.record_hash is None:
            self.record_hash = expected
        elif self.record_hash != expected:
            raise ValueError("record_hash does not match Request Settlement Record")
        return self


class SettlementInputSet(BaseModel):
    session_id: str = Field(min_length=1)
    session_contract_hash: str = Field(min_length=1)
    effective_terms_hash: str = Field(min_length=1)
    endpoint_payment_beneficiary: str = Field(min_length=1)
    consumer_refund_beneficiary: str = Field(min_length=1)
    funding_state_reference: str = Field(min_length=1)
    request_settlement_records: list[RequestSettlementRecord] = Field(default_factory=list)
    request_settlement_root: str | None = None
    final_usage_chain_heads: dict[str, str] = Field(default_factory=dict)
    usage_chain_root: str | None = None
    accepted_checkpoint_references: list[str] = Field(default_factory=list)
    checkpoint_root: str | None = None
    dispute_references: list[str] = Field(default_factory=list)
    failure_references: list[str] = Field(default_factory=list)
    artifact_commitments: list[str] = Field(default_factory=list)
    session_close_reference: str = Field(min_length=1)
    settlement_input_root: str | None = None

    @model_validator(mode="after")
    def _populate_roots(self):
        request_ids = [item.request_id for item in self.request_settlement_records]
        if len(request_ids) != len(set(request_ids)):
            raise ValueError("Request Settlement Records must be unique")
        request_root = canonical_hash(
            {
                "records": [
                    item.record_hash
                    for item in sorted(
                        self.request_settlement_records,
                        key=lambda item: item.request_id,
                    )
                ]
            }
        )
        usage_root = canonical_hash(
            {"chain_heads": dict(sorted(self.final_usage_chain_heads.items()))}
        )
        checkpoint_root = canonical_hash(
            {"checkpoints": sorted(self.accepted_checkpoint_references)}
        )
        for provided, expected, name in (
            (self.request_settlement_root, request_root, "request_settlement_root"),
            (self.usage_chain_root, usage_root, "usage_chain_root"),
            (self.checkpoint_root, checkpoint_root, "checkpoint_root"),
        ):
            if provided is not None and provided != expected:
                raise ValueError(f"{name} does not match Settlement evidence")
        self.request_settlement_root = request_root
        self.usage_chain_root = usage_root
        self.checkpoint_root = checkpoint_root
        payload = self.model_dump(mode="json", exclude={"settlement_input_root"})
        expected_input_root = canonical_hash(payload)
        if self.settlement_input_root is None:
            self.settlement_input_root = expected_input_root
        elif self.settlement_input_root != expected_input_root:
            raise ValueError("settlement_input_root does not match Settlement Input Set")
        return self


class SessionSettlementProposal(BaseModel):
    settlement_id: str
    settlement_sequence: int = Field(ge=1)
    session_id: str
    settlement_input_root: str
    request_settlement_root: str
    usage_chain_root: str
    checkpoint_root: str
    gross_session_charge_q_atoms: int = Field(ge=0)
    capped_session_charge_q_atoms: int = Field(ge=0)
    final_endpoint_payment_q_atoms: int = Field(ge=0)
    requested_endpoint_payment_q_atoms: int = Field(ge=0)
    consumer_payment_refund_q_atoms: int = Field(ge=0)
    actual_network_fees_q_atoms: int = Field(ge=0)
    consumer_fee_refund_q_atoms: int = Field(ge=0)
    disputed_amount_q_atoms: int = Field(ge=0)
    dispute_reserve_q_atoms: int = Field(ge=0)
    endpoint_absorbed_amount_q_atoms: int = Field(ge=0)
    settlement_mode: SettlementMode
    proposal_expiration: str | None = None


class SettlementReadyCommitment(BaseModel):
    """Immutable Settlement Input Set commitment before proposal admission."""

    session_id: str = Field(min_length=1)
    settlement_sequence: int = Field(ge=1)
    session_contract_hash: str = Field(min_length=1)
    effective_terms_hash: str = Field(min_length=1)
    funding_state_reference: str = Field(min_length=1)
    endpoint_payment_beneficiary: str = Field(min_length=1)
    consumer_refund_beneficiary: str = Field(min_length=1)
    request_settlement_root: str = Field(min_length=1)
    usage_chain_root: str = Field(min_length=1)
    checkpoint_root: str = Field(min_length=1)
    settlement_input_root: str = Field(min_length=1)
    session_close_reference: str = Field(min_length=1)
    ready_at: str = Field(min_length=1)
    commitment_hash: str | None = None

    @model_validator(mode="after")
    def _populate_commitment_hash(self):
        payload = self.model_dump(mode="json", exclude={"commitment_hash"})
        expected = canonical_hash(payload)
        if self.commitment_hash is None:
            self.commitment_hash = expected
        elif self.commitment_hash != expected:
            raise ValueError(
                "commitment_hash does not match Settlement Ready Commitment"
            )
        return self


class SessionSettlementAcceptance(BaseModel):
    settlement_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    settlement_input_root: str = Field(min_length=1)
    accepted_endpoint_payment_q_atoms: int = Field(ge=0)
    accepted_consumer_refund_q_atoms: int = Field(ge=0)
    accepted_network_fees_q_atoms: int = Field(ge=0)
    consumer_signature: str = Field(min_length=1)
    accepted_at: str = Field(min_length=1)
    acceptance_hash: str | None = None

    @model_validator(mode="after")
    def _populate_acceptance_hash(self):
        payload = self.model_dump(mode="json", exclude={"acceptance_hash"})
        expected = canonical_hash(payload)
        if self.acceptance_hash is None:
            self.acceptance_hash = expected
        elif self.acceptance_hash != expected:
            raise ValueError("acceptance_hash does not match Settlement Acceptance")
        return self


class SessionUsageCheckpoint(BaseModel):
    """Integer, hash-bound exposure checkpoint for consensus Settlement."""

    checkpoint_id: str = Field(min_length=1)
    checkpoint_sequence: int = Field(ge=1)
    session_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    usage_report_id: str = Field(min_length=1)
    usage_report_hash: str = Field(min_length=1)
    usage_sequence: int = Field(ge=1)
    calculated_charge_q_atoms: int = Field(ge=0)
    current_session_exposure_q_atoms: int = Field(ge=0)
    remaining_deposit_q_atoms: int = Field(ge=0)
    accounting_contract_hash: str = Field(min_length=1)
    created_at: str = Field(min_length=1)
    provider_signature: str = Field(min_length=1)
    consumer_signature: str = Field(min_length=1)
    checkpoint_hash: str | None = None

    @model_validator(mode="after")
    def _populate_checkpoint_hash(self):
        payload = self.model_dump(mode="json", exclude={"checkpoint_hash"})
        expected = canonical_hash(payload)
        if self.checkpoint_hash is None:
            self.checkpoint_hash = expected
        elif self.checkpoint_hash != expected:
            raise ValueError("checkpoint_hash does not match Session Usage Checkpoint")
        return self


class SettlementDispute(BaseModel):
    dispute_id: str = Field(min_length=1)
    settlement_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    disputed_request_ids: list[str] = Field(default_factory=list)
    disputed_usage_report_ids: list[str] = Field(default_factory=list)
    disputed_checkpoint_ids: list[str] = Field(default_factory=list)
    dispute_class: str = Field(min_length=1)
    claimed_endpoint_payment_q_atoms: int = Field(ge=0)
    accepted_endpoint_payment_q_atoms: int = Field(ge=0)
    disputed_amount_q_atoms: int = Field(gt=0)
    evidence_root: str = Field(min_length=1)
    opened_at: str = Field(min_length=1)
    claimant_signature: str = Field(min_length=1)
    dispute_hash: str | None = None

    @model_validator(mode="after")
    def _validate_dispute(self):
        maximum_difference = abs(
            self.claimed_endpoint_payment_q_atoms
            - self.accepted_endpoint_payment_q_atoms
        )
        if self.disputed_amount_q_atoms > maximum_difference:
            raise ValueError("disputed amount exceeds the claimed payment difference")
        payload = self.model_dump(mode="json", exclude={"dispute_hash"})
        expected = canonical_hash(payload)
        if self.dispute_hash is None:
            self.dispute_hash = expected
        elif self.dispute_hash != expected:
            raise ValueError("dispute_hash does not match Settlement Dispute")
        return self


class SettlementCorrection(BaseModel):
    correction_id: str = Field(min_length=1)
    settlement_id: str = Field(min_length=1)
    correction_reason: str = Field(min_length=1)
    prior_result_hash: str = Field(min_length=1)
    endpoint_payment_delta_q_atoms: int
    consumer_refund_delta_q_atoms: int
    network_fee_delta_q_atoms: int
    dispute_reserve_delta_q_atoms: int = 0
    authorization_reference: str = Field(min_length=1)
    evidence_root: str = Field(min_length=1)
    created_at: str = Field(min_length=1)
    correction_signature: str = Field(min_length=1)
    correction_hash: str | None = None

    @model_validator(mode="after")
    def _validate_correction(self):
        if (
            self.endpoint_payment_delta_q_atoms
            + self.consumer_refund_delta_q_atoms
            + self.network_fee_delta_q_atoms
            + self.dispute_reserve_delta_q_atoms
            != 0
        ):
            raise ValueError("Settlement correction must conserve Q including reserve")
        payload = self.model_dump(mode="json", exclude={"correction_hash"})
        expected = canonical_hash(payload)
        if self.correction_hash is None:
            self.correction_hash = expected
        elif self.correction_hash != expected:
            raise ValueError("correction_hash does not match Settlement Correction")
        return self


class AtomicSettlementTransition(BaseModel):
    session_id: str
    settlement_id: str
    endpoint_payment_beneficiary: str
    consumer_refund_beneficiary: str
    previously_released_to_endpoint_q_atoms: int = Field(ge=0)
    previously_refunded_to_consumer_q_atoms: int = Field(ge=0)
    previously_consumed_network_fees_q_atoms: int = Field(ge=0)
    credit_endpoint_q_atoms: int = Field(ge=0)
    credit_consumer_q_atoms: int = Field(ge=0)
    consume_network_fees_q_atoms: int = Field(ge=0)
    retain_dispute_reserve_q_atoms: int = Field(ge=0)
    postpaid_obligation_q_atoms: int = Field(default=0, ge=0)
    total_locked_amount_q_atoms: int = Field(ge=0)
    transition_hash: str | None = None

    @model_validator(mode="after")
    def _validate_atomic_conservation(self):
        distributed = (
            self.previously_released_to_endpoint_q_atoms
            + self.previously_refunded_to_consumer_q_atoms
            + self.previously_consumed_network_fees_q_atoms
            + self.credit_endpoint_q_atoms
            + self.credit_consumer_q_atoms
            + self.consume_network_fees_q_atoms
            + self.retain_dispute_reserve_q_atoms
        )
        if distributed != self.total_locked_amount_q_atoms:
            raise ValueError("atomic Settlement transition does not conserve locked funds")
        payload = self.model_dump(mode="json", exclude={"transition_hash"})
        expected = canonical_hash(payload)
        if self.transition_hash is None:
            self.transition_hash = expected
        elif self.transition_hash != expected:
            raise ValueError("transition_hash does not match Settlement transition")
        return self


class SettlementEvaluation(BaseModel):
    input_set: SettlementInputSet
    proposal: SessionSettlementProposal
    transition: AtomicSettlementTransition
