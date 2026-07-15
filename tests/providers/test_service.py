import pytest

from aidn_hypervisor.plugins.fake import FakeManagedPlugin
from aidn_hypervisor.plugins.registry import PluginRegistry
from aidn_hypervisor.providers.executor import RecordedProviderInstallationExecutor
from aidn_hypervisor.providers.models import InstallationPlan, ProviderInstallationApproval
from aidn_hypervisor.providers.service import ProviderInventoryService
from aidn_hypervisor.providers.store import InMemoryProviderInventoryStore


def _registry() -> PluginRegistry:
    registry = PluginRegistry()
    registry.register(FakeManagedPlugin())
    return registry


def test_fake_plugin_exposes_attach_schema_and_discovers_models() -> None:
    plugin = FakeManagedPlugin()

    attach_schema = plugin.attach_provider_schema()
    models = plugin.discover_models(
        {
            "provider_instance_id": "pi-fake",
            "display_name": "Local Fake",
            "configuration": {"base_url": "http://127.0.0.1:9999"},
        }
    )

    assert attach_schema["fields"] == [
        {"id": "display_name", "type": "text", "required": True},
        {"id": "base_url", "type": "text", "required": True},
    ]
    assert models[0]["provider_model_reference"] == "fake-model"
    assert models[0]["capability_bindings"] == ["llm.chat"]
    assert models[0]["operational_state"] == "ready"


def test_fake_plugin_discovery_uses_provider_specific_model_deployment_ids() -> None:
    plugin = FakeManagedPlugin()

    first_models = plugin.discover_models(
        {
            "provider_instance_id": "pi-fake-a",
            "display_name": "Local Fake A",
            "configuration": {"base_url": "http://127.0.0.1:9999"},
        }
    )
    second_models = plugin.discover_models(
        {
            "provider_instance_id": "pi-fake-b",
            "display_name": "Local Fake B",
            "configuration": {"base_url": "http://127.0.0.1:9998"},
        }
    )

    assert first_models[0]["model_deployment_id"] != second_models[0]["model_deployment_id"]
    assert first_models[0]["provider_instance_id"] == "pi-fake-a"
    assert second_models[0]["provider_instance_id"] == "pi-fake-b"


def test_base_plugin_attach_existing_provider_passes_configuration_through() -> None:
    plugin = FakeManagedPlugin()

    attached = plugin.attach_existing_provider({"base_url": "http://127.0.0.1:9999"})

    assert attached == {
        "configuration": {"base_url": "http://127.0.0.1:9999"},
        "connection_mode": "attached",
        "operational_state": "ready",
    }


def test_fake_plugin_creates_runtime_binding_projection() -> None:
    plugin = FakeManagedPlugin()

    binding = plugin.create_runtime_binding(
        model_deployment={
            "model_deployment_id": "md-fake",
            "provider_instance_id": "pi-fake",
            "provider_model_reference": "fake-model",
        },
        capability_id="llm.chat",
        capability_version="1.0.0",
        capability_definition_hash="cap-hash",
    )

    assert binding["model_deployment_id"] == "md-fake"
    assert binding["capability_id"] == "llm.chat"
    assert binding["compatibility_bundle"]["plugin_id"] == "fake-managed"
    assert binding["compatibility_bundle"]["provider_type"] == "fake"
    assert binding["compatibility_bundle"]["model_id"] == "fake-model"


