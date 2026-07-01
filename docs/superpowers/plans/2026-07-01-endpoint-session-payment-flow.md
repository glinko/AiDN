# Endpoint Session And Payment Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add session-based paid endpoint execution with deposit lock, endpoint session policy, session-scoped execution, idle billing, and refund-oriented settlement.

**Architecture:** Build a new session domain above the current endpoint-first and wallet-accounting layers. Keep endpoint configuration/publication as the trust and discovery layer, keep task queue/runtime control as the execution substrate, and introduce Sessions as the commercial reservation unit between them.

**Tech Stack:** Python, FastAPI, Pydantic, existing endpoint-first package, wallet accounting/export layer, operator dashboard HTML/JS, pytest

---

## File Structure

### New Files

- `src/aidn_hypervisor/sessions/models.py`
  - session policy, session record, deposit lock, settlement snapshot
- `src/aidn_hypervisor/sessions/store.py`
  - persisted session and deposit records
- `src/aidn_hypervisor/sessions/service.py`
  - open/close/session lifecycle orchestration
- `tests/sessions/test_models.py`
  - policy and session model validation
- `tests/sessions/test_service.py`
  - open/close, slot reservation, queue/busy policy

### Existing Files To Modify

- `src/aidn_hypervisor/endpoints/models.py`
  - add endpoint session policy contract
- `src/aidn_hypervisor/endpoints/service.py`
  - update endpoint configuration flows to persist session policy
- `src/aidn_hypervisor/endpoint_publications/models.py`
  - include session policy in the public commercial contract
- `src/aidn_hypervisor/api.py`
  - add session open/list/detail/close routes
- `src/aidn_hypervisor/service.py`
  - bind paid requests to `session_id` and session-aware settlement attribution
- `src/aidn_hypervisor/state.py`
  - extend root snapshot with session and deposit state
- `src/aidn_hypervisor/static/operator_dashboard.html`
  - add operator-facing session panel, deposit confirmation, and slot-state visibility
- `tests/test_api.py`
  - cover session lifecycle and dashboard session payloads
- `tests/test_persistence.py`
  - session/deposit round-trip persistence
- `ROADMAP.md`
  - mark checkpoint progress when implementation lands

---

## Milestone Breakdown

### Phase 1: Session Policy Contract

Outcome:
- endpoints can publish session policy alongside pricing and runtime metadata.

Tasks:
- add session policy fields to endpoint model
- expose session policy through `/api/v1/endpoints`
- include session policy in endpoint publication payload and proof shape
- show session policy on dashboard endpoint detail

Acceptance:
- endpoint payload includes `minimum_deposit`, `recommended_deposit`, `idle_timeout`, `idle_fee_per_minute`, `max_concurrent_sessions`, and `maximum_session_duration`
- publication hash rules remain explicit about whether session policy is execution-relevant commercial contract

### Phase 2: Session Open And Close Lifecycle

Outcome:
- clients can reserve and release a paid endpoint slot explicitly.

Tasks:
- add `EndpointSession` and `LockedDeposit` models
- implement session open route
- enforce minimum deposit
- assign active slot or queue/busy result depending on endpoint policy
- implement manual close route
- persist session status transitions

Acceptance:
- opening a session below minimum deposit is rejected
- opening a session on a saturated endpoint obeys queue policy
- closing a session releases its slot deterministically

### Phase 3: Session-Scoped Execution

Outcome:
- paid endpoint requests execute only through an active Session.

Tasks:
- extend task request contract with `session_id`
- validate session ownership and active state before execution
- map execution usage into session totals
- ensure proxy and remote paths can still attach usage to the correct session

Acceptance:
- request without valid session is rejected for paid endpoint path
- usage totals accrue against the active session
- session state updates `last_activity_at`

### Phase 4: Settlement, Refund, And No-Request Fee

Outcome:
- session closure produces provider payout and client refund decisions.

Tasks:
- add session settlement summary model
- compute usage spend from metered events
- apply no-request minimum session fee
- compute refund remainder from locked deposit
- emit wallet-facing deposit lock, payout, and refund journal events

Acceptance:
- no-request session pays minimum fee and refunds the remainder
- used session pays actual usage plus policy fees and refunds unused balance
- strict-accounting failures produce explicit blocked closure state instead of silent corruption

### Phase 5: Idle Billing And Saturation UX

Outcome:
- sessions reflect idle reservation value explicitly to both operator and client.

Tasks:
- implement idle timer updates
- accrue idle fee based on endpoint policy
- auto-close abandoned sessions on timeout
- expose active/queued/idle sessions in dashboard
- add deposit confirmation UX before session open

Acceptance:
- idle timeout closes the session automatically
- idle charge appears in session settlement
- operator can inspect slot occupancy and queued demand
- client sees deposit, idle fee, and timeout before confirming

---

## Recommended Build Order

1. `sessions/models.py` + tests
2. endpoint session policy model updates
3. `sessions/store.py` and persistence wiring
4. `sessions/service.py` open/close lifecycle
5. API routes and endpoint payload exposure
6. task/session binding in runtime service
7. wallet event extensions for deposit/refund/payout
8. dashboard session UX

---

## Key Risks

- Session semantics may overlap awkwardly with current allocation lease behavior if boundaries are not kept explicit.
- Idle billing can become surprising UX if confirmation surfaces are weak.
- Missing provider usage data is more dangerous once funds are pre-locked, so strict-accounting behavior needs explicit session outcomes.
- Proxy and remote execution paths may require additional session propagation design if the remote endpoint is also paid.

---

## Explicit Deferrals

This plan does not yet implement:
- on-chain escrow mechanics;
- multi-hypervisor marketplace session brokering;
- validator-specific session economics;
- delegated session sponsorship by third-party wallets;
- revenue sharing across proxy hops.

---

## Immediate Next Coding Slice

Recommended first implementation batch:

1. add endpoint session policy fields to endpoint models and publications
2. add session models/store/service with open/close lifecycle
3. expose `POST /api/v1/endpoints/{endpoint_id}/sessions` and `POST /api/v1/sessions/{session_id}/close`
4. add dashboard policy visibility before building full session console

This gives the project a real `M4` skeleton quickly without prematurely coupling all wallet and execution paths.
