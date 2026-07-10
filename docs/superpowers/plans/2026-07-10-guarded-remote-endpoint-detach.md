# Guarded Remote Endpoint Detach Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a first-class operator flow for detaching a preferred remote endpoint, but block the detach when any local proxy Endpoint still depends on that remote route.

**Architecture:** Extend the existing remote-endpoint catalogue symmetrically: `attach_remote_endpoint()` already persists a preferred route, so this slice adds a matching detach path in the remote-endpoint domain service, exposes it through the operator API, and surfaces it in the dashboard. Dependency enforcement stays explicit and deterministic by checking local Endpoint manifests for `proxy_target.remote_endpoint_id` before removal and returning a conflict instead of cascading hidden edits.

**Tech Stack:** Python, FastAPI, Pydantic models, existing remote endpoint and endpoint stores/services, static operator dashboard HTML/JS, `pytest`

---

## File Structure

- Modify: `src/aidn_hypervisor/remote_endpoints/service.py`
  - Add the domain detach operation and a dedicated dependency error contract.
- Modify: `tests/remote_endpoints/test_remote_endpoint_service.py`
  - Lock the detach behavior and dependency guard with focused unit tests.
- Modify: `src/aidn_hypervisor/api.py`
  - Add the operator HTTP route for detaching remote endpoints and map dependency errors to `409`.
- Modify: `tests/test_api.py`
  - Cover API detach success, API conflict, and shell affordances.
- Modify: `src/aidn_hypervisor/static/operator_dashboard.html`
  - Add the operator action, API call, and conflict messaging in the Remote Endpoints workspace.

## Task 1: Add The Remote Endpoint Detach Domain Operation

**Files:**
- Modify: `C:\Users\admin\Documents\New project 3\AiDN\.worktrees\endpoint-proxy-detach-lifecycle\tests\remote_endpoints\test_remote_endpoint_service.py`
- Modify: `C:\Users\admin\Documents\New project 3\AiDN\.worktrees\endpoint-proxy-detach-lifecycle\src\aidn_hypervisor\remote_endpoints\service.py`

- [ ] **Step 1: Write the failing unit test for a successful detach**

```python
from aidn_hypervisor.remote_endpoints.service import RemoteEndpointService
from aidn_hypervisor.remote_endpoints.store import RemoteEndpointStore


def test_detach_remote_endpoint_removes_catalog_entry() -> None:
    service = RemoteEndpointService(RemoteEndpointStore())
    attached = service.attach_remote_endpoint(
        source_node_id="node-remote",
        source_endpoint_id="ep-remote",
        source_owner_wallet="wallet-remote",
        source_publication_id="pub-remote",
        source_configuration_hash="cfg-remote",
        source_visibility="public",
        source_model_class="llm_text",
        source_status="published",
        source_base_url="https://remote.example",
        operator_id="operator-remote",
        pricing={"unit": "q_per_1kk_tokens", "input": 8, "output": 12},
        rating={"score": 0.96, "tier": "A", "updated_at": "2026-06-30T00:00:00+00:00"},
        alias="Primary Remote",
    )

    detached = service.detach_remote_endpoint(attached.remote_endpoint_id)

    assert detached.remote_endpoint_id == attached.remote_endpoint_id
    assert service.list_remote_endpoints() == []
```

- [ ] **Step 2: Write the failing dependency-guard test**

```python
import pytest

from aidn_hypervisor.endpoints.models import CreateEndpointCommand
from aidn_hypervisor.endpoints.service import EndpointService
from aidn_hypervisor.endpoints.store import EndpointStore
from aidn_hypervisor.remote_endpoints.service import (
    RemoteEndpointDependencyError,
    RemoteEndpointService,
)
from aidn_hypervisor.remote_endpoints.store import RemoteEndpointStore


def test_detach_remote_endpoint_rejects_active_proxy_dependencies() -> None:
    remote_service = RemoteEndpointService(RemoteEndpointStore())
    endpoint_service = EndpointService(EndpointStore())
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="bundle-a",
            bundle_hash="bundle-hash-a",
            display_name="Proxy Worker",
            model_class="llm_text",
            capabilities=["chat"],
        )
    )
    attached = remote_service.attach_remote_endpoint(
        source_node_id="node-remote",
        source_endpoint_id="ep-remote",
        source_owner_wallet="wallet-remote",
        source_publication_id="pub-remote",
        source_configuration_hash="cfg-remote",
        source_visibility="public",
        source_model_class="llm_text",
        source_status="published",
        source_base_url="https://remote.example",
        operator_id="operator-remote",
        pricing={"unit": "q_per_1kk_tokens", "input": 8, "output": 12},
        rating={"score": 0.96, "tier": "A", "updated_at": "2026-06-30T00:00:00+00:00"},
    )
    endpoint_service.attach_proxy_target(created.endpoint.endpoint_id, attached)

    with pytest.raises(RemoteEndpointDependencyError) as error:
        remote_service.detach_remote_endpoint(
            attached.remote_endpoint_id,
            endpoint_service=endpoint_service,
        )

    assert error.value.remote_endpoint_id == attached.remote_endpoint_id
    assert error.value.dependent_endpoint_ids == [created.endpoint.endpoint_id]
    assert remote_service.list_remote_endpoints()[0].remote_endpoint_id == attached.remote_endpoint_id
```

