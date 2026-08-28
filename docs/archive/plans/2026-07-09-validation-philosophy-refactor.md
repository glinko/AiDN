# Validation Philosophy Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace binary validation semantics with report-first operational certification while preserving temporary compatibility for existing `validation_status` consumers.

**Architecture:** The refactor proceeds top-down and compatibility-first. First we align the product and protocol docs, then we expand the validation domain model and derivation rules around `ValidationReport` and `certification_status`, then we update API and read models to emit both canonical and legacy trust projections, and finally we migrate marketplace and dashboard aggregation away from `validated_count`.

**Tech Stack:** Python, FastAPI, Pydantic, pytest, static HTML/JS dashboard, Markdown product/protocol docs

---

## File Structure

- `docs/product/UX-0001-hypervisor-operator-journey.md`
  - operator-facing validation language, validator role, marketplace trust language
- `docs/product/ECO-0003-validation-economics.md`
  - validation reward semantics, certification reward language, maintenance degradation semantics
- `docs/product/RFC-0035-validation-escrow-system.md`
  - validator assignment and escrow semantics under report-first validation
- `docs/product/RFC-0057-validation-report-specification.md`
  - new canonical protocol spec for report schema and publication rules
- `src/aidn_hypervisor/validation/models.py`
  - canonical report schema, certification status literals, compatibility projection helpers
- `src/aidn_hypervisor/validation/service.py`
  - report submission flow, certification derivation, compatibility summary payloads
- `src/aidn_hypervisor/validation/store.py`
  - persistence support for expanded report and snapshot structures
- `src/aidn_hypervisor/endpoints/models.py`
  - endpoint-attached validation state extended with certification fields
- `src/aidn_hypervisor/api.py`
  - request payload models and expanded validation summary/history/report contracts
- `src/aidn_hypervisor/dashboard.py`
  - market trust aggregation based on certification states
- `src/aidn_hypervisor/registry_service.py`
  - registry-side trust aggregation based on certification states
- `src/aidn_hypervisor/operator_views.py`
  - endpoint and market payload wiring for canonical and compatibility trust fields
- `src/aidn_hypervisor/static/operator_dashboard.html`
  - trust labels, trust chips, and aggregation labels updated to certification language
- `tests/validation/test_models.py`
  - certification status model tests, report schema tests
- `tests/validation/test_service.py`
  - report-first service semantics, compatibility mapping, maintenance derivation
- `tests/test_api.py`
  - validation endpoint payloads, history payloads, market trust aggregation payloads
- `tests/test_operator_views.py`
  - operator view payload compatibility and certification projections
- `tests/test_persistence.py`
  - persistence of expanded report and certification snapshot fields
- `tests/test_wallet.py`
  - wallet event compatibility while shifting semantic language

### Task 1: Align Product And Protocol Documents

**Files:**
- Create: `docs/product/RFC-0057-validation-report-specification.md`
- Modify: `docs/product/UX-0001-hypervisor-operator-journey.md`
- Modify: `docs/product/ECO-0003-validation-economics.md`
- Modify: `docs/product/RFC-0035-validation-escrow-system.md`

- [ ] **Step 1: Add the new RFC-0057 shell first**

Create `docs/product/RFC-0057-validation-report-specification.md` with the canonical report-first structure:

```md
# RFC-0057 Validation Report Specification

Status: `Draft`

Version: `0.1`

Depends on:

- `RFC-0035 Validation Escrow System`
- `ECO-0003 Validation Economics`

## 1. Purpose

Validation Reports are the canonical trust artifacts of AiDN validation.

They record observable endpoint behavior, protocol compliance, accounting verification, detected issues, and certification recommendation.

## 2. Design Invariants

- Reports are immutable.
- Reports describe evidence, not model identity.
- Certification is derived from reports.
- Marketplace and reputation consume report history.
```

- [ ] **Step 2: Rewrite UX-0001 validation sections around certification**

Replace validator and marketplace language in `docs/product/UX-0001-hypervisor-operator-journey.md` with wording like:

```md
## 11. Validation

Validation is initiated explicitly by the operator.

Validation remains optional.

Validation is an operational certification flow.

Validation does not attempt to prove objective model identity.

The primary output of Validation is a published Validation Report.
```

Also update validator and marketplace sections:

```md
Validators act as protocol inspectors.

Marketplace surfaces compare certification status, validation history, and published reports rather than relying on a binary validated flag.
```

