"""Tests for consensus/execution.py — ExecutionEngine core behaviour."""

import json

from aidn_hypervisor.consensus.admission import AdmissionValidator
from aidn_hypervisor.consensus.execution import (
    BlockExecutionResult,
    ExecutionEngine,
    ExecutionEvent,
    StateChange,
)
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


# ── 1. Empty block ─────────────────────────────────────────────────

def test_execute_empty_block():
    engine = _engine()
    result = engine.execute_block(
        block_height=1,
        block_hash=BLOCK_HASH,
        txs=[],
    )
    assert isinstance(result, BlockExecutionResult)
    assert result.block_height == 1
    assert result.operations_executed == 0
    assert result.operations_rejected == 0
    assert result.error is None
    assert result.state_root != ""


# ── 2. Single valid tx ────────────────────────────────────────────

def test_execute_single_valid_tx():
    engine = _engine()
    result = engine.execute_block(
        block_height=1,
        block_hash=BLOCK_HASH,
        txs=[_tx()],
    )
    assert result.operations_executed == 1
    assert result.operations_rejected == 0
    assert result.error is None


# ── 3. Multiple valid txs ─────────────────────────────────────────

def test_execute_multiple_valid_txs():
    engine = _engine()
    txs = [
        _tx(created_at="2025-06-01T11:00:00Z"),
        _tx(created_at="2025-06-01T11:01:00Z"),
    ]
    result = engine.execute_block(
        block_height=2,
        block_hash=BLOCK_HASH,
        txs=txs,
    )
    assert result.operations_executed == 2
    assert result.operations_rejected == 0


# ── 4. Block with invalid tx (bad JSON) ───────────────────────────

def test_execute_block_with_invalid_tx():
    engine = _engine()
    result = engine.execute_block(
        block_height=1,
        block_hash=BLOCK_HASH,
        txs=[b"not json at all"],
    )
    assert result.operations_rejected == 1
    assert result.operations_executed == 0
    assert result.execution_events[0].operation_type == "PARSE_ERROR"


# ── 5. Block with expired tx ──────────────────────────────────────

def test_execute_block_with_expired_tx():
    engine = _engine()
    result = engine.execute_block(
        block_height=1,
        block_hash=BLOCK_HASH,
        txs=[_tx(expires_at="2020-01-01T00:00:00Z")],
    )
    assert result.operations_rejected == 1
    assert "expired" in result.execution_events[0].error


# ── 6. Block with duplicate tx ────────────────────────────────────

def test_execute_block_with_duplicate_tx():
    env = LedgerOperationEnvelope(
        operation_type="WALLET_TRANSFER",
        origin_type="wallet",
        created_at="2025-06-01T11:00:00Z",
    )
    adm = _admission(finalized_operation_ids={env.operation_id})
    engine = _engine(admission_validator=adm)
    data = json.dumps(env.model_dump(mode="json")).encode("utf-8")
    result = engine.execute_block(
        block_height=1,
        block_hash=BLOCK_HASH,
        txs=[data],
    )
    assert result.operations_rejected == 1
    assert "duplicate" in result.execution_events[0].error


# ── 7. Block tracks state changes ─────────────────────────────────

def test_execute_block_tracks_state_changes():
    engine = _engine()
    result = engine.execute_block(
        block_height=1,
        block_hash=BLOCK_HASH,
        txs=[_tx()],
    )
    assert len(result.state_changes) >= 1
    assert isinstance(result.state_changes[0], StateChange)


# ── 8. Block tracks execution events ──────────────────────────────

def test_execute_block_tracks_execution_events():
    engine = _engine()
    result = engine.execute_block(
        block_height=1,
        block_hash=BLOCK_HASH,
        txs=[_tx()],
    )
    assert len(result.execution_events) == 1
    assert isinstance(result.execution_events[0], ExecutionEvent)
    assert result.execution_events[0].success is True


# ── 9. Block computes state root ──────────────────────────────────

def test_execute_block_computes_state_root():
    engine = _engine()
    result = engine.execute_block(
        block_height=1,
        block_hash=BLOCK_HASH,
        txs=[_tx()],
    )
    assert result.state_root != ""
    assert len(result.state_root) == 64  # SHA-256 hex


# ── 10. Block records in ledger ───────────────────────────────────

def test_execute_block_records_in_ledger():
    engine = _engine()
    engine.execute_block(
        block_height=1,
        block_hash=BLOCK_HASH,
        txs=[_tx()],
    )
    ops = engine.ledger.snapshot_operations()
    assert len(ops) >= 1


# ── 11. Block marks finalized ─────────────────────────────────────

def test_execute_block_marks_finalized():
    engine = _engine()
    env = LedgerOperationEnvelope(
        operation_type="WALLET_TRANSFER",
        origin_type="protocol",
        created_at="2025-06-01T11:00:00Z",
    )
    data = json.dumps(env.model_dump(mode="json")).encode("utf-8")
    engine.execute_block(
        block_height=1,
        block_hash=BLOCK_HASH,
        txs=[data],
    )
    assert env.operation_id in engine.admission._finalized_ids


