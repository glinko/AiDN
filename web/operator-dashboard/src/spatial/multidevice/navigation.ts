export type MobileGestureState = 'IDLE' | 'PANNING' | 'PINCHING' | 'LONG_PRESS_PENDING' | 'SEED_READY' | 'CANCELLED'

export type MobileNavigationCommand =
  | { type: 'PAN'; dx: number; dy: number }
  | { type: 'ROTATE'; dx: number; dy: number }
  | { type: 'ZOOM'; scale: number }
  | { type: 'SELECT'; ref: string | null }
  | { type: 'SEED' }
  | { type: 'FOCUS_NEXT'; direction: 'forward' | 'backward' }
  | { type: 'HOME' }
  | { type: 'CANCEL' }

export type MobileGestureTarget = 'canvas' | 'entity' | 'form' | 'scroll' | 'button'

export type MobileNavigationState = {
  state: MobileGestureState
  startX: number
  startY: number
  lastX: number
  lastY: number
  startTime: number
  pointerCount: number
  captureScroll: boolean
  gestureMode: 'pan' | 'rotate'
}

export type MobileGestureEvent =
  | { type: 'pointerdown'; x: number; y: number; pointerCount?: number; target: MobileGestureTarget; mode?: 'pan' | 'rotate'; time?: number }
  | { type: 'pointermove'; x: number; y: number; pointerCount?: number; time?: number }
  | { type: 'pointerup'; x: number; y: number; target: MobileGestureTarget; time?: number; selectedRef?: string | null }
  | { type: 'pinch'; scale: number }
  | { type: 'cancel' }
  | { type: 'keyboard'; key: 'Home' | 'Escape' | 'ArrowLeft' | 'ArrowRight' }

export type MobileGestureResult = { state: MobileNavigationState; command?: MobileNavigationCommand }

export const MOBILE_LONG_PRESS_MS = 520
export const MOBILE_DRAG_THRESHOLD_PX = 10
export const MOBILE_SWIPE_THRESHOLD_PX = 56
export const MOBILE_TOUCH_TARGET_PX = 44

export function createMobileNavigationState(): MobileNavigationState {
  return { state: 'IDLE', startX: 0, startY: 0, lastX: 0, lastY: 0, startTime: 0, pointerCount: 0, captureScroll: false, gestureMode: 'pan' }
}

export function shouldCaptureMobileGesture(target: MobileGestureTarget, dx: number, dy: number): boolean {
  if (target === 'form' || target === 'button') return false
  if (target === 'canvas' || target === 'entity') return true
  // Let a mostly vertical swipe continue to scroll a page. Horizontal focus
  // navigation is intentionally captured only after a meaningful threshold.
  return Math.abs(dx) > MOBILE_DRAG_THRESHOLD_PX && Math.abs(dx) >= Math.abs(dy) * 1.1
}

export function handleMobileGesture(current: MobileNavigationState, event: MobileGestureEvent): MobileGestureResult {
  if (event.type === 'cancel') return { state: { ...current, state: 'CANCELLED', captureScroll: false }, command: { type: 'CANCEL' } }
  if (event.type === 'keyboard') {
    if (event.key === 'Home') return { state: { ...current, state: 'IDLE' }, command: { type: 'HOME' } }
    if (event.key === 'Escape') return { state: { ...current, state: 'CANCELLED' }, command: { type: 'CANCEL' } }
    return { state: { ...current, state: 'IDLE' }, command: { type: 'FOCUS_NEXT', direction: event.key === 'ArrowRight' ? 'forward' : 'backward' } }
  }
  if (event.type === 'pointerdown') {
    const time = event.time ?? 0
    const pointerCount = event.pointerCount ?? 1
    if (event.target === 'form' || event.target === 'button') return { state: { ...current, state: 'IDLE', pointerCount, captureScroll: false } }
    return {
      state: {
        ...current,
        state: pointerCount > 1 ? 'PINCHING' : 'LONG_PRESS_PENDING',
        startX: event.x,
        startY: event.y,
        lastX: event.x,
        lastY: event.y,
        startTime: time,
        pointerCount,
        captureScroll: pointerCount > 1 || event.target === 'canvas' || event.target === 'entity',
        gestureMode: event.mode ?? 'pan',
      },
    }
  }
  if (event.type === 'pinch') {
    return { state: { ...current, state: 'PINCHING', pointerCount: 2, captureScroll: true }, command: { type: 'ZOOM', scale: Math.max(0.1, event.scale) } }
  }
  if (event.type === 'pointermove') {
    const dx = event.x - current.startX
    const dy = event.y - current.startY
    const distance = Math.hypot(dx, dy)
    const pointerCount = event.pointerCount ?? current.pointerCount
    if (pointerCount > 1) return { state: { ...current, state: 'PINCHING', lastX: event.x, lastY: event.y, pointerCount, captureScroll: true } }
    if (!current.captureScroll || distance <= MOBILE_DRAG_THRESHOLD_PX) return { state: { ...current, lastX: event.x, lastY: event.y } }
    return { state: { ...current, state: 'PANNING', lastX: event.x, lastY: event.y, pointerCount, captureScroll: true }, command: current.gestureMode === 'rotate'
      ? { type: 'ROTATE', dx: event.x - current.lastX, dy: event.y - current.lastY }
      : { type: 'PAN', dx: event.x - current.lastX, dy: event.y - current.lastY } }
  }
  const dx = event.x - current.startX
  const dy = event.y - current.startY
  const elapsed = (event.time ?? current.startTime) - current.startTime
  if (current.state === 'LONG_PRESS_PENDING' && Math.hypot(dx, dy) < MOBILE_DRAG_THRESHOLD_PX && elapsed >= MOBILE_LONG_PRESS_MS) {
    return { state: { ...current, state: event.target === 'canvas' ? 'SEED_READY' : 'IDLE', captureScroll: false }, command: event.target === 'canvas' ? { type: 'SEED' } : { type: 'SELECT', ref: event.selectedRef ?? null } }
  }
  if (current.state === 'PANNING' || Math.hypot(dx, dy) >= MOBILE_DRAG_THRESHOLD_PX) {
    if (Math.abs(dx) >= MOBILE_SWIPE_THRESHOLD_PX && Math.abs(dx) > Math.abs(dy) * 1.2) {
      return { state: { ...current, state: 'IDLE', captureScroll: false }, command: { type: 'FOCUS_NEXT', direction: dx < 0 ? 'forward' : 'backward' } }
    }
    return { state: { ...current, state: 'IDLE', captureScroll: false }, command: { type: 'PAN', dx, dy } }
  }
  if (event.target === 'entity') return { state: { ...current, state: 'IDLE' }, command: { type: 'SELECT', ref: event.selectedRef ?? null } }
  return { state: { ...current, state: 'IDLE', captureScroll: false } }
}

export function mobileKeyboardEquivalent(key: string): MobileGestureResult {
  const normalized = key === 'Home' || key === 'Escape' || key === 'ArrowLeft' || key === 'ArrowRight' ? key : 'Escape'
  return handleMobileGesture(createMobileNavigationState(), { type: 'keyboard', key: normalized })
}
