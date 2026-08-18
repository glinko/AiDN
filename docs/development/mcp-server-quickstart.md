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

The HTTP endpoint is POST-only, so a `405` response to `GET /mcp` or
`HEAD /mcp` is expected. Test the actual JSON-RPC handshake instead. A valid
remote connection is one `initialize` request followed by one
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
uv run uvicorn aidn_hypervisor.main:build_app --factory --host 127.0.0.1 --port 8766
```

The Agent calls `POST /mcp` with `Authorization: Bearer <agent-token>`.
`initialize` returns an `Mcp-Session-Id`; send that header on subsequent
requests. The transport session is ephemeral, while the bound Control Session
and audit/plan state use the persistent MCP state file described above.

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
