# UI-0002 AiDN Hypervisor Dashboard Screen and Action Map

Status: `Draft`

Version: `0.1`

Depends on:

- [UI-0001 Hypervisor Dashboard Specification](./UI-0001-hypervisor-dashboard-specification.md)
- [UX-0001 Hypervisor Operator Journey](./UX-0001-hypervisor-operator-journey.md)
- [UX-0002 Endpoint Session and Payment Flow](./UX-0002-endpoint-session-and-payment-flow.md)
- [UX-0003 Operator Readiness Wizard](./UX-0003-operator-readiness-wizard.md)
- [MCP-0001 Node Control Server Implementation Profile](./MCP-0001-node-control-server-implementation-profile.md)

## 1. Purpose

This document maps every Hypervisor Dashboard menu screen to its domain objects,
displayed data, operator actions, navigation outcomes, permissions, and required
feedback.

It is both:

- an information-architecture specification;
- an implementation checklist for eliminating decorative or inert controls.

The Dashboard SHALL let a paired operator perform every node-management action
available to an authorized MCP agent, subject to the same protocol rules,
approval boundaries, signatures, consensus path, and safety checks. UI parity
does not mean bypassing those controls.

## 2. Status Vocabulary

The action inventories below use these implementation states:

| State | Meaning |
| --- | --- |
| `IMPLEMENTED` | The maintained React Dashboard invokes a real backend operation and renders its result. |
| `READ_ONLY` | Real data is displayed, but no mutation is currently exposed on that screen. |
| `UI_PENDING` | A backend operation exists, but the maintained Dashboard does not yet expose the complete flow. |
| `API_PENDING` | The product requires the action, but a safe canonical operator API is not complete. |
| `NOT_APPLICABLE` | The screen intentionally links to another canonical screen instead of duplicating the action. |

This document describes the intended complete product. The status column records
the implementation snapshot at version `0.1`; it SHALL be updated when controls
are added or removed.

## 3. Global Interaction Contract

### 3.1 Every interactive element has one visible outcome

Every button, link, row action, selectable metric, tab, menu item, and form
submission SHALL result in at least one of:

1. navigation to a named canonical screen or object inspector;
2. opening an editor, drawer, confirmation, or evidence view;
3. submitting a real authenticated operation;
4. changing a documented local UI state such as a filter or mode;
5. displaying a specific explanation that the action is blocked.

Controls SHALL NOT exist only to animate, reload silently, or resemble an
available action.

### 3.2 Operation states

Every mutation SHALL visibly pass through the applicable states:

```text
READY -> CONFIRMING -> SUBMITTING -> ACCEPTED/PENDING -> FINALIZED
                                   -> BLOCKED/REJECTED/FAILED
```

The UI SHALL show:

- the action being performed;
- the target object ID;
- whether the action is local, operator-approved, Wallet-signed, or consensus-bound;
- the returned operation, plan, job, transaction, or evidence ID;
- whether completion is final or still pending;
- a human-readable failure reason;
- the next safe action;
- a retry only when retry is valid and idempotent.

### 3.3 Refresh behavior

A refresh control SHALL report `Refreshing`, then either:

- the completion time and refreshed scope; or
- the number and names of sections that failed.

Background refresh SHALL not erase a visible operation result. Stale data SHALL
be labeled with its last successful update time.

### 3.4 Destructive and economic actions

Actions that can stop execution, revoke publication, detach capacity, rotate a
credential, close a Session, move Q, or affect settlement SHALL display the
consequence before confirmation.

The confirmation SHALL name the target object and distinguish:

- existing Sessions from future Sessions;
- local state from consensus state;
- refundable funds from Endpoint Payment and Network Fees;
- reversible actions from irreversible actions.

### 3.5 Permission boundary

Read operations MAY be available without an unlocked operator session when they
do not reveal protected data. Mutations SHALL require the paired browser operator
boundary. Network-facing ownership operations additionally require the bound
Wallet and canonical signatures. Validator-mode writes SHALL use the consensus
transaction path.

