# IMP-0002 — AiDN Deletion, Decommissioning and Reset Implementation Profile

Status: Draft

Version: 0.1

Category: Implementation Profile

Normative Reference: RFC-0074

## 1. Purpose and implementation scope

IMP-0002 defines how the reference Hypervisor realizes RFC-0074. The first
conforming implementation covers Provider Plugins, Provider Instances, Model
Deployments, Bundle drafts and revisions, Runtime Instances, Endpoints,
Validation Reports, Hooks, Agent Control Sessions, Node and Wallet identity,
Snapshots, and cached Artifacts.

Every destructive path SHALL pass through `LifecycleManager`; UI, HTTP, CLI,
MCP, Agent, Plugin, and internal services MUST NOT issue an alternate direct
delete. `ResetManager` and `ArtifactGC` are lifecycle services owned by the
same boundary.

## 2. Persistent metadata and states

Every managed persistent record SHOULD expose:

    object:
      id:
      type:
      state:
      revision:
      created_at:
      updated_at:
      deleted_at:
      retired_at:
      network_visibility:
      tombstoned:
      owner:
      parent_id:
      resource_refs:
      network_refs:

Applicable states are `ACTIVE`, `DISABLED`, `UNPUBLISHED`, `RETIRED`,
`SOFT_DELETED`, `DELETED`, `DECOMMISSIONING`, `DECOMMISSIONED`, and `FAILED`.
Object-specific transition tables MUST reject unsupported transitions.

## 3. Required service architecture

The implementation SHALL provide:

    API / CLI / MCP / Dashboard
                 |
                 v
          LifecycleManager
          /       |        \
    DependencyGraph NetworkOps RuntimeManager
          \       |        /
              Local Storage
                   |
               Tombstones -> ArtifactGC

`LifecycleManager` owns dependency discovery, plan generation, transition
validation, network coordination, runtime draining, Resource Lease release,
local deletion, tombstones, GC scheduling, audit, and recovery. `ResetManager`
orchestrates the reset profiles below and shares the same operation store.

## 4. Dependency graph

The graph SHALL be reconstructible from durable state and MUST expose:

    GetDependents(object_id)
    GetDependencies(object_id)
    BuildRemovalGraph(object_id)

The canonical direction is:

    Provider Plugin -> Provider Instance -> Model Deployment
      -> Bundle Revision -> Runtime Instance -> Endpoint -> Session

Side dependencies include Bundle Revision -> Validation Report, Endpoint ->
Hook subscriptions, and Node -> Providers/Bundles/Endpoints/Sessions. A live
dependent blocks deletion. `cascade=true` expands the plan; it MUST NOT mean
blind recursive deletion.

## 5. Removal Plan and plan/apply

Every destructive request first produces a durable plan:

    removal_plan:
      plan_id:
      plan_hash:
      target: {type:, id:}
      current_state:
      dependencies: []
      actions: []
      network_actions: []
      local_actions: []
      artifacts_to_delete: []
      artifacts_to_preserve: []
      secrets_affected: []
      estimated_freed: {ram_bytes:, vram_bytes:, disk_bytes:}
      requires_approval:
      created_at:
      expires_at:

`plan_hash` is `sha256(CanonicalJSON(RemovalPlan))`. Apply MUST provide the
plan ID and exact hash; changed target state or dependencies returns
`MCP_CONFLICT_STALE_PLAN` / `REMOVAL_PLAN_STALE`. HTTP destructive routes are
plan-only by default:

    POST /api/v1/lifecycle/removal-plan
    POST /api/v1/lifecycle/removal-plan/{id}/apply

The durable operation state is:

    PLANNED -> PRECHECK -> APPROVED -> DRAINING -> NETWORK_TRANSITIONS
      -> LOCAL_REMOVAL -> VERIFYING -> COMPLETED

`BLOCKED`, `FAILED`, `PARTIALLY_APPLIED`, and `ROLLBACK_REQUIRED` are terminal
or operator-recovery states. Apply accepts an idempotency key and repeated
requests return the same logical operation.

## 6. Object-specific execution

### 6.1 Runtime

Runtime removal marks `DRAINING`, rejects new work, drains according to policy,
stops and verifies the process, releases its Resource Lease, emits
`aidn.resource.state_changed`, calls `Scheduler.reconcile()`, removes metadata,
and writes a tombstone. `force=true` requires destructive permission and MUST
wait for process ownership to end before releasing the Lease.

### 6.2 Provider and Plugin

Provider removal requires zero active runtimes, model deployments, and bundle
dependencies. It stops the provider, removes its service/configuration, uses
`SecretStore.Delete(secret_ref)` only for explicitly selected provider-only
secrets, removes the record, and creates a tombstone. A Plugin cannot be
removed while any Provider Instance references it.

### 6.3 Model and artifacts

Model removal stops dependent runtimes, removes deployment metadata, decrements
artifact references, and schedules GC only at reference count zero. Shared
weights MUST remain available to other deployments.

### 6.4 Bundles and Endpoints

