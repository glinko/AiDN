# G5 Replacement and Fault-Recovery Acceptance

Date: 2026-08-04

Status: PASS for the controlled LAN testnet profile.

## Scope

The failed validator at `192.168.88.127` was not reset in place. A separate
replacement root was provisioned from the verified quorum at `192.168.88.128`,
`.129` and `.130`. The old deployment and its state directories were retained
as rollback evidence.

Application source used for state sync: `e2b82be`.

The replacement used the preserved genesis, node identity and validator key,
but a new CometBFT data directory with State Sync enabled. It did not copy a
blockstore, state database, ABCI response store or prior signing state.

## State-Sync Result

The replacement converged on the live `chain-Anm7Jk` quorum at height `13002`
with AppHash
`32294FD52BAB77FFB72D42FDC931335B8CD899142A1674C3D459856119D4C3D3` and
`catching_up=false`. It retained node identity
`958378d45dbeb237cc3a09601904da6836ee43c0` and reached three peers.

The first attempt was intentionally retained as a failed recovery record. It
must not be treated as a successful G5 result.

## Live Drills

The live collector used four RPC views:

- `192.168.88.128:26657`
- `192.168.88.129:26657`
- `192.168.88.130:26657`
- replacement `192.168.88.127:27657`

All four views reconverged after each action with identity and chain ID
preserved:

- graceful replacement restart: `PASS`
- isolated abrupt CometBFT and ABCI termination: `PASS`
- host reboot with explicit ABCI-then-Comet recovery: `PASS`
- stale settlement predecessor rejection: `PASS`

The live report hash is:

`sha256:f1a88f284d46cbe01d92b0037ceed3570b01a66b0450639510a70218130314ea`

The aggregated G5 report hash is:

`sha256:97778eba167bfb47a535737696040eb21a28fdfc679dafd353d646f48d2e9f34`

The stale predecessor was rejected with code `1` and log
`Settlement proposal funding predecessor is not finalized`; no new escrow was
created by the probe.

## Gate State

The release-gate matrix for commit `0b48b91` records G0, G1, G2, G3 and G5 as
`PASS`. G4, G6 and G7 remain `NOT_RUN` until public-network evidence,
independent operator attestations and a complete EVD-0001 bundle are supplied.
