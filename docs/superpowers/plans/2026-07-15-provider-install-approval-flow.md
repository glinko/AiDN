# Provider Install Approval and Apply Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a complete local provider installation lifecycle: preview, approve, apply through a controlled executor, persist job results, and surface the resulting local Provider Instance record.

**Architecture:** Keep provider installation plan generation declarative, require a durable approval before apply, and bind apply to the exact approved plan/configuration hashes. The MVP executor is `RecordedProviderInstallationExecutor`: it records declarative actions and creates local provider inventory state, but it does not run shell, Docker, downloads, package managers, or plugin installer code. Future real host executors can replace the executor interface without changing approval, job, API, persistence, or UI contracts.

**Tech Stack:** Python 3.13, FastAPI, Pydantic v2, pytest, in-memory provider inventory store, static operator dashboard HTML/JS.

**Implementation status:** Implemented on `feat/provider-install-approval-flow` through commit `eed1286`. The safe MVP operator path now covers `Approve/Apply Provider -> Discover Models -> Create Runtime Binding -> Create Endpoint Draft`. Apply remains non-host-mutating through `RecordedProviderInstallationExecutor`; real shell/container/download/package-manager/plugin-installer execution is deferred behind the existing executor, approval, job, persistence, and UI contracts.

**Next phase:** permission diffing, secret-handle selection, dry-run diagnostics, rollback semantics, plugin sandbox policy, signed package verification, and real executor enablement behind explicit operator confirmations.

---

## File Structure

- `src/aidn_hypervisor/providers/models.py`: approval, job, step result, and execution result models.
- `src/aidn_hypervisor/providers/executor.py`: executor Protocol and recorded MVP executor.
- `src/aidn_hypervisor/providers/store.py`: approval/job persistence in provider inventory.
- `src/aidn_hypervisor/providers/service.py`: canonical hashing, approval creation, apply orchestration, job transitions, provider instance creation.
- `src/aidn_hypervisor/state.py`: snapshot fields for approvals and jobs.
- `src/aidn_hypervisor/service.py`: Hypervisor facade and snapshot/restore wiring.
- `src/aidn_hypervisor/api.py`: approval/apply/list HTTP routes.
- `src/aidn_hypervisor/operator_views.py`: Providers workspace approval/job summaries.
- `src/aidn_hypervisor/static/operator_dashboard.html`: controlled apply UI, schema-rendered install forms, recipe prefill, model discovery, Runtime Binding, Endpoint draft creation, and guided setup copy.
- `tests/providers/test_models.py`: model validation tests.
- `tests/providers/test_service.py`: provider inventory approval/apply tests.
- `tests/test_service.py`: Hypervisor snapshot/restore tests.
- `tests/test_api.py`: HTTP route and dashboard shell tests.
- `tests/test_operator_views.py`: provider workspace payload tests.

## Safety Boundaries

- This plan adds an `Apply` route, but the MVP executor is non-host-mutating.
- Do not add shell execution, `subprocess`, Docker calls, package manager calls, Git checkout, model downloads, or plugin installer code execution.
- Do not persist or pass plaintext secret values.
- Apply requires an existing approval and exact hash match.
- Apply result is local operational state, not Ledger, Registry, Verification, Certification, or Reputation evidence.

### Task 1: Approval and Job Models

**Files:**
- Modify: `src/aidn_hypervisor/providers/models.py`
- Test: `tests/providers/test_models.py`

- [ ] **Step 1: Write failing model tests**

Append to `tests/providers/test_models.py`:

```python
import pytest
from pydantic import ValidationError

from aidn_hypervisor.providers.models import (
    ProviderInstallationApproval,
    ProviderInstallationExecutionResult,
    ProviderInstallationJob,
    ProviderInstallationStepResult,
)


def test_provider_installation_approval_captures_plan_binding_without_secrets() -> None:
    approval = ProviderInstallationApproval(
        approval_id="pia-123",
        plugin_id="fake-managed",
        plan_id="plan-fake-managed-local-fake",
        plan_hash="sha256:" + "a" * 64,
        configuration_hash="sha256:" + "b" * 64,
        configuration={"display_name": "Local Fake"},
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

    assert approval.status == "APPROVED"
    assert approval.configuration == {"display_name": "Local Fake"}
    assert approval.approved_permissions == ["network.private"]
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


def test_provider_installation_job_records_apply_result() -> None:
    step = ProviderInstallationStepResult(
        step_id="containers",
        step_type="containers",
        status="RECORDED",
        summary="Recorded 1 container declaration.",
        details={"count": 1},
    )
    job = ProviderInstallationJob(
        job_id="pij-123",
        approval_id="pia-123",
        plugin_id="fake-managed",
        plan_id="plan-fake-managed-local-fake",
        plan_hash="sha256:" + "a" * 64,
        configuration_hash="sha256:" + "b" * 64,
        status="SUCCEEDED",
        executor_id="recorded-declarative-v1",
        step_results=[step],
        provider_instance_id="pi-pij-123",
        created_at="2026-07-15T12:00:00+00:00",
        started_at="2026-07-15T12:00:01+00:00",
        completed_at="2026-07-15T12:00:02+00:00",
    )

    assert job.status == "SUCCEEDED"
    assert job.step_results[0].status == "RECORDED"
    assert job.provider_instance_id == "pi-pij-123"


def test_provider_installation_execution_result_contains_provider_instance_payload() -> None:
    result = ProviderInstallationExecutionResult(
        step_results=[],
        provider_instance={
            "provider_instance_id": "pi-pij-123",
            "plugin_id": "fake-managed",
            "provider_family": "fake",
            "display_name": "Local Fake",
            "connection_mode": "managed",
            "configuration": {"display_name": "Local Fake"},
            "operational_state": "created",
        },
    )

    assert result.provider_instance["connection_mode"] == "managed"
```

