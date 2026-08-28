# M5 Reputation And Rating Read-Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the first computed `M5` reputation layer as a read model, publish it through registry, discovery, market, and operator surfaces, and migrate ranking to prefer computed reputation over legacy static rating.

**Architecture:** Introduce one focused reputation builder module that consumes already-available trust and operational facts, computes a normalized `reputation` payload, and is called from existing projection layers instead of duplicating score logic. Keep legacy `rating` intact for compatibility while making `reputation.score` the canonical trust number for new sorting and UI breakdowns.

**Tech Stack:** Python, FastAPI, Pydantic, existing registry/dashboard/operator shell contracts, static operator dashboard HTML/JS, `pytest`

---

## File Structure

- Create: `src/aidn_hypervisor/reputation.py`
  - Canonical read-model builder for computed reputation score, tier, components, and evidence.
- Modify: `src/aidn_hypervisor/registry_models.py`
  - Add a typed `RegistryReputation` contract and attach it to node advertisements.
- Modify: `src/aidn_hypervisor/service.py`
  - Compute node reputation when building advertisements and local operator projections.
- Modify: `src/aidn_hypervisor/registry_service.py`
  - Publish `reputation` through discovery results and switch candidate ordering to prefer `reputation.score`.
- Modify: `src/aidn_hypervisor/dashboard.py`
  - Project `reputation` into market payloads and canonical candidate rows.
- Modify: `src/aidn_hypervisor/static/operator_dashboard.html`
  - Replace rating-only trust surfaces with reputation score plus component breakdown.
- Modify: `tests/test_api.py`
  - Cover registry publication, market payload projection, and shell rendering of reputation.
- Create: `tests/test_reputation.py`
  - Focused unit tests for the reputation builder formula and tier mapping.
- Modify: `ROADMAP.md`
  - Mark computed reputation publication as the active delivered `M5` slice and keep next-step language factual.

## Task 1: Lock The Reputation Builder Contract With Failing Tests

**Files:**
- Create: `C:\Users\admin\Documents\New project 3\AiDN\tests\test_reputation.py`
- Reference: `C:\Users\admin\Documents\New project 3\AiDN\docs\superpowers\specs\2026-07-10-m5-reputation-rating-read-model-design.md`

- [ ] **Step 1: Write the failing unit tests for score, tier, and evidence**

```python
from aidn_hypervisor.reputation import build_reputation_profile


def test_build_reputation_profile_returns_score_tier_components_and_evidence() -> None:
    profile = build_reputation_profile(
        node_status="ready",
        heartbeat_fresh=True,
        trust_summary={
            "total_endpoints": 4,
            "certified_count": 2,
            "certified_with_issues_count": 1,
            "validated_count": 3,
            "pending_count": 1,
            "attention_count": 0,
            "in_sync_count": 3,
            "drift_count": 1,
        },
        operational_stats={
            "total_tasks": 20,
            "successful_tasks": 18,
            "failed_tasks": 2,
        },
        baseline_rating={"score": 0.40, "tier": "C", "updated_at": "2026-07-10T00:00:00+00:00"},
        updated_at="2026-07-10T09:15:00+00:00",
    )

    assert profile["score"] > 0.0
    assert profile["tier"] in {"A", "B", "C", "D", "unrated"}
    assert profile["components"]["freshness"] > 0.0
    assert profile["components"]["publication_integrity"] > 0.0
    assert profile["components"]["validation_posture"] > 0.0
    assert profile["components"]["operational_reliability"] > 0.0
    assert profile["evidence"]["node_status"] == "ready"
    assert profile["evidence"]["published_endpoint_count"] == 4


def test_build_reputation_profile_penalizes_stale_and_drifted_nodes() -> None:
    healthy = build_reputation_profile(
        node_status="ready",
        heartbeat_fresh=True,
        trust_summary={
            "total_endpoints": 2,
            "certified_count": 1,
            "certified_with_issues_count": 0,
            "validated_count": 1,
            "pending_count": 0,
            "attention_count": 0,
            "in_sync_count": 2,
            "drift_count": 0,
        },
        operational_stats={"total_tasks": 10, "successful_tasks": 10, "failed_tasks": 0},
        baseline_rating={"score": 0.50, "tier": "C", "updated_at": "2026-07-10T00:00:00+00:00"},
        updated_at="2026-07-10T09:15:00+00:00",
    )
    degraded = build_reputation_profile(
        node_status="stale",
        heartbeat_fresh=False,
        trust_summary={
            "total_endpoints": 2,
            "certified_count": 0,
            "certified_with_issues_count": 0,
            "validated_count": 0,
            "pending_count": 1,
            "attention_count": 1,
            "in_sync_count": 0,
            "drift_count": 2,
        },
        operational_stats={"total_tasks": 10, "successful_tasks": 6, "failed_tasks": 4},
        baseline_rating={"score": 0.50, "tier": "C", "updated_at": "2026-07-10T00:00:00+00:00"},
        updated_at="2026-07-10T09:15:00+00:00",
    )

    assert healthy["score"] > degraded["score"]
    assert healthy["components"]["freshness"] > degraded["components"]["freshness"]
    assert healthy["components"]["publication_integrity"] > degraded["components"]["publication_integrity"]


def test_build_reputation_profile_uses_unrated_tier_when_no_signal_exists() -> None:
    profile = build_reputation_profile(
        node_status="offline",
        heartbeat_fresh=False,
        trust_summary={
            "total_endpoints": 0,
            "certified_count": 0,
            "certified_with_issues_count": 0,
            "validated_count": 0,
            "pending_count": 0,
            "attention_count": 0,
            "in_sync_count": 0,
            "drift_count": 0,
        },
        operational_stats={"total_tasks": 0, "successful_tasks": 0, "failed_tasks": 0},
        baseline_rating={"score": 0.0, "tier": "unrated", "updated_at": "2026-07-10T00:00:00+00:00"},
        updated_at="2026-07-10T09:15:00+00:00",
    )

    assert profile["score"] == 0.0
    assert profile["tier"] == "unrated"
```