The Dashboard SHALL never expose private keys after their one-time creation view,
reusable Provider secrets, MCP bearer tokens after their one-time issue/rotation
view, or private Session payloads outside their authorized evidence boundary.

## 4. Global Shell

### 4.1 Header

Displays:

- AiDN product identity and online/degraded state;
- active Hypervisor name and locality;
- connected remote Hypervisor tabs;
- global refresh state and last update;
- Basic/Advanced mode;
- operator-session entry point.

Actions:

| Element | Action | Result | Status |
| --- | --- | --- | --- |
| AiDN logo | Open Overview | Navigates to the active Hypervisor Overview. | `IMPLEMENTED` |
| Active Hypervisor tab | Open its Overview | Makes the selected Hypervisor the active workspace. | `IMPLEMENTED` for local node |
| Remote discovery | Open Network | Shows discovered and attached remote capacity. | `IMPLEMENTED` |
| Add Hypervisor | Open the browser-local connection drawer | Validates and saves another operator-owned dashboard URL, then opens that node in a new tab. Pairing remains on the target node; credentials are never entered into the local dashboard. Full multi-node read-model switching remains `API_PENDING`. | `IMPLEMENTED` (browser launcher) |
| Refresh | Refresh all dashboard read models | Shows progress, completion time, and partial failures. | `IMPLEMENTED` |
| Basic/Advanced mode | Change navigation density | Preserves the current object and does not alter backend state. | `IMPLEMENTED` |
| Operator badge | Open Settings | Opens browser pairing, agent access, and operator-session controls. | `IMPLEMENTED` |

### 4.2 Navigation

Basic Mode contains:

```text
Overview
Agents
Bundles
Market
Catalog
Wallet
Settings
```

Advanced Mode additionally exposes:

```text
Endpoints
Provider Plugins
Models
Validation
Network
```

Each menu item SHALL navigate to exactly one canonical screen and visibly mark
the active screen. Hiding an Advanced item SHALL not destroy state or create a
second Basic-mode implementation of the same object.

### 4.3 Resource footer

Displays live CPU, RAM, GPU/VRAM, storage, network, Session, and job summaries
when measured data exists. Unknown capacity SHALL remain unknown rather than
being displayed as zero.

Target actions:

- CPU/RAM/GPU/storage opens Settings at Resource Probe evidence;
- Sessions opens Agents & Sessions;
- Jobs opens Models at the install/materialization queue;
- network opens Network diagnostics.

Current state: `READ_ONLY`.

## 5. Overview

### Purpose

Overview answers three questions: Is this Hypervisor healthy? What is currently
running? What should the operator do next?

### Displays

- active Bundle count and registered Bundle count;
- published and configured Endpoint count;
- running and queued execution count;
- owner Wallet binding state;
- overall readiness percentage and next blocker;
- ordered Readiness Wizard checks;
- compact active Bundle inventory;
- host resource capacity and use;
- validation summary;
- Provider, network, and storage health evidence.

### Operator objects

Node, Readiness Check, Bundle, Endpoint, Session summary, Wallet summary,
Resource Probe, Validation summary.

### Actions

| Action | Expected result | Status |
| --- | --- | --- |
| Select Active Bundles metric | Open Bundles. | `IMPLEMENTED` |
| Select Published Endpoints metric | Open Endpoints. | `IMPLEMENTED` |
| Select Running Sessions metric | Open Agents & Sessions. | `IMPLEMENTED` |
| Select Wallet metric | Open Wallet. | `IMPLEMENTED` |
| Select Readiness metric | Open Network/readiness evidence. | `IMPLEMENTED` |
| Execute next Readiness action | Navigate to Wallet, Settings, Providers, Models, Bundles, Endpoints, Validation, or Network as required. | `IMPLEMENTED` |
| Refresh readiness | Re-run live checks and show completion or failure. | `IMPLEMENTED` |
| Open Bundle row | Open the Bundle canonical details inspector. | `UI_PENDING` |
| Open linked Endpoint | Open Endpoints focused on the related Endpoint. | `IMPLEMENTED` without row focus |
| Resolve a health failure | Navigate to the canonical owning screen, not mutate the object from Overview. | `UI_PENDING` for deep links |

