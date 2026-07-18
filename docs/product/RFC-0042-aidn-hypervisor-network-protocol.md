RFC-0042

AiDN Hypervisor Network Protocol and Dispatcher Architecture

Status: Draft

Version: 0.5

Revision note: application protocols extend the Dispatcher through authorized
profiles rather than becoming dependencies of the transport foundation. Runtime
routes bind both Runtime Generation and independently mutable Route Generation.

Supersedes:

* RFC-0042 Version 0.4 - AiDN Hypervisor Network Protocol and Dispatcher Architecture

Depends on:

* RFC-0036 AiDN Ledger State Machine
* RFC-0039 Hypervisor Service Model

Extended by:

* RFC-0040 through RFC-0067 application, consensus, Registry, Runtime,
  Session, Validation, Plugin, recovery and upgrade profiles as applicable.

---

## 1. Purpose

This document defines the AiDN Hypervisor Network Protocol and the mandatory
internal Network Dispatcher architecture used by every conforming Hypervisor.

It specifies how Hypervisors and authorized Services:

* discover peers;
* establish authenticated connections;
* verify network identity;
* negotiate protocol versions;
* advertise available Services;
* route protocol messages;
* multiplex independent channels;
* transport Session data;
* reconnect and resume interrupted communication;
* enforce rate limits and flow control;
* relay messages when direct communication is unavailable;
* protect against replay, duplication and message substitution;
* expose stable network errors;
* preserve application-level protocol boundaries.

This protocol provides the common network layer for AiDN Services.

All external and cross-component AiDN traffic SHALL pass through the Network
Dispatcher. Services, Runtimes and Provider Plugins SHALL use scoped Dispatcher
interfaces and SHALL NOT impersonate another protocol subject or bypass
authorization and route-generation checks.

---

## 2. Core Principle

The Hypervisor Network Protocol transports authenticated protocol messages between identifiable participants.

It SHALL NOT redefine the semantics of:

* Ledger Operations;
* Sessions;
* Capabilities;
* Usage Reports;
* Validation Reports;
* Registry objects;
* Consensus messages;
* Settlements.

Conceptually:

```text
Transport
    ↓
Authenticated Connection
    ↓
Message Envelope
    ↓
Routing
    ↓
Role-Specific Protocol
```

The network layer determines how a message reaches its destination.

The destination protocol determines what the message means.

---

## 3. Protocol Scope

The protocol covers:

Hypervisor ↔ Hypervisor
Service ↔ Hypervisor
Runtime ↔ Hypervisor
Consumer Client ↔ Hypervisor
Relay Hypervisor ↔ Destination Hypervisor

It does not replace the internal transport protocol used by CometBFT for canonical Consensus.

---

## 4. Consensus Transport Boundary

CometBFT MAY use its own peer-to-peer networking for:

* block proposals;
* prevotes;
* precommits;
* consensus evidence;
* block synchronization.

RFC-0042 SHALL still support:

* Consensus Service discovery;
* Consensus Service Health;
* Validator readiness;
* Consensus endpoint advertisement;
* configuration exchange;
* operational control messages.

AiDN application traffic SHALL NOT be silently inserted into consensus vote channels.

---

## 5. Transport Independence

The Hypervisor Network Protocol is logically independent of one physical transport.

A conforming implementation MAY use:

* QUIC;
* TCP with TLS;
* WebSocket over TLS;
* Unix domain sockets;
* another authenticated ordered transport.

Every supported Transport Profile SHALL preserve the same protocol semantics.

---

## 6. Initial Transport Profiles

The MVP SHOULD support:

QUIC_TLS
TCP_TLS
WEBSOCKET_TLS
LOCAL_IPC

QUIC_TLS is the preferred public peer transport.

LOCAL_IPC is intended for Services running on the same trusted host.

---

## 7. Transport Profile Definition

```yaml
transport_profile:
  transport_profile_id:
  protocol_family:
  encryption_required:
  mutual_authentication:
  stream_multiplexing:
  message_framing:
  maximum_frame_size:
  keepalive_model:
  migration_support:
  profile_version:
```

---

## 8. Public Transport Encryption

All public Hypervisor connections SHALL use authenticated encryption.

Plaintext public transport SHALL NOT be permitted.

---

## 9. Local IPC

Local IPC MAY omit transport-layer encryption only when:

* the communication remains inside one trusted operating-system boundary;
* peer identity is authenticated through operating-system credentials or equivalent controls;
* the channel cannot be reached by unrelated users or containers;
* message-level authentication remains available where required.

---

## 10. Hypervisor Identity

Every Hypervisor SHALL authenticate using its registered Hypervisor Identity.

The connection identity SHALL bind to:

network_id
+
chain_id
+
network_revision
+
hypervisor_id
+
node_public_key

---

## 11. Identity Separation

The transport identity SHALL remain distinct from:

* Wallet spending key;
* Consensus signing key;
* Service key;
* Runtime key;
* Governance key;
* Endpoint Session key.

A public network connection SHALL NOT require exposure of Wallet private keys.

---

## 12. Connection Identity

Every authenticated connection SHALL have:

```yaml
connection_identity:
  connection_id:
  local_hypervisor_id:
  remote_hypervisor_id:
  network_id:
  chain_id:
  network_revision:
  negotiated_transport_profile:
  negotiated_protocol_version:
  established_at:
  connection_nonce:
```

---

## 13. Connection ID

Recommended derivation:

```text
connection_id
=
HASH(
    local_hypervisor_id
    +
    remote_hypervisor_id
    +
    connection_nonce_a
    +
    connection_nonce_b
    +
    network_revision
)
```

A Connection ID identifies one authenticated connection instance.

It is not a permanent peer identity.

---

## 14. Network Domain Validation

A Hypervisor SHALL reject a peer claiming a different:

* Network ID;
* Chain ID;
* Network Revision;

unless a specific compatibility or recovery protocol explicitly permits read-only communication.

---

## 15. Network Revision Mismatch

A peer from another Network Revision SHALL receive:

NETWORK_REVISION_MISMATCH

The connection MAY remain open only for explicitly supported:

* recovery diagnostics;
* historical Registry retrieval;
* fork analysis.

It SHALL NOT carry ordinary mutable protocol traffic.

---

## 16. Protocol Version Negotiation

Peers SHALL advertise:

* minimum supported protocol version;
* maximum supported protocol version;
* active preferred version;
* compatible message profiles;
* required security features.

---

## 17. Version Selection

The selected protocol version SHALL be the highest mutually supported version that:

* is active on the current network;
* satisfies mandatory security requirements;
* supports the required channel;
* is not blocked by protocol policy.

---

## 18. No Silent Version Downgrade

A peer SHALL NOT silently select a lower version when:

* the higher version is required by the active network;
* the lower version lacks mandatory security behavior;
* the destination Service requires the higher version.

A downgrade SHALL be explicit and visible in the handshake.

---

## 19. Compatibility Window

During an authorized Compatibility Window, a Hypervisor MAY support more than one protocol version.

Each connection SHALL still use one clearly negotiated version for a given message channel unless the protocol explicitly supports per-message versioning.

---

## 20. Handshake Lifecycle

An external connection follows:

TRANSPORT_CONNECTING
    ↓
HELLO_EXCHANGING
    ↓
IDENTITY_VERIFYING
    ↓
VERSION_NEGOTIATING
    ↓
SERVICE_NEGOTIATING
    ↓
ESTABLISHED

Alternative states include:

REJECTED
QUARANTINED
DRAINING
CLOSED

---

## 21. Client Hello

The initiating peer SHALL send:

```yaml
hypervisor_client_hello:
  network_id:
  chain_id:
  network_revision:
  hypervisor_id:
  node_public_key:
  identity_version:
  supported_transport_profiles:
  supported_protocol_versions:
  supported_message_profiles:
  advertised_services_summary:
  connection_nonce:
  timestamp:
  challenge:
  signature:
```

---

## 22. Server Hello

The receiving peer SHALL respond with:

```yaml
hypervisor_server_hello:
  network_id:
  chain_id:
  network_revision:
  hypervisor_id:
  node_public_key:
  identity_version:
  selected_transport_profile:
  selected_protocol_version:
  selected_message_profiles:
  connection_nonce:
  client_challenge_response:
  server_challenge:
  timestamp:
  signature:
```

