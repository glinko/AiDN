from datetime import datetime, timezone

import pytest

from aidn_hypervisor.sessions.service import SessionService
from aidn_hypervisor.sessions.store import SessionStore


def _session_service() -> SessionService:
    return SessionService(SessionStore())


def _session_policy(**overrides):
    policy = {
        "minimum_deposit": 10.0,
        "recommended_deposit": 25.0,
        "idle_fee_per_minute": 1.0,
        "idle_timeout_seconds": 600,
        "max_concurrent_sessions": 1,
        "maximum_session_duration_seconds": 3600,
        "queue_policy": "busy",
        "minimum_session_fee": 2.0,
    }
    policy.update(overrides)
    return policy


def test_open_session_rejects_deposit_below_minimum() -> None:
    service = _session_service()

    with pytest.raises(ValueError, match="minimum deposit"):
        service.open_session(
            endpoint_id="ep-1",
            client_wallet="wallet-client",
            provider_wallet="wallet-provider",
            node_id="node-1",
            deposit_q=9.0,
            session_policy=_session_policy(),
        )


def test_open_session_rejects_when_endpoint_slots_are_full_and_policy_is_busy() -> None:
    service = _session_service()
    policy = _session_policy(max_concurrent_sessions=1, queue_policy="busy")

    first = service.open_session(
        endpoint_id="ep-1",
        client_wallet="wallet-a",
        provider_wallet="wallet-provider",
        node_id="node-1",
        deposit_q=10.0,
        session_policy=policy,
    )

    assert first.session.status == "active"
    assert first.session.reserved_slot_index == 0
    with pytest.raises(ValueError, match="busy"):
        service.open_session(
            endpoint_id="ep-1",
            client_wallet="wallet-b",
            provider_wallet="wallet-provider",
            node_id="node-1",
            deposit_q=10.0,
            session_policy=policy,
        )


def test_close_session_releases_slot_for_next_waiting_session() -> None:
    service = _session_service()
    policy = _session_policy(max_concurrent_sessions=1, queue_policy="queue")

    first = service.open_session(
        endpoint_id="ep-1",
        client_wallet="wallet-a",
        provider_wallet="wallet-provider",
        node_id="node-1",
        deposit_q=10.0,
        session_policy=policy,
    )
    second = service.open_session(
        endpoint_id="ep-1",
        client_wallet="wallet-b",
        provider_wallet="wallet-provider",
        node_id="node-1",
        deposit_q=10.0,
        session_policy=policy,
    )

    closed = service.close_session(first.session.session_id)
    promoted = service.get_session(second.session.session_id)

    assert closed.session.status == "closed"
    assert promoted.session.status == "active"
    assert promoted.session.reserved_slot_index == 0


def test_close_session_applies_minimum_session_fee_when_no_requests_were_sent() -> None:
    service = _session_service()

    opened = service.open_session(
        endpoint_id="ep-1",
        client_wallet="wallet-a",
        provider_wallet="wallet-provider",
        node_id="node-1",
        deposit_q=10.0,
        session_policy=_session_policy(minimum_session_fee=2.0),
    )

    closed = service.close_session(opened.session.session_id)

    assert closed.deposit.status == "released"
    assert closed.deposit.consumed_q == 2.0
    assert closed.deposit.refunded_q == 8.0
    assert closed.settlement is not None
    assert closed.settlement.no_request is True
    assert closed.settlement.charged_q == 2.0
    assert closed.settlement.refunded_q == 8.0


def test_close_session_refunds_remaining_balance_after_usage_charge() -> None:
    service = _session_service()

    opened = service.open_session(
        endpoint_id="ep-1",
        client_wallet="wallet-a",
        provider_wallet="wallet-provider",
        node_id="node-1",
        deposit_q=20.0,
        session_policy=_session_policy(minimum_session_fee=2.0),
    )
    service.record_usage_charge(opened.session.session_id, amount_q=6.5)

    closed = service.close_session(opened.session.session_id)

    assert closed.deposit.status == "released"
    assert closed.deposit.consumed_q == 6.5
    assert closed.deposit.refunded_q == 13.5
    assert closed.settlement is not None
    assert closed.settlement.no_request is False
    assert closed.settlement.usage_charged_q == 6.5
    assert closed.settlement.charged_q == 6.5
    assert closed.settlement.refunded_q == 13.5


def test_record_usage_charge_rejects_charge_above_locked_deposit() -> None:
    service = _session_service()

    opened = service.open_session(
        endpoint_id="ep-1",
        client_wallet="wallet-a",
        provider_wallet="wallet-provider",
        node_id="node-1",
        deposit_q=10.0,
        session_policy=_session_policy(),
    )

    with pytest.raises(ValueError, match="deposit"):
        service.record_usage_charge(opened.session.session_id, amount_q=11.0)


def test_sweep_idle_sessions_auto_closes_timed_out_session_with_idle_fee() -> None:
    service = _session_service()

    opened = service.open_session(
        endpoint_id="ep-1",
        client_wallet="wallet-a",
        provider_wallet="wallet-provider",
        node_id="node-1",
        deposit_q=30.0,
        session_policy=_session_policy(idle_fee_per_minute=1.0, idle_timeout_seconds=600),
    )
    service.record_usage_charge(opened.session.session_id, amount_q=6.0)
    service.store.save_session(
        service.get_session(opened.session.session_id).session.model_copy(
            update={
                "last_activity_at": "2026-07-01T00:00:00+00:00",
                "idle_deadline_at": "2026-07-01T00:10:00+00:00",
            }
        )
    )

    swept = service.sweep_idle_sessions(
        now=datetime(2026, 7, 1, 0, 10, 0, tzinfo=timezone.utc)
    )

    assert len(swept) == 1
    assert swept[0].session.close_reason == "idle_timeout"
    assert swept[0].settlement is not None
    assert swept[0].settlement.idle_fee_charged_q == 10.0
    assert swept[0].settlement.charged_q == 16.0
    assert swept[0].deposit.refunded_q == 14.0


def test_sweep_idle_sessions_keeps_no_request_minimum_fee_rule() -> None:
    service = _session_service()

    opened = service.open_session(
        endpoint_id="ep-1",
        client_wallet="wallet-a",
        provider_wallet="wallet-provider",
        node_id="node-1",
        deposit_q=10.0,
        session_policy=_session_policy(
            minimum_session_fee=2.0,
            idle_fee_per_minute=1.0,
            idle_timeout_seconds=600,
        ),
    )
    service.store.save_session(
        opened.session.model_copy(
            update={
                "last_activity_at": "2026-07-01T00:00:00+00:00",
                "idle_deadline_at": "2026-07-01T00:10:00+00:00",
            }
        )
    )

    swept = service.sweep_idle_sessions(
        now=datetime(2026, 7, 1, 0, 10, 0, tzinfo=timezone.utc)
    )

    assert len(swept) == 1
    assert swept[0].settlement is not None
    assert swept[0].settlement.no_request is True
    assert swept[0].settlement.minimum_session_fee_q == 2.0
    assert swept[0].settlement.idle_fee_charged_q == 0.0
    assert swept[0].deposit.consumed_q == 2.0
