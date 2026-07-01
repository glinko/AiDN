# M3 Settlement Lifecycle Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an operator-correctable settlement lifecycle with `hold`, `release`, and append-only correction journaling on top of the current wallet allocation finalization flow.

**Architecture:** Extend the existing wallet allocation event model rather than introducing a second settlement subsystem. Keep raw usage events immutable, add settlement-facing `base` and `effective` totals, persist a replay-safe correction stream, and expose operator write endpoints that enforce the new state machine.

**Tech Stack:** `Python`, `FastAPI`, `pytest`, `pydantic`, existing `HypervisorService`, existing wallet export stream contract, existing state snapshot persistence.

---

## File Structure

- Modify: `src/aidn_hypervisor/wallet_models.py`
  - Add hold/release/correction request models, correction event model, and expanded allocation event fields.
- Modify: `src/aidn_hypervisor/state.py`
  - Persist the new allocation event fields and the correction event stream through snapshot/restore.
- Modify: `src/aidn_hypervisor/service.py`
  - Add hold/release/correction service methods, correction export/list methods, strict-accounting auto-hold behavior, and reconcile rules that respect `hold`.
- Modify: `src/aidn_hypervisor/api.py`
  - Add wallet hold/release/correction/export endpoints.
- Modify: `tests/test_wallet.py`
  - Add service-level TDD coverage for hold transitions, correction semantics, reconcile behavior, strict-accounting auto-hold, and correction export.
- Modify: `tests/test_api.py`
  - Add API-level coverage for the new wallet endpoints and export route.
- Modify: `ROADMAP.md`
  - Mark settlement lifecycle hardening progress inside M3 after verification.
- Modify: `docs/superpowers/plans/2026-06-19-m3-wallet-pricing-and-usage-metering.md`
  - Sync the M3 sub-plan so the remaining work no longer describes the pre-hold model.

### Task 1: Extend Wallet Models And Persist Correction State

**Files:**
- Modify: `tests/test_wallet.py`
- Modify: `src/aidn_hypervisor/wallet_models.py`
- Modify: `src/aidn_hypervisor/state.py`

- [ ] **Step 1: Write the failing snapshot/model tests for hold and correction fields**

```python
def test_service_snapshot_and_restore_preserves_wallet_settlement_hold_and_corrections() -> None:
    service = _service()
    allocation = service.create_allocation(
        AllocationRequest(
            workload_type="llm_text",
            owner_id="agent-a",
            bundle_id="phi4-local",
        )
    )
    service.release_allocation(allocation["allocation_id"])
    event = service.list_wallet_allocation_events()[0]
    held = service.hold_wallet_allocation_event(
        event["event_id"], reason="manual review"
    )
    service.apply_wallet_allocation_correction(
        held["event_id"],
        reason="billing correction",
        effective_usage_total_q=0.0,
        annotations={"source": "ops"},
    )

    snapshot = service.snapshot_state()
    restored = _service()
    restored.restore_state(snapshot)

    restored_event = restored.list_wallet_allocation_events()[0]
    restored_correction = restored.list_wallet_allocation_correction_events()[0]

    assert restored_event["settlement_status"] == "hold"
    assert restored_event["hold_reason"] == "manual review"
    assert restored_event["effective_usage_total_q"] == 0.0
    assert restored_event["correction_count"] == 1
    assert restored_correction["reason"] == "billing correction"
    assert restored_correction["effective_usage_total_q_after"] == 0.0
```

- [ ] **Step 2: Run the focused snapshot test to verify it fails**

Run: `python -m pytest tests/test_wallet.py::test_service_snapshot_and_restore_preserves_wallet_settlement_hold_and_corrections -q`

Expected: `FAIL` with missing `hold_wallet_allocation_event`, missing correction event stream, or missing snapshot fields.

- [ ] **Step 3: Add the wallet request and event models**

