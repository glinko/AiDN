# Hypervisor MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a single-node Python/FastAPI hypervisor MVP with plugin-based providers, queue-backed task admission, and resource-aware scheduling for `llm_text.generate` and `audio.transcribe`.

**Architecture:** A core hypervisor process owns the API, task queue, scheduler, resource orchestrator, bundle registry, and process manager. Provider-specific behavior lives behind plugin adapters, while actual runtimes are external local processes or attached local services.

**Tech Stack:** Python, FastAPI, Pydantic, asyncio, pytest, httpx, uvicorn

---

### Task 1: Scaffold the Python package and test harness

**Files:**
- Create: `pyproject.toml`
- Create: `src/aidn_hypervisor/__init__.py`
- Create: `src/aidn_hypervisor/main.py`
- Create: `tests/conftest.py`
- Test: `tests/test_smoke.py`

- [ ] **Step 1: Write the failing smoke test**

```python
# tests/test_smoke.py
from fastapi.testclient import TestClient

from aidn_hypervisor.main import build_app


def test_health_endpoint_returns_ok() -> None:
    client = TestClient(build_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_smoke.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aidn_hypervisor'`

- [ ] **Step 3: Write minimal implementation**

```toml
# pyproject.toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "aidn-hypervisor"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["fastapi>=0.115", "pydantic>=2.8", "uvicorn>=0.30"]

[project.optional-dependencies]
dev = ["pytest>=8.2", "httpx>=0.27"]

[tool.pytest.ini_options]
pythonpath = ["src"]
```

```python
# src/aidn_hypervisor/main.py
from fastapi import FastAPI


def build_app() -> FastAPI:
    app = FastAPI(title="AiDN Hypervisor")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
```

```python
# src/aidn_hypervisor/__init__.py
__all__ = ["__version__"]
__version__ = "0.1.0"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_smoke.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/aidn_hypervisor/__init__.py src/aidn_hypervisor/main.py tests/test_smoke.py
git commit -m "feat: scaffold hypervisor package"
```

### Task 2: Define domain models for tasks, bundles, resources, and runtimes

**Files:**
- Create: `src/aidn_hypervisor/domain/models.py`
- Create: `src/aidn_hypervisor/domain/types.py`
- Test: `tests/domain/test_models.py`

- [ ] **Step 1: Write the failing domain-model tests**

```python
from aidn_hypervisor.domain.models import BundleConfig, NodeCapacity, TaskRequest


def test_task_request_defaults_to_auto_mode() -> None:
    task = TaskRequest(task_type="llm_text.generate", payload={"prompt": "hi"})
    assert task.mode == "auto"


def test_bundle_config_requires_resource_profile() -> None:
    bundle = BundleConfig.model_validate(
        {
            "bundle_id": "phi4-ollama",
            "plugin_id": "ollama",
            "provider_type": "ollama",
            "workload_type": "llm_text",
            "model_id": "phi4",
            "launch_mode": "attached_service",
            "endpoint": "http://localhost:11434",
            "device_affinity": "cpu",
            "resource_profile": {"steady_ram_mb": 4096, "per_request_ram_mb": 256},
            "warm_policy": "auto",
            "priority_class": 50,
            "max_parallel_requests": 2,
            "enabled": True,
        }
    )
    assert bundle.bundle_id == "phi4-ollama"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/domain/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError` for `aidn_hypervisor.domain`

- [ ] **Step 3: Write minimal implementation**

```python
# src/aidn_hypervisor/domain/types.py
from typing import Literal

TaskMode = Literal["manual", "auto"]
WarmPolicy = Literal["always", "auto", "never"]
LaunchMode = Literal["managed_process", "attached_service"]
TaskStatus = Literal["queued", "admitted", "starting", "running", "completed", "failed", "cancelled"]
```

