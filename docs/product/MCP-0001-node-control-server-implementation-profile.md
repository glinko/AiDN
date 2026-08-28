# MCP-0001 AiDN Node Control Server Implementation Profile

Status: Draft

Version: 0.1

This file is the implementation profile for the first MCP-0001 slice. The
normative design pack is maintained as the following documents:

- MCP-0001-aiDN-node-control-server.md
- MCP-0001-resources.md
- MCP-0001-tools.md
- MCP-0001-security.md
- MCP-0001-examples.md
- MCP-0001-workflows.md
- MCP-0001-errors.md

## Boundary

The server is a local control-plane adapter over an already constructed AiDN
Hypervisor service. It is not a consensus authority, a Provider API, a wallet
signing service, or a general-purpose host shell.

The default transport is MCP JSON-RPC over newline-delimited stdio. An opt-in
MVP remote transport is also implemented as an authenticated HTTP gateway
with a bearer token for the bound Agent Control Session and a separate bearer
token for operator approval and emergency-stop actions. It is a private
server-to-server/LAN boundary, not an Internet-facing production gateway.
The `aidn-mcp-server-http` launcher adds the production HTTP profile: Uvicorn
requires a client certificate signed by the configured CA, the gateway
requires HTTPS, TLS 1.2 or newer, and one process worker.

The authority path is:

```text
Agent
  -> MCP JSON-RPC / stdio
  -> ControlSession scope and approval policy
  -> HypervisorService and operator read models
  -> existing runtime, bundle, registry and ledger boundaries

Remote MCP client
  -> authenticated HTTP /mcp gateway
  -> ephemeral transport session bound to the same ControlSession
  -> same control-plane path

Operator channel
  -> separate authenticated HTTP operator routes
  -> approval or emergency-stop boundary
  -> same ControlSession authority
```

## Implemented Protocol Surface

The server supports MCP lifecycle methods:

- `initialize`
- `notifications/initialized`
- `ping`
- `tools/list`
- `tools/call`
- `resources/list`
- `resources/read`

It negotiates MCP protocol versions `2025-06-18` and `2025-03-26`.

Implemented tools are filtered by the active Control Session:

- capabilities, policy, host inspection, node status and health;
- network status and peers;
- Provider and model inventory;
- Bundle and Endpoint inventory, Endpoint draft creation and publication;
- resources, scheduler policy, wallet summary and delegated budget;
- Resident Steward status/context, deterministic reasoning routing, and
  durable bounded Escalation Task hand-offs;
- local MCP audit query;
- Bundle activation and retirement through plan/apply.

Resources mirror the same read models under `aidn://` URIs. The parameterized
resource `aidn://bundle/<bundle_id>` returns one Bundle revision and runtime
state.

## Control Session

Every server instance has one explicit `ControlSession` containing:

- agent identity;
- operator identity;
- scoped permissions;
- an optional lease expiry;
- optional delegated budget view;
- approval policy;
- approved plan hashes.

Permission names use the form `DOMAIN:ACTION`, with resource-specific suffixes
and `DOMAIN:*` support. Read tools are only advertised when their required
scope is granted. A denied call returns a stable MCP tool error and creates a
hash-linked local audit event.

## Mutation Contract

The current mutation surface exposes:

- `aidn.provider.attach` for an already reachable endpoint;
- `aidn.bundle.activate`;
- `aidn.bundle.retire`.
- `aidn.endpoint.create` and `aidn.endpoint.publish` for the endpoint-first
  draft/publication path, using the same configuration-hash and operator
  policy boundaries as the Dashboard.

Both require:

1. `mode: "plan"`;
2. a `request_id`;
3. an `idempotency_key`;
4. a plan hash for `mode: "apply"`;
5. explicit approval when the session approval policy requires it.

Plans contain the target revision, intended changes, risks, estimated downtime,
estimated Q atoms, and validation impact. Apply uses the current Bundle
revision and rejects a stale expected revision. Repeated apply with the same
session and idempotency key returns the original result; a different request
under that key is rejected.

Provider attachment is deliberately narrower than Plugin installation: it
accepts only a validated configuration for an already reachable endpoint and
does not download packages, execute host commands, manage models, or expose
credentials. It requires `PROVIDER:WRITE` and an explicit operator approval.

### Resident Steward escalation boundary

The `STEWARD:ESCALATE` permission exposes only non-executing hand-off tools:

- `aidn.steward.escalate` creates a durable task with an idempotency key and a
  fresh, bounded, redacted context;