```python
class WalletAllocationHoldRequest(BaseModel):
    reason: str = Field(min_length=1)


class WalletAllocationReleaseRequest(BaseModel):
    reason: str = Field(min_length=1)
    target_status: Literal["grace", "closed"]


class WalletAllocationCorrectionRequest(BaseModel):
    reason: str = Field(min_length=1)
    effective_usage_total_q: float = Field(ge=0.0)
    annotations: dict = Field(default_factory=dict)
    resolution_note: str | None = None
    release_after_apply: bool = False
    release_target_status: Literal["grace", "closed"] | None = None


class WalletAllocationCorrectionEvent(BaseModel):
    sequence_id: int = Field(ge=1)
    event_id: str
    correction_id: str
    allocation_event_id: str
    allocation_id: str
    owner_id: str
    node_id: str
    operator_id: str
    bundle_id: str
    workload_type: str
    occurred_at: str
    created_by: str
    reason: str
    base_usage_total_q: float = Field(ge=0.0)
    effective_usage_total_q_before: float = Field(ge=0.0)
    effective_usage_total_q_after: float = Field(ge=0.0)
    delta_q: float
    annotations: dict = Field(default_factory=dict)
    resolution_note: str | None = None
```

```python
class WalletAllocationEvent(BaseModel):
    sequence_id: int = Field(ge=1)
    event_id: str
    allocation_id: str
    owner_id: str
    node_id: str
    operator_id: str
    bundle_id: str
    workload_type: str
    status: Literal["released", "expired"]
    settlement_status: Literal["grace", "hold", "closed"]
    occurred_at: str
    hold_reason: str | None = None
    hold_source: Literal["manual", "dispute", "strict_accounting", "system"] | None = None
    hold_started_at: str | None = None
    hold_released_at: str | None = None
    grace_expires_at: str | None = None
    closed_at: str | None = None
    reopened_at: str | None = None
    reopen_reason: str | None = None
    reopen_count: int = Field(default=0, ge=0)
    dispute_id: str | None = None
    dispute_opened_at: str | None = None
    dispute_reason: str | None = None
    dispute_status: Literal["none", "open", "resolved"] = "none"
    dispute_opened_by: str | None = None
    dispute_resolved_at: str | None = None
    dispute_resolution: Literal["accepted", "rejected", "withdrawn"] | None = None
    dispute_resolution_reason: str | None = None
    usage_event_count: int = Field(ge=0)
    base_usage_total_q: float = Field(ge=0.0)
    effective_usage_total_q: float = Field(ge=0.0)
    correction_count: int = Field(default=0, ge=0)
```

- [ ] **Step 4: Persist the new wallet fields and correction stream through state snapshots**

```python
class WalletAllocationSnapshot(BaseModel):
    sequence_id: int = Field(ge=1)
    event_id: str
    allocation_id: str
    owner_id: str
    node_id: str
    operator_id: str
    bundle_id: str
    workload_type: str
    status: str
    settlement_status: str
    occurred_at: str
    hold_reason: str | None = None
    hold_source: str | None = None
    hold_started_at: str | None = None
    hold_released_at: str | None = None
    grace_expires_at: str | None = None
    closed_at: str | None = None
    reopened_at: str | None = None
    reopen_reason: str | None = None
    reopen_count: int = Field(default=0, ge=0)
    dispute_id: str | None = None
    dispute_opened_at: str | None = None
    dispute_reason: str | None = None
    dispute_status: str = "none"
    dispute_opened_by: str | None = None
    dispute_resolved_at: str | None = None
    dispute_resolution: str | None = None
    dispute_resolution_reason: str | None = None
    usage_event_count: int = Field(ge=0)
    base_usage_total_q: float = Field(ge=0.0)
    effective_usage_total_q: float = Field(ge=0.0)
    correction_count: int = Field(default=0, ge=0)
```

```python
class WalletAllocationCorrectionSnapshot(BaseModel):
    sequence_id: int = Field(ge=1)
    event_id: str
    correction_id: str
    allocation_event_id: str
    allocation_id: str
    owner_id: str
    node_id: str
    operator_id: str
    bundle_id: str
    workload_type: str
    occurred_at: str
    created_by: str
    reason: str
    base_usage_total_q: float = Field(ge=0.0)
    effective_usage_total_q_before: float = Field(ge=0.0)
    effective_usage_total_q_after: float = Field(ge=0.0)
    delta_q: float
    annotations: dict = Field(default_factory=dict)
    resolution_note: str | None = None
```

