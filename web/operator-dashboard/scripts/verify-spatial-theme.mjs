import { readFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('..', import.meta.url))
const cssPath = resolve(root, 'src/spatial/theme/spatial-theme.css')
const galleryPath = resolve(root, 'src/spatial/theme/SpatialTokenGallery.tsx')
const boundaryPath = resolve(root, 'src/spatial/theme/SpatialThemeBoundary.tsx')
const primitivesPath = resolve(root, 'src/spatial/primitives/primitives.tsx')
const workspacePath = resolve(root, 'src/spatial/workspace/SpatialWorkspace.tsx')
const canvasPath = resolve(root, 'src/spatial/workspace/SpatialCanvas.tsx')
const overlayPath = resolve(root, 'src/spatial/workspace/SpatialDomOverlay.tsx')
const viewportPath = resolve(root, 'src/spatial/workspace/viewport.ts')
const errorBoundaryPath = resolve(root, 'src/spatial/workspace/SpatialRendererErrorBoundary.tsx')

function fail(message) {
  console.error(`Spatial theme verification failed: ${message}`)
  process.exitCode = 1
}

const [css, gallery, boundary, primitives, workspace, canvas, overlay, viewport, errorBoundary] = await Promise.all([
  readFile(cssPath, 'utf8'),
  readFile(galleryPath, 'utf8'),
  readFile(boundaryPath, 'utf8'),
  readFile(primitivesPath, 'utf8'),
  readFile(workspacePath, 'utf8'),
  readFile(canvasPath, 'utf8'),
  readFile(overlayPath, 'utf8'),
  readFile(viewportPath, 'utf8'),
  readFile(errorBoundaryPath, 'utf8'),
])

if (/^\s*(?:html|body|:root|#root)(?:\s|[,{])/m.test(css)) {
  fail('theme CSS must not define global html/body/root selectors')
}

const unscopedClassNames = [...gallery.matchAll(/className="([^"]+)"/g)]
  .map(([, value]) => value)
  .flatMap((value) => value.split(/\s+/).filter((name) => name && !name.startsWith('aidn-')))

if (unscopedClassNames.length > 0) {
  fail(`fixture contains unscoped class names: ${[...new Set(unscopedClassNames)].join(', ')}`)
}

for (const required of [
  '@supports (backdrop-filter: blur(1px))',
  "data-aidn-contrast='high'",
  "data-aidn-transparency='reduced'",
  '.aidn-glass-surface {',
  'border: 1px solid var(--aidn-glass-border)',
  'box-shadow: var(--aidn-shadow-soft)',
  '--aidn-surface-fallback:',
  '@media (prefers-reduced-transparency: reduce)',
]) {
  if (!css.includes(required)) fail(`missing fallback/profile rule ${required}`)
}

for (const required of ['SPATIAL_TOKEN_VERSION', 'data-aidn-theme-version', 'spatial-theme.css']) {
  if (!boundary.includes(required)) fail(`theme boundary is missing ${required}`)
}

for (const required of [
  'export function Surface',
  'export function GlassFrame',
  'export function Button',
  'export function IconButton',
  'export const Input',
  'export const TextArea',
  'export function InsetField',
  'export function Toggle',
  'export const Slider',
  'export function Tooltip',
  'export function StatusLabel',
  'export function FocusRing',
  'export function RaisedControl',
  "'aria-label': string",
  'data-aidn-depth',
  'data-aidn-glass',
  'data-aidn-accent',
  'data-aidn-radius',
  'data-aidn-emphasis',
]) {
  if (!primitives.includes(required)) fail(`primitive contract is missing ${required}`)
}

for (const required of [
  'export function SpatialWorkspace',
  'SpatialRendererErrorBoundary',
  'useSpatialViewport',
  'SpatialCanvas',
  'SpatialDomOverlay',
  'data-spatial-workspace="hybrid"',
  'data-spatial-layer="canvas"',
  'data-spatial-layer="dom-overlay"',
  'data-aidn-canvas-state',
  'data-interactive="true"',
  'aidn-spatial-scene-lane',
  'simulateRendererError',
  'ResizeObserver',
  'orientationchange',
  'frameloop="demand"',
  'tabIndex={-1}',
  'data-aidn-quality-profile',
  'data-aidn-primary-agent-state',
  'data-aidn-camera-focus',
  'data-aidn-performance-gate',
  'SpatialEntityList',
  'SpatialNavigationController',
]) {
  const source = `${workspace}\n${canvas}\n${overlay}\n${viewport}\n${errorBoundary}\n${gallery}`
  if (!source.includes(required)) fail(`hybrid shell contract is missing ${required}`)
}

for (const required of [
  "data-aidn-depth='raised'",
  ".aidn-spatial-button:active",
  '.aidn-spatial-button:focus-visible',
  '.aidn-spatial-button:disabled',
  'min-height: 44px',
  '.aidn-tooltip-content',
  '.aidn-status-label',
  '.aidn-focus-ring',
  '.aidn-raised-control',
  '.aidn-spatial-workspace',
  '.aidn-spatial-canvas-layer',
  '.aidn-spatial-dom-overlay',
  'pointer-events: none',
  'position: fixed',
  '.aidn-spatial-renderer-error',
  '.aidn-spatial-primary-card',
  '.aidn-spatial-navigation',
  '.aidn-spatial-entity-list',
  '.aidn-spatial-gate',
]) {
  if (!css.includes(required)) fail(`primitive style rule is missing ${required}`)
}

if (/[a-z]+-\[[^\]]+\]/.test(gallery)) {
  fail('fixture must use semantic Spatial classes instead of arbitrary utility literals')
}

if (process.exitCode !== 1) {
  console.log('Verified Spatial theme scope, primitive contract, hybrid renderer boundary, fixture class names, and profile fallbacks.')
}
