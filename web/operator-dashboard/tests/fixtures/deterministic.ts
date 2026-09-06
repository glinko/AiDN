import { vi } from 'vitest'

export const FIXED_NOW = new Date('2026-09-04T12:00:00.000Z')
export const FIXED_BROWSER_KEY = '0123456789abcdef'.repeat(4)
export const FIXED_REQUEST_IDS = [
  'request-00000001',
  'request-00000002',
  'request-00000003',
] as const

export function installDeterministicRuntime() {
  vi.useFakeTimers()
  vi.setSystemTime(FIXED_NOW)
  window.localStorage.setItem('aidn.dashboard.browser-key.v1', FIXED_BROWSER_KEY)
}
