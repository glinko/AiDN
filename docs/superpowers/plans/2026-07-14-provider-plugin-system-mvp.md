# Provider Plugin System MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce first-class `ProviderPlugin`, `ProviderInstance`, `ModelDeployment`, and `RuntimeBinding` flows without breaking the current bundle-backed execution path.

**Architecture:** Add a new local `providers` domain/service/store package, extend the plugin contract with attach/discover/runtime-binding metadata, and project `RuntimeBinding` into the existing `BundleConfig` scheduler/process-manager path as a compatibility layer. Update API, endpoint-draft inputs, onboarding, and dashboard payloads so operators follow `plugin -> provider instance -> model deployment -> runtime binding -> endpoint`.

**Tech Stack:** Python, FastAPI, Pydantic, pytest, existing `HypervisorService`, current operator dashboard HTML/JS, existing plugin registry and bundle scheduler.

**Current status:** Provider inventory, runtime-binding compatibility projection, endpoint draft runtime-binding input, plugin-first Providers workspace, provider inventory snapshot/restore, rich Plugin Directory metadata, permission/secret/UI schema/recipe manifest fields, preview Installation Plans, approval/apply job records, schema-driven dashboard forms, Installation Recipe prefill, model discovery from an applied Provider Instance, Runtime Binding creation from a Model Deployment, and Endpoint draft creation from a Runtime Binding are implemented and verified. The latest full test suite for this branch passed with `775 passed, 1 warning`.

**Next phase:** harden the guarded operator approval/apply boundary before real host mutation: permission diffing, secret-handle selection, dry-run diagnostics, rollback semantics, plugin sandbox policy, signed package verification, and eventually sandboxed plan application behind explicit confirmations.

---

## File Structure

### New files

- `src/aidn_hypervisor/providers/__init__.py`
  Exports the local provider-inventory package.
- `src/aidn_hypervisor/providers/models.py`
  Defines plugin manifest, provider-instance, model-deployment, runtime-binding, and request/response models.
- `src/aidn_hypervisor/providers/store.py`
  Provides an in-memory CRUD store for provider instances, model deployments, and runtime bindings.
- `src/aidn_hypervisor/providers/service.py`
  Owns provider-plugin inventory lifecycle and the `RuntimeBinding -> BundleConfig` compatibility projection.
- `tests/providers/test_models.py`
  Covers validation and model defaults.
- `tests/providers/test_store.py`
  Covers CRUD and idempotent replacement semantics.
- `tests/providers/test_service.py`
  Covers attach-existing flow, model discovery, runtime-binding creation, and compatibility projection.

### Modified files

- `src/aidn_hypervisor/plugins/base.py`
  Adds manifest/control-plane defaults and runtime-binding helpers to the plugin contract.
- `src/aidn_hypervisor/plugins/fake.py`
  Implements the new plugin methods for tests and dashboard fixtures.
- `src/aidn_hypervisor/plugins/registry.py`
  Adds listing helpers for plugin-directory style payloads.
- `src/aidn_hypervisor/domain/models.py`
  Keeps legacy `BundleConfig`, but adds thin compatibility request models only if a route still depends on `domain.models`.
- `src/aidn_hypervisor/service.py`
  Composes the new provider service, persists provider inventory state, and exposes provider/runtime-binding facades.
- `src/aidn_hypervisor/api.py`
  Adds operator API routes for plugins, provider instances, model deployments, and runtime bindings.
- `src/aidn_hypervisor/endpoints/models.py`
  Extends endpoint-draft creation to accept `runtime_binding_id` while preserving legacy `bundle_id`/`bundle_hash` fallback.
- `src/aidn_hypervisor/endpoints/api.py`
  Resolves runtime-binding input through hypervisor compatibility projection before calling `EndpointService`.
- `src/aidn_hypervisor/operator_views.py`
  Rebuilds the providers workspace payload around plugins, provider instances, models, and runtime bindings.
- `src/aidn_hypervisor/operator_onboarding.py`
  Updates onboarding milestones from `provider -> bundle` to `provider plugin -> provider instance -> model deployment -> runtime binding`.
- `src/aidn_hypervisor/static/operator_dashboard.html`
  Updates the providers workspace empty state, lists, CTAs, and draft submission flow.
- `tests/plugins/test_registry.py`
  Verifies the richer plugin-directory listing.
- `tests/test_service.py`
  Verifies `HypervisorService` facades and compatibility behavior.
- `tests/test_api.py`
  Verifies new provider/runtime-binding routes and updated dashboard payloads.
- `tests/test_operator_views.py`
  Verifies the provider-first dashboard payload and onboarding recommendations.
- `tests/endpoints/test_service.py`
  Verifies endpoint creation with runtime-binding input.
- `tests/endpoints/test_endpoint_api.py`
  Verifies endpoint API compatibility for `runtime_binding_id`.

## Task 1: Create the Provider Inventory Domain Package