Local Bundle drafts may be deleted when they have no network or runtime refs.
Public revisions transition to `RETIRED`; local manifests may later be GC'd
while the network representation remains sufficient. A private Endpoint is
disabled and locally removed after dependency checks. A public Endpoint MUST
be disabled, unpublished, finalized where required, retired, then locally
removed. Suggested routes are:

    POST /api/v1/endpoints/{id}/unpublish
    POST /api/v1/endpoints/{id}/retire

Active Sessions default to `DRAIN`; `CANCEL` or `DENY_REMOVAL` require policy.

### 6.5 Validation Reports

Deleting local custody marks availability `UNAVAILABLE`, retains the report
hash, validation ID, historical result, and pointer history, emits
`aidn.validation.report_unavailable`, and invokes
`ValidationService.Reevaluate(endpoint_id)`. Current eligibility MAY become
`DEGRADED` or `REVALIDATION_REQUIRED`.

## 7. Tombstones and ArtifactGC

The durable Tombstone Store SHALL retain:

    object_id, object_type, final_revision, previous_state,
    deleted_at, actor, reason, network_state, expires_at

Creation of an object ID present in a permanent tombstone returns
`OBJECT_TOMBSTONED`; IDs are never recycled. Recommended retention is 7 days
for Runtime, 30 days for Provider/Model/private Endpoint, network-aligned or
indefinite for public Endpoint, and indefinite for Node identity.

`ArtifactGC` supports plan/apply for unused model files, temporary downloads,
orphaned caches, retired local Bundle artifacts, and expired snapshots. An
artifact is eligible only when `reference_count == 0`, not pinned, and not
required by recovery policy. Deletion is normally asynchronous: logical object
removal may complete while disk cleanup is pending. `GC_FAILED` never
resurrects the object.

## 8. ResetManager

The reset plan SHALL contain reset ID, profile, hash, preserved identity and
Wallet flags, delete sets, network actions, active Sessions, pending Jobs and
Validations, reclaimed disk estimate, and approval requirements. Operation
state survives restart in `lifecycle_operations` with operation ID, target,
plan hash, state, current step, timestamps, and error. Startup resumes,
reconciles, or marks an incomplete operation; it never blindly repeats it.

### 8.1 Runtime Reset

`aidn node reset runtime` pauses admission, rejects new Runtime activation,
drains/cancels Requests, stops Runtimes, releases Leases, clears transient
queues/jobs/cache, restarts runtime services, reconciles resources, and
returns Scheduler to `ENABLED`. Node identity, Wallet, Providers, Models,
Bundles, Endpoints, and network registration remain.

### 8.2 Configuration Reset

`aidn node reset configuration` requires approval, drains Sessions, unpublishes
and retires public objects, stops Runtimes, releases Leases, deletes local
Endpoints/Bundles/Models/Provider Instances, optionally removes non-core
Plugins, clears operational Hooks/caches, verifies Node and Wallet preservation,
and enters `READY_EMPTY`.

### 8.3 Identity-Preserving Reset

`aidn node reset preserve-identity` additionally clears peer/network caches,
operational configuration, and snapshots (unless retained), stores the
selected identity in a protected reset vault, then enters `FIRST_RUN_REINIT`.
The wizard asks for network, role, bootstrap, RPC/P2P, and sharing settings
without generating a new identity. A public-key mismatch returns
`RESET_IDENTITY_VERIFICATION_FAILED` and leaves the node blocked.

### 8.4 Factory Reset

`aidn node reset factory` builds and displays a complete consequence summary,
pauses the Scheduler, blocks new Sessions, drains/cancels work, attempts Node
Decommission, unpublishes/retires public objects, revokes Agent Sessions,
deletes Hooks and operational state, securely erases Node identity, and
verifies `FIRST_RUN`. `preserve_wallet=true` is the default. Wallet erase
requires a separate `WALLET:SECURE_ERASE` authorization and confirmation.

If network decommission cannot complete, `--force-local` requires stronger
approval and records `UNSIGNED_IDENTITY_LOST` or a network-unavailable reason;
the UI MUST warn that distributed history remains.

## 9. Node, Wallet, and secret handling

`aidn node decommission` blocks new network Sessions, drains existing ones,
unpublishes Endpoints, retires public objects, submits the network operation,
waits for finalization, and marks the Node `DECOMMISSIONED` without deleting
local files unless a reset follows. Heartbeat/lease expiry handles lost keys
and stale topology; local deletion never rewrites network history.

Secret operations use a `SecretStore` abstraction and MUST NOT guess or unlink
secret paths. Secure erase documentation MUST state storage limitations; for
encrypted stores, deleting the encryption key may be the available guarantee.

## 10. CLI, HTTP, MCP, and Dashboard

Required CLI surface:

    aidn object inspect <type> <id>
    aidn object remove <type> <id> [--apply] [--cascade]
    aidn node decommission [--plan]
    aidn node reset runtime|configuration|preserve-identity|factory
    aidn storage gc [--apply]
    aidn tombstone list|inspect <id>
    aidn wallet erase

Destructive commands are plan-only by default. `--yes` is allowed only with
an explicit destructive capability; Factory Reset normally requires typed
`RESET NODE` confirmation.

