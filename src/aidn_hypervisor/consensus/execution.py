"""RFC-0047 §13-§16 — Deterministic Block Execution Engine."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from aidn_hypervisor.consensus.admission import AdmissionValidator
from aidn_hypervisor.consensus.coverage import (
    VALIDATION_EVIDENCE_OPERATION_TYPES,
    strict_operation_coverage_error,
    strict_operation_version_error,
)
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.consensus.protocol_authority import ProtocolAuthorityPolicy

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
    validator_updates: list[dict] = field(default_factory=list)


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
    validator_updates: list[dict] = field(default_factory=list)


def compute_execution_state_root(ledger_service: Any) -> str:
    """Compute the deterministic execution StateRoot for a Ledger projection."""
    ops = ledger_service.snapshot_operations()
    wallet_seqs = ledger_service.snapshot_wallet_sequences()

    state: dict[str, Any] = {
        "operations": len(ops),
        "wallets": wallet_seqs,
    }
    consensus_state = ledger_service.snapshot_consensus_state()
    if (
        consensus_state["active_validator_set"]
        or consensus_state["active_validator_set_epoch"] is not None
        or consensus_state["activated_validator_set_epochs"]
    ):
        state["consensus_state"] = consensus_state
    canonical = json.dumps(state, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


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
        "OPERATOR_WALLET_BIND": 150,
        "SESSION_OPEN": 500,
        "DEPOSIT_LOCK": 300,
        "SESSION_ESCROW_LOCK": 300,
        "SESSION_ESCROW_EXTEND": 250,
        "SESSION_ESCROW_RELEASE": 250,
        "SESSION_CHECKPOINT_COMMIT": 200,
        "SESSION_SETTLEMENT_READY_COMMIT": 175,
        "SESSION_SETTLEMENT_PROPOSE": 250,
        "SESSION_SETTLEMENT_ACCEPT": 200,
        "SESSION_SETTLEMENT_DISPUTE": 250,
        "SESSION_SETTLEMENT_PARTIAL_FINALIZE": 400,
        "SESSION_SETTLEMENT_CORRECT": 300,
        "SESSION_SETTLEMENT_FINALIZE": 400,
        "SESSION_FORCE_SETTLE": 400,
        "SESSION_SETTLE": 400,
        "ENDPOINT_PUBLISH": 250,
        "VALIDATION_REQUEST": 600,
        "VALIDATION_REPORT": 350,
        "VALIDATOR_STAKE": 450,
        "VALIDATOR_UNSTAKE": 300,
        "REGISTRY_UPSERT": 200,
        "SNAPSHOT_COMMIT": 100,
        "SESSION_FAILURE_EVIDENCE": 150,
        "CONSENSUS_VALIDATOR_SET_UPDATE": 200,
        "EPOCH_TASK": 150,
        "EPOCH_TRANSITION": 200,
        "EPOCH_SCHEDULE_COMMIT": 150,
        "EPOCH_SCHEDULE_REBASE": 150,
        "EPOCH_RESULT_MANIFEST_COMMIT": 175,
        "TREASURY_MANIFEST_BIND": 250,
        "TREASURY_FUND": 250,
        "REWARD_MINT": 250,
        "SERVICE_VERIFICATION_COMMIT": 200,
        "REPUTATION_PROFILE_UPDATE": 250,
        "PENALTY_APPLY": 250,
        "STAKE_LOCK": 300,
        "UNSTAKE_REQUEST": 200,
        "STAKE_RELEASE": 200,
        "PARTICIPANT_SUSPEND": 200,
        "PARTICIPANT_REINSTATE": 200,
    }

    def __init__(
        self,
        *,
        ledger_service: Any,  # LedgerOperationService
        admission_validator: AdmissionValidator,
        handlers: dict[str, Callable] | None = None,
        gas_limit_per_block: int = 10_000_000,
        gas_limit_per_operation: int = 1_000_000,
        strict_operation_coverage: bool = False,
        protocol_authority_policy: ProtocolAuthorityPolicy | None = None,
    ) -> None:
        self.ledger = ledger_service
        self.admission = admission_validator
        self._handlers: dict[str, Callable] = dict(handlers or {})
        self._gas_costs: dict[str, int] = dict(self._DEFAULT_GAS_COSTS)
        self._gas_limit_block = gas_limit_per_block
        self._gas_limit_operation = gas_limit_per_operation
        self._strict_operation_coverage = strict_operation_coverage
        self._protocol_authority_policy = protocol_authority_policy

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
        seen_operation_ids: set[str] = set()
        finalized_operation_ids_method = getattr(self.ledger, "finalized_operation_ids", None)
        finalized_operation_ids = (
            set(finalized_operation_ids_method())
            if callable(finalized_operation_ids_method)
            else {
                str(operation["operation_id"])
                for operation in self.ledger.snapshot_operations()
                if operation.get("operation_id")
            }
        )
        preexisting_epoch_schedule_commit = (
            self.ledger.epoch_schedule_commitment() is not None
        )
        block_contains_epoch_schedule_commit = False
        for tx_data in txs:
            try:
                if self._parse_envelope(tx_data).operation_type == "EPOCH_SCHEDULE_COMMIT":
                    block_contains_epoch_schedule_commit = True
                    break
            except Exception:
                continue
        validator_updates: list[dict] = []

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

            result = self._execute_one(
                tx_data,
                seen_operation_ids,
                finalized_operation_ids=finalized_operation_ids,
                preexisting_epoch_schedule_commit=preexisting_epoch_schedule_commit,
                block_contains_epoch_schedule_commit=block_contains_epoch_schedule_commit,
            )

            if result.success:
                if result.envelope is None:
                    result.success = False
                    result.error = "fatal: successful execution has no envelope"
                else:
                    try:
                        if result.envelope.operation_type == "WALLET_TRANSFER" and self._strict_operation_coverage:
                            self.ledger.apply_consensus_wallet_transfer(result.envelope)
                        elif result.envelope.operation_type == "OPERATOR_WALLET_BIND":
                            self.ledger.apply_consensus_operator_wallet_bind(result.envelope)
                        elif result.envelope.operation_type == "ENDPOINT_PUBLISH":
                            self.ledger.apply_consensus_endpoint_publish(result.envelope)
                        elif result.envelope.operation_type == "SESSION_OPEN" and self._strict_operation_coverage:
                            self.ledger.apply_consensus_session_open(
                                result.envelope,
                                finalized_operation_ids=finalized_operation_ids,
                            )
                        elif result.envelope.operation_type == "SESSION_ACCEPT" and self._strict_operation_coverage:
                            self.ledger.apply_consensus_session_accept(
                                result.envelope,
                                finalized_operation_ids=finalized_operation_ids,
                            )
                        elif result.envelope.operation_type == "REWARD_MINT":
                            self.ledger.apply_consensus_reward_mint(
                                result.envelope,
                                finalized_operation_ids=finalized_operation_ids,
                            )
                        elif result.envelope.operation_type == "DEVELOPMENT_REWARD_CALCULATE":
                            self.ledger.apply_consensus_development_reward_calculate(
                                result.envelope,
                            )
                        elif result.envelope.operation_type == "DEVELOPMENT_POOL_ALLOCATE":
                            self.ledger.apply_consensus_development_pool_allocate(
                                result.envelope,
                                finalized_operation_ids=finalized_operation_ids,
                            )
                        elif result.envelope.operation_type == "DEVELOPMENT_POOL_CARRYOVER":
                            self.ledger.apply_consensus_development_pool_carryover(
                                result.envelope,
                                finalized_operation_ids=finalized_operation_ids,
                            )
                        elif result.envelope.operation_type == "DEVELOPMENT_BOUNTY_CREATE":
                            self.ledger.apply_consensus_development_bounty_create(
                                result.envelope,
                                finalized_operation_ids=finalized_operation_ids,
                            )
                        elif result.envelope.operation_type == "DEVELOPMENT_BOUNTY_RESERVE":
                            self.ledger.apply_consensus_development_bounty_reserve(
                                result.envelope,
                                finalized_operation_ids=finalized_operation_ids,
                            )
                        elif result.envelope.operation_type == "DEVELOPMENT_BOUNTY_RELEASE":
                            self.ledger.apply_consensus_development_bounty_release(
                                result.envelope,
                                finalized_operation_ids=finalized_operation_ids,
                            )
                        elif result.envelope.operation_type == "DEVELOPMENT_BOUNTY_EXPIRE":
                            self.ledger.apply_consensus_development_bounty_expire(
                                result.envelope,
                                finalized_operation_ids=finalized_operation_ids,
                            )
                        elif result.envelope.operation_type == "DEVELOPMENT_REWARD_RESERVE":
                            self.ledger.apply_consensus_development_reward_reserve(
                                result.envelope,
                                finalized_operation_ids=finalized_operation_ids,
                            )
                        elif result.envelope.operation_type == "DEVELOPMENT_REWARD_PAY_IMMEDIATE":
                            self.ledger.apply_consensus_development_reward_pay_immediate(
                                result.envelope,
                                finalized_operation_ids=finalized_operation_ids,
                            )
                        elif result.envelope.operation_type == "DEVELOPMENT_REWARD_PAY_MATURITY":
                            self.ledger.apply_consensus_development_reward_pay_maturity(
                                result.envelope,
                                finalized_operation_ids=finalized_operation_ids,
                            )
                        elif result.envelope.operation_type == "DEVELOPMENT_REWARD_MARK_UNCLAIMED":
                            self.ledger.apply_consensus_development_reward_mark_unclaimed(
                                result.envelope,
                                finalized_operation_ids=finalized_operation_ids,
                            )
                        elif result.envelope.operation_type == "DEVELOPMENT_REWARD_CLAIM":
                            self.ledger.apply_consensus_development_reward_claim(
                                result.envelope,
                                finalized_operation_ids=finalized_operation_ids,
                            )
                        elif result.envelope.operation_type == "DEVELOPMENT_REWARD_EXPIRE_UNCLAIMED":
                            self.ledger.apply_consensus_development_reward_expire_unclaimed(
                                result.envelope,
                                finalized_operation_ids=finalized_operation_ids,
                            )
                        elif result.envelope.operation_type == "DEVELOPMENT_REWARD_FINALIZE_COMMITMENT":
                            self.ledger.apply_consensus_development_reward_finalize_commitment(
                                result.envelope,
                                finalized_operation_ids=finalized_operation_ids,
                            )
                        elif result.envelope.operation_type == "DEVELOPMENT_REWARD_CANCEL_UNVESTED":
                            self.ledger.apply_consensus_development_reward_cancel_unvested(
                                result.envelope,
                                finalized_operation_ids=finalized_operation_ids,
                            )
                        elif result.envelope.operation_type == "DEVELOPMENT_REWARD_CORRECT":
                            self.ledger.apply_consensus_development_reward_correct(
                                result.envelope,
                                finalized_operation_ids=finalized_operation_ids,
                            )
                        elif result.envelope.operation_type == "EPOCH_TRANSITION":
                            self.ledger.apply_consensus_epoch_transition(
                                result.envelope,
                                finalized_operation_ids=finalized_operation_ids,
                            )
                        elif result.envelope.operation_type == "EPOCH_SCHEDULE_COMMIT":
                            self.ledger.apply_consensus_epoch_schedule_commit(
                                result.envelope,
                            )
                        elif result.envelope.operation_type == "EPOCH_SCHEDULE_REBASE":
                            self.ledger.apply_consensus_epoch_schedule_rebase(
                                result.envelope,
                            )
                        elif result.envelope.operation_type == "EPOCH_RESULT_MANIFEST_COMMIT":
                            self.ledger.apply_consensus_epoch_result_manifest(
                                result.envelope,
                            )
                        elif result.envelope.operation_type == "SERVICE_VERIFICATION_COMMIT":
                            self.ledger.apply_consensus_service_verification(
                                result.envelope,
                            )
                        elif result.envelope.operation_type == "REPUTATION_PROFILE_UPDATE":
                            self.ledger.apply_consensus_reputation_profile_update(
                                result.envelope,
                                finalized_operation_ids=finalized_operation_ids,
                            )
                        elif result.envelope.operation_type in VALIDATION_EVIDENCE_OPERATION_TYPES:
                            self.ledger.apply_consensus_validation_evidence(
                                result.envelope,
                                finalized_operation_ids=finalized_operation_ids,
                            )
                        elif result.envelope.operation_type == "SNAPSHOT_COMMIT":
                            self.ledger.apply_consensus_snapshot_commit(
                                result.envelope,
                            )
                        elif result.envelope.operation_type == "SESSION_FAILURE_EVIDENCE":
                            self.ledger.apply_consensus_session_failure_evidence(
                                result.envelope,
                            )
                        elif result.envelope.operation_type == "CONSENSUS_VALIDATOR_SET_UPDATE":
                            self.ledger.apply_consensus_validator_set_update(
                                result.envelope,
                            )
                        elif result.envelope.operation_type == "TREASURY_MANIFEST_BIND":
                            self.ledger.apply_consensus_treasury_manifest_bind(
                                result.envelope,
                            )
                        elif result.envelope.operation_type == "TREASURY_FUND":
                            self.ledger.apply_consensus_treasury_fund(
                                result.envelope,
                            )
                        elif result.envelope.operation_type == "PENALTY_APPLY":
                            self.ledger.apply_consensus_penalty_apply(
                                result.envelope,
                                finalized_operation_ids=finalized_operation_ids,
                            )
                        elif result.envelope.operation_type == "SESSION_ESCROW_LOCK":
                            self.ledger.apply_consensus_session_escrow_lock(
                                result.envelope,
                            )
                        elif result.envelope.operation_type == "SESSION_ESCROW_EXTEND":
                            self.ledger.apply_consensus_session_escrow_extend(
                                result.envelope,
                                finalized_operation_ids=finalized_operation_ids,
                            )
                        elif result.envelope.operation_type == "SESSION_ESCROW_RELEASE":
                            self.ledger.apply_consensus_session_escrow_release(
                                result.envelope,
                                finalized_operation_ids=finalized_operation_ids,
                            )
                        elif result.envelope.operation_type == "SESSION_CHECKPOINT_COMMIT":
                            self.ledger.apply_consensus_session_checkpoint_commit(
                                result.envelope,
                                finalized_operation_ids=finalized_operation_ids,
                            )
                        elif result.envelope.operation_type == "SESSION_SETTLEMENT_READY_COMMIT":
                            self.ledger.apply_consensus_settlement_ready_commit(
                                result.envelope,
                                finalized_operation_ids=finalized_operation_ids,
                            )
                        elif result.envelope.operation_type == "SESSION_SETTLEMENT_PROPOSE":
                            self.ledger.apply_consensus_settlement_propose(
                                result.envelope,
                                finalized_operation_ids=finalized_operation_ids,
                            )
                        elif result.envelope.operation_type == "SESSION_SETTLEMENT_ACCEPT":
                            self.ledger.apply_consensus_settlement_accept(
                                result.envelope,
                                finalized_operation_ids=finalized_operation_ids,
                            )
                        elif result.envelope.operation_type == "SESSION_SETTLEMENT_DISPUTE":
                            self.ledger.apply_consensus_settlement_dispute(
                                result.envelope,
                                finalized_operation_ids=finalized_operation_ids,
                            )
                        elif result.envelope.operation_type == "SESSION_SETTLEMENT_PARTIAL_FINALIZE":
                            self.ledger.apply_consensus_settlement_partial_finalize(
                                result.envelope,
                                finalized_operation_ids=finalized_operation_ids,
                            )
                        elif result.envelope.operation_type == "SESSION_SETTLEMENT_CORRECT":
                            self.ledger.apply_consensus_settlement_correct(
                                result.envelope,
                                finalized_operation_ids=finalized_operation_ids,
                            )
                        elif result.envelope.operation_type == "SESSION_SETTLEMENT_FINALIZE":
                            self.ledger.apply_consensus_settlement_finalize(
                                result.envelope,
                                finalized_operation_ids=finalized_operation_ids,
                            )
                        elif result.envelope.operation_type == "SESSION_FORCE_SETTLE":
                            self.ledger.apply_consensus_force_settle(
                                result.envelope,
                                finalized_operation_ids=finalized_operation_ids,
                            )
                        elif result.envelope.operation_type == "STAKE_LOCK":
                            self.ledger.apply_consensus_stake_lock(result.envelope)
                        elif result.envelope.operation_type == "UNSTAKE_REQUEST":
                            self.ledger.apply_consensus_unstake_request(result.envelope)
                        elif result.envelope.operation_type == "STAKE_RELEASE":
                            self.ledger.apply_consensus_stake_release(result.envelope)
                        elif result.envelope.operation_type == "PARTICIPANT_SUSPEND":
                            self.ledger.apply_consensus_participant_suspend(
                                result.envelope,
                                finalized_operation_ids=finalized_operation_ids,
                            )
                        elif result.envelope.operation_type == "PARTICIPANT_REINSTATE":
                            self.ledger.apply_consensus_participant_reinstate(
                                result.envelope,
                                finalized_operation_ids=finalized_operation_ids,
                            )
                        else:
                            self.ledger.record_admitted_envelope(
                                result.envelope,
                                emitted_events=result.emitted_events,
                            )
                    except Exception as error:
                        result.success = False
                        result.error = f"fatal: ledger commit failed: {error}"
                    else:
                        seen_operation_ids.add(result.envelope.operation_id)
                        # Make sequential wallet operations in one block
                        # visible to admission immediately. The pre-block
                        # finalized-operation set remains immutable, so this
                        # does not weaken same-block dependency checks.
                        self.admission.record_finalized(result.envelope.operation_id)
                        if result.envelope.sender_wallet is not None:
                            self.admission.advance_wallet_sequence(result.envelope.sender_wallet)
                        executed += 1
            if not result.success:
                rejected += 1
                # Check for fatal error — triggers atomic rollback
                if result.error and "fatal" in result.error.lower():
                    fatal_error = result.error
                    break

            events.append(result)
            changes.extend(result.state_changes)

        # A schedule becomes active only at the matching Epoch transition.
        # The finalized-operation set intentionally excludes schedules from
        # this block, preventing same-block schedule-and-activation shortcuts.
        if fatal_error is None:
            try:
                for event in events:
                    if not event.success or event.envelope is None:
                        continue
                    if event.envelope.operation_type != "EPOCH_TRANSITION":
                        continue
                    updates = self.ledger.activate_consensus_validator_set_update(
                        activation_epoch=int(event.envelope.payload["opening_epoch"]),
                        finalized_operation_ids=finalized_operation_ids,
                    )
                    event.validator_updates.extend(updates)
                    validator_updates.extend(updates)
            except (ValueError, TypeError, KeyError) as error:
                fatal_error = f"fatal: validator set activation failed: {error}"

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
                validator_updates=[],
            )

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
            validator_updates=validator_updates,
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
        *,
        finalized_operation_ids: set[str],
        preexisting_epoch_schedule_commit: bool = False,
        block_contains_epoch_schedule_commit: bool = False,
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

        coverage_error = (
            strict_operation_coverage_error(
                envelope.operation_type,
                has_custom_handler=envelope.operation_type in self._handlers,
            )
            if self._strict_operation_coverage
            else None
        )
        if coverage_error is not None:
            return ExecutionEvent(
                operation_id=envelope.operation_id,
                operation_type=envelope.operation_type,
                success=False,
                envelope=envelope,
                error=coverage_error,
            )
        version_error = strict_operation_version_error(
            envelope.operation_type,
            envelope.operation_version,
        )
        if version_error is not None:
            return ExecutionEvent(
                operation_id=envelope.operation_id,
                operation_type=envelope.operation_type,
                success=False,
                envelope=envelope,
                error=version_error,
            )
        authority_error = self._protocol_authority_error(envelope)
        if authority_error is not None:
            return ExecutionEvent(
                operation_id=envelope.operation_id,
                operation_type=envelope.operation_type,
                success=False,
                envelope=envelope,
                error=authority_error,
            )

        if (
            envelope.operation_type == "EPOCH_TRANSITION"
            and block_contains_epoch_schedule_commit
            and not preexisting_epoch_schedule_commit
        ):
            return ExecutionEvent(
                operation_id=envelope.operation_id,
                operation_type=envelope.operation_type,
                success=False,
                envelope=envelope,
                error="epoch transition cannot depend on same-block epoch schedule commit",
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
            if envelope.operation_type == "WALLET_TRANSFER" and self._strict_operation_coverage:
                validated_transfer = self.ledger.validate_consensus_wallet_transfer(envelope)
                state_changes.append(
                    StateChange(
                        entity_type="wallet",
                        entity_id=str(envelope.sender_wallet),
                        change_type="transfer",
                        after={
                            "recipient_wallet": envelope.payload["recipient_wallet"],
                            "amount_q_atoms": int(envelope.payload["amount"]),
                            "network_fee_q_atoms": int(validated_transfer["network_fee_q_atoms"]),
                        },
                    )
                )
                emitted.extend(["WalletTransferred", "NetworkFeeRecycled"])
            elif envelope.operation_type == "OPERATOR_WALLET_BIND":
                self.ledger.validate_consensus_operator_wallet_bind(envelope)
                state_changes.append(
                    StateChange(
                        entity_type="operator_wallet",
                        entity_id=str(envelope.payload["node_id"]),
                        change_type="bind",
                        after={
                            "wallet_id": envelope.payload["wallet_id"],
                            "public_key": envelope.payload["public_key"],
                        },
                    )
                )
                emitted.append("OperatorWalletBound")
            elif envelope.operation_type == "ENDPOINT_PUBLISH":
                self.ledger.validate_consensus_endpoint_publish(envelope)
                publication = envelope.payload["publication"]
                state_changes.append(
                    StateChange(
                        entity_type="endpoint_publication",
                        entity_id=str(publication["publication_id"]),
                        change_type="publish",
                        after={
                            "endpoint_id": publication["endpoint_id"],
                            "configuration_hash": publication["configuration_hash"],
                            "sequence": publication["sequence"],
                        },
                    )
                )
                emitted.append("EndpointPublished")
            elif envelope.operation_type == "SESSION_OPEN" and self._strict_operation_coverage:
                self.ledger.validate_consensus_session_open(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
                state_changes.append(
                    StateChange(
                        entity_type="session",
                        entity_id=str(envelope.payload["session_id"]),
                        change_type="open",
                        after={
                            "funding_lock_operation_id": envelope.payload["funding_lock_operation_id"],
                            "funding_state_reference": envelope.payload["funding_state_reference"],
                        },
                    )
                )
                emitted.append("SessionOpened")
            elif envelope.operation_type == "SESSION_ACCEPT" and self._strict_operation_coverage:
                self.ledger.validate_consensus_session_accept(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
                state_changes.append(
                    StateChange(
                        entity_type="session",
                        entity_id=str(envelope.payload["session_id"]),
                        change_type="accept",
                        after={
                            "session_open_operation_id": envelope.payload["session_open_operation_id"],
                            "accepted_by": envelope.payload["accepted_by"],
                        },
                    )
                )
                emitted.append("SessionAccepted")
            elif envelope.operation_type == "REWARD_MINT":
                self.ledger.validate_consensus_reward_mint(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
                state_changes.append(
                    StateChange(
                        entity_type="wallet",
                        entity_id=str(envelope.payload["recipient_wallet"]),
                        change_type="credit",
                        after={"amount_q_atoms": int(envelope.payload["amount"])},
                    )
                )
                emitted.append("RewardMinted")
            elif envelope.operation_type == "DEVELOPMENT_REWARD_CALCULATE":
                self.ledger.validate_consensus_development_reward_calculate(envelope)
                state_changes.append(
                    StateChange(
                        entity_type="development_reward_calculation",
                        entity_id=str(envelope.payload["commitment_id"]),
                        change_type="commit",
                        after={
                            "epoch": int(envelope.payload["epoch"]),
                            "calculation_root": envelope.payload["calculation_root"],
                        },
                    )
                )
                emitted.append("DevelopmentRewardCalculationCommitted")
            elif envelope.operation_type == "DEVELOPMENT_POOL_ALLOCATE":
                self.ledger.validate_consensus_development_pool_allocate(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
                state_changes.append(
                    StateChange(
                        entity_type="development_pool",
                        entity_id=str(envelope.payload["pool_allocation"]["allocation_id"]),
                        change_type="allocate",
                        after={
                            "pool_id": envelope.payload["pool_allocation"]["pool_id"],
                            "epoch": int(envelope.payload["pool_allocation"]["epoch"]),
                            "allocated_q_atoms": int(envelope.payload["pool_allocation"]["allocated_q_atoms"]),
                            "remaining_q_atoms": int(envelope.payload["pool_allocation"]["remaining_q_atoms"]),
                        },
                    )
                )
                emitted.append("DevelopmentPoolAllocated")
            elif envelope.operation_type == "DEVELOPMENT_POOL_CARRYOVER":
                validation = self.ledger.validate_consensus_development_pool_carryover(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
                state_changes.append(
                    StateChange(
                        entity_type="development_pool",
                        entity_id=validation["carryover"].carryover_id,
                        change_type="carryover",
                        after={
                            "source_epoch": validation["carryover"].source_epoch,
                            "target_epoch": validation["carryover"].target_epoch,
                            "carried_q_atoms": validation["carryover"].carried_q_atoms,
                            "returned_to_emission_reserve_q_atoms": validation[
                                "carryover"
                            ].returned_to_emission_reserve_q_atoms,
                        },
                    )
                )
                emitted.append("DevelopmentPoolCarriedOver")
            elif envelope.operation_type == "DEVELOPMENT_BOUNTY_CREATE":
                validation = self.ledger.validate_consensus_development_bounty_create(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
                state_changes.append(
                    StateChange(
                        entity_type="development_bounty",
                        entity_id=validation["bounty"].bounty_id,
                        change_type="create",
                        after={
                            "state": "OPEN",
                            "reserved_budget_q_atoms": validation["bounty"].reserved_budget_q_atoms,
                        },
                    )
                )
                emitted.append("DevelopmentBountyCreated")
            elif envelope.operation_type == "DEVELOPMENT_BOUNTY_RESERVE":
                validation = self.ledger.validate_consensus_development_bounty_reserve(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
                state_changes.append(
                    StateChange(
                        entity_type="development_bounty",
                        entity_id=validation["reservation"].bounty_id,
                        change_type="reserve",
                        after={
                            "amount_q_atoms": validation["reservation"].amount_q_atoms,
                            "state": validation["bounty_state"].state,
                        },
                    )
                )
                emitted.append("DevelopmentBountyReserved")
            elif envelope.operation_type == "DEVELOPMENT_BOUNTY_RELEASE":
                validation = self.ledger.validate_consensus_development_bounty_release(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
                state_changes.append(
                    StateChange(
                        entity_type="development_bounty",
                        entity_id=validation["release"].bounty_id,
                        change_type="release",
                        after={
                            "released_q_atoms": validation["release"].released_q_atoms,
                            "returned_q_atoms": validation["release"].returned_q_atoms,
                            "state": validation["bounty_state"].state,
                        },
                    )
                )
                emitted.append("DevelopmentBountyReleased")
            elif envelope.operation_type == "DEVELOPMENT_BOUNTY_EXPIRE":
                validation = self.ledger.validate_consensus_development_bounty_expire(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
                state_changes.append(
                    StateChange(
                        entity_type="development_bounty",
                        entity_id=validation["expiry"].bounty_id,
                        change_type="expire",
                        after={
                            "returned_q_atoms": validation["expiry"].returned_q_atoms,
                            "state": validation["bounty_state"].state,
                        },
                    )
                )
                emitted.append("DevelopmentBountyExpired")
            elif envelope.operation_type == "DEVELOPMENT_REWARD_RESERVE":
                self.ledger.validate_consensus_development_reward_reserve(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
                state_changes.append(
                    StateChange(
                        entity_type="development_reward",
                        entity_id=str(envelope.payload["reward_reserve"]["reserve_id"]),
                        change_type="reserve",
                        after={
                            "reward_id": envelope.payload["reward_reserve"]["reward_id"],
                            "pool_allocation_id": envelope.payload["reward_reserve"]["pool_allocation_id"],
                            "reserved_q_atoms": int(envelope.payload["reward_reserve"]["reserved_q_atoms"]),
                            "remaining_q_atoms": int(envelope.payload["reward_reserve"]["remaining_q_atoms"]),
                        },
                    )
                )
                emitted.append("DevelopmentRewardReserved")
            elif envelope.operation_type == "DEVELOPMENT_REWARD_PAY_IMMEDIATE":
                payment_validation = self.ledger.validate_consensus_development_reward_pay_immediate(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
                state_changes.append(
                    StateChange(
                        entity_type="development_reward_payment",
                        entity_id=str(payment_validation["payment_record"].payment_id),
                        change_type="pay",
                        after={
                            "reward_id": envelope.payload["reward_id"],
                            "contributor_id": envelope.payload["contributor_id"],
                            "recipient_wallet": envelope.payload["recipient_wallet"],
                            "payment_stage": envelope.payload["payment_stage"],
                            "amount_q_atoms": int(envelope.payload["amount_q_atoms"]),
                            "reserve_remaining_q_atoms": int(
                                payment_validation["payment_record"].reserve_remaining_q_atoms
                            ),
                            "pool_remaining_q_atoms": int(payment_validation["payment_record"].pool_remaining_q_atoms),
                        },
                    )
                )
                emitted.append("DevelopmentRewardPaidImmediate")
            elif envelope.operation_type == "DEVELOPMENT_REWARD_PAY_MATURITY":
                payment_validation = self.ledger.validate_consensus_development_reward_pay_maturity(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
                state_changes.append(
                    StateChange(
                        entity_type="development_reward_payment",
                        entity_id=str(payment_validation["payment_record"].payment_id),
                        change_type="pay_maturity",
                        after={
                            "reward_id": envelope.payload["reward_id"],
                            "contributor_id": envelope.payload["contributor_id"],
                            "recipient_wallet": envelope.payload["recipient_wallet"],
                            "payment_stage": envelope.payload["payment_stage"],
                            "amount_q_atoms": int(envelope.payload["amount_q_atoms"]),
                            "reserve_remaining_q_atoms": int(
                                payment_validation["payment_record"].reserve_remaining_q_atoms
                            ),
                            "pool_remaining_q_atoms": int(payment_validation["payment_record"].pool_remaining_q_atoms),
                        },
                    )
                )
                emitted.append("DevelopmentRewardPaidMaturity")
            elif envelope.operation_type == "DEVELOPMENT_REWARD_MARK_UNCLAIMED":
                unclaimed_validation = self.ledger.validate_consensus_development_reward_mark_unclaimed(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
                state_changes.append(
                    StateChange(
                        entity_type="development_reward_unclaimed",
                        entity_id=str(unclaimed_validation["unclaimed_record"].unclaimed_id),
                        change_type="mark_unclaimed",
                        after={
                            "reward_id": envelope.payload["reward_id"],
                            "contributor_id": envelope.payload["contributor_id"],
                            "payment_stage": envelope.payload["payment_stage"],
                            "amount_q_atoms": int(envelope.payload["amount_q_atoms"]),
                            "claim_expiration_epoch": int(
                                unclaimed_validation["unclaimed_record"].claim_expiration_epoch
                            ),
                        },
                    )
                )
                emitted.append("DevelopmentRewardMarkedUnclaimed")
            elif envelope.operation_type == "DEVELOPMENT_REWARD_CLAIM":
                claim_validation = self.ledger.validate_consensus_development_reward_claim(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
                state_changes.append(
                    StateChange(
                        entity_type="development_reward_claim",
                        entity_id=str(claim_validation["claim_record"].claim_id),
                        change_type="claim",
                        after={
                            "unclaimed_id": envelope.payload["unclaimed_id"],
                            "contributor_id": envelope.payload["contributor_id"],
                            "recipient_wallet": envelope.payload["recipient_wallet"],
                            "payment_stage": envelope.payload["payment_stage"],
                            "amount_q_atoms": int(envelope.payload["amount_q_atoms"]),
                            "claim_epoch": int(envelope.payload["claim_epoch"]),
                            "reserve_remaining_q_atoms": int(
                                claim_validation["claim_record"].reserve_remaining_q_atoms
                            ),
                        },
                    )
                )
                emitted.append("DevelopmentRewardClaimed")
            elif envelope.operation_type == "DEVELOPMENT_REWARD_EXPIRE_UNCLAIMED":
                expiry_validation = self.ledger.validate_consensus_development_reward_expire_unclaimed(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
                state_changes.append(
                    StateChange(
                        entity_type="development_reward_expiry",
                        entity_id=str(expiry_validation["expiry_record"].expiry_id),
                        change_type="return_to_carryover",
                        after={
                            "unclaimed_id": envelope.payload["unclaimed_id"],
                            "reward_id": envelope.payload["reward_id"],
                            "payment_stage": envelope.payload["payment_stage"],
                            "amount_q_atoms": int(envelope.payload["amount_q_atoms"]),
                            "expiry_epoch": int(envelope.payload["expiry_epoch"]),
                            "pool_remaining_q_atoms": int(expiry_validation["expiry_record"].pool_remaining_q_atoms),
                        },
                    )
                )
                emitted.append("DevelopmentRewardExpiredReturned")
            elif envelope.operation_type == "DEVELOPMENT_REWARD_FINALIZE_COMMITMENT":
                finalized_validation = self.ledger.validate_consensus_development_reward_finalize_commitment(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
                state_changes.append(
                    StateChange(
                        entity_type="development_reward_finalized_commitment",
                        entity_id=str(finalized_validation["finalized_record"].finalized_commitment_id),
                        change_type="finalize",
                        after={
                            "calculation_root": envelope.payload["calculation_root"],
                            "finalization_epoch": int(envelope.payload["finalization_epoch"]),
                            "source_operation_root": envelope.payload["source_operation_root"],
                            "reserve_root": envelope.payload["reserve_root"],
                            "payment_root": envelope.payload["payment_root"],
                            "unclaimed_root": envelope.payload["unclaimed_root"],
                            "claim_root": envelope.payload["claim_root"],
                            "expiry_root": envelope.payload["expiry_root"],
                        },
                    )
                )
                emitted.append("DevelopmentRewardCommitmentFinalized")
            elif envelope.operation_type == "DEVELOPMENT_REWARD_CANCEL_UNVESTED":
                validation = self.ledger.validate_consensus_development_reward_cancel_unvested(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
                state_changes.append(
                    StateChange(
                        entity_type="development_reward_adjustment",
                        entity_id=validation["cancellation"].cancellation_id,
                        change_type="cancel_unvested",
                        after={
                            "reward_id": validation["cancellation"].reward_id,
                            "cancelled_q_atoms": validation["cancellation"].cancelled_q_atoms,
                            "returned_to_pool_q_atoms": validation["cancellation"].returned_to_pool_q_atoms,
                        },
                    )
                )
                emitted.append("DevelopmentRewardUnvestedCancelled")
            elif envelope.operation_type == "DEVELOPMENT_REWARD_CORRECT":
                validation = self.ledger.validate_consensus_development_reward_correct(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
                state_changes.append(
                    StateChange(
                        entity_type="development_reward_adjustment",
                        entity_id=validation["correction"].correction_id,
                        change_type="correct",
                        after={
                            "reward_id": validation["correction"].reward_id,
                            "correction_delta_q_atoms": validation["correction"].correction_delta_q_atoms,
                            "returned_to_pool_q_atoms": validation["correction"].returned_to_pool_q_atoms,
                            "additional_reserved_q_atoms": validation["correction"].additional_reserved_q_atoms,
                        },
                    )
                )
                emitted.append("DevelopmentRewardCorrected")
            elif envelope.operation_type == "EPOCH_TRANSITION":
                self.ledger.validate_consensus_epoch_transition(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
                state_changes.append(
                    StateChange(
                        entity_type="epoch",
                        entity_id=str(envelope.payload["closing_epoch"]),
                        change_type="update",
                        after={
                            "opening_epoch": int(envelope.payload["opening_epoch"]),
                            "reward_calculation_root": envelope.payload["reward_calculation_root"],
                        },
                    )
                )
                emitted.append("EpochTransition")
            elif envelope.operation_type == "EPOCH_SCHEDULE_COMMIT":
                validation = self.ledger.validate_consensus_epoch_schedule_commit(envelope)
                schedule = validation["epoch_schedule"]
                state_changes.append(
                    StateChange(
                        entity_type="epoch_schedule",
                        entity_id=schedule.schedule_hash,
                        change_type="commit",
                        after=schedule.model_dump(mode="json"),
                    )
                )
                emitted.append("EpochScheduleCommitted")
            elif envelope.operation_type == "EPOCH_SCHEDULE_REBASE":
                validation = self.ledger.validate_consensus_epoch_schedule_rebase(envelope)
                rebase = validation["rebase"]
                state_changes.append(
                    StateChange(
                        entity_type="epoch_schedule_rebase",
                        entity_id=rebase.rebase_hash,
                        change_type="commit",
                        after=rebase.model_dump(mode="json"),
                    )
                )
                emitted.append("EpochScheduleRebased")
            elif envelope.operation_type == "EPOCH_RESULT_MANIFEST_COMMIT":
                validation = self.ledger.validate_consensus_epoch_result_manifest(envelope)
                manifest = validation["manifest"]
                state_changes.append(
                    StateChange(
                        entity_type="epoch_result_manifest",
                        entity_id=manifest.manifest_hash,
                        change_type="commit",
                        after={
                            "epoch_number": manifest.epoch_number,
                            "task_result_root": manifest.task_result_root,
                            "reward_calculation_root": manifest.reward_calculation_root,
                        },
                    )
                )
                emitted.append("EpochResultManifestCommitted")
            elif envelope.operation_type == "SERVICE_VERIFICATION_COMMIT":
                self.ledger.validate_consensus_service_verification(envelope)
                state_changes.append(
                    StateChange(
                        entity_type="service_verification",
                        entity_id=str(envelope.payload["verification_report_id"]),
                        change_type="create",
                        after={
                            "service_id": envelope.payload["service_id"],
                            "verification_epoch": int(envelope.payload["verification_epoch"]),
                        },
                    )
                )
                emitted.append("ServiceVerificationCommitted")
            elif envelope.operation_type == "REPUTATION_PROFILE_UPDATE":
                self.ledger.validate_consensus_reputation_profile_update(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
                state_changes.append(
                    StateChange(
                        entity_type="reputation_profile",
                        entity_id=str(envelope.payload["object_id"]),
                        change_type="update",
                        after={
                            "new_profile_hash": envelope.payload["new_profile_hash"],
                            "effective_epoch": int(envelope.payload["effective_epoch"]),
                        },
                    )
                )
                emitted.append("ReputationProfileUpdated")
            elif envelope.operation_type in VALIDATION_EVIDENCE_OPERATION_TYPES:
                self.ledger.validate_consensus_validation_evidence(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
                payload = envelope.payload
                entity_id = str(
                    payload.get("report_id")
                    or payload.get("receipt_id")
                    or payload.get("failure_id")
                    or envelope.operation_id
                )
                change_type = {
                    "VALIDATION_REPORT_COMMIT": "commit",
                    "VALIDATION_REPORT_STORAGE_RECEIPT": "receipt",
                    "VALIDATION_REPORT_STORAGE_FAILURE": "failure",
                    "VALIDATION_REPORT_AVAILABILITY_COMMIT": "availability",
                    "VALIDATION_REPORT_CUSTODY_RELEASE": "release",
                }[envelope.operation_type]
                emitted_event = {
                    "VALIDATION_REPORT_COMMIT": "ValidationReportCommitted",
                    "VALIDATION_REPORT_STORAGE_RECEIPT": "ValidationReportStorageReceiptCommitted",
                    "VALIDATION_REPORT_STORAGE_FAILURE": "ValidationReportStorageFailureCommitted",
                    "VALIDATION_REPORT_AVAILABILITY_COMMIT": "ValidationReportAvailabilityCommitted",
                    "VALIDATION_REPORT_CUSTODY_RELEASE": "ValidationReportCustodyReleased",
                }[envelope.operation_type]
                state_changes.append(
                    StateChange(
                        entity_type="validation_report",
                        entity_id=entity_id,
                        change_type=change_type,
                        after={
                            "report_hash": payload.get("report_hash"),
                            "endpoint_id": payload.get("endpoint_id"),
                            "endpoint_configuration_hash": payload.get("endpoint_configuration_hash"),
                        },
                    )
                )
                emitted.append(emitted_event)
            elif envelope.operation_type == "SNAPSHOT_COMMIT":
                self.ledger.validate_consensus_snapshot_commit(envelope)
                state_changes.append(
                    StateChange(
                        entity_type="snapshot",
                        entity_id=str(envelope.payload["snapshot_id"]),
                        change_type="create",
                        after={
                            "block_height": int(envelope.payload["block_height"]),
                            "application_state_hash": envelope.payload["application_state_hash"],
                        },
                    )
                )
                emitted.append("SnapshotCommitted")
            elif envelope.operation_type == "SESSION_FAILURE_EVIDENCE":
                self.ledger.validate_consensus_session_failure_evidence(envelope)
                state_changes.append(
                    StateChange(
                        entity_type="session_failure_evidence",
                        entity_id=str(envelope.payload["session_id"]),
                        change_type="commit",
                        after={
                            "failure_class": envelope.payload["failure_class"],
                            "failure_evidence_root": envelope.payload["failure_evidence_root"],
                        },
                    )
                )
                emitted.append("SessionFailureEvidenceCommitted")
            elif envelope.operation_type == "CONSENSUS_VALIDATOR_SET_UPDATE":
                self.ledger.validate_consensus_validator_set_update(envelope)
                state_changes.append(
                    StateChange(
                        entity_type="validator_set",
                        entity_id=str(envelope.payload["activation_epoch"]),
                        change_type="schedule",
                        after={
                            "activation_epoch": int(envelope.payload["activation_epoch"]),
                            "validator_set_hash": envelope.payload["validator_set_hash"],
                        },
                    )
                )
                emitted.append("ValidatorSetUpdateScheduled")
            elif envelope.operation_type == "TREASURY_MANIFEST_BIND":
                self.ledger.validate_consensus_treasury_manifest_bind(envelope)
                state_changes.append(
                    StateChange(
                        entity_type="faucet_treasury",
                        entity_id=str(envelope.payload["treasury_manifest"]["treasury_id"]),
                        change_type="bind",
                        after={"manifest_hash": envelope.payload["treasury_manifest"]["manifest_hash"]},
                    )
                )
                emitted.append("FaucetTreasuryManifestBound")
            elif envelope.operation_type == "TREASURY_FUND":
                self.ledger.validate_consensus_treasury_fund(envelope)
                state_changes.append(
                    StateChange(
                        entity_type="wallet",
                        entity_id=str(envelope.payload["treasury_wallet_id"]),
                        change_type="credit",
                        after={"amount_q_atoms": int(envelope.payload["amount"])},
                    )
                )
                emitted.append("FaucetTreasuryFunded")
            elif envelope.operation_type == "PENALTY_APPLY":
                self.ledger.validate_consensus_penalty_apply(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
                target = str(envelope.payload["target_wallet_or_lock"])
                target_is_lock = target.startswith("lock:")
                state_changes.append(
                    StateChange(
                        entity_type="stake" if target_is_lock else "wallet",
                        entity_id=target.removeprefix("lock:") if target_is_lock else target,
                        change_type="slash" if target_is_lock else "debit",
                        after={"amount_q_atoms": int(envelope.payload["amount"])},
                    )
                )
                emitted.append("PenaltyApplied")
                if target_is_lock:
                    emitted.append("StakeSlashed")
            elif envelope.operation_type == "SESSION_ESCROW_LOCK":
                self.ledger.validate_consensus_session_escrow_lock(envelope)
                state_changes.append(
                    StateChange(
                        entity_type="session_funding",
                        entity_id=str(envelope.payload["session_id"]),
                        change_type="lock",
                        after={
                            "total_locked_amount_q_atoms": int(envelope.payload["total_locked_amount_q_atoms"]),
                            "funding_state_hash": envelope.payload["funding_state_hash"],
                        },
                    )
                )
                emitted.append("SessionEscrowLocked")
            elif envelope.operation_type == "SESSION_ESCROW_EXTEND":
                self.ledger.validate_consensus_session_escrow_extend(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
                state_changes.append(
                    StateChange(
                        entity_type="session_funding",
                        entity_id=str(envelope.payload["session_id"]),
                        change_type="extend",
                        after={
                            "funding_state_hash": envelope.payload["funding"]["funding_state_hash"],
                            "added_q_atoms": int(envelope.payload["added_endpoint_payment_reserve_q_atoms"])
                            + int(envelope.payload["added_network_fee_reserve_q_atoms"]),
                        },
                    )
                )
                emitted.append("SessionEscrowExtended")
            elif envelope.operation_type == "SESSION_ESCROW_RELEASE":
                self.ledger.validate_consensus_session_escrow_release(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
                state_changes.append(
                    StateChange(
                        entity_type="session_funding",
                        entity_id=str(envelope.payload["session_id"]),
                        change_type="release",
                        after={
                            "funding_state_hash": envelope.payload["funding"]["funding_state_hash"],
                            "release_q_atoms": int(envelope.payload["release_payment_q_atoms"])
                            + int(envelope.payload["release_fee_q_atoms"]),
                        },
                    )
                )
                emitted.extend(["SessionEscrowReleased", "SessionRefunded"])
            elif envelope.operation_type == "SESSION_CHECKPOINT_COMMIT":
                self.ledger.validate_consensus_session_checkpoint_commit(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
                state_changes.append(
                    StateChange(
                        entity_type="session_checkpoint",
                        entity_id=str(envelope.payload["checkpoint"]["checkpoint_id"]),
                        change_type="commit",
                        after={
                            "session_id": envelope.payload["session_id"],
                            "checkpoint_sequence": int(envelope.payload["checkpoint"]["checkpoint_sequence"]),
                            "checkpoint_hash": envelope.payload["checkpoint"]["checkpoint_hash"],
                        },
                    )
                )
                emitted.append("SessionCheckpointCommitted")
            elif envelope.operation_type == "SESSION_SETTLEMENT_READY_COMMIT":
                self.ledger.validate_consensus_settlement_ready_commit(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
                state_changes.append(
                    StateChange(
                        entity_type="settlement",
                        entity_id=str(envelope.payload["ready"]["settlement_input_root"]),
                        change_type="ready_commit",
                        after={
                            "session_id": envelope.payload["session_id"],
                            "commitment_hash": envelope.payload["ready"]["commitment_hash"],
                        },
                    )
                )
                emitted.append("SessionSettlementReadyCommitted")
            elif envelope.operation_type == "SESSION_SETTLEMENT_PROPOSE":
                self.ledger.validate_consensus_settlement_propose(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
                state_changes.append(
                    StateChange(
                        entity_type="settlement",
                        entity_id=str(envelope.payload["proposal"]["settlement_id"]),
                        change_type="propose",
                        after={
                            "settlement_input_root": envelope.payload["proposal"]["settlement_input_root"],
                            "funding_state_reference": envelope.payload["funding_state_reference"],
                        },
                    )
                )
                emitted.append("SessionSettlementProposed")
            elif envelope.operation_type == "SESSION_SETTLEMENT_ACCEPT":
                self.ledger.validate_consensus_settlement_accept(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
                state_changes.append(
                    StateChange(
                        entity_type="settlement",
                        entity_id=str(envelope.payload["acceptance"]["settlement_id"]),
                        change_type="accept",
                        after={
                            "acceptance_hash": envelope.payload["acceptance"]["acceptance_hash"],
                        },
                    )
                )
                emitted.append("SessionSettlementAccepted")
            elif envelope.operation_type == "SESSION_SETTLEMENT_DISPUTE":
                self.ledger.validate_consensus_settlement_dispute(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
                state_changes.append(
                    StateChange(
                        entity_type="settlement_dispute",
                        entity_id=str(envelope.payload["dispute"]["dispute_id"]),
                        change_type="open",
                        after={
                            "settlement_id": envelope.payload["dispute"]["settlement_id"],
                            "disputed_amount_q_atoms": int(envelope.payload["dispute"]["disputed_amount_q_atoms"]),
                            "dispute_hash": envelope.payload["dispute"]["dispute_hash"],
                        },
                    )
                )
                emitted.append("SessionSettlementDisputed")
            elif envelope.operation_type == "SESSION_SETTLEMENT_PARTIAL_FINALIZE":
                self.ledger.validate_consensus_settlement_partial_finalize(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
                state_changes.append(
                    StateChange(
                        entity_type="session_funding",
                        entity_id=str(envelope.payload["transition"]["session_id"]),
                        change_type="partial_finalize",
                        after={
                            "transition_hash": envelope.payload["transition"]["transition_hash"],
                            "credit_endpoint_q_atoms": int(envelope.payload["transition"]["credit_endpoint_q_atoms"]),
                            "credit_consumer_q_atoms": int(envelope.payload["transition"]["credit_consumer_q_atoms"]),
                            "retain_dispute_reserve_q_atoms": int(
                                envelope.payload["transition"]["retain_dispute_reserve_q_atoms"]
                            ),
                        },
                    )
                )
                emitted.append("SessionSettlementPartiallyFinalized")
            elif envelope.operation_type == "SESSION_SETTLEMENT_CORRECT":
                self.ledger.validate_consensus_settlement_correct(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
                state_changes.append(
                    StateChange(
                        entity_type="settlement_correction",
                        entity_id=str(envelope.payload["correction"]["correction_id"]),
                        change_type="resolve",
                        after={
                            "settlement_id": envelope.payload["correction"]["settlement_id"],
                            "correction_hash": envelope.payload["correction"]["correction_hash"],
                            "endpoint_payment_delta_q_atoms": int(
                                envelope.payload["correction"]["endpoint_payment_delta_q_atoms"]
                            ),
                            "consumer_refund_delta_q_atoms": int(
                                envelope.payload["correction"]["consumer_refund_delta_q_atoms"]
                            ),
                        },
                    )
                )
                emitted.extend(["SessionSettlementCorrected", "SessionSettlementDisputeResolved"])
            elif envelope.operation_type == "SESSION_SETTLEMENT_FINALIZE":
                self.ledger.validate_consensus_settlement_finalize(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
                state_changes.append(
                    StateChange(
                        entity_type="session_funding",
                        entity_id=str(envelope.payload["transition"]["session_id"]),
                        change_type="finalize",
                        after={
                            "transition_hash": envelope.payload["transition"]["transition_hash"],
                            "credit_endpoint_q_atoms": int(envelope.payload["transition"]["credit_endpoint_q_atoms"]),
                            "credit_consumer_q_atoms": int(envelope.payload["transition"]["credit_consumer_q_atoms"]),
                        },
                    )
                )
                emitted.append("SessionSettlementFinalized")
            elif envelope.operation_type == "SESSION_FORCE_SETTLE":
                self.ledger.validate_consensus_force_settle(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
                state_changes.append(
                    StateChange(
                        entity_type="session_funding",
                        entity_id=str(envelope.payload["session_id"]),
                        change_type="refund",
                        after={
                            "failure_class": envelope.payload["failure_class"],
                            "credit_consumer_q_atoms": int(envelope.payload["transition"]["credit_consumer_q_atoms"]),
                        },
                    )
                )
                emitted.extend(["SessionForcedSettlementAuthorized", "SessionRefunded"])
            elif envelope.operation_type == "STAKE_LOCK":
                self.ledger.validate_consensus_stake_lock(envelope)
                state_changes.append(
                    StateChange(
                        entity_type="stake",
                        entity_id=str(envelope.payload["stake_id"]),
                        change_type="lock",
                        after={"amount_q_atoms": int(envelope.payload["amount"])},
                    )
                )
                emitted.append("StakeLocked")
            elif envelope.operation_type == "UNSTAKE_REQUEST":
                self.ledger.validate_consensus_unstake_request(envelope)
                state_changes.append(
                    StateChange(
                        entity_type="stake",
                        entity_id=str(envelope.payload["stake_id"]),
                        change_type="unbonding",
                        after={"request_epoch": int(envelope.payload["request_epoch"])},
                    )
                )
                emitted.append("StakeUnbondingStarted")
            elif envelope.operation_type == "STAKE_RELEASE":
                self.ledger.validate_consensus_stake_release(envelope)
                state_changes.append(
                    StateChange(
                        entity_type="stake",
                        entity_id=str(envelope.payload["stake_id"]),
                        change_type="release",
                        after={"current_epoch": int(envelope.payload["current_epoch"])},
                    )
                )
                emitted.append("StakeReleased")
            elif envelope.operation_type == "PARTICIPANT_SUSPEND":
                self.ledger.validate_consensus_participant_suspend(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
                state_changes.append(
                    StateChange(
                        entity_type="participant",
                        entity_id=str(envelope.payload["target_id"]),
                        change_type="suspend",
                        after={"minimum_recovery_epoch": int(envelope.payload["minimum_recovery_epoch"])},
                    )
                )
                emitted.append("ParticipantSuspended")
            elif envelope.operation_type == "PARTICIPANT_REINSTATE":
                self.ledger.validate_consensus_participant_reinstate(
                    envelope,
                    finalized_operation_ids=finalized_operation_ids,
                )
                state_changes.append(
                    StateChange(
                        entity_type="participant",
                        entity_id=str(envelope.payload["target_id"]),
                        change_type="reinstate",
                        after={"current_epoch": int(envelope.payload["current_epoch"])},
                    )
                )
                emitted.append("ParticipantReinstated")
            else:
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

    def _protocol_authority_error(
        self,
        envelope: LedgerOperationEnvelope,
    ) -> str | None:
        if envelope.operation_type not in {
            "EPOCH_TRANSITION",
            "EPOCH_SCHEDULE_COMMIT",
            "EPOCH_SCHEDULE_REBASE",
            "EPOCH_RESULT_MANIFEST_COMMIT",
        }:
            return None
        if self._protocol_authority_policy is None:
            return None
        try:
            if envelope.operation_type == "EPOCH_TRANSITION":
                self._protocol_authority_policy.verify_epoch_transition(envelope)
            elif envelope.operation_type == "EPOCH_RESULT_MANIFEST_COMMIT":
                self._protocol_authority_policy.verify_epoch_result_manifest_commit(envelope)
            elif envelope.operation_type == "EPOCH_SCHEDULE_REBASE":
                self._protocol_authority_policy.verify_epoch_schedule_rebase(envelope)
            else:
                self._protocol_authority_policy.verify_epoch_schedule_commit(envelope)
        except ValueError as error:
            return str(error)
        return None

    def _compute_state_root(self) -> str:
        """Compute deterministic hash of current ledger state."""
        return compute_execution_state_root(self.ledger)

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
            "consensus_state": self.ledger.snapshot_consensus_state(),
        }

    def _restore_state(self, state: dict) -> None:
        """Restore ledger state from captured snapshot."""
        settlement = state.get("settlement_state", {})
        self.ledger.restore(
            operations=state.get("operations", []),
            wallet_sequences=state.get("wallet_sequences", {}),
            wallet_q_atom_balances=settlement.get("wallet_q_atom_balances"),
            recyclable_q_atoms=int(settlement.get("recyclable_q_atoms", 0)),
            burned_q_atoms=int(settlement.get("burned_q_atoms", 0)),
            stake_records=settlement.get("stake_records"),
            participant_suspensions=settlement.get("participant_suspensions"),
            session_funding_accounts=settlement.get("session_funding_accounts"),
            settlement_ready_commits=settlement.get("settlement_ready_commits"),
            settlement_proposals=settlement.get("settlement_proposals"),
            settlement_acceptances=settlement.get("settlement_acceptances"),
            session_checkpoints=settlement.get("session_checkpoints"),
            settlement_disputes=settlement.get("settlement_disputes"),
            settlement_corrections=settlement.get("settlement_corrections"),
            settlement_transition_hashes=settlement.get("settlement_transition_hashes"),
            development_pool_allocations=settlement.get("development_pool_allocations"),
            development_pool_carryovers=settlement.get("development_pool_carryovers"),
            development_bounty_states=settlement.get("development_bounty_states"),
            development_reward_reserves=settlement.get("development_reward_reserves"),
            development_reward_payment_records=settlement.get("development_reward_payment_records"),
            development_reward_unclaimed_records=settlement.get("development_reward_unclaimed_records"),
            development_reward_claim_records=settlement.get("development_reward_claim_records"),
            development_reward_expiry_records=settlement.get("development_reward_expiry_records"),
            development_reward_finalized_commitments=settlement.get("development_reward_finalized_commitments"),
            development_reward_adjustment_snapshots=settlement.get("development_reward_adjustment_snapshots"),
            development_reward_cancellations=settlement.get("development_reward_cancellations"),
            development_reward_corrections=settlement.get("development_reward_corrections"),
            consensus_state=state.get("consensus_state"),
        )
        self._gas_used = 0
        self._state_changes.clear()
        self._execution_events.clear()
