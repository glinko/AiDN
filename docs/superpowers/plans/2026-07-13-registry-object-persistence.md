# Registry Object Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a standalone in-memory Registry Object store inside `RegistryService`, keep node-backed compatibility fallback, and route local operator object APIs through the new store boundary.

**Architecture:** `RegistryService` becomes the primary owner of immutable local registry objects through a separate `_registry_objects` map keyed by `object_id`. Read paths prefer store-backed objects and only fall back to `nodes[].canonical_registry_objects` when a stored copy is absent, while the API local fallback ingests the local node's projected canonical objects into the standalone store before serving list/get routes.

**Tech Stack:** Python, Pydantic, FastAPI, pytest

---

## File Map

- Modify: `C:\Users\admin\Documents\New project 3\AiDN\src\aidn_hypervisor\registry_service.py`
  - Add standalone object storage, ingestion APIs, conflict handling, and merged read path.
- Modify: `C:\Users\admin\Documents\New project 3\AiDN\src\aidn_hypervisor\api.py`
  - Ingest local projected registry objects into the fallback `RegistryService`.
- Modify: `C:\Users\admin\Documents\New project 3\AiDN\tests\test_registry_service.py`
  - Add service-level red/green coverage for store-backed objects and precedence rules.
- Modify: `C:\Users\admin\Documents\New project 3\AiDN\tests\test_api.py`
  - Add API coverage proving local routes now work through the standalone store path.
- Modify: `C:\Users\admin\Documents\New project 3\AiDN\ROADMAP.md`
  - Update current implementation status from payload retrieval to standalone local object persistence.
- Modify: `C:\Users\admin\Documents\New project 3\AiDN\docs\superpowers\specs\2026-07-13-rfc-implementation-alignment-audit.md`
  - Update alignment notes so the next gap is beyond local standalone persistence.

## Constraints

- Keep default response shapes backward-compatible.
- Do not remove `canonical_registry_objects` from node advertisements in this slice.
- Do not add durable disk persistence, manifests, retention, or replication.
- Do not commit in this slice; leave changes uncommitted for user review.

### Task 1: Add Standalone Registry Object Store In `RegistryService`

**Files:**
- Modify: `C:\Users\admin\Documents\New project 3\AiDN\src\aidn_hypervisor\registry_service.py`
- Test: `C:\Users\admin\Documents\New project 3\AiDN\tests\test_registry_service.py`

- [ ] **Step 1: Write the failing service tests for standalone object ingestion and precedence**

```python
def test_registry_service_lists_store_backed_registry_objects_without_node_advertisement() -> None:
    service = RegistryService()
    service.ingest_registry_objects(
        [
            {
                "object_id": "sha256:capdef-store",
                "object_type": "capability_definition",
                "object_version": "capdef.v1",
                "namespace": "protocol",
                "payload_hash": "sha256:payload-store",
                "payload_encoding": "canonical_json",
                "source_reference": "llm.chat",
                "payload": {
                    "capability_id": "llm.chat",
                    "capability_version": "2.0.0",
                },
            }
        ]
    )

    objects = service.list_registry_objects()

    assert [item["object_id"] for item in objects] == ["sha256:capdef-store"]
    assert objects[0]["source_count"] == 1
    assert objects[0]["sources"][0]["status"] == "stored"


def test_registry_service_prefers_store_backed_registry_object_over_node_backed_copy(
    monkeypatch,
) -> None:
    ready_time = datetime.fromisoformat("2026-07-05T14:00:05+00:00").timestamp()
    monkeypatch.setattr("aidn_hypervisor.registry_service.time.time", lambda: ready_time)
    service = RegistryService()
    service.ingest_registry_objects(
        [
            {
                "object_id": "sha256:capdef-1",
                "object_type": "capability_definition",
                "object_version": "capdef.v1",
                "namespace": "protocol",
                "payload_hash": "sha256:payload-store",
                "payload_encoding": "canonical_json",
                "source_reference": "llm.chat",
                "payload": {"capability_id": "llm.chat", "capability_version": "2.0.0"},
            }
        ]
    )
    service.upsert_node(
        _node(
            "node-a",
            heartbeat_at="2026-07-05T14:00:00+00:00",
            canonical_registry_objects=[
                {
                    "object_id": "sha256:capdef-1",
                    "object_type": "capability_definition",
                    "object_version": "capdef.v1",
                    "namespace": "protocol",
                    "payload_hash": "sha256:payload-node",
                    "payload_encoding": "canonical_json",
                    "source_reference": "llm.chat",
                    "payload": {"capability_id": "llm.chat", "capability_version": "1.9.0"},
                }
            ],
        )
    )

    item = service.get_registry_object("sha256:capdef-1", include_payload=True)

    assert item["payload_hash"] == "sha256:payload-store"
    assert item["payload"]["capability_version"] == "2.0.0"
    assert {source["status"] for source in item["sources"]} == {"stored"}
```

