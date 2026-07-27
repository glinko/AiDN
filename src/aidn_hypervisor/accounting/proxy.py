"""Usage profile for an opaque upstream Proxy Runtime."""

from aidn_hypervisor.accounting.models import (
    RuntimeUsageProfile,
    RuntimeUsageProfileDimension,
)


def build_proxy_opaque_usage_profile(
    *,
    runtime_id: str,
    runtime_generation: int,
    runtime_configuration_hash: str,
    adapter_version: str = "proxy-openai.v1",
) -> RuntimeUsageProfile:
    """Declare only measurements the proxy can defend without upstream metering."""
    return RuntimeUsageProfile(
        runtime_id=runtime_id,
        runtime_generation=runtime_generation,
        runtime_configuration_hash=runtime_configuration_hash,
        adapter_version=adapter_version,
        dimensions=[
            RuntimeUsageProfileDimension(
                dimension_id="input_tokens",
                unit="token",
                expected_availability="UNAVAILABLE",
                billing_eligible=False,
                limitations=["UPSTREAM_USAGE_OPAQUE"],
            ),
            RuntimeUsageProfileDimension(
                dimension_id="output_tokens",
                unit="token",
                expected_availability="UNAVAILABLE",
                billing_eligible=False,
                limitations=["UPSTREAM_USAGE_OPAQUE"],
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
