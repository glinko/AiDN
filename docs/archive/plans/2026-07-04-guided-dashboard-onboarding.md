# Guided Dashboard Onboarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the existing operator dashboard bootstrap affordances into a persisted guided onboarding flow that takes a new operator from `wallet -> provider -> bundle -> first endpoint -> publish`, then returns them to the normal dashboard with onboarding marked complete.

**Architecture:** Keep `HypervisorService` as the factual source of persisted state, but move onboarding-step derivation into a focused `operator_onboarding.py` helper so the dashboard can render one canonical progress model. `operator_views.py` becomes the owner of onboarding-aware `Home`, `Providers`, `Bundles`, and `Endpoints` payloads, while `operator_dashboard.html` renders a guided layer on top of the existing shell instead of introducing a separate wizard mode.

**Tech Stack:** Python, FastAPI, Pydantic, pytest, existing `aidn_hypervisor` services, and the static operator dashboard HTML/JS shell.

---

## File Structure

### New files

- `src/aidn_hypervisor/operator_onboarding.py`
  - Pure helper module that derives onboarding progress, current step, completion state, and workspace guidance from factual dashboard state
- `tests/test_operator_onboarding.py`
  - Unit tests for step derivation, completion rules, and workspace-specific recommendations

### Existing files to modify

- `src/aidn_hypervisor/state.py`
  - Add persisted onboarding snapshot models to `HypervisorStateSnapshot`
- `src/aidn_hypervisor/service.py`
  - Persist onboarding state, restore it from snapshots, and synchronize it after wallet and endpoint lifecycle actions
- `src/aidn_hypervisor/operator_views.py`
  - Embed one onboarding payload into `Home`, `Providers`, `Bundles`, and `Endpoints`
- `src/aidn_hypervisor/api.py`
  - Keep dashboard routes thin, but ensure endpoint create/publish flows return refreshed onboarding-aware payloads
- `src/aidn_hypervisor/static/operator_dashboard.html`
  - Replace the loose bootstrap card with a guided agenda, progress rail, workspace jump controls, and completion copy
- `tests/test_service.py`
  - Cover persistence and completion rules
- `tests/test_operator_views.py`
  - Cover dashboard payload shaping after factual state changes
- `tests/test_api.py`
  - Cover route payloads and shell markup for the guided layer

### Existing reference files to inspect while implementing

- `docs/archive/specifications/2026-07-04-guided-dashboard-onboarding-design.md`
- `ROADMAP.md`
- `src/aidn_hypervisor/state.py:219-289`
- `src/aidn_hypervisor/service.py:1211-1293`
- `src/aidn_hypervisor/service.py:1772-1977`
- `src/aidn_hypervisor/service.py:2516-2541`
- `src/aidn_hypervisor/operator_views.py:102-188`
- `src/aidn_hypervisor/operator_views.py:236-477`
- `src/aidn_hypervisor/api.py:860-897`
- `src/aidn_hypervisor/api.py:1385-1412`
- `src/aidn_hypervisor/static/operator_dashboard.html:1519-1592`
- `src/aidn_hypervisor/static/operator_dashboard.html:2168-2201`
- `src/aidn_hypervisor/static/operator_dashboard.html:3045-3204`
- `src/aidn_hypervisor/static/operator_dashboard.html:6280-6365`

---

### Task 1: Persist Guided Onboarding State

**Files:**
- Modify: `src/aidn_hypervisor/state.py:219-289`
- Modify: `src/aidn_hypervisor/service.py:1211-1293`
- Modify: `src/aidn_hypervisor/service.py:1772-1977`
- Test: `tests/test_service.py`

- [ ] **Step 1: Write the failing service tests**

