# ADR-006 — Workspace Sessions and Context Graph

**Статус:** Accepted  
**Дата решения:** 2026-09-04  
**Область:** Spatial Agent Interface, sessions, context, branching, provenance  
**Связанный вопрос:** [SPATIAL-Q-006 — Границы Session и вложенные операции](./OPEN-QUESTIONS.md#spatial-q-006--границы-session-и-вложенные-операции)  
**Связанные решения:** [ADR-001 — Node-scoped Primary Agent](./ADR-001-primary-agent-scope.md), [ADR-002 — Node Workspace Ownership](./ADR-002-node-workspace-ownership.md), [ADR-003 — Orbital Attention System](./ADR-003-orbital-attention-system.md), [ADR-004 — Primary Agent Visual State Language](./ADR-004-primary-agent-visual-state-language.md), [ADR-005 — Spatial Entity Topology](./ADR-005-spatial-entity-topology.md)  
**Исходный план:** [AiDN Spatial Agent Interface — Implementation Plan](./AiDN-Spatial-Agent-Interface-Implementation-Plan.md)

## Решение

Workspace Session — это пользовательский semantic context, начинающийся с
явного взаимодействия оператора с Primary Agent. Внутри Workspace Session
формируется граф контекста, базовая структура которого является ветвящимся
деревом.

Workspace Session не отождествляется с протокольной AiDN Session. Первая
описывает человеческий контекст и историю работы в Workspace, вторая —
конкретное протокольное или экономическое взаимодействие между Actors,
Endpoint и Services.

Каноническая модель:

~~~text
Workspace Session
│
├── Root Interaction
├── Conversation Surfaces
├── Generated Objects
├── Branches
├── Context References
└── Related AiDN Protocol Sessions
~~~

## Создание Workspace Session

Workspace Session создаётся при явном вводе оператора:

1. создан Interaction Seed в свободной точке Workspace и отправлен текст;
2. инициировано голосовое обращение к Primary Agent;
3. выполнен другой явный input, создающий новый interaction context.

Открытие системного меню, пассивное обнаружение события или автоматическое
обновление данных само по себе не создаёт новую Workspace Session.

Начальный input формирует Root Interaction. Все последующие ветви,
Conversation Surfaces и Generated Objects получают ссылку на session ID и root
provenance.

## Conversation Surface

Если результат естественно представим текстом, он остаётся в той же
Conversation Surface:

~~~text
┌─────────────────────────────┐
│ Operator                     │
│ Объясни состояние Endpoint   │
│                             │
│ Primary Agent                │
│ Endpoint работает, но...     │
│                             │
│ Operator                     │
│ А почему latency выросла?    │
│                             │
│ Primary Agent                │
│ ...                          │
└─────────────────────────────┘
~~~

Каждое сообщение не превращается в отдельный Workspace object. Новая
Conversation Surface создаётся только при явном branching, выборе другого
context anchor или переходе к типу представления, который должен жить отдельно.

## Generated Objects

Если результат лучше представить отдельным объектом, агент создаёт Generated
Object рядом с исходной Conversation Surface и связывает его semantic thread:

~~~text
┌────────────────┐
│ Conversation    │
└───────┬────────┘
        │ semantic thread
        ▼
┌───────┴────────┐
│ Chart / Report │
└────────────────┘
~~~

Generated Object может быть:

- Image;
- Table;
- Chart;
- File;
- Report;
- Code;
- Topology;
- Endpoint Card;
- Agent Object;
- Payment Object;
- другой тип, определённый canonical schema.

Тип данных определяется semantic reference, а не формой визуального контейнера.
Layout Engine выбирает свободное место. Большой объект может временно занять
центральную область через Focus Translation согласно [ADR-003](./ADR-003-orbital-attention-system.md).

Импульсы вдоль semantic thread используются только для смысловых событий:

~~~text
Conversation ────────●────→ Generated Table
~~~

Импульс означает создание, обновление или передачу результата. Он не должен
отображать каждый transport packet или WebSocket frame.

## Context Graph

Каждый interaction branch имеет не более одного structural parent. Один parent
может иметь любое количество descendants:

~~~text
parent_count(node) <= 1
child_count(node)  >= 0
~~~

Это даёт ветвящееся дерево контекста:

~~~text
                   [A]
                  /   \
                 /     \
               [B]     [C]
                |
               [D]
~~~

Пользователь может вернуться к любой точке и начать новую ветвь, не создавая
линейный список независимых чатов.

### Типы связей

Используются две разные семантики:

~~~text
CONTINUES_FROM
→ structural parent, максимум одна связь

USES_CONTEXT
→ дополнительные контекстные ссылки, 0..N
~~~

CONTINUES_FROM отвечает на вопрос «откуда продолжается эта ветка».  
USES_CONTEXT отвечает на вопрос «какие дополнительные материалы нужно
учесть».

Structural parent должен принадлежать тому же Workspace Session. Context
references могут указывать на любой доступный оператору Workspace object, в том
числе на объект другой закрытой Session, если это разрешено policy.

Пример:

~~~text
        [PDF]
          ╲
           ╲ USES_CONTEXT
            ╲
[A] ─────── [NEW]
  CONTINUES_FROM  ╲
                   ╲ USES_CONTEXT
                    [IMAGE]
~~~

Несколько USES_CONTEXT не превращаются в несколько structural parents. Это
сохраняет понятную историю ветвления и не разрушает provenance.

## Context Linking

Interaction Seed должен поддерживать действие LINK. Оно позволяет продолжить
существующий контекст без создания новой независимой цепочки.

Рекомендуемая семантика выбора:

1. первый выбранный объект становится structural parent;
2. последующие выбранные объекты добавляются в context_refs;
3. оператор может явно выбрать режим Continue from или Add to context;
4. ссылки видны до отправки input и могут быть удалены до подтверждения.

Пример:

~~~text
new Interaction Seed
        │
       LINK
        │
        ▼
browse / select previous object
        │
        ▼
establish context relation
~~~

Link UI не должен требовать отдельной страницы. На desktop используется
контекстный picker или spatial selection, на mobile — полноэкранный или
bottom-sheet picker с теми же semantic roles.

## Lifecycle Workspace Session

~~~text
CREATED
    ↓
ACTIVE
    ↓
BRANCHING
    ↓
IDLE
    ↓
CLOSED
    ↓
ARCHIVED
~~~

- CREATED — создан Root Interaction, но ответ ещё не получен.
- ACTIVE — выполняется текущая Conversation Surface или связанная операция.
- BRANCHING — создаётся новая ветвь или добавляются context references.
- IDLE — пользователь временно не взаимодействует, но Session доступна.
- CLOSED — активные поверхности закрыты; граф и история сохранены.
- ARCHIVED — Session вынесена из активного viewport, но доступна через поиск и
  историю.

Состояния не должны смешиваться с lifecycle протокольных Sessions. Закрытие
Workspace Session не должно автоматически означать немедленное удаление или
отмену каждой связанной AiDN Session; правила завершения и billing определяются
протоколом.

## Workspace Session и AiDN Protocol Session

В одной Workspace Session может быть несколько протокольных Sessions:

~~~text
Workspace Session S-42
        │
        ├── AiDN Session P-1001
        │      Primary → Endpoint X
        │
        ├── Subagent
        │      └── AiDN Session P-1002
        │             Subagent → Endpoint Y
        │
        └── AiDN Session P-1003
               Primary → Endpoint Z
~~~

Для оператора это одна исследовательская или рабочая Session. На уровне
протокола каждая AiDN Session имеет собственные ownership, authorization,
provenance, escrow, billing и lifecycle.

Protocol Session не является structural node Workspace Context Graph. Она
связывается через related_protocol_sessions и отображается как relation или
Generated Object, но не создаёт автоматически новый пользовательский чат.

## Voice Session

Голосовой ввод создаёт Workspace Session Root тем же способом, что и текст:

~~~text
click Primary Agent
        ↓
voice conversation
        ↓
Workspace Session Root
~~~

После завершения голосовая Conversation Surface может быть свернута в Session
Artifact. Transcript, summary, associated semantic context и provenance
сохраняются в artifact reference.

Новая Interaction Seed может продолжить голосовую ветвь через LINK:

~~~text
New Text Surface ───────→ Old Voice Session Artifact
~~~

Голосовая и текстовая формы остаются разными presentation surfaces, но могут
принадлежать одному Context Graph.

## Закрытие и схлопывание

При закрытии активной Conversation Surface:

~~~text
FULL
  ↓
COLLAPSE
  ↓
SESSION ARTIFACT
~~~

Дерево контекста не удаляется:

~~~text
             □
            / \
           □   □

             ↓ collapse

             ▣
        Session Artifact
~~~

Раскрытие Session Artifact восстанавливает graph view или открывает его
в Focus Mode. Схлопывание изменяет presentation state, но не semantic state и
не protocol records.

## Модель данных

Минимальная запись Workspace Session:

~~~yaml
workspace_session:
  id:
  workspace_id:
  root_interaction_id:
  status:
  created_at:
  updated_at:
  closed_at:
  revision:
  provenance:
~~~

Минимальная запись interaction node:

~~~yaml
interaction_node:
  id:
  workspace_session_id:
  kind:
  structural_parent_ref:
  context_refs:
    - object_ref:
      relation: USES_CONTEXT
  surface_ref:
  generated_object_refs:
    - object_ref:
  related_protocol_sessions:
    - session_ref:
  status:
  created_at:
  provenance:
~~~

Инварианты модели:

- structural_parent_ref содержит не более одной ссылки;
- CONTINUES_FROM не образует циклов;
- context_refs не меняют parent-child topology;
- протокольные Sessions хранятся как related references;
- каждая ссылка проверяется через Workspace authorization policy;
- удаление presentation instance не удаляет referenced semantic object.

## Layout и camera

Context Graph хранит semantic topology отдельно от экранных координат. Layout
Engine может перестраивать расположение объектов при branching, создании
Generated Object или изменении viewport.

Focus Translation изменяет только camera transform; координаты World Space и
relations не переписываются. Это согласуется с [ADR-003](./ADR-003-orbital-attention-system.md)
и предотвращает изменение сохранённого дерева при временном раскрытии объекта.

Semantic thread между parent, child и context reference должна отличаться по
толщине или glyph:

~~~text
CONTINUES_FROM → основная, более заметная thread
USES_CONTEXT   → вторичная, более тонкая thread
~~~

Ни один визуальный канал не является единственным источником истины о
направлении связи; доступные labels и inspect relation должны раскрывать тип
relation.

## Access Control и provenance

Создание ветви, добавление context reference, открытие чужого Session Artifact
и использование протокольного Session требуют проверки capability policy.

Каждая операция должна сохранять:

- operator identity;
- primary agent или subagent identity;
- workspace session ID;
- parent/context references;
- related protocol session IDs;
- timestamp и revision;
- результат authorization check.

Недоступный или отозванный объект не удаляется из истории автоматически; он
показывается как unavailable reference с причиной и временем проверки.

## Consequences

### Положительные

- история взаимодействия становится пространственным Context Graph, а не
  линейным списком сообщений;
- ветвление не создаёт множество независимых пользовательских чатов;
- пользовательский контекст отделён от протокольной и экономической Session;
- один interaction может использовать сколько угодно дополнительного контекста;
- голосовые, текстовые и объектные представления объединяются одной provenance;
- Focus Translation и collapse не повреждают semantic topology.

### Ограничения

- потребуется отдельное хранилище Workspace Session и Context Graph;
- нужен lifecycle для branches, references и Session Artifacts;
- необходимо предотвращать циклы, слишком глубокие ветви и визуальное
  переполнение;
- billing и протокольные операции должны иметь собственные Session records;
- picker context references должен учитывать authorization и stale objects.

## Не входит в это решение

Этот ADR не определяет:

- ownership Workspace — см. [ADR-002](./ADR-002-node-workspace-ownership.md);
- семантику Primary Agent — см. [ADR-001](./ADR-001-primary-agent-scope.md);
- окончательный billing и escrow protocol;
- полную схему canonical objects и presentation instances;
- конкретную БД, CRDT, frontend framework или animation library;
- политику retention и semantic search для архивных Sessions.

## Критерии приёмки

Решение считается реализованным, когда:

- явный текстовый и голосовой input создают Workspace Session Root;
- продолжение в одной Conversation Surface не создаёт новый object на каждое
  сообщение;
- Generated Objects связываются с источником semantic thread;
- structural parent ограничен одной связью, context_refs поддерживает 0..N;
- LINK позволяет выбрать parent и дополнительные context references;
- ветвление отображается как дерево без принудительного списка новых чатов;
- одна Workspace Session может ссылаться на несколько AiDN Protocol Sessions;
- протокольные Sessions не создают автоматически пользовательские чаты;
- закрытие и collapse сохраняют Context Graph и provenance;
- Focus Translation не меняет World Space coordinates;
- authorization проверяется для каждой ссылки и операции;
- есть desktop, mobile, keyboard, voice и recovery сценарии.

## Связанные документы

- [Реестр открытых вопросов](./OPEN-QUESTIONS.md)
- [ADR-001 — Node-scoped Primary Agent](./ADR-001-primary-agent-scope.md)
- [ADR-002 — Node Workspace Ownership](./ADR-002-node-workspace-ownership.md)
- [ADR-003 — Orbital Attention System](./ADR-003-orbital-attention-system.md)
- [ADR-004 — Primary Agent Visual State Language](./ADR-004-primary-agent-visual-state-language.md)
- [ADR-005 — Spatial Entity Topology](./ADR-005-spatial-entity-topology.md)
- [Общий план Spatial Agent Interface](./AiDN-Spatial-Agent-Interface-Implementation-Plan.md)
