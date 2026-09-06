import { expect, test } from '@playwright/test'

import { useOfflineDashboardApi } from './fixtures'

test('an explicit operator-preview disable flag keeps the direct Spatial URL on Classic fallback', async ({ page }) => {
  await useOfflineDashboardApi(page)
  await page.addInitScript(() => {
    window.__AIDN_FEATURE_FLAGS__ = { spatial_ui_enabled: true, spatial_operator_preview_enabled: false }
  })
  await page.goto('./#spatial')
  await expect(page.getByRole('heading', { name: 'Spatial UI is disabled' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Return to Classic UI' })).toBeVisible()
})

test('operator-preview fallback keeps System Menu and Classic recovery available', async ({ page }) => {
  await useOfflineDashboardApi(page)
  await page.addInitScript(() => {
    window.__AIDN_FEATURE_FLAGS__ = { spatial_ui_enabled: true, spatial_operator_preview_enabled: true }
    HTMLCanvasElement.prototype.getContext = (() => null) as typeof HTMLCanvasElement.prototype.getContext
  })
  await page.goto('./#spatial')
  await expect(page.getByRole('heading', { name: 'Spatial UI needs WebGL2' })).toBeVisible()
  await page.getByRole('button', { name: 'System Menu' }).click()
  await expect(page.getByRole('dialog')).toContainText('last-known evidence')
  await page.getByRole('dialog').getByRole('button', { name: 'Return to Classic UI' }).click()
  await expect(page).toHaveURL(/#overview/)
})

