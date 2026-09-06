# Spatial UI Implementation Coverage

**Status:** Active implementation registry  
**Contract registry version:** 1  
**Last reviewed:** 2026-09-05  
**Owners:** Spatial UI maintainers and the owning Node subsystem maintainers

This registry is the traceability boundary between the accepted spatial ADRs,
the slices in the [development roadmap](./DEVELOPMENT-ROADMAP.md), and executable
validation. It records implementation coverage; it does not replace an ADR.

Status values are `planned`, `in-progress`, `verified`, or `deferred`. A
`verified` entry requires the named automated test or validation evidence. A
`deferred` entry requires a reason and must not be treated as implemented.

## ADR coverage matrix

| Invariant or ADR | Owner module | Planned slice | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- | --- |
| [ADR-001](./ADR-001-primary-agent-scope.md): one Node-scoped Primary Agent Slot; rebinding does not replace the Node or Workspace | `web/operator-dashboard/src/spatial/data/primary-agent-slot.ts`; `web/operator-dashboard/src/spatial/data/primary-agent-binding.ts` | M3.1-M3.6 | `tests/unit/spatial-primary-agent-slot.test.ts`; `tests/unit/spatial-primary-agent-binding.test.ts`; M3.6 management coverage | verified | Node service persistence remains an adapter behind the same contract |
| [ADR-002](./ADR-002-node-workspace-ownership.md): Workspace is Node-owned and survives Agent failure/replacement | `web/operator-dashboard/src/spatial/workspace/`; future `src/aidn_hypervisor/spatial/workspace.py` | M2.5-M2.7, M6.7, M9.1 | workspace repository contract tests; offline/rebind Playwright flow | in-progress | M2 verifies the typed frontend/persistence seam; durable Node store remains a later backend slice |
| [ADR-003](./ADR-003-orbital-attention-system.md): autonomous activity enters a bounded attention queue without stealing focus | `web/operator-dashboard/src/spatial/topology/attention.ts`; `web/operator-dashboard/src/spatial/workspace/SpatialTopologySurface.tsx` | M5.8-M5.10 | `tests/unit/spatial-topology.test.ts`; `tests/e2e/spatial-topology.spec.ts` | verified | Node Event Store replay remains an adapter seam |
| [ADR-004](./ADR-004-primary-agent-visual-state-language.md): agent state is multi-channel, accessible, and preserves OFFLINE/reduced-motion meaning | `web/operator-dashboard/src/spatial/prototype/`; `web/operator-dashboard/src/spatial/data/primary-agent-state.ts`; `web/operator-dashboard/src/spatial/data/primary-agent-presence.ts` | M1.5, M3.4-M3.5, M11.2 | `tests/unit/spatial-primary-agent-state.test.ts`; `tests/unit/spatial-primary-agent-presence.test.ts`; Spatial workspace accessibility path | verified | Device-lab visual snapshots remain a later M11 hardening pass |
| [ADR-005](./ADR-005-spatial-entity-topology.md): Agent, Endpoint, Service, Session, and Artifact remain distinct semantic classes | `web/operator-dashboard/src/spatial/topology/`; `web/operator-dashboard/src/spatial/prototype/SpatialEntityScene.tsx` | M1.6, M2.4, M5.1-M5.6, M7.6 | `tests/unit/spatial-topology.test.ts`; topology E2E; endpoint energy renderer metadata | verified | Node-owned topology persistence remains an adapter seam |
| [ADR-006](./ADR-006-workspace-sessions-context-graph.md): Workspace Session and protocol session are distinct; a branch has one structural parent and optional context references | `web/operator-dashboard/src/spatial/interaction/session-graph.ts`; future `src/aidn_hypervisor/spatial/sessions.py` | M4.2-M4.10 | `tests/unit/spatial-interaction.test.ts`; collapse/restore surface path | in-progress | Frontend durable adapter is verified; Node persistence remains a later backend seam |
| [ADR-007](./ADR-007-spatial-memory-aging-clustering.md): history ages and virtualizes without semantic loss | `web/operator-dashboard/src/spatial/memory/`; `web/operator-dashboard/src/spatial/contracts/index.ts` | M8.1-M8.8 | `tests/unit/spatial-memory.test.ts`; `tests/e2e/spatial-memory.spec.ts`; typed memory event/contract parsers | verified | Production Node memory persistence remains an adapter seam |
| [ADR-008](./ADR-008-entity-uniqueness-and-provenance.md), `ENTITY-INV-001`-`008`: one primary presence; projections are non-authoritative references | `web/operator-dashboard/src/spatial/topology/reference-registry.ts`; `web/operator-dashboard/src/spatial/topology/provenance.ts` | M2.4, M5.1, M5.7, M6.5, M8.6 | registry/provenance unit tests; focus non-mutation E2E | verified | Node durable constraints remain an adapter seam |
| [ADR-009](./ADR-009-multi-device-workspace-and-mobile-navigation.md): devices share semantic Workspace state but keep independent viewport state | `web/operator-dashboard/src/spatial/multidevice/`; `web/operator-dashboard/src/spatial/contracts/index.ts`; `web/operator-dashboard/tests/unit/spatial-multidevice.test.ts` | M9.1-M9.7 | multi-device service/gesture/contract tests; flag-gated desktop/mobile surface | verified | Durable Node transport remains an adapter seam |
| [ADR-010](./ADR-010-node-status-and-recovery-access.md), `STATUS-INV-001`-`008`: System Menu and authoritative Status work without the Agent or renderer | `web/operator-dashboard/src/spatial/status/`; typed Node clients and recovery command seam | M6.1-M6.7 | `spatial-status.test.ts`; System Menu unit/Playwright fault flows; freshness/revision contract tests | verified | Node production probe wiring remains an adapter seam |
| [ADR-011](./ADR-011-agent-mediated-component-interface.md), `COMP-INV-001`-`010`: registered components and typed intents share the canonical command boundary | `web/operator-dashboard/src/spatial/interaction/intent-gateway.ts`; `component-registry.ts`; `components/`; `components/shared/`; `hardening/authorization.ts` | M4.1, M4.4-M4.5, M10.1-M10.9, M11.1 | `tests/unit/spatial-interaction.test.ts`; `tests/unit/spatial-m10.test.ts`; `tests/unit/spatial-m11.test.ts`; M10 E2E | verified | Node command/MCP persistence remains an adapter behind the same decision contract |
| [ADR-012](./ADR-012-local-trust-boundary-and-mediated-remote-resources.md), `SEC-UI-001`-`010`: remote resources remain mediated, minimized, untrusted, and non-authoritative | `web/operator-dashboard/src/spatial/remote/`; typed Node remoteMediation client seam | M7.1-M7.7 | `tests/unit/spatial-remote-mediation.test.tsx`; typed contract/event tests; hostile-output and timeout paths | verified | Production adapter and durable Node settlement remain behind the typed client seam |
| [ADR-013](./ADR-013-aidn-milky-glass-neumorphism-visual-design.md): the Spatial material system is tokenized, readable, responsive, and motion-safe | `web/operator-dashboard/src/spatial/theme/`; `web/operator-dashboard/src/spatial/primitives/`; `hardening/accessibility.ts` | M1.1-M1.2, M11.2, M11.8 | `tests/unit/spatial-theme.test.tsx`; `tests/unit/spatial-primitives.test.tsx`; `tests/e2e/spatial-theme.spec.ts`; `tests/unit/spatial-m11.test.ts`; `pnpm test:a11y`; `pnpm verify:theme` | verified | Device-lab screenshot baselines remain an optional follow-up |
| [ADR-014](./ADR-014-spatial-ui-technical-architecture.md): Three.js creates space, DOM creates interface, and server/client state boundaries stay explicit | `web/operator-dashboard/src/spatial/workspace/`; `web/operator-dashboard/src/spatial/data/`; `web/operator-dashboard/src/spatial/hardening/`; `web/operator-dashboard/src/lib/` | M0.5-M1.8, M2, M11.4-M11.9 | bundle report; Spatial data/workspace unit and Playwright suites; M11 hardening tests; capability/fallback and rollout gates | verified | Node production adapters remain outside the browser boundary |

## M0 acceptance coverage

This table makes every M0 acceptance criterion executable or explicitly
deferred. Later milestones must add their criteria before their first slice is
implemented.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M0.1-AC-001` | ADR-001 through ADR-014 appear in the matrix | `tools/verify-spatial-coverage.py` | verified | None |
| `M0.1-AC-002` | Every registered criterion names validation or a deferral | `tools/verify-spatial-coverage.py` | verified | None |
| `M0.1-AC-003` | Broken local documentation links fail CI | `tools/verify-docs-links.py` in `.github/workflows/ci.yml` | verified | None |
| `M0.2-AC-001` | Frontend tests run locally without a live Node | `pnpm --dir web/operator-dashboard test` | verified | None |
| `M0.2-AC-002` | Playwright screenshots and traces are retained only on failure | `playwright.config.ts` plus CI artifact `if: failure()` | verified | None |
| `M0.2-AC-003` | WebKit covers iOS-class navigation behavior | `tests/e2e/classic-dashboard.spec.ts` project `mobile-webkit` | verified | None |
| `M0.2-AC-004` | Existing build and pnpm lockfile flow remain intact | `pnpm lint`, `pnpm typecheck`, `pnpm build`, frozen CI install | verified | None |
| `M0.3-AC-001` | Spatial bundle does not break Classic navigation | `tests/unit/spatial-route.test.tsx`; Classic hash Playwright tests | verified | None |
| `M0.3-AC-002` | Direct Spatial URL returns a usable fallback | `tests/unit/spatial-route.test.tsx`; direct-url Playwright test | verified | None |
| `M0.3-AC-003` | Disabling the flag does not delete Workspace data | route boundary is presentation-only; no Node mutation path exists; unit route test | verified | None |
| `M0.3-AC-004` | Selected Node context survives Classic/Spatial switching | route-switch Playwright test and previous-hash unit test | verified | None |
| `M0.4-AC-001` | `App.tsx` is a composition root | `tools/verify-dashboard-seams.py` | verified | None |
| `M0.4-AC-002` | Existing screens retain their hashes | `tests/unit/dashboard-routing.test.ts`; Classic hash Playwright tests | verified | None |
| `M0.4-AC-003` | API calls and payloads match baseline | API fixture contract tests | deferred | Full domain split occurs in M0.4 |
| `M0.4-AC-004` | Classic UI has no unintended visual changes | future baseline visual snapshots | deferred | M0.4 is outside PR-01 |
| `M0.4-AC-005` | Domain modules have no circular dependencies | `tools/verify-dashboard-seams.py` shell import graph | verified | Domain module split remains in the next M0.4 train |
| `M0.5-AC-001` | Classic does not load the Three.js chunk | `scripts/report-bundle.mjs`; production `tests/e2e/spatial-bundle.spec.ts` | verified | The report rejects Spatial assets in the Classic entry graph |
| `M0.5-AC-002` | Spatial chunk loads once | production `tests/e2e/spatial-bundle.spec.ts` | verified | React lazy-module caching is exercised across two route transitions |
| `M0.5-AC-003` | Build is reproducible | `pnpm install --frozen-lockfile`; `pnpm bundle:repro` | verified | The deterministic bundle report is compared across repeat builds |
| `M0.5-AC-004` | Bundle budget is visible in CI | `scripts/report-bundle.mjs` in `.github/workflows/ci.yml` | verified | gzip/Brotli ceilings and the report artifact are emitted by CI |
| `M0.5-AC-005` | Dependency changes preserve generated-asset activation semantics | `M0.5-DEPENDENCIES-AND-BUNDLE.md`; `tools/build-operator-dashboard.sh` boundary | verified | The report is outside `dist`, so atomic static-asset staging remains unchanged |

## M1.1 acceptance coverage

The first Spatial visual slice records its acceptance evidence separately from
the repository-foundation criteria above. A row is verified only when the
named unit, browser, or static validation is present and passing.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M1.1-AC-001` | Primary, secondary, and muted text meet the WCAG AA target on their specimen backgrounds | `web/operator-dashboard/tests/unit/spatial-theme.test.tsx`; `M1.1-MILKY-GLASS-TOKENS.md` contrast table | verified | None |
| `M1.1-AC-002` | Spatial surfaces remain distinguishable without a heavy border | `pnpm verify:theme`; tokenized shadow/radius rules in `spatial-theme.css`; `tests/e2e/spatial-theme.spec.ts` fixture | verified | None |
| `M1.1-AC-003` | Unsupported `backdrop-filter` receives a readable opaque surface | `pnpm verify:theme`; opaque base plus `@supports` enhancement in `spatial-theme.css`; fallback fixture in `tests/e2e/spatial-theme.spec.ts` | verified | None |
| `M1.1-AC-004` | Reduced transparency preserves hierarchy and removes blur dependence | profile boundary assertions in `tests/unit/spatial-theme.test.tsx`; Chromium profile flow in `tests/e2e/spatial-theme.spec.ts`; `pnpm verify:theme` | verified | None |

## M1.2 acceptance coverage

The DOM primitive slice records its contract evidence separately from the token
foundation. A row is verified only when the named unit, browser, or static
validation is present and passing.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M1.2-AC-001` | Semantics remain native and independent of visual placement | `tests/unit/spatial-primitives.test.tsx`; primitive `data-aidn-*` contract | verified | None |
| `M1.2-AC-002` | Hover, active, focus-visible, and disabled states are distinguishable | `spatial-theme.css` state selectors; keyboard path in `tests/e2e/spatial-theme.spec.ts`; `pnpm verify:theme` | verified | None |
| `M1.2-AC-003` | Interactive targets meet the established touch minimum | tokenized 44px control sizing in `spatial-theme.css`; `tests/unit/spatial-primitives.test.tsx`; `pnpm test:a11y` | verified | None |
| `M1.2-AC-004` | `Button` does not implicitly submit without an explicit opt-in | `tests/unit/spatial-primitives.test.tsx` (`does not submit a form unless...`) | verified | None |
| `M1.2-AC-005` | Icon-only controls require a screen-reader label | required `aria-label` type contract; tooltip/unit coverage; `pnpm test:a11y` | verified | None |

## M1.3 acceptance coverage

The hybrid shell records its physical layer and recovery evidence separately
from the reusable DOM primitive contract. A row is verified only when the
named unit, browser, or static validation is present and passing.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M1.3-AC-001` | A DOM control can be activated above the canvas layer | `tests/e2e/spatial-theme.spec.ts` hybrid shell flow; `SpatialDomOverlay` interactive boundary | verified | None |
| `M1.3-AC-002` | Empty overlay space passes pointer events to canvas orbit/pan | `spatial-theme.css` pointer boundary selectors; hybrid shell E2E CSS assertions | verified | None |
| `M1.3-AC-003` | Resize/orientation changes preserve the selected Node | `tests/unit/spatial-workspace.test.tsx`; hybrid shell E2E viewport flow | verified | None |
| `M1.3-AC-004` | Renderer errors leave a usable DOM fallback | `tests/unit/spatial-workspace.test.tsx`; `SpatialRendererErrorBoundary` fallback and categorical log | verified | None |
| `M1.3-AC-005` | Keyboard focus cannot be trapped by the canvas | canvas `tabIndex="-1"`/`aria-hidden`; unit and Spatial E2E checks | verified | None |

