"""Usage profile declared by the native Ollama Runtime adapter."""

from aidn_hypervisor.accounting.models import RuntimeUsageProfile, RuntimeUsageProfileDimension


def build_ollama_usage_profile(
    *,
    runtime_id: str,
    runtime_generation: int,
    runtime_configuration_hash: str,
    adapter_version: str = "ollama-generate.v1",
) -> RuntimeUsageProfile:
    return RuntimeUsageProfile(
        runtime_id=runtime_id,
        runtime_generation=runtime_generation,
        runtime_configuration_hash=runtime_configuration_hash,
        adapter_version=adapter_version,
        dimensions=[
            RuntimeUsageProfileDimension(
                dimension_id="input_tokens",
                unit="token",
                expected_availability="AVAILABLE",
                authority="AUTHORITATIVE_PROVIDER",
                billing_eligible=True,
            ),
            RuntimeUsageProfileDimension(
                dimension_id="output_tokens",
                unit="token",
                expected_availability="AVAILABLE",
                authority="AUTHORITATIVE_PROVIDER",
                billing_eligible=True,
            ),
            RuntimeUsageProfileDimension(
                dimension_id="output_bytes",
                unit="byte",
                expected_availability="AVAILABLE",
                authority="OBSERVABLE_LOCAL",
                billing_eligible=False,
            ),
        ],
    )
