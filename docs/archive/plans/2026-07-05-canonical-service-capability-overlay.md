# Canonical Service Capability Overlay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce a canonical `service / capability / runtime / advertisement` overlay in the repo, keep current `bundle / provider` execution working as a compute compatibility layer, and realign docs plus operator/API payloads to the new RFC-authoritative architecture.

**Architecture:** Add a small canonical domain module and a projection layer that maps legacy compute objects into the new model without rewriting execution internals. `HypervisorService` becomes the source of canonical service and runtime inventory, while `operator_views.py` and `api.py` expose those new read models alongside existing endpoint-first payloads. Existing `bundle` and `provider plugin` concepts remain operational but are explicitly treated as transitional compute internals.

**Tech Stack:** Python, Pydantic, FastAPI, pytest, existing `aidn_hypervisor` service layer, static operator dashboard HTML, markdown docs.

---

## File Structure

### New files

- `src/aidn_hypervisor/canonical_models.py`
  - Canonical protocol service, capability, runtime, compatibility, and advertisement records
- `src/aidn_hypervisor/canonical_projection.py`
  - Pure projection helpers from current `HypervisorService` state into canonical overlays
- `tests/test_canonical_models.py`
  - Unit tests for canonical model validation and defaults
- `tests/test_canonical_projection.py`
  - Focused tests for mapping legacy compute state into canonical service/runtime/capability views

### Existing files to modify

- `src/aidn_hypervisor/service.py`
  - Expose canonical read APIs backed by the new projection layer
- `src/aidn_hypervisor/operator_views.py`
  - Add canonical service/capability/runtime sections to operator payloads
- `src/aidn_hypervisor/api.py`
  - Add read-only operator routes for canonical overlay data and keep existing routes backward-compatible
- `src/aidn_hypervisor/static/operator_dashboard.html`
  - Surface canonical compute/service meaning in `Home`, `Providers`, and `Bundles` without a full terminology rewrite
- `ROADMAP.md`
  - Reframe current milestone work in canonical terms
- `00_VISION.md`
  - Replace public architectural emphasis on `provider/bundle` with `services/capabilities/runtimes`
- `02_ARCHITECTURE.md`
  - Replace the old linear `Agent -> Hypervisor API -> Scheduler -> Node Registry -> Node Agent -> Provider -> Model` view with the new layered model
- `tests/test_service.py`
  - Verify new canonical service inventory methods on `HypervisorService`
- `tests/test_operator_views.py`
  - Verify canonical overlay sections appear in payloads without breaking endpoint-first behavior
- `tests/test_api.py`
  - Verify new routes and enriched payloads serialize correctly

### Existing reference files to inspect while implementing

- `docs/archive/specifications/2026-07-05-canonical-service-capability-overlay-design.md`
- `docs/product/UX-0001-hypervisor-operator-journey.md`
- `docs/product/UX-0002-endpoint-session-and-payment-flow.md`
- `docs/product/RFC-0035-validation-escrow-system.md`
- `docs/product/RFC-0036-aidn-ledger-state-machine.md`
- `docs/product/RFC-0037-settlement-engine.md`
- `src/aidn_hypervisor/domain/models.py`
- `src/aidn_hypervisor/plugins/base.py`
- `src/aidn_hypervisor/registry_models.py`
- `src/aidn_hypervisor/service.py`
- `src/aidn_hypervisor/operator_views.py`
- `src/aidn_hypervisor/static/operator_dashboard.html`

---

### Task 1: Add Canonical Protocol Service And Runtime Models

**Files:**
- Create: `src/aidn_hypervisor/canonical_models.py`
- Create: `tests/test_canonical_models.py`

- [ ] **Step 1: Write the failing canonical model tests**

