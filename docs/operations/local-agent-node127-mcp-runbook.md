# Local Agent Runbook: AiDN Node 127 MCP Control

## Purpose

This runbook gives a local AI agent the context and safe procedure for
operating the AiDN Hypervisor at `192.168.88.127` through MCP. It is an
operational guide, not a source of credentials or authority escalation.

Use this file together with:

- [MCP Server Quickstart](mcp-server-quickstart.md) for protocol and
  transport details;
- [MCP-0001 Implementation Profile](../product/MCP-0001-node-control-server-implementation-profile.md)
  for authority limits;
- [Agent Enrollment Operator Playbook](agent-enrollment-operator-playbook.md)
  for the exact messages an agent gives an operator during access setup;
- [Controlled LAN Testnet](controlled-lan-testnet.md) for the testnet
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

`192.168.88.127` is `node4` in the private controlled AiDN LAN testnet. Its
current profile is an AiDN Hypervisor operator node with
`AIDN_CONSENSUS_MODE=non_validator`; it submits to the configured CometBFT RPC
endpoint instead of binding its own validator RPC or P2P ports. It is used for
integration, recovery and MCP acceptance work.

Therefore, closed local ports `26656`, `26657` and `8545` on this host are not
evidence that consensus is down. Verify the configured consensus endpoint with
`aidn.network.status` and treat the result returned by that control-plane read
model as the node's consensus evidence.

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

For each plan-bound action, the Dashboard has two independent switches:

1. The permission exposes the tool to this credential.
2. **Operator approved by default** permits that already-authorized action to
   apply a valid plan without a second operator confirmation.

An agent may use unattended apply only when both settings are present and the
tool reports an `AUTO` approval mode through `aidn.capabilities.get`. The
experimental **Full rights** setting grants all currently implemented
agent-plane scopes plus those automatic approvals. It does not grant actual
operator identity, Wallet/private-key access, shell, Docker, SSH or consensus
control, and the agent must never describe it as operator authority.

The operator holds a different credential and exclusively controls:

- plan approval through `POST /mcp/operator/approve`;
- emergency stop and clear operations;
- wallet ownership binding or rotation;
- consensus, Docker, systemd, SSH and host configuration;
- provider installation, model deployment, Endpoint publication, validation,
  Session opening, Settlement and wallet transfers until their dedicated MCP
  authority boundaries are implemented.

An agent must never request, infer, store or use the operator credential.

## Operator Provisioning of the Agent Token

### Dashboard-Native Enrollment

For a new agent, the preferred path does not require copying a token or giving
the agent host-shell access. The operator may need to unlock the Settings
screen once with a local pairing code. The agent creates an ephemeral X25519
encryption key locally and submits its public key to:

```text
POST /operators/dashboard/access/agent-enrollment/requests
```

The response contains a request ID and one-time retrieval secret. The agent
keeps both in its own secret store and polls the request endpoint with the
`X-AiDN-Enrollment-Secret` header. It cannot receive a credential while the
request remains pending.

The operator opens **Settings -> Agent enrollment requests**, verifies the
agent label and key fingerprint, then selects **Approve** or **Reject**. An
approval creates a dedicated MCP credential and encrypts it to the agent's
ephemeral X25519 public key. The browser sees only request metadata; it never
receives the token. The agent decrypts the returned envelope locally, stores
the token in its normal secret mechanism, and then initializes `/mcp`.

After submitting a request, the agent SHALL tell the operator only the node
URL, request label, key fingerprint and expiration time. It SHALL NOT show or
ask for the retrieval secret, pairing code, MCP credential or operator token.
The exact interaction wording and recovery steps are normative for this MVP in
[Agent Enrollment Operator Playbook](agent-enrollment-operator-playbook.md).

Enrollment requests expire after ten minutes. They are designed for controlled
LAN MVP operation; public-network use additionally requires the production
HTTPS/mTLS transport profile and admission/rate-limit policy.

The model does not need to see the token. The MCP client transport needs it to
add the `Authorization` header. The safe pattern is therefore:

```text
Node operator secret store
    -> one-time secure transfer to the agent-host secret store
    -> agent launcher injects process environment variable
    -> MCP client adds Bearer header
    -> model calls named MCP tools without receiving the token text
```

### Legacy Manual Credential Transfer

Use this path only when the receiving client cannot implement encrypted agent
enrollment. The operator creates a dedicated credential from the node's React
dashboard:

1. On the node terminal, run `aidn-operator pair`.
2. Open `Settings` in the React dashboard and paste the one-time pairing code.
3. Choose **Issue token**, label it for the receiving agent, and copy the value
   while it is displayed. The dashboard never displays it again.
4. Transfer that value once to the agent host's secret store and close the
   reveal notice.

