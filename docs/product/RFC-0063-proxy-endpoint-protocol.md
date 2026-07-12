# RFC-0063 Proxy Endpoint Protocol

Status: `Draft`

Version: `0.1`

Depends on:

- `ECO-0000 Economic Principles`
- `ECO-0003 Validation Economics`
- `RFC-0036 AiDN Ledger State Machine`
- `RFC-0037 Settlement Engine`
- `RFC-0041 Reputation Profile Engine`
- `RFC-0042 Hypervisor Network Protocol`
- `RFC-0044 Session Protocol`
- `RFC-0045 Capability Architecture`
- `RFC-0049 Distributed Marketplace and Advertisement Registry`
- `RFC-0051 Usage Reporting and Verification Protocol`
- `RFC-0053 Capability Runtime Specification`
- `RFC-0054 Capability Runtime Protocol`
- `RFC-0057 Validation Report Specification`
- `RFC-0059 Ledger Operation Catalog`
- `RFC-0060 Session Failure, Recovery and Forced Settlement`
- `RFC-0064 Validation Assignment, Concealed Session and Escrow Protocol`
- `RFC-0065 Endpoint Certification Derivation and Lifecycle Protocol`

## 1. Purpose

This document defines Proxy Endpoints in AiDN.

It specifies:

- Proxy Endpoint types;
- upstream service relationships;
- upstream disclosure;
- Capability compatibility;
- pricing without authoritative upstream usage;
- `PROXY_OPAQUE` accounting;
- OAuth-connected upstream services;
- upstream quotas and rate limits;
- retries and failover;
- Proxy chains;
- cycle prevention;
- aggregation across several upstream Providers;
- Session recovery;
- failure handling;
- Usage Reporting;
- Certification effects;
- Reputation attribution;
- operator responsibility;
- security and credential isolation.

## 2. Proxy Endpoint Definition

A Proxy Endpoint is an AiDN Endpoint whose requests are executed wholly or partly by another service.

The upstream service MAY be:

- another AiDN Endpoint;
- a proprietary API;
- an OAuth-connected service;
- a local agent connected to a remote Provider;
- a cloud model API;
- another Proxy Runtime;
- a service outside AiDN.

The Proxy Endpoint remains the Consumer-facing protocol counterparty.

## 3. Core Responsibility Principle

The Proxy Endpoint operator is responsible for the complete Consumer-facing Session.

The Consumer has no protocol relationship with the hidden upstream Provider unless the Endpoint explicitly operates in a disclosed pass-through mode.

The Proxy operator remains responsible for:

- published pricing;
- Session acceptance;
- result delivery;
- Usage Reporting;
- retry behavior;
- upstream failure handling;
- Deposit limits;
- refunds;
- Certification claims;
- credential security;
- applicable upstream permissions.

The phrase "the upstream did it" SHALL not erase the Proxy operator's protocol obligations.

## 4. Proxy Is Not a Lower-Trust Endpoint Class

A Proxy Endpoint MAY be fully legitimate and Certified.

Proxy execution is not automatically inferior to local execution.

A Proxy Endpoint may provide:

- access consolidation;
- protocol translation;
- load balancing;
- Provider failover;
- OAuth integration;
- specialized tooling;
- remote agent access;
- uniform AiDN Session behavior.

The Endpoint SHALL accurately disclose what it can and cannot observe.

## 5. Proxy Endpoint Types

The protocol defines:

`DIRECT_EXTERNAL_PROXY`

`AIDN_ENDPOINT_PROXY`

`AGGREGATING_PROXY`

`FAILOVER_PROXY`

`TRANSFORMING_PROXY`

`AGENT_PROXY`

`CHAINED_PROXY`

## 6. DIRECT_EXTERNAL_PROXY

Routes requests to one external upstream service.

Examples:

- OpenAI-compatible API;
- proprietary image-generation API;
- hosted speech service;
- remote inference API.

## 7. AIDN_ENDPOINT_PROXY

Routes requests to another AiDN Endpoint.

The downstream Consumer interacts only with the outer Proxy Endpoint.

The inner AiDN Session remains an internal implementation detail unless disclosed.

## 8. AGGREGATING_PROXY

Selects among several upstream services.

Selection MAY depend on:

- availability;
- price;
- latency;
- Capability support;
- quota;
- geography;
- operator policy;
- request class.

## 9. FAILOVER_PROXY

Uses a primary upstream and one or more fallback services.

Fallback behavior SHALL be declared because it may alter:

- output;
- latency;
- model behavior;
- accounting;
- privacy;
- data location.

## 10. TRANSFORMING_PROXY

Modifies requests or responses.

Examples include:

- prompt templates;
- format conversion;
- image resizing;
- tool-call translation;
- policy filtering;
- response normalization;
- context injection;
- audio transcoding.

Material transformations are part of Endpoint behavior and SHALL be included in the Endpoint Configuration Hash.

## 11. AGENT_PROXY

Exposes an agent or application through AiDN.

The upstream may be:

- Codex through OAuth;
- a remote coding agent;
- a browser agent;
- an automation platform;
- a private enterprise agent;
- an MCP-connected service.

The Proxy operator SHALL define billable units that do not depend on unavailable upstream token counts.

## 12. CHAINED_PROXY

A Chained Proxy routes through another Proxy.

Example:

```text
Consumer
    ->
Proxy A
    ->
Proxy B
    ->
External Provider
```

Proxy chains are permitted only under bounded and cycle-safe rules.

## 13. Proxy Declaration

Every Proxy Endpoint SHALL declare:

```yaml
proxy_declaration:
  proxy_endpoint_type:
  upstream_disclosure_mode:
  upstream_accounting_visibility:
  upstream_failover_supported:
  request_transformation:
  response_transformation:
  chain_depth_limit:
  data_handling_policy_hash:
  proxy_policy_version:
```