```python
class HypervisorStateSnapshot(BaseModel):
    tasks: list[TaskSnapshot] = Field(default_factory=list)
    runtimes: list[RuntimeSnapshot] = Field(default_factory=list)
    bundle_states: list[BundleStateSnapshot] = Field(default_factory=list)
    allocations: list[AllocationSnapshot] = Field(default_factory=list)
    model_installs: list[ModelInstallSnapshot] = Field(default_factory=list)
    operator_requests_policy: dict[str, bool | str] = Field(
        default_factory=lambda: {
            "allow_spillover": False,
            "dispatch_strategy": "local_first",
            "ready_endpoint_only": True,
        }
    )
    wallet_usage_events: list[WalletUsageSnapshot] = Field(default_factory=list)
    wallet_allocation_events: list[WalletAllocationSnapshot] = Field(default_factory=list)
    wallet_allocation_activation_events: list[WalletAllocationActivationSnapshot] = Field(
        default_factory=list
    )
    wallet_allocation_dispute_events: list[WalletAllocationDisputeSnapshot] = Field(
        default_factory=list
    )
    wallet_allocation_correction_events: list[WalletAllocationCorrectionSnapshot] = Field(
        default_factory=list
    )
    events: list[JournalEvent] = Field(default_factory=list)
```

- [ ] **Step 5: Thread correction persistence through `HypervisorService.snapshot_state()` and `restore_state()`**

```python
wallet_allocation_correction_events=[
    WalletAllocationCorrectionSnapshot(**event)
    for event in self._wallet_allocation_correction_events
],
```

```python
self._wallet_allocation_correction_events = [
    event.model_dump(mode="json")
    for event in snapshot.wallet_allocation_correction_events
]
self._next_wallet_allocation_correction_sequence = (
    max(
        (event["sequence_id"] for event in self._wallet_allocation_correction_events),
        default=0,
    )
    + 1
)
```

- [ ] **Step 6: Run the focused snapshot test to verify it passes**

Run: `python -m pytest tests/test_wallet.py::test_service_snapshot_and_restore_preserves_wallet_settlement_hold_and_corrections -q`

Expected: `PASS`

- [ ] **Step 7: Commit**

```bash
git add tests/test_wallet.py src/aidn_hypervisor/wallet_models.py src/aidn_hypervisor/state.py src/aidn_hypervisor/service.py
git commit -m "feat: persist settlement correction state"
```

### Task 2: Implement Service-Level Hold, Release, And Correction Semantics

**Files:**
- Modify: `tests/test_wallet.py`
- Modify: `src/aidn_hypervisor/service.py`

- [ ] **Step 1: Write failing service tests for hold transitions and correction rules**

```python
def test_service_hold_release_and_correction_flow_updates_effective_total(
    monkeypatch,
) -> None:
    current_time = [1_781_827_800.0]
    monkeypatch.setattr("aidn_hypervisor.service.time.time", lambda: current_time[0])
    service = _service(
        plugin=UsageMeteringPlugin(),
        bundle=_bundle("phi4-local", "llm_text").model_copy(
            update={
                "plugin_id": "fake-usage-metering",
                "endpoint": "http://127.0.0.1:8080",
            }
        ),
        wallet_allocation_grace_period_seconds=30,
    )
    allocation = service.create_allocation(
        AllocationRequest(
            workload_type="llm_text",
            owner_id="agent-a",
            bundle_id="phi4-local",
        )
    )
    service.submit(
        TaskRequest(
            task_type="llm_text.generate",
            payload={"prompt": "hello"},
            constraints={"allocation_id": allocation["allocation_id"]},
        )
    )
    service.release_allocation(allocation["allocation_id"])
    event = service.list_wallet_allocation_events()[0]

    held = service.hold_wallet_allocation_event(event["event_id"], reason="manual review")
    corrected = service.apply_wallet_allocation_correction(
        held["event_id"],
        reason="remove duplicated settlement charge",
        effective_usage_total_q=0.0,
        annotations={"reviewer": "ops"},
    )
    released = service.release_wallet_allocation_event(
        held["event_id"],
        reason="review complete",
        target_status="closed",
    )

    assert held["settlement_status"] == "hold"
    assert held["hold_reason"] == "manual review"
    assert corrected["effective_usage_total_q"] == 0.0
    assert corrected["base_usage_total_q"] > corrected["effective_usage_total_q"]
    assert corrected["correction_count"] == 1
    assert released["settlement_status"] == "closed"
    assert released["hold_released_at"] is not None
```

