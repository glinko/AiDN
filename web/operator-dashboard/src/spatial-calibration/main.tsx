import { Component, Suspense, memo, useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { flushSync } from 'react-dom'
import { Canvas } from '@react-three/fiber'
import { Mic, MicOff, Pause, Play, RotateCcw, Send, X, MessageSquare, RefreshCw } from 'lucide-react'
import { AgentDocumentFrame } from '@/spatial/components/AgentDocumentFrame'
import { CalibrationScene } from './Scene'
import { PRIMARY_AGENT_WELCOME, usePrimaryAgentVoice } from './primary-agent-voice'
import { interfaceId, useAgentInterface } from './agent-interface'
import { SeedChat, type OpenSeed } from './SeedChat'
import { SceneTapGesture, type SeedPoint } from './interaction-seed'
import type { WorkspaceArtifact, WorkspaceChatIntent } from '@/spatial/contracts/workspace-chat'
import type { AgentDocument } from '@/spatial/contracts/agent-document'
import type { DashboardSpatialSceneData } from '@/spatial/data/dashboard-adapter'
import './scene.css'
import './agent-frame.css'

class SceneBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  render() {
    return this.state.failed ? <div className="scene-message" role="alert">
      <p>Не удалось запустить 3D-сцену. Диалог с агентом остаётся доступен.</p>
      <button onClick={() => window.location.reload()}>Перезагрузить сцену</button>
    </div> : this.props.children
  }
}

// Transport polling and form keystrokes must not invalidate the optical scene.
const NO_WORKSPACE_ARTIFACTS: readonly WorkspaceArtifact[] = []
const NO_DOCUMENTS: AgentDocument[] = []

const SceneViewport = memo(function SceneViewport({ hidden, paused, reducedMotion, resetKey, scene, onReady, onPrimarySelect,
  workspaceArtifacts, workspaceReady, activeWorkspaceId, onEmptySelect, onWorkspaceSelect }: {
  hidden: boolean; paused: boolean; reducedMotion: boolean; resetKey: number
  scene: DashboardSpatialSceneData | null; onReady: () => void; onPrimarySelect: () => void
  workspaceArtifacts: readonly WorkspaceArtifact[]; workspaceReady: boolean; activeWorkspaceId: string | null
  onEmptySelect: (point: SeedPoint) => void; onWorkspaceSelect: (id: string, point: SeedPoint) => void
}) {
  const gesture = useRef(new SceneTapGesture())
  const canSelect = useCallback(() => gesture.current.canTap(), [])
  return <Canvas camera={{ position: [-1.05, 3.72, 11.8], fov: 33, near: 0.1, far: 180 }}
    id="spatial-scene" tabIndex={0}
    onPointerDownCapture={event => gesture.current.down(event.pointerId, event.clientX, event.clientY, event.button)}
    onPointerMoveCapture={event => gesture.current.move(event.clientX, event.clientY)}
    onPointerUpCapture={event => { gesture.current.move(event.clientX, event.clientY); gesture.current.up(event.pointerId) }}
    onPointerCancelCapture={event => gesture.current.cancel(event.pointerId)}
    onPointerMissed={event => { if (canSelect() && event.button === 0) onEmptySelect({ x: event.clientX, y: event.clientY }) }}
    dpr={1} frameloop={hidden ? 'never' : 'demand'} gl={{ antialias: true, alpha: false, powerPreference: 'high-performance' }}
    aria-label="Шар — основной агент. Нажмите, чтобы приблизиться и открыть диалог. Перетаскивайте сцену; используйте щипок или колесо для приближения."
    fallback={<div className="scene-message" role="alert">3D недоступно. Используйте диалог с агентом.</div>}>
    <Suspense fallback={null}>
      <CalibrationScene paused={paused} reducedMotion={reducedMotion} resetKey={resetKey} onReady={onReady}
        onPrimarySelect={onPrimarySelect} sceneData={scene} agentOnly={!scene} canSelect={canSelect}
        workspaceArtifacts={workspaceArtifacts} workspaceReady={workspaceReady} activeWorkspaceId={activeWorkspaceId} onWorkspaceSelect={onWorkspaceSelect} />
    </Suspense>
  </Canvas>
})

