# AiDN Spatial Agent Interface — реестр открытых вопросов

**Статус:** Draft  
**Версия:** 0.1  
**Дата формирования:** 2026-09-03  
**Область:** Spatial Agent Interface, модель данных, протокол взаимодействия и эксплуатационные сценарии

## Назначение документа

Этот документ содержит вопросы, по которым ещё не принято архитектурное или
продуктовое решение. Он предназначен для последовательного закрытия решений
перед реализацией пространственного интерфейса AiDN.

Реестр не является стенограммой обсуждения и не заменяет RFC, ADR или
техническое задание. После принятия решения соответствующий вопрос получает
статус **Decided**, а решение фиксируется в отдельном ADR/RFC и связывается с
реализационными задачами.

Последовательность реализации принятых решений, dependency graph, vertical
slices и acceptance gates находятся в
[Detailed Development Roadmap](./DEVELOPMENT-ROADMAP.md).

## Правила ведения

- Каждый вопрос имеет стабильный идентификатор SPATIAL-Q-nnn.
- Вопрос считается закрытым только после фиксации решения, владельца решения и
  проверяемых критериев приёмки.
- Изменение принятого решения должно сопровождаться новым ADR или записью о
  пересмотре существующего ADR.
- Термин «агент» в этом документе означает логическую сущность AiDN. Конкретный
  runtime, модель или MCP-подключение не меняют идентичность агента без
  отдельного решения.

### Статусы

Open — решение не принято.  
Under review — собраны варианты и идёт проверка.  
Decided — решение зафиксировано в ADR/RFC.  
Deferred — вопрос сознательно отложен до указанного этапа.  
Rejected — вариант или требование отклонены с обоснованием.

### Приоритеты

P0 — влияет на протокол, ownership, безопасность, экономику или каноническую
модель данных; без решения реализацию соответствующего потока начинать нельзя.  
P1 — влияет на ключевой пользовательский сценарий, масштабирование или
совместимость устройств.  
P2 — улучшение интерфейса или оптимизация, не блокирующая базовую реализацию.

## Первый батч вопросов

| ID | Тема | Приоритет | Статус | Зависимости |
|---|---|---:|---|---|
| SPATIAL-Q-001 | Семантика и жизненный цикл Primary Agent | P0 | Decided ([ADR-001](./ADR-001-primary-agent-scope.md)) | Q-002, Q-012 |
| SPATIAL-Q-002 | Ownership рабочего пространства | P0 | Decided ([ADR-002](./ADR-002-node-workspace-ownership.md)) | Q-001, Q-008 |
| SPATIAL-Q-003 | Автономные действия и проактивность | P1 | Decided ([ADR-003](./ADR-003-orbital-attention-system.md)) | Q-004, Q-011 |
| SPATIAL-Q-004 | Видимость состояний действия | P0 | Decided ([ADR-004](./ADR-004-primary-agent-visual-state-language.md)) | Q-003, Q-010 |
| SPATIAL-Q-005 | Жизненный цикл обнаружения удалённых агентов | P1 | Decided ([ADR-005](./ADR-005-spatial-entity-topology.md)) | Q-001, Q-012 |
| SPATIAL-Q-006 | Границы Session и вложенные операции | P0 | Decided ([ADR-006](./ADR-006-workspace-sessions-context-graph.md)) | Q-008, Q-011, Q-012 |
| SPATIAL-Q-007 | Долгоживущее рабочее пространство и архивирование | P1 | Decided ([ADR-007](./ADR-007-spatial-memory-aging-clustering.md)) | Q-002, Q-008, Q-009 |
| SPATIAL-Q-008 | Канонический объект и его presentation instances | P0 | Decided ([ADR-008](./ADR-008-entity-uniqueness-and-provenance.md)) | Q-002, Q-006 |
| SPATIAL-Q-009 | Синхронизация между устройствами | P1 | Decided ([ADR-009](./ADR-009-multi-device-workspace-and-mobile-navigation.md)) | Q-002, Q-007, Q-008 |
| SPATIAL-Q-010 | Recovery mode при недоступности Primary Agent | P0 | Decided ([ADR-010](./ADR-010-node-status-and-recovery-access.md)) | Q-001, Q-004, Q-011 |
| SPATIAL-Q-011 | Экономическая прозрачность и управление бюджетом | P0 | Decided ([ADR-011](./ADR-011-agent-mediated-component-interface.md)) | Q-003, Q-006, Q-010 |
| SPATIAL-Q-012 | Local Trust Boundary и mediated remote resource access | P0 | Decided ([ADR-012](./ADR-012-local-trust-boundary-and-mediated-remote-resources.md)) | Q-001, Q-002, Q-006, Q-008, Q-009, Q-010, Q-011 |

