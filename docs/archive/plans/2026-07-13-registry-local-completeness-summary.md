# Registry Local Completeness Summary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a versioned local completeness summary contract to `RegistryService` so the durable standalone Registry Object store can be inspected with deterministic counts, payload totals, and basic integrity flags.

**Architecture:** Extend the existing registry service layer with typed summary models plus one on-demand builder method that reads only from `self._registry_objects`. Keep the slice service-local: no API, no persisted manifest object, no node-backed transient records in the summary, and no replication or profile completeness logic.

**Tech Stack:** Python, Pydantic, pytest, existing `aidn_hypervisor` registry service/model modules

---

## File Structure

- Modify: `src/aidn_hypervisor/registry_models.py`
  - Add typed local completeness summary models and issue/totals/integrity submodels.
- Modify: `src/aidn_hypervisor/registry_service.py`
  - Add summary version constants, required-field contract, payload byte helper, issue builder, and `get_local_registry_completeness_summary()`.
- Modify: `tests/test_registry_service.py`
  - Add service-level coverage for empty-store summaries, mixed aggregation, payload byte totals, integrity anomalies, and restart-stable summaries.
- Modify: `ROADMAP.md`
  - Update the registry gap wording so it reflects that a local completeness summary now exists but manifest identity/retention/replication still do not.
- Modify: `docs/archive/specifications/2026-07-13-rfc-implementation-alignment-audit.md`
  - Update the RFC alignment audit to reflect the new local completeness summary capability and the remaining manifest/retention gaps.

## Task 1: Add The Typed Summary Contract And Empty-Store Summary

**Files:**
- Modify: `src/aidn_hypervisor/registry_models.py`
- Modify: `src/aidn_hypervisor/registry_service.py`
- Test: `tests/test_registry_service.py`

- [ ] **Step 1: Write the failing empty-store summary test**

Add this test near the existing store-backed registry object tests in `tests/test_registry_service.py`:

```python
def test_registry_service_returns_empty_local_completeness_summary() -> None:
    service = RegistryService()

    summary = service.get_local_registry_completeness_summary()

    assert summary.summary_version == "registry-local-completeness-summary.v1"
    assert summary.snapshot_schema_version == "registry-object-store.v1"
    assert summary.store_totals.total_object_count == 0
    assert summary.store_totals.payload_object_count == 0
    assert summary.store_totals.payload_bytes_total == 0
    assert summary.by_namespace == {}
    assert summary.by_object_type == {}
    assert summary.integrity.object_count_matches_store is True
    assert summary.integrity.all_object_ids_unique is True
    assert summary.integrity.all_required_fields_present is True
    assert summary.integrity.payload_hash_coverage_count == 0
    assert summary.integrity.issues == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
python -m pytest tests/test_registry_service.py::test_registry_service_returns_empty_local_completeness_summary -v
```

Expected: `FAIL` with `AttributeError` because `RegistryService` does not yet expose `get_local_registry_completeness_summary`.

- [ ] **Step 3: Add the summary models and the minimum service method**

In `src/aidn_hypervisor/registry_models.py`, add these models after `RegistryObjectQuery`:

```python
class RegistryCompletenessIssue(BaseModel):
    code: str
    object_id: str | None = None
    field: str | None = None
    detail: str | None = None


class RegistryCompletenessTotals(BaseModel):
    total_object_count: int = Field(ge=0)
    payload_object_count: int = Field(ge=0)
    payload_bytes_total: int = Field(ge=0)


class RegistryCompletenessIntegrity(BaseModel):
    object_count_matches_store: bool
    all_object_ids_unique: bool
    all_required_fields_present: bool
    payload_hash_coverage_count: int = Field(ge=0)
    issues: list[RegistryCompletenessIssue] = Field(default_factory=list)


class RegistryLocalCompletenessSummary(BaseModel):
    summary_version: str
    generated_at: str
    snapshot_schema_version: str
    store_totals: RegistryCompletenessTotals
    by_namespace: dict[str, int] = Field(default_factory=dict)
    by_object_type: dict[str, int] = Field(default_factory=dict)
    integrity: RegistryCompletenessIntegrity
```

