import base64
import io
import wave

import pytest

from aidn_hypervisor.domain.models import TaskRequest
from aidn_hypervisor.plugins.nemo_speech import NemoSpeechPlugin
from aidn_hypervisor.process_manager import RuntimeHandle


def _wav_data_uri(*, frames: int = 16_000) -> tuple[str, bytes]:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16_000)
        audio.writeframes(b"\x00\x00" * frames)
    payload = buffer.getvalue()
    return "data:audio/wav;base64," + base64.b64encode(payload).decode("ascii"), payload


class StubNemoSpeechPlugin(NemoSpeechPlugin):
    def __init__(self, *, models=None, response=None, health=None):
        self.models = models or [{"id": "parakeet-tdt-0.6b-v3.q8_0.gguf"}]
        self.response = response or {"text": "hello from parakeet", "duration_ms": 999}
        self.health = health or {"ready": True}
        self.json_calls = []
        self.multipart_calls = []

    def _request_json(self, method: str, url: str, payload=None) -> dict:
        self.json_calls.append((method, url, payload))
        if url.endswith("/ready"):
            return self.health
        if url.endswith("/v1/models"):
            return {"data": self.models}
        raise AssertionError(f"unexpected JSON request: {method} {url}")

    def _request_multipart(self, method: str, url: str, body: bytes, *, content_type: str) -> dict:
        self.multipart_calls.append((method, url, body, content_type))
        return self.response


def _runtime() -> RuntimeHandle:
    return RuntimeHandle(
        runtime_id="rt-nemo",
        command=["nemo-speech"],
        status="running",
        bundle_id="bundle-nemo",
        metadata={
            "endpoint": "http://127.0.0.1:8090",
            "model_id": "parakeet-tdt-0.6b-v3.q8_0.gguf",
        },
    )


def test_nemo_manifest_declares_pinned_parakeet_runtime() -> None:
    description = NemoSpeechPlugin().describe()

    assert description["plugin_id"] == "nemo-speech"
    assert description["plugin_version"] == "0.1.0"
    assert description["supported_aidn_capabilities"] == ["speech.stt"]
    assert description["workload_types"] == ["speech_to_text"]
    assert description["runtime_installers"][0]["pinned_version"] == "0.1.0"
    assert description["installation_recipes"][0]["model_configuration"] == {
        "provider_model_reference": "parakeet-tdt-0.6b-v3.q8_0.gguf"
    }
    assert description["usage_contract"]["supported_billing_units"] == [
        "audio_input_milliseconds"
    ]


def test_nemo_install_plan_is_loopback_only_and_checks_ready() -> None:
    plan = NemoSpeechPlugin().build_installation_plan(
        {
            "display_name": "Parakeet",
            "endpoint": "http://127.0.0.1:8090",
            "runtime_version": "0.1.0",
            "backend": "cuda",
            "model_id": "parakeet-tdt-0.6b-v3.q8_0.gguf",
        }
    )

    assert plan["containers"] == []
    assert plan["processes"] == []
    assert plan["health_checks"] == [
        {"type": "http", "url": "http://127.0.0.1:8090/ready", "timeout_seconds": 5}
    ]
    assert plan["resource_limits"] == {"accelerator": "cuda"}


def test_nemo_discovery_and_binding_are_speech_to_text_attached_service() -> None:
    plugin = StubNemoSpeechPlugin()
    instance = {
        "provider_instance_id": "pi-nemo",
        "configuration": {
            "endpoint": "http://127.0.0.1:8090",
            "backend": "cuda",
            "model_id": "parakeet-tdt-0.6b-v3.q8_0.gguf",
        },
    }

    deployment = plugin.discover_models(instance)[0]
    binding = plugin.create_runtime_binding(
        model_deployment=deployment,
        capability_id="speech.stt",
        capability_version="1.0.0",
        capability_definition_hash="sha256:capability",
    )

    assert deployment["capability_bindings"] == ["speech_to_text"]
    assert binding["adapter_id"] == "nemo-speech-http"
    assert binding["adapter_version"] == "nemo-speech-http.v1"
    assert binding["compatibility_bundle"]["launch_mode"] == "attached_service"
    assert binding["compatibility_bundle"]["device_affinity"] == "gpu"


def test_nemo_health_uses_ready_endpoint() -> None:
    plugin = StubNemoSpeechPlugin()

    assert plugin.health_check(_runtime()) is True
    assert plugin.json_calls == [("GET", "http://127.0.0.1:8090/ready", None)]


def test_nemo_invoke_posts_file_multipart_and_measures_wav_duration() -> None:
    audio_ref, audio_bytes = _wav_data_uri(frames=20_000)
    plugin = StubNemoSpeechPlugin()

    result = plugin.invoke(
        TaskRequest(task_type="audio.transcribe", payload={"audio_ref": audio_ref, "language": "ru"}),
        _runtime(),
    )

    assert result["text"] == "hello from parakeet"
    assert result["usage"]["audio_input_milliseconds"] == 1_250
    assert result["usage"]["measurement_kind"] == "exact"
    assert result["usage"]["input_bytes"] == len(audio_bytes)
    assert len(plugin.multipart_calls) == 1
    method, url, body, content_type = plugin.multipart_calls[0]
    assert method == "POST"
    assert url == "http://127.0.0.1:8090/v1/audio/transcriptions"
    assert content_type.startswith("multipart/form-data; boundary=aidn-nemo-speech-")
    assert b'name="file"' in body
    assert b'name="model"' in body
    assert b'name="response_format"' in body
    assert b'name="language"' in body
    assert audio_bytes in body


def test_nemo_rejects_non_wav_audio() -> None:
    plugin = StubNemoSpeechPlugin()
    audio_ref = "data:audio/mpeg;base64," + base64.b64encode(b"audio").decode("ascii")

    with pytest.raises(ValueError, match="WAV data URI"):
        plugin.invoke(
            TaskRequest(task_type="audio.transcribe", payload={"audio_ref": audio_ref}),
            _runtime(),
        )
