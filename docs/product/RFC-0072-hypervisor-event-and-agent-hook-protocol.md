# RFC-0072 — AiDN Hypervisor Event and Agent Hook Protocol

Status: Draft

Version: 0.1

Category: Hypervisor / Agent Control Plane

Depends on:

- MCP-0001 AiDN Node Control MCP Server
- RFC-0042 Network Dispatcher
- RFC-0054 Capability Runtime Protocol
- RFC-0056 Provider Lifecycle Management
- RFC-0060 Endpoint Lifecycle
- RFC-0062 Validation Framework
- RFC-0069 Bundle Architecture
- UI-0001 Hypervisor Dashboard Specification

## 1. Purpose

This RFC defines the AiDN Hypervisor event and hook system. It allows a
Hypervisor to proactively notify authorized agents about relevant changes
without requiring agents to continuously poll Hypervisor state.

Examples include:

- node health and network synchronization changes;
- GPU, memory, storage, or network pressure;
- Provider failures and recovery;
- model deployment and materialization completion;
- Bundle, Runtime Binding, and Endpoint state changes;
- validation events;
- session, wallet, budget, Faucet, upgrade, and recovery events;
- operator approval requirements and long-running job progress.

The protocol SHALL support connected and temporarily disconnected agents.

## 2. Core Principle

MCP provides agent-to-Hypervisor control. Hooks provide Hypervisor-to-agent
event delivery.

    Agent
      | MCP tools
      v
    Hypervisor
      | Events / Hooks
      v
    Agent

Together they form a bidirectional control loop:

    observe event -> reason -> plan -> MCP action
        -> Hypervisor change -> new event

## 3. Hooks Do Not Grant Authority

Receiving a Hook SHALL NOT grant permission to perform any action. A
subsequent MCP action is still checked against the Agent Control Session,
scopes, operator policy, approval requirements, financial budget, and node
safety rules.

Event visibility is not action authority.

## 4. Architecture

Subsystems publish to one internal Event Bus. Events are normalized, filtered
and redacted, then delivered by the Hook Dispatcher:

    Node / Provider / Model / Bundle / Endpoint / Resource / Network / MCP
                                  |
                            Internal Event Bus
                                  |
                            Event Normalizer
                                  |
                         Policy and Redaction Layer
                                  |
                            Hook Dispatcher
                       /          |          \
                    MCP live   Durable     Webhook / adapter
                               Inbox

## 5. Internal Event Bus

All Hypervisor subsystems SHALL publish events to the internal bus. Producers
MAY use subsystem-specific formats, but every externally visible event MUST be
converted to the canonical AiDN Event Envelope before delivery.

## 6. Event Envelope

Every externally visible event SHALL contain:

    event:
      event_id:
      event_type:
      event_version:
      hypervisor_id:
      network_id:
      timestamp:
      sequence:
      source:
      resource_type:
      resource_id:
      resource_revision:
      severity:
      data_class:
      correlation_id:
      causation_id:
      requires_attention:
      requires_action:
      payload:
      event_hash:

The payload MAY contain typed domain fields, trusted action hints, and
explicitly marked untrusted provider or network text.

## 7. Event ID

Every event SHALL have a globally unique Event ID. A recommended derivation is:

    HASH(HypervisorID + EventSequence + EventType + EventTimestamp)

Agents SHALL deduplicate deliveries by event_id.

## 8. Sequence Number

The Hypervisor SHALL maintain monotonically increasing event sequences. A
global sequence SHOULD be used; resource-specific sequences MAY additionally
be maintained so agents can detect gaps for a particular Bundle, Provider, or
Endpoint.

## 9. Event Type Namespace

Event types SHALL use hierarchical names such as:

    aidn.node.ready
    aidn.provider.failed
    aidn.bundle.activated
    aidn.validation.failed

## 10. Severity

The allowed severities are DEBUG, INFO, NOTICE, WARNING, ERROR, and CRITICAL.
Severity represents operational importance and does not imply permission to act.

## 11. Data Classes

Every event SHALL declare one data class:

    PUBLIC | OPERATOR | SENSITIVE | FINANCIAL | SECURITY | SECRET

SECRET events MUST NOT be delivered through ordinary Hook payloads. They may
only contain references to secret handles.

## 12. Hook Definition

