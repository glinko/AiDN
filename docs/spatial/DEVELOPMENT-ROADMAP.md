# AiDN Spatial Agent Interface — Detailed Development Roadmap

**Статус:** Execution plan  
**Дата:** 2026-09-04  
**Область:** Spatial Agent Interface, Primary Agent, Workspace, Component Registry, remote resources, mobile, Classic UI integration  
**Назначение:** подробный план разработки, разбитый на независимо принимаемые вертикальные слайсы  
**Старт реализации в новом чате:** [Implementation Handoff](./IMPLEMENTATION-HANDOFF.md)  

## 1. Цель документа

Этот roadmap переводит концепцию Spatial Agent Interface и решения
ADR-001…ADR-014 в последовательность инженерных изменений, которые можно:

- реализовывать небольшими pull request;
- включать за feature flag;
- проверять отдельными demo-сценариями;
- принимать по измеримым критериям;
- откатывать без повреждения канонического состояния Node;
- постепенно соединять с реальным Hypervisor, MCP, Hooks, Endpoint и
  Resource Accounting.

Roadmap не заменяет ADR. ADR отвечают на вопрос, какое поведение считается
правильным. Этот документ отвечает на вопросы:

1. в каком порядке строить систему;
2. какие контракты появляются на каждом этапе;
3. какие файлы и подсистемы затрагиваются;
4. чем ограничен каждый слайс;
5. какими тестами и демонстрацией он принимается;
6. какие следующие слайсы он разблокирует.

## 2. Нормативные источники

План основан на следующих документах:

- [Общий Spatial Agent Interface Implementation Plan](./AiDN-Spatial-Agent-Interface-Implementation-Plan.md)
- [Реестр двенадцати продуктовых вопросов](./OPEN-QUESTIONS.md)
- [ADR-001 — Node-scoped Primary Agent](./ADR-001-primary-agent-scope.md)
- [ADR-002 — Node Workspace Ownership](./ADR-002-node-workspace-ownership.md)
- [ADR-003 — Orbital Attention System](./ADR-003-orbital-attention-system.md)
- [ADR-004 — Primary Agent Visual State Language](./ADR-004-primary-agent-visual-state-language.md)
- [ADR-005 — Spatial Entity Topology](./ADR-005-spatial-entity-topology.md)
- [ADR-006 — Workspace Sessions and Context Graph](./ADR-006-workspace-sessions-context-graph.md)
- [ADR-007 — Spatial Memory, Aging and Clustering](./ADR-007-spatial-memory-aging-clustering.md)
- [ADR-008 — Entity Uniqueness and Provenance References](./ADR-008-entity-uniqueness-and-provenance.md)
- [ADR-009 — Multi-Device Workspace and Mobile Navigation](./ADR-009-multi-device-workspace-and-mobile-navigation.md)
- [ADR-010 — Node Status and Recovery Access](./ADR-010-node-status-and-recovery-access.md)
- [ADR-011 — Agent-Mediated Component Interface](./ADR-011-agent-mediated-component-interface.md)
- [ADR-012 — Local Trust Boundary and Mediated Remote Resources](./ADR-012-local-trust-boundary-and-mediated-remote-resources.md)
- [ADR-013 — AiDN Milky Glass Neumorphism](./ADR-013-aidn-milky-glass-neumorphism-visual-design.md)
- [ADR-014 — Spatial UI Technical Architecture](./ADR-014-spatial-ui-technical-architecture.md)

Если roadmap расходится с принятым ADR, приоритет имеет ADR. Расхождение
исправляется отдельным documentation change или новым ADR, а не скрытым
решением внутри реализации.

## 3. Текущий baseline репозитория

### 3.1. Frontend

Канонический исходный код Dashboard находится в:

~~~text
web/operator-dashboard/
~~~

Собранные статические файлы находятся в:

~~~text
src/aidn_hypervisor/static/react-dashboard/
~~~

Статический каталог является build output. Ручные изменения generated JS/CSS
в нём запрещены. Сборка и атомарная активация выполняются существующим
tools/build-operator-dashboard.sh.

Уже используются:

- React 19;
- TypeScript;
- Vite;
- TanStack Query;
- Zustand;
- Zod;
- Recharts;
- Base UI;
- Tailwind CSS;
- Lucide.

Для Spatial runtime пока отсутствуют:

- Three.js;
- React Three Fiber;
- Drei;
- Motion;
- отдельная workspace model;
- typed Presentation Intent/Result Model registry;
- frontend unit/component/e2e test harness;
- live-event adapter, отделённый от UI;
- quality profile и renderer capability detection.

### 3.2. Текущий технический долг

На момент составления roadmap:

- web/operator-dashboard/src/App.tsx содержит примерно 4135 строк;
- web/operator-dashboard/src/lib/api.ts содержит примерно 613 строк;
- web/operator-dashboard/src/lib/types.ts содержит примерно 599 строк;
- use-dashboard.ts создаёт большой набор параллельных query;
- Classic UI уже содержит полезные Steward, Settings, Resource Broker,
  Wallet, Endpoint, Network и Hook surfaces;
- frontend-specific tests в web/operator-dashboard отсутствуют;
- Python tests проверяют build/staging generated dashboard assets.

Spatial UI не должен увеличивать App.tsx ещё на несколько тысяч строк.
Подготовительный рефакторинг создаёт seams, но не меняет поведения Classic UI.

### 3.3. Backend assets, которые нужно переиспользовать

В Hypervisor уже существуют:

- canonical Event Bus и durable Event Store;
- per-agent inbox и acknowledgement;
- Hook dispatcher, retries, dead letters и replay;
- operator-to-agent conversation path;
- MCP tool boundary;
- Codex agent bridge;
- Resident Steward status, prompt, policy и inference APIs;
- Endpoint, Session, Wallet, Resource Broker и settlement records;
- Dashboard read models;
- operator browser/session authorization;
- lifecycle plans с revision/plan hash и idempotency.

Roadmap расширяет эти механизмы. Он не создаёт второй Event Store, второй
permission engine, второй Endpoint registry или браузерный источник истины.

## 4. Обязательные архитектурные правила

### 4.1. Источник истины

Authoritative state принадлежит Node/Hypervisor. TanStack Query хранит
server-state cache. Zustand хранит только presentation/workspace state,
которое можно восстановить или безопасно потерять.

### 4.2. Один control path

Voice, text, form edit и spatial action создают typed intent. Изменение
Node проходит через существующую validation, authorization, idempotency и
audit boundary.

### 4.3. Один канонический объект

Одна semantic entity имеет одну primary spatial presence. История, frames,
focus proxies и discovery используют references и provenance.

### 4.4. Локальная trust boundary

Primary Agent не открывает произвольные remote connections. Remote Endpoint
получает только минимальный разрешённый context через local mediation layer.
Remote output является untrusted data.

### 4.5. Renderer boundary

~~~text
R3F / Three.js
→ пространство, сущности, camera, fog, picking, threads, LOD

React DOM / CSS
→ текст, forms, tables, charts, logs, menus, settings, accessible UI
~~~

### 4.6. Progressive delivery

Classic UI остаётся recovery и expert surface. Spatial UI вводится по
route/feature flag. Каждый milestone должен оставлять приложение
работоспособным при отключённом Spatial runtime.

### 4.7. Accessibility с первого слайса

Каждая spatial action получает keyboard/structured equivalent. Цвет,
анимация и положение не являются единственным способом передать состояние.
Reduced motion, high contrast, screen reader и touch paths не откладываются
до финальной полировки.

### 4.8. Bounded rendering

Каждый новый visual effect имеет quality profile, LOD/fallback и измеряемый
budget. Volumetric clouds, WebGPU-first, physics, full-scene DoF и arbitrary
shader generation не входят в MVP.

## 5. Единица поставки

### 5.1. Epic

Группа взаимосвязанных capabilities, завершающаяся milestone gate.

### 5.2. Vertical slice

Минимальный end-to-end результат, который:

- имеет один основной пользовательский сценарий;
- проходит от schema/data до presentation;
- содержит happy path, loading, empty, stale и error states;
- имеет automated tests;
- демонстрируется без ручного изменения базы или файлов;
- не требует незавершённого соседнего PR для запуска.

### 5.3. Task

Локальная инженерная работа внутри slice. Task сам по себе не считается
поставленной пользовательской ценностью.

### 5.4. Experiment

Ограниченный prototype для ответа на один вопрос. Experiment не становится
production dependency автоматически. Для принятия результата нужен decision
record и bounded implementation.

## 6. Definition of Ready для слайса

Слайс готов к разработке, если:

- указаны связанные ADR и invariants;
- определён один основной scenario;
- известен authoritative data source;
- описаны request/response/event schemas;
- известна permission boundary;
- перечислены loading, empty, stale, offline и rejected states;
- указаны desktop, mobile, keyboard и screen-reader expectations;
- определён measurable performance budget;
- понятны миграция и rollback;
- перечислены тесты и demo script;
- нет скрытого решения, противоречащего принятому ADR.

## 7. Definition of Done для каждого слайса

Слайс завершён только когда:

1. schema и contracts versioned;
2. backend validation и authorization работают;
3. frontend не доверяет raw payload без parsing;
4. happy path и отрицательные состояния отображаются;
5. unit/component/integration tests проходят;
6. keyboard и touch paths проверены;
7. status не передаётся только цветом;
8. reduced-motion path сохраняет смысл;
9. logging/audit/telemetry не содержат secrets;
10. feature flag и rollback проверены;
11. build generated assets выполняется штатным script;
12. документация и ADR coverage matrix обновлены;
13. demo evidence приложен к PR;
14. нет новых unbounded monolith modules;
15. lint, typecheck, frontend tests и релевантные Python tests зелёные.

## 8. Целевой CI quality gate

Каждый Spatial PR постепенно должен проходить:

~~~text
pnpm lint
pnpm typecheck
pnpm test
pnpm build
pnpm test:e2e
Python contract/integration tests
generated dashboard asset tests
link and documentation validation
~~~

Первые слайсы добавят отсутствующие команды test и test:e2e. До их появления
PR не может объявлять Spatial UI production-ready.

## 9. Зависимости верхнего уровня

~~~text
R0 Repository seams and test harness
        │
        ├── R1 Design system and hybrid renderer
        │       └── R3 Spatial entities and interaction
        │
        ├── R2 Contracts, data adapters and Workspace service
        │       ├── R4 Primary Agent
        │       ├── R5 Sessions and Context Graph
        │       └── R6 Status and recovery
        │
        ├── R7 Attention, discovery and provenance
        │
        ├── R8 Remote resource mediation
        │
        ├── R9 Spatial memory and multi-device sync
        │
        ├── R10 Resource semantics and shared components
        │
        └── R11 Hardening, rollout and Classic migration
~~~

## 10. Milestone overview

| Milestone | Результат | Основные ADR |
| --- | --- | --- |
| M0 | безопасная база, test harness, feature flag, seams | 011, 013, 014 |
| M1 | standalone Spatial Core prototype | 004, 005, 013, 014 |
| M2 | canonical data flow и Node-owned Workspace | 002, 008, 014 |
| M3 | Primary Agent Slot и живое Agent Presence | 001, 003, 004 |
| M4 | interaction, Sessions и Context Graph | 006, 011 |
| M5 | Endpoint topology, provenance и attention | 003, 005, 008 |
| M6 | System Menu, Status и recovery | 002, 009, 010 |
| M7 | mediated remote resources и Endpoint Test | 005, 008, 012 |
| M8 | spatial memory, clustering и virtualization | 006, 007, 008 |
| M9 | mobile и multi-device Workspace | 002, 007, 009 |
| M10 | Agent-mediated Component Registry и Q resources | 010, 011, 013 |
| M11 | hardening, rollout и controlled migration | все |

# 11. M0 — Repository Foundation

Цель milestone: создать безопасные границы для новой разработки и не
превратить текущий App.tsx в ещё больший монолит.

## Slice M0.1 — Spatial decision and coverage registry

**Цель:** превратить ADR-001…014 в проверяемую coverage matrix.

**Работы:**

- добавить machine-readable или Markdown registry: invariant → owner module →
  planned slice → test → status;
- присвоить стабильные IDs всем новым contracts и event types;
- зафиксировать distinction между current Classic UI и target Spatial UI;
- добавить checklist обновления roadmap при новом ADR;
- отметить unresolved implementation choices отдельно от product decisions.

**Артефакты:**

- docs/spatial/IMPLEMENTATION-COVERAGE.md;
- список feature flags;
- список canonical terms;
- ADR-to-slice table.

**Тесты/проверки:**

- все ADR присутствуют в matrix;
- каждый acceptance criterion имеет planned test или явный deferred reason;
- broken documentation links блокируют CI.

**Demo:** открыть matrix и проследить любой invariant до конкретного slice и
test suite.

**Зависимости:** нет.

## Slice M0.2 — Frontend test harness

**Цель:** дать frontend собственную пирамиду тестов до появления R3F.

**Работы:**

- добавить Vitest;
- добавить React Testing Library и user-event;
- добавить jsdom;
- добавить Playwright для Chromium/WebKit/mobile viewport;
- добавить test fixtures для Dashboard API;
- добавить deterministic clock, request IDs и event stream fixtures;
- добавить scripts test, test:watch, test:e2e и test:a11y;
- сохранить существующий pnpm lock и build flow.

**Минимальные тесты:**

- App boot;
- query loading/error/retry;
- hash navigation Classic UI;
- browser pairing guard;
- one mutation with idempotency;
- mobile smoke;
- keyboard focus smoke.

**Acceptance:**

- tests запускаются локально одной командой;
- CI публикует trace/screenshot только при failure;
- test suite не зависит от работающей внешней Node;
- WebKit path покрывает iOS-class behavior.

**Demo:** искусственно сломанный API fixture даёт typed error, а не unhandled
promise.

**Зависимости:** M0.1.

## Slice M0.3 — Feature flag and route boundary

**Цель:** запускать Classic и Spatial surfaces из одной сборки.

**Работы:**

- ввести feature flag spatial_ui_enabled;
- определить route /operators/dashboard/react/#spatial;
- сохранить Classic route как default до rollout gate;
- добавить capability check WebGL2;
- добавить explicit fallback на Classic UI;
- запрещать server-side flag обходить operator authorization;
- логировать renderer init failure без sensitive GPU details.

