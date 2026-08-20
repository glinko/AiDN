# MCP Server Quickstart

This quickstart runs the local MCP-0001 node-control server against the same
Hypervisor service used by the FastAPI application.

## Prerequisites

- Python 3.11 or later;
- the repository virtual environment created with `uv sync`;
- a valid local Hypervisor configuration;
- an operator identity supplied by the host configuration.

From the repository root:

```powershell
uv sync
```

For restart-safe sessions, set the same state path used by the Hypervisor:

```powershell
$env:AIDN_HYPERVISOR_STATE_PATH = "$HOME/.local/share/aidn/operator/state.json"
```

The MCP store is written next to that file as
`mcp-control-state.json`. Without `AIDN_HYPERVISOR_STATE_PATH`, the server is
intentionally ephemeral and keeps its session, audit and idempotency state in
memory.

## Start the server

The console script starts newline-delimited JSON-RPC on stdin/stdout:

```powershell
uv run aidn-mcp-server `
  --agent-identity agent:local-test `
  --operator-identity operator:local-test `
  --control-session-id acs-local-test `
  --scope CAPABILITIES:READ `
  --scope NODE:READ `
  --scope BUNDLE:READ `
  --scope RESOURCES:READ
```

The process is intended to be spawned by an MCP client. Do not send shell
commands to it and do not parse human-readable logs from stdout. Each output
line is a JSON-RPC response; diagnostics belong on stderr in future transport
profiles.

## Protocol negotiation and minimal smoke input

AiDN accepts MCP protocol versions `2025-11-25`, `2025-06-18`, and
`2025-03-26`. Hermes Agent 0.20.x sends `2025-11-25` in its `initialize`
request even if an older `protocol_version` value is present in its YAML
configuration. Do not keep retrying or rewrite the request to work around
that hint: the server accepts the Hermes handshake directly.

The HTTP endpoint accepts authenticated `GET`/`HEAD` probes as well as JSON-RPC
`POST`. A probe is diagnostic only: it does not create a session or execute a
tool. `HEAD /mcp` returns `204` and `GET /mcp` returns the current server and
refresh instructions. Test the actual JSON-RPC handshake for a working
connection. A valid remote connection is one `initialize` request followed by one
`notifications/initialized` notification; the response includes an
`Mcp-Session-Id` header for subsequent calls.

The following sequence negotiates the protocol, completes the lifecycle, and
reads the capability tool:

```json
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"smoke-client","version":"0.1"}}}
{"jsonrpc":"2.0","method":"notifications/initialized"}
{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"aidn.capabilities.get","arguments":{}}}
```

With PowerShell, save those lines to a temporary input file and pipe them to
the process, or use the test harness below. The notification intentionally has
no response.

## Client integration and bounded workflows

This file describes the MCP wire protocol and a developer smoke test. It is
not necessary to send 128 requests to connect a client. A normal connection is
one `initialize` request, one `notifications/initialized` notification and a
small number of focused tool calls. A read-only inspection should usually be
finished in 3-8 tool calls; a plan/apply mutation is normally two tool calls
plus the separate operator approval request.

For Hermes, configure only the authenticated URL and token. The current
Hermes HTTP transport chooses the handshake version itself, so a
`protocol_version` YAML hint is not a substitute for a compatible server:

```yaml
mcp_servers:
  aidn:
    url: http://192.168.88.122:8766/mcp
    headers:
      Authorization: "Bearer <agent-token>"
    timeout: 180
    connect_timeout: 30