A Hook is a persistent or temporary event subscription:

    hook:
      hook_id:
      owner_operator_id:
      target_agent_id:
      enabled:
      event_filter:
      delivery:
        mode:
        destination:
      payload_profile:
      severity_minimum:
      throttle_policy:
      retry_policy:
      acknowledgment_policy:
      created_at:
      expires_at:
      hook_revision:

## 13. Hook Ownership

Hooks SHALL belong to an operator identity. An agent MAY create or modify a
Hook only with HOOK:MANAGE and only within its own visibility scope. A Hook
MUST NOT expose resources, data classes, or agents outside that scope.

## 14. Event Filters

Hooks SHALL support declarative filters by event type, resource, and minimum
severity:

    event_filter:
      event_types:
        - aidn.provider.failed
        - aidn.bundle.validation_required
      resource_ids:
        - provider-123
        - bundle-456
      severity:
        minimum: WARNING

## 15. Filter Expressions

Advanced profiles MAY support sandboxed declarative expressions such as:

    event.resource_type == "GPU"
    AND event.payload.temperature_c > 85

Arbitrary executable code SHALL NOT be permitted in filters.

## 16. Delivery Modes

The initial protocol supports:

    MCP_LIVE
    DURABLE_INBOX
    SIGNED_WEBHOOK

LOCAL_IPC, NATS, MQTT, AMQP, and AGENT_RUNTIME_ADAPTER are future adapters.

## 17. MCP Live Delivery

With an active MCP Control Session, matching events MAY be delivered through
the MCP transport as a notification:

    {
      "method": "aidn.event",
      "params": {
        "event_id": "evt_123",
        "event_type": "aidn.provider.failed",
        "payload": {}
      }
    }

MCP_LIVE is the preferred low-latency mode for connected agents.

## 18. MCP Live Session Loss

When the MCP session disconnects, live delivery is unavailable. Events
configured as durable SHALL remain in the Durable Inbox. Critical events
SHOULD NOT disappear merely because an agent process or gateway restarted.

## 19. Durable Inbox

Each authorized agent MAY have a persistent Event Inbox. Agents read events
with a cursor:

    GET events after cursor 15420

The cursor and acknowledgments are independent of a transport session.

## 20. Inbox Retention

Retention SHALL be configurable by time, count, or acknowledgment state:

    TIME_BASED | COUNT_BASED | ACK_BASED

Critical audit-related events MAY use a longer retention policy.

## 21. Signed Webhook

A Hook MAY deliver an event to an HTTPS callback:

    POST https://agent.example/hooks/aidn

    {
      "event": {},
      "delivery": {
        "hook_id": "hook_123",
        "delivery_id": "delivery_987",
        "attempt": 1
      }
    }

## 22. Webhook Authentication

Webhook delivery SHALL be authenticated using HMAC-SHA256, Ed25519 signatures,
or mTLS. Recommended headers are:

    AiDN-Event-ID
    AiDN-Hook-ID
    AiDN-Timestamp
    AiDN-Signature

The signature SHALL cover the timestamp and canonical event payload.

## 23. Replay Protection

Webhook receivers SHALL reject timestamps outside the configured acceptance
window unless replay was explicitly requested. event_id remains the
deduplication key.

## 24. Webhook Destination Security

The Hypervisor SHALL protect against SSRF and unsafe callbacks. Implementations
SHOULD provide destination allowlists, DNS re-resolution checks, private-address
restrictions, TLS verification, redirect limits, payload limits, and bounded
outbound timeouts.

## 25. Agent Runtime Adapter

An Agent Runtime Adapter MAY translate events for runtimes that cannot expose an
incoming HTTP endpoint:

    Hook Dispatcher -> Hermes Adapter -> Hermes Runtime
    Hook Dispatcher -> Claw Adapter   -> Claw Agent

Adapters do not change core Hook semantics or grant authority.

## 26. Agent Wake-Up

A runtime adapter MAY wake an inactive agent and include the event context.
Wake-up SHALL NOT imply elevated permissions.

## 27. Delivery Semantics

The default guarantee is AT_LEAST_ONCE. Events may be delivered more than once,
and agents MUST deduplicate by event_id. Exactly-once delivery SHALL NOT be
assumed.

## 28. Acknowledgment

Durable Hooks MAY require explicit acknowledgment:

    aidn.hook.ack({ "hook_id": "hook_123", "event_id": "evt_456" })

An acknowledgment is scoped to the authorized agent and Hook.

