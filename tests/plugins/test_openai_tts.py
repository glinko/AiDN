import base64
import hashlib
import io
import wave

import pytest

from aidn_hypervisor.domain.models import BundleConfig, ResourceProfile, TaskRequest
from aidn_hypervisor.plugins.openai_tts import OpenAITtsPlugin
from aidn_hypervisor.process_manager import RuntimeHandle


def _wav(*, milliseconds: int = 1_250) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16_000)
        audio.writeframes(b"\x00\x00" * (16_000 * milliseconds // 1_000))
    return output.getvalue()


def test_openai_tts_declares_exact_character_and_audio_billing() -> None:
    contract = OpenAITtsPlugin().usage_contract()

    assert contract["supports_exact"] is True
    assert contract["supported_billing_units"] == [
        "text_input_characters",
        "audio_output_milliseconds",
    ]
    assert contract["missing_usage_behavior"] == "strict_accounting"


def test_openai_tts_invoke_returns_hash_bound_wav_usage(monkeypatch) -> None:
    plugin = OpenAITtsPlugin()
    audio_bytes = _wav(milliseconds=1_250)
    monkeypatch.setattr(
        plugin,
        "_synthesize_wav",
        lambda **_: ("audio/wav", audio_bytes),
    )
    runtime = RuntimeHandle(
        runtime_id="tts-1",
        bundle_id="tts-local",
        command=[],
        status="running",
        metadata={
            "endpoint": "http://127.0.0.1:8880",
            "model_id": "tts-1",
            "voice": "alloy",
        },
    )

    result = plugin.invoke(
        TaskRequest(
            task_type="audio.synthesize",
            payload={"text": "Hello!", "voice": "alloy"},
        ),
        runtime,
    )

    assert base64.b64decode(result["audio_ref"].split(",", 1)[1]) == audio_bytes
    assert result["usage"] == {
        "fixed_request_count": 1,
        "text_input_characters": 6,
        "audio_output_milliseconds": 1_250,
        "output_media_type": "audio/wav",
        "output_bytes": len(audio_bytes),
        "output_artifact_sha256": f"sha256:{hashlib.sha256(audio_bytes).hexdigest()}",
        "measurement_kind": "exact",
        "measurement_source": "hypervisor_tts_boundary.wav_header",
    }


def test_openai_tts_rejects_unmeasurable_output() -> None:
    with pytest.raises(RuntimeError, match="valid WAV"):
        OpenAITtsPlugin._result(
            text="hello",
            media_type="audio/mpeg",
            audio_bytes=b"not-a-wav",
        )


def test_openai_tts_partial_wav_duration_uses_only_present_pcm_frames() -> None:
    audio_bytes = _wav(milliseconds=1_000)
    # A mono 16-bit 16 kHz WAV has a 44-byte header and 32 bytes per ms.
    partially_delivered = audio_bytes[: 44 + (32 * 375)]

    duration = OpenAITtsPlugin._delivered_wav_duration_milliseconds(partially_delivered)

    assert duration == 375


def test_openai_tts_bundle_requires_attached_tts_workload() -> None:
    plugin = OpenAITtsPlugin()
    bundle = BundleConfig(
        bundle_id="tts-local",
        plugin_id=plugin.plugin_id,
        provider_type="openai-tts",
        workload_type="text_to_speech",
        model_id="tts-1",
        launch_mode="attached_service",
        endpoint="http://127.0.0.1:8880",
        device_affinity="external",
        resource_profile=ResourceProfile(),
        warm_policy="auto",
    )

    plugin.validate_bundle(bundle)
