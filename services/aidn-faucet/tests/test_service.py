from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from aidn_faucet.models import FaucetChallengeRequest, FaucetClaimRequest, TransferSubmission
from aidn_faucet.policy import AccumulatingPoolPolicy, FixedDailyPolicy
from aidn_faucet.service import FaucetService, TreasurySigner
from aidn_faucet.store import FaucetStore
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from aidn_hypervisor.faucet_treasury import FaucetTreasuryManifest
from aidn_hypervisor.ledger.service import STANDARD_NETWORK_FEE_Q_ATOMS, LedgerOperationService


def _public_key(key: Ed25519PrivateKey) -> str:
    return "ed25519:" + key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    ).hex()


def _manifest(key: Ed25519PrivateKey) -> FaucetTreasuryManifest:
    public_key = _public_key(key)
    return FaucetTreasuryManifest(
        treasury_id="faucet-treasury-test-v1",
        network_id="aidn-localnet-1",
        chain_id="aidn-testnet-1",
        wallet_id="wallet-" + hashlib.sha256(public_key.encode()).hexdigest()[:12],
        wallet_public_key=public_key,
        creator_recovery_wallet="wallet-creator-recovery",
        genesis_allocation_q_atoms=10_000_000_000_000,
        policy_registry_hash="sha256:" + ("cd" * 32),
    )


class LedgerSubmitter:
    def __init__(
        self,
        ledger: LedgerOperationService,
        *,
        admitted_first: bool = False,
        rejected_first: bool = False,
    ) -> None:
        self.ledger = ledger
        self.admitted_first = admitted_first
        self.rejected_first = rejected_first
        self.submitted = []

    def next_sender_sequence(self, wallet_id: str) -> int:
        return self.ledger.wallet_next_sequence(wallet_id)

    def submit_transfer(self, envelope):
        self.submitted.append(envelope)
        if self.rejected_first:
            self.rejected_first = False
            return TransferSubmission(
                operation_id=envelope.operation_id,
                status="REJECTED",
                detail="consensus rejected test envelope",
            )
        if self.admitted_first:
            self.admitted_first = False
            return TransferSubmission(operation_id=envelope.operation_id, status="ADMITTED")
        self.ledger.apply_consensus_wallet_transfer(envelope)
        return TransferSubmission(operation_id=envelope.operation_id, status="FINALIZED")

    def reconcile_transfer(self, envelope):
        self.submitted.append(envelope)
        self.ledger.apply_consensus_wallet_transfer(envelope)
        return TransferSubmission(operation_id=envelope.operation_id, status="FINALIZED")


class AlwaysRejectedSubmitter(LedgerSubmitter):
    def submit_transfer(self, envelope):
        self.submitted.append(envelope)
        return TransferSubmission(
            operation_id=envelope.operation_id,
            status="REJECTED",
            detail="expired envelope",
        )

    def reconcile_transfer(self, envelope):
        return self.submit_transfer(envelope)


class FinalizedThenRejectedSubmitter(LedgerSubmitter):
    """Simulate a stale validator CheckTx response after canonical commit."""

    def submit_transfer(self, envelope):
        self.submitted.append(envelope)
        self.ledger.apply_consensus_wallet_transfer(envelope)
        return TransferSubmission(
            operation_id=envelope.operation_id,
            status="REJECTED",
            detail="duplicate_operation_id",
        )

    def reconcile_transfer(self, envelope):
        self.submitted.append(envelope)
        return TransferSubmission(operation_id=envelope.operation_id, status="FINALIZED")


