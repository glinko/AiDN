# Endpoint Runtime Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add endpoint-native synchronous execution through `POST /api/v1/endpoints/{endpoint_id}/invoke` by adapting the existing `HypervisorService` runtime and plugin substrate behind the endpoint model.

**Architecture:** Keep `EndpointService` as the endpoint-owned boundary, then inject a narrow `EndpointRuntimeAdapter` that resolves `endpoint_id -> bundle_id -> runtime -> plugin invoke`. Reuse existing `HypervisorService` readiness and invocation logic through new focused sync methods instead of routing through the task queue or auto-starting runtimes.

**Tech Stack:** `Python 3.11`, `FastAPI`, `Pydantic v2`, `pytest`, existing `HypervisorService`, existing `ProviderPlugin` registry, existing endpoint API envelope.

---

## File Structure

- Modify: `src/aidn_hypervisor/endpoints/models.py`
  Add endpoint invoke and readiness models.
- Modify: `src/aidn_hypervisor/endpoints/__init__.py`
  Export the new endpoint invoke/readiness surface.
- Create: `src/aidn_hypervisor/endpoints/runtime_adapter.py`
  Bridge endpoint manifests to legacy runtime readiness and synchronous plugin execution.
- Modify: `src/aidn_hypervisor/endpoints/service.py`
  Inject the runtime adapter and expose endpoint readiness and invoke methods.
- Modify: `src/aidn_hypervisor/service.py`
  Add focused public bundle readiness and synchronous invoke hooks that reuse existing runtime and plugin logic without queueing.
- Modify: `src/aidn_hypervisor/endpoints/api.py`
  Add `POST /api/v1/endpoints/{endpoint_id}/invoke` and endpoint-native error mapping for readiness and invoke failures.
- Modify: `src/aidn_hypervisor/main.py`
  Wire the default endpoint service to the resolved `HypervisorService` so endpoint invoke uses the same runtime substrate as legacy routes.
- Modify: `tests/endpoints/test_models.py`
  Cover invoke and readiness models.
- Create: `tests/endpoints/test_runtime_adapter.py`
  Cover adapter and service-level endpoint execution semantics.
- Modify: `tests/endpoints/test_api.py`
  Cover the new invoke route and endpoint error envelope behavior.
- Modify: `tests/test_api.py`
  Cover bootstrap coexistence with injected `HypervisorService` and legacy `/tasks`.

### Task 1: Add Endpoint Invoke And Readiness Models

**Files:**
- Modify: `src/aidn_hypervisor/endpoints/models.py`
- Modify: `src/aidn_hypervisor/endpoints/__init__.py`
- Modify: `tests/endpoints/test_models.py`

- [ ] **Step 1: Write the failing endpoint invoke model tests**

```python
from aidn_hypervisor.endpoints.models import EndpointInvokeRequest, EndpointReadiness


def test_endpoint_invoke_request_defaults_constraints() -> None:
    request = EndpointInvokeRequest(
        task_type="llm_text.generate",
        payload={"prompt": "hello"},
    )

    assert request.constraints == {}


def test_endpoint_readiness_captures_runtime_projection() -> None:
    readiness = EndpointReadiness(
        endpoint_id="ep-1",
        bundle_id="text-a",
        ready=False,
        code="endpoint_runtime_unavailable",
        message="Endpoint ep-1 has no ready runtime",
        runtime_id=None,
        runtime_status=None,
        runtime_health_status=None,
    )

    assert readiness.ready is False
    assert readiness.code == "endpoint_runtime_unavailable"
    assert readiness.bundle_id == "text-a"
```

- [ ] **Step 2: Run the focused model tests to confirm they fail**

Run: `python -m pytest tests/endpoints/test_models.py -q`

Expected: `FAIL` with missing `EndpointInvokeRequest` or `EndpointReadiness`

- [ ] **Step 3: Add the new invoke and readiness models**

```python
# src/aidn_hypervisor/endpoints/models.py
class EndpointInvokeRequest(BaseModel):
    task_type: str
    payload: dict
    constraints: dict = Field(default_factory=dict)


class EndpointReadiness(BaseModel):
    endpoint_id: str
    bundle_id: str
    ready: bool
    code: str | None = None
    message: str | None = None
    runtime_id: str | None = None
    runtime_status: str | None = None
    runtime_health_status: str | None = None


class InvokeEndpointCommand(BaseModel):
    endpoint_id: str
    task_type: str
    payload: dict
    constraints: dict = Field(default_factory=dict)


class InvokeEndpointResult(EndpointResult):
    bundle_id: str
    runtime_id: str
    readiness: EndpointReadiness
    result: dict
```

