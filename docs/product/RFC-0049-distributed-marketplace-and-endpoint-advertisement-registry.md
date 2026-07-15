RFC-0049

Distributed Marketplace and Endpoint Advertisement Registry

Status: Draft

Version: 0.3

Supersedes:

* RFC-0049 Version 0.1

Depends on:

* RFC-0036 AiDN Ledger State Machine
* RFC-0037 Settlement Engine
* RFC-0039 Hypervisor Service Model
* RFC-0040 AiDN Service Verification Framework
* RFC-0041 Reputation Profile Engine
* RFC-0042 AiDN Hypervisor Network Protocol
* RFC-0044 AiDN Session Protocol
* RFC-0045 AiDN Capability Architecture
* RFC-0046 AiDN Registry Architecture
* RFC-0048 Epoch Engine
* RFC-0051 Usage Reporting and Verification Protocol
* RFC-0053 Capability Runtime Specification
* RFC-0054 Capability Runtime Protocol
* RFC-0055 Provider Plugin System and Directory
* RFC-0056 Provider Plugin Runtime Interface
* RFC-0057 Validation Report Specification
* RFC-0058 Participant Eligibility and Sybil Resistance
* RFC-0059 Ledger Operation Catalog
* RFC-0061 Registry Replication Protocol
* RFC-0063 Proxy Endpoint Protocol
* RFC-0064 Validation Assignment, Concealed Session and Escrow Protocol
* RFC-0065 Endpoint Certification Derivation and Lifecycle Protocol
* RFC-0066 Protocol Upgrade and Emergency Recovery
* RFC-0067 Protocol Governance and Authorization Policy

⸻

## 1. Purpose

This document defines the AiDN Distributed Marketplace and Endpoint Advertisement Registry.

It specifies how Endpoint operators:

* publish Endpoint offers;
* describe supported Capabilities;
* publish prices and Accounting Modes;
* declare limits and availability;
* expose Proxy and Data Handling properties;
* bind offers to Endpoint Configuration Hashes;
* update and withdraw offers;
* preserve historical Advertisement versions;
* make Endpoints discoverable through distributed Registry Services.

It also specifies how Consumers and Marketplace clients:

* discover Endpoints;
* query and filter offers;
* verify Advertisement authenticity;
* evaluate freshness;
* compare pricing and limits;
* combine Advertisements with Certification and Reputation;
* apply local ranking policies;
* avoid stale or misleading offers.

⸻

## 2. Core Principle

An Endpoint Advertisement is a signed offer.

It is not proof that the Endpoint:

* is currently available;
* will accept a Session;
* produces high-quality output;
* uses the declared hidden model;
* is independently operated;
* is Certified;
* has good Reputation;
* will remain at the same price forever.

Conceptually:

Advertisement
=
Operator Claim
+
Bound Configuration
+
Public Commercial Terms
+
Expiration
+
Signature

⸻

## 3. Marketplace Definition

The AiDN Marketplace is a distributed view of active Endpoint Advertisements and associated public protocol information.

It is not one centralized service.

Marketplace views MAY be produced by:

* Registry Services;
* Consumer clients;
* independent search services;
* local indexes;
* Hypervisors;
* third-party applications.

⸻

## 4. Marketplace Is Not Consensus

Marketplace results SHALL NOT independently determine:

* canonical Endpoint ownership;
* Wallet balances;
* Certification state;
* Reputation state;
* Session Settlement;
* Governance decisions;
* Validator eligibility.

Canonical facts SHALL be verified against Ledger commitments and signed Registry objects.

⸻

## 5. Marketplace Is Not One Ranking

The protocol SHALL NOT define one mandatory global ranking of Endpoints.

Different Marketplace clients MAY rank by:

* price;
* latency;
* Certification;
* Reputation;
* accounting transparency;
* privacy;
* geographic proximity;
* Proxy status;
* context limit;
* feature support;
* operator diversity.

A local ranking SHALL be marked as non-canonical.

⸻

## 6. Endpoint Advertisement

An Endpoint Advertisement is an immutable, signed Registry Object describing one Endpoint offer for a bounded validity period.

Every Advertisement SHALL bind to:

* Endpoint ID;
* Endpoint Configuration Hash;
* Capability Definition Hash;
* Endpoint Implementation Profile;
* Pricing Policy;
* Accounting Contract;
* Session Policy;
* Failure Policy;
* Data Handling Policy;
* availability declaration;
* expiration;
* operator signature.

An Advertisement SHALL only be publishable after:

* a Runtime Binding or equivalent AiDN Runtime execution surface exists for the
  advertised Configuration Hash;
* the operator has created an Endpoint Draft or equivalent pre-publication
  object from that Runtime Binding.

⸻

## 7. Advertisement Object

```yaml
endpoint_advertisement:
  advertisement_id:
  advertisement_version:
  previous_advertisement_id:
  endpoint_id:
  endpoint_operator:
  operator_hypervisor_id:
  reward_beneficiary:
  endpoint_configuration_hash:
  runtime_reference:
  capability_id:
  capability_version:
  capability_definition_hash:
  implementation_profile_hash:
  feature_profile_hash:
  limit_profile_hash:
  pricing_policy_hash:
  accounting_contract_hash:
  session_policy_hash:
  failure_policy_hash:
  data_handling_policy_hash:
  availability_policy_hash:
  proxy_declaration_hash:
  access_policy_hash:
  minimum_session_deposit:
  maximum_session_duration:
  supported_funding_classes:
  certification_reference:
  reputation_reference:
  publication_epoch:
  valid_from:
  expiration:
  withdrawal_reference:
  registry_retention_class:
  advertisement_flags:
  operator_signature:
```

⸻

## 8. Advertisement Identity

Recommended derivation:

```text
advertisement_id
=
HASH(
    endpoint_id
    +
    advertisement_version
    +
    endpoint_configuration_hash
    +
    canonical_advertisement
)
```

Two different Advertisement payloads SHALL NOT share the same Advertisement ID.

⸻

## 9. Advertisement Version

Advertisement versions SHALL increase monotonically for one Endpoint.

A later version SHALL reference the previous Advertisement ID.

⸻

## 10. Advertisement Immutability

A published Advertisement SHALL be immutable.

Updating:

* price;
* limits;
* Capability;
* Proxy status;
* availability;
* policy;
* Configuration Hash;

requires a new Advertisement version.

⸻

## 11. Advertisement Version Chain

The logical Endpoint offer history follows:

```text
Advertisement v1
    ↓
Advertisement v2
    ↓
Advertisement v3
    ↓
Withdrawal
```

Registry Services SHOULD preserve the complete version chain according to their retention profile.

⸻

## 12. Active Advertisement

An Advertisement is active only when:

* its signature is valid;
* its Endpoint is not retired;
* its validity period has begun;
* it has not expired;
* no later active version supersedes it;
* no valid withdrawal applies;
* a compatible Runtime Binding remains present for the advertised Configuration
  Hash;
* no suspension blocks new Sessions;
* its Network Revision matches the client.

⸻

## 13. Advertisement Status

The derived Advertisement status is one of:

SCHEDULED
ACTIVE
SUPERSEDED
EXPIRED
WITHDRAWN
SUSPENDED
INCOMPATIBLE
ORPHANED
INVALID

