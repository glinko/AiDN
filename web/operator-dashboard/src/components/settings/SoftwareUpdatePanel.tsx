import { useCallback, useEffect, useState } from 'react'
import { CheckCircle2, CircleAlert, Download, RefreshCw, ShieldCheck } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { DashboardApiError, dashboardApi, type SoftwareUpdatePayload } from '@/lib/api'

type SoftwareUpdatePanelProps = {
  enabled: boolean
  sessionActive: boolean
}

function shortHash(value: string | null) {
  return value ? `${value.slice(0, 12)}…${value.slice(-8)}` : '—'
}

function checkedAt(value: string | null) {
  if (!value) return 'not checked yet'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? 'not checked yet' : date.toLocaleString()
}

function statusLabel(status: string) {
  switch (status) {
    case 'up_to_date': return 'Up to date'
    case 'available': return 'Update available'
    case 'updating': return 'Installing'
    case 'restart_scheduled': return 'Restarting'
    case 'updated': return 'Updated'
    case 'error': return 'Needs attention'
    case 'unavailable': return 'Bootstrap required'
    default: return 'Ready to check'
  }
}

function statusClass(status: string) {
  if (status === 'available') return 'border-cyan-300/50 bg-cyan-50 text-cyan-800'
  if (status === 'updating' || status === 'restart_scheduled') return 'border-amber-300/60 bg-amber-50 text-amber-800'
  if (status === 'error') return 'border-rose-300/60 bg-rose-50 text-rose-800'
  if (status === 'up_to_date' || status === 'updated') return 'border-emerald-300/60 bg-emerald-50 text-emerald-800'
  return 'border-border bg-muted text-muted-foreground'
}

function updateError(error: unknown) {
  if (error instanceof DashboardApiError) return error.message
  return error instanceof Error ? error.message : 'The software update request did not complete.'
}

