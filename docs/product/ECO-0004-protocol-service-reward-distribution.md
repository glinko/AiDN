# ECO-0004 Protocol Service Reward Distribution

Status: `Draft`

Version: `0.1`

Depends on:

- `ECO-0000 Economic Principles`
- `ECO-0003 Validation Economics`
- `ECO-0005 Q Emission, Recycling and Epoch Reward Allocation`
- `RFC-0036 AiDN Ledger State Machine`
- `RFC-0040 Service Verification Framework`
- `RFC-0041 Reputation Profile Engine`
- `RFC-0046 Registry Architecture`
- `RFC-0047 CometBFT Consensus Integration`
- `RFC-0048 Epoch Engine`
- `RFC-0057 Validation Report Specification`
- `RFC-0058 Participant Eligibility and Sybil Resistance`
- `RFC-0059 Ledger Operation Catalog`

## 1. Purpose

This document defines how the AiDN protocol distributes Epoch Reward Pools among eligible protocol participants.

It specifies:

- common reward-calculation rules;
- participant eligibility gates;
- contribution weights;
- Service Maturity effects;
- Service Health effects;
- Duty Proof requirements;
- Known Control Group aggregation;
- reward concentration limits;
- Consensus Pool distribution;
- Registry Pool distribution;
- Validation Activity Pool distribution;
- unused reward handling;
- deterministic Reward Mint generation.

This document does not determine the total `Q` emission of an Epoch.

The total Epoch Reward Budget and pool sizes are defined by `ECO-0005`.

## 2. Scope

The MVP distributes protocol rewards through three Service pools:

`Consensus Service Pool`
`Registry Service Pool`
`Validation Activity Pool`

The Faucet Pool is governed directly by `ECO-0005` and is outside the reward-weight formulas defined here.

Compute Providers primarily receive `Q` through Session payments and do not participate in a permanent Compute Service reward pool in the MVP.

## 3. Core Principle

Each Service Pool has a fixed maximum budget for the Epoch.

Eligible participants divide that budget according to proven contribution.

The number of participants does not increase the pool.

Therefore:

```text
More eligible participants
        ↓
Greater competition for the same pool
        ↓
Lower average reward per participant
```

A participant receives no reward merely for:

- registration;
- enabling a Service;
- declaring capacity;
- publishing an Endpoint;
- remaining configured but inactive.

## 4. Relationship to ECO-0005

`ECO-0005` initially allocates the Epoch Reward Budget as follows:

| Pool | Share |
| --- | --- |
| Consensus Service | 30% |
| Registry Service | 30% |
| Validation Activity | 30% |
| Faucet | 10% |

With a base Epoch authorization of `5000Q`:

| Pool | Base Allocation |
| --- | --- |
| Consensus Service | 1500Q |
| Registry Service | 1500Q |
| Validation Activity | 1500Q |
| Faucet | 500Q |

Recyclable `Q` is allocated using the same percentages unless the active protocol configuration defines otherwise.

## 5. Budget Is a Maximum

A Service Pool is a maximum permitted reward budget.

It is not a mandatory Mint amount.

If eligible contribution justifies only part of a pool:

- only the earned amount is minted;
- unused Base Emission authorization expires;
- unused recyclable authorization returns to Recycle Backlog according to `ECO-0005`.

The protocol SHALL NOT invent additional work merely to exhaust a pool.

## 6. Reward Calculation Lifecycle

Reward calculation follows:

```text
Freeze Epoch Evidence
        ↓
Determine Eligible Participants
        ↓
Aggregate Known Control Groups
        ↓
Calculate Raw Participant Weights
        ↓
Apply Diversity Factor
        ↓
Apply Group Concentration Limits
        ↓
Calculate Final Rewards
        ↓
Generate Reward Mint Operations
        ↓
Finalize in the Following Epoch
```

All calculations SHALL be deterministic.

## 7. Reward Evidence Window

Rewards for Epoch `t` SHALL use only evidence finalized for Epoch `t`.

Evidence MAY include:

- Consensus votes;
- block proposals;
- Proof of Registry results;
- Registry service assignments;
- Validation Reports;
- Service Verification Reports;
- finalized suspension events;
- finalized Reputation Profiles;
- Epoch eligibility snapshots.

Evidence submitted after the applicable deadline SHALL not affect the closed Epoch unless an explicit grace rule exists.

## 8. Eligibility Gate

Before receiving a weight, a participant SHALL pass the Service-specific eligibility gate.