```python
def test_service_onboarding_state_persists_after_wallet_and_publish() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 8192})
        ),
        bundles=[_bundle("whisper-a", "speech_to_text")],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
    )
    endpoint_service = EndpointService(EndpointStore())

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
    service.sync_operator_onboarding_state(
        endpoint_items=[
            {
                "endpoint_id": created.endpoint.endpoint_id,
                "bundle_id": "whisper-a",
                "publication_status": "published",
                "visibility": "private",
            }
        ]
    )

    restored = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 8192})
        ),
        bundles=[_bundle("whisper-a", "speech_to_text")],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
    )
    restored.restore_state(service.snapshot_state())

    onboarding = restored.operator_onboarding_state()
    assert onboarding["completed"] is True
    assert onboarding["completed_via"] == "first_local_endpoint_published"
    assert onboarding["current_step"] == "operate"


def test_service_onboarding_stays_incomplete_for_unpublished_endpoint() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 8192})
        ),
        bundles=[_bundle("whisper-a", "speech_to_text")],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
    )

    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    service.sync_operator_onboarding_state(
        endpoint_items=[
            {
                "endpoint_id": "endpoint-draft",
                "bundle_id": "whisper-a",
                "publication_status": "configured",
                "visibility": "private",
            }
        ]
    )

    onboarding = service.operator_onboarding_state()
    assert onboarding["completed"] is False
    assert onboarding["current_step"] == "publish_endpoint"
```

- [ ] **Step 2: Run the focused service tests to verify they fail**

Run: `pytest tests/test_service.py -k onboarding -v`
Expected: FAIL with `AttributeError` or missing onboarding fields on the service snapshot/state methods.

- [ ] **Step 3: Add persisted onboarding snapshot models**

```python
class OperatorOnboardingStepSnapshot(BaseModel):
    key: str
    status: str
    label: str
    workspace: str
    completed_at: str | None = None


class OperatorOnboardingSnapshot(BaseModel):
    completed: bool = False
    completed_at: str | None = None
    completed_via: str | None = None
    current_step: str = "configure_wallet"
    last_workspace: str = "home"
    transition_history: list[str] = Field(default_factory=list)
    steps: list[OperatorOnboardingStepSnapshot] = Field(default_factory=list)


class HypervisorStateSnapshot(BaseModel):
    ...
    owner_wallet: OwnerWalletSnapshot | None = None
    operator_onboarding: OperatorOnboardingSnapshot | None = None
    endpoints: list[EndpointManifestSnapshot] = Field(default_factory=list)
```

- [ ] **Step 4: Persist and restore onboarding state inside `HypervisorService`**

```python
def operator_onboarding_state(self) -> dict:
    if self._operator_onboarding is None:
        return {
            "completed": False,
            "completed_at": None,
            "completed_via": None,
            "current_step": "configure_wallet",
            "last_workspace": "home",
            "transition_history": [],
            "steps": [],
        }
    return deepcopy(self._operator_onboarding)


def sync_operator_onboarding_state(
    self,
    *,
    endpoint_items: list[dict],
    last_workspace: str | None = None,
) -> dict:
    onboarding = self.operator_onboarding_state()
    if last_workspace is not None:
        onboarding["last_workspace"] = last_workspace
    if any(item["publication_status"] == "published" for item in endpoint_items):
        onboarding["completed"] = True
        onboarding["completed_via"] = "first_local_endpoint_published"
        onboarding["completed_at"] = datetime.now(timezone.utc).isoformat()
        onboarding["current_step"] = "operate"
    elif endpoint_items:
        onboarding["current_step"] = "publish_endpoint"
    elif self.owner_wallet_state()["configured"]:
        onboarding["current_step"] = "attach_provider"
    self._operator_onboarding = onboarding
    self._persist_state()
    return deepcopy(onboarding)


def snapshot_state(self) -> HypervisorStateSnapshot:
    return HypervisorStateSnapshot(
        ...
        owner_wallet=(
            OwnerWalletSnapshot(**self._owner_wallet)
            if self._owner_wallet is not None
            else None
        ),
        operator_onboarding=(
            OperatorOnboardingSnapshot(**self._operator_onboarding)
            if self._operator_onboarding is not None
            else None
        ),
        ...
    )


def restore_state(self, snapshot: HypervisorStateSnapshot) -> dict[str, int]:
    ...
    self._operator_onboarding = (
        snapshot.operator_onboarding.model_dump(mode="json")
        if snapshot.operator_onboarding is not None
        else None
    )
```

- [ ] **Step 5: Re-run the focused service tests to verify they pass**

Run: `pytest tests/test_service.py -k onboarding -v`
Expected: PASS for the new onboarding persistence and completion tests.

- [ ] **Step 6: Commit the persistence slice**

```bash
git add src/aidn_hypervisor/state.py src/aidn_hypervisor/service.py tests/test_service.py
git commit -m "feat: persist operator onboarding state"
```

---

### Task 2: Derive One Canonical Onboarding Read Model

