# RFC-0075 — AiDN Node Intelligence Architecture

Status: Draft

Version: 0.1

Category: Hypervisor / Agent / Intelligence Routing

Depends on:

- RFC-0054 Capability Runtime Protocol
- RFC-0069 Bundle Architecture
- RFC-0072 Hypervisor Event and Agent Hook Protocol
- RFC-0073 Resource Broker, Admission Control and Runtime Scheduler
- RFC-0074 Object Lifecycle, Decommissioning and Node Reset
- IMP-0002 Deletion, Decommissioning and Reset Implementation Profile
- MCP-0001 AiDN Node Control MCP Server
- UI-0001 Hypervisor Dashboard Specification

## 1. Purpose

This RFC defines the AiDN Node Intelligence Architecture: a small, resident
local control agent that keeps a Hypervisor operational, and a policy-aware
Reasoning Router that escalates only genuinely difficult work to larger local,
AiDN-hosted, or external intelligence providers.

The resident agent is not a replacement for the Hypervisor, Resource Broker,
or policy engine. The Hypervisor remains authoritative over hardware, process
lifecycle, network state, secrets, finances, and safety. The resident agent is
the local steward that observes those authorities, performs bounded routine
work, and verifies any plan returned by a larger model before it can be
applied.

The architecture therefore separates:

    Operator / Hooks / Events
                 |
                 v
          Resident Node Agent
                 |
        can the steward solve it?
             /           \
           yes            no
            |              |
            v              v
       Local tools     Escalation Task
                              |
                              v
                     Larger Reasoning Model
                              |
                         plan / advice
                              |
                              v
                     steward verifies and applies
                              |
                              v
                           Hypervisor

The large model is an advisor or planner. It MUST NOT receive unrestricted
machine control merely because it was selected as an Intelligence Provider.

## 2. Core invariants

The following rules are normative:

- The Hypervisor, not an Agent or LLM, is the final authority on local safety.
- Hooks and event visibility never grant action authority.
- A larger model may propose a plan, but the Resident Agent MUST validate the
  plan against current policy, dependencies, Resource Broker state, identity,
  budget, and approval requirements before execution.
- External or provider-originated text is untrusted data and MUST NOT be
  interpreted as an instruction that changes the control boundary.
- Routine, low-risk work SHOULD be handled locally without an escalation.
- Escalations MUST carry a bounded, redacted, freshness-stamped context rather
  than an unbounded Hypervisor transcript.
- A GPU-resident Steward is an ordinary RFC-0073 Resource Broker consumer and
  MUST be preemptible or fall back to CPU when higher-priority work needs VRAM.
- Resident Agent actions MUST be idempotent, auditable, and linked to the
  event, request, or escalation that caused them.
- Wallet signing, secret erasure, public retirement, factory reset, and other
  high-risk actions remain separately authorized even when initiated by a
  Steward or returned by a large model.

## 3. Terminology

### 3.1 Resident Node Agent / Node Steward

The Resident Node Agent (also called the Node Steward) is a long-lived local
control process paired with one Hypervisor. It consumes RFC-0072 events,
maintains a bounded operational context, performs routine diagnosis and
actions through the normal MCP/Hypervisor APIs, and creates Escalation Tasks
when local reasoning is insufficient.

The Steward is a control-plane component. It is not an inference Endpoint and
it MUST NOT be advertised as a public compute service unless a separate,
explicit Bundle is created for that purpose.

### 3.2 Intelligence Provider

An Intelligence Provider is a model or service that can produce a structured
answer, recommendation, or plan for an Escalation Task. Providers MAY be:

- a small local model used by the Steward;
- a larger model on the same Hypervisor;
- a trusted AiDN Endpoint;
- an explicitly configured external API.

Provider metadata MUST declare model identity, capabilities, context limit,
latency/cost hints, data handling class, and whether the provider can receive
operator or financial data.

### 3.3 Reasoning Router

The Reasoning Router selects a provider or returns `LOCAL_ONLY` based on task
complexity, local confidence, privacy, latency, cost, available resources,
operator policy, and budget. It routes reasoning, not authority.

### 3.4 Escalation Task

An Escalation Task is a durable, bounded request for non-local reasoning. It
contains the goal, a redacted context snapshot, routing decision, provider
attempts, result, plan hash (when present), and verification outcome. An
Escalation Task does not itself authorize any mutation.

### 3.5 Steward Execution Profile

The execution profile controls where the resident model runs:

- `CPU_RESIDENT` — default; weights and inference stay in host RAM/CPU;
- `IGPU_RESIDENT` — use an integrated accelerator where available;
- `GPU_RESIDENT` — keep a dedicated GPU allocation for the Steward;
- `GPU_BURST` — obtain a temporary lease for a difficult local task and fall
  back when the lease cannot be granted;
- `DISABLED` — no resident model; events and escalations remain inspectable.

## 4. Trust and authority boundary

The control loop is:

    Event / operator request
              |
              v
       Resident Node Agent
              |
       local diagnosis or route
              |
       optional Intelligence Provider
              |
       structured recommendation / plan
              |
       policy + dependency + resource verification
              |
       MCP / Hypervisor action
              |
       authoritative state transition

The Intelligence Provider response MUST be treated as untrusted advice. The
Steward MUST reject a plan when its tool, target, arguments, scope, plan hash,
resource forecast, approval, or freshness does not match current state.

The Steward MUST NOT proxy arbitrary shell commands, arbitrary HTTP requests,
secret values, or raw provider output to a larger model. Any such capability
requires a separately reviewed Hypervisor API and explicit policy scope.

## 5. Resident Agent context

The Steward SHOULD maintain a compact operational context made from canonical
read models rather than replaying an entire conversation. The baseline context
includes:

- Hypervisor identity, version, uptime, and current maintenance mode;
- Provider Plugins and Provider Instances with readiness diagnostics;
- Model Deployments, Bundle revisions, Runtime Instances, and Endpoint states;
- Resource Broker allocatable CPU, RAM, per-device VRAM, leases, queues, and
  scheduler explanations;
- Network, peer, consensus, validation, and discovery readiness;
- active Hooks, pending approvals, budgets, and recent audit/event summaries;
- operator policy, privacy class, and configured goals;
- a bounded recent incident window with event IDs and correlation IDs.

Every context item MUST include an `observed_at` timestamp and SHOULD include a
source revision or event sequence. The Steward MUST refresh a stale item before
using it for a mutating decision. A context snapshot MUST identify omitted data
and MUST not imply that an omitted object does not exist.

## 6. Local decision loop

For each event or operator request, the Steward SHOULD execute:

1. classify the task (`OBSERVE`, `DIAGNOSE`, `RECOVER`, `CONFIGURE`,
   `RESEARCH`, or `MIGRATE`);
2. refresh the minimum authoritative read models;
3. check policy, safety, dependencies, and resource forecast;
4. estimate local confidence and required capabilities;
5. perform a bounded local action when the task is routine and authorized;
6. otherwise create an Escalation Task;
7. verify the result and emit a linked event/audit record;
8. request operator attention when the result is ambiguous or approval is
   required.

Examples of work normally suitable for local handling are checking Provider
health, explaining a `RESOURCE_WAIT`, restarting a failed Provider under an
existing recovery policy, draining a Runtime, or reporting that an Endpoint is
not published. Research, cross-model comparison, migration design, unknown
failures, and multi-step optimization SHOULD be escalated.

## 7. Reasoning Router

The Router MUST evaluate at least:

    complexity
    local_confidence
    required_capabilities
    privacy_class
    maximum_latency
    estimated_cost
    available_budget
    local_resource_fit
    provider_context_limit
    provider_health

A reference policy is:

    if routine and confidence >= threshold:
        LOCAL_STEWARD
    elif private and trusted_local_provider_fits:
        LOCAL_LARGE
    elif private and trusted_AiDN_endpoint_fits:
        AIDN_TRUSTED
    elif budget and policy permit_external:
        EXTERNAL_REASONER
    else:
        OPERATOR_REQUIRED

The Router MUST record why a route was chosen, which providers were rejected,
and whether a fallback was used. It MUST fail closed when no provider meets the
privacy, budget, context, or resource requirements.

## 8. Escalation Task lifecycle

Escalations use this durable state machine:

    CREATED
      -> CONTEXT_PREPARED
      -> DISPATCHED
      -> WAITING_PROVIDER
      -> PLAN_READY
      -> VERIFYING
      -> APPROVED / REJECTED / EXPIRED
      -> EXECUTING
      -> COMPLETED / FAILED / CANCELLED

Each task MUST have an idempotency key, owner/control-session reference,
creation and expiry timestamps, routing decision, attempt count, and a bounded
failure reason. Provider retries MUST use the same logical task identity and
MUST NOT duplicate a mutation.

A provider response MAY contain:

- `answer` — explanatory text;
- `observations` — structured, untrusted findings;
- `recommendations` — non-authoritative suggestions;
- `plan` — typed actions with target revisions and expected preconditions;
- `requires_operator_approval` — an explicit blocker;
- `provider_usage` — cost/latency accounting.

