# Provider Plugin Directory and Declarative Install Plans Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the provider-plugin foundation with richer directory metadata and declarative installation plans, without executing arbitrary installer scripts.

**Architecture:** Keep provider plugins as signed integration packages that can describe install/attach UI and build declarative installation plans. The Hypervisor stores and exposes those plans as inspectable data; actual host changes remain deferred. Sandboxed installer components are represented only as a future capability/risk tier, not as MVP execution behavior.

**Tech Stack:** Python, Pydantic, FastAPI, pytest, existing `ProviderPlugin`, `ProviderInventoryService`, `PluginRegistry`, and operator dashboard payloads.

---

## File Structure

### Modified files

- `src/aidn_hypervisor/providers/models.py`
  Adds typed plugin directory metadata, UI schemas, permission declarations, secret requirements, installation recipes, installation plan models, and installation plan validation.
- `src/aidn_hypervisor/plugins/base.py`
  Extends `ProviderPlugin.plugin_manifest()` and default install-plan helpers to emit the richer manifest while keeping existing plugins compatible.
- `src/aidn_hypervisor/plugins/fake.py`
  Adds deterministic fake provider directory metadata, install schema, recipe, and declarative installation plan for tests and dashboard fixtures.
- `src/aidn_hypervisor/providers/service.py`
  Adds `build_installation_plan()` and returns typed plan payloads without applying host changes.
- `src/aidn_hypervisor/service.py`
  Adds Hypervisor facade for building installation plans.
- `src/aidn_hypervisor/api.py`
  Adds operator route for plan preview: `POST /operators/provider-plugins/{plugin_id}/installation-plan`.
- `src/aidn_hypervisor/operator_views.py`
  Ensures provider workspace payload exposes trust, permissions, UI schema, recipes, and declarative-install capability in the plugin directory.
- `src/aidn_hypervisor/static/operator_dashboard.html`
  Displays richer plugin-directory metadata and makes clear that install plans are preview-only in the MVP.
- `docs/superpowers/plans/2026-07-14-provider-plugin-system-mvp.md`
  Updates stale status/check boxes after Tasks 5 and 6 and points the next phase at declarative install plans.

### Test files

- `tests/providers/test_models.py`
  Covers manifest metadata and installation plan validation.
- `tests/plugins/test_registry.py`
  Covers richer manifest propagation through the registry.
- `tests/providers/test_service.py`
  Covers plan creation through `ProviderInventoryService`.
- `tests/test_service.py`
  Covers Hypervisor facade plan preview.
- `tests/test_api.py`
  Covers operator API route and dashboard shell text.
- `tests/test_operator_views.py`
  Covers provider workspace plugin-directory payload.

## Task 1: Add Directory Metadata and Installation Plan Models

**Files:**
- Modify: `src/aidn_hypervisor/providers/models.py`
- Test: `tests/providers/test_models.py`

- [ ] **Step 1: Write the failing model tests**

Append these tests to `tests/providers/test_models.py`:

```python
from aidn_hypervisor.providers.models import (
    InstallationPlan,
    InstallationRecipe,
    PluginPermission,
    PluginSecretRequirement,
    PluginTrustStatus,
    PluginUISchema,
)


def test_provider_plugin_manifest_exposes_directory_install_metadata() -> None:
    manifest = ProviderPluginManifest(
        plugin_id="aidn.provider.ollama",
        plugin_version="1.0.0",
        display_name="Ollama Provider",
        publisher="AiDN Community",
        package_digest="sha256:abc123",
        provider_families=["ollama"],
        plugin_capability_flags=["CAN_INSTALL_PROVIDER", "CAN_DISCOVER_MODELS"],
        required_permissions=[
            PluginPermission(
                permission_id="container.manage",
                label="Container management",
                risk_level="medium",
                reason="Run the Ollama provider container",
            )
        ],
        supported_aidn_capabilities=["llm.chat"],
        trust_status="COMMUNITY_REVIEWED",
        source_repository="https://github.com/aidn/provider-ollama",
        supported_platforms=["linux"],
        supported_accelerators=["nvidia"],
        install_ui_schema=PluginUISchema(
            schema_id="ollama.install.v1",
            fields=[
                {
                    "id": "model_storage_path",
                    "type": "directory",
                    "required": True,
                }
            ],
        ),
        secret_requirements=[
            PluginSecretRequirement(
                secret_type="API_KEY",
                label="Optional upstream API key",
                required=False,
                allowed_usage=["provider_api"],
            )
        ],
        installation_recipes=[
            InstallationRecipe(
                recipe_id="ollama-qwen3-8b",
                display_name="Ollama + Qwen3 8B",
                description="Install Ollama and pull qwen3:8b",
                provider_configuration={"deployment_mode": "managed_container"},
                model_configuration={"provider_model_reference": "qwen3:8b"},
                endpoint_defaults={"capability_id": "llm.chat"},
            )
        ],
    )

    assert manifest.trust_status == "COMMUNITY_REVIEWED"
    assert manifest.required_permissions[0].permission_id == "container.manage"
    assert manifest.install_ui_schema.fields[0]["id"] == "model_storage_path"
    assert manifest.secret_requirements[0].secret_type == "API_KEY"
    assert manifest.installation_recipes[0].recipe_id == "ollama-qwen3-8b"


def test_installation_plan_is_declarative_and_rejects_script_execution() -> None:
    try:
        InstallationPlan(
            plan_id="plan-ollama",
            plugin_id="aidn.provider.ollama",
            plan_version="1.0.0",
            summary="Install Ollama",
            containers=[],
            processes=[],
            model_downloads=[],
            volumes=[],
            networks=[],
            environment={},
            resource_limits={},
            health_checks=[],
            required_permissions=[],
            secret_references=[],
            unsupported_actions=["RUN_SHELL_SCRIPT"],
        )
    except ValidationError as exc:
        assert "unsupported_actions" in str(exc)
    else:
        raise AssertionError("expected ValidationError")
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python -m pytest tests/providers/test_models.py -q -k "directory_install_metadata or declarative"
```

Expected: FAIL with import errors for `InstallationPlan`, `InstallationRecipe`, `PluginPermission`, `PluginSecretRequirement`, `PluginTrustStatus`, or `PluginUISchema`.

- [ ] **Step 3: Add minimal model implementation**

Add these models to `src/aidn_hypervisor/providers/models.py` before `ProviderPluginManifest`, then extend `ProviderPluginManifest` with the new fields:

```python
PluginTrustStatus = Literal[
    "UNREVIEWED",
    "COMMUNITY_REVIEWED",
    "CONFORMANCE_TESTED",
    "AIDN_CURATED",
    "SECURITY_WARNING",
    "SECURITY_BLOCKED",
]
PluginPermissionRisk = Literal["low", "medium", "high"]
PluginSecretType = Literal[
    "NONE",
    "API_KEY",
    "BEARER_TOKEN",
    "OAUTH",
    "BASIC_AUTH",
    "CLIENT_CERTIFICATE",
    "CUSTOM_SECRET_SET",
]


class PluginPermission(BaseModel):
    permission_id: str
    label: str
    risk_level: PluginPermissionRisk = "low"
    reason: str

    @field_validator("permission_id", "label", "reason")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        return _require_non_empty(value)


class PluginSecretRequirement(BaseModel):
    secret_type: PluginSecretType
    label: str
    required: bool = False
    allowed_usage: list[str] = Field(default_factory=list)

    @field_validator("label")
    @classmethod
    def _label_not_blank(cls, value: str) -> str:
        return _require_non_empty(value)


class PluginUISchema(BaseModel):
    schema_id: str
    fields: list[dict] = Field(default_factory=list)

    @field_validator("schema_id")
    @classmethod
    def _schema_id_not_blank(cls, value: str) -> str:
        return _require_non_empty(value)


class InstallationRecipe(BaseModel):
    recipe_id: str
    display_name: str
    description: str
    provider_configuration: dict = Field(default_factory=dict)
    model_configuration: dict = Field(default_factory=dict)
    endpoint_defaults: dict = Field(default_factory=dict)

    @field_validator("recipe_id", "display_name", "description")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        return _require_non_empty(value)


class InstallationPlan(BaseModel):
    plan_id: str
    plugin_id: str
    plan_version: str
    summary: str
    containers: list[dict] = Field(default_factory=list)
    processes: list[dict] = Field(default_factory=list)
    model_downloads: list[dict] = Field(default_factory=list)
    volumes: list[dict] = Field(default_factory=list)
    networks: list[dict] = Field(default_factory=list)
    environment: dict[str, str] = Field(default_factory=dict)
    resource_limits: dict = Field(default_factory=dict)
    health_checks: list[dict] = Field(default_factory=list)
    required_permissions: list[PluginPermission] = Field(default_factory=list)
    secret_references: list[dict] = Field(default_factory=list)
    unsupported_actions: list[str] = Field(default_factory=list)

    @field_validator("plan_id", "plugin_id", "plan_version", "summary")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        return _require_non_empty(value)

    @field_validator("unsupported_actions")
    @classmethod
    def _reject_unsupported_actions(cls, value: list[str]) -> list[str]:
        if value:
            raise ValueError("installation plan must be declarative-only")
        return value
```

