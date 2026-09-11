import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from 'react'
import { ArrowUp, Mic, MicOff, X } from 'lucide-react'
import type { WorkspaceChatIntent, WorkspacePublication } from '@/spatial/contracts/workspace-chat'
import { seedLayout, type SeedPoint, type SeedViewport } from './interaction-seed'
import { usePrimaryAgentVoice } from './primary-agent-voice'
import './seed-chat.css'

export type OpenSeed = { id: string; point: SeedPoint; existing: boolean }

function currentViewport(): SeedViewport {
  const viewport = window.visualViewport
  return { width: viewport?.width ?? window.innerWidth, height: viewport?.height ?? window.innerHeight,
    offsetTop: viewport?.offsetTop ?? 0, offsetLeft: viewport?.offsetLeft ?? 0 }
}

export function SeedChat({ seed, publication, online, channelError, onSend, onClose }: {
  seed: OpenSeed
  publication: WorkspacePublication | null
  online: boolean
  channelError: string | null
  onSend: (text: string, chat: WorkspaceChatIntent) => Promise<string>
  onClose: () => void
}) {
  const active = publication?.active?.session.session_id === seed.id ? publication.active : null
  const [text, setText] = useState('')
  const [expanded, setExpanded] = useState(seed.existing)
  const [viewport, setViewport] = useState(currentViewport)
  const [layout, setLayout] = useState(() => seedLayout(seed.point, currentViewport(), seed.existing, 0, 1, seed.existing))
  const [sending, setSending] = useState(false)
  const [sent, setSent] = useState<{ requestId: string; text: string } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const input = useRef<HTMLTextAreaElement>(null)
  const measure = useRef<HTMLSpanElement>(null)
  const log = useRef<HTMLDivElement>(null)
  const followsBottom = useRef(true)
  const hasHistory = Boolean(active || seed.existing || sent)
  const waiting = Boolean(sent && !active?.turns.some(turn => turn.role === 'agent' && turn.intent_id === sent.requestId))
    || active?.session.state === 'SUBMITTING'
  const unconfirmed = sent && !active?.turns.some(turn => turn.intent_id === sent.requestId)
  const opening = seed.existing && !active
  const voice = usePrimaryAgentVoice({ deliver: async value => {
    setText(current => (current ? current + '\n' : '') + value)
    setExpanded(true)
    input.current?.focus({ preventScroll: true })
    return 'Проверьте распознанный текст и отправьте его агенту.'
  } })
  const listening = voice.status === 'listening'
  const voiceBusy = voice.status === 'requesting' || voice.status === 'sending'

  useLayoutEffect(() => { input.current?.focus({ preventScroll: true }) }, [])
  useEffect(() => { if (!opening) input.current?.focus({ preventScroll: true }) }, [opening])
  useEffect(() => {
    if (!seed.existing) return
    let mounted = true
    void onSend('Открой сохранённый диалог.', { conversation_id: seed.id, action: 'open' }).catch(cause => {
      if (mounted) setError(cause instanceof Error ? cause.message : 'Не удалось открыть диалог. Повторите запрос.')
    })
    return () => { mounted = false }
  }, [seed.existing, seed.id, onSend])
  useEffect(() => {
    const update = () => setViewport(currentViewport())
    window.addEventListener('resize', update)
    window.visualViewport?.addEventListener('resize', update)
    window.visualViewport?.addEventListener('scroll', update)
    return () => {
      window.removeEventListener('resize', update)
      window.visualViewport?.removeEventListener('resize', update)
      window.visualViewport?.removeEventListener('scroll', update)
    }
  }, [])

  useLayoutEffect(() => {
    const width = measure.current?.getBoundingClientRect().width ?? 0
    const next = seedLayout(seed.point, viewport, expanded, width, 1, hasHistory)
    if (input.current && expanded) {
      input.current.style.width = `${Math.max(24, next.width - 40)}px`
      input.current.style.height = '0px'
      const textHeight = Math.max(24, input.current.scrollHeight)
      Object.assign(next, seedLayout(seed.point, viewport, expanded, width, Math.ceil(textHeight / 24), hasHistory))
      input.current.style.height = `${Math.min(textHeight, hasHistory ? Math.max(24, next.height * 0.3) : Math.max(24, next.height - 112))}px`
    }
    setLayout(next)
  }, [text, expanded, hasHistory, seed.point, viewport])

  useEffect(() => {
    if (followsBottom.current && log.current) log.current.scrollTop = log.current.scrollHeight
  }, [active?.turns.length, unconfirmed])

  async function submit() {
    if (!text.trim() || sending || waiting || opening || !online || listening || voiceBusy) return
    const submitted = text
    setSending(true)
    setError(null)
    try {
      const requestId = await onSend(submitted, { conversation_id: seed.id, action: 'message' })
      setSent({ requestId, text: submitted })
      setText(current => current === submitted ? '' : current)
      setExpanded(true)
      followsBottom.current = true
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Не удалось отправить. Текст сохранён — попробуйте ещё раз.')
    } finally { setSending(false); input.current?.focus({ preventScroll: true }) }
  }

  const status = error ?? voice.error ?? channelError ?? (listening ? 'Слушаю… ' + voice.transcript
    : opening ? 'Агент открывает сохранённый диалог…'
      : waiting ? 'Передано агенту · ожидаем ответ…'
        : hasHistory ? 'Сохранено в кубе · можно продолжить здесь'
          : 'Enter — новая строка · Ctrl/⌘ + Enter — отправить')

  return <section className="seed-chat" style={layout as CSSProperties} data-expanded={expanded} data-phase={listening ? 'listening' : waiting ? 'thinking' : hasHistory ? 'conversation' : 'input'}
    aria-label="Диалог в пространстве" onKeyDown={event => {
      if (event.key === 'Escape' && !event.nativeEvent.isComposing) { event.stopPropagation(); onClose() }
    }}>
    <span className="seed-chat__trace" aria-hidden="true">
      <svg viewBox="0 0 72 72"><path d="M 26 4 A 33 33 0 1 1 16 10" /></svg>
    </span>
    <header className="seed-chat__toolbar">
      <button className="seed-chat__voice" type="button" aria-label={listening ? 'Остановить диктовку' : 'Диктовать в этот диалог'} aria-pressed={listening}
        disabled={!online || !voice.capabilities.recognition || voiceBusy || sending || Boolean(waiting) || opening}
        onClick={() => listening ? voice.stopListening() : voice.startListening()}><MicToggle listening={listening} /></button>
      <button className="seed-chat__send" type="submit" form={'seed-form-' + seed.id} aria-label="Отправить в этот диалог"
        disabled={!online || !text.trim() || sending || Boolean(waiting) || opening || listening || voiceBusy}><ArrowUp size={20} /></button>
      <button className="seed-chat__close" type="button" aria-label="Свернуть этот диалог" onClick={onClose}><X size={18} /></button>
      <h2 className={expanded ? 'seed-chat__title' : 'sr-only'}>{active?.session.title ?? 'Новый диалог'}</h2>
    </header>
    {hasHistory && <div ref={log} className="seed-chat__log" role="log" tabIndex={0} aria-label="Переписка этой сессии" aria-live="polite" aria-relevant="additions"
      onScroll={event => { const element = event.currentTarget; followsBottom.current = element.scrollHeight - element.scrollTop - element.clientHeight < 48 }}>
      {active?.turns.map(turn => <article className="seed-chat__turn" key={turn.turn_id} data-role={turn.role}>
        <strong>{turn.role === 'operator' ? 'Вы' : turn.role === 'agent' ? 'Агент' : 'Система'}</strong><p>{turn.text}</p>
      </article>)}
      {unconfirmed && <article className="seed-chat__turn" data-role="operator" data-unconfirmed="true"><strong>Вы · передано агенту</strong><p>{sent.text}</p></article>}
      {opening && error && <button type="button" onClick={() => {
        setError(null)
        void onSend('Открой сохранённый диалог.', { conversation_id: seed.id, action: 'open' }).catch(cause => setError(cause instanceof Error ? cause.message : 'Не удалось открыть диалог.'))
      }}>Повторить открытие</button>}
    </div>}
    <form id={'seed-form-' + seed.id} className="seed-chat__composer" onSubmit={event => { event.preventDefault(); void submit() }}>
      <label className="sr-only" htmlFor={'seed-input-' + seed.id}>Сообщение в пространстве</label>
      <textarea id={'seed-input-' + seed.id} ref={input} rows={1} value={text} maxLength={16384}
        disabled={opening} placeholder={expanded ? hasHistory ? 'Продолжить диалог…' : 'Что хотите обсудить?' : ''}
        onChange={event => { setText(event.target.value); if (event.target.value) setExpanded(true) }}
        onKeyDown={event => {
          if (event.key === 'Enter' && (event.ctrlKey || event.metaKey) && !event.nativeEvent.isComposing) {
            event.preventDefault(); void submit()
          }
        }} />
    </form>
    <span ref={measure} className="seed-chat__measure" aria-hidden="true">{text || ' '}</span>
    <p className={expanded ? 'seed-chat__status' : 'sr-only'} role="status">{status}</p>
  </section>
}

function MicToggle({ listening }: { listening: boolean }) {
  return listening ? <MicOff size={18} /> : <Mic size={18} />
}
