# ADR-008 — Entity Uniqueness and Provenance References

**Статус:** Accepted  
**Дата решения:** 2026-09-04  
**Область:** Spatial Agent Interface, canonical entities, presentation instances, provenance  
**Связанный вопрос:** [SPATIAL-Q-008 — Канонический объект и его presentation instances](./OPEN-QUESTIONS.md#spatial-q-008--канонический-объект-и-его-presentation-instances)  
**Связанные решения:** [ADR-002 — Node Workspace Ownership](./ADR-002-node-workspace-ownership.md), [ADR-005 — Spatial Entity Topology](./ADR-005-spatial-entity-topology.md), [ADR-006 — Workspace Sessions and Context Graph](./ADR-006-workspace-sessions-context-graph.md), [ADR-007 — Spatial Memory, Aging and Clustering](./ADR-007-spatial-memory-aging-clustering.md)  
**Остающиеся зависимости:** [SPATIAL-Q-009 — Синхронизация между устройствами](./OPEN-QUESTIONS.md#spatial-q-009--синхронизация-между-устройствами), [SPATIAL-Q-011 — Экономическая прозрачность и управление бюджетом](./OPEN-QUESTIONS.md#spatial-q-011--экономическая-прозрачность-и-управление-бюджетом)  
**Исходный план:** [AiDN Spatial Agent Interface — Implementation Plan](./AiDN-Spatial-Agent-Interface-Implementation-Plan.md)

## Решение

Каждая semantic entity должна иметь одну основную spatial presence в рамках
одного Workspace. Endpoint остаётся Endpoint, Agent остаётся Agent, а Session
Artifact хранит interaction и references, но не клон участвовавшей сущности.

Дополнительное presentation-представление допускается только как явно
обозначенная projection, focus proxy или summary. Такая projection ссылается
на ту же canonical entity, не получает отдельную identity, ownership,
provenance, billing или lifecycle и не должна выглядеть как второй
самостоятельный объект.

Главные инварианты:

~~~text
ENTITY-INV-001
Одна semantic entity → одна primary spatial presence на Workspace.

ENTITY-INV-002
История взаимодействия хранит references и provenance, а не копии entity.

ENTITY-INV-003
Local Interaction Familiarity ≠ global reputation и ≠ authorization.
~~~

Это решение дополняет [ADR-005](./ADR-005-spatial-entity-topology.md):
Endpoint Arc и active Workspace используют одну и ту же Endpoint presence.
Оно также уточняет [ADR-006](./ADR-006-workspace-sessions-context-graph.md):
Context Graph может ссылаться на Endpoint, Agent или Service, но не
материализует их дубликаты.

## Термины и границы идентичности

- **Canonical entity** — authoritative semantic record с устойчивым
  идентификатором и revision.
- **Primary spatial presence** — основное представление canonical entity в
  конкретном Workspace. Оно может менять region, LOD и visual state, но не
  identity.
- **Context projection** — вторичное read-only представление той же entity,
  созданное для Conversation Surface, relation view или inspect.
- **Focus proxy** — временная геометрия, используемая камерой или
  Pull-to-Focus. Proxy не является entity и не сохраняется как её клон.
- **Provenance reference** — ссылка на entity и revision, через которую
  зафиксировано участие в операции.
- **Local Interaction Familiarity** — агрегированная история успешных и
  неуспешных взаимодействий конкретной Node или Primary Agent с entity.
- **Global reputation** — внешний или протокольный сигнал репутации,
  определяемый правилами сети. Он не выводится из одного Workspace.

Уникальность определяется ключом Workspace и canonical reference. Одна и та
же сущность может легально присутствовать в разных Workspace или Node
scopes; это разные presentation projections одного semantic record, а не
раздвоение identity.

## Primary Spatial Presence

Для пары workspace_id и canonical entity reference система должна
идемпотентно возвращать одну primary presence. Перемещение между preferred
regions, Endpoint Arc, Active Work и Deep Memory является изменением
presentation state этой presence.

~~~text
Endpoint EP-42
        │
        ▼
Primary Endpoint Presence
        │
        ├── Endpoint Arc
        ├── Active Workspace
        ├── Relation focus
        └── Deep Memory / LOD projection
~~~

Это один объект в semantic model, а не четыре копии. При переходе из
discovery в активное использование Layout Engine должен переиспользовать
presence и обновлять её zone или LOD.

Если компонент интерфейса не может показать primary presence в текущем
viewport, он может использовать relation anchor или focus proxy. Proxy должен
содержать canonical_ref и быть явно временным. Он не может получить новый
entity ID, отдельную цену или отдельную историю.

## Session Stores Interaction, Not Entity Copies

Session Artifact и Context Graph сохраняют interaction records, generated
artifacts, timestamps, context и provenance. Участие Endpoint фиксируется
ссылкой:

~~~text
Session Artifact
      ▣
      │
      ├── request
      ├── response
      └── provenance
              │
              └── Endpoint EP-42
~~~

Пример canonical interaction record:

~~~yaml
interaction_record:
  id:
  workspace_session_id:
  request_id:
  response_id:
  actor_ref:
  endpoint_ref:
    object_id:
    object_type: endpoint
    revision:
  relation: USED_ENDPOINT
  started_at:
  completed_at:
  outcome: success | failure | cancelled | timeout
  usage_ref:
  generated_object_refs:
    - object_id:
  provenance:
~~~

При раскрытии Session Artifact UI может показать compact provenance marker:

~~~text
request  ──→ ◇ EP-42
response ←── ◇ EP-42
~~~

Нажатие или focus этого marker должен подсветить primary Endpoint presence,
показать доступные metadata и при необходимости вызвать Pull-to-Focus из
[ADR-007](./ADR-007-spatial-memory-aging-clustering.md). Историческая запись
не становится вторым Endpoint object.

Session Artifact не должен:

- превращать Endpoint в собственный Session Artifact;
- переносить Endpoint в Session Cluster как новый object;
- копировать его цену, latency, capability или ownership в независимую
  authoritative запись;
- создавать новую AiDN Protocol Session только ради визуального отображения.

Контекстные данные могут содержать snapshot отдельных полей для аудита или
воспроизводимости, но snapshot должен быть маркирован как исторический
snapshot и не может использоваться как живой canonical entity без явной
revalidation.

## Context Projections и допустимые дубли представления

Вторичная projection разрешена только при наличии конкретной presentation
причины:

1. Conversation Surface показывает, через какой Endpoint выполнен request.
2. Relation view показывает связь Endpoint с Remote Agent.
3. Payment или usage view показывает provenance вызова.
4. Pull-to-Focus временно отображает offscreen entity рядом с текущим
   контекстом.
5. Cluster summary показывает aggregate membership без materialization всех
   членов.

Каждая projection MUST:

- содержать canonical_ref и revision;
- иметь presentation role и reason;
- быть read-only относительно identity, ownership и billing;
- ссылаться на primary presence или явно указывать её отсутствие;
- исчезать или схлопываться без удаления canonical entity;
- наследовать authorization и availability state canonical entity.

Projection MUST NOT:

- получать самостоятельный entity ID;
- менять canonical fields через drag, color или layout action;
- участвовать в оплате как отдельный Endpoint;
- порождать отдельный local familiarity counter;
- быть неотличимой от второго самостоятельного Agent или Endpoint.

Это позволяет сохранить пространственную выразительность, не жертвуя
уникальностью semantic model.

## Endpoint Interaction Memory

Endpoint может иметь локальную operational memory о взаимодействиях с текущей
Node и Primary Agent. Она относится к конкретному scope и не является
protocol reputation.

~~~yaml
endpoint_local_experience:
  endpoint_ref:
    object_id:
    revision:
  node_id:
  workspace_id:
  primary_agent_ref:
  interaction_count:
  successful_count:
  failed_count:
  cancelled_count:
  timeout_count:
  last_used_at:
  last_success_at:
  last_failure_at:
  familiarity: NEVER_USED | USED | TRUSTED_BY_HISTORY
  revision:
  provenance:
~~~

Familiarity является derived state:

- NEVER_USED — в текущем scope нет завершённого interaction;
- USED — был хотя бы один interaction, но история не даёт устойчивого
  positive signal;
- TRUSTED_BY_HISTORY — локальная история достигла policy threshold успешных
  взаимодействий и не содержит свежего unresolved failure.

Название TRUSTED_BY_HISTORY не означает security trust. Оно означает только
«известен по локальной истории». Это состояние не выдаёт capability, не
обходит approval, не меняет escrow и не заменяет revalidation.

Counters должны обновляться transactionally вместе с interaction result.
Повторная доставка одного event не должна удваивать счётчики; для этого
используется idempotency key или interaction revision.

## Визуальная семантика Familiarity

Endpoint сохраняет форму и semantic class, определённые [ADR-005](./ADR-005-spatial-entity-topology.md).
Interaction Familiarity показывается мягким вторичным сигналом:

~~~text
NEVER_USED
→ neutral compact energy field

USED
→ faint local inner glow

TRUSTED_BY_HISTORY
→ stable inner glow or slow orbital particle

currently active
→ stronger request/response halo

recent failure
→ restrained instability or warning trace
~~~

Галочка, изменение основной формы или яркий «зелёный» статус не должны быть
единственным representation: они легко путаются с global reputation или
availability. Inspect surface должен показывать понятный текст, например:

~~~text
Known by local history
16 successful / 17 total
Last success: 2026-09-04 12:10 UTC
Global reputation: separate signal
~~~

Local experience может участвовать в ranking Endpoint Arc вместе с
capability match, availability, latency, price и global reputation. При
этом ranking не может нарушать authorization, network policy, user budget
или явное решение оператора.

## Provenance и revision

Каждая ссылка на entity должна содержать как минимум object ID, object type и
revision. Для протокольной операции дополнительно сохраняются actor,
Workspace Session, operation ID и время.

Если canonical entity обновилась, историческая запись продолжает ссылаться
на использованную revision. Живой inspect показывает актуальное состояние и
сообщает о расхождении. Для спорных, оплачиваемых или security-sensitive
операций доступен immutable snapshot, но он остаётся evidence, а не новым
объектом.

Если entity удалена или отозвана:

- canonical record получает tombstone или unavailable state согласно policy;
- provenance references сохраняются;
- UI показывает причину недоступности и последнюю известную revision;
- новая projection не создаётся автоматически из старого snapshot;
- повторное использование требует discovery и revalidation.

Удаление presentation instance, collapse, aging или virtualization не должны
удалять provenance.

## Операции и API-контракт

Минимальный набор операций:

1. get_or_create_primary_presence(workspace_id, canonical_ref) — идемпотентно
   возвращает primary presence.
2. move_presence(presence_id, zone, layout_revision) — меняет только
   presentation state.
3. create_context_projection(canonical_ref, reason, source_ref) — создаёт
   временную read-only projection.
4. record_interaction(record) — записывает request/response и relation
   USED_ENDPOINT с idempotency key.
5. record_interaction_outcome(interaction_id, outcome) — атомарно обновляет
   provenance и local experience.
6. resolve_entity_reference(canonical_ref, requested_revision) — проверяет
   availability и authorization.
7. pull_to_focus(reference) — меняет camera или создаёт temporary proxy без
   изменения canonical position.

Операции presentation должны быть отделены от canonical mutation. Любое
изменение identity, ownership, capability, price или protocol state проходит
свой canonical command path.

## Инварианты

**ENTITY-INV-001 — Primary uniqueness**

Для одного workspace_id и canonical_ref существует не более одной primary
spatial presence. Повторное обнаружение не создаёт новый entity object.

**ENTITY-INV-002 — Reference over clone**

Historical interaction MUST представляться references, provenance и при
необходимости immutable snapshots, но не клоном canonical entity.

**ENTITY-INV-003 — Familiarity separation**

Local Interaction Familiarity MUST храниться отдельно от global reputation,
availability, authorization и capability grants.

**ENTITY-INV-004 — Projection non-authority**

Context projection и focus proxy не имеют собственной identity, ownership,
billing, escrow или самостоятельного lifecycle.

**ENTITY-INV-005 — Revision integrity**

Каждый provenance reference указывает на object ID и revision; обновление
живой entity не переписывает исторический результат.

**ENTITY-INV-006 — Focus non-mutation**

Highlight, Pull-to-Focus, camera movement и возвращение из Deep Memory не
изменяют semantic topology или canonical World Space position.

**ENTITY-INV-007 — Scope clarity**

Локальная история должна содержать node/workspace/agent scope, чтобы
результат одной Node не выдавался за глобальную репутацию сети.

**ENTITY-INV-008 — No implicit protocol effects**

Создание или удаление visual projection не создаёт, не закрывает и не
оплачивает AiDN Protocol Session.

## Реализационные слайсы

1. **Canonical reference registry.** Ввести уникальный ключ
   workspace_id + canonical_ref и идемпотентный primary presence lookup.
2. **Interaction provenance.** Добавить endpoint_ref, relation type,
   revision, outcome и idempotency в Workspace Session records.
3. **Projection layer.** Разделить primary presence, context projection,
   summary и focus proxy; запретить authoritative mutation из presentation.
4. **Local experience.** Ввести counters, familiarity policy и transactionally
   обновляемые interaction events.
5. **Endpoint UI.** Добавить provenance marker, inspect, local familiarity
   indicator и доступное текстовое описание.
6. **Focus integration.** Связать references с Endpoint Arc и Pull-to-Focus
   из [ADR-007](./ADR-007-spatial-memory-aging-clustering.md).
7. **Consistency tests.** Проверить повторный discovery, несколько sessions,
   stale revisions, удалённый Endpoint, duplicate events и несколько
   Workspace.

## Положительные последствия

- Workspace не захламляется визуальными копиями Endpoint, Agent и Service.
- История остаётся проверяемой и сохраняет provenance участвовавших сущностей.
- Один Endpoint можно одинаково показать в Arc, relation view и Session
  inspect без расхождения identity.
- Local interaction history помогает ranking, но не маскируется под
  глобальную репутацию или разрешение операции.
- Pull-to-Focus и spatial memory сохраняют выразительность без изменения
  canonical topology.

## Ограничения и риски

- Для живого inspect и исторических ссылок нужен revision-aware resolver.
- Secondary projections требуют явного lifecycle и очистки временных proxies.
- Familiarity policy нужно калибровать, чтобы единичный успех не создавал
  ложного ощущения надёжности.
- Синхронизация нескольких Workspace и конфликт presentation state остаются
  частью Q-009.
- Цена, usage и escrow не могут вычисляться из visual presence; правила
  экономики остаются частью Q-011 и протокола.

## Не входит в это решение

Этот ADR не определяет:

- глобальную reputation систему и её on-chain источник;
- network-wide discovery или canonical ownership policy;
- окончательный threshold для TRUSTED_BY_HISTORY;
- экономические правила endpoint pricing, escrow и billing;
- межустройственную синхронизацию layout и conflict resolution;
- конкретную БД, frontend framework, scene graph или animation library.

## Критерии приёмки

Решение считается реализованным, когда:

- повторный discovery одного Endpoint возвращает одну primary presence;
- Endpoint Arc, Active Workspace и Deep Memory переиспользуют canonical
  reference, а не создают semantic clones;
- Session Artifact хранит request, response и endpoint provenance reference;
- раскрытие provenance подсвечивает реальный Endpoint или безопасно сообщает
  unavailable/stale state;
- context projections и focus proxies имеют reason, revision и read-only
  semantics;
- local familiarity считается по Node/Workspace/Agent scope и не меняет
  global reputation или authorization;
- duplicate interaction events идемпотентны;
- старые revisions доступны как evidence без подмены живого объекта;
- удаление или collapse presentation не удаляет canonical history;
- layout, Pull-to-Focus и clustering не меняют identity или World Space;
- есть desktop, mobile, keyboard, screen-reader и reduced-motion сценарии;
- тесты покрывают Endpoint, Agent, Session и Payment Artifact references.

## Связанные документы

- [Реестр открытых вопросов](./OPEN-QUESTIONS.md)
- [ADR-002 — Node Workspace Ownership](./ADR-002-node-workspace-ownership.md)
- [ADR-005 — Spatial Entity Topology](./ADR-005-spatial-entity-topology.md)
- [ADR-006 — Workspace Sessions and Context Graph](./ADR-006-workspace-sessions-context-graph.md)
- [ADR-007 — Spatial Memory, Aging and Clustering](./ADR-007-spatial-memory-aging-clustering.md)
- [Общий план Spatial Agent Interface](./AiDN-Spatial-Agent-Interface-Implementation-Plan.md)
