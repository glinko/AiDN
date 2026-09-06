import type { SpatialViewport } from '@/spatial/workspace/viewport'

import type { SpatialEntity } from './entities'

export type SpatialCameraState = {
  x: number
  y: number
  zoom: number
  focusId: string | null
  transitionToken: number
}

export const spatialCameraBounds = {
  minX: -4.5,
  maxX: 4.5,
  minY: -3,
  maxY: 3,
  minZoom: 0.72,
  maxZoom: 1.55,
} as const

export const HOME_CAMERA: SpatialCameraState = {
  x: 0,
  y: 0.5,
  zoom: 1,
  focusId: null,
  transitionToken: 0,
}

/** Stable local command ID used by the visible Primary Agent focus affordance. */
export const FOCUS_PRIMARY_AGENT = 'primary-agent' as const

const primaryAgentFocusTarget: SpatialEntity = {
  id: FOCUS_PRIMARY_AGENT,
  kind: 'subagent',
  label: 'Primary Agent',
  description: 'Primary Agent focus target.',
  position: { x: 0, y: 0.42, z: 0 },
  priority: 1,
}

export function clampSpatialCamera(state: SpatialCameraState): SpatialCameraState {
  return {
    ...state,
    x: Math.min(spatialCameraBounds.maxX, Math.max(spatialCameraBounds.minX, state.x)),
    y: Math.min(spatialCameraBounds.maxY, Math.max(spatialCameraBounds.minY, state.y)),
    zoom: Math.min(spatialCameraBounds.maxZoom, Math.max(spatialCameraBounds.minZoom, state.zoom)),
  }
}

export function homeSpatialCamera(current: SpatialCameraState): SpatialCameraState {
  return { ...HOME_CAMERA, transitionToken: current.transitionToken + 1 }
}

export function focusSpatialEntity(current: SpatialCameraState, entity: SpatialEntity): SpatialCameraState {
  return clampSpatialCamera({
    x: entity.position.x,
    y: entity.position.y,
    zoom: 1.28,
    focusId: entity.id,
    transitionToken: current.transitionToken + 1,
  })
}

export function focusPrimaryAgent(current: SpatialCameraState): SpatialCameraState {
  return focusSpatialEntity(current, primaryAgentFocusTarget)
}

export function returnFromSpatialFocus(current: SpatialCameraState): SpatialCameraState {
  return { ...current, ...HOME_CAMERA, transitionToken: current.transitionToken + 1 }
}

export function zoomSpatialCamera(current: SpatialCameraState, delta: number): SpatialCameraState {
  return clampSpatialCamera({
    ...current,
    zoom: current.zoom + delta,
    transitionToken: current.transitionToken + 1,
  })
}

export function panSpatialCamera(current: SpatialCameraState, deltaX: number, deltaY: number): SpatialCameraState {
  return clampSpatialCamera({
    ...current,
    x: current.x + deltaX / Math.max(current.zoom, 0.1),
    y: current.y + deltaY / Math.max(current.zoom, 0.1),
    focusId: null,
    transitionToken: current.transitionToken + 1,
  })
}

export function rotateSpatialCamera(current: SpatialCameraState, deltaX: number, deltaY: number): SpatialCameraState {
  return panSpatialCamera(current, deltaX * 0.7, deltaY * 0.7)
}

export function cameraForViewport(state: SpatialCameraState, viewport: Pick<SpatialViewport, 'width' | 'height'>): SpatialCameraState {
  if (viewport.width === 0 || viewport.height === 0) return state
  const aspect = viewport.width / viewport.height
  const xLimit = aspect < 1 ? spatialCameraBounds.maxX * 0.72 : spatialCameraBounds.maxX
  return {
    ...state,
    x: Math.min(xLimit, Math.max(-xLimit, state.x)),
  }
}

export function cameraTransitionDuration(prefersReducedMotion: boolean): number {
  return prefersReducedMotion ? 0 : 220
}