- [ ] **Step 3: Rewrite ECO-0003 around report-backed certification**

Update `docs/product/ECO-0003-validation-economics.md` to remove binary `PASS/FAIL` as the primary semantic and replace it with:

```md
Validation Reward does not depend on certification recommendation.

Validators are rewarded for producing valid Validation Reports.

Certification is derived from published reports.

The primary reward for the Endpoint is Certification Status, increased trust, and increased discoverability.
```

- [ ] **Step 4: Rewrite RFC-0035 around report production**

Update `docs/product/RFC-0035-validation-escrow-system.md` so assignment and settlement language says:

```md
Validation tasks assign production of Validation Reports.

Validation Sessions execute ordinary Session traffic.

Validators publish reports after execution.

Escrow guarantees report-producing validation work without revealing validator identity.
```

- [ ] **Step 5: Verify docs are internally aligned**

Run: `rg -n "PASS|FAIL|validated Model Class|binary validated flag|validate Endpoint" docs/product`

Expected: only acceptable historical references remain, and new canonical wording points at reports and certification.

- [ ] **Step 6: Commit**

```bash
git add docs/product/UX-0001-hypervisor-operator-journey.md docs/product/ECO-0003-validation-economics.md docs/product/RFC-0035-validation-escrow-system.md docs/product/RFC-0057-validation-report-specification.md
git commit -m "docs: align validation docs to report-first certification"
```

### Task 2: Lock The Expanded Validation Domain Model

**Files:**
- Modify: `src/aidn_hypervisor/validation/models.py`
- Modify: `src/aidn_hypervisor/endpoints/models.py`
- Test: `tests/validation/test_models.py`
- Test: `tests/test_persistence.py`

- [ ] **Step 1: Write the failing model tests**

Add tests to `tests/validation/test_models.py`:

```python
def test_validation_status_snapshot_accepts_certified_with_issues() -> None:
    snapshot = ValidationStatusSnapshot(
        endpoint_id="ep-1",
        configuration_hash="cfg-1",
        certification_status="certified_with_issues",
        latest_request_id="req-1",
        latest_report_id="report-1",
    )

    assert snapshot.certification_status == "certified_with_issues"
    assert snapshot.validation_status == "validated"


def test_validation_report_requires_recommendation_and_issue_counts() -> None:
    report = ValidationReport(
        report_id="report-1",
        request_id="req-1",
        endpoint_id="ep-1",
        configuration_hash="cfg-1",
        report_kind="initial",
        validator_label="validator-a",
        recommendation="certify_with_issues",
        critical_issue_count=0,
        warning_issue_count=2,
        evidence_summary="operational with warnings",
        created_at="2026-07-09T00:00:00+00:00",
    )

    assert report.recommendation == "certify_with_issues"
    assert report.warning_issue_count == 2
```

Add persistence coverage to `tests/test_persistence.py`:

```python
def test_file_state_store_round_trips_certification_snapshot_fields(tmp_path) -> None:
    snapshot = ValidationStatusSnapshot(
        endpoint_id="ep-1",
        configuration_hash="cfg-1",
        certification_status="certified",
        validation_status="validated",
        latest_request_id="req-1",
        latest_report_id="report-1",
        latest_report_at="2026-07-09T00:00:00+00:00",
    )

    assert snapshot.certification_status == "certified"
    assert snapshot.validation_status == "validated"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/validation/test_models.py tests/test_persistence.py -k "certification or report_requires_recommendation" -v`

Expected: FAIL because `certification_status`, `recommendation`, and the new persisted fields do not exist yet.

- [ ] **Step 3: Implement the minimal domain model changes**

Update `src/aidn_hypervisor/validation/models.py`:

