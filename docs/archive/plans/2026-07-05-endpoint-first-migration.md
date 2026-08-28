# Endpoint-First Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `Endpoints` the canonical operator workspace, with `Home` always pointing to the next endpoint-centric step and `Providers` / `Bundles` acting as preparatory surfaces that explicitly hand work into the endpoint lifecycle.

**Architecture:** Keep the migration view-model first. `operator_views.py` becomes the source of truth for endpoint-centric recommendation state, bundle-to-endpoint relationship mapping, and workspace handoff metadata. `operator_dashboard.html` consumes those payloads to shift CTA hierarchy and copy without changing persistence or protocol contracts.

**Tech Stack:** Python, FastAPI, static HTML/JS dashboard shell, existing `aidn_hypervisor` services, pytest.

---

## File Structure

### Existing files to modify

- `src/aidn_hypervisor/operator_views.py`
  - Add endpoint-pipeline helpers, bundle-to-endpoint relationship mapping, and endpoint-first workspace recommendations
- `src/aidn_hypervisor/api.py`
  - Pass endpoint-aware dependencies into the `Providers` and `Bundles` payload builders so those workspaces can reason about existing endpoint lifecycle
- `src/aidn_hypervisor/static/operator_dashboard.html`
  - Reframe `Home`, `Providers`, `Bundles`, and `Endpoints` around endpoint-first copy, metrics, and CTA priority
- `tests/test_operator_views.py`
  - Cover home pipeline states, provider/bundle handoff metadata, and endpoint-first payload semantics
- `tests/test_api.py`
  - Cover route wiring for endpoint-aware workspace payloads and shell markup for the endpoint-first hierarchy
- `ROADMAP.md`
  - Mark the shell-migration slice current and describe the next step after this migration layer lands

### Existing reference files to inspect while implementing

- `docs/archive/specifications/2026-07-05-endpoint-first-migration-design.md`
- `docs/product/UX-0001-hypervisor-operator-journey.md`
- `docs/product/UX-0002-endpoint-session-and-payment-flow.md`
- `src/aidn_hypervisor/operator_views.py`
- `src/aidn_hypervisor/static/operator_dashboard.html`
- `tests/test_operator_views.py`
- `tests/test_api.py`

---

### Task 1: Add A Canonical Home Endpoint Pipeline Read Model

**Files:**
- Modify: `src/aidn_hypervisor/operator_views.py`
- Modify: `tests/test_operator_views.py`

- [ ] **Step 1: Write the failing home-pipeline tests**

```python
def test_home_payload_surfaces_endpoint_pipeline_for_first_draft(
    service: HypervisorService,
    endpoint_service: EndpointService,
) -> None:
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=service.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Operator STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
        )
    )

    payload = build_operator_home_payload(
        service=service,
        endpoint_service=endpoint_service,
        endpoint_publication_service=None,
        validation_service=None,
        market_candidates=[],
    )

    assert payload["endpoint_pipeline"]["state"] == "draft_exists"
    assert payload["endpoint_pipeline"]["primary_endpoint_id"] == created.endpoint.endpoint_id
    assert payload["endpoint_pipeline"]["recommended_action"]["action"] == "open-endpoints"
    assert payload["bootstrap"]["next_step"] == "Review your configured endpoint and publish it"


def test_home_payload_surfaces_drifted_publication_as_the_primary_attention_state(
    service: HypervisorService,
    endpoint_service: EndpointService,
    endpoint_publication_service: EndpointPublicationService,
) -> None:
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=service.owner_wallet_state()["wallet_id"],
            bundle_id="text-a",
            bundle_hash="text-a",
            display_name="Published Text",
            model_class="llm_text",
            capabilities=["llm_text.generate"],
        )
    )
    endpoint_publication_service.publish_configuration(created.endpoint.endpoint_id)
    endpoint_service.update_endpoint(
        created.endpoint.endpoint_id,
        display_name="Published Text v2",
    )

    payload = build_operator_home_payload(
        service=service,
        endpoint_service=endpoint_service,
        endpoint_publication_service=endpoint_publication_service,
        validation_service=None,
        market_candidates=[],
    )

    assert payload["endpoint_pipeline"]["state"] == "published_drifted"
    assert payload["endpoint_pipeline"]["recommended_action"]["action"] == "publish-configuration"
    assert payload["endpoint_pipeline"]["publication_sync_status"] == "local_changes_not_published"
```

