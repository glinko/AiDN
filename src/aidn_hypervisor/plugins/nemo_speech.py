"""NVIDIA NeMo-Speech.cpp Provider Plugin.

The NeMo-Speech server exposes a deliberately small OpenAI-compatible HTTP
surface.  AiDN keeps the provider contract separate from Whisper because the
wire format and readiness semantics are different: NeMo accepts a WAV upload
in the ``file`` multipart field and serves a single loaded ASR model.
"""

from __future__ import annotations

import hashlib
from urllib import parse

from aidn_hypervisor.plugins.whisper import WhisperPlugin


class NemoSpeechPlugin(WhisperPlugin):
    """Attach or install the reviewed NeMo-Speech.cpp ASR runtime."""

    plugin_id = "nemo-speech"
    plugin_version = "0.1.0"
    _runtime_version = "0.1.0"
    _default_endpoint = "http://127.0.0.1:8090"
    _default_model = "parakeet-tdt-0.6b-v3.q8_0.gguf"
    _default_model_path = (
        "/var/lib/aidn/nemo-speech/models/parakeet-tdt-0.6b-v3.q8_0.gguf"
    )
    _default_backend = "cuda"
    # ``speech_to_text`` is the scheduler workload name.  Endpoint and
    # Runtime Binding contracts use the canonical capability identifier.
    _capability_id = "speech.stt"

    def describe(self) -> dict:
        return {
            "plugin_id": self.plugin_id,
            "plugin_version": self.plugin_version,
            "display_name": "NVIDIA NeMo-Speech.cpp",
            "publisher": "AiDN Built-in",
            "package_digest": (
                "sha256:9e8c3f1e31f7fd2f31f1f9ca3d1e85b6bdfd3f2e"
                "4b9344dbce2d2cba6b1f96f"
            ),
            "provider_type": self.plugin_id,
            "provider_families": ["nemo-speech", "parakeet", "openai-compatible"],
            "plugin_capability_flags": [
                "CAN_ATTACH_EXISTING",
                "CAN_INSTALL_PROVIDER",
                "CAN_DISCOVER_MODELS",
            ],
            "required_permissions": [
                {
                    "permission_id": "host.service_manager",
                    "label": "Manage reviewed user service",
                    "risk_level": "high",
                    "reason": (
                        "Create and supervise the loopback-only NeMo-Speech.cpp "
                        "service for the operator-selected model"
                    ),
                },
                {
                    "permission_id": "network.egress",
                    "label": "Download reviewed runtime",
                    "risk_level": "medium",
                    "reason": (
                        "Download the pinned NeMo-Speech.cpp runtime archive and "
                        "the operator-selected Parakeet model"
                    ),
                },
                {
                    "permission_id": "network.private",
                    "label": "Private provider network",
                    "risk_level": "low",
                    "reason": "Connect to the local NeMo-Speech HTTP endpoint",
                },
            ],
            "trust_status": "AIDN_CURATED",
            "sandbox_policy": {
                "execution_mode": "RECORDED_ONLY",
                "filesystem_scope": "NONE",
                "network_scope": "NONE",
                "secret_scope": "DECLARED_HANDLES_ONLY",
                "notes": (
                    "The generic executor records approval only. Host mutation "
                    "requires the allowlisted Provider runtime installer executor."
                ),
            },
            "runtime_installers": [
                {
                    "installer_id": "aidn-provider-runtime-ubuntu.v1",
                    "provider": self.plugin_id,
                    "platform": "ubuntu",
                    "script": "tools/aidn-provider-runtime-ubuntu.sh",
                    "pinned_version": self._runtime_version,
                    "actions": ["install", "start", "status", "stop", "remove"],
                    "model_configuration_separate": True,
                }
            ],
            "source_repository": "https://github.com/NVIDIA/NeMo-Speech.cpp",
            "license": "Apache-2.0 (runtime); CC BY 4.0 (Parakeet model)",
            "supported_platforms": ["linux"],
            "supported_architectures": ["x86_64"],
            "supported_accelerators": ["cpu", "cuda"],
            "installation_recipes": [
                {
                    "recipe_id": "nemo-speech-parakeet-ubuntu-cuda",
                    "display_name": "Parakeet TDT 0.6B v3 on NVIDIA Ubuntu",
                    "description": (
                        "Install NeMo-Speech.cpp and attach the multilingual "
                        "Parakeet speech-to-text service"
                    ),
                    "provider_configuration": {
                        "display_name": "Local Parakeet",
                        "endpoint": self._default_endpoint,
                        "runtime_version": self._runtime_version,
                        "backend": self._default_backend,
                        "model_id": self._default_model,
                        "model_path": self._default_model_path,
                    },
                    "model_configuration": {
                        "provider_model_reference": self._default_model,
                    },
                    "endpoint_defaults": {"capability_id": self._capability_id},
                }
            ],
            "supported_aidn_capabilities": [self._capability_id],
            "workload_types": ["speech_to_text"],
            "usage_contract": self.usage_contract(),
        }

    def attach_provider_schema(self) -> dict:
        return self.install_provider_schema().copy() | {
            "schema_id": "nemo-speech.attach.v1"
        }

    def install_provider_schema(self) -> dict:
        return {
            "schema_id": "nemo-speech.install.v1",
            "fields": [
                {
                    "id": "display_name",
                    "type": "text",
                    "label": "Provider name",
                    "required": True,
                    "default": "Local Parakeet",
                },
                {
                    "id": "endpoint",
                    "type": "url",
                    "label": "NeMo-Speech HTTP endpoint",
                    "required": True,
                    "default": self._default_endpoint,
                },
                {
                    "id": "runtime_version",
                    "type": "text",
                    "label": "Reviewed runtime version",
                    "required": True,
                    "default": self._runtime_version,
                },
                {
                    "id": "backend",
                    "type": "select",
                    "label": "Acceleration backend",
                    "required": True,
                    "default": self._default_backend,
                    "options": [
                        {"value": "cuda", "label": "NVIDIA CUDA"},
                        {"value": "cpu", "label": "CPU"},
                    ],
                },
                {
                    "id": "model_id",
                    "type": "text",
                    "label": "Loaded model ID",
                    "required": False,
                    "default": self._default_model,
                },
                {
                    "id": "model_path",
                    "type": "text",
                    "label": "GGUF model path",
                    "required": False,
                    "default": self._default_model_path,
                },
            ],
        }

    def validate_provider_configuration(self, configuration: dict) -> None:
        display_name = str(configuration.get("display_name", "")).strip()
        endpoint = str(configuration.get("endpoint", "")).strip()
        if not display_name:
            raise ValueError("display_name is required")
        parsed_endpoint = parse.urlsplit(endpoint)
        if (
            parsed_endpoint.scheme not in {"http", "https"}
            or not parsed_endpoint.netloc
            or parsed_endpoint.username
            or parsed_endpoint.password
        ):
            raise ValueError("endpoint must be an absolute HTTP URL")
        runtime_version = str(
            configuration.get("runtime_version") or self._runtime_version
        ).strip()
        if runtime_version != self._runtime_version:
            raise ValueError(
                f"runtime_version must match the reviewed NeMo-Speech pin {self._runtime_version}"
            )
        backend = str(configuration.get("backend") or self._default_backend).strip().lower()
        if backend not in {"cpu", "cuda"}:
            raise ValueError("backend must be cpu or cuda")
        model_id = str(configuration.get("model_id") or self._default_model).strip()
        if not model_id or len(model_id) > 256:
            raise ValueError("model_id must be bounded text")
        model_path = configuration.get("model_path")
        if model_path is not None:
            model_path = str(model_path).strip()
            if not model_path.startswith("/") or "\x00" in model_path:
                raise ValueError("model_path must be an absolute Unix path")

    def build_installation_plan(self, configuration: dict) -> dict:
        normalized = {
            "display_name": configuration.get("display_name") or "Local Parakeet",
            "endpoint": configuration.get("endpoint") or self._default_endpoint,
            "runtime_version": configuration.get("runtime_version") or self._runtime_version,
            "backend": configuration.get("backend") or self._default_backend,
            "model_id": configuration.get("model_id") or self._default_model,
            "model_path": configuration.get("model_path") or self._default_model_path,
        }
        self.validate_provider_configuration(normalized)
        endpoint = str(normalized["endpoint"]).rstrip("/")
        return {
            "plan_id": "plan-nemo-speech-ubuntu-v1",
            "plugin_id": self.plugin_id,
            "plan_version": "1.0.0",
            "summary": "Install the pinned NeMo-Speech.cpp HTTP ASR runtime",
            "containers": [],
            "processes": [],
            "model_downloads": [],
            "volumes": [],
            "networks": [{"name": "nemo-speech-loopback", "scope": "local"}],
            "environment": {},
            "resource_limits": {"accelerator": normalized["backend"]},
            "health_checks": [
                {"type": "http", "url": f"{endpoint}/ready", "timeout_seconds": 5}
            ],
            "required_permissions": self.plugin_manifest()["required_permissions"],
            "secret_references": [],
            "unsupported_actions": [],
        }

    def attach_existing_provider(self, configuration: dict) -> dict:
        normalized = dict(configuration)
        normalized.setdefault("display_name", "Local Parakeet")
        normalized.setdefault("runtime_version", self._runtime_version)
        normalized.setdefault("backend", self._default_backend)
        normalized.setdefault("model_id", self._default_model)
        normalized.setdefault("model_path", self._default_model_path)
        self.validate_provider_configuration(normalized)
        normalized["endpoint"] = str(normalized["endpoint"]).rstrip("/")
        return {
            "configuration": normalized,
            "connection_mode": "attached",
            "operational_state": "ready",
        }

    def discover_models(self, provider_instance: dict) -> list[dict]:
        configuration = provider_instance.get("configuration") or {}
        endpoint = str(configuration.get("endpoint") or self._default_endpoint).rstrip("/")
        payload = self._request_json("GET", f"{endpoint}/v1/models")
        models = payload.get("data")
        if not isinstance(models, list):
            raise ValueError("NeMo-Speech model discovery returned invalid data")
        provider_instance_id = provider_instance["provider_instance_id"]
        discovered: list[dict] = []
        for item in models:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                continue
            model_id = item["id"].strip()
            if not model_id:
                continue
            suffix = hashlib.sha256(model_id.encode("utf-8")).hexdigest()[:12]
            discovered.append(
                {
                    "model_deployment_id": f"md-{provider_instance_id}-{suffix}",
                    "provider_instance_id": provider_instance_id,
                    "provider_model_reference": model_id,
                    "operator_display_name": model_id,
                    "declared_model_name": model_id,
                    "metadata_sources": {"provider": "nemo-speech-v1-models"},
                    "capability_bindings": ["speech_to_text"],
                    "operational_state": "ready",
                }
            )
        if not discovered:
            raise ValueError("NeMo-Speech reported no loaded ASR model")
        return discovered

    def create_runtime_binding(
        self,
        *,
        model_deployment: dict,
        capability_id: str,
        capability_version: str,
        capability_definition_hash: str,
    ) -> dict:
        if capability_id != self._capability_id:
            raise ValueError(
                f"NeMo-Speech plugin only supports {self._capability_id}"
            )
        configuration = model_deployment.get("provider_configuration") or {}
        backend = str(configuration.get("backend") or self._default_backend).strip().lower()
        if backend not in {"cpu", "cuda"}:
            raise ValueError("backend must be cpu or cuda")
        return {
            "model_deployment_id": model_deployment["model_deployment_id"],
            "provider_instance_id": model_deployment["provider_instance_id"],
            "capability_id": capability_id,
            "capability_version": capability_version,
            "capability_definition_hash": capability_definition_hash,
            "adapter_id": "nemo-speech-http",
            "adapter_version": "nemo-speech-http.v1",
            "supported_features": ["cancellation"],
            "supported_modalities": ["audio", "text"],
            "supported_accounting_modes": ["deterministic", "fixed_price", "observable"],
            "compatibility_bundle": {
                "plugin_id": self.plugin_id,
                "provider_type": self.plugin_id,
                "workload_type": "speech_to_text",
                "model_id": model_deployment["provider_model_reference"],
                "launch_mode": "attached_service",
                "device_affinity": "gpu" if backend == "cuda" else "cpu",
                "provider_api_format": "nemo-speech-v1",
            },
            "status": "ready",
        }

    def validate_bundle(self, bundle_config) -> None:
        if bundle_config.workload_type != "speech_to_text":
            raise ValueError("NeMo-Speech plugin only supports speech_to_text workloads")
        if bundle_config.launch_mode != "attached_service":
            raise ValueError("NeMo-Speech plugin requires attached_service launch_mode")
        if not bundle_config.endpoint:
            raise ValueError("NeMo-Speech bundle requires an endpoint")

    def build_launch_spec(self, bundle_config) -> dict:
        self.validate_bundle(bundle_config)
        raise ValueError("NeMo-Speech attached-service plugin does not manage local process launch")

    def health_check(self, runtime_handle) -> bool:
        try:
            payload = self._request_json("GET", f"{self._endpoint(runtime_handle)}/ready")
        except Exception:
            return False
        return payload.get("ready") is True or payload.get("status") == "ok"

    def health_check_diagnostic(self, runtime_handle) -> dict:
        endpoint = self._endpoint(runtime_handle)
        probe_url = f"{endpoint}/ready"
        try:
            payload = self._request_json("GET", probe_url)
        except Exception as exc:
            detail = str(exc).strip() or exc.__class__.__name__
            return {
                "healthy": False,
                "code": "provider_endpoint_unreachable",
                "message": f"NeMo-Speech readiness probe failed for {probe_url}: {detail}",
                "endpoint": endpoint,
                "probe_url": probe_url,
                "hint": "Start nemo-speech with the Parakeet model and keep it on loopback.",
            }
        healthy = payload.get("ready") is True or payload.get("status") == "ok"
        return {
            "healthy": healthy,
            "code": "provider_healthy" if healthy else "provider_not_ready",
            "message": None if healthy else f"NeMo-Speech is not ready at {probe_url}",
            "endpoint": endpoint,
            "probe_url": probe_url,
            "details": payload,
        }

    def invoke(self, task, runtime_handle) -> dict:
        audio_ref = task.payload.get("audio_ref")
        if not isinstance(audio_ref, str) or not audio_ref:
            raise ValueError("NeMo-Speech invocation requires an audio_ref payload")
        decoded = self._decode_inline_audio(audio_ref)
        if decoded[0] not in {"audio/wav", "audio/x-wav"}:
            raise ValueError("NeMo-Speech requires audio_ref as a WAV data URI")
        evidence = self._inspect_inline_audio(decoded)
        response = self._invoke_nemo_asr(
            endpoint=self._endpoint(runtime_handle),
            model=self._model_id(runtime_handle),
            decoded_audio=decoded,
            language=task.payload.get("language"),
        )
        text = str(response.get("text", ""))
        usage = {
            "fixed_request_count": 1,
            "measurement_kind": "exact"
            if evidence.get("audio_input_milliseconds") is not None
            else "estimated",
            "measurement_source": (
                "hypervisor_ingress.wav_header"
                if evidence.get("audio_input_milliseconds") is not None
                else "provider_request"
            ),
            **evidence,
        }
        if "audio_input_milliseconds" not in usage:
            duration = self._audio_duration_milliseconds(response)
            if duration is not None:
                usage.update(
                    audio_input_milliseconds=duration,
                    measurement_kind="estimated",
                    measurement_source="provider_response.duration_ms",
                )
        return {
            "ok": True,
            "task_type": task.task_type,
            "model_id": self._model_id(runtime_handle),
            "text": text,
            "usage": usage,
            "raw": response,
        }

    def _invoke_nemo_asr(
        self,
        *,
        endpoint: str,
        model: str,
        decoded_audio: tuple[str, str, bytes],
        language: object = None,
    ) -> dict:
        content_type, filename, audio_bytes = decoded_audio
        boundary = f"aidn-nemo-speech-{hashlib.sha256(audio_bytes).hexdigest()[:24]}"
        body = bytearray()
        body.extend(f"--{boundary}\r\n".encode("ascii"))
        body.extend(
            (
                f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode("ascii")
        )
        body.extend(audio_bytes)
        body.extend(f"\r\n--{boundary}\r\n".encode("ascii"))
        body.extend(b'Content-Disposition: form-data; name="model"\r\n\r\n')
        body.extend(model.encode("utf-8"))
        body.extend(f"\r\n--{boundary}\r\n".encode("ascii"))
        body.extend(
            b'Content-Disposition: form-data; name="response_format"\r\n\r\n'
        )
        body.extend(b"verbose_json")
        if isinstance(language, str) and language.strip():
            body.extend(f"\r\n--{boundary}\r\n".encode("ascii"))
            body.extend(b'Content-Disposition: form-data; name="language"\r\n\r\n')
            body.extend(language.strip().encode("ascii", errors="ignore"))
        body.extend(f"\r\n--{boundary}--\r\n".encode("ascii"))
        return self._request_multipart(
            "POST",
            f"{endpoint.rstrip('/')}/v1/audio/transcriptions",
            bytes(body),
            content_type=f"multipart/form-data; boundary={boundary}",
        )

    def bundle_defaults_from_install(self, *, model_id: str, target_path: str) -> dict:
        return {
            "model_id": model_id,
            "launch_mode": "attached_service",
            "device_affinity": "gpu",
        }

    def usage_contract(self) -> dict:
        return {
            "supports_exact": True,
            "supports_estimated": True,
            "supported_billing_units": ["audio_input_milliseconds"],
            "supported_accounting_modes": ["deterministic", "fixed_price", "observable"],
            "default_measurement_source": "hypervisor_ingress.wav_header",
            "fallback_measurement_source": "provider_response.duration_ms",
            "fallback_policy": "provider_duration_estimate",
            "missing_usage_behavior": "strict_accounting",
        }