A participant failing the gate receives:

`Weight = 0`
`Reward = 0Q`

General requirements include:

- valid Service Identity;
- valid owner and Reward Beneficiary;
- required activation age;
- required Stake or Bond;
- compatible protocol version;
- no applicable suspension;
- minimum Service Health;
- required Duty Proof;
- inclusion in the Epoch eligibility snapshot.

Eligibility is binary.

Reward weighting occurs only after eligibility succeeds.

## 9. Common Reward Model

For eligible participant `i`:

`RawWeight(i) = WorkUnits(i) x QualityFactor(i)`

Where:

`QualityFactor(i) = MaturityFactor(i) x HealthFactor(i) x DutyProofFactor(i) x ReliabilityFactor(i)`

Service-specific rules MAY omit or bound individual factors where necessary.

## 10. Work Units

WorkUnits represent the amount of qualifying work performed during the Epoch.

Work Units SHALL be:

- deterministic;
- evidence-backed;
- unique;
- replay-protected;
- normalized within the Service type;
- resistant to self-generated traffic.

Examples include:

- expected Consensus duties completed;
- protocol-assigned Registry duties;
- completed Validation Reports weighted by complexity.

Self-declared workload SHALL not create Work Units.

## 11. Quality Factor

The Quality Factor adjusts Work Units according to the quality and reliability of the participant.

Every component SHALL use fixed-point values.

Typical range:

`0.0 <= Factor <= 1.0`

A Service-specific contribution bonus MAY exceed `1.0` only when explicitly capped by this document.

## 12. Maturity Factor

Maturity reflects sustained qualifying participation.

The initial function is:

`MaturityFactor(n) = 1 - 0.9^n`

Where `n` is the number of qualifying Epochs completed by the Service.

Approximate values:

| Qualifying Epoch | Maturity Factor |
| --- | --- |
| 1 | 0.100 |
| 2 | 0.190 |
| 3 | 0.271 |
| 5 | 0.410 |
| 10 | 0.651 |
| 22 | 0.902 |

Maturity SHALL not advance during an Epoch in which the Service:

- was ineligible;
- failed mandatory Duty Proof;
- remained suspended;
- failed minimum Health requirements.

## 13. Maturity Interruption

A temporary interruption MAY pause Maturity without resetting it.

A serious or prolonged interruption MAY reduce Maturity according to Service-specific rules.

The MVP SHOULD initially use:

`One failed Epoch:`
`Maturity does not advance`

`Three consecutive failed Epochs:`
`Maturity qualifying count decreases by one`

`Service retirement or new Service Identity:`
`Maturity begins from zero`

Historical Reputation remains visible.

## 14. Health Factor

Health reflects Service condition during the current Epoch.

Health MAY include:

- availability;
- correctness;
- latency;
- completion rate;
- protocol compliance;
- error rate;
- synchronization status.

Health SHALL derive from protocol-verifiable evidence.

Purely local self-reported metrics SHALL not directly increase reward weight.

## 15. Minimum Health

Every Service Pool SHALL define a minimum Health requirement.

Recommended initial threshold:

`MinimumHealth = 0.70`

Below the threshold:

`Participant is ineligible for the Epoch`

Passing the threshold does not guarantee a full reward.

## 16. Duty Proof Factor

Duty Proof confirms that the Service performed required protocol responsibilities.

Duty Proof MAY include:

- Consensus signatures;
- Registry challenge responses;
- completed Validation Reports;
- required Epoch task outputs.

The factor SHALL be zero when mandatory proof is absent.

A participant SHALL not receive reward for claimed availability without evidence of actual duty performance.

## 17. Reliability Factor

Reliability reflects whether the participant consistently produced valid and usable protocol evidence.

It MAY consider:

- malformed proof rate;
- conflicting records;
- missed deadlines;
- invalid submissions;
- recovery success;
- report consistency.

Reliability SHALL not be based on subjective popularity.

## 18. Reward Beneficiary Aggregation

Every participant declares a Reward Beneficiary Wallet.

Before final distribution, participants sharing the same Reward Beneficiary SHALL be aggregated into one Known Control Group.

Other finalized ownership relationships MAY also cause aggregation according to `RFC-0058`.

This prevents one operator from avoiding concentration limits merely by creating additional Service identities under the same known control.

## 19. Known Control Group Weight

For group `g`:

`GroupRawWeight(g) = Σ RawWeight(i)`