```python
# src/aidn_hypervisor/domain/models.py
from pydantic import BaseModel, Field

from aidn_hypervisor.domain.types import LaunchMode, TaskMode, WarmPolicy


class ResourceProfile(BaseModel):
    cold_start_cpu: float = 0.0
    cold_start_ram_mb: int = 0
    cold_start_vram_mb: int = 0
    steady_cpu: float = 0.0
    steady_ram_mb: int = 0
    steady_vram_mb: int = 0
    per_request_cpu: float = 0.0
    per_request_ram_mb: int = 0
    per_request_vram_mb: int = 0


class BundleConfig(BaseModel):
    bundle_id: str
    plugin_id: str
    provider_type: str
    workload_type: str
    model_id: str
    launch_mode: LaunchMode
    endpoint: str | None = None
    device_affinity: str
    resource_profile: ResourceProfile
    warm_policy: WarmPolicy
    priority_class: int = 50
    max_parallel_requests: int = 1
    enabled: bool = True


class TaskRequest(BaseModel):
    task_type: str
    payload: dict
    mode: TaskMode = "auto"
    bundle_override: str | None = None
    priority: int = 50
    constraints: dict = Field(default_factory=dict)


class NodeCapacity(BaseModel):
    cpu_cores: float
    ram_mb: int
    gpu_devices: list[str] = Field(default_factory=list)
    vram_mb: dict[str, int] = Field(default_factory=dict)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/domain/test_models.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aidn_hypervisor/domain tests/domain/test_models.py
git commit -m "feat: add hypervisor domain models"
```

### Task 3: Add the plugin contract, registry, and a fake test plugin

**Files:**
- Create: `src/aidn_hypervisor/plugins/base.py`
- Create: `src/aidn_hypervisor/plugins/registry.py`
- Create: `src/aidn_hypervisor/plugins/fake.py`
- Test: `tests/plugins/test_registry.py`

- [ ] **Step 1: Write the failing plugin tests**

```python
from aidn_hypervisor.plugins.fake import FakeManagedPlugin
from aidn_hypervisor.plugins.registry import PluginRegistry


def test_registry_returns_registered_plugin() -> None:
    registry = PluginRegistry()
    plugin = FakeManagedPlugin()

    registry.register(plugin)

    assert registry.get("fake-managed") is plugin
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/plugins/test_registry.py -v`
Expected: FAIL because `PluginRegistry` and `FakeManagedPlugin` do not exist

- [ ] **Step 3: Write minimal implementation**

```python
# src/aidn_hypervisor/plugins/base.py
from abc import ABC, abstractmethod


class ProviderPlugin(ABC):
    plugin_id: str

    @abstractmethod
    def describe(self) -> dict:
        raise NotImplementedError

    @abstractmethod
    def validate_bundle(self, bundle_config) -> None:
        raise NotImplementedError

    @abstractmethod
    def estimate_resources(self, task, bundle_config, runtime_state) -> dict:
        raise NotImplementedError

    @abstractmethod
    def build_launch_spec(self, bundle_config) -> dict:
        raise NotImplementedError

    @abstractmethod
    def health_check(self, runtime_handle) -> bool:
        raise NotImplementedError

    @abstractmethod
    def invoke(self, task, runtime_handle) -> dict:
        raise NotImplementedError

    @abstractmethod
    def stop(self, runtime_handle) -> None:
        raise NotImplementedError
```

```python
# src/aidn_hypervisor/plugins/registry.py
from aidn_hypervisor.plugins.base import ProviderPlugin


class PluginRegistry:
    def __init__(self) -> None:
        self._plugins: dict[str, ProviderPlugin] = {}

    def register(self, plugin: ProviderPlugin) -> None:
        self._plugins[plugin.plugin_id] = plugin

    def get(self, plugin_id: str) -> ProviderPlugin:
        return self._plugins[plugin_id]
```

```python
# src/aidn_hypervisor/plugins/fake.py
from aidn_hypervisor.plugins.base import ProviderPlugin


class FakeManagedPlugin(ProviderPlugin):
    plugin_id = "fake-managed"

    def describe(self) -> dict:
        return {"plugin_id": self.plugin_id, "workload_types": ["llm_text", "speech_to_text"]}

    def validate_bundle(self, bundle_config) -> None:
        return None

    def estimate_resources(self, task, bundle_config, runtime_state) -> dict:
        return {"startup_transient": {}, "runtime_resident": {}, "request_active": {}}

    def build_launch_spec(self, bundle_config) -> dict:
        return {"command": ["python", "-m", "http.server", "0"]}

    def health_check(self, runtime_handle) -> bool:
        return True

    def invoke(self, task, runtime_handle) -> dict:
        return {"ok": True, "task_type": task.task_type}

    def stop(self, runtime_handle) -> None:
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/plugins/test_registry.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aidn_hypervisor/plugins tests/plugins/test_registry.py
git commit -m "feat: add provider plugin registry"
```