Update `src/aidn_hypervisor/registry_service.py` imports:

```python
from aidn_hypervisor.registry_models import (
    RegistryDiscoveryQuery,
    RegistryLocalCompletenessSummary,
    RegistryCompletenessIntegrity,
    RegistryCompletenessTotals,
    RegistryNodeAdvertisement,
    RegistryObjectQuery,
)
```

Add constants near `_REGISTRY_OBJECT_SNAPSHOT_SCHEMA_VERSION`:

```python
_LOCAL_REGISTRY_COMPLETENESS_SUMMARY_VERSION = (
    "registry-local-completeness-summary.v1"
)
_REQUIRED_REGISTRY_OBJECT_FIELDS = (
    "object_id",
    "object_type",
    "object_version",
    "namespace",
    "payload_hash",
    "payload_encoding",
    "source_reference",
)
```

Add the minimum service method to `RegistryService`:

```python
def get_local_registry_completeness_summary(self) -> RegistryLocalCompletenessSummary:
    return RegistryLocalCompletenessSummary(
        summary_version=_LOCAL_REGISTRY_COMPLETENESS_SUMMARY_VERSION,
        generated_at=datetime.utcnow().isoformat() + "Z",
        snapshot_schema_version=_REGISTRY_OBJECT_SNAPSHOT_SCHEMA_VERSION,
        store_totals=RegistryCompletenessTotals(
            total_object_count=len(self._registry_objects),
            payload_object_count=0,
            payload_bytes_total=0,
        ),
        by_namespace={},
        by_object_type={},
        integrity=RegistryCompletenessIntegrity(
            object_count_matches_store=True,
            all_object_ids_unique=True,
            all_required_fields_present=True,
            payload_hash_coverage_count=0,
            issues=[],
        ),
    )
```

- [ ] **Step 4: Run the test to verify it passes**

Run:

```bash
python -m pytest tests/test_registry_service.py::test_registry_service_returns_empty_local_completeness_summary -v
```

Expected: `PASS`

- [ ] **Step 5: Commit**

```bash
git add src/aidn_hypervisor/registry_models.py src/aidn_hypervisor/registry_service.py tests/test_registry_service.py
git commit -m "Add local registry completeness summary contract"
```

## Task 2: Add Aggregation Counts And Payload Byte Totals

**Files:**
- Modify: `src/aidn_hypervisor/registry_service.py`
- Test: `tests/test_registry_service.py`

- [ ] **Step 1: Write the failing mixed-object aggregation test**

Add this test in `tests/test_registry_service.py`:

```python
def test_registry_service_summarizes_local_store_counts_and_payload_bytes() -> None:
    service = RegistryService()
    payload_one = {"capability_id": "llm.chat", "status": "active"}
    payload_two = {"pricing_model": "fixed", "unit_price_q": 2}

    service.ingest_registry_objects(
        [
            {
                "object_id": "sha256:capdef-1",
                "object_type": "capability_definition",
                "object_version": "1.0",
                "namespace": "protocol",
                "payload_hash": "sha256:payload-capdef-1",
                "payload_encoding": "canonical_json",
                "source_reference": "capdef:llm.chat:v1",
                "payload": payload_one,
            },
            {
                "object_id": "sha256:pricing-1",
                "object_type": "pricing_policy",
                "object_version": "1.0",
                "namespace": "marketplace",
                "payload_hash": "sha256:payload-pricing-1",
                "payload_encoding": "canonical_json",
                "source_reference": "pricing:endpoint-1:v1",
                "payload": payload_two,
            },
            {
                "object_id": "sha256:pricing-2",
                "object_type": "pricing_policy",
                "object_version": "1.0",
                "namespace": "marketplace",
                "payload_hash": "sha256:payload-pricing-2",
                "payload_encoding": "canonical_json",
                "source_reference": "pricing:endpoint-2:v1",
            },
        ]
    )

    summary = service.get_local_registry_completeness_summary()
    expected_payload_bytes = sum(
        len(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
                "utf-8"
            )
        )
        for payload in (payload_one, payload_two)
    )

    assert summary.store_totals.total_object_count == 3
    assert summary.store_totals.payload_object_count == 2
    assert summary.store_totals.payload_bytes_total == expected_payload_bytes
    assert summary.by_namespace == {"marketplace": 2, "protocol": 1}
    assert summary.by_object_type == {
        "capability_definition": 1,
        "pricing_policy": 2,
    }
    assert summary.integrity.payload_hash_coverage_count == 3
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
python -m pytest tests/test_registry_service.py::test_registry_service_summarizes_local_store_counts_and_payload_bytes -v
```

