import pytest

from aidn_hypervisor.domain.models import BundleConfig, ResourceProfile, TaskRequest
from aidn_hypervisor.plugins.llamacpp import LlamaCppPlugin
from aidn_hypervisor.process_manager import RuntimeHandle


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
    def __init__(
        self,
        *,
        health_payload=None,
        completion_payload=None,
        chat_payload=None,
        raise_error: Exception | None = None,
    ):
        self.health_payload = health_payload
        self.completion_payload = completion_payload
        self.chat_payload = chat_payload
        self.raise_error = raise_error
        self.calls: list[tuple[str, str, dict | None]] = []
        self.timeouts: list[float] = []

    def _request_json(
        self,
        method: str,
        url: str,
        payload: dict | None = None,
        *,
        timeout_seconds: float = 5,
    ) -> dict:
        self.calls.append((method, url, payload))
        self.timeouts.append(timeout_seconds)
        if self.raise_error is not None:
            raise self.raise_error
        if url.endswith("/health"):
            return self.health_payload or {"status": "ok"}
        if url.endswith("/completion"):
            return self.completion_payload or {"content": ""}
        if url.endswith("/v1/chat/completions"):
            return self.chat_payload or {"choices": [{"message": {"content": ""}}]}
        if url.endswith("/v1/models"):
            return {"data": [{"id": "qwen3.6"}]}
        raise AssertionError(f"unexpected url: {url}")


def test_llamacpp_plugin_describes_llm_text_capability() -> None:
    plugin = LlamaCppPlugin()

    description = plugin.describe()

    assert description["plugin_id"] == "llama.cpp"
    assert description["plugin_version"] == "0.2.0"
    assert description["plugin_capability_flags"] == [
        "CAN_ATTACH_EXISTING",
        "CAN_INSTALL_PROVIDER",
        "CAN_DISCOVER_MODELS",
    ]
    assert description["installation_recipes"][0]["recipe_id"] == ("llamacpp-ubuntu-cpu")
    assert description["runtime_installers"][0]["pinned_version"] == "b10433"


def test_llamacpp_plugin_builds_reviewed_ubuntu_install_plan() -> None:
    plan = LlamaCppPlugin().build_installation_plan({})

    assert plan["plugin_id"] == "llama.cpp"
    assert plan["processes"] == []
    assert plan["model_downloads"] == []
    assert plan["health_checks"][0]["url"] == "http://127.0.0.1:8080/health"


def test_llamacpp_plugin_rejects_unreviewed_backend() -> None:
    with pytest.raises(ValueError, match="backend"):
        LlamaCppPlugin().build_installation_plan({"backend": "shell"})


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


def test_llamacpp_plugin_projects_deployment_to_rfc0054_runtime_adapter() -> None:
    projection = LlamaCppPlugin().create_runtime_binding(
        model_deployment={
            "model_deployment_id": "model-1",
            "provider_instance_id": "provider-1",
            "provider_model_reference": "qwen3.6",
        },
        capability_id="llm.chat",
        capability_version="1.0",
        capability_definition_hash="capability-hash",
    )

    assert projection["adapter_id"] == "llamacpp-openai"
    assert projection["adapter_version"] == "llamacpp-openai.v1"
    assert projection["supported_features"] == ["streaming", "cancellation"]
    assert projection["supported_accounting_modes"] == [
        "provider_metered",
        "fixed_price",
        "observable",
    ]
    assert projection["compatibility_bundle"] == {
        "plugin_id": "llama.cpp",
        "provider_type": "llama.cpp",
        "workload_type": "llm_text",
        "model_id": "qwen3.6",
        "launch_mode": "managed_process",
        "device_affinity": "cpu",
    }


def test_llamacpp_plugin_attaches_existing_openai_compatible_provider() -> None:
    attached = LlamaCppPlugin().attach_existing_provider({"base_url": "http://127.0.0.1:9000/"})

    assert attached == {
        "configuration": {
            "base_url": "http://127.0.0.1:9000/",
            "endpoint": "http://127.0.0.1:9000",
        },
        "connection_mode": "attached",
        "operational_state": "ready",
    }


def test_llamacpp_plugin_rejects_credentialed_or_non_http_attach_endpoint() -> None:
    plugin = LlamaCppPlugin()

    with pytest.raises(ValueError, match="credentials"):
        plugin.attach_existing_provider({"endpoint": "https://user:secret@example.test"})
    with pytest.raises(ValueError, match="absolute HTTP"):
        plugin.attach_existing_provider({"endpoint": "ssh://example.test"})


def test_llamacpp_plugin_discovers_openai_compatible_models() -> None:
    plugin = StubLlamaCppPlugin()

    models = plugin.discover_models({"configuration": {"endpoint": "http://127.0.0.1:9000"}})

    assert models == [
        {
            "provider_model_reference": "qwen3.6",
            "operator_display_name": "qwen3.6",
            "metadata_sources": {"provider": "llamacpp-v1-models"},
            "capability_bindings": ["llm.chat"],
            "operational_state": "ready",
        }
    ]
    assert plugin.calls == [("GET", "http://127.0.0.1:9000/v1/models", None)]


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


def test_llamacpp_plugin_uses_operator_configured_server_binary(monkeypatch) -> None:
    configured_binary = "/opt/aidn/providers/llama.cpp/bin/llama-server"
    monkeypatch.setenv("AIDN_LLAMA_CPP_SERVER_BIN", configured_binary)

    launch_spec = LlamaCppPlugin().build_launch_spec(_bundle())

    assert launch_spec["command"][0] == configured_binary


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


