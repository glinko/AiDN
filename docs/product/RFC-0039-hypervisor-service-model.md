RFC-0039

Hypervisor Service Model

Status: Draft

Version: 0.1 - Reconstructed Edition

Depends on:

* RFC-0036 AiDN Ledger State Machine
* RFC-0037 Settlement Engine

Extended by:

* RFC-0040 Service Verification Framework
* RFC-0042 Hypervisor Network Protocol
* RFC-0045 Capability Architecture
* RFC-0046 Registry Architecture
* RFC-0053 Capability Runtime Specification
* RFC-0058 Participant Eligibility and Sybil Resistance

---

## 1. Purpose

This document defines the AiDN Hypervisor Service Model.

It specifies:

* the role of a Hypervisor;
* the relationship between a Hypervisor and its Services;
* Service identities;
* Service ownership and operation;
* Service registration;
* Service authorization;
* Service lifecycle;
* Service configuration;
* Service Health;
* Service isolation;
* Service discovery;
* Service eligibility;
* Service withdrawal and retirement;
* the relationship between Services, Capability Runtimes and Endpoints.

The Hypervisor Service Model provides a common operational foundation for all AiDN network roles.

---

## 2. Core Principle

A Hypervisor is a protocol host and service coordinator.

It is not one monolithic network role.

A Hypervisor MAY operate several independent Services, including:

Consensus Service
Registry Service
Validation Service
Capability Runtime
Endpoint Gateway
Future protocol-defined Services

Each Service SHALL have:

* its own identity;
* its own lifecycle;
* its own configuration;
* its own Health;
* its own eligibility;
* its own Reputation Profile where applicable;
* its own protocol responsibilities.

A failure in one Service SHALL not automatically invalidate every other Service operated by the same Hypervisor.

---

## 3. Hypervisor Definition

A Hypervisor is an AiDN node responsible for:

* maintaining a node identity;
* connecting to the AiDN network;
* authorizing local or remote Services;
* routing protocol messages;
* managing Service lifecycle;
* exposing public Service state;
* protecting Wallet and node credentials;
* enforcing Session and economic boundaries;
* coordinating Capability Runtimes;
* publishing and withdrawing Endpoints;
* reporting operational state.

The Hypervisor SHALL not contain every Service implementation internally.

---

## 4. Hypervisor Identity

Every Hypervisor SHALL have a unique cryptographic identity.

```yaml
hypervisor_identity:
  hypervisor_id:
  node_public_key:
  network_id:
  chain_id:
  protocol_version:
  owner_wallet:
  identity_version:
```

The Hypervisor Identity is separate from:

* Wallet Identity;
* Service Identity;
* Consensus Key;
* Runtime Identity;
* Endpoint Identity;
* Session Identity.

---

## 5. Wallet and Hypervisor Separation

The Wallet controls economic authorization.

The Hypervisor controls node-level protocol operation.

A compromised Hypervisor process SHALL not automatically gain unrestricted access to the owner's Wallet private key.

Wallet authorization MAY be performed through:

* an isolated signer;
* hardware-backed signing;
* a remote signer;
* another supported secure mechanism.

---

## 6. Service Definition

A Service is an independently identifiable operational component performing one AiDN network role.

A Service MAY be:

* embedded in the Hypervisor process;
* a separate local process;
* a container;
* a virtual machine;
* a remote service;
* a shared authorized service;
* another supported execution environment.

Deployment topology SHALL not change Service protocol semantics.

---

## 7. Core Service Roles

The initial protocol recognizes:

CONSENSUS
REGISTRY
VALIDATION
CAPABILITY_RUNTIME

Additional Service roles MAY be introduced through a versioned protocol update.

---

## 8. Consensus Service

A Consensus Service participates in:

* block proposal;
* prevote;
* precommit;
* block finalization;
* consensus evidence;
* Validator Set transitions.

Consensus eligibility and economics are defined separately.

Registering a Consensus Service does not grant voting authority.

---

## 9. Registry Service

A Registry Service stores and serves protocol information, including:

* finalized Ledger history;
* protocol objects;
* Advertisements;
* Validation Reports;
* Certification history;
* Reputation history;
* Epoch results;
* Snapshot metadata.

Registry architecture and replication are defined separately.

---

## 10. Validation Service

A Validation Service performs assigned Endpoint validation work.

It MAY use:

* automated agents;
* operator review;
* specialized tools;
* local models;
* external analysis systems;
* hybrid execution.

A registered Validation Service receives no reward without completed qualifying work.

---

## 11. Capability Runtime

A Capability Runtime performs computational work behind one or more Endpoints.

The Runtime:

* implements Capability-specific execution;
* manages Providers;
* executes requests;
* reports usage;
* reports Health;
* maintains execution context.

The detailed Runtime model is defined by RFC-0053.

