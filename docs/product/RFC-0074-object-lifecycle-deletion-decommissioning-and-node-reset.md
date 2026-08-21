# RFC-0074 — AiDN Object Lifecycle, Deletion, Decommissioning and Node Reset

Status: Draft

Version: 0.1

Category: Hypervisor / Object Lifecycle / Network State / Recovery

Depends on:

- RFC-0054 Capability Runtime Protocol
- RFC-0056 Provider Lifecycle Management
- RFC-0060 Endpoint Lifecycle
- RFC-0062 Validation Framework
- RFC-0069 Bundle Architecture
- RFC-0072 Hypervisor Event and Agent Hook Protocol
- RFC-0073 Resource Broker, Admission Control and Runtime Scheduler
- MCP-0001 AiDN Node Control MCP Server
- UI-0001 Hypervisor Dashboard Specification

## 1. Purpose

This RFC defines safe lifecycle semantics for AiDN-managed objects and nodes.
It covers disabling, unpublishing, retirement, local deletion,
decommissioning, secure erasure, dependency-aware removal, tombstones, and
runtime, configuration, identity-preserving, and factory reset profiles.

The protocol deliberately separates local physical deletion from distributed
retirement. A local database or artifact MAY be removed when dependencies
permit; consensus-visible history MUST remain verifiable and MUST NOT be
rewritten merely because an operator removed local state.

## 2. Core invariants

The following rules are normative:

- Local deletion and distributed retirement are different operations.
- A live dependent blocks destructive deletion unless an approved cascade plan
  drains or transitions that dependent first.
- Public immutable Bundle revisions and public Endpoint history are retired or
  unpublished, never erased from network history.
- Runtime deletion releases its RFC-0073 Resource Lease and triggers resource
  reconciliation.
- Node identity, Wallet identity, Validator identity, and operational state are
  separate objects. Resetting one MUST NOT implicitly erase another.
- Factory Reset preserves the Wallet by default; Wallet erasure is a separate,
  explicit high-risk action.
- Tombstones prevent stale asynchronous commands from recreating deleted
  objects. IDs MUST NOT be reused for unrelated objects.
- Destructive operations use plan, precheck, approval, apply, verify, and audit
  stages. Partial failure MUST remain observable and resumable.
- Agents receive lifecycle authority only through explicit MCP scopes; event
  visibility never grants action authority.

## 3. Object classes

### 3.1 Local objects

Local objects include Runtime Instances, Provider Instances, Model
Deployments, local model caches, draft Bundles, temporary Jobs, local queue
state, transient credentials, and snapshots. They MAY be physically deleted
after dependency and retention checks succeed.

### 3.2 Distributed objects

Distributed objects include public Bundle revisions, public Endpoints, Node and
Validator registrations, network-visible Validation facts, settlement records,
reputation history, and reward history. They transition to explicit terminal or
inactive states while historical identifiers, hashes, and relevant timestamps
remain queryable.

## 4. Lifecycle vocabulary

The following actions MUST remain distinct:

| Action | Meaning | Reversible? |
| --- | --- | --- |
| `DISABLE` | Keep the object defined but exclude it from active execution. | Usually yes |
| `UNPUBLISH` | Remove a public object from active discovery while keeping local definition and history. | Sometimes |
| `RETIRE` | End an immutable or public lifecycle; a new revision/object is required to return. | No for that revision |
| `DELETE_LOCAL` | Physically remove local state after dependency checks. | No, unless backed up |
| `DECOMMISSION` | Voluntarily remove a Node or identity from active network participation. | No for that identity |
| `SECURE_ERASE` | Explicitly destroy secret material. | No without a backup |
| `RESET` | Apply a named, dependency-aware node reset profile. | Depends on profile |

Typical public Endpoint flow is:

    ACTIVE -> DISABLED -> UNPUBLISHED -> RETIRED -> DELETE_LOCAL

An operator MAY disable without unpublishing, or decommission without deleting
local state, when the selected plan says so.

## 5. Dependency graph and removal plans

