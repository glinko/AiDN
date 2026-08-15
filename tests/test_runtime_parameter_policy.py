import pytest

from aidn_hypervisor.domain.models import BundleConfig, ResourceProfile, TaskRequest
from aidn_hypervisor.model_install_service import ModelInstallService
from aidn_hypervisor.plugins.llamacpp import LlamaCppPlugin
from aidn_hypervisor.runtime_parameter_policy import (
    apply_runtime_parameter_policy,
    default_runtime_parameter_policy,
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


def test_llamacpp_launch_spec_contains_operator_locked_allocation_flags() -> None:
    command = LlamaCppPlugin().build_launch_spec(_bundle())["command"]
    assert "--ctx-size" in command
    assert command[command.index("--ctx-size") + 1] == "4096"
    assert "--n-gpu-layers" in command


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
