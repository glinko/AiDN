# ADR-010 — Node Status and Recovery Access

**Статус:** Accepted  
**Дата решения:** 2026-09-04  
**Область:** Spatial Agent Interface, System Menu, Node status, recovery, operational diagnostics  
**Связанный вопрос:** [SPATIAL-Q-010 — Recovery mode при недоступности Primary Agent](./OPEN-QUESTIONS.md#spatial-q-010--recovery-mode-при-недоступности-primary-agent)  
**Связанные решения:** [ADR-001 — Node-scoped Primary Agent](./ADR-001-primary-agent-scope.md), [ADR-003 — Orbital Attention System](./ADR-003-orbital-attention-system.md), [ADR-004 — Primary Agent Visual State Language](./ADR-004-primary-agent-visual-state-language.md), [ADR-006 — Workspace Sessions and Context Graph](./ADR-006-workspace-sessions-context-graph.md), [ADR-009 — Multi-Device Workspace and Mobile Spatial Navigation](./ADR-009-multi-device-workspace-and-mobile-navigation.md)  
**Следующий связанный вопрос:** [SPATIAL-Q-011 — Экономическая прозрачность и управление бюджетом](./OPEN-QUESTIONS.md#spatial-q-011--экономическая-прозрачность-и-управление-бюджетом)  
**Исходный план:** [AiDN Spatial Agent Interface — Implementation Plan](./AiDN-Spatial-Agent-Interface-Implementation-Plan.md)

## Решение

System Menu является постоянным системным entry point Node и не зависит от
состояния Primary Agent. Отдельный аварийный dashboard, который появляется
только после сбоя, не вводится.

System Menu и Status работают напрямую через Node, Hypervisor и
соответствующие системные компоненты. Primary Agent может быть одним из
наблюдаемых компонентов, но никогда не является источником истины для
состояния Node.

~~~text
                  ○ System Menu
                  ● Primary Agent

System Menu → Status → authoritative component evidence
~~~

Даже если Primary Agent OFFLINE, не отвечает, потерял MCP-соединение,
перезапускается, отключён или не назначен, System Menu MUST оставаться
доступным для авторизованного оператора.

## Постоянный System Menu

Минимальная структура:

~~~text
System Menu
│
├── Status
├── Primary Agent
├── Node Settings
├── Appearance
├── Network
├── Wallet
├── Permissions
└── Advanced
~~~

Точная структура разделов может развиваться отдельно. Раздел Status и
канал прямого доступа к Node являются обязательными для первой реализации.

System Menu принадлежит Node UI shell и не является частью
Conversation Surface, Agent Presence или LLM runtime. Вход в меню должен
оставаться возможным из любого viewport согласно [ADR-009](./ADR-009-multi-device-workspace-and-mobile-navigation.md),
включая состояние, когда camera указывает на Deep Memory или Primary Agent
недоступен.

## Authoritative Status Sources

Status Aggregator должен получать фактическое состояние напрямую от
компонентов:

~~~text
Hypervisor / Node services
          │
          ├── process and health probes
          ├── MCP transport
          ├── hooks runtime
          ├── network and peer subsystem
          ├── wallet / secret-store availability
          ├── sessions and tasks
          ├── endpoints and providers
          └── resource probes
          │
          ▼
   Node Status Aggregator
          │
          ▼
   System Menu → Status
~~~

Цепочка Primary Agent → Status запрещена. Агент может сообщить собственное
наблюдение как secondary evidence, но его ответ не заменяет probe,
heartbeat, service health или authoritative component state.

Если authoritative source не отвечает, Status показывает UNKNOWN или STALE с
временем последнего наблюдения. Нельзя превращать отсутствие ответа агента
в ложное ONLINE и нельзя скрывать отсутствие свежих данных.

## Status Summary

Status представляет компактный фактический overview, а не второй полноценный
dashboard:

~~~text
NODE 22
Node                 ● Online
Hypervisor           ● Running
Primary Agent        ○ Offline
MCP Server           ○ Disconnected
Hooks                ● Queued
Network              ● Connected
Wallet               ● Available
Active Sessions      3
Running Tasks        1
Endpoints            7 active
Warnings             2
~~~

Каждая строка должна иметь state, timestamp/freshness и переход к деталям.
Сводка не обязана показывать все метрики и логи; её задача — быстро
ответить, в каком фактическом состоянии находится Node и какая подсистема
требует внимания.

Поддерживаемые базовые states:

~~~text
ONLINE
RUNNING
STARTING
STOPPING
DEGRADED
OFFLINE
DISCONNECTED
BLOCKED
UNKNOWN
STALE
~~~

Конкретный state vocabulary может быть расширен для отдельных компонентов,
но значение должно быть явным и иметь источник наблюдения.

## Два уровня индикации при сбое агента

Когда Primary Agent недоступен, работают два взаимодополняющих слоя:

1. Spatial UI показывает Primary Agent как OFFLINE согласно visual language
   [ADR-004](./ADR-004-primary-agent-visual-state-language.md).
2. System Menu → Status показывает Node и component evidence с причиной,
   временем и возможными прямыми действиями.

~~~text
Spatial indication:
                  ●
               gray / dim
                 no pulse
              Primary Agent
                 OFFLINE

Status:
Node                 ● Online
Hypervisor           ● Running
Primary Agent        ○ Offline
MCP connection       ○ Disconnected
Last agent response  3 min ago
Hooks                ● Queued
~~~

Spatial presence даёт оператору мгновенный сигнал. Status отвечает на вопрос,
что именно произошло. Эти уровни не должны конкурировать и не должны
дублировать друг друга длинными сообщениями.

## Progressive Detail

Диагностика раскрывается по уровням:

~~~text
Spatial indication
        ↓
Status Summary
        ↓
Detailed subsystem view
~~~

Пример:

~~~text
Primary Agent gray
        ↓
System Menu → Status
Primary Agent: OFFLINE
Last seen: 03:17
        ↓
open details
        ↓
Agent Details
────────────────
Agent: Codex
Binding: primary
Backend: unavailable
MCP: disconnected
Hooks pending: 4
Last successful request: ...
Permissions: ...
~~~

Summary и details должны использовать один status snapshot и одну revision,
чтобы переход в подробности не показывал данные из другой эпохи без
явного stale marker.

## Detailed Subsystem View

Каждый component detail должен показывать:

- component identity и role;
- state;
- authoritative source;
- last observed time;
- freshness/TTL;
- краткое объяснение причины;
- связанные evidence или log reference;
- доступные безопасные действия;
- SHOW_IN_WORKSPACE, если существует spatial representation.

Детальный view не должен требовать вызова Primary Agent или LLM. Формулировка
объяснения может быть сгенерирована позднее, но сырые факты, timestamps и
state берутся из Node Status Aggregator.

## Recovery Access и прямые действия

Recovery access — это постоянный capability System Menu, а не отдельная
аварийная страница. В read-only режиме оператор всегда может просмотреть:

- Node и Hypervisor state;
- Primary Agent binding и last-seen evidence;
- MCP connection и hooks queue;
- Wallet availability и pending state;
- permissions и active grants;
- running sessions и tasks;
- endpoints, providers и resource warnings;
- expenditures и связанные audit references.

Изменяющие действия проходят прямой canonical command path и не зависят от
LLM. В зависимости от capability policy могут быть доступны:

- suspend или resume Primary Agent;
- revoke agent binding или отдельный capability;
- stop/cancel session или task;
- disable endpoint;
- block further expenditure;
- restart сервисного компонента;
- открыть подробности evidence.

Каждое действие должно иметь явный impact, confirmation и audit record.
Status View не получает право менять данные только потому, что он доступен
при сбое агента.

## SHOW_IN_WORKSPACE

Status не должен становиться вторым параллельным интерфейсом управления.
Он является диагностическим индексом реальных Node и Workspace entities.

Универсальная операция:

~~~text
SHOW_IN_WORKSPACE
~~~

Она доступна для:

- Primary Agent;
- Subagent или Remote Agent;
- Endpoint;
- Session;
- Task;
- Warning;
- Resource;
- Node component.

Flow:

~~~text
Status → "2 degraded endpoints"
       → SHOW_IN_WORKSPACE
       → camera focus / Pull-to-Focus
       → actual spatial entities
~~~

Если у объекта есть primary spatial presence, System Menu закрывается или
сворачивается, камера переводится к нему, а исходный menu context сохраняется
для возврата. Focus изменяет только viewport, не canonical topology, что
согласуется с [ADR-007](./ADR-007-spatial-memory-aging-clustering.md).

Если spatial representation отсутствует, Status открывает обычный detail
surface с тем же object reference и provenance. Он не создаёт визуальный
дубликат, согласно [ADR-008](./ADR-008-entity-uniqueness-and-provenance.md).

## Status Snapshot и freshness

Минимальный контракт snapshot:

~~~yaml
node_status_snapshot:
  node_id:
  generated_at:
  node_revision:
  overall_state:
  freshness:
  components:
    - key:
      kind:
      state:
      observed_at:
      stale_after:
      source:
      evidence_ref:
      spatial_ref:
      available_actions:
  active_sessions:
  running_tasks:
  active_endpoints:
  warning_count:
  revision:
  provenance:
~~~

Правила freshness:

1. observed_at относится к фактическому probe или event, а не к времени
   рендера страницы.
2. После stale_after item получает STALE, даже если последнее состояние
   было ONLINE.
3. При недоступном source item получает UNKNOWN или OFFLINE согласно
   семантике компонента, но причина и время последнего evidence сохраняются.
4. Cached snapshot может быть показан offline, но маркируется как
   last-known и не выдаётся за current state.
5. Сводка и detail используют revision snapshot; обновление выполняется
   атомарно или явно помечается partial.

## Status Events

Status Aggregator может публиковать системные события:

~~~text
status.updated
status.degraded
status.offline
status.stale
status.recovered
recovery.action.requested
recovery.action.completed
recovery.action.failed
~~~

События должны содержать component key, node revision, observed_at,
evidence reference и correlation ID. Они могут порождать orbital attention
marker через [ADR-003](./ADR-003-orbital-attention-system.md), но attention
не заменяет Status и не должен скрывать фактическую причину.

## Offline, reload и частичный сбой

System Menu shell должен загружаться независимо от Primary Agent и
Conversation Surface. Если Status Aggregator временно недоступен:

- меню остаётся доступным;
- показывается last-known snapshot с timestamp;
- stale state виден до получения свежего snapshot;
- попытка обновления не вызывает LLM;
- detail view сообщает, какая именно подсистема недоступна;
- recovery actions остаются disabled, пока не подтверждён authoritative
  command channel.

После reload или reconnection UI не должен сбрасывать оператора в
Conversation Surface вместо Status. Оператор может вручную перейти в
FOCUS_PRIMARY_AGENT или SHOW_IN_WORKSPACE.

## Access Control и аудит

System Menu доступен только авторизованному оператору или capability,
разрешающей read-only status. Независимость от Primary Agent не означает
обход ownership или authorization.

Каждый recovery action сохраняет:

- operator identity;
- node identity;
- component key;
- requested action;
- impact/confirmation;
- authorization decision;
- before и after status;
- correlation ID;
- timestamp и revision.

Status read path и mutating recovery command path должны быть разделены.
Отсутствие агента не должно позволять UI выполнять неподтверждённые
операции от имени неизвестного пользователя.

## Accessibility и responsive behavior

System Menu и Status должны быть доступны:

- с keyboard и screen reader;
- при reduced-motion;
- на desktop, tablet и mobile;
- при недоступном или невидимом Primary Agent;
- без обязательного hover или spatial gesture.

Для mobile Status открывается как обычный focus surface или bottom sheet,
но остаётся тем же Node Status view. SHOW_IN_WORKSPACE возвращает оператора
в semantic space и сохраняет обратную навигацию.

Color, glow и dimmed Presence не являются единственным способом определить
OFFLINE, DEGRADED или STALE. Каждый state имеет текстовую метку и
доступное описание.

## Инварианты

**STATUS-INV-001 — Node-owned entry point**

System Menu MUST существовать независимо от lifecycle Primary Agent и
оставаться доступным при его OFFLINE, DISCONNECTED, STOPPING или отсутствии.

**STATUS-INV-002 — Direct authority**

Status MUST строиться на authoritative evidence Node/Hypervisor и
компонентов, а не на ответе Primary Agent.

**STATUS-INV-003 — Explicit freshness**

UNKNOWN, STALE и last-known state нельзя показывать как current ONLINE.

**STATUS-INV-004 — Progressive detail**

Summary, details и raw evidence используют совместимые snapshot revision и
не требуют LLM для фактического состояния.

**STATUS-INV-005 — Recovery without topology mutation**

Просмотр Status, SHOW_IN_WORKSPACE и recovery navigation не изменяют
Workspace topology, canonical objects или provenance.

**STATUS-INV-006 — Direct command path**

Изменяющие recovery actions выполняются только через canonical command path,
с authorization, confirmation и audit.

**STATUS-INV-007 — Spatial bridge**

SHOW_IN_WORKSPACE должен фокусировать существующую spatial entity или
показать detail без создания visual duplicate.

**STATUS-INV-008 — Device independence**

System Menu и Status доступны на любом device viewport согласно
[ADR-009](./ADR-009-multi-device-workspace-and-mobile-navigation.md), а
camera одного устройства не меняет другую без явного Share View.

## Реализационные слайсы

1. **Node Status Aggregator.** Собрать direct probes, freshness, evidence и
   component snapshot.
2. **Permanent System Menu.** Вынести menu shell из Agent/Conversation
   lifecycle и обеспечить read-only доступ при offline состоянии.
3. **Status Summary.** Реализовать компактные component rows, timestamps,
   stale/unknown states и переход к details.
4. **Subsystem Details.** Добавить Agent, MCP, hooks, wallet, network,
   sessions, endpoints и resource details без вызова LLM.
5. **Recovery commands.** Связать suspend/revoke/stop/block/restart с
   canonical command path и audit.
6. **SHOW_IN_WORKSPACE.** Связать status references с spatial presence и
   Pull-to-Focus.
7. **Offline and freshness.** Проверить cached snapshots, reload, partial
   failure, recovery и stale evidence.
8. **Accessibility.** Добавить keyboard, screen-reader, mobile bottom
   sheet и reduced-motion.

## Положительные последствия

- Оператор всегда имеет прямой доступ к фактическому состоянию Node.
- Не нужен отдельный emergency dashboard, конкурирующий с Spatial UI.
- Сбой Primary Agent не скрывает wallet, sessions, hooks, network и
  endpoint evidence.
- Status и Spatial Workspace дополняют друг друга: один объясняет факты,
  второй показывает реальные сущности.
- Recovery actions остаются управляемыми и аудируемыми без участия LLM.

## Ограничения и риски

- Нужен надёжный Status Aggregator с определёнными freshness/TTL.
- Разные компоненты могут иметь разные health semantics; vocabulary должен
  оставаться понятным оператору.
- Cached state может быть устаревшим и обязан иметь явную маркировку.
- Большое число warnings и details требует фильтрации, но не должно
  скрывать critical state.
- Экономические детали и полный budget control остаются предметом Q-011.

## Не входит в это решение

Этот ADR не определяет:

- конкретный transport для health probes;
- полную экономическую модель и budget policy;
- замену Primary Agent или его runtime;
- глобальный audit storage и retention;
- конкретный frontend framework или component library;
- отдельный emergency dashboard.

## Критерии приёмки

Решение считается реализованным, когда:

- System Menu открывается при работающем, перезапускаемом и полностью
  недоступном Primary Agent;
- Status строится без запроса к LLM и содержит authoritative source,
  timestamp и freshness;
- Node, Hypervisor, Primary Agent, MCP, hooks, network, wallet, sessions,
  tasks и endpoints имеют понятные states;
- UNKNOWN, STALE и last-known states явно различимы с текстом и
  screen-reader label;
- переход Summary → Details сохраняет snapshot revision и provenance;
- SHOW_IN_WORKSPACE приводит к существующей entity без создания дубликата;
- recovery actions требуют authorization, confirmation и audit;
- cached/offline snapshot не выдаётся за текущий ONLINE;
- desktop, mobile, keyboard, screen-reader и reduced-motion сценарии
  работают;
- parallel device viewport не меняется без явного Share View;
- failure/recovery/partial status tests покрыты.

## Связанные документы

- [Реестр открытых вопросов](./OPEN-QUESTIONS.md)
- [ADR-001 — Node-scoped Primary Agent](./ADR-001-primary-agent-scope.md)
- [ADR-003 — Orbital Attention System](./ADR-003-orbital-attention-system.md)
- [ADR-004 — Primary Agent Visual State Language](./ADR-004-primary-agent-visual-state-language.md)
- [ADR-006 — Workspace Sessions and Context Graph](./ADR-006-workspace-sessions-context-graph.md)
- [ADR-007 — Spatial Memory, Aging and Clustering](./ADR-007-spatial-memory-aging-clustering.md)
- [ADR-008 — Entity Uniqueness and Provenance References](./ADR-008-entity-uniqueness-and-provenance.md)
- [ADR-009 — Multi-Device Workspace and Mobile Spatial Navigation](./ADR-009-multi-device-workspace-and-mobile-navigation.md)
- [Общий план Spatial Agent Interface](./AiDN-Spatial-Agent-Interface-Implementation-Plan.md)
