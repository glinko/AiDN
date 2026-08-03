# RFC-0051 Usage Reporting, Accounting Evidence and Verification Protocol

Status: `Draft`

Version: `0.8`

Revision note: accepted Usage chain heads feed RFC-0037 Request Settlement
Records; Usage remains evidence and never redirects Endpoint Payment.

Supersedes:

- `RFC-0051 Version 0.7`

Depends on:

- `RFC-0036 AiDN Ledger State Machine`
- `RFC-0037 Settlement Engine`
- `RFC-0041 Reputation Profile Engine`
- `RFC-0042 AiDN Hypervisor Network Protocol and Dispatcher Architecture`
- `RFC-0045 Capability Architecture`
- `RFC-0046 AiDN Registry Architecture`

Extended by:

- `RFC-0044 AiDN Session Protocol`
- `RFC-0049 Distributed Marketplace and Endpoint Advertisement Registry`
- `RFC-0053 AiDN Capability Runtime Specification`
- `RFC-0054 AiDN Capability Runtime Protocol`
- `RFC-0056 AiDN Provider Plugin Runtime Interface`
- `RFC-0059 Ledger Operation Catalog`
- `RFC-0060 Session Failure, Recovery and Forced Settlement`
- `RFC-0063 Proxy Endpoint Protocol`
- `RFC-0064 Validation Assignment, Concealed Session and Escrow Protocol`
- `RFC-0066 Protocol Upgrade and Emergency Recovery`

## 1. Purpose

The Usage Reporting and Verification Protocol defines how billable usage is:

- reported by an Endpoint;
- optionally verified by a Consumer;
- acknowledged during a Session;
- statistically evaluated by the network;
- applied during Settlement.

Every accepted Request SHALL produce at least one Usage Report envelope. Every
terminal Request SHALL produce one Final Usage Report. A report containing only
honest `UNAVAILABLE` or `NOT_APPLICABLE` dimensions remains a valid protocol
object when the accepted Accounting Contract permits that limitation.

An RFC-0053 Runtime Usage Profile SHALL bind to Runtime ID and Runtime
Configuration Hash. Each dimension independently declares unit, availability,
authority, cumulative behavior, Request/Session scope, billing eligibility and
limitations. Unknown values remain unknown; a missing Provider metric SHALL NOT
be converted to zero.

RFC-0054 transports, but does not redefine, the RFC-0051 Usage Report object.
`RUNTIME_USAGE_REPORT` SHALL carry Runtime ID and Generation,
Configuration Hash, Endpoint/Session/Request identity, Usage sequence, previous
Report Hash, per-dimension authority, provider attempts, cumulative/terminal
flags, Report Hash and persistent Runtime authentication. Acknowledgment states
are `ACCEPTED`, `DUPLICATE`, `REJECTED`, `CONFLICT` and `OUT_OF_SEQUENCE`.
Transport delivery acknowledgment SHALL NOT replace this Usage acknowledgment.

Independent verification of reported usage is desirable but is not universally possible.

The protocol therefore distinguishes between:

- mandatory Usage Reporting;
- direct deterministic verification;
- verification of observable quantities;
- Provider-supplied metering;
- opaque proxy accounting;
- fixed-price accounting;
- statistical usage evaluation.

The protocol SHALL never represent unverifiable usage as independently verified.

## 2. Design Principles

Usage Reporting is mandatory.

Independent Usage Verification is desirable but not mandatory unless explicitly required by the Capability or Endpoint policy.

An Endpoint SHALL declare its Accounting Contract before a Session begins.

The Consumer SHALL know:

- which units are billable;
- how those units are measured;
- which measurements are independently verifiable;
- which measurements depend on the Provider;
- which measurements are unavailable;
- the applicable pricing;
- the maximum permitted economic exposure.

Unknown usage SHALL remain explicitly unknown.

Estimated usage SHALL not be presented as measured usage.

Settlement SHALL use the Accounting Contract accepted when the Session opened.

## 3. Participants

Every Session has two accounting participants.

### 3.1 Consumer Hypervisor

The Consumer Hypervisor uses the remote Endpoint.

It MAY independently observe or measure:

- submitted input;
- received output;
- request count;
- character count;
- byte count;
- artifact count;
- image dimensions;
- audio duration;
- video duration;
- Session duration;
- idle periods;
- other Capability-specific quantities.

The Consumer is not required to reproduce all Provider-side measurements.

### 3.2 Provider Hypervisor

The Provider Hypervisor hosts or publishes the Endpoint.

It SHALL produce signed Usage Reports through the corresponding Capability Runtime.

The Hypervisor-to-Runtime message flow carrying those reports is defined separately by `RFC-0054`.

The Provider remains responsible for:

- correct reporting;
- report-chain integrity;
- adherence to the published Accounting Contract;
- enforcement of Session limits;
- enforcement of maximum charges.

For Proxy Endpoints, the hidden upstream service has no protocol relationship with the Consumer.

The Proxy Endpoint remains the Provider from the AiDN protocol perspective.

## 4. Usage Authority

Neither the Consumer nor the Provider is universally authoritative.

The authoritative accounting basis depends on the declared Accounting Mode.

Examples:

- deterministic token counts may be independently reproduced;
- image dimensions may be directly observed;
- proprietary API usage may only be reported by the Provider;
- opaque proxy usage may be unavailable entirely;
- fixed-price requests may not require resource measurement.

The Settlement Engine SHALL preserve the Accounting Mode and verification status of every billable unit.

### 4.1 Usage Authority Classes