### Task 4: Implement the resource orchestrator with reservations and release

**Files:**
- Create: `src/aidn_hypervisor/resources.py`
- Test: `tests/test_resources.py`

- [ ] **Step 1: Write the failing resource tests**

```python
from aidn_hypervisor.domain.models import NodeCapacity
from aidn_hypervisor.resources import ResourceOrchestrator


def test_reserve_rejects_request_that_exceeds_ram() -> None:
    orchestrator = ResourceOrchestrator(NodeCapacity(cpu_cores=8, ram_mb=4096, gpu_devices=[], vram_mb={}))

    admitted = orchestrator.can_fit(cpu=1.0, ram_mb=8192, vram_mb=0)

    assert admitted is False


def test_reserve_then_release_restores_capacity() -> None:
    orchestrator = ResourceOrchestrator(NodeCapacity(cpu_cores=8, ram_mb=4096, gpu_devices=["gpu0"], vram_mb={"gpu0": 2048}))

    reservation = orchestrator.reserve("task-1", cpu=2.0, ram_mb=1024, vram_mb=512)
    orchestrator.release(reservation.reservation_id)

    assert orchestrator.can_fit(cpu=8.0, ram_mb=4096, vram_mb=2048) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_resources.py -v`
Expected: FAIL because `ResourceOrchestrator` does not exist

- [ ] **Step 3: Write minimal implementation**

```python
# src/aidn_hypervisor/resources.py
from dataclasses import dataclass

from aidn_hypervisor.domain.models import NodeCapacity


@dataclass
class Reservation:
    reservation_id: str
    cpu: float
    ram_mb: int
    vram_mb: int


class ResourceOrchestrator:
    def __init__(self, capacity: NodeCapacity) -> None:
        self.capacity = capacity
        self._reservations: dict[str, Reservation] = {}

    def can_fit(self, cpu: float, ram_mb: int, vram_mb: int) -> bool:
        used_cpu = sum(item.cpu for item in self._reservations.values())
        used_ram = sum(item.ram_mb for item in self._reservations.values())
        used_vram = sum(item.vram_mb for item in self._reservations.values())
        return (
            used_cpu + cpu <= self.capacity.cpu_cores
            and used_ram + ram_mb <= self.capacity.ram_mb
            and used_vram + vram_mb <= sum(self.capacity.vram_mb.values())
        )

    def reserve(self, reservation_id: str, cpu: float, ram_mb: int, vram_mb: int) -> Reservation:
        if not self.can_fit(cpu=cpu, ram_mb=ram_mb, vram_mb=vram_mb):
            raise ValueError("insufficient resources")
        reservation = Reservation(reservation_id=reservation_id, cpu=cpu, ram_mb=ram_mb, vram_mb=vram_mb)
        self._reservations[reservation_id] = reservation
        return reservation

    def release(self, reservation_id: str) -> None:
        self._reservations.pop(reservation_id, None)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_resources.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aidn_hypervisor/resources.py tests/test_resources.py
git commit -m "feat: add resource admission checks"
```

### Task 5: Build the in-memory queue and task state transitions

**Files:**
- Create: `src/aidn_hypervisor/queue.py`
- Test: `tests/test_queue.py`

- [ ] **Step 1: Write the failing queue tests**

```python
from aidn_hypervisor.domain.models import TaskRequest
from aidn_hypervisor.queue import InMemoryTaskQueue


def test_queue_orders_by_priority_then_fifo() -> None:
    queue = InMemoryTaskQueue()
    low = queue.enqueue(TaskRequest(task_type="llm_text.generate", payload={"prompt": "a"}, priority=10))
    high = queue.enqueue(TaskRequest(task_type="llm_text.generate", payload={"prompt": "b"}, priority=90))

    next_task = queue.peek_next()

    assert next_task.task_id == high.task_id
    assert next_task.task_id != low.task_id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_queue.py -v`
Expected: FAIL because `InMemoryTaskQueue` does not exist

- [ ] **Step 3: Write minimal implementation**