```

If Hermes reports `Unsupported MCP protocol version: 2025-11-25`, stop the
loop and check the node deployment rather than repeating `initialize`. Three
failed handshakes are enough to diagnose a transport or version problem; do
not spend the model context on repeated identical MCP calls.

### Live permission and tool-catalog refresh

The operator may add or remove scopes on an active Agent credential through the
Dashboard. Scope changes are deliberately live: the gateway re-resolves the
bearer credential on every request and refreshes the scoped control view. The
Hermes gateway does not need to restart and the existing `Mcp-Session-Id`
remains valid.

After an operator changes permissions, the Agent should make this bounded
checkpoint:

1. call `aidn.mcp.session_status` (or `aidn.capabilities.get`);
2. compare `tool_catalog.revision` with its cached value;
3. call the JSON-RPC `tools/list` method when the revision changes and replace
   the cached catalog;
4. only then call a newly granted tool.

`initialize` advertises `tools.listChanged`; the explicit revision is the
reliable refresh signal for the current HTTP transport. An attempted call to a
tool that is not in the cached catalog returns structured
`MCP_UNSUPPORTED_TOOL` details pointing to `tools/list`, rather than requiring
an indefinite retry loop.

If a node upgrade leaves a long-lived Hermes Telegram session showing the old
tool set, send `/reload-mcp` in that chat. Hermes treats this as an in-band
MCP-only reload: it reconnects the configured server and rebuilds the current
session's tool snapshot without restarting the gateway process or discarding
the conversation. A full `systemctl --user restart hermes-gateway.service`
is only a last-resort recovery for a gateway process that is itself unhealthy.

Credential revocation and token rotation are different from a scope update:
they intentionally close the transport session. In that case discard the
`Mcp-Session-Id`, run a new `initialize` handshake with the replacement token,
send `notifications/initialized`, and call `tools/list`. A node/service restart
also requires that normal handshake, but permission changes alone do not.

Keep the workflow bounded when an Agent is driving MCP:

- read this quickstart once, then call only the specific tools needed for the
  task;
- do not repeatedly issue the same tool with the same arguments when the
  result is unchanged;
- after two identical no-progress results, stop and report the blocker instead
  of retrying indefinitely;
- split large repository reviews into named files or small path ranges rather
  than asking a tool to dump the whole tree in one session.

The `messages` limit reported by a model gateway (for example, HTTP 422 after
more than 128 messages) is a provider/session policy, not an MCP requirement.
It indicates that the Agent loop accumulated too much history—usually because
of a repeated tool call. Start a fresh session after a failed loop and fix the
loop guard; increasing the provider limit alone only postpones the failure.

## Plan/apply example

Bundle mutations are never a single blind call. First request a plan:

```json
{"jsonrpc":"2.0","id":10,"method":"tools/call","params":{"name":"aidn.bundle.activate","arguments":{"bundle_id":"bundle-a","mode":"plan","request_id":"req-activate-1","idempotency_key":"idem-activate-1"}}}
```

Then pass the returned `plan_hash` to apply:

```json
{"jsonrpc":"2.0","id":11,"method":"tools/call","params":{"name":"aidn.bundle.activate","arguments":{"bundle_id":"bundle-a","mode":"apply","request_id":"req-activate-1","idempotency_key":"idem-activate-1","plan_hash":"sha256:<returned-plan-hash>"}}}
```

Activation is automatic in the default local profile. Retirement requires an
approved plan when the session approval policy is
`OPERATOR_CONFIRMATION`. The approval hash must be established through the
trusted operator approval boundary; it must not be fabricated by an Agent.
Approved plan hashes survive a process restart when the persistent state path
is configured.

Read the effective policy from both `aidn.capabilities.get` and
`aidn.policy.get` before applying a mutation. The value is credential-scoped:
`effective_approval_policy` (and `control_session.approval_policy`) describes
what this Agent token may apply, while `policy.scheduler` is only the local
routing policy. These values must agree. A stopped Bundle is a valid retirement
target; the apply result is `retired` with runtime status `already_stopped`, so
retrying a retirement does not turn an already-safe state into an internal
error.

### Attach an existing Provider

The MCP mutation boundary also supports attaching an already reachable
Provider endpoint. The session must be granted `PROVIDER:WRITE`; the default
policy requires the separate operator token to approve the plan.

```json
{"jsonrpc":"2.0","id":20,"method":"tools/call","params":{"name":"aidn.provider.attach","arguments":{"plugin_id":"llama.cpp","display_name":"Local llama.cpp","configuration":{"endpoint":"http://127.0.0.1:8080"},"mode":"plan","request_id":"req-provider-1","idempotency_key":"idem-provider-1"}}}
```

The loopback endpoint above is valid only when the MCP server and llama.cpp
runtime run on the same node. Do not copy a loopback URL into a remote Agent's
configuration. For a remote Agent, call the Hypervisor's authenticated HTTP
MCP gateway and keep the provider endpoint local to the Hypervisor node. The
old `192.168.88.20` example was a stale lab address and must not be used.

Approve the returned plan through `/mcp/operator/approve`, then repeat the
same arguments with `mode: "apply"` and the returned `plan_hash`. This action
registers only the Provider instance; model discovery and Runtime Binding
remain separate operations.

### Create and publish an Endpoint from an Agent

Endpoint lifecycle control is available through the narrowly scoped
`ENDPOINT:WRITE` permission. Existing credentials are not widened by an
upgrade: an operator must explicitly add this scope to the Agent credential
through the Dashboard permission catalog. The default credential policy is
`OPERATOR_CONFIRMATION` for both draft creation and publication. The Agent can
prepare plans, but the separate operator token must approve each plan unless
the operator deliberately selects `ENDPOINT:WRITE` under auto-approved scopes.

The Agent should first read `aidn.provider.list` and select a ready
`runtime_binding_id`, then select the enabled immutable `bundle_id` that
belongs to that binding (including the desired revision). The owner wallet is
read from the node and cannot be supplied or replaced by the Agent.

Create a draft (the nested objects are optional and default from the selected
Bundle/runtime policy):

```json
{"jsonrpc":"2.0","id":30,"method":"tools/call","params":{"name":"aidn.endpoint.create","arguments":{"runtime_binding_id":"rtb-example","bundle_id":"bundle-rtb-example-r4","display_name":"Qwen local endpoint","publication":{"visibility":"public","discoverable":true,"accepts_external_requests":true},"runtime":{"context_length":131072,"temperature":0.7,"top_p":0.9,"max_tokens":1024},"runtime_parameter_policy":{"context_length":{"value":131072,"consumer_editable":false},"temperature":{"value":0.7,"consumer_editable":true}},"local_agent_use":true,"mode":"plan","request_id":"req-endpoint-create-1","idempotency_key":"idem-endpoint-create-1"}}}
```

Approve the returned `plan_hash` through the operator endpoint, then repeat
the same request with `mode: "apply"`. The result contains the new
`endpoint_id`. Publication is a separate plan so an operator can review the
final Marketplace visibility, pricing, validation and parameter policy:

```json
{"jsonrpc":"2.0","id":31,"method":"tools/call","params":{"name":"aidn.endpoint.publish","arguments":{"endpoint_id":"ep-<created-id>","mode":"plan","request_id":"req-endpoint-publish-1","idempotency_key":"idem-endpoint-publish-1"}}}
```

After operator approval, apply that second plan with its `plan_hash`. With an
enabled CometBFT network the tool submits the canonical `ENDPOINT_PUBLISH`
wallet operation and returns `CONSENSUS_PENDING` until finality; it never
marks a local publication as final merely because a draft exists. A failed
readiness or canonical-wallet check is returned as a structured MCP error with
the blocking dimensions, so the Agent should report the blocker instead of
retrying the same call in a loop.

## Optional remote gateway

The HTTP gateway is disabled by default. Enable it only for a private LAN or
behind a trusted TLS reverse proxy. The MVP bearer transport is not intended
to be exposed directly to the public Internet.

```powershell
$env:AIDN_MCP_REMOTE_ENABLED = "true"
$env:AIDN_MCP_REMOTE_TOKEN = "replace-with-a-long-agent-secret"
$env:AIDN_MCP_OPERATOR_TOKEN = "replace-with-a-different-operator-secret"
# Use a new value when changing the persisted scope set for an existing node.
$env:AIDN_MCP_CONTROL_SESSION_ID = "acs-node-operator-1"
$env:AIDN_MCP_CONTROL_SESSION_AUTO_RENEW = "true"
$env:AIDN_MCP_CONTROL_SESSION_TTL_SECONDS = "3600"
# For a long-lived local Agent, remove the server-side lease.  Bearer
# credentials remain mandatory and revocable; only the extra Control Session
# expiry is disabled.
$env:AIDN_MCP_CONTROL_SESSION_STATELESS = "true"
uv run uvicorn aidn_hypervisor.main:build_app --factory --host 127.0.0.1 --port 8766
```

The Agent calls `POST /mcp` with `Authorization: Bearer <agent-token>`.
`initialize` returns an `Mcp-Session-Id`; send that header on subsequent
requests. The transport session is ephemeral, while the bound Control Session
and audit/plan state use the persistent MCP state file described above.
With `AIDN_MCP_CONTROL_SESSION_STATELESS=true`, the bound Control Session has
`expires_at: null`; the bearer credential is the revocation boundary. The MCP
transport session remains stateful and is recreated after a Hypervisor restart.

Hermes can consume this endpoint as a Streamable HTTP MCP server. Its
`mcp_servers` entry belongs on the Hermes host, and must contain the real Agent
token out of band; never commit it to this repository:

```yaml
mcp_servers:
  aidn-hypervisor:
    url: https://node.example.net/mcp
    headers:
      Authorization: "Bearer <agent-token>"
    timeout: 180
    connect_timeout: 15