Every reported or discoverable usage dimension SHALL identify one authority
class when a value exists:

- `AUTHORITATIVE_PROVIDER`: an upstream Provider is the contractually accepted
  source;
- `DETERMINISTIC_LOCAL`: both parties can reproduce the value from a fixed
  local rule;
- `OBSERVABLE_LOCAL`: the value is measured from Consumer-visible or
  Hypervisor-observable work;
- `ESTIMATED`: the value is informative and non-authoritative;

Authority is declared per dimension, not once for an entire Endpoint. A Runtime
Adapter may report authoritative output tokens and observable execution time in
the same Request.

An `ESTIMATED` value SHALL NOT be promoted to exact billable usage without an
Accounting Contract rule that independently makes the calculation
deterministic.

### 4.2 Usage Availability

Every dimension has one Availability state:

- `AVAILABLE`: a usable value exists;
- `PARTIAL`: only part of relevant execution was observed;
- `UNAVAILABLE`: no defensible value exists;
- `NOT_APPLICABLE`: the dimension does not apply.

`UNAVAILABLE` and `NOT_APPLICABLE` carry no numeric value and no Authority
Class. Zero remains a measurement and SHALL NOT represent unavailable data.
`PARTIAL` carries a value and Authority but SHALL NOT be treated as complete.

## 5. Usage Reporting Obligation

Every accepted Request SHALL produce authenticated Usage Reports. Report Types
are `INTERIM`, `CHECKPOINT`, `FINAL`, `CORRECTION`, `RECOVERY` and
`DIAGNOSTIC`.

Every terminal Request SHALL produce exactly one accepted Final Report for its
terminal chain position. Runtime Result finalization SHALL fail while the
matching Final Report is missing, rejected, conflicting or out of sequence.

Each Usage Report SHALL identify:

- Session;
- Endpoint;
- Capability;
- pricing version;
- Accounting Contract version;
- Accounting Mode;
- measurement source;
- billable units;
- cumulative usage;
- request-level usage where applicable;
- sequence number;
- previous report hash;
- Provider signature.

The canonical report also binds Runtime ID and Generation, Runtime
Configuration Hash, Endpoint Configuration Hash, Request ID, Accounting
Contract Hash, Request state, Provider attempts, observation interval,
limitations and immutable Report Hash.

Failure to issue required Usage Reports MAY:

- pause execution;
- stop new requests;
- terminate the Session;
- reduce operational Reputation Metrics.

### 5.1 Runtime Usage Profile

Every Runtime publishes a hash-bound Usage Profile containing Runtime ID and
Generation, Runtime Configuration reference, Adapter version, expected
Availability and Authority per dimension, cumulative semantics, Request/Session
scope, billing eligibility, retry reporting and Provider-attempt reporting.

`RuntimeConfigurationHash` commits to `UsageProfileHash`. To avoid an impossible
hash cycle, `UsageProfileHash` commits to profile semantics but excludes the
back-reference `runtime_configuration_hash`. The Profile object still carries
that exact Configuration Hash, and admission validates both directions.

Before execution the Hypervisor validates the accepted Accounting Contract
against the active Runtime Usage Profile. A required unavailable dimension with
no declared fallback rejects the Request before substantial execution.

## 6. Accounting Modes

Each billable unit SHALL declare one Accounting Mode.

The initial Accounting Modes are:

- `DETERMINISTIC`
- `OBSERVABLE`
- `PROVIDER_METERED`
- `FIXED_PRICE`
- `PROXY_OPAQUE`
- `HYBRID`

A single Endpoint MAY use different modes for different units.

Example:

```yaml
accounting:
  input_tokens:
    mode: provider_metered
  output_tokens:
    mode: provider_metered
  idle_time:
    mode: observable
  request_fee:
    mode: fixed_price
```

## 7. Deterministic Accounting

`DETERMINISTIC` means that both parties can reproduce the same billable value using the published Accounting Contract.

Examples include:

- token counts using a published tokenizer and chat template;
- request count;
- input byte count;
- image count;
- decoded image dimensions;
- artifact hash;
- output character count.

The Endpoint SHALL publish all required:

- algorithms;
- schemas;
- versions;
- templates;
- tokenizer artifacts;
- serialization rules;
- rounding rules.

Deterministic values SHOULD require exact equality unless the Capability defines an explicit tolerance.

## 8. Observable Accounting

`OBSERVABLE` means that the Consumer can directly measure the quantity without reproducing Provider internals.

Examples include:

- returned image count;
- output dimensions;
- input audio duration;
- output audio duration;
- decoded video duration;
- returned file size;
- visible tool-call count;
- Session reservation time;
- idle time.

Observable values MAY use deterministic tolerance rules for:

- media padding;
- codec framing;
- fractional frame boundaries;
- timing granularity.

## 9. Provider-Metered Accounting

`PROVIDER_METERED` means that usage is reported by:

- the Endpoint;
- its Capability Runtime;
- or an upstream Provider.

The Consumer cannot necessarily reproduce the measurement independently.

Examples include:

- proprietary model APIs;
- proprietary tokenizers;
- hidden chat templates;
- upstream cached-token accounting;
- upstream usage reports;
- closed reasoning-token accounting.

Provider-metered usage is permitted.

It SHALL NOT be represented as independently verified.

The Endpoint SHALL identify the measurement source.

Example:

```yaml
measurement_source:
  type: upstream_api
  provider_reference: opaque-provider-reference
  report_hash: sha256:...
```

## 10. Fixed-Price Accounting

