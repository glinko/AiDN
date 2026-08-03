"""Integration tests: SessionService <-> SessionFailureHandler wire-up."""


import pytest

from aidn_hypervisor.main import _build_default_session_service
from aidn_hypervisor.persistence import FileStateStore
from aidn_hypervisor.queue import InMemoryTaskQueue
from aidn_hypervisor.scheduler import Scheduler
from aidn_hypervisor.service import HypervisorService
from aidn_hypervisor.session_failure.models import (
    EvidenceLevel,
    FailureClass,
    FailureEvidenceRecord,
    FailureReport,
    RecoveryWindowConfig,
    ReputationEvent,
)
from aidn_hypervisor.session_failure.service import SessionFailureHandler
from aidn_hypervisor.sessions.service import SessionService
from aidn_hypervisor.sessions.store import SessionStore
from aidn_hypervisor.state import HypervisorStateSnapshot


def _session_policy(**overrides):
    policy = {
        "minimum_deposit": 10.0,
        "recommended_deposit": 25.0,
        "idle_fee_per_minute": 1.0,
        "idle_timeout_seconds": 600,
        "max_concurrent_sessions": 5,
        "maximum_session_duration_seconds": 3600,
        "queue_policy": "busy",
        "minimum_session_fee": 2.0,
    }
    policy.update(overrides)
    return policy


def _session_service_with_failure_handler():
    """Create a SessionService wired to a SessionFailureHandler."""
    config = RecoveryWindowConfig(
        consumer_reconnect_timeout_seconds=60,
        provider_reconnect_timeout_seconds=60,
    )
    handler = SessionFailureHandler(recovery_config=config)
    return SessionService(
        SessionStore(),
        failure_handler=handler,
        recovery_config=config,
    ), handler


def test_default_session_service_restores_failure_evidence(tmp_path):
    state_store = FileStateStore(tmp_path / "hypervisor-state.json")
    evidence = FailureEvidenceRecord(
        session_id="session-default-restore",
        evidence_level=EvidenceLevel.OBSERVATIONAL,
        category="provider_timeout",
        detail="provider did not respond",
        recorded_at="2026-07-31T00:00:00+00:00",
        source="test",
    )
    report = FailureReport(
        session_id=evidence.session_id,
        failure_class=FailureClass.PROVIDER_DISCONNECTED,
        evidence_ids=[evidence.recorded_at],
        failure_timestamp=evidence.recorded_at,
        previous_status="active",
        resulting_status="recovering",
    )
    state_store.save(
        HypervisorStateSnapshot(
            session_failure_evidence=[evidence],
            session_failure_reports=[report],
        )
    )

    service = _build_default_session_service(state_store=state_store)

    assert service.failure_handler is not None
    assert service.failure_evidence_root(evidence.session_id) is not None
    assert service.failure_handler.get_failure_report(evidence.session_id) == report


class TestWireUpOpenClose:
    def test_open_session_registers_with_failure_handler(self):
        service, handler = _session_service_with_failure_handler()

        result = service.open_session(
            endpoint_id="ep-1",
            client_wallet="wallet-client",
            provider_wallet="wallet-provider",
            node_id="node-1",
            deposit_q=25.0,
            session_policy=_session_policy(),
        )

        sid = result.session.session_id
        assert handler.get_session_failure_status(sid) == "active"

    def test_close_session_unregisters_from_failure_handler(self):
        service, handler = _session_service_with_failure_handler()

        result = service.open_session(
            endpoint_id="ep-1",
            client_wallet="wallet-client",
            provider_wallet="wallet-provider",
            node_id="node-1",
            deposit_q=25.0,
            session_policy=_session_policy(),
        )

        sid = result.session.session_id
        service.close_session(sid)

        assert handler.get_session_failure_status(sid) is None

    def test_service_without_failure_handler_still_works(self):
        """Backwards compat: SessionService works without failure handler."""
        service = SessionService(SessionStore())

        result = service.open_session(
            endpoint_id="ep-1",
            client_wallet="wallet-client",
            provider_wallet="wallet-provider",
            node_id="node-1",
            deposit_q=25.0,
            session_policy=_session_policy(),
        )

        assert result.session.status == "active"
        service.close_session(result.session.session_id)
        session = service.store.get_session(result.session.session_id)
        assert session.status == "closed"


