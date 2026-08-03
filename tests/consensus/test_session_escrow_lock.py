from __future__ import annotations

import json

from aidn_hypervisor.consensus.abci import AIDNABCIApplication
from aidn_hypervisor.consensus.admission import AdmissionValidator
from aidn_hypervisor.consensus.execution import ExecutionEngine
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.ledger.service import LedgerOperationService
from aidn_hypervisor.settlement.models import SessionFundingAccount


def _funding() -> SessionFundingAccount:
    return SessionFundingAccount(
        session_id="session-consensus-1",
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


def _tx(funding: SessionFundingAccount) -> bytes:
    envelope = LedgerOperationEnvelope(
        operation_type="SESSION_ESCROW_LOCK",
        operation_version="1.0.0",
        protocol_version="0.1",
        origin_type="wallet",
        initiator_id=funding.session_id,
        sender_wallet=funding.consumer_funding_account,
        sender_sequence=1,
        fee_payer=funding.consumer_funding_account,
        fee_class="session",
        created_at="2030-01-01T00:00:00Z",
        expires_at="2030-01-02T00:00:00Z",
        payload=funding.model_dump(mode="json"),
        signatures=["ed25519:consumer"],
    )
    return json.dumps(envelope.model_dump(mode="json")).encode("utf-8")


def _abci() -> tuple[AIDNABCIApplication, LedgerOperationService]:
    ledger = LedgerOperationService()
    ledger.credit_wallet_q_atoms(wallet_id="wallet:consumer", amount_q_atoms=2_000)
    app = AIDNABCIApplication(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
    )
    return app, ledger


def test_abci_session_escrow_lock_debits_consumer_and_persists_funding() -> None:
    app, ledger = _abci()

    result, tx_results = app.finalize_block_with_results(
        block_height=1,
        block_hash=b"A" * 32,
        txs=[_tx(_funding())],
    )

    assert result.code == "ok"
    assert tx_results[0].code == "ok"
    assert ledger.wallet_q_atom_balance("wallet:consumer") == 900
    account = ledger.get_session_funding_account("session-consensus-1")
    assert account.funding_state == "LOCKED"
    assert account.funding_state_hash == _funding().funding_state_hash
    assert ledger.snapshot_operations()[0]["operation_type"] == "SESSION_ESCROW_LOCK"


def test_execution_engine_applies_the_same_escrow_lock() -> None:
    ledger = LedgerOperationService()
    ledger.credit_wallet_q_atoms(wallet_id="wallet:consumer", amount_q_atoms=2_000)
    engine = ExecutionEngine(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
    )

    result = engine.execute_block(
        block_height=1,
        block_hash=b"A" * 32,
        txs=[_tx(_funding())],
    )

    assert result.error is None
    assert result.operations_executed == 1
    assert result.execution_events[0].emitted_events == ["SessionEscrowLocked"]
    assert ledger.wallet_q_atom_balance("wallet:consumer") == 900
    assert ledger.get_session_funding_account("session-consensus-1").funding_state == "LOCKED"


def test_consensus_escrow_lock_rejects_insufficient_prepaid_balance() -> None:
    ledger = LedgerOperationService()
    app = AIDNABCIApplication(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
    )
    funding = _funding()
    tx = _tx(funding)

    result, tx_results = app.finalize_block_with_results(
        block_height=1,
        block_hash=b"A" * 32,
        txs=[tx],
    )

    # The transaction is rejected without creating a Funding Account or a
    # Ledger operation; the containing block remains valid.
    assert result.code == "ok"
    assert tx_results[0].code == "rejected"
    assert "insufficient" in tx_results[0].log
    assert ledger.snapshot_operations() == []


def test_abci_snapshot_restore_preserves_escrow_lock_and_wallet_balance() -> None:
    app, ledger = _abci()
    locked = app.finalize_block(
        block_height=1,
        block_hash=b"A" * 32,
        txs=[_tx(_funding())],
    )
    assert locked.code == "ok"
    snapshot = app.prepare_snapshot()

    restored, restored_ledger = _abci()
    result = restored.apply_snapshot(snapshot)

    assert result.code == "ok"
    assert restored_ledger.wallet_q_atom_balance("wallet:consumer") == 900
    assert restored_ledger.get_session_funding_account(
        "session-consensus-1"
    ).funding_state_hash == ledger.get_session_funding_account(
        "session-consensus-1"
    ).funding_state_hash
    assert restored.prepare_snapshot()["app_hash"] == snapshot["app_hash"]