The Hypervisor SHALL maintain a dependency graph. A representative graph is:

    Provider Plugin
        -> Provider Instance
        -> Model Deployment
        -> Bundle Revision
        -> Runtime Instance
        -> Endpoint
        -> Session

Before a destructive action, the Hypervisor MUST build a deterministic
`removal_plan` containing:

- target object and current revision;
- live and historical dependents;
- ordered actions (drain, disable, unpublish, retire, stop, delete);
- expected resource and network effects;
- approval requirements and policy decision;
- plan hash and `removal_operation_id`.

The default operation is plan-only. Apply MUST reject a stale plan hash or a
changed dependency graph. A Provider, Model, Bundle, or Endpoint with a live
dependent MUST return `DELETE_BLOCKED_BY_DEPENDENCY` rather than silently
deleting the parent.

The removal state machine is:

    PLANNED -> PRECHECK -> APPROVED -> DRAINING -> NETWORK_TRANSITIONS
      -> LOCAL_REMOVAL -> VERIFYING -> COMPLETED

Failure states are `BLOCKED`, `FAILED`, `PARTIALLY_APPLIED`, and
`ROLLBACK_REQUIRED`. Each stage is durable and auditable so an interrupted
operation can resume or reconcile without claiming success.

## 6. Object-specific removal rules

### 6.1 Runtime, Provider, and Model

Runtime removal is:

    BUSY -> DRAINING -> STOPPING -> STOPPED
      -> Resource Lease RELEASED -> DELETE_LOCAL

Provider removal MUST first prove that no Runtime, Model Deployment, Bundle,
or Endpoint still requires it. Model artifacts MAY be garbage-collected only
when no active reference remains. A shared content-addressed artifact remains
until its reference count reaches zero.

### 6.2 Bundle revisions

A local draft Bundle MAY be deleted. A public immutable Bundle revision MUST
transition to `RETIRED`; its ID, revision, content hash, publication and
retirement timestamps remain in historical projections. A replacement uses a
new revision or object identity.

### 6.3 Endpoints

Private Endpoints MAY be disabled and deleted locally after dependency checks.
Public Endpoints MUST be disabled or drained, unpublished from active
discovery, and retired before their local record is deleted. Historical
publication, validation, usage, and settlement references remain queryable.

### 6.4 Validation reports

The network retains the validation fact, hash, and pointer even when local raw
report custody is removed. A missing report is represented as
`REPORT_UNAVAILABLE`; it MUST NOT be rewritten as if validation never
occurred. Policy MAY invalidate current validation eligibility or require
revalidation.

## 7. Tombstones, soft delete, and garbage collection

When local deletion can race with asynchronous agents, the Hypervisor MUST
write a tombstone containing at least:

    object_id, object_type, last_revision, deleted_at,
    deletion_reason, network_status

Commands against a deleted or tombstoned object return `OBJECT_DELETED` or
`OBJECT_TOMBSTONED`; commands against a retired immutable revision return
`OBJECT_RETIRED`. Tombstone retention is object-specific: temporary Jobs may
use short retention, while public Endpoints and Node identities SHOULD retain
long-lived or persistent tombstones.

Non-sensitive local objects MAY use `ACTIVE -> SOFT_DELETED -> PURGED` after a
grace period. Secrets MUST NOT rely on a recycle-bin model. Artifact GC is
reference-aware, policy-driven, and emits an audit/event record for every
purge.

## 8. Node lifecycle and decommissioning

The recommended Node lifecycle is:

    ACTIVE -> DRAINING -> DECOMMISSIONING -> DECOMMISSIONED

Decommissioning MUST stop new Sessions, drain or settle active Sessions,
unpublish public Endpoints, retire applicable public Bundles, finalize the
network decommission operation, revoke temporary capabilities, and mark local
Node state `DECOMMISSIONED`. It MAY be performed without local deletion for
migration, forensics, or archival.

If the network or identity key is unavailable, an operator MAY choose
`FORCED_LOCAL_ONLY`. The UI and audit MUST state that network history remains
unresolved. Liveness/heartbeat expiry SHOULD independently move abandoned
identities to `STALE` and then `INACTIVE`; active topology MUST NOT depend
solely on a voluntary decommission signature.