- [ ] **Step 2: Run the new unit tests and verify they fail**

Run:

```bash
python -m pytest tests/test_reputation.py -q
```

Expected:
- `FAIL`
- import error for `aidn_hypervisor.reputation`

- [ ] **Step 3: Write the minimal reputation builder**

```python
# src/aidn_hypervisor/reputation.py
from datetime import datetime, timezone


def reputation_tier_for(score: float) -> str:
    if score >= 0.9:
        return "A"
    if score >= 0.75:
        return "B"
    if score >= 0.5:
        return "C"
    if score > 0.0:
        return "D"
    return "unrated"


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, round(value, 6)))


def build_reputation_profile(
    *,
    node_status: str,
    heartbeat_fresh: bool,
    trust_summary: dict,
    operational_stats: dict,
    baseline_rating: dict,
    updated_at: str | None = None,
) -> dict:
    freshness = 1.0 if node_status == "ready" and heartbeat_fresh else 0.55 if node_status == "stale" else 0.0
    total_endpoints = int(trust_summary.get("total_endpoints", 0) or 0)
    in_sync_count = int(trust_summary.get("in_sync_count", 0) or 0)
    drift_count = int(trust_summary.get("drift_count", 0) or 0)
    publication_integrity = 1.0 if total_endpoints == 0 else _clamp((in_sync_count - drift_count) / max(total_endpoints, 1) + 0.5)
    certified_count = int(trust_summary.get("certified_count", 0) or 0)
    certified_with_issues_count = int(trust_summary.get("certified_with_issues_count", 0) or 0)
    attention_count = int(trust_summary.get("attention_count", 0) or 0)
    pending_count = int(trust_summary.get("pending_count", 0) or 0)
    validation_posture = _clamp(
        0.45
        + certified_count * 0.15
        + certified_with_issues_count * 0.08
        - attention_count * 0.15
        - pending_count * 0.05
    )
    total_tasks = int(operational_stats.get("total_tasks", 0) or 0)
    successful_tasks = int(operational_stats.get("successful_tasks", 0) or 0)
    failed_tasks = int(operational_stats.get("failed_tasks", 0) or 0)
    operational_reliability = 0.0 if total_tasks <= 0 else _clamp((successful_tasks - failed_tasks) / max(total_tasks, 1) + 0.5)
    baseline = float((baseline_rating or {}).get("score") or 0.0)
    score = _clamp(
        freshness * 0.25
        + publication_integrity * 0.30
        + validation_posture * 0.25
        + operational_reliability * 0.20
    )
    score = _clamp(max(score, baseline * 0.5 if baseline > 0 else score))
    return {
        "score": score,
        "tier": reputation_tier_for(score),
        "updated_at": updated_at or datetime.now(timezone.utc).isoformat(),
        "components": {
            "freshness": freshness,
            "publication_integrity": publication_integrity,
            "validation_posture": validation_posture,
            "operational_reliability": operational_reliability,
        },
        "evidence": {
            "node_status": node_status,
            "published_endpoint_count": total_endpoints,
            "in_sync_count": in_sync_count,
            "drift_count": drift_count,
            "certified_count": certified_count,
            "certified_with_issues_count": certified_with_issues_count,
            "attention_count": attention_count,
            "pending_count": pending_count,
            "total_tasks": total_tasks,
            "successful_tasks": successful_tasks,
            "failed_tasks": failed_tasks,
        },
    }
```