function App() {
  const agent = useAgentInterface()
  const sendAgent = agent.send
  const [paused, setPaused] = useState(false)
  const [reducedMotion, setReducedMotion] = useState(() => matchMedia('(prefers-reduced-motion: reduce)').matches)
  const [hidden, setHidden] = useState(document.hidden)
  const [resetKey, setResetKey] = useState(0)
  const [ready, setReady] = useState(false)
  const [frameOpen, setFrameOpen] = useState(false)
  const [seed, setSeed] = useState<OpenSeed | null>(null)
  const [archiveOpen, setArchiveOpen] = useState(false)
  const [selectedDocument, setSelectedDocument] = useState<string | null>(null)
  const [text, setText] = useState('')
  const [sending, setSending] = useState(false)
  const [sendError, setSendError] = useState<string | null>(null)
  const textInput = useRef<HTMLTextAreaElement>(null)
  const lastMessage = useRef<string | null>(null)
  const lastDocument = useRef<string | null>(null)
  const documents = agent.conversation?.interface?.documents ?? NO_DOCUMENTS
  const messages = (agent.conversation?.messages ?? []).filter(message => !message.chat && !message.request_id?.startsWith('scene-'))
  const answers = messages.filter(message => message.direction === 'AGENT')
  const latestAnswer = answers.at(-1)
  const voice = usePrimaryAgentVoice({ deliver: async value => {
    await agent.send(value)
    setFrameOpen(true)
    return 'Сообщение передано агенту. Ответ появится в этом frame.'
  } })
  const onReady = useCallback(() => setReady(true), [])
  const onEmptySelect = useCallback((point: SeedPoint) => {
    // Commit focus during the tap's user activation, including mobile keyboards.
    flushSync(() => setSeed(current => current ?? { id: interfaceId('session'), point, existing: false }))
    setFrameOpen(false)
    setArchiveOpen(false)
  }, [])
  const onWorkspaceSelect = useCallback((id: string, point: SeedPoint) => {
    flushSync(() => setSeed(current => current?.id === id ? current : { id, point, existing: true }))
    setFrameOpen(false)
    setArchiveOpen(false)
  }, [])
  const sendSeed = useCallback((value: string, chat: WorkspaceChatIntent) => sendAgent(value, undefined, chat), [sendAgent])
  const closeSeed = useCallback(() => {
    setSeed(null)
    document.getElementById('spatial-scene')?.focus({ preventScroll: true })
  }, [])
  const onPrimarySelect = useCallback(() => {
    setFrameOpen(true)
    textInput.current?.focus({ preventScroll: true })
  }, [])

  useEffect(() => {
    if (latestAnswer && latestAnswer.message_id !== lastMessage.current) {
      lastMessage.current = latestAnswer.message_id
      if (!documents.some(item => item.request_id === latestAnswer.request_id)) setSelectedDocument(null)
      setFrameOpen(true)
    }
    const latest = [...documents].sort((a, b) => a.updated_at.localeCompare(b.updated_at)).at(-1)
    const key = latest ? latest.document_id + ':' + latest.revision : null
    if (latest && key !== lastDocument.current) {
      lastDocument.current = key
      setSelectedDocument(latest.document_id)
      setFrameOpen(true)
    }
  }, [documents, latestAnswer])

  useEffect(() => {
    const query = matchMedia('(prefers-reduced-motion: reduce)')
    const motion = () => setReducedMotion(query.matches)
    const visibility = () => setHidden(document.hidden)
    query.addEventListener('change', motion)
    document.addEventListener('visibilitychange', visibility)
    return () => { query.removeEventListener('change', motion); document.removeEventListener('visibilitychange', visibility) }
  }, [])

  useEffect(() => {
    const create = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'i' && !event.altKey && !event.isComposing) {
        event.preventDefault()
        onEmptySelect({ x: innerWidth / 2, y: innerHeight / 2 })
      }
    }
    window.addEventListener('keydown', create)
    return () => window.removeEventListener('keydown', create)
  }, [onEmptySelect])

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (sending || !text.trim()) return
    setSending(true)
    setSendError(null)
    const submitted = text
    try {
      await agent.send(submitted)
      setText(current => current === submitted ? '' : current)
      setFrameOpen(true)
    } catch (cause) {
      setSendError(cause instanceof Error ? cause.message : 'Не удалось отправить сообщение. Текст сохранён.')
    } finally { setSending(false) }
  }

  const recording = voice.status === 'listening'
  const voiceBusy = voice.status === 'requesting' || voice.status === 'sending'
  const source = agent.scene?.source
  const selected = documents.find(item => item.document_id === selectedDocument)
  const secureVoiceUrl = !voice.capabilities.secureContext
    ? 'https://' + window.location.hostname + ':8767' + window.location.pathname + window.location.search : null

  return <main className="pearl-study" data-scene-ready={ready} data-scene-source={source ? 'agent' : 'waiting'} data-workspace-artifacts={agent.workspace?.artifacts.length ?? 0}>
    <h1 className="sr-only">AiDN. Пространство основного агента</h1>
    <div className="scene-source">
      <span className="scene-source__dot" aria-hidden="true" />
      <span><strong>{source ? 'Снимок от агента' : 'Ждём публикацию агента'}</strong>
        <small>{source ? source.nodeId + ' · ' + source.endpointCount + ' endpoints · ' + source.sessionCount + ' sessions' : 'Данные ноды запрашивает основной агент'}</small>
        {agent.conversation?.interface?.scene ? <small>{new Date(agent.conversation.interface.scene.observed_at).toLocaleTimeString()} · {agent.online ? 'Канал подключён' : 'Канал недоступен'}</small> : null}
      </span>
      <button type="button" aria-label="Попросить агента обновить сцену" disabled={!agent.online || sending || Boolean(agent.pending)}
        onClick={() => { void agent.send('Обнови снимок spatial-сцены через MCP и опубликуй его.').catch(() => undefined) }}><RefreshCw size={16} /></button>
    </div>
    <SceneBoundary>
      <SceneViewport hidden={hidden} paused={paused} reducedMotion={reducedMotion} resetKey={resetKey}
        scene={agent.scene} onReady={onReady} onPrimarySelect={onPrimarySelect}
        workspaceArtifacts={agent.workspace?.artifacts ?? NO_WORKSPACE_ARTIFACTS} workspaceReady={Boolean(agent.workspace)}
        activeWorkspaceId={seed?.id ?? null} onEmptySelect={onEmptySelect} onWorkspaceSelect={onWorkspaceSelect} />
      {!ready && <p className="loading" role="status">Подготавливаем свет…</p>}
    </SceneBoundary>

    {seed && <div hidden={frameOpen}><SeedChat key={seed.id} seed={seed} publication={agent.workspace} online={agent.online}
      channelError={agent.error} streaming={agent.streaming?.conversation_id === seed.id ? agent.streaming : null}
      onSend={sendSeed} onClose={closeSeed} /></div>}
    {(agent.workspace?.artifacts.length ?? 0) > 0 && <aside className="workspace-archive" hidden={Boolean(seed)} aria-label="Сохранённые диалоги">
      <button type="button" aria-expanded={archiveOpen} onClick={() => setArchiveOpen(value => !value)}>Диалоги · {agent.workspace!.artifacts.length}</button>
      {archiveOpen && <nav aria-label="Открыть сохранённый диалог">
        {[...agent.workspace!.artifacts].sort((a, b) => b.order - a.order).map(item => <button key={item.artifact.artifact_id} type="button"
          onClick={() => onWorkspaceSelect(item.artifact.session_id, { x: innerWidth / 2, y: innerHeight / 2 })}>
          <span>{item.artifact.title}</span><small>{item.artifact.turn_count} сообщений</small>
        </button>)}
      </nav>}
    </aside>}

    <section className="agent-frame" hidden={!frameOpen} aria-label="Документ основного агента">
      <header className="agent-frame__header">
        <h2>{selected?.title ?? 'Основной агент'}</h2>
        <button type="button" aria-label="Свернуть frame" onClick={() => { setFrameOpen(false); textInput.current?.focus({ preventScroll: true }) }}><X size={20} /></button>
      </header>
      {documents.length > 0 ? <nav className="agent-frame__tabs" aria-label="Документы агента">
        <button type="button" aria-pressed={selectedDocument === null} onClick={() => setSelectedDocument(null)}>Диалог</button>
        {documents.map(item => <button key={item.document_id} type="button" aria-pressed={selectedDocument === item.document_id}
          onClick={() => setSelectedDocument(item.document_id)}>{item.title}</button>)}
      </nav> : null}
      <div className="agent-frame__body">
        <div hidden={selectedDocument !== null && Boolean(selected)} className="agent-conversation" role="log" aria-label="Ответы агента">
          {!answers.length ? <p>{PRIMARY_AGENT_WELCOME} Напишите или продиктуйте, что нужно посмотреть или изменить.</p> : null}
          {messages.slice(-30).map(message => <div key={message.message_id} className="agent-conversation__message" data-direction={message.direction}>
            <strong>{message.direction === 'AGENT' ? 'Агент' : 'Вы'}</strong><p>{message.text}</p>
          </div>)}
          {agent.streaming && <div className="agent-conversation__message" data-direction="AGENT" data-streaming="true">
            <strong>Агент · отвечает…</strong><p>{agent.streaming.text || 'Обрабатывает запрос…'}</p>
          </div>}
        </div>
        {documents.map(item => <div key={item.document_id} hidden={selectedDocument !== item.document_id}>
          <AgentDocumentFrame document={item} disabled={!agent.online}
            intents={agent.conversation?.interface?.intents ?? []} messages={messages} onSubmit={agent.send} />
        </div>)}
      </div>
      <p className="agent-frame__status" role="status">{agent.error ? 'Канал недоступен. Показан последний ответ; изменения заблокированы.' : agent.streaming ? 'Ответ поступает…' : agent.pending ? 'Запрос передан агенту. Ждём ответ…' : 'Чтение и изменения ноды выполняет агент через MCP.'}</p>
    </section>

    <div className="agent-composer" hidden={Boolean(seed)}>
      <form onSubmit={event => void submit(event)}>
        <button type="button" aria-label={frameOpen ? 'Свернуть диалог' : 'Открыть диалог'} aria-expanded={frameOpen} onClick={() => setFrameOpen(value => !value)}><MessageSquare size={19} /></button>
        <label className="sr-only" htmlFor="agent-message">Сообщение основному агенту</label>
        <textarea id="agent-message" ref={textInput} rows={1} value={text} maxLength={16384} placeholder="Спросите агента…"
          onChange={event => setText(event.target.value)} onKeyDown={event => {
            if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); event.currentTarget.form?.requestSubmit() }
          }} />
        <button type="button" aria-label={recording ? 'Остановить запись' : 'Продиктовать агенту'} aria-pressed={recording}
          disabled={!agent.online || !voice.capabilities.recognition || voiceBusy || sending}
          onClick={() => recording ? voice.stopListening() : voice.startListening()}>{recording ? <MicOff size={19} /> : <Mic size={19} />}</button>
        <button className="agent-composer__send" type="submit" aria-label="Отправить агенту" disabled={!agent.online || !text.trim() || sending || recording || voiceBusy}><Send size={18} /></button>
      </form>
      <p className="agent-composer__hint" role="status">
        {sendError ?? voice.error ?? agent.error ?? (agent.streaming ? 'Ответ поступает…' : recording ? 'Слушаю… ' + voice.transcript : voiceBusy ? 'Обрабатываем голосовой ввод…' : voice.capabilities.microphone && voice.capabilities.recognition ? 'Можно говорить или писать · ответы текстом' : 'Введите сообщение · ответы текстом')}
        {secureVoiceUrl ? <a href={secureVoiceUrl}>HTTPS для микрофона</a> : null}
      </p>
    </div>
    <footer className="scene-controls">
      <span className="scene-hint--desktop">Пустой тап — диалог · Ctrl/⌘ + I · щипок — масштаб</span>
      <span className="scene-hint--mobile">Тап — диалог · щипок — масштаб</span>
      <div>
        <button aria-label={paused ? 'Продолжить движение' : 'Приостановить движение'} aria-pressed={paused} disabled={reducedMotion} onClick={() => setPaused(value => !value)}>{paused || reducedMotion ? <Play size={16} /> : <Pause size={16} />}</button>
        <button aria-label="Вернуть исходный ракурс" onClick={() => setResetKey(value => value + 1)}><RotateCcw size={16} /></button>
      </div>
    </footer>
  </main>
}

createRoot(document.getElementById('calibration-root')!).render(<App />)