```python
from aidn_hypervisor.canonical_models import (
    CanonicalAdvertisementRecord,
    CanonicalCapabilityRecord,
    CanonicalCapabilityRuntimeRecord,
    CanonicalComputeCompatibilityRecord,
    CanonicalProtocolServiceRecord,
)


def test_protocol_service_record_derives_enabled_compute_role() -> None:
    record = CanonicalProtocolServiceRecord(
        service_id="compute",
        kind="compute",
        enabled=True,
        derived_roles=["compute_provider"],
        responsibilities=["endpoint_hosting", "session_execution"],
    )

    assert record.kind == "compute"
    assert record.enabled is True
    assert record.derived_roles == ["compute_provider"]


def test_capability_runtime_record_requires_capability_identity() -> None:
    record = CanonicalCapabilityRuntimeRecord(
        runtime_id="runtime-1",
        capability_id="speech.stt",
        runtime_version="0.1.0",
        protocol_version="runtime.v1",
        location_kind="local_process",
        health_status="healthy",
        supported_features=["streaming"],
    )

    assert record.capability_id == "speech.stt"
    assert record.location_kind == "local_process"


def test_compute_compatibility_record_preserves_legacy_mapping() -> None:
    record = CanonicalComputeCompatibilityRecord(
        compatibility_id="bundle:whisper-a",
        legacy_bundle_id="whisper-a",
        legacy_plugin_id="fake-managed",
        legacy_provider_type="fake",
        canonical_capability_id="speech.stt",
        canonical_runtime_id="runtime-whisper-a",
    )

    assert record.legacy_bundle_id == "whisper-a"
    assert record.canonical_capability_id == "speech.stt"


def test_endpoint_advertisement_record_captures_capability_surface() -> None:
    record = CanonicalAdvertisementRecord(
        advertisement_id="adv-endpoint-1",
        resource_type="endpoint",
        owner_wallet="wallet-1",
        hypervisor_id="node-local",
        capability_id="llm.chat",
        visibility="private",
        signature_scope="configuration_publication",
    )

    assert record.resource_type == "endpoint"
    assert record.capability_id == "llm.chat"
```

- [ ] **Step 2: Run the canonical model tests to verify they fail**

Run: `python -m pytest tests/test_canonical_models.py -v`

Expected: FAIL with `ModuleNotFoundError` for `aidn_hypervisor.canonical_models`.

- [ ] **Step 3: Add the minimal canonical model module**

```python
from typing import Literal

from pydantic import BaseModel, Field

ProtocolServiceKind = Literal["compute", "registry", "validation", "consensus"]
RuntimeLocationKind = Literal[
    "local_process",
    "container",
    "virtual_machine",
    "remote_service",
]
AdvertisementResourceType = Literal[
    "endpoint",
    "runtime",
    "registry_service",
    "validation_service",
    "consensus_service",
]


class CanonicalProtocolServiceRecord(BaseModel):
    service_id: str
    kind: ProtocolServiceKind
    enabled: bool
    derived_roles: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)


class CanonicalCapabilityRecord(BaseModel):
    capability_id: str
    request_schema_id: str
    response_schema_id: str
    accounting_rule: str
    validation_rule: str


class CanonicalCapabilityRuntimeRecord(BaseModel):
    runtime_id: str
    capability_id: str
    runtime_version: str
    protocol_version: str
    location_kind: RuntimeLocationKind
    health_status: str
    supported_features: list[str] = Field(default_factory=list)


class CanonicalComputeCompatibilityRecord(BaseModel):
    compatibility_id: str
    legacy_bundle_id: str
    legacy_plugin_id: str
    legacy_provider_type: str
    canonical_capability_id: str
    canonical_runtime_id: str


class CanonicalAdvertisementRecord(BaseModel):
    advertisement_id: str
    resource_type: AdvertisementResourceType
    owner_wallet: str
    hypervisor_id: str
    capability_id: str | None = None
    visibility: str
    signature_scope: str
```

- [ ] **Step 4: Re-run the canonical model tests to verify they pass**

Run: `python -m pytest tests/test_canonical_models.py -v`

Expected: PASS with all canonical model tests green.

- [ ] **Step 5: Commit the canonical model slice**

```bash
git add src/aidn_hypervisor/canonical_models.py tests/test_canonical_models.py
git commit -m "feat: add canonical service capability models"
```

---

### Task 2: Add Canonical Projection Helpers Over Legacy Compute State

**Files:**
- Create: `src/aidn_hypervisor/canonical_projection.py`
- Create: `tests/test_canonical_projection.py`
- Modify: `src/aidn_hypervisor/service.py`
- Modify: `tests/test_service.py`

- [ ] **Step 1: Write the failing projection and service tests**