## 9. Reset profiles

AiDN SHALL expose named reset profiles rather than one ambiguous “reset”:

| Profile | Removes | Preserves |
| --- | --- | --- |
| `RUNTIME_RESET` | Runtime processes, queues, transient Jobs, leases, transient caches | Node identity, Wallet, Providers, Models, Bundles, Endpoints, network registration |
| `CONFIGURATION_RESET` | Providers, Models, local Bundles/Endpoints, Runtime state, queues and caches | Node identity, Wallet, network identity, keys, historical references |
| `IDENTITY_PRESERVING_RESET` | Operational state, Providers, Models, Bundles, Endpoints, peer/network caches and snapshots | Node private identity, selected Validator identity, Wallet |
| `FACTORY_RESET` | Node identity, Providers, Models, Bundles, Endpoints, Runtime/network state, peer cache, local secrets | Wallet by default; only explicit Wallet erase removes it |

### 9.1 Runtime Reset

The Hypervisor pauses admission, drains active work where possible, stops
Runtimes, releases Leases, clears transient queues, restarts services, and
runs RFC-0073 reconciliation. Persistent hooks and configuration remain.

### 9.2 Configuration and identity-preserving reset

These profiles first unpublish/retire public objects as required, then remove
operational state. Identity-preserving reset runs a first-run-like bootstrap
while restoring the same Node and selected Validator public keys.

### 9.3 Factory Reset

Factory Reset returns the installation to `FIRST_RUN`. It MUST require an
explicit confirmation (for example `RESET NODE`) and a high-risk
`NODE:FACTORY_RESET` capability. It MUST revoke local MCP Control Sessions,
remove local hooks according to policy, and verify that no stale Runtime,
Provider, Endpoint, Lease, or operational secret remains. Wallet keys are
preserved unless the operator completes a separate `ERASE WALLET KEYS`
confirmation.

## 10. Reset execution and safety

Every reset follows:

    PLAN -> PRECHECK -> APPROVAL -> PAUSE_SCHEDULER -> DRAIN
      -> NETWORK_TRANSITIONS -> OPTIONAL_CHECKPOINT -> LOCAL_ERASE
      -> SECRET_HANDLING -> VERIFY -> READY / FIRST_RUN

The precheck MUST report active Sessions, pending Validation, queued Requests,
public objects, cached artifact size, Leases, identity state, and exactly what
will be preserved. Paid Sessions MUST be drained, settled, cancelled under
their contract, or cause reset denial. Pending Validation and queued Requests
receive explicit terminal outcomes.

Before destructive local work, an optional recovery snapshot MAY be created.
Reset is not network rollback: it never rewrites consensus history. Completion
proof MUST verify no stale processes, no active Leases, expected identity and
secret state, and the selected post-reset state. Reset audit evidence SHOULD
survive transient-state cleanup or be exported first.

## 11. Identity, Wallet, and secrets

Node identity and Wallet identity are separate. Preserving a Node identity
requires the same private identity key and matching public keys after
reinitialization. Wallet erase is always separate from Node reset and leaves
ledger history intact.

`SECURE_ERASE` is explicit for Node, Validator, Wallet, TLS, Provider, and
other private credentials. The operation MUST require elevated approval,
must not expose key material in events or plans, and MUST distinguish erased
secrets from merely deleted configuration.

## 12. CLI contract

The initial CLI surface is:

    aidn object remove <type> <id>
    aidn object remove <type> <id> --apply
    aidn node reset runtime
    aidn node reset configuration
    aidn node reset preserve-identity
    aidn node reset factory --confirm
    aidn wallet erase

Removal commands are plan-only unless `--apply` is present. Factory Reset and
Wallet erase require explicit destructive confirmation and an appropriate
non-default capability in non-interactive mode.

## 13. MCP contract and authority

MCP-0001 SHOULD expose:

    aidn.object.removal_plan
    aidn.object.remove
    aidn.object.restore_soft_deleted
    aidn.node.reset_plan
    aidn.node.reset
    aidn.node.decommission_plan
    aidn.node.decommission
    aidn.storage.gc_plan
    aidn.storage.gc_apply
    aidn.tombstone.get
    aidn.tombstone.list