```python
# src/aidn_hypervisor/endpoints/__init__.py
from aidn_hypervisor.endpoints.models import (
    EndpointInvokeRequest,
    EndpointReadiness,
    InvokeEndpointCommand,
    InvokeEndpointResult,
)

__all__ = [
    ...,
    "EndpointInvokeRequest",
    "EndpointReadiness",
    "InvokeEndpointCommand",
    "InvokeEndpointResult",
]
```

- [ ] **Step 4: Run the model tests to verify they pass**

Run: `python -m pytest tests/endpoints/test_models.py -q`

Expected: `PASS`

- [ ] **Step 5: Commit the model slice**

```bash
git add src/aidn_hypervisor/endpoints/models.py src/aidn_hypervisor/endpoints/__init__.py tests/endpoints/test_models.py
git commit -m "feat: add endpoint invoke models"
```

### Task 2: Add The Runtime Adapter And Sync Legacy Execution Hooks

**Files:**
- Create: `src/aidn_hypervisor/endpoints/runtime_adapter.py`
- Modify: `src/aidn_hypervisor/endpoints/service.py`
- Modify: `src/aidn_hypervisor/service.py`
- Create: `tests/endpoints/test_runtime_adapter.py`

- [ ] **Step 1: Write the failing adapter and service tests**

```python
from aidn_hypervisor.endpoints.models import CreateEndpointCommand, InvokeEndpointCommand
from aidn_hypervisor.endpoints.runtime_adapter import EndpointExecutionError, EndpointRuntimeAdapter
from aidn_hypervisor.endpoints.service import EndpointService, EndpointStateError
from aidn_hypervisor.endpoints.store import EndpointStore
from aidn_hypervisor.plugins.fake import FakeManagedPlugin
from aidn_hypervisor.plugins.registry import PluginRegistry
from aidn_hypervisor.process_manager import RuntimeHandle
from aidn_hypervisor.queue import InMemoryTaskQueue
from aidn_hypervisor.resources import ResourceOrchestrator
from aidn_hypervisor.scheduler import Scheduler
from aidn_hypervisor.service import HypervisorService
from aidn_hypervisor.domain.models import BundleConfig, NodeCapacity, ResourceProfile


def _hypervisor(*, with_runtime: bool = True, bundle_enabled: bool = True) -> HypervisorService:
    plugins = PluginRegistry()
    plugins.register(FakeManagedPlugin())
    runtimes = (
        [
            RuntimeHandle(
                runtime_id="rt-1",
                bundle_id="text-a",
                command=["python", "-m", "http.server", "0"],
                status="running",
                health_status="healthy",
            )
        ]
        if with_runtime
        else []
    )
    return HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=8.0, ram_mb=16384)),
        bundles=[
            BundleConfig(
                bundle_id="text-a",
                plugin_id="fake-managed",
                provider_type="fake",
                workload_type="llm_text",
                model_id="text-a-model",
                launch_mode="managed_process",
                device_affinity="cpu",
                resource_profile=ResourceProfile(),
                warm_policy="auto",
                enabled=bundle_enabled,
            )
        ],
        plugins=plugins,
        runtimes=runtimes,
    )


def _endpoint_service(hypervisor: HypervisorService) -> EndpointService:
    adapter = EndpointRuntimeAdapter(hypervisor)
    service = EndpointService(EndpointStore(allow_in_memory=True), runtime_adapter=adapter)
    created = service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="text-a",
            bundle_hash="bundle-hash-a",
            display_name="Text Endpoint",
            model_class="llm_text",
            capabilities=["llm_text.generate"],
        )
    )
    service.start_endpoint(created.endpoint.endpoint_id)
    return service


def test_invoke_endpoint_returns_runtime_result_for_active_ready_endpoint() -> None:
    service = _endpoint_service(_hypervisor())
    endpoint = service.list_endpoints()[0]

    result = service.invoke_endpoint(
        InvokeEndpointCommand(
            endpoint_id=endpoint.endpoint_id,
            task_type="llm_text.generate",
            payload={"prompt": "hello"},
        )
    )

    assert result.runtime_id == "rt-1"
    assert result.bundle_id == "text-a"
    assert result.result == {"ok": True, "task_type": "llm_text.generate"}


def test_invoke_endpoint_rejects_non_active_endpoint() -> None:
    adapter = EndpointRuntimeAdapter(_hypervisor())
    service = EndpointService(EndpointStore(allow_in_memory=True), runtime_adapter=adapter)
    created = service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="text-a",
            bundle_hash="bundle-hash-a",
            display_name="Text Endpoint",
            model_class="llm_text",
            capabilities=["llm_text.generate"],
        )
    )

    with pytest.raises(EndpointStateError):
        service.invoke_endpoint(
            InvokeEndpointCommand(
                endpoint_id=created.endpoint.endpoint_id,
                task_type="llm_text.generate",
                payload={"prompt": "hello"},
            )
        )


def test_invoke_endpoint_returns_runtime_unavailable_when_no_runtime_exists() -> None:
    service = _endpoint_service(_hypervisor(with_runtime=False))
    endpoint = service.list_endpoints()[0]

    with pytest.raises(EndpointExecutionError) as error:
        service.invoke_endpoint(
            InvokeEndpointCommand(
                endpoint_id=endpoint.endpoint_id,
                task_type="llm_text.generate",
                payload={"prompt": "hello"},
            )
        )

    assert error.value.code == "endpoint_runtime_unavailable"
```

