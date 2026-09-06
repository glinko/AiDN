import { defineConfig, devices } from '@playwright/test'

const dashboardUrl = 'http://127.0.0.1:4174/operators/dashboard/react/'

export default defineConfig({
  testDir: './tests/e2e',
  testMatch: 'spatial-bundle.spec.ts',
  outputDir: './test-results/spatial-bundle',
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI
    ? [['line'], ['html', { outputFolder: 'playwright-report/spatial-bundle', open: 'never' }]]
    : 'list',
  use: {
    baseURL: dashboardUrl,
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    video: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: 'pnpm build && pnpm bundle:report && pnpm preview --host 127.0.0.1 --port 4174',
    url: dashboardUrl,
    reuseExistingServer: false,
    timeout: 120_000,
  },
})