```python
def test_service_reconcile_skips_held_events_and_auto_holds_strict_accounting_blocked_tasks(
    monkeypatch,
) -> None:
    current_time = [1_781_827_800.0]
    monkeypatch.setattr("aidn_hypervisor.service.time.time", lambda: current_time[0])
    service = _service(
        plugin=StrictMissingUsageMeteringPlugin(),
        bundle=_bundle("phi4-local", "llm_text").model_copy(
            update={"plugin_id": "fake-strict-missing-usage-metering"}
        ),
        wallet_allocation_grace_period_seconds=30,
    )
    allocation = service.create_allocation(
        AllocationRequest(
            workload_type="llm_text",
            owner_id="agent-a",
            bundle_id="phi4-local",
        )
    )
    service.submit(
        TaskRequest(
            task_type="llm_text.generate",
            payload={"prompt": "hello"},
            constraints={"allocation_id": allocation["allocation_id"]},
        )
    )
    service.release_allocation(allocation["allocation_id"])

    event = dict(service.list_wallet_allocation_events()[0])
    current_time[0] += 31
    still_held = dict(service.list_wallet_allocation_events()[0])

    assert event["settlement_status"] == "hold"
    assert event["hold_source"] == "strict_accounting"
    assert still_held["settlement_status"] == "hold"
    assert still_held["closed_at"] is None
```

- [ ] **Step 2: Run the focused service tests to verify they fail**

Run: `python -m pytest tests/test_wallet.py -k "hold_release_and_correction_flow or reconcile_skips_held_events" -q`

Expected: `FAIL` with missing service methods and missing `hold` semantics.

- [ ] **Step 3: Add service state for correction events and helper accessors**

```python
self._wallet_allocation_correction_events: list[dict] = []
self._next_wallet_allocation_correction_sequence = 1
```

```python
def list_wallet_allocation_correction_events(
    self, *, limit: int | None = None
) -> list[dict]:
    events = list(self._wallet_allocation_correction_events)
    if limit is None or limit >= len(events):
        return events
    return events[-limit:]


def export_wallet_allocation_correction_events(
    self,
    *,
    after_event_id: str | None = None,
    after_sequence: int | None = None,
    limit: int = 100,
) -> dict:
    return self._export_wallet_event_stream(
        self._wallet_allocation_correction_events,
        after_event_id=after_event_id,
        after_sequence=after_sequence,
        limit=limit,
    )
```

```python
def _wallet_allocation_event_by_id(self, event_id: str) -> dict:
    event = next(
        (item for item in self._wallet_allocation_events if item["event_id"] == event_id),
        None,
    )
    if event is None:
        raise KeyError(event_id)
    return event
```

- [ ] **Step 4: Extend finalization payloads with base/effective totals and hold metadata**

