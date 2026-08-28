# G3 Multi-Validator Acceptance

Date: 2026-08-04

Status: PASS for the controlled LAN testnet profile.

## Current Release Candidate

The full G3 drill was run against commit `e6c4417` using four validator RPC
views:

- `192.168.88.128:26657`
- `192.168.88.129:26657`
- `192.168.88.130:26657`
- replacement `192.168.88.127:27657`

The drill finalized eight transaction stages with CometBFT inclusion proofs,
performed an explicit replacement restart, and verified quorum progress and
post-restart convergence. The report used the replacement-root offline drill
from the same acceptance run.

## Results

- before transactions: height `14388`
- after transactions: height `14407`
- after restart: height `14415`
- after-restart AppHash:
  `54B05A6D506F571AB80E6F6C9E41F18B128042AE6925A2358AFC19870FFD0F45`
- chain ID: `chain-Anm7Jk`
- validator count: `4`
- peer count: `3` for each validator
- offline drill: `PASS`
- restart drill: `PASS`
- node identity and chain ID: preserved

The offline source report covered `14369 -> 14372` while the replacement was
unreachable, then reconverged all four validators at `14378` with the same
AppHash and replacement node ID.

Machine-readable evidence was retained outside the repository:

- G3 report: `sha256:0820392133abb48b567d56bf86ffcec5da1fa1422e4d97083344e33fced2b00b`
- offline report: `sha256:f50539033bb2d7494f9e3b66923763ed8b8dc5bcb5267be7f1ebcd30181b7027`
- release matrix: `sha256:9471a97d9440ec25f3519f115ea3bde6ab4db15a33fd0e7ff63492ef4a7102f8`

## Scope Boundary

This is controlled-LAN consensus evidence. It does not prove public Internet
networking, independent organizational ownership, or an EVD-0001 publication
bundle. Those remain G4, G6 and G7 evidence gates.
