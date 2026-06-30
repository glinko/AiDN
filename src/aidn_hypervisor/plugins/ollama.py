import json
from urllib import error, request

from aidn_hypervisor.plugins.base import ProviderPlugin


class OllamaPlugin(ProviderPlugin):
    plugin_id = "ollama"
    _default_endpoint = "http://127.0.0.1:11434"
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
            "workload_types": ["llm_text"],
            "usage_contract": self.usage_contract(),
        }

    def validate_bundle(self, bundle_config) -> None:
        if bundle_config.workload_type != "llm_text":
            raise ValueError("Ollama plugin only supports llm_text workloads")
        if not bundle_config.endpoint:
            raise ValueError("Ollama bundle requires an endpoint")

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
            "concurrency_limit": 2,
        }

    def build_launch_spec(self, bundle_config) -> dict:
        self.validate_bundle(bundle_config)
        return {
            "command": ["ollama", "serve"],
            "metadata": {
                "endpoint": bundle_config.endpoint or self._default_endpoint,
                "model_id": bundle_config.model_id,
            },
        }

    def health_check(self, runtime_handle) -> bool:
        try:
            self._request_json("GET", f"{self._endpoint(runtime_handle)}/api/tags")
        except Exception:
            return False
        return True

    def invoke(self, task, runtime_handle) -> dict:
        prompt = task.payload.get("prompt")
        if not prompt:
            raise ValueError("Ollama invocation requires a prompt payload")

        response = self._request_json(
            "POST",
            f"{self._endpoint(runtime_handle)}/api/generate",
            {
                "model": self._model_id(runtime_handle),
                "prompt": prompt,
                "stream": False,
            },
        )
        result = {
            "ok": True,
            "task_type": task.task_type,
            "model_id": self._model_id(runtime_handle),
            "output_text": response.get("response", ""),
            "done": bool(response.get("done", False)),
            "raw": response,
        }
        result["usage"] = self._usage_from_response(response)
        return result

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
            "supports_exact": True,
            "supports_estimated": True,
            "default_measurement_source": "provider_api",
            "fallback_measurement_source": "provider_api_partial",
            "fallback_policy": "partial_response_estimate",
            "missing_usage_behavior": "skip",
        }

    def _endpoint(self, runtime_handle) -> str:
        return runtime_handle.metadata.get("endpoint", self._default_endpoint).rstrip("/")

    def _model_id(self, runtime_handle) -> str:
        model_id = runtime_handle.metadata.get("model_id")
        if not model_id:
            raise ValueError("Ollama runtime metadata is missing model_id")
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

    def _usage_from_response(self, response: dict) -> dict:
        input_tokens = response.get("prompt_eval_count")
        output_tokens = response.get("eval_count")
        if isinstance(input_tokens, int) and isinstance(output_tokens, int):
            return {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "fixed_request_count": 1,
                "measurement_kind": "exact",
                "measurement_source": "provider_api",
            }
        return {
            "input_tokens": int(input_tokens) if isinstance(input_tokens, int) else 0,
            "output_tokens": int(output_tokens) if isinstance(output_tokens, int) else 0,
            "fixed_request_count": 1,
            "measurement_kind": "estimated",
            "measurement_source": "provider_api_partial",
        }