**Files:**
- Create: `src/aidn_hypervisor/providers/__init__.py`
- Create: `src/aidn_hypervisor/providers/models.py`
- Create: `src/aidn_hypervisor/providers/store.py`
- Test: `tests/providers/test_models.py`
- Test: `tests/providers/test_store.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/providers/test_models.py
from pydantic import ValidationError

from aidn_hypervisor.providers.models import (
    ModelDeployment,
    ProviderInstance,
    ProviderPluginManifest,
    RuntimeBinding,
)


def test_provider_plugin_manifest_requires_digest_and_capability_flags() -> None:
    manifest = ProviderPluginManifest(
        plugin_id="aidn.provider.fake",
        plugin_version="0.1.0",
        display_name="Fake Provider",
        publisher="AiDN Test",
        package_digest="sha256:abc123",
        provider_families=["fake"],
        plugin_capability_flags=["CAN_ATTACH_EXISTING", "CAN_DISCOVER_MODELS"],
        required_permissions=[],
        supported_aidn_capabilities=["llm.chat"],
    )

    assert manifest.plugin_id == "aidn.provider.fake"
    assert manifest.plugin_capability_flags == [
        "CAN_ATTACH_EXISTING",
        "CAN_DISCOVER_MODELS",
    ]


def test_runtime_binding_requires_primary_capability() -> None:
    try:
        RuntimeBinding(
            runtime_binding_id="rb-1",
            provider_instance_id="pi-1",
            model_deployment_id="md-1",
            capability_id="",
            capability_version="1.0.0",
            capability_definition_hash="cap-hash",
            plugin_id="aidn.provider.fake",
            compatibility_bundle_id="bundle-rb-1",
            status="ready",
        )
    except ValidationError as exc:
        assert "capability_id" in str(exc)
    else:
        raise AssertionError("expected ValidationError")


def test_model_deployment_tracks_metadata_sources() -> None:
    deployment = ModelDeployment(
        model_deployment_id="md-qwen",
        provider_instance_id="pi-ollama",
        provider_model_reference="qwen3:14b",
        operator_display_name="Qwen 14B",
        declared_model_name="Qwen3 14B",
        metadata_sources={
            "declared_model_name": "OPERATOR_DECLARED",
            "context_limit": "PROVIDER_REPORTED",
        },
        capability_bindings=["llm.chat"],
        operational_state="ready",
    )

    assert deployment.metadata_sources["context_limit"] == "PROVIDER_REPORTED"
```

```python
# tests/providers/test_store.py
from aidn_hypervisor.providers.models import ProviderInstance
from aidn_hypervisor.providers.store import InMemoryProviderInventoryStore


def test_store_round_trips_provider_instances() -> None:
    store = InMemoryProviderInventoryStore()
    instance = ProviderInstance(
        provider_instance_id="pi-1",
        plugin_id="aidn.provider.fake",
        provider_family="fake",
        display_name="Local Fake",
        connection_mode="attached",
        configuration={"base_url": "http://127.0.0.1:1234"},
        operational_state="ready",
    )

    store.save_provider_instance(instance)

    assert store.get_provider_instance("pi-1").display_name == "Local Fake"
    assert len(store.list_provider_instances()) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/providers/test_models.py tests/providers/test_store.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'aidn_hypervisor.providers'`

- [ ] **Step 3: Write the minimal provider domain implementation**

```python
# src/aidn_hypervisor/providers/models.py
from typing import Literal

from pydantic import BaseModel, Field, field_validator


ProviderConnectionMode = Literal["attached", "managed"]
ProviderOperationalState = Literal["created", "ready", "degraded", "error", "removed"]
ModelOperationalState = Literal["discovered", "installing", "ready", "error", "removed"]
RuntimeBindingStatus = Literal["draft", "ready", "degraded", "disabled"]


class ProviderPluginManifest(BaseModel):
    plugin_id: str
    plugin_version: str
    display_name: str
    publisher: str
    package_digest: str
    provider_families: list[str] = Field(default_factory=list)
    plugin_capability_flags: list[str] = Field(default_factory=list)
    required_permissions: list[str] = Field(default_factory=list)
    supported_aidn_capabilities: list[str] = Field(default_factory=list)


class ProviderInstance(BaseModel):
    provider_instance_id: str
    plugin_id: str
    provider_family: str
    display_name: str
    connection_mode: ProviderConnectionMode
    configuration: dict = Field(default_factory=dict)
    operational_state: ProviderOperationalState


class ModelDeployment(BaseModel):
    model_deployment_id: str
    provider_instance_id: str
    provider_model_reference: str
    operator_display_name: str
    declared_model_name: str | None = None
    metadata_sources: dict[str, str] = Field(default_factory=dict)
    capability_bindings: list[str] = Field(default_factory=list)
    operational_state: ModelOperationalState


class RuntimeBinding(BaseModel):
    runtime_binding_id: str
    provider_instance_id: str
    model_deployment_id: str
    capability_id: str
    capability_version: str
    capability_definition_hash: str
    plugin_id: str
    compatibility_bundle_id: str
    status: RuntimeBindingStatus

    @field_validator("capability_id", "capability_version", "capability_definition_hash")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("value must be non-empty")
        return value
```

