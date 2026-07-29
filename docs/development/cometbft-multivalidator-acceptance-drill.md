# Four-Validator CometBFT Acceptance Drill

This runbook validates the MVP consensus boundary through CometBFT's public
RPC endpoint. It is not a public network deployment guide: the RPC endpoint
is intentionally bound to `127.0.0.1`, the validator keys are disposable, and
the testnet must never receive production funds or identities.

## Preconditions

- Linux host with Docker and a recent Docker Compose-independent CLI.
- Repository checkout on the revision being verified.
- Port `127.0.0.1:26657` unused on the host.
- Enough local disk for the CometBFT v0.38.19 and Python images.

## Run

Start an isolated, exactly four-validator network:

```bash
chmod +x tools/run-cometbft-multivalidator-devnet.sh
tools/run-cometbft-multivalidator-devnet.sh "$HOME/aidn-cometbft-state"
```

Then exercise the external acceptance path:

```bash
python tools/verify-cometbft-multivalidator-devnet.py
```

The verifier performs these checks in order:

1. Reads a finalized height and application hash from node 0.
2. Submits a unique protocol-origin `REGISTRY_UPSERT` transaction through
   `broadcast_tx_sync`.
3. Fetches `/tx?prove=true`, validates the transaction hash and verifies the
   CometBFT transaction Merkle proof against the committed header `data_hash`.
4. Restarts `aidn-comet-3`, waits for node 0 to advance, and verifies that the
   committed AiDN application hash has not regressed.

A successful result is one JSON object with `status: "ok"`, the transaction
hash, the transaction height, the post-restart height, and the application
hash. Preserve it with the release candidate evidence.

## CI Use

The manual GitHub Actions workflow **Release verification** builds the package
and runs its hermetic regression suite. Set `run_consensus_drill=true` to run
this Docker-backed drill on an Ubuntu runner. It is intentionally manual: it
pulls container images and creates four disposable validators.

## Scope And Limits

This proves external transaction admission, inclusion proof verification and
one-validator restart continuity in a controlled testnet. It does not replace
the trusted-checkpoint light-client verification required for a production
finality claim, a remotely anchored State Sync recovery drill, or production
key and secret management.

## Cleanup

```bash
for i in 0 1 2 3; do
  docker rm -f "aidn-comet-$i" "aidn-abci-$i" || true
done
docker network rm aidn-cometbft-devnet || true
rm -rf "$HOME/aidn-cometbft-state"
```