Only a typed `plan` can enter verification. Free-form text MUST never be
executed as a tool call.

## 9. Plan verification and execution

Before applying a provider-generated plan, the Steward MUST:

1. resolve every target through current authoritative state;
2. check target revision, tombstone, lifecycle state, and dependencies;
3. call the Resource Broker forecast for every new Runtime or model;
4. re-check Endpoint/session, network, wallet, budget, and approval policy;
5. compare the plan hash and idempotency key;
6. reduce the plan to the explicitly allowed tool/action set;
7. ask the operator when the policy says approval is required;
8. execute through MCP/Hypervisor services and wait for durable results;
9. verify postconditions and link resulting events to the escalation.

The Steward MUST stop rather than partially improvise when a precondition is
false. A failed or stale plan is a normal control result, not a reason to
retry blindly.

## 10. Resource Broker integration

The Steward is a normal RFC-0073 consumer. A GPU-using profile MUST use a
lease with:

    owner: NODE_STEWARD
    priority: LOCAL_CONTROL
    preemption: GPU_FALLBACK_TO_CPU

`CPU_RESIDENT` SHOULD be the default. `GPU_RESIDENT` MUST declare a bounded
VRAM/RAM profile and a maximum residency policy. `GPU_BURST` leases MUST be
short-lived and released immediately after the local reasoning task completes.

When a higher-priority local workload needs VRAM, the Broker MAY revoke or
decline the Steward lease. The Steward MUST continue in CPU mode or mark the
task `RESOURCE_WAIT`; it MUST not block ordinary Endpoint admission.

The Steward SHOULD subscribe to `aidn.resource.vram_pressure`,
`aidn.resource.capacity_available`, `aidn.resource.lease_revoked`, and
`aidn.resource.admission_estimate_failed`. It MUST not make core scheduling
dependent on a model response.

## 11. Hooks and event handling

RFC-0072 events are the Steward's sensory input. Initial event classes include
Node, Provider, Model, Bundle, Endpoint, Validation, Resource, Budget,
Approval, Job, Security, Upgrade, Recovery, and lifecycle events.

For each matching event the Steward may:

- ignore it when no action is useful;
- record or summarize it;
- execute a pre-authorized bounded recovery;
- ask the operator for approval;
- create an Escalation Task.

Event IDs MUST be deduplicated. Agent-generated actions MUST carry the source
event ID, correlation ID, causation ID, and automation depth. The Steward MUST
honor RFC-0072 loop protection, cooldowns, and maximum automated action depth.

The following events are reserved for the initial implementation profile:

    aidn.steward.started
    aidn.steward.ready
    aidn.steward.degraded
    aidn.steward.profile_changed
    aidn.steward.gpu_fallback
    aidn.steward.escalation_created
    aidn.steward.escalation_completed
    aidn.steward.action_blocked
    aidn.reasoning.provider_selected
    aidn.reasoning.provider_failed

## 12. Permissions and policy

The reference MCP policy SHOULD separate these scopes:

    STEWARD:READ
    STEWARD:EXECUTE
    REASONING:ESCALATE
    REASONING:USE_LOCAL
    REASONING:USE_AIDN
    REASONING:USE_EXTERNAL

These scopes do not imply lifecycle, wallet, secret, financial, or factory-reset
authority. The Steward receives only the minimum tool scopes needed for its
configured goals. Destructive operations continue to require the RFC-0074 / IMP-
0002 lifecycle plan, approval, and audit path.

Operator policy MUST be able to constrain:

- which events wake the Steward;
- which tools may be used automatically;
- which Intelligence Providers may receive each data class;
- maximum escalation count, latency, and Q/fiat budget;
- whether external providers are disabled;
- whether GPU burst is allowed;
- whether operator approval is required for each action class.

## 13. Privacy and redaction

Before dispatch, the Steward MUST apply a payload profile to the context:

    PUBLIC
    OPERATOR
    SENSITIVE
    FINANCIAL
    SECURITY
    SECRET

`SECRET` material, private keys, tokens, raw credentials, and seed phrases MUST
never be included in a provider request. Financial and security data require an
explicit provider policy. Provider logs and model text MUST be marked
`UNTRUSTED` and kept separate from system instructions.

Every escalation record SHOULD retain a redaction manifest and provider data
policy so the operator can see what left the local Hypervisor.

## 14. MCP tools and resources

The initial MCP extension SHOULD expose:

    aidn.steward.status
    aidn.steward.profile
    aidn.steward.route
    aidn.steward.escalations
    aidn.steward.escalation_get
    aidn.steward.escalate
    aidn.steward.cancel_escalation
    aidn.steward.execute_plan
    aidn.reasoning.providers
    aidn.reasoning.forecast