- [ ] **Step 2: Run model tests and confirm failure**

Run:

```powershell
python -m pytest tests/providers/test_models.py -q
```

Expected: import failure for new provider installation models.

- [ ] **Step 3: Implement models**

In `src/aidn_hypervisor/providers/models.py`, add `Literal` import if missing:

```python
from typing import Literal
```

Add near existing status declarations:

```python
ProviderInstallationApprovalStatus = Literal["APPROVED", "REVOKED"]
ProviderInstallationJobStatus = Literal["QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"]
ProviderInstallationStepStatus = Literal["RECORDED", "SKIPPED", "FAILED"]
```

Add after `InstallationPlan`:

```python
class ProviderInstallationApproval(BaseModel):
    approval_id: str
    plugin_id: str
    plan_id: str
    plan_hash: str
    configuration_hash: str
    configuration: dict = Field(default_factory=dict)
    approved_permissions: list[str] = Field(default_factory=list)
    acknowledged_secret_requirements: list[dict] = Field(default_factory=list)
    operator_note: str | None = None
    status: ProviderInstallationApprovalStatus = "APPROVED"
    created_at: str

    @field_validator("approval_id", "plugin_id", "plan_id", "plan_hash", "configuration_hash", "created_at")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return _require_non_empty(value)


class ProviderInstallationStepResult(BaseModel):
    step_id: str
    step_type: str
    status: ProviderInstallationStepStatus
    summary: str
    details: dict = Field(default_factory=dict)

    @field_validator("step_id", "step_type", "summary")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return _require_non_empty(value)


class ProviderInstallationJob(BaseModel):
    job_id: str
    approval_id: str
    plugin_id: str
    plan_id: str
    plan_hash: str
    configuration_hash: str
    status: ProviderInstallationJobStatus
    executor_id: str
    step_results: list[ProviderInstallationStepResult] = Field(default_factory=list)
    provider_instance_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None

    @field_validator("job_id", "approval_id", "plugin_id", "plan_id", "plan_hash", "configuration_hash", "executor_id", "created_at")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return _require_non_empty(value)


class ProviderInstallationExecutionResult(BaseModel):
    step_results: list[ProviderInstallationStepResult] = Field(default_factory=list)
    provider_instance: dict
```

- [ ] **Step 4: Run model tests**

Run:

```powershell
python -m pytest tests/providers/test_models.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

Run:

```powershell
git add src/aidn_hypervisor/providers/models.py tests/providers/test_models.py
git commit -m "feat: add provider install lifecycle models"
```

### Task 2: Recorded Executor Boundary

**Files:**
- Create: `src/aidn_hypervisor/providers/executor.py`
- Test: `tests/providers/test_service.py`

- [ ] **Step 1: Write failing executor test**

Append to `tests/providers/test_service.py`:

```python
from aidn_hypervisor.providers.executor import RecordedProviderInstallationExecutor
from aidn_hypervisor.providers.models import InstallationPlan, ProviderInstallationApproval


