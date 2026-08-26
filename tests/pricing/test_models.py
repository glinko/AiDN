import pytest
from pydantic import ValidationError

from aidn_hypervisor.accounting.models import UsageDimensionEvidence
from aidn_hypervisor.endpoints.models import EndpointPricing
from aidn_hypervisor.pricing import (
    RateCardV2,
    RateComponent,
    calculate_rate_card_charge,
    estimate_escrow_deposits,
    quote_rate_card,
)
from aidn_hypervisor.settlement import (
    RequestSettlementInput,
    SettlementEngine,
    build_rate_card_settlement_terms,
)


def test_endpoint_pricing_accepts_only_rate_card_v2() -> None:
    pricing = EndpointPricing(rate_card=RateCardV2(components=[RateComponent(
        component_id="base", dimension="request_count", kind="fixed",
        unit_price_q_atoms=2_000_000, accounting_mode="fixed_price",
    )]))
    assert pricing.is_configured()
    assert pricing.is_paid()
    assert pricing.model_dump(mode="json")["rate_card"]["schema_version"] == "pricing.v2"


@pytest.mark.parametrize("legacy_payload", [
    {"billing_unit": "request"}, {"fixed_price": 1}, {"input_price": 1},
    {"output_price": 1}, {"audio_input_second_price": 1},
])
def test_endpoint_pricing_rejects_legacy_fields(legacy_payload: dict) -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        EndpointPricing.model_validate(legacy_payload)


def test_rate_card_hash_is_stable_for_qualifier_order() -> None:
    first = RateCardV2(components=[RateComponent(
        component_id="image-standard", dimension="image_output_count",
        unit_price_q_atoms=25_000,
        qualifiers={"quality": "standard", "width": 1024, "height": 1024},
    )])
    second = RateCardV2(components=[RateComponent(
        component_id="image-standard", dimension="image_output_count",
        unit_price_q_atoms=25_000,
        qualifiers={"height": 1024, "width": 1024, "quality": "standard"},
    )])
    assert first.rate_card_hash == second.rate_card_hash


def test_rate_card_rejects_duplicate_dimension_and_qualifier_tier() -> None:
    component = {"dimension": "video_output_milliseconds", "unit_price_q_atoms": 500,
                 "qualifiers": {"resolution": "1080p"}}
    with pytest.raises(ValidationError, match="dimensions and qualifiers must be unique"):
        RateCardV2(components=[
            RateComponent(component_id="video-a", **component),
            RateComponent(component_id="video-b", **component),
        ])


def test_rate_card_charge_separates_cached_and_uncached_tokens() -> None:
    rate_card = RateCardV2(components=[
        RateComponent(component_id="input", dimension="input_tokens",
                      unit_price_q_atoms=2_000_000, unit_divisor=1_000_000,
                      accounting_mode="provider_metered"),
        RateComponent(component_id="cached-input", dimension="cached_input_tokens",
                      unit_price_q_atoms=500_000, unit_divisor=1_000_000,
                      accounting_mode="provider_metered"),
        RateComponent(component_id="output", dimension="output_tokens",
                      unit_price_q_atoms=4_000_000, unit_divisor=1_000_000,
                      accounting_mode="provider_metered"),
        RateComponent(component_id="base", dimension="request_count", kind="fixed",
                      unit_price_q_atoms=1_000_000, accounting_mode="fixed_price"),
    ])
    charge = calculate_rate_card_charge(rate_card, {
        "input_tokens": 250_000, "cached_input_tokens": 100_000,
        "output_tokens": 500_000,
    })
    assert [item.charge_q_atoms for item in charge.components] == [
        500_000, 50_000, 2_000_000, 1_000_000,
    ]
    assert charge.total_q_atoms == 3_550_000


def test_rate_card_charge_fails_closed_when_priced_usage_is_missing() -> None:
    rate_card = RateCardV2(components=[RateComponent(
        component_id="cached", dimension="cached_input_tokens", unit_price_q_atoms=1,
    )])
    with pytest.raises(ValueError, match="cached_input_tokens"):
        calculate_rate_card_charge(rate_card, {})


@pytest.mark.parametrize(("rounding", "expected"), [
    ("DOWN", 0),
    ("UP", 1),
    ("HALF_EVEN", 0),
])
def test_rate_card_charge_uses_declared_integer_rounding(rounding: str, expected: int) -> None:
    rate_card = RateCardV2(components=[RateComponent(
        component_id="tiny", dimension="input_tokens", unit_price_q_atoms=1,
        unit_divisor=2, rounding=rounding,
    )])
    assert calculate_rate_card_charge(
        rate_card, {"input_tokens": 1}
    ).total_q_atoms == expected


def test_rate_card_charge_enforces_minimum() -> None:
    minimum = RateCardV2(
        components=[RateComponent(
            component_id="input", dimension="input_tokens", unit_price_q_atoms=1,
        )],
        minimum_charge_q_atoms=10,
    )
    assert calculate_rate_card_charge(minimum, {"input_tokens": 2}).total_q_atoms == 10


