# ECO-0006 Consensus Economics and Validator Eligibility

Status: `Draft`

Version: `0.1`

Depends on:

- `ECO-0000 Economic Principles`
- `ECO-0004 Protocol Service Reward Distribution`
- `ECO-0005 Q Emission, Recycling and Epoch Reward Allocation`
- `RFC-0036 AiDN Ledger State Machine`
- `RFC-0040 Service Verification Framework`
- `RFC-0041 Reputation Profile Engine`
- `RFC-0047 CometBFT Consensus Integration`
- `RFC-0048 Epoch Engine`
- `RFC-0058 Participant Eligibility and Sybil Resistance`
- `RFC-0059 Ledger Operation Catalog`

## 1. Purpose

This document defines the economic and eligibility rules governing AiDN Consensus Validators.

It specifies:

- Consensus Validator candidacy;
- activation requirements;
- Consensus Stake;
- Active Validator Set construction;
- voting power;
- validator rotation;
- reward eligibility;
- downtime handling;
- unbonding;
- suspension;
- objective misconduct;
- Stake slashing;
- recovery and re-entry.

CometBFT provides consensus execution.

AiDN determines which Consensus Services may participate and what economic consequences follow from their behavior.

## 2. Consensus Validator Definition

A Consensus Validator is an eligible Consensus Service included in the active CometBFT Validator Set.

A Consensus Validator participates in:

- block proposal;
- prevote;
- precommit;
- block finalization;
- consensus evidence handling;
- Validator Set transitions.

A registered Consensus Service that is not included in the Active Validator Set is a Consensus Candidate.

Consensus Candidates do not vote and do not receive Consensus Pool rewards.

## 3. Separation from Endpoint Validation

Consensus Validators and Endpoint Validators are different protocol roles.

A Consensus Validator:

- signs blocks;
- maintains Ledger finality;
- participates in CometBFT.

An Endpoint Validator:

- tests Endpoints;
- produces Validation Reports;
- participates in the Validation Activity Pool.

One Hypervisor MAY operate both Services.

Eligibility for one role does not automatically grant eligibility for the other.

## 4. Design Principles

Consensus economics SHALL follow these principles:

- Stake provides collateral, not unlimited authority.
- Wealth alone SHALL NOT determine voting power.
- Identity count alone SHALL NOT determine voting power.
- Consensus rewards compensate proven participation.
- Ordinary downtime reduces rewards before it causes economic penalties.
- Objective cryptographic misconduct may cause severe slashing.
- Validator Set changes occur deterministically.
- Known Control Groups SHALL have bounded consensus influence.
- Consensus safety takes priority over continuous availability.

## 5. Consensus States

A Consensus Service follows this lifecycle:

```text
UNREGISTERED
    ↓
REGISTERED
    ↓
SYNCING
    ↓
CANDIDATE
    ↓
ACTIVE
    ↓
EXITING
    ↓
UNBONDING
    ↓
RETIRED
```

Failure-related states include:

- `DEGRADED`
- `SUSPENDED`
- `SLASHED`
- `BANNED`

## 6. Consensus Service Registration

A Hypervisor registers a Consensus Service through:

`SERVICE_REGISTER`

The registration SHALL include:

- Service Identity;
- owner Wallet;
- Reward Beneficiary Wallet;
- consensus public key;
- protocol version;
- CometBFT version compatibility;
- network endpoints;
- configuration hash.

Registration alone does not permit consensus participation.

## 7. Consensus Candidate Eligibility

A Consensus Service becomes a Candidate only when it satisfies all of the following:

- valid Service Identity;
- valid owner Wallet;
- valid consensus key;
- compatible protocol version;
- complete Ledger synchronization;
- verified application state hash;
- required Consensus Stake locked;
- minimum activation age completed;
- minimum Consensus Reputation satisfied;
- minimum operational Health satisfied;
- successful Consensus Service Verification;
- no active suspension or unbonding;
- valid network reachability.

## 8. Initial Eligibility Parameters

Recommended initial Candidate requirements:

`Minimum activation age:`
`10 qualifying Epochs`

`Minimum Consensus Reputation:`
`0.90`

`Minimum Health:`
`0.90`

`Minimum synchronization status:`
`fully synchronized`

`Required Consensus Stake:`
`500Q`

These values are protocol parameters.

They are intentionally conservative placeholders for testnet and early network operation.

## 9. Genesis Validators

Genesis Validators MAY be activated without completing the ordinary activation age.

Genesis exceptions SHALL be declared in the Genesis document.

Genesis Validators SHALL still provide:

- valid consensus keys;
- required initial Stake or explicit Genesis exemption;
- compatible software;
- valid state commitments.

Genesis exceptions SHALL not automatically apply to later Validators.

## 10. Consensus Stake

Every Consensus Candidate SHALL lock a Consensus Stake.

