import { Component, Suspense, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { Canvas } from '@react-three/fiber'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Mic, MicOff, Pause, Play, RotateCcw, Volume2 } from 'lucide-react'
import {
  createDashboardSpatialLoaders,
  createDashboardSpatialScene,
  useSpatialWorkspaceData,
} from '@/spatial/data'
import { CalibrationScene } from './Scene'
import { PRIMARY_AGENT_WELCOME, usePrimaryAgentVoice } from './primary-agent-voice'
import './scene.css'

const spatialCalibrationQueryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: false, refetchOnWindowFocus: false },
  },
})

const LIVE_SPATIAL_SCOPE = {
  hypervisor_id: 'local-hypervisor',
  node_id: import.meta.env.VITE_AIDN_NODE_ID ?? 'gpu-3090',
} as const
const SECURE_VOICE_PORT = '8767'

const dashboardSpatialLoaders = createDashboardSpatialLoaders()

class SceneBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  render() {
    return this.state.failed ? <div className="scene-message" role="alert">
      <p>Не удалось запустить 3D-сцену.</p>
      <p>Проверьте поддержку WebGL 2 и аппаратное ускорение браузера.</p>
      <button onClick={() => window.location.reload()}>Повторить</button>
    </div> : this.props.children
  }
}

function AppContent() {
  const [paused, setPaused] = useState(false)
  const [reducedMotion, setReducedMotion] = useState(() => matchMedia('(prefers-reduced-motion: reduce)').matches)
  const [hidden, setHidden] = useState(document.hidden)
  const [resetKey, setResetKey] = useState(0)
  const [ready, setReady] = useState(false)
  const voice = usePrimaryAgentVoice()
  const speak = voice.speak
  const lastWelcomeAt = useRef(0)
  const onReady = useCallback(() => setReady(true), [])
  const onPrimarySelect = useCallback(() => {
    const now = Date.now()
    if (now - lastWelcomeAt.current < 2_500) return
    lastWelcomeAt.current = now
    speak(PRIMARY_AGENT_WELCOME)
  }, [speak])
  const workspaceData = useSpatialWorkspaceData({
    scope: LIVE_SPATIAL_SCOPE,
    mode: 'remote',
    profile: 'desktop',
    workspaceLoader: dashboardSpatialLoaders.workspace,
    statusLoader: dashboardSpatialLoaders.status,
    pollIntervalMs: 15_000,
  })
  const sceneData = useMemo(() => workspaceData.snapshot
    ? createDashboardSpatialScene(workspaceData.snapshot, workspaceData.status, {
      state: workspaceData.state === 'partial' || workspaceData.status?.partial ? 'partial' : 'live',
    })
    : null, [workspaceData.snapshot, workspaceData.state, workspaceData.status])
  const sourceLabel = sceneData
    ? `NODE ${sceneData.source.nodeId} · ${sceneData.source.state === 'partial' ? 'PARTIAL' : 'LIVE'}`
    : workspaceData.isLoading
      ? 'NODE · LOADING'
      : 'DEMO FALLBACK'
  const sourceDetail = sceneData
    ? `${sceneData.source.endpointCount} endpoints · ${sceneData.source.sessionCount} sessions · ${sceneData.source.bundleCount} bundles`
    : workspaceData.error
      ? 'Live read-model unavailable'
      : 'Preparing live read-model'
  const voiceLabel = voice.status === 'listening'
    ? 'Слушаю…'
    : voice.status === 'requesting'
      ? 'Запрашиваю доступ…'
    : voice.status === 'sending'
      ? 'Отправляю…'
      : voice.status === 'speaking'
        ? 'Говорю…'
        : voice.status === 'unsupported'
          ? 'Голос недоступен'
          : 'Голосовой диалог'
  const voiceHint = voice.error
    ?? (voice.status === 'listening'
      ? 'Говорите, я передам сообщение основному агенту.'
      : voice.status === 'requesting'
        ? 'Подтвердите доступ к микрофону в окне Chrome.'
      : voice.status === 'sending'
        ? voice.transcript
        : voice.status === 'speaking'
          ? voice.response
          : voice.capabilities.recognition
            ? voice.response
              ? `Последний ответ: ${voice.response}`
              : voice.capabilities.microphone
                ? 'Нажмите микрофон и обратитесь к основному агенту.'
                : 'Голосовой ввод требует HTTPS; текущий адрес HTTP не даёт Chrome запросить микрофон.'
            : 'Нажмите на шар агента, чтобы услышать приветствие.')
  const secureVoiceUrl = !voice.capabilities.secureContext && typeof window !== 'undefined'
    ? `https://${window.location.hostname}:${SECURE_VOICE_PORT}${window.location.pathname}${window.location.search}`
    : null
  useEffect(() => {
    const query = matchMedia('(prefers-reduced-motion: reduce)')
    const motion = () => setReducedMotion(query.matches)
    const visibility = () => setHidden(document.hidden)
    query.addEventListener('change', motion)
    document.addEventListener('visibilitychange', visibility)
    return () => { query.removeEventListener('change', motion); document.removeEventListener('visibilitychange', visibility) }
  }, [])
  return <main className="pearl-study" data-scene-ready={ready} data-scene-source={sceneData ? 'live' : 'demo'}>
    <h1 className="sr-only">AiDN. Пространственный граф основного агента, субагентов, артефактов и эндпоинтов</h1>
    <div className="scene-source" aria-live="polite">
      <span className="scene-source__dot" aria-hidden="true" />
      <span><strong>{sourceLabel}</strong><small>{sourceDetail}</small></span>
    </div>
    <SceneBoundary>
      <Canvas camera={{ position: [-1.05, 3.72, 11.8], fov: 33, near: 0.1, far: 180 }}
        dpr={1} frameloop={hidden ? 'never' : 'demand'}
        gl={{ antialias: true, alpha: false, powerPreference: 'high-performance' }}
        aria-label="Шар — основной агент; доступные субагенты отображаются цветными шарами; сессии и bundles — стеклянными кубами; endpoints — маленькими солнцами с коронами. Нажмите агент, чтобы приблизиться и услышать приветствие; меняйте ракурс перетаскиванием."
        fallback={<div className="scene-message" role="alert">Для этой сцены нужен браузер с поддержкой WebGL 2.</div>}>
        <Suspense fallback={null}>
          <CalibrationScene paused={paused} reducedMotion={reducedMotion} resetKey={resetKey} onReady={onReady} onPrimarySelect={onPrimarySelect} sceneData={sceneData} />
        </Suspense>
      </Canvas>
      {(!ready || workspaceData.isLoading) && <p className="loading" role="status">{workspaceData.isLoading ? 'Подключаем конфигурацию ноды…' : 'Подготавливаем свет…'}</p>}
    </SceneBoundary>
    <section className="voice-console" data-voice-state={voice.status} aria-label="Голосовой диалог с основным агентом">
      <button className="voice-console__button" type="button" aria-label={voice.status === 'listening' ? 'Остановить запись' : 'Начать голосовой диалог'}
        aria-pressed={voice.status === 'listening' || voice.status === 'requesting'} disabled={!voice.capabilities.recognition || voice.status === 'requesting' || voice.status === 'sending' || voice.status === 'speaking'}
        onClick={() => voice.status === 'listening' ? voice.stopListening() : voice.startListening()}>
        {voice.status === 'listening' ? <MicOff size={17} /> : voice.status === 'speaking' ? <Volume2 size={17} /> : <Mic size={17} />}
        <span>{voiceLabel}</span>
      </button>
      <p className="voice-console__status" role="status" aria-live="polite">
        <span>{voiceHint}</span>
        {secureVoiceUrl ? <a className="voice-console__secure-link" href={secureVoiceUrl}>Открыть HTTPS</a> : null}
      </p>
    </section>
    <footer className="scene-controls">
      <span>Перетащите · щипок/колесо · нажмите объект</span>
      <div>
        <button aria-label={paused ? 'Продолжить движение' : 'Приостановить движение'}
          aria-pressed={paused} disabled={reducedMotion} onClick={() => setPaused(value => !value)}>
          {paused || reducedMotion ? <Play size={16} /> : <Pause size={16} />}
        </button>
        <button aria-label="Вернуть исходный ракурс" onClick={() => setResetKey(value => value + 1)}><RotateCcw size={16} /></button>
      </div>
    </footer>
  </main>
}

function App() {
  return <QueryClientProvider client={spatialCalibrationQueryClient}><AppContent /></QueryClientProvider>
}

createRoot(document.getElementById('calibration-root')!).render(<App />)
