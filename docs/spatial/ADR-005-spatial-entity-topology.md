# ADR-005 — Spatial Entity Topology: Endpoints, Subagents and Remote Agents

**Статус:** Accepted  
**Дата решения:** 2026-09-03  
**Область:** Spatial Agent Interface, discovery, endpoints, subagents, semantic relations  
**Связанный вопрос:** [SPATIAL-Q-005 — Жизненный цикл обнаружения удалённых агентов](./OPEN-QUESTIONS.md#spatial-q-005--жизненный-цикл-обнаружения-удалённых-агентов)  
**Связанные решения:** [ADR-001 — Node-scoped Primary Agent](./ADR-001-primary-agent-scope.md), [ADR-002 — Node Workspace Ownership](./ADR-002-node-workspace-ownership.md), [ADR-003 — Orbital Attention System](./ADR-003-orbital-attention-system.md), [ADR-004 — Primary Agent Visual State Language](./ADR-004-primary-agent-visual-state-language.md)  
**Исходный план:** [AiDN Spatial Agent Interface — Implementation Plan](./AiDN-Spatial-Agent-Interface-Implementation-Plan.md)

## Решение

Spatial UI обязан различать классы субъектов, ресурсов, процессов и
представлений. Agent, Endpoint, Service, Session и Artifact не могут
использовать одну и ту же визуальную грамматику без дополнительных признаков.

Каноническое различие:

~~~text
Agent    → автономный Actor
Endpoint → доступная точка вызова Capability / Service
Service  → предоставляемая функциональная область
Session  → протокольный или пользовательский процесс взаимодействия
Artifact → результат, документ или сохранённое представление
~~~

Endpoint не является Agent и не должен выглядеть как самостоятельное живое
присутствие. Subagent является полноценным Agent Actor, но вторичным по
отношению к Primary Agent. Remote Agent является отдельным Actor и может быть
поставщиком Endpoint.

## Базовая визуальная грамматика

Формы являются семантическими классами, а конкретный frontend может
реализовать их органичнее:

~~~text
●  Primary Agent
○  Subagent / local secondary agent
◉  Remote Agent
◇  Endpoint / Service Energy Object
□  Artifact / Session / Information Object
•  Orbital Attention Marker
── luminous semantic relation
~~~

Primary Agent остаётся главным визуальным центром Node согласно [ADR-001](./ADR-001-primary-agent-scope.md).
Остальные сущности не должны конкурировать с ним по размеру, яркости или
визуальному весу без явного focus mode.

## Endpoint как Energy Object

Endpoint отображается как компактный энергетический объект, а не как
сферическое присутствие агента:

~~~text
        ·
     ·  ◇  ·
        ·
~~~

Центральное ядро представляет capability, а частицы вокруг него передают
динамику доступного сервиса. Endpoint может использовать следующие visual
channels:

- яркость ядра;
- количество и скорость частиц;
- halo;
- apparent size;
- stability;
- умеренный цветовой mapping.

Эти каналы могут отражать availability, latency, load, quality, price class и
health, но отображение должно быть сдержанным. Геометрия не должна одновременно
кодировать несколько числовых метрик, которые невозможно надёжно сравнить
визуально.

Рекомендуемая интерпретация:

~~~text
healthy → stable compact energy field
high load → slightly turbulent particles
offline → collapsed / dim energy field
selected → stronger halo
~~~

Фактические значения latency, цены, нагрузки и качества показываются в
Endpoint Information Surface, описанной ниже.

## Endpoint Arc

При discovery или выборе capability найденные Endpoint временно размещаются
перед соответствующим агентом в Endpoint Arc:

~~~text
          far                    far
       ◇                            ◇
          ◇                      ◇
             ◇                ◇
                ◇          ◇
                    ◇  ◇
                      ●
                 Primary Agent
~~~

Arc является пространственным представлением результатов discovery, а не
marketplace carousel.

Правила ранжирования:

- ближе к центральной части дуги — выше relevance или ranking score;
- более центральный объект — предпочтительный кандидат при текущем intent;
- доступный Endpoint имеет спокойное свечение;
- менее релевантный кандидат становится меньше, тусклее или глубже в Cloud
  Space;
- цена, latency и reputation не зашиваются одновременно в положение объекта.

Ближайшие кандидаты могут раскрываться в деталях по focus или selection.
Остальные остаются на дуге до завершения discovery или закрытия focus mode.

Каждый Agent MAY иметь собственную локальную Endpoint Arc. Она принадлежит
пространственному контексту этого агента и не смешивается с Orbital Attention
Markers.

## Выбор Endpoint

При выборе Endpoint выполняется переход:

~~~text
Endpoint Arc
      ↓
selected Endpoint
      ↓
detach from arc
      ↓
move toward Agent
      ↓
active Workspace object
~~~

Выбранный Endpoint становится active Workspace object только после явного
selection или установления взаимодействия. Остальные кандидаты могут
приглушаться, уходить в Cloud Space или исчезать после открытия Session.

Выбор не должен автоматически означать оплату, открытие Session или запуск
операции. Эти действия требуют отдельного intent и соответствующей policy.

## Endpoint Information Surface

Нажатие, tap или клавиатурный selection Endpoint открывает компактную
контекстную информационную поверхность, привязанную к объекту. На desktop это
может быть popover рядом с Endpoint, на узком экране — bottom sheet или
focus-panel. Это не отдельная страница и не новый protocol entity.

### Состав информации

Информационная поверхность SHOULD показывать:

- display name, endpoint ID и canonical semantic reference;
- capability, service type, model class и supported modalities;
- Node, Remote Agent или provider, предоставляющий Endpoint;
- состояние availability и health, время последнего подтверждения;
- latency с measurement window и percentile, если они доступны;
- текущую нагрузку, concurrency, queue state и estimated capacity;
- rate card: currency, billing dimensions, unit price, rounding и minimum
  charge;
- session requirements: minimum или recommended deposit, escrow и idle policy,
  если они применимы;
- validation, certification, reputation и protocol compatibility;
- accepted formats, context or payload limits, timeout и streaming support;
- privacy, trust и provenance indicators;
- краткое описание, ограничения и примеры допустимого использования.

Неподтверждённые данные не должны выдумываться. Если значение отсутствует,
отображается «Not reported» или эквивалентная локализованная метка с временем
последней проверки.

Пример семантической записи:

~~~yaml
endpoint_info:
  endpoint_ref:
  display_name:
  capability:
  provider_ref:
  owner_agent_ref:
  node_ref:
  availability:
    status:
    observed_at:
  performance:
    latency_ms:
    percentile:
    measurement_window:
  capacity:
    load:
    concurrency:
    queue_state:
  pricing:
    rate_card_ref:
    currency:
    dimensions:
    minimum_charge_q_atoms:
  session:
    minimum_deposit:
    recommended_deposit:
    idle_policy:
  validation:
    status:
    observed_at:
  compatibility:
    protocol_version:
    accepted_formats:
    timeout_seconds:
  provenance:
~~~

### Действия из Information Surface

В зависимости от статуса и policy доступны:

- Use / Select;
- Open full details;
- Inspect relation;
- Compare;
- Pin to Workspace;
- Start Session;
- Request approval;
- Hide или dismiss временный результат.

Кнопка Start Session не должна отображаться как выполненная операция до
подтверждения runtime или протокола. Цена, latency и депозит должны быть
видимы до действия, которое может создать обязательство.

### Поведение и доступность

- hover или focus может показывать короткий preview без изменения Workspace;
- click/tap/Enter открывает полную Information Surface;
- Esc, close и потеря focus закрывают поверхность без удаления Endpoint;
- keyboard focus и screen reader получают ту же информацию, что и pointer;
- focus trap не должен мешать System Menu или recovery mode;
- на mobile поверхность не должна закрывать Primary Agent и текущую
  provenance thread;
- при загрузке показывается skeleton, при устаревших данных — timestamp и
  stale indicator;
- поверхность не должна запускать или отменять сетевые операции только из-за
  факта открытия.

## Communication Thread

После selection между Primary Agent и Endpoint появляется semantic thread:

~~~text
Primary Agent
     ●
     │
     │
     ◇
  Endpoint
~~~

Thread представляет смысловое событие, а не raw network connection или каждый
WebSocket frame. Допустимые события:

- request;
- response;
- streaming;
- artifact transfer;
- payment;
- failure;
- session state transition.

Вместо стрелок и сетевой гирлянды используются мягкие luminous pulses вдоль
thread. Пульсация должна обозначать semantic event и не должна зависеть от
частоты транспортных пакетов.

Ключевое правило:

~~~text
Не отображаем пакеты.
Отображаем смысловые события.
~~~

## Subagent как Actor

Subagent является полноценным Agent Actor и принадлежит к тому же семантическому
классу, что Primary Agent:

~~~text
             ○
          Subagent
             │
             │
             ●
       Primary Agent
~~~

Subagent MAY использовать тот же spherical visual language, но должен быть:

- меньше по apparent size;
- менее ярким;
- с более слабым halo;
- с собственным operational state;
- отдельным объектом Workspace, а не marker на орбите внимания.

При spawn Subagent появляется рядом с Primary Agent и получает relation,
provenance и capability grant. Пространственная связь выражается линией или
semantic thread, но не иерархией каталогов.

Каждый Agent MAY иметь локальную interaction region:

~~~text
Agent
├── Orbital Attention Markers
├── Endpoint Arc
├── Active Endpoint
├── Subagents
└── Session Artifacts
~~~

Эта модель рекурсивна: Primary Agent является главным центром, а Subagent —
меньшим локальным центром собственной системы взаимодействий.

## Remote Agent и владение Endpoint

Если Remote Agent предоставляет Endpoint, это отображается отдельной
provenance-связью:

~~~text
      ◉ Remote Agent
             │
             │ PROVIDES
             ▼
             ◇ Endpoint
~~~

Основная operational thread при вызове Endpoint:

~~~text
● Primary Agent
       │
       ▼
◇ Endpoint
~~~

Связь Endpoint → Remote Agent остаётся вторичной provenance-связью. Вызов API
не должен визуально притворяться прямым разговором с владельцем Endpoint.
Information Surface обязана показывать, кто предоставляет capability и кто
подписывает результат, если эта информация доступна.

## Discovery и переход в Workspace

Discovery results являются временными presentation objects:

~~~text
DISCOVERED
    ↓
PRESENTED_IN_ARC
    ↓
INSPECTED
    ↓
SELECTED
    ↓
ACTIVE_WORKSPACE_OBJECT
    ↓
ARCHIVED / PINNED / DISMISSED
~~~

Для Remote Agent используется аналогичный lifecycle. Обнаруженный объект не
становится постоянной частью Workspace только потому, что попал в результат
поиска.

После завершения Session Endpoint или Remote Agent:

- сворачивается или затухает;
- архивируется как semantic relation;
- остаётся в Workspace, если закреплён;
- может быть автоматически поднят снова при регулярном использовании.

Dismiss временного presentation object не удаляет canonical Endpoint, Session,
Agent или provenance. Правила удаления определяются canonical policy и
согласуются с [ADR-003](./ADR-003-orbital-attention-system.md).

## Пример provenance topology

~~~text
                         ◇ Endpoint
                         │
                         │ request
                         ○ Research Subagent
                         │
                         │ delegated task
                         ● Primary Agent
~~~

Если Endpoint найден Subagent, Endpoint Arc принадлежит Subagent, но итоговая
semantic relation может быть видна в общем Workspace через provenance graph.

## Consequences

### Положительные

- Agent, Endpoint, Service, Session и Artifact различимы с первого взгляда;
- discovery можно показать без загрязнения постоянного Workspace;
- Endpoint Arc отображает relevance без перегрузки таблицами;
- Endpoint Information Surface даёт точные параметры до начала операции;
- Subagents получают собственные локальные interaction regions;
- provenance и ownership не смешиваются с транспортной связью;
- семантические события отделены от raw network activity.

### Ограничения

- понадобится единая schema для Endpoint profile и observed metrics;
- потребуется lifecycle временных discovery presentations;
- Information Surface должна корректно работать с устаревшими и неполными
  данными;
- рекурсивные interaction regions требуют ограничения глубины и capacity;
- geometry и visual channels нельзя использовать как единственный источник
  точных сравнений цены или производительности.

## Не входит в это решение

Этот ADR не определяет:

- identity и ownership Primary Agent — см. [ADR-001](./ADR-001-primary-agent-scope.md);
- ownership и persistence Workspace — см. [ADR-002](./ADR-002-node-workspace-ownership.md);
- lifecycle Orbital Attention — см. [ADR-003](./ADR-003-orbital-attention-system.md);
- полный visual state language Primary Agent — см. [ADR-004](./ADR-004-primary-agent-visual-state-language.md);
- протокол discovery, rate card или Session billing;
- конкретные frontend-компоненты, animation library и CSS tokens.

## Критерии приёмки

Решение считается реализованным, когда:

- Agent и Endpoint имеют разные semantic classes и visual grammar;
- Endpoint Arc создаётся как временное discovery presentation;
- selection переводит Endpoint в active Workspace object без скрытого запуска;
- click/tap/focus открывает доступную Information Surface с параметрами,
  availability, latency, нагрузкой, ценой и provenance;
- неизвестные или устаревшие значения помечаются явно;
- Remote Agent и предоставляемый им Endpoint связаны через provenance, но не
  выдаются за одну сущность;
- Subagent получает отдельный actor object и собственную interaction region;
- semantic threads показывают request/response и другие смысловые события, а
  не transport packets;
- dismiss/archive не удаляют canonical history или protocol records;
- есть desktop, mobile, keyboard и screen-reader сценарии;
- есть тесты discovery, selection, stale data, unavailable endpoint,
  aggregation и восстановления Workspace.

## Связанные документы

- [Реестр открытых вопросов](./OPEN-QUESTIONS.md)
- [ADR-001 — Node-scoped Primary Agent](./ADR-001-primary-agent-scope.md)
- [ADR-002 — Node Workspace Ownership](./ADR-002-node-workspace-ownership.md)
- [ADR-003 — Orbital Attention System](./ADR-003-orbital-attention-system.md)
- [ADR-004 — Primary Agent Visual State Language](./ADR-004-primary-agent-visual-state-language.md)
- [Общий план Spatial Agent Interface](./AiDN-Spatial-Agent-Interface-Implementation-Plan.md)
