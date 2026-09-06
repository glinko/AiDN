import { expect, test, type Page } from '@playwright/test'

import { useOfflineDashboardApi as configureOfflineDashboardApi } from './fixtures'

async function openSpatialWorkspace(page: Page) {
  await configureOfflineDashboardApi(page)
  await page.addInitScript(() => {
    window.__AIDN_FEATURE_FLAGS__ = { spatial_ui_enabled: true, spatial_interaction_enabled: true }
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

test('creates, persists, and collapses a text interaction without a canvas entity clone', async ({ page }) => {
  await openSpatialWorkspace(page)
  await expect(page.getByRole('heading', { name: 'Conversation Surface' })).toBeVisible()
  await page.getByRole('button', { name: /Create interaction/ }).click()
  const input = page.getByLabel('Interaction text')
  await expect(input).toBeFocused()
  await input.fill('summarize this workspace')
  await page.getByRole('button', { name: /Submit/ }).click()
  await expect(page.getByRole('log')).toContainText('summarize this workspace')
  await expect(page.getByText(/Primary Agent acknowledged/)).toBeVisible()
  await page.getByRole('button', { name: /Create Generated Object/ }).click()
  await expect(page.getByText('Object linked')).toBeVisible()
  await page.getByRole('button', { name: /Collapse to Artifact/ }).click()
  await expect(page.getByText(/Session collapsed to an Artifact/)).toBeVisible()
  await page.getByRole('button', { name: /Restore Session/ }).click()
  await expect(page.getByText(/Session restored/)).toBeVisible()
  await page.getByRole('button', { name: /Start branch/ }).click()
  await page.getByLabel('Interaction text').fill('continue from the artifact')
  await page.getByRole('button', { name: /Submit/ }).click()
  await expect(page.getByRole('log')).toContainText('continue from the artifact')
  await page.reload()
  await page.getByRole('button', { name: 'Open GlassFrame' }).click()
  await expect(page.getByRole('log')).toContainText('continue from the artifact')
})

test('keyboard seed is explicit and entity controls keep their own semantics', async ({ page }) => {
  await openSpatialWorkspace(page)
  await page.keyboard.press('Control+I')
  await expect(page.getByLabel('Interaction text')).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(page.getByLabel('Interaction text')).toHaveCount(0)
  await page.getByRole('button', { name: 'Primary Agent, Ready' }).click()
  await expect(page.getByLabel('Interaction text')).toHaveCount(0)
})

test('empty canvas click opens the seed while an entity click does not', async ({ page }) => {
  await openSpatialWorkspace(page)
  const canvas = page.locator('canvas[data-aidn-canvas-renderer="2d-fallback"]')
  await canvas.click({ position: { x: 12, y: 12 } })
  await expect(page.getByLabel('Interaction text')).toBeFocused()
  await page.keyboard.press('Escape')
  await expect(page.getByLabel('Interaction text')).toHaveCount(0)
})
