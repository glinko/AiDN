# Runtime Readiness And Provider Broker Pipeline

Status: `Implemented broker jobs, runtime admission, scheduler, and live operations read model`
Last updated: `2026-08-21`

This document records the current operator-facing contracts for runtime
readiness and reviewed Provider runtime installation. It is deliberately
separate from the public Website specification: the Website consumes verified
read models, while this pipeline belongs to the node-local Hypervisor API.

## RFC-0072 Internal Event Bus

The Hypervisor now has one in-process `InternalEventBus` behind the existing
`service.record_event(...)` producer boundary. Legacy `JournalEvent` entries
remain unchanged for current operators and clients, while each new entry is
also normalised into a canonical RFC-0072 envelope with:

- a monotonic node-local sequence and stable event ID;
- `source`, resource identity, severity, data class, attention/action flags;
- optional correlation and causation IDs;
- recursively redacted credential fields and fully redacted `SECRET` payloads;
- a deterministic SHA-256 content hash.

The bus is thread-safe and isolates subscriber failures from authoritative
state transitions. A bounded Durable Event Store now persists the retained
canonical window and per-agent Inbox cursors in the normal Hypervisor snapshot.
Inbox reads are at-least-once: a read does not advance the acknowledgement
cursor, and the same event is returned until the agent explicitly acknowledges
its `event_id`. Acknowledgement is idempotent and advances only across a
contiguous sequence. Retention loss is surfaced as `cursor_status=stale`.

Operators can inspect the current canonical stream with:

```text
GET /operators/events/canonical?limit=100
```

Cursor and Inbox operations are available at:

```text
GET  /operators/events/query?after_sequence=0&limit=100
GET  /operators/events/inbox/{agent_id}
POST /operators/events/inbox/{agent_id}/ack
```

The same retained stream is available to a scoped MCP agent through
`aidn.event.query`, `aidn.event.inbox`, `aidn.event.ack`,
`aidn://events/recent`, and `aidn://events/inbox` under the existing
`AUDIT:READ` permission. The Inbox identity is taken from the active Control
Session; an agent cannot read or acknowledge another agent's Inbox.

## RFC-0072 Hook delivery baseline

The first Hook delivery slice is now implemented above the durable store. A
Hook is an operator-owned, declarative filter over event type, resource ID,
and/or minimum severity. `DURABLE_INBOX` delivery scopes the target agent's
Inbox so unrelated events are not exposed; `MCP_LIVE` delivery uses a live
adapter when one is registered and otherwise follows the same bounded retry
path.

Delivery is at-least-once and idempotent per `hook_id:event_id`. Attempts are
bounded (default three) and use exponential backoff. If the target remains
unavailable, the delivery becomes a durable dead letter instead of being
silently discarded. Operators can inspect and advance the queue with:

```text
GET  /operators/hooks
POST /operators/hooks
GET  /operators/hooks/deliveries
GET  /operators/hooks/dead-letters
POST /operators/hooks/dead-letters/{delivery_id}/retry
POST /operators/hooks/replay/{event_id}
POST /operators/hooks/dispatch
GET  /operators/hooks/metrics
GET  /operators/hooks/{hook_id}
POST /operators/hooks/{hook_id}/test
PATCH /operators/hooks/{hook_id}
DELETE /operators/hooks/{hook_id}
```

Hook definitions, delivery attempts, dead letters, metrics, and scoped Inbox
membership are part of the Hypervisor snapshot. `dispatch` is an explicit
reconciliation pulse, not a policy bypass or an unbounded worker. Signed
webhooks, runtime wake-up adapters, coalescing/hysteresis, and autonomous
recovery remain subsequent RFC-0072 slices. The MCP surface is available under
`HOOK:READ` for inspection and under operator-approved `HOOK:MANAGE` for
`aidn.hook.create`, `aidn.hook.update`, `aidn.hook.pause`,
`aidn.hook.resume`, `aidn.hook.delete`, `aidn.hook.test`, `aidn.hook.ack`,
`aidn.hook.replay`, and `aidn.hook.dead_letter_retry`. Mutating tools require
the normal plan/apply and idempotency boundary; a live event never grants
action authority. The Advanced Mode Automation workspace exposes the same
operator controls through the dashboard.

## Runtime readiness

`RuntimeHandle.status` describes the lifecycle of the process (`starting`,
`running`, `draining`, or `stopped`). `health_status` describes the latest
Provider probe. Neither field alone means that an inference API is usable.

