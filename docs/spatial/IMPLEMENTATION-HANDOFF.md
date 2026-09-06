# AiDN Spatial Agent Interface — Implementation Handoff

**Статус:** M1 Prototype A, M2.1–M2.7 typed Node data path, M3.1–M3.6 Primary Agent lifecycle, M4.1–M4.10 interaction/presentation, M5.1–M5.10 topology/provenance/attention, M6.1–M6.7 status/recovery, M7.1–M7.7 mediated remote resources/Endpoint Test Frame, M8.1–M8.8 spatial memory/aging/clustering/virtualization, M9.1–M9.7 multi-device/mobile navigation, M10.1–M10.9 agent-mediated components/resource semantics и M11.1–M11.10 hardening/evaluation/rollout implemented; operator-preview gate remains Node/test-Node sign-off  
**Дата:** 2026-09-06  
**Назначение:** краткая точка входа для нового чата или нового исполнителя.  

Этот документ не заменяет полный план. Он фиксирует, что уже принято, где
искать источник истины, с какого небольшого слайса начать и какие границы
реализация не должна нарушить.

M1.1–M1.8, M2.1–M2.7, M3.1–M3.6 и M4.1–M4.10 реализованы в `web/operator-dashboard/src/spatial/` и
покрыты unit/Chromium/accessibility/static checks. M2 добавляет versioned Zod
contracts, scoped domain clients/query keys, retained event gateway,
deterministic view models, Node-owned semantic Workspace, device-local
presentation persistence и mock-real runtime path. Spatial renderer получает
только view-model projections; Node remains authoritative. M3.1 добавляет
Node-owned Primary Agent Slot с отдельными binding/grant/inbox references,
revision/idempotency/audit и безопасным restart seam. M3.2–M3.6 добавляют
authorized binding API, binding-owned grants/Hooks/inbox, authoritative
operational state, live Presence и DOM-only management surface. Production
backend storage/event transport подключаются через уже определённые adapters.
M4.1–M4.10 добавляют typed Intent Gateway, Interaction Seed, durable in-memory
conversation/session graph, Component Registry, Presentation Planner,
Conversation Surface, Generated Objects, Session Artifact collapse/restore и
explicit voice adapter. M5.1–M5.10 добавляют workspace-scoped canonical
reference registry, distinct Endpoint Energy/Discovery/Details, semantic
relations, local Subagent lifecycle, scoped interaction provenance/familiarity,
bounded Attention queue, stable orbital marker projection и temporary Focus
Mode/actions. M6.1–M6.7 добавляют Node-owned Status Aggregator, permanent
System Menu, factual Summary/Details, canonical SHOW_IN_WORKSPACE bridge и
plan-bound recovery commands; offline/renderer fallback остаётся DOM-доступным.
Node persistence, canonical Event Store replay, production probe/command
handlers and full Classic parity remain explicit adapter seams. M7.1–M7.7
добавляют local mediation, context manifest minimization, untrusted result
validation, Endpoint Test Frame, accounting/provenance и negative security
suite. Production transport, durable audit/replay and settlement remain
Node-owned adapters behind the typed `remoteMediation` client. M8.1–M8.8
добавляют deterministic preferred regions, bounded Recent Memory, UTC aging
with hysteresis, explainable Session Clusters, on-demand relation reveal,
Pull-to-Focus, LOD0–LOD3 virtualization, bounded render telemetry and
reference-only metadata search. Production persistence and semantic search
remain Node adapters behind the typed memory contracts; the browser never
becomes Workspace authority. M9.1–M9.7 add the shared semantic world/device
viewport split, idempotent revision-aware mutation envelope, offline queue,
mobile gesture controller, adaptive geometry and explicit expiring Share View.
The flag-gated demo shows desktop and mobile viewports over one world; durable
Node sync, authorization and audit remain typed adapter seams.
M10.1–M10.9 add the typed Classic inventory, Component Registry v2 lifecycle
metadata, shared EndpointSummary and EndpointConfiguration, Change Intent
validation/idempotency, bounded query composition, exact q_atoms/resource
terminology and action feedback states. `spatial_change_intent_enabled` stays
off by default; canonical command/MCP translation, Hypervisor revalidation,
durable audit and resource events remain Node-owned adapters. See the [M10
record](./M10-AGENT-MEDIATED-COMPONENTS.md).

