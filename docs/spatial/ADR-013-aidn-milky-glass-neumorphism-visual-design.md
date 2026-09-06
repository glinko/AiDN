# ADR-013 — AiDN Milky Glass Neumorphism Visual Design System

**Статус:** Accepted  
**Дата решения:** 2026-09-04  
**Область:** Spatial Agent Interface, visual design, design tokens, component surfaces, accessibility, motion  
**Объём:** Материальная и типографическая система; расположение объектов и навигация в этот документ не входят  
**Связанные решения:** [ADR-003 — Orbital Attention System](./ADR-003-orbital-attention-system.md), [ADR-004 — Primary Agent Visual State Language](./ADR-004-primary-agent-visual-state-language.md), [ADR-005 — Spatial Entity Topology](./ADR-005-spatial-entity-topology.md), [ADR-011 — Agent-Mediated Component Interface](./ADR-011-agent-mediated-component-interface.md), [ADR-012 — Local Trust Boundary and Mediated Remote Resource Access](./ADR-012-local-trust-boundary-and-mediated-remote-resources.md), [ADR-014 — Spatial UI Technical Architecture and Rendering Boundary](./ADR-014-spatial-ui-technical-architecture.md)  
**Исходный план:** [AiDN Spatial Agent Interface — Implementation Plan](./AiDN-Spatial-Agent-Interface-Implementation-Plan.md)  
**Текущий общий reference:** [DESIGN.md](../../DESIGN.md)

## Решение

Для Spatial Agent Interface принимается визуальная система **AiDN Milky
Glass Neumorphism**. Это гибрид молочно-белого frosted glass, мягкого
neumorphic relief и холодных spectral reflections.

Спецификация описывает, как любой компонент выглядит и реагирует, независимо
от того, где он находится: в Spatial Workspace, в Endpoint Test Frame, в
System Menu или в Classic UI. Она не задаёт координаты, preferred regions,
порядок меню, topology или semantic role объектов.

Канонический принцип:

~~~text
almost-white environment
        +
milky translucent surface
        +
soft top-left highlight
        +
soft bottom-right shadow
        +
restrained spectral accent
        =
AiDN Milky Glass Neumorphism
~~~

Операционная семантика, authority и фактические состояния остаются
каноническими по [ADR-004](./ADR-004-primary-agent-visual-state-language.md),
[ADR-011](./ADR-011-agent-mediated-component-interface.md) и
[ADR-012](./ADR-012-local-trust-boundary-and-mediated-remote-resources.md).
Стиль не выдаёт capability, не меняет permission и не заменяет текстовую
индикацию состояния.

Эта спецификация является целевой материальной системой для нового Spatial
UI и новых переиспользуемых компонентов. Существующий dashboard не должен
молчаливо переключаться на неё в рамках одного изменения: миграция Classic
UI выполняется отдельным срезом с визуальной проверкой и сохранением
операционной читаемости.

## Материальная грамматика

### Поверхность вместо границы

Компонент отделяется от среды комбинацией:

- небольшой разницы тона и opacity;
- внутреннего белого highlight;
- мягкой внешней тени;
- backdrop blur;
- очень слабого spectral reflection.

Тяжёлая серая рамка не является базовым способом разделения. Граница
допустима только как тонкий accessibility и focus cue, а не как декоративный
контур.

### Единый источник света

Вся система предполагает мягкий свет сверху-слева и спереди:

- highlight и inset light приходят сверху-слева;
- тень уходит вниз-вправо;
- pressed/inset states меняют глубину, но не направление света;
- один компонент не должен использовать противоположную физику без явной
  причины.

### Иерархия глубины

Визуальная глубина выбирается по operational role:

| Уровень | Материальная роль | Примеры |
| --- | --- | --- |
| 0 | Environment: матовый почти белый фон | workspace canvas, пустая область |
| 1 | Subtle control: лёгкий relief | secondary control, compact selector |
| 2 | Working surface: молочное стекло | information frame, form, conversation |
| 3 | Focused surface: усиленный edge light и depth | выбранный объект, modal focus, active test frame |
| 4 | 3D entity: продолжение material language в WebGL | Primary Agent, Endpoint, Session Artifact |