## M1.4 acceptance coverage

The bounded white-atmosphere slice records environment and quality-profile
evidence before any canonical data integration.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M1.4-AC-001` | Distant objects lose contrast/saturation predictably | `spatialEntityLod` and fallback distance opacity; `tests/unit/spatial-prototype.test.tsx` | verified | None |
| `M1.4-AC-002` | Glass remains visible on an almost-white background | `SpatialPrimaryAgent` core/halo channels and `M1.4-WHITE-ATMOSPHERIC-ENVIRONMENT.md` | verified | None |
| `M1.4-AC-003` | Mobile idle uses a bounded renderer budget | `environment.ts` mobile profile; `tests/e2e/spatial-prototype.spec.ts` mobile path | verified | None |
| `M1.4-AC-004` | Hidden tabs do not run continuous animation/sampling | visibility-aware performance probe and hidden-frame unit assertion | verified | None |

## M1.5 acceptance coverage

The Primary Agent material remains deterministic and presentation-only until
the live slot/state slices in M3.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M1.5-AC-001` | Each mock state has at least two visual channels | `tests/unit/spatial-prototype.test.tsx`; `primary-agent.ts` visual map | verified | None |
| `M1.5-AC-002` | Color is not the only state signal | semantic label, geometry, motion, and channel contract in `primary-agent.ts` | verified | None |
| `M1.5-AC-003` | OFFLINE preserves the System placeholder | `[data-aidn-system-placeholder]` DOM assertion in `tests/e2e/spatial-prototype.spec.ts` | verified | None |
| `M1.5-AC-004` | Reduced motion replaces pulse with a static channel | reduced-motion unit assertion and theme reduced-motion profile | verified | None |
| `M1.5-AC-005` | Material has a simple LOD fallback | low/mobile `primaryAgentVisual` mapping and profile budgets | verified | None |

## M1.6 acceptance coverage

The mock topology is explicit, countable, pickable, and separate from future
canonical entity schemas.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M1.6-AC-001` | Agent, Endpoint, Artifact, and Attention classes are distinct | `spatialEntityCounts`; geometry/accent mapping; `pnpm verify:prototype` | verified | None |
| `M1.6-AC-002` | Hover/focus does not create a duplicate object | canvas `aria-hidden`/`tabIndex=-1`; native DOM entity list | verified | None |
| `M1.6-AC-003` | Click only changes local selection | `SpatialWorkspace.selectEntity`; no API import in prototype; unit/E2E selection path | verified | None |
| `M1.6-AC-004` | Mouse, touch, and keyboard selection share one contract | fallback pointer path, R3F click path, and `tests/e2e/spatial-prototype.spec.ts` | verified | None |
| `M1.6-AC-005` | LOD changes never change identity | pure `spatialEntityLod` function and stable IDs in unit test | verified | None |

## M1.7 acceptance coverage

Camera commands are device-local and bounded; they do not mutate entity or
Workspace state.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M1.7-AC-001` | HOME returns the Primary Agent view | `HOME_CAMERA`, visible HOME control, and Prototype A E2E flow | verified | None |
| `M1.7-AC-002` | Focus leaves world/entity coordinates unchanged | `focusSpatialEntity` unit assertion | verified | None |
| `M1.7-AC-003` | Rapid camera commands remain valid | `clampSpatialCamera` bounds and repeated zoom/pan pure functions | verified | None |
| `M1.7-AC-004` | Keyboard equivalents cover pointer/touch | `SpatialNavigationController` Home/Escape/+/- and native buttons | verified | None |
| `M1.7-AC-005` | Transitions cancel safely | monotonic `transitionToken` replaces local camera state without stale timers | verified | None |

## M1.8 acceptance coverage

The Prototype A gate exposes deterministic baseline evidence and bounded live
sampling without presenting it as a production performance SLO.

| Acceptance ID | Target | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M1.8-AC-001` | Desktop baseline remains near 60 FPS | `SPATIAL_PERFORMANCE_BUDGET`, gate unit test, and DOM gate readout | verified | Device-lab recording remains a later profiling pass |
| `M1.8-AC-002` | Focus transition starts below 100 ms | pointer-latency budget and local interaction marker | verified | None |
| `M1.8-AC-003` | Desktop frame budget targets about 16 ms | frame-time check in `evaluateSpatialPerformanceGate` | verified | None |
| `M1.8-AC-004` | Mobile remains usable at reduced detail | mobile E2E profile/fog/DPR assertions | verified | None |
| `M1.8-AC-005` | No blocking accessibility defect | `pnpm test:a11y`; canvas excluded and DOM controls native | verified | None |
| `M1.8-AC-006` | DOM and 3D share one visual system | shared atmosphere/token/entity contracts and Prototype A E2E | verified | None |

## M2.1 acceptance coverage

The first canonical data boundary is deliberately independent from the
renderer. Transport payloads are parsed, normalized, and diagnosed before a
future query/store layer can consume them.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M2.1-AC-001` | Malformed payload is rejected before a store boundary | `tests/unit/spatial-contracts.test.ts` malformed relation parser test | verified | None |
| `M2.1-AC-002` | Unknown additive fields do not break a compatible version | `tests/unit/spatial-contracts.test.ts` additive Agent fixture | verified | None |
| `M2.1-AC-003` | Breaking schema version produces an explicit incompatible state | `tests/unit/spatial-contracts.test.ts` incompatible-version diagnostic test | verified | None |
| `M2.1-AC-004` | Timestamp and freshness normalization is centralized | `normalizeSpatialTimestamp` and `normalizeSpatialFreshness` unit tests | verified | None |
| `M2.1-AC-005` | Agent, Endpoint, Session, Artifact, Attention, Status, and Relation have typed contracts | `spatialContractSchemas` export and discriminated fixture tests | verified | None |

## M2.2 acceptance coverage

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M2.2-AC-001` | Domain clients do not import renderer modules | `tests/unit/spatial-data.test.ts`; static import boundary | verified | None |
| `M2.2-AC-002` | Query keys include active Hypervisor and Node scope | scoped query-key unit test | verified | None |
| `M2.2-AC-003` | Node switching cannot reuse the previous Node cache | `tests/unit/spatial-runtime-data.test.tsx` scope-switch test | verified | None |
| `M2.2-AC-004` | Mutations expose narrow projection invalidation targets | `spatialInvalidationKeys()` unit assertions | verified | None |
| `M2.2-AC-005` | Auth, error categories, correlation and idempotency are typed | transport status/header tests | verified | None |

## M2.3 acceptance coverage

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M2.3-AC-001` | Raw events cannot update the renderer directly | gateway callback/cache adapter and import boundary | verified | None |
| `M2.3-AC-002` | Duplicate event IDs are idempotent | gateway replay/dedup unit test | verified | None |
| `M2.3-AC-003` | Reconnect resumes retained events with bounded backoff | resume cursor/reconnect delay tests | verified | None |
| `M2.3-AC-004` | Out-of-order and cross-Node events cannot roll state back | stale sequence/revision gateway test | verified | None |
| `M2.3-AC-005` | Unknown events are diagnosed and ignored safely | unknown/malformed event test | verified | None |

## M2.4 acceptance coverage

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M2.4-AC-001` | Renderer consumes projections rather than raw API records | workspace/canvas typed props and import boundary | verified | None |
| `M2.4-AC-002` | Equal canonical input produces equal view models | deterministic composition unit test | verified | None |
| `M2.4-AC-003` | Visual state, freshness and LOD labels are covered | `tests/unit/spatial-view-models.test.ts` | verified | None |
| `M2.4-AC-004` | Missing evidence remains UNKNOWN/offline instead of green | unknown evidence unit assertion | verified | None |
| `M2.4-AC-005` | Projections carry provenance but no secret payload fields | safe-field assertion and stripped contracts | verified | None |

## M2.5 acceptance coverage

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M2.5-AC-001` | Workspace ownership is Node-scoped, not Agent-scoped | ownership/model tests | verified | None |
| `M2.5-AC-002` | Agent replacement/detach preserves Workspace entities | `workspaceSurvivesAgentChange()` test | verified | None |
| `M2.5-AC-003` | Semantic and presentation revisions remain independent | model reset/version test | verified | None |
| `M2.5-AC-004` | Cross-Node snapshots are rejected | Node mismatch model test | verified | None |
| `M2.5-AC-005` | Presentation reset cannot mutate canonical data | model/repository persistence test | verified | None |

## M2.6 acceptance coverage

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M2.6-AC-001` | Snapshot and changes endpoints are revisioned and Node-scoped | repository/HTTP adapter contracts | verified | None |
| `M2.6-AC-002` | Shared mutations require revision and idempotency | validation/stale/duplicate tests | verified | None |
| `M2.6-AC-003` | Authorization and audit/change records are enforced | unauthorized operation/change assertions | verified | None |
| `M2.6-AC-004` | Wrong Node and Agent replacement races are rejected | repository conflict tests | verified | None |
| `M2.6-AC-005` | Partial persistence failures do not commit | fail-next-write transaction test | verified | None |
| `M2.6-AC-006` | Reload and corrupt presentation recovery are safe | reset fallback/reference tests | verified | None |

## M2.7 acceptance coverage

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M2.7-AC-001` | Initial Workspace snapshot enters through the typed query path | runtime data hook test | verified | None |
| `M2.7-AC-002` | Primary and canonical projections render without duplicate refs | uniqueness/view-model test | verified | None |
| `M2.7-AC-003` | Retained live events update Agent/Endpoint projections | fixture stream/gateway test | verified | None |
| `M2.7-AC-004` | Empty, loading, stale and offline states remain explicit | runtime state and DOM/canvas attributes | verified | None |
| `M2.7-AC-005` | Node switching clears old projections and parse errors recover safely | scope-switch and renderer boundary suites | verified | None |
| `M2.7-AC-006` | Query/cache loss cannot damage persisted Workspace state | repository/cache isolation tests | verified | None |

## M3.1 acceptance coverage

The Primary Agent Slot is a Node-owned role record. This slice keeps the
binding identity/runtime/grant references separate and does not claim that the
browser owns credentials or the Workspace.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M3.1-AC-001` | Slot contract is Node-scoped and separates role from identity/runtime references | `tests/unit/spatial-primary-agent-slot.test.ts` contract parser and secret-stripping assertions | verified | None |
| `M3.1-AC-002` | A Node has exactly one stable slot and cross-Node access is rejected | duplicate/create and ownership unit tests | verified | Durable Node service storage remains a later adapter |
| `M3.1-AC-003` | Lifecycle transitions are explicit and revoked is terminal | transition table and invalid-transition unit test | verified | Extended operational states are M3.4 |
| `M3.1-AC-004` | Bind/replace are atomic, audited, and preserve durable inbox identity | repository bind/replace/change-record test | verified | Canonical binding command API is M3.2 |
| `M3.1-AC-005` | Stale and concurrent operations cannot overwrite a newer slot revision | concurrent Promise and stale-revision repository test | verified | None |
| `M3.1-AC-006` | Reload and corrupted binding references fail safely without Workspace coupling | restart/idempotency and corrupt-reference tests | verified | Durable inbox delivery begins in M3.3 |

## M3.2 acceptance coverage

The binding API exposes one authorized, revisioned command path over the M3.1
slot seam. Plans contain only safe references; mutations emit the reserved
binding-changed event and an audit record without credential material.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M3.2-AC-001` | Inspect and create-plan responses are Node-scoped, typed, and secret-free | `tests/unit/spatial-primary-agent-binding.test.ts` inspect/plan assertions | verified | None |
| `M3.2-AC-002` | Authorized apply supports bind, replace, suspend, detach, revoke, and recover commands | binding API operation matrix in `spatial-primary-agent-binding.test.ts` | verified | None |
| `M3.2-AC-003` | Browser authorization and current-revision checks reject unauthorized or stale plans | typed `UNAUTHORIZED`/`STALE_REVISION` conflict assertions | verified | None |
| `M3.2-AC-004` | Idempotent retries do not create duplicate bindings or duplicate events | same-plan retry and idempotency assertions | verified | Node transport adapter remains a production integration seam |
| `M3.2-AC-005` | Every accepted mutation records actor/audit metadata without secrets | audit and `secret_material_present: false` assertions | verified | None |
| `M3.2-AC-006` | Revoke/detach lifecycle changes stop future delivery and cross-Node plans fail closed | revoke callback plus Node ownership conflict coverage | verified | Durable dispatcher wiring is exercised by M3.3 service tests |

## M3.3 acceptance coverage

Capability grants and binding-owned Hook delivery reuse a durable inbox model.
The browser receives filtered, redacted records and cannot acknowledge another
binding or read after revocation.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M3.3-AC-001` | Grants allowlist tools/categories and emit a grant-changed event | grant issue/revoke and event assertions in `spatial-primary-agent-delivery.test.ts` | verified | None |
| `M3.3-AC-002` | Disconnected bindings retain events and reconnect resumes from a bounded cursor | retained-event reconnect test | verified | None |
| `M3.3-AC-003` | Acknowledgement is idempotent and scoped to the originating binding | duplicate ack and cross-binding conflict assertions | verified | None |
| `M3.3-AC-004` | Type/resource/severity filters apply before delivery and revocation blocks reads | filter and revoked-reader tests | verified | None |
| `M3.3-AC-005` | Redaction removes credential/token/authorization fields before delivery | nested redaction assertion in delivery service test | verified | None |
| `M3.3-AC-006` | Retry, dead-letter, and replay preserve delivery identity without duplicate action | retry/dead-letter/replay matrix | verified | Production Event Store adapter remains behind the service interface |

## M3.4 acceptance coverage

The operational aggregator is authoritative for the frontend projection while
Node remains the source of truth. Precedence, freshness, provenance, and
monotonic revision checks are explicit.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M3.4-AC-001` | READY/LISTENING/THINKING/ACTING/WORKING/ATTENTION/CRITICAL/OFFLINE vocabulary is versioned | state contract and vocabulary test | verified | None |
| `M3.4-AC-002` | Conflicting inputs resolve with CRITICAL attention and action precedence | aggregate precedence tests | verified | None |
| `M3.4-AC-003` | Stale/unknown health never presents as online | stale probe and node health assertions | verified | None |
| `M3.4-AC-004` | Rapid transitions retain source, timestamp, and monotonic revision | aggregator transition/event assertions | verified | None |
| `M3.4-AC-005` | Disconnect during action and attention while thinking remain visible | disconnect/action and independent attention tests | verified | None |
| `M3.4-AC-006` | Recovery accepts newer evidence and rejects stale or mismatched state events | revision/slot mismatch assertions | verified | None |