⸻

## 14. SCHEDULED

The Advertisement is validly published but its valid_from boundary has not yet been reached.

⸻

## 15. ACTIVE

The Advertisement may be used to propose new Sessions.

Acceptance remains at Endpoint discretion.

⸻

## 16. SUPERSEDED

A later valid Advertisement version exists.

The object remains historical and may still govern Sessions opened under it.

⸻

## 17. EXPIRED

The Advertisement validity period ended.

It SHALL NOT be used to open a new Session.

⸻

## 18. WITHDRAWN

The operator explicitly withdrew the offer.

Existing accepted Sessions remain governed by their Session Contracts.

⸻

## 19. SUSPENDED

The Endpoint or relevant Service is currently prohibited from accepting new Sessions under canonical rules.

⸻

## 20. INCOMPATIBLE

The Advertisement uses:

* unsupported Protocol Version;
* unsupported Capability Major Version;
* another Network Revision;
* retired Accounting Contract;
* incompatible Session Protocol.

⸻

## 21. ORPHANED

The Advertisement lacks a valid required canonical reference.

Examples include:

* missing Endpoint registration;
* unknown Configuration Hash;
* invalid operator authorization;
* missing Capability Definition.

⸻

## 22. INVALID

The Advertisement fails:

* schema validation;
* signature validation;
* identity binding;
* hash validation;
* version-chain validation;
* policy-reference validation.

⸻

## 23. Endpoint Registration Requirement

An Endpoint SHALL be registered before its Advertisement may become active.

Advertisement publication does not create the Endpoint Identity.

⸻

## 24. Endpoint Identity

Every Advertisement SHALL reference one exact Endpoint ID.

The Endpoint ID SHALL remain separate from:

* Hypervisor ID;
* Runtime ID;
* Service ID;
* Provider ID;
* Advertisement ID.

⸻

## 25. Endpoint Operator

The Endpoint Operator is responsible for:

* Advertisement accuracy;
* Session acceptance;
* Runtime routing;
* pricing enforcement;
* maximum charge enforcement;
* Usage Reporting;
* Settlement;
* Proxy behavior;
* Data Handling disclosures.

⸻

## 26. Reward Beneficiary

The Advertisement MAY expose the Endpoint Reward Beneficiary or ordinary payment destination where protocol policy permits.

Changing the beneficiary does not create a new Endpoint Identity.

It MAY require:

* a new Configuration Hash;
* a new Advertisement;
* Known Control Group reevaluation.

⸻

## 27. Configuration Binding

Every Advertisement SHALL bind to one exact Endpoint Configuration Hash.

The Configuration Hash SHALL commit to all materially relevant Endpoint behavior.

⸻

## 28. Material Configuration Elements

The Configuration Hash SHOULD cover:

* Capability version;
* Runtime binding;
* supported features;
* limits;
* Accounting Mode;
* Proxy behavior;
* Provider-selection policy;
* Data Handling Policy;
* failure behavior;
* streaming behavior;
* side-effect controls;
* Session policy;
* security profile.

⸻

## 29. Configuration Change

A material configuration change SHALL require:

* a new Configuration Hash;
* a new Advertisement version;
* possible Endpoint reverification;
* possible Certification transition.

⸻

## 30. Non-Material Change

A non-material internal change MAY preserve the same Advertisement when it does not alter Consumer-visible behavior.

Examples include:

* internal logging;
* equivalent hardware replacement;
* implementation optimization;
* private cost change;
* database maintenance.

⸻

## 31. Capability Binding

Every Advertisement SHALL expose exactly one primary Capability.

```yaml
advertised_capability:
  capability_id:
  capability_version:
  capability_definition_hash:
```

⸻

## 32. Capability Compatibility

The Consumer SHALL verify that:

* the Capability version is supported;
* the Definition Hash is known;
* required features are present;
* required modalities are supported;
* the Capability is not retired or security-blocked.

⸻

## 33. Feature Profile

The Advertisement SHALL reference an Endpoint Feature Profile.

The profile SHALL identify:

* supported features;
* unsupported features;
* feature versions;
* feature-specific limits;
* temporary degradation where applicable.

⸻

## 34. Required Feature Handling

An Endpoint SHALL reject a Session or Request requiring an unsupported mandatory feature.

It SHALL NOT accept the work and silently ignore the feature.

⸻

## 35. Limit Profile

The Advertisement SHALL reference a versioned Limit Profile.

It MAY include:

maximum input bytes
maximum output bytes
maximum context units
maximum artifact size
maximum Request duration
maximum Session duration
maximum concurrent Requests
maximum tool calls
maximum workspace size

⸻

## 36. Hard Limits

Hard limits are binding acceptance boundaries.

A Request exceeding a hard limit SHALL be rejected before execution.

⸻

## 37. Soft Limits

Soft limits MAY permit execution through:

* different Request Class;
* higher price;
* reduced output;
* queueing;
* explicit Consumer acceptance.

⸻

## 38. Temporary Capacity

Current operational capacity MAY be lower than the advertised maximum.

The Endpoint MAY reject work before acceptance because of temporary capacity.

It SHALL NOT accept a Request under one limit and then apply an undisclosed lower limit during execution.

⸻

## 39. Pricing Policy

Every Advertisement SHALL reference a Pricing Policy.

```yaml
pricing_policy:
  pricing_policy_id:
  endpoint_id:
  capability_id:
  pricing_model:
  currency_unit: Q
  request_classes:
  unit_prices:
  minimum_charge:
  maximum_charge_rules:
  cancellation_pricing:
  partial_result_pricing:
  queue_time_pricing:
  retry_pricing:
  artifact_pricing:
  tool_pricing:
  effective_from:
  expiration:
  policy_version:
  operator_signature:
```

⸻

## 40. Pricing Models

Initial pricing models include:

FIXED_PER_REQUEST
FIXED_PER_REQUEST_CLASS
UNIT_BASED
TIME_BASED
ARTIFACT_BASED
OUTCOME_CLASS_BASED
HYBRID

⸻

## 41. Fixed Per Request

One accepted Request has one declared price.

Usage dimensions MAY still be reported for diagnostics.

⸻

## 42. Fixed Per Request Class

Price depends on a Request Class determined before execution.

Examples include:

SMALL
STANDARD
LARGE
EXTENDED

⸻

## 43. Unit-Based Pricing

Price is calculated from accepted billable units such as:

* bytes;
* deterministic tokens;
* audio seconds;
* video seconds;
* images;
* artifacts;
* tool calls.

The unit calculation SHALL be defined in the Accounting Contract.

⸻

## 44. Time-Based Pricing

Time-based pricing SHALL distinguish:

* active execution time;
* queue time;
* upstream waiting;
* retry delay;
* paused time;
* Consumer approval waiting.

Only declared billable time classes may be charged.

⸻

## 45. Artifact-Based Pricing

Price may depend on:

* artifact count;
* artifact class;
* output dimensions;
* artifact bytes;
* duration;
* format.

The Request Charge Ceiling remains binding.

⸻

## 46. Outcome-Class Pricing

A Capability MAY support bounded outcome classes when objectively distinguishable before Settlement.

Outcome classes SHALL NOT be vague subjective labels such as:

excellent answer
premium intelligence
high effort