```python
event = WalletAllocationEvent(
    sequence_id=self._next_wallet_allocation_sequence,
    event_id=str(uuid4()),
    allocation_id=str(allocation["allocation_id"]),
    owner_id=str(request["owner_id"]),
    node_id=self.node_id,
    operator_id=self.operator_id,
    bundle_id=str(allocation["bundle_id"]),
    workload_type=str(allocation["workload_type"]),
    status=status,
    occurred_at=datetime.now(timezone.utc).isoformat(),
    settlement_status="closed" if closed_immediately else "grace",
    hold_reason=None,
    hold_source=None,
    hold_started_at=None,
    hold_released_at=None,
    grace_expires_at=(
        None
        if closed_immediately
        else datetime.fromtimestamp(
            current_time + self.wallet_allocation_grace_period_seconds,
            timezone.utc,
        ).isoformat()
    ),
    closed_at=(
        datetime.fromtimestamp(current_time, timezone.utc).isoformat()
        if closed_immediately
        else None
    ),
    reopened_at=None,
    reopen_reason=None,
    reopen_count=0,
    dispute_id=None,
    dispute_opened_at=None,
    dispute_reason=None,
    dispute_status="none",
    dispute_opened_by=None,
    dispute_resolved_at=None,
    dispute_resolution=None,
    dispute_resolution_reason=None,
    usage_event_count=len(matching_usage_events),
    base_usage_total_q=sum(
        float(item["quote"]["charges"]["total_q"]) for item in matching_usage_events
    ),
    effective_usage_total_q=sum(
        float(item["quote"]["charges"]["total_q"]) for item in matching_usage_events
    ),
    correction_count=0,
)
```

- [ ] **Step 5: Implement hold, release, and correction service methods**

```python
def hold_wallet_allocation_event(self, event_id: str, *, reason: str) -> dict:
    self._reconcile_wallet_allocation_events()
    event = self._wallet_allocation_event_by_id(event_id)
    if event["settlement_status"] == "hold":
        raise ValueError(f"Wallet allocation event is already held: {event_id}")
    timestamp = datetime.fromtimestamp(time.time(), timezone.utc).isoformat()
    event["settlement_status"] = "hold"
    event["hold_reason"] = reason
    event["hold_source"] = "manual"
    event["hold_started_at"] = timestamp
    event["hold_released_at"] = None
    event["closed_at"] = None if event["settlement_status"] != "closed" else event["closed_at"]
    self.record_event(
        event_type="wallet.allocation_hold_started",
        message="wallet allocation settlement put on hold",
        bundle_id=event["bundle_id"],
        details={"event_id": event["event_id"], "reason": reason, "hold_source": "manual"},
    )
    self._persist_state()
    return dict(event)
```

```python
def release_wallet_allocation_event(
    self, event_id: str, *, reason: str, target_status: str
) -> dict:
    self._reconcile_wallet_allocation_events()
    event = self._wallet_allocation_event_by_id(event_id)
    if event["settlement_status"] != "hold":
        raise ValueError(f"Wallet allocation event is not held: {event_id}")
    if target_status == "closed" and event.get("dispute_status") == "open":
        raise ValueError(f"Wallet allocation event is disputed: {event_id}")
    timestamp = datetime.fromtimestamp(time.time(), timezone.utc).isoformat()
    event["settlement_status"] = target_status
    event["hold_released_at"] = timestamp
    event["hold_reason"] = reason
    if target_status == "grace":
        event["grace_expires_at"] = datetime.fromtimestamp(
            time.time() + self.wallet_allocation_grace_period_seconds,
            timezone.utc,
        ).isoformat()
        event["closed_at"] = None
    else:
        event["grace_expires_at"] = None
        event["closed_at"] = timestamp
    self.record_event(
        event_type="wallet.allocation_hold_released",
        message="wallet allocation settlement released from hold",
        bundle_id=event["bundle_id"],
        details={"event_id": event["event_id"], "reason": reason, "target_status": target_status},
    )
    self._persist_state()
    return dict(event)
```

