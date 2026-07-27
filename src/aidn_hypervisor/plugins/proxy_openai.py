"""Attached opaque OpenAI-compatible upstream Provider Plugin."""

import json
from urllib import error, parse, request

from aidn_hypervisor.plugins.base import ProviderPlugin


class ProxyOpenAIPlugin(ProviderPlugin):
    """Provision proxy execution without claiming unavailable upstream tokens."""

    plugin_id = "proxy-openai"

    def describe(self) -> dict:
        return {
            "plugin_id": self.plugin_id,
            "plugin_version": "0.1.0",
            "display_name": "Opaque OpenAI-compatible Proxy",
            "provider_type": "proxy-openai",
            "provider_families": ["proxy", "openai-compatible"],
            "plugin_capability_flags": ["CAN_ATTACH_EXISTING", "CAN_DISCOVER_MODELS"],
            "supported_aidn_capabilities": ["llm.chat"],
            "workload_types": ["llm_text"],
            "usage_contract": self.usage_contract(),
        }

    def attach_provider_schema(self) -> dict:
        return {
            "schema_id": "proxy-openai.attach.v1",
            "fields": [
                {"id": "endpoint", "type": "url", "label": "Upstream endpoint", "required": True},
                {"id": "credential_handle", "type": "secret_handle", "label": "Credential handle", "required": False},
            ],
        }

    def validate_provider_configuration(self, configuration: dict) -> None:
        endpoint = configuration.get("endpoint") or configuration.get("base_url")
        if not isinstance(endpoint, str) or not endpoint.strip():
            raise ValueError("Proxy upstream requires an endpoint")
        parsed = parse.urlparse(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("Proxy endpoint must be an absolute credential-free HTTP URL")

    def attach_existing_provider(self, configuration: dict) -> dict:
        self.validate_provider_configuration(configuration)
        endpoint = str(configuration.get("endpoint") or configuration["base_url"]).rstrip("/")
        return {
            "configuration": {**configuration, "endpoint": endpoint},
            "connection_mode": "attached",
            "operational_state": "ready",
        }

    def discover_models(self, provider_instance: dict) -> list[dict]:
        endpoint = str((provider_instance.get("configuration") or {}).get("endpoint", "")).rstrip("/")
        payload = self._request_json("GET", f"{endpoint}/v1/models")
        return [
            {
                "provider_model_reference": item["id"],
                "operator_display_name": item["id"],
                "metadata_sources": {"provider": "proxy-upstream-v1-models"},
                "capability_bindings": ["llm.chat"],
                "operational_state": "ready",
            }
            for item in payload.get("data", [])
            if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"]
        ]

    def validate_bundle(self, bundle_config) -> None:
        if (
            bundle_config.workload_type != "llm_text"
            or bundle_config.launch_mode != "attached_service"
            or not bundle_config.endpoint
        ):
            raise ValueError("Proxy plugin requires an attached llm_text bundle with endpoint")

    def estimate_resources(self, task, bundle_config, runtime_state) -> dict:
        profile = bundle_config.resource_profile
        return {
            "startup_transient": {},
            "runtime_resident": {"cpu": profile.steady_cpu, "ram_mb": profile.steady_ram_mb, "vram_mb": 0},
            "request_active": {"cpu": profile.per_request_cpu, "ram_mb": profile.per_request_ram_mb, "vram_mb": 0},
            "concurrency_limit": 2,
        }

    def build_launch_spec(self, bundle_config) -> dict:
        self.validate_bundle(bundle_config)
        raise ValueError("Proxy plugin does not manage an upstream process")

    def health_check(self, runtime_handle) -> bool:
        try:
            return isinstance(
                self._request_json("GET", f"{runtime_handle.metadata['endpoint'].rstrip('/')}/v1/models").get("data"),
                list,
            )
        except Exception:
            return False

    def invoke(self, task, runtime_handle) -> dict:
        raise RuntimeError("Proxy execution must use the RFC-0054 Runtime Adapter")

    def stop(self, runtime_handle) -> None:
        return None

    def bundle_defaults_from_install(self, *, model_id: str, target_path: str) -> dict:
        return {"model_id": model_id, "launch_mode": "attached_service", "device_affinity": "external"}

    def create_runtime_binding(
        self, *, model_deployment: dict, capability_id: str, capability_version: str, capability_definition_hash: str
    ) -> dict:
        return {
            "model_deployment_id": model_deployment["model_deployment_id"],
            "provider_instance_id": model_deployment["provider_instance_id"],
            "capability_id": capability_id,
            "capability_version": capability_version,
            "capability_definition_hash": capability_definition_hash,
            "adapter_id": "proxy-openai",
            "adapter_version": "proxy-openai.v1",
            "supported_features": ["streaming", "cancellation"],
            "supported_modalities": ["text"],
            "supported_accounting_modes": ["proxy_opaque", "fixed_price", "observable"],
            "compatibility_bundle": {
                "plugin_id": self.plugin_id,
                "provider_type": "proxy-openai",
                "workload_type": "llm_text",
                "model_id": model_deployment["provider_model_reference"],
                "launch_mode": "attached_service",
                "device_affinity": "external",
            },
            "status": "ready",
        }

    def usage_contract(self) -> dict:
        return {
            "supports_exact": False,
            "supports_estimated": False,
            "default_measurement_source": None,
            "fallback_measurement_source": "observable_output",
            "fallback_policy": "fixed_or_observable_only",
            "missing_usage_behavior": "unavailable",
        }

    @staticmethod
    def _request_json(method: str, url: str) -> dict:
        try:
            with request.urlopen(request.Request(url, method=method), timeout=5) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.URLError as exc:
            raise RuntimeError(str(exc)) from exc
