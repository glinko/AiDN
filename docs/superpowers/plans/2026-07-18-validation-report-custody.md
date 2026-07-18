# Validation Report Custody Implementation Plan

Date: 2026-07-18

Status: In progress

Related specifications:

- RFC-0041 Reputation Profile Engine v0.3
- RFC-0046 Registry Architecture v0.3
- RFC-0048 Epoch Engine v0.2
- RFC-0049 Distributed Marketplace and Endpoint Advertisement Registry v0.4
- RFC-0057 Validation Report Specification v0.2
- RFC-0059 Ledger Operation Catalog v0.2
- RFC-0064 Validation Assignment, Concealed Session and Escrow Protocol v0.3
- RFC-0065 Endpoint Certification Derivation and Lifecycle Protocol v0.2

## Goal

Move complete Validation Report custody to the validated Endpoint Hypervisor while keeping the compact result, integrity commitment and Certification inputs canonical. Add objective availability checks so report loss, withholding or corruption affects Certification and Reputation without requiring the Registry network to replicate every report payload.

## Corrected Protocol Decisions

1. The Endpoint Hypervisor is the mandatory origin custodian for the complete Public Validation Report.
2. The Ledger stores a compact Validation Commitment, not only a bare hash. It includes all structured fields required for deterministic Certification derivation.
3. The full report and Evidence Bundle remain immutable, content-addressed off-chain objects.
4. The Endpoint Storage Receipt proves custody acceptance, not agreement with the conclusion.
5. Endpoint storage refusal cannot veto adverse Validation. A refusal is committed separately; positive Certification requires a receipt, while adverse and inconclusive evidence remain processable.
6. Registry Services index commitments and may mirror reports, but complete-report replication is optional.
7. Origin custody and mirror availability are separate states. A mirror can preserve evidence but cannot erase an Endpoint custody violation.
8. Availability challenges respect access classes. Restricted evidence is checked by authorized actors and never made public solely for a custody probe.
9. Mandatory origin retention lasts while the Endpoint exists plus a configurable Retirement Grace Period. Canonical hashes and history remain indefinitely verifiable.

## Current Implementation Impact

The current implementation is directionally compatible because `ValidationStore` already persists complete `ValidationReport` objects with Hypervisor state. The incompatible part is transaction shape:

- `ValidationService.submit_validation_report()` currently creates and stores the full report;
- records `VALIDATION_REPORT_COMMIT` immediately;
- derives and records Certification in the same service call;
- has no signed Storage Receipt, stable report locator or custody state;
- has no separate Public Report and Evidence Bundle;
- has no availability challenge or grace-period lifecycle;
- persists full reports inside the general state snapshot rather than a dedicated content-addressed custody store.

The change is medium-to-high complexity. It crosses models, persistence, API, local ledger operations, Certification derivation, Reputation projection, Marketplace summaries and Epoch scheduling. It should be delivered as compatibility-preserving slices rather than one schema replacement.

## Target Data Model

### ValidationCommitment

Compact canonical object containing Validation and Assignment identity, Endpoint/Configuration/Capability binding, Validator and Epoch, deterministic conclusion codes, report integrity metadata, Evidence Bundle root, access and retention policy, receipt or failure reference, and signatures.

### ValidationReportEnvelope

Immutable signed object containing the safe public structured report. Its canonical bytes produce `report_hash`.

### ValidationEvidenceBundle

Optional immutable object set containing large or sensitive request, response, media, log and artifact evidence. Each bundle declares `PUBLIC`, `ENCRYPTED`, `RESTRICTED` or `HASH_COMMITTED` access.

### ValidationReportStorageReceipt

Endpoint-signed acceptance of exact report bytes, locator and retention obligation.

### ValidationReportCustodyState

Current derived state is `AVAILABLE`, `TEMPORARILY_UNAVAILABLE`, `WITHHELD`, `LOST`, `CORRUPTED` or `ACCESS_RESTRICTED`. It also records the last successful check, failure streak, grace deadline, latest challenge and optional mirror status.

## Stable Locator

Use:

```text
aidn://endpoint/<endpoint_id>/validation/<report_hash>
```

The Hypervisor resolves this logical locator through the current Endpoint route. IP address, transport migration and Hypervisor relocation do not change the canonical locator.

## Delivery Slices

### Slice 1: Models and Compatibility Projection (Completed 2026-07-18)

