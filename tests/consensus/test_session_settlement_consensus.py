from __future__ import annotations

import json

from aidn_hypervisor.consensus.abci import AIDNABCIApplication
from aidn_hypervisor.consensus.admission import AdmissionValidator
from aidn_hypervisor.consensus.execution import ExecutionEngine
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.ledger.service import LedgerOperationService
from aidn_hypervisor.settlement.models import (
    AtomicSettlementTransition,
    SessionFundingAccount,
    SessionSettlementAcceptance,
    SessionSettlementProposal,
    SettlementCorrection,
    SettlementDispute,
    SettlementReadyCommitment,
)

SESSION_ID = "session-settlement-consensus-1"
INPUT_ROOT = "sha256:settlement-input-1"


def _funding() -> SessionFundingAccount:
    return SessionFundingAccount(
        session_id=SESSION_ID,
        session_contract_hash="sha256:session-contract",
        funding_class="ESCROW_PREPAID",
        consumer_funding_account="wallet:consumer",
        endpoint_payment_beneficiary="wallet:endpoint",
        consumer_refund_beneficiary="wallet:consumer",
        total_locked_amount_q_atoms=1_100,
        endpoint_payment_reserve_q_atoms=1_000,
        network_fee_reserve_q_atoms=100,
        unsettled_payment_reserve_q_atoms=1_000,
        unsettled_fee_reserve_q_atoms=100,
    )


def _extended_funding(funding: SessionFundingAccount) -> SessionFundingAccount:
    payload = funding.model_dump(mode="json")
    payload.update(
        {
            "total_locked_amount_q_atoms": 1_450,
            "endpoint_payment_reserve_q_atoms": 1_300,
            "network_fee_reserve_q_atoms": 150,
            "unsettled_payment_reserve_q_atoms": 1_300,
            "unsettled_fee_reserve_q_atoms": 150,
        }
    )
    payload.pop("funding_state_hash", None)
    return SessionFundingAccount.model_validate(payload)


def _envelope(
    operation_type: str,
    payload: dict,
    *,
    origin_type: str = "multi_party",
    sender_wallet: str | None = None,
    sender_sequence: int | None = None,
    fee_payer: str = "wallet:consumer",
    signatures: list[str] | None = None,
    evidence_references: list[str],
) -> bytes:
    envelope = LedgerOperationEnvelope(
        operation_type=operation_type,
        operation_version="1.0.0",
        protocol_version="0.1",
        origin_type=origin_type,
        initiator_id=SESSION_ID,
        sender_wallet=sender_wallet,
        sender_sequence=sender_sequence,
        fee_payer=fee_payer,
        fee_class="session",
        created_at="2030-01-01T00:00:00Z",
        expires_at="2030-01-02T00:00:00Z",
        payload=payload,
        evidence_references=evidence_references,
        signatures=signatures or ["ed25519:session-party"],
    )
    return json.dumps(envelope.model_dump(mode="json")).encode("utf-8")


def _lock_envelope(funding: SessionFundingAccount) -> bytes:
    envelope = LedgerOperationEnvelope(
        operation_type="SESSION_ESCROW_LOCK",
        operation_version="1.0.0",
        protocol_version="0.1",
        origin_type="wallet",
        initiator_id=SESSION_ID,
        sender_wallet="wallet:consumer",
        sender_sequence=1,
        fee_payer="wallet:consumer",
        fee_class="session",
        created_at="2030-01-01T00:00:00Z",
        expires_at="2030-01-02T00:00:00Z",
        payload=funding.model_dump(mode="json"),
        signatures=["ed25519:consumer"],
    )
    return json.dumps(envelope.model_dump(mode="json")).encode("utf-8")


def _extend_envelope(
    current: SessionFundingAccount,
    next_funding: SessionFundingAccount,
    *,
    previous_operation_id: str,
) -> bytes:
    return _envelope(
        "SESSION_ESCROW_EXTEND",
        {
            "session_id": SESSION_ID,
            "extension_id": "extension-settlement-predecessor-1",
            "funding_state_reference": current.funding_state_hash,
            "previous_funding_operation_id": previous_operation_id,
            "added_endpoint_payment_reserve_q_atoms": 300,
            "added_network_fee_reserve_q_atoms": 50,
            "funding": next_funding.model_dump(mode="json"),
        },
        origin_type="wallet",
        sender_wallet="wallet:consumer",
        sender_sequence=2,
        fee_payer="wallet:consumer",
        signatures=["ed25519:consumer"],
        evidence_references=[
            previous_operation_id,
            current.funding_state_hash,
            next_funding.funding_state_hash,
        ],
    )


def _proposal(funding: SessionFundingAccount) -> SessionSettlementProposal:
    return SessionSettlementProposal(
        settlement_id="settlement-consensus-1",
        settlement_sequence=1,
        session_id=SESSION_ID,
        settlement_input_root=INPUT_ROOT,
        request_settlement_root="sha256:requests-1",
        usage_chain_root="sha256:usage-1",
        checkpoint_root="sha256:checkpoints-1",
        gross_session_charge_q_atoms=800,
        capped_session_charge_q_atoms=800,
        final_endpoint_payment_q_atoms=800,
        requested_endpoint_payment_q_atoms=800,
        consumer_payment_refund_q_atoms=200,
        actual_network_fees_q_atoms=20,
        consumer_fee_refund_q_atoms=80,
        disputed_amount_q_atoms=0,
        dispute_reserve_q_atoms=0,
        endpoint_absorbed_amount_q_atoms=0,
        settlement_mode="COOPERATIVE_FINAL",
        proposal_expiration="2030-01-02T00:00:00Z",
    )