Initial recommended amount:

`ConsensusStake = 500Q`

Stake SHALL be locked per Consensus Service.

Stake:

- remains owned by the staking Wallet;
- cannot be spent while locked;
- does not independently generate rewards;
- does not automatically determine voting power;
- may be reduced only by defined protocol penalties.

## 11. Stake Purpose

Consensus Stake provides:

- economic cost for creating many Candidate identities;
- collateral against objective misconduct;
- commitment during the unbonding period;
- limited protection against rapid identity cycling.

Stake is not payment for a Validator slot.

Locking Stake does not guarantee selection.

## 12. Stake Ownership

The Wallet locking Stake SHALL be visible in Ledger state.

A Stake MAY secure only one Consensus Service unless pooled Stake is explicitly introduced by a future protocol version.

The same Q SHALL NOT secure:

- multiple Consensus Services;
- a Consensus Service and unrelated Validation Service;
- multiple overlapping protocol obligations.

## 13. Stake and Voting Power

Voting power SHALL NOT increase linearly with Stake.

The MVP uses:

`one Active Consensus Validator = one equal voting-power unit`

Stake above the minimum does not increase voting power.

This prevents large Q holders from directly purchasing control over consensus.

## 14. Active Validator Set

The Active Validator Set is the set of Consensus Services authorized to participate in CometBFT during an Epoch.

Recommended initial target:

`TargetValidatorSetSize = 21`

The target is a maximum desired size, not a promise that 21 eligible independent Validators always exist.

## 15. Minimum Operational Set

Recommended protocol minimum:

`MinimumOperationalValidators = 4`

If fewer than four independent eligible Validators exist, the network enters:

`CONSENSUS_BOOTSTRAP_RISK`

or:

`CONSENSUS_DEGRADED`

depending on network stage.

The network MAY technically continue if consensus remains possible, but SHALL prominently report reduced Byzantine fault tolerance.

## 16. Byzantine Safety Threshold

Consensus finality requires more than two-thirds of active voting power.

Therefore:

- less than one-third Byzantine voting power cannot finalize conflicting state;
- more than one-third unavailable or non-participating power may halt consensus;
- more than two-thirds malicious power can control finalization.

AiDN SHALL not attempt to weaken these safety assumptions to preserve superficial availability.

## 17. Equal Voting Power

Every Active Validator receives the same configured voting power.

Conceptually:

`VotingPower(i) = 1`

CometBFT implementation MAY use another equal integer value where required.

All active Validators SHALL receive the same amount.

Governance use of the Active Validator Set MAY reuse the same frozen set snapshot for Consensus Chamber eligibility.

Such governance votes are not Consensus votes, do not finalize blocks by themselves, and do not alter CometBFT finality rules.

## 18. Known Control Group Limit

The MVP SHOULD allow no more than:

`one Active Consensus Validator`
`per Known Control Group`

A Known Control Group is defined by `RFC-0058`.

Multiple Consensus Services belonging to one known group MAY remain Candidates or standby nodes.

Only one receives an active voting slot.

## 19. Bootstrap Control Group Exception

During early network bootstrap, insufficient independent operators may make the one-slot rule impractical.

A temporary bootstrap configuration MAY permit:

`maximum two Active Validators`
`per Known Control Group`

Only when:

- the exception is declared in Genesis or protocol configuration;
- aggregate group voting power remains below the configured cap;
- the network has not yet reached the target independent-group count;
- the exception expires automatically.

Recommended bootstrap group voting-power cap:

`20%`

## 20. Candidate Pool

All eligible Consensus Candidates form the Candidate Pool.

Candidate Pool membership does not guarantee:

- active selection;
- Consensus rewards;
- proposer duties;
- voting rights.

Candidates SHALL remain synchronized and maintain their eligibility if they wish to participate in future rotation.

## 21. Validator Selection

Validator selection occurs at an Epoch boundary through a deterministic Epoch Task.

The selection procedure SHALL use:

- finalized Candidate eligibility;
- Known Control Groups;
- current Active Validator Set;
- required rotation fraction;
- Consensus Reputation;
- Service Maturity;
- deterministic Epoch randomness.

No centralized operator chooses Validators.

## 22. Epoch Randomness

Validator selection SHALL use a deterministic seed derived from finalized consensus data.

Example:

`EpochSelectionSeed = HASH(previous_epoch_final_block_hash + previous_epoch_state_root + opening_epoch_number)`

Every honest node SHALL derive the same seed.

A single participant SHALL not be able to choose the seed after seeing the Candidate Pool.

## 23. Candidate Selection Weight

Candidate selection probability MAY consider:

`SelectionWeight = Eligibility x MaturitySelectionFactor x ReputationSelectionFactor x AvailabilitySelectionFactor`

All factors SHALL be bounded.

Stake above the minimum SHALL not affect Selection Weight.