---

## 12. Endpoint Is Not a Service Identity

An Endpoint is a Consumer-facing economic and execution offer.

It is not identical to:

* the Hypervisor;
* the Runtime;
* the Provider;
* the Service process.

Conceptually:

```text
Hypervisor
    ↓ authorizes
Capability Runtime
    ↓ supports
Endpoint
    ↓ accepts
Consumer Session
```

One Runtime MAY support several Endpoints when permitted by its Capability specification.

---

## 13. Service Identity

Every Service SHALL have a unique cryptographic identity.

```yaml
service_identity:
  service_id:
  service_role:
  service_public_key:
  owner_wallet:
  operator_hypervisor:
  reward_beneficiary:
  identity_version:
```

A Service Identity SHALL not be reused for another Service role.

---

## 14. Identity Separation

The following identities SHALL remain distinct:

Wallet Identity
Hypervisor Identity
Service Identity
Runtime Identity
Endpoint Identity
Consensus Signing Key
Governance Key
Session Identity

One key MAY technically authorize several roles only where explicitly permitted.

The recommended model uses separate keys and authorization domains.

---

## 15. Service Owner

The Service Owner is the Wallet with canonical authority to:

* register the Service;
* authorize an operating Hypervisor;
* update ownership-controlled metadata;
* change the Reward Beneficiary;
* retire the Service;
* lock required Stake or Bond.

Ownership does not prove operational control at every moment.

---

## 16. Service Operator

The Service Operator is the Hypervisor responsible for running the Service.

The operator is responsible for:

* connectivity;
* software;
* configuration;
* security;
* protocol behavior;
* Service availability;
* evidence publication.

The owner and operator MAY be different where delegation is explicitly declared.

---

## 17. Reward Beneficiary

A Service MAY declare a Reward Beneficiary Wallet.

The Reward Beneficiary receives protocol rewards earned by that Service.

Changing the Reward Beneficiary:

* requires owner authorization;
* does not change Service Identity;
* does not erase Reputation;
* does not reset Maturity;
* may affect Known Control Group analysis.

---

## 18. Delegated Operation

A Service Owner MAY authorize another Hypervisor to operate the Service.

Delegated operation SHALL include:

```yaml
service_operator_authorization:
  service_id:
  owner_wallet:
  operator_hypervisor_id:
  authorization_scope:
  activation_epoch:
  expiration_epoch:
  owner_signature:
```

The operating Hypervisor SHALL not gain ownership rights merely by running the Service.

---

## 19. Service Registration

A Service SHALL be registered before it can become publicly active.

Registration includes:

```yaml
service_registration:
  service_id:
  service_role:
  owner_wallet:
  operator_hypervisor_id:
  reward_beneficiary:
  service_public_key:
  protocol_version:
  service_version:
  configuration_hash:
  service_policy_hash:
  dependency_manifest_hash:
  locality_class:
  registration_epoch:
  owner_signature:
  operator_signature:
```

---

## 20. Registration Is a Declaration

Registration proves only that:

* the owner authorized the Service record;
* the operator claims to operate the Service;
* the Service Identity exists;
* the declared configuration is bound to a hash.

Registration does not prove:

* availability;
* correct implementation;
* sufficient resources;
* protocol compliance;
* eligibility;
* reward entitlement.

---

## 21. Registration Lifecycle

Service registration follows:

```text
UNREGISTERED
    ↓
REGISTERING
    ↓
REGISTERED
    ↓
VERIFICATION_PENDING
    ↓
VERIFIED
    ↓
ELIGIBLE
```

A Service MAY remain registered without ever becoming verified or eligible.

---

## 22. Discovery Does Not Imply Authorization

A Hypervisor MAY discover a local or remote Service process.

Discovery SHALL not automatically authorize it.

A discovered Service SHALL not receive:

* Session data;
* Wallet authorization;
* Endpoint publication rights;
* reward-reporting authority;
* validation assignments;

until it is explicitly authorized.

---

## 23. Local Service Authorization

A Hypervisor SHALL maintain an authorization record for every connected Service.

Authorization MAY use:

* configured public key;
* registration token;
* certificate enrollment;
* operator approval;
* local trust policy;
* hardware attestation where supported.

---

## 24. Service Authentication

Every Service connection SHALL authenticate:

* Service ID;
* Service key possession;
* Service role;
* supported protocol version;
* current authorization state.

Authentication does not prove Service correctness.

---

## 25. Canonical and Local State

The protocol distinguishes:

Canonical Service State

Stored or committed through Ledger state.

Local Operational State

Observed by the operating Hypervisor.

Examples of canonical state:

* registered;
* verified;
* eligible;
* suspended;
* retired.

Examples of local state:

* process starting;
* connection lost;
* queue full;
* disk nearly full;
* Provider unavailable.

---

