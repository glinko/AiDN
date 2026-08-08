import base64

import pytest

from aidn_hypervisor.domain.models import BundleConfig, ResourceProfile, TaskRequest
from aidn_hypervisor.plugins.registry import PluginRegistry
from aidn_hypervisor.plugins.whisper import WhisperPlugin
from aidn_hypervisor.process_manager import RuntimeHandle
from aidn_hypervisor.providers.service import ProviderInventoryService
from aidn_hypervisor.providers.store import InMemoryProviderInventoryStore


def _bundle(
    *,
    endpoint: str | None = "http://127.0.0.1:9000",
    launch_mode: str = "attached_service",
    workload_type: str = "speech_to_text",
) -> BundleConfig:
    return BundleConfig(
        bundle_id="whisper-local",
        plugin_id="whisper",
        provider_type="whisper",
        workload_type=workload_type,
        model_id="large-v3",
        launch_mode=launch_mode,
        endpoint=endpoint,
        device_affinity="cpu",
        resource_profile=ResourceProfile(),
        warm_policy="auto",
    )


class StubWhisperPlugin(WhisperPlugin):
    def __init__(self, *, health_payload=None, transcribe_payload=None, raise_error: Exception | None = None):
        self.health_payload = health_payload
        self.transcribe_payload = transcribe_payload
        self.raise_error = raise_error
        self.calls: list[tuple[str, str, dict | None]] = []
        self.multipart_calls: list[tuple[str, bytes, str]] = []

    def _request_json(self, method: str, url: str, payload: dict | None = None) -> dict:
        self.calls.append((method, url, payload))
        if self.raise_error is not None:
            raise self.raise_error
        if url.endswith("/health") or url.endswith("/openapi.json"):
            return self.health_payload or {"status": "ok"}
        if url.endswith("/v1/audio/transcriptions"):
            return self.transcribe_payload or {"text": ""}
        raise AssertionError(f"unexpected url: {url}")

    def _request_multipart(
        self, method: str, url: str, body: bytes, *, content_type: str
    ) -> dict:
        self.multipart_calls.append((url, body, content_type))
        if self.raise_error is not None:
            raise self.raise_error
        return self.transcribe_payload or {"text": ""}


def test_whisper_plugin_describes_speech_to_text_capability() -> None:
    plugin = WhisperPlugin()

    description = plugin.describe()

    assert description["plugin_id"] == "whisper"
    assert description["plugin_version"] == "0.2.0"
    assert description["workload_types"] == ["speech_to_text"]
    assert description["supported_aidn_capabilities"] == ["speech_to_text"]
    assert description["plugin_capability_flags"] == [
        "CAN_ATTACH_EXISTING",
        "CAN_INSTALL_PROVIDER",
        "CAN_DISCOVER_MODELS",
    ]
    assert description["installation_recipes"][0]["recipe_id"] == "whisper-local-http"
    assert (
        description["installation_recipes"][0]["provider_configuration"]["api_format"]
        == "whisper_asr_webservice"
    )
    assert description["usage_contract"] == {
        "supports_exact": False,
        "supports_estimated": True,
        "supported_billing_units": ["audio_input_seconds"],
        "supported_accounting_modes": ["fixed_price", "observable"],
        "default_measurement_source": "provider_request",
        "fallback_measurement_source": "provider_request",
        "fallback_policy": "fixed_request_estimate",
        "missing_usage_behavior": "skip",
    }


def test_whisper_plugin_builds_bounded_managed_install_plan() -> None:
    plugin = WhisperPlugin()
    configuration = {
        "display_name": "Local Whisper",
        "endpoint": "http://127.0.0.1:9000",
        "model_id": "small",
    }

    plan = plugin.build_installation_plan(configuration)

    assert plan["plugin_id"] == "whisper"
    assert plan["containers"] == []
    assert plan["processes"] == []
    assert plan["unsupported_actions"] == []
    assert plan["health_checks"] == [
        {
            "type": "http",
            "url": "http://127.0.0.1:9000/openapi.json",
            "timeout_seconds": 5,
        }
    ]
    assert plan["required_permissions"][0]["permission_id"] == "network.private"
    assert plugin.plugin_manifest()["package_digest"].startswith("sha256:")


