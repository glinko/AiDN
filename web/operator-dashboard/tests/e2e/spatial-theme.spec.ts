import { expect, test, type Page } from '@playwright/test'

import { useOfflineDashboardApi } from './fixtures'

async function enableSpatial(page: Page) {
  await page.addInitScript(() => {
    window.__AIDN_FEATURE_FLAGS__ = { spatial_ui_enabled: true }
    const originalGetContext = HTMLCanvasElement.prototype.getContext
    HTMLCanvasElement.prototype.getContext = function getContext(kind: string, options?: unknown) {
      if (kind === 'webgl2') return {} as WebGL2RenderingContext
      return originalGetContext.call(this, kind, options as never)
    }
  })
}

test('demonstrates Spatial token profiles and fallback specimens', async ({ page }) => {
  await useOfflineDashboardApi(page)
  await enableSpatial(page)

  await page.goto('./#overview')
  await page.getByRole('button', { name: 'Open Spatial UI' }).click()

  const theme = page.locator('[data-aidn-theme-version="spatial.tokens.v1"]')
  await expect(page.getByRole('heading', { name: 'Spatial Workspace preview' })).toBeVisible()
  await expect(theme).toHaveAttribute('data-aidn-contrast', 'standard')
  await expect(theme).toHaveAttribute('data-aidn-transparency', 'full')
  await expect(page.getByText('Opaque fallback')).toBeVisible()
  await expect(page.getByText('AA pass').first()).toBeVisible()

  await page.getByRole('button', { name: 'High contrast' }).click()
  await page.getByRole('button', { name: 'Reduced transparency' }).click()
  await expect(theme).toHaveAttribute('data-aidn-contrast', 'high')
  await expect(theme).toHaveAttribute('data-aidn-transparency', 'reduced')

  await page.getByRole('button', { name: 'Replay motion' }).click()
  await expect(page.getByText(/Motion profile:/)).toBeVisible()
})

test('supports a keyboard-only path through Spatial DOM primitives', async ({ page }) => {
  await useOfflineDashboardApi(page)
  await enableSpatial(page)
  await page.goto('./#overview')
  await page.getByRole('button', { name: 'Open Spatial UI' }).click()
  await expect(page.getByRole('heading', { name: 'DOM primitives gallery' })).toBeVisible()

  const slider = page.getByRole('slider', { name: 'Preview intensity' })
  await slider.focus()
  await page.keyboard.press('ArrowRight')
  await expect(slider).toHaveValue('65')

  const toggle = page.getByRole('switch', { name: 'Enable live preview' })
  await toggle.focus()
  await page.keyboard.press('Space')
  await expect(toggle).toHaveAttribute('aria-checked', 'false')

  const iconButton = page.getByRole('button', { name: 'Explain surface profiles' })
  await iconButton.focus()
  await expect(page.getByRole('tooltip')).toBeVisible()

  const save = page.getByRole('button', { name: 'Save workspace' })
  await save.focus()
  await page.keyboard.press('Enter')
  await expect(page.getByText(/Saved Primary workspace with explicit action handler/)).toBeVisible()
})

test('keeps the DOM overlay above the mock scene through resize and selection', async ({ page }) => {
  await useOfflineDashboardApi(page)
  await enableSpatial(page)
  await page.goto('./#overview')
  await page.getByRole('button', { name: 'Open Spatial UI' }).click()

  const workspace = page.locator('[data-spatial-workspace="hybrid"]')
  const canvas = page.locator('canvas[data-aidn-canvas-renderer="2d-fallback"]')
  await expect(page.locator('.aidn-spatial-scene-lane')).toBeVisible()
  await expect(workspace).toHaveAttribute('data-spatial-workspace', 'hybrid')
  await expect(canvas).toHaveAttribute('tabindex', '-1')
  await expect(page.locator('[data-spatial-layer="dom-overlay"]')).toHaveCSS('pointer-events', 'none')
  await expect(page.locator('[data-interactive="true"]').first()).toHaveCSS('pointer-events', 'auto')
  await expect(page.locator('main.aidn-spatial-page')).toHaveCSS('pointer-events', 'none')
  await expect(page.getByRole('button', { name: 'High contrast' })).toHaveCSS('pointer-events', 'auto')

  await page.getByRole('button', { name: 'Open GlassFrame' }).click()
  await page.getByRole('button', { name: 'DOM control over canvas' }).click()
  await expect(page.getByText('DOM control handled the action without touching the canvas.')).toBeVisible()

  await page.evaluate(() => {
    document.querySelector('canvas[data-aidn-canvas-renderer="2d-fallback"]')?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
  })
  await expect(page.getByText('Mock Primary Agent')).toBeVisible()
  const revision = Number(await workspace.getAttribute('data-aidn-viewport-revision'))

  await page.setViewportSize({ width: 480, height: 800 })
  await expect(workspace).toHaveAttribute('data-aidn-viewport-orientation', 'portrait')
  await expect(page.getByText('Mock Primary Agent')).toBeVisible()
  await expect.poll(async () => Number(await workspace.getAttribute('data-aidn-viewport-revision'))).toBeGreaterThan(revision)
})
