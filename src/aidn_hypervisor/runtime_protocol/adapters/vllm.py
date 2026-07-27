"""RFC-0054 adapter for a vLLM OpenAI-compatible completion endpoint."""

from aidn_hypervisor.runtime_protocol.adapters.llamacpp import LlamaCppOpenAIAdapter
from aidn_hypervisor.runtime_protocol.models import RuntimeUsageDimension


class VllmOpenAIAdapter(LlamaCppOpenAIAdapter):
    """Use the shared OpenAI wire mapping with vLLM-specific Usage provenance."""

    def _usage_dimensions(self, usage: dict) -> list[RuntimeUsageDimension]:
        dimensions: list[RuntimeUsageDimension] = []
        for provider_key, dimension_id in (
            ("prompt_tokens", "input_tokens"),
            ("completion_tokens", "output_tokens"),
        ):
            value = usage.get(provider_key)
            if isinstance(value, int) and value >= 0:
                dimensions.append(
                    RuntimeUsageDimension(
                        dimension_id=dimension_id,
                        unit="token",
                        availability="AVAILABLE",
                        authority="AUTHORITATIVE_PROVIDER",
                        value=value,
                        billing_eligible=dimension_id == "input_tokens",
                        source_reference={
                            "source_type": "PROVIDER_USAGE_RESPONSE",
                            "source_id": "vllm-v1-completions",
                        },
                    )
                )
        return dimensions