Extend `ProviderPluginManifest`:

```python
class ProviderPluginManifest(BaseModel):
    plugin_id: str
    plugin_version: str
    display_name: str
    publisher: str
    package_digest: str
    provider_families: list[str] = Field(default_factory=list)
    plugin_capability_flags: list[str] = Field(default_factory=list)
    required_permissions: list[PluginPermission] = Field(default_factory=list)
    supported_aidn_capabilities: list[str] = Field(default_factory=list)
    trust_status: PluginTrustStatus = "UNREVIEWED"
    source_repository: str | None = None
    license: str | None = None
    supported_platforms: list[str] = Field(default_factory=list)
    supported_architectures: list[str] = Field(default_factory=list)
    supported_accelerators: list[str] = Field(default_factory=list)
    attach_ui_schema: PluginUISchema | None = None
    install_ui_schema: PluginUISchema | None = None
    model_ui_schema: PluginUISchema | None = None
    endpoint_defaults_schema: PluginUISchema | None = None
    diagnostics_schema: PluginUISchema | None = None
    secret_requirements: list[PluginSecretRequirement] = Field(default_factory=list)
    installation_recipes: list[InstallationRecipe] = Field(default_factory=list)
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
python -m pytest tests/providers/test_models.py -q -k "directory_install_metadata or declarative"
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/aidn_hypervisor/providers/models.py tests/providers/test_models.py
git commit -m "feat: add provider plugin directory models"
```

## Task 2: Emit Rich Manifests and Declarative Plans from Plugins

**Files:**
- Modify: `src/aidn_hypervisor/plugins/base.py`
- Modify: `src/aidn_hypervisor/plugins/fake.py`
- Test: `tests/plugins/test_registry.py`

- [ ] **Step 1: Write the failing plugin manifest tests**

Append these tests to `tests/plugins/test_registry.py`:

```python
def test_registry_manifest_includes_install_schema_permissions_and_recipes() -> None:
    registry = PluginRegistry()
    registry.register(FakeManagedPlugin())

    manifest = registry.list_manifests()[0]

    assert manifest["trust_status"] == "CONFORMANCE_TESTED"
    assert manifest["required_permissions"][0]["permission_id"] == "network.private"
    assert manifest["attach_ui_schema"]["schema_id"] == "fake.attach.v1"
    assert manifest["install_ui_schema"]["schema_id"] == "fake.install.v1"
    assert manifest["secret_requirements"] == []
    assert manifest["installation_recipes"][0]["recipe_id"] == "fake-managed-local"
    assert "CAN_INSTALL_PROVIDER" in manifest["plugin_capability_flags"]


def test_fake_plugin_builds_declarative_installation_plan() -> None:
    plugin = FakeManagedPlugin()

    plan = plugin.build_installation_plan(
        {
            "display_name": "Local Fake",
            "base_url": "http://127.0.0.1:9999",
        }
    )

    assert plan["plugin_id"] == "fake-managed"
    assert plan["summary"] == "Attach or prepare Fake Managed Provider"
    assert plan["unsupported_actions"] == []
    assert plan["health_checks"][0]["type"] == "http"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python -m pytest tests/plugins/test_registry.py -q -k "install_schema_permissions_and_recipes or declarative_installation_plan"
```

Expected: FAIL because the manifest lacks richer metadata and fake plugin does not return the expected typed plan fields.

- [ ] **Step 3: Extend base plugin manifest extraction**

Update `ProviderPlugin.plugin_manifest()` in `src/aidn_hypervisor/plugins/base.py` so it passes through richer fields from `describe()`:

```python
return ProviderPluginManifest(
    plugin_id=description["plugin_id"],
    plugin_version=description.get("plugin_version", "0.1.0"),
    display_name=description.get("display_name", description["plugin_id"]),
    publisher=description.get("publisher", "local"),
    package_digest=description.get("package_digest", f"dev:{description['plugin_id']}"),
    provider_families=description.get(
        "provider_families",
        [description.get("provider_type", description["plugin_id"])],
    ),
    plugin_capability_flags=description.get("plugin_capability_flags", []),
    required_permissions=description.get("required_permissions", []),
    supported_aidn_capabilities=supported_aidn_capabilities,
    trust_status=description.get("trust_status", "UNREVIEWED"),
    source_repository=description.get("source_repository"),
    license=description.get("license"),
    supported_platforms=description.get("supported_platforms", []),
    supported_architectures=description.get("supported_architectures", []),
    supported_accelerators=description.get("supported_accelerators", []),
    attach_ui_schema=description.get("attach_ui_schema") or self.attach_provider_schema(),
    install_ui_schema=description.get("install_ui_schema") or self.install_provider_schema(),
    model_ui_schema=description.get("model_ui_schema"),
    endpoint_defaults_schema=description.get("endpoint_defaults_schema"),
    diagnostics_schema=description.get("diagnostics_schema"),
    secret_requirements=description.get("secret_requirements", []),
    installation_recipes=description.get("installation_recipes", []),
).model_dump(mode="json")
```

Update the default `build_installation_plan()` to return an `InstallationPlan` JSON payload:

```python
from aidn_hypervisor.providers.models import InstallationPlan, ProviderPluginManifest


def build_installation_plan(self, configuration: dict) -> dict:
    self.validate_provider_configuration(configuration)
    return InstallationPlan(
        plan_id=f"plan-{self.plugin_id}",
        plugin_id=self.plugin_id,
        plan_version="1.0.0",
        summary=f"Prepare {self.plugin_id}",
        required_permissions=self.plugin_manifest().get("required_permissions", []),
    ).model_dump(mode="json")
```

- [ ] **Step 4: Extend fake plugin fixture**

Update `FakeManagedPlugin.describe()`, `attach_provider_schema()`, `install_provider_schema()`, and `build_installation_plan()` in `src/aidn_hypervisor/plugins/fake.py`:

```python
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


def attach_provider_schema(self) -> dict:
    return {
        "schema_id": "fake.attach.v1",
        "fields": [
            {"id": "display_name", "type": "text", "required": True},
            {"id": "base_url", "type": "text", "required": True},
        ],
    }


def install_provider_schema(self) -> dict:
    return {
        "schema_id": "fake.install.v1",
        "fields": [
            {"id": "display_name", "type": "text", "required": True},
            {"id": "base_url", "type": "text", "required": True},
        ],
    }


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
```

- [ ] **Step 5: Run test to verify it passes**

Run:

```bash
python -m pytest tests/plugins/test_registry.py -q -k "install_schema_permissions_and_recipes or declarative_installation_plan"
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/aidn_hypervisor/plugins/base.py src/aidn_hypervisor/plugins/fake.py tests/plugins/test_registry.py
git commit -m "feat: expose provider plugin directory metadata"
```

## Task 3: Add Installation Plan Preview Service and API Route

**Files:**
- Modify: `src/aidn_hypervisor/providers/service.py`
- Modify: `src/aidn_hypervisor/service.py`
- Modify: `src/aidn_hypervisor/api.py`
- Test: `tests/providers/test_service.py`
- Test: `tests/test_service.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write failing service and API tests**

Append to `tests/providers/test_service.py`:

```python
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
```

Append to `tests/test_service.py`:

```python
def test_service_build_provider_installation_plan_preview() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
    )

    plan = service.build_provider_installation_plan(
        plugin_id="fake-managed",
        configuration={
            "display_name": "Local Fake",
            "base_url": "http://127.0.0.1:9999",
        },
    )

    assert plan["plan_id"] == "plan-fake-managed"
    assert plan["plugin_id"] == "fake-managed"
