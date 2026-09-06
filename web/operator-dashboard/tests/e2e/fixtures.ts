import type { Page } from '@playwright/test'

export async function useOfflineDashboardApi(page: Page) {
  await page.route('**/operators/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path === '/operators/dashboard/react' || path.startsWith('/operators/dashboard/react/')) {
      await route.continue()
      return
    }
    await route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'offline dashboard fixture' }),
    })
  })
}