def test_whisper_managed_plan_checks_native_asr_openapi() -> None:
    plan = WhisperPlugin().build_installation_plan(
        {
            "display_name": "Managed Whisper",
            "endpoint": "http://127.0.0.1:9000",
            "model_id": "base",
            "api_format": "whisper_asr_webservice",
        }
    )

    assert plan["health_checks"][0]["url"] == "http://127.0.0.1:9000/openapi.json"


def test_whisper_plugin_discovers_declared_model_and_builds_attached_binding() -> None:
    plugin = WhisperPlugin()
    instance = {
        "provider_instance_id": "pi-whisper",
        "configuration": {
            "endpoint": "http://127.0.0.1:9000",
            "model_id": "small",
        },
    }

    deployment = plugin.discover_models(instance)[0]
    binding = plugin.create_runtime_binding(
        model_deployment=deployment,
        capability_id="speech_to_text",
        capability_version="1.0.0",
        capability_definition_hash="sha256:capability",
    )

    assert deployment["provider_model_reference"] == "small"
    assert deployment["capability_bindings"] == ["speech_to_text"]
    assert binding["compatibility_bundle"]["workload_type"] == "speech_to_text"
    assert binding["compatibility_bundle"]["launch_mode"] == "attached_service"


def test_whisper_managed_binding_preserves_provider_api_format() -> None:
    binding = WhisperPlugin().create_runtime_binding(
        model_deployment={
            "model_deployment_id": "md-whisper",
            "provider_instance_id": "pi-whisper",
            "provider_model_reference": "base",
            "provider_configuration": {
                "api_format": "whisper_asr_webservice",
            },
        },
        capability_id="speech_to_text",
        capability_version="1.0.0",
        capability_definition_hash="sha256:capability",
    )

    assert binding["compatibility_bundle"]["provider_api_format"] == (
        "whisper_asr_webservice"
    )


def test_whisper_managed_plan_can_be_approved_applied_and_discovered() -> None:
    registry = PluginRegistry()
    registry.register(WhisperPlugin())
    service = ProviderInventoryService(
        plugins=registry,
        store=InMemoryProviderInventoryStore(),
    )
    configuration = {
        "display_name": "Local Whisper",
        "endpoint": "http://127.0.0.1:9000",
        "model_id": "small",
    }

    diagnostics = service.run_installation_diagnostics(
        plugin_id="whisper",
        configuration=configuration,
        approved_permissions=["network.private"],
    )
    approval = service.approve_installation_plan(
        "whisper",
        configuration,
        approved_permissions=["network.private"],
    )
    job = service.apply_installation_approval(approval.approval_id)
    models = service.discover_models(job.provider_instance_id)

    assert diagnostics.readiness_status == "ACTION_REQUIRED"
    assert approval.acknowledged_package_verification["status"] == "UNVERIFIED"
    assert job.status == "SUCCEEDED"
    assert job.provider_instance_id is not None
    assert models[0].provider_model_reference == "small"


def test_whisper_plugin_validate_bundle_requires_endpoint() -> None:
    plugin = WhisperPlugin()

    with pytest.raises(ValueError, match="endpoint"):
        plugin.validate_bundle(_bundle(endpoint=None))


def test_whisper_plugin_validate_bundle_rejects_non_speech_workloads() -> None:
    plugin = WhisperPlugin()

    with pytest.raises(ValueError, match="speech_to_text"):
        plugin.validate_bundle(_bundle(workload_type="llm_text"))


def test_whisper_plugin_build_launch_spec_includes_endpoint_and_model_metadata() -> None:
    plugin = WhisperPlugin()

    launch_spec = plugin.build_launch_spec(_bundle())

    assert launch_spec == {
        "command": ["whisper-server"],
        "metadata": {
            "endpoint": "http://127.0.0.1:9000",
            "model_id": "large-v3",
        },
    }