## 14. Upstream Disclosure Modes

The protocol defines:

- `FULLY_DISCLOSED`
- `CATEGORY_DISCLOSED`
- `OPAQUE_UPSTREAM`
- `DYNAMIC_UPSTREAM_SET`

## 15. FULLY_DISCLOSED

The Endpoint discloses:

- upstream Provider identity;
- upstream service or model where known;
- upstream region where relevant;
- fallback Providers;
- material data-processing behavior.

Disclosure remains informational unless independently verifiable.

## 16. CATEGORY_DISCLOSED

The Endpoint discloses only a category.

Examples:

- remote commercial LLM;
- OAuth-connected coding agent;
- external image API;
- private enterprise inference service.

## 17. OPAQUE_UPSTREAM

The Proxy does not disclose the specific upstream Provider.

It SHALL still disclose:

- that execution is proxied;
- which accounting fields are unavailable;
- data-retention policy;
- maximum request cost;
- failure policy;
- whether upstream switching may occur.

## 18. DYNAMIC_UPSTREAM_SET

The Proxy may select among changing Providers.

It SHALL disclose:

- selection policy;
- whether Provider switching can occur within one Session;
- whether model behavior may vary;
- whether data may cross jurisdictions;
- whether Session affinity is preserved.

## 19. Prohibition on False Locality Claims

A Proxy Endpoint SHALL NOT claim local execution when execution is materially remote.

Permitted claims include:

- "request accepted by a local AiDN Hypervisor";
- "execution Provider is undisclosed";
- "upstream location may vary."

The Endpoint SHALL distinguish between:

local protocol termination

and:

local computation

## 20. Capability Binding

A Proxy Endpoint SHALL publish one Capability ID.

The Proxy Runtime is responsible for translating that Capability into upstream operations.

The upstream service need not natively implement AiDN protocol.

The Proxy SHALL preserve the declared Consumer-facing Capability contract.

## 21. Capability Compatibility

The Proxy SHALL verify that every selected upstream can satisfy:

- request schema;
- response schema;
- content types;
- output limits;
- cancellation semantics where declared;
- Usage Reporting requirements;
- Session deadline;
- safety policy;
- artifact delivery rules.

An upstream that cannot satisfy the accepted contract SHALL not be selected.

## 22. Endpoint Configuration Hash

The Proxy Endpoint Configuration Hash SHALL commit to all execution-relevant Proxy behavior.

This includes:

- Proxy type;
- Capability version;
- upstream selection policy;
- disclosed upstream set;
- material request transformations;
- material response transformations;
- accounting mode;
- pricing unit definitions;
- retry policy;
- failover policy;
- Session affinity;
- data-processing policy;
- maximum chain depth.

## 23. Upstream Change

An upstream change requires a new Endpoint Configuration Hash when it may materially alter:

- output behavior;
- Capability compatibility;
- privacy;
- accounting;
- latency guarantees;
- data retention;
- model class;
- failure behavior.

A temporary failover already permitted by the active policy does not require a configuration update.

## 24. Commercial-Only Upstream Change

A change to the Proxy operator's private upstream acquisition cost does not automatically change Endpoint Configuration.

It may require a Pricing Policy update.

The Consumer-facing contract remains authoritative.

## 25. Proxy Pricing Principle

The Proxy operator sets the Consumer-facing price.

The price does not need to equal the upstream provider's internal cost.

The Proxy operator MAY account for:

- subscription costs;
- quota limits;
- infrastructure;
- retry risk;
- transformation services;
- operational overhead;
- scarcity;
- expected failure rate;
- Session reservation;
- business margin.

AiDN does not require the Proxy to prove its internal cost.

## 26. No Required Fiat Conversion

Proxy pricing SHALL be expressed in Q according to the published Pricing Policy.

The protocol does not require:

- fiat-denominated accounting;
- disclosure of upstream subscription price;
- proof of operator profit margin;
- real-time external currency conversion.

The operator assumes the risk that its Q pricing may be economically inaccurate.

## 27. Pricing Under Unknown Upstream Usage

When upstream token or unit usage is unavailable, the Proxy SHALL NOT invent exact usage.

The Proxy SHALL use one or more observable or fixed Consumer-facing units.

Examples include:

- per request
- per request class
- per completed task
- per active execution minute
- per delivered artifact
- per delivered audio minute
- per generated image
- per bounded agent run
- per reserved Session interval

## 28. PROXY_OPAQUE Accounting

A Proxy uses:

`PROXY_OPAQUE`

when authoritative upstream usage is unavailable or inaccessible.

Examples include:

- OAuth service with no token report;
- consumer subscription interface;
- remote agent that exposes no usage API;
- opaque third-party proxy;
- upstream billing hidden from the operator.

## 29. PROXY_OPAQUE Usage Report

A Usage Report SHALL include:

```yaml
proxy_opaque_usage:
  accounting_mode: PROXY_OPAQUE
  upstream_usage_available: false
  upstream_usage_source: unavailable
  authoritative_input_tokens: null
  authoritative_output_tokens: null
  estimated_input_tokens:
  estimated_output_tokens:
  estimates_billable: false
  observable_billable_units:
  request_class:
  active_execution_time:
  delivered_artifacts:
  completion_status:
```

Unknown values SHALL be represented as unknown, not zero.

## 30. Estimated Tokens

A Proxy MAY estimate token counts for diagnostics.

Estimated tokens:

- are not authoritative;
- SHALL identify the estimation tokenizer or method;
- SHALL not be billed as exact upstream usage;
- MAY support statistical comparison;
- MAY help detect abnormal reporting.

## 31. Proxy Pricing Models

The initial supported Proxy pricing models are:

- `FIXED_PER_REQUEST`
- `FIXED_PER_REQUEST_CLASS`
- `FIXED_PER_COMPLETED_TASK`
- `OBSERVABLE_UNIT`
- `ACTIVE_EXECUTION_TIME`
- `HYBRID_BOUNDED`
- `SUBSCRIPTION_CAPACITY_ALLOCATION`

