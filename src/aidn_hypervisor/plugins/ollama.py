import json
import re
from urllib import error, parse, request

from aidn_hypervisor.plugins.base import ProviderPlugin


class OllamaPlugin(ProviderPlugin):
    plugin_id = "ollama"
    plugin_version = "0.2.0"
    _runtime_version = "0.32.12"
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
            "plugin_version": self.plugin_version,
            "display_name": "Ollama",
            "publisher": "AiDN Built-in",
            "package_digest": "sha256:42dc8eff04ff8b320d4ae4df43d0e8100db887337927b799912da94837338320",
            "provider_type": "ollama",
            "provider_families": ["ollama"],
            "plugin_capability_flags": [
                "CAN_ATTACH_EXISTING",
                "CAN_INSTALL_PROVIDER",
                "CAN_DISCOVER_MODELS",
            ],
            "required_permissions": [
                {
                    "permission_id": "host.package_manager",
                    "label": "Install reviewed host packages",
                    "risk_level": "high",
                    "reason": "Install the pinned Ollama runtime on Ubuntu",
                },
                {
                    "permission_id": "host.service_manager",
                    "label": "Manage reviewed system service",
                    "risk_level": "high",
                    "reason": "Enable and supervise the loopback-only Ollama service",
                },
                {
                    "permission_id": "network.egress",
                    "label": "Download reviewed runtime",
                    "risk_level": "medium",
                    "reason": "Download Ollama from the official distribution endpoint",
                },
            ],
            "trust_status": "AIDN_CURATED",
            "sandbox_policy": {
                "execution_mode": "RECORDED_ONLY",
                "filesystem_scope": "NONE",
                "network_scope": "NONE",
                "secret_scope": "NONE",
                "notes": (
                    "The generic executor records approval only. Host mutation requires "
                    "the future allowlisted Provider runtime installer executor."
                ),
            },
            "runtime_installers": [
                {
                    "installer_id": "aidn-provider-runtime-ubuntu.v1",
                    "provider": self.plugin_id,
                    "platform": "ubuntu",
                    "script": "tools/aidn-provider-runtime-ubuntu.sh",
                    "pinned_version": self._runtime_version,
                    "actions": ["install", "start", "status", "stop"],
                    "model_configuration_separate": True,
                }
            ],
            "source_repository": "https://github.com/ollama/ollama",
            "license": "MIT",
            "supported_platforms": ["linux"],
            "supported_architectures": ["x86_64", "arm64"],
            "supported_accelerators": ["cpu", "cuda", "rocm"],
            "installation_recipes": [
                {
                    "recipe_id": "ollama-ubuntu-loopback",
                    "display_name": "Ollama on this Ubuntu node",
                    "description": ("Install pinned Ollama and bind it only to 127.0.0.1:11434"),
                    "provider_configuration": {
                        "display_name": "Local Ollama",
                        "endpoint": self._default_endpoint,
                        "runtime_version": self._runtime_version,
                    },
                    "model_configuration": {},
                    "endpoint_defaults": {"capability_id": "llm.chat"},
                }
            ],
            "supported_aidn_capabilities": ["llm.chat"],
            "workload_types": ["llm_text"],
            "usage_contract": self.usage_contract(),
        }

    def install_provider_schema(self) -> dict:
        return {
            "schema_id": "ollama.install.v1",
            "fields": [
                {
                    "id": "display_name",
                    "type": "text",
                    "label": "Provider name",
                    "required": True,
                    "default": "Local Ollama",
                },
                {
                    "id": "endpoint",
                    "type": "url",
                    "label": "Local endpoint",
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
            ],
        }

    def build_installation_plan(self, configuration: dict) -> dict:
        normalized = {
            "display_name": configuration.get("display_name") or "Local Ollama",
            "endpoint": configuration.get("endpoint") or self._default_endpoint,
            "runtime_version": (configuration.get("runtime_version") or self._runtime_version),
        }
        self.validate_provider_configuration(normalized)
        version = str(normalized["runtime_version"])
        if re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:[.-][A-Za-z0-9.-]+)?", version) is None:
            raise ValueError("runtime_version is invalid")
        return {
            "plan_id": "plan-ollama-ubuntu-v1",
            "plugin_id": self.plugin_id,
            "plan_version": "1.0.0",
            "summary": "Install pinned Ollama as a loopback-only Ubuntu service",
            "containers": [],
            "processes": [],
            "model_downloads": [],
            "volumes": [],
            "networks": [{"name": "ollama-loopback", "scope": "local"}],
            "environment": {"OLLAMA_HOST": "127.0.0.1:11434"},
            "resource_limits": {},
            "health_checks": [
                {
                    "type": "http",
                    "url": f"{str(normalized['endpoint']).rstrip('/')}/api/tags",
                    "timeout_seconds": 5,
                }
            ],
            "required_permissions": self.plugin_manifest()["required_permissions"],
            "secret_references": [],
            "unsupported_actions": [],
        }

    def attach_provider_schema(self) -> dict:
        return {
            "schema_id": "ollama.attach.v1",
            "fields": [
                {
                    "id": "endpoint",
                    "type": "url",
                    "label": "Ollama endpoint",
                    "required": True,
                    "default": self._default_endpoint,
                }
            ],
        }

    def attach_existing_provider(self, configuration: dict) -> dict:
        endpoint = str(configuration.get("endpoint") or configuration.get("base_url") or "").rstrip("/")
        parsed = parse.urlparse(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("Ollama endpoint must be an absolute credential-free HTTP URL")
        return {
            "configuration": {**configuration, "endpoint": endpoint},
            "connection_mode": "attached",
            "operational_state": "ready",
        }

    def discover_models(self, provider_instance: dict) -> list[dict]:
        configuration = provider_instance.get("configuration") or {}
        endpoint = str(configuration.get("endpoint") or self._default_endpoint).rstrip("/")
        models = self._request_json("GET", f"{endpoint}/api/tags").get("models")
        if not isinstance(models, list):
            raise ValueError("Ollama model discovery returned invalid data")
        return [
            {
                "provider_model_reference": item["model"],
                "operator_display_name": item.get("name", item["model"]),
                "metadata_sources": {"provider": "ollama-api-tags"},
                "capability_bindings": ["llm.chat"],
                "operational_state": "ready",
            }
            for item in models
            if isinstance(item, dict) and isinstance(item.get("model"), str) and item["model"]
        ]

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

        request_payload = {
            "model": self._model_id(runtime_handle),
            "prompt": prompt,
            "stream": False,
        }
        options = {}
        option_map = {
            "temperature": "temperature",
            "top_p": "top_p",
            "top_k": "top_k",
            "repeat_penalty": "repeat_penalty",
            "max_tokens": "num_predict",
            "context_length": "num_ctx",
        }
        for source_key, target_key in option_map.items():
            if source_key in task.payload:
                options[target_key] = task.payload[source_key]
        if options:
            request_payload["options"] = options
        try:
            response = self._request_json(
                "POST",
                f"{self._endpoint(runtime_handle)}/api/generate",
                request_payload,
                timeout_seconds=float(runtime_handle.metadata.get("timeout_seconds", 90)),
            )
        except TypeError as error:
            if "timeout_seconds" not in str(error):
                raise
            response = self._request_json("POST", f"{self._endpoint(runtime_handle)}/api/generate", request_payload)
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

    def create_runtime_binding(
        self,
        *,
        model_deployment: dict,
        capability_id: str,
        capability_version: str,
        capability_definition_hash: str,
    ) -> dict:
        """Project native Ollama generation onto the approved Runtime surface."""
        return {
            "model_deployment_id": model_deployment["model_deployment_id"],
            "provider_instance_id": model_deployment["provider_instance_id"],
            "capability_id": capability_id,
            "capability_version": capability_version,
            "capability_definition_hash": capability_definition_hash,
            "adapter_id": "ollama-generate",
            "adapter_version": "ollama-generate.v1",
            "supported_features": ["streaming", "cancellation"],
            "supported_modalities": ["text"],
            "supported_accounting_modes": [
                "provider_metered",
                "fixed_price",
                "observable",
            ],
            "compatibility_bundle": {
                "plugin_id": self.plugin_id,
                "provider_type": "ollama",
                "workload_type": "llm_text",
                "model_id": model_deployment["provider_model_reference"],
                "launch_mode": "attached_service",
                "device_affinity": "cpu",
            },
            "status": "ready",
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

    def _request_json(
        self,
        method: str,
        url: str,
        payload: dict | None = None,
        *,
        timeout_seconds: float = 5,
    ) -> dict:
        body = None
        headers = {}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = request.Request(url=url, method=method, data=body, headers=headers)
        try:
            with request.urlopen(req, timeout=timeout_seconds) as response:
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
        result = {
            "fixed_request_count": 1,
            "measurement_kind": "estimated",
            "measurement_source": "provider_api_partial",
        }
        if isinstance(input_tokens, int):
            result["input_tokens"] = input_tokens
        if isinstance(output_tokens, int):
            result["output_tokens"] = output_tokens
        return result
