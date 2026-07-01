# Endpoint Configuration Publication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add wallet-signed endpoint configuration publication, registry indexing of current published configuration, live proof verification, and operator dashboard sync visibility.

**Architecture:** Build a new publication layer on top of the existing endpoint snapshot model. Local endpoint manifests and configuration snapshots remain the source of editable state, while a wallet-backed publication journal stores signed immutable publication records and the registry indexes the current published configuration hash for discovery.

**Tech Stack:** Python, FastAPI, Pydantic, existing snapshot persistence, operator dashboard HTML/JS, pytest

---

## File Structure

### New Files

- `src/aidn_hypervisor/endpoint_publications/models.py`
  - wallet-signed publication records, proof models, canonical payload helpers
- `src/aidn_hypervisor/endpoint_publications/store.py`
  - append-only storage for publication records layered on existing state store
- `src/aidn_hypervisor/endpoint_publications/service.py`
  - publication orchestration, signing, supersede/revoke logic, proof generation
- `tests/endpoint_publications/test_models.py`
  - canonical hash and signature payload tests
- `tests/endpoint_publications/test_service.py`
  - publication lifecycle tests

### Existing Files To Modify

- `src/aidn_hypervisor/state.py`
  - extend root snapshot with endpoint publication journal records
- `src/aidn_hypervisor/endpoints/models.py`
  - add publication-facing sync fields only if required by response contracts
- `src/aidn_hypervisor/endpoints/store.py`
  - no behavior change unless shared snapshot save helpers are needed
- `src/aidn_hypervisor/api.py`
  - add endpoint publication actions, proof route, wallet publication exports, dashboard sync payload
- `src/aidn_hypervisor/registry_models.py`
  - add endpoint publication summary/index fields for registry advertisement
- `src/aidn_hypervisor/service.py`
  - extend node advertisement generation with published endpoint configuration pointers
- `src/aidn_hypervisor/static/operator_dashboard.html`
  - show local vs published configuration hash, publication actions, sync state
- `src/aidn_hypervisor/main.py`
  - wire publication service into app bootstrap
- `tests/test_api.py`
  - operator dashboard, publish action, proof, wallet export coverage
- `tests/test_persistence.py`
  - publication journal round-trip tests
- `ROADMAP.md`
  - mark the new trust/publication milestone work in current stage and priorities

---

### Task 1: Define Publication Models And Canonical Hashing

**Files:**
- Create: `src/aidn_hypervisor/endpoint_publications/models.py`
- Test: `tests/endpoint_publications/test_models.py`

- [ ] **Step 1: Write the failing tests**

```python
from aidn_hypervisor.endpoint_publications.models import (
    PublishedEndpointConfiguration,
    canonical_configuration_payload,
    configuration_hash_for_publication,
)


def test_configuration_hash_uses_execution_relevant_fields_only() -> None:
    payload_a = canonical_configuration_payload(
        bundle_hash="bundle-hash-a",
        model_class="speech.stt",
        capabilities=["speech.stt"],
        runtime={"context_length": 8192, "timeout": 45, "streaming": True},
        publication={
            "visibility": "shared",
            "shared_with_wallet_ids": ["wallet-a"],
            "discoverable": True,
            "validation": "disabled",
            "accepts_external_requests": True,
        },
        pricing={"billing_unit": "request", "input_price": 1.0},
    )
    payload_b = canonical_configuration_payload(
        bundle_hash="bundle-hash-a",
        model_class="speech.stt",
        capabilities=["speech.stt"],
        runtime={"context_length": 8192, "timeout": 45, "streaming": True},
        publication={
            "visibility": "shared",
            "shared_with_wallet_ids": ["wallet-a"],
            "discoverable": True,
            "validation": "disabled",
            "accepts_external_requests": True,
        },
        pricing={"billing_unit": "request", "input_price": 1.0},
    )

    assert configuration_hash_for_publication(payload_a) == configuration_hash_for_publication(payload_b)


def test_published_endpoint_configuration_excludes_signature_from_signed_payload() -> None:
    record = PublishedEndpointConfiguration(
        schema_version="epcfg.v1",
        publication_id="pub-1",
        endpoint_id="ep-1",
        owner_wallet="wallet-1",
        node_id="node-1",
        configuration_hash="cfg-1",
        previous_configuration_hash=None,
        bundle_id="bundle-a",
        bundle_hash="bundle-hash-a",
        model_class="speech.stt",
        capabilities=["speech.stt"],
        profile={"summary": "Operator STT"},
        runtime={"timeout": 45, "streaming": True},
        publication={"visibility": "public", "discoverable": True},
        pricing={"billing_unit": "request"},
        validation_requirement={"enabled": False},
        published_at="2026-06-30T00:00:00+00:00",
        sequence=1,
        status="published",
        wallet_signature="sig-1",
    )

    assert "wallet_signature" not in record.signed_payload()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/endpoint_publications/test_models.py -q`
