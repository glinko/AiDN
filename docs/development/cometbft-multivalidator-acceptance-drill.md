# Four-Validator CometBFT Acceptance Drill

This runbook validates the MVP consensus boundary through CometBFT's public
RPC endpoint. It is not a public network deployment guide: the RPC endpoint
is intentionally bound to `127.0.0.1`, the validator keys are disposable, and
the testnet must never receive production funds or identities.

## Preconditions

- Linux host with Docker and a recent Docker Compose-independent CLI.
- `uv` installed and available on `PATH`.
- Repository checkout on the revision being verified.
- Ports `127.0.0.1:26657` through `127.0.0.1:26660` unused on the host. They
  expose the four validator RPC views on loopback only.
- Enough local disk for the CometBFT v0.38.19 and Python images.

The validator ABCI store retains eight State Sync snapshots by default. This
is a bounded transfer window rather than an unbounded history. Operators may
override it with `AIDN_COMETBFT_ABCI_RETAINED_SNAPSHOTS`; the value must be
large enough for the slowest expected snapshot transfer to finish while new
blocks continue to commit. After a consumer requests the first chunk, the
source also leases that snapshot for 30 minutes of inactivity by default.
Override the lease with `AIDN_COMETBFT_ABCI_SNAPSHOT_LEASE_SECONDS`; the
source must retain the snapshot for the active lease and must never silently
mix chunks from another snapshot.

Both the ABCI and CometBFT containers are started with Docker restart policy
`unless-stopped`. This is required for the drill: a transient ABCI disconnect
must restart the application and CometBFT rather than leaving the validator
permanently offline. A manual deployment must apply the same policy to both
containers before claiming restart/recovery evidence.

## Run

Start an isolated, exactly four-validator network:

```bash
chmod +x tools/run-cometbft-multivalidator-devnet.sh
tools/run-cometbft-multivalidator-devnet.sh "$HOME/aidn-cometbft-state"
```

Then exercise the external acceptance path:

```bash
uv sync --all-extras --frozen
mkdir -p "$HOME/aidn-cometbft-evidence"
uv run python tools/verify-cometbft-multivalidator-devnet.py \
  --validator-rpc-url http://127.0.0.1:26658 \
  --validator-rpc-url http://127.0.0.1:26659 \
  --validator-rpc-url http://127.0.0.1:26660 \
  --output "$HOME/aidn-cometbft-evidence/consensus-drill.json"
```

The verifier performs these checks in order:

1. Reads finalized height and application hash from all four validator RPC
   endpoints and waits until their views converge.
2. Submits a valid-envelope `REGISTRY_UPSERT` probe and verifies that the
   validator rejects it with the strict operation-coverage error before it can
   enter the mempool or canonical operation log.
3. Creates a disposable Consumer-funded Session and submits the canonical
   `SESSION_ESCROW_LOCK`, `SESSION_FAILURE_EVIDENCE` and
   `SESSION_FORCE_SETTLE` operations in separate blocks through
   `broadcast_tx_sync`.
4. Creates a second disposable Session and submits
   `SESSION_ESCROW_LOCK`, `SESSION_OPEN` and `SESSION_ACCEPT` in separate
   blocks. The lifecycle operations bind the finalized escrow lock and
   Endpoint beneficiary without moving funds a second time.
5. Creates a protocol evidence chain with `SERVICE_VERIFICATION_COMMIT`
   followed by `REPUTATION_PROFILE_UPDATE`. The profile update references the
   already finalized verification operation and records only a fixed-point
   profile-root commitment; it does not calculate a score or move Q.
6. Fetches `/tx?prove=true` for every accepted operation, validates each
   transaction hash and verifies the CometBFT transaction Merkle proof against
   the committed header `data_hash`.
7. Restarts `aidn-comet-3`, waits for all four RPC views to converge again, and
   verifies that the committed AiDN application hash has not regressed.

A successful result is one JSON object with `status: "ok"`, a successful
strict-operation negative probe, records for all eight canonical operations,
including the verification/profile chain, and per-validator status snapshots
under `validator_status_before`, `validator_status_after_transactions` and
`validator_status_after_restart`. The optional `--output` path writes the same
immutable report to disk for release-candidate evidence.

