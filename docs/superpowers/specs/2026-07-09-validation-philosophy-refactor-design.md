# Validation Philosophy Refactor Design

## Summary

This spec redefines AiDN validation as `operational certification` rather than `objective model verification`.

The key change is that the primary trust object becomes the `ValidationReport`, not a binary `pass/fail` flag.

The system will continue to derive a compact certification view for operators and consumers, but that view must now be computed from report evidence rather than treated as the source of truth.

The first implementation slice will use a compatibility-first migration:

- `ValidationReport` becomes the canonical trust artifact;
- `certification_status` is introduced as the canonical summary field;
- existing `validation_status` remains temporarily available as a compatibility projection;
- marketplace and dashboard trust surfaces begin migrating from binary validation language toward report-backed certification language.

## Current Repository Context

The repository already has:

- operator-initiated validation separate from endpoint publication;
- persisted validation requests, bonds, reports, epochs, assignments, and authorizations;
- endpoint and publication summaries that already carry validation-related payloads;
- a marketplace and operator dashboard that consume validation summaries for trust chips and aggregate counts.

The repository also already exposes:

- `GET /api/v1/endpoints/{endpoint_id}/validation`;
- `GET /api/v1/endpoints/{endpoint_id}/validation/history`;
- `POST /api/v1/endpoints/{endpoint_id}/request-validation`;
- `POST /api/v1/validation/requests/{request_id}/reports`;
- `POST /api/v1/validation/requests/{request_id}/maintenance`.

What is still wrong is the governing meaning:

- report submission currently resolves to `pass/fail`;
- endpoint trust is still summarized as `validated` or `validation_failed`;
- marketplace trust still counts `validated` endpoints instead of exposing certification history;
- validator responsibility is still described too much like model judgment rather than protocol inspection.

## Authoritative References

- [UX-0001 Hypervisor Operator Journey](../../product/UX-0001-hypervisor-operator-journey.md)
- [ECO-0003 Validation Economics](../../product/ECO-0003-validation-economics.md)
- [RFC-0035 Validation Escrow System](../../product/RFC-0035-validation-escrow-system.md)
- [RFC-0037 Settlement Engine](../../product/RFC-0037-settlement-engine.md)
- [Validation Bond And Escrow Design](./2026-07-02-validation-bond-and-escrow-design.md)

## Design Decision

### Selected Direction

Adopt a `report-first operational certification` model with an explicit compatibility layer.

The design has four rules:

1. `ValidationReport` is the canonical trust artifact.
2. `Certification` is derived from report evidence and critical issue detection.
3. `validation_status` becomes a legacy compatibility projection rather than a canonical business concept.
4. Validator incentives remain tied to producing valid reports, not to forcing a particular outcome.

### Why

This direction matches the revised philosophy:

- the network cannot reliably prove model identity in the general case;
- the protocol can certify observable behavior, accounting compatibility, and operational correctness;
- consumers and marketplace surfaces should be able to inspect trust evidence, not just a yes/no badge;
- the existing codebase already persists reports, so the shortest path is to make reports primary instead of introducing a separate trust artifact.

### Rejected Alternatives

#### 1. Keep Binary Validation And Only Rewrite The Docs

Rejected because it would make the product documents more correct while leaving the implementation semantically wrong.

The current service, tests, and UI would continue reinforcing the old mental model.

#### 2. Hard-Cut Replace Every Validation Surface In One Slice

Rejected because it would force simultaneous changes to domain models, API responses, operator dashboard, marketplace aggregation, and tests.

That is unnecessary risk for a concept refactor that can be staged.

#### 3. Remove All Legacy Validation Fields Immediately

Rejected because current dashboard and registry views already consume `validation_status`.

Keeping a temporary compatibility projection will let the trust model evolve without breaking every existing surface at once.

## Product Goals

This refactor must let the system:

- certify operational correctness rather than claim objective model identity;
- persist immutable validation reports as first-class trust objects;
- derive certification status from report findings and critical issue detection;
- expose validation history to marketplace and operator surfaces;
- keep publication and validation independent;
- keep validation optional;
- preserve validator anonymity and escrow-backed Session guarantees;
- treat report generation as the rewarded validator output.

This refactor must let the operator:

- request certification for a specific endpoint configuration;
- inspect current certification state and the reports that produced it;
- see whether an endpoint is operational, operational with issues, under review, revoked, or uncertified;
- understand that model quality remains a marketplace concern rather than a protocol guarantee.

