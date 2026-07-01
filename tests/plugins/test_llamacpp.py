import pytest

from aidn_hypervisor.domain.models import BundleConfig, ResourceProfile, TaskRequest
from aidn_hypervisor.process_manager import RuntimeHandle
from aidn_hypervisor.plugins.llamacpp import LlamaCppPlugin


def _bundle(
    *,
    endpoint: str | None = "http://127.0.0.1:8080",
    launch_mode: str = "managed_process",
    workload_type: str = "llm_text",
    model_id: str = "C:/models/phi4.gguf",
) -> BundleConfig:
    return BundleConfig(
        bundle_id="phi4-llamacpp",
        plugin_id="llama.cpp",
        provider_type="llama.cpp",
        workload_type=workload_type,
        model_id=model_id,
        launch_mode=launch_mode,
        endpoint=endpoint,
        device_affinity="cpu",
        resource_profile=ResourceProfile(),
        warm_policy="auto",
    )


class StubLlamaCppPlugin(LlamaCppPlugin):
    def __init__(self, *, health_payload=None, completion_payload=None, raise_error: Exception | None = None):
        self.health_payload = health_payload
        self.completion_payload = completion_payload
        self.raise_error = raise_error
        self.calls: list[tuple[str, str, dict | None]] = []

    def _request_json(self, method: str, url: str, payload: dict | None = None) -> dict:
        self.calls.append((method, url, payload))
        if self.raise_error is not None:
            raise self.raise_error
        if url.endswith("/health"):
            return self.health_payload or {"status": "ok"}
        if url.endswith("/completion"):
            return self.completion_payload or {"content": ""}
        raise AssertionError(f"unexpected url: {url}")


def test_llamacpp_plugin_describes_llm_text_capability() -> None:
    plugin = LlamaCppPlugin()

    assert plugin.describe() == {
        "plugin_id": "llama.cpp",
        "workload_types": ["llm_text"],
        "usage_contract": {
            "supports_exact": True,
            "supports_estimated": True,
            "default_measurement_source": "provider_api",
            "fallback_measurement_source": "provider_api_partial",
            "fallback_policy": "partial_response_estimate",
            "missing_usage_behavior": "skip",
        },
    }


def test_llamacpp_plugin_validate_bundle_requires_endpoint() -> None:
    plugin = LlamaCppPlugin()

    with pytest.raises(ValueError, match="endpoint"):
        plugin.validate_bundle(_bundle(endpoint=None))


def test_llamacpp_plugin_validate_bundle_rejects_non_llm_workloads() -> None:
    plugin = LlamaCppPlugin()

    with pytest.raises(ValueError, match="llm_text"):
        plugin.validate_bundle(_bundle(workload_type="speech_to_text"))


def test_llamacpp_plugin_validate_bundle_rejects_non_managed_launch_mode() -> None:
    plugin = LlamaCppPlugin()

    with pytest.raises(ValueError, match="managed_process"):
        plugin.validate_bundle(_bundle(launch_mode="attached_service"))


def test_llamacpp_plugin_build_launch_spec_derives_host_and_port_from_endpoint() -> None:
    plugin = LlamaCppPlugin()

    launch_spec = plugin.build_launch_spec(_bundle())

    assert launch_spec == {
        "command": [
            "llama-server",
            "--model",
            "C:/models/phi4.gguf",
            "--host",
            "127.0.0.1",
            "--port",
            "8080",
        ],
        "metadata": {
            "endpoint": "http://127.0.0.1:8080",
            "model_id": "C:/models/phi4.gguf",
        },
    }


def test_llamacpp_plugin_estimate_resources_keeps_cold_start_and_sets_concurrency_hint() -> None:
    plugin = LlamaCppPlugin()
    bundle = _bundle().model_copy(
        update={
            "resource_profile": ResourceProfile(
                cold_start_cpu=2.0,
                cold_start_ram_mb=4096,
                steady_cpu=1.0,
                steady_ram_mb=1024,
                per_request_cpu=0.5,
                per_request_ram_mb=256,
            )
        }
    )
    task = TaskRequest(task_type="llm_text.generate", payload={"prompt": "Hi"})

    estimate = plugin.estimate_resources(task, bundle, runtime_state=None)

    assert estimate == {
        "startup_transient": {"cpu": 2.0, "ram_mb": 4096, "vram_mb": 0},
        "runtime_resident": {"cpu": 1.0, "ram_mb": 1024, "vram_mb": 0},
        "request_active": {"cpu": 0.5, "ram_mb": 256, "vram_mb": 0},
        "concurrency_limit": 1,
    }