The readiness projection is persisted on the runtime and reconciled from the
Provider plugin's diagnostic probe:

- `UNKNOWN`: no authoritative probe has completed yet;
- `READY`: the Provider API answered the plugin health check;
- `NOT_READY`: the process may exist, but the Provider API is unavailable or
  rejected the probe;
- `STOPPED`: the operator intentionally stopped the runtime;
- `FAILED`: the managed child process exited.

The canonical read endpoint is:

```text
GET /runtimes/{runtime_id}/readiness
```

It forces a bounded live probe and returns:

```json
{
  "runtime_id": "rt-1",
  "bundle_id": "bundle-qwen",
  "runtime_status": "running",
  "health_status": "healthy",
  "readiness": {
    "status": "READY",
    "code": "provider_healthy",
    "message": "provider runtime is ready",
    "checked_at": "2026-08-20T00:00:00Z",
    "diagnostic": {"healthy": true, "code": "provider_healthy"}
  },
  "endpoint": "http://127.0.0.1:8080",
  "model_id": "qwen-local",
  "last_error": null
}
```

Diagnostics are intentionally allowlisted and truncated before persistence.
The existing `/runtimes` and `/runtimes/{runtime_id}` responses remain
backward-compatible; clients that need readiness must use this explicit
endpoint.

## Runtime admission and listener allocation

Direct Bundle activation now passes through the local `ResourceOrchestrator`
before a managed child is spawned. The gate accounts for the Provider's cold
startup and resident profile together, returns `RESOURCE_ADMISSION_DENIED`
with required/free/shortfall details, and holds a `runtime:<bundle_id>`
residency reservation after admission. The task and allocation paths keep
their existing transient reservation and pass that fact to the lifecycle
facade so the same resources are not counted twice.

For managed local HTTP runtimes, `ProviderProcessManager` owns a
`RuntimePortAllocator`. The configured endpoint port is preferred; when it is
already bound (for example, a second llama.cpp instance requesting `8080`),
the allocator probes the local range and rewrites both the command's
`--port` argument and the runtime metadata to the selected port. A lease
survives `WARM_IDLE`/sleeping state and is released only when the runtime is
stopped, exits, or fails to spawn. The default range is `8000-8999` and can be
overridden with `AIDN_RUNTIME_PORT_START`/`AIDN_RUNTIME_PORT_END`.

Managed stdout and stderr are captured in bounded per-runtime files under
`AIDN_RUNTIME_LOG_DIR` (default:
`~/.local/share/aidn/runtimes/logs`). The readiness projection includes a
bounded `log_tail`; bind failures are classified as
`runtime_port_conflict` instead of the opaque generic exit code.

The first Resource Broker read model is now available without changing the
legacy `/resources` response shape:

```text
GET /resources/leases
GET /resources/forecast?cpu=1&ram_mb=1024&vram_mb=4096
GET /diagnostics/scheduler
```

`forecast` is side-effect free. It returns `ADMIT` or `RESOURCE_WAIT`, the
required/free/shortfall values, measured VRAM, and the active leases. The
scheduler diagnostic exposes the queue summary plus one candidate from every
independent Endpoint queue. Each candidate is classified as `RUNNABLE`,
`RESOURCE_WAIT`, `CONCURRENCY_WAIT`, `BLOCKED`, or
`ESTIMATE_UNAVAILABLE`; a resource-wait candidate also includes read-only
warm-runtime eviction hints. The execution boundary now consumes the same
candidate projection through a global reconciliation loop. Every queue change,
allocation lease release/expiry, and managed-runtime exit rebuilds all
independent queue heads; a fitting peer can run while a larger head is in
`RESOURCE_WAIT`, pending allocation leases are retried, and eligible warm-idle
runtimes are considered for eviction before the next pass. The loop stops at a
stable state and never lets an Agent bypass Resource Broker policy. A race
between the read-only fit check and the atomic lease lock is reported as a
retryable resource wait rather than a failed Provider task.

Operators can request an explicit pass with:

```text
POST /diagnostics/scheduler/reconcile
```

