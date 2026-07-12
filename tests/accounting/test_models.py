import pytest
from pydantic import ValidationError

from aidn_hypervisor.accounting.models import (
    AccountingContract,
    AccountingUnitContract,
    SessionAccountingCheckpoint,
    usage_acknowledgement_hash,
    usage_report_hash,
    UsageAcknowledgement,
    UsageReport,
)
from aidn_hypervisor.sessions.models import EndpointSession


def test_accounting_contract_accepts_multiple_unit_modes() -> None:
    contract = AccountingContract(
        contract_version="acct-v1",
        capability_id="llm_text.generate",
        pricing_version="pricing-v1",
        billable_units=[
            AccountingUnitContract(
                unit="input_tokens",
                mode="provider_metered",
                price=12.0,
                measurement_source="provider_api",
                verification_method="provider_report",
            ),
            AccountingUnitContract(
                unit="request_fee",
                mode="fixed_price",
                price=4.0,
                measurement_source="endpoint_policy",
                verification_method="fixed_contract",
            ),
        ],
        checkpoint_policy="per_request",
        maximum_request_charge=25.0,
    )

    assert contract.billable_units[0].mode == "provider_metered"
    assert contract.billable_units[1].mode == "fixed_price"


def test_usage_report_requires_positive_sequence() -> None:
    with pytest.raises(ValidationError):
        UsageReport(
            report_id="rep-1",
            report_version="0.1",
            session_id="sess-1",
            endpoint_id="ep-1",
            pricing_version="pricing-v1",
            accounting_contract_version="acct-v1",
            accounting_modes={"input_tokens": "provider_metered"},
            sequence=0,
            cumulative_usage={"input_tokens": 10},
            measurement_sources={"input_tokens": "provider_api"},
            created_at="2026-07-10T00:00:00+00:00",
            signature="sig-1",
        )


def test_usage_acknowledgement_tracks_verification_status() -> None:
    acknowledgement = UsageAcknowledgement(
        session_id="sess-1",
        sequence=2,
        provider_report_hash="sha256:abc",
        verification_status="accepted_unverified",
        consumer_measurements={"output_tokens": 120},
        signature="sig-ack",
    )

    assert acknowledgement.verification_status == "accepted_unverified"


def test_usage_report_hash_is_stable_for_equivalent_payloads() -> None:
    report_a = UsageReport(
        report_id="rep-1",
        report_version="0.1",
        session_id="sess-1",
        endpoint_id="ep-1",
        pricing_version="pricing-v1",
        accounting_contract_version="acct-v1",
        accounting_modes={"input_tokens": "provider_metered", "output_tokens": "provider_metered"},
        sequence=2,
        cumulative_usage={"input_tokens": 10, "output_tokens": 7},
        request_usage=[{"unit": "input_tokens", "qty": 10}],
        measurement_sources={"input_tokens": "provider_api", "output_tokens": "provider_api"},
        estimated_usage={"output_tokens": 7},
        previous_report_hash="sha256:prev",
        created_at="2026-07-10T00:00:00+00:00",
        signature="sig-1",
    )
    report_b = UsageReport(
        report_id="rep-1",
        report_version="0.1",
        session_id="sess-1",
        endpoint_id="ep-1",
        pricing_version="pricing-v1",
        accounting_contract_version="acct-v1",
        accounting_modes={"output_tokens": "provider_metered", "input_tokens": "provider_metered"},
        sequence=2,
        cumulative_usage={"output_tokens": 7, "input_tokens": 10},
        request_usage=[{"unit": "input_tokens", "qty": 10}],
        measurement_sources={"output_tokens": "provider_api", "input_tokens": "provider_api"},
        estimated_usage={"output_tokens": 7},
        previous_report_hash="sha256:prev",
        created_at="2026-07-10T00:00:00+00:00",
        signature="sig-1",
    )

    assert usage_report_hash(report_a) == usage_report_hash(report_b)
    assert usage_report_hash(report_a).startswith("sha256:")


def test_usage_acknowledgement_hash_is_stable_for_equivalent_payloads() -> None:
    acknowledgement_a = UsageAcknowledgement(
        session_id="sess-1",
        sequence=2,
        provider_report_hash="sha256:abc",
        verification_status="accepted_unverified",
        consumer_measurements={"input_tokens": 11, "output_tokens": 4},
        observations={"latency_ms": 120, "notes": "ok"},
        signature="sig-ack",
    )
    acknowledgement_b = UsageAcknowledgement(
        session_id="sess-1",
        sequence=2,
        provider_report_hash="sha256:abc",
        verification_status="accepted_unverified",
        consumer_measurements={"output_tokens": 4, "input_tokens": 11},
        observations={"notes": "ok", "latency_ms": 120},
        signature="sig-ack",
    )

    assert usage_acknowledgement_hash(acknowledgement_a) == usage_acknowledgement_hash(
        acknowledgement_b
    )
    assert usage_acknowledgement_hash(acknowledgement_a).startswith("sha256:")