## Non-Goals

This slice does not:

- prove actual model identity;
- solve subjective quality ranking for all endpoint types;
- implement distributed registry storage for reports;
- fully redesign all dashboard copy in one pass;
- remove every legacy validation field in the first migration.

## Core Semantic Shift

### Old Model

The old model treats validation like a binary trust gate:

- request validation;
- validator decides `pass` or `fail`;
- endpoint becomes `validated` or `validation_failed`.

This makes the report secondary.

### New Model

The new model treats validation as an evidence-producing inspection flow:

- request validation for one endpoint configuration;
- validator executes representative requests;
- validator records observations, measurements, protocol checks, and accounting checks;
- validator publishes a structured validation report;
- the system derives certification status from that report.

The report is primary.

The status badge is a projection.

## Canonical Concepts

### Validation Report

`ValidationReport` becomes the canonical trust artifact for one inspection event.

It must be immutable once stored.

It represents evidence, not a vote.

### Certification Status

`CertificationStatus` becomes the canonical summary for the current state of one endpoint configuration.

Initial target values:

- `uncertified`
- `pending_initial`
- `certified`
- `certified_with_issues`
- `maintenance_due`
- `maintenance_in_progress`
- `revoked`
- `superseded`

This status is computed from the latest applicable report and configuration lineage.

### Legacy Validation Status

`validation_status` remains temporarily available only as a compatibility field.

It should be mechanically derived from `certification_status`.

Initial mapping:

- `uncertified -> unvalidated`
- `pending_initial -> pending_initial`
- `maintenance_due -> pending_maintenance`
- `maintenance_in_progress -> pending_maintenance`
- `certified -> validated`
- `certified_with_issues -> validated`
- `revoked -> validation_failed`
- `superseded -> superseded`

This mapping is intentionally lossy.

All new product and API work must prefer `certification_status`.

## Validation Report Contract

The report schema must expand beyond the current `outcome + evidence_summary` shape.

The first canonical schema should include at least:

- `report_id`
- `request_id`
- `endpoint_id`
- `configuration_hash`
- `report_kind`
- `validator_id` or validator protocol identifier
- `validator_label`
- `capability_id`
- `test_description`
- `request_summary`
- `response_summary`
- `observations`
- `measured_metrics`
- `protocol_compliance`
- `accounting_verification`
- `detected_issues`
- `critical_issue_count`
- `recommendation`
- `signed_payload`
- `created_at`

Initial `recommendation` values:

- `certify`
- `certify_with_issues`
- `do_not_certify`

Initial issue severity values:

- `info`
- `warning`
- `critical`

The report may continue carrying raw validator payload in `signed_payload`, but the top-level report must expose normalized protocol fields so API consumers do not need to parse opaque nested blobs.

## Certification Derivation Rules

The certification engine must derive the current certification state from report evidence.

Initial derivation rules:

- if no report exists for the current configuration, status is `uncertified`;
- if an initial validation request exists and no report exists yet, status is `pending_initial`;
- if a maintenance validation request exists and no report exists yet, status is `maintenance_in_progress`;
- if latest report contains any critical protocol, availability, accounting, or capability failure, status is `revoked` for maintenance or `uncertified` for initial review;
- if latest report recommendation is `certify` and no critical issues exist, status is `certified`;
- if latest report recommendation is `certify_with_issues` and no critical issues exist, status is `certified_with_issues`;
- if configuration is replaced, status becomes `superseded` regardless of prior certification.

The implementation must not derive certification from model-quality opinions.

Model quality can appear in report observations, but it must not by itself block certification unless it manifests as a capability mismatch or invalid endpoint behavior.

## Validator Responsibilities

Validators become protocol inspectors, not model judges.

Their responsibility is to:

- execute representative requests;
- measure observable endpoint behavior;
- verify accounting and protocol conformance;
- detect capability mismatch and execution failures;
- publish reproducible evidence.

Validators do not attest that a neural model is objectively identical to a named model.

Product and protocol copy must stop implying otherwise.

## Economics And Escrow Alignment

`ECO-0003` and `RFC-0035` must be interpreted under the new semantics.

The economic behavior remains mostly intact:

- operators still lock a Validation Bond;
- validators still receive reward for work;
- validation sessions still do not create endpoint revenue;
- maintenance review still drives bond refund or forfeiture.

What changes is the semantic trigger:

- reward is for producing a valid report;
- certification is derived from that report;
- maintenance degradation is driven by accumulated negative operational reports rather than a purely binary trust event.

The wallet ledger may continue emitting events such as `validation_bond_locked` and `validation_bond_refunded`, but event descriptions should move away from implying that economic truth comes from a raw `pass/fail` decision.

## API Contract Changes

The first implementation slice should preserve existing endpoints but expand their payloads.

### Validation Summary

`GET /api/v1/endpoints/{endpoint_id}/validation` should evolve to include:

- `certification_status`
- `validation_status` as compatibility field
- `latest_report_id`
- `latest_report_at`
- `latest_recommendation`
- `report_count`
- `maintenance_report_count`
- `critical_issue_count`
- `warning_issue_count`
- `bond_state`
- `current_snapshot`

### Validation History

`GET /api/v1/endpoints/{endpoint_id}/validation/history` should remain the canonical detailed history surface.

It should expose reports as first-class items rather than relying on snapshot status to carry all meaning.

### Report Submission

`POST /api/v1/validation/requests/{request_id}/reports` should stop accepting bare `outcome=pass|fail` as the primary semantic.

The transitional shape may still accept `outcome` for compatibility, but canonical submission should include:

- recommendation;
- normalized observations;
- issue list;
- protocol checks;
- accounting checks;
- metrics.

## New Specification Follow-Up

The product docs set updated philosophy and migration direction.

The protocol layer should then gain a dedicated `RFC-0057 Validation Report Specification`.

That RFC should define:

- report schema;
- issue normalization and severity model;
- recommendation rules;
- registry publication shape;
- reputation input contract;
- compatibility requirements for legacy validation projections.

## Domain Model Changes

The validation domain must move from `outcome-first` to `report-first`.

### ValidationReport

Expand the model to support structured operational findings and recommendation-based certification.

### ValidationStatusSnapshot

Rename the canonical field in the snapshot model to `certification_status`.

If immediate rename would create too much churn, the persisted model may temporarily store both:

- `certification_status`
- `validation_status_compat`

The application layer must treat `certification_status` as canonical.

### Endpoint Validation State

`EndpointValidationState` should gain:

- `certification_status`
- `latest_report_at`
- `latest_recommendation`
- `report_count`

The old `validation_status` field may remain temporarily as a derived projection for existing UI surfaces.

## Marketplace And Dashboard Implications

The marketplace must stop reducing trust to `validated_count`.

The next surface should aggregate:

- `certified_count`
- `certified_with_issues_count`
- `pending_count`
- `attention_count`
- `report_count`

Operator and discovery surfaces should prefer labels such as:

- `Certified`
- `Certified With Issues`
- `Pending Review`
- `Attention Required`
- `Superseded`

The marketplace should eventually expose:

- last certification date;
- maintenance review count;
- validation history access;
- report-backed operational notes.

The first code slice only needs to supply the data contract required for those surfaces.

## Migration Strategy

### Slice 1: Canonical Semantics And Compatibility

- rewrite product and protocol docs to report-first certification semantics;
- introduce `certification_status` and expanded report schema;
- keep `validation_status` as compatibility projection;
- update service derivation rules and summary payloads;
- keep UI mostly functional with minimal compatibility mapping.

### Slice 2: Trust Aggregation Refactor

- update dashboard and registry aggregation to count certification states rather than `validated`;
- replace binary trust chips with certification language;
- expose report counts and last report signals.

### Slice 3: Rich Trust UX

- add report drill-down views;
- expose issue summaries in marketplace and endpoint detail panels;
- reduce or remove legacy `validation_status` usage from the UI.

### Slice 4: Legacy Removal

- remove compatibility-only binary validation terminology from code paths that no longer need it;
- keep migration shims only where external consumers still depend on them.

## Testing Strategy

The implementation plan must cover:

1. domain tests for certification derivation from report findings;
2. service tests for initial and maintenance report handling under recommendation-based semantics;
3. API tests for expanded summary payloads and history payloads;
4. registry and dashboard aggregation tests for certification counts;
5. compatibility tests proving `validation_status` is still derived correctly during migration.

## Expected Outcome

After this refactor begins:

- validation will no longer be described or modeled as objective model verification;
- reports will become the first-class trust artifacts already implied by the architecture;
- certification will represent operational confidence rather than model identity;
- economics, escrow, and trust UX will all point at the same meaning;
- the codebase will have a staged path away from binary validation without requiring a risky one-shot rewrite.
