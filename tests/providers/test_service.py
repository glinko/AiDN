import pytest

from aidn_hypervisor.plugins.fake import FakeManagedPlugin
from aidn_hypervisor.plugins.registry import PluginRegistry
from aidn_hypervisor.providers.executor import RecordedProviderInstallationExecutor
from aidn_hypervisor.providers.models import (
    InstallationPlan,
    ProviderInstallationApproval,
    ProviderInstallationExecutionResult,
    ProviderInstallationJob,
)
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


def test_provider_inventory_store_saves_installation_approvals_and_jobs() -> None:
    store = InMemoryProviderInventoryStore()
    approval = _installation_approval(
        configuration={
            **_installation_configuration(),
            "runtime": {"endpoint": "local", "retries": 3},
        }
    )
    job = ProviderInstallationJob(
        job_id="job-fake-managed",
        approval_id=approval.approval_id,
        plugin_id=approval.plugin_id,
        plan_id=approval.plan_id,
        plan_hash=approval.plan_hash,
        configuration_hash=approval.configuration_hash,
        status="QUEUED",
        executor_id="recorded-declarative-v1",
        step_results=[
            {
                "step_id": "containers",
                "step_type": "containers",
                "status": "RECORDED",
                "summary": "Recorded container declaration",
                "details": {
                    "container": {
                        "name": "fake-provider",
                        "image": "example/fake-provider:latest",
                    }
                },
            }
        ],
        created_at="2026-07-15T12:01:00Z",
    )
    expected_approval = approval.model_copy(deep=True)
    expected_job = job.model_copy(deep=True)

    assert store.save_installation_approval(approval) is None
    assert store.save_installation_job(job) is None

    approval.configuration["runtime"]["endpoint"] = "mutated"
    approval.approved_permissions.append("host.write")
    job.step_results[0].details["container"]["image"] = "mutated:latest"
    job.step_results[0].status = "FAILED"

    assert store.get_installation_approval(expected_approval.approval_id) == expected_approval
    assert store.list_installation_approvals() == [expected_approval]
    assert store.get_installation_job(expected_job.job_id) == expected_job
    assert store.list_installation_jobs() == [expected_job]

    returned_approval = store.get_installation_approval(expected_approval.approval_id)
    returned_approval.configuration["runtime"]["retries"] = 99
    returned_approval.approved_permissions.append("container.delete")
    listed_approval = store.list_installation_approvals()[0]
    listed_approval.configuration["runtime"]["endpoint"] = "listed-mutated"
    listed_approval.approved_permissions.clear()

    returned_job = store.get_installation_job(expected_job.job_id)
    returned_job.step_results[0].details["container"]["name"] = "mutated-provider"
    returned_job.step_results[0].status = "FAILED"
    listed_job = store.list_installation_jobs()[0]
    listed_job.step_results[0].details["container"]["image"] = "listed-mutated:latest"
    listed_job.step_results[0].status = "SKIPPED"

    assert store.get_installation_approval(expected_approval.approval_id).configuration["runtime"] == {
        "endpoint": "local",
        "retries": 3,
    }
    assert store.list_installation_approvals()[0].approved_permissions == ["container.manage"]
    assert store.get_installation_job(expected_job.job_id).step_results[0].details == {
        "container": {
            "name": "fake-provider",
            "image": "example/fake-provider:latest",
        }
    }
    assert store.list_installation_jobs()[0].step_results[0].status == "RECORDED"


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


def test_provider_inventory_approves_and_applies_installation_plan() -> None:
    service = ProviderInventoryService(
        plugins=_registry(),
        store=InMemoryProviderInventoryStore(),
    )
    configuration = _installation_configuration()

    approval = service.approve_installation_plan(
        plugin_id="fake-managed",
        configuration=configuration,
        operator_note="Approved for local testing",
    )
    configuration["base_url"] = "http://127.0.0.1:9998"
    job = service.apply_installation_approval(approval.approval_id)

    provider = service.store.get_provider_instance(job.provider_instance_id)
    stored_approval = service.list_installation_approvals()[0]

    assert approval.plugin_id == "fake-managed"
    assert approval.plan_id == "plan-fake-managed"
    assert approval.plan_hash.startswith("sha256:")
    assert approval.configuration_hash.startswith("sha256:")
    assert approval.configuration["base_url"] == "http://127.0.0.1:9999"
    assert approval.approved_permissions == ["network.private"]
    assert approval.acknowledged_secret_requirements[0]["requirement_key"] == (
        "API_KEY:Optional provider API key handle"
    )
    assert approval.selected_secret_handles == []
    assert approval.operator_note == "Approved for local testing"
    assert stored_approval == approval
    assert job.status == "SUCCEEDED"
    assert job.approval_id == approval.approval_id
    assert job.provider_instance_id == provider.provider_instance_id
    assert job.step_results
    assert job.completed_at is not None
    assert provider.plugin_id == "fake-managed"
    assert provider.connection_mode == "managed"
    assert provider.operational_state == "created"
    assert provider.configuration["base_url"] == "http://127.0.0.1:9999"
    assert service.list_installation_jobs() == [job]