## 32. FIXED_PER_REQUEST

Every accepted request has a fixed price.

The price SHALL be known before execution.

The policy SHALL define failure and cancellation charges.

## 33. FIXED_PER_REQUEST_CLASS

Requests are placed into predefined classes.

| Class | Description |
| --- | --- |
| `Small` | bounded short request |
| `Standard` | ordinary request |
| `Large` | larger context or output |
| `Extended` | long-running bounded task |

Classification SHALL be deterministic from pre-execution request properties.

## 34. FIXED_PER_COMPLETED_TASK

The Consumer pays only when the declared completion condition is reached.

The Endpoint SHALL define:

- task boundary;
- completion evidence;
- failure handling;
- cancellation handling;
- partial-result policy.

## 35. OBSERVABLE_UNIT

Pricing uses units observable by both parties.

Examples:

- delivered bytes;
- audio duration;
- image count;
- video duration;
- artifact count;
- tool-call count where visible.

## 36. ACTIVE_EXECUTION_TIME

Pricing is based on measured active execution time.

The Proxy SHALL distinguish:

- queue time;
- idle time;
- upstream waiting time;
- active execution;
- retry time.

The Pricing Policy SHALL state which intervals are billable.

## 37. HYBRID_BOUNDED

Combines:

- fixed request fee;
- observable units;
- active execution time;
- strict maximum charge.

Every component SHALL be declared before Session acceptance.

## 38. SUBSCRIPTION_CAPACITY_ALLOCATION

A Proxy operator MAY allocate part of an external subscription to AiDN Sessions.

Pricing MAY be based on:

- reserved Session slot;
- bounded request count;
- active execution time;
- daily or Epoch quota;
- task class.

The Proxy SHALL not claim authoritative per-token upstream cost when no such cost exists.

## 39. Maximum Charge

Every Proxy request SHALL have a maximum Consumer charge known before execution.

```text
RequestCharge
<=
DeclaredMaximumRequestCharge
```

The maximum remains binding even when:

- upstream cost is higher than expected;
- retries occur;
- fallback Provider is more expensive;
- the operator mispriced the request.

Unexpected upstream cost is Proxy operator risk.

## 40. Session Deposit

The Session Deposit SHALL cover:

- accepted request exposure;
- permitted reservation fees;
- declared retry charges;
- Network Fees;
- applicable cancellation charges.

The Proxy SHALL not exceed the finalized Deposit.

## 41. Upstream Cost Risk

The Consumer pays according to the AiDN Endpoint contract, not according to hidden upstream billing.

Therefore:

```text
ConsumerCharge
!=
UnverifiedUpstreamCost
```

The Proxy operator absorbs:

- upstream price changes;
- quota overages;
- subscription changes;
- undisclosed Provider charges;
- failed retry costs;
- external currency movement.

## 42. OAuth-Connected Upstream

A Proxy MAY connect to an upstream service using OAuth.

Examples include:

- coding agents;
- cloud AI assistants;
- enterprise applications;
- productivity services;
- user-authorized external tools.

OAuth credentials SHALL remain Runtime-private.

## 43. OAuth Credential Isolation

OAuth credentials SHALL NOT be exposed to:

- Consumers;
- Registry Services;
- Marketplace;
- Ledger;
- unrelated Runtimes;
- Validation Reports;
- remote Hypervisors.

The Proxy Runtime MAY expose only credential status.

## 44. OAuth Status

The Runtime MAY report:

- `VALID`
- `EXPIRING`
- `EXPIRED`
- `REAUTH_REQUIRED`
- `REVOKED`
- `UPSTREAM_SCOPE_INSUFFICIENT`

Credential status changes MAY affect Endpoint availability.

## 45. OAuth Scope

The Proxy operator SHALL obtain only the scopes required for the declared Endpoint behavior where practical.

The Endpoint SHALL disclose when requests may:

- access external repositories;
- modify files;
- send messages;
- invoke tools;
- create irreversible side effects.

## 46. OAuth Expiration During Session

If OAuth expires during an active request:

- the Runtime SHALL stop unsafe retries;
- the request enters upstream failure handling;
- partial-result rules apply;
- the Consumer is not charged for unavailable hidden usage;
- the Proxy MAY attempt reauthentication only within Session limits;
- the failure is attributed to the Proxy Endpoint.

## 47. Manual Reauthentication

Manual operator action MAY be required.

The Proxy SHALL not hold a Consumer Session indefinitely while waiting for a human to click an OAuth consent screen.

The Session Policy SHALL define a bounded recovery window.

## 48. Upstream Quotas

A Proxy SHALL track known upstream limits where available.

Examples include:

- request count;
- token quota;
- daily quota;
- concurrent sessions;
- rate limits;
- subscription caps;
- storage limits;
- tool-call limits.

## 49. Unknown Quota

If an upstream quota is unknown, the Proxy SHALL disclose that availability may be interrupted by undisclosed upstream limits.

Unknown quota SHALL not be represented as unlimited capacity.

## 50. Capacity Advertisement

The Proxy SHOULD publish conservative capacity.

Declared capacity MAY consider:

- known quota;
- historical throttling;
- current queue;
- number of OAuth accounts;
- fallback availability;
- subscription limits;
- safety margin.

The Proxy SHALL avoid advertising capacity it cannot reasonably deliver.

## 51. Rate-Limit Failure

When upstream rate limits are reached:

- new requests MAY be queued if policy permits;
- active requests MAY pause only within deadlines;
- fallback MAY be used if declared;
- undisclosed retry charges SHALL not apply;
- the Consumer MAY cancel according to Session Policy.

## 52. Upstream Failure Classes

Proxy upstream failures include:

- `UPSTREAM_UNAVAILABLE`
- `UPSTREAM_RATE_LIMITED`
- `UPSTREAM_AUTH_EXPIRED`
- `UPSTREAM_QUOTA_EXHAUSTED`
- `UPSTREAM_TIMEOUT`
- `UPSTREAM_PROTOCOL_CHANGED`
- `UPSTREAM_INVALID_RESPONSE`
- `UPSTREAM_CONTENT_REJECTED`
- `UPSTREAM_TASK_CANCELLED`
- `UPSTREAM_UNKNOWN_FAILURE`

## 53. Consumer-Facing Failure Classes

The Proxy SHALL map upstream failures into stable AiDN failure classes.

The Consumer SHALL not be required to understand every proprietary Provider error.

The original upstream error MAY be included as non-authoritative diagnostic metadata after secret removal.

## 54. Failure Pricing

Every Proxy Endpoint SHALL publish a failure-pricing policy.

Supported policies include:

- `NO_CHARGE_ON_FAILURE`
- `BASE_ATTEMPT_FEE`
- `OBSERVABLE_WORK_ONLY`
- `PARTIAL_RESULT_ONLY`
- `ACTIVE_TIME_BOUNDED`

## 55. NO_CHARGE_ON_FAILURE

No Provider payment applies when the declared completion condition is not reached.

Network Fees remain applicable.

## 56. BASE_ATTEMPT_FEE

A small fixed fee MAY apply after the Proxy validly begins upstream execution.

The fee SHALL be declared before acceptance.

It SHALL not depend on unverifiable upstream usage.

## 57. OBSERVABLE_WORK_ONLY

The Consumer pays only for observable delivered work.

Examples:

- delivered audio seconds;
- delivered output chunks;
- valid artifacts;
- completed visible tool actions.

## 58. PARTIAL_RESULT_ONLY

A partial result is billable only when:

- it is delivered;
- it is independently identifiable;
- the policy defines partial pricing;
- the Consumer accepted the policy.

## 59. ACTIVE_TIME_BOUNDED

The Consumer pays for measured active Proxy execution time up to a declared limit.

Queue time and operator reauthentication time SHALL not be billed unless explicitly accepted.

## 60. Retry Policy

The Proxy SHALL publish:

```yaml
proxy_retry_policy:
  maximum_attempts:
  retryable_failure_classes:
  retry_delay:
  retry_charge_policy:
  same_upstream_retry:
  alternate_upstream_retry:
  consumer_confirmation_required:
```

## 61. Retry Transparency

The Consumer SHALL know whether retries may:

- increase latency;
- change upstream Provider;
- alter output behavior;
- consume additional billable units;
- repeat external side effects.

## 62. Retry Charges

Retries SHALL not create hidden charges.

Permitted models include:

- all retries included in fixed price;
- one bounded attempt fee per declared attempt;
- observable work only;
- no charge for failed retries.

The maximum charge remains binding.

## 63. Idempotent Requests

The Proxy SHALL use upstream idempotency controls where available.

For requests with external side effects:

- retries SHALL be disabled by default;
- or use stable idempotency keys;
- or require Consumer approval.

## 64. Non-Idempotent Side Effects

Examples include:

- sending email;
- committing code;
- creating tickets;
- triggering deployment;
- purchasing external services;
- publishing content.

The Proxy SHALL not retry such operations blindly.

## 65. Upstream Failover

Failover MAY occur only when permitted by the active Proxy policy.

Failover SHALL preserve:

- Capability contract;
- request limits;
- maximum Consumer charge;
- privacy policy;
- side-effect safety;
- Session deadline.

## 66. Failover Disclosure

The Proxy policy SHALL declare whether failover can change:

- model family;
- Provider;
- data region;
- retention policy;
- output quality;
- content moderation;
- latency.

Material undisclosed failover is a configuration violation.

## 67. Session Affinity

Stateful Sessions SHOULD remain bound to one upstream.

Examples include:

- chat conversations;
- coding agents;
- workspaces;
- provider-side threads;
- tool sessions.

Switching upstream mid-Session requires compatible state transfer or explicit Consumer-visible reset.

## 68. Stateless Requests

Stateless requests MAY be routed independently when:

- the Endpoint policy allows it;
- outputs remain contract-compatible;
- accounting remains consistent;
- privacy rules remain satisfied.

## 69. Upstream Session State

The Proxy Runtime may maintain:

- upstream thread ID;
- provider session token;
- conversation context;
- workspace ID;
- task ID;
- cached request history.

These identifiers SHALL remain private unless disclosure is required.

## 70. Proxy Session Recovery

After Proxy Runtime restart, recovery SHALL attempt to restore:

- AiDN Session state;
- upstream session reference;
- request state;
- last Usage Report sequence;
- delivered artifact hashes;
- retry state;
- quota state.

## 71. Unrecoverable Upstream State

If the upstream session cannot be resumed:

- the Proxy SHALL not silently begin a different task as though nothing happened;
- the request becomes failed or requires Consumer-approved restart;
- accepted prior usage remains payable according to policy;
- undisclosed upstream work remains non-billable.

## 72. Proxy Runtime Replacement

A replacement Runtime may resume a Proxy Session only when it can securely import:

- upstream credentials or authorized references;
- Session context;
- Usage history;
- request state;
- retry state.

Credential transfer SHALL follow Runtime security rules.

## 73. Proxy Chain Rules

Proxy chains are permitted only when:

- every hop preserves the declared Capability;
- chain depth remains within limit;
- cycle protection succeeds;
- maximum charge remains bounded;
- failure ownership remains clear;
- privacy policy remains compatible.

## 74. Maximum Proxy Depth

Every Proxy Endpoint SHALL publish or obey:

`MaximumProxyDepth`

Recommended MVP default:

```text
MaximumProxyDepth = 3
```

A request exceeding the maximum SHALL be rejected.