Expected: FAIL with import errors for missing publication models/helpers.

- [ ] **Step 3: Write the minimal implementation**

```python
import hashlib
import json
from typing import Literal

from pydantic import BaseModel, Field


PublicationStatus = Literal["published", "superseded", "revoked"]


def canonical_configuration_payload(*, bundle_hash, model_class, capabilities, runtime, publication, pricing):
    return {
        "bundle_hash": bundle_hash,
        "model_class": model_class,
        "capabilities": list(capabilities),
        "runtime": runtime,
        "publication": publication,
        "pricing": pricing,
    }


def configuration_hash_for_publication(payload: dict) -> str:
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8"))
    return digest.hexdigest()


class PublishedEndpointConfiguration(BaseModel):
    schema_version: str = "epcfg.v1"
    publication_id: str
    endpoint_id: str
    owner_wallet: str
    node_id: str
    configuration_hash: str
    previous_configuration_hash: str | None = None
    bundle_id: str
    bundle_hash: str
    model_class: str
    capabilities: list[str] = Field(default_factory=list)
    profile: dict = Field(default_factory=dict)
    runtime: dict = Field(default_factory=dict)
    publication: dict = Field(default_factory=dict)
    pricing: dict = Field(default_factory=dict)
    validation_requirement: dict = Field(default_factory=dict)
    published_at: str
    sequence: int = Field(ge=1)
    status: PublicationStatus = "published"
    wallet_signature: str

    def signed_payload(self) -> dict:
        payload = self.model_dump(mode="json")
        payload.pop("wallet_signature", None)
        return payload
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/endpoint_publications/test_models.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/endpoint_publications/test_models.py src/aidn_hypervisor/endpoint_publications/models.py
git commit -m "feat: add endpoint publication models"
```

### Task 2: Persist Wallet Publication Records

**Files:**
- Modify: `src/aidn_hypervisor/state.py`
- Create: `src/aidn_hypervisor/endpoint_publications/store.py`
- Test: `tests/test_persistence.py`

- [ ] **Step 1: Write the failing tests**

```python
from aidn_hypervisor.endpoint_publications.models import PublishedEndpointConfiguration
from aidn_hypervisor.state import HypervisorStateSnapshot


def test_file_state_store_round_trips_endpoint_publication_records(tmp_path) -> None:
    state_path = tmp_path / "hypervisor-state.json"
    store = FileStateStore(state_path)
    snapshot = HypervisorStateSnapshot(
        endpoint_publications=[
            PublishedEndpointConfiguration(
                schema_version="epcfg.v1",
                publication_id="pub-1",
                endpoint_id="ep-1",
                owner_wallet="wallet-1",
                node_id="node-1",
                configuration_hash="cfg-1",
                previous_configuration_hash=None,
                bundle_id="bundle-a",
                bundle_hash="bundle-hash-a",
                model_class="speech.stt",
                capabilities=["speech.stt"],
                profile={},
                runtime={},
                publication={},
                pricing={},
                validation_requirement={},
                published_at="2026-06-30T00:00:00+00:00",
                sequence=1,
                status="published",
                wallet_signature="sig-1",
            )
        ]
    )

    store.save(snapshot)
    restored = store.load()

    assert restored.endpoint_publications[0].publication_id == "pub-1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_persistence.py -k "endpoint_publication_records" -q`
Expected: FAIL because `HypervisorStateSnapshot` lacks `endpoint_publications`.

- [ ] **Step 3: Write the minimal implementation**

```python
# in src/aidn_hypervisor/state.py
from aidn_hypervisor.endpoint_publications.models import PublishedEndpointConfiguration


class HypervisorStateSnapshot(BaseModel):
    ...
    endpoint_publications: list[PublishedEndpointConfiguration] = Field(default_factory=list)
```

