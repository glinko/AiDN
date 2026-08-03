from __future__ import annotations

import json
from typing import Literal

from aidn_hypervisor.consensus.abci import AIDNABCIApplication
from aidn_hypervisor.consensus.admission import AdmissionValidator
from aidn_hypervisor.consensus.execution import ExecutionEngine
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.ledger.service import LedgerOperationService
from aidn_hypervisor.settlement.models import (
    SessionFundingAccount,
    SessionUsageCheckpoint,
)

SESSION_ID = "session-escrow-checkpoint-consensus-1"
USAGE_HASH = "sha256:usage-report-1"


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


def _released_funding(
    funding: SessionFundingAccount,
    *,
    payment: int,
    fees: int,
) -> SessionFundingAccount:
    payload = funding.model_dump(mode="json")
    payload.update(
        {
            "consumer_payment_refund_q_atoms": (
                funding.consumer_payment_refund_q_atoms + payment
            ),
            "consumer_fee_refund_q_atoms": funding.consumer_fee_refund_q_atoms + fees,
            "unsettled_payment_reserve_q_atoms": (
                funding.unsettled_payment_reserve_q_atoms - payment
            ),
            "unsettled_fee_reserve_q_atoms": funding.unsettled_fee_reserve_q_atoms - fees,
            "funding_state": (
                "REFUNDED"
                if funding.unsettled_payment_reserve_q_atoms - payment == 0
                and funding.unsettled_fee_reserve_q_atoms - fees == 0
                and funding.released_to_endpoint_q_atoms == 0
                else (
                    "RELEASED"
                    if funding.unsettled_payment_reserve_q_atoms - payment == 0
                    and funding.unsettled_fee_reserve_q_atoms - fees == 0
                    else "PARTIALLY_RELEASED"
                )
            ),
        }
    )
    payload.pop("funding_state_hash", None)
    return SessionFundingAccount.model_validate(payload)


def _envelope(
    operation_type: str,
    payload: dict,
    *,
    origin_type: Literal["wallet", "multi_party"] = "multi_party",
    sender_wallet: str | None = None,
    sender_sequence: int | None = None,
    fee_payer: str | None = "wallet:consumer",
    signatures: list[str] | None = None,
    evidence_references: list[str] | None = None,
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
        evidence_references=evidence_references or [],
        signatures=signatures or ["ed25519:session-party"],
    )
    return json.dumps(envelope.model_dump(mode="json")).encode("utf-8")


def _lock_tx(funding: SessionFundingAccount) -> bytes:
    return _envelope(
        "SESSION_ESCROW_LOCK",
        funding.model_dump(mode="json"),
        origin_type="wallet",
        sender_wallet="wallet:consumer",
        sender_sequence=1,
        fee_payer="wallet:consumer",
        signatures=["ed25519:consumer"],
    )


def _extend_tx(
    current: SessionFundingAccount,
    next_funding: SessionFundingAccount,
    *,
    previous_operation_id: str,
) -> bytes:
    return _envelope(
        "SESSION_ESCROW_EXTEND",
        {
            "session_id": SESSION_ID,
            "extension_id": "extension-consensus-1",
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
            current.funding_state_hash or "",
            next_funding.funding_state_hash or "",
        ],
    )


def _checkpoint_tx(
    funding: SessionFundingAccount,
    *,
    previous_operation_id: str,
) -> bytes:
    checkpoint = SessionUsageCheckpoint(
        checkpoint_id="checkpoint-consensus-1",
        checkpoint_sequence=1,
        session_id=SESSION_ID,
        request_id="request-consensus-1",
        usage_report_id="usage-report-consensus-1",
        usage_report_hash=USAGE_HASH,
        usage_sequence=1,
        calculated_charge_q_atoms=400,
        current_session_exposure_q_atoms=500,
        remaining_deposit_q_atoms=950,
        accounting_contract_hash="sha256:accounting-contract",
        created_at="2030-01-01T00:00:00Z",
        provider_signature="ed25519:endpoint-usage",
        consumer_signature="ed25519:consumer-checkpoint",
    )
    return _envelope(
        "SESSION_CHECKPOINT_COMMIT",
        {
            "session_id": SESSION_ID,
            "funding_state_reference": funding.funding_state_hash,
            "previous_funding_operation_id": previous_operation_id,
            "consumer_wallet": "wallet:consumer",
            "checkpoint": checkpoint.model_dump(mode="json"),
        },
        signatures=["ed25519:endpoint", "ed25519:consumer"],
        evidence_references=[
            previous_operation_id,
            funding.funding_state_hash or "",
            checkpoint.checkpoint_id,
            checkpoint.checkpoint_hash or "",
            USAGE_HASH,
        ],
    )


