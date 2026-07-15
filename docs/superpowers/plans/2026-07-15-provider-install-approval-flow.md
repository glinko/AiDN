# Provider Install Approval Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add durable local approval records for provider installation plan previews without applying host changes.

**Architecture:** Keep installation plans preview-only and introduce a local `ProviderInstallationApproval` artifact that binds operator approval to the exact plugin, configuration hash, and plan hash. The approval is stored in provider inventory, included in `HypervisorStateSnapshot`, exposed through operator APIs, and surfaced in the Providers workspace as "approved, not applied." No task in this plan executes installer code, starts containers, downloads models, or mutates host resources.

**Tech Stack:** Python 3.13, FastAPI, Pydantic v2, pytest, in-memory provider inventory store, static operator dashboard HTML/JS.

---

## File Structure

- `src/aidn_hypervisor/providers/models.py`: adds the approval status literal and `ProviderInstallationApproval` Pydantic model.
- `src/aidn_hypervisor/providers/store.py`: persists approval records in the in-memory provider inventory store.
- `src/aidn_hypervisor/providers/service.py`: computes canonical hashes, rebuilds/validates installation plans, creates approvals, and lists approvals.
- `src/aidn_hypervisor/state.py`: includes approval records in durable hypervisor snapshots.
- `src/aidn_hypervisor/service.py`: adds Hypervisor facade methods and snapshot/restore wiring.
- `src/aidn_hypervisor/api.py`: adds approval create/list routes and request validation.
- `src/aidn_hypervisor/operator_views.py`: includes approval summaries in the Providers workspace payload.
- `src/aidn_hypervisor/static/operator_dashboard.html`: displays approvals as local operator decisions and keeps install action preview-only.
- `tests/providers/test_models.py`: verifies approval model validation.
- `tests/providers/test_service.py`: verifies hashing, approval creation, listing, and rejection paths.
- `tests/test_service.py`: verifies Hypervisor facade and snapshot/restore.
- `tests/test_api.py`: verifies HTTP routes and dashboard shell copy.
- `tests/test_operator_views.py`: verifies Providers workspace payload includes approval status.

## Safety Boundaries

- Do not add any install/apply/execute route.
- Do not call Docker, shell installers, package managers, GitHub downloaders, or provider-native APIs.
- Do not persist secret values; persist only acknowledged secret requirement summaries from the manifest.
- Do not treat approval as a provider instance, model deployment, runtime binding, endpoint publication, Registry object, Ledger operation, or Verification result.
- Future apply flow must require the same `approval_id` and matching `plan_hash`, but this plan only creates the record and surfaces the binding.

### Task 1: Approval Model

**Files:**
- Modify: `src/aidn_hypervisor/providers/models.py`
- Test: `tests/providers/test_models.py`

- [ ] **Step 1: Write the failing approval model test**

Append this test to `tests/providers/test_models.py`:

```python
from pydantic import ValidationError

from aidn_hypervisor.providers.models import ProviderInstallationApproval


def test_provider_installation_approval_captures_plan_binding_without_secrets() -> None:
    approval = ProviderInstallationApproval(
        approval_id="pia-123",
        plugin_id="fake-managed",
        plan_id="plan-fake-managed-local-fake",
        plan_hash="sha256:" + "a" * 64,
        configuration_hash="sha256:" + "b" * 64,
        approved_permissions=["network.private"],
        acknowledged_secret_requirements=[
            {
                "secret_type": "API_KEY",
                "label": "Provider API key",
                "required": False,
                "allowed_usage": ["provider_api"],
            }
        ],
        operator_note="Approved for local lab host",
        status="APPROVED",
        created_at="2026-07-15T12:00:00+00:00",
    )

    assert approval.approval_id == "pia-123"
    assert approval.status == "APPROVED"
    assert approval.approved_permissions == ["network.private"]
    assert approval.acknowledged_secret_requirements[0]["secret_type"] == "API_KEY"
    assert "secret_value" not in approval.model_dump(mode="json")


def test_provider_installation_approval_rejects_unknown_status() -> None:
    with pytest.raises(ValidationError):
        ProviderInstallationApproval(
            approval_id="pia-123",
            plugin_id="fake-managed",
            plan_id="plan-fake-managed-local-fake",
            plan_hash="sha256:" + "a" * 64,
            configuration_hash="sha256:" + "b" * 64,
            status="INSTALLED",
            created_at="2026-07-15T12:00:00+00:00",
        )
```