def test_llamacpp_plugin_invoke_uses_chat_completions_for_role_separated_messages() -> None:
    plugin = StubLlamaCppPlugin(
        chat_payload={
            "choices": [{"message": {"content": "The model is ready."}}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 6},
        }
    )
    runtime = RuntimeHandle(
        runtime_id="rt-1",
        command=["llama-server"],
        status="running",
        bundle_id="phi4-llamacpp",
        metadata={"endpoint": "http://127.0.0.1:8080", "model_id": "C:/models/phi4.gguf"},
    )
    messages = [
        {"role": "system", "content": "You are a safe local assistant."},
        {"role": "user", "content": "What is working?"},
    ]
    task = TaskRequest(
        task_type="llm_text.generate",
        payload={
            "prompt": "legacy fallback",
            "messages": messages,
            "temperature": 0.0,
            "top_p": 0.8,
            "max_tokens": 96,
            "chat_template_kwargs": {"enable_thinking": False},
        },
    )

    result = plugin.invoke(task, runtime)

    assert plugin.calls == [
        (
            "POST",
            "http://127.0.0.1:8080/v1/chat/completions",
            {
                "model": "C:/models/phi4.gguf",
                "messages": messages,
                "stream": False,
                "temperature": 0.0,
                "top_p": 0.8,
                "max_tokens": 96,
                "chat_template_kwargs": {"enable_thinking": False},
            },
        )
    ]
    assert result["output_text"] == "The model is ready."
    assert result["usage"]["input_tokens"] == 11
    assert result["usage"]["output_tokens"] == 6


def test_llamacpp_plugin_preserves_openai_tool_contract_and_response_calls() -> None:
    tool_definition = {
        "type": "function",
        "function": {
            "name": "terminal",
            "parameters": {"type": "object"},
        },
    }
    native_call = {
        "id": "call-1",
        "type": "function",
        "function": {"name": "terminal", "arguments": '{"command":"hostname"}'},
    }
    plugin = StubLlamaCppPlugin(
        chat_payload={
            "choices": [{"message": {"content": None, "tool_calls": [native_call]}}]
        }
    )
    runtime = RuntimeHandle(
        runtime_id="rt-1",
        command=["llama-server"],
        status="running",
        bundle_id="phi4-llamacpp",
        metadata={"endpoint": "http://127.0.0.1:8080", "model_id": "C:/models/phi4.gguf"},
    )

    result = plugin.invoke(
        TaskRequest(
            task_type="llm_text.generate",
            payload={
                "messages": [{"role": "user", "content": "Inspect the host"}],
                "tools": [tool_definition],
                "tool_choice": "auto",
                "parallel_tool_calls": False,
            },
        ),
        runtime,
    )

    payload = plugin.calls[-1][2]
    assert payload is not None
    assert payload["tools"] == [tool_definition]
    assert payload["tool_choice"] == "auto"
    assert payload["parallel_tool_calls"] is False
    assert result["tool_calls"] == [native_call]


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


def test_llamacpp_plugin_invoke_accepts_messages_without_legacy_prompt() -> None:
    plugin = StubLlamaCppPlugin(chat_payload={"choices": [{"message": {"content": "chat-only"}}]})
    runtime = RuntimeHandle(
        runtime_id="rt-1",
        command=["llama-server"],
        status="running",
        bundle_id="phi4-llamacpp",
        metadata={"endpoint": "http://127.0.0.1:8080", "model_id": "C:/models/phi4.gguf"},
    )

    result = plugin.invoke(
        TaskRequest(
            task_type="llm_text.generate",
            payload={"messages": [{"role": "user", "content": "Hi"}]},
        ),
        runtime,
    )

    assert result["output_text"] == "chat-only"


def test_llamacpp_plugin_honors_bounded_per_request_transport_timeout() -> None:
    plugin = StubLlamaCppPlugin(chat_payload={"choices": [{"message": {"content": "ok"}}]})
    runtime = RuntimeHandle(
        runtime_id="rt-1",
        command=["llama-server"],
        status="running",
        bundle_id="phi4-llamacpp",
        metadata={
            "endpoint": "http://127.0.0.1:8080",
            "model_id": "C:/models/phi4.gguf",
            "timeout_seconds": 90,
        },
    )

    plugin.invoke(
        TaskRequest(
            task_type="llm_text.generate",
            payload={
                "messages": [{"role": "user", "content": "Hi"}],
                "provider_timeout_seconds": 24,
            },
        ),
        runtime,
    )

    assert plugin.timeouts[-1] == 24.0


def test_llamacpp_plugin_uses_long_context_safe_default_timeout() -> None:
    plugin = StubLlamaCppPlugin(chat_payload={"choices": [{"message": {"content": "ok"}}]})
    runtime = RuntimeHandle(
        runtime_id="rt-1",
        command=["llama-server"],
        status="running",
        bundle_id="phi4-llamacpp",
        metadata={
            "endpoint": "http://127.0.0.1:8080",
            "model_id": "C:/models/phi4.gguf",
        },
    )

    plugin.invoke(
        TaskRequest(
            task_type="llm_text.generate",
            payload={"messages": [{"role": "user", "content": "Hi"}]},
        ),
        runtime,
    )

    assert plugin.timeouts[-1] == 300.0


def test_llamacpp_partial_usage_does_not_invent_unknown_tokens() -> None:
    usage = LlamaCppPlugin()._usage_from_response({"tokens_evaluated": 7})

    assert usage == {
        "input_tokens": 7,
        "fixed_request_count": 1,
        "measurement_kind": "estimated",
        "measurement_source": "provider_api_partial",
    }