## M3.5 acceptance coverage

Live Presence composes the slot, operational state, attention overlay, and
material profile through the existing gateway/cache/view-model boundary. The
renderer receives a typed view model only.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M3.5-AC-001` | Binding/state gateway events update cache, view model, and material without raw renderer transport | event hook and workspace integration tests | verified | None |
| `M3.5-AC-002` | Base operational state and attention overlay remain independent | `spatial-primary-agent-presence.test.ts` critical-while-thinking assertion | verified | None |
| `M3.5-AC-003` | Accessible label, lifecycle, binding, and last-seen evidence remain visible in DOM | Spatial workspace unit/E2E accessibility path | verified | None |
| `M3.5-AC-004` | OFFLINE/revoked Presence stays visible with quality and reduced-motion fallbacks | material profile test and renderer fallback assertions | verified | None |
| `M3.5-AC-005` | Color mapping is configurable without changing semantic state names | material override unit assertion | verified | None |
| `M3.5-AC-006` | System Menu remains an explicit placeholder and focus/details path stays keyboard reachable | Spatial workspace management/control tests | verified | Independent System Menu implementation is M6 |

## M3.6 acceptance coverage

The management surface is DOM-only and can be mounted inside the Spatial frame
or reused by a Classic fallback composition. It exposes safe operational
references, explicit action states, and keyboard/mobile-native controls.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M3.6-AC-001` | Identity, binding, connection, capabilities, hooks, inbox lag, last seen, slot and Node fields are present | `spatial-primary-agent-management.test.tsx` field assertions | verified | None |
| `M3.6-AC-002` | Unassigned, connecting, connected, degraded, revoked, and recovery labels are explicit | lifecycle/status mapping unit path | verified | Invalid-credentials/protocol health adapters remain typed extension points |
| `M3.6-AC-003` | Credentials and secrets are never rendered | safe-note and typed-reference-only props; binding audit tests | verified | None |
| `M3.6-AC-004` | Revoke requires an explicit confirmation step | management component confirmation test | verified | None |
| `M3.6-AC-005` | Disabled actions expose a reason and preserve native keyboard semantics | disabled-action component test and native button controls | verified | None |
| `M3.6-AC-006` | Surface remains usable in Spatial frame and Classic fallback at mobile widths | DOM-only composition, responsive CSS, and workspace keyboard path | verified | Classic route integration remains a composition follow-up, no WebGL dependency |

## M4.1 acceptance coverage

The Intent Gateway is the typed, scope-checked boundary shared by every
interaction modality. It carries references and structured facts, never secret
material or permission decisions.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M4.1-AC-001` | Text, voice, form, and spatial input share one versioned envelope | `spatialIntentEnvelopeSchema`; interaction unit tests | verified | None |
| `M4.1-AC-002` | Empty, oversized, malformed, and byte-bearing input is rejected | `IntentGatewayError` validation paths; interaction unit tests | verified | None |
| `M4.1-AC-003` | Workspace/Node scope and stale target revisions are enforced | gateway scope/revision tests | verified | None |
| `M4.1-AC-004` | Duplicate idempotency keys return one canonical intent | gateway duplicate/audit test | verified | None |
| `M4.1-AC-005` | Authorization is applied after parsing and before acceptance | gateway authorization test | verified | Node policy adapter remains external |
| `M4.1-AC-006` | Audit exposes safe metadata without whole text or secret material | safe audit projection and stripped contracts | verified | None |

## M4.2 acceptance coverage

The Interaction Seed keeps entry points semantic and cancellable before an
operator creates a durable root.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M4.2-AC-001` | Desktop empty click, mobile long press, and keyboard shortcut share seed states | `InteractionSeedController`; shortcut/long-press unit paths | verified | None |
| `M4.2-AC-002` | Seed transitions SEED→COMPOSING→SUBMITTING→ACTIVE or failure/cancel | seed state-machine unit test | verified | None |
| `M4.2-AC-003` | Text, context, continue-from, and reference-only attachment inputs are retained | seed input methods and manifest schema | verified | None |
| `M4.2-AC-004` | Entity/control activation does not create a seed | `shouldOpenInteractionSeed()` test and DOM semantics | verified | None |
| `M4.2-AC-005` | Escape/cancel and keyboard focus never create an empty session | composer keyboard path and cancel state | verified | None |
| `M4.2-AC-006` | Duplicate submit produces one root through gateway idempotency | seed duplicate-submit test | verified | None |

## M4.3 acceptance coverage

Conversation state is projected from a durable session graph and remains
correlated to the accepted intent and active Primary Agent binding.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M4.3-AC-001` | Intent→operator turn→agent turn preserves correlation and provenance | durable conversation turn assertions | verified | None |
| `M4.3-AC-002` | Streaming is bounded, text-only, cancellable, and timeout-aware | chunk limit/sanitization/cancel/timeout service paths | verified | Browser transport adapter remains a later seam |
| `M4.3-AC-003` | Retry creates a response attempt without duplicating the operator prompt | retry turn-count test | verified | None |
| `M4.3-AC-004` | Old or revoked bindings cannot append response chunks | binding authority rejection test | verified | None |
| `M4.3-AC-005` | Disconnected submissions can be queued and resumed | connection/queue service methods | verified | Canonical Event Store transport remains later |
| `M4.3-AC-006` | Snapshot/restore keeps session, turns, and exchanges across reload | conversation snapshot restore API | verified | Durable Node storage remains a backend follow-up |

## M4.4 acceptance coverage

The v1 Component Registry is declarative, versioned, and shared by Classic and
Spatial renderers without accepting remote HTML or executable callbacks.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M4.4-AC-001` | Initial TextResponse, ConversationSurface, summaries, EndpointSummary, and OperationNotice are registered | `DEFAULT_SPATIAL_COMPONENTS` registry test | verified | None |
| `M4.4-AC-002` | Component metadata includes schemas, actions, capabilities, a11y, material, and viewport contract | definition snapshot and type contract | verified | None |
| `M4.4-AC-003` | Unknown components and version mismatches are rejected | registry resolution tests | verified | None |
| `M4.4-AC-004` | Invalid props/data and HTML/script/callback payloads are rejected | unsafe registry data test | verified | None |
| `M4.4-AC-005` | Actions become typed declarative operation intents | `createActionIntent()` allowlist test | verified | None |
| `M4.4-AC-006` | Classic and Spatial renderer names remain metadata, not executable payloads | registry metadata and static import boundary | verified | Full Classic migration remains M10 |

## M4.5 acceptance coverage

Presentation planning resolves only registered components and bounded semantic
placement descriptors; it cannot emit CSS, shaders, or executable code.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M4.5-AC-001` | Planner accepts intent/result/targets/focus/viewport inputs | `SpatialPresentationPlanner.plan()` contract | verified | None |
| `M4.5-AC-002` | Planner emits component/version, anchor, lifetime, density, importance, refs, and actions | planner output schema test | verified | None |
| `M4.5-AC-003` | Unknown/version-mismatched and stale targets are rejected | planner rejection paths | verified | None |
| `M4.5-AC-004` | Replanning updates a reuse key instead of duplicating a frame | planner reuse test | verified | None |
| `M4.5-AC-005` | Mobile density and progressive detail are bounded | mobile planner assertion and max-detail limit | verified | None |
| `M4.5-AC-006` | Unsafe CSS/shader/callback values never reach the result | unsafe presentation rejection test | verified | None |

## M4.6 acceptance coverage

Conversation Surface is DOM-only, accessible, bounded, and linked to durable
turns, citations, provenance, attachments, and Generated Objects.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M4.6-AC-001` | Transcript exposes operator/agent turns and streaming status | `ConversationSurface` log/turn markup and conversation service | verified | None |
| `M4.6-AC-002` | Retry/cancel/error feedback is explicit and recoverable | service controls plus live status copy | verified | None |
| `M4.6-AC-003` | Provenance/session links and Generated Object action remain visible | source turn/session markup and object action | verified | None |
| `M4.6-AC-004` | Streaming text cannot inject UI and remains bounded | sanitized response chunks and max transcript | verified | None |
| `M4.6-AC-005` | Live announcements, predictable focus, keyboard cancel, and mobile layout are present | `role=log`, focus effect, a11y/E2E path | verified | None |
| `M4.6-AC-006` | Surface does not steal camera focus or create duplicate entities | DOM-only component and hybrid overlay boundary | verified | None |

## M4.7 acceptance coverage

Workspace Session and Context Graph preserve structural parentage, references,
revisions, and protocol-session separation.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M4.7-AC-001` | Required relation types are explicit and typed | `SPATIAL_CONTEXT_RELATIONS` registry | verified | None |
| `M4.7-AC-002` | A branch has at most one structural parent and cycles are rejected | graph cycle/parent invariant test | verified | None |
| `M4.7-AC-003` | Context references are bounded and retain source/target revisions | context-node schema and graph snapshot | verified | None |
| `M4.7-AC-004` | Per-reference authorization and scope checks are enforced | graph authorization/scope paths | verified | Node policy adapter remains external |
| `M4.7-AC-005` | Reload preserves graph records and stale references cannot overwrite | graph restore/revision tests | verified | Durable Node store remains later |
| `M4.7-AC-006` | Protocol relation does not create a user chat automatically | `RELATED_PROTOCOL_SESSION` relation boundary | verified | None |

## M4.8 acceptance coverage

Generated Objects remain durable, revisioned, source-linked artifacts rather
than visual clones.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M4.8-AC-001` | Generated Object schema maps table/chart/file/report/object kinds | generated-object schema and kind mapping | verified | None |
| `M4.8-AC-002` | Every object links to its source turn/session and semantic anchor | generated object lifecycle test | verified | None |
| `M4.8-AC-003` | Updates are revision-checked and preserve identity | update/expected-revision service paths | verified | None |
| `M4.8-AC-004` | Collapse/pin/archive/restore are lifecycle operations, not deletion | object lifecycle methods | verified | None |
| `M4.8-AC-005` | Closing a presentation keeps the object and source relation | object snapshot and graph relation test | verified | None |
| `M4.8-AC-006` | Object counts are bounded per session | max-object service test | verified | None |

## M4.9 acceptance coverage

Conversation collapse produces a Session Artifact that can be restored or
branched without losing the Context Graph or camera return point.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M4.9-AC-001` | Collapse stores title, summary, timestamp, turn/object/context refs | artifact schema and collapse service | verified | None |
| `M4.9-AC-002` | Restore reopens the same session and preserves generated objects | artifact restore test | verified | None |
| `M4.9-AC-003` | Branch creates one structural parent and separate session identity | graph branch path | verified | None |
| `M4.9-AC-004` | Artifact is distinct from protocol session and is archivable/pinnable | artifact lifecycle schema | verified | None |
| `M4.9-AC-005` | Camera snapshot and graph survive serialization/reload | artifact snapshot fields and graph restore | verified | Node persistence remains later |
| `M4.9-AC-006` | Reduced-motion collapse transition is explicit | `artifactTransition(true)` unit assertion | verified | None |

## M4.10 acceptance coverage

Voice is an explicit-permission adapter into the same Intent Gateway and
Workspace Session root as text.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M4.10-AC-001` | Voice submission uses the canonical Intent envelope and modality | voice adapter unit test | verified | None |
| `M4.10-AC-002` | Permission denied/unavailable states provide a text fallback | voice permission/fallback methods | verified | None |
| `M4.10-AC-003` | Transcript is previewed, editable, and required before submit | transcript review/edit test | verified | None |
| `M4.10-AC-004` | Start/stop/cancel and visible mic states are explicit | capture state machine | verified | Web Audio device adapter remains injectable |
| `M4.10-AC-005` | Audio is reference-only and never stored in event/audit payloads | attachment manifest and safe audit assertions | verified | None |
| `M4.10-AC-006` | No hidden continuous recording is started | explicit `start()`/`stop()` adapter contract | verified | None |

## M5.1 acceptance coverage

Canonical references are workspace-scoped records; projections and focus
proxies never become a second entity.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M5.1-AC-001` | Repeated discovery returns one primary presence | `CanonicalReferenceRegistry` deduplication test | verified | None |
| `M5.1-AC-002` | Focus/context projections are read-only copies | registry `resolve(..., projection)` contract | verified | None |
| `M5.1-AC-003` | Presentation deletion does not delete canonical identity | registry `deletePresentation()` test | verified | None |
| `M5.1-AC-004` | Historical revisions remain inspectable | registry revision-history assertion | verified | None |
| `M5.1-AC-005` | Cross-workspace identity cannot leak familiarity | scoped lookup assertion | verified | None |
| `M5.1-AC-006` | Duplicate discovery emits measurable telemetry | registry telemetry assertion | verified | None |

## M5.2 acceptance coverage

Endpoint Energy is a distinct capability grammar; evidence-heavy metrics stay
in the information surface rather than being invented in geometry.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M5.2-AC-001` | Endpoint Energy remains distinct from Agent Presence | endpoint energy class and renderer metadata | verified | None |
| `M5.2-AC-002` | Latency/load/cost are not encoded as authoritative geometry | energy projection keeps metrics in details | verified | None |
| `M5.2-AC-003` | Unknown values remain explicit unknowns | `unknownMetrics` unit assertion | verified | None |
| `M5.2-AC-004` | LOD changes preserve endpoint class | `SpatialEntityScene` endpoint-energy metadata | verified | None |
| `M5.2-AC-005` | Selecting an endpoint does not submit an operation | topology E2E explicit-intent assertion | verified | None |
| `M5.2-AC-006` | Offline endpoints collapse/dim without identity loss | offline energy unit assertion | verified | None |

## M5.3 acceptance coverage

