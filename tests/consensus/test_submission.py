"""M7-S3: ConsensusService — submission lifecycle tests."""

import json

from aidn_hypervisor.consensus.abci import AIDNABCIApplication
from aidn_hypervisor.consensus.admission import AdmissionValidator
from aidn_hypervisor.consensus.cometbft import cometbft_transaction_hash
from aidn_hypervisor.consensus.finality import ConsensusFinalityEvidence
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.consensus.service import (
    ConsensusMode,
    ConsensusService,
    ConsensusServiceConfig,
    SubmissionStatus,
)
from aidn_hypervisor.consensus.state_store import ABCIStateStore, ABCIStateStoreError
from aidn_hypervisor.ledger.service import LedgerOperationService

# ---- helpers ----

def _make_envelope(**kw) -> LedgerOperationEnvelope:
    defaults = {
        "operation_type": "WALLET_TRANSFER",
        "origin_type": "wallet",
        "created_at": "2025-01-01T00:00:00Z",
        "payload": {},
        "signatures": ["sig1"],
    }
    defaults.update(kw)
    return LedgerOperationEnvelope(**defaults)


def _make_abci() -> AIDNABCIApplication:
    ledger = LedgerOperationService()
    admission = AdmissionValidator(current_time="2025-01-02T00:00:00Z")
    return AIDNABCIApplication(
        ledger_service=ledger,
        admission_validator=admission,
    )


class RecordingSubmissionTransport:
    def __init__(self, response: dict) -> None:
        self.response = response
        self.calls: list[tuple[bytes, int]] = []

    def broadcast_tx_sync(self, tx_data: bytes, *, timeout_seconds: int) -> dict:
        self.calls.append((tx_data, timeout_seconds))
        return self.response


# ---- submit accepted → admitted ----


def test_submit_accepted_to_admitted():
    abci = _make_abci()
    cfg = ConsensusServiceConfig(mode=ConsensusMode.NON_VALIDATOR)
    svc = ConsensusService(cfg, abci_app=abci)
    env = _make_envelope()
    rec = svc.submit_operation(env)
    assert rec.status == SubmissionStatus.ADMITTED
    assert rec.admitted_at is not None


# ---- submit rejected → failed ----


def test_submit_rejected_to_failed():
    abci = _make_abci()
    cfg = ConsensusServiceConfig(mode=ConsensusMode.NON_VALIDATOR)
    svc = ConsensusService(cfg, abci_app=abci)
    # expired envelope → admission rejects
    env = _make_envelope(expires_at="2024-01-01T00:00:00Z")
    rec = svc.submit_operation(env)
    assert rec.status == SubmissionStatus.FAILED
    assert rec.error is not None


# ---- submit without ABCI ----


def test_submit_without_abci():
    cfg = ConsensusServiceConfig(mode=ConsensusMode.NON_VALIDATOR)
    svc = ConsensusService(cfg)
    env = _make_envelope()
    rec = svc.submit_operation(env)
    assert rec.status == SubmissionStatus.PENDING


def test_submission_retains_exact_transaction_hash_for_finality_lookup():
    cfg = ConsensusServiceConfig(mode=ConsensusMode.NON_VALIDATOR)
    svc = ConsensusService(cfg)
    env = _make_envelope()

    svc.submit_operation(env)

    expected_bytes = json.dumps(env.model_dump(mode="json")).encode("utf-8")
    assert svc.transaction_hash_for_operation(env.operation_id) == cometbft_transaction_hash(
        expected_bytes
    )


def test_http_submission_transport_marks_only_checktx_admission():
    env = _make_envelope()
    transaction_bytes = json.dumps(env.model_dump(mode="json")).encode("utf-8")
    transport = RecordingSubmissionTransport(
        {
            "result": {
                "code": 0,
                "hash": cometbft_transaction_hash(transaction_bytes),
            }
        }
    )
    svc = ConsensusService(
        ConsensusServiceConfig(
            mode=ConsensusMode.NON_VALIDATOR,
            cometbft_endpoint="http://cometbft.test",
            submission_timeout_seconds=2.5,
        ),
        submission_transport=transport,
    )

    record = svc.submit_operation(env)

    assert record.status == SubmissionStatus.ADMITTED
    assert record.admitted_at is not None
    assert record.finalized_at is None
    assert transport.calls == [(transaction_bytes, 2)]


