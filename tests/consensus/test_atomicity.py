"""Tests for consensus/execution.py — Atomicity and rollback behaviour."""

import json

import pytest

from aidn_hypervisor.consensus.admission import AdmissionValidator
from aidn_hypervisor.consensus.execution import ExecutionEngine
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.ledger.service import LedgerOperationService


# ── Helpers ─────────────────────────────────────────────────────────

NOW = "2025-06-01T12:00:00Z"
BLOCK_HASH = b"\x01" * 32


def _ledger() -> LedgerOperationService:
    return LedgerOperationService()


def _admission(**kw) -> AdmissionValidator:
    return AdmissionValidator(current_time=NOW, **kw)


def _engine(**kw) -> ExecutionEngine:
    defaults: dict = {
        "ledger_service": _ledger(),
        "admission_validator": _admission(),
    }
    defaults.update(kw)
    return ExecutionEngine(**defaults)


def _envelope_data(**kw) -> dict:
    return {
        "operation_type": "WALLET_TRANSFER",
        "origin_type": "protocol",
        "created_at": "2025-06-01T11:00:00Z",
        **kw,
    }


def _tx(**kw) -> bytes:
    return json.dumps(_envelope_data(**kw)).encode("utf-8")


# ── 1. Atomic rollback on fatal error ─────────────────────────────

def test_atomic_rollback_on_fatal_error():
    """A fatal error in any tx triggers full block rollback."""

    def fatal_handler(envelope, ledger):
        raise RuntimeError("fatal: ledger corruption detected")

    engine = _engine()
    engine.register_handler("WALLET_TRANSFER", fatal_handler, gas_cost=200)

    result = engine.execute_block(
        block_height=1,
        block_hash=BLOCK_HASH,
        txs=[_tx()],
    )

    assert result.error is not None
    assert "fatal" in result.error.lower()
    assert result.operations_executed == 0
    assert result.operations_rejected == 1


# ── 2. Atomic preserves state on rollback ─────────────────────────

def test_atomic_preserves_state_on_rollback():
    """After rollback, ledger is back to pre-block state."""

    # Seed ledger with one operation
    engine = _engine()
    engine.ledger.record_operation(
        operation_type="SNAPSHOT_COMMIT",
        origin_type="protocol",
        fee_class="standard",
    )
    pre_ops = engine.ledger.snapshot_operations()
    assert len(pre_ops) == 1

    def fatal_handler(envelope, ledger):
        raise RuntimeError("fatal error")

    engine.register_handler("WALLET_TRANSFER", fatal_handler, gas_cost=200)

    result = engine.execute_block(
        block_height=1,
        block_hash=BLOCK_HASH,
        txs=[_tx()],
    )

    post_ops = engine.ledger.snapshot_operations()
    assert len(post_ops) == len(pre_ops)  # rolled back
    assert result.error is not None


# ── 3. Atomic no rollback on normal failure ───────────────────────

def test_atomic_no_rollback_on_normal_failure():
    """Non-fatal errors do NOT trigger rollback."""

    def bad_handler(envelope, ledger):
        raise ValueError("validation rejected")

    engine = _engine()
    engine.register_handler("WALLET_TRANSFER", bad_handler, gas_cost=200)

    result = engine.execute_block(
        block_height=1,
        block_hash=BLOCK_HASH,
        txs=[_tx()],
    )

    # Non-fatal: no rollback, tx rejected but block continues
    assert result.error is None
    assert result.operations_rejected == 1


# ── 4. Atomic all-or-nothing ──────────────────────────────────────

def test_atomic_all_or_nothing():
    """Fatal error means zero operations counted as executed."""
    engine = _engine()

    def fatal_handler(envelope, ledger):
        raise RuntimeError("fatal: state mismatch")

    engine.register_handler("WALLET_TRANSFER", fatal_handler, gas_cost=200)

    result = engine.execute_block(
        block_height=1,
        block_hash=BLOCK_HASH,
        txs=[_tx(), _tx(origin_type="protocol")],
    )

    assert result.operations_executed == 0
    assert result.operations_rejected == 2  # all rejected on fatal


# ── 5. Gas exhaustion does not trigger rollback ───────────────────

def test_atomic_gas_exhaustion_no_rollback():
    """Gas exhaustion rejects remaining txs but does not rollback."""
    engine = _engine(gas_limit_per_block=200)
    result = engine.execute_block(
        block_height=1,
        block_hash=BLOCK_HASH,
        txs=[
            _tx(created_at="2025-06-01T11:00:00Z"),
            _tx(created_at="2025-06-01T11:01:00Z"),
        ],
    )
    assert result.error is None  # no fatal, no rollback
    assert result.operations_executed == 1
    assert result.operations_rejected == 1


# ── 6. State changes cleared on rollback ──────────────────────────

def test_atomic_state_changes_cleared_on_rollback():
    """After fatal rollback, internal state_changes list is cleared."""

    def fatal_handler(envelope, ledger):
        raise RuntimeError("fatal")

    engine = _engine()
    engine.register_handler("WALLET_TRANSFER", fatal_handler, gas_cost=200)

    engine.execute_block(
        block_height=1,
        block_hash=BLOCK_HASH,
        txs=[_tx()],
    )

    assert len(engine.get_state_changes()) == 0


