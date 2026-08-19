# AiDN configuration and hardcoded-parameter inventory

Status: inventory (2026-08-19)

The canonical operator template is [`config/aidn.env.example`](../../config/aidn.env.example).
It documents every supported `AIDN_*` runtime variable in one place without
containing secrets. The systemd templates already consume an `EnvironmentFile`;
the Ubuntu bootstrap currently generates the same variables in its protected
`run-hypervisor.sh` wrapper.

For deployments that need one file shared by the Hypervisor, MCP entry points,
the operator CLI, and the external Faucet, use the companion
[`config/aidn.config.example.toml`](../../config/aidn.config.example.toml).
Set `AIDN_CONFIG_FILE` to a host-only copy. Its `[env]` table uses the same
variable names as the `.env` template, and existing environment values always
win. This makes migration incremental: no systemd wrapper or existing secret
injection mechanism has to be replaced in order to adopt the file.

### Applying a TOML profile on Ubuntu

```sh
sudo install -o root -g aidn -m 0640 config/aidn.config.example.toml /etc/aidn/aidn.toml
printf '%s\n' 'AIDN_CONFIG_FILE=/etc/aidn/aidn.toml' | sudo tee /etc/aidn/hypervisor.env >/dev/null
sudo chown root:aidn /etc/aidn/hypervisor.env
sudo chmod 0640 /etc/aidn/hypervisor.env
sudo systemctl restart aidn-hypervisor
```

The example contains safe loopback/disabled defaults. Set the node identity,
state paths, and any deliberately enabled LAN, MCP, provider-broker, or
CometBFT options in the host-only TOML file. Inject tokens and signing keys
through the Secret Manager or a separate protected `EnvironmentFile`; do not
copy them into the TOML profile. If an existing EnvironmentFile already sets
an `AIDN_*` variable, that value intentionally wins over the TOML value; remove
that duplicate or change it explicitly. To see which source won, inspect the
service environment and the dashboard's effective network/consensus evidence
rather than relying on the template alone.

## What is configurable today

| Area | Configuration surface | Important defaults / notes | Source of truth |
| --- | --- | --- | --- |
| Node and dashboard | `AIDN_NODE_ID`, `AIDN_OPERATOR_ID`, `AIDN_HYPERVISOR_*`, `AIDN_DASHBOARD_ACCESS_ALLOW_INSECURE_LAN` | Loopback `127.0.0.1:8766`; LAN bind is explicit and restarts the service | `src/aidn_hypervisor/main.py`, `dashboard_network_access.py`, `tools/aidn-operator-bootstrap-ubuntu.sh` |
| Capacity | `AIDN_RESOURCE_PROBE_MODE`, `AIDN_RESOURCE_CAPACITY_PATH`, `AIDN_RESOURCE_GPU_VRAM_JSON` | `auto` probes CPU/RAM/NVIDIA VRAM; a valid capacity report wins over a live probe | `src/aidn_hypervisor/resource_probe.py` |
| MCP / local agent | `AIDN_MCP_REMOTE_*`, `AIDN_MCP_MAX_*`, `AIDN_MCP_CONTROL_SESSION_*`, `AIDN_MCP_SCOPES`, `AIDN_MCP_HOST_ROOT` | Remote MCP is off by default; body limit is 1 MiB, transport sessions 128, control-session TTL 3,600 s; stateless mode removes expiry | `src/aidn_hypervisor/main.py`, `mcp/server.py`, `mcp/remote.py` |
| Inference admission | `AIDN_INFERENCE_MAX_REQUEST_BYTES`, `AIDN_INFERENCE_MAX_MESSAGES` | Defaults are 4 MiB and 512 messages; these guard the HTTP request and are independent of model context | `src/aidn_hypervisor/inference_gateway.py` |
| Consensus | `AIDN_CONSENSUS_*`, `AIDN_COMETBFT_*` | Consensus defaults to disabled; local RPC `tcp://127.0.0.1:26657`, ABCI `127.0.0.1:26658`, chain `aidn-localnet-1` | `src/aidn_hypervisor/main.py`, `operator_cometbft_install.py` |
| Host runtime broker | `AIDN_ENABLE_PROVIDER_RUNTIME_INSTALL`, `AIDN_PROVIDER_RUNTIME_*` | Must be explicitly enabled and socket-bound; broker is the privilege boundary for host-mutating installs | `src/aidn_hypervisor/main.py`, `tools/aidn-operator-bootstrap-ubuntu.sh` |
| Network trust/policy | `AIDN_REGISTRY_REPLICATION_CONFIG`, `AIDN_REMOTE_TRUST_ANCHOR_CONFIG`, `AIDN_COMETBFT_FINALITY_CONFIG`, `AIDN_PROTOCOL_AUTHORITY_POLICY_*`, `AIDN_EPOCH_*`, `AIDN_NETWORK_ID` | Paths and schedule inputs are configurable; loaded artifacts remain schema- and signature-checked | `src/aidn_hypervisor/main.py`, `consensus/deployment.py` |
| Optional custody | `AIDN_HYPERVISOR_CUSTODY_SIGNING_KEY` | Secret; opt-in only | `src/aidn_hypervisor/main.py` |
| External Faucet | `AIDN_FAUCET_*` | Faucet has a separate systemd unit and secret set; do not share signing material with the node | `services/aidn-faucet/src/aidn_faucet/cli.py` |

