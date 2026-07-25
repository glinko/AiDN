"""Tests for session_failure.poller — SessionFailurePoller (RFC-0060 timeout enforcement)."""

from datetime import datetime, timedelta, timezone

import pytest

from aidn_hypervisor.session_failure.models import (
    FailureClass,
    RecoveryWindowConfig,
)
from aidn_hypervisor.session_failure.poller import SessionFailurePoller
from aidn_hypervisor.session_failure.service import SessionFailureHandler


@pytest.fixture
def handler():
    config = RecoveryWindowConfig(
        consumer_reconnect_timeout_seconds=60,
        provider_reconnect_timeout_seconds=60,
    )
    return SessionFailureHandler(recovery_config=config)


@pytest.fixture
def poller(handler):
    return SessionFailurePoller(handler)


class TestPollerSweepRecovery:
    def test_sweep_expires_recovered_session(self, handler, poller):
        handler.register_session("sess-001", "active")
        handler.classify_failure(
            session_id="sess-001",
            failure_class=FailureClass.PROVIDER_DISCONNECTED,
        )
        # Force deadline to the past
        handler._recovery_deadlines["sess-001"] = "2020-01-01T00:00:00+00:00"

        results = poller.sweep_expired_recoveries()
        assert len(results) == 1
        assert handler.get_session_failure_status("sess-001") == "force_closing"

    def test_sweep_skips_non_expired_session(self, handler, poller):
        handler.register_session("sess-001", "active")
        handler.classify_failure(
            session_id="sess-001",
            failure_class=FailureClass.PROVIDER_DISCONNECTED,
        )
        # Deadline is in the future (just set)
        results = poller.sweep_expired_recoveries()
        assert len(results) == 0
        assert handler.get_session_failure_status("sess-001") == "recovering"

    def test_sweep_skips_non_recovering_sessions(self, handler, poller):
        handler.register_session("sess-001", "active")
        results = poller.sweep_expired_recoveries()
        assert len(results) == 0


class TestPollerSweepTerminal:
    def test_sweep_skips_terminal_sessions(self, handler, poller):
        handler.register_session("sess-001", "force_settled")
        results = poller.sweep_expired_recoveries()
        assert len(results) == 0