Expected: `FAIL` because the current summary method returns zeroed aggregates.

- [ ] **Step 3: Implement deterministic aggregation and payload byte accounting**

Add this helper to `src/aidn_hypervisor/registry_service.py`:

```python
def _payload_size_bytes(self, payload: object) -> int:
    return len(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    )
```

Replace `get_local_registry_completeness_summary()` with:

```python
def get_local_registry_completeness_summary(self) -> RegistryLocalCompletenessSummary:
    by_namespace: dict[str, int] = {}
    by_object_type: dict[str, int] = {}
    payload_object_count = 0
    payload_bytes_total = 0
    payload_hash_coverage_count = 0

    for object_id in sorted(self._registry_objects):
        record = self._registry_objects[object_id]
        if not isinstance(record, dict):
            raise ValueError(
                f"Registry object store contains non-object record for {object_id}"
            )

        namespace = record.get("namespace")
        if isinstance(namespace, str) and namespace:
            by_namespace[namespace] = by_namespace.get(namespace, 0) + 1

        object_type = record.get("object_type")
        if isinstance(object_type, str) and object_type:
            by_object_type[object_type] = by_object_type.get(object_type, 0) + 1

        payload_hash = record.get("payload_hash")
        if isinstance(payload_hash, str) and payload_hash:
            payload_hash_coverage_count += 1

        if record.get("payload") is not None:
            payload_object_count += 1
            payload_bytes_total += self._payload_size_bytes(record["payload"])

    return RegistryLocalCompletenessSummary(
        summary_version=_LOCAL_REGISTRY_COMPLETENESS_SUMMARY_VERSION,
        generated_at=datetime.utcnow().isoformat() + "Z",
        snapshot_schema_version=_REGISTRY_OBJECT_SNAPSHOT_SCHEMA_VERSION,
        store_totals=RegistryCompletenessTotals(
            total_object_count=len(self._registry_objects),
            payload_object_count=payload_object_count,
            payload_bytes_total=payload_bytes_total,
        ),
        by_namespace=by_namespace,
        by_object_type=by_object_type,
        integrity=RegistryCompletenessIntegrity(
            object_count_matches_store=True,
            all_object_ids_unique=True,
            all_required_fields_present=True,
            payload_hash_coverage_count=payload_hash_coverage_count,
            issues=[],
        ),
    )
```

- [ ] **Step 4: Run the targeted tests**

Run:

```bash
python -m pytest tests/test_registry_service.py::test_registry_service_returns_empty_local_completeness_summary tests/test_registry_service.py::test_registry_service_summarizes_local_store_counts_and_payload_bytes -q
```

Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add src/aidn_hypervisor/registry_service.py tests/test_registry_service.py
git commit -m "Add local registry completeness aggregation"
```

## Task 3: Add Integrity Issues, Restart Stability, And RFC Status Sync

**Files:**
- Modify: `src/aidn_hypervisor/registry_service.py`
- Modify: `tests/test_registry_service.py`
- Modify: `ROADMAP.md`
- Modify: `docs/archive/specifications/2026-07-13-rfc-implementation-alignment-audit.md`

- [ ] **Step 1: Write failing integrity and restart regression tests**

Add these tests to `tests/test_registry_service.py`:

```python
def test_registry_service_surfaces_missing_required_fields_in_summary_issues() -> None:
    service = RegistryService()
    service._registry_objects["sha256:broken-1"] = {
        "object_id": "sha256:broken-1",
        "object_version": "1.0",
        "payload_hash": "sha256:broken-payload",
        "payload_encoding": "canonical_json",
        "source_reference": "broken:1",
    }

    summary = service.get_local_registry_completeness_summary()

    assert summary.store_totals.total_object_count == 1
    assert summary.integrity.all_required_fields_present is False
    assert summary.integrity.object_count_matches_store is True
    assert summary.integrity.all_object_ids_unique is True
    assert {(issue.code, issue.field) for issue in summary.integrity.issues} == {
        ("missing_required_field", "namespace"),
        ("missing_required_field", "object_type"),
    }


