from __future__ import annotations

from datetime import UTC, datetime, timedelta

from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.testnet_participation import (
    TestnetParticipantEnrollment as ParticipantEnrollment,
)
from aidn_hypervisor.testnet_participation import (
    TestnetParticipationCalculator,
    build_testnet_heartbeat_evidence,
)
from aidn_hypervisor.testnet_participation import (
    TestnetParticipationProgram as ParticipationProgram,
)
from aidn_hypervisor.testnet_participation_payout import (
    ParticipationTransferSubmission,
)
from aidn_hypervisor.testnet_participation_payout import (
    TestnetParticipationPayoutService as PayoutService,
)
from aidn_hypervisor.testnet_participation_payout import (
    TestnetParticipationPayoutStore as PayoutStore,
)

START = datetime(2026, 9, 1, tzinfo=UTC)


class _Submitter:
    def __init__(self) -> None:
        self.submitted: list[LedgerOperationEnvelope] = []
        self.finalize = False
        self.reject = False

    def next_sender_sequence(self, wallet_id: str) -> int:
        assert wallet_id == "q1treasury"
        return 7

    def treasury_balance_q_atoms(self, wallet_id: str) -> int:
        assert wallet_id == "q1treasury"
        return 10_000_000

    def submit_transfer(self, envelope: LedgerOperationEnvelope) -> ParticipationTransferSubmission:
        self.submitted.append(envelope)
        return ParticipationTransferSubmission(
            operation_id=envelope.operation_id,
            status=(
                "REJECTED"
                if self.reject
                else "FINALIZED"
                if self.finalize
                else "ADMITTED"
            ),
        )

    def reconcile_transfer(self, envelope: LedgerOperationEnvelope) -> ParticipationTransferSubmission:
        self.submitted.append(envelope)
        return ParticipationTransferSubmission(
            operation_id=envelope.operation_id,
            status=(
                "REJECTED"
                if self.reject
                else "FINALIZED"
                if self.finalize
                else "ADMITTED"
            ),
        )


def _settlement():
    program = ParticipationProgram(
        program_id="testnet-alpha-participation-1",
        network_id="aidn-testnet",
        chain_id="aidn-testnet-1",
        active_from_epoch=10,
        compatible_protocol_versions=["0.1"],
    )
    enrollments = [
        ParticipantEnrollment(
            node_id=f"node-{index}",
            owner_wallet=f"q1owner{index}",
            reward_wallet=f"q1reward{index}",
            registered_at=(START - timedelta(minutes=30)).isoformat(),
            registered_epoch=9,
        )
        for index in (1, 2)
    ]
    heartbeats = [
        build_testnet_heartbeat_evidence(
            evidence_id=f"node-{node}:{slot}",
            node_id=f"node-{node}",
            network_id="aidn-testnet",
            chain_id="aidn-testnet-1",
            observed_at=(START + timedelta(seconds=30 * slot)).isoformat(),
            protocol_version="0.1",
        )
        for node in (1, 2)
        for slot in range(16)
    ]
    return TestnetParticipationCalculator().calculate(
        program,
        protocol_epoch=10,
        source_epoch_transition_operation_id="epoch-transition:10",
        period_start=START.isoformat(),
        enrollments=enrollments,
        heartbeats=heartbeats,
    )


def _service(tmp_path, submitter: _Submitter) -> PayoutService:
    return PayoutService(
        treasury_wallet="q1treasury",
        signer=lambda payload: "ed25519:" + ("ab" * 64),
        store=PayoutStore(tmp_path / "payouts.sqlite"),
        submitter=submitter,
        now=lambda: START,
    )


def test_payout_worker_does_not_advance_sequence_before_finality(tmp_path) -> None:
    submitter = _Submitter()
    service = _service(tmp_path, submitter)
    settlement = _settlement()
    batch = service.schedule(settlement)

    first = service.process_next(settlement.settlement_id)
    assert first is not None and first["status"] == "PENDING"
    assert [item.sender_sequence for item in submitter.submitted] == [7]

    submitter.finalize = True
    reconciled = service.process_next(settlement.settlement_id, reconcile=True)
    assert reconciled is not None and reconciled["status"] == "FINALIZED"
    second = service.process_next(settlement.settlement_id)
    assert second is not None and second["status"] == "FINALIZED"
    assert [item.sender_sequence for item in submitter.submitted] == [7, 7, 8]
    assert service.process_next(settlement.settlement_id) is None
    assert service.store.get_batch(settlement.settlement_id)["status"] == "FINALIZED"
    assert batch.total_reward_q_atoms == 2_000_000


def test_payout_worker_restart_reuses_exact_signed_batch(tmp_path) -> None:
    submitter = _Submitter()
    settlement = _settlement()
    first = _service(tmp_path, submitter)
    batch = first.schedule(settlement)
    first.process_next(settlement.settlement_id)

    restarted = _service(tmp_path, submitter)
    restored = restarted.schedule(settlement)

    assert restored.model_dump(mode="json") == batch.model_dump(mode="json")
    assert len(submitter.submitted) == 1


def test_deterministic_rejection_blocks_the_batch_without_skipping_a_sequence(tmp_path) -> None:
    submitter = _Submitter()
    submitter.reject = True
    service = _service(tmp_path, submitter)
    settlement = _settlement()
    service.schedule(settlement)

    rejected = service.process_next(settlement.settlement_id)

    assert rejected is not None and rejected["status"] == "REJECTED"
    assert [item.sender_sequence for item in submitter.submitted] == [7]
    assert service.process_next(settlement.settlement_id) is None
    assert service.store.get_batch(settlement.settlement_id)["status"] == "BLOCKED"