MCP SHALL expose:

    aidn.object.removal_plan
    aidn.object.remove
    aidn.node.decommission_plan
    aidn.node.decommission
    aidn.node.reset_plan
    aidn.node.reset
    aidn.storage.gc_plan
    aidn.storage.gc_apply
    aidn.tombstone.list
    aidn.tombstone.get

Minimum scopes are `OBJECT:READ`, `OBJECT:DISABLE`, `OBJECT:UNPUBLISH`,
`OBJECT:RETIRE`, `OBJECT:DELETE_LOCAL`, `NODE:DECOMMISSION`,
`NODE:RESET_RUNTIME`, `NODE:RESET_CONFIGURATION`,
`NODE:RESET_PRESERVE_IDENTITY`, `NODE:FACTORY_RESET`, `WALLET:SECURE_ERASE`,
and `STORAGE:GC`. Scope possession is not transitive: Runtime Reset never
implies Factory Reset, and Factory Reset never implies Wallet erase.

Dashboard object menus show only state-valid actions and explain disabled
ones. Removal and reset screens show dependencies, network/local effects,
resources freed, data permanently deleted, preserved identity/Wallet state,
approval, and progress stages: Precheck, Draining, Network Update, Stop,
Delete, Verify, Complete. During maintenance, mutating API requests return
`NODE_MAINTENANCE_IN_PROGRESS`; read-only status remains available.

## 11. Hooks, audit, and errors

The implementation emits:

    aidn.object.removal_planned
    aidn.object.disabled
    aidn.object.unpublished
    aidn.object.retired
    aidn.object.deleted
    aidn.node.decommission_started
    aidn.node.decommission_completed
    aidn.node.decommission_failed
    aidn.node.reset_started
    aidn.node.reset_step
    aidn.node.reset_completed
    aidn.node.reset_failed
    aidn.storage.gc_started
    aidn.storage.gc_completed
    aidn.storage.gc_failed

Audit records include actor, Control Session, operation ID, plan hash, target,
state transition, network operations, local deletions, secret operations, and
result. Reset-step events carry reset ID, profile, step, and progress.

Stable errors include `OBJECT_NOT_FOUND`, `OBJECT_TOMBSTONED`,
`OBJECT_RETIRED`, `DELETE_BLOCKED_BY_DEPENDENCY`, `DELETE_REQUIRES_DRAIN`,
`DELETE_REQUIRES_UNPUBLISH`, `DELETE_REQUIRES_RETIREMENT`,
`REMOVAL_PLAN_STALE`, `REMOVAL_PARTIAL_FAILURE`, `RESET_PRECHECK_FAILED`,
`RESET_IN_PROGRESS`, `RESET_PARTIAL_FAILURE`,
`RESET_IDENTITY_VERIFICATION_FAILED`, `DECOMMISSION_FAILED`,
`DECOMMISSION_NETWORK_UNAVAILABLE`, `SECRET_ERASE_DENIED`,
`WALLET_ERASE_REQUIRES_CONFIRMATION`, `GC_OBJECT_REFERENCED`, and `GC_FAILED`.

## 12. Required fixtures and release gate

The implementation SHALL test unused and dependent Provider removal, cascade
planning, private/public Endpoint removal, Bundle draft/revision semantics,
shared artifacts, Runtime Lease release, all reset profiles, Wallet
preservation/erase, forced local reset, crash recovery, stale plans, tombstone
ID protection, idempotency, CLI/MCP authorization, and UI confirmation.

The critical resource fixture is a 24 GB GPU with Runtime A holding a 20 GB
Lease and Endpoint B waiting for 10 GB: deleting A MUST release the Lease and
make B eligible through global reconciliation. Direct local deletion of a
published Endpoint MUST fail and produce disable -> unpublish -> retire ->
local-delete actions. Factory Reset MUST preserve the Wallet by default and
leave the Hypervisor in `FIRST_RUN`; identity-preserving reset MUST retain the
same Node public key.

The implementation is not production-ready until dependency safety,
idempotency, crash recovery, resource release, network transitions, Wallet and
identity preservation, tombstones, partial failure, and CLI/MCP/UI
authorization are covered. Hard-deleting distributed history, implicit Wallet
erase, blind recursive deletion, secret export, and ID reuse are unsupported.

## 13. Final execution rules

Every destructive object operation follows:

    DISCOVER -> BUILD PLAN -> VALIDATE -> AUTHORIZE -> DRAIN
      -> NETWORK TRANSITION -> STOP RUNTIME -> RELEASE RESOURCES
      -> DELETE LOCAL -> TOMBSTONE -> SCHEDULE GC -> VERIFY -> AUDIT

Every reset follows:

    PLAN -> PAUSE SCHEDULER -> DRAIN -> NETWORK TRANSITIONS
      -> PRESERVE SELECTED IDENTITY -> DELETE SELECTED STATE
      -> VERIFY -> REINITIALIZE -> RESOURCE RECONCILIATION
      -> READY / READY_EMPTY / FIRST_RUN

These rules are normative for the reference Hypervisor implementation.