`FIXED_PRICE` applies a predetermined price to an observable event or accepted task class.

Examples include:

- one accepted request;
- one completed request;
- one generated image;
- one transcription;
- one Session reservation;
- one fixed work package.

Internal resource consumption does not affect the price.

The Endpoint SHALL publish:

- the completion condition;
- failure-pricing policy;
- applicable limits;
- maximum charge.

## 11. Opaque Proxy Accounting

`PROXY_OPAQUE` applies when an Endpoint delegates execution to an upstream service that provides no reliable usage information.

Examples include:

- OAuth-connected coding agents;
- subscription-backed AI services;
- remote proprietary agents;
- APIs that return results without usage metadata;
- chained proxy services;
- interactive tools with opaque internal execution.

In this mode, the Proxy Endpoint may not know:

- upstream input-token usage;
- upstream output-token usage;
- hidden context size;
- internal retries;
- reasoning-token usage;
- cached-token usage;
- remaining upstream quota;
- internal tool-execution cost.

Unknown upstream usage SHALL remain explicitly unknown.

## 12. Provider-Metered vs Proxy-Opaque

The distinction is:

Provider-Metered

The Provider or upstream service supplies a usage measurement, but the Consumer cannot reproduce it independently.

Proxy-Opaque

No reliable upstream measurement is available to the Proxy Endpoint itself.

A Proxy-Opaque Endpoint SHALL NOT claim authoritative upstream token usage.

## 13. Accounting Contract

Before Session acceptance, the Endpoint SHALL publish an Accounting Contract as a versioned Registry Object.

```yaml
accounting_contract:
  registry_object_id:
  registry_object_version:
  contract_version:
  capability_id:
  pricing_version:
  billable_units:
    - unit:
      mode:
      price:
      measurement_source:
      verification_method:
      tolerance:
      rounding:
  checkpoint_policy:
  maximum_unreported_usage:
  maximum_request_charge:
  failure_pricing_policy:
```

Marketplace Advertisements and Session acceptance flows SHALL reference the published Accounting Contract object by identifier and version.

Where a surrounding RFC surface is hash-bound, that canonical Accounting Contract object reference MAY be represented as an `accounting_contract_hash`.

The Consumer SHALL explicitly accept the referenced Accounting Contract before execution.

The accepted Accounting Contract object remains bound to the Session.

Pricing changes SHALL NOT alter an active Session unless both parties explicitly accept a replacement contract.

## 14. Proxy-Opaque Disclosure

A Proxy-Opaque Endpoint SHALL publish:

```yaml
accounting:
  mode: proxy_opaque
  upstream_usage_available: false
  upstream_usage_source: unavailable
  token_estimation:
    enabled:
    estimator_id:
    estimator_version:
    billable: false
  billing:
    units:
    maximum_request_charge:
```

The Marketplace SHALL clearly expose this limitation.

The Endpoint SHALL NOT invent a precise remaining upstream quota when the upstream service does not provide one.

## 15. Permitted Proxy-Opaque Billing Units

A Proxy-Opaque Endpoint MAY bill using fixed or independently observable units.

Permitted units include:

- accepted request;
- completed request;
- active execution time;
- reserved Session time;
- idle time;
- input characters;
- output characters;
- input bytes;
- output bytes;
- returned artifact count;
- visible tool-call count;
- fixed request class;
- fixed Session package.

The billing units SHALL be disclosed before Session opening.

## 16. Prohibited Proxy-Opaque Claims

A Proxy-Opaque Endpoint SHALL NOT:

- claim authoritative upstream token usage;
- bill estimated tokens as measured upstream tokens;
- describe estimates as independently verified;
- bill undisclosed hidden work;
- change the billing basis during an active Session;
- retroactively infer an unlimited charge;
- report unavailable usage as zero;
- conceal that upstream metering is unavailable.

Pretending estimated usage is authoritative usage is a protocol violation.

## 17. Recommended Proxy-Opaque Billing

The recommended MVP model is:

`Base Request Fee + Active Execution Time + Optional Observable Output Fee`

Example:

```yaml
billing:
  base_request_fee: 1Q
  active_execution:
    price_per_minute: 0.2Q
    rounding: started_10_seconds
  output:
    unit: characters
    price_per_1000_units: 0.01Q
  maximum_request_charge: 15Q
```

An operator MAY instead publish a fixed price per completed request.

## 18. Fixed Request Classes

Proxy Endpoints MAY publish fixed task classes.

Example:

```yaml
request_classes:
  small:
    price: 1Q
    maximum_input_characters: 5000
    maximum_execution_time: 120s
  standard:
    price: 3Q
    maximum_input_characters: 25000
    maximum_execution_time: 600s
  large:
    price: 10Q
    maximum_input_characters: 100000
    maximum_execution_time: 1800s
```

Class limits SHALL use observable properties.

Requests exceeding the accepted class SHALL be rejected unless the Consumer approves a new contract.

## 19. Active Execution Time

When active execution time is billable, the contract SHALL define:

- start event;
- stop event;
- pause behavior;
- reconnect handling;
- rate-limit handling;
- maximum execution duration;
- rounding interval;
- whether tool-waiting time is billable.

Queue time and upstream outage time SHALL NOT automatically count as active execution.

Where active processing cannot be distinguished reliably, the Endpoint SHOULD use fixed-price billing.

## 20. Maximum Request Charge

Every Proxy-Opaque request SHOULD define a maximum possible charge.

Before execution, the Consumer SHALL be shown:

- base fee;
- variable units;
- maximum execution time;
- maximum request charge;
- remaining Session Deposit.

The Provider SHALL stop, pause or request additional authorization before exceeding the accepted maximum.

Unknown upstream usage does not authorize an unknown bill.

## 21. Token Estimation

A Proxy Endpoint MAY estimate tokens using a declared estimator.

Example:

```yaml
token_estimation:
  enabled: true
  estimator_id: cl100k_base
  estimator_version: "1"
  estimated_input_tokens: 3400
  estimated_output_tokens: 1800
  upstream_usage_available: false
  billable: false
```

Estimated tokens MAY support:

- workload comparison;
- request classification;
- user-facing estimates;
- statistical analysis;
- pricing recommendations.

Estimated tokens SHALL NOT be authoritative billing units in Proxy-Opaque mode.

## 22. Usage Report Structure

Every Provider Usage Report SHALL use a common structure.

```yaml
usage_report:
  report_id:
  report_version:
  session_id:
  endpoint_id:
  capability_id:
  pricing_version:
  accounting_contract_version:
  accounting_modes:
  sequence:
  cumulative_usage:
  request_usage:
  measurement_sources:
  estimated_usage:
  previous_report_hash:
  created_at:
  signature:
```

Usage Reports SHALL be canonically serialized and signed.

## 23. Proxy-Opaque Usage Report

A Proxy-Opaque Usage Report SHOULD include:

```yaml
usage_report:
  accounting_mode: proxy_opaque
  upstream_usage_available: false
  upstream_usage_source: unavailable
  authoritative_input_tokens: null
  authoritative_output_tokens: null
  observed_usage:
    completed_requests:
    active_execution_seconds:
    input_characters:
    output_characters:
    visible_tool_calls:
    returned_artifacts:
  estimated_usage:
    estimated_input_tokens:
    estimated_output_tokens:
    estimator_id:
    billable: false
  observable_billable_units:
  request_class:
  active_execution_time:
  delivered_artifacts:
  completion_status:
```

Unknown values SHALL be represented as unknown or omitted according to schema.

They SHALL NOT be represented as zero.

Estimated values MAY support diagnostics, anomaly detection, or statistical comparison.

They SHALL NOT be billed as authoritative upstream usage.

## 24. Cumulative Usage

Usage Reports SHOULD contain cumulative totals.

Example:

```yaml
cumulative_usage:
  input_tokens: 12500
  output_tokens: 3400
  completed_requests: 7
  active_execution_seconds: 480
  idle_seconds: 600
```

Every report SHALL reference the previous report hash.

Conflicting reports using the same sequence SHALL be detectable.

## 25. Request-Level Usage

Each billable request SHOULD have a request-level record.

```yaml
request_usage:
  request_id:
  request_class:
  input_units:
  output_units:
  duration_units:
  artifact_units:
  started_at:
  completed_at:
  request_hash:
  response_hash:
  accounting_metadata:
```

Request-level records support investigation and statistical comparison.

## 26. Usage Checkpoints

Usage Reports SHALL be produced at checkpoints.

Checkpoints MAY occur:

- after each completed request;
- after a streaming response;
- after a billable idle interval;
- before Deposit extension;
- before Session close;
- when maximum unreported exposure is reached.

Endpoint policy SHALL publish checkpoint rules.

A Checkpoint binds Session ID, Request ID, accepted Usage Report ID and Hash,
Usage Sequence, calculated charge, current Session exposure, remaining Deposit,
Accounting Contract Hash, Checkpoint Sequence and signatures. Acknowledgment
authorizes continued bounded exposure; it does not claim independent
reproduction of Provider-metered values.

## 27. Rolling Reporting

Long-running Sessions SHALL use rolling Usage Reporting.

The Provider SHALL NOT wait until Session completion to disclose all accumulated usage.

Rolling reporting limits:

- disputed amounts;
- unpaid exposure;
- damage from accounting failure;
- damage from disappearing counterparties.

## 28. Maximum Unreported Exposure

Every Endpoint SHALL define or inherit a maximum amount of usage that may remain unreported or unacknowledged.

When the threshold is reached:

- execution pauses;
- the Provider issues a Usage Report;
- acknowledgement is requested;
- new billable work SHALL NOT begin until policy permits continuation.

## 29. Usage Acknowledgement

The Hypervisor SHALL acknowledge every authenticated Usage Report with one of:
`ACCEPTED`, `DUPLICATE`, `REJECTED`, `CONFLICT`, `OUT_OF_SEQUENCE` or
`PENDING_REVIEW`. Transport delivery acknowledgment SHALL NOT replace this
semantic Usage acknowledgment.

An accepted Session participant MAY additionally acknowledge a Usage
Checkpoint.

The MVP consensus representation is `SessionUsageCheckpoint`: all economic
values use integer `q_atoms`, the object carries provider and Consumer
signatures, and its canonical hash is committed by `SESSION_CHECKPOINT_COMMIT`.
That operation only records an accepted bounded exposure while the Funding
Account is locked; it does not itself release, charge or mint funds. The
checkpoint must bind to a finalized prior Funding operation, its exact state
hash, the Usage Report hash and a monotonic Session checkpoint sequence.

The older float-valued checkpoint fields remain a compatibility projection for
local accounting APIs and are not canonical consensus evidence.

```yaml
usage_ack:
  session_id:
  sequence:
  provider_report_hash:
  verification_status:
  consumer_measurements:
  observations:
  signature:
```

Initial Verification Status values are:

- `VERIFIED`
- `ACCEPTED_UNVERIFIED`
- `STATISTICALLY_PLAUSIBLE`
- `MISMATCH`
- `UNABLE_TO_VERIFY`
- `UNABLE_TO_VERIFY_UPSTREAM_USAGE`

Acknowledgement authorizes accepted usage for later Settlement.

It does not imply that every unit was independently reproduced.

Conflicting signed reports and sequence/chain gaps SHALL preserve both hashes
as durable evidence. Redelivery retains the original Report ID, sequence, hash,
dimensions and Provider attempts.

## 30. Verification Is Desirable, Not Mandatory

Independent verification SHOULD be performed whenever practical.

It is not mandatory for all Endpoints.

A Session MAY proceed when:

- the Provider reports usage;
- exact independent verification is unavailable;
- the limitation was declared before Session opening;
- the Consumer accepted the Accounting Contract;
- applicable budget limits remain enforceable.

Consumers MAY reject Endpoints whose Accounting Modes do not satisfy their policy.

## 31. LLM Token Accounting

Token accounting is model-dependent.

The same input may produce different token counts because of differences in:

- tokenizer;
- tokenizer version;
- chat template;
- system-message handling;
- tool definitions;
- structured-output schemas;
- special tokens;
- multimodal serialization;
- Provider-injected context.

The Consumer SHALL NOT assume its own token count is universally authoritative.

## 32. Deterministic LLM Token Accounting

An LLM Endpoint MAY declare deterministic token accounting when it publishes:

- tokenizer identifier;
- tokenizer artifact hash;
- tokenizer version;
- chat template;
- chat-template hash;
- canonical message serialization;
- tool-schema serialization;
- system-message treatment;
- cached-input treatment;
- special-token treatment.

The Consumer MAY reproduce the calculation.

Hidden, unreproducible Provider instructions SHALL NOT be billed as deterministic usage.

## 33. Provider-Metered LLM Accounting

An LLM Endpoint SHALL use Provider-Metered accounting when upstream usage is supplied but exact reproduction is unavailable.

Examples include:

- proprietary APIs;
- closed tokenizers;
- hidden templates;
- upstream metering;
- proprietary cached-token reporting.

The report SHALL identify the measurement source.

## 34. Proxy-Opaque LLM Accounting

An LLM or coding Endpoint SHALL use Proxy-Opaque accounting when the upstream service supplies no reliable token usage.

Examples include:

- OAuth-based Codex access;
- subscription-backed coding agents;
- remote interactive assistants;
- proprietary services without token reports.

Such Endpoints SHOULD bill by:

- request;
- task class;
- active execution time;
- observable result size;
- fixed Session package.

Token estimates remain non-billable metadata.

## 35. LLM Input Scope

Where token accounting is used, the Accounting Contract SHALL define treatment of:

- system prompts;
- conversation history;
- tool definitions;
- structured-output schemas;
- attached context;
- Runtime-injected templates;
- cached context.

Unobservable hidden work SHALL NOT be represented as independently verified.

## 36. LLM Output Scope

The Accounting Contract SHALL define treatment of:

- visible response text;
- tool-call arguments;
- structured output;
- hidden reasoning fields;
- internal retries;
- discarded speculative tokens;
- retransmitted chunks.

Unobservable internal computation SHALL NOT be billed as deterministic output usage.

## 37. Streaming Responses

Streaming does not change accounting semantics.

The Consumer SHALL reconstruct the canonical final response.

Duplicate or retransmitted transport chunks SHALL NOT be billed twice.

## 38. Image Accounting

Image Capabilities MAY bill by:

- image count;
- resolution class;
- pixel count;
- fixed request;
- processing operation;
- output format.

Independently observable properties include:

- artifact count;
- dimensions;
- format;
- file hash;
- animation-frame count.

Internal generation steps SHALL NOT be billed unless explicitly accepted under a non-deterministic contract.

## 39. Audio Accounting

Audio Capabilities MAY bill by:

- input duration;
- output duration;
- input character count;
- request count;
- fixed request class.

Canonical duration SHOULD derive from decoded sample count and sample rate.

Codec padding MAY use a published tolerance.

## 40. Video Accounting

Video Capabilities MAY bill by:

- duration;
- frame count;
- resolution;
- fixed task class;
- processing operation.

The Accounting Contract SHALL define treatment of:

- variable frame rate;
- dropped frames;
- duplicated frames;
- audio tracks;
- container padding.

## 41. Speech-to-Text Accounting

Speech-to-Text SHOULD normally account for submitted audio duration or fixed request classes.

The Consumer can independently measure the original input.

Provider retries SHALL NOT create additional billable input unless the Consumer explicitly resubmits the request.

## 42. Text-to-Speech Accounting

Text-to-Speech MAY account for:

- input characters;
- input tokens;
- output audio duration;
- fixed request cost.

The selected unit SHALL be published in the Endpoint Advertisement.

## 43. Time-Based Accounting

Time-based billing SHALL distinguish:

- active execution time;
- Session reservation time;
- idle time;
- queue time;
- upstream outage time.

Each category SHALL have a published rule.

The Provider SHALL NOT silently convert queue delay or outage time into active billing.

## 44. Idle Accounting

Idle charging follows the accepted Session Policy.

The Provider and Consumer SHALL derive idle periods from agreed Session events.

Idle billing SHALL identify:

- idle start;
- idle end;
- grace period;
- billable duration;
- rounding interval;
- applicable price.

## 45. Rounding

All rounding rules SHALL be published.

