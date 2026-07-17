from aidn_hypervisor.plugins.base import ProviderPlugin


class FakeManagedPlugin(ProviderPlugin):
    plugin_id = "fake-managed"

    def describe(self) -> dict:
        return {
            "plugin_id": self.plugin_id,
            "plugin_version": "0.1.0",
            "display_name": "Fake Managed Provider",
            "publisher": "AiDN Test",
            "package_digest": "sha256:fake-managed-dev",
            "provider_type": "fake",
            "provider_families": ["fake"],
            "plugin_capability_flags": [
                "CAN_ATTACH_EXISTING",
                "CAN_INSTALL_PROVIDER",
                "CAN_DISCOVER_MODELS",
            ],
            "required_permissions": [
                {
                    "permission_id": "network.private",
                    "label": "Private network",
                    "risk_level": "low",
                    "reason": "Connect to a local fake provider endpoint",
                }
            ],
            "trust_status": "CONFORMANCE_TESTED",
            "source_repository": "https://github.com/glinko/AiDN",
            "license": "Apache-2.0",
            "supported_platforms": ["linux", "darwin", "windows"],
            "supported_architectures": ["x86_64", "arm64"],
            "supported_accelerators": ["cpu"],
            "secret_requirements": [
                {
                    "secret_type": "API_KEY",
                    "label": "Optional provider API key handle",
                    "required": False,
                    "allowed_usage": ["provider.connect", "provider.health_check"],
                }
            ],
            "installation_recipes": [
                {
                    "recipe_id": "fake-managed-local",
                    "display_name": "Local Fake Provider",
                    "description": "Attach a deterministic fake provider for local testing",
                    "provider_configuration": {
                        "display_name": "Local Fake",
                        "base_url": "http://127.0.0.1:9999",
                    },
                    "model_configuration": {
                        "provider_model_reference": "fake-model",
                    },
                    "endpoint_defaults": {
                        "capability_id": "llm.chat",
                    },
                }
            ],
            "supported_aidn_capabilities": ["llm.chat"],
            "workload_types": ["llm_text", "speech_to_text"],
            "usage_contract": self.usage_contract(),
        }

    def validate_bundle(self, bundle_config) -> None:
        return None

    def estimate_resources(self, task, bundle_config, runtime_state) -> dict:
        profile = bundle_config.resource_profile
        startup_transient = {}
        runtime_resident = {
            "cpu": profile.steady_cpu,
            "ram_mb": profile.steady_ram_mb,
            "vram_mb": profile.steady_vram_mb,
        }
        if runtime_state is None:
            startup_transient = {
                "cpu": profile.cold_start_cpu,
                "ram_mb": profile.cold_start_ram_mb,
                "vram_mb": profile.cold_start_vram_mb,
            }

        return {
            "startup_transient": startup_transient,
            "runtime_resident": runtime_resident,
            "request_active": {
                "cpu": profile.per_request_cpu,
                "ram_mb": profile.per_request_ram_mb,
                "vram_mb": profile.per_request_vram_mb,
            },
        }

    def build_launch_spec(self, bundle_config) -> dict:
        return {"command": ["python", "-m", "http.server", "0"]}

    def health_check(self, runtime_handle) -> bool:
        return True

    def invoke(self, task, runtime_handle) -> dict:
        return {"ok": True, "task_type": task.task_type}

    def stop(self, runtime_handle) -> None:
        return None

    def attach_provider_schema(self) -> dict:
        return {
            "schema_id": "fake.attach.v1",
            "fields": [
                {"id": "display_name", "type": "text", "required": True},
                {"id": "base_url", "type": "text", "required": True},
            ]
        }

    def install_provider_schema(self) -> dict:
        return {
            "schema_id": "fake.install.v1",
            "fields": [
                {"id": "display_name", "type": "text", "required": True},
                {"id": "base_url", "type": "text", "required": True},
            ],
        }

    def validate_provider_configuration(self, configuration: dict) -> None:
        if not str(configuration.get("base_url", "")).strip():
            raise ValueError("base_url is required")

    def build_installation_plan(self, configuration: dict) -> dict:
        self.validate_provider_configuration(configuration)
        return {
            "plan_id": "plan-fake-managed",
            "plugin_id": self.plugin_id,
            "plan_version": "1.0.0",
            "summary": "Attach or prepare Fake Managed Provider",
            "containers": [],
            "processes": [],
            "model_downloads": [],
            "volumes": [],
            "networks": [{"name": "private-provider", "scope": "local"}],
            "environment": {},
            "resource_limits": {"cpu": "shared"},
            "health_checks": [
                {
                    "type": "http",
                    "url": configuration["base_url"],
                    "timeout_seconds": 5,
                }
            ],
            "required_permissions": self.plugin_manifest()["required_permissions"],
            "secret_references": [],
            "unsupported_actions": [],
        }

    def discover_models(self, provider_instance: dict) -> list[dict]:
        provider_instance_id = provider_instance["provider_instance_id"]
        return [
            {
                "model_deployment_id": f"md-{provider_instance_id}-fake-model",
                "provider_instance_id": provider_instance_id,
                "provider_model_reference": "fake-model",
                "operator_display_name": "Fake Model",
                "declared_model_name": "Fake Model",
                "metadata_sources": {
                    "declared_model_name": "PLUGIN_DISCOVERED",
                    "provider_model_reference": "PLUGIN_DISCOVERED",
                },
                "capability_bindings": ["llm.chat"],
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
                "provider_type": "fake",
                "plugin_id": self.plugin_id,
                "endpoint": None,
            }
        )
        return binding
