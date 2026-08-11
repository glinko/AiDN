import { useEffect, useState } from 'react'
import {
  Activity,
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
  RadioTower,
  RefreshCw,
  RotateCcw,
  ServerCog,
  Settings,
  ShieldCheck,
  Sparkles,
  WalletCards,
  Trash2,
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
import { Sheet, SheetContent, SheetTrigger } from '@/components/ui/sheet'
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
import type { Bundle, Endpoint, ReadinessStep, WalletDashboard } from '@/lib/types'

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
  running: 'border-cyan-300/25 bg-cyan-300/10 text-cyan-200',
  created: 'border-sky-300/25 bg-sky-300/10 text-sky-200',
  pending: 'border-amber-300/25 bg-amber-300/10 text-amber-200',
  stopped: 'border-slate-300/20 bg-slate-300/8 text-slate-300',
  unavailable: 'border-slate-300/20 bg-slate-300/8 text-slate-300',
  blocked: 'border-rose-300/25 bg-rose-300/10 text-rose-200',
  failed: 'border-rose-300/25 bg-rose-300/10 text-rose-200',
  error: 'border-rose-300/25 bg-rose-300/10 text-rose-200',
}

type OperationsScreen = Exclude<DashboardScreen, 'overview' | 'bundles' | 'endpoints' | 'settings'>

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

  const nodeIdentity = data.home.data?.bootstrap.node_identity ?? data.fleet.data?.node
  const nodeName = getText(nodeIdentity, 'node_id') || 'Local Hypervisor'
  const readinessPercent = data.readiness.data?.progress.percent ?? 0
  const hasRefreshError = [data.home, data.readiness, data.fleet, data.bundles, data.endpoints, data.wallet, data.providers, data.installs].some(
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
    void Promise.all([
      data.home.refetch(),
      data.readiness.refetch(),
      data.fleet.refetch(),
      data.bundles.refetch(),
      data.endpoints.refetch(),
      data.wallet.refetch(),
      data.providers.refetch(),
      data.installs.refetch(),
    ])
  }

  function navigate(screen: DashboardScreen) {
    setActiveScreen(screen)
    if (window.location.hash !== `#${screen}`) {
      window.history.pushState(null, '', `#${screen}`)
    }
    setMobileOpen(false)
  }

  return (
    <div className="operator-shell min-h-svh bg-background text-foreground">
      <TopBar
        nodeName={nodeName}
        advanced={advanced}
        isRefreshing={data.home.isFetching || data.readiness.isFetching}
        refreshError={hasRefreshError}
        onRefresh={refreshAll}
        onToggleAdvanced={() => setAdvanced(!advanced)}
        onOpenNavigation={() => setMobileOpen(true)}
        onNavigate={navigate}
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
            <BundlesScreen bundles={data.bundles.data?.items ?? []} isLoading={data.bundles.isLoading} error={data.bundles.error} onNavigate={navigate} onRefresh={refreshAll} />
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

      <ResourceFooter fleet={data.fleet.data} isLoading={data.fleet.isLoading} />

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
  onRefresh: () => void
  onToggleAdvanced: () => void
  onOpenNavigation: () => void
  onNavigate: (screen: DashboardScreen) => void
}