```python
# src/aidn_hypervisor/providers/store.py
from aidn_hypervisor.providers.models import (
    ModelDeployment,
    ProviderInstance,
    RuntimeBinding,
)


class InMemoryProviderInventoryStore:
    def __init__(self) -> None:
        self._provider_instances: dict[str, ProviderInstance] = {}
        self._model_deployments: dict[str, ModelDeployment] = {}
        self._runtime_bindings: dict[str, RuntimeBinding] = {}

    def save_provider_instance(self, instance: ProviderInstance) -> None:
        self._provider_instances[instance.provider_instance_id] = instance

    def get_provider_instance(self, provider_instance_id: str) -> ProviderInstance:
        return self._provider_instances[provider_instance_id]

    def list_provider_instances(self) -> list[ProviderInstance]:
        return list(self._provider_instances.values())

    def save_model_deployment(self, deployment: ModelDeployment) -> None:
        self._model_deployments[deployment.model_deployment_id] = deployment

    def list_model_deployments(self, provider_instance_id: str | None = None) -> list[ModelDeployment]:
        items = list(self._model_deployments.values())
        if provider_instance_id is None:
            return items
        return [item for item in items if item.provider_instance_id == provider_instance_id]

    def save_runtime_binding(self, binding: RuntimeBinding) -> None:
        self._runtime_bindings[binding.runtime_binding_id] = binding

    def get_runtime_binding(self, runtime_binding_id: str) -> RuntimeBinding:
        return self._runtime_bindings[runtime_binding_id]

    def list_runtime_bindings(self) -> list[RuntimeBinding]:
        return list(self._runtime_bindings.values())
```

```python
# src/aidn_hypervisor/providers/__init__.py
from aidn_hypervisor.providers.models import (
    ModelDeployment,
    ProviderInstance,
    ProviderPluginManifest,
    RuntimeBinding,
)
from aidn_hypervisor.providers.store import InMemoryProviderInventoryStore

__all__ = [
    "ProviderPluginManifest",
    "ProviderInstance",
    "ModelDeployment",
    "RuntimeBinding",
    "InMemoryProviderInventoryStore",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/providers/test_models.py tests/providers/test_store.py -q`

Expected: PASS

- [x] **Step 5: Commit**

```bash
git add src/aidn_hypervisor/providers/__init__.py src/aidn_hypervisor/providers/models.py src/aidn_hypervisor/providers/store.py tests/providers/test_models.py tests/providers/test_store.py
git commit -m "feat: add provider inventory domain models"
```

### Task 2: Extend the Plugin Contract for Provider Lifecycle and Runtime Binding

**Files:**
- Modify: `src/aidn_hypervisor/plugins/base.py`
- Modify: `src/aidn_hypervisor/plugins/fake.py`
- Modify: `src/aidn_hypervisor/plugins/registry.py`
- Test: `tests/plugins/test_registry.py`
- Test: `tests/providers/test_service.py`

- [ ] **Step 1: Write the failing plugin contract tests**

```python
# tests/plugins/test_registry.py
from aidn_hypervisor.plugins.fake import FakeManagedPlugin
from aidn_hypervisor.plugins.registry import PluginRegistry


def test_registry_lists_plugin_directory_manifest() -> None:
    registry = PluginRegistry()
    registry.register(FakeManagedPlugin())

    manifests = registry.list_manifests()

    assert manifests[0]["plugin_id"] == "fake-managed"
    assert "CAN_ATTACH_EXISTING" in manifests[0]["plugin_capability_flags"]
    assert manifests[0]["display_name"] == "Fake Managed Provider"
```

```python
# tests/providers/test_service.py
from aidn_hypervisor.plugins.fake import FakeManagedPlugin


def test_fake_plugin_discovers_models_and_creates_runtime_projection() -> None:
    plugin = FakeManagedPlugin()
    provider_instance = {
        "provider_instance_id": "pi-fake",
        "display_name": "Local Fake",
        "configuration": {"base_url": "http://127.0.0.1:9999"},
    }

    models = plugin.discover_models(provider_instance)
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

    assert models[0]["provider_model_reference"] == "fake-model"
    assert binding["capability_id"] == "llm.chat"
    assert binding["compatibility_bundle"]["plugin_id"] == "fake-managed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/plugins/test_registry.py tests/providers/test_service.py -q`

Expected: FAIL with `AttributeError` for missing `list_manifests`, `discover_models`, or `create_runtime_binding`

- [ ] **Step 3: Add plugin lifecycle defaults and fake-plugin overrides**

```python
# src/aidn_hypervisor/plugins/base.py
from abc import ABC, abstractmethod


class ProviderPlugin(ABC):
    plugin_id: str

    def plugin_manifest(self) -> dict:
        description = self.describe()
        return {
            "plugin_id": description["plugin_id"],
            "plugin_version": "0.1.0",
            "display_name": description.get("display_name", description["plugin_id"]),
            "publisher": "local",
            "package_digest": f"dev:{description['plugin_id']}",
            "provider_families": [description.get("provider_type", description["plugin_id"])],
            "plugin_capability_flags": [],
            "required_permissions": [],
            "supported_aidn_capabilities": description.get("workload_types", []),
        }

    def attach_provider_schema(self) -> dict:
        return {"fields": []}

    def install_provider_schema(self) -> dict:
        return {"fields": []}

    def validate_provider_configuration(self, configuration: dict) -> None:
        return None

    def attach_existing_provider(self, configuration: dict) -> dict:
        return {"configuration": configuration, "operational_state": "ready"}

    def build_installation_plan(self, configuration: dict) -> dict:
        return {"configuration": configuration, "steps": []}

    def discover_models(self, provider_instance: dict) -> list[dict]:
        return []

    def create_runtime_binding(
        self,
        *,
        model_deployment: dict,
        capability_id: str,
        capability_version: str,
        capability_definition_hash: str,
    ) -> dict:
        return {
            "model_deployment_id": model_deployment["model_deployment_id"],
            "capability_id": capability_id,
            "capability_version": capability_version,
            "capability_definition_hash": capability_definition_hash,
            "compatibility_bundle": {
                "plugin_id": self.plugin_id,
                "provider_type": self.plugin_id,
                "model_id": model_deployment["provider_model_reference"],
                "launch_mode": "managed_process",
                "device_affinity": "cpu",
            },
        }
```

