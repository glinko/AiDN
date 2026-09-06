import { expect, test, type Page } from '@playwright/test'

import { useOfflineDashboardApi as configureOfflineDashboardApi } from './fixtures'

async function openTopologySurface(page: Page) {
  await configureOfflineDashboardApi(page)
  await page.addInitScript(() => {
    window.__AIDN_FEATURE_FLAGS__ = { spatial_ui_enabled: true, spatial_interaction_enabled: true, spatial_topology_enabled: true }
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

test('M5 endpoint discovery promotes one canonical presence and exposes read-only details', async ({ page }) => {
  await openTopologySurface(page)
  await expect(page.getByRole('heading', { name: 'Endpoints & attention' })).toBeVisible()
  await expect(page.locator('[data-aidn-m5-topology] [data-aidn-endpoint-candidate]').first()).toBeVisible()
  const firstCandidate = page.locator('[data-aidn-m5-topology] [data-aidn-endpoint-candidate] button').first()
  await firstCandidate.click()
  await page.locator('.aidn-spatial-topology-details').scrollIntoViewIfNeeded()
  await expect(page.locator('.aidn-spatial-topology-details')).toContainText('Node-mediated reference')
  await expect(page.getByText(/explicit intent is still required/)).toBeVisible()
})

test('M5 attention focus is bounded, accessible, and does not move the camera', async ({ page }) => {
  await openTopologySurface(page)
  const viewportBefore = await page.locator('[data-aidn-viewport-readout]').textContent()
  const attentionButton = page.locator('[data-aidn-m5-topology] [data-aidn-attention-state] button').first()
  await expect(attentionButton).toBeVisible()
  await attentionButton.click()
  await expect(page.getByText(/viewport translation is temporary/)).toBeVisible()
  await page.getByRole('button', { name: 'Return viewport' }).click()
  await expect(page.getByText(/canonical positions were unchanged/)).toBeVisible()
  await expect(page.locator('[data-aidn-viewport-readout]')).toHaveText(viewportBefore ?? '')
})
