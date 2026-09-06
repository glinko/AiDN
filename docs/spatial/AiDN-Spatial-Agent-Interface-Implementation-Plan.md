# AiDN Spatial Agent Interface
## Расширенный план реализации агентно-центричного пространственного интерфейса

**Статус:** Design / Implementation Plan  
**Рабочее название интерфейса:** Inti Spatial Agent Interface  
**Основная сущность интерфейса:** Primary Agent Presence («Инти»)  
**Главная идея:** пользователь взаимодействует не с набором страниц и панелей, а с пространством, в центре которого находится основной агент. Все разговоры, артефакты, удалённые агенты, endpoint'ы, сервисы, платежи, связи и результаты проявляются вокруг него как пространственные объекты.  
**Старт реализации в новом чате:** [Implementation Handoff](./IMPLEMENTATION-HANDOFF.md)  
**Детальный план разработки:** [Detailed Development Roadmap](./DEVELOPMENT-ROADMAP.md)  

---

# 1. Цель

Цель системы — создать новый тип пользовательского интерфейса для AiDN, в котором:

- основной объект интерфейса — агент;
- всё пустое пространство является потенциальной зоной взаимодействия;
- голос — основной способ общения;
- текст, файлы, изображения, аудио и другие вложения создаются непосредственно в точке взаимодействия;
- разговоры не существуют как отдельная «страница чата», а превращаются в самостоятельные пространственные объекты;
- завершённые диалоги компактизируются в артефакты;
- удалённые агенты, сервисы и endpoint'ы отображаются как связанные сущности;
- экономические отношения AiDN могут визуализироваться непосредственно между агентами;
- пользователь может перемещать, группировать, сворачивать, раскрывать и исследовать объекты;
- UI не диктует пользователю маршрут по меню;
- основной агент сам приводит релевантные объекты в поле зрения.

Главная формула:

```text
Human
  ↓
Primary Agent
  ↓
Intent
  ↓
AiDN Protocol / Local Tools
  ↓
Objects / Relations / Results
  ↓
Spatial Presentation
```

---

# 2. Принципы интерфейса

## 2.1. Agent-first

Пользователь всегда находится в пространстве своего основного агента.

Никакая страница, dashboard, sidebar или меню не является центральной сущностью UX.

```text
Wrong:
User → Menu → Page → Widget → Action

Target:
User → Agent → Intent → Result
```

## 2.2. Space-first

Вся поверхность экрана является рабочим пространством.

Пустой участок страницы может использоваться как:

- начало текстового запроса;
- точка записи голоса;
- drop-zone для файла;
- место создания нового объекта;
- начало нового независимого контекста.

## 2.3. Object-centric

В UI существуют объекты, а не страницы.

Основные типы:

```text
Agent
Service
Endpoint
Session
Conversation
Artifact
File
Image
Audio
Log
Report
Graph
Payment
Contract
Evidence
Task
Plan
Alert
```

## 2.4. Relation-aware

Любой объект SHOULD иметь явную семантическую связь с другими объектами.

Пример:

```text
Conversation
  ├── created_by → Local Agent
  ├── references → Endpoint
  ├── produced → Log View
  └── resulted_in → Repair Action
```

Связи могут отображаться как световые линии.

## 2.5. Progressive manifestation

UI не должен показывать всё сразу.

Объекты появляются только:

- по запросу пользователя;
- по действию агента;
- по значимому событию;
- при раскрытии связей.

## 2.6. Calm UI

**Material direction:** [ADR-013 — AiDN Milky Glass Neumorphism Visual Design System](./ADR-013-aidn-milky-glass-neumorphism-visual-design.md)

Интерфейс должен ощущаться живым, но не шумным.

MUST:

- плавные анимации;
- мягкие переходы;
- минимальная плотность;
- почти невидимый фон;
- ограниченное количество цветов;
- отсутствие постоянных панелей.

MUST NOT:

- непрерывно мигать;
- показывать лишние сетки;
- заполнять экран десятками значков;
- использовать агрессивные уведомления без критической причины.

---

# 3. Главная визуальная метафора

Пользователь попадает «внутрь облака».

Фон:

- почти белый;
- белые и холодно-серые слои;
- едва заметные голубоватые оттенки;
- мягкая глубина;
- очень медленное движение;
- отсутствие горизонта;
- отсутствие явной геометрической сетки.

Пример слоя фона:

```text
CSS radial gradients
+
blurred pseudo-elements
+
slow translated noise layers
+
very low opacity
```

Визуально:

```text
█████████████████████████████████████
██   ░░       ░░░      ░░       ████
█        ░░              ░░        ██
█                 ●                 ██
█       ░                  ░        ██
██             ░░░                ███
█████████████████████████████████████
```

---

# 4. Primary Agent Presence — Инти

## 4.1. Назначение

Инти — визуальное присутствие основного агента.

Это не кнопка и не просто индикатор.

Инти одновременно:

- показывает наличие агента;
- показывает состояние;
- служит voice-entry point;
- отражает активность;
- является визуальным центром пространства;
- является корневым узлом большинства связей.

## 4.2. Состояния

Минимальный набор:

```text
IDLE
LISTENING
THINKING
ACTING
WAITING_FOR_USER
ATTENTION
CRITICAL
OFFLINE
ESCALATED
```

Пример отображения:

```text
IDLE
soft neutral glow

LISTENING
expanded halo

THINKING
slow internal flow

ACTING
outbound pulses

ATTENTION
warm amber tone

CRITICAL
soft red core

ESCALATED
violet external halo

OFFLINE
dim gray
```

## 4.3. Цвет не должен быть единственным каналом

Для accessibility состояние MUST также различаться через:

- pulse pattern;
- halo geometry;
- motion;
- optional compact label on focus;
- screen reader state.

## 4.4. Click-to-talk

По умолчанию:

```text
click Inti
→ activate microphone
→ agent acknowledges
→ user speaks
→ STT
→ reasoning
→ response
```

Пример голосовой реакции:

```text
"На связи."
```

Если audio output недоступен:

```text
create Text Notice:
"На связи. Голосовой вывод недоступен."
```

Если microphone недоступен:

```text
create Text Notice:
"Микрофон недоступен. Кликните в любом месте и введите запрос."
```

## 4.5. Дополнительные действия

Предлагаемая модель:

```text
Single Click
→ talk

Double Click
→ explain current state

Long Press / Right Click
→ Inti Control Menu
```

Меню:

```text
Response Mode
Listening Mode
Agent Mode
Current State
Show Active Tasks
Show Attention Items
```

---

# 5. Interaction Seed

## 5.1. Назначение

При клике в пустое пространство создаётся `Interaction Seed`.

Это исходная точка нового взаимодействия.

## 5.2. Визуальная форма

Начальное состояние:

- почти замкнутое кольцо;
- один сжатый разрыв;
- мягкие иконки вокруг;
- blinking caret внутри.

Можно воспринимать форму как:

```text
almost-closed ring
with a compressed seam
```

## 5.3. Быстрые действия

Максимум шесть primary actions:

```text
1. File
2. Voice
3. Image
4. Context
5. Action
6. More
```

### File
Прикрепить документ или бинарный файл.

### Voice
Записать голосовой запрос.

### Image
Добавить изображение / screenshot.

### Context
Выбрать существующий объект на canvas как контекст.

### Action
Открыть быстрые действия.

### More
Открыть дополнительные источники ввода.

## 5.4. Состояния Interaction Seed

```text
DORMANT
OPEN
TEXT_INPUT
VOICE_INPUT
ATTACHMENT_INPUT
CONTEXT_PICK
ACTION_PICK
SUBMITTED
CANCELLED
```

---

# 6. Морфинг Interaction Seed → Input Surface

## 6.1. Требование

При начале печати кольцо MUST не исчезать, а трансформироваться.

Цель:

```text
same object
→ new form
```

а не:

```text
old object disappears
+
new textbox appears
```

## 6.2. Анимационная последовательность

```text
ring
↓
seam opens
↓
arc stretches
↓
top-left anchor forms
↓
input border appears
↓
surface expands with text
```

Рекомендуемая продолжительность:

```text
250–400 ms
```

## 6.3. Inti Trace

Часть исходной формы остаётся визуально лежать на верхнем левом углу input surface.

Рабочее имя:

```text
Inti Trace
```

Она показывает, что объект создан через agent interaction.

Состояния:

```text
typing      static
listening   breathing
thinking    flowing
done        settled
error       warning pulse
```

---

# 7. Input Surface

## 7.1. Поведение размера

Поле MUST динамически расти по содержимому.

Пример:

```text
1–3 words
→ compact width

sentence
→ wider

paragraph
→ larger width + height

long content
→ capped width/height + scroll
```

## 7.2. Расширение

Алгоритм:

```text
measure text
↓
calculate preferred width
↓
calculate preferred line wrap
↓
expand width until max
↓
then expand height
↓
then enable scroll
```

## 7.3. Ограничения

Desktop пример:

```text
min width: 220 px
preferred width: 320–720 px
max width: 60vw

min height: 56 px
max height: 45vh
```

Mobile:

```text
max width: 88–92vw
max height: 50vh
```

Конкретные значения MUST быть tuning parameters.

## 7.4. Keyboard semantics

Рекомендуется:

```text
Enter
→ newline

Ctrl+Enter
→ submit

Cmd+Enter
→ submit

Escape
→ cancel / close current interaction
```

`Ctrl+S` SHOULD NOT использоваться для отправки.

---

# 8. Conversation Surface

## 8.1. Основная идея

После отправки Input Surface превращается в `Conversation Surface`.

Это одна непрерывная рабочая поверхность.

Не использовать обязательную модель пузырей:

```text
user bubble
assistant bubble
```

Вместо этого:

```text
conversation object
  ├── user request
  ├── thinking state
  ├── agent response
  ├── generated object previews
  ├── follow-up input
  └── action results
```

## 8.2. Streaming

Conversation Surface MUST поддерживать streaming:

```text
REQUEST
↓
THINKING
↓
PARTIAL OUTPUT
↓
TOOL PROGRESS
↓
FINAL OUTPUT
```

## 8.3. Thinking

UI MAY показывать:

```text
Thinking…
Inspecting endpoint…
Reading logs…
Checking resources…
```

Но MUST NOT отображать скрытый chain-of-thought.

Показывать только user-safe progress states.

## 8.4. Follow-up

Пока объект активен, новые сообщения относятся к его контексту.

```text
conversation_context_id
```

---

# 9. Компактизация Conversation → Session Artifact

## 9.1. Триггеры

Conversation Surface может перейти в compact state:

- пользователь закрывает объект;
- сессия неактивна N минут;
- пользователь явно выбирает Compact;
- workspace выполняет cleanup.

