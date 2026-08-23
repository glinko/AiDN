import { useEffect, useMemo, useState } from 'react'
import {
  Activity,
  ArrowUpRight,
  BellRing,
  Boxes,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleDot,
  Database,
  Gauge,
  GitBranch,
  KeyRound,
  LockKeyhole,
  Network,
  RadioTower,
  RefreshCw,
  ServerCog,
  Settings2,
  ShieldCheck,
  Sparkles,
  WalletCards,
  XCircle,
  Zap,
  type LucideIcon,
} from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import type { AssistedInstallationAction, InstallationPlan, JourneyGraph, JourneyNode, ResidentAgentStatus } from '@/lib/types'
import { dashboardScreens, type DashboardScreen } from '@/stores/operator-dashboard'
import { cn } from '@/lib/utils'

type JourneyPageProps = {
  graph: JourneyGraph | undefined
  residentAgent: ResidentAgentStatus | undefined
  installationPlan: InstallationPlan | undefined
  isLoading: boolean
  error: Error | null
  onRefresh: () => void
  onNavigate: (screen: DashboardScreen) => void
  onApplyInstallationPlan: (planHash: string, action?: AssistedInstallationAction) => Promise<void>
}

type JourneyView = 'journey' | 'list'

const iconByNode: Record<string, LucideIcon> = {
  hypervisor: Boxes,
  wallet: WalletCards,
  provider: ServerCog,
  model: Database,
  bundle: Boxes,
  endpoint: RadioTower,
  validation: ShieldCheck,
  discovery: Network,
  serve_requests: Zap,
  earnings: Sparkles,
  resources: Gauge,
  policies: Settings2,
  security: KeyRound,
  monitoring: BellRing,
  plugins: GitBranch,
  backups: ShieldCheck,
  analytics: Activity,
}

const stateLabel: Record<JourneyNode['state'], string> = {
  ready: 'Ready',
  in_progress: 'In progress',
  not_started: 'Not started',
  blocked: 'Blocked',
  warning: 'Needs attention',
  error: 'Error',
}

const stateStyle: Record<JourneyNode['state'], string> = {
  ready: 'border-emerald-700/35 bg-emerald-50 text-emerald-800',
  in_progress: 'border-sky-700/30 bg-sky-50 text-sky-800',
  not_started: 'border-slate-300 bg-slate-50 text-slate-600',
  blocked: 'border-amber-700/25 bg-amber-50 text-amber-900',
  warning: 'border-amber-700/35 bg-amber-50 text-amber-900',
  error: 'border-rose-700/30 bg-rose-50 text-rose-800',
}

const nodeAccent: Record<JourneyNode['state'], string> = {
  ready: 'border-emerald-700/30 bg-emerald-50 text-emerald-800',
  in_progress: 'border-sky-700/30 bg-sky-50 text-sky-800',
  not_started: 'border-slate-300 bg-slate-50 text-slate-500',
  blocked: 'border-amber-700/25 bg-amber-50 text-amber-900',
  warning: 'border-amber-700/35 bg-amber-50 text-amber-900',
  error: 'border-rose-700/30 bg-rose-50 text-rose-800',
}

const desktopRows = [
  ['wallet', 'provider', 'model', 'bundle'],
  ['endpoint', 'validation', 'discovery', 'serve_requests'],
  ['earnings', 'resources', 'policies', 'security'],
  ['monitoring', 'plugins', 'backups', 'analytics'],
]

const mobileGroups = [
  { id: 'identity', label: 'Identity', nodes: ['hypervisor', 'wallet'] },
  { id: 'compute', label: 'Compute', nodes: ['provider', 'model', 'bundle', 'endpoint'] },
  { id: 'network', label: 'Network', nodes: ['validation', 'discovery', 'serve_requests', 'earnings'] },
  { id: 'operations', label: 'Operations', nodes: ['resources', 'policies', 'security', 'monitoring'] },
  { id: 'extensions', label: 'Extensions', nodes: ['plugins', 'backups', 'analytics'] },
]