## 26. Canonical Service States

The initial canonical states are:

UNREGISTERED
REGISTERED
VERIFICATION_PENDING
VERIFIED
ELIGIBLE
DEGRADED
SUSPENDED
DRAINING
RETIRED

Not every Service role uses every state identically.

---

## 27. Local Operational States

The initial local states are:

DISCOVERED
AUTHORIZING
CONNECTING
INITIALIZING
READY
BUSY
DEGRADED
UNAVAILABLE
RECOVERING
DRAINING
DISCONNECTED

Local state SHALL not independently alter Ledger eligibility.

---

## 28. UNREGISTERED

No canonical Service record exists.

The component may run locally but has no public protocol role.

---

## 29. REGISTERED

The Service has a canonical identity and declaration.

It is not yet considered proven operational.

---

## 30. VERIFICATION_PENDING

Initial or repeated Service Verification is required.

The Service may remain publicly visible as unverified.

It SHALL not receive rewards requiring verified operation.

---

## 31. VERIFIED

The Service has passed applicable verification.

Verification is time-bounded and role-specific.

Verified status does not necessarily imply current reward eligibility.

---

## 32. ELIGIBLE

The Service satisfies the active role-specific requirements for:

* assignments;
* participation;
* rewards;
* protocol duties.

Eligibility may be recalculated every Epoch.

---

## 33. DEGRADED

The Service remains operational but has material current limitations.

Examples include:

* reduced availability;
* excessive synchronization lag;
* partial Provider failure;
* temporary quota exhaustion;
* repeated protocol errors.

A degraded Service MAY lose some eligibility while remaining visible.

---

## 34. SUSPENDED

The Service is temporarily prohibited from one or more protocol functions.

Suspension SHALL define:

* reason;
* scope;
* start;
* minimum duration;
* recovery requirements;
* evidence reference.

Suspension of one Service SHALL not automatically suspend unrelated Services.

---

## 35. DRAINING

The Service is preparing to stop.

During draining:

* new duties MAY be refused;
* existing obligations SHOULD complete;
* active Sessions follow their own recovery rules;
* public availability is updated;
* retirement or relocation may follow.

---

## 36. RETIRED

The Service no longer performs its network role.

Its:

* identity;
* history;
* Reputation;
* evidence;
* ownership history;

remain available.

Retirement does not erase prior behavior.

---

## 37. Service State Transitions

Every canonical state transition SHALL be:

* authorized;
* versioned;
* replay-protected;
* auditable;
* deterministic from valid evidence.

A local process SHALL not directly declare itself canonically eligible.

---

## 38. Service Verification

A Service becomes verified only through the Service Verification Framework.

Verification MAY include:

* identity challenge;
* reachability test;
* protocol compliance;
* role-specific Duty Proof;
* resource test;
* response test;
* synchronization check;
* repeated random challenge.

Detailed verification is defined by RFC-0040.

---

## 39. Verification Is Role-Specific

Different Services require different evidence.

Examples:

Consensus

* synchronized state;
* valid consensus key;
* compatible software;
* vote readiness.

Registry

* required object availability;
* completeness;
* challenge response;
* valid hashes.

Validation

* supported tools;
* report capability;
* assignment execution;
* evidence publication.

Runtime

* Capability implementation;
* request execution;
* Usage Reporting;
* Health Reporting.

---

## 40. Verification Expiration

Verification MAY expire.

Expiration MAY depend on:

* time;
* configuration change;
* Service upgrade;
* repeated failures;
* protocol upgrade;
* operator change;
* security incident.

An expired verification SHALL not remain permanently authoritative.

---

## 41. Eligibility

Eligibility is a role-specific deterministic result.

Eligibility MAY depend on:

* registration age;
* current verification;
* Service Health;
* Reputation;
* Stake or Bond;
* Duty Proof;
* protocol version;
* configuration;
* active suspension;
* Known Control Group restrictions.

---

## 42. Eligibility Is Not Permanent

A Service may be:

Eligible in Epoch 10
Ineligible in Epoch 11
Eligible again in Epoch 15

Temporary ineligibility does not require a new Service Identity.

---

## 43. Registration Does Not Earn Rewards

A registered Service earns no Q merely because it:

* exists;
* is installed;
* exposes a port;
* reports itself healthy;
* remains listed in configuration.

Rewards require protocol-defined useful work and evidence.

---

## 44. Service Maturity

A Service MAY accumulate role-specific Maturity through qualifying Epochs.

Maturity SHALL remain attached to the Service Identity.

It SHALL not automatically transfer to:

* another Service;
* another role;
* a replacement identity;
* a cloned container.

---

## 45. Service Reputation

Every public Service role SHOULD maintain a role-specific Reputation Profile.

Examples:

* Consensus Reputation;
* Registry Reputation;
* Validation Reputation;
* Endpoint Reputation.

