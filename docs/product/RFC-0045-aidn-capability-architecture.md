RFC-0045

AiDN Capability Architecture

Status: Draft

Version: 0.3

Supersedes:

* RFC-0045 Version 0.1

Depends on:

* RFC-0036 AiDN Ledger State Machine
* RFC-0039 Hypervisor Service Model
* RFC-0044 AiDN Session Protocol
* RFC-0049 Distributed Marketplace and Advertisement Registry
* RFC-0051 Usage Reporting and Verification Protocol
* RFC-0053 Capability Runtime Specification
* RFC-0054 Capability Runtime Protocol
* RFC-0055 Provider Plugin System and Directory
* RFC-0056 Provider Plugin Runtime Interface
* RFC-0057 Validation Report Specification
* RFC-0059 Ledger Operation Catalog
* RFC-0063 Proxy Endpoint Protocol
* RFC-0064 Validation Assignment, Concealed Session and Escrow Protocol
* RFC-0065 Endpoint Certification Derivation and Lifecycle Protocol
* RFC-0066 Protocol Upgrade and Emergency Recovery
* RFC-0067 Protocol Governance and Authorization Policy

---

## 1. Purpose

This document defines the AiDN Capability Architecture.

It specifies:

* what a Capability represents;
* Capability identity and naming;
* Capability versions;
* request and response contracts;
* supported input and output modalities;
* streaming behavior;
* artifact handling;
* stateful execution;
* side effects;
* cancellation and retry semantics;
* accounting-unit declarations;
* validation guidelines;
* Capability registration and lifecycle;
* Runtime conformance;
* Endpoint implementation profiles;
* Capability negotiation;
* compatibility and deprecation;
* Proxy compatibility;
* Marketplace presentation.

A Capability is the stable network contract connecting:

```text
Consumer
    ↓
Session
    ↓
Endpoint
    ↓
Capability Runtime
    ↓
Provider or execution backend
```

---

## 2. Core Principle

A Capability SHALL describe observable Consumer-facing behavior.

It SHALL NOT depend on one particular:

* model;
* vendor;
* Runtime;
* Provider;
* hardware type;
* operating system;
* programming language;
* implementation framework.

For example:

llm.chat

describes a conversational text-generation contract.

It does not mean:

OpenAI API
Qwen
Claude
llama.cpp
one particular tokenizer
one particular GPU

Different implementations may provide the same Capability when they satisfy the same network-visible contract.

---

## 3. Capability Definition

A Capability is a versioned protocol definition describing:

* accepted request structure;
* produced response structure;
* supported modalities;
* execution semantics;
* streaming semantics;
* failure semantics;
* observable usage dimensions;
* permitted accounting modes;
* side-effect behavior;
* validation profile;
* conformance requirements.

---

## 4. Capability Is Not an Endpoint

A Capability defines what kind of service may be offered.

An Endpoint defines one actual offer of that service.

Capability:
llm.chat v2.1
Endpoint:
Qwen-based chat
2Q per standard request
32k context
Proxy-Opaque accounting
Certified

Many Endpoints MAY implement the same Capability.

---

## 5. Capability Is Not a Runtime

A Runtime is a concrete execution implementation.

Examples include:

* llama.cpp Runtime;
* image-generation Runtime;
* STT Runtime;
* remote coding-agent Runtime;
* Proxy Runtime.

A Runtime SHALL declare which Capability contract it implements.

---

## 6. Capability Is Not a Provider

A Provider is the actual backend executing work.

Examples include:

* local model;
* remote model API;
* GPU worker;
* OAuth-connected agent;
* external speech service;
* another AiDN Endpoint.

The Capability remains stable when the Provider changes, provided Consumer-facing behavior remains compatible.

---

## 7. Capability Is Not a Model Identity Claim

A Capability MAY permit Endpoints to declare model metadata.

Such metadata does not alter the Capability contract and is not automatically proven.

For example:

capability_id: llm.chat
declared_model: qwen3.5-27b

The Capability proves neither:

* that the model is truly Qwen;
* that exact weights are used;
* that execution is local;
* that the Endpoint does not proxy another service.

Certification validates observable Capability behavior, not hidden model identity.

---

## 8. Capability Identity

Every Capability SHALL have a stable Capability ID.

Recommended format:

`<namespace>.<family>.<function>`

Examples:

llm.chat
llm.complete
llm.embed
image.generate
image.edit
image.upscale
speech.stt
speech.tts
audio.transform
video.generate
agent.execute
tool.invoke

---

## 9. Capability ID Rules

A Capability ID SHALL:

* use lowercase ASCII;
* use dot-separated components;
* contain only letters, digits, hyphens and dots;
* remain stable across compatible minor versions;
* identify one coherent Consumer-facing function;
* avoid embedding vendor or model names.

Invalid examples include:

OpenAI_GPT
MyServer
Qwen3090
BestImageGenerator

---

## 10. Namespaces

Initial reserved namespaces include:

llm
image
speech
audio
video
embedding
agent
tool
data
document

Third-party Capability namespaces MAY use:

vendor.<organization>.<function>

or another governance-approved naming convention.

---

## 11. Standard and Extension Capabilities

Capabilities are classified as:

STANDARD
EXPERIMENTAL
VENDOR_EXTENSION
PRIVATE

Standard

Defined by canonical AiDN protocol governance.

Experimental

Publicly registered but not guaranteed long-term compatibility.

Vendor Extension

Defined by a specific organization.

Private

Used within a restricted network or operator group and not necessarily listed in the global Marketplace.

---

## 12. Capability Version

Every Capability SHALL have a version:

MAJOR.MINOR.PATCH

Example:

2.1.3

---

## 13. Major Version

A Major Version change indicates a breaking contract change.

Examples include:

* incompatible request schema;
* incompatible response schema;
* changed mandatory semantics;
* changed side-effect behavior;
* changed accounting interpretation;
* changed result identity rules.

A Runtime implementing Major Version 1 is not automatically compatible with Major Version 2.

---

## 14. Minor Version

A Minor Version adds backward-compatible behavior.

Examples include:

* optional request fields;
* optional response metadata;
* optional streaming event;
* new optional feature;
* additional non-mandatory artifact metadata.

A Consumer supporting an older Minor Version SHALL still be able to use the mandatory base contract.

---

## 15. Patch Version

A Patch Version MAY correct:

* documentation;
* test vectors;
* non-semantic schema annotations;
* error descriptions;
* conformance clarifications.

A Patch Version SHALL NOT change canonical execution or accounting meaning.

---

## 16. Capability Definition Hash

Every Capability version SHALL have a deterministic hash.

```text
capability_definition_hash
=
HASH(
    capability_id
    +
    capability_version
    +
    canonical_capability_definition
)
```

Endpoints and Runtimes SHALL bind to the exact hash they implement.

Within a Hypervisor, that binding SHOULD be created from a Model Deployment
through a Runtime Binding or equivalent runtime-adapter object.

A raw Provider inventory entry is not by itself an AiDN Capability binding.

---

## 17. Capability Definition Object

```yaml
capability_definition:
  capability_id:
  capability_version:
  capability_status:
  capability_class:
  request_schema_hash:
  response_schema_hash:
  event_schema_hash:
  error_schema_hash:
  input_modalities:
  output_modalities:
  state_model:
  streaming_model:
  cancellation_model:
  idempotency_model:
  side_effect_model:
  limit_dimensions:
  observable_usage_dimensions:
  permitted_accounting_modes:
  feature_registry_hash:
  validation_profile_hash:
  conformance_profile_hash:
  security_profile_hash:
  previous_version:
  compatibility_rules:
  deprecation_policy:
  definition_hash:
```

---

## 18. Capability Classes

The initial Capability classes are:

GENERATION
TRANSFORMATION
ANALYSIS
EMBEDDING
RETRIEVAL
AGENT_EXECUTION
TOOL_EXECUTION
STREAM_PROCESSING

---

## 19. Generation Capability

Produces new content from input instructions.