M11.1–M11.10 add the additive hardening registry and pure browser-side gates:
Node/Primary-Agent capability decisions with actor-attributed audit, visible
reliability recovery, keyboard/AT and EN/RU localization contracts, profile
performance budgets, privacy lifecycle/export, content-free bounded telemetry,
reversible rollout stages and the separate Classic migration decision. See the
[M11 hardening record](./M11-HARDENING-EVALUATION-ROLLOUT.md). The browser
cannot mint authority, settle resources, or erase evidence; real test-Node
rollback and Node persistence remain the final release gate.

## 1. Как начать работу в новом чате

Скопировать в новый чат:

~~~text
Продолжай реализацию AiDN Spatial Agent Interface.
Сначала прочитай docs/spatial/IMPLEMENTATION-HANDOFF.md и раздел M11
в docs/spatial/DEVELOPMENT-ROADMAP.md. Проверь git status: worktree
может содержать чужие незакоммиченные изменения, их нельзя откатывать
или удалять. M1, M2.1–M2.7, M3.1–M3.6, M4.1–M4.10, M5.1–M5.10, M6.1–M6.7
и M7.1–M7.7, M8.1–M8.8, M9.1–M9.7, M10.1–M10.9 и M11.1–M11.10 уже
закрыты; следующий трен — подключение hardening contracts к Node/test-Node
adapters без изменения generated assets.
~~~

Перед любым изменением:

1. открыть этот handoff;
2. открыть соответствующий milestone в полном roadmap;
3. прочитать связанные ADR;
4. проверить текущий git status;
5. ограничить PR одним vertical slice и его acceptance criteria.

## 2. Репозиторий и важные пути

Рабочая копия:

~~~text
AiDN_ci_fix/
~~~

Исходники действующего Dashboard:

~~~text
web/operator-dashboard/
~~~

Generated production assets:

~~~text
src/aidn_hypervisor/static/react-dashboard/
~~~

Последний каталог является build output. Его нельзя редактировать вручную.
Для сборки и атомарной активации используется:

~~~text
tools/build-operator-dashboard.sh
~~~

Ключевые текущие frontend-файлы:

~~~text
web/operator-dashboard/src/App.tsx
web/operator-dashboard/src/lib/api.ts
web/operator-dashboard/src/lib/types.ts
web/operator-dashboard/src/hooks/use-dashboard.ts
~~~

На момент подготовки handoff App.tsx содержит примерно 4 135 строк и должен
превратиться в composition root, а не в место для новых feature-компонентов.

## 3. Канонические документы

Читать в таком порядке:

1. [Detailed Development Roadmap](./DEVELOPMENT-ROADMAP.md) — порядок,
   слайсы, зависимости, тесты и acceptance gates.
2. [Основной implementation plan](./AiDN-Spatial-Agent-Interface-Implementation-Plan.md) —
   продуктовая цель и общая пространственная модель.
3. [Реестр исходных вопросов](./OPEN-QUESTIONS.md) — происхождение решений.
4. ADR-001…ADR-014 — нормативные решения. При конфликте roadmap и ADR
   приоритет имеет ADR.

Ключевые ADR:

- [ADR-001](./ADR-001-primary-agent-scope.md) — Primary Agent является
  Node-scoped logical slot, а не конкретной LLM.
- [ADR-002](./ADR-002-node-workspace-ownership.md) — Workspace принадлежит
  Node; смена агента не удаляет историю.
- [ADR-003](./ADR-003-orbital-attention-system.md) и
  [ADR-004](./ADR-004-primary-agent-visual-state-language.md) — attention и
  visual state language.
- [ADR-005](./ADR-005-spatial-entity-topology.md),
  [ADR-006](./ADR-006-workspace-sessions-context-graph.md),
  [ADR-007](./ADR-007-spatial-memory-aging-clustering.md),
  [ADR-008](./ADR-008-entity-uniqueness-and-provenance.md) — сущности,
  сессии, память и provenance.
- [ADR-009](./ADR-009-multi-device-workspace-and-mobile-navigation.md) и
  [ADR-010](./ADR-010-node-status-and-recovery-access.md) — multi-device,
  Status и recovery.
- [ADR-011](./ADR-011-agent-mediated-component-interface.md) и
  [ADR-012](./ADR-012-local-trust-boundary-and-mediated-remote-resources.md) —
  agent-mediated UI и remote trust boundary.