---

## SPATIAL-Q-001 — Семантика и жизненный цикл Primary Agent

**Область:** identity, workspace, memory, sessions  
**Приоритет:** P0  
**Статус:** Decided  
**Решение:** [ADR-001 — Node-scoped Primary Agent](./ADR-001-primary-agent-scope.md)

### Краткий итог решения

Primary Agent является Node-scoped ролью, назначенной конкретной AiDN Node.
Node имеет один Primary Agent Slot; конкретная Agent Identity и runtime
подключаются к slot через отдельный binding и capability grant. Замена агента
не удаляет состояние Node, workspace, историю Sessions или ledger state.

### Решение, которое требуется принять

Определить, что именно является Primary Agent:

- постоянно назначенный агент пользователя;
- агент конкретного устройства;
- агент конкретной AiDN-ноды;
- сменяемый пользователем агент, привязанный к workspace.

Необходимо также определить поведение при замене, отзыве, сбое или удалении
Primary Agent: судьбу памяти, активных сессий, артефактов, полномочий и
истории действий.

### Контекст и ограничения

Пространственный интерфейс строится вокруг присутствия Primary Agent. Поэтому
его идентичность должна быть стабильной и отделённой от конкретного процесса,
модели и MCP-транспорта. Иначе замена runtime будет выглядеть как потеря
пользовательского пространства.

### Критерии закрытия

- описан стабильный идентификатор Primary Agent и его владелец;
- определены операции assign, replace, suspend и revoke;
- задана миграция памяти, сессий и полномочий;
- описаны состояния недоступности и восстановления;
- решение отражено в ADR и проверено сценариями замены агента.

## SPATIAL-Q-002 — Ownership рабочего пространства

**Область:** ownership, persistence, access control  
**Приоритет:** P0  
**Статус:** Decided  
**Решение:** [ADR-002 — Node Workspace Ownership](./ADR-002-node-workspace-ownership.md)

### Краткий итог решения

Spatial Workspace принадлежит конкретной AiDN Node. Оператор управляет
Workspace, а Primary Agent работает внутри него как назначаемый способ
взаимодействия. Состояния Node, Workspace, агента и оператора разделяются;
замена или отказ агента не удаляет Workspace, историю, артефакты или ledger
state.

### Решение, которое требуется принять

Определить каноническую модель владения:

- Human → Workspace → Agent;
- Agent → Workspace → Human interaction;
- либо модель с отдельным Workspace Owner и делегированными агентами.

Нужно установить, кто имеет право читать, изменять, экспортировать и удалять
пространственные объекты, если агент заменён, отключён или скомпрометирован.

### Критерии закрытия

- определён canonical owner workspace;
- описаны права пользователя, Primary Agent и делегированных агентов;
- задано поведение при удалении или замене агента;
- определены экспорт, резервное копирование и восстановление workspace;
- модель проверена на сценариях смены агента и отзыва доступа.

## SPATIAL-Q-003 — Автономные действия и проактивность

**Область:** agent autonomy, notifications, object lifecycle  
**Приоритет:** P1  
**Статус:** Decided  
**Решение:** [ADR-003 — Orbital Attention System](./ADR-003-orbital-attention-system.md)

### Краткий итог решения

Автономные результаты не раскрывают интерфейс автоматически. Они проходят
policy/redaction и накапливаются как Attention Items. В Spatial UI они
представляются компактными Orbital Attention Markers вокруг Primary Agent;
раскрытие выполняется через Focus Mode и перемещение камеры, без изменения
координат объектов Workspace. Низкоприоритетные элементы агрегируются, а
критические не скрываются.

### Решение, которое требуется принять

Определить, как отображаются действия, инициированные агентом без
непосредственного запроса пользователя. Рассматриваемый сценарий: агент
создал подзадачу, обратился к удалённому агенту, потратил Q и сформировал
несколько артефактов, пока пользователь отсутствовал.

Нужно установить правила публикации объектов в пространстве: полный журнал,
сводный объект, уведомление с раскрытием по запросу или комбинация этих
вариантов.

