# Controlled Localnet Epoch 1 RFC-0068 / ECO-0007 Live Payout Acceptance

Date: `2026-08-13`

This record captures the first complete RFC-0068 to ECO-0007 development
reward path on the controlled AiDN localnet. It is live consensus evidence,
not a claim of public-network readiness or organizational independence.

## Scope and Network

- Network: `aidn-localnet-1`
- Chain: `chain-Anm7Jk`
- Validators: `192.168.88.128`, `192.168.88.129`, `192.168.88.130`
- Finality observation: `3/3` RPC agreement
- Protocol authority policy hash:
  `sha256:40c7c0371dca2160043bcd05e37ceb3d8cc8ab33d67bc21b451c95b3e45625a4`
- Authority threshold: `2-of-3`
- ECO-0007 activation approval hash:
  `sha256:763013829e936f51eb33eab072edba980366db5ed315389f0f9ee25492db9545`
- ECO-0007 activation ID:
  `sha256:4bcd9bebe1d6fc375d823b4fad07367d3d79423dbff9ae01211b333adbb55b71`
- Production profile hash:
  `sha256:e8952c81b17dc0a274eeb2504ef79d9ef6c64a70853260ba398c8745600ae6ad`

The localnet uses disposable controlled authority keys. Private keys and the
contributor Wallet private key were not exported or committed.

## RFC-0068 Contribution

The acceptance runner created a clean repository clone and a real protected
`main` merge commit. The contribution was then processed through the normal
intake, Wallet-claim, authority-signature, challenge and finalization path.

- Repository: `controlled-localnet-aidn`
- Base commit: `ada519632c7463103453cb3926045dc61668111b`
- Source commit: `d3e16d0a273874863f8c125b5fe817bf7c0a5761`
- Merge commit: `1500b5046755b15d2befccf5ff1e8a072f673674`
- Contribution ID:
  `sha256:755f843ee1c294fd0bf6e57f388f76f4b14eaf921d50323d6b89d4a1d456217a`
- Attestation hash:
  `sha256:cd392ae53fbd117d25a077c2635b3bcb7fb23cd7d21f12e4ab397775db7f0c46`
- Contribution units: `3178 milli-CU`
- Wallet claim: `VERIFIED`
- Wallet: `wallet-160f13d3acf5`
- Wallet binding hash:
  `sha256:ec1ba9477ffb2a02ab7ffed71c3ecd91469a6cf94ea4261142c3c33ecb22b248`
- Wallet claim hash:
  `sha256:12a676c2d9d8304f95896be1b8e75851f56f04a7866ab6a9536427b50e800a46`
- Authority signatures: `controlled-localnet-authority-a` and
  `controlled-localnet-authority-b`, state `VERIFIED`
- Challenge boundary: epoch `2`
- Contribution finalization: epoch `3`, state `FINALIZED`

The merge commit and Wallet claim are evidence inputs. Neither Git nor the
Wallet claim independently creates Q.

## ECO-0007 Batch

The batch was built from the finalized RFC-0068 attestation and the current
`READY` quorum preflight. The preflight matched across all three validators:

- Pool: `GENERAL_DEVELOPMENT`
- Pool budget: `250000000 q_atoms = 250 Q`
- Preflight hash:
  `sha256:e9be982a3c40028919ba9db93878a804c09da13d99e5eb358785c46ef421314f`
- Source transition operation:
  `7af516b4a59d04439bcfc93e761172896df413d709d1923d0bbd3d905bad035f`
- Batch ID:
  `sha256:97d51959d44d2562a9386ae0094eb504bfbb936244de6d632b1c16f3077f6b8c`
- Batch hash:
  `sha256:929da330478e80bd18d42d6b0c427ee7f67efaa371db4c4570c0f01be476d069`