# ── 12. Register custom handler ───────────────────────────────────

def test_register_custom_handler():
    engine = _engine()

    def my_handler(envelope, ledger):
        return {
            "state_changes": [
                StateChange(
                    entity_type="custom",
                    entity_id="e1",
                    change_type="create",
                )
            ],
            "emitted_events": ["custom.event"],
        }

    engine.register_handler("CUSTOM_OP", my_handler, gas_cost=50)
    assert "CUSTOM_OP" in engine._handlers
    assert engine._gas_costs.get("CUSTOM_OP") == 50


# ── 13. Custom handler returns state changes ──────────────────────

def test_custom_handler_returns_state_changes():
    engine = _engine()

    def handler(envelope, ledger):
        return {
            "state_changes": [
                StateChange(
                    entity_type="wallet",
                    entity_id="w1",
                    change_type="credit",
                    after={"balance": 1000},
                )
            ],
            "emitted_events": ["wallet.credited"],
        }

    engine.register_handler("CUSTOM_TRANSFER", handler, gas_cost=100)
    result = engine.execute_block(
        block_height=1,
        block_hash=BLOCK_HASH,
        txs=[_tx(operation_type="CUSTOM_TRANSFER")],
    )
    assert result.operations_executed == 1
    assert len(result.state_changes) >= 1
    assert result.state_changes[0].entity_type == "wallet"


# ── 14. Gas limit per operation ───────────────────────────────────

def test_gas_limit_per_operation():
    engine = _engine(gas_limit_per_operation=50)
    result = engine.execute_block(
        block_height=1,
        block_hash=BLOCK_HASH,
        txs=[_tx()],
    )
    # WALLET_TRANSFER costs 200 > 50
    assert result.operations_rejected == 1
    assert "gas" in result.execution_events[0].error.lower()


# ── 15. Gas limit per block ───────────────────────────────────────

def test_gas_limit_per_block():
    engine = _engine(gas_limit_per_block=200)
    txs = [
        _tx(created_at="2025-06-01T11:00:00Z"),
        _tx(created_at="2025-06-01T11:01:00Z"),
    ]  # each costs 200
    result = engine.execute_block(
        block_height=1,
        block_hash=BLOCK_HASH,
        txs=txs,
    )
    # First tx succeeds (200 used), second is rejected (gas exhausted)
    assert result.operations_executed == 1
    assert result.operations_rejected == 1
    assert result.execution_events[1].operation_type == "GAS_EXHAUSTED"


# ── 16. Gas cost by operation type ────────────────────────────────

def test_gas_cost_by_operation_type():
    engine = _engine()
    assert engine._get_gas_cost("WALLET_TRANSFER") == 200
    assert engine._get_gas_cost("SESSION_OPEN") == 500
    assert engine._get_gas_cost("SNAPSHOT_COMMIT") == 100
    assert engine._get_gas_cost("UNKNOWN_TYPE") == 100


# ── 17. Parse error handling ──────────────────────────────────────

def test_parse_error_handling():
    engine = _engine()
    result = engine.execute_block(
        block_height=1,
        block_hash=BLOCK_HASH,
        txs=[b"not valid json", _tx()],
    )
    assert result.operations_rejected >= 1
    assert result.operations_executed >= 1


# ── 18. Admission failure handling ────────────────────────────────

def test_admission_failure_handling():
    env = LedgerOperationEnvelope(
        operation_type="WALLET_TRANSFER",
        origin_type="wallet",
        created_at="2025-06-01T11:00:00Z",
    )
    adm = _admission(finalized_operation_ids={env.operation_id})
    engine = _engine(admission_validator=adm)
    data = json.dumps(env.model_dump(mode="json")).encode("utf-8")
    result = engine.execute_block(
        block_height=1,
        block_hash=BLOCK_HASH,
        txs=[data],
    )
    assert result.operations_rejected == 1
    assert result.execution_events[0].success is False


# ── 19. Reset tracking ────────────────────────────────────────────

def test_reset_tracking():
    engine = _engine()
    engine.execute_block(
        block_height=1,
        block_hash=BLOCK_HASH,
        txs=[_tx()],
    )
    assert len(engine.get_execution_events()) > 0
    assert engine._gas_used > 0
    engine.reset_tracking()
    assert len(engine.get_execution_events()) == 0
    assert len(engine.get_state_changes()) == 0
    assert engine._gas_used == 0


# ── 20. State root changes after execution ────────────────────────

def test_state_root_changes_after_execution():
    engine = _engine()
    root_before = engine._compute_state_root()
    engine.execute_block(
        block_height=1,
        block_hash=BLOCK_HASH,
        txs=[_tx()],
    )
    root_after = engine._compute_state_root()
    assert root_before != root_after