## 24. Selection Factor Bounds

To prevent old Validators from becoming permanent, Maturity and Reputation SHALL have limited influence over selection.

Recommended ranges:

`0.80 <= MaturitySelectionFactor <= 1.00`

`0.80 <= ReputationSelectionFactor <= 1.00`

New eligible Validators therefore retain a meaningful chance of selection.

## 25. Validator Rotation

The Active Validator Set SHOULD rotate gradually rather than being completely replaced every Epoch.

Recommended initial parameter:

`RotationFraction = 1/3`

At each Epoch boundary:

- approximately two-thirds of eligible active Validators MAY remain;
- approximately one-third of slots become open;
- suspended, exiting or ineligible Validators are removed first;
- open slots are filled from the Candidate Pool.

## 26. Retention Selection

Incumbent Validators are retained according to:

- continued eligibility;
- participation rate;
- Consensus Reputation;
- absence of suspension;
- deterministic retention ranking.

No incumbent has a permanent seat.

A Validator MAY be rotated out despite satisfactory behavior.

Rotation out is not a penalty.

## 27. New Candidate Selection

Open slots SHALL be filled through deterministic weighted selection among eligible Candidates not already active.

Selection SHALL enforce:

- Known Control Group limits;
- target set size;
- protocol compatibility;
- independent-group diversity;
- no duplicate consensus keys.

## 28. Active Set Smaller Than Target

If fewer eligible independent Candidates exist than the target set size:

- all eligible Candidates MAY be selected;
- remaining slots stay empty;
- voting power is recalculated over the actual Active Set;
- Diversity warnings are published;
- rewards remain limited by `ECO-0004`.

The protocol SHALL not create synthetic Validators to fill empty slots. Tempting as imaginary infrastructure may be, it remains stubbornly unavailable during outages.

## 29. Active Validator Duties

An Active Validator SHALL:

- remain synchronized;
- participate in prevote and precommit rounds;
- validate proposals;
- propose blocks when selected;
- maintain the AiDN application connection;
- report correct application state;
- retain consensus evidence;
- protect its consensus private key;
- follow Validator Set updates.

## 30. Consensus Participation

For Validator `i`:

`ParticipationRate(i) = ValidExpectedVotesSubmitted / ExpectedVotes`

Expected votes derive from finalized CometBFT consensus history.

Duplicate, malformed or late-invalid votes do not count as successful participation.

## 31. Minimum Participation

Recommended minimum reward eligibility:

`MinimumParticipationForReward = 0.80`

A Validator below this value receives no Consensus Pool reward for the Epoch.

Recommended minimum retention eligibility:

`MinimumParticipationForRetention = 0.67`

A Validator below the retention threshold MAY be removed at the next Epoch boundary.

## 32. Downtime Classification

Consensus downtime is classified as:

- `MINOR_DOWNTIME`
- `MAJOR_DOWNTIME`
- `PERSISTENT_DOWNTIME`
- `CONSENSUS_ABANDONMENT`

Recommended initial ranges:

| Classification | Participation |
| --- | --- |
| Normal | >= 90% |
| Minor Downtime | 80–90% |
| Major Downtime | 67–80% |
| Persistent Downtime | below 67% for repeated Epochs |
| Abandonment | near-zero participation without exit |

## 33. Ordinary Downtime Consequences

Ordinary downtime SHALL primarily cause:

- reduced Consensus reward;
- no reward below the threshold;
- reduced Health;
- reduced Consensus Reputation;
- removal from the Active Set;
- temporary suspension after repeated failures.

Ordinary downtime SHALL NOT normally slash Stake.

This avoids turning hardware failure, ISP trouble or a regrettably timed kernel update into immediate confiscation.

## 34. Persistent Downtime

Recommended initial rule:

`Participation below 67%`
`for three consecutive Active Epochs`

causes:

- removal from the Active Validator Set;
- temporary Consensus suspension;
- Maturity pause or reduction;
- mandatory re-verification before re-entry.

Recommended suspension:

`7 Epochs`

The repository implementation evaluates this policy with integer basis points
and stores the suspension boundary as canonical participant state. A
`PARTICIPANT_SUSPEND` operation requires finalized prior evidence; a
same-block evidence shortcut is rejected. Reinstatement requires a separate
finalized recovery evidence operation and the minimum recovery Epoch.

## 35. Consensus Abandonment

A Validator that stops participating without submitting an exit request may be classified as abandoned.

Abandonment MAY cause:

- immediate removal when protocol evidence permits;
- no reward;
- extended reactivation delay;
- reduced Consensus Reputation.

Stake remains locked until ordinary or extended unbonding completes.

Abandonment alone does not automatically justify slashing.

## 36. Block Proposal Duties

A Validator selected as proposer SHALL:

- construct a proposal compatible with AiDN state-machine rules;
- avoid invalid or duplicate operations;
- respect block limits;
- include mandatory protocol operations where required.

A failed proposer duty reduces Duty Proof.

## 37. Invalid Proposal

An invalid proposal MAY result from:

- software defect;
- stale state;
- incompatible protocol version;
- deliberate malformed construction.

One invalid proposal SHALL generally reduce:

- reward;
- Reliability;
- Health.

Repeated deliberate invalid proposals MAY cause suspension.

Invalid proposal alone does not necessarily justify Stake slashing unless objective malicious evidence exists.

## 38. Application State Divergence

A Validator producing an application state hash inconsistent with finalized honest state SHALL:

- stop consensus participation;
- enter `SUSPENDED`;
- recover from a verified Snapshot;
- pass synchronization verification before returning.

State divergence caused by incompatible software is treated as a severe operational failure.

It is not automatically malicious.

## 39. Reward Eligibility

Consensus rewards are distributed through the Consensus Pool defined by `ECO-0005` and `ECO-0004`.

An Active Validator earns Consensus reward only when:

- it remained eligible;
- Participation met the reward threshold;
- no objective misconduct occurred;
- required Duty Proof exists;
- Service Health remained above the minimum;
- reward evidence was finalized.

## 40. Consensus Reward Formula

`ECO-0004` defines:

`ConsensusRawWeight = BaseWorkUnits x Maturity x Availability x VoteParticipation x DutyProof x SigningReliability`

Consensus Stake amount above the minimum SHALL not increase the reward.

Reward depends on participation, not wealth.

## 41. No Candidate Reward

Consensus Candidates not included in the Active Validator Set receive no Consensus Pool reward merely for remaining synchronized.

The protocol MAY later introduce a small standby reward through a separately defined pool.

No standby reward exists in the MVP.

## 42. Proposer Reward Neutrality

The MVP SHALL not grant a large independent proposer bonus.

Proposer opportunities are not evenly distributed during short intervals.

Proposal performance MAY influence Duty Proof, but the Consensus Pool remains primarily based on overall participation.

This avoids turning random proposer selection into a daily lottery layered inside another daily lottery.

## 43. Voluntary Exit

An Active Validator MAY request voluntary exit through:

`UNSTAKE_REQUEST`

or a role-specific exit operation referencing its Consensus Service.

The exit becomes effective at a future Epoch boundary.

The Validator SHALL continue participating until removed from the Active Set unless the protocol authorizes earlier exit.

## 44. Exit Delay

Recommended initial exit activation delay:

`1 Epoch`

This allows the network to:

- select a replacement;
- update the Validator Set;
- avoid sudden voting-power loss;
- finalize pending evidence.

## 45. Unbonding Period

After leaving the Active Validator Set, Stake enters `UNBONDING`.

Recommended initial period:

`UnbondingPeriod = 14 Epochs`

The typed consensus Ledger path now implements the corresponding
`STAKE_LOCK -> UNSTAKE_REQUEST -> STAKE_RELEASE` lifecycle. Available Wallet
Q is debited at lock, the exact release Epoch is persisted at unbonding, and
release before that boundary is rejected. Ordinary downtime never authorizes
`PENALTY_APPLY` by itself.

During unbonding:

- Stake remains locked;
- historical misconduct evidence may still cause slashing;
- the Service cannot immediately re-register using the same Stake;
- no Consensus reward is earned.

## 46. Unbonding Completion

After the period completes, `STAKE_RELEASE` returns the remaining Stake when:

- no unresolved misconduct evidence exists;
- no active penalty applies;
- the Service has completed its exit obligations.

Released Q returns to the staking Wallet.

No new Q is minted.

## 47. Exit During Suspension

A suspended Validator MAY request exit.

Suspension does not bypass:

- evidence review;
- Stake slashing;
- unbonding;
- outstanding protocol obligations.

A Validator SHALL not avoid penalties by retiring immediately after misconduct.

## 48. Objective Misconduct

Consensus Stake may be slashed only for objective protocol violations.

Initial slashable violations include:

- double-signing conflicting blocks;
- signing conflicting votes at the same height and round;
- cryptographically provable consensus equivocation;
- deliberate use of conflicting consensus keys;
- forged consensus evidence;
- attempting to apply an unauthorized Validator Set update;
- provable manipulation of finalized consensus evidence.

## 49. Double-Signing

Double-signing is a critical violation.

Valid evidence SHALL include conflicting signed consensus messages from the same consensus key for the same height and round where only one is permitted.

On confirmed double-signing:

- the Validator is immediately suspended;
- it is removed from the Active Validator Set;
- Consensus reward for the affected Epoch is forfeited;
- Stake is slashed;
- the consensus key is permanently banned.

## 50. Double-Signing Slash

Recommended initial penalty:

`100% of Consensus Stake`