### Complete service environment catalog

This is the exhaustive list of variables consumed by the Hypervisor, the
external Faucet, or the supported operator/acceptance surfaces (as opposed to
ad-hoc shell locals):

- **Identity/state:** `AIDN_NODE_ID`, `AIDN_OPERATOR_ID`,
  `AIDN_CONFIG_FILE`,
  `AIDN_HYPERVISOR_STATE_PATH`, `AIDN_HYPERVISOR_BUNDLES_PATH`,
  `AIDN_HYPERVISOR_MODEL_STORE_PATH`, `AIDN_OPERATOR_API_URL`.
- **Dashboard/listener:** `AIDN_HYPERVISOR_API_HOST`,
  `AIDN_HYPERVISOR_API_PORT`, `AIDN_HYPERVISOR_BIND_HOST_PATH`,
  `AIDN_HYPERVISOR_RESTART_ON_BIND_CHANGE`,
  `AIDN_DASHBOARD_ACCESS_ALLOW_INSECURE_LAN`,
  `AIDN_INFERENCE_PUBLIC_BASE_URL`.
- **Capacity/custody:** `AIDN_RESOURCE_PROBE_MODE`,
  `AIDN_RESOURCE_CAPACITY_PATH`, `AIDN_RESOURCE_GPU_VRAM_JSON`,
  `AIDN_HYPERVISOR_CUSTODY_SIGNING_KEY`.
- **MCP and TLS:** `AIDN_MCP_REMOTE_ENABLED`, `AIDN_MCP_REMOTE_TOKEN`,
  `AIDN_MCP_OPERATOR_TOKEN`, `AIDN_MCP_REMOTE_HOST`, `AIDN_MCP_REMOTE_PORT`,
  `AIDN_MCP_REMOTE_TLS_REQUIRED`, `AIDN_MCP_MAX_BODY_BYTES`,
  `AIDN_MCP_MAX_TRANSPORT_SESSIONS`, `AIDN_MCP_TLS_CERTFILE`,
  `AIDN_MCP_TLS_KEYFILE`, `AIDN_MCP_TLS_CA_FILE`,
  `AIDN_MCP_TLS_CERT_HANDLE`, `AIDN_MCP_TLS_KEY_HANDLE`,
  `AIDN_MCP_TLS_CA_HANDLE`, `AIDN_MCP_TLS_RELOAD_SECONDS`,
  `AIDN_MCP_CONTROL_SESSION_STATELESS`,
  `AIDN_MCP_CONTROL_SESSION_AUTO_RENEW`,
  `AIDN_MCP_CONTROL_SESSION_TTL_SECONDS`, `AIDN_MCP_CONTROL_SESSION_ID`,
  `AIDN_MCP_AGENT_IDENTITY`, `AIDN_MCP_OPERATOR_IDENTITY`,
  `AIDN_MCP_SCOPES`, `AIDN_MCP_HOST_ROOT`.