Overview SHALL avoid destructive controls. It is an orientation and routing
surface, not a second copy of every management page.

## 6. Agents & Sessions

### Purpose

This screen supervises delegated agents and live execution. It distinguishes:

- MCP agents authorized to control the Hypervisor;
- Consumer Sessions reserving Endpoint execution;
- Requests/tasks executing inside a Session.

Credential details remain canonical in Settings, while Session lifecycle and
execution pressure are canonical here.

### Displays

- active, queued, and closed Session counts;
- Session ID, Endpoint, Consumer authorization reference, status, and request count;
- locked deposit, consumed amount, Endpoint Payment projection, fees, and refund projection;
- idle deadline and last activity;
- related request/task states and recent activity;
- active MCP-agent count and links to their permission profiles;
- queue pressure and admission failures.

### Operator objects

MCP Credential, Agent Control Session, Consumer Session, Request, Deposit,
Usage checkpoint, Settlement preview, task queue.

### Actions

| Action | Expected result | Status |
| --- | --- | --- |
| Manage agent permissions | Open Settings at MCP agent credentials. | `IMPLEMENTED` |
| Close Session | Apply canonical close and settlement policy; show payment/refund result. | `IMPLEMENTED` |
| Sweep idle Sessions | Close only Sessions whose server-side deadline has elapsed. | `IMPLEMENTED` |
| Refresh Sessions | Reload Session ledger and show result. | `IMPLEMENTED` |
| Inspect Session | Show requests, usage chain, checkpoint, deposit, activity, and settlement evidence in the Session inspector. | `IMPLEMENTED` |
| Cancel queued Request | Cancel according to accepted Request/Session policy. | `API_PENDING` |
| Inspect task/result | Show execution status and authorized evidence without leaking another Session. | `IMPLEMENTED` for Session-scoped task summaries |
| Pause new admission | Change scheduler admission policy with an explicit scope and expiry. | `API_PENDING` |
| Inspect MCP audit trail | Open filtered audit events for the selected agent. | `UI_PENDING` |

Closing a Session SHALL never imply that subjective result quality was judged.
The UI shows the deterministic contractual outcome.

## 7. Bundles

### Purpose

Bundles are the primary operational workspace. A Bundle connects Provider,
Model Deployment, Runtime Binding, resource policy, Endpoint relationships, and
Validation consequences.

### Displays

- Bundle ID, revision, ancestry, and content hash;
- Provider type/instance and model identity;
- Runtime status and generation;
- enabled, paused, cooldown, failed, or draining state;
- resource requirements and current allocation;
- linked Endpoint offers and active Session count;
- validation impact and activity history.

### Operator objects

Bundle revision, Runtime Binding, Provider Instance, Model Deployment, Resource
Profile, Endpoint relationship, Session relationship.

### Actions

| Action | Expected result | Status |
| --- | --- | --- |
| Enable Bundle | Admit new compatible work after readiness checks. | `IMPLEMENTED` |
| Pause/disable Bundle | Stop new admission without rewriting existing Sessions. | `IMPLEMENTED` |
| Retry Bundle | Retry recoverable startup/runtime work and show resulting health. | `IMPLEMENTED` |
| Reset cooldown | Clear an eligible failure cooldown. | `IMPLEMENTED` |
| Create revision | Clone immutable source into a new ID/hash with explicit overrides. | `IMPLEMENTED` |
| Inspect Bundle | Open full dependency, hash, generation, resource, Endpoint, and history view. | `IMPLEMENTED` (React inspector; generation and active Session evidence remain API-pending) |
| Compare revisions | Show field-level changes and their resource/validation/Endpoint effects. | `IMPLEMENTED` (read-only comparison) |
| Run activation preflight | Verify resources, Provider, model, Runtime Binding, route generation, and validation impact. | `IMPLEMENTED` (read-only projection; canonical evidence endpoint remains planned) |
| Drain Bundle | Stop new Sessions and wait for accepted work to finish. | `API_PENDING` |
| Retire revision | Retain audit history while preventing future activation. | `API_PENDING` |

