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

## Minimal smoke input

The following sequence negotiates the protocol, completes the lifecycle, and
reads the capability tool:

```json
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"smoke-client","version":"0.1"}}}
{"jsonrpc":"2.0","method":"notifications/initialized"}
{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"aidn.capabilities.get","arguments":{}}}
```

With PowerShell, save those lines to a temporary input file and pipe them to
the process, or use the test harness below. The notification intentionally has
no response.

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

## Optional remote gateway

The HTTP gateway is disabled by default. Enable it only for a private LAN or
behind a trusted TLS reverse proxy. The MVP bearer transport is not intended
to be exposed directly to the public Internet.

```powershell
$env:AIDN_MCP_REMOTE_ENABLED = "true"
$env:AIDN_MCP_REMOTE_TOKEN = "replace-with-a-long-agent-secret"
$env:AIDN_MCP_OPERATOR_TOKEN = "replace-with-a-different-operator-secret"
uv run uvicorn aidn_hypervisor.main:build_app --factory --host 127.0.0.1 --port 8766
```

The Agent calls `POST /mcp` with `Authorization: Bearer <agent-token>`.
`initialize` returns an `Mcp-Session-Id`; send that header on subsequent
requests. The transport session is ephemeral, while the bound Control Session
and audit/plan state use the persistent MCP state file described above.

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
