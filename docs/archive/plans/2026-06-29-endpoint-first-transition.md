# Endpoint-First Transition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new endpoint-centric bounded context to `AiDN/main` with endpoint manifests, configuration snapshots, and a versioned `/api/v1/endpoints` API while keeping the legacy hypervisor routes and execution substrate intact. This is the first endpoint-facing implementation step behind the operator journey defined in [UX-0001 Hypervisor Operator Journey](../../product/UX-0001-hypervisor-operator-journey.md).

**Architecture:** Implement a parallel `endpoints/` package rather than rewriting the current bundle-centric services. The new `EndpointService` owns endpoint lifecycle and snapshot history, persists through the existing root state snapshot, and is exposed through a new versioned API router. Runtime, scheduler, wallet, and registry behavior stay in the legacy `HypervisorService` for this milestone. Publication and validation should remain separate concerns in the endpoint contract even before full validation workflows are implemented.

**Tech Stack:** `Python 3.11`, `FastAPI`, `Pydantic v2`, `pytest`, existing `FileStateStore`, existing `HypervisorStateSnapshot`, existing `build_app()` bootstrap.

---

## File Structure

- Create: `src/aidn_hypervisor/endpoints/__init__.py`
  Export the new endpoint package surface.
- Create: `src/aidn_hypervisor/endpoints/models.py`
  Define endpoint manifest, configuration snapshot, command, and result models.
- Create: `src/aidn_hypervisor/endpoints/state.py`
  Define snapshot records persisted inside the root hypervisor state file.
- Create: `src/aidn_hypervisor/endpoints/store.py`
  Provide snapshot-backed endpoint persistence on top of `FileStateStore`.
- Create: `src/aidn_hypervisor/endpoints/service.py`
  Implement endpoint lifecycle, snapshot creation, and state transition rules.
- Create: `src/aidn_hypervisor/endpoints/api.py`
  Expose `/api/v1/endpoints` CRUD and lifecycle routes with a deterministic envelope.
- Modify: `src/aidn_hypervisor/state.py`
  Extend `HypervisorStateSnapshot` with endpoint collections.
- Modify: `src/aidn_hypervisor/main.py`
  Wire the new endpoint router and default endpoint service into app bootstrap.
- Create: `tests/endpoints/test_models.py`
  Validate endpoint model defaults and shape.
- Create: `tests/endpoints/test_store.py`
  Validate endpoint persistence and coexistence with legacy snapshot fields.
- Create: `tests/endpoints/test_service.py`
  Validate lifecycle, snapshot creation, and state transitions.
- Create: `tests/endpoints/test_api.py`
  Validate versioned endpoint routes and response envelopes.
- Modify: `tests/test_persistence.py`
  Validate default bootstrap and shared state-file behavior.

### Task 1: Add Endpoint Models And Snapshot Records

**Files:**
- Create: `src/aidn_hypervisor/endpoints/__init__.py`
- Create: `src/aidn_hypervisor/endpoints/models.py`
- Create: `src/aidn_hypervisor/endpoints/state.py`
- Create: `tests/endpoints/test_models.py`
- Modify: `src/aidn_hypervisor/state.py`

- [ ] **Step 1: Write the failing endpoint model tests**

```python
import pytest
from pydantic import ValidationError

from aidn_hypervisor.endpoints.models import (
    CreateEndpointCommand,
    EndpointConfigurationSnapshot,
    EndpointManifest,
    EndpointPricing,
    EndpointPublicationPolicy,
    EndpointRuntimeConfig,
)


def test_endpoint_manifest_defaults_to_created_status() -> None:
    manifest = EndpointManifest(
        endpoint_id="ep-1",
        owner_wallet="wallet-1",
        created_at="2026-06-29T00:00:00+00:00",
        bundle_id="bundle-a",
        bundle_hash="bundle-hash-a",
        configuration_hash="cfg-a",
        display_name="Operator STT",
        model_class="speech.stt",
        capabilities=["speech.stt"],
    )

    assert manifest.status == "created"
    assert manifest.publication.visibility == "private"
    assert manifest.pricing.billing_unit == "request"


def test_create_endpoint_command_requires_bundle_identity() -> None:
    with pytest.raises(ValidationError):
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            display_name="Operator STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
        )


def test_configuration_snapshot_requires_bundle_hash() -> None:
    with pytest.raises(ValidationError):
        EndpointConfigurationSnapshot(
            configuration_hash="cfg-a",
            endpoint_id="ep-1",
            created_at="2026-06-29T00:00:00+00:00",
            runtime=EndpointRuntimeConfig(streaming=True, timeout=30),
            publication=EndpointPublicationPolicy(discoverable=True),
            execution_config={"streaming": True, "timeout": 30},
        )
```

