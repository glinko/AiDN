import pytest

from aidn_hypervisor.consensus.replay import (
    FinalizedOperationRegistry,
    finalized_operation_digest,
)
from aidn_hypervisor.ledger.service import LedgerOperationService


def _record(sequence_id: int = 1, operation_id: str = "operation-1") -> dict:
    return {
        "sequence_id": sequence_id,
        "operation_id": operation_id,
        "operation_type": "TEST_OPERATION",
        "payload": {"value": sequence_id},
    }


def test_replay_registry_indexes_immutable_record_digest() -> None:
    record = _record()
    registry = FinalizedOperationRegistry.from_records([record])

    reference = registry.require("operation-1")

    assert reference.record_digest == finalized_operation_digest(record)
    assert registry.operation_ids() == {"operation-1"}
    assert registry.snapshot() == [reference.as_dict()]


def test_replay_registry_rejects_duplicate_or_conflicting_identity() -> None:
    registry = FinalizedOperationRegistry.from_records([_record()])

    with pytest.raises(ValueError, match="duplicate finalized operation ID"):
        registry.register(_record())

    conflicting = _record()
    conflicting["payload"] = {"value": "different"}
    with pytest.raises(ValueError, match="conflicting finalized operation identity"):
        registry.register(conflicting)


def test_replay_registry_rejects_duplicate_sequence_and_restore_rebuilds_it() -> None:
    with pytest.raises(ValueError, match="sequence is duplicated"):
        FinalizedOperationRegistry.from_records([_record(), _record(operation_id="operation-2")])

    ledger = LedgerOperationService()
    operation = ledger.record_operation(
        operation_type="TEST_OPERATION",
        origin_type="protocol",
        fee_class="standard",
        payload={"value": "one"},
    )
    restored = LedgerOperationService()
    restored.restore(
        operations=ledger.snapshot_operations(),
        wallet_sequences=ledger.snapshot_wallet_sequences(),
    )

    assert restored.finalized_operation_ids() == {operation["operation_id"]}
    assert restored.finalized_operation_reference(operation["operation_id"]) == ledger.finalized_operation_reference(
        operation["operation_id"]
    )