Discovery is a ranked, temporary Endpoint Arc projection with explicit
selection/promotion and bounded candidate materialization.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M5.3-AC-001` | Discovery candidates carry rank and relevance explanation | discovery schema/service test | verified | None |
| `M5.3-AC-002` | Empty and bounded candidate sets remain valid | discovery result schema and max-candidate path | verified | None |
| `M5.3-AC-003` | Duplicate/stale candidates are rejected or marked | deduplication and `markStale()` service paths | verified | None |
| `M5.3-AC-004` | Explicit selection promotes one canonical primary presence | discovery promotion unit/E2E path | verified | None |
| `M5.3-AC-005` | Dismissal removes presentation without deleting the Endpoint | discovery `dismiss()` lifecycle | verified | None |
| `M5.3-AC-006` | Candidate list is keyboard-addressable DOM | native button surface and topology E2E | verified | None |

## M5.4 acceptance coverage

Endpoint Information is a DOM, read-only surface with source revision,
freshness, provenance, and explicit unknown/loading states.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M5.4-AC-001` | Details render in DOM rather than WebGL | `SpatialTopologySurface` DOM boundary | verified | None |
| `M5.4-AC-002` | Source revision and freshness remain visible | details surface fields and E2E | verified | None |
| `M5.4-AC-003` | Unknown latency/load/cost are not fabricated | nullable details contract and E2E | verified | None |
| `M5.4-AC-004` | Provider/node provenance is inspectable | provenance field in details surface | verified | None |
| `M5.4-AC-005` | Loading/partial/stale/unavailable values remain typed | endpoint details freshness/availability schema | verified | None |
| `M5.4-AC-006` | Narrow viewport keeps details in the frame | responsive topology CSS and mobile-safe grid | verified | None |

## M5.5 acceptance coverage

Semantic Relations represent meaningful flow, not individual transport frames.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M5.5-AC-001` | Relation source/target references and revisions are typed | semantic relation schema | verified | None |
| `M5.5-AC-002` | Streaming chunks aggregate into one semantic relation | `aggregateStreamChunk()` unit test | verified | None |
| `M5.5-AC-003` | Direction and labels are inspectable without color | relation inspection direction label | verified | None |
| `M5.5-AC-004` | Inspecting a relation does not change topology | relation inspection is read-only | verified | None |
| `M5.5-AC-005` | Visible relation count is bounded | `visibleRelations(max)` contract | verified | None |
| `M5.5-AC-006` | Offscreen/stale endpoints remain reference-linked | revision-bearing relation payload | verified | None |

## M5.6 acceptance coverage

Local Subagents are secondary Agent actors and use the same local mediation
boundary for remote Endpoint access.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M5.6-AC-001` | Subagent is distinct from a remote Endpoint | lifecycle schema and delegation relation | verified | None |
| `M5.6-AC-002` | Remote access requires scoped mediation/grant | denied/mediated request path | verified | None |
| `M5.6-AC-003` | Completion preserves delegation provenance | relation and lifecycle assertions | verified | None |
| `M5.6-AC-004` | Orphaned state is recoverable and inspectable | `recoverOrphans()` path | verified | None |
| `M5.6-AC-005` | Spawn/working/completed/failed/cancelled are explicit | transition table and unit test | verified | None |
| `M5.6-AC-006` | Archive cleans presentation without deleting history | archived lifecycle state | verified | None |

## M5.7 acceptance coverage

Interaction provenance is local operational history, not authorization or
global reputation.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M5.7-AC-001` | Duplicate interaction events do not increment counters twice | idempotency unit assertion | verified | None |
| `M5.7-AC-002` | Failed/timeout outcomes remain visible | outcome counters and history | verified | None |
| `M5.7-AC-003` | Familiarity never grants authorization | provenance service has no grant path | verified | Node policy remains authoritative |
| `M5.7-AC-004` | Global reputation is stored separately | separate reputation map assertion | verified | None |
| `M5.7-AC-005` | Historical Endpoint revisions remain inspectable | `inspectHistory()` contract | verified | None |
| `M5.7-AC-006` | Records are scoped to Node/Workspace/Primary Agent | versioned provenance payload fields | verified | None |

## M5.8 acceptance coverage

Attention Items form a bounded, redacted queue that survives disconnects and
keeps lifecycle actions distinct.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M5.8-AC-001` | Attention model carries source, subject, severity, state, and scope | attention item schema | verified | None |
| `M5.8-AC-002` | Duplicate source events produce one item | queue source-index assertion | verified | None |
| `M5.8-AC-003` | Redaction removes secret-like summary material | redacted summary unit assertion | verified | None |
| `M5.8-AC-004` | Disconnected queue reconnects without losing unread items | queue connection/reconnect API | verified | Node Event Store replay remains adapter |
| `M5.8-AC-005` | Critical items remain separate from regular grouping | marker projection critical-lane assertion | verified | None |
| `M5.8-AC-006` | Seen/ack/resolved/archive/dismiss are distinct idempotent states | queue transition table | verified | None |

## M5.9 acceptance coverage

Orbital markers are stable, bounded presentation instances; the accessible
attention list remains the authoritative interaction surface.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M5.9-AC-001` | Marker slots remain stable across reprojection | stable slot map in marker service | verified | None |
| `M5.9-AC-002` | Severity maps to orbit lanes and non-color metadata | lane/severity schema and unit test | verified | None |
| `M5.9-AC-003` | Visible marker count is bounded and regular items aggregate | max-visible marker assertion | verified | None |
| `M5.9-AC-004` | Attention remains keyboard-accessible in DOM | topology surface native buttons | verified | None |
| `M5.9-AC-005` | Reduced motion uses static angular velocity | reduced-motion unit assertion | verified | None |
| `M5.9-AC-006` | Autonomous arrival does not steal camera focus | topology focus E2E viewport assertion | verified | None |

## M5.10 acceptance coverage

Focus Mode translates the viewport temporarily and routes any destructive
proposal through a canonical action callback.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M5.10-AC-001` | Inspect/focus state is explicit and source-linked | focus schema/controller | verified | None |
| `M5.10-AC-002` | Acknowledge/dismiss/archive update the queue, not the entity | focus action tests | verified | None |
| `M5.10-AC-003` | Source-unavailable state is explicit | source availability focus path | verified | None |
| `M5.10-AC-004` | Return restores the previous viewport reference | `returnFromFocus()` unit/E2E path | verified | None |
| `M5.10-AC-005` | SHOW_IN_WORKSPACE is temporary and preserves world positions | `world_position_preserved` assertion | verified | None |
| `M5.10-AC-006` | Destructive proposals require canonical plan acceptance | `onProposeAction` callback boundary | verified | None |

## M6.1 acceptance coverage

The Status Aggregator consumes direct Node probe evidence and never asks the
Primary Agent or an LLM to become an authority.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M6.1-AC-001` | Node, Hypervisor, Agent, MCP, Hooks, Network, Consensus, Wallet, Sessions, Tasks, Endpoints, Providers/Runtimes, and resources have typed component slots | `SPATIAL_STATUS_COMPONENT_KINDS`; aggregator probe contract | verified | Production probe adapters remain injectable |
| `M6.1-AC-002` | Partial probe failure preserves healthy components and marks the failed component UNKNOWN | `spatial-status.test.ts` partial probe test | verified | None |
| `M6.1-AC-003` | Cached ONLINE evidence is never returned as current ONLINE | `readCached()` freshness assertion | verified | None |
| `M6.1-AC-004` | Snapshot revision and generated/observed timestamps are consistent | aggregator revision and contract parsing | verified | Node Event Store persistence remains an adapter |
| `M6.1-AC-005` | Status evidence is bounded and redacted before presentation | evidence/details bounds and authorization fields | verified | None |
| `M6.1-AC-006` | Aggregation has no Agent/LLM dependency | `SpatialStatusAggregator` constructor/probe API and static seam check | verified | None |

## M6.2 acceptance coverage

System Menu is rendered by the Node UI shell and stays available when the
Spatial renderer is unavailable.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M6.2-AC-001` | Permanent System Menu exposes Status, Primary Agent, Node Settings, Appearance, Network, Wallet, Permissions, and Advanced | `SystemMenu` navigation unit test | verified | None |
| `M6.2-AC-002` | Menu is available for an unassigned/offline Agent | fallback snapshot and offline fixture path | verified | None |
| `M6.2-AC-003` | Menu remains available after WebGL2/renderer failure | `spatial-recovery.spec.ts` WebGL fallback | verified | None |
| `M6.2-AC-004` | Escape closes and focus is trapped inside the dialog | `SystemMenu` keyboard handler and unit test | verified | None |
| `M6.2-AC-005` | Dialog has menu semantics and readable DOM controls | role/aria assertions and `pnpm test:a11y` | verified | None |
| `M6.2-AC-006` | Direct Classic route remains reachable | route boundary fallback and Classic route Playwright tests | verified | None |

## M6.3 acceptance coverage

Status Summary is compact, factual, non-color-dependent, and explicitly
labels UNKNOWN/STALE/partial evidence.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M6.3-AC-001` | Component rows expose state text, observed time, and freshness | System Menu status summary DOM | verified | None |
| `M6.3-AC-002` | State meaning is not conveyed by color alone | text state labels and `StatusLabel` semantics | verified | None |
| `M6.3-AC-003` | Rows are keyboard-focusable and drill down to details | native row buttons and details unit test | verified | None |
| `M6.3-AC-004` | Refresh only requests status and does not mutate Workspace | `onRefresh` callback assertion | verified | Node transport remains adapter-backed |
| `M6.3-AC-005` | Warning count and partial-probe marker remain visible | summary action row fixture | verified | None |
| `M6.3-AC-006` | Mobile summary remains readable in the bottom-sheet frame | mobile Playwright flow and responsive CSS | verified | None |

## M6.4 acceptance coverage

Details share the selected snapshot revision and expose bounded evidence with
an explicit authorization state.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M6.4-AC-001` | Summary and Details display one snapshot revision | details heading revision assertion | verified | None |
| `M6.4-AC-002` | Component identity, source, observed time, freshness, and issue code are typed | status details contract/UI | verified | None |
| `M6.4-AC-003` | Last events and raw evidence are bounded | schema max lengths and bounded render slices | verified | None |
| `M6.4-AC-004` | Unauthorized evidence is explicit instead of silently omitted | authorization notice path | verified | Node policy remains authoritative |
| `M6.4-AC-005` | No secret or private topology material is copied into evidence | aggregator redaction test | verified | None |
| `M6.4-AC-006` | Narrow viewport uses an adaptive details frame | mobile System Menu Playwright flow | verified | None |

## M6.5 acceptance coverage

SHOW_IN_WORKSPACE resolves canonical references and requests a temporary focus;
it never creates a duplicate entity or changes world coordinates.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M6.5-AC-001` | Existing canonical presence resolves to FOCUS | `StatusWorkspaceBridge` unit test | verified | None |
| `M6.5-AC-002` | SHOW_IN_WORKSPACE preserves world position | bridge result `world_position_preserved` contract | verified | Viewport focus adapter remains injectable |
| `M6.5-AC-003` | Missing spatial representation opens Details only | bridge `NO_SPATIAL_REPRESENTATION` path | verified | None |
| `M6.5-AC-004` | Stale/unavailable references remain explicit | bridge stale/unavailable result states | verified | None |
| `M6.5-AC-005` | Wrong workspace is rejected | cross-scope bridge unit assertion | verified | None |
| `M6.5-AC-006` | Reduced-motion focus remains immediate and non-mutating | existing Spatial focus reduced-motion boundary | verified | None |

## M6.6 acceptance coverage

Recovery actions use a plan/apply command seam with capability, revision,
confirmation, audit, and idempotency checks.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M6.6-AC-001` | Initial recovery actions are registered and typed | `SPATIAL_RECOVERY_ACTIONS` and recovery service | verified | Handler wiring is adapter-provided |
| `M6.6-AC-002` | Status presentation cannot bypass command validation | service `plan()`/`apply()` boundary | verified | None |
| `M6.6-AC-003` | Stale plans are rejected | recovery unit stale revision assertion | verified | None |
| `M6.6-AC-004` | Duplicate apply is idempotent and audited | recovery unit NOOP/audit assertion | verified | None |
| `M6.6-AC-005` | Destructive actions require explicit confirmation and capability | recovery unit confirmation/capability assertions | verified | None |
| `M6.6-AC-006` | Results carry finality state and safe error code | `spatial.recovery.resulted.v1` contract | verified | Live Node command event wiring remains adapter |

## M6.7 acceptance coverage

Offline and partial recovery preserve semantic Workspace state while labeling
last-known data and retaining a Classic escape hatch.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M6.7-AC-001` | Last-known status includes timestamp and is read-only | cached status UI notice and aggregator test | verified | None |
| `M6.7-AC-002` | Partial Node/API failure does not clear healthy Workspace data | workspace data partial path and aggregator test | verified | None |
| `M6.7-AC-003` | Retry is bounded by the existing transport/backoff seam | typed refresh callback and reconnect backoff | verified | Production retry policy remains adapter |
| `M6.7-AC-004` | Classic fallback remains accessible | fallback E2E and route boundary unit test | verified | None |
| `M6.7-AC-005` | Renderer recovery keeps semantic state and DOM controls | renderer error boundary plus System Menu sibling | verified | None |
| `M6.7-AC-006` | Node switch cannot retain old Node status data | scope reset in `useSpatialWorkspaceData` and scope assertions | verified | Durable multi-device switch begins in M9 |

## M7.1 acceptance coverage

The local mediation service is the only browser-visible remote boundary; it
resolves canonical Endpoint references and delegates transport to an injected
Node adapter.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M7.1-AC-001` | Presentation and Primary Agent receive no arbitrary URL/socket transport API | `LocalRemoteMediationService` accepts only registered adapter IDs and typed request contracts | verified | Production adapter wiring remains a Node client seam |
| `M7.1-AC-002` | Endpoint address is resolved from the workspace-scoped canonical registry | unknown URL/reference unit assertion and `CanonicalReferenceRegistry` registration | verified | None |
| `M7.1-AC-003` | Denied Endpoint never invokes the transport adapter | revoked endpoint negative unit test | verified | None |
| `M7.1-AC-004` | Timeout/cancel produces typed failure and releases the in-flight controller | timeout unit test and `AbortController` cleanup path | verified | Node cancellation persistence remains adapter-backed |
| `M7.1-AC-005` | Request bounds, correlation, idempotency and mediation events are retained | remote request schema and service event log assertions | verified | Durable audit sink remains a Node adapter |
| `M7.1-AC-006` | Authorization, capability, availability, revision and session gates run before transport | authorization/stale/capability tests | verified | Policy decision source remains Node-owned |