**Files:**
- Create: `src/aidn_hypervisor/operator_onboarding.py`
- Create: `tests/test_operator_onboarding.py`
- Modify: `src/aidn_hypervisor/operator_views.py:102-188`
- Modify: `src/aidn_hypervisor/operator_views.py:236-477`
- Test: `tests/test_operator_views.py`

- [ ] **Step 1: Write the failing onboarding derivation tests**

```python
from aidn_hypervisor.operator_onboarding import build_onboarding_payload


def test_build_onboarding_payload_requires_wallet_first() -> None:
    payload = build_onboarding_payload(
        wallet_ready=False,
        provider_count=1,
        bundle_count=1,
        endpoint_items=[],
        first_endpoint_candidate={"bundle_id": "whisper-a"},
        persisted={"completed": False},
    )

    assert payload["current_step"] == "configure_wallet"
    assert payload["workspace"] == "home"
    assert payload["recommended_action"]["action"] == "create-wallet"


def test_build_onboarding_payload_completes_after_first_published_endpoint() -> None:
    payload = build_onboarding_payload(
        wallet_ready=True,
        provider_count=1,
        bundle_count=1,
        endpoint_items=[
            {
                "endpoint_id": "endpoint-1",
                "publication_status": "published",
                "bundle_id": "whisper-a",
            }
        ],
        first_endpoint_candidate={"bundle_id": "whisper-a"},
        persisted={"completed": True, "completed_via": "first_local_endpoint_published"},
    )

    assert payload["completed"] is True
    assert payload["current_step"] == "operate"
    assert payload["recommended_action"]["action"] == "open-home"
```

- [ ] **Step 2: Run the new onboarding unit tests to verify they fail**

Run: `pytest tests/test_operator_onboarding.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'aidn_hypervisor.operator_onboarding'`.

- [ ] **Step 3: Create `operator_onboarding.py` with deterministic step derivation**

```python
ONBOARDING_STEPS = [
    ("configure_wallet", "Configure Wallet", "home"),
    ("attach_provider", "Attach Provider", "providers"),
    ("prepare_bundle", "Prepare Bundle", "bundles"),
    ("create_endpoint", "Create Endpoint", "bundles"),
    ("publish_endpoint", "Publish Endpoint", "endpoints"),
    ("operate", "Operate Hypervisor", "home"),
]


def build_onboarding_payload(
    *,
    wallet_ready: bool,
    provider_count: int,
    bundle_count: int,
    endpoint_items: list[dict],
    first_endpoint_candidate: dict | None,
    persisted: dict | None,
) -> dict:
    if not wallet_ready:
        current_step = "configure_wallet"
    elif provider_count <= 0:
        current_step = "attach_provider"
    elif bundle_count <= 0 or first_endpoint_candidate is None:
        current_step = "prepare_bundle"
    elif not endpoint_items:
        current_step = "create_endpoint"
    elif any(item["publication_status"] == "published" for item in endpoint_items):
        current_step = "operate"
    else:
        current_step = "publish_endpoint"

    completed = bool((persisted or {}).get("completed")) or current_step == "operate"
    workspace = dict((key, workspace) for key, _, workspace in ONBOARDING_STEPS)[current_step]

    return {
        "completed": completed,
        "completed_at": (persisted or {}).get("completed_at"),
        "completed_via": (persisted or {}).get("completed_via"),
        "current_step": current_step,
        "workspace": workspace,
        "steps": [
            {
                "key": key,
                "label": label,
                "workspace": item_workspace,
                "status": (
                    "active"
                    if key == current_step
                    else "complete"
                    if completed or ONBOARDING_STEPS.index((key, label, item_workspace))
                    < next(
                        index
                        for index, entry in enumerate(ONBOARDING_STEPS)
                        if entry[0] == current_step
                    )
                    else "upcoming"
                ),
            }
            for key, label, item_workspace in ONBOARDING_STEPS
        ],
        "recommended_action": onboarding_recommended_action(
            current_step=current_step,
            first_endpoint_candidate=first_endpoint_candidate,
        ),
    }
```

- [ ] **Step 4: Embed onboarding payloads into operator view builders**