- [ ] **Step 2: Run the focused adapter tests to confirm they fail**

Run: `python -m pytest tests/endpoints/test_runtime_adapter.py -q`

Expected: `FAIL` with missing `EndpointRuntimeAdapter`, `EndpointExecutionError`, or `invoke_endpoint`

- [ ] **Step 3: Add focused legacy execution hooks and the endpoint runtime adapter**

```python
# src/aidn_hypervisor/service.py
def bundle_runtime_readiness(self, bundle_id: str, request: TaskRequest) -> dict:
    bundle = self._get_bundle(bundle_id)
    if not bundle.enabled:
        return {
            "ready": False,
            "code": "endpoint_bundle_unavailable",
            "message": f"Bundle is disabled: {bundle_id}",
        }
    if self._current_bundle_state(bundle.bundle_id)["drain_mode"]:
        return {
            "ready": False,
            "code": "endpoint_runtime_unavailable",
            "message": f"Bundle is draining: {bundle.bundle_id}",
        }
    if self._bundle_in_cooldown(bundle.bundle_id):
        return {
            "ready": False,
            "code": "endpoint_runtime_unavailable",
            "message": f"Bundle is in cooldown: {bundle.bundle_id}",
        }

    plugin = self._get_plugin(bundle.plugin_id)
    runtime = self._runtime_for_bundle(bundle.bundle_id)
    if runtime is None:
        return {
            "ready": False,
            "code": "endpoint_runtime_unavailable",
            "message": f"Endpoint bundle has no active runtime: {bundle.bundle_id}",
        }
    if not self._health_check_with_retry(plugin, runtime, bundle.bundle_id):
        return {
            "ready": False,
            "code": "endpoint_runtime_unhealthy",
            "message": runtime.last_error or f"Runtime is unhealthy: {bundle.bundle_id}",
        }

    estimate = plugin.estimate_resources(request, bundle, runtime)
    concurrency_limit = estimate.get("concurrency_limit")
    effective_limit = bundle.max_parallel_requests
    if concurrency_limit is not None:
        effective_limit = min(bundle.max_parallel_requests, concurrency_limit)
    if self._active_bundle_task_count(bundle.bundle_id) >= effective_limit:
        return {
            "ready": False,
            "code": "endpoint_runtime_unavailable",
            "message": f"Runtime is saturated: {bundle.bundle_id}",
        }
    return {
        "ready": True,
        "bundle": bundle,
        "plugin": plugin,
        "runtime": runtime,
    }


def invoke_bundle_sync(self, bundle_id: str, request: TaskRequest) -> tuple[RuntimeHandle, dict]:
    readiness = self.bundle_runtime_readiness(bundle_id, request)
    if not readiness["ready"]:
        raise ValueError(str(readiness["message"]))
    bundle = readiness["bundle"]
    plugin = readiness["plugin"]
    runtime = readiness["runtime"]
    estimate = plugin.estimate_resources(request, bundle, runtime)
    request_active = estimate.get("request_active", {})
    reservation_id = f"endpoint-request:{uuid4()}"
    self.resources.reserve(
        reservation_id,
        cpu=request_active.get("cpu", 0.0),
        ram_mb=request_active.get("ram_mb", 0),
        vram_mb=request_active.get("vram_mb", 0),
    )
    try:
        runtime.status = "running"
        result = self._invoke_with_retry(plugin, bundle, request, runtime)
        self._register_bundle_success(bundle.bundle_id, runtime)
        runtime.health_status = "healthy"
        runtime.last_error = None
        return runtime, result
    finally:
        self.resources.release(reservation_id)
```