```python
def apply_wallet_allocation_correction(
    self,
    event_id: str,
    *,
    reason: str,
    effective_usage_total_q: float,
    annotations: dict | None = None,
    resolution_note: str | None = None,
    release_after_apply: bool = False,
    release_target_status: str | None = None,
) -> dict:
    self._reconcile_wallet_allocation_events()
    event = self._wallet_allocation_event_by_id(event_id)
    if event["settlement_status"] != "hold":
        raise ValueError(f"Wallet allocation event is not held: {event_id}")
    before = float(event["effective_usage_total_q"])
    correction = WalletAllocationCorrectionEvent(
        sequence_id=self._next_wallet_allocation_correction_sequence,
        event_id=str(uuid4()),
        correction_id=str(uuid4()),
        allocation_event_id=event["event_id"],
        allocation_id=event["allocation_id"],
        owner_id=event["owner_id"],
        node_id=self.node_id,
        operator_id=self.operator_id,
        bundle_id=event["bundle_id"],
        workload_type=event["workload_type"],
        occurred_at=datetime.now(timezone.utc).isoformat(),
        created_by=self.operator_id,
        reason=reason,
        base_usage_total_q=float(event["base_usage_total_q"]),
        effective_usage_total_q_before=before,
        effective_usage_total_q_after=effective_usage_total_q,
        delta_q=effective_usage_total_q - before,
        annotations=dict(annotations or {}),
        resolution_note=resolution_note,
    ).model_dump(mode="json")
    self._wallet_allocation_correction_events.append(correction)
    self._next_wallet_allocation_correction_sequence += 1
    event["effective_usage_total_q"] = effective_usage_total_q
    event["correction_count"] = int(event["correction_count"]) + 1
    self.record_event(
        event_type="wallet.allocation_correction_applied",
        message="wallet allocation settlement correction applied",
        bundle_id=event["bundle_id"],
        details={
            "event_id": event["event_id"],
            "correction_id": correction["correction_id"],
            "reason": reason,
            "effective_usage_total_q_after": effective_usage_total_q,
        },
    )
    if release_after_apply and release_target_status is not None:
        self.release_wallet_allocation_event(
            event_id,
            reason=reason,
            target_status=release_target_status,
        )
    self._persist_state()
    return dict(event)
```

- [ ] **Step 6: Make dispute and strict-accounting flows auto-hold**

```python
event["settlement_status"] = "hold"
event["hold_source"] = "dispute"
event["hold_reason"] = event["dispute_reason"]
event["hold_started_at"] = timestamp
event["closed_at"] = None
```

```python
if self._allocation_has_blocked_wallet_accounting(event["allocation_id"]):
    event["settlement_status"] = "hold"
    event["hold_source"] = "strict_accounting"
    event["hold_reason"] = "strict_accounting_blocked"
    event["hold_started_at"] = event["hold_started_at"] or datetime.fromtimestamp(
        current_time, timezone.utc
    ).isoformat()
```

```python
def _allocation_has_blocked_wallet_accounting(self, allocation_id: str) -> bool:
    for task in self.queue.snapshot():
        if task.request.constraints.get("allocation_id") != allocation_id:
            continue
        result = self._task_results.get(task.task_id) or {}
        accounting = result.get("wallet_accounting")
        if accounting and accounting.get("settlement_status") == "blocked":
            return True
    return False
```

- [ ] **Step 7: Update reconcile logic so held events never auto-close and only base totals follow raw usage**

```python
if event["usage_total_q"] != next_usage_total_q:
    event["usage_total_q"] = next_usage_total_q
    event["base_usage_total_q"] = next_usage_total_q
    if int(event.get("correction_count", 0)) == 0:
        event["effective_usage_total_q"] = next_usage_total_q
    changed = True

if event.get("settlement_status") == "hold":
    continue
if dispute_open:
    continue
```

- [ ] **Step 8: Run the focused service tests to verify they pass**

Run: `python -m pytest tests/test_wallet.py -k "hold_release_and_correction_flow or reconcile_skips_held_events" -q`

Expected: `PASS`

- [ ] **Step 9: Commit**

```bash
git add tests/test_wallet.py src/aidn_hypervisor/service.py
git commit -m "feat: harden settlement lifecycle in service"
```

### Task 3: Add Wallet API Routes For Hold, Release, And Correction Export

**Files:**
- Modify: `tests/test_api.py`
- Modify: `src/aidn_hypervisor/api.py`

- [ ] **Step 1: Write the failing API tests for hold, release, correction, and correction export**

