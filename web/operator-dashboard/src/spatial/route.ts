const SPATIAL_HASH = '#spatial'
const PREVIOUS_CLASSIC_HASH_KEY = 'aidn.dashboard.previous-classic-hash.v1'

export type WebGL2Capability = {
  supported: boolean
  reason: 'supported' | 'unavailable' | 'context-error' | 'not-browser'
}

export type SpatialFallbackReason =
  | 'flag-disabled'
  | 'webgl2-unavailable'
  | 'renderer-init-failed'

export function isSpatialRoute(hash = typeof window === 'undefined' ? '' : window.location.hash): boolean {
  return hash.split('?', 1)[0].toLowerCase() === SPATIAL_HASH
}

export function detectWebGL2(): WebGL2Capability {
  if (typeof document === 'undefined') return { supported: false, reason: 'not-browser' }

  try {
    const canvas = document.createElement('canvas')
    const context = canvas.getContext('webgl2')
    return context
      ? { supported: true, reason: 'supported' }
      : { supported: false, reason: 'unavailable' }
  } catch {
    return { supported: false, reason: 'context-error' }
  }
}

export function logSpatialRendererFailure(reason: SpatialFallbackReason): void {
  // Keep diagnostics categorical: browser/GPU details are not useful in a
  // rollout log and can expose fingerprinting data.
  console.warn('[spatial] renderer initialization failed', { reason })
}

export function normalizeClassicHash(hash: string | null | undefined): string {
  if (!hash || !hash.startsWith('#') || isSpatialRoute(hash)) return '#overview'
  return hash
}

function dispatchRouteChange(): void {
  window.dispatchEvent(new PopStateEvent('popstate'))
}

export function openSpatialRoute(): void {
  const currentHash = normalizeClassicHash(window.location.hash)
  window.sessionStorage.setItem(PREVIOUS_CLASSIC_HASH_KEY, currentHash)
  if (!isSpatialRoute()) {
    window.history.pushState({ route: 'spatial' }, '', SPATIAL_HASH)
    dispatchRouteChange()
  }
}

export function returnToClassicRoute(fallbackHash = '#overview'): void {
  const storedHash = window.sessionStorage.getItem(PREVIOUS_CLASSIC_HASH_KEY)
  const targetHash = normalizeClassicHash(storedHash ?? fallbackHash)
  window.sessionStorage.removeItem(PREVIOUS_CLASSIC_HASH_KEY)
  window.history.pushState({ route: targetHash.slice(1) }, '', targetHash)
  dispatchRouteChange()
}