for all eligible participants `i` belonging to group `g`.

Members retain their individual evidence and Maturity.

Aggregation applies only to pool-share calculation and concentration controls.

## 20. Independent Group Count

For each pool, the protocol calculates:

`IndependentGroupCount = number of eligible Known Control Groups`

This value is used to determine whether enough independent participants exist to justify distributing the full pool.

## 21. Diversity Factor

A Service Pool SHALL not necessarily pay its full budget when controlled by too few independent groups.

`DiversityFactor = min(1, IndependentGroupCount / TargetIndependentGroups)`

Then:

`DistributablePool = NominalPoolBudget x DiversityFactor`

Recommended initial targets:

| Pool | Target Independent Groups |
| --- | --- |
| Consensus | 5 |
| Registry | 5 |
| Validation | 3 |

## 22. Diversity Example

Suppose:

`Consensus Pool = 1500Q`
`Eligible independent groups = 3`
`Target groups = 5`

Then:

`DiversityFactor = 3 / 5 = 0.60`

`Distributable Consensus Pool = 1500Q x 0.60 = 900Q`

The remaining `600Q` is not minted from Base Emission.

This prevents one or two early operators from collecting the full infrastructure subsidy merely because no one else has arrived yet.

## 23. Group Share Limit

Each pool SHALL define a maximum share payable to one Known Control Group.

The initial dynamic limit is:

`MaximumGroupShare = max(1 / IndependentGroupCount, MinimumGroupShareCap)`

Recommended minimum cap:

`MinimumGroupShareCap = 20%`

Examples:

| Independent Groups | Maximum Group Share |
| --- | --- |
| 1 | 100% |
| 2 | 50% |
| 3 | 33.33% |
| 5 | 20% |
| 10 | 20% |

The Diversity Factor still limits the total distributable pool when the number of groups is small.

## 24. Capped Proportional Distribution

Initial group shares are calculated proportionally:

`InitialGroupShare(g) = DistributablePool x GroupRawWeight(g) / Σ GroupRawWeight`

If a group exceeds the Maximum Group Share:

1. Its reward is capped.
2. The remaining amount is redistributed among uncapped groups.
3. Redistribution uses their remaining proportional weights.
4. The process repeats until no group exceeds the cap.
5. Any amount that cannot be distributed without violating caps remains unminted.

This calculation SHALL use a deterministic bounded iteration.

## 25. Distribution Within a Group

After a Known Control Group receives its final group allocation, the allocation is divided among its eligible Service instances:

`ParticipantReward(i) = GroupReward(g) x RawWeight(i) / GroupRawWeight(g)`

The group owner SHALL not choose the internal distribution manually.

## 26. Minimum Reward

The protocol MAY define a minimum reward amount to avoid economically meaningless dust.

Recommended initial value:

`MinimumReward = 0.01Q`

A calculated reward below the minimum:

- is not minted;
- is not reassigned to another participant;
- follows the pool's unused-budget handling.

## 27. Fixed-Point Arithmetic

All calculations SHALL use deterministic fixed-point integer arithmetic.

The protocol SHALL define:

- Q precision;
- factor precision;
- rounding direction;
- remainder handling.

The MVP SHOULD round participant rewards downward.

Rounding remainder remains unused.

## 28. Consensus Pool Purpose

The Consensus Pool rewards active Consensus Validators for maintaining:

- block ordering;
- block finality;
- BFT voting;
- proposer duties;
- canonical Ledger availability.

The Consensus Pool does not reward Stake ownership by itself.

Stake provides eligibility and security collateral.

## 29. Consensus Eligibility

A Consensus Service receives weight only when:

- it belonged to the active CometBFT Validator Set;
- required Consensus Stake remained locked;
- it was synchronized;
- it was not suspended;
- it met minimum voting participation;
- it used a compatible protocol version;
- no objective double-signing evidence exists.

Detailed Consensus eligibility and slashing rules belong to `ECO-0006`.

## 30. Consensus Work Units

Consensus Work Units SHALL not be proportional to unlimited Stake.

The initial model assigns:

`BaseConsensusWorkUnits = 1`

to each eligible active Consensus Service.

Quality factors then adjust the reward according to actual participation.

This avoids turning reward distribution into unrestricted wealth-weighted dominance.

## 31. Consensus Participation Factor

`VoteParticipation = ValidVotesSubmitted / ExpectedVotes`

Expected votes SHALL derive from finalized Consensus history.