- [ ] **Step 2: Run the focused model tests to confirm they fail**

Run: `python -m pytest tests/endpoints/test_models.py -q`

Expected: `FAIL` with `ModuleNotFoundError: No module named 'aidn_hypervisor.endpoints'`

- [ ] **Step 3: Add the endpoint domain models and persisted snapshot records**

```python
# src/aidn_hypervisor/endpoints/models.py
from typing import Literal

from pydantic import BaseModel, Field

EndpointStatus = Literal["created", "stopped", "active", "suspended", "deleted"]
EndpointVisibility = Literal["public", "private"]
EndpointValidationMode = Literal["enabled", "disabled"]
EndpointVerificationStatus = Literal["unsupported", "pending", "active", "suspended"]


class EndpointProfile(BaseModel):
    summary: str | None = None
    strengths: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    recommended_tasks: list[str] = Field(default_factory=list)
    supported_languages: list[str] = Field(default_factory=list)
    preferred_formats: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)


class EndpointRuntimeConfig(BaseModel):
    context_length: int | None = Field(default=None, ge=1)
    temperature: float | None = Field(default=None, ge=0.0)
    top_p: float | None = Field(default=None, ge=0.0, le=1.0)
    top_k: int | None = Field(default=None, ge=1)
    max_tokens: int | None = Field(default=None, ge=1)
    streaming: bool = False
    timeout: int | None = Field(default=None, ge=1)


class EndpointPublicationPolicy(BaseModel):
    visibility: EndpointVisibility = "private"
    discoverable: bool = False
    validation: EndpointValidationMode = "disabled"
    accepts_external_requests: bool = False


class EndpointPricing(BaseModel):
    billing_unit: str = "request"
    input_price: float | None = Field(default=None, ge=0.0)
    output_price: float | None = Field(default=None, ge=0.0)
    fixed_price: float | None = Field(default=None, ge=0.0)


class EndpointValidationState(BaseModel):
    enabled: bool = False
    model_class_supported: bool = False
    verification_status: EndpointVerificationStatus = "unsupported"
    validation_profile: str | None = None


class EndpointManifest(BaseModel):
    endpoint_id: str
    owner_wallet: str
    created_at: str
    bundle_id: str
    bundle_hash: str
    configuration_hash: str
    display_name: str
    model_class: str
    capabilities: list[str] = Field(default_factory=list)
    profile: EndpointProfile = Field(default_factory=EndpointProfile)
    runtime: EndpointRuntimeConfig = Field(default_factory=EndpointRuntimeConfig)
    publication: EndpointPublicationPolicy = Field(default_factory=EndpointPublicationPolicy)
    pricing: EndpointPricing = Field(default_factory=EndpointPricing)
    validation: EndpointValidationState = Field(default_factory=EndpointValidationState)
    status: EndpointStatus = "created"


class EndpointConfigurationSnapshot(BaseModel):
    configuration_hash: str
    endpoint_id: str
    bundle_hash: str
    created_at: str
    runtime: EndpointRuntimeConfig
    publication: EndpointPublicationPolicy
    execution_config: dict[str, bool | int | str | None] = Field(default_factory=dict)


class CreateEndpointCommand(BaseModel):
    owner_wallet: str
    bundle_id: str
    bundle_hash: str
    display_name: str
    model_class: str
    capabilities: list[str] = Field(default_factory=list)
    profile: EndpointProfile = Field(default_factory=EndpointProfile)
    runtime: EndpointRuntimeConfig = Field(default_factory=EndpointRuntimeConfig)
    publication: EndpointPublicationPolicy = Field(default_factory=EndpointPublicationPolicy)
    pricing: EndpointPricing = Field(default_factory=EndpointPricing)
    validation: EndpointValidationState = Field(default_factory=EndpointValidationState)
```