def test_recorded_provider_installation_executor_records_declarative_plan_without_host_mutation() -> None:
    executor = RecordedProviderInstallationExecutor()
    plan = InstallationPlan(
        plan_id="plan-fake-managed-local-fake",
        plugin_id="fake-managed",
        plan_version="1.0.0",
        summary="Install fake provider",
        containers=[{"name": "fake-provider"}],
        health_checks=[{"url": "http://127.0.0.1:9999"}],
    )
    approval = ProviderInstallationApproval(
        approval_id="pia-123",
        plugin_id="fake-managed",
        plan_id=plan.plan_id,
        plan_hash="sha256:" + "a" * 64,
        configuration_hash="sha256:" + "b" * 64,
        configuration={"display_name": "Local Fake", "base_url": "http://127.0.0.1:9999"},
        status="APPROVED",
        created_at="2026-07-15T12:00:00+00:00",
    )

    result = executor.apply(
        approval=approval,
        plan=plan,
        configuration=approval.configuration,
        manifest={
            "plugin_id": "fake-managed",
            "display_name": "Fake Managed Provider",
            "provider_families": ["fake"],
        },
        provider_instance_id="pi-pij-123",
    )

    assert executor.executor_id == "recorded-declarative-v1"
    assert [step.step_type for step in result.step_results] == ["containers", "health_checks"]
    assert result.provider_instance["provider_instance_id"] == "pi-pij-123"
    assert result.provider_instance["connection_mode"] == "managed"
    assert result.provider_instance["operational_state"] == "created"
```

- [ ] **Step 2: Run executor test and confirm failure**

Run:

```powershell
python -m pytest tests/providers/test_service.py::test_recorded_provider_installation_executor_records_declarative_plan_without_host_mutation -q
```

Expected: import failure for `aidn_hypervisor.providers.executor`.

- [ ] **Step 3: Implement recorded executor**

Create `src/aidn_hypervisor/providers/executor.py`:

```python
from typing import Protocol

from aidn_hypervisor.providers.models import (
    InstallationPlan,
    ProviderInstallationApproval,
    ProviderInstallationExecutionResult,
    ProviderInstallationStepResult,
)


class ProviderInstallationExecutor(Protocol):
    executor_id: str

    def apply(
        self,
        *,
        approval: ProviderInstallationApproval,
        plan: InstallationPlan,
        configuration: dict,
        manifest: dict,
        provider_instance_id: str,
    ) -> ProviderInstallationExecutionResult:
        ...


class RecordedProviderInstallationExecutor:
    executor_id = "recorded-declarative-v1"

    def apply(
        self,
        *,
        approval: ProviderInstallationApproval,
        plan: InstallationPlan,
        configuration: dict,
        manifest: dict,
        provider_instance_id: str,
    ) -> ProviderInstallationExecutionResult:
        step_results = []
        for step_type in (
            "containers",
            "processes",
            "model_downloads",
            "volumes",
            "networks",
            "environment",
            "resource_limits",
            "health_checks",
        ):
            value = getattr(plan, step_type)
            count = len(value) if isinstance(value, list) else len(value.keys())
            if count == 0:
                continue
            step_results.append(
                ProviderInstallationStepResult(
                    step_id=step_type,
                    step_type=step_type,
                    status="RECORDED",
                    summary=f"Recorded {count} {step_type} declaration(s).",
                    details={"count": count},
                )
            )

        provider_families = manifest.get("provider_families", [])
        display_name = configuration.get("display_name") or manifest.get("display_name") or approval.plugin_id
        return ProviderInstallationExecutionResult(
            step_results=step_results,
            provider_instance={
                "provider_instance_id": provider_instance_id,
                "plugin_id": approval.plugin_id,
                "provider_family": provider_families[0] if provider_families else "unknown",
                "display_name": display_name,
                "connection_mode": "managed",
                "configuration": dict(configuration),
                "operational_state": "created",
            },
        )
```

- [ ] **Step 4: Run executor test**

Run:

```powershell
python -m pytest tests/providers/test_service.py::test_recorded_provider_installation_executor_records_declarative_plan_without_host_mutation -q
```

Expected: pass.

- [ ] **Step 5: Commit**

Run:

```powershell
git add src/aidn_hypervisor/providers/executor.py tests/providers/test_service.py
git commit -m "feat: add recorded provider install executor"
```

### Task 3: Store Approvals and Jobs

**Files:**
- Modify: `src/aidn_hypervisor/providers/store.py`
- Test: `tests/providers/test_service.py`

- [ ] **Step 1: Write failing store test**

Append to `tests/providers/test_service.py`:

```python
from aidn_hypervisor.providers.models import ProviderInstallationJob


def test_provider_inventory_store_saves_installation_approvals_and_jobs() -> None:
    store = InMemoryProviderInventoryStore()
    approval = ProviderInstallationApproval(
        approval_id="pia-123",
        plugin_id="fake-managed",
        plan_id="plan-fake-managed-local-fake",
        plan_hash="sha256:" + "a" * 64,
        configuration_hash="sha256:" + "b" * 64,
        configuration={"display_name": "Local Fake"},
        status="APPROVED",
        created_at="2026-07-15T12:00:00+00:00",
    )
    job = ProviderInstallationJob(
        job_id="pij-123",
        approval_id="pia-123",
        plugin_id="fake-managed",
        plan_id="plan-fake-managed-local-fake",
        plan_hash=approval.plan_hash,
        configuration_hash=approval.configuration_hash,
        status="QUEUED",
        executor_id="recorded-declarative-v1",
        created_at="2026-07-15T12:00:00+00:00",
    )

    store.save_installation_approval(approval)
    store.save_installation_job(job)

    assert store.get_installation_approval("pia-123") == approval
    assert store.list_installation_approvals() == [approval]
    assert store.get_installation_job("pij-123") == job
    assert store.list_installation_jobs() == [job]
