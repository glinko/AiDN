# Proxy Session Propagation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add lazy upstream Session brokering for paid proxy Endpoints so one local client-facing Session can transparently open, reuse, and close a remote paid Session.

**Architecture:** Extend the current session and proxy execution layers rather than creating a second public session subsystem. The local Session remains the only public contract; a persisted `ProxySessionBinding` stores upstream broker state and is consumed only by proxy execution, close reconciliation, and operator-facing detail payloads.

**Tech Stack:** Python, FastAPI, Pydantic, existing `sessions/` package, existing proxy execution flow in `HypervisorService`, pytest

---

## File Structure

### Create

- `docs/superpowers/plans/2026-07-02-proxy-session-propagation.md`
  - this implementation plan

### Modify

- `src/aidn_hypervisor/remote_endpoints/models.py`
  - add attached remote session policy snapshot fields needed for broker decisions
- `src/aidn_hypervisor/sessions/models.py`
  - add `ProxySessionBinding`
- `src/aidn_hypervisor/sessions/store.py`
  - persist and fetch `ProxySessionBinding` by local session id
- `src/aidn_hypervisor/sessions/service.py`
  - expose binding CRUD helpers used by runtime brokering
- `src/aidn_hypervisor/state.py`
  - add snapshot model for proxy session bindings
- `src/aidn_hypervisor/service.py`
  - lazy-open upstream session on first proxy request, reuse binding, best-effort remote close, expose binding status
- `src/aidn_hypervisor/api.py`
  - include `proxy_session` blocks in operator-facing task/session payloads
- `tests/sessions/test_models.py`
  - model validation for `ProxySessionBinding`
- `tests/sessions/test_service.py`
  - binding store/service behavior
- `tests/remote_endpoints/test_remote_endpoint_service.py`
  - remote endpoint session policy persistence
- `tests/test_service.py`
  - proxy runtime brokering tests
- `tests/test_api.py`
  - operator payload tests for `proxy_session`
- `tests/test_persistence.py`
  - snapshot/restore of proxy session bindings
- `ROADMAP.md`
  - mark remote/proxy-aware paid session propagation complete when green

---

### Task 1: Remote Endpoint Session Policy Snapshot

**Files:**
- Modify: `src/aidn_hypervisor/remote_endpoints/models.py`
- Test: `tests/remote_endpoints/test_remote_endpoint_service.py`

- [ ] **Step 1: Write the failing test**

```python
def test_attach_remote_endpoint_persists_session_policy_snapshot() -> None:
    attached = service.attach_remote_endpoint(
        source_node_id="node-remote",
        source_endpoint_id="ep-remote",
        source_owner_wallet="wallet-remote",
        source_publication_id="pub-remote",
        source_configuration_hash="cfg-remote",
        source_visibility="public",
        source_model_class="llm_text",
        source_status="published",
        source_base_url="http://remote-hv",
        operator_id="operator-remote",
        pricing={"unit": "q_per_1kk_tokens", "input": 8, "output": 12},
        rating={"score": 0.96, "tier": "A", "updated_at": "2026-07-02T00:00:00+00:00"},
        session_policy={
            "minimum_deposit": 10.0,
            "recommended_deposit": 25.0,
            "max_concurrent_sessions": 1,
        },
    )

    assert attached.session_policy["minimum_deposit"] == 10.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest --import-mode=importlib tests\remote_endpoints\test_remote_endpoint_service.py -k session_policy -q`
Expected: FAIL with unexpected keyword `session_policy` or missing field assertion.

- [ ] **Step 3: Write minimal implementation**

```python
class RemoteEndpointReference(BaseModel):
    ...
    session_policy: dict = Field(default_factory=dict)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest --import-mode=importlib tests\remote_endpoints\test_remote_endpoint_service.py -k session_policy -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aidn_hypervisor/remote_endpoints/models.py tests/remote_endpoints/test_remote_endpoint_service.py
git commit -m "feat: persist remote endpoint session policy snapshot"
```

### Task 2: Proxy Session Binding Domain And Persistence