- [ ] **Step 3: Run the unit tests and verify RED**

Run:

```bash
python -m pytest tests/remote_endpoints/test_remote_endpoint_service.py -k "detach_remote_endpoint" -q
```

Expected:
- `FAIL`
- missing `detach_remote_endpoint` and dependency error behavior

- [ ] **Step 4: Implement the minimal service detach path**

Add a focused domain contract in `remote_endpoints/service.py`:

```python
class RemoteEndpointDependencyError(RuntimeError):
    def __init__(
        self,
        remote_endpoint_id: str,
        dependent_endpoint_ids: list[str],
    ) -> None:
        super().__init__(
            f"remote endpoint {remote_endpoint_id} is still used by local endpoints"
        )
        self.remote_endpoint_id = remote_endpoint_id
        self.dependent_endpoint_ids = dependent_endpoint_ids
```

Then add a service method that:
- loads the current remote endpoint via `get_remote_endpoint()`;
- scans `endpoint_service.store.list_manifests()` when `endpoint_service` is provided;
- collects dependent local `endpoint_id` values whose `proxy_target.remote_endpoint_id` matches;
- raises `RemoteEndpointDependencyError` when the list is non-empty;
- otherwise removes the record from the store and returns the detached reference.

- [ ] **Step 5: Run the unit tests and verify GREEN**

Run:

```bash
python -m pytest tests/remote_endpoints/test_remote_endpoint_service.py -k "detach_remote_endpoint" -q
```

Expected:
- `PASS`

- [ ] **Step 6: Commit the domain detach operation**

```bash
git add tests/remote_endpoints/test_remote_endpoint_service.py src/aidn_hypervisor/remote_endpoints/service.py
git commit -m "feat: add guarded remote endpoint detach"
```

## Task 2: Expose Guarded Detach Through The Operator API

**Files:**
- Modify: `C:\Users\admin\Documents\New project 3\AiDN\.worktrees\endpoint-proxy-detach-lifecycle\tests\test_api.py`
- Modify: `C:\Users\admin\Documents\New project 3\AiDN\.worktrees\endpoint-proxy-detach-lifecycle\src\aidn_hypervisor\api.py`

- [ ] **Step 1: Write the failing API success test**

```python
def test_detach_remote_endpoint_route_removes_preferred_catalogue_entry() -> None:
    hypervisor = _service(whisper_endpoint="http://127.0.0.1:9000")
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
    client = TestClient(
        build_app(
            service=hypervisor,
            remote_endpoint_service=remote_endpoint_service,
        )
    )

    response = client.delete(
        f"/operators/remote-endpoints/{attached.remote_endpoint_id}"
    )

    assert response.status_code == 200
    body = response.json()["data"]["remote_endpoint"]
    assert body["remote_endpoint_id"] == attached.remote_endpoint_id
    assert remote_endpoint_service.list_remote_endpoints() == []
```

- [ ] **Step 2: Write the failing API conflict test**

```python
def test_detach_remote_endpoint_route_rejects_proxy_dependencies() -> None:
    hypervisor = _service(whisper_endpoint="http://127.0.0.1:9000")
    endpoint_service = EndpointService(EndpointStore())
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="bundle-a",
            bundle_hash="bundle-hash-a",
            display_name="Proxy Worker",
            model_class="llm_text",
            capabilities=["chat"],
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
    )
    endpoint_service.attach_proxy_target(created.endpoint.endpoint_id, attached)
    client = TestClient(
        build_app(
            service=hypervisor,
            endpoint_service=endpoint_service,
            remote_endpoint_service=remote_endpoint_service,
        )
    )

    response = client.delete(
        f"/operators/remote-endpoints/{attached.remote_endpoint_id}"
    )

    assert response.status_code == 409
    body = response.json()
    assert body["error"]["code"] == "remote_endpoint_in_use"
    assert body["error"]["details"]["dependent_endpoint_ids"] == [created.endpoint.endpoint_id]
```

- [ ] **Step 3: Run the API tests and verify RED**

Run:

```bash
python -m pytest tests/test_api.py -k "detach_remote_endpoint_route" -q
```

Expected:
- `FAIL`
- route missing

- [ ] **Step 4: Implement the route**

Add `DELETE /operators/remote-endpoints/{remote_endpoint_id}` in `src/aidn_hypervisor/api.py` that:
- returns `409 registry_unavailable` style error if `remote_endpoint_service` is missing;
- calls `remote_endpoint_service.detach_remote_endpoint(remote_endpoint_id, endpoint_service=endpoint_service)`;
- maps `KeyError` to `404 remote_endpoint_not_found`;
- maps `RemoteEndpointDependencyError` to `409 remote_endpoint_in_use` with `dependent_endpoint_ids`;
- returns the detached remote endpoint in the normal `_ok(...)` envelope.

