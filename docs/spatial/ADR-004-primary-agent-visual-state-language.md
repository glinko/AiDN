# ADR-004 — Primary Agent Visual State Language

**Статус:** Accepted  
**Дата решения:** 2026-09-03  
**Область:** Spatial Agent Interface, visual semantics, accessibility, motion  
**Связанный вопрос:** [SPATIAL-Q-004 — Видимость состояний действия](./OPEN-QUESTIONS.md#spatial-q-004--видимость-состояний-действия)  
**Связанные решения:** [ADR-001 — Node-scoped Primary Agent](./ADR-001-primary-agent-scope.md), [ADR-002 — Node Workspace Ownership](./ADR-002-node-workspace-ownership.md), [ADR-003 — Orbital Attention System](./ADR-003-orbital-attention-system.md), [ADR-013 — AiDN Milky Glass Neumorphism Visual Design System](./ADR-013-aidn-milky-glass-neumorphism-visual-design.md)  
**Исходный план:** [AiDN Spatial Agent Interface — Implementation Plan](./AiDN-Spatial-Agent-Interface-Implementation-Plan.md)

## Решение

Primary Agent Presence должен визуально отражать текущее operational state
агента. Для этого используется многоканальный visual state language, а не
один фиксированный цвет или подпись статуса.

Семантика состояния фиксируется системой. Способ визуального отображения
является настраиваемым mapping и может использовать цвет, яркость, глубину,
прозрачность, glow, pulse, scale, halo, cloud occlusion и характер движения.

Визуальное состояние является проекцией operational state и не заменяет
канонические runtime events, action lifecycle или audit trail.

## Канонические состояния

Минимальный набор состояний Primary Agent:

| Состояние | Семантика |
|---|---|
| READY | агент доступен для взаимодействия и не выполняет активную работу |
| THINKING | агент обрабатывает запрос или строит план |
| ACTING | агент выполняет внешнее действие, например MCP/tool operation |
| ATTENTION | у агента есть важная информация для оператора |
| CRITICAL | обнаружена критическая проблема Node, безопасности или данных |
| OFFLINE | backend агента недоступен, но сам slot и Workspace существуют |

Реализация может отображать THINKING и ACTING общим состоянием WORKING, если
раздельная визуализация не улучшает понимание. Архитектура должна сохранять
возможность различать их позднее.

Состояния action lifecycle остаются отдельной канонической моделью. Например:

~~~text
planning / awaiting approval → THINKING или ATTENTION
executing                  → ACTING
completed                  → READY + completed attention marker
failed                     → ATTENTION или CRITICAL + attention marker
~~~

Точное отображение зависит от severity и policy. Нельзя считать факт изменения
анимации подтверждением завершения операции.

## Visual Channels

### Color and hue

Цвет является одним из каналов:

~~~text
READY     → neutral / white / soft blue
THINKING  → violet / purple
ACTING    → blue / cyan / green
ATTENTION → amber
CRITICAL  → red или другой critical tone
OFFLINE   → desaturated gray
~~~

Конкретные значения должны быть configurable и не могут быть единственным
сигналом. В темах с высокой контрастностью или для пользователей с
цветовыми нарушениями применяются дополнительные формы, яркость, glyph и
текстовая accessibility label.

### Brightness, opacity and glow

Brightness отражает уровень активности, а не severity сам по себе:

~~~text
idle       → soft glow
active     → brighter glow
critical   → strong localized glow
offline    → minimal brightness
~~~

Glow и opacity должны изменяться плавно и не создавать ложного эффекта
непрерывной ошибки.

### Scale and pulse

Primary Agent Presence может мягко изменять apparent size:

~~~text
READY      → stable scale
THINKING   → subtle breathing pulse
ACTING     → slightly increased presence
OFFLINE    → reduced apparent volume
~~~

Pulse может использовать brightness, scale, halo и internal glow:

~~~text
THINKING  → slow deep pulse
ACTING    → moderately faster pulse
ATTENTION → periodic accent pulse
CRITICAL  → stronger urgent pulse
~~~

Масштаб и амплитуда должны иметь верхний предел. Визуальное присутствие не
должно прыгать, нарушать layout или вызывать motion sickness. При включённом
prefers-reduced-motion анимации заменяются статичными или минимальными
переходами.

### Depth and Cloud Occlusion

Cloud Space является полноценным semantic channel:

~~~text
FOREGROUND       → READY / direct interaction
MID DEPTH        → processing / working
BACKGROUND       → temporarily unavailable for direct interaction
CLOUD OCCLUDED   → deeply busy, detached or unavailable
~~~

Рекомендуемая пространственная интерпретация:

~~~text
READY     → агент перед облаками
THINKING  → агент частично внутри облаков
WORKING   → агент глубже в облаках
OFFLINE   → серый неподвижный объект внутри тумана
ATTENTION → агент визуально ближе, с тёплым halo
~~~

Глубина не должна скрывать агента полностью. Даже в OFFLINE оператор должен
понимать, что Primary Agent существует, но временно недоступен.

## Состояние OFFLINE

Если backend Primary Agent недоступен, Presence должен перейти в OFFLINE:

~~~text
color    → desaturated gray
brightness → minimal
pulse    → none
halo     → almost absent
depth    → slightly distant
motion   → none
~~~

OFFLINE не является ошибкой приложения и не должен скрывать Node Workspace,
System Menu или recovery operations. Индикация доступности Node и доступности
Primary Agent должна оставаться различимой.

## Композиция visual state

Visual state строится из независимых слоёв:

~~~text
Base Operational State
        +
Attention State
        +
Connectivity State
        +
Interaction State
~~~

Слои не должны полностью перекрашивать или заменять друг друга. Например:

~~~text
THINKING
+ CRITICAL ATTENTION
+ CONNECTED

→ purple body
→ red orbital attention marker
→ normal network halo
~~~

Таким образом, тело Presence показывает текущую operational activity, а
[Orbital Attention System](./ADR-003-orbital-attention-system.md) показывает
накопленные события, решения и информацию для оператора.

Ключевой инвариант:

~~~text
Primary Agent Presence = current operational state
Orbital Attention System = pending information / events / decisions
~~~

## Настройка визуального mapping

Семантика состояний не изменяется пользователем, но visual mapping может быть
настроен через System Menu:

~~~text
System Menu
└── Appearance
    └── Primary Agent
        ├── State Colors
        ├── Brightness
        ├── Pulse
        ├── Scale Animation
        ├── Cloud Depth
        ├── Motion Intensity
        └── Accessibility
~~~

Пример профиля:

~~~yaml
agent_visual_state:
  THINKING:
    color: purple
    brightness: 0.65
    pulse:
      enabled: true
      period_ms: 2400
      scale_amplitude: 0.04
    depth: background
    cloud_occlusion: 0.35
~~~

Пользователь может назначить THINKING зелёным или ACTING синим, но не может
переименовать CRITICAL в «всё нормально» или отключить обязательный
non-color-сигнал для критических состояний.

Предустановленные темы:

- Default;
- Calm;
- High Contrast;
- Minimal Motion;
- Color Blind Safe;
- Custom.

Профиль должен версионироваться, валидироваться и иметь безопасный fallback.
Настройки визуального mapping не изменяют Node State, Agent Capability Grant,
Workspace Semantic State или экономические policy.

## Accessibility и взаимодействие

Для каждого состояния должны существовать:

- текстовая accessibility label;
- non-color различие;
- поддержка клавиатурного и screen-reader focus;
- режим reduced motion;
- режим High Contrast;
- предсказуемый порядок объявлений при смене состояния.

Пульсация, глубина и cloud occlusion не должны быть единственным способом
понять, что требуется действие оператора. ACTION_REQUIRED и CRITICAL должны
иметь явное текстовое описание и доступный control path.

Visual state не должен блокировать ручной доступ к Node Workspace, System Menu
или recovery mode.

## Производительность и устойчивость

- Переходы выполняются через composited properties, не меняя координаты
  semantic объектов Workspace.
- Состояние Presence должно обновляться по подтверждённым state events, а не
  по частоте сетевых пакетов или внутренним токенам модели.
- При пропуске или дублировании события итоговое состояние восстанавливается
  из канонического Node/Agent read model.
- Анимация должна деградировать до статичного представления без потери
  семантики.
- Visual mapping не должен приводить к бесконечным перерисовкам или росту
  количества объектов на canvas.

## Последствия

### Положительные

- богатый и расширяемый язык состояний без жёсткой привязки к цветам;
- совместимость с Orbital Attention System;
- чёткое разделение текущей активности и накопленного внимания;
- поддержка пользовательских тем и accessibility;
- сохранение роли Primary Agent как живого центрального присутствия Node.

### Ограничения

- потребуется единый набор motion tokens и state transition tokens;
- нужно валидировать пользовательские visual profiles;
- потребуется тестирование на мобильных экранах, reduced motion и high contrast;
- разделение THINKING/ACTING остаётся опциональным UX-решением;
- visual state не заменяет action state machine и audit events.

## Не входит в это решение

Этот ADR не определяет:

- семантику Primary Agent и ownership Node — см. [ADR-001](./ADR-001-primary-agent-scope.md);
- ownership и persistence Workspace — см. [ADR-002](./ADR-002-node-workspace-ownership.md);
- lifecycle Orbital Attention Markers — см. [ADR-003](./ADR-003-orbital-attention-system.md);
- конкретные frontend framework или animation library; material tokens,
  typography и surface profiles определены в [ADR-013](./ADR-013-aidn-milky-glass-neumorphism-visual-design.md);
- полный набор capability policy и recovery permissions.

## Критерии приёмки

Решение считается реализованным, когда:

- Primary Agent отображает READY, THINKING, ACTING/WORKING, ATTENTION, CRITICAL
  и OFFLINE;
- для состояния используются минимум два независимых visual channel;
- цвет не является единственным сигналом;
- OFFLINE сохраняет доступ к Workspace и System Menu;
- visual mapping можно сменить без изменения state semantics;
- Base Operational State и Orbital Attention State отображаются независимо;
- focus/reduced-motion/high-contrast режимы сохраняют смысл состояния;
- visual state не меняет World Space coordinates и canonical protocol records;
- есть тесты переходов, конфликтующих слоёв, отказа backend и восстановления.

## Связанные документы

- [Реестр открытых вопросов](./OPEN-QUESTIONS.md)
- [ADR-001 — Node-scoped Primary Agent](./ADR-001-primary-agent-scope.md)
- [ADR-002 — Node Workspace Ownership](./ADR-002-node-workspace-ownership.md)
- [ADR-003 — Orbital Attention System](./ADR-003-orbital-attention-system.md)
- [ADR-013 — AiDN Milky Glass Neumorphism Visual Design System](./ADR-013-aidn-milky-glass-neumorphism-visual-design.md)
- [Общий план Spatial Agent Interface](./AiDN-Spatial-Agent-Interface-Implementation-Plan.md)