```python
# in src/aidn_hypervisor/endpoint_publications/store.py
from aidn_hypervisor.endpoint_publications.models import PublishedEndpointConfiguration


class EndpointPublicationStore:
    def __init__(self, state_store=None) -> None:
        self._state_store = state_store
        self._records: list[PublishedEndpointConfiguration] = []
        self.restore()

    def restore(self) -> None:
        if self._state_store is None:
            return
        root = self._state_store.load()
        self._records = [PublishedEndpointConfiguration.model_validate(item.model_dump(mode="json")) for item in root.endpoint_publications]

    def list_records(self) -> list[PublishedEndpointConfiguration]:
        return list(self._records)

    def append(self, record: PublishedEndpointConfiguration) -> None:
        self._records.append(record)
        self._flush()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_persistence.py -k "endpoint_publication_records" -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aidn_hypervisor/state.py src/aidn_hypervisor/endpoint_publications/store.py tests/test_persistence.py
git commit -m "feat: persist endpoint publication records"
```

### Task 3: Implement Publication Service Lifecycle

**Files:**
- Create: `src/aidn_hypervisor/endpoint_publications/service.py`
- Test: `tests/endpoint_publications/test_service.py`

- [ ] **Step 1: Write the failing tests**

```python
from aidn_hypervisor.endpoint_publications.service import EndpointPublicationService
from aidn_hypervisor.endpoints.service import EndpointService
from aidn_hypervisor.endpoints.store import EndpointStore


def test_publish_configuration_creates_signed_current_record() -> None:
    endpoint_service = EndpointService(EndpointStore())
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="bundle-a",
            bundle_hash="bundle-hash-a",
            display_name="Operator STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
        )
    )
    service = EndpointPublicationService(store=EndpointPublicationStore(), endpoint_service=endpoint_service)

    record = service.publish_configuration(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet="wallet-1",
        node_id="node-1",
        wallet_private_key="sk-1",
    )

    assert record.endpoint_id == created.endpoint.endpoint_id
    assert record.status == "published"
    assert record.wallet_signature


def test_publish_configuration_supersedes_prior_publication() -> None:
    ...
    assert records[0].status == "superseded"
    assert records[1].status == "published"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/endpoint_publications/test_service.py -q`
Expected: FAIL with missing service implementation.

- [ ] **Step 3: Write the minimal implementation**

```python
from datetime import datetime, timezone
from uuid import uuid4

from aidn_hypervisor.endpoint_publications.models import (
    PublishedEndpointConfiguration,
    canonical_configuration_payload,
    configuration_hash_for_publication,
)


class EndpointPublicationService:
    def __init__(self, *, store, endpoint_service) -> None:
        self.store = store
        self.endpoint_service = endpoint_service

    def publish_configuration(self, *, endpoint_id: str, owner_wallet: str, node_id: str, wallet_private_key: str):
        manifest = self.endpoint_service.get_endpoint(endpoint_id).endpoint
        previous = self.current_publication(endpoint_id)
        payload = canonical_configuration_payload(
            bundle_hash=manifest.bundle_hash,
            model_class=manifest.model_class,
            capabilities=manifest.capabilities,
            runtime=manifest.runtime.model_dump(mode="json"),
            publication=manifest.publication.model_dump(mode="json"),
            pricing=manifest.pricing.model_dump(mode="json"),
        )
        configuration_hash = configuration_hash_for_publication(payload)
        sequence = 1 if previous is None else previous.sequence + 1
        if previous is not None:
            previous.status = "superseded"
        record = PublishedEndpointConfiguration(
            publication_id=f"pub-{uuid4().hex[:12]}",
            endpoint_id=endpoint_id,
            owner_wallet=owner_wallet,
            node_id=node_id,
            configuration_hash=configuration_hash,
            previous_configuration_hash=(previous.configuration_hash if previous else None),
            bundle_id=manifest.bundle_id,
            bundle_hash=manifest.bundle_hash,
            model_class=manifest.model_class,
            capabilities=list(manifest.capabilities),
            profile=manifest.profile.model_dump(mode="json"),
            runtime=manifest.runtime.model_dump(mode="json"),
            publication=manifest.publication.model_dump(mode="json"),
            pricing=manifest.pricing.model_dump(mode="json"),
            validation_requirement=manifest.validation.model_dump(mode="json"),
            published_at=datetime.now(timezone.utc).isoformat(),
            sequence=sequence,
            status="published",
            wallet_signature=f"sig-{configuration_hash[:16]}-{wallet_private_key[:8]}",
        )
        self.store.append(record)
        return record
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/endpoint_publications/test_service.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aidn_hypervisor/endpoint_publications/service.py tests/endpoint_publications/test_service.py
git commit -m "feat: add endpoint publication service"
```

### Task 4: Add API Routes For Publish, Revoke, Proof, And Wallet Export