- `aidn.steward.escalation.plan` attaches typed actions and a canonical plan
  hash;
- `aidn.steward.escalation.verify` checks declared postconditions;
- `aidn.steward.escalation.cancel` closes a hand-off without executing it.

`aidn.steward.escalations` and `aidn.steward.escalation.get` are read tools
under `STEWARD:READ`. Operator approval is deliberately outside the Agent
tool catalog and is performed through the operator API with an exact plan
hash and approval reference. None of these tools invokes a model, reserves a
Resource Broker lease, or executes the returned plan. The durable task store
rejects idempotency conflicts, redacts credential-looking context keys, and
rejects `SECRET` escalation payloads.

The current implementation does not expose wallet transfers, private keys,
arbitrary shell execution, consensus bypass, validation bypass, Provider
Plugin installation, model deployment, validation requests, or network join
operations.

## Remote Gateway and Emergency Stop

The remote gateway is disabled by default. It is enabled only when
`AIDN_MCP_REMOTE_ENABLED=true` and `AIDN_MCP_REMOTE_TOKEN` is configured. A
transport session is created by `initialize`, returned in `Mcp-Session-Id`,
and discarded on DELETE or process restart. The durable Control Session,
plans, idempotency records, approvals, audit chain, and emergency-stop state
remain in the operator-local MCP state file when a Hypervisor state path is
configured.

`AIDN_MCP_OPERATOR_TOKEN` is independent from the Agent token. When present,
it enables operator-only routes for exact plan approval and emergency-stop
activation/clear. An active emergency stop freezes all Agent mutation tools
and new remote plan approvals while preserving read access and the operator
clear action. Browser-origin requests are rejected; configure TLS or a
private reverse proxy before exposing the route outside a trusted LAN.

`AIDN_MCP_CONTROL_SESSION_AUTO_RENEW=true` enables a sliding lease for the
already-bound Control Session. `AIDN_MCP_CONTROL_SESSION_TTL_SECONDS` sets the
lease duration and defaults to one hour. A valid authenticated Agent or
Operator request may renew an expired persisted lease, but renewal never
changes identity, scopes, budget, approvals or emergency-stop state. Invalid
credentials cannot renew a session, and an idle session still expires until a
valid credential reconnects.

For a long-lived local Agent integration, set
`AIDN_MCP_CONTROL_SESSION_STATELESS=true`. In this mode the server-side
Control Session has no lease expiry (`expires_at: null`), while every remote
request still requires the active, revocable MCP bearer credential and its
stored scopes. This removes the idle-session failure seen by agents such as
Hermes without making the MCP route unauthenticated. The protocol transport
session (`Mcp-Session-Id`) remains stateful as required by MCP and is recreated
after a gateway restart. Turning stateless mode off restores a finite lease
using `AIDN_MCP_CONTROL_SESSION_TTL_SECONDS`.

The production launcher additionally requires either `--certfile`, `--keyfile`,
and `--ca-file`, or the corresponding Secret Manager handles. It configures
Uvicorn with `CERT_REQUIRED` and rejects a private key readable by group or
other users on POSIX systems. mTLS authenticates the transport peer; the
bearer token still selects the already-bound Agent Control Session and is never
replaced by an untrusted HTTP identity header. A Secret Manager-backed form
accepts `--cert-handle`, `--key-handle` and
`--ca-handle`, materializes them only as short-lived `0600` files, and watches
their hash-only fingerprint. A complete valid rotation triggers a graceful
single-worker restart; invalid or partial bundles leave the active certificate
in place. The Secret Manager master key remains outside the encrypted store.

## Data Protection

MCP responses use project read models and JSON-safe serialization. Private
wallet keys and secret values are not returned. Host inspection uses Python
platform and disk APIs only; it does not invoke a shell. Delegated budget data
is a bounded view and is not a spend authorization by itself.

Mutation audit events include the session identities, request and idempotency
references, action class, plan hash, and result. Audit events are linked by a
local hash chain and persisted atomically in `mcp-control-state.json` beside
the configured Hypervisor state file. The MCP file is operator-local state; it
is not included in the Ledger snapshot or consensus app-hash.

## RFC-0072 Event and Hook Extension

MCP-0001 remains the agent-to-Hypervisor control and authority boundary.
RFC-0072 defines the complementary Hypervisor-to-agent event plane: canonical
event envelopes, scoped Hooks, MCP live notifications, durable inbox delivery,
acknowledgments, retries, dead letters, and event-driven approval/job
notifications. A Hook never grants permission to invoke a mutation tool; every
resulting action continues through this profile's Control Session, scope,
policy, budget, and approval checks.