```python
def test_operator_wallet_hold_release_and_correction_endpoints() -> None:
    service = _service(
        plugin=UsageMeteringPlugin(),
        bundle=_bundle("phi4-local", "llm_text").model_copy(
            update={"plugin_id": "fake-usage-metering", "endpoint": "http://127.0.0.1:8080"}
        ),
    )
    allocation = service.create_allocation(
        AllocationRequest(workload_type="llm_text", owner_id="agent-a", bundle_id="phi4-local")
    )
    service.submit(
        TaskRequest(
            task_type="llm_text.generate",
            payload={"prompt": "hello"},
            constraints={"allocation_id": allocation["allocation_id"]},
        )
    )
    service.release_allocation(allocation["allocation_id"])
    event_id = service.list_wallet_allocation_events()[0]["event_id"]
    client = TestClient(build_app(service=service))

    hold = client.post(
        f"/operators/wallet/allocations/{event_id}/hold",
        json={"reason": "manual review"},
    )
    correction = client.post(
        f"/operators/wallet/allocations/{event_id}/corrections",
        json={
            "reason": "ops correction",
            "effective_usage_total_q": 0.0,
            "annotations": {"reviewer": "ops"},
            "release_after_apply": False,
            "release_target_status": None,
        },
    )
    release = client.post(
        f"/operators/wallet/allocations/{event_id}/release",
        json={"reason": "done", "target_status": "closed"},
    )
    export = client.get("/operators/wallet/allocations/corrections/export")

    assert hold.status_code == 200
    assert hold.json()["settlement_status"] == "hold"
    assert correction.status_code == 200
    assert correction.json()["effective_usage_total_q"] == 0.0
    assert release.status_code == 200
    assert release.json()["settlement_status"] == "closed"
    assert export.status_code == 200
    assert export.json()["items"][0]["reason"] == "ops correction"
```

```python
def test_operator_wallet_hold_endpoint_returns_409_for_invalid_transition() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.post(
        "/operators/wallet/allocations/missing/hold",
        json={"reason": "manual review"},
    )

    assert response.status_code == 404
```

- [ ] **Step 2: Run the focused API tests to verify they fail**

Run: `python -m pytest tests/test_api.py -k "hold_release_and_correction_endpoints or hold_endpoint_returns_409" -q`

Expected: `FAIL` with missing routes or missing request models.

- [ ] **Step 3: Add the new wallet endpoints**

```python
@router.get("/operators/wallet/allocations/corrections")
async def wallet_allocation_correction_events(limit: int = 100) -> list[dict]:
    return service.list_wallet_allocation_correction_events(limit=limit)


@router.get("/operators/wallet/allocations/corrections/export")
async def export_wallet_allocation_correction_events(
    after_event_id: str | None = None,
    after_sequence: int | None = None,
    limit: int = 100,
) -> dict:
    return service.export_wallet_allocation_correction_events(
        after_event_id=after_event_id,
        after_sequence=after_sequence,
        limit=limit,
    )
```

```python
@router.post("/operators/wallet/allocations/{event_id}/hold")
async def hold_wallet_allocation_event(
    event_id: str, request: WalletAllocationHoldRequest
) -> dict:
    try:
        return service.hold_wallet_allocation_event(event_id, reason=request.reason)
    except KeyError as error:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown wallet allocation event: {event_id}",
        ) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
```

```python
@router.post("/operators/wallet/allocations/{event_id}/release")
async def release_wallet_allocation_event(
    event_id: str, request: WalletAllocationReleaseRequest
) -> dict:
    try:
        return service.release_wallet_allocation_event(
            event_id,
            reason=request.reason,
            target_status=request.target_status,
        )
    except KeyError as error:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown wallet allocation event: {event_id}",
        ) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
```

```python
@router.post("/operators/wallet/allocations/{event_id}/corrections")
async def apply_wallet_allocation_correction(
    event_id: str, request: WalletAllocationCorrectionRequest
) -> dict:
    try:
        return service.apply_wallet_allocation_correction(
            event_id,
            **request.model_dump(mode="json"),
        )
    except KeyError as error:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown wallet allocation event: {event_id}",
        ) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
```