Examples:

llm.chat
image.generate
speech.tts
video.generate

---

## 20. Transformation Capability

Transforms supplied content.

Examples:

image.edit
image.upscale
audio.transform
document.convert

---

## 21. Analysis Capability

Produces observations or structured analysis of supplied content.

Examples:

speech.stt
image.classify
document.extract

---

## 22. Embedding Capability

Produces vector or structured representations.

Examples:

llm.embed
image.embed
multimodal.embed

The Capability SHALL define:

* vector dimension handling;
* numeric encoding;
* normalization disclosure;
* batch behavior;
* model compatibility metadata.

---

## 23. Retrieval Capability

Returns matching objects or references from a declared data source.

Examples:

data.search
document.retrieve

The Capability SHALL distinguish:

* retrieval result;
* generated interpretation;
* source reference;
* ranking score.

---

## 24. Agent Execution Capability

Executes a stateful or semi-stateful task that may involve:

* planning;
* tool calls;
* file modification;
* code execution;
* external systems;
* multiple intermediate steps.

Agent Capabilities SHALL define stronger rules for:

* side effects;
* cancellation;
* recovery;
* workspace state;
* user approval;
* tool evidence.

---

## 25. Tool Execution Capability

Invokes one specific tool or tool class.

Examples:

tool.http
tool.shell.sandboxed
tool.database.query

A Tool Capability SHALL explicitly declare its side-effect and security model.

---

## 26. Capability Contract Layers

The architecture separates three layers:

Capability Definition
Endpoint Implementation Profile
Session Contract

---

## 27. Capability Definition Layer

Defines the general network contract.

It answers:

* what Requests look like;
* what responses look like;
* which semantics are mandatory;
* which features exist;
* which usage dimensions may be reported.

---

## 28. Endpoint Implementation Profile

Defines how one Endpoint implements the Capability.

It answers:

* which Capability version;
* which Endpoint Feature Profile;
* which formats;
* which Endpoint Limit Profile;
* which Accounting Modes;
* which state model;
* which Provider disclosure;
* which safety and Data Handling policies.

The Endpoint Implementation Profile SHALL be the alignment point for Marketplace-facing Feature Profile and Limit Profile references.

---

## 29. Session Contract Layer

Freezes the specific terms accepted by Consumer and Endpoint.

It answers:

* exact Endpoint Configuration Hash;
* exact Capability version;
* exact limits;
* exact pricing;
* exact accounting;
* exact Data Handling Policy;
* exact Session semantics.

---

## 30. Runtime Capability Binding

Every Capability Runtime instance SHALL bind to:

```yaml
runtime_capability_binding:
  runtime_id:
  capability_id:
  supported_major_version:
  supported_minor_range:
  active_definition_hash:
  implemented_features:
  conformance_profile:
```

---

## 31. One Primary Capability per Runtime

In the MVP, one Runtime instance SHALL implement one primary Capability ID and one Major Version.

It MAY:

* support several compatible Minor Versions;
* support optional features;
* back several Endpoints;
* use several Providers internally.

It SHALL NOT expose unrelated Capability contracts through one ambiguous Runtime identity.

---

## 32. Multiple Runtime Instances

One software process MAY host several Runtime instances.

Example:

```text
Runtime process
├── Runtime A: llm.chat v2
├── Runtime B: llm.embed v1
└── Runtime C: agent.execute v1
```

Each Runtime instance SHALL have separate:

* Runtime ID;
* Capability binding;
* Health;
* configuration;
* execution limits.

---

## 33. Endpoint Capability Binding

Every Endpoint SHALL bind to one primary Capability version.

```yaml
endpoint_capability_binding:
  endpoint_id:
  capability_id:
  capability_version:
  capability_definition_hash:
  endpoint_implementation_profile_hash:
  runtime_id:
  endpoint_configuration_hash:
```

---

## 34. One Primary Capability per Endpoint

An Endpoint SHALL expose one primary Capability.

A Consumer SHALL not need to guess whether one Endpoint behaves as:

* chat;
* embedding;
* image generation;
* agent execution;

depending on undocumented request fields.

---

## 35. Composite Behavior

An Endpoint MAY internally invoke several other Capabilities.

Example:

```text
agent.execute
    ↓
llm.chat
    ↓
tool.invoke
    ↓
document.retrieve
```

The Consumer-facing Endpoint remains agent.execute.

Internal composition does not change the primary Capability.

---

## 36. Explicit Composite Capability

When the composition itself creates a stable Consumer-facing contract, it MAY be registered as a new Capability.

For example:

research.report.generate

It SHALL define its own:

* inputs;
* outputs;
* side effects;
* accounting;
* validation;
* result contract.

---

## 37. Request Schema

Every Capability SHALL define a canonical Request Schema.

The schema SHALL identify:

* mandatory fields;
* optional fields;
* data types;
* size constraints;
* modality references;
* version behavior;
* unknown-field handling.

---

## 38. Response Schema

Every Capability SHALL define a canonical Response Schema.

It SHALL identify:

* completion state;
* result payload;
* artifacts;
* structured metadata;
* warnings;
* usage reference;
* error behavior;
* partial-result representation.

---

## 39. Canonical Schema Representation

The MVP SHALL define one canonical schema representation capable of describing:

* scalar fields;
* structured objects;
* arrays;
* binary references;
* tagged unions;
* optional fields;
* numeric limits;
* strings;
* content references.

JSON-compatible schemas MAY be used for developer accessibility.

Canonical hashing SHALL use deterministic serialization.

---

## 40. Payload and Envelope Separation

The Session Protocol defines the Request envelope.

The Capability defines the Capability-specific payload.

```text
Session Request Envelope
├── Session ID
├── Request ID
├── Charge Ceiling
├── Deadline
└── Capability Payload
```

This prevents every Capability from inventing its own economic and replay-protection layer.

---

## 41. Input Modalities

Initial modality identifiers include:

TEXT
STRUCTURED_DATA
BINARY
IMAGE
AUDIO
VIDEO
DOCUMENT
FILE
ARTIFACT_REFERENCE
VECTOR

A Capability SHALL list all permitted input modalities.

---

## 42. Output Modalities

A Capability SHALL list all possible output modalities.

Example:

```yaml
output_modalities:
  - TEXT
  - STRUCTURED_DATA
  - ARTIFACT_REFERENCE
```

An Endpoint MAY support a subset only when the Capability marks those modalities optional.

---

## 43. Modality Descriptor

```yaml
modality_descriptor:
  modality:
  content_type:
  encoding:
  schema_reference:
  maximum_size:
  streaming_support:
  artifact_required:
```

---

## 44. Content Type

Binary and artifact modalities SHALL declare a content type.

Examples:

image/png
image/webp
audio/wav
audio/mpeg
video/mp4
application/pdf
application/json

An Endpoint SHALL NOT return an unrelated content type without an accepted conversion rule.

---

## 45. Inline and Referenced Payloads

A Capability MAY allow payloads:

INLINE
ARTIFACT_REFERENCE
STREAMED

Large payloads SHOULD use content-addressed artifact references.

---

## 46. Input Integrity

Referenced inputs SHALL include:

* content hash;
* size;
* content type;
* access reference;
* expiration;
* authorization where required.

The Runtime SHALL verify input integrity before execution.

---

## 47. Output Integrity

Output artifacts SHALL include content-addressed descriptors under RFC-0044.

The Consumer SHALL be able to verify:

* content hash;
* content type;
* size;
* request association.

---

## 48. Capability State Model

Every Capability SHALL declare one state model:

STATELESS
SESSION_STATEFUL
EXTERNAL_STATEFUL
WORKSPACE_STATEFUL

---

## 49. Stateless Capability

Each Request can be executed independently.

The Endpoint SHALL not imply preserved hidden context.

Examples:

image.upscale
llm.embed
speech.stt

---

## 50. Session-Stateful Capability

State is preserved within one AiDN Session.

Examples:

llm.chat
interactive agent

The Capability SHALL define:

* state creation;
* state update;
* state reset;
* state expiration;
* recovery expectations.

---

## 51. External-Stateful Capability

State is primarily stored in an external Provider or application.

Examples:

* Provider conversation thread;
* OAuth-connected coding agent;
* remote workspace.

The Endpoint SHALL disclose:

* external-state dependency;
* recovery limitations;
* retention uncertainty;
* possible Provider lock-in.

---

## 52. Workspace-Stateful Capability

Execution modifies a bounded workspace.

Examples:

agent.execute
code.workspace.modify

The Capability SHALL define:

* workspace identity;
* file-state boundaries;
* persistence;
* snapshot behavior;
* side-effect approval;
* result export.

---

## 53. State Initialization

A stateful Capability SHALL define how state is initialized.

Possible modes include:

EMPTY
CONSUMER_PROVIDED
RESTORED
RUNTIME_TEMPLATE
EXTERNAL_REFERENCE

---

## 54. State Reset

A stateful Capability SHOULD support an explicit reset operation when meaningful.

Reset SHALL define whether it:

* clears Runtime context;
* clears external Provider thread;
* clears workspace;
* preserves artifacts;
* affects billing.

---

## 55. State Recovery

The Capability SHALL declare one recovery class:

FULLY_RECOVERABLE
CHECKPOINT_RECOVERABLE
RECONSTRUCTIBLE
BEST_EFFORT
NON_RECOVERABLE

The Endpoint MAY offer a stronger implementation than the minimum Capability requirement.

---

## 56. Streaming Model

Every Capability SHALL declare one streaming model:

NO_STREAMING
OUTPUT_STREAMING
INPUT_STREAMING
BIDIRECTIONAL_STREAMING
EVENT_STREAMING

---

## 57. Output Streaming

Output is delivered incrementally.

Examples:

* text tokens or text chunks;
* audio frames;
* video fragments;
* progress events.

The Capability SHALL define whether chunks are semantically independent or only valid as a complete stream.

---

## 58. Input Streaming

The Consumer sends incremental input.

Examples:

* live audio for STT;
* video frames;
* streaming sensor data;
* document chunks.

The Capability SHALL define:

* chunk ordering;
* finalization;
* backpressure;
* maximum buffering;
* incomplete-input behavior.

---

## 59. Bidirectional Streaming

Input and output may proceed concurrently.

Examples:

* real-time speech conversation;
* interactive agent control;
* live translation.

The Capability SHALL define directional sequencing independently.

---

## 60. Event Streaming

The Runtime emits structured events such as:

* progress;
* tool call;
* partial result;
* warning;
* state transition;
* required approval.

Events SHALL be distinct from billable result content unless the Accounting Contract says otherwise.

---

## 61. Stream Completion Semantics

A Capability SHALL define:

* normal completion event;
* partial completion;
* cancellation completion;
* error termination;
* final result root;
* final Usage Report requirement.

---

## 62. Partial Result Semantics

A Capability SHALL declare whether partial results are:

NOT_USABLE
OPTIONALLY_USABLE
INDEPENDENTLY_USABLE

This declaration affects:

* cancellation;
* failure handling;
* Settlement;
* Validation.

---

## 63. Cancellation Model

Every Capability SHALL declare one cancellation class:

IMMEDIATE
CHECKPOINT_BOUNDED
BEST_EFFORT
NON_CANCELLABLE_AFTER_START

---

## 64. Immediate Cancellation

Execution can stop promptly without material side effects.

Example:

* queued text generation;
* local stateless transformation.

---

## 65. Checkpoint-Bounded Cancellation

Execution may stop only at defined safe boundaries.

Examples:

* video segment generation;
* batch processing;
* multi-stage transformation.

---

## 66. Best-Effort Cancellation

Cancellation may fail because:

* remote Provider does not support it;
* execution already completed;
* external operation cannot be interrupted.

The Endpoint SHALL disclose this limitation.

---

## 67. Non-Cancellable After Start

Some operations cannot safely stop after execution begins.

Examples may include certain irreversible external actions.

Such Capabilities require explicit Consumer confirmation before execution.

---

## 68. Idempotency Model

Every Capability SHALL declare one idempotency model:

NATURALLY_IDEMPOTENT
IDEMPOTENT_WITH_KEY
NON_IDEMPOTENT
SIDE_EFFECT_DEPENDENT

---

## 69. Naturally Idempotent

Repeating the same Request produces no additional external effect.

The output itself MAY differ for nondeterministic models, but no external state is duplicated.

---

## 70. Idempotent with Key

The Runtime or Provider supports stable idempotency keys.

Repeating a Request with the same key SHALL not repeat the underlying operation.

---

## 71. Non-Idempotent

Repeating a Request may create additional external effects.

Automatic retry SHALL be disabled unless the Consumer approves it.

---

## 72. Side-Effect Dependent

Some Request modes are read-only while others create external changes.

The Request payload SHALL explicitly identify the requested side-effect class.

---

## 73. Side-Effect Model

Every Capability SHALL declare possible side-effect classes:

NONE
READ_ONLY_EXTERNAL
REVERSIBLE_WRITE
EXTERNAL_WRITE
IRREVERSIBLE
FINANCIAL
SECURITY_SENSITIVE

---

## 74. No Undeclared Side Effects

An Endpoint SHALL NOT produce a side-effect class absent from:

* the Capability Definition;
* the Endpoint Implementation Profile;
* the accepted Session Contract;
* any required Consumer approval.

---

## 75. Side-Effect Evidence

A side-effecting Capability SHALL define evidence such as:

* operation ID;
* external reference;
* input hash;
* result hash;
* completion state;
* idempotency reference;
* Consumer approval reference.

---

## 76. Tool Calls

An Agent Capability MAY call tools internally.

The Capability SHALL declare whether tool calls are:

HIDDEN_INTERNAL
OBSERVABLE
APPROVAL_REQUIRED
CONSUMER_SUPPLIED

---

## 77. Hidden Internal Tool Calls

The Endpoint may use internal tools without exposing each call when they do not create material external side effects.

Their cost treatment SHALL still follow the accepted Accounting Contract.

---

## 78. Observable Tool Calls

The Endpoint emits structured tool-call events.

These events MAY include:

* Tool ID;
* argument commitment;
* side-effect class;
* start;
* completion;
* output commitment.

---

## 79. Approval-Required Tool Calls

The Runtime SHALL pause before execution until it receives a valid Consumer approval token.

Approval SHALL bind to:

* Session;
* Request;
* Tool Call;
* side-effect class;
* maximum additional exposure;
* expiration.

---

## 80. Feature Registry

A Capability MAY define optional features.

Examples for llm.chat may include:

structured_output
tool_calls
vision_input
audio_input
reasoning_metadata
provider_thread
json_schema_output

---

## 81. Feature Identifier

Feature IDs SHALL be namespaced within the Capability.

Example:

llm.chat.tool_calls
llm.chat.vision_input

---

## 82. Feature Version

A feature MAY have an independent version when its semantics evolve.

```yaml
capability_feature:
  feature_id:
  feature_version:
  mandatory_for_capability:
  request_schema_extension:
  response_schema_extension:
  compatibility:
```

---

## 83. Required and Optional Features

A Consumer MAY mark a feature as:

REQUIRED
PREFERRED
OPTIONAL

If a required feature is unavailable, the Endpoint SHALL reject the Request or Session.

It SHALL NOT silently downgrade.

---

## 84. Endpoint Feature Profile

```yaml
endpoint_feature_profile:
  endpoint_id:
  capability_id:
  capability_version:
  supported_features:
  unsupported_features:
  feature_limits:
  profile_hash:
```

This is the canonical Marketplace Feature Profile surface for one Endpoint.

Any Marketplace Feature Profile reference SHALL resolve to an Endpoint Feature Profile consistent with the Capability Definition and the Endpoint Implementation Profile.

---

## 85. Feature Negotiation

Feature negotiation SHALL occur before execution.

It MAY occur:

* during Session opening;
* at Request preflight;
* through both layers.

The accepted feature set SHALL be evidence-visible.

---

## 86. Unknown Features

An unknown optional feature MAY be ignored.

An unknown required feature SHALL cause rejection.

---

## 87. Capability Extensions

Vendor-specific fields SHALL be placed in a namespaced extension object.

Example:

```yaml
extensions:
  vendor.example:
    custom_mode: fast
```

---

## 88. Extension Safety

An extension SHALL NOT silently alter:

* maximum charge;
* Settlement Resolver;
* Data Handling Policy;
* side-effect class;
* security boundary;
* mandatory Capability semantics.

Such changes require explicit base-contract fields.

---

## 89. Limit Dimensions

A Capability SHALL define which limits an Endpoint must or may publish.

Initial dimensions include:

MAX_INPUT_BYTES
MAX_OUTPUT_BYTES
MAX_CONTEXT_UNITS
MAX_BATCH_SIZE
MAX_ARTIFACTS
MAX_ARTIFACT_BYTES
MAX_EXECUTION_TIME
MAX_TOOL_CALLS
MAX_CONCURRENT_STREAMS
MAX_WORKSPACE_BYTES

---

## 90. Capability-Specific Limits

A Capability MAY add dimensions such as:

MAX_IMAGE_WIDTH
MAX_IMAGE_HEIGHT
MAX_AUDIO_DURATION
MAX_VIDEO_DURATION
MAX_VECTOR_DIMENSION
MAX_DOCUMENT_PAGES

---

## 91. Hard and Soft Limits

Limits are classified as:

HARD
SOFT
ADVISORY

Hard

Requests exceeding the limit SHALL be rejected.

Soft

Requests may be accepted with changed behavior or additional policy.

Advisory

Used for planning and Marketplace presentation.

---

## 92. Endpoint Limit Profile

```yaml
endpoint_limit_profile:
  endpoint_id:
  capability_id:
  hard_limits:
  soft_limits:
  advisory_limits:
  limit_policy_hash:
```

This is the canonical Marketplace Limit Profile surface for one Endpoint.

Any Marketplace Limit Profile reference SHALL resolve to an Endpoint Limit Profile consistent with the Capability-defined limit dimensions and the Endpoint Implementation Profile.

---

## 93. No Hidden Limit Reduction

An Endpoint SHALL NOT knowingly accept a Request under declared limits and then fail because of a lower undisclosed internal limit.

Temporary operational capacity may still cause rejection before execution.

---

## 94. Observable Usage Dimensions

Every Capability SHALL define which work dimensions may be observed or measured.

Examples include:

REQUEST_COUNT
INPUT_BYTES
OUTPUT_BYTES
INPUT_TOKENS
OUTPUT_TOKENS
ACTIVE_EXECUTION_TIME
QUEUE_TIME
AUDIO_SECONDS
VIDEO_SECONDS
IMAGE_COUNT
ARTIFACT_COUNT
ARTIFACT_BYTES
TOOL_CALL_COUNT
WORKSPACE_BYTES

---

## 95. Observable Does Not Mean Billable

A Usage Report may contain an observed dimension without using it for billing.

Example:

estimated_output_tokens: 1200
billable_unit: fixed_request_class

---

## 96. Permitted Accounting Modes

A Capability SHALL list compatible Accounting Modes.

Initial modes include:

DETERMINISTIC
OBSERVABLE
PROVIDER_METERED
PROXY_OPAQUE
FIXED_PRICE
HYBRID

---

## 97. Capability Does Not Set Endpoint Price

The Capability defines possible units.

The Endpoint defines:

* price;
* minimum Deposit;
* charge ceilings;
* request classes;
* failure pricing.

AiDN does not require all Endpoints implementing one Capability to use the same business model.

---

## 98. Deterministic Accounting

Deterministic accounting requires a shared method producing the same result for both parties.

Examples may include:

* exact byte count;
* exact artifact count;
* defined audio duration;
* deterministic tokenizer and version.

---

## 99. Token Accounting

A Capability MAY support token dimensions.

It SHALL NOT assume that all models or Providers use the same tokenizer.

Exact token billing requires:

* agreed tokenizer identity and version;
* or authoritative Provider usage accepted by the Accounting Contract.

---

## 100. Estimated Tokens

Estimated tokens MAY be reported for:

* diagnostics;
* statistical comparison;
* capacity planning;
* anomaly analysis.

They SHALL be marked:

authoritative: false

unless the Accounting Contract explicitly establishes them as deterministic billable units.

---

## 101. Proxy-Opaque Capability Support

A Capability MAY permit PROXY_OPAQUE accounting.

This means:

* upstream usage may be unknown;
* exact upstream tokens may be unavailable;
* billing uses fixed or observable Consumer-facing units;
* unknown values remain unknown.

---

## 102. Fixed Request Classes

A Capability MAY define standard Request Class dimensions.

Example:

SMALL
STANDARD
LARGE
EXTENDED

The Capability SHALL define which observable request properties may determine the class.

The Endpoint assigns prices to supported classes.

---

## 103. No Retroactive Request Reclassification

Once a Request Class is accepted, the Endpoint SHALL NOT move the completed Request into a more expensive class.

---

## 104. Usage Schema

Every Capability SHALL provide a Usage Schema describing:

* possible dimensions;
* unit identifiers;
* cumulative behavior;
* nullability;
* estimate markers;
* authority source;
* billing eligibility.

---

## 105. Result Status

Every Capability response SHALL end in one of:

COMPLETED
PARTIAL
CANCELLED
FAILED
EXPIRED

Capability-specific sub-status MAY be added.

---

## 106. Meaningful Completion

The Capability SHALL define minimum conditions for COMPLETED.

Examples:

Image Generation

* valid decodable image;
* content hash;
* supported dimensions;
* artifact delivery.

STT

* valid transcription response;
* request association;
* completion status.

Agent Execution

* declared task boundary reached;
* final state summary;
* side-effect records;
* artifact or result references.

---

## 107. Error Architecture

A Capability SHALL define Capability-specific errors while reusing stable Session errors.

Errors SHALL distinguish:

* invalid request;
* unsupported feature;
* resource limit;
* execution failure;
* Provider failure;
* policy rejection;
* cancellation;
* partial completion;
* malformed output.

---

## 108. Standard Capability Error Codes

The MVP SHALL define at least:

CAPABILITY_NOT_FOUND
CAPABILITY_VERSION_UNSUPPORTED
CAPABILITY_DEFINITION_MISMATCH
CAPABILITY_SCHEMA_INVALID
CAPABILITY_FEATURE_UNSUPPORTED
CAPABILITY_REQUIRED_FEATURE_MISSING
CAPABILITY_INPUT_MODALITY_UNSUPPORTED
CAPABILITY_OUTPUT_MODALITY_UNSUPPORTED
CAPABILITY_LIMIT_EXCEEDED
CAPABILITY_STATE_MODEL_UNSUPPORTED
CAPABILITY_STREAMING_UNSUPPORTED
CAPABILITY_CANCELLATION_UNSUPPORTED
CAPABILITY_SIDE_EFFECT_NOT_ALLOWED
CAPABILITY_CONSUMER_APPROVAL_REQUIRED
CAPABILITY_ACCOUNTING_MODE_UNSUPPORTED
CAPABILITY_RUNTIME_UNAVAILABLE
CAPABILITY_RESULT_INVALID
CAPABILITY_ARTIFACT_INVALID
CAPABILITY_DEPRECATED
CAPABILITY_RETIRED

---

## 109. Provider-Specific Errors

Provider-specific errors MAY be included as diagnostics.

The Endpoint SHALL map them to stable Capability or Session errors.

Secrets and private upstream identifiers SHALL be removed where required.

---

## 110. Data Handling Requirements

A Capability SHALL define which Data Handling declarations may be required.

Examples include:

* data leaves Hypervisor;
* upstream Provider receives content;
* temporary retention;
* long-term retention;
* workspace persistence;
* external tool access;
* geographic restrictions;
* training-use uncertainty.

---

## 111. Capability Privacy Profile

```yaml
capability_privacy_profile:
  content_may_leave_hypervisor:
  external_provider_possible:
  persistent_state_possible:
  sensitive_data_supported:
  consumer_deletion_supported:
  required_disclosures:
```

The Endpoint supplies actual policy values.

---

## 112. Security Profile

A Capability SHALL define relevant security properties.

Examples include:

* untrusted input handling;
* code execution;
* network access;
* filesystem access;
* side effects;
* secret access;
* sandbox requirement;
* artifact scanning;
* output-size limits.

---

## 113. Agent Security

An agent.execute or comparable Capability SHALL declare:

* available tools;
* workspace scope;
* network scope;
* secret scope;
* side-effect approval policy;
* execution time limit;
* recovery model;
* audit event model.

---

## 114. Runtime Isolation Requirement

A Capability MAY require a minimum Runtime isolation level.

Possible classes include:

PROCESS_ISOLATED
CONTAINER_ISOLATED
VM_ISOLATED
SANDBOXED
EXTERNAL_PROVIDER

Such declarations describe the implementation profile.

They do not automatically prove that isolation is correctly enforced.

---

## 115. Capability Validation Profile

Every Standard Capability SHALL define a Validation Profile.

```yaml
capability_validation_profile:
  capability_id:
  capability_version:
  minimum_request_count:
  permitted_test_categories:
  required_observations:
  required_artifact_checks:
  required_protocol_checks:
  required_usage_checks:
  critical_failure_conditions:
  inconclusive_conditions:
  maximum_validation_workload:
  prohibited_validation_uses:
  standard_risk_class:
```

---

## 116. Flexible Validation Principle

The Validation Profile SHALL define broad boundaries rather than one universal benchmark unless objective benchmarking is truly necessary.

Validators MAY design their own representative Requests within those boundaries.

---

## 117. Validation Does Not Prove Hidden Model Identity

A Capability Validation SHALL normally verify:

* Endpoint reachability;
* request compatibility;
* meaningful output;
* valid result format;
* artifact integrity;
* Usage Reporting;
* limit compliance;
* obvious failure behavior.

It SHALL NOT normally prove:

* exact hidden model;
* exact model weights;
* local execution;
* upstream Provider identity.

---

## 118. Capability-Specific Meaningful Output

The Validation Profile SHALL define basic observable expectations.

Examples:

llm.chat

* valid response structure;
* non-empty meaningful text;
* no obvious protocol corruption.

image.generate

* decodable image;
* supported dimensions;
* not blank or obviously corrupted unless requested;
* valid artifact descriptor.

speech.stt

* valid transcription response from valid speech input;
* no unrelated protocol garbage.

speech.tts

* valid decodable audio;
* non-empty duration;
* not pure silence or noise unless requested.

agent.execute

* task events are structurally valid;
* side effects follow approval rules;
* output or failure state is auditable.

---

## 119. Validation Workload Limit

The Capability Validation Profile SHALL limit:

* Request count;
* input size;
* output size;
* artifact size;
* execution duration;
* tool calls;
* side effects.

This prevents Validation assignments from becoming free production workloads.

---

## 120. Prohibited Validation Side Effects

Validation SHALL normally prohibit:

* real financial transactions;
* sending real external messages;
* production deployment;
* destructive file changes;
* irreversible account actions.

A specialized Capability policy may define safe test environments.

---

## 121. Capability Risk Class

Every Capability version SHALL have a default risk class:

STANDARD
ELEVATED
RESTRICTED

The risk class influences:

* Certification requirements;
* number of reports;
* validity period;
* side-effect controls;
* Marketplace warnings.

---

## 122. Standard Risk

Ordinary generation and transformation Capabilities are normally Standard.

One eligible Validation Report is generally sufficient for Initial Certification.

---

## 123. Elevated Risk

Elevated Capabilities may include:

* autonomous agents with external writes;
* infrastructure control;
* high-cost long-running tasks;
* security-sensitive tools.

They MAY require:

* more than one report;
* shorter Certification;
* stronger Runtime isolation;
* stronger side-effect approval.

---

## 124. Restricted Risk

Restricted Capabilities require a specialized policy before ordinary public Certification.

The network SHALL not apply a generic chat-model validation profile to a Capability capable of controlling critical physical infrastructure. Even standards committees should occasionally resist comedy.

---

## 125. Conformance Profile

Every Standard Capability SHALL define conformance requirements.

```yaml
capability_conformance_profile:
  mandatory_schema_tests:
  mandatory_behavior_tests:
  streaming_tests:
  cancellation_tests:
  idempotency_tests:
  artifact_tests:
  usage_tests:
  side_effect_tests:
  error_tests:
```

---

## 126. Runtime Conformance

A Runtime SHALL pass Capability conformance before it may be declared compatible for public use where the protocol requires verification.

Conformance proves contract implementation.

It does not prove:

* output quality;
* continuous availability;
* hidden Provider identity;
* legal authorization.

---

## 127. Endpoint Conformance

An Endpoint SHALL be checked against:

* Runtime Capability binding;
* Endpoint Implementation Profile;
* Endpoint limits;
* Accounting Mode;
* Session behavior;
* Proxy behavior;
* Data Handling disclosures.

---

## 128. Capability Test Vectors

The project SHOULD publish deterministic or bounded test vectors.

Examples include:

* valid minimum Request;
* invalid schema;
* maximum-size boundary;
* unsupported feature;
* streaming sequence;
* cancellation;
* artifact hash validation;
* Usage Report schema;
* expected errors.

For nondeterministic generation, test vectors validate protocol structure rather than exact semantic output.

---

## 129. Reference Capability Harness

The AiDN project SHOULD provide a Capability conformance harness capable of:

* discovering Runtime Capability binding;
* sending valid and invalid Requests;
* testing limits;
* testing streaming;
* testing cancellation;
* testing artifacts;
* testing Usage Reports;
* testing side-effect approvals;
* verifying stable errors.

---

## 130. Capability Lifecycle

A Capability version follows:

```text
DRAFT
    ↓
PROPOSED
    ↓
EXPERIMENTAL
    ↓
ACTIVE
    ↓
DEPRECATED
    ↓
RETIRED
```

Alternative state:

SECURITY_BLOCKED

---

## 131. Draft Capability

A Draft is under design.

It SHALL NOT be treated as a stable Marketplace contract.

---

## 132. Proposed Capability

A Proposed Capability has a complete definition and is under protocol review.

Implementations MAY experiment with it.

---

## 133. Experimental Capability

An Experimental Capability may be publicly used with explicit compatibility warnings.

It MAY change more quickly than an Active Capability.

---

## 134. Active Capability

An Active Capability is a supported protocol contract.

Standard Marketplace clients SHOULD recognize it.

---

## 135. Deprecated Capability

A Deprecated Capability remains usable during a Compatibility Window.

New Endpoints SHOULD migrate to a supported version.

---

## 136. Retired Capability

A Retired Capability cannot be used for new Sessions.

Historical Sessions and evidence remain valid under their original contract.

---

## 137. Security-Blocked Capability

A Capability MAY be temporarily or permanently blocked when its contract creates an unresolved critical security problem.

Blocking SHALL follow authorized protocol rules.

It SHALL define treatment of existing Sessions.

---

## 138. Capability Registration

A new Capability Definition SHALL be committed through a canonical operation such as:

CAPABILITY_DEFINE

The operation SHALL reference:

* definition hash;
* schemas;
* validation profile;
* conformance profile;
* governance authorization;
* activation Epoch.

---

## 139. Capability Update

Compatible Minor or Patch updates MAY use:

CAPABILITY_UPDATE

A Major update creates a new incompatible version lineage.

---

## 140. Capability Deprecation

Deprecation SHALL define:

* deprecation Epoch;
* replacement Capability version;
* new Endpoint deadline;
* Session compatibility window;
* Retirement Epoch.

