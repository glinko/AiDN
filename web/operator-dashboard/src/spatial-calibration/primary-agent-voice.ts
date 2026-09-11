import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { dashboardApi } from '@/lib/api'
import type { AgentConversation } from '@/lib/types'

export const PRIMARY_AGENT_WELCOME = 'Привет! Чем займёмся сегодня?'

const DELIVERY_ACK = 'Сообщение отправлено основному агенту. Ответ пока не пришёл.'
const DEFAULT_POLL_INTERVAL_MS = 500
const DEFAULT_REPLY_TIMEOUT_MS = 45_000

type SpeechRecognitionAlternativeLike = { transcript?: string; confidence?: number }
type SpeechRecognitionResultLike = {
  isFinal: boolean
  0?: SpeechRecognitionAlternativeLike
}
type SpeechRecognitionResultsLike = {
  length: number
  [index: number]: SpeechRecognitionResultLike
}
type SpeechRecognitionEventLike = Event & { results: SpeechRecognitionResultsLike }
type SpeechRecognitionErrorEventLike = Event & { error?: string; message?: string }

type SpeechRecognitionLike = {
  lang: string
  interimResults: boolean
  continuous: boolean
  maxAlternatives: number
  start: () => void
  stop: () => void
  abort: () => void
  onresult: ((event: SpeechRecognitionEventLike) => void) | null
  onend: (() => void) | null
  onerror: ((event: SpeechRecognitionErrorEventLike) => void) | null
}

type SpeechRecognitionConstructor = new () => SpeechRecognitionLike

declare global {
  interface Window {
    SpeechRecognition?: SpeechRecognitionConstructor
    webkitSpeechRecognition?: SpeechRecognitionConstructor
  }
}

export type VoiceCapabilities = {
  recognition: boolean
  synthesis: boolean
  secureContext: boolean
  microphone: boolean
}

export type PrimaryAgentVoiceStatus = 'idle' | 'requesting' | 'listening' | 'sending' | 'unsupported' | 'error'

export type PrimaryAgentVoice = {
  capabilities: VoiceCapabilities
  status: PrimaryAgentVoiceStatus
  transcript: string
  response: string
  error: string | null
  startListening: () => void
  stopListening: () => void
  submit: (text: string) => Promise<void>
}

export function detectVoiceCapabilities(): VoiceCapabilities {
  if (typeof window === 'undefined') return { recognition: false, synthesis: false, secureContext: false, microphone: false }
  const secureContext = window.isSecureContext === true
  return {
    recognition: typeof window.SpeechRecognition === 'function' || typeof window.webkitSpeechRecognition === 'function',
    synthesis: typeof window.speechSynthesis !== 'undefined' && typeof window.SpeechSynthesisUtterance === 'function',
    secureContext,
    microphone: secureContext && typeof navigator.mediaDevices?.getUserMedia === 'function',
  }
}