unless a deterministic protocol definition exists, which would be a rare outbreak of precision.

⸻

## 47. Hybrid Pricing

A Hybrid policy combines several declared components.

Example:

1Q fixed Request fee
+
0.1Q per generated image
+
0.01Q per artifact MB

Every component SHALL be independently bounded.

⸻

## 48. Minimum Charge

An Endpoint MAY define a minimum charge for an accepted Request.

The minimum SHALL be visible before Request acceptance.

⸻

## 49. Maximum Charge Rule

Every Session and Request remains subject to:

ProviderPayment
≤
RequestChargeCeiling
≤
MaximumSessionCharge
≤
LockedDeposit

⸻

## 50. No Retroactive Price Change

A new Advertisement or Pricing Policy SHALL NOT change:

* an accepted Session;
* an accepted Request Class;
* completed work;
* a finalized Checkpoint.

⸻

## 51. Price Effective Boundary

A Pricing Policy SHALL specify:

* effective_from;
* expiration;
* Advertisement version;
* applicable Endpoint Configuration Hash.

⸻

## 52. Price Display

Marketplace clients SHOULD display:

* minimum Session Deposit;
* common Request prices;
* possible variable components;
* maximum known charge;
* cancellation costs;
* accounting uncertainty.

A single attractive starting price SHALL NOT conceal mandatory additional components.

⸻

## 53. Accounting Contract

Every Advertisement SHALL reference an Accounting Contract.

The contract SHALL define:

* Accounting Mode;
* possible usage dimensions;
* authoritative usage source;
* estimated usage treatment;
* billable units;
* rounding;
* checkpoints;
* report frequency;
* unknown-value behavior.

⸻

## 54. Supported Accounting Modes

Initial modes are:

DETERMINISTIC
OBSERVABLE
PROVIDER_METERED
PROXY_OPAQUE
FIXED_PRICE
HYBRID

⸻

## 55. Deterministic Accounting

Both parties can derive the same usage from published rules.

Example:

* byte count;
* image count;
* audio duration;
* agreed tokenizer and version.

⸻

## 56. Observable Accounting

Billing uses Consumer-visible or independently measurable work.

Examples include:

* completed artifacts;
* delivered bytes;
* accepted execution duration;
* acknowledged output segments.

⸻

## 57. Provider-Metered Accounting

An authoritative Provider usage report is accepted as the billing source.

The Advertisement SHALL disclose this dependency.

⸻

## 58. Proxy-Opaque Accounting

The upstream may not report exact usage.

The Advertisement SHALL explain:

* which values are unavailable;
* which estimates may be shown;
* which Consumer-facing units are billable;
* which maximum limits apply.

Unknown usage SHALL remain unknown.

⸻

## 59. Fixed-Price Accounting

Usage may be reported, but payment is determined by an accepted fixed price.

⸻

## 60. Accounting Transparency Indicator

Marketplace clients SHOULD expose an accounting-transparency label such as:

FULLY_DETERMINISTIC
CONSUMER_OBSERVABLE
PROVIDER_REPORTED
OPAQUE_UPSTREAM
FIXED_PRICE

This label is informational and derived from the Accounting Contract.

⸻

## 61. Session Policy

Every Advertisement SHALL reference a Session Policy defining:

* maximum Session duration;
* Idle Timeout;
* maximum Requests;
* maximum concurrency;
* queueing;
* recovery window;
* amendment support;
* Deposit extension;
* close behavior;
* artifact retention.

⸻

## 62. Failure Policy

Every Advertisement SHALL reference a Failure Policy defining:

* failure classes;
* retry behavior;
* partial-result treatment;
* cancellation;
* Provider payment after failure;
* Forced Settlement baseline;
* recovery windows.

⸻

## 63. Data Handling Policy

Every Advertisement SHALL expose a Data Handling Policy when user data may be:

* logged;
* retained;
* sent upstream;
* processed outside the Hypervisor;
* used by tools;
* stored in a remote workspace.

⸻

## 64. Data Handling Declaration

```yaml
data_handling_policy:
  content_may_leave_hypervisor:
  external_provider_possible:
  retention_possible:
  maximum_declared_retention:
  training_use_possible:
  geographic_constraints:
  deletion_support:
  encrypted_transport_required:
  restricted_data_supported:
  policy_version:
```

⸻

## 65. No Hidden Upstream Processing

An Endpoint SHALL NOT advertise data as local-only while transmitting it to an undeclared external Provider.

Objective evidence of such behavior may affect:

* Certification;
* Reputation;
* suspension;
* penalties where defined.

⸻

## 66. Access Policy

An Endpoint MAY restrict access by:

* public availability;
* allowlist;
* invitation;
* organization;
* credential class;
* jurisdiction;
* protocol role;
* private network.

Restrictions SHALL be declared.

⸻

## 67. Public Marketplace Visibility

An Advertisement MAY be:

PUBLIC
AUTHENTICATED_ONLY
RESTRICTED
UNLISTED
PRIVATE

⸻

## 68. Public Advertisement

May appear in ordinary Marketplace queries.

⸻

## 69. Authenticated-Only Advertisement

Requires an authenticated AiDN identity to retrieve full commercial terms.

⸻

## 70. Restricted Advertisement

Visible only to subjects satisfying the Access Policy.

⸻

## 71. Unlisted Advertisement

Retrievable by Advertisement ID or Endpoint ID but omitted from general search results.

⸻

## 72. Private Advertisement

Distributed only through explicitly authorized channels.

It may still use the same Advertisement schema.

⸻

## 73. Availability Policy

The Advertisement SHALL define expected availability behavior.

It MAY include:

* operating schedule;
* maintenance windows;
* queue policy;
* regional availability;
* maximum active Sessions;
* temporary Health endpoint;
* expected response deadline.

⸻

## 74. Advertised Availability Is Not Current Health

An availability schedule describes intended operation.

Current Health describes present condition.

Marketplace clients SHOULD distinguish them.

⸻

## 75. Current Endpoint Health

Current Health MAY be sourced from:

* signed Endpoint Health Reports;
* Hypervisor observations;
* Runtime state;
* Session acceptance results;
* recent protocol evidence.

Health remains distinct from Advertisement content.

⸻

## 76. Availability Status

A Marketplace client MAY derive:

AVAILABLE
BUSY
DEGRADED
MAINTENANCE
UNAVAILABLE
UNKNOWN

The derivation SHALL identify freshness.

⸻

## 77. Stale Health

A Health record older than the applicable freshness threshold SHALL be displayed as:

UNKNOWN

rather than confidently available.

⸻

## 78. Proxy Declaration

Every Advertisement SHALL state whether the Endpoint is:

DIRECT
PROXY_DISCLOSED
PROXY_OPAQUE_UPSTREAM
DYNAMIC_PROXY
COMPOSITE

⸻

## 79. Direct Endpoint

The operator declares that execution is performed through directly controlled Runtime infrastructure.

This is still a declaration unless supported by stronger attestation.

⸻

## 80. Proxy-Disclosed Endpoint

The Endpoint declares use of an external or downstream Provider and may disclose its identity or class.

⸻

## 81. Proxy-Opaque Upstream

The Endpoint declares that upstream identity or usage is not fully observable.

It SHALL use compatible Accounting Modes.

⸻

