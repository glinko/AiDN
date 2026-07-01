# Agent Allocation Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an agent-facing allocation contract so clients can request a usable local provider capability and receive a lease with bundle, runtime, and endpoint details they can later inspect or release.

**Architecture:** Build a small allocation layer inside the hypervisor core rather than a parallel scheduler. Allocations will reuse existing bundle selection, runtime startup, resource accounting, and event journal paths, then expose a dedicated HTTP contract for create/list/get/release allocation flows.

**Tech Stack:** Python, FastAPI, Pydantic, pytest

---

## File Structure

- Modify: `src/aidn_hypervisor/domain/models.py`
  - add allocation request/response domain models
- Modify: `src/aidn_hypervisor/state.py`
  - persist allocation snapshots
- Modify: `src/aidn_hypervisor/service.py`
  - add allocation lifecycle, endpoint resolution, state restore, journal events
- Modify: `src/aidn_hypervisor/api.py`
  - expose allocation endpoints and capability discovery
- Modify: `src/aidn_hypervisor/process_manager.py`
  - preserve runtime metadata already needed for resolved endpoints
- Modify: `tests/test_service.py`
  - cover allocation lifecycle, endpoint resolution, release behavior, restore behavior
- Modify: `tests/test_api.py`
  - cover allocation endpoints and discovery payloads
- Modify: `tests/test_state.py`
  - cover allocation persistence and restore

### Task 1: Allocation Domain and Persistence

**Files:**
- Modify: `src/aidn_hypervisor/domain/models.py`
- Modify: `src/aidn_hypervisor/state.py`
- Test: `tests/test_state.py`

- [ ] **Step 1: Write the failing persistence test**

```python
def test_service_snapshot_and_restore_preserves_allocations() -> None:
    service = _service()
    allocation = service.create_allocation(
        AllocationRequest(workload_type="speech_to_text")
    )

    snapshot = service.snapshot_state()
    restored_service = _service(with_runtime=False, use_process_manager=True)
    restored_service.restore_state(snapshot)

    assert restored_service.get_allocation(allocation["allocation_id"]) == {
        "allocation_id": allocation["allocation_id"],
        "workload_type": "speech_to_text",
        "bundle_id": "whisper-a",
        "runtime_id": allocation["runtime_id"],
        "endpoint": allocation["endpoint"],
        "status": "active",
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_state.py -k preserves_allocations -q`
Expected: FAIL with `AttributeError` or missing allocation state in snapshot/restore

- [ ] **Step 3: Add minimal domain and state models**

```python
class AllocationRequest(BaseModel):
    workload_type: str
    bundle_id: str | None = None
    lease_seconds: int = Field(default=300, ge=1, le=3600)


class AllocationSnapshot(BaseModel):
    allocation_id: str
    workload_type: str
    bundle_id: str
    runtime_id: str
    endpoint: str
    status: str
```

- [ ] **Step 4: Extend hypervisor state snapshot**

```python
class HypervisorStateSnapshot(BaseModel):
    tasks: list[TaskSnapshot] = Field(default_factory=list)
    runtimes: list[RuntimeSnapshot] = Field(default_factory=list)
    bundle_states: list[BundleStateSnapshot] = Field(default_factory=list)
    allocations: list[AllocationSnapshot] = Field(default_factory=list)
    events: list[JournalEvent] = Field(default_factory=list)
```

- [ ] **Step 5: Run test to verify the persistence shape passes after service support is added**

Run: `python -m pytest tests/test_state.py -k preserves_allocations -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/aidn_hypervisor/domain/models.py src/aidn_hypervisor/state.py tests/test_state.py
git commit -m "feat: add allocation state models"
```

### Task 2: Service Allocation Lifecycle

**Files:**
- Modify: `src/aidn_hypervisor/service.py`
- Test: `tests/test_service.py`

- [ ] **Step 1: Write the failing service tests**

```python
def test_service_create_allocation_starts_runtime_and_returns_endpoint() -> None:
    service = _service(with_runtime=False, use_process_manager=True)

    allocation = service.create_allocation(
        AllocationRequest(workload_type="speech_to_text")
    )

    assert allocation["bundle_id"] == "whisper-a"
    assert allocation["runtime_id"] == "rt-1"
    assert allocation["endpoint"] == "http://127.0.0.1:9000"
    assert allocation["status"] == "active"


def test_service_release_allocation_marks_it_released() -> None:
    service = _service(with_runtime=False, use_process_manager=True)
    allocation = service.create_allocation(
        AllocationRequest(workload_type="speech_to_text")
    )

    result = service.release_allocation(allocation["allocation_id"])

    assert result["status"] == "released"
    assert service.get_allocation(allocation["allocation_id"])["status"] == "released"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_service.py -k allocation -q`
Expected: FAIL with missing `create_allocation` / `release_allocation`

- [ ] **Step 3: Add minimal allocation service methods**