function TopBar({
  nodeName,
  advanced,
  isRefreshing,
  refreshError,
  onRefresh,
  onToggleAdvanced,
  onOpenNavigation,
  onNavigate,
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
            className="relative shrink-0 border-x border-t border-border/70 bg-[#0a1725] px-3 py-2 text-left text-sm font-semibold text-cyan-200 after:absolute after:inset-x-3 after:bottom-0 after:h-0.5 after:bg-cyan-300 sm:px-4"
          >
            <span className="block max-w-44 truncate">{nodeName}</span>
            <span className="hidden text-[10px] font-medium uppercase tracking-[0.14em] text-muted-foreground sm:block">Local Hypervisor</span>
          </button>
          <button type="button" className="hidden shrink-0 items-center gap-2 border border-dashed border-border/70 px-3 text-xs text-muted-foreground transition-colors hover:border-cyan-300/40 hover:text-cyan-100 md:flex" onClick={() => onNavigate('network')}>
            <Network className="size-3.5" />
            Remote discovery
          </button>
        </div>
        <div className="ml-auto flex shrink-0 items-center gap-1.5">
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
          <span className="grid size-8 place-items-center rounded-full border border-border bg-[#0b1725] font-mono text-[11px] font-semibold text-slate-200">
            OP
          </span>
        </div>
      </div>
    </header>
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
  const activeSessions = fleet?.queue.active ?? 0
  const queuedSessions = fleet?.queue.queued ?? 0
  const validationSummary = summarizeValidation(endpoints)

  return (
    <div className="space-y-4 lg:space-y-5">
      <section className="flex flex-col justify-between gap-3 border-b border-border/75 pb-4 sm:flex-row sm:items-end">
        <div>
          <p className="eyebrow">Hypervisor workspace</p>
          <h1 className="mt-1 text-2xl font-semibold tracking-[-0.045em] text-white sm:text-3xl">Overview</h1>
          <p className="mt-1 text-sm text-muted-foreground">{nodeName} <span className="text-slate-600">/</span> local operations</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <SmallInfo label="Node" value={nodeName} />
          <SmallInfo label="Sync" value={readiness?.network_ready ? 'Healthy' : 'Review'} tone={readiness?.network_ready ? 'good' : 'warn'} />
          <Button variant="outline" size="sm" className="border-border bg-[#091725]" onClick={onRefresh}>
            <RefreshCw className={cn('size-3.5', data.home.isFetching && 'animate-spin')} />
            Refresh
          </Button>
        </div>
      </section>

      <section className="grid grid-cols-2 gap-3 xl:grid-cols-5">
        <MetricCard label="Active Bundles" value={formatCount(bundles.filter((bundle) => bundle.enabled).length)} detail={`${bundles.length} registered`} icon={Boxes} tone="cyan" loading={data.bundles.isLoading} />
        <MetricCard label="Published Endpoints" value={formatCount(publishedCount)} detail={`${endpoints.length} configured`} icon={RadioTower} tone="blue" loading={data.endpoints.isLoading} />
        <MetricCard label="Running Sessions" value={formatCount(activeSessions)} detail={`${queuedSessions} queued`} icon={Activity} tone="violet" loading={data.fleet.isLoading} />
        <MetricCard label="Wallet" value={wallet?.configured ? 'Bound' : 'Setup'} detail={wallet?.configured ? shortId(wallet.wallet_id) : 'Action required'} icon={WalletCards} tone={wallet?.configured ? 'green' : 'amber'} loading={data.home.isLoading} />
        <MetricCard label="Readiness" value={readiness ? formatPercent(readiness.progress.percent) : '—'} detail={readiness?.overall_state ?? 'Checking status'} icon={ShieldCheck} tone={readiness?.overall_state === 'ready' ? 'green' : 'amber'} loading={data.readiness.isLoading} />
      </section>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_296px]">
        <div className="min-w-0 space-y-4">
          <ReadinessWizard readiness={readiness} isLoading={data.readiness.isLoading} error={data.readiness.error} onNavigate={onNavigate} onRefresh={onRefresh} />
          <BundleTableSection bundles={bundles} isLoading={data.bundles.isLoading} error={data.bundles.error} onNavigate={onNavigate} compact />
        </div>
        <aside className="space-y-4">
          <ResourceOverview fleet={fleet} isLoading={data.fleet.isLoading} error={data.fleet.error} />
          <ValidationOverview endpoints={endpoints} summary={validationSummary} isLoading={data.endpoints.isLoading} error={data.endpoints.error} />
          <SystemState fleet={fleet} home={home} isLoading={data.fleet.isLoading || data.home.isLoading} />
        </aside>
      </div>
    </div>
  )
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

function MetricCard({ label, value, detail, icon: Icon, tone, loading }: { label: string; value: string; detail: string; icon: LucideIcon; tone: 'cyan' | 'blue' | 'violet' | 'green' | 'amber'; loading: boolean }) {
  const color = {
    cyan: 'text-cyan-300 bg-cyan-300/10',
    blue: 'text-sky-300 bg-sky-300/10',
    violet: 'text-violet-300 bg-violet-300/10',
    green: 'text-emerald-300 bg-emerald-300/10',
    amber: 'text-amber-200 bg-amber-300/10',
  }[tone]
  return (
    <Card className="min-h-32 border-border/80 bg-card py-0 shadow-none" size="sm">
      <CardContent className="flex h-full flex-col p-4">
        <div className="flex items-start justify-between gap-2">
          <p className="eyebrow">{label}</p>
          <span className={cn('grid size-8 place-items-center rounded-lg', color)}><Icon className="size-4" /></span>
        </div>
        {loading ? <Skeleton className="mt-4 h-8 w-16 bg-white/8" /> : <p className="mt-3 text-2xl font-semibold tracking-[-0.05em] text-white">{value}</p>}
        <p className="mt-auto pt-1 text-xs text-muted-foreground">{detail}</p>
      </CardContent>
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

function BundleTableSection({ bundles, isLoading, error, onNavigate, compact = false, onAction }: { bundles: Bundle[]; isLoading: boolean; error: Error | null; onNavigate: NavigationProps['onNavigate']; compact?: boolean; onAction?: (bundle: Bundle, action: BundleAction) => void }) {
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
        {bundles.length > 0 ? <BundleTable bundles={bundles} onNavigate={onNavigate} onAction={onAction} /> : null}
      </CardContent>
    </Card>
  )
}

type BundleAction = 'enable' | 'disable' | 'retry' | 'reset-cooldown'

function BundleTable({ bundles, onNavigate, onAction }: { bundles: Bundle[]; onNavigate: NavigationProps['onNavigate']; onAction?: (bundle: Bundle, action: BundleAction) => void }) {
  const columns: ColumnDef<Bundle>[] = [
    {
      accessorKey: 'bundle_id',
      header: 'Bundle',
      cell: ({ row }) => <div><p className="font-medium text-slate-100">{shortId(row.original.bundle_id, 20)}</p><p className="mt-0.5 font-mono text-[10px] text-slate-500">{shortId(row.original.bundle_id)}</p></div>,
    },
    { accessorKey: 'provider_type', header: 'Provider', cell: ({ row }) => <span className="font-mono text-xs text-slate-300">{row.original.provider_type}</span> },
    { accessorKey: 'model_id', header: 'Model', cell: ({ row }) => <span className="text-xs text-slate-200">{row.original.model_id}</span> },
    { accessorKey: 'runtime_status', header: 'Runtime', cell: ({ row }) => <StatusBadge value={row.original.runtime_status} /> },
    { accessorKey: 'publish_status', header: 'Publication', cell: ({ row }) => <StatusBadge value={row.original.publish_status} /> },
    {
      id: 'endpoint',
      header: '',
      cell: ({ row }) => row.original.endpoint_relationship?.state === 'published_endpoint' ? <Button variant="ghost" size="sm" className="text-cyan-200 hover:bg-cyan-300/10" onClick={() => onNavigate('endpoints')}>Endpoint<ChevronRight /></Button> : <span className="text-xs text-muted-foreground">No Endpoint</span>,
    },
    ...(onAction ? [{
      id: 'controls',
      header: 'Controls',
      cell: ({ row }: { row: { original: Bundle } }) => <div className="flex flex-wrap gap-1.5"><Button variant="outline" size="xs" className="border-border bg-[#091725]" onClick={() => onAction(row.original, row.original.enabled ? 'disable' : 'enable')}>{row.original.enabled ? 'Pause' : 'Enable'}</Button><Button variant="outline" size="xs" className="border-cyan-300/25 bg-[#091725] text-cyan-100" onClick={() => onAction(row.original, 'retry')}>Retry</Button><Button variant="ghost" size="xs" className="text-slate-300" onClick={() => onAction(row.original, 'reset-cooldown')}>Reset</Button></div>,
    }] satisfies ColumnDef<Bundle>[] : []),
  ]
  const table = useReactTable({ data: bundles, columns, getCoreRowModel: getCoreRowModel() })
  return <DataTable table={table} />
}

function BundlesScreen({ bundles, isLoading, error, onNavigate, onRefresh }: { bundles: Bundle[]; isLoading: boolean; error: Error | null; onNavigate: NavigationProps['onNavigate']; onRefresh: () => void }) {
  const [busy, setBusy] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)

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
      <BundleRevisionControl bundles={bundles} onRefresh={onRefresh} />
      <BundleTableSection bundles={bundles} isLoading={isLoading} error={error} onNavigate={onNavigate} onAction={runBundleAction} />
    </div>
  )
}

