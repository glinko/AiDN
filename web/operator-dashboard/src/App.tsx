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
  getText,
  resourceUsage,
  shortId,
} from '@/lib/format'
import { useDashboardData } from '@/hooks/use-dashboard'
import { DashboardApiError, dashboardApi, type AccessCredential, type AgentPermissionCatalog, type DashboardAccessStatus, type EnrollmentRequest } from '@/lib/api'
import { dashboardScreens, useOperatorDashboardStore, type DashboardScreen } from '@/stores/operator-dashboard'
import type { Bundle, Endpoint, ReadinessStep } from '@/lib/types'

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
  const hasRefreshError = [data.home, data.readiness, data.fleet, data.bundles, data.endpoints].some(
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
            <BundlesScreen bundles={data.bundles.data?.items ?? []} isLoading={data.bundles.isLoading} error={data.bundles.error} onNavigate={navigate} />
          ) : null}
          {activeScreen === 'endpoints' ? (
            <EndpointsScreen endpoints={data.endpoints.data?.items ?? []} isLoading={data.endpoints.isLoading} error={data.endpoints.error} onNavigate={navigate} />
          ) : null}
          {activeScreen === 'settings' ? <SettingsAccessWorkspace /> : null}
          {isOperationsScreen(activeScreen) ? (
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

function BundleTableSection({ bundles, isLoading, error, onNavigate, compact = false }: { bundles: Bundle[]; isLoading: boolean; error: Error | null; onNavigate: NavigationProps['onNavigate']; compact?: boolean }) {
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
        {bundles.length > 0 ? <BundleTable bundles={bundles} onNavigate={onNavigate} /> : null}
      </CardContent>
    </Card>
  )
}

function BundleTable({ bundles, onNavigate }: { bundles: Bundle[]; onNavigate: NavigationProps['onNavigate'] }) {
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
  ]
  const table = useReactTable({ data: bundles, columns, getCoreRowModel: getCoreRowModel() })
  return <DataTable table={table} />
}

function BundlesScreen({ bundles, isLoading, error, onNavigate }: { bundles: Bundle[]; isLoading: boolean; error: Error | null; onNavigate: NavigationProps['onNavigate'] }) {
  return (
    <div className="space-y-4">
      <ScreenHeading eyebrow="Bundle-first operations" title="Bundles" detail="Bundles are immutable operator deployments. Provider, model, runtime and Endpoint state are inspected from one canonical object." />
      <BundleTableSection bundles={bundles} isLoading={isLoading} error={error} onNavigate={onNavigate} />
    </div>
  )
}

function EndpointsScreen({ endpoints, isLoading, error, onNavigate }: { endpoints: Endpoint[]; isLoading: boolean; error: Error | null; onNavigate: NavigationProps['onNavigate'] }) {
  return (
    <div className="space-y-4">
      <ScreenHeading eyebrow="Network-facing service offers" title="Endpoints" detail="Endpoint publication remains commercially distinct from the Bundle that runs it. This table shows the bound configuration, execution state and public readiness." />
      <Card className="border-border/80 bg-card py-0 shadow-none">
        <CardHeader className="border-b border-border/75 px-5 py-4">
          <div><p className="eyebrow">Endpoint inventory</p><CardTitle className="mt-1 text-lg font-semibold tracking-[-0.03em]">Published and local offers</CardTitle></div>
          <Button variant="ghost" size="sm" className="text-cyan-200 hover:bg-cyan-300/10 hover:text-cyan-100" onClick={() => onNavigate('bundles')}>View Bundles<ChevronRight /></Button>
        </CardHeader>
        <CardContent className="p-0">
          {isLoading && endpoints.length === 0 ? <TableSkeleton columns={5} rows={6} /> : null}
          {error && endpoints.length === 0 ? <PanelError title="Endpoint inventory is unavailable" error={error} /> : null}
          {!isLoading && !error && endpoints.length === 0 ? <EmptyState title="No Endpoint offers are configured" detail="Create a Bundle first, then review its publication readiness before exposing it to the Market." actionLabel="Open Bundles" onAction={() => onNavigate('bundles')} /> : null}
          {endpoints.length > 0 ? <EndpointTable endpoints={endpoints} /> : null}
        </CardContent>
      </Card>
    </div>
  )
}

