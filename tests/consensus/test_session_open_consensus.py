from __future__ import annotations

import json

from aidn_hypervisor.consensus.abci import AIDNABCIApplication
from aidn_hypervisor.consensus.admission import AdmissionValidator
from aidn_hypervisor.consensus.execution import ExecutionEngine
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.ledger.service import LedgerOperationService
from aidn_hypervisor.settlement.models import SessionFundingAccount

SESSION_ID = "session-open-consensus-1"


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


def _envelope(
    operation_type: str,
    payload: dict,
    *,
    sender_sequence: int,
    sender_wallet: str = "wallet:consumer",
    initiator_id: str = SESSION_ID,
    evidence_references: list[str] | None = None,
) -> bytes:
    envelope = LedgerOperationEnvelope(
        operation_type=operation_type,
        operation_version="1.0.0",
        protocol_version="0.1",
        origin_type="wallet",
        initiator_id=initiator_id,
        sender_wallet=sender_wallet,
        sender_sequence=sender_sequence,
        fee_payer=sender_wallet,
        fee_class="session",
        created_at="2030-01-01T00:00:00Z",
        expires_at="2030-01-02T00:00:00Z",
        payload=payload,
        evidence_references=evidence_references or [],
        signatures=["ed25519:consumer"],
    )
    return json.dumps(envelope.model_dump(mode="json")).encode("utf-8")


def _lock_tx(funding: SessionFundingAccount) -> bytes:
    return _envelope(
        "SESSION_ESCROW_LOCK",
        funding.model_dump(mode="json"),
        sender_sequence=1,
    )


def _open_tx(
    funding: SessionFundingAccount,
    lock_operation_id: str,
    *,
    sender_sequence: int = 2,
    endpoint_payment_beneficiary: str | None = None,
) -> bytes:
    payload = {
        "session_id": SESSION_ID,
        "consumer_hypervisor_id": "hv-consumer",
        "provider_hypervisor_id": "hv-endpoint",
        "endpoint_id": "endpoint:text",
        "endpoint_version": "1.0.0",
        "endpoint_configuration_hash": "sha256:endpoint-config",
        "pricing_policy_hash": "sha256:pricing",
        "accounting_contract_hash": "sha256:accounting",
        "session_policy_hash": "sha256:session-policy",
        "session_contract_hash": funding.session_contract_hash,
        "effective_terms_hash": "sha256:effective-terms",
        "endpoint_payment_beneficiary": endpoint_payment_beneficiary
        or funding.endpoint_payment_beneficiary,
        "consumer_refund_beneficiary": funding.consumer_refund_beneficiary,
        "deposit_amount_q_atoms": funding.total_locked_amount_q_atoms,
        "funding_lock_operation_id": lock_operation_id,
        "funding_state_reference": funding.funding_state_hash,
        "open_expiration": "2030-01-02T00:00:00Z",
    }
    return _envelope(
        "SESSION_OPEN",
        payload,
        sender_sequence=sender_sequence,
        evidence_references=[lock_operation_id, funding.funding_state_hash],
    )


def _accept_tx(
    funding: SessionFundingAccount,
    open_operation_id: str,
    *,
    sender_sequence: int = 1,
) -> bytes:
    return _envelope(
        "SESSION_ACCEPT",
        {
            "session_id": SESSION_ID,
            "session_open_operation_id": open_operation_id,
            "session_contract_hash": funding.session_contract_hash,
            "effective_terms_hash": "sha256:effective-terms",
            "endpoint_id": "endpoint:text",
            "endpoint_configuration_hash": "sha256:endpoint-config",
            "provider_hypervisor_id": "hv-endpoint",
            "accepted_by": "wallet:endpoint",
            "accepted_at": "2030-01-01T00:00:00Z",
        },
        sender_sequence=sender_sequence,
        sender_wallet=funding.endpoint_payment_beneficiary,
        initiator_id="hv-endpoint",
        evidence_references=[open_operation_id],
    )


def _app() -> tuple[AIDNABCIApplication, LedgerOperationService]:
    ledger = LedgerOperationService()
    ledger.credit_wallet_q_atoms(wallet_id="wallet:consumer", amount_q_atoms=2_000)
    return (
        AIDNABCIApplication(
            ledger_service=ledger,
            admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
            strict_operation_coverage=True,
        ),
        ledger,
    )