Examples include:

- whole token;
- whole second;
- started ten-second interval;
- started minute;
- whole image;
- fixed request unit.

Settlement SHALL use integer or fixed-point arithmetic.

Rounding SHALL occur exactly once.

## 46. Cost Estimate

Before request execution, the Endpoint SHOULD provide an estimated cost.

The estimate MAY include:

- estimated input units;
- maximum output units;
- fixed request fee;
- active-time ceiling;
- reservation charges;
- idle charges;
- Network Fee;
- maximum request charge.

An estimate is not a final Usage Report.

Proxy-Opaque estimates SHALL clearly identify their uncertainty.

## 47. Operator Pricing for Opaque Proxies

The protocol does not automatically determine the operator’s price.

The operator MAY consider:

- upstream subscription limits;
- average number of successful requests;
- expected rate limits;
- average execution duration;
- concurrent Session capacity;
- risk of losing upstream access;
- desired Q earnings;
- comparable Marketplace prices;
- cost variance;
- request failure rate.

The operator accepts the commercial risk of pricing an opaque upstream service.

## 48. Pricing Assistance

The Hypervisor MAY provide an advisory pricing assistant.

A basic recommendation MAY use:

`Target Q Earnings per Period ÷ Expected Successful Requests per Period = Suggested Base Price per Request`

The recommendation MAY also consider:

- median active time;
- average output size;
- Session occupancy;
- failure rate;
- rate-limit frequency;
- comparable Endpoint prices.

Pricing assistance SHALL remain advisory.

## 49. Upstream Capacity Reporting

A Proxy-Opaque Endpoint SHOULD publish observable capacity indicators.

Example:

```yaml
upstream_capacity:
  usage_visibility: unavailable
  concurrent_sessions: 2
  availability_confidence: medium
  recent_rate_limit: false
  successful_requests_last_epoch: 184
  failed_requests_last_epoch: 7
```

A precise remaining quota SHALL NOT be claimed unless the upstream service exposes it.

## 50. Statistical Usage Evaluation

Usage that cannot be independently verified MAY be statistically evaluated.

Statistical evaluation compares an Endpoint against relevant peer groups.

A peer group MAY include Endpoints sharing:

- Capability;
- declared model;
- Model Class;
- Runtime type;
- tokenizer family;
- Accounting Mode;
- estimator version;
- request category;
- context-size range;
- output-size range.

Statistical evaluation detects persistent abnormal patterns.

It does not prove the exact usage of an individual request.

## 51. Statistical Metrics

The network MAY evaluate:

- reported input tokens per input character;
- output tokens per output character;
- charge per completed request;
- active time per request;
- usage per request class;
- output size distribution;
- deviation from peer median;
- success rate;
- timeout rate;
- rate-limit frequency;
- maximum-charge frequency;
- confirmed mismatch rate;
- report omission rate.

Median and robust percentile methods SHOULD be preferred over simple averages.

## 52. Statistical Outcomes

Statistical outcomes MAY include:

- `TYPICAL`
- `PLAUSIBLE`
- `ANOMALOUS`
- `PERSISTENTLY_ANOMALOUS`
- `INSUFFICIENT_DATA`

A single anomaly SHALL NOT prove misconduct.

Persistent unexplained anomalies MAY affect:

- Accounting Transparency;
- Accounting Consistency;
- Endpoint Reputation;
- Marketplace ranking;
- Maintenance Validation probability.

## 53. Statistical Limitations

Statistical evaluation SHALL account for legitimate variation caused by:

- language;
- Unicode content;
- code versus prose;
- tool definitions;
- system prompts;
- multimodal content;
- reasoning format;
- tokenizer family;
- request complexity;
- upstream Provider policy.

Estimated tokens from incompatible estimators SHALL NOT be directly compared.

## 54. Peer Group Resistance

Statistical evaluation SHALL account for Sybil manipulation.

Peer statistics SHOULD be weighted by:

- independent Wallet ownership;
- Endpoint age;
- Reputation;
- report volume;
- operator diversity;
- validation history;
- estimator compatibility.

A small or suspiciously homogeneous peer group SHALL produce low confidence.

## 55. Consumer Policy

Consumers MAY define Accounting Mode policies.

Examples:

- deterministic only;
- deterministic or observable;
- Provider-Metered above a Reputation threshold;
- Proxy-Opaque only with a maximum request charge;
- fixed-price requests only;
- statistical confidence above a threshold.

Agents SHALL respect the owner’s accounting policy.

## 56. Budget Protection

Consumers SHALL be able to limit exposure through:

- Session Deposit;
- maximum request charge;
- maximum output units;
- maximum active execution time;
- maximum Session duration;
- maximum unacknowledged usage;
- automatic termination;
- per-Endpoint spending limit.

Budget protection SHALL remain enforceable even when usage is opaque.

## 57. Usage Disagreement

A Consumer MAY challenge a Usage Report when:

- a deterministic value differs;
- an observable value differs;
- the report violates the Accounting Contract;
- billing exceeds accepted limits;
- the report sequence is invalid;
- duplicate charging occurred;
- the measurement source was misrepresented.

Statistical anomaly alone SHOULD NOT automatically produce an Accounting Mismatch.

## 58. Confirmed Mismatch

A Confirmed Mismatch requires objective evidence.

Examples include:

- incorrect artifact count;
- incorrect decoded media duration;
- invalid deterministic token result;
- duplicate billing;
- conflicting signed reports;
- billing beyond the accepted maximum;
- report-sequence manipulation;
- pricing-version substitution.