**States:**

- flag disabled;
- flag enabled and supported;
- flag enabled but WebGL2 unavailable;
- renderer initialization failed;
- operator selected Classic fallback.

**Acceptance:**

- Spatial bundle не ломает Classic navigation;
- direct URL корректно возвращает fallback;
- выключение flag не требует удаления workspace data;
- selected Node/Hypervisor context сохраняется при switch.

**Demo:** переключение Classic ↔ Spatial на одной Node без reload login.

**Зависимости:** M0.2.

## Slice M0.4 — App.tsx decomposition seams

**Цель:** выделить устойчивый app shell и domain surfaces без redesign.

**Работы:**

- вынести routing/hash sync;
- вынести Hypervisor selector;
- вынести query provider и mutation notices;
- разделить screen registry и screen components;
- перенести domain helpers рядом с соответствующими feature modules;
- разделить api.ts на transport, parser и domain clients;
- разделить types.ts на domain schemas;
- оставить compatibility exports только на время одного migration train;
- запретить новые feature components внутри App.tsx.

**Ограничение:** поведение, copy и dark Classic UI визуально не меняются.

**Acceptance:**

- App.tsx становится composition root;
- существующие screens доступны по прежним hashes;
- API calls и payloads идентичны baseline;
- visual smoke показывает отсутствие unintended changes;
- no circular dependencies.

**Demo:** существующие Overview, Agents, Endpoints, Wallet и Settings работают
после refactor.

**Зависимости:** M0.2, M0.3.

## Slice M0.5 — Spatial dependencies and bundle budget

**Цель:** добавить renderer libraries с контролируемым bundle impact.

**Работы:**

- добавить three;
- добавить @react-three/fiber;
- добавить @react-three/drei;
- добавить motion;
- включить route-level lazy loading;
- отделить spatial chunk от Classic initial chunk;
- добавить bundle size report;
- определить baseline gzip/brotli budgets;
- проверить licensing и lockfile reproducibility.

**Acceptance:**

- Classic route не загружает Three.js chunk до перехода в Spatial;
- Spatial chunk загружается один раз;
- build остаётся reproducible;
- bundle budget видим в CI;
- dependency addition не меняет generated asset activation semantics.

**Demo:** network panel показывает отсутствие spatial chunk на Classic route.

**Зависимости:** M0.3, M0.4.

## Gate M0

Milestone принят, когда:

- Classic UI не регрессировал;
- test harness работает;
- Spatial route gated;
- App имеет устойчивые seams;
- dependencies lazy-loaded;
- ADR coverage registry создан;
- source/build-output boundary задокументирован и проверен.

# 12. M1 — Spatial Core and Visual Foundation

Цель milestone: доказать ощущение пространства и совместимость WebGL + DOM
без подключения реального агента.

**Implementation status (2026-09-05):** M1.1–M1.8 Prototype A slices are
verified in the frontend fixture, with acceptance evidence recorded in
[IMPLEMENTATION-COVERAGE.md](./IMPLEMENTATION-COVERAGE.md). The implementation
keeps the environment, visual state, synthetic entity grammar, local camera,
and performance gate presentation-only; M2 is the next contract/data boundary.

## Slice M1.1 — Milky Glass token package

**Цель:** реализовать ADR-013 как versioned design-system foundation.

**Работы:**

- создать tokens для colors, text, opacity, shadow, radius, blur, spacing и
  motion;
- определить light/high-contrast/reduced-transparency fallbacks;
- создать theme boundary только для Spatial surface;
- не менять текущую dark palette Classic UI;
- добавить token documentation и Storybook-equivalent fixture page;
- запретить arbitrary visual values lint convention или review rule.

**Components:** token preview, contrast specimen, motion specimen, fallback
specimen.

**Acceptance:**

- primary/secondary/muted text проходят выбранный contrast target;
- surface различима без тяжёлой border;
- unsupported backdrop-filter получает читаемую opaque surface;
- reduced-transparency не разрушает hierarchy.

**Demo:** одна fixture page во всех quality/accessibility profiles.

**Зависимости:** M0.5.

## Slice M1.2 — Surface primitives

**Цель:** создать минимальный reusable DOM design system.

**Работы:**

- Surface;
- GlassFrame;
- Button;
- IconButton;
- Input;
- TextArea;
- Toggle;
- Slider;
- Tooltip;
- StatusLabel;
- FocusRing;
- InsetField;
- RaisedControl.

**Контракт:**

~~~text
depth: flat | raised | floating | inset
glass: none | soft | medium | strong
accent: neutral | blue | violet | cyan | amber | critical
radius: small | medium | large | pill
emphasis: secondary | normal | primary
~~~

**Acceptance:**

- semantics не зависят от placement;
- hover, active, focus-visible и disabled различимы;
- touch target не меньше установленного minimum;
- Button не выполняет action без explicit handler;
- screen reader labels обязательны для icon-only controls.

**Demo:** primitives gallery с keyboard-only прохождением.

**Зависимости:** M1.1.

## Slice M1.3 — Hybrid renderer shell

**Цель:** создать физическое разделение SpatialCanvas и DOMOverlay.

**Работы:**

- добавить SpatialWorkspace composition root;
- добавить fixed WebGL canvas;
- добавить fixed DOM overlay;
- настроить pointer-events boundary;
- добавить renderer error boundary;
- добавить loading/fallback surface;
- добавить ResizeObserver и DPR control;
- не связывать canvas напрямую с Dashboard API.

**Acceptance:**

- DOM control кликается поверх canvas;
- пустой overlay не блокирует orbit/pan;
- resize и orientation change не теряют selected Node;
- renderer error возвращает оператора в usable DOM fallback;
- keyboard focus не уходит в canvas trap.

**Demo:** DOM GlassFrame открывается поверх интерактивной mock scene.

**Зависимости:** M1.2.

## Slice M1.4 — White atmospheric environment

**Цель:** реализовать минимальную пространственную среду ADR-014.

**Работы:**

- high-key background;
- soft matte ground;
- subtle horizon;
- THREE.Fog с bounded near/far;
- Hemisphere Light;
- soft key и fill;
- neutral studio environment map;
- no visible grid;
- no volumetric cloud meshes;
- no DoF.

**Quality profiles:**

- low: opaque/simple materials, no post-processing;
- mobile: DPR cap, simple shadows, minimal reflections;
- desktop: physical materials and soft shadows;
- high: optional richer reflections, но не новый semantic behavior.

**Acceptance:**

- distant objects теряют contrast/saturation предсказуемо;
- glass object остаётся видимым на almost-white background;
- mobile scene не перегревает renderer в idle;
- no continuous animation when tab hidden.

**Demo:** camera перемещается от near object к fog boundary.

**Зависимости:** M1.3.

## Slice M1.5 — Primary Agent material prototype

**Цель:** создать визуальный центр без реального backend state.

**Работы:**

- glass sphere;
- inner luminous core;
- restrained halo;
- optional instanced inner particles;
- mock READY/THINKING/WORKING/OFFLINE states;
- semantic DOM label доступный по focus;
- no custom shader until baseline profiling.

**Acceptance:**

- минимум два visual channels на состояние;
- color не единственный signal;
- OFFLINE не скрывает System entry placeholder;
- reduced-motion заменяет pulse статическим channel;
- material имеет LOD fallback.

**Demo:** deterministic state sequence с паузой на каждом состоянии.

**Зависимости:** M1.4.

## Slice M1.6 — Mock spatial entities and picking

**Цель:** проверить общий visual grammar.

**Работы:**

- 3 Subagent presences;
- 7 Endpoint energy objects;
- 6 Session Artifacts;
- 3 Attention Markers;
- 2 semantic threads;
- Endpoint particles через InstancedMesh;
- raycasting/object picking;
- keyboard-accessible parallel entity list;
- selection highlight без protocol effect.

**Acceptance:**

- Agent, Endpoint, Artifact и Attention визуально различимы;
- hover/focus не создаёт duplicate object;
- click только выбирает entity;
- selection доступен мышью, touch и keyboard;
- LOD переключение не меняет identity.

**Demo:** выбрать каждую semantic class и открыть mock tooltip.

**Зависимости:** M1.5.

## Slice M1.7 — Camera and navigation prototype

**Цель:** проверить HOME, focus, zoom и возврат.

**Работы:**

- WorkspaceCamera;
- NavigationController;
- FOCUS_PRIMARY_AGENT;
- focus entity;
- return from focus;
- bounded rotate/pan/zoom;
- camera state local to viewport;
- reduced-motion instant/short transition;
- Escape и visible Back control.

**Acceptance:**

- HOME всегда возвращает Primary Agent;
- focus не меняет world coordinates;
- rapid repeated commands не оставляют camera в invalid state;
- keyboard equivalent покрывает pointer/touch;
- camera transition отменяется безопасно.

**Demo:** HOME → Endpoint focus → return → Session focus → HOME.

**Зависимости:** M1.6.

## Slice M1.8 — Prototype A performance and UX gate

**Цель:** принять или скорректировать Spatial Core до backend integration.

**Измерения:**

- FPS и frame time desktop/mobile;
- memory after repeated focus cycles;
- idle GPU/CPU activity;
- bundle size;
- pointer latency;
- reduced-motion behavior;
- WebKit/iOS viewport;
- browser zoom 200%;
- forced colors/high contrast fallback.

**Acceptance target:**

- около 60 FPS на target desktop baseline;
- click/focus transition начинается менее чем за 100ms;
- средний desktop frame ориентирован на 16ms budget;
- mobile profile остаётся usable при reduced detail;
- no blocking accessibility defect;
- DOM и 3D выглядят одной visual system.

**Demo:** записанный desktop и mobile сценарий Prototype A.

**Зависимости:** M1.1…M1.7.

## Gate M1

После gate разрешается интеграция с canonical data. Если гибридная модель не
проходит UX/performance gate, решение пересматривается до появления
backend-dependent spatial code.

# 13. M2 — Contracts, Data Flow and Node-owned Workspace

Цель milestone: связать Spatial runtime с typed canonical data, не отдавая
renderer'у authority.

**Текущий статус:** M2.1–M2.7 typed data path, live gateway, view-model,
Node-owned Workspace model/persistence seam и mock-real runtime verified;
следующий gate — M3 Primary Agent Slot. Durable backend storage and production
event transport remain explicit adapter seams.

## Slice M2.1 — Shared schema package

**Цель:** отделить transport payload от UI model.

**Работы:**

- создать Zod schemas для IDs, revisions, timestamps и freshness;
- создать discriminated schemas для Agent, Endpoint, Session, Artifact,
  Attention, Status и Relation;
- определить schema version;
- определить UNKNOWN/STALE/UNAVAILABLE без boolean shortcuts;
- добавить parser diagnostics без raw secret payload;
- создать fixtures из реальных Dashboard responses.

**Acceptance:**

- malformed payload отклоняется до store;
- unknown additive fields не ломают compatible version;
- breaking schema version даёт explicit incompatible state;
- timestamp/freshness нормализуются в одном месте.

**Demo:** good, stale, partial и malformed payload fixtures.

**Зависимости:** M0.4, M1.

## Slice M2.2 — Domain API clients and query keys

**Цель:** декомпозировать api.ts и use-dashboard.ts по domains.

**Работы:**

- transport client;
- auth/session adapter;
- query key factory;
- node status client;
- agents client;
- workspace client;
- endpoints client;
- sessions client;
- resources client;
- events/hooks client;
- mutation invalidation policy;
- request correlation и idempotency helper.

**Acceptance:**

- domain client не импортирует renderer;
- query key включает active Hypervisor/Node scope;
- switch Node не показывает data предыдущей Node;
- mutations invalidate только нужные projections;
- 401/403/409/422 имеют typed error categories.

**Demo:** switch между двумя mock Nodes с разными caches.

**Зависимости:** M2.1.

## Slice M2.3 — Live Event Gateway

**Цель:** провести live events через Event Dispatcher и State Adapter.

**Работы:**

- определить transport adapter interface;
- реализовать WebSocket или совместимый server stream за interface;
- reconnect with bounded backoff;
- resume cursor;
- event schema parsing;
- deduplication;
- per-Node ordering;
- stale revision rejection;
- Query cache updates;
- presentation notification output отдельно.

**Event path:**

~~~text
transport
→ parse
→ authenticate
→ deduplicate
→ order/revision check
→ query cache update
→ view-model derivation
→ renderer
~~~

**Acceptance:**

- raw event не меняет mesh напрямую;
- duplicate event идемпотентен;
- reconnect не теряет retained events;
- out-of-order event не откатывает state;
- unknown event диагностируется и игнорируется безопасно.

**Demo:** endpoint READY → DEGRADED → READY через fixture stream.

**Зависимости:** M2.1, M2.2.

## Slice M2.4 — View Model layer

**Цель:** сделать presentation projection явной.

**Работы:**

- AgentViewModel;
- EndpointViewModel;
- SessionArtifactViewModel;
- AttentionViewModel;
- NodeStatusViewModel;
- deterministic state composition;
- provenanceRef и sourceRevision;
- familiarity отдельно от reputation;
- display text/freshness labels;
- quality/LOD hints без arbitrary styling.

**Acceptance:**

- renderer не импортирует raw API types;
- одинаковый canonical state даёт одинаковый view model;
- visual state покрывается unit tests;
- missing evidence не превращается в green/online;
- view model не содержит private keys, tokens или full secret config.

**Demo:** один EndpointViewModel рендерится DOM details и 3D presence.

**Зависимости:** M2.1, M2.3.

## Slice M2.5 — Workspace domain model

**Цель:** ввести Node-owned semantic Workspace.

**Backend model:**

- workspace_id;
- node_id;
- revision;
- canonical entity references;
- semantic anchors;
- relations;
- cluster membership;
- created_at/updated_at;
- schema_version.

**Presentation model:**

- device-local viewport;
- selection;
- opened frames;
- temporary focus;
- transient discovery;
- local quality profile.

**Acceptance:**

- Workspace ownership не зависит от Agent binding;
- replacement/detach агента не удаляет Workspace;
- semantic и presentation state versioned отдельно;
- Node mismatch отклоняется;
- presentation reset не меняет canonical data.