- Add target models without deleting legacy `ValidationReport` fields.
- Define canonical serialization and SHA-256 hashing helpers.
- Add versioned retention and access policies.
- Project legacy reports into a compatibility commitment for existing snapshots.
- Extend state snapshot parsing so old state files remain readable.

Completed: old snapshots load unchanged; new reports produce deterministic hashes and compact commitments; the local ledger projection contains deterministic Certification inputs without loading a full report payload. Current Certification derivation remains intentionally compatible until Slice 4.

### Slice 2: Dedicated Endpoint Custody Store

- Add a content-addressed Validation Report store below one configured Hypervisor data root.
- Store Public Reports and Evidence Bundles separately.
- Use atomic staging, hash verification and immutable promotion.
- Add report get, verify, inventory and retention metadata APIs.
- Keep report bytes out of the general JSON state snapshot; persist only metadata and references.

Exit criteria: report bytes survive restart; corrupted bytes are detected before serving; path traversal and arbitrary-file reads are rejected; identical content deduplicates safely.

Progress 2026-07-18: a controlled content-addressed store now writes canonical report bodies through a staging directory and atomic promotion, verifies hashes on every read, stores only relative-path metadata in snapshots, and is enabled by default when file-state persistence is configured. Legacy `ValidationReport` entries remain in the general state snapshot for compatibility, so removal of duplicate legacy data is deferred to Slice 8.

### Slice 3: Transfer and Storage Receipt

- Add Validation-channel report transfer messages.
- Verify the assignment-scoped transfer signature, concealed Assignment binding, Endpoint, Configuration, Capability, size and hash before promotion; verify the permanent Validator signature after reveal.
- Issue Endpoint-signed Storage Receipt only after durable storage succeeds.
- Add stable locator resolution and authenticated retrieval.
- Keep the Validator temporary copy through finalization or dispute timeout.

Exit criteria: valid transfer returns a verifiable receipt; invalid bindings return stable errors; receipt retry is idempotent; restart does not lose accepted custody.

Progress 2026-07-18: the local Endpoint-side receipt primitive is implemented with an injectable Ed25519 signer, content re-verification before signing, deterministic receipt identity, idempotent persistence and a local ledger projection. It remains opt-in through `AIDN_HYPERVISOR_CUSTODY_SIGNING_KEY`. Assignment-key transfer, canonical Hypervisor-key registration and Certification enforcement remain pending.

Progress 2026-07-18: operator-facing validation summaries and histories now expose only the compact commitment, custody-object metadata, receipt metadata and future custody-state records. They do not expose the stored report body; authenticated locator retrieval remains a later transport slice.

Progress 2026-07-18: the local protocol projection records an immutable, idempotent `VALIDATION_REPORT_STORAGE_FAILURE` for endpoint refusal or custody failure. It does not modify the report conclusion or Certification by itself and is not yet assignment-key signed; those enforcement and network-authentication rules remain Slice 4 and Slice 5 work.

Progress 2026-07-18: local custody verification now records compact availability observations. A verified object is `available`, a missing object is initially `temporarily_unavailable`, and a hash or size mismatch is `corrupted`. The observations are projected as `VALIDATION_REPORT_AVAILABILITY_COMMIT`; epoch scheduling, independent actors, grace windows, Reputation and Certification transitions remain later work.

Progress 2026-07-18: a compatibility-preserving service policy can now require a valid local Storage Receipt before a positive report changes Certification to `CERTIFIED` or `CERTIFIED_WITH_ISSUES`. In that mode an initial report remains `pending_initial` until custody succeeds; negative results remain independent of receipt. The policy is opt-in until canonical Endpoint and assignment identity binding are implemented.

Progress 2026-07-18: the validation service can build a compact transfer envelope that binds a completed report to its persisted Assignment, Authorization, Endpoint, Configuration Hash and report integrity commitment. It is the future `VALIDATION` channel payload; assignment-key signatures, expiry enforcement and concealed identity handling are still pending.

Progress 2026-07-18: transfer envelopes now reject expired authorizations and optionally carry a separately injected Ed25519 validator signature. Unsigned envelopes remain available only for migration compatibility; canonical validator-key authorization, receiver-side transfer acceptance and RFC-0042 delivery are still pending.

Progress 2026-07-18: an endpoint-side receiver contract now verifies the transfer signature, persisted Assignment and Authorization bindings, Endpoint and Configuration Hash, report identity and canonical hash before promoting the body into custody. It can require signatures by policy. RFC-0042 `VALIDATION` channel delivery, canonical key lookup and replay protection remain pending.

