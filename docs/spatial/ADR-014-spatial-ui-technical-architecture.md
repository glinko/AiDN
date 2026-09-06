# ADR-014 — Spatial UI Technical Architecture and Rendering Boundary

**Статус:** Accepted  
**Дата решения:** 2026-09-04  
**Область:** Spatial Agent Interface, frontend runtime, rendering, state, data adapters, performance  
**Связанные решения:** [ADR-008 — Entity Uniqueness and Provenance References](./ADR-008-entity-uniqueness-and-provenance.md), [ADR-009 — Multi-Device Workspace and Mobile Spatial Navigation](./ADR-009-multi-device-workspace-and-mobile-navigation.md), [ADR-011 — Agent-Mediated Component Interface](./ADR-011-agent-mediated-component-interface.md), [ADR-012 — Local Trust Boundary and Mediated Remote Resource Access](./ADR-012-local-trust-boundary-and-mediated-remote-resources.md), [ADR-013 — AiDN Milky Glass Neumorphism Visual Design System](./ADR-013-aidn-milky-glass-neumorphism-visual-design.md)  
**Исходный план:** [AiDN Spatial Agent Interface — Implementation Plan](./AiDN-Spatial-Agent-Interface-Implementation-Plan.md)

## Решение

Spatial UI строится как hybrid React/DOM + React Three Fiber/Three.js
приложение. Three.js отвечает за пространственность и lightweight entities,
а React DOM отвечает за информацию, формы, текст и управление.

Главное правило:

~~~text
Three.js creates space.
React DOM creates interface.
Neither renderer competes for the other's work.
~~~

3D-слой упрощается до high-key atmospheric environment и набора физических
материалов. Volumetric clouds, тяжёлый post-processing и WebGPU-first runtime
не входят в MVP.

## Target stack

| Layer | Technology | Роль |
| --- | --- | --- |
| Application | React 19, TypeScript, Vite | приложение, composition и build |
| Spatial renderer | Three.js, React Three Fiber, Drei | camera, picking, entities, depth |
| DOM UI | React DOM, CSS, AiDN Design System | frames, forms, text, tables, controls |
| Client state | Zustand | camera, focus, layout, selection, transient presentation |
| Server state | TanStack Query | authoritative data, cache, refetch, mutations |
| Motion | Motion | DOM transitions и shared motion language |
| Schemas | Zod | Presentation Intent, view models, event payloads |
| Live data | WebSocket через adapter | node events без прямого изменения renderer |
| Request data | REST/HTTP через query layer | initial state, history, configuration |
| Voice/audio | Web Audio API, Web Speech или local STT adapter | voice input/output без coupling к renderer |
| Optional content | react-markdown, Shiki, TanStack Virtual, Recharts/visx | вторичные presentation needs |

Дополнительная библиотека не становится архитектурным центром без отдельного
решения. Redux, Material UI как основной visual system, physics engine,
Babylon.js, Unity WebGL и Unreal не используются в этой архитектуре.

## Five-layer architecture

~~~text
PRESENTATION / DOM
  Milky Glass UI / Component Registry
          │
SPATIAL VIEW
  R3F / Three.js / camera / picking
          │
WORKSPACE MODEL
  entities / relations / clusters / semantic positions
          │
NODE DATA
  REST / WebSocket / Query cache / View Models
          │
AiDN NODE API
~~~

Primary Agent находится рядом с renderer boundary. Он формирует
Presentation Intent и system actions, но не рисует UI и не выполняет
произвольный frontend code:

~~~text
Primary Agent
      │ Presentation Intent
      ▼
Schema validation
      ▼
Presentation Planner
      ▼
Component Registry / Spatial View Model
      ├── React DOM
      └── R3F entity projection
~~~

System action сохраняет отдельный путь:

~~~text
Primary Agent
      ▼
MCP / canonical command path
      ▼
Hypervisor
~~~

Presentation не является authority для Node, protocol, wallet или
permission, что согласуется с ADR-011 и ADR-012.

## Rendering boundary

### Three.js / R3F отвечает за

- Primary Agent, Subagents и Endpoint energy objects;
- Session Artifacts и Attention Markers;
- semantic threads и flow pulses;
- camera, spatial depth, fog и horizon;
- world positioning, object picking и spatial animation;
- lightweight LOD и visibility culling.

### React DOM отвечает за