**Demo:** создать Workspace, detach mock agent, reload и восстановить entities.

**Зависимости:** M2.1, backend persistence decision.

## Slice M2.6 — Workspace API and persistence

**Цель:** предоставить минимальный canonical CRUD без произвольных layout
mutations.

**Endpoints:**

- GET workspace snapshot;
- GET changes after revision;
- POST semantic operation;
- POST/PUT device-local viewport;
- POST reset presentation;
- GET entity reference;
- GET relation reference.

**Rules:**

- revision required for shared mutation;
- idempotency key required;
- authorization per operator/agent actor;
- audit entry for semantic mutation;
- presentation-only mutation не создаёт protocol event.

**Tests:**

- stale revision;
- duplicate operation;
- wrong Node;
- agent replaced mid-request;
- reload;
- partial persistence failure;
- corrupt presentation state fallback.

**Demo:** два clients читают один semantic Workspace с разными viewports.

**Зависимости:** M2.5.

## Slice M2.7 — Spatial runtime connected to mock-real data

**Цель:** заменить mock entities Prototype A на view models.

**Работы:**

- query initial snapshot;
- materialize primary presences;
- apply live events;
- empty Workspace;
- loading skeleton/fog placeholder;
- stale banner/status;
- offline snapshot;
- renderer recovery after parse error.

**Acceptance:**

- no direct fetch inside entity components;
- Node switch destroys old scene projections safely;
- duplicate canonical_ref не создаёт second primary presence;
- stale state имеет explicit label;
- Query cache loss не повреждает persisted Workspace.

**Demo:** live fixture Node обновляет Agent и Endpoint states.

**Зависимости:** M2.2…M2.6.

## Gate M2

Milestone принят, когда одна Node-owned Workspace загружается, обновляется и
восстанавливается через canonical typed path, а renderer остаётся полностью
неавторитетным.

# 14. M3 — Primary Agent Slot and Agent Presence

Цель milestone: заменить исторически зашитого Resident Steward на
Node-scoped Primary Agent Slot, который может быть связан с любым разрешённым
agent runtime через MCP/Hooks.

**Текущий статус:** M3.1–M3.6 Primary Agent lifecycle slices verified. Gate M3
закрыт: Node-scoped slot, authorized binding plans, capability/Hooks delivery,
authoritative operational state, live Presence, and the DOM-only management
surface are connected through the typed Node boundary. Следующий milestone —
M4 typed Intent and interaction surfaces.

## Slice M3.1 — Primary Agent Slot domain model

**Цель:** создать каноническую роль Primary Agent отдельно от модели и
runtime.

**Model:**

- slot_id;
- node_id;
- current_binding_id;
- lifecycle_state;
- revision;
- assigned_at;
- assigned_by;
- last_seen_at;
- capability_grant_ref;
- hook_subscription_ref;
- durable_inbox_ref.

**Lifecycle:**

~~~text
UNASSIGNED
→ BINDING
→ CONNECTED
→ DEGRADED
→ DISCONNECTED
→ REVOKED
~~~

**Rules:**

- ровно один slot на Node;
- binding заменяется атомарно;
- Agent Identity, runtime binding и grants — разные records;
- replacement не удаляет Workspace;
- slot state не выводится только из LLM response.

**Tests:** duplicate slot, concurrent bind, stale revision, Node mismatch,
restart, corrupted binding reference.

**Demo:** Node имеет UNASSIGNED slot без потери доступа к Workspace.

**Зависимости:** M2.5, M2.6.

## Slice M3.2 — Agent binding API

**Цель:** управлять assign/replace/detach/revoke через canonical command path.

**Operations:**

- inspect slot;
- create binding plan;
- apply binding;
- replace binding;
- suspend;
- detach;
- revoke credentials;
- verify health;
- recover previous safe state.

**Security:**

- browser operator authorization;
- plan hash/current revision;
- idempotency key;
- audit actor;
- no credential material in read response;
- concurrent replace serialised or conflict-rejected.

**Acceptance:**

- retry не создаёт две bindings;
- apply stale plan возвращает typed conflict;
- revoke останавливает future hook delivery;
- audit показывает who/when/what without secret.

**Demo:** bind mock MCP agent, replace it, then detach.

**Зависимости:** M3.1.

## Slice M3.3 — Capability grants, Hooks and durable inbox

**Цель:** подключить slot к уже существующим MCP, Hook Dispatcher и Event
Store mechanisms.

**Работы:**

- capability grant reference;
- allowlisted MCP tools;
- read/write/action categories;
- hook subscription owned by binding;
- redaction profile;
- delivery cursor;
- acknowledgement;
- retry/dead-letter/replay;
- retained events during disconnect;
- grant change event.

**Acceptance:**

- disconnected agent получает retained events после reconnect;
- ack идемпотентен;
- revoked agent не читает inbox;
- hook filter ограничен type/resource/severity;
- one binding cannot acknowledge another binding inbox;
- payload проходит redaction before delivery.

**Demo:** отключить agent, создать event, подключить и получить один retained
event без duplicate action.

**Зависимости:** M3.2, existing Event Store/Hook Dispatcher.

## Slice M3.4 — Agent operational state aggregator

**Цель:** получить authoritative state для visual language ADR-004.

**Inputs:**

- binding lifecycle;
- MCP connectivity;
- request in flight;
- tool action in flight;
- attention severity;
- Node/Agent health probe;
- last successful response;
- last failed response.

**Output:**

~~~text
READY
LISTENING
THINKING
ACTING
WORKING
ATTENTION
CRITICAL
OFFLINE
~~~

**Rules:**

- THINKING/ACTING могут объединяться в WORKING presentation profile;
- attention является independent overlay;
- stale probe не равен ONLINE;
- state transition содержит timestamp, source и revision.

**Tests:** conflicting inputs, stale health, rapid transition, disconnect
during action, attention while thinking, recovery.

**Demo:** deterministic state fixture drives AgentViewModel.

**Зависимости:** M3.1…M3.3, M2.4.

## Slice M3.5 — Live Primary Agent Presence

**Цель:** связать physical Agent object с реальным slot state.

**Работы:**

- replace mock Agent state;
- Base Operational layer;
- Attention overlay layer;
- accessible state label;
- last-seen details;
- material profiles;
- quality fallback;
- reduced-motion mapping;
- focus/open Agent Details.

**Acceptance:**

- state update идёт Event Gateway → cache → view model → material;
- no renderer transport call;
- OFFLINE Presence остаётся видимым;
- System Menu placeholder доступен;
- color mapping configurable without semantic rename;
- critical attention не скрывается thinking color.

**Demo:** disconnect/reconnect mock binding while Agent remains in Workspace.

**Зависимости:** M1.5, M2.7, M3.4.

## Slice M3.6 — Primary Agent management surface

**Цель:** дать оператору понятное управление slot без привязки к конкретной
LLM.

**Surface fields:**

- Agent Identity;
- binding type;
- connection state;
- granted capabilities;
- hooks state;
- inbox lag;
- last seen;
- replace/detach/revoke;
- health check;
- audit link.

**States:** unassigned, connecting, connected, degraded, revoked, invalid
credentials, incompatible protocol.

**Acceptance:**

- secrets никогда не возвращаются в UI;
- destructive revoke требует explicit confirmation;
- disabled/blocked action объясняет причину;
- surface работает в Classic fallback и Spatial frame;
- keyboard and mobile paths complete.

**Demo:** назначить agent из Classic surface и увидеть Presence в Spatial.

**Зависимости:** M3.2…M3.5, Component Registry minimum from M4.4 can follow
with temporary direct composition.

## Gate M3

Milestone принят: Agent Presence представляет реальный Node-scoped slot, агент
можно безопасно заменить или отозвать через typed command path, а Workspace и
inbox переживают замену. Acceptance evidence находится в
[M3.2–M3.6 lifecycle record](./M3.X-PRIMARY-AGENT-LIFECYCLE.md) и разделах
M3.2–M3.6 [coverage registry](./IMPLEMENTATION-COVERAGE.md).

# 15. M4 — Interaction, Workspace Sessions and Presentation

Цель milestone: сделать Primary Agent реальным входом в Workspace через
text/voice и начать формировать Context Graph.

**Текущий статус:** M4.1–M4.10 frontend interaction slice implemented and
verified. Typed Intent Gateway, Interaction Seed, durable in-memory Session /
Context Graph, Component Registry, Presentation Planner, Conversation Surface,
Generated Object lifecycle, Session Artifact collapse/restore, and explicit
voice adapter are covered by the [M4 implementation record](./M4.X-INTERACTION-AND-PRESENTATION.md)
and the [coverage registry](./IMPLEMENTATION-COVERAGE.md). Node persistence,
canonical Event Store wiring, and full Classic parity remain follow-up seams.

## Slice M4.1 — Typed Intent Gateway

**Цель:** унифицировать text, voice, form и spatial inputs.

**Intent envelope:**

- intent_id;
- workspace_id;
- actor_ref;
- modality;
- text or structured operation;
- target_refs;
- parent_ref;
- context_refs;
- attachments_manifest;
- current_revision;
- idempotency_key;
- created_at.

**Rules:**

- frontend формирует structured facts, не просит LLM угадывать changed field;
- input не является permission;
- target references проверяются на Node scope;
- attachments передаются by reference;
- secret-like input не логируется целиком.

**Tests:** empty intent, oversized input, wrong workspace, duplicate submit,
stale target, unauthorized actor, malformed attachment manifest.

**Demo:** text input и button action создают совместимые intent envelopes.

**Зависимости:** M2.1, M2.5, M3.

## Slice M4.2 — Interaction Seed

**Цель:** реализовать создание новой interaction в произвольной точке.

**Desktop:** click empty space.  
**Mobile:** long press empty space.  
**Keyboard:** Create Interaction command.

**States:**

~~~text
SEED
→ COMPOSING
→ SUBMITTING
→ ACTIVE
→ FAILED or CANCELLED
~~~

**Controls:**

- text;
- file/image/audio attachment references;
- voice;
- Continue from;
- Add to context;
- cancel;
- submit.

**Acceptance:**

- Seed не создаётся при click на entity/control;
- escape/cancel не оставляет пустой Session;
- placement сохраняет semantic anchor;
- keyboard focus попадает в input;
- mobile keyboard не закрывает System access;
- duplicate submit создаёт один root.

**Demo:** создать Seed мышью, touch emulation и keyboard.

**Зависимости:** M4.1, M1.3, M1.7.

## Slice M4.3 — Durable operator-agent conversation

**Цель:** связать Interaction Seed с существующим agent conversation/Hook
path.

**Flow:**

~~~text
Intent
→ canonical operator.message event
→ bound Primary Agent inbox
→ response event
→ Workspace Session projection
→ Conversation Surface
~~~

**Работы:**

- correlation between intent, event and response;
- streaming status;
- retry without duplicate prompt;
- cancel state;
- timeout;
- reconnect;
- agent disconnected queue;
- provenance.

**Acceptance:**

- message survives browser reload;
- no response from old/revoked binding is accepted as current authority;
- streaming chunks cannot inject UI code;
- timeout preserves intent for retry;
- response associated with correct Workspace/branch.

**Demo:** submit message, reload during processing, receive final response.

**Зависимости:** M3.3, M4.1, existing agent_conversation.

## Slice M4.4 — Component Registry v1

**Цель:** позволить агенту выбирать проверенную presentation, а не arbitrary
HTML.

**Registry definition:**

- component_id;
- version;
- props schema;
- data schema;
- supported intents;
- required capabilities;
- allowed actions;
- accessibility contract;
- material profile;
- supported viewports;
- loading/empty/error renderers.

**Initial components:**

- TextResponse;
- ConversationSurface;
- KeyValueSummary;
- StatusSummary;
- EndpointSummary;
- OperationNotice.

**Acceptance:**

- unknown component rejected;
- invalid props rejected;
- remote HTML/script/callback rejected;
- version mismatch explicit;
- component action creates typed intent;
- Classic and Spatial can render at least one same component.

**Demo:** mock Presentation Intent renders allowlisted EndpointSummary.

**Зависимости:** M1.2, M2.1, M4.1.

## Slice M4.5 — Presentation Planner v1

**Цель:** преобразовывать Result Model в bounded composition.

**Planner input:**

- intent;
- typed Result Model;
- target refs;
- importance;
- current focus;
- viewport class;
- requested presentation.

**Planner output:**

- registered component/version;
- semantic anchor;
- lifetime;
- density;
- importance;
- entity references;
- allowed actions.

**Rules:**

- no CSS values;
- no shader source;
- no executable code;
- reuse existing frame when possible;
- update instead of duplicate;
- progressive detail;
- max component count per response.

**Tests:** unknown request, excessive component count, stale target, reuse,
mobile adaptation, partial result.

**Demo:** same Endpoint result gives compact list then focused details.

**Зависимости:** M4.4.

## Slice M4.6 — Conversation Surface

**Цель:** сохранить естественный текстовый диалог в одной surface.

**Работы:**

- user/agent turns;
- streaming;
- message status;
- retry/cancel;
- citations/provenance refs;
- attachment summaries;
- generated object links;
- collapse;
- accessible live announcements;
- virtualized long transcript.

**Acceptance:**

- каждое сообщение не создаёт новый spatial entity;
- long response не меняет camera самопроизвольно;
- streaming bounded and cancellable;
- focus remains predictable;
- session can reopen after reload;
- mobile uses adaptive geometry.

**Demo:** 20-turn fixture with one generated object and one failed turn.

**Зависимости:** M4.3…M4.5.

## Slice M4.7 — Workspace Session and Context Graph

**Цель:** реализовать root, structural parent и context references.

**Relations:**

~~~text
CONTINUES_FROM
USES_CONTEXT
PRODUCED
DELEGATED_TO
USED_ENDPOINT
RELATED_PROTOCOL_SESSION
~~~

**Rules:**

- parent_count <= 1;
- context_refs 0..N;
- relation includes source/target revisions;
- authorization per reference;
- cycle prevention for structural tree;
- protocol Session не создаёт user chat автоматически.

**Tests:** branch, multi-context, forbidden reference, missing target, stale
revision, cycle, same parent retry, cross-Node reference.

