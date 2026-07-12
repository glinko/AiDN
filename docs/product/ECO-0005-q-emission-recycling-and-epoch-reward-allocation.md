# ECO-0005 Q Emission, Recycling and Epoch Reward Allocation

Status: `Draft`

Version: `0.2`

Supersedes:

- `ECO-0005 Version 0.1`

Depends on:

- `ECO-0000 Economic Principles`
- `ECO-0003 Validation Economics`
- `RFC-0035 Validation Escrow System`
- `RFC-0036 AiDN Ledger State Machine`
- `RFC-0037 Settlement Engine`
- `RFC-0040 Service Verification Framework`
- `RFC-0041 Reputation Profile Engine`
- `RFC-0046 Registry Architecture`
- `RFC-0047 CometBFT Consensus Integration`
- `RFC-0048 Epoch Engine`
- `RFC-0057 Validation Report Specification`

## Purpose

This document defines:

- the base emission of `Q`;
- the recycling of `Q` removed from circulation;
- the Epoch Reward Budget;
- the division of the budget into reward pools;
- proportional reward distribution among participants;
- the initial Faucet allocation mechanism;
- the effect of emission and recycling on total `Q` supply.

`Q` is the internal accounting and compute-exchange unit of AiDN.

`Q` is not defined as a fiat-denominated asset.

This document extends [ECO-0000 Economic Principles](./ECO-0000-economic-principles.md) with the concrete Epoch reward-budget, recycling, and carryover model for the current draft stack.

## 1. Core Economic Principle

Each Epoch receives a predetermined and limited `Q` reward budget.

The number of:

- Hypervisors;
- Services;
- Endpoints;
- Validators;
- Registry operators;
- Consensus participants;

SHALL NOT automatically increase the total reward budget.

A larger number of eligible participants causes the same pool to be divided among more participants.

The protocol therefore rewards competition for useful contribution without allowing participant count to become an uncontrolled emission mechanism.

## 2. Epoch Duration

The initial Epoch duration is:

`24 hours`

Emission and reward calculations occur once per Epoch through deterministic Epoch Tasks.

All calculations use finalized Ledger state.

## 3. Base Emission

The protocol authorizes a base reward budget of:

`5000 Q per Epoch`

The amount is a versioned protocol parameter.

It MAY be changed by a future protocol upgrade.

The Base Emission Budget is an emission authorization.

`Q` is created only when an eligible reward or Faucet payment is finalized.

Unpaid portions of most reward pools are not automatically minted.

## 4. Q Removed from Circulation

Some protocol operations remove existing `Q` from circulation.

Initial examples include:

- Network Fees;
- protocol penalties;
- Validator penalties;
- Consensus slashing;
- forfeited Validation Bonds;
- other explicitly defined protocol deductions.

Removed `Q` SHALL be recorded by the Ledger.

## 5. Recyclable Removal

The MVP treats eligible protocol deductions as recyclable removals.

A recyclable removal:

1. removes existing `Q` from the responsible Wallet or locked balance;
2. temporarily reduces circulating and total supply;
3. becomes available for redistribution through a future Epoch Reward Budget.

This mechanism transfers `Q` from protocol-consuming or rule-violating participants toward participants maintaining network infrastructure.

## 6. Permanent Burn

A future protocol version MAY define permanent burns.

Permanently burned `Q`:

- reduces total supply;
- is not added to a later reward budget;
- cannot be restored.

Unless explicitly marked as permanent, current MVP protocol deductions are recyclable.

## 7. Recyclable Amount

For Epoch `t`, the recyclable amount is calculated from eligible `Q` removed during the previous finalized Epoch.

`RecyclableAmount(t) = EligibleRemovedQ(t - 1) + RecycleBacklog(t - 1)`

Only finalized Ledger Operations SHALL contribute to the calculation.

## 8. Epoch Reward Budget

The new reward authorization for Epoch `t` is:

`NewEpochRewardBudget(t) = BaseEmission + RecyclableAmount(t)`

With the initial Base Emission:

`NewEpochRewardBudget(t) = 5000 Q + RecyclableAmount(t)`

## 9. Net Supply Effect

When all recyclable `Q` is eventually redistributed, recyclable removal does not create long-term inflation.

Example:

`500 Q` removed in Epoch `10`

