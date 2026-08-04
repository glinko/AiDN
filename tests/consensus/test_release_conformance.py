"""Machine-readable GATE-0001 deterministic protocol probes."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from aidn_hypervisor.consensus.abci import AIDNABCIApplication
from aidn_hypervisor.consensus.admission import AdmissionValidator
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.ledger.service import LedgerOperationService
from aidn_hypervisor.settlement import SessionFundingAccount, SessionSettlementProposal


def _app(*, strict: bool = True) -> AIDNABCIApplication:
    return AIDNABCIApplication(
        ledger_service=LedgerOperationService(),
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        strict_operation_coverage=strict,
    )


def _tx(**overrides: object) -> bytes:
    values: dict[str, object] = {
        "operation_type": "WALLET_TRANSFER",
        "operation_version": "1.0.0",
        "protocol_version": "0.1",
        "origin_type": "protocol",
        "created_at": "2030-01-01T00:00:00Z",
        "payload": {},
    }
    values.update(overrides)
    envelope = LedgerOperationEnvelope.model_validate(values)
    return json.dumps(envelope.model_dump(mode="json")).encode("utf-8")


def test_unknown_operation_is_rejected_before_mempool_mutation() -> None:
    app = _app()

    result = app.process_proposal_transaction(_tx(operation_type="UNKNOWN_OPERATION"))

    assert result.code == "rejected"
    assert result.log == "consensus operation type is not registered: UNKNOWN_OPERATION"
    assert app.mempool.size() == 0


def test_unsupported_operation_version_is_rejected() -> None:
    app = _app()

    result = app.process_proposal_transaction(_tx(operation_version="9.9.9"))

    assert result.code == "rejected"
    assert result.log == "unsupported operation version: WALLET_TRANSFER:9.9.9"


def test_duplicate_operation_is_idempotent_in_mempool() -> None:
    app = _app(strict=False)
    tx = _tx(payload={"idempotency": "same-operation"})

    first = app.process_proposal_transaction(tx)
    second = app.process_proposal_transaction(tx)

    assert first.code == "ok"
    assert second.code == "duplicate"
    assert app.mempool.size() == 1


def test_negative_and_reserve_overflow_values_are_rejected() -> None:
    with pytest.raises(ValidationError):
        SessionFundingAccount(
            session_id="session-boundary",
            funding_class="ESCROW_PREPAID",
            consumer_funding_account="wallet-consumer",
            endpoint_payment_beneficiary="wallet-endpoint",
            consumer_refund_beneficiary="wallet-consumer",
            total_locked_amount_q_atoms=0,
            endpoint_payment_reserve_q_atoms=-1,
            network_fee_reserve_q_atoms=1,
        )


def test_settlement_rejects_a_stale_funding_predecessor() -> None:
    ledger = LedgerOperationService()
    funding = SessionFundingAccount(
        session_id="session-predecessor",
        session_contract_hash="sha256:contract",
        funding_class="ESCROW_PREPAID",
        consumer_funding_account="wallet-consumer",
        endpoint_payment_beneficiary="wallet-endpoint",
        consumer_refund_beneficiary="wallet-consumer",
        total_locked_amount_q_atoms=100,
        endpoint_payment_reserve_q_atoms=100,
        network_fee_reserve_q_atoms=0,
        unsettled_payment_reserve_q_atoms=100,
        unsettled_fee_reserve_q_atoms=0,
    )
    ledger.credit_wallet_q_atoms(wallet_id="wallet-consumer", amount_q_atoms=100)
    locked = ledger.lock_session_funding(funding, created_at="2030-01-01T00:00:00Z")
    proposal = SessionSettlementProposal(
        settlement_id="settlement-predecessor",
        settlement_sequence=1,
        session_id=locked.session_id,
        settlement_input_root="sha256:input",
        request_settlement_root="sha256:requests",
        usage_chain_root="sha256:usage",
        checkpoint_root="sha256:checkpoints",
        gross_session_charge_q_atoms=0,
        capped_session_charge_q_atoms=0,
        final_endpoint_payment_q_atoms=0,
        requested_endpoint_payment_q_atoms=0,
        consumer_payment_refund_q_atoms=100,
        actual_network_fees_q_atoms=0,
        consumer_fee_refund_q_atoms=0,
        disputed_amount_q_atoms=0,
        dispute_reserve_q_atoms=0,
        endpoint_absorbed_amount_q_atoms=0,
        settlement_mode="COOPERATIVE_FINAL",
    )
    envelope = LedgerOperationEnvelope(
        operation_type="SESSION_SETTLEMENT_PROPOSE",
        origin_type="multi_party",
        fee_payer="wallet-consumer",
        fee_class="session",
        created_at="2030-01-01T00:00:00Z",
        payload={
            "session_id": locked.session_id,
            "funding_lock_operation_id": "stale-predecessor",
            "funding_state_reference": locked.funding_state_hash,
            "endpoint_payment_beneficiary": locked.endpoint_payment_beneficiary,
            "consumer_refund_beneficiary": locked.consumer_refund_beneficiary,
            "proposal": proposal.model_dump(mode="json"),
        },
        evidence_references=["stale-predecessor", "sha256:input"],
    )

    with pytest.raises(ValueError, match="funding predecessor is not finalized"):
        ledger.validate_consensus_settlement_propose(
            envelope,
            finalized_operation_ids=ledger.finalized_operation_ids(),
        )

    with pytest.raises(ValidationError, match="locked amount must equal payment plus fee reserves"):
        SessionFundingAccount(
            session_id="session-overflow",
            funding_class="ESCROW_PREPAID",
            consumer_funding_account="wallet-consumer",
            endpoint_payment_beneficiary="wallet-endpoint",
            consumer_refund_beneficiary="wallet-consumer",
            total_locked_amount_q_atoms=1,
            endpoint_payment_reserve_q_atoms=1,
            network_fee_reserve_q_atoms=1,
        )


def test_canonical_envelope_golden_vector() -> None:
    envelope = LedgerOperationEnvelope(
        operation_type="WALLET_TRANSFER",
        origin_type="protocol",
        created_at="2030-01-01T00:00:00Z",
    )

    assert envelope.canonical_bytes().decode("utf-8") == (
        '{"created_at":"2030-01-01T00:00:00Z","evidence_references":[],'
        '"expires_at":null,"fee_class":"standard","fee_payer":null,'
        '"initiator_id":null,"operation_id":"","operation_type":"WALLET_TRANSFER",'
        '"operation_version":"1.0.0","origin_type":"protocol","payload":{},'
        '"protocol_version":"0.1","sender_sequence":null,"sender_wallet":null,'
        '"signatures":[],"target_epoch":null}'
    )