# ── 7. Execution events cleared on rollback ───────────────────────

def test_atomic_events_cleared_on_rollback():
    """After fatal rollback, internal execution_events list is cleared."""

    def fatal_handler(envelope, ledger):
        raise RuntimeError("fatal")

    engine = _engine()
    engine.register_handler("WALLET_TRANSFER", fatal_handler, gas_cost=200)

    engine.execute_block(
        block_height=1,
        block_hash=BLOCK_HASH,
        txs=[_tx()],
    )

    assert len(engine.get_execution_events()) == 0


# ── 8. Block result on rollback ───────────────────────────────────

def test_atomic_block_result_on_rollback():
    """Rollback result has empty events, empty state_changes, empty root."""

    def fatal_handler(envelope, ledger):
        raise RuntimeError("fatal error")

    engine = _engine()
    engine.register_handler("WALLET_TRANSFER", fatal_handler, gas_cost=200)

    result = engine.execute_block(
        block_height=1,
        block_hash=BLOCK_HASH,
        txs=[_tx()],
    )

    assert result.execution_events == []
    assert result.state_changes == []
    assert result.state_root == ""
    assert result.atomic is True


# ── 9. Capture and restore state ──────────────────────────────────

def test_capture_and_restore_state():
    """_capture_state + _restore_state round-trips correctly."""
    engine = _engine()
    engine.ledger.record_operation(
        operation_type="SNAPSHOT_COMMIT",
        origin_type="protocol",
        fee_class="standard",
    )
    snap = engine._capture_state()
    assert "operations" in snap
    assert "wallet_sequences" in snap
    assert "settlement_state" in snap

    # Modify ledger
    engine.ledger.record_operation(
        operation_type="REGISTRY_UPSERT",
        origin_type="protocol",
        fee_class="standard",
    )
    assert len(engine.ledger.snapshot_operations()) == 2

    # Restore
    engine._restore_state(snap)
    assert len(engine.ledger.snapshot_operations()) == 1


# ── 10. Restore operations ────────────────────────────────────────

def test_restore_operations():
    """Restoring operations list restores the exact set."""
    engine = _engine()
    engine.ledger.record_operation(
        operation_type="SNAPSHOT_COMMIT",
        origin_type="protocol",
        fee_class="standard",
    )
    snap = engine._capture_state()

    engine.ledger.record_operation(
        operation_type="REGISTRY_UPSERT",
        origin_type="protocol",
        fee_class="standard",
    )
    engine._restore_state(snap)
    ops = engine.ledger.snapshot_operations()
    assert len(ops) == 1
    assert ops[0]["operation_type"] == "SNAPSHOT_COMMIT"


# ── 11. Restore wallet sequences ──────────────────────────────────

def test_restore_wallet_sequences():
    """Restoring wallet sequences restores the exact map."""
    engine = _engine()
    engine.ledger._wallet_next_sequences["w1"] = 5
    snap = engine._capture_state()

    engine.ledger._wallet_next_sequences["w1"] = 99
    engine._restore_state(snap)
    assert engine.ledger._wallet_next_sequences["w1"] == 5


# ── 12. Restore settlement state ──────────────────────────────────

def test_restore_settlement_state():
    """Restoring settlement state (balances, funding accounts, etc.)."""
    engine = _engine()
    engine.ledger.credit_wallet_q_atoms(wallet_id="w1", amount_q_atoms=1000)
    snap = engine._capture_state()

    engine.ledger.credit_wallet_q_atoms(wallet_id="w1", amount_q_atoms=5000)
    assert engine.ledger.wallet_q_atom_balance("w1") == 6000

    engine._restore_state(snap)
    assert engine.ledger.wallet_q_atom_balance("w1") == 1000


# ── 13. Atomic with empty block ───────────────────────────────────

def test_atomic_with_empty_block():
    """Empty block — no rollback needed, clean result."""
    engine = _engine()
    result = engine.execute_block(
        block_height=1,
        block_hash=BLOCK_HASH,
        txs=[],
    )
    assert result.error is None
    assert result.operations_executed == 0
    assert result.operations_rejected == 0
    assert result.state_root != ""


# ── 14. Atomic with all valid ─────────────────────────────────────

def test_atomic_with_all_valid():
    """All txs valid — no rollback, all counted."""
    engine = _engine()
    result = engine.execute_block(
        block_height=1,
        block_hash=BLOCK_HASH,
        txs=[
            _tx(created_at="2025-06-01T11:00:00Z"),
            _tx(created_at="2025-06-01T11:01:00Z"),
        ],
    )
    assert result.operations_executed == 2
    assert result.operations_rejected == 0
    assert result.error is None


# ── 15. Gas reset on rollback ─────────────────────────────────────

def test_atomic_gas_reset_on_rollback():
    """After fatal rollback, gas counter is reset to 0."""

    def fatal_handler(envelope, ledger):
        raise RuntimeError("fatal")

    engine = _engine()
    engine.register_handler("WALLET_TRANSFER", fatal_handler, gas_cost=200)

    engine.execute_block(
        block_height=1,
        block_hash=BLOCK_HASH,
        txs=[_tx()],
    )

    assert engine._gas_used == 0