The removed `Q` becomes recyclable according to `ECO-0005` unless the active protocol version defines permanent burn.

The reporter does not receive the slashed amount directly.

This avoids creating a market for manufacturing profitable accusations.

## 51. Validator Key Ban

A consensus key proven to have double-signed SHALL never be reused.

The owner Wallet or Known Control Group MAY be subject to:

- extended reactivation delay;
- reduced Consensus Reputation;
- temporary Consensus-role ban;
- additional verification requirements.

Permanent exclusion of the Wallet requires broader protocol rules and SHALL not be inferred automatically from one key.

## 52. Other Slashable Misconduct

Recommended initial penalties:

| Misconduct | Stake Slash |
| --- | --- |
| Confirmed double-signing | 100% |
| Forged consensus evidence | 100% |
| Unauthorized Validator Set manipulation | 100% |
| Repeated deliberate conflicting application commitments | 50–100% |
| Objective protocol-key misuse | 25–100% |

The exact percentage SHALL be deterministic and linked to a defined evidence class.

## 53. Non-Slashable Failures

The following SHALL normally not cause Stake slashing:

- ordinary downtime;
- missed votes;
- ISP outage;
- hardware failure;
- operating-system crash;
- accidental restart;
- temporary clock issue;
- failed proposal;
- State Sync failure;
- software incompatibility without conflicting signatures.

These failures may still cause reward loss, Reputation reduction and removal.

## 54. Misconduct Evidence

Slashable evidence SHALL be:

- cryptographically verifiable;
- bound to the consensus key;
- committed to finalized Ledger state;
- replay-protected;
- independently reproducible.

Subjective claims or ordinary timeout observations SHALL not authorize slashing.

## 55. Evidence Submission

Consensus misconduct evidence MAY originate from:

- CometBFT evidence handling;
- another Consensus Validator;
- a synchronized observing node;
- the AiDN application adapter.

Submission does not determine guilt.

The State Machine verifies evidence deterministically.

## 56. Penalty Application

Confirmed penalties use:

`PENALTY_APPLY`

under `RFC-0059`.

The operation SHALL specify:

- target Stake;
- misconduct type;
- evidence root;
- finalized evidence operation ID;
- slash amount;
- recyclable or permanent classification;
- effective Epoch.

The current consensus execution boundary requires the evidence operation to
be finalized before `PENALTY_APPLY` enters a block. Same-block evidence and
penalty application is rejected. `wallet:<wallet-id>` targets debit available
Q; `lock:<stake-id>` targets reduce the canonical Stake without double-debiting
the owner Wallet, and a full slash marks the Stake unreleasable. Ordinary
downtime, missed votes and availability failures do not enter this penalty
path; they are handled by the deterministic participation and suspension
policy.

## 57. Reward Forfeiture

A Validator confirmed to have committed critical misconduct forfeits its Consensus reward for the affected Epoch.

If Reward Mint has not finalized:

- the reward is omitted.

If Reward Mint already finalized:

- a separate Penalty Operation MAY remove up to the applicable reward amount under a defined rule.

Finalized history SHALL not be silently rewritten.

## 58. Consensus Suspension

A Consensus Service MAY be suspended for:

- Persistent Downtime;
- State divergence;
- invalid protocol version;
- Stake deficiency;
- repeated malformed votes;
- security compromise;
- objective misconduct;
- failed Consensus Service Verification.

Suspension scope applies to Consensus participation.

Other Hypervisor functions MAY remain active.

## 59. Suspension Duration

Recommended initial suspension periods:

| Cause | Minimum Suspension |
| --- | --- |
| Persistent Downtime | 7 Epochs |
| State divergence | until recovery plus 2 Epochs |
| Invalid protocol version | until upgrade plus 1 Epoch |
| Stake deficiency | until restored plus 1 Epoch |
| Key compromise without double-signing | 14 Epochs |
| Confirmed double-signing | permanent key ban |

## 60. Reinstatement

A suspended Consensus Service may return to Candidate status after:

- suspension duration completed;
- required Stake remains or is restored;
- full synchronization completed;
- application state hash verified;
- consensus key is valid;
- re-verification succeeds;
- minimum Health and Reputation are restored.

Reinstatement does not guarantee immediate Active Set selection.

## 61. Stake Deficiency

A Stake may fall below the required amount due to slashing or protocol parameter changes.

A deficient Service:

- becomes ineligible;
- is removed from the Active Set;
- receives no Consensus reward;
- may top up Stake through `STAKE_LOCK`.

A protocol increase in required Stake SHALL provide a declared transition period.

## 62. Consensus Key Rotation

Consensus key rotation SHALL require:

- owner Wallet authorization;
- current Service Identity authorization;
- proof of possession of the new key;
- no unresolved misconduct evidence;
- activation at an Epoch boundary.

The old key remains slashable for conduct committed before rotation.

## 63. Emergency Key Rotation

