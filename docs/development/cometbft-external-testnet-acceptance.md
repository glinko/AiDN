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
which disagree on the finalized height, block ID or application hash.

The output deliberately reports `NOT_PROVEN_BY_PROTOCOL` for ownership. Two
RPC URLs are not evidence of independent operators on their own; preserve the
testnet validator roster, control-group declarations and each operator's
attestation with the release evidence.