**Files:**
- Modify: `src/aidn_hypervisor/sessions/models.py`
- Modify: `src/aidn_hypervisor/sessions/store.py`
- Modify: `src/aidn_hypervisor/sessions/service.py`
- Modify: `src/aidn_hypervisor/state.py`
- Test: `tests/sessions/test_models.py`
- Test: `tests/sessions/test_service.py`
- Test: `tests/test_persistence.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_proxy_session_binding_requires_local_and_remote_ids() -> None:
    binding = ProxySessionBinding(
        local_session_id="sess-local",
        remote_endpoint_id="ep-remote",
        remote_session_id="sess-remote",
        remote_node_id="node-remote",
        source_base_url="http://remote-hv",
        status="active",
        opened_at="2026-07-02T00:00:00+00:00",
        close_status="not_requested",
    )

    assert binding.remote_session_id == "sess-remote"


def test_session_store_round_trips_proxy_session_binding() -> None:
    store.save_proxy_session_binding(binding)
    assert store.get_proxy_session_binding("sess-local").remote_session_id == "sess-remote"


def test_snapshot_restores_proxy_session_bindings(tmp_path: Path) -> None:
    snapshot = service.snapshot_state()
    restored.restore_state(snapshot)
    assert restored.session_service.get_proxy_session_binding("sess-local").status == "active"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest --import-mode=importlib tests\sessions\test_models.py tests\sessions\test_service.py tests\test_persistence.py -k proxy_session -q`
Expected: FAIL with missing `ProxySessionBinding`, missing store/service methods, or missing snapshot fields.

- [ ] **Step 3: Write minimal implementation**

```python
class ProxySessionBinding(BaseModel):
    local_session_id: str
    remote_endpoint_id: str
    remote_session_id: str
    remote_node_id: str
    source_base_url: str
    status: Literal["pending_open", "active", "degraded", "close_pending", "closed"]
    opened_at: str
    last_error: str | None = None
    close_status: Literal["not_requested", "closed", "pending_reconcile"] = "not_requested"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest --import-mode=importlib tests\sessions\test_models.py tests\sessions\test_service.py tests\test_persistence.py -k proxy_session -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aidn_hypervisor/sessions/models.py src/aidn_hypervisor/sessions/store.py src/aidn_hypervisor/sessions/service.py src/aidn_hypervisor/state.py tests/sessions/test_models.py tests/sessions/test_service.py tests/test_persistence.py
git commit -m "feat: persist proxy session bindings"
```

### Task 3: Lazy Upstream Session Broker In Proxy Runtime

**Files:**
- Modify: `src/aidn_hypervisor/service.py`
- Test: `tests/test_service.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_proxy_paid_session_opens_upstream_session_lazily_on_first_request() -> None:
    result = service.submit(
        TaskRequest(
            task_type="llm_text.generate",
            payload={"prompt": "hello"},
            constraints={"endpoint_id": local_endpoint_id, "session_id": local_session_id},
        )
    )

    binding = session_service.get_proxy_session_binding(local_session_id)
    assert binding.remote_session_id == "remote-session-1"
    assert transport.calls[0] == ("POST", "http://remote-hv/api/v1/endpoints/ep-remote/sessions")


def test_proxy_paid_session_reuses_same_upstream_session_on_second_request() -> None:
    service.submit(first_request)
    service.submit(second_request)
    assert sum(1 for call in transport.calls if call[1].endswith("/sessions")) == 1


def test_closing_local_proxy_session_attempts_remote_close() -> None:
    session_service.close_session(local_session_id)
    assert ("POST", "http://remote-hv/api/v1/sessions/remote-session-1/close") in transport.calls


def test_upstream_session_open_failure_keeps_local_session_active() -> None:
    with pytest.raises(RuntimeError):
        service.submit(proxy_request)

    assert session_service.get_session(local_session_id).session.status == "active"
    assert session_service.get_proxy_session_binding(local_session_id).status == "degraded"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest --import-mode=importlib tests\test_service.py -k "proxy and session" -q`
Expected: FAIL with missing binding orchestration, missing remote session open/close calls, or absent proxy session status updates.

- [ ] **Step 3: Write minimal implementation**

