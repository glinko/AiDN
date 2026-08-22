# Resident Steward event-to-action guard

This slice implements the first executable safety boundary from RFC-0075 for
the event-to-action path. It does not enable autonomous mutations. The
Hypervisor and MCP policy remain authoritative.

## What the guard does

`ResidentAgentService.guard_action()` is a claim-only operation. Before a
Steward proposes a recovery or configuration action it:

1. bounds the action, target, and event identifiers;
2. carries `event_id`, `event_type`, `correlation_id`, and `causation_id` into a
   lineage object (the source event is the default causation when no explicit
   causation is supplied);
3. rejects attempts whose `automation_depth` is above the local limit;
4. suppresses the same action/target during a bounded cooldown; and
5. records the guarded or blocked attempt in a bounded history.

The current default is deliberately conservative:

```text
MAX_AUTOMATION_DEPTH = 0
DEFAULT_ACTION_COOLDOWN_SECONDS = 30
MAX_ACTION_COOLDOWN_SECONDS = 3600
```

An `ACTION_GUARDED` result is not permission to execute anything. The caller
must still pass the ordinary Hypervisor/MCP scope, approval, lifecycle,
dependency, budget, and Resource Broker checks. A blocked result is a normal
control-plane outcome, not a provider failure.

## API

Operator/dashboard boundary:

```http
POST /operators/dashboard/steward/action-guard
```

Example request:

```json
{
  "action": "aidn.provider.restart",
  "target_id": "provider-1",
  "event_id": "evt-123",
  "event_type": "aidn.provider.failed",
  "correlation_id": "incident-7",
  "automation_depth": 0,
  "cooldown_seconds": 60
}
```

The response includes `allowed`, a typed `code`, the `lineage`, `action_id`,
and cooldown state. The operation only reserves the local guard slot; it does
not call `aidn.provider.restart`.

The Hypervisor also records `aidn.steward.action_guarded` or
`aidn.steward.action_blocked` with the action ID and causal linkage. If the
journal projection is temporarily unavailable, the guard result remains
usable and reports a null `guard_event_id` rather than turning a safety check
into an execution failure.

The read-only `POST /operators/dashboard/steward/decide` projection now also
returns the causal lineage and an explicit automation decision. If an event ID
matches the bounded recent event window, missing correlation/causation values
are recovered from that event rather than guessed by the client.

## MCP

Agents with the explicit `STEWARD:GUARD` scope can call:

```text
aidn.steward.action_guard
```

The tool is intentionally not included in the default read scopes. It is a
claim-only action-class tool and has no handler path to runtime, wallet,
filesystem, or external-provider mutation.

## Persistence and restart behavior

Cooldown entries and the bounded action history are included in the Resident
Steward snapshot. Expired entries are discarded on restore, and the snapshot
never recreates a provider process or a Resource Broker lease. This preserves
loop protection across a gateway/Hypervisor restart without making stale
cooldowns permanent.

## Future action execution

The next execution slice should pass the guard result into a typed action
envelope and then call the normal policy-gated service. The action envelope
must retain `action_id`, the causal lineage, and `automation_depth` so emitted
RFC-0072 events can point back to the exact guarded attempt.
