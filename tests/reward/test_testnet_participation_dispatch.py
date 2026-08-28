from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aidn_hypervisor.consensus.epoch_schedule import build_epoch_schedule
from aidn_hypervisor.consensus.finality import ConsensusFinalityEvidence
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.testnet_participation import (
    TestnetParticipantEnrollment,
    build_testnet_heartbeat_evidence,
)
from aidn_hypervisor.testnet_participation_dispatch import (
    TestnetParticipationSettlementDispatcher,
)
from aidn_hypervisor.testnet_participation_evidence import TestnetParticipationEvidenceStore
from aidn_hypervisor.testnet_participation_payout import ParticipationTransferSubmission
from aidn_hypervisor.testnet_participation_runtime import (
    TestnetParticipationManagedRuntime,
    TestnetParticipationRuntimeConfig,
)

START = datetime(2026, 9, 1, tzinfo=UTC)
EPOCH_SECONDS = 600


class _Finality:
    def __init__(self, chain_id: str) -> None:
        self.chain_id = chain_id
        self.known: set[str] = set()

    def finality_evidence(self, operation_id: str):
        if operation_id not in self.known:
            return None
        return ConsensusFinalityEvidence(
            operation_id=operation_id,
            chain_id=self.chain_id,
            block_height=100,
            block_id="block-100",
            app_hash="app-hash",
            commit_hash="commit-hash",
            finalized_at=(START + timedelta(days=1)).isoformat(),
            verifier_id="test-finality",
            operation_type="EPOCH_TRANSITION",
        )


class _Submitter:
    def __init__(self) -> None:
        self.submitted: list[LedgerOperationEnvelope] = []

    def next_sender_sequence(self, wallet_id: str) -> int:
        assert wallet_id == "wallet-treasury"
        return 1

    def treasury_balance_q_atoms(self, wallet_id: str) -> int:
        assert wallet_id == "wallet-treasury"
        return 10_000_000

    def submit_transfer(self, envelope: LedgerOperationEnvelope) -> ParticipationTransferSubmission:
        self.submitted.append(envelope)
        return ParticipationTransferSubmission(operation_id=envelope.operation_id, status="FINALIZED")

    def reconcile_transfer(self, envelope: LedgerOperationEnvelope) -> ParticipationTransferSubmission:
        return self.submit_transfer(envelope)


def _schedule():
    return build_epoch_schedule(
        genesis_start_time=START.isoformat(),
        epoch_duration_seconds=EPOCH_SECONDS,
        parameter_version="genesis",
        task_set_version="genesis",
        protocol_version="0.1",
    )


def _transition(schedule, closing_epoch: int) -> LedgerOperationEnvelope:
    scheduled_end = START + timedelta(seconds=(closing_epoch + 1) * EPOCH_SECONDS)
    return LedgerOperationEnvelope(
        operation_type="EPOCH_TRANSITION",
        origin_type="protocol",
        initiator_id="epoch-engine",
        fee_class="protocol_sponsored",
        protocol_version="0.1",
        created_at=scheduled_end.isoformat(),
        target_epoch=str(closing_epoch),
        payload={
            "closing_epoch": closing_epoch,
            "opening_epoch": closing_epoch + 1,
            "epoch_schedule_hash": schedule.schedule_hash,
            "scheduled_end_time": scheduled_end.isoformat().replace("+00:00", "Z"),
        },
    )


def _write_program(path) -> None:
    path.write_text(
        """schema_version = \"aidn.testnet-participation.v1\"\n\n[program]\nprogram_id = \"testnet-alpha-participation-1\"\nnetwork_id = \"aidn-testnet\"\nchain_id = \"aidn-testnet-1\"\nactive_from_epoch = 10\ncompatible_protocol_versions = [\"0.1\"]\n""",
        encoding="utf-8",
    )