## 82. Dynamic Proxy

The Endpoint may choose among several upstreams.

The Advertisement SHALL disclose whether routing may change:

* model behavior;
* latency;
* data location;
* retention;
* moderation;
* accounting.

⸻

## 83. Composite Endpoint

The Endpoint performs internal multi-stage execution.

It remains responsible for one primary Consumer-facing Capability.

⸻

## 84. Proxy Disclosure Is Not Upstream Proof

A Proxy disclosure indicates what the operator claims.

It does not automatically prove the exact upstream.

Certification may verify only observable Proxy behavior.

⸻

## 85. Failover Policy

A Proxy or multi-Provider Endpoint SHOULD expose a Failover Policy.

```yaml
failover_policy:
  failover_enabled:
  maximum_attempts:
  provider_switch_allowed:
  result_variation_possible:
  state_continuity:
  billing_treatment:
  disclosure_level:
```

⸻

## 86. Retry Pricing Disclosure

The Advertisement SHALL state whether internal retries may affect Consumer payment.

Undeclared retries SHALL not create additional billable units.

⸻

## 87. Certification Reference

An Advertisement MAY reference current Endpoint Certification.

The reference SHALL identify:

* Certification Record;
* Endpoint Configuration Hash;
* Capability version;
* Certification state;
* expiration;
* observations.

⸻

## 88. Certification Is Not Advertisement Truth

Certification provides bounded evidence that the Endpoint responded under Validation.

It does not prove every Advertisement claim.

For example, it does not necessarily prove:

* exact hidden model;
* permanent availability;
* future quality;
* operator independence.

⸻

## 89. Certification Configuration Match

A Marketplace client SHALL verify:

Advertisement Configuration Hash
=
Certification Configuration Hash

A Certification for another configuration SHALL not be displayed as current Certification for this offer.

⸻

## 90. Certification States

Marketplace clients SHOULD distinguish:

UNCERTIFIED
CERTIFICATION_PENDING
CERTIFIED
CERTIFIED_WITH_OBSERVATIONS
DEGRADED
REVALIDATION_REQUIRED
REVOKED
EXPIRED

⸻

## 91. Reputation Reference

The Advertisement MAY include a current Reputation Profile reference.

The Profile itself remains canonical or canonically committed under RFC-0041.

⸻

## 92. Reputation Configuration Scope

Endpoint Reputation remains attached to Endpoint Identity and history.

Configuration-specific events SHOULD be visible where relevant.

A new Configuration Hash does not erase Endpoint history.

⸻

## 93. Reputation Display

Marketplace clients SHOULD display:

* Endpoint Profile State;
* relevant dimensions;
* Confidence;
* active flags;
* recent events;
* historical critical flags.

A single Overall Score SHALL NOT hide critical accounting or integrity problems.

⸻

## 94. New Endpoint

A new Endpoint may have:

Certification: CERTIFIED
Reputation Confidence: LOW

These states are compatible.

Certification is a bounded check.

Reputation requires history.

⸻

## 95. Known Control Group

Marketplace clients SHOULD expose known common-control relationships where canonically available.

Several Endpoints under one Known Control Group SHALL not be presented as independent operator diversity.

⸻

## 96. Operator Diversity

A Consumer MAY filter or rank by:

* unique Known Control Groups;
* Hypervisor diversity;
* Registry source diversity;
* Provider disclosure diversity.

Unknown ownership SHALL be marked unknown rather than independent.

⸻

## 97. Model Metadata

An Advertisement MAY include declared model metadata.

```yaml
declared_model_metadata:
  model_family:
  model_name:
  model_version:
  quantization:
  context_claim:
  deployment_claim:
  disclosure_level:
```

⸻

## 98. Model Metadata Is a Claim

Declared model metadata SHALL be marked as:

OPERATOR_DECLARED

unless supported by a stronger proof mechanism.

Endpoint Validation normally does not prove exact hidden model identity.

⸻

## 99. Hardware Metadata

An Advertisement MAY include declared hardware or acceleration metadata.

This information is advisory unless attested.

The Endpoint contract remains based on observable Capability behavior.

⸻

## 100. Performance Metadata

The operator MAY publish:

* expected latency;
* expected throughput;
* queue time;
* benchmark results;
* maximum concurrency.

These SHALL identify:

* measurement method;
* date;
* sample conditions;
* whether independently verified.

⸻

## 101. Performance Claim Expiration

Performance claims SHOULD expire or be periodically refreshed.

A benchmark from six software versions and two GPUs ago should not remain eternally young.

⸻

## 102. Advertisement Publication

An Advertisement SHALL be published as an immutable Registry Object.

A canonical commitment MAY be required depending on protocol policy.

⸻

## 103. Publication Operation

RFC-0059 SHOULD support:

ENDPOINT_ADVERTISEMENT_PUBLISH

The operation SHALL reference:

* Advertisement ID;
* Endpoint ID;
* Configuration Hash;
* validity;
* operator authorization;
* Registry object reference.

⸻

## 104. Publication Authorization

Only the authorized Endpoint operator or owner policy may publish an Advertisement.

A Registry cannot create an offer on behalf of an Endpoint merely because it indexed one.

⸻

## 105. Advertisement Update

An update creates a new Advertisement Object and a new publication operation.

The new version SHALL reference the previous version.

⸻

## 106. Scheduled Update

An operator MAY publish a future Advertisement version with valid_from.

This supports:

* future price changes;
* planned Capability upgrades;
* maintenance;
* policy changes.

⸻

## 107. Overlapping Advertisements

One Endpoint SHALL have at most one active primary Advertisement for one exact commercial offer scope unless multiple offers are explicitly distinguished.

⸻

## 108. Multiple Offers per Endpoint

An Endpoint MAY publish several concurrent offers only when each has a distinct Offer ID or clearly separated scope.

Examples include:

* public retail pricing;
* organization-specific pricing;
* reserved-capacity pricing;
* regional offer.

⸻

## 109. Offer Identity

Where multiple offers exist:

```yaml
endpoint_offer:
  offer_id:
  endpoint_id:
  access_scope:
  advertisement_id:
```

A Session SHALL bind to one exact Offer ID and Advertisement ID.

⸻

## 110. Advertisement Withdrawal

The operator MAY publish:

ENDPOINT_ADVERTISEMENT_WITHDRAW

Withdrawal SHALL identify:

* Advertisement ID;
* Endpoint ID;
* effective boundary;
* reason;
* operator signature.

⸻

## 111. Withdrawal Effect

After withdrawal:

* new Sessions SHALL not use the withdrawn Advertisement;
* existing accepted Sessions remain valid;
* historical queries remain possible;
* Registry Services preserve the withdrawal record.

⸻

## 112. Emergency Withdrawal

An authorized Service suspension or emergency action MAY make an Advertisement inactive even without operator withdrawal.

⸻

## 113. Endpoint Retirement

Retiring an Endpoint makes all its Advertisements inactive for new Sessions.

Historical objects remain available.

⸻

## 114. Advertisement Expiration

Every Advertisement SHALL expire.

Recommended maximum validity:

AdvertisementMaximumLifetime = 30 Epochs

The exact value is configurable.

⸻

## 115. Renewal

Renewal requires a new Advertisement version or an explicitly signed renewal object.

