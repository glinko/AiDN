# Controlled LAN Consensus Acceptance Evidence

Date: 2026-08-02

Status: `PASSED`

Scope: `CONTROLLED_LAN_TESTNET`

This record captures a live four-host acceptance run against the Ubuntu
validators at `192.168.88.127` through `192.168.88.130`. It proves the current
strict CometBFT/ABCI consensus boundary and restart continuity in the
controlled lab. It does not prove independent operator ownership, public
network finality or production key management.

## Deployment

- Each host ran one `aidn-abci-lan` container from the strict image
  `aidn-hypervisor-lan-testnet-strict:20260802`.
- Each host ran one `aidn-comet-lan` container from
  `cometbft/cometbft:v0.38.19`.
- Both containers used Docker restart policy `unless-stopped`.
- The disposable Consumer genesis balance was supplied only through
  `AIDN_CONSENSUS_GENESIS_ACCOUNTS_JSON`.
- The previous application and CometBFT state was preserved under host-local
  `/home/user/aidn-lan-testnet/backups/fresh-*` before the clean run.

## Readiness Result

`verify-cometbft-lan-testnet.py` returned `status: ok` for all four RPC views.
The fresh network converged at height `1` with AppHash
`9833FDEF68263F01509F26A2D717F08FBAE724CEBC452F1B0712D31983C72DFC` and
reported four unique validator node IDs with three P2P peers per node.

## Strict Economic Drill

`verify-cometbft-multivalidator-devnet.py --skip-restart` returned `EXIT=0`.
The drill proved:

- unsupported `REGISTRY_UPSERT` was rejected before canonical execution with
  `consensus operation transition is not implemented`;
- the `SESSION_ESCROW_LOCK` -> `SESSION_FAILURE_EVIDENCE` ->
  `SESSION_FORCE_SETTLE` chain was finalized;
- the `SESSION_ESCROW_LOCK` -> `SESSION_OPEN` -> `SESSION_ACCEPT` chain was
  finalized without a second escrow debit;
- `SERVICE_VERIFICATION_COMMIT` -> `REPUTATION_PROFILE_UPDATE` was finalized;
- all eight accepted transactions had valid CometBFT inclusion proofs;
- all four validators converged at height `25` with AppHash
  `B09AAD2C7F59008E7CA0B98603A67616545719FBD05346FADB9DE307DB25AD53`.

## Restart Result

After the transaction batch, `aidn-comet-lan` was remotely restarted on
`192.168.88.130`. The container returned with `unless-stopped`, and the
readiness verifier returned `status: ok` at height `53` with the same AppHash
`B09AAD2C7F59008E7CA0B98603A67616545719FBD05346FADB9DE307DB25AD53` on every
RPC view. The four validator node IDs remained unchanged.

## Reproduction

Use the commands in [Controlled LAN Testnet](../operations/controlled-lan-testnet.md) for
the readiness gate and the commands in [Four-Validator CometBFT Acceptance
Drill](cometbft-multivalidator-acceptance-drill.md) for the complete
transaction proof drill. Each complete run must use a fresh disposable state;
the verifier deliberately does not mint or replenish balances and an existing
state can correctly fail later with insufficient `q_atoms`.

The machine-readable drill report used for this record was written outside the
repository at:

`%TEMP%\\aidn-cometbft-lan-drill-strict-20260802-fresh.json`

## Limitations

The report keeps `ownership_evidence: NOT_PROVEN_BY_PROTOCOL`. A controlled LAN
with four hosts is technical evidence under one operator context, not proof of
four independent organizations or a public trust anchor.
