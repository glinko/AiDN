import pytest

from aidn_hypervisor.consensus.finality import (
    ConsensusFinalityEvidence,
    QuorumConsensusFinalitySource,
    VerifiedConsensusFinalitySource,
)
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.consensus.service import (
    ConsensusMode,
    ConsensusService,
    ConsensusServiceConfig,
    SubmissionStatus,
)
from aidn_hypervisor.queue import InMemoryTaskQueue
from aidn_hypervisor.scheduler import Scheduler
from aidn_hypervisor.service import HypervisorService


def _evidence(*, operation_id: str = "operation-1") -> ConsensusFinalityEvidence:
    return ConsensusFinalityEvidence(
        operation_id=operation_id,
        chain_id="aidn-testnet-1",
        block_height=42,
        block_id="block-42",
        app_hash="app-hash-42",
        commit_hash="commit-hash-42",
        finalized_at="2030-01-01T00:00:00Z",
        verifier_id="cometbft-rpc-verifier",
    )


def test_verified_finality_source_returns_only_verified_matching_evidence():
    evidence = _evidence()
    source = VerifiedConsensusFinalitySource(
        load=lambda operation_id: evidence,
        verify=lambda candidate: candidate.commit_hash == "commit-hash-42",
    )

    assert source.finality_evidence("operation-1") == evidence


def test_verified_finality_source_fails_closed_for_mismatched_or_invalid_evidence():
    mismatched = VerifiedConsensusFinalitySource(
        load=lambda operation_id: _evidence(operation_id="operation-other"),
        verify=lambda candidate: True,
    )
    rejected = VerifiedConsensusFinalitySource(
        load=lambda operation_id: _evidence(),
        verify=lambda candidate: False,
    )
    broken = VerifiedConsensusFinalitySource(
        load=lambda operation_id: (_ for _ in ()).throw(ConnectionError("offline")),
        verify=lambda candidate: True,
    )

    assert mismatched.finality_evidence("operation-1") is None
    assert rejected.finality_evidence("operation-1") is None
    assert broken.finality_evidence("operation-1") is None


def test_finality_evidence_rejects_incomplete_or_unsupported_records():
    with pytest.raises(ValueError, match="block_height"):
        ConsensusFinalityEvidence(
            **{
                **_evidence().model_dump(),
                "block_height": 0,
            }
        )


def test_finality_evidence_permits_empty_cometbft_app_hash():
    evidence = ConsensusFinalityEvidence(
        **{
            **_evidence().model_dump(),
            "app_hash": "",
        }
    )

    assert evidence.app_hash == ""


def test_quorum_finality_source_requires_matching_evidence_from_configured_sources():
    evidence = _evidence()

    class Source:
        def __init__(self, value):
            self.value = value

        def finality_evidence(self, operation_id: str):
            return self.value

    source = QuorumConsensusFinalitySource(
        sources=[Source(evidence), Source(evidence), Source(None)],
        quorum=2,
        source_ids=["rpc-a", "rpc-b", "rpc-c"],
    )

    assert source.finality_evidence("operation-1") == evidence


def test_quorum_finality_source_fails_closed_without_matching_quorum():
    first = _evidence()
    second = ConsensusFinalityEvidence(
        **{**first.model_dump(), "block_id": "different-block"}
    )

    class Source:
        def __init__(self, value):
            self.value = value

        def finality_evidence(self, operation_id: str):
            return self.value

    source = QuorumConsensusFinalitySource(
        sources=[Source(first), Source(second), Source(None)],
        quorum=2,
        source_ids=["rpc-a", "rpc-b", "rpc-c"],
    )

    assert source.finality_evidence("operation-1") is None


def test_quorum_finality_source_accepts_only_the_unique_matching_supermajority():
    first = _evidence()
    second = ConsensusFinalityEvidence(
        **{**first.model_dump(), "block_id": "different-block"}
    )

    class Source:
        def __init__(self, value):
            self.value = value

        def finality_evidence(self, operation_id: str):
            return self.value

    source = QuorumConsensusFinalitySource(
        sources=[Source(first), Source(first), Source(second)],
        quorum=2,
        source_ids=["validator-view-a", "validator-view-b", "validator-view-c"],
    )

    assert source.finality_evidence("operation-1") == first

    strict_source = QuorumConsensusFinalitySource(
        sources=[Source(first), Source(first), Source(second)],
        quorum=3,
        source_ids=["validator-view-a", "validator-view-b", "validator-view-c"],
    )
    assert strict_source.finality_evidence("operation-1") is None


def test_quorum_finality_source_fails_closed_on_an_ambiguous_tie():
    first = _evidence()
    second = ConsensusFinalityEvidence(
        **{**first.model_dump(), "block_id": "different-block"}
    )

    class Source:
        def __init__(self, value):
            self.value = value

        def finality_evidence(self, operation_id: str):
            return self.value

    source = QuorumConsensusFinalitySource(
        sources=[Source(first), Source(first), Source(second), Source(second)],
        quorum=2,
        source_ids=["rpc-a", "rpc-b", "rpc-c", "rpc-d"],
    )

    assert source.finality_evidence("operation-1") is None


def test_quorum_finality_source_rejects_invalid_configuration():
    with pytest.raises(ValueError, match="at least two"):
        QuorumConsensusFinalitySource(sources=[], quorum=1)


def test_hypervisor_reports_local_consensus_state_without_claiming_finality():
    consensus = ConsensusService(ConsensusServiceConfig(mode=ConsensusMode.NON_VALIDATOR))
    envelope = LedgerOperationEnvelope(
        operation_type="REGISTRY_UPSERT",
        origin_type="protocol",
        created_at="2030-01-01T00:00:00Z",
    )
    consensus.submit_operation(envelope)
    assert consensus.mark_finalized(envelope.operation_id, block_height=9) is True
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        consensus_service=consensus,
    )

    finality = service.ledger_operation_finality(envelope.operation_id)

    assert finality["status"] == "locally_observed_finalized"
    assert finality["consensus_finalized"] is False
    assert finality["finality_evidence"] is None


def test_hypervisor_uses_verified_finality_source_when_present():
    evidence = _evidence()

    class FinalitySource:
        def finality_evidence(self, operation_id: str):
            return evidence

    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        consensus_finality_source=FinalitySource(),
    )

    finality = service.ledger_operation_finality("operation-1")

    assert finality["status"] == "consensus_finalized"
    assert finality["consensus_finalized"] is True
    assert finality["finality_evidence"]["commit_hash"] == "commit-hash-42"


def test_hypervisor_reconciles_verified_finality_into_submission_state():
    consensus = ConsensusService(
        ConsensusServiceConfig(
            mode=ConsensusMode.NON_VALIDATOR,
            chain_id="aidn-testnet-1",
        )
    )
    envelope = LedgerOperationEnvelope(
        operation_type="REGISTRY_UPSERT",
        origin_type="protocol",
        created_at="2030-01-01T00:00:00Z",
    )
    consensus.submit_operation(envelope)
    evidence = _evidence(operation_id=envelope.operation_id)

    class FinalitySource:
        def finality_evidence(self, operation_id: str):
            return evidence

    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        consensus_service=consensus,
        consensus_finality_source=FinalitySource(),
    )

    finality = service.ledger_operation_finality(envelope.operation_id)

    assert finality["consensus_finalized"] is True
    assert consensus.get_submission(envelope.operation_id).status == SubmissionStatus.FINALIZED
    assert consensus.get_submission(envelope.operation_id).block_height == 42