On Confirmed Mismatch:

- no new work SHALL begin;
- active execution SHOULD stop safely;
- evidence SHALL be preserved;
- the Session enters `ACCOUNTING_MISMATCH`;
- Settlement uses the last accepted checkpoint;
- a Mismatch Report MAY be published.

## 59. Unverifiable Usage

When the Consumer cannot reproduce Provider-Metered or Proxy-Opaque usage:

- status SHALL be `UNABLE_TO_VERIFY` or `UNABLE_TO_VERIFY_UPSTREAM_USAGE`;
- the report MAY still be accepted;
- no immediate Reputation penalty applies;
- the event MAY contribute to statistical analysis.

Unverifiable does not mean incorrect.

## 60. Last Accepted Checkpoint

The last acknowledged Usage Report defines the uncontested accounting baseline.

Acknowledgement MAY be:

- verified;
- accepted unverified;
- statistically plausible.

Consumer acceptance authorizes Settlement according to the accepted Accounting Contract.

## 61. Failure to Acknowledge

The Provider SHALL NOT accumulate unlimited unacknowledged usage.

When the exposure threshold is reached:

- execution pauses;
- acknowledgement is requested;
- the Session closes after timeout if no acknowledgement arrives.

The last accepted checkpoint SHALL be eligible for Settlement.

## 62. Provider Fails to Report

If the Provider fails to issue required Usage Reports:

- the Consumer MAY pause requests;
- the Session MAY close;
- only previously accepted usage is eligible for Settlement;
- the failure affects Provider reliability metrics.

## 63. Deposit Threshold

Before beginning a request, the Provider SHALL determine whether the remaining Deposit can cover:

- the applicable base fee;
- the minimum request charge;
- the next permitted execution interval;
- the Network Fee;
- the maximum unacknowledged exposure.

If not, the Provider SHALL:

- reject the request;
- pause execution;
- or request a Deposit extension.

## 64. Deposit Extension

The Consumer MAY increase the Deposit during an active Session.

The extension becomes usable only after Ledger finalization.

Deposit extension SHALL NOT modify:

- the existing pricing version;
- the Accounting Contract;
- previously accepted usage.

## 65. Session Close

Before ordinary Session close:

1. Provider publishes the final Usage Report.
2. Consumer verifies or accepts it according to the Accounting Contract.
3. Consumer publishes the final acknowledgement.
4. Provider generates the Invoice.
5. Settlement applies pricing to accepted usage.
6. Remaining Deposit is refunded.

A Session SHALL NOT enter ordinary Settlement with an unresolved Confirmed Mismatch.

## 66. Settlement

Settlement applies published pricing to accepted usage.

Accepted usage MAY be:

- deterministically verified;
- directly observed;
- accepted Provider-Metered usage;
- accepted Proxy-Opaque observable usage;
- fixed-price completion.

Settlement SHALL preserve:

- Accounting Mode;
- measurement source;
- Verification Status;
- report references.

This information supports later Reputation and statistical analysis.

## 67. Crash Recovery

Each party SHALL persist:

- latest local Usage Report;
- latest remote Usage Report;
- last accepted sequence;
- request-level evidence;
- Accounting Contract version;
- pricing version;
- acknowledgement chain.

After reconnect, the parties exchange checkpoint hashes.

Recovery continues only if the chains are consistent.

Otherwise, the Session enters mismatch termination.

## 68. Idempotency

Usage Reports and acknowledgements SHALL be idempotent.

Resending the same signed object SHALL NOT:

- increase usage;
- duplicate billing;
- advance a sequence twice.

Different objects using the same sequence SHALL be treated as conflicting evidence.

## 69. Validation Integration

Validators MAY inspect Usage Reporting during Endpoint certification.

A Validator MAY:

- reproduce deterministic accounting;
- verify observable quantities;
- inspect Provider-Metered disclosures;
- inspect Proxy-Opaque disclosures;
- compare usage statistically;
- verify maximum-charge enforcement;
- document unavailable upstream usage.

A Validator SHALL NOT require authoritative upstream token counts when the upstream service does not provide them.

## 70. Marketplace Transparency

Every Endpoint Advertisement SHALL expose:

- Accounting Contract object reference and version;
- Accounting Modes;
- measurement sources;
- independent-verification availability;
- upstream-usage visibility;
- estimator information;
- maximum request charge;
- historical mismatch rate;
- statistical anomaly rate;
- Accounting Transparency metrics.

Example:

```yaml
accounting_transparency:
  accounting_contract_ref:
    registry_object_id:
    registry_object_version:
  mode: proxy_opaque
  upstream_usage_available: false
  exact_token_reporting: unavailable
  token_estimates_billable: false
  billing_basis:
    - request
    - active_execution_time
  maximum_request_charge: 15Q
  statistical_confidence: medium
```

Marketplace transparency and pricing disclosures SHALL derive from the referenced Accounting Contract object accepted for the advertised Session path.

## 71. Reputation Impact

Usage-related Reputation Metrics MAY include:

- Accounting Transparency;
- Usage Report Availability;
- Deterministic Verification Rate;
- Confirmed Mismatch Rate;
- Statistical Anomaly Rate;
- Maximum-Charge Compliance;
- Pricing Predictability;
- Reporting Consistency;
- Cost Variance;
- Upstream Failure Rate.

Provider-Metered or Proxy-Opaque accounting alone SHALL NOT reduce Reputation.

Misrepresentation of accounting transparency SHALL reduce Reputation.

