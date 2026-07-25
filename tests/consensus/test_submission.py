"""M7-S3: ConsensusService — submission lifecycle tests."""

import json

import pytest

from aidn_hypervisor.consensus.abci import AIDNABCIApplication
from aidn_hypervisor.consensus.admission import AdmissionValidator
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.consensus.service import (
    ConsensusMode,
    ConsensusService,
    ConsensusServiceConfig,
    SubmissionStatus,
)
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


# ---- resubmit ----


def test_resubmit_pending():
    cfg = ConsensusServiceConfig(mode=ConsensusMode.NON_VALIDATOR)
    svc = ConsensusService(cfg)
    env = _make_envelope()
    svc.submit_operation(env)
    count = svc.resubmit_pending()
    assert count == 1
    rec = svc.get_submission(env.operation_id)
    assert rec.retry_count == 1
    assert rec.status == SubmissionStatus.PENDING


def test_resubmit_max_retries():
    cfg = ConsensusServiceConfig(mode=ConsensusMode.NON_VALIDATOR)
    svc = ConsensusService(cfg)
    env = _make_envelope()
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
    env = _make_envelope()
    tx_bytes = json.dumps(env.model_dump(mode="json")).encode("utf-8")
    result = svc.propose_block(
        txs=[tx_bytes],
        block_height=1,
        block_hash=b"\x01" * 32,
    )
    assert result["block_height"] == 1
    assert result["code"] == "ok"


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
    env = _make_envelope()
    tx_bytes = json.dumps(env.model_dump(mode="json")).encode("utf-8")
    svc.propose_block(txs=[tx_bytes], block_height=1, block_hash=b"\x01" * 32)
    assert svc.is_finalized(env.operation_id)


# ---- block proposal increments counter ----


def test_block_proposal_increments_counter():
    abci = _make_abci()
    cfg = ConsensusServiceConfig(
        mode=ConsensusMode.VALIDATOR,
        validator_pubkey="pk-v",
    )
    svc = ConsensusService(cfg, abci_app=abci)
    env = _make_envelope()
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