## 29. Retry Policy

Failed deliveries SHALL use bounded retries with a short initial delay,
exponential backoff, and a maximum attempt count. The policy is configurable
per Hook and MUST NOT create an unbounded worker.

## 30. Dead Letter Queue

After retry exhaustion, delivery state becomes DEAD_LETTER. Dead letters remain
inspectable and authorized tools SHALL support list, inspect, retry, and discard.

## 31. Event Coalescing

High-frequency telemetry SHALL be coalesced. Four utilization samples such as
61%, 62%, 61%, and 63% SHOULD produce transition or threshold events rather
than four agent messages:

    aidn.resource.gpu_pressure_started
    aidn.resource.gpu_pressure_updated
    aidn.resource.gpu_pressure_resolved

## 32. Threshold Events

An operator or authorized agent MAY define a threshold Hook:

    condition:
      metric: gpu.temperature
      operator: ">="
      value: 85
      sustain_seconds: 30

Threshold evaluation SHALL be bounded and observable.

## 33. Hysteresis

Threshold Hooks SHOULD support hysteresis, for example entering WARNING at
85°C and resolving below 80°C, to prevent oscillation.

## 34. Rate Limiting

Hooks MAY set max_events_per_second, max_events_per_minute, and burst. On
overflow, noncritical events MAY be coalesced while critical events MUST remain
deliverable. Overflow SHALL be observable.

## 35. Backpressure

If an agent cannot keep up, the Hypervisor MAY coalesce telemetry, delay low
priority events, or drop events explicitly marked disposable. Critical events
MUST be retained. Drops SHALL be recorded.

## 36. Event Catalog — Node

Initial node events:

    aidn.node.installed
    aidn.node.initialized
    aidn.node.starting
    aidn.node.ready
    aidn.node.syncing
    aidn.node.degraded
    aidn.node.stopped
    aidn.node.failed
    aidn.node.recovered

## 37. Network Events

    aidn.network.connected
    aidn.network.disconnected
    aidn.network.peer_count_low
    aidn.network.sync_started
    aidn.network.sync_completed
    aidn.network.sync_stalled
    aidn.network.profile_mismatch
    aidn.network.apphash_mismatch

apphash_mismatch SHOULD be CRITICAL.

## 38. Resource Events

    aidn.resource.cpu_pressure
    aidn.resource.memory_pressure
    aidn.resource.disk_pressure
    aidn.resource.gpu_pressure
    aidn.resource.vram_pressure
    aidn.resource.gpu_temperature_high
    aidn.resource.storage_low
    aidn.resource.network_saturated
    aidn.resource.local_priority_requested

## 39. Provider Events

    aidn.provider.install_started
    aidn.provider.installed
    aidn.provider.starting
    aidn.provider.ready
    aidn.provider.degraded
    aidn.provider.failed
    aidn.provider.restarted
    aidn.provider.update_available
    aidn.provider.update_completed

## 40. Model Events

    aidn.model.download_started
    aidn.model.download_progress
    aidn.model.download_completed
    aidn.model.verify_failed
    aidn.model.deployed
    aidn.model.unloaded
    aidn.model.update_available

Progress events SHOULD be coalesced.

## 41. Bundle Events

    aidn.bundle.draft_created
    aidn.bundle.preflight_passed
    aidn.bundle.preflight_failed
    aidn.bundle.activated
    aidn.bundle.retired
    aidn.bundle.rollback_completed
    aidn.bundle.material_change_detected
    aidn.bundle.validation_required

## 42. Endpoint Events

    aidn.endpoint.published
    aidn.endpoint.unpublished
    aidn.endpoint.healthy
    aidn.endpoint.degraded
    aidn.endpoint.unavailable
    aidn.endpoint.session_limit_reached

Endpoint configuration changes SHALL still occur through Bundle revisions.

## 43. Validation Events

    aidn.validation.requested
    aidn.validation.assigned
    aidn.validation.started
    aidn.validation.completed
    aidn.validation.failed
    aidn.validation.expired
    aidn.validation.report_available

## 44. Session Events

    aidn.session.opened
    aidn.session.running
    aidn.session.budget_warning
    aidn.session.degraded
    aidn.session.completed
    aidn.session.failed
    aidn.session.cancelled
    aidn.session.settlement_pending
    aidn.session.settled

