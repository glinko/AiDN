import { useEffect, useState } from 'react'
import {
  Activity,
  ArrowRightLeft,
  Box,
  Boxes,
  BriefcaseBusiness,
  CheckCircle2,
  ChevronRight,
  CircleDot,
  Copy,
  Cpu,
  Database,
  Gauge,
  Layers3,
  KeyRound,
  LogOut,
  Menu,
  Network,
  PanelsTopLeft,
  Plus,
  RadioTower,
  RefreshCw,
  RotateCcw,
  Search,
  ServerCog,
  Settings,
  ShieldCheck,
  Sparkles,
  WalletCards,
  Trash2,
  Clock3,
  Eye,
  XCircle,
  Zap,
  type LucideIcon,
} from 'lucide-react'
import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
} from '@tanstack/react-table'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Separator } from '@/components/ui/separator'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import {
  formatCount,
  formatMemory,
  formatPercent,
  getRecord,
  getText,
  getTextList,
  resourceUsage,
  shortId,
} from '@/lib/format'
import { useDashboardData } from '@/hooks/use-dashboard'
import { DashboardApiError, dashboardApi, type AccessCredential, type AgentPermissionCatalog, type DashboardAccessStatus, type DashboardRecord, type EnrollmentRequest, type ProviderArtifactInventory, type ProviderWorkspace } from '@/lib/api'
import { dashboardScreens, useOperatorDashboardStore, type DashboardScreen } from '@/stores/operator-dashboard'
import type { Bundle, Endpoint, Fleet, Readiness, ReadinessStep, WalletDashboard } from '@/lib/types'
import { createSavedHypervisor, loadSavedHypervisors, saveSavedHypervisors, type SavedHypervisorConnection } from '@/lib/hypervisor-connections'

type NavigationItem = {
  id: DashboardScreen
  label: string
  icon: LucideIcon
  advanced?: boolean
}

const navigationItems: NavigationItem[] = [
  { id: 'overview', label: 'Overview', icon: PanelsTopLeft },
  { id: 'agents', label: 'Agents', icon: Activity },
  { id: 'bundles', label: 'Bundles', icon: Boxes },
  { id: 'market', label: 'Market', icon: BriefcaseBusiness },
  { id: 'catalog', label: 'Catalog', icon: Box },
  { id: 'endpoints', label: 'Endpoints', icon: RadioTower, advanced: true },
  { id: 'wallet', label: 'Wallet', icon: WalletCards },
  { id: 'settings', label: 'Settings', icon: Settings },
]

const advancedItems: NavigationItem[] = [
  { id: 'providers', label: 'Provider Plugins', icon: ServerCog, advanced: true },
  { id: 'models', label: 'Models', icon: Database, advanced: true },
  { id: 'validation', label: 'Validation', icon: ShieldCheck, advanced: true },
  { id: 'network', label: 'Network', icon: Network, advanced: true },
]

function inventoryRecords(value: ProviderArtifactInventory | undefined): DashboardRecord[] {
  if (Array.isArray(value)) return value
  const items = getRecord(value)?.items
  return Array.isArray(items)
    ? items.filter((item): item is DashboardRecord => Boolean(getRecord(item)))
    : []
}

const statusClassNames: Record<string, string> = {
  ready: 'border-emerald-400/25 bg-emerald-400/10 text-emerald-300',
  healthy: 'border-emerald-400/25 bg-emerald-400/10 text-emerald-300',
  published: 'border-emerald-400/25 bg-emerald-400/10 text-emerald-300',
  in_sync: 'border-emerald-400/25 bg-emerald-400/10 text-emerald-300',
  enabled: 'border-emerald-400/25 bg-emerald-400/10 text-emerald-300',
  closed: 'border-slate-300/25 bg-slate-300/10 text-slate-200',
  settled: 'border-emerald-300/25 bg-emerald-300/10 text-emerald-200',
  completed: 'border-emerald-300/25 bg-emerald-300/10 text-emerald-200',
  force_settled: 'border-amber-300/30 bg-amber-300/10 text-amber-200',
  running: 'border-cyan-300/25 bg-cyan-300/10 text-cyan-200',
  loopback_active: 'border-cyan-300/25 bg-cyan-300/10 text-cyan-200',
  lan_active: 'border-amber-300/30 bg-amber-300/10 text-amber-200',
  created: 'border-sky-300/25 bg-sky-300/10 text-sky-200',
  pending: 'border-amber-300/25 bg-amber-300/10 text-amber-200',
  stopped: 'border-slate-300/20 bg-slate-300/8 text-slate-300',
  unavailable: 'border-slate-300/20 bg-slate-300/8 text-slate-300',
  blocked: 'border-rose-300/25 bg-rose-300/10 text-rose-200',
  failed: 'border-rose-300/25 bg-rose-300/10 text-rose-200',
  error: 'border-rose-300/25 bg-rose-300/10 text-rose-200',
}

const terminalSessionStatuses = new Set([
  'closed',
  'settled',
  'completed',
  'cancelled',
  'canceled',
  'rejected',
  'failed',
  'expired',
  'force_settled',
  'unrecoverable',
])

function normalizeStatus(value: string): string {
  return value.trim().toLowerCase().replaceAll('-', '_').replaceAll(' ', '_')
}

function isTerminalSessionStatus(value: string): boolean {
  return terminalSessionStatuses.has(normalizeStatus(value))
}

function terminalSessionLabel(value: string): string {
  switch (normalizeStatus(value)) {
    case 'closed':
      return 'Closed'
    case 'force_settled':
      return 'Force settled'
    case 'settled':
      return 'Settled'
    case 'completed':
      return 'Completed'
    case 'cancelled':
    case 'canceled':
      return 'Cancelled'
    case 'rejected':
      return 'Rejected'
    case 'failed':
      return 'Failed'
    case 'expired':
      return 'Expired'
    case 'unrecoverable':
      return 'Unrecoverable'
    default:
      return 'Terminal'
  }
}

type OperationsScreen = Exclude<DashboardScreen, 'overview' | 'bundles' | 'endpoints' | 'settings'>

type RefreshFeedback = {
  state: 'idle' | 'running' | 'success' | 'error'
  message: string
}

const operationsScreens: readonly OperationsScreen[] = [
  'agents',
  'market',
  'catalog',
  'wallet',
  'providers',
  'models',
  'validation',
  'network',
]

function isOperationsScreen(screen: DashboardScreen): screen is OperationsScreen {
  return operationsScreens.includes(screen as OperationsScreen)
}

function App() {
  const { activeScreen, advanced, setActiveScreen, setAdvanced } = useOperatorDashboardStore()
  const data = useDashboardData()
  const [mobileOpen, setMobileOpen] = useState(false)
  const [savedHypervisors, setSavedHypervisors] = useState<SavedHypervisorConnection[]>(loadSavedHypervisors)
  const [addHypervisorOpen, setAddHypervisorOpen] = useState(false)
  const [refreshFeedback, setRefreshFeedback] = useState<RefreshFeedback>({ state: 'idle', message: 'Live data refreshes every 20 seconds' })

  const nodeIdentity = data.home.data?.bootstrap.node_identity ?? data.fleet.data?.node
  const nodeName = getText(nodeIdentity, 'node_id') || 'Local Hypervisor'
  const readinessPercent = data.readiness.data?.progress.percent ?? 0
  const hasRefreshError = [data.home, data.readiness, data.fleet, data.bundles, data.endpoints, data.wallet, data.providers, data.installs, data.sessions, data.market, data.remoteEndpoints, data.events].some(
    (query) => query.isError,
  )

  useEffect(() => {
    function syncScreenFromHash() {
      const candidate = window.location.hash.slice(1) as DashboardScreen
      if (dashboardScreens.includes(candidate)) {
        setActiveScreen(candidate)
      }
    }

    syncScreenFromHash()
    window.addEventListener('hashchange', syncScreenFromHash)
    return () => window.removeEventListener('hashchange', syncScreenFromHash)
  }, [setActiveScreen])

  function refreshAll() {
    setRefreshFeedback({ state: 'running', message: 'Refreshing Hypervisor state...' })
    void Promise.allSettled([
      data.home.refetch(),
      data.readiness.refetch(),
      data.fleet.refetch(),
      data.bundles.refetch(),
      data.endpoints.refetch(),
      data.wallet.refetch(),
      data.providers.refetch(),
      data.installs.refetch(),
      data.sessions.refetch(),
      data.market.refetch(),
      data.remoteEndpoints.refetch(),
      data.events.refetch(),
    ]).then((results) => {
      const failed = results.filter((result) => result.status === 'rejected').length
      const time = new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(new Date())
      setRefreshFeedback(failed > 0
        ? { state: 'error', message: `${failed} dashboard section${failed === 1 ? '' : 's'} failed to refresh at ${time}` }
        : { state: 'success', message: `Hypervisor state refreshed at ${time}` })
    })
  }

  function navigate(screen: DashboardScreen) {
    setActiveScreen(screen)
    if (window.location.hash !== `#${screen}`) {
      // Assigning the hash keeps browser history and the hashchange listener
      // in sync on Safari/iOS as well as desktop browsers.
      window.location.hash = screen
    }
    setMobileOpen(false)
  }

  return (
    <div className="operator-shell min-h-svh bg-background text-foreground">
      <TopBar
        nodeName={nodeName}
        advanced={advanced}
        isRefreshing={data.home.isFetching || data.readiness.isFetching || data.events.isFetching}
        refreshError={hasRefreshError}
        refreshFeedback={refreshFeedback}
        onRefresh={refreshAll}
        onToggleAdvanced={() => setAdvanced(!advanced)}
        onOpenNavigation={() => setMobileOpen(true)}
        onNavigate={navigate}
        savedHypervisors={savedHypervisors}
        onAddHypervisor={() => setAddHypervisorOpen(true)}
        onRemoveHypervisor={(connection) => {
          const next = savedHypervisors.filter((item) => item.id !== connection.id)
          saveSavedHypervisors(next)
          setSavedHypervisors(next)
        }}
      />

      <div className="mx-auto flex w-full max-w-[1760px] gap-0 px-3 pb-20 pt-3 lg:px-5">
        <aside className="hidden w-[224px] shrink-0 lg:block">
          <Navigation
            activeScreen={activeScreen}
            advanced={advanced}
            readinessPercent={readinessPercent}
            onNavigate={navigate}
            onToggleAdvanced={() => setAdvanced(!advanced)}
          />
        </aside>

        <main className="min-w-0 flex-1 lg:pl-5">
          {activeScreen === 'overview' ? (
            <OverviewScreen data={data} onNavigate={navigate} onRefresh={refreshAll} />
          ) : null}
          {activeScreen === 'bundles' ? (
            <BundlesScreen bundles={data.bundles.data?.items ?? []} isLoading={data.bundles.isLoading} error={data.bundles.error} onNavigate={navigate} onRefresh={refreshAll} readiness={data.readiness.data} fleet={data.fleet.data} providers={data.providers.data} />
          ) : null}
          {activeScreen === 'endpoints' ? (
            <EndpointsScreen endpoints={data.endpoints.data?.items ?? []} isLoading={data.endpoints.isLoading} error={data.endpoints.error} onNavigate={navigate} onRefresh={refreshAll} ownerWallet={data.home.data?.bootstrap.owner_wallet?.wallet_id ?? ''} bundles={data.bundles.data?.items ?? []} bindings={data.providers.data?.runtime_bindings ?? []} />
          ) : null}
          {activeScreen === 'models' ? (
            <ModelsWorkspace installs={data.installs.data?.items ?? []} workspace={data.providers.data} isLoading={data.installs.isLoading || data.providers.isLoading} error={data.installs.error ?? data.providers.error} onRefresh={refreshAll} />
          ) : null}
          {activeScreen === 'settings' ? <SettingsWorkspace fleet={data.fleet.data} onRefresh={refreshAll} /> : null}
          {activeScreen === 'wallet' ? <WalletWorkspace wallet={data.wallet.data} isLoading={data.wallet.isLoading} error={data.wallet.error} onRefresh={refreshAll} /> : null}
          {activeScreen === 'providers' || activeScreen === 'catalog' ? (
            <ProviderWorkspaceScreen screen={activeScreen} workspace={data.providers.data} isLoading={data.providers.isLoading} error={data.providers.error} onRefresh={refreshAll} />
          ) : null}
          {isOperationsScreen(activeScreen) && activeScreen !== 'providers' && activeScreen !== 'catalog' && activeScreen !== 'wallet' && activeScreen !== 'models' ? (
            <OperationsWorkspace screen={activeScreen} data={data} onNavigate={navigate} onRefresh={refreshAll} />
          ) : null}
        </main>
      </div>

      <ResourceFooter fleet={data.fleet.data} isLoading={data.fleet.isLoading} onNavigate={navigate} />

      <AddHypervisorSheet
        open={addHypervisorOpen}
        onOpenChange={setAddHypervisorOpen}
        savedHypervisors={savedHypervisors}
        onAdded={(connection) => {
          const next = [connection, ...savedHypervisors.filter((item) => item.id !== connection.id)]
          saveSavedHypervisors(next)
          setSavedHypervisors(next)
          window.open(connection.url, '_blank', 'noopener,noreferrer')
        }}
      />

      <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
        <SheetTrigger className="hidden" />
        <SheetContent side="left" className="w-[280px] overflow-y-auto border-r-border bg-[#07111d] p-3">
          <Navigation
            activeScreen={activeScreen}
            advanced={advanced}
            readinessPercent={readinessPercent}
            onNavigate={navigate}
            onToggleAdvanced={() => setAdvanced(!advanced)}
          />
        </SheetContent>
      </Sheet>
    </div>
  )
}

type TopBarProps = {
  nodeName: string
  advanced: boolean
  isRefreshing: boolean
  refreshError: boolean
  refreshFeedback: RefreshFeedback
  onRefresh: () => void
  onToggleAdvanced: () => void
  onOpenNavigation: () => void
  onNavigate: (screen: DashboardScreen) => void
  savedHypervisors: SavedHypervisorConnection[]
  onAddHypervisor: () => void
  onRemoveHypervisor: (connection: SavedHypervisorConnection) => void
}

function TopBar({
  nodeName,
  advanced,
  isRefreshing,
  refreshError,
  refreshFeedback,
  onRefresh,
  onToggleAdvanced,
  onOpenNavigation,
  onNavigate,
  savedHypervisors,
  onAddHypervisor,
  onRemoveHypervisor,
}: TopBarProps) {
  return (
    <header className="sticky top-0 z-30 border-b border-border/80 bg-[#040a12]/95 backdrop-blur-xl">
      <div className="mx-auto flex h-16 w-full max-w-[1760px] items-center gap-3 px-3 lg:px-5">
        <Button
          aria-label="Open navigation"
          className="lg:hidden"
          variant="outline"
          size="icon"
          onClick={onOpenNavigation}
        >
          <Menu />
        </Button>
        <button type="button" aria-label="Open Hypervisor overview" className="flex shrink-0 items-center gap-2.5 font-semibold tracking-[-0.04em] text-white" onClick={() => onNavigate('overview')}>
          <span className="grid size-8 place-items-center rounded-[10px] bg-gradient-to-br from-cyan-300 via-cyan-400 to-blue-500 shadow-[0_0_24px_rgba(43,215,197,0.18)]">
            <Sparkles className="size-4 text-[#04101c]" strokeWidth={2.8} />
          </span>
          <span className="hidden text-lg sm:inline">AiDN</span>
        </button>
        <span className="hidden rounded-full border border-emerald-300/20 bg-emerald-300/10 px-2 py-1 font-mono text-[10px] font-semibold tracking-[0.12em] text-emerald-300 xl:inline">
          ONLINE
        </span>
        <Separator orientation="vertical" className="hidden h-6 bg-border/80 lg:block" />
        <div className="flex min-w-0 items-stretch gap-1 overflow-x-auto [scrollbar-width:none]">
          <button
            type="button"
            aria-label={`Open ${nodeName} overview`}
            className="relative shrink-0 border-x border-t border-border/70 bg-[#0a1725] px-3 py-2 text-left text-sm font-semibold text-cyan-200 after:absolute after:inset-x-3 after:bottom-0 after:h-0.5 after:bg-cyan-300 sm:px-4"
            onClick={() => onNavigate('overview')}
          >
            <span className="block max-w-44 truncate">{nodeName}</span>
            <span className="hidden text-[10px] font-medium uppercase tracking-[0.14em] text-muted-foreground sm:block">Local Hypervisor</span>
          </button>
          {savedHypervisors.map((connection) => (
            <div key={connection.id} className="group flex shrink-0 items-stretch border border-border/70 bg-[#071321]">
              <a
                href={connection.url}
                target="_blank"
                rel="noreferrer"
                className="flex min-w-0 items-center px-3 py-2 text-left text-sm font-medium text-slate-200 transition-colors hover:bg-cyan-300/[0.06] hover:text-cyan-100 sm:px-4"
                title={`Open ${connection.name} at ${connection.url}`}
              >
                <span className="block max-w-36 truncate">{connection.name}</span>
              </a>
              <button
                type="button"
                aria-label={`Remove ${connection.name} from this browser`}
                className="border-l border-border/70 px-2 text-xs text-slate-500 transition-colors hover:bg-rose-300/10 hover:text-rose-200"
                onClick={() => onRemoveHypervisor(connection)}
              >
                ×
              </button>
            </div>
          ))}
          <button
            type="button"
            aria-label="Add Hypervisor"
            className="flex shrink-0 items-center gap-1.5 border border-dashed border-cyan-300/30 px-3 text-xs font-medium text-cyan-100 transition-colors hover:border-cyan-200/70 hover:bg-cyan-300/[0.06] sm:px-4"
            onClick={onAddHypervisor}
          >
            <Plus className="size-3.5" />
            <span className="hidden sm:inline">Add Hypervisor</span>
          </button>
          <button type="button" className="hidden shrink-0 items-center gap-2 border border-dashed border-border/70 px-3 text-xs text-muted-foreground transition-colors hover:border-cyan-300/40 hover:text-cyan-100 md:flex" onClick={() => onNavigate('network')}>
            <Network className="size-3.5" />
            Remote discovery
          </button>
        </div>
        <div className="ml-auto flex shrink-0 items-center gap-1.5">
          <span aria-live="polite" className={cn('hidden max-w-64 truncate font-mono text-[10px] xl:block', refreshFeedback.state === 'error' ? 'text-amber-200' : refreshFeedback.state === 'running' ? 'text-cyan-200' : 'text-slate-500')}>
            {refreshFeedback.message}
          </span>
          <Tooltip>
            <TooltipTrigger render={<Button variant="ghost" size="icon" aria-label="Refresh dashboard" onClick={onRefresh} />}>
              <RefreshCw className={cn('size-4', isRefreshing && 'animate-spin', refreshError && 'text-amber-300')} />
            </TooltipTrigger>
            <TooltipContent>Refresh current Hypervisor state</TooltipContent>
          </Tooltip>
          <Button variant="outline" size="sm" className="hidden border-border bg-[#081523] text-foreground hover:bg-[#102438] sm:inline-flex" onClick={onToggleAdvanced}>
            <Layers3 />
            {advanced ? 'Basic mode' : 'Advanced mode'}
          </Button>
        </div>
      </div>
    </header>
  )
}