```python
from aidn_hypervisor.canonical_projection import (
    project_capability_runtimes,
    project_compute_compatibility,
    project_protocol_services,
)


def test_project_protocol_services_marks_compute_enabled_by_default(service) -> None:
    records = project_protocol_services(service)

    assert [record.kind for record in records] == [
        "compute",
        "registry",
        "validation",
        "consensus",
    ]
    assert records[0].enabled is True
    assert "endpoint_hosting" in records[0].responsibilities


def test_project_capability_runtimes_maps_bundle_runtime_to_canonical_runtime(service) -> None:
    records = project_capability_runtimes(service)

    whisper = next(record for record in records if record.capability_id == "speech.stt")
    assert whisper.runtime_id == "runtime-whisper-a"
    assert whisper.location_kind == "local_process"


def test_service_exposes_canonical_overlay_inventory(service) -> None:
    payload = service.canonical_overlay_inventory()

    assert "services" in payload
    assert "capabilities" in payload
    assert "runtimes" in payload
    assert "compatibility" in payload
    assert payload["services"][0]["kind"] == "compute"
```

- [ ] **Step 2: Run the focused projection tests to verify they fail**

Run: `python -m pytest tests/test_canonical_projection.py tests/test_service.py -k "canonical_overlay or project_protocol_services or project_capability_runtimes" -v`

Expected: FAIL with missing module or missing `HypervisorService.canonical_overlay_inventory()`.

- [ ] **Step 3: Implement the canonical projection layer and service read methods**

```python
from aidn_hypervisor.canonical_models import (
    CanonicalCapabilityRecord,
    CanonicalCapabilityRuntimeRecord,
    CanonicalComputeCompatibilityRecord,
    CanonicalProtocolServiceRecord,
)


_CAPABILITY_BY_WORKLOAD = {
    "llm_text": "llm.chat",
    "speech_to_text": "speech.stt",
}


def _capability_id_for_bundle(bundle) -> str:
    return _CAPABILITY_BY_WORKLOAD.get(bundle.workload_type, bundle.workload_type)


def project_protocol_services(service) -> list[CanonicalProtocolServiceRecord]:
    return [
        CanonicalProtocolServiceRecord(
            service_id="compute",
            kind="compute",
            enabled=True,
            derived_roles=["compute_provider"],
            responsibilities=[
                "provider_management",
                "endpoint_hosting",
                "session_execution",
                "marketplace_integration",
            ],
        ),
        CanonicalProtocolServiceRecord(
            service_id="registry",
            kind="registry",
            enabled=service.registry_enabled(),
            derived_roles=["registry_operator"] if service.registry_enabled() else [],
            responsibilities=["ledger_storage", "snapshot_distribution", "historical_lookup"],
        ),
        CanonicalProtocolServiceRecord(
            service_id="validation",
            kind="validation",
            enabled=service.validation_enabled(),
            derived_roles=["validator"] if service.validation_enabled() else [],
            responsibilities=["endpoint_validation", "validation_reporting"],
        ),
        CanonicalProtocolServiceRecord(
            service_id="consensus",
            kind="consensus",
            enabled=False,
            derived_roles=[],
            responsibilities=["block_proposal", "block_validation", "ledger_finalization"],
        ),
    ]


def project_capability_runtimes(service) -> list[CanonicalCapabilityRuntimeRecord]:
    runtimes = []
    runtime_by_bundle = {
        runtime.bundle_id: runtime for runtime in service.list_runtimes()
    }
    for bundle in service.bundles:
        runtime = runtime_by_bundle.get(bundle.bundle_id)
        runtimes.append(
            CanonicalCapabilityRuntimeRecord(
                runtime_id=f"runtime-{bundle.bundle_id}",
                capability_id=_capability_id_for_bundle(bundle),
                runtime_version="legacy.bundle.v1",
                protocol_version="runtime.v1",
                location_kind="local_process",
                health_status=(runtime.health_status if runtime is not None else "unavailable"),
                supported_features=["legacy_bundle_compatibility"],
            )
        )
    return runtimes


def project_compute_compatibility(service) -> list[CanonicalComputeCompatibilityRecord]:
    records = []
    for bundle in service.bundles:
        records.append(
            CanonicalComputeCompatibilityRecord(
                compatibility_id=f"bundle:{bundle.bundle_id}",
                legacy_bundle_id=bundle.bundle_id,
                legacy_plugin_id=bundle.plugin_id,
                legacy_provider_type=bundle.provider_type,
                canonical_capability_id=_capability_id_for_bundle(bundle),
                canonical_runtime_id=f"runtime-{bundle.bundle_id}",
            )
        )
    return records
```