Нельзя делать каждый элемент Level 3 или Level 4. Повышенная глубина должна
сигнализировать фокус или самостоятельную 3D-сущность.

## Design tokens

### Цветовая база

Canvas не должен быть чистым белым. Основной фон — холодный off-white,
поверхности — прозрачные молочные слои.

~~~css
:root {
  --aidn-bg-0: #fbfcfe;
  --aidn-bg-1: #f6f8fb;
  --aidn-bg-2: #eef2f6;

  --aidn-surface: rgba(249, 251, 254, 0.68);
  --aidn-surface-soft: rgba(250, 252, 255, 0.48);
  --aidn-surface-strong: rgba(248, 250, 253, 0.82);
  --aidn-glass-border: rgba(255, 255, 255, 0.82);

  --aidn-text: #223553;
  --aidn-text-secondary: #73839d;
  --aidn-text-muted: #a1aec1;

  --aidn-blue: #7ea8ee;
  --aidn-blue-soft: #dce8fb;
  --aidn-violet: #b9b9f4;
  --aidn-cyan: #b9def4;
  --aidn-peach: #f1d2bb;

  --aidn-state-ready: #6aa987;
  --aidn-state-attention: #c38d55;
  --aidn-state-critical: #c87883;
  --aidn-state-offline: #8e99a8;
}
~~~

90–95% площади интерфейса должны оставаться нейтральными. Blue, violet,
cyan, peach и state colors используются как inner glow, reflection, status
channel или action accent, а не как сплошная заливка больших surfaces.

Цвет никогда не является единственным сигналом. Состояния должны иметь
label, icon, shape, brightness, motion или текстовое объяснение согласно
[ADR-004](./ADR-004-primary-agent-visual-state-language.md).

### Тени

Тень состоит из нескольких очень мягких слоёв. Не следует заменять их одной
тёмной drop-shadow.

~~~css
:root {
  --aidn-shadow-float:
    0 24px 60px rgba(70, 88, 115, 0.09),
    0 8px 24px rgba(70, 88, 115, 0.055);

  --aidn-shadow-soft:
    0 10px 28px rgba(73, 92, 120, 0.07),
    0 2px 8px rgba(73, 92, 120, 0.035);

  --aidn-shadow-neumorphic:
    10px 10px 24px rgba(167, 177, 194, 0.12),
    -10px -10px 24px rgba(255, 255, 255, 0.92);

  --aidn-shadow-inset:
    inset 4px 4px 12px rgba(158, 170, 189, 0.10),
    inset -4px -4px 12px rgba(255, 255, 255, 0.88);
}
~~~

Тени не должны использоваться для имитации ошибки, статуса или authority.
Смысл состояния задаётся [ADR-004](./ADR-004-primary-agent-visual-state-language.md),
а elevation только помогает прочитать hierarchy.

### Радиусы и blur

~~~css
:root {
  --aidn-radius-sm: 12px;
  --aidn-radius-md: 18px;
  --aidn-radius-lg: 28px;
  --aidn-radius-xl: 36px;
  --aidn-radius-pill: 999px;

  --aidn-blur-sm: blur(10px);
  --aidn-blur-md: blur(18px);
  --aidn-blur-lg: blur(26px);
}
~~~

Рекомендации: small control — 12–18px; input — 18px; frame — 24–30px;
large surface — 28–36px; pill — 999px. Tooltip и compact control используют
small blur, рабочая surface — medium, крупное glass — large.

При отсутствии backdrop-filter компонент должен сохранять opaque fallback и
читаемость.

### Motion

~~~css
:root {
  --aidn-ease: cubic-bezier(.22, .8, .25, 1);
  --aidn-duration-fast: 160ms;
  --aidn-duration-normal: 220ms;
  --aidn-duration-enter: 280ms;
}
~~~