If the current consensus key is believed compromised, the operator MAY request emergency rotation.

Until rotation finalizes:

- the Consensus Service may be suspended;
- it SHALL not continue signing with both keys;
- the new key receives no authority before activation.

Emergency rotation cannot erase evidence signed by the old key.

## 64. Validator Set Update

At each Epoch boundary, the protocol generates:

`CONSENSUS_VALIDATOR_SET_UPDATE`

The operation contains:

- additions;
- removals;
- voting-power assignments;
- activation Epoch;
- eligibility evidence root;
- Candidate selection seed;
- resulting Validator Set hash.

The repository MVP implements the typed protocol schedule boundary in both
consensus execution entrypoints. It validates protocol origin,
activation-Epoch binding, membership entry shape, positive Stake/voting power,
valid Ed25519 consensus keys, non-overlapping identities, evidence-root
presence and one update per activation Epoch. After the schedule is finalized,
the matching `EPOCH_TRANSITION` applies it to the canonical active set and
returns CometBFT validator updates; removals are represented by zero power.
The active set is included in state snapshots and application commitments.
The deterministic MVP `ValidatorScheduleBuilder` now consumes a finalized
Eligibility snapshot plus immutable consensus metadata, ranks candidates from
the committed selection seed, retains the configured incumbent fraction,
enforces the per-Known-Control-Group slot cap, rejects duplicate consensus keys
and emits equal voting power for each selected member. The builder computes the
evidence root over the complete snapshot and metadata set, requires the
snapshot to be the immediately preceding Epoch, and binds that root into the
typed schedule operation. It also commits a canonical participant-suspension
root and excludes a participant whose suspension is effective at the target
activation Epoch. Ledger admission independently reconstructs and checks the
final Validator Set hash before recording the schedule.

The duty-policy adapter also translates a removing `ValidatorDutyDecision` into
an evidence-bound `PARTICIPANT_SUSPEND` envelope. The adapter is pure: it does
not mutate Ledger state, authorize slashing or bypass the requirement that the
referenced duty-evidence operation was finalized in an earlier block.

## 65. Validator Set Finality

A Validator Set update becomes active only after Ledger finalization and CometBFT application according to `RFC-0047`.

Local configuration changes SHALL not independently alter voting power.

## 66. Insufficient Online Voting Power

If online voting power falls below the threshold needed for finalization:

- consensus halts;
- no conflicting minority chain SHALL be finalized;
- Session execution may continue only within existing finalized authorization;
- new Ledger state transitions remain pending;
- operators are notified of the halt.

Safety SHALL not be sacrificed by reducing the threshold dynamically.

## 67. Emergency Validator Replacement

Ordinary replacement requires Epoch rotation.

A future emergency protocol MAY replace clearly unavailable Validators after a prolonged halt.

Such a mechanism SHALL require:

- deterministic evidence;
- strong activation thresholds;
- delayed activation where possible;
- complete public audit history.

The MVP SHALL not permit one administrator to rewrite the Active Validator Set.

## 68. Network Partition

During a partition:

- a partition with insufficient voting power cannot finalize blocks;
- Validators SHALL not sign conflicting histories;
- double-signing across partitions remains slashable;
- after network recovery, Validators synchronize to the finalized canonical history.

## 69. Reward During Consensus Halt

Consensus reward during a halt SHALL depend on objective participation evidence.

Validators that remained available and correctly signed all possible rounds MAY receive partial reward.

No reward SHALL be paid for fabricated participation during a period with no finalized evidence.

A detailed halt-reward factor MAY be introduced later.

The MVP MAY set the affected Epoch reward conservatively to zero when evidence is insufficient.

## 70. Consensus Diversity

The protocol SHOULD monitor:

- independent Known Control Groups;
- hosting-provider concentration;
- autonomous-system concentration;
- geographic concentration;
- software-version concentration;
- correlated downtime.

Only Known Control Group relationships directly affect MVP selection rules.

Other diversity signals remain informational until reliable verification exists.

## 71. Hosting Concentration

Multiple Validators hosted by the same infrastructure provider may share a failure domain.

The Marketplace or explorer SHOULD display known hosting concentration.

Hosting-provider identity SHALL not alone prove common ownership or justify slashing.

Future versions MAY introduce bounded diversity incentives.

## 72. Software Diversity

Running identical Validator software versions creates correlated risk.

The protocol SHOULD report software-version concentration.

Validators SHALL still use protocol-compatible implementations.

Software diversity SHALL not excuse inconsistent state execution.

## 73. Consensus Reputation Profile

The Consensus Reputation Profile MAY include:

- vote participation;
- proposal correctness;
- signing reliability;
- synchronization reliability;
- active-set history;
- suspension history;
- recovery success;
- State Sync correctness;
- confirmed misconduct;
- key-rotation history.