```

Use the LAN URL only when the gateway is intentionally bound to the LAN and
firewalled to the Agent host. For a public deployment use the production mTLS
profile below. The operator token is separate and must not be placed in the
Agent's `mcp_servers` entry; approvals stay on the operator boundary.

If Hermes and the Hypervisor share a host, stdio is simpler and avoids opening
an HTTP listener:

```yaml
mcp_servers:
  aidn-hypervisor:
    command: /opt/aidn/.venv/bin/aidn-mcp-server
    args:
      - --agent-identity
      - agent:hermes
      - --operator-identity
      - operator:local
      - --control-session-id
      - acs-hermes
      - --scope
      - CAPABILITIES:READ
      - --scope
      - NODE:READ
      - --scope
      - BUNDLE:READ
      - --scope
      - RESOURCES:READ
    env:
      AIDN_HYPERVISOR_STATE_PATH: /var/lib/aidn/hypervisor-state.json
    timeout: 180
```

For mutations, add `PROVIDER:WRITE` or the other narrowly required scope only
after the operator has approved the policy. A remote stdio command on a
different node is not a substitute for the authenticated HTTP gateway.

When enabled, an authenticated Agent or Operator request renews the bound
Control Session lease when it enters its renewal window. Renewal does not
change the session identity, scopes, delegated budget or approved plans. An
idle session still expires after the configured TTL, and the next request with
the valid bearer credential can establish a fresh lease without changing
authority.

Operator actions use the separate token and never appear as Agent tools:

```text
POST /mcp/operator/approve
POST /mcp/operator/emergency-stop
POST /mcp/operator/emergency-stop/clear
```

Approval accepts only `{plan_hash, approval_reference}`. Emergency-stop and
clear accept `{reason, reference}`. While active, all Agent mutation tools and
new plan approvals are rejected; read tools remain available so an operator
can inspect the node and clear the stop.

## Production mTLS HTTP profile

For a remotely reachable operator boundary, use the dedicated launcher rather
than plain Uvicorn. It requires a server certificate/key, a CA that signs
client certificates, TLS 1.2 or newer, and exactly one worker. The client must
still send the Agent bearer token after the mTLS handshake.

```bash
export AIDN_MCP_REMOTE_ENABLED=true
export AIDN_MCP_REMOTE_TOKEN='long-agent-secret'
export AIDN_MCP_OPERATOR_TOKEN='different-operator-secret'
export AIDN_HYPERVISOR_STATE_PATH=/var/lib/aidn/hypervisor-state.json

