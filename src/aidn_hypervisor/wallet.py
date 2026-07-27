from aidn_hypervisor.registry_models import RegistryPricing
from aidn_hypervisor.wallet_models import WalletQuote, WalletQuoteCharges

_TOKENS_PER_UNIT = 1_000_000


def quote_usage_q(
    *,
    pricing: RegistryPricing | dict,
    input_tokens: int | None,
    output_tokens: int | None,
    fixed_request_count: int = 1,
    audio_input_seconds: float | None = None,
) -> dict:
    normalized_pricing = (
        pricing if isinstance(pricing, RegistryPricing) else RegistryPricing(**pricing)
    )
    input_q = ((input_tokens or 0) / _TOKENS_PER_UNIT) * normalized_pricing.input
    output_q = ((output_tokens or 0) / _TOKENS_PER_UNIT) * normalized_pricing.output
    fixed_q = float((normalized_pricing.fixed_request or 0) * fixed_request_count)
    audio_input_q = (
        float(audio_input_seconds * normalized_pricing.audio_input_second)
        if audio_input_seconds is not None
        else None
    )
    quote = WalletQuote(
        pricing=normalized_pricing,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        fixed_request_count=fixed_request_count,
        audio_input_seconds=audio_input_seconds,
        charges=WalletQuoteCharges(
            input_q=input_q,
            output_q=output_q,
            fixed_q=fixed_q,
            audio_input_q=audio_input_q,
            total_q=input_q + output_q + fixed_q + (audio_input_q or 0.0),
        ),
    )
    return quote.model_dump(mode="json", exclude_none=True)