- [ ] **Step 2: Run the focused home-pipeline tests to verify they fail**

Run: `pytest tests/test_operator_views.py -k "home_payload_surfaces_endpoint_pipeline" -v`

Expected: FAIL because `endpoint_pipeline` does not exist in the home payload and drift is not promoted into one canonical home-level state.

- [ ] **Step 3: Add endpoint-pipeline helpers and wire them into `build_operator_home_payload`**

```python
def _primary_endpoint_for_home(endpoint_items: list[dict]) -> dict | None:
    priority = {
        "local_changes_not_published": 0,
        "never_published": 1,
        "in_sync": 2,
    }
    if not endpoint_items:
        return None
    return sorted(
        endpoint_items,
        key=lambda item: (
            priority.get(item.get("publication_sync_status"), 99),
            item.get("publication_status") != "published",
            item.get("endpoint_id") or "",
        ),
    )[0]


def _home_endpoint_pipeline(*, endpoint_items: list[dict], wallet_ready: bool) -> dict:
    primary = _primary_endpoint_for_home(endpoint_items)
    if not wallet_ready:
        return {
            "state": "wallet_required",
            "primary_endpoint_id": None,
            "publication_sync_status": None,
            "recommended_action": {
                "action": "create-wallet",
                "label": "Create Wallet",
                "workspace": "home",
            },
        }
    if primary is None:
        return {
            "state": "no_endpoint",
            "primary_endpoint_id": None,
            "publication_sync_status": None,
            "recommended_action": {
                "action": "open-bundles",
                "label": "Open Bundles",
                "workspace": "bundles",
            },
        }
    if primary["publication_sync_status"] == "local_changes_not_published":
        return {
            "state": "published_drifted",
            "primary_endpoint_id": primary["endpoint_id"],
            "publication_sync_status": primary["publication_sync_status"],
            "recommended_action": {
                "action": "publish-configuration",
                "label": "Publish Configuration",
                "workspace": "endpoints",
            },
        }
    if primary["publication_status"] in {"configured", "draft"}:
        return {
            "state": "draft_exists",
            "primary_endpoint_id": primary["endpoint_id"],
            "publication_sync_status": primary["publication_sync_status"],
            "recommended_action": {
                "action": "open-endpoints",
                "label": "Open Endpoints",
                "workspace": "endpoints",
            },
        }
    return {
        "state": "published_in_sync",
        "primary_endpoint_id": primary["endpoint_id"],
        "publication_sync_status": primary["publication_sync_status"],
        "recommended_action": {
            "action": "open-endpoints",
            "label": "Open Live Endpoint",
            "workspace": "endpoints",
        },
    }


def build_operator_home_payload(
    *,
    service,
    endpoint_service,
    endpoint_publication_service=None,
    validation_service=None,
    market_candidates=None,
) -> dict:
    ...
    endpoint_pipeline = _home_endpoint_pipeline(
        endpoint_items=endpoints_payload["items"],
        wallet_ready=service.owner_wallet_state()["configured"],
    )
    return {
        "bootstrap": _build_operator_home_bootstrap_payload(...),
        "endpoint_pipeline": endpoint_pipeline,
        "onboarding": onboarding,
        ...
    }
```

- [ ] **Step 4: Re-run the focused home-pipeline tests to verify they pass**

Run: `pytest tests/test_operator_views.py -k "home_payload_surfaces_endpoint_pipeline" -v`

Expected: PASS for both the draft and drifted endpoint pipeline cases.

- [ ] **Step 5: Commit the home read-model slice**

```bash
git add src/aidn_hypervisor/operator_views.py tests/test_operator_views.py
git commit -m "feat: add home endpoint pipeline state"
```

---

### Task 2: Make Providers And Bundles Explicitly Endpoint-Producing Workspaces

