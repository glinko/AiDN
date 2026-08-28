# Allocation Lease TTL And Gating Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add expiring allocation leases with cleanup and enforce explicit refusal when a lease cannot be granted because the target bundle is unavailable or node resources cannot fit the runtime residency.

**Architecture:** Extend the new allocation layer, not the task queue. Allocations remain immediate lease requests: the hypervisor either grants a lease with `expires_at` and reserved residency, or returns a conflict. Expired leases are cleaned before reads and writes so state stays self-healing without a background worker.

**Tech Stack:** Python, FastAPI, Pydantic, pytest

---

## File Structure

- Modify: `src/aidn_hypervisor/state.py`
  - persist allocation timestamps and reservation ids
- Modify: `src/aidn_hypervisor/service.py`
  - add lease expiry timestamps, cleanup, resource gating, release of held reservations
- Modify: `src/aidn_hypervisor/api.py`
  - surface conflict responses unchanged from service `ValueError`
- Modify: `tests/test_service.py`
  - verify expiry, cleanup, and resource refusal
- Modify: `tests/test_api.py`
  - verify allocation conflict and expiry-visible behavior
- Modify: `tests/test_state.py`
  - verify expired allocations are not restored as active

### Task 1: Expiring Lease State

**Files:**
- Modify: `src/aidn_hypervisor/state.py`
- Modify: `tests/test_state.py`

- [ ] **Step 1: Write the failing restore test**

```python
def test_service_restore_skips_expired_allocation() -> None:
    bundle = _bundle("whisper-a", "speech_to_text").model_copy(
        update={"endpoint": "http://127.0.0.1:9000"}
    )
    service = _service(bundles=[bundle], plugins=_registry())
    allocation = service.create_allocation(
        AllocationRequest(workload_type="speech_to_text", lease_seconds=1)
    )

    snapshot = service.snapshot_state()
    restored = _service(bundles=[bundle], plugins=_registry())
    restored.restore_state(snapshot)

    assert restored.get_allocation(allocation["allocation_id"])["status"] == "active"
```

- [ ] **Step 2: Run test to verify it fails after time control is added**

Run: `python -m pytest tests/test_state.py -k expired_allocation -q`
Expected: FAIL because allocation snapshots do not carry expiry metadata

- [ ] **Step 3: Add snapshot fields for lease timing**

```python
class AllocationSnapshot(BaseModel):
    allocation_id: str
    request: AllocationRequest
    bundle_id: str
    runtime_id: str
    endpoint: str
    status: str
    created_at: str
    expires_at: str
    reservation_id: str | None = None
```

- [ ] **Step 4: Run the restore test again after service support is added**

Run: `python -m pytest tests/test_state.py -k expired_allocation -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aidn_hypervisor/state.py tests/test_state.py
git commit -m "feat: persist allocation lease timing"
```

### Task 2: Lease Cleanup And Resource Gating

**Files:**
- Modify: `src/aidn_hypervisor/service.py`
- Modify: `tests/test_service.py`

- [ ] **Step 1: Write the failing service tests**

```python
def test_service_releases_expired_allocation_on_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_time = [1_781_827_800.0]
    monkeypatch.setattr("aidn_hypervisor.service.time.time", lambda: current_time[0])
    service = _allocation_service()
    allocation = service.create_allocation(
        AllocationRequest(workload_type="speech_to_text", lease_seconds=1)
    )

    current_time[0] += 2.0

    assert service.get_allocation(allocation["allocation_id"])["status"] == "expired"


def test_service_create_allocation_rejects_when_runtime_residency_cannot_fit() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=1.0, ram_mb=1024, vram_mb={"gpu0": 256})
        ),
        bundles=[
            _bundle(
                "whisper-a",
                "speech_to_text",
                resource_profile=ResourceProfile(
                    steady_cpu=2.0,
                    steady_ram_mb=2048,
                    steady_vram_mb=512,
                ),
                endpoint="http://127.0.0.1:9000",
            )
        ],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
    )

    with pytest.raises(ValueError, match="insufficient resources"):
        service.create_allocation(AllocationRequest(workload_type="speech_to_text"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_service.py -k "expired_allocation or runtime_residency_cannot_fit" -q`
Expected: FAIL because leases do not expire and allocations do not gate on residency fit

- [ ] **Step 3: Add cleanup and residency checks**

```python
def _cleanup_expired_allocations(self) -> None:
    now = time.time()
    for allocation in self._allocations.values():
        if allocation["status"] != "active":
            continue
        if allocation["expires_at_ts"] > now:
            continue
        allocation["status"] = "expired"
        reservation_id = allocation.get("reservation_id")
        if reservation_id is not None and self.resources is not None:
            self.resources.release(reservation_id)
        self.record_event(
            event_type="allocation.expired",
            message="allocation lease expired",
            bundle_id=allocation["bundle_id"],
            runtime_id=allocation["runtime_id"],
            details={"allocation_id": allocation["allocation_id"]},
        )
```

- [ ] **Step 4: Run targeted tests to verify they pass**

Run: `python -m pytest tests/test_service.py -k "expired_allocation or runtime_residency_cannot_fit" -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aidn_hypervisor/service.py tests/test_service.py
git commit -m "feat: add allocation lease cleanup and gating"
```

### Task 3: API Behavior And Full Verification

**Files:**
- Modify: `tests/test_api.py`
- Modify: `tests/test_state.py`
- Modify: `src/aidn_hypervisor/service.py`

- [ ] **Step 1: Write the failing API tests**

```python
def test_create_allocation_endpoint_returns_409_when_resources_do_not_fit() -> None:
    service = _service(
        with_runtime=False,
        use_process_manager=True,
        capacity=NodeCapacity(cpu_cores=1.0, ram_mb=1024, gpu_devices=["gpu0"], vram_mb={"gpu0": 256}),
        whisper_profile=ResourceProfile(steady_cpu=2.0, steady_ram_mb=2048, steady_vram_mb=512),
        whisper_endpoint="http://127.0.0.1:9000",
    )
    client = TestClient(build_app(service=service))

    response = client.post("/allocations", json={"workload_type": "speech_to_text"})

    assert response.status_code == 409
    assert "insufficient resources" in response.json()["detail"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_api.py -k "allocation_endpoint_returns_409 or expired_allocation" -q`
Expected: FAIL until service cleanup and conflict propagation are complete

- [ ] **Step 3: Ensure reads trigger cleanup before returning allocations**

```python
def get_allocation(self, allocation_id: str) -> dict:
    self._cleanup_expired_allocations()
    return self._public_allocation(self._allocations[allocation_id])
```

- [ ] **Step 4: Run focused verification**

Run: `python -m pytest tests/test_state.py -k expired_allocation -q`
Expected: PASS

Run: `python -m pytest tests/test_service.py -k "expired_allocation or runtime_residency_cannot_fit" -q`
Expected: PASS

Run: `python -m pytest tests/test_api.py -k allocation_endpoint_returns_409 -q`
Expected: PASS

- [ ] **Step 5: Run full verification**

Run: `python -m pytest -q`
Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add src/aidn_hypervisor/service.py tests/test_api.py tests/test_state.py
git commit -m "feat: add allocation expiry and conflict handling"
```