## 9.2. Анимация

```text
surface
↓
shrink
↓
fold
↓
gain visual depth
↓
move into nearby orbit
↓
Session Artifact
```

## 9.3. Визуальный объект

Не буквальный куб.

Рекомендуется:

```text
soft 3D artifact
rounded volumetric tile
semi-transparent
soft internal light
```

## 9.4. Уровни представления

```text
FULL
CARD
ARTIFACT
CHIP
```

---

# 10. Session Artifact

## 10.1. Содержимое

Artifact хранит:

```yaml
session:
  id:
  owner_agent:
  participants:
  started_at:
  ended_at:
  conversation:
  attachments:
  generated_objects:
  related_entities:
  actions:
  payments:
  contracts:
  evidence:
  summary:
```

## 10.2. Single click

```text
single click
→ focus
→ show semantic relations
```

## 10.3. Double click

```text
double click
→ move toward center
→ expand
→ restore conversation surface
```

## 10.4. Drag

Пользователь MUST иметь возможность вручную перемещать artifact.

После ручного перемещения:

```text
layout_mode = USER_POSITIONED
```

---

# 11. Пространственные связи

## 11.1. Relation Edge

Связи являются визуализацией семантического графа.

```yaml
relation:
  id:
  source:
  target:
  type:
  direction:
  strength:
  visibility:
  active:
```

## 11.2. Типы связей

Примеры:

```text
CREATED_BY
PARTICIPATED_IN
USES
PROVIDED_BY
CONNECTED_TO
PAID
REQUESTED
PRODUCED
DERIVED_FROM
VALIDATED_BY
DEPENDS_ON
FAILED_BECAUSE_OF
```

## 11.3. Visual language

Default:

```text
thin
soft
semi-transparent
neutral
```

On focus:

```text
brighter
slightly thicker
animated
```

## 11.4. Semantic pulses

Допустимо показывать редкие смысловые события:

```text
REQUEST
RESULT
PAYMENT
ARTIFACT
ERROR
```

Но MUST NOT визуализировать каждый network packet.

---

# 12. Remote Agent and Provider Provenance

**Decision:** [ADR-012 — Local Trust Boundary and Mediated Remote Resource Access](./ADR-012-local-trust-boundary-and-mediated-remote-resources.md)

Remote Agent identity is a protocol/provenance fact, not an implicit
user-facing conversation channel. The default spatial representation is the
Endpoint capability object; a Remote Agent is not materialized as a full
Agent Presence unless the operator explicitly requests a read-only metadata
view.

## 12.1. Discovery and provenance

После AiDN discovery в пространстве может появиться provenance marker или
Endpoint Arc candidate.

До выбора:

```text
dim presence
far-space
no strong edge
```

После establishment session:

```text
visible semantic relation
semantic activity
```

Это не означает прямой Human ↔ Remote Agent connection: запрос проходит
через local AiDN Node, authorization, context minimization и policy.

## 12.2. Пример

```text
                 ◇ Remote Endpoint

        ● Main Agent

                               ◇ Image Endpoint
```

При запросе оператора:

```text
Endpoint Details
provider/operator: metadata
remote node: metadata
reputation: metadata
```

Details остаётся read-only provenance projection и не открывает отдельный
канал переписки с владельцем Remote Agent.

## 12.3. Distinguish actor types

Визуально SHOULD мягко различать:

```text
Local Agent
Remote Agent / provider metadata
Service
Endpoint
Infrastructure Node
Artifact
```

Local Agent может иметь полноценную Agent Presence. Remote Agent и provider
по умолчанию остаются metadata/provenance, а capability показывается через
Endpoint representation. Нельзя превращать интерфейс в diagram editor или
создавать Human ↔ Remote Agent shortcut по умолчанию.

---

# 13. Endpoint как capability projection

В новой концепции AiDN Endpoint — не обязательно «модель».

Он представляет доступную capability.

```text
Actor
  ↓
Capability
  ↓
Endpoint
```

Пример:

```yaml
endpoint:
  capability: image.generate
  actor: remote_agent_42
  actor_visibility: provenance_only
  price: 0.05 Q
```

UI может отображать Endpoint как свойство/проекцию Agent Presence.

---

# 14. Multi-Agent Task Visualization

Пример:

```text
                     ◉ Search Agent
                        │
                        │
              ◉ Papers ─□─ ◉ Translation
                        │
                        │
                        ●
                    Main Agent
```

`□` — task/session artifact.

## 14.1. Expanded economics

По запросу:

```text
Show economics
```

UI показывает:

```text
Main Agent
   │ 2.8 Q
   ▼
Search Agent

Main Agent
   │ 0.7 Q
   ▼
Paper Agent
```

---

# 15. Пространственные зоны

**Decision:** [ADR-009 — Multi-Device Workspace and Mobile Spatial Navigation](./ADR-009-multi-device-workspace-and-mobile-navigation.md)

## 15.1. Near Space

Содержит:

- текущую беседу;
- активные задачи;
- выбранные объекты;
- live sessions.

## 15.2. Mid Space

Содержит:

- недавние conversations;
- активные remote resources и provenance markers;
- related artifacts;
- endpoint relations.

## 15.3. Far Space

Содержит:

- архивные sessions;
- distant remote resources и provenance;
- broader network;
- older artifacts.

---

# 16. Zoom semantics