- [ ] **Step 2: Run the service tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_registry_service.py -q
```

Expected: FAIL because `RegistryService` has no standalone object ingestion path and still reads only from `canonical_registry_objects` nested under node advertisements.

- [ ] **Step 3: Implement the standalone object store and merged read path**

```python
class RegistryService:
    def __init__(self, *, stale_grace_seconds: int = 30) -> None:
        self.stale_grace_seconds = stale_grace_seconds
        self._nodes: dict[str, dict] = {}
        self._registry_objects: dict[str, dict] = {}

    def upsert_registry_object(self, record: dict) -> dict:
        object_id = str(record["object_id"])
        normalized = dict(record)
        existing = self._registry_objects.get(object_id)
        if existing is not None and existing != normalized:
            raise ValueError(f"Conflicting registry object for {object_id}")
        self._registry_objects[object_id] = normalized
        return dict(self._registry_objects[object_id])

    def ingest_registry_objects(self, records: list[dict]) -> list[dict]:
        return [self.upsert_registry_object(record) for record in records]

    def _iter_store_backed_registry_objects(self) -> list[dict]:
        return [dict(self._registry_objects[object_id]) for object_id in sorted(self._registry_objects)]
```

And update `list_registry_objects()` so it:

```python
objects_by_id: dict[str, dict] = {}

for item in self._iter_store_backed_registry_objects():
    if query_model.object_type is not None and item.get("object_type") != query_model.object_type:
        continue
    if query_model.namespace is not None and item.get("namespace") != query_model.namespace:
        continue
    if query_model.source_reference is not None and item.get("source_reference") != query_model.source_reference:
        continue
    row = {
        "object_id": str(item["object_id"]),
        "object_type": item["object_type"],
        "object_version": item["object_version"],
        "namespace": item["namespace"],
        "payload_hash": item["payload_hash"],
        "payload_encoding": item["payload_encoding"],
        "source_reference": item["source_reference"],
        "source_count": 1,
        "sources": [
            {
                "node_id": None,
                "operator_id": None,
                "status": "stored",
            }
        ],
    }
    if query_model.include_payload and item.get("payload") is not None:
        row["payload"] = item["payload"]
    objects_by_id[row["object_id"]] = row

for node_id in self._nodes:
    # preserve the current node-backed loop
    # but skip when object_id already exists in objects_by_id
```

- [ ] **Step 4: Run the service tests to verify they pass**

Run:

```powershell
python -m pytest tests/test_registry_service.py -q
```

Expected: PASS with the new standalone store tests green and the existing node-backed compatibility tests still green.

### Task 2: Route Local Operator Object APIs Through Standalone Store

**Files:**
- Modify: `C:\Users\admin\Documents\New project 3\AiDN\src\aidn_hypervisor\api.py`
- Test: `C:\Users\admin\Documents\New project 3\AiDN\tests\test_api.py`

- [ ] **Step 1: Write the failing API tests for local fallback ingestion**

```python
def test_operator_registry_object_endpoint_uses_store_backed_local_fallback() -> None:
    service = _service(with_runtime=False, use_process_manager=True)
    client = TestClient(build_app(service=service))
    advertisement = service.node_advertisement()
    object_id = advertisement["canonical_registry_objects"][0]["object_id"]

    response = client.get(f"/operators/registry/objects/{object_id}?include_payload=true")

    assert response.status_code == 200
    assert response.json()["payload"]["capability_id"] == "llm.chat"
    assert response.json()["sources"][0]["status"] == "stored"


