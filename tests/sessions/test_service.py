from datetime import datetime, timezone

import pytest

from aidn_hypervisor.accounting.models import AccountingContract, UsageReport
from aidn_hypervisor.sessions.models import ProxySessionBinding
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
    assert closed.deposit.consumed_q == 2.01
    assert closed.deposit.refunded_q == 7.99
    assert closed.settlement is not None
    assert closed.settlement.no_request is True
    assert closed.settlement.network_fee_q == 0.01
    assert closed.settlement.charged_q == 2.01
    assert closed.settlement.refunded_q == 7.99


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
    assert closed.deposit.consumed_q == 6.51
    assert closed.deposit.refunded_q == 13.49
    assert closed.settlement is not None
    assert closed.settlement.no_request is False
    assert closed.settlement.usage_charged_q == 6.5
    assert closed.settlement.network_fee_q == 0.01
    assert closed.settlement.charged_q == 6.51
    assert closed.settlement.refunded_q == 13.49


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
    assert swept[0].settlement.network_fee_q == 0.01
    assert swept[0].settlement.charged_q == 16.01
    assert swept[0].deposit.refunded_q == 13.99


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
    assert swept[0].settlement.network_fee_q == 0.01
    assert swept[0].deposit.consumed_q == 2.01


def test_session_service_round_trips_proxy_session_binding() -> None:
    service = _session_service()
    binding = ProxySessionBinding(
        local_session_id="sess-local",
        remote_endpoint_id="ep-remote",
        remote_session_id="sess-remote",
        remote_node_id="node-remote",
        source_base_url="https://remote.example",
        status="active",
        opened_at="2026-07-02T00:00:00+00:00",
        close_status="not_requested",
    )

    service.save_proxy_session_binding(binding)

    assert service.get_proxy_session_binding("sess-local").remote_session_id == "sess-remote"


def test_open_session_preserves_accounting_contract_snapshot() -> None:
    service = _session_service()
    contract = AccountingContract(
        contract_version="acct-v1",
        capability_id="llm_text.generate",
        pricing_version="pricing-v1",
        billable_units=[],
        checkpoint_policy="per_request",
        maximum_request_charge=25.0,
    )

    opened = service.open_session(
        endpoint_id="ep-1",
        client_wallet="wallet-a",
        provider_wallet="wallet-provider",
        node_id="node-1",
        deposit_q=10.0,
        session_policy=_session_policy(),
        accounting_contract=contract.model_dump(mode="json"),
    )

    assert opened.session.accounting_contract_snapshot["contract_version"] == "acct-v1"
    assert opened.session.accounting_contract_snapshot["maximum_request_charge"] == 25.0


def test_record_usage_checkpoint_creates_acknowledgement_and_updates_accepted_state() -> None:
    service = _session_service()
    opened = service.open_session(
        endpoint_id="ep-1",
        client_wallet="wallet-a",
        provider_wallet="wallet-provider",
        node_id="node-1",
        deposit_q=20.0,
        session_policy=_session_policy(),
    )
    charged = service.record_usage_charge(opened.session.session_id, amount_q=6.5)
    report = UsageReport(
        report_id="rep-1",
        report_version="0.1",
        session_id=opened.session.session_id,
        endpoint_id="ep-1",
        capability_id="llm_text.generate",
        pricing_version="pricing-v1",
        accounting_contract_version="acct-v1",
        accounting_modes={"input_tokens": "provider_metered"},
        sequence=1,
        cumulative_usage={"input_tokens": 100, "output_tokens": 40},
        measurement_sources={"input_tokens": "provider_api", "output_tokens": "provider_api"},
        created_at="2026-07-10T00:00:00+00:00",
        signature="sig-1",
    )

    updated = service.record_usage_checkpoint(
        opened.session.session_id,
        usage_report=report.model_dump(mode="json"),
        accepted_charge_q=charged.deposit.consumed_q,
    )

    assert updated.accounting_status == "open"
    assert updated.last_accepted_report_sequence == 1
    assert updated.last_accepted_usage_charged_q == 6.5
    assert updated.last_usage_acknowledgement_snapshot["verification_status"] == "accepted_unverified"


def test_close_session_uses_last_accepted_checkpoint_when_later_usage_mismatches() -> None:
    service = _session_service()
    opened = service.open_session(
        endpoint_id="ep-1",
        client_wallet="wallet-a",
        provider_wallet="wallet-provider",
        node_id="node-1",
        deposit_q=20.0,
        session_policy=_session_policy(minimum_session_fee=0.0),
    )
    first_charge = service.record_usage_charge(opened.session.session_id, amount_q=6.5)
    first_report = UsageReport(
        report_id="rep-1",
        report_version="0.1",
        session_id=opened.session.session_id,
        endpoint_id="ep-1",
        capability_id="llm_text.generate",
        pricing_version="pricing-v1",
        accounting_contract_version="acct-v1",
        accounting_modes={"input_tokens": "provider_metered"},
        sequence=1,
        cumulative_usage={"input_tokens": 100, "output_tokens": 40},
        measurement_sources={"input_tokens": "provider_api", "output_tokens": "provider_api"},
        created_at="2026-07-10T00:00:00+00:00",
        signature="sig-1",
    )
    service.record_usage_checkpoint(
        opened.session.session_id,
        usage_report=first_report.model_dump(mode="json"),
        accepted_charge_q=first_charge.deposit.consumed_q,
    )
    second_charge = service.record_usage_charge(opened.session.session_id, amount_q=5.5)
    second_report = UsageReport(
        report_id="rep-2",
        report_version="0.1",
        session_id=opened.session.session_id,
        endpoint_id="ep-1",
        capability_id="llm_text.generate",
        pricing_version="pricing-v1",
        accounting_contract_version="acct-v1",
        accounting_modes={"input_tokens": "provider_metered"},
        sequence=2,
        cumulative_usage={"input_tokens": 180, "output_tokens": 80},
        measurement_sources={"input_tokens": "provider_api", "output_tokens": "provider_api"},
        created_at="2026-07-10T00:01:00+00:00",
        signature="sig-2",
    )

    mismatched = service.record_usage_checkpoint(
        opened.session.session_id,
        usage_report=second_report.model_dump(mode="json"),
        accepted_charge_q=second_charge.deposit.consumed_q,
        verification_status="mismatch",
    )
    closed = service.close_session(opened.session.session_id)

    assert mismatched.accounting_status == "mismatch"
    assert mismatched.last_accepted_report_sequence == 1
    assert closed.deposit.consumed_q == 6.51
    assert closed.deposit.refunded_q == 13.49
    assert closed.settlement is not None
    assert closed.settlement.network_fee_q == 0.01
    assert closed.settlement.charged_q == 6.51


def test_require_request_budget_rejects_when_remaining_deposit_is_below_maximum_request_charge() -> None:
    service = _session_service()
    opened = service.open_session(
        endpoint_id="ep-1",
        client_wallet="wallet-a",
        provider_wallet="wallet-provider",
        node_id="node-1",
        deposit_q=25.0,
        session_policy=_session_policy(),
        accounting_contract={
            "contract_version": "acct-v1",
            "pricing_version": "pricing-v1",
            "checkpoint_policy": "per_request",
            "maximum_request_charge": 15.0,
            "billable_units": [],
        },
    )
    service.record_usage_charge(opened.session.session_id, amount_q=12.0)

    with pytest.raises(ValueError, match="maximum request charge"):
        service.require_request_budget(
            endpoint_id="ep-1",
            session_id=opened.session.session_id,
        )