## 45. Sharing Events

    aidn.sharing.enabled
    aidn.sharing.disabled
    aidn.sharing.remote_work_started
    aidn.sharing.remote_work_completed
    aidn.sharing.drain_started
    aidn.sharing.resources_reclaimed
    aidn.sharing.local_priority_requested

The local-priority event lets an agent react when an operator needs resources
back.

## 46. Wallet Events

Wallet events require financial visibility permissions:

    aidn.wallet.balance_changed
    aidn.wallet.incoming
    aidn.wallet.outgoing
    aidn.wallet.faucet_received

Sensitive transaction fields MAY be redacted.

## 47. Budget Events

    aidn.budget.created
    aidn.budget.threshold_reached
    aidn.budget.reservation_created
    aidn.budget.reservation_released
    aidn.budget.exhausted
    aidn.budget.expired
    aidn.budget.revoked

Agents MAY reduce workload or prefer local endpoints after a threshold event,
but they cannot increase their own budget.

## 48. Security Events

    aidn.security.authentication_failed
    aidn.security.permission_denied
    aidn.security.agent_session_revoked
    aidn.security.secret_rotation_required
    aidn.security.suspicious_activity

Payloads SHALL avoid secret material.

## 49. Upgrade Events

    aidn.upgrade.available
    aidn.upgrade.plan_ready
    aidn.upgrade.started
    aidn.upgrade.completed
    aidn.upgrade.failed
    aidn.upgrade.rollback_required

## 50. Recovery Events

    aidn.recovery.snapshot_created
    aidn.recovery.snapshot_failed
    aidn.recovery.state_sync_started
    aidn.recovery.state_sync_completed
    aidn.recovery.restore_completed
    aidn.recovery.restore_failed

## 51. Approval Events

The MCP control plane SHALL emit events when operator intervention is required:

    aidn.approval.required
    aidn.approval.granted
    aidn.approval.denied
    aidn.approval.expired

An agent can therefore pause a workflow instead of polling for approval.

## 52. Job Events

Long-running MCP jobs SHALL produce:

    aidn.job.started
    aidn.job.progress
    aidn.job.waiting_approval
    aidn.job.completed
    aidn.job.failed
    aidn.job.cancelled

Progress events SHOULD be rate-limited.

## 53. Attention Event

The Hypervisor MAY expose aidn.agent.attention_required, but typed domain
events SHOULD be preferred.

## 54. Recommended Actions

An event MAY contain trusted machine-generated action hints:

    recommended_actions:
      - tool: aidn.provider.restart
        target: provider-123
      - tool: aidn.bundle.rollback
        target: bundle-456

These are suggestions only. The agent MUST independently authorize and decide
whether to invoke a tool.

## 55. Untrusted Payloads

Provider logs, model output, external metadata, and Marketplace text are
untrusted. Such values MUST be labeled as untrusted and SHALL NOT be
interpreted as system instructions.

    payload:
      provider_message:
        value: "..."
        trust: UNTRUSTED

## 56. Correlation ID

Related events SHOULD share a correlation_id. For example, Provider failure,
Bundle degradation, and Endpoint unavailability can be one incident chain.

## 57. Causation ID

Events MAY reference the event or MCP action that caused them. Agent-triggered
operations should preserve that causation link so automation can distinguish an
expected state transition from an unrelated failure.

## 58. Automation Loop Protection

The Hook system SHALL protect against event-action-event loops. Implementations
SHOULD use retry counters, cooldowns, correlation tracking, and a maximum
automated action depth.

## 59. Hook Loop Metadata

Events generated by agent-triggered actions SHOULD contain:

    automation:
      originating_agent:
      action_id:
      automation_depth:

Policy MAY deny autonomous actions beyond a configured depth.

## 60. Persistent vs Ephemeral Hooks

Hooks may be:

    PERSISTENT
    SESSION
    ONE_SHOT

PERSISTENT hooks survive Hypervisor restart. SESSION hooks exist only for an
Agent Control Session. ONE_SHOT hooks are removed after their first successful
matching event.

## 61. Hook Expiration

Every non-operator system Hook SHOULD have a finite expiration unless
explicitly configured persistent. This prevents abandoned agents from
accumulating subscriptions.

## 62. MCP Hook Tools