A stale Advertisement SHALL not remain active indefinitely because the operator forgot it existed.

⸻

## 116. Marketplace Registry Storage

Registry Services store Advertisement Objects under namespace:

marketplace

Full Registries SHALL retain:

* all active Advertisements;
* recent superseded versions;
* current withdrawals;
* referenced current policies.

Archive Registries SHOULD retain complete history.

⸻

## 117. Advertisement Replication

Advertisement Objects SHALL replicate under RFC-0061.

Replication preserves:

* Object ID;
* signatures;
* version chain;
* access class;
* expiration;
* canonical references.

⸻

## 118. Marketplace Query Interface

A Marketplace query MAY filter by:

* Capability ID;
* Capability version;
* features;
* input modalities;
* output modalities;
* price;
* Pricing Model;
* Accounting Mode;
* Certification state;
* Reputation state;
* Proxy class;
* availability;
* limits;
* access policy;
* Known Control Group;
* Data Handling properties.

⸻

## 119. Marketplace Query Object

```yaml
marketplace_query:
  query_id:
  capability_requirements:
  required_features:
  preferred_features:
  limit_requirements:
  price_constraints:
  accounting_constraints:
  certification_constraints:
  reputation_constraints:
  proxy_constraints:
  data_handling_constraints:
  availability_constraints:
  operator_diversity_constraints:
  pagination:
  query_version:
```

⸻

## 120. Query Results

A query result SHOULD include:

```yaml
marketplace_result:
  advertisement:
  endpoint_status:
  capability_status:
  certification_summary:
  reputation_summary:
  health_summary:
  price_summary:
  proxy_summary:
  data_handling_summary:
  freshness:
  registry_source:
  verification_references:
```

⸻

## 121. Query Result Verification

The Consumer SHALL verify:

* Advertisement signature;
* Endpoint registration;
* Configuration Hash;
* policy hashes;
* Capability Definition Hash;
* expiration;
* withdrawal state;
* Certification reference;
* Network Revision.

⸻

## 122. Registry Source Diversity

A Consumer MAY query several Registry Services.

Disagreement MAY indicate:

* synchronization lag;
* index error;
* missing replication;
* stale data;
* malicious omission.

Canonical object verification resolves factual conflicts where possible.

⸻

## 123. Query Freshness

Every result SHALL expose:

* Registry canonical height;
* Advertisement publication time;
* Advertisement expiration;
* Health timestamp;
* Certification freshness;
* Reputation Profile Epoch;
* known synchronization lag.

⸻

## 124. Stale Marketplace Result

A stale result MAY still be displayed for historical purposes.

It SHALL NOT be presented as currently available without warning.

⸻

## 125. Ranking

Ranking is a local derived process.

A ranking algorithm MAY use:

Capability match
Price
Certification
Reputation
Health
Latency
Accounting transparency
Proxy status
Privacy
Operator diversity
Consumer preferences

⸻

## 126. Ranking Disclosure

Marketplace clients SHOULD disclose the major factors in their ranking.

A paid placement, sponsorship or operator preference SHALL be labeled separately from protocol evidence.

⸻

## 127. No Canonical Best Endpoint

The protocol SHALL NOT declare one Endpoint as globally best.

The best choice depends on Consumer requirements.

A cheap Proxy-Opaque Endpoint may be appropriate for one user and unacceptable for another.

⸻

## 128. Local Ranking Formula

A client MAY calculate:

LocalRank
=
CapabilityMatch
×
PolicyCompatibility
×
LocalPreferenceFunction

The formula is not canonical.

⸻

## 129. Hard Filtering Before Ranking

Endpoints failing mandatory Consumer constraints SHOULD be removed before ranking.

Examples include:

* missing required feature;
* unacceptable Data Handling;
* unsupported Accounting Mode;
* expired Advertisement;
* revoked Certification where Certification is required;
* insufficient context limit.

⸻

## 130. Price Comparison

Marketplace clients SHALL compare prices only when units and pricing semantics are compatible.

Comparing:

1Q per request

with:

0.001Q per token

requires an explicit workload assumption.

⸻

## 131. Estimated Cost

A client MAY calculate estimated cost.

It SHALL disclose:

* assumptions;
* expected Request size;
* uncertain usage;
* possible minimums;
* maximum charge;
* whether upstream usage is opaque.

⸻

## 132. Maximum Cost

Where exact cost is uncertain, the Marketplace SHOULD emphasize:

Request Charge Ceiling
Maximum Session Charge
Minimum Deposit

These values are contractually meaningful.

⸻

## 133. Historical Pricing

Archive Registry data MAY support historical price analysis.

Historical prices SHALL not be used as current offers.

⸻

## 134. Consumer Preference Profile

A Marketplace client MAY maintain a local Consumer Preference Profile.

It MAY include:

* preferred price range;
* required Certification;
* preferred operators;
* privacy requirements;
* allowed Proxy classes;
* required features;
* preferred latency;
* risk tolerance.

This profile remains local unless the Consumer chooses to publish it.

⸻

## 135. Automatic Endpoint Selection

A Consumer agent MAY automatically select an Endpoint.

It SHALL preserve enough evidence to explain:

* which Advertisement was chosen;
* which constraints were applied;
* which ranking version was used;
* which estimated cost was considered.

⸻

## 136. Endpoint Selection Commitment

A Session Contract SHALL reference the exact Advertisement or Offer used.

This prevents later ambiguity over which terms were accepted.

⸻

## 137. Marketplace Recommendation Service

A third party MAY publish Recommendation Objects.

Recommendation Objects SHALL be:

* non-canonical;
* signed;
* versioned;
* source-attributed;
* distinct from Reputation Profiles.

⸻

## 138. Sponsored Placement

A Marketplace MAY display sponsored placements.

Sponsored status SHALL not alter:

* Certification;
* Reputation;
* canonical ranking;
* protocol eligibility.

It SHALL be visibly labeled by the Marketplace implementation.

⸻

## 139. Marketplace Abuse

The architecture SHALL account for:

* Advertisement spam;
* identity multiplication;
* stale offers;
* bait pricing;
* hidden fees;
* fake Certification references;
* Configuration mismatch;
* model-identity misrepresentation;
* self-generated Reputation;
* Registry index poisoning;
* paid-ranking concealment;
* false availability;
* Proxy nondisclosure.

⸻

## 140. Advertisement Spam

Spam protection MAY include:

* publication fee;
* minimum Endpoint Bond;
* maximum active offers per Endpoint;
* expiration;
* canonical Endpoint registration;
* rate limits;
* duplicate detection.

⸻

## 141. Publication Fee

A bounded Network Fee MAY apply to Advertisement publication.

The fee pays for canonical and Registry processing.

It does not purchase Marketplace priority.

⸻

## 142. Endpoint Bond

A future or active protocol MAY require an Endpoint Bond for public Marketplace listing.

The Bond SHALL NOT automatically be forfeited because users dislike the output.

Forfeiture requires an objective protocol rule.

⸻

## 143. Duplicate Advertisement

Identical active Advertisements for one Endpoint and Offer scope SHOULD be deduplicated.

Repeated publication SHALL not create additional Marketplace weight.

⸻

## 144. Identity Multiplication

Creating many Endpoints does not automatically create:

* higher ranking;
* greater Reputation;
* independent operator diversity;
* governance power;
* reward entitlement.

Known Control Group rules apply.

⸻

## 145. Bait Pricing

An Endpoint SHALL NOT advertise one mandatory price while applying hidden mandatory charges absent from the referenced Pricing Policy.

Objective bait-pricing evidence may affect:

* Reputation;
* Certification observations;
* suspension;
* penalties where defined.

⸻

## 146. Optional Add-Ons

Optional charges are permitted when:

* clearly disclosed;
* not mandatory for the advertised base function;
* explicitly accepted by the Consumer;
* bounded by Request and Session ceilings.

⸻

## 147. False Certification Reference

An Advertisement referencing:

* another Endpoint’s Certification;
* another Configuration Hash;
* expired Certification as current;
* revoked Certification as valid;

is invalid or misleading according to the exact failure class.

⸻

## 148. False Reputation Reference

The Advertisement SHALL reference the canonical Endpoint Reputation Profile.

It SHALL NOT substitute an unrelated operator or Hypervisor score as Endpoint Reputation.

⸻

## 149. False Availability

Repeated acceptance failure while advertising active availability MAY create:

* Health degradation;
* Reputation events;
* Triggered Validation;
* Marketplace warning.

A single failure does not prove deliberate deception.

⸻

## 150. Model Identity Misrepresentation

Because exact hidden model identity is difficult to prove, model claims SHALL be labeled as declarations.

Objective contradictory evidence MAY create a Reputation or disclosure violation.

Unverifiable suspicion alone SHALL not produce a severe penalty.

⸻

## 151. Proxy Nondisclosure

An Endpoint that materially routes data to an undeclared external upstream may violate:

* Proxy Declaration;
* Data Handling Policy;
* Endpoint Configuration;
* Certification assumptions.

Objective evidence may trigger suspension or penalty under applicable rules.

⸻

## 152. Registry Index Poisoning

Registry Services SHALL index only valid Advertisement Objects.

A malformed or unsigned object SHALL not appear as an active offer.

⸻

## 153. Marketplace Cache

Marketplace clients MAY cache query results.

Cached results SHALL preserve:

* Advertisement ID;
* expiration;
* source;
* freshness;
* canonical references.

⸻

## 154. Cache Invalidation

Cached Advertisement data SHOULD be invalidated by:

* later Advertisement version;
* withdrawal;
* expiration;
* Endpoint suspension;
* Capability retirement;
* Network Revision change.

⸻

## 155. Offline Marketplace View

A client MAY maintain an offline Marketplace index.

It SHALL clearly indicate its last synchronization point.

⸻

## 156. Privacy

Marketplace queries may reveal Consumer intent.

Clients MAY improve privacy through:

* querying several Registries;
* local indexes;
* broad queries followed by local filtering;
* relays;
* private Registry Services;
* Object ID retrieval.

⸻

## 157. Endpoint Privacy

An Endpoint MAY hide:

* physical Runtime address;
* exact Provider identity;
* internal topology;
* operator private metadata.

It SHALL still disclose Consumer-relevant behavior required by protocol.

⸻

## 158. Unlisted Endpoints

An unlisted Endpoint MAY still accept Sessions from Consumers who know its Advertisement ID or receive a private offer.

The same Session and accounting rules apply.

⸻

## 159. Marketplace and Validation

Validation assignments SHOULD reference the exact Advertisement and Configuration Hash active for the target Endpoint.

A Validation Report SHALL indicate whether the tested offer was:

* active;
* superseded;
* withdrawn during validation;
* configuration-changed.

⸻

## 160. Marketplace and Certification

When Certification state changes, Marketplace views SHOULD update promptly.

A stale Registry may temporarily show the old state, so clients SHALL verify freshness.

⸻

## 161. Marketplace and Reputation

Marketplace clients SHOULD combine:

* Advertisement;
* current Certification;
* current Reputation;
* current Health;
* historical critical flags.

No one signal replaces the others.

⸻

## 162. Marketplace and Governance

Standard Marketplace object schemas and required disclosures are governed by protocol.

Local rankings and presentation remain implementation-specific.

⸻

## 163. Marketplace and Protocol Upgrades

An upgrade MAY change:

* Advertisement schema;
* required fields;
* supported Capability versions;
* Accounting Modes;
* Proxy disclosure;
* Certification references.

Compatibility behavior SHALL be declared under RFC-0066.

⸻

## 164. Existing Sessions During Advertisement Upgrade

Existing Sessions remain bound to their accepted Advertisement and Session Contract.

A new Advertisement cannot rewrite them.

⸻

## 165. Network Revision

Advertisements SHALL bind to one Network Revision.

Old-revision Advertisements SHALL not be used to open Sessions on a new revision unless explicitly migrated.

⸻

## 166. Recovery After Network Revision

After Network Revision Recovery, operators SHOULD republish active Advertisements with:

* new Network Revision;
* current Configuration Hash;
* current policies;
* current Certification treatment.

⸻

## 167. Ledger Operations

RFC-0059 SHOULD support:

ENDPOINT_REGISTER
ENDPOINT_UPDATE
ENDPOINT_ADVERTISEMENT_PUBLISH
ENDPOINT_ADVERTISEMENT_WITHDRAW
ENDPOINT_OFFER_PUBLISH
ENDPOINT_OFFER_WITHDRAW
ENDPOINT_SUSPEND
ENDPOINT_REINSTATE
ENDPOINT_RETIRE

⸻

## 168. ENDPOINT_ADVERTISEMENT_PUBLISH

Creates the canonical reference to an Advertisement Object.

It SHALL verify:

* Endpoint existence;
* operator authorization;
* Advertisement signature;
* Configuration Hash;
* Capability Definition;
* validity period;
* policy references.

⸻

## 169. ENDPOINT_ADVERTISEMENT_WITHDRAW

Makes the targeted Advertisement inactive for new Sessions.

It does not delete the historical object.

⸻

## 170. ENDPOINT_UPDATE

Updates canonical Endpoint metadata that is not solely Advertisement content.

Material updates may require a new Configuration Hash and new Advertisement.

⸻

## 171. Epoch Integration

RFC-0048 SHOULD support Marketplace tasks including:

Expire Endpoint Advertisements
Activate Scheduled Advertisements
Apply Advertisement Withdrawals
Apply Endpoint Suspensions
Detect Configuration Mismatches
Update Marketplace Freshness Roots
Publish Capability Supply Metrics
Publish Pricing Distribution Metrics
Publish Operator Diversity Metrics

⸻

## 172. Marketplace Metrics

The network SHOULD publish aggregate metrics such as:

* active Endpoints by Capability;
* active Endpoints by Known Control Group;
* Certified Endpoint count;
* Proxy share;
* Accounting Mode distribution;
* price distribution;
* average Advertisement age;
* stale Advertisement rate;
* active Endpoint availability;
* Capability feature coverage;
* operator concentration.

⸻

## 173. No Demand Surveillance Requirement

The protocol SHALL NOT require public publication of individual Consumer searches or selection preferences.

Aggregate demand metrics MAY be produced voluntarily or through privacy-preserving methods later.

⸻

## 174. Error Codes

The MVP SHALL define at least:

MARKETPLACE_ADVERTISEMENT_NOT_FOUND
MARKETPLACE_ADVERTISEMENT_INVALID
MARKETPLACE_ADVERTISEMENT_EXPIRED
MARKETPLACE_ADVERTISEMENT_WITHDRAWN
MARKETPLACE_ADVERTISEMENT_SUPERSEDED
MARKETPLACE_ADVERTISEMENT_VERSION_CONFLICT
MARKETPLACE_ADVERTISEMENT_SIGNATURE_INVALID
MARKETPLACE_ENDPOINT_NOT_FOUND
MARKETPLACE_ENDPOINT_SUSPENDED
MARKETPLACE_ENDPOINT_RETIRED
MARKETPLACE_ENDPOINT_CONFIGURATION_MISMATCH
MARKETPLACE_CAPABILITY_NOT_FOUND
MARKETPLACE_CAPABILITY_VERSION_UNSUPPORTED
MARKETPLACE_CAPABILITY_DEFINITION_MISMATCH
MARKETPLACE_REQUIRED_FEATURE_MISSING
MARKETPLACE_PRICING_POLICY_INVALID
MARKETPLACE_ACCOUNTING_CONTRACT_INVALID
MARKETPLACE_SESSION_POLICY_INVALID
MARKETPLACE_DATA_POLICY_INVALID
MARKETPLACE_PROXY_DECLARATION_INVALID
MARKETPLACE_CERTIFICATION_REFERENCE_INVALID
MARKETPLACE_REPUTATION_REFERENCE_INVALID
MARKETPLACE_QUERY_INVALID
MARKETPLACE_QUERY_LIMIT_EXCEEDED
MARKETPLACE_QUERY_CURSOR_INVALID
MARKETPLACE_QUERY_STALE
MARKETPLACE_ACCESS_DENIED

⸻

## 175. Idempotency

The following SHALL be idempotent:

* Advertisement publication with the same Advertisement ID;
* withdrawal submission;
* offer publication;
* Registry ingestion;
* query by exact Object ID;
* Endpoint retirement;
* scheduled activation processing.

Conflicting content under one Advertisement ID SHALL be rejected.

⸻

## 176. Conformance Testing

Marketplace implementations SHALL be tested for:

* valid Advertisement publication;
* invalid signature rejection;
* invalid Configuration Hash;
* expired Advertisement;
* withdrawal;
* superseding versions;
* scheduled activation;
* multiple Offers;
* Capability filtering;
* feature filtering;
* pricing display;
* Accounting Mode display;
* Certification mismatch;
* stale Health;
* Proxy disclosure;
* Data Handling filtering;
* Known Control Group aggregation;
* Network Revision mismatch.

⸻

## 177. Reference Marketplace Harness

The AiDN project SHOULD provide a Marketplace Conformance Harness capable of:

* publishing Advertisement versions;
* querying active offers;
* simulating withdrawal;
* testing stale Registry results;
* comparing policy hashes;
* validating Certification references;
* testing pricing models;
* testing required features;
* testing access policies;
* verifying local ranking separation.

⸻

## 178. MVP Requirements

The MVP SHALL implement:

* immutable Advertisement Objects;
* Advertisement version chains;
* exact Endpoint Configuration binding;
* one primary Capability per offer;
* feature and limit profiles;
* Pricing Policies;
* Accounting Contracts;
* Session Policies;
* Failure Policies;
* Data Handling Policies;
* Proxy declarations;
* active, expired, withdrawn and superseded states;
* Advertisement expiration;
* public and restricted offers;
* Certification references;
* Reputation references;
* Health freshness;
* Marketplace queries;
* filtering;
* local non-canonical ranking;
* price summaries;
* Request and Session maximum exposure display;
* Known Control Group disclosure;
* Registry replication;
* historical Advertisement retention;
* Network Revision binding.

⸻

## 179. Deferred Features

The MVP MAY postpone:

* decentralized order-book matching;
* auction pricing;
* reserved-capacity markets;
* futures for compute capacity;
* subscription plans;
* prepaid Consumer accounts;
* automatic multi-Endpoint splitting;
* encrypted Marketplace search;
* private information retrieval;
* zero-knowledge pricing;
* cross-network Endpoint discovery;
* protocol-native sponsored placement;
* insurance-backed Endpoint offers;
* automatic price optimization;
* demand-based protocol pricing.

⸻

## 180. Open Protocol Parameters

The following remain configurable:

* Advertisement maximum lifetime;
* publication fee;
* maximum active Offers per Endpoint;
* maximum policy size;
* query result limit;
* query cursor lifetime;
* Health freshness threshold;
* pricing display precision;
* scheduled activation delay;
* withdrawal effective delay;
* public Marketplace Bond;
* Marketplace history retention;
* performance-claim lifetime;
* maximum extension-object size.

⸻

## 181. Identity Invariants

Endpoint
≠
Advertisement
Endpoint
≠
Runtime
Endpoint
≠
Provider
Advertisement
≠
Certification
Advertisement
≠
Reputation
Marketplace Ranking
≠
Canonical Protocol State

⸻

## 182. Advertisement Invariants

* Every Advertisement is immutable.
* Every update creates a new version.
* One active Advertisement binds to one Configuration Hash.
* An expired Advertisement cannot open a new Session.
* Withdrawal does not alter existing Sessions.
* Historical offers remain auditable.
* Registry storage does not create operator authorization.
* Advertisement signatures remain attributable.

⸻

## 183. Pricing Invariants

Advertised Pricing Policy
Binds New Sessions Only
Completed Work
Cannot Be Repriced Retroactively
RequestCharge
≤
RequestChargeCeiling
ProviderPayment
≤
MaximumSessionCharge
Hidden Mandatory Fees
Are Not Valid Pricing Components

⸻

## 184. Accounting Invariants

* Accounting Mode is explicit.
* Unknown upstream usage remains unknown.
* Estimated tokens are labeled non-authoritative.
* Fixed-price offers may report usage without billing by usage.
* Accounting Contract is bound before execution.
* Marketplace cost estimates disclose assumptions.
* Maximum exposure is displayed separately from estimated cost.

⸻

## 185. Capability Invariants

* Every offer exposes one primary Capability.
* Capability Definition Hash is exact.
* Required features cannot be silently omitted.
* Material Capability changes require a new Configuration Hash.
* Retired Capability versions cannot open new Sessions.
* Model metadata does not replace Capability identity.

⸻

## 186. Certification and Reputation Invariants

* Certification applies only to its Configuration Hash.
* Certification does not prove permanent availability.
* Reputation remains attached to Endpoint history.
* New Configuration does not erase Reputation.
* New Endpoint begins with low Reputation Confidence.
* Advertisement cannot substitute operator Reputation for Endpoint Reputation.
* Critical historical flags remain visible.

⸻

## 187. Proxy Invariants

* Proxy status is disclosed.
* Proxy-Opaque accounting is explicit.
* Internal retries do not create undeclared charges.
* Dynamic upstream variation is disclosed.
* External data handling is disclosed.
* Outer Session maximum remains binding.
* Hidden upstream identity is not presented as proven.

⸻

## 188. Registry Invariants