```python
def _ensure_proxy_session_binding(self, endpoint_manifest, local_session_id: str) -> ProxySessionBinding:
    existing = self.session_service.try_get_proxy_session_binding(local_session_id)
    if existing is not None and existing.status == "active":
        return existing
    remote_session = self._open_remote_proxy_session(endpoint_manifest, local_session_id)
    return self.session_service.save_proxy_session_binding(
        ProxySessionBinding(
            local_session_id=local_session_id,
            remote_endpoint_id=endpoint_manifest.proxy_target.source_endpoint_id,
            remote_session_id=remote_session["session"]["session_id"],
            remote_node_id=endpoint_manifest.proxy_target.source_node_id,
            source_base_url=endpoint_manifest.proxy_target.source_base_url,
            status="active",
            opened_at=remote_session["session"]["opened_at"],
        )
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest --import-mode=importlib tests\test_service.py -k "proxy and session" -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aidn_hypervisor/service.py tests/test_service.py
git commit -m "feat: broker upstream sessions for proxy endpoints"
```

### Task 4: Operator-Facing Proxy Session Payloads

**Files:**
- Modify: `src/aidn_hypervisor/api.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_operator_session_payload_exposes_proxy_session_binding() -> None:
    response = client.get("/operators/dashboard/sessions")
    item = response.json()["data"]["items"][0]
    assert item["proxy_session"]["remote_session_id"] == "remote-session-1"


def test_get_task_detail_exposes_proxy_session_block() -> None:
    detail = client.get(f"/tasks/{task_id}")
    assert detail.json()["proxy_session"]["status"] == "active"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest --import-mode=importlib tests\test_api.py -k proxy_session -q`
Expected: FAIL with missing `proxy_session` block.

- [ ] **Step 3: Write minimal implementation**

```python
proxy_binding = session_service.try_get_proxy_session_binding(session.session_id)
payload["proxy_session"] = (
    proxy_binding.model_dump(mode="json") if proxy_binding is not None else None
)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest --import-mode=importlib tests\test_api.py -k proxy_session -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aidn_hypervisor/api.py tests/test_api.py
git commit -m "feat: expose proxy session state to operators"
```

### Task 5: Regression Slice And Roadmap Update

**Files:**
- Modify: `ROADMAP.md`
- Test: `tests/test_service.py`
- Test: `tests/test_api.py`
- Test: `tests/test_wallet.py`
- Test: `tests/test_persistence.py`
- Test: `tests/sessions/test_service.py`

- [ ] **Step 1: Run focused regression suite**

Run:

```bash
python -m pytest --import-mode=importlib tests\test_service.py tests\test_api.py tests\test_wallet.py tests\test_persistence.py tests\sessions\test_service.py -k "proxy or session or wallet or persistence" -q
```

Expected: PASS with zero failures.

- [ ] **Step 2: Update roadmap once tests are green**

```md
- [x] Remote/proxy-aware paid session propagation
```

- [ ] **Step 3: Re-run the regression suite after roadmap update**

Run:

```bash
python -m pytest --import-mode=importlib tests\test_service.py tests\test_api.py tests\test_wallet.py tests\test_persistence.py tests\sessions\test_service.py -k "proxy or session or wallet or persistence" -q
```

Expected: PASS with zero failures.

- [ ] **Step 4: Commit**

```bash
git add ROADMAP.md tests/test_service.py tests/test_api.py tests/test_wallet.py tests/test_persistence.py tests/sessions/test_service.py
git commit -m "feat: add proxy session propagation"
```

---

## Self-Review

### Spec Coverage

- Lazy upstream session open: covered by Task 3.
- Reuse within one local session: covered by Task 3.
- Best-effort remote close: covered by Task 3.
- Operator-facing proxy session payloads: covered by Task 4.
- Snapshot/restore: covered by Task 2.
- Remote endpoint policy snapshot: covered by Task 1.

No spec gaps remain for this implementation slice.

### Placeholder Scan

- No `TODO`, `TBD`, or deferred implementation markers are present in task steps.
- Each task has a concrete verification command.
- Each task names exact files.

### Type Consistency

- Binding model name is consistently `ProxySessionBinding`.
- Session payload block is consistently `proxy_session`.
- Upstream broker helper naming is consistently `proxy session binding`, not mixed with allocation or wallet terminology.