def _populate_evidence(path) -> None:
    key = Ed25519PrivateKey.generate()
    store = TestnetParticipationEvidenceStore(path)
    store.register_enrollment(
        TestnetParticipantEnrollment(
            node_id="node-1",
            owner_wallet="wallet-owner",
            reward_wallet="wallet-reward",
            registered_at=(START - timedelta(minutes=30)).isoformat(),
            registered_epoch=9,
        ),
        public_key="ed25519:" + key.public_key().public_bytes_raw().hex(),
        binding_operation_id="operator-wallet-bind:node-1",
    )
    for slot in range(16):
        heartbeat = build_testnet_heartbeat_evidence(
            evidence_id=f"heartbeat:{slot}",
            node_id="node-1",
            network_id="aidn-testnet",
            chain_id="aidn-testnet-1",
            observed_at=(START + timedelta(seconds=30 * slot)).isoformat(),
            protocol_version="0.1",
            identity_signature_verified=False,
        )
        store.record_finalized_heartbeat(
            heartbeat.model_copy(
                update={"identity_signature": "ed25519:" + key.sign(heartbeat.signing_bytes()).hex()}
            )
        )


def _runtime(tmp_path, *, enabled: bool = True):
    if not enabled:
        return TestnetParticipationManagedRuntime(
            config=TestnetParticipationRuntimeConfig(
                active_network_id="aidn-testnet", active_chain_id="aidn-testnet-1"
            )
        )
    program_path = tmp_path / "program.toml"
    evidence_path = tmp_path / "evidence.sqlite"
    _write_program(program_path)
    _populate_evidence(evidence_path)
    return TestnetParticipationManagedRuntime(
        config=TestnetParticipationRuntimeConfig(
            enabled=True,
            mode="dry_run",
            active_network_id="aidn-testnet",
            active_chain_id="aidn-testnet-1",
            program_path=str(program_path),
            evidence_store_path=str(evidence_path),
            payout_store_path=str(tmp_path / "payout.sqlite"),
            treasury_wallet="wallet-treasury",
            treasury_signer_secret_ref="secret://testnet/treasury",
        ),
        signer=lambda _: "ed25519:" + "ab" * 64,
        submitter=_Submitter(),
    )


def test_dispatcher_runs_only_at_the_finalized_daily_schedule_boundary(tmp_path) -> None:
    schedule = _schedule()
    runtime = _runtime(tmp_path)
    finality = _Finality("aidn-testnet-1")
    dispatcher = TestnetParticipationSettlementDispatcher(
        runtime=runtime, epoch_schedule=schedule, finality_source=finality
    )
    not_due = _transition(schedule, closing_epoch=142)
    finality.known.add(not_due.operation_id)
    assert dispatcher.dispatch(not_due).status == "not_due"

    due = _transition(schedule, closing_epoch=143)
    finality.known.add(due.operation_id)
    result = dispatcher.dispatch(due)
    assert result.status == "processed"
    assert result.period_start == "2026-09-01T00:00:00Z"
    assert result.runtime is not None
    assert result.runtime.mode == "dry_run"
    assert result.runtime.batch_status == "PENDING"

    # Re-observing the exact finalized transition reuses the same durable batch.
    assert dispatcher.dispatch(due).runtime is not None


def test_dispatcher_requires_verified_finality_and_committed_schedule(tmp_path) -> None:
    schedule = _schedule()
    runtime = _runtime(tmp_path, enabled=False)
    finality = _Finality("aidn-testnet-1")
    dispatcher = TestnetParticipationSettlementDispatcher(
        runtime=runtime, epoch_schedule=schedule, finality_source=finality
    )
    transition = _transition(schedule, closing_epoch=143)
    with pytest.raises(ValueError, match="TRANSITION_NOT_FINALIZED"):
        dispatcher.dispatch(transition)

    finality.known.add(transition.operation_id)
    incompatible = transition.model_copy(
        update={"payload": {**transition.payload, "epoch_schedule_hash": "sha256:wrong"}}
    )
    with pytest.raises(ValueError, match="SCHEDULE_MISMATCH"):
        dispatcher.dispatch(incompatible)

