# RFC Cross-Sync Design

**Date:** 2026-07-12

**Goal**

Run one semantic synchronization pass across the reconstructed AiDN RFC set so that Marketplace, Session, Registry, Certification, Runtime, Settlement, and Epoch lifecycle concepts use compatible fields, object references, and canonical operations.

## Scope

This pass updates only cross-document compatibility surfaces:

* contract fields and object references;
* canonical operation names and lifecycle hooks;
* derived states and status names where another RFC depends on them;
* profile, hash, and object-linkage wording;
* Epoch task lists and update flows;
* explicit inter-RFC bindings that are currently implied or missing.

This pass does not aim to:

* restyle every RFC for consistency;
* rename stable concepts unless compatibility requires it;
* redesign economics or introduce new protocol subsystems;
* rewrite intact sections that are already semantically aligned.

## Recommended Approach

Use a semantic sync pass rather than a minimal link-only patch or a full wording normalization pass.

Why:

* a link-only pass leaves hidden field and operation mismatches in place;
* a full normalization pass creates too much churn for too little protocol value;
* the current need is to align ownership of terms, state transitions, and object flow between already reconstructed RFCs.

## Source-of-Truth Matrix

### Marketplace Offer Model

`RFC-0049` is the source for Marketplace offer semantics:

* `Advertisement`;
* `Offer`;
* `Pricing Policy`;
* `Accounting Contract`;
* `Feature Profile`;
* `Limit Profile`;
* `Proxy Declaration`;
* `Failover Policy`;
* Health freshness and display boundaries.

Dependent RFCs must not redefine those commercial surfaces incompatibly.

### Session Binding

`RFC-0044` is the source for accepted Session economic binding.

It must carry the accepted commercial identity from Marketplace:

* `advertisement_id`;
* `offer_id`;
* accepted Configuration-bound references that matter for pricing and settlement.

### Registry Object Model

`RFC-0046` is the source for storage, retention, and object-versioning semantics.

Marketplace-facing objects must fit the Registry model as immutable, versioned Registry Objects with valid retention and version-chain behavior.

### Epoch and Canonical Processing

`RFC-0048` and `RFC-0059` are the sources for:

* protocol task scheduling;
* activation and expiration processing;
* suspension and withdrawal application;
* canonical operation naming and validation surfaces.

If an object has lifecycle rules, those RFCs must know how the lifecycle is applied.

## Document Sync Targets

### `RFC-0037`

Settlement must reference the accepted commercial offer identity:

* `advertisement_id`;
* `offer_id`;
* accepted Session commercial terms.

### `RFC-0041`

Reputation should expose a Marketplace-facing summary surface without collapsing canonical Reputation state into Marketplace ranking.

### `RFC-0044`

Add Marketplace-derived commercial identity into the Session Contract and any related invariants where needed.

### `RFC-0045`

Ensure Marketplace-published feature, limit, and Accounting Mode surfaces match Capability-side definitions and object roles.

### `RFC-0046`

Ensure Marketplace objects and related policy objects are clearly part of Registry storage, retention, and historical version chains.

### `RFC-0048`

Add Marketplace epoch tasks for:

* advertisement expiration;
* scheduled activation;
* withdrawal application;
* suspension propagation;
* Marketplace freshness and aggregate metrics.

### `RFC-0049`

Acts as the source document for offer and Marketplace semantics and is adjusted only if a contradiction with the broader protocol set is discovered during sync.

### `RFC-0051`

Accounting Contract must be treated as a first-class object/reference surface rather than an implicit pricing side note.

### `RFC-0053`

Runtime execution semantics must stay distinct from commercial offer semantics. Runtime may execute work, but it does not publish Marketplace price identity directly.

### `RFC-0059`

Must include Marketplace operations such as:

* `ENDPOINT_ADVERTISEMENT_PUBLISH`;
* `ENDPOINT_ADVERTISEMENT_WITHDRAW`;
* `ENDPOINT_OFFER_PUBLISH`;
* `ENDPOINT_OFFER_WITHDRAW`;
* related endpoint lifecycle operations where needed.

### `RFC-0063`

Proxy-facing Marketplace disclosures such as `Proxy Declaration` and `Failover Policy` must be explicit and consistent with Proxy protocol semantics.

### `RFC-0065`

Certification updates Marketplace-visible state but must not rewrite Advertisement history or pretend Certification is the Advertisement itself.

### `RFC-0066`

Recovery and Network Revision transitions must explicitly require republish or reactivation semantics for active Advertisements where the new revision changes validity.

## Acceptance Criteria

The sync pass is complete when:

* every Marketplace-facing object has a coherent chain of publication, storage, query, and usage;
* `RFC-0044`, `RFC-0049`, and `RFC-0037` agree on the commercial identity accepted by a Session;
* `RFC-0048` and `RFC-0059` cover lifecycle events needed by new Marketplace objects;
* `RFC-0053` and `RFC-0063` do not leak commercial authority into Runtime or Proxy layers incorrectly;
* `RFC-0065` and `RFC-0066` update Marketplace-visible truth without rewriting immutable historical Advertisement objects;
* no new required term is introduced without an owning RFC and a compatible reference path.

## Execution Order

1. Update `RFC-0044` and `RFC-0037` to bind Sessions and Settlement to accepted Advertisement and Offer identity.
2. Update `RFC-0048` and `RFC-0059` to add lifecycle tasks and canonical operations.
3. Update `RFC-0051`, `RFC-0053`, and `RFC-0063` to align accounting, runtime, and proxy boundaries.
4. Update `RFC-0065` and `RFC-0066` to align Marketplace visibility with certification and recovery semantics.
5. Update `RFC-0041`, `RFC-0045`, and `RFC-0046` to align summary surfaces, profile wording, and storage/retention references.

## Risks and Guardrails

Primary risk:

* introducing stylistic churn that obscures real semantic changes.

Guardrails:

* patch only the minimum text needed to remove protocol ambiguity;
* preserve existing document structure whenever possible;
* verify post-edit references and key term presence with repository-wide scans;
* avoid claiming new canonical behavior unless at least one owning RFC and one dependent RFC both reflect it.
