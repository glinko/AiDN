from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta

from aidn_hypervisor.consensus.abci import AIDNABCIApplication
from aidn_hypervisor.consensus.admission import AdmissionValidator
from aidn_hypervisor.consensus.execution import ExecutionEngine
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.consensus.validator_schedule import compute_validator_set_hash
from aidn_hypervisor.ledger.service import LedgerOperationService

PUBLIC_KEY = "ed25519:" + base64.b64encode(bytes(range(32))).decode("ascii")


def _envelope(operation_type: str, payload: dict, *, target_epoch: str) -> bytes:
    value = {
        "operation_type": operation_type,
        "operation_version": "1.0.0",
        "protocol_version": "0.1",
        "origin_type": "protocol",
        "initiator_id": "epoch-engine",
        "sender_wallet": None,
        "sender_sequence": None,
        "fee_payer": None,
        "fee_class": "protocol_sponsored",
        "created_at": datetime.now(UTC).isoformat(),
        "expires_at": (datetime.now(UTC) + timedelta(hours=24)).isoformat(),
        "target_epoch": target_epoch,
        "payload": payload,
        "evidence_references": ["sha256:eligibility"],
        "signatures": ["ed25519:epoch-engine"],
    }
    return json.dumps(value).encode()


def _validator_schedule(*, activation_epoch: int, removal: bool = False) -> bytes:
    if removal:
        additions: list[dict] = []
        removals = [{"node_id": "node-1"}]
        updates: list[dict] = []
    else:
        additions = [
            {
                "node_id": "node-1",
                "operator_id": "operator-1",
                "consensus_address": "sha256:node-1",
                "consensus_public_key": PUBLIC_KEY,
                "stake": 500_000_000_000,
                "voting_power": 1,
            }
        ]
        removals = []
        updates = []
    payload = {
        "activation_epoch": activation_epoch,
        "validator_additions": additions,
        "validator_removals": removals,
        "voting_power_updates": updates,
        "validator_set_hash": compute_validator_set_hash(additions),
        "eligibility_evidence_root": f"sha256:eligibility-{activation_epoch}",
    }
    return _envelope(
        "CONSENSUS_VALIDATOR_SET_UPDATE",
        payload,
        target_epoch=str(activation_epoch),
    )


def _epoch_transition(*, closing_epoch: int) -> bytes:
    payload = {
        "closing_epoch": closing_epoch,
        "opening_epoch": closing_epoch + 1,
        "closing_state_root": f"sha256:closing-{closing_epoch}",
        "epoch_task_result_root": f"sha256:tasks-{closing_epoch}",
        "eligibility_snapshot_root": f"sha256:eligibility-snapshot-{closing_epoch}",
        "reward_calculation_root": f"sha256:rewards-{closing_epoch}",
        "next_protocol_parameters_hash": f"sha256:params-{closing_epoch + 1}",
        "pool_budgets": {"registry": 0},
        "pool_budget_references": {"registry": f"epoch:{closing_epoch}:registry"},
    }
    return _envelope("EPOCH_TRANSITION", payload, target_epoch=str(closing_epoch))


def _application() -> tuple[AIDNABCIApplication, LedgerOperationService]:
    ledger = LedgerOperationService()
    app = AIDNABCIApplication(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(
            current_time=datetime.now(UTC).isoformat()
        ),
    )
    return app, ledger


def test_finalized_epoch_transition_activates_prior_validator_schedule() -> None:
    app, ledger = _application()

    scheduled = app.finalize_block(
        block_height=1,
        block_hash=b"A" * 32,
        txs=[_validator_schedule(activation_epoch=2)],
    )
    activated, tx_results = app.finalize_block_with_results(
        block_height=2,
        block_hash=b"B" * 32,
        txs=[_epoch_transition(closing_epoch=1)],
    )

    assert scheduled.code == "ok"
    assert activated.code == "ok"
    assert tx_results[0].code == "ok"
    assert activated.validator_updates == [{"public_key": PUBLIC_KEY, "power": 1}]
    assert ledger.active_validator_set_epoch() == 2
    assert ledger.active_validator_set()["node-1"]["consensus_public_key"] == PUBLIC_KEY