## M7.2 acceptance coverage

Context manifests make every field crossing the local trust boundary explicit;
the browser projection never carries secrets or unrelated Workspace state.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M7.2-AC-001` | Manifest records purpose, capability, allowlist, policy revision and hash | `spatial.remote-context-manifest.v1` parser and manifest builder | verified | Cryptographic hash replacement remains a Node seam |
| `M7.2-AC-002` | Secret/system prompt/history/wallet/token fields are redacted before transport | secret minimization unit test | verified | None |
| `M7.2-AC-003` | Attachments are content-addressed and media/size limits are typed | attachment regex, MIME and payload limit contract | verified | Binary content storage remains Node-owned |
| `M7.2-AC-004` | Unrelated sessions, browser state and hidden context are absent by construction | allowlist-only fields in the request assertion | verified | None |
| `M7.2-AC-005` | Stale manifest/capability mismatch/cross-Workspace session is rejected | capability, stale and scope negative paths | verified | None |
| `M7.2-AC-006` | Manual frame exposes a what-will-be-sent summary and consent boundary | Endpoint Test Frame summary and explicit-submit UI test | verified | Consent persistence remains a Node adapter |

## M7.3 acceptance coverage

Remote output is data: it is MIME/size checked, classified, sanitized for
text display, and attached to local Endpoint provenance.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M7.3-AC-001` | Result schema, MIME and response size are validated | `spatial.remote-result.v1` parser and validator | verified | Streaming protocol adapter remains future work |
| `M7.3-AC-002` | Prompt injection is quarantined and cannot become an instruction | hostile-output unit test | verified | None |
| `M7.3-AC-003` | Script/HTML payload is rendered as inert text and never remote UI | script/HTML classification and `<pre>` text rendering test | verified | None |
| `M7.3-AC-004` | Invalid/oversized/malformed output gets a deterministic invalid state | validator status/classification contract | verified | Full streaming decoder remains an adapter seam |
| `M7.3-AC-005` | Result retains Endpoint, revision, request and correlation provenance | remote result and provenance schema assertions | verified | Durable provenance chain remains Node-owned |
| `M7.3-AC-006` | Invalid data remains auditable without unsafe rendering | result record plus `INVALID_RESULT` frame state | verified | None |

## M7.4 acceptance coverage

Endpoint Test Frame is a local registered component with explicit submit,
accessible state, and response/provenance in the same frame.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M7.4-AC-001` | Frame is created by the local planner from a canonical Endpoint | `createEndpointTestFrame()` unit path | verified | None |
| `M7.4-AC-002` | Opening/editing/focusing never submits a request | Endpoint Test Frame render test before submit | verified | None |
| `M7.4-AC-003` | Duplicate submit is idempotent | same idempotency key unit assertion | verified | Node replay store remains an adapter seam |
| `M7.4-AC-004` | Response appears in the originating frame with request/provenance | frame state/result DOM assertions | verified | None |
| `M7.4-AC-005` | Remote output cannot load a component, callback or executable action | safe text-only result model and hostile markup test | verified | None |
| `M7.4-AC-006` | Keyboard, labels and live status cover the complete manual flow | native textarea/buttons, `role=status`, a11y/unit path | verified | Device-lab snapshots remain later hardening |

## M7.5 acceptance coverage

Every request produces local accounting evidence. Free tests explicitly settle
zero usage; metered estimates and measured units remain Node-authoritative.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M7.5-AC-001` | Workspace Session and Protocol Session references stay distinct | remote request/accounting schemas | verified | Protocol session persistence remains Node-owned |
| `M7.5-AC-002` | Free Endpoint records zero cost explicitly | free fixture accounting assertion | verified | None |
| `M7.5-AC-003` | Metered Endpoint exposes estimate and measured usage from the mediation seam | metered fixture accounting assertion | verified | Rate-card settlement remains Node adapter |
| `M7.5-AC-004` | Settlement evidence does not create a second Endpoint entity | canonical registry + accounting reference model | verified | Durable entity constraints remain an existing adapter seam |
| `M7.5-AC-005` | Failed, cancelled and invalid requests use a typed charge policy/state | accounting state and charge-policy contract | verified | Provider-specific policy remains Node-owned |
| `M7.5-AC-006` | UI presents Node accounting evidence rather than calculating authority | accounting payload is rendered as evidence only | verified | Full Q/settlement UX belongs to M10 |

## M7.6 acceptance coverage

Remote resources remain metadata/provenance projections in the Endpoint Arc;
they never become conversational actors or duplicate canonical entities.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M7.6-AC-001` | Provider/remote identity is metadata attached to Endpoint provenance | endpoint provenance contract and details surface | verified | Provider freshness is Node-supplied |
| `M7.6-AC-002` | Local Subagent remains a distinct actor from a remote Endpoint | M5 topology registry and remote request actor refs | verified | None |
| `M7.6-AC-003` | Endpoint has one canonical presence across discovery/frame/result | canonical reference registry and frame endpoint_ref | verified | None |
| `M7.6-AC-004` | Request/result provenance is visible in the same local frame | Endpoint Test Frame provenance text | verified | None |
| `M7.6-AC-005` | Unavailable Endpoint produces local unavailable/rejected state, not an agent message | unavailable gate and typed frame states | verified | None |
| `M7.6-AC-006` | Remote feature rollback leaves local inspection/provenance available | `spatial_remote_mediation_enabled` default-off flag | verified | Production rollout policy remains deployment-owned |

## M7.7 acceptance coverage

The negative suite makes the ADR-012 boundary regression-proof and ensures
every hostile path is deterministic and bounded.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M7.7-AC-001` | Arbitrary URL, SSRF-style target and redirect-like input cannot be selected | canonical reference/URL rejection test | verified | Redirect policy is enforced by the Node adapter |
| `M7.7-AC-002` | Prompt injection and script/HTML payloads quarantine as inert data | hostile-output validator tests | verified | None |
| `M7.7-AC-003` | Secret leakage, oversized response and MIME mismatch are rejected/quarantined | validator classification and bounded response tests | verified | None |
| `M7.7-AC-004` | Duplicate/replayed response and wrong Endpoint revision do not duplicate or mutate state | idempotency/stale revision assertions | verified | Durable replay ledger remains Node-owned |
| `M7.7-AC-005` | Timeout/cancel, revoked Agent, insufficient authorization and cross-Workspace context are typed failures | timeout/authorization/scope tests | verified | None |
| `M7.7-AC-006` | Failure paths do not leave an in-flight lease/controller or hidden retry | controller cleanup and no-auto-submit assertions | verified | Provider lease settlement remains a Node adapter |

## M8.1 acceptance coverage

Preferred regions are deterministic presentation anchors around the Primary
Agent; manual placement remains local presentation state.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M8.1-AC-001` | Projection records map to Active Work, Agent Space, Recent, Cluster, Endpoint Arc, or Deep Memory | `SpatialMemoryEngine.layout()` and region unit assertions | verified | None |
| `M8.1-AC-002` | Primary Agent remains the HOME anchor and region anchors are semantic, not pixel-fixed | layout contract and `primary_agent_ref` assertion | verified | None |
| `M8.1-AC-003` | Same topology, seed, and policy revision produce deterministic positions with bounded collision checks | deterministic seed and placement unit path | verified | None |
| `M8.1-AC-004` | Manual move survives reflow until the operator resets layout | `move()`/reflow/reset unit assertion | verified | None |
| `M8.1-AC-005` | Mobile viewport uses the same anchors with an adaptive projection | viewport scale branch and responsive CSS; mobile E2E surface | verified | None |
| `M8.1-AC-006` | Layout changes do not mutate canonical entities or relations | presentation-only engine and event boundary test | verified | None |

## M8.2 acceptance coverage

Recent Memory is a bounded, inspectable inbox with explicit pin exceptions and
no history deletion.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M8.2-AC-001` | Fresh artifacts are ordered newest-first near the Primary Agent | `visibleRecent()` ordering unit assertion | verified | None |
| `M8.2-AC-002` | Visible Recent Memory respects a configurable budget | budget fixture with 12 artifacts | verified | None |
| `M8.2-AC-003` | Pinned items remain visible as an explicit exception | pinned overflow assertion | verified | None |
| `M8.2-AC-004` | Overflow is virtualized without deleting semantic records | render-state and record-count assertion | verified | None |
| `M8.2-AC-005` | Hidden history remains keyboard/search addressable | native memory buttons and metadata search path | verified | None |
| `M8.2-AC-006` | Unresolved attention does not silently disappear into history | unresolved aging/presentation assertion | verified | None |

## M8.3 acceptance coverage

Aging records lifecycle policy and uses hysteresis so time alone never deletes
semantic history.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M8.3-AC-001` | Lifecycle covers Active, Recent, Older, Clustered, Peripheral, and Virtualized states | level enum and aging fixture | verified | None |
| `M8.3-AC-002` | UTC inactivity, relevance, reuse, unresolved, and pin weight influence placement | aging/reuse/pin unit assertions | verified | None |
| `M8.3-AC-003` | Hysteresis prevents small timestamp changes from causing jitter | threshold hysteresis unit path | verified | None |
| `M8.3-AC-004` | Policy revision is carried in layout and cluster provenance | contract snapshot parser assertions | verified | None |
| `M8.3-AC-005` | Reuse returns an artifact toward Recent without changing its semantic reference | `reuse()` and record-count assertion | verified | None |
| `M8.3-AC-006` | Pin/unresolved state keeps important history near without deletion | pinned/unresolved unit fixture | verified | None |

## M8.4 acceptance coverage

Session Clusters are explainable presentation constructs with stable membership
references, manual groups, and explicit stale members.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M8.4-AC-001` | Structural, project, topic, Endpoint, Agent, subsystem, similarity, and manual criteria are typed | cluster criterion registry and service implementation | verified | None |
| `M8.4-AC-002` | Promotion exposes criterion, evidence, criterion revision, and provenance | cluster unit assertions and `spatial.memory-cluster.v1` | verified | None |
| `M8.4-AC-003` | Re-running promotion is idempotent and does not duplicate clusters | repeated `clusters()` assertion | verified | None |
| `M8.4-AC-004` | Manual grouping survives reclassification and supports member removal | manual group/remove-member unit path | verified | None |
| `M8.4-AC-005` | Stale or unavailable members remain explicit instead of being fabricated | stale member fixture | verified | None |
| `M8.4-AC-006` | Cluster movement is presentation-only and never rewrites canonical relation identity | cluster projections and relation reveal test | verified | None |

## M8.5 acceptance coverage

Relations stay quiet by default and become an accessible, bounded navigation
list on explicit reveal.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M8.5-AC-001` | Relation reveal is on-demand and bounded | `revealRelations()` max-size assertion | verified | None |
| `M8.5-AC-002` | Direction, type, and semantic text are available without color or hover | accessible relation text unit assertion | verified | None |
| `M8.5-AC-003` | Source/target orientation is consistent and inspectable | direction label assertion | verified | None |
| `M8.5-AC-004` | Offscreen references expose an anchor state rather than mutating topology | offscreen flags and world-position assertion | verified | None |
| `M8.5-AC-005` | Keyboard/DOM relation list is available from the memory surface | `<details>` relation surface E2E path | verified | None |
| `M8.5-AC-006` | Reveal never changes canonical entity or relation records | engine presentation-only boundary test | verified | None |

## M8.6 acceptance coverage

Pull-to-Focus materializes a temporary presentation and restores the prior
camera while preserving the canonical world position and target revision.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M8.6-AC-001` | Focus lifecycle is REQUESTED → MATERIALIZING → FOCUSED → RETURNING/PINNED | focus state-machine unit assertion | verified | None |
| `M8.6-AC-002` | Virtualized/offscreen targets materialize on demand and retain world position | deep artifact focus fixture | verified | None |
| `M8.6-AC-003` | Target revision, source, and restore camera are inspectable | focus contract parser | verified | None |
| `M8.6-AC-004` | Stale, unavailable, unauthorized, or tombstone references are explicit | unavailable focus unit assertion | verified | None |
| `M8.6-AC-005` | Reduced motion skips mandatory travel and remains cancellable | reduced-motion focus input and cancel path | verified | None |
| `M8.6-AC-006` | Pinning a focused target is explicit and does not create a duplicate identity | `pinFocus()` and projection identity assertion | verified | None |

## M8.7 acceptance coverage

Virtualization and LOD keep renderer work bounded while retaining searchable
semantic records and releasing materialized memory.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M8.7-AC-001` | LOD0–LOD3 preserve identity while changing only presentation detail | `planVirtualization()` LOD counts and identity assertions | verified | None |
| `M8.7-AC-002` | Viewport culling and offscreen suspension produce explicit virtualized state | culling fixture and telemetry | verified | None |
| `M8.7-AC-003` | Render budget remains bounded for 10, 1,000, and 20,000 artifacts | 20k performance scenario in `spatial-memory.test.ts` | verified | Device-lab GPU timings remain M11 work |
| `M8.7-AC-004` | Cluster summaries and DOM lists avoid full history materialization | cluster summary projection and bounded DOM list | verified | None |
| `M8.7-AC-005` | Search and relation references continue working for non-rendered objects | search/focus after virtualization unit path | verified | None |
| `M8.7-AC-006` | Repeated focus releases memory and reports materialization telemetry | materialize/release and telemetry assertion | verified | None |

## M8.8 acceptance coverage

Search is a reference-returning, authorization-filtered recall surface with a
deterministic metadata fallback and optional semantic adapter seam.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M8.8-AC-001` | Metadata search returns canonical references rather than object clones | search result contract and reference assertion | verified | None |
| `M8.8-AC-002` | Each result explains relevance evidence | result evidence unit assertion | verified | None |
| `M8.8-AC-003` | Unauthorized records are absent before ranking | authorization-filter fixture | verified | None |
| `M8.8-AC-004` | Stale/unavailable search references remain typed and inspectable | result state contract and unavailable path | verified | None |
| `M8.8-AC-005` | Search result opens Pull-to-Focus without topology mutation | memory surface E2E focus path | verified | None |
| `M8.8-AC-006` | No vector database is required for deterministic MVP recall | local metadata fallback and event parser test | verified | Semantic adapter remains injectable |

## M9.1 acceptance coverage