def _proposal_tx(
    funding: SessionFundingAccount,
    *,
    funding_lock_operation_id: str,
    settlement_ready_operation_id: str | None = None,
) -> bytes:
    proposal = _proposal(funding)
    payload = {
        "session_id": SESSION_ID,
        "funding_lock_operation_id": funding_lock_operation_id,
        "funding_state_reference": funding.funding_state_hash,
        "endpoint_payment_beneficiary": "wallet:endpoint",
        "consumer_refund_beneficiary": "wallet:consumer",
        "proposal": proposal.model_dump(mode="json"),
    }
    evidence_references = [funding_lock_operation_id, INPUT_ROOT]
    if settlement_ready_operation_id is not None:
        payload["settlement_ready_operation_id"] = settlement_ready_operation_id
        evidence_references.append(settlement_ready_operation_id)
    return _envelope(
        "SESSION_SETTLEMENT_PROPOSE",
        payload,
        evidence_references=evidence_references,
    )


def _ready_tx(
    funding: SessionFundingAccount,
    *,
    funding_lock_operation_id: str,
    input_root: str = INPUT_ROOT,
) -> bytes:
    ready = SettlementReadyCommitment(
        session_id=SESSION_ID,
        settlement_sequence=1,
        session_contract_hash=funding.session_contract_hash,
        effective_terms_hash="sha256:effective-terms-1",
        funding_state_reference=funding.funding_state_hash,
        endpoint_payment_beneficiary=funding.endpoint_payment_beneficiary,
        consumer_refund_beneficiary=funding.consumer_refund_beneficiary,
        request_settlement_root="sha256:requests-1",
        usage_chain_root="sha256:usage-1",
        checkpoint_root="sha256:checkpoints-1",
        settlement_input_root=input_root,
        session_close_reference="sha256:session-close-1",
        ready_at="2030-01-01T00:00:00Z",
    )
    return _envelope(
        "SESSION_SETTLEMENT_READY_COMMIT",
        {
            "session_id": SESSION_ID,
            "funding_predecessor_operation_id": funding_lock_operation_id,
            "ready": ready.model_dump(mode="json"),
        },
        evidence_references=[
            funding_lock_operation_id,
            input_root,
            ready.commitment_hash,
            ready.session_close_reference,
        ],
    )


def _accept_tx(*, proposal_operation_id: str) -> bytes:
    acceptance = SessionSettlementAcceptance(
        settlement_id="settlement-consensus-1",
        session_id=SESSION_ID,
        settlement_input_root=INPUT_ROOT,
        accepted_endpoint_payment_q_atoms=800,
        accepted_consumer_refund_q_atoms=280,
        accepted_network_fees_q_atoms=20,
        consumer_signature="ed25519:consumer-acceptance",
        accepted_at="2030-01-01T00:00:00Z",
    )
    return _envelope(
        "SESSION_SETTLEMENT_ACCEPT",
        {
            "proposal_operation_id": proposal_operation_id,
            "consumer_wallet": "wallet:consumer",
            "acceptance": acceptance.model_dump(mode="json"),
        },
        evidence_references=[proposal_operation_id, INPUT_ROOT],
    )


def _finalize_tx(*, proposal_operation_id: str, acceptance_operation_id: str) -> bytes:
    transition = AtomicSettlementTransition(
        session_id=SESSION_ID,
        settlement_id="settlement-consensus-1",
        endpoint_payment_beneficiary="wallet:endpoint",
        consumer_refund_beneficiary="wallet:consumer",
        previously_released_to_endpoint_q_atoms=0,
        previously_refunded_to_consumer_q_atoms=0,
        previously_consumed_network_fees_q_atoms=0,
        credit_endpoint_q_atoms=800,
        credit_consumer_q_atoms=280,
        consume_network_fees_q_atoms=20,
        retain_dispute_reserve_q_atoms=0,
        total_locked_amount_q_atoms=1_100,
    )
    return _envelope(
        "SESSION_SETTLEMENT_FINALIZE",
        {
            "session_id": SESSION_ID,
            "settlement_input_root": INPUT_ROOT,
            "proposal_operation_id": proposal_operation_id,
            "acceptance_operation_id": acceptance_operation_id,
            "acceptance_hash": SessionSettlementAcceptance(
                settlement_id="settlement-consensus-1",
                session_id=SESSION_ID,
                settlement_input_root=INPUT_ROOT,
                accepted_endpoint_payment_q_atoms=800,
                accepted_consumer_refund_q_atoms=280,
                accepted_network_fees_q_atoms=20,
                consumer_signature="ed25519:consumer-acceptance",
                accepted_at="2030-01-01T00:00:00Z",
            ).acceptance_hash,
            "transition": transition.model_dump(mode="json"),
        },
        evidence_references=[
            proposal_operation_id,
            acceptance_operation_id,
            INPUT_ROOT,
            "settlement-consensus-1",
        ],
    )