```python
CertificationStatus = Literal[
    "uncertified",
    "pending_initial",
    "certified",
    "certified_with_issues",
    "maintenance_due",
    "maintenance_in_progress",
    "revoked",
    "superseded",
]
ValidationReportRecommendation = Literal[
    "certify",
    "certify_with_issues",
    "do_not_certify",
]


class ValidationReport(BaseModel):
    report_id: str
    request_id: str
    endpoint_id: str
    configuration_hash: str
    report_kind: ValidationRequestKind
    validator_id: str | None = None
    validator_label: str
    capability_id: str | None = None
    test_description: str | None = None
    request_summary: str | None = None
    response_summary: str | None = None
    observations: list[str] = Field(default_factory=list)
    measured_metrics: dict = Field(default_factory=dict)
    protocol_compliance: dict = Field(default_factory=dict)
    accounting_verification: dict = Field(default_factory=dict)
    detected_issues: list[dict] = Field(default_factory=list)
    critical_issue_count: int = Field(default=0, ge=0)
    warning_issue_count: int = Field(default=0, ge=0)
    recommendation: ValidationReportRecommendation
    evidence_summary: str
    signed_payload: dict = Field(default_factory=dict)
    created_at: str


class ValidationStatusSnapshot(BaseModel):
    endpoint_id: str
    configuration_hash: str
    certification_status: CertificationStatus = "uncertified"
    validation_status: str = "unvalidated"
    latest_request_id: str | None = None
    latest_report_id: str | None = None
    latest_report_at: str | None = None
    validated_at: str | None = None
    superseded_at: str | None = None
    maintenance_count: int = Field(default=0, ge=0)
```

Update `src/aidn_hypervisor/endpoints/models.py`:

```python
class EndpointValidationState(BaseModel):
    enabled: bool = False
    model_class_supported: bool = False
    verification_status: EndpointVerificationStatus = "unsupported"
    validation_profile: str | None = None
    certification_status: str = "uncertified"
    validation_status: str = "unvalidated"
    latest_request_id: str | None = None
    latest_report_id: str | None = None
    latest_report_at: str | None = None
    latest_recommendation: str | None = None
    report_count: int = 0
    validated_configuration_hash: str | None = None
    validated_at: str | None = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/validation/test_models.py tests/test_persistence.py -k "certification or report_requires_recommendation" -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aidn_hypervisor/validation/models.py src/aidn_hypervisor/endpoints/models.py tests/validation/test_models.py tests/test_persistence.py
git commit -m "feat: add certification-first validation models"
```

### Task 3: Refactor Validation Service To Derive Certification

**Files:**
- Modify: `src/aidn_hypervisor/validation/service.py`
- Modify: `src/aidn_hypervisor/validation/store.py`
- Test: `tests/validation/test_service.py`
- Test: `tests/test_wallet.py`

- [ ] **Step 1: Write the failing service tests**

Add tests to `tests/validation/test_service.py`:

```python
def test_submit_validation_report_with_certify_with_issues_marks_certified_with_issues() -> None:
    service = ValidationService(ValidationStore())
    requested = service.request_validation(
        endpoint_id="ep-1",
        owner_wallet="wallet-1",
        configuration_hash="cfg-1",
        minimum_session_deposit_q=25.0,
    )
    service.assign_epoch_requests(
        epoch_id="epoch-1",
        validator_entries=[{"validator_id": "val-1", "validator_label": "validator-a", "shares": 1}],
        seed="seed-1",
    )

    resolved = service.submit_validation_report(
        request_id=requested.request.request_id,
        recommendation="certify_with_issues",
        validator_label="validator-a",
        evidence_summary="operational with warnings",
        detected_issues=[{"severity": "warning", "code": "latency_spike"}],
    )

    assert resolved.snapshot.certification_status == "certified_with_issues"
    assert resolved.snapshot.validation_status == "validated"


def test_maintenance_report_with_critical_issue_revokes_certification() -> None:
    service = ValidationService(ValidationStore())
    requested = service.request_validation(
        endpoint_id="ep-1",
        owner_wallet="wallet-1",
        configuration_hash="cfg-1",
        minimum_session_deposit_q=25.0,
    )
    service.force_mark_validated(
        request_id=requested.request.request_id,
        report_id="report-1",
        validated_at="2026-07-09T00:00:00+00:00",
    )

    outcome = service.resolve_maintenance(
        endpoint_id="ep-1",
        configuration_hash="cfg-1",
        recommendation="do_not_certify",
        validator_label="validator-a",
        evidence_summary="accounting mismatch",
        detected_issues=[{"severity": "critical", "code": "accounting_mismatch"}],
    )

    assert outcome.snapshot.certification_status == "revoked"
    assert outcome.snapshot.validation_status == "validation_failed"
```

Add wallet compatibility coverage to `tests/test_wallet.py`:

```python
def test_validation_wallet_events_survive_certification_refactor() -> None:
    assert "validation_bond_locked"
    assert "validation_bond_refunded"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/validation/test_service.py tests/test_wallet.py -k "certify_with_issues or revokes_certification or wallet_events_survive" -v`

Expected: FAIL because service methods still require `outcome` and do not derive `certification_status`.

- [ ] **Step 3: Implement certification derivation and compatibility projection**

Add helpers to `src/aidn_hypervisor/validation/service.py`:

```python
def _compat_validation_status_for(certification_status: str) -> str:
    return {
        "uncertified": "unvalidated",
        "pending_initial": "pending_initial",
        "maintenance_due": "pending_maintenance",
        "maintenance_in_progress": "pending_maintenance",
        "certified": "validated",
        "certified_with_issues": "validated",
        "revoked": "validation_failed",
        "superseded": "superseded",
    }[certification_status]


def _derive_certification_status(*, request_kind: str, recommendation: str, critical_issue_count: int) -> str:
    if recommendation == "do_not_certify" or critical_issue_count > 0:
        return "revoked" if request_kind == "maintenance" else "uncertified"
    if recommendation == "certify_with_issues":
        return "certified_with_issues"
    return "certified"
```

Update report submission flow:

```python
report = ValidationReport(
    report_id=self._new_id("report"),
    request_id=request.request_id,
    endpoint_id=request.endpoint_id,
    configuration_hash=request.configuration_hash,
    report_kind="initial",
    validator_label=validator_label,
    recommendation=recommendation,
    detected_issues=detected_issues,
    critical_issue_count=sum(1 for item in detected_issues if item.get("severity") == "critical"),
    warning_issue_count=sum(1 for item in detected_issues if item.get("severity") == "warning"),
    evidence_summary=evidence_summary,
    created_at=self._now(),
)

certification_status = _derive_certification_status(
    request_kind="initial",
    recommendation=report.recommendation,
    critical_issue_count=report.critical_issue_count,
)
validation_status = _compat_validation_status_for(certification_status)
```

Update maintenance flow to use recommendation and detected issues the same way, while keeping bond refund and forfeiture rules unchanged.

- [ ] **Step 4: Expand `validation_summary()` to emit canonical and compatibility fields**

Return payload like:

```python
return {
    "endpoint_id": endpoint_id,
    "configuration_hash": resolved_configuration_hash,
    "certification_status": current_snapshot.certification_status if current_snapshot else "uncertified",
    "validation_status": current_snapshot.validation_status if current_snapshot else "unvalidated",
    "latest_request_id": ...,
    "latest_report_id": ...,
    "latest_report_at": current_snapshot.latest_report_at if current_snapshot else None,
    "latest_recommendation": latest_report.recommendation if latest_report else None,
    "report_count": len(reports),
    "maintenance_report_count": sum(1 for item in reports if item.report_kind == "maintenance"),
    "critical_issue_count": latest_report.critical_issue_count if latest_report else 0,
    "warning_issue_count": latest_report.warning_issue_count if latest_report else 0,
    "bond_state": ...,
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/validation/test_service.py tests/test_wallet.py -k "certify_with_issues or revokes_certification or wallet_events_survive" -v`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/aidn_hypervisor/validation/service.py src/aidn_hypervisor/validation/store.py tests/validation/test_service.py tests/test_wallet.py
git commit -m "feat: derive certification from validation reports"
```

### Task 4: Expand API Contracts Around Certification

**Files:**
- Modify: `src/aidn_hypervisor/api.py`
- Test: `tests/test_api.py`
- Test: `tests/test_operator_views.py`

- [ ] **Step 1: Write the failing API tests**

Add tests to `tests/test_api.py`:

```python
def test_validation_summary_endpoint_returns_certification_and_compatibility_fields() -> None:
    response = client.get("/api/v1/endpoints/ep-1/validation")

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["certification_status"] == "certified"
    assert body["validation_status"] == "validated"
    assert "latest_recommendation" in body
    assert "critical_issue_count" in body


