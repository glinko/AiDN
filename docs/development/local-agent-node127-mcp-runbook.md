# Local Agent Runbook: AiDN Node 127 MCP Control

## Purpose

This runbook gives a local AI agent the context and safe procedure for
operating the AiDN Hypervisor at `192.168.88.127` through MCP. It is an
operational guide, not a source of credentials or authority escalation.

Use this file together with:

- [MCP Server Quickstart](./mcp-server-quickstart.md) for protocol and
  transport details;
- [MCP-0001 Implementation Profile](../product/MCP-0001-node-control-server-implementation-profile.md)
  for authority limits;
- [Controlled LAN Testnet](./controlled-lan-testnet.md) for the testnet
  topology and evidence boundary.

## What AiDN Is

AiDN is a control plane for running AI capabilities as managed Endpoint
services. An operator assembles an immutable Bundle from a Provider, model,
Runtime and resource profile. The Bundle may then back an Endpoint. Sessions,
Usage Reports, Accounting Contracts and Settlement apply contractual bounds to
the Endpoint service; they do not turn upstream Provider cost into an
unbounded Consumer charge.

For this MCP slice, the practical lifecycle is:

```text
Provider -> model/runtime -> immutable Bundle -> Endpoint -> Request/Result
```

The agent must preserve the distinction between these objects. A Provider is
not an Endpoint, and attaching a Provider is not permission to publish a
service, deploy a model, spend Q, or modify consensus.

## Node 127 Assignment

`192.168.88.127` is `node4` in the private controlled AiDN LAN testnet. It is
a CometBFT validator host and an AiDN Hypervisor operator node used for
integration, recovery and MCP acceptance work.

It is **not** a public Internet node, production network, or proof of
organizational independence. The MVP accepts it as a separate controlled-testnet
operator only through an explicit project policy assumption. Do not claim that
the node or the testnet provides public-finality, independent-ownership or
mainnet evidence.

Current operator-facing URLs:

```text
Hypervisor API and MCP gateway: http://192.168.88.127:8000
MCP endpoint:                 http://192.168.88.127:8000/mcp
React dashboard:              http://192.168.88.127:8000/operators/dashboard/react
```

The gateway is a private LAN control boundary. Do not expose it to the public
Internet and do not treat a bearer token as a substitute for production mTLS.

## Credentials and Authority

The local agent receives only an **Agent MCP token** through its secure runtime
configuration, for example as `AIDN_NODE127_MCP_AGENT_TOKEN`. Never put that
token, an operator token, a wallet key, SSH password or a Secret Manager key in
a prompt, repository file, tool argument, log or dashboard field.

The Agent token may read the node and use only the mutation tools advertised by
`tools/list` for the current Control Session. On this node the intended normal
write boundary is Provider attachment. The current deployment grants
`PROVIDER:WRITE`; Bundle management must be considered read-only unless
`tools/list` explicitly advertises a corresponding write capability.

The operator holds a different credential and exclusively controls:

- plan approval through `POST /mcp/operator/approve`;
- emergency stop and clear operations;
- wallet ownership binding or rotation;
- consensus, Docker, systemd, SSH and host configuration;
- provider installation, model deployment, Endpoint publication, validation,
  Session opening, Settlement and wallet transfers until their dedicated MCP
  authority boundaries are implemented.

An agent must never request, infer, store or use the operator credential.

## Connect Procedure

Configure the MCP client with the private endpoint and an environment-backed
Agent token. The exact client configuration syntax is client-specific; the
required transport values are:

```yaml
name: aidn-node127
url: http://192.168.88.127:8000/mcp
authorization: Bearer ${AIDN_NODE127_MCP_AGENT_TOKEN}
protocol_version: "2025-03-26"
```

Use MCP JSON-RPC `initialize`, store the returned `Mcp-Session-Id`, and send
that header with later requests. Then send `notifications/initialized` and call
`tools/list`. The tool list is authoritative for the current session; do not
invent a tool because it appears in a roadmap or another environment.

