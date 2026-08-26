"""Usage profile for deterministic OpenAI-compatible TTS execution."""

from aidn_hypervisor.accounting.models import (
    RuntimeUsageProfile,
    RuntimeUsageProfileDimension,
)


def build_tts_usage_profile(
    *,
    runtime_id: str,
    runtime_generation: int,
    runtime_configuration_hash: str,
    adapter_version: str = "openai-tts.v1",
) -> RuntimeUsageProfile:
    return RuntimeUsageProfile(
        runtime_id=runtime_id,
        runtime_generation=runtime_generation,
        runtime_configuration_hash=runtime_configuration_hash,
        adapter_version=adapter_version,
        dimensions=[
            RuntimeUsageProfileDimension(
                dimension_id="text_input_characters",
                unit="character",
                expected_availability="AVAILABLE",
                authority="DETERMINISTIC_LOCAL",
                billing_eligible=True,
            ),
            RuntimeUsageProfileDimension(
                dimension_id="audio_output_milliseconds",
                unit="millisecond",
                expected_availability="AVAILABLE",
                authority="DETERMINISTIC_LOCAL",
                billing_eligible=True,
                limitations=["VALID_WAV_OUTPUT_REQUIRED"],
            ),
        ],
    )
