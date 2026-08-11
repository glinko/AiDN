from __future__ import annotations

import json

from aidn_hypervisor.consensus.abci import AIDNABCIApplication
from aidn_hypervisor.consensus.admission import AdmissionValidator
from aidn_hypervisor.consensus.execution import ExecutionEngine
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.ledger.service import (
    STANDARD_NETWORK_FEE_Q_ATOMS,
    LedgerOperationService,
)


def _tx(*, sender: str = "wallet:sender", amount: int = 25) -> bytes:
    envelope = LedgerOperationEnvelope(
        operation_type="WALLET_TRANSFER",
        operation_version="1.0.0",
        protocol_version="0.1",
        origin_type="wallet",
        sender_wallet=sender,
        sender_sequence=1,
        fee_payer=sender,
        fee_class="standard",
        created_at="2030-01-01T00:00:00Z",
        expires_at="2030-01-02T00:00:00Z",
        payload={
            "recipient_wallet": "wallet:recipient",
            "amount": amount,
            "memo_hash": "sha256:test-memo",
        },
        signatures=["ed25519:sender"],
    )
    return json.dumps(envelope.model_dump(mode="json")).encode("utf-8")


def _ledger() -> LedgerOperationService:
    ledger = LedgerOperationService()
    ledger.credit_wallet_q_atoms(wallet_id="wallet:sender", amount_q_atoms=100_000)
    return ledger


def test_abci_wallet_transfer_moves_amount_and_recycles_standard_fee() -> None:
    ledger = _ledger()
    app = AIDNABCIApplication(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        strict_operation_coverage=True,
    )

    result, tx_results = app.finalize_block_with_results(
        block_height=1,
        block_hash=b"A" * 32,
        txs=[_tx()],
    )

    assert result.code == "ok"
    assert tx_results[0].code == "ok"
    assert ledger.wallet_q_atom_balance("wallet:sender") == (
        100_000 - 25 - STANDARD_NETWORK_FEE_Q_ATOMS
    )
    assert ledger.wallet_q_atom_balance("wallet:recipient") == 25
    assert ledger.recyclable_q_atom_balance() == STANDARD_NETWORK_FEE_Q_ATOMS


def test_execution_engine_matches_abci_wallet_transfer_transition() -> None:
    ledger = _ledger()
    engine = ExecutionEngine(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        strict_operation_coverage=True,
    )

    result = engine.execute_block(
        block_height=1,
        block_hash=b"B" * 32,
        txs=[_tx()],
    )

    assert result.error is None
    assert result.operations_executed == 1
    assert result.execution_events[0].emitted_events == [
        "WalletTransferred",
        "NetworkFeeRecycled",
    ]
    assert ledger.wallet_q_atom_balance("wallet:sender") == (
        100_000 - 25 - STANDARD_NETWORK_FEE_Q_ATOMS
    )
    assert ledger.wallet_q_atom_balance("wallet:recipient") == 25
    assert ledger.recyclable_q_atom_balance() == STANDARD_NETWORK_FEE_Q_ATOMS


def test_abci_wallet_transfer_replay_does_not_move_balance_twice() -> None:
    ledger = _ledger()
    app = AIDNABCIApplication(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        strict_operation_coverage=True,
    )
    first = app.finalize_block(
        block_height=1,
        block_hash=b"C" * 32,
        txs=[_tx()],
    )
    second, tx_results = app.finalize_block_with_results(
        block_height=2,
        block_hash=b"D" * 32,
        txs=[_tx()],
    )

    assert first.code == "ok"
    assert second.code == "ok"
    assert tx_results[0].code == "rejected"
    assert "duplicate" in tx_results[0].log
    assert ledger.wallet_q_atom_balance("wallet:sender") == (
        100_000 - 25 - STANDARD_NETWORK_FEE_Q_ATOMS
    )
    assert ledger.wallet_q_atom_balance("wallet:recipient") == 25
    assert ledger.recyclable_q_atom_balance() == STANDARD_NETWORK_FEE_Q_ATOMS


def test_wallet_transfer_rejects_insufficient_balance_before_recording() -> None:
    ledger = LedgerOperationService()
    ledger.credit_wallet_q_atoms(wallet_id="wallet:sender", amount_q_atoms=10_024)
    app = AIDNABCIApplication(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        strict_operation_coverage=True,
    )

    result, tx_results = app.finalize_block_with_results(
        block_height=1,
        block_hash=b"E" * 32,
        txs=[_tx()],
    )

    assert result.code == "ok"
    assert tx_results[0].code == "rejected"
    assert "insufficient" in tx_results[0].log
    assert ledger.snapshot_operations() == []
    assert ledger.wallet_q_atom_balance("wallet:sender") == 10_024


def test_abci_snapshot_restore_preserves_wallet_transfer_economics() -> None:
    ledger = _ledger()
    app = AIDNABCIApplication(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        strict_operation_coverage=True,
    )
    result = app.finalize_block(
        block_height=1,
        block_hash=b"F" * 32,
        txs=[_tx()],
    )
    snapshot = app.prepare_snapshot()

    restored_ledger = LedgerOperationService()
    restored = AIDNABCIApplication(
        ledger_service=restored_ledger,
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        strict_operation_coverage=True,
    )
    restore_result = restored.apply_snapshot(snapshot)

    assert result.code == "ok"
    assert restore_result.code == "ok"
    assert restored_ledger.wallet_q_atom_balance("wallet:sender") == (
        100_000 - 25 - STANDARD_NETWORK_FEE_Q_ATOMS
    )
    assert restored_ledger.wallet_q_atom_balance("wallet:recipient") == 25
    assert restored_ledger.recyclable_q_atom_balance() == STANDARD_NETWORK_FEE_Q_ATOMS
    assert restored.prepare_snapshot()["app_hash"] == snapshot["app_hash"]

    # A snapshot restore must rebuild admission replay protection from the
    # canonical operation log. Otherwise the same transfer can pass CheckTx
    # after restart and fail only later during block execution.
    replay = restored.check_transaction(_tx())
    assert replay.code == "rejected"
    assert replay.log == "duplicate_operation_id"


def test_abci_query_exposes_only_finalized_operation_replay_provenance() -> None:
    ledger = _ledger()
    app = AIDNABCIApplication(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        strict_operation_coverage=True,
    )
    tx = _tx()
    envelope = LedgerOperationEnvelope.model_validate(json.loads(tx))
    app.finalize_block(block_height=1, block_hash=b"G" * 32, txs=[tx])

    response = app.query(path=f"operation/finalized/{envelope.operation_id}")
    reference = json.loads(response.value)

    assert reference["operation_id"] == envelope.operation_id
    assert reference["operation_type"] == "WALLET_TRANSFER"
    assert reference["sequence_id"] == 1
    assert "payload" not in reference
    assert "signatures" not in reference


def test_abci_repairs_a_noncanonical_admission_replay_cache_entry() -> None:
    ledger = _ledger()
    admission = AdmissionValidator(current_time="2030-01-01T00:00:00Z")
    tx = _tx()
    envelope = LedgerOperationEnvelope.model_validate(json.loads(tx))
    admission.record_finalized(envelope.operation_id)
    app = AIDNABCIApplication(
        ledger_service=ledger,
        admission_validator=admission,
        strict_operation_coverage=True,
    )

    # This simulates a validator process which survived a controlled chain
    # reset. The cache is not authority when the canonical Ledger lacks the ID.
    result = app.check_transaction(tx)

    assert result.code == "ok"