def test_registry_service_raises_for_non_mapping_store_record_in_summary() -> None:
    service = RegistryService()
    service._registry_objects["sha256:bad-shape"] = "not-a-dict"

    with pytest.raises(
        ValueError,
        match="Registry object store contains non-object record for sha256:bad-shape",
    ):
        service.get_local_registry_completeness_summary()


def test_registry_service_local_completeness_summary_survives_restart(
    tmp_path: Path,
) -> None:
    snapshot_path = tmp_path / "registry-objects.json"
    payload = {"pricing_model": "fixed", "unit_price_q": 2}
    seeded = RegistryService(snapshot_path=snapshot_path)
    seeded.upsert_registry_object(
        {
            "object_id": "sha256:restart-summary-1",
            "object_type": "pricing_policy",
            "object_version": "1.0",
            "namespace": "marketplace",
            "payload_hash": "sha256:restart-payload-1",
            "payload_encoding": "canonical_json",
            "source_reference": "pricing:restart-1",
            "payload": payload,
        }
    )

    before = seeded.get_local_registry_completeness_summary()
    restarted = RegistryService(snapshot_path=snapshot_path)
    after = restarted.get_local_registry_completeness_summary()

    assert after.summary_version == before.summary_version
    assert after.snapshot_schema_version == before.snapshot_schema_version
    assert after.store_totals == before.store_totals
    assert after.by_namespace == before.by_namespace
    assert after.by_object_type == before.by_object_type
    assert after.integrity == before.integrity
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run:

```bash
python -m pytest tests/test_registry_service.py::test_registry_service_surfaces_missing_required_fields_in_summary_issues tests/test_registry_service.py::test_registry_service_raises_for_non_mapping_store_record_in_summary tests/test_registry_service.py::test_registry_service_local_completeness_summary_survives_restart -q
```

Expected: at least the missing-required-fields test fails because the current summary always reports `all_required_fields_present=True` with no issues.

- [ ] **Step 3: Implement integrity issue handling and update status docs**

In `src/aidn_hypervisor/registry_service.py`, add the missing import:

```python
from aidn_hypervisor.registry_models import (
    RegistryCompletenessIssue,
    RegistryCompletenessIntegrity,
    RegistryCompletenessTotals,
    RegistryDiscoveryQuery,
    RegistryLocalCompletenessSummary,
    RegistryNodeAdvertisement,
    RegistryObjectQuery,
)
```

Add this helper:

```python
def _registry_object_summary_issues(
    self,
    *,
    object_id: str,
    record: dict,
) -> list[RegistryCompletenessIssue]:
    issues: list[RegistryCompletenessIssue] = []
    for field in _REQUIRED_REGISTRY_OBJECT_FIELDS:
        value = record.get(field)
        if value is None or (isinstance(value, str) and not value):
            issues.append(
                RegistryCompletenessIssue(
                    code="missing_required_field",
                    object_id=object_id,
                    field=field,
                    detail=f"Stored record is missing required field {field}",
                )
            )
    return issues
```

Update `get_local_registry_completeness_summary()` so it accumulates issues and derives `all_required_fields_present` from them:

```python
def get_local_registry_completeness_summary(self) -> RegistryLocalCompletenessSummary:
    by_namespace: dict[str, int] = {}
    by_object_type: dict[str, int] = {}
    payload_object_count = 0
    payload_bytes_total = 0
    payload_hash_coverage_count = 0
    issues: list[RegistryCompletenessIssue] = []

    for object_id in sorted(self._registry_objects):
        record = self._registry_objects[object_id]
        if not isinstance(record, dict):
            raise ValueError(
                f"Registry object store contains non-object record for {object_id}"
            )

        issues.extend(
            self._registry_object_summary_issues(object_id=object_id, record=record)
        )

        namespace = record.get("namespace")
        if isinstance(namespace, str) and namespace:
            by_namespace[namespace] = by_namespace.get(namespace, 0) + 1

        object_type = record.get("object_type")
        if isinstance(object_type, str) and object_type:
            by_object_type[object_type] = by_object_type.get(object_type, 0) + 1

        payload_hash = record.get("payload_hash")
        if isinstance(payload_hash, str) and payload_hash:
            payload_hash_coverage_count += 1

        if record.get("payload") is not None:
            payload_object_count += 1
            payload_bytes_total += self._payload_size_bytes(record["payload"])

    return RegistryLocalCompletenessSummary(
        summary_version=_LOCAL_REGISTRY_COMPLETENESS_SUMMARY_VERSION,
        generated_at=datetime.utcnow().isoformat() + "Z",
        snapshot_schema_version=_REGISTRY_OBJECT_SNAPSHOT_SCHEMA_VERSION,
        store_totals=RegistryCompletenessTotals(
            total_object_count=len(self._registry_objects),
            payload_object_count=payload_object_count,
            payload_bytes_total=payload_bytes_total,
        ),
        by_namespace=by_namespace,
        by_object_type=by_object_type,
        integrity=RegistryCompletenessIntegrity(
            object_count_matches_store=True,
            all_object_ids_unique=True,
            all_required_fields_present=not any(
                issue.code == "missing_required_field" for issue in issues
            ),
            payload_hash_coverage_count=payload_hash_coverage_count,
            issues=issues,
        ),
    )
```

Update `ROADMAP.md` in the registry-alignment section so the current gap wording becomes:

```markdown
- registry-backed object views now support deduplicated `object_id` lookup, filtered listing, durable local snapshot persistence, and a versioned local completeness summary over the standalone store, while manifest identity, retention policy enforcement, and replication remain the next gaps;
```

Update `docs/archive/specifications/2026-07-13-rfc-implementation-alignment-audit.md` in the registry rows and `Registry Lifecycle And Manifest Slice` section so it states:

```markdown
- first local completeness summary scaffolding now exists over the durable local object set;
- manifests, retention policy enforcement, and replication still remain out of scope;
```

- [ ] **Step 4: Run the targeted registry suite and sync docs confidence checks**

Run:

```bash
python -m pytest tests/test_registry_service.py -q
```

Expected: all registry service tests pass.

Then run:

```bash
rg -n "local completeness summary|manifest identity|retention policy enforcement|replication" ROADMAP.md docs/archive/specifications/2026-07-13-rfc-implementation-alignment-audit.md
```

Expected: both docs mention the new local completeness summary and still describe manifests/retention/replication as future work.

- [ ] **Step 5: Commit**

```bash
git add src/aidn_hypervisor/registry_service.py tests/test_registry_service.py ROADMAP.md docs/archive/specifications/2026-07-13-rfc-implementation-alignment-audit.md
git commit -m "Add registry local completeness summary"
```

## Final Verification

- [ ] Run the focused regression suite:

```bash
python -m pytest tests/test_registry_service.py tests/test_api.py -q
```

Expected: all targeted tests pass.

- [ ] Run the full project suite:

```bash
python -m pytest -q
```

Expected: full suite passes with no new failures.

- [ ] Run whitespace sanity check:

```bash
git diff --check
```

Expected: no new content errors. Existing line-ending warnings may remain if they already existed in the branch.