```python
# src/aidn_hypervisor/plugins/fake.py
from aidn_hypervisor.plugins.base import ProviderPlugin


class FakeManagedPlugin(ProviderPlugin):
    plugin_id = "fake-managed"

    def describe(self) -> dict:
        return {
            "plugin_id": self.plugin_id,
            "display_name": "Fake Managed Provider",
            "provider_type": "fake",
            "workload_types": ["llm_text", "speech_to_text"],
            "usage_contract": self.usage_contract(),
        }

    def plugin_manifest(self) -> dict:
        manifest = super().plugin_manifest()
        manifest["plugin_capability_flags"] = [
            "CAN_ATTACH_EXISTING",
            "CAN_DISCOVER_MODELS",
            "CAN_STREAM",
            "CAN_REPORT_USAGE",
        ]
        return manifest

    def attach_provider_schema(self) -> dict:
        return {
            "fields": [
                {"id": "display_name", "type": "text", "required": True},
                {"id": "base_url", "type": "text", "required": True},
            ]
        }

    def discover_models(self, provider_instance: dict) -> list[dict]:
        return [
            {
                "provider_model_reference": "fake-model",
                "operator_display_name": "Fake Model",
                "declared_model_name": "Fake Model",
                "metadata_sources": {"declared_model_name": "PLUGIN_DISCOVERED"},
                "capability_bindings": ["llm.chat"],
                "operational_state": "ready",
            }
        ]
```

```python
# src/aidn_hypervisor/plugins/registry.py
class PluginRegistry:
    ...
    def list_manifests(self) -> list[dict]:
        return [plugin.plugin_manifest() for plugin in self.list()]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/plugins/test_registry.py tests/providers/test_service.py -q`

Expected: PASS

- [x] **Step 5: Commit**

```bash
git add src/aidn_hypervisor/plugins/base.py src/aidn_hypervisor/plugins/fake.py src/aidn_hypervisor/plugins/registry.py tests/plugins/test_registry.py tests/providers/test_service.py
git commit -m "feat: extend provider plugin contract for lifecycle metadata"
```

### Task 3: Add the Provider Inventory Service and Operator API

**Files:**
- Create: `src/aidn_hypervisor/providers/service.py`
- Modify: `src/aidn_hypervisor/service.py`
- Modify: `src/aidn_hypervisor/api.py`
- Test: `tests/providers/test_service.py`
- Test: `tests/test_service.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write the failing service and API tests**

```python
# tests/providers/test_service.py
from aidn_hypervisor.plugins.fake import FakeManagedPlugin
from aidn_hypervisor.plugins.registry import PluginRegistry
from aidn_hypervisor.providers.service import ProviderInventoryService
from aidn_hypervisor.providers.store import InMemoryProviderInventoryStore


def test_provider_inventory_service_attaches_provider_discovers_model_and_creates_runtime_binding() -> None:
    registry = PluginRegistry()
    registry.register(FakeManagedPlugin())
    inventory = ProviderInventoryService(
        plugins=registry,
        store=InMemoryProviderInventoryStore(),
    )

    provider = inventory.attach_provider_instance(
        plugin_id="fake-managed",
        display_name="Local Fake",
        configuration={"base_url": "http://127.0.0.1:9999"},
    )
    models = inventory.discover_models(provider.provider_instance_id)
    binding = inventory.create_runtime_binding(
        model_deployment_id=models[0].model_deployment_id,
        capability_id="llm.chat",
        capability_version="1.0.0",
        capability_definition_hash="cap-hash",
    )

    assert provider.plugin_id == "fake-managed"
    assert models[0].provider_instance_id == provider.provider_instance_id
    assert binding.compatibility_bundle_id.startswith("bundle-rtb-")
```

```python
# tests/test_api.py
def test_provider_attach_and_runtime_binding_routes_expose_operator_inventory(client: TestClient) -> None:
    attach = client.post(
        "/operators/provider-instances/attach",
        json={
            "plugin_id": "fake-managed",
            "display_name": "Local Fake",
            "configuration": {"base_url": "http://127.0.0.1:9999"},
        },
    )
    provider_instance_id = attach.json()["provider_instance_id"]

    discovered = client.post(
        f"/operators/provider-instances/{provider_instance_id}/discover-models"
    )
    model_deployment_id = discovered.json()["items"][0]["model_deployment_id"]

    binding = client.post(
        f"/operators/model-deployments/{model_deployment_id}/runtime-bindings",
        json={
            "capability_id": "llm.chat",
            "capability_version": "1.0.0",
            "capability_definition_hash": "cap-hash",
        },
    )

    assert attach.status_code == 200
    assert discovered.status_code == 200
    assert binding.status_code == 200
    assert binding.json()["capability_id"] == "llm.chat"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/providers/test_service.py tests/test_service.py tests/test_api.py -q`

Expected: FAIL with `ImportError` for `ProviderInventoryService` or `404` for the new operator routes

- [ ] **Step 3: Implement provider inventory service, hypervisor facade, and routes**

```python
# src/aidn_hypervisor/providers/service.py
from uuid import uuid4

