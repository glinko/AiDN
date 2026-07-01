# Operator Dashboard Terminal Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle the shipped `Home / Fleet / Market` operator dashboard into a dense terminal-style control room with a left rail, top metrics strip, central workspace, right inspector, and bottom operations band while preserving the current hypervisor and registry-backed workflows.

**Architecture:** Keep the existing FastAPI routes and dashboard JSON payloads as the data backbone. Concentrate the redesign in the static dashboard shell with lightweight client-side view state, and only add small payload enrichments if the current contracts cannot support the approved inspector and market-table behaviors.

**Tech Stack:** `Python`, `FastAPI`, `pytest`, static `HTML/CSS/JavaScript`, existing `HypervisorService`, existing registry discovery payloads, in-app browser verification.

---

## File Structure

- Modify: `src/aidn_hypervisor/static/operator_dashboard.html`
  - Replace the current light card layout with the terminal-style multi-zone dashboard shell, mode-specific layouts, selection state, and richer client-side rendering.
- Modify: `tests/test_api.py`
  - Add route-level assertions that the HTML shell exposes the new structural markers and visual modes.
- Modify: `src/aidn_hypervisor/dashboard.py`
  - Only if needed, normalize market payload details for compare-friendly table columns or inspector data.
- Modify: `src/aidn_hypervisor/service.py`
  - Only if needed, add small operator-dashboard read-model helpers for richer `Home` and `Fleet` summaries.
- Modify: `ROADMAP.md`
  - Mark the terminal dashboard slice as delivered and keep the roadmap aligned with the shipped operator surface.

### Task 1: Lock The New Dashboard Shell Contract In Tests

**Files:**
- Modify: `tests/test_api.py`

- [ ] **Step 1: Write the failing shell test for the terminal layout markers**

```python
def test_operator_dashboard_shell_route_returns_terminal_layout_markup() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert "AiDN Operator Dashboard" in response.text
    assert 'data-screen="home"' in response.text
    assert 'data-screen="fleet"' in response.text
    assert 'data-screen="market"' in response.text
    assert 'data-role="command-rail"' in response.text
    assert 'data-role="metrics-strip"' in response.text
    assert 'data-role="workspace"' in response.text
    assert 'data-role="inspector"' in response.text
    assert 'data-role="operations-band"' in response.text
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `python -m pytest tests/test_api.py::test_operator_dashboard_shell_route_returns_terminal_layout_markup -q`

Expected: `FAIL` because the current static HTML does not expose the terminal layout markers.

- [ ] **Step 3: Add one focused route test for the market execution-table affordances**

```python
def test_operator_dashboard_shell_route_exposes_market_terminal_controls() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert "Execution Market" in response.text
    assert "Selected Offer" in response.text
    assert "Request Queue" in response.text
    assert "Policy Controls" in response.text
```

- [ ] **Step 4: Run the focused tests to verify they fail for the expected reason**

Run: `python -m pytest tests/test_api.py -k terminal_layout_markup or market_terminal_controls -q`

Expected: `FAIL` because the current shell still renders the lighter first-slice wording and structure.

- [ ] **Step 5: Commit**

```bash
git add tests/test_api.py
git commit -m "test: lock terminal dashboard shell contract"
```

### Task 2: Rebuild The Static Dashboard Shell Around The Approved Visual Model

**Files:**
- Modify: `src/aidn_hypervisor/static/operator_dashboard.html`
- Test: `tests/test_api.py`

- [ ] **Step 1: Replace the old topbar/grid shell with the new five-zone structure**

```html
<body>
  <div class="app-shell">
    <aside class="command-rail" data-role="command-rail"></aside>
    <main class="dashboard-stage">
      <section class="metrics-strip" data-role="metrics-strip"></section>
      <section class="workspace" data-role="workspace"></section>
      <aside class="inspector" data-role="inspector"></aside>
      <section class="operations-band" data-role="operations-band"></section>
    </main>
  </div>
</body>
```

- [ ] **Step 2: Run the shell test to verify it still fails until the labels are wired**

Run: `python -m pytest tests/test_api.py::test_operator_dashboard_shell_route_returns_terminal_layout_markup -q`

Expected: `FAIL` if the structure exists but the expected visible labels or navigation markers are not present yet.

- [ ] **Step 3: Add the terminal visual system and responsive behavior**

```css
:root {
  --bg: #06131f;
  --bg-elevated: #0c1d2d;
  --panel: #0f2234;
  --panel-strong: #13293f;
  --line: rgba(145, 180, 214, 0.16);
  --line-strong: rgba(255, 173, 84, 0.34);
  --ink: #ebf3fb;
  --muted: #87a0ba;
  --accent: #ffae57;
  --accent-soft: rgba(255, 174, 87, 0.16);
  --good: #44d07f;
  --bad: #ff6b6b;
  --shadow: 0 24px 80px rgba(0, 0, 0, 0.38);
}

