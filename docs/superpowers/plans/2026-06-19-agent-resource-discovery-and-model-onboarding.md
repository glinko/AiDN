# Agent Resource Discovery And Model Onboarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an agent-facing discovery contract that reports usable bundles, endpoints, and resource fit, then add an operator-controlled model onboarding flow so new local models can be installed and exposed through the hypervisor.

**Architecture:** Extend the current single-node hypervisor with one new read path and one new control path. The read path computes a derived capability catalog from bundle inventory, runtime state, and resource admission checks; the control path adds explicit model install and bundle registration jobs instead of silently assuming models already exist on disk.

**Tech Stack:** `Python`, `FastAPI`, `Pydantic`, `pytest`, existing `HypervisorService`, bundle registry, resource orchestrator, process manager, plugin adapters.

---

## File Map

- Modify: `src/aidn_hypervisor/domain/models.py`
- Modify: `src/aidn_hypervisor/api.py`
- Modify: `src/aidn_hypervisor/service.py`
- Modify: `src/aidn_hypervisor/resources.py`
- Modify: `src/aidn_hypervisor/state.py`
- Modify: `src/aidn_hypervisor/process_manager.py`
- Modify: `src/aidn_hypervisor/plugins/base.py`
- Modify: `src/aidn_hypervisor/plugins/llamacpp.py`
- Modify: `src/aidn_hypervisor/plugins/ollama.py`
- Modify: `src/aidn_hypervisor/plugins/whisper.py`
- Create: `src/aidn_hypervisor/model_store.py`
- Create: `tests/test_model_store.py`
- Modify: `tests/test_service.py`
- Modify: `tests/test_api.py`
- Modify: `tests/test_state.py`

### Task 1: Agent Capability Catalog

**Files:**
- Modify: `src/aidn_hypervisor/domain/models.py`
- Modify: `src/aidn_hypervisor/service.py`
- Modify: `src/aidn_hypervisor/api.py`
- Modify: `tests/test_service.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Write the failing service tests for a derived capability catalog**

```python
def test_service_capability_catalog_reports_fit_and_endpoint_readiness() -> None:
    service = _service(
        with_runtime=False,
        use_process_manager=True,
        reserve_runtime=False,
        whisper_endpoint="http://127.0.0.1:9000",
    )

    catalog = service.capability_catalog(owner_id="agent-a")

    assert catalog["resources"]["free"]["cpu"] > 0
    assert catalog["bundles"][0]["bundle_id"] == "whisper-a"
    assert catalog["bundles"][0]["can_allocate_now"] is True
    assert catalog["bundles"][0]["allocation_mode"] == "active"
    assert catalog["bundles"][0]["endpoint"] == "http://127.0.0.1:9000"


def test_service_capability_catalog_reports_wait_when_resources_are_busy() -> None:
    service = _service(
        with_runtime=False,
        use_process_manager=True,
        reserve_runtime=False,
        whisper_endpoint="http://127.0.0.1:9000",
    )
    service.resources.reserve("busy", cpu=8.0, ram_mb=16384, vram_mb=0)

    catalog = service.capability_catalog(owner_id="agent-a")

    assert catalog["bundles"][0]["can_allocate_now"] is False
    assert catalog["bundles"][0]["can_queue"] is True
    assert catalog["bundles"][0]["reason"] == "insufficient_resources"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_service.py -k capability_catalog -q`
Expected: FAIL with missing `capability_catalog`

- [ ] **Step 3: Add catalog response models**

```python
class CapabilityProbeRequest(BaseModel):
    owner_id: str
    workload_type: str | None = None
    bundle_id: str | None = None
    include_disabled: bool = False


class CapabilityCatalogEntry(BaseModel):
    bundle_id: str
    workload_type: str
    enabled: bool
    status: str
    endpoint: str | None = None
    can_allocate_now: bool
    can_queue: bool
    allocation_mode: str
    reason: str | None = None
```

- [ ] **Step 4: Implement the catalog service method**

```python
def capability_catalog(
    self,
    *,
    owner_id: str,
    workload_type: str | None = None,
    bundle_id: str | None = None,
    include_disabled: bool = False,
) -> dict:
    self._cleanup_expired_allocations()
    self._reconcile_pending_allocations()
    bundles = self._filtered_catalog_bundles(
        workload_type=workload_type,
        bundle_id=bundle_id,
        include_disabled=include_disabled,
    )
    return {
        "resources": self.resources.summary() if self.resources is not None else _empty_resource_summary(),
        "bundles": [
            self._catalog_entry(bundle, owner_id=owner_id)
            for bundle in bundles
        ],
    }