from aidn_hypervisor.domain.models import BundleConfig, ResourceProfile
from aidn_hypervisor.providers.models import ModelDeployment, ProviderInstance, RuntimeBinding


class ProviderInventoryService:
    def __init__(self, *, plugins, store) -> None:
        self.plugins = plugins
        self.store = store

    def list_plugin_manifests(self) -> list[dict]:
        return self.plugins.list_manifests()

    def attach_provider_instance(self, *, plugin_id: str, display_name: str, configuration: dict) -> ProviderInstance:
        plugin = self.plugins.get(plugin_id)
        plugin.validate_provider_configuration(configuration)
        attached = plugin.attach_existing_provider(configuration)
        instance = ProviderInstance(
            provider_instance_id=f"pi-{uuid4().hex[:12]}",
            plugin_id=plugin_id,
            provider_family=plugin.describe().get("provider_type", plugin_id),
            display_name=display_name,
            connection_mode="attached",
            configuration=attached["configuration"],
            operational_state=attached.get("operational_state", "ready"),
        )
        self.store.save_provider_instance(instance)
        return instance

    def discover_models(self, provider_instance_id: str) -> list[ModelDeployment]:
        instance = self.store.get_provider_instance(provider_instance_id)
        plugin = self.plugins.get(instance.plugin_id)
        discovered = plugin.discover_models(instance.model_dump(mode="json"))
        items: list[ModelDeployment] = []
        for item in discovered:
            deployment = ModelDeployment(
                model_deployment_id=f"md-{uuid4().hex[:12]}",
                provider_instance_id=provider_instance_id,
                provider_model_reference=item["provider_model_reference"],
                operator_display_name=item["operator_display_name"],
                declared_model_name=item.get("declared_model_name"),
                metadata_sources=item.get("metadata_sources", {}),
                capability_bindings=item.get("capability_bindings", []),
                operational_state=item.get("operational_state", "ready"),
            )
            self.store.save_model_deployment(deployment)
            items.append(deployment)
        return items

    def create_runtime_binding(
        self,
        *,
        model_deployment_id: str,
        capability_id: str,
        capability_version: str,
        capability_definition_hash: str,
    ) -> RuntimeBinding:
        deployment = next(
            item
            for item in self.store.list_model_deployments()
            if item.model_deployment_id == model_deployment_id
        )
        instance = self.store.get_provider_instance(deployment.provider_instance_id)
        plugin = self.plugins.get(instance.plugin_id)
        projection = plugin.create_runtime_binding(
            model_deployment=deployment.model_dump(mode="json"),
            capability_id=capability_id,
            capability_version=capability_version,
            capability_definition_hash=capability_definition_hash,
        )
        binding = RuntimeBinding(
            runtime_binding_id=f"rtb-{uuid4().hex[:12]}",
            provider_instance_id=instance.provider_instance_id,
            model_deployment_id=model_deployment_id,
            capability_id=capability_id,
            capability_version=capability_version,
            capability_definition_hash=capability_definition_hash,
            plugin_id=instance.plugin_id,
            compatibility_bundle_id=f"bundle-rtb-{uuid4().hex[:10]}",
            status="ready",
        )
        self.store.save_runtime_binding(binding)
        binding._compatibility_bundle = projection["compatibility_bundle"]
        return binding

    def bundle_config_for_runtime_binding(self, runtime_binding_id: str) -> BundleConfig:
        binding = self.store.get_runtime_binding(runtime_binding_id)
        deployment = next(
            item
            for item in self.store.list_model_deployments()
            if item.model_deployment_id == binding.model_deployment_id
        )
        instance = self.store.get_provider_instance(binding.provider_instance_id)
        plugin = self.plugins.get(instance.plugin_id)
        projection = plugin.create_runtime_binding(
            model_deployment=deployment.model_dump(mode="json"),
            capability_id=binding.capability_id,
            capability_version=binding.capability_version,
            capability_definition_hash=binding.capability_definition_hash,
        )["compatibility_bundle"]
        return BundleConfig(
            bundle_id=binding.compatibility_bundle_id,
            plugin_id=projection["plugin_id"],
            provider_type=projection["provider_type"],
            workload_type=binding.capability_id,
            model_id=projection["model_id"],
            launch_mode=projection["launch_mode"],
            endpoint=instance.configuration.get("base_url"),
            device_affinity=projection.get("device_affinity", "cpu"),
            resource_profile=ResourceProfile(),
            warm_policy="auto",
            priority_class=50,
            max_parallel_requests=1,
            enabled=True,
        )
```

```python
# src/aidn_hypervisor/service.py
from aidn_hypervisor.providers.service import ProviderInventoryService
from aidn_hypervisor.providers.store import InMemoryProviderInventoryStore