- forms и editable fields;
- tables, charts и configuration controls;
- text conversations, Markdown, logs и code;
- glass frames, menus, tooltips и EndpointTestFrame;
- status labels, errors, approvals и accessible live regions.

Нельзя рендерить сложный текст, configuration forms или большие таблицы в
WebGL ради визуальной однородности. DOM-компонент использует
[ADR-013](./ADR-013-aidn-milky-glass-neumorphism-visual-design.md), а
пространственный объект использует согласованный 3D material profile.

### Physical layers

~~~tsx
<App>
  <SpatialWorkspace />
  <UIOverlay>
    <PresentationLayer />
    <SystemMenu />
    <InteractionSurface />
  </UIOverlay>
</App>
~~~

Canvas находится под DOM overlay. Overlay по умолчанию не перехватывает
pointer events; конкретный frame или control включает pointer events
локально.

~~~css
.spatial-canvas {
  position: fixed;
  inset: 0;
  z-index: 0;
}

.ui-overlay {
  position: fixed;
  inset: 0;
  z-index: 10;
  pointer-events: none;
}

.ui-overlay > [data-interactive="true"] {
  pointer-events: auto;
}
~~~

DOM frame может быть связан с 3D object, но не обязан быть физически
приклеен к его screen position. Малый label или tooltip может использовать
projected coordinates; большой information frame переходит в focus region.

~~~text
3D world coordinates
        ↓
camera projection
        ↓
screen coordinates
        ↓
small label / tooltip anchor
~~~

Проекция не меняет canonical world position и не создаёт duplicate entity.

## Environment

Environment — это почти белая studio space, а не набор визуально различимых
cloud objects:

~~~text
high-key white background
subtle horizon
soft ground plane
controlled distance fog
neutral environment reflections
optional sparse dust/noise
~~~

Fog используется для потери контраста и saturation дальних объектов. Он не
является самостоятельным объектом Workspace и не должен создавать тяжёлый
volumetric effect.

MVP environment:

- THREE.Fog с явными near/far параметрами;
- matte ground plane без постоянной сетки;
- Hemisphere Light;
- large directional key light;
- мягкий fill light;
- невидимая neutral studio environment map для glass reflections.

Bloom ограничивается Primary Agent core, active Endpoint, Attention Marker,
semantic pulse и CRITICAL state. Depth of Field откладывается за пределы MVP.

## Entity material profiles

### Primary Agent

Primary Agent использует стандартный physical glass material прежде, чем
вводить custom shader:

~~~jsx
<meshPhysicalMaterial
  color="#f7fbff"
  roughness={0.12}
  metalness={0}
  transmission={0.82}
  thickness={1.4}
  ior={1.32}
  transparent
/>
~~~

Минимальное расширение — inner luminous core, very subtle particle layer,
faint iridescence и soft halo. Shader добавляется только после измерения
пользы для состояния или interaction.

### Endpoint

Endpoint остаётся energy object:

- central glass/energy sphere;
- 8–20 instanced particles;
- 1–2 orbital curves;
- subtle glow.

Particles должны использовать InstancedMesh, а не отдельные React
components. Availability, latency, load и familiarity остаются view-model
signals и не превращаются в нечитабельный набор эффектов.

### Session Artifact

Session Artifact использует frosted translucent glass cube с лёгким
metallic tint, а не хромированную железную поверхность:

~~~text
roughness: 0.25
metalness: 0.05
transmission: 0.60
opacity: 0.75
semantic tint: 5–15%
~~~

Форма и material profile продолжают ADR-013, а семантика объекта и
provenance остаются в ADR-006/ADR-008.

## State и data flow

### Server state и workspace state

Authoritative Node data загружается через TanStack Query:

- endpoints;
- node status;
- agents;
- configuration;
- resource accounting;
- history и artifacts;
- revisions и availability.

Zustand хранит только client/workspace state:

- selected object;
- camera и focus;
- layout и semantic positions;
- hover;
- opened frames;
- temporary discovery results;
- presentation transition state.

Query cache является источником server state, Zustand — источником локальной
presentation state. Один объект не должен иметь две competing authoritative
версии.

### WebSocket adapter

WebSocket не должен напрямую менять цвет sphere или вызывать React
component. Канонический путь:

~~~text
WebSocket
    ↓
Event Dispatcher
    ↓
State Adapter
    ├── TanStack Query cache update
    └── Zustand presentation update
    ↓