The disposable network funds `wallet:acceptance-consumer` through the explicit
`AIDN_CONSENSUS_GENESIS_ACCOUNTS_JSON` test-only setting. That setting is not a
minting operation and must not be used as a production deployment default.
The complete drill consumes disposable state, including a deliberately
unfinalized lifecycle escrow. Re-run `run-cometbft-multivalidator-devnet.sh`
with a new state root before repeating the verifier; reusing a previously
successful state can correctly fail with insufficient `q_atoms` rather than
silently replenishing the test wallet.

## Session failure-chain semantics

The three-operation sequence is intentionally staged. A transaction accepted
by `broadcast_tx_sync` is not finality. The next operation is submitted only
after the verifier has a matching transaction proof, committed block and
application commitment. The same rule is used by the Hypervisor consensus
orchestrator: a repeated force-finalization request resumes the first missing
stage and does not apply local settlement early.

The controlled drill exercises the validator-side canonical path. The
non-validator MVP API path additionally keeps the local session ledger as a
projection: it prepares the local force operation, submits the canonical lock,
failure evidence and force operations in order, and applies the local terminal
transition only after verified finality of the force operation. Until then the
API reports `202`/`CONSENSUS_PENDING`; the local locked exposure remains
unchanged. This is safe for the current remote-canonical profile, but it does
not claim that a Hypervisor which also owns the canonical validator ledger can
open a Session by applying an independent local lock first.

## Validator state recovery

A validator must not be repaired by deleting CometBFT data or editing the
Hypervisor JSON by hand. First stop CometBFT and the ABCI process, preserve an
archive of the state directory, and run the recovery tool in plan-only mode:

```bash
uv run python tools/repair-validator-state-from-abci.py \
  --hypervisor-state /state/hypervisor.json \
  --abci-state /state/abci \
  --discard-operation-id OPERATION_ID
```

The tool accepts a plan only when the local operation history is the ABCI
history plus exactly the explicitly listed local operations, and when the
projected Hypervisor state reproduces the snapshot AppHash. Apply only the
printed plan, with an explicit backup path:

```bash
uv run python tools/repair-validator-state-from-abci.py \
  --hypervisor-state /state/hypervisor.json \
  --abci-state /state/abci \
  --discard-operation-id OPERATION_ID \
  --backup-path /state/backups/hypervisor.pre-recovery.json \
  --confirm-offline \
  --apply
```

`--apply` is intentionally blocked unless `--confirm-offline` is present.
The flag is an operator declaration that both CometBFT and the ABCI process
are stopped; it is not a substitute for checking the process list and the
service/container status. Applying a projection while the validator is live
can create a second state writer and invalidate recovery evidence.

This changes only the Hypervisor's consensus projection fields. Local operator
configuration remains intact, while the next validator startup still fails
closed if the repaired state does not match the durable ABCI snapshot.

## CI Use

The manual GitHub Actions workflow **Release verification** builds the package
and runs its hermetic regression suite. Set `run_consensus_drill=true` to run
this Docker-backed drill on an Ubuntu runner. It is intentionally manual: it
pulls container images and creates four disposable validators. The consensus
job installs the verifier dependencies in its own workspace, runs the strict
operation-coverage probe and uploads `consensus-drill.json` plus the verifier
stdout as `consensus-drill-evidence-<commit>`. A failed run also preserves the
logs of all four CometBFT and ABCI containers before cleanup.

## Scope And Limits

This proves external transaction admission, inclusion proof verification,
four-validator height/AppHash convergence and one-validator restart continuity
in a controlled testnet. It does not replace
the trusted-checkpoint light-client verification required for a production
finality claim, or production key and secret management. A State Sync recovery
drill must verify that the source retains the advertised snapshot for the full
chunk transfer; a source that advertises a snapshot and prunes it mid-transfer
is not an acceptable recovery peer.

## Cleanup

```bash
for i in 0 1 2 3; do
  docker rm -f "aidn-comet-$i" "aidn-abci-$i" || true
done
docker network rm aidn-cometbft-devnet || true
rm -rf "$HOME/aidn-cometbft-state"
```