- Gross scheduled reward: `3178000 q_atoms = 3.178 Q`
- Immediate payout: `1271200 q_atoms = 1.2712 Q`
- Maturity reserve: `1906800 q_atoms = 1.9068 Q`
- Q denomination: `1 Q = 1000000 q_atoms`

The batch commitment remains explicitly non-emitting and `simulation_only`.
Economic effects were created only by the separately authorized, ordered
consensus operations listed below.

## Consensus Finality

Each operation was submitted once by the resumable executor and independently
verified through the canonical `operation/finalized` projection on all three
validator RPCs. The record digest and sequence were identical on every RPC.

| Sequence | Operation | Operation ID | Transaction | Finality block | Record digest | RPC quorum |
| ---: | --- | --- | --- | ---: | --- | ---: |
| 29 | `DEVELOPMENT_REWARD_CALCULATE` | `c4f4186876d062c36f7bb4467eb2d154536507d3266d6008d06d465dd4822243` | `4FE184EB6B4F09EDDE7971AF309A8A8654A388F52D7C9451452A82220DB31F0B` | 67859 | `8faae396cfacca4cbefb68b5eb4ac7d14dda94c7dc089fb7aeaec75d50603a22` | 3/3 |
| 30 | `DEVELOPMENT_POOL_ALLOCATE` | `6d5187f66232d1897cbaf9d3acb9d4806cfb90a7e23f527b7a967a7cf2449882` | `A0EB790B9AAEB6F4CA9E9ADA80083B2D5560134CC368D74326E060E7998784B8` | 67862 | `49a7514032c04de7a91190edccb4f154c29b19959819db4d97c2a34ba99085c2` | 3/3 |
| 31 | `DEVELOPMENT_REWARD_RESERVE` | `a4d618d49f29547497acd29683f55d1ff99793ae9be0f509595e3a8a5396630f` | `1F368614B42AD166E5FA68451F507F4B421890606C90277F62C33BD854B77C76` | 67864 | `1d35205a1d9d9f80a85448f90b4048eba9fde5b7fcd804a7c80703039d9e69be` | 3/3 |
| 32 | `DEVELOPMENT_REWARD_PAY_IMMEDIATE` | `cf53477ac5b6321503b773689cab3ed4d15bfedf69b0903d10986b2f38a9d78f` | `144A06A0D4C6BF5B46181E55BE5FE980098D5086992E4F574F65E3458DCB8B7B` | 67947 | `e7d263b570ff88de24876b2220c876bef83db41fc7940796d6c825e7d1c9df49` | 3/3 |

The payment transaction returned `tx_result.code=0`. The recipient balance
was read independently from all three validators as:

```text
wallet-160f13d3acf5 = 1271200 q_atoms = 1.2712 Q
```

## Restart and Replay Evidence

The first executor invocation persisted an in-flight envelope and stopped in
`AWAITING_VERIFIED_FINALITY` without claiming a payout. A later invocation
reconciled the same operation IDs and finalized the remaining stages. A clean
replay then returned `FINALIZED` immediately for all four operations, with the
same execution hash and transaction identities. No new operation ID was
created, the pending file was cleared, and the recipient balance remained
`1271200 q_atoms`.

This proves the controlled executor's restart/reconciliation and replay
boundary for this batch. It does not prove maturity-stage payout, public
network deployment, external organizational independence, or production
governance readiness.

## Implementation Corrections Exercised

- JSON intake boundaries now normalize factor values, role allocations and
  authority objects into the same typed models used by the domain service.
- The reward batch builder accepts BOM-prefixed Windows JSON while preserving
  strict schema and hash validation.
- The executor persists exact envelopes and reuses operation IDs during
  recovery instead of resubmitting a new payment.

## External Evidence

The full disposable evidence archive remains outside the repository at:

```text
%USERPROFILE%\.aidn\controlled-localnet-20260813\epoch-1-eco0005-evidence\contribution-acceptance-v3\
```

The checked-in record contains public hashes and operational results only.