Motion должна ощущаться как небольшая масса поверхности: короткий lift,
мягкое появление, отсутствие резких скачков. Expensive blur, bloom и
continuous animation ограничиваются viewport и состоянием объекта.

## Surface primitives

### Основная glass surface

~~~css
.aidn-surface {
  background:
    linear-gradient(
      145deg,
      rgba(255, 255, 255, 0.74),
      rgba(244, 247, 251, 0.52)
    );
  border: 1px solid var(--aidn-glass-border);
  box-shadow:
    var(--aidn-shadow-float),
    inset 0 1px 0 rgba(255, 255, 255, 0.95),
    inset 0 -1px 0 rgba(167, 181, 203, 0.06);
  backdrop-filter: var(--aidn-blur-lg) saturate(115%);
  -webkit-backdrop-filter: var(--aidn-blur-lg) saturate(115%);
  border-radius: var(--aidn-radius-lg);
}
~~~

Используется для information frames, configuration surfaces, status views,
conversation frames и temporary tool surfaces.

### Лёгкое стекло

~~~css
.aidn-surface--light {
  background: rgba(255, 255, 255, 0.36);
  border: 1px solid rgba(255, 255, 255, 0.62);
  box-shadow:
    0 10px 35px rgba(88, 104, 128, 0.055),
    inset 0 1px 0 rgba(255, 255, 255, 0.88);
  backdrop-filter: var(--aidn-blur-md);
  -webkit-backdrop-filter: var(--aidn-blur-md);
}
~~~

Используется для secondary controls, compact selectors, tooltips и
маленьких floating menus. Слишком прозрачный элемент не должен скрывать
label или focus ring.

### Raised и pressed controls

~~~css
.aidn-control {
  border: 0;
  background:
    linear-gradient(
      145deg,
      rgba(255, 255, 255, 0.88),
      rgba(239, 243, 248, 0.72)
    );
  box-shadow:
    7px 7px 18px rgba(167, 177, 194, 0.14),
    -7px -7px 18px rgba(255, 255, 255, 0.92),
    inset 0 1px 0 rgba(255, 255, 255, 0.92);
  color: var(--aidn-text);
  border-radius: var(--aidn-radius-pill);
  transition:
    transform var(--aidn-duration-fast) var(--aidn-ease),
    box-shadow var(--aidn-duration-normal) var(--aidn-ease),
    background var(--aidn-duration-normal) ease;
}

.aidn-control:hover {
  transform: translateY(-1px);
  box-shadow:
    9px 9px 22px rgba(160, 172, 192, 0.16),
    -9px -9px 22px rgba(255, 255, 255, 0.96);
}

.aidn-control:active,
.aidn-control[aria-pressed="true"] {
  transform: translateY(0);
  background: rgba(241, 245, 249, 0.72);
  box-shadow:
    inset 5px 5px 12px rgba(170, 180, 196, 0.16),
    inset -5px -5px 12px rgba(255, 255, 255, 0.86);
}
~~~

Pressed state слегка уводит control внутрь поверхности. Движение не должно
изменять layout или создавать ощущение потери focus.

### Inset input

~~~css
.aidn-input {
  background: rgba(244, 247, 250, 0.52);
  border: 1px solid rgba(255, 255, 255, 0.64);
  border-radius: var(--aidn-radius-md);
  box-shadow: var(--aidn-shadow-inset);
  color: var(--aidn-text);
  outline: none;
}

.aidn-input:focus-visible {
  box-shadow:
    var(--aidn-shadow-inset),
    0 0 0 3px rgba(126, 168, 238, 0.22);
}
~~~

Input выглядит утопленным, но focus-visible обязан оставаться различимым
при keyboard и assistive navigation.

### Accent и iridescent layers

Цветные эффекты применяются малыми областями:

~~~css
.aidn-accent-glow {
  box-shadow:
    0 16px 40px rgba(84, 110, 148, 0.08),
    0 0 30px rgba(142, 177, 238, 0.08),
    inset 0 1px 0 rgba(255, 255, 255, 0.94);
}

