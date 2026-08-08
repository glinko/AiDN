"""RFC-0054 adapter for an operator-managed Whisper HTTP service."""

import json
from urllib import error as urllib_error
from urllib import request as urllib_request

from aidn_hypervisor.plugins.whisper import WhisperPlugin
from aidn_hypervisor.runtime_protocol.adapters.llamacpp import LlamaCppOpenAIAdapter
from aidn_hypervisor.runtime_protocol.models import RuntimeUsageDimension


class WhisperHttpAdapter(LlamaCppOpenAIAdapter):
    """Normalize native Whisper responses into Runtime Result and Usage evidence.

    The adapter deliberately accepts only the same payload shape as the plugin:
    ``{"audio_ref": "data:audio/...;base64,..."}`` for native Whisper. The
    legacy AiDN JSON mode remains available only when explicitly configured on
    the Provider Instance.
    """

    adapter_label = "whisper"
    _supported_api_formats = {"aidn_json", "whisper_asr_webservice"}

    def __init__(
        self,
        *,
        endpoint: str,
        model: str,
        runtime_signature: str,
        api_format: str = "whisper_asr_webservice",
        timeout_seconds: float = 90,
    ) -> None:
        super().__init__(
            endpoint=endpoint,
            model=model,
            runtime_signature=runtime_signature,
            timeout_seconds=timeout_seconds,
        )
        if api_format not in self._supported_api_formats:
            raise ValueError(f"unsupported Whisper API format: {api_format}")
        self.api_format = api_format
        self._plugin = WhisperPlugin()

    def _completion(self, execution_request) -> dict:
        audio_ref = (execution_request.request_payload or {}).get("audio_ref")
        if not isinstance(audio_ref, str) or not audio_ref:
            raise ValueError("Whisper adapter requires a non-empty audio_ref")

        if self.api_format == "whisper_asr_webservice":
            response = self._plugin._invoke_native_asr(
                endpoint=self.endpoint,
                audio_ref=audio_ref,
            )
        else:
            response = self._request_json(
                "POST",
                f"{self.endpoint}/v1/audio/transcriptions",
                {"model": self.model, "audio_ref": audio_ref},
            )

        text = str(response.get("text", ""))
        usage: dict = {"output_bytes": len(text.encode("utf-8"))}
        try:
            usage["input_bytes"] = len(
                self._plugin._decode_inline_audio(audio_ref)[2]
            )
        except ValueError:
            # The legacy adapter may receive an opaque reference. Do not infer
            # its size or turn an unavailable measurement into zero.
            pass
        duration_seconds = self._plugin._audio_duration_seconds(response)
        if duration_seconds is not None:
            usage["audio_input_seconds"] = duration_seconds
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
                limitations=["WHISPER_TOKEN_USAGE_UNAVAILABLE"],
            )
            for dimension_id in ("input_tokens", "output_tokens")
        ]
        duration_seconds = usage.get("audio_input_seconds")
        if isinstance(duration_seconds, (int, float)) and not isinstance(
            duration_seconds, bool
        ) and duration_seconds >= 0:
            dimensions.append(
                RuntimeUsageDimension(
                    dimension_id="audio_input_seconds",
                    unit="second",
                    availability="AVAILABLE",
                    authority="ESTIMATED",
                    value=float(duration_seconds),
                    billing_eligible=False,
                    source_reference={
                        "source_type": "PROVIDER_USAGE_RESPONSE",
                        "source_id": "whisper-response-duration",
                    },
                    limitations=["WHISPER_DURATION_REPORTED_BY_PROVIDER"],
                )
            )
        else:
            dimensions.append(
                RuntimeUsageDimension(
                    dimension_id="audio_input_seconds",
                    unit="second",
                    availability="UNAVAILABLE",
                    billing_eligible=False,
                    limitations=["WHISPER_PROVIDER_MAY_OMIT_DURATION"],
                )
            )
        output_bytes = usage.get("output_bytes")
        if isinstance(output_bytes, int) and output_bytes >= 0:
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
                        "source_id": "whisper-transcript-output",
                        "observation_boundary": "adapter-result-payload",
                    },
                )
            )
        return dimensions

    def _request_json(self, method: str, url: str, payload: dict | None = None) -> dict:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        request = urllib_request.Request(
            url,
            method=method,
            data=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib_request.urlopen(request, timeout=self.timeout_seconds) as response:
                decoded = json.loads(response.read().decode("utf-8"))
        except urllib_error.URLError as exc:
            raise RuntimeError(str(exc)) from exc
        if not isinstance(decoded, dict):
            raise RuntimeError("Whisper provider returned an invalid JSON object")
        return decoded
