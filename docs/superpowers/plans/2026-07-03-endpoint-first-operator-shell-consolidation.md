# Endpoint-First Operator Shell Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate the operator dashboard around a single endpoint-first view-model layer, then extend the shell with actionable `Providers`, `Bundles`, and `Installs` workflows that support the operator bootstrap funnel.

**Architecture:** Introduce a new read-only `operator_views.py` module as the canonical owner of dashboard payload composition. Move richer dashboard shaping out of `api.py`, keep domain services as factual state and command sources, and gradually reduce old `HypervisorService.operator_dashboard_*()` methods to factual summaries. Expand the operator API and dashboard UI around one bootstrap funnel: `wallet -> provider/model -> bundle -> endpoint -> publish`.

**Tech Stack:** Python, FastAPI, Pydantic, pytest, existing `aidn_hypervisor` services and static dashboard HTML.

---

## File Structure

### New files

- `src/aidn_hypervisor/operator_views.py`
  - Canonical operator-facing payload builders for `Home`, `Endpoints`, `Providers`, `Bundles`, `Installs`, `Market`, and `Remote Endpoints`
- `tests/test_operator_views.py`
  - Focused unit tests for bootstrap funnel, next-step logic, publication sync summaries, and provider/bundle/install payload composition

### Existing files to modify

- `src/aidn_hypervisor/api.py`
  - Replace in-file dashboard builders with `operator_views.py` imports
  - Add operator routes for `providers`, `bundles`, and `installs`
- `src/aidn_hypervisor/service.py`
  - Keep wallet and node-identity facts as-is
  - Reduce `operator_dashboard_home()`, `operator_dashboard_fleet()`, and `operator_dashboard_endpoints()` to transitional factual summaries only
- `src/aidn_hypervisor/static/operator_dashboard.html`
  - Add workspaces for `Providers`, `Bundles`, and `Installs`
  - Rewire `Home` to render the centralized bootstrap funnel and recommended next actions
- `tests/test_api.py`
  - Update or add route-level assertions for new operator dashboard payloads and shell wiring
- `tests/test_service.py`
  - Narrow service tests toward factual summary behavior where operator payload ownership moves into `operator_views.py`

### Existing reference files to inspect while implementing

- `docs/superpowers/specs/2026-07-03-endpoint-first-operator-shell-consolidation-design.md`
- `src/aidn_hypervisor/api.py:153-241`
- `src/aidn_hypervisor/api.py:1024-1048`
- `src/aidn_hypervisor/api.py:1509-1524`
- `src/aidn_hypervisor/api.py:1549-1561`
- `src/aidn_hypervisor/api.py:1803-1821`
- `src/aidn_hypervisor/service.py:1235-1354`
- `tests/test_api.py:1751-1817`
- `tests/test_service.py:1057-1082`

---

### Task 1: Create The Operator View-Model Layer

**Files:**
- Create: `src/aidn_hypervisor/operator_views.py`
- Create: `tests/test_operator_views.py`
- Modify: `src/aidn_hypervisor/api.py:153-241`

- [ ] **Step 1: Write the failing view-model tests**

```python
from aidn_hypervisor.operator_views import (
    build_operator_home_payload,
    build_operator_endpoints_payload,
)


def test_home_payload_requires_wallet_before_network_actions(service, endpoint_service):
    payload = build_operator_home_payload(
        service=service,
        endpoint_service=endpoint_service,
        endpoint_publication_service=None,
        validation_service=None,
        market_candidates=[],
    )

    assert payload["bootstrap"]["wallet_ready"] is False
    assert payload["bootstrap"]["next_step"] == "Create or import a wallet"


def test_home_payload_prefers_first_endpoint_candidate_after_wallet_setup(
    service, endpoint_service
):
    service.configure_owner_wallet(mode="create", label="Primary Wallet")

    payload = build_operator_home_payload(
        service=service,
        endpoint_service=endpoint_service,
        endpoint_publication_service=None,
        validation_service=None,
        market_candidates=[],
    )

    assert payload["bootstrap"]["wallet_ready"] is True
    assert payload["bootstrap"]["first_endpoint_candidate"]["bundle_id"] == "whisper-a"
    assert payload["bootstrap"]["next_step"] == "Create your first endpoint from whisper-a"


def test_endpoints_payload_includes_publication_sync_and_validation_summary(
    service, endpoint_service, endpoint_publication_service, validation_service
):
    payload = build_operator_endpoints_payload(
        service=service,
        endpoint_service=endpoint_service,
        endpoint_publication_service=endpoint_publication_service,
        validation_service=validation_service,
    )

    assert "summary" in payload
    assert "items" in payload
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_operator_views.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aidn_hypervisor.operator_views'`