```python
from aidn_hypervisor.operator_onboarding import build_onboarding_payload


def build_operator_home_payload(...):
    ...
    onboarding = build_onboarding_payload(
        wallet_ready=service.owner_wallet_state()["configured"],
        provider_count=service_payload.get("bootstrap", {}).get("provider_count", 0),
        bundle_count=service_payload.get("bootstrap", {}).get("bundle_count", 0),
        endpoint_items=endpoints_payload["items"],
        first_endpoint_candidate=service_payload.get("bootstrap", {}).get(
            "first_endpoint_candidate"
        ),
        persisted=service.operator_onboarding_state(),
    )
    return {
        "bootstrap": _build_operator_home_bootstrap_payload(...),
        "onboarding": onboarding,
        ...
    }


def build_operator_bundles_payload(*, service) -> dict:
    ...
    return {
        "owner_wallet": fleet["owner_wallet"],
        "node_identity": fleet["node_identity"],
        "onboarding": build_onboarding_payload(
            wallet_ready=fleet["owner_wallet"]["configured"],
            provider_count=len(service.plugins.list()),
            bundle_count=len(items),
            endpoint_items=[],
            first_endpoint_candidate=candidate,
            persisted=service.operator_onboarding_state(),
        ),
        "summary": {...},
        "items": items,
    }
```

- [ ] **Step 5: Add view-model tests for workspace guidance**

```python
def test_home_payload_exposes_onboarding_progress(service, endpoint_service) -> None:
    payload = build_operator_home_payload(
        service=service,
        endpoint_service=endpoint_service,
        endpoint_publication_service=None,
        validation_service=None,
        market_candidates=[],
    )

    assert payload["onboarding"]["current_step"] == "configure_wallet"
    assert payload["onboarding"]["recommended_action"]["action"] == "create-wallet"


def test_bundles_payload_marks_current_onboarding_workspace(service) -> None:
    service.configure_owner_wallet(mode="create", label="Primary Wallet")

    payload = build_operator_bundles_payload(service=service)

    assert payload["onboarding"]["workspace"] in {"providers", "bundles"}
    assert "steps" in payload["onboarding"]
```

- [ ] **Step 6: Run the onboarding and operator view tests**

Run: `pytest tests/test_operator_onboarding.py tests/test_operator_views.py -v`
Expected: PASS with onboarding progression and view payload assertions green.

- [ ] **Step 7: Commit the read-model slice**

```bash
git add src/aidn_hypervisor/operator_onboarding.py src/aidn_hypervisor/operator_views.py tests/test_operator_onboarding.py tests/test_operator_views.py
git commit -m "feat: derive canonical operator onboarding payloads"
```

---

### Task 3: Synchronize Dashboard API Flows With Onboarding Progress

**Files:**
- Modify: `src/aidn_hypervisor/api.py:860-897`
- Modify: `src/aidn_hypervisor/api.py` endpoint create/publish action handlers
- Modify: `tests/test_api.py`

- [ ] **Step 1: Write the failing API tests for onboarding-aware responses**

```python
def test_operator_dashboard_home_returns_onboarding_payload() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard/home")

    assert response.status_code == 200
    assert response.json()["onboarding"]["current_step"] == "configure_wallet"
    assert response.json()["onboarding"]["recommended_action"]["action"] == "create-wallet"


def test_endpoint_publish_refreshes_onboarding_completion_state() -> None:
    hypervisor = _service(whisper_endpoint="http://127.0.0.1:9000")
    hypervisor.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    client = TestClient(build_app(service=hypervisor, endpoint_service=endpoint_service))

    created = client.post(
        "/operators/endpoints",
        json={
            "owner_wallet": hypervisor.owner_wallet_state()["wallet_id"],
            "bundle_id": "whisper-a",
            "bundle_hash": "whisper-a",
            "display_name": "Operator STT",
            "model_class": "speech.stt",
            "capabilities": ["speech.stt"],
        },
    ).json()

    publish = client.post(
        f"/operators/endpoints/{created['endpoint']['endpoint_id']}/publish",
        json={},
    )

    assert publish.status_code == 200
    home = client.get("/operators/dashboard/home")
    assert home.json()["onboarding"]["completed"] is True
    assert home.json()["onboarding"]["current_step"] == "operate"
```

- [ ] **Step 2: Run the focused API tests to verify they fail**

Run: `pytest tests/test_api.py -k onboarding -v`
Expected: FAIL because the route payloads do not yet include `onboarding`, or publish actions do not refresh onboarding state.

- [ ] **Step 3: Refresh onboarding state from endpoint lifecycle routes**

