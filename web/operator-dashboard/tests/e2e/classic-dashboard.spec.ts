import { expect, test } from '@playwright/test'

import { useOfflineDashboardApi } from './fixtures'

test.beforeEach(async ({ page }) => {
  await useOfflineDashboardApi(page)
})

test('boots and keeps keyboard focus visible without a live Node', async ({ page }) => {
  await page.goto('./#overview')
  await expect(page.getByRole('button', { name: 'Open Hypervisor overview' })).toBeVisible()

  await page.keyboard.press('Tab')
  await expect(page.locator(':focus')).not.toHaveJSProperty('tagName', 'BODY')
})

test('navigates by Classic hash', async ({ page }) => {
  await page.goto('./#settings')

  await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible()
  await expect(page).toHaveURL(/#settings$/)
})

test('returns a direct Spatial URL to Classic when the rollout flag is off', async ({ page }) => {
  await page.goto('./#spatial')

  await expect(page.getByRole('heading', { name: 'Spatial UI is disabled' })).toBeVisible()
  await page.getByRole('button', { name: 'Return to Classic UI' }).click()
  await expect(page).toHaveURL(/#overview$/)
  await expect(page.getByRole('button', { name: 'Open Hypervisor overview' })).toBeVisible()
})

test('switches the same Node context between Classic and Spatial routes', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'chromium', 'Single-project route-switch demo')
  await page.addInitScript(() => {
    window.__AIDN_FEATURE_FLAGS__ = { spatial_ui_enabled: true }
    const originalGetContext = HTMLCanvasElement.prototype.getContext
    HTMLCanvasElement.prototype.getContext = function getContext(kind: string, options?: unknown) {
      if (kind === 'webgl2') return {} as WebGL2RenderingContext
      return originalGetContext.call(this, kind, options as never)
    }
  })
  await page.goto('./#overview')

  await page.getByRole('button', { name: 'Open Spatial UI' }).click()
  await expect(page.getByRole('heading', { name: 'Spatial Workspace preview' })).toBeVisible()
  await expect(page).toHaveURL(/#spatial$/)

  await page.getByRole('button', { name: 'Return to Classic UI' }).click()
  await expect(page.getByRole('button', { name: 'Open Hypervisor overview' })).toBeVisible()
  await expect(page).toHaveURL(/#overview$/)
})

test('opens mobile navigation and preserves the selected hash', async ({ page }, testInfo) => {
  test.skip(!testInfo.project.name.includes('mobile'), 'Mobile viewport smoke')
  await page.goto('./#overview')

  await page.getByRole('button', { name: 'Open navigation' }).click()
  await page.getByRole('button', { name: 'Settings', exact: true }).click()

  await expect(page.getByRole('heading', { name: 'Settings' })).toBeVisible()
  await expect(page).toHaveURL(/#settings$/)
})
