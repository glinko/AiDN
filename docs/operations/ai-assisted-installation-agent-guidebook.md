# Гайдбук агента: AI-assisted установка модели

Этот протокол описывает единственный путь для запроса вида «установи модель»,
«подними endpoint» или «раскатай Bundle». JSON-план является канонической
записью намерения ноды, а Spatial frame — его редактируемым представлением.
Агент не должен заменять frame вопросами в свободном тексте.

## Контракт результата

Агент должен довести запрос до одного из двух результатов:

1. показать оператору заполненный опросник и ждать подтверждения;
2. после подтверждения последовательно выполнить разрешённые стадии и
   показать подтверждённый результат или точную причину остановки.

Любая стадия остаётся отдельной MCP-операцией. Создание плана не скачивает
модель, не устанавливает Provider, не останавливает runtime и не публикует
Endpoint.

## Алгоритм агента

### 1. Разобрать запрос

Определи, что именно просит оператор: Provider, модель, источник артефакта,
создание Bundle, запуск private Endpoint или публикацию. Разреши точные
идентификаторы через MCP (`aidn.provider.list`, `aidn.model.list` и связанные
read-инструменты). Если Provider, модель или конкретный `HTTPS`/`hf://`
источник отсутствует либо неоднозначен, задай один короткий уточняющий вопрос.
Нельзя угадывать URL, ревизию или размер модели.

### 2. Создать внутренний план

Вызови `aidn.steward.installation_prepare` в режиме `plan`, затем в режиме
`apply` для записи intent-only плана, если MCP-сеанс разрешает эту операцию.
Для ревизии существующего плана передай его текущий `expected_plan_hash`.
План должен содержать рекомендуемые значения:

- контекст `131072 → 65536 → 32768`;
- `max_tokens`, GPU layers, KV-cache и concurrency;
- политику замены текущего runtime;
- visibility, бесплатный/платный режим и тариф;
- обязательность validation и разрешение внешних запросов без allowlist;
- действие после Bundle: `draft` или `start`.

Без явного ответа оператора значения `ask` не являются разрешением.

### 3. Выпустить опросник в frame

После сохранения плана вызови:

```text
aidn.ui.read({request_id, kind: "installation"})
aidn.ui.present({
  request_id,
  document: {
    document_id,
    title: "Установка модели",
    blocks: [
      {type: "text", text: "Проверьте рекомендации перед установкой."},
      {type: "fields", source_id, title: "Параметры установки"}
    ]
  }
})
```

`aidn.ui.read(kind="installation")` возвращает только зарегистрированные
поля. Используй их `value`, `editable`, `description`, `minimum`, `maximum` и
`options`; не придумывай свои значения и не вставляй HTML/скрипты.
План может хранить `ask` как нерешённое состояние, но frame показывает для
него безопасную рекомендацию (`private`, `free`, `required`, `deny`, `parallel`).
Если оператор оставляет рекомендацию и отмечает подтверждение, именно она
становится явным ответом и записывается в новую ревизию плана.

Frame содержит следующие группы полей:

| Группа | Поля | Вид по умолчанию |
| --- | --- | --- |
| Модель | provider, model id, source, endpoint action | выбранные агентом значения |
| Ресурсы | requested context, fallback 64K/32K, on exhausted, max tokens, GPU layers, KV-cache, concurrency | 128K → 64K → 32K, `auto` где возможно |
| Замена | mode, allow stop current | `ask` / `ask` |
| Публикация | visibility, pricing, validation, external requests, endpoint name | `ask`, validation `ask`, external `ask` |
| Тариф | kind, dimension, unit price, divisor, minimum charge | metered/request_count, цена `0` до выбора paid |
| Подтверждение | `workflow.confirm_installation` | `false` |

Последнее поле — единственный сигнал «раскатывать». Не считай сообщение
«да», отдельную реплику или изменение поля разрешением на установку.

### 4. Принять форму

Когда UI передаст `intent_id`, выполни ровно:

1. `aidn.ui.apply` с `mode=plan`;
2. `aidn.ui.apply` с тем же `intent_id` и `request_id`, используя возвращённый
   MCP `plan_hash`;
3. после успешного read-back заново опубликуй источник через
   `aidn.ui.present` с тем же `document_id`.

Поля `current` и `proposed` должны передаваться без подмены. Конфликт ревизии,
ошибка валидации или отсутствие scope останавливают процесс и оставляют draft
видимым.

Если результат содержит `installation_confirmed=true`, переходи к следующей
стадии. Если флаг false, это только сохранённая правка плана — жди следующего
подтверждения.

### 5. Раскатать Bundle по state machine

Для текущего `installation_plan_hash` вызывай
`aidn.steward.installation_apply` только с `action`, который вернул
`aidn.steward.installation_workflow`:

```text
prepare_review
apply_provider_installation
request_model_install
process_model_install
create_bundle
create_private_endpoint
forecast_private_endpoint
start_private_endpoint
```

После каждой операции перечитай `aidn.steward.installation_workflow`. Не
перепрыгивай через стадию и не повторяй уже успешную операцию с новым
idempotency key.

## Ресурсная политика

Перед регистрацией Bundle Hypervisor прогнозирует каждую конфигурацию в
порядке 128K, 64K, 32K. Если Resource Broker отклонил все варианты, не создавай
Bundle и покажи `shortfall`, `attempted_context_lengths` и
`ask_for_smaller_runtime_configuration`. Если есть активный runtime, переход
`replace` допускается только при `allow_stop_current=allow` и отдельном MCP
approval. Иначе верни `ask_replace_current_runtime` или предложи parallel.

## Тариф и публикация

`pricing=free` удаляет тариф. Для `paid` требуется положительная цена и
заполненные поля тарифа; при неполных данных выпусти обновлённый frame с
вопросом о тарифе. Создание private Endpoint и публичная публикация — разные
операции. Даже при `visibility=public` не публикуй Endpoint как побочный эффект
создания Bundle: сначала нужна validation, затем отдельная политика и approval.

## Безопасность и идемпотентность

- JSON-план owner-readable (`0600`) и не содержит секретов, ключей или токенов.
- Не используй shell, прямой HTTP к ноде или чтение файлов вместо MCP.
- На каждой ревизии требуй текущий `expected_plan_hash`.
- Для каждого MCP plan/apply используй новый idempotency key, но сохраняй
  request correlation там, где это требует инструмент.
- Не утверждай успех без результата инструмента и подтверждённого read-back.
- При approval, conflict, `RESOURCE_WAIT`, ошибке загрузки или нехватке места
  остановись на текущем шаге и сообщи оператору следующую допустимую операцию.

## Короткая фраза для оператора

«Я подготовил рекомендуемые параметры установки. Они открыты в frame и
редактируемы. Установка начнётся только после отметки “Подтвердить установку и
раскатку Bundle”; до этого нода не скачивает модель и не останавливает текущий
runtime».