```python
# src/aidn_hypervisor/endpoints/state.py
from aidn_hypervisor.endpoints.models import EndpointConfigurationSnapshot, EndpointManifest


class EndpointManifestSnapshot(EndpointManifest):
    pass


class EndpointConfigurationSnapshotRecord(EndpointConfigurationSnapshot):
    pass
```

```python
# src/aidn_hypervisor/state.py
from aidn_hypervisor.endpoints.state import (
    EndpointConfigurationSnapshotRecord,
    EndpointManifestSnapshot,
)


class HypervisorStateSnapshot(BaseModel):
    ...
    endpoints: list[EndpointManifestSnapshot] = Field(default_factory=list)
    endpoint_configuration_snapshots: list[EndpointConfigurationSnapshotRecord] = Field(
        default_factory=list
    )
```

- [ ] **Step 4: Run the model tests to verify they pass**

Run: `python -m pytest tests/endpoints/test_models.py -q`

Expected: `PASS`

- [ ] **Step 5: Commit the endpoint model slice**

```bash
git add src/aidn_hypervisor/endpoints/__init__.py src/aidn_hypervisor/endpoints/models.py src/aidn_hypervisor/endpoints/state.py src/aidn_hypervisor/state.py tests/endpoints/test_models.py
git commit -m "feat: add endpoint domain models"
```

### Task 2: Add Snapshot-Backed Endpoint Persistence

**Files:**
- Create: `src/aidn_hypervisor/endpoints/store.py`
- Create: `tests/endpoints/test_store.py`
- Modify: `tests/test_persistence.py`

- [ ] **Step 1: Write the failing endpoint store tests**

```python
from pathlib import Path

from aidn_hypervisor.endpoints.models import (
    EndpointConfigurationSnapshot,
    EndpointManifest,
    EndpointPricing,
)
from aidn_hypervisor.endpoints.store import EndpointStore
from aidn_hypervisor.persistence import FileStateStore
from aidn_hypervisor.state import HypervisorStateSnapshot, TaskSnapshot
from aidn_hypervisor.domain.models import TaskRequest


def test_endpoint_store_round_trips_manifest_and_configuration_history(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "hypervisor-state.json"
    file_store = FileStateStore(state_path)
    file_store.save(
        HypervisorStateSnapshot(
            tasks=[
                TaskSnapshot(
                    task_id="task-1",
                    priority=50,
                    enqueue_index=0,
                    created_at="2026-06-29T00:00:00+00:00",
                    status="queued",
                    request=TaskRequest(
                        task_type="audio.transcribe",
                        payload={"audio_ref": "clip.wav"},
                    ),
                    bundle_id="whisper-a",
                )
            ]
        )
    )

    manifest = EndpointManifest(
        endpoint_id="ep-1",
        owner_wallet="wallet-1",
        created_at="2026-06-29T00:00:00+00:00",
        bundle_id="bundle-a",
        bundle_hash="bundle-hash-a",
        configuration_hash="cfg-a",
        display_name="Operator STT",
        model_class="speech.stt",
        capabilities=["speech.stt"],
        pricing=EndpointPricing(billing_unit="second", input_price=0.4, output_price=0.0),
    )
    snapshot = EndpointConfigurationSnapshot(
        configuration_hash="cfg-a",
        endpoint_id="ep-1",
        bundle_hash="bundle-hash-a",
        created_at="2026-06-29T00:00:00+00:00",
        runtime=manifest.runtime,
        publication=manifest.publication,
        execution_config={"streaming": False, "timeout": None},
    )

    store = EndpointStore(file_store)
    store.save_manifest(manifest)
    store.save_configuration_snapshot(snapshot)

    reloaded = EndpointStore(file_store)

    assert reloaded.get_manifest("ep-1").display_name == "Operator STT"
    assert len(reloaded.list_configuration_snapshots("ep-1")) == 1
    assert FileStateStore(state_path).load().tasks[0].task_id == "task-1"
```

- [ ] **Step 2: Run the endpoint store tests to confirm they fail**

Run: `python -m pytest tests/endpoints/test_store.py -q`

Expected: `FAIL` with `ModuleNotFoundError` or missing `EndpointStore`

- [ ] **Step 3: Implement the snapshot-backed endpoint store**

