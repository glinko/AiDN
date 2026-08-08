"""Explicit projection from local Ledger records to consensus envelopes.

Local Ledger records and consensus envelopes intentionally have different
identity rules. These builders preserve the local operation as an audit
correlation while requiring callers to provide canonical dependency IDs and
authorization before an envelope can be submitted.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from aidn_hypervisor.consensus.models import LedgerOperationEnvelope


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"local operation field is invalid: {field_name}")
    return value


def _optional_text(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, field_name)


def _local_operation_payload(operation: Mapping[str, object], operation_type: str) -> dict:
    from aidn_hypervisor.ledger.service import LedgerOperationService

    record = dict(operation)
    LedgerOperationService.verify_operation_record(record)
    if record.get("operation_type") != operation_type:
        raise ValueError(f"local operation must be {operation_type}")
    payload = record.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("local operation payload is invalid")
    return payload


def _references(*values: object) -> list[str]:
    references: set[str] = set()
    for value in values:
        if isinstance(value, str) and value.strip():
            references.add(value)
        elif isinstance(value, (list, tuple, set)):
            references.update(
                item for item in value if isinstance(item, str) and item.strip()
            )
    return sorted(references)


def _signatures(signatures: Sequence[str], *, required: str | None = None) -> list[str]:
    result = sorted({signature for signature in signatures if signature.strip()})
    if not result:
        raise ValueError("consensus projection requires an authorization signature")
    if required is not None and required not in result:
        raise ValueError("consensus projection signature does not bind initiator")
    return result


def build_session_failure_evidence_envelope(
    operation: Mapping[str, object],
    *,
    signatures: Sequence[str],
    operation_version: str = "1.0.0",
    protocol_version: str = "0.1",
) -> LedgerOperationEnvelope:
    """Build a typed evidence envelope without reusing the local operation ID."""
    payload = _local_operation_payload(operation, "SESSION_FAILURE_EVIDENCE")
    local_operation_id = _required_text(operation.get("operation_id"), "operation_id")
    session_id = _required_text(payload.get("session_id"), "payload.session_id")
    _required_text(payload.get("failure_class"), "payload.failure_class")
    failure_root = _required_text(
        payload.get("failure_evidence_root"),
        "payload.failure_evidence_root",
    )
    projected_payload = dict(payload)
    existing_local_id = projected_payload.get("local_operation_id")
    if existing_local_id is not None and existing_local_id != local_operation_id:
        raise ValueError("local operation correlation is conflicting")
    projected_payload["local_operation_id"] = local_operation_id
    envelope = LedgerOperationEnvelope(
        operation_type="SESSION_FAILURE_EVIDENCE",
        operation_version=operation_version,
        protocol_version=protocol_version,
        origin_type="evidence_triggered",
        initiator_id=session_id,
        fee_class="session",
        created_at=_required_text(operation.get("created_at"), "created_at"),
        expires_at=_optional_text(operation.get("expires_at"), "expires_at"),
        target_epoch=_optional_text(operation.get("target_epoch"), "target_epoch"),
        payload=projected_payload,
        evidence_references=_references(operation.get("evidence_references"), failure_root),
        signatures=_signatures(signatures),
    )
    return envelope


def build_session_escrow_lock_envelope(
    operation: Mapping[str, object],
    *,
    funding: Mapping[str, object] | object,
    sender_sequence: int,
    signatures: Sequence[str],
    operation_version: str = "1.0.0",
    protocol_version: str = "0.1",
) -> LedgerOperationEnvelope:
    """Build a canonical escrow-lock envelope from a local lock record.

    The caller supplies the canonical funding projection and wallet sequence;
    neither value is inferred from a local operation ID.
    """
    payload = _local_operation_payload(operation, "SESSION_ESCROW_LOCK")
    local_operation_id = _required_text(operation.get("operation_id"), "operation_id")
    if isinstance(funding, Mapping):
        funding_payload = dict(funding)
    else:
        model_dump = getattr(funding, "model_dump", None)
        if not callable(model_dump):
            raise ValueError("funding must be a mapping or SessionFundingAccount")
        funding_payload = model_dump(mode="json")
    if not isinstance(funding_payload, dict):
        raise ValueError("funding projection is invalid")

    from aidn_hypervisor.settlement.models import SessionFundingAccount

    try:
        canonical_funding = SessionFundingAccount.model_validate(funding_payload)
    except ValueError as error:
        raise ValueError(f"funding projection is invalid: {error}") from error
    if canonical_funding.funding_state != "LOCKED":
        raise ValueError("canonical escrow funding must be LOCKED")
    if sender_sequence < 1:
        raise ValueError("canonical escrow sender sequence must be positive")
    for field_name in ("sender_wallet", "fee_payer"):
        local_value = operation.get(field_name)
        if local_value is not None and local_value != canonical_funding.consumer_funding_account:
            raise ValueError(f"local escrow authorization conflicts: {field_name}")

    for field_name in (
        "session_id",
        "session_contract_hash",
        "funding_state_hash",
        "total_locked_amount_q_atoms",
        "endpoint_payment_reserve_q_atoms",
        "network_fee_reserve_q_atoms",
        "endpoint_payment_beneficiary",
        "consumer_refund_beneficiary",
    ):
        local_value = payload.get(field_name)
        canonical_value = funding_payload.get(field_name)
        if local_value is not None and local_value != canonical_value:
            raise ValueError(f"local and canonical escrow fields conflict: {field_name}")

    # A canonical record may be restored from ABCI after the in-memory
    # submission index was lost. Reconstruct that exact envelope instead of
    # adding a local correlation field or normalizing its evidence order.
    canonical_record = LedgerOperationEnvelope(
        operation_type=_required_text(operation.get("operation_type"), "operation_type"),
        operation_version=_required_text(operation.get("operation_version"), "operation_version"),
        protocol_version=_required_text(operation.get("protocol_version"), "protocol_version"),
        origin_type=_required_text(operation.get("origin_type"), "origin_type"),
        initiator_id=operation.get("initiator_id"),
        sender_wallet=operation.get("sender_wallet"),
        sender_sequence=sender_sequence,
        fee_payer=operation.get("fee_payer"),
        fee_class=_required_text(operation.get("fee_class"), "fee_class"),
        created_at=_required_text(operation.get("created_at"), "created_at"),
        expires_at=_optional_text(operation.get("expires_at"), "expires_at"),
        target_epoch=_optional_text(operation.get("target_epoch"), "target_epoch"),
        payload=payload,
        evidence_references=list(operation.get("evidence_references") or []),
        signatures=list(operation.get("signatures") or []),
    )
    if canonical_record.operation_id == local_operation_id:
        return canonical_record.model_copy(update={"signatures": _signatures(signatures)})

    projected_payload = dict(funding_payload)
    projected_payload["local_operation_id"] = local_operation_id
    sender_wallet = canonical_funding.consumer_funding_account
    return LedgerOperationEnvelope(
        operation_type="SESSION_ESCROW_LOCK",
        operation_version=operation_version,
        protocol_version=protocol_version,
        origin_type="wallet",
        initiator_id=canonical_funding.session_id,
        sender_wallet=sender_wallet,
        sender_sequence=sender_sequence,
        fee_payer=sender_wallet,
        fee_class="session",
        created_at=_required_text(operation.get("created_at"), "created_at"),
        expires_at=_optional_text(operation.get("expires_at"), "expires_at"),
        target_epoch=_optional_text(operation.get("target_epoch"), "target_epoch"),
        payload=projected_payload,
        evidence_references=_references(
            operation.get("evidence_references"),
            canonical_funding.funding_state_hash,
        ),
        signatures=_signatures(signatures),
    )


def build_session_escrow_lock_envelope_from_funding(
    funding: Mapping[str, object] | object,
    *,
    sender_sequence: int,
    signatures: Sequence[str],
    created_at: str,
    expires_at: str | None = None,
    target_epoch: str | None = None,
    operation_version: str = "1.0.0",
    protocol_version: str = "0.1",
) -> LedgerOperationEnvelope:
    """Build a canonical lock without recording a local economic mutation.

    Validator Hypervisors use this at Session-open time. The local Session
    stores the resulting immutable envelope as a pending intent; the wallet
    and local Funding Account change only when the canonical ABCI operation is
    finalized. ``LOCK_PENDING`` is deliberately converted to the canonical
    ``LOCKED`` projection before hashing the envelope.
    """
    if isinstance(funding, Mapping):
        funding_payload = dict(funding)
    else:
        model_dump = getattr(funding, "model_dump", None)
        if not callable(model_dump):
            raise ValueError("funding must be a mapping or SessionFundingAccount")
        funding_payload = model_dump(mode="json")
    if not isinstance(funding_payload, dict):
        raise ValueError("funding projection is invalid")

    from aidn_hypervisor.settlement.models import SessionFundingAccount

    state = funding_payload.get("funding_state")
    if state not in {"LOCK_PENDING", "LOCKED"}:
        raise ValueError("canonical Session-open funding must be LOCK_PENDING or LOCKED")
    funding_payload["funding_state"] = "LOCKED"
    funding_payload["funding_state_hash"] = None
    try:
        canonical_funding = SessionFundingAccount.model_validate(funding_payload)
    except ValueError as error:
        raise ValueError(f"funding projection is invalid: {error}") from error
    if sender_sequence < 1:
        raise ValueError("canonical escrow sender sequence must be positive")
    created_at = _required_text(created_at, "created_at")
    sender_wallet = canonical_funding.consumer_funding_account
    return LedgerOperationEnvelope(
        operation_type="SESSION_ESCROW_LOCK",
        operation_version=operation_version,
        protocol_version=protocol_version,
        origin_type="wallet",
        initiator_id=canonical_funding.session_id,
        sender_wallet=sender_wallet,
        sender_sequence=sender_sequence,
        fee_payer=sender_wallet,
        fee_class="session",
        created_at=created_at,
        expires_at=expires_at,
        target_epoch=target_epoch,
        payload=canonical_funding.model_dump(mode="json"),
        evidence_references=[
            canonical_funding.session_contract_hash or canonical_funding.session_id,
            canonical_funding.funding_state_hash or canonical_funding.session_id,
        ],
        signatures=_signatures(signatures),
    )


def build_session_settlement_ready_envelope(
    *,
    ready,
    funding_predecessor_operation_id: str,
    fee_payer: str,
    created_at: str,
    signatures: Sequence[str],
    operation_version: str = "1.0.0",
    protocol_version: str = "0.1",
) -> LedgerOperationEnvelope:
    """Build the canonical, no-funds-moving Settlement readiness envelope."""
    from aidn_hypervisor.settlement.models import SettlementReadyCommitment

    try:
        commitment = SettlementReadyCommitment.model_validate(ready)
    except ValueError as error:
        raise ValueError(f"Settlement readiness projection is invalid: {error}") from error
    funding_predecessor_operation_id = _required_text(
        funding_predecessor_operation_id,
        "funding_predecessor_operation_id",
    )
    fee_payer = _required_text(fee_payer, "fee_payer")
    created_at = _required_text(created_at, "created_at")
    return LedgerOperationEnvelope(
        operation_type="SESSION_SETTLEMENT_READY_COMMIT",
        operation_version=operation_version,
        protocol_version=protocol_version,
        origin_type="multi_party",
        initiator_id=commitment.session_id,
        fee_payer=fee_payer,
        fee_class="session",
        created_at=created_at,
        payload={
            "session_id": commitment.session_id,
            "funding_predecessor_operation_id": funding_predecessor_operation_id,
            "ready": commitment.model_dump(mode="json"),
        },
        evidence_references=_references(
            funding_predecessor_operation_id,
            commitment.settlement_input_root,
            commitment.commitment_hash,
            commitment.session_close_reference,
        ),
        signatures=_signatures(signatures),
    )


def build_session_settlement_propose_envelope(
    *,
    proposal,
    funding,
    funding_predecessor_operation_id: str,
    settlement_ready_operation_id: str,
    created_at: str,
    signatures: Sequence[str],
    operation_version: str = "1.0.0",
    protocol_version: str = "0.1",
) -> LedgerOperationEnvelope:
    """Build a canonical Settlement proposal bound to readiness and funding."""
    from aidn_hypervisor.settlement.models import (
        SessionFundingAccount,
        SessionSettlementProposal,
    )

    try:
        typed_proposal = SessionSettlementProposal.model_validate(proposal)
        typed_funding = SessionFundingAccount.model_validate(funding)
    except ValueError as error:
        raise ValueError(f"Settlement proposal projection is invalid: {error}") from error
    if typed_proposal.session_id != typed_funding.session_id:
        raise ValueError("Settlement proposal and funding sessions differ")
    funding_state_reference = _required_text(
        typed_funding.funding_state_hash,
        "funding_state_hash",
    )
    funding_predecessor_operation_id = _required_text(
        funding_predecessor_operation_id,
        "funding_predecessor_operation_id",
    )
    settlement_ready_operation_id = _required_text(
        settlement_ready_operation_id,
        "settlement_ready_operation_id",
    )
    return LedgerOperationEnvelope(
        operation_type="SESSION_SETTLEMENT_PROPOSE",
        operation_version=operation_version,
        protocol_version=protocol_version,
        origin_type="multi_party",
        initiator_id=typed_proposal.session_id,
        fee_payer=typed_funding.consumer_funding_account,
        fee_class="session",
        created_at=_required_text(created_at, "created_at"),
        payload={
            "proposal": typed_proposal.model_dump(mode="json"),
            "session_id": typed_proposal.session_id,
            "funding_state_reference": funding_state_reference,
            "endpoint_payment_beneficiary": typed_funding.endpoint_payment_beneficiary,
            "consumer_refund_beneficiary": typed_funding.consumer_refund_beneficiary,
            "funding_predecessor_operation_id": funding_predecessor_operation_id,
            "settlement_ready_operation_id": settlement_ready_operation_id,
        },
        evidence_references=_references(
            funding_predecessor_operation_id,
            settlement_ready_operation_id,
            typed_proposal.settlement_id,
            typed_proposal.settlement_input_root,
            typed_proposal.request_settlement_root,
            typed_proposal.usage_chain_root,
            typed_proposal.checkpoint_root,
        ),
        signatures=_signatures(signatures),
    )


def build_session_settlement_accept_envelope(
    *,
    acceptance,
    proposal_operation_id: str,
    consumer_wallet: str,
    created_at: str,
    signatures: Sequence[str] | None = None,
    operation_version: str = "1.0.0",
    protocol_version: str = "0.1",
) -> LedgerOperationEnvelope:
    """Build a canonical Consumer acceptance for one proposal."""
    from aidn_hypervisor.settlement.models import SessionSettlementAcceptance

    try:
        typed_acceptance = SessionSettlementAcceptance.model_validate(acceptance)
    except ValueError as error:
        raise ValueError(f"Settlement acceptance projection is invalid: {error}") from error
    proposal_operation_id = _required_text(proposal_operation_id, "proposal_operation_id")
    consumer_wallet = _required_text(consumer_wallet, "consumer_wallet")
    authorization_signatures = signatures or [typed_acceptance.consumer_signature]
    return LedgerOperationEnvelope(
        operation_type="SESSION_SETTLEMENT_ACCEPT",
        operation_version=operation_version,
        protocol_version=protocol_version,
        origin_type="multi_party",
        initiator_id=typed_acceptance.session_id,
        fee_payer=consumer_wallet,
        fee_class="session",
        created_at=_required_text(created_at, "created_at"),
        payload={
            "acceptance": typed_acceptance.model_dump(mode="json"),
            "proposal_operation_id": proposal_operation_id,
            "consumer_wallet": consumer_wallet,
        },
        evidence_references=_references(
            proposal_operation_id,
            typed_acceptance.settlement_id,
            typed_acceptance.settlement_input_root,
            typed_acceptance.acceptance_hash,
        ),
        signatures=_signatures(
            authorization_signatures,
            required=typed_acceptance.consumer_signature,
        ),
    )


def build_session_settlement_finalize_envelope(
    *,
    proposal,
    acceptance,
    transition,
    proposal_operation_id: str,
    acceptance_operation_id: str,
    consumer_wallet: str,
    created_at: str,
    signatures: Sequence[str],
    operation_version: str = "1.0.0",
    protocol_version: str = "0.1",
) -> LedgerOperationEnvelope:
    """Build the canonical atomic Settlement funding transition."""
    from aidn_hypervisor.settlement.models import (
        AtomicSettlementTransition,
        SessionSettlementAcceptance,
        SessionSettlementProposal,
    )

    try:
        typed_proposal = SessionSettlementProposal.model_validate(proposal)
        typed_acceptance = SessionSettlementAcceptance.model_validate(acceptance)
        typed_transition = AtomicSettlementTransition.model_validate(transition)
    except ValueError as error:
        raise ValueError(f"Settlement finalization projection is invalid: {error}") from error
    if (
        typed_transition.session_id != typed_proposal.session_id
        or typed_transition.settlement_id != typed_proposal.settlement_id
        or typed_acceptance.settlement_id != typed_proposal.settlement_id
    ):
        raise ValueError("Settlement finalization identities do not match")
    proposal_operation_id = _required_text(proposal_operation_id, "proposal_operation_id")
    acceptance_operation_id = _required_text(
        acceptance_operation_id,
        "acceptance_operation_id",
    )
    consumer_wallet = _required_text(consumer_wallet, "consumer_wallet")
    return LedgerOperationEnvelope(
        operation_type="SESSION_SETTLEMENT_FINALIZE",
        operation_version=operation_version,
        protocol_version=protocol_version,
        origin_type="multi_party",
        initiator_id=typed_transition.session_id,
        fee_payer=consumer_wallet,
        fee_class="session",
        created_at=_required_text(created_at, "created_at"),
        payload={
            "transition": typed_transition.model_dump(mode="json"),
            "session_id": typed_proposal.session_id,
            "settlement_input_root": typed_proposal.settlement_input_root,
            "proposal_operation_id": proposal_operation_id,
            "acceptance_operation_id": acceptance_operation_id,
            "acceptance_hash": typed_acceptance.acceptance_hash,
        },
        evidence_references=_references(
            proposal_operation_id,
            acceptance_operation_id,
            typed_proposal.settlement_id,
            typed_proposal.settlement_input_root,
        ),
        signatures=_signatures(signatures),
    )


def build_session_force_settle_envelope(
    operation: Mapping[str, object],
    *,
    funding_lock_operation_id: str,
    failure_evidence_operation_id: str,
    initiator_wallet: str,
    initiator_signature: str,
    observed_at: str,
    transition: Mapping[str, object],
    signatures: Sequence[str],
    operation_version: str = "1.0.0",
    protocol_version: str = "0.1",
) -> LedgerOperationEnvelope:
    """Build a canonical Forced Settlement envelope with explicit dependencies."""
    payload = _local_operation_payload(operation, "SESSION_FORCE_SETTLE")
    local_operation_id = _required_text(operation.get("operation_id"), "operation_id")
    session_id = _required_text(payload.get("session_id"), "payload.session_id")
    failure_root = _required_text(
        payload.get("failure_evidence_root"),
        "payload.failure_evidence_root",
    )
    settlement_id = _required_text(
        payload.get("settlement_id"),
        "payload.settlement_id",
    )
    funding_lock_operation_id = _required_text(
        funding_lock_operation_id,
        "funding_lock_operation_id",
    )
    failure_evidence_operation_id = _required_text(
        failure_evidence_operation_id,
        "failure_evidence_operation_id",
    )
    if local_operation_id in {funding_lock_operation_id, failure_evidence_operation_id}:
        raise ValueError("consensus dependency cannot reuse the local operation ID")
    if not isinstance(transition, Mapping) or not transition:
        raise ValueError("consensus projection requires a settlement transition")
    if transition.get("session_id") != session_id:
        raise ValueError("consensus transition session binding is invalid")
    if transition.get("settlement_id") != settlement_id:
        raise ValueError("consensus transition Settlement binding is invalid")
    initiator_wallet = _required_text(initiator_wallet, "initiator_wallet")
    initiator_signature = _required_text(initiator_signature, "initiator_signature")
    observed_at = _required_text(observed_at, "observed_at")
    projected_payload = dict(payload)
    existing_local_id = projected_payload.get("local_operation_id")
    if existing_local_id is not None and existing_local_id != local_operation_id:
        raise ValueError("local operation correlation is conflicting")
    projected_payload.update(
        {
            "local_operation_id": local_operation_id,
            "failure_evidence_operation_id": failure_evidence_operation_id,
            "funding_lock_operation_id": funding_lock_operation_id,
            "initiator_wallet": initiator_wallet,
            "initiator_signature": initiator_signature,
            "observed_at": observed_at,
            "transition": dict(transition),
        }
    )
    envelope_signatures = _signatures(signatures, required=initiator_signature)
    return LedgerOperationEnvelope(
        operation_type="SESSION_FORCE_SETTLE",
        operation_version=operation_version,
        protocol_version=protocol_version,
        origin_type="evidence_triggered",
        initiator_id=session_id,
        fee_payer=_required_text(operation.get("fee_payer"), "fee_payer"),
        fee_class="session",
        created_at=_required_text(operation.get("created_at"), "created_at"),
        expires_at=_optional_text(operation.get("expires_at"), "expires_at"),
        target_epoch=_optional_text(operation.get("target_epoch"), "target_epoch"),
        payload=projected_payload,
        evidence_references=_references(
            operation.get("evidence_references"),
            failure_root,
            settlement_id,
            funding_lock_operation_id,
            failure_evidence_operation_id,
            projected_payload.get("settlement_input_root"),
            projected_payload.get("request_settlement_root"),
            projected_payload.get("usage_chain_root"),
            projected_payload.get("checkpoint_root"),
            projected_payload.get("provider_usage_report_hashes"),
            [
                item.get("record_hash")
                for item in projected_payload.get("request_evidence", [])
                if isinstance(item, Mapping)
            ],
        ),
        signatures=envelope_signatures,
    )