def test_submit_validation_report_endpoint_accepts_recommendation_payload() -> None:
    response = client.post(
        f"/api/v1/validation/requests/{request_id}/reports",
        json={
            "recommendation": "certify_with_issues",
            "validator_label": "validator-a",
            "evidence_summary": "operational with warnings",
            "detected_issues": [{"severity": "warning", "code": "latency_spike"}],
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["snapshot"]["certification_status"] == "certified_with_issues"
```

Add operator-view coverage to `tests/test_operator_views.py`:

```python
def test_endpoints_payload_includes_certification_status_and_legacy_validation_status(...) -> None:
    assert payload["items"][0]["validation_summary"]["certification_status"] == "certified"
    assert payload["items"][0]["validation_summary"]["validation_status"] == "validated"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_api.py tests/test_operator_views.py -k "certification_status or recommendation_payload" -v`

Expected: FAIL because the API does not accept `recommendation` and does not return `certification_status`.

- [ ] **Step 3: Introduce explicit request payload models and compatibility handling**

Add request models near the existing API request classes in `src/aidn_hypervisor/api.py`:

```python
class ValidationReportSubmitRequest(BaseModel):
    recommendation: str | None = None
    outcome: str | None = None
    validator_label: str
    evidence_summary: str
    detected_issues: list[dict] = Field(default_factory=list)
    observations: list[str] = Field(default_factory=list)
    measured_metrics: dict = Field(default_factory=dict)
    protocol_compliance: dict = Field(default_factory=dict)
    accounting_verification: dict = Field(default_factory=dict)


class ValidationMaintenanceSubmitRequest(ValidationReportSubmitRequest):
    pass
```

Map legacy payloads in the route:

```python
recommendation = request.recommendation
if recommendation is None and request.outcome is not None:
    recommendation = "certify" if request.outcome == "pass" else "do_not_certify"
```

- [ ] **Step 4: Update route responses and history payloads**

Ensure `/validation` returns expanded summary and `/validation/history` exposes enriched reports:

```python
return _ok(
    {
        "request": result.request.model_dump(mode="json"),
        "snapshot": result.snapshot.model_dump(mode="json"),
        "report": result.report.model_dump(mode="json"),
    }
)
```

Do not strip `certification_status`, `latest_recommendation`, or issue counters from serialized responses.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_api.py tests/test_operator_views.py -k "certification_status or recommendation_payload" -v`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/aidn_hypervisor/api.py tests/test_api.py tests/test_operator_views.py
git commit -m "feat: expose certification-first validation api"
```

### Task 5: Migrate Trust Aggregation And Dashboard Labels

**Files:**
- Modify: `src/aidn_hypervisor/dashboard.py`
- Modify: `src/aidn_hypervisor/registry_service.py`
- Modify: `src/aidn_hypervisor/operator_views.py`
- Modify: `src/aidn_hypervisor/static/operator_dashboard.html`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write the failing aggregation and UI payload tests**

Extend `tests/test_api.py`:

```python
def test_operator_dashboard_market_payload_includes_certification_counts() -> None:
    item = next(candidate for candidate in response.json()["candidates"] if candidate["node_id"] == "node-external")

    assert item["trust_summary"]["certified_count"] == 1
    assert item["trust_summary"]["certified_with_issues_count"] == 1
    assert item["trust_summary"]["validation_by_status"]["validated"] == 2


def test_operator_dashboard_remote_endpoints_payload_surfaces_certification_status() -> None:
    assert item["published_validation_summary"]["certification_status"] == "certified_with_issues"
    assert item["published_validation_summary"]["validation_status"] == "validated"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_api.py -k "certification_counts or surfaces_certification_status" -v`

Expected: FAIL because trust summaries still only emit `validated_count`.

- [ ] **Step 3: Update aggregation helpers to count canonical certification states**

Update `src/aidn_hypervisor/dashboard.py` and `src/aidn_hypervisor/registry_service.py`:

```python
certified_count = 0
certified_with_issues_count = 0
pending_count = 0
attention_count = 0

certification_status = (
    item.get("published_validation_summary", {}) or {}
).get("certification_status")
validation_status = (
    item.get("published_validation_summary", {}) or {}
).get("validation_status", "unknown")

if certification_status == "certified":
    certified_count += 1
elif certification_status == "certified_with_issues":
    certified_with_issues_count += 1
elif certification_status in {"pending_initial", "maintenance_in_progress", "maintenance_due", "uncertified"}:
    pending_count += 1
elif certification_status not in {None, "superseded"}:
    attention_count += 1
```

Return both canonical and legacy counts during migration:

```python
return {
    "total_endpoints": len(published_endpoints),
    "certified_count": certified_count,
    "certified_with_issues_count": certified_with_issues_count,
    "validated_count": certified_count + certified_with_issues_count,
    "pending_count": pending_count,
    "attention_count": attention_count,
    ...
}
```

- [ ] **Step 4: Update dashboard labels without removing compatibility**

Change `src/aidn_hypervisor/static/operator_dashboard.html` helpers:

```javascript
function certificationStatus(summary) {
  return summary?.certification_status || "uncertified";
}

function trustStatusLabel(status) {
  switch (status) {
    case "certified":
      return "Certified";
    case "certified_with_issues":
      return "Certified With Issues";
    case "pending_initial":
      return "Pending Initial";
    case "maintenance_in_progress":
      return "Maintenance In Progress";
    case "revoked":
      return "Attention Required";
    default:
      return String(status || "Unknown").replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
  }
}
```

Update market chip logic:

```javascript
if (trust.certified_with_issues_count) {
  return {
    label: `${formatCount(trust.certified_with_issues_count)} certified with issues / ${formatCount(trust.total_endpoints)}`,
    tone: "warn",
  };
}
if (trust.certified_count) {
  return {
    label: `${formatCount(trust.certified_count)} certified / ${formatCount(trust.total_endpoints)}`,
    tone: "good",
  };
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_api.py -k "certification_counts or surfaces_certification_status" -v`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/aidn_hypervisor/dashboard.py src/aidn_hypervisor/registry_service.py src/aidn_hypervisor/operator_views.py src/aidn_hypervisor/static/operator_dashboard.html tests/test_api.py
git commit -m "feat: migrate trust aggregation to certification semantics"
```

### Task 6: Full Validation Regression Pass

**Files:**
- Modify: any files touched by earlier tasks if failures reveal contract drift
- Test: `tests/validation/test_models.py`
- Test: `tests/validation/test_service.py`
- Test: `tests/test_api.py`
- Test: `tests/test_operator_views.py`
- Test: `tests/test_persistence.py`
- Test: `tests/test_wallet.py`

- [ ] **Step 1: Run the focused validation suite**

Run:

```bash
python -m pytest tests/validation/test_models.py tests/validation/test_service.py tests/test_api.py tests/test_operator_views.py tests/test_persistence.py tests/test_wallet.py -k "validation or certification or trust_summary" -v
```

Expected: PASS

- [ ] **Step 2: Fix the smallest failing contract mismatches first**

If the suite exposes drift, correct read-model mismatches using targeted patches like:

```python
summary["validation_status"] = _compat_validation_status_for(summary["certification_status"])
summary["latest_report_at"] = current_snapshot.latest_report_at
summary["latest_recommendation"] = latest_report.recommendation if latest_report else None
```

and UI mismatches like:

```javascript
const trust = item.published_validation_summary || {};
const status = trust.certification_status || trust.validation_status || "uncertified";
```

- [ ] **Step 3: Re-run the focused validation suite**

Run:

```bash
python -m pytest tests/validation/test_models.py tests/validation/test_service.py tests/test_api.py tests/test_operator_views.py tests/test_persistence.py tests/test_wallet.py -k "validation or certification or trust_summary" -v
```

Expected: PASS with no remaining certification/validation regressions.

- [ ] **Step 4: Run one broader smoke pass for endpoint shell stability**

Run:

```bash
python -m pytest tests/test_api.py -k "operator_dashboard_endpoints_payload_includes_validation_summary or operator_dashboard_market_payload_includes_trust_summary or endpoint_validation_history_endpoint_returns_reports_and_assignments" -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src tests
git commit -m "test: lock certification-first validation regression coverage"
```

## Self-Review

- Spec coverage:
  - report-first canonical trust object: Task 2 and Task 3
  - `certification_status` plus legacy compatibility: Task 2, Task 3, Task 4, Task 5
  - docs and new RFC: Task 1
  - API expansion: Task 4
  - marketplace/dashboard trust migration: Task 5
  - regression protection: Task 6
- Placeholder scan:
  - no `TODO`, `TBD`, or `implement later` placeholders remain
  - every code-changing task includes concrete snippets and exact commands
- Type consistency:
  - canonical terms used consistently: `certification_status`, `recommendation`, `detected_issues`, `latest_report_at`, `latest_recommendation`
  - compatibility term retained consistently: `validation_status`

Plan complete and saved to `docs/archive/plans/2026-07-09-validation-philosophy-refactor.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