function routeFor(node: JourneyNode | undefined): DashboardScreen | null {
  const value = node?.action?.screen ?? node?.action?.route
  return value && dashboardScreens.includes(value as DashboardScreen) ? value as DashboardScreen : null
}

function NodeStateIcon({ state }: { state: JourneyNode['state'] }) {
  if (state === 'ready') return <CheckCircle2 className="size-3.5" aria-hidden="true" />
  if (state === 'blocked') return <LockKeyhole className="size-3.5" aria-hidden="true" />
  if (state === 'error') return <XCircle className="size-3.5" aria-hidden="true" />
  if (state === 'in_progress') return <Activity className="size-3.5" aria-hidden="true" />
  return <CircleDot className="size-3.5" aria-hidden="true" />
}

function JourneyStatus({ state }: { state: JourneyNode['state'] }) {
  return (
    <span className={cn('inline-flex min-h-7 items-center gap-1.5 rounded-full border px-2.5 text-[11px] font-semibold', stateStyle[state])}>
      <NodeStateIcon state={state} />
      {stateLabel[state]}
    </span>
  )
}

function JourneyNodeCard({ node, onSelect, onNavigate }: { node: JourneyNode; onSelect: (node: JourneyNode) => void; onNavigate: (screen: DashboardScreen) => void }) {
  const Icon = iconByNode[node.id] ?? CircleDot
  const route = routeFor(node)
  return (
    <article
      className={cn('group relative flex min-h-[194px] flex-col rounded-2xl border bg-white/90 p-4 text-left transition-[border-color,box-shadow,transform] duration-200 hover:-translate-y-0.5 hover:border-primary/60 hover:shadow-[0_14px_30px_rgba(32,70,88,0.12)]', node.state === 'ready' ? 'border-emerald-700/25' : 'border-border')}
      aria-label={`${node.title}: ${stateLabel[node.state]}`}
    >
      <button
        type="button"
        className="flex min-h-0 flex-1 flex-col text-left outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary"
        onClick={() => onSelect(node)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault()
            onSelect(node)
          }
        }}
      >
        <div className="flex items-start justify-between gap-3">
          <span className={cn('grid size-10 place-items-center rounded-xl border', nodeAccent[node.state])}>
            <Icon className="size-5" aria-hidden="true" />
          </span>
          <span className="font-mono text-[10px] font-medium text-slate-500">{node.required ? 'REQUIRED' : 'OPTIONAL'}</span>
        </div>
        <div className="mt-4">
          <h3 className="text-[15px] font-bold tracking-[-0.02em] text-foreground">{node.title}</h3>
          <p className="mt-1.5 line-clamp-2 text-xs leading-5 text-muted-foreground">{node.description}</p>
        </div>
        <div className="mt-auto pt-4"><JourneyStatus state={node.state} /></div>
      </button>
      <div className="mt-3 flex items-center justify-between gap-2 border-t border-border/80 pt-3">
        <button type="button" className="min-h-11 text-left text-[11px] font-medium text-muted-foreground underline-offset-4 hover:text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary" onClick={() => onSelect(node)}>
          {node.dependencies.length ? `${node.dependencies.length} prerequisite${node.dependencies.length === 1 ? '' : 's'}` : 'Inspect status'}
        </button>
        {route ? <Button variant="ghost" size="sm" className="min-h-11 gap-1 px-2 text-primary hover:bg-primary/8" onClick={() => onNavigate(route)}>{node.action?.label ?? 'Open'}<ArrowUpRight className="size-3.5" /></Button> : null}
      </div>
    </article>
  )
}

