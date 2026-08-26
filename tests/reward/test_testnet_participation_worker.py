from __future__ import annotations

from datetime import UTC, datetime, timedelta

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.testnet_participation import (
    TestnetParticipantEnrollment as ParticipantEnrollment,
)
from aidn_hypervisor.testnet_participation import (
    TestnetParticipationProgram as ParticipationProgram,
)
from aidn_hypervisor.testnet_participation import (
    build_testnet_heartbeat_evidence,
)
from aidn_hypervisor.testnet_participation_evidence import (
    TestnetParticipationEvidenceStore as EvidenceStore,
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
from aidn_hypervisor.testnet_participation_worker import (
    TestnetParticipationWorker as ParticipationWorker,
)

START = datetime(2026, 9, 1, tzinfo=UTC)


class _Submitter:
    def next_sender_sequence(self, wallet_id: str) -> int:
        assert wallet_id == "wallet-treasury"
        return 1

    def treasury_balance_q_atoms(self, wallet_id: str) -> int:
        return 5_000_000

    def submit_transfer(self, envelope: LedgerOperationEnvelope) -> ParticipationTransferSubmission:
        return ParticipationTransferSubmission(
            operation_id=envelope.operation_id, status="FINALIZED"
        )

    def reconcile_transfer(self, envelope: LedgerOperationEnvelope) -> ParticipationTransferSubmission:
        return self.submit_transfer(envelope)


def _public_key(private_key: Ed25519PrivateKey) -> str:
    return "ed25519:" + private_key.public_key().public_bytes_raw().hex()


def test_worker_calculates_from_verified_store_and_finalizes_one_daily_payment(tmp_path) -> None:
    private_key = Ed25519PrivateKey.generate()
    program = ParticipationProgram(
        program_id="testnet-alpha-participation-1",
        network_id="aidn-testnet",
        chain_id="aidn-testnet-1",
        active_from_epoch=10,
        compatible_protocol_versions=["0.1"],
    )
    evidence = EvidenceStore(tmp_path / "evidence.sqlite")
    evidence.register_enrollment(
        ParticipantEnrollment(
            node_id="node-1",
            owner_wallet="wallet-owner",
            reward_wallet="wallet-reward",
            registered_at=(START - timedelta(minutes=30)).isoformat(),
            registered_epoch=9,
        ),
        public_key=_public_key(private_key),
        binding_operation_id="operator-wallet-bind:node-1",
    )
    for slot in range(16):
        raw = build_testnet_heartbeat_evidence(
            evidence_id=f"heartbeat:{slot}",
            node_id="node-1",
            network_id="aidn-testnet",
            chain_id="aidn-testnet-1",
            observed_at=(START + timedelta(seconds=slot * 30)).isoformat(),
            protocol_version="0.1",
            identity_signature_verified=False,
        )
        evidence.record_finalized_heartbeat(
            raw.model_copy(
                update={
                    "identity_signature": "ed25519:"
                    + private_key.sign(raw.signing_bytes()).hex()
                }
            )
        )
    payout = PayoutService(
        treasury_wallet="wallet-treasury",
        signer=lambda payload: "ed25519:" + ("ab" * 64),
        store=PayoutStore(tmp_path / "payout.sqlite"),
        submitter=_Submitter(),
        now=lambda: START,
    )
    worker = ParticipationWorker(
        program=program,
        active_network_id="aidn-testnet",
        active_chain_id="aidn-testnet-1",
        evidence_store=evidence,
        payout_service=payout,
    )

    result = worker.process_finalized_epoch(
        protocol_epoch=10,
        source_epoch_transition_operation_id="epoch-transition:10",
        period_start=START.isoformat(),
    )

    assert result.settlement.total_reward_q_atoms == 1_000_000
    assert result.batch_status == "FINALIZED"
    assert result.processed_operation_id == result.batch.transfers[0].operation_id