def _disputed_proposal_tx(
    funding: SessionFundingAccount,
    *,
    funding_lock_operation_id: str,
) -> bytes:
    proposal = SessionSettlementProposal(
        settlement_id="settlement-consensus-disputed-1",
        settlement_sequence=1,
        session_id=SESSION_ID,
        settlement_input_root="sha256:settlement-input-disputed-1",
        request_settlement_root="sha256:requests-disputed-1",
        usage_chain_root="sha256:usage-disputed-1",
        checkpoint_root="sha256:checkpoints-disputed-1",
        gross_session_charge_q_atoms=800,
        capped_session_charge_q_atoms=800,
        final_endpoint_payment_q_atoms=800,
        requested_endpoint_payment_q_atoms=800,
        consumer_payment_refund_q_atoms=100,
        actual_network_fees_q_atoms=20,
        consumer_fee_refund_q_atoms=80,
        disputed_amount_q_atoms=100,
        dispute_reserve_q_atoms=100,
        endpoint_absorbed_amount_q_atoms=0,
        settlement_mode="PARTIAL_UNDISPUTED",
        proposal_expiration="2030-01-02T00:00:00Z",
    )
    return _envelope(
        "SESSION_SETTLEMENT_PROPOSE",
        {
            "session_id": SESSION_ID,
            "funding_lock_operation_id": funding_lock_operation_id,
            "funding_state_reference": funding.funding_state_hash,
            "endpoint_payment_beneficiary": "wallet:endpoint",
            "consumer_refund_beneficiary": "wallet:consumer",
            "proposal": proposal.model_dump(mode="json"),
        },
        evidence_references=[
            funding_lock_operation_id,
            proposal.settlement_input_root,
        ],
    )


def _disputed_accept_tx(*, proposal_operation_id: str) -> bytes:
    acceptance = SessionSettlementAcceptance(
        settlement_id="settlement-consensus-disputed-1",
        session_id=SESSION_ID,
        settlement_input_root="sha256:settlement-input-disputed-1",
        accepted_endpoint_payment_q_atoms=800,
        accepted_consumer_refund_q_atoms=180,
        accepted_network_fees_q_atoms=20,
        consumer_signature="ed25519:consumer-disputed-acceptance",
        accepted_at="2030-01-01T00:00:00Z",
    )
    return _envelope(
        "SESSION_SETTLEMENT_ACCEPT",
        {
            "proposal_operation_id": proposal_operation_id,
            "consumer_wallet": "wallet:consumer",
            "acceptance": acceptance.model_dump(mode="json"),
        },
        evidence_references=[proposal_operation_id, acceptance.settlement_input_root],
    )


def _dispute_tx(*, proposal_operation_id: str) -> bytes:
    dispute = SettlementDispute(
        dispute_id="dispute-consensus-1",
        settlement_id="settlement-consensus-disputed-1",
        session_id=SESSION_ID,
        disputed_request_ids=["request-disputed-1"],
        disputed_usage_report_ids=["usage-report-disputed-1"],
        disputed_checkpoint_ids=[],
        dispute_class="USAGE_VALUE",
        claimed_endpoint_payment_q_atoms=900,
        accepted_endpoint_payment_q_atoms=800,
        disputed_amount_q_atoms=100,
        evidence_root="sha256:dispute-evidence-1",
        opened_at="2030-01-01T00:00:00Z",
        claimant_signature="ed25519:consumer-dispute",
    )
    return _envelope(
        "SESSION_SETTLEMENT_DISPUTE",
        {
            "session_id": SESSION_ID,
            "settlement_id": dispute.settlement_id,
            "settlement_input_root": "sha256:settlement-input-disputed-1",
            "proposal_operation_id": proposal_operation_id,
            "claimant_wallet": "wallet:consumer",
            "dispute": dispute.model_dump(mode="json"),
        },
        evidence_references=[
            proposal_operation_id,
            "sha256:settlement-input-disputed-1",
            dispute.dispute_id,
            dispute.dispute_hash,
            dispute.evidence_root,
        ],
    )


def _partial_finalize_tx(
    *,
    proposal_operation_id: str,
    acceptance_operation_id: str,
    dispute_operation_id: str,
) -> bytes:
    acceptance = SessionSettlementAcceptance(
        settlement_id="settlement-consensus-disputed-1",
        session_id=SESSION_ID,
        settlement_input_root="sha256:settlement-input-disputed-1",
        accepted_endpoint_payment_q_atoms=800,
        accepted_consumer_refund_q_atoms=180,
        accepted_network_fees_q_atoms=20,
        consumer_signature="ed25519:consumer-disputed-acceptance",
        accepted_at="2030-01-01T00:00:00Z",
    )
    dispute = SettlementDispute(
        dispute_id="dispute-consensus-1",
        settlement_id="settlement-consensus-disputed-1",
        session_id=SESSION_ID,
        disputed_request_ids=["request-disputed-1"],
        disputed_usage_report_ids=["usage-report-disputed-1"],
        disputed_checkpoint_ids=[],
        dispute_class="USAGE_VALUE",
        claimed_endpoint_payment_q_atoms=900,
        accepted_endpoint_payment_q_atoms=800,
        disputed_amount_q_atoms=100,
        evidence_root="sha256:dispute-evidence-1",
        opened_at="2030-01-01T00:00:00Z",
        claimant_signature="ed25519:consumer-dispute",
    )
    transition = AtomicSettlementTransition(
        session_id=SESSION_ID,
        settlement_id="settlement-consensus-disputed-1",
        endpoint_payment_beneficiary="wallet:endpoint",
        consumer_refund_beneficiary="wallet:consumer",
        previously_released_to_endpoint_q_atoms=0,
        previously_refunded_to_consumer_q_atoms=0,
        previously_consumed_network_fees_q_atoms=0,
        credit_endpoint_q_atoms=800,
        credit_consumer_q_atoms=180,
        consume_network_fees_q_atoms=20,
        retain_dispute_reserve_q_atoms=100,
        total_locked_amount_q_atoms=1_100,
    )
    return _envelope(
        "SESSION_SETTLEMENT_PARTIAL_FINALIZE",
        {
            "session_id": SESSION_ID,
            "settlement_input_root": "sha256:settlement-input-disputed-1",
            "proposal_operation_id": proposal_operation_id,
            "acceptance_operation_id": acceptance_operation_id,
            "dispute_operation_id": dispute_operation_id,
            "acceptance_hash": acceptance.acceptance_hash,
            "dispute_hash": dispute.dispute_hash,
            "transition": transition.model_dump(mode="json"),
        },
        evidence_references=[
            proposal_operation_id,
            acceptance_operation_id,
            dispute_operation_id,
            "sha256:settlement-input-disputed-1",
            "settlement-consensus-disputed-1",
            acceptance.acceptance_hash,
            dispute.dispute_hash,
            dispute.evidence_root,
        ],
    )


