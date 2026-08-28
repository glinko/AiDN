from __future__ import annotations

from types import SimpleNamespace

from aidn_hypervisor.consensus.finality import ConsensusFinalityEvidence
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.testnet_participation_consensus import (
    ConsensusParticipationTransferSubmitter,
)


def _transfer() -> LedgerOperationEnvelope:
    return LedgerOperationEnvelope(
        operation_type="WALLET_TRANSFER",
        origin_type="wallet",
        initiator_id="testnet-participation:test",
        sender_wallet="wallet-treasury",
        sender_sequence=1,
        fee_payer="wallet-treasury",
        created_at="2030-01-01T00:00:00Z",
        payload={"recipient_wallet": "wallet-reward", "amount": 1_000_000},
    )


class _FinalitySource:
    def __init__(self, evidence: ConsensusFinalityEvidence | None = None) -> None:
        self.evidence = evidence

    def finality_evidence(self, operation_id: str) -> ConsensusFinalityEvidence | None:
        if self.evidence is None or self.evidence.operation_id != operation_id:
            return None
        return self.evidence


class _Consensus:
    def __init__(self) -> None:
        self.config = SimpleNamespace(chain_id="aidn-testnet-1")
        self.submitted: list[tuple[LedgerOperationEnvelope, bool]] = []
        self.restored: list[str] = []
        self.marked: list[tuple[str, int]] = []

    def query_wallet_next_sequence(self, wallet_id: str) -> int:
        assert wallet_id == "wallet-treasury"
        return 7

    def submit_operation(self, envelope: LedgerOperationEnvelope, *, retry_existing: bool = False):
        self.submitted.append((envelope, retry_existing))
        return SimpleNamespace(status=SimpleNamespace(value="admitted"), error=None)

    def restore_submission(self, envelope: LedgerOperationEnvelope):
        self.restored.append(envelope.operation_id)

    def mark_included(self, operation_id: str, height: int) -> None:
        self.marked.append((operation_id, height))

    def mark_finalized(self, operation_id: str, height: int) -> None:
        self.marked.append((operation_id, height))


def test_consensus_submitter_fails_closed_for_sequence_and_balance_reads() -> None:
    adapter = ConsensusParticipationTransferSubmitter(
        consensus_service=_Consensus(),
        finality_source=_FinalitySource(),
        canonical_balance_q_atoms=lambda wallet_id: 5_000_000,
    )

    assert adapter.next_sender_sequence("wallet-treasury") == 7
    assert adapter.treasury_balance_q_atoms("wallet-treasury") == 5_000_000
    assert adapter.submit_transfer(_transfer()).status == "ADMITTED"


def test_consensus_submitter_reconciles_verified_finality_before_rebroadcast() -> None:
    envelope = _transfer()
    consensus = _Consensus()
    finality = ConsensusFinalityEvidence(
        operation_id=envelope.operation_id,
        operation_type="WALLET_TRANSFER",
        chain_id="aidn-testnet-1",
        block_height=14,
        block_id="block-14",
        app_hash="app-hash",
        commit_hash="commit-hash",
        finalized_at="2030-01-01T00:00:10Z",
        verifier_id="test-finality",
    )
    adapter = ConsensusParticipationTransferSubmitter(
        consensus_service=consensus,
        finality_source=_FinalitySource(finality),
        canonical_balance_q_atoms=lambda wallet_id: 5_000_000,
    )

    result = adapter.reconcile_transfer(envelope)

    assert result.status == "FINALIZED"
    assert consensus.restored == []
    assert consensus.submitted == []
    assert consensus.marked == [(envelope.operation_id, 14), (envelope.operation_id, 14)]