function getSpeechRecognitionConstructor(): SpeechRecognitionConstructor | undefined {
  if (typeof window === 'undefined') return undefined
  return window.SpeechRecognition ?? window.webkitSpeechRecognition
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

function nonEmptyText(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null
}

/** Extract only explicit assistant-shaped fields; never speak an arbitrary API payload. */
export function extractAgentReply(value: unknown, depth = 0): string | null {
  if (depth > 3) return null
  const record = asRecord(value)
  for (const key of ['output_text', 'response_text', 'assistant_text', 'agent_reply', 'reply', 'answer']) {
    const text = nonEmptyText(record[key])
    if (text) return text
  }

  const role = String(record.role ?? record.sender ?? record.direction ?? '').toLowerCase()
  if (role === 'assistant' || role === 'agent' || role === 'ai' || role === 'agent_reply') {
    const text = nonEmptyText(record.text ?? record.content ?? record.message)
    if (text) return text
  }

  for (const key of ['result', 'data', 'response', 'payload']) {
    const nested = record[key]
    if (nested && typeof nested === 'object') {
      const text = extractAgentReply(nested, depth + 1)
      if (text) return text
    }
  }
  return null
}

export function extractLatestAgentReply(
  conversation: AgentConversation | null | undefined,
  knownMessageIds: ReadonlySet<string> = new Set(),
  requestStartedAt?: number,
): string | null {
  if (!conversation) return null
  for (const message of [...conversation.messages].reverse()) {
    if (message.direction !== 'AGENT' || !message.text.trim()) continue
    if (message.message_id && knownMessageIds.has(message.message_id)) continue
    if (requestStartedAt !== undefined) {
      const createdAt = Date.parse(message.created_at)
      if (Number.isFinite(createdAt) && createdAt < requestStartedAt - 1_500) continue
    }
    return message.text.trim()
  }
  return null
}

type VoiceDeliveryOptions = {
  readConversation?: () => Promise<AgentConversation>
  sendMessage?: (text: string) => Promise<unknown>
  sleep?: (milliseconds: number) => Promise<void>
  now?: () => number
  pollIntervalMs?: number
  replyTimeoutMs?: number
}

/** Send speech through the same durable channel used by the operator dashboard. */
export async function deliverVoiceMessage(text: string, options: VoiceDeliveryOptions = {}): Promise<string | null> {
  const normalized = text.trim()
  if (!normalized) throw new Error('Не удалось распознать голосовое сообщение.')

  const readConversation = options.readConversation ?? (() => dashboardApi.agentConversation())
  const sendMessage = options.sendMessage ?? ((value: string) => dashboardApi.sendAgentConversationMessage(value))
  const sleep = options.sleep ?? ((milliseconds: number) => new Promise<void>((resolve) => window.setTimeout(resolve, milliseconds)))
  const now = options.now ?? (() => Date.now())
  const pollIntervalMs = Math.max(150, options.pollIntervalMs ?? DEFAULT_POLL_INTERVAL_MS)
  const replyTimeoutMs = Math.max(pollIntervalMs, options.replyTimeoutMs ?? DEFAULT_REPLY_TIMEOUT_MS)

  const before = await readConversation()
  if (!before.connected) throw new Error('Основной агент сейчас не подключён к voice channel.')
  const knownMessageIds = new Set(before.messages.map((message) => message.message_id).filter(Boolean))
  const requestStartedAt = now()
  const directResponse = extractAgentReply(await sendMessage(normalized))
  if (directResponse) return directResponse

  const deadline = requestStartedAt + replyTimeoutMs
  while (now() < deadline) {
    await sleep(Math.min(pollIntervalMs, Math.max(0, deadline - now())))
    const reply = extractLatestAgentReply(await readConversation(), knownMessageIds, requestStartedAt)
    if (reply) return reply
  }
  return null
}

export function usePrimaryAgentVoice(options: { deliver?: (text: string) => Promise<string | null> } = {}): PrimaryAgentVoice {
  const [capabilities] = useState<VoiceCapabilities>(detectVoiceCapabilities)
  const [status, setStatus] = useState<PrimaryAgentVoiceStatus>(capabilities.recognition ? 'idle' : 'unsupported')
  const [transcript, setTranscript] = useState('')
  const [response, setResponse] = useState('')
  const [error, setError] = useState<string | null>(null)
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null)
  const submittedTranscriptRef = useRef<string | null>(null)
  const mountedRef = useRef(true)
  const submitRef = useRef<(text: string) => Promise<void>>(() => Promise.resolve())
  const deliveryRef = useRef(options.deliver)
  deliveryRef.current = options.deliver
  const submit = useCallback(async (text: string) => {
    const normalized = text.trim()
    if (!normalized || !mountedRef.current) return
    setTranscript(normalized)
    setError(null)
    setStatus('sending')
    try {
      const reply = await (deliveryRef.current ?? deliverVoiceMessage)(normalized)
      if (!mountedRef.current) return
      setResponse(reply ?? DELIVERY_ACK)
      setStatus('idle')
    } catch (cause) {
      if (!mountedRef.current) return
      setStatus('error')
      setError(cause instanceof Error ? cause.message : 'Не удалось отправить голосовое сообщение.')
    }
  }, [])
  submitRef.current = submit

  useEffect(() => {
    mountedRef.current = true
    const Constructor = capabilities.recognition ? getSpeechRecognitionConstructor() : undefined
    if (!Constructor) return () => { mountedRef.current = false }

    const recognition = new Constructor()
    recognition.lang = 'ru-RU'
    recognition.interimResults = true
    recognition.continuous = false
    recognition.maxAlternatives = 1
    recognition.onresult = (event) => {
      const fragments: string[] = []
      for (let index = 0; index < event.results.length; index += 1) {
        const fragment = event.results[index]?.[0]?.transcript?.trim()
        if (fragment) fragments.push(fragment)
      }
      const nextTranscript = fragments.join(' ').replace(/\s+/g, ' ').trim()
      if (!nextTranscript) return
      setTranscript(nextTranscript)
      const lastResult = event.results[event.results.length - 1]
      if (lastResult?.isFinal && submittedTranscriptRef.current !== nextTranscript) {
        submittedTranscriptRef.current = nextTranscript
        setStatus('sending')
        recognition.stop()
        void submitRef.current(nextTranscript)
      }
    }
    recognition.onend = () => {
      setStatus((current) => current === 'listening' ? 'idle' : current)
    }
    recognition.onerror = (event) => {
      if (event.error === 'aborted') return
      if (event.error === 'no-speech') {
        setStatus('idle')
        setError('Я не услышал сообщение. Попробуйте ещё раз.')
        return
      }
      setStatus('error')
      setError(event.error === 'not-allowed' ? 'Разрешите доступ к микрофону для голосового диалога.' : 'Голосовой ввод завершился с ошибкой.')
    }
    recognitionRef.current = recognition
    return () => {
      mountedRef.current = false
      recognition.abort()
      recognitionRef.current = null
    }
  }, [capabilities.recognition])

  const startListening = useCallback(() => {
    const recognition = recognitionRef.current
    if (!recognition || !capabilities.recognition) {
      setStatus('unsupported')
      setError('Голосовой ввод недоступен в этом браузере.')
      return
    }
    if (status === 'requesting' || status === 'listening' || status === 'sending') return
    setError(null)
    setTranscript('')
    submittedTranscriptRef.current = null

    if (!capabilities.secureContext || !capabilities.microphone) {
      setStatus('error')
      setError('Chrome блокирует микрофон на HTTP. Откройте эту страницу по HTTPS и разрешите доступ к микрофону.')
      return
    }

    setStatus('requesting')
    const permission = navigator.mediaDevices.getUserMedia({ audio: true })
    permission.then((stream) => stream.getTracks().forEach((track) => track.stop())).catch(() => {
      if (mountedRef.current) {
        try { recognition.abort() } catch { /* recognition may already have ended */ }
        setStatus('error')
        setError('Разрешите доступ к микрофону для голосового диалога.')
      }
    })
    try {
      recognition.start()
      setStatus('listening')
    } catch {
      setStatus('error')
      setError('Не удалось включить микрофон. Нажмите кнопку ещё раз.')
    }
  }, [capabilities.microphone, capabilities.recognition, capabilities.secureContext, status])

  const stopListening = useCallback(() => {
    const recognition = recognitionRef.current
    if (!recognition || status !== 'listening') return
    const pendingTranscript = transcript.trim()
    try { recognition.stop() } catch { /* recognition may already have ended */ }
    if (pendingTranscript && submittedTranscriptRef.current !== pendingTranscript) {
      submittedTranscriptRef.current = pendingTranscript
      setStatus('sending')
      void submit(pendingTranscript)
    } else {
      setStatus('idle')
    }
  }, [status, submit, transcript])

  return useMemo(() => ({
    capabilities,
    status,
    transcript,
    response,
    error,
    startListening,
    stopListening,
    submit,
  }), [capabilities, error, response, startListening, status, stopListening, submit, transcript])
}
