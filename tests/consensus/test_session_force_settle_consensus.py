from __future__ import annotations

import json
from typing import Literal

from aidn_hypervisor.consensus.abci import AIDNABCIApplication
from aidn_hypervisor.consensus.admission import AdmissionValidator
from aidn_hypervisor.consensus.execution import ExecutionEngine
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.ledger.service import LedgerOperationService
from aidn_hypervisor.settlement.models import (
    AtomicSettlementTransition,
    SessionFundingAccount,
)

SESSION_ID = "session-force-consensus-1"
FAILURE_ROOT = "sha256:failure-evidence-1"


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
    origin_type: Literal["wallet", "multi_party", "protocol", "evidence_triggered"],
    fee_payer: str | None,
    evidence_references: list[str],
) -> bytes:
    envelope = LedgerOperationEnvelope(
        operation_type=operation_type,
        operation_version="1.0.0",
        protocol_version="0.1",
        origin_type=origin_type,
        initiator_id=SESSION_ID,
        fee_payer=fee_payer,
        fee_class="session",
        created_at="2030-01-01T00:00:00Z",
        expires_at="2030-01-02T00:00:00Z",
        payload=payload,
        evidence_references=evidence_references,
        signatures=["ed25519:session-party"],
    )
    return json.dumps(envelope.model_dump(mode="json")).encode("utf-8")


def _lock_tx(funding: SessionFundingAccount) -> bytes:
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


def _failure_tx(*, failure_class: str = "ENDPOINT_UNAVAILABLE") -> bytes:
    return _envelope(
        "SESSION_FAILURE_EVIDENCE",
        {
            "session_id": SESSION_ID,
            "failure_evidence_root": FAILURE_ROOT,
            "failure_class": failure_class,
        },
        origin_type="evidence_triggered",
        fee_payer=None,
        evidence_references=[FAILURE_ROOT],
    )


def _force_tx(
    *,
    lock_operation_id: str,
    failure_operation_id: str,
    failure_class: str = "ENDPOINT_UNAVAILABLE",
) -> bytes:
    transition = AtomicSettlementTransition(
        session_id=SESSION_ID,
        settlement_id="forced-settlement-consensus-1",
        endpoint_payment_beneficiary="wallet:endpoint",
        consumer_refund_beneficiary="wallet:consumer",
        previously_released_to_endpoint_q_atoms=0,
        previously_refunded_to_consumer_q_atoms=0,
        previously_consumed_network_fees_q_atoms=0,
        credit_endpoint_q_atoms=0,
        credit_consumer_q_atoms=1_100,
        consume_network_fees_q_atoms=0,
        retain_dispute_reserve_q_atoms=0,
        total_locked_amount_q_atoms=1_100,
    )
    return _envelope(
        "SESSION_FORCE_SETTLE",
        {
            "session_id": SESSION_ID,
            "failure_class": failure_class,
            "requested_at": "2030-01-01T00:30:00Z",
            "force_after": "2030-01-01T01:00:00Z",
            "observed_at": "2030-01-01T02:00:00Z",
            "failure_evidence_root": FAILURE_ROOT,
            "failure_evidence_operation_id": failure_operation_id,
            "funding_lock_operation_id": lock_operation_id,
            "requested_payment_q_atoms": 0,
            "requested_refund_q_atoms": 1_100,
            "request_settlement_root": "sha256:requests-empty",
            "usage_chain_root": "sha256:usage-empty",
            "checkpoint_root": "sha256:checkpoints-empty",
            "initiator_wallet": "wallet:consumer",
            "initiator_signature": "ed25519:consumer-force",
            "transition": transition.model_dump(mode="json"),
        },
        origin_type="evidence_triggered",
        fee_payer="wallet:consumer",
        evidence_references=[
            lock_operation_id,
            failure_operation_id,
            FAILURE_ROOT,
            "forced-settlement-consensus-1",
        ],
    )