```python
def registry_enabled(self) -> bool:
    return False


def validation_enabled(self) -> bool:
    return False


def canonical_overlay_inventory(self) -> dict:
    from aidn_hypervisor.canonical_projection import (
        project_capability_runtimes,
        project_compute_compatibility,
        project_protocol_services,
    )

    runtimes = project_capability_runtimes(self)
    compatibility = project_compute_compatibility(self)
    capability_ids = sorted({runtime.capability_id for runtime in runtimes})
    return {
        "services": [record.model_dump(mode="json") for record in project_protocol_services(self)],
        "capabilities": [
            {
                "capability_id": capability_id,
                "source": "legacy_compute_overlay",
            }
            for capability_id in capability_ids
        ],
        "runtimes": [record.model_dump(mode="json") for record in runtimes],
        "compatibility": [record.model_dump(mode="json") for record in compatibility],
    }
```

- [ ] **Step 4: Re-run the focused projection tests to verify they pass**

Run: `python -m pytest tests/test_canonical_projection.py tests/test_service.py -k "canonical_overlay or project_protocol_services or project_capability_runtimes" -v`

Expected: PASS for the projection and service inventory tests.

- [ ] **Step 5: Commit the projection slice**

```bash
git add src/aidn_hypervisor/canonical_projection.py src/aidn_hypervisor/service.py tests/test_canonical_projection.py tests/test_service.py
git commit -m "feat: project legacy compute into canonical overlay"
```

---

### Task 3: Expose Canonical Overlay Through Operator Views And API

**Files:**
- Modify: `src/aidn_hypervisor/operator_views.py`
- Modify: `src/aidn_hypervisor/api.py`
- Modify: `src/aidn_hypervisor/static/operator_dashboard.html`
- Modify: `tests/test_operator_views.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Write the failing operator/API regression tests**

```python
def test_home_payload_exposes_canonical_service_overlay(
    service: HypervisorService,
    endpoint_service: EndpointService,
) -> None:
    payload = build_operator_home_payload(
        service=service,
        endpoint_service=endpoint_service,
        endpoint_publication_service=None,
        validation_service=None,
        market_candidates=[],
    )

    assert payload["canonical_overlay"]["services"][0]["kind"] == "compute"
    assert payload["canonical_overlay"]["runtimes"][0]["capability_id"] == "speech.stt"
    assert payload["canonical_overlay"]["compatibility"][0]["legacy_bundle_id"] == "whisper-a"


def test_operator_services_route_returns_canonical_service_inventory() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/services")

    assert response.status_code == 200
    body = response.json()
    assert body["services"][0]["kind"] == "compute"
    assert "capabilities" in body
    assert "runtimes" in body


def test_operator_dashboard_shell_mentions_compute_service_overlay() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert "Compute Service" in response.text
    assert "Capability Runtimes" in response.text
    assert "Bundles remain a transitional local supply layer." in response.text
```

- [ ] **Step 2: Run the operator/API regression tests to verify they fail**

Run: `python -m pytest tests/test_operator_views.py tests/test_api.py -k "canonical_service_overlay or operator_services_route_returns_canonical_service_inventory or dashboard_shell_mentions_compute_service_overlay" -v`

Expected: FAIL because the canonical overlay payloads and route do not yet exist.

- [ ] **Step 3: Add canonical overlay payloads and operator routes**

```python
def build_operator_home_payload(
    *,
    service,
    endpoint_service,
    endpoint_publication_service=None,
    validation_service=None,
    market_candidates=None,
) -> dict:
    ...
    return {
        "bootstrap": ...,
        "canonical_overlay": service.canonical_overlay_inventory(),
        "onboarding": onboarding,
        ...
    }
```

```python
@router.get("/operators/services")
async def operator_services() -> dict:
    return service.canonical_overlay_inventory()
```

```html
<div class="notice" style="margin-top: 14px;">
  <strong>Compute Service</strong>
  <span style="display: block; margin-top: 4px;">
    This node currently exposes compute through capability runtimes. Bundles remain a transitional local supply layer during the overlay migration.
  </span>
