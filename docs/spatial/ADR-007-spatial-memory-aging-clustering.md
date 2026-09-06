# ADR-007 — Spatial Memory, Aging and Clustering

**Статус:** Accepted  
**Дата решения:** 2026-09-04  
**Область:** Spatial Agent Interface, долгоживущее Workspace, memory layout, retention, rendering  
**Связанный вопрос:** [SPATIAL-Q-007 — Долгоживущее рабочее пространство и архивирование](./OPEN-QUESTIONS.md#spatial-q-007--долгоживущее-рабочее-пространство-и-архивирование)  
**Связанные решения:** [ADR-002 — Node Workspace Ownership](./ADR-002-node-workspace-ownership.md), [ADR-003 — Orbital Attention System](./ADR-003-orbital-attention-system.md), [ADR-005 — Spatial Entity Topology](./ADR-005-spatial-entity-topology.md), [ADR-006 — Workspace Sessions and Context Graph](./ADR-006-workspace-sessions-context-graph.md)  
**Следующий связанный вопрос:** [SPATIAL-Q-008 — Канонический объект и его presentation instances](./OPEN-QUESTIONS.md#spatial-q-008--канонический-объект-и-его-presentation-instances)  
**Исходный план:** [AiDN Spatial Agent Interface — Implementation Plan](./AiDN-Spatial-Agent-Interface-Implementation-Plan.md)

## Решение

Workspace является пространственной памятью Node, а не бесконечным dashboard и
не списком чатов. История не удаляется только потому, что перестала быть
активной: новые объекты располагаются рядом с Primary Agent, связанные объекты
собираются в тематические кластеры, а неактивные объекты постепенно уходят в
периферийные и виртуализированные слои.

Пространственная организация является presentation projection над semantic
model. Она не изменяет ownership, canonical objects, Context Graph,
provenance или протокольные записи. Это связывает решение с [ADR-002](./ADR-002-node-workspace-ownership.md)
и [ADR-006](./ADR-006-workspace-sessions-context-graph.md): Workspace сохраняет
свою Node-scoped принадлежность, а Session и relation semantics остаются
каноническими независимо от положения объекта на canvas.

Главный принцип:

~~~text
Workspace не очищается по мере накопления истории.
Workspace пространственно стареет.

новое       → рядом с Primary Agent
недавнее    → в зоне быстрого доступа
связанное   → в semantic cluster
старое      → в глубине пространства
неактивное  → виртуализируется, но не исчезает
~~~

## Термины и границы

- **Spatial Memory** — слой presentation state, который определяет preferred
  region, возрастной класс, видимость и уровень детализации объекта.
- **Session Artifact** — компактное представление закрытой или свёрнутой
  Workspace Session. Его semantic reference и provenance определяются
  [ADR-006](./ADR-006-workspace-sessions-context-graph.md).
- **Session Cluster** — presentation construct для тематически или структурно
  связанных объектов. Cluster не является новой protocol entity и не заменяет
  canonical object.
- **Preferred Region** — семантически закреплённая область Workspace. Она
  помогает сформировать пространственную память, но не является жёсткой
  пиксельной координатой.
- **Memory Level** — Active Work, Recent Memory, Cluster Memory или Deep
  Memory; уровень определяет presentation policy, а не право доступа.
- **Virtualized Artifact** — объект, который существует в semantic model, но
  не рендерится как полноценная сцена до тех пор, пока он не станет релевантным.
- **Pull-to-Focus** — временное привлечение удалённого объекта или relation в
  текущий viewport без переписывания его canonical World Space position.

Этот ADR определяет пространственное старение, кластеризацию, навигацию и
рендеринг. Конкретная схема canonical objects и presentation instances
останется предметом [SPATIAL-Q-008](./OPEN-QUESTIONS.md#spatial-q-008--канонический-объект-и-его-presentation-instances),
а межустройственная синхронизация — предметом
[SPATIAL-Q-009](./OPEN-QUESTIONS.md#spatial-q-009--синхронизация-между-устройствами).

## Preferred Spatial Regions

Workspace SHOULD сохранять устойчивые пространственные ориентиры вокруг
Primary Agent. Layout Engine может адаптировать их к размеру viewport, но не
должен превращать их в набор независимых страниц.

~~~text
┌─────────────────────────────────────────────────────┐
│                                                     │
│   Agent Space                 Session Memory        │
│   upper-left                 upper-right            │
│                                                     │
│                  ● Primary Agent                    │
│                                                     │
│              Recent Memory                          │
│              lower-center                           │
│                                                     │
│             Endpoint Arc / Discovery                │
│                  lower-area                         │
│                                                     │
└─────────────────────────────────────────────────────┘
~~~

Каноническая семантика preferred regions:

| Region | Назначение | Базовый состав |
|---|---|---|
| Active Work | текущая работа и объекты, требующие немедленного внимания | Primary Agent, активная Conversation Surface, selected Endpoint |
| Agent Space | агенты и делегированные ветви | Subagents, Remote Agents и их локальные relation projections |
| Recent Memory | последние закрытые или свёрнутые взаимодействия | 5–10 наиболее свежих Session Artifacts по умолчанию |
| Cluster Memory | организованная долговременная память | Session Clusters и их summary objects |
| Endpoint Arc | временные результаты discovery | найденные Endpoint и Service Energy Objects |
| Deep Memory | старые, редко используемые и виртуализированные объекты | offscreen artifacts, cluster summaries, relation anchors |

Preferred regions являются рекомендациями для layout, а не ограничениями для
оператора. Оператор может переместить, закрепить или временно сфокусировать
объект. Автоматический layout не должен постоянно возвращать объект в
исходную позицию после ручного перемещения.

## Memory Levels

Пространство разделяется на четыре уровня памяти:

~~~text
                    DEEP MEMORY
                old / offscreen / fog
               CLUSTER MEMORY
             semantic session groups
                 upper-right
                RECENT MEMORY
            latest session artifacts
                below agent
                ACTIVE WORK
                   ●
~~~

### Active Work

Active Work содержит текущую Conversation Surface, выбранные объекты,
ожидающие решения relation и активные протокольные операции. Эти объекты не
должны стареть, пока остаются частью незавершённого interaction context.

### Recent Memory

После закрытия Conversation Surface или её компактизации в Session Artifact
объект помещается под Primary Agent, ближе к центру. В зоне поддерживается
ограниченное число полноценных представлений. Новый артефакт появляется
ближе к центру, более старые постепенно смещаются наружу.

### Cluster Memory

Если артефакт получил descendants, был продолжен через
CONTINUES_FROM или устойчиво связан с другими объектами по теме, он может
перейти из Recent Memory в Cluster Memory. Нижняя область таким образом
остаётся inbox свежей памяти, а верхняя правая — пространством организованных
ветвей.

### Deep Memory

Старые или редко используемые объекты уходят в периферийную область, Cloud
Space или за пределы текущего viewport. Их semantic records, provenance,
поисковая доступность и relation anchors сохраняются.

Переход между уровнями меняет presentation state. Он не является удалением,
закрытием protocol session или отзывом capability.

## Session Artifact

Session Artifact SHOULD выглядеть как компактный volumetric memory object:

- мягкий куб или другая форма с сильно сглаженными гранями;
- полупрозрачный metallic, glass-like или нейтральный material;
- слабый внутренний glow и спокойное floating motion;
- умеренный цветовой tint, связанный с классификацией или темой;
- отсутствие постоянного длинного текста на поверхности.

Цвет не должен быть случайным декоративным шумом и не является единственным
источником смысла. Semantic state остаётся доступным через focus, inspect и
текстовую альтернативу.

Hover или focus по области кластера SHOULD постепенно раскрывать:

- название или generated title;
- timestamp;
- краткое summary;
- связанного Agent или Endpoint;
- текущий presentation status;
- unresolved или attention marker;
- число descendants и связанных context references.

Hit area должна покрывать смысловую область кластера, а не только точную
геометрию маленького куба. Это особенно важно для touch-устройств и
низкой точности pointer input.

## Aging Model

Агинг определяется не только временем создания, а временем неактивности,
повторным использованием, релевантностью и явным закреплением. Базовый
lifecycle:

~~~text
NEW
 ↓
RECENT
 ↓
OLDER
 ↓
CLUSTERED
 ↓
PERIPHERAL
 ↓
VIRTUALIZED
~~~

- **NEW** — объект только создан или обновлён и находится в Active Work.
- **RECENT** — закрытый объект в зоне Recent Memory.
- **OLDER** — объект покинул ближний центр, но остаётся полноценным
  представлением.
- **CLUSTERED** — объект включён в semantic cluster или контекстную ветвь.
- **PERIPHERAL** — объект находится в дальней зоне или Cloud Space и имеет
  пониженный visual prominence.
- **VIRTUALIZED** — объект представлен summary, LOD0 point, relation anchor
  или searchable record.

Layout Engine SHOULD использовать устойчивый приоритет размещения, основанный
на следующих факторах:

~~~text
effective distance
  ↑ age
  ↑ inactivity
  ↓ relevance
  ↓ pin weight
  ↓ recent reuse
~~~

Это концептуальная модель, а не обязательная формула конкретной реализации.
Реализация MUST быть детерминированной для одинакового входного состояния и
должна использовать hysteresis, чтобы объект не прыгал между зонами из-за
малого изменения score.

Состояния PINNED, ACTIVE и явное KEEP_NEAR оператора могут временно отменять
автоматическое удаление из Recent Memory или отодвигание в Deep Memory.
Удаление presentation instance не удаляет semantic object и не отменяет его
provenance.

## Session Cluster Promotion

Артефакт может быть повышен до Session Cluster, если выполнено хотя бы одно
условие:

1. от него создан один или несколько descendants;
2. через него продолжается Context Graph;
3. он устойчиво связан с тем же проектом, Endpoint, Agent, subsystem или
   task family, что и другие артефакты;
4. оператор явно объединил его с другими объектами.

Promotion SHOULD быть обратимым на уровне presentation policy, но не должен
разрывать semantic relations. У кластера есть собственное summary
presentation, а member references остаются доступными при раскрытии.

~~~text
BEFORE
        ● Primary Agent
          ▣ A

AFTER CONTINUES_FROM / descendants
                         Session Cluster
                          ▣ A
                           \
                            ▣ B
             ● Primary Agent
~~~

Кластер не должен вести себя как папка файлового менеджера. Это облако
related artifacts с общей spatial presentation и возможностью раскрыть
provenance.

## Semantic Session Clustering

Критерии кластеризации MAY включать:

- общий structural parent или Context Graph branch;
- общий проект или topic;
- общий Endpoint или Agent;
- один subsystem Node;
- одна task family;
- semantic similarity, вычисленная отдельным индексом;
- явную ручную группировку оператора.

Система SHOULD объяснять причину принадлежности при inspect кластера.
Embedding similarity может быть дополнительным сигналом, но не должна
создавать скрытую или непроверяемую связь: каждая membership relation
должна иметь criterion и revision.

Кластеризация не меняет canonical relation type из [ADR-006](./ADR-006-workspace-sessions-context-graph.md).
Например, similarity cluster не превращает два объекта в parent и child и не
создаёт новую AiDN Protocol Session.

## Semantic Gesture Navigation

Жесты перемещают camera focus между major regions и не переключают страницы.
Базовая схема для touch-устройств:

~~~text
three-finger swipe left  → Session Cluster / Cluster Memory
three-finger swipe right → Agent / Subagent Space
three-finger swipe down  → центр на Primary Agent
~~~

Жест MUST сохранять Workspace topology и canonical World Space coordinates.
Инерция и переходы MAY использоваться, но должны быть ограничены и
прерываемы оператором.

Ни одна функция навигации не должна быть доступна только жестом. Для desktop и
keyboard должны существовать equivalent controls: region navigator, focus
buttons или командная палитра. Для screen reader должен существовать
структурированный список semantic regions и объектов.

На малом экране Layout Engine может показывать одну focused region за раз,
сохраняя те же semantic zones. Это camera composition, а не отдельная модель
данных.

## Relation Reveal

Исторические semantic threads по умолчанию должны быть спокойными и
малозаметными. При hover, keyboard focus или явном раскрытии кластера система
показывает:

- labels узлов;
- направление relation;
- тип relation;
- unresolved markers;
- controls для перехода к source и target.

Поддерживаемые relation labels включают:

~~~text
CONTINUES_FROM
USES_CONTEXT
CREATED_FROM
PRODUCED
DELEGATED_TO
USED_ENDPOINT
~~~

Каноническое направление хранится в semantic model. Визуальное направление
может зависеть от relation type. Например, CONTINUES_FROM хранится как
child → parent, но на canvas может быть показано как causal flow
parent → child. UI MUST явно раскрывать relation type, чтобы такое
представление не создавало двусмысленность.

Постоянные подписи на каждой нити запрещены для базового режима: они
перегружают workspace и превращают relation graph в таблицу. Для простой
связи достаточно glyph или тонкой линии; подробности появляются в inspect
surface.

## Pull-to-Focus

При focus relation MAY показывать directional controls:

~~~text
        ←     →
▣ A ───────────── ▣ B
~~~

Оператор может:

- сфокусировать source;
- сфокусировать target;
- временно привлечь удалённый объект в текущую область;
- открыть inspect relation или artifact.

Если target находится в Deep Memory или за пределами viewport, его presentation
может пройти по semantic thread из тумана в focus region. После просмотра
объект MAY вернуться в исходную область, остаться рядом до конца текущего
interaction или быть закреплён оператором.

Pull-to-Focus MUST изменять только camera transform или temporary focus proxy.
Canonical World Space position, cluster membership и provenance нельзя
переписывать как побочный эффект навигации.

Недоступный, отозванный или stale объект показывается как unavailable
reference с причиной и временем последней проверки. Система не должна
подменять отсутствующий объект выдуманным relation.

## Spatial Virtualization and Level of Detail

Semantic model может содержать сотни и тысячи Session Artifacts, но renderer
должен держать bounded render budget. По умолчанию в активном viewport
показываются примерно 10–30 полноценных объектов, а точные лимиты
конфигурируются с учётом устройства.

Offscreen artifacts MAY существовать как:

- cluster summary;
- LOD0 point или low-cost marker;
- relation anchor;
- searchable semantic record;
- thumbnail или compact metadata projection.

При приближении camera, открытии relation или Pull-to-Focus объект
материализуется через LOD:

~~~text
LOD0 → anchor / summary
LOD1 → compact volumetric object
LOD2 → labels, relations и interaction affordances
LOD3 → full inspect surface / Conversation Surface
~~~

Virtualization MUST быть детерминированной и не должна удалять semantic
records, audit trail, Context Graph или protocol references. Materialization
должна быть инкрементальной, отменяемой и безопасной при частичных сетевых
данных.

## Минимальная модель данных

Пространственный слой хранит projection, а не копию канонического объекта:

~~~yaml
spatial_memory_projection:
  id:
  workspace_id:
  semantic_ref:
    object_id:
    object_type:
    revision:
  session_ref:
  zone: active_work | agent_space | recent_memory | cluster_memory | endpoint_arc | deep_memory
  memory_level: active | recent | older | clustered | peripheral | virtualized
  age_class:
  created_at:
  last_active_at:
  last_reused_at:
  relevance_score:
  pin_weight:
  cluster_ref:
  lod: 0 | 1 | 2 | 3
  render_state: materialized | summarized | virtualized | unavailable
  world_position:
    x:
    y:
    z:
  manual_position_override:
  presentation_revision:
  provenance:
~~~

~~~yaml
session_cluster:
  id:
  workspace_id:
  title:
  criterion:
  criterion_revision:
  member_refs:
    - semantic_ref:
      projection_ref:
  summary_ref:
  collapsed:
  pinned:
  presentation_revision:
  provenance:
~~~

~~~yaml
viewport_focus:
  workspace_id:
  region:
  anchor_ref:
  camera_transform:
  source: pointer | keyboard | gesture | relation | agent
  restore_target:
  revision:
~~~

Инварианты:

1. semantic_ref указывает на canonical object и не содержит независимой копии
   authoritative данных.
2. Один semantic object может иметь несколько presentation projections,
   которые будут уточнены в [SPATIAL-Q-008](./OPEN-QUESTIONS.md#spatial-q-008--канонический-объект-и-его-presentation-instances).
3. Collapse, aging и virtualization не удаляют object, relation или
   provenance.
4. Structural parent и Context Graph semantics подчиняются [ADR-006](./ADR-006-workspace-sessions-context-graph.md).
5. world_position не изменяется camera focus и Pull-to-Focus.
6. manual_position_override имеет приоритет над автоматическим layout, пока
   оператор его не сбросит.
7. Cluster membership хранит criterion и revision, чтобы результат можно было
   объяснить и воспроизвести.
8. Unavailable references сохраняются с причиной, а не заменяются пустым или
   вымышленным объектом.

## Responsive, Accessibility и Motion

Spatial UI должен оставаться управляемым при desktop, mobile и keyboard
сценариях:

- touch-target включает область кластера, а не только пиксельный центр
  объекта;
- у каждой spatial action есть keyboard и button equivalent;
- focus order следует semantic order, а не случайному порядку DOM;
- screen reader получает роль объекта, название, memory level, relation type и
  состояние доступности;
- reduced-motion отключает floating motion, долгие перелёты и обязательную
  инерцию, заменяя их коротким fade или мгновенным focus transition;
- камера не должна самопроизвольно уводить оператора от текущей задачи;
  proactive focus требует явного attention state и возможности отмены;
- контраст, размер подписи и цветовые различия не должны быть единственным
  способом распознать возраст или кластер.

Визуальные переходы должны сообщать изменение semantic state, а не изображать
сетевые пакеты. Импульсы по relation допустимы для создания, обновления или
передачи результата, но потоковая генерация не должна превращать canvas в
непрерывную гирлянду.

## Rendering и эксплуатационные ограничения

Renderer SHOULD:

- использовать spatial culling и LOD;
- загружать relation и object metadata инкрементально;
- отделять semantic store от scene graph;
- сохранять frame budget отдельно для desktop и mobile;
- иметь telemetry materialized count, virtualized count, focus latency и
  dropped frames;
- корректно восстанавливаться после partial sync, reload и offline режима.

Layout Engine MUST обеспечивать стабильность: одинаковая semantic topology и
одинаковая policy revision должны давать сопоставимую раскладку. Небольшие
изменения timestamps или relevance не должны вызывать массовое перемещение
объектов.

## Реализационные слайсы

1. **Projection model.** Ввести spatial_memory_projection,
   session_cluster и viewport_focus с versioning и provenance.
2. **Preferred regions.** Реализовать зоны вокруг Primary Agent и bounded
   Recent Memory без жёсткой привязки к пикселям.
3. **Aging policy.** Добавить lifecycle, hysteresis, PINNED и ручной reset
   layout.
4. **Cluster promotion.** Поддержать promotion по descendants, context
   relations, semantic criteria и ручной группировке.
5. **Relation reveal.** Реализовать focus/hover/keyboard inspect, labels и
   Pull-to-Focus без изменения World Space.
6. **Virtualization.** Добавить culling, LOD0–LOD3, summary projections и
   materialization по demand.
7. **Responsive and accessibility pass.** Добавить gesture alternatives,
   reduced-motion, screen-reader representation и mobile focus composition.
8. **Benchmarks and telemetry.** Проверить 10, 1000 и 20 000 artifacts,
   partial sync, reload, stale references и long-lived Workspace.

## Положительные последствия

- Workspace получает понятную пространственную память без превращения в
  файловый менеджер или список чатов.
- Новые и актуальные объекты остаются под рукой, а история масштабируется за
  счёт кластеров и virtualization.
- Ветви Context Graph становятся видимыми только тогда, когда это полезно.
- Operator может вернуть объект из глубины через relation, не теряя
  исходную топологию.
- Переход к mobile и accessibility не требует отдельной semantic модели.

## Ограничения и риски

- Layout и semantic clustering требуют отдельной policy revision и
  воспроизводимого тестового набора.
- Неправильная кластеризация может создать ложное ощущение связи; criterion
  должен быть объяснимым и отменяемым.
- Слишком активная motion или auto-focus может мешать оператору; действует
  правило reduced-motion и explicit attention.
- Большое число relations потребует индексации, culling и защиты от
  массового materialization.
- Между устройствами нужно синхронизировать projection state отдельно от
  canonical objects; это остаётся частью Q-009.

## Не входит в это решение

Этот ADR не определяет:

- canonical object schema и окончательную семантику presentation instances;
- конкретный алгоритм embedding, vector database или semantic search;
- retention, юридическое удаление и экспорт пользовательских данных;
- CRDT, транспорт синхронизации и conflict resolution между устройствами;
- protocol ownership, billing, escrow или authorization policy;
- конкретный frontend framework, 3D engine или animation library.

## Критерии приёмки

Решение считается реализованным, когда:

- preferred regions стабильно ориентируют layout, но не блокируют ручное
  перемещение;
- новые Session Artifacts появляются в Recent Memory под Primary Agent;
- Recent Memory имеет ограниченный и проверяемый visible budget;
- старение переводит объекты в peripheral и virtualized representation без
  удаления semantic history;
- descendants и CONTINUES_FROM могут продвигать объект в Session Cluster;
- semantic и manual clustering показывают criterion и сохраняют provenance;
- gesture и keyboard navigation меняют camera focus, а не topology;
- relation labels и directional controls раскрываются по focus;
- Pull-to-Focus не переписывает World Space coordinates;
- offscreen objects materialize по demand и возвращаются в исходную область;
- stale и unavailable references показываются явно;
- desktop, mobile, keyboard, screen-reader, offline и reduced-motion
  сценарии покрыты тестами;
- renderer сохраняет bounded render budget на Workspace с тысячами артефактов.

## Связанные документы

- [Реестр открытых вопросов](./OPEN-QUESTIONS.md)
- [ADR-002 — Node Workspace Ownership](./ADR-002-node-workspace-ownership.md)
- [ADR-003 — Orbital Attention System](./ADR-003-orbital-attention-system.md)
- [ADR-005 — Spatial Entity Topology](./ADR-005-spatial-entity-topology.md)
- [ADR-006 — Workspace Sessions and Context Graph](./ADR-006-workspace-sessions-context-graph.md)
- [Общий план Spatial Agent Interface](./AiDN-Spatial-Agent-Interface-Implementation-Plan.md)