Shared semantic state and device-local viewport state are separate contracts.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M9.1-AC-001` | Two devices resolve the same Workspace revision and canonical references | `SpatialMultiDeviceWorkspaceService` world snapshot unit path | verified | None |
| `M9.1-AC-002` | Camera, zoom, focus, selection and opened frames remain device-local | independent desktop/mobile viewport unit assertion | verified | None |
| `M9.1-AC-003` | Shared pins and semantic anchors propagate without copying camera state | PIN/MOVE_ANCHOR mutation and viewport assertions | verified | None |
| `M9.1-AC-004` | Device IDs never grant mutation authority | authorization callback unit assertion | verified | Node capability wiring remains an adapter seam |
| `M9.1-AC-005` | HOME uses the Primary Agent when available and a safe default otherwise | default viewport contract and focus anchor | verified | None |
| `M9.1-AC-006` | Presentation geometry is local and reference-preserving | `createPresentationGeometry()` contract assertion | verified | None |

## M9.2 acceptance coverage

The mutation envelope is idempotent, revision-aware and never carries viewport
commands in the shared semantic stream.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M9.2-AC-001` | Envelope carries operation/idempotency, actor/device, base and target refs | `spatial.workspace-mutation.v1` parser unit assertion | verified | None |
| `M9.2-AC-002` | Disjoint stale mutations merge without losing a branch | concurrent disjoint mutation unit assertion | verified | Durable server merge remains an adapter seam |
| `M9.2-AC-003` | Same-target stale topology conflicts expose current evidence | conflict result revision/winner assertion | verified | None |
| `M9.2-AC-004` | Duplicate retry returns IDEMPOTENT and does not increment revision | duplicate idempotency unit assertion | verified | None |
| `M9.2-AC-005` | Unauthorized and invalid targets are rejected explicitly | authorization/target result paths | verified | None |
| `M9.2-AC-006` | Resolved mutation is auditable and carries resulting world revision | mutation-result contract and audit ref | verified | None |

## M9.3 acceptance coverage

Offline work is an explicit local queue with replay, rebase, conflict and
discard states; protocol/resource actions are not added to this queue.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M9.3-AC-001` | Pending mutations carry idempotency keys and deterministic replay order | offline queue unit fixture | verified | None |
| `M9.3-AC-002` | Connectivity state is visible as ONLINE/OFFLINE/RECONNECTING | queue contract and M9 surface readout | verified | None |
| `M9.3-AC-003` | Reconnect replay does not duplicate an already applied operation | replay/idempotent service path | verified | None |
| `M9.3-AC-004` | Stale/conflicting operations remain visible for operator resolution | conflict entry state and evidence | verified | Server-side conflict UI remains an adapter seam |
| `M9.3-AC-005` | Local operators can discard a queued mutation | discard unit assertion | verified | None |
| `M9.3-AC-006` | Authoritative actor authorization is rechecked before replay | service authorization callback path | verified | None |

## M9.4 acceptance coverage

Mobile navigation is a pure gesture controller with DOM/keyboard equivalents;
it changes a viewport, not Workspace topology.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M9.4-AC-001` | One-finger pan/rotate, pinch zoom and tap select have typed commands | mobile navigation reducer unit test | verified | None |
| `M9.4-AC-002` | Long press on empty space emits Seed only after the movement threshold | long-press/threshold unit assertion | verified | None |
| `M9.4-AC-003` | Long press after a drag does not seed and page scroll can win arbitration | scroll/form arbitration helper | verified | Device-lab WebKit timing remains M11 work |
| `M9.4-AC-004` | HOME, Escape and arrow navigation are keyboard accessible | keyboard fallback unit assertion and buttons | verified | None |
| `M9.4-AC-005` | Form inputs and buttons never accidentally capture a canvas drag | form target unit assertion | verified | None |
| `M9.4-AC-006` | Touch targets and mobile controls remain usable one-handed | 44px token contract and responsive CSS | verified | None |

## M9.5 acceptance coverage

Presentation geometry adapts per device while preserving canonical identity,
relations and keyboard-safe action surfaces.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M9.5-AC-001` | Desktop uses a focus frame and mobile uses a bottom sheet | geometry variant unit assertion | verified | None |
| `M9.5-AC-002` | Tablet uses a side panel without changing semantic refs | geometry contract | verified | None |
| `M9.5-AC-003` | Safe-area and keyboard insets are explicit geometry fields | geometry inset parser assertion | verified | None |
| `M9.5-AC-004` | Endpoint/Status/Conversation surfaces remain DOM-operable | existing DOM overlay plus M9 surface seam | verified | Full adaptive component matrix remains M11 work |
| `M9.5-AC-005` | Orientation changes preserve semantic focus | local viewport revision and focus ref fields | verified | None |
| `M9.5-AC-006` | Geometry revision never changes Workspace revision | service separation and unit assertion | verified | None |

## M9.6 acceptance coverage

Share View is an explicit, temporary focus authorization and never transfers
authority or overwrites another device's default camera.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M9.6-AC-001` | Owner explicitly creates a Share View with an audience and expiry | share service unit path | verified | None |
| `M9.6-AC-002` | Recipient accepts/declines/leaves only when addressed | audience authorization assertions | verified | None |
| `M9.6-AC-003` | Shared focus authorization is checked for target and recipient | applySharedFocus unit path | verified | None |
| `M9.6-AC-004` | Recipient camera changes locally; owner camera remains unchanged | independent viewport assertion | verified | None |
| `M9.6-AC-005` | Expired share cannot move a camera | expiry guard in service | verified | None |
| `M9.6-AC-006` | Share state is auditable and versioned | `spatial.share-view.v1` contract/event registry | verified | Durable audit persistence remains Node-owned |

## M9.7 acceptance coverage

The scale/failure seam exercises shared consistency and local independence
without requiring a browser-owned transport.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M9.7-AC-001` | Desktop/mobile online and offline paths retain semantic consistency | service + offline queue unit suite | verified | None |
| `M9.7-AC-002` | Different branches can merge while same-target conflict remains visible | concurrent mutation tests | verified | None |
| `M9.7-AC-003` | Agent replacement/revision/auth evidence remains explicit | Node-owned repository seam plus M9 result evidence | verified | Durable integration remains backend work |
| `M9.7-AC-004` | Viewport recovery, stale auth and duplicate replay are deterministic | viewport defaults and replay tests | verified | None |
| `M9.7-AC-005` | 1,000 semantic objects remain addressable with bounded local viewport state | scale fixture unit assertion | verified | GPU/WebGL device timings remain M11 work |
| `M9.7-AC-006` | WebGL fallback and reduced-motion recipients retain DOM controls | existing renderer fallback/a11y gates plus M9 feedback | verified | Full WebKit matrix remains M11 work |

## M10.1 acceptance coverage

The current Classic surface is inventoried as typed fragments before any
visual migration. EndpointConfiguration is traced from `dashboardApi.endpoints`
through the current JSX and the shared registry candidate.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M10.1-AC-001` | Every current App section has one inventory owner | `src/app/component-inventory.ts`; `spatial-m10.test.ts` | verified | None |
| `M10.1-AC-002` | Inventory records source, query key, mutations and states | typed `ComponentInventoryRecord` fields | verified | None |
| `M10.1-AC-003` | EndpointConfiguration API-to-JSX trace is explicit | `endpointConfigurationInventory` assertion | verified | Node endpoint revision adapter remains API-owned |
| `M10.1-AC-004` | Generated dashboard output is excluded from inventory | `validateComponentInventory` path guard | verified | None |
| `M10.1-AC-005` | First shared migration candidates are selected | `migration_priority` and candidate registry IDs | verified | Full decomposition remains M10.8 |
| `M10.1-AC-006` | Accessibility gaps and existing tests are recorded | inventory record fields and unit assertion | verified | None |

## M10.2 acceptance coverage

Component Registry v2 adds lifecycle and planner metadata while retaining the
declarative, non-executable M4 boundary.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M10.2-AC-001` | Registry records category, revision, variants, stream and viewport policy | `component-registry.ts` v2 fields | verified | None |
| `M10.2-AC-002` | Version migrations are deterministic and validated | `spatial-m10.test.ts` migration path | verified | Node-side durable migration remains an adapter |
| `M10.2-AC-003` | Unsupported viewport uses a registered fallback | `resolveForViewport` unit assertion | verified | None |
| `M10.2-AC-004` | Config variants require declared capabilities | `validateVariant` unit assertion | verified | None |
| `M10.2-AC-005` | Removed entries cannot resolve as remote components | deprecation rejection unit assertion | verified | None |
| `M10.2-AC-006` | Standard loading/empty/stale/offline/error states are declared | `supported_states` registry metadata | verified | Visual state matrix remains M11 hardening |

## M10.3 acceptance coverage

EndpointSummary is a single typed view model and implementation rendered in
the Classic endpoint table and Spatial topology detail frame.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M10.3-AC-001` | Classic and Spatial use one EndpointSummary implementation | shared component import in both surfaces | verified | None |
| `M10.3-AC-002` | Adapters expose canonical ref, revision and provenance | `endpointSummaryFromClassic/Spatial` | verified | None |
| `M10.3-AC-003` | Loading/empty/stale/offline/unavailable states are explicit | `EndpointSummaryState` and state copy map | verified | None |
| `M10.3-AC-004` | Endpoint Summary performs no fetch or mutation | component read-model boundary | verified | API remains parent-owned |
| `M10.3-AC-005` | Spatial profile remains ADR-013-compatible and DOM-accessible | spatial variant role/name contract | verified | Full visual regression remains M11 |
| `M10.3-AC-006` | Classic endpoint behavior keeps existing table actions | Classic table regression suite plus shared cell | verified | None |

## M10.4 acceptance coverage

EndpointConfiguration emits the same typed Change Intent semantics for form,
voice and Spatial sources; canonical application remains explicit.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M10.4-AC-001` | Change Intent contains target, revisions, current/proposed values and field schema | `spatialChangeIntentSchema` | verified | None |
| `M10.4-AC-002` | Form and voice produce the same deterministic diff | `spatial-m10.test.ts` | verified | None |
| `M10.4-AC-003` | Stale, occupied, unauthorized and offline states have alternatives | `ChangeIntentService.validate` tests | verified | Node revalidation is the final authority |
| `M10.4-AC-004` | Apply requires explicit confirmation and is idempotent | `ChangeIntentService.apply` tests | verified | None |
| `M10.4-AC-005` | Classic and Spatial render the shared configuration boundary | `EndpointConfiguration` imports in both surfaces | verified | Backend command adapter remains integration work |
| `M10.4-AC-006` | Result revision and provenance are visible after apply | component status and apply result model | verified | Durable audit storage remains Node-owned |

## M10.5 acceptance coverage

Query-driven composition maps supported operator questions to bounded,
registered components rather than arbitrary UI code.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M10.5-AC-001` | Endpoint list, inspect and compare intents map to registry IDs | `planSpatialQuery` map | verified | None |
| `M10.5-AC-002` | Resource, agent, session and hook intents are registered | M10 builtin component definitions | verified | None |
| `M10.5-AC-003` | Composition has reuse keys and bounded item budgets | query planner plan assertions | verified | None |
| `M10.5-AC-004` | Virtualized lists declare required budgets | registry `virtualization` metadata | verified | Browser performance lab remains M11 |
| `M10.5-AC-005` | Authoritative data stays outside the planner | planner accepts registry only and returns a plan | verified | Node query adapters remain external seams |
| `M10.5-AC-006` | Change Intent rollout has a safe server-authorized flag | `spatial_change_intent_enabled` flag row and helper | verified | Default remains disabled |

## M10.6 acceptance coverage

Resource language uses Compute Unit terminology and exact integer quantities.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M10.6-AC-001` | Canonical labels distinguish Resources, Usage, Cost and Settlement | `resource-terminology.ts` dictionary | verified | None |
| `M10.6-AC-002` | Forbidden fiat framing is rejected | `assertCanonicalResourceCopy` | verified | None |
| `M10.6-AC-003` | q_atoms remain exact integer strings | `qAtomsSchema` and parser test | verified | None |
| `M10.6-AC-004` | Formatting preserves integer evidence | `formatQAtoms` unit assertion | verified | None |
| `M10.6-AC-005` | Translation keys retain semantic distinction | canonical dictionary keys | verified | Locale catalog expansion remains later |
| `M10.6-AC-006` | Browser does not compute invoice authority | summary schema carries source/rate-card evidence only | verified | Node accounting remains authoritative |

## M10.7 acceptance coverage

Resource Summary and registered resource component contracts expose evidence,
state and exact quantities without inventing telemetry.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M10.7-AC-001` | Free, unknown, zero and metered states are distinct | `SPATIAL_RESOURCE_SUMMARY_STATES` | verified | None |
| `M10.7-AC-002` | Summary carries balance, usage, contribution and cost q_atoms | `spatialResourceSummarySchema` | verified | None |
| `M10.7-AC-003` | Rate-card revision and evidence refs are retained | resource summary parser | verified | None |
| `M10.7-AC-004` | Resource components are registered for Classic/Spatial reuse | `node-resource-summary` registry entry and inventory | verified | Full chart polish remains M11 |
| `M10.7-AC-005` | Large histories declare virtualization | Settlement/list registry metadata | verified | Durable pagination remains Node adapter work |
| `M10.7-AC-006` | Accessible text alternatives remain available | exact q_atoms text and shared component contract | verified | None |

## M10.8 acceptance coverage

Classic decomposition proceeds through shared contracts and removes inline
ownership only after the replacement has a tested seam.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M10.8-AC-001` | EndpointSummary is extracted before configuration migration | shared component and inventory priority | verified | None |
| `M10.8-AC-002` | EndpointConfiguration is shared by Classic and Spatial | component imports and render paths | verified | None |
| `M10.8-AC-003` | Inventory candidate IDs match registry IDs | inventory unit assertion | verified | None |
| `M10.8-AC-004` | Shared components expose stable typed view models | EndpointSummary adapters and contracts | verified | None |
| `M10.8-AC-005` | Existing Classic actions remain in their owner screen | Classic endpoint table action regression | verified | None |
| `M10.8-AC-006` | No generated dashboard files are edited manually | generated asset boundary and worktree audit | verified | None |

## M10.9 acceptance coverage

Action feedback reports user-visible effects and evidence without exposing
hidden reasoning.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M10.9-AC-001` | Proposed, approval, executing and completed states are typed | `SPATIAL_ACTION_FEEDBACK_STATES` | verified | None |
| `M10.9-AC-002` | Partial completion reports completed and remaining refs | `ActionFeedbackTransition` fields | verified | None |
| `M10.9-AC-003` | Rejected and rolled-back paths are explicit | transition state table and unit test | verified | None |
| `M10.9-AC-004` | Safe next action and evidence refs are visible | action feedback contract | verified | None |
| `M10.9-AC-005` | Attention is raised for abandonment/partial/finality states | `createActionFeedback` default policy | verified | Node notification adapter remains external |
| `M10.9-AC-006` | Invalid state transitions fail closed | transition unit assertion | verified | None |