Existing Bundle revisions SHALL never be edited in place or silently deleted.

## 8. Market

### Purpose

Market is the Consumer-oriented view of canonical Endpoint offers. It hides
private Provider topology while showing enough commercial and trust information
to choose capacity.

### Displays

- local and remote public Endpoint offers;
- capability/model class without unnecessary deployment internals;
- node/operator identity and availability;
- accounting mode, price, minimum deposit, and Session limits;
- reputation, Validation/certification, and publication evidence;
- attached/preferred status;
- catalogue freshness and Registry source.

### Operator objects

Endpoint Advertisement, remote node, Registry candidate, Accounting Contract,
Validation summary, preferred Remote Endpoint.

### Actions

| Action | Expected result | Status |
| --- | --- | --- |
| Refresh catalogue | Re-run Registry-backed discovery and show freshness/errors. | `IMPLEMENTED` |
| Open local offer | Open its canonical Endpoint page. | `IMPLEMENTED` without row focus |
| Attach remote offer | Add verified remote capacity to the local preferred catalogue. | `IMPLEMENTED` |
| Open Network | Inspect source nodes, discovery, and attached capacity. | `IMPLEMENTED` |
| Filter/sort offers | Filter by capability, price, accounting mode, reputation, Validation, and availability. | `UI_PENDING` |
| Inspect offer | Show public configuration, proof, pricing, Session terms, and trust evidence. | `UI_PENDING` |
| Bookmark/prefer offer | Save a local routing preference without republishing the remote offer. | `API_PENDING` |
| Start Consumer Session | Review exact deposit/price/timeout terms, sign, and reserve capacity. | `UI_PENDING` |
| Stage Proxy Endpoint | Continue to an Endpoint draft backed by attached remote capacity. | `UI_PENDING` |

Market SHALL never present an Endpoint as verified merely because its node is
reachable.

## 9. Catalog

### Purpose

Catalog shows installable Provider Plugins, official packages, Runtime
components, and Bundle templates. It starts operator deployment workflows; it
does not represent already-running Provider instances.

### Displays

- Plugin/package identity, version, source, signature, compatibility, and permissions;
- installation state and retained artifacts;
- supported capabilities and attach/install modes;
- Bundle templates and required resources;
- warnings, known limitations, and approval requirements.

### Operator objects

Provider Plugin release, package, installation plan, installation approval,
installation job/artifact, Bundle template.

### Actions

| Action | Expected result | Status |
| --- | --- | --- |
| Select Plugin | Populate a real attach/install configuration. | `IMPLEMENTED` for attach |
| Attach existing Provider | Create a Provider Instance for an already-running service. | `IMPLEMENTED` |
| Create installation plan | Show exact files, services, permissions, ports, and resource impact. | `UI_PENDING` |
| Dry-run diagnostics | Validate prerequisites without changing the host. | `UI_PENDING` |
| Approve installation plan | Record explicit operator approval for the exact plan hash. | `UI_PENDING` |
| Apply approved installation | Execute the approved plan and stream job state. | `UI_PENDING` |
| Roll back failed installation | Revert only changes recorded by the installation job. | `UI_PENDING` |
| Remove retained artifact | Remove an unused artifact after dependency checks. | `UI_PENDING` |
| Start Bundle wizard | Continue with Provider, model, resources, Endpoint, Validation, and review. | `UI_PENDING` |

