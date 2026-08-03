from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from aidn_hypervisor.consensus.abci import AIDNABCIApplication
from aidn_hypervisor.consensus.admission import AdmissionValidator
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.ledger.service import LedgerOperationService


def _timestamp(*, future_hours: int = 0) -> str:
    return (datetime.now(UTC) + timedelta(hours=future_hours)).isoformat()


def _envelope(operation_type: str, payload: dict) -> dict:
    return {
        "operation_type": operation_type,
        "operation_version": "1.0.0",
        "protocol_version": "0.1",
        "origin_type": "protocol",
        "initiator_id": "epoch-engine",
        "sender_wallet": None,
        "sender_sequence": None,
        "fee_payer": None,
        "fee_class": "protocol_sponsored",
        "created_at": _timestamp(),
        "expires_at": _timestamp(future_hours=24),
        "target_epoch": "7",
        "payload": payload,
        "evidence_references": [],
        "signatures": [],
    }


def _transition_payload(root: str) -> dict:
    return {
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


def _reward_payload(transition_operation_id: str, root: str, *, amount: int = 400) -> dict:
    return {
        "reward_id": "reward:registry:1",
        "reward_type": "REGISTRY",
        "reward_epoch": 7,
        "recipient_wallet": "wallet:registry-1",
        "amount": amount,
        "pool_id": "registry",
        "pool_budget_reference": "epoch:7:registry",
        "contribution_evidence_root": "sha256:evidence-root",
        "calculation_version": "registry-reward-calculation.v1",
        "reward_calculation_root": root,
        "calculation_operation_id": transition_operation_id,
    }


def _application() -> tuple[AIDNABCIApplication, LedgerOperationService]:
    ledger = LedgerOperationService()
    app = AIDNABCIApplication(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time=_timestamp()),
    )
    return app, ledger


def test_abci_applies_registry_reward_only_after_finalized_transition() -> None:
    app, ledger = _application()
    root = "sha256:calculation-root"
    transition = _envelope("EPOCH_TRANSITION", _transition_payload(root))
    transition_id = LedgerOperationEnvelope.model_validate(transition).operation_id

    first = app.finalize_block(
        block_height=1,
        block_hash=b"A" * 32,
        txs=[json.dumps(transition).encode()],
    )
    assert first.code == "ok"

    reward = _envelope("REWARD_MINT", _reward_payload(transition_id, root))
    second, tx_results = app.finalize_block_with_results(
        block_height=2,
        block_hash=b"B" * 32,
        txs=[json.dumps(reward).encode()],
    )

    assert second.code == "ok"
    assert tx_results[0].code == "ok"
    assert ledger.wallet_q_atom_balance("wallet:registry-1") == 400
    assert [item["operation_type"] for item in ledger.snapshot_operations()] == [
        "EPOCH_TRANSITION",
        "REWARD_MINT",
    ]


def test_abci_rejects_reward_mint_authorized_by_transition_in_same_block() -> None:
    app, ledger = _application()
    root = "sha256:calculation-root"
    transition = _envelope("EPOCH_TRANSITION", _transition_payload(root))
    transition_id = LedgerOperationEnvelope.model_validate(transition).operation_id
    reward = _envelope("REWARD_MINT", _reward_payload(transition_id, root))

    result, tx_results = app.finalize_block_with_results(
        block_height=1,
        block_hash=b"A" * 32,
        txs=[json.dumps(transition).encode(), json.dumps(reward).encode()],
    )

    assert result.code == "ok"
    assert [item.code for item in tx_results] == ["ok", "rejected"]
    assert "not finalized" in tx_results[1].log
    assert ledger.wallet_q_atom_balance("wallet:registry-1") == 0
    assert [item["operation_type"] for item in ledger.snapshot_operations()] == [
        "EPOCH_TRANSITION"
    ]


def test_abci_rejects_registry_reward_when_root_or_budget_binding_differs() -> None:
    app, ledger = _application()
    transition_root = "sha256:calculation-root"
    transition = _envelope("EPOCH_TRANSITION", _transition_payload(transition_root))
    transition_id = LedgerOperationEnvelope.model_validate(transition).operation_id
    app.finalize_block(
        block_height=1,
        block_hash=b"A" * 32,
        txs=[json.dumps(transition).encode()],
    )

    wrong_root = _envelope(
        "REWARD_MINT",
        _reward_payload(transition_id, "sha256:other-root"),
    )
    wrong_budget = _envelope(
        "REWARD_MINT",
        {
            **_reward_payload(transition_id, transition_root),
            "pool_budget_reference": "epoch:7:other-pool",
        },
    )
    result, tx_results = app.finalize_block_with_results(
        block_height=2,
        block_hash=b"B" * 32,
        txs=[json.dumps(wrong_root).encode(), json.dumps(wrong_budget).encode()],
    )

    assert result.code == "ok"
    assert [item.code for item in tx_results] == ["rejected", "rejected"]
    assert ledger.wallet_q_atom_balance("wallet:registry-1") == 0
    assert len(ledger.snapshot_operations()) == 1


def test_abci_rejects_non_sequential_epoch_transition() -> None:
    app, ledger = _application()
    root = "sha256:calculation-root"
    transition = _envelope(
        "EPOCH_TRANSITION",
        {
            **_transition_payload(root),
            "opening_epoch": 9,
        },
    )

    result, tx_results = app.finalize_block_with_results(
        block_height=1,
        block_hash=b"A" * 32,
        txs=[json.dumps(transition).encode()],
    )

    assert result.code == "ok"
    assert tx_results[0].code == "rejected"
    assert "immediately follow" in tx_results[0].log
    assert ledger.snapshot_operations() == []