```

- [ ] **Step 2: Run store test and confirm failure**

Run:

```powershell
python -m pytest tests/providers/test_service.py::test_provider_inventory_store_saves_installation_approvals_and_jobs -q
```

Expected: store methods are missing.

- [ ] **Step 3: Implement store methods**

Update `src/aidn_hypervisor/providers/store.py` imports:

```python
from aidn_hypervisor.providers.models import (
    ModelDeployment,
    ProviderInstallationApproval,
    ProviderInstallationJob,
    ProviderInstance,
    RuntimeBinding,
)
```

In `InMemoryProviderInventoryStore.__init__`, add:

```python
self._installation_approvals: dict[str, ProviderInstallationApproval] = {}
self._installation_jobs: dict[str, ProviderInstallationJob] = {}
```

Add methods:

```python
def save_installation_approval(self, approval: ProviderInstallationApproval) -> ProviderInstallationApproval:
    self._installation_approvals[approval.approval_id] = approval.model_copy(deep=True)
    return approval

def get_installation_approval(self, approval_id: str) -> ProviderInstallationApproval:
    return self._installation_approvals[approval_id].model_copy(deep=True)

def list_installation_approvals(self) -> list[ProviderInstallationApproval]:
    return [approval.model_copy(deep=True) for approval in self._installation_approvals.values()]

def save_installation_job(self, job: ProviderInstallationJob) -> ProviderInstallationJob:
    self._installation_jobs[job.job_id] = job.model_copy(deep=True)
    return job

def get_installation_job(self, job_id: str) -> ProviderInstallationJob:
    return self._installation_jobs[job_id].model_copy(deep=True)

def list_installation_jobs(self) -> list[ProviderInstallationJob]:
    return [job.model_copy(deep=True) for job in self._installation_jobs.values()]
```

- [ ] **Step 4: Run store test**

Run:

```powershell
python -m pytest tests/providers/test_service.py::test_provider_inventory_store_saves_installation_approvals_and_jobs -q
```

Expected: pass.

- [ ] **Step 5: Commit**

Run:

```powershell
git add src/aidn_hypervisor/providers/store.py tests/providers/test_service.py
git commit -m "feat: persist provider install approvals and jobs"
```

### Task 4: Provider Inventory Approval and Apply Service

**Files:**
- Modify: `src/aidn_hypervisor/providers/service.py`
- Test: `tests/providers/test_service.py`

- [ ] **Step 1: Write failing service tests**

Append to `tests/providers/test_service.py`:

```python
def test_provider_inventory_approves_and_applies_installation_plan() -> None:
    service = ProviderInventoryService(
        plugins=_registry(),
        store=InMemoryProviderInventoryStore(),
    )
    approval = service.approve_installation_plan(
        plugin_id="fake-managed",
        configuration={"display_name": "Local Fake", "base_url": "http://127.0.0.1:9999"},
        operator_note="Reviewed plan.",
    )

    job = service.apply_installation_approval(approval_id=approval.approval_id)

    assert job.status == "SUCCEEDED"
    assert job.approval_id == approval.approval_id
    assert job.plan_hash == approval.plan_hash
    assert job.provider_instance_id is not None
    provider = service.store.get_provider_instance(job.provider_instance_id)
    assert provider.plugin_id == "fake-managed"
    assert provider.connection_mode == "managed"
    assert provider.operational_state == "created"
    assert service.list_installation_jobs() == [job]


def test_provider_inventory_apply_rejects_revoked_approval() -> None:
    service = ProviderInventoryService(
        plugins=_registry(),
        store=InMemoryProviderInventoryStore(),
    )
    approval = service.approve_installation_plan(
        plugin_id="fake-managed",
        configuration={"display_name": "Local Fake", "base_url": "http://127.0.0.1:9999"},
    )
    service.store.save_installation_approval(approval.model_copy(update={"status": "REVOKED"}))

    with pytest.raises(ValueError, match="approval is not active"):
        service.apply_installation_approval(approval_id=approval.approval_id)