The factor SHALL be capped:

`0 <= VoteParticipation <= 1`

A Validator below the minimum participation threshold is ineligible.

Recommended initial threshold:

`MinimumVoteParticipation = 0.80`

## 32. Consensus Availability Factor

Consensus Availability reflects whether the Validator remained:

- connected;
- synchronized;
- capable of voting;
- available during expected participation windows.

Availability SHALL be computed from consensus evidence rather than ordinary self-reported uptime.

## 33. Consensus Duty Factor

Consensus Duty includes:

- voting;
- proposer responsibility;
- valid proposal production;
- timely block participation;
- correct Validator Set behavior.

A missed proposer opportunity MAY reduce Duty Proof.

A Validator SHALL not receive an excessive reward merely because random proposer selection favored it.

## 34. Consensus Reliability Factor

Consensus Reliability MAY include:

- valid signature rate;
- malformed vote rate;
- synchronization failures;
- conflicting evidence;
- repeated recovery failures.

Objective equivocation or double-signing makes the Service ineligible and may trigger penalties under `ECO-0006`.

## 35. Consensus Raw Weight

The initial Consensus formula is:

`ConsensusRawWeight(i) = BaseConsensusWorkUnits x Maturity(i) x Availability(i) x VoteParticipation(i) x DutyProof(i) x SigningReliability(i)`

All factors are bounded between `0` and `1`.

## 36. Consensus Reward Neutrality

Consensus reward SHALL not depend on:

- Wallet balance beyond required Stake;
- number of Endpoints;
- number of hosted models;
- number of registered Hypervisors;
- arbitrary self-reported compute power.

Consensus rewards only consensus participation.

## 37. Registry Pool Purpose

The Registry Pool rewards full Registry Services for maintaining and serving protocol information.

Qualifying responsibilities include:

- Ledger history storage;
- Advertisement history;
- Validation Report storage;
- Epoch result storage;
- Snapshot storage and delivery;
- historical object retrieval;
- synchronization support;
- Proof of Registry responses.

Detailed Registry replication, completeness, challenge, and inventory rules are defined by `RFC-0061`.

## 38. Registry Eligibility

A Registry Service receives weight only when:

- it satisfies the required full Registry profile;
- required object ranges are synchronized;
- it passed mandatory Proof of Registry challenges;
- it remained reachable;
- it met minimum completeness;
- it was not suspended;
- required Registry collateral remained valid where configured.

Claimed storage without successful verification produces no weight.

The Full Registry profile, completeness rules, synchronization-lag handling, and challenge mechanics used to establish this evidence are defined by `RFC-0061`.

## 39. Registry Base Work Units

Every eligible full Registry receives:

`BaseRegistryWorkUnits = 1`

This represents the baseline cost of maintaining the complete required dataset.

Additional Work Units MAY be earned for protocol-assigned service duties.

## 40. Additional Registry Work Units

Additional verified contribution MAY include:

- serving Snapshot chunks to new nodes;
- serving protocol-assigned historical ranges;
- assisting State Sync;
- maintaining designated archival ranges;
- responding to additional randomized challenges.

Only protocol-assigned or independently verifiable service counts.

Self-generated download traffic SHALL not create Work Units.

Recommended initial cap:

`AdditionalRegistryWorkUnits <= 0.50`

Therefore:

`MaximumRegistryWorkUnits = 1.50`

This rewards additional service without allowing bandwidth volume to overwhelm the entire pool.

## 41. Registry Proof Success

`ProofSuccess = SuccessfulMandatoryChallenges / TotalMandatoryChallenges`

Invalid objects, invalid proofs and missing deadlines reduce the factor.

Recommended eligibility threshold:

`MinimumProofSuccess = 0.90`

## 42. Registry Completeness

Completeness represents whether the Registry stores the required object set.

`Completeness = VerifiedRequiredObjects / SampledRequiredObjects`

Completeness SHALL be established through challenge sampling and cryptographic commitments.

A Registry serving only popular recent objects SHALL not qualify as a full Registry.

Segment manifests, Inventory Roots, and completeness manifests are defined by `RFC-0061`.

## 43. Registry Availability

Availability reflects successful protocol requests during assigned observation windows.

The protocol SHALL avoid rewarding raw request volume.

Availability is based on:

- randomized requests;
- assigned retrieval duties;
- verified peer interactions;
- successful Snapshot serving.

## 44. Registry Latency