def test_provider_inventory_apply_rejects_revoked_approval() -> None:
    service = ProviderInventoryService(
        plugins=_registry(),
        store=InMemoryProviderInventoryStore(),
    )
    approval = service.approve_installation_plan(
        plugin_id="fake-managed",
        configuration=_installation_configuration(),
    )
    service.store.save_installation_approval(approval.model_copy(update={"status": "REVOKED"}))

    with pytest.raises(ValueError, match="installation approval is not active"):
        service.apply_installation_approval(approval.approval_id)


def test_provider_inventory_approval_rejects_incomplete_explicit_permission_acknowledgement() -> None:
    service = ProviderInventoryService(
        plugins=_registry(),
        store=InMemoryProviderInventoryStore(),
    )

    with pytest.raises(
        ValueError,
        match="approved permissions must match requested permissions exactly",
    ):
        service.approve_installation_plan(
            plugin_id="fake-managed",
            configuration=_installation_configuration(),
            approved_permissions=[],
        )


def test_provider_inventory_approval_records_selected_secret_handles() -> None:
    service = ProviderInventoryService(
        plugins=_registry(),
        store=InMemoryProviderInventoryStore(),
    )

    approval = service.approve_installation_plan(
        plugin_id="fake-managed",
        configuration=_installation_configuration(),
        approved_permissions=["network.private"],
        selected_secret_handles=[
            {
                "requirement_key": "API_KEY:Optional provider API key handle",
                "secret_handle": "secret://providers/fake-managed/api-key",
            }
        ],
    )

    assert approval.selected_secret_handles[0].secret_handle == (
        "secret://providers/fake-managed/api-key"
    )
    assert approval.selected_secret_handles[0].label == "Optional provider API key handle"


def test_provider_inventory_approval_requires_handles_for_required_secret_requirements() -> None:
    class RequiredSecretPlugin(FakeManagedPlugin):
        plugin_id = "required-secret"

        def describe(self) -> dict:
            description = super().describe()
            description["plugin_id"] = self.plugin_id
            description["secret_requirements"] = [
                {
                    "secret_type": "API_KEY",
                    "label": "Required provider API key handle",
                    "required": True,
                    "allowed_usage": ["provider.connect"],
                }
            ]
            return description

        def build_installation_plan(self, configuration: dict) -> dict:
            plan = super().build_installation_plan(configuration)
            plan["plugin_id"] = self.plugin_id
            return plan

    registry = PluginRegistry()
    registry.register(RequiredSecretPlugin())
    service = ProviderInventoryService(
        plugins=registry,
        store=InMemoryProviderInventoryStore(),
    )

    with pytest.raises(ValueError, match="required secret handles are missing"):
        service.approve_installation_plan(
            plugin_id="required-secret",
            configuration=_installation_configuration(),
            approved_permissions=["network.private"],
        )


def test_provider_inventory_apply_rejects_secret_requirement_drift() -> None:
    class MutableSecretPlugin(FakeManagedPlugin):
        plugin_id = "mutable-secret"

        def __init__(self) -> None:
            self.secret_label = "Optional provider API key handle"

        def describe(self) -> dict:
            description = super().describe()
            description["plugin_id"] = self.plugin_id
            description["secret_requirements"] = [
                {
                    "secret_type": "API_KEY",
                    "label": self.secret_label,
                    "required": False,
                    "allowed_usage": ["provider.connect"],
                }
            ]
            return description

        def build_installation_plan(self, configuration: dict) -> dict:
            plan = super().build_installation_plan(configuration)
            plan["plugin_id"] = self.plugin_id
            return plan

    plugin = MutableSecretPlugin()
    registry = PluginRegistry()
    registry.register(plugin)
    service = ProviderInventoryService(
        plugins=registry,
        store=InMemoryProviderInventoryStore(),
    )
    approval = service.approve_installation_plan(
        plugin_id="mutable-secret",
        configuration=_installation_configuration(),
        approved_permissions=["network.private"],
    )
    plugin.secret_label = "Changed provider API key handle"

    with pytest.raises(
        ValueError,
        match="installation secret requirements changed since approval",
    ):
        service.apply_installation_approval(approval.approval_id)


def test_provider_inventory_apply_rejects_plan_hash_mismatch() -> None:
    class MutablePlanPlugin(FakeManagedPlugin):
        plugin_id = "mutable-plan"

        def __init__(self) -> None:
            self.summary = "Original plan"

        def build_installation_plan(self, configuration: dict) -> dict:
            plan = super().build_installation_plan(configuration)
            plan["plugin_id"] = self.plugin_id
            plan["summary"] = self.summary
            return plan

    plugin = MutablePlanPlugin()
    registry = PluginRegistry()
    registry.register(plugin)
    service = ProviderInventoryService(
        plugins=registry,
        store=InMemoryProviderInventoryStore(),
    )
    approval = service.approve_installation_plan(
        plugin_id="mutable-plan",
        configuration=_installation_configuration(),
    )
    plugin.summary = "Updated plan"

    with pytest.raises(ValueError, match="installation plan hash mismatch"):
        service.apply_installation_approval(approval.approval_id)


