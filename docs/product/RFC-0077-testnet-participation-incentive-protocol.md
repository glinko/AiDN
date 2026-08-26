# RFC-0077 Testnet Participation Incentive Protocol

Status: `Draft`

Version: `0.1`

Depends on:

- `RFC-0016 Wallet and Identity`
- `RFC-0048 Epoch Engine`
- `RFC-0058 Participant Eligibility and Sybil Resistance`
- `RFC-0076 Network Profile and Network Configuration`

## 1. Boundary

Testnet participation is a temporary incentive program. It is separate from:

- Faucet onboarding funds;
- the permanent 5000 Q protocol Epoch distribution;
- development/contribution rewards under RFC-0068 and ECO-0007.

`aidn-testnet-1 Q` does not imply convertibility to Mainnet Q. Participation
history remains verifiable, but no future Mainnet reward is promised.

## 2. Launch parameters

```yaml
program_id: testnet-alpha-participation-1
participation_window: 600 seconds
reward_per_eligible_window: 1 Q
heartbeat_interval: 30 seconds
minimum_presence: 80 percent
minimum_enrollment: 1800 seconds
settlement_period: 86400 seconds
funding_source: TESTNET_INCENTIVE_TREASURY
```

The reviewed host policy is stored as
`config/testnet-participation.example.toml` using schema
`aidn.testnet-participation.v1`. The release replaces the example activation
Epoch with the finalized public-network boundary before enabling payouts.

One day contains at most 144 eligible windows and therefore at most 144 Q per
Node Identity. The 1 Q unit is accrued per eligible ten-minute window, not per
heartbeat message.

## 3. Eligibility

Eligibility is attached to a registered Node Identity, not directly to a
Wallet. For a window to qualify:

- registration and Node Identity verification are finalized;
- the node completed the 30-minute enrollment period before the window;
- the protocol version is allowed by the program;
- the Node Identity is neither banned nor retired during the window;
- finalized, signature-verified heartbeat evidence covers at least 80% of the
  expected heartbeat slots;
- network and chain identifiers match the active program.

Multiple heartbeats in the same 30-second slot count once. Duplicate evidence
IDs count once. Wallet or Endpoint multiplication does not increase one Node
Identity's eligible-window count.

## 4. Daily settlement

The existing 24-hour canonical protocol Epoch is the settlement period. Local
wall-clock timers SHALL NOT pay rewards.

```text
finalized heartbeats
        -> freeze at Epoch close
        -> classify 144 ten-minute windows
        -> produce deterministic accruals
        -> commit one evidence root and settlement hash
        -> consensus-authorized treasury payment
```

The calculator is non-emitting. It neither credits a Wallet nor creates a
generic `REWARD_MINT`. The payout worker converts the finalized settlement into
one canonical `WALLET_TRANSFER` per earning Node Identity, signed by the
dedicated Testnet Incentive Treasury. Every transfer binds the program ID,
source Epoch, evidence root, settlement ID and settlement hash. Rebuilding the
same batch yields the same operation IDs; finalized duplicates fail through
the existing Ledger replay protection. The worker preflights the total reward
plus one network fee per recipient against the treasury balance.

This deliberately reuses the audited Wallet transfer path. It does not add a
second mint authority and cannot pay more Q than the separately funded testnet
treasury owns. A payout worker SHALL persist and reconcile each submitted
operation until finality before considering a daily settlement complete.

Late heartbeats do not rewrite a finalized day. A challenged observation is
resolved before evidence freeze or handled by an explicit correction process.

## 5. Sunset

Every program has a network ID, start Epoch, and either an end Epoch or a
Governance termination operation. Mainnet activation SHALL terminate the
testnet program before or at the activation boundary. No implementation may
depend on an operator remembering to disable it manually.

## 6. Evidence retained

The protocol retains Node ID, first seen/enrollment, heartbeat-slot history,
software version, eligibility results, settlement IDs, and reward destination.
Peer/IP metadata may be retained only where policy and law permit. Evidence is
useful for Sybil analysis and contributor history; it is not proof of one
human per node.
