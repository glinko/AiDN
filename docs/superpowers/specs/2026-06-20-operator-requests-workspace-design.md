# Operator Requests Workspace Design

## Summary

This spec defines the first `Requests` workflow inside the AiDN operator dashboard.

The current dashboard already covers:
- `Home`
- `Fleet`
- `Market`
- inline `Wallet`

What is still missing is the operator surface for live workload flow control.

The new `Requests` workspace should let an operator:
- inspect queued, active, and recent tasks;
- understand current admission pressure;
- cancel work that is still in flight;
- set spillover intent for future routing;
- preview which market candidates are suitable when local execution should spill outward.

This is a real operator workflow, not a decorative dashboard tab.

## Design Decision

### Selected Direction

Build `Requests` as a full workspace mode inside the existing terminal dashboard shell.

This means:
- `Requests` becomes the first live secondary module in the left rail after `Wallet`;
- the center workspace becomes a task operations surface;
- the right inspector shows selected-task detail and actions;
- spillover policy lives inside the `Requests` mode as an operator control surface.

### Rejected Alternatives

#### A. Requests As A Drawer

Rejected because queue triage, active task inspection, admission telemetry, and task history need more horizontal space than the wallet drawer.

#### B. Lower-Band Queue Expansion

Rejected because it would produce a cramped mini-console and delay the real operator workflow we already know the product needs.

## Product Goals

The first `Requests` slice must let an operator:
- see which tasks are waiting, starting, running, or recently finished;
- inspect one task without leaving the main shell;
- cancel queued, admitted, starting, or running tasks through the existing task API;
- understand admission ordering pressure through current telemetry;
- set and review spillover policy for future dispatch decisions;
- preview market candidates that satisfy the current spillover policy.

## Non-Goals

This slice does not:
- migrate already-queued local tasks onto remote nodes;
- rebind a submitted task to a different bundle after it is accepted;
- implement automatic market spillover execution;
- become a full historical analytics surface;
- expose per-task "why it did not fit" diagnostics;
- replace `Market` as the canonical offer-comparison screen.

Those concerns belong to later orchestration milestones.

## Scope Boundary

The central rule for this slice is:

`Spillover policy is real, but spillover execution remains future-facing.`

That means:
- policy changes are persisted and visible;
- policy affects operator recommendations and future dispatch intent;
- policy drives a live spillover-preview shortlist;
- current queued tasks remain bound to their existing selected bundle.

The UI must communicate this honestly.

## Information Architecture

The dashboard shell remains intact:
- primary modes:
  - `Home`
  - `Fleet`
  - `Market`
- secondary modules:
  - `Requests`
  - `Models`
  - `Policies`
  - `Settings`

`Requests` should behave like an operator NOC screen inside the same shell rather than a separate application.

## Workspace Layout

The `Requests` mode should reuse the terminal dashboard composition:
- left command rail;
- top metrics strip;
- central workspace;
- right inspector;
- lower operational cards.

### Header

The workspace header must show:
- `Requests` title;
- concise copy explaining that this is the workload triage and dispatch-intent surface;
- compact spillover policy controls aligned to the right.

### Summary Cards

The top of the workspace should show four summary cards:
- `Queued`
- `Active`
- `Failed (Recent)`
- `Spillover Ready`

Purpose:
- expose queue pressure immediately;
- show whether failures are accumulating;
- show whether current market visibility could absorb future spillover.

### Main Task Surface

The main task surface uses tabs:
- `Queue`
- `Active`
- `Recent`
- `Admission`

#### Queue Tab

Shows tasks in:
- `queued`
- `admitted`
- `starting`

Each row should show:
- `task_type`
- selected `bundle_id`
- priority
- age
- status
- spillover eligibility badge

#### Active Tab

Shows tasks in:
- `running`

Each row should show:
- `task_type`
- selected `bundle_id`
- runtime or allocation context when available;
- started state;
- current status;
- wallet or accounting block hint when available from the task result.

#### Recent Tab

Shows recent tasks in:
- `completed`
- `failed`
- `cancelled`

The first slice should support simple status filtering and row selection.

#### Admission Tab

Shows the current admission telemetry rows in a compact compare-friendly table.

Each row should include:
- `task_id`
- `bundle_id`
- `effective_priority`
- `aging_bonus`
- `fair_share_round`
- `admission_rank`
- `selection_reason`

This tab is for operator reasoning, not end-user reporting.

## Right Inspector

Selecting a task row updates the right inspector.

The inspector must show:
- `task_id`
- `task_type`
- selected `bundle_id`
- status
- priority
- result if present;
- recovery reason if present;
- recent event history from the task journal.