Zoom SHOULD быть семантическим, а не только геометрическим.

Пример:

```text
close zoom
→ full conversation

medium zoom
→ artifact + relations

far zoom
→ agent neighborhood

very far zoom
→ network constellation
```

---

# 17. Canvas Architecture

**Decision:** [ADR-014 — Spatial UI Technical Architecture and Rendering Boundary](./ADR-014-spatial-ui-technical-architecture.md)

Целевой frontend/runtime stack:

```text
React 19 + TypeScript + Vite
│
├── React DOM / AiDN Design System
├── React Three Fiber / Three.js / Drei
├── Presentation Planner + Component Registry
├── TanStack Query (server state)
├── Zustand (workspace/client state)
├── Motion (shared DOM/3D motion language)
├── Zod (schemas and intent validation)
├── Web Audio / Web Speech or local STT adapter
├── REST/HTTP query layer
└── WebSocket event adapter
```

Граница ответственности renderer'ов:

```text
Three.js / R3F
→ spatial entities, depth, camera, fog, picking, relations, LOD

React DOM / CSS
→ text, forms, tables, charts, logs, settings, conversation frames
```

Spatial runtime не должен превращать UI-текст, формы и таблицы в WebGL-геометрию.
Визуальной основой является high-key atmospheric environment и Milky Glass
Neumorphism из [ADR-013](./ADR-013-aidn-milky-glass-neumorphism-visual-design.md).

---

# 18. Renderer strategy

**Decision:** MVP использует WebGL2 через React Three Fiber/Three.js для
пространственных сущностей и React DOM/CSS для интерфейсных поверхностей.

Target renderer:

```text
WebGL2 + R3F/Three.js:
  Primary Agent, Subagents, Endpoints, Session Artifacts,
  Attention Markers, semantic threads, camera and atmospheric depth

React DOM/CSS:
  glass frames, forms, tables, logs, configuration,
  conversations, EndpointTestFrame, status and error surfaces

TanStack Query + Zustand:
  authoritative server state vs local workspace state

Motion:
  shared DOM/3D motion vocabulary
```

Не входит в MVP:

```text
WebGPU-first renderer
volumetric clouds
heavy post-processing
full-scene depth of field
physics engine
```

Fog, physical materials, soft studio lighting и очень умеренный bloom
достаточны для первого spatial prototype. WebGPU и сложные shader-пути
оцениваются только после доказательства UX.

---

# 19. Data Model

**Decision:** [ADR-008 — Entity Uniqueness and Provenance References](./ADR-008-entity-uniqueness-and-provenance.md)
с учётом rendering/data boundary из [ADR-014](./ADR-014-spatial-ui-technical-architecture.md).

Canonical entities и их spatial projections разделены: одна primary presence
на Workspace, исторические interaction records используют references и
provenance, а временные context projections не становятся самостоятельными
объектами.

## 19.1. Workspace

```yaml
workspace:
  id:
  owner:
  revision:
  viewport:
    x:
    y:
    zoom:
  objects: []
  relations: []
  groups: []
  created_at:
  updated_at:
```

## 19.2. Canvas Object

```yaml
object:
  id:
  type:
  semantic_ref:
  state:
  layout:
    x:
    y:
    width:
    height:
    z:
    mode:
  presentation:
    variant:
    collapsed:
  created_by:
  created_at:
  updated_at:
```

## 19.3. Layout Mode

```text
AUTO
USER_POSITIONED
PINNED
LOCKED
COLLAPSED
```

---

# 20. Canvas Mutation Protocol

LLM MUST NOT отправлять пиксельные координаты как основное средство layout.

Agent выдаёт semantic intent.

Пример:

```json
{
  "op": "CREATE",
  "component": "LogViewer",
  "semantic_ref": "runtime:rt-42",
  "relation": {
    "target": "endpoint:ep-17",
    "type": "DIAGNOSTIC_DETAIL"
  },
  "importance": "PRIMARY"
}
```

Layout Engine решает:

```text
where to place
how large
which direction
collision avoidance
```

---

# 21. Canonical Canvas Operations

```text
CREATE
UPDATE
REMOVE

LINK
UNLINK

FOCUS
HIGHLIGHT

EXPAND
COLLAPSE

GROUP
UNGROUP

PIN
UNPIN

MOVE
RESIZE

SPEAK
PLAY_AUDIO

REQUEST_INPUT
REQUEST_APPROVAL
```

---

# 22. Component Registry

**Decision:** [ADR-011 — Agent-Mediated Component Interface and Resource Semantics](./ADR-011-agent-mediated-component-interface.md)

Agent MAY выбирать только зарегистрированные компоненты.

MUST NOT:

```text
LLM → arbitrary JavaScript
```

MUST:

```text
Agent
↓
Presentation Intent
↓
Schema Validation
↓
Component Registry
↓
Renderer
```

## 22.1. Initial component set

```text
Text
Markdown
Notice
Status

Conversation
Prompt

FileViewer
ImageViewer
AudioPlayer
CodeViewer
LogViewer

Metric
MetricGrid
Chart

AgentCard
EndpointCard
EndpointTestFrame
ServiceCard
NodeCard

Task
Plan
Progress
Timeline

TopologyGraph
DependencyGraph

Payment
Contract
Evidence
ValidationReport

Confirmation
Approval
Error
```

## 22.2. Visual Design System