---

## 23. Handshake Completion

The initiator SHALL complete mutual authentication by signing the server challenge.

The connection becomes established only after:

* both identities are verified;
* network domain matches;
* protocol version is selected;
* required security features succeed;
* Service negotiation completes or is explicitly deferred.

---

## 24. Handshake Replay Protection

Handshake messages SHALL include:

* fresh nonces;
* challenge-response;
* expiration;
* network domain;
* peer identities.

A previously captured handshake SHALL NOT establish a new valid connection.

---

## 25. Clock Skew

Timestamps MAY support freshness checks.

Freshness SHALL NOT rely only on wall-clock agreement.

Nonce and challenge validation remain mandatory.

A configured maximum clock skew MAY be used for diagnostics and rejection of obviously stale messages.

---

## 26. Quarantine State

A connection MAY enter QUARANTINED when:

* identity is valid but Service claims are inconsistent;
* version compatibility is uncertain;
* the peer is under security review;
* canonical registration cannot currently be retrieved;
* rate-limit abuse was recently observed.

A quarantined connection SHALL have restricted channels.

---

## 27. Peer Discovery

Hypervisors MAY discover peers through:

STATIC_CONFIGURATION
GENESIS_SEEDS
DNS_SEEDS
REGISTRY_DISCOVERY
PEER_EXCHANGE
LOCAL_DISCOVERY
OPERATOR_INPUT

---

## 28. Discovery Is Not Trust

Discovery provides a possible network address.

It does not establish:

* canonical identity;
* eligibility;
* Service verification;
* reliability;
* current Health.

Every discovered peer SHALL complete authentication.

---

## 29. Peer Record

```yaml
peer_record:
  hypervisor_id:
  network_addresses:
  transport_profiles:
  supported_protocol_range:
  service_summary:
  last_observed_epoch:
  record_expiration:
  source_type:
  source_reference:
  record_signature:
```

---

## 30. Peer Record Expiration

Peer Records SHALL expire.

An expired record MAY be used as a low-confidence connection hint but SHALL NOT be presented as current availability.

---

## 31. Peer Exchange

An established peer MAY provide bounded peer recommendations.

Peer Exchange SHALL be:

* rate-limited;
* size-limited;
* source-attributed;
* non-authoritative;
* protected against recursive amplification.

---

## 32. Discovery Diversity

A Hypervisor SHOULD use several discovery sources when practical.

Depending on one seed operator creates an avoidable bootstrap failure domain.

---

## 33. Network Address

A Hypervisor MAY advertise multiple addresses:

PUBLIC_DIRECT
PRIVATE_DIRECT
RELAY_REQUIRED
ONION_OR_PRIVACY_NETWORK
LOCAL_ONLY

The exact supported address classes are Transport Profile specific.

---

## 34. Address Scope

A private or local address SHALL NOT be advertised as globally reachable.

Every address SHALL include a scope and expiration.

---

## 35. NAT and Firewall Traversal

A Hypervisor behind NAT MAY use:

* outbound persistent connections;
* QUIC connection migration;
* relay Services;
* operator-configured port forwarding;
* future hole-punching profiles.

NAT traversal SHALL NOT weaken identity authentication.

---

## 36. Direct Communication Preference

Peers SHOULD prefer a direct authenticated connection when:

* reachable;
* policy-compatible;
* economically reasonable;
* privacy-compatible.

Relay use remains permitted.

---

## 37. Relay Communication

A Relay Hypervisor forwards opaque authenticated messages between peers unable or unwilling to establish a direct connection.

A relay SHALL NOT become the logical sender of the forwarded application message.

---

## 38. Relay Envelope

```yaml
relay_envelope:
  relay_message_id:
  source_hypervisor_id:
  destination_hypervisor_id:
  inner_message_hash:
  relay_path:
  hop_limit:
  expiration:
  source_signature:
```

The inner message SHOULD remain end-to-end authenticated and encrypted where practical.

---

## 39. Relay Responsibility

A relay is responsible for:

* forwarding integrity;
* route limits;
* rate limits;
* relay availability;
* not modifying the inner message.

It is not responsible for the semantic validity of the inner application message.

---

## 40. Relay Hop Limit

Every relayed message SHALL include a Hop Limit.

Recommended MVP default:

MaximumRelayHops = 2

Messages exceeding the limit SHALL be rejected.

---

## 41. Relay Loop Prevention

Relay paths SHALL record visited Relay commitments.

A Relay SHALL reject a message when:

* its own commitment already appears;
* the destination equals the source;
* the Hop Limit is exhausted;
* the path integrity fails.

---

## 42. Relay Privacy

A relay MAY learn:

* source route;
* destination route;
* message size;
* timing;
* channel class.

End-to-end encryption SHOULD prevent the relay from learning application payloads where the application protocol permits it.

---

## 43. Relay Economics

Relay payment, if introduced, SHALL be defined separately.

The MVP SHALL NOT create hidden relay charges inside Session billing.

---

## 44. Connection Multiplexing

One physical connection MAY carry several logical channels.

Initial channel classes are:

CONTROL
SERVICE_CONTROL
SESSION_CONTROL
SESSION_DATA
RUNTIME
REGISTRY
VALIDATION
GOVERNANCE
OBSERVABILITY

---

## 45. Consensus Channel Exclusion

Consensus vote and block-proposal traffic SHOULD remain on the CometBFT transport.

A future profile MAY explicitly bridge consensus traffic, but RFC-0042 does not define such bridging in the MVP.

---

## 46. Channel Identity

Every logical channel SHALL have:

```yaml
channel_identity:
  channel_id:
  channel_class:
  source_subject:
  destination_subject:
  protocol_profile:
  protocol_version:
  priority:
  opened_at:
```

---

## 47. Channel Authorization

A connection identity does not automatically authorize every channel.

Channel creation SHALL verify:

* source role;
* destination role;
* Service authorization;
* protocol compatibility;
* rate limits;
* suspension state;
* privacy policy.

---

## 48. Channel Priorities

Initial priority classes are:

CRITICAL_CONTROL
HIGH
NORMAL
BULK
BACKGROUND

Examples:

* connection control: CRITICAL_CONTROL;
* Session cancellation: HIGH;
* ordinary Request: NORMAL;
* Registry replication: BULK;
* historical synchronization: BACKGROUND.

---

## 49. Priority Safety

Bulk Registry synchronization SHALL NOT indefinitely starve:

* Session cancellation;
* Deposit warnings;
* Service Health;
* connection control;
* emergency messages.

---

## 50. Message Envelope

All Hypervisor-routed messages SHALL use a common envelope.

```yaml
network_message:
  message_id:
  message_type:
  message_version:
  network_id:
  chain_id:
  network_revision:
  connection_id:
  channel_id:
  source_subject:
  destination_subject:
  correlation_id:
  causation_id:
  sequence:
  priority:
  created_at:
  expiration:
  hop_limit:
  payload_hash:
  payload_length:
  payload_encoding:
  authentication:
```

---

## 51. Source Subject

The source MAY be:

HYPERVISOR
SERVICE
RUNTIME
ENDPOINT
CONSUMER_SESSION
PROTOCOL

The source identity SHALL be authorized for the message type.

---

## 52. Destination Subject

The destination MAY identify:

* Hypervisor ID;
* Service ID;
* Runtime ID;
* Endpoint ID;
* Session ID;
* protocol role;
* broadcast group where explicitly supported.

---

## 53. Message ID

Every message SHALL have a stable unique Message ID.

Recommended derivation:

```text
message_id
=
HASH(
    source_subject
    +
    destination_subject
    +
    message_type
    +
    source_sequence
    +
    message_nonce
)
```

---

## 54. Correlation ID

A Correlation ID links:

* Request to Response;
* Challenge to Response;
* Open to Accept;
* command to Result.

It does not replace Message ID.

---

## 55. Causation ID

A Causation ID references the message or canonical event that caused the new message.

This supports audit and distributed tracing.

---

## 56. Message Sequence

Each ordered source-channel pair SHALL maintain a monotonically increasing sequence.

The destination SHALL detect:

* duplicate sequence;
* gap;
* replay;
* conflicting message under one sequence.

---

## 57. Unordered Messages

A protocol profile MAY explicitly mark messages as unordered.

Unordered messages SHALL still have:

* Message ID;
* replay protection;
* expiration;
* authentication.

---

## 58. Payload Hash

The envelope SHALL commit to the exact payload.

A payload whose content does not match payload_hash SHALL be rejected.

---

## 59. Payload Encoding

Initial supported encodings MAY include:

CANONICAL_CBOR
CANONICAL_JSON
PROTOBUF_PROFILE
RAW_BINARY_REFERENCE

The active message profile SHALL define the canonical representation used for signatures and hashes.

---

## 60. Canonical Serialization

Canonical signing SHALL not depend on:

* map field order;
* whitespace;
* locale;
* floating-point formatting;
* implementation-specific serialization.

---

## 61. Large Payloads

Large objects SHOULD NOT be inserted directly into ordinary message frames.

They SHOULD use:

* artifact references;
* Registry object references;
* chunked transfer;
* dedicated bulk stream.

---

## 62. Maximum Frame Size

Every Transport Profile SHALL define a Maximum Frame Size.

Oversized payloads SHALL be rejected or transferred through an approved chunking profile.

---

## 63. Chunked Transfer

Chunked transfer SHALL include:

```yaml
network_chunk:
  transfer_id:
  object_hash:
  chunk_sequence:
  chunk_hash:
  chunk_length:
  final_chunk:
```

---

## 64. Chunk Integrity

The receiver SHALL detect:

* missing chunks;
* duplicate chunks;
* conflicting chunks;
* incorrect object root;
* unexpected total size.

---

## 65. End-to-End Authentication

Application messages SHOULD be authenticated by their logical source in addition to transport authentication when they:

* create economic exposure;
* alter canonical state;
* create Validation evidence;
* create Usage evidence;
* authorize side effects;
* carry governance decisions.

---

## 66. Hop-by-Hop Authentication

Every transport hop SHALL authenticate the immediate peer.

Hop authentication does not replace end-to-end message signatures where required.

---

## 67. Authorization Before Routing

A Hypervisor SHALL verify that the source is permitted to send the message type before forwarding it to a local Service.

Examples:

* Runtime cannot submit Governance Vote;
* Registry cannot authorize Wallet transfer;
* Consumer Session key cannot register Service;
* Validation Service cannot sign Consensus vote.

---

## 68. Unknown Message Type

An unknown message SHALL be handled according to its profile:

IGNORE_IF_OPTIONAL
REJECT
CLOSE_CHANNEL
CLOSE_CONNECTION

Unknown mandatory control messages SHALL cause negotiation failure.

---

## 69. Unsupported Optional Field

Unknown optional fields MAY be ignored when the active schema explicitly permits forward-compatible extensions.

Unknown required fields SHALL cause rejection.

---

## 70. Request-Response Pattern

The network layer SHALL support a standard request-response pattern.

A response SHALL reference the Request's Correlation ID.

---

## 71. Event Pattern

A Service MAY emit asynchronous events.

Events SHALL:

* identify source;
* identify intended audience;
* be sequence-aware where ordering matters;
* be rate-limited;
* not imply canonical state unless canonically committed.

---

## 72. Subscription Pattern

A peer MAY subscribe to bounded event topics.

Examples include:

* Endpoint Health;
* Registry object availability;
* Session state;
* upgrade readiness.

Subscriptions SHALL be authorized and rate-limited.

---

## 73. Broadcast

Global broadcast SHALL be avoided for ordinary application messages.

Supported broadcast scopes MAY include:

CONNECTED_PEERS
SERVICE_ROLE_GROUP
ACTIVE_VALIDATOR_GROUP
SUBSCRIBED_GROUP

Every broadcast profile SHALL define deduplication and Hop Limits.

---

## 74. Gossip

Selected object classes MAY use gossip dissemination.

Gossip objects SHALL be:

* content-addressed;
* deduplicated;
* expiration-bound;
* source-attributed;
* size-limited.

Registry replication details belong to RFC-0061.

---

## 75. Service Advertisement

A Hypervisor MAY advertise authorized Services through:

```yaml
service_network_advertisement:
  hypervisor_id:
  service_id:
  service_role:
  service_state:
  service_protocol_version:
  configuration_hash:
  network_addresses:
  feature_summary:
  health_summary:
  verification_reference:
  expiration:
  hypervisor_signature:
  service_signature:
```

---

## 76. Advertisement Is Not Verification

A Service Network Advertisement proves only that the signed claim was published.

It SHALL NOT be treated as proof of:

* availability;
* completeness;
* eligibility;
* independent ownership;
* current verification.

---

## 77. Service Directory Exchange

Established Hypervisors MAY exchange compact Service directories.

Directory entries SHALL remain expiration-bound.

Canonical Service registration remains authoritative.

---

## 78. Local Service Connection

A local or remote Service connects to its operating Hypervisor through the Service Control Plane.

The Service SHALL authenticate:

* Service ID;
* Service key;
* Service role;
* operator authorization;
* configuration hash;
* supported protocol versions.

---

## 79. Service Connection Lifecycle

DISCOVERED
    ↓
AUTHENTICATING
    ↓
AUTHORIZED
    ↓
NEGOTIATING
    ↓
READY

Alternative states include:

DEGRADED
DRAINING
DISCONNECTED
REVOKED

---

## 80. Service Hello

```yaml
service_hello:
  service_id:
  service_role:
  service_public_key:
  operator_hypervisor_id:
  configuration_hash:
  service_protocol_versions:
  supported_message_profiles:
  local_operational_state:
  connection_nonce:
  challenge:
  signature:
```

---

## 81. Service Authorization Response

The Hypervisor SHALL return:

* authorization state;
* selected protocol version;
* permitted channel classes;
* public canonical Service state;
* current Network Revision;
* active policy references;
* a challenge response.

---

## 82. Service Authorization Revocation

When Service authorization is revoked:

* new channels SHALL be denied;
* existing channels SHALL drain or terminate;
* pending obligations SHALL be preserved;
* evidence SHALL remain attributable;
* canonical state updates SHALL follow the applicable RFC.

---

## 83. Runtime Network Channel

Capability Runtime traffic SHALL use the Runtime channel profile from RFC-0054.

The Hypervisor SHALL route:

* execution requests;
* cancellation;
* stream events;
* Usage Reports;
* Health;
* recovery state;
* artifact references.

---

## 84. Runtime Identity Boundary

A Runtime SHALL NOT receive traffic for a Capability or Endpoint it is not authorized to serve.

---

## 85. Endpoint Routing

Routing to an Endpoint SHALL resolve:

Endpoint ID
    ↓
Endpoint Configuration
    ↓
Authorized Runtime
    ↓
Current Runtime Connection

A stale Endpoint-to-Runtime mapping SHALL not be used after a material configuration update.

---

## 86. Session Control Routing

Session control messages include:

* Session Open notifications;
* Session Accept or Reject;
* Deposit extension notice;
* Session amendment;
* close messages;
* recovery;
* Settlement state.

They SHALL use SESSION_CONTROL.

---

## 87. Session Data Routing

Request payloads, streams and artifacts SHALL use SESSION_DATA or content references.

Bulk payloads SHOULD use separate streams from critical Session control.

---

## 88. Session Message Binding

Every Session-routed message SHALL reference:

* Session ID;
* Session Contract Hash;
* source Session identity;
* destination Endpoint or Consumer identity;
* applicable message sequence.

---

## 89. Session Route Migration

A Session MAY survive transport reconnection or Endpoint Runtime relocation.

A new route SHALL prove:

* same Session Contract;
* same Endpoint identity;
* valid Runtime authorization;
* correct recovery sequence.

---

## 90. Consumer Client Connection

A Consumer client MAY connect directly to an Endpoint Hypervisor or through a gateway.

The Consumer SHALL authenticate using:

* Wallet authority for economic control messages;
* scoped Session keys for Session traffic.

---

## 91. Gateway Client Routing

A gateway routing Consumer traffic SHALL NOT gain authority to:

* increase Deposit;
* alter Request charge ceiling;
* modify Session Contract;
* acknowledge Checkpoints;
* approve side effects;

unless explicitly authorized by the Consumer.

---

## 92. Validation Routing

Validation traffic MAY include:

* private Assignment offers;
* Assignment acceptance;
* concealed Session credentials;
* report commitments;
* reveal messages;
* evidence references.

Validation messages SHALL use the VALIDATION channel profile.