export function SoftwareUpdatePanel({ enabled, sessionActive }: SoftwareUpdatePanelProps) {
  const [update, setUpdate] = useState<SoftwareUpdatePayload | null>(null)
  const [busy, setBusy] = useState<'load' | 'check' | 'apply' | null>(null)
  const [confirmApply, setConfirmApply] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async (quiet = false) => {
    if (!enabled || !sessionActive) return
    if (!quiet) setBusy('load')
    try {
      const result = await dashboardApi.softwareUpdate()
      if (result) setUpdate(result)
      setError(null)
    } catch (reason) {
      if (!quiet) setError(updateError(reason))
    } finally {
      if (!quiet) setBusy(null)
    }
  }, [enabled, sessionActive])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    if (!update || (update.status !== 'updating' && update.status !== 'restart_scheduled')) return
    const timer = window.setInterval(() => {
      void load(true)
    }, 2500)
    return () => window.clearInterval(timer)
  }, [load, update])

  const check = useCallback(async () => {
    setBusy('check')
    setError(null)
    setConfirmApply(false)
    try {
      const result = await dashboardApi.checkSoftwareUpdate()
      if (result) setUpdate(result)
    } catch (reason) {
      setError(updateError(reason))
    } finally {
      setBusy(null)
    }
  }, [])

  const apply = useCallback(async () => {
    if (!update?.available_commit) return
    setBusy('apply')
    setError(null)
    try {
      const result = await dashboardApi.applySoftwareUpdate(update.available_commit)
      if (result) setUpdate(result)
      setConfirmApply(false)
    } catch (reason) {
      setError(updateError(reason))
    } finally {
      setBusy(null)
    }
  }, [update])

  if (!enabled) {
    return (
      <Card className="border-border/80 bg-card py-0 shadow-none">
        <CardContent className="flex gap-3 p-5">
          <ShieldCheck className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
          <div><p className="font-medium">Software updates</p><p className="mt-1 text-xs leading-5 text-muted-foreground">Updates are available after this node is started by the supported operator bootstrap.</p></div>
        </CardContent>
      </Card>
    )
  }

  if (!sessionActive) {
    return (
      <Card className="border-border/80 bg-card py-0 shadow-none">
        <CardContent className="flex gap-3 p-5">
          <ShieldCheck className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
          <div><p className="font-medium">Software updates</p><p className="mt-1 text-xs leading-5 text-muted-foreground">Pair this browser with the one-time terminal code before checking or installing a software update.</p></div>
        </CardContent>
      </Card>
    )
  }

  const status = update?.status ?? 'idle'
  const canApply = status === 'available' && Boolean(update?.available_commit) && busy === null
  const isRestarting = status === 'updating' || status === 'restart_scheduled'

  return (
    <Card className="border-border/80 bg-card py-0 shadow-none">
      <CardHeader className="border-b border-border/70 px-5 py-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="eyebrow">Software lifecycle</p>
            <CardTitle className="mt-1 text-lg font-semibold">Software updates</CardTitle>
            <p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">Check the configured AiDN release ref, review the exact commit, then install it with one explicit confirmation. The operator TOML, wallet and model data remain outside the code update.</p>
          </div>
          <span className={`inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-medium ${statusClass(status)}`}>{statusLabel(status)}</span>
        </div>
      </CardHeader>
      <CardContent className="space-y-4 p-5">
        <div className="grid gap-3 sm:grid-cols-3">
          <div className="rounded-lg border border-border/70 bg-muted/40 p-3"><p className="eyebrow">Current commit</p><p className="mt-1 break-all font-mono text-xs text-foreground">{shortHash(update?.current_commit ?? null)}</p></div>
          <div className="rounded-lg border border-border/70 bg-muted/40 p-3"><p className="eyebrow">Reviewed target</p><p className="mt-1 break-all font-mono text-xs text-foreground">{shortHash(update?.available_commit ?? null)}</p></div>
          <div className="rounded-lg border border-border/70 bg-muted/40 p-3"><p className="eyebrow">Release ref</p><p className="mt-1 break-all font-mono text-xs text-foreground">{update?.target_ref || '—'}</p></div>
        </div>
        <p className="text-xs leading-5 text-muted-foreground">Last checked: {checkedAt(update?.checked_at ?? null)}. The node fetches only the fixed HTTPS repository configured by the bootstrap.</p>
        {update?.message ? <div className="flex gap-2 rounded-lg border border-emerald-300/50 bg-emerald-50 p-3 text-xs leading-5 text-emerald-800"><CheckCircle2 className="mt-0.5 size-4 shrink-0" /><span>{update.message}</span></div> : null}
        {update?.error || error ? <div className="flex gap-2 rounded-lg border border-rose-300/60 bg-rose-50 p-3 text-xs leading-5 text-rose-800"><CircleAlert className="mt-0.5 size-4 shrink-0" /><span>{error || update?.error}</span></div> : null}
        {isRestarting ? <div className="rounded-lg border border-amber-300/60 bg-amber-50 p-3 text-xs leading-5 text-amber-800">The update is being applied in the background. The Dashboard may reconnect after the Hypervisor restarts; keep this tab open and refresh if needed.</div> : null}
        {confirmApply && canApply ? <div className="rounded-lg border border-amber-300/60 bg-amber-50 p-4"><p className="text-sm font-semibold text-amber-900">Install this reviewed commit?</p><p className="mt-1 text-xs leading-5 text-amber-800">The service will rebuild its environment and Dashboard assets, then restart. Unsaved checkout changes are rejected; generated assets are rebuilt.</p><div className="mt-3 flex flex-wrap gap-2"><Button className="bg-amber-600 text-white hover:bg-amber-700" disabled={busy !== null} onClick={() => void apply()}>{busy === 'apply' ? <RefreshCw className="animate-spin" /> : <Download />}{busy === 'apply' ? 'Installing…' : 'Install reviewed update'}</Button><Button variant="ghost" disabled={busy !== null} onClick={() => setConfirmApply(false)}>Cancel</Button></div></div> : null}
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border/70 pt-4"><p className="text-xs text-muted-foreground">Updates never accept commands or paths from the browser.</p><div className="flex flex-wrap gap-2"><Button variant="outline" className="border-border" disabled={busy !== null || isRestarting} onClick={() => void check()}>{busy === 'check' ? <RefreshCw className="animate-spin" /> : <RefreshCw />}{busy === 'check' ? 'Checking…' : 'Check for updates'}</Button>{canApply && !confirmApply ? <Button className="bg-cyan-600 text-white hover:bg-cyan-700" onClick={() => setConfirmApply(true)}><Download />Review install</Button> : null}</div></div>
      </CardContent>
    </Card>
  )
}