If `pytest` is not already imported in this file, add:

```python
import pytest
```

- [ ] **Step 2: Run the model tests and confirm failure**

Run:

```powershell
python -m pytest tests/providers/test_models.py -q
```

Expected: fails with `ImportError` or `cannot import name 'ProviderInstallationApproval'`.

- [ ] **Step 3: Add the approval model**

In `src/aidn_hypervisor/providers/models.py`, add `Literal` to the typing imports if it is not already present:

```python
from typing import Literal
```

Add this near the other provider status/type declarations:

```python
ProviderInstallationApprovalStatus = Literal["APPROVED", "REVOKED"]
```

Add this model after `InstallationPlan` and before `ProviderPluginManifest`:

```python
class ProviderInstallationApproval(BaseModel):
    approval_id: str
    plugin_id: str
    plan_id: str
    plan_hash: str
    configuration_hash: str
    approved_permissions: list[str] = Field(default_factory=list)
    acknowledged_secret_requirements: list[dict] = Field(default_factory=list)
    operator_note: str | None = None
    status: ProviderInstallationApprovalStatus = "APPROVED"
    created_at: str

    @field_validator("approval_id", "plugin_id", "plan_id", "plan_hash", "configuration_hash", "created_at")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return _require_non_empty(value)
```

- [ ] **Step 4: Run the model tests and confirm pass**

Run:

```powershell
python -m pytest tests/providers/test_models.py -q
```

Expected: all tests in `tests/providers/test_models.py` pass.

- [ ] **Step 5: Commit**

Run:

```powershell
git add src/aidn_hypervisor/providers/models.py tests/providers/test_models.py
git commit -m "feat: add provider install approval model"
```

### Task 2: Approval Store

**Files:**
- Modify: `src/aidn_hypervisor/providers/store.py`
- Test: `tests/providers/test_service.py`

- [ ] **Step 1: Write the failing store test**

Append this test to `tests/providers/test_service.py`:

```python
from aidn_hypervisor.providers.models import ProviderInstallationApproval


def test_provider_inventory_store_saves_and_lists_installation_approvals() -> None:
    store = InMemoryProviderInventoryStore()
    approval = ProviderInstallationApproval(
        approval_id="pia-123",
        plugin_id="fake-managed",
        plan_id="plan-fake-managed-local-fake",
        plan_hash="sha256:" + "a" * 64,
        configuration_hash="sha256:" + "b" * 64,
        approved_permissions=["network.private"],
        acknowledged_secret_requirements=[],
        status="APPROVED",
        created_at="2026-07-15T12:00:00+00:00",
    )

    store.save_installation_approval(approval)

    assert store.get_installation_approval("pia-123").plugin_id == "fake-managed"
    assert store.list_installation_approvals() == [approval]
```

- [ ] **Step 2: Run the provider service tests and confirm failure**

Run:

```powershell
python -m pytest tests/providers/test_service.py::test_provider_inventory_store_saves_and_lists_installation_approvals -q
```

Expected: fails with `AttributeError: 'InMemoryProviderInventoryStore' object has no attribute 'save_installation_approval'`.

- [ ] **Step 3: Implement store methods**

In `src/aidn_hypervisor/providers/store.py`, update imports:

```python
from aidn_hypervisor.providers.models import (
    ModelDeployment,
    ProviderInstallationApproval,
    ProviderInstance,
    RuntimeBinding,
)
```

In `InMemoryProviderInventoryStore.__init__`, add:

```python
self._installation_approvals: dict[str, ProviderInstallationApproval] = {}
```

Add these methods after the runtime binding methods:

```python
def save_installation_approval(
    self, approval: ProviderInstallationApproval
) -> ProviderInstallationApproval:
    self._installation_approvals[approval.approval_id] = approval.model_copy(deep=True)
    return approval

def get_installation_approval(self, approval_id: str) -> ProviderInstallationApproval:
    return self._installation_approvals[approval_id].model_copy(deep=True)

def list_installation_approvals(self) -> list[ProviderInstallationApproval]:
    return [
        approval.model_copy(deep=True)
        for approval in self._installation_approvals.values()
    ]
```

- [ ] **Step 4: Run the focused store test**

Run:

```powershell
python -m pytest tests/providers/test_service.py::test_provider_inventory_store_saves_and_lists_installation_approvals -q
```

Expected: pass.

- [ ] **Step 5: Commit**

Run:

```powershell
git add src/aidn_hypervisor/providers/store.py tests/providers/test_service.py
git commit -m "feat: persist provider install approvals"
```

### Task 3: Provider Inventory Approval Service

**Files:**
- Modify: `src/aidn_hypervisor/providers/service.py`
- Test: `tests/providers/test_service.py`

- [ ] **Step 1: Write failing approval service tests**

Append these tests to `tests/providers/test_service.py`:

```python
def test_provider_inventory_approves_installation_plan_with_hash_binding() -> None:
    service = ProviderInventoryService(
        plugins=_registry(),
        store=InMemoryProviderInventoryStore(),
    )

    approval = service.approve_installation_plan(
        plugin_id="fake-managed",
        configuration={
            "display_name": "Local Fake",
            "base_url": "http://127.0.0.1:9999",
        },
        operator_note="Operator reviewed plan.",
    )

    assert approval.approval_id.startswith("pia-")
    assert approval.plugin_id == "fake-managed"
    assert approval.plan_id.startswith("plan-")
    assert approval.plan_hash.startswith("sha256:")
    assert approval.configuration_hash.startswith("sha256:")
    assert approval.status == "APPROVED"
    assert approval.operator_note == "Operator reviewed plan."
    assert service.store.get_installation_approval(approval.approval_id) == approval
    assert service.list_installation_approvals() == [approval]


def test_provider_inventory_approval_hashes_are_deterministic_for_same_plan() -> None:
    service = ProviderInventoryService(
        plugins=_registry(),
        store=InMemoryProviderInventoryStore(),
    )

    first = service.approve_installation_plan(
        plugin_id="fake-managed",
        configuration={"base_url": "http://127.0.0.1:9999", "display_name": "Local Fake"},
    )
    second = service.approve_installation_plan(
        plugin_id="fake-managed",
        configuration={"display_name": "Local Fake", "base_url": "http://127.0.0.1:9999"},
    )

    assert first.approval_id != second.approval_id
    assert first.plan_hash == second.plan_hash
    assert first.configuration_hash == second.configuration_hash


def test_provider_inventory_approval_rejects_attach_only_plugin() -> None:
    class AttachOnlyPlugin(FakeManagedPlugin):
        plugin_id = "attach-only-approval"

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
        service.approve_installation_plan(
            plugin_id="attach-only-approval",
            configuration={"display_name": "Local Fake", "base_url": "http://127.0.0.1:9999"},
        )
```

- [ ] **Step 2: Run the approval service tests and confirm failure**

Run:

```powershell
python -m pytest tests/providers/test_service.py::test_provider_inventory_approves_installation_plan_with_hash_binding tests/providers/test_service.py::test_provider_inventory_approval_hashes_are_deterministic_for_same_plan tests/providers/test_service.py::test_provider_inventory_approval_rejects_attach_only_plugin -q
```

Expected: fails with `AttributeError: 'ProviderInventoryService' object has no attribute 'approve_installation_plan'`.

- [ ] **Step 3: Add canonical hash helpers and service methods**