**Demo:** A branches into B and C; C uses PDF and Image context.

**Зависимости:** M2.5, M4.2…M4.6.

## Slice M4.8 — Generated Object lifecycle

**Цель:** создавать table/chart/file/report/object рядом с Conversation
Surface.

**Работы:**

- GeneratedObject schema;
- type-specific component mapping;
- source relation;
- layout placement request;
- focus translation for large object;
- update/revision;
- collapse/pin/archive;
- no canonical entity cloning.

**Acceptance:**

- generated object linked to source turn;
- large frame moves to focus region, not object-attached tooltip;
- update preserves identity/revision;
- close presentation does not delete underlying artifact;
- no more than bounded objects per response.

**Demo:** conversation produces one Table and one Report artifact.

**Зависимости:** M4.5, M4.7.

## Slice M4.9 — Session collapse, restore and branching

**Цель:** превратить завершённую Conversation Surface в Session Artifact.

**Работы:**

- collapse transition;
- compact artifact view model;
- title/summary/timestamp;
- reopen;
- start branch from artifact;
- archive/pin;
- restore camera;
- reload persistence.

**Acceptance:**

- collapse сохраняет full Context Graph;
- reopen restores transcript and generated links;
- branch preserves one structural parent;
- artifact is not Protocol Session;
- reduced-motion path has no spatial travel requirement.

**Demo:** close conversation, reopen, create second branch.

**Зависимости:** M4.6…M4.8.

## Slice M4.10 — Voice interaction

**Цель:** добавить voice modality без отдельной semantic model.

**Работы:**

- explicit microphone permission;
- Web Audio capture;
- Web Speech or local STT adapter interface;
- transcript preview/correction;
- start/stop/cancel;
- audio attachment reference;
- voice response optional;
- unavailable permission/device states;
- no hidden continuous recording.

**Acceptance:**

- voice creates same Intent envelope and Workspace Session Root;
- permission denial has text fallback;
- transcript can be reviewed before mutation request;
- microphone state always visible;
- audio bytes do not enter event log directly.

**Demo:** voice question → transcript → same Conversation Surface.

**Зависимости:** M4.1…M4.7.

## Gate M4

Milestone принят: operator text/voice entry uses the same Intent envelope,
response turns remain in a durable session projection, a generated object can
be source-linked, the Session can collapse to an Artifact and restore, and a
branch preserves the Context Graph. Evidence is the M4 interaction test suite,
DOM Conversation Surface, and M4.1–M4.10 coverage rows. The next hardening
seam is Node-backed persistence and canonical Event Store delivery.

# 16. M5 — Entity Topology, Discovery, Provenance and Attention

Цель milestone: сделать spatial grammar операционно полезной: показывать
Endpoint, Subagent, relations, provenance и автономные события без хаоса.

**Текущий статус:** M5.1–M5.10 реализованы в typed frontend topology
adapters и flag-gated DOM/renderer seam. Canonical reference registry,
Endpoint discovery/details, semantic relations, local Subagent lifecycle,
interaction provenance/familiarity, bounded Attention queue, orbital marker
projection и temporary Focus Mode покрыты unit/E2E acceptance evidence.
Подключение к Node Event Store и durable server persistence остаётся явным
adapter seam следующего hardening train.

## Slice M5.1 — Canonical reference registry

**Цель:** обеспечить ENTITY-INV-001 и ENTITY-INV-002.

**Key:**

~~~text
workspace_id + canonical_ref
~~~

**Работы:**

- idempotent primary presence lookup;
- entity type and revision;
- primary/context/summary/focus projection kinds;
- unavailable/tombstone state;
- reference resolution API;
- duplicate detection telemetry.

**Acceptance:**

- repeated discovery returns same primary presence;
- focus proxy is read-only;
- presentation delete does not delete canonical entity;
- old revision remains inspectable as evidence;
- cross-workspace identity cannot leak familiarity.

**Demo:** discover EP-42 three times and show one primary object.

**Зависимости:** M2.5, M2.6, M4.7.

## Slice M5.2 — Endpoint Energy Object

**Цель:** связать real EndpointViewModel с distinct 3D grammar.

**Visual:**

- central energy/glass core;
- instanced particles;
- restrained orbit curves;
- availability state;
- familiarity hint;
- active halo;
- offline collapse/dim fallback.

**Acceptance:**

- Endpoint never looks like Agent Presence;
- price/latency/load not all encoded in geometry;
- unknown values remain unknown;
- LOD preserves class distinction;
- selection has no implicit request.

**Demo:** healthy, busy, degraded, offline and familiar endpoints.

**Зависимости:** M1.6, M2.4, M5.1.

## Slice M5.3 — Endpoint discovery and Arc

**Цель:** показать ranked temporary candidates.

**Работы:**

- Discovery Result schema;
- ranking/relevance field;
- Endpoint Arc layout;
- centrality by relevance;
- candidate virtualization;
- selected candidate detach/approach;
- dismiss discovery;
- pin/promote active object.

**Rules:**

- discovery projections temporary;
- selected endpoint becomes/activates canonical primary presence;
- no request until explicit intent;
- ranking explanation available in details.

**Tests:** empty discovery, 1/7/100 candidates, duplicate refs, stale candidate,
selection conflict, keyboard traversal.

**Demo:** discover seven endpoints, inspect ranking, select one.

**Зависимости:** M5.1, M5.2, layout engine minimum.

## Slice M5.4 — Endpoint Information Surface

**Цель:** дать параметры Endpoint по click/tap/focus.

**Fields:**

- identity/display name;
- capability;
- availability/freshness;
- latency evidence;
- load/capacity;
- Resource Cost;
- required minimum/recommended deposit if metered;
- provider/node provenance;
- validation;
- local familiarity;
- supported input/output;
- actions.

**States:** loading, partial, stale, unavailable, unauthorized, incompatible.

**Acceptance:**

- frame uses DOM;
- source revision and timestamp visible;
- unknown data not invented;
- user can SHOW provenance entity or evidence;
- frame anchored to focus region on mobile.

**Demo:** inspect free and metered Endpoint.

**Зависимости:** M4.4, M5.2, M5.3.

## Slice M5.5 — Semantic Threads and Flow Pulses

**Цель:** визуализировать meaningful relations, not packets.

**Relations:** request, response, streaming, produced, delegated, uses,
settlement, failure.

**Работы:**

- relation schema;
- source/target reference;
- visual path;
- event pulse;
- idle thread;
- hover/focus label;
- keyboard relation inspector;
- offscreen anchor.

**Acceptance:**

- WebSocket frame does not create a pulse by itself;
- repeated stream chunks are aggregated semantically;
- direction/readable label available without color;
- relation reveal does not change topology;
- culling prevents unbounded lines.

**Demo:** Primary Agent delegates to Subagent, which uses Endpoint.

**Зависимости:** M4.7, M5.1.

## Slice M5.6 — Local Subagent lifecycle

**Цель:** представить local delegated actor отдельно от remote resource.

**Работы:**

- Subagent entity/state;
- parent/delegation relation;
- spawn/working/completed/failed lifecycle;
- own attention markers;
- optional local Endpoint Arc;
- capability grant scope;
- cleanup/archive.

**Acceptance:**

- Subagent is Agent class, but visually secondary;
- subagent remote access passes same local mediation boundary;
- completion does not delete provenance;
- orphaned subagent state is recoverable;
- user does not directly mistake remote provider for local Subagent.

**Demo:** Primary Agent spawns research Subagent and receives result.

**Зависимости:** M3, M4.7, M5.5.

## Slice M5.7 — Interaction provenance and familiarity

**Цель:** хранить local experience without global reputation confusion.

**Records:**

- request_id;
- endpoint_ref and revision;
- result_ref;
- outcome;
- latency evidence;
- resource usage reference;
- idempotency key;
- node/workspace/agent scope.

**Derived familiarity:**

~~~text
NEVER_USED
USED
TRUSTED_BY_HISTORY
~~~

**Acceptance:**

- duplicate interaction event does not increment counters twice;
- failed interaction visible;
- local familiarity not used as authorization;
- global reputation remains separate;
- historical endpoint revision remains inspectable.

**Demo:** endpoint evolves from unseen to used without changing global score.

**Зависимости:** M5.1, M5.2, real or fixture interaction path.

## Slice M5.8 — Attention Item backend projection

**Цель:** превратить autonomous event в bounded attention queue.

**Model:**

- attention_id;
- source_event_ref;
- subject_ref;
- severity;
- state;
- summary;
- created_at;
- acknowledged_at;
- redaction profile;
- target agent/workspace;
- grouping key.

**Lifecycle:**

~~~text
UNREAD
→ SEEN
→ ACKNOWLEDGED
→ RESOLVED or ARCHIVED
~~~

**Rules:**

- Attention Item is presentation-support record, not protocol entity;
- critical never hidden in low-priority aggregation;
- unavailable agent uses durable inbox;
- hide/dismiss/archive/delete semantics distinct.

**Tests:** duplicate event, redaction, agent disconnected, grouping, critical,
ack retry, deleted source.

**Demo:** three canonical events yield one grouped low marker and one critical.

**Зависимости:** M3.3, M2.3, M5.1.

## Slice M5.9 — Orbital Attention Markers

**Цель:** показать pending information around Primary Agent.

**Работы:**

- marker renderer;
- stable orbital slots;
- severity + type channels;
- bounded visible count;
- aggregation marker;
- critical override;
- accessible attention list;
- no camera movement on arrival.

**Acceptance:**

- autonomous event never steals focus;
- unread count accurate after reconnect;
- marker selection opens source context;
- reduced-motion uses static placement;
- color not sole severity cue;
- 1000 queued events do not create 1000 meshes.

**Demo:** events arrive while user edits a frame; camera remains stable.

**Зависимости:** M5.8, M3.5.

## Slice M5.10 — Attention Focus Mode and actions

**Цель:** inspect and resolve attention without moving canonical objects.

**Actions:**

- inspect;
- acknowledge;
- dismiss presentation;
- archive;
- open source;
- propose action;
- SHOW_IN_WORKSPACE;
- return to previous viewport.

**Acceptance:**

- focus translation is temporary;
- return restores camera;
- source unavailable has explicit state;
- destructive action still uses canonical plan/approval path;
- resolving source updates marker through event flow.

**Demo:** select critical marker, inspect Endpoint, apply safe action, return.

**Зависимости:** M5.9, M1.7, M4.5.

## Gate M5

Milestone принят, когда Endpoint discovery, details, Subagent delegation,
provenance, familiarity и autonomous attention работают в одном Workspace
без entity duplicates и focus theft.

# 17. M6 — System Menu, Status and Recovery

Цель milestone: сохранить прямой операторский контроль, даже если Primary
Agent, MCP или WebGL недоступны.

**Реализация:** M6.1–M6.7 verified in the typed frontend/Node adapter seam:
`src/spatial/status/` provides the authoritative snapshot reducer, permanent
System Menu, canonical SHOW_IN_WORKSPACE bridge, and plan-bound recovery
commands. Production probe/command handlers remain explicit Node adapters.

## Slice M6.1 — Node Status Aggregator

**Цель:** собрать authoritative component snapshot без участия LLM.

**Components:**

- Node;
- Hypervisor;
- Primary Agent Slot;
- MCP;
- Hooks;
- Network;
- Consensus;
- Wallet;
- Sessions;
- Tasks;
- Endpoints;
- Providers/Runtimes;
- resources.

**Каждый component status содержит:**

- state;
- source;
- observed_at;
- freshness;
- revision;
- evidence refs;
- optional issue code;
- supported recovery actions.

**State vocabulary:**

~~~text
ONLINE
READY
DEGRADED
OFFLINE
UNKNOWN
STALE
BLOCKED
RESTARTING
~~~

**Acceptance:**

- cached status не выдаётся за current ONLINE;
- partial probe failure не обнуляет весь snapshot;
- status response redacted;
- snapshot revision consistent;
- LLM/Primary Agent не вызывается.

**Demo:** Agent OFFLINE, Hypervisor ONLINE, Hooks DEGRADED в одном snapshot.

**Зависимости:** existing dashboard/readiness services, M2.1.

## Slice M6.2 — Permanent System Menu shell

**Цель:** вынести system entry point из Agent lifecycle.

**Работы:**

- permanent menu control;
- Status;
- Primary Agent;
- Node Settings;
- Appearance;
- Network;
- Wallet;
- Permissions;
- Advanced/Classic;
- renderer fallback;
- mobile bottom sheet;
- keyboard shortcut.

**Acceptance:**

- menu доступно при UNASSIGNED/OFFLINE Agent;
- menu доступно после WebGL error;
- focus trap корректен;
- Escape closes;
- screen reader получает menu semantics;
- direct Classic route remains reachable.

**Demo:** принудительно сломать Agent and canvas, открыть Status.

**Зависимости:** M1.2, M3.5.

## Slice M6.3 — Status Summary

**Цель:** дать компактный factual overview.

**Работы:**

- component rows;
- state label and non-color indicator;
- observed time/freshness;
- warning count;
- drill-down;
- refresh;
- cached/offline marker;
- partial failure.

**Acceptance:**

- summary не становится full dashboard;
- state row is keyboard-focusable;
- UNKNOWN and STALE explicit;
- refresh does not trigger all unrelated mutations;
- mobile viewport remains readable.

**Demo:** summary with 12 components and two warnings.

**Зависимости:** M6.1, M6.2.

## Slice M6.4 — Subsystem Details and raw evidence

**Цель:** раскрыть причину state без разговора с Agent.

**Работы:**

- typed details per subsystem;
- last events;
- health probe evidence;
- connection/runtime identity;
- freshness;
- related entities;
- safe raw evidence;
- copy IDs;
- no secrets/private topology beyond authorization.

**Acceptance:**

- Summary and Details share snapshot revision;
- no invented explanatory text;
- raw evidence is bounded/virtualized;
- inaccessible evidence returns explicit authorization state;
- mobile uses adaptive frame.

**Demo:** open MCP Details from DEGRADED row and inspect last failure.

**Зависимости:** M6.3, Component Registry.

## Slice M6.5 — SHOW_IN_WORKSPACE bridge

