import pytest

from aidn_hypervisor.domain.models import BundleConfig, ResourceProfile, TaskRequest
from aidn_hypervisor.plugins.vllm import VllmPlugin
from aidn_hypervisor.process_manager import RuntimeHandle


class StubVllmPlugin(VllmPlugin):
    def __init__(self) -> None:
        self.request_kwargs: list[dict] = []

    def _request_json(
        self,
        method: str,
        url: str,
        payload: dict | None = None,
        **kwargs,
    ) -> dict:
        self.request_kwargs.append(dict(kwargs))
        if url.endswith("/v1/completions"):
            return {"model": "qwen", "choices": [{"text": "ok"}], "usage": {}}
        return {"data": []}


class UnreachableVllmPlugin(VllmPlugin):
    def _request_json(
        self,
        method: str,
        url: str,
        payload: dict | None = None,
        **kwargs,
    ) -> dict:
        raise RuntimeError("<urlopen error [Errno 111] Connection refused>")


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


def test_vllm_plugin_builds_reviewed_ubuntu_cuda_install_plan() -> None:
    plugin = VllmPlugin()
    manifest = plugin.plugin_manifest()
    plan = plugin.build_installation_plan({})

    assert "CAN_INSTALL_PROVIDER" in manifest["plugin_capability_flags"]
    assert manifest["installation_recipes"][0]["recipe_id"] == "vllm-ubuntu-cuda"
    assert manifest["runtime_installers"][0]["pinned_version"] == "0.27.1"
    assert plan["processes"] == []
    assert plan["model_downloads"] == []
    assert plan["resource_limits"] == {"accelerator": "cuda"}


def test_vllm_plugin_rejects_unreviewed_managed_backend() -> None:
    with pytest.raises(ValueError, match="requires cuda"):
        VllmPlugin().build_installation_plan({"backend": "rocm"})


def test_vllm_partial_usage_does_not_invent_unknown_tokens() -> None:
    usage = VllmPlugin._usage_from_response({"prompt_tokens": 7})

    assert usage == {
        "input_tokens": 7,
        "fixed_request_count": 1,
        "measurement_kind": "estimated",
        "measurement_source": "provider_api_partial",
    }


def test_vllm_plugin_invoke_uses_runtime_execution_timeout() -> None:
    plugin = StubVllmPlugin()
    runtime = RuntimeHandle(
        runtime_id="rt-1",
        command=["vllm", "serve"],
        status="running",
        bundle_id="qwen-vllm",
        metadata={
            "endpoint": "http://127.0.0.1:8000",
            "model_id": "qwen",
            "timeout_seconds": 37,
        },
    )

    result = plugin.invoke(TaskRequest(task_type="llm_text.generate", payload={"prompt": "Hi"}), runtime)

    assert result["output_text"] == "ok"
    assert plugin.request_kwargs == [{"timeout_seconds": 37.0}]


def test_vllm_health_diagnostic_explains_unreachable_endpoint() -> None:
    plugin = UnreachableVllmPlugin()
    runtime = RuntimeHandle(
        runtime_id="provider-health",
        command=[],
        status="running",
        metadata={"endpoint": "http://127.0.0.1:11234"},
    )

    diagnostic = plugin.health_check_diagnostic(runtime)

    assert diagnostic["healthy"] is False
    assert diagnostic["code"] == "provider_endpoint_unreachable"
    assert diagnostic["probe_url"] == "http://127.0.0.1:11234/v1/models"
    assert "Start vLLM with a model" in diagnostic["message"]
