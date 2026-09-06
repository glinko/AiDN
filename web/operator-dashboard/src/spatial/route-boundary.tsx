import { lazy, Suspense, useEffect, useRef, useState, type ReactNode } from 'react'

import { isSpatialOperatorPreviewEnabled, isSpatialUiEnabled } from '@/lib/feature-flags'
import { detectWebGL2, isSpatialRoute, logSpatialRendererFailure, normalizeClassicHash, returnToClassicRoute, type SpatialFallbackReason, type WebGL2Capability } from '@/spatial/route'

export type SpatialRendererStatus = 'ready' | 'failed'

function FallbackSystemMenu({ onReturn }: { onReturn: () => void }) {
  const [open, setOpen] = useState(false)
  return (
    <div data-aidn-system-menu-state={open ? 'open' : 'closed'}>
      <button type="button" aria-haspopup="dialog" aria-expanded={open} data-aidn-system-menu-trigger onClick={() => setOpen((value) => !value)}>System Menu</button>
      {open ? <div role="dialog" aria-modal="true" aria-labelledby="fallback-system-menu-title"><h2 id="fallback-system-menu-title">System Menu</h2><p>Renderer unavailable. Node Status remains available as last-known evidence.</p><p>Current snapshot: UNKNOWN · cached and read-only.</p><button type="button" onClick={onReturn}>Return to Classic UI</button><button type="button" onClick={() => setOpen(false)}>Close</button></div> : null}
    </div>
  )
}

// Keep the renderer graph out of the Classic entry chunk. The dynamic import
// is evaluated only after the flag, route, and WebGL2 capability gates pass.
const LazySpatialRoute = lazy(() => import('@/spatial/spatial-route').then(({ SpatialRoute }) => ({ default: SpatialRoute })))

function fallbackCopy(reason: SpatialFallbackReason): { title: string; detail: string } {
  switch (reason) {
    case 'flag-disabled':
      return {
        title: 'Spatial UI is disabled',
        detail: 'This deployment has the Spatial surface turned off. The Classic UI remains the default operator surface.',
      }
    case 'webgl2-unavailable':
      return {
        title: 'Spatial UI needs WebGL2',
        detail: 'This browser or device does not provide WebGL2. Nothing was changed; continue in the Classic UI.',
      }
    case 'renderer-init-failed':
      return {
        title: 'Spatial renderer could not start',
        detail: 'The Spatial renderer failed during initialization. Node state and operator access are unchanged; continue in the Classic UI.',
      }
  }
}

export function SpatialFallback({ reason, onReturn }: { reason: SpatialFallbackReason; onReturn: () => void }) {
  const copy = fallbackCopy(reason)
  return (
    <main
      aria-labelledby="spatial-fallback-title"
      className="grid min-h-svh place-items-center bg-[#050c15] px-5 py-12 text-white"
      data-spatial-route-state={reason}
    >
      {reason !== 'flag-disabled' ? <div className="fixed right-4 top-4 z-50"><FallbackSystemMenu onReturn={onReturn} /></div> : null}
      <section className="w-full max-w-xl rounded-2xl border border-cyan-300/20 bg-[#0a1725] p-6 shadow-[0_18px_60px_rgba(0,0,0,0.28)] sm:p-8">
        <h1 id="spatial-fallback-title" className="mt-3 text-2xl font-semibold tracking-[-0.04em]">{copy.title}</h1>
        <p className="mt-3 text-sm leading-6 text-slate-300">{copy.detail}</p>
        <p className="mt-4 rounded-lg border border-white/10 bg-black/10 px-3 py-2 text-xs leading-5 text-cyan-100">The rollout flag controls presentation only. Existing Node authorization, Workspace data, and Classic controls are not bypassed or removed.</p>
        <button type="button" className="mt-6 min-h-11 rounded-lg bg-cyan-100 px-4 text-sm font-semibold text-[#06121d] transition hover:bg-cyan-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-200 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0a1725]" onClick={onReturn}>
          Return to Classic UI
        </button>
      </section>
    </main>
  )
}

