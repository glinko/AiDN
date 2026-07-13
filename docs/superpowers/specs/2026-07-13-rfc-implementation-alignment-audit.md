# RFC Implementation Alignment Audit

Date: 2026-07-13

Status: Draft audit

Purpose: identify where the current Python implementation already matches the new RFC contract set and where the RFCs now intentionally lead implementation.

## Executive Summary

The product RFC layer is internally aligned after the RFC-0040, RFC-0042, RFC-0045, RFC-0046, RFC-0049, and cross-reference sync pass.

The implementation is partially aligned. It has strong local support for M3/M4 behavior:

- endpoint publication;
- canonical advertisement projection;
- paid Session open and close;
- deposit lock and refund;
- usage report and acknowledgement chains;
- accounting contract snapshots and deterministic registry-style object metadata;
- canonical capability/profile bindings and local immutable Registry Object envelopes;
- local ledger operation recording;
- registry discovery and reputation summaries.

The implementation does not yet fully model the newer network-contract entities as first-class objects:

- Marketplace Offer identity;
- immutable Advertisement identity in Session contracts;
- settlement evidence roots;
- Runtime identity and one-primary-Capability Runtime binding;
- Service Verification records and profiles;
- Registry manifests and retention profiles;
- Hypervisor Network Protocol envelopes, channels and Network Revision binding;
- protocol upgrade and recovery state.

The next implementation work should therefore move from the durable standalone Registry object store toward lifecycle, manifest, and verification surfaces, because Marketplace contract identity, accounting objects, and capability/profile bindings can now already be addressed, inspected, stored, and recovered through registry-style object views.

## Verification Performed

Commands run during the initial audit:

```powershell
python -m pytest tests\sessions tests\accounting tests\ledger tests\endpoint_publications -q
```

Result:

```text
71 passed, 1 warning
```

Recent verification evidence for the current slice:

```text
python -m pytest tests/test_registry_service.py tests/test_api.py -q
```

```text
249 passed, 1 warning
```

```text
python -m pytest -q
```

```text
675 passed, 1 warning
```

## Current Alignment Matrix

| Contract Area | RFC Source | Current Implementation | Alignment | Gap |
| --- | --- | --- | --- | --- |
| Endpoint Advertisement publication | RFC-0049, RFC-0059 | `EndpointPublicationService` records publish and withdraw operations; registry projects canonical advertisement rows. | Partial | Operation names still use `ADVERTISEMENT_PUBLISH` / `ADVERTISEMENT_WITHDRAW` instead of new `ENDPOINT_ADVERTISEMENT_PUBLISH` / `ENDPOINT_ADVERTISEMENT_WITHDRAW`; there is no separate Offer operation. |
| Advertisement identity in discovery | RFC-0049 | `CanonicalAdvertisementRecord.advertisement_id` and registry canonical candidates expose `advertisement_id`. | Partial | Advertisement ID is derived from publication ID in projection, not yet a full immutable Advertisement Object with policy hashes and expiration. |
| Offer identity | RFC-0049, RFC-0044 | Local publication and session flows now derive and preserve `offer_id`, and ledger/session evidence keeps the accepted Offer scope visible for local execution flows. | Partial | There is still no first-class immutable Offer object lifecycle beyond local/default-offer handling, and marketplace-wide Offer policy/versioning remains incomplete. |
| Session contract binding | RFC-0044 | `EndpointSession` now stores `advertisement_id`, optional `offer_id`, accounting contract references, and a derived `session_contract_hash` alongside endpoint, wallet, policy snapshot, accounting snapshot, and accounting chains. | Partial | `capability_definition_hash`, pricing policy hash, and a fully explicit authoritative Session Contract object are still missing from the local model. |
| Settlement evidence | RFC-0037, RFC-0060 | `SESSION_SETTLE` payloads now include accepted Advertisement/Offer identity, `session_contract_hash`, `settlement_evidence_root`, charged/refunded/payout values, and last accepted report sequence. | Partial | There is still no invoice object or broader network-visible settlement evidence object lifecycle beyond local ledger/event payloads. |
| Accounting contract | RFC-0051, RFC-0049 | `AccountingContract` now derives deterministic object metadata, Hypervisor generation returns registry-style fields, Sessions store both snapshot and object references, overlay/node advertisement expose immutable envelopes plus canonical payloads, and registry-backed object views can list and fetch objects by `object_id` with opt-in payload retrieval plus durable local snapshot persistence. | Partial | First local completeness summary scaffolding now exists over the durable local object set, but manifests, retention policy enforcement, and replication still remain out of scope. |
| Usage reporting and acknowledgement | RFC-0051 | Usage report hash, acknowledgement hash, checkpoint, mismatch and ack timeout handling exist. | Strong local alignment | Still local and unsigned; lacks network-visible report object references and full settlement integration. |
| Capability identity | RFC-0045 | Canonical projection now emits versioned `CapabilityDefinition`-style records with definition hashes plus endpoint feature, limit, and implementation profile hashes bound from published endpoint configuration into canonical advertisements, immutable local Registry Object envelopes, and node advertisements. | Partial | Profiles are still projection-driven and not yet fully RFC-shaped request/response/event contracts with validation and conformance profiles. |
| Runtime binding | RFC-0053, RFC-0054 | Runtime projection exists from legacy bundles; provider adapters and local runtime lifecycle exist elsewhere. | Partial | Runtime identity is still compatibility projection, not a formal one-primary-Capability Runtime service with handshake, authorization, recovery, and conformance surface. |
| Registry discovery | RFC-0046, RFC-0061 | `RegistryService` supports node upsert, freshness, discovery filters, canonical candidates, rating/reputation summary, immutable Registry Object envelopes, deduplicated object listing/filtering, `object_id` lookup, opt-in payload retrieval, and a standalone local Registry Object store with durable snapshot persistence used by operator routes while preserving source provenance. | Partial | First local completeness summary scaffolding now exists over the durable local object set, but manifests, retention policy enforcement, and replication still remain out of scope. |
| Reputation marketplace summary | RFC-0041, RFC-0049 | Registry reputation/rating and trust summary exist in discovery candidates. | Partial | No explicit bounded `Marketplace Summary` object or canonical Reputation Profile event chain matching RFC-0041. |
| Endpoint validation/certification | RFC-0057, RFC-0064, RFC-0065 | Validation request, bond, report, status snapshot, epoch, validator entry, assignment and authorization models exist. | Partial | No full concealed assignment, escrow, certification derivation lifecycle, policy version binding, or marketplace certification update operation. |
| Service Verification | RFC-0040 | No first-class Service Verification model found in `src`. | Missing | Need verification subjects, profiles, challenges, check results, records and service state updates. |
| Hypervisor Network Protocol | RFC-0042 | Current implementation is local FastAPI/service orchestration and registry API. | Missing | Need network envelope, authenticated peer/service hello, channels, sequencing, replay protection, relay, chunk transfer, Network Revision binding. |
| Protocol Upgrade and Recovery | RFC-0066 | RFC exists; implementation has local persistence/snapshot concepts. | Missing | Need Network Revision state, compatibility windows, upgrade readiness, recovery mode and republished Marketplace Advertisement handling. |
| Ledger operation catalog | RFC-0059 | Generic `LedgerOperationService` records typed operations with ids, sender sequence, payload, evidence references and result roots. | Partial | Operation catalog is not yet enforced as typed operation schemas; several new operation names from RFC-0059 are absent. |

