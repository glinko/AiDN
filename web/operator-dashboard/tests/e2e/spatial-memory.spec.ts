import { expect, test, type Page } from '@playwright/test'

import { useOfflineDashboardApi as configureOfflineDashboardApi } from './fixtures'

async function openMemorySurface(page: Page) {
  await configureOfflineDashboardApi(page)
  await page.addInitScript(() => {
    window.__AIDN_FEATURE_FLAGS__ = { spatial_ui_enabled: true, spatial_memory_enabled: true }
    const originalGetContext = HTMLCanvasElement.prototype.getContext
    HTMLCanvasElement.prototype.getContext = function getContext(kind: string, options?: unknown) {
      if (kind === 'webgl2') return {} as WebGL2RenderingContext
      return originalGetContext.call(this, kind, options as never)
    }
  })
  await page.goto('./#overview')
  await page.getByRole('button', { name: 'Open Spatial UI' }).click()
  await page.getByRole('button', { name: 'Open GlassFrame' }).click()
}

test('M8 memory surface searches, focuses and keeps bounded render telemetry visible', async ({ page }) => {
  await openMemorySurface(page)
  const surface = page.locator('[data-aidn-m8-memory]')
  await expect(surface.getByRole('heading', { name: 'Long-lived spatial memory' })).toBeVisible()
  await expect(surface.locator('[data-aidn-m8-render-budget]')).toContainText('/30 full objects')
  await expect(surface.getByText('RECENT MEMORY', { exact: true })).toBeVisible()
  await surface.getByLabel('Search history').fill('Repair')
  await expect(surface.getByText('Search result frame')).toBeVisible()
  await expect(surface.getByText('Repair plan')).toBeVisible()
  await surface.getByRole('button', { name: /Repair plan/ }).click()
  await expect(surface).toContainText('World Space position is preserved')
  await surface.getByRole('button', { name: 'Reset layout' }).click()
  await expect(surface).toContainText('deterministic semantic anchors')
  await surface.getByText(/Reveal semantic relations/).click()
  await expect(surface.locator('[data-aidn-m8-telemetry]')).toContainText('virtualized')
})