def test_provider_inventory_apply_rejects_plan_hash_mismatch() -> None:
    class ChangingPlanPlugin(FakeManagedPlugin):
        plugin_id = "changing-plan"

        def __init__(self) -> None:
            self.counter = 0

        def describe(self) -> dict:
            description = super().describe()
            description["plugin_id"] = self.plugin_id
            return description

        def build_installation_plan(self, configuration: dict) -> dict:
            self.counter += 1
            plan = super().build_installation_plan(configuration)
            plan["plugin_id"] = self.plugin_id
            plan["summary"] = f"Install attempt {self.counter}"
            return plan

    registry = PluginRegistry()
    registry.register(ChangingPlanPlugin())
    service = ProviderInventoryService(
        plugins=registry,
        store=InMemoryProviderInventoryStore(),
    )
    approval = service.approve_installation_plan(
        plugin_id="changing-plan",
        configuration={"display_name": "Local Fake", "base_url": "http://127.0.0.1:9999"},
    )

    with pytest.raises(ValueError, match="approved plan hash does not match"):
        service.apply_installation_approval(approval_id=approval.approval_id)
```

- [ ] **Step 2: Run service tests and confirm failure**

Run:

```powershell
python -m pytest tests/providers/test_service.py::test_provider_inventory_approves_and_applies_installation_plan tests/providers/test_service.py::test_provider_inventory_apply_rejects_revoked_approval tests/providers/test_service.py::test_provider_inventory_apply_rejects_plan_hash_mismatch -q
```

Expected: service methods are missing.

- [ ] **Step 3: Implement service hashing, approval, apply, and job listing**

In `src/aidn_hypervisor/providers/service.py`, add imports:

```python
import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

from aidn_hypervisor.providers.executor import (
    ProviderInstallationExecutor,
    RecordedProviderInstallationExecutor,
)
```

Add model imports:

```python
ProviderInstallationApproval,
ProviderInstallationJob,
ProviderPluginManifest,
ProviderInstance,
```

Add helpers:

```python
def _canonical_hash(value: dict) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return f"sha256:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
```

Update `ProviderInventoryService.__init__` to accept an executor:

```python
def __init__(
    self,
    *,
    plugins: PluginRegistry,
    store: InMemoryProviderInventoryStore,
    installation_executor: ProviderInstallationExecutor | None = None,
) -> None:
    self.plugins = plugins
    self.store = store
    self.installation_executor = installation_executor or RecordedProviderInstallationExecutor()
```

Add methods after `build_installation_plan`:

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
        configuration=dict(configuration),
        approved_permissions=[permission.permission_id for permission in manifest.required_permissions],
        acknowledged_secret_requirements=[
            requirement.model_dump(mode="json") for requirement in manifest.secret_requirements
        ],
        operator_note=operator_note,
        status="APPROVED",
        created_at=_now_iso(),
    )
    self.store.save_installation_approval(approval)
    return approval

def list_installation_approvals(self) -> list[ProviderInstallationApproval]:
    return self.store.list_installation_approvals()

def apply_installation_approval(self, *, approval_id: str) -> ProviderInstallationJob:
    approval = self.store.get_installation_approval(approval_id)
    if approval.status != "APPROVED":
        raise ValueError("installation approval is not active")
    plugin = self._get_plugin(approval.plugin_id)
    manifest = ProviderPluginManifest.model_validate(plugin.plugin_manifest())
    plan = InstallationPlan.model_validate(
        self.build_installation_plan(
            plugin_id=approval.plugin_id,
            configuration=approval.configuration,
        )
    )
    plan_hash = _canonical_hash(plan.model_dump(mode="json"))
    configuration_hash = _canonical_hash(dict(approval.configuration))
    if plan_hash != approval.plan_hash:
        raise ValueError("approved plan hash does not match current plan")
    if configuration_hash != approval.configuration_hash:
        raise ValueError("approved configuration hash does not match current configuration")

    now = _now_iso()
    job_id = f"pij-{uuid4().hex[:12]}"
    provider_instance_id = f"pi-{job_id}"
    job = ProviderInstallationJob(
        job_id=job_id,
        approval_id=approval.approval_id,
        plugin_id=approval.plugin_id,
        plan_id=approval.plan_id,
        plan_hash=approval.plan_hash,
        configuration_hash=approval.configuration_hash,
        status="QUEUED",
        executor_id=self.installation_executor.executor_id,
        created_at=now,
    )
    self.store.save_installation_job(job)
    running = job.model_copy(update={"status": "RUNNING", "started_at": _now_iso()})
    self.store.save_installation_job(running)
    try:
        result = self.installation_executor.apply(
            approval=approval,
            plan=plan,
            configuration=approval.configuration,
            manifest=manifest.model_dump(mode="json"),
            provider_instance_id=provider_instance_id,
        )
        provider = ProviderInstance.model_validate(result.provider_instance)
        self.store.save_provider_instance(provider)
        succeeded = running.model_copy(
            update={
                "status": "SUCCEEDED",
                "step_results": result.step_results,
                "provider_instance_id": provider.provider_instance_id,
                "completed_at": _now_iso(),
            }
        )
        self.store.save_installation_job(succeeded)
        return succeeded
    except Exception as error:
        failed = running.model_copy(
            update={
                "status": "FAILED",
                "error_code": error.__class__.__name__,
                "error_message": str(error),
                "completed_at": _now_iso(),
            }
        )
        self.store.save_installation_job(failed)
        return failed

def list_installation_jobs(self) -> list[ProviderInstallationJob]:
    return self.store.list_installation_jobs()
```