```python
@router.get("/operators/dashboard/home")
async def operator_dashboard_home() -> dict:
    market = build_market_payload(
        service=service,
        registry_service=registry_service,
    )
    return build_operator_home_payload(
        service=service,
        endpoint_service=endpoint_service,
        endpoint_publication_service=endpoint_publication_service,
        validation_service=validation_service,
        market_candidates=market["candidates"],
    )


def _refresh_onboarding_from_endpoints() -> None:
    if endpoint_service is None:
        service.sync_operator_onboarding_state(endpoint_items=[])
        return
    endpoint_items = _operator_dashboard_endpoints_payload(
        service=service,
        endpoint_service=endpoint_service,
        endpoint_publication_service=endpoint_publication_service,
        validation_service=validation_service,
    )["items"]
    service.sync_operator_onboarding_state(endpoint_items=endpoint_items)
```

- [ ] **Step 4: Call the refresh helper after create and publish operations**

```python
created = endpoint_service.create_endpoint(command)
_refresh_onboarding_from_endpoints()
return _ok({"endpoint": created.endpoint.model_dump(mode="json")}, status_code=201)


publication = endpoint_publication_service.publish_endpoint(...)
_refresh_onboarding_from_endpoints()
return _ok(
    {
        "publication": publication.model_dump(mode="json"),
        "onboarding": service.operator_onboarding_state(),
    }
)
```

- [ ] **Step 5: Re-run the focused API tests**

Run: `pytest tests/test_api.py -k onboarding -v`
Expected: PASS with onboarding returned from the dashboard and publish flows advancing completion.

- [ ] **Step 6: Commit the API synchronization slice**

```bash
git add src/aidn_hypervisor/api.py tests/test_api.py
git commit -m "feat: synchronize onboarding across dashboard api flows"
```

---

### Task 4: Replace Loose Bootstrap Controls With A Guided Dashboard Layer

**Files:**
- Modify: `src/aidn_hypervisor/static/operator_dashboard.html:1519-1592`
- Modify: `src/aidn_hypervisor/static/operator_dashboard.html:2168-2201`
- Modify: `src/aidn_hypervisor/static/operator_dashboard.html:3045-3204`
- Modify: `src/aidn_hypervisor/static/operator_dashboard.html:6280-6365`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Write the failing shell assertions**

```python
def test_operator_dashboard_shell_route_exposes_guided_onboarding_sections() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert "Onboarding Progress" in response.text
    assert "Current Guided Step" in response.text
    assert "Return To Home After First Publish" in response.text
    assert 'data-screen-jump="providers"' in response.text
    assert 'data-screen-jump="bundles"' in response.text
    assert 'data-screen-jump="endpoints"' in response.text


def test_operator_dashboard_shell_route_mentions_validation_is_optional_after_publish() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert "Onboarding completes when the first local endpoint is published." in response.text
    assert "Validation stays optional and does not block completion." in response.text
```

- [ ] **Step 2: Run the shell tests to verify they fail**

Run: `pytest tests/test_api.py -k "guided_onboarding_sections or validation_is_optional_after_publish" -v`
Expected: FAIL because the current dashboard still renders the older bootstrap card and copy.

- [ ] **Step 3: Add onboarding UI state and render helpers**

```javascript
const state = {
  ...,
  onboardingDismissed: false,
};

function onboardingStepChip(step) {
  return `
    <div class="step-chip ${step.status}">
      <strong>${step.label}</strong>
      <span>${step.workspace}</span>
    </div>
  `;
}

function onboardingWorkspaceAction(onboarding) {
  const action = onboarding?.recommended_action || {};
  if (action.type === "screen") {
    return `<button class="primary-button action-focus" type="button" data-screen-jump="${action.action}">${action.label}</button>`;
  }
  return `<button class="primary-button action-focus" type="button" data-bootstrap-action="${action.action}">${action.label}</button>`;
}
```

- [ ] **Step 4: Replace the Home bootstrap card with a guided agenda**