def test_provider_inventory_apply_isolates_nested_approval_configuration_from_plan_rebuild() -> None:
    class NestedMutatingPlanPlugin(FakeManagedPlugin):
        plugin_id = "nested-mutating-plan"

        def build_installation_plan(self, configuration: dict) -> dict:
            configuration["runtime"]["endpoint"] = "mutated-by-plan"
            plan = super().build_installation_plan(configuration)
            plan["plugin_id"] = self.plugin_id
            return plan

    registry = PluginRegistry()
    registry.register(NestedMutatingPlanPlugin())
    service = ProviderInventoryService(
        plugins=registry,
        store=InMemoryProviderInventoryStore(),
    )
    configuration = {
        **_installation_configuration(),
        "runtime": {"endpoint": "approved", "retries": 3},
    }

    approval = service.approve_installation_plan(
        plugin_id="nested-mutating-plan",
        configuration=configuration,
    )
    job = service.apply_installation_approval(approval.approval_id)
    provider = service.store.get_provider_instance(job.provider_instance_id)
    stored_approval = service.store.get_installation_approval(approval.approval_id)

    assert job.status == "SUCCEEDED"
    assert approval.configuration["runtime"] == {"endpoint": "approved", "retries": 3}
    assert stored_approval.configuration["runtime"] == {"endpoint": "approved", "retries": 3}
    assert provider.configuration["runtime"] == {"endpoint": "approved", "retries": 3}


def test_provider_inventory_apply_fails_when_executor_returns_mismatched_provider_identity() -> None:
    class MismatchedProviderExecutor:
        executor_id = "mismatched-provider"

        def apply(
            self,
            *,
            approval: ProviderInstallationApproval,
            plan: InstallationPlan,
            configuration: dict,
            manifest: dict,
            provider_instance_id: str,
        ) -> ProviderInstallationExecutionResult:
            return ProviderInstallationExecutionResult(
                provider_instance={
                    "provider_instance_id": f"{provider_instance_id}-other",
                    "plugin_id": approval.plugin_id,
                    "provider_family": "fake",
                    "display_name": "Local Fake",
                    "connection_mode": "managed",
                    "configuration": configuration,
                    "operational_state": "created",
                },
            )

    service = ProviderInventoryService(
        plugins=_registry(),
        store=InMemoryProviderInventoryStore(),
        installation_executor=MismatchedProviderExecutor(),
    )
    approval = service.approve_installation_plan(
        plugin_id="fake-managed",
        configuration=_installation_configuration(),
    )

    job = service.apply_installation_approval(approval.approval_id)

    assert job.status == "FAILED"
    assert job.error_code == "ValueError"
    assert "provider_instance_id" in (job.error_message or "")
    assert service.list_provider_instances() == []


def test_provider_inventory_apply_fails_when_executor_returns_mismatched_plugin() -> None:
    class MismatchedPluginExecutor:
        executor_id = "mismatched-plugin"

        def apply(
            self,
            *,
            approval: ProviderInstallationApproval,
            plan: InstallationPlan,
            configuration: dict,
            manifest: dict,
            provider_instance_id: str,
        ) -> ProviderInstallationExecutionResult:
            return ProviderInstallationExecutionResult(
                provider_instance={
                    "provider_instance_id": provider_instance_id,
                    "plugin_id": "other-plugin",
                    "provider_family": "fake",
                    "display_name": "Local Fake",
                    "connection_mode": "managed",
                    "configuration": configuration,
                    "operational_state": "created",
                },
            )

    service = ProviderInventoryService(
        plugins=_registry(),
        store=InMemoryProviderInventoryStore(),
        installation_executor=MismatchedPluginExecutor(),
    )
    approval = service.approve_installation_plan(
        plugin_id="fake-managed",
        configuration=_installation_configuration(),
    )

    job = service.apply_installation_approval(approval.approval_id)

    assert job.status == "FAILED"
    assert job.error_code == "ValueError"
    assert "plugin_id" in (job.error_message or "")
    assert service.list_provider_instances() == []


def test_provider_inventory_approval_hashes_are_deterministic_for_key_order() -> None:
    service = ProviderInventoryService(
        plugins=_registry(),
        store=InMemoryProviderInventoryStore(),
    )

    first = service.approve_installation_plan(
        plugin_id="fake-managed",
        configuration={
            "display_name": "Local Fake",
            "base_url": "http://127.0.0.1:9999",
        },
    )
    second = service.approve_installation_plan(
        plugin_id="fake-managed",
        configuration={
            "base_url": "http://127.0.0.1:9999",
            "display_name": "Local Fake",
        },
    )

    assert first.configuration_hash == second.configuration_hash
    assert first.plan_hash == second.plan_hash
