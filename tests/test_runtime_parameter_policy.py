import pytest

from aidn_hypervisor.domain.models import BundleConfig, ResourceProfile, TaskRequest
from aidn_hypervisor.model_install_service import ModelInstallService
from aidn_hypervisor.plugins.llamacpp import LlamaCppPlugin
from aidn_hypervisor.runtime_parameter_policy import (
    apply_runtime_parameter_policy,
    apply_runtime_parameter_policy_payload,
    default_runtime_parameter_policy,
    marketplace_parameter_policy,
)


def _bundle() -> BundleConfig:
    return BundleConfig(
        bundle_id="qwen-local",
        plugin_id="llama.cpp",
        provider_type="llama.cpp",
        workload_type="llm_text",
        model_id="/models/qwen.gguf",
        launch_mode="managed_process",
        endpoint="http://127.0.0.1:8080",
        device_affinity="gpu",
        resource_profile=ResourceProfile(),
        warm_policy="auto",
        runtime_parameter_policy=default_runtime_parameter_policy("llama.cpp"),
    )


def test_locked_context_is_applied_and_cannot_be_overridden() -> None:
    bundle = _bundle()
    effective = apply_runtime_parameter_policy(
        TaskRequest(task_type="llm_text.generate", payload={"prompt": "hello"}),
        bundle,
    )
    assert effective.payload["context_length"] == 4096
    assert effective.payload["temperature"] == 0.7

    with pytest.raises(ValueError, match="context_length.*locked"):
        apply_runtime_parameter_policy(
            TaskRequest(
                task_type="llm_text.generate",
                payload={"prompt": "hello", "context_length": 8192},
            ),
            bundle,
        )


def test_editable_temperature_is_range_checked() -> None:
    with pytest.raises(ValueError, match="temperature.*maximum"):
        apply_runtime_parameter_policy(
            TaskRequest(
                task_type="llm_text.generate",
                payload={"prompt": "hello", "temperature": 3.0},
            ),
            _bundle(),
        )


def test_marketplace_projection_makes_mutability_explicit() -> None:
    projection = marketplace_parameter_policy(default_runtime_parameter_policy("llama.cpp"))

    assert projection["version"] == "runtime-parameters.v1"
    parameters = {item["name"]: item for item in projection["parameters"]}
    assert parameters["temperature"]["default"] == 0.7
    assert parameters["temperature"]["mutable"] is True
    assert parameters["temperature"]["locked"] is False
    assert parameters["context_length"]["mutable"] is False
    assert parameters["context_length"]["locked"] is True


def test_payload_policy_applies_defaults_and_rejects_locked_remote_override() -> None:
    policy = default_runtime_parameter_policy("llama.cpp")
    effective = apply_runtime_parameter_policy_payload(
        {"messages": [], "temperature": 0.25},
        policy,
    )

    assert effective["temperature"] == 0.25
    assert effective["context_length"] == 4096
    with pytest.raises(ValueError, match="context_length.*locked"):
        apply_runtime_parameter_policy_payload(
            {"context_length": 8192},
            policy,
        )


def test_llamacpp_launch_spec_contains_operator_locked_allocation_flags() -> None:
    command = LlamaCppPlugin().build_launch_spec(_bundle())["command"]
    assert "--ctx-size" in command
    assert command[command.index("--ctx-size") + 1] == "4096"
    assert "--n-gpu-layers" in command
    assert "--kv-offload" in command
    assert command[command.index("--cache-type-k") + 1] == "f16"
    assert command[command.index("--cache-type-v") + 1] == "f16"


def test_llamacpp_launch_spec_can_keep_long_context_kv_cache_on_host() -> None:
    defaults = default_runtime_parameter_policy("llama.cpp")
    bundle = _bundle().model_copy(
        update={
            "runtime_parameter_policy": {
                **defaults,
                "context_length": defaults["context_length"].model_copy(
                    update={"value": 131072}
                ),
                "kv_offload": defaults["kv_offload"].model_copy(
                    update={"value": False}
                ),
                "kv_cache_type_k": defaults["kv_cache_type_k"].model_copy(
                    update={"value": "q8_0"}
                ),
                "kv_cache_type_v": defaults["kv_cache_type_v"].model_copy(
                    update={"value": "q8_0"}
                ),
            }
        }
    )
    command = LlamaCppPlugin().build_launch_spec(bundle)["command"]
    assert command[command.index("--ctx-size") + 1] == "131072"
    assert command[command.index("--n-gpu-layers") + 1] == "99"
    assert "--no-kv-offload" in command


def test_llamacpp_launch_spec_can_keep_quantized_long_context_kv_cache_on_gpu() -> None:
    defaults = default_runtime_parameter_policy("llama.cpp")
    bundle = _bundle().model_copy(
        update={
            "runtime_parameter_policy": {
                **defaults,
                "context_length": defaults["context_length"].model_copy(
                    update={"value": 131072}
                ),
                "kv_cache_type_k": defaults["kv_cache_type_k"].model_copy(
                    update={"value": "q8_0"}
                ),
                "kv_cache_type_v": defaults["kv_cache_type_v"].model_copy(
                    update={"value": "q8_0"}
                ),
            }
        }
    )
    command = LlamaCppPlugin().build_launch_spec(bundle)["command"]
    assert "--kv-offload" in command
    assert command[command.index("--cache-type-k") + 1] == "q8_0"
    assert command[command.index("--cache-type-v") + 1] == "q8_0"


def test_hugging_face_blob_url_is_resolved_to_download_artifact() -> None:
    normalized = ModelInstallService._normalize_source(
        provider_type="llama.cpp",
        model_id="qwen.gguf",
        source_url="https://huggingface.co/org/model/blob/main/qwen.gguf",
    )
    assert normalized["resolved_source_url"].endswith("/resolve/main/qwen.gguf")


def test_hugging_face_repository_url_is_a_vllm_provider_reference() -> None:
    normalized = ModelInstallService._normalize_source(
        provider_type="vllm",
        model_id="qwen",
        source_url="https://huggingface.co/org/model",
    )
    assert normalized == {
        "source_url": "https://huggingface.co/org/model",
        "source_kind": "provider_reference",
        "provider_model_reference": "org/model",
    }


def test_hf_uri_resolves_namespace_repository_file() -> None:
    normalized = ModelInstallService._normalize_source(
        provider_type="llama.cpp",
        model_id="qwen.gguf",
        source_url="hf://org/model/qwen.gguf",
    )
    assert normalized["resolved_source_url"] == (
        "https://huggingface.co/org/model/resolve/main/qwen.gguf"
    )