Все зарегистрированные компоненты используют material profiles из
[ADR-013 — AiDN Milky Glass Neumorphism Visual Design System](./ADR-013-aidn-milky-glass-neumorphism-visual-design.md).
Surface profile не зависит от spatial placement и выбирается через tokens:
depth, glass, accent, radius и emphasis. Presentation Planner передаёт
declarative profile, а renderer отвечает за CSS или Three.js material.

---

# 23. Agent Presentation Planner

**Decision:** [ADR-011 — Agent-Mediated Component Interface and Resource Semantics](./ADR-011-agent-mediated-component-interface.md)

Steward / Primary Agent должен иметь отдельный слой:

```text
Reasoning
↓
Result Model
↓
Presentation Planner
↓
Canvas Operations
```

Reasoning не должен напрямую строить UI.

## 23.1. Presentation decisions

Planner определяет:

```text
what to show
which component type
which object is context
what relations exist
whether output should be speech
whether output should create artifact
whether object should be compact/full
```

---

# 24. Layout Engine

## 24.1. Responsibilities

Layout Engine отвечает за:

```text
placement
collision avoidance
preferred direction
object grouping
distance to semantic parent
workspace bounds
focus animation
zoom target
```

## 24.2. Heuristics

Пример:

```text
diagnostic detail
→ near source object

unrelated query
→ new context island

child relation
→ outward from parent

remote actor metadata
→ farther from local agent

archived artifact
→ move outward
```

## 24.3. User authority

После ручного перемещения объекта:

```text
Agent MUST NOT reposition
unless:
- user enables auto-layout
- object is unpinned
```

---

# 25. Spatial Memory

**Decision:** [ADR-007 — Spatial Memory, Aging and Clustering](./ADR-007-spatial-memory-aging-clustering.md)

Workspace MUST сохраняться между сессиями браузера как semantic model и
presentation projection. История не удаляется из-за aging: новые объекты
остаются рядом с Primary Agent, связанные объекты переходят в semantic
clusters, а неактивные объекты получают более дальний LOD или virtualized
representation.

После возврата пользователя:

```text
restore viewport
restore object positions
restore collapsed states
restore relationships
restore session artifacts
```

## 25.1. Recency drift

Автоматическое отдаление старых объектов является частью принятой aging
policy. Оно должно быть детерминированным, использовать hysteresis и уважать
ручное закрепление или override оператора.

Пример:

```text
recent
→ closer

inactive
→ slowly move toward mid-space

archived
→ far-space
```

Но ручная позиция MUST иметь приоритет.

---

# 26. Audio Architecture

## 26.1. Input

```text
Microphone
↓
VAD
↓
STT
↓
Primary Agent
```

## 26.2. Output

```text
Agent Response
├── visual
└── speech
    ↓
    TTS
```

## 26.3. Default policy

```text
voice query
→ voice + visual response

text query
→ visual response
```

Пользователь может изменить policy.

---

# 27. Audio fallback

Если microphone unavailable:

```text
text interaction remains fully functional
```

Если speakers unavailable:

```text
visual answer
```

Если TTS unavailable:

```text
visual answer
+
optional status notice
```

---

# 28. File / Image / Audio Attachments

Attachment становится canvas object.

Пример:

```yaml
attachment:
  id:
  type: file
  mime:
  name:
  size:
  hash:
  local_ref:
  related_session:
```

---

# 29. Drag-and-drop

Пользователь SHOULD иметь возможность:

```text
drag file onto empty canvas
→ create File Artifact

drag file onto conversation
→ attach to context

drag artifact onto agent
→ send/share/reference
```

---

# 30. Context Picker

Context Picker — фундаментальная функция.

Пользователь:

```text
click Context
↓
select one or more canvas objects
↓
submit question
```

Agent получает structured context:

```yaml
context:
  - type: endpoint
    id: ep-42
  - type: log
    id: log-17
```

---

# 31. Inti State Explanation

Double click / explicit command:

```text
Why yellow?
```

Agent создаёт небольшой diagnostic object:

```text
Attention

Endpoint ep-42 failed
three health checks.

Last event:
health_check timeout

[Show Endpoint]
[Show Logs]
```

---

# 32. Proactive Agent UI

Hooks могут инициировать объекты без запроса.

Пример:

```text
event:
endpoint.failure
↓
Steward policy
↓
create compact alert artifact
↓
Inti → ATTENTION
```

## 32.1. Severity

```text
INFO
→ usually no object

WARNING
→ subtle artifact

ERROR
→ visible artifact

CRITICAL
→ Inti critical state + prominent artifact
```

---

# 33. Human approval

Опасные действия MUST создавать approval object.

```text
Agent proposes:
Disable Endpoint ep-42

Reason:
Repeated runtime failure

Impact:
3 active clients affected

[Approve]
[Reject]
[Inspect]
```

---

# 34. AiDN Protocol Integration

**Decision:** [ADR-012 — Local Trust Boundary and Mediated Remote Resource Access](./ADR-012-local-trust-boundary-and-mediated-remote-resources.md)

Новый UI должен отражать protocol primitives.

```text
Actor
Capability
Endpoint
Offer
Session
Contract
Payment
Evidence
Settlement
Reputation
```

## 34.1. Agent relation

```text
Primary Agent
→ Local AiDN Node
→ policy / authorization / context minimization
→ Remote Endpoint
→ result validation / provenance
→ Local Primary Agent
```

Каждая стадия MAY получить визуальное представление.

---

# 35. Economics Layer