Progress 2026-07-18: a transport-neutral `VALIDATION_REPORT_TRANSFER` message profile now delegates to the receiver contract and enforces idempotent Message ID handling with conflicting-replay rejection. The adapter is intentionally in-process because the current product has no RFC-0042 Hypervisor network dispatcher; persistence of replay state and real transport integration remain pending.

Progress 2026-07-18: Message ID replay records are now persisted with the Validation state snapshot, so the channel adapter preserves idempotency through Hypervisor restart. Retention bounds, network-level sequence reconciliation and a shared RFC-0042 dispatcher remain pending.

### Slice 4: Compact Ledger Operations and Dual Write

- Extend `VALIDATION_REPORT_COMMIT` with compact Certification inputs and receipt/failure references.
- Add storage receipt, storage failure, availability commit and custody release operations.
- During migration, emit both legacy-compatible events and the new commitment projection.
- Separate report storage from Certification state derivation.

Exit criteria: replay creates no duplicate effect; commitment validates without fetching the full report; negative report plus refusal remains canonical; positive report without receipt cannot certify.

### Slice 5: Certification Custody Lifecycle

- Require an accepted receipt and initial report availability for positive Certification.
- Add temporary availability warning and grace deadline.
- Map temporary failure to warning or `DEGRADED`, serious custody states to `REVALIDATION_REQUIRED`, and prolonged unresolved state to `EXPIRED` or policy-defined revocation.
- Preserve historical Certification Records instead of rewriting them.

Exit criteria: transitions are deterministic and idempotent; one transient outage does not revoke Certification; restoration repairs current state without erasing history.

### Slice 6: Availability Challenges and Reputation

- Add bounded randomized custody challenges to Epoch tasks.
- Verify report size, hash, signature and authorized access behavior.
- Separate origin and mirror observations.
- Emit Endpoint Reputation events for availability, retention, integrity and disclosure reliability.
- Emit Hypervisor Reputation events only when evidence binds a shared storage failure to the Hypervisor.

Exit criteria: duplicate evidence counts once; Known Control Group actors do not count as independent observations; corruption is critical; mirror success does not clear origin failure.

### Slice 7: Marketplace and Operator UX

- Show retained report count, origin availability, mirror availability, last checked Epoch and active grace state.
- Add operator report inventory, storage pressure, retrieval diagnostics and repair controls.
- Warn before Endpoint retirement about custody grace obligations.
- Expose report explanation without exposing restricted Evidence Bundles.

Exit criteria: Consumers distinguish Certification from report availability; operators can repair custody failures; private evidence never appears in public Marketplace payloads.

### Slice 8: Migration Completion

- Backfill compact commitments and custody metadata for legacy local reports.
- Mark unverifiable legacy reports explicitly instead of inventing receipts.
- Remove immediate Certification derivation from report submission after all callers use the new pipeline.
- Stop embedding full report payloads in new general state snapshots.
- Retain compatibility reads for at least one declared migration window.

## Test Strategy

- Unit: canonical hashes, signatures, binding validation, policy validation, custody derivation and legacy projection.
- Service: durable transfer, restart, retrieval, refusal paths, corruption, restoration and idempotency.
- Certification: complete custody transition matrix and grace boundaries.
- API/UI: access-aware retrieval, route migration, Marketplace freshness, repair and retirement warnings.
- Security: path traversal, symlink escape, oversized payloads, substitution, forged signatures, cross-Endpoint receipt replay and unauthorized restricted-evidence challenges.

## Rollout and Compatibility

1. Ship readers and models first.
2. Enable dual-write commitments behind a protocol feature flag.
3. Enable custody transfer and receipts for new Validation assignments.
4. Start availability checks in observe-only mode.
5. Enable Marketplace warnings.
6. Enable Reputation consequences.
7. Enable Certification transitions after at least one full grace window and published network parameters.

No existing Certification SHALL be revoked merely because a pre-migration report lacks a newly introduced receipt. Legacy records receive an explicit compatibility state and become subject to the new custody requirement on their next Maintenance Validation.

## Open Parameters

- maximum Public Report and Evidence Bundle sizes;
- Validator temporary-copy dispute window;
- custody challenge frequency and transient failure threshold;
- custody and Retirement grace periods;
- authorized actor count for restricted evidence;
- mirror discovery policy;
- legacy migration window.

## Deferred

- mandatory Archive Registry mirrors;
- paid report storage markets;
- erasure-coded Evidence Bundles;
- private information retrieval;
- zero-knowledge custody proofs;
- cross-network report portability.