`aidn.steward.execute_plan` MUST be plan-bound and MUST use the same
authorization and approval checks as a direct operator request. It MUST NOT be
a generic tool execution endpoint.

Recommended read resources are:

    aidn://steward/status
    aidn://steward/profile
    aidn://steward/escalations
    aidn://steward/escalations/<task_id>
    aidn://reasoning/providers

## 15. Dashboard and Journey integration

Advanced Mode SHOULD show:

- Resident Agent state, model, execution profile, freshness, and last action;
- current Resource Lease or CPU fallback reason;
- Intelligence Providers and privacy/cost eligibility;
- Escalation Tasks with stage, provider, redaction class, and approval state;
- proposed plans, verification blockers, and causative events;
- automation depth, cooldown, and recent failures.

The Node Journey graph SHOULD expose a non-blocking `Node Steward` /
`Intelligence` branch. Steward readiness MUST NOT make the Provider Node
journey appear ready when the underlying Provider, Bundle, Endpoint, or
Validation state is not ready. A fully configured Steward improves operations;
it does not replace those required stages.

## 16. Failure and fallback behavior

If the local model is unavailable, the Steward MUST continue to expose health
and read-only status and MAY route to a permitted provider. If GPU admission is
denied, it MUST fall back to CPU or mark only the reasoning task as waiting.

If all reasoning providers fail, the Steward MUST return a bounded diagnostic
with the attempted routes and preserve the task for retry or operator review.

If an MCP session or Hook transport expires, durable event/inbox semantics from
RFC-0072 apply. The Steward MUST rehydrate from authoritative state before
acting; it MUST not assume that a cached response is current.

## 17. MVP implementation profile

The first implementation SHOULD deliver these vertical slices:

1. Resident Agent process boundary and `CPU_RESIDENT` profile.
2. Canonical compact context built from existing Hypervisor read models.
3. Event-to-Steward delivery through the local RFC-0072 path.
4. Local routing for health, status, queue, and bounded recovery tasks.
5. Durable Escalation Task store with one structured Intelligence Provider
   adapter and plan-only results.
6. Resource Broker integration for optional `GPU_BURST` with CPU fallback.
7. MCP status, escalation inspection, provider listing, and plan verification.
8. Dashboard status and escalation detail surface.

The MVP MUST NOT enable unrestricted external shell execution, automatic wallet
signing, automatic secret erasure, automatic Factory Reset, or unreviewed
external data transfer.

## 18. Future phases

Phase 2 MAY add:

- multiple local models and confidence calibration;
- trusted AiDN Endpoint selection with latency and reputation signals;
- signed Webhook/Runtime adapters and agent wake-up;
- benchmark/research workflows that return structured evidence;
- multi-agent specialization and cross-Hypervisor event brokering;
- learned routing and cost optimization subject to deterministic safety gates.

Cross-Hypervisor reasoning MUST be specified separately from local Steward
control. It introduces authenticity, privacy, spam, replay, and economic
accounting concerns that are not solved by this RFC.

## 19. Acceptance criteria

An implementation conforms to this RFC when it can demonstrate that:

- a small local model can handle a routine Provider/Runtime health request
  without sending the full Hypervisor history to a large model;
- a complex request produces a bounded, inspectable Escalation Task;
- a larger model can return a typed plan, but cannot execute it directly;
- a stale target, missing dependency, insufficient VRAM, expired approval, or
  policy violation blocks the plan with a typed explanation;
- a GPU-resident Steward releases or falls back when the Resource Broker needs
  the device for higher-priority work;
- event deduplication and causation metadata prevent an automation loop;
- secret and financial fields are redacted according to policy;
- all applied actions are idempotent, auditable, and visible in the Journey or
  Advanced Mode surfaces;
- a disconnected agent can recover from durable state without replaying unsafe
  actions.

## 20. Normative summary

AiDN Hypervisor intelligence is a two-level control system. A lightweight
Resident Node Agent is the always-available local steward: it observes Hooks,
understands canonical node state, performs routine authorized work, and
protects the machine from unsafe plans. Larger models are specialists selected
by a Reasoning Router for complex, private, expensive, or research-heavy work.

The larger model proposes. The Steward verifies. The Hypervisor authorizes and
executes. The Resource Broker constrains placement. Policies and approvals
remain in force at every boundary. This provides cheap local cognition and
on-demand higher reasoning without turning an external LLM into an unrestricted
operator of the node.