def test_http_submission_transport_rejects_checktx_failure():
    transport = RecordingSubmissionTransport(
        {"result": {"code": 12, "log": "invalid operation"}}
    )
    svc = ConsensusService(
        ConsensusServiceConfig(
            mode=ConsensusMode.NON_VALIDATOR,
            cometbft_endpoint="http://cometbft.test",
        ),
        submission_transport=transport,
    )

    record = svc.submit_operation(_make_envelope())

    assert record.status == SubmissionStatus.FAILED
    assert record.error == "invalid operation"
    assert svc.is_finalized(record.operation_id) is False


def test_submission_is_idempotent_for_the_same_operation_and_transaction():
    transport = RecordingSubmissionTransport({"result": {"code": 0}})
    svc = ConsensusService(
        ConsensusServiceConfig(
            mode=ConsensusMode.NON_VALIDATOR,
            cometbft_endpoint="http://cometbft.test",
        ),
        submission_transport=transport,
    )
    env = _make_envelope()

    first = svc.submit_operation(env)
    second = svc.submit_operation(env)

    assert second is first
    assert len(transport.calls) == 1
    assert svc.get_metrics()["total_submitted"] == 1


def test_retry_existing_submission_rebroadcasts_and_accepts_cometbft_cache():
    env = _make_envelope()
    transaction_bytes = json.dumps(env.model_dump(mode="json")).encode("utf-8")
    transport = RecordingSubmissionTransport(
        {
            "result": {
                "code": 0,
                "hash": cometbft_transaction_hash(transaction_bytes),
            }
        }
    )
    svc = ConsensusService(
        ConsensusServiceConfig(
            mode=ConsensusMode.NON_VALIDATOR,
            cometbft_endpoint="http://cometbft.test",
        ),
        submission_transport=transport,
    )

    first = svc.submit_operation(env)
    transport.response = {
        "error": {
            "code": -32603,
            "message": "Internal error",
            "data": "tx already exists in cache",
        }
    }
    second = svc.submit_operation(env, retry_existing=True)

    assert second is first
    assert second.status == SubmissionStatus.ADMITTED
    assert second.error is None
    assert len(transport.calls) == 2
    assert svc.get_metrics()["total_submitted"] == 1
    assert svc.get_metrics()["total_failed"] == 0


def test_reconcile_finality_requires_matching_chain_and_is_idempotent():
    transport = RecordingSubmissionTransport({"result": {"code": 0}})
    svc = ConsensusService(
        ConsensusServiceConfig(
            mode=ConsensusMode.NON_VALIDATOR,
            chain_id="aidn-testnet-1",
            cometbft_endpoint="http://cometbft.test",
        ),
        submission_transport=transport,
    )
    env = _make_finalizable_envelope()
    svc.submit_operation(env)
    evidence = ConsensusFinalityEvidence(
        operation_id=env.operation_id,
        chain_id="aidn-testnet-1",
        block_height=17,
        block_id="block-17",
        app_hash="app-17",
        commit_hash="commit-17",
        finalized_at="2030-01-01T00:00:00Z",
        verifier_id="test-source",
    )

    class Source:
        def finality_evidence(self, operation_id: str):
            return evidence

    assert svc.reconcile_finality(env.operation_id, finality_source=Source()) is not None
    assert svc.reconcile_finality(env.operation_id, finality_source=Source()) is not None
    assert svc.is_finalized(env.operation_id)
    assert svc.get_submission(env.operation_id).status == SubmissionStatus.FINALIZED
    assert svc.get_metrics()["total_finalized"] == 1


def _make_finalizable_envelope(**kw) -> LedgerOperationEnvelope:
    defaults = {
        "operation_type": "REGISTRY_UPSERT",
        "origin_type": "protocol",
        "created_at": "2025-01-01T00:00:00Z",
        "payload": {"test": True},
    }
    defaults.update(kw)
    return LedgerOperationEnvelope(**defaults)


# ---- resubmit ----


def test_resubmit_pending():
    cfg = ConsensusServiceConfig(mode=ConsensusMode.NON_VALIDATOR)
    svc = ConsensusService(cfg)
    env = _make_finalizable_envelope()
    svc.submit_operation(env)
    count = svc.resubmit_pending()
    assert count == 1
    rec = svc.get_submission(env.operation_id)
    assert rec.retry_count == 1
    assert rec.status == SubmissionStatus.PENDING


