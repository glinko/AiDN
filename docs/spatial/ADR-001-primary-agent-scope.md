# ADR-001 — Node-scoped Primary Agent

**Статус:** Accepted  
**Дата решения:** 2026-09-03  
**Область:** Spatial Agent Interface, identity, delegation, Node control plane  
**Связанный вопрос:** [SPATIAL-Q-001 — Семантика и жизненный цикл Primary Agent](./OPEN-QUESTIONS.md#spatial-q-001--семантика-и-жизненный-цикл-primary-agent)  
**Связанные вопросы:** [SPATIAL-Q-002 — Ownership рабочего пространства](./OPEN-QUESTIONS.md#spatial-q-002--ownership-рабочего-пространства), [SPATIAL-Q-012 — Local Trust Boundary и mediated remote resource access](./OPEN-QUESTIONS.md#spatial-q-012--local-trust-boundary-и-mediated-remote-resource-access)  
**Исходный план:** [AiDN Spatial Agent Interface — Implementation Plan](./AiDN-Spatial-Agent-Interface-Implementation-Plan.md)

## Решение

Primary Agent определяется как роль, назначенная конкретной AiDN Node. Это не
глобальный агент пользователя, не тип модели и не конкретная реализация
runtime.

Каждая Node имеет один Primary Agent Slot. В slot назначается текущая Agent
Identity и её binding к MCP, hooks и разрешённому набору операций Hypervisor.
В пространственном интерфейсе центральный Agent Presence представляет именно
этот slot и его состояние.

Модель:

~~~text
AiDN Node
 ├── Hypervisor
 ├── MCP Server
 ├── Hook Bus
 └── Primary Agent Slot
        └── current Agent Binding
~~~

Один и тот же пользователь может иметь разные Primary Agents для разных Nodes.
Одна и та же реализация агента, например Codex или локальная модель, может быть
назначена в несколько slots, но каждое назначение является отдельной
Node-scoped binding.

## Обоснование

Node-scoped модель:

- сохраняет однозначную границу полномочий и operational state;
- не связывает UI с конкретным провайдером или моделью;
- позволяет заменять Codex, локальную модель или AiDN-native agent без изменения
  канонической модели Node;
- упрощает аудит, provenance и маршрутизацию hooks;
- предотвращает ошибочное представление, будто агент пользователя имеет
  автоматический доступ ко всем его Nodes.

## Каноническая сущность Primary Agent Slot

Минимальная запись slot должна содержать:

| Поле | Назначение |
|---|---|
| slot_id | стабильный идентификатор роли в Node |
| node_id | Node, которой принадлежит slot |
| status | состояние slot |
| agent_identity | назначенная Agent Identity |
| binding | MCP/transport/runtime binding |
| capability_grant | набор разрешённых возможностей |
| assigned_at | время назначения |
| changed_at | время последнего изменения |
| provenance | кто и каким подтверждённым действием изменил binding |

Роль, Agent Identity и реализация runtime должны храниться раздельно. Запись
вида «Primary Agent = Codex» не является канонической моделью; канонической
является запись «Primary Agent Slot → current binding: Codex».

## Жизненный цикл назначенного агента

Поддерживаемые состояния slot:

~~~text
UNASSIGNED
    │
    ▼
ATTACHING ─────► ACTIVE
    ▲              │
    │              ▼
DETACHING ◄──── SUSPENDED
    │
    ▼
UNASSIGNED
~~~

Дополнительные terminal или protective states, например REVOKED или
DEGRADED, могут быть добавлены отдельным ADR. Переходы должны быть
аудируемыми и атомарными.

### Правила замены

Замена Primary Agent является отдельной control operation:

1. проверить права инициатора и новый Agent Binding;
2. остановить или перевести текущие операции в безопасное состояние;
3. выполнить DETACH текущего binding;
4. создать запись provenance;
5. выполнить ATTACH нового binding;
6. выдать новый capability grant согласно policy Node;
7. доставить новому агенту разрешённые непрочитанные события.

Замена не должна:

- удалять состояние Node;
- удалять workspace, session history или артефакты;
- изменять ledger state;
- передавать новому агенту полномочия автоматически и без проверки policy;
- скрывать активные операции от recovery mode.

## Полномочия

Назначение Primary Agent не означает root-доступ. Полномочия выдаются через
отдельный Agent Capability Grant, ограниченный policy конкретной Node.

Пример capability set:

- hypervisor.read;
- resource.inspect;
- endpoint.manage;
- runtime.manage;
- hooks.receive;
- session.observe;
- wallet.read;
- wallet.spend — только при отдельном разрешении и экономической policy.

Полный список capability и режимы approve/deny/auto должны быть определены в
отдельной policy-спецификации. Владелец Node может отозвать grant независимо от
доступности Primary Agent.

## Hooks и события

Hooks Node маршрутизируются активному Primary Agent через policy и redaction:

~~~text
Node Event
    ↓
Hook Bus
    ↓
Policy / Redaction
    ↓
Primary Agent
~~~

Если активного агента нет, событие помещается в durable inbox. Событие не
теряется и не становится автоматически доступным новому агенту: доставка
определяется policy, типом события и его чувствительностью.

Каждая доставка должна содержать Node ID, slot ID, event ID, timestamp и
provenance. Повторная доставка должна быть идемпотентной.

## Представление в Spatial UI

Центральный luminous Agent Presence представляет активный Primary Agent Slot.
При замене агента объект пространства сохраняется, а изменяется его underlying
binding и состояние. Это позволяет не терять layout, связи, историю и
семантические ссылки при смене модели или MCP-провайдера.

В интерфейсе должен существовать небольшой постоянный entry point системного
меню, визуально вторичный относительно Agent Presence. Через него доступны:

- Node Settings;
- Primary Agent Settings;
- Agent Replacement;
- Permissions;
- Network;
- Wallet;
- Advanced / Manual Mode.

Детальная структура меню, включая responsive-варианты, выносится в отдельный
UX-документ.

## Последствия

### Положительные

- стабильная Node-scoped ownership и provenance;
- независимость интерфейса от конкретной LLM;
- безопасная смена агента;
- предсказуемая маршрутизация hooks;
- сохранение workspace и истории при изменении binding.

### Ограничения

- потребуется отдельная модель capability grants;
- нужно реализовать durable inbox и policy доставки hooks;
- multi-device и workspace ownership нельзя считать решёнными этим ADR;
- внешний агент должен поддерживать проверяемую Agent Identity и binding.

## Не входит в это решение

Этот ADR не определяет:

- каноническое владение workspace — см. SPATIAL-Q-002;
- границы пользовательских и дочерних Sessions — см. SPATIAL-Q-006;
- local trust boundary и mediated remote resources — см. [ADR-012](./ADR-012-local-trust-boundary-and-mediated-remote-resources.md);
- конкретные провайдеры, LLM, MCP SDK или формат prompt;
- экономическую политику и лимиты расходов.

## Критерии приёмки

Решение считается реализованным, когда:

- у Node есть ровно один канонический Primary Agent Slot;
- назначение и замена агента выполняются атомарно и журналируются;
- замена не удаляет workspace, sessions, артефакты или ledger state;
- capability grant хранится отдельно от Agent Identity и runtime binding;
- hooks доставляются активному агенту через policy/redaction;
- при отсутствии агента события сохраняются в durable inbox;
- UI представляет slot, а не жёстко зашитый тип модели;
- есть позитивные и отказоустойчивые тесты attach, detach, revoke и recovery.

## Связанные документы

- [Реестр открытых вопросов](./OPEN-QUESTIONS.md)
- [Общий план Spatial Agent Interface](./AiDN-Spatial-Agent-Interface-Implementation-Plan.md)
