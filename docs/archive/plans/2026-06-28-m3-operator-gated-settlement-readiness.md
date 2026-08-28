# M3 Operator-Gated Settlement Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the `M3` pricing and accounting boundary by adding `audio_minute` pricing, making settlement-readiness a first-class routing signal, and exposing operator-gated readiness policy through local, registry, and dashboard contracts.

**Architecture:** Reuse the existing capability catalog, registry advertisement, and operator requests policy surfaces instead of introducing a second accounting subsystem. Treat settlement readiness as a derived accounting profile computed from workload type, bundle pricing, and provider `usage_contract`, then use that profile consistently in local routing, spillover filtering, and operator UX.

**Tech Stack:** `Python`, `FastAPI`, `pytest`, `pydantic`, current `HypervisorService`, current registry discovery contract, current operator dashboard HTML shell, current wallet and settlement lifecycle code in `AiDN_0.1`.

---

## File Structure

- Modify: `src/aidn_hypervisor/registry_models.py`
  - Finalize the pricing contract (`audio_minute`) and bundle advertisement readiness fields.
- Modify: `src/aidn_hypervisor/wallet.py`
  - Quote `audio_minute` pricing without regressing current token-only quote payloads.
- Modify: `src/aidn_hypervisor/service.py`
  - Finalize bundle accounting profile derivation, settlement-readiness rules, policy-gated routing, and operator/dashboard payloads.
- Modify: `src/aidn_hypervisor/api.py`
  - Expose `require_settlement_ready` through agent and operator API contracts.
- Modify: `src/aidn_hypervisor/registry_service.py`
  - Preserve readiness metadata in nested and flattened discovery outputs without changing older fields unexpectedly.
- Modify: `src/aidn_hypervisor/plugins/base.py`
  - Ensure plugin `usage_contract()` contract clearly supports `billable_dimensions`.
- Modify: `src/aidn_hypervisor/plugins/whisper.py`
  - Publish the `audio_minutes` billable dimension and usable metering semantics.
- Modify: `src/aidn_hypervisor/plugins/ollama.py`
  - Verify token-oriented contracts publish token billable dimensions.
- Modify: `src/aidn_hypervisor/plugins/llamacpp.py`
  - Verify token-oriented contracts publish token billable dimensions.
- Modify: `src/aidn_hypervisor/dashboard.py`
  - Thread readiness flags and reasons into dashboard view-model payloads where needed.
- Modify: `src/aidn_hypervisor/static/operator_dashboard.html`
  - Show readiness badges/reasons and a settlement-ready policy toggle in operator-facing workflow surfaces.
- Modify: `tests/test_wallet.py`
  - Add quote and accounting-profile tests for `audio_minute` and readiness reasons.
- Modify: `tests/test_service.py`
  - Add service-level tests for capability catalog, routing gate behavior, and operator policy persistence.
- Modify: `tests/test_api.py`
  - Add API-level tests for agent constraints, operator requests policy, and dashboard payloads.
- Modify: `tests/test_registry_service.py`
  - Add registry discovery tests for readiness publication and filtering.
- Modify: `tests/test_registry_api.py`
  - Add registry API tests for flattened candidate readiness fields.
- Modify: `ROADMAP.md`
  - Move the immediate priority from “decide readiness boundary” to the next remaining item after verification.

## Task 1: Finalize Pricing Contract And Readiness Derivation

**Files:**
- Modify: `tests/test_wallet.py`
- Modify: `src/aidn_hypervisor/registry_models.py`
- Modify: `src/aidn_hypervisor/wallet.py`
- Modify: `src/aidn_hypervisor/service.py`
- Modify: `src/aidn_hypervisor/plugins/base.py`
- Modify: `src/aidn_hypervisor/plugins/whisper.py`
- Modify: `src/aidn_hypervisor/plugins/ollama.py`
- Modify: `src/aidn_hypervisor/plugins/llamacpp.py`

- [ ] **Step 1: Write failing quote and readiness tests**