Catalog and Provider Plugins SHALL remain separate: Catalog describes available
supply; Provider Plugins manages installed/attached runtime supply.

## 10. Endpoints

### Purpose

Endpoints are Consumer-facing service offers. Their commercial identity,
configuration, publication, and Validation are distinct from the Bundle that
executes them.

### Displays

- Endpoint ID, display name, capability, visibility, and owner/payment beneficiary;
- Runtime Binding and Bundle revision;
- publication status, configuration hash, revision, and consensus finality;
- runtime readiness and accepted external-request policy;
- accounting mode, fixed/variable price, minimum deposit, and Session limits;
- Validation state, evidence reference, and certification;
- current Session load and route generation.

### Operator objects

Endpoint draft, Configuration Snapshot, Advertisement/Publication, Accounting
Contract, Runtime Binding, Validation Request/Report, Session policy.

### Actions

| Action | Expected result | Status |
| --- | --- | --- |
| Create draft | Persist a local Endpoint identity from a ready Runtime Binding or Bundle. | `IMPLEMENTED` |
| Publish | Run readiness checks, sign the exact configuration, and use consensus when required. | `IMPLEMENTED` |
| Request Validation | Create a separate Validation request for an existing Endpoint. | `IMPLEMENTED` |
| Open Bundle | Navigate to the exact backing Bundle revision. | `IMPLEMENTED` without object focus |
| Edit draft | Update only an unpublished draft and show changed fields. | `UI_PENDING` |
| Create configuration revision | Clone a published configuration rather than mutate it. | `API_PENDING` |
| Revoke publication | Stop advertising future availability while preserving history and active Session rules. | `UI_PENDING` |
| Delete local draft | Delete only an unpublished, unused draft after dependency checks. | `API_PENDING` |
| Configure shared Wallet allowlist | Add/remove Wallets and produce a new configuration revision where required. | `UI_PENDING` |
| Configure Proxy route | Bind attached remote capacity without exposing upstream topology. | `UI_PENDING` |
| Inspect publication proof | Show operation ID, block/finality, config hash, and Registry sync. | `UI_PENDING` |

Publication and Validation SHALL always remain separate operator actions.

## 11. Wallet

### Purpose

Wallet binds operator ownership and displays canonical Q accounting. Node
identity and Wallet identity remain distinct.

### Displays

- owner Wallet ID, label, public identity, and binding state;
- canonical balance and its source/finality;
- network identity registration state;
- usage, allocation, settlement, dispute, correction, and fee activity;
- faucet eligibility preview without pretending the faucet is part of the node;
- export and evidence availability.

### Operator objects

Owner Wallet, Wallet Identity, balance projection, Ledger operation, Allocation,
Settlement, Dispute, Correction, external Faucet claim reference.

### Actions

| Action | Expected result | Status |
| --- | --- | --- |
| Create Wallet | Generate a Wallet and reveal its private key exactly once. | `IMPLEMENTED` |
| Import Wallet | Bind a validated supplied private key to this Hypervisor. | `IMPLEMENTED` |
| Register network identity | Submit canonical Wallet identity registration and show finality. | `IMPLEMENTED` |
| Copy one-time private key | Copy only during the creation result; never retrieve it later. | `IMPLEMENTED` |
| Refresh balance | Reconcile canonical balance/identity and report source errors. | `IMPLEMENTED` |
| Inspect ledger operation | Show type, amount, participants, status, operation ID, and finality. | `UI_PENDING` |
| Export accounting evidence | Download bounded usage, Session, allocation, settlement, or ledger data. | `UI_PENDING` |
| Claim external Faucet | Open or invoke the separately governed Faucet and track the claim operation. | `UI_PENDING` |
| Open dispute/reopen allocation | Require exact event, reason, evidence, amount, and consequence. | `UI_PENDING` |
| Hold/release/correct allocation | Use authorized policy and show conservation effects. | `UI_PENDING` |
| Transfer ownership | Use a future signed ownership-transfer protocol, never overwrite binding locally. | `API_PENDING` |