def _correction_tx(
    *,
    partial_finalize_operation_id: str,
    prior_transition_hash: str,
    endpoint_payment_delta_q_atoms: int = 0,
    consumer_refund_delta_q_atoms: int = 100,
    network_fee_delta_q_atoms: int = 0,
    dispute_reserve_delta_q_atoms: int = -100,
) -> bytes:
    correction = SettlementCorrection(
        correction_id="correction-consensus-1",
        settlement_id="settlement-consensus-disputed-1",
        correction_reason="accepted dispute resolution to Consumer",
        prior_result_hash=prior_transition_hash,
        endpoint_payment_delta_q_atoms=endpoint_payment_delta_q_atoms,
        consumer_refund_delta_q_atoms=consumer_refund_delta_q_atoms,
        network_fee_delta_q_atoms=network_fee_delta_q_atoms,
        dispute_reserve_delta_q_atoms=dispute_reserve_delta_q_atoms,
        authorization_reference="resolution:consumer-dispute-1",
        evidence_root="sha256:correction-evidence-1",
        created_at="2030-01-01T00:00:00Z",
        correction_signature="ed25519:settlement-authority",
    )
    return _envelope(
        "SESSION_SETTLEMENT_CORRECT",
        {
            "session_id": SESSION_ID,
            "settlement_id": correction.settlement_id,
            "settlement_input_root": "sha256:settlement-input-disputed-1",
            "partial_finalize_operation_id": partial_finalize_operation_id,
            "endpoint_payment_beneficiary": "wallet:endpoint",
            "consumer_refund_beneficiary": "wallet:consumer",
            "correction": correction.model_dump(mode="json"),
        },
        signatures=["ed25519:endpoint", "ed25519:consumer"],
        evidence_references=[
            partial_finalize_operation_id,
            "sha256:settlement-input-disputed-1",
            correction.correction_id,
            correction.correction_hash,
            correction.prior_result_hash,
            correction.authorization_reference,
            correction.evidence_root,
        ],
    )


def _abci() -> tuple[AIDNABCIApplication, LedgerOperationService]:
    ledger = LedgerOperationService()
    ledger.credit_wallet_q_atoms(wallet_id="wallet:consumer", amount_q_atoms=2_000)
    app = AIDNABCIApplication(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
    )
    return app, ledger


def _lock_and_propose_abci() -> tuple[
    AIDNABCIApplication,
    LedgerOperationService,
    SessionFundingAccount,
    str,
]:
    app, ledger = _abci()
    funding = _funding()
    assert app.finalize_block(
        block_height=1,
        block_hash=b"A" * 32,
        txs=[_lock_envelope(funding)],
    ).code == "ok"
    lock_id = ledger.snapshot_operations()[0]["operation_id"]
    assert app.finalize_block(
        block_height=2,
        block_hash=b"B" * 32,
        txs=[_proposal_tx(funding, funding_lock_operation_id=lock_id)],
    ).code == "ok"
    proposal_id = ledger.snapshot_operations()[-1]["operation_id"]
    return app, ledger, funding, proposal_id


def test_abci_settlement_propose_accept_finalize_moves_exact_amounts() -> None:
    app, ledger, _funding_account, proposal_id = _lock_and_propose_abci()

    accepted = app.finalize_block(
        block_height=3,
        block_hash=b"C" * 32,
        txs=[_accept_tx(proposal_operation_id=proposal_id)],
    )
    assert accepted.code == "ok"
    acceptance_id = ledger.snapshot_operations()[-1]["operation_id"]

    finalized = app.finalize_block(
        block_height=4,
        block_hash=b"D" * 32,
        txs=[
            _finalize_tx(
                proposal_operation_id=proposal_id,
                acceptance_operation_id=acceptance_id,
            )
        ],
    )

    assert finalized.code == "ok"
    assert ledger.wallet_q_atom_balance("wallet:consumer") == 1_180
    assert ledger.wallet_q_atom_balance("wallet:endpoint") == 800
    account = ledger.get_session_funding_account(SESSION_ID)
    assert account.funding_state == "RELEASED"
    assert account.released_to_endpoint_q_atoms == 800
    assert account.consumer_payment_refund_q_atoms == 200
    assert account.consumer_fee_refund_q_atoms == 80
    assert account.consumed_network_fees_q_atoms == 20
    assert ledger.snapshot_operations()[-1]["operation_type"] == (
        "SESSION_SETTLEMENT_FINALIZE"
    )


def test_settlement_dependencies_cannot_be_satisfied_in_one_block() -> None:
    app, ledger = _abci()
    funding = _funding()
    lock_tx = _lock_envelope(funding)
    lock_id = LedgerOperationEnvelope.model_validate(json.loads(lock_tx)).operation_id

    result, tx_results = app.finalize_block_with_results(
        block_height=1,
        block_hash=b"A" * 32,
        txs=[lock_tx, _proposal_tx(funding, funding_lock_operation_id=lock_id)],
    )

    assert result.code == "ok"
    assert [item.code for item in tx_results] == ["ok", "rejected"]
    assert len(ledger.snapshot_operations()) == 1
    assert ledger.snapshot_operations()[0]["operation_type"] == "SESSION_ESCROW_LOCK"