```python
def test_quote_usage_q_includes_audio_charge_when_audio_pricing_is_present() -> None:
    quote = quote_usage_q(
        pricing={
            "unit": "q_per_1kk_tokens",
            "input": 12,
            "output": 18,
            "audio_minute": 30,
            "fixed_request": 4,
        },
        input_tokens=0,
        output_tokens=0,
        audio_seconds=120.0,
        fixed_request_count=0,
    )

    assert quote["charges"] == {
        "input_q": 0.0,
        "output_q": 0.0,
        "audio_q": 60.0,
        "fixed_q": 0.0,
        "total_q": 60.0,
    }


def test_service_bundle_accounting_profile_marks_whisper_not_ready_without_audio_pricing() -> None:
    service = _service(whisper_endpoint="http://127.0.0.1:9000")

    profile = service._bundle_accounting_profile(service.bundle("whisper-a"))

    assert profile["billable_dimensions"] == ["audio_minutes"]
    assert profile["settlement_ready"] is False
    assert profile["settlement_reason"] == "missing_audio_minute_pricing"
```

- [ ] **Step 2: Run the focused readiness tests and verify failure**

Run: `python -m pytest tests/test_wallet.py -k "audio_charge or missing_audio_pricing" -q`

Expected: `FAIL` because either the quote payload still omits audio accounting or the readiness profile does not yet derive the expected `speech_to_text` reason.

- [ ] **Step 3: Finalize the pricing contract in `registry_models.py`**

```python
class RegistryPricing(BaseModel):
    unit: str = "q_per_1kk_tokens"
    input: int = Field(ge=0)
    output: int = Field(ge=0)
    audio_minute: int | None = Field(default=None, ge=0)
    fixed_request: int | None = Field(default=None, ge=0)
```

```python
class RegistryBundleAdvertisement(BaseModel):
    bundle_id: str
    plugin_id: str
    workload_type: str
    provider_type: str
    model_id: str
    endpoint: str | None = None
    enabled: bool
    status: str
    launch_mode: str
    device_affinity: str
    max_parallel_requests: int
    supports_allocation: bool = True
    supports_queue: bool = True
    usage_contract: dict = Field(default_factory=dict)
    billable_dimensions: list[str] = Field(default_factory=list)
    settlement_ready: bool = False
    settlement_mode: str = "unsupported"
    settlement_reason: str | None = None
```

- [ ] **Step 4: Add `audio_minute` quoting while preserving token-only payload compatibility**

```python
def quote_usage_q(
    *,
    pricing: RegistryPricing | dict,
    input_tokens: int,
    output_tokens: int,
    audio_seconds: float = 0.0,
    fixed_request_count: int = 1,
) -> dict:
    normalized_pricing = (
        pricing if isinstance(pricing, RegistryPricing) else RegistryPricing(**pricing)
    )
    input_q = (input_tokens / _TOKENS_PER_UNIT) * normalized_pricing.input
    output_q = (output_tokens / _TOKENS_PER_UNIT) * normalized_pricing.output
    audio_q = 0.0
    if normalized_pricing.audio_minute is not None:
        audio_q = (
            float(audio_seconds) / _SECONDS_PER_AUDIO_MINUTE
        ) * normalized_pricing.audio_minute
    fixed_q = float((normalized_pricing.fixed_request or 0) * fixed_request_count)
    payload = WalletQuote(
        pricing=normalized_pricing,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        audio_seconds=audio_seconds,
        fixed_request_count=fixed_request_count,
        charges=WalletQuoteCharges(
            input_q=input_q,
            output_q=output_q,
            audio_q=audio_q,
            fixed_q=fixed_q,
            total_q=input_q + output_q + audio_q + fixed_q,
        ),
    ).model_dump(mode="json", exclude_none=True)
    if normalized_pricing.audio_minute is None and float(audio_seconds) == 0.0:
        payload["charges"].pop("audio_q", None)
    return payload
```

- [ ] **Step 5: Make provider contracts advertise billable dimensions explicitly**

```python
def usage_contract(self) -> dict:
    return {
        "supports_exact": True,
        "supports_estimated": False,
        "default_measurement_source": "provider_api",
        "fallback_measurement_source": None,
        "fallback_policy": "none",
        "missing_usage_behavior": "strict_accounting",
        "billable_dimensions": ["audio_minutes"],
    }
```

```python
def usage_contract(self) -> dict:
    return {
        "supports_exact": True,
        "supports_estimated": True,
        "default_measurement_source": "provider_api",
        "fallback_measurement_source": "provider_api_partial",
        "fallback_policy": "partial_response_estimate",
        "missing_usage_behavior": "skip",
        "billable_dimensions": ["input_tokens", "output_tokens", "fixed_request"],
    }
```