**Decision:** [ADR-011 — Agent-Mediated Component Interface and Resource Semantics](./ADR-011-agent-mediated-component-interface.md)

Q и Compute Units описываются как ресурсный взаимозачёт. Экономические
детали скрыты по умолчанию и раскрываются компонентами ResourceBalance,
ResourceUsage, ResourceCostEditor и SettlementHistory.

По запросу:

```text
show economics
```

Показать:

```text
price
spent
escrow
fees
settlement
budget
```

---

# 36. Security boundary

**Decision:** [ADR-010 — Node Status and Recovery Access](./ADR-010-node-status-and-recovery-access.md)

**Trust boundary:** [ADR-012 — Local Trust Boundary and Mediated Remote Resource Access](./ADR-012-local-trust-boundary-and-mediated-remote-resources.md)

System Menu и Status являются Node-owned entry point и authoritative
recovery surface, независимыми от lifecycle Primary Agent.

UI Agent MUST NOT иметь прямой unrestricted wallet access.

Использовать:

```text
Agent Identity
↓
Capability Grant
↓
Budget Policy
↓
Wallet Authorization
```

---

# 37. UI Security

MUST:

- schema validate all generated UI;
- sanitize Markdown/HTML;
- prevent arbitrary script execution;
- prevent arbitrary component loading;
- validate file references;
- enforce permission checks independently of UI;
- separate presentation intent from executable action.

---

# 38. Accessibility

MUST:

- keyboard navigation;
- screen-reader labels;
- non-color status cues;
- reduced-motion mode;
- text scaling;
- focus visibility;
- alternate list view as fallback.

---

# 39. Reduced Motion

При:

```text
prefers-reduced-motion
```

заменять:

```text
morphing
→ crossfade

flying objects
→ direct reposition

pulses
→ static halo
```

---

# 40. Mobile UX

**Decision:** [ADR-009 — Multi-Device Workspace and Mobile Spatial Navigation](./ADR-009-multi-device-workspace-and-mobile-navigation.md)

Mobile использует тот же semantic Workspace с более узким viewport и другой
input modality. Это не отдельная упрощённая semantic model и не набор
mobile-only страниц.

Рекомендуется:

```text
Primary Agent
→ center/top-center

active conversation
→ dominant card

artifacts
→ nearby stack/constellation

pinch
→ zoom

swipe
→ pan
```

---

# 41. Touch Interaction

```text
Tap Inti
→ talk

Double Tap Inti
→ explain state

Long Press Inti
→ menu

Long Press Empty Space
→ Interaction Seed

Long Press Object
→ object actions

Drag
→ move

Pinch
→ zoom
```

---

# 42. Persistence

MVP persistence:

```text
local workspace state
+
server-side semantic state
```

Разделить:

```text
Presentation State
vs
Protocol/System State
```

Presentation можно потерять без повреждения системы.

---

# 43. Canonical backend split

```text
AiDN Node API / Protocol State
        │
        ▼
REST/HTTP + WebSocket adapters
        │
        ▼
Canonical query/event state
        │
        ▼
UI View Models
        │
        ▼
Presentation Planner
        │
        ├── React DOM / Component Registry
        └── R3F / Three.js spatial renderer
```

Primary Agent формирует intent и presentation intent, но не меняет DOM или
3D-сцену напрямую. Node остаётся источником истины; renderer получает
нормализованные view models.

---

# 44. State authority

Authoritative:

```text
AiDN node state
protocol state
wallet state
sessions
payments
contracts
```

Non-authoritative:

```text
positions
zoom
collapsed cards
decorative state
animations
```

---

# 45. Event Model

Canvas обновляется event-driven.

Пример:

```yaml
event:
  id:
  type:
  source:
  semantic_ref:
  timestamp:
  payload:
```

---

# 46. Live updates

Примеры:

```text
runtime.state_changed
endpoint.health_changed
session.opened
session.completed
payment.settled
agent.connected
agent.disconnected
```

Canvas object updates без page reload.

Поток событий:

```text
WebSocket
  ↓
Event Dispatcher
  ↓
State Adapter
  ↓
TanStack Query cache / Zustand
  ↓
UI View Models
  ↓
React DOM / R3F renderer
```

Нельзя связывать WebSocket-сообщение напрямую с изменением цвета объекта:
визуальное состояние выводится из актуального view model.

---

# 47. MVP-0 — Visual Prototype

Цель: проверить ощущение интерфейса.

Реализовать:

```text
white atmospheric environment
soft horizon + matte ground + fog
Primary Agent physical glass sphere
3 Subagents
6 Session Artifacts
7 Endpoints + Endpoint Arc
2 semantic threads + 3 Attention markers
camera rotate / focus / zoom
click-to-talk mock
Interaction Seed
text morph
Conversation Surface
compact artifact
drag
double-click restore
basic relation line
```

Без backend.

---

# 48. MVP-1 — Real Local Agent

Добавить:

```text
real Steward
STT
TTS
text requests
tool calls
streaming
basic canvas mutations
```

---

# 49. MVP-2 — System Objects

Добавить:

```text
Endpoint
Runtime
Provider
Logs
Resources
Tasks
Alerts
```

Agent может создавать реальные системные views.

---

# 50. MVP-3 — AiDN Agent Relations

Добавить:

```text
mediated remote actors and resources
discovery
session links
capabilities
endpoint projection
payments
```

