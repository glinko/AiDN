import { useState } from 'react'
import { MessageCircle, Send, Zap } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import type { ResidentInference } from '@/lib/types'
import { cn } from '@/lib/utils'

type ResidentStewardChatProps = {
  inference: ResidentInference | undefined
  onChat: (message: string) => Promise<Record<string, unknown> | undefined>
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

function text(value: unknown, fallback: string): string {
  return typeof value === 'string' && value.trim() ? value : fallback
}

export function ResidentStewardChat({ inference, onChat }: ResidentStewardChatProps) {
  const [message, setMessage] = useState('')
  const [reply, setReply] = useState('')
  const [error, setError] = useState('')
  const [sending, setSending] = useState(false)
  const runtimeState = String(inference?.state || 'NOT_CONFIGURED').toUpperCase()
  const ready = runtimeState === 'RUNNING'
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
    try {
      const response = record(await onChat(value))
      const nested = record(response.result)
      setReply(text(response.output_text ?? response.content ?? response.response ?? nested.output_text ?? nested.content, 'Модель не вернула текстовый ответ.'))
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Resident Steward не смог ответить.')
    } finally {
      setSending(false)
    }
  }

  return (
    <Card className="border-cyan-300/20 bg-cyan-300/[0.035] py-0 shadow-none">
      <CardHeader className="flex-row items-start justify-between gap-3 border-b border-cyan-300/15 px-5 py-4">
        <div className="min-w-0">
          <p className="eyebrow text-cyan-100">Local conversation</p>
          <CardTitle className="mt-1 text-lg font-semibold text-white">Ask Resident Steward</CardTitle>
          <p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">Задавайте вопросы о состоянии узла и следующих шагах. Ответы строятся на безопасном контексте установки; изменения по-прежнему требуют подтверждения оператора.</p>
        </div>
        <Badge variant="outline" className={cn('shrink-0 font-mono text-[10px] uppercase', ready ? 'border-emerald-300/30 text-emerald-100' : 'border-amber-300/35 text-amber-100')}>
          {ready ? 'RUNNING' : runtimeState}
        </Badge>
      </CardHeader>
      <CardContent className="space-y-3 p-4 sm:p-5">
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
