import pytest

from aidn_hypervisor.domain.models import BundleConfig, ResourceProfile, TaskRequest
from aidn_hypervisor.plugins.vllm import VllmPlugin


def _bundle() -> BundleConfig:
    return BundleConfig(
        bundle_id="qwen-vllm",
        plugin_id="vllm",
        provider_type="vllm",
        workload_type="llm_text",
        model_id="qwen",
        launch_mode="attached_service",
        endpoint="http://127.0.0.1:8000",
        device_affinity="gpu",
        resource_profile=ResourceProfile(steady_cpu=1, steady_ram_mb=1024, steady_vram_mb=2048),
        warm_policy="auto",
    )


def test_vllm_plugin_is_attached_only_and_projects_runtime_binding() -> None:
    plugin = VllmPlugin()
    bundle = _bundle()

    plugin.validate_bundle(bundle)
    with pytest.raises(ValueError, match="does not manage local process launch"):
        plugin.build_launch_spec(bundle)
    assert (
        plugin.estimate_resources(TaskRequest(task_type="llm_text.generate", payload={"prompt": "hi"}), bundle, None)[
            "concurrency_limit"
        ]
        == 2
    )
    assert (
        plugin.create_runtime_binding(
            model_deployment={
                "model_deployment_id": "model-1",
                "provider_instance_id": "provider-1",
                "provider_model_reference": "qwen",
            },
            capability_id="llm.chat",
            capability_version="1.0",
            capability_definition_hash="hash",
        )["adapter_id"]
        == "vllm-openai"
    )


def test_vllm_partial_usage_does_not_invent_unknown_tokens() -> None:
    usage = VllmPlugin._usage_from_response({"prompt_tokens": 7})

    assert usage == {
        "input_tokens": 7,
        "fixed_request_count": 1,
        "measurement_kind": "estimated",
        "measurement_source": "provider_api_partial",
    }