def test_session_accounting_checkpoint_rejects_accepted_sequence_ahead_of_report_head() -> None:
    with pytest.raises(ValidationError):
        SessionAccountingCheckpoint(
            last_report_sequence=2,
            last_accepted_report_sequence=3,
        )


def test_session_accounting_checkpoint_rejects_accepted_hash_without_sequence() -> None:
    with pytest.raises(ValidationError):
        SessionAccountingCheckpoint(
            last_report_sequence=2,
            last_accepted_report_hash="sha256:abc",
        )


def test_session_accounting_checkpoint_rejects_report_hash_without_sequence() -> None:
    with pytest.raises(ValidationError):
        SessionAccountingCheckpoint(
            last_report_hash="sha256:report",
        )


def test_session_accounting_checkpoint_rejects_ack_hash_without_sequence() -> None:
    with pytest.raises(ValidationError):
        SessionAccountingCheckpoint(
            last_report_sequence=2,
            last_ack_hash="sha256:ack",
        )


def test_session_accounting_checkpoint_rejects_ack_sequence_ahead_of_report_head() -> None:
    with pytest.raises(ValidationError):
        SessionAccountingCheckpoint(
            last_report_sequence=2,
            last_ack_sequence=3,
        )


def test_endpoint_session_accepts_ack_pending_and_force_settle_required() -> None:
    ack_pending_session = EndpointSession(
        session_id="sess-1",
        endpoint_id="ep-1",
        client_wallet="wallet-client",
        provider_wallet="wallet-provider",
        node_id="node-1",
        status="active",
        created_at="2026-07-10T00:00:00+00:00",
        expires_at="2026-07-10T01:00:00+00:00",
        idle_deadline_at="2026-07-10T00:30:00+00:00",
        deposit_locked_q=12.5,
        queue_policy_snapshot="fifo",
        accounting_status="ack_pending",
    )
    force_settle_session = EndpointSession(
        session_id="sess-2",
        endpoint_id="ep-1",
        client_wallet="wallet-client",
        provider_wallet="wallet-provider",
        node_id="node-1",
        status="active",
        created_at="2026-07-10T00:00:00+00:00",
        expires_at="2026-07-10T01:00:00+00:00",
        idle_deadline_at="2026-07-10T00:30:00+00:00",
        deposit_locked_q=12.5,
        queue_policy_snapshot="fifo",
        accounting_status="force_settle_required",
    )

    assert ack_pending_session.accounting_status == "ack_pending"
    assert force_settle_session.accounting_status == "force_settle_required"


def test_endpoint_session_exposes_usage_chains_and_checkpoint_fields() -> None:
    session = EndpointSession(
        session_id="sess-3",
        endpoint_id="ep-1",
        client_wallet="wallet-client",
        provider_wallet="wallet-provider",
        node_id="node-1",
        status="active",
        created_at="2026-07-10T00:00:00+00:00",
        expires_at="2026-07-10T01:00:00+00:00",
        idle_deadline_at="2026-07-10T00:30:00+00:00",
        deposit_locked_q=12.5,
        queue_policy_snapshot="fifo",
    )

    assert session.usage_report_chain == []
    assert session.usage_acknowledgement_chain == []
    assert session.accounting_checkpoint == {}


def test_endpoint_session_accounting_checkpoint_remains_dict_shaped() -> None:
    session = EndpointSession(
        session_id="sess-4",
        endpoint_id="ep-1",
        client_wallet="wallet-client",
        provider_wallet="wallet-provider",
        node_id="node-1",
        status="active",
        created_at="2026-07-10T00:00:00+00:00",
        expires_at="2026-07-10T01:00:00+00:00",
        idle_deadline_at="2026-07-10T00:30:00+00:00",
        deposit_locked_q=12.5,
        queue_policy_snapshot="fifo",
        accounting_checkpoint={
            "last_report_sequence": 2,
            "last_report_hash": "sha256:report",
        },
    )

    assert isinstance(session.accounting_checkpoint, dict)
    assert session.accounting_checkpoint["last_report_sequence"] == 2
    assert session.accounting_checkpoint["last_report_hash"] == "sha256:report"