### Критерии закрытия

- определены классы автономных событий и их видимость;
- задана политика уведомлений и дедупликации;
- определён механизм summary/artifact для серии событий;
- установлен лимит визуального шума и способ его настройки пользователем;
- указано, какие автономные действия требуют предварительного разрешения.

## SPATIAL-Q-004 — Видимость состояний действия

**Область:** interaction state, auditability, safety  
**Приоритет:** P0  
**Статус:** Decided  
**Решение:** [ADR-004 — Primary Agent Visual State Language](./ADR-004-primary-agent-visual-state-language.md)

### Краткий итог решения

Operational state Primary Agent кодируется несколькими независимыми visual
channels: цветом, яркостью, глубиной, glow, pulse, scale, halo и motion.
Семантика состояний фиксирована системой, а visual mapping настраивается
пользователем. Состояние агента и Orbital Attention System разделены:
Presence показывает текущую работу, орбитальные markers — накопленные события и
решения.

### Решение, которое требуется принять

Ввести однозначно различимые состояния:

thinking → planning → awaiting approval → executing → completed → failed

Нужно исключить смешение рассуждения, предложения действия, принятого решения
и фактически выполненной операции. Для каждого состояния следует определить
доступные пользователю действия и источник истины о статусе.

### Критерии закрытия

- состояния и переходы описаны как конечный автомат;
- для каждого состояния определены UI-индикатор и audit event;
- запрещено показывать действие как выполненное до подтверждения runtime;
- ошибки, отмена, тайм-аут и повторный запуск имеют отдельные состояния;
- модель проверена на опасной операции и на частичном сбое.

## SPATIAL-Q-005 — Жизненный цикл обнаружения удалённых агентов

**Область:** discovery, trust, network visualization  
**Приоритет:** P1  
**Статус:** Decided  
**Решение:** [ADR-005 — Spatial Entity Topology](./ADR-005-spatial-entity-topology.md)

### Краткий итог решения

Agent, Endpoint, Service, Session и Artifact получают различные semantic
classes и visual grammar. Endpoint discovery показывается временной Endpoint
Arc; выбранный Endpoint становится Workspace object только после явного
selection или взаимодействия. Subagent является отдельным Actor с локальной
interaction region, а Endpoint Information Surface показывает его параметры,
availability, latency, нагрузку, цену и provenance.

### Решение, которое требуется принять

Определить, когда удалённый агент становится объектом пространства и какие
статусы ему доступны:

discovered → under consideration → selected → connected → used before → blocked

Необходимо отделить факт обнаружения от доверия, выбора, установления Session и
сохранённой истории взаимодействия.

### Критерии закрытия

- задана state machine удалённого агента;
- определены TTL и правила удаления устаревших discovery records;
- доверие и доступ представлены отдельно от визуального присутствия;
- установлено, какие агенты отображаются по умолчанию и почему;
- определены требования к provenance и network evidence.

## SPATIAL-Q-006 — Границы Session и вложенные операции

**Область:** sessions, billing, provenance, delegation  
**Приоритет:** P0  
**Статус:** Decided  
**Решение:** [ADR-006 — Workspace Sessions and Context Graph](./ADR-006-workspace-sessions-context-graph.md)

### Краткий итог решения

Workspace Session является пользовательским semantic context, начинающимся с
явного Root Interaction. Внутри него формируется ветвящийся Context Graph:
каждый branch имеет не более одного structural parent через CONTINUES_FROM, а
дополнительный контекст подключается через 0..N USES_CONTEXT references.
Протокольные AiDN Sessions остаются отдельными экономическими и
provenance-сущностями и могут быть связаны с одной Workspace Session без
создания новых пользовательских чатов.

### Решение, которое требуется принять

Определить, что считается одной Session, если пользователь последовательно
задаёт вопросы, изменяет endpoint, нанимает remote agent, а тот запускает
дополнительные операции.

Варианты модели: одна пользовательская Session с графом дочерних операций;
вложенные AiDN Sessions; либо Conversation Artifact, ссылающийся на набор
канонических Session records.

### Критерии закрытия

- задана каноническая сущность Session и её границы;
- описаны parent/child relationships и correlation IDs;
- определено, как Session влияет на ownership, escrow, billing и закрытие;
- задано поведение повторов, тайм-аутов и частичного завершения;
- пользовательский журнал и протокол используют одну модель provenance.