function BundleRevisionControl({ bundles, onRefresh }: { bundles: Bundle[]; onRefresh: () => void }) {
  const [sourceBundleId, setSourceBundleId] = useState('')
  const [bundleId, setBundleId] = useState('')
  const [overrides, setOverrides] = useState('{}')
  const [enabled, setEnabled] = useState(false)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  useEffect(() => {
    if (!sourceBundleId && bundles.length > 0) {
      setSourceBundleId(bundles[0].bundle_id)
      setBundleId(`${bundles[0].bundle_id}-r${Number(getRecord(bundles[0])?.revision ?? 1) + 1}`)
    }
  }, [bundles, sourceBundleId])

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

  return <Card className="border-cyan-300/20 bg-cyan-300/[0.03] py-0 shadow-none"><CardHeader className="border-b border-border/70 px-5 py-4"><p className="eyebrow text-cyan-100">Endpoint lifecycle</p><CardTitle className="mt-1 text-lg font-semibold">Create a draft from a ready runtime</CardTitle><p className="mt-1 text-sm leading-6 text-muted-foreground">Draft creation is local. Publication signs the immutable configuration and, on a validator, submits `ENDPOINT_PUBLISH` through consensus. Validation is a separate request.</p></CardHeader><CardContent className="grid gap-3 p-5 lg:grid-cols-4"><label className="grid gap-2"><span className="eyebrow">Display name</span><input value={displayName} onChange={(event) => setDisplayName(event.target.value)} className="h-10 rounded-lg border border-input bg-[#07111d] px-3 text-sm text-white outline-none focus:border-cyan-300" /></label><label className="grid gap-2"><span className="eyebrow">Runtime Binding</span><select value={bindingId} onChange={(event) => setBindingId(event.target.value)} className="h-10 rounded-lg border border-input bg-[#07111d] px-3 font-mono text-xs text-white outline-none focus:border-cyan-300"><option value="">Manual Bundle fields</option>{bindings.map((binding) => <option key={getText(binding, 'runtime_binding_id')} value={getText(binding, 'runtime_binding_id')}>{shortId(getText(binding, 'runtime_binding_id'), 28)} · {getText(binding, 'capability_id')}</option>)}</select></label><label className="grid gap-2"><span className="eyebrow">Capability</span><input value={modelClass} onChange={(event) => setModelClass(event.target.value)} className="h-10 rounded-lg border border-input bg-[#07111d] px-3 font-mono text-xs text-white outline-none focus:border-cyan-300" /></label><label className="grid gap-2"><span className="eyebrow">Visibility</span><select value={visibility} onChange={(event) => setVisibility(event.target.value as typeof visibility)} className="h-10 rounded-lg border border-input bg-[#07111d] px-3 text-sm text-white outline-none focus:border-cyan-300"><option value="private">Private</option><option value="shared">Shared</option><option value="public">Public</option></select></label><label className="grid gap-2"><span className="eyebrow">Bundle ID</span><input value={bundleId} onChange={(event) => setBundleId(event.target.value)} disabled={Boolean(bindingId)} className="h-10 rounded-lg border border-input bg-[#07111d] px-3 font-mono text-xs text-white outline-none focus:border-cyan-300 disabled:opacity-50" /></label><label className="grid gap-2"><span className="eyebrow">Bundle hash</span><input value={bundleHash} onChange={(event) => setBundleHash(event.target.value)} disabled={Boolean(bindingId)} className="h-10 rounded-lg border border-input bg-[#07111d] px-3 font-mono text-xs text-white outline-none focus:border-cyan-300 disabled:opacity-50" /></label><label className="grid gap-2"><span className="eyebrow">Fixed price Q</span><input inputMode="decimal" value={fixedPrice} onChange={(event) => setFixedPrice(event.target.value)} className="h-10 rounded-lg border border-input bg-[#07111d] px-3 text-sm text-white outline-none focus:border-cyan-300" /></label><label className="grid gap-2"><span className="eyebrow">Minimum deposit Q</span><input inputMode="decimal" value={minimumDeposit} onChange={(event) => setMinimumDeposit(event.target.value)} className="h-10 rounded-lg border border-input bg-[#07111d] px-3 text-sm text-white outline-none focus:border-cyan-300" /></label><div className="flex flex-wrap items-center gap-3 lg:col-span-3"><label className="flex items-center gap-2 text-xs text-slate-300"><input type="checkbox" checked={acceptsExternal} onChange={(event) => setAcceptsExternal(event.target.checked)} />Accept external requests</label><label className="flex items-center gap-2 text-xs text-slate-300"><input type="checkbox" checked={validationEnabled} onChange={(event) => setValidationEnabled(event.target.checked)} />Require validation</label></div><div className="flex items-end justify-end"><Button className="w-full bg-cyan-300 text-[#06121d] hover:bg-cyan-200" disabled={busy} onClick={() => void createDraft()}><RadioTower />{busy ? 'Creating...' : 'Create draft'}</Button></div>{message ? <div className="lg:col-span-4"><OperationNotice message={message} onDismiss={() => setMessage(null)} /></div> : null}</CardContent></Card>
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
  const [busy, setBusy] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const plugins = workspace?.plugin_directory ?? []
  const deployments = workspace?.model_deployments ?? []
  const artifactSets = inventoryRecords(workspace?.model_artifact_sets)
  const instances = workspace?.provider_instances ?? []

  useEffect(() => {
    if (!providerType && plugins.length > 0) setProviderType(getText(plugins[0], 'plugin_id'))
  }, [plugins, providerType])

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
      await dashboardApi.requestModelInstall({ provider_type: providerType, model_id: modelId.trim(), source_url: sourceUrl.trim() })
      setMessage('Model installation queued. Run the materializer, then refresh this workspace.')
      onRefresh()
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : 'Model installation request failed.')
    } finally { setBusy(null) }
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
      await dashboardApi.registerBundleFromInstall(id, { bundle_id: nextBundleId, workload_type: workloadType, endpoint })
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
    <Card className="border-border/80 bg-card py-0 shadow-none"><CardHeader className="border-b border-border/70 px-5 py-4"><p className="eyebrow">Operator inputs</p><CardTitle className="mt-1 text-lg font-semibold">Name the next immutable objects</CardTitle><p className="mt-1 text-sm leading-6 text-muted-foreground">These values stay in the dashboard flow; no terminal prompt is required for Bundle registration, provider materialization, or Runtime Binding.</p></CardHeader><CardContent className="grid gap-3 p-5 lg:grid-cols-4"><label className="grid gap-2"><span className="eyebrow">Bundle ID</span><input value={bundleId} onChange={(event) => setBundleId(event.target.value)} placeholder="bundle-whisper-small" className="h-10 rounded-lg border border-input bg-[#07111d] px-3 font-mono text-xs text-white outline-none focus:border-cyan-300" /></label><label className="grid gap-2"><span className="eyebrow">Capability version</span><input value={capabilityVersion} onChange={(event) => setCapabilityVersion(event.target.value)} className="h-10 rounded-lg border border-input bg-[#07111d] px-3 font-mono text-xs text-white outline-none focus:border-cyan-300" /></label><label className="grid gap-2 lg:col-span-2"><span className="eyebrow">Capability definition hash</span><input value={capabilityDefinitionHash} onChange={(event) => setCapabilityDefinitionHash(event.target.value)} placeholder="sha256:..." className="h-10 rounded-lg border border-input bg-[#07111d] px-3 font-mono text-xs text-white outline-none focus:border-cyan-300" /></label></CardContent></Card>
    <Card className="border-border/80 bg-card py-0 shadow-none"><CardHeader className="border-b border-border/70 px-5 py-4"><p className="eyebrow">Step 1</p><CardTitle className="mt-1 text-lg font-semibold">Install and materialize model</CardTitle><p className="mt-1 text-sm leading-6 text-muted-foreground">The source URL is used by the node-side model store. The browser never supplies a target path or executes a shell command.</p></CardHeader><CardContent className="grid gap-3 p-5 lg:grid-cols-4"><label className="grid gap-2"><span className="eyebrow">Provider type</span><select value={providerType} onChange={(event) => setProviderType(event.target.value)} className="h-10 rounded-lg border border-input bg-[#07111d] px-3 text-sm text-white outline-none focus:border-cyan-300"><option value="">Select Provider</option>{plugins.map((plugin) => <option key={getText(plugin, 'plugin_id')} value={getText(plugin, 'plugin_id')}>{getText(plugin, 'display_name') || getText(plugin, 'plugin_id')}</option>)}</select></label><label className="grid gap-2"><span className="eyebrow">Model ID</span><input value={modelId} onChange={(event) => setModelId(event.target.value)} placeholder="whisper-small" className="h-10 rounded-lg border border-input bg-[#07111d] px-3 font-mono text-xs text-white outline-none focus:border-cyan-300" /></label><label className="grid gap-2 lg:col-span-2"><span className="eyebrow">Source URL</span><input value={sourceUrl} onChange={(event) => setSourceUrl(event.target.value)} placeholder="https://.../model.bin" className="h-10 rounded-lg border border-input bg-[#07111d] px-3 text-xs text-white outline-none focus:border-cyan-300" /></label><label className="grid gap-2"><span className="eyebrow">Bundle workload</span><input value={workloadType} onChange={(event) => setWorkloadType(event.target.value)} className="h-10 rounded-lg border border-input bg-[#07111d] px-3 font-mono text-xs text-white outline-none focus:border-cyan-300" /></label><label className="grid gap-2 lg:col-span-2"><span className="eyebrow">Bundle endpoint</span><input value={endpoint} onChange={(event) => setEndpoint(event.target.value)} className="h-10 rounded-lg border border-input bg-[#07111d] px-3 font-mono text-xs text-white outline-none focus:border-cyan-300" /></label><div className="flex items-end gap-2"><Button className="bg-cyan-300 text-[#06121d] hover:bg-cyan-200" disabled={busy === 'install'} onClick={() => void installModel()}><Database />{busy === 'install' ? 'Queueing...' : 'Queue install'}</Button><Button variant="outline" className="border-border bg-[#091725]" disabled={busy === 'process'} onClick={() => void processInstalls()}><RefreshCw />{busy === 'process' ? 'Running...' : 'Materialize'}</Button></div></CardContent></Card>
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

