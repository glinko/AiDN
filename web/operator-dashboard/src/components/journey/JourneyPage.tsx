import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
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
import type { TestnetParticipationDashboard } from '@/lib/api'
import type { AssistedInstallationAction, InstallationPlan, JourneyGraph, JourneyNode, ResidentAgentStatus } from '@/lib/types'
import { dashboardScreens, type DashboardScreen } from '@/stores/operator-dashboard'
import { cn } from '@/lib/utils'

type JourneyPageProps = {
  graph: JourneyGraph | undefined
  residentAgent: ResidentAgentStatus | undefined
  installationPlan: InstallationPlan | undefined
  participation: TestnetParticipationDashboard | undefined
  isLoading: boolean
  error: Error | null
  onRefresh: () => void
  onNavigate: (screen: DashboardScreen) => void
  onApplyInstallationPlan: (planHash: string, action?: AssistedInstallationAction) => Promise<void>
  onStewardChat: (message: string) => Promise<Record<string, unknown> | undefined>
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

function text(value: unknown, fallback = '—'): string {
  return typeof value === 'string' && value.trim() ? value : fallback
}

function InstallationHandoffPanel({ plan, onStewardChat }: { plan: InstallationPlan | undefined; onStewardChat: (message: string) => Promise<Record<string, unknown> | undefined> }) {
  const [message, setMessage] = useState('')
  const [reply, setReply] = useState('')
  const [chatError, setChatError] = useState('')
  const [sending, setSending] = useState(false)
  if (!plan?.available || !plan.ai_assisted || !plan.completion_report) return null
  const report = plan.completion_report
  const node = record(report.node)
  const wallet = record(report.wallet)
  const installation = record(report.installation)
  const security = record(report.security)
  const handoff = plan.steward_handoff

  const submit = async (nextMessage?: string) => {
    const value = (nextMessage ?? message).trim()
    if (!value || sending) return
    setMessage(value)
    setSending(true)
    setChatError('')
    try {
      const response = record(await onStewardChat(value))
      const nested = record(response.result)
      setReply(text(response.output_text ?? response.content ?? response.response ?? nested.output_text ?? nested.content, 'The Steward returned no text. Refresh inference status and try again.'))
    } catch (cause) {
      setChatError(cause instanceof Error ? cause.message : 'The Resident Steward could not answer. Check that local inference is running.')
    } finally {
      setSending(false)
    }
  }

  return (
    <section className="overflow-hidden rounded-2xl border border-border bg-white" aria-labelledby="installation-report-title">
      <div className="grid xl:grid-cols-[minmax(0,1.05fr)_minmax(22rem,0.95fr)]">
        <div className="p-5 sm:p-6">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div><h2 id="installation-report-title" className="text-xl font-bold tracking-[-0.025em] text-foreground">Your operator handoff</h2><p className="mt-1 max-w-2xl text-sm leading-6 text-muted-foreground">Observed installation facts are collected here. Secret material stays in local protected storage and is never returned by this page.</p></div>
            <span className="rounded-full border border-emerald-700/25 bg-emerald-50 px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.1em] text-emerald-800">{text(installation.workflow_status, 'Recorded')}</span>
          </div>
          <dl className="mt-5 divide-y divide-border/75 border-y border-border/75 text-sm">
            <div className="grid gap-1 py-3 sm:grid-cols-[9rem_1fr]"><dt className="text-muted-foreground">Node</dt><dd className="break-all font-mono text-xs text-foreground">{text(node.node_id)} · {text(node.base_url, 'address unavailable')}</dd></div>
            <div className="grid gap-1 py-3 sm:grid-cols-[9rem_1fr]"><dt className="text-muted-foreground">Runtime</dt><dd className="break-all font-mono text-xs text-foreground">{text(installation.provider, 'not selected')} · {text(installation.model_id, 'model not selected')}</dd></div>
            <div className="grid gap-1 py-3 sm:grid-cols-[9rem_1fr]"><dt className="text-muted-foreground">Wallet</dt><dd className="break-all font-mono text-xs text-foreground">{text(wallet.wallet_id, 'not configured')}</dd></div>
            <div className="grid gap-1 py-3 sm:grid-cols-[9rem_1fr]"><dt className="text-muted-foreground">Public key</dt><dd className="break-all font-mono text-xs text-foreground">{text(wallet.public_key, 'not available')}</dd></div>
            <div className="grid gap-1 py-3 sm:grid-cols-[9rem_1fr]"><dt className="text-muted-foreground">Fingerprint</dt><dd className="font-mono text-xs text-foreground">{text(wallet.public_key_fingerprint, 'not available')}</dd></div>
          </dl>
          <div className="mt-4 flex items-start gap-3 rounded-xl bg-amber-50 p-3 text-amber-950"><ShieldCheck className="mt-0.5 size-4 shrink-0" /><p className="text-xs leading-5">{text(security.message, 'Private keys and recovery seeds are not exposed in the Dashboard.')}</p></div>
        </div>
        <div className="border-t border-border bg-primary/[0.035] p-5 sm:p-6 xl:border-l xl:border-t-0">
          <div className="flex items-start justify-between gap-3"><div><h2 className="text-xl font-bold tracking-[-0.025em] text-foreground">Continue with Resident Steward</h2><p className="mt-1 text-sm leading-6 text-muted-foreground">{handoff?.welcome ?? 'Ask about the observed node state and the next reviewed setup step.'}</p></div><span className={cn('rounded-full border px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.1em]', handoff?.ready ? 'border-emerald-700/25 bg-emerald-50 text-emerald-800' : 'border-amber-700/25 bg-amber-50 text-amber-900')}>{handoff?.ready ? 'Ready' : 'Not running'}</span></div>
          <div className="mt-4 flex flex-wrap gap-2">{handoff?.suggested_questions.map((question) => <button key={question} type="button" className="min-h-11 rounded-lg border border-border bg-white px-3 py-2 text-left text-xs font-medium text-foreground hover:border-primary/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary" onClick={() => void submit(question)} disabled={sending}>{question}</button>)}</div>
          {reply ? <div className="mt-4 rounded-xl border border-primary/20 bg-white p-4" aria-live="polite"><p className="whitespace-pre-wrap text-sm leading-6 text-foreground">{reply}</p></div> : null}
          {chatError ? <div className="mt-4 rounded-xl border border-rose-700/25 bg-rose-50 p-3 text-xs leading-5 text-rose-900" role="alert">{chatError}</div> : null}
          <form className="mt-4" onSubmit={(event) => { event.preventDefault(); void submit() }}>
            <label htmlFor="steward-message" className="text-xs font-semibold text-foreground">Message</label>
            <textarea id="steward-message" value={message} onChange={(event) => setMessage(event.target.value)} rows={3} maxLength={16_384} placeholder="What should I configure next?" className="mt-2 w-full resize-y rounded-xl border border-input bg-white px-3 py-2.5 text-sm text-foreground outline-none placeholder:text-muted-foreground focus:border-primary focus:ring-2 focus:ring-primary/20" />
            <div className="mt-2 flex items-center justify-between gap-3"><p className="text-[11px] text-muted-foreground">Prompt protocol {text(record(handoff?.prompt).version, '1.0')} · changes still require review</p><Button type="submit" disabled={!message.trim() || sending || !handoff?.ready}>{sending ? 'Thinking…' : 'Ask Steward'}<ArrowUpRight className="size-4" /></Button></div>
          </form>
        </div>
      </div>
    </section>
  )
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

type JourneyDesktopPlacement = {
  id: string
  colStart: number
  colSpan?: number
}

const desktopRows: JourneyDesktopPlacement[][] = [
  [{ id: 'hypervisor', colStart: 2, colSpan: 2 }],
  [{ id: 'wallet', colStart: 1 }, { id: 'provider', colStart: 3 }],
  [{ id: 'resources', colStart: 1 }, { id: 'model', colStart: 3 }, { id: 'plugins', colStart: 4 }],
  [{ id: 'security', colStart: 1 }, { id: 'bundle', colStart: 3 }, { id: 'policies', colStart: 4 }],
  [{ id: 'monitoring', colStart: 1 }, { id: 'endpoint', colStart: 3 }],
  [{ id: 'backups', colStart: 1 }, { id: 'validation', colStart: 2 }],
  [{ id: 'earnings', colStart: 2 }, { id: 'discovery', colStart: 3 }, { id: 'serve_requests', colStart: 4 }],
  [{ id: 'analytics', colStart: 4 }],
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

function JourneyNodeCard({ node, onSelect, onNavigate, nodeRef }: { node: JourneyNode; onSelect: (node: JourneyNode) => void; onNavigate: (screen: DashboardScreen) => void; nodeRef?: (element: HTMLElement | null) => void }) {
  const Icon = iconByNode[node.id] ?? CircleDot
  const route = routeFor(node)
  return (
    <article
      ref={nodeRef}
      className={cn('group relative flex h-full min-h-[212px] min-w-0 flex-col rounded-2xl border bg-white/90 p-4 text-left transition-[border-color,box-shadow,transform] duration-200 hover:-translate-y-0.5 hover:border-primary/60 hover:shadow-[0_14px_30px_rgba(32,70,88,0.12)]', node.state === 'ready' ? 'border-emerald-700/25' : 'border-border')}
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
      <div className="mt-3 grid min-w-0 gap-2 border-t border-border/80 pt-3">
        <button type="button" className="flex min-h-8 min-w-0 items-center justify-between gap-2 text-left text-[11px] font-medium text-muted-foreground underline-offset-4 hover:text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary" onClick={() => onSelect(node)}>
          <span className="min-w-0 truncate">{node.dependencies.length ? `${node.dependencies.length} prerequisite${node.dependencies.length === 1 ? '' : 's'}` : 'Inspect status'}</span>
          <ChevronRight className="size-3.5 shrink-0" aria-hidden="true" />
        </button>
        {route ? <Button variant="ghost" size="sm" className="min-h-10 w-full min-w-0 justify-between gap-2 px-2 text-primary hover:bg-primary/8" onClick={() => onNavigate(route)}><span className="min-w-0 truncate">{node.action?.label ?? 'Open'}</span><ArrowUpRight className="size-3.5 shrink-0" /></Button> : null}
      </div>
    </article>
  )
}

function JourneyGraphDesktop({ graph, onSelect, onNavigate }: { graph: JourneyGraph; onSelect: (node: JourneyNode) => void; onNavigate: (screen: DashboardScreen) => void }) {
  const byId = useMemo(() => new Map(graph.nodes.map((node) => [node.id, node])), [graph.nodes])
  const graphRef = useRef<HTMLDivElement>(null)
  const nodeRefs = useRef(new Map<string, HTMLElement>())
  const [edgeGeometry, setEdgeGeometry] = useState<Array<{ edge: JourneyGraph['edges'][number]; path: string; key: string; delay: string }>>([])
  const [edgeLayerSize, setEdgeLayerSize] = useState({ width: 0, height: 0 })

  useLayoutEffect(() => {
    const canvas = graphRef.current
    if (!canvas) return
    let frame = 0
    const measure = () => {
      const bounds = canvas.getBoundingClientRect()
      const nextGeometry = graph.edges.flatMap((edge, index) => {
        const from = nodeRefs.current.get(edge.from)?.getBoundingClientRect()
        const to = nodeRefs.current.get(edge.to)?.getBoundingClientRect()
        if (!from || !to || bounds.width <= 0 || bounds.height <= 0) return []
        const startX = from.left + from.width / 2 - bounds.left
        const startY = from.bottom - bounds.top
        const endX = to.left + to.width / 2 - bounds.left
        const endY = to.top - bounds.top
        const controlY = startY + Math.max(18, (endY - startY) * 0.48)
        return [{
          edge,
          key: `${edge.from}-${edge.to}-${index}`,
          delay: `${index * 0.18}s`,
          path: `M ${startX.toFixed(1)} ${startY.toFixed(1)} C ${startX.toFixed(1)} ${controlY.toFixed(1)}, ${endX.toFixed(1)} ${controlY.toFixed(1)}, ${endX.toFixed(1)} ${endY.toFixed(1)}`,
        }]
      })
      setEdgeLayerSize({ width: bounds.width, height: bounds.height })
      setEdgeGeometry(nextGeometry)
    }
    const scheduleMeasure = () => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(measure)
    }
    scheduleMeasure()
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(scheduleMeasure)
    observer?.observe(canvas)
    nodeRefs.current.forEach((element) => observer?.observe(element))
    window.addEventListener('resize', scheduleMeasure)
    return () => {
      cancelAnimationFrame(frame)
      observer?.disconnect()
      window.removeEventListener('resize', scheduleMeasure)
    }
  }, [graph.edges, graph.nodes])

  const renderNode = (id: string) => {
    const node = byId.get(id)
    return node ? <JourneyNodeCard key={id} node={node} onSelect={onSelect} onNavigate={onNavigate} nodeRef={(element) => { if (element) nodeRefs.current.set(id, element); else nodeRefs.current.delete(id) }} /> : null
  }
  return (
    <section className="relative overflow-x-auto rounded-2xl border border-border bg-white/65 p-4 sm:p-6" aria-label="Node journey dependency graph">
      <div className="relative z-10 flex flex-wrap items-end justify-between gap-3 border-b border-border/80 pb-4">
        <div>
          <p className="font-mono text-[10px] font-medium uppercase tracking-[0.16em] text-primary">Dependency map</p>
          <h2 className="mt-1 text-base font-bold tracking-[-0.025em] text-foreground">From node identity to served requests</h2>
          <p className="mt-1 max-w-2xl text-xs leading-5 text-muted-foreground">Every dotted route is a live prerequisite from the Hypervisor read model. Follow the main path down the center; side branches show operational support.</p>
        </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-[10px] font-semibold uppercase tracking-[0.1em] text-muted-foreground" aria-label="Dependency map legend">
          <span className="inline-flex items-center gap-2"><span className="journey-legend-line" aria-hidden="true" />Required</span>
          <span className="inline-flex items-center gap-2"><span className="journey-legend-line journey-legend-line-optional" aria-hidden="true" />Optional</span>
        </div>
      </div>
      <div ref={graphRef} className="relative z-0 mt-5 min-w-[760px] pb-2">
        {edgeLayerSize.width > 0 ? <svg className="pointer-events-none absolute inset-0 z-0 h-full w-full overflow-visible" viewBox={`0 0 ${edgeLayerSize.width} ${edgeLayerSize.height}`} preserveAspectRatio="none" aria-hidden="true">
          {edgeGeometry.map(({ edge, path, key, delay }) => {
            const optional = edge.type === 'optional'
            return <g key={key} className={optional ? 'journey-edge-group journey-edge-group-optional' : 'journey-edge-group'}>
              <path d={path} pathLength="1" className="journey-edge" />
              <path d={path} pathLength="1" className="journey-edge-flow" style={{ animationDelay: delay }} />
            </g>
          })}
        </svg> : null}
        <div className="relative z-10 mx-auto grid max-w-[980px] grid-cols-4 gap-x-4 gap-y-7">
          {desktopRows.map((row, rowIndex) => (
            <div key={rowIndex} className="col-span-4 grid min-w-0 grid-cols-4 gap-x-4">
              {row.map(({ id, colStart, colSpan = 1 }) => <div key={id} className="min-w-0" style={{ gridColumn: `${colStart} / span ${colSpan}` }}>{renderNode(id)}</div>)}
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
    apply_provider_installation: 'apply_provider_installation',
    request_model_install: 'request_model_install',
    process_model_install: 'process_model_install',
    create_bundle: 'create_bundle',
    create_private_endpoint: 'create_private_endpoint',
    forecast_private_endpoint: 'forecast_private_endpoint',
    start_private_endpoint: 'start_private_endpoint',
  }
  const action = workflowAction[nextAction?.id ?? ''] ?? (reviewable ? 'prepare_review' : undefined)
  const completion = plan.workflow?.completion
  const destination = nextAction?.id === 'approve_provider_installation' || nextAction?.id === 'inspect_provider_installation' || status === 'waiting_for_provider'
    ? 'providers'
    : nextAction?.id === 'wait_model_install' || nextAction?.id === 'inspect_model_install' || status === 'model_install_queued'
      ? 'models'
      : null
  const statusLabel = status === 'ready_for_review' || status === 'legacy_review_required'
    ? 'Review required'
    : status === 'provider_install_queued'
      ? 'Provider queued'
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
      {completion?.state === 'READY' ? <div className="mt-3 rounded-xl border border-emerald-700/20 bg-emerald-50 p-3 text-xs leading-5 text-emerald-900"><p className="font-semibold">Private Endpoint ready</p><p className="mt-1">{String(completion.summary ?? 'The assisted setup reached a healthy local runtime.')}</p><p className="mt-1 font-mono text-[10px] uppercase tracking-[0.08em] text-emerald-800">Publication: {String(completion.publication ?? 'NOT_PUBLISHED').replaceAll('_', ' ')}</p></div> : null}
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

function formatQAtoms(value: number): string {
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(value / 1_000_000)
}

function TestnetParticipationPanel({ participation }: { participation: TestnetParticipationDashboard | undefined }) {
  const runtime = participation?.runtime
  const settlement = participation?.last_settlement
  const accounting = settlement?.accounting
  const payout = settlement?.payout
  const mode = runtime?.mode ?? 'disabled'
  const statusLabel = mode === 'submit' ? 'Settling' : mode === 'dry_run' ? 'Dry run' : mode === 'inspect' ? 'Observe only' : 'Not enabled'
  const statusClass = mode === 'submit'
    ? 'border-emerald-700/25 bg-emerald-50 text-emerald-800'
    : mode === 'dry_run'
      ? 'border-sky-700/25 bg-sky-50 text-sky-800'
      : 'border-slate-300 bg-slate-50 text-slate-600'
  const outcome = settlement?.state === 'processed'
    ? payout?.batch_status === 'FINALIZED' ? 'Finalized' : payout?.batch_status === 'PENDING' ? 'Awaiting finality' : 'Calculated'
    : settlement?.state === 'not_due' ? 'Next daily boundary pending' : 'No finalized settlement yet'

  return (
    <section className="rounded-2xl border border-border bg-white/80 p-4" aria-label="Testnet participation status">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-bold text-foreground">Testnet participation</h2>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">Rewards follow a finalized network epoch. This panel cannot create a payout.</p>
        </div>
        <span className={cn('shrink-0 rounded-full border px-2 py-1 text-[10px] font-bold uppercase tracking-[0.1em]', statusClass)}>{statusLabel}</span>
      </div>

      {!participation?.available ? <p className="mt-4 rounded-xl border border-border bg-secondary/45 p-3 text-xs leading-5 text-muted-foreground">Participation accounting is not configured on this Hypervisor. Release defaults keep payouts off.</p> : <>
        <dl className="mt-4 space-y-2 text-xs">
          <div className="flex justify-between gap-3"><dt className="text-muted-foreground">Network</dt><dd className="max-w-[11rem] truncate font-mono text-foreground" title={participation.program?.chain_id}>{participation.program?.chain_id ?? 'Not reported'}</dd></div>
          <div className="flex justify-between gap-3"><dt className="text-muted-foreground">Settlement</dt><dd className="text-right font-medium text-foreground">{outcome}</dd></div>
          <div className="flex justify-between gap-3"><dt className="text-muted-foreground">Eligible nodes</dt><dd className="font-mono text-foreground">{accounting?.eligible_node_count ?? 0}</dd></div>
          <div className="flex justify-between gap-3"><dt className="text-muted-foreground">Last calculated</dt><dd className="font-mono text-foreground">{accounting ? `${formatQAtoms(accounting.total_reward_q_atoms)} Q` : '—'}</dd></div>
        </dl>
        {settlement?.source_epoch_transition_operation_id ? <p className="mt-3 truncate font-mono text-[10px] text-muted-foreground" title={settlement.source_epoch_transition_operation_id}>Epoch {settlement.closing_epoch} · {settlement.source_epoch_transition_operation_id}</p> : null}
        {participation.last_error_code ? <p className="mt-3 rounded-xl border border-amber-700/25 bg-amber-50 p-3 text-xs leading-5 text-amber-900">Accounting is paused: {participation.last_error_code.replaceAll('_', ' ').toLowerCase()}. Review the network and runtime configuration.</p> : null}
      </>}
    </section>
  )
}

function JourneyRail({ graph, residentAgent, installationPlan, participation, onNavigate, onApplyInstallationPlan }: { graph: JourneyGraph; residentAgent: ResidentAgentStatus | undefined; installationPlan: InstallationPlan | undefined; participation: TestnetParticipationDashboard | undefined; onNavigate: (screen: DashboardScreen) => void; onApplyInstallationPlan: (planHash: string, action?: AssistedInstallationAction) => Promise<void> }) {
  const next = graph.recommended_action
  const route = next.screen && dashboardScreens.includes(next.screen as DashboardScreen) ? next.screen as DashboardScreen : null
  const nodeId = graph.hypervisor.node_id || 'local-node'
  return (
    <aside className="space-y-3 xl:sticky xl:top-4 xl:self-start">
      <section className="rounded-2xl border border-border bg-white/80 p-4"><div className="flex items-center justify-between gap-3"><h2 className="text-sm font-bold text-foreground">Node status</h2><span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-700/25 bg-emerald-50 px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.12em] text-emerald-800"><span className="size-1.5 rounded-full bg-emerald-700" />{graph.hypervisor.state === 'ready' ? 'Online' : 'Starting'}</span></div><dl className="mt-4 space-y-2 text-xs"><div className="flex justify-between gap-3"><dt className="text-muted-foreground">Node ID</dt><dd className="max-w-[11rem] truncate font-mono text-foreground">{nodeId}</dd></div><div className="flex justify-between gap-3"><dt className="text-muted-foreground">Role</dt><dd className="font-medium capitalize text-foreground">{graph.role}</dd></div><div className="flex justify-between gap-3"><dt className="text-muted-foreground">Network</dt><dd className="font-medium text-foreground">{graph.hypervisor.network_ready ? 'Ready' : 'Evidence pending'}</dd></div></dl><Button variant="outline" size="sm" className="mt-4 min-h-11 w-full justify-between" onClick={() => onNavigate('settings')}>Node settings<ChevronRight className="size-3.5" /></Button></section>
      <section className="rounded-2xl border border-primary/20 bg-primary/[0.045] p-4" aria-label="Resident Node Steward status">
        <div className="flex items-start justify-between gap-3">
          <div><p className="font-mono text-[10px] font-medium uppercase tracking-[0.14em] text-primary">RFC-0075</p><h2 className="mt-1 text-sm font-bold text-foreground">Resident Steward</h2></div>
          <span className={cn('rounded-full border px-2 py-1 text-[10px] font-bold uppercase tracking-[0.1em]', residentAgent?.enabled ? 'border-emerald-700/25 bg-emerald-50 text-emerald-800' : 'border-slate-300 bg-slate-50 text-muted-foreground')}>{residentAgent?.enabled ? residentAgent.state : 'Disabled'}</span>
        </div>
        <p className="mt-2 text-xs leading-5 text-muted-foreground">CPU-first local control agent. It can advance the reviewed private setup through policy-bound MCP actions; resource admission remains authoritative.</p>
        <dl className="mt-3 space-y-2 text-xs"><div className="flex justify-between gap-3"><dt className="text-muted-foreground">Profile</dt><dd className="font-mono font-medium text-foreground">{residentAgent?.execution.profile ?? 'CPU_RESIDENT'}</dd></div><div className="flex justify-between gap-3"><dt className="text-muted-foreground">Model</dt><dd className="max-w-[11rem] truncate font-mono text-foreground">{residentAgent?.model.llama_cpp_reference ?? 'Qwen2.5-0.5B:Q4_K_M'}</dd></div><div className="flex justify-between gap-3"><dt className="text-muted-foreground">Events seen</dt><dd className="font-mono text-foreground">{residentAgent?.event_ingestion.events_seen ?? 0}</dd></div></dl>
        <p className="mt-3 text-[11px] leading-4 text-muted-foreground">{residentAgent?.health === 'NOT_RUNNING' ? 'Inference adapter is not started; no model weights are downloaded automatically.' : residentAgent?.last_error ?? 'Status is reported by the Hypervisor.'}</p>
      </section>
      <TestnetParticipationPanel participation={participation} />
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

export function JourneyPage({ graph, residentAgent, installationPlan, participation, isLoading, error, onRefresh, onNavigate, onApplyInstallationPlan, onStewardChat }: JourneyPageProps) {
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
      <InstallationHandoffPanel plan={installationPlan} onStewardChat={onStewardChat} />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_300px]"> <div className="min-w-0">{view === 'list' ? <JourneyList graph={graph} onSelect={selectNode} onNavigate={onNavigate} /> : <><div className="hidden lg:block overflow-x-auto"><JourneyGraphDesktop graph={graph} onSelect={selectNode} onNavigate={onNavigate} /></div><div className="space-y-3 lg:hidden">{mobileGroups.map((group) => <JourneyGroup key={group.id} label={group.label} nodes={group.nodes} byId={byId} open={Boolean(openGroups[group.id])} onToggle={() => setOpenGroups((current) => ({ ...current, [group.id]: !current[group.id] }))} onSelect={selectNode} onNavigate={onNavigate} />)}</div></>}</div><JourneyRail graph={graph} residentAgent={residentAgent} installationPlan={installationPlan} participation={participation} onNavigate={onNavigate} onApplyInstallationPlan={onApplyInstallationPlan} /></div>
      <JourneyDetailSheet node={selected} open={detailOpen} onOpenChange={setDetailOpen} onNavigate={onNavigate} />
    </div>
  )
}