**Цель:** вести из factual Status к existing spatial entity.

**Работы:**

- resolve canonical_ref;
- highlight existing presence;
- temporary focus proxy only when allowed;
- Pull-to-Focus request;
- unavailable/stale reference state;
- return to Status.

**Acceptance:**

- no duplicate entity;
- world coordinates unchanged;
- absent spatial representation opens detail frame;
- wrong workspace rejected;
- reduced-motion uses immediate focus/outline.

**Demo:** Status → degraded Endpoint → existing Endpoint object.

**Зависимости:** M5.1, M5.4, M6.4.

## Slice M6.6 — Recovery commands

**Цель:** выполнить ограниченные recovery actions через canonical command
path.

**Initial actions:**

- restart permitted service;
- stop unsafe runtime;
- suspend Agent binding;
- revoke binding credentials;
- disable failing Hook;
- retry Hook dead letter;
- block remote Endpoint;
- return to Classic advanced surface.

**Rules:**

- action plan before apply;
- current revision/plan hash;
- capability and operator authorization;
- confirmation based on consequence;
- audit;
- idempotency;
- result/finality state.

**Acceptance:**

- Status presentation never bypasses command validation;
- stale plan rejected;
- duplicate apply idempotent;
- result updates through live event path;
- destructive action cannot be triggered by remote content.

**Demo:** retry a dead-letter delivery and watch status recover.

**Зависимости:** M6.4, existing lifecycle/approval mechanisms.

## Slice M6.7 — Offline and partial recovery

**Цель:** проверить system behavior при недоступных частях stack.

**Scenarios:**

- Agent offline;
- MCP offline;
- WebGL unavailable;
- Node API partially unavailable;
- browser offline with last snapshot;
- stale snapshot after reconnect;
- authentication expired;
- Node switched while frame open.

**Acceptance:**

- last-known labelled with timestamp;
- no cached mutation;
- retry bounded;
- Classic fallback accessible;
- workspace presentation recovers without losing semantic state;
- old Node data removed on Node switch.

**Demo:** scripted fault injection sequence.

**Зависимости:** M6.1…M6.6.

## Gate M6

Milestone принят, когда Node остаётся наблюдаемой и управляемой без Primary
Agent, а Status и recovery не создают parallel authority.

# 18. M7 — Mediated Remote Resources and Endpoint Test

Цель milestone: разрешить полезную работу с remote Endpoint, сохраняя local
trust boundary и resource accounting.

## Slice M7.1 — Local mediation service

**Цель:** запретить прямой remote transport из Agent и frontend.

**Pipeline:**

~~~text
Intent
→ authorization
→ policy
→ capability validation
→ context minimization
→ Session/accounting setup
→ transport adapter
→ response validation
→ provenance
→ local result
~~~

**Работы:**

- mediation interface;
- endpoint allow/deny;
- transport adapter registry;
- timeout/cancel;
- request size limits;
- correlation ID;
- audit;
- session binding;
- no arbitrary URL from LLM.

**Acceptance:**

- frontend and Agent cannot open remote socket via presentation;
- endpoint address resolved from canonical registry;
- denied endpoint never receives request;
- timeout releases local resources correctly;
- transport error typed.

**Demo:** allowed fixture Endpoint succeeds, unregistered URL is rejected.

**Зависимости:** M4.1, M5.1, existing Endpoint/Session services.

## Slice M7.2 — Context Manifest and minimization

**Цель:** сделать данные, пересекающие trust boundary, явными.

**Manifest:**

- task type;
- endpoint/capability ref;
- allowed text fields;
- attachment refs;
- media types;
- size limits;
- transformation/redaction;
- retention expectation;
- purpose;
- operator consent when required;
- manifest revision/hash.

**Rules:**

- no system prompt by default;
- no unrelated Workspace Sessions;
- no wallet secrets/tokens;
- no hidden browser state;
- attachments content-addressed;
- preview what will be sent for manual tests.

**Tests:** secret pattern, oversized attachment, unsupported MIME, stale
manifest, endpoint capability mismatch, cross-session reference.

**Demo:** STT request sends audio + language hint, no conversation history.

**Зависимости:** M7.1.

## Slice M7.3 — Remote Result Validator

**Цель:** обрабатывать remote output as data, not authority.

**Работы:**

- schema validation;
- MIME validation;
- maximum size;
- streaming bounds;
- sanitization for rendered content;
- prompt-injection classification;
- provenance attachment;
- quarantine/invalid state;
- remote UI payload rejection;
- safe text/markdown rendering.

**Acceptance:**

- instruction-like output does not change Agent policy;
- script/HTML callback not executed;
- malformed stream terminates safely;
- result source Endpoint/request ID visible;
- invalid result remains auditable without unsafe render.

**Demo:** fixture returns prompt injection and script; UI shows quarantined
data.

**Зависимости:** M7.1, M7.2.

## Slice M7.4 — Endpoint Test Frame

**Цель:** дать оператору вручную тестировать выбранный Endpoint.

**Component fields:**

- target Endpoint;
- input schema-derived fields;
- text/media input;
- what-will-be-sent summary;
- Resource Cost/free marker;
- explicit Submit;
- cancel;
- request state;
- response;
- provenance;
- usage/accounting evidence.

**States:** ready, validating, submitting, streaming, complete, cancelled,
timeout, unavailable, invalid result, insufficient deposit, rejected.

**Acceptance:**

- frame created by local planner;
- no auto-submit on open;
- duplicate submit idempotent;
- answer appears in same frame;
- response cannot load remote component;
- keyboard/mobile/screen-reader complete.

**Demo:** test one free text Endpoint and inspect response provenance.

**Зависимости:** M4.4, M5.4, M7.1…M7.3.

## Slice M7.5 — Session and Resource Accounting binding

**Цель:** связать manual/agent request с AiDN Protocol Session и Q evidence.

**Records:**

- Workspace Session ref;
- Protocol Session ref;
- request ID;
- endpoint/rate-card revision;
- free/metered policy;
- input/output units;
- measured usage;
- invoice/settlement evidence;
- result ref;
- status/finality.

**Acceptance:**

- free endpoint records zero cost explicitly;
- metered request displays known estimate/policy before submit;
- Workspace Session remains distinct from Protocol Session;
- settlement event does not clone Endpoint;
- failed request follows defined charge policy;
- UI does not calculate authoritative cost independently.

**Demo:** free request and metered fixture request in one Workspace Session.

**Зависимости:** M7.4, existing accounting/session APIs.

## Slice M7.6 — Remote resource spatial integration

**Цель:** показать selected remote resource and provenance without creating a
remote conversational actor.

**Работы:**

- active Endpoint object;
- request/result pulses;
- provider/remote Node metadata in details;
- local/remote visual distinction;
- source marker in Session;
- SHOW_IN_WORKSPACE;
- no Human ↔ Remote Agent channel.

**Acceptance:**

- remote provider identity is metadata/provenance;
- local Subagent remains distinct actor;
- Endpoint stays one canonical object;
- remote result relation visible;
- unavailable Endpoint does not impersonate agent message.

**Demo:** Primary Agent tests remote Endpoint and presents local result.

**Зависимости:** M5.2…M5.7, M7.4.

## Slice M7.7 — Remote boundary negative suite

**Цель:** сделать security invariants regression-proof.

**Tests:**

- arbitrary remote URL;
- SSRF-style target;
- redirect to disallowed host;
- prompt injection;
- script/HTML payload;
- secret leakage attempt;
- oversized response;
- MIME mismatch;
- duplicate submit;
- replayed response;
- wrong Endpoint revision;
- timeout/cancel race;
- Agent revoked mid-request;
- insufficient authorization;
- cross-Workspace context.

**Acceptance:** каждый case имеет deterministic reject/quarantine/result state
и не оставляет зависший lease/session.

**Зависимости:** M7.1…M7.6.

## Gate M7

Milestone принят, когда оператор через Primary Agent открывает Endpoint Test
Frame, явно отправляет минимальный context, получает validated result и
видит provenance/accounting, при этом remote resource не получает authority.

**Implementation note (2026-09-05):** M7.1–M7.7 are covered by the typed
`web/operator-dashboard/src/spatial/remote/` seam. The local mediation service
resolves canonical Endpoint references, builds a minimized context manifest,
delegates only through an injected Node transport adapter, validates/quarantines
remote output, records provenance/accounting, and exposes the opt-in Endpoint
Test Frame. Production transport, durable audit/replay and settlement handlers
remain Node-owned adapters behind `remoteMediation` clients; the browser never
accepts an arbitrary remote URL or renders remote markup.

# 19. M8 — Spatial Memory, Aging and Clustering

Цель milestone: превратить Workspace в долговременную spatial memory,
которая остаётся понятной при тысячах Sessions.

## Slice M8.1 — Preferred Regions layout engine

**Цель:** реализовать мягкую пространственную организацию.

**Regions:**

- Primary Agent HOME;
- local Agent Space;
- Recent Memory;
- Session Cluster Memory;
- Endpoint Discovery Arc;
- Deep Memory.

**Работы:**

- semantic anchors;
- collision avoidance;
- bounded local placement;
- manual position override;
- pinned state;
- deterministic layout seed;
- reset layout;
- no pixel-fixed zones.

**Acceptance:**

- objects appear in expected semantic region;
- manual move survives reflow;
- Primary Agent remains HOME anchor;
- layout does not rewrite Context Graph;
- mobile uses same anchors with adaptive projection.

**Demo:** materialize mixed set of 25 entities.

**Зависимости:** M2.5, M4.8, M5.

## Slice M8.2 — Recent Memory

**Цель:** держать ограниченный набор свежих Session Artifacts near agent.

**Rules:**

- newest closer to center;
- visible budget configurable, initial 5–10;
- pinned exception explicit;
- overflow moves toward peripheral representation;
- hover/focus reveals labels;
- unresolved attention remains separately represented.

**Acceptance:**

- 100 recent sessions render bounded visible set;
- ordering stable across reload;
- pin/unpin deterministic;
- hidden label accessible via keyboard/list;
- no history deletion.

**Demo:** create 12 sessions and watch bounded Recent Memory.

**Зависимости:** M4.9, M8.1.

## Slice M8.3 — Aging policy

**Цель:** перемещать inactive artifacts в memory depth without deletion.

**Inputs:**

- age;
- inactivity;
- relevance;
- pin weight;
- recent reuse;
- unresolved state;
- branch descendants.

**Lifecycle:**

~~~text
NEW
→ RECENT
→ OLDER
→ CLUSTERED
→ PERIPHERAL
→ VIRTUALIZED
~~~

**Rules:**

- hysteresis prevents visual jitter;
- policy version recorded;
- operator can reset layout;
- important/reused artifact can move closer;
- semantic state unchanged.

**Tests:** clock advance, reuse, pin, unresolved item, policy upgrade,
timezone independence.

**Demo:** deterministic simulated aging timeline.

**Зависимости:** M8.1, M8.2.

## Slice M8.4 — Session Cluster promotion

**Цель:** группировать long-lived context branches.

**Criteria:**

- shared structural parent;
- same project/topic;
- same Endpoint;
- same Agent;
- same Node subsystem;
- semantic similarity;
- manual group.

**Работы:**

- cluster entity as presentation construct;
- criterion/evidence;
- membership revision;
- promote on descendants;
- collapse/expand cluster;
- manual override;
- remove from cluster;
- no protocol entity creation.

**Acceptance:**

- cluster reason inspectable;
- retry does not duplicate membership;
- moving cluster does not move canonical entity identity;
- manual group survives reclassification;
- stale member explicit.

**Demo:** branch A/B/C promoted into Node Debugging cluster.

**Зависимости:** M4.7, M8.3.

## Slice M8.5 — Relation reveal and navigation

**Цель:** показывать graph only on demand.

**Работы:**

- hover/focus cluster region;
- reveal labels;
- structural/context relation styles;
- source/target focus controls;
- semantic relation text;
- offscreen direction;
- accessible relation list.

**Acceptance:**

- default view not covered by graph;
- relation semantics accessible without hover;
- child/parent orientation consistent;
- navigation does not mutate topology;
- dense graph uses bounded visible subset.

**Demo:** reveal one branching Context Graph and traverse keyboard-only.

**Зависимости:** M5.5, M8.4.

## Slice M8.6 — Pull-to-Focus

**Цель:** временно bring distant artifact into current context.

**Lifecycle:**

~~~text
REQUESTED
→ MATERIALIZING
→ FOCUSED
→ RETURNING or PINNED
~~~

**Rules:**

- canonical world position preserved;
- use temporary focus projection;
- target revision visible;
- unavailable target explicit;
- reduced-motion immediate composition;
- return restores prior camera/selection.

**Tests:** offscreen, virtualized, deleted/tombstone, stale revision, repeated
pull, cancel, pin.

**Demo:** pull old artifact from Deep Memory, inspect, return.

**Зависимости:** M5.1, M8.5.

## Slice M8.7 — Spatial virtualization and LOD

**Цель:** ограничить render cost при large Workspace.

**Levels:**

~~~text
LOD0 point/sprite
LOD1 simple translucent shape
LOD2 physical material + semantic marker
LOD3 full detail/particles/relations
~~~

**Работы:**

- viewport culling;
- distance/importance LOD;
- cluster summaries;
- offscreen suspension;
- lazy materialization;
- relation culling;
- DOM list virtualization;
- performance telemetry.

**Acceptance datasets:**

- 10 artifacts;
- 1000 artifacts;
- 20 000 semantic artifacts with bounded rendered subset.

**Acceptance:**

- semantic search/reference works for non-rendered artifact;
- render count bounded;
- no identity change across LOD;
- materialization under defined latency;
- memory released after repeated focus.

**Demo:** 20k fixture, under 30 full visual objects.

**Зависимости:** M8.1…M8.6, M1 quality profiles.

## Slice M8.8 — Search and recall

**Цель:** найти deep artifact через agent intent or System search.

**Работы:**

- metadata search;
- semantic adapter interface;
- result references;
- relevance evidence;
- search result frame;
- focus/pull;
- unavailable/stale handling;
- authorization filter.

**Acceptance:**

- search result is reference, not clone;
- user can inspect why matched;
- unauthorized artifact absent;
- no vector database mandated for MVP;
- deterministic metadata fallback works.

