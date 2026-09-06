"""Usage profile declared by the NeMo-Speech Runtime adapter."""

from aidn_hypervisor.accounting.models import (
    RuntimeUsageProfile,
    RuntimeUsageProfileDimension,
)


def build_nemo_speech_usage_profile(
    *,
    runtime_id: str,
    runtime_generation: int,
    runtime_configuration_hash: str,
    adapter_version: str = "nemo-speech-http.v1",
) -> RuntimeUsageProfile:
    """Declare deterministic WAV duration and observable transcript bytes."""

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
                limitations=["NEMO_SPEECH_TOKEN_USAGE_UNAVAILABLE"],
            ),
            RuntimeUsageProfileDimension(
                dimension_id="output_tokens",
                unit="token",
                expected_availability="UNAVAILABLE",
                billing_eligible=False,
                limitations=["NEMO_SPEECH_TOKEN_USAGE_UNAVAILABLE"],
            ),
            RuntimeUsageProfileDimension(
                dimension_id="audio_input_milliseconds",
                unit="millisecond",
                expected_availability="AVAILABLE",
                authority="DETERMINISTIC_LOCAL",
                billing_eligible=True,
                limitations=["EXACT_FOR_HYPERVISOR_INGRESS_WAV"],
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