- [ ] **Step 3: Write the minimal operator view-model module**

```python
from aidn_hypervisor.dashboard import build_market_payload


def build_operator_home_payload(
    *,
    service,
    endpoint_service,
    endpoint_publication_service=None,
    validation_service=None,
    market_candidates=None,
):
    market_candidates = market_candidates or []
    endpoints_payload = build_operator_endpoints_payload(
        service=service,
        endpoint_service=endpoint_service,
        endpoint_publication_service=endpoint_publication_service,
        validation_service=validation_service,
    )
    bootstrap = _build_home_bootstrap(
        service=service,
        endpoint_items=endpoints_payload["items"],
        provider_count=len(service.plugins.list()) if hasattr(service.plugins, "list") else 0,
        bundle_count=len(service.bundles),
        first_endpoint_candidate=service.operator_dashboard_home()["bootstrap"].get(
            "first_endpoint_candidate"
        ),
    )
    return {
        "bootstrap": bootstrap,
        "market_preview": {"candidate_count": len(market_candidates)},
    }


def build_operator_endpoints_payload(
    *,
    service,
    endpoint_service,
    endpoint_publication_service=None,
    validation_service=None,
):
    return {
        "owner_wallet": service.owner_wallet_state(),
        "node_identity": service.node_identity(),
        "summary": {"total": 0, "configured": 0, "published": 0, "validation_requested": 0, "private": 0, "shared": 0, "public": 0},
        "policy": {
            "publish_requires_validation": False,
            "validation_optional": True,
            "execution_privacy": "endpoint implementation remains private",
        },
        "items": [],
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_operator_views.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aidn_hypervisor/operator_views.py tests/test_operator_views.py src/aidn_hypervisor/api.py
git commit -m "feat: add operator view model layer"
```

### Task 2: Move Existing Home And Endpoints Dashboard Composition To Operator Views

**Files:**
- Modify: `src/aidn_hypervisor/operator_views.py`
- Modify: `src/aidn_hypervisor/api.py:1024-1048`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Write the failing API regression tests**

```python
def test_operator_dashboard_home_route_uses_operator_view_payload(client):
    response = client.get("/operators/dashboard/home")

    assert response.status_code == 200
    payload = response.json()
    assert "bootstrap" in payload
    assert "market_preview" in payload
    assert "node_identity" in payload["bootstrap"]


def test_operator_dashboard_endpoints_route_uses_endpoint_first_payload(client):
    response = client.get("/operators/dashboard/endpoints")

    assert response.status_code == 200
    payload = response.json()
    assert "summary" in payload
    assert "items" in payload
    assert "owner_wallet" in payload
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_api.py -k "dashboard_home_route_uses_operator_view_payload or dashboard_endpoints_route_uses_endpoint_first_payload" -v`
Expected: FAIL because the new payload keys or route behavior are not wired through `operator_views.py`

- [ ] **Step 3: Replace the route-level payload assembly**

```python
from aidn_hypervisor.operator_views import (
    build_operator_endpoints_payload,
    build_operator_home_payload,
)


@router.get("/operators/dashboard/home")
async def operator_dashboard_home() -> dict:
    market = build_market_payload(service=service, registry_service=registry_service)
    return build_operator_home_payload(
        service=service,
        endpoint_service=endpoint_service,
        endpoint_publication_service=endpoint_publication_service,
        validation_service=validation_service,
        market_candidates=market["candidates"],
    )


@router.get("/operators/dashboard/endpoints")
async def operator_dashboard_endpoints() -> dict:
    return build_operator_endpoints_payload(
        service=service,
        endpoint_service=endpoint_service,
        endpoint_publication_service=endpoint_publication_service,
        validation_service=validation_service,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_api.py -k "dashboard_home_route_uses_operator_view_payload or dashboard_endpoints_route_uses_endpoint_first_payload" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aidn_hypervisor/operator_views.py src/aidn_hypervisor/api.py tests/test_api.py
git commit -m "feat: route dashboard home and endpoints through operator views"
```