</div>
<div class="notice" style="margin-top: 14px;">
  <strong>Capability Runtimes</strong>
  <span style="display: block; margin-top: 4px;">
    Endpoint publication and session execution are being realigned around capability runtimes rather than public provider plugins.
  </span>
</div>
```

- [ ] **Step 4: Re-run the operator/API regression tests to verify they pass**

Run: `python -m pytest tests/test_operator_views.py tests/test_api.py -k "canonical_service_overlay or operator_services_route_returns_canonical_service_inventory or dashboard_shell_mentions_compute_service_overlay" -v`

Expected: PASS with canonical overlay data visible in the operator payload and `/operators/services`.

- [ ] **Step 5: Commit the operator/API slice**

```bash
git add src/aidn_hypervisor/operator_views.py src/aidn_hypervisor/api.py src/aidn_hypervisor/static/operator_dashboard.html tests/test_operator_views.py tests/test_api.py
git commit -m "feat: expose canonical service capability overlay"
```

---

### Task 4: Realign Roadmap, Vision, And Architecture Docs

**Files:**
- Modify: `ROADMAP.md`
- Modify: `00_VISION.md`
- Modify: `02_ARCHITECTURE.md`

- [ ] **Step 1: Update the roadmap to mark the canonical overlay as the immediate architecture slice**

```md
Product alignment summary:
- the new RFC set is now authoritative for service, capability, runtime, registry, marketplace, verification, and reputation architecture;
- the current repo is introducing a compatibility-first overlay so existing bundle/provider execution continues while canonical service/capability/runtime models become primary;
- future registry, marketplace, verification, and reputation work should build on canonical advertisements and service/runtime records rather than deepening bundle-centric contracts.

Immediate Priorities:
1. Land the canonical `service / capability / runtime` overlay in code and operator/API payloads
2. Reframe current `bundle/provider` machinery as compute compatibility internals
3. Build registry, marketplace, verification, reputation, and epoch work on the canonical overlay
```

- [ ] **Step 2: Update the vision to replace public provider/bundle emphasis**

```md
### 4. Capability And Runtime Driven

The network should expose capabilities and runtimes as its canonical execution model.

Provider stacks such as `llama.cpp`, `vLLM`, `Ollama`, `Whisper`, and future adapters remain implementation details behind capability runtimes rather than primary public protocol objects.
```

- [ ] **Step 3: Update the architecture doc to show the canonical stack**

```md
Agent
  ↓
Hypervisor
  ↓
Protocol Services
  ↓
Capability Runtimes
  ↓
Endpoints
  ↓
Advertisements / Marketplace / Registry
```

- [ ] **Step 4: Run the focused verification suite**

Run: `python -m pytest tests/test_canonical_models.py tests/test_canonical_projection.py tests/test_service.py tests/test_operator_views.py tests/test_api.py -k "canonical or operator_services or home_payload_exposes_canonical_service_overlay" -v`

Expected: PASS for the canonical overlay model, projection, service, view, and API regression slices.

- [ ] **Step 5: Commit the docs realignment**

```bash
git add ROADMAP.md 00_VISION.md 02_ARCHITECTURE.md
git commit -m "docs: realign architecture to canonical service overlay"
```

---

## Self-Review

### Spec coverage

- `Canonical service model in code`
  - Covered by Task 1 and Task 2
- `Canonical capability and runtime model`
  - Covered by Task 1 and Task 2
- `Compute compatibility projections`
  - Covered by Task 2
- `Documentation and roadmap realignment`
  - Covered by Task 4
- `Minimal API/UI impact`
  - Covered by Task 3

### Placeholder scan

- No `TODO`, `TBD`, `placeholder`, or incomplete implementation instructions remain.

### Type consistency

- `CanonicalProtocolServiceRecord`
  - Defined in Task 1 and consumed consistently in Tasks 2 and 3
- `CanonicalCapabilityRuntimeRecord`
  - Defined in Task 1 and consumed consistently in Tasks 2 and 3
- `CanonicalComputeCompatibilityRecord`
  - Defined in Task 1 and consumed consistently in Tasks 2 and 3
- `service.canonical_overlay_inventory()`
  - Introduced in Task 2 and consumed consistently in Task 3

## Execution Handoff

Plan complete and saved to `docs/archive/plans/2026-07-05-canonical-service-capability-overlay.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
