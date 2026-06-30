# Operator Dashboard First Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first working operator dashboard slice with real `Home`, `Fleet`, and `Market` data contracts plus a browser-rendered dashboard shell served by the FastAPI app.

**Architecture:** Keep the existing hypervisor service and registry service as the source of truth, then add thin operator-facing read models on top of them. Serve a lightweight HTML/JavaScript dashboard from the hypervisor app that fetches JSON from new operator dashboard endpoints instead of inventing a parallel frontend-only model.

**Tech Stack:** `Python`, `FastAPI`, `pytest`, existing `HypervisorService`, existing `RegistryService`, static HTML/CSS/JavaScript served from the app package.

---

## File Structure

- Modify: `src/aidn_hypervisor/main.py`
  - Allow the hypervisor app to receive an optional registry service and serve the dashboard page.
- Modify: `src/aidn_hypervisor/api.py`
  - Add operator dashboard routes for `home`, `fleet`, `market`, and the HTML shell.
- Modify: `src/aidn_hypervisor/service.py`
  - Add operator dashboard read-model helpers backed by real hypervisor state.
- Create: `src/aidn_hypervisor/dashboard.py`
  - Build market payloads from registry discovery and load the dashboard HTML asset.
- Create: `src/aidn_hypervisor/static/operator_dashboard.html`
  - Render the `Home/Fleet/Market` shell with client-side fetches.
- Modify: `tests/test_service.py`
  - Add service-level tests for fleet and home read models.
- Modify: `tests/test_api.py`
  - Add API tests for dashboard JSON routes and HTML shell.

### Task 1: Add Hypervisor Dashboard Read Models

**Files:**
- Modify: `src/aidn_hypervisor/service.py`
- Test: `tests/test_service.py`

- [ ] **Step 1: Write the failing service tests**

```python
def test_service_dashboard_fleet_reports_node_resources_bundles_and_installs(tmp_path) -> None:
    store = FileModelStore(tmp_path)
    service = _service(model_store=store)
    install = service.request_model_install(
        requested_by="operator-a",
        source_uri="https://example.invalid/models/phi4.gguf",
        model_id="phi4-gguf",
        plugin_id="fake-managed",
        provider_type="fake",
        workload_type="llm_text",
    )

    fleet = service.operator_dashboard_fleet()

    assert fleet["node"]["node_id"] == service.node_id
    assert fleet["node"]["operator_id"] == service.operator_id
    assert fleet["resources"]["free"]["cpu"] == pytest.approx(6.5)
    assert fleet["queue"]["queued"] == 0
    assert fleet["bundles"][0]["bundle_id"] == "whisper-a"
    assert fleet["bundles"][0]["publish_status"] == "ready_to_publish"
    assert fleet["installs"][0]["install_id"] == install["install_id"]
    assert fleet["installs"][0]["install_status"] == "pending"


def test_service_dashboard_home_reports_publish_market_and_capacity_blocks(tmp_path) -> None:
    store = FileModelStore(tmp_path)
    service = _service(model_store=store, whisper_endpoint="http://127.0.0.1:9000")
    service.request_model_install(
        requested_by="operator-a",
        source_uri="https://example.invalid/models/phi4.gguf",
        model_id="phi4-gguf",
        plugin_id="fake-managed",
        provider_type="fake",
        workload_type="llm_text",
    )

    home = service.operator_dashboard_home()

    assert home["publish"]["draft_offer_count"] == 3
    assert home["publish"]["install_pending_count"] == 1
    assert home["market_visibility"]["local_offer_count"] == 3
    assert home["fleet_capacity"]["node_count"] == 1
    assert "Publish Offer" in home["operator_controls"]["actions"]
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `python -m pytest tests/test_service.py -k dashboard -q`

Expected: `FAIL` with missing `operator_dashboard_fleet` and `operator_dashboard_home` on `HypervisorService`.

- [ ] **Step 3: Write the minimal read-model implementation**

```python
def operator_dashboard_fleet(self) -> dict:
    resources = self.resources.summary() if self.resources is not None else _empty_resource_summary()
    runtimes = {runtime.bundle_id: runtime for runtime in self.list_runtimes()}
    bundles = []
    for bundle in self.bundles:
        state = self.bundle_state(bundle.bundle_id)
        runtime = runtimes.get(bundle.bundle_id)
        bundles.append(
            {
                "bundle_id": bundle.bundle_id,
                "plugin_id": bundle.plugin_id,
                "provider_type": bundle.provider_type,
                "workload_type": bundle.workload_type,
                "model_id": bundle.model_id,
                "enabled": bundle.enabled,
                "endpoint": bundle.endpoint,
                "runtime_status": runtime.status if runtime is not None else "stopped",
                "publish_status": "ready_to_publish" if bundle.enabled else "disabled",
                "cooldown_until": state["cooldown_until"],
                "drain_mode": state["drain_mode"],
            }
        )
    return {
        "node": {
            "node_id": self.node_id,
            "operator_id": self.operator_id,
            "base_url": self.base_url,
            "can_host_custom_model": self.can_host_custom_model,
            "pricing": self.pricing,
            "rating": self.rating,
        },
        "resources": resources,
        "queue": self.queue_summary(),
        "installs": [
            {
                "install_id": install["install_id"],
                "model_id": install["model_id"],
                "plugin_id": install["plugin_id"],
                "provider_type": install["provider_type"],
                "requested_by": install["requested_by"],
                "install_status": install["status"],
                "created_at": install["created_at"],
            }
            for install in self.list_model_installs()
        ],
        "bundles": bundles,
    }


