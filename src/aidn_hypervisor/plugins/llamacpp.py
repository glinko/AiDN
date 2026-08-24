import json
import os
import shutil
from pathlib import Path
from urllib import error, parse, request

from aidn_hypervisor.plugins.base import ProviderPlugin
from aidn_hypervisor.resource_estimator import estimate_llama_cpp_resources


class LlamaCppPlugin(ProviderPlugin):
    plugin_id = "llama.cpp"
    plugin_version = "0.2.0"
    _runtime_ref = "b10433"
    _default_endpoint = "http://127.0.0.1:8080"
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
            "display_name": "llama.cpp OpenAI-compatible",
            "publisher": "AiDN Built-in",
            "package_digest": "sha256:d59dfb2694f413e63109cc2abfad814be469787f804fc348a85594290df8798a",
            "provider_type": "llama.cpp",
            "provider_families": ["llama.cpp", "openai-compatible"],
            "plugin_capability_flags": [
                "CAN_ATTACH_EXISTING",
                "CAN_INSTALL_PROVIDER",
                "CAN_DISCOVER_MODELS",
            ],
            "required_permissions": [
                {
                    "permission_id": "host.package_manager",
                    "label": "Install reviewed build dependencies",
                    "risk_level": "high",
                    "reason": "Install the Ubuntu toolchain required to build llama.cpp",
                },
                {
                    "permission_id": "host.service_manager",
                    "label": "Manage reviewed user service",
                    "risk_level": "high",
                    "reason": "Create and supervise the loopback-only llama.cpp service",
                },
                {
                    "permission_id": "network.egress",
                    "label": "Download reviewed source",
                    "risk_level": "medium",
                    "reason": "Fetch the pinned llama.cpp release from its official repository",
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
                    "pinned_version": self._runtime_ref,
                    "actions": ["install", "start", "status", "stop", "remove"],
                    "model_configuration_separate": True,
                }
            ],
            "source_repository": "https://github.com/ggml-org/llama.cpp",
            "license": "MIT",
            "supported_platforms": ["linux"],
            "supported_architectures": ["x86_64", "arm64"],
            "supported_accelerators": ["cpu", "cuda"],
            "installation_recipes": [
                {
                    "recipe_id": "llamacpp-ubuntu-cpu",
                    "display_name": "llama.cpp on this Ubuntu node",
                    "description": ("Build the reviewed llama-server release; add a GGUF model later"),
                    "provider_configuration": {
                        "display_name": "Local llama.cpp",
                        "endpoint": self._default_endpoint,
                        "runtime_ref": self._runtime_ref,
                        "backend": "cpu",
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
            "schema_id": "llamacpp.install.v1",
            "fields": [
                {
                    "id": "display_name",
                    "type": "text",
                    "label": "Provider name",
                    "required": True,
                    "default": "Local llama.cpp",
                },
                {
                    "id": "endpoint",
                    "type": "url",
                    "label": "Local endpoint",
                    "required": True,
                    "default": self._default_endpoint,
                },
                {
                    "id": "runtime_ref",
                    "type": "text",
                    "label": "Reviewed runtime release",
                    "required": True,
                    "default": self._runtime_ref,
                },
                {
                    "id": "backend",
                    "type": "select",
                    "label": "Acceleration backend",
                    "required": True,
                    "default": "cpu",
                    "options": [
                        {"value": "cpu", "label": "CPU"},
                        {"value": "cuda", "label": "NVIDIA CUDA"},
                    ],
                },
            ],
        }

    def build_installation_plan(self, configuration: dict) -> dict:
        normalized = {
            "display_name": configuration.get("display_name") or "Local llama.cpp",
            "endpoint": configuration.get("endpoint") or self._default_endpoint,
            "runtime_ref": configuration.get("runtime_ref") or self._runtime_ref,
            "backend": configuration.get("backend") or "cpu",
        }
        self.validate_provider_configuration(normalized)
        runtime_ref = str(normalized["runtime_ref"])
        if not runtime_ref or any(character.isspace() for character in runtime_ref):
            raise ValueError("runtime_ref is invalid")
        backend = str(normalized["backend"])
        if backend not in {"cpu", "cuda"}:
            raise ValueError("backend must be cpu or cuda")
        return {
            "plan_id": "plan-llamacpp-ubuntu-v1",
            "plugin_id": self.plugin_id,
            "plan_version": "1.0.0",
            "summary": "Build pinned llama.cpp for a loopback-only Ubuntu runtime",
            "containers": [],
            "processes": [],
            "model_downloads": [],
            "volumes": [],
            "networks": [{"name": "llamacpp-loopback", "scope": "local"}],
            "environment": {},
            "resource_limits": {},
            "health_checks": [
                {
                    "type": "http",
                    "url": f"{str(normalized['endpoint']).rstrip('/')}/health",
                    "timeout_seconds": 5,
                }
            ],
            "required_permissions": self.plugin_manifest()["required_permissions"],
            "secret_references": [],
            "unsupported_actions": [],
        }

    def attach_provider_schema(self) -> dict:
        return {
            "schema_id": "llamacpp.attach.v1",
            "fields": [
                {
                    "id": "endpoint",
                    "type": "url",
                    "label": "OpenAI-compatible endpoint",
                    "required": True,
                    "default": self._default_endpoint,
                }
            ],
        }

    def validate_provider_configuration(self, configuration: dict) -> None:
        endpoint = configuration.get("endpoint") or configuration.get("base_url")
        if not isinstance(endpoint, str) or not endpoint.strip():
            raise ValueError("llama.cpp provider requires an endpoint")
        parsed = parse.urlparse(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("llama.cpp endpoint must be an absolute HTTP URL")
        if parsed.username or parsed.password:
            raise ValueError("llama.cpp endpoint must not include credentials")

    def attach_existing_provider(self, configuration: dict) -> dict:
        self.validate_provider_configuration(configuration)
        endpoint = str(configuration.get("endpoint") or configuration["base_url"]).rstrip("/")
        return {
            "configuration": {**configuration, "endpoint": endpoint},
            "connection_mode": "attached",
            "operational_state": "ready",
        }

    def discover_models(self, provider_instance: dict) -> list[dict]:
        configuration = provider_instance.get("configuration") or {}
        endpoint = configuration.get("endpoint") or configuration.get("base_url")
        self.validate_provider_configuration({"endpoint": endpoint})
        payload = self._request_json("GET", f"{str(endpoint).rstrip('/')}/v1/models")
        models = payload.get("data")
        if not isinstance(models, list):
            raise ValueError("llama.cpp model discovery returned invalid data")
        discovered = []
        for item in models:
            model_id = item.get("id") if isinstance(item, dict) else None
            if not isinstance(model_id, str) or not model_id:
                continue
            discovered.append(
                {
                    "provider_model_reference": model_id,
                    "operator_display_name": model_id,
                    "metadata_sources": {"provider": "llamacpp-v1-models"},
                    "capability_bindings": ["llm.chat"],
                    "operational_state": "ready",
                }
            )
        return discovered

    def validate_bundle(self, bundle_config) -> None:
        if bundle_config.workload_type != "llm_text":
            raise ValueError("llama.cpp plugin only supports llm_text workloads")
        if bundle_config.launch_mode != "managed_process":
            raise ValueError("llama.cpp plugin requires managed_process launch_mode")
        if not bundle_config.endpoint:
            raise ValueError("llama.cpp bundle requires an endpoint")

    def estimate_resources(self, task, bundle_config, runtime_state) -> dict:
        profile = bundle_config.resource_profile
        return estimate_llama_cpp_resources(
            model_id=bundle_config.model_id,
            policy=bundle_config.runtime_parameter_policy,
            resource_profile=profile,
            max_parallel_requests=bundle_config.max_parallel_requests,
            runtime_warm=runtime_state is not None,
        )

    def build_launch_spec(self, bundle_config) -> dict:
        self.validate_bundle(bundle_config)
        endpoint = bundle_config.endpoint or self._default_endpoint
        parsed = parse.urlparse(endpoint)
        host = parsed.hostname or "127.0.0.1"
        port = str(parsed.port or 8080)
        return {
            "command": self._launch_command(
                bundle_config,
                host=host,
                port=port,
            ),
            "metadata": {
                "endpoint": endpoint,
                "model_id": bundle_config.model_id,
            },
        }

    @classmethod
    def _server_binary(cls) -> str:
        """Resolve the reviewed llama-server binary for managed processes.

        Provider installers keep the executable in the operator-owned runtime
        root, while manually built CUDA runtimes commonly remain under a
        ``build-*/bin`` directory.  The Hypervisor service intentionally has a
        small systemd PATH, so relying on ``llama-server`` being discoverable
        there makes an otherwise installed provider look broken.
        """

        configured = os.environ.get("AIDN_LLAMA_CPP_SERVER_BIN", "").strip()
        if configured:
            return configured

        # Preserve the normal command when an operator explicitly installed a
        # system-wide/runtime-PATH binary.
        if shutil.which("llama-server"):
            return "llama-server"

        runtime_root = os.environ.get("AIDN_LLAMA_CPP_RUNTIME_ROOT", "").strip()
        root = Path(runtime_root).expanduser() if runtime_root else (
            Path.home() / ".local" / "share" / "aidn" / "providers" / "llama.cpp"
        )
        candidates = [root / "bin" / "llama-server"]
        candidates.extend(sorted(root.glob("build*/bin/llama-server")))
        for candidate in candidates:
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)

        # Keep the original command as the final fallback so the process
        # manager raises FileNotFoundError and the MCP boundary can report a
        # precise, actionable diagnostic.
        return "llama-server"

    @classmethod
    def _launch_command(cls, bundle_config, *, host: str, port: str) -> list[str]:
        command = [
            cls._server_binary(),
            "--model",
            bundle_config.model_id,
            "--host",
            host,
            "--port",
            port,
        ]
        policy = bundle_config.runtime_parameter_policy
        launch_flags = {
            "context_length": "--ctx-size",
            "gpu_layers": "--n-gpu-layers",
            "batch_size": "--batch-size",
            "threads": "--threads",
        }
        for name, flag in launch_flags.items():
            setting = policy.get(name)
            if setting is not None:
                command.extend([flag, str(setting.value)])
        kv_offload = policy.get("kv_offload")
        if kv_offload is not None:
            command.append("--kv-offload" if bool(kv_offload.value) else "--no-kv-offload")
        for name, flag in (
            ("kv_cache_type_k", "--cache-type-k"),
            ("kv_cache_type_v", "--cache-type-v"),
        ):
            setting = policy.get(name)
            if setting is not None and str(setting.value).strip():
                command.extend([flag, str(setting.value).strip()])
        return command

    def health_check(self, runtime_handle) -> bool:
        try:
            payload = self._request_json("GET", f"{self._endpoint(runtime_handle)}/health")
        except Exception:
            return False
        return payload.get("status") == "ok"

    def invoke(self, task, runtime_handle) -> dict:
        prompt = task.payload.get("prompt")
        if not prompt:
            raise ValueError("llama.cpp invocation requires a prompt payload")

        request_payload = {"prompt": prompt, "stream": False}
        request_map = {
            "temperature": "temperature",
            "top_p": "top_p",
            "top_k": "top_k",
            "repeat_penalty": "repeat_penalty",
            "max_tokens": "n_predict",
        }
        for source_key, target_key in request_map.items():
            if source_key in task.payload:
                request_payload[target_key] = task.payload[source_key]
        # CPU-resident models can legitimately spend longer than the short
        # health/discovery timeout generating a response.  Keep transport
        # timeout separate from the provider probe timeout and allow the
        # runtime to override it when a managed bundle supplies one.
        timeout_seconds = runtime_handle.metadata.get("timeout_seconds", 90)
        try:
            timeout_seconds = max(1.0, min(3600.0, float(timeout_seconds)))
        except (TypeError, ValueError):
            timeout_seconds = 90.0
        try:
            response = self._request_json(
                "POST",
                f"{self._endpoint(runtime_handle)}/completion",
                request_payload,
                timeout_seconds=timeout_seconds,
            )
        except TypeError as error:
            # Keep transitional/external plugin test doubles compatible with
            # the older helper signature while the provider contract rolls out.
            if "timeout_seconds" not in str(error):
                raise
            response = self._request_json(
                "POST",
                f"{self._endpoint(runtime_handle)}/completion",
                request_payload,
            )
        result = {
            "ok": True,
            "task_type": task.task_type,
            "model_id": self._model_id(runtime_handle),
            "output_text": response.get("content", ""),
            "raw": response,
        }
        result["usage"] = self._usage_from_response(response)
        return result

    def stop(self, runtime_handle) -> None:
        return None

    def bundle_defaults_from_install(self, *, model_id: str, target_path: str) -> dict:
        return {
            "model_id": target_path,
            "launch_mode": "managed_process",
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

    def create_runtime_binding(
        self,
        *,
        model_deployment: dict,
        capability_id: str,
        capability_version: str,
        capability_definition_hash: str,
    ) -> dict:
        """Project a llama.cpp deployment onto the RFC-0054 adapter surface."""
        return {
            "model_deployment_id": model_deployment["model_deployment_id"],
            "provider_instance_id": model_deployment["provider_instance_id"],
            "capability_id": capability_id,
            "capability_version": capability_version,
            "capability_definition_hash": capability_definition_hash,
            "adapter_id": "llamacpp-openai",
            "adapter_version": "llamacpp-openai.v1",
            "supported_features": ["streaming", "cancellation"],
            "supported_modalities": ["text"],
            "supported_accounting_modes": [
                "provider_metered",
                "fixed_price",
                "observable",
            ],
            "compatibility_bundle": {
                "plugin_id": self.plugin_id,
                "provider_type": "llama.cpp",
                "workload_type": "llm_text",
                "model_id": model_deployment["provider_model_reference"],
                "launch_mode": "managed_process",
                "device_affinity": "cpu",
            },
            "status": "ready",
        }

    def _endpoint(self, runtime_handle) -> str:
        return runtime_handle.metadata.get("endpoint", self._default_endpoint).rstrip("/")

    def _model_id(self, runtime_handle) -> str:
        model_id = runtime_handle.metadata.get("model_id")
        if not model_id:
            raise ValueError("llama.cpp runtime metadata is missing model_id")
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
        except (error.URLError, TimeoutError) as exc:
            raise RuntimeError(str(exc)) from exc

    def _usage_from_response(self, response: dict) -> dict:
        input_tokens = response.get("tokens_evaluated")
        output_tokens = response.get("tokens_predicted")
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