- [ ] **Step 5: Run the API tests and verify GREEN**

Run:

```bash
python -m pytest tests/test_api.py -k "detach_remote_endpoint_route" -q
```

Expected:
- `PASS`

- [ ] **Step 6: Commit the API detach route**

```bash
git add tests/test_api.py src/aidn_hypervisor/api.py
git commit -m "feat: expose guarded remote endpoint detach route"
```

## Task 3: Surface Detach In The Remote Endpoints Workspace

**Files:**
- Modify: `C:\Users\admin\Documents\New project 3\AiDN\.worktrees\endpoint-proxy-detach-lifecycle\tests\test_api.py`
- Modify: `C:\Users\admin\Documents\New project 3\AiDN\.worktrees\endpoint-proxy-detach-lifecycle\src\aidn_hypervisor\static\operator_dashboard.html`

- [ ] **Step 1: Write the failing shell test**

```python
def test_operator_dashboard_shell_route_exposes_detach_remote_endpoint_action() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert 'data-remote-action="detach"' in response.text
    assert "Detach Remote Endpoint" in response.text
    assert '"/operators/remote-endpoints/' in response.text
```

- [ ] **Step 2: Run the shell test and verify RED**

Run:

```bash
python -m pytest tests/test_api.py -k "detach_remote_endpoint_action" -q
```

Expected:
- `FAIL`
- detach action missing from shell markup or handlers

- [ ] **Step 3: Add the shell action**

Update `operator_dashboard.html` so that:
- the selected attached remote endpoint shows a `Detach Remote Endpoint` action;
- the handler calls `DELETE /operators/remote-endpoints/{remote_endpoint_id}`;
- success clears `selectedRemoteEndpointKey` when the removed entry was selected and refreshes the remote payload;
- `409 remote_endpoint_in_use` is surfaced as an operator-friendly message naming the dependent endpoint ids;
- attach and stage-proxy actions keep their current behavior.

- [ ] **Step 4: Run the shell test and verify GREEN**

Run:

```bash
python -m pytest tests/test_api.py -k "detach_remote_endpoint_action" -q
```

Expected:
- `PASS`

- [ ] **Step 5: Commit the shell detach action**

```bash
git add tests/test_api.py src/aidn_hypervisor/static/operator_dashboard.html
git commit -m "feat: add dashboard remote endpoint detach action"
```

## Task 4: Verify The Slice And Realign The Roadmap

**Files:**
- Modify: `C:\Users\admin\Documents\New project 3\AiDN\.worktrees\endpoint-proxy-detach-lifecycle\ROADMAP.md`
- Modify: `C:\Users\admin\Documents\New project 3\AiDN\.worktrees\endpoint-proxy-detach-lifecycle\tests\remote_endpoints\test_remote_endpoint_service.py`
- Modify: `C:\Users\admin\Documents\New project 3\AiDN\.worktrees\endpoint-proxy-detach-lifecycle\tests\test_api.py`

- [ ] **Step 1: Update the roadmap after tests are green**

Add one factual bullet under the current stage summary describing that preferred remote routes can now be detached explicitly, with proxy dependency protection. Keep the immediate priority wording unchanged unless implementation reveals a stronger mismatch.

- [ ] **Step 2: Run the focused slice**

Run:

```bash
python -m pytest tests/remote_endpoints/test_remote_endpoint_service.py tests/test_api.py -k "detach_remote_endpoint" -q
```

Expected:
- `PASS`

- [ ] **Step 3: Run the full suite**

Run:

```bash
python -m pytest -q
```

Expected:
- `PASS`

- [ ] **Step 4: Commit any final roadmap or test adjustments**

```bash
git add ROADMAP.md tests/remote_endpoints/test_remote_endpoint_service.py tests/test_api.py
git commit -m "docs: record guarded remote endpoint detach slice"
```

## Spec Coverage Check

- explicit remote endpoint detach flow: Task 1
- dependency guard against live proxy usage: Task 1 and Task 2
- operator API error contract with dependent endpoints surfaced: Task 2
- dashboard control and operator-friendly conflict messaging: Task 3
- roadmap realignment and regression coverage: Task 4

## Placeholder Scan

Checked for:
- `TBD`
- `TODO`
- vague “handle edge cases” wording
- steps without exact files, commands, or expected results

## Type Consistency

Canonical names used throughout the plan:
- `detach_remote_endpoint(remote_endpoint_id, endpoint_service=None)`
- `RemoteEndpointDependencyError`
- `DELETE /operators/remote-endpoints/{remote_endpoint_id}`
- `remote_endpoint_in_use`
- `dependent_endpoint_ids`
