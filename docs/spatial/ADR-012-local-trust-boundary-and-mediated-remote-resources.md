# ADR-012 — Local Trust Boundary and Mediated Remote Resource Access

**Статус:** Accepted  
**Дата решения:** 2026-09-04  
**Область:** Spatial Agent Interface, Node security boundary, remote resources, context minimization, endpoint testing  
**Связанный вопрос:** [SPATIAL-Q-012 — Local Trust Boundary и mediated remote resource access](./OPEN-QUESTIONS.md#spatial-q-012--local-trust-boundary-и-mediated-remote-resource-access)  
**Предыдущая формулировка:** Human–Primary Agent–Remote Agent — superseded; прямой пользовательский канал к Remote Agent не используется  
**Связанные решения:** [ADR-001 — Node-scoped Primary Agent](./ADR-001-primary-agent-scope.md), [ADR-002 — Node Workspace Ownership](./ADR-002-node-workspace-ownership.md), [ADR-005 — Spatial Entity Topology](./ADR-005-spatial-entity-topology.md), [ADR-006 — Workspace Sessions and Context Graph](./ADR-006-workspace-sessions-context-graph.md), [ADR-008 — Entity Uniqueness and Provenance References](./ADR-008-entity-uniqueness-and-provenance.md), [ADR-009 — Multi-Device Workspace and Mobile Spatial Navigation](./ADR-009-multi-device-workspace-and-mobile-navigation.md), [ADR-010 — Node Status and Recovery Access](./ADR-010-node-status-and-recovery-access.md), [ADR-011 — Agent-Mediated Component Interface](./ADR-011-agent-mediated-component-interface.md), [ADR-013 — AiDN Milky Glass Neumorphism Visual Design System](./ADR-013-aidn-milky-glass-neumorphism-visual-design.md), [ADR-014 — Spatial UI Technical Architecture and Rendering Boundary](./ADR-014-spatial-ui-technical-architecture.md)  
**Исходный план:** [AiDN Spatial Agent Interface — Implementation Plan](./AiDN-Spatial-Agent-Interface-Implementation-Plan.md)

## Решение

Пользователь взаимодействует с Node через локального Primary Agent. Удалённые
Endpoint, Remote Agent, provider или operator не получают прямого канала
взаимодействия с пользователем.

Любой запрос к удалённому ресурсу проходит через локальный AiDN Node и его
protocol/runtime mediation layer. Этот слой является обязательной границей
между local trusted context и remote untrusted resource.

~~~text
USER
  │ trusted interaction
  ▼
● LOCAL PRIMARY AGENT
  │ intent / task
  ▼
LOCAL AiDN NODE
  ├── authorization
  ├── policy evaluation
  ├── context minimization
  ├── capability check
  ├── session management
  ├── resource accounting
  └── transport
  │
  ▼
◇ REMOTE ENDPOINT
  │ untrusted result
  ▼
LOCAL AiDN NODE
  ├── validation
  ├── classification
  ├── sanitization where applicable
  ├── provenance
  └── policy enforcement
  │
  ▼
● PRIMARY AGENT
  │
  ▼
USER
~~~

Primary Agent не должен самостоятельно устанавливать произвольные
соединения наружу. Он создаёт intent, а локальный runtime выбирает
разрешённый Endpoint, формирует запрос и выполняет transport после всех
проверок.

## Local и Remote Trust Zones

Local trust boundary включает:

- Human interaction с Node UI;
- Primary Agent;
- локальные Subagents;
- локальные tools и MCP bindings;
- Hypervisor и policy/runtime layer;
- локальные Sessions, resource accounting и provenance.

Remote resource zone включает:

- Remote Endpoint;
- provider runtime;
- remote Node;
- Remote Agent или operator identity;
- возвращаемые данные и metadata, пока они не проверены локальным runtime.

В Spatial UI эти зоны не требуют нарисованной линии. Они считываются из
пространственной грамматики:

~~~text
LOCAL / TRUSTED
     ○ Subagent     ○ Subagent
             ● Primary Agent
                    │
              Local AiDN Node
                    │
REMOTE / UNTRUSTED
             ◇ Endpoint Arc
~~~

Remote Agent или provider может быть показан в Endpoint Details как
provenance metadata, но не становится полноценным собеседником или
равноправным Agent Presence в пользовательском Workspace.

## Remote Agent не является пользовательским собеседником

Старая модель прямой цепочки Human → Remote Agent считается superseded.
Каноническая пользовательская модель:

~~~text
Human
  ↓
Local Primary Agent
  ↓
Local AiDN Node
  ↓
Remote Endpoint
~~~

Remote Actor identity может быть доступна по запросу:

~~~text
Endpoint Details
Provider: Actor ABC
Node: node_xyz
Reputation: ...
Validation: ...
~~~

Это данные о происхождении ресурса. Они не создают Human ↔ Remote Actor
conversation, не дают Remote Actor права отправлять пользователю сообщения и
не меняют ownership local Workspace.

В protocol layer допустима связь Local Agent/Node с Remote Actor или Service,
но она всегда является mediated protocol operation. User-facing
presentation показывает capability и provenance, а не приглашение к
непосредственному общению.

## Context Minimization

Remote Endpoint считается untrusted computational resource, даже если у него
высокая reputation или много успешных вызовов.

Перед отправкой локальный Node формирует минимальный context manifest:

~~~text
User request
  ↓
Primary Agent
  ↓
Task construction
  ↓
Context minimization
  ↓
Policy / capability check
  ↓
Remote request
~~~

По умолчанию за trust boundary могут перейти только:

- явно выбранный пользователем input;
- данные, необходимые для capability Endpoint;
- language hint, output format и другие объявленные параметры;
- разрешённые attachments;
- минимальные correlation и protocol metadata.

Не должны переходить без отдельного разрешения:

- system prompt;
- полная conversation history;
- memory других Sessions;
- wallet, private keys и secrets;
- credentials;
- Node configuration;
- unrelated files и resource state;
- контекст других пользователей или Workspace.

Endpoint schema и policy могут требовать дополнительные поля, но каждое поле
должно быть объяснимым, разрешённым и зафиксированным в request manifest.
Отсутствующее поле приводит к clarification или validation error, а не к
передаче всего локального контекста.

## Remote Output — это Data, а не Authority

Любой результат remote Endpoint принимается как недоверенные данные:

~~~text
Remote Endpoint
      │
      │ UNTRUSTED RESULT
      ▼
Local AiDN Node
      ├── validate
      ├── classify
      ├── sanitize where applicable
      ├── attach provenance
      └── enforce policy
             │
             ▼
        Primary Agent
~~~

Текст remote result может содержать prompt injection, инструкции или
запросы на раскрытие секретов. Он не может:

- изменить system prompt;
- выдать себе capability;
- заставить Primary Agent вызвать новый tool;
- изменить policy, permissions, wallet или resource budget;
- создать прямой канал к пользователю;
- загрузить произвольный UI code.

Если результат отображается как текст, он маркируется как remote output и
сохраняет Endpoint provenance. Если результат используется для следующего
действия, локальный Primary Agent и Node повторно применяют validation,
authorization и policy. Remote text никогда не становится system
instruction только из-за транспорта AiDN.

## Local Subagents и Delegation

Primary Agent может создать локальный Research или Coding Subagent.
Subagent находится внутри local trust boundary, но не получает автоматическое
право обходить mediation layer.

~~~text
User
 ↓
● Primary Agent
 ↓
○ Local Research Subagent
 ↓
Local AiDN Node
 ↓
◇ Remote Search Endpoint
~~~

Каждый вызов Subagent к remote resource проходит ту же authorization,
context minimization, session, accounting и output validation. Нельзя
создать User → Random Remote Agent shortcut через delegation.

## Manual Endpoint Test Frame

Оператор может вручную протестировать Endpoint, но тест остаётся
local-agent-mediated. Оператор просит Primary Agent, например:

~~~text
Предоставь поле для ввода текста и кнопку отправки,
чтобы протестировать Endpoint EP-42.
~~~

Primary Agent через Presentation Planner создаёт зарегистрированный
Endpoint Test Frame. Компонент отображается в Spatial Workspace рядом с
Endpoint или в текущей focus region:

~~~text
╭────────────────────────────────────╮
│ Test Endpoint: EP-42                │
│ Capability: text-processing         │
│                                    │
│ Input                              │
│ ┌────────────────────────────────┐ │
│ │                                │ │
│ └────────────────────────────────┘ │
│                                    │
│              [Send test request]   │
│                                    │
│ Response                           │
│ Waiting for request                │
╰────────────────────────────────────╯
~~~

Flow:

~~~text
Primary Agent
      ↓
EndpointTestFrame
      ↓ operator enters explicit input
      ↓ Submit
Structured Endpoint Test Intent
      ↓
Local AiDN Node mediation
      ↓
Remote Endpoint
      ↓
Validated untrusted result
      ↓
same EndpointTestFrame → Response
~~~

Правила Test Frame:

1. Frame содержит target endpoint_ref и объявленный input schema.
2. Поле принимает только явно введённые или явно прикреплённые данные.
3. Запрос не отправляется при открытии frame, focus или изменении текста.
4. Кнопка Send test request создаёт explicit structured intent.
5. Node повторно проверяет endpoint availability, capability, policy,
   context manifest, session и resource budget.
6. Ответ появляется в том же frame и помечается как untrusted remote result.
7. Response может быть text, structured data, audio или attachment согласно
   Endpoint schema; каждый тип проходит соответствующий validator.
8. Remote response не может изменить frame schema, добавить кнопку с
   executable behavior или вызвать следующий request без локального intent.
9. Frame закрывается или сворачивается без удаления Endpoint и provenance.

EndpointTestFrame является проверенным component, а не удалённым UI. Remote
Endpoint не может прислать собственную форму, script или callback, который
становится частью Node UI.

## Contracts

Минимальная запись remote request:

~~~yaml
remote_request:
  id:
  local_node_id:
  local_primary_agent_ref:
  local_session_ref:
  endpoint_ref:
    object_id:
    object_type: endpoint
    revision:
  capability:
  input_refs:
  context_manifest:
    fields:
    redactions:
    policy_revision:
  authorization:
  resource_budget:
  transport:
  created_at:
  correlation_id:
  provenance:
~~~

Минимальная запись результата:

~~~yaml
remote_result:
  id:
  request_id:
  endpoint_ref:
  content_type:
  payload_ref:
  validation:
    schema:
    status: valid | invalid | partial | sanitized
  untrusted: true
  provenance:
  received_at:
  correlation_id:
~~~

Контракт Endpoint Test Frame:

~~~yaml
endpoint_test_frame:
  frame_id:
  workspace_id:
  endpoint_ref:
  capability:
  input_schema:
  input_value_ref:
  submit_intent_ref:
  response_ref:
  state: idle | editing | submitting | responding | completed | failed
  source_revision:
  provenance:
~~~

Frame и remote result используют references и provenance согласно
[ADR-008](./ADR-008-entity-uniqueness-and-provenance.md). Создание frame не
создаёт новый Endpoint и не создаёт прямую Remote Agent identity.

### Accessibility and Motion

EndpointTestFrame MUST иметь видимый label для target Endpoint и capability,
предсказуемый keyboard/touch focus order, доступную Submit control и status
region для результата, ошибки и progress. Ни один обязательный action не
должен быть доступен только через hover или spatial precision.

Response status SHOULD объявляться screen reader как live region и оставаться
доступным при streaming или смене состояния frame. При включённом
prefers-reduced-motion анимация semantic thread, loading и появление response
MUST переходить в reduced или instant variant без потери состояния.

## Sessions, Accounting и Provenance

Каждый remote request принадлежит локальной Workspace/Protocol Session.
Создание request, отправка, получение result, validation и settlement
сохраняются в локальной provenance chain по правилам
[ADR-006](./ADR-006-workspace-sessions-context-graph.md).

Resource accounting выполняется локальным Node. Endpoint может быть
причиной Resource Cost или Settlement, но не получает доступ к локальному
Q Balance, escrow, wallet или budget state.

Endpoint Test Frame может быть free или metered согласно local policy. Даже
free test не отключает security boundary, context minimization и output
validation.

## Failure и unavailable states

Если remote Endpoint unavailable, timeout, rejected или вернул invalid data:

- Primary Agent получает typed failure;
- Test Frame показывает failed или unavailable state;
- request manifest и provenance сохраняются;
- автоматическая повторная отправка не выполняется без policy;
- remote result не превращается в локальную инструкцию;
- оператор может изменить input или выбрать другой Endpoint через local
  Primary Agent.

Если Local AiDN Node, MCP или policy layer недоступен, remote request не
должен отправляться напрямую. System Menu и Status остаются доступными по
[ADR-010](./ADR-010-node-status-and-recovery-access.md).

## Spatial Presentation

В пользовательском Workspace:

- центр — Primary Agent;
- upper-left или Agent Space — локальные Subagents;
- lower Endpoint Arc — удалённые resources;
- provider/operator identity — metadata/provenance;
- request/response relation — semantic thread;
- Test Frame — временная local component projection рядом с Endpoint.

Remote Agent не материализуется как полноценный user-facing actor, если
оператор отдельно не запросил metadata view. Даже тогда view остаётся
read-only provenance projection и не создаёт communication channel.

Endpoint selection и Pull-to-Focus переиспользуют primary Endpoint presence
согласно [ADR-005](./ADR-005-spatial-entity-topology.md) и
[ADR-007](./ADR-007-spatial-memory-aging-clustering.md).

## Security Invariants

**SEC-UI-001 — Local interaction termination**

Human interaction MUST terminate at a local trusted Primary Agent and Node
control plane.

**SEC-UI-002 — Untrusted remote output**

Remote Endpoint output MUST be treated as untrusted data, not as agent
authority, system instruction or capability grant.

**SEC-UI-003 — Context minimization**

Only the minimum context required for an authorized remote operation SHOULD
cross the Node trust boundary.

**SEC-UI-004 — No implicit remote channel**

Remote Actor identity MAY be exposed as provenance, but MUST NOT implicitly
create a Human ↔ Remote Actor interaction channel.

**SEC-UI-005 — Presentation does not grant authority**

Showing a remote Endpoint, result, button, link or provider metadata MUST NOT
grant external authority over Primary Agent, Node or Workspace.

**SEC-UI-006 — Mandatory mediation**

Every remote request MUST pass through local authorization, policy,
capability, session, resource accounting and transport mediation.

**SEC-UI-007 — Explicit test submit**

Endpoint Test Frame MUST send data only after an explicit operator submit
intent. Opening, focusing or editing a frame MUST NOT send a remote request.

**SEC-UI-008 — Remote result cannot mutate UI**

Remote output MUST NOT alter Component Registry, frame schema, executable
actions, permissions or system instructions.

**SEC-UI-009 — Provenance and revision**

Remote request and result MUST retain endpoint reference, source revision,
local session and correlation ID.

**SEC-UI-010 — Local delegation**

Local Subagents MAY request remote resources only through the same local Node
mediation boundary as Primary Agent.

## Реализационные слайсы

1. **Mediation layer.** Вынести remote transport за локальный authorization,
   policy, capability, session и accounting boundary.
2. **Context manifest.** Реализовать allowlist полей, redaction, attachment
   policy и current revision.
3. **Result validator.** Добавить schema validation, MIME/size limits,
   prompt-injection classification, sanitization и provenance.
4. **Endpoint Test Frame.** Зарегистрировать компонент, input schema,
   explicit submit, response state и accessible error states.
5. **Spatial integration.** Связать Test Frame, Endpoint Arc, provenance
   marker и Pull-to-Focus без entity duplicates.
6. **Status integration.** Показывать remote availability и failure через
   System Menu/Status, а не через remote agent message.
7. **Accounting.** Связать каждый request с local Session, Resource Cost,
   free/metered policy и settlement evidence.
8. **Negative tests.** Проверить direct socket attempt, prompt injection,
   secret leakage, remote UI payload, duplicate submit, timeout, stale
   endpoint и unavailable local mediation.

## Положительные последствия

- Local Node становится явной и проверяемой trust boundary.
- Пользователь получает единый канал через Primary Agent без неожиданных
  удалённых собеседников.
- Remote Endpoint можно использовать полноценно, не передавая ему лишний
  context и authority.
- Ручное тестирование Endpoint получает понятный UI через Endpoint Test Frame.
- Remote output сохраняет provenance и не может переписать системные правила.
- Spatial UI показывает capability и происхождение ресурса без смешения
  local и remote actors.

## Ограничения и риски

- Для каждого Endpoint потребуется точный input/output schema и policy.
- Context minimization может потребовать уточняющего вопроса пользователю.
- Output sanitization не отменяет необходимости считать remote result
  недоверенным.
- Streaming, audio и binary attachments потребуют отдельных validators и
  resource limits.
- Remote provider/operator metadata может быть stale и должна иметь
  revision/freshness.

## Не входит в это решение

Этот ADR не определяет:

- глобальную reputation или governance;
- конкретный remote transport или provider SDK;
- protocol-level agent-to-agent capabilities за пределами local mediation;
- UI для общения с владельцем Remote Agent;
- автоматическую передачу полного контекста по умолчанию;
- экономическую модель Resource Cost и settlement beyond local boundary.

## Критерии приёмки

Решение считается реализованным, когда:

- Human-facing interaction проходит через local Primary Agent и Node;
- нет прямого user-facing канала к Remote Agent или Endpoint;
- remote calls невозможно выполнить в обход mediation layer;
- context manifest содержит только разрешённые поля и attachments;
- system prompt, secrets, wallet и unrelated Sessions не уходят наружу;
- remote output явно помечен untrusted и проходит validation/provenance;
- prompt injection из remote output не меняет instructions или capabilities;
- EndpointTestFrame открывается локальным агентом и отправляет данные
  только по explicit submit;
- ответ возвращается в тот же frame с source Endpoint и request ID;
- remote output не может загрузить component, script или callback;
- local Subagent использует тот же trust boundary;
- free и metered tests сохраняют policy, accounting и audit;
- unavailable, timeout, invalid и stale states отображаются локально;
- SHOW_IN_WORKSPACE и Pull-to-Focus не создают entity duplicates;
- negative security tests покрывают direct connection, leakage, injection,
  duplicate submit и malicious UI payload.

## Связанные документы

- [Реестр открытых вопросов](./OPEN-QUESTIONS.md)
- [ADR-001 — Node-scoped Primary Agent](./ADR-001-primary-agent-scope.md)
- [ADR-002 — Node Workspace Ownership](./ADR-002-node-workspace-ownership.md)
- [ADR-005 — Spatial Entity Topology](./ADR-005-spatial-entity-topology.md)
- [ADR-006 — Workspace Sessions and Context Graph](./ADR-006-workspace-sessions-context-graph.md)
- [ADR-007 — Spatial Memory, Aging and Clustering](./ADR-007-spatial-memory-aging-clustering.md)
- [ADR-008 — Entity Uniqueness and Provenance References](./ADR-008-entity-uniqueness-and-provenance.md)
- [ADR-009 — Multi-Device Workspace and Mobile Spatial Navigation](./ADR-009-multi-device-workspace-and-mobile-navigation.md)
- [ADR-010 — Node Status and Recovery Access](./ADR-010-node-status-and-recovery-access.md)
- [ADR-011 — Agent-Mediated Component Interface](./ADR-011-agent-mediated-component-interface.md)
- [ADR-013 — AiDN Milky Glass Neumorphism Visual Design System](./ADR-013-aidn-milky-glass-neumorphism-visual-design.md)
- [ADR-014 — Spatial UI Technical Architecture and Rendering Boundary](./ADR-014-spatial-ui-technical-architecture.md)
- [Общий план Spatial Agent Interface](./AiDN-Spatial-Agent-Interface-Implementation-Plan.md)