```python
# src/aidn_hypervisor/endpoints/store.py
from aidn_hypervisor.endpoints.models import EndpointConfigurationSnapshot, EndpointManifest
from aidn_hypervisor.endpoints.state import (
    EndpointConfigurationSnapshotRecord,
    EndpointManifestSnapshot,
)
from aidn_hypervisor.state import HypervisorStateSnapshot


class EndpointStore:
    def __init__(self, state_store=None) -> None:
        self._state_store = state_store
        self._manifests: dict[str, EndpointManifest] = {}
        self._snapshots: list[EndpointConfigurationSnapshot] = []
        self.restore()

    def restore(self) -> None:
        if self._state_store is None:
            return
        root = self._state_store.load()
        self._manifests = {
            item.endpoint_id: EndpointManifest.model_validate(item.model_dump(mode="json"))
            for item in root.endpoints
        }
        self._snapshots = [
            EndpointConfigurationSnapshot.model_validate(item.model_dump(mode="json"))
            for item in root.endpoint_configuration_snapshots
        ]

    def list_manifests(self) -> list[EndpointManifest]:
        return list(self._manifests.values())

    def get_manifest(self, endpoint_id: str) -> EndpointManifest:
        return self._manifests[endpoint_id]

    def save_manifest(self, manifest: EndpointManifest) -> None:
        self._manifests[manifest.endpoint_id] = manifest
        self._flush()

    def save_configuration_snapshot(self, snapshot: EndpointConfigurationSnapshot) -> None:
        self._snapshots.append(snapshot)
        self._flush()

    def list_configuration_snapshots(
        self, endpoint_id: str
    ) -> list[EndpointConfigurationSnapshot]:
        return [item for item in self._snapshots if item.endpoint_id == endpoint_id]

    def _flush(self) -> None:
        if self._state_store is None:
            return
        root = self._state_store.load()
        updated = root.model_copy(
            update={
                "endpoints": [
                    EndpointManifestSnapshot.model_validate(item.model_dump(mode="json"))
                    for item in self._manifests.values()
                ],
                "endpoint_configuration_snapshots": [
                    EndpointConfigurationSnapshotRecord.model_validate(
                        item.model_dump(mode="json")
                    )
                    for item in self._snapshots
                ],
            }
        )
        self._state_store.save(updated)
```

- [ ] **Step 4: Run the endpoint store and persistence tests**

Run: `python -m pytest tests/endpoints/test_store.py tests/test_persistence.py -k "endpoint or state_store" -q`

Expected: `PASS`

- [ ] **Step 5: Commit the endpoint persistence slice**

```bash
git add src/aidn_hypervisor/endpoints/store.py tests/endpoints/test_store.py tests/test_persistence.py
git commit -m "feat: add endpoint snapshot store"
```

### Task 3: Implement Endpoint Lifecycle And Snapshot Hashing

**Files:**
- Create: `src/aidn_hypervisor/endpoints/service.py`
- Create: `tests/endpoints/test_service.py`
- Modify: `src/aidn_hypervisor/endpoints/models.py`

- [ ] **Step 1: Write the failing endpoint service tests**

```python
from aidn_hypervisor.endpoints.models import CreateEndpointCommand, UpdateEndpointCommand
from aidn_hypervisor.endpoints.service import EndpointService, EndpointStateError
from aidn_hypervisor.endpoints.store import EndpointStore


def test_create_endpoint_generates_initial_configuration_snapshot() -> None:
    service = EndpointService(EndpointStore())

    created = service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="bundle-a",
            bundle_hash="bundle-hash-a",
            display_name="Operator STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
        )
    )

    assert created.endpoint.status == "created"
    assert created.snapshot.endpoint_id == created.endpoint.endpoint_id
    assert created.snapshot.configuration_hash == created.endpoint.configuration_hash


def test_update_endpoint_runtime_creates_new_configuration_hash() -> None:
    service = EndpointService(EndpointStore())
    created = service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="bundle-a",
            bundle_hash="bundle-hash-a",
            display_name="Operator STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
        )
    )

    updated = service.update_endpoint(
        UpdateEndpointCommand(
            endpoint_id=created.endpoint.endpoint_id,
            runtime={"streaming": True, "timeout": 45},
        )
    )

    assert updated.endpoint.configuration_hash != created.endpoint.configuration_hash
    assert len(service.list_configuration_snapshots(created.endpoint.endpoint_id)) == 2


def test_suspend_requires_active_endpoint() -> None:
    service = EndpointService(EndpointStore())
    created = service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="bundle-a",
            bundle_hash="bundle-hash-a",
            display_name="Operator STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
        )
    )

    with pytest.raises(EndpointStateError):
        service.suspend_endpoint(created.endpoint.endpoint_id)
```

