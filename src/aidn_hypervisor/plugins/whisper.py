import json
from urllib import error, request

from aidn_hypervisor.plugins.base import ProviderPlugin


class WhisperPlugin(ProviderPlugin):
    plugin_id = "whisper"
    _default_endpoint = "http://127.0.0.1:9000"
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
            "workload_types": ["speech_to_text"],
            "usage_contract": self.usage_contract(),
        }

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
        return {
            "command": ["whisper-server"],
            "metadata": {
                "endpoint": bundle_config.endpoint or self._default_endpoint,
                "model_id": bundle_config.model_id,
            },
        }

    def health_check(self, runtime_handle) -> bool:
        try:
            payload = self._request_json("GET", f"{self._endpoint(runtime_handle)}/health")
        except Exception:
            return False
        return payload.get("status") == "ok"

    def invoke(self, task, runtime_handle) -> dict:
        audio_ref = task.payload.get("audio_ref")
        if not audio_ref:
            raise ValueError("Whisper invocation requires an audio_ref payload")

        response = self._request_json(
            "POST",
            f"{self._endpoint(runtime_handle)}/v1/audio/transcriptions",
            {
                "model": self._model_id(runtime_handle),
                "audio_ref": audio_ref,
            },
        )
        return {
            "ok": True,
            "task_type": task.task_type,
            "model_id": self._model_id(runtime_handle),
            "text": response.get("text", ""),
            "usage": {
                "input_tokens": 0,
                "output_tokens": 0,
                "fixed_request_count": 1,
                "measurement_kind": "estimated",
                "measurement_source": "provider_request",
            },
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
            "default_measurement_source": "provider_request",
            "fallback_measurement_source": "provider_request",
            "fallback_policy": "fixed_request_estimate",
            "missing_usage_behavior": "skip",
        }

    def _endpoint(self, runtime_handle) -> str:
        return runtime_handle.metadata.get("endpoint", self._default_endpoint).rstrip("/")

    def _model_id(self, runtime_handle) -> str:
        model_id = runtime_handle.metadata.get("model_id")
        if not model_id:
            raise ValueError("Whisper runtime metadata is missing model_id")
        return model_id

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
