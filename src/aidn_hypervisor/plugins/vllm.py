"""Attached-service vLLM Provider Plugin."""

import json
from urllib import error, parse, request

from aidn_hypervisor.plugins.base import ProviderPlugin


class VllmPlugin(ProviderPlugin):
    plugin_id = "vllm"
    plugin_version = "0.2.0"
    _runtime_version = "0.27.1"
    _default_endpoint = "http://127.0.0.1:8000"

    def describe(self) -> dict:
        return {
            "plugin_id": self.plugin_id,
            "plugin_version": self.plugin_version,
            "display_name": "vLLM OpenAI-compatible",
            "publisher": "AiDN Built-in",
            "package_digest": "sha256:a40d4f7c40e38b84d57894e7fb8bdd1aaaeb4adf96d319de1ec34cd0df424ed3",
            "provider_type": "vllm",
            "provider_families": ["vllm", "openai-compatible"],
            "plugin_capability_flags": [
                "CAN_ATTACH_EXISTING",
                "CAN_INSTALL_PROVIDER",
                "CAN_DISCOVER_MODELS",
            ],
            "required_permissions": [
                {
                    "permission_id": "host.package_manager",
                    "label": "Install reviewed Python runtime",
                    "risk_level": "high",
                    "reason": "Install pinned vLLM into an isolated uv environment",
                },
                {
                    "permission_id": "host.service_manager",
                    "label": "Manage reviewed user service",
                    "risk_level": "high",
                    "reason": "Create and supervise the loopback-only vLLM service",
                },
                {
                    "permission_id": "network.egress",
                    "label": "Download reviewed runtime",
                    "risk_level": "medium",
                    "reason": "Download vLLM and its pinned Python dependencies",
                },
            ],
            "trust_status": "AIDN_CURATED",
            "sandbox_policy": {
                "execution_mode": "RECORDED_ONLY",
                "filesystem_scope": "NONE",
                "network_scope": "NONE",
                "secret_scope": "DECLARED_HANDLES_ONLY",
                "notes": (
                    "The generic executor records approval only. Host mutation requires "
                    "the future allowlisted Provider runtime installer executor; model "
                    "credentials remain a separate secret-handle step."
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
            "source_repository": "https://github.com/vllm-project/vllm",
            "license": "Apache-2.0",
            "supported_platforms": ["linux"],
            "supported_architectures": ["x86_64", "arm64"],
            "supported_accelerators": ["cuda"],
            "installation_recipes": [
                {
                    "recipe_id": "vllm-ubuntu-cuda",
                    "display_name": "vLLM on this NVIDIA Ubuntu node",
                    "description": ("Install pinned vLLM; select and download a model later"),
                    "provider_configuration": {
                        "display_name": "Local vLLM",
                        "endpoint": self._default_endpoint,
                        "runtime_version": self._runtime_version,
                        "backend": "cuda",
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
            "schema_id": "vllm.install.v1",
            "fields": [
                {
                    "id": "display_name",
                    "type": "text",
                    "label": "Provider name",
                    "required": True,
                    "default": "Local vLLM",
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
                {
                    "id": "backend",
                    "type": "select",
                    "label": "Acceleration backend",
                    "required": True,
                    "default": "cuda",
                    "options": [{"value": "cuda", "label": "NVIDIA CUDA"}],
                },
            ],
        }

    def build_installation_plan(self, configuration: dict) -> dict:
        normalized = {
            "display_name": configuration.get("display_name") or "Local vLLM",
            "endpoint": configuration.get("endpoint") or self._default_endpoint,
            "runtime_version": (configuration.get("runtime_version") or self._runtime_version),
            "backend": configuration.get("backend") or "cuda",
        }
        self.validate_provider_configuration(normalized)
        version = str(normalized["runtime_version"])
        parts = version.split(".")
        if len(parts) != 3 or not all(part.isdigit() for part in parts):
            raise ValueError("runtime_version is invalid")
        if normalized["backend"] != "cuda":
            raise ValueError("the managed vLLM profile currently requires cuda")
        return {
            "plan_id": "plan-vllm-ubuntu-cuda-v1",
            "plugin_id": self.plugin_id,
            "plan_version": "1.0.0",
            "summary": "Install pinned vLLM in an isolated Ubuntu CUDA environment",
            "containers": [],
            "processes": [],
            "model_downloads": [],
            "volumes": [],
            "networks": [{"name": "vllm-loopback", "scope": "local"}],
            "environment": {},
            "resource_limits": {"accelerator": "cuda"},
            "health_checks": [
                {
                    "type": "http",
                    "url": f"{str(normalized['endpoint']).rstrip('/')}/v1/models",
                    "timeout_seconds": 5,
                }
            ],
            "required_permissions": self.plugin_manifest()["required_permissions"],
            "secret_references": [],
            "unsupported_actions": [],
        }

    def attach_provider_schema(self) -> dict:
        return {
            "schema_id": "vllm.attach.v1",
            "fields": [{"id": "endpoint", "type": "url", "label": "vLLM endpoint", "required": True}],
        }

    def validate_provider_configuration(self, configuration: dict) -> None:
        endpoint = configuration.get("endpoint") or configuration.get("base_url")
        if not isinstance(endpoint, str) or not endpoint.strip():
            raise ValueError("vLLM provider requires an endpoint")
        parsed = parse.urlparse(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("vLLM endpoint must be an absolute HTTP URL")
        if parsed.username or parsed.password:
            raise ValueError("vLLM endpoint must not include credentials")

    def attach_existing_provider(self, configuration: dict) -> dict:
        self.validate_provider_configuration(configuration)
        endpoint = str(configuration.get("endpoint") or configuration["base_url"]).rstrip("/")
        return {
            "configuration": {**configuration, "endpoint": endpoint},
            "connection_mode": "attached",
            "operational_state": "ready",
        }

    def discover_models(self, provider_instance: dict) -> list[dict]:
        endpoint = self._endpoint_from_configuration(provider_instance.get("configuration") or {})
        payload = self._request_json("GET", f"{endpoint}/v1/models")
        models = payload.get("data")
        if not isinstance(models, list):
            raise ValueError("vLLM model discovery returned invalid data")
        return [
            {
                "provider_model_reference": item["id"],
                "operator_display_name": item["id"],
                "metadata_sources": {"provider": "vllm-v1-models"},
                "capability_bindings": ["llm.chat"],
                "operational_state": "ready",
            }
            for item in models
            if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"]
        ]

    def health_check(self, runtime_handle) -> bool:
        try:
            payload = self._request_json("GET", f"{self._endpoint(runtime_handle)}/v1/models")
        except Exception:
            return False
        return isinstance(payload.get("data"), list)

    def validate_bundle(self, bundle_config) -> None:
        if bundle_config.workload_type != "llm_text":
            raise ValueError("vLLM plugin only supports llm_text workloads")
        if bundle_config.launch_mode != "attached_service":
            raise ValueError("vLLM plugin requires attached_service launch_mode")
        if not bundle_config.endpoint:
            raise ValueError("vLLM bundle requires an endpoint")

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
        raise ValueError("vLLM attached-service plugin does not manage local process launch")

    def invoke(self, task, runtime_handle) -> dict:
        prompt = task.payload.get("prompt")
        if not isinstance(prompt, str) or not prompt:
            raise ValueError("vLLM invocation requires a prompt payload")
        request_payload = {
            "model": self._model_id(runtime_handle),
            "prompt": prompt,
            "max_tokens": 64,
        }
        try:
            response = self._request_json(
                "POST",
                f"{self._endpoint(runtime_handle)}/v1/completions",
                request_payload,
                timeout_seconds=float(runtime_handle.metadata.get("timeout_seconds", 90)),
            )
        except TypeError as error:
            # Keep test and transitional adapters that implement the legacy
            # helper signature working while the plugin contract is upgraded.
            if "timeout_seconds" not in str(error):
                raise
            response = self._request_json("POST", f"{self._endpoint(runtime_handle)}/v1/completions", request_payload)
        choice = (response.get("choices") or [{}])[0]
        return {
            "ok": True,
            "task_type": task.task_type,
            "model_id": str(response.get("model", self._model_id(runtime_handle))),
            "output_text": str(choice.get("text", "")),
            "raw": response,
            "usage": self._usage_from_response(response.get("usage") or {}),
        }

    def stop(self, runtime_handle) -> None:
        return None

    def bundle_defaults_from_install(self, *, model_id: str, target_path: str) -> dict:
        return {
            "model_id": model_id,
            "launch_mode": "attached_service",
            "device_affinity": "gpu",
        }

    def create_runtime_binding(
        self, *, model_deployment: dict, capability_id: str, capability_version: str, capability_definition_hash: str
    ) -> dict:
        return {
            "model_deployment_id": model_deployment["model_deployment_id"],
            "provider_instance_id": model_deployment["provider_instance_id"],
            "capability_id": capability_id,
            "capability_version": capability_version,
            "capability_definition_hash": capability_definition_hash,
            "adapter_id": "vllm-openai",
            "adapter_version": "vllm-openai.v1",
            "supported_features": ["streaming", "cancellation"],
            "supported_modalities": ["text"],
            "supported_accounting_modes": ["provider_metered", "fixed_price", "observable"],
            "compatibility_bundle": {
                "plugin_id": self.plugin_id,
                "provider_type": "vllm",
                "workload_type": "llm_text",
                "model_id": model_deployment["provider_model_reference"],
                "launch_mode": "attached_service",
                "device_affinity": "gpu",
            },
            "status": "ready",
        }

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
        return self._endpoint_from_configuration(runtime_handle.metadata)

    def _endpoint_from_configuration(self, configuration: dict) -> str:
        return str(configuration.get("endpoint") or configuration.get("base_url") or self._default_endpoint).rstrip("/")

    def _model_id(self, runtime_handle) -> str:
        model_id = runtime_handle.metadata.get("model_id")
        if not model_id:
            raise ValueError("vLLM runtime metadata is missing model_id")
        return str(model_id)

    def _request_json(
        self,
        method: str,
        url: str,
        payload: dict | None = None,
        *,
        timeout_seconds: float = 5,
    ) -> dict:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Content-Type": "application/json"} if data is not None else {}
        try:
            with request.urlopen(
                request.Request(url, method=method, data=data, headers=headers), timeout=timeout_seconds
            ) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.URLError as exc:
            raise RuntimeError(str(exc)) from exc

    @staticmethod
    def _usage_from_response(usage: dict) -> dict:
        input_tokens, output_tokens = usage.get("prompt_tokens"), usage.get("completion_tokens")
        exact = isinstance(input_tokens, int) and isinstance(output_tokens, int)
        if exact:
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
