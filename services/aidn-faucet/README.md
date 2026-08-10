# AiDN Faucet Treasury

`aidn-faucet` is an external policy service. It is not a Hypervisor plugin and
it does not add a faucet-specific Ledger operation.

The service:

1. authenticates a wallet claimant with a short-lived signed challenge;
2. evaluates a replaceable policy (`fixed-daily` or `accumulating-pool`);
3. builds and signs an ordinary `WALLET_TRANSFER` from the dedicated Treasury
   Wallet;
4. submits the exact envelope through a deployment-provided consensus adapter;
5. changes quota/pool state only after `FINALIZED` is reported.

Before step 3, the service verifies the Treasury activation proof from
ECO-0009. A local manifest or a locally configured starting balance is never
enough. Consensus-funded manifests require finalized `TREASURY_FUND` evidence;
Genesis-funded manifests require matching canonical ABCI manifest responses
from the configured RPC quorum. If the proof is unavailable, the service
remains inspectable but rejects new claims.

`ADMITTED` is not payment finality. A submitter must return `FINALIZED` only
after the configured consensus-finality boundary has been verified. Pending
claims retain the exact signed envelope and can be reconciled idempotently.

The Treasury private key is never part of the public manifest, repository,
HTTP response or Hypervisor state. Keep it in a dedicated secret store or a
local file readable only by the Faucet service account.

## Package layout

- `src/aidn_faucet/policy.py` contains replaceable policy implementations.
- `src/aidn_faucet/service.py` contains wallet proof, signing and idempotent
  claim orchestration.
- `src/aidn_faucet/cometbft_submitter.py` contains the failover submission,
  canonical sequence and verified-finality adapter.
- `src/aidn_faucet/store.py` contains SQLite durability.
- `src/aidn_faucet/api.py` contains the small agent-facing HTTP API.

The consensus submitter is still an injected boundary, but the package now
ships a production adapter for the existing AiDN CometBFT proof interfaces.
The CLI uses this adapter by default. Build the finality source from an
operator-approved trusted checkpoint
using `build_cometbft_finality_source` or
`build_cometbft_multi_rpc_finality_source`, passing a shared
`FaucetTransactionHashRegistry.lookup` callback. Then pass that source,
registry and `build_http_cometbft_faucet_submitter(...)` to `FaucetService`.
The wiring is intentionally explicit:

```python
registry = FaucetTransactionHashRegistry()
finality = build_cometbft_multi_rpc_finality_source(
    config=finality_config,
    transaction_hash_for_operation=registry.lookup,
)
submitter = build_http_cometbft_faucet_submitter(
    rpc_endpoints=rpc_endpoints,
    treasury_wallet_id=manifest.wallet_id,
    chain_id=manifest.chain_id,
    finality_source=finality,
    transaction_hash_registry=registry,
)
```

The default service command wires the same objects from an immutable Treasury
manifest and a `CometBftFinalityDeploymentConfig` file:

```bash
aidn-faucet serve \
  --manifest /etc/aidn/faucet-treasury.json \
  --private-key /var/lib/aidn-faucet/treasury.key \
  --state /var/lib/aidn-faucet/faucet.sqlite \
  --finality-config /etc/aidn/cometbft-finality.json \
  --agent-token "$AIDN_FAUCET_AGENT_TOKEN" \
  --creator-token "$AIDN_FAUCET_CREATOR_TOKEN" \
  --host 127.0.0.1
```

The built-in factory rejects a chain mismatch between the manifest and the
finality file before starting the HTTP server. Status responses include the
activation state, diagnostic reason and public proof hash; they never include
private keys or bearer tokens.

To make the GUI and MCP endpoint reachable from a trusted private LAN, use
`--lan` (or bind to one specific LAN address with `--host`). Both bearer
tokens are mandatory for every non-loopback bind:

```bash
export AIDN_FAUCET_AGENT_TOKEN='replace-with-a-long-random-agent-token'
export AIDN_FAUCET_CREATOR_TOKEN='replace-with-a-separate-creator-token'

aidn-faucet serve \
  --manifest /etc/aidn/faucet-treasury.json \
  --private-key /var/lib/aidn-faucet/treasury.key \
  --state /var/lib/aidn-faucet/faucet.sqlite \
  --finality-config /etc/aidn/cometbft-finality.json \
  --lan
```

The same process then serves:

- `http://<node-lan-ip>:8790/` for the creator GUI;
- `http://<node-lan-ip>:8790/mcp` for agent MCP clients.

The `--lan` mode is intended for a controlled private network and emits a
startup warning because it is plain HTTP. Restrict TCP/8790 to the trusted LAN
with the host firewall; use HTTPS with an authenticated reverse proxy before
crossing an untrusted network. Never put either token in a URL or commit it to
the repository.

## MCP and operator UI

The same process exposes two separate operator surfaces:

- `GET /` serves the minimal creator control room. Entering a creator token
  keeps it only in browser memory; the page never stores it in localStorage and
  never displays the Treasury private key or signed envelope.
- `POST /mcp` serves the MCP JSON-RPC endpoint. MCP sessions are bearer-token
  bound and auto-renew their in-memory TTL while the connection is active.

The agent token exposes only:

- `aidn.faucet.status`;
- `aidn.faucet.issue_challenge`;
- `aidn.faucet.claim`;
- `aidn.faucet.reconcile`.

The creator token exposes administrative status, pause, resume, low-balance
watermark, sanitized claim inspection and exact-claim reconciliation. It does
not expose a Treasury private key. Agent and creator tools are scope-separated
at `tools/list`; an agent cannot invoke an admin tool by guessing its name.

An HTTP MCP client should send the same bearer token on initialization and
subsequent requests, and reuse the returned `Mcp-Session-Id` header:

```json
{
  "mcpServers": {
    "aidn-faucet": {
      "url": "http://127.0.0.1:8790/mcp",
      "headers": {
        "Authorization": "Bearer ${AIDN_FAUCET_AGENT_TOKEN}"
      }
    }
  }
}
```

Bind the service to loopback or a protected private network. Production remote
access must use HTTPS and an authenticated reverse proxy; do not expose the
creator control token over public HTTP.

The adapter may fail over submission to another RPC, but it always sends the
same signed bytes and operation ID. A CheckTx response remains `ADMITTED`;
only verified operation-bound commit evidence becomes `FINALIZED`.

Creator controls use a separate `AIDN_FAUCET_CREATOR_TOKEN` and are exposed at:

- `GET /v1/admin/status`
- `POST /v1/admin/pause`
- `POST /v1/admin/resume`
- `POST /v1/admin/low-balance-watermark`

Signer rotation is deliberately not an online mutable setting: the Treasury
public key is part of the immutable manifest. Rotating it requires a new
Treasury manifest and an authorized funding/migration operation.