- [ ] **Step 6: Derive readiness from workload + pricing + usage contract**

```python
def _settlement_readiness_for_bundle(
    self,
    bundle: BundleConfig,
    *,
    usage_contract: dict,
    billable_dimensions: list[str],
) -> tuple[str, bool, str | None]:
    supports_measurement = bool(
        usage_contract.get("supports_exact") or usage_contract.get("supports_estimated")
    )
    settlement_mode = (
        "strict"
        if usage_contract.get("missing_usage_behavior") == "strict_accounting"
        else "best_effort"
    )
    if not supports_measurement:
        return settlement_mode, False, "missing_usage_measurement_support"

    if bundle.workload_type == "llm_text":
        if not any(
            dimension in billable_dimensions
            for dimension in ("input_tokens", "output_tokens", "fixed_request")
        ):
            return settlement_mode, False, "missing_token_pricing_dimension"
        return settlement_mode, True, None

    if bundle.workload_type == "speech_to_text":
        if "audio_minutes" not in billable_dimensions:
            return settlement_mode, False, "missing_audio_minute_dimension"
        if self._pricing.audio_minute is None:
            return settlement_mode, False, "missing_audio_minute_pricing"
        return settlement_mode, True, None

    return "unsupported", False, "unsupported_workload_accounting"
```

- [ ] **Step 7: Run the focused tests and verify they pass**

Run: `python -m pytest tests/test_wallet.py -k "audio_charge or missing_audio_pricing" -q`

Expected: `PASS`

- [ ] **Step 8: Commit the pricing and readiness derivation slice**

```bash
git add src/aidn_hypervisor/registry_models.py src/aidn_hypervisor/wallet.py src/aidn_hypervisor/service.py src/aidn_hypervisor/plugins/base.py src/aidn_hypervisor/plugins/whisper.py src/aidn_hypervisor/plugins/ollama.py src/aidn_hypervisor/plugins/llamacpp.py tests/test_wallet.py
git commit -m "feat: add pricing-backed settlement readiness derivation"
```

### Task 2: Add Agent And Operator Policy Gates To Routing

**Files:**
- Modify: `tests/test_service.py`
- Modify: `tests/test_api.py`
- Modify: `src/aidn_hypervisor/service.py`
- Modify: `src/aidn_hypervisor/api.py`

- [ ] **Step 1: Write failing service and API tests for settlement-ready gating**

```python
def test_service_capability_catalog_filters_not_ready_bundles_when_agent_requires_settlement_ready() -> None:
    service = _service(with_runtime=False, whisper_endpoint="http://127.0.0.1:9000")
    catalog = service.capability_catalog(
        owner_id="agent-a",
        workload_type="speech_to_text",
        require_settlement_ready=True,
    )

    assert catalog["bundles"] == []
```

```python
def test_operator_dashboard_requests_policy_endpoint_persists_settlement_ready_flag() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.post(
        "/operators/dashboard/requests/policy",
        json={
            "allow_spillover": True,
            "dispatch_strategy": "balanced",
            "ready_endpoint_only": False,
            "require_settlement_ready": True,
        },
    )

    assert response.status_code == 200
    assert response.json()["require_settlement_ready"] is True
```

- [ ] **Step 2: Run the focused gate tests and verify failure**

Run: `python -m pytest tests/test_service.py tests/test_api.py -k "require_settlement_ready" -q`

Expected: `FAIL` because either the catalog ignores the flag or the operator policy endpoint does not persist/return it.

- [ ] **Step 3: Extend the agent and operator API request models**

```python
class OperatorRequestsPolicyRequest(BaseModel):
    allow_spillover: bool = False
    dispatch_strategy: Literal["local_first", "balanced", "market_first"] = "local_first"
    ready_endpoint_only: bool = True
    require_settlement_ready: bool = False
```

```python
return service.capability_catalog(
    owner_id=owner_id,
    workload_type=workload_type,
    provider_type=provider_type,
    model_id=model_id,
    bundle_id=bundle_id,
    require_settlement_ready=bool(require_settlement_ready),
)
```

- [ ] **Step 4: Persist and expose the operator policy flag in the service**

```python
_DEFAULT_OPERATOR_REQUESTS_POLICY = {
    "allow_spillover": False,
    "dispatch_strategy": "local_first",
    "ready_endpoint_only": True,
    "require_settlement_ready": False,
}
```