body {
  margin: 0;
  min-height: 100vh;
  color: var(--ink);
  background:
    radial-gradient(circle at top left, rgba(255, 174, 87, 0.14), transparent 28%),
    radial-gradient(circle at bottom right, rgba(53, 140, 255, 0.12), transparent 28%),
    linear-gradient(180deg, #04101a 0%, var(--bg) 100%);
  font-family: "Segoe UI", sans-serif;
}
```

- [ ] **Step 4: Implement mode-specific rendering plus row selection and inspector updates**

```javascript
const state = {
  screen: "home",
  payloads: {},
  selectedMarketCandidateId: null,
  selectedBundleId: null,
};

function selectMarketCandidate(bundleId) {
  state.selectedMarketCandidateId = bundleId;
  render();
}

function selectFleetBundle(bundleId) {
  state.selectedBundleId = bundleId;
  render();
}
```

- [ ] **Step 5: Run the focused shell tests to verify they pass**

Run: `python -m pytest tests/test_api.py -k operator_dashboard_shell_route -q`

Expected: `PASS`

- [ ] **Step 6: Commit**

```bash
git add src/aidn_hypervisor/static/operator_dashboard.html tests/test_api.py
git commit -m "feat: restyle operator dashboard as terminal control room"
```

### Task 3: Add The Minimal Payload Enrichment Needed For The New Inspector

**Files:**
- Modify: `src/aidn_hypervisor/dashboard.py`
- Modify: `src/aidn_hypervisor/service.py`
- Modify: `tests/test_api.py`
- Modify: `tests/test_service.py`

- [ ] **Step 1: Write the failing payload test only if the HTML implementation reveals missing fields**

```python
def test_operator_dashboard_market_endpoint_exposes_compare_friendly_candidate_fields() -> None:
    hypervisor = _service(whisper_endpoint="http://127.0.0.1:9000")
    registry = RegistryService()
    registry.upsert_node(RegistryNodeAdvertisement(**hypervisor.node_advertisement()))
    client = TestClient(build_app(service=hypervisor, registry_service=registry))

    response = client.get("/operators/dashboard/market")

    candidate = response.json()["candidates"][0]
    assert "endpoint_ready" in candidate
    assert "supports_allocation" in candidate
    assert "supports_queue" in candidate
    assert "origin" in candidate
```

- [ ] **Step 2: Run the focused payload test to verify it fails before changing production code**

Run: `python -m pytest tests/test_api.py::test_operator_dashboard_market_endpoint_exposes_compare_friendly_candidate_fields -q`

Expected: `FAIL` only if the current payload is missing one of the fields the new inspector now depends on.

- [ ] **Step 3: Add the smallest payload normalization needed for the new UI**

```python
return {
    "origin": "own",
    "node_id": advertisement["node_id"],
    "operator_id": advertisement["operator_id"],
    "status": advertisement["status"],
    "base_url": advertisement["base_url"],
    "resources": advertisement["resources"]["free"],
    "can_host_custom_model": advertisement["can_host_custom_model"],
    "pricing": advertisement["pricing"],
    "rating": advertisement["rating"],
    "bundle_id": bundle["bundle_id"],
    "plugin_id": bundle["plugin_id"],
    "provider_type": bundle["provider_type"],
    "model_id": bundle["model_id"],
    "workload_type": bundle["workload_type"],
    "endpoint": bundle["endpoint"],
    "supports_allocation": bundle["supports_allocation"],
    "supports_queue": bundle["supports_queue"],
    "endpoint_ready": bool(bundle["endpoint"]) and bundle["status"] == "ready",
}
```

- [ ] **Step 4: Run the focused payload tests to verify they pass**

Run: `python -m pytest tests/test_service.py -k dashboard -q`

Expected: `PASS`

Run: `python -m pytest tests/test_api.py -k operator_dashboard_market_endpoint -q`

Expected: `PASS`

- [ ] **Step 5: Commit**

```bash
git add src/aidn_hypervisor/dashboard.py src/aidn_hypervisor/service.py tests/test_api.py tests/test_service.py
git commit -m "feat: enrich operator dashboard selection payloads"
```

### Task 4: Verify The Desktop Prototype, Then Sync Roadmap State

**Files:**
- Modify: `ROADMAP.md`
- Create: `design-qa.md`
- Test: `tests/test_api.py`
- Test: `tests/test_service.py`

- [ ] **Step 1: Run the dashboard-focused regression tests**

Run: `python -m pytest tests/test_service.py -k dashboard -q`

Expected: `PASS`

Run: `python -m pytest tests/test_api.py -k operator_dashboard -q`

Expected: `PASS`

- [ ] **Step 2: Run the broader slice regression**

Run: `python -m pytest tests/test_service.py tests/test_api.py tests/test_registry_service.py tests/test_registry_api.py -q`

Expected: `PASS`

- [ ] **Step 3: Capture the redesigned dashboard in the in-app browser and compare it against the approved reference**

Run: `uvicorn aidn_hypervisor.main:app --reload --port 8766`

Then verify:
- left command rail is persistent;
- top metrics strip is visible;
- `Home`, `Fleet`, and `Market` each render distinct layouts;
- market row selection updates the inspector;
- bottom operational cards are visible and readable at desktop width;
- narrow-screen layout still stacks cleanly.

- [ ] **Step 4: Save the visual QA result**

```md
# Design QA

final result: passed

- matched the approved terminal-style composition
- preserved AiDN terminology and workflows
- kept desktop density without breaking responsive stacking
```

- [ ] **Step 5: Update roadmap state to reflect the delivered dashboard slice**

```md
- the operator dashboard now ships as a terminal-style multi-zone control room with `Home / Fleet / Market`, right-side inspection, and operator-facing market/fleet visibility on top of the current hypervisor and registry contracts;
```

- [ ] **Step 6: Commit**

```bash
git add ROADMAP.md design-qa.md
git commit -m "docs: sync roadmap with operator dashboard redesign"
```
