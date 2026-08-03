import json

import pytest

from aidn_hypervisor.consensus.abci import AIDNABCIApplication
from aidn_hypervisor.consensus.admission import AdmissionValidator
from aidn_hypervisor.consensus.coverage import (
    CONSENSUS_APPLIED_OPERATION_TYPES,
    VALIDATION_EVIDENCE_OPERATION_TYPES,
    operation_coverage,
    strict_operation_coverage_error,
)
from aidn_hypervisor.consensus.execution import ExecutionEngine
from aidn_hypervisor.consensus.models import KNOWN_OPERATION_TYPES, LedgerOperationEnvelope
from aidn_hypervisor.ledger.service import LedgerOperationService


def _tx(operation_type: str) -> bytes:
    envelope = LedgerOperationEnvelope(
        operation_type=operation_type,
        origin_type="protocol",
        created_at="2030-01-01T00:00:00Z",
        payload={},
    )
    return json.dumps(envelope.model_dump(mode="json")).encode("utf-8")


def test_coverage_matrix_has_no_applied_operation_outside_protocol_catalog() -> None:
    assert CONSENSUS_APPLIED_OPERATION_TYPES <= KNOWN_OPERATION_TYPES
    assert all(
        operation_coverage(operation_type) == "IMPLEMENTED"
        for operation_type in CONSENSUS_APPLIED_OPERATION_TYPES
    )
    assert operation_coverage("CUSTOM_EXTENSION") == "EXTENSION"
    assert operation_coverage("REGISTRY_UPSERT") == "DECLARED_UNIMPLEMENTED"
    assert VALIDATION_EVIDENCE_OPERATION_TYPES <= CONSENSUS_APPLIED_OPERATION_TYPES


@pytest.mark.parametrize(
    "operation_type",
    sorted(KNOWN_OPERATION_TYPES - CONSENSUS_APPLIED_OPERATION_TYPES),
)
def test_strict_profile_rejects_every_declared_unimplemented_operation(
    operation_type: str,
) -> None:
    assert strict_operation_coverage_error(operation_type) == (
        "consensus operation transition is not implemented: "
        f"{operation_type}"
    )


def test_strict_abci_rejects_known_unimplemented_transition() -> None:
    app = AIDNABCIApplication(
        ledger_service=LedgerOperationService(),
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        strict_operation_coverage=True,
    )

    result = app.process_proposal_transaction(_tx("REGISTRY_UPSERT"))

    assert result.code == "rejected"
    assert result.log == "consensus operation transition is not implemented: REGISTRY_UPSERT"
    assert app.mempool.size() == 0


def test_strict_execution_rejects_unregistered_extension_without_handler() -> None:
    engine = ExecutionEngine(
        ledger_service=LedgerOperationService(),
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        strict_operation_coverage=True,
    )

    result = engine.execute_block(
        block_height=1,
        block_hash=b"E" * 32,
        txs=[_tx("CUSTOM_EXTENSION")],
    )

    assert result.operations_executed == 0
    assert result.operations_rejected == 1
    assert result.execution_events[0].error == "consensus operation type is not registered: CUSTOM_EXTENSION"


def test_strict_execution_allows_explicit_custom_handler() -> None:
    engine = ExecutionEngine(
        ledger_service=LedgerOperationService(),
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        strict_operation_coverage=True,
    )
    engine.register_handler("CUSTOM_EXTENSION", lambda envelope, ledger: {})

    result = engine.execute_block(
        block_height=1,
        block_hash=b"H" * 32,
        txs=[_tx("CUSTOM_EXTENSION")],
    )

    assert result.operations_executed == 1
    assert result.operations_rejected == 0