- [ ] **Step 2: Run the endpoint service tests to confirm they fail**

Run: `python -m pytest tests/endpoints/test_service.py -q`

Expected: `FAIL` with missing `EndpointService`, `UpdateEndpointCommand`, or lifecycle methods

- [ ] **Step 3: Implement the endpoint service and configuration hash derivation**

```python
# src/aidn_hypervisor/endpoints/service.py
import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4

from aidn_hypervisor.endpoints.models import (
    CreateEndpointCommand,
    EndpointConfigurationSnapshot,
    EndpointManifest,
    EndpointRuntimeConfig,
    UpdateEndpointCommand,
)


class EndpointStateError(ValueError):
    pass


class EndpointService:
    def __init__(self, store) -> None:
        self.store = store

    def create_endpoint(self, cmd: CreateEndpointCommand):
        endpoint_id = f"ep-{uuid4().hex[:12]}"
        created_at = datetime.now(timezone.utc).isoformat()
        configuration_hash = self._configuration_hash(
            bundle_hash=cmd.bundle_hash,
            runtime=cmd.runtime,
            publication=cmd.publication,
            execution_config=self._execution_config(cmd.runtime, cmd.publication),
        )
        manifest = EndpointManifest(
            endpoint_id=endpoint_id,
            owner_wallet=cmd.owner_wallet,
            created_at=created_at,
            bundle_id=cmd.bundle_id,
            bundle_hash=cmd.bundle_hash,
            configuration_hash=configuration_hash,
            display_name=cmd.display_name,
            model_class=cmd.model_class,
            capabilities=cmd.capabilities,
            profile=cmd.profile,
            runtime=cmd.runtime,
            publication=cmd.publication,
            pricing=cmd.pricing,
            validation=cmd.validation,
            status="created",
        )
        snapshot = EndpointConfigurationSnapshot(
            configuration_hash=configuration_hash,
            endpoint_id=endpoint_id,
            bundle_hash=cmd.bundle_hash,
            created_at=created_at,
            runtime=cmd.runtime,
            publication=cmd.publication,
            execution_config=self._execution_config(cmd.runtime, cmd.publication),
        )
        self.store.save_manifest(manifest)
        self.store.save_configuration_snapshot(snapshot)
        return CreateEndpointResult(endpoint=manifest, snapshot=snapshot)

    def update_endpoint(self, cmd: UpdateEndpointCommand):
        current = self.store.get_manifest(cmd.endpoint_id)
        next_runtime = cmd.runtime or current.runtime
        next_publication = cmd.publication or current.publication
        should_rotate_config = cmd.runtime is not None or cmd.publication is not None
        configuration_hash = current.configuration_hash
        snapshot = None
        if should_rotate_config:
            configuration_hash = self._configuration_hash(
                bundle_hash=current.bundle_hash,
                runtime=next_runtime,
                publication=next_publication,
                execution_config=self._execution_config(next_runtime, next_publication),
            )
            snapshot = EndpointConfigurationSnapshot(
                configuration_hash=configuration_hash,
                endpoint_id=current.endpoint_id,
                bundle_hash=current.bundle_hash,
                created_at=datetime.now(timezone.utc).isoformat(),
                runtime=next_runtime,
                publication=next_publication,
                execution_config=self._execution_config(next_runtime, next_publication),
            )
            self.store.save_configuration_snapshot(snapshot)
        updated = current.model_copy(
            update={
                "display_name": cmd.display_name or current.display_name,
                "profile": cmd.profile or current.profile,
                "runtime": next_runtime,
                "publication": next_publication,
                "pricing": cmd.pricing or current.pricing,
                "configuration_hash": configuration_hash,
            }
        )
        self.store.save_manifest(updated)
        return UpdateEndpointResult(endpoint=updated, snapshot=snapshot)

    def start_endpoint(self, endpoint_id: str):
        return self._transition(endpoint_id, allowed={"created", "stopped"}, next_status="active")

    def stop_endpoint(self, endpoint_id: str):
        return self._transition(endpoint_id, allowed={"active", "suspended"}, next_status="stopped")

    def suspend_endpoint(self, endpoint_id: str):
        return self._transition(endpoint_id, allowed={"active"}, next_status="suspended")

    def resume_endpoint(self, endpoint_id: str):
        return self._transition(endpoint_id, allowed={"suspended"}, next_status="active")

    def delete_endpoint(self, endpoint_id: str):
        return self._transition(
            endpoint_id,
            allowed={"created", "stopped", "active", "suspended"},
            next_status="deleted",
        )

    def list_configuration_snapshots(self, endpoint_id: str):
        return self.store.list_configuration_snapshots(endpoint_id)

    def _transition(self, endpoint_id: str, *, allowed: set[str], next_status: str):
        current = self.store.get_manifest(endpoint_id)
        if current.status not in allowed:
            raise EndpointStateError(
                f"Endpoint {endpoint_id} cannot move from {current.status} to {next_status}"
            )
        updated = current.model_copy(update={"status": next_status})
        self.store.save_manifest(updated)
        return EndpointResult(endpoint=updated)

    def _configuration_hash(self, *, bundle_hash, runtime, publication, execution_config) -> str:
        payload = {
            "bundle_hash": bundle_hash,
            "runtime": runtime.model_dump(mode="json"),
            "publication": publication.model_dump(mode="json"),
            "execution_config": execution_config,
        }
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8"))
        return digest.hexdigest()

    def _execution_config(self, runtime: EndpointRuntimeConfig, publication) -> dict:
        return {
            "accepts_external_requests": publication.accepts_external_requests,
            "streaming": runtime.streaming,
            "timeout": runtime.timeout,
            "max_concurrency": runtime.max_tokens,
        }
```

