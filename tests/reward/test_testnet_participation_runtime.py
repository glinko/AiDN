from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.testnet_participation import (
    TestnetParticipantEnrollment as ParticipantEnrollment,
)
from aidn_hypervisor.testnet_participation import build_testnet_heartbeat_evidence
from aidn_hypervisor.testnet_participation_evidence import (
    TestnetParticipationEvidenceStore as EvidenceStore,
)
from aidn_hypervisor.testnet_participation_payout import ParticipationTransferSubmission
from aidn_hypervisor.testnet_participation_runtime import (
    TestnetParticipationManagedRuntime as ManagedRuntime,
)
from aidn_hypervisor.testnet_participation_runtime import (
    TestnetParticipationRuntimeConfig as RuntimeConfig,
)

START = datetime(2026, 9, 1, tzinfo=UTC)


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


def _write_program(path) -> None:
    path.write_text(
        """schema_version = \"aidn.testnet-participation.v1\"\n\n[program]\nprogram_id = \"testnet-alpha-participation-1\"\nnetwork_id = \"aidn-testnet\"\nchain_id = \"aidn-testnet-1\"\nactive_from_epoch = 10\ncompatible_protocol_versions = [\"0.1\"]\n""",
        encoding="utf-8",
    )


def _populate_evidence(path) -> None:
    key = Ed25519PrivateKey.generate()
    store = EvidenceStore(path)
    store.register_enrollment(
        ParticipantEnrollment(
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
        unsigned = build_testnet_heartbeat_evidence(
            evidence_id=f"heartbeat:{slot}",
            node_id="node-1",
            network_id="aidn-testnet",
            chain_id="aidn-testnet-1",
            observed_at=(START + timedelta(seconds=30 * slot)).isoformat(),
            protocol_version="0.1",
            identity_signature_verified=False,
        )
        store.record_finalized_heartbeat(
            unsigned.model_copy(
                update={"identity_signature": "ed25519:" + key.sign(unsigned.signing_bytes()).hex()}
            )
        )


def test_disabled_runtime_cannot_initialize_or_submit_a_payout() -> None:
    runtime = ManagedRuntime(
        config=RuntimeConfig(
            active_network_id="aidn-testnet",
            active_chain_id="aidn-testnet-1",
        )
    )

    result = runtime.process_finalized_epoch(
        protocol_epoch=10,
        source_epoch_transition_operation_id="epoch-transition:10",
        period_start=START.isoformat(),
    )

    assert result.mode == "disabled"
    assert result.detail == "PARTICIPATION_RUNTIME_DISABLED"


def test_dry_run_persists_a_signed_batch_without_submitting(tmp_path) -> None:
    program_path = tmp_path / "program.toml"
    evidence_path = tmp_path / "evidence.sqlite"
    payout_path = tmp_path / "payout.sqlite"
    _write_program(program_path)
    _populate_evidence(evidence_path)
    submitter = _Submitter()
    runtime = ManagedRuntime(
        config=RuntimeConfig(
            enabled=True,
            mode="dry_run",
            active_network_id="aidn-testnet",
            active_chain_id="aidn-testnet-1",
            program_path=str(program_path),
            evidence_store_path=str(evidence_path),
            payout_store_path=str(payout_path),
            treasury_wallet="wallet-treasury",
            treasury_signer_secret_ref="secret://testnet/treasury",
        ),
        signer=lambda _: "ed25519:" + "ab" * 64,
        submitter=submitter,
    )

    result = runtime.process_finalized_epoch(
        protocol_epoch=10,
        source_epoch_transition_operation_id="epoch-transition:10",
        period_start=START.isoformat(),
    )

    assert result.mode == "dry_run"
    assert result.batch is not None and result.batch.transfers
    assert result.batch_status == "PENDING"
    assert result.detail == "PARTICIPATION_PAYOUT_DRY_RUN_NOT_SUBMITTED"
    assert submitter.submitted == []


def test_submit_mode_requires_an_explicit_treasury_integration(tmp_path) -> None:
    program_path = tmp_path / "program.toml"
    _write_program(program_path)
    config = RuntimeConfig(
        enabled=True,
        mode="submit",
        active_network_id="aidn-testnet",
        active_chain_id="aidn-testnet-1",
        program_path=str(program_path),
        evidence_store_path=str(tmp_path / "evidence.sqlite"),
        payout_store_path=str(tmp_path / "payout.sqlite"),
        treasury_wallet="wallet-treasury",
        treasury_signer_secret_ref="secret://testnet/treasury",
    )

    with pytest.raises(ValueError, match="TREASURY_INTEGRATION_REQUIRED"):
        ManagedRuntime(config=config)


def test_submit_mode_uses_the_same_persisted_batch_path(tmp_path) -> None:
    program_path = tmp_path / "program.toml"
    evidence_path = tmp_path / "evidence.sqlite"
    _write_program(program_path)
    _populate_evidence(evidence_path)
    submitter = _Submitter()
    runtime = ManagedRuntime(
        config=RuntimeConfig(
            enabled=True,
            mode="submit",
            active_network_id="aidn-testnet",
            active_chain_id="aidn-testnet-1",
            program_path=str(program_path),
            evidence_store_path=str(evidence_path),
            payout_store_path=str(tmp_path / "payout.sqlite"),
            treasury_wallet="wallet-treasury",
            treasury_signer_secret_ref="secret://testnet/treasury",
        ),
        signer=lambda _: "ed25519:" + "ab" * 64,
        submitter=submitter,
    )

    result = runtime.process_finalized_epoch(
        protocol_epoch=10,
        source_epoch_transition_operation_id="epoch-transition:10",
        period_start=START.isoformat(),
    )

    assert result.mode == "submit"
    assert result.batch_status == "FINALIZED"
    assert result.processed_operation_id == submitter.submitted[0].operation_id
