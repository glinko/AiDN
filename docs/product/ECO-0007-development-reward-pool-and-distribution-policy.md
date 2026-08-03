# ECO-0007 AiDN Development Reward Pool and Q Distribution Policy

Status: `Draft`

Version: `0.1`

Depends on:

- `ECO-0004 AiDN Epoch Emission Allocation`
- `ECO-0005 Q Emission, Recycling and Epoch Reward Allocation`
- `ECO-0006 AiDN Validator Set and Reward Parameters`
- `RFC-0036 AiDN Ledger State Machine`
- `RFC-0048 Epoch Engine`
- `RFC-0058 Participant Eligibility and Sybil Resistance`
- `RFC-0059 Ledger Operation Catalog`
- `RFC-0067 Protocol Governance and Authorization Policy`
- `RFC-0068 Development Contribution Accounting and Attribution Protocol`

## 1. Purpose

This document defines the bounded economic mechanism that rewards accepted development contributions with Q. It specifies the Development Reward Pool, its epoch-emission source and carryover, CU conversion, caps and normalization, role allocations, immediate and maturity payments, bounties, security work, claims, corrections, Governance parameters, and emission conservation.

`RFC-0068` determines eligible contribution evidence and relative Contribution Units. This policy determines Q distribution. Neither a merge nor raw lines of code independently mint Q.

## 2. Core Model

```text
Epoch emission -> bounded Development Reward Pool -> finalized RFC-0068
contributions -> capped and normalized rewards -> immediate and maturity payments
```

For epoch `e`:

```text
DevelopmentBaseAllocation_e = floor(DistributableEpochEmission_e * DevelopmentShare_e)

DevelopmentPool_e = DevelopmentBaseAllocation_e
                  + DevelopmentCarryoverIn_e
                  + DedicatedDevelopmentGrants_e
                  + ReturnedUnclaimedRewards_e
                  + ReturnedCancelledRewards_e
```

Distributable epoch emission is defined by the active emission policy and may contain base issuance, recycled Q, assigned protocol revenue, grants, and donations. This ECO does not redefine total emission. New Q assigned to development SHALL NOT exceed the active epoch allocation; carryover is already allocated but undistributed Q.

Recommended launch values are `DevelopmentShare = 5%`, with an ordinary Governance range of 3% through 10%. A change outside that range SHOULD require an enhanced Governance threshold and SHALL apply only from a declared future epoch.

## 3. Pool Accounts and Reserves

The protocol SHOULD preserve logically distinct buckets, even if one Treasury Wallet holds them:

- `GENERAL_DEVELOPMENT` for ordinary RFC-0068 contributions;
- `SECURITY_AND_AUDIT` for private reports, emergency fixes, audits, cryptographic review, incident response, and high-risk dependency remediation;
- `DOCUMENTATION_AND_EDUCATION` for operator/protocol documentation, tutorials, localization, and adoption tooling;
- `BOUNTY_RESERVE`, `MATURITY_RESERVE`, and `UNCLAIMED_REWARDS`.

Security rewards are based on severity, exploitability, affected systems, disclosure quality, evidence, and remediation, not public patch size. A recommended Security allocation is 10% through 25% of the base allocation. Governance may reserve documentation or contribution-class shares to avoid ordinary production-code work consuming all funds.

Unpaid maturity rewards SHALL remain reserved for their contribution and cannot fund current oversubscription. Reserved bounty Q cannot fund unrelated ordinary work before bounty release or expiry.

```text
SpendableDevelopmentBudget_e = DevelopmentPool_e
                             - MaturityReserveRequirements_e
                             - SecurityReserveRequirements_e
                             - ApprovedBountyReservations_e
```

Unused uncommitted pool value carries forward. The recommended maximum carryover is six base allocations. Value above the cap SHALL be explicitly returned to the emission reserve, assigned to security, assigned to an approved major bounty, or burned/recycled under active emission policy; it SHALL NOT disappear.

## 4. Contribution Reward Calculation

Every calculation SHALL reference a finalized RFC-0068 Contribution Attestation with Contribution ID, epoch, CU, role allocation, eligibility/challenge state, maturity schedule, and verified Wallet bindings. CU are non-transferable accounting units, not Q.

Governance may publish `NominalQPerCU`; the recommended initial value is one nominal Q per CU:

```text
NominalReward_i = ContributionUnits_i * NominalQPerCU
ContributionCap_i = min(applicable OrdinaryPerContributionCap,
                         applicable BountyCap_i,
                         applicable ExceptionalApprovalCap_i)
CappedNominalReward_i = min(NominalReward_i, ContributionCap_i)
TotalEpochRewardDemand = SUM(CappedNominalReward_i)
```

The ordinary cap is recommended as 20% of one epoch's Development Base Allocation. An exceptional cap requires enhanced approval. A pre-approved bounty may use a higher range but SHALL disclose its minimum/maximum reward, criteria, funding reservation, review authority, and expiry.

When demand does not exceed the available contribution budget, each valid contribution receives its capped nominal reward and the remainder carries forward. The Pool SHALL NOT be exhausted merely because Q is available. When demand exceeds the available budget:

```text
NormalizedReward_i = AvailableEpochContributionBudget
                   * CappedNominalReward_i
                   / TotalEpochRewardDemand
```

Canonical allocation SHALL use fixed-point arithmetic, floor allocation, largest-remainder distribution, and Contribution ID ordering to break equal remainders. Governance may define a minimum reward threshold and a repository, contributor, or Known Control Group epoch cap. The recommended automatic contributor cap is 35% of one base allocation; exceeding it triggers deferred payment, bounty funding, or enhanced review, not automatic confiscation.

## 5. Reward Schedule and Roles

The default schedule is:

| Stage | Share | Recommended boundary |
| --- | ---: | --- |
| Immediate | 40% | challenge window closed |
| Maturity stage 1 | 30% | 4 epochs after merge |
| Maturity stage 2 | 30% | 12 epochs after merge |

```yaml
development_reward_schedule:
  contribution_id:
  gross_reward:
  immediate_amount:
  maturity_stage_one_amount:
  maturity_stage_two_amount:
  immediate_epoch:
  maturity_stage_one_epoch:
  maturity_stage_two_epoch:
  schedule_hash:
```

Initial finalization accounts for the full Gross Reward; unpaid stages move to `MATURITY_RESERVE`. The immediate payment becomes payable only after valid attestation, challenge closure, a verified Wallet, and no blocking security issue. Maturity uses RFC-0068 conditions.

Reduced maturity returns only cancelled unpaid value to the pool or reserve. It SHALL NOT automatically claw back an immediate payment. A requirement change normally preserves maturity eligibility; prompt remediation of an ordinary defect may preserve it and is normally grouped with the original work. Proven intentional gaming cancels unpaid value and may require a separate penalty process.

Each Gross Reward is divided according to RFC-0068's attested allocation:

```text
ParticipantReward_p = GrossReward * AllocationBasisPoints_p / 10,000
```

Explicitly unallocated role share returns to the pool. Reviewer rewards require substantive independent review. Maintainer status alone does not create a share of every contribution.

## 6. Bounties, Grants, and External Funding

```yaml
development_bounty:
  bounty_id:
  title:
  description:
  acceptance_criteria:
  eligible_repository_ids:
  contribution_class:
  minimum_reward:
  maximum_reward:
  reserved_budget:
  priority_factor:
  reviewer_policy:
  opens_at:
  expires_at:
  bounty_hash:
  authorization_signature:
```

Approved bounty funds are reserved from the current Pool, carryover, dedicated grants, or a bounded future allocation. Expired uncompleted bounty funds return to the Pool. CU may inform a bounty result but need not set it linearly. Useful unsolicited work may earn an ordinary CU reward but has no reward guarantee before merge and attestation.

External grants SHALL declare amount, permitted scope, expiry, Governance conditions, and unused-fund treatment. Restricted grants SHALL remain restricted. Unrestricted donations may augment carryover without changing base emission. Pool accounting distinguishes `NEW_EMISSION`, `RECYCLED_Q`, `DONATED_Q`, `CARRYOVER_Q`, and `RETURNED_REWARD_Q`.

## 7. Claims, Records, and Conservation

An otherwise valid allocation without a verified Wallet is `UNCLAIMED`; Q remains in the Unclaimed bucket. The recommended claim window is 12 epochs. A later valid binding claims the unchanged allocation; price or later pool conditions SHALL NOT reprice it. On expiry, Q returns to carryover or the general emission reserve under active policy. Lost Wallet access requires approved identity recovery or Wallet rotation.

