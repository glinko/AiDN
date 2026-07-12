# RFC-0058 Participant Eligibility and Sybil Resistance

Status: `Draft`

Version: `0.1`

Depends on:

- `RFC-0016 Wallet and Identity`
- `RFC-0036 AiDN Ledger State Machine`
- `RFC-0039 Hypervisor Service Model`
- `RFC-0040 Service Verification Framework`
- `RFC-0041 Reputation Profile Engine`
- `RFC-0047 CometBFT Consensus Integration`
- `RFC-0048 Epoch Engine`
- `ECO-0005 Q Emission, Recycling and Epoch Reward Allocation`

## 1. Purpose

This document defines:

- participant identity levels;
- Hypervisor eligibility states;
- requirements for participating in protocol rewards;
- basic Sybil-resistance mechanisms;
- reward aggregation rules;
- service-specific eligibility principles;
- the limits of decentralized identity verification.

The protocol SHALL permit one operator to own and operate multiple legitimate Hypervisors.

The protocol SHALL prevent simple identity multiplication from creating a proportional increase in unearned rewards or protocol influence.

## 2. Problem Statement

In an open network, one operator may create:

- multiple Wallets;
- multiple Hypervisors;
- multiple Endpoints;
- multiple Registry Services;
- multiple Validation Services;
- multiple Consensus Services.

The network cannot generally prove that two independently created Wallets belong to the same physical person.

Therefore, AiDN SHALL NOT claim to provide perfect one-person-one-participant identity.

Instead, AiDN applies economic and operational Sybil resistance.

Every additional reward-eligible identity SHALL require additional:

- time;
- collateral where applicable;
- operational availability;
- independently verified work;
- protocol responsibility.

## 3. Design Philosophy

AiDN does not prohibit multiple nodes under common ownership.

Operating multiple useful nodes is legitimate.

The protocol distinguishes between:

Multiple nodes providing additional useful capacity

and:

Multiple identities created only to multiply rewards or influence

The protocol SHALL reward additional proven contribution.

It SHALL NOT reward identity count alone.

## 4. Identity Hierarchy

AiDN defines the following identity levels:

`Wallet Identity -> Hypervisor Identity -> Service Identity -> Endpoint Identity`

Each identity has a separate purpose.

## 5. Wallet Identity

A Wallet represents protocol ownership and economic authority.

A Wallet may own:

- multiple Hypervisors;
- multiple Services;
- multiple Endpoints;
- Stakes;
- Bonds;
- reward rights.

Wallet ownership is established through Ledger Operations.

A Wallet count SHALL NOT be treated as proof of operator count.

## 6. Hypervisor Identity

Every Hypervisor has an independent Node Identity.

Node Identity is represented by a cryptographic key pair distinct from the owner Wallet.

The Hypervisor private key authorizes node-level protocol communication.

The owner Wallet authorizes:

- Hypervisor registration;
- ownership changes;
- Service activation;
- reward destination;
- Hypervisor retirement.

A Hypervisor Identity SHALL remain unique.

## 7. Service Identity

Every reward-eligible Service instance SHALL have a distinct Service Identity.

Examples include:

- Registry Service Identity;
- Consensus Service Identity;
- Validation Service Identity.

A Service Identity is bound to:

- one Hypervisor;
- one Service type;
- one owner Wallet;
- one activation record.

Creating a Service Identity does not grant reward eligibility.

## 8. Endpoint Identity

Every Endpoint has an independent Endpoint Identity.

Endpoint count SHALL NOT directly increase:

- Faucet eligibility;
- Service reward weight;
- Consensus voting power;
- Validation assignment capacity.

For Faucet eligibility, a Hypervisor needs at least one active Endpoint.

Creating additional Endpoints on the same Hypervisor does not create additional Faucet claims.

## 9. Participant State Machine

A registered Hypervisor follows this eligibility lifecycle:

`UNREGISTERED -> REGISTERED -> ACTIVATING -> ELIGIBLE -> SUSPENDED -> ELIGIBLE or RETIRED`

## 10. Registered State

A Hypervisor becomes `REGISTERED` after a finalized registration operation.

Registration includes:

- Node Identity;
- owner Wallet;
- protocol version;
- reward Wallet;
- registration Epoch;
- enabled Services.

Registration alone provides no reward rights.

## 11. Activating State

A registered Hypervisor enters `ACTIVATING` while it establishes:

- protocol compatibility;
- network availability;
- minimum uptime;
- Endpoint or Service functionality;
- required collateral;
- initial verification evidence.

The activation period introduces a time cost to large-scale identity creation.

## 12. Eligible State

A Hypervisor or Service becomes `ELIGIBLE` only after satisfying the requirements of the relevant protocol activity.

Eligibility is activity-specific.

A Hypervisor may be:

- Faucet-eligible;
- Registry-ineligible;
- Validation-eligible;
- Consensus-ineligible;

at the same time.

There is no universal reward-eligible status.

## 13. Suspended State

A Hypervisor or Service may become `SUSPENDED` after:

- repeated Duty Proof failure;
- protocol incompatibility;
- expired registration;
- insufficient collateral;
- confirmed misconduct;
- repeated unavailability;
- service-specific eligibility failure.

Suspension SHALL affect only the relevant protocol function unless the violation is broader.

## 14. Retired State

A Hypervisor may be retired voluntarily by its owner.

Retirement:

- stops future reward eligibility;
- prevents new Faucet claims;
- does not delete historical records;
- does not remove completed Reputation history;
- does not automatically invalidate owned Endpoints transferred elsewhere.

## 15. Eligibility Snapshot

Reward and Faucet eligibility SHALL be determined from a finalized Epoch snapshot.

Changes occurring after the snapshot take effect in the next Epoch unless a protocol rule explicitly requires immediate suspension.

This prevents eligibility from changing differently across nodes during the same Epoch.

## 16. General Eligibility Requirements

A reward-eligible participant SHALL have:

- a valid registered identity;
- a compatible protocol version;
- a valid owner Wallet;
- a valid reward destination;
- required operational age;
- required collateral where applicable;
- required Duty Proof;
- acceptable Health;
- no active suspension.

Each reward pool MAY define additional requirements.

## 17. No Reward for Identity Count

The following SHALL NOT increase reward weight by themselves:

- creating a Wallet;
- registering a Hypervisor;
- enabling a Service;
- publishing multiple Endpoints;
- creating multiple advertisements;
- generating additional keys;
- declaring additional capacity.

Reward weight arises only from qualifying work and verified availability.

## 18. Fixed Pool Protection

All protocol rewards originate from fixed Epoch pools defined by `ECO-0005`.

Creating more identities does not enlarge a reward pool.

Therefore:

More participants
`->`
smaller average reward per participant

not:

More participants
`->`
more total `Q` emitted

This is the primary system-wide Sybil protection.

## 19. Contribution Normalization

Service reward calculations SHALL normalize contribution before distribution.

A participant SHALL NOT gain additional weight by splitting one contribution across multiple identities.

Examples:

- the same Consensus vote cannot count for two Services;
- the same Registry response cannot count for two Registry identities;
- the same Validation Report cannot reward two Validators;
- the same Endpoint Session cannot count as independent work multiple times.

Every proof SHALL have a unique protocol identity.

## 20. Reward Beneficiary

Every Hypervisor and Service SHALL declare a Reward Beneficiary Wallet.

The Reward Beneficiary:

- receives protocol rewards;
- is visible in Ledger state;
- may own multiple Hypervisors;
- may be used for reward concentration accounting.

Changing the beneficiary SHALL require owner authorization and become effective at a future Epoch boundary.

## 21. Known Control Group

The protocol defines a Known Control Group as identities linked through finalized protocol relationships.

Provable links MAY include:

- the same owner Wallet;
- the same Reward Beneficiary Wallet;
- explicit delegation;
- shared ownership records;
- common Stake ownership;
- explicit organization membership.

Known Control Groups SHALL be used where protocol rules require reward or voting-power aggregation.

They SHALL also be used where governance rules require:

- one Infrastructure Chamber voting unit per known control group;
- aggregation of multiple Service identities into one Infrastructure governance participant;
- detection of conflicts where one operator attempts to multiply governance influence through additional Service registrations.

