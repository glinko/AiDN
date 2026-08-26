"""OpenAI-compatible text-to-speech Provider with locally verified WAV Usage."""

from __future__ import annotations

import base64
import hashlib
import json
import struct
from decimal import ROUND_HALF_EVEN, Decimal
from urllib import error, parse, request

from aidn_hypervisor.plugins.base import ProviderPlugin
from aidn_hypervisor.plugins.whisper import WhisperPlugin


class OpenAITtsPlugin(ProviderPlugin):
    plugin_id = "openai-tts"
    plugin_version = "0.1.0"
    _max_audio_bytes = 25 * 1024 * 1024

    def describe(self) -> dict:
        return {
            "plugin_id": self.plugin_id,
            "plugin_version": self.plugin_version,
            "display_name": "OpenAI-compatible TTS",
            "publisher": "AiDN Built-in",
            "provider_type": "openai-tts",
            "provider_families": ["tts", "openai-compatible"],
            "plugin_capability_flags": ["CAN_ATTACH_EXISTING", "CAN_DISCOVER_MODELS"],
            "required_permissions": [
                {
                    "permission_id": "network.private",
                    "label": "TTS Provider network",
                    "risk_level": "low",
                    "reason": "Connect to the operator-selected TTS endpoint",
                }
            ],
            "supported_aidn_capabilities": ["speech.tts"],
            "workload_types": ["text_to_speech"],
            "usage_contract": self.usage_contract(),
        }

    def attach_provider_schema(self) -> dict:
        return {
            "schema_id": "openai-tts.attach.v1",
            "fields": [
                {"id": "endpoint", "type": "url", "label": "Provider endpoint", "required": True},
                {"id": "model_id", "type": "text", "label": "TTS model", "required": True, "default": "tts-1"},
                {"id": "voice", "type": "text", "label": "Default voice", "required": True, "default": "alloy"},
            ],
        }

    def validate_provider_configuration(self, configuration: dict) -> None:
        endpoint = str(configuration.get("endpoint") or "").strip()
        parsed = parse.urlsplit(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("TTS endpoint must be an absolute credential-free HTTP URL")
        if not str(configuration.get("model_id") or "").strip():
            raise ValueError("TTS model_id is required")
        if not str(configuration.get("voice") or "").strip():
            raise ValueError("TTS voice is required")

    def attach_existing_provider(self, configuration: dict) -> dict:
        self.validate_provider_configuration(configuration)
        return {
            "configuration": {
                **configuration,
                "endpoint": str(configuration["endpoint"]).rstrip("/"),
            },
            "connection_mode": "attached",
            "operational_state": "ready",
        }

    def discover_models(self, provider_instance: dict) -> list[dict]:
        configuration = dict(provider_instance.get("configuration") or {})
        model_id = str(configuration.get("model_id") or "").strip()
        if not model_id:
            return []
        return [
            {
                "provider_model_reference": model_id,
                "operator_display_name": model_id,
                "metadata_sources": {"operator_configuration": "openai-tts.attach.v1"},
                "capability_bindings": ["speech.tts"],
                "operational_state": "ready",
            }
        ]

    def validate_bundle(self, bundle_config) -> None:
        if (
            bundle_config.workload_type != "text_to_speech"
            or bundle_config.launch_mode != "attached_service"
            or not bundle_config.endpoint
        ):
            raise ValueError("OpenAI TTS requires an attached text_to_speech bundle")

    def estimate_resources(self, task, bundle_config, runtime_state) -> dict:
        profile = bundle_config.resource_profile
        return {
            "startup_transient": {},
            "runtime_resident": {
                "cpu": profile.steady_cpu,
                "ram_mb": profile.steady_ram_mb,
                "vram_mb": 0,
            },
            "request_active": {
                "cpu": profile.per_request_cpu,
                "ram_mb": profile.per_request_ram_mb,
                "vram_mb": 0,
            },
            "concurrency_limit": 2,
        }

    def build_launch_spec(self, bundle_config) -> dict:
        self.validate_bundle(bundle_config)
        raise ValueError("OpenAI TTS does not manage an upstream process")

    def health_check(self, runtime_handle) -> bool:
        try:
            with request.urlopen(
                request.Request(
                    f"{runtime_handle.metadata['endpoint'].rstrip('/')}/v1/models",
                    method="GET",
                ),
                timeout=5,
            ) as response:
                return 200 <= response.status < 300
        except Exception:
            return False

    def invoke(self, task, runtime_handle) -> dict:
        text = task.payload.get("text")
        if not isinstance(text, str) or not text:
            raise ValueError("TTS invocation requires non-empty text")
        voice = str(task.payload.get("voice") or runtime_handle.metadata.get("voice") or "alloy")
        media_type, audio_bytes = self._synthesize_wav(
            endpoint=str(runtime_handle.metadata["endpoint"]),
            model=str(runtime_handle.metadata["model_id"]),
            voice=voice,
            text=text,
        )
        return self._result(text=text, media_type=media_type, audio_bytes=audio_bytes)

    def stop(self, runtime_handle) -> None:
        return None

    def create_runtime_binding(
        self,
        *,
        model_deployment: dict,
        capability_id: str,
        capability_version: str,
        capability_definition_hash: str,
    ) -> dict:
        return {
            "model_deployment_id": model_deployment["model_deployment_id"],
            "provider_instance_id": model_deployment["provider_instance_id"],
            "capability_id": capability_id,
            "capability_version": capability_version,
            "capability_definition_hash": capability_definition_hash,
            "adapter_id": "openai-tts",
            "adapter_version": "openai-tts.v1",
            "supported_features": ["streaming", "cancellation"],
            "supported_modalities": ["text", "audio"],
            "supported_accounting_modes": ["deterministic", "fixed_price", "hybrid"],
            "compatibility_bundle": {
                "plugin_id": self.plugin_id,
                "provider_type": "openai-tts",
                "workload_type": "text_to_speech",
                "model_id": model_deployment["provider_model_reference"],
                "launch_mode": "attached_service",
                "device_affinity": "external",
            },
            "status": "ready",
        }

    def usage_contract(self) -> dict:
        return {
            "supports_exact": True,
            "supports_estimated": False,
            "supported_billing_units": [
                "text_input_characters",
                "audio_output_milliseconds",
            ],
            "supported_accounting_modes": ["deterministic", "fixed_price", "hybrid"],
            "default_measurement_source": "hypervisor_tts_boundary.wav_header",
            "fallback_measurement_source": None,
            "fallback_policy": "reject_unmeasurable_audio",
            "missing_usage_behavior": "strict_accounting",
        }

    def _synthesize_wav(
        self,
        *,
        endpoint: str,
        model: str,
        voice: str,
        text: str,
    ) -> tuple[str, bytes]:
        body = json.dumps(
            {
                "model": model,
                "input": text,
                "voice": voice,
                "response_format": "wav",
            },
            separators=(",", ":"),
        ).encode("utf-8")
        upstream = request.Request(
            f"{endpoint.rstrip('/')}/v1/audio/speech",
            method="POST",
            data=body,
            headers={"Content-Type": "application/json", "Accept": "audio/wav"},
        )
        try:
            with request.urlopen(upstream, timeout=90) as response:
                media_type = response.headers.get_content_type()
                audio_bytes = response.read(self._max_audio_bytes + 1)
        except error.URLError as exc:
            raise RuntimeError(str(exc)) from exc
        if len(audio_bytes) > self._max_audio_bytes:
            raise RuntimeError("TTS response exceeds the maximum audio artifact size")
        if not audio_bytes:
            raise RuntimeError("TTS Provider returned an empty audio artifact")
        return media_type, audio_bytes

    def _stream_synthesize_wav(
        self,
        *,
        endpoint: str,
        model: str,
        voice: str,
        text: str,
        timeout_seconds: float = 90,
        chunk_size: int = 64 * 1024,
    ):
        """Yield bounded WAV bytes while retaining the upstream response context."""
        body = json.dumps(
            {
                "model": model,
                "input": text,
                "voice": voice,
                "response_format": "wav",
            },
            separators=(",", ":"),
        ).encode("utf-8")
        upstream = request.Request(
            f"{endpoint.rstrip('/')}/v1/audio/speech",
            method="POST",
            data=body,
            headers={"Content-Type": "application/json", "Accept": "audio/wav"},
        )
        try:
            with request.urlopen(upstream, timeout=timeout_seconds) as response:
                media_type = response.headers.get_content_type()
                if media_type not in {"audio/wav", "audio/x-wav"}:
                    raise RuntimeError("TTS streaming output must be a WAV artifact")
                delivered = 0
                while True:
                    chunk = response.read(chunk_size)
                    if not chunk:
                        break
                    delivered += len(chunk)
                    if delivered > self._max_audio_bytes:
                        raise RuntimeError("TTS response exceeds the maximum audio artifact size")
                    yield chunk
                if delivered == 0:
                    raise RuntimeError("TTS Provider returned an empty audio artifact")
        except error.URLError as exc:
            raise RuntimeError(str(exc)) from exc

    @staticmethod
    def _delivered_wav_duration_milliseconds(audio_bytes: bytes) -> int | None:
        """Measure only complete PCM frames physically present in a partial WAV.

        ``wave.getnframes()`` trusts the declared data size in the header.  That
        would overcharge a cancelled stream, so this parser clamps the data
        chunk to the bytes that crossed the Hypervisor delivery boundary.
        """
        if len(audio_bytes) < 12 or audio_bytes[:4] != b"RIFF" or audio_bytes[8:12] != b"WAVE":
            return None
        offset = 12
        frame_rate: int | None = None
        block_align: int | None = None
        while offset + 8 <= len(audio_bytes):
            chunk_id = audio_bytes[offset : offset + 4]
            declared_size = struct.unpack_from("<I", audio_bytes, offset + 4)[0]
            payload_offset = offset + 8
            if chunk_id == b"fmt " and declared_size >= 16:
                if payload_offset + 16 > len(audio_bytes):
                    return None
                _format, _channels, frame_rate, _byte_rate, block_align = struct.unpack_from(
                    "<HHIIH", audio_bytes, payload_offset
                )
                if frame_rate <= 0 or block_align <= 0:
                    return None
            elif chunk_id == b"data":
                if frame_rate is None or block_align is None:
                    return None
                available_size = min(declared_size, max(0, len(audio_bytes) - payload_offset))
                complete_frames = available_size // block_align
                milliseconds = Decimal(complete_frames) * Decimal(1_000) / Decimal(frame_rate)
                return int(milliseconds.to_integral_value(rounding=ROUND_HALF_EVEN))
            next_offset = payload_offset + declared_size + (declared_size % 2)
            if next_offset <= offset or next_offset > len(audio_bytes):
                return None
            offset = next_offset
        return None

    @staticmethod
    def _result(*, text: str, media_type: str, audio_bytes: bytes) -> dict:
        duration_milliseconds = WhisperPlugin._wav_duration_milliseconds(
            audio_bytes,
            content_type=media_type,
        )
        if duration_milliseconds is None:
            raise RuntimeError("TTS output must be a valid WAV artifact for metered execution")
        artifact_hash = f"sha256:{hashlib.sha256(audio_bytes).hexdigest()}"
        return {
            "ok": True,
            "audio_ref": (f"data:{media_type};base64," + base64.b64encode(audio_bytes).decode("ascii")),
            "usage": {
                "fixed_request_count": 1,
                "text_input_characters": len(text),
                "audio_output_milliseconds": duration_milliseconds,
                "output_media_type": media_type,
                "output_bytes": len(audio_bytes),
                "output_artifact_sha256": artifact_hash,
                "measurement_kind": "exact",
                "measurement_source": "hypervisor_tts_boundary.wav_header",
            },
        }