- [ ] **Step 4: Run the endpoint service tests**

Run: `python -m pytest tests/endpoints/test_service.py -q`

Expected: `PASS`

- [ ] **Step 5: Commit the endpoint service slice**

```bash
git add src/aidn_hypervisor/endpoints/models.py src/aidn_hypervisor/endpoints/service.py tests/endpoints/test_service.py
git commit -m "feat: add endpoint lifecycle service"
```

### Task 4: Add The Versioned Endpoint API

**Files:**
- Create: `src/aidn_hypervisor/endpoints/api.py`
- Create: `tests/endpoints/test_api.py`
- Modify: `src/aidn_hypervisor/main.py`

- [ ] **Step 1: Write the failing endpoint API tests**

```python
from fastapi.testclient import TestClient

from aidn_hypervisor.endpoints.service import EndpointService
from aidn_hypervisor.endpoints.store import EndpointStore
from aidn_hypervisor.main import build_app


def _client() -> TestClient:
    endpoint_service = EndpointService(EndpointStore())
    return TestClient(build_app(endpoint_service=endpoint_service))


def test_create_endpoint_api_returns_enveloped_response() -> None:
    response = _client().post(
        "/api/v1/endpoints",
        json={
            "owner_wallet": "wallet-1",
            "bundle_id": "bundle-a",
            "bundle_hash": "bundle-hash-a",
            "display_name": "Operator STT",
            "model_class": "speech.stt",
            "capabilities": ["speech.stt"],
        },
    )

    body = response.json()

    assert response.status_code == 201
    assert body["data"]["endpoint"]["status"] == "created"
    assert body["error"] is None
    assert body["correlation_id"]


def test_patch_endpoint_runtime_rotates_configuration_hash() -> None:
    client = _client()
    created = client.post(
        "/api/v1/endpoints",
        json={
            "owner_wallet": "wallet-1",
            "bundle_id": "bundle-a",
            "bundle_hash": "bundle-hash-a",
            "display_name": "Operator STT",
            "model_class": "speech.stt",
            "capabilities": ["speech.stt"],
        },
    ).json()["data"]["endpoint"]

    updated = client.patch(
        f"/api/v1/endpoints/{created['endpoint_id']}",
        json={"runtime": {"streaming": True, "timeout": 45}},
    ).json()["data"]["endpoint"]

    assert updated["configuration_hash"] != created["configuration_hash"]
```

