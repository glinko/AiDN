# Operator Requests Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first live `Requests` workspace in the operator dashboard with real queue triage, task inspection, cancellation, persisted spillover policy, and policy-driven market spillover preview.

**Architecture:** Keep the existing FastAPI app, `HypervisorService`, and static dashboard shell as the backbone. Add one operator-facing requests read model plus a small policy write path on the backend, then extend the dashboard shell with a new `Requests` mode that consumes those contracts and reuses the existing task detail and cancellation APIs.

**Tech Stack:** `Python`, `FastAPI`, `pytest`, static `HTML/CSS/JavaScript`, existing `HypervisorService`, existing queue/task APIs, existing market payload builder, in-app browser verification.

---

## File Structure

- Modify: `src/aidn_hypervisor/service.py`
  - Add persisted operator spillover policy state plus `operator_dashboard_requests()` read-model aggregation.
- Modify: `src/aidn_hypervisor/api.py`
  - Add `GET /operators/dashboard/requests` and one small policy update endpoint for the requests workspace.
- Modify: `src/aidn_hypervisor/state.py`
  - Persist the new operator requests policy through snapshot and restore.
- Modify: `src/aidn_hypervisor/static/operator_dashboard.html`
  - Add a live `Requests` rail entry, requests workspace rendering, task inspector logic, and policy controls.
- Modify: `tests/test_service.py`
  - Add read-model and policy persistence tests for the requests workspace.
- Modify: `tests/test_api.py`
  - Add dashboard route and policy API tests plus shell contract assertions for requests controls.
- Modify: `ROADMAP.md`
  - Mark the requests workspace slice as delivered after the feature is verified.
- Modify: `design-qa.md`
  - Record the browser verification result for the new requests mode.

### Task 1: Add The Requests Read Model And Persisted Spillover Policy

**Files:**
- Modify: `tests/test_service.py`
- Modify: `src/aidn_hypervisor/service.py`
- Modify: `src/aidn_hypervisor/state.py`

- [ ] **Step 1: Write the failing service test for the requests dashboard payload**

```python
def test_service_requests_dashboard_reports_queue_recent_and_policy() -> None:
    service = _service(with_runtime=False, use_process_manager=True, reserve_runtime=False)
    queued = service.submit(
        TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "queued.wav"})
    )
    completed = service.submit(
        TaskRequest(task_type="llm_text.generate", payload={"prompt": "done"})
    )

    payload = service.operator_dashboard_requests()

    assert payload["summary"]["queued"] >= 1
    assert payload["summary"]["completed_recent"] >= 1
    assert payload["policy"] == {
        "allow_spillover": False,
        "dispatch_strategy": "local_first",
        "ready_endpoint_only": True,
    }
    assert any(item["task_id"] == queued.task_id for item in payload["queue"])
    assert any(item["task_id"] == completed.task_id for item in payload["recent"])
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `python -m pytest tests/test_service.py::test_service_requests_dashboard_reports_queue_recent_and_policy -q`

Expected: `FAIL` with missing `operator_dashboard_requests` or missing policy fields.

- [ ] **Step 3: Write the failing persistence test for requests policy**

```python
def test_service_snapshot_and_restore_preserves_requests_policy() -> None:
    service = _service()
    service.update_operator_requests_policy(
        allow_spillover=True,
        dispatch_strategy="balanced",
        ready_endpoint_only=False,
    )

    snapshot = service.snapshot_state()
    restored = _service()
    restored.restore_state(snapshot)

    assert restored.operator_requests_policy() == {
        "allow_spillover": True,
        "dispatch_strategy": "balanced",
        "ready_endpoint_only": False,
    }
```

- [ ] **Step 4: Run the focused persistence test to verify it fails**

Run: `python -m pytest tests/test_service.py::test_service_snapshot_and_restore_preserves_requests_policy -q`

Expected: `FAIL` with missing requests-policy snapshot support.

- [ ] **Step 5: Add the minimal service implementation**

```python
def operator_requests_policy(self) -> dict[str, bool | str]:
    return {
        "allow_spillover": self._operator_requests_policy["allow_spillover"],
        "dispatch_strategy": self._operator_requests_policy["dispatch_strategy"],
        "ready_endpoint_only": self._operator_requests_policy["ready_endpoint_only"],
    }

def update_operator_requests_policy(
    self,
    *,
    allow_spillover: bool,
    dispatch_strategy: str,
    ready_endpoint_only: bool,
) -> dict[str, bool | str]:
    if dispatch_strategy not in {"local_first", "balanced", "market_first"}:
        raise ValueError(f"Unsupported dispatch strategy: {dispatch_strategy}")
    self._operator_requests_policy = {
        "allow_spillover": bool(allow_spillover),
        "dispatch_strategy": dispatch_strategy,
        "ready_endpoint_only": bool(ready_endpoint_only),
    }
    self._persist_state()
    return self.operator_requests_policy()