```python
# src/aidn_hypervisor/queue.py
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4

from aidn_hypervisor.domain.models import TaskRequest


@dataclass(order=True)
class QueuedTask:
    sort_key: tuple[int, str] = field(init=False, repr=False)
    priority: int
    created_at: str
    task_id: str
    request: TaskRequest
    status: str = "queued"

    def __post_init__(self) -> None:
        self.sort_key = (-self.priority, self.created_at)


class InMemoryTaskQueue:
    def __init__(self) -> None:
        self._tasks: list[QueuedTask] = []

    def enqueue(self, request: TaskRequest) -> QueuedTask:
        task = QueuedTask(
            priority=request.priority,
            created_at=datetime.now(timezone.utc).isoformat(),
            task_id=str(uuid4()),
            request=request,
        )
        self._tasks.append(task)
        self._tasks.sort(key=lambda item: item.sort_key)
        return task

    def peek_next(self) -> QueuedTask | None:
        return self._tasks[0] if self._tasks else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_queue.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aidn_hypervisor/queue.py tests/test_queue.py
git commit -m "feat: add in-memory task queue"
```

### Task 6: Implement the process manager and runtime handles

**Files:**
- Create: `src/aidn_hypervisor/process_manager.py`
- Test: `tests/test_process_manager.py`

- [ ] **Step 1: Write the failing process-manager tests**

```python
from aidn_hypervisor.process_manager import ProviderProcessManager


def test_start_runtime_returns_handle() -> None:
    manager = ProviderProcessManager()

    handle = manager.start_runtime({"command": ["python", "-c", "print('ready')"]})

    assert handle.command == ["python", "-c", "print('ready')"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_process_manager.py -v`
Expected: FAIL because `ProviderProcessManager` does not exist

- [ ] **Step 3: Write minimal implementation**

```python
# src/aidn_hypervisor/process_manager.py
from dataclasses import dataclass


@dataclass
class RuntimeHandle:
    runtime_id: str
    command: list[str]
    status: str


class ProviderProcessManager:
    def __init__(self) -> None:
        self._runtimes: dict[str, RuntimeHandle] = {}

    def start_runtime(self, launch_spec: dict) -> RuntimeHandle:
        runtime_id = f"rt-{len(self._runtimes) + 1}"
        handle = RuntimeHandle(runtime_id=runtime_id, command=launch_spec["command"], status="starting")
        self._runtimes[runtime_id] = handle
        return handle
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_process_manager.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aidn_hypervisor/process_manager.py tests/test_process_manager.py
git commit -m "feat: add provider process manager"
```

### Task 7: Add the scheduler and service layer for manual and automatic routing

**Files:**
- Create: `src/aidn_hypervisor/scheduler.py`
- Create: `src/aidn_hypervisor/service.py`
- Test: `tests/test_scheduler.py`
- Test: `tests/test_service.py`

- [ ] **Step 1: Write the failing scheduler tests**

```python
from aidn_hypervisor.domain.models import BundleConfig, ResourceProfile, TaskRequest
from aidn_hypervisor.scheduler import Scheduler


def test_scheduler_prefers_explicit_bundle_override() -> None:
    bundle = BundleConfig(
        bundle_id="whisper-a",
        plugin_id="fake-managed",
        provider_type="fake",
        workload_type="speech_to_text",
        model_id="whisper-small",
        launch_mode="managed_process",
        device_affinity="cpu",
        resource_profile=ResourceProfile(),
        warm_policy="auto",
        enabled=True,
    )
    scheduler = Scheduler()

    selected = scheduler.select_bundle(
        TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip.wav"}, mode="manual", bundle_override="whisper-a"),
        [bundle],
    )

    assert selected.bundle_id == "whisper-a"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_scheduler.py -v`
Expected: FAIL because `Scheduler` does not exist

- [ ] **Step 3: Write minimal implementation**

```python
# src/aidn_hypervisor/scheduler.py
from aidn_hypervisor.domain.models import BundleConfig, TaskRequest


class Scheduler:
    def select_bundle(self, request: TaskRequest, bundles: list[BundleConfig]) -> BundleConfig:
        if request.bundle_override:
            for bundle in bundles:
                if bundle.bundle_id == request.bundle_override:
                    return bundle
        compatible = [bundle for bundle in bundles if bundle.enabled]
        return sorted(compatible, key=lambda bundle: bundle.priority_class, reverse=True)[0]
```