Suggested scopes are `OBJECT:DELETE_LOCAL`, `OBJECT:RETIRE`,
`NODE:RESET_RUNTIME`, `NODE:RESET_CONFIGURATION`, `NODE:DECOMMISSION`, and
`NODE:FACTORY_RESET`. Wallet and Validator key operations remain separate
financial/identity scopes. A reset/configuration agent MUST NOT implicitly
gain Wallet erase, Q transfer, or Validator-key rotation authority.

## 14. Events, resources, and audit

RFC-0072 event producers SHOULD emit at least:

    aidn.object.disabled
    aidn.object.unpublished
    aidn.object.retired
    aidn.object.deleted
    aidn.object.removal_planned
    aidn.object.removal_failed
    aidn.object.removal_completed
    aidn.node.decommission_started
    aidn.node.decommission_completed
    aidn.node.reset_started
    aidn.node.reset_completed
    aidn.node.reset_failed
    aidn.storage.gc_completed
    aidn.validation.report_unavailable

Runtime removal MUST publish RFC-0073 Lease release and resource-state
reconciliation events. Lifecycle actions are audited with actor, object,
previous/new state, operation and plan hashes, approval, network references,
timestamps, and the terminal result. Secret values and raw provider output
are redacted.

## 15. Dashboard requirements

Managed-object pages SHOULD show only state-valid contextual actions. A
Provider page exposes its dependent Models, Bundles, Endpoints, required
transitions, and a Removal Plan before offering Apply. Settings > Maintenance
exposes Runtime Reset, Configuration Reset, Reinitialize Node, Decommission
Node, and Factory Reset.

High-risk screens MUST display exact counts and sizes for local deletion,
network facts that remain, identity and Wallet consequences, pending Sessions,
and approval requirements. Factory Reset MUST require typed confirmation.

## 16. Error codes

Implementations SHOULD use these stable errors:

    OBJECT_NOT_FOUND
    OBJECT_DISABLED
    OBJECT_RETIRED
    OBJECT_DELETED
    OBJECT_TOMBSTONED
    DELETE_BLOCKED_BY_DEPENDENCY
    DELETE_REQUIRES_UNPUBLISH
    DELETE_REQUIRES_RETIREMENT
    DELETE_REQUIRES_DRAIN
    DECOMMISSION_REQUIRED
    DECOMMISSION_FAILED
    RESET_PRECHECK_FAILED
    RESET_PARTIAL_FAILURE
    RESET_REQUIRES_APPROVAL
    SECRET_ERASE_REQUIRES_CONFIRMATION
    WALLET_ERASE_DENIED
    GC_OBJECT_REFERENCED

## 17. MVP and deferred work

The MVP SHALL deliver:

- a dependency graph and deterministic Removal Plan;
- Disable, Unpublish, Retire, and guarded Local Delete;
- durable tombstones and audit records;
- Runtime Reset, Configuration Reset, Identity-Preserving Reset, and guarded
  Factory Reset;
- RFC-0073 Lease/Scheduler integration and verification;
- CLI, MCP plan/apply tools, and Dashboard maintenance controls;
- explicit decommission and forced-local-only outcomes.

The following MAY follow in later phases: remote backup and archival export,
multi-node coordinated decommission, network-wide GC, privacy-specific
selective erasure, cross-node artifact transfer, live migration, and
distributed tombstone replication.

## 18. Normative summary

AiDN SHALL treat removal as a lifecycle operation, not a raw database delete.
Local objects may be physically removed after dependency checks; objects that
entered distributed state become `UNPUBLISHED`, `RETIRED`, `DECOMMISSIONED`,
or `EXPIRED` while their historical facts remain verifiable. Node reset ranges
from transient Runtime cleanup to Factory Reset, and handles Node identity,
Wallet identity, network history, and secret erasure independently. This
separation is the foundation for safe deletion, recovery, decommissioning,
and long-term network consistency.