.aidn-iridescent {
  background:
    radial-gradient(
      circle at 25% 15%,
      rgba(182, 207, 255, 0.18),
      transparent 38%
    ),
    radial-gradient(
      circle at 78% 82%,
      rgba(238, 205, 191, 0.12),
      transparent 42%
    ),
    rgba(250, 252, 255, 0.58);
}
~~~

Нельзя использовать постоянный neon glow, крупную насыщенную заливку или
разные направления spectral light в соседних компонентах.

## Surface API и Component Registry

Presentation Planner не должен знать CSS, shadow values или конкретную
animation library. Он выбирает семантический surface profile, а renderer
применяет tokens.

~~~typescript
type SurfaceDepth = "flat" | "raised" | "floating" | "inset";
type GlassLevel = "none" | "soft" | "medium" | "strong";
type SurfaceRadius = "small" | "medium" | "large" | "pill";
type SurfaceAccent =
  | "neutral"
  | "blue"
  | "violet"
  | "cyan"
  | "amber"
  | "critical";

interface AiDNSurfaceStyle {
  depth: SurfaceDepth;
  glass: GlassLevel;
  accent: SurfaceAccent;
  radius: SurfaceRadius;
  emphasis: "secondary" | "normal" | "primary";
}
~~~

Пример declarative mapping:

~~~tsx
<Surface
  depth="floating"
  glass="medium"
  radius="large"
  accent="neutral"
>
  <EndpointStatus />
</Surface>
~~~

или:

~~~html
<div
  class="aidn-surface"
  data-depth="floating"
  data-glass="medium"
  data-accent="blue"
></div>
~~~

Registry связывает material profile с компонентами:

| Component role | Default profile | Примечание |
| --- | --- | --- |
| information frame | floating / medium / large | читаемый рабочий контекст |
| compact selector | raised / soft / medium | не конкурирует с primary action |
| editable field | inset / soft / medium | focus-visible обязателен |
| EndpointTestFrame | floating / medium / large | response и failure видимы в том же frame |
| tooltip | raised / soft / medium | не используется как единственный источник инструкции |
| critical notice | floating / medium / large + critical accent | текст и icon обязательны |
| 3D entity | material profile Level 4 | renderer-specific, semantic mapping общий |

Добавление нового material profile проходит через registry change и visual
review, а не через локальную самодеятельность компонента.

## Typography

### Основной текст

Базовая гарнитура — Inter с Geist и system-ui fallback:

~~~css
:root {
  --aidn-font-sans: Inter, Geist, ui-sans-serif, system-ui, -apple-system,
    BlinkMacSystemFont, "Segoe UI", sans-serif;
  --aidn-font-mono: "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo,
    Consolas, monospace;
}
~~~

Основной текст — холодный slate/navy, не чистый black:

- primary: #223553;
- secondary: #73839d;
- muted: #a1aec1.

Mono используется для hash, runtime, chain ID, port и других exact
technical values, а не как декоративная типографика. Заголовки и body copy
не должны выглядеть как терминал.

### Иерархия

- display — название workspace или выбранного объекта;
- body — объяснение, consequence и operator guidance;
- label — короткие uppercase роли с умеренным tracking;
- mono — только машинные идентификаторы и точные значения.

Минимальный контраст обычного текста — не ниже WCAG AA 4.5:1; крупного
текста — не ниже 3:1. Muted text нельзя использовать для единственного
значимого сообщения.

## Иконки и состояния

Иконки — outline с округлыми окончаниями и stroke примерно 1.5–1.8px;
Lucide является допустимым базовым набором.

Icon, color, text и shape работают совместно. Например, critical notice
использует label и icon даже при наличии красного accent; OFFLINE не
сообщается только низкой brightness. Канонические state semantics и
independent visual layers описаны в
[ADR-004](./ADR-004-primary-agent-visual-state-language.md), а внимание
событий — в [ADR-003](./ADR-003-orbital-attention-system.md).

