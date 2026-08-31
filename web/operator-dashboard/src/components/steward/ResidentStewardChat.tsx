import { useState } from 'react'
import { Check, MessageCircle, Send, X, Zap } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import type { ResidentInference } from '@/lib/types'
import { cn } from '@/lib/utils'

type ResidentStewardChatProps = {
  inference: ResidentInference | undefined
  onChat: (message: string) => Promise<Record<string, unknown> | undefined>
  onApproveAction: (action: string, targetId: string, planHash: string) => Promise<Record<string, unknown> | undefined>
}

type PendingAction = {
  action: string
  targetId: string
  planHash: string
  label: string
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

function text(value: unknown, fallback: string): string {
  return typeof value === 'string' && value.trim() ? value : fallback
}

function field(value: unknown, fallback = 'Не указано'): string {
  return typeof value === 'string' && value.trim() ? value : fallback
}

export function ResidentStewardChat({ inference, onChat, onApproveAction }: ResidentStewardChatProps) {
  const [message, setMessage] = useState('')
  const [reply, setReply] = useState('')
  const [error, setError] = useState('')
  const [sending, setSending] = useState(false)
  const [pendingAction, setPendingAction] = useState<PendingAction | null>(null)
  const [approving, setApproving] = useState(false)
  const runtimeState = String(inference?.state || 'NOT_CONFIGURED').toUpperCase()
  const ready = runtimeState === 'RUNNING'
  const execution = record(inference?.execution)
  const runtime = record(record(inference).runtime)
  const profile = field(execution.profile ?? inference?.profile)
  const model = field(inference?.model_path, 'Модель не настроена')
  const provider = field(inference?.provider_type)
  const lease = field(execution.resource_lease ?? inference?.lease_id, 'Нет активной аренды')
  const suggestedQuestions = [
    'Что сейчас настроено на этом узле?',
    'Какие следующие шаги по настройке рекомендуешь?',
    'Проверь состояние локальной модели и ресурсов.',
  ]

  async function submit(nextMessage?: string) {
    const value = (nextMessage ?? message).trim()
    if (!value || sending || !ready) return
    setMessage(value)
    setSending(true)
    setError('')
    setPendingAction(null)
    try {
      const response = record(await onChat(value))
      const nested = record(response.result)
      setReply(text(response.output_text ?? response.content ?? response.response ?? nested.output_text ?? nested.content, 'Модель не вернула текстовый ответ.'))
      const actionResult = record(response.steward_action)
      const plan = record(actionResult.plan)
      if (String(actionResult.status).toUpperCase() === 'APPROVAL_REQUIRED' && typeof plan.action === 'string' && typeof plan.target_id === 'string' && typeof plan.plan_hash === 'string') {
        setPendingAction({
          action: plan.action,
          targetId: plan.target_id,
          planHash: plan.plan_hash,
          label: text(plan.changes && Array.isArray(plan.changes) ? plan.changes[0] : undefined, plan.action),
        })
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Resident Steward не смог ответить.')
    } finally {
      setSending(false)
    }
  }

  async function approvePendingAction() {
    if (!pendingAction || approving) return
    setApproving(true)
    setError('')
    try {
      const result = record(await onApproveAction(pendingAction.action, pendingAction.targetId, pendingAction.planHash))
      const status = String(result.status || 'COMPLETED').replaceAll('_', ' ').toLowerCase()
      setReply('Действие ' + pendingAction.label + ' для ' + pendingAction.targetId + ': ' + status + '.')
      setPendingAction(null)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Не удалось подтвердить действие Steward.')
    } finally {
      setApproving(false)
    }
  }

  return (
    <Card className="border-cyan-300/20 bg-cyan-300/[0.035] py-0 shadow-none">
      <CardHeader className="flex-row items-start justify-between gap-3 border-b border-cyan-300/15 px-5 py-4">
        <div className="min-w-0">
          <p className="eyebrow text-cyan-100">Local conversation</p>
          <CardTitle className="mt-1 text-lg font-semibold text-white">Ask Resident Steward</CardTitle>
          <p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">Задавайте вопросы о состоянии узла и следующих шагах. Steward сам использует разрешённые инструменты; режим каждого действия задаётся выше: Auto, Ask или Deny.</p>
        </div>
        <Badge variant="outline" className={cn('shrink-0 font-mono text-[10px] uppercase', ready ? 'border-emerald-300/30 text-emerald-100' : 'border-amber-300/35 text-amber-100')}>
          {ready ? 'RUNNING' : runtimeState}
        </Badge>
      </CardHeader>
      <CardContent className="space-y-3 p-4 sm:p-5">
        <section className={cn('rounded-xl border px-4 py-3', ready ? 'border-emerald-300/25 bg-emerald-300/[0.055]' : 'border-amber-300/25 bg-amber-300/[0.055]')} aria-label="Resident Steward runtime">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <p className={cn('text-sm font-semibold', ready ? 'text-emerald-100' : 'text-amber-100')}>{ready ? 'Steward подключён и отвечает локально' : 'Steward сейчас не готов к диалогу'}</p>
              <p className="mt-1 text-xs leading-5 text-slate-400">{ready ? 'Запущенная модель и её аренда ресурсов показаны ниже. Настройка модели доступна в разделе Policy & local model.' : (inference?.last_error || 'Запустите подготовленную модель, чтобы открыть локальный диалог.')}</p>
            </div>
            <Badge variant="outline" className={cn('shrink-0 font-mono text-[10px] uppercase', ready ? 'border-emerald-300/30 text-emerald-100' : 'border-amber-300/35 text-amber-100')}>{ready ? 'ONLINE' : runtimeState}</Badge>
          </div>
          <dl className="mt-3 grid gap-x-4 gap-y-2 text-xs sm:grid-cols-2 xl:grid-cols-4">
            <div className="min-w-0"><dt className="text-slate-500">Модель</dt><dd className="mt-0.5 truncate font-mono text-slate-200" title={model}>{model}</dd></div>
            <div><dt className="text-slate-500">Профиль</dt><dd className="mt-0.5 font-medium text-slate-200">{profile.replaceAll('_', ' ')}</dd></div>
            <div><dt className="text-slate-500">Провайдер</dt><dd className="mt-0.5 font-medium text-slate-200">{provider}</dd></div>
            <div className="min-w-0"><dt className="text-slate-500">Runtime</dt><dd className="mt-0.5 truncate font-mono text-slate-200" title={field(runtime.runtime_id, lease)}>{field(runtime.runtime_id, lease)}</dd></div>
          </dl>
        </section>
        <div className="flex flex-wrap gap-2">
          {suggestedQuestions.map((question) => (
            <button key={question} type="button" disabled={!ready || sending} onClick={() => void submit(question)} className="min-h-11 rounded-lg border border-cyan-300/20 bg-[#091725] px-3 py-2 text-left text-xs font-medium text-cyan-100 transition hover:border-cyan-300/50 disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300">
              {question}
            </button>
          ))}
        </div>
        {!ready ? <p className="rounded-lg border border-amber-300/20 bg-amber-300/[0.05] px-3 py-2 text-xs leading-5 text-amber-100" role="status">
          {runtimeState === 'RESOURCE_WAIT' ? 'Модель ожидает свободных ресурсов. Уменьшите RAM/VRAM и повторите Prepare.' : inference?.last_error || 'Модель ещё не запущена. После Prepare нажмите Start model.'}
        </p> : null}
        {reply ? <div className="rounded-xl border border-cyan-300/20 bg-[#07111d] p-4" aria-live="polite"><p className="whitespace-pre-wrap break-words text-sm leading-6 text-slate-100">{reply}</p></div> : null}
        {pendingAction ? <section className="rounded-xl border border-amber-300/30 bg-amber-300/[0.055] p-4" aria-label="Steward action awaiting approval">
          <p className="text-sm font-semibold text-amber-100">Действие ожидает подтверждения</p>
          <p className="mt-1 text-xs leading-5 text-amber-100/80">{pendingAction.label} · <span className="font-mono">{pendingAction.targetId}</span></p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button type="button" size="sm" className="bg-amber-300 text-[#2a1700] hover:bg-amber-200" disabled={approving} onClick={() => void approvePendingAction()}><Check />{approving ? 'Applying…' : 'Approve & run'}</Button>
            <Button type="button" size="sm" variant="outline" className="border-amber-300/30 bg-transparent text-amber-100 hover:bg-amber-300/10" disabled={approving} onClick={() => setPendingAction(null)}><X />Dismiss</Button>
          </div>
        </section> : null}
        {error ? <div className="rounded-lg border border-rose-300/25 bg-rose-300/[0.05] px-3 py-2 text-xs leading-5 text-rose-100" role="alert">{error}</div> : null}
        <form className="flex flex-col gap-2 sm:flex-row sm:items-end" onSubmit={(event) => { event.preventDefault(); void submit() }}>
          <label className="grid min-w-0 flex-1 gap-1.5"><span className="eyebrow">Message</span><textarea value={message} onChange={(event) => setMessage(event.target.value)} rows={2} maxLength={16_384} placeholder="Например: что нужно настроить дальше?" disabled={!ready || sending} className="w-full resize-y rounded-lg border border-input bg-[#091725] px-3 py-2.5 text-sm text-white outline-none placeholder:text-slate-500 focus:border-cyan-300 disabled:cursor-not-allowed disabled:opacity-60" /></label>
          <Button type="submit" className="min-h-11 shrink-0 bg-cyan-300 text-[#06121d] hover:bg-cyan-200" disabled={!ready || !message.trim() || sending}>
            {sending ? <Zap className="animate-pulse" /> : <Send />}
            {sending ? 'Thinking…' : 'Ask Steward'}
          </Button>
        </form>
        <p className="flex items-center gap-2 text-[11px] text-slate-500"><MessageCircle className="size-3.5" />Контекст запроса не содержит приватные ключи и секреты.</p>
      </CardContent>
    </Card>
  )
}