The Dashboard SHALL not provide a generic hidden mint action or treat local
accounting projections as canonical balance.

## 12. Settings

### Purpose

Settings controls the local host boundary, operator browser access, delegated
MCP agents, and non-domain-specific node configuration.

### Displays

- Resource Probe source, timestamp, limitations, and measured capacity;
- paired browser session state and expiry;
- insecure-LAN/HTTPS transport warning;
- MCP agent credentials by ID, label, fingerprint, scopes, last use, and state;
- permission catalogue, risk, related MCP tools, and auto-approval state;
- pending agent enrollment requests;
- operator authority fingerprint and node-local configuration status.

### Operator objects

Resource Probe, browser operator session, pairing code exchange, MCP Credential,
Agent Permission, auto-approval policy, Enrollment Request, node settings.

### Actions

| Action | Expected result | Status |
| --- | --- | --- |
| Run Resource Probe | Measure host capacity server-side and refresh evidence. | `IMPLEMENTED` |
| Pair browser | Exchange one-time code for 10-minute, 1-day, 30-day, or long-lived session. | `IMPLEMENTED` |
| End browser session | Revoke the current browser session. | `IMPLEMENTED` |
| Create agent credential | Issue a bearer token once with selected scopes. | `IMPLEMENTED` |
| Edit agent permissions | Add/remove each scope and its independent default approval. | `IMPLEMENTED` |
| Grant full experimental control | Select all available scopes and mutation auto-approvals with a critical warning. | `IMPLEMENTED` |
| Rotate credential | Invalidate old sessions and reveal the new token once. | `IMPLEMENTED` |
| Revoke credential | Permanently deny future use of that credential. | `IMPLEMENTED` |
| Approve/reject enrollment | Resolve a pending agent pairing request. | `IMPLEMENTED` |
| Configure network/consensus | Select approved finality/RPC policy and validate reachability. | `UI_PENDING` |
| Configure updates/backups/log retention | Apply node-local operational policy with impact preview. | `API_PENDING` |

Full experimental control SHALL be explicit, visually critical, revocable, and
audited. It SHALL not bypass consensus, signatures, or protocol invariants.

## 13. Provider Plugins

### Purpose

This Advanced screen manages actual execution systems attached or installed on
the Hypervisor. A Provider Instance is backing infrastructure, not a
Consumer-facing service.

### Displays

- Plugin identity/version and installation source;
- Provider Instance ID, display name, configuration fingerprint, and health;
- model count and Runtime Binding readiness;
- discovered Model Deployments;
- retained artifacts and materialization state;
- recent probe/discovery errors.

### Operator objects

Provider Plugin, Provider Instance, health observation, Model Deployment,
Runtime Binding, installation artifact.

### Actions

| Action | Expected result | Status |
| --- | --- | --- |
| Attach existing Provider | Create an instance using validated Plugin configuration. | `IMPLEMENTED` |
| Probe Provider | Run real health/capability checks and retain evidence. | `IMPLEMENTED` |
| Discover models | Reconcile Provider model supply into Model Deployments. | `IMPLEMENTED` |
| Inspect Provider | Show config fingerprint, capabilities, health history, models, and Bundles. | `UI_PENDING` |
| Start/stop/restart managed Provider | Apply only when the Plugin declares lifecycle support. | `API_PENDING` |
| Detach Provider | Reject while Bundles/Bindings depend on it; preserve audit history. | `API_PENDING` |
| Roll back installation | Use recorded installation job boundaries. | `UI_PENDING` |
| Remove unused artifacts | Verify references before removal. | `UI_PENDING` |
| Open related Models/Bundles | Navigate with exact Provider filter. | `UI_PENDING` |

