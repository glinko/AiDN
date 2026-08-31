import { useCallback, useEffect, useMemo, useState } from 'react'
import { BookOpenText, Check, RefreshCw, Save, ShieldCheck } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { dashboardApi, type DashboardRecord } from '@/lib/api'
import { cn } from '@/lib/utils'

type PromptState = {
  text: string
  sha256: string | null
  path: string | null
  maxChars: number
}

type Feedback = {
  kind: 'success' | 'error'
  message: string
}

function textValue(record: DashboardRecord | undefined, key: string): string | null {
  const value = record?.[key]
  return typeof value === 'string' && value.trim() ? value : null
}

function promptState(payload: DashboardRecord | undefined): PromptState {
  return {
    text: textValue(payload, 'text') || '',
    sha256: textValue(payload, 'sha256'),
    path: textValue(payload, 'path'),
    maxChars: typeof payload?.max_chars === 'number' ? payload.max_chars : 24_000,
  }
}

function fileName(path: string | null): string {
  if (!path) return 'steward-prompt.md'
  return path.split(/[\\/]/).filter(Boolean).at(-1) || 'steward-prompt.md'
}

export function StewardPromptEditor() {
  const [loaded, setLoaded] = useState<PromptState | null>(null)
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState<'load' | 'save' | null>('load')
  const [feedback, setFeedback] = useState<Feedback | null>(null)

  const load = useCallback(async () => {
    setBusy('load')
    setFeedback(null)
    try {
      const next = promptState(await dashboardApi.stewardPrompt())
      setLoaded(next)
      setDraft(next.text)
    } catch (error) {
      setFeedback({
        kind: 'error',
        message: error instanceof Error ? error.message : 'Steward briefing could not be loaded.',
      })
    } finally {
      setBusy(null)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  const dirty = Boolean(loaded && draft !== loaded.text)
  const remaining = Math.max(0, (loaded?.maxChars ?? 24_000) - draft.length)
  const fingerprint = useMemo(() => loaded?.sha256?.replace('sha256:', '').slice(0, 12) || 'not loaded', [loaded?.sha256])

  async function save() {
    if (!loaded || !draft.trim()) return
    setBusy('save')
    setFeedback(null)
    try {
      const next = promptState(await dashboardApi.updateStewardPrompt(draft, loaded.sha256))
      setLoaded(next)
      setDraft(next.text)
      setFeedback({ kind: 'success', message: 'Steward briefing saved. The next message uses this version immediately.' })
    } catch (error) {
      setFeedback({
        kind: 'error',
        message: error instanceof Error ? error.message : 'Steward briefing could not be saved.',
      })
    } finally {
      setBusy(null)
    }
  }

  return (
    <Card className="border-cyan-300/20 bg-cyan-300/[0.025] py-0 shadow-none">
      <CardHeader className="flex-row items-start justify-between gap-3 border-b border-border/70 px-5 py-4">
        <div className="min-w-0">
          <CardTitle className="flex items-center gap-2 text-lg font-semibold text-white"><BookOpenText className="size-5 text-cyan-200" />What Steward knows</CardTitle>
          <p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">This local operating brief tells Steward how AiDN fits together and how to explain the observed node. It is applied to the next chat request without restarting the model.</p>
        </div>
        <Button variant="outline" size="sm" className="min-h-11 shrink-0 border-cyan-300/25 bg-[#091725] text-cyan-100" onClick={() => void load()} disabled={busy !== null}><RefreshCw className={cn(busy === 'load' && 'animate-spin')} />Reload</Button>
      </CardHeader>
      <CardContent className="space-y-4 p-4 sm:p-5">
        <div className="rounded-xl border border-cyan-300/15 bg-cyan-300/[0.045] px-3 py-3 text-xs leading-5 text-cyan-100/85">
          You can change terminology, explanations and response style here. Private keys, arbitrary shell access, tool allow-lists and the action policy stay enforced by the Hypervisor and cannot be overridden by this file.
        </div>
        <label className="grid gap-2">
          <span className="flex flex-wrap items-center justify-between gap-2"><span className="text-sm font-medium text-slate-100">Operating brief</span><span className="font-mono text-[10px] text-slate-500">{fileName(loaded?.path || null)} · revision {fingerprint}</span></span>
          <textarea value={draft} onChange={(event) => setDraft(event.target.value)} disabled={busy === 'load'} spellCheck={false} className="min-h-96 w-full resize-y rounded-xl border border-input bg-[#07111d] px-4 py-3 font-mono text-xs leading-6 text-slate-100 outline-none placeholder:text-slate-600 focus:border-cyan-300 disabled:cursor-wait disabled:opacity-60" aria-describedby="steward-prompt-hint" />
        </label>
        <div className="flex flex-wrap items-center justify-between gap-3" id="steward-prompt-hint">
          <p className={cn('text-xs', remaining < 500 ? 'text-amber-100' : 'text-slate-500')}>{draft.length.toLocaleString()} characters · {remaining.toLocaleString()} remaining</p>
          <Button className="min-h-11 bg-cyan-300 text-[#06121d] hover:bg-cyan-200" disabled={busy !== null || !dirty || !draft.trim() || remaining < 0} onClick={() => void save()}>{busy === 'save' ? <RefreshCw className="animate-spin" /> : <Save />}{busy === 'save' ? 'Saving…' : dirty ? 'Save briefing' : 'Saved'}</Button>
        </div>
        {feedback ? <div className={cn('flex items-start gap-2 rounded-lg border px-3 py-2 text-xs leading-5', feedback.kind === 'error' ? 'border-rose-300/30 bg-rose-300/[0.06] text-rose-100' : 'border-emerald-300/25 bg-emerald-300/[0.06] text-emerald-100')} role={feedback.kind === 'error' ? 'alert' : 'status'} aria-live="polite">{feedback.kind === 'success' ? <Check className="mt-0.5 size-4 shrink-0" /> : <ShieldCheck className="mt-0.5 size-4 shrink-0" />}{feedback.message}</div> : null}
      </CardContent>
    </Card>
  )
}
