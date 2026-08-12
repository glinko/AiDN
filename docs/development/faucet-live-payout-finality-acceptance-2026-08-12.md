# Faucet Live Payout and Finality Acceptance

Status: PASS

Date: 2026-08-12

This report records a secret-free operational acceptance of the external
Faucet against the controlled AiDN local multi-validator network. It is
evidence of the deployed payout path, not a public-network or independent
operator claim.

## Deployment

- Faucet host: `192.168.88.123`
- Deployed checkout: `c350d54`
- Treasury activation: `ACTIVE`
- Treasury: `aidn-localnet-faucet-reset-v1`
- Chain ID: `chain-Anm7Jk`
- Policy: `fixed-daily`, `50 Q` per wallet allocation
- Finality configuration hash: `sha256:df057c2cbbd66ccdd0161b84cd3dacc3b6c2c55266a805dd9fc98ab243f55f71`

No private key, bearer token, recipient wallet, or signed secret material is
included in this report.

## Payout

- Claim status: `APPROVED`
- Amount: `50,000,000 q_atoms` (`50 Q`)
- Operation type: `WALLET_TRANSFER`
- Operation ID: `15e56b4a23823270c75ae8d366b9e363e0012d22c2fe572183c8ff96da5e0cec`
- Transaction hash: `8672CE6816383916923D52EE7537DB9FDB3E93B5991AF11AE4ECB31A597637FC`
- Finalized at height: `49991`
- Finalized at: `2026-08-12T22:57:42.698132839Z`
- Quota follow-up: `QUOTA_EXHAUSTED`, proving the same wallet was not paid twice

## External finality proof

The exact operation and transaction were independently checked through the
configured CometBFT RPC quorum:

- RPC endpoints: `192.168.88.128:26657`, `192.168.88.129:26657`, `192.168.88.130:26657`
- Minimum agreement: `2`
- Observed agreement: `3/3`
- Block ID: `1469C6092575E1FAF6033149AD281940C0935424D6C4B2B2072CD9175142B699`
- App hash: `D493A081127FCBC2D7710FFE6986E3144C6020E577932018FE6740B79A050288`
- Commit hash: `ec86e8706bfd195254fe9bcb750875588e741dad5d1404d5c19d3ca301930d05`
- Verifier: `faucet-123:0`
- Proof version: `consensus-finality-evidence.v1`

The idempotent reconciliation pass returned the same claim status, operation
ID, and transaction hash after the service/runtime refresh.

## Checkpoint recovery

The previous trusted checkpoint had expired after the localnet reset. A new
checkpoint at height `49691` was selected from matching validator RPC results,
validated against the deployment schema, and installed without changing the
Treasury manifest, funding state, or Faucet database. The new checkpoint is a
verification anchor; it is not a new funding or minting event.

The checked-in checkpoint rotation tool is the required procedure for future
localnet resets and operational rotations.

## Scope and limitations

- This acceptance proves activation, payout, exact-envelope binding,
  reconciliation, and multi-RPC finality on the controlled localnet.
- It does not prove public RPC/P2P reachability, independent operator
  control, or production mainnet readiness.
- Rejected and superseded claims remain retained for diagnostics and are not
  treated as successful payments.

## Reproduction

Run on the Faucet host with credentials supplied through its protected service
environment; do not place tokens or private keys in shell history or reports:

```bash
set -a; . /etc/aidn/faucet.env; set +a
services/aidn-faucet/.venv/bin/python tools/run_faucet_live_acceptance.py \
  --faucet-url http://127.0.0.1:8790 \
  --finality-config /etc/aidn/cometbft-finality.json \
  --require-external-finality \
  --finality-timeout-seconds 180 \
  --output /var/lib/aidn-faucet/evidence/live-claim-finality.json
```
