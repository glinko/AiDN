import {
  Activity,
  AlertTriangle,
  Clock3,
  Database,
  Gauge,
  Layers3,
  RefreshCw,
  ServerCog,
  Zap,
} from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import type { ResourceBrokerDashboard } from '@/lib/types'
import { formatCount, formatMemory, getRecord, shortId } from '@/lib/format'
import { cn } from '@/lib/utils'

type ResourceBrokerWorkspaceProps = {
  data: ResourceBrokerDashboard | undefined
  isLoading: boolean
  error: Error | null
  isFetching: boolean
  onRefresh: () => void
}

type RecordValue = Record<string, unknown>

function record(value: unknown): RecordValue {
  return getRecord(value) ?? {}
}

function number(value: unknown, fallback = 0): number {
  const parsed = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

function text(value: unknown, fallback = '—'): string {
  return typeof value === 'string' && value.trim() ? value : fallback
}

function list(value: unknown): RecordValue[] {
  return Array.isArray(value)
    ? value.filter((item): item is RecordValue => Boolean(getRecord(item)))
    : []
}

function statusLabel(value: unknown): string {
  return text(value, 'unknown').replaceAll('_', ' ').toLowerCase().replace(/^./, (letter) => letter.toUpperCase())
}

function statusClass(value: unknown): string {
  const normalized = text(value, 'unknown').toUpperCase()
  if (['READY', 'RUNNABLE', 'TRUSTED', 'ACTIVE', 'HEALTHY', 'STABLE'].includes(normalized)) {
    return 'border-emerald-300/25 bg-emerald-300/10 text-emerald-100'
  }
  if (['RESOURCE_WAIT', 'WAITING', 'UNCERTAIN', 'DEGRADED', 'WARNING'].includes(normalized)) {
    return 'border-amber-300/25 bg-amber-300/10 text-amber-100'
  }
  if (['FAILED', 'ERROR', 'BLOCKED', 'UNROUTED'].includes(normalized)) {
    return 'border-rose-300/25 bg-rose-300/10 text-rose-100'
  }
  return 'border-slate-300/20 bg-slate-300/8 text-slate-300'
}

function formatTimestamp(value: unknown): string {
  const raw = text(value, '')
  if (!raw) return 'Not recorded'
  const parsed = new Date(raw)
  return Number.isNaN(parsed.getTime()) ? raw : parsed.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

function formatSeconds(value: unknown): string {
  const seconds = number(value, NaN)
  if (!Number.isFinite(seconds)) return 'Unavailable'
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)}s`
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`
  return `${(seconds / 3600).toFixed(1)}h`
}

function MetricCard({ label, value, detail, icon: Icon, tone = 'text-cyan-100' }: { label: string; value: string; detail?: string; icon: typeof Gauge; tone?: string }) {
  return (
    <Card className="border-border/80 bg-card py-0 shadow-none">
      <CardContent className="flex items-start gap-3 p-4">
        <span className="grid size-9 shrink-0 place-items-center rounded-lg border border-cyan-300/15 bg-cyan-300/[0.06] text-cyan-100"><Icon className="size-4" aria-hidden="true" /></span>
        <div className="min-w-0"><p className="eyebrow">{label}</p><p className={cn('mt-1 truncate font-mono text-xl font-semibold', tone)}>{value}</p>{detail ? <p className="mt-1 truncate text-[11px] text-muted-foreground">{detail}</p> : null}</div>
      </CardContent>
    </Card>
  )
}

function ResourceMeter({ label, used, total, suffix = '' }: { label: string; used: number; total: number; suffix?: string }) {
  const percent = total > 0 ? Math.min(100, Math.max(0, (used / total) * 100)) : 0
  return (
    <div>
      <div className="flex items-center justify-between gap-3 text-xs"><span className="text-slate-300">{label}</span><span className="font-mono text-slate-400">{used.toFixed(suffix ? 1 : 0)}{suffix} / {total.toFixed(suffix ? 1 : 0)}{suffix}</span></div>
      <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-800"><div className="h-full rounded-full bg-gradient-to-r from-cyan-300 to-teal-300 transition-[width]" style={{ width: `${percent}%` }} /></div>
    </div>
  )
}