def _service(
    tmp_path,
    *,
    policy,
    now,
    admitted_first=False,
    rejected_first=False,
    require_treasury_activation=False,
):
    treasury_key = Ed25519PrivateKey.generate()
    manifest = _manifest(treasury_key)
    ledger = LedgerOperationService()
    ledger.credit_wallet_q_atoms(
        wallet_id=manifest.wallet_id,
        amount_q_atoms=10_000_000_000_000 + 100_000,
    )
    service = FaucetService(
        manifest=manifest,
        signer=TreasurySigner(treasury_key, expected_public_key=manifest.wallet_public_key),
        policy=policy,
        store=FaucetStore(tmp_path / "faucet.sqlite"),
        submitter=LedgerSubmitter(
            ledger,
            admitted_first=admitted_first,
            rejected_first=rejected_first,
        ),
        require_treasury_activation=require_treasury_activation,
        now=lambda: now[0],
    )
    return service, ledger, now


def _claim(service: FaucetService, wallet_key: Ed25519PrivateKey, request_id: str):
    public_key = _public_key(wallet_key)
    wallet_id = "wallet-" + hashlib.sha256(public_key.encode()).hexdigest()[:12]
    challenge = service.issue_challenge(
        FaucetChallengeRequest(wallet_id=wallet_id, wallet_public_key=public_key)
    )
    signature = "ed25519:" + wallet_key.sign(challenge.signing_bytes()).hex()
    return service.claim(
        FaucetClaimRequest(
            request_id=request_id,
            wallet_id=wallet_id,
            wallet_public_key=public_key,
            challenge_id=challenge.challenge_id,
            wallet_signature=signature,
        )
    )


def test_fixed_daily_claim_uses_signed_wallet_transfer_and_is_idempotent(tmp_path) -> None:
    now = [datetime(2030, 1, 2, tzinfo=UTC)]
    service, ledger, _ = _service(
        tmp_path,
        policy=FixedDailyPolicy(amount_q=50),
        now=now,
    )
    wallet_key = Ed25519PrivateKey.generate()

    first = _claim(service, wallet_key, "agent-request-1")
    duplicate = _claim(service, wallet_key, "agent-request-1")
    second = _claim(service, wallet_key, "agent-request-2")

    assert first.status == "APPROVED"
    assert first.amount_q_atoms == 50_000_000
    assert duplicate.operation_id == first.operation_id
    assert second.status == "QUOTA_EXHAUSTED"
    assert len(ledger.snapshot_operations()) == 1
    assert len(service.submitter.submitted) == 1

    envelope = service.submitter.submitted[0]
    public_key = bytes.fromhex(service.manifest.wallet_public_key.removeprefix("ed25519:"))
    signature = bytes.fromhex(envelope.signatures[0].removeprefix("ed25519:"))
    Ed25519PublicKey.from_public_bytes(public_key).verify(signature, envelope.signing_bytes())
    assert ledger.wallet_q_atom_balance(envelope.payload["recipient_wallet"]) == 50_000_000
    assert ledger.recyclable_q_atom_balance() == STANDARD_NETWORK_FEE_Q_ATOMS


def test_claims_fail_closed_without_canonical_treasury_activation(tmp_path) -> None:
    now = [datetime(2030, 1, 2, tzinfo=UTC)]
    service, _, _ = _service(
        tmp_path,
        policy=FixedDailyPolicy(amount_q=50),
        now=now,
        require_treasury_activation=True,
    )

    assert service.status().treasury_activation_state == "UNVERIFIED"
    with pytest.raises(ValueError, match="FAUCET_TREASURY_NOT_ACTIVE"):
        _claim(service, Ed25519PrivateKey.generate(), "activation-required")


def test_admission_does_not_consume_quota_until_finality(tmp_path) -> None:
    now = [datetime(2030, 1, 2, tzinfo=UTC)]
    service, _, _ = _service(
        tmp_path,
        policy=FixedDailyPolicy(amount_q=50),
        now=now,
        admitted_first=True,
    )
    wallet_key = Ed25519PrivateKey.generate()

    pending = _claim(service, wallet_key, "agent-request-pending")
    assert pending.status == "PENDING_FINALITY"
    assert service.store.get_policy_state(service.policy.policy_id) == {}
    finalized = service.reconcile(pending.request_id)
    assert finalized.status == "APPROVED"
    assert service.store.get_policy_state(service.policy.policy_id) == {}