One role's positive Reputation SHALL not erase another role's failure.

---

## 46. Hypervisor Reputation Relationship

Negative Service evidence MAY propagate upward to the parent Hypervisor when it indicates:

* shared infrastructure failure;
* routing failure;
* operator misconduct;
* identity compromise;
* repeated cross-Service problems.

Positive Hypervisor Reputation SHALL not automatically make a new Service trustworthy.

---

## 47. Service Health

Service Health represents current operational condition.

Health MAY include:

* availability;
* latency;
* queue depth;
* synchronization lag;
* error rate;
* resource pressure;
* Provider availability;
* challenge success;
* recovery state.

---

## 48. Self-Reported Health

A Service MAY report local Health metrics.

Self-reported metrics are useful for:

* routing;
* diagnostics;
* load management;
* operator alerts;
* graceful draining.

They SHALL not directly create canonical rewards or Reputation.

---

## 49. Public Health

Public Service Health SHALL be derived from some combination of:

* signed Service reports;
* Hypervisor observations;
* external challenges;
* finalized protocol evidence;
* Session results;
* role-specific verification.

The applicable role specification determines the authoritative calculation.

---

## 50. Health and Reputation Separation

Health describes current condition.

Reputation describes behavior over time.

A Service may have:

Strong historical Reputation
+
Current degraded Health

or:

Little Reputation history
+
Current healthy operation

---

## 51. Service Configuration

Every Service SHALL expose a versioned configuration commitment.

```yaml
service_configuration:
  service_id:
  service_version:
  protocol_version:
  configuration_hash:
  policy_hashes:
  dependency_manifest_hash:
  effective_epoch:
```

Configuration secrets SHALL not be published.

---

## 52. Configuration Hash

The Configuration Hash SHALL commit to all execution-relevant public behavior.

It MAY cover:

* protocol version;
* Service role;
* required resources;
* role-specific policy;
* dependencies;
* public limits;
* storage profile;
* validation profile;
* routing behavior.

---

## 53. Configuration Change

A material Service change SHALL produce a new Configuration Hash.

Material changes MAY include:

* role behavior;
* protocol version;
* verification-relevant settings;
* security policy;
* storage profile;
* Runtime behavior;
* dependency model;
* accounting behavior.

---

## 54. Reverification After Change

A material configuration change MAY cause:

VERIFIED
→
VERIFICATION_PENDING

The previous verification remains part of history but does not automatically apply to materially changed behavior.

---

## 55. Secret Configuration

Service configuration MAY contain:

* API keys;
* OAuth tokens;
* database credentials;
* signing-key references;
* private network addresses;
* Provider credentials.

Secrets SHALL not be placed in:

* Ledger;
* Marketplace;
* public Registry objects;
* public Health Reports;
* Validation Reports.

---

## 56. Service Dependencies

A Service MAY depend on:

* another local process;
* a Runtime;
* storage;
* a database;
* network connectivity;
* another AiDN Service;
* external upstream Provider;
* signing infrastructure.

Dependencies SHALL be declared at an appropriate abstraction level.

---

## 57. Dependency Manifest

```yaml
service_dependency_manifest:
  service_id:
  required_dependencies:
  optional_dependencies:
  failure_propagation:
  recovery_order:
  dependency_policy_version:
```

Sensitive dependency details MAY remain concealed.

---

## 58. Dependency Failure

Failure of a dependency MAY cause the Service to become:

* degraded;
* unavailable;
* recovering;
* ineligible.

The dependency's identity and the Service's identity remain distinct.

---

## 59. No Circular Mandatory Dependency

Mandatory Service dependencies SHALL not create an unrecoverable cycle.

Example of a dangerous cycle:

Registry requires Validator activation
Validator activation requires Registry

Bootstrap and recovery paths SHALL remain explicitly defined.

---

## 60. Service Isolation

Services SHOULD be isolated so that one compromised or failed Service cannot directly:

* access Wallet private keys;
* control unrelated Services;
* alter Ledger state;
* read unrelated Session data;
* modify another Service's evidence;
* impersonate another Service.

---

## 61. Process Isolation

Implementations MAY use:

* separate processes;
* containers;
* virtual machines;
* operating-system users;
* network namespaces;
* mandatory access control;
* remote execution.

The protocol does not mandate one isolation technology.

---

## 62. Resource Isolation

A Hypervisor SHOULD be able to limit Service use of:

* CPU;
* memory;
* GPU;
* disk;
* bandwidth;
* open files;
* concurrent requests;
* queue size.

A Service exhausting its resources SHOULD not automatically terminate the Hypervisor.

---

## 63. Secret Isolation

Each Service SHALL receive only secrets required for its role.

Examples:

* Consensus Service receives its consensus signing access;
* Registry does not need OAuth Provider credentials;
* Runtime does not need Wallet spending keys;
* Validation Service does not need Consensus keys.

---

## 64. Service Crash

A Service crash SHALL:

* update local state;
* trigger Health changes;
* preserve evidence;
* initiate recovery where possible;
* affect only applicable obligations.

The Hypervisor SHOULD continue operating unrelated Services.

---

## 65. Hypervisor Crash

After Hypervisor restart, it SHALL:

1. recover Hypervisor Identity;
2. load authorized Service records;
3. reconnect Services;
4. reconcile canonical Service state;
5. recover active obligations;
6. report current Health;
7. resume public operation.

---

## 66. Service Reconnection

A reconnecting Service SHALL prove:

* Service Identity;
* authorization;
* compatible version;
* current configuration;
* last known state;
* pending obligations.

The Hypervisor SHALL not blindly trust stale local state.

---

## 67. Service Recovery

A recovering Service MAY need to restore:

* task state;
* Session state;
* last report sequence;
* synchronization position;
* challenge state;
* result hashes;
* queue state.

Role-specific recovery is defined by the applicable Service RFC.

---

## 68. Service Replacement

An operator MAY replace one Service implementation with another while preserving Service Identity only when:

* role remains the same;
* owner authorization remains valid;
* key control remains valid;
* configuration compatibility is declared;
* required state is transferred or reconstructed;
* no conflicting evidence exists.

---

## 69. Replacement and Reputation

Replacing:

* hardware;
* container;
* executable;
* host;
* database engine;

does not erase Service Reputation when Service Identity remains the same.

---

## 70. Incompatible Replacement

A materially incompatible replacement SHALL require:

* new Configuration Hash;
* re-verification;
* possible temporary ineligibility;
* public state update.

It MAY require a new Service Identity when role continuity cannot be established.

---

## 71. Service Relocation

A Service MAY move between:

* hosts;
* VMs;
* containers;
* networks;
* operating Hypervisors.

Relocation SHALL preserve:

* identity;
* authorization;
* evidence history;
* Maturity;
* Reputation;

when continuity is valid.

---

## 72. Multiple Services of One Role

One Hypervisor MAY operate multiple Services of the same role.

Each instance SHALL have:

* separate Service ID;
* separate authorization;
* separate configuration;
* separate Health;
* separate verification;
* separate role-specific obligations.

---

## 73. No Artificial Service Multiplication

Splitting one implementation into several Service identities SHALL not automatically create:

* additional useful work;
* additional rewards;
* additional governance power;
* additional Faucet rights;
* additional independent Reputation.

Later Sybil-resistance rules MAY aggregate known common control.

---

## 74. Shared Service Backend

Several Service identities MAY share:

* storage;
* network;
* hardware;
* Provider;
* Runtime backend.

Shared infrastructure SHALL not automatically prove fraud.

It creates a shared failure domain and SHALL not be presented as independent infrastructure where that matters.

---

## 75. Service Groups

A Hypervisor MAY organize Services into local Service Groups for:

* failover;
* maintenance;
* load distribution;
* recovery;
* resource allocation.

A local Service Group is not automatically a canonical protocol object.

---

## 76. Public Service Advertisement

A Hypervisor MAY advertise active Services to peers.

Advertisement MAY include:

* Service ID;
* role;
* protocol version;
* current public state;
* public Health summary;
* supported features;
* network address;
* verification reference.

Detailed network behavior is defined by RFC-0042.

---

## 77. Advertisement Is Not Proof

A Service Advertisement is a signed availability claim.

It does not prove:

* Service correctness;
* Service completeness;
* reward eligibility;
* independent ownership;
* future availability.

---

## 78. Service Discovery

Hypervisors MAY discover Services through:

* local configuration;
* process discovery;
* explicit registration;
* network discovery;
* Registry data;
* peer exchange;
* operator approval.

Discovery SHALL not bypass authentication or authorization.

---

## 79. Service Control Plane

The Hypervisor Service Control Plane SHALL support operations conceptually equivalent to:

REGISTER
AUTHORIZE
CONNECT
NEGOTIATE
START
READY
HEALTH_REPORT
DEGRADE
DRAIN
STOP
RECOVER
REPLACE
RETIRE

Detailed messages are defined by role-specific protocols.

---

## 80. Service Data Plane

The Service Data Plane carries role-specific work.

Examples include:

* Consensus votes;
* Registry objects;
* Validation tasks;
* Runtime requests;
* Usage Reports;
* artifacts.

Control-plane authorization SHALL precede data-plane access.

---

## 81. Service Events

A Service MAY emit:

SERVICE_CONNECTED
SERVICE_READY
SERVICE_HEALTH_CHANGED
SERVICE_CONFIGURATION_CHANGED
SERVICE_DEGRADED
SERVICE_RECOVERING
SERVICE_DRAINING
SERVICE_DISCONNECTED
SERVICE_SECURITY_ALERT