The resulting value becomes `AIDN_NODE127_MCP_AGENT_TOKEN` on the agent host.
It is a dedicated Agent credential, not a Wallet, operator token or consensus
key. The two following values must never be equal:

```text
Agent host: AIDN_NODE127_MCP_AGENT_TOKEN
Node operator boundary: AIDN_MCP_OPERATOR_TOKEN
```

Use a secure out-of-band channel for the one-time transfer, such as a password
manager share, an encrypted vault entry or a direct session on the agent host.
Do not send it in chat, e-mail, source control, a ticket, a shell history or a
dashboard form. Do not obtain it by having the agent SSH to the node.

### Linux Agent Host

For a manually launched local agent, store the value outside the repository in
a file readable only by its operating-system account:

```bash
install -d -m 700 "$HOME/.config/aidn-agent"
umask 077
printf '%s' '<token-entered-by-operator>' > "$HOME/.config/aidn-agent/node127-mcp-token"
```

Use a launcher that reads the file only into the child process environment:

```bash
#!/usr/bin/env bash
set -euo pipefail
export AIDN_NODE127_MCP_AGENT_TOKEN="$(<"$HOME/.config/aidn-agent/node127-mcp-token")"
exec /path/to/local-agent "$@"
```

For a long-running service or container, prefer its native secret mechanism:
systemd credentials, Docker secrets, Kubernetes Secrets or an organization
vault. The entrypoint reads the secret file and exports the variable only for
the MCP client process. Never place the value directly in a systemd unit,
Docker command line, image layer or `.env` file in the repository.

### Windows Agent Host

Use the user's credential vault or another DPAPI-backed secret provider. A
launcher retrieves the value only for the process that starts the local agent:

```powershell
# Example after the operator has stored this secret in a configured vault.
$env:AIDN_NODE127_MCP_AGENT_TOKEN = Get-Secret aidn-node127-mcp-token -AsPlainText
& 'C:\Path\To\local-agent.exe'
Remove-Item Env:AIDN_NODE127_MCP_AGENT_TOKEN -ErrorAction SilentlyContinue
```

`Get-Secret` is supplied by a configured PowerShell SecretManagement vault; a
Windows Credential Manager or enterprise vault launcher may serve the same
role. Do not use `setx`, a checked-in `.env` file, a desktop shortcut argument
or a plain-text project configuration because those make the credential
persistent or broadly readable.

### Client Configuration

Configure the MCP client to obtain the token from its environment or secret
provider, not from the agent prompt. A generic representation is:

```yaml
name: aidn-node127
url: http://192.168.88.127:8000/mcp
authorization: Bearer ${AIDN_NODE127_MCP_AGENT_TOKEN}
protocol_version: "2025-03-26"
```

MCP client configuration formats differ. If a client does not support
environment interpolation in headers, use its own secret-reference mechanism
or a launcher/reverse proxy that adds the header. Do not replace the secure
reference with a literal token.

### Rotation and Revocation

Rotate the Agent token from **Settings -> Agent credentials** when the agent
host, its configuration or an operator session might have been exposed. The
replacement value is shown once and the previous credential is revoked
immediately, including its active MCP transport sessions. Use **Revoke** when
no replacement is needed. The node operator then updates the agent-host secret
entry through the approved deployment procedure and then restarts the agent.
The old token must stop authenticating. The agent reconnects with a new MCP
transport session and repeats its required first-read sequence.

The current gateway is plain HTTP on a private LAN. This is acceptable only
inside that controlled network. Before crossing an untrusted LAN, Wi-Fi, VPN
or the public Internet, move the gateway to the documented mTLS HTTPS profile;
local secret storage alone does not encrypt a bearer token in transit.

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

For resource-sensitive work, also read `aidn.resource_broker.leases`,
`aidn.scheduler.status`, and `aidn.scheduler.candidates` before attempting a
Bundle activation. A `RESOURCE_WAIT` candidate is a queueing decision, not a
Provider failure; use its required/free/shortfall projection instead of
blindly retrying activation.

## Agent Permission Boundary

Each Dashboard credential has an explicit allow-listed MCP permission set.
The operator changes it in **Settings -> Agent credentials -> Permissions**.
The Dashboard closes existing MCP transport sessions when it saves a change;
the Agent SHALL initialize again and use `tools/list` as the authoritative
inventory. Granting a permission only exposes a corresponding implemented
tool. It never bypasses plan approval, enables a deferred tool, exposes a
private key, grants arbitrary shell access, or creates consensus authority.

For Bundle activation the exact permission is `BUNDLE:ACTIVATE`. The Agent
still creates a plan first and follows the returned approval policy before it
applies that plan.

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
