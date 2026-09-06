# AiDN Operator Dashboard

React/Vite reference implementation for the UI-0001 Hypervisor dashboard.

```bash
pnpm install --frozen-lockfile
pnpm dev
```

Set `AIDN_HYPERVISOR_URL` before `pnpm dev` to proxy the dashboard API to a LAN
node. Production assets are built with `pnpm build` and served by FastAPI at
`/operators/dashboard/react`.

The Spatial renderer dependencies are route-level lazy loaded. Run
`pnpm bundle:report` after a build to emit the gzip/Brotli budget report under
`test-results/`; `pnpm bundle:repro` repeats the build and compares the
deterministic report. `pnpm test:bundle` serves the production build and checks
that Classic does not request the Spatial chunk and that a second Spatial
transition reuses the first request. See
[the M0.5 dependency and bundle record](../../docs/spatial/M0.5-DEPENDENCIES-AND-BUNDLE.md)
for the locked versions, licenses, and baseline ceilings.

The Spatial route boundary is disabled by default. Set the build-time
`VITE_SPATIAL_UI_ENABLED=true` flag (or provide the equivalent server-rendered
`window.__AIDN_FEATURE_FLAGS__` rollout hint) to exercise
`/operators/dashboard/react/#spatial`. The flag controls presentation only;
Node authorization and API permissions remain authoritative.

The M1.1 Spatial theme fixture is available after entering `#spatial`. It
exercises the versioned `spatial.tokens.v1` package, WCAG contrast specimens,
high-contrast/reduced-transparency profiles, and the opaque backdrop fallback.
Use `pnpm verify:theme` for the scoped-token review rule and `pnpm test:theme`
for the Chromium profile flow; `pnpm test:a11y` also audits the actual gallery.
See [the M1.1 token record](../../docs/spatial/M1.1-MILKY-GLASS-TOKENS.md) for
the token groups and acceptance evidence.

The M1.2 DOM primitives gallery is mounted beneath the token specimens. It
exercises the reusable `Surface`, `GlassFrame`, `Button`, `IconButton`, field,
toggle, slider, tooltip, status, focus-ring, and raised-control contracts with
a keyboard-only path. Run `pnpm verify:theme`, `pnpm test:theme`, and
`pnpm test:a11y` to validate the scoped primitive styles and accessibility
behavior. See [the M1.2 DOM primitives record](../../docs/spatial/M1.2-DOM-PRIMITIVES.md)
for the public API and acceptance evidence.

The M1.3 hybrid renderer shell adds a fixed `SpatialCanvas` beneath a
pointer-transparent `SpatialDomOverlay`. `SpatialWorkspace` owns mock selection,
ResizeObserver/orientation metrics, bounded DPR, and a DOM error fallback; the
canvas stays out of the keyboard focus path. See [the M1.3 hybrid shell record](../../docs/spatial/M1.3-HYBRID-RENDERER-SHELL.md)
for the layer contract and recovery evidence.

Prototype A (M1.4–M1.8) now extends that boundary with a bounded white studio
environment, low/mobile/desktop/high quality profiles, a deterministic
Primary Agent material/state fixture, 3/7/6/3 mock entity classes with two
semantic threads, local camera navigation, and a visible performance/UX gate.
The DOM panel exposes the accessible Primary Agent label, keyboard entity list,
HOME/focus/back controls, and quality selector; none of these fixtures call the
Dashboard API or imply canonical authority. Run `pnpm verify:prototype` and
`pnpm test:prototype` for the static and Chromium paths. See the [M1.4
environment](../../docs/spatial/M1.4-WHITE-ATMOSPHERIC-ENVIRONMENT.md), [M1.5
material](../../docs/spatial/M1.5-PRIMARY-AGENT-MATERIAL.md), [M1.6 entity
grammar](../../docs/spatial/M1.6-MOCK-ENTITIES-PICKING.md), [M1.7 camera
prototype](../../docs/spatial/M1.7-CAMERA-NAVIGATION.md), and [M1.8
gate](../../docs/spatial/M1.8-PROTOTYPE-A-GATE.md) records.