- [ ] **Step 2: Run the endpoint API tests to confirm they fail**

Run: `python -m pytest tests/endpoints/test_api.py -q`

Expected: `FAIL` with missing endpoint router or unsupported `build_app(endpoint_service=...)`

- [ ] **Step 3: Implement the versioned endpoint router and inject it into `build_app()`**

```python
# src/aidn_hypervisor/endpoints/api.py
from uuid import uuid4

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from aidn_hypervisor.endpoints.models import CreateEndpointCommand, UpdateEndpointCommand


def build_endpoint_router(service) -> APIRouter:
    router = APIRouter(prefix="/api/v1/endpoints")

    def _ok(data: dict, *, status_code: int = 200) -> JSONResponse:
        return JSONResponse(
            status_code=status_code,
            content={
                "data": data,
                "error": None,
                "correlation_id": str(uuid4()),
            },
        )

    def _error(status_code: int, code: str, message: str) -> JSONResponse:
        return JSONResponse(
            status_code=status_code,
            content={
                "data": None,
                "error": {"code": code, "message": message},
                "correlation_id": str(uuid4()),
            },
        )

    @router.get("")
    async def list_endpoints():
        items = [item.model_dump(mode="json") for item in service.list_endpoints()]
        return _ok({"items": items})

    @router.post("", status_code=201)
    async def create_endpoint(command: CreateEndpointCommand):
        created = service.create_endpoint(command)
        return _ok(
            {
                "endpoint": created.endpoint.model_dump(mode="json"),
                "snapshot": created.snapshot.model_dump(mode="json"),
            },
            status_code=201,
        )

    @router.get("/{endpoint_id}")
    async def get_endpoint(endpoint_id: str):
        try:
            result = service.get_endpoint(endpoint_id)
        except KeyError:
            return _error(404, "endpoint_not_found", f"Unknown endpoint: {endpoint_id}")
        return _ok({"endpoint": result.endpoint.model_dump(mode="json")})
```

```python
# src/aidn_hypervisor/main.py
from aidn_hypervisor.endpoints.api import build_endpoint_router
from aidn_hypervisor.endpoints.service import EndpointService
from aidn_hypervisor.endpoints.store import EndpointStore


def build_app(
    service: HypervisorService | None = None,
    registry_service: RegistryService | None = None,
    endpoint_service: EndpointService | None = None,
) -> FastAPI:
    app = FastAPI(...)
    app.include_router(
        build_api_router(
            service or _build_default_service(),
            registry_service=registry_service,
        )
    )
    app.include_router(build_endpoint_router(endpoint_service or EndpointService(EndpointStore())))
    return app
```

- [ ] **Step 4: Run the endpoint API tests**

Run: `python -m pytest tests/endpoints/test_api.py -q`

Expected: `PASS`

- [ ] **Step 5: Commit the endpoint API slice**

```bash
git add src/aidn_hypervisor/endpoints/api.py src/aidn_hypervisor/main.py tests/endpoints/test_api.py
git commit -m "feat: add versioned endpoint api"
```

### Task 5: Share Default Persistence And Verify Legacy Coexistence

**Files:**
- Modify: `src/aidn_hypervisor/main.py`
- Modify: `tests/test_persistence.py`
- Modify: `tests/endpoints/test_api.py`

- [ ] **Step 1: Write the failing shared-persistence tests**