The first RFC-0072 implementation slice is now advertised by the live tool
catalog. The Event Bus, durable Inbox, scoped delivery, bounded retries,
dead-letter recovery, replay, and authorization tests are present. `HOOK:READ`
exposes Hook definitions, deliveries, dead letters, and metrics. `HOOK:MANAGE`
adds operator-owned `aidn.hook.create`, `update`, `pause`, `resume`, `delete`,
`test`, `ack`, `replay`, and `dead_letter_retry`. Mutations still require the
normal plan/apply, idempotency, scope, and operator-approval boundaries, and a
Hook is always restricted to the current Agent identity. Signed webhooks,
runtime wake-up adapters, threshold coalescing, and autonomous recovery remain
deferred RFC-0072 slices.

## RFC-0073 Resource Broker and Scheduler Extension

RFC-0073 defines the local Resource Broker as the final authority for Runtime
admission. MCP inspection and forecast tools may expose devices, allocatable
capacity, Leases, queue candidates, denials, and explainable scheduling
decisions. Manual reconciliation, drain, stop, pin, and unpin actions remain
subject to this profile's Control Session, scopes, operator policy, budget, and
approval checks.

An Agent is not the scheduler. Resource admission, Lease atomicity, owner
priority, and fail-closed restart reconciliation must continue to work when no
Agent or LLM is connected.

The first RFC-0073 surface is implemented: `RESOURCES:READ`
credentials can call `aidn.resources.status`,
`aidn.resource_broker.forecast`, `aidn.resource_broker.leases`, and
`aidn.resource_broker.explain_denial`; `SCHEDULER:READ` credentials can call
`aidn.scheduler.status`, `aidn.scheduler.queues`, and
`aidn.scheduler.candidates`. These projections never reserve capacity or
bypass operator policy. A separately granted `SCHEDULER:WRITE` scope exposes
the plan/apply `aidn.scheduler.reconcile` control; it only requests the local
fixed-point loop and cannot override Resource Broker admission or approval
policy. Runtime drain/stop/pin/unpin controls remain deferred until the full
Lease and Runtime state machine is in place.

## RFC-0075 Reasoning Router Extension

The first Reasoning Router slice is read-only. `STEWARD:READ` credentials can
call `aidn.steward.reasoning.providers` and
`aidn.steward.reasoning.route`, or read
`aidn://steward/reasoning/providers`. The Router applies provider capability,
context, privacy, trust, external-provider, latency, cost, delegated-budget,
and Resource Broker checks and returns typed rejection reasons. It never calls
a model or reserves a lease. Provider registration is an operator API action
and stores only bounded non-secret metadata; credential material remains in
the provider adapter/SecretStore boundary.

## Deferred Slices

The following remain unsupported until their authority boundaries are defined
and tested:

- QUIC transport and public-network gateway hardening;
- host preparation and clean-host installation;
- Provider Plugin installation and model deployment;
- Validation requests;
- Session open and Settlement actions;
- wallet transfer and signing workflows;
- cross-host recovery and upgrade orchestration;
- optional expert host execution.

An unsupported operation must not be represented as an implemented capability.

## Source Layout

- `src/aidn_hypervisor/mcp/server.py` contains the JSON-RPC server, control
  session, catalog, resources, plan/apply boundary and audit stream.
- `src/aidn_hypervisor/mcp/remote.py` contains the opt-in bearer-token HTTP
  gateway, file- and Secret Manager-backed mTLS launcher, rotation watcher,
  transport sessions, operator approval route and emergency stop.
- `src/aidn_hypervisor/secrets.py` contains encrypted local secret storage,
  atomic multi-handle updates, reload and hash-only fingerprints.
- `src/aidn_hypervisor/mcp/persistence.py` contains the versioned atomic local
  store for sessions, approvals, plans, idempotency and audit events.
- `src/aidn_hypervisor/mcp/__init__.py` exports the public construction API.
- `pyproject.toml` exposes the `aidn-mcp-server` console script.
- `pyproject.toml` also exposes `aidn-mcp-server-http` for the mandatory-mTLS
  HTTP profile.
- `tests/test_mcp_server.py` contains the initial conformance tests.
- `tests/test_mcp_remote.py` contains remote authentication, session,
  approval, emergency-stop and persistence tests.
- `docs/operations/mcp-server-quickstart.md` contains the local invocation
  and JSON-RPC smoke procedure.