```python
def operator_requests_policy(self) -> dict[str, bool | str]:
    return {
        "allow_spillover": bool(self._operator_requests_policy.get("allow_spillover")),
        "dispatch_strategy": str(
            self._operator_requests_policy.get("dispatch_strategy", "local_first")
        ),
        "ready_endpoint_only": bool(
            self._operator_requests_policy.get("ready_endpoint_only", True)
        ),
        "require_settlement_ready": bool(
            self._operator_requests_policy.get("require_settlement_ready", False)
        ),
    }
```

- [ ] **Step 5: Apply the gate in local catalog and market filtering**

```python
def capability_catalog(
    self,
    *,
    owner_id: str,
    workload_type: str | None = None,
    provider_type: str | None = None,
    model_id: str | None = None,
    bundle_id: str | None = None,
    require_settlement_ready: bool = False,
) -> dict:
    bundles = [
        self._catalog_entry(bundle, owner_id=owner_id)
        for bundle in self.bundles
        if self._bundle_matches_catalog_filters(
            bundle,
            workload_type=workload_type,
            provider_type=provider_type,
            model_id=model_id,
            bundle_id=bundle_id,
        )
    ]
    if require_settlement_ready:
        bundles = [bundle for bundle in bundles if bool(bundle.get("settlement_ready"))]
    return {
        "node": {
            "node_id": self.node_id,
            "operator_id": self.operator_id,
            "can_host_custom_model": self.can_host_custom_model,
            "pricing": self.pricing,
        },
        "resources": self.resources.summary(),
        "bundles": bundles,
    }
```

```python
if bool(policy.get("require_settlement_ready")):
    candidates = [
        candidate for candidate in candidates if bool(candidate.get("settlement_ready"))
    ]
```

- [ ] **Step 6: Run the focused gate tests and verify they pass**

Run: `python -m pytest tests/test_service.py tests/test_api.py -k "require_settlement_ready" -q`

Expected: `PASS`

- [ ] **Step 7: Commit the routing-gate slice**

```bash
git add src/aidn_hypervisor/service.py src/aidn_hypervisor/api.py tests/test_service.py tests/test_api.py
git commit -m "feat: gate routing on settlement readiness policy"
```

### Task 3: Publish Readiness Through Registry And Capability Contracts

**Files:**
- Modify: `tests/test_registry_service.py`
- Modify: `tests/test_registry_api.py`
- Modify: `tests/test_service.py`
- Modify: `src/aidn_hypervisor/service.py`
- Modify: `src/aidn_hypervisor/registry_service.py`

- [ ] **Step 1: Write failing registry and catalog publication tests**

```python
def test_service_capability_catalog_reports_settlement_metadata() -> None:
    service = _service(with_runtime=False, whisper_endpoint="http://127.0.0.1:9000")

    catalog = service.capability_catalog(owner_id="agent-a", workload_type="speech_to_text")

    assert catalog["bundles"][0]["billable_dimensions"] == ["audio_minutes"]
    assert catalog["bundles"][0]["settlement_ready"] is False
    assert catalog["bundles"][0]["settlement_reason"] == "missing_audio_minute_pricing"
```

```python
def test_registry_service_discovery_returns_settlement_metadata_in_flattened_candidates(monkeypatch) -> None:
    ready_time = datetime.fromisoformat("2026-06-19T18:30:05+00:00").timestamp()
    monkeypatch.setattr("aidn_hypervisor.registry_service.time.time", lambda: ready_time)
    service = RegistryService()
    service.upsert_node(_node("node-a", bundles=[_bundle("whisper-a", workload_type="speech_to_text")]))

    result = service.discover(RegistryDiscoveryQuery(workload_type="speech_to_text"))

    assert result["candidates"][0]["billable_dimensions"] == ["audio_minutes"]
    assert result["candidates"][0]["settlement_ready"] is False
    assert result["candidates"][0]["settlement_reason"] == "missing_audio_minute_pricing"
```

- [ ] **Step 2: Run the focused publication tests and verify failure**

Run: `python -m pytest tests/test_service.py tests/test_registry_service.py tests/test_registry_api.py -k "settlement_metadata or missing_audio_minute_pricing" -q`

Expected: `FAIL` because the current flattened candidate or catalog contract is missing one or more readiness fields.