def operator_dashboard_home(self) -> dict:
    fleet = self.operator_dashboard_fleet()
    return {
        "publish": {
            "install_pending_count": sum(1 for item in fleet["installs"] if item["install_status"] == "pending"),
            "draft_offer_count": len(fleet["bundles"]),
            "live_offer_count": sum(1 for item in fleet["bundles"] if item["enabled"]),
        },
        "market_visibility": {
            "local_offer_count": len(fleet["bundles"]),
            "live_offer_count": sum(1 for item in fleet["bundles"] if item["enabled"]),
        },
        "fleet_capacity": {
            "node_count": 1,
            "queued": fleet["queue"]["queued"],
            "active": fleet["queue"]["active"],
            "free": fleet["resources"]["free"],
        },
        "operator_controls": {
            "actions": [
                "Install Model",
                "Publish Offer",
                "Attach Endpoint",
                "Pause Queue",
                "Raise Limits",
                "Connect Remote Node",
            ]
        },
    }
```

- [ ] **Step 4: Run the focused tests to verify they pass**

Run: `python -m pytest tests/test_service.py -k dashboard -q`

Expected: `PASS`

- [ ] **Step 5: Commit**

```bash
git add src/aidn_hypervisor/service.py tests/test_service.py
git commit -m "feat: add operator dashboard read models"
```

### Task 2: Add Market Aggregation And Dashboard API Endpoints

**Files:**
- Create: `src/aidn_hypervisor/dashboard.py`
- Modify: `src/aidn_hypervisor/api.py`
- Modify: `src/aidn_hypervisor/main.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write the failing API tests**

```python
def test_operator_dashboard_fleet_endpoint_returns_aggregated_payload(tmp_path) -> None:
    service = _service(model_store=FileModelStore(tmp_path))
    client = TestClient(build_app(service=service))

    response = client.get("/operators/dashboard/fleet")

    assert response.status_code == 200
    assert response.json()["node"]["node_id"] == service.node_id
    assert response.json()["bundles"][0]["bundle_id"] == "whisper-a"


def test_operator_dashboard_market_endpoint_marks_own_and_external_candidates() -> None:
    hypervisor = _service(whisper_endpoint="http://127.0.0.1:9000")
    registry = RegistryService()
    registry.upsert_node(RegistryNodeAdvertisement(**hypervisor.node_advertisement()))
    registry.upsert_node(
        RegistryNodeAdvertisement(
            node_id="node-external",
            operator_id="operator-b",
            base_url="https://remote.example",
            heartbeat_at="2026-06-20T12:00:00Z",
            resources={"total": {"cpu": 12.0, "ram_mb": 32768, "vram_mb": 16384}, "free": {"cpu": 8.0, "ram_mb": 24576, "vram_mb": 8192}},
            providers=["fake"],
            can_host_custom_model=True,
            pricing={"unit": "q_per_1kk_tokens", "input": 9, "output": 15, "fixed_request": 1},
            rating={"score": 0.97, "tier": "A", "updated_at": "2026-06-20T11:55:00Z"},
            bundles=[{
                "bundle_id": "remote-text",
                "plugin_id": "fake-managed",
                "workload_type": "llm_text",
                "provider_type": "fake",
                "model_id": "remote-text-model",
                "endpoint": "https://remote.example/runtimes/remote-text",
                "enabled": True,
                "status": "ready",
                "launch_mode": "attached_service",
                "device_affinity": "cpu",
                "max_parallel_requests": 2,
                "supports_allocation": True,
                "supports_queue": True,
            }],
        )
    )
    client = TestClient(build_app(service=hypervisor, registry_service=registry))

    response = client.get("/operators/dashboard/market")

    assert response.status_code == 200
    assert response.json()["candidates"][0]["origin"] in {"own", "external"}
    assert {item["origin"] for item in response.json()["candidates"]} == {"own", "external"}
```

