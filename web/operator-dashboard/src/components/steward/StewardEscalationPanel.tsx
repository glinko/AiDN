import { useMemo, useState, type ReactNode } from 'react'
import {
  Activity,
  CheckCircle2,
  ChevronRight,
  Clock3,
  Cpu,
  Eye,
  GitBranch,
  KeyRound,
  LoaderCircle,
  RefreshCw,
  ShieldCheck,
  XCircle,
} from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import type { EscalationTask, ResidentAgentStatus } from '@/lib/types'
import { cn } from '@/lib/utils'

type StewardEscalationPanelProps = {
  status: ResidentAgentStatus | undefined
  tasks: EscalationTask[]
  isLoading: boolean
  error: Error | null
  isFetching: boolean
  onRefresh: () => void
}

const stateTone: Record<string, string> = {
  CREATED: 'border-slate-300/25 bg-slate-300/8 text-slate-200',
  CONTEXT_PREPARED: 'border-sky-300/25 bg-sky-300/8 text-sky-100',
  WAITING_PROVIDER: 'border-amber-300/25 bg-amber-300/8 text-amber-100',
  PLAN_READY: 'border-cyan-300/25 bg-cyan-300/8 text-cyan-100',
  WAITING_APPROVAL: 'border-amber-300/30 bg-amber-300/10 text-amber-100',
  APPROVED: 'border-emerald-300/25 bg-emerald-300/8 text-emerald-100',
  VERIFYING: 'border-sky-300/25 bg-sky-300/8 text-sky-100',
  COMPLETED: 'border-emerald-300/30 bg-emerald-300/10 text-emerald-100',
  FAILED: 'border-rose-300/30 bg-rose-300/10 text-rose-100',
  EXPIRED: 'border-slate-300/25 bg-slate-300/8 text-slate-300',
  CANCELLED: 'border-slate-300/25 bg-slate-300/8 text-slate-300',
}

function stateLabel(value: string): string {
  return value.replaceAll('_', ' ').toLowerCase().replace(/^./, (letter) => letter.toUpperCase())
}

function stateClass(value: string): string {
  return stateTone[value.toUpperCase()] ?? stateTone.CREATED
}

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return 'Not recorded'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

function recordValue(value: unknown, key: string): unknown {
  return typeof value === 'object' && value !== null && key in value ? (value as Record<string, unknown>)[key] : undefined
}

function textValue(value: unknown, key: string, fallback = '—'): string {
  const item = recordValue(value, key)
  return typeof item === 'string' && item.trim() ? item : fallback
}

function planActions(task: EscalationTask): Array<Record<string, unknown>> {
  const actions = recordValue(task.plan, 'actions')
  return Array.isArray(actions) ? actions.filter((item): item is Record<string, unknown> => typeof item === 'object' && item !== null) : []
}

function providerId(task: EscalationTask): string {
  if (task.selected_provider_id) return task.selected_provider_id
  return textValue(recordValue(task.route_decision, 'selected_provider'), 'provider_id', 'No provider selected')
}

function TaskStateIcon({ state }: { state: string }) {
  const normalized = state.toUpperCase()
  if (normalized === 'COMPLETED' || normalized === 'APPROVED') return <CheckCircle2 className="size-4" aria-hidden="true" />
  if (normalized === 'FAILED') return <XCircle className="size-4" aria-hidden="true" />
  if (normalized === 'WAITING_APPROVAL') return <ShieldCheck className="size-4" aria-hidden="true" />
  if (normalized === 'CONTEXT_PREPARED' || normalized === 'VERIFYING') return <LoaderCircle className="size-4 animate-spin" aria-hidden="true" />
  return <Activity className="size-4" aria-hidden="true" />
}

function TaskRow({ task, onSelect }: { task: EscalationTask; onSelect: () => void }) {
  return (
    <button
      type="button"
      className="group flex min-h-[78px] w-full items-start gap-3 border-b border-border/70 px-4 py-3 text-left transition-colors last:border-b-0 hover:bg-white/[0.035] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-cyan-300/70"
      onClick={onSelect}
      aria-label={`Inspect escalation ${task.task_id}`}
    >
      <span className={cn('mt-0.5 grid size-8 shrink-0 place-items-center rounded-lg border', stateClass(task.state))}>
        <TaskStateIcon state={task.state} />
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex flex-wrap items-center gap-2">
          <span className="truncate text-sm font-medium text-slate-100">{task.goal}</span>
          <Badge variant="outline" className={cn('h-5 px-1.5 font-mono text-[9px] uppercase tracking-[0.08em]', stateClass(task.state))}>{stateLabel(task.state)}</Badge>
        </span>
        <span className="mt-1 flex flex-wrap gap-x-3 gap-y-1 font-mono text-[10px] text-slate-500">
          <span>{task.task_id}</span>
          <span>{providerId(task)}</span>
          <span>{formatTimestamp(task.updated_at)}</span>
        </span>
      </span>
      <ChevronRight className="mt-2 size-4 shrink-0 text-slate-500 transition-transform group-hover:translate-x-0.5 group-hover:text-cyan-200" aria-hidden="true" />
    </button>
  )
}