Consensus Reputation is separate from:

- Endpoint Reputation;
- Registry Reputation;
- Validation Reputation.

## 74. Reputation and Selection

Consensus Reputation influences Candidate selection only within bounded limits.

Reputation SHALL not:

- grant permanent Validator status;
- override Known Control Group limits;
- replace required Stake;
- permit incompatible software;
- excuse misconduct.

## 75. Reward Beneficiary

Consensus rewards are paid to the declared Reward Beneficiary Wallet.

Changing the beneficiary:

- requires owner authorization;
- becomes effective at an Epoch boundary;
- does not change Known Control Group history;
- does not reset Maturity or Reputation.

## 76. Multiple Consensus Services per Wallet

One Wallet MAY own multiple Consensus Services.

However:

- each Service requires separate Stake;
- each Service has separate Maturity and Health;
- each Service must independently qualify;
- Known Control Group limits apply;
- only permitted active slots receive voting authority.

Registering extra candidates does not increase the Consensus Pool.

## 77. Self-Delegation and Delegated Stake

Delegated Stake is not supported in the MVP.

Only directly controlled Stake may secure a Consensus Service.

Future versions MAY introduce delegation.

Delegation SHALL require separate economics and cannot silently alter equal voting power.

## 78. Consensus Pool Share

Consensus Pool rewards follow `ECO-0004`.

The pool is fixed before individual rewards are calculated.

The number of Validators does not enlarge the pool.

Example:

`Consensus Pool = 1500Q`
`Active eligible Validators = 15`

The `15` Validators divide the same pool according to proven participation weights.

## 79. Small Active Set Rewards

If fewer independent Validators exist than the diversity target, `ECO-0004` reduces the distributable Consensus Pool through the Diversity Factor.

This prevents early Validators from collecting the entire Consensus subsidy due solely to lack of competition.

## 80. Economic Attack: Validator Multiplication

An operator may create many Consensus Candidates.

The attack is limited because:

- each Candidate requires separate Stake;
- each Candidate requires activation age;
- each Candidate must synchronize and remain healthy;
- Known Control Group limits active slots;
- equal voting power prevents over-staking;
- the Consensus Pool remains fixed;
- new identities begin with zero Maturity.

## 81. Economic Attack: Stake Concentration

An operator may accumulate large quantities of `Q`.

The attack is limited because:

- excess Stake does not increase voting power;
- one Known Control Group has limited active slots;
- Active Set selection requires operational eligibility;
- consensus authority cannot be purchased solely through Q balance.

## 82. Economic Attack: Intentional Downtime

A Validator may attempt to reduce network availability or manipulate rewards.

Consequences include:

- lost reward;
- reduced Health;
- reduced Reputation;
- removal;
- suspension after repetition.

Downtime does not create additional `Q` or increase later reward entitlement.

## 83. Economic Attack: Manufactured Slashing

An attacker may attempt to fabricate misconduct evidence against another Validator.

Protection includes:

- cryptographic evidence requirements;
- deterministic verification;
- no direct reporter bounty;
- replay protection;
- signed consensus-message validation.

Invalid accusations do not cause penalties.

Repeated malicious evidence submissions MAY affect the submitter's Reputation.

## 84. Economic Attack: Key Theft

A stolen consensus key could double-sign and slash the Validator.

Operators SHOULD use:

- isolated signing processes;
- hardware-backed keys where available;
- remote signers;
- strict key access control;
- monitoring;
- emergency rotation.

The protocol cannot distinguish malicious use from key theft when the same valid key signs conflicting messages.

The Stake secures key-management responsibility as well as operator honesty.

## 85. Economic Attack: Long-Range Identity Cycling

A slashed operator may create new Consensus Services.

Protection includes:

- Known Control Group history;
- owner Wallet history;
- fresh activation delay;
- new Stake requirement;
- zero initial Maturity;
- reduced group-level Consensus Reputation where applicable.

The protocol cannot perfectly identify undisclosed new Wallet ownership.

## 86. Testnet Parameters

Testnet MAY use:

`Consensus Stake:`
`100–500Q`

`Activation Age:`
`1–3 Epochs`

`Unbonding:`
`2–5 Epochs`

`Target Validator Set:`
`4–21`

Testnet configuration SHALL be visibly separate from production-like configuration.

## 87. Production-Like Review

Before production-like deployment, the protocol SHALL review:

- initial Q supply;
- average Consensus reward;
- Stake-to-reward ratio;
- cost of operating many candidates;
- Active Set diversity;
- reward concentration;
- unbonding adequacy;
- observed downtime;
- key-security incidents.

The initial `500Q` Stake is not guaranteed to remain appropriate.

## 88. Stake-to-Reward Monitoring

The network SHOULD publish:

`StakeCoverageRatio = ConsensusStake / MedianConsensusRewardPerEpoch`