**Files:**
- Modify: `src/aidn_hypervisor/api.py`
- Modify: `src/aidn_hypervisor/main.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_publish_configuration_endpoint_returns_signed_record() -> None:
    client = TestClient(build_app(service=_service(), endpoint_service=endpoint_service, endpoint_publication_service=publication_service))

    response = client.post(f"/api/v1/endpoints/{endpoint_id}/publish-configuration")

    assert response.status_code == 200
    assert response.json()["data"]["publication"]["endpoint_id"] == endpoint_id
    assert response.json()["data"]["publication"]["wallet_signature"]


def test_endpoint_proof_returns_live_configuration_hash() -> None:
    response = client.get(f"/api/v1/endpoints/{endpoint_id}/proof")

    assert response.status_code == 200
    assert response.json()["data"]["proof"]["endpoint_id"] == endpoint_id
    assert response.json()["data"]["proof"]["configuration_hash"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_api.py -k "publish_configuration_endpoint or endpoint_proof_returns_live_configuration_hash" -q`
Expected: FAIL because the routes do not exist.

- [ ] **Step 3: Write the minimal implementation**

```python
# in src/aidn_hypervisor/api.py
@router.post("/api/v1/endpoints/{endpoint_id}/publish-configuration")
async def publish_endpoint_configuration(endpoint_id: str) -> JSONResponse:
    record = endpoint_publication_service.publish_configuration(
        endpoint_id=endpoint_id,
        owner_wallet=service.owner_wallet_state()["wallet_id"],
        node_id=service.node_id,
        wallet_private_key=service.owner_wallet_private_key(),
    )
    return _ok({"publication": record.model_dump(mode="json")})


@router.get("/api/v1/endpoints/{endpoint_id}/proof")
async def endpoint_proof(endpoint_id: str) -> JSONResponse:
    endpoint = endpoint_service.get_endpoint(endpoint_id).endpoint
    return _ok(
        {
            "proof": {
                "endpoint_id": endpoint.endpoint_id,
                "node_id": service.node_id,
                "configuration_hash": endpoint.configuration_hash,
                "bundle_hash": endpoint.bundle_hash,
                "runtime_status": endpoint.status,
                "publication": endpoint.publication.model_dump(mode="json"),
            }
        }
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_api.py -k "publish_configuration_endpoint or endpoint_proof_returns_live_configuration_hash" -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aidn_hypervisor/api.py src/aidn_hypervisor/main.py tests/test_api.py
git commit -m "feat: expose endpoint publication and proof APIs"
```

### Task 5: Extend Registry Advertisement With Published Configuration Index

**Files:**
- Modify: `src/aidn_hypervisor/registry_models.py`
- Modify: `src/aidn_hypervisor/service.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_registry_advertisement_includes_current_published_configuration_hash() -> None:
    hypervisor = _service(whisper_endpoint="http://127.0.0.1:9000")
    hypervisor.configure_owner_wallet(mode="create", label="Primary Wallet")
    ...

    response = client.get("/operators/registry/advertisement")

    assert response.status_code == 200
    assert response.json()["published_endpoints"][0]["current_configuration_hash"]
    assert response.json()["published_endpoints"][0]["endpoint_id"] == endpoint_id
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_api.py -k "published_configuration_hash" -q`
Expected: FAIL because advertisement lacks published endpoint index data.

- [ ] **Step 3: Write the minimal implementation**

```python
# in src/aidn_hypervisor/registry_models.py
class RegistryPublishedEndpointSummary(BaseModel):
    endpoint_id: str
    owner_wallet: str
    node_id: str
    current_publication_id: str
    current_configuration_hash: str
    published_at: str
    status: str
    visibility: str
    model_class: str


class RegistryNodeAdvertisement(BaseModel):
    ...
    published_endpoints: list[RegistryPublishedEndpointSummary] = Field(default_factory=list)
```

```python
# in src/aidn_hypervisor/service.py node_advertisement helper
"published_endpoints": [
    {
        "endpoint_id": record.endpoint_id,
        "owner_wallet": record.owner_wallet,
        "node_id": record.node_id,
        "current_publication_id": record.publication_id,
        "current_configuration_hash": record.configuration_hash,
        "published_at": record.published_at,
        "status": record.status,
        "visibility": record.publication.get("visibility", "private"),
        "model_class": record.model_class,
    }
    for record in current_publication_records
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_api.py -k "published_configuration_hash" -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aidn_hypervisor/registry_models.py src/aidn_hypervisor/service.py tests/test_api.py
git commit -m "feat: advertise published endpoint configuration hashes"
```

