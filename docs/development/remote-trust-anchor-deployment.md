# Remote Snapshot Trust Anchor Deployment

Checkpoint State Sync is enabled only from a signed, locally verified Trust
Anchor. A remote HTTP response is not itself trust evidence.

Set `AIDN_REMOTE_TRUST_ANCHOR_CONFIG` to an operator-owned JSON file:

```json
{
  "source_url": "https://anchors.example.net/aidn-testnet-1.json",
  "storage_path": "/var/lib/aidn/remote-trust-anchors.json",
  "trusted_signers": {
    "testnet-release-authority": "ed25519:<32-byte-public-key-hex>"
  },
  "expected_network_id": "aidn-testnet",
  "expected_chain_id": "aidn-testnet-1",
  "expected_network_revision": 1,
  "max_checkpoint_age_blocks": 10000,
  "max_checkpoint_age_seconds": 2592000
}
```

The source must be credential-free HTTPS. Redirects, unknown signers, invalid
Ed25519 signatures, conflicting anchors at the same height, stale anchors and
network/chain/revision mismatches all fail closed. Only verified envelopes are
persisted in the mode-0600 local store.

When configured, the Hypervisor refreshes the anchor during lifespan startup.
Failure prevents startup instead of silently treating an unverified checkpoint
as usable. `TrustedAnchorSyncAdvisor.apply_to_sync_mode_config()` is the only
supported path for projecting a persistent remote anchor into checkpoint-sync
eligibility.

This does not make a testnet independent. The operator must separately verify
the signer key out of band and use an endpoint operated outside the local
control group.