## 75. Proxy Path Descriptor

Every Proxy-to-Proxy request SHALL carry a protected path descriptor.

```yaml
proxy_path:
  origin_session_id:
  visited_endpoint_commitments:
  current_depth:
  maximum_depth:
  path_nonce:
```

The descriptor MAY conceal exact Endpoint identities from the outer Consumer while still supporting cycle detection.

## 76. Cycle Prevention

A Proxy SHALL reject a request when:

- its own Endpoint commitment already appears in the path;
- the path nonce is reused inconsistently;
- maximum depth is exceeded;
- path integrity fails.

## 77. Hidden Cycles

A Proxy using an external upstream may be unable to know whether the upstream routes back into AiDN.

Where exact path transparency is unavailable:

- the Proxy SHALL use timeouts;
- request IDs;
- recursion limits;
- duplicate-content detection;
- maximum external call count.

Perfect cycle detection is not guaranteed across opaque external systems.

## 78. Chain Accounting

Each AiDN Proxy hop MAY open its own internal Session.

However, the outer Consumer pays only according to the outer Endpoint contract.

Internal Proxy costs do not automatically propagate after execution.

Each Proxy operator bears its own downstream cost risk.

## 79. No Cascading Unbounded Charges

A Proxy chain SHALL not produce an unbounded Consumer liability.

```text
OuterConsumerCharge
<=
OuterDeclaredMaximumCharge
```

regardless of inner chain depth or cost.

## 80. Proxy Aggregation

An Aggregating Proxy MAY select upstreams dynamically.

The selection function MAY use:

- health;
- latency;
- cost;
- quota;
- Capability class;
- request size;
- consumer policy;
- privacy constraints.

## 81. Deterministic vs Private Selection

The upstream-selection algorithm MAY remain private.

The Endpoint SHALL still disclose material Consumer-facing behavior.

The Consumer need not know the operator's complete routing strategy.

## 82. Upstream Quality Variation

When upstreams may produce materially different outputs, the Proxy SHALL disclose:

- dynamic Provider selection;
- possible output variation;
- whether model identity is stable;
- whether Session affinity is used.

## 83. Upstream Diversity Claim

A Proxy MAY claim Provider diversity only when it actually maintains independent usable upstreams.

The claim MAY be validated through:

- observed failover;
- configuration evidence;
- operator disclosure;
- Validation Reports.

It is not cryptographically proven merely by declaration.

## 84. Data Handling Policy

Every Proxy Endpoint SHALL publish a Data Handling Policy.

It SHALL describe:

- whether Session data leaves the Hypervisor;
- upstream disclosure class;
- possible retention;
- logging;
- jurisdiction where known;
- training-use uncertainty;
- external tool access;
- sensitive-data restrictions.

## 85. Consumer Data Consent

The Consumer accepts the Data Handling Policy during Session negotiation.

The Proxy SHALL not route data through a materially less private upstream than the accepted policy permits.

## 86. Sensitive Data

A Proxy MAY reject sensitive workloads it cannot safely handle.

The Proxy SHALL not imply private local execution when data is sent to an external commercial service.

## 87. Upstream Terms and Authorization

The Proxy operator is responsible for ensuring that upstream use is permitted.

This MAY include:

- API terms;
- OAuth terms;
- subscription limits;
- redistribution rights;
- automation permissions;
- resale restrictions;
- organizational policies.

AiDN Certification does not certify legal permission to resell or proxy an upstream service.

## 88. Protocol Enforcement Limit

The AiDN protocol cannot fully verify upstream contract compliance.

The Endpoint operator SHALL not represent protocol Certification as legal authorization.

Confirmed service abuse or access revocation may affect Endpoint Reputation and availability.

## 89. Credential Sharing Prohibition

The Proxy SHALL not expose upstream credentials to Consumers.

A Consumer SHALL not receive:

- API keys;
- OAuth refresh tokens;
- session cookies;
- upstream account credentials;
- remote signer secrets.

## 90. Consumer Credential Delegation

A future Proxy MAY operate using Consumer-provided upstream credentials.

Such mode SHALL be explicitly declared.

The MVP SHOULD avoid storing long-lived Consumer credentials.

## 91. Usage Reporting Responsibility

The Proxy Endpoint SHALL always publish an AiDN Usage Report.

This remains true when upstream usage is unknown.

The report SHALL distinguish:

- observable values;
- measured local values;
- estimated values;
- unavailable values;
- billable values.

## 92. Proxy Usage Report Fields

```yaml
proxy_usage_report:
  session_id:
  request_id:
  proxy_endpoint_id:
  accounting_mode:
  request_class:
  accepted_maximum_charge:
  locally_observed_input:
  locally_observed_output:
  active_execution_time:
  queue_time:
  retry_count:
  upstream_switch_count:
  upstream_usage_available:
  upstream_usage_reference:
  estimated_upstream_usage:
  delivered_artifacts:
  completion_status:
  billable_units:
  cumulative_charge:
  signature:
```

## 93. Usage Verification

Proxy usage verification MAY validate:

- request count;
- request class;
- active execution time;
- delivered artifacts;
- response byte count;
- retry count;
- cumulative maximum-charge compliance.

It generally cannot validate hidden upstream token usage when none is reported.

## 94. Statistical Verification

The network MAY statistically compare similar Proxy Endpoints.

Examples include:

- reported execution time;
- estimated tokens;
- request-class charges;
- failure rates;
- output sizes;
- latency.

Statistical anomalies may trigger Validation or Reputation review.

They SHALL not alone prove fraud.

## 95. Proxy Validation

A Proxy Endpoint is validated through observable behavior.

Validation MAY examine:

- protocol compatibility;
- request execution;
- output usefulness;
- Usage Reporting;
- declared Proxy mode;
- failover behavior where observable;
- failure pricing;
- maximum-charge compliance;
- data-policy disclosure;
- accounting limitations.

