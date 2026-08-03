from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from aidn_hypervisor.consensus.admission import AdmissionValidator
from aidn_hypervisor.consensus.execution import ExecutionEngine
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.ledger.service import LedgerOperationService


def _envelope(operation_type: str, payload: dict) -> bytes:
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
        "target_epoch": "7",
        "payload": payload,
        "evidence_references": [],
        "signatures": [],
    }
    return json.dumps(value).encode()


def _transition(root: str) -> tuple[bytes, str]:
    value = {
        "closing_epoch": 7,
        "opening_epoch": 8,
        "closing_state_root": "sha256:closing-state",
        "epoch_task_result_root": "sha256:epoch-tasks",
        "eligibility_snapshot_root": "sha256:eligibility",
        "reward_calculation_root": root,
        "next_protocol_parameters_hash": "sha256:next-parameters",
        "pool_budgets": {"registry": 1_000},
        "pool_budget_references": {"registry": "epoch:7:registry"},
    }
    data = _envelope("EPOCH_TRANSITION", value)
    return data, LedgerOperationEnvelope.model_validate(json.loads(data)).operation_id


def _reward(transition_id: str, root: str) -> bytes:
    return _envelope(
        "REWARD_MINT",
        {
            "reward_id": "reward:execution:1",
            "reward_type": "REGISTRY",
            "reward_epoch": 7,
            "recipient_wallet": "wallet:registry-1",
            "amount": 400,
            "pool_id": "registry",
            "pool_budget_reference": "epoch:7:registry",
            "contribution_evidence_root": "sha256:evidence",
            "calculation_version": "registry-reward-calculation.v1",
            "reward_calculation_root": root,
            "calculation_operation_id": transition_id,
        },
    )


def _engine() -> tuple[ExecutionEngine, LedgerOperationService]:
    ledger = LedgerOperationService()
    engine = ExecutionEngine(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(
            current_time=datetime.now(UTC).isoformat()
        ),
    )
    return engine, ledger


def test_execution_engine_applies_registry_mint_after_prior_transition() -> None:
    engine, ledger = _engine()
    root = "sha256:execution-root"
    transition, transition_id = _transition(root)

    first = engine.execute_block(block_height=1, block_hash=b"A" * 32, txs=[transition])
    second = engine.execute_block(
        block_height=2,
        block_hash=b"B" * 32,
        txs=[_reward(transition_id, root)],
    )

    assert first.operations_executed == 1
    assert second.operations_executed == 1
    assert ledger.wallet_q_atom_balance("wallet:registry-1") == 400


def test_execution_engine_rejects_same_block_transition_mint_bypass() -> None:
    engine, ledger = _engine()
    root = "sha256:execution-root"
    transition, transition_id = _transition(root)

    result = engine.execute_block(
        block_height=1,
        block_hash=b"A" * 32,
        txs=[transition, _reward(transition_id, root)],
    )

    assert result.operations_executed == 1
    assert result.operations_rejected == 1
    assert "not finalized" in (result.execution_events[1].error or "")
    assert ledger.wallet_q_atom_balance("wallet:registry-1") == 0


def test_execution_engine_rejects_non_sequential_epoch_transition() -> None:
    engine, ledger = _engine()
    transition, _ = _transition("sha256:execution-root")
    value = json.loads(transition)
    value["payload"]["opening_epoch"] = 9

    result = engine.execute_block(
        block_height=1,
        block_hash=b"A" * 32,
        txs=[json.dumps(value).encode()],
    )

    assert result.operations_executed == 0
    assert result.operations_rejected == 1
    assert "immediately follow" in (result.execution_events[0].error or "")
    assert ledger.snapshot_operations() == []
