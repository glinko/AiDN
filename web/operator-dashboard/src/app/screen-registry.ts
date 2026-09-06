import {
  Activity,
  BellRing,
  Box,
  Boxes,
  BriefcaseBusiness,
  Database,
  Gauge,
  GitBranch,
  Network,
  PanelsTopLeft,
  RadioTower,
  ServerCog,
  Settings,
  ShieldCheck,
  WalletCards,
  type LucideIcon,
} from 'lucide-react'

import type { DashboardScreen } from '@/stores/operator-dashboard'

export type NavigationItem = {
  id: DashboardScreen
  label: string
  icon: LucideIcon
  advanced?: boolean
}

export const navigationItems: readonly NavigationItem[] = [
  { id: 'overview', label: 'Overview', icon: PanelsTopLeft },
  { id: 'agents', label: 'Agents', icon: Activity },
  { id: 'bundles', label: 'Bundles', icon: Boxes },
  { id: 'market', label: 'Market', icon: BriefcaseBusiness },
  { id: 'catalog', label: 'Catalog', icon: Box },
  { id: 'endpoints', label: 'Endpoints', icon: RadioTower, advanced: true },
  { id: 'wallet', label: 'Wallet', icon: WalletCards },
  { id: 'settings', label: 'Settings', icon: Settings },
]

export const advancedItems: readonly NavigationItem[] = [
  { id: 'providers', label: 'Provider Plugins', icon: ServerCog, advanced: true },
  { id: 'models', label: 'Models', icon: Database, advanced: true },
  { id: 'validation', label: 'Validation', icon: ShieldCheck, advanced: true },
  { id: 'network', label: 'Network', icon: Network, advanced: true },
  { id: 'cometbft', label: 'CometBFT', icon: GitBranch, advanced: true },
  { id: 'resources', label: 'Resources', icon: Gauge, advanced: true },
  { id: 'hooks', label: 'Hooks', icon: BellRing },
]

export type OperationsScreen = Exclude<DashboardScreen, 'overview' | 'bundles' | 'endpoints' | 'settings' | 'resources'>

const operationsScreens: readonly OperationsScreen[] = [
  'agents',
  'market',
  'catalog',
  'wallet',
  'providers',
  'models',
  'validation',
  'network',
  'cometbft',
  'hooks',
]

export function isOperationsScreen(screen: DashboardScreen): screen is OperationsScreen {
  return operationsScreens.includes(screen as OperationsScreen)
}