### Task 3: Add Providers, Bundles, And Installs Payload Builders And Routes

**Files:**
- Modify: `src/aidn_hypervisor/operator_views.py`
- Modify: `src/aidn_hypervisor/api.py:1803-1821`
- Modify: `tests/test_operator_views.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Write the failing payload and route tests**

```python
def test_build_operator_bundles_payload_marks_first_endpoint_candidate(service):
    payload = build_operator_bundles_payload(service=service)

    assert "items" in payload
    assert any(item["is_first_endpoint_candidate"] for item in payload["items"])


def test_operator_dashboard_providers_route_returns_workspace_payload(client):
    response = client.get("/operators/dashboard/providers")

    assert response.status_code == 200
    payload = response.json()
    assert "summary" in payload
    assert "items" in payload


def test_operator_dashboard_installs_route_returns_actionable_install_state(client):
    response = client.get("/operators/dashboard/installs")

    assert response.status_code == 200
    payload = response.json()
    assert "summary" in payload
    assert "items" in payload
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_operator_views.py tests/test_api.py -k "bundles_payload_marks_first_endpoint_candidate or dashboard_providers_route_returns_workspace_payload or dashboard_installs_route_returns_actionable_install_state" -v`
Expected: FAIL with missing builders and/or missing routes

- [ ] **Step 3: Implement the new builders and routes**

```python
def build_operator_bundles_payload(*, service):
    candidate = service.operator_dashboard_home()["bootstrap"].get("first_endpoint_candidate")
    candidate_id = candidate["bundle_id"] if candidate else None
    items = []
    for bundle in service.bundles:
        items.append(
            {
                "bundle_id": bundle.bundle_id,
                "model_name": bundle.model_name,
                "provider": bundle.provider_type,
                "enabled": bundle.enabled,
                "is_first_endpoint_candidate": bundle.bundle_id == candidate_id,
            }
        )
    return {"summary": {"total": len(items)}, "items": items}


@router.get("/operators/dashboard/providers")
async def operator_dashboard_providers() -> dict:
    return build_operator_providers_payload(service=service)


@router.get("/operators/dashboard/bundles")
async def operator_dashboard_bundles() -> dict:
    return build_operator_bundles_payload(service=service)


@router.get("/operators/dashboard/installs")
async def operator_dashboard_installs() -> dict:
    return build_operator_installs_payload(service=service)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_operator_views.py tests/test_api.py -k "bundles_payload_marks_first_endpoint_candidate or dashboard_providers_route_returns_workspace_payload or dashboard_installs_route_returns_actionable_install_state" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aidn_hypervisor/operator_views.py src/aidn_hypervisor/api.py tests/test_operator_views.py tests/test_api.py
git commit -m "feat: add operator provider bundle and install views"
```

### Task 4: Expand The Dashboard UI To Use The New Operator Workspaces

**Files:**
- Modify: `src/aidn_hypervisor/static/operator_dashboard.html`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Write the failing dashboard-shell tests**

```python
def test_operator_dashboard_shell_exposes_provider_bundle_and_install_workspaces() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert "Providers" in response.text
    assert "Bundles" in response.text
    assert "Installs" in response.text
    assert "/operators/dashboard/providers" in response.text
    assert "/operators/dashboard/bundles" in response.text
    assert "/operators/dashboard/installs" in response.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_api.py -k "operator_dashboard_shell_exposes_provider_bundle_and_install_workspaces" -v`
Expected: FAIL because those workspace endpoints or shell hooks are not rendered yet

- [ ] **Step 3: Add workspace fetch and render wiring**

```javascript
async function loadProvidersWorkspace() {
  state.payloads.providers = await fetchJson("/operators/dashboard/providers");
}

async function loadBundlesWorkspace() {
  state.payloads.bundles = await fetchJson("/operators/dashboard/bundles");
}

async function loadInstallsWorkspace() {
  state.payloads.installs = await fetchJson("/operators/dashboard/installs");
}