function JourneyGraphDesktop({ graph, onSelect, onNavigate }: { graph: JourneyGraph; onSelect: (node: JourneyNode) => void; onNavigate: (screen: DashboardScreen) => void }) {
  const byId = useMemo(() => new Map(graph.nodes.map((node) => [node.id, node])), [graph.nodes])
  const renderNode = (id: string) => {
    const node = byId.get(id)
    return node ? <JourneyNodeCard key={id} node={node} onSelect={onSelect} onNavigate={onNavigate} /> : null
  }
  return (
    <section className="relative overflow-hidden rounded-2xl border border-border bg-white/60 p-4 sm:p-6" aria-label="Node journey graph">
      <div className="pointer-events-none absolute inset-0 opacity-60" aria-hidden="true">
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="h-full w-full text-primary/35">
          <path d="M50 11V19M13 19H87M13 19V25M37 19V25M63 19V25M87 19V25M13 49V54M37 49V54M63 49V54M87 49V54M13 78V84M50 78V84M87 78V84" fill="none" stroke="currentColor" strokeDasharray="1.4 1.5" strokeWidth="0.35" vectorEffect="non-scaling-stroke" />
          <circle cx="50" cy="19" r="0.9" fill="currentColor" />
        </svg>
      </div>
      <div className="relative z-10 mx-auto max-w-[920px]">
        <div className="mx-auto max-w-[300px] rounded-2xl border border-primary/35 bg-white px-5 py-4 text-center shadow-[0_12px_32px_rgba(10,127,131,0.10)]">
          <div className="mx-auto grid size-11 place-items-center rounded-xl border border-primary/25 bg-primary/8 text-primary"><Boxes className="size-5" /></div>
          <p className="mt-3 font-mono text-[10px] font-medium uppercase tracking-[0.16em] text-muted-foreground">Hypervisor</p>
          <p className="mt-1 text-lg font-bold tracking-[-0.03em] text-foreground">{graph.hypervisor.node_id || 'Your AiDN Node'}</p>
          <p className="mt-1 text-xs text-muted-foreground">{graph.hypervisor.network_ready ? 'Node is online and network-aware' : 'Node is online; network evidence pending'}</p>
        </div>
        <div className="mt-8 space-y-7">
          {desktopRows.map((row, rowIndex) => (
            <div key={rowIndex} className={cn('grid gap-3', row.length === 3 ? 'grid-cols-2 lg:grid-cols-3' : 'grid-cols-2 lg:grid-cols-4')}>
              {row.map(renderNode)}
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

function JourneyGroup({ label, nodes, byId, open, onToggle, onSelect, onNavigate }: { label: string; nodes: string[]; byId: Map<string, JourneyNode>; open: boolean; onToggle: () => void; onSelect: (node: JourneyNode) => void; onNavigate: (screen: DashboardScreen) => void }) {
  const available = nodes.map((id) => byId.get(id)).filter((node): node is JourneyNode => Boolean(node))
  const ready = available.filter((node) => node.state === 'ready').length
  return (
    <section className="overflow-hidden rounded-2xl border border-border bg-white/75">
      <button type="button" className="flex min-h-14 w-full items-center justify-between gap-3 px-4 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary" onClick={onToggle} aria-expanded={open}>
        <span><span className="block text-sm font-bold text-foreground">{label}</span><span className="mt-0.5 block text-xs text-muted-foreground">{ready} / {available.length} ready</span></span>
        <ChevronDown className={cn('size-4 text-muted-foreground transition-transform duration-200', open && 'rotate-180')} />
      </button>
      {open ? <div className="border-t border-border/80 p-3"><div className="space-y-3">{available.map((node) => <JourneyNodeCard key={node.id} node={node} onSelect={onSelect} onNavigate={onNavigate} />)}</div></div> : null}
    </section>
  )
}

function JourneyList({ graph, onSelect, onNavigate }: { graph: JourneyGraph; onSelect: (node: JourneyNode) => void; onNavigate: (screen: DashboardScreen) => void }) {
  return <div className="space-y-2" aria-label="Node journey list">{graph.nodes.map((node) => <div key={node.id} className="flex items-center gap-3 rounded-xl border border-border bg-white/75 p-3"><span className={cn('grid size-9 shrink-0 place-items-center rounded-lg border', nodeAccent[node.state])}><NodeStateIcon state={node.state} /></span><button type="button" className="min-h-11 min-w-0 flex-1 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary" onClick={() => onSelect(node)}><span className="block truncate text-sm font-semibold text-foreground">{node.title}</span><span className="block truncate text-xs text-muted-foreground">{node.reason}</span></button><JourneyStatus state={node.state} />{routeFor(node) ? <Button variant="ghost" size="icon" className="size-11 shrink-0 text-primary" aria-label={node.action?.label ?? `Open ${node.title}`} onClick={() => { const route = routeFor(node); if (route) onNavigate(route) }}><ChevronRight className="size-4" /></Button> : null}</div>)}</div>
}

function AssistedSetupCard({ plan, onNavigate, onApply }: { plan: InstallationPlan | undefined; onNavigate: (screen: DashboardScreen) => void; onApply: (planHash: string, action?: AssistedInstallationAction) => Promise<void> }) {
  const [applying, setApplying] = useState(false)
  if (!plan?.available || !plan.ai_assisted || plan.status === 'MANUAL') return null
  const status = plan.status.toLowerCase()
  const modelId = plan.model.id && plan.model.id !== 'skip' ? plan.model.id : 'No model selected'
  const provider = plan.provider && plan.provider !== 'skip' ? plan.provider : 'No provider selected'
  const reviewable = Boolean(plan.plan_hash) && status === 'ready_for_review' && plan.integrity === 'verified'
  const needsRegeneration = ['legacy_review_required', 'stale'].includes(status) || plan.integrity !== 'verified'
  const nextAction = plan.workflow?.next_action
  const workflowAction: Record<string, AssistedInstallationAction | undefined> = {
    prepare_assisted_installation_review: 'prepare_review',
    request_model_install: 'request_model_install',
    process_model_install: 'process_model_install',
    create_bundle: 'create_bundle',
    create_private_endpoint: 'create_private_endpoint',
    forecast_private_endpoint: 'forecast_private_endpoint',
    start_private_endpoint: 'start_private_endpoint',
  }
  const action = workflowAction[nextAction?.id ?? ''] ?? (reviewable ? 'prepare_review' : undefined)
  const destination = nextAction?.id === 'approve_provider_installation' || status === 'waiting_for_provider'
    ? 'providers'
    : nextAction?.id === 'wait_model_install' || nextAction?.id === 'inspect_model_install' || status === 'model_install_queued'
      ? 'models'
      : null
  const statusLabel = status === 'ready_for_review' || status === 'legacy_review_required'
    ? 'Review required'
    : status === 'model_install_queued'
      ? 'Model queued'
      : status === 'waiting_for_provider'
        ? 'Provider required'
        : plan.status.replaceAll('_', ' ')
  return (
    <section className="rounded-2xl border border-primary/25 bg-primary/[0.045] p-4" aria-label="Assisted installation plan">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="font-mono text-[10px] font-medium uppercase tracking-[0.14em] text-primary">Installer handoff</p>
          <h2 className="mt-1 text-sm font-bold text-foreground">Assisted setup</h2>
        </div>
        <span className="rounded-full border border-primary/20 bg-white px-2 py-1 text-[10px] font-bold uppercase tracking-[0.1em] text-primary">{statusLabel}</span>
      </div>
      <p className="mt-2 text-xs leading-5 text-muted-foreground">The terminal wizard saved a reviewable plan. It never installs or publishes without this operator boundary.</p>
      <dl className="mt-3 space-y-2 text-xs">
        <div className="flex justify-between gap-3"><dt className="text-muted-foreground">Provider</dt><dd className="font-mono text-foreground">{provider}</dd></div>
        <div className="flex justify-between gap-3"><dt className="text-muted-foreground">Model</dt><dd className="max-w-[12rem] truncate font-mono text-foreground" title={modelId}>{modelId}</dd></div>
        <div className="flex justify-between gap-3"><dt className="text-muted-foreground">Endpoint</dt><dd className="font-mono text-foreground">{plan.endpoint.requested_action}</dd></div>
      </dl>
      {nextAction?.reason || plan.reason ? <p className="mt-3 rounded-xl border border-border bg-white/75 p-3 text-xs leading-5 text-muted-foreground">{nextAction?.reason ?? plan.reason}</p> : null}
      {needsRegeneration ? <p className="mt-3 text-xs leading-5 text-amber-800">Run the installer again to create a fresh, hash-bound plan before continuing.</p> : null}
      {action && plan.plan_hash && plan.integrity === 'verified' ? <Button
        className="mt-4 min-h-11 w-full justify-between"
        disabled={applying}
        onClick={() => {
          if (!plan.plan_hash) return
          setApplying(true)
          void onApply(plan.plan_hash, action).finally(() => setApplying(false))
        }}
      >{applying ? 'Applying…' : action === 'prepare_review' ? 'Review and continue' : nextAction?.label ?? 'Continue setup'}<ArrowUpRight className="size-4" /></Button> : destination ? <Button variant="outline" className="mt-4 min-h-11 w-full justify-between" onClick={() => onNavigate(destination)}>{destination === 'providers' ? 'Open providers' : 'Open models'}<ArrowUpRight className="size-4" /></Button> : null}
    </section>
  )
}

function JourneyRail({ graph, residentAgent, installationPlan, onNavigate, onApplyInstallationPlan }: { graph: JourneyGraph; residentAgent: ResidentAgentStatus | undefined; installationPlan: InstallationPlan | undefined; onNavigate: (screen: DashboardScreen) => void; onApplyInstallationPlan: (planHash: string, action?: AssistedInstallationAction) => Promise<void> }) {
  const next = graph.recommended_action
  const route = next.screen && dashboardScreens.includes(next.screen as DashboardScreen) ? next.screen as DashboardScreen : null
  const nodeId = graph.hypervisor.node_id || 'local-node'
  return (
    <aside className="space-y-3 xl:sticky xl:top-4 xl:self-start">
      <section className="rounded-2xl border border-border bg-white/80 p-4"><div className="flex items-center justify-between gap-3"><h2 className="text-sm font-bold text-foreground">Node status</h2><span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-700/25 bg-emerald-50 px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.12em] text-emerald-800"><span className="size-1.5 rounded-full bg-emerald-700" />{graph.hypervisor.state === 'ready' ? 'Online' : 'Starting'}</span></div><dl className="mt-4 space-y-2 text-xs"><div className="flex justify-between gap-3"><dt className="text-muted-foreground">Node ID</dt><dd className="max-w-[11rem] truncate font-mono text-foreground">{nodeId}</dd></div><div className="flex justify-between gap-3"><dt className="text-muted-foreground">Role</dt><dd className="font-medium capitalize text-foreground">{graph.role}</dd></div><div className="flex justify-between gap-3"><dt className="text-muted-foreground">Network</dt><dd className="font-medium text-foreground">{graph.hypervisor.network_ready ? 'Ready' : 'Evidence pending'}</dd></div></dl><Button variant="outline" size="sm" className="mt-4 min-h-11 w-full justify-between" onClick={() => onNavigate('settings')}>Node settings<ChevronRight className="size-3.5" /></Button></section>
      <section className="rounded-2xl border border-primary/20 bg-primary/[0.045] p-4" aria-label="Resident Node Steward status">
        <div className="flex items-start justify-between gap-3">
          <div><p className="font-mono text-[10px] font-medium uppercase tracking-[0.14em] text-primary">RFC-0075</p><h2 className="mt-1 text-sm font-bold text-foreground">Resident Steward</h2></div>
          <span className={cn('rounded-full border px-2 py-1 text-[10px] font-bold uppercase tracking-[0.1em]', residentAgent?.enabled ? 'border-emerald-700/25 bg-emerald-50 text-emerald-800' : 'border-slate-300 bg-slate-50 text-slate-600')}>{residentAgent?.enabled ? residentAgent.state : 'Disabled'}</span>
        </div>
        <p className="mt-2 text-xs leading-5 text-muted-foreground">CPU-first local control agent. It observes the event stream but cannot execute tools or reserve VRAM in this slice.</p>
        <dl className="mt-3 space-y-2 text-xs"><div className="flex justify-between gap-3"><dt className="text-muted-foreground">Profile</dt><dd className="font-mono font-medium text-foreground">{residentAgent?.execution.profile ?? 'CPU_RESIDENT'}</dd></div><div className="flex justify-between gap-3"><dt className="text-muted-foreground">Model</dt><dd className="max-w-[11rem] truncate font-mono text-foreground">{residentAgent?.model.llama_cpp_reference ?? 'Qwen2.5-0.5B:Q4_K_M'}</dd></div><div className="flex justify-between gap-3"><dt className="text-muted-foreground">Events seen</dt><dd className="font-mono text-foreground">{residentAgent?.event_ingestion.events_seen ?? 0}</dd></div></dl>
        <p className="mt-3 text-[11px] leading-4 text-muted-foreground">{residentAgent?.health === 'NOT_RUNNING' ? 'Inference adapter is not started; no model weights are downloaded automatically.' : residentAgent?.last_error ?? 'Status is reported by the Hypervisor.'}</p>
      </section>
      <AssistedSetupCard plan={installationPlan} onNavigate={onNavigate} onApply={onApplyInstallationPlan} />
      <section className="rounded-2xl border border-border bg-white/80 p-4"><div className="flex items-end justify-between gap-3"><div><h2 className="text-sm font-bold text-foreground">Progress overview</h2><p className="mt-1 text-xs text-muted-foreground">Required stages</p></div><strong className="text-3xl font-bold tracking-[-0.06em] text-primary">{graph.progress.percent}%</strong></div><div className="mt-4 h-2 overflow-hidden rounded-full bg-secondary"><div className="h-full rounded-full bg-primary transition-[width] duration-500" style={{ width: `${graph.progress.percent}%` }} /></div><div className="mt-4 grid grid-cols-2 gap-2 text-xs"><span className="text-muted-foreground"><b className="text-foreground">{graph.progress.required_ready}</b> ready</span><span className="text-right text-muted-foreground"><b className="text-foreground">{graph.progress.required_total - graph.progress.required_ready}</b> remaining</span></div></section>
      <section className="rounded-2xl border border-primary/25 bg-primary/[0.06] p-4"><p className="font-mono text-[10px] font-medium uppercase tracking-[0.14em] text-primary">Next recommended</p><h2 className="mt-2 text-base font-bold text-foreground">{next.title}</h2><p className="mt-1 text-xs leading-5 text-muted-foreground">{next.description}</p>{route ? <Button className="mt-4 min-h-11 w-full justify-between" onClick={() => onNavigate(route)}>{next.label}<ArrowUpRight className="size-4" /></Button> : null}</section>
      <section className="rounded-2xl border border-border bg-white/80 p-4"><h2 className="text-sm font-bold text-foreground">Quick actions</h2><div className="mt-2 divide-y divide-border/70">{([{ label: 'Dashboard', screen: 'overview' as DashboardScreen, icon: Boxes }, { label: 'Resource broker', screen: 'settings' as DashboardScreen, icon: Gauge }, { label: 'Event log', screen: 'hooks' as DashboardScreen, icon: BellRing }, { label: 'Documentation', screen: 'catalog' as DashboardScreen, icon: Sparkles }]).map(({ label, screen, icon: Icon }) => <button type="button" key={label} className="flex min-h-12 w-full items-center justify-between gap-3 text-left text-xs font-semibold text-foreground hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary" onClick={() => onNavigate(screen)}><span className="flex items-center gap-2"><Icon className="size-4 text-primary" />{label}</span><ChevronRight className="size-3.5 text-muted-foreground" /></button>)}</div></section>
      <section className="rounded-2xl border border-border bg-white/65 p-4"><h2 className="text-sm font-bold text-foreground">Legend</h2><div className="mt-3 grid grid-cols-2 gap-2 text-[11px] text-muted-foreground"><span className="flex items-center gap-2"><span className="size-2 rounded-full bg-emerald-700" />Ready</span><span className="flex items-center gap-2"><span className="size-2 rounded-full bg-sky-700" />In progress</span><span className="flex items-center gap-2"><span className="size-2 rounded-full bg-slate-400" />Not started</span><span className="flex items-center gap-2"><span className="size-2 rounded-full bg-amber-700" />Blocked / warning</span></div></section>
    </aside>
  )
}

function JourneyNextMobile({ graph, onNavigate }: { graph: JourneyGraph; onNavigate: (screen: DashboardScreen) => void }) {
  const next = graph.recommended_action
  const route = next.screen && dashboardScreens.includes(next.screen as DashboardScreen) ? next.screen as DashboardScreen : null
  return (
    <section className="rounded-2xl border border-primary/25 bg-primary/[0.06] p-4 md:hidden" aria-live="polite">
      <div className="flex items-start gap-3">
        <span className="grid size-9 shrink-0 place-items-center rounded-xl border border-primary/20 bg-white text-primary"><Zap className="size-4" /></span>
        <div className="min-w-0 flex-1"><p className="font-mono text-[10px] font-medium uppercase tracking-[0.14em] text-primary">Next recommended</p><h2 className="mt-1 text-base font-bold text-foreground">{next.title}</h2><p className="mt-1 text-xs leading-5 text-muted-foreground">{next.description}</p></div>
      </div>
      {route ? <Button className="mt-4 min-h-11 w-full justify-between" onClick={() => onNavigate(route)}>{next.label}<ArrowUpRight className="size-4" /></Button> : null}
    </section>
  )
}

function JourneyDetailSheet({ node, open, onOpenChange, onNavigate }: { node: JourneyNode | undefined; open: boolean; onOpenChange: (open: boolean) => void; onNavigate: (screen: DashboardScreen) => void }) {
  const [mobile, setMobile] = useState(false)
  useEffect(() => {
    const update = () => setMobile(window.innerWidth < 768)
    update()
    window.addEventListener('resize', update)
    return () => window.removeEventListener('resize', update)
  }, [])
  const route = routeFor(node)
  return <Sheet open={open} onOpenChange={onOpenChange}><SheetContent side={mobile ? 'bottom' : 'right'} className={cn('border-border bg-popover p-0 text-popover-foreground', mobile ? 'max-h-[82dvh] rounded-t-2xl' : 'w-[min(25rem,calc(100vw-1rem))]')}><SheetHeader className="border-b border-border/80 p-5"><div className="flex items-center gap-3"><span className={cn('grid size-10 place-items-center rounded-xl border', node ? nodeAccent[node.state] : 'border-border bg-secondary text-muted-foreground')}>{node ? <NodeStateIcon state={node.state} /> : <CircleDot className="size-5" />}</span><div className="min-w-0"><SheetTitle className="truncate text-lg">{node?.title ?? 'Journey detail'}</SheetTitle><SheetDescription>{node ? stateLabel[node.state] : 'Select a stage to inspect it.'}</SheetDescription></div></div></SheetHeader>{node ? <div className="space-y-5 overflow-y-auto p-5"><p className="text-sm leading-6 text-muted-foreground">{node.description}</p><div className="rounded-xl border border-border bg-secondary/50 p-4"><p className="font-mono text-[10px] font-medium uppercase tracking-[0.13em] text-muted-foreground">Current evidence</p><p className="mt-2 text-sm leading-6 text-foreground">{node.reason}</p></div>{node.dependencies.length ? <div><p className="font-mono text-[10px] font-medium uppercase tracking-[0.13em] text-muted-foreground">Requires</p><div className="mt-2 flex flex-wrap gap-2">{node.dependencies.map((dependency) => <span key={dependency} className="rounded-full border border-border bg-white px-2.5 py-1 text-xs text-muted-foreground">{dependency.replaceAll('_', ' ')}</span>)}</div></div> : null}{node.details && Object.keys(node.details).length ? <div><p className="font-mono text-[10px] font-medium uppercase tracking-[0.13em] text-muted-foreground">Details</p><dl className="mt-2 divide-y divide-border/70 rounded-xl border border-border bg-white">{Object.entries(node.details).slice(0, 6).map(([key, value]) => <div key={key} className="flex justify-between gap-4 px-3 py-2.5 text-xs"><dt className="text-muted-foreground">{key.replaceAll('_', ' ')}</dt><dd className="max-w-[12rem] truncate font-mono text-foreground">{typeof value === 'object' ? JSON.stringify(value) : String(value ?? '—')}</dd></div>)}</dl></div> : null}{route ? <Button className="min-h-11 w-full justify-between" onClick={() => { onOpenChange(false); onNavigate(route) }}>{node.action?.label ?? 'Continue'}<ArrowUpRight className="size-4" /></Button> : null}</div> : null}</SheetContent></Sheet>
}

export function JourneyPage({ graph, residentAgent, installationPlan, isLoading, error, onRefresh, onNavigate, onApplyInstallationPlan }: JourneyPageProps) {
  const [view, setView] = useState<JourneyView>('journey')
  const [selected, setSelected] = useState<JourneyNode>()
  const [detailOpen, setDetailOpen] = useState(false)
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>({ identity: true, compute: true, network: true })
  const byId = useMemo(() => new Map((graph?.nodes ?? []).map((node) => [node.id, node])), [graph?.nodes])
  const selectNode = (node: JourneyNode) => { setSelected(node); setDetailOpen(true) }
  if (isLoading && !graph) return <div className="space-y-4"><Skeleton className="h-24 w-full rounded-2xl" /><div className="grid gap-3 lg:grid-cols-4">{Array.from({ length: 8 }, (_, index) => <Skeleton key={index} className="h-48 rounded-2xl" />)}</div></div>
  if (error && !graph) return <section className="rounded-2xl border border-rose-700/25 bg-rose-50 p-5"><div className="flex items-start gap-3"><XCircle className="mt-0.5 size-5 shrink-0 text-rose-700" /><div><h1 className="text-base font-bold text-rose-900">Node journey is unavailable</h1><p className="mt-1 text-sm text-rose-800/80">The Hypervisor did not return the canonical graph. No setup action was attempted.</p><Button variant="outline" className="mt-4 min-h-11 border-rose-700/25 bg-transparent text-rose-900" onClick={onRefresh}><RefreshCw className="size-4" />Retry</Button></div></div></section>
  if (!graph) return null
  return (
    <div className="space-y-5">
      <header className="flex flex-col justify-between gap-4 border-b border-border/80 pb-5 sm:flex-row sm:items-end"><div><p className="font-mono text-[10px] font-medium uppercase tracking-[0.16em] text-primary">Operational map</p><h1 className="mt-2 text-3xl font-bold tracking-[-0.05em] text-foreground sm:text-4xl">Your node journey</h1><p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">Follow the path from an initialized Hypervisor to a useful, discoverable AI service. Every stage is computed from live node state.</p></div><div className="flex flex-wrap items-center gap-2"><Button variant="outline" className="min-h-11" onClick={onRefresh}><RefreshCw className={cn('size-4', isLoading && 'animate-spin')} />Refresh</Button><div className="flex min-h-11 rounded-lg border border-border bg-white p-1" role="group" aria-label="Journey view"><button type="button" className={cn('min-h-9 rounded-md px-3 text-xs font-semibold', view === 'journey' ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground')} onClick={() => setView('journey')}>Journey</button><button type="button" className={cn('min-h-9 rounded-md px-3 text-xs font-semibold', view === 'list' ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground')} onClick={() => setView('list')}>List</button></div></div></header>
      <JourneyNextMobile graph={graph} onNavigate={onNavigate} />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_300px]"> <div className="min-w-0">{view === 'list' ? <JourneyList graph={graph} onSelect={selectNode} onNavigate={onNavigate} /> : <><div className="hidden md:block"><JourneyGraphDesktop graph={graph} onSelect={selectNode} onNavigate={onNavigate} /></div><div className="space-y-3 md:hidden">{mobileGroups.map((group) => <JourneyGroup key={group.id} label={group.label} nodes={group.nodes} byId={byId} open={Boolean(openGroups[group.id])} onToggle={() => setOpenGroups((current) => ({ ...current, [group.id]: !current[group.id] }))} onSelect={selectNode} onNavigate={onNavigate} />)}</div></>}</div><JourneyRail graph={graph} residentAgent={residentAgent} installationPlan={installationPlan} onNavigate={onNavigate} onApplyInstallationPlan={onApplyInstallationPlan} /></div>
      <JourneyDetailSheet node={selected} open={detailOpen} onOpenChange={setDetailOpen} onNavigate={onNavigate} />
    </div>
  )
}