Latency MAY influence Health but SHALL be bounded.

Latency differences should not allow a centrally hosted Registry near most validators to capture the entire pool.

Recommended latency factor range:

`0.80 <= LatencyFactor <= 1.00`

provided the Registry remains within the maximum acceptable response deadline.

## 45. Registry Raw Weight

The initial Registry formula is:

`RegistryRawWeight(i) = RegistryWorkUnits(i) x Maturity(i) x Availability(i) x ProofSuccess(i) x Completeness(i) x LatencyFactor(i) x Reliability(i)`

All quality factors are bounded.

## 45A. Finalized Registry Reward Input

The Registry pool SHALL consume a fixed-point `Registry Reward Input` derived
from a consensus-finalized Registry Duty Evidence object defined by
`RFC-0061`.

The input SHALL include:

- Registry Service ID and reward beneficiary;
- Epoch and finalized operation ID;
- Registry Work Units;
- Maturity, Health, Availability, Proof Success, Completeness, Latency and
  Reliability factors;
- Known Control Group ID;
- Duty Evidence ID, evidence hash and eligibility decision hash.

The MVP uses `1,000,000` as the fixed-point scale.  A conforming calculator
MAY convert the resulting fixed-point raw weight into the pool's integer
distribution, but SHALL use deterministic integer rounding.

The Registry input is not a Q amount.  A Registry Service, peer, webhook or
local Ledger record SHALL NOT create `REWARD_MINT` directly.  Reward minting
requires the finalized epoch reward calculation, pool budget, caps, diversity
and Ledger authorization defined by this ECO.

If finality, mandatory Proof, Completeness, beneficiary binding or any
eligibility gate is missing, the Registry receives zero weight for the epoch.
The evidence MAY still be committed as an explicit ineligible verification
result for audit and later diagnosis.

## 45B. Registry Epoch Calculation Boundary

The Epoch Engine SHALL aggregate only finalized `Registry Reward Input`
objects for one exact Epoch and Registry pool budget.  The canonical MVP
calculation uses fixed-point integer arithmetic with scale `1,000,000`:

1. count distinct effective Known Control Groups;
2. calculate `DiversityFactor = min(1, GroupCount / TargetGroups)`;
3. derive the distributable pool using integer floor rounding;
4. aggregate raw weights by Known Control Group;
5. cap a group at `max(1 / GroupCount, MinimumGroupShareCap)`;
6. redistribute only among uncapped groups by remaining raw weight;
7. distribute each group allocation among its member Registry Services;
8. leave atoms that cannot be assigned without violating a cap unminted.

The calculation SHALL produce an immutable `Registry Reward Calculation`
containing the pool budget reference, diversity factor, group cap, per-service
allocations and all evidence/snapshot references.  Its
`REWARD_CALCULATION_ROOT` SHALL be the canonical hash of that object and SHALL
be independent of input ordering.

When an input has no Known Control Group, the MVP SHALL use its verified reward
beneficiary as the effective grouping key.  This fallback is conservative
against multiple Registry identities sharing one beneficiary; later identity
resolution MAY replace it only from a future Epoch boundary.

The calculation root and pool budget SHALL be committed by the consensus
finalized `EPOCH_TRANSITION`.  Only then may the Ledger accept an individual
`REWARD_MINT`.  Registry Services, peer replication, webhooks and local
calculation workers SHALL not mint Q directly.

The transition itself SHALL bind the closing and opening Epochs, all required
state/calculation roots and typed per-pool budgets.  The opening Epoch must be
the immediate successor of the closing Epoch, and a second transition for the
same closing Epoch is invalid.

In the MVP consensus executor, this dependency is evaluated against the
pre-block finalized operation set in both the ABCI and deterministic local
execution entrypoints.  A same-block `EPOCH_TRANSITION` plus `REWARD_MINT` is
rejected, and an accepted mint is applied only through the budget-checked
Ledger path.  Specialized Registry mint execution does not imply that every
other Ledger operation family is already fully consensus-wired.

## 46. Registry Location Neutrality

The Registry reward SHALL not directly depend on geographic claims.

Future protocols MAY reward proven failure-domain diversity.

Such incentives SHALL require verifiable topology evidence and separate rules.

IP address or declared location alone SHALL not increase reward.

## 47. Validation Pool Purpose

The Validation Activity Pool rewards useful completed Validation work.

It does not provide a passive reward for keeping Validation Service enabled.