**Demo:** найти вчерашнюю Endpoint debugging Session и Pull-to-Focus.

**Зависимости:** M8.6, M8.7.

## Gate M8

Milestone принят, когда Workspace с большой историей остаётся визуально
ограниченным, а любая разрешённая Session может быть найдена, раскрыта и
возвращена без изменения canonical topology.

**Implementation note (2026-09-05):** M8.1–M8.8 are covered by the typed
`web/operator-dashboard/src/spatial/memory/` projection engine and the
`spatial.memory-*.v1` contracts. Preferred regions, bounded Recent Memory,
UTC aging with hysteresis, explainable clusters, relation reveal,
Pull-to-Focus, LOD/culling telemetry and authorization-filtered metadata search
are verified by the M8 unit/performance fixture and Chromium memory surface.
The `spatial_memory_enabled` flag is opt-in; durable Node persistence,
authorization and semantic search remain production adapter seams.

# 20. M9 — Mobile and Multi-device Workspace

Цель milestone: открыть один semantic Workspace на desktop, tablet и mobile,
сохраняя device-local camera и adaptive presentation geometry.

## Slice M9.1 — Shared semantic state vs device viewport

**Цель:** формально разделить синхронизируемое и локальное состояние.

**Shared:**

- entities;
- relations;
- Session trees;
- clusters;
- semantic anchors;
- pins;
- manual semantic positions.

**Device-local:**

- camera;
- zoom;
- current focus;
- hover/selection;
- opened temporary frames;
- presentation geometry;
- quality profile;
- gesture state.

**Acceptance:**

- second device sees same entity/relation revision;
- camera movement never emits shared mutation;
- local frame close does not close frame elsewhere;
- semantic pin propagates;
- device IDs cannot grant extra authority.

**Demo:** desktop and mobile fixtures on same Workspace with independent
cameras.

**Зависимости:** M2.5, M2.6, M8.1.

## Slice M9.2 — Workspace sync protocol

**Цель:** синхронизировать shared mutations deterministically.

**Contract:**

- workspace revision;
- operation ID;
- idempotency key;
- actor/device;
- base revision;
- operation type;
- target refs;
- conflict category;
- server result revision.

**Rules:**

- stale shared mutation rejected or deterministically merged by explicit rule;
- no silent last-write-wins for topology;
- duplicate operation idempotent;
- device viewport never enters shared operation stream;
- conflict includes current evidence.

**Tests:** concurrent move, concurrent pin, branch creation, cluster edit,
duplicate retry, offline reconnect, removed entity.

**Demo:** two clients create different branches concurrently without loss.

**Зависимости:** M9.1.

## Slice M9.3 — Offline mutation queue

**Цель:** поддержать безопасную работу при временном disconnect.

**Работы:**

- local pending queue;
- operation preview;
- connectivity indicator;
- replay order;
- rebase/reject;
- operator conflict resolution surface;
- discard local operation;
- no offline protocol/resource action.

**Acceptance:**

- presentation-only operations can remain local;
- authoritative Node mutation blocked or explicitly queued by policy;
- reconnect does not duplicate;
- stale conflict visible;
- secret/auth expiry handled before replay.

**Demo:** create local branch offline, reconnect, resolve one conflict.

**Зависимости:** M9.2.

## Slice M9.4 — Mobile navigation controller

**Цель:** управлять тем же Workspace через touch.

**Gestures:**

- one-finger rotate/pan;
- pinch zoom;
- tap select;
- long press empty space create Seed;
- long press entity actions;
- swipe semantic region focus where enabled;
- HOME control;
- cancel current gesture.

**Requirements:**

- touch targets;
- gesture threshold;
- scroll/gesture arbitration;
- orientation change;
- safe-area insets;
- no accidental drag during form input;
- keyboard fallback.

**Acceptance:**

- gesture changes viewport, not topology;
- browser page scroll does not fight intentional spatial interaction;
- long press does not fire after drag;
- one-handed System Menu accessible;
- no hover-only action.

**Demo:** iPhone-class Playwright/WebKit scenario.

**Зависимости:** M1.7, M9.1.

## Slice M9.5 — Adaptive presentation geometry

**Цель:** сохранить semantic position при разных screen sizes.

**Работы:**

- desktop focus frame;
- tablet layout;
- mobile bottom sheet/focus surface;
- responsive Conversation Surface;
- Endpoint Details;
- Endpoint Test Frame;
- Status;
- tables with horizontal/stacked behavior;
- virtual keyboard avoidance.

**Acceptance:**

- identity and relations same across devices;
- frame size not synchronized as world state;
- table remains operable, not clipped;
- keyboard does not hide Submit/Cancel;
- orientation change preserves semantic focus.

**Demo:** same Endpoint Details on 1440px, tablet and narrow mobile.

**Зависимости:** M1.2, M4.6, M5.4, M6.3, M7.4.

## Slice M9.6 — Share View

**Цель:** опционально передать camera/focus другому авторизованному device.

**Rules:**

- explicit action;
- explicit audience;
- temporary session;
- accept/decline;
- no authority transfer;
- no persistent viewport overwrite by default;
- audit of sharing session.

**Acceptance:**

- without Share View cameras remain independent;
- recipient can leave;
- expired share cannot move camera;
- shared focus reference authorization checked;
- reduced-motion recipient may use instant focus.

**Demo:** desktop shares current cluster focus with mobile, mobile exits.

**Зависимости:** M9.2, M9.4, M9.5.

## Slice M9.7 — Multi-device scale and failure suite

**Scenarios:**

- desktop + mobile online;
- one device offline;
- both mutate different branches;
- same entity conflict;
- Agent replacement;
- Workspace revision upgrade;
- viewport recovery;
- stale auth;
- 1000 rendered/reference objects;
- WebGL fallback on one device.

**Acceptance:** semantic consistency and device-local independence preserved
for every scenario.

**Зависимости:** M9.1…M9.6.

## Gate M9

Milestone принят, когда desktop и mobile являются двумя viewports одного
Workspace, но не двигают и не перезаписывают друг друга без Share View.

**Implementation note (2026-09-05):** M9.1–M9.7 are verified in the
flag-gated frontend contract/service seam. `web/operator-dashboard/src/spatial/
multidevice/` provides the shared world/device viewport split, revision-aware
mutation resolver, offline queue, mobile gesture controller, adaptive geometry,
and expiring Share View. Node transport, durable audit, and server-side
authorization remain the typed adapter boundary; see
[`M9.X-MULTI-DEVICE.md`](./M9.X-MULTI-DEVICE.md) and the coverage registry.

# 21. M10 — Agent-mediated Components and Resource Semantics

Цель milestone: превратить существующие Classic pages в reusable Component
Registry и дать Primary Agent возможность показывать и менять реальные
Node capabilities через typed intents.

## Slice M10.1 — Current UI component inventory

**Цель:** разобрать существующий App.tsx по domain ownership.

**Inventory groups:**

- Node/Overview;
- Journey;
- Agents/Primary Agent;
- Bundles;
- Providers/Runtimes/Models;
- Endpoints;
- Sessions;
- Resources;
- Wallet/Q;
- Network/Consensus;
- Validation;
- Settings/Updates;
- Hooks;
- Logs/Events.

**Для каждого fragment записать:**

- canonical entity;
- data source/query key;
- mutations;
- states;
- current component location;
- reusable boundary;
- candidate registry ID;
- Classic-only or shared;
- accessibility gaps;
- test coverage.

**Acceptance:**

- every current App.tsx section assigned;
- no duplicate ownership between domains;
- generated asset path excluded;
- first migration candidates selected by low risk/high reuse.

**Demo:** inventory can trace EndpointConfiguration from API to current JSX.

**Зависимости:** M0.4.

## Slice M10.2 — Registry schema v2 and component lifecycle

**Цель:** расширить M4 registry для production domain components.

**Add:**

- component category;
- minimum data revision;
- mutation intent schema;
- role/capability visibility;
- compact/summary/detail/config variants;
- stream support;
- virtualization requirement;
- viewport constraints;
- feature flag;
- deprecation/removal policy.

**Acceptance:**

- component version migration test;
- unsupported viewport gives fallback;
- planner cannot select configuration variant without capability;
- deprecated registry entry cannot load remote code;
- component states standardized.

**Зависимости:** M4.4, M10.1.

## Slice M10.3 — First shared component: EndpointSummary

**Цель:** доказать shared Component Registry in Classic and Spatial.

**Работы:**

- extract EndpointSummary from current UI;
- feed one typed view model;
- render in Classic Endpoint page;
- render in Spatial frame;
- support loading/empty/stale/offline;
- preserve current Classic behavior behind theme adapter.

**Acceptance:**

- one component implementation;
- no duplicated fetch;
- no visual regression in Classic;
- Spatial uses ADR-013 material profile;
- same revision/provenance displayed.

**Demo:** same Endpoint opened from Classic route and Spatial Agent.

**Зависимости:** M10.2, M5.4.

## Slice M10.4 — EndpointConfiguration and Change Intent

**Цель:** доказать shared mutation path.

**Change Intent contains:**

- target type/id/revision;
- current values;
- proposed values;
- field schema;
- actor;
- intent ID;
- idempotency key;
- optional natural-language summary.

**Flow:**

~~~text
form or voice
→ Change Intent
→ Primary Agent validation/planning
→ MCP canonical operation
→ Hypervisor revalidation
→ result event
→ component update
~~~

**Scenarios:** port change, occupied port, stale revision, unauthorized field,
Agent offline, direct Classic manual fallback.

**Acceptance:**

- form and voice create same semantic change;
- LLM does not parse values already known by form;
- stale/occupied rejected with alternatives;
- apply requires explicit action;
- audit and result revision visible.

**Demo:** change Endpoint port from Spatial and inspect same value in Classic.

**Зависимости:** M4.1, M4.5, M10.3.

## Slice M10.5 — Query-driven component composition

**Цель:** поддержать show/compare/explain flows.

**Initial intents:**

- show all Endpoints;
- inspect one Endpoint;
- compare Endpoints;
- show Node resources;
- explain current Agent status;
- show recent Sessions;
- show Hook failures.

**Components:**

- EndpointList;
- EndpointComparison;
- NodeResourceSummary;
- AgentDetails;
- SessionList;
- HookDeliverySummary.

**Acceptance:**

- planner chooses minimum useful composition;
- repeated query reuses frame;
- detail request transforms/extends existing frame;
- large list virtualized;
- data always authoritative.

**Demo:** show all Endpoints → focus Parakeet → show details.

**Зависимости:** M10.2…M10.4.

## Slice M10.6 — Q and Resource terminology

**Цель:** привести new UI к resource semantics ADR-011.

**Canonical terms:**

| Avoid | Use |
| --- | --- |
| Money | Resources / Compute Units |
| Income | Resource Contribution |
| Spending | Resource Usage |
| Revenue | Contribution Credit |
| Payment | Resource Settlement |
| Price | Resource Cost |
| Earnings | Contribution Credits |

**Работы:**

- copy dictionary;
- i18n keys;
- API field mapping without protocol rename;
- tooltips explaining Q;
- zero/free state;
- metered unit labels;
- consistency lint/review checklist.

**Acceptance:**

- no implication that Q is fiat currency;
- exact q_atoms available in details;
- formatted Q does not lose integer evidence;
- translation preserves semantic distinction.

**Demo:** Resource Cost and Settlement History in English/Russian fixtures.

**Зависимости:** M10.2.

## Slice M10.7 — Resource components

**Components:**

- ResourceBalance;
- ResourceUsage;
- ResourceCostEditor;
- ResourceContributionChart;
- SettlementHistory;
- DepositStatus;
- UsageEvidence;
- DisputeStatus.

**Rules:**

- browser never computes authoritative invoice;
- chart derived from canonical events;
- free vs unknown vs zero distinct;
- q_atoms exact value inspectable;
- endpoint rate-card revision shown;
- no decorative fake telemetry.

**Acceptance:**

- loading/empty/stale/disputed/finality-pending states;
- table/chart accessible alternative;
- mobile responsive;
- large history virtualized;
- one component works Classic + Spatial.

**Demo:** inspect usage and settlement for one Protocol Session.

**Зависимости:** M7.5, M10.6.

## Slice M10.8 — Progressive Classic decomposition

**Цель:** продолжить extraction без big-bang rewrite.

**Recommended order:**

1. Status and OperationNotice;
2. EndpointSummary/Configuration;
3. Agent/Hook status;
4. Resource/Wallet summaries;
5. Sessions;
6. Providers/Runtimes;
7. Network/Consensus;
8. Bundle/Journey complex surfaces.

**Per-component migration:**

- extract schema/view model;
- add tests;
- render Classic;
- register Spatial variant;
- remove old inline implementation;
- remove temporary compatibility export;
- update inventory.

**Acceptance:**

- no two authoritative components for same operation;
- App.tsx line count and responsibility shrink each train;
- old inline implementation removed after replacement;
- no unused legacy CSS/API.

**Demo:** inventory shows migrated ownership and deleted duplicate code.

**Зависимости:** M10.1…M10.7.

## Slice M10.9 — Agent action feedback and partial completion

**Цель:** сделать configure/start/stop/diagnose actions legible.

**States:**

- proposed;
- needs clarification;
- awaiting approval;
- executing;
- partially completed;
- completed;
- rejected;
- rolled back where supported;
- finality pending.

**Acceptance:**

- hidden chain-of-thought never required;
- user sees action/effect/evidence;
- partial result lists completed and remaining;
- failure offers safe next action;
- attention created when operator can leave.

**Demo:** multi-step Endpoint change partially fails and remains recoverable.

**Зависимости:** M4.5, M5.8, M6.6, M10.4.

## Gate M10

Milestone принят, когда Primary Agent может показать и изменить реальную
Endpoint configuration через shared components, а Classic UI использует тот
же schema/control path и остаётся полноценным fallback.

