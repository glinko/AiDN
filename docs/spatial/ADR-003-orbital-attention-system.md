# ADR-003 — Orbital Attention System

**Статус:** Accepted  
**Дата решения:** 2026-09-03  
**Область:** Spatial Agent Interface, autonomous activity, notifications, focus navigation  
**Связанный вопрос:** [SPATIAL-Q-003 — Автономные действия и проактивность](./OPEN-QUESTIONS.md#spatial-q-003--автономные-действия-и-проактивность)  
**Связанные решения:** [ADR-001 — Node-scoped Primary Agent](./ADR-001-primary-agent-scope.md), [ADR-002 — Node Workspace Ownership](./ADR-002-node-workspace-ownership.md)  
**Исходный план:** [AiDN Spatial Agent Interface — Implementation Plan](./AiDN-Spatial-Agent-Interface-Implementation-Plan.md)

## Решение

Автономная работа Primary Agent не должна автоматически перемещать камеру,
раскрывать интерфейс или заполнять Workspace большим количеством объектов.
Результаты автономной активности сначала классифицируются как элементы
внимания и помещаются в компактную очередь внимания.

В Spatial UI эта очередь представляется через Orbital Attention Markers,
вращающиеся вокруг Primary Agent. Marker является presentation instance, а не
самостоятельной protocol entity.

Каноническая цепочка:

~~~text
Autonomous Activity
        ↓
Primary Agent
        ↓
Attention Item
        ↓
Orbital Attention Marker
        ↓
Operator focus
~~~

Орбита показывает наличие незакрытых элементов внимания, но не заменяет
историю, Session, Payment или другой канонический объект.

## Термины и разделение сущностей

### Attention Item

Каноническая семантическая запись о результате, событии или требовании,
которое может потребовать внимания оператора. Attention Item связывается с
источником события, Node, Primary Agent и, если применимо, Session, Task,
Endpoint или Payment Artifact.

### Orbital Attention Marker

Компактное визуальное представление Attention Item в текущем viewport. Marker
может вращаться, менять интенсивность и переходить в focus mode, но не является
самостоятельной сущностью протокола.

### Workspace Artifact

Постоянное пространственное представление раскрытого или сохранённого
семантического объекта: Task Result, Conversation Surface, Image Viewer,
Report Object, Diagnostic Object, Remote Agent Session Object или Economic
Object.

Куб, точка или другая форма — это только визуальная оболочка. Тип данных
определяется semantic reference и canonical object.

## Основные инварианты

- Автономное событие не должно самопроизвольно менять положение камеры.
- Незакрытое внимание должно быть заметно без открытия отдельной страницы.
- Критические элементы не должны скрываться за агрегированным маркером.
- Цвет не является единственным способом передачи состояния.
- Скрытие marker не удаляет каноническую историю, ledger record, payment,
  evidence или системное событие.
- Пространственные координаты объектов не изменяются из-за focus translation.
- Orbital markers представляют текущую очередь внимания, а не persistent
  history.

## Жизненный цикл внимания

~~~text
CREATED
    ↓
ORBITING_UNREAD
    ↓
SELECTED
    ↓
FOCUSED
    ↓
RESOLVED
~~~

Дополнительные переходы:

~~~text
ORBITING_UNREAD → AGGREGATED
ORBITING_UNREAD → DISMISSED
FOCUSED         → ACTION_REQUIRED
FOCUSED         → ARCHIVED
~~~

### Состояния

- CREATED — Attention Item создан и прошёл policy/redaction.
- ORBITING_UNREAD — элемент представлен marker и ещё не просмотрен.
- AGGREGATED — элемент входит в группу, но остаётся доступным для раскрытия.
- SELECTED — оператор выбрал marker.
- FOCUSED — связанный semantic object раскрыт, а камера переведена в focus.
- ACTION_REQUIRED — требуется решение или действие оператора.
- RESOLVED — внимание закрыто; marker исчезает или преобразуется в Workspace
  Artifact.
- DISMISSED — marker убран из активной очереди, исходные данные сохранены.
- ARCHIVED — объект сохранён в историческом представлении.

Переходы должны быть идемпотентными, журналироваться и связываться с event
ID и workspace revision.

## Классификация важности

Используются следующие уровни:

| Уровень | Назначение | Поведение |
|---|---|---|
| INFORMATION | справочное событие | спокойный marker, без навязчивого сигнала |
| COMPLETED | успешно завершённая работа | marker доступен до просмотра или агрегации |
| ATTENTION | важная информация | amber-состояние и повышенный приоритет в орбите |
| ACTION_REQUIRED | требуется решение оператора | persistent marker, явное действие |
| CRITICAL | серьёзная ошибка Node, безопасности или данных | отдельный marker, немедленное отображение, нельзя агрегировать с low priority |

Интенсивность, частота пульсации и форма не должны создавать ложное ощущение
срочности. Для каждого уровня должны быть текстовая метка и доступный
non-color сигнал.

## Модель данных

Минимальная запись Attention Item:

~~~yaml
attention_item:
  id:
  node_id:
  workspace_id:
  source_agent:
  source_event_id:
  type:
  severity:
  status:
  unread:
  created_at:
  updated_at:
  semantic_ref:
  session_ref:
  preview:
  payload_ref:
  required_action:
  aggregation_key:
  provenance:
~~~

Orbital Marker хранит только presentation state:

~~~yaml
orbital_marker:
  id:
  attention_ref:
  orbit:
    lane:
    radius:
    phase:
    angular_velocity:
  severity:
  unread:
  presentation_state:
~~~

Attention Item и Orbital Marker должны иметь разные идентификаторы. Удаление
marker не удаляет Attention Item.

## Орбитальная компоновка

Каждый marker получает orbital slot вокруг Primary Agent. Рекомендуются
несколько невидимых или визуально ненавязчивых lanes:

~~~text
Inner Orbit  → ACTION_REQUIRED / CRITICAL
Middle Orbit → COMPLETED / responses
Outer Orbit  → INFORMATION / low priority
~~~

Орбиты должны двигаться медленно. Анимация отражает наличие внимания, а не
сетевой трафик и не скорость обработки модели. При hover или focus marker может
замедляться или останавливаться.

Семантическое кодирование отделяется от состояния:

~~~text
shape / glyph → semantic type
color / pulse  → status and severity
~~~

Например, одинаковый glyph Task может быть спокойным зелёным после успешного
завершения, жёлтым при ожидании решения или красным при критическом сбое.

## Ограничение количества и агрегация

Одновременно отображается ограниченное число индивидуальных markers:

~~~text
recommended visible markers: 5–8
~~~

Остальные элементы агрегируются по severity, type, recency и semantic
relation. Примеры агрегатов:

- 3 completed tasks;
- 2 warnings;
- 7 updates;
- 12 more.

Раскрытие агрегата показывает состав группы и позволяет выбрать отдельный
Attention Item. INFORMATION и COMPLETED можно агрегировать свободнее.
ACTION_REQUIRED и CRITICAL должны сохранять отдельное, явно заметное
представление.

Агрегация не изменяет provenance и не объединяет канонические операции в одну
протокольную сущность.

## Активация и Focus Mode

При выборе marker выполняется последовательность:

~~~text
ORBITING_UNREAD
        ↓
SELECTED
        ↓
DETACHING
        ↓
EXPANDING
        ↓
FOCUS_TRANSLATION
        ↓
FOCUSED
~~~

Marker временно отсоединяется от орбиты, semantic object раскрывается, а камера
переводит его в центр viewport.

### Camera-first правило

Workspace использует две системы координат:

~~~text
World Space
    │
    ▼
Viewport / Camera Transform
    │
    ▼
Screen Space
~~~

Focus Translation изменяет только viewport transform. Позиции Primary Agent,
marker и связанных объектов в World Space сохраняются:

~~~text
НЕ: изменять координаты всех объектов Workspace

ДА: изменить viewport.camera, чтобы выбранный объект оказался в центре
~~~

Во время focus mode:

- Primary Agent остаётся видимым, если позволяет размер экрана;
- semantic threads до агента сохраняются;
- несвязанные объекты могут быть приглушены;
- фоновая анимация продолжается с меньшей интенсивностью;
- орбита остальных markers может быть временно замедлена.

Semantic thread должна показывать происхождение информации от Primary Agent или
другого источника, даже когда объект раскрыт.

## Выход из Focus Mode

Focus mode завершается при закрытии, dismiss, archive, выполнении требуемого
действия или возврате к агенту:

~~~text
FOCUSED
    ↓
COLLAPSING / DISMISSING
    ↓
RESTORE_VIEWPORT
    ↓
CENTER_ON_PRIMARY_AGENT
~~~

До перевода камеры сохраняется focus context:

~~~yaml
focus_context:
  previous_viewport:
    x:
    y:
    zoom:
  focused_object:
~~~

Восстановление может использовать сохранённый viewport либо команду
CENTER_ON_PRIMARY_AGENT. World Space при этом не изменяется.

## Действия оператора

Базовые действия для Attention Item:

- Open;
- Expand;
- Move;
- Pin;
- Group;
- Inspect Relation;
- Dismiss;
- Hide;
- Archive.

В зависимости от semantic object также могут быть доступны:

- Approve;
- Reject;
- Retry;
- Delegate;
- Reply;
- Complete.

Доступность действий определяется типом объекта, статусом и capability policy.
Сам marker не получает полномочий автоматически.

### Dismiss, Hide, Archive и Delete

Эти операции имеют разные семантики:

| Операция | Результат |
|---|---|
| Dismiss | убрать из активной очереди внимания; сохранить историю |
| Hide | убрать из текущего presentation; сохранить semantic object |
| Archive | переместить в историческое представление; сохранить provenance |
| Delete | удалить underlying data только если это разрешено его canonical policy |

Dismiss или Hide не должны удалять protocol history, Session history, ledger
record, payment, evidence или system event.

## Автономные события и доставка

Перед созданием Attention Item события проходят policy и redaction. События,
созданные при отсутствии Primary Agent, сохраняются в durable inbox согласно
[ADR-001](./ADR-001-primary-agent-scope.md). При подключении агента доставка
непрочитанных элементов выполняется по policy, а не автоматически для каждого
события.

Оператор должен видеть происхождение Attention Item и связь с Node, агентом,
Session или Task. Повторная доставка и повторное открытие должны быть
идемпотентными.

## Consequences

### Положительные

- автономная работа заметна, но не захватывает интерфейс;
- Primary Agent становится визуальным центром накопленного внимания Node;
- пространство не загрязняется десятками временных объектов;
- focus mode сохраняет контекст и provenance;
- семантические данные отделены от визуальной анимации;
- разные типы объектов используют единый attention-механизм.

### Ограничения

- потребуется Attention Item store и lifecycle state machine;
- потребуется policy агрегации и лимит orbital capacity;
- focus camera должна быть отделена от semantic layout;
- доступность и non-color сигналы требуют отдельного UX-тестирования;
- постоянная история остаётся в Workspace и не может быть заменена одной
  орбитой.

## Не входит в это решение

Этот ADR не определяет:

- ownership Workspace — см. [ADR-002](./ADR-002-node-workspace-ownership.md);
- семантику Primary Agent — см. [ADR-001](./ADR-001-primary-agent-scope.md);
- границы Session и billing;
- конкретный движок анимаций или frontend framework;
- окончательные цвета, glyph set и motion tokens;
- политику хранения и удаления канонических данных.

## Критерии приёмки

Решение считается реализованным, когда:

- автономное событие создаёт Attention Item через policy/redaction;
- unread Attention Items отображаются через Orbital Markers;
- одновременно видимо не более рекомендованного числа individual markers;
- low-priority элементы агрегируются, а CRITICAL не скрывается;
- marker не является protocol entity и имеет отдельную semantic reference;
- marker selection переводит объект в focus mode без изменения World Space;
- semantic thread сохраняет происхождение объекта;
- Dismiss, Hide, Archive и Delete имеют разное проверяемое поведение;
- при отсутствии агента события сохраняются в durable inbox;
- есть тесты lifecycle, агрегации, focus translation, восстановления viewport и
  отказа Primary Agent.

## Связанные документы

- [Реестр открытых вопросов](./OPEN-QUESTIONS.md)
- [ADR-001 — Node-scoped Primary Agent](./ADR-001-primary-agent-scope.md)
- [ADR-002 — Node Workspace Ownership](./ADR-002-node-workspace-ownership.md)
- [Общий план Spatial Agent Interface](./AiDN-Spatial-Agent-Interface-Implementation-Plan.md)