View Model derivation
    ↓
DOM / R3F renderer
~~~

Пример event:

~~~json
{
  "type": "endpoint.state_changed",
  "endpoint_id": "ep_42",
  "state": "READY"
}
~~~

Renderer получает уже обновлённый view model, а не raw socket payload.
Unknown events, stale revision и malformed payload дают typed diagnostic и
не меняют визуальное состояние молча.

### View Models

~~~typescript
interface EndpointViewModel {
  id: string;
  capability: string;
  visualState: "healthy" | "attention" | "critical" | "offline";
  familiarity: "unseen" | "known" | "trusted_by_history";
  activity: "idle" | "working" | "streaming";
  emphasis: number;
  availability: "available" | "degraded" | "unavailable";
  sourceRevision: string;
  provenanceRef: string;
}
~~~

View Model содержит presentation projection, но не заменяет canonical Node
state и не получает право менять protocol records.

## Presentation Planner contract

Planner передаёт semantics и bounded style hints, а не CSS:

~~~json
{
  "component": "EndpointList",
  "anchor": "CURRENT_CONTEXT",
  "importance": "PRIMARY",
  "lifetime": "SESSION",
  "presentation": {
    "density": "compact",
    "surfaceProfile": "floating-medium"
  }
}
~~~

Planner не может передать glassOpacity, arbitrary borderRadius, JavaScript,
shader source или renderer callback. Material profile выбирается из registry
согласно ADR-011 и ADR-013.

## Quality profiles и capability detection

На старте runtime оценивает:

- WebGL/WebGL2 capabilities;
- доступность WebGPU без обязательного использования;
- GPU renderer и limits;
- browser;
- device memory, screen size и DPR;
- reduced-motion и high-contrast preferences.

Профиль выбирается по capabilities, а не только по имени устройства:

~~~typescript
type QualityProfile = "low" | "mobile" | "desktop" | "high";
~~~

| Profile | Rules |
| --- | --- |
| low | LOD0/LOD1, no post-processing, reduced particles, opaque fallbacks |
| mobile | DPR до 1.5, reduced particles, simple shadows, light bloom, no DoF |
| desktop | DPR до 2, physical materials, soft shadows, light post-processing |
| high | richer reflections, extra samples, optional DoF after explicit opt-in |

MVP использует WebGL2 через Three.js. WebGPU оценивается отдельным
экспериментом после доказательства UX и базовой производительности.

## Spatial LOD и performance

Glass/transmission и particles требуют bounded render budget:

~~~text
LOD0  tiny point or sprite
LOD1  simple translucent sphere/cube
LOD2  physical material with minimal detail
LOD3  full particles, orbits and relation details
~~~

LOD определяется distance, zoom, focus, importance и visibility. Far-space
objects могут быть virtualized или suspended, но canonical object, relation
и provenance не удаляются.

Initial budgets:

- 60 FPS на поддерживаемом desktop profile в базовом workspace;
- response на click/focus менее 100ms до начала transition;
- средний frame budget около 16ms в desktop baseline;
- mobile profile не обязан показывать полный particle/orbit detail;
- bloom, blur, transmission и shadow проходят отдельный performance check;
- DoF не включается в MVP.

Spatial index (octree, BVH или spherical region index) откладывается до
объёма примерно 200–500 объектов. До этого используется простой bounded
collection и culling.

## Motion language

DOM и R3F используют эквивалентный motion vocabulary:

~~~text
ENTER
EXIT
FOCUS
UNFOCUS
PULL
RETURN
SPAWN
ATTENTION
ORBIT
IDLE
~~~

Для каждого transition фиксируются duration, easing/spring, overshoot и
reduced-motion variant. Компонент не придумывает собственный easing без
registry change. Camera flight, semantic pulse и DOM surface enter должны
ощущаться частью одной материальной системы.

## Module boundaries

~~~text
frontend/
├── app/
├── design-system/
│   ├── tokens/
│   ├── css/
│   ├── Surface/
│   ├── Button/
│   ├── Input/
│   ├── Toggle/
│   ├── Tooltip/
│   └── GlassFrame/
├── spatial/
│   ├── canvas/
│   ├── environment/
│   ├── entities/
│   ├── relations/
│   ├── layout/
│   ├── camera/
│   ├── interaction/
│   └── quality/
├── presentation/
│   ├── planner/
│   ├── registry/
│   ├── schemas/
│   ├── renderer/
│   └── anchors/
├── workspace/
│   ├── model/
│   ├── relations/
│   ├── clustering/
│   ├── persistence/
│   └── spatial-index/
├── state/
├── data/
│   ├── api/
│   ├── query/
│   ├── websocket/
│   ├── events/
│   └── view-models/
└── classic/
~~~