function AddHypervisorSheet({
  open,
  onOpenChange,
  savedHypervisors,
  onAdded,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  savedHypervisors: SavedHypervisorConnection[]
  onAdded: (connection: SavedHypervisorConnection) => void
}) {
  const [name, setName] = useState('')
  const [url, setUrl] = useState('')
  const [error, setError] = useState<string | null>(null)

  function add() {
    try {
      const connection = createSavedHypervisor(name, url)
      onAdded(connection)
      setError(null)
      setName('')
      setUrl('')
      onOpenChange(false)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Enter a valid Hypervisor dashboard URL.')
    }
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetTrigger className="hidden" />
      <SheetContent side="right" className="w-full overflow-y-auto border-l-border bg-[#07111d] p-0 sm:max-w-lg">
        <SheetHeader className="border-b border-border/70 px-5 py-5 pr-14">
          <p className="eyebrow text-cyan-200">Connected Hypervisors</p>
          <SheetTitle className="mt-1 text-xl font-semibold text-white">Add your Hypervisor</SheetTitle>
          <SheetDescription className="mt-2 leading-6 text-muted-foreground">Save another node in this browser and open its dashboard in a new tab. Each node keeps its own operator session and secrets.</SheetDescription>
        </SheetHeader>
        <div className="space-y-5 p-5">
          <div className="rounded-lg border border-cyan-300/20 bg-cyan-300/[0.05] p-4 text-sm leading-6 text-cyan-50/80">
            Pair the new node from its own <strong className="font-semibold text-cyan-100">Settings</strong> page. Do not paste the local operator token here and do not put credentials into the URL.
          </div>
          <label className="grid gap-2">
            <span className="eyebrow">Node name</span>
            <input value={name} onChange={(event) => setName(event.target.value)} placeholder="Hypervisor GPU-02" className="h-10 rounded-lg border border-input bg-[#040b13] px-3 text-sm text-white outline-none transition focus:border-cyan-300" />
          </label>
          <label className="grid gap-2">
            <span className="eyebrow">Dashboard URL</span>
            <input value={url} onChange={(event) => setUrl(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') add() }} inputMode="url" autoComplete="url" placeholder="http://192.168.88.128:8000" className="h-10 rounded-lg border border-input bg-[#040b13] px-3 font-mono text-xs text-white outline-none transition focus:border-cyan-300" />
            <span className="text-xs leading-5 text-muted-foreground">HTTP is suitable only for a controlled LAN. Use HTTPS outside the private network.</span>
          </label>
          {error ? <p role="alert" className="rounded-lg border border-rose-300/25 bg-rose-300/[0.06] px-3 py-2 text-sm leading-5 text-rose-100">{error}</p> : null}
          <div className="flex flex-col gap-2 sm:flex-row sm:justify-end">
            <Button variant="outline" className="border-border bg-[#091725]" onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button className="bg-cyan-300 text-[#06121d] hover:bg-cyan-200" disabled={!url.trim()} onClick={add}><Plus />Save and open</Button>
          </div>
          {savedHypervisors.length > 0 ? <div className="border-t border-border/70 pt-5"><p className="eyebrow">Saved in this browser</p><div className="mt-3 space-y-2">{savedHypervisors.map((connection) => <div key={connection.id} className="rounded-lg border border-border/70 bg-[#040b13] px-3 py-2"><p className="truncate text-sm font-medium text-slate-200">{connection.name}</p><p className="truncate font-mono text-[11px] text-slate-500">{connection.url}</p></div>)}</div></div> : null}
        </div>
      </SheetContent>
    </Sheet>
  )
}

type NavigationProps = {
  activeScreen: DashboardScreen
  advanced: boolean
  readinessPercent: number
  onNavigate: (screen: DashboardScreen) => void
  onToggleAdvanced: () => void
}

function Navigation({ activeScreen, advanced, readinessPercent, onNavigate, onToggleAdvanced }: NavigationProps) {
  const items = advanced ? [...navigationItems, ...advancedItems] : navigationItems.filter((item) => !item.advanced)

  return (
    <nav className="operator-panel flex min-h-[calc(100svh-104px)] flex-col p-2 lg:sticky lg:top-[76px]">
      <div className="mb-3 px-2 pt-2">
        <p className="eyebrow">Control Plane</p>
        <p className="mt-1 text-xs leading-5 text-muted-foreground">Bundle-first operations for this Hypervisor.</p>
      </div>
      <div className="space-y-1">
        {items.map((item, index) => {
          const Icon = item.icon
          const isCurrent = item.id === activeScreen
          return (
            <Tooltip key={`${item.label}-${index}`}>
              <TooltipTrigger
                render={
                  <button
                    type="button"
                    aria-current={isCurrent ? 'page' : undefined}
                    className={cn(
                      'group flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm font-medium transition-colors',
                      isCurrent
                        ? 'bg-cyan-300/10 text-cyan-100 shadow-[inset_2px_0_0_0_#2bd7c5]'
                        : 'text-slate-300 hover:bg-white/[0.045] hover:text-white',
                    )}
                    onClick={() => onNavigate(item.id)}
                  />
                }
              >
                <Icon className={cn('size-4 shrink-0', isCurrent ? 'text-cyan-300' : 'text-slate-400 group-hover:text-slate-200')} />
                <span>{item.label}</span>
              </TooltipTrigger>
              <TooltipContent side="right">Open {item.label}</TooltipContent>
            </Tooltip>
          )
        })}
      </div>
      <div className="mt-auto space-y-3 px-1 pb-1 pt-5">
        <div className="rounded-lg border border-border/80 bg-black/10 p-3">
          <div className="flex items-center justify-between gap-2">
            <span className="eyebrow">Readiness</span>
            <span className="font-mono text-xs font-semibold text-cyan-200">{formatPercent(readinessPercent)}</span>
          </div>
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-white/8">
            <div className="h-full rounded-full bg-gradient-to-r from-blue-400 to-cyan-300" style={{ width: `${Math.min(100, Math.max(0, readinessPercent))}%` }} />
          </div>
        </div>
        <Button variant="outline" className="w-full border-border bg-transparent text-slate-200 hover:bg-white/[0.05]" onClick={onToggleAdvanced}>
          <ServerCog />
          {advanced ? 'Switch to Basic' : 'Switch to Advanced'}
        </Button>
      </div>
    </nav>
  )
}

type DashboardData = ReturnType<typeof useDashboardData>

function OverviewScreen({ data, onNavigate, onRefresh }: { data: DashboardData; onNavigate: NavigationProps['onNavigate']; onRefresh: () => void }) {
  const bundles = data.bundles.data?.items ?? []
  const endpoints = data.endpoints.data?.items ?? []
  const readiness = data.readiness.data
  const fleet = data.fleet.data
  const home = data.home.data
  const wallet = home?.bootstrap.owner_wallet
  const nodeIdentity = home?.bootstrap.node_identity ?? fleet?.node
  const nodeName = getText(nodeIdentity, 'node_id') || 'Local Hypervisor'
  const publishedCount = data.endpoints.data?.summary.published ?? endpoints.filter((endpoint) => endpoint.publication_status === 'published').length
  const activeSessions = data.sessions.data?.summary.active ?? fleet?.queue.active ?? 0
  const queuedSessions = data.sessions.data?.summary.queued ?? fleet?.queue.queued ?? 0
  const validationSummary = summarizeValidation(endpoints)

  return (
    <div className="space-y-4 lg:space-y-5">
      <section className="flex flex-col justify-between gap-4 border-b border-border/75 pb-4 sm:flex-row sm:items-end">
        <div>
          <h1 className="text-2xl font-semibold tracking-[-0.045em] text-white sm:text-3xl">Overview</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">{nodeName} at a glance: current execution, capacity, network evidence, and the next safe operator action.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <SmallInfo label="Node" value={nodeName} />
          <SmallInfo label="Refresh" value={data.home.isFetching || data.events.isFetching ? 'Updating' : 'Live'} tone={data.home.isFetching || data.events.isFetching ? 'warn' : 'good'} />
          <Button variant="outline" size="sm" className="border-border bg-[#091725]" onClick={onRefresh}>
            <RefreshCw className={cn('size-3.5', (data.home.isFetching || data.events.isFetching) && 'animate-spin')} />
            Refresh all
          </Button>
        </div>
      </section>

      <NodeStatusStrip readiness={readiness} fleet={fleet} market={data.market.data} endpoints={data.endpoints.data} isLoading={data.readiness.isLoading || data.fleet.isLoading} />

      <AttentionRequired readiness={readiness} readinessError={data.readiness.error} onNavigate={onNavigate} onRefresh={onRefresh} />

      <section className="grid grid-cols-2 gap-3 xl:grid-cols-5">
        <MetricCard label="Active Bundles" value={formatCount(bundles.filter((bundle) => bundle.enabled).length)} detail={`${bundles.length} registered · open inventory`} icon={Boxes} tone="cyan" loading={data.bundles.isLoading} onClick={() => onNavigate('bundles')} />
        <MetricCard label="Published Endpoints" value={formatCount(publishedCount)} detail={`${endpoints.length} configured · open offers`} icon={RadioTower} tone="blue" loading={data.endpoints.isLoading} onClick={() => onNavigate('endpoints')} />
        <MetricCard label="Running Sessions" value={formatCount(activeSessions)} detail={`${queuedSessions} queued · open queue`} icon={Activity} tone="violet" loading={data.sessions.isLoading || data.fleet.isLoading} onClick={() => onNavigate('agents')} />
        <MetricCard label="Wallet" value={wallet?.configured ? 'Bound' : 'Setup'} detail={wallet?.configured ? shortId(wallet.wallet_id) : 'Action required · open Wallet'} icon={WalletCards} tone={wallet?.configured ? 'green' : 'amber'} loading={data.home.isLoading} onClick={() => onNavigate('wallet')} />
        <MetricCard label="Readiness" value={readiness ? formatPercent(readiness.progress.percent) : '—'} detail={readiness?.overall_state ?? 'Status unavailable'} icon={ShieldCheck} tone={readiness?.overall_state === 'ready' ? 'green' : 'amber'} loading={data.readiness.isLoading} onClick={() => onNavigate('network')} />
      </section>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_296px]">
        <div className="min-w-0 space-y-4">
          <BundleTableSection bundles={bundles} isLoading={data.bundles.isLoading} error={data.bundles.error} onNavigate={onNavigate} compact />
          <SessionQueueOverview sessions={data.sessions.data} isLoading={data.sessions.isLoading} error={data.sessions.error} onNavigate={onNavigate} />
          <RecentOperations events={data.events.data ?? []} isLoading={data.events.isLoading} error={data.events.error} onNavigate={onNavigate} onRefresh={onRefresh} />
        </div>
        <aside className="space-y-4">
          <ResourceOverview fleet={fleet} isLoading={data.fleet.isLoading} error={data.fleet.error} onNavigate={onNavigate} />
          <NetworkValidationOverview readiness={readiness} market={data.market.data} remoteEndpoints={data.remoteEndpoints.data} validation={validationSummary} onNavigate={onNavigate} />
          <SystemState fleet={fleet} home={home} isLoading={data.fleet.isLoading || data.home.isLoading} />
        </aside>
      </div>

      <ReadinessWizard readiness={readiness} isLoading={data.readiness.isLoading} error={data.readiness.error} onNavigate={onNavigate} onRefresh={onRefresh} />
    </div>
  )
}

function NodeStatusStrip({ readiness, fleet, market, endpoints, isLoading }: { readiness: DashboardData['readiness']['data']; fleet: DashboardData['fleet']['data']; market: DashboardData['market']['data']; endpoints: DashboardData['endpoints']['data']; isLoading: boolean }) {
  const discovery = market ? `${formatCount(market.nodes.length)} node${market.nodes.length === 1 ? '' : 's'}` : 'Unknown'
  const assurance = endpoints ? `${formatCount(endpoints.summary.published)} published` : 'Unknown'
  return (
    <section className="grid gap-px overflow-hidden rounded-xl border border-border/80 bg-border/60 sm:grid-cols-2 xl:grid-cols-4">
      <StatusSignal label="Hypervisor inventory" value={isLoading && !fleet ? 'Checking' : fleet ? 'Ready' : 'Unknown'} detail={fleet ? 'capacity read model available' : 'fleet read model unavailable'} tone={fleet ? 'good' : 'muted'} />
      <StatusSignal label="Consensus readiness" value={readiness ? readiness.network_ready ? 'Ready' : 'Blocked' : 'Unknown'} detail={readiness ? 'reported by readiness checks' : 'readiness evidence unavailable'} tone={readiness?.network_ready ? 'good' : readiness ? 'bad' : 'muted'} />
      <StatusSignal label="Execution readiness" value={readiness ? readiness.execution_ready ? 'Ready' : 'Review' : 'Unknown'} detail={readiness ? 'provider and runtime gate' : 'readiness evidence unavailable'} tone={readiness?.execution_ready ? 'good' : readiness ? 'warn' : 'muted'} />
      <StatusSignal label="Discovery / assurance" value={`${discovery} · ${assurance}`} detail="current local read models" tone={market && endpoints ? 'good' : 'muted'} />
    </section>
  )
}

function StatusSignal({ label, value, detail, tone }: { label: string; value: string; detail: string; tone: 'good' | 'warn' | 'bad' | 'muted' }) {
  const dot = tone === 'good' ? 'bg-emerald-300' : tone === 'warn' ? 'bg-amber-300' : tone === 'bad' ? 'bg-rose-300' : 'bg-slate-500'
  const text = tone === 'good' ? 'text-emerald-300' : tone === 'warn' ? 'text-amber-200' : tone === 'bad' ? 'text-rose-200' : 'text-slate-300'
  return <div className="bg-[#081522] px-4 py-3.5"><div className="flex items-center gap-2"><span className={cn('size-2 rounded-full', dot)} /><p className="text-xs font-semibold text-slate-200">{label}</p></div><p className={cn('mt-2 font-mono text-sm font-semibold', text)}>{value}</p><p className="mt-1 text-[11px] leading-4 text-muted-foreground">{detail}</p></div>
}

function AttentionRequired({ readiness, readinessError, onNavigate, onRefresh }: { readiness: DashboardData['readiness']['data']; readinessError: Error | null; onNavigate: NavigationProps['onNavigate']; onRefresh: () => void }) {
  if (readinessError && !readiness) {
    return <PanelError title="Next action is unavailable" detail="Readiness checks did not return. Refresh to recover the operator path; no mutation was attempted." error={readinessError} onRetry={onRefresh} />
  }
  const ready = readiness?.overall_state.toLowerCase() === 'ready' && readiness.execution_ready && readiness.network_ready
  const action = readiness?.next_action
  return (
    <Card className={cn('border-border/80 py-0 shadow-none', ready ? 'bg-emerald-300/[0.035]' : 'border-amber-300/25 bg-amber-300/[0.045]')}>
      <CardContent className="flex flex-col gap-4 p-4 sm:flex-row sm:items-center sm:justify-between sm:p-5">
        <div className="flex min-w-0 gap-3">
          <span className={cn('mt-0.5 grid size-9 shrink-0 place-items-center rounded-lg', ready ? 'bg-emerald-300/10 text-emerald-300' : 'bg-amber-300/10 text-amber-200')}><ShieldCheck className="size-4" /></span>
          <div className="min-w-0"><p className="text-xs font-semibold uppercase tracking-[0.12em] text-slate-400">{ready ? 'No blocking action reported' : 'Attention required'}</p><p className="mt-1 font-semibold text-white">{ready ? 'The node passed the current readiness gate.' : action?.label || 'Review readiness checks'}</p><p className="mt-1 max-w-3xl text-xs leading-5 text-muted-foreground">{ready ? 'Use the workspaces below to inspect active objects, capacity, and recent evidence.' : action?.detail || 'The readiness read model did not provide a next safe action.'}</p></div>
        </div>
        {!ready && action ? <ReadinessAction action={action} onNavigate={onNavigate} onRefresh={onRefresh} /> : <Button variant="outline" size="sm" className="shrink-0 border-emerald-300/25 bg-transparent text-emerald-100 hover:bg-emerald-300/10" onClick={() => onNavigate('network')}>Open readiness<ChevronRight /></Button>}
      </CardContent>
    </Card>
  )
}

function SessionQueueOverview({ sessions, isLoading, error, onNavigate }: { sessions: DashboardData['sessions']['data']; isLoading: boolean; error: Error | null; onNavigate: NavigationProps['onNavigate'] }) {
  if (isLoading && !sessions) return <PanelSkeleton rows={3} />
  if (error && !sessions) return <PanelError title="Session queue is unavailable" error={error} />
  const items = sessions?.items ?? []
  return <Card className="border-border/80 bg-card py-0 shadow-none"><CardHeader className="flex-row items-center justify-between gap-3 border-b border-border/75 px-5 py-4"><div><p className="text-xs font-semibold uppercase tracking-[0.12em] text-slate-400">Execution pressure</p><CardTitle className="mt-1 text-lg font-semibold tracking-[-0.03em]">Sessions and queue</CardTitle><p className="mt-1 text-sm text-muted-foreground">{sessions?.summary.active ?? 0} active · {sessions?.summary.queued ?? 0} queued · {sessions?.summary.closed ?? 0} closed</p></div><Button variant="ghost" size="sm" className="text-cyan-200 hover:bg-cyan-300/10 hover:text-cyan-100" onClick={() => onNavigate('agents')}>Open Agents<ChevronRight /></Button></CardHeader><CardContent className="divide-y divide-border/70 p-0">{items.length === 0 ? <EmptyState title="No Sessions in the local ledger" detail="Published Endpoints will create Session records when Consumers submit work. This is an empty state, not a failed refresh." actionLabel="Review Endpoints" onAction={() => onNavigate('endpoints')} /> : items.slice(0, 4).map((item, index) => { const session = getRecord(item.session); const id = getText(session, 'session_id') || `session-${index + 1}`; const status = getText(session, 'status') || 'unknown'; return <button type="button" key={id} className="flex w-full items-center gap-3 px-5 py-4 text-left transition-colors hover:bg-white/[0.025] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-cyan-300/70" onClick={() => onNavigate('agents')}><span className="grid size-8 shrink-0 place-items-center rounded-lg bg-violet-300/10 text-violet-200"><Activity className="size-4" /></span><span className="min-w-0 flex-1"><span className="flex flex-wrap items-center gap-2"><span className="truncate text-sm font-medium text-slate-100">{getText(item, 'display_name') || getText(session, 'endpoint_id') || 'Endpoint Session'}</span><StatusBadge value={status} /></span><span className="mt-1 block truncate font-mono text-[11px] text-slate-500">{id} · {getText(session, 'request_count') || '0'} request(s)</span></span><ChevronRight className="size-4 shrink-0 text-slate-500" /></button> })}</CardContent></Card>
}

function RecentOperations({ events, isLoading, error, onNavigate, onRefresh }: { events: NonNullable<DashboardData['events']['data']>; isLoading: boolean; error: Error | null; onNavigate: NavigationProps['onNavigate']; onRefresh: () => void }) {
  if (isLoading && events.length === 0) return <PanelSkeleton rows={3} />
  if (error && events.length === 0) return <PanelError title="Recent operations are unavailable" error={error} onRetry={onRefresh} />
  return <Card className="border-border/80 bg-card py-0 shadow-none"><CardHeader className="flex-row items-center justify-between gap-3 border-b border-border/75 px-5 py-4"><div><p className="text-xs font-semibold uppercase tracking-[0.12em] text-slate-400">Evidence journal</p><CardTitle className="mt-1 text-lg font-semibold tracking-[-0.03em]">Recent operations</CardTitle></div><Button variant="ghost" size="sm" className="text-cyan-200 hover:bg-cyan-300/10 hover:text-cyan-100" onClick={() => onNavigate('network')}>Open diagnostics<ChevronRight /></Button></CardHeader><CardContent className="divide-y divide-border/70 p-0">{events.length === 0 ? <EmptyState title="No recent operations recorded" detail="The Hypervisor event journal is empty. The dashboard will not manufacture activity entries." actionLabel="Refresh journal" onAction={onRefresh} /> : events.slice().reverse().slice(0, 5).map((event, index) => { const targetScreen: DashboardScreen = event.bundle_id ? 'bundles' : event.task_id ? 'agents' : 'network'; const target = event.bundle_id || event.task_id; return <button type="button" key={`${event.timestamp}:${event.event_type}:${target ?? index}`} className="flex w-full items-start gap-3 px-5 py-3.5 text-left transition-colors hover:bg-white/[0.025] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-cyan-300/70" onClick={() => onNavigate(targetScreen)}><span className="mt-0.5 grid size-7 shrink-0 place-items-center rounded-md bg-cyan-300/8 text-cyan-200"><Activity className="size-3.5" /></span><span className="min-w-0 flex-1"><span className="flex flex-wrap items-center justify-between gap-2"><span className="font-mono text-[10px] font-semibold uppercase tracking-[0.1em] text-cyan-100/70">{event.event_type}</span><span className="text-[10px] text-slate-500">{formatTimestamp(event.timestamp)}</span></span><span className="mt-1 block truncate text-xs text-slate-200">{event.message || 'Operation recorded'}</span>{target ? <span className="mt-1 block truncate font-mono text-[10px] text-slate-500">{target}</span> : null}</span><ChevronRight className="mt-1 size-3.5 shrink-0 text-slate-600" /></button> })}</CardContent></Card>
}

function NetworkValidationOverview({ readiness, market, remoteEndpoints, validation, onNavigate }: { readiness: DashboardData['readiness']['data']; market: DashboardData['market']['data']; remoteEndpoints: DashboardData['remoteEndpoints']['data']; validation: ReturnType<typeof summarizeValidation>; onNavigate: NavigationProps['onNavigate'] }) {
  return <Card className="border-border/80 bg-card py-0 shadow-none"><CardHeader className="px-4 py-4"><CardTitle className="text-base font-semibold">Network and assurance</CardTitle><p className="mt-1 text-xs leading-5 text-muted-foreground">Evidence is split between readiness, discovery, and Endpoint validation.</p></CardHeader><CardContent className="space-y-3 px-4 pb-4"><button type="button" className="flex w-full items-center gap-3 rounded-lg border border-border/70 bg-black/10 p-3 text-left transition-colors hover:border-cyan-300/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300/70" onClick={() => onNavigate('network')}><span className="grid size-7 place-items-center rounded-md bg-sky-300/10 text-sky-200"><Network className="size-3.5" /></span><span className="min-w-0 flex-1"><span className="block text-xs font-semibold text-slate-100">Consensus / discovery</span><span className="mt-1 block text-[11px] text-muted-foreground">{readiness ? readiness.network_ready ? 'Readiness reports network-ready' : 'Readiness reports a network blocker' : 'No readiness evidence'} · {market ? `${market.nodes.length} visible nodes` : 'discovery unavailable'} · {remoteEndpoints ? `${remoteEndpoints.summary.attached} attached remote` : 'remote inventory unavailable'}</span></span><ChevronRight className="size-3.5 text-slate-500" /></button><button type="button" className="flex w-full items-center gap-3 rounded-lg border border-border/70 bg-black/10 p-3 text-left transition-colors hover:border-cyan-300/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300/70" onClick={() => onNavigate('validation')}><span className="grid size-7 place-items-center rounded-md bg-emerald-300/10 text-emerald-200"><ShieldCheck className="size-3.5" /></span><span className="min-w-0 flex-1"><span className="block text-xs font-semibold text-slate-100">Endpoint validation</span><span className="mt-1 block text-[11px] text-muted-foreground">{validation.verified} verified · {validation.pending} pending · {validation.unvalidated} without validation evidence</span></span><ChevronRight className="size-3.5 text-slate-500" /></button></CardContent></Card>
}

function formatTimestamp(value: string): string {
  if (!value) return 'time unavailable'
  const timestamp = new Date(value)
  if (Number.isNaN(timestamp.getTime())) return value
  return new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit' }).format(timestamp)
}

function SmallInfo({ label, value, tone = 'muted' }: { label: string; value: string; tone?: 'good' | 'warn' | 'muted' }) {
  const toneClass = tone === 'good' ? 'text-emerald-300' : tone === 'warn' ? 'text-amber-200' : 'text-slate-200'
  return (
    <div className="rounded-md border border-border/75 bg-[#081422] px-2.5 py-1.5">
      <span className="mr-1.5 font-mono text-[9px] font-semibold uppercase tracking-[0.13em] text-slate-500">{label}</span>
      <span className={cn('text-xs font-semibold', toneClass)}>{value}</span>
    </div>
  )
}

function MetricCard({ label, value, detail, icon: Icon, tone, loading, onClick }: { label: string; value: string; detail: string; icon: LucideIcon; tone: 'cyan' | 'blue' | 'violet' | 'green' | 'amber'; loading: boolean; onClick: () => void }) {
  const color = {
    cyan: 'text-cyan-300 bg-cyan-300/10',
    blue: 'text-sky-300 bg-sky-300/10',
    violet: 'text-violet-300 bg-violet-300/10',
    green: 'text-emerald-300 bg-emerald-300/10',
    amber: 'text-amber-200 bg-amber-300/10',
  }[tone]
  return (
    <Card className="min-h-32 border-border/80 bg-card py-0 shadow-none transition-colors hover:border-cyan-300/35" size="sm">
      <button type="button" className="flex h-full w-full flex-col p-4 text-left outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-cyan-300/70" onClick={onClick}>
        <div className="flex items-start justify-between gap-2">
          <p className="eyebrow">{label}</p>
          <span className={cn('grid size-8 place-items-center rounded-lg', color)}><Icon className="size-4" /></span>
        </div>
        {loading ? <Skeleton className="mt-4 h-8 w-16 bg-white/8" /> : <p className="mt-3 text-2xl font-semibold tracking-[-0.05em] text-white">{value}</p>}
        <p className="mt-auto flex w-full items-center justify-between gap-2 pt-1 text-xs text-muted-foreground"><span>{detail}</span><ChevronRight className="size-3.5 text-cyan-200/70" /></p>
      </button>
    </Card>
  )
}

function ReadinessWizard({ readiness, isLoading, error, onNavigate, onRefresh }: { readiness: DashboardData['readiness']['data']; isLoading: boolean; error: Error | null; onNavigate: NavigationProps['onNavigate']; onRefresh: () => void }) {
  if (isLoading && !readiness) {
    return <PanelSkeleton rows={5} />
  }
  if (error && !readiness) {
    return <PanelError title="Readiness is unavailable" error={error} onRetry={onRefresh} />
  }
  if (!readiness) {
    return <PanelError title="Readiness data has not arrived" detail="Refresh the dashboard to run the operator checks." onRetry={onRefresh} />
  }

  const nextAction = readiness.next_action
  return (
    <Card className="border-border/80 bg-card py-0 shadow-none">
      <CardHeader className="border-b border-border/75 px-5 py-4">
        <div>
          <p className="eyebrow">Operator setup</p>
          <CardTitle className="mt-1 text-lg font-semibold tracking-[-0.03em]">Readiness Wizard</CardTitle>
          <p className="mt-1 text-sm text-muted-foreground">A single preflight path from host prerequisites to an externally usable Bundle.</p>
        </div>
        <div className="text-right">
          <p className="font-mono text-2xl font-semibold tracking-[-0.06em] text-cyan-200">{formatPercent(readiness.progress.percent)}</p>
          <p className="text-xs text-muted-foreground">{readiness.progress.ready} of {readiness.progress.total} checks ready</p>
        </div>
      </CardHeader>
      <CardContent className="p-5">
        <div className="rounded-lg border border-cyan-300/20 bg-cyan-300/[0.045] p-3.5 sm:flex sm:items-center sm:justify-between sm:gap-4">
          <div>
            <p className="eyebrow text-cyan-100/75">Next safe action</p>
            <p className="mt-1 font-semibold text-white">{nextAction.label}</p>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">{nextAction.detail}</p>
          </div>
          <ReadinessAction action={nextAction} onNavigate={onNavigate} onRefresh={onRefresh} />
        </div>
        <div className="mt-4 grid gap-2">
          {readiness.steps.map((step) => <ReadinessStepRow key={step.key} step={step} onNavigate={onNavigate} onRefresh={onRefresh} />)}
        </div>
      </CardContent>
    </Card>
  )
}

function ReadinessAction({ action, onNavigate, onRefresh }: { action: { kind: string; label: string; detail: string; screen?: string } | undefined; onNavigate: NavigationProps['onNavigate']; onRefresh: () => void }) {
  if (!action) return null
  if (action.kind === 'refresh') {
    return <Button size="sm" variant="outline" className="mt-3 border-cyan-300/25 bg-transparent text-cyan-100 hover:bg-cyan-300/10 sm:mt-0" onClick={onRefresh}><RefreshCw />{action.label}</Button>
  }
  return <Button size="sm" className="mt-3 bg-cyan-300 text-[#06121d] hover:bg-cyan-200 sm:mt-0" onClick={() => onNavigate(readinessActionScreen(action))}>{action.label}<ChevronRight /></Button>
}

function readinessActionScreen(action: { screen?: string; label: string; detail: string }): DashboardScreen {
  const value = `${action.screen ?? ''} ${action.label} ${action.detail}`.toLowerCase()
  if (value.includes('wallet')) return 'wallet'
  if (value.includes('resource') || value.includes('capacity')) return 'settings'
  if (value.includes('consensus') || value.includes('network') || value.includes('cometbft')) return 'network'
  if (value.includes('provider') || value.includes('install')) return 'providers'
  if (value.includes('model')) return 'models'
  if (value.includes('validation')) return 'validation'
  if (value.includes('endpoint')) return 'endpoints'
  if (value.includes('bundle')) return 'bundles'
  if (value.includes('market')) return 'market'
  return 'overview'
}

function ReadinessStepRow({ step, onNavigate, onRefresh }: { step: ReadinessStep; onNavigate: NavigationProps['onNavigate']; onRefresh: () => void }) {
  const icon = step.status === 'ready' ? <CheckCircle2 className="size-4 text-emerald-300" /> : step.status === 'blocked' ? <XCircle className="size-4 text-rose-300" /> : <CircleDot className="size-4 text-amber-200" />
  return (
    <div className="rounded-lg border border-border/70 bg-black/10 p-3.5">
      <div className="flex gap-3">
        <span className="mt-0.5 shrink-0">{icon}</span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm font-semibold text-slate-100">{step.title}</p>
            <StatusBadge value={step.status} />
          </div>
          <p className="mt-1 text-xs leading-5 text-slate-300">{step.summary}</p>
          <p className="mt-0.5 text-xs leading-5 text-muted-foreground">{step.detail}</p>
          {step.action ? <div className="mt-2"><ReadinessAction action={step.action} onNavigate={onNavigate} onRefresh={onRefresh} /></div> : null}
        </div>
      </div>
    </div>
  )
}

function BundleTableSection({ bundles, isLoading, error, onNavigate, compact = false, onAction, onSelect }: { bundles: Bundle[]; isLoading: boolean; error: Error | null; onNavigate: NavigationProps['onNavigate']; compact?: boolean; onAction?: (bundle: Bundle, action: BundleAction) => void; onSelect?: (bundle: Bundle) => void }) {
  return (
    <Card className="border-border/80 bg-card py-0 shadow-none">
      <CardHeader className="border-b border-border/75 px-5 py-4">
        <div>
          <p className="eyebrow">Deployment inventory</p>
          <CardTitle className="mt-1 text-lg font-semibold tracking-[-0.03em]">{compact ? 'Active Bundles' : 'Bundles'}</CardTitle>
        </div>
        <Button variant="ghost" size="sm" className="text-cyan-200 hover:bg-cyan-300/10 hover:text-cyan-100" onClick={() => onNavigate('bundles')}>
          {compact ? 'View all' : 'Bundle workflow'}<ChevronRight />
        </Button>
      </CardHeader>
      <CardContent className="p-0">
        {isLoading && bundles.length === 0 ? <TableSkeleton columns={6} rows={compact ? 3 : 6} /> : null}
        {error && bundles.length === 0 ? <PanelError title="Bundle inventory is unavailable" error={error} /> : null}
        {!isLoading && !error && bundles.length === 0 ? <EmptyState title="No Bundle deployments are registered" detail="Start in Catalog to inspect Provider capacity, then create an immutable Bundle revision." actionLabel="Open Catalog" onAction={() => onNavigate('catalog')} /> : null}
        {bundles.length > 0 ? <BundleTable bundles={bundles} onNavigate={onNavigate} onAction={onAction} onSelect={onSelect} compact={compact} /> : null}
      </CardContent>
    </Card>
  )
}

type BundleAction = 'enable' | 'disable' | 'retry' | 'reset-cooldown'

function BundleTable({ bundles, onNavigate, onAction, onSelect, compact = false }: { bundles: Bundle[]; onNavigate: NavigationProps['onNavigate']; onAction?: (bundle: Bundle, action: BundleAction) => void; onSelect?: (bundle: Bundle) => void; compact?: boolean }) {
  const columns: ColumnDef<Bundle>[] = [
    {
      accessorKey: 'bundle_id',
      header: 'Bundle',
      cell: ({ row }) => <button type="button" className="rounded-md text-left outline-none focus-visible:ring-2 focus-visible:ring-cyan-300/70" aria-label={`Inspect Bundle ${row.original.bundle_id}`} onClick={() => onSelect ? onSelect(row.original) : onNavigate('bundles')}><p className="font-medium text-slate-100 transition-colors hover:text-cyan-200">{shortId(row.original.bundle_id, 20)}</p><p className="mt-0.5 font-mono text-[10px] text-slate-500">r{String(getRecord(row.original)?.revision ?? 1)} Â· {shortId(getText(row.original, 'bundle_hash'), 18)}</p></button>,
    },
    { accessorKey: 'provider_type', header: 'Provider', cell: ({ row }) => <div><span className="font-mono text-xs text-slate-300">{row.original.provider_type}</span><p className="mt-1 text-[10px] text-slate-500">{shortId(row.original.plugin_id, 20)}</p></div> },
    { accessorKey: 'model_id', header: 'Model', cell: ({ row }) => <div><span className="text-xs text-slate-200">{row.original.model_id}</span><p className="mt-1 text-[10px] text-slate-500">{row.original.workload_type || 'workload not reported'}</p></div> },
    { accessorKey: 'runtime_status', header: 'Runtime', cell: ({ row }) => <StatusBadge value={row.original.runtime_status} /> },
    ...(!compact ? [{ id: 'resources', header: 'Resources', cell: ({ row }: { row: { original: Bundle } }) => { const required = bundleRequiredResources(row.original); return <div className="min-w-[120px] text-xs text-slate-300"><p>{required.cpu.toFixed(1)} CPU Â· {formatMemory(required.ram_mb)}</p><p className="mt-1 text-[10px] text-slate-500">VRAM {formatMemory(required.vram_mb)}</p></div> } }] satisfies ColumnDef<Bundle>[] : []),
    { accessorKey: 'publish_status', header: 'Publication', cell: ({ row }) => <div><StatusBadge value={row.original.publish_status} /><p className="mt-1 text-[10px] text-slate-500">{bundleEndpointState(row.original).replaceAll('_', ' ')}</p></div> },
    {
      id: 'endpoint',
      header: '',
      cell: ({ row }) => row.original.endpoint_relationship?.state === 'published_endpoint' ? <Button variant="ghost" size="sm" className="text-cyan-200 hover:bg-cyan-300/10" onClick={() => onNavigate('endpoints')}>Endpoint<ChevronRight /></Button> : <span className="text-xs text-muted-foreground">No Endpoint</span>,
    },
    ...(onAction ? [{
      id: 'controls',
      header: 'Controls',
      cell: ({ row }: { row: { original: Bundle } }) => { const record = getRecord(row.original); const failed = ['failed', 'error', 'cooldown'].includes(bundleLifecycleStatus(row.original)); const hasCooldown = Boolean(valueText(record, 'cooldown_until')); return <div className="flex flex-wrap gap-1.5"><Button variant="outline" size="xs" className="border-border bg-[#091725]" disabled={row.original.enabled && bundleLifecycleStatus(row.original) === 'running'} onClick={() => onAction(row.original, row.original.enabled ? 'disable' : 'enable')}>{row.original.enabled ? 'Pause' : 'Enable'}</Button><Button variant="outline" size="xs" className="border-cyan-300/25 bg-[#091725] text-cyan-100" disabled={!failed} onClick={() => onAction(row.original, 'retry')}>Retry</Button><Button variant="ghost" size="xs" className="text-slate-300" disabled={!hasCooldown} onClick={() => onAction(row.original, 'reset-cooldown')}>Reset</Button></div> },
    }] satisfies ColumnDef<Bundle>[] : []),
  ]
  const table = useReactTable({ data: bundles, columns, getCoreRowModel: getCoreRowModel() })
  return <DataTable table={table} />
}

type BundlePreflightState = 'ready' | 'blocked' | 'unknown' | 'info'

type BundlePreflightCheck = {
  key: string
  label: string
  state: BundlePreflightState
  detail: string
}

function bundleEndpointState(bundle: Bundle): string {
  const state = getText(getRecord(bundle)?.endpoint_relationship, 'state')
  return state || (bundle.endpoint ? 'draft_endpoint' : 'no_endpoint')
}

function bundleLifecycleStatus(bundle: Bundle): string {
  const record = getRecord(bundle)
  const runtime = normalizeStatus(valueText(record, 'runtime_status') || 'stopped')
  const inventory = normalizeStatus(valueText(record, 'inventory_status'))
  if (!bundle.enabled) return 'paused'
  if (['failed', 'error', 'unhealthy'].includes(runtime) || ['failed', 'error', 'unhealthy'].includes(inventory)) return 'failed'
  if (valueText(record, 'cooldown_until')) return 'cooldown'
  if (['running', 'ready', 'healthy', 'active'].includes(runtime)) return 'running'
  return runtime || 'unknown'
}

function bundleRequiredResources(bundle: Bundle): { cpu: number; ram_mb: number; vram_mb: number } {
  const record = getRecord(bundle)
  const profile = getRecord(record?.resource_profile)
  const runtime = normalizeStatus(valueText(record, 'runtime_status'))
  const warm = ['running', 'ready', 'healthy', 'active'].includes(runtime)
  const prefix = warm ? 'steady' : 'cold_start'
  return {
    cpu: numberValue(profile, `${prefix}_cpu`) + numberValue(profile, 'per_request_cpu'),
    ram_mb: numberValue(profile, `${prefix}_ram_mb`) + numberValue(profile, 'per_request_ram_mb'),
    vram_mb: numberValue(profile, `${prefix}_vram_mb`) + numberValue(profile, 'per_request_vram_mb'),
  }
}

function readinessState(readiness: Readiness | undefined, key: string): BundlePreflightState {
  const step = readiness?.steps.find((candidate) => candidate.key === key)
  if (!step) return 'unknown'
  if (step.status === 'ready') return 'ready'
  if (step.status === 'blocked') return 'blocked'
  return 'unknown'
}

function bundlePreflightChecks(bundle: Bundle, readiness?: Readiness, fleet?: Fleet, providers?: ProviderWorkspace): BundlePreflightCheck[] {
  const record = getRecord(bundle)
  const pluginId = valueText(record, 'plugin_id')
  const providerType = valueText(record, 'provider_type')
  const modelId = valueText(record, 'model_id')
  const providerStep = readinessState(readiness, 'provider')
  const modelStep = readinessState(readiness, 'model_deployment')
  const bindingStep = readinessState(readiness, 'runtime_binding')
  const provider = providers?.provider_instances.find((item) => valueText(item, 'plugin_id') === pluginId || valueText(item, 'provider_type') === providerType)
  const providerHealthy = provider ? ['ready', 'healthy', 'operational', 'running'].includes(normalizeStatus(valueText(provider, 'health_status') || valueText(provider, 'operational_state'))) : false
  const deployment = providers?.model_deployments.find((item) => valueText(item, 'model_id') === modelId && (!pluginId || valueText(item, 'plugin_id') === pluginId || valueText(item, 'provider_type') === providerType))
  const deploymentReady = deployment ? ['ready', 'healthy', 'materialized', 'available'].includes(normalizeStatus(valueText(deployment, 'status') || valueText(deployment, 'deployment_status'))) : false
  const deploymentId = valueText(deployment, 'model_deployment_id')
  const binding = providers?.runtime_bindings.find((item) => valueText(item, 'bundle_id') === bundle.bundle_id || valueText(item, 'compatibility_bundle_id') === bundle.bundle_id || (deploymentId !== '' && valueText(item, 'model_deployment_id') === deploymentId))
  const bindingReady = binding ? ['ready', 'healthy', 'active', 'bound'].includes(normalizeStatus(valueText(binding, 'status') || valueText(binding, 'binding_status'))) : false
  const required = bundleRequiredResources(bundle)
  const total = fleet?.resources.total
  const free = fleet?.resources.free
  const capacityKnown = Boolean(total && (total.cpu > 0 || total.ram_mb > 0 || total.vram_mb > 0))
  const fits = Boolean(free && free.cpu >= required.cpu && free.ram_mb >= required.ram_mb && free.vram_mb >= required.vram_mb)
  const lifecycle = bundleLifecycleStatus(bundle)
  const endpointState = bundleEndpointState(bundle)

  return [
    {
      key: 'bundle',
      label: 'Bundle revision',
      state: !bundle.enabled ? 'blocked' : lifecycle === 'failed' || lifecycle === 'cooldown' ? 'blocked' : 'ready',
      detail: !bundle.enabled ? 'The revision is paused. Enable it before admitting new work.' : lifecycle === 'failed' || lifecycle === 'cooldown' ? `Lifecycle is ${lifecycle}; retry or reset the cooldown before activation.` : `Revision r${String(valueText(record, 'revision') || '1')} is enabled and its source history is immutable.`,
    },
    {
      key: 'provider',
      label: 'Provider instance',
      state: providers && providers.provider_instances.length > 0 ? (provider ? (providerHealthy ? 'ready' : 'blocked') : 'blocked') : providerStep,
      detail: providers && providers.provider_instances.length > 0 ? (provider ? (providerHealthy ? `${valueText(provider, 'display_name') || pluginId || providerType} reports a usable health state.` : 'The matching Provider instance is present but not healthy.') : `No attached Provider matches ${pluginId || providerType}.`) : 'Provider inventory is not available; readiness evidence is used instead.',
    },
    {
      key: 'model',
      label: 'Model deployment',
      state: providers && providers.model_deployments.length > 0 ? (deployment ? (deploymentReady ? 'ready' : 'blocked') : 'blocked') : modelStep,
      detail: providers && providers.model_deployments.length > 0 ? (deployment ? (deploymentReady ? `${modelId} is available to the attached Provider.` : 'The model deployment exists but is not ready or materialized.') : `No deployment for ${modelId} was reported.`) : 'Model deployment inventory is not available; readiness evidence is used instead.',
    },
    {
      key: 'binding',
      label: 'Runtime Binding',
      state: providers && providers.runtime_bindings.length > 0 ? (binding ? (bindingReady ? 'ready' : 'blocked') : 'blocked') : bindingStep,
      detail: providers && providers.runtime_bindings.length > 0 ? (binding ? (bindingReady ? `Binding ${shortId(valueText(binding, 'runtime_binding_id'), 24)} is active.` : 'The binding exists but is not active.') : 'No Runtime Binding targets this Bundle or its model deployment.') : 'Runtime Binding inventory is not available; readiness evidence is used instead.',
    },
    {
      key: 'capacity',
      label: 'Host capacity',
      state: !capacityKnown ? (readinessState(readiness, 'resources') === 'blocked' ? 'blocked' : 'unknown') : fits ? 'ready' : 'blocked',
      detail: !capacityKnown ? `Capacity probe is not reporting enough data for ${required.cpu.toFixed(1)} CPU, ${formatMemory(required.ram_mb)} RAM and ${formatMemory(required.vram_mb)} VRAM.` : fits ? `Free capacity covers ${required.cpu.toFixed(1)} CPU, ${formatMemory(required.ram_mb)} RAM and ${formatMemory(required.vram_mb)} VRAM.` : `Free capacity does not cover ${required.cpu.toFixed(1)} CPU, ${formatMemory(required.ram_mb)} RAM and ${formatMemory(required.vram_mb)} VRAM.`,
    },
    {
      key: 'endpoint',
      label: 'Endpoint relationship',
      state: endpointState === 'published_endpoint' ? 'ready' : 'info',
      detail: endpointState === 'published_endpoint' ? 'A published Endpoint points at this revision.' : endpointState === 'draft_endpoint' ? 'A draft Endpoint exists; publication remains a separate trust decision.' : 'No Endpoint is linked. This does not block local Bundle execution.',
    },
    {
      key: 'validation',
      label: 'Validation impact',
      state: 'info',
      detail: endpointState === 'published_endpoint' ? 'Endpoint validation and publication policy are managed in the Endpoints workspace.' : 'Validation is not inferred from Bundle readiness and will be evaluated when an Endpoint is drafted.',
    },
  ]
}

function BundlePreflightPanel({ bundle, readiness, fleet, providers, onNavigate, onRefresh }: { bundle: Bundle; readiness?: Readiness; fleet?: Fleet; providers?: ProviderWorkspace; onNavigate: NavigationProps['onNavigate']; onRefresh: () => void }) {
  const checks = bundlePreflightChecks(bundle, readiness, fleet, providers)
  const blocked = checks.filter((check) => check.state === 'blocked')
  const ready = checks.filter((check) => check.state === 'ready')
  const unknown = checks.filter((check) => check.state === 'unknown')
  const overall = blocked.length > 0 ? 'blocked' : unknown.length > 0 ? 'unknown' : 'ready'
  return <Card className="border-cyan-300/20 bg-cyan-300/[0.03] py-0 shadow-none"><CardHeader className="border-b border-border/70 px-5 py-4"><div className="flex flex-wrap items-start justify-between gap-3"><div><p className="eyebrow text-cyan-100">Activation evidence</p><CardTitle className="mt-1 text-lg font-semibold">Preflight: {shortId(bundle.bundle_id, 30)}</CardTitle><p className="mt-1 text-xs leading-5 text-muted-foreground">Read-only projection from current Hypervisor inventories. Refresh evidence before changing lifecycle state.</p></div><StatusBadge value={overall} /></div></CardHeader><CardContent className="space-y-3 p-5"><div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground"><span>{ready.length} ready</span><span>Â·</span><span>{blocked.length} blocked</span><span>Â·</span><span>{unknown.length} unknown</span><Button variant="outline" size="sm" className="ml-auto border-border bg-[#091725]" onClick={onRefresh}><RefreshCw />Refresh evidence</Button></div><div className="grid gap-2 lg:grid-cols-2">{checks.map((check) => <div key={check.key} className="flex gap-3 rounded-lg border border-border/70 bg-black/10 p-3"><BundleCheckIcon state={check.state} /><div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><p className="text-sm font-medium text-slate-100">{check.label}</p><StatusBadge value={check.state} /></div><p className="mt-1 text-xs leading-5 text-muted-foreground">{check.detail}</p></div></div>)}</div><div className="flex flex-wrap gap-2"><Button variant="outline" size="sm" className="border-border bg-[#091725]" onClick={() => onNavigate('providers')}><ServerCog />Provider workspace</Button><Button variant="outline" size="sm" className="border-border bg-[#091725]" onClick={() => onNavigate('models')}><Database />Model deployments</Button><Button variant="outline" size="sm" className="border-border bg-[#091725]" onClick={() => onNavigate('endpoints')}><RadioTower />Endpoint impact</Button></div></CardContent></Card>
}

function BundleCheckIcon({ state }: { state: BundlePreflightState }) {
  if (state === 'ready') return <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-300" />
  if (state === 'blocked') return <XCircle className="mt-0.5 size-4 shrink-0 text-rose-300" />
  if (state === 'info') return <CircleDot className="mt-0.5 size-4 shrink-0 text-cyan-200" />
  return <CircleDot className="mt-0.5 size-4 shrink-0 text-amber-200" />
}

function BundleCopyValue({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false)
  async function copy() {
    if (!value || value === 'Not reported') return
    try {
      await navigator.clipboard.writeText(value)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1400)
    } catch {
      setCopied(false)
    }
  }
  return <div className="min-w-0"><p className="eyebrow">{label}</p><button type="button" className="mt-1 flex max-w-full items-center gap-1 rounded text-left font-mono text-xs text-slate-200 hover:text-cyan-200" onClick={() => void copy()} title="Copy value"><span className="truncate">{value || 'Not reported'}</span>{value && value !== 'Not reported' ? <Copy className="size-3 shrink-0" /> : null}</button>{copied ? <p className="mt-1 text-[10px] text-emerald-300">Copied</p> : null}</div>
}

function BundleInspector({ bundle, open, onOpenChange, onAction, onNavigate, onPreflight, onClone, preflight, readiness, fleet, providers }: { bundle?: Bundle; open: boolean; onOpenChange: (open: boolean) => void; onAction: (bundle: Bundle, action: BundleAction) => void; onNavigate: NavigationProps['onNavigate']; onPreflight: () => void; onClone: () => void; preflight: boolean; readiness?: Readiness; fleet?: Fleet; providers?: ProviderWorkspace }) {
  if (!bundle) return null
  const record = getRecord(bundle)
  const profile = getRecord(record?.resource_profile)
  const metadata = getRecord(record?.runtime_metadata)
  const relation = getRecord(record?.endpoint_relationship)
  const lifecycle = bundleLifecycleStatus(bundle)
  const endpointState = bundleEndpointState(bundle)
  const required = bundleRequiredResources(bundle)
  const checks = bundlePreflightChecks(bundle, readiness, fleet, providers)
  return <Sheet open={open} onOpenChange={onOpenChange}><SheetContent side="right" className="w-full overflow-y-auto border-slate-700 bg-[#07111d] p-0 sm:max-w-xl"><SheetHeader className="border-b border-border/70 px-5 py-5"><div className="flex flex-wrap items-center gap-2"><StatusBadge value={lifecycle} /><span className="eyebrow">Bundle inspector</span></div><SheetTitle className="pr-8 text-xl text-white">{bundle.bundle_id}</SheetTitle><SheetDescription className="font-mono text-[11px] text-slate-500">Immutable revision r{String(valueText(record, 'revision') || '1')} Â· {shortId(valueText(record, 'bundle_hash'), 28)}</SheetDescription></SheetHeader><div className="space-y-4 p-5">
    <Card className="border-border/80 bg-card py-0 shadow-none"><CardHeader className="border-b border-border/70 px-4 py-3"><CardTitle className="text-sm">Identity & ancestry</CardTitle></CardHeader><CardContent className="grid grid-cols-2 gap-x-4 gap-y-4 p-4"><BundleCopyValue label="Bundle ID" value={bundle.bundle_id} /><BundleCopyValue label="Content hash" value={valueText(record, 'bundle_hash', 'Not reported')} /><BundleCopyValue label="Revision" value={valueText(record, 'revision', '1')} /><BundleCopyValue label="Revision of" value={valueText(record, 'revision_of', 'Root revision')} /><BundleCopyValue label="Launch mode" value={valueText(record, 'launch_mode', 'Not reported')} /><BundleCopyValue label="Device affinity" value={valueText(record, 'device_affinity', 'Not reported')} /></CardContent></Card>
    <Card className="border-border/80 bg-card py-0 shadow-none"><CardHeader className="border-b border-border/70 px-4 py-3"><CardTitle className="text-sm">Execution chain</CardTitle></CardHeader><CardContent className="space-y-3 p-4"><div className="grid grid-cols-[1fr_auto] items-center gap-2"><div><p className="eyebrow">Provider</p><p className="mt-1 text-sm text-slate-200">{valueText(record, 'provider_type')} <span className="font-mono text-xs text-slate-500">{shortId(valueText(record, 'plugin_id'), 24)}</span></p></div><Button variant="ghost" size="sm" className="text-cyan-200" onClick={() => onNavigate('providers')}>Open<ChevronRight /></Button></div><div className="border-l border-cyan-300/30 pl-3"><p className="eyebrow">Model deployment</p><p className="mt-1 text-sm text-slate-200">{valueText(record, 'model_id')}</p></div><div className="border-l border-cyan-300/30 pl-3"><p className="eyebrow">Runtime</p><p className="mt-1 text-sm text-slate-200">{valueText(record, 'runtime_id', 'No runtime handle')}</p><p className="mt-1 text-xs text-muted-foreground">{valueText(record, 'runtime_health_status', 'Health not reported')} Â· {valueText(record, 'runtime_last_error', 'No runtime error')}</p></div><div className="grid grid-cols-[1fr_auto] items-center gap-2 border-l border-cyan-300/30 pl-3"><div><p className="eyebrow">Endpoint relationship</p><p className="mt-1 text-sm text-slate-200">{endpointState.replaceAll('_', ' ')}</p><p className="mt-1 font-mono text-[11px] text-slate-500">{valueText(relation, 'endpoint_id', 'No Endpoint ID')}</p></div><Button variant="ghost" size="sm" className="text-cyan-200" onClick={() => onNavigate('endpoints')}>Open<ChevronRight /></Button></div></CardContent></Card>
    <Card className="border-border/80 bg-card py-0 shadow-none"><CardHeader className="border-b border-border/70 px-4 py-3"><div className="flex items-center justify-between gap-3"><CardTitle className="text-sm">Resource profile</CardTitle><StatusBadge value={valueText(record, 'warm_policy', 'auto')} /></div></CardHeader><CardContent className="grid grid-cols-2 gap-x-4 gap-y-4 p-4"><SessionValue label="Activation CPU" value={`${required.cpu.toFixed(1)} cores`} /><SessionValue label="Activation RAM" value={formatMemory(required.ram_mb)} /><SessionValue label="Activation VRAM" value={formatMemory(required.vram_mb)} /><SessionValue label="Steady CPU" value={`${numberValue(profile, 'steady_cpu').toFixed(1)} cores`} /><SessionValue label="Steady RAM" value={formatMemory(numberValue(profile, 'steady_ram_mb'))} /><SessionValue label="Steady VRAM" value={formatMemory(numberValue(profile, 'steady_vram_mb'))} /><SessionValue label="Priority" value={valueText(record, 'priority_class', '50')} /><SessionValue label="Parallel limit" value={valueText(record, 'max_parallel_requests', '1')} /></CardContent></Card>
    {preflight ? <Card className="border-cyan-300/20 bg-cyan-300/[0.03] py-0 shadow-none"><CardHeader className="border-b border-border/70 px-4 py-3"><CardTitle className="text-sm">Current preflight</CardTitle></CardHeader><CardContent className="space-y-2 p-4">{checks.map((check) => <div key={check.key} className="flex items-center gap-2"><BundleCheckIcon state={check.state} /><span className="text-xs text-slate-200">{check.label}</span><StatusBadge value={check.state} /></div>)}</CardContent></Card> : null}
    {metadata && Object.keys(metadata).length > 0 ? <Card className="border-border/80 bg-card py-0 shadow-none"><CardHeader className="border-b border-border/70 px-4 py-3"><CardTitle className="text-sm">Runtime metadata</CardTitle></CardHeader><CardContent className="space-y-2 p-4">{Object.entries(metadata).slice(0, 8).map(([key, value]) => <div key={key} className="flex items-start justify-between gap-3 text-xs"><span className="font-mono text-slate-500">{key}</span><span className="max-w-[65%] break-all text-right text-slate-300">{typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean' ? String(value) : 'structured value'}</span></div>)}</CardContent></Card> : null}
  </div><div className="sticky bottom-0 mt-auto flex flex-wrap gap-2 border-t border-border/70 bg-[#07111d] p-4"><Button variant="outline" className="border-border bg-[#091725]" onClick={onPreflight}><Gauge />{preflight ? 'Refresh preflight' : 'Run preflight'}</Button><Button variant="outline" className="border-cyan-300/25 bg-[#091725] text-cyan-100" onClick={onClone}><Boxes />Create revision</Button><Button variant="outline" className="border-border bg-[#091725]" onClick={() => onAction(bundle, bundle.enabled ? 'disable' : 'enable')}>{bundle.enabled ? 'Pause' : 'Enable'}</Button><Button variant="ghost" className="ml-auto" onClick={() => onOpenChange(false)}>Close</Button></div></SheetContent></Sheet>
}

function BundleComparison({ source, target }: { source?: Bundle; target?: Bundle }) {
  if (!source || !target) return null
  const sourceRecord = getRecord(source)
  const targetRecord = getRecord(target)
  const fields: Array<[string, string, string]> = [
    ['Revision', valueText(sourceRecord, 'revision', '1'), valueText(targetRecord, 'revision', '1')],
    ['Bundle hash', valueText(sourceRecord, 'bundle_hash', 'Not reported'), valueText(targetRecord, 'bundle_hash', 'Not reported')],
    ['Provider', valueText(sourceRecord, 'provider_type'), valueText(targetRecord, 'provider_type')],
    ['Model', valueText(sourceRecord, 'model_id'), valueText(targetRecord, 'model_id')],
    ['Launch mode', valueText(sourceRecord, 'launch_mode', 'Not reported'), valueText(targetRecord, 'launch_mode', 'Not reported')],
    ['Endpoint', valueText(sourceRecord, 'endpoint', 'None'), valueText(targetRecord, 'endpoint', 'None')],
    ['Device affinity', valueText(sourceRecord, 'device_affinity', 'Not reported'), valueText(targetRecord, 'device_affinity', 'Not reported')],
    ['Warm policy', valueText(sourceRecord, 'warm_policy', 'Not reported'), valueText(targetRecord, 'warm_policy', 'Not reported')],
    ['Priority', valueText(sourceRecord, 'priority_class', '50'), valueText(targetRecord, 'priority_class', '50')],
    ['Parallel limit', valueText(sourceRecord, 'max_parallel_requests', '1'), valueText(targetRecord, 'max_parallel_requests', '1')],
    ['Resource profile', JSON.stringify(sourceRecord?.resource_profile ?? {}), JSON.stringify(targetRecord?.resource_profile ?? {})],
  ]
  return <Card className="border-violet-300/20 bg-violet-300/[0.03] py-0 shadow-none"><CardHeader className="border-b border-border/70 px-5 py-4"><div className="flex flex-wrap items-center justify-between gap-3"><div><p className="eyebrow text-violet-100">Immutable history</p><CardTitle className="mt-1 text-lg font-semibold">Revision comparison</CardTitle><p className="mt-1 text-xs text-muted-foreground">Field-level view only. Neither source is edited by comparison.</p></div><StatusBadge value={source.bundle_id === target.bundle_id ? 'same revision' : 'comparison ready'} /></div></CardHeader><CardContent className="overflow-x-auto p-0"><table className="w-full min-w-[640px] text-left text-xs"><thead className="border-b border-border/70 text-[10px] uppercase tracking-[0.16em] text-slate-500"><tr><th className="px-5 py-3">Field</th><th className="px-5 py-3">Source · {shortId(source.bundle_id, 18)}</th><th className="px-5 py-3">Target · {shortId(target.bundle_id, 18)}</th><th className="px-5 py-3">Change</th></tr></thead><tbody className="divide-y divide-border/70">{fields.map(([label, left, right]) => <tr key={label}><td className="px-5 py-3 font-medium text-slate-300">{label}</td><td className="max-w-[220px] break-all px-5 py-3 font-mono text-slate-400">{left}</td><td className="max-w-[220px] break-all px-5 py-3 font-mono text-slate-200">{right}</td><td className="px-5 py-3"><StatusBadge value={left === right ? 'unchanged' : 'changed'} /></td></tr>)}</tbody></table></CardContent></Card>
}

function BundlesScreen({ bundles, isLoading, error, onNavigate, onRefresh, readiness, fleet, providers }: { bundles: Bundle[]; isLoading: boolean; error: Error | null; onNavigate: NavigationProps['onNavigate']; onRefresh: () => void; readiness?: Readiness; fleet?: Fleet; providers?: ProviderWorkspace }) {
  const [busy, setBusy] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [providerFilter, setProviderFilter] = useState('all')
  const [endpointFilter, setEndpointFilter] = useState('all')
  const [selectedBundleId, setSelectedBundleId] = useState<string | null>(null)
  const [preflightBundleId, setPreflightBundleId] = useState<string | null>(null)
  const [compareSourceId, setCompareSourceId] = useState('')
  const [compareTargetId, setCompareTargetId] = useState('')
  const [revisionSeed, setRevisionSeed] = useState<string | undefined>()

  const filteredBundles = bundles.filter((bundle) => {
    const haystack = [bundle.bundle_id, bundle.provider_type, bundle.model_id, bundle.plugin_id, bundle.workload_type].join(' ').toLowerCase()
    return (search.trim() === '' || haystack.includes(search.trim().toLowerCase())) && (statusFilter === 'all' || bundleLifecycleStatus(bundle) === statusFilter) && (providerFilter === 'all' || bundle.provider_type === providerFilter) && (endpointFilter === 'all' || bundleEndpointState(bundle) === endpointFilter)
  })
  const selectedBundle = bundles.find((bundle) => bundle.bundle_id === selectedBundleId)
  const preflightBundle = bundles.find((bundle) => bundle.bundle_id === preflightBundleId)
  const compareSource = bundles.find((bundle) => bundle.bundle_id === compareSourceId)
  const compareTarget = bundles.find((bundle) => bundle.bundle_id === compareTargetId)
  const statuses = Array.from(new Set(bundles.map(bundleLifecycleStatus))).sort()
  const providersInUse = Array.from(new Set(bundles.map((bundle) => bundle.provider_type))).sort()
  const summary = {
    total: bundles.length,
    enabled: bundles.filter((bundle) => bundle.enabled).length,
    attention: bundles.filter((bundle) => ['failed', 'cooldown'].includes(bundleLifecycleStatus(bundle))).length,
    linked: bundles.filter((bundle) => bundleEndpointState(bundle) === 'published_endpoint').length,
  }

  async function runBundleAction(bundle: Bundle, action: BundleAction) {
    if (action === 'disable' && !window.confirm(`Pause Bundle ${bundle.bundle_id}? Existing Sessions are not rewritten.`)) return
    setBusy(`${bundle.bundle_id}:${action}`)
    setMessage(null)
    try {
      await dashboardApi.bundleOperation(bundle.bundle_id, action)
      setMessage(`${bundle.bundle_id}: ${action.replace('-', ' ')} completed.`)
      onRefresh()
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : 'Bundle operation failed.')
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="space-y-4">
      <ScreenHeading eyebrow="Bundle-first operations" title="Bundles" detail="Bundles are immutable deployments. These controls operate the current revision only; configuration changes require a new revision rather than overwriting active history." />
      {message ? <OperationNotice message={message} onDismiss={() => setMessage(null)} /> : null}
      {busy ? <p className="font-mono text-xs text-cyan-200">Applying {busy.replace(':', ' ')}...</p> : null}
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4"><BundleSummary label="Total revisions" value={summary.total} detail="Immutable records" icon={Boxes} /><BundleSummary label="Enabled" value={summary.enabled} detail="Admit compatible work" icon={Zap} /><BundleSummary label="Needs attention" value={summary.attention} detail="Failed or cooldown" icon={ShieldCheck} tone={summary.attention > 0 ? 'warning' : 'default'} /><BundleSummary label="Published links" value={summary.linked} detail="Endpoint relationships" icon={RadioTower} /></div>
      <Card className="border-border/80 bg-card py-0 shadow-none"><CardContent className="grid gap-3 p-4 lg:grid-cols-[minmax(14rem,1.6fr)_repeat(3,minmax(9rem,0.7fr))_auto]"><label className="relative"><Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-slate-500" /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search Bundle, model, Provider..." className="h-10 w-full rounded-lg border border-input bg-[#07111d] pl-9 pr-3 text-sm text-white outline-none focus:border-cyan-300" /></label><select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} className="h-10 rounded-lg border border-input bg-[#07111d] px-3 text-sm text-white outline-none focus:border-cyan-300"><option value="all">All lifecycle states</option>{statuses.map((status) => <option key={status} value={status}>{status}</option>)}</select><select value={providerFilter} onChange={(event) => setProviderFilter(event.target.value)} className="h-10 rounded-lg border border-input bg-[#07111d] px-3 text-sm text-white outline-none focus:border-cyan-300"><option value="all">All Providers</option>{providersInUse.map((provider) => <option key={provider} value={provider}>{provider}</option>)}</select><select value={endpointFilter} onChange={(event) => setEndpointFilter(event.target.value)} className="h-10 rounded-lg border border-input bg-[#07111d] px-3 text-sm text-white outline-none focus:border-cyan-300"><option value="all">All Endpoint links</option><option value="published_endpoint">Published</option><option value="draft_endpoint">Draft</option><option value="no_endpoint">Unlinked</option><option value="published_drifted">Drifted</option></select><Button variant="outline" className="h-10 border-border bg-[#091725]" onClick={() => { setSearch(''); setStatusFilter('all'); setProviderFilter('all'); setEndpointFilter('all') }}>Clear</Button></CardContent></Card>
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground"><span>Showing {filteredBundles.length} of {bundles.length} revisions</span><span>Â·</span><span>Select a row to inspect dependencies and actions</span></div>
      <BundleTableSection bundles={filteredBundles} isLoading={isLoading} error={error} onNavigate={onNavigate} onAction={runBundleAction} onSelect={(bundle) => setSelectedBundleId(bundle.bundle_id)} />
      <Card className="border-violet-300/15 bg-violet-300/[0.025] py-0 shadow-none"><CardHeader className="border-b border-border/70 px-5 py-4"><div className="flex flex-wrap items-end justify-between gap-3"><div><p className="eyebrow text-violet-100">Revision history</p><CardTitle className="mt-1 text-lg font-semibold">Compare two immutable records</CardTitle><p className="mt-1 text-xs leading-5 text-muted-foreground">Compare configuration and resource fields before creating or enabling a new revision.</p></div><StatusBadge value={compareSource && compareTarget ? 'ready' : 'select two'} /></div></CardHeader><CardContent className="grid gap-3 p-5 lg:grid-cols-[1fr_1fr_auto]"><select value={compareSourceId} onChange={(event) => setCompareSourceId(event.target.value)} className="h-10 rounded-lg border border-input bg-[#07111d] px-3 text-sm text-white outline-none focus:border-violet-300"><option value="">Source revision</option>{bundles.map((bundle) => <option key={`source:${bundle.bundle_id}`} value={bundle.bundle_id}>{bundle.bundle_id} Â· r{String(valueText(getRecord(bundle), 'revision') || '1')}</option>)}</select><select value={compareTargetId} onChange={(event) => setCompareTargetId(event.target.value)} className="h-10 rounded-lg border border-input bg-[#07111d] px-3 text-sm text-white outline-none focus:border-violet-300"><option value="">Target revision</option>{bundles.map((bundle) => <option key={`target:${bundle.bundle_id}`} value={bundle.bundle_id}>{bundle.bundle_id} Â· r{String(valueText(getRecord(bundle), 'revision') || '1')}</option>)}</select><Button variant="outline" className="h-10 border-violet-300/25 bg-[#091725] text-violet-100" disabled={!compareSource || !compareTarget} onClick={() => { if (compareSource && compareTarget) window.requestAnimationFrame(() => document.getElementById('bundle-comparison')?.scrollIntoView({ behavior: 'smooth', block: 'start' })) }}><Eye />Compare</Button></CardContent></Card>
      {compareSource && compareTarget ? <div id="bundle-comparison"><BundleComparison source={compareSource} target={compareTarget} /></div> : null}
      {preflightBundle ? <BundlePreflightPanel bundle={preflightBundle} readiness={readiness} fleet={fleet} providers={providers} onNavigate={onNavigate} onRefresh={onRefresh} /> : null}
      <div id="bundle-revision-factory"><BundleRevisionControl key={revisionSeed ?? 'default'} bundles={bundles} onRefresh={onRefresh} initialSourceBundleId={revisionSeed} /></div>
      <BundleInspector bundle={selectedBundle} open={Boolean(selectedBundle)} onOpenChange={(open) => { if (!open) setSelectedBundleId(null) }} onAction={(bundle, action) => void runBundleAction(bundle, action)} onNavigate={onNavigate} preflight={Boolean(preflightBundle && selectedBundleId === preflightBundleId)} onPreflight={() => { if (selectedBundle) { setPreflightBundleId(selectedBundle.bundle_id); onRefresh() } }} onClone={() => { if (selectedBundle) { setRevisionSeed(selectedBundle.bundle_id); setSelectedBundleId(null); window.setTimeout(() => document.getElementById('bundle-revision-factory')?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 0) } }} readiness={readiness} fleet={fleet} providers={providers} />
    </div>
  )
}

function BundleSummary({ label, value, detail, icon: Icon, tone = 'default' }: { label: string; value: number; detail: string; icon: LucideIcon; tone?: 'default' | 'warning' }) {
  return <Card className={cn('border-border/80 bg-card py-0 shadow-none', tone === 'warning' && 'border-amber-300/25')}><CardContent className="flex items-center gap-3 p-4"><span className={cn('grid size-9 place-items-center rounded-lg border border-cyan-300/20 bg-cyan-300/[0.06] text-cyan-200', tone === 'warning' && 'border-amber-300/25 bg-amber-300/[0.06] text-amber-200')}><Icon className="size-4" /></span><div><p className="eyebrow">{label}</p><p className="mt-1 text-2xl font-semibold tracking-[-0.04em] text-white">{formatCount(value)}</p><p className="text-xs text-muted-foreground">{detail}</p></div></CardContent></Card>
}

function BundleRevisionControl({ bundles, onRefresh, initialSourceBundleId }: { bundles: Bundle[]; onRefresh: () => void; initialSourceBundleId?: string }) {
  const [sourceBundleId, setSourceBundleId] = useState('')
  const [bundleId, setBundleId] = useState('')
  const [overrides, setOverrides] = useState('{}')
  const [enabled, setEnabled] = useState(false)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  useEffect(() => {
    if (initialSourceBundleId && bundles.some((bundle) => bundle.bundle_id === initialSourceBundleId)) {
      setSourceBundleId(initialSourceBundleId)
      const source = bundles.find((bundle) => bundle.bundle_id === initialSourceBundleId)
      if (source) setBundleId(`${source.bundle_id}-r${Number(getRecord(source)?.revision ?? 1) + 1}`)
      return
    }
    if (bundles.length > 0) {
      setSourceBundleId((current) => current || bundles[0].bundle_id)
      setBundleId((current) => current || `${bundles[0].bundle_id}-r${Number(getRecord(bundles[0])?.revision ?? 1) + 1}`)
    }
  }, [bundles, initialSourceBundleId])

  function chooseSource(nextId: string) {
    setSourceBundleId(nextId)
    const source = bundles.find((bundle) => bundle.bundle_id === nextId)
    if (source) setBundleId(`${source.bundle_id}-r${Number(getRecord(source)?.revision ?? 1) + 1}`)
  }

  async function createRevision() {
    let parsed: DashboardRecord
    try {
      const candidate: unknown = JSON.parse(overrides)
      const record = getRecord(candidate)
      if (!record) throw new Error('Revision overrides must be a JSON object.')
      parsed = record
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : 'Revision overrides are not valid JSON.')
      return
    }
    if (!sourceBundleId || !bundleId.trim()) {
      setMessage('Choose a source Bundle and provide a new revision ID.')
      return
    }
    setBusy(true)
    setMessage(null)
    try {
      const result = await dashboardApi.createBundleRevision(sourceBundleId, { bundle_id: bundleId.trim(), overrides: parsed, enabled })
      setMessage(`Created ${getText(result, 'bundle_id') || bundleId.trim()} with hash ${getText(result, 'bundle_hash') || 'pending'}. The source revision was not overwritten.`)
      onRefresh()
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : 'Bundle revision creation failed.')
    } finally {
      setBusy(false)
    }
  }

  return <Card className="border-cyan-300/20 bg-cyan-300/[0.03] py-0 shadow-none"><CardHeader className="border-b border-border/70 px-5 py-4"><p className="eyebrow text-cyan-100">Immutable revision factory</p><CardTitle className="mt-1 text-lg font-semibold">Create a new Bundle revision</CardTitle><p className="mt-1 text-sm leading-6 text-muted-foreground">A revision receives a new ID and content hash. The source remains auditable and unchanged; enable the new revision only when preflight is complete.</p></CardHeader><CardContent className="grid gap-3 p-5 lg:grid-cols-[1fr_1fr_1.5fr_auto]"><label className="grid gap-2"><span className="eyebrow">Source revision</span><select value={sourceBundleId} onChange={(event) => chooseSource(event.target.value)} className="h-10 rounded-lg border border-input bg-[#07111d] px-3 text-sm text-white outline-none focus:border-cyan-300"><option value="">Select Bundle</option>{bundles.map((bundle) => <option key={bundle.bundle_id} value={bundle.bundle_id}>{bundle.bundle_id} · r{String(getRecord(bundle)?.revision ?? 1)}</option>)}</select></label><label className="grid gap-2"><span className="eyebrow">New revision ID</span><input value={bundleId} onChange={(event) => setBundleId(event.target.value)} placeholder="bundle-whisper-r2" className="h-10 rounded-lg border border-input bg-[#07111d] px-3 font-mono text-xs text-white outline-none focus:border-cyan-300" /></label><label className="grid gap-2"><span className="eyebrow">Immutable overrides JSON</span><input value={overrides} onChange={(event) => setOverrides(event.target.value)} className="h-10 rounded-lg border border-input bg-[#07111d] px-3 font-mono text-xs text-white outline-none focus:border-cyan-300" /></label><div className="flex items-end gap-2"><label className="flex h-10 items-center gap-2 rounded-lg border border-border/70 px-3 text-xs text-slate-300"><input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} />Enable</label><Button className="h-10 bg-cyan-300 text-[#06121d] hover:bg-cyan-200" disabled={busy || bundles.length === 0} onClick={() => void createRevision()}><Boxes />{busy ? 'Creating...' : 'Create revision'}</Button></div>{message ? <div className="lg:col-span-4"><OperationNotice message={message} onDismiss={() => setMessage(null)} /></div> : null}</CardContent></Card>
}

function EndpointsScreen({ endpoints, isLoading, error, onNavigate, onRefresh, ownerWallet, bundles, bindings }: { endpoints: Endpoint[]; isLoading: boolean; error: Error | null; onNavigate: NavigationProps['onNavigate']; onRefresh: () => void; ownerWallet: string; bundles: Bundle[]; bindings: DashboardRecord[] }) {
  const [busy, setBusy] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  async function runEndpointAction(endpoint: Endpoint, action: 'publish' | 'validate') {
    setBusy(`${endpoint.endpoint_id}:${action}`)
    setMessage(null)
    try {
      if (action === 'publish') await dashboardApi.publishEndpoint(endpoint.endpoint_id)
      if (action === 'validate') await dashboardApi.requestEndpointValidation(endpoint.endpoint_id)
      setMessage(`${endpoint.endpoint_id}: ${action} request completed.`)
      onRefresh()
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : 'Endpoint operation failed.')
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="space-y-4">
      <ScreenHeading eyebrow="Network-facing service offers" title="Endpoints" detail="Endpoint publication remains commercially distinct from the Bundle that runs it. This table shows the bound configuration, execution state and public readiness." />
      <EndpointDraftControl ownerWallet={ownerWallet} bundles={bundles} bindings={bindings} onRefresh={onRefresh} />
      {busy ? <p className="font-mono text-xs text-cyan-200">Applying {busy.replace(':', ' ')}...</p> : null}
      {message ? <OperationNotice message={message} onDismiss={() => setMessage(null)} /> : null}
      <Card className="border-border/80 bg-card py-0 shadow-none">
        <CardHeader className="border-b border-border/75 px-5 py-4">
          <div><p className="eyebrow">Endpoint inventory</p><CardTitle className="mt-1 text-lg font-semibold tracking-[-0.03em]">Published and local offers</CardTitle></div>
          <Button variant="ghost" size="sm" className="text-cyan-200 hover:bg-cyan-300/10 hover:text-cyan-100" onClick={() => onNavigate('bundles')}>View Bundles<ChevronRight /></Button>
        </CardHeader>
        <CardContent className="p-0">
          {isLoading && endpoints.length === 0 ? <TableSkeleton columns={5} rows={6} /> : null}
          {error && endpoints.length === 0 ? <PanelError title="Endpoint inventory is unavailable" error={error} /> : null}
          {!isLoading && !error && endpoints.length === 0 ? <EmptyState title="No Endpoint offers are configured" detail="Create a Bundle first, then review its publication readiness before exposing it to the Market." actionLabel="Open Bundles" onAction={() => onNavigate('bundles')} /> : null}
          {endpoints.length > 0 ? <EndpointTable endpoints={endpoints} onAction={runEndpointAction} /> : null}
        </CardContent>
      </Card>
    </div>
  )
}

function EndpointDraftControl({ ownerWallet, bundles, bindings, onRefresh }: { ownerWallet: string; bundles: Bundle[]; bindings: DashboardRecord[]; onRefresh: () => void }) {
  const [displayName, setDisplayName] = useState('New Endpoint')
  const [bindingId, setBindingId] = useState('')
  const [bundleId, setBundleId] = useState('')
  const [bundleHash, setBundleHash] = useState('')
  const [modelClass, setModelClass] = useState('llm.chat')
  const [visibility, setVisibility] = useState<'private' | 'shared' | 'public'>('private')
  const [sharedWalletIds, setSharedWalletIds] = useState('')
  const [acceptsExternal, setAcceptsExternal] = useState(false)
  const [validationEnabled, setValidationEnabled] = useState(false)
  const [fixedPrice, setFixedPrice] = useState('0')
  const [minimumDeposit, setMinimumDeposit] = useState('0')
  const [marketplaceHtml, setMarketplaceHtml] = useState('')
  const [marketplacePreview, setMarketplacePreview] = useState<{ html: string; content_hash: string; sanitizer_version: string } | null>(null)
  const [previewBusy, setPreviewBusy] = useState(false)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  useEffect(() => {
    if (!bindingId && bindings.length > 0) {
      const first = bindings[0]
      setBindingId(getText(first, 'runtime_binding_id'))
      setModelClass(getText(first, 'capability_id') || 'llm.chat')
    }
  }, [bindingId, bindings])

  useEffect(() => {
    if (!bundleId && bundles.length > 0) {
      const first = bundles[0]
      setBundleId(first.bundle_id)
      setBundleHash(getText(first, 'bundle_hash'))
    }
  }, [bundleId, bundles])

  useEffect(() => {
    if (!sharedWalletIds && ownerWallet) setSharedWalletIds(ownerWallet)
  }, [ownerWallet, sharedWalletIds])

  async function createDraft() {
    if (!ownerWallet) {
      setMessage('Configure the owner Wallet before creating an Endpoint draft.')
      return
    }
    if (!displayName.trim() || (!bindingId && (!bundleId.trim() || !bundleHash.trim()))) {
      setMessage('Provide a display name and either a Runtime Binding or Bundle ID plus Bundle hash.')
      return
    }
    setBusy(true)
    setMessage(null)
    const validation = validationEnabled
      ? { enabled: true, model_class_supported: true, verification_status: 'pending', certification_status: 'pending_initial', validation_status: 'pending_initial' }
      : { enabled: false, model_class_supported: false, verification_status: 'unsupported', certification_status: 'uncertified', validation_status: 'unvalidated' }
    try {
      await dashboardApi.createEndpoint({
        owner_wallet: ownerWallet,
        runtime_binding_id: bindingId || null,
        bundle_id: bundleId,
        bundle_hash: bundleHash,
        display_name: displayName.trim(),
        model_class: modelClass.trim() || 'llm.chat',
        capabilities: [modelClass.trim() || 'llm.chat'],
        profile: marketplaceHtml.trim()
          ? { marketplace_description: { html: marketplaceHtml } }
          : {},
        runtime: { streaming: true },
        publication: { visibility, shared_with_wallet_ids: visibility === 'shared' ? sharedWalletIds.split(',').map((wallet) => wallet.trim()).filter(Boolean) : [], discoverable: visibility !== 'private', validation: validationEnabled ? 'enabled' : 'disabled', accepts_external_requests: acceptsExternal },
        pricing: { billing_unit: 'request', fixed_price: Number(fixedPrice) || 0 },
        session: { minimum_deposit: Number(minimumDeposit) || 0, max_concurrent_sessions: 1 },
        validation,
      })
      setMessage('Endpoint draft created. Review readiness, then publish the exact configuration.')
      onRefresh()
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : 'Endpoint draft creation failed.')
    } finally {
      setBusy(false)
    }
  }

  async function previewDescription() {
    if (!marketplaceHtml.trim()) {
      setMessage('Add HTML content before requesting a server preview.')
      setMarketplacePreview(null)
      return
    }
    setPreviewBusy(true)
    setMessage(null)
    try {
      const result = await dashboardApi.previewMarketplaceDescription(marketplaceHtml)
      const description = getRecord(result?.description)
      setMarketplacePreview({
        html: getText(result, 'rendered_html') || getText(description, 'html'),
        content_hash: getText(description, 'content_hash'),
        sanitizer_version: getText(description, 'sanitizer_version'),
      })
    } catch (cause) {
      setMarketplacePreview(null)
      setMessage(cause instanceof Error ? cause.message : 'Marketplace preview failed.')
    } finally {
      setPreviewBusy(false)
    }
  }

  return (
    <Card className="border-cyan-300/20 bg-cyan-300/[0.03] py-0 shadow-none">
      <CardHeader className="border-b border-border/70 px-5 py-4">
        <p className="eyebrow text-cyan-100">Endpoint lifecycle</p>
        <CardTitle className="mt-1 text-lg font-semibold">Create a draft from a ready runtime</CardTitle>
        <p className="mt-1 text-sm leading-6 text-muted-foreground">Draft creation is local. Publication signs the immutable configuration and, on a validator, submits <code>ENDPOINT_PUBLISH</code> through consensus. Validation is a separate request.</p>
      </CardHeader>
      <CardContent className="grid gap-3 p-5 lg:grid-cols-4">
        <label className="grid gap-2"><span className="eyebrow">Display name</span><input value={displayName} onChange={(event) => setDisplayName(event.target.value)} className="h-10 rounded-lg border border-input bg-[#07111d] px-3 text-sm text-white outline-none focus:border-cyan-300" /></label>
        <label className="grid gap-2"><span className="eyebrow">Runtime Binding</span><select value={bindingId} onChange={(event) => setBindingId(event.target.value)} className="h-10 rounded-lg border border-input bg-[#07111d] px-3 font-mono text-xs text-white outline-none focus:border-cyan-300"><option value="">Manual Bundle fields</option>{bindings.map((binding) => <option key={getText(binding, 'runtime_binding_id')} value={getText(binding, 'runtime_binding_id')}>{shortId(getText(binding, 'runtime_binding_id'), 28)} · {getText(binding, 'capability_id')}</option>)}</select></label>
        <label className="grid gap-2"><span className="eyebrow">Capability</span><input value={modelClass} onChange={(event) => setModelClass(event.target.value)} className="h-10 rounded-lg border border-input bg-[#07111d] px-3 font-mono text-xs text-white outline-none focus:border-cyan-300" /></label>
        <label className="grid gap-2"><span className="eyebrow">Visibility</span><select value={visibility} onChange={(event) => setVisibility(event.target.value as typeof visibility)} className="h-10 rounded-lg border border-input bg-[#07111d] px-3 text-sm text-white outline-none focus:border-cyan-300"><option value="private">Private</option><option value="shared">Shared</option><option value="public">Public</option></select></label>
        <label className="grid gap-2"><span className="eyebrow">Bundle ID</span><input value={bundleId} onChange={(event) => setBundleId(event.target.value)} disabled={Boolean(bindingId)} className="h-10 rounded-lg border border-input bg-[#07111d] px-3 font-mono text-xs text-white outline-none focus:border-cyan-300 disabled:opacity-50" /></label>
        <label className="grid gap-2"><span className="eyebrow">Bundle hash</span><input value={bundleHash} onChange={(event) => setBundleHash(event.target.value)} disabled={Boolean(bindingId)} className="h-10 rounded-lg border border-input bg-[#07111d] px-3 font-mono text-xs text-white outline-none focus:border-cyan-300 disabled:opacity-50" /></label>
        <label className="grid gap-2"><span className="eyebrow">Fixed price Q</span><input inputMode="decimal" value={fixedPrice} onChange={(event) => setFixedPrice(event.target.value)} className="h-10 rounded-lg border border-input bg-[#07111d] px-3 text-sm text-white outline-none focus:border-cyan-300" /></label>
        <label className="grid gap-2"><span className="eyebrow">Minimum deposit Q</span><input inputMode="decimal" value={minimumDeposit} onChange={(event) => setMinimumDeposit(event.target.value)} className="h-10 rounded-lg border border-input bg-[#07111d] px-3 text-sm text-white outline-none focus:border-cyan-300" /></label>
        <div className="grid gap-2 lg:col-span-4">
          <label className="eyebrow" htmlFor="marketplace-description-html">Marketplace HTML description</label>
          <textarea id="marketplace-description-html" value={marketplaceHtml} onChange={(event) => { setMarketplaceHtml(event.target.value); setMarketplacePreview(null) }} rows={6} placeholder="<p>Describe your endpoint, supported inputs, and a safe usage example.</p>" className="w-full rounded-lg border border-input bg-[#07111d] px-3 py-2 font-mono text-xs leading-5 text-white outline-none focus:border-cyan-300" />
          <p className="text-xs leading-5 text-muted-foreground">The Hypervisor sanitizes this bounded source before it is stored or published. Preview always renders the server-returned sanitized HTML.</p>
          <div className="flex flex-wrap items-center gap-2">
            <Button type="button" variant="outline" className="border-cyan-300/25 bg-[#091725] text-cyan-100" disabled={previewBusy || !marketplaceHtml.trim()} onClick={() => void previewDescription()}><Eye />{previewBusy ? 'Sanitizing...' : 'Preview sanitized HTML'}</Button>
            {marketplacePreview?.content_hash ? <span className="font-mono text-[10px] text-slate-400">{marketplacePreview.sanitizer_version} · {shortId(marketplacePreview.content_hash, 32)}</span> : null}
          </div>
          {marketplacePreview?.html ? <div className="rounded-lg border border-emerald-300/20 bg-emerald-300/[0.04] p-4" aria-live="polite"><p className="eyebrow text-emerald-200">Server preview</p><div className="prose prose-invert mt-2 max-w-none text-sm" dangerouslySetInnerHTML={{ __html: marketplacePreview.html }} /></div> : null}
        </div>
        <div className="flex flex-wrap items-center gap-3 lg:col-span-3"><label className="flex items-center gap-2 text-xs text-slate-300"><input type="checkbox" checked={acceptsExternal} onChange={(event) => setAcceptsExternal(event.target.checked)} />Accept external requests</label><label className="flex items-center gap-2 text-xs text-slate-300"><input type="checkbox" checked={validationEnabled} onChange={(event) => setValidationEnabled(event.target.checked)} />Require validation</label></div>
        <div className="flex items-end justify-end"><Button className="w-full bg-cyan-300 text-[#06121d] hover:bg-cyan-200" disabled={busy} onClick={() => void createDraft()}><RadioTower />{busy ? 'Creating...' : 'Create draft'}</Button></div>
        {message ? <div className="lg:col-span-4"><OperationNotice message={message} onDismiss={() => setMessage(null)} /></div> : null}
      </CardContent>
    </Card>
  )
}