def test_resubmit_max_retries():
    cfg = ConsensusServiceConfig(mode=ConsensusMode.NON_VALIDATOR)
    svc = ConsensusService(cfg)
    env = _make_finalizable_envelope()
    svc.submit_operation(env)
    # resubmit 4 times with max_retries=3 → only 3 succeed
    svc.resubmit_pending(max_retries=3)
    svc.resubmit_pending(max_retries=3)
    svc.resubmit_pending(max_retries=3)
    count = svc.resubmit_pending(max_retries=3)
    assert count == 0  # retry_count == 3, no more allowed


def test_resubmit_no_effect_when_finalized():
    cfg = ConsensusServiceConfig(mode=ConsensusMode.DISABLED)
    svc = ConsensusService(cfg)
    env = _make_envelope()
    svc.submit_operation(env)
    count = svc.resubmit_pending()
    assert count == 0  # already finalized, not PENDING/FAILED


# ---- monitor_inclusion ----


def test_monitor_inclusion_returns_pending():
    cfg = ConsensusServiceConfig(mode=ConsensusMode.NON_VALIDATOR)
    svc = ConsensusService(cfg)
    env = _make_envelope()
    svc.submit_operation(env)
    pending = svc.monitor_inclusion()
    assert env.operation_id in pending


def test_monitor_inclusion_empty_when_all_finalized():
    cfg = ConsensusServiceConfig(mode=ConsensusMode.DISABLED)
    svc = ConsensusService(cfg)
    svc.submit_operation(_make_envelope())
    pending = svc.monitor_inclusion()
    assert len(pending) == 0


# ---- propose_block ----


def test_propose_block_validator():
    abci = _make_abci()
    cfg = ConsensusServiceConfig(
        mode=ConsensusMode.VALIDATOR,
        validator_pubkey="pk-v",
    )
    svc = ConsensusService(cfg, abci_app=abci)
    env = _make_finalizable_envelope()
    tx_bytes = json.dumps(env.model_dump(mode="json")).encode("utf-8")
    result = svc.propose_block(
        txs=[tx_bytes],
        block_height=1,
        block_hash=b"\x01" * 32,
    )
    assert result["block_height"] == 1
    assert result["code"] == "ok"
    assert result["executed"] == 1


def test_propose_block_non_validator_error():
    cfg = ConsensusServiceConfig(mode=ConsensusMode.NON_VALIDATOR)
    svc = ConsensusService(cfg)
    result = svc.propose_block(txs=[], block_height=1, block_hash=b"\x01" * 32)
    assert "error" in result


def test_propose_block_no_abci_error():
    cfg = ConsensusServiceConfig(
        mode=ConsensusMode.VALIDATOR,
        validator_pubkey="pk-v",
    )
    svc = ConsensusService(cfg)
    result = svc.propose_block(txs=[], block_height=1, block_hash=b"\x01" * 32)
    assert "error" in result


# ---- sign_block ----


def test_sign_block_validator():
    cfg = ConsensusServiceConfig(
        mode=ConsensusMode.VALIDATOR,
        validator_pubkey="pk-v",
    )
    svc = ConsensusService(cfg)
    result = svc.sign_block(b"\xaa" * 32)
    assert result["signed"] is True
    assert result["validator"] == "pk-v"


def test_sign_block_non_validator_error():
    cfg = ConsensusServiceConfig(mode=ConsensusMode.NON_VALIDATOR)
    svc = ConsensusService(cfg)
    result = svc.sign_block(b"\xaa" * 32)
    assert "error" in result


# ---- record_missed_block ----


def test_record_missed_block():
    cfg = ConsensusServiceConfig(
        mode=ConsensusMode.VALIDATOR,
        validator_pubkey="pk-v",
    )
    svc = ConsensusService(cfg)
    svc.record_missed_block()
    svc.record_missed_block()
    assert svc._missed_blocks == 2


# ---- block proposal marks txs finalized ----


def test_block_proposal_marks_txs_finalized():
    abci = _make_abci()
    cfg = ConsensusServiceConfig(
        mode=ConsensusMode.VALIDATOR,
        validator_pubkey="pk-v",
    )
    svc = ConsensusService(cfg, abci_app=abci)
    env = _make_finalizable_envelope()
    tx_bytes = json.dumps(env.model_dump(mode="json")).encode("utf-8")
    svc.propose_block(txs=[tx_bytes], block_height=1, block_hash=b"\x01" * 32)
    assert svc.is_finalized(env.operation_id)