## M11.1 acceptance coverage

Authorization and audit records stay on the Node-owned decision boundary;
presentation objects provide no authority.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M11.1-AC-001` | Presentation objects cannot grant capabilities | `spatial-m11.test.ts` authorization boundary | verified | None |
| `M11.1-AC-002` | Browser session, Primary Agent, MCP, Hooks, Workspace, remote, recovery, resource and Share View capabilities have one matrix | `SPATIAL_AUTHORIZATION_CAPABILITY_MATRIX` | verified | Node persistence adapter remains external |
| `M11.1-AC-003` | Every action records actor, target, revision, decision and result | `authorization.ts` and `SpatialAuditService.recordDecision` | verified | None |
| `M11.1-AC-004` | Scope, stale revision, missing capability and revocation decisions fail closed | authorization/revocation unit coverage | verified | None |
| `M11.1-AC-005` | Repeated idempotency keys do not repeat an action and failed actions retain evidence | audit dedupe/evidence coverage | verified | Durable retention store remains Node-owned |
| `M11.1-AC-006` | Secret/private payloads are rejected or redacted | `redactSensitiveKeys` and `assertNoSensitivePayload` | verified | None |

## M11.2 acceptance coverage

The primary operator path remains keyboard-first and readable when material
effects such as motion, blur or color are unavailable.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M11.2-AC-001` | Primary Workspace-to-Home flow has an explicit keyboard sequence | `SPATIAL_PRIMARY_KEYBOARD_FLOW` and unit test | verified | None |
| `M11.2-AC-002` | Entity controls require names, focus and keyboard operation | accessibility contract validator | verified | None |
| `M11.2-AC-003` | Focus order/return and live-region rates are bounded | accessibility issue checks | verified | Browser AT matrix remains a lab follow-up |
| `M11.2-AC-004` | State meaning survives color, forced-colors and reduced transparency | contract gate plus existing theme/a11y suites | verified | None |
| `M11.2-AC-005` | Reduced motion has a safe path | `reducedMotionSafe` gate and existing reduced-motion E2E | verified | None |
| `M11.2-AC-006` | Errors include instructions and touch targets meet 44px minimum | accessibility validator and `pnpm test:a11y` | verified | None |

## M11.3 acceptance coverage

Operator copy is catalogued in English and Russian while protocol terms and
integer Compute Unit semantics remain stable.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M11.3-AC-001` | EN/RU resource, state, action and error strings exist | `SPATIAL_CATALOG` | verified | None |
| `M11.3-AC-002` | Pluralization is locale-aware | `translateSpatialCount` unit coverage | verified | None |
| `M11.3-AC-003` | q_atoms remain integer strings with Q semantics | `formatSpatialQuantity` unit coverage | verified | None |
| `M11.3-AC-004` | Timestamps use an explicit locale and timezone | `formatSpatialTimestamp` contract | verified | None |
| `M11.3-AC-005` | Errors preserve a stable code beside human copy | `localizeSpatialError` unit coverage | verified | None |
| `M11.3-AC-006` | Protocol terms stay canonical and screen readers receive a locale tag | `assertProtocolTermNotMachineTranslated`; `spatialLocaleLanguageTag` | verified | None |

## M11.4 acceptance coverage

Performance reports make profile budgets and unsupported-device fallback
explicit rather than treating a single desktop number as an SLO.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M11.4-AC-001` | LOW, MOBILE, DESKTOP and HIGH budgets are documented in code | `SPATIAL_PERFORMANCE_BUDGETS` | verified | Device-lab calibration can tune thresholds |
| `M11.4-AC-002` | Initial JS/CSS/WebGL, TTI and first frame are measured | performance report contract and `pnpm bundle:report` | verified | None |
| `M11.4-AC-003` | FPS, frame p95, memory, idle CPU/GPU and event burst are checked | `evaluateSpatialPerformanceReport` | verified | None |
| `M11.4-AC-004` | 20k semantic objects, conversation DOM and mount cycles have budgets | performance report fields and fixture test | verified | None |
| `M11.4-AC-005` | Unsupported or failed profiles retain operator control via Classic | fallback evaluator and route boundary | verified | None |
| `M11.4-AC-006` | Performance evidence is a bounded, versioned record | `spatial.performance-report.v1` parser | verified | None |

## M11.5 acceptance coverage

Faults are represented as visible incidents with an explicit recovery action;
green status requires all safety invariants to pass.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M11.5-AC-001` | Disconnect, reorder and duplicate events have safe recovery actions | `RELIABILITY_RECOVERY_ACTIONS` | verified | Event adapter remains Node-owned |
| `M11.5-AC-002` | API/Agent/Hook/Workspace failures do not silently commit | reliability controller and audit boundary | verified | None |
| `M11.5-AC-003` | Corrupt presentation and renderer loss rebuild from canonical | incident action map and unit test | verified | None |
| `M11.5-AC-004` | Timeouts and malicious remote output avoid duplicate action/charge | safe action map and remote quarantine contract | verified | Settlement adapter remains external |
| `M11.5-AC-005` | Sleep/wake and Node switch invalidate stale local state | incident action map | verified | Browser/device matrix remains follow-up |
| `M11.5-AC-006` | Recovery is visible and Classic fallback is always available | `isSafeForGreen`/`requireClassicFallback` unit coverage | verified | None |

## M11.6 acceptance coverage

Workspace export and lifecycle APIs carry references, revisions and evidence;
they never turn a presentation object into evidence or export secrets.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M11.6-AC-001` | Workspace fields have PUBLIC/OPERATOR/PRIVATE/SECRET classification | privacy classification helper and schema | verified | None |
| `M11.6-AC-002` | Archive/Delete/Redact are explicit lifecycle transitions | `SpatialPrivacyLifecycleService` | verified | None |
| `M11.6-AC-003` | Export preserves canonical refs, revisions and evidence refs | export unit coverage | verified | Node export adapter remains external |
| `M11.6-AC-004` | Transcript and diagnostic redaction removes credential patterns | `redactSpatialTranscript` | verified | None |
| `M11.6-AC-005` | Presentation GC cannot erase referenced evidence | GC guard and unit coverage | verified | None |
| `M11.6-AC-006` | Remote disclosure is field-minimized and lifecycle-aware | privacy record contract | verified | Remote manifest remains ADR-012 boundary |

## M11.7 acceptance coverage

Telemetry is content-free, bounded and correlation-capable so an operator
scenario can be traced without prompts, tokens or private text.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M11.7-AC-001` | Renderer/fallback/frame/event/schema/view-model metrics are named | `SPATIAL_OBSERVABILITY_METRIC_NAMES` | verified | None |
| `M11.7-AC-002` | Duplicate, planner, attention, conflict and quarantine metrics exist | metric registry and bounded recorder | verified | None |
| `M11.7-AC-003` | Prompts, tokens, private text and secrets are rejected | `SpatialTelemetryViolation` unit coverage | verified | None |
| `M11.7-AC-004` | Dimensions and cardinality are bounded | telemetry max-cardinality unit coverage | verified | None |
| `M11.7-AC-005` | Correlation IDs are preserved without content | observability contract and test | verified | None |
| `M11.7-AC-006` | Records can be flushed as a bounded scenario trace | `BoundedSpatialTelemetry.flush` API | verified | Export sink remains deployment-specific |

## M11.8 acceptance coverage

Visual acceptance reuses ADR-013 tokens and DOM semantics across viewport,
contrast, motion, loading and failure states.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M11.8-AC-001` | Desktop/mobile and normal/high-contrast states remain readable | theme/a11y E2E suites and accessibility gate | verified | Device screenshot baseline remains follow-up |
| `M11.8-AC-002` | Reduced-motion and blur-fallback paths preserve hierarchy | `pnpm verify:theme`; reduced-motion tests | verified | None |
| `M11.8-AC-003` | READY/WORKING/CRITICAL/OFFLINE include non-color semantics | Primary Agent status contracts and E2E | verified | None |
| `M11.8-AC-004` | Loading/stale/error and endpoint cardinalities remain bounded | workspace/data state tests | verified | None |
| `M11.8-AC-005` | System Menu/recovery and Entity Details/Test Frame retain DOM controls | recovery, remote mediation and workspace suites | verified | None |
| `M11.8-AC-006` | No WebGL text or unreviewed material authority is introduced | DOM/3D boundary and theme static verifiers | verified | None |

## M11.9 acceptance coverage