def test_llamacpp_plugin_exposes_retry_policy_for_transport_operations() -> None:
    plugin = LlamaCppPlugin()

    assert plugin.retry_policy() == {
        "health_check": {"max_attempts": 3, "backoff_seconds": 0.25},
        "invoke": {
            "max_attempts": 3,
            "backoff_seconds": 0.5,
            "retry_exceptions": (RuntimeError,),
        },
    }


def test_llamacpp_plugin_exposes_circuit_breaker_policy_for_provider_cooldown() -> None:
    plugin = LlamaCppPlugin()

    assert plugin.circuit_breaker_policy() == {
        "failure_threshold": 2,
        "cooldown_seconds": 30.0,
    }


def test_llamacpp_plugin_health_check_calls_health_endpoint() -> None:
    plugin = StubLlamaCppPlugin(health_payload={"status": "ok"})
    runtime = RuntimeHandle(
        runtime_id="rt-1",
        command=["llama-server"],
        status="running",
        bundle_id="phi4-llamacpp",
        metadata={"endpoint": "http://127.0.0.1:8080", "model_id": "C:/models/phi4.gguf"},
    )

    assert plugin.health_check(runtime) is True
    assert plugin.calls == [("GET", "http://127.0.0.1:8080/health", None)]


def test_llamacpp_plugin_health_check_returns_false_on_transport_error() -> None:
    plugin = StubLlamaCppPlugin(raise_error=RuntimeError("connection refused"))
    runtime = RuntimeHandle(
        runtime_id="rt-1",
        command=["llama-server"],
        status="running",
        bundle_id="phi4-llamacpp",
        metadata={"endpoint": "http://127.0.0.1:8080", "model_id": "C:/models/phi4.gguf"},
    )

    assert plugin.health_check(runtime) is False


def test_llamacpp_plugin_invoke_posts_prompt_and_returns_normalized_payload() -> None:
    plugin = StubLlamaCppPlugin(
        completion_payload={
            "content": "Hello from llama.cpp",
            "tokens_evaluated": 7,
            "tokens_predicted": 12,
        }
    )
    runtime = RuntimeHandle(
        runtime_id="rt-1",
        command=["llama-server"],
        status="running",
        bundle_id="phi4-llamacpp",
        metadata={"endpoint": "http://127.0.0.1:8080", "model_id": "C:/models/phi4.gguf"},
    )
    task = TaskRequest(task_type="llm_text.generate", payload={"prompt": "Hi"})

    result = plugin.invoke(task, runtime)

    assert plugin.calls == [
        (
            "POST",
            "http://127.0.0.1:8080/completion",
            {"prompt": "Hi", "stream": False},
        )
    ]
    assert result == {
        "ok": True,
        "task_type": "llm_text.generate",
        "model_id": "C:/models/phi4.gguf",
        "output_text": "Hello from llama.cpp",
        "usage": {
            "input_tokens": 7,
            "output_tokens": 12,
            "fixed_request_count": 1,
            "measurement_kind": "exact",
            "measurement_source": "provider_api",
        },
        "raw": {
            "content": "Hello from llama.cpp",
            "tokens_evaluated": 7,
            "tokens_predicted": 12,
        },
    }


def test_llamacpp_plugin_invoke_requires_prompt_payload() -> None:
    plugin = StubLlamaCppPlugin()
    runtime = RuntimeHandle(
        runtime_id="rt-1",
        command=["llama-server"],
        status="running",
        bundle_id="phi4-llamacpp",
        metadata={"endpoint": "http://127.0.0.1:8080", "model_id": "C:/models/phi4.gguf"},
    )
    task = TaskRequest(task_type="llm_text.generate", payload={})

    with pytest.raises(ValueError, match="prompt"):
        plugin.invoke(task, runtime)
