import { create } from 'zustand'

export type DashboardScreen =
  | 'overview'
  | 'agents'
  | 'bundles'
  | 'market'
  | 'catalog'
  | 'endpoints'
  | 'wallet'
  | 'settings'
  | 'providers'
  | 'models'
  | 'validation'
  | 'network'

export const dashboardScreens: readonly DashboardScreen[] = [
  'overview',
  'agents',
  'bundles',
  'market',
  'catalog',
  'endpoints',
  'wallet',
  'settings',
  'providers',
  'models',
  'validation',
  'network',
]

type OperatorDashboardState = {
  activeScreen: DashboardScreen
  advanced: boolean
  setActiveScreen: (screen: DashboardScreen) => void
  setAdvanced: (advanced: boolean) => void
}

export const useOperatorDashboardStore = create<OperatorDashboardState>((set) => ({
  activeScreen: 'overview',
  advanced: false,
  setActiveScreen: (activeScreen) => set({ activeScreen }),
  setAdvanced: (advanced) => set({ advanced }),
}))
