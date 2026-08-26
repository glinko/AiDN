"""Deterministic escrow deposit guidance derived from an Endpoint contract."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from aidn_hypervisor.pricing.models import BillingDimension, RateCardV2
from aidn_hypervisor.pricing.quotes import quote_rate_card


class EscrowDepositRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "escrow-deposit-recommendation.v1"
    rate_card_hash: str
    safety_margin_bps: int = Field(ge=0, le=10_000)
    recommended_multiplier: int = Field(ge=1, le=100)
    usage_assumptions: dict[BillingDimension, int]
    missing_dimensions: list[BillingDimension]
    estimated_request_charge_q_atoms: int | None = Field(default=None, ge=0)
    minimum_deposit_q_atoms: int | None = Field(default=None, ge=0)
    recommended_deposit_q_atoms: int | None = Field(default=None, ge=0)
    automatic: bool


class EscrowDepositRecommendationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    usage_overrides: dict[BillingDimension, int] = Field(default_factory=dict)
    safety_margin_bps: int = Field(default=2_000, ge=0, le=10_000)
    recommended_multiplier: int = Field(default=5, ge=1, le=100)


def _policy_number(policy: dict[str, Any], name: str, *, use_allowed_max: bool) -> int | None:
    raw = policy.get(name)
    if raw is None:
        return None
    if hasattr(raw, "model_dump"):
        item = raw.model_dump(mode="json", by_alias=True)
    elif isinstance(raw, dict):
        item = raw
    else:
        return None
    selected = item.get("value")
    if use_allowed_max and item.get("consumer_editable") is True:
        selected = item.get("max", item.get("maximum", selected))
    if isinstance(selected, bool) or not isinstance(selected, (int, float)):
        return None
    return max(0, int(selected))


def _runtime_limit(runtime: object, name: str) -> int | None:
    value = getattr(runtime, name, None)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return max(0, value)


def estimate_escrow_deposits(
    rate_card: RateCardV2,
    *,
    runtime: object | None = None,
    runtime_parameter_policy: dict[str, Any] | None = None,
    usage_overrides: dict[BillingDimension, int] | None = None,
    safety_margin_bps: int = 2_000,
    recommended_multiplier: int = 5,
) -> EscrowDepositRecommendation:
    """Estimate one high-usage request and a multi-request working balance.

    LLM assumptions use the immutable context window and the largest output
    allowed to a Consumer. Other workload families can supply explicit integer
    Usage assumptions until their media limit profiles are standardized.
    """
    if not 0 <= safety_margin_bps <= 10_000:
        raise ValueError("safety margin must be between 0 and 10000 basis points")
    if not 1 <= recommended_multiplier <= 100:
        raise ValueError("recommended deposit multiplier must be between 1 and 100")

    policy = dict(runtime_parameter_policy or {})
    context_tokens = _policy_number(
        policy,
        "context_length",
        use_allowed_max=True,
    ) or (_runtime_limit(runtime, "context_length") if runtime is not None else None)
    output_tokens = _policy_number(
        policy,
        "max_tokens",
        use_allowed_max=True,
    ) or (_runtime_limit(runtime, "max_tokens") if runtime is not None else None)
    if context_tokens is not None and output_tokens is not None:
        output_tokens = min(output_tokens, context_tokens)
    text_input_characters = _policy_number(
        policy,
        "max_text_characters",
        use_allowed_max=True,
    )
    audio_input_milliseconds = _policy_number(
        policy,
        "max_audio_input_milliseconds",
        use_allowed_max=True,
    )
    audio_output_milliseconds = _policy_number(
        policy,
        "max_audio_output_milliseconds",
        use_allowed_max=True,
    )

    assumptions: dict[BillingDimension, int] = {}
    priced_dimensions = {item.dimension for item in rate_card.components}
    if "input_tokens" in priced_dimensions and context_tokens is not None:
        assumptions["input_tokens"] = context_tokens
    if "cached_input_tokens" in priced_dimensions and context_tokens is not None:
        # Cached tokens replace, rather than duplicate, uncached input tokens.
        # The normal worst case is therefore an entirely uncached context.
        assumptions["cached_input_tokens"] = 0
    if "output_tokens" in priced_dimensions and output_tokens is not None:
        assumptions["output_tokens"] = output_tokens
    if "text_input_characters" in priced_dimensions:
        if text_input_characters is not None:
            assumptions["text_input_characters"] = text_input_characters
        elif context_tokens is not None:
            assumptions["text_input_characters"] = context_tokens * 4
    if "audio_input_milliseconds" in priced_dimensions and audio_input_milliseconds is not None:
        assumptions["audio_input_milliseconds"] = audio_input_milliseconds
    if "audio_output_milliseconds" in priced_dimensions and audio_output_milliseconds is not None:
        assumptions["audio_output_milliseconds"] = audio_output_milliseconds
    assumptions.update(usage_overrides or {})

    quote = quote_rate_card(rate_card, assumptions)
    estimated = quote.estimated_charge_q_atoms
    minimum = None
    recommended = None
    if estimated is not None:
        minimum = (
            estimated * (10_000 + safety_margin_bps) + 9_999
        ) // 10_000
        recommended = minimum * recommended_multiplier

    return EscrowDepositRecommendation(
        rate_card_hash=str(rate_card.rate_card_hash),
        safety_margin_bps=safety_margin_bps,
        recommended_multiplier=recommended_multiplier,
        usage_assumptions=assumptions,
        missing_dimensions=quote.missing_dimensions,
        estimated_request_charge_q_atoms=estimated,
        minimum_deposit_q_atoms=minimum,
        recommended_deposit_q_atoms=recommended,
        automatic=estimated is not None,
    )