```yaml
development_reward_record:
  reward_id:
  contribution_id:
  contribution_epoch:
  distribution_epoch:
  contribution_units:
  nominal_reward:
  capped_nominal_reward:
  normalization_factor:
  gross_reward:
  role_distribution:
  vesting_schedule:
  pool_source_breakdown:
  reward_state:
  reward_hash:
```

Recommended derivation:

```text
RewardID = HASH(ContributionID + RewardScheduleHash + DistributionEpoch)
```

Reward states are `CALCULATED`, `RESERVED`, `IMMEDIATE_PAYABLE`, `IMMEDIATE_PAID`, `MATURITY_PENDING`, `MATURITY_PAYABLE`, `MATURED`, `UNCLAIMED`, `CANCELLED_UNVESTED`, and `FINALIZED`.

For every epoch:

```text
DevelopmentPoolIn = DevelopmentBaseAllocation + CarryoverIn + Grants + ReturnedRewards
DevelopmentPoolIn = PaidImmediateRewards + ReservedMaturityRewards + ReservedBounties
                  + SecurityAllocations + CarryoverOut + ReturnedToEmissionReserve
```

For every contribution:

```text
GrossReward = PaidImmediate + PaidMaturity + Unclaimed + CancelledUnvested + StillReserved
```

Every atom entering the Pool SHALL end an epoch in one defined state. Cancelled unpaid rewards return to the Pool and are not burned unless the active emission policy explicitly requires it.

Corrections may address attribution, arithmetic, duplicates, invalid attestation, invalid Wallet binding, or challenge resolution. A negative correction first reduces unpaid maturity, unclaimed value, or future offsets. Recovery of already paid Q requires separate authorization.

## 8. Governance, Security, and Operations

Governance may control Development Share, security/documentation shares, nominal rate, minimum reward, caps, schedule shares/boundaries, claim window, carryover cap, repository caps, bounty reserve, and security reward cap. Historical finalized contributions SHALL NOT be repriced. Emergency action may pause new rewards, suspend a compromised repository, freeze disputed payouts, or disable an attestation authority; it SHALL NOT silently redirect Pool funds.

`RFC-0059` SHOULD provide equivalent operations:

```text
DEVELOPMENT_POOL_ALLOCATE
DEVELOPMENT_POOL_CARRYOVER
DEVELOPMENT_BOUNTY_CREATE
DEVELOPMENT_BOUNTY_RESERVE
DEVELOPMENT_BOUNTY_RELEASE
DEVELOPMENT_BOUNTY_EXPIRE
DEVELOPMENT_REWARD_CALCULATE
DEVELOPMENT_REWARD_RESERVE
DEVELOPMENT_REWARD_PAY_IMMEDIATE
DEVELOPMENT_REWARD_PAY_MATURITY
DEVELOPMENT_REWARD_MARK_UNCLAIMED
DEVELOPMENT_REWARD_CLAIM
DEVELOPMENT_REWARD_CANCEL_UNVESTED
DEVELOPMENT_REWARD_CORRECT
```

The current strict consensus profile implements `DEVELOPMENT_REWARD_CALCULATE`
as immutable evidence, `DEVELOPMENT_POOL_ALLOCATE` as a source-bound pool
reserve, `DEVELOPMENT_REWARD_RESERVE` as a schedule-bound reward reserve,
`DEVELOPMENT_REWARD_PAY_IMMEDIATE` as a source-bound immediate payment,
`DEVELOPMENT_REWARD_PAY_MATURITY` as a source-bound maturity payment, and
`DEVELOPMENT_REWARD_MARK_UNCLAIMED` as a source-bound unclaimed-stage record,
and `DEVELOPMENT_REWARD_CLAIM` as a Wallet-bound claim transition.
Calculation, allocation, reserve and unclaimed transitions do not credit
Wallets or mint Q. Immediate payment requires finalized predecessors, the
exact payable payment hash and stage, a verified Wallet binding, replay
protection, and snapshot-safe reserve/pool conservation checks; maturity
payment additionally requires a finalized epoch transition whose opening
epoch reaches the exact stage-one or stage-two boundary and accepts only a
reserved maturity stage. Unclaimed marking requires an exact `UNCLAIMED`
stage with no Wallet, records the claim-expiration epoch, and leaves both the
reserve and Wallet unchanged. No transition is an alias for `REWARD_MINT`.
`DEVELOPMENT_REWARD_CLAIM` requires that immutable record, a finalized epoch
boundary inside its claim window, and a valid RFC-0068 signed Wallet binding;
it creates a separate `CLAIMED` record, consumes exactly one stage and credits
only the bound Wallet. Expiry-return and finalized evidence closure are also
implemented as source-bound transitions. Pool carryover is bound to the source
epoch transition and conservation split; bounty create/reserve/release/expiry
is bound to the allocated pool and immutable bounty state; cancellation and
correction preserve paid history and append only validated unpaid-balance
adjustments. All of these transitions are dispatched and validated in both
ABCI and deterministic execution, with snapshot restore coverage.