* Marketplace objects are content-addressed Registry Objects.
* Registry indexes are non-canonical.
* Query freshness is visible.
* Stale results do not override canonical withdrawal.
* Replication preserves Advertisement identity and signatures.
* A Registry cannot publish an offer on behalf of an unauthorized operator.
* Historical Advertisement chains remain verifiable.

⸻

## 189. Security Invariants

* Advertisement publication is authorized.
* Policy references are hash-bound.
* Configuration mismatch is detectable.
* Fake Certification references are rejected.
* Hidden mandatory charges are prohibited.
* Access policies are enforced.
* Network Revision replay is rejected.
* Local ranking cannot modify canonical Reputation.
* Sponsored placement cannot impersonate protocol ranking.
* Endpoint retirement does not erase historical evidence.

⸻

## 190. Design Invariants

* Marketplace discovery is distributed.
* Endpoint offers are explicit and versioned.
* Commercial terms are accepted before execution.
* Marketplace search is separate from Endpoint trust.
* Certification, Reputation and Health remain distinct.
* Consumers may choose different ranking priorities.
* Operators compete through price, features, limits, privacy and reliability.
* Registry Services provide discovery without becoming commercial authorities.
* Historical offer terms remain recoverable for Session disputes.
* The protocol lets markets compare offers, but does not pretend that putting five numbers into a weighted sum reveals the objectively best model in the universe.

Комментарии к новой редакции

1. Advertisement является оффером, а не карточкой Endpoint

Теперь Advertisement включает не просто:

Endpoint ID
Capability
Price

а полный набор ссылок на условия:

Capability Definition
Feature Profile
Limit Profile
Pricing Policy
Accounting Contract
Session Policy
Failure Policy
Data Handling Policy
Proxy Declaration

Это позволяет Consumer заранее понять, что именно он принимает.

⸻

2. Advertisement immutable

Изменение цены не редактирует старый объект.

Публикуется:

Advertisement v1: 1Q
Advertisement v2: 2Q

Session, открытая по v1, продолжает использовать 1Q.

Session по v2 использует 2Q.

Это особенно важно для споров и Forced Settlement. Без исторической версии оператор мог бы показать текущую цену и заявить, что она всегда такой и была. Очень по-человечески, но плохо проверяется.

⸻

3. Offer и Endpoint можно разделить

Один Endpoint может иметь несколько коммерческих предложений:

Public Offer
Organization Offer
Reserved Capacity Offer
Private Offer

При этом Capability и Runtime остаются теми же.

Session привязывается к конкретному:

Endpoint ID
+
Offer ID
+
Advertisement ID

⸻

4. Marketplace не имеет единого глобального рейтинга

Один Consumer хочет:

самый дешёвый Endpoint

Другой:

только direct local execution

Третий:

Certified Endpoint с прозрачным accounting

Четвёртый:

максимальный context независимо от цены

Одна каноническая формула не сможет корректно представить все предпочтения.

Поэтому протокол публикует проверяемые данные, а ranking остаётся локальным.

⸻

5. Hard filter должен выполняться до ranking

Если Consumer требует:

tool_calls = REQUIRED

Endpoint без Tool Calls не должен просто опуститься на несколько позиций.

Он должен быть исключён.

То же касается:

* Data Handling;
* Capability version;
* Accounting Mode;
* context;
* Certification;
* side effects.

Ranking применяется только к совместимым предложениям.

⸻

6. Цена без Accounting Contract бессмысленна

Запись:

0.001Q за token

не говорит:

* чей tokenizer;
* какая версия;
* кто считает;
* что делать с Proxy;
* считается ли system prompt;
* считаются ли retries.

Поэтому price всегда идёт вместе с Accounting Contract.

⸻

7. Estimated cost и Maximum cost разделены

Для Proxy или usage-based Endpoint Consumer может не знать точную итоговую цену.

Marketplace показывает:

Estimated cost: около 3Q
Maximum Request Charge: 5Q
Maximum Session Charge: 20Q

Именно maximum является контрактным ограничением.

Estimate является полезным предположением, которому всё же не следует вручать ключи от кошелька.

⸻

8. Certification проверяется по Configuration Hash

Нельзя показывать старую Certification после изменения:

* модели;
* Proxy;
* Capability version;
* Accounting Mode;
* Data Handling;
* Runtime.

Marketplace обязан сравнить:

Advertisement Configuration Hash
=
Certification Configuration Hash

⸻

9. Model name остаётся декларацией

Оператор может написать:

declared_model: Qwen 27B

Но Marketplace должен показать:

Operator declared

а не:

Network verified model

Существующая Validation подтверждает наблюдаемое поведение, а не точные веса внутри чужого сервера.

⸻

10. Proxy disclosure становится частью оффера

Consumer должен видеть:

DIRECT
PROXY_DISCLOSED
PROXY_OPAQUE_UPSTREAM
DYNAMIC_PROXY

Особенно важно раскрывать:

* уходит ли запрос наружу;
* известны ли usage tokens;
* может ли upstream меняться;
* может ли измениться data location;
* как оплачиваются retries.

⸻

11. Availability schedule и current Health разделены

Advertisement может говорить:

работает 24/7

Но текущий Health может быть:

OAuth expired
Runtime unavailable
Queue full

Marketplace показывает оба значения.

Обещание работать круглосуточно не делает Endpoint доступным силой оптимизма.

⸻

12. Advertisement обязательно истекает

Без expiration в Marketplace останутся тысячи мёртвых Endpoints, операторы которых давно:

* выключили сервер;
* потеряли ключи;
* забыли проект;
* сменили цену;
* отправились строить следующую распределённую сеть.

Поэтому Advertisement требует регулярного обновления.

⸻

13. Sponsored placement не должно маскироваться под ranking

Marketplace может зарабатывать на рекламе или приоритетном размещении.

Но такое размещение должно быть отдельно отмечено и не изменять:

* Reputation;
* Certification;
* protocol eligibility;
* canonical data.

⸻

14. Что теперь нужно синхронизировать

После принятия RFC-0049 v0.2:

* RFC-0037: Settlement должен ссылаться на Advertisement и Offer, принятые Session;
* RFC-0041: Reputation Profile должен предоставлять Marketplace Summary;
* RFC-0044: Session Contract должен хранить advertisement_id и offer_id;
* RFC-0045: Feature и Limit Profiles должны совпадать со схемами Advertisement;
* RFC-0046: Full Registry retention должен включать активные Advertisements и связанные политики;
* RFC-0048: добавить Marketplace Epoch Tasks из раздела 171;
* RFC-0051: Accounting Contract должен быть полноценным Registry Object;
* RFC-0053: Runtime не публикует цену напрямую, цена принадлежит Endpoint offer;
* RFC-0058: Known Control Groups используются для отображения operator diversity;
* RFC-0059: добавить Marketplace Operations из раздела 167;
* RFC-0063: Proxy Declaration и Failover Policy становятся обязательными Marketplace objects;
* RFC-0065: Certification state должен обновлять Marketplace views, но не изменять Advertisement;
* RFC-0066: Network Revision Recovery требует перепубликации Advertisements.

Из исходного списка теперь восстановлены и обновлены:

RFC-0039
RFC-0040
RFC-0042
RFC-0044
RFC-0045
RFC-0046
RFC-0049

Следующая разумная работа уже не восстановление отдельного документа, а сверка терминологии и операций между ними.
