from pathlib import Path

from aidn_hypervisor.domain.models import ResourceProfile
from aidn_hypervisor.resource_estimator import estimate_llama_cpp_resources, model_size_mb
from aidn_hypervisor.runtime_parameter_policy import default_runtime_parameter_policy


def _policy(*, context: int = 4096, gpu_layers: int = 99, kv_offload: bool = True):
    policy = default_runtime_parameter_policy("llama.cpp")
    policy["context_length"] = policy["context_length"].model_copy(
        update={"value": context}
    )
    policy["gpu_layers"] = policy["gpu_layers"].model_copy(
        update={"value": gpu_layers}
    )
    policy["kv_offload"] = policy["kv_offload"].model_copy(
        update={"value": kv_offload}
    )
    return policy


def _fixture_model() -> Path:
    # Use a repository file as a deterministic local-artifact stand-in.  The
    # estimator only needs a real byte size and the test must not allocate a
    # large temporary GGUF on constrained CI volumes.
    return Path(__file__).resolve().parents[1] / "pyproject.toml"


def test_llama_estimator_accounts_for_gguf_weights_and_full_gpu_layers() -> None:
    model = _fixture_model()

    estimate = estimate_llama_cpp_resources(
        model_id=str(model),
        policy=_policy(),
        resource_profile=ResourceProfile(),
        max_parallel_requests=1,
    )

    assert estimate["estimate_confidence"] == "ESTIMATED"
    model_mb = model_size_mb(str(model))
    assert estimate["estimate_breakdown"]["model_weights_mb"] == model_mb
    assert estimate["estimate_breakdown"]["gpu_model_weights_mb"] == model_mb
    # KV offload keeps the cache out of VRAM but accounts for it in host RAM.
    assert estimate["runtime_resident"]["vram_mb"] > model_mb
    assert estimate["runtime_resident"]["ram_mb"] >= estimate["estimate_breakdown"]["kv_cache_mb"]


def test_llama_estimator_scales_kv_cache_with_context_and_keeps_gpu_offload_explicit() -> None:
    model = _fixture_model()

    short = estimate_llama_cpp_resources(
        model_id=str(model),
        policy=_policy(context=4096, kv_offload=False),
        resource_profile=ResourceProfile(),
    )
    long = estimate_llama_cpp_resources(
        model_id=str(model),
        policy=_policy(context=131072, kv_offload=False),
        resource_profile=ResourceProfile(),
    )

    assert long["estimate_breakdown"]["kv_cache_mb"] > short["estimate_breakdown"]["kv_cache_mb"]
    assert long["runtime_resident"]["vram_mb"] > short["runtime_resident"]["vram_mb"]
    assert "kv_cache_on_gpu" in long["estimate_assumptions"]


def test_explicit_resource_profile_remains_authoritative() -> None:
    model = _fixture_model()

    estimate = estimate_llama_cpp_resources(
        model_id=str(model),
        policy=_policy(context=131072),
        resource_profile=ResourceProfile(steady_vram_mb=2048, steady_ram_mb=4096),
    )

    assert estimate["runtime_resident"]["vram_mb"] == 2048
    assert estimate["runtime_resident"]["ram_mb"] == 4096