- **Inference guardrails:** `AIDN_INFERENCE_MAX_REQUEST_BYTES`,
  `AIDN_INFERENCE_MAX_MESSAGES`.
- **Consensus/CometBFT:** `AIDN_CONSENSUS_MODE`,
  `AIDN_CONSENSUS_NODE_ID`, `AIDN_CONSENSUS_VALIDATOR_PUBKEY`,
  `AIDN_CONSENSUS_STRICT_OPERATION_COVERAGE`, `AIDN_COMETBFT_ENDPOINT`,
  `AIDN_COMETBFT_CHAIN_ID`, `AIDN_COMETBFT_SERVICE`,
  `AIDN_COMETBFT_CONFIG_PATH`, `AIDN_COMETBFT_ABCI_STATE_PATH`,
  `AIDN_COMETBFT_ABCI_HOST`, `AIDN_COMETBFT_ABCI_PORT`,
  `AIDN_COMETBFT_ABCI_QUERY_TIMEOUT_SECONDS`,
  `AIDN_COMETBFT_ABCI_RETAINED_SNAPSHOTS`,
  `AIDN_COMETBFT_ABCI_SNAPSHOT_LEASE_SECONDS`.
- **Privileged runtime broker:** `AIDN_ENABLE_PROVIDER_RUNTIME_INSTALL`,
  `AIDN_PROVIDER_RUNTIME_DISPATCHER`, `AIDN_PROVIDER_RUNTIME_BROKER_SOCKET`,
  `AIDN_PROVIDER_RUNTIME_OPERATOR_NAME`,
  `AIDN_PROVIDER_RUNTIME_OPERATOR_UID`,
  `AIDN_PROVIDER_RUNTIME_OPERATOR_GID`,
  `AIDN_PROVIDER_RUNTIME_OPERATOR_HOME`.
- **Trust/policy/scheduling:** `AIDN_SECRET_MANAGER_PATH`,
  `AIDN_SECRET_MANAGER_MASTER_KEY`, `AIDN_REGISTRY_REPLICATION_CONFIG`,
  `AIDN_REMOTE_TRUST_ANCHOR_CONFIG`, `AIDN_COMETBFT_FINALITY_CONFIG`,
  `AIDN_PROTOCOL_AUTHORITY_POLICY_PATH`,
  `AIDN_PROTOCOL_AUTHORITY_POLICY_JSON`, `AIDN_NETWORK_ID`,
  `AIDN_EPOCH_DURATION_SECONDS`, `AIDN_EPOCH_START_TIME`,
  `AIDN_EPOCH_PARAMETER_VERSION`, `AIDN_EPOCH_TASK_SET_VERSION`,
  `AIDN_EPOCH_PROTOCOL_VERSION`, `AIDN_CONSENSUS_GENESIS_ACCOUNTS_JSON`,
  `AIDN_FAUCET_TREASURY_GENESIS_MANIFEST`.
- **Provider acceptance probes:** `AIDN_LLAMACPP_ENDPOINT`,
  `AIDN_LLAMACPP_MODEL`, `AIDN_LLAMACPP_LIVE`, `AIDN_VLLM_ENDPOINT`,
  `AIDN_VLLM_MODEL`, `AIDN_OLLAMA_ENDPOINT`, `AIDN_OLLAMA_MODEL`.