```

Append to `tests/test_api.py`:

```python
def test_provider_plugin_installation_plan_preview_route() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.post(
        "/operators/provider-plugins/fake-managed/installation-plan",
        json={
            "configuration": {
                "display_name": "Local Fake",
                "base_url": "http://127.0.0.1:9999",
            }
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["plugin_id"] == "fake-managed"
    assert body["unsupported_actions"] == []
    assert body["health_checks"][0]["type"] == "http"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python -m pytest tests/providers/test_service.py tests/test_service.py tests/test_api.py -q -k "installation_plan"
```

Expected: FAIL because `build_installation_plan`, `build_provider_installation_plan`, and the API route are missing.

- [ ] **Step 3: Implement service facades**

Add to `ProviderInventoryService` in `src/aidn_hypervisor/providers/service.py`:

```python
def build_installation_plan(self, *, plugin_id: str, configuration: dict) -> dict:
    plugin = self._get_plugin(plugin_id)
    return dict(plugin.build_installation_plan(dict(configuration)))
```

Add to `HypervisorService` in `src/aidn_hypervisor/service.py` near provider inventory methods:

```python
def build_provider_installation_plan(
    self,
    *,
    plugin_id: str,
    configuration: dict,
) -> dict:
    return self.provider_inventory.build_installation_plan(
        plugin_id=plugin_id,
        configuration=configuration,
    )
```

- [ ] **Step 4: Implement API request model and route**

In `src/aidn_hypervisor/api.py`, add a local request model near other operator request models:

```python
class BuildProviderInstallationPlanRequest(BaseModel):
    configuration: dict = Field(default_factory=dict)
```

Add route near `/operators/provider-plugins`:

```python
@router.post("/operators/provider-plugins/{plugin_id}/installation-plan")
async def build_provider_installation_plan(
    plugin_id: str,
    payload: BuildProviderInstallationPlanRequest,
) -> dict:
    try:
        return service.build_provider_installation_plan(
            plugin_id=plugin_id,
            configuration=payload.configuration,
        )
    except KeyError as error:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown plugin: {error.args[0]}",
        ) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
```

- [ ] **Step 5: Run tests to verify they pass**

Run:

```bash
python -m pytest tests/providers/test_service.py tests/test_service.py tests/test_api.py -q -k "installation_plan"
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/aidn_hypervisor/providers/service.py src/aidn_hypervisor/service.py src/aidn_hypervisor/api.py tests/providers/test_service.py tests/test_service.py tests/test_api.py
git commit -m "feat: preview provider installation plans"
```

## Task 4: Surface Rich Plugin Directory Metadata in Operator Views

**Files:**
- Modify: `src/aidn_hypervisor/operator_views.py`
- Modify: `src/aidn_hypervisor/static/operator_dashboard.html`
- Test: `tests/test_operator_views.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write failing operator view tests**

Append to `tests/test_operator_views.py`:

```python
def test_providers_payload_exposes_plugin_directory_install_metadata() -> None:
    service = _empty_service()
    service.plugins.register(FakeManagedPlugin())

    payload = build_operator_providers_payload(service=service)
    plugin = payload["plugin_directory"][0]

    assert plugin["trust_status"] == "CONFORMANCE_TESTED"
    assert plugin["required_permissions"][0]["permission_id"] == "network.private"
    assert plugin["install_ui_schema"]["schema_id"] == "fake.install.v1"
    assert plugin["installation_recipes"][0]["recipe_id"] == "fake-managed-local"
    assert payload["summary"]["installable_plugin_count"] == 1
```

Extend `test_operator_dashboard_shell_route_exposes_provider_attach_and_reload_controls` in `tests/test_api.py` with:

```python
assert "Plugin directory" in response.text
assert "Trust" in response.text
assert "Install plan preview" in response.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python -m pytest tests/test_operator_views.py tests/test_api.py -q -k "install_metadata or provider_attach_and_reload_controls"
```

Expected: FAIL because `installable_plugin_count` and dashboard copy are missing.

- [ ] **Step 3: Add summary counts to provider payload**

In `build_operator_providers_payload()` in `src/aidn_hypervisor/operator_views.py`, add:

```python
installable_plugin_count = sum(
    1
    for manifest in plugin_directory
    if "CAN_INSTALL_PROVIDER" in manifest.get("plugin_capability_flags", [])
)
```

Add to the returned `summary`:

```python
"installable_plugin_count": installable_plugin_count,
```

- [ ] **Step 4: Update dashboard plugin directory table**

In `renderProvidersWorkspace()` in `src/aidn_hypervisor/static/operator_dashboard.html`, update the plugin directory table head to include trust and permissions:

```javascript
<div>Plugin</div>
<div>Trust</div>
<div>Capabilities</div>
<div>Permissions</div>
<div>Install plan preview</div>
```

Update the plugin row body to include:

```javascript
<div><span class="chip ${provider.trust_status === "CONFORMANCE_TESTED" ? "good" : ""}">${provider.trust_status || "UNREVIEWED"}</span></div>
<div class="row-meta">${(provider.supported_aidn_capabilities || provider.workload_types || []).join(", ") || "-"}</div>
<div class="row-meta">${(provider.required_permissions || []).map((permission) => permission.label || permission.permission_id).join(", ") || "No elevated permissions"}</div>
<div class="row-meta">${provider.install_ui_schema ? "Declarative preview available" : "Attach only"}</div>
```

Keep the existing inspect/select action button in the final column if the table already has one. The exact row can contain both the preview text and existing action button if preserving the column count is simpler.

- [ ] **Step 5: Run tests to verify they pass**

Run:

```bash
python -m pytest tests/test_operator_views.py tests/test_api.py -q -k "install_metadata or provider_attach_and_reload_controls"
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/aidn_hypervisor/operator_views.py src/aidn_hypervisor/static/operator_dashboard.html tests/test_operator_views.py tests/test_api.py
git commit -m "feat: surface provider plugin directory metadata"
```

## Task 5: Roadmap Cleanup and Full Verification

**Files:**
- Modify: `docs/superpowers/plans/2026-07-14-provider-plugin-system-mvp.md`
- Modify: `docs/superpowers/plans/2026-07-15-provider-plugin-directory-install-plan.md`

- [ ] **Step 1: Update provider MVP plan status**

In `docs/superpowers/plans/2026-07-14-provider-plugin-system-mvp.md`, update top status:

```markdown
**Current status:** Provider inventory, runtime-binding compatibility projection, endpoint draft runtime-binding input, plugin-first Providers workspace, and provider inventory snapshot/restore are implemented and verified. The full test suite passed with `740 passed, 1 warning` before starting the declarative install-plan slice.

**Next phase:** deepen the Plugin Directory foundation with richer manifests, declarative UI schemas, permission and secret metadata, installation recipes, and preview-only declarative Installation Plans. Sandboxed installer execution remains deferred.
```

Mark stale commit checkboxes for Tasks 3, 4, 5, and 6 as checked only when the corresponding commits are already present in `git log`.

- [ ] **Step 2: Run focused and full verification**

Run:

```bash
python -m pytest tests/providers/test_models.py tests/plugins/test_registry.py tests/providers/test_service.py tests/test_service.py tests/test_api.py tests/test_operator_views.py -q
```

Expected: PASS.

Run:

```bash
python -m pytest -q
```

Expected: PASS.

Run:

```bash
git diff --check
```

Expected: exit 0.

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/plans/2026-07-14-provider-plugin-system-mvp.md docs/superpowers/plans/2026-07-15-provider-plugin-directory-install-plan.md
git commit -m "docs: update provider plugin roadmap status"
```

## Self-Review

### Spec coverage

- Declarative-only managed install is covered by Tasks 1-3.
- Rich Plugin Directory manifest metadata is covered by Tasks 1, 2, and 4.
- Secret requirements and permission declarations are modeled in Task 1 and surfaced through plugin manifests in Task 2.
- Installation recipes are modeled in Task 1, emitted in Task 2, and surfaced in Task 4.
- Sandboxed installer execution is explicitly excluded from implementation and remains represented only as metadata/risk-tier language in the design spec.

### Placeholder scan

- No `TBD`, `TODO`, or “similar to above” placeholders are used.
- All commands include concrete paths and expected results.
- Code steps name exact files and functions.

### Type consistency

- `ProviderPluginManifest.required_permissions` uses `PluginPermission`.
- `ProviderPluginManifest.secret_requirements` uses `PluginSecretRequirement`.
- `ProviderPluginManifest.installation_recipes` uses `InstallationRecipe`.
- `ProviderInventoryService.build_installation_plan()` delegates to `ProviderPlugin.build_installation_plan()`.
- The API route returns the declarative `InstallationPlan` payload directly and does not apply host changes.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-15-provider-plugin-directory-install-plan.md`. Two execution options:

**1. Subagent-Driven (recommended)** - Dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