- [ ] **Step 4: Run the unit tests and verify they pass**

Run:

```bash
python -m pytest tests/test_reputation.py -q
```

Expected:
- `PASS`

- [ ] **Step 5: Commit the reputation builder**

```bash
git add src/aidn_hypervisor/reputation.py tests/test_reputation.py
git commit -m "feat: add computed reputation builder"
```

## Task 2: Publish Reputation In Registry And Discovery

**Files:**
- Modify: `C:\Users\admin\Documents\New project 3\AiDN\src\aidn_hypervisor\registry_models.py`
- Modify: `C:\Users\admin\Documents\New project 3\AiDN\src\aidn_hypervisor\service.py`
- Modify: `C:\Users\admin\Documents\New project 3\AiDN\src\aidn_hypervisor\registry_service.py`
- Modify: `C:\Users\admin\Documents\New project 3\AiDN\tests\test_api.py`
- Reference: `C:\Users\admin\Documents\New project 3\AiDN\src\aidn_hypervisor\validation\service.py`

- [ ] **Step 1: Add failing API tests for node advertisement and discovery reputation publication**

```python
def test_node_advertisement_includes_computed_reputation() -> None:
    service = _service(whisper_endpoint="http://127.0.0.1:9000")

    payload = service.node_advertisement()

    assert "reputation" in payload
    assert payload["reputation"]["score"] >= 0.0
    assert "components" in payload["reputation"]
    assert "evidence" in payload["reputation"]


def test_registry_discovery_orders_ready_nodes_by_reputation_then_price() -> None:
    registry = RegistryService()
    better = RegistryNodeAdvertisement(
        **_node("node-better", rating_score=0.20, input_price=14, output_price=28),
        published_endpoints=[
            {
                "endpoint_id": "ep-better",
                "owner_wallet": "wallet-better",
                "node_id": "node-better",
                "current_publication_id": "pub-better",
                "current_configuration_hash": "cfg-better",
                "published_at": "2026-07-10T00:00:00+00:00",
                "status": "published",
                "visibility": "public",
                "model_class": "llm_text",
                "publication_sync_status": "in_sync",
                "published_validation_summary": {
                    "certification_status": "certified",
                    "validation_status": "validated",
                },
            }
        ],
    )
    cheaper = RegistryNodeAdvertisement(
        **_node("node-cheaper", rating_score=0.95, input_price=12, output_price=24),
        published_endpoints=[
            {
                "endpoint_id": "ep-cheaper",
                "owner_wallet": "wallet-cheaper",
                "node_id": "node-cheaper",
                "current_publication_id": "pub-cheaper",
                "current_configuration_hash": "cfg-cheaper",
                "published_at": "2026-07-10T00:00:00+00:00",
                "status": "published",
                "visibility": "public",
                "model_class": "llm_text",
                "publication_sync_status": "local_changes_not_published",
                "published_validation_summary": {
                    "certification_status": "uncertified",
                    "validation_status": "unvalidated",
                },
            }
        ],
    )

    registry.upsert_node(cheaper)
    registry.upsert_node(better)

    payload = registry.discover(RegistryDiscoveryQuery())

    assert payload["nodes"][0]["node_id"] == "node-better"
    assert "reputation" in payload["nodes"][0]
    assert "reputation" in payload["candidates"][0]
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run:

```bash
python -m pytest tests/test_api.py -k "computed_reputation or reputation_then_price" -q
```

Expected:
- `FAIL`
- missing `reputation` field or discovery still ordered purely by legacy `rating`

- [ ] **Step 3: Add the typed registry contract and service-side projection**

```python
# src/aidn_hypervisor/registry_models.py
class RegistryReputation(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    tier: str
    updated_at: str
    components: dict[str, float] = Field(default_factory=dict)
    evidence: dict[str, int | float | str] = Field(default_factory=dict)


class RegistryNodeAdvertisement(BaseModel):
    ...
    rating: RegistryRating
    reputation: RegistryReputation | None = None
    bundles: list[RegistryBundleAdvertisement]
```

```python
# src/aidn_hypervisor/service.py
from aidn_hypervisor.reputation import build_reputation_profile
from aidn_hypervisor.dashboard import _aggregate_market_trust


def _node_operational_stats(self) -> dict:
    total = len(self._task_results)
    successful = sum(
        1
        for result in self._task_results.values()
        if result.get("status") == "completed"
    )
    failed = sum(
        1
        for result in self._task_results.values()
        if result.get("status") in {"failed", "unbillable"}
    )
    return {
        "total_tasks": total,
        "successful_tasks": successful,
        "failed_tasks": failed,
    }


def _node_reputation_payload(
    self,
    *,
    heartbeat_at: str,
    status: str,
    published_endpoints: list[dict],
) -> dict:
    heartbeat_age = (
        datetime.now(timezone.utc) - datetime.fromisoformat(heartbeat_at)
    ).total_seconds()
    heartbeat_fresh = heartbeat_age <= self.heartbeat_ttl_seconds
    trust_summary = _aggregate_market_trust(published_endpoints)
    return build_reputation_profile(
        node_status=status,
        heartbeat_fresh=heartbeat_fresh,
        trust_summary=trust_summary,
        operational_stats=self._node_operational_stats(),
        baseline_rating=self.rating,
        updated_at=heartbeat_at,
    )


def node_advertisement(self, *, heartbeat_at: str | None = None) -> dict:
    timestamp = heartbeat_at or datetime.now(timezone.utc).isoformat()
    published_endpoints = [...]
    advertisement = RegistryNodeAdvertisement(
        ...
        heartbeat_at=timestamp,
        status="ready",
        published_endpoints=published_endpoints,
        reputation=self._node_reputation_payload(
            heartbeat_at=timestamp,
            status="ready",
            published_endpoints=published_endpoints,
        ),
    )
    return advertisement.model_dump(mode="json")
```

- [ ] **Step 4: Project reputation through registry discovery and switch sorting**

```python
# src/aidn_hypervisor/registry_service.py
if query.min_rating is not None and (
    (node.get("reputation") or node["rating"])["score"] < query.min_rating
):
    continue


def _candidate_trust_score(self, candidate: dict) -> float:
    reputation = candidate.get("reputation") or {}
    if reputation.get("score") is not None:
        return float(reputation["score"])
    rating = candidate.get("rating") or {}
    return float(rating.get("score") or 0.0)


def _candidate_sort_key(self, candidate: dict) -> tuple:
    return (
        {"ready": 0, "stale": 1, "offline": 2}[candidate["status"]],
        0 if candidate["endpoint_ready"] else 1,
        0 if candidate["supports_allocation"] else 1,
        0 if candidate["supports_queue"] else 1,
        -self._candidate_trust_score(candidate),
        candidate["pricing"]["input"],
        candidate["pricing"]["output"],
        candidate["node_id"],
        candidate["bundle_id"],
    )
```

- [ ] **Step 5: Run the focused tests and verify they pass**

Run:

```bash
python -m pytest tests/test_api.py -k "computed_reputation or reputation_then_price" -q
```

Expected:
- `PASS`

- [ ] **Step 6: Commit registry and discovery reputation publication**

```bash
git add src/aidn_hypervisor/registry_models.py src/aidn_hypervisor/service.py src/aidn_hypervisor/registry_service.py tests/test_api.py
git commit -m "feat: publish computed reputation in discovery"
```

## Task 3: Project Reputation Into Market Payloads And Operator Shell

**Files:**
- Modify: `C:\Users\admin\Documents\New project 3\AiDN\src\aidn_hypervisor\dashboard.py`
- Modify: `C:\Users\admin\Documents\New project 3\AiDN\src\aidn_hypervisor\static\operator_dashboard.html`
- Modify: `C:\Users\admin\Documents\New project 3\AiDN\tests\test_api.py`

- [ ] **Step 1: Add failing tests for market payload projection and shell breakdown**

```python
def test_operator_dashboard_market_payload_includes_reputation_block() -> None:
    service = _service()
    advertisement = service.node_advertisement()

    payload = build_market_payload(service=service, registry_service=None)

    assert payload["candidates"][0]["reputation"]["score"] >= 0.0
    assert "components" in payload["candidates"][0]["reputation"]


def test_operator_dashboard_shell_renders_reputation_breakdown() -> None:
    response = TestClient(build_app(service=_service())).get("/operators/dashboard")

    assert response.status_code == 200
    assert "function candidateReputation" in response.text
    assert "Reputation Score" in response.text
    assert "Publication Integrity" in response.text
    assert "Operational Reliability" in response.text
```

- [ ] **Step 2: Run the targeted tests and verify they fail**

Run:

```bash
python -m pytest tests/test_api.py -k "reputation_block or reputation_breakdown" -q
```

Expected:
- `FAIL`
- market candidates or shell do not yet expose the new `reputation` contract

- [ ] **Step 3: Thread reputation into market payload builders**

```python
# src/aidn_hypervisor/dashboard.py
def _local_candidate_from_advertisement(advertisement: dict, bundle: dict) -> dict:
    return {
        ...
        "rating": advertisement["rating"],
        "reputation": advertisement.get("reputation") or advertisement["rating"],
        ...
    }


def _canonical_candidate_row(...):
    return {
        ...
        "rating": advertisement["rating"],
        "reputation": advertisement.get("reputation") or advertisement["rating"],
        ...
    }
```

- [ ] **Step 4: Render score plus component breakdown in the shell**

```javascript
function candidateReputation(candidate) {
  return candidate?.reputation || candidate?.rating || { score: 0, tier: "unrated", components: {} };
}

function reputationComponentLabel(key) {
  return {
    freshness: "Freshness",
    publication_integrity: "Publication Integrity",
    validation_posture: "Validation Posture",
    operational_reliability: "Operational Reliability",
  }[key] || key;
}
```

```javascript
<div class="inspector-card">
  <strong>Reputation Score</strong>
  <div class="inspector-metric">${formatRating(candidateReputation(candidate).score)}</div>
</div>
```

```javascript
<div class="trust-grid">
  ${Object.entries(candidateReputation(candidate).components || {})
    .map(
      ([key, value]) => renderTrustLane(
        reputationComponentLabel(key),
        formatRating(value),
        value >= 0.75 ? "good" : value >= 0.5 ? "" : "bad",
        `Computed from current node trust and operational evidence.`
      )
    )
    .join("")}
</div>
```

- [ ] **Step 5: Run the targeted tests and verify they pass**

Run:

```bash
python -m pytest tests/test_api.py -k "reputation_block or reputation_breakdown" -q
```

Expected:
- `PASS`

- [ ] **Step 6: Commit market and shell reputation projection**

```bash
git add src/aidn_hypervisor/dashboard.py src/aidn_hypervisor/static/operator_dashboard.html tests/test_api.py
git commit -m "feat: expose reputation in market and shell"
```

## Task 4: Sync The Roadmap And Run Full Regression

**Files:**
- Modify: `C:\Users\admin\Documents\New project 3\AiDN\ROADMAP.md`
- Modify: `C:\Users\admin\Documents\New project 3\AiDN\tests\test_api.py`
- Modify: `C:\Users\admin\Documents\New project 3\AiDN\tests\test_reputation.py`

- [ ] **Step 1: Update the roadmap to reflect the delivered reputation slice**

```markdown
- validation economics and maintenance-validation policy are now defined at the product level, but the protocol and registry trust layer are still incomplete;
```

Replace with:

```markdown
- validation economics and maintenance-validation policy are now defined at the product level, and the first computed reputation publication layer now projects trust through registry, discovery, and operator market surfaces;
```

```markdown
2. Implement `M5` rating, validation, and trust publication on top of the canonical endpoint workspace.
3. Propagate those trust signals cleanly through discovery, market selection, and the operator shell.
```

Replace with:

```markdown
2. Deepen `M5` trust with richer remote/proxy lifecycle and later persisted reputation inputs.
3. Expand endpoint lifecycle controls across remote/proxy and marketplace routing with the new reputation layer available to routing decisions.
```

- [ ] **Step 2: Run the full suite**

Run:

```bash
python -m pytest -q
```

Expected:
- `PASS`

- [ ] **Step 3: Run the focused reputation and trust slice again**

Run:

```bash
python -m pytest tests/test_reputation.py tests/test_api.py -k "reputation or trust_summary or market" -q
```

Expected:
- `PASS`

- [ ] **Step 4: Commit the roadmap and verification slice**

```bash
git add ROADMAP.md tests/test_reputation.py tests/test_api.py
git commit -m "docs: update roadmap for reputation publication"
```

## Spec Coverage Check

- dedicated reputation read-model builder: Task 1
- computed `reputation` payload alongside legacy `rating`: Tasks 2 and 3
- trust-aware sorting with `reputation.score`: Task 2
- operator-facing breakdown surfaces: Task 3
- roadmap alignment and delivered-slice visibility: Task 4

## Placeholder Scan

Checked for:

- `TBD`
- `TODO`
- vague “add tests” steps without code
- unnamed score sources or undefined payload fields

## Type Consistency

Canonical names used throughout the plan:

- `build_reputation_profile(...)`
- `RegistryReputation`
- `reputation.score`
- `reputation.components`
- `reputation.evidence`

No alternative names should be introduced during implementation.