## Interaction и motion

### Hover, focus и pressed

Hover является оптическим:

- lift не больше 1px;
- brightness изменение минимальное;
- shadow слегка усиливается;
- layout и hit target не меняются.

Keyboard focus и touch focus должны иметь явный, контрастный indicator.
Hover-only metadata не может быть единственным способом узнать состояние
или выполнить действие.

### Enter и reveal

~~~css
@keyframes aidn-surface-enter {
  from {
    opacity: 0;
    transform: translateY(8px) scale(.985);
    filter: blur(4px);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
    filter: blur(0);
  }
}

.aidn-surface-enter {
  animation: aidn-surface-enter var(--aidn-duration-enter) var(--aidn-ease);
}
~~~

Opening, response reveal и semantic thread pulse должны быть короткими и
причинно связанными с событием. Нельзя превращать streaming или обычную
telemetry в непрерывную гирлянду.

### Reduced motion

~~~css
@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    animation-duration: 1ms !important;
    animation-iteration-count: 1 !important;
    scroll-behavior: auto !important;
    transition-duration: 1ms !important;
  }
}
~~~

Reduced-motion variant сохраняет state, focus, progress и relation direction,
но убирает постоянный pulse, camera flight и декоративный parallax.

## DOM и 3D continuity

Three.js-сущности должны выглядеть продолжением DOM material language:

~~~javascript
new THREE.MeshPhysicalMaterial({
  color: 0xf7faff,
  roughness: 0.18,
  metalness: 0.02,
  transmission: 0.72,
  thickness: 0.8,
  transparent: true,
  opacity: 0.82,
  ior: 1.35
});
~~~

Разрешены environment reflections, subtle bloom, cool edge lighting и
barely-visible spectral tint. 3D renderer не должен вводить отдельную
цветовую систему, конфликтующую с CSS tokens.

DOM fallback и 3D presentation обязаны сохранять одну semantic identity:

~~~text
DOM surface
      ↕ same tokens / state semantics
Three.js material
~~~

## Accessibility, responsive и performance

- Body и primary labels соблюдают WCAG AA contrast.
- Status не передаётся только цветом, glow, opacity или motion.
- Все controls доступны клавиатурой и touch; target не должен требовать
  точного попадания в визуальный пиксель.
- Focus-visible остаётся различимым поверх glass и при high-contrast mode.
- Screen reader получает название компонента, target, state и error/result
  через обычный DOM и live-region semantics.
- Для mobile сохраняются touch targets и читаемая hierarchy; style не
  зависит от ширины viewport.
- Backdrop blur имеет opaque fallback.
- Дорогие blur, bloom и 3D effects ограничены активным viewport и не
  применяются бездумно к длинным спискам.
- При virtualized history визуальный слой не меняет canonical object,
  provenance или state.

## Что категорически запрещено

- чистый #fff на #fff без tonal separation;
- тяжёлые серые borders и один жёсткий drop-shadow;
- яркая сплошная заливка как единственный статус;
- постоянный neon glow или чрезмерная saturation;
- одинаковая translucent depth у всех компонентов;
- мелкий или low-contrast текст ради визуальной «чистоты»;
- arbitrary component-specific shadow и radius values;
- hover-only action, label или error;
- motion, которая ломает reduced-motion или увеличивает layout;
- передача CSS, arbitrary JavaScript или 3D material values из LLM;
- использование surface appearance как доказательства authority,
  validation или успешного protocol operation.

## Style invariants

**STYLE-001 — Placement independence**  
Style system MUST работать одинаково для любого semantic object и не
предполагать его spatial location.

**STYLE-002 — Token ownership**  
Surface, color, type, radius, shadow и motion values MUST приходить из
versioned token system или registry profile.

**STYLE-003 — Neutral majority**  
Большинство интерфейса MUST оставаться нейтральным; accent не должен
превращаться в заливку всей поверхности.