Detailed reward-pool aggregation and concentration formulas are defined separately by `ECO-0004`.

## 22. Unknown Common Ownership

The protocol cannot reliably prove common ownership based only on:

- IP address;
- geographic location;
- hosting provider;
- network latency;
- similar hardware;
- similar configuration;
- transaction history.

Such signals MAY support risk analysis.

They SHALL NOT alone trigger:

- slashing;
- confiscation;
- suspension;
- forced ownership grouping.

The network SHALL avoid replacing Sybil resistance with enthusiastic false accusations.

## 23. Collateral

Selected protocol roles MAY require locked collateral.

Collateral creates an economic cost for operating many reward-eligible identities.

Collateral MAY include:

- Node Activation Bond;
- Registry Bond;
- Validation Stake;
- Consensus Stake.

Collateral remains owned by the participant while locked.

It may be reduced only through explicitly defined protocol violations.

## 24. Node Activation Bond

A future production-like network MAY require a refundable Node Activation Bond for reward-eligible Hypervisors.

The bond SHALL:

- be locked per Hypervisor;
- remain unavailable while eligibility is active;
- be returned after a defined exit delay;
- not automatically create reward weight;
- not grant Consensus voting power by itself.

The initial bond amount is a versioned protocol parameter.

Testnet MAY set the bond to zero.

## 25. Activation Delay

Reward-eligible identities MAY require a minimum activation period.

The delay exists to reduce profitable rapid identity cycling.

Recommended initial principles:

- Faucet eligibility: at least one completed qualifying Epoch;
- Registry eligibility: full synchronization plus successful verification;
- Validation eligibility: existing Validator requirements;
- Consensus eligibility: separate Consensus activation and unbonding rules.

Exact durations are protocol parameters.

## 26. Faucet Eligibility

Under `ECO-0005`, a Faucet-eligible Hypervisor SHALL:

- be registered;
- have a valid Node Identity;
- be associated with a Wallet;
- not be suspended;
- have at least one active Endpoint;
- satisfy the minimum Faucet activation age;
- submit no more than one successful claim per Epoch.

Multiple Endpoints on one Hypervisor do not create multiple Faucet claims.

## 27. Faucet Sybil Limitation

The MVP Faucet rule remains economically vulnerable to operators registering many active Hypervisors.

The following mechanisms reduce but do not eliminate this risk:

- fixed total Faucet Pool;
- Faucet division among all eligible Hypervisors;
- activation delay;
- active Endpoint requirement;
- one claim per Hypervisor per Epoch;
- Node Identity;
- Endpoint reachability checks;
- future Node Activation Bond.

Faucet eligibility SHALL be considered an evolving protocol mechanism.

## 28. Initial Participant Access

A new participant may initially lack `Q` required for collateral.

The protocol MAY support a limited onboarding path for the first Hypervisor associated with a new Wallet.

Possible future mechanisms include:

- one-time onboarding grant;
- temporary bond exemption;
- sponsored activation;
- invitation-based activation;
- bounded computational challenge.

The MVP SHALL define one deterministic onboarding path before non-zero Node Activation Bonds become mandatory.

## 29. Registry Eligibility

A Registry Service becomes reward-eligible only after:

- completing required synchronization;
- storing the required object set;
- serving protocol queries;
- passing initial Proof of Registry;
- maintaining acceptable Health;
- satisfying minimum operational age;
- locking required collateral if configured.

Claimed storage capacity alone creates no reward rights.

## 30. Registry Sybil Resistance

Registry reward weight SHALL depend on verified service contribution rather than Registry identity count.

The protocol SHOULD consider:

- successful challenge responses;
- availability;
- object completeness;
- response correctness;
- response latency;
- Snapshot delivery;
- independent service locations where verifiable.

Running multiple Registry identities over the same incomplete dataset SHALL not satisfy completeness requirements.

## 31. Consensus Eligibility

Consensus eligibility is separate from ordinary Hypervisor registration.

A Consensus Service SHALL satisfy:

- protocol compatibility;
- synchronization;
- Consensus Stake;
- minimum Consensus Reputation;
- minimum operational age;
- valid consensus key;
- stable participation;
- absence of active suspension.