**Implementation note (2026-09-05):** M10.1–M10.9 now have typed frontend
seams and coverage entries. The Classic inventory, Registry v2 lifecycle
metadata, shared EndpointSummary/EndpointConfiguration, Change Intent service,
bounded query composition, exact q_atoms/resource terminology, and action
feedback transitions live under `web/operator-dashboard/src/`. The
`spatial_change_intent_enabled` flag remains off by default; canonical command
translation, Hypervisor revalidation, audit and durable resource events remain
Node-owned adapters. See [`M10-AGENT-MEDIATED-COMPONENTS.md`](./M10-AGENT-MEDIATED-COMPONENTS.md)
and [`IMPLEMENTATION-COVERAGE.md`](./IMPLEMENTATION-COVERAGE.md).

# 22. M11 — Hardening, Evaluation and Rollout

Цель milestone: довести Spatial UI от функционального prototype до
контролируемого operator preview.

## Slice M11.1 — Authorization and audit review

**Scope:**

- operator browser session;
- Primary Agent grants;
- MCP tools;
- Hooks;
- Workspace mutations;
- remote mediation;
- recovery actions;
- resource actions;
- Share View.

**Работы:**

- permission matrix;
- confused-deputy tests;
- actor attribution;
- revision/idempotency review;
- secret redaction;
- audit retention;
- failed action evidence;
- capability revocation propagation.

**Acceptance:** no presentation object grants authority; every Node mutation
has an actor, target, revision, decision and result.

**Зависимости:** all functional milestones.

## Slice M11.2 — Accessibility conformance

**Проверки:**

- keyboard-only full primary flow;
- screen-reader semantic entity list;
- focus order;
- focus return;
- status text;
- color independence;
- 200% zoom;
- high contrast/forced colors;
- reduced motion;
- reduced transparency;
- touch targets;
- live region streaming rate;
- form errors and instructions.

**Primary flow:**

~~~text
open Workspace
→ inspect Agent
→ create Interaction
→ inspect Endpoint
→ submit test
→ view result
→ open Status
→ return HOME
~~~

**Acceptance:** no blocking issue in primary/recovery flows.

**Зависимости:** M1…M10.

## Slice M11.3 — Localization and content hardening

**Работы:**

- extract UI strings;
- English/Russian catalogs;
- pluralization;
- number/Q formatting;
- timestamps/timezones;
- long labels;
- RTL readiness assessment;
- technical IDs remain copyable;
- error code + human explanation;
- no machine-translated protocol terminology at runtime.

**Acceptance:**

- no clipped Russian labels in mobile;
- Q/resource semantics consistent;
- errors retain stable code;
- screen reader language correct.

**Зависимости:** Component Registry and major surfaces.

## Slice M11.4 — Performance and thermal hardening

**Profiles:** low, mobile, desktop, high.

**Measurements:**

- initial JS/CSS/WebGL chunk;
- time to interactive;
- first spatial frame;
- steady FPS;
- 95th percentile frame;
- memory growth;
- idle CPU/GPU;
- thermal behavior mobile;
- event burst;
- 20k semantic artifact dataset;
- long Conversation DOM;
- repeated canvas mount/unmount.

**Optimizations only after evidence:**

- LOD tuning;
- InstancedMesh batching;
- relation culling;
- query select/memoization;
- worker for expensive layout if measured;
- spatial index after threshold;
- opaque material fallback;
- disable post-processing.

**Acceptance:** budgets documented per supported device class; unsupported
profile falls back without losing control.

**Зависимости:** M8.7, M9, M10.

## Slice M11.5 — Reliability and chaos scenarios

**Faults:**

- WebSocket disconnect/reorder/duplicate;
- API partial outage;
- Agent dies mid-request;
- Agent replaced mid-stream;
- Hook retry/dead letter;
- Workspace write conflict;
- corrupt presentation state;
- stale Status;
- Endpoint timeout;
- remote malicious output;
- browser sleep/wake;
- Node switch;
- renderer context loss.

**Acceptance:**

- no silent data loss;
- no incorrect green status;
- no duplicate charge/action;
- recovery path visible;
- Classic fallback available;
- renderer can rebuild projections from canonical state.

**Зависимости:** M2…M10.

## Slice M11.6 — Privacy and data lifecycle

**Работы:**

- classify Workspace data;
- retention policy hooks;
- export format;
- archive vs delete;
- attachment lifecycle;
- transcript/redaction;
- browser cache policy;
- diagnostics redaction;
- remove presentation-only data;
- ensure protocol evidence not deleted by UI cleanup.

**Acceptance:**

- Archive/Delete semantics explicit;
- user export preserves references/revisions;
- presentation GC cannot erase settlement/evidence;
- remote manifest records disclosed fields;
- secrets absent from exported UI state.

**Зависимости:** M4, M7, M8.

## Slice M11.7 — Observability

**Metrics:**

- renderer init/fallback;
- frame performance buckets;
- event lag/reconnect;
- schema rejection;
- view-model failure;
- duplicate entity prevention;
- planner rejection;
- attention backlog;
- Workspace conflicts;
- remote validation/quarantine;
- component error boundary;
- user fallback to Classic.

**Rules:**

- no prompts, tokens, private text or secrets in metrics;
- correlation IDs allow tracing local operation;
- cardinality bounded;
- telemetry opt/policy aligned.

**Acceptance:** one operator scenario traceable from intent to final result
without exposing content.

**Зависимости:** all main paths.

## Slice M11.8 — Visual regression and design acceptance

**Matrix:**

- desktop/mobile;
- normal/high contrast;
- normal/reduced motion;
- backdrop-filter/fallback;
- READY/WORKING/CRITICAL/OFFLINE;
- empty/loading/stale/error;
- 1/7/100 endpoints;
- short/long conversation;
- System Menu and recovery;
- Entity Details/Test Frame.

**Acceptance:**

- ADR-013 tokens only;
- no unreadable glass-on-white;
- DOM/3D material continuity;
- no neon/bloom washout;
- no text rendered as WebGL substitute;
- no unreviewed arbitrary shadow/radius.

**Зависимости:** M1…M10.

## Slice M11.9 — Operator preview rollout

**Stages:**

1. developer-only route;
2. local fixture mode;
3. single test Node;
4. selected LAN Nodes;
5. opt-in operator preview;
6. default-on for supported profiles;
7. Classic remains Advanced/Recovery until separate decision.

**Per-stage gates:**

- error budget;
- rollback;
- data compatibility;
- migration/rebuild;
- operator feedback;
- performance evidence;
- security sign-off.

**Acceptance:**

- disable flag returns usable Classic UI;
- Workspace schema migration reversible or rebuildable;
- generated assets installed atomically;
- no Node protocol upgrade required solely for visual rollout unless declared.

**Зависимости:** M11.1…M11.8.

## Slice M11.10 — Classic UI migration decision

**Цель:** определить, что остаётся permanent expert fallback.

**Review:**

- which pages fully share components;
- which actions still need direct manual controls;
- recovery requirements;
- accessibility parity;
- support burden;
- legacy code removal candidates;
- documentation/user guide.

**Rules:**

- no dead legacy implementation retained after replacement;
- no removal before parity and rollback evidence;
- generated assets not treated as source;
- one canonical API/control path remains.

**Deliverable:** отдельный ADR/decision, not an implicit cleanup commit.

**Зависимости:** operator preview evidence.

## Gate M11

Spatial UI может называться operator preview, когда все blocking security,
reliability, accessibility and performance gates пройдены, а rollback в
Classic UI проверен на реальной test Node.

**Implementation note (2026-09-06):** M11.1–M11.10 browser-side hardening
contracts and gates are implemented under
`web/operator-dashboard/src/spatial/hardening/`; additive schema IDs are listed
in `IMPLEMENTATION-COVERAGE.md`. The frontend has deterministic unit evidence
for authorization/audit, fault recovery, accessibility/localization,
performance profiles, privacy/export, bounded telemetry, staged rollout and
the Classic migration decision. The Gate M11 remains intentionally open until
the same rollback is exercised against a real test Node with Node-owned
persistence and audit adapters.

# 23. Рекомендуемый порядок выполнения слайсов

Порядок ниже является dependency order, а не календарным обещанием.

## Wave 0 — Подготовка

~~~text
M0.1 Coverage registry
M0.2 Frontend tests
M0.3 Feature flag
M0.4 App seams
M0.5 Spatial dependencies
~~~

## Wave 1 — Быстрый visual proof

~~~text
M1.1 Tokens
M1.2 Primitives
M1.3 Hybrid shell
M1.4 Environment
M1.5 Agent prototype
M1.6 Mock entities
M1.7 Camera
M1.8 UX/performance gate
~~~

## Wave 2 — Канонический data spine

~~~text
M2.1 Schemas
M2.2 Domain clients
M2.3 Live events
M2.4 View models
M2.5 Workspace model
M2.6 Workspace API
M2.7 Connected scene
~~~

## Wave 3 — Первый полезный vertical product path

~~~text
M3.1–M3.6 Primary Agent
M4.1–M4.10 Interaction, conversation, Context Graph, objects, collapse, voice
~~~

Результат Wave 3:

~~~text
operator opens Spatial UI
→ sees real Primary Agent state
→ creates text interaction
→ agent receives it through durable path
→ typed response appears in DOM frame
~~~

## Wave 4 — Sessions and real Endpoint inspection

~~~text
M4.1–M4.10 frontend interaction slice complete; Node-backed persistence seam
M5.1 Canonical references
M5.2 Endpoint object
M5.3 Discovery Arc
M5.4 Endpoint Details
M5.5 Semantic threads
~~~

## Wave 5 — Agent work and operator attention

~~~text
M5.6 Subagents
M5.7 Familiarity
M5.8 Attention projection
M5.9 Orbit
M5.10 Focus/actions
~~~

## Wave 6 — Recovery and remote resources

M6 Status/Recovery и M7 Remote Mediation могут выполняться параллельно после
общего data/registry foundation, но Gate M7 требует работающего Status для
unavailable и blocked states.

## Wave 7 — Long-lived Workspace

~~~text
M8 Spatial Memory
→ M9 Multi-device
→ M10 Shared components/resources
~~~

Некоторые M10 inventory/extraction tasks можно начинать после M0.4, но
production mutation components принимаются после Typed Intent и canonical
command path.

## Wave 8 — Preview

~~~text
M11 Security
M11 Accessibility
M11 Performance
M11 Reliability
M11 Privacy
M11 Observability
M11 Visual acceptance
M11 Rollout
~~~

# 24. Рекомендуемый размер pull request

Один PR SHOULD:

- закрывать один numbered slice или его явно названную часть;
- иметь до одного нового cross-layer contract;
- не смешивать visual redesign и backend mutation semantics;
- не смешивать refactor с новым behavior без characterization tests;
- удалять заменённый локальный legacy path в том же или следующем
  строго связанном PR;
- содержать demo steps;
- перечислять ADR invariants;
- иметь rollback note.

Слайс следует разбить, если PR одновременно:

- меняет schema storage;
- добавляет новый transport;
- перестраивает App shell;
- вводит новую 3D entity;
- мигрирует несколько Classic pages;
- добавляет remote security boundary.

## T-shirt sizing

| Size | Ориентир |
| --- | --- |
| S | один layer, существующий contract, локальные tests |
| M | frontend + adapter или backend + schema, один demo flow |
| L | end-to-end vertical path, migration, fault tests |
| XL | необходимо разрезать до начала реализации |

# 25. ADR coverage matrix

| ADR | Основные implementation slices | Главный acceptance proof |
| --- | --- | --- |
| ADR-001 | M3.1–M3.6 | replace/detach Agent без потери Workspace/inbox |
| ADR-002 | M2.5–M2.7, M6.7, M9.1 | Node-owned Workspace переживает Agent failure |
| ADR-003 | M5.8–M5.10 | autonomous event заметен без focus theft |
| ADR-004 | M1.5, M3.4–M3.5, M11.2 | state channels, OFFLINE, reduced motion |
| ADR-005 | M1.6, M5.2–M5.6, M7.6 | Agent/Endpoint/Artifact distinct, Arc/details/thread |
| ADR-006 | M4.2–M4.10 | branch tree, context refs, collapse/restore |
| ADR-007 | M8.1–M8.8 | aging/clustering/20k virtualization |
| ADR-008 | M5.1, M5.7, M6.5, M8.6 | one primary presence, provenance over clone |
| ADR-009 | M9.1–M9.7 | same semantic world, independent viewports |
| ADR-010 | M6.1–M6.7 | Status/recovery works without Agent/renderer |
| ADR-011 | M4.1, M4.4–M4.5, M10.1–M10.9 | shared component and Change Intent |
| ADR-012 | M7.1–M7.7 | no direct remote authority/context leakage |
| ADR-013 | M1.1–M1.2, M11.2, M11.8 | tokenized readable DOM/3D material system |
| ADR-014 | M0.5, M1, M2, M11.4 | hybrid renderer and typed data boundary |

# 26. Contract inventory

Перед реализацией соответствующего слайса должны появиться versioned
contracts.

## 26.1. Identity and scope

- NodeRef;
- WorkspaceRef;
- CanonicalEntityRef;
- AgentIdentityRef;
- PrimaryAgentSlotRef;
- BindingRef;
- DeviceRef;
- OperatorRef.

## 26.2. Revision and mutation

- Revision;
- BaseRevision;
- IdempotencyKey;
- OperationId;
- PlanHash;
- ActorContext;
- AuditReference;
- ConflictResult.

## 26.3. Workspace

- WorkspaceSnapshot;
- WorkspaceOperation;
- SemanticAnchor;
- PresentationProjection;
- ViewportState;
- ClusterRecord;
- RelationRecord;
- FocusRequest.

## 26.4. Agent

- PrimaryAgentSlot;
- AgentBinding;
- CapabilityGrant;
- HookSubscriptionRef;
- AgentOperationalState;
- AgentHealthEvidence;
- AgentInboxCursor.

## 26.5. Interaction

- IntentEnvelope;
- PresentationIntent;
- ResultModel;
- ChangeIntent;
- AttachmentManifest;
- ConversationTurn;
- GeneratedObject;
- WorkspaceSession;
- ContextReference.

## 26.6. Entity and provenance

- EntityViewModel;
- EndpointViewModel;
- SessionArtifactViewModel;
- InteractionProvenance;
- FamiliarityRecord;
- RevisionSnapshot;
- AvailabilityEvidence.

## 26.7. Attention

