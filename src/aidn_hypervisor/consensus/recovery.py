"""Fail-closed reconciliation of local Hypervisor state to an ABCI snapshot."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from aidn_hypervisor.consensus.abci import AIDNABCIApplication
from aidn_hypervisor.consensus.state_store import ABCIStateStore
from aidn_hypervisor.ledger.service import LedgerOperationService
from aidn_hypervisor.persistence import FileStateStore
from aidn_hypervisor.state import HypervisorStateSnapshot


class ValidatorRecoveryError(RuntimeError):
    """The local state cannot be reconciled without an operator decision."""


@dataclass(frozen=True)
class ValidatorRecoveryPlan:
    """Verified local-state replacement plan; no files are changed on build."""

    source_snapshot_id: str
    source_height: int
    source_app_hash: str
    discarded_operation_ids: tuple[str, ...]
    changed_fields: tuple[str, ...]
    projected_state: HypervisorStateSnapshot


_CONSENSUS_PROJECTION_FIELDS = (
    "ledger_operations",
    "wallet_operation_sequences",
    "wallet_q_atom_balances",
    "recyclable_q_atoms",
    "burned_q_atoms",
    "stake_records",
    "participant_suspensions",
    "session_funding_accounts",
    "settlement_proposals",
    "settlement_acceptances",
    "session_checkpoints",
    "settlement_disputes",
    "settlement_corrections",
    "settlement_transition_hashes",
)


def build_validator_recovery_plan(
    *,
    hypervisor_state_path: Path | str,
    abci_state_path: Path | str,
    discard_operation_ids: list[str] | tuple[str, ...],
) -> ValidatorRecoveryPlan:
    """Build a verified replacement from the current durable ABCI snapshot.

    The function changes no files. Any local Ledger operation absent from the
    canonical snapshot must be named explicitly by the operator; missing or
    conflicting canonical operations fail closed.
    """
    hypervisor_path = Path(hypervisor_state_path)
    hypervisor = FileStateStore(hypervisor_path).load()
    abci_store = ABCIStateStore(abci_state_path)
    snapshot = abci_store.load_current()
    if snapshot is None:
        raise ValidatorRecoveryError("ABCI state has no current snapshot")

    canonical_operations = list(snapshot.get("ledger_operations", []))
    local_operations = [item.model_dump(mode="json") for item in hypervisor.ledger_operations]
    canonical_ids = _operation_ids(canonical_operations)
    local_ids = _operation_ids(local_operations)
    missing_ids = canonical_ids - local_ids
    extra_ids = local_ids - canonical_ids
    requested_discard = {str(item).strip() for item in discard_operation_ids if str(item).strip()}

    if missing_ids:
        raise ValidatorRecoveryError(
            "local Hypervisor state is missing canonical operations: "
            + ", ".join(sorted(missing_ids))
        )
    if requested_discard != extra_ids:
        raise ValidatorRecoveryError(
            "explicit discard list must exactly match local operations absent from the ABCI snapshot"
        )
    if _filter_operations(local_operations, requested_discard) != canonical_operations:
        raise ValidatorRecoveryError(
            "local and ABCI operation histories conflict beyond the explicitly discarded operations"
        )

    settlement_state = snapshot.get("settlement_state")
    if not isinstance(settlement_state, dict):
        raise ValidatorRecoveryError("ABCI snapshot settlement state is invalid")
    projected_data = hypervisor.model_dump(mode="json")
    projected_data.update(
        {
            "ledger_operations": canonical_operations,
            "wallet_operation_sequences": dict(snapshot.get("wallet_sequences", {})),
            "wallet_q_atom_balances": dict(settlement_state.get("wallet_q_atom_balances", {})),
            "recyclable_q_atoms": int(settlement_state.get("recyclable_q_atoms", 0)),
            "burned_q_atoms": int(settlement_state.get("burned_q_atoms", 0)),
            "stake_records": list(settlement_state.get("stake_records", [])),
            "participant_suspensions": list(settlement_state.get("participant_suspensions", [])),
            "session_funding_accounts": list(settlement_state.get("session_funding_accounts", [])),
            "settlement_proposals": list(settlement_state.get("settlement_proposals", [])),
            "settlement_acceptances": list(settlement_state.get("settlement_acceptances", [])),
            "session_checkpoints": list(settlement_state.get("session_checkpoints", [])),
            "settlement_disputes": list(settlement_state.get("settlement_disputes", [])),
            "settlement_corrections": list(settlement_state.get("settlement_corrections", [])),
            "settlement_transition_hashes": dict(
                settlement_state.get("settlement_transition_hashes", {})
            ),
        }
    )
    projected_state = HypervisorStateSnapshot.model_validate(projected_data)
    _verify_projected_app_hash(snapshot, projected_state)

    current_data = hypervisor.model_dump(mode="json")
    changed_fields = tuple(
        field_name
        for field_name in _CONSENSUS_PROJECTION_FIELDS
        if current_data.get(field_name) != projected_data.get(field_name)
    )
    snapshot_id = str(_current_snapshot_id(abci_store))
    return ValidatorRecoveryPlan(
        source_snapshot_id=snapshot_id,
        source_height=int(snapshot.get("last_block_height", 0)),
        source_app_hash=str(snapshot.get("app_hash", "")),
        discarded_operation_ids=tuple(sorted(requested_discard)),
        changed_fields=changed_fields,
        projected_state=projected_state,
    )


def apply_validator_recovery_plan(
    *,
    plan: ValidatorRecoveryPlan,
    hypervisor_state_path: Path | str,
    backup_path: Path | str | None = None,
) -> Path:
    """Archive the current file and atomically activate a verified plan."""
    target = Path(hypervisor_state_path)
    if not target.is_file():
        raise ValidatorRecoveryError("Hypervisor state file does not exist")
    backup = (
        Path(backup_path)
        if backup_path is not None
        else target.with_name(
            f"{target.name}.pre-recovery-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
        )
    )
    backup.parent.mkdir(parents=True, exist_ok=True)
    if backup.exists():
        raise ValidatorRecoveryError(f"recovery backup already exists: {backup}")
    shutil.copy2(target, backup)
    try:
        FileStateStore(target).save(plan.projected_state)
    except Exception:
        shutil.copy2(backup, target)
        raise
    return backup


def _verify_projected_app_hash(snapshot: dict, projected_state: HypervisorStateSnapshot) -> None:
    ledger = LedgerOperationService()
    ledger.restore(
        operations=[item.model_dump(mode="json") for item in projected_state.ledger_operations],
        wallet_sequences=projected_state.wallet_operation_sequences,
        wallet_q_atom_balances=projected_state.wallet_q_atom_balances,
        recyclable_q_atoms=projected_state.recyclable_q_atoms,
        burned_q_atoms=projected_state.burned_q_atoms,
        stake_records=projected_state.stake_records,
        participant_suspensions=projected_state.participant_suspensions,
        session_funding_accounts=[item.model_dump(mode="json") for item in projected_state.session_funding_accounts],
        settlement_proposals=[item.model_dump(mode="json") for item in projected_state.settlement_proposals],
        settlement_acceptances=[item.model_dump(mode="json") for item in projected_state.settlement_acceptances],
        session_checkpoints=[item.model_dump(mode="json") for item in projected_state.session_checkpoints],
        settlement_disputes=[item.model_dump(mode="json") for item in projected_state.settlement_disputes],
        settlement_corrections=[item.model_dump(mode="json") for item in projected_state.settlement_corrections],
        settlement_transition_hashes=projected_state.settlement_transition_hashes,
    )
    computed = AIDNABCIApplication(ledger_service=ledger).prepare_snapshot()["app_hash"]
    expected = str(snapshot.get("app_hash", "")).lower()
    if computed.lower() != expected:
        raise ValidatorRecoveryError(
            f"projected Hypervisor state AppHash mismatch: expected {expected}, computed {computed}"
        )


def _operation_ids(operations: list[dict]) -> set[str]:
    result: set[str] = set()
    for operation in operations:
        operation_id = operation.get("operation_id") if isinstance(operation, dict) else None
        if not isinstance(operation_id, str) or not operation_id.strip():
            raise ValidatorRecoveryError("Ledger operation has no valid operation_id")
        if operation_id in result:
            raise ValidatorRecoveryError(f"duplicate Ledger operation: {operation_id}")
        result.add(operation_id)
    return result


def _filter_operations(operations: list[dict], discarded: set[str]) -> list[dict]:
    return [item for item in operations if item.get("operation_id") not in discarded]


def _current_snapshot_id(store: ABCIStateStore) -> str:
    current_path = store.root / "current.json"
    try:
        import json

        pointer = json.loads(current_path.read_text(encoding="utf-8"))
        identifier = pointer["snapshot_id"]
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValidatorRecoveryError("ABCI current snapshot pointer is invalid") from error
    return str(identifier)