- [ ] **Step 4: Run provider service tests**

Run:

```powershell
python -m pytest tests/providers/test_service.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

Run:

```powershell
git add src/aidn_hypervisor/providers/service.py tests/providers/test_service.py
git commit -m "feat: apply approved provider install plans"
```

### Task 5: Hypervisor Facade and Snapshot Persistence

**Files:**
- Modify: `src/aidn_hypervisor/state.py`
- Modify: `src/aidn_hypervisor/service.py`
- Test: `tests/test_service.py`

- [ ] **Step 1: Write failing snapshot/restore test**

Append to `tests/test_service.py`:

```python
def test_provider_installation_approval_and_job_survive_snapshot_restore() -> None:
    service = _service()
    approval = service.approve_provider_installation_plan(
        plugin_id="fake-managed",
        configuration={"display_name": "Local Fake", "base_url": "http://127.0.0.1:9999"},
        operator_note="Reviewed before controlled apply.",
    )
    job = service.apply_provider_installation_approval(approval["approval_id"])

    snapshot = service.snapshot_state()
    restored = _service()
    restored.restore_state(snapshot)

    assert restored.list_provider_installation_approvals()[0]["approval_id"] == approval["approval_id"]
    assert restored.list_provider_installation_jobs()[0]["job_id"] == job["job_id"]
    assert restored.provider_inventory.store.get_provider_instance(job["provider_instance_id"]).plugin_id == "fake-managed"
```

- [ ] **Step 2: Run focused test and confirm failure**

Run:

```powershell
python -m pytest tests/test_service.py::test_provider_installation_approval_and_job_survive_snapshot_restore -q
```

Expected: Hypervisor facade methods or snapshot fields are missing.

- [ ] **Step 3: Add snapshot fields**

In `src/aidn_hypervisor/state.py`, import:

```python
ProviderInstallationApproval,
ProviderInstallationJob,
```

Add to `HypervisorStateSnapshot` after `runtime_bindings`:

```python
provider_installation_approvals: list[ProviderInstallationApproval] = Field(default_factory=list)
provider_installation_jobs: list[ProviderInstallationJob] = Field(default_factory=list)
```

- [ ] **Step 4: Add Hypervisor facade methods**

In `src/aidn_hypervisor/service.py`, add near existing provider facade methods:

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

def apply_provider_installation_approval(self, approval_id: str) -> dict:
    return self.provider_inventory.apply_installation_approval(
        approval_id=approval_id
    ).model_dump(mode="json")

def list_provider_installation_approvals(self) -> list[dict]:
    return [
        approval.model_dump(mode="json")
        for approval in self.provider_inventory.list_installation_approvals()
    ]

def list_provider_installation_jobs(self) -> list[dict]:
    return [
        job.model_dump(mode="json")
        for job in self.provider_inventory.list_installation_jobs()
    ]
```

- [ ] **Step 5: Wire snapshot/restore**

In `snapshot_state`, after `runtime_bindings`, add:

```python
provider_installation_approvals=[
    approval.model_copy(deep=True)
    for approval in self.provider_inventory.list_installation_approvals()
],
provider_installation_jobs=[
    job.model_copy(deep=True)
    for job in self.provider_inventory.list_installation_jobs()
],
```

In `restore_state`, after runtime bindings restore, add:

```python
for approval in snapshot.provider_installation_approvals:
    self.provider_inventory.store.save_installation_approval(approval)
for job in snapshot.provider_installation_jobs:
    self.provider_inventory.store.save_installation_job(job)
```

- [ ] **Step 6: Run focused test**

Run:

```powershell
python -m pytest tests/test_service.py::test_provider_installation_approval_and_job_survive_snapshot_restore -q
```

Expected: pass.

- [ ] **Step 7: Commit**

Run:

```powershell
git add src/aidn_hypervisor/state.py src/aidn_hypervisor/service.py tests/test_service.py
git commit -m "feat: snapshot provider install apply jobs"
```

### Task 6: Operator API Routes

