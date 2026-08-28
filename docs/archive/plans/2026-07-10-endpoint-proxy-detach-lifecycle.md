# Endpoint Proxy Detach Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a first-class operator flow for detaching a proxy target so an Endpoint can revert from `proxy` execution back to `local` execution without manual manifest surgery.

**Architecture:** Extend the existing endpoint lifecycle symmetrically: `attach_proxy_target()` already rotates configuration into `proxy`, so this slice adds a matching detach path in the endpoint domain service, exposes it through the versioned endpoint API, and surfaces it in the operator shell where proxy routes are already attached. The implementation should preserve existing publish/validation/proxy guidance and only add the missing reverse transition.

**Tech Stack:** Python, FastAPI, Pydantic models, existing endpoint store/service layer, static operator dashboard HTML/JS, `pytest`

---

## File Structure

- Modify: `src/aidn_hypervisor/endpoints/service.py`
  - Add the domain operation that reverts an endpoint from `proxy` back to `local` and rotates configuration snapshots.
- Modify: `src/aidn_hypervisor/endpoints/api.py`
  - Add the HTTP action for proxy detach and keep validation supersede behavior aligned with the existing attach/update routes.
- Modify: `src/aidn_hypervisor/static/operator_dashboard.html`
  - Add the operator action and shell copy/state transitions for detaching a proxy route from the Endpoints workspace.
- Modify: `tests/endpoints/test_proxy_endpoint_service.py`
  - Lock the domain detach behavior with a focused unit test.
- Modify: `tests/test_api.py`
  - Cover the new endpoint API route and the shell markup/action affordance.

## Task 1: Add The Endpoint-Service Detach Operation

**Files:**
- Modify: `C:\Users\admin\Documents\New project 3\AiDN\.worktrees\endpoint-proxy-detach-lifecycle\tests\endpoints\test_proxy_endpoint_service.py`
- Modify: `C:\Users\admin\Documents\New project 3\AiDN\.worktrees\endpoint-proxy-detach-lifecycle\src\aidn_hypervisor\endpoints\service.py`

- [ ] **Step 1: Write the failing unit test for detaching a proxy target**

```python
def test_detach_proxy_target_reverts_endpoint_to_local_strategy() -> None:
    service = EndpointService(EndpointStore())
    created = service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="bundle-a",
            bundle_hash="bundle-hash-a",
            display_name="Operator STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
        )
    )
    proxied = service.attach_proxy_target(created.endpoint.endpoint_id, _remote_reference())

    detached = service.detach_proxy_target(created.endpoint.endpoint_id)

    assert detached.endpoint.execution_strategy == "local"
    assert detached.endpoint.proxy_target is None
    assert detached.endpoint.configuration_hash != proxied.endpoint.configuration_hash
    assert len(service.list_configuration_snapshots(created.endpoint.endpoint_id)) == 3
    assert detached.snapshot is not None
    assert detached.snapshot.proxy_target is None
    assert detached.snapshot.execution_config["execution_strategy"] == "local"
```

- [ ] **Step 2: Run the unit test and verify RED**

Run:

```bash
python -m pytest tests/endpoints/test_proxy_endpoint_service.py -k detach_proxy_target -q
```

Expected:
- `FAIL`
- missing `detach_proxy_target` behavior

- [ ] **Step 3: Implement the minimal service operation**

Add a focused method in `EndpointService` that:
- loads the current manifest;
- builds a new execution config with `execution_strategy="local"` and `proxy_target=None`;
- rotates `configuration_hash`;
- saves a new `EndpointConfigurationSnapshot`;
- persists the manifest with `execution_strategy="local"` and `proxy_target=None`.

- [ ] **Step 4: Run the unit test and verify GREEN**

Run:

```bash
python -m pytest tests/endpoints/test_proxy_endpoint_service.py -k detach_proxy_target -q
```

Expected:
- `PASS`

- [ ] **Step 5: Commit the domain detach operation**

```bash
git add tests/endpoints/test_proxy_endpoint_service.py src/aidn_hypervisor/endpoints/service.py
git commit -m "feat: add endpoint proxy detach operation"
```

## Task 2: Expose Proxy Detach Through The Endpoint API

**Files:**
- Modify: `C:\Users\admin\Documents\New project 3\AiDN\.worktrees\endpoint-proxy-detach-lifecycle\tests\test_api.py`
- Modify: `C:\Users\admin\Documents\New project 3\AiDN\.worktrees\endpoint-proxy-detach-lifecycle\src\aidn_hypervisor\endpoints\api.py`

- [ ] **Step 1: Write the failing API test for the detach route**

Mirror the existing attach test with a detach flow:

```python
def test_detach_proxy_target_route_reverts_endpoint_to_local_strategy() -> None:
    service = _service(whisper_endpoint="http://127.0.0.1:9000")
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=service.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Shared STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
        )
    )
    remote_endpoint_service = RemoteEndpointService(RemoteEndpointStore())
    attached = remote_endpoint_service.attach_remote_endpoint(
        source_node_id="node-external",
        source_endpoint_id="ep-remote",
        source_owner_wallet="wallet-remote",
        source_publication_id="pub-remote",
        source_configuration_hash="cfg-remote",
        source_visibility="public",
        source_model_class="llm_text",
        source_status="published",
        source_base_url="https://remote.example",
        operator_id="operator-b",
        pricing={"unit": "q_per_1kk_tokens", "input": 9, "output": 15, "fixed_request": 1},
        rating={"score": 0.97, "tier": "A", "updated_at": "2026-06-20T11:55:00Z"},
        alias="Primary Remote",
    )
    endpoint_service.attach_proxy_target(created.endpoint.endpoint_id, attached)
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            remote_endpoint_service=remote_endpoint_service,
        )
    )

    response = client.delete(f"/api/v1/endpoints/{created.endpoint.endpoint_id}/proxy-target")

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["endpoint"]["execution_strategy"] == "local"
    assert body["endpoint"]["proxy_target"] is None
    assert body["snapshot"]["proxy_target"] is None
```

- [ ] **Step 2: Run the API test and verify RED**

Run:

```bash
python -m pytest tests/test_api.py -k detach_proxy_target_route -q
```

Expected:
- `FAIL`
- route missing

- [ ] **Step 3: Implement the route**

Add a `DELETE /api/v1/endpoints/{endpoint_id}/proxy-target` route that:
- loads the current endpoint;
- calls `service.detach_proxy_target(endpoint_id)`;
- mirrors the existing validation supersede behavior used by update/attach routes when configuration hash changes;
- returns `{ endpoint, snapshot }`.

- [ ] **Step 4: Run the API test and verify GREEN**

Run:

```bash
python -m pytest tests/test_api.py -k detach_proxy_target_route -q
```

Expected:
- `PASS`

- [ ] **Step 5: Commit the API detach route**

```bash
git add tests/test_api.py src/aidn_hypervisor/endpoints/api.py
git commit -m "feat: expose endpoint proxy detach route"
```

## Task 3: Surface Detach In The Operator Shell

**Files:**
- Modify: `C:\Users\admin\Documents\New project 3\AiDN\.worktrees\endpoint-proxy-detach-lifecycle\tests\test_api.py`
- Modify: `C:\Users\admin\Documents\New project 3\AiDN\.worktrees\endpoint-proxy-detach-lifecycle\src\aidn_hypervisor\static\operator_dashboard.html`

- [ ] **Step 1: Write failing shell tests for the detach action**

Add assertions alongside the current attach shell tests:

```python
def test_operator_dashboard_shell_exposes_detach_proxy_route_action() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert 'data-endpoint-action="detach-proxy-target"' in response.text
    assert 'case "detach-proxy-target":' in response.text
    assert "Detach Proxy Route" in response.text
```

- [ ] **Step 2: Run the shell test and verify RED**

Run:

```bash
python -m pytest tests/test_api.py -k detach_proxy_route_action -q
```

Expected:
- `FAIL`
- detach action missing from shell markup/handlers

- [ ] **Step 3: Add the shell action**

Update `operator_dashboard.html` so that:
- proxied endpoints expose a `Detach Proxy Route` button in the Endpoints workspace;
- action routing recognizes `detach-proxy-target`;
- the shell calls `DELETE /api/v1/endpoints/{endpoint_id}/proxy-target`;
- after success it refreshes endpoints payloads and clears any stale guided proxy flow for that endpoint.

- [ ] **Step 4: Run the shell test and verify GREEN**

Run:

```bash
python -m pytest tests/test_api.py -k detach_proxy_route_action -q
```

Expected:
- `PASS`

- [ ] **Step 5: Commit the shell detach action**

```bash
git add tests/test_api.py src/aidn_hypervisor/static/operator_dashboard.html
git commit -m "feat: add dashboard proxy detach action"
```

## Task 4: Verify The Slice End-To-End

**Files:**
- Modify: `C:\Users\admin\Documents\New project 3\AiDN\.worktrees\endpoint-proxy-detach-lifecycle\tests\test_api.py`
- Modify: `C:\Users\admin\Documents\New project 3\AiDN\.worktrees\endpoint-proxy-detach-lifecycle\tests\endpoints\test_proxy_endpoint_service.py`

- [ ] **Step 1: Run the focused proxy lifecycle slice**

Run:

```bash
python -m pytest tests/endpoints/test_proxy_endpoint_service.py tests/test_api.py -k "proxy and detach" -q
```

Expected:
- `PASS`

- [ ] **Step 2: Run the full suite**

Run:

```bash
python -m pytest -q
```

Expected:
- `PASS`

- [ ] **Step 3: Commit any final adjustments**

```bash
git add tests/endpoints/test_proxy_endpoint_service.py tests/test_api.py
git commit -m "test: cover proxy detach lifecycle"
```

## Spec Coverage Check

- reverse proxy lifecycle action in the endpoint domain: Task 1
- operator-facing API for detaching proxy targets: Task 2
- shell-level operator control for reverting to local execution: Task 3
- focused and full regression for the lifecycle slice: Task 4

## Placeholder Scan

Checked for:
- `TBD`
- `TODO`
- vague “add tests” steps without exact targets
- missing commands or expected outcomes

## Type Consistency

Canonical names used throughout the plan:
- `detach_proxy_target(endpoint_id)`
- `DELETE /api/v1/endpoints/{endpoint_id}/proxy-target`
- `execution_strategy == "local"`
- `proxy_target is None`