M2.1–M2.7 connect that shell to a typed Node data path. Scoped domain clients,
query keys, retained event replay, deterministic view models, Node-owned
semantic Workspace persistence, device-local presentation state, and
mock-real runtime fixtures live under `src/spatial/data/` and
`src/spatial/workspace/`. The route demonstrates an Endpoint recovery stream
while keeping the renderer projection-only. Run `pnpm test` and
`pnpm typecheck`; see the [M2 runtime records](../../docs/spatial/M2.7-RUNTIME-DATA-INTEGRATION.md)
and linked M2.2–M2.6 slice documents.

M3.1 adds the Node-owned Primary Agent Slot contract and deterministic
`InMemoryPrimaryAgentSlotRepository`. The slot is kept separate from Agent
Identity, runtime binding, grants, hooks, and durable inbox references, with
explicit lifecycle, revision, idempotency, audit, concurrency, and restart
guards. See [the M3.1 record](../../docs/spatial/M3.1-PRIMARY-AGENT-SLOT.md)
and run `pnpm vitest run tests/unit/spatial-primary-agent-slot.test.ts`.

M3.2–M3.6 complete the live Primary Agent lifecycle. The typed binding API
supports inspect/plan/apply/replace/suspend/detach/revoke/recover with
authorization, revision conflicts, idempotency, audit, and secret-free
binding-changed events. Binding-owned grants and Hooks provide filtered,
redacted durable inbox delivery with cursor resume, idempotent acknowledgement,
retry, dead-letter, and replay. The operational state aggregator and Presence
view model keep `CRITICAL` attention independent from activity, preserve
`OFFLINE`, and select quality/reduced-motion material fallbacks. The DOM-only
management surface exposes safe slot fields and explicit revoke confirmation in
the Spatial frame or a Classic fallback composition. See the [M3 lifecycle
record](../../docs/spatial/M3.X-PRIMARY-AGENT-LIFECYCLE.md) and run:

```bash
pnpm vitest run tests/unit/spatial-primary-agent-binding.test.ts tests/unit/spatial-primary-agent-delivery.test.ts tests/unit/spatial-primary-agent-state.test.ts tests/unit/spatial-primary-agent-presence.test.ts tests/unit/spatial-primary-agent-management.test.tsx
```

M4.1–M4.10 add the typed Intent Gateway, Interaction Seed, durable in-memory
conversation/session graph, declarative Component Registry and Presentation
Planner, DOM-only Conversation Surface, Generated Object lifecycle, Session
Artifact collapse/restore, and explicit voice adapter. The shared contracts
and event parser remain Node-scoped; Node persistence, Event Store delivery,
and full Classic parity are follow-up seams. See the [M4 interaction record](../../docs/spatial/M4.X-INTERACTION-AND-PRESENTATION.md)
and run `pnpm vitest run tests/unit/spatial-interaction.test.ts`.

M5.1–M5.10 add the workspace-scoped canonical reference registry, distinct
Endpoint Energy/Discovery/Details, semantic relation aggregation, local
Subagent lifecycle, scoped interaction provenance/familiarity, bounded
Attention queue, reduced-motion orbital marker projection, and temporary
Focus Mode/actions. The DOM surface is behind `spatial_topology_enabled=false`;
Node Event Store replay remains the production adapter seam. See the [M5
topology record](../../docs/spatial/M5.X-TOPOLOGY-PROVENANCE-ATTENTION.md) and
run `pnpm vitest run tests/unit/spatial-topology.test.ts`.

