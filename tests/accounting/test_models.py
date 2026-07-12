import pytest
from pydantic import ValidationError

from aidn_hypervisor.accounting.models import (
    AccountingContract,
    AccountingUnitContract,
    UsageAcknowledgement,
    UsageReport,
)


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