def _operation_id(tx: bytes) -> str:
    return LedgerOperationEnvelope.model_validate(json.loads(tx)).operation_id


def test_abci_session_open_is_non_economic_and_binds_finalized_lock() -> None:
    app, ledger = _app()
    funding = _funding()
    lock_tx = _lock_tx(funding)
    lock_id = _operation_id(lock_tx)

    lock_result = app.finalize_block(
        block_height=1,
        block_hash=b"L" * 32,
        txs=[lock_tx],
    )
    open_result, tx_results = app.finalize_block_with_results(
        block_height=2,
        block_hash=b"O" * 32,
        txs=[_open_tx(funding, lock_id)],
    )

    assert lock_result.code == "ok"
    assert open_result.code == "ok"
    assert tx_results[0].code == "ok"
    assert ledger.wallet_q_atom_balance("wallet:consumer") == 900
    assert ledger.session_open_record(SESSION_ID) is not None
    assert [item["operation_type"] for item in ledger.snapshot_operations()] == [
        "SESSION_ESCROW_LOCK",
        "SESSION_OPEN",
    ]


def test_execution_engine_matches_non_economic_session_open_projection() -> None:
    ledger = LedgerOperationService()
    ledger.credit_wallet_q_atoms(wallet_id="wallet:consumer", amount_q_atoms=2_000)
    funding = _funding()
    lock_tx = _lock_tx(funding)
    lock_id = _operation_id(lock_tx)
    engine = ExecutionEngine(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        strict_operation_coverage=True,
    )

    lock_result = engine.execute_block(
        block_height=1,
        block_hash=b"L" * 32,
        txs=[lock_tx],
    )
    open_result = engine.execute_block(
        block_height=2,
        block_hash=b"O" * 32,
        txs=[_open_tx(funding, lock_id)],
    )

    assert lock_result.operations_executed == 1
    assert open_result.operations_executed == 1
    assert open_result.execution_events[0].emitted_events == ["SessionOpened"]
    assert ledger.wallet_q_atom_balance("wallet:consumer") == 900


def test_session_open_cannot_depend_on_lock_in_the_same_block() -> None:
    app, ledger = _app()
    funding = _funding()
    lock_tx = _lock_tx(funding)
    lock_id = _operation_id(lock_tx)

    result, tx_results = app.finalize_block_with_results(
        block_height=1,
        block_hash=b"S" * 32,
        txs=[lock_tx, _open_tx(funding, lock_id)],
    )

    assert result.code == "ok"
    assert tx_results[0].code == "ok"
    assert tx_results[1].code == "rejected"
    assert "not finalized" in tx_results[1].log
    assert ledger.session_open_record(SESSION_ID) is None
    assert ledger.wallet_q_atom_balance("wallet:consumer") == 900


def test_execution_engine_rejects_same_block_lock_and_open_dependency() -> None:
    ledger = LedgerOperationService()
    ledger.credit_wallet_q_atoms(wallet_id="wallet:consumer", amount_q_atoms=2_000)
    funding = _funding()
    lock_tx = _lock_tx(funding)
    engine = ExecutionEngine(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        strict_operation_coverage=True,
    )

    result = engine.execute_block(
        block_height=1,
        block_hash=b"E" * 32,
        txs=[lock_tx, _open_tx(funding, _operation_id(lock_tx))],
    )

    assert result.operations_executed == 1
    assert result.operations_rejected == 1
    assert "not finalized" in (result.execution_events[1].error or "")
    assert ledger.session_open_record(SESSION_ID) is None
    assert ledger.wallet_q_atom_balance("wallet:consumer") == 900


def test_session_open_rejects_binding_conflict_and_duplicate_session() -> None:
    app, ledger = _app()
    funding = _funding()
    lock_tx = _lock_tx(funding)
    lock_id = _operation_id(lock_tx)
    assert app.finalize_block(block_height=1, block_hash=b"L" * 32, txs=[lock_tx]).code == "ok"

    conflict_result, conflict_tx_results = app.finalize_block_with_results(
        block_height=2,
        block_hash=b"C" * 32,
        txs=[
            _open_tx(
                funding,
                lock_id,
                endpoint_payment_beneficiary="wallet:other-endpoint",
            )
        ],
    )
    assert conflict_result.code == "ok"
    assert conflict_tx_results[0].code == "rejected"
    assert "beneficiary" in conflict_tx_results[0].log

    open_tx = _open_tx(funding, lock_id)
    assert app.finalize_block(block_height=3, block_hash=b"O" * 32, txs=[open_tx]).code == "ok"
    duplicate_result, duplicate_tx_results = app.finalize_block_with_results(
        block_height=4,
        block_hash=b"D" * 32,
        txs=[_open_tx(funding, lock_id, sender_sequence=3)],
    )
    assert duplicate_result.code == "ok"
    assert duplicate_tx_results[0].code == "rejected"
    assert duplicate_tx_results[0].log == "Session is already opened"
    assert len(ledger.snapshot_operations()) == 2