function EndpointTable({ endpoints, onAction }: { endpoints: Endpoint[]; onAction: (endpoint: Endpoint, action: 'publish' | 'validate') => void }) {
  const columns: ColumnDef<Endpoint>[] = [
    { accessorKey: 'display_name', header: 'Endpoint', cell: ({ row }) => <div><p className="font-medium text-slate-100">{row.original.display_name || shortId(row.original.endpoint_id, 22)}</p><p className="mt-0.5 font-mono text-[10px] text-slate-500">{shortId(row.original.endpoint_id)}</p></div> },
    { accessorKey: 'model_class', header: 'Capability', cell: ({ row }) => <span className="text-xs text-slate-200">{row.original.model_class || row.original.capabilities[0] || '—'}</span> },
    { accessorKey: 'visibility', header: 'Visibility', cell: ({ row }) => <StatusBadge value={row.original.visibility || 'private'} /> },
    { accessorKey: 'publication_status', header: 'Publication', cell: ({ row }) => <StatusBadge value={row.original.publication_status} /> },
    { accessorKey: 'runtime_status', header: 'Runtime', cell: ({ row }) => <StatusBadge value={row.original.runtime_status} /> },
    { id: 'controls', header: 'Controls', cell: ({ row }) => <div className="flex flex-wrap gap-1.5"><Button variant="outline" size="xs" className="border-cyan-300/25 bg-[#091725] text-cyan-100" onClick={() => onAction(row.original, 'publish')}>Publish</Button><Button variant="outline" size="xs" className="border-amber-300/25 bg-[#091725] text-amber-100" onClick={() => onAction(row.original, 'validate')}>Validate</Button></div> },
  ]
  const table = useReactTable({ data: endpoints, columns, getCoreRowModel: getCoreRowModel() })
  return <DataTable table={table} />
}

