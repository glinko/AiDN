import { useEffect, useMemo, useState } from 'react'
import { Check, Cpu, Pause, Play, RefreshCw, Save, ShieldCheck, Square, Zap } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import type { ResidentAgentStatus, ResidentInference, StewardActionPolicy } from '@/lib/types'
import { cn } from '@/lib/utils'

type InferencePreparePayload = {
  model_path: string
  provider_type: string
  profile: 'CPU_RESIDENT' | 'IGPU_RESIDENT' | 'GPU_RESIDENT' | 'GPU_BURST'
  ram_mb: number
  vram_mb: number
  fallback_enabled: boolean
  readiness_timeout_seconds: number
  source_url?: string
  download?: boolean
}

type StewardPolicyPanelProps = {
  status: ResidentAgentStatus | undefined
  policy: StewardActionPolicy | undefined
  inference: ResidentInference | undefined
  isFetching: boolean
  onRefresh: () => void
  onSavePolicy: (payload: { auto_actions: string[]; approval_actions: string[]; max_actions_per_hour: number }) => Promise<unknown>
  onToggle: (enabled: boolean) => Promise<unknown>
  onPrepare: (payload: InferencePreparePayload) => Promise<unknown>
  onStart: () => Promise<unknown>
  onStop: () => Promise<unknown>
}

type StewardFeedback = {
  kind: 'success' | 'error'
  message: string
}

function labelForAction(action: string): string {
  return action.replaceAll('.', ' · ').replaceAll('_', ' ').replace(/^./, (letter) => letter.toUpperCase())
}

function actionMode(action: string, auto: string[], approval: string[]): 'AUTO' | 'APPROVAL' | 'DISABLED' {
  if (auto.includes(action)) return 'AUTO'
  if (approval.includes(action)) return 'APPROVAL'
  return 'DISABLED'
}