## SPATIAL-Q-007 — Долгоживущее рабочее пространство и архивирование

**Область:** scalability, retention, rendering  
**Приоритет:** P1  
**Статус:** Decided  
**Решение:** [ADR-007 — Spatial Memory, Aging and Clustering](./ADR-007-spatial-memory-aging-clustering.md)

### Краткий итог решения

Workspace является пространственной памятью Node. Объекты проходят
presentation lifecycle от Active Work и Recent Memory через semantic clusters
в Deep Memory и virtualized representation. Старение изменяет положение,
видимость и LOD, но не удаляет semantic object, Context Graph, provenance или
протокольные записи. Layout использует preferred regions вокруг Primary Agent,
relation reveal и Pull-to-Focus; жесты меняют camera focus, а не topology.

Recent Session Artifacts располагаются под Primary Agent и ограничены
bounded visible budget. Agents и Subagents получают Agent Space, clusters —
верхнюю правую область, а Endpoint discovery — временную Endpoint Arc. Для
тысяч объектов renderer применяет culling и LOD, сохраняя searchable records,
relation anchors и возможность материализации по demand.

Решение не закрывает схему canonical objects/presentation instances (Q-008) и
междустройственную синхронизацию projection state (Q-009).

### Границы зафиксированного решения

ADR-007 фиксирует поведение workspace при сотнях разговоров, агентов, задач,
файлов и артефактов. Решение разделяет существование объекта в semantic model
и его рендеринг на canvas.

Автоматическое старение, semantic clusters, дальние слои пространства,
поиск, восстановление и bounded rendering определены как presentation policy.
Удаление semantic history, provenance или канонических ссылок этой политикой
не допускается.

### Критерии, учтённые при принятии

- установлены lifecycle и retention policy для объектов;
- определён порог, после которого объект перестаёт рендериться напрямую;
- поиск и навигация работают без загрузки всего workspace на canvas;
- архивирование не удаляет provenance и ссылки на канонические объекты;
- заданы ограничения памяти, времени рендера и сетевой синхронизации.

### Критерии приняты в ADR-007

- preferred regions, четыре memory levels и Recent Memory formalized;
- lifecycle aging, hysteresis, pinning и promotion в Session Cluster заданы;
- relation reveal, semantic gesture navigation и Pull-to-Focus определены;
- virtualized artifacts и LOD0–LOD3 отделены от semantic model;
- добавлены responsive, accessibility, reduced-motion и bounded-render
  требования.

## SPATIAL-Q-008 — Канонический объект и его presentation instances

**Область:** domain model, references, consistency  
**Приоритет:** P0  
**Статус:** Decided  
**Решение:** [ADR-008 — Entity Uniqueness and Provenance References](./ADR-008-entity-uniqueness-and-provenance.md)

### Краткий итог решения

Одна canonical entity получает одну primary spatial presence в рамках
Workspace. Endpoint, Agent и Service не клонируются в Session Artifact:
история сохраняет request, response, references и provenance с object ID и
revision. Дополнительные context projections и focus proxies разрешены
только как временные read-only представления с явной причиной.

Local Interaction Familiarity хранится отдельно от global reputation,
availability и authorization. Она может влиять на ranking Endpoint Arc, но
не выдаёт capability, не изменяет цену и не заменяет revalidation.

### Границы зафиксированного решения

ADR-008 разделяет canonical object, primary spatial presence, context
projection, focus proxy и provenance reference. Для одного Workspace и
canonical reference действует идемпотентное правило единственности.

Изменение presentation state не является canonical mutation: camera focus,
aging, clustering, collapse и virtualization не переписывают identity,
ownership, billing или protocol records.

### Критерии, учтённые при принятии

- определены типы canonical entity и presentation role;
- задан формат reference с object ID, object type и revision;
- исторические взаимодействия используют provenance, а не entity clones;
- projection и focus proxy не имеют отдельного lifecycle, billing или
  authorization;
- local familiarity отделена от global reputation;
- модель проверена для Endpoint, Session, Agent и Payment Artifact.

## SPATIAL-Q-009 — Синхронизация между устройствами

**Область:** multi-device, responsive layout, synchronization  
**Приоритет:** P1  
**Статус:** Decided  
**Решение:** [ADR-009 — Multi-Device Workspace and Mobile Spatial Navigation](./ADR-009-multi-device-workspace-and-mobile-navigation.md)

