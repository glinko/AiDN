"""RFC-0047 §13-§16 — Deterministic Block Execution Engine."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from aidn_hypervisor.consensus.admission import AdmissionValidator
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope

# ── Data models ─────────────────────────────────────────────────────


@dataclass
class StateChange:
    """Records a single state transition."""

    entity_type: str  # "wallet", "session", "endpoint", "registry", etc.
    entity_id: str
    change_type: str  # "credit", "debit", "create", "update", "delete"
    before: dict | None = None
    after: dict | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class ExecutionEvent:
    """Emitted after each operation execution."""

    operation_id: str
    operation_type: str
    success: bool
    envelope: LedgerOperationEnvelope | None = field(default=None, repr=False)
    state_changes: list[StateChange] = field(default_factory=list)
    emitted_events: list[str] = field(default_factory=list)
    error: str | None = None
    gas_used: int = 0


@dataclass
class BlockExecutionResult:
    """Result of executing a full block of operations."""

    block_height: int
    block_hash: bytes
    operations_executed: int
    operations_rejected: int
    execution_events: list[ExecutionEvent] = field(default_factory=list)
    state_changes: list[StateChange] = field(default_factory=list)
    state_root: str = ""
    atomic: bool = True
    error: str | None = None


# ── Execution Engine ────────────────────────────────────────────────


class ExecutionEngine:
    """
    RFC-0047 §13-§16 — Deterministic block execution engine.

    Executes operations in order within a block, tracks state changes,
    emits events, enforces atomicity.
    """

    # Default gas costs per operation category (class-level, read-only reference)
    _DEFAULT_GAS_COSTS: dict[str, int] = {
        "WALLET_TRANSFER": 200,
        "SESSION_OPEN": 500,
        "DEPOSIT_LOCK": 300,
        "SESSION_SETTLE": 400,
        "ENDPOINT_PUBLISH": 250,
        "VALIDATION_REQUEST": 600,
        "VALIDATION_REPORT": 350,
        "VALIDATOR_STAKE": 450,
        "VALIDATOR_UNSTAKE": 300,
        "REGISTRY_UPSERT": 200,
        "SNAPSHOT_COMMIT": 100,
        "EPOCH_TASK": 150,
    }

    def __init__(
        self,
        *,
        ledger_service: Any,  # LedgerOperationService
        admission_validator: AdmissionValidator,
        handlers: dict[str, Callable] | None = None,
        gas_limit_per_block: int = 10_000_000,
        gas_limit_per_operation: int = 1_000_000,
    ) -> None:
        self.ledger = ledger_service
        self.admission = admission_validator
        self._handlers: dict[str, Callable] = dict(handlers or {})
        self._gas_costs: dict[str, int] = dict(self._DEFAULT_GAS_COSTS)
        self._gas_limit_block = gas_limit_per_block
        self._gas_limit_operation = gas_limit_per_operation

        # Per-block state tracking
        self._state_changes: list[StateChange] = []
        self._execution_events: list[ExecutionEvent] = []
        self._gas_used = 0

    # ── Public API ────────────────────────────────────────────────

    def execute_block(
        self,
        *,
        block_height: int,
        block_hash: bytes,
        txs: list[bytes],
    ) -> BlockExecutionResult:
        """
        Execute all transactions in a block deterministically.

        Atomicity: if any operation fails fatally, the entire block state
        is rolled back to pre-execution.
        """
        # Reset per-block gas counter
        self._gas_used = 0

        # Capture pre-state for potential rollback
        pre_state = self._capture_state()
        pre_admission_state = self.admission.snapshot_state()

        events: list[ExecutionEvent] = []
        changes: list[StateChange] = []
        executed = 0
        rejected = 0
        fatal_error: str | None = None
        successful_envelopes: list[LedgerOperationEnvelope] = []
        seen_operation_ids: set[str] = set()

        for tx_data in txs:
            # Block-level gas check
            if self._gas_used >= self._gas_limit_block:
                rejected += 1
                events.append(
                    ExecutionEvent(
                        operation_id="",
                        operation_type="GAS_EXHAUSTED",
                        success=False,
                        error="block gas limit exceeded",
                    )
                )
                continue

            result = self._execute_one(tx_data, seen_operation_ids)

            if result.success:
                if result.envelope is None:
                    result.success = False
                    result.error = "fatal: successful execution has no envelope"
                else:
                    try:
                        self.ledger.record_admitted_envelope(
                            result.envelope,
                            emitted_events=result.emitted_events,
                        )
                    except Exception as error:
                        result.success = False
                        result.error = f"fatal: ledger commit failed: {error}"
                    else:
                        successful_envelopes.append(result.envelope)
                        seen_operation_ids.add(result.envelope.operation_id)
                        executed += 1
            if not result.success:
                rejected += 1
                # Check for fatal error — triggers atomic rollback
                if result.error and "fatal" in result.error.lower():
                    fatal_error = result.error
                    break

            events.append(result)
            changes.extend(result.state_changes)

        # Atomic rollback on fatal error
        if fatal_error:
            self._restore_state(pre_state)
            self.admission.restore_state(pre_admission_state)
            return BlockExecutionResult(
                block_height=block_height,
                block_hash=block_hash,
                operations_executed=0,
                operations_rejected=len(txs),
                execution_events=[],
                state_changes=[],
                state_root="",
                atomic=True,
                error=fatal_error,
            )

        for envelope in successful_envelopes:
            self.admission.record_finalized(envelope.operation_id)
            if envelope.sender_wallet is not None:
                self.admission.advance_wallet_sequence(envelope.sender_wallet)

        # The root commits to this block's records, not only pre-block state.
        state_root = self._compute_state_root()

        # Store results in tracking lists
        self._execution_events.extend(events)
        self._state_changes.extend(changes)

        return BlockExecutionResult(
            block_height=block_height,
            block_hash=block_hash,
            operations_executed=executed,
            operations_rejected=rejected,
            execution_events=events,
            state_changes=changes,
            state_root=state_root,
            atomic=True,
        )

    def register_handler(
        self,
        operation_type: str,
        handler_fn: Callable,
        *,
        gas_cost: int = 100,
    ) -> None:
        """Register a custom handler for an operation type."""
        self._handlers[operation_type] = handler_fn
        self._gas_costs[operation_type] = gas_cost

    def get_state_changes(self) -> list[StateChange]:
        """Get accumulated state changes."""
        return list(self._state_changes)

    def get_execution_events(self) -> list[ExecutionEvent]:
        """Get accumulated execution events."""
        return list(self._execution_events)

    def reset_tracking(self) -> None:
        """Reset per-block tracking state."""
        self._state_changes.clear()
        self._execution_events.clear()
        self._gas_used = 0

    # ── Internal: single-operation execution ──────────────────────

    def _execute_one(
        self,
        tx_data: bytes,
        seen_operation_ids: set[str],
    ) -> ExecutionEvent:
        """Execute a single transaction."""
        # 1. Parse
        try:
            envelope = self._parse_envelope(tx_data)
        except Exception as e:
            return ExecutionEvent(
                operation_id="",
                operation_type="PARSE_ERROR",
                success=False,
                error=f"parse: {e}",
            )

        # 2. Admission check
        admission = self.admission.validate(envelope)
        if not admission.admitted:
            return ExecutionEvent(
                operation_id=envelope.operation_id,
                operation_type=envelope.operation_type,
                success=False,
                error=f"admission: {admission.reason}",
            )
        if envelope.operation_id in seen_operation_ids:
            return ExecutionEvent(
                operation_id=envelope.operation_id,
                operation_type=envelope.operation_type,
                success=False,
                error="admission: duplicate_operation_id",
            )

        # 3. Per-operation gas check
        gas_cost = self._get_gas_cost(envelope.operation_type)
        if gas_cost > self._gas_limit_operation:
            return ExecutionEvent(
                operation_id=envelope.operation_id,
                operation_type=envelope.operation_type,
                success=False,
                error="operation gas limit exceeded",
            )
        if self._gas_used + gas_cost > self._gas_limit_block:
            return ExecutionEvent(
                operation_id=envelope.operation_id,
                operation_type=envelope.operation_type,
                success=False,
                error="block gas limit exceeded",
            )

        # 4. Execute via registered handler or default path
        state_changes: list[StateChange] = []
        emitted: list[str] = []
        error: str | None = None

        try:
            handler = self._handlers.get(envelope.operation_type)
            if handler:
                result = handler(envelope, self.ledger)
                if isinstance(result, dict):
                    state_changes = result.get("state_changes", [])
                    emitted = result.get("emitted_events", [])
            else:
                # Default: track state change; actual ledger recording happens
                # in execute_block() after all txs succeed (atomicity guarantee)
                state_changes.append(
                    StateChange(
                        entity_type="ledger",
                        entity_id=envelope.operation_id,
                        change_type="create",
                        after={"operation_type": envelope.operation_type},
                    )
                )
                emitted.append(f"operation.recorded:{envelope.operation_id}")

        except Exception as e:
            error = str(e)

        self._gas_used += gas_cost

        return ExecutionEvent(
            operation_id=envelope.operation_id,
            operation_type=envelope.operation_type,
            success=error is None,
            envelope=envelope,
            state_changes=state_changes,
            emitted_events=emitted,
            error=error,
            gas_used=gas_cost,
        )

    # ── Internal: gas ─────────────────────────────────────────────

    def _get_gas_cost(self, operation_type: str) -> int:
        """Get gas cost for an operation type."""
        return self._gas_costs.get(operation_type, 100)

    # ── Internal: state root ──────────────────────────────────────

    def _compute_state_root(self) -> str:
        """Compute deterministic hash of current ledger state."""
        ops = self.ledger.snapshot_operations()
        wallet_seqs = self.ledger.snapshot_wallet_sequences()

        state = {
            "operations": len(ops),
            "wallets": wallet_seqs,
        }
        canonical = json.dumps(state, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()

    # ── Internal: parse ───────────────────────────────────────────

    def _parse_envelope(self, tx_data: bytes) -> LedgerOperationEnvelope:
        """Parse raw bytes into LedgerOperationEnvelope."""
        obj = json.loads(tx_data)
        return LedgerOperationEnvelope.model_validate(obj)

    # ── Internal: state capture / restore (atomicity) ─────────────

    def _capture_state(self) -> dict:
        """Capture current ledger state for potential rollback."""
        return {
            "operations": self.ledger.snapshot_operations(),
            "wallet_sequences": self.ledger.snapshot_wallet_sequences(),
            "settlement_state": self.ledger.snapshot_settlement_state(),
        }

    def _restore_state(self, state: dict) -> None:
        """Restore ledger state from captured snapshot."""
        settlement = state.get("settlement_state", {})
        self.ledger.restore(
            operations=state.get("operations", []),
            wallet_sequences=state.get("wallet_sequences", {}),
            wallet_q_atom_balances=settlement.get("wallet_q_atom_balances"),
            session_funding_accounts=settlement.get("session_funding_accounts"),
            settlement_proposals=settlement.get("settlement_proposals"),
            settlement_acceptances=settlement.get("settlement_acceptances"),
            settlement_transition_hashes=settlement.get(
                "settlement_transition_hashes"
            ),
        )
        self._gas_used = 0
        self._state_changes.clear()
        self._execution_events.clear()