def operator_dashboard_requests(self, *, market_candidates: list[dict] | None = None) -> dict:
    tasks = self.queue.snapshot()
    queue = [self._operator_dashboard_task_entry(task) for task in tasks if task.status in {"queued", "admitted", "starting"}]
    active = [self._operator_dashboard_task_entry(task) for task in tasks if task.status == "running"]
    recent = [self._operator_dashboard_task_entry(task) for task in tasks if task.status in {"completed", "failed", "cancelled"}][-12:]
    preview = self._operator_spillover_preview(market_candidates or [])
    return {
        "summary": {
            "queued": len(queue),
            "active": len(active),
            "completed_recent": len([item for item in recent if item["status"] == "completed"]),
            "failed_recent": len([item for item in recent if item["status"] == "failed"]),
            "admission_blocked": len(queue),
            "spillover_ready": len(preview),
        },
        "queue": queue,
        "active": active,
        "recent": list(reversed(recent)),
        "admission": self.admission_telemetry(),
        "policy": self.operator_requests_policy(),
        "market_spillover_preview": preview,
    }
```

- [ ] **Step 6: Persist requests policy in state snapshots**

```python
class HypervisorStateSnapshot(BaseModel):
    ...
    operator_requests_policy: dict[str, bool | str] = Field(
        default_factory=lambda: {
            "allow_spillover": False,
            "dispatch_strategy": "local_first",
            "ready_endpoint_only": True,
        }
    )
```

```python
"operator_requests_policy": dict(self._operator_requests_policy),
```

```python
self._operator_requests_policy = dict(snapshot.operator_requests_policy)
```

- [ ] **Step 7: Run the focused service tests to verify they pass**

Run: `python -m pytest tests/test_service.py -k "requests_dashboard_reports_queue_recent_and_policy or preserves_requests_policy" -q`

Expected: `PASS`

- [ ] **Step 8: Commit**

```bash
git add src/aidn_hypervisor/service.py src/aidn_hypervisor/state.py tests/test_service.py
git commit -m "feat: add requests dashboard read model"
```

### Task 2: Add Requests Dashboard Routes And Policy Write API

**Files:**
- Modify: `tests/test_api.py`
- Modify: `src/aidn_hypervisor/api.py`

- [ ] **Step 1: Write the failing API test for the requests dashboard route**

```python
def test_operator_dashboard_requests_endpoint_returns_grouped_payload() -> None:
    service = _service(with_runtime=False, use_process_manager=True, reserve_runtime=False)
    service.submit(TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "queued.wav"}))
    client = TestClient(build_app(service=service))

    response = client.get("/operators/dashboard/requests")

    assert response.status_code == 200
    assert "summary" in response.json()
    assert "queue" in response.json()
    assert "policy" in response.json()
    assert "market_spillover_preview" in response.json()