**Files:**
- Modify: `src/aidn_hypervisor/api.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write failing API tests**

Append near existing provider installation-plan route tests in `tests/test_api.py`:

```python
def test_provider_installation_approval_and_apply_routes() -> None:
    client = TestClient(build_app(service=_service()))

    approval_response = client.post(
        "/operators/provider-plugins/fake-managed/installation-approvals",
        json={
            "configuration": {"display_name": "Local Fake", "base_url": "http://127.0.0.1:9999"},
            "operator_note": "Reviewed plan.",
        },
    )
    assert approval_response.status_code == 200
    approval = approval_response.json()

    apply_response = client.post(
        f"/operators/provider-installation-approvals/{approval['approval_id']}/apply",
        json={"operator_note": "Controlled apply."},
    )
    assert apply_response.status_code == 200
    job = apply_response.json()
    assert job["status"] == "SUCCEEDED"
    assert job["approval_id"] == approval["approval_id"]
    assert job["executor_id"] == "recorded-declarative-v1"
    assert job["provider_instance_id"].startswith("pi-pij-")

    jobs_response = client.get("/operators/provider-installation-jobs")
    assert jobs_response.status_code == 200
    assert jobs_response.json()["items"][0]["job_id"] == job["job_id"]


def test_provider_installation_apply_route_rejects_unknown_approval() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.post(
        "/operators/provider-installation-approvals/pia-missing/apply",
        json={},
    )

    assert response.status_code == 404
```

Add malformed payload assertion to existing malformed payload route test:

```python
approval_extra_field_response = client.post(
    "/operators/provider-plugins/fake-managed/installation-approvals",
    json={"configuration": {}, "unexpected": True},
)
assert approval_extra_field_response.status_code == 422
```

- [ ] **Step 2: Run focused API tests and confirm failure**

Run:

```powershell
python -m pytest tests/test_api.py::test_provider_installation_approval_and_apply_routes tests/test_api.py::test_provider_installation_apply_route_rejects_unknown_approval -q
```

Expected: missing routes.

- [ ] **Step 3: Add request models**

In `src/aidn_hypervisor/api.py`, add after `BuildProviderInstallationPlanRequest`:

```python
class ApproveProviderInstallationPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    configuration: dict = Field(default_factory=dict)
    operator_note: str | None = None


class ApplyProviderInstallationApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operator_note: str | None = None
```

- [ ] **Step 4: Add routes**

After the installation-plan route, add:

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
            raise HTTPException(status_code=404, detail=f"Unknown plugin: {error.args[0]}") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @router.get("/operators/provider-installation-approvals")
    async def list_provider_installation_approvals() -> dict:
        return {"items": service.list_provider_installation_approvals()}

    @router.post("/operators/provider-installation-approvals/{approval_id}/apply")
    async def apply_provider_installation_approval(
        approval_id: str,
        payload: ApplyProviderInstallationApprovalRequest,
    ) -> dict:
        try:
            return service.apply_provider_installation_approval(approval_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=f"Unknown approval: {error.args[0]}") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @router.get("/operators/provider-installation-jobs")
    async def list_provider_installation_jobs() -> dict:
        return {"items": service.list_provider_installation_jobs()}
```

- [ ] **Step 5: Run focused API tests**

Run:

```powershell
python -m pytest tests/test_api.py::test_provider_installation_approval_and_apply_routes tests/test_api.py::test_provider_installation_apply_route_rejects_unknown_approval tests/test_api.py::test_provider_inventory_operator_routes_reject_malformed_payloads -q
```

Expected: pass.

- [ ] **Step 6: Commit**

Run:

```powershell
git add src/aidn_hypervisor/api.py tests/test_api.py
git commit -m "feat: expose provider install apply routes"
```

### Task 7: Operator Workspace UI and Payload

**Files:**
- Modify: `src/aidn_hypervisor/operator_views.py`
- Modify: `src/aidn_hypervisor/static/operator_dashboard.html`
- Test: `tests/test_operator_views.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write failing operator payload test**

Append to `tests/test_operator_views.py`:

```python
def test_provider_workspace_payload_includes_installation_apply_summary() -> None:
    service = _service()
    approval = service.approve_provider_installation_plan(
        plugin_id="fake-managed",
        configuration={"display_name": "Local Fake", "base_url": "http://127.0.0.1:9999"},
    )
    job = service.apply_provider_installation_approval(approval["approval_id"])

    payload = build_operator_providers_payload(service)

    assert payload["summary"]["approved_installation_count"] == 1
    assert payload["summary"]["installation_job_count"] == 1
    assert payload["installation_approvals"][0]["status_label"] == "Applied with controlled executor"
    assert payload["installation_jobs"][0]["job_id"] == job["job_id"]
    assert payload["installation_jobs"][0]["status"] == "SUCCEEDED"