```python
from pathlib import Path

from fastapi.testclient import TestClient

from aidn_hypervisor.main import build_app
from aidn_hypervisor.persistence import FileStateStore
from aidn_hypervisor.state import HypervisorStateSnapshot, TaskSnapshot
from aidn_hypervisor.domain.models import TaskRequest


def test_endpoint_api_persists_without_erasing_legacy_tasks(
    tmp_path: Path,
    monkeypatch,
) -> None:
    state_path = tmp_path / "hypervisor-state.json"
    FileStateStore(state_path).save(
        HypervisorStateSnapshot(
            tasks=[
                TaskSnapshot(
                    task_id="task-1",
                    priority=50,
                    enqueue_index=0,
                    created_at="2026-06-29T00:00:00+00:00",
                    status="queued",
                    request=TaskRequest(
                        task_type="audio.transcribe",
                        payload={"audio_ref": "clip.wav"},
                    ),
                    bundle_id="whisper-a",
                )
            ]
        )
    )
    monkeypatch.setenv("AIDN_HYPERVISOR_STATE_PATH", str(state_path))

    client = TestClient(build_app())
    response = client.post(
        "/api/v1/endpoints",
        json={
            "owner_wallet": "wallet-1",
            "bundle_id": "bundle-a",
            "bundle_hash": "bundle-hash-a",
            "display_name": "Operator STT",
            "model_class": "speech.stt",
            "capabilities": ["speech.stt"],
        },
    )

    assert response.status_code == 201
    restored = FileStateStore(state_path).load()
    assert restored.tasks[0].task_id == "task-1"
    assert restored.endpoints[0].display_name == "Operator STT"


def test_default_app_restores_endpoint_state_from_configured_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    state_path = tmp_path / "hypervisor-state.json"
    FileStateStore(state_path).save(
        HypervisorStateSnapshot(
            endpoints=[
                {
                    "endpoint_id": "ep-1",
                    "owner_wallet": "wallet-1",
                    "created_at": "2026-06-29T00:00:00+00:00",
                    "bundle_id": "bundle-a",
                    "bundle_hash": "bundle-hash-a",
                    "configuration_hash": "cfg-a",
                    "display_name": "Operator STT",
                    "model_class": "speech.stt",
                    "capabilities": ["speech.stt"],
                    "status": "created",
                }
            ]
        )
    )
    monkeypatch.setenv("AIDN_HYPERVISOR_STATE_PATH", str(state_path))

    response = TestClient(build_app()).get("/api/v1/endpoints")

    assert response.status_code == 200
    assert response.json()["data"]["items"][0]["endpoint_id"] == "ep-1"
```

- [ ] **Step 2: Run the shared-persistence tests to confirm they fail**

Run: `python -m pytest tests/test_persistence.py -k "endpoint_api_persists or restores_endpoint_state" -q`

Expected: `FAIL` because the default endpoint service is not sharing the configured state store

- [ ] **Step 3: Build the default endpoint service on top of the shared root state store**

```python
# src/aidn_hypervisor/main.py
def build_app(
    service: HypervisorService | None = None,
    registry_service: RegistryService | None = None,
    endpoint_service: EndpointService | None = None,
) -> FastAPI:
    app = FastAPI(...)
    shared_state_store = _default_state_store()
    resolved_service = service or _build_default_service(shared_state_store)
    resolved_endpoint_service = endpoint_service or _build_default_endpoint_service(
        shared_state_store
    )
    app.include_router(
        build_api_router(resolved_service, registry_service=registry_service)
    )
    app.include_router(build_endpoint_router(resolved_endpoint_service))
    return app


def _build_default_service(state_store: FileStateStore | None = None) -> HypervisorService:
    state_store = state_store or _default_state_store()
    ...


def _build_default_endpoint_service(
    state_store: FileStateStore | None = None,
) -> EndpointService:
    state_store = state_store or _default_state_store()
    return EndpointService(EndpointStore(state_store))
```

- [ ] **Step 4: Run the shared-persistence and regression suite**

Run: `python -m pytest tests/endpoints/test_models.py tests/endpoints/test_store.py tests/endpoints/test_service.py tests/endpoints/test_api.py tests/test_persistence.py tests/test_api.py -q`

Expected: `PASS`

- [ ] **Step 5: Commit the shared bootstrap slice**

```bash
git add src/aidn_hypervisor/main.py tests/test_persistence.py tests/endpoints/test_api.py
git commit -m "feat: wire endpoint service into app bootstrap"
```

## Self-Review Checklist

- Spec coverage:
  - endpoint manifest model: Task 1
  - configuration snapshot model: Tasks 1 and 3
  - endpoint lifecycle service: Task 3
  - versioned `/api/v1/endpoints` API: Task 4
  - persistence and coexistence with legacy state: Tasks 2 and 5
- Placeholder scan:
  - no placeholder markers or deferred "implement later" steps remain inside tasks
- Type consistency:
  - `EndpointManifest`, `EndpointConfigurationSnapshot`, `CreateEndpointCommand`, `UpdateEndpointCommand`, `EndpointStore`, and `EndpointService` names are used consistently across all tasks