def test_rate_card_quote_exposes_lower_and_estimated_atom_amounts() -> None:
    rate_card = RateCardV2(
        components=[
            RateComponent(
                component_id="base",
                dimension="request_count",
                kind="fixed",
                unit_price_q_atoms=100,
                accounting_mode="fixed_price",
            ),
            RateComponent(
                component_id="input",
                dimension="input_tokens",
                unit_price_q_atoms=2,
            ),
        ],
    )

    incomplete = quote_rate_card(rate_card)
    assert incomplete.lower_bound_q_atoms == 100
    assert incomplete.estimated_charge_q_atoms is None
    assert incomplete.missing_dimensions == ["input_tokens"]

    complete = quote_rate_card(rate_card, {"input_tokens": 40})
    assert complete.estimated_charge_q_atoms == 180
    assert complete.missing_dimensions == []


def test_metered_rate_card_can_be_quoted_without_expected_usage() -> None:
    quote = quote_rate_card(
        RateCardV2(
            components=[
                RateComponent(
                    component_id="output",
                    dimension="output_tokens",
                    unit_price_q_atoms=3,
                )
            ]
        )
    )

    assert quote.lower_bound_q_atoms == 0
    assert quote.estimated_charge_q_atoms is None
    assert quote.missing_dimensions == ["output_tokens"]


def test_llm_deposit_recommendation_uses_limits_margin_and_five_request_buffer() -> None:
    rate_card = RateCardV2(components=[
        RateComponent(
            component_id="base", dimension="request_count", kind="fixed",
            unit_price_q_atoms=1_000_000, accounting_mode="fixed_price",
        ),
        RateComponent(
            component_id="input", dimension="input_tokens",
            unit_price_q_atoms=2_000_000, unit_divisor=1_000_000,
        ),
        RateComponent(
            component_id="output", dimension="output_tokens",
            unit_price_q_atoms=4_000_000, unit_divisor=1_000_000,
        ),
    ])

    recommendation = estimate_escrow_deposits(
        rate_card,
        runtime_parameter_policy={
            "context_length": {"value": 4096, "consumer_editable": False},
            "max_tokens": {"value": 512, "consumer_editable": False},
        },
    )

    assert recommendation.usage_assumptions == {
        "input_tokens": 4096,
        "output_tokens": 512,
    }
    assert recommendation.estimated_request_charge_q_atoms == 1_010_240
    assert recommendation.minimum_deposit_q_atoms == 1_212_288
    assert recommendation.recommended_deposit_q_atoms == 6_061_440
    assert recommendation.automatic is True


def test_deposit_recommendation_requires_explicit_limits_for_media_usage() -> None:
    recommendation = estimate_escrow_deposits(
        RateCardV2(components=[RateComponent(
            component_id="audio", dimension="audio_input_milliseconds",
            unit_price_q_atoms=10,
        )])
    )

    assert recommendation.automatic is False
    assert recommendation.minimum_deposit_q_atoms is None
    assert recommendation.missing_dimensions == ["audio_input_milliseconds"]


def test_tts_deposit_recommendation_uses_text_and_audio_output_limits() -> None:
    recommendation = estimate_escrow_deposits(
        RateCardV2(components=[
            RateComponent(
                component_id="text",
                dimension="text_input_characters",
                unit_price_q_atoms=2,
            ),
            RateComponent(
                component_id="audio",
                dimension="audio_output_milliseconds",
                unit_price_q_atoms=3,
            ),
        ]),
        runtime_parameter_policy={
            "max_text_characters": {"value": 1_000, "consumer_editable": False},
            "max_audio_output_milliseconds": {
                "value": 60_000,
                "consumer_editable": False,
            },
        },
    )

    assert recommendation.usage_assumptions == {
        "text_input_characters": 1_000,
        "audio_output_milliseconds": 60_000,
    }
    assert recommendation.estimated_request_charge_q_atoms == 182_000
    assert recommendation.minimum_deposit_q_atoms == 218_400
    assert recommendation.recommended_deposit_q_atoms == 1_092_000
    assert recommendation.automatic is True


def test_rate_card_builds_integer_terms_and_settles_hybrid_request() -> None:
    rate_card = RateCardV2(components=[
        RateComponent(component_id="request-base", dimension="request_count", kind="fixed",
                      unit_price_q_atoms=1_000, accounting_mode="fixed_price"),
        RateComponent(component_id="input-token-charge", dimension="input_tokens",
                      unit_price_q_atoms=2_000_000, unit_divisor=1_000_000,
                      accounting_mode="provider_metered",
                      required_authority="AUTHORITATIVE_PROVIDER"),
    ])
    terms = build_rate_card_settlement_terms(rate_card)
    request = RequestSettlementInput(
        session_id="session-1", request_id="request-1",
        request_charge_ceiling_q_atoms=10_000,
        accounting_contract_hash=str(rate_card.rate_card_hash),
        terminal_state="COMPLETED", result_reference="sha256:result",
        final_usage_report_id="usage-1", final_usage_report_hash="sha256:usage-1",
        usage_sequence=1, dimensions=[UsageDimensionEvidence(
            dimension_id="input_tokens", unit="token", availability="AVAILABLE",
            authority="AUTHORITATIVE_PROVIDER", value=120, billing_eligible=True,
            source_reference={"source_type": "PROVIDER_USAGE_RESPONSE",
                              "source_id": "provider-receipt-1"},
        )],
    )
    record = SettlementEngine().evaluate_request(request, terms)
    assert terms.accounting_mode == "hybrid"
    assert terms.terms_version == "settlement-terms.v3"
    assert record.raw_calculated_charge_q_atoms == 1_240
    assert [item.charge_q_atoms for item in record.billable_components] == [1_000, 240]