- AttentionItem;
- AttentionGroup;
- AttentionMarkerProjection;
- AttentionLifecycleOperation;
- FocusModeState.

## 26.8. Status

- NodeStatusSnapshot;
- ComponentStatus;
- Freshness;
- EvidenceReference;
- RecoveryPlan;
- RecoveryResult.

## 26.9. Remote resource

- RemoteOperationIntent;
- ContextManifest;
- TransportRequest;
- RemoteResultEnvelope;
- ValidationResult;
- QuarantineRecord;
- EndpointTestState.

## 26.10. Resource accounting

- ResourceCost;
- RateCardReference;
- UsageMeasurement;
- ProtocolSessionReference;
- InvoiceReference;
- SettlementEvidence;
- DepositStatus.

# 27. Event taxonomy

Event names require stable namespace and schema version. Initial groups:

~~~text
workspace.created
workspace.operation_applied
workspace.conflict
workspace.presentation_reset

agent.slot_created
agent.binding_started
agent.bound
agent.disconnected
agent.revoked
agent.state_changed

interaction.created
interaction.submitted
interaction.response_started
interaction.response_completed
interaction.failed

session.workspace_created
session.branch_created
session.collapsed
session.restored

entity.discovered
entity.reference_updated
entity.unavailable
endpoint.state_changed

attention.created
attention.acknowledged
attention.resolved
attention.archived

status.snapshot_changed
recovery.plan_created
recovery.applied

remote.request_started
remote.result_validated
remote.result_quarantined
remote.request_failed

resource.usage_recorded
resource.settlement_pending
resource.settled
~~~

Каждый event содержит:

- event_id;
- event_type;
- schema_version;
- node_id;
- sequence or revision;
- occurred_at;
- actor/source;
- resource_id where applicable;
- severity;
- redacted payload;
- correlation/idempotency reference.

# 28. Test strategy

## 28.1. Unit tests

Покрывают:

- Zod parsers;
- reducers/state machines;
- view-model derivation;
- layout policy;
- LOD selection;
- attention grouping;
- familiarity counters;
- context graph cycle checks;
- revision conflict rules;
- resource formatting;
- permission decisions.

## 28.2. Component tests

Покрывают:

- loading/empty/stale/error/success;
- keyboard focus;
- screen-reader names;
- reduced motion;
- mobile geometry;
- explicit submit;
- disabled reason;
- planner registry rejection;
- Classic/Spatial shared component parity.

## 28.3. R3F renderer tests

Покрывают:

- entity identity;
- picking;
- material state mapping;
- LOD;
- camera HOME/focus/return;
- focus cancellation;
- context loss fallback;
- bounded entity counts.

Pixel-perfect snapshots не заменяют semantic assertions.

## 28.4. Backend contract tests

Покрывают:

- Workspace persistence/revisions;
- Primary Agent binding;
- Hook/inbox lifecycle;
- status freshness;
- remote context manifest;
- result validation;
- resource/session links;
- audit/redaction.

## 28.5. Integration tests

Покрывают end-to-end:

- event → query cache → view model → renderer;
- Interaction Seed → Agent inbox → response → Session;
- Endpoint Test → mediation → result → accounting;
- Status → recovery → live update;
- multi-device conflict/reconnect;
- Agent replacement mid-flow.

## 28.6. E2E

Playwright projects:

- Chromium desktop;
- WebKit desktop;
- Chromium mobile;
- WebKit mobile;
- reduced motion;
- high contrast/forced colors where supported;
- WebGL disabled fallback.

## 28.7. Visual regression

Only stable states:

- environment baseline;
- material primitives;
- Agent states;
- Endpoint states;
- Session Artifact;
- Attention Orbit;
- Conversation Surface;
- Endpoint Details/Test;
- Status/Recovery;
- mobile focus surface.

Анимация freeze'ится на deterministic timestamp.

## 28.8. Security tests

- authorization;
- cross-Node references;
- cross-Workspace context;
- arbitrary component;
- arbitrary style/shader/script;
- remote injection;
- secret leakage;
- SSRF/redirect;
- replay/duplicate;
- stale revision;
- revoked Agent.

## 28.9. Performance tests

- 10/1000/20k Workspace data;
- event burst;
- long transcript;
- 100 Endpoint candidates;
- mount/unmount cycles;
- mobile DPR;
- background tab;
- network reconnect;
- low profile.

# 29. Fixture and demo environments

## 29.1. Pure frontend fixture mode

Назначение: visual/interaction work без Hypervisor.

Должен иметь:

- deterministic Node snapshot;
- scripted event stream;
- Agent state controls;
- Endpoint variants;
- Context Graph fixture;
- 20k memory dataset;
- remote malicious result fixtures;
- clock control;
- network disconnect toggle.

## 29.2. Local integrated Node

Назначение: API, MCP, Hooks, Workspace persistence, Status and recovery.

Requirements:

- no public network dependency;
- test Agent binding;
- test Endpoint;
- disposable data directory;
- repeatable bootstrap.

## 29.3. LAN test Node

Назначение: browser pairing, mobile devices, real GPU/browser variance,
operator preview.

## 29.4. Mini testnet

Назначение: remote discovery, Protocol Sessions, accounting, remote failure,
multi-Node provenance.

## 29.5. Demo evidence per PR

Каждый visual/interaction PR прикладывает:

- route;
- fixture/state;
- desktop screenshot or short recording;
- mobile screenshot when affected;
- keyboard path;
- error/offline state;
- performance observation when R3F changed.

# 30. Storage, migrations and compatibility

## 30.1. Schema versioning

Workspace, Agent Binding, Session Graph, Attention and Provenance records
имеют независимые schema versions.

## 30.2. Migration rules

- migration deterministic;
- backup/checkpoint before destructive transform;
- unknown future fields preserved where safe;
- migration failure leaves previous state readable;
- presentation state may be rebuilt;
- canonical protocol/economic evidence is never regenerated from UI.

## 30.3. Rollback

- feature flag disables Spatial route;
- Classic UI continues to use canonical APIs;
- new backend records remain ignored safely by old UI;
- generated assets activate atomically;
- no rollback requires deleting Node identity, wallet, sessions or ledger.

## 30.4. Legacy removal

После завершения replacement slice:

1. prove parity;
2. switch all callers;
3. remove old inline implementation;
4. remove compatibility export;
5. remove obsolete CSS/test fixtures;
6. verify no route imports it;
7. update inventory and docs.

Неиспользуемый legacy path не сохраняется «на всякий случай».

# 31. Основные риски и способы ограничения

## Risk 1 — App monolith grows

**Mitigation:** M0.4, feature modules, registry ownership, no new screens in
App.tsx.

## Risk 2 — Renderer becomes authority

**Mitigation:** M2 contracts/view models, no fetch in entities, command path
tests.

## Risk 3 — Spatial novelty harms operation

**Mitigation:** Classic fallback, Status independent, component parity,
operator preview.

## Risk 4 — White glass loses readability

**Mitigation:** contrast tokens, opaque fallback, high contrast, visual gate.

## Risk 5 — Mobile overheats

**Mitigation:** profiles, DPR cap, InstancedMesh, no DoF, idle suspension,
thermal tests.

## Risk 6 — Agent creates chaotic UI

**Mitigation:** registry, bounded planner, reuse/update rules, max objects,
presentation GC.

## Risk 7 — Entity duplication

**Mitigation:** canonical reference registry, projection kinds, duplicate
telemetry, tests.

## Risk 8 — Remote output controls local agent

**Mitigation:** mediation, context manifest, untrusted result validator,
negative suite.

## Risk 9 — Multi-device lost updates

**Mitigation:** revision/idempotency, explicit conflicts, device-local
viewport, no silent LWW.

## Risk 10 — Status depends on Agent

**Mitigation:** direct aggregator/probes, cached freshness, permanent System
Menu.

## Risk 11 — Workspace history becomes unbounded

**Mitigation:** semantic persistence + visual virtualization, clustering,
search, bounded render counts.

## Risk 12 — Q looks like banking UI

**Mitigation:** resource terminology, exact evidence, no financial claims or
decorative revenue framing.

# 32. Первый implementation batch

Первый batch должен закончиться наблюдаемым Prototype A и безопасной базой.
Рекомендуемая серия PR:

## PR-01 — Coverage and frontend tests

- M0.1;
- M0.2 foundation;
- no UI behavior change.

## PR-02 — App shell seams

- M0.3;
- first half M0.4;
- characterization tests.

## PR-03 — API/type domain split

- second half M0.4;
- query key factory;
- no transport behavior change.

## PR-04 — Spatial dependencies and lazy route

- M0.5;
- empty feature-flagged route;
- bundle report.

## PR-05 — Spatial design tokens

- M1.1;
- fixture gallery;
- contrast/fallback tests.

## PR-06 — DOM primitives

- M1.2;
- keyboard/reduced-motion tests.

## PR-07 — Hybrid shell

- M1.3;
- error boundary;
- pointer/focus tests.

## PR-08 — Atmospheric environment

- M1.4;
- capability profiles;
- performance baseline.

## PR-09 — Primary Agent prototype

- M1.5;
- mock state controls;
- accessibility semantics.

## PR-10 — Entity grammar

- M1.6;
- mock Endpoints/Subagents/Artifacts/Attention;
- picking and LOD.

## PR-11 — Camera/navigation

- M1.7;
- HOME/focus/return;
- desktop/mobile controls.

## PR-12 — Prototype A acceptance

- M1.8;
- desktop/mobile evidence;
- performance and design decision;
- backlog corrections before M2.

Нельзя начинать real Workspace persistence, Agent Slot или remote transport
до Prototype A gate, если gate выявил необходимость сменить renderer
architecture.

# 33. Второй implementation batch

После Gate M1:

1. M2.1 schemas;
2. M2.2 domain clients/query keys;
3. M2.3 event adapter;
4. M2.4 view models;
5. M2.5 Workspace model;
6. M2.6 Workspace API;
7. M2.7 connected scene;
8. M3.1 Primary Agent Slot;
9. M3.2 binding API;
10. M3.3 hooks/inbox;
11. M3.4 operational state;
12. M3.5 live Presence;
13. M3.6 management surface.

Итог второго batch: typed Node data path, Node-owned Workspace seam,
mock-real live state и готовые adapters для Primary Agent Slot; production
Agent binding теперь закрыт M3, а conversation/context UX закрыт M4.

# 34. Третий implementation batch

После Gate M3 (M4 batch verified):

1. M4.1 Typed Intent;
2. M4.2 Interaction Seed;
3. M4.3 durable conversation;
4. M4.4 Registry;
5. M4.5 Planner;
6. M4.6 Conversation Surface;
7. M4.7 Context Graph;
8. M4.8 Generated Objects;
9. M4.9 collapse/restore;
10. M4.10 voice.

Итог третьего batch: первая полноценная human ↔ local Primary Agent
Workspace Session.

# 35. Контрольные продуктовые демо

## Demo A — Spatial Core

White environment, Primary Agent, entities, attention, focus and mobile
navigation без backend.

## Demo B — Typed Node Presence

Mock-real Node snapshot обновляет Agent/Endpoint states через typed event
pipeline; production transport подключается через те же adapters.

## Demo C — Durable Conversation

User creates Seed, Agent receives event, response streams, reload preserves
Session.

## Demo D — Context Branch

Conversation collapses into Artifact; user continues two branches and adds
external context reference.

## Demo E — Discovery

Agent finds Endpoints, Arc ranks candidates, user inspects and selects one.

## Demo F — Attention

Autonomous critical event creates marker without moving camera; operator
focuses, resolves and returns.

## Demo G — Recovery

Primary Agent and WebGL are unavailable; System Menu shows factual status and
runs authorized recovery.

## Demo H — Remote Endpoint Test

Agent opens Test Frame; user reviews context, submits; validated result and
Resource evidence return locally.

## Demo I — Long Memory

Workspace contains 20k semantic artifacts; recent/cluster/deep memory and
Pull-to-Focus remain bounded.

## Demo J — Multi-device

Desktop and mobile show same entities with independent cameras; explicit
Share View works.

## Demo K — Shared Configuration

EndpointConfiguration is the same component in Classic and Spatial; form and
voice produce same Change Intent.

## Demo L — Operator Preview

Full primary flow on a test Node with fault injection, accessibility and
performance evidence.

# 36. Milestone exit checklist

Перед закрытием любого milestone:

- all planned slices accepted;
- ADR matrix updated;
- unresolved decisions moved to OPEN-QUESTIONS or new ADR;
- no critical/high security finding;
- no blocking accessibility finding;
- performance baseline recorded;
- Classic fallback tested;
- upgrade/rollback tested when storage/API changed;
- generated dashboard built atomically;
- docs index regenerated;
- demo evidence reviewed by operator;
- next milestone inputs satisfy Definition of Ready.

# 37. Что сознательно не входит в initial roadmap

- WebGPU-first renderer;
- volumetric clouds;
- physics engine;
- VR/AR;
- remote agent as direct human chat counterpart;
- arbitrary LLM-generated HTML/CSS/JavaScript/shaders;
- full replacement of Classic UI before parity;
- global reputation implementation;
- final DAO/governance UI;
- new Q economics rules beyond already canonical protocol;
- mandatory vector database;
- global CRDT without proven need;
- hidden always-on microphone;
- direct browser ownership of protocol state.

Эти направления требуют отдельного decision и не должны проникать в MVP как
«маленькая удобная доработка».

# 38. Итоговая последовательность продукта

~~~text
Safe Classic baseline
        ↓
Feature-flagged Spatial Core
        ↓
Typed Node data and Workspace
        ↓
Node-scoped Primary Agent
        ↓
Durable interaction and Context Graph
        ↓
Endpoints, Subagents, Provenance and Attention
        ↓
Status and Recovery
        ↓
Mediated Remote Resources
        ↓
Spatial Memory and Multi-device
        ↓
Shared Component Registry and Resource UX
        ↓
Hardening and Operator Preview
~~~

Roadmap считается выполненным не тогда, когда нарисованы все объекты, а
когда оператор может безопасно управлять реальной Node через Primary Agent,
понимать фактическое состояние без агента, использовать local/remote
resources через один канонический path и восстановиться после отказа без
потери Workspace или protocol evidence.
