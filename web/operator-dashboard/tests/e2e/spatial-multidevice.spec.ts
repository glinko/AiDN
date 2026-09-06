import { expect, test, type Page } from '@playwright/test'

import { useOfflineDashboardApi as configureOfflineDashboardApi } from './fixtures'

async function openMultiDeviceSurface(page: Page) {
  await configureOfflineDashboardApi(page)
  await page.addInitScript(() => {
    window.__AIDN_FEATURE_FLAGS__ = { spatial_ui_enabled: true, spatial_multi_device_sync_enabled: true }
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

test('M9 desktop and mobile share semantic world but keep local viewports', async ({ page }) => {
  await openMultiDeviceSurface(page)
  const surface = page.locator('[data-aidn-m9-multidevice]')
  await expect(surface.getByRole('heading', { name: 'One Workspace, two local viewports' })).toBeVisible()
  await expect(surface.locator('[data-aidn-m9-world-revision]')).toContainText('world revision')
  const desktopCamera = surface.locator('[data-aidn-m9-desktop-camera]')
  const mobileCamera = surface.locator('[data-aidn-m9-mobile-camera]')
  await expect(desktopCamera).toContainText('HOME')
  await expect(mobileCamera).toContainText('HOME')
  await surface.getByRole('button', { name: 'Zoom desktop' }).click()
  await expect(desktopCamera).toContainText('zoom 1.25')
  await expect(mobileCamera).toContainText('zoom 1.00')
  await surface.getByRole('button', { name: 'Pin shared ref' }).click()
  await expect(surface).toContainText('pinned in the shared semantic world')
  await surface.getByRole('button', { name: 'Queue mobile mutation' }).click()
  await expect(surface.locator('[data-aidn-m9-offline-state]')).toContainText('1 pending')
  await surface.getByRole('button', { name: /Replay offline/ }).click()
  await expect(surface).toContainText('Offline replay resolved')
  await surface.getByRole('button', { name: 'Share focus' }).click()
  await expect(surface).toContainText('Share View accepted for mobile-demo')
})