function ModelsWorkspace({ installs, workspace, isLoading, error, onRefresh }: { installs: DashboardRecord[]; workspace: ProviderWorkspace | undefined; isLoading: boolean; error: Error | null; onRefresh: () => void }) {
  const [providerType, setProviderType] = useState('')
  const [modelId, setModelId] = useState('')
  const [sourceUrl, setSourceUrl] = useState('')
  const [workloadType, setWorkloadType] = useState('llm_text')
  const [endpoint, setEndpoint] = useState('http://127.0.0.1:8080')
  const [bundleId, setBundleId] = useState('')
  const [artifactSetName, setArtifactSetName] = useState('')
  const [artifactFiles, setArtifactFiles] = useState('[{"relative_path":"model.bin","artifact_id":"artifact-1","role":"WEIGHTS"}]')
  const [capabilityVersion, setCapabilityVersion] = useState('1.0.0')
  const [capabilityDefinitionHash, setCapabilityDefinitionHash] = useState('sha256:capability-definition')
  const [temperature, setTemperature] = useState('0.7')
  const [temperatureEditable, setTemperatureEditable] = useState(true)
  const [topP, setTopP] = useState('0.9')
  const [topPEditable, setTopPEditable] = useState(true)
  const [maxTokens, setMaxTokens] = useState('512')
  const [maxTokensEditable, setMaxTokensEditable] = useState(true)
  const [contextLength, setContextLength] = useState('4096')
  const [contextLengthEditable, setContextLengthEditable] = useState(false)
  const [gpuMemoryUtilization, setGpuMemoryUtilization] = useState('0.9')
  const [gpuMemoryEditable, setGpuMemoryEditable] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const plugins = workspace?.plugin_directory ?? []
  const llmPlugins = plugins.filter((plugin) => {
    const capabilities = getTextList(plugin, 'supported_aidn_capabilities')
    return capabilities.length === 0 || capabilities.includes('llm.chat')
  })
  const deployments = workspace?.model_deployments ?? []
  const artifactSets = inventoryRecords(workspace?.model_artifact_sets)
  const instances = workspace?.provider_instances ?? []

  useEffect(() => {
    if (!providerType && llmPlugins.length > 0) setProviderType(getText(llmPlugins[0], 'plugin_id'))
  }, [llmPlugins, providerType])

  useEffect(() => {
    if (!bundleId && modelId.trim()) {
      setBundleId(`bundle-${modelId.trim().replace(/[^a-zA-Z0-9-]+/g, '-')}`)
    }
  }, [bundleId, modelId])

  async function installModel() {
    if (!providerType || !modelId.trim() || !sourceUrl.trim()) {
      setMessage('Select a Provider type and provide model ID plus source URL.')
      return
    }
    setBusy('install')
    setMessage(null)
    try {
      await dashboardApi.requestModelInstall({ provider_type: providerType, model_id: modelId.trim(), source_url: sourceUrl.trim(), runtime_parameter_policy: buildRuntimePolicy() })
      setMessage('Model installation queued. Run the materializer, then refresh this workspace.')
      onRefresh()
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : 'Model installation request failed.')
    } finally { setBusy(null) }
  }

  function buildRuntimePolicy(): DashboardRecord {
    const number = (raw: string, label: string): number => {
      const value = Number(raw)
      if (!Number.isFinite(value)) throw new Error(`${label} must be a number.`)
      return value
    }
    const policy: DashboardRecord = {
      temperature: { value: number(temperature, 'Temperature'), consumer_editable: temperatureEditable, min: 0, max: 2 },
      top_p: { value: number(topP, 'Top P'), consumer_editable: topPEditable, min: 0, max: 1 },
      max_tokens: { value: Math.round(number(maxTokens, 'Max tokens')), consumer_editable: maxTokensEditable, min: 1, max: 32768 },
      context_length: { value: Math.round(number(contextLength, 'Context length')), consumer_editable: contextLengthEditable, min: 512, max: 131072 },
    }
    if (providerType === 'ollama' || providerType === 'vllm') {
      policy.gpu_memory_utilization = { value: number(gpuMemoryUtilization, 'GPU memory utilization'), consumer_editable: gpuMemoryEditable, min: 0.1, max: 0.99 }
    }
    return policy
  }

  async function processInstalls() {
    setBusy('process')
    setMessage(null)
    try {
      const result = await dashboardApi.processModelInstalls()
      setMessage(`Model materialization processed: ${result?.items?.length ?? 0} job(s).`)
      onRefresh()
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : 'Model materialization failed.')
    } finally { setBusy(null) }
  }

  async function registerBundle(install: DashboardRecord) {
    const id = getText(install, 'install_id')
    const nextBundleId = bundleId.trim() || `bundle-${getText(install, 'model_id').replace(/[^a-zA-Z0-9-]+/g, '-')}`
    if (!nextBundleId) {
      setMessage('Provide a Bundle ID before registering the completed install.')
      return
    }
    setBusy(`register:${id}`)
    setMessage(null)
    try {
      const persistedPolicy = getRecord(install)?.runtime_parameter_policy
      const runtimeParameterPolicy = getRecord(persistedPolicy) && Object.keys(getRecord(persistedPolicy) ?? {}).length > 0
        ? (getRecord(persistedPolicy) as DashboardRecord)
        : buildRuntimePolicy()
      await dashboardApi.registerBundleFromInstall(id, { bundle_id: nextBundleId, workload_type: workloadType, endpoint, runtime_parameter_policy: runtimeParameterPolicy })
      setMessage(`Bundle ${nextBundleId} registered from the completed model install.`)
      onRefresh()
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : 'Bundle registration failed.')
    } finally { setBusy(null) }
  }

  async function createArtifactSet() {
    let files: DashboardRecord[]
    try {
      const parsed: unknown = JSON.parse(artifactFiles)
      if (!Array.isArray(parsed)) throw new Error('Artifact files must be a JSON array.')
      files = parsed.filter((item): item is DashboardRecord => Boolean(getRecord(item)))
      if (files.length === 0) throw new Error('Artifact files array is empty.')
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : 'Artifact set JSON is invalid.')
      return
    }
    if (!artifactSetName.trim()) { setMessage('Provide an artifact set name.'); return }
    setBusy('artifact-set')
    setMessage(null)
    try {
      await dashboardApi.createModelArtifactSet({ display_name: artifactSetName.trim(), files })
      setMessage('Immutable model artifact set created.')
      onRefresh()
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : 'Artifact set creation failed.')
    } finally { setBusy(null) }
  }

  async function bindArtifactSet(deployment: DashboardRecord, artifactSetId: string) {
    if (!artifactSetId) return
    const id = getText(deployment, 'model_deployment_id')
    setBusy(`bind:${id}`)
    try {
      await dashboardApi.bindModelArtifactSet(id, artifactSetId)
      setMessage(`Artifact set bound to ${id}. Materialize it on the Provider before creating a Runtime Binding.`)
      onRefresh()
    } catch (cause) { setMessage(cause instanceof Error ? cause.message : 'Artifact binding failed.') } finally { setBusy(null) }
  }

    async function materialize(deployment: DashboardRecord, artifactSetId: string) {
      const providerId = getText(deployment, 'provider_instance_id')
      const deploymentId = getText(deployment, 'model_deployment_id')
      const modelReference = getText(deployment, 'provider_model_reference').trim()
      if (!modelReference) {
        setMessage('The deployment has no provider model reference; discover the model again before materializing.')
        return
      }
      const destination = `/var/lib/aidn/models/${modelReference}`
    setBusy(`materialize:${deploymentId}`)
    try {
      await dashboardApi.materializeModelArtifactSet(providerId, artifactSetId, destination)
      setMessage(`Artifact set materialized on ${providerId}.`)
      onRefresh()
    } catch (cause) { setMessage(cause instanceof Error ? cause.message : 'Artifact materialization failed.') } finally { setBusy(null) }
  }

  async function createBinding(deployment: DashboardRecord) {
    const deploymentId = getText(deployment, 'model_deployment_id')
    const capabilityId = getTextList(deployment, 'capability_bindings')[0] || (workloadType === 'speech_to_text' ? 'speech_to_text' : 'llm.chat')
    if (!capabilityVersion.trim() || !capabilityDefinitionHash.trim()) {
      setMessage('Provide a capability version and definition hash before creating a Runtime Binding.')
      return
    }
    setBusy(`binding:${deploymentId}`)
    try {
      await dashboardApi.createRuntimeBinding(deploymentId, { capability_id: capabilityId, capability_version: capabilityVersion.trim(), capability_definition_hash: capabilityDefinitionHash.trim() })
      setMessage(`Runtime Binding created for ${deploymentId}.`)
      onRefresh()
    } catch (cause) { setMessage(cause instanceof Error ? cause.message : 'Runtime Binding creation failed.') } finally { setBusy(null) }
  }

  return <div className="space-y-4"><ScreenHeading eyebrow="Model materialization pipeline" title="Models" detail="Move in order: queue and materialize the model, discover a deployment, bind immutable artifacts when required, then create a Runtime Binding. Each transition reports its backend result." />
    {isLoading && !workspace ? <PanelSkeleton rows={6} /> : null}
    {error && !workspace ? <PanelError title="Model workspace is unavailable" error={error} onRetry={onRefresh} /> : null}
    {message ? <OperationNotice message={message} onDismiss={() => setMessage(null)} /> : null}
    <Card className="border-border/80 bg-card py-0 shadow-none"><CardHeader className="border-b border-border/70 px-5 py-4"><p className="eyebrow">Runtime policy</p><CardTitle className="mt-1 text-lg font-semibold">Operator defaults and customer controls</CardTitle><p className="mt-1 text-sm leading-6 text-muted-foreground">The value is applied when a request omits the parameter. The checkbox is enforced on the node. Keep context length and GPU allocation locked when VRAM is fixed.</p></CardHeader><CardContent className="grid gap-3 p-5 md:grid-cols-2 xl:grid-cols-5"><label className="grid gap-2"><span className="eyebrow">Temperature</span><input type="number" min="0" max="2" step="0.1" value={temperature} onChange={(event) => setTemperature(event.target.value)} className="h-10 rounded-lg border border-input bg-[#07111d] px-3 text-sm text-white outline-none focus:border-cyan-300" /><span className="flex items-center gap-2 text-xs text-slate-300"><input type="checkbox" checked={temperatureEditable} onChange={(event) => setTemperatureEditable(event.target.checked)} />Customer may change</span></label><label className="grid gap-2"><span className="eyebrow">Top P</span><input type="number" min="0" max="1" step="0.05" value={topP} onChange={(event) => setTopP(event.target.value)} className="h-10 rounded-lg border border-input bg-[#07111d] px-3 text-sm text-white outline-none focus:border-cyan-300" /><span className="flex items-center gap-2 text-xs text-slate-300"><input type="checkbox" checked={topPEditable} onChange={(event) => setTopPEditable(event.target.checked)} />Customer may change</span></label><label className="grid gap-2"><span className="eyebrow">Max tokens</span><input type="number" min="1" max="32768" step="1" value={maxTokens} onChange={(event) => setMaxTokens(event.target.value)} className="h-10 rounded-lg border border-input bg-[#07111d] px-3 text-sm text-white outline-none focus:border-cyan-300" /><span className="flex items-center gap-2 text-xs text-slate-300"><input type="checkbox" checked={maxTokensEditable} onChange={(event) => setMaxTokensEditable(event.target.checked)} />Customer may change</span></label><label className="grid gap-2"><span className="eyebrow">Context length</span><input type="number" min="512" max="131072" step="512" value={contextLength} onChange={(event) => setContextLength(event.target.value)} className="h-10 rounded-lg border border-input bg-[#07111d] px-3 text-sm text-white outline-none focus:border-cyan-300" /><span className="flex items-center gap-2 text-xs text-amber-200"><input type="checkbox" checked={contextLengthEditable} onChange={(event) => setContextLengthEditable(event.target.checked)} />Allow VRAM-affecting change</span></label><label className="grid gap-2"><span className="eyebrow">GPU memory utilization</span><input type="number" min="0.1" max="0.99" step="0.05" value={gpuMemoryUtilization} onChange={(event) => setGpuMemoryUtilization(event.target.value)} disabled={providerType === 'llama.cpp'} className="h-10 rounded-lg border border-input bg-[#07111d] px-3 text-sm text-white outline-none focus:border-cyan-300 disabled:opacity-40" /><span className="flex items-center gap-2 text-xs text-amber-200"><input type="checkbox" checked={gpuMemoryEditable} onChange={(event) => setGpuMemoryEditable(event.target.checked)} disabled={providerType === 'llama.cpp'} />Allow change</span></label></CardContent></Card>
    <Card className="border-border/80 bg-card py-0 shadow-none"><CardHeader className="border-b border-border/70 px-5 py-4"><p className="eyebrow">Operator inputs</p><CardTitle className="mt-1 text-lg font-semibold">Name the next immutable objects</CardTitle><p className="mt-1 text-sm leading-6 text-muted-foreground">These values stay in the dashboard flow; no terminal prompt is required for Bundle registration, provider materialization, or Runtime Binding.</p></CardHeader><CardContent className="grid gap-3 p-5 lg:grid-cols-4"><label className="grid gap-2"><span className="eyebrow">Bundle ID</span><input value={bundleId} onChange={(event) => setBundleId(event.target.value)} placeholder="bundle-whisper-small" className="h-10 rounded-lg border border-input bg-[#07111d] px-3 font-mono text-xs text-white outline-none focus:border-cyan-300" /></label><label className="grid gap-2"><span className="eyebrow">Capability version</span><input value={capabilityVersion} onChange={(event) => setCapabilityVersion(event.target.value)} className="h-10 rounded-lg border border-input bg-[#07111d] px-3 font-mono text-xs text-white outline-none focus:border-cyan-300" /></label><label className="grid gap-2 lg:col-span-2"><span className="eyebrow">Capability definition hash</span><input value={capabilityDefinitionHash} onChange={(event) => setCapabilityDefinitionHash(event.target.value)} placeholder="sha256:..." className="h-10 rounded-lg border border-input bg-[#07111d] px-3 font-mono text-xs text-white outline-none focus:border-cyan-300" /></label></CardContent></Card>
    <Card className="border-border/80 bg-card py-0 shadow-none"><CardHeader className="border-b border-border/70 px-5 py-4"><p className="eyebrow">Step 1</p><CardTitle className="mt-1 text-lg font-semibold">Install and materialize model</CardTitle><p className="mt-1 text-sm leading-6 text-muted-foreground">Paste a concrete Hugging Face file URL (GGUF for llama.cpp/Ollama) or a repository URL for vLLM. The node resolves and downloads it; the browser never supplies a target path or shell command.</p></CardHeader><CardContent className="grid gap-3 p-5 lg:grid-cols-4"><label className="grid gap-2"><span className="eyebrow">Provider type</span><select value={providerType} onChange={(event) => setProviderType(event.target.value)} className="h-10 rounded-lg border border-input bg-[#07111d] px-3 text-sm text-white outline-none focus:border-cyan-300"><option value="">Select Provider</option>{llmPlugins.map((plugin) => <option key={getText(plugin, 'plugin_id')} value={getText(plugin, 'plugin_id')}>{getText(plugin, 'display_name') || getText(plugin, 'plugin_id')}</option>)}</select></label><label className="grid gap-2"><span className="eyebrow">Model ID</span><input value={modelId} onChange={(event) => setModelId(event.target.value)} placeholder="qwen2.5-7b-instruct" className="h-10 rounded-lg border border-input bg-[#07111d] px-3 font-mono text-xs text-white outline-none focus:border-cyan-300" /></label><label className="grid gap-2 lg:col-span-2"><span className="eyebrow">Model page / file URL</span><input value={sourceUrl} onChange={(event) => setSourceUrl(event.target.value)} placeholder="https://huggingface.co/.../resolve/main/model.gguf" className="h-10 rounded-lg border border-input bg-[#07111d] px-3 text-xs text-white outline-none focus:border-cyan-300" /></label><label className="grid gap-2"><span className="eyebrow">Bundle workload</span><input value={workloadType} onChange={(event) => setWorkloadType(event.target.value)} className="h-10 rounded-lg border border-input bg-[#07111d] px-3 font-mono text-xs text-white outline-none focus:border-cyan-300" /></label><label className="grid gap-2 lg:col-span-2"><span className="eyebrow">Bundle endpoint</span><input value={endpoint} onChange={(event) => setEndpoint(event.target.value)} className="h-10 rounded-lg border border-input bg-[#07111d] px-3 font-mono text-xs text-white outline-none focus:border-cyan-300" /></label><div className="flex items-end gap-2"><Button className="bg-cyan-300 text-[#06121d] hover:bg-cyan-200" disabled={busy === 'install'} onClick={() => void installModel()}><Database />{busy === 'install' ? 'Queueing...' : 'Queue install'}</Button><Button variant="outline" className="border-border bg-[#091725]" disabled={busy === 'process'} onClick={() => void processInstalls()}><RefreshCw />{busy === 'process' ? 'Running...' : 'Materialize'}</Button></div></CardContent></Card>
    <Card className="border-border/80 bg-card py-0 shadow-none"><CardHeader className="border-b border-border/70 px-5 py-4"><p className="eyebrow">Install queue</p><CardTitle className="mt-1 text-lg font-semibold">Model install jobs</CardTitle></CardHeader><CardContent className="divide-y divide-border/70 p-0">{installs.length === 0 ? <p className="px-5 py-6 text-sm text-muted-foreground">No model installs queued.</p> : installs.map((install) => { const id = getText(install, 'install_id'); const status = getText(install, 'install_status') || getText(install, 'status') || 'unknown'; const canRegister = Boolean(getRecord(install)?.can_register_bundle) || status === 'completed'; return <div key={id} className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-center"><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><p className="font-medium text-slate-100">{getText(install, 'model_id')}</p><StatusBadge value={status} /></div><p className="mt-1 break-all font-mono text-[11px] text-slate-500">{getText(install, 'provider_type')} · {id} · {getText(install, 'target_path') || 'target reserved by node'}</p>{getText(install, 'last_error') ? <p className="mt-1 text-xs text-rose-200">{getText(install, 'last_error')}</p> : null}</div>{canRegister ? <Button variant="outline" size="sm" className="border-cyan-300/25 bg-[#091725] text-cyan-100" disabled={busy === `register:${id}`} onClick={() => void registerBundle(install)}><Boxes />Register Bundle</Button> : null}</div> })}</CardContent></Card>
    <Card className="border-border/80 bg-card py-0 shadow-none"><CardHeader className="border-b border-border/70 px-5 py-4"><p className="eyebrow">Optional artifact custody</p><CardTitle className="mt-1 text-lg font-semibold">Create immutable model artifact set</CardTitle></CardHeader><CardContent className="grid gap-3 p-5 lg:grid-cols-[1fr_2fr_auto]"><label className="grid gap-2"><span className="eyebrow">Display name</span><input value={artifactSetName} onChange={(event) => setArtifactSetName(event.target.value)} placeholder="Whisper small files" className="h-10 rounded-lg border border-input bg-[#07111d] px-3 text-sm text-white outline-none focus:border-cyan-300" /></label><label className="grid gap-2"><span className="eyebrow">Files JSON</span><input value={artifactFiles} onChange={(event) => setArtifactFiles(event.target.value)} className="h-10 rounded-lg border border-input bg-[#07111d] px-3 font-mono text-xs text-white outline-none focus:border-cyan-300" /></label><div className="flex items-end"><Button className="bg-cyan-300 text-[#06121d] hover:bg-cyan-200" disabled={busy === 'artifact-set'} onClick={() => void createArtifactSet()}><Layers3 />Create set</Button></div></CardContent></Card>
    <div className="grid gap-4 lg:grid-cols-2"><InventoryCard title="Artifact sets" detail="Content-addressed file manifests. Bind a set to a Model Deployment before Runtime Binding." items={artifactSets} primaryKey="artifact_set_id" /><InventoryCard title="Provider instances" detail={`${instances.length} provider instance(s) available for materialization.`} items={instances} primaryKey="provider_instance_id" /></div>
    <Card className="border-border/80 bg-card py-0 shadow-none"><CardHeader className="border-b border-border/70 px-5 py-4"><p className="eyebrow">Step 2 and 3</p><CardTitle className="mt-1 text-lg font-semibold">Deployments and Runtime Bindings</CardTitle></CardHeader><CardContent className="divide-y divide-border/70 p-0">{deployments.length === 0 ? <p className="px-5 py-6 text-sm text-muted-foreground">Discover models from the Providers screen first.</p> : deployments.map((deployment) => { const id = getText(deployment, 'model_deployment_id'); const artifactId = getText(deployment, 'artifact_set_id'); const providerId = getText(deployment, 'provider_instance_id'); return <div key={id} className="space-y-3 px-5 py-4"><div className="flex flex-wrap items-center justify-between gap-3"><div><p className="font-medium text-slate-100">{getText(deployment, 'operator_display_name') || getText(deployment, 'provider_model_reference')}</p><p className="mt-1 font-mono text-[11px] text-slate-500">{id} · provider {shortId(providerId)} · artifacts {artifactId || 'not bound'}</p></div><StatusBadge value={getText(deployment, 'artifact_materialization_status') || getText(deployment, 'operational_state') || 'unknown'} /></div><div className="flex flex-wrap gap-2"><select defaultValue={artifactId} onChange={(event) => void bindArtifactSet(deployment, event.target.value)} className="h-9 min-w-52 rounded-lg border border-input bg-[#07111d] px-3 font-mono text-xs text-white outline-none focus:border-cyan-300"><option value="">Bind artifact set...</option>{artifactSets.map((item) => <option key={getText(item, 'artifact_set_id')} value={getText(item, 'artifact_set_id')}>{getText(item, 'display_name') || getText(item, 'artifact_set_id')}</option>)}</select>{artifactId ? <Button variant="outline" size="sm" className="border-border bg-[#091725]" disabled={busy === `materialize:${id}`} onClick={() => void materialize(deployment, artifactId)}><Database />Materialize</Button> : null}<Button variant="outline" size="sm" className="border-cyan-300/25 bg-[#091725] text-cyan-100" disabled={busy === `binding:${id}` || (getText(deployment, 'artifact_materialization_required') === 'true' && getText(deployment, 'artifact_materialization_ready') !== 'true')} onClick={() => void createBinding(deployment)}><Zap />Create Runtime Binding</Button></div></div> })}</CardContent></Card>
  </div>
}

function SettingsAccessWorkspace() {
  const [status, setStatus] = useState<DashboardAccessStatus | null>(null)
  const [pairingCode, setPairingCode] = useState('')
  const [sessionDuration, setSessionDuration] = useState('one_day')
  const [label, setLabel] = useState('Local agent')
  const [revealedToken, setRevealedToken] = useState<string | null>(null)
  const [enrollments, setEnrollments] = useState<EnrollmentRequest[]>([])
  const [permissionCatalog, setPermissionCatalog] = useState<AgentPermissionCatalog | null>(null)
  const [selectedCredentialId, setSelectedCredentialId] = useState<string | null>(null)
  const [draftScopes, setDraftScopes] = useState<string[]>([])
  const [draftAutoApprovedScopes, setDraftAutoApprovedScopes] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const [networkMessage, setNetworkMessage] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  async function refreshAccess() {
    try {
      setError(null)
      const nextStatus = await dashboardApi.accessStatus()
      setStatus(nextStatus)
      if (nextStatus.session.active) {
        const [enrollmentResponse, catalog] = await Promise.all([
          dashboardApi.enrollmentRequests().catch(() => undefined),
          dashboardApi.agentPermissionCatalog().catch(() => undefined),
        ])
        setEnrollments(enrollmentResponse?.items ?? [])
        setPermissionCatalog(catalog ?? null)
      } else {
        setEnrollments([])
        setPermissionCatalog(null)
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'The access control service did not respond.')
    }
  }

  useEffect(() => { void refreshAccess() }, [])

  async function pair() {
    if (!pairingCode.trim()) return
    setBusy('pair')
    try {
      setError(null)
      await dashboardApi.pairDashboard(pairingCode.trim(), sessionDuration)
      setPairingCode('')
      await refreshAccess()
    } catch (cause) {
      setError(cause instanceof DashboardApiError ? cause.message : 'Pairing was rejected.')
    } finally { setBusy(null) }
  }

  async function updateNetworkAccess(mode: 'loopback' | 'lan') {
    if (!status?.network_access.apply_supported || !status.session.active) return
    setBusy('network')
    setError(null)
    setNetworkMessage(null)
    try {
      const result = await dashboardApi.updateDashboardNetworkAccess(mode)
      setStatus((current) => current ? { ...current, network_access: result } : current)
      if (result.restart_scheduled) {
        setNetworkMessage(mode === 'lan'
          ? 'LAN listener accepted. The Hypervisor is restarting and will bind 0.0.0.0 after the service comes back.'
          : 'Loopback-only listener accepted. This LAN tab will disconnect when the service restarts; use the host or an SSH tunnel to reconnect.')
      } else if (result.restart_required) {
        setNetworkMessage(`Saved ${mode === 'lan' ? 'LAN' : 'loopback'} access. Restart the Hypervisor service to apply the new listener.`)
      } else {
        setNetworkMessage(`Dashboard is already using ${mode === 'lan' ? 'LAN' : 'loopback'} access.`)
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Dashboard network access update failed.')
    } finally { setBusy(null) }
  }

  function selectNetworkMode(mode: 'loopback' | 'lan') {
    setNetworkMessage(null)
    setStatus((current) => current ? {
      ...current,
      network_access: {
        ...current.network_access,
        mode,
        configured_mode: mode,
        configured_host: mode === 'lan' ? '0.0.0.0' : '127.0.0.1',
        restart_required: current.network_access.effective_mode !== mode,
        restart_scheduled: false,
      },
    } : current)
  }

  async function issueCredential() {
    if (!label.trim()) return
    setBusy('create')
    try {
      setError(null)
      const issued = await dashboardApi.createAgentCredential(label.trim(), permissionCatalog?.default_scopes)
      setRevealedToken(issued?.token ?? null)
      await refreshAccess()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Credential creation failed.')
    } finally { setBusy(null) }
  }

  async function rotate(credential: AccessCredential) {
    setBusy(credential.credential_id)
    try {
      setError(null)
      const issued = await dashboardApi.rotateAgentCredential(credential.credential_id)
      setRevealedToken(issued?.token ?? null)
      await refreshAccess()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Credential rotation failed.')
    } finally { setBusy(null) }
  }

  async function revoke(credential: AccessCredential) {
    if (!window.confirm(`Revoke ${credential.label}? Any connected agent using it will lose access.`)) return
    setBusy(credential.credential_id)
    try {
      setError(null)
      await dashboardApi.revokeAgentCredential(credential.credential_id)
      await refreshAccess()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Credential revocation failed.')
    } finally { setBusy(null) }
  }

  function openPermissions(credential: AccessCredential) {
    setSelectedCredentialId(credential.credential_id)
    setDraftScopes(credential.scopes)
    setDraftAutoApprovedScopes(credential.auto_approved_scopes)
    setError(null)
  }

  function toggleScope(scope: string) {
    setDraftScopes((current) => {
      const next = current.includes(scope) ? current.filter((item) => item !== scope) : [...current, scope]
      if (!next.includes(scope)) setDraftAutoApprovedScopes((approved) => approved.filter((item) => item !== scope))
      return next
    })
  }

  function toggleAutoApproval(scope: string) {
    setDraftAutoApprovedScopes((current) => current.includes(scope)
      ? current.filter((item) => item !== scope)
      : [...current, scope])
    setDraftScopes((current) => current.includes(scope) ? current : [...current, scope])
  }

  function setExperimentalFullControl(enabled: boolean) {
    if (!permissionCatalog) return
    if (enabled) {
      if (!window.confirm('Grant all implemented MCP agent-plane permissions and automatic approval for every plan-bound action? This does not share wallet keys, the operator token, shell access, or consensus bypass.')) return
      setDraftScopes(permissionCatalog.full_control_scopes)
      setDraftAutoApprovedScopes(permissionCatalog.full_control_auto_approved_scopes)
      return
    }
    setDraftAutoApprovedScopes([])
  }

  async function savePermissions(credential: AccessCredential) {
    if (draftScopes.length === 0) {
      setError('Select at least one permission before saving.')
      return
    }
    setBusy(`permissions:${credential.credential_id}`)
    try {
      setError(null)
      await dashboardApi.updateAgentCredentialScopes(credential.credential_id, draftScopes, draftAutoApprovedScopes)
      setSelectedCredentialId(null)
      await refreshAccess()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Permission update failed.')
    } finally { setBusy(null) }
  }

  async function logout() {
    setBusy('logout')
    try {
      await dashboardApi.logoutDashboardAccess()
      setRevealedToken(null)
      await refreshAccess()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Dashboard sign-out failed.')
    } finally { setBusy(null) }
  }

  async function decideEnrollment(request: EnrollmentRequest, decision: 'approve' | 'reject') {
    if (decision === 'reject' && !window.confirm(`Reject enrollment request from ${request.label}?`)) return
    setBusy(request.request_id)
    try {
      setError(null)
      if (decision === 'approve') await dashboardApi.approveEnrollment(request.request_id)
      else await dashboardApi.rejectEnrollment(request.request_id)
      await refreshAccess()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Enrollment decision failed.')
    } finally { setBusy(null) }
  }

  const selectedCredential = status?.credentials.find((credential) => credential.credential_id === selectedCredentialId) ?? null
  if (selectedCredential) {
    const permissions = permissionCatalog?.items ?? []
    const isFullControl = permissionCatalog !== null
      && permissionCatalog.full_control_scopes.every((scope) => draftScopes.includes(scope))
      && permissionCatalog.full_control_auto_approved_scopes.every((scope) => draftAutoApprovedScopes.includes(scope))
    return <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between"><ScreenHeading eyebrow="Agent authority" title={`Permissions: ${selectedCredential.label}`} detail="Select the MCP tools this credential may discover and execute. Saving closes its current MCP sessions, so the agent must reconnect." /><Button variant="outline" className="border-border bg-[#091725]" onClick={() => setSelectedCredentialId(null)}>Back to agents</Button></div>
      {error ? <PanelError title="Permission update was not completed" detail={error} onRetry={() => void refreshAccess()} /> : null}
      <Card className="border-amber-300/25 bg-amber-300/[0.04] py-0 shadow-none"><CardContent className="flex gap-3 p-4"><ShieldCheck className="mt-0.5 size-4 shrink-0 text-amber-200" /><div><p className="text-sm font-semibold text-amber-100">Authority remains bounded</p><p className="mt-1 text-xs leading-5 text-amber-100/75">Permissions never expose private keys, arbitrary shell execution, consensus bypass, or operator credentials. For an action, both permission and “operator approved by default” must be enabled before the agent can apply its plan without a separate confirmation.</p></div></CardContent></Card>
      {!permissionCatalog ? <PanelSkeleton rows={5} /> : ['Read', 'Actions'].map((group) => <Card key={group} className="border-border/80 bg-card py-0 shadow-none"><CardHeader className="border-b border-border/70 px-5 py-4"><p className="eyebrow">{group === 'Read' ? 'Observation rights' : 'Operational rights'}</p><CardTitle className="mt-1 text-lg font-semibold">{group === 'Read' ? 'Read-only tools' : 'Plan-bound actions'}</CardTitle></CardHeader><CardContent className="divide-y divide-border/70 p-0">{permissions.filter((permission) => permission.category === group).map((permission) => <label key={permission.scope} className="flex cursor-pointer gap-3 px-5 py-4 transition hover:bg-white/[0.02]"><input type="checkbox" checked={draftScopes.includes(permission.scope)} onChange={() => toggleScope(permission.scope)} disabled={selectedCredential.state !== 'active'} className="mt-1 size-4 accent-cyan-300" /><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><p className="font-medium text-slate-100">{permission.label}</p><span className={cn('rounded border px-1.5 py-0.5 font-mono text-[10px] uppercase', permission.risk === 'critical' ? 'border-rose-300/30 text-rose-200' : permission.risk === 'high' ? 'border-amber-300/30 text-amber-200' : 'border-slate-500/30 text-slate-400')}>{permission.risk}</span></div><p className="mt-1 text-sm leading-5 text-muted-foreground">{permission.description}</p><p className="mt-2 font-mono text-[11px] text-slate-500">{permission.scope} · {permission.tool_names.join(', ')}</p></div></label>)}</CardContent></Card>)}
      {permissionCatalog ? <Card className="border-amber-300/25 bg-amber-300/[0.04] py-0 shadow-none"><CardHeader className="border-b border-amber-300/20 px-5 py-4"><p className="eyebrow text-amber-100">Default approval</p><CardTitle className="mt-1 text-lg font-semibold text-amber-50">Operator approved by default</CardTitle><p className="mt-1 text-sm leading-5 text-amber-100/75">Enable this only for actions the agent may apply without a separate operator confirmation. Enabling it also enables the corresponding action permission.</p></CardHeader><CardContent className="divide-y divide-amber-300/15 p-0">{permissions.filter((permission) => permission.approval_key).map((permission) => <label key={permission.scope} className="flex cursor-pointer items-start gap-3 px-5 py-4 transition hover:bg-white/[0.02]"><input type="checkbox" checked={draftAutoApprovedScopes.includes(permission.scope)} onChange={() => toggleAutoApproval(permission.scope)} disabled={selectedCredential.state !== 'active'} className="mt-0.5 size-4 accent-amber-300" /><span className="min-w-0"><span className="flex flex-wrap items-center gap-2 font-medium text-amber-50">{permission.label}<span className="rounded border border-amber-300/30 px-1.5 py-0.5 font-mono text-[10px] uppercase text-amber-200">{permission.risk}</span></span><span className="mt-1 block text-sm leading-5 text-amber-100/70">Both this checkbox and the action permission above must be enabled for automatic apply.</span></span></label>)}</CardContent></Card> : null}
      {permissionCatalog ? <Card className="border-rose-300/30 bg-rose-300/[0.04] py-0 shadow-none"><CardContent className="flex flex-col gap-3 p-5 sm:flex-row sm:items-start sm:justify-between"><div><p className="eyebrow text-rose-100">Experimental</p><p className="mt-1 font-semibold text-rose-50">Full agent-plane control</p><p className="mt-1 max-w-2xl text-sm leading-5 text-rose-100/75">Grants every implemented agent permission and automatically approves provider attachment, Bundle activation, and retirement. It is not operator impersonation: wallet keys, the operator token, shell access, and consensus authority remain unavailable.</p></div><label className="flex shrink-0 cursor-pointer items-center gap-2 rounded-lg border border-rose-300/30 bg-[#091725] px-3 py-2 text-sm font-medium text-rose-100"><input type="checkbox" checked={isFullControl} onChange={(event) => setExperimentalFullControl(event.target.checked)} disabled={selectedCredential.state !== 'active'} className="size-4 accent-rose-300" />Full rights</label></CardContent></Card> : null}
      <div className="flex flex-col gap-3 rounded-xl border border-border/80 bg-[#07111d] p-4 sm:flex-row sm:items-center sm:justify-between"><p className="text-sm leading-5 text-muted-foreground">{permissionCatalog?.note}</p><div className="flex shrink-0 gap-2"><Button variant="outline" className="border-border bg-[#091725]" onClick={() => setSelectedCredentialId(null)}>Cancel</Button><Button className="bg-cyan-300 text-[#06121d] hover:bg-cyan-200" disabled={selectedCredential.state !== 'active' || draftScopes.length === 0 || busy === `permissions:${selectedCredential.credential_id}`} onClick={() => void savePermissions(selectedCredential)}>{busy === `permissions:${selectedCredential.credential_id}` ? 'Saving...' : 'Save permissions'}</Button></div></div>
    </div>
  }

  return (
    <div className="space-y-4">
      <ScreenHeading eyebrow="Local access boundary" title="Settings" detail="Pair this browser from the node terminal, then manage agent credentials without exposing existing secret values." />
      {error ? <PanelError title="Access action was not completed" detail={error} onRetry={() => void refreshAccess()} /> : null}
      {!status ? <PanelSkeleton rows={4} /> : null}
      {status ? <>
         {status.transport.insecure_lan ? <Card className="border-amber-300/25 bg-amber-300/[0.04] py-0 shadow-none"><CardContent className="flex gap-3 p-4"><ShieldCheck className="mt-0.5 size-4 shrink-0 text-amber-200" /><div><p className="text-sm font-semibold text-amber-100">Private LAN transport</p><p className="mt-1 text-xs leading-5 text-amber-100/75">This node explicitly allows browser access over HTTP. Do not expose this dashboard outside the controlled LAN; production access requires HTTPS.</p></div></CardContent></Card> : null}
         <Card className="border-border/80 bg-card py-0 shadow-none">
           <CardHeader className="border-b border-border/70 px-5 py-4">
             <div className="flex flex-wrap items-start justify-between gap-3">
               <div><p className="eyebrow">Dashboard listener</p><CardTitle className="mt-1 text-lg font-semibold">Choose the access boundary</CardTitle><p className="mt-1 max-w-2xl text-sm leading-6 text-muted-foreground">Loopback keeps the UI on this host. LAN binds 0.0.0.0 so trusted devices on the local network can open it; the service restarts to apply the change.</p></div>
               <StatusBadge value={status.network_access.effective_mode === 'lan' ? 'LAN active' : 'loopback active'} />
             </div>
           </CardHeader>
           <CardContent className="space-y-4 p-5">
             <div className="grid gap-3 sm:grid-cols-2">
               <label className={cn('flex cursor-pointer gap-3 rounded-lg border p-4 transition', status.network_access.mode === 'loopback' ? 'border-cyan-300/50 bg-cyan-300/[0.07]' : 'border-border/70 bg-[#07111d] hover:border-cyan-300/30')}><input type="radio" name="dashboard-network-access" value="loopback" checked={status.network_access.mode === 'loopback'} onChange={() => selectNetworkMode('loopback')} disabled={!status.session.active || busy === 'network'} className="mt-1 size-4 accent-cyan-300" /><span><span className="block font-medium text-slate-100">Loopback only</span><span className="mt-1 block text-xs leading-5 text-muted-foreground">127.0.0.1 · only local browser sessions can reach the Dashboard.</span></span></label>
               <label className={cn('flex cursor-pointer gap-3 rounded-lg border p-4 transition', status.network_access.mode === 'lan' ? 'border-amber-300/50 bg-amber-300/[0.07]' : 'border-border/70 bg-[#07111d] hover:border-amber-300/30')}><input type="radio" name="dashboard-network-access" value="lan" checked={status.network_access.mode === 'lan'} onChange={() => selectNetworkMode('lan')} disabled={!status.session.active || busy === 'network'} className="mt-1 size-4 accent-amber-300" /><span><span className="block font-medium text-amber-50">LAN · 0.0.0.0</span><span className="mt-1 block text-xs leading-5 text-amber-100/70">Reachable on the trusted LAN; keep this HTTP endpoint off the public Internet.</span></span></label>
             </div>
             <div className="flex flex-col gap-3 rounded-lg border border-border/70 bg-[#07111d] p-4 sm:flex-row sm:items-center sm:justify-between"><div><p className="eyebrow">Current listener</p><p className="mt-1 font-mono text-sm text-slate-100">{status.network_access.effective_host}:{status.network_access.port}</p><p className="mt-1 text-xs leading-5 text-muted-foreground">{status.network_access.restart_required ? `Pending ${status.network_access.configured_mode === 'lan' ? 'LAN' : 'loopback'} configuration · restart required` : 'Effective and configured boundaries match.'}</p></div><Button className={status.network_access.mode === 'lan' ? 'bg-amber-200 text-[#191204] hover:bg-amber-100' : 'bg-cyan-300 text-[#06121d] hover:bg-cyan-200'} disabled={!status.session.active || !status.network_access.apply_supported || busy === 'network' || !status.network_access.restart_required} onClick={() => void updateNetworkAccess(status.network_access.mode)}>{busy === 'network' ? 'Applying...' : status.network_access.restart_required ? 'Apply listener' : 'Listener applied'}</Button></div>
             {!status.network_access.apply_supported ? <p className="text-xs leading-5 text-amber-200">This process was not started by the supported operator bootstrap, so the listener file is unavailable. Re-run the bootstrap before changing the network boundary here.</p> : null}
             {networkMessage ? <OperationNotice message={networkMessage} onDismiss={() => setNetworkMessage(null)} /> : null}
           </CardContent>
         </Card>
        {!status.enabled ? <PanelError title="Credential management is unavailable" detail="This Hypervisor was started without the encrypted local secret store. Re-run the supported operator bootstrap or configure the secret manager before enabling remote MCP access." /> : null}
        {status.enabled && !status.session.active ? <Card className="border-border/80 bg-card py-0 shadow-none"><CardHeader className="border-b border-border/70 px-5 py-4"><p className="eyebrow">Terminal-to-browser pairing</p><CardTitle className="mt-1 text-lg font-semibold">Trust this browser</CardTitle><p className="mt-1 text-sm leading-6 text-muted-foreground">On the Hypervisor host, run <code className="rounded bg-black/20 px-1.5 py-0.5 font-mono text-xs text-cyan-100">aidn-operator pair</code>. The one-time code creates a browser-bound session. The node stores only hashes of the browser key and session cookie; use Forget this browser to revoke it.</p></CardHeader><CardContent className="flex flex-col gap-3 p-5"><label className="grid gap-2"><span className="eyebrow">Pairing code</span><input value={pairingCode} onChange={(event) => setPairingCode(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') void pair() }} autoComplete="one-time-code" placeholder="Paste code from the node terminal" className="h-10 rounded-lg border border-input bg-[#07111d] px-3 text-sm text-white outline-none transition focus:border-cyan-300" /></label><label className="grid gap-2"><span className="eyebrow">Trust duration</span><select value={sessionDuration} onChange={(event) => setSessionDuration(event.target.value)} className="h-10 rounded-lg border border-input bg-[#07111d] px-3 text-sm text-white outline-none transition focus:border-cyan-300"><option value="ten_minutes">10 minutes</option><option value="one_day">1 day</option><option value="thirty_days">30 days</option><option value="forever">Indefinitely</option></select></label><div className="flex justify-end"><Button className="bg-cyan-300 text-[#06121d] hover:bg-cyan-200" disabled={!pairingCode.trim() || busy === 'pair'} onClick={() => void pair()}>{busy === 'pair' ? 'Pairing...' : 'Trust browser'}<ChevronRight /></Button></div></CardContent></Card> : null}
        {status.enabled && status.session.active ? <>
          <Card className="border-border/80 bg-card py-0 shadow-none"><CardHeader className="flex-row items-center justify-between gap-3 border-b border-border/70 px-5 py-4"><div><CardTitle className="text-lg font-semibold">Agent enrollment requests</CardTitle><p className="mt-1 text-sm text-muted-foreground">Agents generate an ephemeral encryption key and wait here. Approving sends the credential only in an encrypted envelope.</p></div><Button variant="outline" size="sm" className="border-border bg-[#091725]" onClick={() => void refreshAccess()}><RefreshCw />Refresh</Button></CardHeader><CardContent className="p-0">{enrollments.filter((request) => request.state === 'pending').length === 0 ? <EmptyState title="No pending agent requests" detail="An agent can request access without receiving an operator token or using the host shell." actionLabel="Refresh requests" onAction={() => void refreshAccess()} /> : <div className="divide-y divide-border/70">{enrollments.filter((request) => request.state === 'pending').map((request) => <div key={request.request_id} className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-center"><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><p className="font-medium text-white">{request.label}</p><StatusBadge value={request.state} /></div><p className="mt-1 truncate font-mono text-[11px] text-slate-400">{request.key_fingerprint} · expires {new Date(request.expires_at).toLocaleTimeString()}</p></div><div className="flex gap-2"><Button size="sm" className="bg-cyan-300 text-[#06121d] hover:bg-cyan-200" disabled={busy === request.request_id} onClick={() => void decideEnrollment(request, 'approve')}>Approve</Button><Button variant="outline" size="sm" className="border-rose-300/25 bg-[#091725] text-rose-50 hover:border-rose-300/60" disabled={busy === request.request_id} onClick={() => void decideEnrollment(request, 'reject')}>Reject</Button></div></div>)}</div>}</CardContent></Card>
          <Card className="border-border/80 bg-card py-0 shadow-none"><CardHeader className="flex-row items-start justify-between gap-4 border-b border-border/70 px-5 py-4"><div><p className="eyebrow">MCP agent credentials</p><CardTitle className="mt-1 text-lg font-semibold">Issue a new agent token</CardTitle><p className="mt-1 text-sm leading-6 text-muted-foreground">The token is shown once. An agent authenticates to this node with it; existing values cannot be displayed again.</p></div><Button variant="outline" size="sm" className="shrink-0 border-border bg-[#091725]" disabled={busy === 'logout'} onClick={() => void logout()}><LogOut />Sign out</Button></CardHeader><CardContent className="space-y-4 p-5"><p className="rounded-md border border-border/70 bg-[#07111d] px-3 py-2 font-mono text-[11px] text-slate-400">Operator authority: {status.operator_authority.configured ? status.operator_authority.fingerprint : 'not configured'} · never shared with agents</p><div className="flex flex-col gap-3 sm:flex-row sm:items-end"><label className="grid flex-1 gap-2"><span className="eyebrow">Agent label</span><input value={label} onChange={(event) => setLabel(event.target.value)} maxLength={96} placeholder="For example: coding-agent-node127" className="h-10 rounded-lg border border-input bg-[#07111d] px-3 text-sm text-white outline-none transition focus:border-cyan-300" /></label><Button className="bg-cyan-300 text-[#06121d] hover:bg-cyan-200" disabled={!label.trim() || busy === 'create'} onClick={() => void issueCredential()}><KeyRound />{busy === 'create' ? 'Issuing...' : 'Issue token'}</Button></div>{revealedToken ? <div className="rounded-lg border border-cyan-300/30 bg-cyan-300/[0.06] p-4"><div className="flex items-start justify-between gap-4"><div><p className="eyebrow text-cyan-100">Copy now</p><p className="mt-1 text-sm font-semibold text-cyan-50">New token is visible once</p></div><Button variant="outline" size="sm" className="border-cyan-300/25 bg-[#091725]" onClick={() => void navigator.clipboard.writeText(revealedToken)}><Copy />Copy</Button></div><code className="mt-3 block break-all rounded-md bg-black/25 p-3 font-mono text-xs leading-5 text-cyan-50">{revealedToken}</code><p className="mt-2 text-xs leading-5 text-cyan-100/75">Close this notice after transferring the value through an approved secret channel. Rotation immediately revokes the prior token.</p><Button variant="outline" size="sm" className="mt-3 border-border bg-[#091725]" onClick={() => setRevealedToken(null)}>I stored it</Button></div> : null}</CardContent></Card>
          <Card className="border-border/80 bg-card py-0 shadow-none"><CardHeader className="flex-row items-center justify-between gap-3 border-b border-border/70 px-5 py-4"><div><p className="eyebrow">Active inventory</p><CardTitle className="mt-1 text-lg font-semibold">Agent credentials</CardTitle></div><Button variant="outline" size="sm" className="border-border bg-[#091725]" onClick={() => void refreshAccess()}><RefreshCw />Refresh</Button></CardHeader><CardContent className="p-0">{status.credentials.length === 0 ? <EmptyState title="No agent credentials" detail="Issue a dedicated token for each agent or remote Hypervisor connection." actionLabel="Issue token" onAction={() => void issueCredential()} /> : <div className="divide-y divide-border/70">{status.credentials.map((credential) => <div key={credential.credential_id} className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-center"><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><p className="font-medium text-slate-100">{credential.label}</p><StatusBadge value={credential.state} /></div><p className="mt-1 truncate font-mono text-[11px] text-slate-500">{credential.fingerprint} · {credential.scopes.length} permissions · last used {credential.last_used_at ? new Date(credential.last_used_at).toLocaleString() : 'never'}</p></div>{credential.state === 'active' ? <div className="flex flex-wrap gap-2"><Button variant="outline" size="sm" className="border-cyan-300/30 bg-[#091725] text-cyan-100 hover:bg-cyan-300/10" disabled={busy === credential.credential_id} onClick={() => openPermissions(credential)}><ShieldCheck />Permissions</Button><Button variant="outline" size="sm" className="border-border bg-[#091725]" disabled={busy === credential.credential_id} onClick={() => void rotate(credential)}><RotateCcw />Rotate</Button><Button variant="outline" size="sm" className="border-rose-300/25 bg-transparent text-rose-100 hover:bg-rose-300/10" disabled={busy === credential.credential_id} onClick={() => void revoke(credential)}><Trash2 />Revoke</Button></div> : null}</div>)}</div>}</CardContent></Card>
        </> : null}
      </> : null}
    </div>
  )
}

function formatQAtoms(qAtoms: number) {
  return `${new Intl.NumberFormat(undefined, {
    maximumFractionDigits: 6,
    minimumFractionDigits: qAtoms !== 0 && Math.abs(qAtoms) < 1_000_000 ? 6 : 0,
  }).format(qAtoms / 1_000_000)} Q`
}

function parseQAtoms(value: string): number | null {
  const normalized = value.trim()
  const match = /^(\d+)(?:\.(\d{0,6}))?$/.exec(normalized)
  if (!match) return null
  try {
    const whole = BigInt(match[1])
    const fraction = BigInt((match[2] || '').padEnd(6, '0') || '0')
    const atoms = whole * 1_000_000n + fraction
    const numeric = Number(atoms)
    return Number.isSafeInteger(numeric) && numeric > 0 ? numeric : null
  } catch {
    return null
  }
}

function WalletActivityList({ title, items, emptyDetail }: { title: string; items: DashboardRecord[]; emptyDetail: string }) {
  return <Card className="border-border/80 bg-card py-0 shadow-none"><CardHeader className="border-b border-border/70 px-5 py-4"><CardTitle className="text-base font-semibold">{title}</CardTitle></CardHeader><CardContent className="p-0">{items.length === 0 ? <p className="px-5 py-6 text-sm leading-6 text-muted-foreground">{emptyDetail}</p> : <div className="divide-y divide-border/70">{items.slice(-6).reverse().map((item, index) => {
    const quote = getRecord(item)?.quote
    const charges = getRecord(getRecord(quote)?.charges)
    const amount = getText(item, 'amount_q') || getText(charges, 'total_q')
    return <div key={getText(item, 'event_id') || `${title}-${index}`} className="min-w-0 px-5 py-3"><div className="flex min-w-0 items-start justify-between gap-3"><div className="min-w-0"><p className="truncate text-sm font-medium text-slate-100">{getText(item, 'event_type') || 'Recorded activity'}</p><p className="mt-1 truncate font-mono text-[11px] text-slate-500">{getText(item, 'occurred_at') || getText(item, 'created_at') || 'Time not reported'}</p></div>{amount ? <p className="shrink-0 font-mono text-xs text-cyan-100">{amount} Q</p> : null}</div></div>
  })}</div>}</CardContent></Card>
}

function WalletLedgerOperations({ items, emptyDetail }: { items: DashboardRecord[]; emptyDetail: string }) {
  return <Card className="border-border/80 bg-card py-0 shadow-none"><CardHeader className="border-b border-border/70 px-5 py-4"><div className="flex items-center justify-between gap-3"><div><p className="eyebrow">Canonical record</p><CardTitle className="mt-1 text-base font-semibold">Ledger operations</CardTitle></div><StatusBadge value={items.length ? `${items.length} recorded` : 'empty'} /></div><p className="mt-1 text-xs leading-5 text-muted-foreground">Outgoing Wallet operations are read from the Hypervisor Ledger projection. A browser refresh never manufactures activity.</p></CardHeader><CardContent className="p-0">{items.length === 0 ? <p className="px-5 py-6 text-sm leading-6 text-muted-foreground">{emptyDetail}</p> : <div className="divide-y divide-border/70">{items.slice(-8).reverse().map((item, index) => {
    const payload = getRecord(item)?.payload
    const amountAtoms = Number(getRecord(payload)?.amount ?? getRecord(item)?.amount_q_atoms ?? 0)
    const recipient = getText(payload, 'recipient_wallet') || getText(item, 'recipient_wallet')
    const operationId = getText(item, 'operation_id') || getText(item, 'event_id')
    const status = getText(getRecord(item)?.result, 'status') || getText(item, 'status') || 'recorded'
    return <div key={operationId || `ledger-${index}`} className="flex flex-col gap-2 px-5 py-3 sm:flex-row sm:items-center sm:justify-between"><div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><p className="font-medium text-slate-100">{getText(item, 'operation_type') || 'Ledger operation'}</p><StatusBadge value={status} /></div><p className="mt-1 truncate font-mono text-[11px] text-slate-500">{shortId(operationId, 24)}{recipient ? ` · to ${shortId(recipient, 20)}` : ''}</p><p className="mt-1 text-xs text-muted-foreground">{getText(item, 'created_at') || getText(item, 'occurred_at') || 'Time not reported'}</p></div>{amountAtoms > 0 ? <p className="shrink-0 font-mono text-xs text-cyan-100">{formatQAtoms(amountAtoms)}</p> : null}</div>
  })}</div>}</CardContent></Card>
}

function WalletPendingOperations({ items }: { items: DashboardRecord[] }) {
  const activeItems = items.filter((item) => getText(item, 'submission_status') !== 'failed' && getText(item, 'status') !== 'failed')
  const failedItems = items.length - activeItems.length
  return <Card className={cn('border py-0 shadow-none', activeItems.length ? 'border-amber-300/25 bg-amber-300/[0.04]' : failedItems ? 'border-rose-300/25 bg-rose-300/[0.04]' : 'border-border/80 bg-card')}><CardHeader className="border-b border-border/70 px-5 py-4"><div className="flex items-center justify-between gap-3"><div><p className="eyebrow">Awaiting finality</p><CardTitle className="mt-1 text-base font-semibold">Pending transfers</CardTitle></div><StatusBadge value={activeItems.length ? `${activeItems.length} pending` : failedItems ? `${failedItems} rejected` : 'clear'} /></div><p className="mt-1 text-xs leading-5 text-muted-foreground">Rejected envelopes remain visible for diagnostics, but they do not reserve balance or count as active pending transfers.</p></CardHeader><CardContent className="p-0">{items.length === 0 ? <p className="px-5 py-6 text-sm leading-6 text-muted-foreground">No Wallet transfers are waiting for consensus.</p> : <div className="divide-y divide-border/70">{items.slice(-8).reverse().map((item, index) => { const operationId = getText(item, 'operation_id'); const amountAtoms = Number(getRecord(item)?.amount_q_atoms ?? 0); const error = getText(item, 'error'); return <div key={operationId || `pending-${index}`} className="px-5 py-3"><div className="flex flex-wrap items-center justify-between gap-2"><p className="font-mono text-xs text-amber-50">{shortId(operationId, 24)}</p><StatusBadge value={getText(item, 'submission_status') || getText(item, 'status') || 'pending'} /></div><p className="mt-1 text-xs text-muted-foreground">To {shortId(getText(item, 'recipient_wallet'), 24)} · sequence {String(getRecord(item)?.sender_sequence ?? '—')} · {formatQAtoms(amountAtoms)}</p>{error ? <p className="mt-2 text-xs text-rose-200">{error}</p> : null}</div> })}</div>}</CardContent></Card>
}

function WalletTransferWorkspace({ walletId, onRefresh }: { walletId: string; onRefresh: () => void }) {
  const [recipientWallet, setRecipientWallet] = useState('')
  const [amountQ, setAmountQ] = useState('')
  const [memo, setMemo] = useState('')
  const [preview, setPreview] = useState<DashboardRecord | null>(null)
  const [result, setResult] = useState<DashboardRecord | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<'preview' | 'submit' | null>(null)
  const amountQAtoms = parseQAtoms(amountQ)
  const requestPayload = amountQAtoms === null ? null : { recipient_wallet: recipientWallet.trim(), amount_q_atoms: amountQAtoms, ...(memo.trim() ? { memo: memo.trim() } : {}) }

  function resetPreview() {
    setPreview(null)
    setResult(null)
    setError(null)
  }

  async function createPreview() {
    if (!requestPayload?.recipient_wallet || amountQAtoms === null) {
      setError('Enter a recipient Wallet and a positive Q amount with no more than six decimal places.')
      return
    }
    setBusy('preview')
    setError(null)
    setResult(null)
    try {
      const response = await dashboardApi.previewWalletTransfer(requestPayload)
      setPreview(getRecord(response) ?? null)
      if (!getRecord(response)) setError('The Hypervisor returned no transfer preview.')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Transfer preview failed.')
    } finally {
      setBusy(null)
    }
  }

  async function submitTransfer() {
    if (!requestPayload || !preview) return
    if (getRecord(preview)?.sufficient_balance === false) {
      setError('The Owner Wallet does not have enough Q for the transfer and network fee.')
      return
    }
    setBusy('submit')
    setError(null)
    try {
      const response = await dashboardApi.submitWalletTransfer(requestPayload)
      const nextResult = getRecord(response) ?? null
      setResult(nextResult)
      onRefresh()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Wallet transfer failed.')
      onRefresh()
    } finally {
      setBusy(null)
    }
  }

  const previewAmount = Number(getRecord(preview)?.amount_q_atoms ?? 0)
  const previewFee = Number(getRecord(preview)?.network_fee_q_atoms ?? 0)
  const previewTotal = Number(getRecord(preview)?.total_debit_q_atoms ?? 0)
  const previewInsufficient = getRecord(preview)?.sufficient_balance === false
  const resultStatus = getText(result, 'status')
  const resultFinality = getRecord(getRecord(result)?.finality)

  return <Card className="border-cyan-300/20 bg-cyan-300/[0.03] py-0 shadow-none"><CardHeader className="border-b border-cyan-300/15 px-5 py-4"><div className="flex flex-wrap items-start justify-between gap-3"><div><p className="eyebrow text-cyan-100">Operator payment</p><CardTitle className="mt-1 text-lg font-semibold">Transfer Q</CardTitle><p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">Send Q from the configured Owner Wallet to another Wallet. The server signs the canonical operation; this form never receives a private key.</p></div><ArrowRightLeft className="mt-1 size-5 text-cyan-200" /></div></CardHeader><CardContent className="space-y-4 p-5"><div className="grid gap-3 lg:grid-cols-[1.2fr_0.7fr_1fr_auto]"><label className="grid gap-2"><span className="eyebrow">Recipient Wallet</span><input value={recipientWallet} onChange={(event) => { setRecipientWallet(event.target.value); resetPreview() }} placeholder="wallet-..." autoComplete="off" className="h-10 rounded-lg border border-input bg-[#07111d] px-3 font-mono text-xs text-white outline-none focus:border-cyan-300" /><span className="text-xs text-muted-foreground">Sender: {shortId(walletId, 24)}</span></label><label className="grid gap-2"><span className="eyebrow">Amount in Q</span><input value={amountQ} onChange={(event) => { setAmountQ(event.target.value); resetPreview() }} inputMode="decimal" placeholder="0.000000" className="h-10 rounded-lg border border-input bg-[#07111d] px-3 font-mono text-sm text-white outline-none focus:border-cyan-300" /><span className="text-xs text-muted-foreground">Stored as integer q_atoms.</span></label><label className="grid gap-2"><span className="eyebrow">Memo (optional)</span><input value={memo} onChange={(event) => { setMemo(event.target.value); resetPreview() }} maxLength={256} placeholder="Operator note" className="h-10 rounded-lg border border-input bg-[#07111d] px-3 text-sm text-white outline-none focus:border-cyan-300" /><span className="text-xs text-muted-foreground">Only a memo hash enters the Ledger.</span></label><div className="flex items-end"><Button className="w-full bg-cyan-300 text-[#06121d] hover:bg-cyan-200" disabled={busy !== null || !requestPayload?.recipient_wallet || amountQAtoms === null} onClick={() => void createPreview()}><Gauge />{busy === 'preview' ? 'Checking...' : 'Preview transfer'}</Button></div></div>{error ? <OperationNotice message={error} onDismiss={() => setError(null)} /> : null}{preview ? <div className={cn('rounded-lg border p-4', previewInsufficient ? 'border-rose-300/30 bg-rose-300/[0.05]' : 'border-cyan-300/25 bg-[#07111d]')}><div className="flex flex-wrap items-start justify-between gap-3"><div><p className="eyebrow">Review before signing</p><p className="mt-1 text-sm font-semibold text-slate-100">{formatQAtoms(previewAmount)} to {shortId(getText(preview, 'recipient_wallet'), 28)}</p><p className="mt-1 text-xs leading-5 text-muted-foreground">Sequence {String(getRecord(preview)?.sender_sequence ?? '—')} · {getRecord(preview)?.consensus_required ? 'consensus finality required' : 'local ledger mode'}</p></div><StatusBadge value={previewInsufficient ? 'insufficient balance' : 'ready'} /></div><div className="mt-4 grid gap-3 sm:grid-cols-3"><div><p className="eyebrow">Network fee</p><p className="mt-1 font-mono text-sm text-slate-100">{formatQAtoms(previewFee)}</p></div><div><p className="eyebrow">Total debit</p><p className="mt-1 font-mono text-sm text-slate-100">{formatQAtoms(previewTotal)}</p></div><div><p className="eyebrow">Available</p><p className="mt-1 font-mono text-sm text-slate-100">{formatQAtoms(Number(getRecord(preview)?.available_balance_q_atoms ?? 0))}</p></div></div><div className="mt-4 flex flex-wrap gap-2"><Button className="bg-cyan-300 text-[#06121d] hover:bg-cyan-200" disabled={busy !== null || previewInsufficient} onClick={() => void submitTransfer()}><ArrowRightLeft />{busy === 'submit' ? 'Submitting...' : 'Submit transfer'}</Button><Button variant="outline" className="border-border bg-[#091725]" disabled={busy !== null} onClick={resetPreview}>Edit transfer</Button></div></div> : null}{result ? <div className="rounded-lg border border-emerald-300/25 bg-emerald-300/[0.04] p-4"><div className="flex flex-wrap items-start justify-between gap-3"><div><p className="eyebrow text-emerald-100">Operation result</p><p className="mt-1 text-sm font-semibold text-emerald-50">{resultStatus === 'CONSENSUS_PENDING' ? 'Transfer is awaiting consensus finality.' : 'Transfer was finalized.'}</p><p className="mt-1 break-all font-mono text-xs text-emerald-100/75">{getText(result, 'operation_id') || 'Operation ID unavailable'}</p></div><StatusBadge value={resultStatus || 'recorded'} /></div><p className="mt-3 text-xs leading-5 text-emerald-100/75">{resultFinality?.status ? `Finality: ${String(resultFinality.status)}.` : 'Refresh the Wallet read model to inspect the canonical outcome.'} {resultStatus === 'CONSENSUS_PENDING' ? 'Do not submit another transfer for this sequence while it is pending.' : ''}</p></div> : null}</CardContent></Card>
}

function WalletIdentityRegistrationWorkspace({
  walletState,
  busy,
  onRegister,
  onRefresh,
}: {
  walletState: WalletDashboard['wallet_state']
  busy: boolean
  onRegister: () => void
  onRefresh: () => void
}) {
  const state = walletState.identity_registration_state || (walletState.identity_state === 'registered' ? 'registered' : 'not_registered')
  const operation = getRecord(walletState.identity_operation)
  const registered = state === 'registered'
  const pending = state === 'pending'
  const rejected = state === 'rejected'
  const unavailable = state === 'unavailable'
  const tone = registered
    ? 'border-emerald-300/25 bg-emerald-300/[0.04]'
    : rejected
      ? 'border-rose-300/25 bg-rose-300/[0.04]'
      : 'border-amber-300/25 bg-amber-300/[0.04]'
  const title = registered
    ? 'Network identity is registered'
    : pending
      ? 'Network identity registration is pending'
      : rejected
        ? 'Network identity registration was rejected'
        : unavailable
          ? 'Network identity status is unavailable'
          : 'Wallet is bound, but network identity is not registered'
  const detail = registered
    ? 'The current chain projection contains the identity for this Wallet. No new registration is required.'
    : pending
      ? 'The signed WALLET_IDENTITY_REGISTER operation was submitted. Refresh this read model after consensus finality; do not submit a duplicate.'
      : rejected
        ? 'The previous signed operation was rejected. Correct the reported cause, then create a fresh consensus operation for the same Wallet.'
        : unavailable
          ? 'The configured canonical identity source is unavailable. The Dashboard will not claim registration from a local projection.'
          : 'Register this same Wallet in the current chain. This does not replace ownership or create a second Wallet.'
  return <Card className={cn('py-0 shadow-none', tone)}><CardContent className="flex flex-col gap-4 p-4 lg:flex-row lg:items-start lg:justify-between"><div className="flex min-w-0 gap-3"><span className={cn('mt-0.5 shrink-0', registered ? 'text-emerald-200' : rejected ? 'text-rose-200' : 'text-amber-200')}><CircleDot className="size-4" /></span><div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><p className={cn('text-sm font-semibold', registered ? 'text-emerald-100' : rejected ? 'text-rose-100' : 'text-amber-100')}>{title}</p><StatusBadge value={state} /></div><p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">{detail}</p>{operation ? <div className="mt-3 grid gap-2 rounded-lg border border-white/10 bg-black/10 p-3 text-xs sm:grid-cols-2"><div><p className="eyebrow">Operation ID</p><p className="mt-1 break-all font-mono text-slate-200">{getText(operation, 'operation_id') || 'Unavailable'}</p></div><div><p className="eyebrow">Consensus lifecycle</p><p className="mt-1 text-slate-200">Submission: {getText(operation, 'submission_status') || 'not observed'} · Finality: {getText(operation, 'status') || 'not finalized'}</p></div>{getText(operation, 'sender_sequence') ? <div><p className="eyebrow">Wallet sequence</p><p className="mt-1 font-mono text-slate-200">{getText(operation, 'sender_sequence')}</p></div> : null}{getText(operation, 'error') ? <div className="sm:col-span-2"><p className="eyebrow text-rose-200">Rejection reason</p><p className="mt-1 break-words text-rose-100">{getText(operation, 'error')}</p></div> : null}</div> : null}{walletState.identity_error ? <p className="mt-2 text-xs leading-5 text-amber-200">Canonical identity source: {String(walletState.identity_error)}</p> : null}</div></div><div className="flex shrink-0 flex-wrap gap-2 lg:pt-0.5">{pending || registered || unavailable ? <Button variant="outline" className="border-border bg-[#091725]" disabled={busy} onClick={onRefresh}><RefreshCw />{busy ? 'Refreshing...' : registered ? 'Refresh identity' : 'Check status'}</Button> : null}{!registered && !pending && !unavailable ? <Button className={cn(rejected ? 'bg-rose-200 text-[#1d080b] hover:bg-rose-100' : 'bg-amber-200 text-[#191204] hover:bg-amber-100')} disabled={busy} onClick={onRegister}><CircleDot />{busy ? 'Submitting...' : rejected ? 'Retry registration' : 'Register in network'}</Button> : null}</div></CardContent></Card>
}

function WalletWorkspace({ wallet, isLoading, error, onRefresh }: { wallet: WalletDashboard | undefined; isLoading: boolean; error: Error | null; onRefresh: () => void }) {
  const [label, setLabel] = useState('Primary Wallet')
  const [privateKey, setPrivateKey] = useState('')
  const [mode, setMode] = useState<'create' | 'import'>('create')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [revealedKey, setRevealedKey] = useState<string | null>(null)
  const ownerWallet = wallet?.owner_wallet
  const walletState = wallet?.wallet_state
  const configured = Boolean(ownerWallet?.configured)
  const identityRegistered = walletState?.identity_state === 'registered'
  const identityRegistrationState = walletState?.identity_registration_state || (identityRegistered ? 'registered' : 'not_registered')
  const balance = walletState?.canonical_balance_q_atoms ?? 0
  const economics = getRecord(getRecord(wallet?.economics_summary)?.removals)

  async function configureWallet() {
    if (mode === 'import' && !privateKey.trim()) {
      setMessage('Paste the existing private key before importing the Wallet.')
      return
    }
    setBusy(true)
    setMessage(null)
    try {
      const result = mode === 'create'
        ? await dashboardApi.createOwnerWallet(label.trim())
        : await dashboardApi.importOwnerWallet(label.trim(), privateKey.trim())
      const key = getText(result, 'private_key')
      if (key) setRevealedKey(key)
      const status = getText(result, 'status')
      setMessage(status === 'CONSENSUS_PENDING'
        ? 'Wallet bind was submitted to consensus and is pending finality. Refresh this screen after the node observes the transaction.'
        : mode === 'create' ? 'Owner Wallet was created and bound to this Hypervisor.' : 'Owner Wallet was imported and bound to this Hypervisor.')
      setPrivateKey('')
      onRefresh()
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : 'Wallet configuration failed.')
    } finally {
      setBusy(false)
    }
  }

  async function registerNetworkIdentity() {
    setBusy(true)
    setMessage(null)
    try {
      const result = await dashboardApi.registerOwnerWalletIdentity()
      const status = getText(result, 'status')
      const operationId = shortId(getText(result, 'operation_id'))
      setMessage(status === 'CONSENSUS_PENDING'
        ? `Network identity registration was submitted${operationId ? ` (${operationId})` : ''}. It will appear after the configured consensus quorum finalizes it; refresh this screen in a few seconds.`
        : 'Network identity is registered for the current Wallet on this chain.')
      onRefresh()
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : 'Network identity registration failed.')
    } finally {
      setBusy(false)
    }
  }

  return <div className="space-y-4"><ScreenHeading eyebrow="Operator ownership" title="Wallet" detail="Inspect the owner Wallet's ledger projection, binding and registry identity. Private key material is never returned to the Dashboard." />
    {isLoading && !wallet ? <PanelSkeleton rows={4} /> : null}
    {error && !wallet ? <PanelError title="Wallet state is unavailable" error={error} onRetry={onRefresh} /> : null}
    {error && wallet ? <PanelError title="Wallet refresh did not complete" detail="The last confirmed Wallet projection remains visible below. Retry when the Hypervisor API is reachable." onRetry={onRefresh} /> : null}
    {configured ? <Card className="border-emerald-300/25 bg-emerald-300/[0.04] py-0 shadow-none"><CardContent className="flex gap-3 p-5"><WalletCards className="mt-0.5 size-5 shrink-0 text-emerald-300" /><div><p className="font-semibold text-emerald-50">Owner Wallet configured</p><p className="mt-1 text-sm text-emerald-100/75">{ownerWallet?.label || 'Owner Wallet'} · <span className="font-mono">{shortId(ownerWallet?.wallet_id)}</span></p><p className="mt-2 text-xs leading-5 text-emerald-100/65">Changing ownership is intentionally not an in-place Dashboard action. It requires the future signed ownership-transfer protocol.</p></div></CardContent></Card> : <Card className="border-border/80 bg-card py-0 shadow-none"><CardHeader className="border-b border-border/70 px-5 py-4"><p className="eyebrow">Wallet bootstrap</p><CardTitle className="mt-1 text-lg font-semibold">Bind node ownership</CardTitle><p className="mt-1 text-sm leading-6 text-muted-foreground">Create a new key once or import a key you already control. The request follows the canonical wallet-binding path; a validator node may report a pending consensus operation before the binding becomes active.</p></CardHeader><CardContent className="space-y-4 p-5"><div className="flex flex-wrap gap-2"><Button variant={mode === 'create' ? 'default' : 'outline'} className={cn(mode === 'create' ? 'bg-cyan-300 text-[#06121d] hover:bg-cyan-200' : 'border-border bg-[#091725]')} onClick={() => setMode('create')}>Create Wallet</Button><Button variant={mode === 'import' ? 'default' : 'outline'} className={cn(mode === 'import' ? 'bg-cyan-300 text-[#06121d] hover:bg-cyan-200' : 'border-border bg-[#091725]')} onClick={() => setMode('import')}>Import Wallet</Button></div><label className="grid gap-2"><span className="eyebrow">Wallet label</span><input value={label} onChange={(event) => setLabel(event.target.value)} maxLength={128} className="h-10 rounded-lg border border-input bg-[#07111d] px-3 text-sm text-white outline-none focus:border-cyan-300" /></label>{mode === 'import' ? <label className="grid gap-2"><span className="eyebrow">Existing private key</span><input type="password" value={privateKey} onChange={(event) => setPrivateKey(event.target.value)} autoComplete="off" placeholder="ed25519:..." className="h-10 rounded-lg border border-input bg-[#07111d] px-3 font-mono text-xs text-white outline-none focus:border-cyan-300" /><span className="text-xs leading-5 text-muted-foreground">The key is submitted only to the node's encrypted Wallet bootstrap service and is never added to the Dashboard read-model.</span></label> : null}<div className="flex justify-end"><Button className="bg-cyan-300 text-[#06121d] hover:bg-cyan-200" disabled={busy} onClick={() => void configureWallet()}><KeyRound />{busy ? 'Binding...' : mode === 'create' ? 'Create and bind' : 'Import and bind'}</Button></div></CardContent></Card>}
    {configured && wallet ? <>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Card className="border-border/80 bg-card py-0 shadow-none"><CardContent className="p-5"><p className="text-sm text-muted-foreground">Canonical balance</p><p className="mt-2 break-all font-mono text-2xl font-semibold tracking-tight text-cyan-100">{formatQAtoms(balance)}</p><p className="mt-2 text-xs leading-5 text-muted-foreground">{walletState?.balance_source === 'remote_consensus_quorum' ? 'Verified by the configured consensus RPC quorum.' : walletState?.balance_source === 'consensus_projection' ? 'Current validator consensus projection.' : walletState?.balance_source === 'local_projection_unverified' ? 'Remote consensus balance is unavailable; this is an unverified local projection.' : 'Local ledger projection.'}</p>{walletState?.balance_error ? <p className="mt-2 text-xs leading-5 text-amber-200">{String(walletState.balance_error)}</p> : null}</CardContent></Card>
        <Card className="border-border/80 bg-card py-0 shadow-none"><CardContent className="p-5"><p className="text-sm text-muted-foreground">Binding</p><p className="mt-2 text-xl font-semibold capitalize text-slate-100">{walletState?.binding_state || 'unknown'}</p><p className="mt-2 text-xs leading-5 text-muted-foreground">{walletState?.binding_state === 'pending' ? 'Waiting for the canonical bind operation to finalize.' : 'Owner Wallet is available to node operations.'}</p></CardContent></Card>
        <Card className={cn('border py-0 shadow-none', identityRegistrationState === 'registered' ? 'border-emerald-300/25 bg-emerald-300/[0.04]' : identityRegistrationState === 'rejected' ? 'border-rose-300/25 bg-rose-300/[0.04]' : 'border-amber-300/25 bg-amber-300/[0.04]')}><CardContent className="p-5"><p className="text-sm text-muted-foreground">Network identity</p><p className={cn('mt-2 text-xl font-semibold capitalize', identityRegistrationState === 'registered' ? 'text-emerald-100' : identityRegistrationState === 'rejected' ? 'text-rose-100' : 'text-amber-100')}>{identityRegistrationState.replace('_', ' ')}</p><p className="mt-2 text-xs leading-5 text-muted-foreground">{identityRegistered ? 'Identity evidence is visible in the current registry projection.' : identityRegistrationState === 'pending' ? 'Signed registration is awaiting consensus finality.' : identityRegistrationState === 'rejected' ? 'The last registration attempt was rejected.' : 'No finalized wallet identity record is visible in this chain projection.'}</p></CardContent></Card>
         <Card className="border-border/80 bg-card py-0 shadow-none"><CardContent className="p-5"><p className="text-sm text-muted-foreground">Recorded usage</p><p className="mt-2 font-mono text-2xl font-semibold tracking-tight text-slate-100">{wallet.usage_events.length}</p><p className="mt-2 text-xs leading-5 text-muted-foreground">{wallet.allocation_events.length} allocation events and {wallet.dispute_events.length} disputes retained locally.</p></CardContent></Card>
       </div>
       <WalletTransferWorkspace walletId={String(ownerWallet?.wallet_id || walletState?.wallet_id || '')} onRefresh={onRefresh} />
       <WalletPendingOperations items={wallet.pending_operations} />
       {walletState ? <WalletIdentityRegistrationWorkspace walletState={walletState} busy={busy} onRegister={() => void registerNetworkIdentity()} onRefresh={onRefresh} /> : null}
       <div className="grid gap-4 xl:grid-cols-2"><WalletActivityList title="Usage activity" items={wallet.usage_events} emptyDetail="No metered usage has been recorded for this Wallet." /><WalletActivityList title="Allocation activity" items={wallet.allocation_events} emptyDetail="No allocation or settlement events have been recorded for this Wallet." /></div>
       <WalletLedgerOperations items={wallet.ledger_operations} emptyDetail="No finalized Wallet ledger operations have been recorded for this Wallet." />
      <Card className="border-border/80 bg-card py-0 shadow-none"><CardHeader className="border-b border-border/70 px-5 py-4"><CardTitle className="text-base font-semibold">Economic record</CardTitle><p className="mt-1 text-sm leading-6 text-muted-foreground">These are local accounting events. The external faucet is a separate Treasury service and is not represented as a claimable balance here.</p></CardHeader><CardContent className="grid gap-4 p-5 sm:grid-cols-3"><div><p className="text-sm text-muted-foreground">Recyclable removals</p><p className="mt-1 font-mono text-lg text-slate-100">{String(economics?.count ?? 0)}</p></div><div><p className="text-sm text-muted-foreground">Removed value</p><p className="mt-1 font-mono text-lg text-slate-100">{String(economics?.total_q ?? 0)} Q</p></div><div><p className="text-sm text-muted-foreground">Faucet integration</p><p className="mt-1 text-sm font-medium text-slate-100">External service</p></div></CardContent></Card>
    </> : null}
    {revealedKey ? <Card className="border-amber-300/30 bg-amber-300/[0.05] py-0 shadow-none"><CardHeader className="border-b border-amber-300/20 px-5 py-4"><p className="eyebrow text-amber-100">Store immediately</p><CardTitle className="mt-1 text-lg font-semibold text-amber-50">New private key is visible once</CardTitle></CardHeader><CardContent className="p-5"><code className="block break-all rounded-lg bg-black/25 p-3 font-mono text-xs leading-5 text-amber-50">{revealedKey}</code><div className="mt-3 flex flex-wrap gap-2"><Button variant="outline" size="sm" className="border-amber-300/30 bg-[#091725] text-amber-100" onClick={() => void navigator.clipboard.writeText(revealedKey)}><Copy />Copy key</Button><Button variant="outline" size="sm" className="border-border bg-[#091725]" onClick={() => setRevealedKey(null)}>I stored it</Button></div></CardContent></Card> : null}
    {message ? <OperationNotice message={message} onDismiss={() => setMessage(null)} /> : null}
  </div>
}

function SettingsWorkspace({ fleet, onRefresh }: { fleet: DashboardData['fleet']['data']; onRefresh: () => void }) {
  return (
    <div className="space-y-4">
      <ResourceProbeControl fleet={fleet} onRefresh={onRefresh} />
      <SettingsAccessWorkspace />
    </div>
  )
}

function ResourceProbeControl({ fleet, onRefresh }: { fleet: DashboardData['fleet']['data']; onRefresh: () => void }) {
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const probe = fleet?.resources.probe

  async function refreshProbe() {
    setBusy(true)
    setMessage(null)
    try {
      await dashboardApi.probeResources()
      setMessage('Host capacity was measured and the Dashboard read-models were refreshed.')
      onRefresh()
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : 'Resource probe failed.')
    } finally {
      setBusy(false)
    }
  }

  return <Card className="border-border/80 bg-card py-0 shadow-none"><CardHeader className="flex-row items-start justify-between gap-4 border-b border-border/70 px-5 py-4"><div><p className="eyebrow">Host capacity</p><CardTitle className="mt-1 text-lg font-semibold">Resource probe</CardTitle><p className="mt-1 max-w-2xl text-sm leading-6 text-muted-foreground">Measure CPU, memory, storage and supported GPU capacity directly on this Hypervisor. The browser never supplies resource values.</p></div><Button className="bg-cyan-300 text-[#06121d] hover:bg-cyan-200" disabled={busy} onClick={() => void refreshProbe()}><Gauge />{busy ? 'Measuring...' : 'Run probe'}</Button></CardHeader><CardContent className="p-5"><div className="rounded-lg border border-border/70 bg-[#07111d] p-3"><p className="eyebrow">Last evidence</p><p className="mt-1 text-sm text-slate-200">{getText(probe, 'source') || 'No current probe record'}</p><p className="mt-1 text-xs leading-5 text-muted-foreground">{Array.isArray(probe?.limitations) && probe.limitations.length > 0 ? String(probe.limitations[0]) : 'A paired operator session is required to run this local measurement.'}</p></div>{message ? <div className="mt-3"><OperationNotice message={message} onDismiss={() => setMessage(null)} /></div> : null}</CardContent></Card>
}

function providerAttachFields(plugin: DashboardRecord | undefined): DashboardRecord[] {
  const schema = getRecord(plugin?.attach_ui_schema)
  return Array.isArray(schema?.fields)
    ? schema.fields.filter((field): field is DashboardRecord => Boolean(getRecord(field)))
    : []
}

function providerInstallFields(plugin: DashboardRecord | undefined): DashboardRecord[] {
  const schema = getRecord(plugin?.install_ui_schema)
  return Array.isArray(schema?.fields)
    ? schema.fields.filter((field): field is DashboardRecord => Boolean(getRecord(field)))
    : []
}

function providerFieldDefault(field: DashboardRecord): unknown {
  if (field.default !== undefined) return field.default
  if (Array.isArray(field.options)) {
    const firstOption = getRecord(field.options[0])
    return firstOption?.value ?? ''
  }
  if (field.type === 'boolean') return false
  return ''
}

function providerConfigurationDefaults(plugin: DashboardRecord | undefined): DashboardRecord {
  return Object.fromEntries(providerAttachFields(plugin).map((field) => [getText(field, 'id'), providerFieldDefault(field)]).filter(([id]) => Boolean(id)))
}

function providerInstallConfigurationDefaults(plugin: DashboardRecord | undefined): DashboardRecord {
  const fields = providerInstallFields(plugin)
  const defaults = Object.fromEntries(fields.map((field) => [getText(field, 'id'), providerFieldDefault(field)]).filter(([id]) => Boolean(id)))
  const recipes = Array.isArray(plugin?.installation_recipes) ? plugin.installation_recipes : []
  const recipe = getRecord(recipes[0])
  const recipeConfiguration = getRecord(recipe?.provider_configuration) ?? {}
  return { ...defaults, ...recipeConfiguration }
}

function providerRuntimeConfigurationFor(plugin: DashboardRecord | undefined, instances: DashboardRecord[]): DashboardRecord {
  const id = getText(plugin, 'plugin_id')
  const existing = instances.find((instance) => getText(instance, 'plugin_id') === id && getText(instance, 'connection_mode') === 'managed' && getText(instance, 'operational_state') !== 'removed')
  return {
    ...providerInstallConfigurationDefaults(plugin),
    ...(getRecord(existing)?.configuration ?? {}),
  }
}

function providerFieldValue(configuration: DashboardRecord, field: DashboardRecord): string | boolean {
  const value = configuration[getText(field, 'id')]
  if (field.type === 'boolean') return value === true
  return typeof value === 'string' || typeof value === 'number' ? String(value) : ''
}

function providerFieldOptions(field: DashboardRecord): DashboardRecord[] {
  return Array.isArray(field.options)
    ? field.options.filter((option): option is DashboardRecord => Boolean(getRecord(option)))
    : []
}

function providerConfigurationIssue(plugin: DashboardRecord | undefined, displayName: string, configuration: DashboardRecord): string | null {
  const fields = providerAttachFields(plugin)
  if (!displayName.trim()) return 'Set a display name for the Provider instance.'
  for (const field of fields) {
    const id = getText(field, 'id')
    const value = id === 'display_name' ? displayName : configuration[id]
    if (field.required === true && (value === undefined || value === null || String(value).trim() === '')) {
      return `${getText(field, 'label') || id} is required.`
    }
    if (getText(field, 'type') === 'url' && value) {
      try {
        const parsed = new URL(String(value))
        if (!['http:', 'https:'].includes(parsed.protocol)) throw new Error('unsupported protocol')
      } catch {
        return `${getText(field, 'label') || id} must be an absolute HTTP URL.`
      }
    }
  }
  return null
}

function providerInstallConfigurationIssue(plugin: DashboardRecord | undefined, configuration: DashboardRecord): string | null {
  for (const field of providerInstallFields(plugin)) {
    const id = getText(field, 'id')
    const value = configuration[id]
    if (field.required === true && (value === undefined || value === null || String(value).trim() === '')) {
      return `${getText(field, 'label') || id} is required.`
    }
    if (getText(field, 'type') === 'url' && value) {
      try {
        const parsed = new URL(String(value))
        if (!['http:', 'https:'].includes(parsed.protocol)) throw new Error('unsupported protocol')
      } catch {
        return `${getText(field, 'label') || id} must be an absolute HTTP URL.`
      }
    }
  }
  return null
}

function ProviderWorkspaceScreen({ screen, workspace, isLoading, error, onRefresh }: { screen: 'providers' | 'catalog'; workspace: ProviderWorkspace | undefined; isLoading: boolean; error: Error | null; onRefresh: () => void }) {
  const [pluginId, setPluginId] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [configuration, setConfiguration] = useState<DashboardRecord>({})
  const [runtimePluginId, setRuntimePluginId] = useState('')
  const [runtimeConfiguration, setRuntimeConfiguration] = useState<DashboardRecord>({})
  const [busy, setBusy] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const plugins = workspace?.plugin_directory ?? []
  const instances = (workspace?.provider_instances ?? []).filter((instance) => getText(instance, 'operational_state') !== 'removed')
  const deployments = workspace?.model_deployments ?? []
  const bindings = workspace?.runtime_bindings ?? []
  const runtimeExecutor = getRecord(workspace?.installation_executor)
  const runtimeSandbox = getRecord(runtimeExecutor?.sandbox_capabilities)
  const runtimeInstallEnabled = runtimeSandbox?.host_mutation === true
  const selectedPlugin = plugins.find((plugin) => getText(plugin, 'plugin_id') === pluginId)
  const attachFields = providerAttachFields(selectedPlugin)
  const runtimePlugins = plugins.filter((plugin) => {
    const installers = getRecord(plugin)?.runtime_installers
    return Array.isArray(installers) && installers.length > 0
  })
  const installedRuntimeIds = new Set(
    instances
      .filter((instance) => getText(instance, 'connection_mode') === 'managed' && getText(instance, 'operational_state') !== 'removed')
      .map((instance) => getText(instance, 'plugin_id'))
      .filter(Boolean),
  )
  const installedRuntimeIdsKey = Array.from(installedRuntimeIds).sort().join(',')
  const runtimePlugin = runtimePlugins.find((plugin) => getText(plugin, 'plugin_id') === runtimePluginId)
  const runtimePluginRecord = getRecord(runtimePlugin)
  const runtimeInstallers = Array.isArray(runtimePluginRecord?.runtime_installers) ? runtimePluginRecord.runtime_installers : []
  const runtimeInstalled = installedRuntimeIds.has(runtimePluginId)
  const runtimeInstaller = getRecord(runtimeInstallers[0])
  const runtimeConfigurationIssue = runtimePlugin
    ? providerInstallConfigurationIssue(runtimePlugin, runtimeConfiguration)
    : null

  useEffect(() => {
    if (!pluginId && plugins.length > 0) {
      const firstPlugin = plugins[0]
      const nextPlugin = getText(firstPlugin, 'plugin_id')
      setPluginId(nextPlugin)
      setDisplayName(getText(firstPlugin, 'display_name') || nextPlugin)
      setConfiguration(providerConfigurationDefaults(firstPlugin))
    }
  }, [pluginId, plugins])

  useEffect(() => {
    if (runtimePlugins.length === 0) {
      if (runtimePluginId) setRuntimePluginId('')
      return
    }
    if (!runtimePluginId || !runtimePlugins.some((plugin) => getText(plugin, 'plugin_id') === runtimePluginId)) {
      const installedIds = new Set(installedRuntimeIdsKey ? installedRuntimeIdsKey.split(',') : [])
      const installed = runtimePlugins.find((plugin) => installedIds.has(getText(plugin, 'plugin_id')))
      const nextPlugin = installed ?? runtimePlugins[0]
      const nextPluginId = getText(nextPlugin, 'plugin_id')
      setRuntimePluginId(nextPluginId)
      setRuntimeConfiguration(providerInstallConfigurationDefaults(nextPlugin))
    }
  }, [installedRuntimeIdsKey, runtimePluginId, runtimePlugins])

  function choosePlugin(nextPluginId: string) {
    setPluginId(nextPluginId)
    const plugin = plugins.find((item) => getText(item, 'plugin_id') === nextPluginId)
    if (plugin) {
      setDisplayName(getText(plugin, 'display_name') || nextPluginId)
      setConfiguration(providerConfigurationDefaults(plugin))
    }
  }

  function chooseRuntimePlugin(nextPluginId: string) {
    setRuntimePluginId(nextPluginId)
    const plugin = runtimePlugins.find((item) => getText(item, 'plugin_id') === nextPluginId)
    setRuntimeConfiguration(providerRuntimeConfigurationFor(plugin, instances))
  }

  async function attach() {
    const issue = providerConfigurationIssue(selectedPlugin, displayName, configuration)
    if (!pluginId || issue) {
      setMessage(issue || 'Select a Provider plugin and set a display name.')
      return
    }
    const parsedConfiguration: DashboardRecord = {
      ...configuration,
      ...(attachFields.some((field) => getText(field, 'id') === 'display_name') ? { display_name: displayName.trim() } : {}),
    }
    setBusy('attach')
    setMessage(null)
    try {
      const result = await dashboardApi.attachProvider({ plugin_id: pluginId, display_name: displayName.trim(), configuration: parsedConfiguration })
      const providerInstanceId = getText(result, 'provider_instance_id')
      if (providerInstanceId) {
        try {
          const health = getRecord(await dashboardApi.providerOperation(providerInstanceId, 'probe'))
          const diagnostic = getRecord(health?.diagnostic)
          setMessage(health?.healthy === true
            ? `Provider ${providerInstanceId} was attached and is healthy.`
            : `Provider ${providerInstanceId} was attached but is unavailable. ${getText(diagnostic, 'message') || getText(health, 'error') || 'Run Probe again after starting the service.'}`)
        } catch {
          setMessage(`Provider ${providerInstanceId} was attached. Probe it before using it for a Bundle.`)
        }
      } else {
        setMessage(`Provider ${displayName.trim()} was attached. Probe it before using it for a Bundle.`)
      }
      onRefresh()
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : 'Provider attachment failed.')
    } finally {
      setBusy(null)
    }
  }

  async function runProviderOperation(providerInstanceId: string, action: 'probe' | 'discover-models') {
    setBusy(`${providerInstanceId}:${action}`)
    setMessage(null)
    try {
      const result = await dashboardApi.providerOperation(providerInstanceId, action)
      const payload = getRecord(result)
      const discovered = payload?.items
      if (action === 'discover-models') {
        setMessage(`Model discovery completed: ${Array.isArray(discovered) ? discovered.length : 0} model deployment(s) found.`)
      } else {
        const diagnostic = getRecord(payload?.diagnostic)
        setMessage(payload?.healthy === true
          ? `Provider ${providerInstanceId} is healthy.`
          : `Provider ${providerInstanceId} is unhealthy. ${getText(diagnostic, 'message') || getText(payload, 'error') || 'Check the endpoint and service logs.'}`)
      }
      onRefresh()
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : 'Provider operation failed.')
    } finally {
      setBusy(null)
    }
  }

  async function applyRuntimeChange(action: 'install' | 'change') {
    const plugin = runtimePlugin
    const providerId = getText(plugin, 'plugin_id')
    if (!providerId || !plugin) {
      setMessage('Select a Provider runtime first.')
      return
    }
    if (runtimeInstallers.length === 0) {
      setMessage(`Provider ${providerId} has no reviewed Ubuntu runtime installer.`)
      return
    }
    if (!runtimeInstallEnabled) {
      setMessage('Runtime installation is unavailable until this node exposes the root-owned broker.')
      return
    }
    if (runtimeConfigurationIssue) {
      setMessage(runtimeConfigurationIssue)
      return
    }
    const displayName = getText(plugin, 'display_name') || providerId
    setBusy(`runtime:${action}:${providerId}`)
    setMessage(`${action === 'change' ? 'Changing' : 'Installing'} ${displayName}. The reviewed runtime may take a few minutes; model setup remains separate.`)
    try {
      // Pressing Install/Change is the operator's explicit acknowledgement of
      // the reviewed permission and sandbox contract for this runtime action.
      const result = getRecord(await dashboardApi.providerRuntimeAction(providerId, action, runtimeConfiguration, undefined, true))
      const status = getText(result, 'status')
      const providerInstanceId = getText(result, 'provider_instance_id')
      if (status !== 'SUCCEEDED') {
        const failureDetail = getText(result, 'error') || getText(result, 'error_message')
        setMessage(`${displayName} ${action} ${status ? status.toLowerCase() : 'did not complete'}.${failureDetail ? ` ${failureDetail}` : ' Review the installation job details and retry.'}`)
        onRefresh()
        return
      }
      if (providerInstanceId) {
        try {
          const health = getRecord(await dashboardApi.providerOperation(providerInstanceId, 'probe'))
          setMessage(health?.healthy === true
            ? `${displayName} ${action === 'change' ? 'changed' : 'installed'} and passed its health check. Model setup remains separate.`
            : `${displayName} ${action === 'change' ? 'changed' : 'installed'}, but the health check is not ready yet. Retry Probe when the runtime settles.`)
        } catch {
          setMessage(`${displayName} ${action === 'change' ? 'changed' : 'installed'}, but its health check could not complete. Retry Probe.`)
        }
      } else {
        setMessage(`${displayName} ${action === 'change' ? 'change' : 'installation'} completed. Refresh Provider instances to continue.`)
      }
      onRefresh()
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : `Provider runtime ${action} failed.`)
    } finally {
      setBusy(null)
    }
  }

  async function removeRuntime() {
    const plugin = runtimePlugin
    const providerId = getText(plugin, 'plugin_id')
    if (!providerId || !plugin) {
      setMessage('Select an installed Provider runtime first.')
      return
    }
    if (!window.confirm(`Remove ${getText(plugin, 'display_name') || providerId}? Model deployments and runtime bindings must be removed first.`)) return
    setBusy(`runtime:remove:${providerId}`)
    setMessage(`Removing ${getText(plugin, 'display_name') || providerId}. Model files and caches are preserved where supported.`)
    try {
      const result = getRecord(await dashboardApi.providerRuntimeAction(providerId, 'remove'))
      const status = getText(result, 'status')
      setMessage(status === 'REMOVED'
        ? `${getText(plugin, 'display_name') || providerId} runtime removed. Model setup remains available for a later install.`
        : `${getText(plugin, 'display_name') || providerId} removal ${status ? status.toLowerCase() : 'completed'}.`)
      onRefresh()
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : 'Provider runtime removal failed.')
    } finally {
      setBusy(null)
    }
  }

  const title = screen === 'catalog' ? 'Catalog' : 'Provider Plugins'
  const detail = screen === 'catalog'
    ? 'Select a real Provider Plugin, attach an existing local service, then discover its model supply. The next Bundle revision remains a separate immutable operation.'
    : 'Provider Plugins are the backing execution systems for Bundles. They are never published directly to Consumers.'

  return <div className="space-y-4"><ScreenHeading eyebrow={screen === 'catalog' ? 'Operator catalog' : 'Runtime supply'} title={title} detail={detail} />
    {message ? <OperationNotice message={message} onDismiss={() => setMessage(null)} /> : null}
    {isLoading && !workspace ? <PanelSkeleton rows={5} /> : null}
    {error && !workspace ? <PanelError title="Provider workspace is unavailable" error={error} onRetry={onRefresh} /> : null}
    {workspace ? <>
      <Card className="border-cyan-300/20 bg-cyan-300/[0.03] py-0 shadow-none"><CardHeader className="border-b border-border/70 px-5 py-4"><div className="flex flex-wrap items-start justify-between gap-3"><div><p className="eyebrow text-cyan-100">Reviewed Ubuntu runtimes</p><CardTitle className="mt-1 text-lg font-semibold">Provider runtime catalog</CardTitle><p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">Select one runtime from the compact catalog. Installed runtimes expose Change and Remove; model selection and downloads remain a separate step.</p></div><StatusBadge value={runtimeInstalled ? 'installed' : runtimeInstallEnabled ? 'available' : 'blocked'} /></div></CardHeader><CardContent className="space-y-4 p-5">{runtimePlugins.length === 0 ? <EmptyState title="No reviewed runtimes available" detail="This node has no Provider Plugin with an allowlisted Ubuntu runtime installer." actionLabel="Refresh catalog" onAction={onRefresh} /> : <><div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(16rem,0.8fr)]"><label className="grid gap-2"><span className="eyebrow">Provider runtime</span><select value={runtimePluginId} onChange={(event) => chooseRuntimePlugin(event.target.value)} className="h-10 rounded-lg border border-input bg-[#07111d] px-3 text-sm text-white outline-none focus:border-cyan-300"><optgroup label="Installed">{runtimePlugins.filter((plugin) => installedRuntimeIds.has(getText(plugin, 'plugin_id'))).map((plugin) => <option key={getText(plugin, 'plugin_id')} value={getText(plugin, 'plugin_id')}>{getText(plugin, 'display_name') || getText(plugin, 'plugin_id')}</option>)}</optgroup><optgroup label="Available">{runtimePlugins.filter((plugin) => !installedRuntimeIds.has(getText(plugin, 'plugin_id'))).map((plugin) => <option key={getText(plugin, 'plugin_id')} value={getText(plugin, 'plugin_id')}>{getText(plugin, 'display_name') || getText(plugin, 'plugin_id')}</option>)}</optgroup></select></label><div className="rounded-lg border border-border/70 bg-[#07111d] px-3 py-2"><p className="eyebrow">Pinned runtime</p><p className="mt-1 text-sm text-slate-100">{getText(runtimeInstaller, 'pinned_version') || 'Reviewed version'}</p><p className="mt-1 text-xs text-muted-foreground">{getText(runtimeInstaller, 'platform') || 'ubuntu'} · {runtimeInstalled ? 'Runtime is managed on this node.' : 'Not installed on this node.'}</p></div></div>{runtimeInstalled ? <p className="text-xs leading-5 text-amber-100/80">Change re-runs the reviewed installer against the selected configuration. Remove is blocked while model deployments or runtime bindings still reference this runtime.</p> : <p className="text-xs leading-5 text-muted-foreground">Install is enabled only when the root-owned allowlisted broker is available. Runtime files are separate from model downloads.</p>}{providerInstallFields(runtimePlugin).length > 0 ? <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{providerInstallFields(runtimePlugin).map((field) => { const id = getText(field, 'id'); const type = getText(field, 'type'); const value = providerFieldValue(runtimeConfiguration, field); const options = providerFieldOptions(field); return <label key={id} className="grid gap-2"><span className="eyebrow">{getText(field, 'label') || id}{field.required === true ? ' *' : ''}</span>{type === 'select' ? <select value={String(value)} onChange={(event) => setRuntimeConfiguration((current) => ({ ...current, [id]: event.target.value }))} className="h-10 rounded-lg border border-input bg-[#07111d] px-3 text-sm text-white outline-none focus:border-cyan-300">{options.map((option) => <option key={String(option.value)} value={String(option.value)}>{getText(option, 'label') || String(option.value)}</option>)}</select> : type === 'boolean' ? <span className="flex h-10 items-center gap-2 rounded-lg border border-input bg-[#07111d] px-3 text-sm text-slate-200"><input type="checkbox" checked={value === true} onChange={(event) => setRuntimeConfiguration((current) => ({ ...current, [id]: event.target.checked }))} />Enabled</span> : <input type={type === 'url' ? 'url' : 'text'} value={String(value)} onChange={(event) => setRuntimeConfiguration((current) => ({ ...current, [id]: event.target.value }))} placeholder={String(field.default ?? '')} className="h-10 rounded-lg border border-input bg-[#07111d] px-3 text-sm text-white outline-none focus:border-cyan-300" />}</label> })}</div> : null}<div className="flex flex-wrap gap-2">{!runtimeInstalled ? <Button className="bg-cyan-300 text-[#06121d] hover:bg-cyan-200" disabled={!runtimeInstallEnabled || busy !== null || Boolean(runtimeConfigurationIssue)} onClick={() => void applyRuntimeChange('install')}><ServerCog />{busy === `runtime:install:${runtimePluginId}` ? 'Installing...' : 'Install runtime'}</Button> : null}{runtimeInstalled ? <><Button variant="outline" className="border-cyan-300/25 bg-[#091725] text-cyan-100" disabled={!runtimeInstallEnabled || busy !== null || Boolean(runtimeConfigurationIssue)} onClick={() => void applyRuntimeChange('change')}><Settings />{busy === `runtime:change:${runtimePluginId}` ? 'Changing...' : 'Change runtime'}</Button><Button variant="destructive" className="border-rose-300/30" disabled={!runtimeInstallEnabled || busy !== null} onClick={() => void removeRuntime()}><Trash2 />{busy === `runtime:remove:${runtimePluginId}` ? 'Removing...' : 'Remove runtime'}</Button></> : null}</div></>}</CardContent></Card>
      <Card className="border-border/80 bg-card py-0 shadow-none"><CardHeader className="border-b border-border/70 px-5 py-4"><p className="eyebrow">Attach existing Provider</p><CardTitle className="mt-1 text-lg font-semibold">Create Provider instance</CardTitle><p className="mt-1 text-sm leading-6 text-muted-foreground">Choose a plugin first. The fields below come from that plugin's contract, so vLLM uses its OpenAI-compatible endpoint instead of inheriting an Ollama URL.</p></CardHeader><CardContent className="grid gap-4 p-5 md:grid-cols-2 lg:grid-cols-4"><label className="grid gap-2"><span className="eyebrow">Plugin</span><select value={pluginId} onChange={(event) => choosePlugin(event.target.value)} className="h-10 rounded-lg border border-input bg-[#07111d] px-3 text-sm text-white outline-none focus:border-cyan-300">{plugins.map((plugin) => <option key={getText(plugin, 'plugin_id')} value={getText(plugin, 'plugin_id')}>{getText(plugin, 'display_name') || getText(plugin, 'plugin_id')}</option>)}</select></label><label className="grid gap-2"><span className="eyebrow">Provider name</span><input value={displayName} onChange={(event) => setDisplayName(event.target.value)} placeholder="Local vLLM" className="h-10 rounded-lg border border-input bg-[#07111d] px-3 text-sm text-white outline-none focus:border-cyan-300" /></label>{attachFields.filter((field) => getText(field, 'id') !== 'display_name').map((field) => { const id = getText(field, 'id'); const type = getText(field, 'type'); const value = providerFieldValue(configuration, field); const options = providerFieldOptions(field); return <label key={id} className="grid gap-2"><span className="eyebrow">{getText(field, 'label') || id}{field.required === true ? ' *' : ''}</span>{type === 'select' ? <select value={String(value)} onChange={(event) => setConfiguration((current) => ({ ...current, [id]: event.target.value }))} className="h-10 rounded-lg border border-input bg-[#07111d] px-3 text-sm text-white outline-none focus:border-cyan-300">{options.map((option) => <option key={String(option.value)} value={String(option.value)}>{getText(option, 'label') || String(option.value)}</option>)}</select> : type === 'boolean' ? <span className="flex h-10 items-center gap-2 rounded-lg border border-input bg-[#07111d] px-3 text-sm text-slate-200"><input type="checkbox" checked={value === true} onChange={(event) => setConfiguration((current) => ({ ...current, [id]: event.target.checked }))} />Enabled</span> : <input type={type === 'url' ? 'url' : 'text'} value={String(value)} onChange={(event) => setConfiguration((current) => ({ ...current, [id]: event.target.value }))} placeholder={String(field.default ?? '')} className="h-10 rounded-lg border border-input bg-[#07111d] px-3 text-sm text-white outline-none focus:border-cyan-300" />}</label> })}<div className="flex items-end"><Button className="w-full bg-cyan-300 text-[#06121d] hover:bg-cyan-200" disabled={busy === 'attach' || plugins.length === 0} onClick={() => void attach()}><ServerCog />{busy === 'attach' ? 'Attaching...' : 'Attach'}</Button></div></CardContent></Card>
      <Card className="border-border/80 bg-card py-0 shadow-none"><CardHeader className="flex-row items-center justify-between gap-3 border-b border-border/70 px-5 py-4"><div><p className="eyebrow">Attached inventory</p><CardTitle className="mt-1 text-lg font-semibold">Provider instances</CardTitle><p className="mt-1 text-xs text-muted-foreground">Unhealthy is an observed state, not an installation failure. Open the probe detail before changing runtime or model settings.</p></div><Button variant="outline" size="sm" className="border-border bg-[#091725]" onClick={onRefresh}><RefreshCw />Refresh</Button></CardHeader><CardContent className="divide-y divide-border/70 p-0">{instances.length === 0 ? <EmptyState title="No Provider instances attached" detail="Attach a known local Provider above. The Dashboard will not guess an upstream endpoint or create credentials." actionLabel="Refresh catalog" onAction={onRefresh} /> : instances.map((instance) => { const id = getText(instance, 'provider_instance_id'); const record = getRecord(instance); const providerConfiguration = getRecord(record?.configuration); const healthError = getText(record, 'last_health_error'); return <div key={id} className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-center"><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><p className="font-medium text-white">{getText(instance, 'display_name') || id}</p><StatusBadge value={getText(instance, 'health_status') || 'unknown'} /></div><p className="mt-1 break-all font-mono text-[11px] text-slate-500">{id} · {getText(providerConfiguration, 'endpoint') || getText(providerConfiguration, 'base_url') || 'endpoint not declared'} · {String(record?.model_count ?? 0)} models · {String(record?.runtime_binding_ready_count ?? 0)} ready bindings</p>{healthError ? <p className="mt-2 max-w-3xl text-xs leading-5 text-rose-200">{healthError}</p> : null}</div><div className="flex flex-wrap gap-2"><Button variant="outline" size="sm" className="border-border bg-[#091725]" disabled={busy === `${id}:probe`} onClick={() => void runProviderOperation(id, 'probe')}><Gauge />Probe</Button><Button variant="outline" size="sm" className="border-cyan-300/25 bg-[#091725] text-cyan-100" disabled={busy === `${id}:discover-models`} onClick={() => void runProviderOperation(id, 'discover-models')}><Database />Discover models</Button></div></div> })}</CardContent></Card>
      <div className="grid gap-4 lg:grid-cols-2"><InventoryCard title="Model deployments" detail="Discovered model supply. Runtime binding is required before Endpoint admission." items={deployments} primaryKey="model_deployment_id" /><InventoryCard title="Runtime bindings" detail="Compatibility records backing eligible Bundle and Endpoint runtime selection." items={bindings} primaryKey="runtime_binding_id" /></div>
    </> : null}
  </div>
}

function InventoryCard({ title, detail, items, primaryKey }: { title: string; detail: string; items: DashboardRecord[]; primaryKey: string }) {
  return <Card className="border-border/80 bg-card py-0 shadow-none"><CardHeader className="border-b border-border/70 px-5 py-4"><CardTitle className="text-base font-semibold">{title}</CardTitle><p className="mt-1 text-xs leading-5 text-muted-foreground">{detail}</p></CardHeader><CardContent className="p-0">{items.length === 0 ? <p className="px-5 py-6 text-sm text-muted-foreground">No records yet.</p> : <div className="divide-y divide-border/70">{items.slice(0, 8).map((item) => <div key={getText(item, primaryKey)} className="px-5 py-3"><div className="flex items-center justify-between gap-3"><p className="truncate font-mono text-xs text-slate-200">{shortId(getText(item, primaryKey), 24)}</p><StatusBadge value={getText(item, 'status') || 'recorded'} /></div></div>)}</div>}</CardContent></Card>
}

function OperationNotice({ message, onDismiss }: { message: string; onDismiss: () => void }) {
  const failed = /failed|rejected|required|invalid|unavailable|error/i.test(message)
  return <div role={failed ? 'alert' : 'status'} aria-live="polite" className={cn('flex items-start justify-between gap-3 rounded-lg border p-3 text-sm', failed ? 'border-rose-300/25 bg-rose-300/[0.05] text-rose-100' : 'border-emerald-300/25 bg-emerald-300/[0.05] text-emerald-100')}><div className="flex items-start gap-2"><span className="mt-0.5" aria-hidden="true">{failed ? <XCircle className="size-4" /> : <CheckCircle2 className="size-4" />}</span><p className="leading-5">{message}</p></div><Button variant="ghost" size="icon-xs" className="shrink-0" aria-label="Dismiss operation result" onClick={onDismiss}><XCircle /></Button></div>
}

function OperationsWorkspace({ screen, data, onNavigate, onRefresh }: { screen: OperationsScreen; data: DashboardData; onNavigate: NavigationProps['onNavigate']; onRefresh: () => void }) {
  if (screen === 'agents') return <AgentsWorkspace data={data} onNavigate={onNavigate} onRefresh={onRefresh} />
  if (screen === 'market') return <MarketWorkspace data={data} onNavigate={onNavigate} onRefresh={onRefresh} />
  if (screen === 'validation') return <ValidationWorkspace data={data} onNavigate={onNavigate} onRefresh={onRefresh} />
  return <NetworkWorkspace data={data} onNavigate={onNavigate} onRefresh={onRefresh} />
}

function AgentsWorkspace({ data, onNavigate, onRefresh }: { data: DashboardData; onNavigate: NavigationProps['onNavigate']; onRefresh: () => void }) {
  return <AgentsSessionsWorkspace data={data} onNavigate={onNavigate} onRefresh={onRefresh} />
}

function AgentsSessionsWorkspace({ data, onNavigate, onRefresh }: { data: DashboardData; onNavigate: NavigationProps['onNavigate']; onRefresh: () => void }) {
  const sessions = data.sessions.data
  const [busy, setBusy] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [idleOnly, setIdleOnly] = useState(false)
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null)
  const [agentAccessSummary, setAgentAccessSummary] = useState('Checking delegated access...')
  const [activeAgentCredentials, setActiveAgentCredentials] = useState<AccessCredential[]>([])

  useEffect(() => {
    let active = true
    void dashboardApi.accessStatus().then((status) => {
      if (!active) return
      const activeCredentials = status.credentials.filter((credential) => credential.state === 'active').length
      setActiveAgentCredentials(status.credentials.filter((credential) => credential.state === 'active'))
      setAgentAccessSummary(status.session.active
        ? `${activeCredentials} active MCP credential${activeCredentials === 1 ? '' : 's'} · operator session paired`
        : 'Pair the dashboard to inspect delegated MCP access')
    }).catch(() => {
      if (active) setAgentAccessSummary('Delegated access status is unavailable')
    })
    return () => { active = false }
  }, [])

  async function closeSession(sessionId: string) {
    if (!window.confirm(`Close Session ${sessionId}? The canonical settlement policy will be applied.`)) return
    setBusy(sessionId)
    setMessage(`Submitting close for ${sessionId}. The Hypervisor will calculate settlement and refund server-side.`)
    try {
      const result = await dashboardApi.closeSession(sessionId)
      const settlementId = valueText(getRecord(result), 'settlement_id') || valueText(getRecord(getRecord(result)?.settlement), 'settlement_id')
      setSelectedSessionId(null)
      setMessage(settlementId
        ? `Session ${sessionId} closed. Settlement ${shortId(settlementId, 20)} is now recorded; refresh the ledger to inspect the result.`
        : `Session ${sessionId} closed. Settlement and refundable balance were recalculated by the Hypervisor.`)
      onRefresh()
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : `Session ${sessionId} could not be closed.`)
    } finally { setBusy(null) }
  }

  async function sweepIdle() {
    setBusy('sweep')
    setMessage('Checking active Sessions against their idle deadlines...')
    try {
      const result = await dashboardApi.sweepIdleSessions()
      setMessage(`Idle sweep completed. ${result?.closed_count ?? 0} Session${result?.closed_count === 1 ? '' : 's'} closed by the server.`)
      onRefresh()
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : 'Idle Session sweep failed.')
    } finally { setBusy(null) }
  }

  const items = sessions?.items ?? []
  const filteredItems = items.filter((item) => {
    const session = getRecord(item.session)
    const preview = getRecord(item.settlement_preview)
    const status = normalizeStatus(valueText(session, 'status') || 'unknown')
    const needle = search.trim().toLowerCase()
    const haystack = [
      valueText(item, 'display_name'),
      valueText(session, 'session_id'),
      valueText(session, 'endpoint_id'),
      valueText(session, 'node_id'),
      valueText(session, 'client_wallet'),
    ].join(' ').toLowerCase()
    const secondsUntilIdle = numberValue(preview, 'seconds_until_idle_timeout')
    const idleDeadlineValue = getRecord(preview)?.seconds_until_idle_timeout
    const hasIdleDeadline = (typeof idleDeadlineValue === 'number' && Number.isFinite(idleDeadlineValue)) || (typeof idleDeadlineValue === 'string' && idleDeadlineValue.trim().length > 0)
    return (!needle || haystack.includes(needle))
      && (statusFilter === 'all' || status === statusFilter)
      && (!idleOnly || (!isTerminalSessionStatus(status) && hasIdleDeadline && secondsUntilIdle <= 120))
  })
  const selectedItem = items.find((item) => valueText(getRecord(item.session), 'session_id') === selectedSessionId)
  const hasFilters = Boolean(search.trim() || statusFilter !== 'all' || idleOnly)

  return <div className="space-y-4">
    <ScreenHeading eyebrow="Execution and delegated control" title="Agents & Sessions" detail="Supervise Consumer Sessions here and manage delegated MCP credentials in Settings. Inspect shows the server's accounting evidence; closing a Session never makes the browser calculate a payout." />
    {message ? <OperationNotice message={message} onDismiss={() => setMessage(null)} /> : null}
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <CompactStat label="Active" value={sessions?.summary.active ?? 0} />
      <CompactStat label="Queued" value={sessions?.summary.queued ?? 0} />
      <CompactStat label="Terminal" value={sessions?.summary.terminal ?? sessions?.summary.closed ?? 0} />
      <CompactStat label="Visible" value={filteredItems.length} />
    </div>
    <Card className="border-cyan-300/20 bg-cyan-300/[0.035] py-0 shadow-none">
      <CardContent className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex min-w-0 items-start gap-3"><KeyRound className="mt-0.5 size-4 shrink-0 text-cyan-200" /><div className="min-w-0"><p className="font-medium text-slate-100">Delegated MCP control</p><p className="mt-1 truncate text-xs text-muted-foreground">{agentAccessSummary}. Session lifecycle stays here; credential scope and approval policy stay in Settings.</p>{activeAgentCredentials.length > 0 ? <div className="mt-2 flex flex-wrap gap-1.5">{activeAgentCredentials.slice(0, 3).map((credential) => <span key={credential.credential_id} className="rounded border border-cyan-300/15 bg-[#091725] px-2 py-1 font-mono text-[10px] text-slate-300">{credential.label || shortId(credential.credential_id, 16)}</span>)}{activeAgentCredentials.length > 3 ? <span className="px-2 py-1 text-[10px] text-slate-500">+{activeAgentCredentials.length - 3} more</span> : null}</div> : null}</div></div>
        <Button variant="outline" size="sm" className="shrink-0 border-cyan-300/25 bg-[#091725] text-cyan-100" onClick={() => onNavigate('settings')}><KeyRound />Manage permissions</Button>
      </CardContent>
    </Card>
    <div className="flex flex-wrap gap-2">
      <Button variant="outline" className="border-border bg-[#091725]" disabled={busy === 'sweep'} onClick={() => void sweepIdle()}><RotateCcw />{busy === 'sweep' ? 'Sweeping...' : 'Sweep idle Sessions'}</Button>
      <Button variant="ghost" onClick={onRefresh}><RefreshCw className={cn(data.sessions.isFetching && 'animate-spin')} />Refresh Sessions</Button>
    </div>
    {data.sessions.isLoading && !sessions ? <PanelSkeleton rows={5} /> : null}
    {data.sessions.error && !sessions ? <PanelError title="Session control is unavailable" error={data.sessions.error} onRetry={onRefresh} /> : null}
    {sessions ? <Card className="border-border/80 bg-card py-0 shadow-none">
      <CardHeader className="border-b border-border/70 px-5 py-4">
        <div className="flex flex-wrap items-end justify-between gap-3"><div><CardTitle className="text-lg font-semibold">Session ledger</CardTitle><p className="mt-1 text-sm text-muted-foreground">{sessions.summary.active} active · {sessions.summary.queued} queued · {sessions.summary.terminal ?? sessions.summary.closed} terminal</p></div><StatusBadge value={sessions.summary.active > 0 ? 'running' : 'ready'} /></div>
        <div className="mt-4 grid gap-2 lg:grid-cols-[minmax(0,1fr)_11rem_auto]">
          <label className="relative block"><Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-slate-500" /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search Session, Endpoint, wallet..." className="h-9 w-full rounded-md border border-border bg-[#091725] pl-9 pr-3 text-sm text-slate-100 outline-none placeholder:text-slate-500 focus:border-cyan-300/60" /></label>
          <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} aria-label="Filter Sessions by status" className="h-9 rounded-md border border-border bg-[#091725] px-3 text-sm text-slate-200 outline-none focus:border-cyan-300/60"><option value="all">All statuses</option><option value="active">Active</option><option value="queued">Queued</option><option value="closed">Closed</option><option value="force_settled">Force settled</option><option value="failed">Failed</option></select>
          <label className="flex h-9 items-center gap-2 rounded-md border border-border bg-[#091725] px-3 text-xs text-slate-300"><input type="checkbox" checked={idleOnly} onChange={(event) => setIdleOnly(event.target.checked)} className="accent-cyan-300" />Idle risk</label>
        </div>
      </CardHeader>
      <CardContent className="divide-y divide-border/70 p-0">
        {filteredItems.length === 0 ? <EmptyState title={hasFilters ? 'No Sessions match these filters' : 'No Sessions recorded'} detail={hasFilters ? 'Clear the filters to restore the full ledger.' : 'Published Endpoints will create Session records when Consumers submit work.'} actionLabel={hasFilters ? 'Clear filters' : 'Review Endpoints'} onAction={() => hasFilters ? (setSearch(''), setStatusFilter('all'), setIdleOnly(false)) : onNavigate('endpoints')} /> : filteredItems.map((item) => <SessionLedgerRow key={valueText(getRecord(item.session), 'session_id')} item={item} busy={busy} onInspect={() => setSelectedSessionId(valueText(getRecord(item.session), 'session_id'))} onClose={() => void closeSession(valueText(getRecord(item.session), 'session_id'))} />)}
      </CardContent>
    </Card> : null}
    <SessionDetailSheet item={selectedItem} open={Boolean(selectedItem)} busy={busy} onOpenChange={(open) => { if (!open) setSelectedSessionId(null) }} onCloseSession={(sessionId) => void closeSession(sessionId)} />
  </div>
}

function SessionLedgerRow({ item, busy, onInspect, onClose }: { item: DashboardRecord; busy: string | null; onInspect: () => void; onClose: () => void }) {
  const session = getRecord(item.session)
  const deposit = getRecord(item.deposit)
  const preview = getRecord(item.settlement_preview)
  const id = valueText(session, 'session_id')
  const status = valueText(session, 'status') || 'unknown'
  const terminal = isTerminalSessionStatus(status)
  const idleLabel = sessionIdleLabel(session, preview, status)
  return <div className="grid gap-3 px-5 py-4 xl:grid-cols-[minmax(0,1.45fr)_repeat(4,minmax(6rem,0.5fr))_auto] xl:items-center">
    <div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><button type="button" className="truncate text-left font-medium text-slate-100 underline-offset-4 hover:text-cyan-200 hover:underline" onClick={onInspect}>{valueText(item, 'display_name') || valueText(session, 'endpoint_id') || 'Endpoint Session'}</button><StatusBadge value={status} /></div><p className="mt-1 truncate font-mono text-[11px] text-slate-500">{shortId(id, 24)} · {valueText(session, 'request_count') || '0'} request(s)</p><p className={cn('mt-2 flex items-center gap-1 text-xs', idleLabel.attention ? 'text-amber-200' : 'text-muted-foreground')}><Clock3 className="size-3.5" />{idleLabel.label}</p></div>
    <SessionValue label="Locked" value={`${valueText(deposit, 'locked_q', '0')} Q`} />
    <SessionValue label="Consumed" value={`${valueText(deposit, 'consumed_q', '0')} Q`} />
    <SessionValue label="Payment preview" value={`${valueText(preview, 'projected_charged_q', '0')} Q`} />
    <SessionValue label="Refund preview" value={`${valueText(preview, 'projected_refundable_q', '0')} Q`} />
    <div className="flex flex-wrap gap-2 xl:justify-end"><Button variant="outline" size="sm" className="border-cyan-300/25 bg-transparent text-cyan-100" onClick={onInspect}><Eye />Inspect</Button><Button variant="outline" size="sm" className={cn('bg-transparent', terminal ? 'border-slate-300/20 text-slate-400' : 'border-rose-300/25 text-rose-100 hover:bg-rose-300/10')} disabled={terminal || busy === id} onClick={onClose}>{busy === id ? 'Closing...' : terminal ? terminalSessionLabel(status) : 'Close Session'}</Button></div>
  </div>
}

function SessionDetailSheet({ item, open, busy, onOpenChange, onCloseSession }: { item?: DashboardRecord; open: boolean; busy: string | null; onOpenChange: (open: boolean) => void; onCloseSession: (sessionId: string) => void }) {
  const session = getRecord(item?.session)
  const deposit = getRecord(item?.deposit)
  const settlement = getRecord(item?.settlement)
  const preview = getRecord(item?.settlement_preview)
  const checkpoint = getRecord(session?.accounting_checkpoint)
  const tasks = recordList(item?.related_tasks)
  const activity = recordList(item?.activity)
  if (!item || !session) return null
  const sessionId = valueText(session, 'session_id')
  const status = valueText(session, 'status') || 'unknown'
  const terminal = isTerminalSessionStatus(status)
  const usageChain = recordList(session.usage_report_chain)
  const acknowledgementChain = recordList(session.usage_acknowledgement_chain)
  return <Sheet open={open} onOpenChange={onOpenChange}><SheetContent side="right" className="w-full overflow-y-auto border-slate-700 bg-[#07111d] p-0 sm:max-w-xl"><SheetHeader className="border-b border-border/70 px-5 py-5"><div className="flex items-center gap-2"><StatusBadge value={status} /><span className="eyebrow">Session inspector</span></div><SheetTitle className="pr-8 text-xl text-white">{valueText(item, 'display_name') || valueText(session, 'endpoint_id') || 'Endpoint Session'}</SheetTitle><SheetDescription className="font-mono text-[11px] text-slate-500">{sessionId}</SheetDescription></SheetHeader><div className="space-y-4 p-5">
    <Card className="border-border/80 bg-card py-0 shadow-none"><CardHeader className="border-b border-border/70 px-4 py-3"><CardTitle className="text-sm">Identity & lifecycle</CardTitle></CardHeader><CardContent className="grid grid-cols-2 gap-x-4 gap-y-4 p-4"><SessionValue label="Endpoint" value={valueText(session, 'endpoint_id', 'Not reported')} /><SessionValue label="Node" value={valueText(session, 'node_id', 'Not reported')} /><SessionValue label="Consumer auth" value={shortId(valueText(session, 'client_wallet'), 18)} /><SessionValue label="Requests" value={valueText(session, 'request_count', '0')} /><SessionValue label="Created" value={formatDateTime(valueText(session, 'created_at'))} /><SessionValue label="Last activity" value={formatDateTime(valueText(session, 'last_activity_at'))} /><SessionValue label="Idle deadline" value={formatDateTime(valueText(session, 'idle_deadline_at'))} /><SessionValue label="Funding state" value={valueText(session, 'canonical_funding_status', 'Not reported')} /><SessionValue label="Accounting" value={valueText(session, 'accounting_status', 'Not reported')} /></CardContent></Card>
    <Card className="border-border/80 bg-card py-0 shadow-none"><CardHeader className="border-b border-border/70 px-4 py-3"><CardTitle className="text-sm">Execution & accounting evidence</CardTitle></CardHeader><CardContent className="grid grid-cols-2 gap-x-4 gap-y-4 p-4"><SessionValue label="Locked deposit" value={`${valueText(deposit, 'locked_q', '0')} Q`} /><SessionValue label="Consumed" value={`${valueText(deposit, 'consumed_q', '0')} Q`} /><SessionValue label="Endpoint payment" value={`${valueText(preview, 'projected_charged_q', '0')} Q`} /><SessionValue label="Network fee" value={`${valueText(preview, 'network_fee_q', '0')} Q`} /><SessionValue label="Refund preview" value={`${valueText(preview, 'projected_refundable_q', '0')} Q`} /><SessionValue label="Remaining" value={`${valueText(item, 'remaining_q', '0')} Q`} /><SessionValue label="Settlement" value={valueText(settlement, 'status', valueText(item, 'settlement_status', 'Not finalized'))} /><SessionValue label="Funding operation" value={shortId(valueText(session, 'canonical_funding_operation_id'), 18)} /><div className="col-span-2 rounded-md border border-cyan-300/15 bg-cyan-300/[0.035] p-3 text-xs leading-5 text-muted-foreground">{sessionIdleLabel(session, preview, status).label}. These values are projections or canonical records returned by the Hypervisor; the browser does not settle funds.</div></CardContent></Card>
    <Card className="border-border/80 bg-card py-0 shadow-none"><CardHeader className="border-b border-border/70 px-4 py-3"><div className="flex items-center justify-between gap-3"><CardTitle className="text-sm">Requests & results</CardTitle><span className="eyebrow">{tasks.length} record(s)</span></div></CardHeader><CardContent className="divide-y divide-border/70 p-0">{tasks.length === 0 ? <p className="p-4 text-sm text-muted-foreground">No request or task evidence has been recorded for this Session.</p> : tasks.slice(0, 12).map((task, index) => <div key={valueText(task, 'task_id') || `${sessionId}:task:${index}`} className="space-y-2 p-4"><div className="flex flex-wrap items-center justify-between gap-2"><span className="font-mono text-[11px] text-slate-400">{shortId(valueText(task, 'task_id'), 22)}</span><StatusBadge value={valueText(task, 'status', 'unknown')} /></div><p className="text-sm text-slate-200">{valueText(task, 'task_type') || valueText(task, 'bundle_id') || 'Request execution'}</p><p className="text-xs leading-5 text-muted-foreground">Endpoint: {valueText(task, 'endpoint_id', valueText(session, 'endpoint_id', 'Not reported'))} · Created {formatDateTime(valueText(task, 'created_at'))}</p>{valueText(task, 'input_preview') ? <p className="rounded border border-border/70 bg-[#091725] p-2 font-mono text-[11px] text-slate-400">{valueText(task, 'input_preview')}</p> : null}</div>)}</CardContent></Card>
    <Card className="border-border/80 bg-card py-0 shadow-none"><CardHeader className="border-b border-border/70 px-4 py-3"><CardTitle className="text-sm">Usage & checkpoint</CardTitle></CardHeader><CardContent className="grid grid-cols-2 gap-x-4 gap-y-4 p-4"><SessionValue label="Accepted report seq." value={valueText(session, 'last_accepted_report_sequence', 'Not reported')} /><SessionValue label="Accepted usage" value={`${valueText(session, 'last_accepted_usage_charged_q', '0')} Q`} /><SessionValue label="Report chain" value={`${usageChain.length} link(s)`} /><SessionValue label="Acknowledgements" value={`${acknowledgementChain.length} link(s)`} /><SessionValue label="Report head" value={shortId(valueText(session, 'last_accepted_report_hash') || valueText(session, 'report_hash'), 18)} /><SessionValue label="Checkpoint" value={valueText(checkpoint, 'status', checkpoint ? 'Recorded' : 'Not recorded')} /></CardContent></Card>
    <Card className="border-border/80 bg-card py-0 shadow-none"><CardHeader className="border-b border-border/70 px-4 py-3"><div className="flex items-center justify-between gap-3"><CardTitle className="text-sm">Activity timeline</CardTitle><span className="eyebrow">latest first</span></div></CardHeader><CardContent className="divide-y divide-border/70 p-0">{activity.length === 0 ? <p className="p-4 text-sm text-muted-foreground">No activity events have been retained.</p> : activity.slice(0, 12).map((event, index) => <div key={`${valueText(event, 'timestamp')}:${index}`} className="flex gap-3 p-4"><CircleDot className="mt-1 size-3 shrink-0 text-cyan-200" /><div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><p className="text-sm text-slate-200">{valueText(event, 'message') || valueText(event, 'event_type') || 'Session event'}</p><span className="font-mono text-[10px] text-slate-500">{formatDateTime(valueText(event, 'timestamp'))}</span></div>{valueText(event, 'task_id') ? <p className="mt-1 font-mono text-[10px] text-slate-500">task {shortId(valueText(event, 'task_id'), 18)}</p> : null}</div></div>)}</CardContent></Card>
  </div><div className="sticky bottom-0 mt-auto flex gap-2 border-t border-border/70 bg-[#07111d] p-4"><Button variant="outline" className="flex-1 border-border bg-[#091725]" onClick={() => onOpenChange(false)}>Close inspector</Button><Button className="flex-1 bg-rose-300 text-[#1b0b10] hover:bg-rose-200" disabled={terminal || busy === sessionId} onClick={() => onCloseSession(sessionId)}>{busy === sessionId ? 'Closing...' : terminal ? terminalSessionLabel(status) : 'Close Session'}</Button></div></SheetContent></Sheet>
}

function SessionValue({ label, value }: { label: string; value: string }) {
  return <div><p className="eyebrow">{label}</p><p className="mt-1 font-mono text-xs text-slate-200">{value}</p></div>
}

function valueText(value: unknown, key: string, fallback = ''): string {
  const candidate = getRecord(value)?.[key]
  if (typeof candidate === 'string' && candidate.length > 0) return candidate
  if (typeof candidate === 'number' && Number.isFinite(candidate)) return String(candidate)
  if (typeof candidate === 'boolean') return String(candidate)
  return fallback
}

function numberValue(value: unknown, key: string): number {
  const candidate = getRecord(value)?.[key]
  if (typeof candidate === 'number' && Number.isFinite(candidate)) return candidate
  if (typeof candidate === 'string' && candidate.trim()) {
    const parsed = Number(candidate)
    if (Number.isFinite(parsed)) return parsed
  }
  return 0
}

function recordList(value: unknown): DashboardRecord[] {
  return Array.isArray(value)
    ? value.filter((item): item is DashboardRecord => Boolean(getRecord(item)))
    : []
}

function formatDateTime(value: string): string {
  if (!value) return 'Not reported'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return shortId(value, 22)
  return date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

function sessionIdleLabel(session: DashboardRecord | undefined, preview: DashboardRecord | undefined, status: string): { label: string; attention: boolean } {
  if (isTerminalSessionStatus(status)) return { label: 'Terminal · no idle action', attention: false }
  const seconds = numberValue(preview, 'seconds_until_idle_timeout')
  if (seconds <= 0 && valueText(session, 'idle_deadline_at')) return { label: 'Idle deadline reached · sweep eligible', attention: true }
  if (seconds > 0 && seconds <= 120) return { label: `Idle deadline in ${Math.ceil(seconds)}s`, attention: true }
  if (seconds > 0) return { label: `Idle deadline in ${formatDuration(seconds)}`, attention: false }
  return { label: valueText(session, 'idle_deadline_at') ? `Idle deadline ${formatDateTime(valueText(session, 'idle_deadline_at'))}` : 'Idle deadline not reported', attention: false }
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.ceil(seconds)}s`
  const minutes = Math.ceil(seconds / 60)
  if (minutes < 60) return `${minutes}m`
  const hours = Math.floor(minutes / 60)
  const remainingMinutes = minutes % 60
  return remainingMinutes > 0 ? `${hours}h ${remainingMinutes}m` : `${hours}h`
}

function MarketWorkspace({ data, onNavigate, onRefresh }: { data: DashboardData; onNavigate: NavigationProps['onNavigate']; onRefresh: () => void }) {
  const market = data.market.data
  const remotes = data.remoteEndpoints.data
  const [busy, setBusy] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const offers = market?.canonical_candidates.length ? market.canonical_candidates : market?.candidates ?? []

  async function attach(item: DashboardRecord) {
    const nodeId = getText(item, 'node_id')
    const endpointId = getText(item, 'endpoint_id')
    const key = `${nodeId}:${endpointId}`
    setBusy(key)
    setMessage(`Attaching ${endpointId} from ${nodeId}...`)
    try {
      await dashboardApi.attachRemoteEndpoint({ node_id: nodeId, endpoint_id: endpointId, routing_mode: 'preferred' })
      setMessage(`Remote Endpoint ${endpointId} attached. Continue in Endpoints to stage a local proxy draft.`)
      onRefresh()
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : 'Remote Endpoint attach failed.')
    } finally { setBusy(null) }
  }

  return <div className="space-y-4">
    <ScreenHeading eyebrow="Network service discovery" title="Market" detail="Browse canonical offers without exposing Provider topology. Local offers open their Endpoint; remote offers can be attached to this Hypervisor as preferred capacity." />
    {message ? <OperationNotice message={message} onDismiss={() => setMessage(null)} /> : null}
    <div className="flex flex-wrap gap-2"><Button variant="outline" className="border-border bg-[#091725]" onClick={onRefresh}><RefreshCw className={cn(data.market.isFetching && 'animate-spin')} />Refresh catalogue</Button><Button variant="outline" className="border-border bg-[#091725]" onClick={() => onNavigate('endpoints')}><RadioTower />Manage local Endpoints</Button><Button variant="ghost" onClick={() => onNavigate('network')}><Network />Network status</Button></div>
    {(data.market.isLoading || data.remoteEndpoints.isLoading) && !market ? <PanelSkeleton rows={6} /> : null}
    {data.market.error && !market ? <PanelError title="Market catalogue is unavailable" error={data.market.error} onRetry={onRefresh} /> : null}
    {market ? <Card className="border-border/80 bg-card py-0 shadow-none"><CardHeader className="border-b border-border/70 px-5 py-4"><div className="flex flex-wrap items-end justify-between gap-3"><div><CardTitle className="text-lg font-semibold">Canonical offers</CardTitle><p className="mt-1 text-sm text-muted-foreground">{offers.length} offer(s) across {market.nodes.length} visible node(s)</p></div><StatusBadge value={offers.length > 0 ? 'ready' : 'unavailable'} /></div></CardHeader><CardContent className="divide-y divide-border/70 p-0">{offers.length === 0 ? <EmptyState title="No market offers discovered" detail="Publish a local Endpoint or restore Registry replication to populate the canonical catalogue." actionLabel="Create Endpoint" onAction={() => onNavigate('endpoints')} /> : offers.map((offer, index) => { const nodeId = getText(offer, 'node_id'); const endpointId = getText(offer, 'endpoint_id'); const origin = getText(offer, 'origin') || 'external'; const remote = remotes?.discovered.find((item) => getText(item, 'node_id') === nodeId && getText(item, 'endpoint_id') === endpointId); const attachSource = remote ?? offer; const attached = Boolean(getRecord(attachSource)?.already_attached); const key = `${nodeId}:${endpointId}`; return <div key={`${key}:${index}`} className="grid gap-3 px-5 py-4 lg:grid-cols-[minmax(0,1.5fr)_minmax(9rem,0.7fr)_minmax(8rem,0.6fr)_auto] lg:items-center"><div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><p className="font-medium text-slate-100">{getText(offer, 'display_name') || endpointId || getText(offer, 'bundle_id')}</p><StatusBadge value={origin === 'own' ? 'published' : getText(offer, 'status') || 'ready'} /></div><p className="mt-1 truncate font-mono text-[11px] text-slate-500">{nodeId} · {getText(offer, 'model_class') || getText(offer, 'model_id') || 'model class not disclosed'}</p></div><SessionValue label="Origin" value={origin} /><SessionValue label="Price" value={marketPrice(offer)} /><div>{origin === 'own' ? <Button variant="outline" size="sm" className="border-cyan-300/25 bg-[#091725] text-cyan-100" onClick={() => onNavigate('endpoints')}>Open Endpoint<ChevronRight /></Button> : <Button className="bg-cyan-300 text-[#06121d] hover:bg-cyan-200" size="sm" disabled={!endpointId || attached || busy === key} onClick={() => void attach(attachSource)}>{attached ? 'Attached' : busy === key ? 'Attaching...' : 'Attach'}</Button>}</div></div> })}</CardContent></Card> : null}
  </div>
}

function marketPrice(offer: DashboardRecord): string {
  const pricing = getRecord(offer.pricing)
  const fixed = getText(pricing, 'fixed') || getText(pricing, 'fixed_price_q') || getText(offer, 'fixed_price_q')
  if (fixed) return `${fixed} Q`
  const input = getText(pricing, 'input')
  return input ? `${input} Q input` : 'Contract-bound'
}

function ValidationWorkspace({ data, onNavigate, onRefresh }: { data: DashboardData; onNavigate: NavigationProps['onNavigate']; onRefresh: () => void }) {
  const endpoints = data.endpoints.data?.items ?? []
  const summary = summarizeValidation(endpoints)
  const [busy, setBusy] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  async function requestValidation(endpoint: Endpoint) {
    setBusy(endpoint.endpoint_id)
    setMessage(`Submitting validation request for ${endpoint.endpoint_id}...`)
    try {
      const result = await dashboardApi.requestEndpointValidation(endpoint.endpoint_id)
      const status = getText(result, 'status') || getText(result, 'validation_status') || 'accepted'
      setMessage(`Validation request for ${endpoint.endpoint_id} was ${status}. Refresh will show the resulting evidence.`)
      onRefresh()
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : `Validation request for ${endpoint.endpoint_id} failed.`)
    } finally { setBusy(null) }
  }

  return <div className="space-y-4">
    <ScreenHeading eyebrow="Endpoint assurance" title="Validation" detail="Request and inspect Validation without changing the immutable Bundle. Runtime health and Validation evidence remain separate signals." />
    {message ? <OperationNotice message={message} onDismiss={() => setMessage(null)} /> : null}
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4"><CompactStat label="Published" value={summary.published} /><CompactStat label="Verified" value={summary.verified} /><CompactStat label="Pending" value={summary.pending} /><CompactStat label="Unvalidated" value={summary.unvalidated} /></div>
    {data.endpoints.isLoading && endpoints.length === 0 ? <PanelSkeleton rows={5} /> : null}
    {data.endpoints.error && endpoints.length === 0 ? <PanelError title="Validation inventory is unavailable" error={data.endpoints.error} onRetry={onRefresh} /> : null}
    <Card className="border-border/80 bg-card py-0 shadow-none"><CardHeader className="flex-row items-center justify-between gap-3 border-b border-border/70 px-5 py-4"><div><CardTitle className="text-lg font-semibold">Endpoint validation queue</CardTitle><p className="mt-1 text-sm text-muted-foreground">Only actual Endpoint records appear here.</p></div><Button variant="outline" size="sm" className="border-border bg-[#091725]" onClick={onRefresh}><RefreshCw className={cn(data.endpoints.isFetching && 'animate-spin')} />Refresh evidence</Button></CardHeader><CardContent className="divide-y divide-border/70 p-0">{endpoints.length === 0 ? <EmptyState title="No Endpoints to validate" detail="Create a draft from a ready Runtime Binding, then publish it before requesting network Validation." actionLabel="Create Endpoint" onAction={() => onNavigate('endpoints')} /> : endpoints.map((endpoint) => { const validation = getRecord(endpoint.validation_summary) ?? getRecord(endpoint.validation); const state = getText(validation, 'status') || getText(validation, 'state') || 'unvalidated'; return <div key={endpoint.endpoint_id} className="grid gap-3 px-5 py-4 lg:grid-cols-[minmax(0,1.5fr)_minmax(8rem,0.5fr)_minmax(8rem,0.5fr)_auto] lg:items-center"><div className="min-w-0"><p className="font-medium text-slate-100">{endpoint.display_name || endpoint.endpoint_id}</p><p className="mt-1 truncate font-mono text-[11px] text-slate-500">{endpoint.endpoint_id} · {endpoint.model_class || 'model class pending'}</p></div><div><p className="eyebrow">Publication</p><div className="mt-1"><StatusBadge value={endpoint.publication_status} /></div></div><div><p className="eyebrow">Validation</p><div className="mt-1"><StatusBadge value={state} /></div></div><div className="flex flex-wrap gap-2"><Button variant="outline" size="sm" className="border-cyan-300/25 bg-[#091725] text-cyan-100" disabled={busy === endpoint.endpoint_id} onClick={() => void requestValidation(endpoint)}><ShieldCheck />{busy === endpoint.endpoint_id ? 'Submitting...' : 'Request validation'}</Button><Button variant="ghost" size="sm" onClick={() => onNavigate('endpoints')}>Details<ChevronRight /></Button></div></div> })}</CardContent></Card>
  </div>
}

function CompactStat({ label, value }: { label: string; value: number }) {
  return <div className="rounded-lg border border-border/80 bg-card px-4 py-3"><p className="eyebrow">{label}</p><p className="mt-2 text-xl font-semibold text-white">{formatCount(value)}</p></div>
}

function NetworkWorkspace({ data, onNavigate, onRefresh }: { data: DashboardData; onNavigate: NavigationProps['onNavigate']; onRefresh: () => void }) {
  const readiness = data.readiness.data
  const remotes = data.remoteEndpoints.data
  const market = data.market.data
  const node = data.home.data?.bootstrap.node_identity ?? data.fleet.data?.node
  const [busy, setBusy] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  async function detach(item: DashboardRecord) {
    const id = getText(item, 'remote_endpoint_id')
    if (!id || !window.confirm(`Detach remote Endpoint ${id}? Active proxy routes may block this action.`)) return
    setBusy(id)
    setMessage(`Detaching remote Endpoint ${id}...`)
    try {
      await dashboardApi.detachRemoteEndpoint(id)
      setMessage(`Remote Endpoint ${id} detached from this Hypervisor.`)
      onRefresh()
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : `Remote Endpoint ${id} could not be detached.`)
    } finally { setBusy(null) }
  }

  function refreshNetwork() {
    setMessage('Rechecking consensus, registry and remote Endpoint state...')
    onRefresh()
  }

  return <div className="space-y-4">
    <ScreenHeading eyebrow="Consensus and discovery" title="Network" detail="Inspect the evidence that makes this Hypervisor network-ready. A green label is shown only when the corresponding backend check reports ready." />
    {message ? <OperationNotice message={message} onDismiss={() => setMessage(null)} /> : null}
    <div className="flex flex-wrap gap-2"><Button className="bg-cyan-300 text-[#06121d] hover:bg-cyan-200" onClick={refreshNetwork}><RefreshCw className={cn(data.readiness.isFetching && 'animate-spin')} />Recheck network</Button><Button variant="outline" className="border-border bg-[#091725]" onClick={() => onNavigate('market')}><BriefcaseBusiness />Browse Market</Button><Button variant="outline" className="border-border bg-[#091725]" onClick={() => onNavigate('settings')}><Settings />Host settings</Button></div>
    {data.readiness.error && !readiness ? <PanelError title="Network readiness is unavailable" error={data.readiness.error} onRetry={refreshNetwork} /> : null}
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(20rem,0.8fr)]"><Card className="border-border/80 bg-card py-0 shadow-none"><CardHeader className="border-b border-border/70 px-5 py-4"><div className="flex items-center justify-between gap-3"><div><CardTitle className="text-lg font-semibold">Readiness evidence</CardTitle><p className="mt-1 text-sm text-muted-foreground">{getText(node, 'node_id') || 'Local Hypervisor'} · {getText(node, 'base_url') || 'control address unavailable'}</p></div><StatusBadge value={readiness?.network_ready ? 'ready' : 'blocked'} /></div></CardHeader><CardContent className="divide-y divide-border/70 p-0">{readiness?.steps.map((step) => <div key={step.key} className="flex flex-col gap-2 px-5 py-4 sm:flex-row sm:items-start sm:justify-between"><div><p className="font-medium text-slate-100">{step.title}</p><p className="mt-1 max-w-2xl text-xs leading-5 text-muted-foreground">{step.detail || step.summary}</p></div><StatusBadge value={step.status} /></div>) ?? <p className="px-5 py-6 text-sm text-muted-foreground">Network evidence has not arrived yet.</p>}</CardContent></Card><Card className="border-border/80 bg-card py-0 shadow-none"><CardHeader className="border-b border-border/70 px-5 py-4"><CardTitle className="text-lg font-semibold">Visible network</CardTitle></CardHeader><CardContent className="divide-y divide-border/70 p-0"><NetworkFact label="Registry nodes" value={formatCount(market?.nodes.length ?? 0)} detail="nodes returned by current discovery" /><NetworkFact label="Remote offers" value={formatCount(remotes?.summary.discovered ?? 0)} detail="published Endpoint records" /><NetworkFact label="Attached capacity" value={formatCount(remotes?.summary.attached ?? 0)} detail="remote Endpoints available to proxy routes" /></CardContent></Card></div>
    <Card className="border-border/80 bg-card py-0 shadow-none"><CardHeader className="border-b border-border/70 px-5 py-4"><CardTitle className="text-lg font-semibold">Attached remote Endpoints</CardTitle><p className="mt-1 text-sm text-muted-foreground">Detach is rejected when a local proxy route still depends on the record.</p></CardHeader><CardContent className="divide-y divide-border/70 p-0">{(remotes?.attached ?? []).length === 0 ? <EmptyState title="No remote capacity attached" detail="Open Market to discover and attach an Endpoint from another Hypervisor." actionLabel="Browse Market" onAction={() => onNavigate('market')} /> : remotes?.attached.map((item) => { const id = getText(item, 'remote_endpoint_id'); return <div key={id} className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-center sm:justify-between"><div><p className="font-medium text-slate-100">{getText(item, 'alias') || getText(item, 'source_endpoint_id')}</p><p className="mt-1 font-mono text-[11px] text-slate-500">{getText(item, 'source_node_id')} · {id}</p></div><div className="flex items-center gap-2"><StatusBadge value={getText(item, 'status') || 'ready'} /><Button variant="outline" size="sm" className="border-rose-300/25 bg-transparent text-rose-100 hover:bg-rose-300/10" disabled={busy === id} onClick={() => void detach(item)}><Trash2 />{busy === id ? 'Detaching...' : 'Detach'}</Button></div></div> })}</CardContent></Card>
  </div>
}

function NetworkFact({ label, value, detail }: { label: string; value: string; detail: string }) {
  return <div className="px-5 py-4"><p className="eyebrow">{label}</p><p className="mt-2 text-lg font-semibold text-slate-100">{value}</p><p className="mt-1 text-xs text-muted-foreground">{detail}</p></div>
}

function DataTable<TData>({ table }: { table: ReturnType<typeof useReactTable<TData>> }) {
  return (
    <div className="overflow-x-auto">
      <Table className="min-w-[720px]">
        <TableHeader className="bg-black/10">
          {table.getHeaderGroups().map((headerGroup) => <TableRow key={headerGroup.id} className="border-border/70 hover:bg-transparent">
            {headerGroup.headers.map((header) => <TableHead key={header.id} className="h-10 px-5 font-mono text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-500">{header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext())}</TableHead>)}
          </TableRow>)}
        </TableHeader>
        <TableBody>
          {table.getRowModel().rows.map((row) => <TableRow key={row.id} className="border-border/65 transition-colors hover:bg-white/[0.025]">
            {row.getVisibleCells().map((cell) => <TableCell key={cell.id} className="px-5 py-3.5">{flexRender(cell.column.columnDef.cell, cell.getContext())}</TableCell>)}
          </TableRow>)}
        </TableBody>
      </Table>
    </div>
  )
}

function ResourceOverview({ fleet, isLoading, error, onNavigate }: { fleet: DashboardData['fleet']['data']; isLoading: boolean; error: Error | null; onNavigate: NavigationProps['onNavigate'] }) {
  if (isLoading && !fleet) return <PanelSkeleton rows={4} />
  if (error && !fleet) return <PanelError title="Resource probe is unavailable" error={error} />
  const resources = fleet?.resources
  const cpu = resourceUsage(resources?.total.cpu, resources?.free.cpu)
  const ram = resourceUsage(resources?.total.ram_mb, resources?.free.ram_mb)
  const vram = resourceUsage(resources?.total.vram_mb, resources?.free.vram_mb)
  const probe = resources?.probe
  const gpuReported = Boolean(probe?.gpu_reported)
  return (
    <Card className="border-border/80 bg-card py-0 shadow-none">
      <CardHeader className="flex-row items-start justify-between gap-3 px-4 py-4"><div><p className="eyebrow">Host telemetry</p><CardTitle className="mt-1 text-base font-semibold">Resource usage</CardTitle></div><Button variant="ghost" size="xs" className="text-cyan-200 hover:bg-cyan-300/10" onClick={() => onNavigate('settings')}>Probe details<ChevronRight /></Button></CardHeader>
      <CardContent className="space-y-4 px-4 pb-4">
        <ResourceMeter label="CPU" value={cpu.percent} detail={`${formatCount(cpu.used)} / ${formatCount(cpu.total)} cores`} color="cyan" />
        <ResourceMeter label="RAM" value={ram.percent} detail={`${formatMemory(ram.used)} / ${formatMemory(ram.total)}`} color="violet" />
        <ResourceMeter label="GPU memory" value={vram.percent} detail={gpuReported ? `${formatMemory(vram.used)} / ${formatMemory(vram.total)}` : 'Not reported by this host'} color="amber" muted={!gpuReported} />
        <div className="border-t border-border/70 pt-3">
          <p className="font-mono text-[10px] uppercase tracking-[0.12em] text-slate-500">Probe source</p>
          <p className="mt-1 text-xs text-slate-300">{getText(probe, 'source') || 'No resource probe record'}</p>
          {Array.isArray(probe?.limitations) && probe.limitations.length > 0 ? <p className="mt-1 text-xs leading-5 text-amber-200/80">{String(probe.limitations[0])}</p> : null}
        </div>
      </CardContent>
    </Card>
  )
}

function ResourceMeter({ label, value, detail, color, muted = false }: { label: string; value: number; detail: string; color: 'cyan' | 'violet' | 'amber'; muted?: boolean }) {
  const tone = color === 'cyan' ? 'bg-cyan-300' : color === 'violet' ? 'bg-violet-300' : 'bg-amber-300'
  return <div>
    <div className="flex items-baseline justify-between gap-2"><p className="font-mono text-[10px] uppercase tracking-[0.12em] text-cyan-100/60">{label}</p><p className={cn('font-mono text-xs font-semibold', muted ? 'text-slate-400' : 'text-white')}>{muted ? '—' : formatPercent(value)}</p></div>
    <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-white/8"><div className={cn('h-full rounded-full transition-[width]', tone, muted && 'opacity-30')} style={{ width: `${muted ? 0 : Math.min(100, value)}%` }} /></div>
    <p className="mt-1.5 text-xs text-muted-foreground">{detail}</p>
  </div>
}

function SystemState({ fleet, home, isLoading }: { fleet: DashboardData['fleet']['data']; home: DashboardData['home']['data']; isLoading: boolean }) {
  if (isLoading && !fleet && !home) return <PanelSkeleton rows={3} />
  const queue = fleet?.queue
  const providerCount = home?.bootstrap.provider_count ?? 0
  return <Card className="border-border/80 bg-card py-0 shadow-none"><CardHeader className="px-4 py-4"><div><p className="eyebrow">Control-plane state</p><CardTitle className="mt-1 text-base font-semibold">System health</CardTitle></div></CardHeader><CardContent className="space-y-3 px-4 pb-4"><HealthRow icon={ServerCog} label="Provider plugins" value={formatCount(providerCount)} detail="registered" /><HealthRow icon={Gauge} label="Queue" value={formatCount(queue?.active ?? 0)} detail={`${queue?.queued ?? 0} queued`} /><HealthRow icon={Network} label="Network" value="Linked" detail={getText(fleet?.node, 'base_url') || 'local node'} /></CardContent></Card>
}

function HealthRow({ icon: Icon, label, value, detail }: { icon: LucideIcon; label: string; value: string; detail: string }) {
  return <div className="flex items-center gap-3"><span className="grid size-7 place-items-center rounded-md bg-cyan-300/8 text-cyan-200"><Icon className="size-3.5" /></span><div className="min-w-0 flex-1"><p className="text-xs font-medium text-white">{label}</p><p className="truncate text-[11px] text-muted-foreground">{detail}</p></div><span className="font-mono text-xs font-semibold text-emerald-300">{value}</span></div>
}

function ResourceFooter({ fleet, isLoading, onNavigate }: { fleet: DashboardData['fleet']['data']; isLoading: boolean; onNavigate: NavigationProps['onNavigate'] }) {
  const resources = fleet?.resources
  const cpu = resourceUsage(resources?.total.cpu, resources?.free.cpu)
  const ram = resourceUsage(resources?.total.ram_mb, resources?.free.ram_mb)
  const vram = resourceUsage(resources?.total.vram_mb, resources?.free.vram_mb)
  const queue = fleet?.queue
  const items = [
    { label: 'CPU', value: isLoading ? '…' : formatPercent(cpu.percent), icon: Cpu, tone: 'text-cyan-300', screen: 'settings' as DashboardScreen },
    { label: 'RAM', value: isLoading ? '…' : formatPercent(ram.percent), icon: Database, tone: 'text-violet-300', screen: 'settings' as DashboardScreen },
    { label: 'VRAM', value: isLoading ? '…' : resources?.probe?.gpu_reported ? formatPercent(vram.percent) : '—', icon: Zap, tone: 'text-amber-300', screen: 'settings' as DashboardScreen },
    { label: 'Sessions', value: isLoading ? '…' : formatCount(queue?.active ?? 0), icon: Activity, tone: 'text-sky-300', screen: 'agents' as DashboardScreen },
  ]
  return <footer className="fixed inset-x-0 bottom-0 z-20 border-t border-border/75 bg-[#060e18]/95 backdrop-blur-xl"><div className="mx-auto flex w-full max-w-[1760px] overflow-x-auto px-3 lg:px-5">{items.map(({ label, value, icon: Icon, tone, screen }) => <button type="button" key={label} className="flex min-w-40 items-center gap-2 border-r border-border/70 px-4 py-2.5 text-left transition-colors hover:bg-white/[0.035] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-cyan-300/70 first:pl-0" onClick={() => onNavigate(screen)}><Icon className={cn('size-4', tone)} /><div><p className="font-mono text-[9px] uppercase tracking-[0.12em] text-cyan-100/60">{label}</p><p className="mt-0.5 font-mono text-xs font-semibold text-white">{value}</p></div><ChevronRight className="ml-auto size-3.5 text-slate-600" /></button>)}</div></footer>
}

function ScreenHeading({ eyebrow, title, detail }: { eyebrow: string; title: string; detail: string }) {
  return <section className="border-b border-border/75 pb-4"><p className="eyebrow">{eyebrow}</p><h1 className="mt-1 text-2xl font-semibold tracking-[-0.045em] text-white sm:text-3xl">{title}</h1><p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">{detail}</p></section>
}

function StatusBadge({ value }: { value: string }) {
  const normalized = normalizeStatus(value)
  return <Badge variant="outline" className={cn('h-5 border px-1.5 font-mono text-[9px] font-semibold uppercase tracking-[0.09em]', statusClassNames[normalized] ?? 'border-slate-300/20 bg-slate-300/8 text-slate-300')}>{value.replaceAll('_', ' ')}</Badge>
}

function PanelSkeleton({ rows }: { rows: number }) {
  return <Card className="border-border/80 bg-card py-0 shadow-none"><CardContent className="space-y-3 p-5"><Skeleton className="h-5 w-40 bg-white/8" />{Array.from({ length: rows }, (_, index) => <Skeleton key={index} className="h-12 w-full bg-white/6" />)}</CardContent></Card>
}

function TableSkeleton({ columns, rows }: { columns: number; rows: number }) {
  return <div className="space-y-px overflow-hidden">{Array.from({ length: rows + 1 }, (_, row) => <div key={row} className="grid min-w-[720px] grid-cols-6 gap-4 border-b border-border/65 px-5 py-4">{Array.from({ length: columns }, (_, column) => <Skeleton key={column} className={cn('h-4 bg-white/6', column === 0 && 'w-28')} />)}</div>)}</div>
}

function PanelError({ title, detail, error, onRetry }: { title: string; detail?: string; error?: Error | null; onRetry?: () => void }) {
  return <Card className="border-amber-300/20 bg-amber-300/[0.035] py-0 shadow-none"><CardContent className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between"><div><p className="font-semibold text-amber-100">{title}</p><p className="mt-1 max-w-xl text-xs leading-5 text-amber-100/75">{detail ?? error?.message ?? 'The Hypervisor did not provide this read model. Other dashboard sections remain available.'}</p></div>{onRetry ? <Button variant="outline" size="sm" className="shrink-0 border-amber-300/25 bg-transparent text-amber-100 hover:bg-amber-300/10" onClick={onRetry}><RefreshCw />Retry</Button> : null}</CardContent></Card>
}

function EmptyState({ title, detail, actionLabel, onAction }: { title: string; detail: string; actionLabel: string; onAction: () => void }) {
  return <div className="px-5 py-12 text-center"><Boxes className="mx-auto size-6 text-slate-600" /><p className="mt-3 font-medium text-slate-200">{title}</p><p className="mx-auto mt-1 max-w-md text-sm leading-6 text-muted-foreground">{detail}</p><Button variant="outline" size="sm" className="mt-4 border-border bg-[#091725]" onClick={onAction}>{actionLabel}<ChevronRight /></Button></div>
}

function summarizeValidation(endpoints: Endpoint[]) {
  return endpoints.reduce((summary, endpoint) => {
    summary.total += 1
    if (endpoint.publication_status === 'published') summary.published += 1
    const validationStatus = getText(endpoint.validation_summary, 'status') || getText(endpoint.validation_summary, 'validation_status') || getText(endpoint.validation, 'validation_status')
    if (validationStatus === 'verified' || validationStatus === 'passed' || validationStatus === 'valid') summary.verified += 1
    if (validationStatus === 'pending' || validationStatus === 'running') summary.pending += 1
    if (!validationStatus || validationStatus === 'unvalidated') summary.unvalidated += 1
    return summary
  }, { total: 0, published: 0, verified: 0, pending: 0, unvalidated: 0 })
}

export default App