class HypervisorService:
    def __init__(..., provider_inventory=None, **kwargs) -> None:
        ...
        self.provider_inventory = provider_inventory or ProviderInventoryService(
            plugins=self.plugins,
            store=InMemoryProviderInventoryStore(),
        )

    def attach_provider_instance(self, *, plugin_id: str, display_name: str, configuration: dict) -> dict:
        instance = self.provider_inventory.attach_provider_instance(
            plugin_id=plugin_id,
            display_name=display_name,
            configuration=configuration,
        )
        self._persist_state()
        return instance.model_dump(mode="json")

    def discover_provider_models(self, provider_instance_id: str) -> list[dict]:
        models = self.provider_inventory.discover_models(provider_instance_id)
        self._persist_state()
        return [item.model_dump(mode="json") for item in models]

    def create_runtime_binding(self, *, model_deployment_id: str, capability_id: str, capability_version: str, capability_definition_hash: str) -> dict:
        binding = self.provider_inventory.create_runtime_binding(
            model_deployment_id=model_deployment_id,
            capability_id=capability_id,
            capability_version=capability_version,
            capability_definition_hash=capability_definition_hash,
        )
        compatibility_bundle = self.provider_inventory.bundle_config_for_runtime_binding(
            binding.runtime_binding_id
        )
        self._replace_bundle(compatibility_bundle)
        self._persist_bundle_config_if_available()
        self._persist_state()
        return binding.model_dump(mode="json")
```

```python
# src/aidn_hypervisor/api.py
@router.get("/operators/provider-plugins")
async def list_provider_plugins() -> dict:
    return {"items": service.provider_inventory.list_plugin_manifests()}


@router.post("/operators/provider-instances/attach")
async def attach_provider_instance(payload: dict) -> dict:
    return service.attach_provider_instance(**payload)


@router.post("/operators/provider-instances/{provider_instance_id}/discover-models")
async def discover_provider_models(provider_instance_id: str) -> dict:
    return {"items": service.discover_provider_models(provider_instance_id)}