```python
# src/aidn_hypervisor/service.py
from aidn_hypervisor.domain.models import TaskRequest
from aidn_hypervisor.queue import InMemoryTaskQueue
from aidn_hypervisor.scheduler import Scheduler


class HypervisorService:
    def __init__(self, queue: InMemoryTaskQueue, scheduler: Scheduler, resources=None, bundles=None, plugins=None, runtimes=None) -> None:
        self.queue = queue
        self.scheduler = scheduler
        self.resources = resources
        self.bundles = bundles or []
        self.plugins = plugins or []
        self.runtimes = runtimes or []

    def submit(self, request: TaskRequest):
        return self.queue.enqueue(request)

    def queue_snapshot(self) -> list[dict]:
        return [
            {"task_id": task.task_id, "status": task.status, "priority": task.priority}
            for task in self.queue._tasks
        ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_scheduler.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aidn_hypervisor/scheduler.py src/aidn_hypervisor/service.py tests/test_scheduler.py
git commit -m "feat: add bundle scheduler"
```

### Task 8: Expose FastAPI endpoints for health, tasks, queue, bundles, runtimes, resources, and plugins

**Files:**
- Modify: `src/aidn_hypervisor/main.py`
- Create: `src/aidn_hypervisor/api.py`
- Test: `tests/api/test_tasks_api.py`

- [ ] **Step 1: Write the failing API tests**

```python
from fastapi.testclient import TestClient

from aidn_hypervisor.main import build_app


def test_post_tasks_returns_accepted_task() -> None:
    client = TestClient(build_app())

    response = client.post("/tasks", json={"task_type": "llm_text.generate", "payload": {"prompt": "hello"}})

    assert response.status_code == 202
    assert response.json()["status"] == "queued"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/api/test_tasks_api.py -v`
Expected: FAIL with `404 != 202`

- [ ] **Step 3: Write minimal implementation**

```python
# src/aidn_hypervisor/api.py
from fastapi import APIRouter, HTTPException

from aidn_hypervisor.domain.models import TaskRequest


def build_router(service) -> APIRouter:
    router = APIRouter()

    @router.post("/tasks", status_code=202)
    async def create_task(request: TaskRequest) -> dict:
        task = service.submit(request)
        return {"task_id": task.task_id, "status": task.status}

    @router.get("/queue")
    async def get_queue() -> list[dict]:
        return service.queue_snapshot()

    @router.get("/bundles")
    async def get_bundles() -> list:
        return service.bundles

    @router.get("/runtimes")
    async def get_runtimes() -> list:
        return service.runtimes

    @router.get("/resources")
    async def get_resources() -> dict:
        if service.resources is None:
            return {"configured": False}
        return {
            "cpu_cores": service.resources.capacity.cpu_cores,
            "ram_mb": service.resources.capacity.ram_mb,
            "gpu_devices": service.resources.capacity.gpu_devices,
            "vram_mb": service.resources.capacity.vram_mb,
        }

    @router.get("/plugins")
    async def get_plugins() -> list:
        return service.plugins

    return router
```

```python
# src/aidn_hypervisor/main.py
from fastapi import FastAPI

from aidn_hypervisor.api import build_router
from aidn_hypervisor.domain.models import NodeCapacity
from aidn_hypervisor.queue import InMemoryTaskQueue
from aidn_hypervisor.resources import ResourceOrchestrator
from aidn_hypervisor.scheduler import Scheduler
from aidn_hypervisor.service import HypervisorService


def build_app() -> FastAPI:
    app = FastAPI(title="AiDN Hypervisor")
    resources = ResourceOrchestrator(NodeCapacity(cpu_cores=8, ram_mb=16384, gpu_devices=[], vram_mb={}))
    service = HypervisorService(queue=InMemoryTaskQueue(), scheduler=Scheduler(), resources=resources)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(build_router(service))
    return app
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/api/test_tasks_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aidn_hypervisor/main.py src/aidn_hypervisor/api.py tests/api/test_tasks_api.py
git commit -m "feat: expose hypervisor task api"
```

### Task 9: Add real provider adapter skeletons for `llama.cpp`, `Ollama`, and `Whisper`

**Files:**
- Create: `src/aidn_hypervisor/plugins/llamacpp.py`
- Create: `src/aidn_hypervisor/plugins/ollama.py`
- Create: `src/aidn_hypervisor/plugins/whisper.py`
- Test: `tests/plugins/test_contracts.py`

