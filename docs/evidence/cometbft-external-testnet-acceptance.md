# External CometBFT Testnet Acceptance

`tools/verify-cometbft-external-testnet.py` is a read-only verifier for a
previously finalized AiDN ledger operation. Unlike the disposable devnet drill,
it does not submit a transaction and cannot restart a validator.

The operator supplies at least two independently hosted HTTPS RPC endpoints, a
trusted checkpoint obtained out of band, and the exact operation and transaction
identifiers. Example configuration:

```json
{
  "rpc_endpoints": ["https://rpc-a.example.net", "https://rpc-b.example.net"],
  "chain_id": "aidn-testnet-1",
  "verifier_id": "release-acceptance-2026-07",
  "operation_id": "<AiDN-ledger-operation-id>",
  "transaction_hash": "<64-uppercase-or-lowercase-hex-characters>",
  "trust_period_seconds": 1209600,
  "trusted_checkpoint": {
    "height": 12345,
    "block_id": "<64-hex>",
    "app_hash": "<64-hex-or-empty-for-initial-root>",
    "header_time": "2026-07-29T00:00:00Z",
    "validator_set_hash": "<64-hex>",
    "next_validator_set_hash": "<64-hex>",
    "validators": [
      {"address": "<40-hex>", "public_key": "ed25519:<base64>", "voting_power": 100}
    ]
  }
}
```

Run it from the release checkout:

```bash
PYTHONPATH=src python tools/verify-cometbft-external-testnet.py \
  --config /etc/aidn/external-cometbft-acceptance.json
```

For every endpoint, the verifier checks the exact transaction binding, its
Merkle inclusion proof, CometBFT commit signatures and validator transition
relative to the operator-provided trusted checkpoint. It then rejects endpoints
which disagree on any canonical finality field: operation, chain, height, block
ID, application hash, commit hash, finalization timestamp or proof version.

The production Hypervisor wiring also exposes a multi-RPC finality source. Its
`minimum_agreement` value requires a bounded quorum of independently verified
RPC observations before evidence is passed to the local ABCI commitment
boundary. An ambiguous tie or insufficient matching evidence fails closed.
For a non-validator Hypervisor, the same builder may omit the local ABCI
application and expose the verified operation-bound RPC quorum directly. A
validator keeps the stricter local-ABCI binding, which additionally requires
the local committed block and AppHash to match the remote evidence.
The source labels and endpoint URLs are configuration inputs; they do not prove
that the endpoint operators are organizationally independent.

The output deliberately reports `NOT_PROVEN_BY_PROTOCOL` for ownership. Two
RPC URLs are not evidence of independent operators on their own; preserve the
testnet validator roster, control-group declarations and each operator's
attestation with the release evidence.

## Hypervisor activation

The running Hypervisor can load the same multi-RPC finality boundary from an
operator-owned JSON file by setting:

```bash
export AIDN_CONSENSUS_MODE=non_validator
export AIDN_COMETBFT_FINALITY_CONFIG=/etc/aidn/cometbft-finality.json
```

The deployment file contains the `rpc_endpoints`, `minimum_agreement`,
`chain_id`, `verifier_id`, `trust_period_seconds`, and the complete
`trusted_checkpoint` object. It must contain at least two unique credential-free
HTTP(S) RPC endpoints. The loader rejects unknown fields, endpoint paths,
credentials, invalid quorum bounds and an incorrectly shaped profile before
the application starts. Checkpoint freshness is enforced later by the
light-client trust-period rule. The full schema is represented by
`CometBftFinalityDeploymentConfig` in the source package.

When `AIDN_CONSENSUS_MODE=validator`, the source is additionally bound to the
Hypervisor's own durable ABCI Ledger. If the local ABCI application is absent
or belongs to another Ledger, startup fails closed. Without the deployment
variable, no external finality source is created and the existing local/MVP
behavior remains unchanged.