def test_whisper_plugin_estimate_resources_ignores_cold_start_and_sets_concurrency_hint() -> None:
    plugin = WhisperPlugin()
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
    task = TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip.wav"})

    estimate = plugin.estimate_resources(task, bundle, runtime_state=None)

    assert estimate == {
        "startup_transient": {},
        "runtime_resident": {"cpu": 1.0, "ram_mb": 1024, "vram_mb": 0},
        "request_active": {"cpu": 0.5, "ram_mb": 256, "vram_mb": 0},
        "concurrency_limit": 1,
    }


def test_whisper_plugin_exposes_retry_policy_for_transport_operations() -> None:
    plugin = WhisperPlugin()

    assert plugin.retry_policy() == {
        "health_check": {"max_attempts": 3, "backoff_seconds": 0.25},
        "invoke": {
            "max_attempts": 3,
            "backoff_seconds": 0.5,
            "retry_exceptions": (RuntimeError,),
        },
    }


def test_whisper_plugin_exposes_circuit_breaker_policy_for_provider_cooldown() -> None:
    plugin = WhisperPlugin()

    assert plugin.circuit_breaker_policy() == {
        "failure_threshold": 2,
        "cooldown_seconds": 30.0,
    }


def test_whisper_plugin_health_check_calls_health_endpoint() -> None:
    plugin = StubWhisperPlugin(health_payload={"status": "ok"})
    runtime = RuntimeHandle(
        runtime_id="rt-1",
        command=["whisper-server"],
        status="running",
        bundle_id="whisper-local",
        metadata={"endpoint": "http://127.0.0.1:9000", "model_id": "large-v3"},
    )

    assert plugin.health_check(runtime) is True
    assert plugin.calls == [("GET", "http://127.0.0.1:9000/health", None)]


def test_whisper_native_asr_health_check_uses_openapi_contract() -> None:
    plugin = StubWhisperPlugin(health_payload={"paths": {"/asr": {}}})
    runtime = RuntimeHandle(
        runtime_id="rt-1",
        command=["whisper-server"],
        status="running",
        bundle_id="whisper-local",
        metadata={
            "endpoint": "http://127.0.0.1:9000",
            "model_id": "base",
            "api_format": "whisper_asr_webservice",
        },
    )

    assert plugin.health_check(runtime) is True
    assert plugin.calls == [("GET", "http://127.0.0.1:9000/openapi.json", None)]


def test_whisper_plugin_health_check_returns_false_on_transport_error() -> None:
    plugin = StubWhisperPlugin(raise_error=RuntimeError("connection refused"))
    runtime = RuntimeHandle(
        runtime_id="rt-1",
        command=["whisper-server"],
        status="running",
        bundle_id="whisper-local",
        metadata={"endpoint": "http://127.0.0.1:9000", "model_id": "large-v3"},
    )

    assert plugin.health_check(runtime) is False


def test_whisper_plugin_invoke_posts_audio_ref_and_returns_normalized_payload() -> None:
    plugin = StubWhisperPlugin(
        transcribe_payload={"text": "hello world", "language": "en"}
    )
    runtime = RuntimeHandle(
        runtime_id="rt-1",
        command=["whisper-server"],
        status="running",
        bundle_id="whisper-local",
        metadata={"endpoint": "http://127.0.0.1:9000", "model_id": "large-v3"},
    )
    task = TaskRequest(
        task_type="audio.transcribe",
        payload={"audio_ref": "C:/audio/clip.wav"},
    )

    result = plugin.invoke(task, runtime)

    assert plugin.calls == [
        (
            "POST",
            "http://127.0.0.1:9000/v1/audio/transcriptions",
            {"model": "large-v3", "audio_ref": "C:/audio/clip.wav"},
        )
    ]
    assert result == {
        "ok": True,
        "task_type": "audio.transcribe",
        "model_id": "large-v3",
        "text": "hello world",
        "usage": {
            "fixed_request_count": 1,
            "measurement_kind": "estimated",
            "measurement_source": "provider_request",
        },
        "raw": {"text": "hello world", "language": "en"},
    }