uv run aidn-mcp-server-http \
  --host 0.0.0.0 \
  --port 9446 \
  --certfile /etc/aidn/tls/mcp-server.pem \
  --keyfile /etc/aidn/tls/mcp-server-key.pem \
  --ca-file /etc/aidn/tls/mcp-client-ca.pem
```

The private key must be readable only by the service account on POSIX hosts.
The launcher fails before binding when the certificate, key or CA is missing,
the CA is not usable, or the key permissions are too broad. Do not add CORS or
forward an unauthenticated `X-Forwarded-*` identity header; the gateway rejects
browser-origin requests and does not trust application-level certificate
headers.

### Secret Manager-backed TLS and rotation

For a long-running operator service, keep the certificate, private key and
client CA in the encrypted local Secret Manager instead of passing plaintext
file paths to the launcher. The master key is supplied out of band and is not
stored in the encrypted store:

```bash
export AIDN_SECRET_MANAGER_PATH=/var/lib/aidn/secrets.json
export AIDN_SECRET_MANAGER_MASTER_KEY='<base64-32-byte-master-key>'
export AIDN_MCP_REMOTE_ENABLED=true
export AIDN_MCP_REMOTE_TOKEN='long-agent-secret'
export AIDN_MCP_OPERATOR_TOKEN='different-operator-secret'

