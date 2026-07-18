# Network Dispatcher Implementation Plan

Date: 2026-07-18

Status: In progress

Normative source: RFC-0042 v0.3

## Goal

Introduce one transport-independent trusted routing boundary for Hypervisor,
Service, Runtime, Session, Validation and Provider Plugin traffic. Preserve
application semantics in their existing services while centralizing envelope,
domain, authorization, Route Generation, admission, replay and delivery state.

## Delivery Slices

1. Dispatcher core: canonical envelope, domain and payload validation, scoped
   local routes, Route Generation, bounded queues, delivery records and stable
   rejection errors.
2. Durable state: routes, persistent deduplication, critical delivery records
   and Dead Letter metadata in `HypervisorStateSnapshot`.
3. Validation integration: route `VALIDATION_REPORT_TRANSFER` through the core
   and remove profile-local replay ownership after compatibility migration.
4. Runtime and Plugin control: scoped `RUNTIME` and `PLUGIN_CONTROL` routes,
   permission-derived authorization and route invalidation on binding updates.
5. Session routing: Session Contract and Configuration binding, priority and
   deadline policies, recovery-facing delivery records.
6. Transport gateways: Local IPC first, then authenticated TCP/TLS or QUIC/TLS,
   handshake, connection and channel lifecycle.
7. Recovery and operations: restart revalidation, Dead Letter operator surface,
   metrics, overload and Safe Mode.

Progress 2026-07-18: Slice 1 is implemented. Slice 2 now persists routes,
durable queued messages, delivery records, processed Message IDs and Dead Letter
metadata using `HypervisorStateSnapshot`. Local handlers are intentionally
rebound after restart and queued messages are revalidated before delivery.

Progress 2026-07-18: Slice 4 has a first route-factory layer. Ready Runtime
Bindings receive scoped `RUNTIME` routes, and `PLUGIN_CONTROL` message types are
derived from the intersection of declared and approved Plugin permissions. Full
lifecycle wiring will register, drain and revoke these routes as Provider
Inventory state changes.

## Current Boundary

The repository currently has application services and an in-process Validation
channel adapter, but no common network dispatcher or physical peer transport.
The first slice therefore establishes the dispatcher semantics without claiming
that QUIC, peer discovery or remote relay delivery already exists.

## Exit Criteria for Slice 1

- Invalid domain, expiration and payload integrity fail before handlers run.
- Unauthorized source/channel/message combinations are rejected by default.
- A stale Route Generation never reaches a replacement handler.
- Queue capacity is bounded and explicit.
- Duplicate Message IDs do not repeat application processing.
- Delivery and Dead Letter records expose stable stages and errors.
- Validation transfer can run through the same dispatcher contract.