This measures how many Epochs of typical rewards are at risk.

A very low ratio weakens deterrence.

A very high ratio may prevent legitimate participation.

The metric initially informs protocol upgrades rather than automatically changing Stake.

## 89. Consensus Metrics

The network SHALL publish:

- Candidate count;
- Active Validator count;
- independent group count;
- Active Set composition;
- voting-power distribution;
- participation rates;
- proposer success;
- missed votes;
- suspended Validators;
- Stake distribution;
- unbonding Stake;
- slashed Q;
- Consensus Pool distribution;
- reward concentration;
- halt duration.

## 90. Epoch Tasks

Consensus economics integrates with `RFC-0048` through tasks including:

`Freeze Consensus Evidence`
`Evaluate Candidate Eligibility`
`Evaluate Active Validator Performance`
`Process Misconduct Evidence`
`Apply Suspensions`
`Calculate Retained Validators`
`Select Rotating Validators`
`Generate Validator Set Update`
`Calculate Consensus Rewards`
`Begin Unbonding`
`Release Matured Stake`

Task dependencies SHALL determine execution order.

## 91. Ledger Operations

This specification uses:

- `SERVICE_REGISTER`;
- `SERVICE_UPDATE`;
- `SERVICE_RETIRE`;
- `STAKE_LOCK`;
- `UNSTAKE_REQUEST`;
- `STAKE_RELEASE`;
- `CONSENSUS_VALIDATOR_SET_UPDATE`;
- `PARTICIPANT_SUSPEND`;
- `PARTICIPANT_REINSTATE`;
- `PENALTY_APPLY`;
- `REWARD_MINT`;
- `EPOCH_TRANSITION`.

No Consensus Service may directly alter its own Ledger eligibility.

## 92. Parameter Configuration

The following are versioned protocol parameters:

- Consensus Stake;
- activation age;
- minimum Consensus Reputation;
- minimum Health;
- target Validator Set size;
- minimum operational set size;
- equal voting-power value;
- Known Control Group active-slot limit;
- bootstrap group exception;
- bootstrap group power cap;
- rotation fraction;
- selection-factor bounds;
- reward participation threshold;
- retention participation threshold;
- persistent-downtime threshold;
- suspension periods;
- exit delay;
- unbonding period;
- slashing percentages;
- key-ban rules;
- Diversity target.

## 93. Parameter Changes

Consensus economic parameters SHALL change only through:

- a versioned protocol upgrade;
- deterministic activation Epoch;
- published migration rules;
- declared Stake transition periods where needed.

A Stake increase SHALL not immediately slash or invalidate otherwise compliant Validators without a reasonable transition window.

## 94. Deferred Features

The MVP MAY postpone:

- delegated Stake;
- liquid Stake;
- stake-weighted voting;
- dynamic Stake adjustment;
- automatic hosting-diversity incentives;
- private Validator identities;
- zero-knowledge ownership grouping;
- standby Validator rewards;
- insurance against key theft;
- governance-based Validator admission;
- cross-chain Validator security.

## 95. Economic Invariants

The following SHALL always hold:

`Stake Above Minimum`
`Does Not Increase Voting Power`

`One Active Validator`
`=`
`One Equal Voting Unit`

`Known Control Group Influence`
`<=`
`Configured Group Limit`

`Candidate Registration`
`Does Not Guarantee Selection`

`Candidate Status`
`Does Not Earn Consensus Reward`

`Ordinary Downtime`
`Does Not Automatically Slash Stake`

`Objective Double-Signing`
`Causes Immediate Removal and Slashing`

`Consensus Rewards`
`<=`
`Consensus Pool Budget`

## 96. Security Invariants

- Consensus keys are unique.
- Conflicting signatures are objectively verifiable.
- Validator Set changes are protocol-generated.
- Local configuration cannot alter voting power.
- A minority partition cannot lower the finality threshold.
- Safety is preferred over liveness during partitions.
- Unbonding Stake remains slashable for historical misconduct.
- Key rotation does not erase old-key responsibility.
- Consensus State divergence causes suspension and recovery.
- No administrator can directly assign arbitrary Validator voting power.

## 97. Design Invariants

- CometBFT provides consensus mechanics.
- AiDN determines Validator eligibility and economics.
- Consensus Stake is collateral, not purchased authority.
- Voting power is equal in the MVP.
- Known Control Groups have bounded active influence.
- Active Validators rotate deterministically.
- Reward depends on proven consensus participation.
- Ordinary failures reduce reward and eligibility before causing penalties.
- Severe slashing requires objective cryptographic evidence.
- Double-signing causes complete Consensus Stake loss under the initial policy.
- Slashed `Q` is recycled according to `ECO-0005`.
- Consensus Candidates earn no passive reward.
- Consensus Pool size does not depend on Validator count.
- Every Validator Set transition is finalized and auditable.