def _paid_consumer_timeout_force_tx(
    *,
    lock_operation_id: str,
    failure_operation_id: str,
) -> bytes:
    request_record_hash = "sha256:request-record-consumer-timeout"
    final_usage_hash = "sha256:final-usage-consumer-timeout"
    settlement_input_root = "sha256:settlement-input-consumer-timeout"
    request_settlement_root = "sha256:request-root-consumer-timeout"
    transition = AtomicSettlementTransition(
        session_id=SESSION_ID,
        settlement_id="forced-settlement-consumer-timeout-1",
        endpoint_payment_beneficiary="wallet:endpoint",
        consumer_refund_beneficiary="wallet:consumer",
        previously_released_to_endpoint_q_atoms=0,
        previously_refunded_to_consumer_q_atoms=0,
        previously_consumed_network_fees_q_atoms=0,
        credit_endpoint_q_atoms=1_000,
        credit_consumer_q_atoms=100,
        consume_network_fees_q_atoms=0,
        retain_dispute_reserve_q_atoms=0,
        total_locked_amount_q_atoms=1_100,
    )
    return _envelope(
        "SESSION_FORCE_SETTLE",
        {
            "session_id": SESSION_ID,
            "failure_class": "CONSUMER_TIMEOUT_AFTER_COMPLETED_FIXED_PRICE",
            "requested_at": "2030-01-01T00:30:00Z",
            "force_after": "2030-01-01T01:00:00Z",
            "observed_at": "2030-01-01T02:00:00Z",
            "failure_evidence_root": FAILURE_ROOT,
            "failure_evidence_operation_id": failure_operation_id,
            "funding_lock_operation_id": lock_operation_id,
            "settlement_input_root": settlement_input_root,
            "requested_payment_q_atoms": 1_000,
            "requested_refund_q_atoms": 100,
            "request_settlement_root": request_settlement_root,
            "usage_chain_root": "sha256:usage-root-consumer-timeout",
            "checkpoint_root": "sha256:checkpoint-root-consumer-timeout",
            "request_evidence": [
                {
                    "request_id": "request-consumer-timeout-1",
                    "terminal_state": "COMPLETED",
                    "record_hash": request_record_hash,
                    "final_usage_report_hash": final_usage_hash,
                    "capped_request_charge_q_atoms": 1_000,
                    "disputed_amount_q_atoms": 0,
                    "dispute_state": "NONE",
                }
            ],
            "provider_usage_report_hashes": [final_usage_hash],
            "initiator_wallet": "wallet:consumer",
            "initiator_signature": "ed25519:consumer-force",
            "transition": transition.model_dump(mode="json"),
        },
        origin_type="evidence_triggered",
        fee_payer="wallet:consumer",
        evidence_references=[
            lock_operation_id,
            failure_operation_id,
            FAILURE_ROOT,
            "forced-settlement-consumer-timeout-1",
            settlement_input_root,
            request_settlement_root,
            request_record_hash,
            final_usage_hash,
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


def _prepare_abci(
    *,
    failure_class: str = "ENDPOINT_UNAVAILABLE",
) -> tuple[AIDNABCIApplication, LedgerOperationService, str, str]:
    app, ledger = _abci()
    funding = _funding()
    assert app.finalize_block(
        block_height=1,
        block_hash=b"A" * 32,
        txs=[_lock_tx(funding)],
    ).code == "ok"
    lock_id = ledger.snapshot_operations()[0]["operation_id"]
    assert app.finalize_block(
        block_height=2,
        block_hash=b"B" * 32,
        txs=[_failure_tx(failure_class=failure_class)],
    ).code == "ok"
    failure_id = ledger.snapshot_operations()[-1]["operation_id"]
    return app, ledger, lock_id, failure_id


def test_abci_force_settlement_refunds_remaining_locked_exposure() -> None:
    app, ledger, lock_id, failure_id = _prepare_abci()

    result = app.finalize_block(
        block_height=3,
        block_hash=b"C" * 32,
        txs=[_force_tx(lock_operation_id=lock_id, failure_operation_id=failure_id)],
    )

    assert result.code == "ok"
    assert ledger.wallet_q_atom_balance("wallet:consumer") == 2_000
    assert ledger.wallet_q_atom_balance("wallet:endpoint") == 0
    account = ledger.get_session_funding_account(SESSION_ID)
    assert account.funding_state == "REFUNDED"
    assert account.consumer_payment_refund_q_atoms == 1_000
    assert account.consumer_fee_refund_q_atoms == 100
    assert account.unsettled_payment_reserve_q_atoms == 0
    assert ledger.snapshot_operations()[-1]["operation_type"] == "SESSION_FORCE_SETTLE"


def test_abci_force_settlement_binds_consumer_timeout_to_failure_class() -> None:
    app, ledger, lock_id, failure_id = _prepare_abci(
        failure_class="CONSUMER_DISCONNECTED"
    )

    result = app.finalize_block(
        block_height=3,
        block_hash=b"C" * 32,
        txs=[
            _force_tx(
                lock_operation_id=lock_id,
                failure_operation_id=failure_id,
                failure_class="CONSUMER_TIMEOUT_AFTER_COMPLETED_FIXED_PRICE",
            )
        ],
    )

    assert result.code == "ok"
    assert ledger.get_session_funding_account(SESSION_ID).funding_state == "REFUNDED"


def test_abci_consumer_timeout_pays_only_completed_request_evidence() -> None:
    app, ledger, lock_id, failure_id = _prepare_abci(
        failure_class="CONSUMER_DISCONNECTED"
    )

    result = app.finalize_block(
        block_height=3,
        block_hash=b"C" * 32,
        txs=[
            _paid_consumer_timeout_force_tx(
                lock_operation_id=lock_id,
                failure_operation_id=failure_id,
            )
        ],
    )

    assert result.code == "ok"
    assert ledger.wallet_q_atom_balance("wallet:consumer") == 1_000
    assert ledger.wallet_q_atom_balance("wallet:endpoint") == 1_000
    funding = ledger.get_session_funding_account(SESSION_ID)
    assert funding.funding_state == "RELEASED"
    assert funding.released_to_endpoint_q_atoms == 1_000
    assert funding.consumer_payment_refund_q_atoms == 0
    assert funding.consumer_fee_refund_q_atoms == 100


def test_abci_consumer_timeout_rejects_payment_not_backed_by_request_evidence() -> None:
    app, ledger, lock_id, failure_id = _prepare_abci(
        failure_class="CONSUMER_DISCONNECTED"
    )
    tx = json.loads(
        _paid_consumer_timeout_force_tx(
            lock_operation_id=lock_id,
            failure_operation_id=failure_id,
        )
    )
    tx["payload"]["request_evidence"][0]["capped_request_charge_q_atoms"] = 999
    tx["operation_id"] = ""

    result, tx_results = app.finalize_block_with_results(
        block_height=3,
        block_hash=b"C" * 32,
        txs=[json.dumps(tx).encode("utf-8")],
    )

    assert result.code == "ok"
    assert tx_results[0].code == "rejected"
    assert "does not match Request evidence" in tx_results[0].log
    assert ledger.wallet_q_atom_balance("wallet:consumer") == 900
    assert ledger.wallet_q_atom_balance("wallet:endpoint") == 0
    assert ledger.get_session_funding_account(SESSION_ID).funding_state == "LOCKED"


def test_abci_failure_evidence_requires_root_reference() -> None:
    app, ledger = _abci()
    tx = json.loads(_failure_tx())
    tx["evidence_references"] = []
    tx["operation_id"] = ""

    result, tx_results = app.finalize_block_with_results(
        block_height=1,
        block_hash=b"A" * 32,
        txs=[json.dumps(tx).encode("utf-8")],
    )

    assert result.code == "ok"
    assert tx_results[0].code == "rejected"
    assert "root is not referenced" in tx_results[0].log
    assert ledger.snapshot_operations() == []


def test_abci_failure_evidence_rejects_conflicting_class_for_same_root() -> None:
    app, ledger = _abci()
    assert app.finalize_block(
        block_height=1,
        block_hash=b"A" * 32,
        txs=[_failure_tx()],
    ).code == "ok"

    conflicting = json.loads(_failure_tx())
    conflicting["payload"]["failure_class"] = "ENDPOINT_FAILURE"
    conflicting["operation_id"] = ""
    result, tx_results = app.finalize_block_with_results(
        block_height=2,
        block_hash=b"B" * 32,
        txs=[json.dumps(conflicting).encode("utf-8")],
    )

    assert result.code == "ok"
    assert tx_results[0].code == "rejected"
    assert "conflicting" in tx_results[0].log
    assert len(ledger.snapshot_operations()) == 1


def test_force_settlement_rejects_unelapsed_timeout() -> None:
    app, ledger, lock_id, failure_id = _prepare_abci()
    tx = json.loads(
        _force_tx(lock_operation_id=lock_id, failure_operation_id=failure_id)
    )
    tx["payload"]["observed_at"] = "2030-01-01T00:45:00Z"
    tx["operation_id"] = ""
    tx = json.dumps(tx).encode("utf-8")

    result, tx_results = app.finalize_block_with_results(
        block_height=3,
        block_hash=b"C" * 32,
        txs=[tx],
    )

    assert result.code == "ok"
    assert tx_results[0].code == "rejected"
    assert "timeout" in tx_results[0].log
    assert ledger.get_session_funding_account(SESSION_ID).funding_state == "LOCKED"


def test_force_settlement_rejects_unbound_failure_evidence() -> None:
    app, ledger, lock_id, failure_id = _prepare_abci()
    tx = json.loads(
        _force_tx(lock_operation_id=lock_id, failure_operation_id=failure_id)
    )
    tx["payload"]["failure_evidence_root"] = "sha256:unbound-failure"
    tx["evidence_references"].append("sha256:unbound-failure")
    tx["operation_id"] = ""

    result, tx_results = app.finalize_block_with_results(
        block_height=3,
        block_hash=b"C" * 32,
        txs=[json.dumps(tx).encode("utf-8")],
    )

    assert result.code == "ok"
    assert tx_results[0].code == "rejected"
    assert "failure evidence binding" in tx_results[0].log
    assert ledger.get_session_funding_account(SESSION_ID).funding_state == "LOCKED"


def test_execution_engine_applies_force_settlement_and_snapshot_restores_it() -> None:
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
        txs=[_lock_tx(funding)],
    )
    assert locked.error is None
    lock_id = ledger.snapshot_operations()[0]["operation_id"]
    evidence = engine.execute_block(
        block_height=2,
        block_hash=b"B" * 32,
        txs=[_failure_tx()],
    )
    assert evidence.error is None
    failure_id = ledger.snapshot_operations()[-1]["operation_id"]
    forced = engine.execute_block(
        block_height=3,
        block_hash=b"C" * 32,
        txs=[_force_tx(lock_operation_id=lock_id, failure_operation_id=failure_id)],
    )

    assert forced.error is None
    assert ledger.get_session_funding_account(SESSION_ID).funding_state == "REFUNDED"
    assert ledger.wallet_q_atom_balance("wallet:consumer") == 2_000
    assert any(
        event.operation_type == "SESSION_FAILURE_EVIDENCE"
        and event.emitted_events == ["SessionFailureEvidenceCommitted"]
        for event in evidence.execution_events
    )
