# ADR-009 — Multi-Device Workspace and Mobile Spatial Navigation

**Статус:** Accepted  
**Дата решения:** 2026-09-04  
**Область:** Spatial Agent Interface, multi-device workspace, viewport, camera, touch navigation, synchronization  
**Связанный вопрос:** [SPATIAL-Q-009 — Синхронизация между устройствами](./OPEN-QUESTIONS.md#spatial-q-009--синхронизация-между-устройствами)  
**Связанные решения:** [ADR-001 — Node-scoped Primary Agent](./ADR-001-primary-agent-scope.md), [ADR-002 — Node Workspace Ownership](./ADR-002-node-workspace-ownership.md), [ADR-006 — Workspace Sessions and Context Graph](./ADR-006-workspace-sessions-context-graph.md), [ADR-007 — Spatial Memory, Aging and Clustering](./ADR-007-spatial-memory-aging-clustering.md), [ADR-008 — Entity Uniqueness and Provenance References](./ADR-008-entity-uniqueness-and-provenance.md)  
**Исходный план:** [AiDN Spatial Agent Interface — Implementation Plan](./AiDN-Spatial-Agent-Interface-Implementation-Plan.md)

## Решение

Desktop, tablet и mobile отображают один и тот же Node Workspace. Mobile не
является отдельной упрощённой моделью и не получает отдельную историю,
агентов, Endpoint или Session Graph. Устройства используют общий semantic
world, но имеют независимые viewport и camera state.

~~~text
                    Node Workspace
                         │
              ┌──────────┴──────────┐
              │                     │
         Desktop View          Mobile View
              │                     │
        wide viewport          narrow viewport
~~~

Главное правило:

~~~text
same semantic world
≠
same camera
~~~

Операторское перемещение camera на одном устройстве не должно самопроизвольно
перемещать camera на другом. Shared world, object identity и relations
остаются согласованными, а способ их показа адаптируется к viewport и
input modality.

## Shared Semantic World

Между устройствами синхронизируются:

- canonical object references и их revision;
- Primary Agent, Subagents и Remote Agents;
- Endpoint и Service entities;
- Workspace Sessions, Context Graph и provenance;
- Session Artifacts и Session Clusters;
- semantic relations и cluster membership;
- semantic world anchors и ручные workspace-level positions;
- pins, explicit keep-near overrides и presentation policy revision;
- availability и stale state, если они подтверждены authoritative source.

Эти данные являются частью одного Node Workspace согласно
[ADR-002](./ADR-002-node-workspace-ownership.md). Presentation projection
не должна создавать отдельную mobile semantic model.

## Device-Local Viewport

По умолчанию локальными для каждого устройства являются:

- camera orientation и transform;
- zoom;
- current focus и выбранный region;
- раскрытый объект или Focus Mode;
- временная selection;
- drag gesture в процессе выполнения;
- размер, плотность и arrangement адаптивного presentation surface;
- scroll position, bottom sheet state и keyboard state.

Текущий viewport можно восстановить на том же устройстве, но он не должен
рассылаться другим устройствам без явной команды оператора. Если оператор
выбирает Share View, система создаёт отдельную ephemeral viewport projection
с указанным audience и TTL. Это исключение не превращает локальную camera в
глобальный источник истины.

## Spherical Semantic Space

Workspace моделируется как сферическое semantic space вокруг Primary Agent.
Сфера является моделью координат и навигации, а не обязательным способом
рендеринга: конкретная реализация может использовать 2D projection, 2.5D,
3D scene или accessible structured view.

~~~text
                     AGENT SPACE
                        ╱
                       ╱
        SESSION       ●       OTHER CONTEXT
        MEMORY      Primary
                    Agent
                       ╲
                        ╲
                 RECENT SESSIONS
                   ENDPOINT ARC
~~~

Primary Agent выступает canonical origin для HOME orientation. Semantic
regions и world anchors располагаются относительно него:

- Agent Space — слева или сверху;
- Session Cluster и Deep Memory — справа или в дальней зоне;
- Recent Memory — ниже Primary Agent;
- Endpoint Arc — перед или ниже активного центра;
- Attention Orbit — вокруг Primary Agent согласно [ADR-003](./ADR-003-orbital-attention-system.md);
- Deep Memory — дальше от текущего focus, согласно [ADR-007](./ADR-007-spatial-memory-aging-clustering.md).

Сферическая модель помогает связать aging и навигацию: оператор может
отдалиться от текущего центра, повернуть semantic space и приблизиться к
кластеру или artifact, не меняя саму Workspace topology.

## Semantic Position и Presentation Geometry

Semantic world anchor и relations являются общими для устройств. Размер
объекта, форма expanded surface, плотность подписей и arrangement дочерних
элементов могут быть device-dependent.

~~~text
shared:
  object identity
  semantic world anchor
  relation
  cluster membership
  pin / manual workspace position

device-local:
  camera
  zoom
  focus
  selection
  expanded geometry
  touch arrangement
~~~

Большая таблица или Conversation Surface не должна синхронизироваться как
фиксированные пиксели. На desktop она может занимать большую область, на
mobile открываться как focus card или bottom sheet, сохраняя тот же
semantic_ref и provenance. Устройство не должно показывать пользователю
случайную левую четверть объекта только потому, что desktop geometry
слишком велика.

Изменение presentation geometry не является canonical mutation. Это правило
согласуется с [ADR-008](./ADR-008-entity-uniqueness-and-provenance.md):
разные views ссылаются на одну entity и не создают её копии.

## HOME Orientation

При первом открытии Workspace на устройстве камера выполняет
FOCUS_PRIMARY_AGENT:

~~~text
horizontal: center
vertical: slightly above center

below:
Recent Session Artifacts
~~~

Последующее открытие на том же устройстве может восстановить локальный
viewport, если Workspace revision совместима. Команда HOME или
FOCUS_PRIMARY_AGENT всегда возвращает камеру к Primary Agent и безопасной
области Active Work.

FOCUS_PRIMARY_AGENT используется:

- при первом открытии нового устройства;
- после выхода из Focus Mode;
- после восстановления из offline или stale viewport;
- по явной команде оператора;
- как безопасный fallback, если сохранённая camera указывает на удалённый
  или недоступный объект.

Автоматический HOME переход не должен происходить во время активного ввода
или незавершённой операции без явного recovery reason.

## Desktop Navigation

Desktop использует привычные pointer и keyboard equivalents:

~~~text
mouse drag       → rotate / pan Workspace
wheel            → zoom
click            → select / open
double click     → focus / inspect
click empty      → Interaction Seed
hover            → reveal metadata
keyboard focus   → navigate semantic objects and relations
HOME             → FOCUS_PRIMARY_AGENT
~~~

Трёхмерное перемещение, если оно используется, должно оставаться обратимым:
ESC, HOME или явная кнопка возврата восстанавливают понятный focus.

## Mobile Navigation

Touchscreen является прямым способом навигации по тому же semantic space:

~~~text
one-finger drag          → rotate / pan Workspace
pinch                    → zoom out
spread                   → zoom in
tap object               → select / open
tap Primary Agent        → voice interaction
long press empty space   → Interaction Seed
drag object              → reposition / manipulate
long press object        → object actions
swipe left / right       → rotate toward semantic region
HOME control             → FOCUS_PRIMARY_AGENT
~~~

Жесты не должны быть единственным способом выполнить действие. Для каждого
жеста существуют button, keyboard или командная альтернатива. Touch target
должен покрывать semantic object или кластер, а не требовать попадания в
маленькую декоративную деталь.

Swipe left/right изменяет orientation или camera focus. Он не открывает
новую страницу и не создаёт mobile-only branch.

Трёхпальцевые semantic shortcuts из [ADR-007](./ADR-007-spatial-memory-aging-clustering.md)
могут использоваться как быстрый переход к Cluster Memory или Agent Space.
Они дополняют, а не заменяют one-finger rotate/pan и также должны иметь
button и keyboard equivalents.

## Interaction Seed на mobile

Long press в свободной точке создаёт Interaction Seed именно в этой
semantic области:

~~~text
long press empty space
        ↓
Interaction Seed
        ↓
Input Surface
~~~

В Seed сохраняются одинаковые semantic actions для desktop и mobile:

- File;
- Image;
- Voice;
- Context;
- Link;
- Action;
- More.

Radial controls могут превращаться в bottom sheet или touch-friendly row,
но action semantics, authorization и provenance остаются общими. Создание
Seed не должно менять canonical world position до явного подтверждения
оператора.

## Touch и Voice

Tap Primary Agent открывает voice interaction или доступную альтернативу,
но не создаёт отдельный mobile Agent. Voice input формирует Workspace Session
Root по правилам [ADR-006](./ADR-006-workspace-sessions-context-graph.md).

Во время жеста система должна различать:

- camera manipulation;
- object drag;
- relation focus;
- Interaction Seed creation;
- long press context menu.

Ошибочное распознавание жеста должно быть отменяемым и не должно выполнять
destructive action без подтверждения.

## Synchronization Contract

Каждая mutation в shared Workspace содержит:

~~~yaml
workspace_mutation:
  event_id:
  workspace_id:
  device_id:
  actor_ref:
  base_revision:
  operation:
  payload:
  logical_clock:
  created_at:
~~~

Правила синхронизации:

1. Semantic object, relation, cluster membership и workspace-level anchor
   применяются через canonical Workspace command path.
2. Device-local camera, selection и expanded geometry не входят в обычный
   shared event stream.
3. Непересекающиеся изменения объединяются.
4. Конфликтующие изменения проверяются по base_revision.
5. Для MVP deterministic winner выбирается по monotonic workspace revision с
   device_id как tie-breaker; проигравшее значение сохраняется в audit/undo
   history и может быть восстановлено оператором.
6. Повторная доставка event_id идемпотентна.
7. Неавторизованное или stale mutation отклоняется с причиной и не
   переписывает semantic world.
8. Share View создаёт отдельную ephemeral projection и не меняет default
   camera другого устройства.

В будущем conflict resolution может быть уточнён отдельным RFC, но базовые
инварианты общего semantic world не меняются.

## Offline и partial sync

Устройство может открыть последний согласованный Workspace snapshot в
offline режиме. Неприменённые local mutations помещаются в очередь с
idempotency key и отображаются как pending.

При восстановлении связи:

- сначала проверяется Workspace revision;
- затем применяются только разрешённые операции;
- конфликт показывается оператору через recovery surface;
- stale object не превращается в новый object;
- camera и локальный focus могут быть восстановлены независимо от
  semantic sync.

Если Primary Agent или remote service недоступен, UI сохраняет доступ к
semantic history и показывает unavailable state согласно [ADR-007](./ADR-007-spatial-memory-aging-clustering.md).

## Privacy и security

Синхронизация выполняется только для Workspace, к которому устройство имеет
capability. Transport и server-side storage должны использовать
аутентифицированный защищённый канал.

Не разрешается:

- синхронизировать приватный input на устройство без его authorization;
- выдавать local viewport share за permanent Workspace state;
- раскрывать private provenance через публичный camera event;
- использовать mobile snapshot как authoritative source без revision check.

Presentation projection не расширяет права доступа. Это согласуется с
ownership и access rules [ADR-002](./ADR-002-node-workspace-ownership.md) и
provenance rules [ADR-008](./ADR-008-entity-uniqueness-and-provenance.md).

## Accessibility и Reduced Motion

Сферическая и пространственная модель должна иметь non-spatial fallback:

- логический список regions и objects;
- keyboard traversal по semantic order;
- screen-reader labels для Primary Agent, cluster, artifact и relation;
- action для HOME, focus source, focus target и возврата;
- text alternative для camera-only transitions.

При prefers-reduced-motion:

- вращение заменяется коротким reposition или fade;
- flying objects заменяются direct focus transition;
- pulses и floating motion заменяются статическим halo;
- focus restoration не использует обязательную инерцию.

Оператор должен иметь возможность остановить auto-focus, закрыть bottom sheet
и вернуться к предыдущему focus без потери context.

## Performance и responsive budget

Renderer не должен загружать отдельную полную сцену для каждого устройства.
Он получает semantic model и материализует device-specific projection через
LOD и culling, определённые [ADR-007](./ADR-007-spatial-memory-aging-clustering.md).

Для mobile дополнительно требуются:

- bounded number of materialized objects;
- progressive loading summaries и thumbnails;
- отменяемая загрузка relation details;
- сохранение frame budget во время pinch и rotate;
- отсутствие полного re-layout при каждом pixel движения пальца.

Responsive layout может менять размер и способ раскрытия объекта, но не
смысл, identity или relation.

## Модель данных

~~~yaml
workspace_world:
  workspace_id:
  node_id:
  coordinate_model: spherical_semantic_space
  primary_agent_ref:
  world_revision:
  semantic_objects:
    - canonical_ref:
      semantic_anchor:
        theta:
        phi:
        radius:
      region:
      manual_override:
      revision:
  relations:
  clusters:
  pins:
  provenance:
~~~

~~~yaml
device_viewport_state:
  workspace_id:
  device_id:
  camera_orientation:
  camera_transform:
  zoom:
  focus_region:
  focus_anchor_ref:
  selection_refs:
  expanded_ref:
  local_layout_revision:
  updated_at:
~~~

~~~yaml
presentation_geometry:
  workspace_id:
  device_id:
  semantic_ref:
  variant:
  width:
  height:
  density:
  arrangement:
  revision:
~~~

Device viewport state и presentation geometry не становятся канонической
semantic relation. Они могут быть сброшены без потери Workspace.

## Инварианты

**UI-INV-M01 — Shared Workspace**

Desktop и mobile MUST представлять один semantic Node Workspace.

**UI-INV-M02 — Device-local Viewport**

Viewport и camera state являются device-local, если оператор явно не
выполнил Share View.

**UI-INV-M03 — Shared Semantic Anchors**

Semantic object position, relations и cluster membership SHOULD оставаться
согласованными между устройствами.

**UI-INV-M04 — Adaptive Geometry**

Presentation geometry MAY адаптироваться к viewport, размеру экрана и input
modality без изменения identity и semantics.

**UI-INV-M05 — Canonical Home**

Primary Agent определяет canonical HOME orientation Workspace.

**UI-INV-M06 — No Page Split**

Gesture navigation меняет camera focus, а не создаёт отдельную mobile page,
Workspace или Context Graph branch.

**UI-INV-M07 — Explicit Sharing**

Camera или focus другого устройства не изменяются без явного Share View и
указанного audience.

**UI-INV-M08 — Deterministic Sync**

Shared mutations имеют revision и idempotency key; конфликт не должен
молча переписывать semantic history.

**UI-INV-M09 — Accessible Equivalent**

Каждая touch или spatial action имеет keyboard, button или structured
semantic equivalent.

## Реализационные слайсы

1. **Shared world schema.** Ввести workspace world anchors, device-local
   viewport state и presentation geometry.
2. **HOME orientation.** Реализовать FOCUS_PRIMARY_AGENT и восстановление
   local camera с безопасным fallback.
3. **Desktop projection.** Связать существующий canvas/layout с semantic
   regions и world anchors.
4. **Mobile navigation.** Добавить rotate/pan, pinch, long press Seed,
   touch targets и bottom-sheet focus surface.
5. **Sync protocol.** Реализовать revision, idempotency, offline queue,
   deterministic conflict handling и Share View.
6. **Adaptive geometry.** Отделить semantic anchor от размеров таблиц,
   Conversation Surface и inspect panels.
7. **Accessibility.** Добавить keyboard/screen-reader representation,
   reduced-motion и non-spatial fallback.
8. **Scale tests.** Проверить открытие одного Workspace на desktop, tablet и
   mobile, параллельное перемещение camera, конфликт layout, offline
   mutation и возврат HOME.

## Положительные последствия

- Mobile становится полноценным окном в Node Workspace, а не урезанным
  приложением.
- Desktop и mobile сохраняют общий semantic context без эффекта
  «полтергейста» от чужой camera.
- Сферическая модель естественно связывает aging, clusters, focus и
  navigation.
- Presentation geometry может быть адаптивной без клонирования сущностей.
- Touch и voice становятся альтернативными input modalities одной модели
  взаимодействия.

## Ограничения и риски

- Сферическая semantic model потребует понятного 2D/3D projection и
  accessible fallback.
- Одновременные manual moves требуют revision-aware conflict handling.
- Полная синхронизация world anchors не должна превращать каждый жест в
  сетевой event.
- Непредсказуемый auto-focus может мешать оператору; действуют HOME,
  explicit sharing и reduced-motion правила.
- Q-009 закрыт на уровне workspace contract, но transport, storage и
  multi-device conflict implementation требуют отдельной реализации.

## Не входит в это решение

Этот ADR не определяет:

- конкретный сетевой транспорт синхронизации;
- обязательный 3D engine или буквальный сферический renderer;
- глобальный viewport broadcast без явного Share View;
- экономический или protocol state, который не относится к Workspace
  presentation;
- окончательный CRDT и распределённое разрешение конфликтов;
- отдельную mobile semantic model или mobile-only object types.

## Критерии приёмки

Решение считается реализованным, когда:

- desktop, tablet и mobile открывают один Workspace и видят одни
  canonical entities;
- изменение semantic relation или cluster membership доступно на всех
  авторизованных устройствах после sync;
- camera, zoom и focus одного устройства не двигают другое без Share View;
- HOME и FOCUS_PRIMARY_AGENT возвращают камеру к Primary Agent;
- mobile gestures выполняют rotate/pan, zoom, selection и Seed creation;
- desktop и keyboard equivalents покрывают touch actions;
- presentation geometry адаптируется без клонирования entities;
- semantic positions и manual anchors имеют revision и deterministic
  conflict handling;
- offline queue и duplicate event handling сохраняют consistency;
- stale и unauthorized mutations отклоняются с понятной причиной;
- reduced-motion и screen-reader сценарии доступны;
- Workspace с тысячами объектов использует LOD/culling и bounded render
  budget.

## Связанные документы

- [Реестр открытых вопросов](./OPEN-QUESTIONS.md)
- [ADR-001 — Node-scoped Primary Agent](./ADR-001-primary-agent-scope.md)
- [ADR-002 — Node Workspace Ownership](./ADR-002-node-workspace-ownership.md)
- [ADR-003 — Orbital Attention System](./ADR-003-orbital-attention-system.md)
- [ADR-006 — Workspace Sessions and Context Graph](./ADR-006-workspace-sessions-context-graph.md)
- [ADR-007 — Spatial Memory, Aging and Clustering](./ADR-007-spatial-memory-aging-clustering.md)
- [ADR-008 — Entity Uniqueness and Provenance References](./ADR-008-entity-uniqueness-and-provenance.md)
- [Общий план Spatial Agent Interface](./AiDN-Spatial-Agent-Interface-Implementation-Plan.md)