**Files:**
- Modify: `src/aidn_hypervisor/operator_views.py`
- Modify: `src/aidn_hypervisor/api.py`
- Modify: `tests/test_operator_views.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Write the failing provider and bundle relationship tests**

```python
def test_bundles_payload_exposes_endpoint_relationship_states(
    service: HypervisorService,
    endpoint_service: EndpointService,
) -> None:
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=service.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Operator STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
        )
    )

    payload = build_operator_bundles_payload(
        service=service,
        endpoint_service=endpoint_service,
        endpoint_publication_service=None,
        validation_service=None,
    )

    whisper = next(item for item in payload["items"] if item["bundle_id"] == "whisper-a")
    text = next(item for item in payload["items"] if item["bundle_id"] == "text-a")
    assert whisper["endpoint_relationship"]["state"] == "draft_endpoint_exists"
    assert whisper["endpoint_relationship"]["endpoint_id"] == created.endpoint.endpoint_id
    assert whisper["endpoint_action"]["recommended"] == "open_endpoint"
    assert text["endpoint_relationship"]["state"] == "no_endpoint"
    assert text["endpoint_action"]["recommended"] == "create_endpoint"


def test_providers_payload_prefers_endpoint_handoff_once_local_supply_is_usable(
    service: HypervisorService,
    endpoint_service: EndpointService,
) -> None:
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    payload = build_operator_providers_payload(
        service=service,
        endpoint_service=endpoint_service,
        endpoint_publication_service=None,
        validation_service=None,
    )

    assert payload["summary"]["endpoint_ready_bundles"] == 2
    assert payload["recommended_action"]["action"] == "open-bundles"
    assert payload["recommended_action"]["workspace"] == "bundles"


def test_operator_dashboard_bundles_route_passes_endpoint_services(
    monkeypatch,
) -> None:
    hypervisor = _service()
    endpoint_service = EndpointService(EndpointStore())
    captured: dict[str, object] = {}

    def fake_build_operator_bundles_payload(**kwargs) -> dict:
        captured.update(kwargs)
        return {"summary": {"total": 0}, "items": []}

    monkeypatch.setattr(
        "aidn_hypervisor.api.build_operator_bundles_payload",
        fake_build_operator_bundles_payload,
    )
    client = TestClient(build_app(service=hypervisor, endpoint_service=endpoint_service))

    response = client.get("/operators/dashboard/bundles")

    assert response.status_code == 200
    assert captured["service"] is hypervisor
    assert captured["endpoint_service"] is endpoint_service
```

- [ ] **Step 2: Run the focused provider and bundle tests to verify they fail**

Run: `pytest tests/test_operator_views.py tests/test_api.py -k "endpoint_relationship_states or endpoint_handoff_once_local_supply_is_usable or bundles_route_passes_endpoint_services" -v`

Expected: FAIL because `build_operator_providers_payload()` and `build_operator_bundles_payload()` do not accept endpoint-aware dependencies and do not expose bundle-to-endpoint relationship state.

- [ ] **Step 3: Add endpoint relationship mapping and route the new dependencies through `api.py`**

```python
def _bundle_relationships(endpoint_items: list[dict]) -> dict[str, dict]:
    relationships: dict[str, dict] = {}
    for item in endpoint_items:
        state = (
            "published_endpoint_exists"
            if item["publication_status"] == "published"
            else "draft_endpoint_exists"
        )
        relationships[item["bundle_id"]] = {
            "state": state,
            "endpoint_id": item["endpoint_id"],
            "publication_sync_status": item.get("publication_sync_status"),
        }
    return relationships


def build_operator_providers_payload(
    *,
    service,
    endpoint_service=None,
    endpoint_publication_service=None,
    validation_service=None,
) -> dict:
    endpoint_items = build_operator_endpoints_payload(
        service=service,
        endpoint_service=endpoint_service,
        endpoint_publication_service=endpoint_publication_service,
        validation_service=validation_service,
    )["items"]
    relationships = _bundle_relationships(endpoint_items)
    ...
    return {
        "owner_wallet": fleet["owner_wallet"],
        "node_identity": fleet["node_identity"],
        "recommended_action": {
            "action": "open-bundles" if bundles else "attach-provider",
            "label": "Open Bundles" if bundles else "Attach Provider",
            "workspace": "bundles" if bundles else "providers",
        },
        "summary": {
            "total": len(items),
            "bundles": len(bundles),
            "installs": len(installs),
            "endpoint_ready_bundles": sum(
                1 for bundle in bundles if bundle["bundle_id"] not in relationships
            ),
        },
        "items": items,
    }


