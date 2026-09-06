import { useCallback, useEffect } from 'react'

import { dashboardScreens, type DashboardScreen } from '@/stores/operator-dashboard'

export type DashboardNavigate = (screen: DashboardScreen) => void

export function dashboardScreenFromHash(hash: string): DashboardScreen | null {
  const candidate = hash.slice(1) as DashboardScreen
  return dashboardScreens.includes(candidate) ? candidate : null
}

export function navigateToDashboardScreen(screen: DashboardScreen, setActiveScreen: (screen: DashboardScreen) => void): void {
  setActiveScreen(screen)
  if (window.location.hash !== `#${screen}`) {
    // Keep navigation inside the React workspace while preserving browser
    // back/forward semantics on Safari/iOS as well as desktop browsers.
    window.history.pushState({ screen }, '', `#${screen}`)
  }
}

/** Keep the URL hash and the external dashboard store in sync. */
export function useDashboardRouting(setActiveScreen: (screen: DashboardScreen) => void): DashboardNavigate {
  useEffect(() => {
    function syncScreenFromHash() {
      const screen = dashboardScreenFromHash(window.location.hash)
      if (screen) setActiveScreen(screen)
    }

    syncScreenFromHash()
    window.addEventListener('hashchange', syncScreenFromHash)
    window.addEventListener('popstate', syncScreenFromHash)
    return () => {
      window.removeEventListener('hashchange', syncScreenFromHash)
      window.removeEventListener('popstate', syncScreenFromHash)
    }
  }, [setActiveScreen])

  return useCallback((screen: DashboardScreen) => {
    navigateToDashboardScreen(screen, setActiveScreen)
  }, [setActiveScreen])
}