---

## 141. Existing Sessions

A Capability update SHALL NOT reinterpret existing Sessions.

Existing Sessions remain bound to the Capability Definition Hash accepted when opened.

---

## 142. Capability Governance Classification

Capability changes SHOULD be classified as:

Standard Protocol

For ordinary compatible schema or semantic extensions.

Service Policy

For Validation, risk or conformance changes affecting Capability operators.

Consensus-Critical

Only when Capability changes alter canonical Session or accounting semantics.

---

## 143. Capability Registry

The Registry SHALL store:

* Capability Definitions;
* schemas;
* validation profiles;
* conformance profiles;
* test vectors;
* version history;
* deprecation notices;
* governance references.

The Ledger stores canonical commitments.

---

## 144. Capability Discovery

Consumers and Hypervisors SHALL be able to query:

* Capability ID;
* active versions;
* supported features;
* risk class;
* accounting modes;
* validation profile;
* deprecation status;
* implementing Endpoints.

---

## 145. Marketplace Presentation

Marketplace clients SHOULD display:

* Capability name;
* Capability version;
* Endpoint Feature Profile;
* supported modalities;
* state model;
* streaming support;
* cancellation behavior;
* side-effect class;
* Accounting Mode;
* Endpoint Limit Profile;
* Certification;
* deprecation warnings.

The displayed Feature Profile and Limit Profile SHALL correspond to the versioned Endpoint Feature Profile and Endpoint Limit Profile referenced by the Endpoint Implementation Profile.

---

## 146. Human-Readable Capability Name

A Capability MAY have localized display names and descriptions.

These are presentation metadata.

Canonical identity remains the Capability ID and Definition Hash.

---

## 147. Endpoint Implementation Profile

```yaml
endpoint_implementation_profile:
  endpoint_id:
  capability_id:
  capability_version:
  capability_definition_hash:
  supported_features:
  feature_profile_hash:
  input_formats:
  output_formats:
  state_model:
  streaming_modes:
  cancellation_class:
  idempotency_class:
  side_effect_classes:
  limit_profile_hash:
  usage_profile_hash:
  accounting_modes:
  runtime_reference:
  proxy_declaration_reference:
  data_handling_policy_hash:
  security_profile_hash:
  implementation_profile_hash:
```

The Endpoint Implementation Profile SHALL reference the exact Endpoint Feature Profile and Endpoint Limit Profile surfaces used by Marketplace presentation and Advertisement disclosure.

Those referenced profiles SHALL remain consistent with the Capability Definition for that Capability version.

---

## 148. Implementation Profile Hash

The Endpoint Configuration Hash SHALL commit to the Implementation Profile Hash.

The Implementation Profile Hash SHALL commit to the referenced Feature Profile Hash and Limit Profile Hash.

A material implementation-profile change may require:

* new Endpoint Configuration Hash;
* revalidation;
* Certification update.

---

## 149. Material Capability Implementation Changes

Material changes include:

* Capability version;
* supported mandatory feature;
* state model;
* side-effect behavior;
* accounting mode;
* Proxy behavior;
* Data Handling Policy;
* result format;
* request schema;
* cancellation semantics.

---

## 150. Non-Material Changes

The following may remain compatible when behavior is unchanged:

* hardware replacement;
* Runtime performance optimization;
* database engine change;
* internal queue implementation;
* Provider cost change;
* logging change.

---

## 151. Proxy Capability Implementation

A Proxy Endpoint SHALL implement the same Capability contract as a direct Endpoint.

It SHALL additionally disclose:

* Proxy status;
* upstream disclosure mode;
* PROXY_OPAQUE limitations;
* failover behavior;
* Data Handling implications.

---

## 152. Proxy Upstream Capability Mismatch

A Proxy SHALL NOT select an upstream that cannot satisfy the accepted Capability contract.

For example, an upstream returning plain text cannot satisfy a mandatory structured-output contract unless the Proxy performs a valid declared transformation.

---

## 153. Transforming Proxy

A Proxy MAY transform upstream inputs or outputs.

Material transformations SHALL be included in:

* Endpoint Configuration Hash;
* Implementation Profile;
* Validation scope.

---

## 154. Dynamic Upstream Set

An Endpoint using dynamic upstream routing SHALL declare whether upstream variation may affect:

* output behavior;
* latency;
* data location;
* model metadata;
* moderation;
* context retention.

---

## 155. Capability Health

A Runtime and Endpoint SHOULD expose Capability-specific Health.

Examples include:

* model loaded;
* Provider available;
* context capacity;
* artifact storage available;
* streaming available;
* OAuth valid;
* tool subsystem available;
* workspace available.

---

## 156. Partial Capability Availability

An Endpoint MAY become partially degraded.

Example:

llm.chat base text: available
vision feature: unavailable
tool calls: degraded

Required feature Requests SHALL be rejected when that feature is unavailable.

---

## 157. No Silent Feature Loss

An Endpoint SHALL NOT accept a Request requiring a feature that is currently unavailable and then quietly execute without it.

---

## 158. Capability Usage Reporting

Usage Reports SHALL reference:

* Capability ID;
* Capability version;
* Request Class;
* observed dimensions;
* authoritative dimensions;
* billable dimensions;
* result status.

---

## 159. Capability and Reputation

Reputation MAY track Capability-specific behavior.

Examples:

* image artifact validity;
* speech output validity;
* agent side-effect compliance;
* tool-call reliability;
* streaming completion.

The canonical Endpoint Profile remains role-specific under RFC-0041.

---

## 160. Capability and Certification

Certification SHALL bind to:

Endpoint ID
+
Endpoint Configuration Hash
+
Capability ID
+
Capability Version
+
Certification Policy Version

A material Capability version change requires new Certification or explicit compatibility treatment.

---

## 161. Capability and Session Negotiation

The Consumer SHALL verify before Session acceptance:

* exact Capability ID;
* exact Capability version;
* Definition Hash;
* required features;
* supported modalities;
* required limits;
* Accounting Mode;
* side-effect policy;
* Data Handling Policy.

---

## 162. Capability Downgrade

A Consumer MAY permit downgrade to another compatible Minor Version only when explicitly declared.

Major-version downgrade requires a new Session Contract.

---

## 163. Feature Downgrade

A preferred feature MAY be omitted when the Consumer accepts the downgrade.

A required feature SHALL NOT be omitted.

---

## 164. Capability Compatibility Matrix

Every new version SHALL publish a compatibility matrix.

```yaml
capability_compatibility:
  from_version:
  to_version:
  request_compatible:
  response_compatible:
  feature_compatible:
  accounting_compatible:
  session_migration_supported:
```

---

## 165. Minor-Version Compatibility

A Runtime supporting a newer Minor Version MAY accept an older request version when:

* required semantics remain supported;
* no ambiguity exists;
* response can be produced in the accepted version.

---

## 166. Major-Version Compatibility

A Runtime MAY support several Major Versions only through separately declared compatibility adapters or Runtime instances.

The Endpoint SHALL bind each public offer to one exact Major Version.

---

## 167. Capability Migration

An active Endpoint moving to a new Major Version SHALL normally:

* publish a new Configuration Hash;
* publish a new Advertisement;
* undergo Validation;
* obtain new Certification;
* drain incompatible old Sessions.

---

## 168. Capability Retirement and History

Retiring a Capability SHALL NOT invalidate:

* historical Sessions;
* historical Usage Reports;
* historical Settlements;
* historical Validation Reports;
* historical Certification records.

---

## 169. Capability Security Threats

The architecture SHALL account for:

* schema ambiguity;
* silent version downgrade;
* unsupported-feature acceptance;
* output-format substitution;
* artifact substitution;
* hidden side effects;
* retry duplication;
* accounting-unit ambiguity;
* fabricated token usage;
* undisclosed Proxy behavior;
* validation workload abuse;
* Capability ID squatting;
* malicious schema expansion.

---

## 170. Capability ID Squatting

