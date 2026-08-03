"""M7-S3: ConsensusService — core behaviour tests."""

import pytest

from aidn_hypervisor.consensus.abci import AIDNABCIApplication
from aidn_hypervisor.consensus.admission import AdmissionValidator
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.consensus.service import (
    ConsensusMode,
    ConsensusService,
    ConsensusServiceConfig,
    SubmissionRecord,
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


# ---- disabled mode ----


def test_service_disabled_mode_finalizes_locally():
    cfg = ConsensusServiceConfig(mode=ConsensusMode.DISABLED)
    svc = ConsensusService(cfg)
    env = _make_envelope()
    rec = svc.submit_operation(env)
    assert rec.status == SubmissionStatus.FINALIZED
    assert svc.is_finalized(env.operation_id)
    assert svc._total_finalized == 1


# ---- non-validator mode ----


def test_service_non_validator_mode_pending():
    cfg = ConsensusServiceConfig(mode=ConsensusMode.NON_VALIDATOR)
    svc = ConsensusService(cfg)
    env = _make_envelope()
    rec = svc.submit_operation(env)
    # Without ABCI, stays PENDING
    assert rec.status == SubmissionStatus.PENDING


# ---- validator mode ----


def test_service_validator_mode():
    cfg = ConsensusServiceConfig(
        mode=ConsensusMode.VALIDATOR,
        validator_pubkey="pk-abc",
    )
    svc = ConsensusService(cfg)
    assert svc.is_validator is True
    assert svc.is_enabled is True


# ---- submit_operation_returns_record ----


def test_submit_operation_returns_record():
    cfg = ConsensusServiceConfig(mode=ConsensusMode.DISABLED)
    svc = ConsensusService(cfg)
    env = _make_envelope()
    rec = svc.submit_operation(env)
    assert isinstance(rec, SubmissionRecord)
    assert rec.operation_id == env.operation_id


# ---- get_submission ----


def test_get_submission_exists():
    cfg = ConsensusServiceConfig(mode=ConsensusMode.DISABLED)
    svc = ConsensusService(cfg)
    env = _make_envelope()
    svc.submit_operation(env)
    rec = svc.get_submission(env.operation_id)
    assert rec is not None
    assert rec.operation_id == env.operation_id


def test_get_submission_missing():
    cfg = ConsensusServiceConfig(mode=ConsensusMode.DISABLED)
    svc = ConsensusService(cfg)
    rec = svc.get_submission("does-not-exist")
    assert rec is None


# ---- list_submissions ----


def test_list_submissions_all():
    cfg = ConsensusServiceConfig(mode=ConsensusMode.DISABLED)
    svc = ConsensusService(cfg)
    svc.submit_operation(_make_envelope())
    svc.submit_operation(_make_envelope(origin_type="protocol"))
    assert len(svc.list_submissions()) == 2


def test_list_submissions_filtered():
    cfg = ConsensusServiceConfig(mode=ConsensusMode.DISABLED)
    svc = ConsensusService(cfg)
    svc.submit_operation(_make_envelope())
    # non-validator to get PENDING
    cfg2 = ConsensusServiceConfig(mode=ConsensusMode.NON_VALIDATOR)
    svc2 = ConsensusService(cfg2)
    svc2.submit_operation(_make_envelope())
    assert len(svc2.list_submissions(status=SubmissionStatus.PENDING)) == 1
    assert len(svc2.list_submissions(status=SubmissionStatus.FINALIZED)) == 0


def test_list_submissions_limited():
    cfg = ConsensusServiceConfig(mode=ConsensusMode.DISABLED)
    svc = ConsensusService(cfg)
    for i in range(5):
        svc.submit_operation(_make_envelope(payload={"n": i}))
    assert len(svc.list_submissions(limit=2)) == 2


# ---- mark_included / mark_finalized ----


def test_mark_included():
    cfg = ConsensusServiceConfig(mode=ConsensusMode.NON_VALIDATOR)
    svc = ConsensusService(cfg)
    env = _make_envelope()
    svc.submit_operation(env)
    ok = svc.mark_included(env.operation_id, 42)
    assert ok is True
    rec = svc.get_submission(env.operation_id)
    assert rec.status == SubmissionStatus.INCLUDED
    assert rec.block_height == 42


def test_mark_finalized():
    cfg = ConsensusServiceConfig(mode=ConsensusMode.NON_VALIDATOR)
    svc = ConsensusService(cfg)
    env = _make_envelope()
    svc.submit_operation(env)
    ok = svc.mark_finalized(env.operation_id, 42)
    assert ok is True
    rec = svc.get_submission(env.operation_id)
    assert rec.status == SubmissionStatus.FINALIZED
    assert svc.is_finalized(env.operation_id)


def test_is_finalized_true():
    cfg = ConsensusServiceConfig(mode=ConsensusMode.DISABLED)
    svc = ConsensusService(cfg)
    env = _make_envelope()
    svc.submit_operation(env)
    assert svc.is_finalized(env.operation_id)


def test_is_finalized_false():
    cfg = ConsensusServiceConfig(mode=ConsensusMode.DISABLED)
    svc = ConsensusService(cfg)
    assert not svc.is_finalized("nonexistent")


# ---- submit unknown ----


def test_submit_unknown_operation():
    cfg = ConsensusServiceConfig(mode=ConsensusMode.NON_VALIDATOR)
    svc = ConsensusService(cfg)
    assert svc.get_submission("no-such-id") is None


# ---- metrics ----


def test_metrics_disabled_mode():
    cfg = ConsensusServiceConfig(mode=ConsensusMode.DISABLED)
    svc = ConsensusService(cfg)
    svc.submit_operation(_make_envelope())
    m = svc.get_metrics()
    assert m["mode"] == "disabled"
    assert m["total_submitted"] == 1
    assert m["total_finalized"] == 1
    assert m["pending_count"] == 0


def test_metrics_validator_mode():
    cfg = ConsensusServiceConfig(
        mode=ConsensusMode.VALIDATOR,
        validator_pubkey="pk-v",
    )
    svc = ConsensusService(cfg)
    m = svc.get_metrics()
    assert m["mode"] == "validator"
    assert m["participation_rate"] == 1.0


def test_metrics_non_validator_mode():
    cfg = ConsensusServiceConfig(mode=ConsensusMode.NON_VALIDATOR)
    svc = ConsensusService(cfg)
    m = svc.get_metrics()
    assert m["mode"] == "non_validator"


# ---- participation rate ----


def test_participation_rate_perfect():
    cfg = ConsensusServiceConfig(
        mode=ConsensusMode.VALIDATOR,
        validator_pubkey="pk-v",
    )
    svc = ConsensusService(cfg)
    svc._participation_count = 10
    svc._missed_blocks = 0
    m = svc.get_metrics()
    assert m["participation_rate"] == 1.0


def test_participation_rate_with_misses():
    cfg = ConsensusServiceConfig(
        mode=ConsensusMode.VALIDATOR,
        validator_pubkey="pk-v",
    )
    svc = ConsensusService(cfg)
    svc._participation_count = 8
    svc._missed_blocks = 2
    m = svc.get_metrics()
    assert m["participation_rate"] == pytest.approx(0.8, abs=0.001)


# ---- config defaults ----


def test_config_defaults():
    cfg = ConsensusServiceConfig()
    assert cfg.node_id == "local-node"
    assert cfg.mode == ConsensusMode.NON_VALIDATOR
    assert cfg.chain_id == "aidn-localnet-1"
    assert cfg.gas_limit == 1_000_000
    assert cfg.max_retries == 3
    assert cfg.abci_retained_snapshots == 8
    assert cfg.abci_snapshot_lease_seconds == 1800


def test_validator_abci_bootstrap_requires_validator_mode_and_durable_path(tmp_path):
    service = ConsensusService(ConsensusServiceConfig(mode=ConsensusMode.NON_VALIDATOR))
    with pytest.raises(ValueError, match="only validator"):
        service.bootstrap_validator_abci(ledger_service=LedgerOperationService())

    validator = ConsensusService(ConsensusServiceConfig(mode=ConsensusMode.VALIDATOR))
    with pytest.raises(ValueError, match="durable state path"):
        validator.bootstrap_validator_abci(ledger_service=LedgerOperationService())

    ledger = LedgerOperationService()
    configured = ConsensusService(
        ConsensusServiceConfig(
            mode=ConsensusMode.VALIDATOR,
            abci_state_path=str(tmp_path / "abci"),
            abci_listen_port=0,
        )
    )
    application = configured.bootstrap_validator_abci(ledger_service=ledger)
    assert application.ledger is ledger
    assert application._state_store is not None
    assert application._state_store.retained_snapshots == 8
    assert application._state_store.snapshot_lease_seconds == 1800
    assert configured.bootstrap_validator_abci(ledger_service=ledger) is application
    with pytest.raises(ValueError, match="another Ledger"):
        configured.bootstrap_validator_abci(ledger_service=LedgerOperationService())


def test_validator_abci_server_lifecycle(tmp_path):
    service = ConsensusService(
        ConsensusServiceConfig(
            mode=ConsensusMode.VALIDATOR,
            abci_state_path=str(tmp_path / "abci"),
            abci_listen_port=0,
        )
    )
    with pytest.raises(ValueError, match="bootstrap"):
        service.start_validator_abci_server()

    service.bootstrap_validator_abci(ledger_service=LedgerOperationService())
    server = service.start_validator_abci_server()
    assert server.is_running
    assert service.start_validator_abci_server() is server
    service.stop_validator_abci_server()
    assert not server.is_running