@router.post("/operators/model-deployments/{model_deployment_id}/runtime-bindings")
async def create_runtime_binding(model_deployment_id: str, payload: dict) -> dict:
    return service.create_runtime_binding(
        model_deployment_id=model_deployment_id,
        **payload,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/providers/test_service.py tests/test_service.py tests/test_api.py -q`

Expected: PASS

- [x] **Step 5: Commit**

```bash
git add src/aidn_hypervisor/providers/service.py src/aidn_hypervisor/service.py src/aidn_hypervisor/api.py tests/providers/test_service.py tests/test_service.py tests/test_api.py
git commit -m "feat: add provider inventory service and operator API"
```

### Task 4: Make Runtime Binding the Primary Endpoint-Draft Input

**Files:**
- Modify: `src/aidn_hypervisor/endpoints/models.py`
- Modify: `src/aidn_hypervisor/endpoints/api.py`
- Modify: `src/aidn_hypervisor/endpoints/service.py`
- Modify: `src/aidn_hypervisor/service.py`
- Test: `tests/endpoints/test_service.py`
- Test: `tests/endpoints/test_endpoint_api.py`

- [ ] **Step 1: Write the failing endpoint-draft compatibility tests**

```python
# tests/endpoints/test_service.py
from aidn_hypervisor.endpoints.models import CreateEndpointCommand


def test_create_endpoint_accepts_runtime_binding_identity_with_bundle_fallback() -> None:
    cmd = CreateEndpointCommand(
        owner_wallet="wallet-a",
        runtime_binding_id="rtb-1",
        bundle_id="bundle-rtb-1",
        bundle_hash="bundle-hash",
        display_name="Local Qwen",
        model_class="llm.chat",
        capabilities=["llm.chat"],
    )

    assert cmd.runtime_binding_id == "rtb-1"
    assert cmd.bundle_id == "bundle-rtb-1"
```

```python
# tests/endpoints/test_endpoint_api.py
def test_create_endpoint_route_accepts_runtime_binding_id(client: TestClient) -> None:
    response = client.post(
        "/api/v1/endpoints",
        json={
            "owner_wallet": "wallet-a",
            "runtime_binding_id": "rtb-1",
            "bundle_id": "bundle-rtb-1",
            "bundle_hash": "bundle-hash",
            "display_name": "Local Qwen",
            "model_class": "llm.chat",
            "capabilities": ["llm.chat"],
        },
    )

    assert response.status_code == 200
    assert response.json()["endpoint"]["bundle_id"] == "bundle-rtb-1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/endpoints/test_service.py tests/endpoints/test_endpoint_api.py -q`

Expected: FAIL with `ValidationError` for missing/unknown `runtime_binding_id` or route-level rejection

- [ ] **Step 3: Add runtime-binding aware endpoint inputs**

```python
# src/aidn_hypervisor/endpoints/models.py
class CreateEndpointCommand(BaseModel):
    owner_wallet: str
    runtime_binding_id: str | None = None
    bundle_id: str
    bundle_hash: str
    display_name: str
    model_class: str
    capabilities: list[str] = Field(default_factory=list)
    profile: EndpointProfile = Field(default_factory=EndpointProfile)
    runtime: EndpointRuntimeConfig = Field(default_factory=EndpointRuntimeConfig)
    publication: EndpointPublicationPolicy = Field(default_factory=EndpointPublicationPolicy)
    pricing: EndpointPricing = Field(default_factory=EndpointPricing)
    session: EndpointSessionPolicy = Field(default_factory=EndpointSessionPolicy)
    validation: EndpointValidationState = Field(default_factory=EndpointValidationState)
```

```python
# src/aidn_hypervisor/endpoints/api.py
bundle_hash = payload.get("bundle_hash")
bundle_id = payload.get("bundle_id")
runtime_binding_id = payload.get("runtime_binding_id")
if runtime_binding_id:
    compatibility = hypervisor_service.bundle_for_runtime_binding(runtime_binding_id)
    bundle_id = compatibility.bundle_id
    if not bundle_hash:
        bundle_hash = hypervisor_service.bundle_hash_for_bundle(compatibility.bundle_id)

cmd = CreateEndpointCommand(
    **payload,
    runtime_binding_id=runtime_binding_id,
    bundle_id=bundle_id,
    bundle_hash=bundle_hash,
)
```

```python
# src/aidn_hypervisor/service.py
def bundle_for_runtime_binding(self, runtime_binding_id: str) -> BundleConfig:
    return self.provider_inventory.bundle_config_for_runtime_binding(runtime_binding_id)
```

`EndpointService` itself should remain mostly storage-focused; avoid leaking provider logic into it.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/endpoints/test_service.py tests/endpoints/test_endpoint_api.py -q`

Expected: PASS

- [x] **Step 5: Commit**

```bash
git add src/aidn_hypervisor/endpoints/models.py src/aidn_hypervisor/endpoints/api.py src/aidn_hypervisor/endpoints/service.py src/aidn_hypervisor/service.py tests/endpoints/test_service.py tests/endpoints/test_endpoint_api.py
git commit -m "feat: accept runtime bindings in endpoint draft flow"
```

### Task 5: Rebuild the Operator Providers Workflow Around Plugins, Instances, Models, and Runtime Bindings

**Files:**
- Modify: `src/aidn_hypervisor/operator_views.py`
- Modify: `src/aidn_hypervisor/operator_onboarding.py`
- Modify: `src/aidn_hypervisor/static/operator_dashboard.html`
- Modify: `src/aidn_hypervisor/api.py`
- Test: `tests/test_operator_views.py`
- Test: `tests/test_api.py`

- [x] **Step 1: Write the failing provider-workspace and onboarding tests**

```python
# tests/test_operator_views.py
def test_providers_payload_uses_plugin_first_empty_state(service) -> None:
    payload = build_operator_providers_payload(
        service=service,
        endpoint_service=None,
        endpoint_publication_service=None,
        validation_service=None,
    )

    assert payload["summary"]["total_provider_instances"] == 0
    assert payload["empty_state"]["title"] == "No providers installed"
    assert payload["empty_state"]["primary_action"]["action"] == "browse_provider_plugins"


def test_providers_payload_exposes_models_and_runtime_binding_readiness(service) -> None:
    payload = build_operator_providers_payload(
        service=service,
        endpoint_service=None,
        endpoint_publication_service=None,
        validation_service=None,
    )

    instance = payload["provider_instances"][0]
    assert instance["model_count"] >= 1
    assert instance["runtime_binding_ready_count"] >= 1
```

```python
# tests/test_api.py
def test_operator_dashboard_providers_route_returns_plugin_directory_and_provider_inventory(client: TestClient) -> None:
    response = client.get("/operators/dashboard/providers")

    assert response.status_code == 200
    body = response.json()
    assert "plugin_directory" in body
    assert "provider_instances" in body
    assert "empty_state" in body
```

- [x] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_operator_views.py tests/test_api.py -q`

Expected: FAIL with missing keys such as `empty_state`, `plugin_directory`, or `provider_instances`

- [x] **Step 3: Update payload builders, onboarding copy, and dashboard JS**

```python
# src/aidn_hypervisor/operator_views.py
def build_operator_providers_payload(...):
    manifests = service.provider_inventory.list_plugin_manifests()
    provider_instances = service.list_provider_instances()
    model_deployments = service.list_model_deployments()
    runtime_bindings = service.list_runtime_bindings()

    return {
        "owner_wallet": fleet["owner_wallet"],
        "node_identity": fleet["node_identity"],
        "plugin_directory": manifests,
        "provider_instances": provider_instances,
        "model_deployments": model_deployments,
        "runtime_bindings": runtime_bindings,
        "empty_state": {
            "title": "No providers installed",
            "description": "Attach an existing provider or browse provider plugins.",
            "primary_action": {
                "action": "browse_provider_plugins",
                "label": "Browse provider plugins",
                "workspace": "providers",
            },
            "secondary_action": {
                "action": "attach_provider",
                "label": "Add existing provider",
                "workspace": "providers",
            },
        },
        "summary": {
            "total_plugins": len(manifests),
            "total_provider_instances": len(provider_instances),
            "total_model_deployments": len(model_deployments),
            "total_runtime_bindings": len(runtime_bindings),
        },
        "recommended_action": _providers_recommended_action(
            provider_instances=provider_instances,
            model_deployments=model_deployments,
            runtime_bindings=runtime_bindings,
        ),
    }
```

```python
# src/aidn_hypervisor/operator_onboarding.py
PROVIDER_PLUGIN_STEPS = [
    "wallet_ready",
    "attach_provider",
    "add_model",
    "create_runtime_binding",
    "create_endpoint",
]
```

```javascript
// src/aidn_hypervisor/static/operator_dashboard.html
function renderProvidersWorkspace(payload) {
  const hasProviders = (payload.provider_instances || []).length > 0;
  if (!hasProviders) {
    return `
      <section class="empty-state">
        <h2>${payload.empty_state.title}</h2>
        <p>${payload.empty_state.description}</p>
        <button data-action="browse_provider_plugins">${payload.empty_state.primary_action.label}</button>
        <button data-action="attach_provider">${payload.empty_state.secondary_action.label}</button>
      </section>
    `;
  }
  return renderProviderInventory(payload);
}
```

Do not remove the bundles workspace in this slice; leave it visible as a compatibility execution view.

- [x] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_operator_views.py tests/test_api.py -q`

Expected: PASS

- [x] **Step 5: Commit**

```bash
git add src/aidn_hypervisor/operator_views.py src/aidn_hypervisor/operator_onboarding.py src/aidn_hypervisor/static/operator_dashboard.html src/aidn_hypervisor/api.py tests/test_operator_views.py tests/test_api.py
git commit -m "feat: migrate providers workspace to plugin-first workflow"
```

### Task 6: Persist Provider Inventory State and Run Full Verification

**Files:**
- Modify: `src/aidn_hypervisor/service.py`
- Modify: `tests/test_service.py`
- Modify: `tests/test_api.py`

- [x] **Step 1: Write the failing persistence regression tests**

```python
# tests/test_service.py
def test_provider_inventory_survives_state_restore() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
    )
    attached = service.attach_provider_instance(
        plugin_id="fake-managed",
        display_name="Local Fake",
        configuration={"base_url": "http://127.0.0.1:9999"},
    )
    models = service.discover_provider_models(attached["provider_instance_id"])
    binding = service.create_runtime_binding(
        model_deployment_id=models[0]["model_deployment_id"],
        capability_id="llm.chat",
        capability_version="1.0.0",
        capability_definition_hash="cap-hash",
    )

    restored = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        plugins=service.plugins,
        runtimes=ProviderProcessManager(),
    )
    restored.restore_state(service.snapshot_state())

    assert restored.list_provider_instances()[0]["display_name"] == "Local Fake"
    assert restored.list_model_deployments()[0]["provider_instance_id"] == attached["provider_instance_id"]
    assert restored.list_runtime_bindings()[0]["runtime_binding_id"] == binding["runtime_binding_id"]
