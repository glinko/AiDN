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