Module dependency direction:

~~~text
AiDN API
  ↓
data adapters
  ↓
canonical/query state
  ↓
view models
  ↓
workspace/presentation
  ↓
DOM or R3F renderer
~~~

Renderer modules не должны импортировать напрямую transport client или
wallet/private data.

## Prototype sequence

1. **Prototype A — Spatial Core.** White atmospheric environment, horizon,
   fog, Primary Agent, Subagents, Session Artifacts, Endpoints, Endpoint Arc,
   semantic threads, Attention Markers, rotate/focus/zoom. Без панелей.
2. **Prototype B — Hybrid Surface.** Focus Artifact → Milky Glass DOM frame
   → fake conversation; Endpoint → glass Endpoint Details.
3. **Prototype C — Mobile.** Тот же Workspace в mobile viewport: swipe,
   pinch, tap, long press, focus, DOM keyboard и reduced-motion.
4. **Prototype D — Agent integration.** Mock Primary Agent API →
   Presentation Intent → schema validation → EndpointList и
   EndpointTestFrame.
5. **Prototype E — Real Node integration.** Real Primary Agent → MCP →
   Hypervisor → query cache/events → view models → real DOM/R3F projections.

## Security и authority

- Node API и Hypervisor остаются authoritative.
- Presentation state можно потерять без повреждения protocol state.
- R3F picking создаёт intent, но не даёт права выполнить action.
- DOM frame не принимает remote UI code.
- Remote requests идут через local Node mediation по ADR-012.
- View models redacted и не содержат private keys или secrets.

## Не входит в MVP

- WebGPU-first renderer;
- volumetric cloud library;
- physics engine;
- VR/AR;
- full text rendering in WebGL;
- DoF и тяжёлый SSAO;
- spatial index до достижения object-count threshold;
- автоматическая генерация arbitrary CSS, shader или JavaScript;
- переписывание Classic UI до отдельного migration slice.

## Критерии приёмки

ADR считается реализованным для первой spatial surface, когда:

- React/R3F и DOM слои работают одновременно и не перехватывают чужие
  events;
- сложный текст, формы и controls не рендерятся в WebGL;
- R3F entities не вызывают transport напрямую;
- REST и WebSocket проходят data adapters и typed view models;
- TanStack Query хранит server state, Zustand — client/workspace state;
- Presentation Planner выдаёт schema-validated intent без arbitrary CSS/code;
- environment использует fog и controlled lighting без обязательных clouds,
  DoF или heavy bloom;
- Primary Agent, Endpoint и Session Artifact имеют bounded materials и LOD;
- quality profile выбирается по capabilities и учитывает mobile/reduced motion;
- WebGL2 является рабочим MVP baseline;
- DOM и R3F используют общие material/state semantics;
- manual test, unavailable, stale и remote-untrusted states сохраняют
  локальные security и accessibility rules;
- Prototype A–E проходят на desktop и mobile acceptance paths.

## Связанные документы

- [ADR-008 — Entity Uniqueness and Provenance References](./ADR-008-entity-uniqueness-and-provenance.md)
- [ADR-009 — Multi-Device Workspace and Mobile Spatial Navigation](./ADR-009-multi-device-workspace-and-mobile-navigation.md)
- [ADR-011 — Agent-Mediated Component Interface](./ADR-011-agent-mediated-component-interface.md)
- [ADR-012 — Local Trust Boundary and Mediated Remote Resource Access](./ADR-012-local-trust-boundary-and-mediated-remote-resources.md)
- [ADR-013 — AiDN Milky Glass Neumorphism Visual Design System](./ADR-013-aidn-milky-glass-neumorphism-visual-design.md)
- [Detailed Development Roadmap](./DEVELOPMENT-ROADMAP.md)
- [AiDN Spatial Agent Interface — Implementation Plan](./AiDN-Spatial-Agent-Interface-Implementation-Plan.md)
- [Общая design-система Hypervisor](../../DESIGN.md)