def test_validator_removal_is_emitted_as_zero_power_update() -> None:
    app, ledger = _application()
    app.finalize_block(
        block_height=1,
        block_hash=b"A" * 32,
        txs=[_validator_schedule(activation_epoch=2)],
    )
    app.finalize_block(
        block_height=2,
        block_hash=b"B" * 32,
        txs=[_epoch_transition(closing_epoch=1)],
    )
    app.finalize_block(
        block_height=3,
        block_hash=b"C" * 32,
        txs=[_validator_schedule(activation_epoch=3, removal=True)],
    )

    activated, tx_results = app.finalize_block_with_results(
        block_height=4,
        block_hash=b"D" * 32,
        txs=[_epoch_transition(closing_epoch=2)],
    )

    assert activated.code == "ok"
    assert tx_results[0].code == "ok"
    assert activated.validator_updates == [{"public_key": PUBLIC_KEY, "power": 0}]
    assert ledger.active_validator_set_epoch() == 3
    assert ledger.active_validator_set() == {}


def test_active_validator_set_survives_abci_snapshot_restore() -> None:
    source, source_ledger = _application()
    source.finalize_block(
        block_height=1,
        block_hash=b"A" * 32,
        txs=[_validator_schedule(activation_epoch=2)],
    )
    source.finalize_block(
        block_height=2,
        block_hash=b"B" * 32,
        txs=[_epoch_transition(closing_epoch=1)],
    )

    restored, restored_ledger = _application()
    result = restored.apply_snapshot(source.prepare_snapshot())

    assert result.code == "ok"
    assert restored_ledger.active_validator_set_epoch() == 2
    assert restored_ledger.active_validator_set() == source_ledger.active_validator_set()


def test_activation_requires_schedule_operation_to_be_pre_finalized() -> None:
    app, ledger = _application()
    schedule = LedgerOperationEnvelope.model_validate(
        json.loads(_validator_schedule(activation_epoch=2))
    )
    ledger.apply_consensus_validator_set_update(schedule)

    try:
        ledger.activate_consensus_validator_set_update(
            activation_epoch=2,
            finalized_operation_ids=set(),
        )
    except ValueError as error:
        assert "not finalized" in str(error)
    else:
        raise AssertionError("activation accepted a non-finalized schedule")


def test_execution_engine_activates_schedule_at_epoch_boundary() -> None:
    ledger = LedgerOperationService()
    engine = ExecutionEngine(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time=datetime.now(UTC).isoformat()),
    )

    scheduled = engine.execute_block(
        block_height=1,
        block_hash=b"A" * 32,
        txs=[_validator_schedule(activation_epoch=2)],
    )
    activated = engine.execute_block(
        block_height=2,
        block_hash=b"B" * 32,
        txs=[_epoch_transition(closing_epoch=1)],
    )

    assert scheduled.error is None
    assert activated.error is None
    assert activated.validator_updates == [{"public_key": PUBLIC_KEY, "power": 1}]
    assert activated.execution_events[0].validator_updates == activated.validator_updates


def test_execution_engine_rejects_same_block_schedule_and_activation() -> None:
    ledger = LedgerOperationService()
    engine = ExecutionEngine(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time=datetime.now(UTC).isoformat()),
    )

    result = engine.execute_block(
        block_height=1,
        block_hash=b"A" * 32,
        txs=[
            _validator_schedule(activation_epoch=2),
            _epoch_transition(closing_epoch=1),
        ],
    )

    assert result.error is not None
    assert "not finalized" in result.error
    assert ledger.snapshot_operations() == []
    assert ledger.active_validator_set() == {}


def test_abci_rejects_same_block_schedule_and_activation() -> None:
    app, ledger = _application()

    result, tx_results = app.finalize_block_with_results(
        block_height=1,
        block_hash=b"A" * 32,
        txs=[
            _validator_schedule(activation_epoch=2),
            _epoch_transition(closing_epoch=1),
        ],
    )

    assert result.code == "internal"
    assert "not finalized" in result.log
    assert all(item.code == "internal" for item in tx_results)
    assert ledger.snapshot_operations() == []
    assert ledger.active_validator_set() == {}