```

- [ ] **Step 2: Add failing dashboard shell assertions**

Append to `test_operator_dashboard_shell_route_exposes_provider_install_controls` in `tests/test_api.py`:

```python
assert "/operators/provider-installation-approvals" in response.text
assert "/operators/provider-installation-jobs" in response.text
assert "Apply approved plan" in response.text
assert "controlled executor" in response.text
```

- [ ] **Step 3: Run focused operator tests and confirm failure**

Run:

```powershell
python -m pytest tests/test_operator_views.py::test_provider_workspace_payload_includes_installation_apply_summary tests/test_api.py::test_operator_dashboard_shell_route_exposes_provider_install_controls -q
```

Expected: missing payload keys/copy.

- [ ] **Step 4: Add operator payload data**

In `src/aidn_hypervisor/operator_views.py`, inside `build_operator_providers_payload`, collect jobs and approvals:

```python
installation_jobs = service.list_provider_installation_jobs()
applied_approval_ids = {
    job["approval_id"] for job in installation_jobs if job["status"] == "SUCCEEDED"
}
installation_approvals = []
for approval in service.list_provider_installation_approvals():
    status_label = (
        "Applied with controlled executor"
        if approval["approval_id"] in applied_approval_ids
        else "Approved, ready to apply"
    )
    installation_approvals.append({**approval, "status_label": status_label})
```

Add to returned `summary`:

```python
"approved_installation_count": sum(
    1 for approval in installation_approvals if approval["status"] == "APPROVED"
),
"installation_job_count": len(installation_jobs),
```

Add top-level keys:

```python
"installation_approvals": installation_approvals,
"installation_jobs": installation_jobs,
```

- [ ] **Step 5: Add dashboard controlled apply copy**

In `src/aidn_hypervisor/static/operator_dashboard.html`, add endpoint references/copy in Providers workspace:

```html
<p class="muted">Apply approved plan uses the controlled executor in this MVP. It records declarative actions and creates local provider inventory state; it does not run shell, Docker, downloads, or plugin installer code.</p>
<button type="button">Apply approved plan</button>
```

Ensure the dashboard source includes these route strings:

```javascript
const providerInstallationApprovalsUrl = "/operators/provider-installation-approvals";
const providerInstallationJobsUrl = "/operators/provider-installation-jobs";
```

- [ ] **Step 6: Run focused operator tests**

Run:

```powershell
python -m pytest tests/test_operator_views.py::test_provider_workspace_payload_includes_installation_apply_summary tests/test_api.py::test_operator_dashboard_shell_route_exposes_provider_install_controls -q
```

Expected: pass.

- [ ] **Step 7: Commit**

Run:

```powershell
git add src/aidn_hypervisor/operator_views.py src/aidn_hypervisor/static/operator_dashboard.html tests/test_operator_views.py tests/test_api.py
git commit -m "feat: show provider install apply state"
```

### Task 8: Verification

**Files:**
- Modify: no source files unless verification exposes an issue.

- [ ] **Step 1: Run focused provider/operator suite**

Run:

```powershell
python -m pytest tests/providers/test_models.py tests/providers/test_service.py tests/test_service.py tests/test_api.py tests/test_operator_views.py -q
```

Expected: pass.

- [ ] **Step 2: Run full suite**

Run:

```powershell
python -m pytest -q
```

Expected: pass. If there are pre-existing unrelated failures, capture exact failing tests and keep the focused suite green.

- [ ] **Step 3: Verify no host mutation execution was added**

Run:

```powershell
rg -n "subprocess|Start-Process|docker|podman|pip install|git clone|Invoke-WebRequest|curl|Remove-Item|Move-Item" src/aidn_hypervisor/providers src/aidn_hypervisor/api.py src/aidn_hypervisor/service.py tests/providers
```

Expected: no new host-mutation execution paths in provider install code.

- [ ] **Step 4: Inspect diff**

Run:

```powershell
git status --short
git diff --stat
git log --oneline -8
```

Expected: only provider install lifecycle code, tests, docs, and dashboard copy changed.

## Self-Review

- Spec coverage: preview, approval, apply, job persistence, executor boundary, Provider Instance creation, schema-rendered UI, Installation Recipe prefill, model discovery, Runtime Binding creation, Endpoint draft creation, guided setup copy, API, and snapshot/restore are covered.
- Placeholder scan: no unresolved placeholder instructions remain.
- Type consistency: `ProviderInstallationApproval`, `ProviderInstallationJob`, `ProviderInstallationStepResult`, `ProviderInstallationExecutionResult`, `RecordedProviderInstallationExecutor`, `approve_installation_plan`, `apply_installation_approval`, `discover_models_for_provider_instance`, `create_runtime_binding`, and endpoint-draft `runtime_binding_id` handoff are used consistently.
- Security check: the plan introduces an apply route but keeps execution non-host-mutating; real shell/container/download adapters are explicitly excluded.