Allowed actions:
- `Cancel Task` for tasks that are still in-flight;
- `Open Market Compare` for the spillover preview context;
- no destructive or fake actions beyond what current APIs support.

If the task is already terminal, the action area must explain why cancellation is unavailable.

## Spillover Policy Surface

The first slice includes a real operator policy surface inside `Requests`.

### Required Controls

- `Allow Spillover` toggle
- `Ready Endpoints Only` toggle
- `Dispatch Strategy` select with:
  - `Local First`
  - `Balanced`
  - `Market First`

### Meaning

These controls define operator intent for future routing behavior and spillover recommendations.

In this slice they do not:
- rewrite current queued tasks;
- trigger remote execution directly;
- override a task that was already admitted to a local runtime.

### Required Notice

The UI must state clearly:

`Affects future routing and spillover recommendations.`

This notice is a product requirement, not optional copy.

## Spillover Preview

The `Requests` mode should include a dedicated `Spillover Preview` block.

Purpose:
- show whether useful external capacity is visible right now;
- make policy changes feel concrete;
- connect local queue pressure to the market layer.

The preview should show a shortlist of 3-5 candidates that satisfy the current policy.

Each preview item should include:
- node or bundle identity;
- price;
- queue support;
- endpoint readiness;
- custom-model policy.

If no candidates fit the policy, the empty state must say that explicitly rather than showing a blank panel.

## Read Model Contract

Add a new endpoint:

- `GET /operators/dashboard/requests`

This route should aggregate the existing task APIs, queue snapshot, admission diagnostics, and market visibility into one UI-friendly payload.

### Shape

```json
{
  "summary": {
    "queued": 0,
    "active": 0,
    "completed_recent": 0,
    "failed_recent": 0,
    "admission_blocked": 0,
    "spillover_ready": 0
  },
  "queue": [],
  "active": [],
  "recent": [],
  "admission": [],
  "policy": {
    "allow_spillover": true,
    "dispatch_strategy": "balanced",
    "ready_endpoint_only": true
  },
  "market_spillover_preview": []
}
```

### Data Sources

- `queue` comes from current in-memory task state;
- `active` and `recent` should be derived from the same task state snapshot plus task journal/result state;
- `admission` comes from current admission diagnostics;
- `market_spillover_preview` comes from current market candidates filtered through the active policy.

## Backend Design Notes

The first slice should add a small operator-facing read model rather than inventing a second task system.

Preferred approach:
- add `operator_dashboard_requests()` on `HypervisorService`;
- keep policy state on the service as lightweight operator preferences;
- expose a small policy update endpoint only if the existing dashboard route set cannot carry writes cleanly.

The implementation should stay inside the current FastAPI plus static-shell architecture.

## Frontend Behavior

The static dashboard shell should:
- make the `Requests` button live in the left rail;
- switch the center workspace into the `Requests` mode;
- update the inspector on task-row selection;
- fetch task detail lazily when a row becomes selected;
- submit task cancellation through the current task API;
- submit policy changes immediately and reflect them in the preview.

The mode should feel as dense and deliberate as the rest of the terminal dashboard, not like a fallback admin table.

## Error Handling

The operator workflow must handle:
- missing task detail;
- cancellation conflicts;
- no spillover candidates;
- temporarily stale admission telemetry;
- policy update failure.

UI behavior should prefer:
- inline notices;
- non-blocking error banners;
- preserving current selection where possible.

The mode should not blank the whole workspace because one selected-task request fails.

## Testing Requirements

The first implementation pass must cover:
- dashboard shell contract for a live `Requests` control;
- `GET /operators/dashboard/requests` payload shape and status grouping;
- policy persistence and policy echo in the requests read model;
- spillover preview filtering against policy state;
- selected-task inspection behavior through the current task detail route;
- task cancellation flow;
- browser verification that:
  - `Requests` opens correctly;
  - tab switching works;
  - task selection updates the inspector;
  - policy controls update visible preview state.

## Rollout Standard

This slice is acceptable only if:
- the operator can triage tasks without leaving the main shell;
- the UI is explicit about future-vs-current spillover behavior;
- the new mode looks native to the terminal dashboard direction;
- no fake operator actions remain that imply remote rerouting already exists.

## Related Documents

- Base dashboard architecture: [2026-06-20-operator-fleet-market-dashboard-design.md](./2026-06-20-operator-fleet-market-dashboard-design.md)
- Terminal redesign: [2026-06-20-operator-dashboard-terminal-redesign-design.md](./2026-06-20-operator-dashboard-terminal-redesign-design.md)
- Wallet and pricing architecture: [2026-06-19-network-registry-wallet-rating-design.md](./2026-06-19-network-registry-wallet-rating-design.md)