def test_provider_inventory_service_attaches_discovers_and_projects_runtime_binding() -> None:
    registry = PluginRegistry()
    registry.register(FakeManagedPlugin())
    service = ProviderInventoryService(
        plugins=registry,
        store=InMemoryProviderInventoryStore(),
    )

    manifests = service.list_plugin_manifests()
    instance = service.attach_provider_instance(
        plugin_id="fake-managed",
        display_name="Local Fake",
        configuration={"base_url": "http://127.0.0.1:9999"},
    )
    models = service.discover_models(instance.provider_instance_id)
    binding = service.create_runtime_binding(
        model_deployment_id=models[0].model_deployment_id,
        capability_id="llm.chat",
        capability_version="1.0.0",
        capability_definition_hash="cap-hash",
    )
    bundle = service.bundle_config_for_runtime_binding(binding.runtime_binding_id)

    assert manifests[0]["plugin_id"] == "fake-managed"
    assert instance.connection_mode == "attached"
    assert instance.configuration["base_url"] == "http://127.0.0.1:9999"
    assert service.store.get_provider_instance(instance.provider_instance_id).display_name == "Local Fake"
    assert models[0].provider_instance_id == instance.provider_instance_id
    assert service.store.get_model_deployment(models[0].model_deployment_id).provider_model_reference == "fake-model"
    assert binding.provider_instance_id == instance.provider_instance_id
    assert service.store.get_runtime_binding(binding.runtime_binding_id).compatibility_bundle_id == binding.compatibility_bundle_id
    assert bundle.bundle_id == binding.compatibility_bundle_id
    assert bundle.plugin_id == "fake-managed"
    assert bundle.provider_type == "fake"
    assert bundle.workload_type == "llm.chat"
    assert bundle.model_id == "fake-model"
    assert bundle.endpoint == "http://127.0.0.1:9999"


def test_provider_inventory_service_validates_configuration_before_attach() -> None:
    class ValidationTrackingPlugin(FakeManagedPlugin):
        plugin_id = "fake-validation-tracking"

        def __init__(self) -> None:
            self.validated_configurations: list[dict] = []

        def validate_provider_configuration(self, configuration: dict) -> None:
            self.validated_configurations.append(dict(configuration))

        def attach_existing_provider(self, configuration: dict) -> dict:
            if not self.validated_configurations:
                raise ValueError("validation not run")
            return {
                "configuration": dict(configuration),
                "connection_mode": "attached",
                "operational_state": "ready",
            }

    plugin = ValidationTrackingPlugin()
    registry = PluginRegistry()
    registry.register(plugin)
    service = ProviderInventoryService(
        plugins=registry,
        store=InMemoryProviderInventoryStore(),
    )

    instance = service.attach_provider_instance(
        plugin_id="fake-validation-tracking",
        display_name="Tracked Fake",
        configuration={"base_url": "http://127.0.0.1:9999"},
    )

    assert instance.plugin_id == "fake-validation-tracking"
    assert plugin.validated_configurations == [{"base_url": "http://127.0.0.1:9999"}]


def test_provider_inventory_service_reuses_runtime_binding_identity_for_same_logical_binding() -> None:
    registry = PluginRegistry()
    registry.register(FakeManagedPlugin())
    service = ProviderInventoryService(
        plugins=registry,
        store=InMemoryProviderInventoryStore(),
    )

    instance = service.attach_provider_instance(
        plugin_id="fake-managed",
        display_name="Local Fake",
        configuration={"base_url": "http://127.0.0.1:9999"},
    )
    model = service.discover_models(instance.provider_instance_id)[0]

    first = service.create_runtime_binding(
        model_deployment_id=model.model_deployment_id,
        capability_id="llm.chat",
        capability_version="1.0.0",
        capability_definition_hash="cap-hash",
    )
    second = service.create_runtime_binding(
        model_deployment_id=model.model_deployment_id,
        capability_id="llm.chat",
        capability_version="1.0.0",
        capability_definition_hash="cap-hash",
    )

    assert first.runtime_binding_id == second.runtime_binding_id
    assert first.compatibility_bundle_id == second.compatibility_bundle_id
    assert [binding.runtime_binding_id for binding in service.store.list_runtime_bindings()] == [
        first.runtime_binding_id
    ]


