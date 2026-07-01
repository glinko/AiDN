import pytest
from pydantic import ValidationError

from aidn_hypervisor.sessions.models import EndpointSession, LockedDeposit


def test_endpoint_session_requires_positive_locked_deposit() -> None:
    with pytest.raises(ValidationError):
        EndpointSession(
            session_id="sess-1",
            endpoint_id="ep-1",
            client_wallet="wallet-client",
            provider_wallet="wallet-provider",
            node_id="node-1",
            status="active",
            created_at="2026-07-01T00:00:00+00:00",
            started_at="2026-07-01T00:00:00+00:00",
            last_activity_at="2026-07-01T00:00:00+00:00",
            expires_at="2026-07-01T01:00:00+00:00",
            idle_deadline_at="2026-07-01T00:10:00+00:00",
            deposit_locked_q=0.0,
            reserved_slot_index=0,
            queue_policy_snapshot="busy",
            session_policy_snapshot={"minimum_deposit": 10.0},
        )


def test_locked_deposit_rejects_consumed_amount_above_locked_amount() -> None:
    with pytest.raises(ValidationError):
        LockedDeposit(
            deposit_id="dep-1",
            session_id="sess-1",
            wallet_id="wallet-client",
            locked_q=10.0,
            consumed_q=11.0,
            refunded_q=0.0,
            status="locked",
        )