def test_typed_settlement_rejects_disputed_reserve_until_dispute_profile_exists() -> None:
    app, ledger = _abci()
    funding = _funding()
    assert app.finalize_block(
        block_height=1,
        block_hash=b"A" * 32,
        txs=[_lock_envelope(funding)],
    ).code == "ok"
    lock_id = ledger.snapshot_operations()[0]["operation_id"]
    proposal_tx = json.loads(
        _proposal_tx(funding, funding_lock_operation_id=lock_id)
    )
    proposal_tx["payload"]["proposal"]["settlement_mode"] = "PARTIAL_UNDISPUTED"
    proposal_tx["payload"]["proposal"]["dispute_reserve_q_atoms"] = 1
    proposal_tx["operation_id"] = ""

    result, tx_results = app.finalize_block_with_results(
        block_height=2,
        block_hash=b"B" * 32,
        txs=[json.dumps(proposal_tx).encode("utf-8")],
    )

    assert result.code == "ok"
    assert tx_results[0].code == "rejected"
    assert "partial Settlement dispute reserve is invalid" in tx_results[0].log
    assert ledger.get_session_funding_account(SESSION_ID).funding_state == "LOCKED"


def test_abci_settlement_dispute_and_partial_finalize_retain_bounded_reserve() -> None:
    app, ledger = _abci()
    funding = _funding()
    assert app.finalize_block(
        block_height=1,
        block_hash=b"A" * 32,
        txs=[_lock_envelope(funding)],
    ).code == "ok"
    lock_id = ledger.snapshot_operations()[-1]["operation_id"]
    assert app.finalize_block(
        block_height=2,
        block_hash=b"B" * 32,
        txs=[
            _disputed_proposal_tx(
                funding,
                funding_lock_operation_id=lock_id,
            )
        ],
    ).code == "ok"
    proposal_id = ledger.snapshot_operations()[-1]["operation_id"]
    assert app.finalize_block(
        block_height=3,
        block_hash=b"C" * 32,
        txs=[_disputed_accept_tx(proposal_operation_id=proposal_id)],
    ).code == "ok"
    acceptance_id = ledger.snapshot_operations()[-1]["operation_id"]
    assert app.finalize_block(
        block_height=4,
        block_hash=b"D" * 32,
        txs=[_dispute_tx(proposal_operation_id=proposal_id)],
    ).code == "ok"
    dispute_id = ledger.snapshot_operations()[-1]["operation_id"]
    partial = app.finalize_block(
        block_height=5,
        block_hash=b"E" * 32,
        txs=[
            _partial_finalize_tx(
                proposal_operation_id=proposal_id,
                acceptance_operation_id=acceptance_id,
                dispute_operation_id=dispute_id,
            )
        ],
    )

    assert partial.code == "ok"
    assert ledger.wallet_q_atom_balance("wallet:consumer") == 1_080
    assert ledger.wallet_q_atom_balance("wallet:endpoint") == 800
    account = ledger.get_session_funding_account(SESSION_ID)
    assert account.funding_state == "DISPUTE_RESERVED"
    assert account.released_to_endpoint_q_atoms == 800
    assert account.consumer_payment_refund_q_atoms == 100
    assert account.consumer_fee_refund_q_atoms == 80
    assert account.consumed_network_fees_q_atoms == 20
    assert account.active_dispute_reserve_q_atoms == 100
    assert ledger.get_settlement_dispute(
        "settlement-consensus-disputed-1"
    ).disputed_amount_q_atoms == 100
    assert ledger.snapshot_operations()[-1]["operation_type"] == (
        "SESSION_SETTLEMENT_PARTIAL_FINALIZE"
    )

    snapshot = app.prepare_snapshot()
    restored, restored_ledger = _abci()
    assert restored.apply_snapshot(snapshot).code == "ok"
    assert restored_ledger.get_session_funding_account(SESSION_ID).funding_state == (
        "DISPUTE_RESERVED"
    )
    assert restored_ledger.get_settlement_dispute(
        "settlement-consensus-disputed-1"
    ).dispute_id == "dispute-consensus-1"
    assert restored.prepare_snapshot()["app_hash"] == snapshot["app_hash"]