def test_provider_inventory_service_ignores_plugin_supplied_random_runtime_binding_ids() -> None:
    class RandomIdentityPlugin(FakeManagedPlugin):
        plugin_id = "fake-random-identity"

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
            suffix = uuid4().hex[:12]
            binding["runtime_binding_id"] = f"plugin-rtb-{suffix}"
            binding["compatibility_bundle_id"] = f"plugin-bundle-{suffix}"
            return binding

    from uuid import uuid4

    plugin = RandomIdentityPlugin()
    registry = PluginRegistry()
    registry.register(plugin)
    service = ProviderInventoryService(
        plugins=registry,
        store=InMemoryProviderInventoryStore(),
    )

    instance = service.attach_provider_instance(
        plugin_id="fake-random-identity",
        display_name="Random Fake",
        configuration={"base_url": "http://127.0.0.1:9999"},
    )
    model = service.discover_models(instance.provider_instance_id)[0]

    first = service.create_runtime_binding(
        model_deployment_id=model.model_deployment_id,
        capability_id="llm.chat",
        capability_version="1.0.0",
        capability_definition_hash="cap-hash",
    )
    second = service.create_runtime_binding(
        model_deployment_id=model.model_deployment_id,
        capability_id="llm.chat",
        capability_version="1.0.0",
        capability_definition_hash="cap-hash",
    )
    bundle = service.bundle_config_for_runtime_binding(first.runtime_binding_id)

    assert first.runtime_binding_id == second.runtime_binding_id
    assert first.compatibility_bundle_id == second.compatibility_bundle_id
    assert not first.runtime_binding_id.startswith("plugin-rtb-")
    assert not first.compatibility_bundle_id.startswith("plugin-bundle-")
    assert [binding.runtime_binding_id for binding in service.store.list_runtime_bindings()] == [
        first.runtime_binding_id
    ]
    assert bundle.bundle_id == first.compatibility_bundle_id


def test_provider_inventory_builds_declarative_installation_plan() -> None:
    service = ProviderInventoryService(
        plugins=_registry(),
        store=InMemoryProviderInventoryStore(),
    )

    plan = service.build_installation_plan(
        plugin_id="fake-managed",
        configuration={
            "display_name": "Local Fake",
            "base_url": "http://127.0.0.1:9999",
        },
    )

    assert plan["plugin_id"] == "fake-managed"
    assert plan["unsupported_actions"] == []
    assert plan["health_checks"][0]["url"] == "http://127.0.0.1:9999"


def test_provider_inventory_rejects_non_declarative_installation_plan() -> None:
    class BadPlanPlugin(FakeManagedPlugin):
        plugin_id = "bad-plan"

        def build_installation_plan(self, configuration: dict) -> dict:
            plan = super().build_installation_plan(configuration)
            plan["plugin_id"] = self.plugin_id
            plan["unsupported_actions"] = ["RUN_SHELL_SCRIPT"]
            return plan

    registry = PluginRegistry()
    registry.register(BadPlanPlugin())
    service = ProviderInventoryService(
        plugins=registry,
        store=InMemoryProviderInventoryStore(),
    )

    with pytest.raises(ValueError, match="declarative-only"):
        service.build_installation_plan(
            plugin_id="bad-plan",
            configuration={
                "display_name": "Local Fake",
                "base_url": "http://127.0.0.1:9999",
            },
        )


def test_provider_inventory_rejects_installation_plan_for_attach_only_plugin() -> None:
    class AttachOnlyPlugin(FakeManagedPlugin):
        plugin_id = "attach-only"

        def describe(self) -> dict:
            description = super().describe()
            description["plugin_id"] = self.plugin_id
            description["plugin_capability_flags"] = ["CAN_ATTACH_EXISTING"]
            return description

    registry = PluginRegistry()
    registry.register(AttachOnlyPlugin())
    service = ProviderInventoryService(
        plugins=registry,
        store=InMemoryProviderInventoryStore(),
    )

    with pytest.raises(ValueError, match="does not support managed installation"):
        service.build_installation_plan(
            plugin_id="attach-only",
            configuration={
                "display_name": "Local Fake",
                "base_url": "http://127.0.0.1:9999",
            },
        )


def _installation_configuration() -> dict:
    return {
        "display_name": "Local Fake",
        "base_url": "http://127.0.0.1:9999",
    }


def _installation_plan(*, plugin_id: str = "fake-managed", plan_id: str = "plan-fake-managed") -> InstallationPlan:
    return InstallationPlan(
        plan_id=plan_id,
        plugin_id=plugin_id,
        plan_version="1.0.0",
        summary="Install the fake managed provider",
        containers=[
            {
                "name": "fake-provider",
                "image": "example/fake-provider:latest",
            }
        ],
        processes=[],
        model_downloads=[
            {
                "model": "fake-model",
                "source": "provider-cache",
            }
        ],
        volumes=[
            {
                "name": "fake-model-cache",
                "mount_path": "/models",
            }
        ],
        networks=[],
        environment={"FAKE_PROVIDER_MODE": "managed"},
        resource_limits={"memory": "1Gi"},
        health_checks=[
            {
                "url": "http://127.0.0.1:9999",
                "interval_seconds": 10,
            }
        ],
    )


