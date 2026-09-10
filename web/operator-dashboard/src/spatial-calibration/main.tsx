import { Component, Suspense, useCallback, useEffect, useState, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { Canvas } from '@react-three/fiber'
import { Pause, Play, RotateCcw } from 'lucide-react'
import { CalibrationScene } from './Scene'
import './scene.css'

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

function App() {
  const [paused, setPaused] = useState(false)
  const [reducedMotion, setReducedMotion] = useState(() => matchMedia('(prefers-reduced-motion: reduce)').matches)
  const [hidden, setHidden] = useState(document.hidden)
  const [resetKey, setResetKey] = useState(0)
  const [ready, setReady] = useState(false)
  const onReady = useCallback(() => setReady(true), [])
  useEffect(() => {
    const query = matchMedia('(prefers-reduced-motion: reduce)')
    const motion = () => setReducedMotion(query.matches)
    const visibility = () => setHidden(document.hidden)
    query.addEventListener('change', motion)
    document.addEventListener('visibilitychange', visibility)
    return () => { query.removeEventListener('change', motion); document.removeEventListener('visibilitychange', visibility) }
  }, [])
  return <main className="pearl-study" data-scene-ready={ready}>
    <h1 className="sr-only">AiDN. Пространственный граф основного агента, субагентов, артефактов и эндпоинтов</h1>
    <SceneBoundary>
      <Canvas camera={{ position: [0.15, 3.5, 10.8], fov: 33, near: 0.1, far: 180 }}
        dpr={1} frameloop={hidden ? 'never' : 'demand'}
        gl={{ antialias: true, alpha: false, powerPreference: 'high-performance' }}
        aria-label="Шар — основной агент; шесть цветных шаров — субагенты; стеклянные кубы — кластеры артефактов; маленькие солнца с коронами — эндпоинты. Меняйте ракурс перетаскиванием, нажмите объект для приближения."
        fallback={<div className="scene-message" role="alert">Для этой сцены нужен браузер с поддержкой WebGL 2.</div>}>
        <Suspense fallback={null}>
          <CalibrationScene paused={paused} reducedMotion={reducedMotion} resetKey={resetKey} onReady={onReady} />
        </Suspense>
      </Canvas>
      {!ready && <p className="loading" role="status">Подготавливаем свет…</p>}
    </SceneBoundary>
    <footer className="scene-controls">
      <span>Перетащите · нажмите объект</span>
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

createRoot(document.getElementById('calibration-root')!).render(<App />)