---

## 93. Concealed Assignment Privacy

The network layer SHALL minimize unnecessary exposure of:

* Validator identity before reveal;
* target relationship;
* concealed credential purpose;
* report content before commitment.

Relays and unrelated Hypervisors SHALL not receive plaintext assignment details unless required.

---

## 94. Registry Routing

Registry traffic MAY include:

* object requests;
* object responses;
* segment manifests;
* challenge messages;
* replication inventory;
* Snapshot transfer.

Bulk Registry transfer SHALL use low-priority bounded streams.

---

## 95. Snapshot Transfer

Snapshot transport SHALL support:

* resumable chunks;
* object hashes;
* manifest verification;
* provider authentication;
* bandwidth limits;
* parallel-source retrieval.

Detailed Snapshot trust rules belong to RFC-0062.

---

## 96. Governance Routing

Governance messages MAY include:

* Proposal notifications;
* voting availability;
* signed votes;
* readiness signals;
* emergency notifications.

Canonical governance decisions remain Ledger Operations.

Network delivery alone does not finalize a Governance Vote.

---

## 97. Upgrade Notifications

Hypervisors SHOULD propagate:

* scheduled upgrade;
* activation Epoch;
* readiness deadline;
* Compatibility Window;
* emergency cancellation.

The receiving node SHALL verify canonical authorization independently.

---

## 98. Emergency Messages

Emergency network notifications MAY request:

* local safe mode;
* operation pause awareness;
* evidence preservation;
* operator attention.

A non-canonical emergency message SHALL NOT independently change canonical state.

---

## 99. Message Delivery Semantics

The network layer provides:

AT_MOST_ONCE_PROCESSING

through Message ID deduplication where supported.

Transport retransmission MAY occur.

Application handlers SHALL remain idempotent.

---

## 100. No Exactly-Once Network Claim

The protocol SHALL NOT claim physically exact-once delivery.

Distributed transport may:

* lose acknowledgment;
* reconnect;
* retransmit;
* duplicate frames.

Exactly-once economic behavior is achieved through:

* stable IDs;
* idempotent state transitions;
* replay protection;
* canonical Settlement.

---

## 101. Acknowledgment Classes

The network layer MAY support:

RECEIVED
VALIDATED
ROUTED
PROCESSED
REJECTED

An acknowledgment SHALL state what was acknowledged.

RECEIVED does not mean the application accepted the message.

---

## 102. Message Expiration

Every time-sensitive message SHALL contain an expiration or protocol deadline.

Expired messages SHALL not create new obligations.

---

## 103. Deadline Propagation

Relays and Hypervisors SHALL preserve the original application deadline.

A relay SHALL NOT extend a Request deadline merely because forwarding was slow.

---

## 104. Flow Control

Every connection and channel SHALL support flow control.

Flow control MAY limit:

* bytes in flight;
* frames in flight;
* open streams;
* queued messages;
* per-channel memory;
* message rate.

---

## 105. Backpressure

A receiver MAY emit:

PAUSE
RESUME
WINDOW_UPDATE
RATE_LIMITED
RETRY_AFTER

The sender SHALL respect valid backpressure.

---

## 106. Backpressure and Deadlines

When backpressure would make an application deadline impossible, the sender or receiver SHOULD fail the affected request rather than retain it indefinitely.

---

## 107. Connection-Level Limits

A Hypervisor SHOULD enforce:

* maximum connections per peer;
* maximum unauthenticated connections;
* handshake rate;
* idle connection count;
* total bandwidth;
* total queued bytes.

---

## 108. Subject-Level Limits

Limits SHOULD also apply to:

* Hypervisor ID;
* Service ID;
* Runtime ID;
* Endpoint ID;
* Consumer Session identity;
* network address.

This reduces trivial identity-local resource abuse.

---

## 109. Pre-Authentication Limits

Before identity verification, the peer SHALL receive only minimal resources.

The protocol SHOULD limit:

* handshake message size;
* handshake duration;
* concurrent pending handshakes;
* cryptographic work;
* retry frequency.

---

## 110. Authenticated Abuse

Authentication does not grant unlimited network capacity.

An authenticated peer MAY still be:

* rate-limited;
* quarantined;
* disconnected;
* suspended through canonical rules.

---

## 111. Connection Keepalive

Transport Profiles MAY use keepalive.

Keepalive SHALL distinguish:

* transport reachability;
* Hypervisor process availability;
* Service availability;
* Session liveness.

A live TCP connection does not prove a healthy Runtime. Technology remains stubbornly literal.

---

## 112. Idle Connection

An idle connection MAY close after the negotiated timeout.

Closing an idle connection SHALL NOT automatically terminate active Sessions if they can reconnect under RFC-0044.

---

## 113. Reconnection

After connection loss, peers MAY establish a new authenticated connection.

The new connection SHALL:

* perform a fresh handshake;
* obtain a new Connection ID;
* preserve permanent peer identity;
* reconcile resumable channels.

---

## 114. Connection Resume Token

A Transport Profile MAY support a bounded Resume Token.

The token SHALL be:

* peer-bound;
* connection-state-bound;
* expiration-bound;
* replay-protected;
* unable to bypass current Network Revision checks.

---

## 115. Channel Resume

A resumable channel SHALL reconcile:

* last sent sequence;
* last processed sequence;
* unacknowledged Message IDs;
* active transfer IDs;
* application recovery state.

---

## 116. Session Recovery Separation

Connection resume does not by itself resolve Session state divergence.

Session recovery SHALL still follow RFC-0044 and RFC-0060.

---

## 117. Runtime Reconnection

A reconnecting Runtime SHALL present:

* Runtime ID;
* current Configuration Hash;
* Capability binding;
* last event sequence;
* active Session references;
* recovery state.

The Hypervisor SHALL compare this with canonical and stored local state.

---

## 118. Registry Transfer Resume

Registry and Snapshot transfers MAY resume by Transfer ID and verified chunk position.

A resumed transfer SHALL not trust previously received unverified chunks.

---

## 119. Connection Draining

A Hypervisor MAY drain a connection because of:

* maintenance;
* protocol upgrade;
* peer relocation;
* transport migration;
* security concern;
* resource pressure.

Draining SHALL stop new channels while allowing bounded existing work to complete.

---

## 120. Connection Migration

Transport Profiles supporting connection migration MAY change network path without changing Connection ID when transport security guarantees continuity.

Application identities and channel state remain unchanged.

---

## 121. Duplicate Connections

Two Hypervisors MAY establish simultaneous duplicate connections.

The protocol SHALL deterministically select:

* one preferred connection;
* or a bounded set of role-separated connections.

Selection SHOULD use:

* peer identities;
* connection nonces;
* transport quality;
* direction tie-breaker.

---

## 122. Connection Tie-Breaker

A deterministic tie-breaker MAY prefer the connection initiated by the lexicographically lower Hypervisor ID or another published rule.

Both peers SHALL derive the same preferred result.

---

## 123. Multi-Connection Use

Multiple connections between the same peers MAY be retained for:

* traffic separation;
* redundancy;
* bulk transfer;
* privacy;
* transport migration.

They SHALL not duplicate application processing.

---

## 124. Message Deduplication

Receivers SHALL maintain bounded Message ID deduplication state.

The retention window SHALL cover the maximum expected replay and reconnection interval.

---

## 125. Persistent Deduplication

Messages capable of creating economic or canonical effects SHALL use application-level persistent replay protection.

In-memory connection deduplication alone is insufficient.

---

## 126. Compression

A Transport Profile MAY support compression.

Compression SHALL NOT be used where it creates unacceptable:

* decompression-bomb risk;
* secret side-channel risk;
* excessive CPU cost;
* ambiguity in signed payloads.

Signatures SHALL commit to the unambiguous canonical payload.

---

## 127. Decompression Limits

Receivers SHALL enforce:

* maximum compressed size;
* maximum decompressed size;
* expansion ratio;
* decompression time.

---

## 128. Error Envelope

Network errors SHALL use:

```yaml
network_error:
  error_code:
  error_class:
  message_id:
  correlation_id:
  retryable:
  retry_after:
  diagnostic_reference:
  responder_signature:
```

Diagnostics SHALL not expose secrets.

---

## 129. Error Classes

Initial error classes are:

AUTHENTICATION
AUTHORIZATION
VERSION
ROUTING
RATE_LIMIT
RESOURCE
TIMEOUT
SCHEMA
REPLAY
STATE
SECURITY
INTERNAL

---

## 130. Retryable Error

An error marked retryable SHALL include enough information to avoid immediate uncontrolled retry loops.

The sender SHALL respect:

* Retry After;
* Request deadline;
* maximum attempts;
* application retry policy.

---

## 131. Required Network Error Codes

The MVP SHALL define at least:

NETWORK_ID_MISMATCH
CHAIN_ID_MISMATCH
NETWORK_REVISION_MISMATCH
HANDSHAKE_INVALID
HANDSHAKE_EXPIRED
HANDSHAKE_REPLAYED
IDENTITY_INVALID
IDENTITY_NOT_REGISTERED
PROTOCOL_VERSION_UNSUPPORTED
PROTOCOL_DOWNGRADE_PROHIBITED
TRANSPORT_PROFILE_UNSUPPORTED
MESSAGE_PROFILE_UNSUPPORTED
SERVICE_NOT_FOUND
SERVICE_NOT_AUTHORIZED
SERVICE_ROLE_MISMATCH
RUNTIME_NOT_FOUND
ENDPOINT_ROUTE_NOT_FOUND
MESSAGE_SCHEMA_INVALID
MESSAGE_SIGNATURE_INVALID
MESSAGE_HASH_MISMATCH
MESSAGE_EXPIRED
MESSAGE_REPLAYED
MESSAGE_SEQUENCE_INVALID
MESSAGE_TOO_LARGE
CHANNEL_NOT_AUTHORIZED
CHANNEL_LIMIT_EXCEEDED
CONNECTION_LIMIT_EXCEEDED
RATE_LIMITED
BACKPRESSURE_REQUIRED
RELAY_REQUIRED
RELAY_PATH_INVALID
RELAY_HOP_LIMIT_EXCEEDED
RELAY_LOOP_DETECTED
TRANSFER_NOT_FOUND
TRANSFER_CHUNK_INVALID
TRANSFER_HASH_MISMATCH
CONNECTION_DRAINING
PEER_QUARANTINED
INTERNAL_ROUTING_FAILURE

---

## 132. Error Privacy

Error messages SHALL avoid revealing:

* private network topology;
* secret keys;
* OAuth status details not meant for the peer;
* unrelated Service existence;
* internal filesystem paths;
* private Session payloads.

---

## 133. Logging

A Hypervisor SHOULD log:

* connection lifecycle;
* identity validation;
* protocol negotiation;
* channel creation;
* routing failures;
* rate-limit events;
* replay detection;
* relay decisions;
* security alerts.

Logs SHALL avoid unnecessary private payload retention.

---

## 134. Distributed Tracing

Implementations MAY use:

* Correlation ID;
* Causation ID;
* Session ID;
* Request ID;
* Transfer ID;

for distributed tracing.

Tracing metadata SHALL not alter canonical application behavior.

---

## 135. Metrics

A Hypervisor SHOULD expose:

* active connections;
* authenticated peers;
* connection failures;
* handshake duration;
* channel count;
* bandwidth by class;
* queue depth;
* retransmissions;
* rate-limit events;
* relay traffic;
* message rejection count;
* reconnect rate;
* transfer completion rate.

---

## 136. Peer Health

Network Peer Health MAY include:

* recent connection success;
* latency;
* packet loss where measurable;
* reconnect frequency;
* protocol error rate;
* rate-limit violations.

Peer Health is operational.

It is not a replacement for role-specific Reputation.

---

## 137. Reputation Events

Objective network behavior MAY create Reputation Events, including:

* conflicting signed peer records;
* repeated protocol-invalid messages;
* deliberate replay attempts;
* Service identity impersonation;
* persistent routing failure;
* relay message modification;
* successful recovery.

Ordinary packet loss SHALL not automatically become misconduct.

---

## 138. Suspension

A canonically suspended Service or Hypervisor SHALL have applicable channels denied.

The network layer SHALL enforce the active suspension scope.

---

## 139. Local Blocklist

An operator MAY maintain a local blocklist for security or resource reasons.

A local blocklist:

* does not create canonical suspension;
* does not alter Ledger state;
* may affect local reachability;
* SHOULD expose a local diagnostic reason.

---

## 140. Security Incident

On suspected compromise, a Hypervisor SHOULD:

* stop unsafe channels;
* enter Local Safe Mode where needed;
* preserve evidence;
* rotate affected keys;
* notify authorized operators;
* avoid signing contradictory state.

---

## 141. Key Rotation

Hypervisor and Service key rotation SHALL preserve:

* old-key accountability;
* transition authorization;
* activation boundary;
* replay-domain separation;
* connection reauthentication.

Existing connections MAY be drained after rotation.

---

## 142. Certificate and Key Expiration

Transport certificates or equivalent credentials MAY expire independently from canonical Service identity.

Renewal SHALL not create a new Hypervisor identity when canonical key continuity remains valid.

---

## 143. Denial-of-Service Protection

The protocol SHALL account for:

* connection floods;
* handshake floods;
* large-message attacks;
* channel floods;
* subscription floods;
* relay amplification;
* decompression bombs;
* expensive signature verification;
* slow-read attacks;
* Session routing abuse.

---

## 144. Resource Admission Order

A Hypervisor SHOULD perform inexpensive checks before expensive checks.

Recommended order:

1. frame size;
2. basic schema;
3. network domain;
4. expiration;
5. replay cache;
6. identity lookup;
7. signature verification;
8. authorization;
9. application routing.

---

## 145. Relay Amplification Protection

A Relay SHALL NOT forward more data or messages than bounded by:

* authenticated source limits;
* Hop Limit;
* destination policy;
* relay quota;
* message size.

Unauthenticated relay use SHALL be prohibited.

---

## 146. Privacy Considerations

The network layer may expose metadata such as:

* peer relationships;
* Service roles;
* message timing;
* message sizes;
* Relay paths.

Deployments requiring stronger privacy MAY use:

* privacy-network addresses;
* relays;
* padding;
* batching;
* separate Service addresses.

These features are optional unless required by a profile.

---

## 147. Endpoint Location Privacy

An Endpoint MAY advertise a gateway or relay address instead of the Runtime's physical address.

The Consumer-facing Hypervisor remains responsible for routing.

---

## 148. Service Topology Privacy

A Hypervisor is not required to reveal all private internal Service addresses.

It SHALL reveal enough public routing metadata to satisfy its protocol obligations.

---

## 149. Conformance Testing

Implementations SHALL be tested for:

* valid handshake;
* invalid network domain;
* Network Revision mismatch;
* replayed handshake;
* protocol negotiation;
* downgrade rejection;
* duplicate connections;
* Service authentication;
* unauthorized channel;
* message replay;
* sequence gap;
* oversized message;
* backpressure;
* relay loop;
* reconnect;
* channel resume;
* Session route recovery;
* chunk corruption;
* key rotation;
* draining.

---

## 150. Reference Network Harness

The AiDN project SHOULD provide a Network Conformance Harness capable of:

* simulating peers;
* generating malformed handshakes;
* negotiating versions;
* opening channels;
* replaying messages;
* interrupting connections;
* testing relay paths;
* applying bandwidth limits;
* testing chunk transfer;
* verifying stable errors.

---

## 151. Protocol Upgrade

RFC-0066 governs network protocol upgrades.

A network upgrade SHALL define:

* active Protocol Version;
* supported Compatibility Window;
* mandatory security changes;
* Message Profile migration;
* treatment of existing connections;
* required reconnect behavior.

---

## 152. Existing Connections During Upgrade

An upgrade MAY:

* preserve existing compatible connections;
* require channel renegotiation;
* drain old-version connections;
* require full reconnect.

The behavior SHALL be declared before activation.

---

## 153. Emergency Network Action

An authorized emergency action MAY:

* stop new connections;
* restrict selected channels;
* disable relay;
* pause new Sessions;
* require Local Safe Mode.

It SHALL not rewrite finalized application state.

---

## 154. Recovery Governance Traffic

During Consensus halt, signed recovery messages MAY be exchanged out of band through RFC-0042 connections.

Such traffic SHALL be clearly marked:

NON_CANONICAL_RECOVERY_SIGNAL