def build_operator_bundles_payload(
    *,
    service,
    endpoint_service=None,
    endpoint_publication_service=None,
    validation_service=None,
) -> dict:
    endpoint_items = build_operator_endpoints_payload(
        service=service,
        endpoint_service=endpoint_service,
        endpoint_publication_service=endpoint_publication_service,
        validation_service=validation_service,
    )["items"]
    relationships = _bundle_relationships(endpoint_items)
    ...
    items.append(
        {
            **bundle,
            "endpoint_relationship": relationships.get(
                bundle["bundle_id"],
                {"state": "no_endpoint", "endpoint_id": None, "publication_sync_status": None},
            ),
            "endpoint_action": {
                "recommended": (
                    "open_endpoint"
                    if bundle["bundle_id"] in relationships
                    else "create_endpoint"
                )
            },
        }
    )
    return {
        ...,
        "recommended_action": {
            "action": "open-endpoints" if endpoint_items else "create-endpoint",
            "label": "Open Endpoints" if endpoint_items else "Create Endpoint",
            "workspace": "endpoints" if endpoint_items else "bundles",
        },
    }


@router.get("/operators/dashboard/providers")
async def operator_dashboard_providers() -> dict:
    return build_operator_providers_payload(
        service=service,
        endpoint_service=endpoint_service,
        endpoint_publication_service=endpoint_publication_service,
        validation_service=validation_service,
    )


@router.get("/operators/dashboard/bundles")
async def operator_dashboard_bundles() -> dict:
    return build_operator_bundles_payload(
        service=service,
        endpoint_service=endpoint_service,
        endpoint_publication_service=endpoint_publication_service,
        validation_service=validation_service,
    )
```

- [ ] **Step 4: Re-run the focused provider and bundle tests to verify they pass**

Run: `pytest tests/test_operator_views.py tests/test_api.py -k "endpoint_relationship_states or endpoint_handoff_once_local_supply_is_usable or bundles_route_passes_endpoint_services" -v`

Expected: PASS with explicit endpoint relationship state in `Bundles` and endpoint-aware route wiring in `api.py`.

- [ ] **Step 5: Commit the endpoint-producing workspace slice**

```bash
git add src/aidn_hypervisor/operator_views.py src/aidn_hypervisor/api.py tests/test_operator_views.py tests/test_api.py
git commit -m "feat: add endpoint-aware provider and bundle handoff"
```

---

### Task 3: Make Endpoints The Canonical Operator Workspace In The Dashboard Shell

**Files:**
- Modify: `src/aidn_hypervisor/operator_views.py`
- Modify: `src/aidn_hypervisor/static/operator_dashboard.html`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Write the failing shell and payload tests**

```python
def test_operator_dashboard_shell_route_exposes_endpoint_pipeline_copy() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert "Endpoint Pipeline" in response.text
    assert "Endpoints are the primary operator workspace." in response.text
    assert "Providers prepare execution supply. Bundles prepare endpoint candidates." in response.text
    assert 'data-screen-jump="endpoints"' in response.text


def test_endpoints_payload_marks_workspace_as_primary_control_plane(
    service: HypervisorService,
    endpoint_service: EndpointService,
) -> None:
    payload = build_operator_endpoints_payload(
        service=service,
        endpoint_service=endpoint_service,
        endpoint_publication_service=None,
        validation_service=None,
    )

    assert payload["workspace_role"] == "primary_control_plane"
    assert payload["recommended_action"]["workspace"] == "endpoints"
    assert payload["policy"]["validation_optional"] is True
```

- [ ] **Step 2: Run the focused shell tests to verify they fail**

Run: `pytest tests/test_api.py -k "endpoint_pipeline_copy or primary_control_plane" -v`

Expected: FAIL because the shell still uses older bootstrap and inventory-first copy and the endpoints payload does not expose a canonical workspace role.

- [ ] **Step 3: Reframe the endpoints payload and shell copy around endpoint-first hierarchy**

```python
def build_operator_endpoints_payload(
    *,
    service,
    endpoint_service,
    endpoint_publication_service=None,
    validation_service=None,
) -> dict:
    ...
    attention_count = sum(
        1
        for item in items
        if item["publication_sync_status"] != "in_sync"
        or item["publication_status"] != "published"
    )
    return {
        "owner_wallet": service.owner_wallet_state(),
        "node_identity": service.node_identity(),
        "workspace_role": "primary_control_plane",
        "recommended_action": {
            "action": "select_endpoint" if items else "create_endpoint",
            "label": "Open Endpoint Controls" if items else "Create Endpoint",
            "workspace": "endpoints",
        },
        "summary": {
            "total": len(items),
            "configured": ...,
            "published": ...,
            "validation_requested": ...,
            "private": ...,
            "shared": ...,
            "public": ...,
            "attention_count": attention_count,
        },
        "policy": {
            "publish_requires_validation": False,
            "validation_optional": True,
            "execution_privacy": "endpoint implementation remains private",
        },
        "items": items,
        "onboarding": build_onboarding_payload(...),
    }