- [ ] **Step 3: Publish settlement metadata from catalog and registry advertisement paths**

```python
payload = {
    "bundle_id": bundle.bundle_id,
    "plugin_id": bundle.plugin_id,
    "provider_type": bundle.provider_type,
    "model_id": bundle.model_id,
    "workload_type": bundle.workload_type,
    "enabled": bundle.enabled,
    "status": self._bundle_inventory_status(bundle),
    "endpoint": endpoint,
    "can_allocate_now": False,
    "can_queue": False,
    "allocation_mode": "unavailable",
    "reason": None,
    "required": required,
    "requires_runtime_start": runtime is None,
    "fit": self._catalog_fit(required),
    "usage_contract": accounting["usage_contract"],
    "billable_dimensions": accounting["billable_dimensions"],
    "settlement_ready": accounting["settlement_ready"],
    "settlement_mode": accounting["settlement_mode"],
    "settlement_reason": accounting["settlement_reason"],
}
```

```python
return RegistryBundleAdvertisement(
    bundle_id=bundle.bundle_id,
    plugin_id=bundle.plugin_id,
    workload_type=bundle.workload_type,
    provider_type=bundle.provider_type,
    model_id=bundle.model_id,
    endpoint=bundle.endpoint,
    enabled=bundle.enabled,
    status=self._bundle_registry_status(bundle),
    launch_mode=bundle.launch_mode,
    device_affinity=bundle.device_affinity,
    max_parallel_requests=bundle.max_parallel_requests,
    supports_allocation=True,
    supports_queue=True,
    usage_contract=accounting["usage_contract"],
    billable_dimensions=accounting["billable_dimensions"],
    settlement_ready=accounting["settlement_ready"],
    settlement_mode=accounting["settlement_mode"],
    settlement_reason=accounting["settlement_reason"],
)
```

- [ ] **Step 4: Preserve readiness metadata in registry storage and flattened candidates**

```python
def _flatten_candidates(self, nodes: list[dict]) -> list[dict]:
    candidates: list[dict] = []
    for node in nodes:
        for bundle in node["bundles"]:
            candidates.append(
                {
                    "node_id": node["node_id"],
                    "operator_id": node["operator_id"],
                    "status": node["status"],
                    "base_url": node["base_url"],
                    "resources": node["resources"],
                    "can_host_custom_model": node["can_host_custom_model"],
                    "pricing": node["pricing"],
                    "rating": node["rating"],
                    "bundle_id": bundle["bundle_id"],
                    "plugin_id": bundle["plugin_id"],
                    "provider_type": bundle["provider_type"],
                    "model_id": bundle["model_id"],
                    "workload_type": bundle["workload_type"],
                    "endpoint": bundle["endpoint"],
                    "endpoint_ready": self._bundle_endpoint_ready(bundle),
                    "supports_allocation": bundle["supports_allocation"],
                    "supports_queue": bundle["supports_queue"],
                    "billable_dimensions": bundle.get("billable_dimensions", []),
                    "settlement_ready": bool(bundle.get("settlement_ready")),
                    "settlement_mode": bundle.get("settlement_mode", "unsupported"),
                    "settlement_reason": bundle.get("settlement_reason"),
                }
            )
    candidates.sort(key=self._candidate_sort_key)
    return candidates
```

- [ ] **Step 5: Run the focused publication tests and verify they pass**

Run: `python -m pytest tests/test_service.py tests/test_registry_service.py tests/test_registry_api.py -k "settlement_metadata or missing_audio_minute_pricing" -q`

Expected: `PASS`

- [ ] **Step 6: Commit the publication slice**

```bash
git add src/aidn_hypervisor/service.py src/aidn_hypervisor/registry_service.py tests/test_service.py tests/test_registry_service.py tests/test_registry_api.py
git commit -m "feat: publish settlement readiness metadata"
```

### Task 4: Add Operator Dashboard Readiness UX

**Files:**
- Modify: `tests/test_api.py`
- Modify: `src/aidn_hypervisor/dashboard.py`
- Modify: `src/aidn_hypervisor/static/operator_dashboard.html`
- Modify: `ROADMAP.md`

- [ ] **Step 1: Write failing operator dashboard tests for readiness badges and policy toggle**

```python
def test_operator_dashboard_requests_policy_payload_includes_settlement_ready_toggle() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert "require_settlement_ready" in response.text
```