export function StewardPolicyPanel({ status, policy, inference, isFetching, onRefresh, onSavePolicy, onToggle, onPrepare, onStart, onStop }: StewardPolicyPanelProps) {
  const catalog = useMemo(() => (policy?.catalog ?? []).filter((entry) => !entry.guard_only), [policy?.catalog])
  const [autoActions, setAutoActions] = useState<string[]>(policy?.auto_actions ?? [])
  const [approvalActions, setApprovalActions] = useState<string[]>(policy?.approval_actions ?? [])
  const [maxActions, setMaxActions] = useState(String(policy?.max_actions_per_hour ?? 12))
  const [modelPath, setModelPath] = useState(status?.model.path ?? '')
  const [sourceUrl, setSourceUrl] = useState('')
  const [profile, setProfile] = useState<'CPU_RESIDENT' | 'IGPU_RESIDENT' | 'GPU_RESIDENT' | 'GPU_BURST'>((status?.execution.profile as 'CPU_RESIDENT' | 'IGPU_RESIDENT' | 'GPU_RESIDENT' | 'GPU_BURST') || 'CPU_RESIDENT')
  const [ramMb, setRamMb] = useState(String(status?.execution.ram_budget_mb ?? 1024))
  const [vramMb, setVramMb] = useState(String(status?.execution.vram_mb ?? 0))
  const [feedback, setFeedback] = useState<StewardFeedback | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  useEffect(() => {
    setAutoActions(policy?.auto_actions ?? [])
    setApprovalActions(policy?.approval_actions ?? [])
    setMaxActions(String(policy?.max_actions_per_hour ?? 12))
  }, [policy?.auto_actions, policy?.approval_actions, policy?.max_actions_per_hour])

  useEffect(() => {
    setModelPath(status?.model.path ?? '')
    setProfile((status?.execution.profile as 'CPU_RESIDENT' | 'IGPU_RESIDENT' | 'GPU_RESIDENT' | 'GPU_BURST') || 'CPU_RESIDENT')
    setRamMb(String(status?.execution.ram_budget_mb ?? 1024))
    setVramMb(String(status?.execution.vram_mb ?? 0))
  }, [status?.model.path, status?.execution.profile, status?.execution.ram_budget_mb, status?.execution.vram_mb])

  function setMode(action: string, mode: 'AUTO' | 'APPROVAL' | 'DISABLED') {
    setAutoActions((current) => mode === 'AUTO' ? [...new Set([...current.filter((item) => item !== action), action])] : current.filter((item) => item !== action))
    setApprovalActions((current) => mode === 'APPROVAL' ? [...new Set([...current.filter((item) => item !== action), action])] : current.filter((item) => item !== action))
  }

  async function run(key: string, work: () => Promise<unknown>, message: string) {
    setBusy(key)
    setFeedback(null)
    try {
      await work()
      setFeedback({ kind: 'success', message })
      onRefresh()
    } catch (error) {
      setFeedback({
        kind: 'error',
        message: error instanceof Error ? error.message : 'Steward operation failed.',
      })
    } finally {
      setBusy(null)
    }
  }

  const runtimeState = String(inference?.state || status?.execution.inference_adapter || 'NOT_CONFIGURED').toUpperCase()
  const isRunning = ['RUNNING', 'READY'].includes(runtimeState)
  return (
    <Card className="border-emerald-300/20 bg-emerald-300/[0.025] py-0 shadow-none">
      <CardHeader className="flex-row items-start justify-between gap-3 border-b border-border/70 px-5 py-4">
        <div><p className="eyebrow text-emerald-100">Steward operations</p><CardTitle className="mt-1 text-lg font-semibold text-white">Policy & local model</CardTitle><p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">Choose what the Resident Steward may do automatically, what requires operator approval, and where its local reasoning model is allowed to run.</p></div>
        <Button variant="outline" size="sm" className="min-h-11 shrink-0 border-emerald-300/25 bg-[#091725] text-emerald-100" onClick={onRefresh} aria-label="Refresh Steward policy"><RefreshCw className={cn(isFetching && 'animate-spin')} />Refresh</Button>
      </CardHeader>
      <CardContent className="space-y-5 p-4 sm:p-5">
        <section className="rounded-xl border border-border/80 bg-[#07111d] p-4" aria-label="Steward service status">
          <div className="flex flex-wrap items-center justify-between gap-3"><div><p className="eyebrow">Resident service</p><p className="mt-1 text-sm font-semibold text-white">{status?.enabled ? 'Enabled for local control' : 'Disabled'}</p><p className="mt-1 text-xs leading-5 text-muted-foreground">Disabling the Steward does not stop Providers, Bundles, or Endpoints.</p></div><div className="flex items-center gap-2"><Badge variant="outline" className={cn('font-mono text-[10px] uppercase', status?.enabled ? 'border-emerald-300/30 text-emerald-100' : 'border-slate-300/30 text-slate-300')}>{status?.enabled ? 'ON' : 'OFF'}</Badge><Button variant={status?.enabled ? 'outline' : 'default'} className={status?.enabled ? 'min-h-11 border-amber-300/25 bg-[#091725] text-amber-100' : 'min-h-11 bg-emerald-300 text-[#06121d] hover:bg-emerald-200'} disabled={busy === 'toggle'} onClick={() => void run('toggle', () => onToggle(!status?.enabled), status?.enabled ? 'Resident Steward disabled.' : 'Resident Steward enabled.')}>{status?.enabled ? <Pause /> : <Play />}{status?.enabled ? 'Disable' : 'Enable'}</Button></div></div>
        </section>

        <section className="rounded-xl border border-border/80 bg-[#07111d] p-4" aria-label="Steward action policy">
          <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="eyebrow">Action boundary</p><p className="mt-1 text-sm font-semibold text-white">Automation policy</p><p className="mt-1 text-xs leading-5 text-muted-foreground">Every action remains allow-listed. Approval-gated actions still require an explicit plan reference.</p></div><label className="grid min-w-36 gap-1.5"><span className="eyebrow">Max actions / hour</span><input type="number" min={1} max={10000} value={maxActions} onChange={(event) => setMaxActions(event.target.value)} className="min-h-11 w-full rounded-lg border border-input bg-[#091725] px-3 font-mono text-sm text-white outline-none focus:border-emerald-300" /></label></div>
          <div className="mt-4 divide-y divide-border/70 rounded-lg border border-border/70">{catalog.map((entry) => { const mode = actionMode(entry.action, autoActions, approvalActions); return <div key={entry.action} className="grid gap-3 px-3 py-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center"><div className="min-w-0"><p className="text-sm font-medium text-slate-100">{entry.label || labelForAction(entry.action)}</p><p className="mt-1 text-xs leading-5 text-slate-500">{entry.detail || 'Bounded Resident Steward action.'}</p><p className="mt-1 font-mono text-[10px] text-slate-600">{entry.action}</p></div><div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label={`${entry.label || entry.action} policy`}>
            {(['AUTO', 'APPROVAL', 'DISABLED'] as const).map((option) => <button key={option} type="button" role="radio" aria-checked={mode === option} className={cn('min-h-11 rounded-lg border px-3 text-[10px] font-semibold tracking-[0.08em] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-300', mode === option ? option === 'AUTO' ? 'border-emerald-300/40 bg-emerald-300/15 text-emerald-100' : option === 'APPROVAL' ? 'border-amber-300/40 bg-amber-300/15 text-amber-100' : 'border-slate-300/35 bg-slate-300/10 text-slate-200' : 'border-border bg-[#091725] text-slate-500 hover:text-slate-200')} onClick={() => setMode(entry.action, option)}>{option}</button>)}
          </div></div> })}</div>
          <div className="mt-4 flex flex-wrap items-center justify-between gap-3"><p className="text-xs text-slate-500">Automatic: {autoActions.length} · Approval: {approvalActions.length} · Disabled: {Math.max(0, catalog.length - autoActions.length - approvalActions.length)}</p><Button className="min-h-11 bg-emerald-300 text-[#06121d] hover:bg-emerald-200" disabled={busy === 'policy'} onClick={() => void run('policy', () => onSavePolicy({ auto_actions: autoActions, approval_actions: approvalActions, max_actions_per_hour: Math.max(1, Number(maxActions) || 1) }), 'Steward policy saved.')}>{busy === 'policy' ? <Zap className="animate-pulse" /> : <Save />}{busy === 'policy' ? 'Saving…' : 'Save policy'}</Button></div>
        </section>

        <section className="rounded-xl border border-border/80 bg-[#07111d] p-4" aria-label="Steward local reasoning model">
          <div className="flex flex-wrap items-start justify-between gap-3"><div><p className="eyebrow">Local reasoning</p><p className="mt-1 text-sm font-semibold text-white">Model lifecycle</p><p className="mt-1 text-xs leading-5 text-muted-foreground">Prepare verifies the artifact and runtime profile. Start obtains a Resource Broker lease; stop releases it.</p></div><Badge variant="outline" className={cn('font-mono text-[10px] uppercase', isRunning ? 'border-emerald-300/30 text-emerald-100' : 'border-slate-300/30 text-slate-300')}>{runtimeState}</Badge></div>
          <div className="mt-4 grid min-w-0 gap-3 md:grid-cols-2 xl:grid-cols-[minmax(0,1fr)_minmax(160px,180px)_minmax(120px,150px)_minmax(120px,150px)]">
            <label className="grid min-w-0 gap-1.5 md:col-span-2 xl:col-span-1"><span className="eyebrow">GGUF model path</span><input value={modelPath} onChange={(event) => setModelPath(event.target.value)} placeholder="/var/lib/aidn/models/steward.gguf" className="min-h-11 w-full max-w-full min-w-0 rounded-lg border border-input bg-[#091725] px-3 font-mono text-xs text-white outline-none focus:border-emerald-300" /></label>
            <label className="grid min-w-0 gap-1.5"><span className="eyebrow">Execution profile</span><select value={profile} onChange={(event) => setProfile(event.target.value as typeof profile)} className="min-h-11 w-full max-w-full min-w-0 rounded-lg border border-input bg-[#091725] px-3 text-sm text-white outline-none focus:border-emerald-300"><option value="CPU_RESIDENT">CPU resident</option><option value="IGPU_RESIDENT">iGPU resident</option><option value="GPU_RESIDENT">GPU resident</option><option value="GPU_BURST">GPU burst</option></select></label>
            <label className="grid min-w-0 gap-1.5"><span className="eyebrow">RAM budget (MB)</span><input type="number" min={128} value={ramMb} onChange={(event) => setRamMb(event.target.value)} className="min-h-11 w-full max-w-full min-w-0 rounded-lg border border-input bg-[#091725] px-3 font-mono text-sm text-white outline-none focus:border-emerald-300" /></label>
            <label className="grid min-w-0 gap-1.5"><span className="eyebrow">VRAM budget (MB)</span><input type="number" min={0} value={vramMb} onChange={(event) => setVramMb(event.target.value)} className="min-h-11 w-full max-w-full min-w-0 rounded-lg border border-input bg-[#091725] px-3 font-mono text-sm text-white outline-none focus:border-emerald-300" /></label>
            <label className="grid min-w-0 gap-1.5 md:col-span-2 xl:col-span-4"><span className="eyebrow">Optional HTTPS source</span><input value={sourceUrl} onChange={(event) => setSourceUrl(event.target.value)} placeholder="https://huggingface.co/.../resolve/main/steward.gguf" className="min-h-11 w-full max-w-full min-w-0 rounded-lg border border-input bg-[#091725] px-3 font-mono text-xs text-white outline-none focus:border-emerald-300" /><span className="text-xs leading-5 text-slate-500">When supplied, Prepare downloads atomically from the configured allow-list and verifies the artifact before the runtime can start.</span></label>
          </div>
          <div className="mt-4 flex flex-wrap items-center justify-between gap-3"><div className="flex flex-wrap gap-2"><Button variant="outline" className="min-h-11 border-border bg-[#091725] text-slate-100" disabled={busy === 'prepare' || !modelPath.trim()} onClick={() => void run('prepare', () => onPrepare({ model_path: modelPath.trim(), provider_type: 'llama.cpp', profile, ram_mb: Math.max(128, Number(ramMb) || 1024), vram_mb: Math.max(0, Number(vramMb) || 0), fallback_enabled: true, readiness_timeout_seconds: 60, ...(sourceUrl.trim() ? { source_url: sourceUrl.trim(), download: true } : {}) }), sourceUrl.trim() ? 'Model downloaded, verified, and prepared.' : 'Local model prepared and verified.')}>{busy === 'prepare' ? <Zap className="animate-pulse" /> : <Check />}{busy === 'prepare' ? 'Preparing…' : sourceUrl.trim() ? 'Download & prepare' : 'Prepare model'}</Button><Button className="min-h-11 bg-emerald-300 text-[#06121d] hover:bg-emerald-200" disabled={busy === 'start' || isRunning} onClick={() => void run('start', onStart, 'Resident model started.')}>{busy === 'start' ? <Zap className="animate-pulse" /> : <Play />}{busy === 'start' ? 'Starting…' : 'Start model'}</Button><Button variant="outline" className="min-h-11 border-rose-300/25 bg-[#091725] text-rose-100" disabled={busy === 'stop' || !isRunning} onClick={() => void run('stop', onStop, 'Resident model stopped and its lease was released.')}>{busy === 'stop' ? <Zap className="animate-pulse" /> : <Square />}{busy === 'stop' ? 'Stopping…' : 'Stop model'}</Button></div><div className="flex items-center gap-2 text-xs text-slate-500"><Cpu className="size-4" />{inference?.lease_id ? `Lease ${inference.lease_id}` : 'No active lease'}<ShieldCheck className="ml-2 size-4 text-emerald-200" />Operator-controlled</div></div>
        </section>
        {feedback ? <div className={cn('min-w-0 break-words rounded-lg border px-3 py-2 text-xs leading-5', feedback.kind === 'error' ? 'border-rose-300/30 bg-rose-300/[0.06] text-rose-100' : 'border-emerald-300/25 bg-emerald-300/[0.06] text-emerald-100')} role={feedback.kind === 'error' ? 'alert' : 'status'} aria-live="polite">{feedback.message}</div> : null}
      </CardContent>
    </Card>
  )
}
