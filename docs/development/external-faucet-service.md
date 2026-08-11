# External Faucet Service Runbook

This runbook is for the external `services/aidn-faucet` package described by
ECO-0008. The service is a Treasury policy signer, not a Hypervisor component.

For a complete Ubuntu deployment procedure that may be handed to a local
agent, use [Faucet Agent Deployment Instructions](./faucet-agent-deployment-instructions.md).

## Current implementation boundary

The package currently provides:

- fixed-daily `50 Q` per Wallet policy;
- accumulating `5 Q` per minute pool policy;
- signed Wallet challenge verification;
- SQLite-backed claim and policy state;
- deterministic, idempotent signed `WALLET_TRANSFER` envelopes;
- explicit `ADMITTED` versus `FINALIZED` handling;
- reconciliation of a pending exact envelope after a timeout.

The consensus submitter is injected by deployment. The default CLI wiring is
`aidn_faucet.deployment:build_cometbft_submitter`; it loads the Treasury
manifest and the operator-approved multi-RPC finality file, rejects a chain
mismatch, and constructs the production adapter with the configured quorum.
It must not report
`FINALIZED` until a configured finality verifier has checked the canonical
network result. The package now provides
`aidn_faucet.cometbft_submitter.CometBftFaucetTransferSubmitter` and an HTTP
builder for the existing AiDN CometBFT finality interfaces. The builder uses
RPC failover for the exact same envelope and a configurable sequence quorum;
it still treats a raw `broadcast_tx_sync` response as admission only.

## Secret separation

Keep these objects separate:

- public `faucet-treasury.json` manifest, safe to distribute;
- Treasury online signer key, readable only by the Faucet service account;
- creator recovery Wallet, stored outside the online service;
- agent API token, rotated independently from the Treasury key;
- SQLite state, backed up with restricted permissions.

The private key must never be committed, put in the manifest, returned by
`/v1/status`, or sent to an agent.

## Policy changes

Deploy a new policy instance with a new policy version and an explicit future
activation boundary. Do not mutate an existing SQLite policy state in place.
Keep old claims and their decision hashes for audit. For an accumulating pool,
the pool state is reset only after the exact transfer reaches finality.

## Agent flow

1. Agent calls `POST /v1/challenges` with its Wallet ID and public key.
2. Agent signs the returned challenge with the recipient Wallet key.
3. Agent calls `POST /v1/claims` with an idempotency `request_id` and proof.
4. Agent receives `APPROVED`, `PENDING_FINALITY`, `SUBMISSION_REJECTED` or
   `SUBMISSION_UNKNOWN`. Rejected consensus admission and unavailable
   submission transport are distinct states with different operator actions.
   The response includes the operation ID and transaction hash for evidence
   assembly; neither is a substitute for finality.
5. For a non-final response, agent calls
   `POST /v1/claims/{request_id}/reconcile`; it must not create a new request.

For the two-validator acceptance gate, use the returned `operation_id` and
`transaction_hash` in an `ExternalCometBftAcceptanceConfig`, then run
`tools/verify-cometbft-external-testnet.py`. The verifier requires a trusted
checkpoint, checks inclusion and commit proofs independently on every RPC,
and rejects any disagreement in canonical evidence. A restart/reconciliation
run must reuse the same request, operation ID and transaction hash.

The HTTP service should be bound to loopback or a protected private network.
All protected API and MCP routes require `Authorization: Bearer ...`; the root
route only serves a secret-free GUI shell and requires the creator token for
data or control actions. The CLI keeps the loopback default. For a trusted LAN,
set both tokens and pass `--lan`, or bind to one specific LAN address with
`--host 192.168.x.x`; a non-loopback bind is rejected when either token is
missing. Plain HTTP is acceptable only inside a controlled test LAN. Use HTTPS
and an authenticated reverse proxy outside it.

## MCP and creator UI

The service exposes `POST /mcp` as a separate MCP JSON-RPC surface. It uses the
agent and creator bearer tokens already configured for the service, but never
mixes their tool sets. Agent sessions can inspect status and execute the normal
Wallet challenge/claim/reconcile flow. Creator sessions can inspect controls,
pause/resume claims, set a low-balance watermark, inspect sanitized claim state
and reconcile one persisted claim. Creator tools are omitted from an agent's
`tools/list` response and remain denied if called by name.

The root URL (`/`) serves a small responsive creator control room. It is a
deliberately minimal surface for Treasury operations, not a replacement for
the Hypervisor dashboard. The token is entered into a password field and kept
only in browser memory. The page exposes no private key or signed envelope.

For an agent on the same host, configure the MCP URL as:

```text
http://127.0.0.1:8790/mcp
```

For a LAN deployment, replace the host with the Faucet node address:

```text
http://<faucet-node-lan-ip>:8790/mcp
```

The creator control room is available at the matching root URL:
`http://<faucet-node-lan-ip>:8790/`.

Send `Authorization: Bearer <AIDN_FAUCET_AGENT_TOKEN>` on `initialize` and
subsequent requests, and preserve the returned `Mcp-Session-Id`. The service
renews the session expiry on valid requests; restarting the service invalidates
old sessions and requires a fresh `initialize`.

## Live acceptance drill

Run the acceptance runner on the Faucet host or a protected operator host. It
creates a one-use recipient Wallet in process memory, proves control using the
normal challenge flow, submits one claim, reconciles the same claim and checks
that the fixed-daily policy rejects a second claim for that Wallet. It never
writes the recipient private key, bearer token, Wallet proof or Treasury
envelope to the report.

```bash
cd /opt/aidn/AiDN
set -a
. /etc/aidn/faucet.env
set +a
export AIDN_FAUCET_URL=http://127.0.0.1:8790
uv run python tools/run_faucet_live_acceptance.py \
  --output /var/lib/aidn-faucet/evidence/live-claim.json
```

For the current `fixed-daily` policy the expected amount is `50_000_000`
`q_atoms`. A future accumulating-pool policy must set its expected amount and
use `--skip-quota-check` when repeated claims are intentionally valid. The
report is evidence of a single live execution, not authority to expose the
Faucet publicly or to reuse its ephemeral recipient Wallet.

## Production completion gates

Before using the service against a public or shared network, add and verify:

- a consensus relay/finality adapter with trusted network configuration;
- one-time post-genesis Treasury funding for existing networks;
- creator pause, resume and low-balance controls through a separate creator
  token;
- a documented new-lineage procedure for signer rotation and state recovery;
- at-least-two-validator finality and restart evidence;
- RPC failover without changing the signed operation;
- a backup/restore drill for pending claims and policy state.

The service must fail closed if any of these boundaries is unavailable.

## Creator controls

The creator token is separate from the agent claim token. It authorizes only
operational controls and is never returned by the service. Pause/resume is
durable in SQLite, and a positive low-balance watermark blocks new claims when
the configured balance provider is unavailable or reports less than the
watermark. A Treasury signer cannot be silently rotated because its public key
is hash-bound into the Treasury manifest; key rotation is a new Treasury
lineage and requires a new authorized funding/migration operation.