Provider credentials SHALL be represented by secret handles, never returned to
the Dashboard.

## 14. Models

### Purpose

Models manages the ordered path from model supply to a Runtime Binding suitable
for an immutable Bundle.

### Displays

- installation queue and materialization job status;
- Provider model reference and Model Deployment identity;
- artifact sets, file hashes, custody, and materialization location/status;
- capability bindings and definition hashes;
- Runtime Binding identity/readiness;
- related Provider and Bundle candidates.

### Operator objects

Model Install Job, Model Deployment, Model Artifact, Artifact Set,
Materialization, Capability Binding, Runtime Binding.

### Actions

| Action | Expected result | Status |
| --- | --- | --- |
| Queue model install | Create a node-side installation job from Provider type, model ID, and source. | `IMPLEMENTED` |
| Process/materialize installs | Execute pending jobs and show each result. | `IMPLEMENTED` |
| Register Bundle candidate | Persist the completed model install as a Bundle candidate. | `IMPLEMENTED` |
| Create Artifact Set | Persist an immutable content-addressed file manifest. | `IMPLEMENTED` |
| Bind Artifact Set | Associate an existing set with a Model Deployment. | `IMPLEMENTED` |
| Materialize Artifact Set | Place verified artifacts at a node-resolved destination. | `IMPLEMENTED` |
| Create Runtime Binding | Bind capability/version/hash to a ready Model Deployment. | `IMPLEMENTED` |
| Retry/cancel install | Act on a specific eligible job with retained failure evidence. | `UI_PENDING` |
| Remove unreferenced artifact/set | Reject removal when deployments or Bindings depend on it. | `UI_PENDING` |
| Inspect Runtime Binding | Show generation, Provider, model, capability, hashes, and Bundle links. | `UI_PENDING` |
| Continue to Bundle revision | Pre-fill the Bundle flow with the selected ready Binding. | `UI_PENDING` |

The UI SHALL not skip Model Deployment or Runtime Binding by passing unpersisted
form data directly to Endpoint creation.

## 15. Validation

### Purpose

Validation manages explicit Endpoint certification requests and their evidence.
It does not claim objective model identity or automatically judge response
quality.

### Displays

- Endpoint publication and Validation state;
- request/report ID, epoch, Validator assignment state, and timestamps;
- Verification Result and Certification Recommendation;
- evidence/custody status and retention deadline;
- Validation Bond and escrow state where applicable;
- expiration, maintenance, failure, and revalidation reason.

### Operator objects

Validation Request, Validation Session, Validation Report, evidence/custody
record, Certification, Bond/Escrow, maintenance event.

### Actions

| Action | Expected result | Status |
| --- | --- | --- |
| Request Validation | Submit a request for a persisted Endpoint identity. | `IMPLEMENTED` |
| Refresh evidence | Reconcile Endpoint Validation summaries. | `IMPLEMENTED` |
| Open Endpoint | Navigate to the exact Endpoint configuration. | `IMPLEMENTED` without object focus |
| Inspect report/history | Show immutable report, prior reports, evidence root, and recommendation. | `UI_PENDING` |
| Check evidence custody | Verify retained evidence and display failures. | `UI_PENDING` |
| Run custody/maintenance sweep | Process due maintenance without exposing concealed traffic identity. | `UI_PENDING` |
| Revalidate | Create a new request against the current Endpoint revision. | `UI_PENDING` |
| Withdraw pending request | Only when protocol state permits and consequences are shown. | `API_PENDING` |
| Inspect Bond/Escrow | Show locked amount, payer, release conditions, and finality. | `UI_PENDING` |

Publishing an Endpoint SHALL NOT automatically request Validation.

## 16. Network

### Purpose

Network exposes consensus, Registry replication, peer discovery, and preferred
remote Endpoint state. It explains why a node is or is not network-ready.

### Displays