- [ ] **Step 2: Run the focused API tests to verify they fail**

Run: `python -m pytest tests/test_api.py -k operator_dashboard -q`

Expected: `FAIL` with missing dashboard routes or unexpected `build_app()` signature.

- [ ] **Step 3: Implement minimal dashboard aggregation and routes**

```python
# src/aidn_hypervisor/dashboard.py
from pathlib import Path

from aidn_hypervisor.registry_models import RegistryDiscoveryQuery


def build_market_payload(*, service, registry_service) -> dict:
    if registry_service is None:
        own = service.node_advertisement()
        nodes = [own]
        candidates = [
            {
                "origin": "own",
                "node_id": own["node_id"],
                "operator_id": own["operator_id"],
                "status": own["status"],
                "pricing": own["pricing"],
                "rating": own["rating"],
                "can_host_custom_model": own["can_host_custom_model"],
                "resources": own["resources"]["free"],
                **bundle,
                "endpoint_ready": bool(bundle.get("endpoint")) and bundle["status"] == "ready",
            }
            for bundle in own["bundles"]
        ]
        return {"nodes": nodes, "candidates": candidates}

    discovery = registry_service.discover(RegistryDiscoveryQuery())
    for candidate in discovery["candidates"]:
        candidate["origin"] = "own" if candidate["node_id"] == service.node_id else "external"
    return discovery


def load_dashboard_html() -> str:
    path = Path(__file__).with_name("static") / "operator_dashboard.html"
    return path.read_text(encoding="utf-8")
```

```python
# build_app
def build_app(
    service: HypervisorService | None = None,
    registry_service: RegistryService | None = None,
) -> FastAPI:
    ...
    app.include_router(build_api_router(service or _build_default_service(), registry_service=registry_service))
```

```python
# build_api_router
from fastapi.responses import HTMLResponse
from aidn_hypervisor.dashboard import build_market_payload, load_dashboard_html

def build_api_router(service: HypervisorService, registry_service: RegistryService | None = None) -> APIRouter:
    router = APIRouter()

    @router.get("/operators/dashboard", response_class=HTMLResponse)
    async def operator_dashboard() -> str:
        return load_dashboard_html()

    @router.get("/operators/dashboard/home")
    async def operator_dashboard_home() -> dict:
        home = service.operator_dashboard_home()
        home["market_preview"] = {
            "candidate_count": len(build_market_payload(service=service, registry_service=registry_service)["candidates"])
        }
        return home

    @router.get("/operators/dashboard/fleet")
    async def operator_dashboard_fleet() -> dict:
        return service.operator_dashboard_fleet()

    @router.get("/operators/dashboard/market")
    async def operator_dashboard_market() -> dict:
        return build_market_payload(service=service, registry_service=registry_service)
```

- [ ] **Step 4: Run the focused API tests to verify they pass**

Run: `python -m pytest tests/test_api.py -k operator_dashboard -q`

Expected: `PASS`

- [ ] **Step 5: Commit**

```bash
git add src/aidn_hypervisor/main.py src/aidn_hypervisor/api.py src/aidn_hypervisor/dashboard.py tests/test_api.py
git commit -m "feat: add operator dashboard api"
```

### Task 3: Add The Dashboard HTML Shell

**Files:**
- Create: `src/aidn_hypervisor/static/operator_dashboard.html`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write the failing HTML route test**

```python
def test_operator_dashboard_shell_route_returns_home_fleet_market_markup() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert "AiDN Operator Dashboard" in response.text
    assert 'data-screen="home"' in response.text
    assert 'data-screen="fleet"' in response.text
    assert 'data-screen="market"' in response.text
```

