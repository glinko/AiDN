# Registry Object Durable Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a durable snapshot-backed local Registry Object store so standalone `RegistryService` objects survive process restarts without changing current read semantics.

**Architecture:** Keep `RegistryService` as the public owner of standalone Registry Object ingestion and lookup, but add an optional snapshot file boundary for `_registry_objects`. The service should load a versioned JSON snapshot on startup, persist atomically after successful mutations, preserve payload and `_source` metadata, and continue to treat node-backed advertisement objects as compatibility fallback rather than part of the persisted store.

**Tech Stack:** Python, pathlib, json, tempfile-style atomic replace, pytest

---

## File Map

- Modify: `C:\Users\admin\Documents\New project 3\AiDN\src\aidn_hypervisor\registry_service.py`
  - Add snapshot path support, load/save helpers, batch-aware persistence, and explicit invalid-snapshot failure behavior.
- Modify: `C:\Users\admin\Documents\New project 3\AiDN\tests\test_registry_service.py`
  - Add restart-style durability coverage, malformed snapshot coverage, and batch persistence assertions.
- Modify: `C:\Users\admin\Documents\New project 3\AiDN\ROADMAP.md`
  - Move Registry object status from in-memory-only persistence to local durable persistence, while keeping manifests/retention/replication listed as remaining gaps.
- Modify: `C:\Users\admin\Documents\New project 3\AiDN\docs\superpowers\specs\2026-07-13-rfc-implementation-alignment-audit.md`
  - Update the alignment matrix and next-step wording to reflect durable local persistence being done while broader Registry lifecycle work remains open.

## Constraints

- Preserve current `RegistryService` public read semantics for `list_registry_objects()` and `get_registry_object()`.
- Persist only the standalone `_registry_objects` store in this slice.
- Do not persist `_nodes`, manifests, retention state, replication state, or Snapshot Provider data in this slice.
- Persist after a successful `upsert_registry_object()` and once after a successful `ingest_registry_objects()` batch.
- Invalid or incompatible snapshot files must fail explicitly during service construction.
- Do not create commits during plan execution; leave the slice uncommitted for main-session review because the branch already carries broader RFC-alignment work.

### Task 1: Add Failing Durability Tests Around Snapshot Load/Save

**Files:**
- Modify: `C:\Users\admin\Documents\New project 3\AiDN\tests\test_registry_service.py`
- Test: `C:\Users\admin\Documents\New project 3\AiDN\tests\test_registry_service.py`

- [ ] **Step 1: Write the failing restart and snapshot-file tests**

Add the following tests near the existing store-backed object coverage:

```python
from pathlib import Path
import json
```

```python
def test_registry_service_persists_store_backed_objects_across_restart(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "registry-objects.json"
    service = RegistryService(snapshot_path=snapshot_path)

    service.upsert_registry_object(
        {
            "object_id": "sha256:stored-restart",
            "object_type": "capability_definition",
            "object_version": "capdef.v1",
            "namespace": "protocol",
            "payload_hash": "sha256:stored-restart-payload",
            "payload_encoding": "canonical_json",
            "source_reference": "llm.chat",
            "payload": {
                "capability_id": "llm.chat",
                "capability_version": "2.1.0",
            },
            "_source": {
                "node_id": "node-local",
                "operator_id": "operator-local",
                "status": "ready",
            },
        }
    )

    restarted = RegistryService(snapshot_path=snapshot_path)
    fetched = restarted.get_registry_object("sha256:stored-restart", include_payload=True)

    assert fetched["payload"]["capability_version"] == "2.1.0"
    assert fetched["sources"] == [
        {"node_id": "node-local", "operator_id": "operator-local", "status": "ready"}
    ]
```

