from aidn_hypervisor.registry_models import RegistryPricing
from aidn_hypervisor.wallet_models import WalletQuote, WalletQuoteCharges

_TOKENS_PER_UNIT = 1_000_000


def quote_usage_q(
    *,
    pricing: RegistryPricing | dict,
    input_tokens: int,
    output_tokens: int,
    fixed_request_count: int = 1,
) -> dict:
    normalized_pricing = (
        pricing if isinstance(pricing, RegistryPricing) else RegistryPricing(**pricing)
    )
    input_q = (input_tokens / _TOKENS_PER_UNIT) * normalized_pricing.input
    output_q = (output_tokens / _TOKENS_PER_UNIT) * normalized_pricing.output
    fixed_q = float((normalized_pricing.fixed_request or 0) * fixed_request_count)
    quote = WalletQuote(
        pricing=normalized_pricing,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        fixed_request_count=fixed_request_count,
        charges=WalletQuoteCharges(
            input_q=input_q,
            output_q=output_q,
            fixed_q=fixed_q,
            total_q=input_q + output_q + fixed_q,
        ),
    )
    return quote.model_dump(mode="json")