function EscalationDetail({ task }: { task: EscalationTask }) {
  const actions = planActions(task)
  const approvalStatus = textValue(task.approval, 'status', 'NOT_REQUESTED')
  const verificationPassed = recordValue(task.verification, 'passed')
  return (
    <div className="space-y-5 overflow-y-auto px-4 pb-6 sm:px-6">
      <div className="rounded-xl border border-cyan-300/15 bg-cyan-300/[0.045] p-4">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="outline" className={cn('h-6 px-2 font-mono text-[10px] uppercase tracking-[0.08em]', stateClass(task.state))}>{stateLabel(task.state)}</Badge>
          <span className="font-mono text-[10px] text-slate-500">{task.task_id}</span>
        </div>
        <h3 className="mt-3 text-lg font-semibold tracking-[-0.02em] text-white">{task.goal}</h3>
        <p className="mt-2 text-sm leading-6 text-slate-400">This is a durable reasoning hand-off. The dashboard can inspect its evidence, but no plan is executed from this view.</p>
      </div>

      <section className="grid gap-3 sm:grid-cols-2" aria-label="Escalation metadata">
        <Meta label="Provider" value={providerId(task)} icon={<GitBranch className="size-3.5" />} />
        <Meta label="Data class" value={task.data_class} icon={<ShieldCheck className="size-3.5" />} />
        <Meta label="Created" value={formatTimestamp(task.created_at)} icon={<Clock3 className="size-3.5" />} />
        <Meta label="Updated" value={formatTimestamp(task.updated_at)} icon={<Activity className="size-3.5" />} />
      </section>

      <section className="rounded-xl border border-border/80 bg-[#091725] p-4">
        <div className="flex items-center justify-between gap-3">
          <div><p className="eyebrow">Approval boundary</p><p className="mt-1 text-sm font-semibold text-white">{stateLabel(approvalStatus)}</p></div>
          <KeyRound className="size-4 text-cyan-200" aria-hidden="true" />
        </div>
        <p className="mt-2 text-xs leading-5 text-slate-400">Approval is recorded separately from the Agent tool catalog and is bound to the exact plan hash.</p>
        {task.plan_hash ? <code className="mt-3 block break-all rounded-md bg-black/20 p-2 font-mono text-[10px] text-cyan-100">{task.plan_hash}</code> : <p className="mt-3 text-xs text-slate-500">No plan has been attached.</p>}
      </section>

      <section className="rounded-xl border border-border/80 bg-[#091725] p-4">
        <div className="flex items-center justify-between gap-3"><div><p className="eyebrow">Typed plan</p><p className="mt-1 text-sm font-semibold text-white">{actions.length ? `${actions.length} action${actions.length === 1 ? '' : 's'} proposed` : 'No actions proposed'}</p></div><Cpu className="size-4 text-cyan-200" aria-hidden="true" /></div>
        {actions.length ? <ol className="mt-3 space-y-2">{actions.map((action, index) => <li key={`${String(action.tool)}-${index}`} className="rounded-lg border border-border/70 bg-black/15 p-3"><div className="flex items-start gap-2"><span className="grid size-5 shrink-0 place-items-center rounded bg-cyan-300/10 font-mono text-[10px] text-cyan-100">{index + 1}</span><div className="min-w-0"><p className="truncate font-mono text-xs text-cyan-100">{textValue(action, 'tool', 'unknown tool')}</p><p className="mt-1 text-[11px] leading-5 text-slate-500">Arguments are retained for review only.</p></div></div></li>)}</ol> : <p className="mt-3 text-xs leading-5 text-slate-500">The provider has not returned a typed plan yet.</p>}
      </section>

      <section className="rounded-xl border border-border/80 bg-[#091725] p-4">
        <div className="flex items-center justify-between gap-3"><div><p className="eyebrow">Postconditions</p><p className="mt-1 text-sm font-semibold text-white">{task.postconditions.length} declared</p></div><CheckCircle2 className="size-4 text-emerald-200" aria-hidden="true" /></div>
        {task.verification ? <p className={cn('mt-3 text-xs leading-5', verificationPassed === true ? 'text-emerald-200' : 'text-rose-200')}>{verificationPassed === true ? 'All declared postconditions passed.' : 'One or more postconditions failed.'}</p> : <p className="mt-3 text-xs leading-5 text-slate-500">Verification has not been recorded.</p>}
      </section>
    </div>
  )
}

function Meta({ label, value, icon }: { label: string; value: string; icon: ReactNode }) {
  return <div className="rounded-xl border border-border/80 bg-[#091725] p-3"><p className="eyebrow flex items-center gap-1.5">{icon}{label}</p><p className="mt-2 truncate text-sm font-medium text-slate-100" title={value}>{value}</p></div>
}

