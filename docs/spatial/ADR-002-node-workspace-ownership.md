# ADR-002 — Node Workspace Ownership

**Статус:** Accepted  
**Дата решения:** 2026-09-03  
**Область:** Spatial Agent Interface, persistence, ownership, recovery  
**Связанный вопрос:** [SPATIAL-Q-002 — Ownership рабочего пространства](./OPEN-QUESTIONS.md#spatial-q-002--ownership-рабочего-пространства)  
**Связанное решение:** [ADR-001 — Node-scoped Primary Agent](./ADR-001-primary-agent-scope.md)  
**Исходный план:** [AiDN Spatial Agent Interface — Implementation Plan](./AiDN-Spatial-Agent-Interface-Implementation-Plan.md)

## Решение

Spatial Workspace принадлежит конкретной AiDN Node. Workspace не является
состоянием Primary Agent, конкретной модели или agent runtime.

Пользователь выступает оператором Workspace, а Primary Agent является одним из
разрешённых способов взаимодействия с Node внутри этого Workspace.

Каноническая структура:

~~~text
AiDN Node
 ├── Hypervisor
 ├── Protocol State
 ├── Node Services
 ├── Primary Agent Slot
 │       └── Current Agent Binding
 └── Spatial Workspace
         └── Operator Interaction
~~~

Один пользователь может работать с несколькими Nodes, и одна Node может иметь
несколько авторизованных операторов. Это не меняет владельца Workspace: им
остаётся Node.

## Обоснование

Node-owned Workspace:

- сохраняет контекст при замене или отключении агента;
- позволяет подключать разные UI и способы управления;
- не требует передавать агенту право собственности на данные;
- поддерживает recovery и ручное управление без LLM;
- даёт стабильную основу для provenance, аудита и multi-operator доступа.

## Разделение состояний

Состояния Node, Workspace, агента и оператора должны храниться раздельно:

| Слой | Содержание | Владелец |
|---|---|---|
| Node State | Hypervisor, endpoints, runtimes, ресурсы, sessions, network, wallet, permissions и protocol state | AiDN Node |
| Workspace Semantic State | conversations, session artifacts, relations, selected endpoints, tasks, files, reports и context groups | AiDN Node |
| Workspace Presentation State | позиции, размеры, zoom, viewport, collapsed/pinned/focus state и визуальные группы | AiDN Node, с device-specific представлениями |
| Primary Agent State | Agent Identity, runtime, модель, текущий context, grants, hook subscriptions и активные задачи | Primary Agent Slot |
| Operator State | текущая авторизация, настройки интерфейса и пользовательские предпочтения | Operator identity |

Критический инвариант:

~~~text
Primary Agent State != Workspace State
~~~

Изменение состояния агента не должно автоматически изменять ownership или
состав Workspace.

## Идентичность Workspace

Workspace должен иметь собственный стабильный идентификатор, связанный с Node,
но не с агентом:

~~~yaml
workspace:
  id: workspace_node_22
  node_id: node_22
  revision: 1842
~~~

Идентификатор сохраняется при:

- перезапуске или отключении Primary Agent;
- замене агента или модели;
- отказе runtime;
- потере MCP-соединения;
- обновлении агента;
- подключении другого авторизованного UI.

Изменения semantic и presentation state должны иметь отдельные revisions или
эквивалентный механизм конкурентного контроля. Геометрия canvas не является
источником истины для Node State.

## Сохранность Workspace

Следующие операции не должны удалять или сбрасывать Workspace:

~~~text
Primary Agent restart
Primary Agent disconnect
Primary Agent replacement
Agent model replacement
Agent runtime failure
MCP connection loss
Agent upgrade
~~~

При замене агента сохраняются:

- Session history и Conversation Artifacts;
- Endpoint и Remote Agent relations;
- File Artifacts и Generated Reports;
- semantic groups и provenance;
- Node и ledger state.

Новый Primary Agent получает доступ только в пределах назначенных capability
grants. Сам факт назначения не делает его владельцем Workspace.

## Отношения оператора и агента

Оператор может взаимодействовать с Workspace напрямую или через Primary Agent:

~~~text
Operator
    │
    ▼
Node Workspace
    │
    ├── Primary Agent
    ├── Objects
    ├── Relations
    ├── Sessions
    └── Controls
~~~

Разрешённые способы взаимодействия включают:

- работу с canvas objects;
- открытие Session Artifacts;
- выбор Endpoint или Remote Agent;
- прикрепление файлов;
- изменение spatial layout;
- системное меню;
- разрешённые manual operations;
- естественно-языковые команды через Primary Agent.

Authorization должна проверяться для каждой операции отдельно. Нельзя
выводить права оператора или агента из факта отображения объекта на canvas.

## Recovery и отсутствие агента

Workspace должен оставаться доступным, даже если Primary Agent недоступен:

~~~text
Primary Agent
     OFFLINE
        ×

Node Workspace
     remains available
~~~

В этом состоянии авторизованный оператор должен иметь возможность:

- открыть существующие artifacts и conversations;
- увидеть Node status и активные операции;
- открыть system menu;
- заменить или повторно подключить Primary Agent;
- отозвать capability grants;
- остановить сессии и выполнить recovery operations.

Recovery path не зависит от LLM и должен быть доступен через отдельный
контрольный канал, определённый в [ADR-001](./ADR-001-primary-agent-scope.md) и
последующих security ADR.

## Пространственное представление

Spatial UI представляет Workspace конкретной Node. Центральный Agent Presence
является presentation instance Primary Agent Slot, а не владельцем пространства.

При замене агента:

1. Workspace и его semantic objects сохраняются;
2. Agent Presence сохраняет semantic identity slot;
3. меняется underlying Agent Binding;
4. изменяются статус и разрешения;
5. layout, relations и история остаются доступными.

Это позволяет менять Codex, локальную модель или AiDN-native agent без миграции
самого Workspace.

## Последствия

### Положительные

- стабильный контекст Node независимо от выбранного агента;
- независимость Workspace от конкретного UI и runtime;
- поддержка recovery и нескольких операторов;
- чёткое разделение semantic и presentation state;
- предсказуемая модель ownership и provenance.

### Ограничения

- необходимы отдельные persistence schemas для Node и Workspace;
- multi-device layout требует отдельного решения;
- правила retention и архивирования выносятся в SPATIAL-Q-007;
- local trust boundary и mediated remote resources зафиксированы в
  [ADR-012](./ADR-012-local-trust-boundary-and-mediated-remote-resources.md).

## Не входит в это решение

Этот ADR не определяет:

- границы и вложенность Sessions;
- каноническую модель presentation instances;
- конкретную базу данных, формат сериализации или CRDT;
- экономическую политику, escrow и budget controls;
- полный набор ролей и полномочий нескольких операторов.

## Критерии приёмки

Решение считается реализованным, когда:

- Workspace имеет стабильные workspace_id и node_id;
- ownership Workspace не зависит от Primary Agent или runtime;
- замена, сбой и отключение агента сохраняют semantic state и историю;
- semantic и presentation state разделены и версионируются;
- новый агент получает только назначенные capability grants;
- recovery mode позволяет работать с Workspace без LLM;
- операции оператора и агента проходят отдельную authorization check;
- есть тесты замены агента, потери MCP и восстановления Workspace.

## Связанные документы

- [Реестр открытых вопросов](./OPEN-QUESTIONS.md)
- [ADR-001 — Node-scoped Primary Agent](./ADR-001-primary-agent-scope.md)
- [Общий план Spatial Agent Interface](./AiDN-Spatial-Agent-Interface-Implementation-Plan.md)