uv run aidn-mcp-server-http \
  --host 0.0.0.0 \
  --port 9446 \
  --cert-handle secret://mcp/tls/certificate \
  --key-handle secret://mcp/tls/private-key \
  --ca-handle secret://mcp/tls/ca \
  --tls-reload-seconds 5
```

The launcher materializes handles only into a private temporary directory with
`0600` files. It polls the encrypted store and accepts a rotation only after a
complete new certificate/key/CA bundle validates. It then performs a graceful
single-worker restart; durable Control Session, plan, audit and idempotency
state remains available, while clients must reconnect their ephemeral MCP
transport session. Rotate the three TLS handles atomically with the Secret
Manager `put_many()` operation where possible. A partial or invalid bundle does
not replace the active certificate and is not served.

## Troubleshooting a stuck Agent

If logs show the same tool and arguments repeating, cancel that run and start
a new session. Verify that the Agent's loop guard is enabled and that the MCP
server returns a terminal error for an unchanged/no-progress request. Do not
retry a `422 messages` response with the same accumulated history: it cannot
reduce the message count. The MCP handshake itself is still the three-line
sequence shown above.

## Tests

Run the MCP conformance tests:

```powershell
uv run pytest tests/test_mcp_server.py -q
uv run pytest tests/test_mcp_server.py tests/test_mcp_remote.py -q --override-ini addopts=
```

The tests cover lifecycle negotiation, scope-filtered catalogs, resources,
permission errors, plan hashes, idempotency, approval boundaries and stdio
output shape. The remote suite additionally covers bearer authentication,
transport session binding, operator approval, emergency stop, restart
persistence, HTTPS enforcement, mTLS context requirements, Secret Manager
materialization, hash-only rotation detection and private-key cleanup.

## Ubuntu acceptance

After the checkout and virtual environment are present on an Ubuntu operator
host, run the real listener/client rotation check from another machine:

```bash
./tools/run-remote-mcp-tls-rotation-acceptance.sh \
  --remote-ssh user@192.168.88.127 \
  --remote-repo /home/user/aidn/AiDN
```

The harness generates disposable CA/server/client identities, launches the
actual Secret Manager-backed MCP HTTP profile on loopback, verifies a client
certificate and MCP session, atomically rotates the server certificate, then
requires the new certificate and a new transport session. It does not touch
the host's production Secret Manager, Registry peers or persistent operator
state. The result is technical host acceptance, not evidence of organizational
independence.