- [ADR-013](./ADR-013-aidn-milky-glass-neumorphism-visual-design.md) и
  [ADR-014](./ADR-014-spatial-ui-technical-architecture.md) — visual system
  и техническая архитектура.
- [M3.1 — Primary Agent Slot](./M3.1-PRIMARY-AGENT-SLOT.md) — текущий
  реализованный domain seam и его acceptance evidence.
- [M3.2–M3.6 — Primary Agent lifecycle](./M3.X-PRIMARY-AGENT-LIFECYCLE.md) —
  binding, grants/Hooks/inbox, operational state, live Presence и management
  surface acceptance evidence.
- [M7 — Mediated Remote Resources and Endpoint Test Frame](./M7.X-REMOTE-MEDIATION.md) —
  local mediation, minimized context, untrusted output, provenance/accounting
  and negative security evidence.
- [M8 — Spatial Memory, Aging and Clustering](./M8.X-SPATIAL-MEMORY.md) —
  deterministic regions, aging, clusters, focus, virtualization and search
  evidence.
- [M9.x — Multi-device Workspace and Mobile Navigation](./M9.X-MULTI-DEVICE.md) —
  shared semantic world, local viewports, mutation sync, offline replay,
  mobile gestures, adaptive geometry and Share View evidence.
- [M10 — Agent-mediated Components and Resource Semantics](./M10-AGENT-MEDIATED-COMPONENTS.md) —
  inventory, Registry v2, shared Endpoint components, Change Intent, query
  composition, Q/resource terminology and action feedback evidence.

## 4. Уже принятые архитектурные решения

### 4.1. Продуктовая модель

- Основной интерфейс Spatial UI — Primary Agent Presence в центре
  Node Workspace.
- UI является пространством, а не заменой одних страниц другими:
  агент, endpoint, artifact, session и attention имеют разные semantic
  representations.
- Classic Admin UI остаётся fallback и direct-control surface до отдельного
  migration decision.
- System Menu и factual Status не зависят от доступности Primary Agent.
- Node владеет Workspace, sessions, artifacts, relationships, attention и
  operator-facing history.

### 4.2. Trust and control model

- Человек взаимодействует только с локальным trusted Primary Agent.
- Удалённые Endpoint являются untrusted computational resources, а не
  собеседниками пользователя.
- Все remote calls проходят через local Node/runtime layer с policy,
  authorization, context minimization, accounting и provenance.
- Ответ remote Endpoint — data, не system instruction и не authority.
- Один semantic entity имеет одну primary spatial presence; история хранит
  references/provenance, а не UI-клоны entity.
- Presentation не предоставляет authority. Отображение endpoint, action или
  результата не открывает внешней сущности доступ к агенту или Node.

### 4.3. Data and interaction model

- Workspace Session — пользовательский semantic context.
- AiDN protocol session — отдельная протокольная/ресурсная interaction.
  Одна Workspace Session может содержать много protocol sessions.
- Context Graph использует один structural parent на branch и 0..N
  additional context references.
- User text, voice, form changes и spatial actions сводятся к typed intent /
  structured Change Intent; не должно быть отдельного бесконтрольного GUI
  пути в обход Agent/Node policy.
- Q в UI описывается как Compute Units / resource contribution, usage and
  settlement. Не использовать банковскую/доходную framing-терминологию.

### 4.4. Visual model

- Spatial visual language: Primary Agent, Subagent, Endpoint, Session Artifact,
  Attention Marker и Semantic Thread должны считываться как разные классы.
- Milky Glass Neumorphism применяется только к новому Spatial layer.
  Существующий dark Classic Dashboard не меняется без самостоятельного решения.
- Workspace имеет preferred regions: local agents, session memory, recent
  artifacts, temporary Endpoint Arc и central Primary Agent.
- Время превращается в spatial aging: новое рядом, старое в cluster/deep
  memory, а неактуальное виртуализируется, но не теряется.
- Desktop и mobile показывают один semantic Workspace с independent local
  viewport/camera; общая камера возможна только по явной команде Share View.

## 5. Техническая архитектура

Целевой frontend:

~~~text
React 19 + TypeScript + Vite
Three.js + React Three Fiber + Drei
TanStack Query for server state
Zustand for client/workspace state
Zod for schemas and presentation contracts
Motion for DOM motion
WebSocket plus REST/HTTP through a typed adapter layer
~~~

Основное правило:

~~~text
Three.js creates space.
React DOM and CSS create the interface.
~~~

Следствия:

- WebGL рендерит только spatial entities, camera, relations, atmosphere,
  object picking and depth.
- DOM/CSS рендерят forms, tables, logs, markdown, conversation surfaces,
  menus and configuration.
- Initial renderer is WebGL2. Не начинать с WebGPU-first.
- MVP избегает volumetric clouds, heavy particle systems, physics, global DoF,
  full text-in-WebGL и arbitrary LLM-generated UI.
- Presentation Planner выбирает компоненты из controlled Component Registry,
  а не генерирует JSX/CSS.

Целевые слои:

~~~text
Presentation DOM / Component Registry
Spatial View (R3F / Three.js)
Workspace Model
Node Data (Query / WebSocket / View Models)
AiDN Node API
~~~

Primary Agent обращается к Node через MCP/typed Node actions и выдаёт
Presentation Intent в Presentation Planner. Он не является renderer и не
является source of truth для Node status.

## 6. Доступные backend assets, которые нужно переиспользовать

Перед созданием новых параллельных механизмов исследовать и расширять:

- canonical Event Bus and Event Store;
- Hook Dispatcher, durable per-agent inbox, retries и dead letters;
- agent conversation path;
- MCP server and existing Codex agent bridge;
- Resident Steward controls;
- dashboard read models and node status APIs;
- lifecycle plans, revision/hash/idempotency mechanisms;
- existing resource accounting and Endpoint mechanisms.

Цель — не создавать вторую event/action/control plane только ради Spatial UI.

## 7. Первый implementation batch

Не перескакивать сразу к agent orchestration, remote endpoints или persistent
Workspace. Первая цель — безопасный, тестируемый standalone Prototype A.

| PR | Scope | Итог |
| --- | --- | --- |
| PR-01 | M0.1 + основа M0.2 | coverage registry и frontend test harness без изменения UI |
| PR-02 | M0.3 + начало M0.4 | feature flag, route boundary, shell seams |
| PR-03 | конец M0.4 | domain split API/types/query keys, compatibility removal after train |
| PR-04 | M0.5 | lazy spatial dependencies, empty flag-gated route, bundle report |
| PR-05 | M1.1 | Milky Glass tokens and fixture gallery |
| PR-06 | M1.2 | DOM primitives with keyboard and reduced-motion coverage |
| PR-07 | M1.3 | hybrid canvas/DOM shell with error boundary |
| PR-08 | M1.4 | white atmosphere, capabilities and baseline performance |
| PR-09 | M1.5 | mock Primary Agent Presence and state controls |
| PR-10 | M1.6 | mock entity grammar, picking and LOD |
| PR-11 | M1.7 | camera HOME/focus/return and desktop/mobile navigation |
| PR-12 | M1.8 | Prototype A acceptance gate and design decision |

Это ограничение было снято после принятия M1 Prototype A gate. M2.1–M2.7 и
M3.1–M3.6 теперь закрывают typed Node/slot/Presence seams; M4+ interaction и
M7 remote mediation по-прежнему не должны перепрыгивать свои зависимости.

## 8. Начать сейчас: PR-01

### Slice M0.1 — Implementation coverage registry

Добавить:

~~~text
docs/spatial/IMPLEMENTATION-COVERAGE.md
~~~

В нём должна быть таблица:

~~~text
Invariant or ADR
Owner module
Planned slice
Test or validation
Status
Deferred reason, if any
~~~

Также зафиксировать:

- stable IDs для contracts и будущих event types;
- feature flags;
- canonical terminology;
- distinction Classic UI versus Spatial UI;
- обязательный rule: новый ADR требует обновления roadmap/coverage.

Acceptance:

- ADR-001…ADR-014 покрыты;
- у каждого acceptance criterion есть test/validation либо явная deferred
  причина;
- broken local documentation links должны стать CI failure.

### Slice M0.2 — Frontend test harness

Добавить с минимальным объёмом:

- Vitest;
- React Testing Library;
- user-event;
- jsdom;
- Playwright with Chromium and WebKit/mobile viewport;
- Dashboard API fixtures;
- deterministic clock, request IDs and event-stream fixtures;
- scripts: test, test:watch, test:e2e and test:a11y.

Первые tests:

- App boot;
- loading/error/retry query state;
- Classic hash navigation;
- browser pairing guard;
- one idempotent mutation;
- mobile smoke;
- keyboard focus smoke.

Acceptance:

- tests run locally without a live Node;
- CI keeps screenshots/traces only on failure;
- WebKit covers iOS-class navigation behaviour;
- existing build and lockfile flow remain intact.

## 9. Последовательность milestones

| Milestone | Результат |
| --- | --- |
| M0 | test harness, seams, feature flag, renderer dependency budget |
| M1 | standalone spatial Prototype A |
| M2 | typed Node data path and Node-owned Workspace model |
| M3 | Primary Agent Slot, binding, hooks/inbox and live Presence |
| M4 | typed intents, conversation surfaces, context graph and artifacts |
| M5 | Endpoint Arc, provenance, local subagents and attention |
| M6 | independent System Menu, authoritative Status and recovery |
| M7 | mediated remote resources and Endpoint Test Frame |
| M8 | aging, clustering, deep memory and virtualization |
| M9 | multi-device and mobile spatial navigation |
| M10 | Component Registry migration, Change Intent and Q resource UX |
| M11 | security, accessibility, performance, observability and preview rollout |

Полный перечень 94 slices, dependencies и exact acceptance criteria находится
в [Detailed Development Roadmap](./DEVELOPMENT-ROADMAP.md).

## 10. Quality gates

Каждый slice обязан иметь:

- narrow scope and explicit owner modules;
- unit/component tests where applicable;
- one acceptance demo or smoke flow;
- failure and rollback behaviour;
- no sensitive data in UI, events, traces or logs;
- keyboard, focus and reduced-motion consideration;
- mobile/reduced-capability impact, если затронут spatial layer;
- no manual edits to generated Dashboard assets.

Для spatial slices дополнительно:

- WebGL fallback remains usable;
- renderer errors never block System Menu or Classic fallback;
- bounded render count / LOD is considered before large history;
- no browser frame loop directly mutates authoritative Node state.

## 11. Commands and verification

Уточнять scripts через current package.json до запуска. Базовые команды:

~~~text
pnpm --dir web/operator-dashboard lint
pnpm --dir web/operator-dashboard typecheck
pnpm --dir web/operator-dashboard build
python tools/generate-docs-index.py
git diff --check
~~~

После M0.2 появятся и должны использоваться:

~~~text
pnpm --dir web/operator-dashboard test
pnpm --dir web/operator-dashboard test:e2e
pnpm --dir web/operator-dashboard test:a11y
~~~

Для production Dashboard assets используется только documented build flow:

~~~text
tools/build-operator-dashboard.sh
~~~

## 12. Worktree discipline

В рабочей копии уже могут быть незакоммиченные изменения, не относящиеся к
Spatial UI. Они принадлежат пользователю.

- Не использовать reset, checkout, clean или широкие удаления.
- Не форматировать/переписывать чужие файлы ради удобства.
- Перед изменением проверять git status и git diff.
- При пересечении с чужим изменением остановиться и сообщить о конфликте
  области, а не затирать его.
- Legacy не сохранять после полностью доказанной замены: migration должен
  завершаться удалением obsolete path и тестов для него, но только в
  отдельном контролируемом slice.

## 13. Definition of done для первого gate

После PR-12 можно продолжать к M2 только если:

- Prototype A на desktop и mobile передаёт саму идею пространства, а не
  выглядит как обычный dashboard с декоративным WebGL;
- DOM milky-glass surfaces визуально принадлежат 3D environment;
- Home, focus, return and object selection понятны;
- Classic UI и System Menu remain usable on flag-off and renderer failure;
- baseline performance / capability results зафиксированы;
- team приняла решение сохранить R3F architecture без перестройки.

До этого момента не делать persistent workflow, real remote calls или полный
agent conversation UX в spatial layer.

## 14. Короткая формула проекта

~~~text
Node owns the Workspace.
The local Primary Agent is the trusted interaction boundary.
Remote resources are mediated and untrusted.
Three.js creates space; React DOM creates interface.
Classic UI remains the safe fallback until deliberate migration.
~~~