def test_settlement_correction_resolves_active_dispute_reserve() -> None:
    app, ledger = _abci()
    funding = _funding()
    assert app.finalize_block(
        block_height=1,
        block_hash=b"A" * 32,
        txs=[_lock_envelope(funding)],
    ).code == "ok"
    lock_id = ledger.snapshot_operations()[-1]["operation_id"]
    assert app.finalize_block(
        block_height=2,
        block_hash=b"B" * 32,
        txs=[_disputed_proposal_tx(funding, funding_lock_operation_id=lock_id)],
    ).code == "ok"
    proposal_id = ledger.snapshot_operations()[-1]["operation_id"]
    assert app.finalize_block(
        block_height=3,
        block_hash=b"C" * 32,
        txs=[_disputed_accept_tx(proposal_operation_id=proposal_id)],
    ).code == "ok"
    acceptance_id = ledger.snapshot_operations()[-1]["operation_id"]
    assert app.finalize_block(
        block_height=4,
        block_hash=b"D" * 32,
        txs=[_dispute_tx(proposal_operation_id=proposal_id)],
    ).code == "ok"
    dispute_id = ledger.snapshot_operations()[-1]["operation_id"]
    assert app.finalize_block(
        block_height=5,
        block_hash=b"E" * 32,
        txs=[
            _partial_finalize_tx(
                proposal_operation_id=proposal_id,
                acceptance_operation_id=acceptance_id,
                dispute_operation_id=dispute_id,
            )
        ],
    ).code == "ok"
    partial_id = ledger.snapshot_operations()[-1]["operation_id"]
    prior_transition_hash = ledger.snapshot_operations()[-1]["payload"]["transition"][
        "transition_hash"
    ]
    invalid = app.finalize_block_with_results(
        block_height=6,
        block_hash=b"F" * 32,
        txs=[
            _correction_tx(
                partial_finalize_operation_id=partial_id,
                prior_transition_hash=prior_transition_hash,
                consumer_refund_delta_q_atoms=99,
                network_fee_delta_q_atoms=1,
            )
        ],
    )
    assert invalid[0].code == "ok"
    assert invalid[1][0].code == "rejected"
    assert "cannot change Network Fees" in invalid[1][0].log
    assert ledger.get_session_funding_account(SESSION_ID).funding_state == (
        "DISPUTE_RESERVED"
    )
    corrected = app.finalize_block(
        block_height=7,
        block_hash=b"G" * 32,
        txs=[
            _correction_tx(
                partial_finalize_operation_id=partial_id,
                prior_transition_hash=prior_transition_hash,
            )
        ],
    )

    assert corrected.code == "ok"
    assert ledger.wallet_q_atom_balance("wallet:consumer") == 1_180
    assert ledger.wallet_q_atom_balance("wallet:endpoint") == 800
    account = ledger.get_session_funding_account(SESSION_ID)
    assert account.funding_state == "RELEASED"
    assert account.active_dispute_reserve_q_atoms == 0
    assert account.consumer_payment_refund_q_atoms == 200
    assert account.consumer_fee_refund_q_atoms == 80
    assert ledger.get_settlement_correction(
        "correction-consensus-1"
    ).dispute_reserve_delta_q_atoms == -100
    assert ledger.snapshot_operations()[-1]["operation_type"] == (
        "SESSION_SETTLEMENT_CORRECT"
    )

    snapshot = app.prepare_snapshot()
    restored, restored_ledger = _abci()
    assert restored.apply_snapshot(snapshot).code == "ok"
    assert restored_ledger.get_session_funding_account(SESSION_ID).funding_state == (
        "RELEASED"
    )
    assert restored_ledger.get_settlement_correction(
        "correction-consensus-1"
    ).correction_id == "correction-consensus-1"
    assert restored.prepare_snapshot()["app_hash"] == snapshot["app_hash"]


def test_settlement_proposal_binds_latest_escrow_predecessor() -> None:
    app, ledger = _abci()
    funding = _funding()
    assert app.finalize_block(
        block_height=1,
        block_hash=b"A" * 32,
        txs=[_lock_envelope(funding)],
    ).code == "ok"
    lock_id = ledger.snapshot_operations()[-1]["operation_id"]
    next_funding = _extended_funding(funding)
    assert app.finalize_block(
        block_height=2,
        block_hash=b"B" * 32,
        txs=[
            _extend_envelope(
                funding,
                next_funding,
                previous_operation_id=lock_id,
            )
        ],
    ).code == "ok"
    extension_id = ledger.snapshot_operations()[-1]["operation_id"]

    stale = json.loads(_proposal_tx(next_funding, funding_lock_operation_id=lock_id))
    stale["payload"]["proposal"].update(
        {
            "consumer_payment_refund_q_atoms": 500,
            "consumer_fee_refund_q_atoms": 130,
            "actual_network_fees_q_atoms": 20,
        }
    )
    stale["evidence_references"] = [
        lock_id,
        stale["payload"]["proposal"]["settlement_input_root"],
    ]
    stale["operation_id"] = ""
    stale_result, stale_txs = app.finalize_block_with_results(
        block_height=3,
        block_hash=b"C" * 32,
        txs=[json.dumps(stale).encode("utf-8")],
    )
    assert stale_result.code == "ok"
    assert stale_txs[0].code == "rejected"
    assert "funding predecessor" in stale_txs[0].log

    current = json.loads(_proposal_tx(next_funding, funding_lock_operation_id=lock_id))
    current["payload"].pop("funding_lock_operation_id")
    current["payload"]["funding_predecessor_operation_id"] = extension_id
    current["payload"]["proposal"].update(
        {
            "consumer_payment_refund_q_atoms": 500,
            "consumer_fee_refund_q_atoms": 130,
            "actual_network_fees_q_atoms": 20,
        }
    )
    current["evidence_references"] = [
        extension_id,
        current["payload"]["proposal"]["settlement_input_root"],
    ]
    current["operation_id"] = ""
    result = app.finalize_block(
        block_height=4,
        block_hash=b"D" * 32,
        txs=[json.dumps(current).encode("utf-8")],
    )
    assert result.code == "ok"
    assert ledger.get_settlement_proposal("settlement-consensus-1").session_id == SESSION_ID
    assert ledger.get_session_funding_account(SESSION_ID).funding_state == "LOCKED"


def test_settlement_partial_finalize_requires_dispute_dependency() -> None:
    app, ledger = _abci()
    funding = _funding()
    assert app.finalize_block(
        block_height=1,
        block_hash=b"A" * 32,
        txs=[_lock_envelope(funding)],
    ).code == "ok"
    lock_id = ledger.snapshot_operations()[-1]["operation_id"]
    proposal_tx = _disputed_proposal_tx(
        funding,
        funding_lock_operation_id=lock_id,
    )
    proposal_envelope = LedgerOperationEnvelope.model_validate(
        json.loads(proposal_tx)
    )
    partial_tx = _partial_finalize_tx(
        proposal_operation_id=proposal_envelope.operation_id,
        acceptance_operation_id="missing-acceptance",
        dispute_operation_id="missing-dispute",
    )
    result, tx_results = app.finalize_block_with_results(
        block_height=2,
        block_hash=b"B" * 32,
        txs=[proposal_tx, partial_tx],
    )
    assert result.code == "ok"
    assert [item.code for item in tx_results] == ["ok", "rejected"]
    assert ledger.get_session_funding_account(SESSION_ID).funding_state == "LOCKED"