- [ ] **Step 1: Write the failing plugin-contract tests**

```python
from aidn_hypervisor.plugins.llamacpp import LlamaCppPlugin
from aidn_hypervisor.plugins.ollama import OllamaPlugin
from aidn_hypervisor.plugins.whisper import WhisperPlugin


def test_all_builtin_plugins_expose_workload_types() -> None:
    plugins = [LlamaCppPlugin(), OllamaPlugin(), WhisperPlugin()]

    for plugin in plugins:
        description = plugin.describe()
        assert description["plugin_id"]
        assert description["workload_types"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/plugins/test_contracts.py -v`
Expected: FAIL because built-in plugins do not exist

- [ ] **Step 3: Write minimal implementation**

```python
# src/aidn_hypervisor/plugins/ollama.py
from aidn_hypervisor.plugins.base import ProviderPlugin


class OllamaPlugin(ProviderPlugin):
    plugin_id = "ollama"

    def describe(self) -> dict:
        return {"plugin_id": self.plugin_id, "provider_type": "ollama", "workload_types": ["llm_text"]}

    def validate_bundle(self, bundle_config) -> None:
        return None

    def estimate_resources(self, task, bundle_config, runtime_state) -> dict:
        return {"startup_transient": {}, "runtime_resident": {}, "request_active": {}}

    def build_launch_spec(self, bundle_config) -> dict:
        return {"endpoint": bundle_config.endpoint}

    def health_check(self, runtime_handle) -> bool:
        return True

    def invoke(self, task, runtime_handle) -> dict:
        return {"provider": self.plugin_id, "task_type": task.task_type}

    def stop(self, runtime_handle) -> None:
        return None
```

```python
# src/aidn_hypervisor/plugins/llamacpp.py
from aidn_hypervisor.plugins.base import ProviderPlugin


class LlamaCppPlugin(ProviderPlugin):
    plugin_id = "llamacpp"

    def describe(self) -> dict:
        return {"plugin_id": self.plugin_id, "provider_type": "llama.cpp", "workload_types": ["llm_text"]}

    def validate_bundle(self, bundle_config) -> None:
        return None

    def estimate_resources(self, task, bundle_config, runtime_state) -> dict:
        return {"startup_transient": {}, "runtime_resident": {}, "request_active": {}}

    def build_launch_spec(self, bundle_config) -> dict:
        return {"command": ["llama-server", "--model", bundle_config.model_id]}

    def health_check(self, runtime_handle) -> bool:
        return True

    def invoke(self, task, runtime_handle) -> dict:
        return {"provider": self.plugin_id, "task_type": task.task_type}

    def stop(self, runtime_handle) -> None:
        return None
```

```python
# src/aidn_hypervisor/plugins/whisper.py
from aidn_hypervisor.plugins.base import ProviderPlugin


class WhisperPlugin(ProviderPlugin):
    plugin_id = "whisper"

    def describe(self) -> dict:
        return {"plugin_id": self.plugin_id, "provider_type": "whisper", "workload_types": ["speech_to_text"]}

    def validate_bundle(self, bundle_config) -> None:
        return None

    def estimate_resources(self, task, bundle_config, runtime_state) -> dict:
        return {"startup_transient": {}, "runtime_resident": {}, "request_active": {}}

    def build_launch_spec(self, bundle_config) -> dict:
        return {"command": ["whisper-server", "--model", bundle_config.model_id]}

    def health_check(self, runtime_handle) -> bool:
        return True

    def invoke(self, task, runtime_handle) -> dict:
        return {"provider": self.plugin_id, "task_type": task.task_type}

    def stop(self, runtime_handle) -> None:
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/plugins/test_contracts.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aidn_hypervisor/plugins/llamacpp.py src/aidn_hypervisor/plugins/ollama.py src/aidn_hypervisor/plugins/whisper.py tests/plugins/test_contracts.py
git commit -m "feat: add built-in provider plugins"
```

### Task 10: Add persistence, integration tests, and end-to-end scheduling flow

**Files:**
- Create: `src/aidn_hypervisor/storage.py`
- Modify: `src/aidn_hypervisor/service.py`
- Test: `tests/integration/test_end_to_end.py`
- Test: `tests/integration/test_queue_under_pressure.py`