Confirmed objective mismatches have greater impact than statistical anomalies.

## 72. Attribution

Possible mismatch attribution states include:

- `PROVIDER_AT_FAULT`
- `CONSUMER_AT_FAULT`
- `BOTH_INCONSISTENT`
- `PROTOCOL_INCOMPATIBILITY`
- `INCONCLUSIVE`

A single mismatch SHALL NOT automatically prove malicious behavior.

Attribution SHOULD consider:

- evidence quality;
- repeated behavior;
- independent counterparties;
- Capability version;
- Runtime version;
- later validation results.

## 73. Runtime Responsibilities

The Capability Runtime SHALL:

- generate Provider Usage Reports;
- declare Accounting Modes;
- identify measurement sources;
- expose verification metadata where available;
- preserve report-chain integrity;
- maintain request-level accounting evidence;
- avoid fabricating unavailable upstream usage.

The Runtime-side transport, message identity, and recovery behavior for these duties are defined separately by `RFC-0054`.

The Hypervisor SHALL:

- negotiate the Accounting Contract;
- verify signatures;
- enforce Deposits and limits;
- route reports and acknowledgements;
- initiate Settlement;
- publish Mismatch evidence when necessary.

## 74. Privacy

Usage Reporting SHOULD avoid exposing raw Session content.

Reports SHOULD prefer:

- hashes;
- counts;
- durations;
- dimensions;
- canonical metadata;
- classifications;
- aggregate statistics.

Peer comparison SHALL NOT require disclosure of private prompts or results.

## 75. Security Considerations

The protocol SHALL account for:

- inflated usage reports;
- fake mismatch claims;
- duplicate billing;
- report-chain rewriting;
- tokenizer substitution;
- template substitution;
- pricing-version substitution;
- manipulated peer groups;
- Sybil Endpoints;
- omission of low-usage reports;
- artificial cost normalization;
- undisclosed Proxy-Opaque operation;
- billing estimates as actual usage;
- forced unacknowledged exposure.

## 76. MVP Requirements

The MVP SHALL support:

- mandatory signed Provider Usage Reports;
- versioned Accounting Contracts;
- all six Accounting Modes, including `HYBRID`;
- `AVAILABLE`, `PARTIAL`, `UNAVAILABLE` and `NOT_APPLICABLE`;
- dimension-specific Authority with no Authority on unavailable values;
- Runtime Usage Profiles and pre-admission Contract compatibility;
- one Usage envelope for every accepted Request;
- one Final Usage Report for every terminal Request;
- cumulative report sequences;
- Consumer acknowledgements;
- conflict and out-of-sequence evidence preservation;
- deterministic verification when available;
- observable-unit verification;
- Provider-Metered acceptance;
- Proxy-Opaque accounting;
- fixed-price accounting;
- token estimates as non-billable metadata;
- maximum request charges;
- budget limits;
- maximum unacknowledged exposure;
- confirmed mismatch termination;
- last-accepted-checkpoint Settlement;
- statistical usage collection;
- robust peer comparison;
- Marketplace Accounting Transparency;
- Reputation event generation.
- correction and dispute records;

The MVP MAY postpone:

- zero-knowledge usage proofs;
- confidential aggregate statistics;
- automated fraud attribution;
- advanced anomaly detection;
- cross-tokenizer normalization;
- complex cached-token verification;
- complex video metering.

## 77. Open Protocol Parameters

The following remain Capability-specific or configurable:

- checkpoint frequency;
- maximum unacknowledged usage;
- acknowledgement timeout;
- deterministic tolerance;
- media tolerance;
- idle billing interval;
- rounding rules;
- failed-request pricing;
- maximum request charge defaults;
- mismatch Reputation weights;
- evidence-retention period;
- minimum peer-group size;
- statistical confidence thresholds;
- estimator compatibility rules.

## 78. Design Invariants

- Every Endpoint reports usage.
- Every accepted Request produces a Usage Report envelope.
- Every terminal Request produces an accepted Final Usage Report.
- Unavailable is not zero and carries no numeric Authority.
- Partial is not complete and Not Applicable is not Unavailable.
- Usage Reports, charge calculation and Settlement remain distinct objects.
- Independent verification is desirable but not universally required.
- Accounting limitations are declared before Session execution.
- Unknown upstream usage remains explicitly unknown.
- Provider-Metered usage is valid but not represented as independently verified.
- Proxy-Opaque Endpoints may publish prices without knowing upstream token usage.
- AiDN billing units need not match upstream billing units.
- Estimated tokens are informational and non-authoritative.
- Proxy-Opaque billing uses fixed or observable units.
- Consumers may reject Accounting Modes they do not trust.
- Every opaque request SHOULD have a maximum accepted charge.
- Statistical comparison supplements direct verification.
- Statistical anomalies are not automatic proof of misconduct.
- Confirmed mismatches stop further economic exposure.
- Settlement preserves accounting provenance.
- Reputation distinguishes opacity, transparency, and correctness.
- Budget limits protect Consumers even when exact usage cannot be reproduced.
- The Proxy Endpoint remains responsible for its published Accounting Contract.

## RFC-0037 Settlement Evidence Binding

Settlement consumes only the accepted Final Usage chain head and the exact
Accounting Contract Hash for each Request. It applies Availability, Authority,
fallback, retry and terminal-state rules before Request and Session ceilings.
Usage Reports SHALL NOT name or redirect the Endpoint Payment Beneficiary;
Provider cost remains separate from Consumer-facing Endpoint Payment.