```python
# src/aidn_hypervisor/endpoints/runtime_adapter.py
from aidn_hypervisor.domain.models import TaskRequest
from aidn_hypervisor.endpoints.models import (
    EndpointManifest,
    EndpointReadiness,
    InvokeEndpointCommand,
    InvokeEndpointResult,
)


class EndpointExecutionError(ValueError):
    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class EndpointRuntimeAdapter:
    def __init__(self, hypervisor_service) -> None:
        self.hypervisor_service = hypervisor_service

    def readiness(self, endpoint: EndpointManifest, request: TaskRequest) -> EndpointReadiness:
        payload = self.hypervisor_service.bundle_runtime_readiness(endpoint.bundle_id, request)
        runtime = payload.get("runtime")
        return EndpointReadiness(
            endpoint_id=endpoint.endpoint_id,
            bundle_id=endpoint.bundle_id,
            ready=bool(payload["ready"]),
            code=payload.get("code"),
            message=payload.get("message"),
            runtime_id=None if runtime is None else runtime.runtime_id,
            runtime_status=None if runtime is None else runtime.status,
            runtime_health_status=None if runtime is None else runtime.health_status,
        )

    def invoke(self, endpoint: EndpointManifest, command: InvokeEndpointCommand) -> InvokeEndpointResult:
        request = TaskRequest(
            task_type=command.task_type,
            payload=command.payload,
            mode="manual",
            bundle_override=endpoint.bundle_id,
            constraints=command.constraints,
        )
        readiness = self.readiness(endpoint, request)
        if not readiness.ready:
            raise EndpointExecutionError(
                code=str(readiness.code),
                message=str(readiness.message),
            )
        runtime, result = self.hypervisor_service.invoke_bundle_sync(
            endpoint.bundle_id,
            request,
        )
        return InvokeEndpointResult(
            endpoint=endpoint,
            bundle_id=endpoint.bundle_id,
            runtime_id=runtime.runtime_id,
            readiness=readiness.model_copy(update={"ready": True}),
            result=result,
        )
```

```python
# src/aidn_hypervisor/endpoints/service.py
class EndpointService:
    def __init__(self, store: EndpointStore, runtime_adapter=None) -> None:
        self.store = store
        self.runtime_adapter = runtime_adapter

    def endpoint_readiness(self, endpoint_id: str, command: InvokeEndpointCommand) -> EndpointReadiness:
        endpoint = self.get_endpoint(endpoint_id)
        request = command.model_copy(update={"endpoint_id": endpoint_id})
        return self.runtime_adapter.readiness(
            endpoint,
            TaskRequest(
                task_type=request.task_type,
                payload=request.payload,
                mode="manual",
                bundle_override=endpoint.bundle_id,
                constraints=request.constraints,
            ),
        )

    def invoke_endpoint(self, command: InvokeEndpointCommand) -> InvokeEndpointResult:
        endpoint = self.get_endpoint(command.endpoint_id)
        if endpoint.status != "active":
            raise EndpointStateError(
                f"Endpoint {endpoint.endpoint_id} is not active: {endpoint.status}"
            )
        if self.runtime_adapter is None:
            raise EndpointExecutionError(
                code="endpoint_runtime_unavailable",
                message="Endpoint runtime adapter is not configured",
            )
        return self.runtime_adapter.invoke(endpoint, command)
```

- [ ] **Step 4: Run the focused adapter tests**

Run: `python -m pytest tests/endpoints/test_runtime_adapter.py tests/endpoints/test_service.py -q`

