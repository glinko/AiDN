"""Usage profile declared by the vLLM OpenAI-compatible Runtime adapter."""

from aidn_hypervisor.accounting.llamacpp import build_llamacpp_usage_profile


def build_vllm_usage_profile(
    *,
    runtime_id: str,
    runtime_generation: int,
    runtime_configuration_hash: str,
    adapter_version: str = "vllm-openai.v1",
):
    return build_llamacpp_usage_profile(
        runtime_id=runtime_id,
        runtime_generation=runtime_generation,
        runtime_configuration_hash=runtime_configuration_hash,
        adapter_version=adapter_version,
    )
