import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'

import { useOfflineDashboardApi } from './fixtures'

test('@a11y Classic shell has no serious or critical automated violations', async ({ page }) => {
  await useOfflineDashboardApi(page)
  await page.goto('./#overview')
  await expect(page.getByRole('button', { name: 'Open Hypervisor overview' })).toBeVisible()

  const results = await new AxeBuilder({ page }).analyze()
  const blocking = results.violations.filter((violation) =>
    violation.impact === 'serious' || violation.impact === 'critical')

  expect(blocking, blocking.map((violation) => `${violation.id}: ${violation.help}`).join('\n')).toEqual([])
})

test('@a11y Spatial fallback remains keyboard and screen-reader usable', async ({ page }) => {
  await useOfflineDashboardApi(page)
  await page.goto('./#spatial')
  await expect(page.getByRole('heading', { name: 'Spatial UI is disabled' })).toBeVisible()

  const results = await new AxeBuilder({ page }).analyze()
  const blocking = results.violations.filter((violation) =>
    violation.impact === 'serious' || violation.impact === 'critical')

  expect(blocking, blocking.map((violation) => `${violation.id}: ${violation.help}`).join('\n')).toEqual([])
})

test('@a11y Spatial token gallery has no serious or critical violations', async ({ page }) => {
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
  await page.getByRole('button', { name: 'Open Spatial UI' }).click()
  await expect(page.getByRole('heading', { name: 'Spatial Workspace preview' })).toBeVisible()

  const results = await new AxeBuilder({ page }).analyze()
  const blocking = results.violations.filter((violation) =>
    violation.impact === 'serious' || violation.impact === 'critical')

  expect(blocking, blocking.map((violation) => `${violation.id}: ${violation.help}`).join('\n')).toEqual([])
})