- Network ID, chain ID, revision, node identity, and advertised address;
- CometBFT RPC/P2P reachability, chain height, sync, quorum, and trusted checkpoint;
- Registry replication state, peers, lag, conflicts, and last successful exchange;
- discovered remote nodes and Endpoint offers;
- attached Remote Endpoints and dependent proxy routes;
- readiness checks with evidence and exact blockers.

### Operator objects

Network identity, consensus status, trusted finality configuration, peer,
Registry object/replication state, remote node, Remote Endpoint, proxy dependency.

### Actions

| Action | Expected result | Status |
| --- | --- | --- |
| Recheck network | Refresh consensus, readiness, Registry, and remote discovery evidence. | `IMPLEMENTED` |
| Browse Market | Open canonical offer discovery. | `IMPLEMENTED` |
| Open Settings | Continue to host/network configuration. | `IMPLEMENTED` |
| Detach Remote Endpoint | Reject when a proxy dependency exists; otherwise remove local preference. | `IMPLEMENTED` |
| Inspect peer/node | Show identity, reachability, revision, lag, and trust evidence. | `UI_PENDING` |
| Attach discovered Endpoint | Add verified remote capacity from Network or Market. | `IMPLEMENTED` in Market |
| Resolve Registry conflict | Select only an authorized deterministic/governance resolution. | `UI_PENDING` |
| Reconcile/sync Registry | Execute bounded synchronization and show changed object IDs. | `UI_PENDING` |
| Update trusted checkpoint | Validate chain/quorum proof before replacing finality config. | `API_PENDING` |
| Add/remove network peer | Require identity, transport validation, and policy checks. | `API_PENDING` |
| Stage Proxy Endpoint | Continue from attached remote capacity to a local Endpoint draft. | `UI_PENDING` |

A reachable RPC port SHALL not by itself be displayed as healthy consensus.

## 17. Operator-to-MCP Parity

The Dashboard SHALL expose the same domain capabilities as MCP through operator-
appropriate workflows. It does not need a one-button copy of every MCP tool;
several read tools may be combined in one inspector.

| MCP capability group | Canonical Dashboard screen |
| --- | --- |
| Node health/status, host inspection, resources | Overview, Settings |
| Network status/peers | Network |
| Provider inventory/attach | Catalog, Provider Plugins |
| Model inventory/materialization | Models |
| Bundle list/get/activate/retire | Bundles |
| Endpoint list/publication/Validation | Endpoints, Validation |
| Wallet summary | Wallet |
| Scheduler policy and execution state | Agents & Sessions |
| Budget status | Wallet, Agents & Sessions |
| Audit query | Settings and object-specific activity inspectors |
| Agent credential permissions | Settings |

An action exposed to an MCP agent but absent from the Dashboard SHALL be tracked
as `UI_PENDING`. An action absent from both SHALL be `API_PENDING`; the UI SHALL
not simulate it.

## 18. Completion Checklist

A screen is functionally complete only when:

- every interactive-looking element has a documented action;
- every action invokes a real route or documented local UI transition;
- loading, empty, success, pending, blocked, rejected, and failed states exist;
- object IDs and protocol status are visible where needed for diagnosis;
- the operator sees the next safe step after success or failure;
- destructive/economic consequences are confirmed before submission;
- keyboard focus, touch targets, mobile scrolling, and screen-reader status are verified;
- no secret, private topology, or cross-Session data is leaked;
- deep links identify the relevant object, not merely the owning screen;
- automated tests cover the action-to-route contract and major state transitions.

The implementation roadmap SHOULD close `IMPLEMENTED` gaps in this order:

1. object inspectors and focused deep links;
2. Endpoint revision/revoke and Bundle preflight/drain;
3. Catalog installation plan, approval, apply, and rollback;
4. Validation report/evidence/custody operations;
5. Wallet accounting exports, Faucet handoff, and dispute controls;
6. Network peer, Registry conflict, and trusted-finality management;
7. full Consumer Session creation and settlement inspection.