In `src/aidn_hypervisor/providers/service.py`, add imports:

```python
import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4
```

Add `ProviderInstallationApproval` to the models import.

Add these helpers near the top of the file:

```python
def _canonical_hash(value: dict) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return f"sha256:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
```

Add these methods to `ProviderInventoryService` after `build_installation_plan`:

```python
def approve_installation_plan(
    self,
    *,
    plugin_id: str,
    configuration: dict,
    operator_note: str | None = None,
) -> ProviderInstallationApproval:
    plugin = self._get_plugin(plugin_id)
    manifest = ProviderPluginManifest.model_validate(plugin.plugin_manifest())
    plan = InstallationPlan.model_validate(
        self.build_installation_plan(plugin_id=plugin_id, configuration=configuration)
    )
    approval = ProviderInstallationApproval(
        approval_id=f"pia-{uuid4().hex[:12]}",
        plugin_id=plugin_id,
        plan_id=plan.plan_id,
        plan_hash=_canonical_hash(plan.model_dump(mode="json")),
        configuration_hash=_canonical_hash(dict(configuration)),
        approved_permissions=[
            permission.permission_id for permission in manifest.required_permissions
        ],
        acknowledged_secret_requirements=[
            requirement.model_dump(mode="json")
            for requirement in manifest.secret_requirements
        ],
        operator_note=operator_note,
        status="APPROVED",
        created_at=_now_iso(),
    )
    self.store.save_installation_approval(approval)
    return approval

def list_installation_approvals(self) -> list[ProviderInstallationApproval]:
    return self.store.list_installation_approvals()
```

- [ ] **Step 4: Run provider service tests**

Run:

```powershell
python -m pytest tests/providers/test_service.py -q
```

Expected: all provider service tests pass.

- [ ] **Step 5: Commit**

Run:

```powershell
git add src/aidn_hypervisor/providers/service.py tests/providers/test_service.py
git commit -m "feat: approve provider install plans locally"
```

### Task 4: Hypervisor Facade and Snapshot Persistence

**Files:**
- Modify: `src/aidn_hypervisor/state.py`
- Modify: `src/aidn_hypervisor/service.py`
- Test: `tests/test_service.py`

- [ ] **Step 1: Write failing Hypervisor snapshot test**

Append this test to `tests/test_service.py`:

```python
def test_provider_installation_approvals_survive_snapshot_restore() -> None:
    service = _service()
    approval = service.approve_provider_installation_plan(
        plugin_id="fake-managed",
        configuration={
            "display_name": "Local Fake",
            "base_url": "http://127.0.0.1:9999",
        },
        operator_note="Reviewed before host changes.",
    )

    snapshot = service.snapshot_state()
    restored = _service()
    restored.restore_state(snapshot)

    restored_approvals = restored.list_provider_installation_approvals()
    assert [item["approval_id"] for item in restored_approvals] == [
        approval["approval_id"]
    ]
    assert restored_approvals[0]["plan_hash"] == approval["plan_hash"]
    assert restored_approvals[0]["operator_note"] == "Reviewed before host changes."
```

- [ ] **Step 2: Run the focused Hypervisor test and confirm failure**

Run:

```powershell
python -m pytest tests/test_service.py::test_provider_installation_approvals_survive_snapshot_restore -q
```

Expected: fails because `approve_provider_installation_plan` is missing.

- [ ] **Step 3: Add snapshot model field**

In `src/aidn_hypervisor/state.py`, update provider imports:

```python
from aidn_hypervisor.providers.models import (
    ModelDeployment,
    ProviderInstallationApproval,
    ProviderInstance,
    RuntimeBinding,
)
```

Add this field to `HypervisorStateSnapshot` immediately after `runtime_bindings`:

```python
provider_installation_approvals: list[ProviderInstallationApproval] = Field(
    default_factory=list
)
```

- [ ] **Step 4: Add Hypervisor facade methods**

In `src/aidn_hypervisor/service.py`, add these methods next to the existing provider inventory facade methods:

```python
def approve_provider_installation_plan(
    self,
    *,
    plugin_id: str,
    configuration: dict,
    operator_note: str | None = None,
) -> dict:
    return self.provider_inventory.approve_installation_plan(
        plugin_id=plugin_id,
        configuration=configuration,
        operator_note=operator_note,
    ).model_dump(mode="json")

def list_provider_installation_approvals(self) -> list[dict]:
    return [
        approval.model_dump(mode="json")
        for approval in self.provider_inventory.list_installation_approvals()
    ]
```

- [ ] **Step 5: Wire snapshot and restore**

In `HypervisorService.snapshot_state`, add this argument after `runtime_bindings=[...]`:

```python
provider_installation_approvals=[
    approval.model_copy(deep=True)
    for approval in self.provider_inventory.list_installation_approvals()
],
```

In `HypervisorService.restore_state`, after restoring runtime bindings, add:

```python
for approval in snapshot.provider_installation_approvals:
    self.provider_inventory.store.save_installation_approval(approval)
```

- [ ] **Step 6: Run the focused Hypervisor test**

Run:

```powershell
python -m pytest tests/test_service.py::test_provider_installation_approvals_survive_snapshot_restore -q
```

Expected: pass.

- [ ] **Step 7: Commit**

Run:

```powershell
git add src/aidn_hypervisor/state.py src/aidn_hypervisor/service.py tests/test_service.py
git commit -m "feat: snapshot provider install approvals"
```

### Task 5: Operator API Routes