- **Faucet service:** `AIDN_FAUCET_HOST`,
  `AIDN_FAUCET_PENDING_RECONCILE_INTERVAL_SECONDS`,
  `AIDN_FAUCET_AGENT_TOKEN`, `AIDN_FAUCET_CREATOR_TOKEN`,
  `AIDN_FAUCET_FINALITY_CONFIG`, `AIDN_FAUCET_URL` (acceptance tooling).

Plugin-container identity variables (`AIDN_PLUGIN_HOST_*`) are also
documented in the template, but are generated per approved installation and
must not be set as global operator configuration.

### Web build and UI defaults

The browser bundles have a separate build-time surface. These values are not
read from the Hypervisor process environment:

| Surface | Current value | How to override / migrate |
| --- | --- | --- |
| Website API | `VITE_WEBSITE_API_BASE` or `/api/site/v1` | Set at website build time; production should use the reverse proxy route |
| Website dev proxy | `AIDN_WEBSITE_BACKEND_URL` or `http://127.0.0.1:8000` | Set in the Vite environment; never use this as a production public URL |
| Website demo mode | `VITE_WEBSITE_DEMO=true` or Vite `demo` mode | Demo metrics are explicitly illustrative and must stay disabled in production |
| Install command ref | `VITE_AIDN_INSTALL_REF` or `operator-bootstrap-v0.1.0-rc1` | Pin an immutable tag/commit; never silently fall back to `main` |
| Dashboard API proxy | `VITE_AIDN_API_ROOT` or same-origin | Build-time only; the browser must not embed credentials |
| Dashboard request timeout | `15,000 ms` in `web/operator-dashboard/src/lib/api.ts` | Candidate for a build/runtime API policy, with bounded minimum/maximum |
| Provider form fallbacks | `temperature=0.7`, `top_p=0.9`, `top_k=40`, `repeat_penalty=1.1`, `max_tokens=512`, `context_length=4096` (llama/Ollama), `8192` (vLLM), GPU utilization `0.9` | These are UI fallback drafts only. The API response and Bundle revision must remain authoritative; remove duplication once a provider schema endpoint is available |
| Model form fallback | Endpoint `http://127.0.0.1:8080`, capability version `1.0.0` | Candidate for provider catalog metadata; local loopback is intentionally safe for development |
| Dashboard network form | RPC `26657`, P2P `26656`, ABCI `26658`; loopback by default | Reviewed CometBFT request defaults; do not loosen host choices without firewall/acknowledgement checks |

The frontend's `Q_ATOMS_PER_Q = 1_000_000` is a display conversion and must
match the backend economic unit; it is not an operator setting.

## Configuration precedence and state boundaries

1. An explicit request/CLI argument wins.
2. For CometBFT, an applied dashboard configuration is authoritative even when
   it intentionally stores an empty value; the bootstrap environment must not
   resurrect retired local services.
3. Otherwise the process reads `AIDN_*` from its environment.
4. Finally, the code default is used.

> **Listener note.** The bootstrap-generated wrapper expands the dashboard host
> and port from its captured values. The generic systemd template still
> contains a literal `127.0.0.1:8766` in `ExecStart`; changing
> `AIDN_HYPERVISOR_API_HOST` in `/etc/aidn/hypervisor.env` does not change that
> command until the unit is migrated to variable expansion. This is tracked
> below as a migration candidate rather than silently pretending the env key
> works everywhere.

Provider attachment, model materialization, Bundle revisions, endpoint
publication, local-agent permission, and per-request generation parameters are
**stateful domain data**, not global process configuration. They must remain in
the node state/Bundle revision and are intentionally absent from the env file.
In particular, `context_length`, temperature, top-p, max tokens, and their
operator/customer mutability policy belong to a published Bundle revision.

## Hardcoded values that are intentional protocol or safety invariants

These should not be moved to an operator config file merely because they are
constants in Python:

- MCP JSON-RPC method/error semantics and supported protocol versions
  (`src/aidn_hypervisor/mcp/server.py`).
- Pydantic input bounds (for example inference parameter ranges, maximum field
  lengths, and list limits in `inference_gateway.py` and `operator_access_api.py`).