```python
def test_registry_service_writes_versioned_snapshot_file_on_upsert(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "registry-objects.json"
    service = RegistryService(snapshot_path=snapshot_path)

    service.upsert_registry_object(
        {
            "object_id": "sha256:stored-file",
            "object_type": "accounting_contract",
            "object_version": "acctobj.v1",
            "namespace": "usage",
            "payload_hash": "sha256:stored-file-payload",
            "payload_encoding": "canonical_json",
            "source_reference": "endpoint-1",
            "payload": {"accounting_mode": "fixed_price"},
        }
    )

    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))

    assert snapshot["schema_version"] == "registry-object-store.v1"
    assert snapshot["objects"][0]["object_id"] == "sha256:stored-file"
    assert snapshot["objects"][0]["payload"] == {"accounting_mode": "fixed_price"}
```

```python
def test_registry_service_batch_ingest_persists_all_objects_once_per_batch(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "registry-objects.json"
    service = RegistryService(snapshot_path=snapshot_path)

    service.ingest_registry_objects(
        [
            {
                "object_id": "sha256:stored-batch-a",
                "object_type": "capability_definition",
                "object_version": "capdef.v1",
                "namespace": "protocol",
                "payload_hash": "sha256:stored-batch-a-payload",
                "payload_encoding": "canonical_json",
                "source_reference": "llm.chat",
            },
            {
                "object_id": "sha256:stored-batch-b",
                "object_type": "endpoint_feature_profile",
                "object_version": "feature-profile.v1",
                "namespace": "marketplace",
                "payload_hash": "sha256:stored-batch-b-payload",
                "payload_encoding": "canonical_json",
                "source_reference": "adv-pub-1",
            },
        ]
    )

    restarted = RegistryService(snapshot_path=snapshot_path)
    listed = restarted.list_registry_objects()

    assert [item["object_id"] for item in listed] == [
        "sha256:stored-batch-b",
        "sha256:stored-batch-a",
    ]
```

- [ ] **Step 2: Write the failing invalid-snapshot tests**

Add the negative coverage:

```python
def test_registry_service_starts_empty_when_snapshot_path_does_not_exist(tmp_path: Path) -> None:
    service = RegistryService(snapshot_path=tmp_path / "missing.json")

    assert service.list_registry_objects() == []
```

```python
def test_registry_service_rejects_invalid_snapshot_schema_version(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "registry-objects.json"
    snapshot_path.write_text(
        json.dumps({"schema_version": "registry-object-store.v999", "objects": []}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="registry-object-store.v999"):
        RegistryService(snapshot_path=snapshot_path)
```

```python
def test_registry_service_rejects_malformed_snapshot_payload(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "registry-objects.json"
    snapshot_path.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(ValueError, match="Malformed registry object snapshot"):
        RegistryService(snapshot_path=snapshot_path)
```

- [ ] **Step 3: Run the durability tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_registry_service.py -q
```

Expected: FAIL because `RegistryService.__init__()` does not accept `snapshot_path`, does not load a snapshot, and does not write any file after store mutations.

### Task 2: Implement Snapshot-Backed Durable Persistence In `RegistryService`

**Files:**
- Modify: `C:\Users\admin\Documents\New project 3\AiDN\src\aidn_hypervisor\registry_service.py`
- Test: `C:\Users\admin\Documents\New project 3\AiDN\tests\test_registry_service.py`

- [ ] **Step 1: Add snapshot constants and constructor support**

Update imports and constructor setup:

```python
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import time
```

```python
_REGISTRY_OBJECT_SNAPSHOT_SCHEMA_VERSION = "registry-object-store.v1"


class RegistryService:
    def __init__(
        self,
        *,
        stale_grace_seconds: int = 30,
        snapshot_path: str | Path | None = None,
    ) -> None:
        self.stale_grace_seconds = stale_grace_seconds
        self._nodes: dict[str, dict] = {}
        self._registry_objects: dict[str, dict] = {}
        self._snapshot_path = Path(snapshot_path) if snapshot_path is not None else None
        self._load_registry_object_snapshot()
