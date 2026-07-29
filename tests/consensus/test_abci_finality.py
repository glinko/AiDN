"""Tests for binding verified CometBFT evidence to local ABCI state."""

from aidn_hypervisor.consensus.abci import AIDNABCIApplication
from aidn_hypervisor.consensus.abci_finality import ABCICommittedFinalitySource
from aidn_hypervisor.consensus.finality import ConsensusFinalityEvidence
from aidn_hypervisor.ledger.service import LedgerOperationService


class StaticEvidenceSource:
    def __init__(self, evidence: ConsensusFinalityEvidence | None) -> None:
        self.evidence = evidence

    def finality_evidence(self, operation_id: str) -> ConsensusFinalityEvidence | None:
        if self.evidence is not None and self.evidence.operation_id == operation_id:
            return self.evidence
        return None


def _app_and_evidence() -> tuple[AIDNABCIApplication, ConsensusFinalityEvidence]:
    app = AIDNABCIApplication(ledger_service=LedgerOperationService())
    block_hash = b"\xAB" * 32
    app.finalize_block(block_height=7, block_hash=block_hash, txs=[])
    commitment = app.commitment_at(7)
    assert commitment is not None
    return app, ConsensusFinalityEvidence(
        operation_id="operation-1",
        chain_id="aidn-testnet-1",
        block_height=7,
        block_id=commitment.block_hash,
        app_hash=commitment.app_hash,
        commit_hash="C" * 64,
        finalized_at="2030-01-01T00:00:00Z",
        verifier_id="zip215-light-client",
    )


def test_abci_committed_finality_source_requires_exact_local_commitment_match():
    app, evidence = _app_and_evidence()
    source = ABCICommittedFinalitySource(
        source=StaticEvidenceSource(evidence),
        abci_application=app,
    )

    assert source.finality_evidence("operation-1") == evidence


def test_abci_committed_finality_source_rejects_mismatched_app_hash_or_block_hash():
    app, evidence = _app_and_evidence()
    bad_app_hash = ConsensusFinalityEvidence(
        **{**evidence.model_dump(), "app_hash": "D" * 64}
    )
    bad_block_hash = ConsensusFinalityEvidence(
        **{**evidence.model_dump(), "block_id": "E" * 64}
    )

    assert (
        ABCICommittedFinalitySource(
            source=StaticEvidenceSource(bad_app_hash),
            abci_application=app,
        ).finality_evidence("operation-1")
        is None
    )
    assert (
        ABCICommittedFinalitySource(
            source=StaticEvidenceSource(bad_block_hash),
            abci_application=app,
        ).finality_evidence("operation-1")
        is None
    )