The durable AiDN Control Session normally uses a one-hour sliding lease with
auto-renew. A valid authenticated request renews it during the renewal window.
After an idle expiry, reconnect and initialize again with the same Agent token;
this does not alter scopes, approved plans, budgets or operator identity.

## Required First Read

Before proposing any mutation, make these MCP calls in order and retain the
returned IDs and health facts in the agent work log:

1. `aidn.node.health`
2. `aidn.node.status`
3. `aidn.network.status`
4. `aidn.resources.status`
5. `aidn.wallet.summary`
6. `aidn.provider.list`
7. `aidn.model.list`
8. `aidn.bundle.list`
9. `aidn.endpoint.list`
10. `aidn.audit.query`

Continue only when node health is healthy and the intended operation has a
clear resource, Provider and Endpoint relationship. A successful dashboard
readiness check is useful context, but it does not grant the Agent new scope.

## Allowed Mutation Workflow

### Attach an already running Provider

Use `aidn.provider.attach` only for a Provider endpoint that the operator has
already made reachable and authorized. It registers the Provider configuration;
it does not install packages, execute a host process, discover a model,
construct a Bundle or publish an Endpoint.

1. Call `aidn.provider.attach` with `mode: "plan"`, a unique `request_id` and
   a unique `idempotency_key`.
2. Inspect the returned target, risks, validation impact and `plan_hash`.
3. Report the plan to the operator. Include the endpoint, plugin ID, requested
   permissions, `plan_hash`, request ID and expected effect. Do not apply it.
4. Wait for an explicit operator approval made through the separate operator
   boundary.
5. Call the same MCP tool with `mode: "apply"`, the same request and
   idempotency identifiers, and the approved exact `plan_hash`.
6. Re-read `aidn.provider.list`, `aidn.model.list`, `aidn.bundle.list`,
   `aidn.endpoint.list` and `aidn.audit.query`. Report the result without
   claiming any downstream object was created unless it is present in its own
   inventory.

The same plan/apply discipline applies to any future mutation tool that is
actually advertised. Do not treat a successful plan as a completed change.

## Prohibited Actions

The following are out of scope even if an error message makes them appear
convenient:

- running shell commands, editing JSON state, changing Docker containers or
  systemd services;
- clearing pending consensus records or changing CometBFT ports;
- creating, importing, exporting or rotating a wallet;
- passing an Agent token to `/mcp/operator/*` routes;
- fabricating an approval reference, `plan_hash`, Provider receipt or Usage
  value;
- treating `UNAVAILABLE` Usage as zero;
- creating a public Endpoint, a Settlement or a Q transfer through an
  unsupported MCP tool;
- presenting this controlled LAN testnet as independent or production-ready.

## Failure Handling

| Condition | Agent response |
| --- | --- |
| `MCP_CONTROL_SESSION_EXPIRED` | Reconnect, initialize, obtain a new transport session ID, and retry only an idempotent read or the same idempotent request. |
| `MCP_APPROVAL_REQUIRED` | Stop at the plan boundary and report the exact `plan_hash` to the operator. |
| Scope or deferred-tool error | Record the stable error and report that the operation is unsupported. Do not seek a bypass. |
| Consensus unavailable | Keep to read-only diagnosis; report node/network facts. Do not alter host or chain configuration. |
| Existing different wallet binding | Stop and report the conflict. Never delete state or retry with a different wallet. |
| Resource probe unavailable or zero | Report the missing evidence. Do not invent capacity from a Provider process or model name. |
| Provider or model missing | Re-read inventory and report the gap. Provider installation and model deployment require their own approved workflow. |

## Completion Report Format

After each operation, produce a concise operator report containing:

```text
Node: node4 / 192.168.88.127
MCP control session: <ID, never token>
Action: read-only inspection | provider attach plan | provider attach apply
Result: success | blocked | failed
Evidence: relevant inventory IDs, plan hash, audit event IDs and health state
Authority: Agent scope used; operator approval reference if applicable
Limitations: unavailable measurements, deferred tools, or unresolved faults
Next safe action: one explicit operator or agent action
```

Never include credentials, private keys, raw request payloads containing
secrets, or claims beyond the evidence returned by the node.