```

- [ ] **Step 5: Expose the new agent-facing endpoint**

```python
@router.get("/agent/capabilities")
async def agent_capabilities(
    owner_id: str,
    workload_type: str | None = None,
    bundle_id: str | None = None,
    include_disabled: bool = False,
) -> dict:
    return service.capability_catalog(
        owner_id=owner_id,
        workload_type=workload_type,
        bundle_id=bundle_id,
        include_disabled=include_disabled,
    )
```

- [ ] **Step 6: Run tests to verify the service and API pass**

Run: `python -m pytest tests/test_service.py -k capability_catalog -q`
Expected: PASS

Run: `python -m pytest tests/test_api.py -k agent_capabilities -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/aidn_hypervisor/domain/models.py src/aidn_hypervisor/service.py src/aidn_hypervisor/api.py tests/test_service.py tests/test_api.py
git commit -m "feat: add agent capability catalog"
```

### Task 2: Rich Resource Fit And Admission Explanation

**Files:**
- Modify: `src/aidn_hypervisor/resources.py`
- Modify: `src/aidn_hypervisor/service.py`
- Modify: `tests/test_service.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Write the failing tests for resource-fit explanations**

```python
def test_service_capability_catalog_reports_missing_resource_delta() -> None:
    service = _service(
        with_runtime=False,
        use_process_manager=True,
        reserve_runtime=False,
        capacity=NodeCapacity(cpu_cores=2.0, ram_mb=2048, vram_mb={"gpu0": 1024}),
        whisper_profile=ResourceProfile(
            cold_start_cpu=1.0,
            cold_start_ram_mb=1024,
            steady_cpu=2.0,
            steady_ram_mb=2048,
            steady_vram_mb=512,
        ),
        whisper_endpoint="http://127.0.0.1:9000",
    )
    service.resources.reserve("busy", cpu=1.5, ram_mb=1024, vram_mb=256)

    catalog = service.capability_catalog(owner_id="agent-a")

    assert catalog["bundles"][0]["fit"]["cpu_shortfall"] == 1.5
    assert catalog["bundles"][0]["fit"]["ram_mb_shortfall"] == 1024
    assert catalog["bundles"][0]["fit"]["vram_mb_shortfall"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_service.py -k resource_delta -q`
Expected: FAIL because fit breakdown is missing

- [ ] **Step 3: Add a non-mutating fit probe to the resource orchestrator**

```python
def fit_report(self, cpu: float, ram_mb: int, vram_mb: int) -> dict[str, float | int | bool]:
    used_cpu = sum(item.cpu for item in self._reservations.values())
    used_ram = sum(item.ram_mb for item in self._reservations.values())
    used_vram = sum(item.vram_mb for item in self._reservations.values())
    total_vram = sum(self.capacity.vram_mb.values())
    return {
        "fits": used_cpu + cpu <= self.capacity.cpu_cores
        and used_ram + ram_mb <= self.capacity.ram_mb
        and used_vram + vram_mb <= total_vram,
        "cpu_shortfall": max(0.0, used_cpu + cpu - self.capacity.cpu_cores),
        "ram_mb_shortfall": max(0, used_ram + ram_mb - self.capacity.ram_mb),
        "vram_mb_shortfall": max(0, used_vram + vram_mb - total_vram),
    }
```

- [ ] **Step 4: Attach fit reports to the catalog entries**

```python
fit = self.resources.fit_report(required_cpu, required_ram_mb, required_vram_mb)
entry["fit"] = fit
entry["requires_runtime_start"] = runtime is None
entry["required"] = {
    "cpu": required_cpu,
    "ram_mb": required_ram_mb,
    "vram_mb": required_vram_mb,
}
```

- [ ] **Step 5: Run tests to verify it passes**

Run: `python -m pytest tests/test_service.py -k resource_delta -q`
Expected: PASS

Run: `python -m pytest tests/test_api.py -k agent_capabilities -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/aidn_hypervisor/resources.py src/aidn_hypervisor/service.py tests/test_service.py tests/test_api.py
git commit -m "feat: explain capability admission fit"
```

### Task 3: Operator Model Store And Install Jobs

