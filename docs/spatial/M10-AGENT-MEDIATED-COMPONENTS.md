# M10 · Agent-mediated Components and Resource Semantics

M10 introduces the first shared Classic/Spatial component path while keeping
Node authority and the existing Classic route intact. The implementation is
flag-gated where it can issue a change, and generated dashboard output remains
out of scope for manual edits.

## Implemented seams

- [component inventory](../../web/operator-dashboard/src/app/component-inventory.ts)
  records every current Classic fragment, its data source/query key, mutations,
  states, ownership, accessibility gap, test coverage and migration priority.
- [Component Registry v2](../../web/operator-dashboard/src/spatial/interaction/component-registry.ts)
  adds categories, data revisions, variants, capability visibility, viewport
  fallbacks, virtualization, lifecycle/deprecation metadata and migrations.
- [EndpointSummary](../../web/operator-dashboard/src/components/shared/EndpointSummary.tsx)
  is a read-only typed view model rendered in the Classic endpoint table and
  the Spatial topology frame. Both surfaces show revision and provenance.
- [EndpointConfiguration](../../web/operator-dashboard/src/components/shared/EndpointConfiguration.tsx)
  is a small shared control boundary. It emits a typed
  `spatial.change-intent.v1`; it does not call the API or infer authority in the
  browser.
- [ChangeIntentService](../../web/operator-dashboard/src/spatial/components/change-intent.ts)
  normalizes form, voice and Spatial sources, computes a deterministic field
  diff, rejects stale/occupied/unauthorized/offline paths, requires explicit
  apply and deduplicates by actor/idempotency key.
- [query composition](../../web/operator-dashboard/src/spatial/components/query-composition.ts)
  maps supported questions to bounded registered components and virtualization
  budgets.
- [resource terminology and contracts](../../web/operator-dashboard/src/spatial/components/resource-terminology.ts)
  preserve exact `q_atoms` and reject fiat framing. Resource summaries carry
  source revision, rate-card revision and evidence references.
- [action feedback](../../web/operator-dashboard/src/spatial/components/action-feedback.ts)
  models partial completion, evidence, safe next action and attention without
  exposing hidden reasoning.

## Authority and rollout

`spatial_change_intent_enabled` defaults off. The flag only controls whether a
Spatial configuration surface is shown; authorization, canonical command
translation, Hypervisor revalidation, audit and final revision remain Node/API
responsibilities. The Classic UI remains the direct-control and recovery
fallback.

## Verification

The focused unit evidence is in
`web/operator-dashboard/tests/unit/spatial-m10.test.ts`. Run the full frontend
gate from `web/operator-dashboard`:

```text
pnpm test
pnpm typecheck
pnpm build
pnpm lint
```

Repository traceability gates remain:

```text
python tools/verify-spatial-coverage.py
python tools/verify-docs-links.py
python tools/verify-dashboard-seams.py
```

See [IMPLEMENTATION-COVERAGE.md](./IMPLEMENTATION-COVERAGE.md) for the M10.1–M10.9 acceptance registry and stable contract/event IDs.