Expected: `PASS`

- [ ] **Step 5: Commit the adapter slice**

```bash
git add src/aidn_hypervisor/endpoints/runtime_adapter.py src/aidn_hypervisor/endpoints/service.py src/aidn_hypervisor/service.py tests/endpoints/test_runtime_adapter.py
git commit -m "feat: add endpoint runtime adapter"
```

### Task 3: Add The Endpoint Invoke API Route

**Files:**
- Modify: `src/aidn_hypervisor/endpoints/api.py`
- Modify: `tests/endpoints/test_api.py`

- [ ] **Step 1: Write the failing endpoint invoke API tests**

```python
def test_invoke_endpoint_returns_enveloped_result_for_active_ready_endpoint() -> None:
    hypervisor = _service(with_runtime=True)
    client = TestClient(build_app(service=hypervisor))
    created = client.post(
        "/api/v1/endpoints",
        json={
            "owner_wallet": "wallet-1",
            "bundle_id": "text-a",
            "bundle_hash": "bundle-hash-a",
            "display_name": "Text Endpoint",
            "model_class": "llm_text",
            "capabilities": ["llm_text.generate"],
        },
    ).json()["data"]["endpoint"]
    client.post(f"/api/v1/endpoints/{created['endpoint_id']}/start")

    response = client.post(
        f"/api/v1/endpoints/{created['endpoint_id']}/invoke",
        json={"task_type": "llm_text.generate", "payload": {"prompt": "hello"}},
    )

    assert response.status_code == 200
    assert response.json()["error"] is None
    assert response.json()["data"]["result"] == {
        "ok": True,
        "task_type": "llm_text.generate",
    }


def test_invoke_endpoint_returns_not_active_error_for_stopped_endpoint() -> None:
    hypervisor = _service(with_runtime=True)
    client = TestClient(build_app(service=hypervisor))
    created = client.post(
        "/api/v1/endpoints",
        json={
            "owner_wallet": "wallet-1",
            "bundle_id": "text-a",
            "bundle_hash": "bundle-hash-a",
            "display_name": "Text Endpoint",
            "model_class": "llm_text",
            "capabilities": ["llm_text.generate"],
        },
    ).json()["data"]["endpoint"]

    response = client.post(
        f"/api/v1/endpoints/{created['endpoint_id']}/invoke",
        json={"task_type": "llm_text.generate", "payload": {"prompt": "hello"}},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "endpoint_not_active"
```

- [ ] **Step 2: Run the endpoint API tests to confirm they fail**

Run: `python -m pytest tests/endpoints/test_api.py -q`

Expected: `FAIL` with missing `/invoke` route or missing endpoint execution methods

- [ ] **Step 3: Add the invoke route and endpoint execution error mapping**

```python
# src/aidn_hypervisor/endpoints/api.py
from aidn_hypervisor.endpoints.models import EndpointInvokeRequest, UpdateEndpointCommand
from aidn_hypervisor.endpoints.runtime_adapter import EndpointExecutionError


@router.post("/{endpoint_id}/invoke")
async def invoke_endpoint(
    endpoint_id: str,
    command: EndpointInvokeRequest,
    request: Request,
) -> JSONResponse:
    try:
        result = service.invoke_endpoint(
            InvokeEndpointCommand(
                endpoint_id=endpoint_id,
                **command.model_dump(mode="python", exclude_unset=True),
            )
        )
    except KeyError:
        return _not_found(request, endpoint_id)
    except EndpointStateError as error:
        return _error(
            request,
            status_code=status.HTTP_409_CONFLICT,
            code="endpoint_not_active",
            message=str(error),
        )
    except EndpointExecutionError as error:
        return _error(
            request,
            status_code=status.HTTP_409_CONFLICT,
            code=error.code,
            message=error.message,
        )
    return _success(request, result.model_dump(mode="json"))
```

- [ ] **Step 4: Run the endpoint API tests**

Run: `python -m pytest tests/endpoints/test_api.py -q`

Expected: `PASS`

- [ ] **Step 5: Commit the API slice**

```bash
git add src/aidn_hypervisor/endpoints/api.py tests/endpoints/test_api.py
git commit -m "feat: add endpoint invoke route"
```

### Task 4: Wire The Adapter Through App Bootstrap And Prove Legacy Coexistence

