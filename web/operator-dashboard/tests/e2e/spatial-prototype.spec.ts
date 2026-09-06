import { expect, test, type Page } from '@playwright/test'

import { useOfflineDashboardApi as configureOfflineDashboardApi } from './fixtures'

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

async function openSpatialWorkspace(page: Page) {
  await configureOfflineDashboardApi(page)
  await enableSpatial(page)
  await page.goto('./#overview')
  await page.getByRole('button', { name: 'Open Spatial UI' }).click()
  await page.getByRole('button', { name: 'Open GlassFrame' }).click()
}

test('runs the Prototype A entity and camera path on the desktop fallback', async ({ page }) => {
  await openSpatialWorkspace(page)

  const workspace = page.locator('[data-spatial-workspace="hybrid"]')
  const canvasShell = page.locator('.aidn-spatial-canvas-shell')
  await expect(canvasShell).toHaveAttribute('data-aidn-canvas-atmosphere', 'white-studio')
  await expect(canvasShell).toHaveAttribute('data-aidn-canvas-fog', '5-20')
  await expect(workspace).toHaveAttribute('data-aidn-quality-profile', 'desktop')
  await expect(page.getByRole('button', { name: 'Primary Agent, Ready' })).toBeVisible()
  await expect(page.locator('[data-aidn-system-placeholder]')).toContainText('System')

  await page.getByLabel('Scene quality').selectOption('high')
  await expect(workspace).toHaveAttribute('data-aidn-quality-profile', 'high')
  await expect(canvasShell).toHaveAttribute('data-aidn-canvas-fog', '5-24')

  await page.getByRole('button', { name: 'Cycle state' }).click()
  await expect(workspace).toHaveAttribute('data-aidn-primary-agent-state', 'THINKING')
  await expect(page.getByText('Reasoning is in progress; no action has been committed.')).toBeVisible()

  await page.getByText(/Keyboard entity list/).click()
  await expect(page.getByText(/Subagents 3 · Endpoints 7 · Artifacts 6 · Attention 3/)).toBeVisible()
  await page.getByRole('button', { name: /Browser endpoint/ }).click()
  await expect(workspace).toHaveAttribute('data-aidn-selected-node', 'endpoint-browser')
  await page.getByRole('button', { name: 'Focus selected' }).click()
  await expect(workspace).toHaveAttribute('data-aidn-camera-focus', 'endpoint-browser')
  await page.getByRole('button', { name: 'Back from focus' }).click()
  await expect(workspace).toHaveAttribute('data-aidn-camera-focus', 'home')

  await page.getByRole('button', { name: /Session artifact/ }).click()
  await page.getByRole('button', { name: 'Focus selected' }).click()
  await expect(workspace).toHaveAttribute('data-aidn-camera-focus', 'artifact-session')
  await page.getByRole('button', { name: 'HOME' }).click()
  await expect(workspace).toHaveAttribute('data-aidn-camera-focus', 'home')

  const navigation = page.locator('[data-aidn-navigation-controller]')
  await navigation.focus()
  await page.keyboard.press('Home')
  await expect(workspace).toHaveAttribute('data-aidn-camera-focus', 'home')
  await page.keyboard.press('+')
  await expect(workspace).toHaveAttribute('data-aidn-camera-zoom', '1.08')
})

test('keeps the mobile profile bounded and the performance gate readable', async ({ page }) => {
  await page.setViewportSize({ width: 480, height: 800 })
  await openSpatialWorkspace(page)

  const workspace = page.locator('[data-spatial-workspace="hybrid"]')
  await expect(workspace).toHaveAttribute('data-aidn-quality-profile', 'mobile')
  await expect(page.locator('.aidn-spatial-canvas-shell')).toHaveAttribute('data-aidn-canvas-fog', '4.5-15')
  await expect(page.locator('[data-aidn-prototype-gate]')).toHaveAttribute('data-aidn-prototype-gate', /pass|needs-attention/)
  await page.getByText(/Prototype A performance gate/).click()
  await expect(page.getByText(/Bounded samples:/)).toBeVisible()
})