def _installation_approval(
    *,
    configuration: dict | None = None,
    plugin_id: str = "fake-managed",
    plan_id: str = "plan-fake-managed",
    status: str = "APPROVED",
) -> ProviderInstallationApproval:
    return ProviderInstallationApproval(
        approval_id="approval-fake-managed",
        plugin_id=plugin_id,
        plan_id=plan_id,
        plan_hash="sha256:plan",
        configuration_hash="sha256:configuration",
        configuration=configuration or _installation_configuration(),
        approved_permissions=["container.manage"],
        status=status,
        created_at="2026-07-15T12:00:00Z",
    )


def test_recorded_provider_installation_executor_records_declarative_plan_without_host_mutation() -> None:
    executor = RecordedProviderInstallationExecutor()
    configuration = _installation_configuration()
    plan = _installation_plan()
    approval = _installation_approval(configuration=configuration)

    result = executor.apply(
        approval=approval,
        plan=plan,
        configuration=dict(configuration),
        manifest={
            "plugin_id": "fake-managed",
            "display_name": "Fake Managed Provider",
            "provider_families": ["fake"],
        },
        provider_instance_id="pi-fake-managed",
    )

    assert executor.executor_id == "recorded-declarative-v1"
    assert [step.step_type for step in result.step_results] == [
        "containers",
        "model_downloads",
        "volumes",
        "environment",
        "resource_limits",
        "health_checks",
    ]
    assert all(step.status == "RECORDED" for step in result.step_results)
    assert result.provider_instance == {
        "provider_instance_id": "pi-fake-managed",
        "plugin_id": "fake-managed",
        "provider_family": "fake",
        "display_name": "Local Fake",
        "connection_mode": "managed",
        "configuration": configuration,
        "operational_state": "created",
    }
    assert result.provider_instance["configuration"] is not configuration


def test_recorded_provider_installation_executor_rejects_revoked_approval() -> None:
    executor = RecordedProviderInstallationExecutor()
    configuration = _installation_configuration()

    with pytest.raises(ValueError, match="approved"):
        executor.apply(
            approval=_installation_approval(configuration=configuration, status="REVOKED"),
            plan=_installation_plan(),
            configuration=configuration,
            manifest={"plugin_id": "fake-managed"},
            provider_instance_id="pi-fake-managed",
        )


def test_recorded_provider_installation_executor_rejects_mismatched_configuration() -> None:
    executor = RecordedProviderInstallationExecutor()
    configuration = _installation_configuration()

    with pytest.raises(ValueError, match="configuration"):
        executor.apply(
            approval=_installation_approval(configuration=configuration),
            plan=_installation_plan(),
            configuration={**configuration, "base_url": "http://127.0.0.1:9998"},
            manifest={"plugin_id": "fake-managed"},
            provider_instance_id="pi-fake-managed",
        )


def test_recorded_provider_installation_executor_rejects_plugin_and_plan_mismatches() -> None:
    executor = RecordedProviderInstallationExecutor()
    configuration = _installation_configuration()

    with pytest.raises(ValueError, match="plugin"):
        executor.apply(
            approval=_installation_approval(configuration=configuration, plugin_id="fake-managed"),
            plan=_installation_plan(plugin_id="other-plugin"),
            configuration=configuration,
            manifest={"plugin_id": "fake-managed"},
            provider_instance_id="pi-fake-managed",
        )

    with pytest.raises(ValueError, match="plan"):
        executor.apply(
            approval=_installation_approval(configuration=configuration, plan_id="plan-fake-managed"),
            plan=_installation_plan(plan_id="other-plan"),
            configuration=configuration,
            manifest={"plugin_id": "fake-managed"},
            provider_instance_id="pi-fake-managed",
        )

    with pytest.raises(ValueError, match="manifest"):
        executor.apply(
            approval=_installation_approval(configuration=configuration, plugin_id="fake-managed"),
            plan=_installation_plan(plugin_id="fake-managed"),
            configuration=configuration,
            manifest={"plugin_id": "other-plugin"},
            provider_instance_id="pi-fake-managed",
        )