export function SpatialRoutePlaceholder({ onReturn }: { onReturn: () => void }) {
  return (
    <main
      aria-labelledby="spatial-placeholder-title"
      className="grid min-h-svh place-items-center bg-[#eef6f8] px-5 py-12 text-slate-900"
      data-spatial-route-state="loading"
    >
      <div className="fixed right-4 top-4 z-50"><FallbackSystemMenu onReturn={onReturn} /></div>
      <section className="w-full max-w-2xl rounded-3xl border border-white/80 bg-white/75 p-6 shadow-[12px_12px_32px_rgba(98,134,148,0.15),-12px_-12px_32px_rgba(255,255,255,0.9)] backdrop-blur-xl sm:p-10">
        <h1 id="spatial-placeholder-title" className="mt-3 text-3xl font-semibold tracking-[-0.05em] sm:text-4xl">Spatial Workspace preview</h1>
        <p className="mt-4 max-w-xl text-sm leading-6 text-slate-600">The flag, route, and WebGL2 capability gate are active. The hybrid renderer surface is loading while the same Node and operator context remains in place.</p>
        <div className="mt-6 grid gap-3 text-sm sm:grid-cols-3">
          <div className="rounded-xl border border-cyan-100 bg-cyan-50/70 p-3"><p className="font-mono text-[10px] uppercase tracking-[0.12em] text-cyan-700">Route</p><p className="mt-1 font-medium">#spatial</p></div>
          <div className="rounded-xl border border-cyan-100 bg-cyan-50/70 p-3"><p className="font-mono text-[10px] uppercase tracking-[0.12em] text-cyan-700">Node context</p><p className="mt-1 font-medium">Preserved</p></div>
          <div className="rounded-xl border border-cyan-100 bg-cyan-50/70 p-3"><p className="font-mono text-[10px] uppercase tracking-[0.12em] text-cyan-700">Renderer</p><p className="mt-1 font-medium">Hybrid shell loading</p></div>
        </div>
        <button type="button" className="mt-7 min-h-11 rounded-lg border border-slate-300 bg-white px-4 text-sm font-semibold text-slate-800 transition hover:border-cyan-400 hover:text-cyan-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500 focus-visible:ring-offset-2" onClick={onReturn}>
          Return to Classic UI
        </button>
      </section>
    </main>
  )
}

export type SpatialRouteBoundaryProps = {
  classic: ReactNode
  spatial?: ReactNode
  rendererStatus?: SpatialRendererStatus
  detectCapability?: () => WebGL2Capability
}

export function SpatialRouteBoundary({ classic, spatial, rendererStatus = 'ready', detectCapability = detectWebGL2 }: SpatialRouteBoundaryProps) {
  const [spatialRoute, setSpatialRoute] = useState(() => isSpatialRoute())
  const lastClassicHash = useRef(normalizeClassicHash(typeof window === 'undefined' ? '#overview' : window.location.hash))

  useEffect(() => {
    function syncRoute() {
      if (isSpatialRoute()) {
        setSpatialRoute(true)
      } else {
        lastClassicHash.current = normalizeClassicHash(window.location.hash)
        setSpatialRoute(false)
      }
    }

    syncRoute()
    window.addEventListener('hashchange', syncRoute)
    window.addEventListener('popstate', syncRoute)
    return () => {
      window.removeEventListener('hashchange', syncRoute)
      window.removeEventListener('popstate', syncRoute)
    }
  }, [])

  useEffect(() => {
    if (spatialRoute && rendererStatus === 'failed') logSpatialRendererFailure('renderer-init-failed')
  }, [rendererStatus, spatialRoute])

  if (!spatialRoute) return <>{classic}</>

  const onReturn = () => returnToClassicRoute(lastClassicHash.current)
  if (!isSpatialUiEnabled() || !isSpatialOperatorPreviewEnabled()) return <SpatialFallback reason="flag-disabled" onReturn={onReturn} />
  const capability = detectCapability()
  if (!capability.supported) return <SpatialFallback reason="webgl2-unavailable" onReturn={onReturn} />
  if (rendererStatus === 'failed') return <SpatialFallback reason="renderer-init-failed" onReturn={onReturn} />
  if (spatial) return spatial

  return (
    <Suspense fallback={<SpatialRoutePlaceholder onReturn={onReturn} />}>
      <LazySpatialRoute onReturn={onReturn} />
    </Suspense>
  )
}