MCP-0001 SHALL be extended with:

    aidn.hook.list
    aidn.hook.get
    aidn.hook.create
    aidn.hook.update
    aidn.hook.pause
    aidn.hook.resume
    aidn.hook.delete
    aidn.hook.test
    aidn.hook.ack
    aidn.hook.replay
    aidn.hook.dead_letters
    aidn.hook.dead_letter_retry

## 63. Event Query Tools

Add:

    aidn.event.query
    aidn.event.get
    aidn.event.cursor

aidn.event.stream is optional for transports that support a live stream.

## 64. MCP Resources

Expose the following resources when authorized:

    aidn://events/recent
    aidn://hooks
    aidn://hooks/<hook_id>
    aidn://hooks/<hook_id>/status
    aidn://events/<event_id>
    aidn://events/inbox/<agent_id>

## 65. Hook Creation Example

    {
      "target_agent_id": "agent-ops-1",
      "event_filter": {
        "event_types": [
          "aidn.provider.failed",
          "aidn.bundle.validation_required"
        ]
      },
      "severity_minimum": "WARNING",
      "delivery": {
        "mode": "MCP_LIVE"
      },
      "fallback_delivery": {
        "mode": "DURABLE_INBOX"
      }
    }

## 66. Resource Pressure Example

An operator can ask an agent to watch GPU pressure and release remote work when
local demand requires it. A matching event can include:

    gpu:
      available_vram: 3GB
      requested_local_vram: 12GB
    remote_sessions:
      active: 3
    recommended_action:
      drain remote workloads

The agent MAY call aidn.sharing.pause or aidn.session.cancel, subject to policy.

## 67. Provider Recovery Example

    vLLM process crashes
      -> Provider Manager detects failure
      -> aidn.provider.failed
      -> Ops Agent wakes
      -> aidn.provider.health
      -> agent reasons
      -> aidn.provider.restart
      -> aidn.provider.ready

No polling is required.

## 68. Budget Example

With a 100 Q budget, aidn.budget.threshold_reached at 20 Q can cause an agent
to reduce external work, prefer local endpoints, stop opening sessions, or
request approval. It cannot increase its own budget.

## 69. Validation Example

    Bundle v8 activated
      -> material change detected
      -> validation invalidated
      -> aidn.bundle.validation_required
      -> agent receives event
      -> aidn.validation.request
      -> aidn.validation.completed

The agent may publish the Endpoint only if policy permits.

## 70. Delivery Status

Every delivery SHOULD expose:

    PENDING | DELIVERING | DELIVERED | ACKNOWLEDGED | RETRYING |
    FAILED | DEAD_LETTER | EXPIRED

## 71. Metrics

The Hypervisor SHOULD expose:

    events_generated
    events_delivered
    events_acknowledged
    events_retried
    events_dead_lettered
    events_coalesced
    events_dropped
    average_delivery_latency
    queue_depth

## 72. UI Integration

Advanced Mode SHOULD include:

    Automation
      Hooks
      Event Stream
      Agent Sessions
      Dead Letters

The Hook page should show name, target agent, event types, delivery mode,
status, last delivery, and failure count.

## 73. Basic Mode

Basic Mode SHOULD hide low-level Hook configuration and expose simple controls:

- Notify my agent when Provider fails.
- Notify when Q budget falls below X.
- Allow agent to recover failed Providers.

These controls create Hooks internally.

## 74. Audit

All Hook lifecycle actions SHALL be audited:

    HOOK_CREATED
    HOOK_UPDATED
    HOOK_PAUSED
    HOOK_RESUMED
    HOOK_DELETED
    HOOK_DELIVERY_FAILED
    HOOK_REPLAY_REQUESTED

Agent actions caused by events SHALL reference the originating Event ID where
known.

## 75. Idempotency

Hook creation and modification SHALL support idempotency keys. Event delivery
is at-least-once, so agent processing SHALL be idempotent by event_id.

## 76. Privacy

A Hook may expose only fields authorized for the operator, agent, and Control
Session. A resource agent may receive a budget threshold without receiving
full transaction history.

## 77. Financial Event Safety

Financial events MUST NOT contain private keys, seed phrases, or raw signing
material. Subject to scope, they MAY contain amount, transaction ID, budget
ID, and public wallet address.

## 78. Critical Events

The following SHOULD bypass normal coalescing and low-priority throttling:

    aidn.network.apphash_mismatch
    aidn.security.agent_session_revoked
    aidn.wallet.signing_failure
    aidn.node.failed
    aidn.recovery.restore_failed

