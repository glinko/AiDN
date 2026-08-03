"""Tests for consensus/execution.py — Integration scenarios."""

import json

from aidn_hypervisor.consensus.admission import AdmissionValidator
from aidn_hypervisor.consensus.execution import (
    ExecutionEngine,
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


# ── 1. Full block flow ────────────────────────────────────────────

def test_integration_full_block_flow():
    """End-to-end: submit → execute → verify ledger state."""
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
    assert result.error is None
    assert len(result.execution_events) == 2

    # Ledger has recorded operations
    ops = engine.ledger.snapshot_operations()
    assert len(ops) >= 2


# ── 2. Integration with custom handlers ───────────────────────────

def test_integration_with_custom_handlers():
    """Custom handlers execute alongside default path."""

    handler_calls = []

    def custom_handler(envelope, ledger):
        handler_calls.append(envelope.operation_id)
        return {
            "state_changes": [
                StateChange(
                    entity_type="custom",
                    entity_id=envelope.operation_id,
                    change_type="create",
                )
            ],
            "emitted_events": ["custom.processed"],
        }

    engine = _engine()
    engine.register_handler("CUSTOM_OP", custom_handler, gas_cost=50)

    result = engine.execute_block(
        block_height=1,
        block_hash=BLOCK_HASH,
        txs=[_tx(operation_type="CUSTOM_OP")],
    )

    assert result.operations_executed == 1
    assert len(handler_calls) == 1
    assert len(result.state_changes) >= 1


# ── 3. Integration: ledger state consistent ───────────────────────

def test_integration_ledger_state_consistent():
    """After execution, ledger snapshot matches what was executed."""
    engine = _engine()

    engine.execute_block(
        block_height=1,
        block_hash=BLOCK_HASH,
        txs=[
            _tx(created_at="2025-06-01T11:00:00Z"),
            _tx(created_at="2025-06-01T11:01:00Z"),
            _tx(created_at="2025-06-01T11:02:00Z"),
        ],
    )

    ops = engine.ledger.snapshot_operations()
    # 3 txs executed = 3 ledger records
    assert len(ops) >= 3


def test_integration_ledger_preserves_admitted_envelope():
    """Consensus persistence keeps the original identity and payload."""
    engine = _engine()
    envelope = LedgerOperationEnvelope(
        operation_type="WALLET_TRANSFER",
        origin_type="protocol",
        created_at="2025-06-01T11:00:00Z",
        payload={"recipient": "wallet-b", "amount_q_atoms": 42},
    )

    result = engine.execute_block(
        block_height=1,
        block_hash=BLOCK_HASH,
        txs=[json.dumps(envelope.model_dump(mode="json")).encode("utf-8")],
    )

    assert result.operations_executed == 1
    record = engine.ledger.snapshot_operations()[0]
    assert record["operation_id"] == envelope.operation_id
    assert record["payload"] == envelope.payload


# ── 4. Integration: state root deterministic ──────────────────────

def test_integration_state_root_deterministic():
    """Same inputs → same state root."""
    txs = [_tx(), _tx(origin_type="protocol")]

    engine1 = _engine()
    r1 = engine1.execute_block(block_height=1, block_hash=BLOCK_HASH, txs=txs)

    engine2 = _engine()
    r2 = engine2.execute_block(block_height=1, block_hash=BLOCK_HASH, txs=txs)

    assert r1.state_root == r2.state_root


# ── 5. Integration: multiple blocks ───────────────────────────────

def test_integration_multiple_blocks():
    """Execute multiple blocks sequentially, state accumulates."""
    engine = _engine()

    r1 = engine.execute_block(
        block_height=1, block_hash=BLOCK_HASH, txs=[_tx()]
    )
    r2 = engine.execute_block(
        block_height=2, block_hash=BLOCK_HASH, txs=[_tx(created_at="2025-06-01T11:02:00Z")]
    )

    assert r1.block_height == 1
    assert r2.block_height == 2

    ops = engine.ledger.snapshot_operations()
    assert len(ops) >= 2  # one ledger record per successful tx

    # State root changes between blocks
    assert r1.state_root != r2.state_root


# ── 6. Integration: gas tracking ──────────────────────────────────

def test_integration_gas_tracking():
    """Gas is tracked correctly across a block."""
    engine = _engine()

    result = engine.execute_block(
        block_height=1,
        block_hash=BLOCK_HASH,
        txs=[
            _tx(created_at="2025-06-01T11:00:00Z"),
            _tx(created_at="2025-06-01T11:01:00Z"),
        ],  # each costs 200
    )

    assert result.operations_executed == 2
    total_gas = sum(e.gas_used for e in result.execution_events if e.success)
    assert total_gas == 400  # 2 * 200


# ── 7. Integration: admission sequence ────────────────────────────

def test_integration_admission_sequence():
    """Finalized IDs are updated after block execution."""
    engine = _engine()

    env = LedgerOperationEnvelope(
        operation_type="WALLET_TRANSFER",
        origin_type="protocol",
        created_at="2025-06-01T11:00:00Z",
    )
    data = json.dumps(env.model_dump(mode="json")).encode("utf-8")

    engine.execute_block(
        block_height=1, block_hash=BLOCK_HASH, txs=[data]
    )

    assert env.operation_id in engine.admission._finalized_ids

    # Second block with same tx should be rejected
    result = engine.execute_block(
        block_height=2, block_hash=BLOCK_HASH, txs=[data]
    )
    assert result.operations_rejected == 1


# ── 8. Integration: handler error handling ────────────────────────

def test_integration_handler_error_handling():
    """Handler that raises a non-fatal error rejects the tx but continues."""

    def bad_handler(envelope, ledger):
        raise ValueError("validation rejected")

    engine = _engine()
    engine.register_handler("WALLET_TRANSFER", bad_handler, gas_cost=200)

    snapshot_payload = {
        "snapshot_id": "sha256:snapshot:integration",
        "block_height": 10,
        "epoch": 1,
        "application_state_hash": "sha256:application-state",
        "snapshot_hash": "sha256:snapshot-content",
        "chunk_root": "sha256:chunk-root",
        "protocol_version": "0.1",
        "registry_references": [{"object_id": "sha256:manifest"}],
    }
    result = engine.execute_block(
        block_height=1,
        block_hash=BLOCK_HASH,
        txs=[
            _tx(),
            _tx(operation_type="SNAPSHOT_COMMIT", payload=snapshot_payload),
        ],
    )

    # First tx rejected (non-fatal), second typed Snapshot commit should succeed.
    assert result.error is None  # no fatal error
    assert result.operations_rejected == 1
    assert result.operations_executed == 1


# ── 9. Integration: block height tracking ─────────────────────────

def test_integration_block_height_tracking():
    """Block height is correctly passed through results."""
    engine = _engine()

    for height in range(1, 6):
        result = engine.execute_block(
            block_height=height,
            block_hash=BLOCK_HASH,
            txs=[_tx()],
        )
        assert result.block_height == height


# ── 10. Integration: finalized IDs updated ────────────────────────

def test_integration_finalized_ids_updated():
    """All successfully executed tx IDs end up in finalized set."""
    engine = _engine()

    envs = []
    txs = []
    for i in range(3):
        env = LedgerOperationEnvelope(
            operation_type="WALLET_TRANSFER",
            origin_type="protocol",
            created_at=f"2025-06-01T11:{i:02d}:00Z",
        )
        envs.append(env)
        txs.append(json.dumps(env.model_dump(mode="json")).encode("utf-8"))

    engine.execute_block(
        block_height=1, block_hash=BLOCK_HASH, txs=txs
    )

    for env in envs:
        assert env.operation_id in engine.admission._finalized_ids