## 96. Validation Does Not Reveal Upstream Truth

Validation SHALL NOT claim proof of upstream identity unless independently attested.

A Validator MAY report:

- "upstream identity undisclosed";
- "behavior changed between requests";
- "OAuth failure was observed";
- "token usage unavailable";
- "failover appears to occur."

## 97. Proxy Certification

A Proxy Endpoint MAY be:

`CERTIFIED`

`CERTIFIED_WITH_OBSERVATIONS`

`DEGRADED`

`CERTIFICATION_REVOKED`

just like another Endpoint.

`PROXY_OPAQUE` accounting alone SHALL not prevent Certification.

It SHOULD usually be shown as an observation.

## 98. Certification Observation

A typical Certification note MAY state:

The Endpoint successfully provided the declared Capability.
Execution is proxied through an undisclosed upstream.
Authoritative upstream token usage is unavailable.
Billing uses fixed request classes.

## 99. Configuration Change and Certification

The following changes normally require revalidation:

- upstream category change;
- material Provider change;
- accounting-mode change;
- transformation change;
- data-policy change;
- failover-policy change;
- maximum Proxy depth change;
- Session-affinity change.

## 100. Proxy Reputation

Proxy Reputation MAY include:

- request success rate;
- upstream failure rate;
- OAuth failure rate;
- quota exhaustion rate;
- failover success;
- maximum-charge compliance;
- Usage Report consistency;
- recovery success;
- result-delivery reliability;
- data-policy violations;
- undisclosed behavior changes.

## 101. Failure Attribution

For the Consumer-facing Session, upstream failure is attributed to the Proxy Endpoint.

The detailed cause MAY be:

- `UPSTREAM_EXTERNAL`
- `UPSTREAM_AUTH`
- `UPSTREAM_QUOTA`
- `UPSTREAM_RATE_LIMIT`
- `UPSTREAM_PROTOCOL`
- `UPSTREAM_UNKNOWN`

This allows fair diagnostics without transferring responsibility away from the Proxy.

## 102. External Correlated Failure

When many Proxy Endpoints using one upstream fail simultaneously, the event MAY be classified as correlated external failure.

This may reduce current Health more strongly than long-term misconduct Reputation.

The Proxy remains responsible for the failed Consumer Session settlement.

## 103. Repeated Upstream Failure

Repeated upstream failure may cause:

- lower Availability;
- lower Reputation;
- `CERTIFIED_WITH_OBSERVATIONS`;
- `DEGRADED`;
- Triggered Validation;
- removal from Marketplace recommendations.

## 104. Hidden Upstream Change

A material undisclosed upstream change MAY cause:

- Configuration Hash mismatch;
- Certification invalidation;
- Reputation reduction;
- `REVALIDATION_REQUIRED`;
- penalty when signed declarations were knowingly false.

## 105. Proxy Session Settlement

Ordinary Proxy Sessions use ordinary Session Settlement.

Provider Payment is calculated from:

- accepted Proxy Pricing Policy;
- observable or fixed billable units;
- Last Accepted Checkpoint;
- maximum charge;
- failure policy.

Unknown upstream usage SHALL not create additional payment.

## 106. Proxy Forced Settlement

`RFC-0060` applies.

The default payable baseline is:

`Last Accepted Proxy Usage Checkpoint`

plus deterministic authorized charges.

Unacknowledged opaque upstream usage SHALL not be paid.

## 107. Validation Session Exception

When a Proxy Endpoint processes a concealed Validation Session under `RFC-0064`:

```text
Endpoint Payment = 0Q
```

even when the Proxy incurred upstream cost.

The Proxy operator accepts this possibility as part of Certification participation.

## 108. Proxy Validation Cost Risk

A Certified Proxy Endpoint bears the upstream cost of bounded validation requests.

The protocol SHALL limit this exposure through:

- maximum validation request count;
- maximum output size;
- Capability Guidelines;
- execution-time limits;
- prohibited unrelated work;
- Assignment Performance Bonds for Validators.

## 109. High-Cost Proxy Validation

A Proxy Endpoint whose upstream cost makes ordinary concealed validation impractical MAY:

- publish strict validation workload limits;
- use a Capability-specific validation profile;
- remain uncertified;
- request a future specialized validation policy.

It SHALL not receive ordinary Certification while refusing all meaningful validation.

## 110. Proxy Endpoint Withdrawal

If upstream access becomes permanently unavailable, the operator SHOULD withdraw the Endpoint.

Leaving a known-dead Endpoint active may reduce Reputation and trigger Certification degradation.

## 111. Temporary Upstream Maintenance

A Proxy MAY enter:

`DEGRADED`

`TEMPORARILY_UNAVAILABLE`

`DRAINING`

according to its policy.

Active Sessions follow recovery or forced settlement rules.

## 112. Upstream Protocol Change

When an external Provider changes its API or behavior:

- the Runtime SHALL detect incompatibility where possible;
- new Sessions SHALL pause;
- Endpoint Configuration MAY require update;
- Certification MAY become `REVALIDATION_REQUIRED`;
- active Sessions follow `RFC-0060`.

## 113. Proxy Runtime Health

The Proxy Runtime SHOULD report:

```yaml
proxy_runtime_health:
  upstream_connectivity:
  credential_status:
  quota_status:
  rate_limit_status:
  current_provider:
  failover_readiness:
  active_sessions:
  queued_requests:
  recent_upstream_failures:
```

Sensitive upstream identity MAY remain concealed according to policy.

## 114. Marketplace Disclosure

Marketplace presentation SHOULD include:

- Proxy status;
- disclosure mode;
- Accounting Mode;
- authoritative usage availability;
- pricing unit;
- failover support;
- data-handling summary;
- Certification observations;
- upstream variability warning;
- maximum charge.

## 115. No "Exact Tokens" Badge