def test_rejected_submission_is_publicly_distinct_and_retries_exact_claim(tmp_path) -> None:
    now = [datetime(2030, 1, 2, tzinfo=UTC)]
    service, _, _ = _service(
        tmp_path,
        policy=FixedDailyPolicy(amount_q=50),
        now=now,
        rejected_first=True,
    )
    wallet_key = Ed25519PrivateKey.generate()

    rejected = _claim(service, wallet_key, "agent-request-rejected")
    assert rejected.status == "SUBMISSION_REJECTED"
    retried = service.reconcile(rejected.request_id)

    assert retried.status == "APPROVED"
    assert retried.operation_id == rejected.operation_id
    assert len(service.submitter.submitted) == 2
    assert service.submitter.submitted[0].model_dump() == service.submitter.submitted[1].model_dump()


def test_rejected_claim_does_not_block_new_claim_or_quota(tmp_path) -> None:
    now = [datetime(2030, 1, 2, tzinfo=UTC)]
    service, ledger, _ = _service(
        tmp_path,
        policy=FixedDailyPolicy(amount_q=50),
        now=now,
    )
    service.submitter = AlwaysRejectedSubmitter(ledger)
    wallet_key = Ed25519PrivateKey.generate()

    rejected = _claim(service, wallet_key, "expired-request")
    replacement = _claim(service, wallet_key, "replacement-request")

    assert rejected.status == "SUBMISSION_REJECTED"
    assert replacement.status == "SUBMISSION_REJECTED"
    assert replacement.operation_id != rejected.operation_id


def test_rejected_claim_reconciles_finality_before_rebroadcasting(tmp_path) -> None:
    now = [datetime(2030, 1, 2, tzinfo=UTC)]
    service, ledger, _ = _service(
        tmp_path,
        policy=FixedDailyPolicy(amount_q=50),
        now=now,
    )
    service.submitter = FinalizedThenRejectedSubmitter(ledger)
    wallet_key = Ed25519PrivateKey.generate()

    rejected = _claim(service, wallet_key, "finalized-before-reject")
    assert rejected.status == "SUBMISSION_REJECTED"

    reconciled = service.reconcile(rejected.request_id)

    assert reconciled.status == "APPROVED"
    assert reconciled.operation_id == rejected.operation_id
    assert len(ledger.snapshot_operations()) == 1


def test_pending_recovery_reconciles_only_the_serialized_treasury_transfer(tmp_path) -> None:
    now = [datetime(2030, 1, 2, tzinfo=UTC)]
    service, _, _ = _service(
        tmp_path,
        policy=FixedDailyPolicy(amount_q=50),
        now=now,
        admitted_first=True,
    )
    wallet_key = Ed25519PrivateKey.generate()

    pending = _claim(service, wallet_key, "background-recovery")
    recovered = service.reconcile_pending_claim()

    assert pending.status == "PENDING_FINALITY"
    assert recovered is not None
    assert recovered.status == "APPROVED"
    assert service.reconcile_pending_claim() is None


def test_accumulating_pool_resets_only_after_finalized_claim(tmp_path) -> None:
    now = [datetime(2030, 1, 2, tzinfo=UTC)]
    service, _, _ = _service(
        tmp_path,
        policy=AccumulatingPoolPolicy(rate_q=5, interval_seconds=60),
        now=now,
    )
    wallet_key = Ed25519PrivateKey.generate()

    now[0] += timedelta(seconds=60)
    first = _claim(service, wallet_key, "pool-request-1")
    assert first.status == "APPROVED"
    state = service.store.get_policy_state(service.policy.policy_id)
    assert state["generation"] == 1
    assert state["accumulated_q_atoms"] == 0

    now[0] += timedelta(seconds=60)
    second = _claim(service, wallet_key, "pool-request-2")
    assert second.status == "APPROVED"
    assert second.amount_q_atoms == 5_000_000