```

- [ ] **Step 2: Add load/save helpers with explicit failure behavior**

Add the helper methods near the registry-object helpers:

```python
    def _load_registry_object_snapshot(self) -> None:
        if self._snapshot_path is None or not self._snapshot_path.exists():
            return
        try:
            snapshot = json.loads(self._snapshot_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Malformed registry object snapshot: {self._snapshot_path}"
            ) from exc

        schema_version = snapshot.get("schema_version")
        if schema_version != _REGISTRY_OBJECT_SNAPSHOT_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported registry object snapshot schema version: {schema_version}"
            )

        objects = snapshot.get("objects")
        if not isinstance(objects, list):
            raise ValueError("Registry object snapshot must contain an objects list")

        for record in objects:
            self.upsert_registry_object(record, persist=False)
```

```python
    def _persist_registry_object_snapshot(self) -> None:
        if self._snapshot_path is None:
            return
        self._snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot = {
            "schema_version": _REGISTRY_OBJECT_SNAPSHOT_SCHEMA_VERSION,
            "objects": [
                deepcopy(self._registry_objects[object_id])
                for object_id in sorted(self._registry_objects)
            ],
        }
        temp_path = self._snapshot_path.with_suffix(self._snapshot_path.suffix + ".tmp")
        temp_path.write_text(
            json.dumps(snapshot, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        temp_path.replace(self._snapshot_path)
```

- [ ] **Step 3: Make mutation paths persistence-aware without changing read behavior**

Update the write methods:

```python
    def upsert_registry_object(self, record: dict, *, persist: bool = True) -> dict:
        object_id = str(record["object_id"])
        normalized = deepcopy(record)
        existing = self._registry_objects.get(object_id)
        if existing is not None and existing != normalized:
            raise ValueError(f"Conflicting registry object for {object_id}")
        self._registry_objects[object_id] = normalized
        if persist:
            self._persist_registry_object_snapshot()
        return deepcopy(self._registry_objects[object_id])
```

```python
    def ingest_registry_objects(self, records: list[dict]) -> list[dict]:
        stored: list[dict] = []
        for record in records:
            stored.append(self.upsert_registry_object(record, persist=False))
        if stored:
            self._persist_registry_object_snapshot()
        return stored
```

Leave `list_registry_objects()` and `get_registry_object()` semantics unchanged apart from now seeing reloaded `_registry_objects`.

- [ ] **Step 4: Run the targeted durability tests to verify they pass**

Run:

```powershell
python -m pytest tests/test_registry_service.py -q
```

Expected: PASS with both the new snapshot tests and the existing store-vs-node compatibility tests green.

### Task 3: Cover Conflict Semantics After Reload

**Files:**
- Modify: `C:\Users\admin\Documents\New project 3\AiDN\tests\test_registry_service.py`
- Test: `C:\Users\admin\Documents\New project 3\AiDN\tests\test_registry_service.py`

- [ ] **Step 1: Write the failing persisted-conflict regression test**

Add a restart conflict case:

```python
def test_registry_service_preserved_snapshot_conflicts_with_node_backed_duplicate(
    tmp_path: Path,
    monkeypatch,
) -> None:
    ready_time = datetime.fromisoformat("2026-07-05T14:00:05+00:00").timestamp()
    monkeypatch.setattr("aidn_hypervisor.registry_service.time.time", lambda: ready_time)
    snapshot_path = tmp_path / "registry-objects.json"

    seeded = RegistryService(snapshot_path=snapshot_path)
    seeded.upsert_registry_object(
        {
            "object_id": "sha256:shared-restart",
            "object_type": "capability_definition",
            "object_version": "capdef.v1",
            "namespace": "protocol",
            "payload_hash": "sha256:stored-shared-payload",
            "payload_encoding": "canonical_json",
            "source_reference": "llm.chat",
            "payload": {"capability_version": "2.1.0"},
        }
    )

    restarted = RegistryService(snapshot_path=snapshot_path)
    restarted.upsert_node(
        _node(
            "node-a",
            heartbeat_at="2026-07-05T14:00:00+00:00",
            canonical_registry_objects=[
                {
                    "object_id": "sha256:shared-restart",
                    "object_type": "capability_definition",
                    "object_version": "capdef.v1",
                    "namespace": "protocol",
                    "payload_hash": "sha256:node-shared-payload",
                    "payload_encoding": "canonical_json",
                    "source_reference": "llm.chat",
                    "payload": {"capability_version": "2.0.0"},
                }
            ],
        )
    )

    with pytest.raises(ValueError, match="sha256:shared-restart"):
        restarted.get_registry_object("sha256:shared-restart", include_payload=True)
```

- [ ] **Step 2: Run the focused conflict test to verify it fails if reload state is broken**

Run:

```powershell
python -m pytest tests/test_registry_service.py::test_registry_service_preserved_snapshot_conflicts_with_node_backed_duplicate -v
```

Expected: PASS once restart-loaded objects participate in the same conflict checks as live-ingested store objects. If it fails, the reload path is bypassing the existing conflict semantics.

- [ ] **Step 3: Tighten helper behavior only if the new conflict test exposes a gap**

If reload state does not behave exactly like live-ingested store state, normalize by reusing the same write path:

```python
        for record in objects:
            self.upsert_registry_object(record, persist=False)
```

Do not add a second normalization code path for snapshot loads.

- [ ] **Step 4: Re-run the full registry service file**

Run:

```powershell
python -m pytest tests/test_registry_service.py -q
```

Expected: PASS

### Task 4: Sync Documentation And Verify The Whole Repository

**Files:**
- Modify: `C:\Users\admin\Documents\New project 3\AiDN\ROADMAP.md`
- Modify: `C:\Users\admin\Documents\New project 3\AiDN\docs\superpowers\specs\2026-07-13-rfc-implementation-alignment-audit.md`

- [ ] **Step 1: Update roadmap language from in-memory-only to durable local persistence**

Replace and tighten wording such as:

```markdown
- `RegistryService` now also maintains a standalone local in-memory Registry Object store, and local operator object routes ingest projected canonical objects into that store while preserving local node provenance for returned sources;
```

with:

```markdown
- `RegistryService` now maintains a standalone local Registry Object store with snapshot-backed durable persistence, and local operator object routes ingest projected canonical objects into that store while preserving local node provenance for returned sources;
```

And replace:

```markdown
- but it still lacks durable persistence beyond process memory, manifests, retention policy enforcement, and replication of those objects as first-class protocol data.
```

with:

```markdown
- but it still lacks retention policy enforcement, manifests, and replication of those objects as first-class protocol data.
```

- [ ] **Step 2: Update the alignment audit matrix and next-step language**

Adjust the `Accounting contract` and `Registry discovery` gap text from:

```markdown
There is still no durable object persistence beyond process memory, and no retention/manifests/replication yet.
```

to:

```markdown
There is now durable local snapshot persistence for standalone Registry Objects, but no retention/manifests/replication yet.
```

And update the executive summary conclusion from:

```markdown
The right next move is a narrow Registry durability slice
```

to:

```markdown
The right next move is lifecycle and manifest work on top of the new durable Registry object store
```

- [ ] **Step 3: Run targeted verification**

Run:

```powershell
python -m pytest tests/test_registry_service.py tests/test_api.py -q
```

Expected: PASS. `tests/test_api.py` should stay green without code changes because API fallback already ingests projected canonical objects into the standalone store boundary.

- [ ] **Step 4: Run full verification and diff hygiene**

Run:

```powershell
python -m pytest -q
git diff --check
```

Expected:

- `python -m pytest -q`: PASS
- `git diff --check`: no content errors; CRLF warnings are acceptable if they are the only output

- [ ] **Step 5: Leave the workspace ready for review**

Confirm in the handoff:

```text
- no commit created in this slice
- standalone Registry Objects now survive service restart when the same snapshot path is reused
- payloads and `_source` metadata survive reload
- manifests, retention, and replication are still intentionally out of scope
```

## Self-Review

- Spec coverage: covered snapshot file format, constructor load behavior, write-after-mutation semantics, restart persistence, malformed snapshot handling, and post-slice doc sync.
- Placeholder scan: no TBD/TODO placeholders remain.
- Type consistency: plan consistently uses `snapshot_path`, `_persist_registry_object_snapshot`, `_load_registry_object_snapshot`, `upsert_registry_object(..., persist=False)`, and the existing `RegistryService` read methods.
