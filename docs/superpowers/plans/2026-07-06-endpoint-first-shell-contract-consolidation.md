# Endpoint-First Shell Contract Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate the operator shell around an endpoint-first contract so `Home`, `Providers`, and `Bundles` become preparatory/handoff workspaces and `Endpoints` remains the only deep lifecycle control plane.

**Architecture:** Extend the existing `operator_views.py` read-model builders to compute canonical endpoint-first CTA and relationship state, then reduce inference in `operator_dashboard.html` so non-endpoint workspaces render those payloads instead of deciding lifecycle ownership locally. Keep legacy bootstrap and bundle-centric service outputs only as factual inputs and transitional adapters.

**Tech Stack:** Python, FastAPI, server-rendered dashboard HTML/JS, pytest

---

## File Structure

- Modify: `src/aidn_hypervisor/operator_views.py`
  - Centralize endpoint-first pipeline, provider readiness, and bundle relationship builders.
- Modify: `src/aidn_hypervisor/static/operator_dashboard.html`
  - Reduce client-side recommendation inference and render payload-driven handoff/CTA state.
- Modify: `tests/test_api.py`
  - Add read-model and shell regression coverage for `Home`, `Providers`, and `Bundles`.
- Modify: `ROADMAP.md`
  - Mark the shell migration slice current/delivered once tests are green.

## Task 1: Lock The Endpoint-First Read Model With Failing Tests

**Files:**
- Modify: `C:\Users\admin\Documents\New project 3\AiDN\tests\test_api.py`
- Reference: `C:\Users\admin\Documents\New project 3\AiDN\src\aidn_hypervisor\operator_views.py`

- [ ] **Step 1: Add failing home-pipeline tests for endpoint-first CTA ownership**

```python
def test_operator_dashboard_home_endpoint_pipeline_uses_endpoints_for_draft_follow_up() -> None:
    hypervisor = _service(whisper_endpoint="http://127.0.0.1:9000")
    hypervisor.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=hypervisor.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Draft STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
        )
    )
    client = TestClient(build_app(service=hypervisor, endpoint_service=endpoint_service))

    payload = client.get("/operators/dashboard/home").json()

    assert payload["endpoint_pipeline"]["state"] == "draft_exists"
    assert payload["endpoint_pipeline"]["recommended_action"]["workspace"] == "endpoints"
    assert payload["onboarding"]["recommended_action"]["action"] == "endpoints"


def test_operator_dashboard_home_endpoint_pipeline_uses_endpoints_for_in_sync_management() -> None:
    hypervisor = _service(whisper_endpoint="http://127.0.0.1:9000")
    hypervisor.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    publication_service = EndpointPublicationService(
        store=EndpointPublicationStore(),
        endpoint_service=endpoint_service,
    )
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=hypervisor.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Published STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
        )
    )
    publication_service.publish_configuration(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet=hypervisor.owner_wallet_state()["wallet_id"],
        node_id=hypervisor.node_id,
        wallet_private_key=hypervisor.owner_wallet_private_key(),
    )
    client = TestClient(
        build_app(
            service=hypervisor,
            endpoint_service=endpoint_service,
            endpoint_publication_service=publication_service,
        )
    )

    payload = client.get("/operators/dashboard/home").json()

    assert payload["endpoint_pipeline"]["state"] == "published_in_sync"
    assert payload["endpoint_pipeline"]["recommended_action"]["action"] == "endpoints"
    assert payload["endpoint_pipeline"]["recommended_action"]["workspace"] == "endpoints"
```

- [ ] **Step 2: Run the new home tests and verify they fail for the right reason**

Run:

```powershell
python -m pytest tests/test_api.py -k "home_endpoint_pipeline_uses_endpoints" -v
```

Expected:
- `FAIL`
- current payload returns older action semantics such as `publish-configuration` or non-endpoint-centric action naming instead of the new canonical handoff

- [ ] **Step 3: Add failing provider and bundle relationship tests**

```python
def test_operator_dashboard_providers_payload_prefers_endpoint_handoff_when_supply_is_ready() -> None:
    hypervisor = _service(whisper_endpoint="http://127.0.0.1:9000")
    hypervisor.configure_owner_wallet(mode="create", label="Primary Wallet")
    client = TestClient(build_app(service=hypervisor))

    payload = client.get("/operators/dashboard/providers").json()

    assert payload["summary"]["recommended_action"]["workspace"] == "endpoints"
    assert payload["summary"]["recommended_action"]["action"] in {"create_endpoint", "open_endpoint"}
    assert payload["items"][0]["endpoint_readiness"]["state"] in {
        "ready_for_endpoint_creation",
        "already_backing_endpoint_supply",
    }


def test_operator_dashboard_bundles_payload_exposes_endpoint_relationship_contract() -> None:
    hypervisor = _service(whisper_endpoint="http://127.0.0.1:9000")
    hypervisor.configure_owner_wallet(mode="create", label="Primary Wallet")
    client = TestClient(build_app(service=hypervisor))

    payload = client.get("/operators/dashboard/bundles").json()
    first = payload["items"][0]

    assert first["endpoint_relationship"]["state"] == "no_endpoint"
    assert first["endpoint_relationship"]["recommended_action"]["workspace"] == "endpoints"
    assert first["endpoint_relationship"]["recommended_action"]["action"] == "create_endpoint"
```