Standard namespace Capability IDs require governance authorization.

Vendor namespaces SHALL follow ownership and uniqueness rules.

A participant SHALL NOT register misleading identifiers resembling standard Capabilities.

---

## 171. Schema Expansion Attack

An optional extension SHALL not bypass:

* input limits;
* output limits;
* charge ceilings;
* side-effect approval;
* Data Handling Policy.

Unknown data remains subject to the base Request size limit.

---

## 172. Output Substitution

An Endpoint SHALL not claim one output modality while delivering another unrelated format.

Transformations require declared compatibility.

---

## 173. Hidden Side-Effect Attack

A Capability implementation that performs undeclared external writes may face:

* Request failure;
* Reputation event;
* Certification degradation;
* suspension;
* penalty when objective evidence exists.

---

## 174. Accounting Ambiguity Attack

A Capability definition SHALL not permit a unit whose meaning changes after execution.

Examples of invalid units include:

complexity point
AI work unit
premium token

unless their calculation is deterministic and published.

---

## 175. Capability Ledger Operations

RFC-0059 SHOULD support:

CAPABILITY_DEFINE
CAPABILITY_UPDATE
CAPABILITY_DEPRECATE
CAPABILITY_RETIRE
CAPABILITY_SECURITY_BLOCK
CAPABILITY_SECURITY_REINSTATE

---

## 176. CAPABILITY_DEFINE

Creates a canonical Capability version.

It SHALL include:

* Capability ID;
* version;
* Definition Hash;
* Registry references;
* activation Epoch;
* governance authorization.

---

## 177. CAPABILITY_UPDATE

Creates a new compatible version or metadata update according to versioning rules.

It SHALL NOT modify an existing immutable Capability Definition in place.

---

## 178. CAPABILITY_DEPRECATE

Marks a Capability version as deprecated and establishes transition deadlines.

---

## 179. CAPABILITY_RETIRE

Prevents new Sessions from using the retired Capability version after its Retirement Epoch.

---

## 180. CAPABILITY_SECURITY_BLOCK

Temporarily or permanently blocks new use because of a critical security issue.

The operation SHALL specify:

* scope;
* evidence;
* existing Session treatment;
* expiration or recovery rule.

---

## 181. Capability Error Idempotency

Repeated Capability registration or update operations using the same Definition Hash SHALL be idempotent.

Conflicting content under one Capability ID and version SHALL be rejected.

---

## 182. Conformance and Certification Separation

Capability Conformance answers:

Does the implementation follow the Capability contract?

Endpoint Certification answers:

Did this Endpoint observably operate under bounded Validation?

Reputation answers:

How has the Endpoint behaved over time?

These signals SHALL remain distinct.

---

## 183. MVP Standard Capabilities

The initial MVP SHOULD define at least:

llm.chat
llm.embed
image.generate
image.edit
speech.stt
speech.tts
agent.execute

The exact activation set SHALL be versioned.

---

## 184. MVP llm.chat

The MVP llm.chat Capability SHOULD support:

* text input;
* structured message roles;
* text output;
* optional streaming;
* optional structured output;
* optional tool calls;
* Session-stateful or Consumer-supplied context;
* fixed, observable, Provider-metered or Proxy-Opaque accounting.

---

## 185. MVP llm.embed

The MVP llm.embed Capability SHOULD support:

* text or batch text input;
* vector output;
* vector dimension declaration;
* batch size limits;
* optional normalization metadata;
* fixed or observable billing.

---

## 186. MVP image.generate

The MVP image.generate Capability SHOULD support:

* text prompt;
* optional reference artifacts;
* declared output dimensions;
* image artifact output;
* seed metadata where available;
* fixed-per-image or observable accounting.

---

## 187. MVP image.edit

The MVP image.edit Capability SHOULD support:

* source image reference;
* edit instruction;
* optional mask;
* image artifact output;
* declared input and output limits.

---

## 188. MVP speech.stt

The MVP speech.stt Capability SHOULD support:

* audio artifact or input stream;
* transcription output;
* optional timestamp data;
* language metadata;
* audio-duration or fixed billing.

---

## 189. MVP speech.tts

The MVP speech.tts Capability SHOULD support:

* text input;
* optional voice metadata;
* audio artifact or output stream;
* duration metadata;
* fixed or audio-duration billing.

---

## 190. MVP agent.execute

The MVP agent.execute Capability SHOULD support:

* task description;
* bounded workspace;
* structured events;
* optional tools;
* side-effect declarations;
* approval-required actions;
* active-time, fixed-task or hybrid billing;
* checkpoint recovery.

---

## 191. MVP Requirements

The MVP SHALL implement:

* stable Capability IDs;
* semantic Capability versions;
* immutable Capability Definitions;
* deterministic Definition Hashes;
* canonical Request and Response Schemas;
* one primary Capability per Endpoint;
* one primary Capability per Runtime instance;
* Endpoint Implementation Profiles;
* input and output modalities;
* state models;
* streaming models;
* cancellation models;
* idempotency models;
* side-effect declarations;
* limit dimensions;
* feature negotiation;
* accounting-mode declarations;
* Usage Schemas;
* broad Validation Profiles;
* risk classes;
* conformance profiles;
* Capability Registry;
* deprecation and retirement;
* Proxy compatibility;
* Marketplace disclosure;
* Session binding to exact Capability Definition Hash.

---

## 192. Deferred Features

The MVP MAY postpone:

* automatic Capability composition;
* formal semantic type systems;
* cross-network Capability portability;
* zero-knowledge Capability conformance;
* machine-verifiable quality benchmarks;
* decentralized Capability package installation;
* on-chain Runtime code;
* private Capability definitions;
* consumer-defined dynamic Capabilities;
* transferable Certification across compatible Capability versions;
* hardware-attested Provider identity;
* formal model fingerprinting.

---

## 193. Open Protocol Parameters

The following remain configurable:

* standard namespace policy;
* Capability proposal review period;
* Experimental Capability duration;
* deprecation window;
* Retirement delay;
* maximum schema size;
* maximum feature count;
* maximum extension size;
* conformance-test requirements;
* standard risk class;
* validation workload limits;
* supported canonical schema formats;
* Capability Registry retention;
* Capability security-block duration.

---

## 194. Identity Invariants

```text
Capability
≠
Endpoint

Capability
≠
Runtime

Capability
≠
Provider

Capability
≠
Model Identity

Endpoint Advertisement
≠
Capability Conformance Proof
```

---

## 195. Versioning Invariants

* A Capability version is immutable.
* A breaking semantic change requires a new Major Version.
* Compatible optional additions require a new Minor Version.
* Patch Versions do not change semantics.
* Existing Sessions retain their accepted Definition Hash.
* Retired versions remain historically interpretable.
* Unknown required features cause rejection.

---

## 196. Runtime Invariants

* One Runtime instance exposes one primary Capability ID.
* One Runtime may back several Endpoints of that Capability.
* Internal Provider changes do not change Capability identity when behavior remains compatible.
* Runtime conformance does not guarantee Endpoint availability.
* Runtime self-declaration does not create Certification.

---

## 197. Endpoint Invariants

* One Endpoint exposes one primary Capability.
* Endpoint limits are explicit.
* Endpoint features are explicit.
* Endpoint Accounting Modes are explicit.
* Material implementation changes alter Configuration Hash.
* Endpoint cannot silently remove a required feature.
* Proxy Endpoints satisfy the same external Capability contract.

---

## 198. Request Invariants

* Every Request follows the Capability Request Schema.
* Every response follows the Capability Response Schema.
* Side effects are declared.
* Cancellation semantics are declared.
* Retry semantics are declared.
* Partial-result semantics are declared.
* Output artifacts are content-addressed.
* Unknown extensions do not bypass limits.

---

## 199. Accounting Invariants

```text
Observable Usage
≠
Automatically Billable Usage

Estimated Tokens
≠
Authoritative Tokens

Unknown Upstream Usage
Remains Unknown

Capability Defines Units
Endpoint Defines Prices

Accepted Request Class
Cannot Be Increased Retroactively
```