- [ ] **Step 4: Run the focused API tests to verify they pass**

Run: `python -m pytest tests/test_api.py -k "hold_release_and_correction_endpoints or hold_endpoint_returns_409" -q`

Expected: `PASS`

- [ ] **Step 5: Commit**

```bash
git add tests/test_api.py src/aidn_hypervisor/api.py src/aidn_hypervisor/wallet_models.py
git commit -m "feat: add wallet settlement correction api"
```

### Task 4: Verify Full M3.1 Slice And Sync Docs

**Files:**
- Modify: `ROADMAP.md`
- Modify: `docs/superpowers/plans/2026-06-19-m3-wallet-pricing-and-usage-metering.md`
- Modify: `tests/test_wallet.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Add the remaining regression tests for correction export ordering and release guards**

```python
def test_operator_wallet_correction_export_uses_replay_safe_sequence_cursor() -> None:
    service = _service()
    client = TestClient(build_app(service=service))

    response = client.get(
        "/operators/wallet/allocations/corrections/export",
        params={"after_sequence": 0, "limit": 10},
    )

    assert response.status_code == 200
    assert "items" in response.json()
    assert "next_after_sequence" in response.json()
    assert "cursor_status" in response.json()
```

```python
def test_service_release_wallet_hold_rejects_open_dispute(monkeypatch) -> None:
    current_time = [1_781_827_800.0]
    monkeypatch.setattr("aidn_hypervisor.service.time.time", lambda: current_time[0])
    service = _service(
        plugin=UsageMeteringPlugin(),
        bundle=_bundle("phi4-local", "llm_text").model_copy(
            update={
                "plugin_id": "fake-usage-metering",
                "endpoint": "http://127.0.0.1:8080",
            }
        ),
        wallet_allocation_grace_period_seconds=30,
    )
    allocation = service.create_allocation(
        AllocationRequest(
            workload_type="llm_text",
            owner_id="agent-a",
            bundle_id="phi4-local",
        )
    )
    service.submit(
        TaskRequest(
            task_type="llm_text.generate",
            payload={"prompt": "hello"},
            constraints={"allocation_id": allocation["allocation_id"]},
        )
    )
    service.release_allocation(allocation["allocation_id"])
    event_id = service.list_wallet_allocation_events()[0]["event_id"]
    service.hold_wallet_allocation_event(event_id, reason="manual review")
    service.dispute_wallet_allocation_event(event_id, reason="provider mismatch")
    with pytest.raises(ValueError, match="is disputed"):
        service.release_wallet_allocation_event(
            event_id,
            reason="close now",
            target_status="closed",
        )
```

- [ ] **Step 2: Run focused wallet and API suites**

Run: `python -m pytest tests/test_wallet.py -k "wallet allocation or correction or hold" -q`

Expected: `PASS`

Run: `python -m pytest tests/test_api.py -k "wallet and (correction or hold or release)" -q`

Expected: `PASS`

- [ ] **Step 3: Run the broader regression**

Run: `python -m pytest tests/test_wallet.py tests/test_service.py tests/test_api.py -q`

Expected: `PASS`

- [ ] **Step 4: Sync roadmap and M3 sub-plan**

```md
- settlement lifecycle hardening now supports held allocation settlement events, operator release actions, and replay-safe correction journaling without mutating usage history;
```

```md
### 1. Automatic Usage Metering And Allocation Closure

- [x] add `hold` settlement state and operator reconcile correction journal
- [x] replay-safe correction export stream
- [ ] decide whether adapter-declared `usage_contract` should become an enforced runtime capability gate for production bundles
- [ ] decide whether zero-grace nodes should remain audit-only on reopen or accepted dispute, or grow a separate late-adjustment window later
```

- [ ] **Step 5: Commit**

```bash
git add tests/test_wallet.py tests/test_api.py ROADMAP.md docs/superpowers/plans/2026-06-19-m3-wallet-pricing-and-usage-metering.md
git commit -m "docs: sync settlement lifecycle hardening delivery"
```