def test_abci_snapshot_restore_rebuilds_session_open_projection() -> None:
    app, ledger = _app()
    funding = _funding()
    lock_tx = _lock_tx(funding)
    lock_id = _operation_id(lock_tx)
    assert app.finalize_block(block_height=1, block_hash=b"L" * 32, txs=[lock_tx]).code == "ok"
    assert app.finalize_block(
        block_height=2,
        block_hash=b"O" * 32,
        txs=[_open_tx(funding, lock_id)],
    ).code == "ok"
    snapshot = app.prepare_snapshot()

    restored_app, restored_ledger = _app()
    restore_result = restored_app.apply_snapshot(snapshot)

    assert restore_result.code == "ok"
    assert restored_ledger.session_open_record(SESSION_ID) == ledger.session_open_record(
        SESSION_ID
    )
    assert restored_ledger.wallet_q_atom_balance("wallet:consumer") == 900
    assert restored_app.prepare_snapshot()["app_hash"] == snapshot["app_hash"]


def test_session_accept_requires_finalized_open_and_keeps_escrow_unchanged() -> None:
    app, ledger = _app()
    funding = _funding()
    lock_tx = _lock_tx(funding)
    lock_id = _operation_id(lock_tx)
    assert app.finalize_block(block_height=1, block_hash=b"L" * 32, txs=[lock_tx]).code == "ok"
    open_tx = _open_tx(funding, lock_id)
    assert app.finalize_block(block_height=2, block_hash=b"O" * 32, txs=[open_tx]).code == "ok"
    open_id = _operation_id(open_tx)

    result, tx_results = app.finalize_block_with_results(
        block_height=3,
        block_hash=b"A" * 32,
        txs=[_accept_tx(funding, open_id)],
    )

    assert result.code == "ok"
    assert tx_results[0].code == "ok"
    assert ledger.session_accept_record(SESSION_ID) is not None
    assert ledger.wallet_q_atom_balance("wallet:consumer") == 900
    assert ledger.wallet_q_atom_balance("wallet:endpoint") == 0
    assert [item["operation_type"] for item in ledger.snapshot_operations()] == [
        "SESSION_ESCROW_LOCK",
        "SESSION_OPEN",
        "SESSION_ACCEPT",
    ]


def test_session_accept_rejects_same_block_open_and_duplicate_acceptance() -> None:
    app, ledger = _app()
    funding = _funding()
    lock_tx = _lock_tx(funding)
    lock_id = _operation_id(lock_tx)
    assert app.finalize_block(block_height=1, block_hash=b"L" * 32, txs=[lock_tx]).code == "ok"
    open_tx = _open_tx(funding, lock_id)
    open_id = _operation_id(open_tx)

    same_block_result, same_block_tx_results = app.finalize_block_with_results(
        block_height=2,
        block_hash=b"S" * 32,
        txs=[open_tx, _accept_tx(funding, open_id)],
    )
    assert same_block_result.code == "ok"
    assert same_block_tx_results[0].code == "ok"
    assert same_block_tx_results[1].code == "rejected"
    assert "not finalized" in same_block_tx_results[1].log
    assert ledger.session_accept_record(SESSION_ID) is None

    assert app.finalize_block(block_height=3, block_hash=b"A" * 32, txs=[_accept_tx(funding, open_id)]).code == "ok"
    duplicate_result, duplicate_tx_results = app.finalize_block_with_results(
        block_height=4,
        block_hash=b"D" * 32,
        txs=[_accept_tx(funding, open_id, sender_sequence=2)],
    )
    assert duplicate_result.code == "ok"
    assert duplicate_tx_results[0].code == "rejected"
    assert duplicate_tx_results[0].log == "Session is already accepted"