## Highest-Value Next Slice

### Registry Lifecycle And Manifest Slice

Goal: turn the now-durable local Registry Object store into a clearer local completeness boundary with explicit summary integrity checks, restart-stable behavior, and manifest/replication follow-up surfaces.

This slice should add:

- local completeness-summary integrity issue detection over persisted Registry Objects;
- first local completeness summary scaffolding now exists over the durable local object set;
- malformed local record rejection and restart-stable summary coverage for the local object store;
- alignment of Registry durability docs and follow-up verification notes with current implementation evidence;
- manifests, retention policy enforcement, and replication still remain out of scope.

Why this first:

- the repo now already has local Offer, Session-contract, and settlement-evidence identity in place;
- the most immediate remaining gap for Registry architecture is not object identity, but lifecycle and durability semantics beyond raw snapshot storage;
- it keeps the next step compact and testable without requiring real networking or consensus;
- it prepares RFC-0046 and RFC-0061 implementation work on top of a stable persisted object boundary.

Expected files:

- `src/aidn_hypervisor/registry_service.py`
- `tests/test_registry_service.py`
- `ROADMAP.md`
- `docs/superpowers/specs/2026-07-13-rfc-implementation-alignment-audit.md`

Acceptance checks:

```powershell
python -m pytest tests\test_registry_service.py tests\test_api.py -q
```

The full test suite should also be run after the targeted tests, but the targeted command is the minimum gate for this slice.

## Recommended Follow-Up Slices

### Slice 2: Accounting Contract Registry Object

Make `AccountingContract` publishable as an immutable object with:

- object ID;
- object version;
- payload hash;
- canonical encoding;
- capability ID;
- pricing policy reference;
- registry namespace `usage` or `marketplace`.

This should replace loose accounting snapshots in Advertisement/Session paths with explicit object references while preserving local snapshots for auditability.

### Slice 3: Capability Profile Foundation

Add local models for:

- `CapabilityDefinition`;
- `EndpointFeatureProfile`;
- `EndpointLimitProfile`;
- `EndpointImplementationProfile`.

This should extend the current `CanonicalCapabilityRuntimeRecord` rather than replacing it. The first version can support `llm.chat` and `speech.stt` only.

Status:

- completed in local projection form;
- not yet promoted to standalone Registry Objects or verification-enforced protocol objects.

### Slice 4: Registry Object Envelope

Add immutable `RegistryObject` support for the policy objects already used by Marketplace and Session code.

Start with:

- Advertisement;
- Accounting Contract;
- Proxy Declaration;
- Failover Policy;
- Feature Profile;
- Limit Profile.

Do not implement peer replication or manifests in this slice.

Status:

- completed in local projection, advertisement, and registry-backed query form with standalone local snapshot-backed payload persistence;
- not yet promoted to retention, completeness-manifest, or replication semantics.

### Slice 5: Service Verification Foundation

Add the first service verification models and a local conformance harness for:

- Runtime identity control;
- Capability binding check;
- Registry discovery check;
- Usage report schema support.

This should not attempt full distributed challenge assignment yet.

## Current Answer To The Core Question

The documentation now converges as a protocol architecture.

The implementation converges with the older local-first M3/M4 parts and partially with the new RFCs through compatibility projections. It does not yet fully implement the new network-contract layer.

The right next move was not another broad rewrite. The right next move was a narrow local completeness slice on top of the now-durable Registry object store, so summary integrity checks, malformed-record handling, and restart-stable behavior become explicit before broader manifest, retention, and replication layers are added.