function EndpointTable({ endpoints }: { endpoints: Endpoint[] }) {
  const columns: ColumnDef<Endpoint>[] = [
    { accessorKey: 'display_name', header: 'Endpoint', cell: ({ row }) => <div><p className="font-medium text-slate-100">{row.original.display_name || shortId(row.original.endpoint_id, 22)}</p><p className="mt-0.5 font-mono text-[10px] text-slate-500">{shortId(row.original.endpoint_id)}</p></div> },
    { accessorKey: 'model_class', header: 'Capability', cell: ({ row }) => <span className="text-xs text-slate-200">{row.original.model_class || row.original.capabilities[0] || '—'}</span> },
    { accessorKey: 'visibility', header: 'Visibility', cell: ({ row }) => <StatusBadge value={row.original.visibility || 'private'} /> },
    { accessorKey: 'publication_status', header: 'Publication', cell: ({ row }) => <StatusBadge value={row.original.publication_status} /> },
    { accessorKey: 'runtime_status', header: 'Runtime', cell: ({ row }) => <StatusBadge value={row.original.runtime_status} /> },
  ]
  const table = useReactTable({ data: endpoints, columns, getCoreRowModel: getCoreRowModel() })
  return <DataTable table={table} />
}

function SettingsAccessWorkspace() {
  const [status, setStatus] = useState<DashboardAccessStatus | null>(null)
  const [pairingCode, setPairingCode] = useState('')
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
      await dashboardApi.pairDashboard(pairingCode.trim())
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
        {status.enabled && !status.session.active ? <Card className="border-border/80 bg-card py-0 shadow-none"><CardHeader className="border-b border-border/70 px-5 py-4"><p className="eyebrow">Terminal-to-browser pairing</p><CardTitle className="mt-1 text-lg font-semibold">Unlock this Settings session</CardTitle><p className="mt-1 text-sm leading-6 text-muted-foreground">On the Hypervisor host, run <code className="rounded bg-black/20 px-1.5 py-0.5 font-mono text-xs text-cyan-100">aidn-operator pair</code>. Paste the short-lived code here. It is single-use and never stored by the browser.</p></CardHeader><CardContent className="flex flex-col gap-3 p-5 sm:flex-row sm:items-end"><label className="grid flex-1 gap-2"><span className="eyebrow">Pairing code</span><input value={pairingCode} onChange={(event) => setPairingCode(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') void pair() }} autoComplete="one-time-code" placeholder="Paste code from the node terminal" className="h-10 rounded-lg border border-input bg-[#07111d] px-3 text-sm text-white outline-none transition focus:border-cyan-300" /></label><Button className="bg-cyan-300 text-[#06121d] hover:bg-cyan-200" disabled={!pairingCode.trim() || busy === 'pair'} onClick={() => void pair()}>{busy === 'pair' ? 'Pairing...' : 'Pair dashboard'}<ChevronRight /></Button></CardContent></Card> : null}
        {status.enabled && status.session.active ? <>
          <Card className="border-border/80 bg-card py-0 shadow-none"><CardHeader className="flex-row items-center justify-between gap-3 border-b border-border/70 px-5 py-4"><div><CardTitle className="text-lg font-semibold">Agent enrollment requests</CardTitle><p className="mt-1 text-sm text-muted-foreground">Agents generate an ephemeral encryption key and wait here. Approving sends the credential only in an encrypted envelope.</p></div><Button variant="outline" size="sm" className="border-border bg-[#091725]" onClick={() => void refreshAccess()}><RefreshCw />Refresh</Button></CardHeader><CardContent className="p-0">{enrollments.filter((request) => request.state === 'pending').length === 0 ? <EmptyState title="No pending agent requests" detail="An agent can request access without receiving an operator token or using the host shell." actionLabel="Refresh requests" onAction={() => void refreshAccess()} /> : <div className="divide-y divide-border/70">{enrollments.filter((request) => request.state === 'pending').map((request) => <div key={request.request_id} className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-center"><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><p className="font-medium text-white">{request.label}</p><StatusBadge value={request.state} /></div><p className="mt-1 truncate font-mono text-[11px] text-slate-400">{request.key_fingerprint} · expires {new Date(request.expires_at).toLocaleTimeString()}</p></div><div className="flex gap-2"><Button size="sm" className="bg-cyan-300 text-[#06121d] hover:bg-cyan-200" disabled={busy === request.request_id} onClick={() => void decideEnrollment(request, 'approve')}>Approve</Button><Button variant="outline" size="sm" className="border-rose-300/25 bg-[#091725] text-rose-50 hover:border-rose-300/60" disabled={busy === request.request_id} onClick={() => void decideEnrollment(request, 'reject')}>Reject</Button></div></div>)}</div>}</CardContent></Card>
          <Card className="border-border/80 bg-card py-0 shadow-none"><CardHeader className="flex-row items-start justify-between gap-4 border-b border-border/70 px-5 py-4"><div><p className="eyebrow">MCP agent credentials</p><CardTitle className="mt-1 text-lg font-semibold">Issue a new agent token</CardTitle><p className="mt-1 text-sm leading-6 text-muted-foreground">The token is shown once. An agent authenticates to this node with it; existing values cannot be displayed again.</p></div><Button variant="outline" size="sm" className="shrink-0 border-border bg-[#091725]" disabled={busy === 'logout'} onClick={() => void logout()}><LogOut />Sign out</Button></CardHeader><CardContent className="space-y-4 p-5"><p className="rounded-md border border-border/70 bg-[#07111d] px-3 py-2 font-mono text-[11px] text-slate-400">Operator authority: {status.operator_authority.configured ? status.operator_authority.fingerprint : 'not configured'} · never shared with agents</p><div className="flex flex-col gap-3 sm:flex-row sm:items-end"><label className="grid flex-1 gap-2"><span className="eyebrow">Agent label</span><input value={label} onChange={(event) => setLabel(event.target.value)} maxLength={96} placeholder="For example: coding-agent-node127" className="h-10 rounded-lg border border-input bg-[#07111d] px-3 text-sm text-white outline-none transition focus:border-cyan-300" /></label><Button className="bg-cyan-300 text-[#06121d] hover:bg-cyan-200" disabled={!label.trim() || busy === 'create'} onClick={() => void issueCredential()}><KeyRound />{busy === 'create' ? 'Issuing...' : 'Issue token'}</Button></div>{revealedToken ? <div className="rounded-lg border border-cyan-300/30 bg-cyan-300/[0.06] p-4"><div className="flex items-start justify-between gap-4"><div><p className="eyebrow text-cyan-100">Copy now</p><p className="mt-1 text-sm font-semibold text-cyan-50">New token is visible once</p></div><Button variant="outline" size="sm" className="border-cyan-300/25 bg-[#091725]" onClick={() => void navigator.clipboard.writeText(revealedToken)}><Copy />Copy</Button></div><code className="mt-3 block break-all rounded-md bg-black/25 p-3 font-mono text-xs leading-5 text-cyan-50">{revealedToken}</code><p className="mt-2 text-xs leading-5 text-cyan-100/75">Close this notice after transferring the value through an approved secret channel. Rotation immediately revokes the prior token.</p><Button variant="outline" size="sm" className="mt-3 border-border bg-[#091725]" onClick={() => setRevealedToken(null)}>I stored it</Button></div> : null}</CardContent></Card>
          <Card className="border-border/80 bg-card py-0 shadow-none"><CardHeader className="flex-row items-center justify-between gap-3 border-b border-border/70 px-5 py-4"><div><p className="eyebrow">Active inventory</p><CardTitle className="mt-1 text-lg font-semibold">Agent credentials</CardTitle></div><Button variant="outline" size="sm" className="border-border bg-[#091725]" onClick={() => void refreshAccess()}><RefreshCw />Refresh</Button></CardHeader><CardContent className="p-0">{status.credentials.length === 0 ? <EmptyState title="No agent credentials" detail="Issue a dedicated token for each agent or remote Hypervisor connection." actionLabel="Issue token" onAction={() => void issueCredential()} /> : <div className="divide-y divide-border/70">{status.credentials.map((credential) => <div key={credential.credential_id} className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-center"><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><p className="font-medium text-slate-100">{credential.label}</p><StatusBadge value={credential.state} /></div><p className="mt-1 truncate font-mono text-[11px] text-slate-500">{credential.fingerprint} · {credential.scopes.length} permissions · last used {credential.last_used_at ? new Date(credential.last_used_at).toLocaleString() : 'never'}</p></div>{credential.state === 'active' ? <div className="flex flex-wrap gap-2"><Button variant="outline" size="sm" className="border-cyan-300/30 bg-[#091725] text-cyan-100 hover:bg-cyan-300/10" disabled={busy === credential.credential_id} onClick={() => openPermissions(credential)}><ShieldCheck />Permissions</Button><Button variant="outline" size="sm" className="border-border bg-[#091725]" disabled={busy === credential.credential_id} onClick={() => void rotate(credential)}><RotateCcw />Rotate</Button><Button variant="outline" size="sm" className="border-rose-300/25 bg-transparent text-rose-100 hover:bg-rose-300/10" disabled={busy === credential.credential_id} onClick={() => void revoke(credential)}><Trash2 />Revoke</Button></div> : null}</div>)}</div>}</CardContent></Card>
        </> : null}
      </> : null}
    </div>
  )
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