function WalletActivityList({ title, items, emptyDetail }: { title: string; items: DashboardRecord[]; emptyDetail: string }) {
  return <Card className="border-border/80 bg-card py-0 shadow-none"><CardHeader className="border-b border-border/70 px-5 py-4"><CardTitle className="text-base font-semibold">{title}</CardTitle></CardHeader><CardContent className="p-0">{items.length === 0 ? <p className="px-5 py-6 text-sm leading-6 text-muted-foreground">{emptyDetail}</p> : <div className="divide-y divide-border/70">{items.slice(-6).reverse().map((item, index) => {
    const quote = getRecord(item)?.quote
    const charges = getRecord(getRecord(quote)?.charges)
    const amount = getText(item, 'amount_q') || getText(charges, 'total_q')
    return <div key={getText(item, 'event_id') || `${title}-${index}`} className="min-w-0 px-5 py-3"><div className="flex min-w-0 items-start justify-between gap-3"><div className="min-w-0"><p className="truncate text-sm font-medium text-slate-100">{getText(item, 'event_type') || 'Recorded activity'}</p><p className="mt-1 truncate font-mono text-[11px] text-slate-500">{getText(item, 'occurred_at') || getText(item, 'created_at') || 'Time not reported'}</p></div>{amount ? <p className="shrink-0 font-mono text-xs text-cyan-100">{amount} Q</p> : null}</div></div>
  })}</div>}</CardContent></Card>
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
        <Card className={cn('border py-0 shadow-none', identityRegistered ? 'border-emerald-300/25 bg-emerald-300/[0.04]' : 'border-amber-300/25 bg-amber-300/[0.04]')}><CardContent className="p-5"><p className="text-sm text-muted-foreground">Network identity</p><p className={cn('mt-2 text-xl font-semibold', identityRegistered ? 'text-emerald-100' : 'text-amber-100')}>{identityRegistered ? 'Registered' : 'Not registered'}</p><p className="mt-2 text-xs leading-5 text-muted-foreground">{identityRegistered ? 'Identity evidence is visible in the current registry projection.' : 'No wallet identity record is visible in this chain projection.'}</p></CardContent></Card>
        <Card className="border-border/80 bg-card py-0 shadow-none"><CardContent className="p-5"><p className="text-sm text-muted-foreground">Recorded usage</p><p className="mt-2 font-mono text-2xl font-semibold tracking-tight text-slate-100">{wallet.usage_events.length}</p><p className="mt-2 text-xs leading-5 text-muted-foreground">{wallet.allocation_events.length} allocation events and {wallet.dispute_events.length} disputes retained locally.</p></CardContent></Card>
      </div>
      {!identityRegistered ? <Card className="border-amber-300/25 bg-amber-300/[0.04] py-0 shadow-none"><CardContent className="flex flex-col gap-4 p-4 sm:flex-row sm:items-start sm:justify-between"><div className="flex gap-3"><CircleDot className="mt-0.5 size-4 shrink-0 text-amber-200" /><div><p className="text-sm font-semibold text-amber-100">Wallet is bound, but the network reset removed its registry identity</p><p className="mt-1 max-w-3xl text-sm leading-6 text-amber-100/75">Register this same Wallet in the current chain. This submits a signed, no-fee consensus operation. It does not expose the private key, replace ownership or create a second Wallet.</p>{walletState?.identity_error ? <p className="mt-2 text-xs leading-5 text-amber-200">Identity quorum is currently unavailable: {String(walletState.identity_error)}</p> : null}</div></div><Button className="shrink-0 bg-amber-200 text-[#191204] hover:bg-amber-100" disabled={busy || Boolean(walletState?.identity_error)} onClick={() => void registerNetworkIdentity()}><CircleDot />{busy ? 'Submitting...' : 'Register in network'}</Button></CardContent></Card> : null}
      <div className="grid gap-4 xl:grid-cols-2"><WalletActivityList title="Usage activity" items={wallet.usage_events} emptyDetail="No metered usage has been recorded for this Wallet." /><WalletActivityList title="Allocation activity" items={wallet.allocation_events} emptyDetail="No allocation or settlement events have been recorded for this Wallet." /></div>
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

function ProviderWorkspaceScreen({ screen, workspace, isLoading, error, onRefresh }: { screen: 'providers' | 'catalog'; workspace: ProviderWorkspace | undefined; isLoading: boolean; error: Error | null; onRefresh: () => void }) {
  const [pluginId, setPluginId] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [configuration, setConfiguration] = useState('{\n  "base_url": "http://127.0.0.1:11434"\n}')
  const [busy, setBusy] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const plugins = workspace?.plugin_directory ?? []
  const instances = workspace?.provider_instances ?? []
  const deployments = workspace?.model_deployments ?? []
  const bindings = workspace?.runtime_bindings ?? []

  useEffect(() => {
    if (!pluginId && plugins.length > 0) {
      const nextPlugin = getText(plugins[0], 'plugin_id')
      setPluginId(nextPlugin)
      setDisplayName(getText(plugins[0], 'display_name') || nextPlugin)
    }
  }, [pluginId, plugins])

  function choosePlugin(nextPluginId: string) {
    setPluginId(nextPluginId)
    const plugin = plugins.find((item) => getText(item, 'plugin_id') === nextPluginId)
    if (plugin && !displayName.trim()) setDisplayName(getText(plugin, 'display_name') || nextPluginId)
  }

  async function attach() {
    let parsedConfiguration: DashboardRecord
    try {
      const candidate: unknown = JSON.parse(configuration)
      const record = getRecord(candidate)
      if (!record) throw new Error('Configuration must be a JSON object.')
      parsedConfiguration = record
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : 'Provider configuration is not valid JSON.')
      return
    }
    if (!pluginId || !displayName.trim()) {
      setMessage('Select a Provider plugin and set a display name.')
      return
    }
    setBusy('attach')
    setMessage(null)
    try {
      const result = await dashboardApi.attachProvider({ plugin_id: pluginId, display_name: displayName.trim(), configuration: parsedConfiguration })
      setMessage(`Provider ${getText(result, 'provider_instance_id') || displayName.trim()} was attached. Probe it before using it for a Bundle.`)
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
      const discovered = getRecord(result)?.items
      setMessage(action === 'discover-models' ? `Model discovery completed: ${Array.isArray(discovered) ? discovered.length : 0} model deployment(s) found.` : `Provider ${providerInstanceId} health check completed.`)
      onRefresh()
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : 'Provider operation failed.')
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
      <Card className="border-border/80 bg-card py-0 shadow-none"><CardHeader className="border-b border-border/70 px-5 py-4"><p className="eyebrow">Attach existing Provider</p><CardTitle className="mt-1 text-lg font-semibold">Create Provider instance</CardTitle><p className="mt-1 text-sm leading-6 text-muted-foreground">Use the Plugin's documented configuration. For local Ollama, the usual value is a `base_url`; no Provider credentials are persisted in this form.</p></CardHeader><CardContent className="grid gap-3 p-5 lg:grid-cols-[0.8fr_0.9fr_1.5fr_auto]"><label className="grid gap-2"><span className="eyebrow">Plugin</span><select value={pluginId} onChange={(event) => choosePlugin(event.target.value)} className="h-10 rounded-lg border border-input bg-[#07111d] px-3 text-sm text-white outline-none focus:border-cyan-300">{plugins.map((plugin) => <option key={getText(plugin, 'plugin_id')} value={getText(plugin, 'plugin_id')}>{getText(plugin, 'display_name') || getText(plugin, 'plugin_id')}</option>)}</select></label><label className="grid gap-2"><span className="eyebrow">Provider name</span><input value={displayName} onChange={(event) => setDisplayName(event.target.value)} placeholder="Node Ollama" className="h-10 rounded-lg border border-input bg-[#07111d] px-3 text-sm text-white outline-none focus:border-cyan-300" /></label><label className="grid gap-2"><span className="eyebrow">Configuration JSON</span><input value={configuration} onChange={(event) => setConfiguration(event.target.value)} className="h-10 rounded-lg border border-input bg-[#07111d] px-3 font-mono text-xs text-white outline-none focus:border-cyan-300" /></label><div className="flex items-end"><Button className="w-full bg-cyan-300 text-[#06121d] hover:bg-cyan-200" disabled={busy === 'attach' || plugins.length === 0} onClick={() => void attach()}><ServerCog />{busy === 'attach' ? 'Attaching...' : 'Attach'}</Button></div></CardContent></Card>
      <Card className="border-border/80 bg-card py-0 shadow-none"><CardHeader className="flex-row items-center justify-between gap-3 border-b border-border/70 px-5 py-4"><div><p className="eyebrow">Attached inventory</p><CardTitle className="mt-1 text-lg font-semibold">Provider instances</CardTitle></div><Button variant="outline" size="sm" className="border-border bg-[#091725]" onClick={onRefresh}><RefreshCw />Refresh</Button></CardHeader><CardContent className="divide-y divide-border/70 p-0">{instances.length === 0 ? <EmptyState title="No Provider instances attached" detail="Attach a known local Provider above. The Dashboard will not guess an upstream endpoint or create credentials." actionLabel="Refresh catalog" onAction={onRefresh} /> : instances.map((instance) => { const id = getText(instance, 'provider_instance_id'); return <div key={id} className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-center"><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><p className="font-medium text-white">{getText(instance, 'display_name') || id}</p><StatusBadge value={getText(instance, 'health_status') || 'unknown'} /></div><p className="mt-1 break-all font-mono text-[11px] text-slate-500">{id} · {String(getRecord(instance)?.model_count ?? 0)} models · {String(getRecord(instance)?.runtime_binding_ready_count ?? 0)} ready bindings</p></div><div className="flex flex-wrap gap-2"><Button variant="outline" size="sm" className="border-border bg-[#091725]" disabled={busy === `${id}:probe`} onClick={() => void runProviderOperation(id, 'probe')}><Gauge />Probe</Button><Button variant="outline" size="sm" className="border-cyan-300/25 bg-[#091725] text-cyan-100" disabled={busy === `${id}:discover-models`} onClick={() => void runProviderOperation(id, 'discover-models')}><Database />Discover models</Button></div></div> })}</CardContent></Card>
      <div className="grid gap-4 lg:grid-cols-2"><InventoryCard title="Model deployments" detail="Discovered model supply. Runtime binding is required before Endpoint admission." items={deployments} primaryKey="model_deployment_id" /><InventoryCard title="Runtime bindings" detail="Compatibility records backing eligible Bundle and Endpoint runtime selection." items={bindings} primaryKey="runtime_binding_id" /></div>
    </> : null}
  </div>
}

function InventoryCard({ title, detail, items, primaryKey }: { title: string; detail: string; items: DashboardRecord[]; primaryKey: string }) {
  return <Card className="border-border/80 bg-card py-0 shadow-none"><CardHeader className="border-b border-border/70 px-5 py-4"><CardTitle className="text-base font-semibold">{title}</CardTitle><p className="mt-1 text-xs leading-5 text-muted-foreground">{detail}</p></CardHeader><CardContent className="p-0">{items.length === 0 ? <p className="px-5 py-6 text-sm text-muted-foreground">No records yet.</p> : <div className="divide-y divide-border/70">{items.slice(0, 8).map((item) => <div key={getText(item, primaryKey)} className="px-5 py-3"><div className="flex items-center justify-between gap-3"><p className="truncate font-mono text-xs text-slate-200">{shortId(getText(item, primaryKey), 24)}</p><StatusBadge value={getText(item, 'status') || 'recorded'} /></div></div>)}</div>}</CardContent></Card>
}

function OperationNotice({ message, onDismiss }: { message: string; onDismiss: () => void }) {
  const failed = /failed|rejected|required|invalid|unavailable|error/i.test(message)
  return <div className={cn('flex items-start justify-between gap-3 rounded-lg border p-3 text-sm', failed ? 'border-rose-300/25 bg-rose-300/[0.05] text-rose-100' : 'border-emerald-300/25 bg-emerald-300/[0.05] text-emerald-100')}><p className="leading-5">{message}</p><Button variant="ghost" size="icon-xs" className="shrink-0" aria-label="Dismiss operation result" onClick={onDismiss}>×</Button></div>
}

function OperationsWorkspace({ screen, data, onNavigate, onRefresh }: { screen: OperationsScreen; data: DashboardData; onNavigate: NavigationProps['onNavigate']; onRefresh: () => void }) {
  const home = data.home.data
  const fleet = data.fleet.data
  const readiness = data.readiness.data
  const bundles = data.bundles.data?.items ?? []
  const endpoints = data.endpoints.data?.items ?? []
  const validation = summarizeValidation(endpoints)
  const publishedEndpoints = endpoints.filter((endpoint) => endpoint.publication_status === 'published').length
  const modelCount = new Set(bundles.map((bundle) => bundle.model_id).filter((modelId) => modelId && modelId !== 'unknown')).size
  const nodeIdentity = home?.bootstrap.node_identity ?? fleet?.node
  const wallet = home?.bootstrap.owner_wallet
  const queue = fleet?.queue

  const workspace = {
    agents: {
      eyebrow: 'Execution supervision',
      title: 'Agents',
      detail: 'Observe current execution pressure before adding work. Agent-specific controls will appear here as they are exposed by the control plane.',
      facts: [
        { label: 'Active work', value: formatCount(queue?.active ?? 0), detail: 'requests executing now' },
        { label: 'Queued work', value: formatCount(queue?.queued ?? 0), detail: 'requests awaiting admission' },
      ],
      related: 'endpoints' as const,
      relatedLabel: 'Review Endpoints',
    },
    market: {
      eyebrow: 'Service discovery',
      title: 'Market',
      detail: 'Inspect the local offer inventory before publishing or consuming services. Remote discovery remains governed by the Network workspace.',
      facts: [
        { label: 'Published offers', value: formatCount(publishedEndpoints), detail: 'local Endpoints visible to the network' },
        { label: 'Configured offers', value: formatCount(endpoints.length), detail: 'all local Endpoint records' },
      ],
      related: 'endpoints' as const,
      relatedLabel: 'Review Endpoints',
    },
    catalog: {
      eyebrow: 'Operator inventory',
      title: 'Catalog',
      detail: 'Catalog capability is represented by the registered Provider inventory. Installation and approval controls stay inside this React workspace as they are migrated from the control API.',
      facts: [
        { label: 'Providers', value: formatCount(home?.bootstrap.provider_count ?? 0), detail: 'registered Provider records' },
        { label: 'Bundles', value: formatCount(bundles.length), detail: 'immutable deployments using catalog capacity' },
      ],
      related: 'providers' as const,
      relatedLabel: 'Inspect Providers',
    },
    wallet: {
      eyebrow: 'Operator ownership',
      title: 'Wallet',
      detail: 'The owner Wallet binds this Hypervisor to network-facing management actions. Private key material is never returned to the browser.',
      facts: [
        { label: 'Binding', value: wallet?.configured ? 'Configured' : 'Not configured', detail: wallet?.label || 'No owner wallet record' },
        { label: 'Wallet ID', value: wallet?.wallet_id ? shortId(wallet.wallet_id) : 'Unavailable', detail: 'current operator beneficiary identity' },
      ],
      related: 'network' as const,
      relatedLabel: 'Review Network',
    },
    settings: {
      eyebrow: 'Host configuration',
      title: 'Settings',
      detail: 'Host identity and capacity reporting are read from the active Hypervisor record. The Resource Probe supplies the values shown in the persistent footer.',
      facts: [
        { label: 'Node', value: getText(nodeIdentity, 'node_id') || 'Local Hypervisor', detail: getText(nodeIdentity, 'base_url') || 'local control address' },
        { label: 'Resource probe', value: fleet?.resources.probe ? 'Reporting' : 'Unavailable', detail: getText(fleet?.resources.probe, 'source') || 'no probe evidence was supplied' },
      ],
      related: 'network' as const,
      relatedLabel: 'Review Network',
    },
    providers: {
      eyebrow: 'Runtime supply',
      title: 'Provider Plugins',
      detail: 'Provider records are the backing systems for Bundles. A Provider is not a consumer-facing Endpoint and is never published by itself.',
      facts: [
        { label: 'Providers', value: formatCount(home?.bootstrap.provider_count ?? 0), detail: 'registered Provider records' },
        { label: 'Bound Bundles', value: formatCount(bundles.length), detail: 'deployments consuming Provider capacity' },
      ],
      related: 'bundles' as const,
      relatedLabel: 'Review Bundles',
    },
    models: {
      eyebrow: 'Model inventory',
      title: 'Models',
      detail: 'Model inventory is derived from immutable Bundle definitions, so an operator can trace every deployed model back to its runtime and Endpoint relationship.',
      facts: [
        { label: 'Models in Bundles', value: formatCount(modelCount), detail: 'unique model identifiers in the local deployment set' },
        { label: 'Bundles', value: formatCount(bundles.length), detail: 'immutable model deployment records' },
      ],
      related: 'bundles' as const,
      relatedLabel: 'Review Bundles',
    },
    validation: {
      eyebrow: 'Endpoint assurance',
      title: 'Validation',
      detail: 'Validation status is recorded against Endpoints. It supplements runtime health and does not change a Bundle in place.',
      facts: [
        { label: 'Published', value: formatCount(validation.published), detail: 'Endpoint records with published status' },
        { label: 'Awaiting review', value: formatCount(validation.pending + validation.unvalidated), detail: 'pending or unvalidated Endpoint records' },
      ],
      related: 'endpoints' as const,
      relatedLabel: 'Review Endpoints',
    },
    network: {
      eyebrow: 'Network control plane',
      title: 'Network',
      detail: 'Network readiness is evaluated from the configured consensus and replication evidence. Remote Hypervisors are discovered here, not through a decorative tab.',
      facts: [
        { label: 'Readiness', value: readiness?.network_ready ? 'Ready' : 'Review required', detail: readiness?.overall_state || 'network status has not arrived' },
        { label: 'Node address', value: getText(nodeIdentity, 'base_url') || 'Unavailable', detail: 'advertised local control address' },
      ],
      related: 'endpoints' as const,
      relatedLabel: 'Review Endpoints',
    },
  }[screen]

  return (
    <div className="space-y-4">
      <ScreenHeading eyebrow={workspace.eyebrow} title={workspace.title} detail={workspace.detail} />
      <Card className="border-border/80 bg-card py-0 shadow-none">
        <CardHeader className="flex-row items-center justify-between gap-3 border-b border-border/75 px-5 py-4">
          <div>
            <CardTitle className="text-lg font-semibold tracking-[-0.03em]">Current local state</CardTitle>
            <p className="mt-1 text-sm text-muted-foreground">Live Hypervisor read-model data, refreshed automatically every 20 seconds.</p>
          </div>
          <Button variant="outline" size="sm" className="shrink-0 border-border bg-[#091725]" onClick={onRefresh}>
            <RefreshCw className={cn('size-3.5', data.home.isFetching && 'animate-spin')} />
            Refresh
          </Button>
        </CardHeader>
        <CardContent className="p-0">
          <dl className="divide-y divide-border/70">
            {workspace.facts.map((fact) => <div key={fact.label} className="grid gap-1 px-5 py-4 sm:grid-cols-[minmax(12rem,0.75fr)_minmax(0,1.25fr)] sm:items-baseline sm:gap-5">
              <dt className="font-mono text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-500">{fact.label}</dt>
              <dd><span className="font-medium text-slate-100">{fact.value}</span><p className="mt-1 text-xs text-muted-foreground">{fact.detail}</p></dd>
            </div>)}
          </dl>
          <div className="flex flex-wrap gap-2 border-t border-border/70 px-5 py-4">
            <Button size="sm" className="bg-cyan-300 text-[#06121d] hover:bg-cyan-200" onClick={() => onNavigate(workspace.related)}>{workspace.relatedLabel}<ChevronRight /></Button>
            <Button variant="outline" size="sm" className="border-border bg-[#091725]" onClick={() => onNavigate('overview')}>Return to Overview</Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
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

function ResourceOverview({ fleet, isLoading, error }: { fleet: DashboardData['fleet']['data']; isLoading: boolean; error: Error | null }) {
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
      <CardHeader className="px-4 py-4"><div><p className="eyebrow">Host telemetry</p><CardTitle className="mt-1 text-base font-semibold">Resource usage</CardTitle></div></CardHeader>
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

function ValidationOverview({ endpoints, summary, isLoading, error }: { endpoints: Endpoint[]; summary: ReturnType<typeof summarizeValidation>; isLoading: boolean; error: Error | null }) {
  if (isLoading && endpoints.length === 0) return <PanelSkeleton rows={3} />
  if (error && endpoints.length === 0) return <PanelError title="Validation data is unavailable" error={error} />
  return <Card className="border-border/80 bg-card py-0 shadow-none"><CardHeader className="px-4 py-4"><div><p className="eyebrow">Endpoint assurance</p><CardTitle className="mt-1 text-base font-semibold">Validation overview</CardTitle></div></CardHeader><CardContent className="px-4 pb-4"><div className="flex items-end gap-5"><div className="grid size-[88px] place-items-center rounded-full border-[7px] border-cyan-300/20 bg-cyan-300/5"><div className="text-center"><p className="font-mono text-2xl font-semibold text-white">{summary.total}</p><p className="font-mono text-[9px] uppercase tracking-[0.12em] text-cyan-100/65">offers</p></div></div><div className="space-y-2 text-xs"><StatusLine label="Published" value={summary.published} className="bg-emerald-300" /><StatusLine label="Pending review" value={summary.pending} className="bg-amber-300" /><StatusLine label="Unvalidated" value={summary.unvalidated} className="bg-slate-400" /></div></div><p className="mt-4 text-xs leading-5 text-muted-foreground">Validation reflects endpoint evidence. It does not replace Runtime health or the Bundle publication chain.</p></CardContent></Card>
}

function StatusLine({ label, value, className }: { label: string; value: number; className: string }) {
  return <div className="flex items-center gap-2"><span className={cn('size-2 rounded-full', className)} /><span className="text-slate-300">{label}</span><span className="ml-auto font-mono text-slate-100">{value}</span></div>
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

function ResourceFooter({ fleet, isLoading }: { fleet: DashboardData['fleet']['data']; isLoading: boolean }) {
  const resources = fleet?.resources
  const cpu = resourceUsage(resources?.total.cpu, resources?.free.cpu)
  const ram = resourceUsage(resources?.total.ram_mb, resources?.free.ram_mb)
  const vram = resourceUsage(resources?.total.vram_mb, resources?.free.vram_mb)
  const queue = fleet?.queue
  const items = [
    { label: 'CPU', value: isLoading ? '…' : formatPercent(cpu.percent), icon: Cpu, tone: 'text-cyan-300' },
    { label: 'RAM', value: isLoading ? '…' : formatPercent(ram.percent), icon: Database, tone: 'text-violet-300' },
    { label: 'VRAM', value: isLoading ? '…' : resources?.probe?.gpu_reported ? formatPercent(vram.percent) : '—', icon: Zap, tone: 'text-amber-300' },
    { label: 'Sessions', value: isLoading ? '…' : formatCount(queue?.active ?? 0), icon: Activity, tone: 'text-sky-300' },
  ]
  return <footer className="fixed inset-x-0 bottom-0 z-20 border-t border-border/75 bg-[#060e18]/95 backdrop-blur-xl"><div className="mx-auto flex w-full max-w-[1760px] overflow-x-auto px-3 lg:px-5">{items.map(({ label, value, icon: Icon, tone }) => <div key={label} className="flex min-w-40 items-center gap-2 border-r border-border/70 px-4 py-2.5 first:pl-0"><Icon className={cn('size-4', tone)} /><div><p className="font-mono text-[9px] uppercase tracking-[0.12em] text-cyan-100/60">{label}</p><p className="mt-0.5 font-mono text-xs font-semibold text-white">{value}</p></div></div>)}</div></footer>
}

function ScreenHeading({ eyebrow, title, detail }: { eyebrow: string; title: string; detail: string }) {
  return <section className="border-b border-border/75 pb-4"><p className="eyebrow">{eyebrow}</p><h1 className="mt-1 text-2xl font-semibold tracking-[-0.045em] text-white sm:text-3xl">{title}</h1><p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">{detail}</p></section>
}

function StatusBadge({ value }: { value: string }) {
  const normalized = value.toLowerCase().replaceAll(' ', '_')
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
    const validationStatus = getText(endpoint.validation, 'validation_status')
    if (validationStatus === 'pending' || validationStatus === 'running') summary.pending += 1
    if (!validationStatus || validationStatus === 'unvalidated') summary.unvalidated += 1
    return summary
  }, { total: 0, published: 0, pending: 0, unvalidated: 0 })
}

export default App