- [ ] **Step 4: Run the provider and bundle tests and verify they fail**

Run:

```powershell
python -m pytest tests/test_api.py -k "providers_payload_prefers_endpoint_handoff or bundles_payload_exposes_endpoint_relationship_contract" -v
```

Expected:
- `FAIL`
- provider and bundle payloads do not yet expose `endpoint_readiness` / `endpoint_relationship` in the expected shape

- [ ] **Step 5: Add failing shell markup tests for payload-driven CTA focus**

```python
def test_operator_dashboard_shell_route_uses_payload_driven_provider_and_bundle_handoff_copy() -> None:
    response = TestClient(build_app(service=_service())).get("/operators/dashboard")

    assert response.status_code == 200
    assert "selectedProvider()?.endpoint_readiness" in response.text
    assert "selectedFleetBundle()?.endpoint_relationship" in response.text
    assert "This screen prepares execution supply for endpoint creation." in response.text
    assert "This screen tracks bundle-to-endpoint relationship state." in response.text
```

- [ ] **Step 6: Run the shell test and verify it fails**

Run:

```powershell
python -m pytest tests/test_api.py -k "payload_driven_provider_and_bundle_handoff_copy" -v
```

Expected:
- `FAIL`
- shell still depends on local recommendation helpers instead of payload-driven relationship state

- [ ] **Step 7: Commit the failing tests**

```powershell
git -C 'C:\Users\admin\Documents\New project 3\AiDN' add tests/test_api.py
git -C 'C:\Users\admin\Documents\New project 3\AiDN' commit -m "test: lock endpoint-first shell contract"
```

## Task 2: Implement Canonical Endpoint-First Builders In `operator_views.py`

**Files:**
- Modify: `C:\Users\admin\Documents\New project 3\AiDN\src\aidn_hypervisor\operator_views.py`
- Test: `C:\Users\admin\Documents\New project 3\AiDN\tests\test_api.py`

- [ ] **Step 1: Implement explicit home CTA normalization around `Endpoints`**

Update the home builders so draft, published, and in-sync follow-up all normalize to explicit endpoint handoff:

```python
def _canonical_endpoint_workspace_action(*, label: str, detail: str | None = None) -> dict:
    payload = {
        "action": "endpoints",
        "label": label,
        "workspace": "endpoints",
    }
    if detail is not None:
        payload["detail"] = detail
    return payload


def _normalized_home_onboarding_action(
    *,
    endpoint_pipeline: dict,
    first_endpoint_candidate: dict | None,
) -> dict:
    state = endpoint_pipeline.get("state")
    if state == "wallet_required":
        return {
            "label": "Create Wallet",
            "detail": "Create or import a wallet before any publish or network-facing step.",
            "type": "bootstrap",
            "action": "create-wallet",
        }
    if state == "no_endpoint":
        ...
    if state == "published_drifted":
        return {
            "label": "Republish In Endpoints",
            "detail": "Open Endpoints and publish the updated configuration so the live service is back in sync.",
            "type": "screen",
            "action": "endpoints",
        }
    return {
        "label": "Manage Endpoint",
        "detail": "Open Endpoints to manage draft, publication, privacy, proxy, sessions, and validation state.",
        "type": "screen",
        "action": "endpoints",
    }
```

- [ ] **Step 2: Add provider readiness helpers**

Introduce payload helpers that make provider rows endpoint-aware without moving deep lifecycle controls into the provider workspace:

```python
def _provider_endpoint_readiness(*, provider: dict, endpoint_items: list[dict]) -> dict:
    if not provider.get("plugin_id"):
        return {
            "state": "not_attached",
            "recommended_action": {
                "action": "providers",
                "label": "Open Providers",
                "workspace": "providers",
            },
        }
    if int(provider.get("bundle_count", 0) or 0) <= 0:
        return {
            "state": "attached_no_usable_supply",
            "recommended_action": {
                "action": "providers",
                "label": "Inspect Provider",
                "workspace": "providers",
            },
        }
    related = [
        item for item in endpoint_items if item.get("bundle", {}).get("provider_type") == provider.get("plugin_id")
    ]
    if related:
        return {
            "state": "already_backing_endpoint_supply",
            "recommended_action": {
                "action": "open_endpoint",
                "label": "Open Endpoint",
                "workspace": "endpoints",
                "endpoint_id": related[0].get("endpoint_id"),
            },
        }
    return {
        "state": "ready_for_endpoint_creation",
        "recommended_action": {
            "action": "create_endpoint",
            "label": "Create Endpoint",
            "workspace": "endpoints",
        },
    }
```

- [ ] **Step 3: Add bundle relationship helpers**

Make bundle payloads expose one explicit endpoint relationship contract:

```python
def _bundle_endpoint_relationship(*, bundle: dict, relationship: dict | None) -> dict:
    if relationship is None:
        return {
            "state": "no_endpoint",
            "recommended_action": {
                "action": "create_endpoint",
                "label": "Create Endpoint",
                "workspace": "endpoints",
                "bundle_id": bundle.get("bundle_id"),
            },
        }
    publication_sync_status = relationship.get("publication_sync_status")
    endpoint_id = relationship.get("endpoint_id")
    if publication_sync_status == "local_changes_not_published":
        return {
            "state": "published_drifted",
            "recommended_action": {
                "action": "open_endpoint",
                "label": "Republish In Endpoints",
                "workspace": "endpoints",
                "endpoint_id": endpoint_id,
            },
        }
    if relationship.get("publication_status") == "published":
        state = "published_endpoint"
    else:
        state = "draft_endpoint"
    return {
        "state": state,
        "recommended_action": {
            "action": "open_endpoint",
            "label": "Open Endpoint",
            "workspace": "endpoints",
            "endpoint_id": endpoint_id,
        },
    }
```

- [ ] **Step 4: Wire the new helpers into the home, providers, and bundles payload builders**

Update the existing builders:

```python
def build_operator_providers_payload(...):
    ...
    items = []
    for provider in provider_rows:
        readiness = _provider_endpoint_readiness(
            provider=provider,
            endpoint_items=endpoint_items,
        )
        items.append({
            **provider,
            "endpoint_readiness": readiness,
        })
    summary["recommended_action"] = next(
        (
            item["endpoint_readiness"]["recommended_action"]
            for item in items
            if item["endpoint_readiness"]["recommended_action"]["workspace"] == "endpoints"
        ),
        summary["recommended_action"],
    )
    return {
        **payload,
        "items": items,
        "summary": summary,
    }


def build_operator_bundles_payload(...):
    relationships = _bundle_relationships(endpoint_items)
    items = []
    for bundle in bundle_rows:
        items.append({
            **bundle,
            "endpoint_relationship": _bundle_endpoint_relationship(
                bundle=bundle,
                relationship=relationships.get(bundle["bundle_id"]),
            ),
        })
    ...
```

- [ ] **Step 5: Run the focused tests and verify they pass**

Run:

```powershell
python -m pytest tests/test_api.py -k "home_endpoint_pipeline_uses_endpoints or providers_payload_prefers_endpoint_handoff or bundles_payload_exposes_endpoint_relationship_contract" -v
```

Expected:
- `PASS`

- [ ] **Step 6: Commit the read-model implementation**

```powershell
git -C 'C:\Users\admin\Documents\New project 3\AiDN' add src/aidn_hypervisor/operator_views.py tests/test_api.py
git -C 'C:\Users\admin\Documents\New project 3\AiDN' commit -m "feat: add endpoint-first shell read models"
```

## Task 3: Move Dashboard Shell Handoff Logic To Payload-Driven Rendering

**Files:**
- Modify: `C:\Users\admin\Documents\New project 3\AiDN\src\aidn_hypervisor\static\operator_dashboard.html`
- Test: `C:\Users\admin\Documents\New project 3\AiDN\tests\test_api.py`

- [ ] **Step 1: Add small payload-driven helpers for endpoint handoff**

Replace ad hoc provider/bundle recommendation focus with payload-first helpers:

```javascript
function providerEndpointReadiness(provider) {
  return provider?.endpoint_readiness || {
    state: "not_attached",
    recommended_action: { action: "providers", label: "Open Providers", workspace: "providers" },
  };
}

function bundleEndpointRelationship(bundle) {
  return bundle?.endpoint_relationship || {
    state: "no_endpoint",
    recommended_action: { action: "create_endpoint", label: "Create Endpoint", workspace: "endpoints" },
  };
}
```

- [ ] **Step 2: Reframe Providers inspector and workspace around endpoint readiness**