export function StewardEscalationPanel({ status, tasks, isLoading, error, isFetching, onRefresh }: StewardEscalationPanelProps) {
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null)
  const selectedTask = useMemo(() => tasks.find((task) => task.task_id === selectedTaskId), [selectedTaskId, tasks])
  const activeTasks = tasks.filter((task) => !['COMPLETED', 'FAILED', 'EXPIRED', 'CANCELLED'].includes(task.state.toUpperCase())).length
  const attentionTasks = tasks.filter((task) => ['WAITING_APPROVAL', 'FAILED', 'WAITING_PROVIDER'].includes(task.state.toUpperCase())).length

  return (
    <>
      <Card className="border-cyan-300/20 bg-cyan-300/[0.035] py-0 shadow-none">
        <CardHeader className="flex-row items-start justify-between gap-3 border-b border-border/70 px-5 py-4">
          <div><p className="eyebrow text-cyan-100">Resident control</p><CardTitle className="mt-1 text-lg font-semibold text-white">Node Steward</CardTitle><p className="mt-1 max-w-2xl text-sm leading-6 text-muted-foreground">A small local control agent handles routine node work and hands complex reasoning to a bounded, inspectable task queue.</p></div>
          <Button variant="outline" size="sm" className="shrink-0 border-cyan-300/25 bg-[#091725] text-cyan-100" onClick={onRefresh} aria-label="Refresh Node Steward"><RefreshCw className={cn(isFetching && 'animate-spin')} />Refresh</Button>
        </CardHeader>
        <CardContent className="space-y-4 p-4 sm:p-5">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Meta label="Health" value={status?.health || 'Not reported'} icon={<Activity className="size-3.5" />} />
            <Meta label="Execution" value={status?.execution.profile || 'Not reported'} icon={<Cpu className="size-3.5" />} />
            <Meta label="Active hand-offs" value={String(activeTasks)} icon={<GitBranch className="size-3.5" />} />
            <Meta label="Attention" value={String(attentionTasks)} icon={<ShieldCheck className="size-3.5" />} />
          </div>
          {error ? <div className="rounded-lg border border-amber-300/20 bg-amber-300/[0.04] px-3 py-2 text-xs leading-5 text-amber-100">Steward escalation read model unavailable: {error.message}</div> : null}
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1.35fr)_minmax(17rem,0.65fr)]">
            <section className="overflow-hidden rounded-xl border border-border/80 bg-[#07111d]" aria-label="Escalation task list">
              <div className="flex items-center justify-between gap-3 border-b border-border/70 px-4 py-3"><div><p className="eyebrow">Durable queue</p><p className="mt-1 text-sm font-semibold text-white">Escalation Tasks</p></div><Badge variant="outline" className="border-cyan-300/20 bg-cyan-300/[0.05] font-mono text-[10px] text-cyan-100">{tasks.length} retained</Badge></div>
              {isLoading ? <div className="flex items-center gap-2 px-4 py-8 text-xs text-slate-400"><LoaderCircle className="size-4 animate-spin" />Loading hand-offs…</div> : tasks.length === 0 ? <div className="px-4 py-8 text-center"><GitBranch className="mx-auto size-5 text-slate-600" /><p className="mt-2 text-sm font-medium text-slate-200">No escalation tasks</p><p className="mt-1 text-xs leading-5 text-slate-500">Complex work will appear here instead of silently entering a model conversation.</p></div> : <div>{tasks.slice(0, 8).map((task) => <TaskRow key={task.task_id} task={task} onSelect={() => setSelectedTaskId(task.task_id)} />)}</div>}
            </section>
            <section className="rounded-xl border border-border/80 bg-[#07111d] p-4" aria-label="Steward authority boundary">
              <div className="flex items-start gap-3"><span className="grid size-9 shrink-0 place-items-center rounded-lg border border-cyan-300/20 bg-cyan-300/[0.06] text-cyan-100"><Eye className="size-4" /></span><div><p className="eyebrow">Control boundary</p><p className="mt-1 text-sm font-semibold text-white">Inspect first, execute elsewhere</p></div></div>
              <ul className="mt-4 space-y-3 text-xs leading-5 text-slate-400"><li className="flex gap-2"><CheckCircle2 className="mt-0.5 size-3.5 shrink-0 text-emerald-200" />Context is bounded and credential-looking fields are redacted.</li><li className="flex gap-2"><CheckCircle2 className="mt-0.5 size-3.5 shrink-0 text-emerald-200" />Plans are hash-bound and approval stays with the operator.</li><li className="flex gap-2"><CheckCircle2 className="mt-0.5 size-3.5 shrink-0 text-emerald-200" />This surface never starts a provider or invokes a tool.</li></ul>
            </section>
          </div>
        </CardContent>
      </Card>
      <Sheet open={Boolean(selectedTask)} onOpenChange={(open) => { if (!open) setSelectedTaskId(null) }}>
        <SheetContent side="right" className="w-full border-border bg-[#07111d] text-white sm:max-w-xl">
          <SheetHeader className="border-b border-border/70 px-4 py-5 sm:px-6"><p className="eyebrow text-cyan-100">Escalation detail</p><SheetTitle className="mt-1 text-lg text-white">Task evidence</SheetTitle><SheetDescription className="text-slate-400">Review the bounded hand-off and its policy state. Execution remains outside this detail view.</SheetDescription></SheetHeader>
          {selectedTask ? <EscalationDetail task={selectedTask} /> : null}
        </SheetContent>
      </Sheet>
    </>
  )
}