def test_execution_engine_applies_dispute_and_partial_finalize() -> None:
    ledger = LedgerOperationService()
    ledger.credit_wallet_q_atoms(wallet_id="wallet:consumer", amount_q_atoms=2_000)
    engine = ExecutionEngine(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
    )
    funding = _funding()
    assert engine.execute_block(
        block_height=1,
        block_hash=b"A" * 32,
        txs=[_lock_envelope(funding)],
    ).error is None
    lock_id = ledger.snapshot_operations()[-1]["operation_id"]
    assert engine.execute_block(
        block_height=2,
        block_hash=b"B" * 32,
        txs=[_disputed_proposal_tx(funding, funding_lock_operation_id=lock_id)],
    ).error is None
    proposal_id = ledger.snapshot_operations()[-1]["operation_id"]
    assert engine.execute_block(
        block_height=3,
        block_hash=b"C" * 32,
        txs=[_disputed_accept_tx(proposal_operation_id=proposal_id)],
    ).error is None
    acceptance_id = ledger.snapshot_operations()[-1]["operation_id"]
    assert engine.execute_block(
        block_height=4,
        block_hash=b"D" * 32,
        txs=[_dispute_tx(proposal_operation_id=proposal_id)],
    ).error is None
    dispute_id = ledger.snapshot_operations()[-1]["operation_id"]
    result = engine.execute_block(
        block_height=5,
        block_hash=b"E" * 32,
        txs=[
            _partial_finalize_tx(
                proposal_operation_id=proposal_id,
                acceptance_operation_id=acceptance_id,
                dispute_operation_id=dispute_id,
            )
        ],
    )

    assert result.error is None
    assert result.operations_executed == 1
    assert ledger.wallet_q_atom_balance("wallet:endpoint") == 800
    assert ledger.get_session_funding_account(SESSION_ID).funding_state == (
        "DISPUTE_RESERVED"
    )
    partial_id = ledger.snapshot_operations()[-1]["operation_id"]
    prior_transition_hash = ledger.snapshot_operations()[-1]["payload"]["transition"][
        "transition_hash"
    ]
    corrected = engine.execute_block(
        block_height=6,
        block_hash=b"F" * 32,
        txs=[
            _correction_tx(
                partial_finalize_operation_id=partial_id,
                prior_transition_hash=prior_transition_hash,
            )
        ],
    )
    assert corrected.error is None
    assert corrected.operations_executed == 1
    assert ledger.wallet_q_atom_balance("wallet:consumer") == 1_180
    assert ledger.wallet_q_atom_balance("wallet:endpoint") == 800
    assert ledger.get_session_funding_account(SESSION_ID).funding_state == "RELEASED"


def test_ordinary_finalize_rejects_proposal_with_dispute_reserve() -> None:
    app, ledger = _abci()
    funding = _funding()
    assert app.finalize_block(
        block_height=1,
        block_hash=b"A" * 32,
        txs=[_lock_envelope(funding)],
    ).code == "ok"
    lock_id = ledger.snapshot_operations()[-1]["operation_id"]
    assert app.finalize_block(
        block_height=2,
        block_hash=b"B" * 32,
        txs=[_disputed_proposal_tx(funding, funding_lock_operation_id=lock_id)],
    ).code == "ok"
    proposal_id = ledger.snapshot_operations()[-1]["operation_id"]
    assert app.finalize_block(
        block_height=3,
        block_hash=b"C" * 32,
        txs=[_disputed_accept_tx(proposal_operation_id=proposal_id)],
    ).code == "ok"
    acceptance_id = ledger.snapshot_operations()[-1]["operation_id"]
    ordinary_finalize = json.loads(
        _partial_finalize_tx(
            proposal_operation_id=proposal_id,
            acceptance_operation_id=acceptance_id,
            dispute_operation_id="dispute-op-placeholder",
        )
    )
    ordinary_finalize["operation_type"] = "SESSION_SETTLEMENT_FINALIZE"
    ordinary_finalize["operation_id"] = ""
    result, tx_results = app.finalize_block_with_results(
        block_height=4,
        block_hash=b"D" * 32,
        txs=[json.dumps(ordinary_finalize).encode("utf-8")],
    )
    assert result.code == "ok"
    assert tx_results[0].code == "rejected"
    assert "partial finalization" in tx_results[0].log


def test_execution_engine_applies_same_settlement_flow() -> None:
    ledger = LedgerOperationService()
    ledger.credit_wallet_q_atoms(wallet_id="wallet:consumer", amount_q_atoms=2_000)
    engine = ExecutionEngine(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
    )
    funding = _funding()

    locked = engine.execute_block(
        block_height=1,
        block_hash=b"A" * 32,
        txs=[_lock_envelope(funding)],
    )
    assert locked.error is None
    lock_id = ledger.snapshot_operations()[0]["operation_id"]
    proposed = engine.execute_block(
        block_height=2,
        block_hash=b"B" * 32,
        txs=[_proposal_tx(funding, funding_lock_operation_id=lock_id)],
    )
    assert proposed.error is None
    proposal_id = ledger.snapshot_operations()[-1]["operation_id"]
    accepted = engine.execute_block(
        block_height=3,
        block_hash=b"C" * 32,
        txs=[_accept_tx(proposal_operation_id=proposal_id)],
    )
    assert accepted.error is None
    acceptance_id = ledger.snapshot_operations()[-1]["operation_id"]
    finalized = engine.execute_block(
        block_height=4,
        block_hash=b"D" * 32,
        txs=[
            _finalize_tx(
                proposal_operation_id=proposal_id,
                acceptance_operation_id=acceptance_id,
            )
        ],
    )

    assert finalized.error is None
    assert finalized.operations_executed == 1
    assert ledger.wallet_q_atom_balance("wallet:endpoint") == 800
    assert ledger.get_session_funding_account(SESSION_ID).funding_state == "RELEASED"


