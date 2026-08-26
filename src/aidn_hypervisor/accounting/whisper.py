"""Usage profile declared by the Whisper Runtime adapter."""

from aidn_hypervisor.accounting.models import (
    RuntimeUsageProfile,
    RuntimeUsageProfileDimension,
)


def build_whisper_usage_profile(
    *,
    runtime_id: str,
    runtime_generation: int,
    runtime_configuration_hash: str,
    adapter_version: str = "whisper-http.v1",
) -> RuntimeUsageProfile:
    """Declare honest Whisper measurements for fixed-price and observable work."""
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
                limitations=["WHISPER_TOKEN_USAGE_UNAVAILABLE"],
            ),
            RuntimeUsageProfileDimension(
                dimension_id="output_tokens",
                unit="token",
                expected_availability="UNAVAILABLE",
                billing_eligible=False,
                limitations=["WHISPER_TOKEN_USAGE_UNAVAILABLE"],
            ),
            RuntimeUsageProfileDimension(
                dimension_id="audio_input_milliseconds",
                unit="millisecond",
                expected_availability="PARTIAL",
                authority="DETERMINISTIC_LOCAL",
                billing_eligible=True,
                limitations=[
                    "EXACT_FOR_HYPERVISOR_INGRESS_WAV",
                    "OTHER_MEDIA_FORMATS_REQUIRE_A_TRUSTED_DURATION_METER",
                ],
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
