# Wallet Bootstrap Recovery Acceptance - 2026-08-08

Status: accepted for the controlled LAN testnet

Scope: validator nodes `192.168.88.127` through `192.168.88.130`

## Incident

The operator UI attempted to create a second wallet after an earlier
`OPERATOR_WALLET_BIND` transaction had already established a different canonical
binding. The retry was rejected with `operator already has a different wallet
binding`.

The incident had three independent causes:

1. CometBFT was not supervised consistently. An ABCI or host restart could leave
   the consensus RPC unavailable even though the ABCI listener remained active.
2. A failed UI retry generated a new wallet and operation instead of preserving
   the original wallet intent and operation identity.
3. Validator bootstrap accepted only an external finality adapter as confirmation.
   It did not reconcile an exact pending wallet binding from committed local ABCI
   state after consensus had committed the transaction.

The reported ABCI absence was not the primary failure on node `.127`: the ABCI
application was listening on `127.0.0.1:27658`. The consensus process using RPC
port `27657` had stopped and was not restarted automatically.

## Corrective Changes

- `9273d13` makes wallet retries identity-preserving, exposes canonical recovery
  state, rejects creation of a competing wallet, and adds supervised CometBFT
  deployment behavior.
- `e286eff` adds the LAN testnet image recipe used for a common deployment
  artifact.
- `9c68554` recognizes an exact wallet binding in committed local ABCI state as
  sufficient validator-bootstrap finality while retaining the height-zero guard
  against uncommitted local state.

The UI now offers recovery only for the canonical wallet public key. A retry
resubmits the same pending binding and never silently creates a new wallet.

## State Reconciliation

The old canonical wallet private key was not available in any active or backup
operator state. Because this is a disposable controlled testnet, the four
validators were reset together from one agreed genesis and one exact application
image. The previous state was retained instead of edited or deleted.

Rollback snapshots:

- `.127`: `/home/user/aidn-g5-reprovision-20260804T100200Z/backup-20260808T154900Z`
- `.128`-`.130`: `/home/user/aidn-g5-clean/backup-20260808T154900Z`

The replacement wallet bind uses operation ID
`9ed07fad5f08aedf810b1ec0c8621e6b15668115aebbc77ca24d07dc6ee7973e`
and canonical wallet ID `wallet-5320047bb01d`. No private key material is stored
in this acceptance record.

## Live Evidence

All four validators run application image ID
`sha256:43aeadffef48a3117361b1e13d5ea3c8cbc12b973c19da16066649e9cfc75b48`.

The final LAN verifier reported:

- status: `ok`
- chain ID: `chain-Anm7Jk`
- exact shared height: `450`
- shared AppHash:
  `4F28843C51A83C12E1A16003DA1CF9472B25F72B876003881C669CA78ABB1504`
- unique validator IDs: `4`
- ownership evidence: `NOT_PROVEN_BY_PROTOCOL`, as expected for the controlled
  LAN topology

Node `.127` runs CometBFT under user systemd with automatic restart. Nodes
`.128` through `.130` run both CometBFT and ABCI containers with the
`unless-stopped` restart policy.

After an intentional ABCI container restart on `.127`:

- the CometBFT service returned to `active`;
- block height continued increasing;
- the operator dashboard still reported the canonical wallet as configured;
- no replacement wallet operation was created.

## Automated Coverage

Focused wallet, consensus, bootstrap, and dashboard tests passed:

- `140 passed, 151 deselected`
- local ABCI finality regression selection: `5 passed, 6 deselected`
- Ruff checks passed for all modified Python files
- shell syntax checks passed for the modified deployment scripts

## Invariants

- A retry does not generate a different wallet or operation identity.
- A canonical wallet conflict cannot be repaired by overwriting chain state.
- Recovery requires the private key matching the canonical public key.
- Local ABCI state at height zero is not accepted as consensus finality.
- A committed exact local ABCI binding can complete validator bootstrap.
- Consensus and ABCI processes are supervised and checked after rollout.
- Full network reset is allowed only for an explicitly disposable coordinated
  testnet; production recovery must preserve canonical history.