It does not become canonical merely because many peers forwarded it.

---

## 155. Ledger Operations

Most network messages are not Ledger Operations.

Canonical changes still use RFC-0059.

The network layer transports operations but does not finalize them.

---

## 156. Registry Storage

Registry Services MAY store:

* signed Peer Records;
* Service Network Advertisements;
* protocol-version manifests;
* relay profiles;
* historical network evidence;
* security incident commitments.

Network routing SHALL not depend on one Registry provider.

---

## 157. Genesis Configuration

Genesis SHOULD define:

* Network ID;
* Chain ID;
* initial Network Revision;
* initial protocol version;
* supported Transport Profiles;
* seed peers;
* mandatory security profiles;
* maximum basic frame size.

---

## 158. MVP Requirements

The MVP SHALL implement:

* authenticated encrypted public transport;
* QUIC or TCP/TLS public profile;
* Local IPC profile;
* mutual Hypervisor handshake;
* Network ID, Chain ID and Network Revision validation;
* version negotiation;
* downgrade protection;
* peer discovery;
* signed Peer Records;
* Service authentication;
* channel multiplexing;
* common Message Envelope;
* Message IDs;
* message sequencing;
* replay protection;
* request-response correlation;
* flow control;
* backpressure;
* rate limits;
* Session control and data routing;
* Runtime routing;
* Registry bulk transfer;
* Validation channel;
* connection reconnection;
* channel resume;
* bounded relay;
* stable error codes;
* complete network observability.

---

## 159. Deferred Features

The MVP MAY postpone:

* anonymous peer discovery;
* onion routing;
* mandatory traffic padding;
* generalized hole punching;
* paid relay markets;
* multi-path Session routing;
* multicast data plane;
* hardware-attested network identity;
* private Service discovery;
* zero-knowledge Service routing;
* consensus transport replacement;
* satellite and delay-tolerant profiles.

---

## 160. Open Protocol Parameters

The following remain configurable:

* maximum frame size;
* maximum message size;
* maximum chunk size;
* maximum connections per peer;
* pending-handshake limit;
* handshake timeout;
* maximum clock skew;
* idle timeout;
* keepalive interval;
* deduplication window;
* maximum channels;
* channel queue limits;
* relay Hop Limit;
* relay rate limits;
* maximum subscriptions;
* compression ratio;
* reconnect backoff;
* quarantine duration;
* peer-record expiration.

---

## 161. Identity Invariants

Transport Identity
≠
Wallet Identity
Hypervisor Identity
≠
Service Identity
Connection ID
≠
Hypervisor ID
Discovery Record
≠
Authenticated Identity
Network Connection
≠
Protocol Eligibility

---

## 162. Routing Invariants

* Every routed message has an authenticated source.
* Every routed message has an authorized destination.
* Hypervisors do not reinterpret application payload semantics.
* Runtime traffic reaches only authorized Runtimes.
* Session traffic remains bound to its Session Contract.
* Relay forwarding does not change logical source identity.
* Bulk traffic does not starve critical control traffic.
* Unknown mandatory message profiles are rejected.

---

## 163. Delivery Invariants

* The protocol does not claim physical exactly-once delivery.
* Duplicate delivery is neutralized through Message IDs and idempotency.
* Economic effects remain application-level and canonical.
* Retransmission does not create duplicate Requests.
* Reconnection creates a new Connection ID but preserves peer identity.
* Connection resume does not override Session recovery rules.
* Expired messages create no new obligations.

---

## 164. Version Invariants

* Every connection selects an explicit Protocol Version.
* Mandatory security versions cannot be silently downgraded.
* Network Revision mismatch blocks ordinary mutable traffic.
* Compatibility Windows are explicit.
* Existing application contracts retain their accepted versions.
* Old-revision messages cannot be replayed as current messages.

---

## 165. Security Invariants

* Public transport is encrypted and authenticated.
* Handshakes are nonce-based and replay-protected.
* Services are unauthorized by default.
* Channel permissions are role-specific.
* Session keys cannot authorize Wallet spending.
* Relays cannot modify authenticated inner messages.
* Large payloads are bounded and hash-verified.
* Compression is resource-limited.
* Local blocklists do not impersonate canonical suspension.
* Non-canonical recovery messages do not become canonical through repetition.

---

## 166. Design Invariants

* The Hypervisor Network Protocol is transport-independent.
* Hypervisors coordinate routing without absorbing every application role.
* Service discovery is separate from Service trust.
* Transport reachability is separate from Service Health.
* Application semantics remain in specialized RFCs.
* Control and bulk data use independent priorities.
* Sessions survive ordinary transport interruption.
* Direct connections are preferred but relays are supported.
* Consensus remains integrated but not accidentally tunneled through unrelated application channels.
* The network layer moves authenticated bytes and commitments; it does not become a philosopher interpreting what the model "really meant."

---

# Part II - Network Dispatcher

This Part is normative in RFC-0042 v0.3. Where an earlier section says that a
Hypervisor routes, queues, authorizes or tracks a message, the responsible
component is the Network Dispatcher defined here.

## 167. Dispatcher Definition and Trust Boundary

The Network Dispatcher is the sole trusted Hypervisor control-plane component
for external and cross-component AiDN traffic. It is responsible for:

* ingress validation;
* identity resolution and authentication;
* message and channel authorization;
* replay protection;
* route resolution and Route Generation checks;
* bounded admission and priority scheduling;
* local, remote and Relay delivery;
* delivery tracking, Dead Letter storage and restart recovery.

Provider Plugins, Runtimes and external Services are outside this trust boundary.
They SHALL interact through scoped Dispatcher interfaces.

## 168. Dispatcher Components

A conforming implementation SHOULD provide logical components equivalent to:

```text
Transport Gateway
  -> Frame Decoder
  -> Envelope and Domain Validator
  -> Replay Guard
  -> Identity Resolver
  -> Authorization Engine
  -> Route Resolver and Route Table
  -> Admission Controller
  -> Bounded Priority Queues
  -> Local, Remote or Relay Delivery
  -> Delivery Tracker
  -> Dead Letter Store
  -> Recovery Manager
```

The components MAY share one process, but their protocol responsibilities SHALL
remain separately testable.

## 169. Deterministic Ingress Pipeline

Every incoming message SHALL be processed in this logical order:

1. frame and basic encoding limits;
2. common envelope schema;
3. Network ID, Chain ID and Network Revision;
4. expiration and Hop Limit;
5. Message ID replay state;
6. payload length and hash;
7. source identity and authentication;
8. message, channel and destination authorization;
9. destination route and Route Generation;
10. bounded queue admission;
11. priority and deadline scheduling;
12. delivery and delivery-state recording;
13. explicit acknowledgment or stable error.

Cheap checks SHOULD precede cryptographic and stateful work.

## 170. Dispatcher Message Envelope

The Dispatcher SHALL consume the common `network_message` envelope from Section
50. For v0.3 the authoritative sequence field is `source_sequence` and the
authoritative priority field is `priority_class`. Compatibility decoders MAY
accept the v0.2 names `sequence` and `priority`, but SHALL normalize them before
authentication and authorization.

The Dispatcher SHALL reject payload-length or payload-hash mismatch before
application delivery. Canonical serialization SHALL be deterministic.

## 171. Route Record and Route Generation

```yaml
dispatcher_route:
  destination_type:
  destination_id:
  route_type:
  target_hypervisor_id:
  target_connection_id:
  target_channel_id:
  target_local_handler:
  configuration_hash:
  runtime_binding_hash:
  session_contract_hash:
  route_generation:
  route_state:
  created_at:
  expires_at:
```

Route states are `ACTIVE`, `STALE`, `DRAINING`, `UNREACHABLE`, `QUARANTINED`
and `REVOKED`.

Every material route update SHALL increment `route_generation`. Before final
delivery the queued generation SHALL equal the current generation. A mismatch
requires explicit re-resolution, protocol-defined migration, rejection or Dead
Letter handling; it SHALL NOT silently deliver to a replacement target.

## 172. Endpoint, Session, Runtime and Plugin Routes

Endpoint routes bind Endpoint ID, Endpoint Configuration Hash, authorized
Runtime Binding and current Runtime connection. Session routes additionally bind
Session ID, Session Contract Hash, Consumer Session identity and recovery state.

