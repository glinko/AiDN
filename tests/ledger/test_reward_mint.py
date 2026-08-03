from __future__ import annotations

import pytest

from aidn_hypervisor.consensus.finality import ConsensusFinalityEvidence
from aidn_hypervisor.ledger.service import LedgerOperationService


class _StaticFinalitySource:
    def __init__(self, evidence: ConsensusFinalityEvidence | None) -> None:
        self.evidence = evidence

    def finality_evidence(self, operation_id: str) -> ConsensusFinalityEvidence | None:
        if self.evidence is not None and self.evidence.operation_id == operation_id:
            return self.evidence
        return None


def _transition(ledger: LedgerOperationService, root: str) -> dict:
    return ledger.record_operation(
        operation_type="EPOCH_TRANSITION",
        origin_type="protocol",
        fee_class="protocol_sponsored",
        initiator_id="epoch-engine",
        target_epoch="7",
        payload={
            "closing_epoch": 7,
            "reward_calculation_root": root,
            "pool_budgets": {"registry": 1_000},
        },
    )


def _finality(operation_id: str) -> ConsensusFinalityEvidence:
    return ConsensusFinalityEvidence(
        operation_id=operation_id,
        chain_id="aidn-testnet-1",
        block_height=42,
        block_id="block-42",
        app_hash="app-hash-42",
        commit_hash="commit-42",
        finalized_at="2026-08-01T00:00:00Z",
        verifier_id="quorum-1",
    )


def _mint(ledger: LedgerOperationService, source: _StaticFinalitySource, transition: dict, **overrides) -> dict:
    values = {
        "reward_id": "reward-1",
        "reward_type": "REGISTRY",
        "reward_epoch": 7,
        "recipient_wallet": "wallet:registry-a",
        "amount_q_atoms": 400,
        "pool_id": "registry",
        "pool_budget_reference": "epoch:7:registry",
        "contribution_evidence_root": "root:evidence",
        "calculation_version": "registry-reward-calculation.v1",
        "reward_calculation_root": "root:calculation",
        "calculation_operation_id": transition["operation_id"],
        "finality_source": source,
    }
    values.update(overrides)
    return ledger.commit_reward_mint(**values)


def test_reward_mint_requires_finality_and_credits_once() -> None:
    ledger = LedgerOperationService()
    transition = _transition(ledger, "root:calculation")
    source = _StaticFinalitySource(_finality(transition["operation_id"]))

    first = _mint(ledger, source, transition)
    repeated = _mint(ledger, source, transition)

    assert first == repeated
    assert first["operation_type"] == "REWARD_MINT"
    assert ledger.wallet_q_atom_balance("wallet:registry-a") == 400
    assert [item["operation_type"] for item in ledger.snapshot_operations()] == [
        "EPOCH_TRANSITION",
        "REWARD_MINT",
    ]


def test_reward_mint_rejects_missing_or_mismatched_finality() -> None:
    ledger = LedgerOperationService()
    transition = _transition(ledger, "root:calculation")

    with pytest.raises(ValueError, match="finality"):
        _mint(ledger, _StaticFinalitySource(None), transition)

    with pytest.raises(ValueError, match="finality"):
        _mint(
            ledger,
            _StaticFinalitySource(_finality("different-operation")),
            transition,
            reward_id="reward-2",
        )

    assert ledger.wallet_q_atom_balance("wallet:registry-a") == 0
    assert not any(item["operation_type"] == "REWARD_MINT" for item in ledger.snapshot_operations())


def test_reward_mint_enforces_calculation_root_and_pool_budget() -> None:
    ledger = LedgerOperationService()
    transition = _transition(ledger, "root:calculation")
    source = _StaticFinalitySource(_finality(transition["operation_id"]))

    with pytest.raises(ValueError, match="calculation root"):
        _mint(ledger, source, transition, reward_calculation_root="root:other")

    _mint(ledger, source, transition)
    with pytest.raises(ValueError, match="pool budget"):
        _mint(
            ledger,
            source,
            transition,
            reward_id="reward-2",
            recipient_wallet="wallet:registry-b",
            amount_q_atoms=601,
        )


def test_reward_mint_rejects_conflicting_retry() -> None:
    ledger = LedgerOperationService()
    transition = _transition(ledger, "root:calculation")
    source = _StaticFinalitySource(_finality(transition["operation_id"]))
    _mint(ledger, source, transition)

    with pytest.raises(ValueError, match="conflicting reward"):
        _mint(ledger, source, transition, amount_q_atoms=401)