Agents with `RESOURCES:READ` can use `aidn.resources.forecast` and
`aidn.resources.leases` (the RFC-0073 aliases are
`aidn.resource_broker.forecast`, `aidn.resource_broker.leases`, and
`aidn.resource_broker.explain_denial`). Agents with `SCHEDULER:READ` can use
`aidn.scheduler.status`, `aidn.scheduler.queues`, and
`aidn.scheduler.candidates`, or read the matching MCP resources under
`aidn://resources/*`, `aidn://resource-broker/*`, and `aidn://scheduler/*`.
Agents explicitly granted `SCHEDULER:WRITE` may request the same
policy-respecting pass with the plan/apply tool `aidn.scheduler.reconcile`.

## Provider installation jobs

The root-owned broker remains the only host mutation boundary. The inventory
service now supports both modes:

- default `wait_for_completion=true`: preserve the existing request/response
  behavior;
- `wait_for_completion=false`: create a durable `QUEUED` job and dispatch the
  same reviewed broker invocation on the bounded installation executor.

The job stores a bounded event history (`progress_events`, at most 32 events),
`progress_percent`, `current_step`, `updated_at`, and `cancel_requested`. When
the reviewed runtime executor is connected to the root broker, the Hypervisor
also persists the broker job ID, terminal status, and the last consumed event
offset. The root broker stores its own bounded journal in a root-owned state
file, deduplicates submissions by `client_job_id + request_hash`, and exposes
only the following control operations over the existing UID-restricted socket:

```json
{"operation":"submit","client_job_id":"aidn:pij-...","argv":[...],"timeout_seconds":3600}
{"operation":"status","broker_job_id":"brj-...","after_offset":7}
{"operation":"cancel","broker_job_id":"brj-..."}
```

Every event has a monotonic `offset` and stable `event_id`. A status response
returns only events after `after_offset` and includes
`events_truncated_before` when the bounded journal has compacted older events;
the Hypervisor records an explicit replay-gap event before resuming. Repeating
`submit` with the same client job and request is idempotent; reusing the client
job ID for different argv is rejected.
The HTTP contract is:

```text
POST /operators/provider-installation-approvals/{approval_id}/apply
     {"wait_for_completion": false}
GET  /operators/provider-installation-jobs
GET  /operators/provider-installation-jobs/{job_id}
POST /operators/provider-installation-jobs/{job_id}/cancel
```

Dashboard Provider install/change requests accept the same
`wait_for_completion` field. Existing callers omit it and keep synchronous
behavior.

## Live operations read model

Runtime readiness and broker progress are exposed through one reconciled
projection so an operator or agent does not have to combine a cached provider
snapshot with a separate job poll. The projection reconciles managed process
health and reattaches non-terminal broker jobs before it is returned:

```text
GET /operators/dashboard/runtime-operations
aidn.runtime.operations
aidn://runtime/operations
```

The response contains a timestamped `generated_at`, a `freshness` boundary,
summary counters, per-runtime readiness records, and bounded Provider Broker
installation-job records. The established `aidn.provider.list` and
`/operators/dashboard/providers` read models include the same
`runtime_operations` field for clients that already cache the Provider tool
catalog. The React Provider workspace refreshes this projection every five
seconds and shows the freshness timestamp, runtime readiness, active tasks,
and install progress or failure without treating a stale snapshot as current.

The dedicated MCP tool/resource use `PROVIDER:READ`; they are read-only and do
not grant installation or runtime mutation authority. A reconciliation warning
is returned as bounded diagnostic data while the rest of the read model stays
available.

Cancellation is cooperative by design. A queued job can be canceled before
dispatch. A running root-owned action is never killed by the HTTP layer; the
request is forwarded to the broker's provider-runtime cancellation hook and
persisted as `cancel_requested=true`, and the final job state reflects what the
broker actually did. This prevents the UI from claiming a rollback when a
privileged installer already changed host state.

On Hypervisor restart, persisted jobs with a broker ID are reattached to the
same broker job and resume polling from the stored offset. If the broker itself
restarted, it marks every non-terminal action as `FAILED` with
`details.code=broker_restarted`, so a retry cannot silently duplicate a host
mutation. Jobs that never reached the broker are failed explicitly as
`hypervisor_restarted` rather than being replayed with a new request.

## Remaining hardening

The durable control protocol is now the default for asynchronous reviewed
runtime installs, and the live readiness/job projection is available to the
MCP and dashboard read models. Remaining work is operational: add
provider-specific interrupt hooks only where an installer can prove a safe
cancellation boundary, and collect restart and replay-gap evidence on Ubuntu
22.04/24.04.