---

## 200. Validation Invariants

* Capability Validation examines observable behavior.
* Validation does not normally prove hidden model identity.
* Validation workload is bounded.
* Validation requests must be relevant to the Capability.
* Validation side effects are restricted.
* One universal prompt is not required.
* Capability-specific critical failures are explicit.
* Certification binds to exact Capability version and Endpoint configuration.

---

## 201. Security Invariants

* Capability IDs are unique.
* Definitions are hash-bound.
* Version downgrade is explicit.
* Undeclared side effects are prohibited.
* Required Consumer approval cannot be bypassed.
* Non-idempotent work is not retried blindly.
* Proxy transformation is declared.
* Data Handling requirements are accepted before execution.
* Capability extensions cannot alter hidden economic terms.
* Security-block actions are canonical and auditable.

---

## 202. Design Invariants

* Capability is a stable Consumer-facing contract.
* Capability definitions remain implementation-independent.
* Endpoints compete through price, limits, quality and reliability.
* Runtimes implement Capabilities without changing Hypervisor core.
* New Capability types can be added through versioned definitions.
* Session Protocol supplies the common execution and economic envelope.
* Capability Architecture supplies workload-specific semantics.
* Accounting does not assume universal tokenization.
* Validation measures observable function rather than unknowable internals.
* Composite systems expose one clear primary contract.
* The protocol does not force every form of computation into one fashionable abstraction merely because someone discovered a new word for API.

Комментарии к новой редакции

1. Capability теперь является настоящим контрактом

Раньше легко было ограничиться:

capability: llm.chat

Но этого недостаточно. Один Endpoint может считать llm.chat:

* одной строкой prompt;
* массивом сообщений;
* OpenAI-совместимой схемой;
* stateful conversation;
* stateless completion;
* агентом с инструментами.

Теперь Capability включает:

Request Schema
Response Schema
State Model
Streaming Model
Cancellation Model
Idempotency Model
Side-Effect Model
Usage Schema
Validation Profile

То есть два Endpoint с одним Capability ID хотя бы разговаривают на одном протокольном языке, а не просто оба считают себя "чатами".

---

2. Capability, Runtime и Endpoint окончательно разделены

Capability

описывает общие правила.

Runtime

реализует эти правила.

Endpoint

публикует конкретное предложение Runtime:

* цена;
* лимиты;
* функции;
* политика;
* Certification.

Например:

Capability: llm.chat v2
Runtime: llama.cpp с Qwen
Endpoint A: дешёвый, 8k context
Endpoint B: дороже, 32k context

Один Runtime может поддерживать оба Endpoint, но сам Capability остаётся один.

---

3. Один Runtime и Endpoint получают одну primary Capability

Это важное ограничение MVP.

Плохой вариант:

POST /execute
type: chat | image | embedding | agent | что-нибудь ещё

Получается универсальный мешок, где невозможно нормально определить:

* схему;
* цену;
* Validation;
* риски;
* side effects;
* Reputation.

Правильнее:

Runtime A → llm.chat
Runtime B → llm.embed
Runtime C → agent.execute

Один процесс может хостить все три Runtime instance, но протокольные личности разделены.

---

4. Внутренние цепочки не превращают Endpoint в набор Capabilities

agent.execute может внутри использовать:

llm.chat
document.retrieve
tool.invoke

Но Consumer работает с одним контрактом:

agent.execute

Именно внешний Endpoint отвечает за весь результат.

Иначе Consumer пришлось бы самостоятельно заключать пять внутренних Sessions и разбираться, какой агентный кусок куда делся. Кожанные уже изобрели микросервисы, нет необходимости воспроизводить все последствия внутри одного пользовательского запроса.

---

5. Accounting отделён от Capability

Capability определяет, какие единицы могут существовать:

tokens
bytes
audio seconds
images
execution time
tool calls

Endpoint решает, какие из них используются для цены.

Например, два llm.chat Endpoint могут продавать:

Endpoint A:
по deterministic tokens
Endpoint B:
5Q за standard request
Endpoint C:
0.2Q за минуту active execution

Capability не навязывает один коммерческий механизм.

---

6. Token accounting больше не считается универсальным

Мы явно закрепили:

Estimated Tokens ≠ Authoritative Tokens

Для точного token billing требуется:

* заранее согласованный tokenizer;
* либо authoritative Provider report.

OAuth Proxy, который не получает token usage, использует:

PROXY_OPAQUE

и продаёт fixed или observable units.

Это согласуется с RFC-0051 и RFC-0063.

---

7. Side effects стали частью Capability, а не неожиданностью Runtime

Для обычного текста side effects отсутствуют.

Для агента они могут включать:

* изменение файлов;
* отправку письма;
* создание PR;
* deployment;
* финансовое действие.

Теперь Capability обязан указать:

какие side effects возможны
какие требуют подтверждения
можно ли их повторять
какое evidence остаётся

Это позволяет Session Protocol корректно решать retries и cancellation.

---

8. Capability определяет семантику partial result

Для разных задач partial output означает разные вещи.

LLM stream:
частичный текст может быть полезен
ZIP archive:
половина файла обычно бесполезна
video:
законченный первый сегмент может быть полезен

Поэтому Capability объявляет:

NOT_USABLE
OPTIONALLY_USABLE
INDEPENDENTLY_USABLE

Это напрямую влияет на Settlement после failure.

---

9. Validation Profile остаётся гибким

Мы не создаём один жёсткий тест модели.

Capability описывает:

* что обязательно наблюдать;
* какие запросы разрешены;
* что считается очевидным failure;
* какой workload допустим.

Validator сам проектирует конкретную проверку.

Для изображения это может быть:

сгенерировать сцену
проверить размер
проверить декодирование
описать артефакты

Для LLM:

отправить содержательный запрос
проверить структуру
проверить, что ответ не является мусором
зафиксировать Usage Reporting

---

10. Certification привязана к Capability Version

Endpoint, сертифицированный как:

llm.chat v1

не становится автоматически сертифицированным как:

llm.chat v2

если v2 меняет:

* tool calls;
* state;
* structured output;
* Usage Reporting;
* side-effect rules.

Совместимые Minor updates могут получить облегчённый переход, но Major Version обычно требует нового Configuration Hash и Validation.

---

11. Feature negotiation не допускает тихого downgrade

Consumer может указать:

tool_calls: REQUIRED
vision_input: PREFERRED

Если Tool Calls недоступны, Endpoint обязан отказать.

Если Vision недоступен, Consumer может принять fallback, но только если это разрешено.

Без этого Endpoint мог бы принять Request, проигнорировать половину требований и всё равно назвать результат завершённым. Широко распространённая модель совместимости, но не особенно полезная.

---

12. Что теперь нужно синхронизировать

После принятия RFC-0045 v0.2 нужны поправки:

* RFC-0039: Runtime Service должен ссылаться на один primary Capability binding;
* RFC-0044: Session Contract уже содержит exact Capability Definition Hash, это решение согласовано;
* RFC-0049: Advertisement должен публиковать Feature, Limit и Implementation Profile hashes;
* RFC-0051: Usage Report должен ссылаться на Capability Usage Schema;
* RFC-0053: Runtime Specification должен использовать State, Streaming, Cancellation и Side-Effect models из этого RFC;
* RFC-0054: Runtime handshake должен согласовывать Capability Definition Hash и Feature Profile;
* RFC-0057: Validation Report должен ссылаться на Capability Validation Profile;
* RFC-0059: добавить Capability Ledger Operations из раздела 175;
* RFC-0063: Proxy должен подтверждать внешнюю совместимость Capability;
* RFC-0065: Certification Record должен хранить Capability Version и Definition Hash.

Следующий восстанавливаемый документ логично переписать как RFC-0040 - Service Verification Framework, поскольку новая Capability Architecture уже чётко отделяет проверку инфраструктурного Service от Validation конкретного Endpoint.