A Proxy Endpoint SHALL not receive an "exact token accounting" indicator when upstream tokens are unavailable.

Local token estimates do not qualify.

## 116. Proxy Advertisement

A Proxy Advertisement SHALL include:

```yaml
proxy_advertisement:
  endpoint_id:
  capability_id:
  proxy_type:
  upstream_disclosure_mode:
  accounting_mode:
  pricing_policy_hash:
  failure_policy_hash:
  retry_policy_hash:
  failover_policy_hash:
  data_handling_policy_hash:
  maximum_charge_policy:
  certification_reference:
```

## 117. Ledger Objects

Proxy-specific data MAY be represented through:

- Endpoint Configuration;
- Pricing Policy;
- Accounting Contract;
- Session Policy;
- Advertisement;
- Usage Reports;
- Session Settlements;
- Validation Reports;
- Reputation events.

A separate Proxy registration operation is not required in the MVP.

## 118. Runtime Protocol Integration

`RFC-0054` SHALL support Proxy-specific runtime events including:

- `UPSTREAM_AVAILABLE`
- `UPSTREAM_DEGRADED`
- `UPSTREAM_UNAVAILABLE`
- `UPSTREAM_AUTH_EXPIRED`
- `UPSTREAM_RATE_LIMITED`
- `UPSTREAM_QUOTA_EXHAUSTED`
- `UPSTREAM_SWITCHED`
- `PROXY_RETRY_STARTED`
- `PROXY_RETRY_COMPLETED`
- `PROXY_RETRY_FAILED`

## 119. Session Protocol Integration

`RFC-0044` SHALL permit Proxy Session negotiation to include:

- Proxy declaration;
- Accounting Mode;
- fixed or observable units;
- maximum request charge;
- failure pricing;
- retry policy;
- failover disclosure;
- data-handling policy;
- Session affinity.

## 120. Ledger Operation Catalog Amendments

`RFC-0059` does not require a new mandatory Proxy operation.

However, Endpoint operations SHALL permit Proxy-specific hashes:

- `proxy_policy_hash`;
- `retry_policy_hash`;
- `failover_policy_hash`;
- `data_handling_policy_hash`.

`ENDPOINT_UPDATE` SHALL invalidate Certification when these execution-relevant policies change materially.

## 121. Error Codes

The MVP SHALL define at least:

- `PROXY_UPSTREAM_UNAVAILABLE`
- `PROXY_UPSTREAM_AUTH_EXPIRED`
- `PROXY_UPSTREAM_REAUTH_REQUIRED`
- `PROXY_UPSTREAM_RATE_LIMITED`
- `PROXY_UPSTREAM_QUOTA_EXHAUSTED`
- `PROXY_UPSTREAM_TIMEOUT`
- `PROXY_UPSTREAM_PROTOCOL_CHANGED`
- `PROXY_UPSTREAM_INVALID_RESPONSE`
- `PROXY_FAILOVER_UNAVAILABLE`
- `PROXY_FAILOVER_POLICY_VIOLATION`
- `PROXY_RETRY_LIMIT_EXCEEDED`
- `PROXY_RETRY_UNSAFE`
- `PROXY_CHAIN_DEPTH_EXCEEDED`
- `PROXY_CYCLE_DETECTED`
- `PROXY_PATH_INVALID`
- `PROXY_ACCOUNTING_UNAVAILABLE`
- `PROXY_MAXIMUM_CHARGE_EXCEEDED`
- `PROXY_DATA_POLICY_VIOLATION`
- `PROXY_SESSION_CONTEXT_LOST`
- `PROXY_CONFIGURATION_CHANGED`

## 122. Idempotency

The Proxy SHALL ensure that repeated AiDN messages do not create duplicate upstream execution.

`EXECUTE_REQUEST` replay SHALL:

- return existing request state;
- use upstream idempotency key where available;
- avoid duplicate side effects;
- avoid duplicate billing.

## 123. Evidence Preservation

The Proxy SHOULD preserve:

- request hash;
- transformed request hash;
- upstream request reference;
- response hash;
- transformed response hash;
- retry history;
- Provider switch history;
- Usage Report sequence;
- artifact hashes;
- failure evidence.

Sensitive upstream content MAY remain private.

## 124. Transformation Auditability

When request or response transformation is material, the Proxy SHOULD record:

- transformation policy version;
- input hash;
- transformed-input hash;
- raw-output hash;
- delivered-output hash.

The transformation code itself need not be public unless policy requires it.

## 125. Consumer Visibility

The Consumer SHOULD be able to determine:

- whether execution is proxied;
- what billing units apply;
- maximum charge;
- whether exact upstream usage is known;
- whether upstream may change;
- whether data leaves AiDN infrastructure;
- what happens on failure.

The Consumer need not know the Proxy operator's confidential internal costs or credentials.

## 126. Proxy Sybil Considerations

Creating many Proxy Endpoints SHALL not create infrastructure rewards.

Proxy Endpoints primarily earn through ordinary Sessions.

Endpoint count SHALL not increase:

- Faucet claims beyond one per Hypervisor;
- Consensus rewards;
- Registry rewards;
- Validation rewards.

## 127. Self-Dealing

A Proxy operator MAY route through another Endpoint it controls.

Such routing remains valid but SHALL not be treated as independent demand or independent reliability evidence.

Known Control Group relationships MAY be used for analytics and anti-gaming.

## 128. Proxy Economic Attack: Underpricing

A Proxy operator may price below actual upstream cost.

This is permitted.

The operator bears the loss.

The protocol SHALL not rescue the Proxy through extra Mint or hidden Consumer charges.

## 129. Proxy Economic Attack: Overpricing

A Proxy operator may charge a high fixed price.

This is permitted if disclosed.

Consumers choose whether to use the Endpoint.

Marketplace competition and Reputation provide the primary constraint.