**Files:**
- Create: `src/aidn_hypervisor/model_store.py`
- Modify: `src/aidn_hypervisor/domain/models.py`
- Modify: `src/aidn_hypervisor/service.py`
- Modify: `src/aidn_hypervisor/state.py`
- Modify: `src/aidn_hypervisor/api.py`
- Create: `tests/test_model_store.py`
- Modify: `tests/test_service.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Write the failing tests for model install requests**

```python
def test_service_register_model_install_job_tracks_requested_artifact(tmp_path) -> None:
    service = _service(model_store=FileModelStore(tmp_path))

    job = service.request_model_install(
        provider_type="llama.cpp",
        model_id="phi-4-mini.gguf",
        source_url="https://example.invalid/models/phi-4-mini.gguf",
        requested_by="operator-a",
    )

    assert job["status"] == "queued"
    assert job["model_id"] == "phi-4-mini.gguf"
    assert job["source_url"].endswith(".gguf")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_model_store.py -q`
Expected: FAIL with missing model store and install API

- [ ] **Step 3: Add model store and install job state**

```python
class FileModelStore:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def reserve_target_path(self, provider_type: str, model_id: str) -> Path:
        safe_name = model_id.replace("/", "_")
        target = self.root / provider_type / safe_name
        target.parent.mkdir(parents=True, exist_ok=True)
        return target
```

- [ ] **Step 4: Add operator endpoints for install job creation and listing**

```python
@router.post("/operators/models/install", status_code=status.HTTP_202_ACCEPTED)
async def request_model_install(request: ModelInstallRequest) -> dict:
    return service.request_model_install(**request.model_dump(mode="json"))


@router.get("/operators/models/install")
async def list_model_installs() -> list[dict]:
    return service.list_model_installs()
```

- [ ] **Step 5: Keep the first implementation intentionally narrow**

```python
def request_model_install(self, *, provider_type: str, model_id: str, source_url: str, requested_by: str) -> dict:
    install_id = str(uuid4())
    target_path = str(self.model_store.reserve_target_path(provider_type, model_id))
    job = {
        "install_id": install_id,
        "provider_type": provider_type,
        "model_id": model_id,
        "source_url": source_url,
        "target_path": target_path,
        "requested_by": requested_by,
        "status": "queued",
    }
    self._model_installs[install_id] = job
    self._persist_state()
    return dict(job)
```

- [ ] **Step 6: Run tests to verify it passes**

Run: `python -m pytest tests/test_model_store.py tests/test_service.py -k model_install -q`
Expected: PASS

Run: `python -m pytest tests/test_api.py -k models_install -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/aidn_hypervisor/model_store.py src/aidn_hypervisor/domain/models.py src/aidn_hypervisor/service.py src/aidn_hypervisor/state.py src/aidn_hypervisor/api.py tests/test_model_store.py tests/test_service.py tests/test_api.py
git commit -m "feat: add operator model install jobs"
```

### Task 4: Bundle Registration From Installed Models

**Files:**
- Modify: `src/aidn_hypervisor/service.py`
- Modify: `src/aidn_hypervisor/api.py`
- Modify: `src/aidn_hypervisor/plugins/base.py`
- Modify: `src/aidn_hypervisor/plugins/llamacpp.py`
- Modify: `src/aidn_hypervisor/plugins/ollama.py`
- Modify: `src/aidn_hypervisor/plugins/whisper.py`
- Modify: `tests/test_service.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Write the failing tests for install-to-bundle registration**

```python
def test_service_registers_bundle_from_completed_install(tmp_path) -> None:
    service = _service(model_store=FileModelStore(tmp_path))
    install = service._create_completed_install_for_test(
        provider_type="llama.cpp",
        model_id="phi-4-mini.gguf",
        target_path=str(tmp_path / "llama.cpp" / "phi-4-mini.gguf"),
    )

    bundle = service.register_bundle_from_install(
        install_id=install["install_id"],
        bundle_id="phi4-local",
        workload_type="llm_text",
        endpoint="http://127.0.0.1:8080",
    )

    assert bundle["bundle_id"] == "phi4-local"
    assert service.bundles[-1].model_id == str(tmp_path / "llama.cpp" / "phi-4-mini.gguf")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_service.py -k register_bundle_from_install -q`
Expected: FAIL because install jobs do not feed bundle registration

- [ ] **Step 3: Extend plugin contract with bundle defaults from install artifacts**

```python
def bundle_defaults_from_install(self, *, model_id: str, target_path: str) -> dict:
    return {
        "model_id": target_path,
        "launch_mode": "managed_process",
        "device_affinity": "gpu0",
    }
```

- [ ] **Step 4: Add the operator endpoint**

```python
@router.post("/operators/models/{install_id}/register-bundle")
async def register_bundle_from_install(install_id: str, request: RegisterBundleFromInstallRequest) -> dict:
    return service.register_bundle_from_install(
        install_id=install_id,
        **request.model_dump(mode="json"),
    )
```

- [ ] **Step 5: Run tests to verify it passes**

Run: `python -m pytest tests/test_service.py -k register_bundle_from_install -q`
Expected: PASS

