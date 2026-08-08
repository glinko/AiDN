import base64
import binascii
import hashlib
import json
import re
from urllib import error, parse, request

from aidn_hypervisor.plugins.base import ProviderPlugin


class WhisperPlugin(ProviderPlugin):
    plugin_id = "whisper"
    plugin_version = "0.2.0"
    _default_endpoint = "http://127.0.0.1:9000"
    _default_model = "small"
    _managed_api_format = "whisper_asr_webservice"
    _supported_api_formats = {"aidn_json", "whisper_asr_webservice"}
    _max_inline_audio_bytes = 25 * 1024 * 1024
    _audio_mime_extensions = {
        "audio/flac": "flac",
        "audio/mpeg": "mp3",
        "audio/mp4": "m4a",
        "audio/ogg": "ogg",
        "audio/wav": "wav",
        "audio/webm": "webm",
        "audio/x-flac": "flac",
        "audio/x-wav": "wav",
    }
    _circuit_breaker_policy = {
        "failure_threshold": 2,
        "cooldown_seconds": 30.0,
    }
    _retry_policy = {
        "health_check": {"max_attempts": 3, "backoff_seconds": 0.25},
        "invoke": {
            "max_attempts": 3,
            "backoff_seconds": 0.5,
            "retry_exceptions": (RuntimeError,),
        },
    }

    def describe(self) -> dict:
        return {
            "plugin_id": self.plugin_id,
            "plugin_version": self.plugin_version,
            "display_name": "Whisper HTTP Provider",
            "publisher": "AiDN Built-in",
            "package_digest": (
                "sha256:e31e667a78a007570c26933d553812143f6f436e36f017ae5697375f25f8a959"
            ),
            "provider_type": "whisper",
            "provider_families": ["whisper"],
            "plugin_capability_flags": [
                "CAN_ATTACH_EXISTING",
                "CAN_INSTALL_PROVIDER",
                "CAN_DISCOVER_MODELS",
            ],
            "required_permissions": [
                {
                    "permission_id": "network.private",
                    "label": "Private provider network",
                    "risk_level": "low",
                    "reason": "Connect to the operator-selected Whisper HTTP endpoint",
                }
            ],
            "trust_status": "AIDN_CURATED",
            "sandbox_policy": {
                "execution_mode": "RECORDED_ONLY",
                "filesystem_scope": "NONE",
                "network_scope": "NONE",
                "secret_scope": "DECLARED_HANDLES_ONLY",
                "notes": (
                    "The MVP apply records local provider inventory only; it does not "
                    "install packages or start a host process."
                ),
            },
            "supported_platforms": ["linux", "darwin", "windows"],
            "supported_architectures": ["x86_64", "arm64"],
            "supported_accelerators": ["cpu", "cuda"],
            "installation_recipes": [
                {
                    "recipe_id": "whisper-local-http",
                    "display_name": "Local Whisper HTTP",
                    "description": (
                        "Register an operator-managed Whisper HTTP service on this host"
                    ),
                    "provider_configuration": {
                        "display_name": "Local Whisper",
                        "endpoint": self._default_endpoint,
                        "model_id": self._default_model,
                        "api_format": self._managed_api_format,
                    },
                    "model_configuration": {
                        "provider_model_reference": self._default_model,
                    },
                    "endpoint_defaults": {
                        "capability_id": "speech_to_text",
                    },
                }
            ],
            "supported_aidn_capabilities": ["speech_to_text"],
            "workload_types": ["speech_to_text"],
            "usage_contract": self.usage_contract(),
        }

    def attach_provider_schema(self) -> dict:
        return self.install_provider_schema().copy() | {"schema_id": "whisper.attach.v1"}

    def install_provider_schema(self) -> dict:
        return {
            "schema_id": "whisper.install.v1",
            "fields": [
                {
                    "id": "display_name",
                    "type": "text",
                    "label": "Provider name",
                    "required": True,
                    "default": "Local Whisper",
                },
                {
                    "id": "endpoint",
                    "type": "url",
                    "label": "Whisper HTTP endpoint",
                    "required": True,
                    "default": self._default_endpoint,
                },
                {
                    "id": "model_id",
                    "type": "text",
                    "label": "Provider model ID",
                    "required": True,
                    "default": self._default_model,
                },
                {
                    "id": "api_format",
                    "type": "select",
                    "label": "Whisper API format",
                    "required": False,
                    "default": "aidn_json",
                    "options": [
                        {"value": "aidn_json", "label": "AiDN JSON adapter"},
                        {
                            "value": "whisper_asr_webservice",
                            "label": "Whisper ASR Webservice",
                        },
                    ],
                },
            ],
        }

    def validate_provider_configuration(self, configuration: dict) -> None:
        display_name = str(configuration.get("display_name", "")).strip()
        endpoint = str(configuration.get("endpoint", "")).strip()
        model_id = str(configuration.get("model_id", "")).strip()
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
        if not model_id:
            raise ValueError("model_id is required")
        api_format = str(configuration.get("api_format") or "aidn_json").strip()
        if api_format not in self._supported_api_formats:
            raise ValueError("api_format is unsupported")

    def build_installation_plan(self, configuration: dict) -> dict:
        self.validate_provider_configuration(configuration)
        endpoint = str(configuration["endpoint"]).rstrip("/")
        api_format = str(configuration.get("api_format") or "aidn_json")
        health_url = (
            f"{endpoint}/openapi.json"
            if api_format == self._managed_api_format
            else f"{endpoint}/health"
        )
        return {
            "plan_id": "plan-whisper-http-v1",
            "plugin_id": self.plugin_id,
            "plan_version": "1.0.0",
            "summary": "Register an operator-managed Whisper HTTP provider",
            "containers": [],
            "processes": [],
            "model_downloads": [],
            "volumes": [],
            "networks": [{"name": "whisper-provider", "scope": "private"}],
            "environment": {},
            "resource_limits": {"cpu": "operator-managed"},
            "health_checks": [
                {
                    "type": "http",
                    "url": health_url,
                    "timeout_seconds": 5,
                }
            ],
            "required_permissions": self.plugin_manifest()["required_permissions"],
            "secret_references": [],
            "unsupported_actions": [],
        }

    def discover_models(self, provider_instance: dict) -> list[dict]:
        configuration = provider_instance.get("configuration") or {}
        model_id = str(configuration.get("model_id") or self._default_model)
        provider_instance_id = provider_instance["provider_instance_id"]
        model_suffix = hashlib.sha256(model_id.encode("utf-8")).hexdigest()[:12]
        return [
            {
                "model_deployment_id": f"md-{provider_instance_id}-{model_suffix}",
                "provider_instance_id": provider_instance_id,
                "provider_model_reference": model_id,
                "operator_display_name": model_id,
                "declared_model_name": model_id,
                "metadata_sources": {
                    "declared_model_name": "OPERATOR_DECLARED",
                    "provider_model_reference": "OPERATOR_DECLARED",
                },
                "capability_bindings": ["speech_to_text"],
                "operational_state": "ready",
            }
        ]

    def create_runtime_binding(
        self,
        *,
        model_deployment: dict,
        capability_id: str,
        capability_version: str,
        capability_definition_hash: str,
    ) -> dict:
        binding = super().create_runtime_binding(
            model_deployment=model_deployment,
            capability_id=capability_id,
            capability_version=capability_version,
            capability_definition_hash=capability_definition_hash,
        )
        binding["compatibility_bundle"].update(
            {
                "plugin_id": self.plugin_id,
                "provider_type": "whisper",
                "workload_type": "speech_to_text",
                "launch_mode": "attached_service",
                "device_affinity": "cpu",
            }
        )
        provider_configuration = model_deployment.get("provider_configuration") or {}
        api_format = str(provider_configuration.get("api_format") or "aidn_json").strip()
        if api_format not in self._supported_api_formats:
            raise ValueError("api_format is unsupported")
        binding["compatibility_bundle"]["provider_api_format"] = api_format
        return binding

    def validate_bundle(self, bundle_config) -> None:
        if bundle_config.workload_type != "speech_to_text":
            raise ValueError("Whisper plugin only supports speech_to_text workloads")
        if not bundle_config.endpoint:
            raise ValueError("Whisper bundle requires an endpoint")

    def estimate_resources(self, task, bundle_config, runtime_state) -> dict:
        profile = bundle_config.resource_profile
        return {
            "startup_transient": {},
            "runtime_resident": {
                "cpu": profile.steady_cpu,
                "ram_mb": profile.steady_ram_mb,
                "vram_mb": profile.steady_vram_mb,
            },
            "request_active": {
                "cpu": profile.per_request_cpu,
                "ram_mb": profile.per_request_ram_mb,
                "vram_mb": profile.per_request_vram_mb,
            },
            "concurrency_limit": 1,
        }

    def build_launch_spec(self, bundle_config) -> dict:
        self.validate_bundle(bundle_config)
        launch_spec = {
            "command": ["whisper-server"],
            "metadata": {
                "endpoint": bundle_config.endpoint or self._default_endpoint,
                "model_id": bundle_config.model_id,
            },
        }
        api_format = getattr(bundle_config, "provider_api_format", None)
        if api_format:
            launch_spec["metadata"]["api_format"] = api_format
        return launch_spec

    def health_check(self, runtime_handle) -> bool:
        try:
            if self._api_format(runtime_handle) == self._managed_api_format:
                payload = self._request_json(
                    "GET", f"{self._endpoint(runtime_handle)}/openapi.json"
                )
                return "/asr" in payload.get("paths", {})
            payload = self._request_json("GET", f"{self._endpoint(runtime_handle)}/health")
        except Exception:
            return False
        return payload.get("status") == "ok"

    def invoke(self, task, runtime_handle) -> dict:
        audio_ref = task.payload.get("audio_ref")
        if not audio_ref:
            raise ValueError("Whisper invocation requires an audio_ref payload")

        if self._api_format(runtime_handle) == self._managed_api_format:
            response = self._invoke_native_asr(
                endpoint=self._endpoint(runtime_handle),
                audio_ref=str(audio_ref),
            )
        else:
            response = self._request_json(
                "POST",
                f"{self._endpoint(runtime_handle)}/v1/audio/transcriptions",
                {
                    "model": self._model_id(runtime_handle),
                    "audio_ref": audio_ref,
                },
            )
        usage = {
            "fixed_request_count": 1,
            "measurement_kind": "estimated",
            "measurement_source": "provider_request",
        }
        duration_seconds = self._audio_duration_seconds(response)
        if duration_seconds is not None:
            usage["audio_input_seconds"] = duration_seconds
            usage["measurement_source"] = "provider_response.duration"
        return {
            "ok": True,
            "task_type": task.task_type,
            "model_id": self._model_id(runtime_handle),
            "text": response.get("text", ""),
            "usage": usage,
            "raw": response,
        }

    def stop(self, runtime_handle) -> None:
        return None

    def bundle_defaults_from_install(self, *, model_id: str, target_path: str) -> dict:
        return {
            "model_id": model_id,
            "launch_mode": "attached_service",
            "device_affinity": "cpu",
        }

    def retry_policy(self) -> dict:
        return dict(self._retry_policy)

    def circuit_breaker_policy(self) -> dict:
        return dict(self._circuit_breaker_policy)

    def usage_contract(self) -> dict:
        return {
            "supports_exact": False,
            "supports_estimated": True,
            "supported_billing_units": ["audio_input_seconds"],
            "supported_accounting_modes": ["fixed_price", "observable"],
            "default_measurement_source": "provider_request",
            "fallback_measurement_source": "provider_request",
            "fallback_policy": "fixed_request_estimate",
            "missing_usage_behavior": "skip",
        }

    @staticmethod
    def _audio_duration_seconds(response: dict) -> float | None:
        """Accept only non-negative numeric duration evidence from the Provider."""
        for key in ("audio_duration_seconds", "duration_seconds", "duration"):
            value = response.get(key)
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)) and value >= 0:
                return float(value)
        return None

    def _endpoint(self, runtime_handle) -> str:
        return runtime_handle.metadata.get("endpoint", self._default_endpoint).rstrip("/")

    def _model_id(self, runtime_handle) -> str:
        model_id = runtime_handle.metadata.get("model_id")
        if not model_id:
            raise ValueError("Whisper runtime metadata is missing model_id")
        return model_id

    def _api_format(self, runtime_handle) -> str:
        api_format = str(runtime_handle.metadata.get("api_format") or "aidn_json")
        if api_format not in self._supported_api_formats:
            raise ValueError("Whisper runtime metadata has unsupported api_format")
        return api_format

    def _invoke_native_asr(
        self, *, endpoint: str, audio_ref: str
    ) -> dict:
        content_type, filename, audio_bytes = self._decode_inline_audio(audio_ref)
        boundary = f"aidn-whisper-{hashlib.sha256(audio_bytes).hexdigest()[:24]}"
        body = bytearray()
        body.extend(f"--{boundary}\r\n".encode("ascii"))
        body.extend(
            (
                f'Content-Disposition: form-data; name="audio_file"; '
                f'filename="{filename}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode("ascii")
        )
        body.extend(audio_bytes)
        body.extend(f"\r\n--{boundary}--\r\n".encode("ascii"))
        return self._request_multipart(
            "POST",
            f"{endpoint}/asr?{parse.urlencode({'task': 'transcribe', 'output': 'json'})}",
            bytes(body),
            content_type=f"multipart/form-data; boundary={boundary}",
        )

    def _decode_inline_audio(self, audio_ref: str) -> tuple[str, str, bytes]:
        match = re.fullmatch(
            r"data:(?P<mime>[^;,]+);base64,(?P<data>[A-Za-z0-9+/=\s]+)",
            audio_ref,
            flags=re.IGNORECASE,
        )
        if match is None:
            raise ValueError(
                "native Whisper requires audio_ref as a base64 data URI; "
                "arbitrary filesystem paths are not permitted"
            )
        content_type = match.group("mime").lower()
        extension = self._audio_mime_extensions.get(content_type)
        if extension is None:
            raise ValueError(f"native Whisper does not accept audio MIME type: {content_type}")
        try:
            audio_bytes = base64.b64decode(
                re.sub(r"\s+", "", match.group("data")), validate=True
            )
        except (ValueError, binascii.Error) as exc:
            raise ValueError("audio_ref contains invalid base64 audio data") from exc
        if not audio_bytes:
            raise ValueError("audio_ref contains empty audio data")
        if len(audio_bytes) > self._max_inline_audio_bytes:
            raise ValueError(
                f"inline audio exceeds {self._max_inline_audio_bytes} byte limit"
            )
        return content_type, f"input.{extension}", audio_bytes

    def _request_json(self, method: str, url: str, payload: dict | None = None) -> dict:
        body = None
        headers = {}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = request.Request(url=url, method=method, data=body, headers=headers)
        try:
            with request.urlopen(req, timeout=5) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.URLError as exc:
            raise RuntimeError(str(exc)) from exc

    def _request_multipart(
        self,
        method: str,
        url: str,
        body: bytes,
        *,
        content_type: str,
    ) -> dict:
        req = request.Request(
            url=url,
            method=method,
            data=body,
            headers={
                "Content-Type": content_type,
                "Content-Length": str(len(body)),
                "Accept": "application/json",
            },
        )
        try:
            with request.urlopen(req, timeout=60) as response:
                raw = response.read().decode("utf-8")
        except error.URLError as exc:
            raise RuntimeError(str(exc)) from exc
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("native Whisper returned a non-JSON response") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("native Whisper returned an invalid JSON response")
        return payload