- Canonical JSON/hash domains and `sha256:` identity rules.
- `Q_ATOMS_PER_Q = 1_000_000` and ledger fee/economic units
  (`wallet_read_models.py`, `services/aidn-faucet/.../models.py`).
- State-machine names, terminal states, operation types, and permission scope
  identifiers. Changing them would require a protocol migration, not a local
  tuning change.
- TLS minimums, socket framing limits, and transport safety checks.

## Hardcoded values that are migration candidates

The following values affect deployment behavior but are not yet wired to the
canonical env file. They are listed so future changes do not get hidden in a
script or unit file:

| Candidate | Current location | Current value | Proposed future key |
| --- | --- | --- | --- |
| llama.cpp model command | `deploy/aidn-llamacpp-qwen3-8.service` | host `127.0.0.1`, port `8080`, 99 GPU layers, context `131072`, KV cache `q8_0`, one slot | `AIDN_LLAMACPP_HOST`, `AIDN_LLAMACPP_PORT`, `AIDN_LLAMACPP_MODEL`, `AIDN_LLAMACPP_GPU_LAYERS`, `AIDN_LLAMACPP_CONTEXT_LENGTH`, `AIDN_LLAMACPP_CACHE_TYPE_K/V`, `AIDN_LLAMACPP_PARALLEL` |
| CometBFT install wizard | `operator_cometbft_install.py`, `operator_access_api.py` | `v0.38.19`, chain `aidn-localnet-1`, RPC/P2P/ABCI `26657/26656/26658` | `AIDN_COMETBFT_DEFAULT_*` (still validated by the reviewed installer) |
| MCP body/session safety | `mcp/remote.py`, `mcp/server.py` | body 1 MiB; session minimum 60 s; default TTL 3,600 s | Add explicit envs only if an operator needs to tune them; preserve lower bounds |
| MCP default scopes/approval policy | `mcp/server.py` | read-only catalog; bundle activation auto, retire/provider attach require confirmation | A reviewed policy file, not arbitrary user input |
| Faucet policy | `services/aidn-faucet/src/aidn_faucet/cli.py` | fixed-daily, 50 Q daily, 5 Q rate, 60 s interval, port `8790` | `AIDN_FAUCET_POLICY`, `AIDN_FAUCET_DAILY_Q`, `AIDN_FAUCET_RATE_Q`, `AIDN_FAUCET_INTERVAL_SECONDS`, `AIDN_FAUCET_PORT` |
| Transport/relay defaults | `dispatcher/transport/*.py`, `dispatcher/relay.py` | socket send/receive 5 s; relay hop limit 2, 50 msg/s, expiry 300 s | Add only with per-transport tests and abuse review |
| Provider catalog pins | `provider_catalog.py`, provider install catalog/specs | reviewed runtime versions and installer scripts | A signed catalog manifest; never arbitrary shell from an env file |

## Deployment-only tool variables

`tools/` contains acceptance, rollout, and recovery scripts with their own
command-line defaults (`AIDN_SSH_*`, `AIDN_G5_*`, `AIDN_TRUST_*`,
`AIDN_PERSISTENT_PEERS`, `AIDN_RPC_SERVERS`, and similar). They are deliberately
not loaded by the Hypervisor service. Pass them per invocation or use a separate
operator shell profile; putting them in `/etc/aidn/hypervisor.env` would make
test credentials and recovery targets part of the production process environment.

## Safe migration workflow

1. Copy the example, fill non-secret values, and inject secrets separately.
2. Run `python -m aidn_hypervisor.main`/the service health check and inspect the
   effective dashboard/network evidence before enabling LAN or consensus.
3. Change one class of values at a time; restart the service after env changes.
4. For Bundle/runtime changes, create a new revision and publish/validate it;
   do not edit the global env file to change a model's context or generation
   policy.
5. When a migration candidate is promoted to an env key, add a test for its
   default, validation bounds, and precedence before changing the unit/script.