**STYLE-004 — Semantic separation**  
Style MUST NOT менять authority, state semantics, permission, provenance или
protocol truth.

**STYLE-005 — Non-color status**  
Важное состояние MUST иметь хотя бы один независимый текстовый, icon,
shape, layout или motion signal.

**STYLE-006 — Accessible interaction**  
Focus, keyboard, touch, contrast, screen-reader и reduced-motion paths MUST
сохранять функциональность и смысл.

**STYLE-007 — DOM/3D continuity**  
DOM и 3D renderers MUST использовать согласованные material profiles и state
semantics.

**STYLE-008 — Bounded effects**  
Blur, bloom, shadow и continuous animation MUST иметь performance budget и
не ухудшать читаемость или scrolling.

## Реализационные срезы

1. **Token package.** Вынести colors, shadows, radii, blur, typography и
   motion tokens в versioned package.
2. **Surface primitive.** Реализовать единый Surface API с depth, glass,
   accent, radius и emphasis.
3. **Registry mapping.** Привязать существующие shared components и
   EndpointTestFrame к material profiles из
   [ADR-011](./ADR-011-agent-mediated-component-interface.md).
4. **State integration.** Соединить accent layers с visual state language
   [ADR-004](./ADR-004-primary-agent-visual-state-language.md), не меняя
   state semantics.
5. **DOM/3D bridge.** Согласовать CSS renderer и Three.js material profiles.
6. **Accessibility pass.** Проверить contrast, focus, touch, screen-reader,
   high-contrast и reduced-motion paths.
7. **Performance pass.** Проверить blur/bloom budgets, mobile fallback,
   virtualized lists и scrolling.
8. **Migration slices.** Переносить Classic и Spatial surfaces по одной,
   визуально сверяя результат и не смешивая старую и новую material grammar
   внутри одного компонента.

## Критерии приёмки

Спецификация считается внедрённой на конкретной surface, когда:

- все surfaces используют tokenized profiles;
- placement и component semantics не зашиты в material primitive;
- background и surfaces визуально читаются без тяжёлых границ;
- controls имеют raised/pressed/inset states;
- focus-visible, contrast и status labels проверены;
- цвет не является единственным operational signal;
- reduced-motion variant сохраняет state и action feedback;
- unsupported backdrop-filter получает читаемый fallback;
- EndpointTestFrame, status, error и response states сохраняют одну
  материальную грамматику;
- DOM и 3D representation одного объекта визуально согласованы;
- shadow, blur, bloom и animation проходят bounded performance check;
- no arbitrary style values и no arbitrary UI code проходят registry review;
- visual regression проверен на desktop и mobile viewport;
- [ADR-004](./ADR-004-primary-agent-visual-state-language.md),
  [ADR-011](./ADR-011-agent-mediated-component-interface.md) и
  [ADR-012](./ADR-012-local-trust-boundary-and-mediated-remote-resources.md)
  остаются непротиворечивыми.

## Связанные документы

- [Реестр открытых вопросов](./OPEN-QUESTIONS.md)
- [ADR-003 — Orbital Attention System](./ADR-003-orbital-attention-system.md)
- [ADR-004 — Primary Agent Visual State Language](./ADR-004-primary-agent-visual-state-language.md)
- [ADR-005 — Spatial Entity Topology](./ADR-005-spatial-entity-topology.md)
- [ADR-011 — Agent-Mediated Component Interface](./ADR-011-agent-mediated-component-interface.md)
- [ADR-012 — Local Trust Boundary and Mediated Remote Resource Access](./ADR-012-local-trust-boundary-and-mediated-remote-resources.md)
- [ADR-014 — Spatial UI Technical Architecture and Rendering Boundary](./ADR-014-spatial-ui-technical-architecture.md)
- [AiDN Spatial Agent Interface — Implementation Plan](./AiDN-Spatial-Agent-Interface-Implementation-Plan.md)
- [Общая design-система Hypervisor](../../DESIGN.md)