- [ ] **Step 2: Run the route test to verify it fails**

Run: `python -m pytest tests/test_api.py::test_operator_dashboard_shell_route_returns_home_fleet_market_markup -q`

Expected: `FAIL` until the static HTML contains the expected shell.

- [ ] **Step 3: Write the minimal interactive shell**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>AiDN Operator Dashboard</title>
  <style>
    :root { --bg:#f5efe5; --panel:#fffaf4; --ink:#182126; --muted:#61707a; --line:rgba(24,33,38,0.12); --accent:#c05c36; --good:#2f6c57; }
    body { margin:0; font-family:"Segoe UI",sans-serif; color:var(--ink); background:linear-gradient(180deg,#f9f3ea 0%, var(--bg) 100%); }
    .shell { max-width:1400px; margin:0 auto; padding:28px; }
    .topbar, .panel { background:var(--panel); border:1px solid var(--line); border-radius:20px; }
    .topbar { display:flex; justify-content:space-between; align-items:center; padding:18px 22px; margin-bottom:18px; }
    .nav { display:flex; gap:10px; }
    .nav button { border:1px solid var(--line); background:#fff; border-radius:999px; padding:10px 14px; cursor:pointer; }
    .nav button.active { background:var(--accent); color:#fff; border-color:var(--accent); }
    .grid { display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); gap:16px; }
    .panel { padding:18px; min-height:180px; }
    .muted { color:var(--muted); }
    .chips { display:flex; flex-wrap:wrap; gap:8px; margin-top:12px; }
    .chip { padding:6px 10px; border-radius:999px; background:#fff; border:1px solid var(--line); font-size:12px; }
    .rows { display:grid; gap:10px; margin-top:12px; }
    .row { padding:12px; border-radius:14px; border:1px solid var(--line); background:#fff; }
    @media (max-width: 960px) { .grid { grid-template-columns:1fr; } .topbar { flex-direction:column; align-items:flex-start; gap:12px; } }
  </style>
</head>
<body>
  <div class="shell">
    <div class="topbar">
      <div>
        <h1>AiDN Operator Dashboard</h1>
        <p class="muted">Fleet + Market command center for publish, compare, and attach flows.</p>
      </div>
      <div class="nav">
        <button class="active" data-screen="home">Home</button>
        <button data-screen="fleet">Fleet</button>
        <button data-screen="market">Market</button>
      </div>
    </div>
    <div id="screen"></div>
  </div>
  <script>
    const state = { screen: "home", payloads: {} };
    const endpoints = {
      home: "/operators/dashboard/home",
      fleet: "/operators/dashboard/fleet",
      market: "/operators/dashboard/market",
    };
    async function loadScreen(screen) {
      state.screen = screen;
      document.querySelectorAll("[data-screen]").forEach((button) => {
        button.classList.toggle("active", button.dataset.screen === screen);
      });
      const response = await fetch(endpoints[screen]);
      state.payloads[screen] = await response.json();
      render();
    }
    function render() {
      const root = document.getElementById("screen");
      const payload = state.payloads[state.screen] || {};
      if (state.screen === "home") {
        root.innerHTML = `<div class="grid">
          <section class="panel"><h2>Publish & Onboard</h2><div class="rows"><div class="row">Draft offers: ${payload.publish?.draft_offer_count ?? 0}</div><div class="row">Pending installs: ${payload.publish?.install_pending_count ?? 0}</div><div class="chips">${(payload.operator_controls?.actions ?? []).map((item) => `<span class="chip">${item}</span>`).join("")}</div></div></section>
          <section class="panel"><h2>Market Visibility</h2><div class="rows"><div class="row">Local offers: ${payload.market_visibility?.local_offer_count ?? 0}</div><div class="row">Market candidates: ${payload.market_preview?.candidate_count ?? 0}</div></div></section>
          <section class="panel"><h2>Fleet Capacity</h2><div class="rows"><div class="row">Nodes: ${payload.fleet_capacity?.node_count ?? 0}</div><div class="row">Queued tasks: ${payload.fleet_capacity?.queued ?? 0}</div></div></section>
          <section class="panel"><h2>Operator Controls</h2><p class="muted">Quick actions stay here while deep flows live in Fleet and Market.</p></section>
        </div>`;
        return;
      }
      if (state.screen === "fleet") {
        root.innerHTML = `<div class="grid">
          <section class="panel"><h2>Node</h2><div class="rows"><div class="row">${payload.node?.node_id ?? "-"}</div><div class="row">Operator: ${payload.node?.operator_id ?? "-"}</div></div></section>
          <section class="panel"><h2>Bundles</h2><div class="rows">${(payload.bundles ?? []).map((item) => `<div class="row"><strong>${item.bundle_id}</strong><div class="muted">${item.model_id} / ${item.publish_status}</div></div>`).join("")}</div></section>
          <section class="panel"><h2>Installs</h2><div class="rows">${(payload.installs ?? []).map((item) => `<div class="row"><strong>${item.model_id}</strong><div class="muted">${item.install_status}</div></div>`).join("") || '<div class="row">No installs</div>'}</div></section>
          <section class="panel"><h2>Resources</h2><div class="rows"><div class="row">CPU free: ${payload.resources?.free?.cpu ?? 0}</div><div class="row">RAM free: ${payload.resources?.free?.ram_mb ?? 0} MB</div><div class="row">VRAM free: ${payload.resources?.free?.vram_mb ?? 0} MB</div></div></section>
        </div>`;
        return;
      }
      root.innerHTML = `<div class="grid">
        <section class="panel"><h2>Market Candidates</h2><div class="rows">${(payload.candidates ?? []).map((item) => `<div class="row"><strong>${item.bundle_id}</strong><div class="muted">${item.origin} / ${item.model_id} / in ${item.pricing?.input ?? 0}q / rating ${item.rating?.score ?? 0}</div></div>`).join("")}</div></section>
        <section class="panel"><h2>Market Summary</h2><div class="rows"><div class="row">Candidates: ${(payload.candidates ?? []).length}</div><div class="row">Nodes: ${(payload.nodes ?? []).length}</div></div></section>
      </div>`;
    }
    document.querySelectorAll("[data-screen]").forEach((button) => {
      button.addEventListener("click", () => loadScreen(button.dataset.screen));
    });
    loadScreen("home");
  </script>
</body>
</html>
```

- [ ] **Step 4: Run the shell test to verify it passes**

Run: `python -m pytest tests/test_api.py::test_operator_dashboard_shell_route_returns_home_fleet_market_markup -q`

Expected: `PASS`

- [ ] **Step 5: Commit**

```bash
git add src/aidn_hypervisor/static/operator_dashboard.html tests/test_api.py
git commit -m "feat: add operator dashboard shell"
```

### Task 4: Run The Full Slice And Refresh The Mockup

**Files:**
- Modify: `docs/superpowers/mockups/operator-market-dashboard-options.html`
- Test: `tests/test_service.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Add one end-to-end API test for dashboard home and market**

```python
def test_operator_dashboard_home_and_market_routes_share_real_operator_state(tmp_path) -> None:
    hypervisor = _service(model_store=FileModelStore(tmp_path), whisper_endpoint="http://127.0.0.1:9000")
    registry = RegistryService()
    registry.upsert_node(RegistryNodeAdvertisement(**hypervisor.node_advertisement()))
    client = TestClient(build_app(service=hypervisor, registry_service=registry))

    home = client.get("/operators/dashboard/home")
    market = client.get("/operators/dashboard/market")

    assert home.status_code == 200
    assert market.status_code == 200
    assert home.json()["market_preview"]["candidate_count"] == len(market.json()["candidates"])
```

- [ ] **Step 2: Run the dashboard-focused suite**

Run: `python -m pytest tests/test_service.py -k dashboard -q`

Expected: `PASS`

Run: `python -m pytest tests/test_api.py -k operator_dashboard -q`

Expected: `PASS`

- [ ] **Step 3: Run the broader regression slice**

Run: `python -m pytest tests/test_service.py tests/test_api.py tests/test_registry_service.py tests/test_registry_api.py -q`

Expected: `PASS`

- [ ] **Step 4: Refresh the visual mockup so the static design reference still matches the shipped shell**

```html
<!-- Keep option C aligned with the first shipping shell:
     Home + Fleet + Market, quick actions, market candidates,
     and no wallet-first emphasis. -->
```

- [ ] **Step 5: Commit**

```bash
git add tests/test_service.py tests/test_api.py docs/superpowers/mockups/operator-market-dashboard-options.html
git commit -m "test: cover operator dashboard first slice"
```
