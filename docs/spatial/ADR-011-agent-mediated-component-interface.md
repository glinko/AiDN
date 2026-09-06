# ADR-011 — Agent-Mediated Component Interface and Resource Semantics

**Статус:** Accepted  
**Дата решения:** 2026-09-04  
**Область:** Spatial Agent Interface, Component Registry, Presentation Planner, resource semantics, control path  
**Связанный вопрос:** [SPATIAL-Q-011 — Экономическая прозрачность и управление бюджетом](./OPEN-QUESTIONS.md#spatial-q-011--экономическая-прозрачность-и-управление-бюджетом)  
**Связанные решения:** [ADR-003 — Orbital Attention System](./ADR-003-orbital-attention-system.md), [ADR-006 — Workspace Sessions and Context Graph](./ADR-006-workspace-sessions-context-graph.md), [ADR-008 — Entity Uniqueness and Provenance References](./ADR-008-entity-uniqueness-and-provenance.md), [ADR-010 — Node Status and Recovery Access](./ADR-010-node-status-and-recovery-access.md), [ADR-013 — AiDN Milky Glass Neumorphism Visual Design System](./ADR-013-aidn-milky-glass-neumorphism-visual-design.md), [ADR-014 — Spatial UI Technical Architecture and Rendering Boundary](./ADR-014-spatial-ui-technical-architecture.md)  
**Следующее связанное решение:** [ADR-012 — Local Trust Boundary and Mediated Remote Resource Access](./ADR-012-local-trust-boundary-and-mediated-remote-resources.md)  
**Исходный план:** [AiDN Spatial Agent Interface — Implementation Plan](./AiDN-Spatial-Agent-Interface-Implementation-Plan.md)

## Решение

Primary Agent является default information и control interface AiDN Node.
Он не генерирует произвольный frontend и не подменяет Hypervisor. Агент
получает intent оператора, запрашивает authoritative state через MCP,
формирует typed result и поручает Presentation Planner собрать нужную
композицию из заранее зарегистрированных компонентов.

Существующие статические страницы не удаляются и не переписываются как
отдельный продукт. Они декомпозируются на переиспользуемые компоненты.
Classic Admin UI и Spatial UI используют одну Component Registry, один schema
contract и одну canonical validation/command boundary.

~~~text
Human
  │ voice / text / form / spatial action
  ▼
Typed Intent Gateway
  │
  ▼
Primary Agent
  │ intent, query и action planning
  ▼
MCP / canonical command path
  │
  ▼
Hypervisor authoritative state
  │
  ▼
Result Model
  │
  ▼
Presentation Planner
  │
  ▼
Component Registry
  │
  ├── Spatial Frames
  └── Classic Page Composer
~~~

Это единый control path. Голос, текст, изменение поля формы и spatial action
отличаются только способом создания typed intent, а не правилами
authorisation, validation, audit и выполнения.

## Q и ресурсная терминология

Q / Compute Units — это единицы учёта вклада и потребления ресурсов AiDN
Network. Их отображение не должно превращать Node в банковский интерфейс.
Экономические свойства Q и protocol settlement сохраняются, но базовая
семантика UI — ресурсный взаимозачёт.

~~~text
Hypervisor contributes resources
        ↓
Network usage
        ↓
Resource accounting
        ↓
Q / Compute Units
        ↓
Mutual resource settlement
~~~

Канонические labels для нового интерфейса:

| Не использовать как основной UX label | Использовать |
|---|---|
| Money | Resources / Compute Units |
| Income | Resource Contribution / Earned Compute Units |
| Spending | Resource Usage |
| Revenue | Contribution Credit |
| Payment | Resource Settlement |
| Price | Resource Cost |
| Wallet Balance | Q Balance / Resource Balance |
| Transaction | Settlement / Q Operation |
| Earnings | Contribution Credits |

Для Endpoint допустимы labels Resource Cost: 2 Q / request или Cost: 2 Q /
request. Это не означает долларовую цену. Legacy API или protocol field может
сохранить старое имя до отдельной миграции, но новый UI и новые schema
contracts не должны вводить финансовую метафорику без необходимости.

Минимальный ресурсный overview должен показывать:

- Q Balance или Resource Balance;
- Resource Usage за выбранный период;
- pending escrow и reserved resources;
- Resource Contribution и Contribution Credits;
- Resource Cost Endpoint;
- Resource Settlement History;
- связь каждой операции с Session, Agent, Endpoint и результатом.

Экономические детали раскрываются progressive disclosure и могут быть
показаны компонентами ResourceBalance, ResourceUsage,
ResourceContributionChart и SettlementHistory, а не отдельной банковской
панелью.

## Agent-Mediated UI

Agent-Mediated UI разделяет четыре роли:

1. **Human** задаёт цель, выбирает объект или изменяет поле.
2. **Primary Agent** понимает intent, получает контекст, проверяет
   допустимость и выбирает действие.
3. **MCP / Hypervisor** возвращает authoritative data и выполняет
   canonical command.
4. **Presentation Planner** выбирает проверенные компоненты и связывает их с
   result model.

Presentation Planner не рисует интерфейс свободным текстом LLM. LLM может
предложить intent, fields и preferred representation, но planner MUST
проверить результат по Component Registry, schema, capability policy и
accessibility contract.

~~~text
User Intent
    ↓
Primary Agent
    ↓
Query / Action Planning
    ↓
MCP
    ↓
Authoritative Node State
    ↓
Result Model
    ↓
Presentation Planner
    ↓
Component Registry
    ↓
Spatial Frame
~~~

## Component Decomposition

Каждая существующая static page рассматривается как композиция:

~~~text
Page
 │
 ├── component
 ├── component
 ├── component
 └── component
~~~

Например, Endpoint Page декомпозируется на:

~~~text
Endpoint Page
│
├── EndpointHeader
├── EndpointStatus
├── EndpointMetrics
├── ActivityChart
├── ResourceCost
├── RuntimeConfiguration
├── EndpointControls
└── LogViewer
~~~

После декомпозиции Spatial Planner может выбрать только нужные части:

~~~text
SHOW:
  EndpointStatus
  ActivityChart
FOR:
  endpoint_parakeet
~~~

Classic Page Composer использует те же компоненты для полной страницы:

~~~text
Component Registry
        │
        ├── Classic Page Composer
        │       └── Endpoints → Parakeet → Configuration
        │
        └── Presentation Planner
                └── "Покажи настройки Parakeet"
~~~

Различается композиция и layout, но не data schema, validation или action
semantics. System Menu → Advanced / Manual остаётся escape hatch для
оператора, которому нужен полный классический интерфейс.

## Component Registry Contract

Agent MAY выбирать только зарегистрированные компоненты. Registry entry
описывает schema, допустимые actions и требования к capability:

~~~yaml
component_definition:
  type:
  version:
  props_schema:
  data_schema:
  allowed_states:
  allowed_actions:
  required_capabilities:
  slots:
  layout_roles:
  accessibility:
  localization:
  provenance:
~~~

Registry MUST:

- отклонять неизвестный component type;
- валидировать props и data schema;
- требовать declared capability для action;
- предоставлять loading, empty, error, stale и disabled states;
- включать keyboard, touch и screen-reader semantics;
- запрещать произвольный JavaScript, HTML, script или remote component;
- иметь versioning и migration rules.

Базовый набор включает:

~~~text
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
ResourceBalance
ResourceUsage
ResourceContributionChart
ResourceCostEditor
SettlementHistory
Payment
Contract
Evidence
ValidationReport
Confirmation
Approval
ChoiceList
Error
~~~

Набор расширяется через registry change, а не через генерацию нового
компонента во время запроса.

## Presentation Intent и Result Model

Для запроса агент или Typed Intent Gateway формирует структурированный
Presentation Intent:

~~~yaml
presentation_intent:
  id:
  mode: QUERY | EXPLAIN | COMPARE | CONFIGURE | CHANGE | START | STOP | DIAGNOSE | CONNECT | INSPECT
  target_refs:
    - object_id:
      object_type:
  scope:
  fields:
  constraints:
  preferred_surface:
  source_session_ref:
  actor_ref:
  current_revision:
~~~

MCP и Hypervisor возвращают typed Result Model с authoritative source:

~~~yaml
result_model:
  schema:
  source_refs:
    - object_id:
      object_type:
      revision:
  data:
  actions:
    - intent_type:
      required_capabilities:
      approval:
  warnings:
  errors:
  generated_at:
  revision:
  provenance:
~~~

Presentation Planner преобразует result model в Frame Spec:

~~~yaml
frame_spec:
  frame_id:
  workspace_id:
  title:
  context_refs:
    - object_id:
      object_type:
      revision:
  components:
    - type:
      version:
      data_ref:
      props:
      layout_role:
      actions:
      accessibility:
  relations:
  focus_policy:
  provenance:
~~~

Frame Spec является декларативным. Renderer не принимает из него произвольный
код и не должен вычислять authoritative data на клиенте.

## Query Flow

Пример: оператор говорит «Покажи все Endpoint и их состояние».

~~~yaml
presentation_intent:
  mode: QUERY
  target_refs:
    - object_type: endpoint
      scope: all
  fields:
    - name
    - capability
    - status
    - recent_activity
    - resource_cost
~~~

Primary Agent запрашивает данные через MCP. После получения result model
Planner выбирает EndpointList или EndpointCard и показывает только
релевантные поля:

~~~text
╭────────────────────────────────────────────────────╮
│ Endpoints                                          │
│                                                    │
│ Whisper          READY     3 requests    1 Q/req  │
│ Parakeet         READY    17 requests    1 Q/req  │
│ Qwen-27B         BUSY      8 requests    4 Q/req  │
│ ImageGen         OFFLINE   0 requests    3 Q/req  │
╰────────────────────────────────────────────────────╯
~~~

Ненужные sidebar, административные поля и действия не должны materialize
только потому, что они существуют на полной странице.

## Configure и Change Intent

Запрос «Хочу изменить параметры Parakeet» переводит representation из
EndpointSummary в EndpointConfiguration. Компонент может быть тем же самым
в Classic UI и Spatial Frame.

Изменение формы MUST формировать structured Change Intent, а не прямой вызов
configuration API из браузера:

~~~yaml
change_intent:
  id:
  target:
    type: endpoint
    id: endpoint_parakeet
  current:
    port: 8000
    resource_cost:
      amount: 1
      unit: Q
      basis: request
  proposed:
    port: 9999
    resource_cost:
      amount: 2
      unit: Q
      basis: request
  diff:
    - path: port
      from: 8000
      to: 9999
    - path: resource_cost.amount
      from: 1
      to: 2
  current_revision:
  source: form | voice | spatial
  actor_ref:
  workspace_session_ref:
  provenance:
~~~

Пользователь может видеть естественное описание:

~~~text
Изменить порт Parakeet с 8000 на 9999 и Resource Cost с 1 Q до 2 Q/request.
~~~

Но для выполнения используются одновременно natural-language context,
structured change set, target reference и current revision.

Единый поток изменения:

~~~text
Form / Voice / Spatial Action
            ↓
Structured Change Intent
            ↓
Primary Agent
            ↓
validation / permissions / clarification
            ↓
MCP canonical command
            ↓
Hypervisor
            ↓
Result Model
            ↓
Frame update
~~~

Current revision защищает от записи поверх устаревшего состояния. Если порт
9999 занят, агент не выполняет частичную мутацию, а возвращает
ValidationNotice и ChoiceList:

~~~text
Port 9999 is already used by Runtime X.

Available:
9998   10000   10001

[Use 9998]   [Choose another]
~~~

После выбора и требуемого подтверждения формируется новый Change Intent с
актуальной revision.

## Classic UI и прямое управление

Classic Admin UI остаётся доступным через System Menu → Advanced / Manual.
Он может показывать полные страницы, raw configuration, таблицы, логи и
ручные controls.

При этом Classic UI не создаёт второй backend control path. Его controls
формируют тот же structured intent или canonical command, проходят ту же
validation, capability policy, approval и audit boundary. Разница в том, что
оператору не требуется вести разговор с агентом.

~~~text
Spatial UI       ─┐
Voice / Text     ─┼→ Typed Intent / Canonical Command → MCP → Hypervisor
Classic UI       ─┘
~~~

Если Primary Agent недоступен, System Menu и Status остаются доступными
согласно [ADR-010](./ADR-010-node-status-and-recovery-access.md). Чтение
фактического состояния и разрешённые manual actions не должны зависеть от
успешного ответа LLM.

## Provenance и entity references

Каждый Frame и Component data binding должны хранить object reference и
source revision. Endpoint, Agent и Service не копируются в Session Artifact:
история хранит request, response и provenance согласно
[ADR-008](./ADR-008-entity-uniqueness-and-provenance.md).

Workspace Session и related protocol sessions связываются по правилам
[ADR-006](./ADR-006-workspace-sessions-context-graph.md). Component action
должен содержать workspace_session_ref и correlation ID, чтобы:

- восстановить, откуда пришёл intent;
- показать operator audit trail;
- связать Resource Settlement с Endpoint и Session;
- безопасно повторить или отклонить duplicate command;
- открыть фактический объект через SHOW_IN_WORKSPACE.

Presentation component не может менять identity, ownership, billing или
protocol state только через изменение props, layout или визуального frame.

## Approval, errors и safe states

Компонент обязан явно различать:

- loading;
- empty;
- stale;
- unavailable;
- validation error;
- action proposed;
- approval required;
- applied;
- rejected;
- partially completed.

Action, который изменяет Node или ресурсный баланс, должен получить
capability decision и, если policy требует, Approval component. Planner
может отобразить кнопку или выбор, но не может сам выдать разрешение.

LLM не является authoritative validator. MCP/Hypervisor повторно проверяют
schema, revision, permissions, resource limits и canonical state перед
изменением.

## Accessibility, localization и performance

Component Registry MUST включать:

- semantic roles и labels;
- keyboard navigation;
- screen-reader descriptions;
- touch targets;
- localized labels для Resource Cost и Q Balance;
- text alternative для spatial frame и generated chart;
- reduced-motion variant;
- error и stale copy.

Presentation Planner не должен собирать на один intent больше компонентов,
чем необходимо. Registry и renderer используют culling, lazy data binding и
bounded frame budget согласно [ADR-007](./ADR-007-spatial-memory-aging-clustering.md).
Streaming result обновляет существующий frame, а не создаёт новый компонент
на каждый transport event.

## Инварианты

**COMP-INV-001 — Registered composition**

Planner и LLM могут выбирать только зарегистрированные и versioned
компоненты.

**COMP-INV-002 — One schema contract**

Spatial UI и Classic UI используют общий data schema, validation и action
semantics.

**COMP-INV-003 — Intent before mutation**

Изменение формы, голоса или spatial action сначала создаёт typed intent и
проходит canonical validation.

**COMP-INV-004 — Authoritative source**

Фактические Node data, Resource Balance и Resource Usage приходят от
Hypervisor/MCP, а не вычисляются в браузере или LLM.

**COMP-INV-005 — Resource semantics**

Новый UI описывает Q как Compute Units и Resource Settlement, а не как
доллары или банковский доход.

**COMP-INV-006 — Reference over clone**

Component frame и Session history используют entity references и provenance,
а не semantic clones.

**COMP-INV-007 — Shared control boundary**

Spatial, Voice, Classic и Form flows сходятся к одной canonical command,
validation, authorization и audit boundary.

**COMP-INV-008 — No arbitrary UI code**

Результат агента не может загрузить произвольный JavaScript, HTML, remote
component или executable renderer instruction.

**COMP-INV-009 — Revision safety**

Change Intent содержит current revision; stale или duplicate mutation
отклоняется идемпотентно и не переписывает чужое состояние.

**COMP-INV-010 — Progressive detail**

Planner показывает минимально достаточную композицию и раскрывает
diagnostic, economic и administrative details по запросу.

## Реализационные слайсы

1. **Component inventory.** Разобрать существующие static pages и выделить
   компоненты, schema contracts и повторяемые states.
2. **Registry.** Ввести registry definitions, versioning, props/data schema,
   capability requirements и accessibility contract.
3. **Classic Page Composer.** Перевести текущие страницы на shared
   components без удаления manual/advanced paths.
4. **Typed Intent Gateway.** Ввести Presentation Intent, Result Model,
   Change Intent и current revision checks.
5. **Presentation Planner.** Реализовать allowlisted composition,
   progressive detail, spatial frame и provenance bindings.
6. **MCP command boundary.** Связать component actions с canonical validation,
   authorization, approvals и audit.
7. **Resource terminology.** Заменить новые UX labels на Q/Compute Units,
   Resource Usage, Resource Cost, Contribution Credits и Resource Settlement.
8. **Resource components.** Добавить ResourceBalance, ResourceUsage,
   ResourceCostEditor, ResourceContributionChart и SettlementHistory.
9. **Failure states.** Реализовать stale, unavailable, validation,
   clarification, approval и partial completion states.
10. **Evaluation.** Проверить query, configure, rejected change, occupied
    port, duplicate event, offline agent, Classic fallback и accessibility.

## Положительные последствия

- Existing UI становится источником зрелых компонентов, а не техническим
  долгом, который нужно выбросить.
- Spatial и Classic интерфейсы не расходятся по schema и поведению.
- Primary Agent собирает минимально необходимое представление под intent.
- Voice, form и spatial actions используют один проверяемый command path.
- Q получает точную ресурсную семантику без потери settlement capabilities.
- Ошибки и недостающие данные превращаются в понятные typed components, а
  не в сырые HTTP errors.

## Ограничения и риски

- Потребуется большая работа по инвентаризации и декомпозиции существующих
  страниц.
- Registry versioning и schema migration должны быть частью release process.
- Planner должен избегать как чрезмерной генерации компонентов, так и
  чрезмерного минимализма, скрывающего нужный контекст.
- Classic UI может временно содержать legacy labels, пока не выполнена
  отдельная миграция; новые поверхности их не должны копировать.
- local trust boundary и mediated remote resources определены в
  [ADR-012](./ADR-012-local-trust-boundary-and-mediated-remote-resources.md);
  material profiles и surface tokens определены в
  [ADR-013](./ADR-013-aidn-milky-glass-neumorphism-visual-design.md).

## Не входит в это решение

Этот ADR не определяет:

- конкретную LLM, prompt или inference provider;
- глобальную reputation и network governance;
- protocol economics beyond resource labels and presentation;
- окончательный canonical object schema;
- конкретный frontend framework или scene graph;
- полное удаление Classic Admin UI.

## Критерии приёмки

Решение считается реализованным, когда:

- минимум одна существующая static page декомпозирована в shared components;
- один компонент EndpointConfiguration работает в Classic и Spatial UI;
- query intent создаёт typed Result Model и минимальный Spatial Frame;
- form, voice и spatial change создают один формат Change Intent;
- Hypervisor/MCP повторно валидируют revision, capability и canonical state;
- Planner отклоняет unknown component и arbitrary code;
- Session history хранит Endpoint references и provenance без entity clone;
- Q отображается как Compute Units/Resource Settlement с понятными labels;
- Resource Balance, Usage, Cost и Contribution доступны progressive detail;
- ошибки occupied port, stale state, unavailable agent и approval required
  имеют typed UI states;
- Classic fallback и System Menu работают при недоступном Primary Agent;
- keyboard, touch, screen-reader, localization и reduced-motion paths
  покрыты тестами;
- component composition и streaming не нарушают bounded render budget.

## Связанные документы

- [Реестр открытых вопросов](./OPEN-QUESTIONS.md)
- [ADR-003 — Orbital Attention System](./ADR-003-orbital-attention-system.md)
- [ADR-006 — Workspace Sessions and Context Graph](./ADR-006-workspace-sessions-context-graph.md)
- [ADR-007 — Spatial Memory, Aging and Clustering](./ADR-007-spatial-memory-aging-clustering.md)
- [ADR-008 — Entity Uniqueness and Provenance References](./ADR-008-entity-uniqueness-and-provenance.md)
- [ADR-010 — Node Status and Recovery Access](./ADR-010-node-status-and-recovery-access.md)
- [ADR-012 — Local Trust Boundary and Mediated Remote Resource Access](./ADR-012-local-trust-boundary-and-mediated-remote-resources.md)
- [ADR-013 — AiDN Milky Glass Neumorphism Visual Design System](./ADR-013-aidn-milky-glass-neumorphism-visual-design.md)
- [ADR-014 — Spatial UI Technical Architecture and Rendering Boundary](./ADR-014-spatial-ui-technical-architecture.md)
- [Detailed Development Roadmap](./DEVELOPMENT-ROADMAP.md)
- [Общий план Spatial Agent Interface](./AiDN-Spatial-Agent-Interface-Implementation-Plan.md)
