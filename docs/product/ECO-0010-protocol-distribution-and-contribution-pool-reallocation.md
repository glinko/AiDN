# ECO-0010 Protocol Distribution and Contribution Pool Reallocation

Status: `Draft`

Version: `0.1`

Amends:

- `ECO-0005 Q Emission, Recycling and Epoch Reward Allocation`
- `ECO-0007 Development Reward Pool and Distribution Policy`

## 1. Daily base emission

The 24-hour protocol Epoch retains a base emission of exactly `5000 Q`.

```text
5000 Q
  3000 Q  Contribution Pool (60%)
  2000 Q  Protocol Service Pools (40%)
```

The implemented pre-amendment service-pool ratio is `30:30:30:10`, not the
illustrative `30:30:5` ratio used in early discussion. ECO-0010 preserves the
implemented ratio inside the 2000 Q Protocol Service allocation:

| Pool | Q per base Epoch | Total share |
| --- | ---: | ---: |
| Contribution | 3000 | 60% |
| Consensus | 600 | 12% |
| Registry | 600 | 12% |
| Validation | 600 | 12% |
| Faucet | 200 | 4% |
| Total | 5000 | 100% |

Canonical q-atom arithmetic and deterministic remainder assignment remain
mandatory. Recyclable Q follows the same active versioned shares unless a
future policy explicitly assigns a recyclable category elsewhere.

## 2. Contribution mechanism

The 3000 Q allocation uses the already implemented RFC-0068/ECO-0007 flow:
eligible repository evidence, signed Wallet binding, Contribution
Attestation, challenge closure, CU scoring, normalization, caps, maturity,
unclaimed handling, and consensus-bound payment operations.

It does not create a fixed `PR -> Q` price and does not allow GitHub, a bot, or
an LLM to mint Q. The default `DevelopmentShare` becomes 6000 basis points.
All existing anti-splitting, contributor/Known Control Group caps, security
reserve, documentation reserve, carryover, and maturity rules remain active.

## 3. Separation from Testnet incentives

RFC-0077 participation payments draw from a separately funded temporary
Testnet Incentive Treasury. They do not reduce or enlarge the 5000 Q base
emission and automatically sunset under the participation program policy.

## 4. Activation

This allocation activates only through a declared future Epoch and the
existing Governance authorization path. Historical Epochs are never
recalculated. The activation record binds the exact policy hash and all five
pool shares.