Epoch `11` authorizes:

`5000 Q` base emission

`+ 500 Q` recycling

`= 5500 Q`

If the entire budget is distributed:

`5500 Q` minted

`- 500 Q` previously removed

`= 5000 Q` net supply growth

Therefore, maximum long-term net supply growth from the base policy is approximately:

`5000 Q per Epoch`

Actual growth MAY be lower when authorized rewards are not earned or distributed.

## 10. Circulation Is Not Emission

The following operations only move existing `Q` and SHALL NOT create new `Q`:

- Session payments;
- Wallet transfers;
- Deposit locks;
- Deposit refunds;
- Escrow locks;
- Escrow releases;
- Stake deposits;
- Stake returns;
- direct transfers between protocol objects.

Only explicit Mint Operations increase supply.

## 11. Budget-First Distribution

Reward calculation SHALL follow this order:

Determine Epoch Reward Budget

`->`

Divide Budget into Reward Pools

`->`

Determine Eligible Participants

`->`

Calculate Participant Weights

`->`

Distribute Each Pool Proportionally

`->`

Mint Final Rewards

Individual claims SHALL never increase the size of the pool.

Detailed intra-pool eligibility, weighting, diversity reduction, concentration caps, and Reward Mint derivation are defined separately by `ECO-0004`.

## 12. Initial Reward Pools

The initial Epoch Reward Budget is divided into the following pools:

- `Consensus Service: 30%`
- `Registry Service: 30%`
- `Validation Activity: 30%`
- `Faucet: 10%`

For a Base Emission Budget of `5000 Q`, before recyclable additions:

- `Consensus Service: 1500 Q`
- `Registry Service: 1500 Q`
- `Validation Activity: 1500 Q`
- `Faucet: 500 Q`

The same percentages apply to recyclable `Q` unless a future protocol version defines another allocation.

## 13. Pool Configuration

Pool shares SHALL be versioned protocol parameters.

Changes require:

- a protocol upgrade;
- a declared activation Epoch;
- deterministic Ledger configuration;
- no retroactive recalculation.

The total of all pool shares SHALL equal `100%`.

## 14. Service Participation

A Hypervisor MAY participate in multiple reward pools when it operates multiple eligible Services.

Example:

`Hypervisor A -> Consensus Service + Registry Service`

`Hypervisor A` MAY receive:

- a Consensus Pool share;
- a Registry Pool share.

Each reward SHALL be independently supported by proof of the corresponding work.

## 15. No Reward for Activation Alone

Enabling a Service SHALL NOT produce a reward.

A Service receives a reward only when it provides objective Duty Proof for the current Epoch.

Examples:

- signed Consensus participation;
- successful Proof of Registry responses;
- completed Validation Reports.

Configuration is not contribution.

## 16. Proportional Pool Distribution

Each eligible participant receives a weight.

For participant `i`:

`Reward(i) = PoolBudget x Weight(i) / SumOfEligibleWeights`

If all eligible participants have equal weights, the pool is divided equally.

If contribution quality differs, higher proven contribution receives a larger share.

## 17. Participant Weight

The general weight model is:

`Weight = Maturity x Health x DutyProof x Contribution`

Each factor SHALL use deterministic values between `0` and `1`, except where a service specification defines a normalized contribution score.

`ECO-0004` defines the MVP service-pool formulas and concentration controls.

## 18. Service Maturity

Maturity reflects sustained qualifying participation.

The recommended initial function is:

`Maturity(n) = 1 - 0.9^n`

Where `n` is the number of qualifying Epochs completed by the Service.

Approximate values:

- `1 -> 0.100`
- `2 -> 0.190`
- `3 -> 0.271`
- `10 -> 0.651`
- `22 -> 0.902`

Maturity affects relative weight.

It does not independently create `Q`.

## 19. Qualifying Epoch

A Service advances Maturity only when:

- it was enabled for the required Epoch interval;
- it remained eligible;
- required Duty Proof exists;
- its Health exceeded the minimum threshold;
- it was not suspended;
- it fulfilled applicable protocol responsibilities.

A Service that was merely configured but provided no proof does not advance Maturity.

## 20. Health

Health represents the current operational condition of the Service.

Health MAY include:

- availability;
- correctness;
- response latency;
- participation rate;
- completion rate;
- error rate;
- verification results.

Health is independent from long-term Reputation.

## 21. Consensus Pool

The Consensus Pool rewards Consensus Services that maintain canonical Ledger finality.

Consensus weight MAY consider:

- expected votes;
- submitted votes;
- proposal participation;
- synchronization status;
- availability;
- signing reliability;
- Maturity;
- absence of objective protocol violations.

A Consensus Service configured but not participating receives no reward.

## 22. Registry Pool

The Registry Pool rewards Registry Services that preserve and serve protocol information.

Registry weight MAY consider:

- successful Proof of Registry responses;
- object correctness;
- historical completeness;
- Snapshot availability;
- response latency;
- service availability;
- synchronization support;
- Maturity.

A Registry Service SHALL NOT receive a reward solely because it claims to store data.

## 23. Validation Activity Pool

The Validation Pool rewards completed Validation work.

It is an Activity Reward Pool rather than a passive readiness payment.

Validation weight MAY consider:

- completed eligible Validation Reports;
- report completeness;
- evidence quality;
- report complexity;
- deadline compliance;
- Validator Reputation Profile;
- protocol-level report validity.

A Validation Service that publishes no eligible report receives no Validation Pool reward.

## 24. Validation Outcome Neutrality

Validation reward SHALL NOT depend on whether the Endpoint receives Certification.

A valid report may recommend:

- `CERTIFY`;
- `CERTIFY_WITH_OBSERVATIONS`;
- `DO_NOT_CERTIFY`;
- `INCONCLUSIVE`.

The Validator is rewarded for useful, valid work rather than for producing a favorable result.

## 25. Compute Service Income

Compute Providers primarily earn `Q` through Session payments.

Compute Service does not receive a permanent share of the base infrastructure reward pools in the MVP.

This avoids paying twice for the same function:

Session Payment

`+`

Passive Compute Reward

A future protocol version MAY introduce temporary incentives for:

- underrepresented Capabilities;
- early testnet capacity;
- geographic coverage;
- network bootstrap.

Such incentives SHALL use an explicitly defined temporary pool.

## 26. Marketplace Reward

Marketplace functionality is part of the Registry and discovery layer.

The MVP does not define a separate Marketplace Reward Pool.

Storage and availability responsibilities are rewarded through the Registry Pool.

## 27. Pool Exhaustion

A Service Pool cannot be exceeded.

All eligible participants divide the available pool.

Adding more participants:

- increases competition;
- reduces average reward per participant;
- does not increase total emission.

## 28. Empty Service Pool

If a Service Pool has no eligible participants:

- no `Q` is minted from that pool;
- the unused allocation does not automatically move to another Service Pool;
- the unused allocation does not carry forward unless explicitly defined.

This prevents absent services from creating an accumulating future reward windfall.

The Faucet follows a separate carryover rule.

## 29. Faucet Purpose

The Faucet provides free `Q` to active Hypervisor operators.

Its purpose is to:

- support continued network participation;
- ensure operators can open Sessions;
- provide limited access to protocol operations;
- reduce the initial barrier to using remote resources.

The Faucet is not compensation for computation.

## 30. Faucet Pool

The Faucet receives:

`10% of the new Epoch Reward Budget`

With a base budget of `5000 Q`:

`Base Faucet Allocation = 500 Q`

The current Faucet Pool also includes unused Faucet allocation carried from previous Epochs.

`FaucetPool(t) = NewFaucetAllocation(t) + FaucetCarryover(t - 1)`

## 31. Active Hypervisor

For Faucet purposes, an Active Hypervisor is a registered Hypervisor that, at the Epoch eligibility snapshot:

- has a valid Node Identity;
- is associated with a Wallet;
- is not suspended;
- has at least one active Endpoint.

An active Endpoint is an Endpoint that:

- is registered;
- has not been withdrawn;
- has not expired;
- is active in the current Ledger state.

Validation or Certification is not required for Faucet eligibility.

## 32. Faucet Eligibility Snapshot

The set of Faucet-eligible Hypervisors SHALL be frozen at the beginning of the Epoch.

A Hypervisor becoming active during the current Epoch becomes eligible in the next Epoch.

A Hypervisor losing its final active Endpoint after the snapshot remains eligible for the current Epoch but may become ineligible in the following Epoch.