def test_block_proposal_does_not_finalize_rejected_transaction():
    abci = _make_abci()
    svc = ConsensusService(
        ConsensusServiceConfig(mode=ConsensusMode.VALIDATOR, validator_pubkey="pk-v"),
        abci_app=abci,
    )
    expired = _make_envelope(expires_at="2025-01-01T00:00:00Z")
    transaction = json.dumps(expired.model_dump(mode="json")).encode("utf-8")

    result = svc.propose_block(txs=[transaction], block_height=1, block_hash=b"x" * 32)

    assert result["code"] == "ok"
    assert result["executed"] == 0
    assert svc.is_finalized(expired.operation_id) is False
    assert svc.get_submission(expired.operation_id).status == SubmissionStatus.FAILED


def test_block_proposal_failure_does_not_mark_operation_finalized(tmp_path, monkeypatch):
    store = ABCIStateStore(tmp_path / "abci")
    abci = AIDNABCIApplication(
        ledger_service=LedgerOperationService(),
        admission_validator=AdmissionValidator(current_time="2025-01-02T00:00:00Z"),
        state_store=store,
    )
    monkeypatch.setattr(
        store,
        "persist",
        lambda state: (_ for _ in ()).throw(ABCIStateStoreError("disk full")),
    )
    svc = ConsensusService(
        ConsensusServiceConfig(mode=ConsensusMode.VALIDATOR, validator_pubkey="pk-v"),
        abci_app=abci,
    )
    envelope = _make_finalizable_envelope()
    transaction = json.dumps(envelope.model_dump(mode="json")).encode("utf-8")

    result = svc.propose_block(txs=[transaction], block_height=1, block_hash=b"y" * 32)

    assert result["code"] == "internal"
    assert result["app_hash"] == ""
    assert svc.is_finalized(envelope.operation_id) is False
    assert svc.get_submission(envelope.operation_id).status == SubmissionStatus.FAILED


# ---- block proposal increments counter ----


def test_block_proposal_increments_counter():
    abci = _make_abci()
    cfg = ConsensusServiceConfig(
        mode=ConsensusMode.VALIDATOR,
        validator_pubkey="pk-v",
    )
    svc = ConsensusService(cfg, abci_app=abci)
    env = _make_finalizable_envelope()
    tx_bytes = json.dumps(env.model_dump(mode="json")).encode("utf-8")
    svc.propose_block(txs=[tx_bytes], block_height=1, block_hash=b"\x01" * 32)
    assert svc._blocks_proposed == 1
    assert svc._participation_count == 1


# ---- snapshot and restore ----


def test_snapshot_and_restore():
    abci = _make_abci()
    cfg = ConsensusServiceConfig(mode=ConsensusMode.NON_VALIDATOR)
    svc = ConsensusService(cfg, abci_app=abci)
    snap = svc.snapshot_state()
    assert snap["config"]["node_id"] == "local-node"
    assert snap["abci_snapshot"] is not None
    ok = svc.restore_state(snap)
    assert ok is True


# ---- submission retry count increments ----


def test_submission_retry_count_increments():
    cfg = ConsensusServiceConfig(mode=ConsensusMode.NON_VALIDATOR)
    svc = ConsensusService(cfg)
    env = _make_envelope()
    svc.submit_operation(env)
    svc.resubmit_pending()
    svc.resubmit_pending()
    rec = svc.get_submission(env.operation_id)
    assert rec.retry_count == 2


# ---- submission status transitions ----


def test_submission_status_transitions():
    cfg = ConsensusServiceConfig(mode=ConsensusMode.NON_VALIDATOR)
    svc = ConsensusService(cfg)
    env = _make_envelope()
    svc.submit_operation(env)
    rec = svc.get_submission(env.operation_id)
    assert rec.status == SubmissionStatus.PENDING
    svc.mark_included(env.operation_id, 1)
    assert rec.status == SubmissionStatus.INCLUDED
    svc.mark_finalized(env.operation_id, 1)
    assert rec.status == SubmissionStatus.FINALIZED


# ---- multiple submissions independent ----


def test_multiple_submissions_independent():
    cfg = ConsensusServiceConfig(mode=ConsensusMode.DISABLED)
    svc = ConsensusService(cfg)
    env1 = _make_envelope()
    env2 = _make_envelope(origin_type="protocol")
    svc.submit_operation(env1)
    svc.submit_operation(env2)
    assert svc.get_submission(env1.operation_id) is not None
    assert svc.get_submission(env2.operation_id) is not None
    assert env1.operation_id != env2.operation_id
    assert svc._total_submitted == 2