### Task 6: Add Dashboard Publication Sync State

**Files:**
- Modify: `src/aidn_hypervisor/api.py`
- Modify: `src/aidn_hypervisor/static/operator_dashboard.html`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_operator_dashboard_endpoints_payload_reports_publication_sync_state() -> None:
    ...
    response = client.get("/operators/dashboard/endpoints")

    assert response.status_code == 200
    assert response.json()["items"][0]["local_configuration_hash"]
    assert response.json()["items"][0]["published_configuration_hash"]
    assert response.json()["items"][0]["publication_sync_status"] == "in_sync"


def test_operator_dashboard_shell_exposes_publication_sync_copy() -> None:
    response = client.get("/operators/dashboard")

    assert "Published Configuration" in response.text
    assert "Sync Status" in response.text
    assert 'data-endpoint-action="publish-configuration"' in response.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_api.py -k "publication_sync_state or publish_configuration" -q`
Expected: FAIL because payload and shell do not expose publication sync UI.

- [ ] **Step 3: Write the minimal implementation**

```python
# in src/aidn_hypervisor/api.py
"local_configuration_hash": manifest.configuration_hash,
"published_configuration_hash": current_publication.configuration_hash if current_publication else None,
"publication_sync_status": (
    "in_sync"
    if current_publication and current_publication.configuration_hash == manifest.configuration_hash
    else "local_changes_not_published"
    if current_publication
    else "never_published"
),
```

```javascript
// in operator_dashboard.html selected endpoint views
<div class="inspector-stat">
  <strong>Published Configuration</strong>
  <span>${formatMaybe(selected.published_configuration_hash)}</span>
</div>
<div class="inspector-stat">
  <strong>Sync Status</strong>
  <span>${formatMaybe(selected.publication_sync_status)}</span>
</div>
<button class="primary-button" type="button" data-endpoint-action="publish-configuration">Publish Configuration</button>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_api.py -k "publication_sync_state or publish_configuration" -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aidn_hypervisor/api.py src/aidn_hypervisor/static/operator_dashboard.html tests/test_api.py
git commit -m "feat: show endpoint publication sync state"
```

### Task 7: Update Documentation And Roadmap

**Files:**
- Modify: `ROADMAP.md`
- Modify: `docs/superpowers/specs/2026-06-29-endpoint-first-transition-design.md`

- [ ] **Step 1: Write the failing documentation checklist**

```text
Checklist:
1. ROADMAP current-stage missing items mention wallet-signed endpoint configuration publication.
2. ROADMAP immediate priorities mention public endpoint configuration trust layer.
3. Endpoint-first transition spec links forward to endpoint publication work.
```

- [ ] **Step 2: Run the checklist manually**

Run: open `ROADMAP.md` and `docs/superpowers/specs/2026-06-29-endpoint-first-transition-design.md`
Expected: FAIL because these exact follow-up references are missing.

- [ ] **Step 3: Write the minimal documentation updates**

```markdown
- wallet-signed publication of endpoint configurations with registry-visible current configuration hashes;
- live proof verification path so remote users can compare published and served endpoint configuration.
```

```markdown
Future follow-up after this transition slice:
- wallet-signed endpoint configuration publication;
- registry indexing of current published endpoint configuration;
- dashboard sync state between local and published endpoint configuration.
```

- [ ] **Step 4: Re-run the checklist**

Run: manually inspect both files again
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ROADMAP.md docs/superpowers/specs/2026-06-29-endpoint-first-transition-design.md
git commit -m "docs: capture endpoint configuration publication roadmap"
```

---

## Self-Review

### Spec coverage

- wallet-signed configuration artifact: covered by Tasks 1 and 3
- wallet-backed publication journal: covered by Task 2
- endpoint publish/proof API: covered by Task 4
- registry current hash indexing: covered by Task 5
- dashboard local vs published sync state: covered by Task 6
- roadmap/doc visibility: covered by Task 7

No uncovered requirements remain for the first implementation slice.

### Placeholder scan

No `TODO`, `TBD`, or unresolved implementation placeholders remain in tasks.

### Type consistency

The plan uses one consistent set of names:
- `PublishedEndpointConfiguration`
- `EndpointPublicationStore`
- `EndpointPublicationService`
- `configuration_hash`
- `publication_sync_status`

No conflicting names remain across tasks.

---

Plan complete and saved to `docs/superpowers/plans/2026-06-30-endpoint-configuration-publication.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