Detailed participant-eligibility, activation-age, and anti-Sybil interpretation for Faucet claims is defined separately in [RFC-0058 Participant Eligibility and Sybil Resistance](./RFC-0058-participant-eligibility-and-sybil-resistance.md).

## 33. Faucet Share

At the beginning of Epoch `t`, the protocol calculates:

`FaucetShare(t) = FaucetPool(t) / ActiveHypervisorCount(t)`

Every eligible Hypervisor has the right to claim exactly one Faucet Share during the Epoch.

## 34. Faucet Claim

A Faucet Claim SHALL:

- identify the Hypervisor;
- identify the associated Wallet;
- reference the current Epoch;
- be signed by the required Hypervisor identity;
- be finalized through the Ledger.

Each eligible Hypervisor MAY submit no more than one successful Faucet Claim per Epoch.

## 35. Faucet Payment

A successful Faucet Claim transfers the calculated Faucet Share to the Wallet associated with the eligible Hypervisor.

All eligible Hypervisors receive the same Faucet Share for the same Epoch.

Claim order does not affect payment size.

## 36. Faucet Example

Suppose:

`Faucet Pool = 500 Q`

`Active Hypervisors = 100`

Then:

`Faucet Share = 500 Q / 100 = 5 Q`

If `70` Hypervisors claim:

`Total Faucet Mint = 350 Q`

`Remaining Faucet Pool = 150 Q`

The remaining `150 Q` becomes Faucet Carryover for the next Epoch.

## 37. Faucet Carryover

Unused Faucet allocation SHALL carry into the next Epoch.

`FaucetCarryover(t) = FaucetPool(t) - TotalFaucetPayments(t)`

Carryover:

- is not yet minted `Q`;
- is not part of Total Supply;
- is an unspent emission authorization;
- remains restricted to the Faucet Pool.

Faucet Carryover SHALL NOT be redistributed to Consensus, Registry, or Validation pools.

## 38. Faucet Rounding

All Faucet calculations SHALL use deterministic fixed-point arithmetic.

Any rounding remainder remains in the Faucet Pool and carries forward.

Rounding dust SHALL NOT be assigned arbitrarily to an individual claimant.

## 39. Zero Active Hypervisors

If `ActiveHypervisorCount = 0`, then:

- no Faucet Share is calculated;
- no Faucet `Q` is minted;
- the entire Faucet Pool carries to the next Epoch.

## 40. Faucet Supply Effect

Only completed Faucet payments create `Q`.

Unclaimed Faucet Shares do not increase supply.

Example:

`Authorized Faucet Pool = 500 Q`

`Actual Claims = 350 Q`

Then:

`Actual Faucet Mint = 350 Q`

`Carryover = 150 Q`

## 41. Faucet Abuse Considerations

The MVP eligibility rule is based on registered Hypervisors with at least one active Endpoint.

This rule may be vulnerable to:

- multiple Hypervisors controlled by one operator;
- low-value Endpoint creation;
- automated identity generation;
- Sybil participation.

The MVP SHALL at minimum enforce:

- one claim per eligible Hypervisor per Epoch;
- valid Node Identity;
- valid Wallet association;
- active Endpoint requirement;
- finalized Ledger registration.

Additional anti-Sybil controls MAY be introduced later.

## 42. Future Faucet Algorithm

The Faucet allocation algorithm is not considered permanent.

Future protocol versions MAY introduce:

- adaptive payment schedules;
- changing eligibility requirements;
- network-growth factors;
- demand-based allocation;
- progressive payments;
- new-operator prioritization;
- Reputation requirements;
- anti-Sybil deposits;
- randomized or game-like allocation mechanics.

Any change SHALL occur through a versioned protocol upgrade.

Historical Faucet payments SHALL not be recalculated.

## 43. Recycle Backlog

Recyclable `Q` not distributed during its first eligible Epoch MAY remain in a Recycle Backlog.

`RecycleBacklog(t) = AvailableRecyclableBudget(t) - RecyclableBudgetActuallyMinted(t)`

The backlog represents authorized restoration of previously removed `Q`.

It is not an existing Wallet balance.

## 44. Base Budget Carryover

Unused Base Emission allocations do not carry forward, except for the Faucet Pool.

