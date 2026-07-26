# M9: Network Transport + Registry Replication Protocol

## Goal

Connect the new `registry/` package (M8) with the existing Network Dispatcher
to enable cross-registry-peer replication over authenticated transports.

## RFC-0042 Compliance

- §5 Transport Independence
- §6 Initial Transport Profiles
- §50-§131 Message Envelope, Routing, Errors
- §158 MVP Requirements (Registry bulk transfer)
- §167-§182 Dispatcher Architecture

## Existing Infrastructure

- `dispatcher/transport/` — QUIC, TCP/TLS, Unix socket transports
- `dispatcher/models.py` — `NetworkMessage`, `MessageFramer`
- `dispatcher/gateway.py` — `NetworkGateway`
- `dispatcher/channels.py` — Channel multiplexing
- `registry/` — Full M8 implementation (S1-S6 + bridge)

## Slices

### M9-S1: Registry Network Message Types

Registry-specific message types for replication protocol:
- `RegistryMessage` — wrapper for registry-specific payloads
- Message types: INVENTORY_REQUEST, INVENTORY_RESPONSE, OBJECT_REQUEST,
  OBJECT_RESPONSE, BLOOM_FILTER, SYNC_STATUS, ANNOUNCEMENT
- Integration with `NetworkMessage` envelope
- RFC-0042 §50 compliance

### M9-S2: Registry Channel + Route Binding

Channel configuration for registry replication traffic:
- `RegistryChannelConfig` — channel identity, priorities, rate limits
- Route binding for registry messages through Dispatcher
- Channel authorization for registry peers
- RFC-0042 §44-§49 compliance

### M9-S3: Registry Replication Transport

Transport layer connecting registry/ with dispatcher:
- `RegistryReplicator` — high-level replication controller
- Uses `RegistryServiceAdapter` (bridge) for data access
- Inventory exchange over network channels
- Object transfer with chunked support
- RFC-0061 §28-§31 + RFC-0042 §158

### M9-S4: gRPC Transport Profile

gRPC-based transport for cross-registry communication:
- `GrpcTransport` implementing `TransportGateway`
- Proto definitions for registry replication messages
- Bidirectional streaming for sync
- Health checks + keepalive
- RFC-0042 §5-§6 compliance

### M9-S5: Registry Peer Discovery + Sync

Peer discovery and automatic sync:
- `RegistryPeerDiscovery` — discover registry peers
- `AutoSyncController` — periodic inventory comparison + sync
- Lag monitoring + alerting
- Integration with PeerManager (M8-S2)

### M9-S6: Integration + End-to-End Tests

Full integration tests:
- Two registry instances replicating via dispatcher
- Inventory exchange verification
- Object transfer with chunked resumption
- Anti-entropy round over network
- Completeness convergence

## Test Targets

| Slice | Tests | Total Cumulative |
|---|---|---|
| S1 | ~30 | ~420 |
| S2 | ~25 | ~445 |
| S3 | ~35 | ~480 |
| S4 | ~30 | ~510 |
| S5 | ~25 | ~535 |
| S6 | ~20 | ~555 |

## Execution Strategy

- Strict TDD per slice
- Subagent per slice
- Commit after each slice
- Full test suite after M9 completion
- Push to GitHub after all slices
