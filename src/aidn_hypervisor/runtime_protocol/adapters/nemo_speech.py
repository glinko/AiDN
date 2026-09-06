"""RFC-0054 adapter for the NVIDIA NeMo-Speech.cpp HTTP ASR service."""

from aidn_hypervisor.plugins.nemo_speech import NemoSpeechPlugin
from aidn_hypervisor.runtime_protocol.adapters.llamacpp import LlamaCppOpenAIAdapter
from aidn_hypervisor.runtime_protocol.models import RuntimeUsageDimension


class NemoSpeechHttpAdapter(LlamaCppOpenAIAdapter):
    """Translate a WAV data URI into NeMo's multipart transcription request."""

    adapter_label = "nemo-speech"

    def __init__(
        self,
        *,
        endpoint: str,
        model: str,
        runtime_signature: str,
        timeout_seconds: float = 90,
    ) -> None:
        super().__init__(
            endpoint=endpoint,
            model=model,
            runtime_signature=runtime_signature,
            timeout_seconds=timeout_seconds,
        )
        self._plugin = NemoSpeechPlugin()

    def _completion(self, execution_request) -> dict:
        payload = execution_request.request_payload or {}
        audio_ref = payload.get("audio_ref")
        if not isinstance(audio_ref, str) or not audio_ref:
            raise ValueError("NeMo-Speech adapter requires a non-empty audio_ref")
        decoded = self._plugin._decode_inline_audio(audio_ref)
        if decoded[0] not in {"audio/wav", "audio/x-wav"}:
            raise ValueError("NeMo-Speech adapter requires a WAV data URI")
        usage = self._plugin._inspect_inline_audio(decoded)
        response = self._plugin._invoke_nemo_asr(
            endpoint=self.endpoint,
            model=self.model,
            decoded_audio=decoded,
            language=payload.get("language"),
        )
        text = str(response.get("text", ""))
        usage["output_bytes"] = len(text.encode("utf-8"))
        return {
            "model": self.model,
            "choices": [{"text": text, "finish_reason": "stop"}],
            "usage": usage,
        }

    def _usage_dimensions(self, usage: dict) -> list[RuntimeUsageDimension]:
        dimensions = [
            RuntimeUsageDimension(
                dimension_id=dimension_id,
                unit="token",
                availability="UNAVAILABLE",
                billing_eligible=False,
                limitations=["NEMO_SPEECH_TOKEN_USAGE_UNAVAILABLE"],
            )
            for dimension_id in ("input_tokens", "output_tokens")
        ]
        duration = usage.get("audio_input_milliseconds")
        if isinstance(duration, int) and not isinstance(duration, bool) and duration >= 0:
            dimensions.append(
                RuntimeUsageDimension(
                    dimension_id="audio_input_milliseconds",
                    unit="millisecond",
                    availability="AVAILABLE",
                    authority="DETERMINISTIC_LOCAL",
                    value=duration,
                    billing_eligible=True,
                    source_reference={
                        "source_type": "HYPERVISOR_OBSERVATION",
                        "source_id": "nemo-speech-ingress-wav",
                        "source_hash": usage.get("input_artifact_sha256"),
                        "observation_boundary": "hypervisor-audio-ingress",
                    },
                )
            )
        else:
            dimensions.append(
                RuntimeUsageDimension(
                    dimension_id="audio_input_milliseconds",
                    unit="millisecond",
                    availability="UNAVAILABLE",
                    billing_eligible=False,
                    limitations=["NEMO_SPEECH_WAV_DURATION_UNAVAILABLE"],
                )
            )
        output_bytes = usage.get("output_bytes")
        if isinstance(output_bytes, int) and not isinstance(output_bytes, bool) and output_bytes >= 0:
            dimensions.append(
                RuntimeUsageDimension(
                    dimension_id="output_bytes",
                    unit="byte",
                    availability="AVAILABLE",
                    authority="OBSERVABLE_LOCAL",
                    value=output_bytes,
                    billing_eligible=False,
                    source_reference={
                        "source_type": "RUNTIME_COUNTER",
                        "source_id": "nemo-speech-transcript-output",
                        "observation_boundary": "adapter-result-payload",
                    },
                )
            )
        return dimensions



