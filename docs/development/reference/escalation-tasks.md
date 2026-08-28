# Resident Steward Escalation Tasks

This is the implementation guide for the durable hand-off slice of RFC-0075.
An Escalation Task is a bounded request for larger reasoning; it is not a
remote execution session.

## Boundary

```text
Resident Steward
  -> Reasoning Router (read-only)
  -> EscalationTaskService (durable, bounded)
  -> larger provider (future adapter)
  -> typed plan
  -> operator approval / Hypervisor policy
  -> existing MCP action boundary
```

The current service deliberately stops before the provider call and before
execution. It stores enough state for a future adapter without giving a model
authority over the node.

## Task lifecycle

`CONTEXT_PREPARED` means a provider was selected. `WAITING_PROVIDER` means
the route was fail-closed and no eligible provider was available. A typed plan
enters `PLAN_READY` or `WAITING_APPROVAL`. The operator API moves an approved
plan to `APPROVED`; postcondition verification moves it to `COMPLETED` or
`FAILED`. Tasks expire after their bounded TTL and can be cancelled.

## API

The operator routes are:

```text
GET  /operators/dashboard/steward/escalations
POST /operators/dashboard/steward/escalations
GET  /operators/dashboard/steward/escalations/{task_id}
POST /operators/dashboard/steward/escalations/{task_id}/plan
POST /operators/dashboard/steward/escalations/{task_id}/approve
POST /operators/dashboard/steward/escalations/{task_id}/verify
POST /operators/dashboard/steward/escalations/{task_id}/cancel
```

Agents receive the non-executing subset through MCP:

```text
aidn.steward.escalations
aidn.steward.escalation.get
aidn.steward.escalate
aidn.steward.escalation.plan
aidn.steward.escalation.verify
aidn.steward.escalation.cancel
aidn://steward/escalations
```

`STEWARD:ESCALATE` does not include approval, lifecycle, wallet, shell, or
execution authority. A future plan executor must use the existing MCP
plan/apply and Resource Broker checks rather than adding a generic tool-call
endpoint.

## Data safety

Context is bounded by keys, nesting depth, item count, and string length.
Credential-looking keys are replaced with `[REDACTED]`; `SECRET` data class
is rejected. Plan actions contain a tool name and bounded arguments only.
Provider output must be treated as untrusted data and is not persisted as a
prompt transcript.

## Idempotency and plan binding

Creation requires `idempotency_key`. Retrying the same key and canonical input
returns the original task. Reusing it with different input returns
`ESCALATION_IDEMPOTENCY_CONFLICT`. Plan submission has its own idempotency key
and receives a `sha256:` plan hash. Operator approval must reference that
exact hash; a stale hash cannot be approved.

## Verification

Postconditions are declarative dot paths, for example:

```json
[{"path":"runtime.state","expected":"running"}]
```

Verification compares an observed bounded read model to every condition. It
does not perform a refresh or a mutation. The caller must obtain fresh state
from authoritative Hypervisor APIs before submitting observations.

## Advanced Mode dashboard

The operator dashboard's **Agents** workspace renders the read-only Steward
projection above the existing session view. It uses the same query boundary as
the operator API:

```text
GET /operators/dashboard/resident-agent
GET /operators/dashboard/steward/escalations?limit=64
```

The panel shows the Steward health/profile, active hand-off count, attention
states, and a bounded durable queue. Selecting a task opens a detail sheet with
its goal, route metadata, approval state, exact plan hash, typed actions, and
postcondition verification. The sheet deliberately has no execute control:
approval and execution remain separate lifecycle/MCP operations, and a missing
escalation read model is shown inline without turning the whole dashboard
refresh state into a failure for older Hypervisor nodes.