Runtime replacement MAY preserve work only when Capability semantics, Request
IDs, usage-chain continuity, state and side-effect safety remain compatible.

Plugin routes bind Plugin ID and version, Provider Instance, granted permissions,
managed Runtime IDs and Route Generation. Plugin updates that change adapters,
permissions, provider connection or message mapping SHALL increment affected
Route Generations.

## 173. Provider Plugin Isolation

Provider Plugins SHALL NOT open arbitrary AiDN channels. `PLUGIN_CONTROL` MAY
carry installation plans and progress, Provider Health, model discovery and
management, diagnostics and Runtime-binding requests. Runtime execution results
and Usage Reports use only explicitly granted Runtime routes.

External Provider or package egress is a separate policy boundary and MAY be
restricted to declared Provider hosts, model repositories, package registries,
OAuth hosts or no egress. Plugin permission expansion requires local approval.

### 173.1 Plugin Host Message Profiles

RFC-0056 handshake, capability, operation, Health, diagnostics and recovery
objects are application payload profiles inside the common `network_message`
envelope. They SHALL reuse RFC-0042 Message ID, source sequence, expiration,
payload integrity, authentication, replay protection and Route Generation.

The Dispatcher SHALL NOT accept a second nested transport identity as a
replacement for the authenticated envelope source.

An active Plugin control route binds:

* Installed Plugin ID;
* Installation Generation;
* Plugin Session Identity;
* granted permission hash;
* owned Provider Instance and Model Deployment scope;
* current Plugin Control Route Generation.

Plugin Manager traffic targets `installed_plugin_id`. Provider and model object
IDs remain operation scope, not alternate Plugin identities. Runtime Adapters
register separately under RFC-0054 and use `RUNTIME`, not `PLUGIN_CONTROL`, for
Session execution.

## 174. Bounded Queues and Admission

The Dispatcher SHALL use bounded logical queues for Critical Control, High,
Interactive, Normal, Runtime, Validation, Registry Bulk, Background and Dead
Letter traffic. Every queue SHALL define maximum messages, bytes and message age,
plus admission and overflow policy.

Admission returns one of `ADMITTED`, `BACKPRESSURED`, `RATE_LIMITED`, `REJECTED`,
`EXPIRED` or `ROUTE_UNAVAILABLE`. Priority is validated from role and message
type; sender claims do not grant unlimited capacity. Critical control capacity
SHALL be protected from Bulk and Background starvation.

Messages creating or resolving economic or security state SHALL be durably
queued or explicitly rejected, never silently dropped.

## 175. Delivery State and Acknowledgments

Tracked delivery states are:

```text
RECEIVED -> ENVELOPE_VALIDATED -> AUTHENTICATED -> AUTHORIZED
-> ROUTE_RESOLVED -> QUEUED -> DELIVERY_ATTEMPTED -> DELIVERED
-> APPLICATION_ACCEPTED
```

Alternative states include `APPLICATION_REJECTED`, `EXPIRED`, `RATE_LIMITED`,
`ROUTE_FAILED`, `DELIVERY_FAILED`, `DEAD_LETTERED`, `DUPLICATE` and `CANCELLED`.

Acknowledgment classes are `RECEIVED`, `VALIDATED`, `AUTHORIZED`, `QUEUED`,
`DELIVERED`, `PROCESSED` and `REJECTED`. `DELIVERED` does not mean application
processing completed.

## 176. Delivery Record

```yaml
delivery_record:
  message_id:
  source_subject:
  destination_subject:
  route_generation:
  delivery_state:
  received_at:
  queued_at:
  delivered_at:
  completed_at:
  attempt_count:
  last_error_code:
  payload_hash:
```

Private payload content need not be retained.

## 177. Replay and Retry Semantics

The network does not claim physical exactly-once delivery. Connection and channel
replay state SHALL be bounded. Messages with economic or canonical effects SHALL
also use persistent application-level deduplication.

Retries are message-profile specific and SHALL define retryable errors, maximum
attempts, backoff, deadline, Route Generation behavior and side-effect safety.
Non-idempotent side effects SHALL NOT be retried without an idempotency key or
proof that the prior attempt did not execute.

## 178. Dead Letter Store

Messages that cannot be safely delivered or discarded MAY enter a Dead Letter
Store containing envelope metadata, payload hash, failure stage, stable error,
Route Generation, timestamps, retryability and operator-action requirement.

Raw private payload SHOULD be omitted unless recovery requires it. Dead Letter
records SHALL NOT be automatically replayed after configuration changes.

## 179. Dispatcher Persistence and Restart

The Dispatcher SHALL persist active routes and generations, durable deduplication,
durable queued messages, critical delivery records, active transfers, resume
positions and Dead Letter metadata.

After restart it SHALL restore protocol domain, invalidate old connections,
restore routes and deduplication, revalidate queued messages against expiration,
authorization, protocol version, Network Revision and Route Generation, then
resume or fail them explicitly. No durable queue is replayed blindly.

## 180. Protocol-Specific Routing

`SESSION_CONTROL`, `SESSION_DATA`, `RUNTIME`, `REGISTRY`, `VALIDATION`,
`GOVERNANCE`, `OBSERVABILITY` and `PLUGIN_CONTROL` are distinct authorized
profiles. `VALIDATION` carries concealed Assignment traffic, report transfer,
Storage Receipts, commitments, reveal and availability challenges. Its routing
SHOULD minimize pre-reveal Validator and target disclosure.

The MVP `VALIDATION_REPORT_TRANSFER` profile SHALL use persistent Message ID
deduplication and an application-level report hash. A `PROCESSED` acknowledgment
means the Endpoint custody handler accepted the immutable report, not that the
Validation commitment finalized.

## 181. Dispatcher Errors

In addition to Section 131, v0.3 requires stable errors for domain, route,
admission, queue, delivery and plugin-permission failures, including:

`SOURCE_NOT_AUTHORIZED`, `DESTINATION_NOT_FOUND`, `ROUTE_NOT_FOUND`,
`ROUTE_STALE`, `ROUTE_DRAINING`, `ROUTE_REVOKED`,
`ROUTE_GENERATION_MISMATCH`, `QUEUE_FULL`, `ADMISSION_REJECTED`,
`DEADLINE_UNREACHABLE`, `DELIVERY_FAILED`, `APPLICATION_REJECTED`,
`DEAD_LETTER_CREATED`, `PLUGIN_NOT_AUTHORIZED`, `PLUGIN_PERMISSION_DENIED`,
`PLUGIN_ROUTE_SCOPE_VIOLATION`, `DISPATCHER_OVERLOADED`,
`DISPATCHER_RECOVERING` and `DISPATCHER_SAFE_MODE`.

Errors SHALL identify the failure stage without exposing credentials, unrelated
Service existence, private topology, private Session content or internal paths.

## 182. Dispatcher Conformance and MVP

Conformance tests SHALL cover domain and envelope validation, authorization,
Route Table resolution, Route Generation races, stale queued messages, Runtime
replacement, Plugin permission enforcement, bounded queue saturation, priority
fairness, deadline expiration, persistent deduplication, Dead Letter creation,
restart recovery and Validation report transfer replay.

The MVP SHALL implement the Dispatcher as a transport-independent core. Physical
QUIC/TLS, TCP/TLS, WebSocket/TLS and Local IPC gateways MAY be delivered in
separate implementation slices, but SHALL invoke the same ingress pipeline.

## 183. Dispatcher Invariants

* Authentication precedes authorization.
* Authorization precedes route admission.
* Every delivery uses the current valid Route Generation.
* Every queue is bounded.
* Expired messages are not delivered.
* Critical control capacity is protected.
* Duplicate delivery does not duplicate application effects.
* Persistent deduplication survives restart.
* Durable queued messages are revalidated after restart.
* Provider Plugins cannot impersonate Services, Wallets or Validators.
* Dead Letter messages are not automatically replayed.
* Connection recovery does not invent Session or economic state.

## 184. Runtime Route Binding

An RFC-0053 Runtime route SHALL include `runtime_id`, `runtime_generation`,
`runtime_binding_hash` and `route_generation`. Runtime Generation authenticates
the execution lineage; Route Generation authenticates the current delivery
target. A message failing either comparison SHALL be rejected before Runtime
delivery.

