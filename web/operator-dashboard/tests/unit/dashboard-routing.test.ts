import { describe, expect, it, vi } from 'vitest'

import { dashboardScreenFromHash, navigateToDashboardScreen } from '@/app/dashboard-routing'

describe('dashboard routing seam', () => {
  it('accepts only registered Classic hashes', () => {
    expect(dashboardScreenFromHash('#overview')).toBe('overview')
    expect(dashboardScreenFromHash('#settings')).toBe('settings')
    expect(dashboardScreenFromHash('#spatial')).toBeNull()
    expect(dashboardScreenFromHash('')).toBeNull()
  })

  it('keeps store updates and browser history in one navigation operation', () => {
    const setActiveScreen = vi.fn()
    window.history.replaceState(null, '', '#overview')

    navigateToDashboardScreen('settings', setActiveScreen)

    expect(setActiveScreen).toHaveBeenCalledWith('settings')
    expect(window.location.hash).toBe('#settings')
  })
})