```python
def test_operator_dashboard_market_payload_exposes_settlement_badges() -> None:
    service = _service(with_runtime=False, whisper_endpoint="http://127.0.0.1:9000")

    payload = service.operator_dashboard_home()

    assert "settlement_ready" in json.dumps(payload)
    assert "settlement_reason" in json.dumps(payload)
```

- [ ] **Step 2: Run the focused dashboard tests and verify failure**

Run: `python -m pytest tests/test_api.py -k "settlement_ready_toggle or settlement_badges" -q`

Expected: `FAIL` because the current dashboard markup or payload does not yet surface readiness state clearly enough.

- [ ] **Step 3: Thread readiness fields into dashboard payloads**

```python
return {
    "bundle_id": bundle.bundle_id,
    "plugin_id": bundle.plugin_id,
    "provider_type": bundle.provider_type,
    "workload_type": bundle.workload_type,
    "model_id": bundle.model_id,
    "enabled": bundle.enabled,
    "endpoint": bundle.endpoint,
    "runtime_status": runtime.status if runtime is not None else "stopped",
    "publish_status": "ready_to_publish" if bundle.enabled else "disabled",
    "inventory_status": self._bundle_inventory_status(bundle),
    "registry_status": self._bundle_registry_status(bundle),
    "cooldown_until": state["cooldown_until"],
    "drain_mode": state["drain_mode"],
    "usage_contract": accounting["usage_contract"],
    "billable_dimensions": accounting["billable_dimensions"],
    "settlement_ready": accounting["settlement_ready"],
    "settlement_mode": accounting["settlement_mode"],
    "settlement_reason": accounting["settlement_reason"],
}
```

- [ ] **Step 4: Render explicit readiness badges and toggle controls in the dashboard HTML**

```html
<div class="policy-toggle-row">
  <label for="policy-settlement-ready">Require Settlement Ready</label>
  <input id="policy-settlement-ready" type="checkbox" />
</div>

<div class="bundle-readiness">
  <span class="bundle-badge" data-ready="{{ settlement_ready }}">
    {{ settlement_ready ? "Settlement Ready" : "Not Settlement Ready" }}
  </span>
  <span class="bundle-reason">{{ settlement_reason || settlement_mode }}</span>
</div>
```

- [ ] **Step 5: Update the roadmap after tests are green**

```markdown
- non-token pricing policy for `whisper`-class workloads is now published through `audio_minute`;
- provider `usage_contract` is now an operator-gated routing signal through settlement-readiness metadata;
- readiness metadata is exposed through capability catalog, registry discovery, and operator policy surfaces.
```

- [ ] **Step 6: Run the focused dashboard tests and then the full suite**

Run: `python -m pytest tests/test_api.py -k "settlement_ready_toggle or settlement_badges" -q`

Expected: `PASS`

Run: `python -m pytest -q`

Expected: `PASS`

- [ ] **Step 7: Commit the dashboard and roadmap slice**

```bash
git add src/aidn_hypervisor/dashboard.py src/aidn_hypervisor/static/operator_dashboard.html tests/test_api.py ROADMAP.md
git commit -m "feat: surface settlement readiness in operator dashboard"
```

## Self-Review

### Spec Coverage

The plan covers every major section of the spec:
- pricing contract: Task 1
- derived accounting profile: Task 1
- policy-aware routing gate: Task 2
- catalog and registry publication: Task 3
- operator-facing visibility: Task 4
- backward compatibility: Tasks 1-4 all preserve default-off routing
- rollout slices `A -> B -> C`: Tasks 1 -> 2/3 -> 4

No spec section is left without an implementation task.

### Placeholder Scan

This plan does not use:
- `TBD`
- `TODO`
- “add validation” without code
- “similar to previous task”
- unnamed file changes

Each task includes explicit files, concrete tests, exact commands, and concrete
code shapes.

### Type Consistency

The plan uses the same names throughout:
- `audio_minute`
- `billable_dimensions`
- `settlement_ready`
- `settlement_mode`
- `settlement_reason`
- `require_settlement_ready`

The readiness reasons are also consistent across tasks:
- `missing_usage_measurement_support`
- `missing_token_pricing_dimension`
- `missing_audio_minute_dimension`
- `missing_audio_minute_pricing`
- `unsupported_workload_accounting`