class TestClassifyFailureIntegration:
    def test_classify_provider_disconnected(self):
        service, handler = _session_service_with_failure_handler()

        result = service.open_session(
            endpoint_id="ep-1",
            client_wallet="wallet-client",
            provider_wallet="wallet-provider",
            node_id="node-1",
            deposit_q=25.0,
            session_policy=_session_policy(),
        )

        sid = result.session.session_id
        service.classify_session_failure(
            session_id=sid,
            failure_class=FailureClass.PROVIDER_DISCONNECTED,
        )

        # SessionService store should be synced via callback
        session = service.store.get_session(sid)
        assert session.status == "recovering"

        # Failure handler should also show recovering
        assert handler.get_session_failure_status(sid) == "recovering"

        # Failure report should exist
        report = handler.get_failure_report(sid)
        assert report is not None
        assert report.failure_class == FailureClass.PROVIDER_DISCONNECTED

    def test_classify_deposit_exhausted(self):
        service, handler = _session_service_with_failure_handler()

        result = service.open_session(
            endpoint_id="ep-1",
            client_wallet="wallet-client",
            provider_wallet="wallet-provider",
            node_id="node-1",
            deposit_q=25.0,
            session_policy=_session_policy(),
        )

        sid = result.session.session_id
        service.classify_session_failure(
            session_id=sid,
            failure_class=FailureClass.DEPOSIT_EXHAUSTED,
        )

        session = service.store.get_session(sid)
        assert session.status == "deposit_exhausted"


class TestRecoveryIntegration:
    def test_recover_session_from_failure(self):
        service, handler = _session_service_with_failure_handler()

        result = service.open_session(
            endpoint_id="ep-1",
            client_wallet="wallet-client",
            provider_wallet="wallet-provider",
            node_id="node-1",
            deposit_q=25.0,
            session_policy=_session_policy(),
        )

        sid = result.session.session_id
        service.classify_session_failure(
            session_id=sid,
            failure_class=FailureClass.PROVIDER_DISCONNECTED,
        )
        assert service.store.get_session(sid).status == "recovering"

        # Recover
        service.recover_session_from_failure(sid)
        assert service.store.get_session(sid).status == "active"
        assert handler.get_session_failure_status(sid) == "active"

    def test_recovery_metadata_survives_service_recreation(self):
        first, _handler = _session_service_with_failure_handler()
        result = first.open_session(
            endpoint_id="ep-1",
            client_wallet="wallet-client",
            provider_wallet="wallet-provider",
            node_id="node-1",
            deposit_q=25.0,
            session_policy=_session_policy(),
        )
        sid = result.session.session_id
        first.classify_session_failure(
            session_id=sid,
            failure_class=FailureClass.PROVIDER_DISCONNECTED,
        )
        persisted = first.store.get_session(sid)
        assert persisted.status == "recovering"
        assert persisted.failure_class == FailureClass.PROVIDER_DISCONNECTED.value
        assert persisted.recovery_deadline_at is not None

        restored_handler = SessionFailureHandler(
            recovery_config=RecoveryWindowConfig(
                consumer_reconnect_timeout_seconds=60,
                provider_reconnect_timeout_seconds=60,
            )
        )
        restored = SessionService(first.store, failure_handler=restored_handler)
        assert restored_handler.get_session_failure_status(sid) == "recovering"
        assert restored_handler.get_recovery_deadline(sid) == (
            persisted.recovery_deadline_at
        )
        restored.recover_session_from_failure(sid)
        assert restored.store.get_session(sid).status == "active"
        assert restored.store.get_session(sid).recovery_deadline_at is None

    def test_terminal_settlement_rejects_stale_recovery(self):
        service, _handler = _session_service_with_failure_handler()
        result = service.open_session(
            endpoint_id="ep-1",
            client_wallet="wallet-client",
            provider_wallet="wallet-provider",
            node_id="node-1",
            deposit_q=25.0,
            deposit_q_atoms=25_000_000,
            fixed_price_q_atoms=10_000_000,
            request_charge_ceiling_q_atoms=10_000_000,
            session_policy=_session_policy(),
            economic_profile="MVP-0001",
        )
        sid = result.session.session_id
        service.classify_session_failure(
            session_id=sid,
            failure_class=FailureClass.PROVIDER_DISCONNECTED,
        )
        service.mark_canonical_settlement_finalized(
            sid,
            settlement_evidence_root="sha256:forced-recovery",
            endpoint_payment_q_atoms=0,
            consumer_refund_q_atoms=25_000_000,
            close_reason="forced_endpoint_unavailable",
        )
        with pytest.raises(ValueError, match="already terminal"):
            service.recover_session_from_failure(sid)
        assert service.store.get_session(sid).status == "force_settled"
        assert _handler.get_session_failure_status(sid) is None

    def test_failure_evidence_round_trips_through_hypervisor_snapshot(self):
        service, _handler = _session_service_with_failure_handler()
        hypervisor = HypervisorService(
            queue=InMemoryTaskQueue(),
            scheduler=Scheduler(),
        )
        hypervisor.bind_external_services(
            registry_service=service.registry_service,
            session_service=service,
        )
        result = service.open_session(
            endpoint_id="ep-1",
            client_wallet="wallet-client",
            provider_wallet="wallet-provider",
            node_id="node-1",
            deposit_q=25.0,
            session_policy=_session_policy(),
        )
        sid = result.session.session_id
        service.classify_session_failure(
            session_id=sid,
            failure_class=FailureClass.PROVIDER_DISCONNECTED,
            details="provider transport lost",
        )
        original_root = service.failure_evidence_root(sid)
        assert original_root is not None
        snapshot = hypervisor.snapshot_state()
        assert snapshot.session_failure_evidence
        assert snapshot.session_failure_reports

        restored_handler = SessionFailureHandler(
            recovery_config=RecoveryWindowConfig(
                consumer_reconnect_timeout_seconds=60,
                provider_reconnect_timeout_seconds=60,
            )
        )
        restored_service = SessionService(
            SessionStore(),
            failure_handler=restored_handler,
        )
        restored_hypervisor = HypervisorService(
            queue=InMemoryTaskQueue(),
            scheduler=Scheduler(),
        )
        restored_hypervisor.bind_external_services(
            registry_service=restored_service.registry_service,
            session_service=restored_service,
        )
        restored_hypervisor.restore_state(snapshot)

        restored_report = restored_handler.get_failure_report(sid)
        assert restored_report is not None
        assert restored_report.failure_class == FailureClass.PROVIDER_DISCONNECTED
        assert restored_handler.evidence_store.has_evidence(sid)
        assert restored_service.failure_evidence_root(sid) == original_root

    def test_sweep_failure_recovery_expires_old_recovering(self):
        service, handler = _session_service_with_failure_handler()

        result = service.open_session(
            endpoint_id="ep-1",
            client_wallet="wallet-client",
            provider_wallet="wallet-provider",
            node_id="node-1",
            deposit_q=25.0,
            session_policy=_session_policy(),
        )

        sid = result.session.session_id
        service.classify_session_failure(
            session_id=sid,
            failure_class=FailureClass.PROVIDER_DISCONNECTED,
        )

        # Force deadline to the past
        handler._recovery_deadlines[sid] = "2020-01-01T00:00:00+00:00"

        expired = service.sweep_failure_recovery()
        assert sid in expired
        assert service.store.get_session(sid).status == "force_closing"