**Files:**
- Modify: `src/aidn_hypervisor/api.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write failing API tests**

Append these tests near the existing provider installation-plan route tests in `tests/test_api.py`:

```python
def test_provider_plugin_installation_approval_route_creates_local_record() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.post(
        "/operators/provider-plugins/fake-managed/installation-approvals",
        json={
            "configuration": {
                "display_name": "Local Fake",
                "base_url": "http://127.0.0.1:9999",
            },
            "operator_note": "Reviewed plan.",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["plugin_id"] == "fake-managed"
    assert body["status"] == "APPROVED"
    assert body["operator_note"] == "Reviewed plan."
    assert body["plan_hash"].startswith("sha256:")


def test_provider_installation_approvals_route_lists_local_records() -> None:
    service = _service()
    service.approve_provider_installation_plan(
        plugin_id="fake-managed",
        configuration={
            "display_name": "Local Fake",
            "base_url": "http://127.0.0.1:9999",
        },
    )
    client = TestClient(build_app(service=service))

    response = client.get("/operators/provider-installation-approvals")

    assert response.status_code == 200
    assert response.json()["items"][0]["plugin_id"] == "fake-managed"
    assert response.json()["items"][0]["status"] == "APPROVED"


def test_provider_plugin_installation_approval_route_rejects_invalid_plan() -> None:
    service = _service()
    service.plugins.register(BadInstallationPlanPlugin())
    client = TestClient(build_app(service=service))

    response = client.post(
        "/operators/provider-plugins/bad-plan/installation-approvals",
        json={
            "configuration": {
                "display_name": "Local Fake",
                "base_url": "http://127.0.0.1:9999",
            }
        },
    )

    assert response.status_code == 409
    assert "declarative-only" in response.json()["detail"]
```

Update the malformed payload test by adding this request:

```python
approval_extra_field_response = client.post(
    "/operators/provider-plugins/fake-managed/installation-approvals",
    json={
        "configuration": {"base_url": "http://127.0.0.1:9999"},
        "unexpected": True,
    },
)
assert approval_extra_field_response.status_code == 422
```

- [ ] **Step 2: Run the API tests and confirm failure**

Run:

```powershell
python -m pytest tests/test_api.py::test_provider_plugin_installation_approval_route_creates_local_record tests/test_api.py::test_provider_installation_approvals_route_lists_local_records tests/test_api.py::test_provider_plugin_installation_approval_route_rejects_invalid_plan -q
```

Expected: fails with 404 for missing routes.

- [ ] **Step 3: Add request model**

In `src/aidn_hypervisor/api.py`, add this model after `BuildProviderInstallationPlanRequest`:

```python
class ApproveProviderInstallationPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    configuration: dict = Field(default_factory=dict)
    operator_note: str | None = None
```

- [ ] **Step 4: Add approval API routes**

In `src/aidn_hypervisor/api.py`, after the installation-plan route, add:

```python
    @router.post("/operators/provider-plugins/{plugin_id}/installation-approvals")
    async def approve_provider_installation_plan(
        plugin_id: str,
        payload: ApproveProviderInstallationPlanRequest,
    ) -> dict:
        try:
            return service.approve_provider_installation_plan(
                plugin_id=plugin_id,
                configuration=payload.configuration,
                operator_note=payload.operator_note,
            )
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown plugin: {error.args[0]}",
            ) from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @router.get("/operators/provider-installation-approvals")
    async def list_provider_installation_approvals() -> dict:
        return {"items": service.list_provider_installation_approvals()}
```

- [ ] **Step 5: Run focused API tests**

Run:

```powershell
python -m pytest tests/test_api.py::test_provider_plugin_installation_approval_route_creates_local_record tests/test_api.py::test_provider_installation_approvals_route_lists_local_records tests/test_api.py::test_provider_plugin_installation_approval_route_rejects_invalid_plan tests/test_api.py::test_provider_inventory_operator_routes_reject_malformed_payloads -q
```

Expected: pass.

- [ ] **Step 6: Commit**

Run:

```powershell
git add src/aidn_hypervisor/api.py tests/test_api.py
git commit -m "feat: expose provider install approval routes"
```

### Task 6: Operator Workspace Payload and Dashboard Copy

**Files:**
- Modify: `src/aidn_hypervisor/operator_views.py`
- Modify: `src/aidn_hypervisor/static/operator_dashboard.html`
- Test: `tests/test_operator_views.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write failing operator payload test**

Append this test to `tests/test_operator_views.py`:

```python
def test_provider_workspace_payload_includes_installation_approval_summary() -> None:
    service = _service()
    approval = service.approve_provider_installation_plan(
        plugin_id="fake-managed",
        configuration={
            "display_name": "Local Fake",
            "base_url": "http://127.0.0.1:9999",
        },
        operator_note="Reviewed plan.",
    )

    payload = build_operator_providers_payload(service)

    assert payload["summary"]["approved_installation_count"] == 1
    assert payload["installation_approvals"][0]["approval_id"] == approval["approval_id"]
    assert payload["installation_approvals"][0]["status_label"] == "Approved, not applied"
```

- [ ] **Step 2: Add failing dashboard shell assertions**

Append these assertions to `test_operator_dashboard_shell_route_exposes_provider_install_controls` in `tests/test_api.py`:

```python
assert "/operators/provider-installation-approvals" in response.text
assert "Approved, not applied" in response.text
```

- [ ] **Step 3: Run focused operator tests and confirm failure**

Run:

```powershell
python -m pytest tests/test_operator_views.py::test_provider_workspace_payload_includes_installation_approval_summary tests/test_api.py::test_operator_dashboard_shell_route_exposes_provider_install_controls -q
```

Expected: fails because payload and dashboard do not include approval data/copy.

- [ ] **Step 4: Add approval data to provider workspace payload**

In `src/aidn_hypervisor/operator_views.py`, inside `build_operator_providers_payload`, collect approvals:

```python
installation_approvals = [
    {
        **approval,
        "status_label": "Approved, not applied"
        if approval["status"] == "APPROVED"
        else approval["status"].title(),
    }
    for approval in service.list_provider_installation_approvals()
]
```

Add this to the returned `summary`:

```python
"approved_installation_count": sum(
    1 for approval in installation_approvals if approval["status"] == "APPROVED"
),
```

Add this top-level return key:

```python
"installation_approvals": installation_approvals,
```

- [ ] **Step 5: Add dashboard approval copy without adding apply controls**

In `src/aidn_hypervisor/static/operator_dashboard.html`, add the approval list fetch endpoint to the Providers workspace JavaScript where other provider endpoints are referenced:

```javascript
const providerInstallationApprovalsUrl = "/operators/provider-installation-approvals";
```

Add visible copy in the provider install section:

```html
<p class="muted">Approved, not applied: approval records bind an operator decision to an exact plan hash. This MVP still does not execute provider installation plans.</p>
```

If the dashboard renders provider payload summaries, add:

```html
<span x-text="providersPayload.summary?.approved_installation_count || 0"></span>
```

Do not add an `Apply`, `Install now`, `Run installer`, or equivalent button.

- [ ] **Step 6: Run focused operator tests**

Run:

```powershell
python -m pytest tests/test_operator_views.py::test_provider_workspace_payload_includes_installation_approval_summary tests/test_api.py::test_operator_dashboard_shell_route_exposes_provider_install_controls -q
```

Expected: pass.

- [ ] **Step 7: Commit**

Run:

```powershell
git add src/aidn_hypervisor/operator_views.py src/aidn_hypervisor/static/operator_dashboard.html tests/test_operator_views.py tests/test_api.py
git commit -m "feat: show provider install approvals in operator workspace"
```

### Task 7: Verification, Roadmap Note, and Final Commit

**Files:**
- Modify: `docs/superpowers/plans/2026-07-15-provider-install-approval-flow.md` only if execution notes need checked boxes.
- Modify: `docs/superpowers/plans/2026-07-15-provider-plugin-directory-install-plan.md` if it has a next-slice/status section.

- [ ] **Step 1: Run focused provider/operator suite**

Run:

```powershell
python -m pytest tests/providers/test_models.py tests/providers/test_service.py tests/test_service.py tests/test_api.py tests/test_operator_views.py -q
```

Expected: pass.

- [ ] **Step 2: Run full test suite**

Run:

```powershell
python -m pytest -q
```

Expected: pass. If the full suite has pre-existing unrelated failures, capture the exact failing tests and still keep the focused suite green.

- [ ] **Step 3: Verify no install/apply surface was introduced**

Run:

```powershell
rg -n "apply|run installer|Install now|docker|subprocess|Start-Process|pip install|git clone" src/aidn_hypervisor tests docs/superpowers/plans/2026-07-15-provider-install-approval-flow.md
```

Expected: any matches are either existing unrelated code, documentation saying no apply/install execution exists, or test names. There must be no new route or function that executes an installation plan.

- [ ] **Step 4: Inspect git diff**

Run:

```powershell
git status --short
git diff --stat
git diff -- src/aidn_hypervisor/providers src/aidn_hypervisor/state.py src/aidn_hypervisor/service.py src/aidn_hypervisor/api.py src/aidn_hypervisor/operator_views.py src/aidn_hypervisor/static/operator_dashboard.html
```

Expected: changes are limited to approval model/store/service/API/payload/UI/tests/docs.

- [ ] **Step 5: Commit any final documentation/test updates**

If there are uncommitted verification or roadmap note changes, run:

```powershell
git add docs/superpowers/plans tests src
git commit -m "docs: record provider install approval verification"
```

If there are no changes, do not create an empty commit.

## Self-Review

- Spec coverage: approval model, hash binding, local persistence, snapshot/restore, API, operator visibility, and no-apply safety boundary are each covered by tasks.
- Placeholder scan: no unresolved placeholder instructions remain.
- Type consistency: `ProviderInstallationApproval`, `approve_installation_plan`, `list_installation_approvals`, `approve_provider_installation_plan`, and `list_provider_installation_approvals` names are consistent across model/store/service/Hypervisor/API/operator tests.
- Security check: plan intentionally persists only permission IDs and secret requirement metadata, not secret values; the UI copy explicitly says approved plans are not applied.