```

- [x] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_service.py tests/test_api.py -q`

Expected: FAIL because provider inventory is not serialized or restored by the hypervisor state snapshot

- [x] **Step 3: Persist the new inventory and expose list helpers**

```python
# src/aidn_hypervisor/service.py
def snapshot_state(self) -> HypervisorStateSnapshot:
    return HypervisorStateSnapshot(
        provider_instances=self.provider_inventory.list_provider_instances(),
        model_deployments=self.provider_inventory.list_model_deployments(),
        runtime_bindings=self.provider_inventory.list_runtime_bindings(),
        ...
    )


def restore_state(self, snapshot: HypervisorStateSnapshot) -> dict[str, int]:
    self.provider_inventory = ProviderInventoryService(
        plugins=self.plugins,
        store=InMemoryProviderInventoryStore(),
    )
    for instance in snapshot.provider_instances:
        self.provider_inventory.store.save_provider_instance(instance)
    for deployment in snapshot.model_deployments:
        self.provider_inventory.store.save_model_deployment(deployment)
    for binding in snapshot.runtime_bindings:
        self.provider_inventory.store.save_runtime_binding(binding)
```

Restore the same payload in the constructor or state-rehydration path before rebuilding dashboard views.

- [x] **Step 4: Run targeted and full verification**

Run: `python -m pytest tests/providers/test_models.py tests/providers/test_store.py tests/providers/test_service.py tests/plugins/test_registry.py tests/test_service.py tests/test_api.py tests/test_operator_views.py tests/endpoints/test_service.py tests/endpoints/test_endpoint_api.py -q`

Expected: PASS

Run: `python -m pytest -q`

Expected: PASS

- [x] **Step 5: Commit**

```bash
git add src/aidn_hypervisor/service.py tests/test_service.py tests/test_api.py
git commit -m "feat: persist provider inventory and verify provider plugin MVP"
```

## Self-Review

### Spec coverage

- Provider Plugin, Provider Instance, Model Deployment, and Runtime Binding are covered by Tasks 1-3.
- Plugin manifest, capability flags, and attach/discover methods are covered by Task 2.
- API flows for attach-existing, model discovery, and runtime binding are covered by Task 3.
- Runtime Binding as the endpoint-draft prerequisite is covered by Task 4.
- Operator dashboard migration to provider-first workflow is covered by Task 5.
- Persistence and compatibility validation are covered by Task 6.
- Managed-install foundation now includes plan preview, approval/apply records, a controlled non-host-mutating executor, schema-rendered install forms, recipe prefill, and guided handoff through model discovery, Runtime Binding, and Endpoint draft creation.
- Full host-mutating execution remains deferred by design until sandbox, permission-diff, secret-handle, diagnostics, rollback, and signed-package controls are implemented.

### Placeholder scan

- No `TBD`, `TODO`, or “similar to above” placeholders remain.
- Each test and code step includes exact files, commands, and concrete snippets.

### Type consistency

- The plan consistently uses `ProviderPlugin`, `ProviderInstance`, `ModelDeployment`, and `RuntimeBinding`.
- `RuntimeBinding -> BundleConfig` compatibility projection stays inside provider inventory/hypervisor service instead of leaking into endpoint storage.
- Endpoint draft changes keep `bundle_id` and `bundle_hash` as compatibility fields while making `runtime_binding_id` the primary new input.

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-07-14-provider-plugin-system-mvp.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
