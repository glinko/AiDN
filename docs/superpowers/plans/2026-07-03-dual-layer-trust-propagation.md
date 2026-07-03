# Dual-Layer Trust Propagation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** propagate `validation` trust and `publication sync` trust consistently through the operator dashboard, market view, and remote registry catalogue.

**Architecture:** keep the existing endpoint/publication/validation domains intact, then add small read-model enrichments at API/dashboard boundaries. The UI should render two separate trust lanes from those read models instead of inventing a new source of truth.

**Tech Stack:** `Python`, `FastAPI`, `pytest`, existing `HypervisorService`, `EndpointService`, `EndpointPublicationService`, `ValidationService`, static HTML dashboard.

---

### Task 1: Define trust read-model coverage

**Files:**
- Modify: `src/aidn_hypervisor/api.py`
- Modify: `src/aidn_hypervisor/dashboard.py`
- Modify: `src/aidn_hypervisor/registry_models.py`
- Test: `tests/test_api.py`

- [ ] Add/propagate endpoint-level trust fields:
  - `validation_summary`
  - `published_validation_summary`
  - `publication_sync_status`
- [ ] Add market-level aggregate trust summary derived from published endpoints on each node.
- [ ] Extend registry-published endpoint summaries so dashboard discovery can consume published/live trust without ad hoc field guessing.

### Task 2: Lock behavior with tests first

**Files:**
- Modify: `tests/test_api.py`

- [ ] Add failing API tests for endpoint dashboard dual-layer trust.
- [ ] Add failing API tests for registry advertisement trust enrichment.
- [ ] Add failing API tests for market trust aggregation.
- [ ] Add failing API tests for remote discovery trust propagation.

### Task 3: Implement backend trust enrichment

**Files:**
- Modify: `src/aidn_hypervisor/api.py`
- Modify: `src/aidn_hypervisor/dashboard.py`
- Modify: `src/aidn_hypervisor/registry_models.py`

- [ ] Add shared helpers for publication sync and trust aggregation.
- [ ] Enrich local registry advertisement output with live/published validation posture.
- [ ] Enrich market candidates with node-level trust aggregates.
- [ ] Enrich remote discovery rows with endpoint-level trust posture.

### Task 4: Render dual-layer trust in the operator UI

**Files:**
- Modify: `src/aidn_hypervisor/static/operator_dashboard.html`

- [ ] Add shared rendering helpers for trust chip labels and tones.
- [ ] Update endpoint table/inspector to show validation trust and publication trust separately.
- [ ] Update market rows/inspector to show compact aggregate trust.
- [ ] Update remote catalogue rows/inspector to show endpoint-level validation trust and publication sync.

### Task 5: Verify end-to-end

**Files:**
- Modify: `tests/test_api.py` if assertions need tightening after implementation

- [ ] Run focused API tests for trust payloads.
- [ ] Run dashboard HTML/API smoke tests covering endpoints, market, and remote routes.
- [ ] If browser preview is available, reload the operator dashboard and visually confirm the new trust surfaces.