`route_generation` is Dispatcher state and SHALL NOT be included in the
immutable Runtime Binding or Runtime Configuration Hash. Reconnect may rotate a
route without changing Runtime identity; incompatible Runtime replacement
requires an explicit Runtime Generation transition.

Комментарии к решениям

1. RFC-0042 не заменяет CometBFT P2P

Это важная граница.

CometBFT уже отвечает за:

* block proposal;
* prevote;
* precommit;
* consensus evidence.

RFC-0042 отвечает за прикладную сеть AiDN:

* Sessions;
* Registry;
* Validation;
* Runtime;
* Governance notifications;
* Service control.

Иначе мы получили бы два разных сетевых слоя, оба считающих себя ответственными за Consensus. Такие отношения обычно заканчиваются плохо даже у процессов, которые не способны испытывать ревность.

---

2. Transport и protocol semantics разделены

Одна и та же Session может работать через:

QUIC
TCP/TLS
WebSocket
Relay

При этом не меняются:

* Session ID;
* Request ID;
* Deposit;
* Usage Checkpoint;
* Settlement.

Transport только перевозит сообщения.

Это позволяет менять сетевую реализацию без переписывания всей экономики.

---

3. QUIC выбран предпочтительным, но не обязательным

QUIC полезен для:

* multiplexing;
* независимых streams;
* более удобного reconnect;
* migration между сетевыми адресами;
* отсутствия head-of-line blocking между логическими потоками.

Но RFC сохраняет TCP/TLS и WebSocket profiles, чтобы сеть могла работать:

* через обычные reverse proxies;
* в браузерных или ограниченных окружениях;
* там, где UDP заблокирован.

---

4. Network Revision участвует уже в handshake

После RFC-0066 недостаточно проверить только:

network_id
chain_id

Две ветви после Recovery могут иметь общий исторический Chain ID, но разные:

network_revision

Поэтому peer другой revision не допускается к обычным mutable сообщениям.

Исторические Registry-запросы можно разрешить отдельно, но Session или Ledger Operation между ветками идти не должны.

---

5. Discovery не означает доверие

Hypervisor может узнать адрес peer через:

* DNS seed;
* Registry;
* другого peer;
* локальную настройку.

Но после этого peer всё равно обязан:

* доказать identity;
* совпасть по Network Revision;
* согласовать версию;
* подтвердить Service authorization.

Запись "он вроде Validator" в списке seed peers не должна превращаться в криптографическую истину.

---

6. Одна connection может перевозить много каналов

Вместо отдельного TCP-соединения на каждый тип трафика используются logical channels:

CONTROL
SESSION_CONTROL
SESSION_DATA
RUNTIME
REGISTRY
VALIDATION
GOVERNANCE

Это снижает число соединений и позволяет делать нормальные priorities.

Например, скачивание Snapshot не должно задерживать:

* Session cancellation;
* DEPOSIT_LOW;
* emergency message;
* Runtime failure.

---

7. Session control и Session data разделены

SESSION_CONTROL переносит:

* Accept;
* Reject;
* Deposit extension;
* Close;
* Recovery;
* Settlement status.

SESSION_DATA переносит:

* Requests;
* stream chunks;
* artifacts;
* Capability events.

Так большой видеопоток не блокирует управляющее сообщение, сообщающее, что Deposit закончился две минуты назад.

---

8. "Exactly once" здесь не обещается

Сеть физически не может гарантировать, что сообщение никогда не будет доставлено дважды:

ответ дошёл;
ack потерялся;
sender отправил снова.

Поэтому гарантия строится иначе:

stable Message ID
+
stable Request ID
+
sequence
+
idempotent handler
+
canonical economic state

Сетевой слой допускает retransmission, а прикладной слой не выполняет работу и не платит второй раз.

---

9. Transport acknowledgment имеет несколько уровней

Полезно различать:

RECEIVED

байты получены;

VALIDATED

envelope и signature проверены;

ROUTED

сообщение передано нужному Service;

PROCESSED

прикладной протокол его обработал.

Иначе sender получает ACK и фантазирует, что модель уже закончила генерацию, хотя Hypervisor лишь положил сообщение в очередь.

---

10. Relay не становится участником Session

Если Endpoint находится за NAT:

```text
Consumer
    ↓
Relay
    ↓
Endpoint Hypervisor
```

Relay видит маршрут и метаданные, но логическим Provider остаётся Endpoint.

Relay не может:

* изменить Request;
* увеличить цену;
* подписать Usage Report;
* подтвердить Checkpoint;
* получить Session Deposit.

---

11. Relay ограничен двумя hops

Для MVP:

MaximumRelayHops = 2

Этого достаточно для обычного:

source → relay → destination

и, при необходимости:

source → relay A → relay B → destination

Более длинные пути увеличивают:

* задержку;
* вероятность loops;
* сложность диагностики;
* metadata exposure.

Полноценная anonymous overlay network здесь пока не строится. У проекта и без неё достаточно способов усложнить собственную жизнь.

---

12. Local Service тоже обязан аутентифицироваться

Процесс на том же сервере не становится доверенным только потому, что работает рядом.

Runtime должен доказать:

* Runtime ID;
* Capability binding;
* Configuration Hash;
* Service authorization.

Иначе любой контейнер, получивший доступ к socket, сможет представиться Registry или Runtime нужного Endpoint.

---

13. Runtime routing идёт через Endpoint mapping

Маршрут определяется не просто по порту:

Endpoint ID
→ Endpoint Configuration
→ Authorized Runtime
→ Current Runtime Connection

Если оператор сменил Runtime или Configuration Hash, старый route нельзя продолжать использовать молча.

---

14. Validation traffic получает отдельный privacy profile

До reveal желательно не раскрывать:

* кто Validator;
* какой Endpoint проверяется;
* что credential относится к Validation;
* содержание будущего Report.

Поэтому Assignment и concealed credential должны передаваться либо напрямую, либо в end-to-end encrypted envelope.

Сам Relay не должен понимать, что он только что помог отправить скрытый тест.

---

15. Connection reconnect и Session recovery не одно и то же

После обрыва можно быстро восстановить connection и channel sequences.

Но этого недостаточно, чтобы решить:

* какой Request завершился;
* какие chunks получил Consumer;
* какой Usage Checkpoint последний;
* какой PendingExposure остался.

Это уже задача RFC-0044 и RFC-0060.

Network reconnect восстанавливает канал, но не имеет права самостоятельно придумывать экономическое состояние.

---

16. Peer Health, Service Health и Reputation разделены

Peer Health

описывает сетевое соединение.

Service Health

описывает работу конкретного Service.

Reputation

описывает историю поведения.

Например:

peer connection: excellent
Runtime OAuth: expired
Endpoint Health: degraded

Соединение идеально. Полезной работы всё равно не будет. Классический случай великолепно работающей дороги к закрытому магазину.

---

Что теперь нужно синхронизировать

После принятия RFC-0042 v0.2 нужны точечные изменения:

* RFC-0039: Service connection lifecycle и SERVICE_HELLO должны ссылаться на RFC-0042;
* RFC-0040: Verification Challenges используют общую Message Envelope и VALIDATION либо SERVICE_CONTROL channel;
* RFC-0044: Session control/data routing и reconnect должны ссылаться на channel profiles RFC-0042;
* RFC-0045: большие Capability payloads используют artifact или chunked transport;
* RFC-0046: Registry network exchange должен использовать REGISTRY channel;
* RFC-0047: явно зафиксировать границу между CometBFT P2P и RFC-0042;
* RFC-0054: Runtime Protocol должен стать прикладным profile поверх RUNTIME channel;
* RFC-0058: сетевые identities не должны увеличивать Known Control Group independence;
* RFC-0061: replication inventory и object transfer используют Registry bulk streams;
* RFC-0062: Snapshot chunk transfer должен ссылаться на Transfer ID и resume semantics;
* RFC-0064: Assignment delivery и concealed credentials используют end-to-end protected Validation channel;
* RFC-0066: upgrade handshake должен включать active Protocol Version и Network Revision.

Следующим из оставшихся фундаментальных документов логично восстановить RFC-0046 - Registry Architecture. RFC-0042 уже определил, как Registry traffic перемещается; теперь нужно зафиксировать, какие объекты Registry хранит, какие профили Registry существуют и где заканчивается Registry, чтобы он случайно не объявил себя вторым Ledger.