Любая такая relation остаётся protocol-level и mediated по ADR-012; прямой
пользовательский канал к Remote Agent не создаётся.

---

# 51. MVP-4 — Persistent Spatial Workspace

Добавить:

```text
saved object positions
restored sessions
multiple workspace contexts
semantic zoom
archival
```

---

# 52. MVP-5 — Full Agent Economy UX

Добавить:

```text
offers
contracts
escrow
settlement
reputation
evidence
multi-agent execution graphs
budget policy
```

---

# 53. Prototype milestones

## Milestone A — 1 week

```text
static cloud environment
animated Inti
click in space
Interaction Seed
morph to input
```

## Milestone B — 2 weeks

```text
conversation surface
streaming mock
compact session artifact
drag / expand / collapse
```

## Milestone C — 3–4 weeks

```text
real agent API
voice pipeline
tool progress
generated components
```

## Milestone D — 4–6 weeks

```text
relations
mediated remote resources and provenance
semantic layout
persistent workspace
```

---

# 54. Recommended repository structure

**Current decision:** the canonical frontend module boundaries are defined in
[ADR-014](./ADR-014-spatial-ui-technical-architecture.md). The exploratory
canvas/inti/protocol tree below is historical design vocabulary only; it must
not be implemented as a second runtime architecture. New work belongs under
the ADR-014 structure, while shared presentation components remain usable by
both Classic UI and Spatial UI.

```text
ui/
├── app/
├── canvas/
│   ├── engine/
│   ├── layout/
│   ├── relations/
│   └── viewport/
│
├── inti/
│   ├── presence/
│   ├── states/
│   ├── audio/
│   └── controls/
│
├── interaction/
│   ├── seed/
│   ├── text/
│   ├── voice/
│   ├── attachments/
│   └── context-picker/
│
├── components/
│   ├── conversation/
│   ├── logs/
│   ├── files/
│   ├── agents/
│   ├── endpoints/
│   ├── economics/
│   └── system/
│
├── presentation/
│   ├── schema/
│   ├── registry/
│   ├── planner-client/
│   └── validation/
│
├── state/
│   ├── workspace/
│   ├── objects/
│   ├── relations/
│   └── persistence/
│
└── protocol/
    ├── events/
    ├── websocket/
    └── aidn/
```

---

# 55. Suggested TypeScript interfaces

```ts
type CanvasObjectType =
  | "agent"
  | "conversation"
  | "session"
  | "artifact"
  | "endpoint"
  | "service"
  | "log"
  | "file"
  | "image"
  | "audio"
  | "payment"
  | "contract"
  | "task"
  | "alert";

interface CanvasObject {
  id: string;
  type: CanvasObjectType;
  semanticRef?: string;
  state: Record<string, unknown>;
  layout: ObjectLayout;
  presentation: PresentationState;
}

interface ObjectLayout {
  x: number;
  y: number;
  width: number;
  height: number;
  z: number;
  mode: "auto" | "user" | "pinned" | "locked";
}
```

---

# 56. Presentation Operation

```ts
interface PresentationOperation {
  op:
    | "create"
    | "update"
    | "remove"
    | "link"
    | "unlink"
    | "focus"
    | "expand"
    | "collapse"
    | "highlight";

  target?: string;
  component?: string;
  semanticRef?: string;
  props?: Record<string, unknown>;

  relation?: {
    target: string;
    type: string;
  };
}
```

---

# 57. Agent output contract

```yaml
agent_response:
  speech:
    text: optional

  message:
    text: optional

  presentation:
    operations: []

  actions:
    proposed: []
```

---

# 58. Invariants

## UI-INV-001
Основной агент MUST оставаться доступным пользователю.

## UI-INV-002
Пользователь MUST иметь возможность взаимодействовать без голоса.

## UI-INV-003
Agent-generated presentation MUST проходить schema validation.

## UI-INV-004
LLM MUST NOT исполнять arbitrary frontend code.

## UI-INV-005
Manual user layout MUST иметь приоритет над auto-layout.

## UI-INV-006
Canvas presentation MUST NOT быть authority для protocol state.

## UI-INV-007
Любое опасное действие MUST проходить обычные permission/approval checks.

## UI-INV-008
Удаление визуального объекта MUST NOT удалять сетевую/ledger историю.

## UI-INV-009
Relation edges SHOULD отражать реальные semantic relationships.

## UI-INV-010
Audio failure MUST NOT блокировать управление системой.

---

# 59. Что НЕ нужно реализовывать в первой версии

Deferred:

```text
full 3D engine
VR/AR
physics simulation
particle-heavy environment
fully autonomous layout AI
shared multiplayer canvas
real-time collaborative editing
complex animation editor
custom arbitrary UI generation
```

---

# 60. Главный технический риск

Главный риск не rendering.

Главный риск:

```text
agent intent
→ predictable presentation
```

Если агент будет хаотично создавать объекты, UI быстро превратится в свалку.

Поэтому Presentation Planner и Layout Policy являются ключевыми подсистемами.

---

# 61. Anti-chaos rules

Agent SHOULD:

```text
reuse existing object
instead of duplicating

update
instead of recreate

group related items

collapse stale details

avoid creating low-value objects

prefer focus over duplication
```

---

# 62. Garbage collection UI

Presentation GC:

```text
temporary object
inactive
not pinned
not referenced
↓
eligible for visual cleanup
```

GC MUST NOT удалять underlying system data.

---

# 63. Search and recall