Pool allocation, carryover, bounty reservation, reward calculation/reservation/payment, unclaimed marking, claim, cancellation, and correction SHALL be idempotent. Each paid stage atomically debits the applicable bucket, credits the verified Wallet, updates the record, and updates the maturity reserve. Unclaimed marking only records the immutable claim state and does not debit the reserve. A `(Reward ID, Payment Stage)` cannot pay, become unclaimed, or be claimed twice; a claim keeps the original unclaimed evidence and consumes the corresponding reserved stage exactly once. Failed payment remains reserved for idempotent retry.

The system SHALL mitigate line inflation, PR splitting, fake reviewers, maintainer collusion, Wallet substitution, duplicate rewards, reserve theft, bounty double funding, Sybil identities, and normalization manipulation. No bot, webhook, or maintainer account may mint arbitrary Q: every payment is bounded by epoch allocation, available Pool, caps, canonical attestation, and deterministic distribution.

Ordinary rewards are public or pseudonymous. Private security reward evidence and attribution may remain protected until disclosure is safe. Public accounting SHOULD show Pool allocation, carryover, reward totals, maturity reserve, security reserve, unclaimed and cancelled amounts, while omitting sensitive security detail.

## 9. Launch Parameters, MVP, and Deferred Work

Recommended launch profile:

```yaml
development_share: 0.05
security_pool_share_of_development: 0.15
documentation_pool_share_of_development: 0.05
nominal_q_per_cu: 1.0
ordinary_per_contribution_cap_fraction: 0.20
automatic_contributor_epoch_cap_fraction: 0.35
immediate_reward_share: 0.40
maturity_stage_one_share: 0.30
maturity_stage_two_share: 0.30
maturity_stage_one_epochs: 4
maturity_stage_two_epochs: 12
claim_window_epochs: 12
maximum_carryover_epochs: 6
```

Before mainnet activation, simulation SHOULD cover low/high contribution demand, a dominant contributor, fragmented PRs, collusive review, a large PR, security expenditure, inactive epochs, oversubscription, and high carryover. A low-demand epoch does not award its entire pool to one small contribution; high-demand epochs normalize eligible demand except for properly reserved bounty/security rules.

The post-MVP minimum implementation includes fixed Development Share, bounded Pool and carryover, CU conversion, nominal rate, caps, deterministic normalization, role distribution, immediate/maturity schedule, reserves, unclaimed claims, bounties, Security Pool, reward records, Ledger payments, and public pool accounting.

The first executable rollout is deliberately narrower than the complete
policy. Governance may attach a signed rollout profile to the activation
approval. The profile can cap total accepted reward atoms per calculation
epoch, the number of contribution records, and optionally the accepted reward
attributable to one contributor. These caps are checked before a calculation
commitment can be created and are inherited by reserve/payment transitions. A
rollout profile is prospective and becomes active only at its declared
effective epoch; it cannot retroactively reprice a finalized calculation.

Deferred features include dynamic Development Share, market CU rates, quadratic allocation, decentralized reviewer auctions, ecosystem-wide impact rounds, cross-project grants, public-goods voting, price stabilization, development insurance, and contributor-delegation markets.

Required error codes include:

```text
DEVELOPMENT_POOL_NOT_FOUND
DEVELOPMENT_POOL_INSUFFICIENT
DEVELOPMENT_POOL_ACCOUNTING_CONFLICT
DEVELOPMENT_CARRYOVER_LIMIT_EXCEEDED
DEVELOPMENT_CONTRIBUTION_NOT_FINALIZED
DEVELOPMENT_REWARD_ALREADY_CALCULATED
DEVELOPMENT_REWARD_CALCULATION_INVALID
DEVELOPMENT_NOMINAL_RATE_INVALID
DEVELOPMENT_NORMALIZATION_INVALID
DEVELOPMENT_CONTRIBUTION_CAP_EXCEEDED
DEVELOPMENT_CONTRIBUTOR_CAP_REVIEW_REQUIRED
DEVELOPMENT_ROLE_ALLOCATION_INVALID
DEVELOPMENT_REVIEW_REWARD_INELIGIBLE
DEVELOPMENT_MATURITY_NOT_REACHED
DEVELOPMENT_MATURITY_CANCELLED
DEVELOPMENT_MATURITY_RESERVE_INSUFFICIENT
DEVELOPMENT_WALLET_NOT_VERIFIED
DEVELOPMENT_REWARD_UNCLAIMED
DEVELOPMENT_REWARD_UNCLAIMED_DUPLICATE
DEVELOPMENT_REWARD_UNCLAIMED_STATE_INVALID
DEVELOPMENT_REWARD_UNCLAIMED_WALLET_INVALID
DEVELOPMENT_REWARD_UNCLAIMED_ID_INVALID
DEVELOPMENT_CLAIM_WINDOW_EXPIRED
DEVELOPMENT_REWARD_CLAIM_DUPLICATE
DEVELOPMENT_REWARD_CLAIM_AMOUNT_INVALID
DEVELOPMENT_REWARD_CLAIM_EPOCH_INVALID
DEVELOPMENT_REWARD_CLAIM_UNCLAIMED_NOT_FOUND
DEVELOPMENT_REWARD_CLAIM_UNCLAIMED_BINDING_INVALID
DEVELOPMENT_REWARD_CLAIM_RESERVE_EXCEEDED
DEVELOPMENT_REWARD_CLAIM_STAGE_EXCEEDED
DEVELOPMENT_REWARD_CLAIM_POOL_EXCEEDED
DEVELOPMENT_REWARD_EXPIRE_UNCLAIMED
DEVELOPMENT_REWARD_EXPIRY_DUPLICATE
DEVELOPMENT_REWARD_EXPIRY_NOT_REACHED
DEVELOPMENT_REWARD_EXPIRY_POOL_EXCEEDED
DEVELOPMENT_REWARD_FINALIZED_COMMITMENT_DUPLICATE
DEVELOPMENT_REWARD_ROLLOUT_EPOCH_CAP_EXCEEDED
DEVELOPMENT_REWARD_ROLLOUT_CONTRIBUTION_COUNT_EXCEEDED
DEVELOPMENT_REWARD_ROLLOUT_CONTRIBUTOR_CAP_EXCEEDED
DEVELOPMENT_REWARD_WALLET_BINDING_INVALID
DEVELOPMENT_REWARD_WALLET_BINDING_MISMATCH
DEVELOPMENT_BOUNTY_NOT_FOUND
DEVELOPMENT_BOUNTY_EXPIRED
DEVELOPMENT_BOUNTY_CRITERIA_NOT_MET
DEVELOPMENT_REWARD_PAYMENT_DUPLICATE
DEVELOPMENT_REWARD_PAYMENT_FAILED
DEVELOPMENT_REWARD_CORRECTION_INVALID
```

## 10. Invariants

- merged code does not independently mint Q; carryover and returned rewards are not new emission;
- every Pool atom has a defined accounting state; security, bounty, and maturity reserves remain within the Pool and protected from unrelated spending;
- CU are non-transferable; caps apply before normalization; a low-demand epoch does not force full distribution;
- role shares are deterministic; one payment stage is never paid twice; cancelled unvested value returns to the Pool;
- raw lines, reviewer count, PR count, and contributor aliases do not create reward demand without accepted value;
- a signed rollout profile can only narrow the active reward boundary; it cannot widen the approved Pool or create new emission;
- parameters are prospective, historical rewards are not repriced, and emergency pauses preserve accounting;
- GitHub records what happened, RFC-0068 evaluates contribution, and this ECO bounds the Q distribution.