- [ ] **Step 1: Write the failing integration test**

```python
from aidn_hypervisor.domain.models import NodeCapacity, TaskRequest
from aidn_hypervisor.queue import InMemoryTaskQueue
from aidn_hypervisor.resources import ResourceOrchestrator
from aidn_hypervisor.scheduler import Scheduler
from aidn_hypervisor.service import HypervisorService


def test_second_task_waits_when_resources_are_full() -> None:
    queue = InMemoryTaskQueue()
    resources = ResourceOrchestrator(NodeCapacity(cpu_cores=8, ram_mb=4096, gpu_devices=["gpu0"], vram_mb={"gpu0": 4096}))
    service = HypervisorService(queue=queue, scheduler=Scheduler(), resources=resources, bundles=[])

    first = service.submit(TaskRequest(task_type="llm_text.generate", payload={"prompt": "a"}, priority=60))
    second = service.submit(TaskRequest(task_type="llm_text.generate", payload={"prompt": "b"}, priority=50))

    snapshot = service.queue_snapshot()

    assert snapshot[0]["task_id"] == first.task_id
    assert any(item["task_id"] == second.task_id and item["status"] == "queued" for item in snapshot)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/integration/test_queue_under_pressure.py -v`
Expected: FAIL because `HypervisorService` does not yet admit one task and leave the next queued under resource pressure

- [ ] **Step 3: Write minimal implementation**

```python
# src/aidn_hypervisor/storage.py
from pathlib import Path
import json


class JsonFileStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def write_json(self, name: str, payload: dict) -> None:
        (self.root / name).write_text(json.dumps(payload, indent=2), encoding="utf-8")
```

```python
# src/aidn_hypervisor/service.py
from aidn_hypervisor.domain.models import TaskRequest


class HypervisorService:
    def __init__(self, queue, scheduler, resources, bundles) -> None:
        self.queue = queue
        self.scheduler = scheduler
        self.resources = resources
        self.bundles = bundles

    def submit(self, request: TaskRequest):
        task = self.queue.enqueue(request)
        if self.resources.can_fit(cpu=1.0, ram_mb=2048, vram_mb=0):
            self.resources.reserve(task.task_id, cpu=1.0, ram_mb=2048, vram_mb=0)
            task.status = "admitted"
        return task

    def queue_snapshot(self) -> list[dict]:
        return [{"task_id": task.task_id, "status": task.status, "priority": task.priority} for task in self.queue._tasks]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/integration -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aidn_hypervisor/storage.py src/aidn_hypervisor/service.py tests/integration
git commit -m "feat: add scheduling integration coverage"
```

### Task 11: Final verification and operator documentation

**Files:**
- Create: `README.md`
- Create: `configs/bundles.example.json`
- Test: `tests/test_smoke.py`

- [ ] **Step 1: Write the failing documentation smoke check**

```python
from pathlib import Path


def test_readme_mentions_required_endpoints() -> None:
    text = Path("README.md").read_text(encoding="utf-8")
    assert "/tasks" in text
    assert "/resources" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_smoke.py::test_readme_mentions_required_endpoints -v`
Expected: FAIL with `FileNotFoundError: README.md`

- [ ] **Step 3: Write minimal implementation**

````markdown
# README.md

## Run

```bash
pip install -e .[dev]
uvicorn aidn_hypervisor.main:build_app --factory --reload
```

## API

- `POST /tasks`
- `GET /tasks/{task_id}`
- `GET /queue`
- `GET /bundles`
- `GET /runtimes`
- `GET /resources`
````

```json
// configs/bundles.example.json
[
  {
    "bundle_id": "phi4-ollama",
    "plugin_id": "ollama",
    "provider_type": "ollama",
    "workload_type": "llm_text",
    "model_id": "phi4",
    "launch_mode": "attached_service",
    "endpoint": "http://localhost:11434",
    "device_affinity": "cpu",
    "resource_profile": {"steady_ram_mb": 4096, "per_request_ram_mb": 256},
    "warm_policy": "auto",
    "priority_class": 50,
    "max_parallel_requests": 2,
    "enabled": true
  }
]
```

- [ ] **Step 4: Run the full suite**

Run: `python -m pytest -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add README.md configs/bundles.example.json
git commit -m "docs: add hypervisor operator guide"
```