M6.1–M6.7 add the Node-owned Status Aggregator, permanent System Menu,
revision/freshness-aware Summary and Details, canonical SHOW_IN_WORKSPACE
bridge, and plan-bound recovery commands. The menu remains DOM-accessible when
the Agent or renderer is unavailable; probe/command handlers remain explicit
Node adapters. See the [M6 status/recovery record](../../docs/spatial/M6.X-STATUS-RECOVERY.md)
and run `pnpm vitest run tests/unit/spatial-status.test.ts tests/unit/spatial-system-menu.test.tsx`.

M7.1–M7.7 add the local remote mediation boundary, minimized context
manifest, untrusted result validator, provenance/accounting contracts, and
the explicit-submit Endpoint Test Frame. The opt-in
`spatial_remote_mediation_enabled` surface delegates only through an injected
Node transport adapter; the browser cannot select an arbitrary URL or render
remote markup. See the [M7 mediation record](../../docs/spatial/M7.X-REMOTE-MEDIATION.md)
and run `pnpm vitest run tests/unit/spatial-remote-mediation.test.tsx`.

M8.1–M8.8 add the opt-in `spatial_memory_enabled` DOM memory surface and its
typed projection engine: deterministic preferred regions, bounded Recent
Memory, UTC aging/hysteresis, explainable clusters, relation reveal,
Pull-to-Focus, LOD/culling telemetry and authorization-filtered metadata
search. Semantic references, world positions and provenance remain
presentation-only; durable policy/persistence/search adapters remain Node-owned.
See the [M8 memory record](../../docs/spatial/M8.X-SPATIAL-MEMORY.md) and run
`pnpm vitest run tests/unit/spatial-memory.test.ts`.

M9.1–M9.7 add the opt-in `spatial_multi_device_sync_enabled` boundary:
shared semantic world revisions, independent desktop/tablet/mobile viewports,
idempotent mutation/conflict evidence, offline replay, mobile gestures,
adaptive geometry and expiring Share View. Node remains the authority for
durable sync and authorization. See the [M9 multi-device record](../../docs/spatial/M9.X-MULTI-DEVICE.md)
and run `pnpm vitest run tests/unit/spatial-multidevice.test.ts`.

M10.1–M10.9 add the shared Component Registry v2 and agent-mediated component
seams: Classic inventory, EndpointSummary, EndpointConfiguration, typed Change
Intent validation/idempotency, bounded query composition, exact q_atoms/resource
terminology and action feedback. `spatial_change_intent_enabled` is off by
default; Node remains authoritative for command translation, revalidation,
audit and resource events. See the [M10 record](../../docs/spatial/M10-AGENT-MEDIATED-COMPONENTS.md)
and run `pnpm vitest run tests/unit/spatial-m10.test.ts`.

M11 adds the hardening boundary for a controlled operator preview. The additive
contracts and pure services under `src/spatial/hardening/` cover authorization
and audit attribution, reliability/chaos recovery, keyboard and AT semantics,
EN/RU copy, device performance budgets, privacy lifecycle/export, bounded
content-free observability, and reversible rollout stages. The
`spatial_operator_preview_enabled` hint is presentation-only; an explicit false
returns to Classic without touching Node data. Run:

```bash
pnpm vitest run tests/unit/spatial-m11.test.ts
pnpm typecheck
```

See the [M11 hardening and rollout record](../../docs/spatial/M11-HARDENING-EVALUATION-ROLLOUT.md)
and the [implementation coverage registry](../../docs/spatial/IMPLEMENTATION-COVERAGE.md)
for release gates and migration-decision evidence.

The dashboard composition root is `src/App.tsx`. Shared shell seams live under
`src/app/`: `dashboard-routing.ts` owns Classic hash synchronization,
`operator-providers.tsx` owns React Query and tooltip providers, and the
notification, navigation, TopBar, Hypervisor selector, and screen registry
modules keep new feature components out of the composition root. The existing
Classic screens remain in `src/app/classic-dashboard.tsx` during the migration
train; API and domain-schema splits follow in the remaining M0.4 work.

See [React Dashboard Migration](../../docs/development/reference/react-dashboard-migration.md)
for architecture, release packaging, and the staged migration plan.