Пользователь может сказать:

```text
"Покажи вчерашнюю сессию с image agent."
```

Agent:

```text
search semantic workspace
↓
focus artifact
↓
bring into near-space
```

---

# 64. Multiple workspaces

Later:

```text
Main
Network Investigation
Endpoint Debugging
Research
Testnet
```

Но пользователь SHOULD переключаться через natural language или spatial navigation, а не через обязательные tabs.

---

# 65. Visual identity

Основные свойства:

```text
white
translucent
soft
cold
atmospheric
minimal
slow
material
```

Акцентные цвета принадлежат состояниям, а не branding decorations.

Visual language formalized in [ADR-013](./ADR-013-aidn-milky-glass-neumorphism-visual-design.md);
technical rendering constraints and material/runtime rules are in
[ADR-014](./ADR-014-spatial-ui-technical-architecture.md).

---

# 66. Performance budget

Target desktop:

```text
60 FPS interactions
< 100 ms click response
< 16 ms average render frame
lazy render far-space objects
```

Для большого числа объектов:

```text
quality profiles: low / mobile / desktop / high
LOD0–LOD3
relation culling
offscreen suspension
reduced motion / high contrast modes
```

MVP target:

```text
WebGL2
60 FPS on desktop interaction profile
< 100 ms click/focus response
~16 ms average frame target
mobile profile with reduced particles/transmission/post-processing
no DoF in MVP
```

Renderer capability detection SHOULD учитывать WebGL2, GPU/browser
capabilities, device memory, DPR, screen size and accessibility preferences.

---

# 67. Semantic LOD

Level of Detail:

```text
LOD0
tiny point / sprite

LOD1
simple translucent sphere / cube

LOD2
physical material + semantic marker

LOD3
particles, orbital curves and full interaction detail
```

Выбор зависит от:

```text
zoom
distance
focus
importance
```

---

# 68. Testing

## Unit

```text
Interaction Seed transitions
layout constraints
schema validation
state transitions
keyboard handling
```

## Visual

```text
screenshot regression
animation states
responsive behavior
reduced motion
```

## Agent

```text
same intent
→ expected component type

endpoint failure
→ diagnostic object

show logs
→ LogViewer

show relationships
→ Graph
```

---

# 69. UX acceptance scenarios

## Scenario A
Пользователь загружает UI.

Expected:

```text
white atmospheric environment
soft horizon and fog
Inti visible
no menus
no bars
no dashboard
```

## Scenario B
Click Inti.

Expected:

```text
listening state
voice acknowledgement
speech input
```

## Scenario C
Click empty space + type.

Expected:

```text
Interaction Seed
→ morph
→ expanding input
```

## Scenario D
Submit.

Expected:

```text
Conversation Surface
streaming response
```

## Scenario E
Close conversation.

Expected:

```text
artifact compaction
move to side space
```

## Scenario F
Single click artifact.

Expected:

```text
relations appear
```

## Scenario G
Double click artifact.

Expected:

```text
artifact moves center
expands
conversation restored
```

---

# 70. Final architecture

**Decision:** [ADR-011 — Agent-Mediated Component Interface and Resource Semantics](./ADR-011-agent-mediated-component-interface.md)
и [ADR-014 — Spatial UI Technical Architecture and Rendering Boundary](./ADR-014-spatial-ui-technical-architecture.md).

```text
                      HUMAN
                        │
              voice / text / files
                        │
                        ▼
                 PRIMARY AGENT
                     "INTI"
                        │
         ┌──────────────┼──────────────┐
         │              │              │
         ▼              ▼              ▼
      Reasoning       Tools          AiDN
         │                              │
         └──────────────┬───────────────┘
                        │
                        ▼
              Presentation Planner
                        │
                        ▼
              Presentation Intent
                        │
                        ▼
              Presentation Planner
                        │
        ┌───────────────┴────────────────┐
        ▼                                ▼
 React DOM / Component Registry     R3F / Three.js
        │                                │
        └───────────────┬────────────────┘
                        │
                        ▼
               Spatial Workspace Model
```

Node data поступают через query/event adapters, затем преобразуются в
view models. Primary Agent управляет действиями через MCP; UI только
создаёт validated intent и отображает authoritative result.

---

# 71. Итоговая продуктовая формулировка

> Inti Spatial Agent Interface — это агентно-центричная пространственная рабочая среда, в которой основной AI-агент является постоянным присутствием, а разговоры, инструменты, удалённые агенты, endpoint'ы, файлы, задачи, платежи и результаты проявляются как временные или постоянные объекты вокруг него.

Пользователь не ищет нужную страницу.

Пользователь выражает намерение.

Агент изменяет пространство так, чтобы нужная информация и действия появились непосредственно в текущем контексте.

---

# 72. Реализация: рекомендуемый порядок

```text
1. Cloud background
2. Inti visual prototype
3. Interaction Seed
4. Morphing text surface
5. Conversation Surface
6. Session Artifact
7. Drag / focus / expand / collapse
8. Relation Layer
9. Real local agent
10. STT/TTS
11. Presentation Schema
12. Component Registry
13. Layout Engine
14. System objects
15. Mediated AiDN remote resources
16. Economics visualization
17. Persistent spatial memory
18. Semantic zoom
19. Proactive hooks
20. Production hardening
```

Это позволяет получить работающий, визуально убедительный прототип очень рано, не дожидаясь полной реализации AiDN Protocol.
