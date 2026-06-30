import pytest

from aidn_hypervisor.domain.models import BundleConfig, ResourceProfile, TaskRequest
from aidn_hypervisor.process_manager import RuntimeHandle
from aidn_hypervisor.plugins.ollama import OllamaPlugin


def _bundle(
    *,
    endpoint: str | None = "http://127.0.0.1:11434",
    launch_mode: str = "attached_service",
    workload_type: str = "llm_text",
) -> BundleConfig:
    return BundleConfig(
        bundle_id="phi4-ollama",
        plugin_id="ollama",
        provider_type="ollama",
        workload_type=workload_type,
        model_id="phi4",
        launch_mode=launch_mode,
        endpoint=endpoint,
        device_affinity="cpu",
        resource_profile=ResourceProfile(),
        warm_policy="auto",
    )


class StubOllamaPlugin(OllamaPlugin):
    def __init__(self, *, health_payload=None, invoke_payload=None, raise_error: Exception | None = None):
        self.health_payload = health_payload
        self.invoke_payload = invoke_payload
        self.raise_error = raise_error
        self.calls: list[tuple[str, str, dict | None]] = []

    def _request_json(self, method: str, url: str, payload: dict | None = None) -> dict:
        self.calls.append((method, url, payload))
        if self.raise_error is not None:
            raise self.raise_error
        if url.endswith("/api/tags"):
            return self.health_payload or {"models": []}
        if url.endswith("/api/generate"):
            return self.invoke_payload or {"response": "", "done": True}
        raise AssertionError(f"unexpected url: {url}")


def test_ollama_plugin_describes_llm_text_capability() -> None:
    plugin = OllamaPlugin()

    assert plugin.describe() == {
        "plugin_id": "ollama",
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


def test_ollama_plugin_validate_bundle_requires_endpoint() -> None:
    plugin = OllamaPlugin()

    with pytest.raises(ValueError, match="endpoint"):
        plugin.validate_bundle(_bundle(endpoint=None))


def test_ollama_plugin_validate_bundle_rejects_non_llm_workloads() -> None:
    plugin = OllamaPlugin()

    with pytest.raises(ValueError, match="llm_text"):
        plugin.validate_bundle(_bundle(workload_type="speech_to_text"))


def test_ollama_plugin_build_launch_spec_includes_endpoint_and_model_metadata() -> None:
    plugin = OllamaPlugin()

    launch_spec = plugin.build_launch_spec(_bundle())

    assert launch_spec == {
        "command": ["ollama", "serve"],
        "metadata": {
            "endpoint": "http://127.0.0.1:11434",
            "model_id": "phi4",
        },
    }


def test_ollama_plugin_estimate_resources_ignores_cold_start_and_sets_concurrency_hint() -> None:
    plugin = OllamaPlugin()
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
        "startup_transient": {},
        "runtime_resident": {"cpu": 1.0, "ram_mb": 1024, "vram_mb": 0},
        "request_active": {"cpu": 0.5, "ram_mb": 256, "vram_mb": 0},
        "concurrency_limit": 2,
    }


def test_ollama_plugin_exposes_retry_policy_for_transport_operations() -> None:
    plugin = OllamaPlugin()

    assert plugin.retry_policy() == {
        "health_check": {"max_attempts": 3, "backoff_seconds": 0.25},
        "invoke": {
            "max_attempts": 3,
            "backoff_seconds": 0.5,
            "retry_exceptions": (RuntimeError,),
        },
    }


def test_ollama_plugin_exposes_circuit_breaker_policy_for_provider_cooldown() -> None:
    plugin = OllamaPlugin()

    assert plugin.circuit_breaker_policy() == {
        "failure_threshold": 2,
        "cooldown_seconds": 30.0,
    }


def test_ollama_plugin_health_check_calls_tags_endpoint() -> None:
    plugin = StubOllamaPlugin(health_payload={"models": [{"name": "phi4"}]})
    runtime = RuntimeHandle(
        runtime_id="rt-1",
        command=["ollama", "serve"],
        status="running",
        bundle_id="phi4-ollama",
        metadata={"endpoint": "http://127.0.0.1:11434", "model_id": "phi4"},
    )

    assert plugin.health_check(runtime) is True
    assert plugin.calls == [("GET", "http://127.0.0.1:11434/api/tags", None)]


def test_ollama_plugin_health_check_returns_false_on_transport_error() -> None:
    plugin = StubOllamaPlugin(raise_error=RuntimeError("connection refused"))
    runtime = RuntimeHandle(
        runtime_id="rt-1",
        command=["ollama", "serve"],
        status="running",
        bundle_id="phi4-ollama",
        metadata={"endpoint": "http://127.0.0.1:11434", "model_id": "phi4"},
    )

    assert plugin.health_check(runtime) is False


def test_ollama_plugin_invoke_posts_prompt_and_returns_normalized_payload() -> None:
    plugin = StubOllamaPlugin(
        invoke_payload={
            "response": "Hello",
            "done": True,
            "prompt_eval_count": 7,
            "eval_count": 12,
        }
    )
    runtime = RuntimeHandle(
        runtime_id="rt-1",
        command=["ollama", "serve"],
        status="running",
        bundle_id="phi4-ollama",
        metadata={"endpoint": "http://127.0.0.1:11434", "model_id": "phi4"},
    )
    task = TaskRequest(task_type="llm_text.generate", payload={"prompt": "Hi"})

    result = plugin.invoke(task, runtime)

    assert plugin.calls == [
        (
            "POST",
            "http://127.0.0.1:11434/api/generate",
            {"model": "phi4", "prompt": "Hi", "stream": False},
        )
    ]
    assert result == {
        "ok": True,
        "task_type": "llm_text.generate",
        "model_id": "phi4",
        "output_text": "Hello",
        "done": True,
        "usage": {
            "input_tokens": 7,
            "output_tokens": 12,
            "fixed_request_count": 1,
            "measurement_kind": "exact",
            "measurement_source": "provider_api",
        },
        "raw": {
            "response": "Hello",
            "done": True,
            "prompt_eval_count": 7,
            "eval_count": 12,
        },
    }


def test_ollama_plugin_invoke_requires_prompt_payload() -> None:
    plugin = StubOllamaPlugin()
    runtime = RuntimeHandle(
        runtime_id="rt-1",
        command=["ollama", "serve"],
        status="running",
        bundle_id="phi4-ollama",
        metadata={"endpoint": "http://127.0.0.1:11434", "model_id": "phi4"},
    )
    task = TaskRequest(task_type="llm_text.generate", payload={})

    with pytest.raises(ValueError, match="prompt"):
        plugin.invoke(task, runtime)