class TestReputationCallbackIntegration:
    def test_reputation_callback_receives_events(self):
        config = RecoveryWindowConfig()
        captured: list[ReputationEvent] = []

        handler = SessionFailureHandler(recovery_config=config)
        handler.set_reputation_callback(lambda evt: captured.append(evt))

        service = SessionService(
            SessionStore(),
            failure_handler=handler,
        )

        result = service.open_session(
            endpoint_id="ep-1",
            client_wallet="wallet-client",
            provider_wallet="wallet-provider",
            node_id="node-1",
            deposit_q=25.0,
            session_policy=_session_policy(),
        )

        sid = result.session.session_id
        service.classify_session_failure(
            session_id=sid,
            failure_class=FailureClass.RUNTIME_FAILURE,
        )

        # RUNTIME_FAILURE defaults to PROVIDER_AT_FAULT -> should trigger reputation
        assert len(captured) >= 1
        assert captured[0].failure_class == FailureClass.RUNTIME_FAILURE


class TestProxyFailureIntegration:
    def test_handle_proxy_failure(self):
        service, handler = _session_service_with_failure_handler()

        result = service.open_session(
            endpoint_id="ep-1",
            client_wallet="wallet-client",
            provider_wallet="wallet-provider",
            node_id="node-1",
            deposit_q=25.0,
            session_policy=_session_policy(),
        )

        sid = result.session.session_id
        service.handle_proxy_failure(
            session_id=sid,
            remote_endpoint_id="remote-ep-1",
            error="upstream connection refused",
        )

        assert service.store.get_session(sid).status == "recovering"
        report = handler.get_failure_report(sid)
        assert report.failure_class == FailureClass.UPSTREAM_PROXY_FAILURE