Local events do not automatically become canonical Ledger events.

---

## 82. Canonical Service Operations

The Ledger Operation Catalog SHOULD support operations equivalent to:

SERVICE_REGISTER
SERVICE_UPDATE
SERVICE_OPERATOR_AUTHORIZE
SERVICE_OPERATOR_REVOKE
SERVICE_VERIFICATION_COMMIT
SERVICE_SUSPEND
SERVICE_REINSTATE
SERVICE_RETIRE

Exact schemas are defined in RFC-0059.

---

## 83. Service Update

A Service Update MAY change:

* public metadata;
* operator;
* Reward Beneficiary;
* configuration;
* policy references;
* network address;
* supported protocol version.

Each field SHALL have an explicit authorization rule.

---

## 84. Operator Revocation

The Service Owner MAY revoke an operator authorization.

Revocation SHALL:

* take effect at a deterministic boundary;
* prevent future Service actions;
* preserve already finalized history;
* not erase pending obligations;
* define recovery or draining behavior.

---

## 85. Service Retirement

Retirement SHALL be explicit.

Before retirement, the Service SHOULD:

* stop accepting new duties;
* complete or transfer active duties;
* publish draining state;
* resolve pending rewards and penalties;
* begin applicable Stake or Bond release.

---

## 86. Retirement Does Not Cancel Liability

A Service cannot avoid:

* pending penalty;
* evidence review;
* Session Settlement;
* Stake slashing;
* Bond forfeiture;
* report obligations;

merely by retiring.

---

## 87. Service Stake and Bond

Some Service roles MAY require:

* Stake;
* Bond;
* Escrow contribution;
* performance collateral.

Collateral belongs to the applicable economic specification.

The Hypervisor Service Model does not define one universal collateral requirement.

---

## 88. Reward Accounting

Rewards SHALL be bound to:

* Service ID;
* reward role;
* reward Epoch;
* Reward Beneficiary;
* qualifying evidence.

One piece of work SHALL not generate several rewards merely because several local components participated internally.

---

## 89. Service Responsibility Boundary

The public Service remains responsible for protocol behavior even when it depends on:

* external software;
* a shared backend;
* an upstream Provider;
* another operator;
* remote infrastructure.

Internal delegation does not transfer Consumer-facing or protocol-facing responsibility unless explicitly declared.

---

## 90. Service Policy

Each role MAY define a Service Policy covering:

* availability;
* capacity;
* deadlines;
* resource limits;
* recovery behavior;
* duty acceptance;
* public disclosure;
* verification;
* retention.

The policy SHALL be versioned.

---

## 91. Service Versioning

Every Service SHALL advertise:

* Service implementation version;
* supported protocol version;
* Service Policy version;
* configuration version;
* supported optional features.

Version changes SHALL not silently alter active obligations.

---

## 92. Compatibility

A Hypervisor SHALL reject or isolate a Service when:

* protocol versions are incompatible;
* role is unsupported;
* required security features are absent;
* configuration cannot be validated;
* message semantics differ.

Compatibility negotiation is detailed by RFC-0042 and role-specific protocols.

---

## 93. Active Obligation Stability

A Service upgrade SHALL not retroactively change:

* accepted Session contracts;
* assigned Validation obligations;
* Registry challenge requirements;
* Consensus duties;
* reward evidence.

Existing obligations remain bound to their accepted versions.

---

## 94. Service Security Incident

A Service security incident MAY include:

* key compromise;
* unauthorized operator;
* conflicting signatures;
* secret exposure;
* malicious binary;
* evidence fabrication;
* privilege escape.

The Hypervisor SHOULD:

* isolate the Service;
* preserve evidence;
* stop unsafe actions;
* rotate credentials;
* initiate canonical suspension where required.

---

## 95. Service Key Rotation

Service key rotation SHALL require:

* owner authorization;
* proof of possession of the new key;
* effective boundary;
* preservation of old-key history;
* unresolved-evidence handling.

Rotation SHALL not erase responsibility for messages signed by the old key.

---

## 96. Hypervisor Removal

Removing a Hypervisor from operation does not automatically retire its Services.

Services MAY:

* relocate;
* authorize another Hypervisor;
* enter suspension;
* retire.

The canonical Service state determines the outcome.

---

## 97. Network Partition

During a network partition:

* Services MAY continue bounded local work;
* canonical changes require Consensus finality;
* public Health may become uncertain;
* duplicate duties SHALL be prevented where possible;
* recovery SHALL reconcile with finalized state.

A local Service view SHALL not replace canonical Ledger history.

---

## 98. Consensus Halt

During Consensus halt:

* canonical Service registration and updates stop;
* current registered state remains readable;
* Services MAY continue work permitted by finalized authorization;
* new economic state remains pending;
* no local Hypervisor may unilaterally declare canonical eligibility.

---

## 99. Observability

A Hypervisor SHOULD expose:

* registered Services;
* local operational state;
* canonical state;
* Health;
* version;
* verification status;
* eligibility;
* configuration hash;
* active obligations;
* recovery state;
* recent errors.

Sensitive secrets SHALL remain hidden.

---

## 100. Metrics

Service metrics MAY include:

* uptime;
* response latency;
* request throughput;
* queue depth;
* error rate;
* resource utilization;
* synchronization lag;
* recovery attempts;
* challenge success;
* active duty count.

Metrics are diagnostic unless made protocol-verifiable.

---

## 101. Conformance

A Hypervisor Service implementation SHALL pass conformance tests covering:

* identity;
* registration;
* authorization;
* authentication;
* lifecycle transitions;
* configuration updates;
* Health Reporting;
* reconnection;
* recovery;
* draining;
* retirement;
* malformed messages;
* incompatible versions;
* secret isolation;
* role isolation.

---

## 102. Reference Service

The AiDN project SHOULD provide a minimal Reference Service implementation.

It SHOULD support:

* unique Service Identity;
* registration;
* authorization;
* Health Reporting;
* configuration hashing;
* simulated degradation;
* draining;
* recovery;
* retirement.

The Reference Service provides a stable target for Hypervisor development.

---

## 103. MVP Requirements

The MVP SHALL implement:

* Hypervisor Identity;
* Service Identity;
* separate owner, operator and Reward Beneficiary;
* Consensus, Registry, Validation and Runtime roles;
* Service registration;
* Service authorization;
* canonical and local state separation;
* Service lifecycle;
* Service configuration hashes;
* Service Health Reporting;
* Service Verification hooks;
* Service isolation;
* Service reconnection;
* Service recovery;
* Service draining;
* Service retirement;
* role-specific eligibility;
* no reward for registration alone;
* complete Service history.

---

## 104. Deferred Features

The MVP MAY postpone:

* anonymous Service identities;
* zero-knowledge ownership;
* hardware-attested Service identity;
* cross-network Service portability;
* Service leasing markets;
* automated operator delegation;
* multi-operator threshold Services;
* transferable Service Maturity;
* confidential Service configuration proofs;
* standardized Service packaging.

---

## 105. Open Protocol Parameters

The following remain role-specific or configurable:

* minimum registration age;
* verification frequency;
* Health thresholds;
* authorization expiration;
* reconnect timeout;
* draining duration;
* retirement delay;
* operator-transfer delay;
* key-rotation delay;
* maximum Services per Hypervisor;
* required isolation level;
* public Health update interval.

---

## 106. Identity Invariants

```text
Wallet Identity
≠
Hypervisor Identity

Hypervisor Identity
≠
Service Identity

Service Identity
≠
Endpoint Identity

Service Identity
≠
Runtime Identity

Ownership
≠
Operational Control

Reward Beneficiary
≠
Automatic Service Owner
```

---

## 107. Lifecycle Invariants

* Registration does not imply verification.
* Verification does not permanently imply eligibility.
* Local readiness does not create canonical eligibility.
* Suspension is scoped to the affected Service.
* Retirement does not erase history.
* Operator replacement does not erase Reputation.
* Configuration changes may require reverification.
* Active obligations survive ordinary version changes.

---

## 108. Economic Invariants

```text
Registered Service
Does Not Automatically Earn Q

Installed Service
Does Not Automatically Earn Q

Self-Reported Health
Does Not Automatically Earn Q

One Useful Contribution
Cannot Be Multiplied by Local Service Splitting

Reward Is Bound to Service Evidence
```

---

## 109. Security Invariants

* Discovered Services are unauthorized by default.
* Service messages are authenticated.
* Services receive least-privilege access.
* Runtime Services do not receive Wallet spending keys.
* One Service cannot impersonate another Service role.
* Service key rotation preserves old-key accountability.
* Local state cannot override canonical state.
* Secrets do not enter public Registry or Ledger state.
* A compromised Service does not automatically compromise unrelated Services.
* Canonical suspension requires defined evidence and authorization.

---

## 110. Design Invariants

* The Hypervisor coordinates Services rather than implementing every role monolithically.
* Every public network role has an independent Service identity.
* Services may run locally or remotely without changing protocol semantics.
* Public Service state and local process state remain distinct.
* Service failures are isolated.
* Service behavior is role-specific.
* Service verification is external to self-declaration.
* Service eligibility is periodically reevaluated.
* Reputation is role-specific.
* Endpoints are Consumer-facing offers backed by Runtimes, not aliases for Hypervisors.
* New Service roles can be added without redesigning the Hypervisor core.

Комментарии