def test_operator_registry_objects_endpoint_lists_store_backed_local_objects() -> None:
    service = _service(with_runtime=False, use_process_manager=True)
    client = TestClient(build_app(service=service))

    response = client.get("/operators/registry/objects")

    assert response.status_code == 200
    capability_definition = next(
        item for item in response.json()["objects"] if item["object_type"] == "capability_definition"
    )
    assert capability_definition["sources"][0]["status"] == "stored"
```

- [ ] **Step 2: Run the API tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_api.py -q
```

Expected: FAIL because `_effective_registry_service()` currently only upserts the node advertisement and never ingests the local canonical registry objects into a standalone store.

- [ ] **Step 3: Implement local fallback ingestion in `build_api_router()`**

```python
def _effective_registry_service() -> RegistryService:
    if registry_service is not None:
        return registry_service
    local_registry = RegistryService()
    advertisement = RegistryNodeAdvertisement(**service.node_advertisement())
    local_registry.upsert_node(advertisement)
    local_registry.ingest_registry_objects(advertisement.canonical_registry_objects)
    return local_registry
```

If needed, normalize the Pydantic records before ingestion:

```python
local_registry.ingest_registry_objects(
    [item.model_dump(mode="json") for item in advertisement.canonical_registry_objects]
)
```

- [ ] **Step 4: Run the API tests to verify they pass**

Run:

```powershell
python -m pytest tests/test_api.py -q
```

Expected: PASS with both existing operator registry route tests and the new store-backed local fallback tests green.

### Task 3: Sync Docs And Run Final Verification

**Files:**
- Modify: `C:\Users\admin\Documents\New project 3\AiDN\ROADMAP.md`
- Modify: `C:\Users\admin\Documents\New project 3\AiDN\docs\superpowers\specs\2026-07-13-rfc-implementation-alignment-audit.md`

- [ ] **Step 1: Update roadmap and audit language**

Apply the following content updates:

```markdown
- registry-backed object views now also support a standalone local object-store boundary inside `RegistryService`, with node-advertisement canonical objects retained as compatibility fallback;
```

And replace wording like:

```markdown
there is still no standalone payload persistence independent of node advertisements
```

with:

```markdown
the repo now has standalone local in-memory object persistence inside `RegistryService`, but still lacks durable persistence, retention policy enforcement, manifests, and replication
```

- [ ] **Step 2: Run the targeted verification commands**

Run:

```powershell
python -m pytest tests/test_registry_service.py tests/test_api.py -q
```

Expected: PASS

- [ ] **Step 3: Run the full verification commands**

Run:

```powershell
python -m pytest -q
git diff --check
```

Expected:

- `pytest`: PASS
- `git diff --check`: no content errors; CRLF warnings are acceptable if they are the only output

- [ ] **Step 4: Leave workspace ready for review**

Confirm in the handoff summary:

```text
- no commit created in this slice
- standalone store is now primary for local registry object reads
- node-advertisement canonical objects remain as compatibility fallback
```

## Self-Review

- Spec coverage: covered store introduction, compatibility fallback, local API ingestion, precedence rules, and doc sync.
- Placeholder scan: no TBD/TODO placeholders remain.
- Type consistency: plan consistently uses `ingest_registry_objects`, `upsert_registry_object`, `_registry_objects`, `include_payload`, and existing `RegistryObjectQuery`.