**Files:**
- Modify: `src/aidn_hypervisor/main.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Write the failing bootstrap and coexistence tests**

```python
def test_endpoint_invoke_uses_injected_hypervisor_service_runtime() -> None:
    service = _service(with_runtime=True)
    client = TestClient(build_app(service=service))
    created = client.post(
        "/api/v1/endpoints",
        json={
            "owner_wallet": "wallet-1",
            "bundle_id": "text-a",
            "bundle_hash": "bundle-hash-a",
            "display_name": "Text Endpoint",
            "model_class": "llm_text",
            "capabilities": ["llm_text.generate"],
        },
    ).json()["data"]["endpoint"]
    client.post(f"/api/v1/endpoints/{created['endpoint_id']}/start")

    response = client.post(
        f"/api/v1/endpoints/{created['endpoint_id']}/invoke",
        json={"task_type": "llm_text.generate", "payload": {"prompt": "hello"}},
    )

    assert response.status_code == 200
    assert response.json()["data"]["runtime_id"] == "rt-1"


def test_legacy_tasks_route_still_works_after_endpoint_invoke_wiring() -> None:
    service = _service(with_runtime=True)
    client = TestClient(build_app(service=service))

    response = client.post(
        "/tasks",
        json={"task_type": "audio.transcribe", "payload": {"audio_ref": "clip.wav"}},
    )

    assert response.status_code == 202
    assert response.json()["bundle_id"] == "whisper-a"
```

- [ ] **Step 2: Run the coexistence tests to confirm they fail**

Run: `python -m pytest tests/test_api.py -k "endpoint_invoke_uses_injected_hypervisor_service_runtime or legacy_tasks_route_still_works_after_endpoint_invoke_wiring" -q`

Expected: `FAIL` because the default endpoint service is not yet adapter-backed

- [ ] **Step 3: Wire the default endpoint service to the resolved hypervisor service**

```python
# src/aidn_hypervisor/main.py
from aidn_hypervisor.endpoints.runtime_adapter import EndpointRuntimeAdapter


def build_app(
    service: HypervisorService | None = None,
    registry_service: RegistryService | None = None,
    endpoint_service: EndpointService | None = None,
) -> FastAPI:
    shared_state_store = _default_state_store()
    resolved_service = service or _build_default_service(shared_state_store)
    resolved_endpoint_service = endpoint_service or _build_default_endpoint_service(
        state_store=getattr(resolved_service, "state_store", None) or shared_state_store,
        hypervisor_service=resolved_service,
    )
    ...


def _build_default_endpoint_service(
    state_store: FileStateStore | None = None,
    hypervisor_service: HypervisorService | None = None,
) -> EndpointService:
    store = EndpointStore(state_store) if state_store is not None else EndpointStore(allow_in_memory=True)
    runtime_adapter = (
        None if hypervisor_service is None else EndpointRuntimeAdapter(hypervisor_service)
    )
    return EndpointService(store, runtime_adapter=runtime_adapter)
```

- [ ] **Step 4: Run the endpoint/legacy regression suite**

Run: `python -m pytest tests/endpoints/test_models.py tests/endpoints/test_runtime_adapter.py tests/endpoints/test_service.py tests/endpoints/test_api.py tests/test_api.py tests/test_smoke.py -q`

Expected: `PASS`

- [ ] **Step 5: Commit the bootstrap slice**

```bash
git add src/aidn_hypervisor/main.py tests/test_api.py
git commit -m "feat: wire endpoint invoke through hypervisor runtime"
```

## Self-Review Checklist

- Spec coverage:
  - endpoint-native sync invoke route: Task 3
  - runtime adapter over legacy substrate: Tasks 2 and 4
  - readiness projection and strict readiness failures: Tasks 2 and 3
  - no auto-start and no queue fallback: Task 2 tests and Task 3 API contract
  - coexistence with legacy routes: Task 4
- Placeholder scan:
  - no placeholder markers or deferred implementation notes remain in tasks
- Type consistency:
  - `EndpointInvokeRequest`, `EndpointReadiness`, `InvokeEndpointCommand`, `InvokeEndpointResult`, `EndpointRuntimeAdapter`, `EndpointExecutionError`, `bundle_runtime_readiness`, and `invoke_bundle_sync` are named consistently across all tasks