1. Главная идея: Hypervisor не должен быть монолитом

Правильная структура выглядит так:

```text
Hypervisor
├── Consensus Service
├── Registry Service
├── Validation Service
├── Capability Runtime A
└── Capability Runtime B
```

Если Registry упал, это не должно автоматически:

* останавливать Runtime;
* удалять Endpoints;
* уничтожать Consensus Service;
* заставлять перезапускать всю ноду.

Иначе любой новый сервис увеличивает радиус поражения всего Hypervisor. Классическая архитектура "сложим всё в один процесс, потом назовём это простотой".

---

2. Здесь важно различать Service, Runtime и Endpoint

Это три разных объекта:

Service

Это протокольная роль или управляемый компонент.

Runtime

Это исполнитель Capability и владелец Provider-specific логики.

Endpoint

Это публичное предложение Consumer: Capability, цена, политика, лимиты и доступность.

Например:

```text
llama.cpp Runtime
    ↓
Endpoint A: Qwen, дешёвый
Endpoint B: Qwen, большой контекст
Endpoint C: тот же Runtime, другой Session Policy
```

Hypervisor публикует Endpoints, но не обязан понимать внутренности llama.cpp.

---

3. Owner, Operator и Reward Beneficiary разделены намеренно

В простейшем случае это один Wallet и один Hypervisor.

Но модель позволяет:

Owner:
владелец Service
Operator:
тот, кто физически запускает Service
Reward Beneficiary:
Wallet, получающий награды

Это понадобится для:

* делегированного хостинга;
* совместной инфраструктуры;
* управляемых нод;
* переноса Service между Hypervisors;
* разделения технического и экономического контроля.

При этом такая гибкость требует Known Control Group, иначе оператор начнёт переставлять Beneficiary и торжественно объявлять каждую перестановку новым независимым участником.

---

4. Регистрация, Verification и Eligibility не одно и то же

Цепочка должна быть такой:

```text
SERVICE_REGISTER
    ↓
Service существует в Ledger
    ↓
Service Verification
    ↓
Service доказал базовую работоспособность
    ↓
Epoch Eligibility
    ↓
Service допускается к работе или наградам
```

Просто установить Registry и открыть порт недостаточно.

Иначе reward system превратится в конкурс запуска пустых контейнеров, область, где кожанные неожиданно демонстрируют поразительную производительность.

---

5. Нужны два состояния: canonical и local

Пример:

Canonical State: ELIGIBLE
Local State: DISCONNECTED

Это означает, что по результатам последней эпохи Service был допущен, но прямо сейчас процесс недоступен.

Или наоборот:

Canonical State: VERIFICATION_PENDING
Local State: READY

Локально всё работает, но сеть ещё это не проверила.

Смешивать эти состояния нельзя. Иначе self-reported READY мгновенно становится сетевой истиной.

---

6. Сервис может быть удалённым

Hypervisor не обязан запускать всё на одном сервере:

```text
Hypervisor VM
    ↓ private network
Runtime on GPU host
```

или:

```text
Hypervisor
    ↓ authenticated connection
shared remote Runtime
```

Для протокола важны:

* Identity;
* Authorization;
* version compatibility;
* configuration binding;
* security boundary.

Физическое расположение вторично.

---

7. Изоляция важнее технологии упаковки

RFC не требует Docker, Kubernetes или виртуальных машин.

Он требует результат:

* Service не получает лишние secrets;
* падение Service не валит Hypervisor;
* Runtime не может подписать Wallet transfer;
* Registry не читает OAuth-токены Proxy;
* Validation Service не получает Consensus key.

Как именно это обеспечено, решает реализация.

---

8. Что уже нужно добавить в следующую редакцию

После более поздних RFC документу понадобится версия RFC-0039 v0.2.

Из RFC-0058:

* Known Control Group;
* owner/operator/beneficiary aggregation;
* Service identity cycling;
* delegated-control evidence.

Из RFC-0061 и RFC-0062:

* Full, Archive и Cache Registry profiles;
* Snapshot Provider role;
* synchronization state;
* Registry completeness.

Из RFC-0063:

* Proxy Runtime status;
* upstream dependencies;
* OAuth state;
* quota and rate-limit reporting.

Из RFC-0064:

* Validation Escrow contribution;
* assignment capacity;
* concealed Session credentials;
* post-execution abandonment.

Из RFC-0066:

* network_revision;
* active protocol versions;
* upgrade readiness;
* emergency Service states.

Из RFC-0067:

* Governance Key;
* Infrastructure Chamber eligibility;
* Service contribution paths;
* governance snapshots.

Но базовый принцип RFC-0039 остаётся прежним: Hypervisor является координатором независимых протокольных сервисов, а не одним огромным процессом, который одновременно хранит блоки, валидирует картинки, запускает модели и держит ключи от всего хозяйства.