Detailed requirements are defined by Consensus Economics.

## 32. Consensus Voting-Power Resistance

Stake amount alone SHALL NOT permit unlimited voting power.

The MVP uses:

- equal voting power per active Consensus Service;
- bounded active slots per Known Control Group;
- deterministic active-set selection;
- minimum operational requirements;
- unbonding delays.

A large `Q` balance SHALL NOT automatically permit control of consensus.

## 33. Consensus Identity Splitting

Creating multiple Consensus identities SHALL require:

- separate collateral;
- separate eligibility;
- separate operational responsibility;
- separate participation proofs.

The protocol MAY limit:

- active Consensus Services per Reward Beneficiary;
- voting power per Known Control Group;
- reward share per Known Control Group.

Exact limits belong to `ECO-0006`.

## 34. Validation Eligibility

Initial Validation Service requirements include:

- required uptime history;
- at least one previously certified Endpoint;
- minimum Validation Reputation;
- required Stake;
- ability to execute and publish a Validation Report;
- valid Validation Service Identity.

Manual, automated and hybrid validation MAY all satisfy execution capability.

## 35. Validation Assignment Resistance

Creating multiple Validation identities SHALL NOT multiply reward unless each identity:

- satisfies eligibility;
- receives a valid assignment;
- performs independent work;
- publishes an eligible report;
- provides unique evidence.

One Validation Report SHALL reward only one assigned Validator unless the assignment explicitly supports collaborative validation.

## 36. Validation Cherry-Picking

The assignment system SHOULD prevent Validators from accepting only:

- cheap Endpoints;
- fast Endpoints;
- familiar Capabilities;
- favorable operators.

Possible controls include:

- bounded decline rates;
- randomized offers;
- Capability-specific Validator pools;
- complexity-adjusted rewards;
- acceptance Reputation metrics.

Declining an unaccepted assignment is not misconduct.

Repeated acceptance followed by non-completion affects Health and Reputation.

## 37. Compute and Endpoint Sybil Resistance

Compute Providers earn primarily through Session payments.

Creating additional Compute identities creates no direct Protocol Reward.

Artificial self-dealing Sessions SHALL NOT count as qualified infrastructure work.

Endpoint count MAY affect Marketplace visibility only through actual:

- availability;
- Sessions;
- Reputation;
- independent demand.

## 38. Self-Dealing

A Session between identities in the same Known Control Group MAY remain valid as private computation.

However, it SHALL NOT automatically qualify for:

- network growth measurements;
- independent demand metrics;
- anti-Sybil proof;
- additional Protocol Rewards;
- Validator eligibility growth.

The transfer of existing `Q` remains valid unless another protocol rule is violated.

## 39. Reward Weight Aggregation

Before pool distribution, rewards MAY be aggregated by Reward Beneficiary or Known Control Group.

Conceptually:

`GroupRawWeight = Sum(MemberRawWeights)`

A protocol-defined concentration function MAY then be applied:

`EffectiveGroupWeight = ConcentrationFunction(GroupRawWeight)`

The function MAY include:

- a hard cap;
- diminishing returns;
- square-root weighting;
- pool-share limits.

The exact function is defined by the corresponding reward specification.

For MVP infrastructure reward pools, that specification is `ECO-0004`.

## 40. Diminishing Returns

Future versions MAY apply diminishing returns to multiple Services under common control.

Example:

`EffectiveWeight = sqrt(RawWeight)`

or:

- `First eligible Service: 100% weight`
- `Second: 80%`
- `Third: 65%`
- `Further Services: decreasing weight`

The MVP SHOULD use simple transparent rules rather than opaque heuristics.

## 41. Pool Share Cap

A reward pool MAY define a maximum share payable to one Reward Beneficiary or Known Control Group.

Example:

`Maximum Registry Pool Share per Known Control Group = 10%`

When a cap leaves part of a pool undistributed:

- the remainder SHALL NOT be redistributed above the cap;
- the remainder SHALL not be minted unless the pool specification says otherwise.

The exact caps remain open protocol parameters.

For MVP service rewards, the cap model is defined by `ECO-0004`.

## 42. Maturity Independence

Each Service instance maintains independent Maturity.