```python
def create_allocation(self, request: AllocationRequest) -> dict:
    bundle = self._select_allocation_bundle(request)
    runtime = self._runtime_for_bundle(bundle.bundle_id) or self.start_bundle(bundle.bundle_id)
    allocation = {
        "allocation_id": str(uuid4()),
        "workload_type": request.workload_type,
        "bundle_id": bundle.bundle_id,
        "runtime_id": runtime.runtime_id,
        "endpoint": self._resolve_runtime_endpoint(bundle, runtime),
        "status": "active",
    }
    self._allocations[allocation["allocation_id"]] = allocation
    self.record_event(
        event_type="allocation.created",
        message="allocation created for agent client",
        bundle_id=bundle.bundle_id,
        runtime_id=runtime.runtime_id,
        details={"allocation_id": allocation["allocation_id"]},
    )
    self._persist_state()
    return dict(allocation)
```

- [ ] **Step 4: Add release/get/list helpers and endpoint resolution**

```python
def release_allocation(self, allocation_id: str) -> dict:
    allocation = self._allocations[allocation_id]
    allocation["status"] = "released"
    self.record_event(
        event_type="allocation.released",
        message="allocation released by client",
        bundle_id=allocation["bundle_id"],
        runtime_id=allocation["runtime_id"],
        details={"allocation_id": allocation_id},
    )
    self._persist_state()
    return dict(allocation)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_service.py -k allocation -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/aidn_hypervisor/service.py tests/test_service.py
git commit -m "feat: add allocation service lifecycle"
```

### Task 3: Allocation HTTP Contract

**Files:**
- Modify: `src/aidn_hypervisor/api.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write the failing API tests**

```python
def test_create_allocation_endpoint_returns_agent_lease() -> None:
    service = _service(with_runtime=False, use_process_manager=True)
    client = TestClient(build_app(service=service))

    response = client.post(
        "/allocations",
        json={"workload_type": "speech_to_text"},
    )

    assert response.status_code == 201
    assert response.json()["bundle_id"] == "whisper-a"
    assert response.json()["endpoint"] == "http://127.0.0.1:9000"


def test_release_allocation_endpoint_marks_lease_released() -> None:
    service = _service(with_runtime=False, use_process_manager=True)
    allocation = service.create_allocation(
        AllocationRequest(workload_type="speech_to_text")
    )
    client = TestClient(build_app(service=service))

    response = client.delete(f"/allocations/{allocation['allocation_id']}")

    assert response.status_code == 200
    assert response.json()["status"] == "released"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_api.py -k allocation_endpoint -q`
Expected: FAIL with 404 or missing API support

- [ ] **Step 3: Add allocation endpoints**

```python
@router.post("/allocations", status_code=status.HTTP_201_CREATED)
async def create_allocation(request: AllocationRequest) -> dict:
    return service.create_allocation(request)


@router.get("/allocations")
async def list_allocations() -> list[dict]:
    return service.list_allocations()


@router.get("/allocations/{allocation_id}")
async def get_allocation(allocation_id: str) -> dict:
    return service.get_allocation(allocation_id)


@router.delete("/allocations/{allocation_id}")
async def release_allocation(allocation_id: str) -> dict:
    return service.release_allocation(allocation_id)
```

- [ ] **Step 4: Add capability discovery endpoint**

```python
@router.get("/capabilities")
async def list_capabilities() -> list[dict]:
    return service.capability_inventory()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_api.py -k allocation -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/aidn_hypervisor/api.py tests/test_api.py
git commit -m "feat: add allocation and capability endpoints"
```

### Task 4: Allocation Restore, Journal, and Full Verification

**Files:**
- Modify: `src/aidn_hypervisor/service.py`
- Modify: `tests/test_state.py`
- Modify: `tests/test_service.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Add failing tests for restore and journal events**

```python
def test_service_restore_state_preserves_active_allocation_events() -> None:
    service = _service(with_runtime=False, use_process_manager=True)
    allocation = service.create_allocation(
        AllocationRequest(workload_type="speech_to_text")
    )

    restored = _service(with_runtime=False, use_process_manager=True)
    restored.restore_state(service.snapshot_state())

    assert restored.get_allocation(allocation["allocation_id"])["status"] == "active"
    assert restored.event_journal(limit=1)[0].event_type == "allocation.created"
```

- [ ] **Step 2: Run tests to verify they fail if restore/journal is incomplete**

Run: `python -m pytest tests/test_state.py -k allocation tests/test_service.py -k allocation -q`
Expected: FAIL if allocations are not serialized or restored correctly

- [ ] **Step 3: Implement restore support and capability inventory polishing**

```python
def capability_inventory(self) -> list[dict]:
    return [
        {
            "bundle_id": bundle.bundle_id,
            "workload_type": bundle.workload_type,
            "enabled": bundle.enabled,
            "status": self._bundle_status_for_inventory(bundle),
            "endpoint": bundle.endpoint,
        }
        for bundle in self.bundles
    ]
```

- [ ] **Step 4: Run focused verification**

Run: `python -m pytest tests/test_state.py -k allocation -q`
Expected: PASS

Run: `python -m pytest tests/test_service.py -k allocation -q`
Expected: PASS

Run: `python -m pytest tests/test_api.py -k allocation -q`
Expected: PASS

- [ ] **Step 5: Run full verification**

Run: `python -m pytest -q`
Expected: `passed` with no failures

- [ ] **Step 6: Commit**

```bash
git add src/aidn_hypervisor/service.py tests/test_state.py tests/test_service.py tests/test_api.py
git commit -m "feat: persist and observe agent allocations"
```