```javascript
function renderHomeWorkspace() {
  const home = state.payloads.home || {};
  const onboarding = home.onboarding || {};
  const recommendation = onboarding.recommended_action || {};

  return `
    <div class="workspace-body">
      <div class="summary-grid">...</div>
      <div class="home-columns">
        <section class="subpanel">
          <div class="panel-heading">Onboarding Progress</div>
          <div class="notice">
            <strong>Current Guided Step</strong>
            <span style="display:block; margin-top:4px;">${onboarding.current_step || "configure_wallet"}</span>
          </div>
          <div class="chip-row" style="margin-top: 14px;">
            ${(onboarding.steps || []).map(onboardingStepChip).join("")}
          </div>
          <div class="notice" style="margin-top: 14px;">
            <strong>${recommendation.label || "Open Home"}</strong>
            <span style="display:block; margin-top:4px;">${recommendation.detail || "Follow the guided step highlighted above."}</span>
          </div>
          <div class="wallet-inline-actions" style="margin-top: 10px;">
            ${onboardingWorkspaceAction(onboarding)}
          </div>
          <div class="notice" style="margin-top: 14px;">
            Onboarding completes when the first local endpoint is published.
            Validation stays optional and does not block completion.
          </div>
        </section>
      </div>
    </div>
  `;
}
```

- [ ] **Step 5: Keep create/import/create-endpoint actions, but route completion back to `Home`**

```javascript
async function createBootstrapEndpointDraft() {
  ...
  try {
    const created = await postJson(endpointApiBase, payload);
    state.bootstrapMessage = {
      kind: "good",
      text: `Endpoint ${created.endpoint.endpoint_id} created for ${created.endpoint.bundle_id}.`,
    };
    state.currentScreen = "endpoints";
    await refreshBootstrapPayloads();
  } finally {
    ...
  }
}

async function publishSelectedEndpoint(endpointId) {
  ...
  try {
    await postJson(`${endpointApiBase}/${endpointId}/publish`, {});
    state.currentScreen = "home";
    await refreshBootstrapPayloads();
  } finally {
    ...
  }
}
```

- [ ] **Step 6: Run the shell and route tests**

Run: `pytest tests/test_api.py -k "dashboard_shell_route or onboarding" -v`
Expected: PASS with the new guided onboarding sections and onboarding-aware route payloads.

- [ ] **Step 7: Commit the UI slice**

```bash
git add src/aidn_hypervisor/static/operator_dashboard.html tests/test_api.py
git commit -m "feat: add guided dashboard onboarding layer"
```

---

### Task 5: Verify The Full Slice And Update The Roadmap State

**Files:**
- Modify: `ROADMAP.md`
- Modify: `docs/archive/specifications/2026-07-04-guided-dashboard-onboarding-design.md` (only if implementation drift requires a factual correction)

- [ ] **Step 1: Run the full relevant test matrix**

Run: `pytest tests/test_service.py tests/test_operator_onboarding.py tests/test_operator_views.py tests/test_api.py -v`
Expected: PASS with all onboarding, view-model, and dashboard route tests green.

- [ ] **Step 2: Run a local dashboard smoke check**

Run: `python -m uvicorn aidn_hypervisor.api:app --reload`
Expected: the operator dashboard loads, `Home` shows guided onboarding, wallet setup advances the step, first endpoint creation jumps to `Endpoints`, and first publication returns the operator to `Home` with onboarding completed.

- [ ] **Step 3: Update roadmap status after successful implementation**

```markdown
## M5 Operator Experience

- [x] Guided dashboard onboarding
  - `wallet -> provider -> bundle -> first endpoint -> publish`
  - persisted completion state
  - validation remains optional after first publish
```

- [ ] **Step 4: Commit the verification and roadmap update**

```bash
git add ROADMAP.md docs/archive/specifications/2026-07-04-guided-dashboard-onboarding-design.md
git commit -m "docs: record guided onboarding delivery"
```

---

## Self-Review

- Spec coverage check:
  - persisted onboarding state: Task 1
  - canonical derived onboarding model: Task 2
  - existing dashboard routes staying primary: Task 3
  - embedded guided layer in `Home`, `Providers`, `Bundles`, `Endpoints`: Task 4
  - completion on first local endpoint publish, validation optional: Tasks 1, 3, and 4
  - roadmap alignment and factual docs update: Task 5
- Placeholder scan:
  - no `TODO`, `TBD`, or “implement later” placeholders remain
  - every task includes explicit files, code snippets, commands, and expected results
- Type consistency:
  - persisted service API uses `operator_onboarding_state()` and `sync_operator_onboarding_state(...)`
  - view-model layer consumes `build_onboarding_payload(...)`
  - dashboard uses `home.onboarding` as the single UI payload surface