A Validation Service producing no eligible report receives:

`Validation Weight = 0`
`Validation Reward = 0Q`

## 48. Validation Eligibility

A Validation Service receives weight only when:

- it was eligible when accepting the assignment;
- required Validation Stake remained locked;
- the assignment was valid;
- the report was submitted within the permitted window;
- the report passed protocol schema validation;
- required evidence exists;
- no report fabrication evidence exists.

## 49. Validation Report Work Units

Each assignment receives a Complexity Class before the Validator accepts it.

Initial Complexity Units are:

| Complexity Class | Work Units |
| --- | --- |
| Minimal | 0.50 |
| Standard | 1.00 |
| Advanced | 1.50 |
| Complex | 2.00 |
| Exceptional | 3.00 |

Complexity SHALL be assigned deterministically from:

- Capability;
- required number of requests;
- artifact size;
- expected execution time;
- required tools;
- evidence requirements;
- accounting checks.

The Validator SHALL not choose the Complexity Class.

## 50. Validation Outcome Neutrality

Report reward SHALL not depend on whether the conclusion is favorable.

The following may receive equal weight when report quality is equal:

- `CERTIFY`;
- `CERTIFY_WITH_OBSERVATIONS`;
- `DO_NOT_CERTIFY`.

A negative report is not less valuable merely because the Endpoint failed.

## 51. Report Quality Factor

The Report Quality Factor SHALL consider:

- schema completeness;
- evidence completeness;
- request description;
- response references;
- measurement clarity;
- issue specificity;
- consistency between evidence and conclusion;
- privacy compliance.

Recommended range:

`0 <= ReportQuality <= 1`

A report below the minimum quality threshold receives no reward.

Recommended threshold:

`MinimumReportQuality = 0.60`

## 52. Evidence Factor

Evidence Factor evaluates whether the report includes sufficient support for its observations.

Examples include:

- request hashes;
- response hashes;
- artifact references;
- timestamps;
- measurements;
- Usage Report references;
- protocol observations.

Unsupported subjective statements SHALL not produce a high Evidence Factor.

## 53. Deadline Factor

The initial Deadline Factor is:

`1.00`

when submitted before the assignment deadline.

A permitted grace period MAY use:

`0.75`

Reports submitted after the grace period are ineligible unless protocol failure caused the delay.

## 54. Inconclusive Report Factor

An Inconclusive Report MAY still provide useful evidence.

Its utility factor SHALL depend on why it was inconclusive.

Recommended values:

| Inconclusive Cause | Utility Factor |
| --- | --- |
| Endpoint consistently unavailable with evidence | 1.00 |
| External network failure with useful evidence | 0.75 |
| Insufficient evidence despite meaningful work | 0.50 |
| Validator lacked required tools | 0.25 |
| Empty or superficial report | 0.00 |

An unavailable Endpoint is a meaningful validation result and SHALL not be treated as an empty report.

## 55. Validator Reliability Factor

Validation is an activity reward, so new Validators SHALL not be reduced nearly to zero merely because they have little Maturity.

The initial bounded Reliability Factor is:

`ValidatorReliability = 0.80 + 0.20 x ValidationReliabilityScore`

Therefore:

`0.80 <= ValidatorReliability <= 1.00`

This allows newcomers to earn meaningful rewards while still favoring consistently reliable Validators slightly.

## 56. Validation Report Weight

For report `r`:

`ReportWeight(r) = ComplexityUnits(r) x ReportQuality(r) x EvidenceFactor(r) x DeadlineFactor(r) x ReportUtilityFactor(r)`

For Validator Service `i`:

`ValidationRawWeight(i) = Σ ReportWeight(r) x ValidatorReliability(i)`

Maturity SHALL not directly multiply Validation Report Work Units in the MVP.

## 57. Multiple Reports

A Validator may complete multiple assignments during one Epoch.

Each report:

- has a unique Assignment ID;
- has a unique Report ID;
- contributes independently;
- cannot be reused;
- must satisfy assignment limits.

The Validation Assignment Protocol MAY cap assignments per Validator.

## 58. Collaborative Validation

One report rewards one assigned Validator in the MVP.

Collaborative Validation is deferred.

Multiple Validators testing the same Endpoint SHALL produce independent reports unless a future assignment explicitly defines collaboration.

## 59. Report Fabrication

A report supported by fabricated or conflicting signed evidence receives:

`Weight = 0`

It may additionally cause:

- reward cancellation;
- participant suspension;
- Stake penalty;
- Reputation reduction.

Subjective disagreement over output quality alone is not fabrication.

## 60. Pool Allocation Examples

Consensus Example

Suppose:

`Nominal Consensus Pool = 1500Q`
`Independent Groups = 5`
`Diversity Factor = 1`

Eligible weights:

| Validator | Raw Weight |
| --- | --- |
| A | 0.90 |
| B | 0.85 |
| C | 0.80 |
| D | 0.70 |
| E | 0.60 |

Total:

`3.85`

Validator `A` receives:

`1500 x 0.90 / 3.85 ≈ 350.65Q`

The concentration cap is then applied if necessary.

## 61. Registry Example

Suppose:

`Registry Pool = 1500Q`
`Independent Groups = 10`

A high-quality Registry has:

`Work Units = 1.20`
`Maturity = 0.90`
`Availability = 0.98`
`Proof Success = 1.00`
`Completeness = 1.00`
`Latency Factor = 0.95`
`Reliability = 1.00`

Its Raw Weight is:

`1.20 x 0.90 x 0.98 x 1.00 x 1.00 x 0.95 ≈ 1.005`

Its final reward depends on the sum of all eligible Registry weights.

## 62. Validation Example

A Validator completes:

`One Standard report:`
`1.00 Work Unit`

`One Complex report:`
`2.00 Work Units`

Adjusted report weights:

`Standard:`
`1.00 x 0.90 quality x 1.00 evidence x 1.00 deadline = 0.90`

`Complex:`
`2.00 x 0.80 quality x 0.90 evidence x 1.00 deadline = 1.44`

With Validator Reliability `0.95`:

`Validation Raw Weight = (0.90 + 1.44) x 0.95 = 2.223`

The Validator receives the corresponding proportional share of the Validation Pool.

## 63. Empty Pool

If no participant is eligible for a Service Pool:

`Actual Pool Mint = 0Q`

The Base Emission allocation expires.

The recyclable portion returns to Recycle Backlog.

The pool SHALL not be reassigned to another Service type during the same Epoch.

## 64. Partially Distributed Pool

If concentration limits, minimum rewards or insufficient evidence prevent full distribution:

- only final calculated rewards are minted;
- unused Base Emission authorization expires;
- unused recyclable authorization returns to Recycle Backlog.

## 65. Reward Finalization Delay

Work performed in Epoch `t` SHALL normally be paid after Epoch `t + 1` closes.

The delay permits:

- evidence verification;
- challenge processing;
- conflicting-report detection;
- suspension processing;
- deterministic reward calculation.

## 66. Reward Calculation Commitment

The Epoch Engine SHALL produce a Reward Calculation Root containing:

- pool budgets;
- eligible participants;
- Known Control Groups;
- Raw Weights;
- Diversity Factors;
- concentration caps;
- final rewards;
- unused amounts;
- formula versions;
- evidence references.

The root SHALL be committed through the Epoch transition process.

## 67. Reward Mint Operations

Each final reward produces a protocol-generated:

`REWARD_MINT`

operation under `RFC-0059`.

Every Mint Operation SHALL reference:

- reward Epoch;
- pool;
- recipient;
- amount;
- evidence root;
- calculation version;
- pool authorization.

Participants SHALL not construct their own Reward Mint Operations.

## 68. Reward Challenges

Before Reward Mint finalization, a participant MAY challenge an objective calculation error.

Valid challenge grounds include:

- omitted finalized evidence;
- duplicated evidence;
- incorrect eligibility state;
- incorrect Known Control Group aggregation;
- arithmetic error;
- wrong formula version;
- reward exceeding pool authorization.

Subjective dissatisfaction with the relative reward is not sufficient.

## 69. No Retroactive Recalculation

After Reward Mint finalization:

- later evidence does not alter the reward;
- later Reputation changes do not rewrite history;
- formula upgrades affect future Epochs only.

Confirmed fraud MAY trigger a separate Penalty Operation.

It SHALL not silently modify an already finalized reward record.

## 70. Anti-Gaming Rules

The reward system SHALL reject or discount:

- duplicate proofs;
- self-generated Registry traffic;
- repeated evidence reuse;
- artificial assignment splitting;
- artificial Service splitting;
- self-dealing presented as independent contribution;
- malformed low-information Validation Reports;
- Consensus identities created only to multiply weight;
- unverified contribution claims.

## 71. Service Splitting

