import { expect, test } from '@playwright/test'

import { useOfflineDashboardApi } from './fixtures'

test('keeps Spatial renderer code out of Classic and requests the lazy chunk once', async ({ page }) => {
  const spatialRequests: string[] = []
  page.on('request', (request) => {
    if (/spatial-route-[^/]+\.js(?:\?|$)/.test(request.url())) spatialRequests.push(request.url())
  })

  await useOfflineDashboardApi(page)
  await page.addInitScript(() => {
    window.__AIDN_FEATURE_FLAGS__ = { spatial_ui_enabled: true }
    const originalGetContext = HTMLCanvasElement.prototype.getContext
    HTMLCanvasElement.prototype.getContext = function getContext(kind: string, options?: unknown) {
      if (kind === 'webgl2') return {} as WebGL2RenderingContext
      return originalGetContext.call(this, kind, options as never)
    }
  })

  await page.goto('./#overview')
  await expect(page.getByRole('button', { name: 'Open Hypervisor overview' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Open Spatial UI' })).toBeVisible()
  expect(spatialRequests).toEqual([])

  await page.getByRole('button', { name: 'Open Spatial UI' }).click()
  await expect(page.getByRole('heading', { name: 'Spatial Workspace preview' })).toBeVisible()
  await expect.poll(() => spatialRequests.length).toBe(1)
  const spatialChunk = spatialRequests[0]

  await page.getByRole('button', { name: 'Return to Classic UI' }).click()
  await expect(page.getByRole('button', { name: 'Open Hypervisor overview' })).toBeVisible()
  await page.getByRole('button', { name: 'Open Spatial UI' }).click()
  await expect(page.getByRole('heading', { name: 'Spatial Workspace preview' })).toBeVisible()
  expect(spatialRequests).toEqual([spatialChunk])
})