Run: `python -m pytest tests/test_api.py -k register_bundle_from_install -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/aidn_hypervisor/service.py src/aidn_hypervisor/api.py src/aidn_hypervisor/plugins/base.py src/aidn_hypervisor/plugins/llamacpp.py src/aidn_hypervisor/plugins/ollama.py src/aidn_hypervisor/plugins/whisper.py tests/test_service.py tests/test_api.py
git commit -m "feat: register bundles from installed models"
```

### Task 5: Real Runtime Execution Boundary

**Files:**
- Modify: `src/aidn_hypervisor/process_manager.py`
- Modify: `src/aidn_hypervisor/service.py`
- Modify: `tests/test_service.py`
- Modify: `tests/test_state.py`

- [ ] **Step 1: Write the failing tests for subprocess-backed runtime handles**

```python
def test_process_manager_start_runtime_records_pid_metadata(monkeypatch) -> None:
    manager = ProviderProcessManager()

    handle = manager.start_runtime(
        {"command": ["python", "-c", "print('ok')"], "bundle_id": "text-a"}
    )

    assert handle.bundle_id == "text-a"
    assert "pid" in handle.metadata
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_service.py -k pid_metadata -q`
Expected: FAIL because runtime manager is currently in-memory only

- [ ] **Step 3: Replace the stub runtime start with an execution adapter**

```python
def start_runtime(self, launch_spec: dict) -> RuntimeHandle:
    process = subprocess.Popen(
        launch_spec["command"],
        cwd=launch_spec.get("cwd"),
        env=launch_spec.get("env"),
    )
    runtime_id = f"rt-{len(self._runtimes) + 1}"
    handle = RuntimeHandle(
        runtime_id=runtime_id,
        command=launch_spec["command"],
        status="starting",
        bundle_id=launch_spec.get("bundle_id"),
        health_status="unknown",
        metadata={**dict(launch_spec.get("metadata", {})), "pid": str(process.pid)},
    )
    self._runtimes[runtime_id] = handle
    return handle
```

- [ ] **Step 4: Guard the first real execution with explicit launch mode checks**

```python
if bundle.launch_mode != "managed_process":
    raise ValueError(f"Bundle does not support managed launch: {bundle.bundle_id}")
```

- [ ] **Step 5: Run tests to verify it passes**

Run: `python -m pytest tests/test_service.py -k "pid_metadata or allocation" -q`
Expected: PASS

Run: `python -m pytest tests/test_state.py -k runtime_recovery -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/aidn_hypervisor/process_manager.py src/aidn_hypervisor/service.py tests/test_service.py tests/test_state.py
git commit -m "feat: back runtimes with subprocess launches"
```

### Task 6: End-To-End Verification

**Files:**
- Modify: `tests/test_api.py`
- Modify: `tests/test_service.py`
- Modify: `tests/test_state.py`

- [ ] **Step 1: Add the cross-flow tests**

```python
def test_agent_can_discover_then_allocate_same_bundle() -> None:
    service = _service(
        with_runtime=False,
        use_process_manager=True,
        reserve_runtime=False,
        whisper_endpoint="http://127.0.0.1:9000",
    )

    catalog = service.capability_catalog(owner_id="agent-a")
    allocation = service.create_allocation(
        AllocationRequest(workload_type="speech_to_text", owner_id="agent-a")
    )

    assert catalog["bundles"][0]["bundle_id"] == allocation["bundle_id"]


def test_operator_can_install_register_and_expose_new_model(tmp_path) -> None:
    service = _service(model_store=FileModelStore(tmp_path))
    install = service.request_model_install(
        provider_type="llama.cpp",
        model_id="phi-4-mini.gguf",
        source_url="https://example.invalid/models/phi-4-mini.gguf",
        requested_by="operator-a",
    )
    service.mark_model_install_completed(install["install_id"])
    service.register_bundle_from_install(
        install_id=install["install_id"],
        bundle_id="phi4-local",
        workload_type="llm_text",
        endpoint="http://127.0.0.1:8080",
    )

    catalog = service.capability_catalog(owner_id="agent-a", workload_type="llm_text")

    assert catalog["bundles"][0]["bundle_id"] == "phi4-local"
```

- [ ] **Step 2: Run the focused verification**

Run: `python -m pytest tests/test_service.py -k "discover_then_allocate or install_register" -q`
Expected: PASS

Run: `python -m pytest tests/test_api.py -k "agent_capabilities or models_install" -q`
Expected: PASS

- [ ] **Step 3: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_api.py tests/test_service.py tests/test_state.py
git commit -m "test: cover discovery and onboarding flows"
```