### Краткий итог решения

Desktop, tablet и mobile отображают один semantic Node Workspace. Shared world
включает canonical references, relations, Sessions, artifacts, clusters,
pins и semantic anchors. Camera orientation, zoom, focus, selection и
адаптивная presentation geometry остаются device-local, если оператор явно
не использует Share View.

Workspace моделируется как сферическое semantic space вокруг Primary Agent.
FOCUS_PRIMARY_AGENT задаёт canonical HOME orientation. Mobile использует
rotate/pan, pinch, tap и long press Interaction Seed как альтернативные input
modalities того же пространства, а не как отдельные страницы.

Semantic geometry и presentation geometry разделены: размер таблицы,
Conversation Surface или bottom sheet может быть разным на устройствах, но
identity, provenance, relations и cluster membership остаются общими.
Синхронизация использует revision, idempotency и deterministic conflict
handling; offline mutations обрабатываются через очередь.

### Границы зафиксированного решения

ADR-009 определяет shared semantic world, device-local viewport, сферическую
координатную модель, HOME orientation, mobile gestures, Share View,
responsive geometry, accessibility и sync invariants. Он не требует
буквального 3D renderer и не фиксирует конкретный транспорт или CRDT.

### Критерии, учтённые при принятии

- разделены semantic Workspace и device-specific viewport;
- semantic anchors, relations, clusters и identity синхронизируются;
- camera и focus не транслируются между устройствами без явного Share View;
- presentation geometry адаптируется к viewport без semantic duplicates;
- определены revision, idempotency, offline queue и deterministic conflicts;
- добавлены HOME, touch/keyboard equivalents, screen-reader и reduced-motion.

## SPATIAL-Q-010 — Recovery mode при недоступности Primary Agent

**Область:** resilience, security, operations  
**Приоритет:** P0  
**Статус:** Decided  
**Решение:** [ADR-010 — Node Status and Recovery Access](./ADR-010-node-status-and-recovery-access.md)

### Краткий итог решения

System Menu является постоянным Node-owned entry point и не зависит от
Primary Agent. Status получает authoritative evidence напрямую от Node,
Hypervisor и системных компонентов; ответ агента не является источником
истины.

Recovery access включает прямой read-only Status для Node, Hypervisor,
Primary Agent, MCP, hooks, network, wallet, sessions, tasks, endpoints и
resources. Подробности раскрываются progressive detail, а изменяющие
действия выполняются через canonical command path с authorization,
confirmation и audit.

Spatial indication показывает недоступного агента, Status объясняет причину,
а SHOW_IN_WORKSPACE возвращает оператора к реальным spatial entities без
создания дубликатов. Offline и stale snapshots явно маркируются.

### Границы зафиксированного решения

ADR-010 не вводит отдельный emergency dashboard. System Menu shell,
Status Aggregator, freshness, progressive detail, recovery command path и
SHOW_IN_WORKSPACE являются частью постоянной Node UI. Конкретный transport
health probes и экономическая budget policy остаются отдельными решениями.

### Критерии, учтённые при принятии

- System Menu доступен при любом lifecycle Primary Agent;
- Status не зависит от LLM и использует прямые authoritative sources;
- summary, details, evidence и freshness имеют согласованную revision;
- UNKNOWN, STALE и last-known состояния не маскируются под ONLINE;
- SHOW_IN_WORKSPACE использует существующую spatial entity;
- recovery actions требуют authorization, confirmation и audit;
- добавлены offline, mobile, keyboard, screen-reader и reduced-motion
  сценарии.

## SPATIAL-Q-011 — Экономическая прозрачность и управление бюджетом

**Область:** payments, escrow, approvals, UX  
**Приоритет:** P0  
**Статус:** Decided  
**Решение:** [ADR-011 — Agent-Mediated Component Interface and Resource Semantics](./ADR-011-agent-mediated-component-interface.md)

### Краткий итог решения

Q и Compute Units описываются как единицы учёта вклада и потребления
ресурсов, а не как банковские деньги. В новом UI используются Resource
Balance, Resource Usage, Resource Cost, Contribution Credits и Resource
Settlement. Экономические детали раскрываются progressive detail и
связываются с Session, Agent, Endpoint и результатом.

Статические страницы не удаляются. Они декомпозируются в shared Component
Registry, которую используют Classic Page Composer и Spatial Presentation
Planner. Primary Agent является default control/information interface:
intent → MCP/Hypervisor → Result Model → зарегистрированные компоненты.