```

- [ ] **Step 2: Run the route test to verify it fails**

Run: `python -m pytest tests/test_api.py::test_operator_dashboard_requests_endpoint_returns_grouped_payload -q`

Expected: `FAIL` with missing route.

- [ ] **Step 3: Write the failing API test for policy updates**

```python
def test_operator_dashboard_requests_policy_endpoint_updates_service_state() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.post(
        "/operators/dashboard/requests/policy",
        json={
            "allow_spillover": True,
            "dispatch_strategy": "balanced",
            "ready_endpoint_only": False,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "allow_spillover": True,
        "dispatch_strategy": "balanced",
        "ready_endpoint_only": False,
    }
```

- [ ] **Step 4: Run the policy test to verify it fails**

Run: `python -m pytest tests/test_api.py::test_operator_dashboard_requests_policy_endpoint_updates_service_state -q`

Expected: `FAIL` with missing policy endpoint.

- [ ] **Step 5: Add the route and policy endpoint**

```python
@router.get("/operators/dashboard/requests")
async def operator_dashboard_requests() -> dict:
    market = build_market_payload(service=service, registry_service=registry_service)
    return service.operator_dashboard_requests(
        market_candidates=market["candidates"],
    )

@router.post("/operators/dashboard/requests/policy")
async def update_operator_dashboard_requests_policy(
    request: OperatorRequestsPolicyRequest,
) -> dict:
    try:
        return service.update_operator_requests_policy(**request.model_dump(mode="json"))
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
```

- [ ] **Step 6: Run the focused API tests to verify they pass**

Run: `python -m pytest tests/test_api.py -k "operator_dashboard_requests_endpoint_returns_grouped_payload or operator_dashboard_requests_policy_endpoint_updates_service_state" -q`

Expected: `PASS`

- [ ] **Step 7: Commit**

```bash
git add src/aidn_hypervisor/api.py tests/test_api.py
git commit -m "feat: add requests dashboard api"
```

### Task 3: Extend The Static Dashboard Shell With A Live Requests Workspace

**Files:**
- Modify: `tests/test_api.py`
- Modify: `src/aidn_hypervisor/static/operator_dashboard.html`

- [ ] **Step 1: Write the failing shell test for requests controls**

```python
def test_operator_dashboard_shell_route_exposes_requests_workspace_controls() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert 'data-screen="requests"' in response.text
    assert "/operators/dashboard/requests" in response.text
    assert 'data-requests-policy="strategy"' in response.text
    assert "Spillover Preview" in response.text
```

- [ ] **Step 2: Run the shell test to verify it fails**

Run: `python -m pytest tests/test_api.py::test_operator_dashboard_shell_route_exposes_requests_workspace_controls -q`

Expected: `FAIL` because the shell does not yet expose the requests mode.

- [ ] **Step 3: Add the requests mode to the dashboard endpoints and state**

```javascript
const endpoints = {
  home: "/operators/dashboard/home",
  fleet: "/operators/dashboard/fleet",
  market: "/operators/dashboard/market",
  requests: "/operators/dashboard/requests",
};

const state = {
  screen: "home",
  ...,
  selectedRequestTaskId: null,
  requestsTab: "queue",
  requestDetailCache: {},
  requestPolicyPending: false,
};
```

- [ ] **Step 4: Render the requests workspace, inspector, and policy panel**

```javascript
function renderRequestsWorkspace() {
  const payload = state.payloads.requests || {};
  return `
    <div class="workspace-header">
      <div>
        <div class="panel-heading">Workload Triage</div>
        <h1 class="workspace-title">Requests</h1>
      </div>
      <div class="toolbar">
        <button type="button" data-requests-policy="spillover">Allow Spillover</button>
        <button type="button" data-requests-policy="ready">Ready Endpoints Only</button>
        <select data-requests-policy="strategy">
          <option value="local_first">Local First</option>
          <option value="balanced">Balanced</option>
          <option value="market_first">Market First</option>
        </select>
      </div>
    </div>
  `;
}
```

- [ ] **Step 5: Add lazy task inspection, cancel action, and policy writes**

```javascript
async function loadTaskDetail(taskId) {
  if (state.requestDetailCache[taskId]) return state.requestDetailCache[taskId];
  const response = await fetch(`/tasks/${taskId}`, { cache: "no-store" });
  const payload = await response.json();
  state.requestDetailCache[taskId] = payload;
  return payload;
}

async function cancelSelectedRequestTask(taskId) {
  await fetch(`/tasks/${taskId}/cancel`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
}
```

- [ ] **Step 6: Run the focused shell tests to verify they pass**

Run: `python -m pytest tests/test_api.py -k "wallet_drawer_controls or requests_workspace_controls or operator_dashboard_shell_route" -q`

Expected: `PASS`

- [ ] **Step 7: Commit**

```bash
git add src/aidn_hypervisor/static/operator_dashboard.html tests/test_api.py
git commit -m "feat: add requests workspace to operator dashboard"
```

### Task 4: Verify The Full Requests Slice And Sync Project Docs

**Files:**
- Modify: `ROADMAP.md`
- Modify: `design-qa.md`
- Modify: `tests/test_service.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Run the focused regression suites**

Run: `python -m pytest tests/test_service.py -k "requests or dashboard" -q`

Expected: `PASS`

Run: `python -m pytest tests/test_api.py -k "requests or operator_dashboard" -q`

Expected: `PASS`

- [ ] **Step 2: Run the broader wallet-plus-dashboard regression**

Run: `python -m pytest tests/test_wallet.py tests/test_service.py tests/test_api.py -q`

Expected: `PASS`

- [ ] **Step 3: Verify the requests workspace in the in-app browser**

Run: `uvicorn aidn_hypervisor.main:app --reload --port 8766`

Then verify:
- `Requests` opens from the left rail;
- `Queue`, `Active`, `Recent`, and `Admission` switch correctly;
- selecting a task updates the inspector;
- policy changes update the spillover preview;
- canceling an eligible task updates the visible state without console errors.

- [ ] **Step 4: Sync roadmap and QA notes**

```md
- the operator dashboard now includes a live `Requests` workspace for queue triage, task inspection, cancellation, and future-facing spillover policy management;
```

```md
- browser verification confirmed that the `Requests` workspace opens correctly, updates the inspector on task selection, and applies spillover policy changes without console errors.
```

- [ ] **Step 5: Commit**

```bash
git add ROADMAP.md design-qa.md
git commit -m "docs: sync requests workspace delivery"
```