Rollout is staged, reversible and presentation-only; disabling the flag always
returns the operator to Classic.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M11.9-AC-001` | Developer, fixture, test Node, LAN, opt-in and default stages are ordered | `SPATIAL_ROLLOUT_ORDER` | verified | None |
| `M11.9-AC-002` | Every stage checks error budget and compatibility | rollout gate evaluator | verified | None |
| `M11.9-AC-003` | Security, reliability, accessibility and performance sign-off gates default-on | rollout gate unit coverage | verified | None |
| `M11.9-AC-004` | Rollback is explicit and evidence-linked | `SpatialRolloutController.rollback` | verified | None |
| `M11.9-AC-005` | Schema migration is reversible or rebuildable | compatibility/migration gate fields | verified | Node migration implementation remains external |
| `M11.9-AC-006` | Generated assets are atomic and never the source of edits | build script boundary and worktree policy | verified | None |

## M11.10 acceptance coverage

Classic migration is a separate decision: parity, rollback, support and a
single canonical control path must be reviewed before removal.

| Acceptance ID | Criterion | Test or validation | Status | Deferred reason, if any |
| --- | --- | --- | --- | --- |
| `M11.10-AC-001` | Shared page/component candidates are inventoried | `component-inventory.ts` and M10 inventory test | verified | None |
| `M11.10-AC-002` | Direct controls and recovery paths have Spatial/Classic parity | route/recovery and shared component suites | verified | None |
| `M11.10-AC-003` | Accessibility parity is a release gate | M11 accessibility gate and `pnpm test:a11y` | verified | None |
| `M11.10-AC-004` | Legacy removal waits for rollback and support evidence | `M11-HARDENING-EVALUATION-ROLLOUT.md` decision record | verified | None |
| `M11.10-AC-005` | Generated assets are excluded from migration source review | generated dashboard boundary | verified | None |
| `M11.10-AC-006` | One canonical API/control path remains after replacement | ADR-011/014 and seam verifier | verified | None |

## Stable contract IDs

These IDs are reserved now and must be used as the `schema_version` value when
the corresponding boundary is introduced. A schema-breaking change increments
the final version; an implementation must not silently reuse an ID for a
different shape.

| Stable ID | Owner | First slice | Purpose |
| --- | --- | --- | --- |
| `spatial.workspace.v1` | Node Workspace | M2.5 | Node-owned semantic Workspace snapshot |
| `spatial.entity.v1` | Spatial entity model | M1.6/M2.2 | Discriminated canonical entity summary |
| `spatial.relation.v1` | Spatial entity model | M2.2 | Typed semantic relationship |
| `spatial.viewport.v1` | Client viewport | M1.7/M9.1 | Device-local camera, focus, and layout preferences |
| `spatial.primary-agent-slot.v1` | Primary Agent service | M3.1 | Node-scoped slot and current binding |
| `spatial.primary-agent-grant.v1` | Primary Agent service | M3.3 | Binding-owned capability grant and redaction policy |
| `spatial.primary-agent-state.v1` | Primary Agent service | M3.4 | Authoritative operational state projection |
| `spatial.intent-envelope.v1` | Intent Gateway | M4.1 | Typed text/voice/form/spatial operator intent |
| `spatial.attachment-manifest.v1` | Intent Gateway | M4.1 | Reference-only file/image/audio metadata |
| `spatial.conversation-turn.v1` | Conversation service | M4.3 | Durable operator/agent/system turn |
| `spatial.generated-object.v1` | Generated Object service | M4.8 | Source-linked generated output lifecycle |
| `spatial.workspace-session.v1` | Session service | M4.2 | User semantic session boundary |
| `spatial.context-node.v1` | Context graph | M4.3 | Structural parent and additional references |
| `spatial.artifact.v1` | Artifact service | M4.8 | Compact conversation/result artifact |
| `spatial.attention-item.v1` | Attention service | M5.8 | Bounded autonomous attention record |
| `spatial.node-status.v1` | Node status service | M6.1 | Authoritative status with freshness/evidence |
| `spatial.recovery-command.v1` | Node recovery command service | M6.6 | Plan-bound, capability-checked recovery action |
| `spatial.recovery-result.v1` | Node recovery command service | M6.6 | Audited idempotent recovery outcome |
| `spatial.endpoint-provenance.v1` | Endpoint mediation | M7.2 | Remote resource identity and provenance |
| `spatial.remote-context-manifest.v1` | Local mediation | M7.2 | Explicit minimized context crossing the trust boundary |
| `spatial.remote-request.v1` | Local mediation | M7.1 | Authorized, bounded remote request envelope |
| `spatial.remote-result.v1` | Remote result validator | M7.3 | Untrusted validated/quarantined result |
| `spatial.endpoint-test-frame.v1` | Endpoint Test Frame | M7.4 | Local manual test component state |
| `spatial.resource-accounting.v1` | Resource accounting | M7.5 | Request usage and Node settlement evidence |
| `spatial.memory-layout.v1` | Spatial memory layout engine | M8.1 | Deterministic semantic region anchors and policy revision |
| `spatial.memory-projection.v1` | Spatial memory projection | M8.1-M8.3 | Non-authoritative age, region, LOD, and provenance record |
| `spatial.memory-cluster.v1` | Session cluster promotion | M8.4 | Explainable criterion, membership, stale references, and summary |
| `spatial.memory-focus.v1` | Pull-to-Focus controller | M8.6 | Temporary focus lifecycle with world-position preservation |
| `spatial.memory-search.v1` | Search and recall | M8.8 | Reference-only result and relevance evidence |
| `spatial.memory-virtualization.v1` | Virtualization telemetry | M8.7 | Bounded render count, LOD counts, latency, and release signal |
| `spatial.workspace-world.v1` | Multi-device semantic world | M9.1 | Shared canonical refs, anchors, relations, clusters, pins, and revision |
| `spatial.device-viewport.v1` | Device viewport controller | M9.1/M9.4 | Camera, focus, selection, frames, quality, and gesture state local to a device |
| `spatial.presentation-geometry.v1` | Adaptive presentation geometry | M9.5 | Device-specific arrangement, safe-area, density, and keyboard insets |
| `spatial.workspace-mutation.v1` | Workspace sync envelope | M9.2 | Idempotent actor/device mutation with base revision and target refs |
| `spatial.workspace-mutation-result.v1` | Workspace sync resolver | M9.2 | Applied/conflict/rejected result with current evidence and audit ref |
| `spatial.offline-queue.v1` | Offline mutation queue | M9.3 | Pending replay, connectivity, conflict, and discard state |
| `spatial.share-view.v1` | Ephemeral Share View | M9.6 | Audience, expiry, focus authorization, and leave/decline state |
| `spatial.presentation-intent.v1` | Presentation Planner | M4.1 | Agent-requested registered presentation |
| `spatial.presentation-result.v1` | Presentation Planner | M4.1 | Accepted/rejected presentation outcome |
| `spatial.canonical-reference.v1` | Canonical reference registry | M5.1 | Workspace-scoped identity and projection reference |
| `spatial.endpoint-details.v1` | Endpoint topology | M5.2/M5.4 | Read-only capability details and evidence |
| `spatial.discovery-result.v1` | Endpoint discovery | M5.3 | Ranked temporary Endpoint candidates |
| `spatial.semantic-relation.v1` | Semantic relation service | M5.5 | Aggregated meaningful flow relation |
| `spatial.subagent-lifecycle.v1` | Local Subagent lifecycle | M5.6 | Delegated local actor state |
| `spatial.interaction-provenance.v1` | Provenance/familiarity service | M5.7 | Scoped interaction outcome and revision history |
| `spatial.change-intent.v1` | Intent gateway | M4.4/M10.4 | Typed operator change before canonical mutation |
| `spatial.attention-marker.v1` | Orbital marker projection | M5.9 | Bounded presentation marker |
| `spatial.attention-focus.v1` | Attention focus controller | M5.10 | Temporary focus and viewport return state |
| `spatial.resource-summary.v1` | Resource accounting | M10.7 | Compute Unit contribution, usage, and settlement summary |
| `spatial.result-model.v1` | Result Model boundary | M10.3 | Shared query result with source revision and provenance |
| `spatial.component-frame.v1` | Component Registry | M10.2/M10.5 | Bounded component binding, variant, state and object reference |
| `spatial.action-feedback.v1` | Action feedback | M10.9 | User-visible effect, evidence, partial completion and safe next action |
| `spatial.authorization-decision.v1` | Authorization boundary | M11.1 | Capability, scope, revision and decision evidence |
| `spatial.audit-record.v1` | Audit boundary | M11.1 | Actor-attributed idempotent action result and evidence refs |
| `spatial.reliability-incident.v1` | Reliability controller | M11.5 | Fault, visible recovery state and safety invariants |
| `spatial.privacy-record.v1` | Privacy lifecycle | M11.6 | Classification, lifecycle, disclosure and retention refs |
| `spatial.performance-report.v1` | Performance evaluator | M11.4 | Profile budget measurements and fallback result |
| `spatial.observability-metric.v1` | Bounded telemetry | M11.7 | Content-free metric, bucket and correlation reference |
| `spatial.rollout-stage.v1` | Rollout controller | M11.9 | Reversible stage, compatibility and error-budget gate |

## Stable event type IDs

These event names are reserved for the existing canonical Event Bus. They do
not authorize a second browser-owned event plane. Payloads use a registered
contract ID and include stable event, correlation, causation, actor, Node, and
timestamp fields before they are emitted.

| Event type ID | Payload contract | First slice |
| --- | --- | --- |
| `spatial.workspace.updated.v1` | `spatial.workspace.v1` | M2.6 |
| `spatial.entity.upserted.v1` | `spatial.entity.v1` | M2.6 |
| `spatial.entity.archived.v1` | `spatial.entity.v1` | M8.7 |
| `spatial.relation.upserted.v1` | `spatial.relation.v1` | M2.6 |
| `spatial.primary-agent.binding-changed.v1` | `spatial.primary-agent-slot.v1` | M3.2 |
| `spatial.primary-agent.grant-changed.v1` | `spatial.primary-agent-grant.v1` | M3.3 |
| `spatial.primary-agent.state-changed.v1` | `spatial.primary-agent-state.v1` | M3.4 |
| `spatial.intent.accepted.v1` | `spatial.intent-envelope.v1` | M4.1 |
| `spatial.session.updated.v1` | `spatial.workspace-session.v1` | M4.2 |
| `spatial.context.updated.v1` | `spatial.context-node.v1` | M4.7 |
| `spatial.conversation.turn-updated.v1` | `spatial.conversation-turn.v1` | M4.3 |
| `spatial.generated-object.updated.v1` | `spatial.generated-object.v1` | M4.8 |
| `spatial.artifact.created.v1` | `spatial.artifact.v1` | M4.8 |
| `spatial.attention.raised.v1` | `spatial.attention-item.v1` | M5.8 |
| `spatial.attention.resolved.v1` | `spatial.attention-item.v1` | M5.9 |
| `spatial.node-status.changed.v1` | `spatial.node-status.v1` | M6.2 |
| `spatial.recovery.command-planned.v1` | `spatial.recovery-command.v1` | M6.6 |
| `spatial.recovery.resulted.v1` | `spatial.recovery-result.v1` | M6.6 |
| `spatial.endpoint-provenance.updated.v1` | `spatial.endpoint-provenance.v1` | M7.2 |
| `spatial.remote.context-manifest.updated.v1` | `spatial.remote-context-manifest.v1` | M7.2 |
| `spatial.remote.requested.v1` | `spatial.remote-request.v1` | M7.1 |
| `spatial.remote.resulted.v1` | `spatial.remote-result.v1` | M7.3 |
| `spatial.endpoint-test-frame.updated.v1` | `spatial.endpoint-test-frame.v1` | M7.4 |
| `spatial.resource-accounting.updated.v1` | `spatial.resource-accounting.v1` | M7.5 |
| `spatial.presentation.requested.v1` | `spatial.presentation-intent.v1` | M4.1 |
| `spatial.presentation.resolved.v1` | `spatial.presentation-result.v1` | M4.1 |
| `spatial.canonical-reference.upserted.v1` | `spatial.canonical-reference.v1` | M5.1 |
| `spatial.endpoint-details.updated.v1` | `spatial.endpoint-details.v1` | M5.2/M5.4 |
| `spatial.discovery.updated.v1` | `spatial.discovery-result.v1` | M5.3 |
| `spatial.semantic-relation.updated.v1` | `spatial.semantic-relation.v1` | M5.5 |
| `spatial.subagent.lifecycle-updated.v1` | `spatial.subagent-lifecycle.v1` | M5.6 |
| `spatial.interaction.provenance-recorded.v1` | `spatial.interaction-provenance.v1` | M5.7 |
| `spatial.attention.item-updated.v1` | `spatial.attention-item.v1` | M5.8 |
| `spatial.attention.marker-updated.v1` | `spatial.attention-marker.v1` | M5.9 |
| `spatial.attention.focus-updated.v1` | `spatial.attention-focus.v1` | M5.10 |
| `spatial.memory.layout-updated.v1` | `spatial.memory-layout.v1` | M8.1 |
| `spatial.memory.projection-updated.v1` | `spatial.memory-projection.v1` | M8.1-M8.3 |
| `spatial.memory.cluster-updated.v1` | `spatial.memory-cluster.v1` | M8.4 |
| `spatial.memory.focus-updated.v1` | `spatial.memory-focus.v1` | M8.6 |
| `spatial.memory.search-completed.v1` | `spatial.memory-search.v1` | M8.8 |
| `spatial.memory.virtualization-updated.v1` | `spatial.memory-virtualization.v1` | M8.7 |
| `spatial.workspace-world.updated.v1` | `spatial.workspace-world.v1` | M9.1 |
| `spatial.device-viewport.updated.v1` | `spatial.device-viewport.v1` | M9.1/M9.4 |
| `spatial.presentation-geometry.updated.v1` | `spatial.presentation-geometry.v1` | M9.5 |
| `spatial.workspace-mutation.requested.v1` | `spatial.workspace-mutation.v1` | M9.2 |
| `spatial.workspace-mutation.resolved.v1` | `spatial.workspace-mutation-result.v1` | M9.2 |
| `spatial.offline-queue.updated.v1` | `spatial.offline-queue.v1` | M9.3 |
| `spatial.share-view.updated.v1` | `spatial.share-view.v1` | M9.6 |
| `spatial.change-intent.created.v1` | `spatial.change-intent.v1` | M10.4 |
| `spatial.change-intent.resolved.v1` | `spatial.change-intent.v1` | M4.5/M10.4 |
| `spatial.result-model.updated.v1` | `spatial.result-model.v1` | M10.3 |
| `spatial.component-frame.updated.v1` | `spatial.component-frame.v1` | M10.5 |
| `spatial.resource-summary.updated.v1` | `spatial.resource-summary.v1` | M10.7 |
| `spatial.action-feedback.updated.v1` | `spatial.action-feedback.v1` | M10.9 |

## Feature flags

All flags are server-authorized capabilities. Client-side evaluation may hide
or lazy-load a surface but never bypasses operator authorization.

| Flag ID | Default before gate | Owner | Introduced | Rollback behavior |
| --- | --- | --- | --- | --- |
| `spatial_ui_enabled` | `false` | dashboard route boundary | M0.3 | Return to the unchanged Classic default route |
| `spatial_workspace_persistence_enabled` | `false` | Node Workspace service | M2.5 | Keep stored data; expose read-only/Classic recovery paths |
| `spatial_primary_agent_live_enabled` | `false` | Primary Agent service | M3.1 | Render offline/unbound Presence; keep System Menu available |
| `spatial_interaction_enabled` | `false` | Intent/Conversation surface | M4.1 | Hide Interaction Seed and Conversation Surface; retain read-only Spatial shell |
| `spatial_topology_enabled` | `false` | Endpoint topology and attention surface | M5.1 | Hide M5 discovery/details/attention DOM; retain canonical read-only shell |
| `spatial_status_enabled` | `false` | Node Status, System Menu, and recovery surface | M6.1 | Hide the M6 System Menu enhancement; retain Classic and renderer fallback access |
| `spatial_remote_mediation_enabled` | `false` | remote mediation service | M7.1 | Disable remote submission; retain local inspection/provenance |
| `spatial_memory_enabled` | `false` | Spatial memory projection and virtualization | M8.1 | Hide aging/cluster/search surface; retain canonical Workspace and Classic fallback |
| `spatial_multi_device_sync_enabled` | `false` | Workspace sync service | M9.1 | Preserve semantic Workspace; use device-local viewport only |
| `spatial_change_intent_enabled` | `false` | intent gateway | M10.5 | Fall back to existing canonical Classic commands |
| `spatial_operator_preview_enabled` | `false` | M11 rollout controller | M11.9 | Disable Spatial preview and return to Classic without changing Node data |

## Canonical terminology

| Term | Canonical meaning | Avoid |
| --- | --- | --- |
| Node | The authoritative AiDN runtime and owner of a Spatial Workspace | Treating the browser or Agent as state owner |
| Primary Agent Slot | The one Node-scoped logical role shown by the central Presence | A global user Agent or a specific model name |
| Primary Agent Binding | The current Agent Identity/runtime attached to the slot | Treating rebinding as Workspace replacement |
| Spatial Workspace | Node-owned semantic objects, relations, sessions, attention, and history | A saved camera or an infinite dashboard |
| Workspace Session | A user semantic context and its branch graph | AiDN protocol session |
| Protocol session | A bounded protocol/resource interaction used by one Workspace Session | User conversation history |
| Entity | A canonical Agent, Endpoint, Service, Session, Artifact, or other typed object | A visual clone |
| Presentation instance | A non-authoritative rendering or explicit projection of an Entity | A new semantic identity |
| Endpoint | An untrusted, mediated capability projection | A trusted Agent or direct user conversation partner |
| Subagent | A local Agent Actor delegated by the Primary Agent | Endpoint, Service, or UI component |
| Attention Item | A bounded Node-owned record needing operator awareness | A camera command or modal notification |
| Presentation Intent | A typed request to compose registered components | Generated JSX/CSS or mutation authority |
| Change Intent | A typed operator request evaluated by the canonical command boundary | Direct browser mutation of Node state |
| Compute Unit | Resource contribution, usage, or settlement quantity | Bank balance, yield, income, or investment framing |
| Classic UI | Existing dark operator dashboard and direct-control/recovery surface | Deprecated fallback before an explicit migration ADR |
| Spatial UI | New flag-gated, agent-centered hybrid WebGL/DOM surface | A reskin of Classic UI |

## Classic and Spatial boundary

- Classic UI remains the default direct-control and recovery surface until a
  separate migration decision is accepted.
- Spatial UI is introduced behind `spatial_ui_enabled` and must preserve a
  route back to Classic UI when the Agent or renderer is unavailable.
- The current dark Classic visual system is not converted to Milky Glass by
  this roadmap. ADR-013 applies to the new Spatial layer.
- Both surfaces use the same Node APIs, authorization, validation,
  idempotency, audit, and eventually the same Component Registry. Spatial UI
  does not create a parallel source of truth or control plane.
- Generated files under `src/aidn_hypervisor/static/react-dashboard/` are
  build output and are changed only by `tools/build-operator-dashboard.sh`.

## Unresolved implementation choices

The product decisions above are accepted. The following engineering choices
remain experiments or later-slice decisions and are not silently settled by
this registry:

- exact R3F entity geometry and material tuning within ADR-013/014 budgets;
- WebSocket reconnect/backfill protocol over the canonical Event Store;
- Workspace persistence store and migration mechanics;
- clustering weights and aging thresholds;
- future budget tightening after the M0.5 baseline;
- whether visual-regression hosting uses CI artifacts or an external service.

## Change control

Every new or superseding Spatial ADR must update this file and the development
roadmap in the same change. Reviewers must verify:

- a stable ADR/invariant identifier and owner module are present;
- planned slices and dependencies are explicit;
- every new acceptance criterion names an automated validation or a deferred
  reason;
- new cross-layer contracts and canonical event types have stable versioned
  IDs;
- feature flags define safe default and rollback behavior;
- terminology changes update this glossary and conflicting usages;
- local documentation links pass `python tools/verify-docs-links.py`.