They remain subject to authorization and redaction.

## 79. Offline Agent Behavior

When the agent is offline, MCP_LIVE is unavailable. If a Durable Inbox exists,
the event is queued; if a wake-up adapter exists, the agent MAY be started.
Delivery attempts MUST NOT be treated as processing.

## 80. Hook Health

Each Hook SHALL expose:

    enabled
    last_matching_event
    last_delivery
    last_ack
    consecutive_failures
    queue_depth
    health

## 81. Hook Test

aidn.hook.test SHALL create a synthetic delivery without mutating operational
state. It verifies callback routing, signatures, permissions, and agent
selection.

## 82. Replay

Authorized actors MAY replay retained events by cursor/range. Replayed events
preserve event_id and carry delivery metadata such as replayed = true.

## 83. Versioning

Event schemas SHALL be versioned. Breaking changes require a new event
version, for example aidn.provider.failed version 1.

## 84. Compatibility

Agents SHOULD ignore unknown optional fields and MUST NOT reinterpret unknown
event versions. Unsupported versions SHALL surface as
MCP_EVENT_VERSION_UNSUPPORTED.

## 85. Error Codes

The minimum Hook-specific errors are:

    MCP_HOOK_NOT_FOUND
    MCP_HOOK_PERMISSION_DENIED
    MCP_HOOK_FILTER_INVALID
    MCP_HOOK_DESTINATION_INVALID
    MCP_HOOK_SIGNATURE_CONFIG_INVALID
    MCP_HOOK_DELIVERY_FAILED
    MCP_HOOK_ACK_INVALID
    MCP_HOOK_REPLAY_UNAVAILABLE
    MCP_HOOK_RATE_LIMITED
    MCP_HOOK_QUEUE_FULL
    MCP_EVENT_NOT_FOUND
    MCP_EVENT_VERSION_UNSUPPORTED

## 86. MVP Requirements

The first implementation SHALL support:

- one internal Event Bus and canonical Event Envelope;
- MCP_LIVE and DURABLE_INBOX;
- Hook create/list/update/delete;
- filters by type, severity, and resource;
- at-least-once delivery and event ID deduplication;
- acknowledgment, bounded retry, and basic dead-letter handling;
- Node, Provider, Bundle, Validation, Resource, Budget, Job, and Approval
  events;
- audit linkage from delivery and agent actions.

## 87. MVP Deferred

The MVP MAY postpone signed Webhooks, NATS/MQTT/AMQP, complex expressions,
condition evaluation, wake-up adapters, distributed event replication, and
cross-Hypervisor or semantic routing.

## 88. Phase 2

Phase 2 SHOULD add signed Webhooks, Runtime Adapters, threshold conditions,
hysteresis, advanced coalescing, replay UI, automation-loop detection, and
multi-agent routing.

## 89. Future: Cross-Hypervisor Event Routing

A later protocol MAY route events through CometBFT from Hypervisor A to
Hypervisor B and then to an agent. Local Hooks SHALL be implemented first.
Cross-network delivery requires separate work for authenticity, spam, privacy,
routing, replay, and economic cost.

## 90. Future: Agent Event Broker

Large installations MAY run an Agent Event Broker:

    Multiple Hypervisors -> Event Broker -> Agent Fleet

This can centralize policies, correlation, deduplication, specialization, and
delegation, but is outside the MVP.

## 91. Design Invariants

The following SHALL always hold:

- Agents do not need constant polling.
- Hooks are declarative subscriptions, not arbitrary scripts.
- Events do not grant action authority.
- MCP policy controls actions.
- Agents deduplicate by Event ID.
- Durable events survive temporary disconnects.
- Secrets never appear in ordinary events.
- Financial events respect financial scopes.
- High-frequency telemetry is coalesced.
- Critical events remain retained and observable.
- Hook failures are visible.
- Agent actions may reference causative events.
- Automation loops are bounded.
- The Hypervisor remains authoritative over local node safety.

## 92. Core Interaction Model

    Hypervisor observes reality
      -> event system describes reality
      -> Hook routes relevant information
      -> agent reasons about reality
      -> MCP requests a change
      -> policy decides whether it is allowed
      -> Hypervisor executes the change
      -> new events describe the result

This closes the AiDN autonomous-operations loop without giving an agent
unrestricted control over the machine.