Splitting one physical or logical Service into multiple identities SHALL not create additional qualifying work.

Examples:

- one Registry dataset exposed through ten Service identities;
- one Consensus key represented by multiple Service records;
- one Validation Report submitted through several Validators.

Each identity must independently satisfy:

- eligibility;
- Duty Proof;
- contribution requirements;
- collateral requirements where applicable.

## 72. Pool-Specific Independence

Known Control Group limits apply separately to each pool.

A group receiving `20%` of the Registry Pool MAY also receive Consensus rewards when it independently operates eligible Consensus Services.

Each function represents different work.

Cross-pool earnings SHALL remain transparent in Ledger metrics.

## 73. Reward Transparency

The network SHALL expose:

- pool budgets;
- eligible participant count;
- independent group count;
- participant Raw Weights;
- group caps;
- Diversity Factors;
- final rewards;
- unused Base authorization;
- returned Recycle Backlog;
- formula versions.

Private Session data SHALL not be required for reward verification.

## 74. Monitoring Metrics

The network SHOULD publish:

- average reward per Service;
- median reward per Service;
- reward concentration;
- top-group pool share;
- number of eligible participants;
- number of independent groups;
- unused pool percentage;
- Maturity distribution;
- Health distribution;
- Validation reward per report class;
- Registry proof success distribution;
- Consensus participation distribution.

## 75. Parameter Configuration

The following are versioned protocol parameters:

- minimum Service Health;
- Maturity function;
- Maturity interruption rules;
- target independent group counts;
- minimum group-share cap;
- minimum reward;
- Consensus participation threshold;
- Registry proof threshold;
- Registry additional Work Unit cap;
- Registry latency range;
- Validation complexity classes;
- minimum Report Quality;
- deadline factors;
- Inconclusive Report factors;
- Validator Reliability range;
- challenge window;
- reward delay.

## 76. Parameter Changes

Reward parameters SHALL change only through:

- a versioned protocol upgrade;
- a declared activation Epoch;
- deterministic migration rules.

A new formula SHALL not recalculate previous rewards.

## 77. Relationship to Penalties

This document determines positive rewards.

It does not define:

- slashing amounts;
- Validation Stake penalties;
- Consensus penalties;
- Registry Bond forfeiture.

Penalties are defined by the relevant economic and protocol documents.

A participant may receive zero reward without being penalized.

## 78. MVP Requirements

The MVP SHALL implement:

- fixed Service Pools;
- Service-specific eligibility gates;
- Work Units;
- Maturity;
- Health;
- Duty Proof;
- Known Control Group aggregation;
- Diversity Factors;
- capped proportional distribution;
- Consensus reward formula;
- Registry reward formula;
- Validation report weighting;
- minimum reward handling;
- reward calculation commitments;
- protocol-generated Reward Mint Operations;
- unused pool handling;
- deterministic fixed-point arithmetic;
- reward transparency metrics.

## 79. Deferred Features

The MVP MAY postpone:

- geographic diversity rewards;
- hardware diversity rewards;
- bandwidth auctions;
- proof-of-useful-storage pricing;
- collaborative Validation rewards;
- market-based reward-pool reallocation;
- automatic pool-percentage adjustment;
- external identity-based group aggregation;
- zero-knowledge ownership proofs;
- dynamic Capability-specific Validation pricing.

## 80. Economic Invariants

The following SHALL always hold:

`Total Rewards per Pool <= Distributable Pool Budget`

`Distributable Pool Budget <= Nominal Pool Budget`

`Participant Reward >= 0`

`Identity Count Alone Does Not Create Weight`

`Duplicate Evidence Does Not Create Additional Reward`

`Unused Base Authorization Is Not Minted`

`Unused Recyclable Authorization Returns to Recycle Backlog`

## 81. Design Invariants

- The Epoch Reward Budget is defined before individual rewards.
- Participants divide fixed pools according to proven contribution.
- More participants do not increase total emission.
- Service activation alone earns nothing.
- Consensus rewards active consensus participation.
- Registry rewards verified storage and service availability.
- Validation rewards completed useful reports.
- Validation outcome does not determine reward direction.
- Known common ownership is aggregated.
- Insufficient participant diversity reduces distributable rewards.
- Concentration caps limit one known group's pool share.
- All calculations are deterministic and auditable.
- Protocol Rewards are minted only through authorized Reward Mint Operations.
- Faucet distribution remains governed by `ECO-0005`.
