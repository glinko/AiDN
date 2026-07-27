"""Integration tests: SessionService <-> SessionFailureHandler wire-up."""


from aidn_hypervisor.session_failure.models import (
    FailureClass,
    RecoveryWindowConfig,
    ReputationEvent,
)
from aidn_hypervisor.session_failure.service import SessionFailureHandler
from aidn_hypervisor.sessions.service import SessionService
from aidn_hypervisor.sessions.store import SessionStore


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