Therefore:

- unused Consensus allocation expires;
- unused Registry allocation expires;
- unused Validation allocation expires;
- unused Faucet allocation carries forward.

This prevents indefinite accumulation of unearned infrastructure rewards while preserving the explicit Faucet carryover mechanic.

## 45. Recyclable Budget Carryover

Unused recyclable authorization MAY carry forward as Recycle Backlog.

This is permitted because the corresponding `Q` previously existed and was removed from circulation.

Recycling SHALL never restore more `Q` than was previously removed.

## 46. Actual Mint

For Epoch `t`:

`ActualMint(t) = ConsensusRewards(t) + RegistryRewards(t) + ValidationRewards(t) + FaucetPayments(t)`

Actual Mint SHALL NOT exceed:

`NewEpochRewardBudget(t) + AuthorizedCarryovers(t)`

An authorized emergency pause MAY temporarily stop Reward Mint or Faucet payment finalization.

Such a pause does not by itself redefine:

- `NewEpochRewardBudget(t)`;
- `AuthorizedCarryovers(t)`;
- `RecycleBacklog(t)`;
- Faucet carryover rules.

Budget treatment during and after the pause SHALL follow the separately authorized recovery or continuation rule.

## 47. Supply Accounting

The network SHALL publish:

- Total Supply;
- Circulating Supply;
- Locked Supply;
- `Q` removed during the Epoch;
- `Q` permanently burned;
- `Q` recycled;
- Base Mint;
- Faucet Mint;
- Consensus Rewards;
- Registry Rewards;
- Validation Rewards;
- Faucet Carryover;
- Recycle Backlog.

All values SHALL be reproducible from Ledger state.

## 48. Reward Delay

Work performed in Epoch `t` MAY be finalized and paid after the end of Epoch `t + 1`.

The delay allows:

- evidence publication;
- verification;
- challenge processing;
- deterministic reward calculation;
- consensus finalization.

Faucet payments MAY be processed during the current Epoch because eligibility and payment size are fixed at Epoch start.

## 49. Protocol Parameters

The following are versioned protocol parameters:

- Base Emission per Epoch;
- Reward Pool percentages;
- Epoch duration;
- recyclable deduction categories;
- Service Maturity function;
- minimum Health requirements;
- service-specific weight rules;
- Faucet eligibility rules;
- Faucet claim limit;
- Faucet carryover policy;
- rounding precision;
- reward finalization delay.

These parameters SHALL NOT be scattered across unrelated components.

## 50. Parameter Changes

Economic parameters SHALL change only through:

- a versioned protocol upgrade;
- a deterministic activation Epoch;
- published migration rules.

New parameters SHALL affect only future Epochs.

## 51. Economic Invariants

The following invariants SHALL always hold:

- `Base New Emission Authorization = 5000 Q per Epoch`
- `Total Service Pool Shares + Faucet Share = 100%`
- `Participant Rewards <= Corresponding Pool Budget`
- `Participant Count Does Not Increase Pool Size`
- `Session Payments Do Not Mint Q`
- `Unclaimed Faucet Q Is Not Minted`
- `Faucet Carryover Remains Faucet-Restricted`
- `Recycled Mint <= Previously Removed Recyclable Q`
- `Permanent Burn Is Never Recycled`

## 52. Design Invariants

- Base `Q` emission is limited per Epoch.
- The initial Base Emission is `5000 Q` per Epoch.
- Eligible protocol deductions are recycled through later reward budgets.
- Participant count never automatically increases emission.
- Reward pools are fixed before individual rewards are calculated.
- Participants divide pools proportionally to proven contribution.
- Enabling a Service alone never earns `Q`.
- Consensus and Registry receive infrastructure rewards.
- Validation receives activity rewards.
- Compute Providers primarily earn through Session payments.
- Marketplace does not receive a separate MVP reward.
- Network Fees are removed and recycled rather than directly paid to one service.
- Faucet allocation is divided equally among active Hypervisors.
- An active Hypervisor must have at least one active Endpoint.
- Each eligible Hypervisor may claim once per Epoch.
- Unclaimed Faucet allocation carries forward.
- The Faucet algorithm may be changed by future protocol upgrades.
- All Mint, removal, recycling, and carryover values are auditable through the Ledger.
