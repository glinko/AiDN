import { useState } from 'react'
import {
  Activity,
  ArrowUpRight,
  Box,
  Boxes,
  BriefcaseBusiness,
  CheckCircle2,
  ChevronRight,
  CircleDot,
  Cpu,
  Database,
  ExternalLink,
  Gauge,
  Layers3,
  Menu,
  Network,
  PanelsTopLeft,
  RadioTower,
  RefreshCw,
  ServerCog,
  Settings,
  ShieldCheck,
  Sparkles,
  WalletCards,
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
import { useOperatorDashboardStore, type DashboardScreen } from '@/stores/operator-dashboard'
import type { Bundle, Endpoint, ReadinessStep } from '@/lib/types'

type NavigationItem = {
  id: DashboardScreen | 'legacy'
  label: string
  icon: LucideIcon
  advanced?: boolean
}

const navigationItems: NavigationItem[] = [
  { id: 'overview', label: 'Overview', icon: PanelsTopLeft },
  { id: 'legacy', label: 'Agents', icon: Activity },
  { id: 'bundles', label: 'Bundles', icon: Boxes },
  { id: 'legacy', label: 'Market', icon: BriefcaseBusiness },
  { id: 'legacy', label: 'Catalog', icon: Box },
  { id: 'endpoints', label: 'Endpoints', icon: RadioTower, advanced: true },
  { id: 'legacy', label: 'Wallet', icon: WalletCards },
  { id: 'legacy', label: 'Settings', icon: Settings },
]

const advancedItems: NavigationItem[] = [
  { id: 'legacy', label: 'Provider Plugins', icon: ServerCog, advanced: true },
  { id: 'legacy', label: 'Models', icon: Database, advanced: true },
  { id: 'legacy', label: 'Validation', icon: ShieldCheck, advanced: true },
  { id: 'legacy', label: 'Network', icon: Network, advanced: true },
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

  function refreshAll() {
    void Promise.all([
      data.home.refetch(),
      data.readiness.refetch(),
      data.fleet.refetch(),
      data.bundles.refetch(),
      data.endpoints.refetch(),
    ])
  }

  function navigate(screen: DashboardScreen | 'legacy') {
    if (screen === 'legacy') {
      window.location.assign('/operators/dashboard')
      return
    }
    setActiveScreen(screen)
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
}

function TopBar({
  nodeName,
  advanced,
  isRefreshing,
  refreshError,
  onRefresh,
  onToggleAdvanced,
  onOpenNavigation,
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
        <a href="/operators/dashboard/react" className="flex shrink-0 items-center gap-2.5 font-semibold tracking-[-0.04em] text-white">
          <span className="grid size-8 place-items-center rounded-[10px] bg-gradient-to-br from-cyan-300 via-cyan-400 to-blue-500 shadow-[0_0_24px_rgba(43,215,197,0.18)]">
            <Sparkles className="size-4 text-[#04101c]" strokeWidth={2.8} />
          </span>
          <span className="hidden text-lg sm:inline">AiDN</span>
        </a>
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
          <span className="hidden shrink-0 items-center gap-2 border border-dashed border-border/70 px-3 text-xs text-muted-foreground md:flex">
            <Network className="size-3.5" />
            Remote discovery
          </span>
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
  onNavigate: (screen: DashboardScreen | 'legacy') => void
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
          const label = item.id === 'legacy' ? `${item.label} (legacy workspace)` : item.label
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
                {item.id === 'legacy' ? <ArrowUpRight className="ml-auto size-3 opacity-40" /> : null}
              </TooltipTrigger>
              <TooltipContent side="right">{label}</TooltipContent>
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
  const targetScreen = action.screen
  if (action.kind === 'screen' && (targetScreen === 'bundles' || targetScreen === 'endpoints')) {
    return <Button size="sm" className="mt-3 bg-cyan-300 text-[#06121d] hover:bg-cyan-200 sm:mt-0" onClick={() => onNavigate(targetScreen)}>{action.label}<ChevronRight /></Button>
  }
  if (action.kind === 'refresh') {
    return <Button size="sm" variant="outline" className="mt-3 border-cyan-300/25 bg-transparent text-cyan-100 hover:bg-cyan-300/10 sm:mt-0" onClick={onRefresh}><RefreshCw />{action.label}</Button>
  }
  return <Button size="sm" variant="outline" className="mt-3 border-cyan-300/25 bg-transparent text-cyan-100 hover:bg-cyan-300/10 sm:mt-0" onClick={() => onNavigate('legacy')}><ExternalLink />{action.label}</Button>
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
        {!isLoading && !error && bundles.length === 0 ? <EmptyState title="No Bundle deployments are registered" detail="Start in Catalog to install a Provider, then create an immutable Bundle revision." actionLabel="Open legacy Catalog" /> : null}
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

function EmptyState({ title, detail, actionLabel, onAction }: { title: string; detail: string; actionLabel: string; onAction?: () => void }) {
  return <div className="px-5 py-12 text-center"><Boxes className="mx-auto size-6 text-slate-600" /><p className="mt-3 font-medium text-slate-200">{title}</p><p className="mx-auto mt-1 max-w-md text-sm leading-6 text-muted-foreground">{detail}</p><Button variant="outline" size="sm" className="mt-4 border-border bg-[#091725]" onClick={onAction ?? (() => window.location.assign('/operators/dashboard'))}>{actionLabel}<ExternalLink /></Button></div>
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
