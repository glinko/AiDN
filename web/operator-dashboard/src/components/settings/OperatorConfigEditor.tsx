import { useCallback, useEffect, useState } from 'react'
import { CheckCircle2, CircleAlert, FileCog, RefreshCw, Save, ShieldAlert } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { DashboardApiError, dashboardApi, type OperatorConfigPayload, type OperatorConfigValidation } from '@/lib/api'

type OperatorConfigEditorProps = {
  enabled: boolean
  sessionActive: boolean
}

const editorClass = 'operator-config-editor min-h-[22rem] w-full resize-y rounded-lg border border-input bg-[#050d16] px-4 py-3 font-mono text-xs leading-6 text-[#e8f7f7] outline-none transition focus:border-cyan-300 focus:ring-2 focus:ring-cyan-300/20 disabled:cursor-not-allowed disabled:opacity-60'

function shortHash(value: string | null) {
  return value ? `${value.slice(0, 12)}…${value.slice(-8)}` : 'not created yet'
}

export function OperatorConfigEditor({ enabled, sessionActive }: OperatorConfigEditorProps) {
  const [config, setConfig] = useState<OperatorConfigPayload | null>(null)
  const [draft, setDraft] = useState('')
  const [validation, setValidation] = useState<OperatorConfigValidation | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<'load' | 'validate' | 'save' | 'apply' | null>(null)
  const [confirmApply, setConfirmApply] = useState(false)

  const load = useCallback(async () => {
    if (!enabled || !sessionActive) return
    setBusy('load')
    setError(null)
    try {
      const next = await dashboardApi.operatorConfig()
      setConfig(next)
      setDraft(next.text)
      setValidation(null)
      setConfirmApply(false)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'The operator configuration could not be loaded.')
    } finally {
      setBusy(null)
    }
  }, [enabled, sessionActive])

  useEffect(() => { void load() }, [load])

  async function validate() {
    setBusy('validate')
    setError(null)
    setMessage(null)
    try {
      const result = await dashboardApi.validateOperatorConfig(draft)
      setValidation(result)
      if (result.valid) setMessage(result.changed_keys.length ? 'Profile is valid. Review the restart warning before applying.' : 'Profile is valid and matches the active revision.')
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Configuration validation failed.')
    } finally {
      setBusy(null)
    }
  }

  async function persist(apply: boolean) {
    if (!config || !draft.trim()) return
    setBusy(apply ? 'apply' : 'save')
    setError(null)
    setMessage(null)
    try {
      const result = apply
        ? await dashboardApi.applyOperatorConfig(draft, config.sha256)
        : await dashboardApi.saveOperatorConfig(draft, config.sha256)
      setConfig(result)
      setDraft(result.text)
      setValidation(null)
      setConfirmApply(false)
      setMessage(apply && result.restart_scheduled
        ? 'Configuration accepted. The Hypervisor is restarting; reconnect the Dashboard after it returns.'
        : apply
          ? 'Configuration applied.'
          : 'Draft saved. Apply it when you are ready to restart the Hypervisor.')
    } catch (cause) {
      const conflict = cause instanceof DashboardApiError
        && cause.status === 409
        && cause.message.includes('changed since it was loaded')
      setError(conflict
        ? 'This profile changed on the node while you were editing. Reload it, review the latest values, and try again.'
        : cause instanceof Error ? cause.message : 'Configuration save failed.')
      if (conflict) setConfirmApply(false)
    } finally {
      setBusy(null)
    }
  }

  if (!enabled || !sessionActive) return null

  if (busy === 'load' && !config) {
    return <Card className="border-border/80 bg-card py-0 shadow-none"><CardContent className="flex items-center gap-3 p-5 text-sm text-muted-foreground"><RefreshCw className="size-4 animate-spin" />Loading operator configuration…</CardContent></Card>
  }

  if (!config) {
    return <Card className="border-border/80 bg-card py-0 shadow-none"><CardContent className="flex flex-col gap-3 p-5"><div className="flex items-center gap-2 text-rose-100"><CircleAlert className="size-4" />Configuration profile unavailable</div><p className="text-sm leading-6 text-muted-foreground">{error ?? 'The supported bootstrap did not expose an operator-config.toml path for this process.'}</p><Button variant="outline" size="sm" className="w-fit border-border bg-[#091725]" onClick={() => void load()}><RefreshCw />Retry</Button></CardContent></Card>
  }

  const dirty = draft !== config.text
  const invalid = validation !== null && !validation.valid
  const hasChanges = Boolean(config.restart_required) || Boolean(validation?.changed_keys.length) || dirty
  const protectedCount = config.read_only_keys.length

  return (
    <Card className="border-cyan-300/20 bg-cyan-300/[0.025] py-0 shadow-none">
      <CardHeader className="border-b border-cyan-300/15 px-5 py-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <FileCog className="size-4 text-cyan-200" />
              <p className="eyebrow text-cyan-100">Operator profile</p>
              <span className="rounded-full border border-cyan-300/25 bg-cyan-300/[0.06] px-2 py-0.5 text-[10px] uppercase tracking-[0.12em] text-cyan-100">TOML</span>
              {validation?.valid ? <span className="inline-flex items-center gap-1 rounded-full border border-emerald-300/25 bg-emerald-300/[0.06] px-2 py-0.5 text-[10px] uppercase tracking-[0.12em] text-emerald-100"><CheckCircle2 className="size-3" />Valid</span> : null}
              {invalid ? <span className="inline-flex items-center gap-1 rounded-full border border-rose-300/25 bg-rose-300/[0.06] px-2 py-0.5 text-[10px] uppercase tracking-[0.12em] text-rose-100"><CircleAlert className="size-3" />Needs attention</span> : null}
            </div>
            <CardTitle className="mt-1 text-lg font-semibold">One place for node settings</CardTitle>
            <p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">Edit ports, feature flags, provider URLs, and runtime defaults as plain text. Save keeps a draft; Apply &amp; restart loads the new profile through the bootstrap wrapper.</p>
          </div>
          <Button variant="outline" size="sm" className="w-fit shrink-0 border-border bg-[#091725]" disabled={busy !== null} onClick={() => void load()}><RefreshCw className={busy === 'load' ? 'animate-spin' : ''} />Reload</Button>
        </div>
        <div className="mt-3 flex flex-col gap-1 rounded-lg border border-border/70 bg-[#07111d] px-3 py-2 font-mono text-[11px] text-slate-400 sm:flex-row sm:items-center sm:justify-between"><span className="truncate">{config.path ?? 'profile path unavailable'}</span><span className="shrink-0">sha256 {shortHash(config.sha256)}</span></div>
      </CardHeader>
      <CardContent className="space-y-4 p-5">
        {config.hidden_keys.length > 0 ? <div className="flex gap-3 rounded-lg border border-amber-300/25 bg-amber-300/[0.05] p-3 text-xs leading-5 text-amber-100"><ShieldAlert className="mt-0.5 size-4 shrink-0" /><span>Credentials stay in Secret Manager and are never shown in this editor ({config.hidden_keys.length} hidden setting{config.hidden_keys.length === 1 ? '' : 's'}). {protectedCount ? 'Bootstrap-owned paths are shown for reference and cannot be changed.' : ''}</span></div> : null}
        <label className="grid gap-2" htmlFor="operator-config-editor"><span className="eyebrow">Profile text</span><textarea id="operator-config-editor" value={draft} onChange={(event) => { setDraft(event.target.value); setValidation(null); setMessage(null) }} spellCheck={false} autoCapitalize="off" autoCorrect="off" aria-describedby="operator-config-help" className={editorClass} disabled={busy !== null} /></label>
        <p id="operator-config-help" className="text-xs leading-5 text-muted-foreground">Use the <code className="rounded bg-black/20 px-1 py-0.5 font-mono text-cyan-100">[env]</code> table and <code className="rounded bg-black/20 px-1 py-0.5 font-mono text-cyan-100">AIDN_*</code> keys. The node validates ports, URLs, protected paths, and secret boundaries before writing.</p>
        {validation && !validation.valid ? <div className="rounded-lg border border-rose-300/25 bg-rose-300/[0.05] p-3 text-xs leading-5 text-rose-100"><p className="font-medium">Fix these values before saving:</p><ul className="mt-1 list-disc space-y-1 pl-4">{validation.errors.map((item) => <li key={item}>{item}</li>)}</ul></div> : null}
        {validation?.valid && validation.warnings.length > 0 ? <div className="rounded-lg border border-amber-300/25 bg-amber-300/[0.05] p-3 text-xs leading-5 text-amber-100"><p className="font-medium">Before applying</p><ul className="mt-1 list-disc space-y-1 pl-4">{validation.warnings.map((item) => <li key={item}>{item}</li>)}</ul>{validation.changed_keys.length ? <p className="mt-2 font-mono text-[11px] text-amber-100/75">Changed: {validation.changed_keys.slice(0, 8).join(', ')}{validation.changed_keys.length > 8 ? ` +${validation.changed_keys.length - 8}` : ''}</p> : null}</div> : null}
        {error ? <div className="flex gap-2 rounded-lg border border-rose-300/25 bg-rose-300/[0.05] p-3 text-xs leading-5 text-rose-100"><CircleAlert className="mt-0.5 size-4 shrink-0" /><span>{error}</span></div> : null}
        {message ? <div className="flex gap-2 rounded-lg border border-emerald-300/25 bg-emerald-300/[0.05] p-3 text-xs leading-5 text-emerald-100"><CheckCircle2 className="mt-0.5 size-4 shrink-0" /><span>{message}</span></div> : null}
        <div className="flex flex-col gap-3 border-t border-border/70 pt-4 sm:flex-row sm:items-center sm:justify-between"><p className="text-xs text-muted-foreground">{dirty ? 'Unsaved edits' : config.status === 'missing' ? 'Profile will be created on first save' : 'Profile is in sync'}{config.restart_supported ? ' · service restart is available' : ' · restart must be handled by the host supervisor'}</p><div className="flex flex-wrap gap-2"><Button variant="outline" className="border-border bg-[#091725]" disabled={!draft.trim() || busy !== null} onClick={() => void validate()}>{busy === 'validate' ? <RefreshCw className="animate-spin" /> : <CheckCircle2 />}{busy === 'validate' ? 'Checking…' : 'Validate'}</Button><Button variant="outline" className="border-cyan-300/25 bg-[#091725] text-cyan-100" disabled={!dirty || busy !== null || invalid} onClick={() => void persist(false)}><Save />{busy === 'save' ? 'Saving…' : 'Save draft'}</Button>{confirmApply ? <><Button variant="outline" className="border-amber-300/40 bg-amber-300/[0.06] text-amber-100" disabled={busy !== null || invalid} onClick={() => void persist(true)}>{busy === 'apply' ? <RefreshCw className="animate-spin" /> : <ShieldAlert />}{busy === 'apply' ? 'Restarting…' : 'Confirm restart'}</Button><Button variant="ghost" disabled={busy !== null} onClick={() => setConfirmApply(false)}>Cancel</Button></> : <Button className="bg-amber-200 text-[#191204] hover:bg-amber-100" disabled={!hasChanges || busy !== null || invalid || !config.restart_supported} onClick={() => { if (validation?.valid !== true) { void validate(); return }; setConfirmApply(true) }}><ShieldAlert />Apply &amp; restart</Button>}</div></div>
      </CardContent>
    </Card>
  )
}