## 130. Proxy Economic Attack: Fake Token Usage

A Proxy SHALL not bill fabricated exact tokens under `PROXY_OPAQUE`.

Billing SHALL use declared fixed or observable units.

Fabricated signed usage may trigger:

- Session mismatch;
- Reputation reduction;
- Certification degradation;
- penalty where objectively proven.

## 131. Proxy Economic Attack: Retry Inflation

A Proxy SHALL not create repeated hidden retries to multiply charges.

Retry count and charge policy SHALL be visible in Usage Reports.

Maximum charge remains binding.

## 132. Proxy Economic Attack: Hidden Provider Downgrade

A Proxy may secretly switch to a cheaper or weaker upstream.

Protection includes:

- Validation;
- output observations;
- configuration declarations;
- Session Reputation;
- Triggered Validation;
- material-change requirements.

Hidden downgrade is not always objectively provable, but behavior changes remain observable.

## 133. Proxy Economic Attack: Credential Farming

An operator SHALL not use AiDN Consumers to harvest credentials or authorization.

Consumer-provided authorization flows, if introduced, SHALL use explicit scoped consent.

The MVP SHOULD not permit arbitrary credential prompts inside Proxy Sessions.

## 134. Security Boundary

A compromised Proxy Runtime SHALL not be able to:

- access Wallet private keys;
- mint Q;
- modify Ledger state;
- exceed Session Deposit;
- expose unrelated OAuth credentials;
- access unrelated Endpoint Sessions;
- rewrite finalized Usage Reports.

## 135. Remote Upstream Security

The Proxy SHOULD enforce:

- encrypted upstream transport;
- certificate validation;
- credential rotation;
- request size limits;
- response size limits;
- timeout bounds;
- content validation;
- secret redaction;
- audit logging.

## 136. Privacy Invariants

- Proxy status is disclosed.
- Exact upstream identity may remain opaque.
- Unknown usage remains unknown.
- OAuth credentials remain Runtime-private.
- Consumer data policy is accepted before execution.
- Materially weaker privacy requires a policy update.
- Validation does not magically reveal hidden upstream identity.

## 137. Economic Invariants

```text
Consumer Charge
<=
Declared Maximum Charge
Unknown Upstream Usage
!=
Billable Exact Usage
Upstream Cost
Does Not Automatically Determine Consumer Charge
Failed Hidden Retry
Does Not Create Undisclosed Charge
Internal Proxy Chain Cost
Does Not Create Unbounded Outer Consumer Liability
Validation Session Endpoint Payment = 0Q
```

## 138. Session Invariants

- The Proxy remains the Consumer-facing Provider.
- Every request has one stable Request ID.
- Duplicate requests do not create duplicate upstream work.
- Stateful Sessions preserve upstream affinity or expose reset.
- Maximum charge remains binding through retries and failover.
- Unknown upstream usage does not enter Forced Settlement.
- Upstream failure does not erase accepted completed work.
- External side effects are not retried blindly.

## 139. Certification Invariants

- Proxy Endpoints may be Certified.
- Proxy execution alone is not a failure.
- `PROXY_OPAQUE` accounting may produce Certification observations.
- Certification binds to exact Proxy behavior and policies.
- Material upstream-policy changes require reevaluation.
- Certification does not prove upstream model identity.
- Repeated hidden behavior changes may degrade Certification.

## 140. MVP Requirements

The MVP SHALL implement:

- Proxy Endpoint declaration;
- Direct External Proxy;
- AiDN Endpoint Proxy;
- Aggregating or Failover Proxy;
- `PROXY_OPAQUE` accounting;
- fixed and observable pricing units;
- maximum request charge;
- upstream failure classes;
- retry policy;
- failover disclosure;
- OAuth status handling;
- quota and rate-limit handling;
- Session affinity;
- Proxy Session recovery;
- chain-depth limit;
- cycle detection for AiDN Proxy chains;
- Data Handling Policy;
- Proxy Usage Reports;
- validation support;
- Marketplace disclosure;
- configuration-change Certification effects;
- Proxy Reputation metrics.

## 141. Deferred Features

The MVP MAY postpone:

- Consumer-owned upstream credentials;
- anonymous upstream attestation;
- zero-knowledge Provider disclosure;
- cross-chain Proxy settlement;
- decentralized Proxy routing markets;
- automatic upstream price oracles;
- cryptographic proof of proprietary upstream usage;
- multi-operator revenue sharing;
- nested paid sub-Session disclosure;
- private Provider-set commitments;
- legal-policy enforcement;
- federated OAuth credential vaults.

## 142. Open Protocol Parameters

The following remain configurable:

- Maximum Proxy Depth;
- retry limits;
- retry delays;
- Proxy recovery timeout;
- OAuth reauthentication timeout;
- upstream quota safety margin;
- maximum upstream switches per request;
- active execution measurement rules;
- request-class definitions;
- Proxy Validation workload limits;
- high-cost Proxy Certification rules;
- data-policy classes;
- Provider-switch disclosure threshold;
- statistical anomaly thresholds.

## 143. Design Invariants

- A Proxy Endpoint is a first-class AiDN Endpoint.
- The Proxy operator remains responsible to the Consumer.
- Proxy status SHALL be disclosed.
- Specific upstream identity MAY remain undisclosed.
- The protocol does not require internal cost transparency.
- The operator chooses Q pricing.
- Unknown upstream token usage is never represented as exact.
- Consumer billing uses fixed or observable accepted units.
- Maximum charges remain binding.
- Retries and failover are policy-controlled.
- Proxy chains are bounded and cycle-protected.
- OAuth and upstream credentials remain private.
- Upstream failures are Consumer-facing Proxy failures.
- Certification validates observable Proxy behavior.
- Validation Sessions are non-compensated even when the Proxy incurs upstream cost.
- Internal Proxy complexity does not alter Ledger safety.
