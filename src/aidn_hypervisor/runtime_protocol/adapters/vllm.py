"""RFC-0054 adapter for a vLLM OpenAI-compatible completion endpoint."""

from aidn_hypervisor.runtime_protocol.adapters.llamacpp import LlamaCppOpenAIAdapter
from aidn_hypervisor.runtime_protocol.models import RuntimeUsageDimension


class VllmOpenAIAdapter(LlamaCppOpenAIAdapter):
    """Use the shared OpenAI mapping with vLLM-specific Usage provenance.

    The standard completion API does not expose a portable operation handle, so
    inherited cancellation and in-flight recovery deliberately remain
    best-effort. Confirmed stop requires an adapter for a Provider-specific
    operation API.
    """

    adapter_label = "vllm"

    def _usage_dimensions(self, usage: dict) -> list[RuntimeUsageDimension]:
        dimensions: list[RuntimeUsageDimension] = []
        details = usage.get("prompt_tokens_details")
        cached_tokens = details.get("cached_tokens") if isinstance(details, dict) else None
        for provider_key, dimension_id in (
            ("prompt_tokens", "input_tokens"),
            ("completion_tokens", "output_tokens"),
        ):
            value = usage.get(provider_key)
            if (
                dimension_id == "input_tokens"
                and isinstance(value, int)
                and isinstance(cached_tokens, int)
                and 0 <= cached_tokens <= value
            ):
                value -= cached_tokens
            if isinstance(value, int) and value >= 0:
                dimensions.append(
                    RuntimeUsageDimension(
                        dimension_id=dimension_id,
                        unit="token",
                        availability="AVAILABLE",
                        authority="AUTHORITATIVE_PROVIDER",
                        value=value,
                        billing_eligible=True,
                        source_reference={
                            "source_type": "PROVIDER_USAGE_RESPONSE",
                            "source_id": "vllm-v1-completions",
                        },
                    )
                )
        if isinstance(cached_tokens, int) and cached_tokens >= 0:
            dimensions.append(
                RuntimeUsageDimension(
                    dimension_id="cached_input_tokens",
                    unit="token",
                    availability="AVAILABLE",
                    authority="AUTHORITATIVE_PROVIDER",
                    value=cached_tokens,
                    billing_eligible=True,
                    source_reference={
                        "source_type": "PROVIDER_USAGE_RESPONSE",
                        "source_id": "vllm-v1-completions",
                    },
                )
            )
        return dimensions
