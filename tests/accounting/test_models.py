import pytest
from pydantic import ValidationError

from aidn_hypervisor.accounting.models import (
    AccountingContract,
    AccountingUnitContract,
    RuntimeUsageProfile,
    RuntimeUsageProfileDimension,
    SessionAccountingCheckpoint,
    usage_acknowledgement_hash,
    usage_report_hash,
    UsageAcknowledgement,
    UsageDimensionEvidence,
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


def test_accounting_contract_derives_stable_registry_object_metadata() -> None:
    contract_a = AccountingContract(
        contract_version="acct-v1",
        capability_id="llm.chat",
        pricing_version="pricing-v1",
        pricing_policy_reference="sha256:pricing-v1",
        billable_units=[
            AccountingUnitContract(
                unit="input_tokens",
                mode="provider_metered",
                price=12.0,
                measurement_source="provider_api",
                verification_method="provider_report",
            ),
            AccountingUnitContract(
                unit="output_tokens",
                mode="provider_metered",
                price=18.0,
                measurement_source="provider_api",
                verification_method="provider_report",
            ),
        ],
        checkpoint_policy="per_request",
        maximum_request_charge=25.0,
    )
    contract_b = AccountingContract(
        contract_version="acct-v1",
        capability_id="llm.chat",
        pricing_version="pricing-v1",
        pricing_policy_reference="sha256:pricing-v1",
        billable_units=[
            AccountingUnitContract(
                unit="input_tokens",
                mode="provider_metered",
                price=12.0,
                measurement_source="provider_api",
                verification_method="provider_report",
            ),
            AccountingUnitContract(
                unit="output_tokens",
                mode="provider_metered",
                price=18.0,
                measurement_source="provider_api",
                verification_method="provider_report",
            ),
        ],
        checkpoint_policy="per_request",
        maximum_request_charge=25.0,
    )

    assert contract_a.registry_namespace == "usage"
    assert contract_a.payload_encoding == "canonical_json"
    assert contract_a.registry_object_version == "acctobj.v1"
    assert contract_a.registry_object_id.startswith("sha256:")
    assert contract_a.payload_hash.startswith("sha256:")
    assert contract_a.registry_object_id == contract_b.registry_object_id
    assert contract_a.payload_hash == contract_b.payload_hash


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


def test_usage_availability_distinguishes_partial_unavailable_and_not_applicable() -> None:
    partial = UsageDimensionEvidence(
        dimension_id="output_bytes",
        unit="byte",
        availability="PARTIAL",
        authority="OBSERVABLE_LOCAL",
        value=128,
    )
    unavailable = UsageDimensionEvidence(
        dimension_id="input_tokens",
        unit="token",
        availability="UNAVAILABLE",
    )
    not_applicable = UsageDimensionEvidence(
        dimension_id="audio_input_milliseconds",
        unit="millisecond",
        availability="NOT_APPLICABLE",
    )

    assert partial.value == 128
    assert unavailable.value is None and unavailable.authority is None
    assert not_applicable.value is None and not_applicable.authority is None


def test_usage_profile_hash_avoids_runtime_configuration_back_reference_cycle() -> None:
    profile = RuntimeUsageProfile(
        runtime_id="runtime-1",
        runtime_generation=1,
        runtime_configuration_hash="sha256:configuration-a",
        dimensions=[
            RuntimeUsageProfileDimension(
                dimension_id="input_bytes",
                unit="byte",
                expected_availability="AVAILABLE",
                authority="DETERMINISTIC_LOCAL",
                billing_eligible=True,
            )
        ],
    )
    rebound = RuntimeUsageProfile.model_validate(
        {
            **profile.model_dump(mode="json"),
            "runtime_configuration_hash": "sha256:configuration-b",
        }
    )

    assert rebound.profile_hash == profile.profile_hash


def test_proxy_opaque_fixed_price_accepts_unavailable_tokens() -> None:
    profile = RuntimeUsageProfile(
        runtime_id="runtime-opaque",
        runtime_generation=1,
        runtime_configuration_hash="sha256:opaque",
        dimensions=[
            RuntimeUsageProfileDimension(
                dimension_id="input_tokens",
                unit="token",
                expected_availability="UNAVAILABLE",
            )
        ],
    )
    contract = AccountingContract(
        contract_version="opaque-v1",
        accounting_mode="proxy_opaque",
        pricing_version="fixed-v1",
        billable_units=[
            AccountingUnitContract(
                unit="request_fee",
                mode="fixed_price",
                price=3.0,
                measurement_source="endpoint_policy",
                verification_method="fixed_contract",
            )
        ],
        checkpoint_policy="per_request",
        maximum_request_charge=3.0,
    )

    assert contract.compatibility_errors(profile) == []
    assert contract.calculate_charge([], request_charge_ceiling=3.0) == 3.0


def test_provider_metered_contract_rejects_profile_with_unavailable_required_tokens() -> None:
    profile = RuntimeUsageProfile(
        runtime_id="runtime-opaque",
        runtime_generation=1,
        runtime_configuration_hash="sha256:opaque",
        dimensions=[
            RuntimeUsageProfileDimension(
                dimension_id="input_tokens",
                unit="token",
                expected_availability="UNAVAILABLE",
            )
        ],
    )
    contract = AccountingContract(
        contract_version="metered-v1",
        accounting_mode="provider_metered",
        pricing_version="tokens-v1",
        billable_units=[
            AccountingUnitContract(
                unit="input_tokens",
                mode="provider_metered",
                price=0.01,
                measurement_source="provider_api",
                verification_method="provider_report",
                required_authority="AUTHORITATIVE_PROVIDER",
            )
        ],
        checkpoint_policy="per_request",
    )

    assert contract.compatibility_errors(profile) == [
        "required Usage dimension is unavailable: input_tokens",
        "Usage authority mismatch: input_tokens",
    ]


def test_authoritative_provider_usage_requires_provider_source() -> None:
    with pytest.raises(ValidationError, match="Provider usage source"):
        UsageDimensionEvidence(
            dimension_id="input_tokens",
            unit="token",
            availability="AVAILABLE",
            authority="AUTHORITATIVE_PROVIDER",
            value=10,
        )