Update copy and CTA focus:

```javascript
const readiness = providerEndpointReadiness(provider);
...
<div class="inspector-copy">
  This provider prepares execution supply for endpoint lifecycle. Deep publication, proxy, session, and validation controls stay in Endpoints.
</div>
...
<button
  class="secondary-button ${readiness.recommended_action.workspace === "endpoints" ? "action-focus" : ""}"
  type="button"
  data-screen-jump="${readiness.recommended_action.workspace === "endpoints" ? "endpoints" : "providers"}"
>
  ${readiness.recommended_action.label}
</button>
```

- [ ] **Step 3: Reframe Bundles workspace and inspector around endpoint relationship**

Update bundle rendering to expose explicit relationship state and handoff:

```javascript
const relationship = bundleEndpointRelationship(selected);
...
<div class="inspector-copy">
  This screen tracks bundle-to-endpoint relationship state. Publication, proof, privacy, proxy, sessions, and validation continue in Endpoints.
</div>
<span class="chip">${relationship.state}</span>
<button
  class="primary-button ${relationship.recommended_action.workspace === "endpoints" ? "action-focus" : ""}"
  type="button"
  data-screen-jump="endpoints"
>
  ${relationship.recommended_action.label}
</button>
```

- [ ] **Step 4: Keep Home endpoint-centric and remove stale competing CTA emphasis**

Make the shell prefer server-provided endpoint pipeline state for the primary home CTA:

```javascript
const endpointPipeline = state.payloads.home?.endpoint_pipeline || {};
const recommendation = state.payloads.home?.onboarding?.recommended_action || homeRecommendedAction(bootstrap);
const primaryEndpointId = endpointPipeline.primary_endpoint_id || null;
```

Then ensure home buttons focus only one dominant endpoint-centric path and keep secondary navigation visually weaker.

- [ ] **Step 5: Run shell-focused tests and verify they pass**

Run:

```powershell
python -m pytest tests/test_api.py -k "payload_driven_provider_and_bundle_handoff_copy or home_shell_highlights_publish_configuration_recommendation or shell_route_exposes_bundle" -v
```

Expected:
- `PASS`

- [ ] **Step 6: Run the full regression suite**

Run:

```powershell
python -m pytest -q
```

Expected:
- full suite passes

- [ ] **Step 7: Update the roadmap after tests are green**

Update `C:\Users\admin\Documents\New project 3\AiDN\ROADMAP.md` to reflect:

- endpoint-first shell migration materially complete;
- `Home / Providers / Bundles` now hand off into `Endpoints`;
- next major layer is `M5` trust, rating, and validation publication on top of the consolidated shell.

Suggested edit target:

```markdown
- the current shell slice is migrating `Home`, `Providers`, and `Bundles` to hand work explicitly into `Endpoints`;
```

Replace with:

```markdown
- `Home`, `Providers`, and `Bundles` now behave as endpoint-first agenda and preparation surfaces that hand deep lifecycle control into `Endpoints`;
```

- [ ] **Step 8: Re-run the targeted dashboard tests after the roadmap edit**

Run:

```powershell
python -m pytest tests/test_api.py -k "operator_dashboard_home or operator_dashboard_shell_route or providers_payload_prefers_endpoint_handoff or bundles_payload_exposes_endpoint_relationship_contract" -v
```

Expected:
- `PASS`

- [ ] **Step 9: Commit the shell migration slice**

```powershell
git -C 'C:\Users\admin\Documents\New project 3\AiDN' add src/aidn_hypervisor/static/operator_dashboard.html tests/test_api.py ROADMAP.md
git -C 'C:\Users\admin\Documents\New project 3\AiDN' commit -m "feat: consolidate endpoint-first operator shell"
```

## Spec Coverage Check

- Canonical `Endpoints` control plane: covered by Task 2 and Task 3
- `Home` as endpoint-centric agenda: covered by Task 1 and Task 2
- `Providers` as supply-prep surface: covered by Task 1, Task 2, and Task 3
- `Bundles` as endpoint-relationship surface: covered by Task 1, Task 2, and Task 3
- Non-endpoint lifecycle demotion: covered by Task 3
- Roadmap sync after green tests: covered by Task 3

## Placeholder Scan

Checked for:
- `TBD`
- `TODO`
- vague “add tests” steps without code
- vague “update logic” steps without target files

No placeholders should remain.

## Type Consistency Check

The plan standardizes these payload shapes:

- `endpoint_pipeline.recommended_action.action`
- `endpoint_readiness.state`
- `endpoint_readiness.recommended_action`
- `endpoint_relationship.state`
- `endpoint_relationship.recommended_action`

Use these exact property names in implementation and tests.
