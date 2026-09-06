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

test('System Menu remains independent from the renderer and exposes one status revision', async ({ page }) => {
  await useOfflineDashboardApi(page)
  await enableSpatial(page)
  await page.goto('./#overview')
  await page.getByRole('button', { name: 'Open Spatial UI' }).click()
  await page.getByRole('button', { name: 'Open GlassFrame' }).click()
  await page.getByRole('button', { name: 'System Menu' }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'System Menu' })).toBeVisible()
  await expect(page.getByText(/revision 1/).first()).toBeVisible()
  await page.getByRole('button', { name: /Hypervisor/ }).click()
  await expect(page.getByRole('article', { name: /Hypervisor details/ })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toHaveCount(0)
})

test('WebGL fallback still exposes a DOM System Menu and Classic recovery path', async ({ page }) => {
  await useOfflineDashboardApi(page)
  await page.addInitScript(() => {
    window.__AIDN_FEATURE_FLAGS__ = { spatial_ui_enabled: true }
    HTMLCanvasElement.prototype.getContext = (() => null) as typeof HTMLCanvasElement.prototype.getContext
  })
  await page.goto('./#spatial')
  await expect(page.getByRole('heading', { name: 'Spatial UI needs WebGL2' })).toBeVisible()
  await page.getByRole('button', { name: 'System Menu' }).click()
  await expect(page.getByRole('dialog')).toContainText('last-known evidence')
  await page.getByRole('dialog').getByRole('button', { name: 'Return to Classic UI' }).click()
  await expect(page).toHaveURL(/#overview/)
})

test('System Menu uses an adaptive bottom-sheet frame on mobile', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await useOfflineDashboardApi(page)
  await enableSpatial(page)
  await page.goto('./#overview')
  await page.getByRole('button', { name: 'Open Spatial UI' }).click()
  await page.getByRole('button', { name: 'Open GlassFrame' }).click()
  await page.getByRole('button', { name: 'System Menu' }).click()
  await expect(page.locator('.aidn-spatial-system-menu-dialog')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Status', exact: true })).toBeVisible()
})