Изменения формы, голоса и spatial actions используют typed Change Intent с
target reference, structured diff и current revision. Classic UI остаётся
ручным escape hatch, но сходится к той же validation, authorization,
approval и audit boundary. Planner не может генерировать произвольный код
или обходить canonical command path.

### Границы зафиксированного решения

ADR-011 закрывает resource semantics и Agent-Mediated Component Interface:
общий registry, schema contracts, Result Model, Presentation Planner,
Change Intent, progressive detail и resource components. Он не определяет
конкретную LLM, canonical object schema или полное удаление Classic UI.

### Критерии, учтённые при принятии

- Q terminology переведена в ресурсный взаимозачёт и Compute Units;
- static pages сохраняются и становятся источником shared components;
- Spatial и Classic UI используют общий schema и command boundary;
- component actions проходят typed intent, revision, validation и audit;
- resource balance, usage, cost, contribution и settlement имеют
  зарегистрированные presentation components;
- arbitrary UI code и LLM-only validation запрещены.

## SPATIAL-Q-012 — Local Trust Boundary и mediated remote resource access

**Область:** identity, delegation, security boundary, remote resources, provenance  
**Приоритет:** P0  
**Статус:** Decided  
**Решение:** [ADR-012 — Local Trust Boundary and Mediated Remote Resource Access](./ADR-012-local-trust-boundary-and-mediated-remote-resources.md)

### Краткий итог решения

Прежняя формулировка Human–Primary Agent–Remote Agent признана superseded.
Пользователь взаимодействует с локальным Primary Agent и локальным AiDN
Node. Remote Endpoint и Remote Agent не получают прямого user-facing канала.

Все удалённые запросы проходят через local mediation layer: authorization,
policy, context minimization, capability check, session management,
resource accounting, transport, validation и provenance. Remote output
считается untrusted data и не может стать system instruction, capability
grant или UI code.

Remote provider/operator identity показывается только как provenance
metadata. Локальные Subagents могут делегировать запросы через тот же
boundary. Для ручного тестирования Endpoint Primary Agent создаёт
EndpointTestFrame с полем ввода и explicit Send; validated response
возвращается в этот же frame.

### Границы зафиксированного решения

ADR-012 закрывает local trust boundary, отсутствие прямого Human ↔ Remote
Actor канала, минимизацию контекста, обработку недоверенного результата и
Endpoint Test Frame. Он не определяет конкретный transport, provider SDK,
глобальную reputation или UI для общения с владельцем Remote Agent.

### Критерии, учтённые при принятии

- Human interaction завершается на локальном Primary Agent и Node;
- remote request нельзя выполнить в обход mediation layer;
- secrets, system prompt и unrelated context не передаются по умолчанию;
- remote output валидируется, маркируется untrusted и получает provenance;
- remote identity остаётся metadata/provenance;
- EndpointTestFrame отправляет данные только по explicit submit;
- local Subagents используют ту же security boundary;
- добавлены failure, accounting, accessibility и negative security tests.

---

## Рекомендуемый порядок проработки

1. Завершить identity, ownership и trust boundary: SPATIAL-Q-001 и Q-002
   приняты; Q-012 принят в ADR-012.
2. Зафиксировать канонические сущности, provenance и multi-device contract:
   Q-006 принят в ADR-006, Q-008 принят в ADR-008, Q-009 принят в ADR-009.
3. Утвердить безопасность, восстановление и resource control: Q-004 принят в
   ADR-004, Q-010 принят в ADR-010, Q-011 принят в ADR-011; Q-012 принят в
   ADR-012.
4. Discovery и масштабирование зафиксированы в ADR-005 и ADR-007; при
   реализации учитывать их зависимости от Q-009. Модель автономного внимания
   зафиксирована в ADR-003.
5. Для каждого принятого решения создать ADR/RFC и добавить ссылку в этот
   реестр.

## Definition of Done для первого батча

Первый батч считается закрытым, когда для всех вопросов P0:

- принято и опубликовано решение;
- определены владельцы данных и границы ответственности;
- описаны state machines и события аудита, где это применимо;
- добавлены схемы данных и API-контракты;
- есть хотя бы один позитивный и один отказоустойчивый тестовый сценарий;
- пространственный UI, Hypervisor и экономический слой используют согласованные
  идентификаторы и provenance.
