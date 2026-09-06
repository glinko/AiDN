import { expect, test, type Page } from '@playwright/test'

import { useOfflineDashboardApi as configureOfflineDashboardApi } from './fixtures'

async function openRemoteFrame(page: Page) {
  await configureOfflineDashboardApi(page)
  await page.addInitScript(() => {
    window.__AIDN_FEATURE_FLAGS__ = {
      spatial_ui_enabled: true,
      spatial_interaction_enabled: true,
      spatial_topology_enabled: true,
      spatial_remote_mediation_enabled: true,
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
  await page.locator('[data-aidn-m5-topology] [data-aidn-endpoint-candidate] button').first().click()
}

test('M7 Endpoint Test Frame requires explicit submit and keeps provenance local', async ({ page }) => {
  await openRemoteFrame(page)
  const frame = page.locator('[data-aidn-m7-endpoint-test]')
  await expect(frame).toBeVisible()
  await expect(frame).toContainText('Waiting for explicit submit')
  const input = frame.getByLabel('Explicit test input')
  await input.fill('hello from operator')
  await expect(frame.getByRole('button', { name: 'Send test request' })).toBeEnabled()
  await frame.getByRole('button', { name: 'Send test request' }).click()
  await expect(frame).toContainText('Validated remote data')
  await expect(frame).toContainText('untrusted data')
  await expect(frame).toContainText('remote-request')
})