function EmptyReadModel({ title, detail }: { title: string; detail: string }) {
  return <div className="rounded-xl border border-border/70 bg-black/10 px-4 py-8 text-center"><Gauge className="mx-auto size-5 text-slate-600" aria-hidden="true" /><p className="mt-2 text-sm font-medium text-slate-200">{title}</p><p className="mt-1 text-xs leading-5 text-slate-500">{detail}</p></div>
}

export function ResourceBrokerWorkspace({ data, isLoading, error, isFetching, onRefresh }: ResourceBrokerWorkspaceProps) {
  if (isLoading && !data) {
    return <div className="space-y-4"><Skeleton className="h-24 w-full" /><div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4"><Skeleton className="h-24" /><Skeleton className="h-24" /><Skeleton className="h-24" /><Skeleton className="h-24" /></div><Skeleton className="h-80 w-full" /></div>
  }

  if (error && !data) {
    return <Card className="border-rose-300/25 bg-rose-300/[0.04] py-0 shadow-none"><CardContent className="p-5"><div className="flex items-start gap-3"><AlertTriangle className="mt-0.5 size-5 shrink-0 text-rose-200" /><div><p className="font-medium text-rose-100">Resource Broker read model unavailable</p><p className="mt-1 text-sm leading-6 text-rose-100/70">{error.message}</p><Button variant="outline" size="sm" className="mt-4 border-rose-300/25 bg-transparent text-rose-100" onClick={onRefresh}><RefreshCw />Retry</Button></div></div></CardContent></Card>
  }

  const payload = data ?? { available: false, generated_at: '', hardware: {}, summary: {}, scheduler: {}, leases: [], runtimes: [], runtime_summary: {}, metrics: {} }
  const hardware = record(payload.hardware)
  const summary = record(payload.summary)
  const scheduler = record(payload.scheduler)
  const queue = record(scheduler.queue)
  const candidates = record(scheduler.candidates)
  const reconciliation = record(scheduler.reconciliation)
  const metrics = record(payload.metrics)
  const queueWait = record(metrics.queue_wait)
  const cpu = record(hardware.cpu)
  const ram = record(hardware.ram)
  const gpus = list(hardware.gpus)
  const leases = payload.leases as RecordValue[]
  const runtimes = payload.runtimes as RecordValue[]
  const candidateItems = list(candidates.items)
  const byStatus = record(candidates.by_status)
  const summaryTotal = record(summary.total)
  const summaryFree = record(summary.free)
  const totalVram = number(summaryTotal.vram_mb, gpus.reduce((total, gpu) => total + number(gpu.vram_total_mb), 0))
  const freeVram = number(summaryFree.vram_mb, gpus.reduce((total, gpu) => total + number(gpu.vram_allocatable_mb), 0))
  const totalRam = number(summaryTotal.ram_mb, number(ram.physical_total_mb))
  const freeRam = number(summaryFree.ram_mb, number(ram.free_allocatable_mb))
  const totalCpu = number(summaryTotal.cpu, number(cpu.physical_cores))
  const freeCpu = number(summaryFree.cpu, number(cpu.free_allocatable_cores))
  const runtimeSummary = record(payload.runtime_summary)
  const runtimeFreshness = record(metrics.runtime_freshness)
  const hardwareReconciliation = record(hardware.reconciliation)
  const schedulerState = text(reconciliation.status || reconciliation.state || hardwareReconciliation.state, payload.available ? 'unknown' : 'unavailable')

  return (
    <div className="resource-broker-workspace space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div><p className="eyebrow text-cyan-100">Advanced operations</p><h1 className="mt-1 text-2xl font-semibold tracking-[-0.03em] text-white">Resources and Scheduler</h1><p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">A read-only view of physical capacity, leases, runtime instances, independent queues, and the latest admission decisions. The broker remains the authority; this page never starts or evicts a runtime.</p></div>
        <Button variant="outline" size="sm" className="border-border bg-[#091725]" onClick={onRefresh}><RefreshCw className={cn(isFetching && 'animate-spin')} />Refresh</Button>
      </div>

      {!payload.available ? <Card className="border-amber-300/25 bg-amber-300/[0.04] py-0 shadow-none"><CardContent className="flex items-start gap-3 p-5"><AlertTriangle className="mt-0.5 size-5 shrink-0 text-amber-200" /><div><p className="font-medium text-amber-100">Resource Broker is not available</p><p className="mt-1 text-sm leading-6 text-amber-100/70">This Hypervisor does not expose a trusted local capacity projection yet. No admission decision should be inferred from this screen.</p></div></CardContent></Card> : null}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <MetricCard label="Admission" value={statusLabel(schedulerState)} detail={formatTimestamp(payload.generated_at)} icon={Gauge} tone={statusClass(schedulerState).includes('emerald') ? 'text-emerald-100' : 'text-amber-100'} />
        <MetricCard label="Queued work" value={formatCount(number(queue.queued_tasks))} detail={`${formatCount(number(queue.independent_queues))} independent queues`} icon={Layers3} />
        <MetricCard label="Active leases" value={formatCount(leases.length)} detail={`${formatMemory(number(hardware.reserved_vram_mb))} VRAM reserved`} icon={Database} />
        <MetricCard label="Runtime instances" value={formatCount(number(runtimeSummary.runtime_total, runtimes.length))} detail={`${formatCount(number(runtimeSummary.runtime_ready))} ready`} icon={ServerCog} />
        <MetricCard label="Runnable candidates" value={formatCount(number(metrics.runnable_count, number(byStatus.RUNNABLE)))} detail={`${formatCount(number(metrics.resource_wait_count, number(byStatus.RESOURCE_WAIT)))} waiting for resources`} icon={Activity} />
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.15fr)_minmax(20rem,0.85fr)]">
        <Card className="border-border/80 bg-card py-0 shadow-none">
          <CardHeader className="border-b border-border/70 px-5 py-4"><p className="eyebrow">Hardware monitor</p><CardTitle className="mt-1 text-lg font-semibold">Allocatable capacity</CardTitle><p className="mt-1 text-sm leading-6 text-muted-foreground">Measured usage is combined with active leases and safety headroom before a cold runtime can start.</p></CardHeader>
          <CardContent className="space-y-5 p-5">
            <ResourceMeter label="CPU" used={Math.max(0, totalCpu - freeCpu)} total={totalCpu} suffix=" cores" />
            <ResourceMeter label="RAM" used={Math.max(0, totalRam - freeRam)} total={totalRam} suffix=" MB" />
            <ResourceMeter label="VRAM" used={Math.max(0, totalVram - freeVram)} total={totalVram} suffix=" MB" />
            <div className="grid gap-3 sm:grid-cols-3"><div className="rounded-lg border border-border/70 bg-black/10 p-3"><p className="eyebrow">CPU free</p><p className="mt-1 font-mono text-sm text-cyan-100">{freeCpu.toFixed(1)} cores</p></div><div className="rounded-lg border border-border/70 bg-black/10 p-3"><p className="eyebrow">RAM free</p><p className="mt-1 font-mono text-sm text-cyan-100">{formatMemory(freeRam)}</p></div><div className="rounded-lg border border-border/70 bg-black/10 p-3"><p className="eyebrow">VRAM free</p><p className="mt-1 font-mono text-sm text-cyan-100">{formatMemory(freeVram)}</p></div></div>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-border/70 pt-4 text-[11px] text-slate-500"><span>Source: <b className="font-mono font-normal text-slate-300">{text(hardware.source, 'unknown')}</b></span><span>Observed: <b className="font-mono font-normal text-slate-300">{formatTimestamp(hardware.observed_at)}</b></span><span>Reconciliation: <Badge variant="outline" className={cn('font-mono text-[9px] uppercase', statusClass(hardwareReconciliation.state || schedulerState))}>{statusLabel(hardwareReconciliation.state || schedulerState)}</Badge></span></div>
          </CardContent>
        </Card>

        <Card className="border-border/80 bg-card py-0 shadow-none">
          <CardHeader className="border-b border-border/70 px-5 py-4"><p className="eyebrow">Device allocation</p><CardTitle className="mt-1 text-lg font-semibold">GPUs</CardTitle></CardHeader>
          <CardContent className="space-y-3 p-5">{gpus.length ? gpus.map((gpu, index) => { const total = number(gpu.vram_total_mb); const free = number(gpu.vram_allocatable_mb); return <div key={text(gpu.device_id, `gpu-${index}`)} className="rounded-xl border border-border/70 bg-black/10 p-4"><div className="flex items-start justify-between gap-3"><div><p className="font-mono text-sm text-cyan-100">{text(gpu.device_id, `GPU ${index}`)}</p><p className="mt-1 text-xs text-slate-500">{formatMemory(number(gpu.vram_measured_used_mb))} measured · {formatMemory(free)} allocatable</p></div><Zap className="size-4 text-amber-200" aria-hidden="true" /></div><ResourceMeter label="VRAM" used={Math.max(0, total - free)} total={total} suffix=" MB" /></div> }) : <EmptyReadModel title="No GPU inventory" detail="The current hardware probe did not report device-level VRAM." />}</CardContent>
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card className="border-border/80 bg-card py-0 shadow-none">
          <CardHeader className="flex-row items-start justify-between gap-3 border-b border-border/70 px-5 py-4"><div><p className="eyebrow">Admission control</p><CardTitle className="mt-1 text-lg font-semibold">Queue candidates</CardTitle><p className="mt-1 text-sm leading-6 text-muted-foreground">One head candidate per independent queue. A request that does not fit cannot block a peer that does.</p></div><Badge variant="outline" className={cn('font-mono text-[10px] uppercase', statusClass(schedulerState))}>{statusLabel(schedulerState)}</Badge></CardHeader>
          <CardContent className="p-0">{candidateItems.length ? <div className="divide-y divide-border/70">{candidateItems.slice(0, 12).map((candidate, index) => { const status = text(candidate.status, 'UNKNOWN'); const required = record(candidate.required); const free = record(candidate.free); const shortfall = record(candidate.shortfall); return <div key={text(candidate.task_id, `${candidate.queue_key}-${index}`)} className="px-5 py-4"><div className="flex items-start gap-3"><span className="mt-0.5 grid size-7 shrink-0 place-items-center rounded-md border border-cyan-300/15 bg-cyan-300/[0.05] font-mono text-[10px] text-cyan-100">{index + 1}</span><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><p className="truncate font-mono text-xs text-slate-100">{shortId(text(candidate.task_id, 'unknown task'), 26)}</p><Badge variant="outline" className={cn('h-5 font-mono text-[9px] uppercase', statusClass(status))}>{statusLabel(status)}</Badge></div><p className="mt-1 truncate text-[11px] text-slate-500">{text(candidate.queue_key, 'unassigned queue')} · {text(candidate.runtime_path, 'runtime path unknown')}</p><p className="mt-2 text-xs leading-5 text-slate-400">{text(candidate.decision || candidate.summary || candidate.reason, statusLabel(status))}</p><div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 font-mono text-[10px] text-slate-500"><span>need {formatMemory(number(required.vram_mb))} VRAM</span><span>free {formatMemory(number(free.vram_mb))}</span>{number(shortfall.vram_mb) > 0 ? <span className="text-amber-200">short {formatMemory(number(shortfall.vram_mb))}</span> : null}<span>depth {number(candidate.queue_depth)} / pos {number(candidate.queue_position)}</span></div></div></div></div> })}</div> : <EmptyReadModel title="No queued candidates" detail="Every independent queue is currently empty or no candidate can be projected." />}</CardContent>
        </Card>

        <Card className="border-border/80 bg-card py-0 shadow-none">
          <CardHeader className="border-b border-border/70 px-5 py-4"><p className="eyebrow">Scheduler evidence</p><CardTitle className="mt-1 text-lg font-semibold">Reconciliation and wait time</CardTitle><p className="mt-1 text-sm leading-6 text-muted-foreground">The wait sample is derived from requests currently queued; historical P50/P95 will arrive with durable scheduler telemetry.</p></CardHeader>
          <CardContent className="space-y-4 p-5"><div className="grid gap-3 sm:grid-cols-3"><div className="rounded-xl border border-border/70 bg-black/10 p-3"><p className="eyebrow">P50 current</p><p className="mt-1 font-mono text-lg text-cyan-100">{formatSeconds(queueWait.p50_seconds)}</p></div><div className="rounded-xl border border-border/70 bg-black/10 p-3"><p className="eyebrow">P95 current</p><p className="mt-1 font-mono text-lg text-cyan-100">{formatSeconds(queueWait.p95_seconds)}</p></div><div className="rounded-xl border border-border/70 bg-black/10 p-3"><p className="eyebrow">Sample</p><p className="mt-1 font-mono text-lg text-cyan-100">{formatCount(number(queueWait.sample_count))}</p></div></div><div className="rounded-xl border border-cyan-300/15 bg-cyan-300/[0.035] p-4"><div className="flex items-start gap-3"><span className="grid size-8 shrink-0 place-items-center rounded-lg border border-cyan-300/20 bg-cyan-300/[0.06] text-cyan-100"><Clock3 className="size-4" aria-hidden="true" /></span><div className="min-w-0"><p className="eyebrow text-cyan-100">Latest cycle</p><p className="mt-1 text-sm font-semibold text-white">{statusLabel(reconciliation.status || 'not recorded')}</p><p className="mt-1 text-xs leading-5 text-slate-400">{text(reconciliation.trigger || reconciliation.reason, 'No scheduler trigger recorded.')}</p><p className="mt-2 font-mono text-[10px] text-slate-500">cycles {number(reconciliation.cycles)} · last {formatTimestamp(reconciliation.completed_at || reconciliation.finished_at || reconciliation.updated_at)}</p></div></div></div><div className="flex flex-wrap gap-x-4 gap-y-2 text-[11px] text-slate-500"><span>Current denial count: <b className="font-mono font-normal text-amber-200">{formatCount(number(metrics.admission_denial_count))}</b></span><span>Runtime read: <b className="font-mono font-normal text-slate-300">{text(runtimeFreshness.source, 'unknown')}</b></span><span>Queue sample: <b className="font-mono font-normal text-slate-300">{text(queueWait.source, 'unavailable')}</b></span></div></CardContent>
        </Card>
      </div>

      <Card className="border-border/80 bg-card py-0 shadow-none">
        <CardHeader className="border-b border-border/70 px-5 py-4"><p className="eyebrow">Runtime instances</p><CardTitle className="mt-1 text-lg font-semibold">Warm, active, and draining capacity</CardTitle></CardHeader>
        <CardContent className="p-0">{runtimes.length ? <div className="divide-y divide-border/70">{runtimes.map((runtime, index) => <div key={text(runtime.runtime_id, `${runtime.bundle_id}-${index}`)} className="flex flex-col gap-3 px-5 py-4 lg:flex-row lg:items-center lg:justify-between"><div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><ServerCog className="size-4 text-cyan-100" aria-hidden="true" /><p className="font-mono text-xs text-slate-100">{shortId(text(runtime.runtime_id, 'runtime'), 28)}</p><Badge variant="outline" className={cn('h-5 font-mono text-[9px] uppercase', statusClass(runtime.lifecycle_state || runtime.runtime_status))}>{statusLabel(runtime.lifecycle_state || runtime.runtime_status)}</Badge>{runtime.pinned_warm === true ? <Badge variant="outline" className="h-5 border-cyan-300/20 bg-cyan-300/[0.05] font-mono text-[9px] text-cyan-100">pinned warm</Badge> : null}</div><p className="mt-1 truncate font-mono text-[10px] text-slate-500">bundle {text(runtime.bundle_id)} · model {text(runtime.model_id)} · endpoint {text(runtime.endpoint)}</p><p className="mt-1 text-xs text-slate-400">{text(runtime.readiness_message || runtime.last_error, `${number(runtime.active_task_count)} active task${number(runtime.active_task_count) === 1 ? '' : 's'}`)}</p></div><div className="flex shrink-0 flex-wrap gap-x-4 gap-y-2 font-mono text-[10px] text-slate-500"><span>health {statusLabel(runtime.health_status)}</span><span>tasks {number(runtime.active_task_count)}</span><span>checked {formatTimestamp(runtime.readiness_checked_at)}</span></div></div>)}</div> : <div className="p-5"><EmptyReadModel title="No runtime instances" detail="No managed provider runtime is currently present in the live projection." /></div>}</CardContent>
      </Card>

      <Card className="border-border/80 bg-card py-0 shadow-none">
        <CardHeader className="border-b border-border/70 px-5 py-4"><p className="eyebrow">Resource leases</p><CardTitle className="mt-1 text-lg font-semibold">Atomic reservations</CardTitle><p className="mt-1 text-sm leading-6 text-muted-foreground">Leases are read-only here. Release and drain operations stay behind the lifecycle and Resource Broker authorities.</p></CardHeader>
        <CardContent className="p-0">{leases.length ? <div className="divide-y divide-border/70">{leases.map((lease, index) => <div key={text(lease.lease_id || lease.reservation_id, `lease-${index}`)} className="flex flex-col gap-2 px-5 py-4 sm:flex-row sm:items-center sm:justify-between"><div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><Database className="size-4 text-cyan-100" aria-hidden="true" /><p className="truncate font-mono text-xs text-slate-100">{shortId(text(lease.lease_id || lease.reservation_id, 'lease'), 30)}</p><Badge variant="outline" className={cn('h-5 font-mono text-[9px] uppercase', statusClass(lease.status))}>{statusLabel(lease.status)}</Badge></div><p className="mt-1 truncate text-[11px] text-slate-500">owner {text(lease.owner_id, 'unassigned')} · created {formatTimestamp(lease.created_at)}</p></div><div className="flex flex-wrap gap-x-4 gap-y-1 font-mono text-[10px] text-slate-400"><span>{number(lease.cpu).toFixed(1)} CPU</span><span>{formatMemory(number(lease.ram_mb))} RAM</span><span>{formatMemory(number(lease.vram_mb))} VRAM</span><span>expires {formatTimestamp(lease.expires_at)}</span></div></div>)}</div> : <div className="p-5"><EmptyReadModel title="No active leases" detail="The broker currently reports no active atomic resource reservations." /></div>}</CardContent>
      </Card>

      {list(hardware.external_processes).length || list(hardware.limitations).length ? <Card className="border-amber-300/20 bg-amber-300/[0.03] py-0 shadow-none"><CardHeader className="border-b border-amber-300/15 px-5 py-4"><p className="eyebrow text-amber-100">Probe notes</p><CardTitle className="mt-1 text-lg font-semibold">External usage and limitations</CardTitle></CardHeader><CardContent className="grid gap-3 p-5 sm:grid-cols-2">{list(hardware.external_processes).map((item, index) => <div key={`external-${index}`} className="rounded-lg border border-amber-300/15 bg-black/10 p-3"><p className="eyebrow">External process</p><p className="mt-1 break-words text-xs text-amber-100">{text(item.name || item.command || item.pid, JSON.stringify(item))}</p></div>)}{list(hardware.limitations).map((item, index) => <div key={`limitation-${index}`} className="rounded-lg border border-amber-300/15 bg-black/10 p-3"><p className="eyebrow">Limitation</p><p className="mt-1 break-words text-xs text-amber-100">{JSON.stringify(item)}</p></div>)}</CardContent></Card> : null}
    </div>
  )
}