Creating a new Service does not inherit:

- the Hypervisor's Maturity;
- another Service's Maturity;
- the owner Wallet's age;
- another Endpoint's Reputation.

A newly created identity begins its own eligibility history.

## 43. Reputation Independence

Positive Reputation SHALL not flow downward into new identities.

A trusted Wallet does not automatically create trusted Hypervisors.

A trusted Hypervisor does not automatically create trusted Services.

Negative confirmed behavior MAY propagate upward conservatively according to `RFC-0041`.

## 44. Identity Cycling

Retiring a low-Reputation identity and creating a new one SHALL not automatically erase all economic consequences.

The protocol MAY consider:

- owner Wallet history;
- Reward Beneficiary history;
- locked collateral;
- repeated registration patterns;
- related Service history.

New identities still begin with no positive Reputation or Maturity.

## 45. Ownership Transfer

Future protocol versions MAY support Hypervisor and Endpoint ownership transfer.

Ownership transfer SHALL define separately:

- technical Reputation retention;
- Service Maturity retention;
- owner-specific eligibility;
- collateral transfer;
- reward beneficiary changes;
- activation delay after transfer.

The MVP MAY postpone ownership transfer.

## 46. Service Verification

Every reward-eligible Service SHALL integrate with `RFC-0040`.

Service Verification provides evidence that the Service:

- exists;
- is reachable;
- performs its declared duties;
- reports valid metrics;
- remains compatible with the protocol.

Verification evidence SHALL be bound to the exact Service Identity.

## 47. Eligibility Challenges

The protocol MAY issue random eligibility challenges.

Examples include:

- Endpoint reachability request;
- Registry object request;
- Consensus participation requirement;
- Validation capability check.

Failure of a challenge MAY:

- reduce Health;
- pause Maturity growth;
- suspend reward eligibility;
- trigger additional verification.

One isolated network failure SHOULD NOT automatically trigger slashing.

## 48. Evidence Reuse

One piece of evidence SHALL NOT satisfy multiple independent obligations unless the protocol explicitly permits it.

Examples:

- one Registry proof cannot count as ten proofs;
- one Endpoint response cannot activate multiple Hypervisors;
- one consensus signature cannot represent multiple Validator identities;
- one Validation Report cannot satisfy multiple assignments.

Evidence identifiers SHALL be unique and replay-protected.

## 49. Epoch Integration

Participant Eligibility is calculated through deterministic Epoch Tasks.

Relevant tasks include:

- Freeze Participant Snapshot
- Evaluate Activation Requirements
- Verify Collateral
- Evaluate Duty Proof
- Apply Suspensions
- Calculate Eligible Service Sets
- Aggregate Known Control Groups
- Publish Eligibility Results

Eligibility results become effective according to task dependencies defined by `RFC-0048`.

## 50. Immediate Suspension

Objective critical misconduct MAY cause immediate suspension before the next ordinary eligibility calculation.

Examples include:

- consensus double-signing;
- forged protocol evidence;
- conflicting signed accounting records;
- invalid Registry proofs;
- malicious Validation Report fabrication.

Immediate suspension SHALL require finalized objective evidence.

## 51. Appeal and Recovery

An automatically suspended participant MAY recover by:

- correcting configuration;
- restoring required collateral;
- passing required verification;
- completing a recovery delay;
- publishing required evidence.

Confirmed cryptographic misconduct MAY require longer or permanent exclusion from the relevant role.

Recovery rules are service-specific.

## 52. IP Address Policy

IP addresses MAY be used for:

- routing;
- abuse throttling;
- local rate limiting;
- network diagnostics.

IP addresses SHALL NOT be treated as durable protocol identity.

Multiple legitimate Hypervisors may share one IP.

One Hypervisor may use multiple IP addresses.

## 53. Hardware Identity

Hardware identifiers SHALL NOT be mandatory in the MVP.

Mandatory hardware identity would:

- reduce portability;
- create privacy risks;
- favor specific vendors;
- remain spoofable in many environments;
- complicate virtualized deployment.

Future optional hardware attestation MAY support additional trust but SHALL NOT replace protocol identity.

## 54. External Identity

