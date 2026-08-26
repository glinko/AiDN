"""RFC-0054 adapter for deterministic OpenAI-compatible TTS execution."""

import base64
import hashlib

from aidn_hypervisor.plugins.openai_tts import OpenAITtsPlugin
from aidn_hypervisor.runtime_protocol.adapters.llamacpp import LlamaCppOpenAIAdapter
from aidn_hypervisor.runtime_protocol.models import (
    RuntimeExecuteRequest,
    RuntimeResult,
    RuntimeStreamChunk,
    RuntimeStreamClose,
    RuntimeStreamOpen,
    RuntimeUsageDimension,
    RuntimeUsageReport,
)


class OpenAITtsAdapter(LlamaCppOpenAIAdapter):
    adapter_label = "openai-tts"

    def __init__(
        self,
        *,
        endpoint: str,
        model: str,
        runtime_signature: str,
        voice: str = "alloy",
        timeout_seconds: float = 90,
    ) -> None:
        super().__init__(
            endpoint=endpoint,
            model=model,
            runtime_signature=runtime_signature,
            timeout_seconds=timeout_seconds,
        )
        self.voice = voice
        self._plugin = OpenAITtsPlugin()

    def _completion(self, execution_request) -> dict:
        payload = dict(execution_request.request_payload or {})
        text = payload.get("text")
        if not isinstance(text, str) or not text:
            raise ValueError("TTS adapter requires non-empty text")
        voice = str(payload.get("voice") or self.voice)
        media_type, audio_bytes = self._plugin._synthesize_wav(
            endpoint=self.endpoint,
            model=self.model,
            voice=voice,
            text=text,
        )
        result = self._plugin._result(
            text=text,
            media_type=media_type,
            audio_bytes=audio_bytes,
        )
        return {
            "model": self.model,
            "audio_ref": result["audio_ref"],
            "choices": [{"text": "", "finish_reason": "stop"}],
            "usage": result["usage"],
        }

    def _result_payload(self, response: dict, choice: dict) -> dict:
        return {
            "audio_ref": response["audio_ref"],
            "model": str(response.get("model", self.model)),
            "finish_reason": choice.get("finish_reason"),
        }

    def _usage_dimensions(self, usage: dict) -> list[RuntimeUsageDimension]:
        artifact_hash = usage.get("output_artifact_sha256")
        source_reference = {
            "source_type": "HYPERVISOR_OBSERVATION",
            "source_id": "openai-tts-wav-output",
            "source_hash": artifact_hash,
            "observation_boundary": "hypervisor-tts-response",
        }
        return [
            RuntimeUsageDimension(
                dimension_id="text_input_characters",
                unit="character",
                availability="AVAILABLE",
                authority="DETERMINISTIC_LOCAL",
                value=int(usage["text_input_characters"]),
                billing_eligible=True,
                source_reference={
                    "source_type": "HYPERVISOR_OBSERVATION",
                    "source_id": "openai-tts-request-text",
                    "observation_boundary": "hypervisor-tts-request",
                },
            ),
            RuntimeUsageDimension(
                dimension_id="audio_output_milliseconds",
                unit="millisecond",
                availability="AVAILABLE",
                authority="DETERMINISTIC_LOCAL",
                value=int(usage["audio_output_milliseconds"]),
                billing_eligible=True,
                source_reference=source_reference,
            ),
        ]

    def execute_streaming(
        self,
        protocol,
        runtime_connection_id: str,
        request: RuntimeExecuteRequest,
    ) -> RuntimeResult:
        """Stream hash-bound WAV chunks and meter only delivered audio frames."""
        existing = protocol.store.results.get(request.request_id)
        if existing is not None:
            return existing
        payload = dict(request.request_payload or {})
        text = payload.get("text")
        if not isinstance(text, str) or not text:
            raise ValueError("TTS adapter requires non-empty text")
        voice = str(payload.get("voice") or self.voice)
        self._admit(
            protocol,
            runtime_connection_id,
            request,
            accepted_features=["streaming", "cancellation"],
        )
        stream_id = f"{self.adapter_label}-stream-{request.request_id}"
        protocol.record_runtime_stream_open(
            runtime_connection_id,
            RuntimeStreamOpen(
                runtime_id=request.runtime_id,
                runtime_generation=request.runtime_generation,
                runtime_configuration_hash=request.runtime_configuration_hash,
                route_generation=request.route_generation,
                session_id=request.session_id,
                request_id=request.request_id,
                stream_id=stream_id,
                stream_type="result",
                modality="audio",
                content_type="audio/wav",
                ordering_model="ARTIFACT_CHUNKS",
                result_root_policy="FULL_CONTENT_HASH",
                opened_at=self._now(),
                runtime_signature=self.runtime_signature,
            ),
        )
        started_at = self._now()
        chunks: list[RuntimeStreamChunk] = []
        delivered_audio = bytearray()
        terminal_state = "COMPLETED"
        limitations: list[str] = []
        stream = self._plugin._stream_synthesize_wav(
            endpoint=self.endpoint,
            model=self.model,
            voice=voice,
            text=text,
            timeout_seconds=self.timeout_seconds,
        )
        try:
            for audio_chunk in stream:
                record = protocol.store.requests.get(request.request_id)
                if record is not None and record.request_state == "CANCEL_REQUESTED":
                    terminal_state = "CANCELLED"
                    limitations = ["PARTIAL_AUDIO_DELIVERED"]
                    break
                if not audio_chunk:
                    continue
                delivered_audio.extend(audio_chunk)
                encoded_content = base64.b64encode(audio_chunk).decode("ascii")
                encoded_bytes = encoded_content.encode("utf-8")
                chunk = RuntimeStreamChunk(
                    runtime_id=request.runtime_id,
                    runtime_generation=request.runtime_generation,
                    runtime_configuration_hash=request.runtime_configuration_hash,
                    route_generation=request.route_generation,
                    session_id=request.session_id,
                    request_id=request.request_id,
                    stream_id=stream_id,
                    chunk_sequence=len(chunks) + 1,
                    chunk_hash=f"sha256:{hashlib.sha256(encoded_bytes).hexdigest()}",
                    chunk_length=len(encoded_bytes),
                    content=encoded_content,
                    cumulative_output_units=len(delivered_audio),
                    emitted_at=self._now(),
                    runtime_signature=self.runtime_signature,
                )
                protocol.record_runtime_stream_chunk(runtime_connection_id, chunk)
                chunks.append(chunk)
        except Exception as exc:
            terminal_state = "FAILED"
            limitations = [f"UPSTREAM_STREAM_ERROR:{type(exc).__name__}"]
        finally:
            close_stream = getattr(stream, "close", None)
            if callable(close_stream):
                close_stream()

        duration_milliseconds = self._plugin._delivered_wav_duration_milliseconds(bytes(delivered_audio))
        if terminal_state == "COMPLETED" and duration_milliseconds is None:
            terminal_state = "FAILED"
            limitations = ["INVALID_OR_UNMEASURABLE_WAV_OUTPUT"]
        close = RuntimeStreamClose(
            runtime_id=request.runtime_id,
            runtime_generation=request.runtime_generation,
            runtime_configuration_hash=request.runtime_configuration_hash,
            route_generation=request.route_generation,
            session_id=request.session_id,
            request_id=request.request_id,
            stream_id=stream_id,
            terminal_state=terminal_state,
            final_sequence=len(chunks),
            final_content_root=self._stream_root(stream_id, chunks),
            delivered_length=sum(item.chunk_length for item in chunks),
            close_reason=terminal_state.lower(),
            closed_at=self._now(),
            runtime_signature=self.runtime_signature,
        )
        protocol.record_runtime_stream_close(runtime_connection_id, close)
        delivered_hash = f"sha256:{hashlib.sha256(delivered_audio).hexdigest()}"
        dimensions = [
            RuntimeUsageDimension(
                dimension_id="text_input_characters",
                unit="character",
                availability="AVAILABLE",
                authority="DETERMINISTIC_LOCAL",
                value=len(text),
                billing_eligible=True,
                source_reference={
                    "source_type": "HYPERVISOR_OBSERVATION",
                    "source_id": "openai-tts-request-text",
                    "observation_boundary": "hypervisor-tts-request",
                },
            )
        ]
        if duration_milliseconds is not None:
            dimensions.append(
                RuntimeUsageDimension(
                    dimension_id="audio_output_milliseconds",
                    unit="millisecond",
                    availability="AVAILABLE",
                    authority="DETERMINISTIC_LOCAL",
                    value=duration_milliseconds,
                    billing_eligible=True,
                    source_reference={
                        "source_type": "HYPERVISOR_OBSERVATION",
                        "source_id": "openai-tts-delivered-wav-output",
                        "source_hash": delivered_hash,
                        "observation_boundary": "adapter-delivered-stream",
                    },
                )
            )
        report = RuntimeUsageReport(
            usage_report_id=f"{self.adapter_label}-usage-{request.request_id}",
            runtime_id=request.runtime_id,
            runtime_generation=request.runtime_generation,
            runtime_configuration_hash=request.runtime_configuration_hash,
            endpoint_id=request.endpoint_id,
            endpoint_configuration_hash=request.endpoint_configuration_hash,
            session_id=request.session_id,
            request_id=request.request_id,
            effective_terms_hash=request.effective_terms_hash,
            accounting_contract_hash=request.accounting_contract_hash,
            report_type="FINAL",
            usage_sequence=1,
            dimensions=dimensions,
            provider_attempt_count=1,
            request_state=terminal_state,
            terminal=True,
            observed_from=started_at,
            observed_to=self._now(),
            limitations=limitations,
            created_at=self._now(),
            runtime_signature=self.runtime_signature,
        )
        protocol.record_usage_report(runtime_connection_id, report)
        result_payload = None
        if terminal_state in {"COMPLETED", "CANCELLED"}:
            result_payload = {
                "stream_id": stream_id,
                "model": self.model,
                "delivered_audio_bytes": len(delivered_audio),
                "delivered_audio_sha256": delivered_hash,
            }
        return protocol.record_runtime_result(
            runtime_connection_id,
            RuntimeResult(
                runtime_id=request.runtime_id,
                runtime_generation=request.runtime_generation,
                runtime_configuration_hash=request.runtime_configuration_hash,
                route_generation=request.route_generation,
                endpoint_id=request.endpoint_id,
                endpoint_configuration_hash=request.endpoint_configuration_hash,
                session_id=request.session_id,
                request_id=request.request_id,
                terminal_state=terminal_state,
                result_payload=result_payload,
                stream_roots=[close.final_content_root],
                final_usage_report_id=report.usage_report_id,
                provider_attempt_count=1,
                completed_at=self._now(),
                runtime_signature=self.runtime_signature,
            ),
        )