function renderProvidersWorkspace() {
  const payload = state.payloads.providers || { items: [], summary: {} };
  return `<div class="workspace-header"><h1 class="workspace-title">Providers</h1></div>`;
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_api.py -k "operator_dashboard_shell_exposes_provider_bundle_and_install_workspaces" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aidn_hypervisor/static/operator_dashboard.html tests/test_api.py
git commit -m "feat: add provider bundle and install dashboard workspaces"
```

### Task 5: Reduce Legacy Service Dashboard Methods To Factual Summaries

**Files:**
- Modify: `src/aidn_hypervisor/service.py:1275-1354`
- Modify: `tests/test_service.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Write the failing service-transition tests**

```python
def test_service_dashboard_home_remains_factual_summary_during_transition(service) -> None:
    payload = service.operator_dashboard_home()

    assert "bootstrap" in payload
    assert "publish" in payload
    assert "fleet_capacity" in payload
    assert "market_preview" not in payload


def test_service_dashboard_endpoints_remains_minimal_fallback_summary(service) -> None:
    payload = service.operator_dashboard_endpoints()

    assert "summary" in payload
    assert "items" in payload
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_service.py -k "service_dashboard_home_remains_factual_summary_during_transition or service_dashboard_endpoints_remains_minimal_fallback_summary" -v`
Expected: FAIL if service methods still expose richer UI-owned behavior or incompatible summary shapes

- [ ] **Step 3: Simplify the legacy service methods**

```python
def operator_dashboard_home(self) -> dict:
    fleet = self.operator_dashboard_fleet()
    return {
        "bootstrap": self._operator_dashboard_bootstrap(fleet),
        "publish": {
            "draft_offer_count": len(fleet["bundles"]),
            "install_pending_count": sum(
                1 for install in fleet["installs"] if install["install_status"] in {"pending", "running"}
            ),
            "live_offer_count": sum(1 for bundle in fleet["bundles"] if bundle["enabled"]),
        },
        "fleet_capacity": {
            "node_count": 1,
            "queued": fleet["queue"]["queued"],
            "active": fleet["queue"]["active"],
            "free": fleet["resources"]["free"],
        },
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_service.py tests/test_api.py -k "service_dashboard_home_remains_factual_summary_during_transition or service_dashboard_endpoints_remains_minimal_fallback_summary" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aidn_hypervisor/service.py tests/test_service.py tests/test_api.py
git commit -m "refactor: reduce legacy dashboard services to factual summaries"
```

## Final Verification

- [ ] **Step 1: Run focused operator view and dashboard tests**

Run: `pytest tests/test_operator_views.py tests/test_api.py tests/test_service.py -k "dashboard or operator or wallet_bootstrap or endpoint" -v`
Expected: PASS

- [ ] **Step 2: Run endpoint and session regression coverage**

Run: `pytest tests/endpoints/test_endpoint_api.py tests/endpoints/test_service.py tests/test_wallet.py tests/sessions/test_service.py -v`
Expected: PASS

- [ ] **Step 3: Run validation regression coverage**

Run: `pytest tests/validation/test_service.py -v`
Expected: PASS

- [ ] **Step 4: Smoke-check the static dashboard shell**

Run: `python -m http.server 8879 --bind 127.0.0.1`
Expected: Dashboard shell assets load locally and the operator shell renders the new workspaces without template errors

- [ ] **Step 5: Final integration commit**

```bash
git add src/aidn_hypervisor/operator_views.py src/aidn_hypervisor/api.py src/aidn_hypervisor/service.py src/aidn_hypervisor/static/operator_dashboard.html tests/test_operator_views.py tests/test_api.py tests/test_service.py
git commit -m "feat: consolidate endpoint-first operator shell"
```

## Self-Review

### Spec coverage

This plan covers:
- creation of `operator_views.py`;
- movement of dashboard payload ownership out of `api.py`;
- preservation and reduction of legacy service dashboard methods to factual summaries;
- new `Providers`, `Bundles`, and `Installs` operator payloads and routes;
- dashboard UI expansion for the bootstrap funnel;
- route and regression test coverage.

### Placeholder scan

No `TODO`, `TBD`, or deferred implementation markers remain in the tasks.

### Type consistency

The plan consistently uses:
- `build_operator_home_payload`
- `build_operator_endpoints_payload`
- `build_operator_providers_payload`
- `build_operator_bundles_payload`
- `build_operator_installs_payload`

The same names should be preserved during implementation to avoid churn between tests, API routes, and frontend consumers.