The MVP SHALL NOT require:

- government identity;
- proof of personhood;
- social account identity;
- biometric identity.

Future optional identity systems MAY provide additional eligibility classes.

Core network participation SHALL remain pseudonymous.

## 55. Monitoring Metrics

The network SHOULD publish aggregate Sybil-risk metrics:

- Wallets per Reward Beneficiary;
- Hypervisors per Wallet;
- Services per Wallet;
- reward concentration;
- voting-power concentration;
- Faucet claims per Wallet group;
- new identity creation rate;
- participant churn;
- Maturity distribution;
- collateral distribution.

Metrics are informational unless explicitly used by deterministic protocol rules.

## 56. Attack Examples

Endpoint Multiplication

An operator creates 100 Endpoints on one Hypervisor.

Result:

- one Faucet eligibility unit;
- no extra infrastructure reward;
- no extra Consensus power.

Hypervisor Multiplication

An operator creates 100 Hypervisors.

Result:

- each must independently activate;
- each must maintain an active Endpoint;
- each may require collateral;
- each begins with zero Maturity;
- Faucet Pool size remains fixed.

Registry Multiplication

An operator creates multiple Registry Services.

Result:

- every Service must independently pass Proof of Registry;
- pool size remains fixed;
- group caps or diminishing returns MAY apply.

Consensus Multiplication

An operator creates multiple Consensus Services.

Result:

- separate Stake and eligibility are required;
- aggregate voting power may be capped;
- active-set admission remains deterministic.

Validation Multiplication

An operator creates multiple Validators.

Result:

- every Validator needs separate eligibility;
- only completed assigned reports receive reward;
- one report cannot reward multiple identities.

## 57. MVP Requirements

The MVP SHALL implement:

- separate Wallet, Hypervisor, Service and Endpoint identities;
- owner Wallet binding;
- Reward Beneficiary Wallet;
- Epoch eligibility snapshots;
- Service-specific eligibility;
- activation age;
- independent Service Maturity;
- independent Duty Proof;
- one Faucet claim per eligible Hypervisor per Epoch;
- one Faucet unit per Hypervisor regardless of Endpoint count;
- fixed reward pools;
- unique evidence identifiers;
- replay protection;
- Consensus Stake;
- Validation Stake;
- objective immediate suspension;
- reward concentration metrics.

The MVP MAY postpone:

- mandatory Node Activation Bonds;
- sophisticated Known Control Group discovery;
- external identity integration;
- hardware attestation;
- advanced graph-based Sybil detection;
- automated cross-Wallet clustering;
- ownership transfer.

## 58. Open Protocol Parameters

The following remain to be defined:

- Faucet activation age;
- Node Activation Bond;
- Registry Bond;
- Consensus Stake;
- Validation Stake;
- service-specific minimum Health;
- service-specific minimum Maturity;
- reward pool share caps;
- Known Control Group aggregation rules;
- diminishing-return functions;
- active Consensus Set size;
- maximum voting power per group;
- identity recovery delays;
- collateral unbonding periods.

All parameters SHALL be versioned protocol configuration.

## 59. Security Limitations

AiDN cannot guarantee that:

one Wallet
=
one human

or:

one Hypervisor
=
one independent operator

Sybil resistance is therefore probabilistic and economic.

The protocol aims to ensure that creating additional identities requires proportionally more:

- resources;
- time;
- collateral;
- valid work;
- operational responsibility.

No single mechanism is sufficient alone.

## 60. Design Invariants

- Multiple legitimate Hypervisors per operator are allowed.
- Identity count alone never earns `Q`.
- Reward pools remain fixed regardless of participant count.
- Every reward-eligible identity independently proves contribution.
- New identities do not inherit positive Reputation or Maturity.
- Endpoint count does not multiply Faucet claims.
- One Hypervisor receives at most one Faucet claim per Epoch.
- Infrastructure roles may require collateral.
- Stake alone does not grant unlimited voting power.
- Consensus and reward influence may be aggregated by Known Control Group.
- IP address is not protocol identity.
- Sybil resistance SHALL not depend on unverifiable claims of human uniqueness.
- The protocol rewards useful additional capacity, not merely additional keys.