def test_whisper_plugin_records_provider_duration_without_inventing_tokens() -> None:
    plugin = StubWhisperPlugin(
        transcribe_payload={"text": "hello world", "duration_seconds": 12.5}
    )
    runtime = RuntimeHandle(
        runtime_id="rt-1",
        command=["whisper-server"],
        status="running",
        bundle_id="whisper-local",
        metadata={"endpoint": "http://127.0.0.1:9000", "model_id": "large-v3"},
    )

    result = plugin.invoke(
        TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip.wav"}),
        runtime,
    )

    assert result["usage"] == {
        "fixed_request_count": 1,
        "audio_input_seconds": 12.5,
        "measurement_kind": "estimated",
        "measurement_source": "provider_response.duration",
    }


def test_whisper_native_launch_spec_preserves_api_format() -> None:
    plugin = WhisperPlugin()

    launch_spec = plugin.build_launch_spec(
        _bundle().model_copy(update={"provider_api_format": "whisper_asr_webservice"})
    )

    assert launch_spec["metadata"]["api_format"] == "whisper_asr_webservice"


def test_whisper_native_invoke_posts_bounded_multipart_audio() -> None:
    audio_bytes = b"RIFF\x00\x00\x00\x00WAVEfmt "
    audio_ref = "data:audio/wav;base64," + base64.b64encode(audio_bytes).decode("ascii")
    plugin = StubWhisperPlugin(
        transcribe_payload={"text": "hello native", "language": "en"}
    )
    runtime = RuntimeHandle(
        runtime_id="rt-native",
        command=["whisper-server"],
        status="running",
        bundle_id="whisper-local",
        metadata={
            "endpoint": "http://127.0.0.1:9000",
            "model_id": "base",
            "api_format": "whisper_asr_webservice",
        },
    )

    result = plugin.invoke(
        TaskRequest(task_type="audio.transcribe", payload={"audio_ref": audio_ref}),
        runtime,
    )

    assert result["text"] == "hello native"
    assert len(plugin.multipart_calls) == 1
    url, body, content_type = plugin.multipart_calls[0]
    assert url == "http://127.0.0.1:9000/asr?task=transcribe&output=json"
    assert content_type.startswith("multipart/form-data; boundary=aidn-whisper-")
    assert b'name="audio_file"' in body
    assert b"\r\n" in body
    assert b"\\r\\n" not in body
    assert audio_bytes in body


def test_whisper_native_invoke_rejects_filesystem_audio_ref() -> None:
    plugin = StubWhisperPlugin()
    runtime = RuntimeHandle(
        runtime_id="rt-native",
        command=["whisper-server"],
        status="running",
        bundle_id="whisper-local",
        metadata={
            "endpoint": "http://127.0.0.1:9000",
            "model_id": "base",
            "api_format": "whisper_asr_webservice",
        },
    )

    with pytest.raises(ValueError, match="base64 data URI"):
        plugin.invoke(
            TaskRequest(
                task_type="audio.transcribe",
                payload={"audio_ref": "/srv/private/audio.wav"},
            ),
            runtime,
        )


def test_whisper_plugin_invoke_requires_audio_ref_payload() -> None:
    plugin = StubWhisperPlugin()
    runtime = RuntimeHandle(
        runtime_id="rt-1",
        command=["whisper-server"],
        status="running",
        bundle_id="whisper-local",
        metadata={"endpoint": "http://127.0.0.1:9000", "model_id": "large-v3"},
    )
    task = TaskRequest(task_type="audio.transcribe", payload={})

    with pytest.raises(ValueError, match="audio_ref"):
        plugin.invoke(task, runtime)
