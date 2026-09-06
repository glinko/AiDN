import { expect, test, type Page } from '@playwright/test'

import { useOfflineDashboardApi as configureOfflineDashboardApi } from './fixtures'

async function openM10Topology(page: Page) {
  await configureOfflineDashboardApi(page)
  await page.addInitScript(() => {
    window.__AIDN_FEATURE_FLAGS__ = {
      spatial_ui_enabled: true,
      spatial_interaction_enabled: true,
      spatial_topology_enabled: true,
      spatial_change_intent_enabled: true,
    }
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

test('M10 renders shared EndpointSummary and explicit Change Intent in Spatial', async ({ page }) => {
  await openM10Topology(page)
  await page.locator('[data-aidn-m5-topology] [data-aidn-endpoint-candidate] button').first().click()
  await expect(page.locator('[data-aidn-component="endpoint-summary"]')).toBeVisible()
  const port = page.getByRole('textbox', { name: 'Endpoint port' })
  await port.fill('8081')
  await page.getByRole('button', { name: 'Validate Change Intent' }).click()
  await expect(page.getByText(/Change Intent validated/)).toBeVisible()
  const configuration = page.locator('.aidn-endpoint-configuration')
  await configuration.scrollIntoViewIfNeeded()
  await configuration.getByRole('button', { name: 'Apply' }).evaluate((button) => (button as HTMLButtonElement).click())
  await expect(page.getByText(/applied at revision/)).toBeVisible()
})