```

```html
<div class="panel-heading">Endpoint Pipeline</div>
<div class="notice" style="margin-top: 14px;">
  <strong>Endpoints are the primary operator workspace.</strong>
  <span style="display: block; margin-top: 4px;">
    Providers prepare execution supply. Bundles prepare endpoint candidates. Publication, proof, privacy, proxy routing, and validation converge in Endpoints.
  </span>
</div>
```

```html
<p class="workspace-copy">This screen prepares execution supply for endpoint creation. Once a provider yields usable local bundles, the dominant handoff is into Endpoints.</p>
```

```html
<p class="workspace-copy">This screen prepares endpoint candidates from local inventory. Once a bundle has an endpoint relationship, the operator should continue lifecycle decisions in Endpoints.</p>
```

```html
<p class="workspace-copy">Endpoints is the canonical operator control plane for privacy, signed publication, proof sync, proxy routing, sessions, and optional validation.</p>
```

- [ ] **Step 4: Re-run the focused shell tests to verify they pass**

Run: `pytest tests/test_api.py -k "endpoint_pipeline_copy or primary_control_plane" -v`

Expected: PASS with endpoint-first shell copy and a canonical endpoints workspace role in the payload.

- [ ] **Step 5: Commit the dashboard hierarchy slice**

```bash
git add src/aidn_hypervisor/operator_views.py src/aidn_hypervisor/static/operator_dashboard.html tests/test_api.py
git commit -m "feat: make endpoints the primary dashboard workspace"
```

---

### Task 4: Update The Roadmap And Run Verification

**Files:**
- Modify: `ROADMAP.md`

- [ ] **Step 1: Update the roadmap to mark the migration layer current**

```md
Product alignment summary:
- guided onboarding now lands operators inside a working endpoint-first bootstrap loop;
- the current shell slice is migrating `Home`, `Providers`, and `Bundles` to hand work explicitly into `Endpoints`;
- the next product layer after this migration is trust-and-market depth on top of the canonical endpoint workspace.

Immediate Priorities:
1. Finish the endpoint-first shell migration so `Home`, `Providers`, and `Bundles` all hand off into `Endpoints`
2. Expand endpoint lifecycle controls across remote/proxy and marketplace routing
3. Implement `M5` rating, validation, and trust publication on top of the canonical endpoint workspace
```

- [ ] **Step 2: Run the focused verification suite**

Run: `pytest tests/test_operator_views.py tests/test_api.py tests/test_operator_onboarding.py tests/endpoints/test_endpoint_api.py -v`

Expected: PASS for the endpoint-first payload, route, shell, onboarding, and endpoint API regressions.

- [ ] **Step 3: Run a dashboard smoke pass**

Run: `python -m uvicorn aidn_hypervisor.main:app --reload`

Expected:
- `Home` shows one endpoint-pipeline state and one dominant next action
- `Providers` and `Bundles` both point toward `Endpoints`
- `Endpoints` reads as the primary operator control plane

- [ ] **Step 4: Commit the roadmap and verification slice**

```bash
git add ROADMAP.md
git commit -m "docs: update roadmap for endpoint-first migration"
```

---

## Self-Review

### Spec coverage

- `Home becomes an endpoint pipeline surface`
  - Covered by Task 1 and Task 3
- `Providers and Bundles become endpoint-producing workspaces`
  - Covered by Task 2 and Task 3
- `Endpoints becomes the canonical operator workspace`
  - Covered by Task 3
- `ROADMAP.md` reflects the next stage after the migration
  - Covered by Task 4

### Placeholder scan

- No `TODO`, `TBD`, `implement later`, or placeholder instructions remain.

### Type consistency

- `endpoint_pipeline`
  - Introduced in Task 1 and used consistently afterward
- `endpoint_relationship`
  - Introduced in Task 2 and used consistently in bundle payloads
- `workspace_role`
  - Introduced in Task 3 and used only for the endpoints payload

## Execution Handoff

Plan complete and saved to `docs/archive/plans/2026-07-05-endpoint-first-migration.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
