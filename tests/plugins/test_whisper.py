import pytest

from aidn_hypervisor.domain.models import BundleConfig, ResourceProfile, TaskRequest
from aidn_hypervisor.process_manager import RuntimeHandle
from aidn_hypervisor.plugins.whisper import WhisperPlugin


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

    def _request_json(self, method: str, url: str, payload: dict | None = None) -> dict:
        self.calls.append((method, url, payload))
        if self.raise_error is not None:
            raise self.raise_error
        if url.endswith("/health"):
            return self.health_payload or {"status": "ok"}
        if url.endswith("/v1/audio/transcriptions"):
            return self.transcribe_payload or {"text": ""}
        raise AssertionError(f"unexpected url: {url}")


def test_whisper_plugin_describes_speech_to_text_capability() -> None:
    plugin = WhisperPlugin()

    assert plugin.describe() == {
        "plugin_id": "whisper",
        "workload_types": ["speech_to_text"],
        "usage_contract": {
            "supports_exact": False,
            "supports_estimated": True,
            "default_measurement_source": "provider_request",
            "fallback_measurement_source": "provider_request",
            "fallback_policy": "fixed_request_estimate",
            "missing_usage_behavior": "skip",
        },
    }


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
            "input_tokens": 0,
            "output_tokens": 0,
            "fixed_request_count": 1,
            "measurement_kind": "estimated",
            "measurement_source": "provider_request",
        },
        "raw": {"text": "hello world", "language": "en"},
    }


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