def test_abci_snapshot_restore_preserves_finalized_settlement() -> None:
    app, ledger, _funding_account, proposal_id = _lock_and_propose_abci()
    assert app.finalize_block(
        block_height=3,
        block_hash=b"C" * 32,
        txs=[_accept_tx(proposal_operation_id=proposal_id)],
    ).code == "ok"
    acceptance_id = ledger.snapshot_operations()[-1]["operation_id"]
    assert app.finalize_block(
        block_height=4,
        block_hash=b"D" * 32,
        txs=[
            _finalize_tx(
                proposal_operation_id=proposal_id,
                acceptance_operation_id=acceptance_id,
            )
        ],
    ).code == "ok"
    snapshot = app.prepare_snapshot()

    restored, restored_ledger = _abci()
    assert restored.apply_snapshot(snapshot).code == "ok"
    assert restored_ledger.wallet_q_atom_balance("wallet:consumer") == 1_180
    assert restored_ledger.wallet_q_atom_balance("wallet:endpoint") == 800
    assert restored_ledger.get_session_funding_account(SESSION_ID).funding_state == "RELEASED"
    assert restored.prepare_snapshot()["app_hash"] == snapshot["app_hash"]


def test_abci_settlement_ready_commit_is_typed_replay_safe_and_snapshot_persistent() -> None:
    app, ledger = _abci()
    funding = _funding()
    assert app.finalize_block(
        block_height=1,
        block_hash=b"A" * 32,
        txs=[_lock_envelope(funding)],
    ).code == "ok"
    lock_id = ledger.snapshot_operations()[-1]["operation_id"]

    ready_tx = _ready_tx(funding, funding_lock_operation_id=lock_id)
    assert app.finalize_block(
        block_height=2,
        block_hash=b"B" * 32,
        txs=[ready_tx],
    ).code == "ok"
    ready = ledger.get_settlement_ready_commitment(SESSION_ID)
    assert ready.settlement_input_root == INPUT_ROOT
    assert ledger.snapshot_operations()[-1]["operation_type"] == (
        "SESSION_SETTLEMENT_READY_COMMIT"
    )

    snapshot = app.prepare_snapshot()
    restored_ledger = LedgerOperationService()
    restored_app = AIDNABCIApplication(
        ledger_service=restored_ledger,
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
    )
    assert restored_app.apply_snapshot(snapshot).code == "ok"
    assert restored_ledger.get_settlement_ready_commitment(SESSION_ID) == ready

    duplicate_result, duplicate_txs = restored_app.finalize_block_with_results(
        block_height=3,
        block_hash=b"C" * 32,
        txs=[ready_tx],
    )
    assert duplicate_result.code == "ok"
    assert duplicate_txs[0].code == "rejected"
    assert "already committed" in duplicate_txs[0].log


def test_execution_engine_applies_settlement_ready_commit_and_rejects_conflict() -> None:
    ledger = LedgerOperationService()
    ledger.credit_wallet_q_atoms(wallet_id="wallet:consumer", amount_q_atoms=2_000)
    engine = ExecutionEngine(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
    )
    funding = _funding()
    assert engine.execute_block(
        block_height=1,
        block_hash=b"A" * 32,
        txs=[_lock_envelope(funding)],
    ).error is None
    lock_id = ledger.snapshot_operations()[-1]["operation_id"]
    result = engine.execute_block(
        block_height=2,
        block_hash=b"B" * 32,
        txs=[_ready_tx(funding, funding_lock_operation_id=lock_id)],
    )
    assert result.error is None
    assert result.execution_events[0].emitted_events == [
        "SessionSettlementReadyCommitted"
    ]

    conflicting = _ready_tx(
        funding,
        funding_lock_operation_id=lock_id,
        input_root="sha256:conflicting-settlement-input",
    )
    rejected = engine.execute_block(
        block_height=3,
        block_hash=b"C" * 32,
        txs=[conflicting],
    )
    assert rejected.operations_executed == 0
    assert rejected.operations_rejected == 1
    assert "conflicting Settlement readiness" in rejected.execution_events[0].error


def test_settlement_proposal_must_match_finalized_ready_commitment_when_present() -> None:
    app, ledger = _abci()
    funding = _funding()
    assert app.finalize_block(
        block_height=1,
        block_hash=b"A" * 32,
        txs=[_lock_envelope(funding)],
    ).code == "ok"
    lock_id = ledger.snapshot_operations()[-1]["operation_id"]
    assert app.finalize_block(
        block_height=2,
        block_hash=b"B" * 32,
        txs=[_ready_tx(funding, funding_lock_operation_id=lock_id)],
    ).code == "ok"
    ready_id = ledger.snapshot_operations()[-1]["operation_id"]

    result = app.finalize_block(
        block_height=3,
        block_hash=b"C" * 32,
        txs=[
            _proposal_tx(
                funding,
                funding_lock_operation_id=lock_id,
                settlement_ready_operation_id=ready_id,
            )
        ],
    )
    assert result.code == "ok"