def _release_tx(
    funding: SessionFundingAccount,
    next_funding: SessionFundingAccount,
    *,
    previous_operation_id: str,
    release_id: str,
    payment: int,
    fees: int,
) -> bytes:
    return _envelope(
        "SESSION_ESCROW_RELEASE",
        {
            "session_id": SESSION_ID,
            "release_id": release_id,
            "funding_state_reference": funding.funding_state_hash,
            "previous_funding_operation_id": previous_operation_id,
            "release_payment_q_atoms": payment,
            "release_fee_q_atoms": fees,
            "consumer_signature": "ed25519:consumer-release",
            "endpoint_signature": "ed25519:endpoint-release",
            "funding": next_funding.model_dump(mode="json"),
        },
        signatures=["ed25519:endpoint", "ed25519:consumer"],
        evidence_references=[
            previous_operation_id,
            funding.funding_state_hash or "",
            next_funding.funding_state_hash or "",
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


def _prepare_extended_abci() -> tuple[
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
        txs=[_lock_tx(funding)],
    ).code == "ok"
    lock_id = ledger.snapshot_operations()[-1]["operation_id"]
    next_funding = _extended_funding(funding)
    assert app.finalize_block(
        block_height=2,
        block_hash=b"B" * 32,
        txs=[
            _extend_tx(
                funding,
                next_funding,
                previous_operation_id=lock_id,
            )
        ],
    ).code == "ok"
    extension_id = ledger.snapshot_operations()[-1]["operation_id"]
    assert ledger.wallet_q_atom_balance("wallet:consumer") == 550
    return app, ledger, next_funding, extension_id


def test_abci_extend_checkpoint_and_two_step_release_conserve_funds() -> None:
    app, ledger, funding, extension_id = _prepare_extended_abci()

    checkpoint = app.finalize_block(
        block_height=3,
        block_hash=b"C" * 32,
        txs=[_checkpoint_tx(funding, previous_operation_id=extension_id)],
    )
    assert checkpoint.code == "ok"
    assert len(ledger.list_session_checkpoints(SESSION_ID)) == 1
    assert ledger.wallet_q_atom_balance("wallet:consumer") == 550

    partial = _released_funding(funding, payment=100, fees=50)
    partial_result = app.finalize_block(
        block_height=4,
        block_hash=b"D" * 32,
        txs=[
            _release_tx(
                funding,
                partial,
                previous_operation_id=extension_id,
                release_id="release-consensus-1",
                payment=100,
                fees=50,
            )
        ],
    )
    assert partial_result.code == "ok"
    release_id = ledger.snapshot_operations()[-1]["operation_id"]
    assert ledger.wallet_q_atom_balance("wallet:consumer") == 700
    assert ledger.get_session_funding_account(SESSION_ID).funding_state == (
        "PARTIALLY_RELEASED"
    )

    final = _released_funding(partial, payment=1_200, fees=100)
    final_result = app.finalize_block(
        block_height=5,
        block_hash=b"E" * 32,
        txs=[
            _release_tx(
                partial,
                final,
                previous_operation_id=release_id,
                release_id="release-consensus-2",
                payment=1_200,
                fees=100,
            )
        ],
    )
    assert final_result.code == "ok"
    assert ledger.wallet_q_atom_balance("wallet:consumer") == 2_000
    assert ledger.wallet_q_atom_balance("wallet:endpoint") == 0
    account = ledger.get_session_funding_account(SESSION_ID)
    assert account.funding_state == "REFUNDED"
    assert account.consumer_payment_refund_q_atoms == 1_300
    assert account.consumer_fee_refund_q_atoms == 150
    assert account.unsettled_payment_reserve_q_atoms == 0
    assert account.unsettled_fee_reserve_q_atoms == 0

    snapshot = app.prepare_snapshot()
    restored, restored_ledger = _abci()
    assert restored.apply_snapshot(snapshot).code == "ok"
    assert len(restored_ledger.list_session_checkpoints(SESSION_ID)) == 1
    assert restored_ledger.get_session_funding_account(SESSION_ID).funding_state == (
        "REFUNDED"
    )
    assert restored.prepare_snapshot()["app_hash"] == snapshot["app_hash"]


def test_escrow_extension_cannot_be_admitted_with_same_block_lock() -> None:
    app, ledger = _abci()
    funding = _funding()
    lock_tx = _lock_tx(funding)
    lock_id = LedgerOperationEnvelope.model_validate(json.loads(lock_tx)).operation_id
    next_funding = _extended_funding(funding)

    result, tx_results = app.finalize_block_with_results(
        block_height=1,
        block_hash=b"A" * 32,
        txs=[
            lock_tx,
            _extend_tx(
                funding,
                next_funding,
                previous_operation_id=lock_id,
            ),
        ],
    )

    assert result.code == "ok"
    assert [item.code for item in tx_results] == ["ok", "rejected"]
    assert ledger.wallet_q_atom_balance("wallet:consumer") == 900
    assert ledger.get_session_funding_account(SESSION_ID).total_locked_amount_q_atoms == (
        1_100
    )


def test_execution_engine_applies_extend_and_checkpoint() -> None:
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
        txs=[_lock_tx(funding)],
    ).error is None
    lock_id = ledger.snapshot_operations()[-1]["operation_id"]
    next_funding = _extended_funding(funding)
    assert engine.execute_block(
        block_height=2,
        block_hash=b"B" * 32,
        txs=[_extend_tx(funding, next_funding, previous_operation_id=lock_id)],
    ).error is None
    extension_id = ledger.snapshot_operations()[-1]["operation_id"]
    result = engine.execute_block(
        block_height=3,
        block_hash=b"C" * 32,
        txs=[_checkpoint_tx(next_funding, previous_operation_id=extension_id)],
    )
    assert result.error is None
    assert ledger.list_session_checkpoints(SESSION_ID)[0].checkpoint_sequence == 1
