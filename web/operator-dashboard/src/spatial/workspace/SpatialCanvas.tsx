import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent, type WheelEvent as ReactWheelEvent } from 'react'

import { Canvas } from '@react-three/fiber'

import { spatialTokens } from '@/spatial/theme/tokens'

import {
  spatialAtmosphere,
  spatialEnvironmentProfile,
  type SpatialQualityProfile,
} from '../prototype/environment'
import { HOME_CAMERA, rotateSpatialCamera, zoomSpatialCamera, type SpatialCameraState } from '../prototype/camera'
import { spatialEntities, spatialEntityLod, spatialRelations, type SpatialEntity, type SpatialRelation } from '../prototype/entities'
import { SpatialEntityScene } from '../prototype/SpatialEntityScene'
import { SpatialEnvironment } from '../prototype/SpatialEnvironment'
import { SpatialOrbitControls, WorkspaceCamera } from '../prototype/SpatialCameraRig'
import { primaryAgentAccentColor, primaryAgentVisual, type PrimaryAgentState } from '../prototype/primary-agent'
import { SpatialPrimaryAgent } from '../prototype/SpatialPrimaryAgent'
import type { PrimaryAgentPresenceViewModel } from '../data/primary-agent-presence'

import type { SpatialViewport } from './viewport'

export type SpatialCanvasProps = {
  viewport: SpatialViewport
  selectedNodeId: string | null
  onNodeSelect: (nodeId: string) => void
  onEmptySpace?: () => void
  onEntitySelect?: (entityId: string) => void
  qualityProfile?: SpatialQualityProfile
  primaryAgentState?: PrimaryAgentState
  primaryAgentPresence?: PrimaryAgentPresenceViewModel
  prefersReducedMotion?: boolean
  cameraState?: SpatialCameraState
  onCameraChange?: (state: SpatialCameraState) => void
  simulateRendererError?: boolean
  entities?: readonly SpatialEntity[]
  relations?: readonly SpatialRelation[]
  workspaceDataState?: 'loading' | 'ready' | 'partial' | 'stale' | 'offline' | 'empty' | 'error'
}

function hasUsableWebGL2(): boolean {
  if (typeof document === 'undefined') return false

  try {
    const canvas = document.createElement('canvas')
    const context = canvas.getContext('webgl2') as WebGL2RenderingContext | null
    return Boolean(context && typeof context.getParameter === 'function')
  } catch {
    return false
  }
}

function screenPosition(
  position: SpatialEntity['position'],
  camera: SpatialCameraState,
  width: number,
  height: number,
) {
  const scale = Math.min(width, height) / 8 * camera.zoom
  return {
    x: width * 0.5 + (position.x - camera.x) * scale,
    y: height * 0.42 - (position.y - camera.y) * scale,
    scale,
  }
}

function drawSpatialEnvironment(context: CanvasRenderingContext2D, width: number, height: number, profile: SpatialQualityProfile) {
  context.fillStyle = spatialAtmosphere.background
  context.fillRect(0, 0, width, height)

  const sky = context.createLinearGradient(0, 0, 0, height * 0.72)
  sky.addColorStop(0, '#fbfdff')
  sky.addColorStop(0.78, spatialAtmosphere.background)
  sky.addColorStop(1, spatialAtmosphere.horizon)
  context.fillStyle = sky
  context.fillRect(0, 0, width, height * 0.72)

  const ground = context.createLinearGradient(0, height * 0.58, 0, height)
  ground.addColorStop(0, 'rgba(230, 238, 246, 0.18)')
  ground.addColorStop(1, spatialAtmosphere.ground)
  context.fillStyle = ground
  context.fillRect(0, height * 0.58, width, height * 0.42)

  context.beginPath()
  context.moveTo(0, height * 0.58)
  context.quadraticCurveTo(width * 0.5, height * (profile === 'high' ? 0.55 : 0.57), width, height * 0.58)
  context.strokeStyle = 'rgba(146, 171, 198, 0.18)'
  context.lineWidth = 1
  context.stroke()
}

function drawPrimaryAgent(
  context: CanvasRenderingContext2D,
  state: PrimaryAgentState,
  profile: SpatialQualityProfile,
  camera: SpatialCameraState,
  width: number,
  height: number,
  presence?: PrimaryAgentPresenceViewModel,
) {
  const visual = primaryAgentVisual(state, profile)
  const point = screenPosition({ x: 0, y: 0.42, z: 0 }, camera, width, height)
  const accent = primaryAgentAccentColor(state)
  const radius = Math.min(width, height) * (profile === 'mobile' || profile === 'low' ? 0.075 : 0.09)
  const halo = context.createRadialGradient(point.x, point.y, 5, point.x, point.y, radius * 2.8)
  halo.addColorStop(0, `${accent}55`)
  halo.addColorStop(1, `${accent}00`)
  context.fillStyle = halo
  context.fillRect(point.x - radius * 3, point.y - radius * 3, radius * 6, radius * 6)

  context.beginPath()
  context.arc(point.x, point.y, radius, 0, Math.PI * 2)
  context.fillStyle = state === 'OFFLINE' ? '#b7c1cf' : '#f7fbff'
  context.shadowColor = 'rgba(73, 92, 120, 0.2)'
  context.shadowBlur = 22
  context.shadowOffsetX = 8
  context.shadowOffsetY = 10
  context.fill()
  context.shadowColor = 'transparent'

  context.beginPath()
  context.arc(point.x, point.y, radius * (visual.channel === 'core' ? 0.52 : 0.42), 0, Math.PI * 2)
  context.fillStyle = `${accent}${state === 'OFFLINE' ? '35' : 'bb'}`
  context.fill()

  context.beginPath()
  context.arc(point.x, point.y, radius * 1.24, 0, Math.PI * 2)
  context.strokeStyle = `${accent}${state === 'OFFLINE' ? '70' : 'aa'}`
  context.lineWidth = 2
  if (state === 'OFFLINE') context.setLineDash([5, 7])
  context.stroke()
  context.setLineDash([])

  if (presence?.attention.visible) {
    context.beginPath()
    context.arc(point.x, point.y, radius * 1.58, 0, Math.PI * 2)
    context.strokeStyle = `${presence.attention.color}${presence.attention.severity === 'CRITICAL' ? 'dd' : 'aa'}`
    context.lineWidth = presence.attention.severity === 'CRITICAL' ? 3 : 2
    context.setLineDash(presence.attention.severity === 'CRITICAL' ? [3, 4] : [2, 6])
    context.stroke()
    context.setLineDash([])
  }
}

function drawSemanticThread(context: CanvasRenderingContext2D, source: SpatialEntity, target: SpatialEntity, camera: SpatialCameraState, width: number, height: number) {
  const from = screenPosition(source.position, camera, width, height)
  const to = screenPosition(target.position, camera, width, height)
  context.beginPath()
  context.moveTo(from.x, from.y)
  context.lineTo(to.x, to.y)
  context.strokeStyle = 'rgba(157, 182, 213, 0.38)'
  context.lineWidth = 1
  context.stroke()
}

function drawEntity(context: CanvasRenderingContext2D, entity: SpatialEntity, selected: boolean, camera: SpatialCameraState, profile: SpatialQualityProfile, width: number, height: number) {
  const point = screenPosition(entity.position, camera, width, height)
  const lod = spatialEntityLod(Math.sqrt(entity.position.x ** 2 + entity.position.y ** 2 + Math.abs(entity.position.z)), profile)
  const distanceOpacity = Math.max(0.32, Math.min(1, 1 - Math.abs(entity.position.z) / 12))
  const radius = (entity.kind === 'attention' ? 9 : entity.kind === 'artifact' ? 8 : 7) * (selected ? 1.35 : 1)
  const color = entity.kind === 'subagent'
    ? spatialTokens.color.accent.violet
    : entity.kind === 'endpoint'
      ? spatialTokens.color.accent.cyan
      : entity.kind === 'service'
        ? spatialTokens.color.accent.blue
        : entity.kind === 'session'
          ? spatialTokens.color.accent.violet
      : entity.kind === 'artifact'
        ? spatialTokens.color.accent.peach
        : spatialTokens.color.state.attention

  context.save()
  context.globalAlpha = distanceOpacity * (lod === 'LOD0' ? 0.55 : 1)
  context.fillStyle = selected ? '#ffffff' : color
  context.strokeStyle = selected ? color : `${color}aa`
  context.lineWidth = selected ? 2 : 1

  if (entity.kind === 'artifact') {
    context.fillRect(point.x - radius, point.y - radius * 0.68, radius * 2, radius * 1.35)
    context.strokeRect(point.x - radius, point.y - radius * 0.68, radius * 2, radius * 1.35)
  } else if (entity.kind === 'service') {
    context.fillRect(point.x - radius * 0.72, point.y - radius, radius * 1.44, radius * 2)
    context.strokeRect(point.x - radius * 0.72, point.y - radius, radius * 1.44, radius * 2)
  } else if (entity.kind === 'session') {
    context.beginPath()
    context.moveTo(point.x, point.y - radius)
    context.lineTo(point.x + radius, point.y)
    context.lineTo(point.x, point.y + radius)
    context.lineTo(point.x - radius, point.y)
    context.closePath()
    context.fill()
    context.stroke()
  } else if (entity.kind === 'attention') {
    context.beginPath()
    context.moveTo(point.x, point.y - radius)
    context.lineTo(point.x + radius, point.y + radius)
    context.lineTo(point.x - radius, point.y + radius)
    context.closePath()
    context.fill()
    context.stroke()
  } else {
    context.beginPath()
    context.arc(point.x, point.y, radius, 0, Math.PI * 2)
    context.fill()
    context.stroke()
  }

  if (selected) {
    context.beginPath()
    context.arc(point.x, point.y, radius * 1.8, 0, Math.PI * 2)
    context.strokeStyle = `${color}80`
    context.lineWidth = 1
    context.stroke()
  }
  context.restore()
}

function pickEntityAt(
  event: { clientX: number; clientY: number },
  canvas: HTMLCanvasElement,
  camera: SpatialCameraState,
  width: number,
  height: number,
  entities: readonly SpatialEntity[],
): string | null {
  if (event.clientX === 0 && event.clientY === 0) return 'mock-agent'
  const rect = canvas.getBoundingClientRect()
  const x = event.clientX - rect.left
  const y = event.clientY - rect.top
  const candidates = entities.map((entity) => {
    const point = screenPosition(entity.position, camera, width, height)
    return { entity, distance: Math.hypot(point.x - x, point.y - y) }
  })
  const closest = candidates.sort((left, right) => left.distance - right.distance)[0]
  return closest && closest.distance < 48 ? closest.entity.id : null
}

function FallbackCanvas({
  viewport,
  selectedNodeId,
  onNodeSelect,
  onEmptySpace,
  onEntitySelect,
  qualityProfile,
  primaryAgentState,
  primaryAgentPresence,
  cameraState,
  onCameraChange,
  entities = spatialEntities,
  relations = spatialRelations,
}: Required<Pick<SpatialCanvasProps, 'viewport' | 'selectedNodeId' | 'onNodeSelect'>> & Omit<SpatialCanvasProps, 'viewport' | 'selectedNodeId' | 'onNodeSelect' | 'simulateRendererError'>) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const pointerRef = useRef<{ x: number; y: number; moved: boolean } | null>(null)
  const profile = qualityProfile ?? 'desktop'
  const agentState = primaryAgentState ?? 'READY'
  const camera = cameraState ?? HOME_CAMERA

  useEffect(() => {
    const canvas = canvasRef.current
    const context = canvas?.getContext('2d')
    if (!canvas || !context) return

    const width = Math.max(viewport.width, 1)
    const height = Math.max(viewport.height, 1)
    const dpr = viewport.dpr
    canvas.width = Math.round(width * dpr)
    canvas.height = Math.round(height * dpr)
    context.setTransform(dpr, 0, 0, dpr, 0, 0)
    context.clearRect(0, 0, width, height)
    drawSpatialEnvironment(context, width, height, profile)

    for (const relation of relations) {
      const source = entities.find((entity) => entity.id === relation.sourceId)
      const target = entities.find((entity) => entity.id === relation.targetId)
      if (source && target) drawSemanticThread(context, source, target, camera, width, height)
    }

    drawPrimaryAgent(context, agentState, profile, camera, width, height, primaryAgentPresence)
    for (const entity of entities) {
      drawEntity(context, entity, selectedNodeId === entity.id, camera, profile, width, height)
    }
  }, [agentState, camera, entities, primaryAgentPresence, profile, relations, selectedNodeId, viewport])

  const handlePointerDown = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    pointerRef.current = { x: event.clientX, y: event.clientY, moved: false }
    event.currentTarget.setPointerCapture?.(event.pointerId)
  }

  const handlePointerMove = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    const pointer = pointerRef.current
    if (!pointer || event.buttons === 0) return
    const deltaX = event.clientX - pointer.x
    const deltaY = event.clientY - pointer.y
    if (Math.abs(deltaX) + Math.abs(deltaY) > 3) pointer.moved = true
    if (pointer.moved) onCameraChange?.(rotateSpatialCamera(camera, -deltaX / 120, deltaY / 120))
    pointer.x = event.clientX
    pointer.y = event.clientY
  }

  const handlePointerUp = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    event.currentTarget.releasePointerCapture?.(event.pointerId)
    pointerRef.current = null
  }

  const handleClick = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current
    if (!canvas) return
    const id = pickEntityAt(event, canvas, camera, Math.max(viewport.width, 1), Math.max(viewport.height, 1), entities)
    if (!id) {
      onEmptySpace?.()
      return
    }
    onNodeSelect(id)
    onEntitySelect?.(id)
  }

  const handleWheel = (event: ReactWheelEvent<HTMLCanvasElement>) => {
    onCameraChange?.(zoomSpatialCamera(camera, event.deltaY > 0 ? -0.06 : 0.06))
  }

  return (
    <canvas
      ref={canvasRef}
      className="aidn-spatial-canvas"
      data-aidn-canvas-renderer="2d-fallback"
      data-aidn-canvas-profile={profile}
      data-aidn-canvas-atmosphere="white-studio"
      aria-hidden="true"
      tabIndex={-1}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onClick={handleClick}
      onWheel={handleWheel}
    />
  )
}

export function SpatialCanvas({
  viewport,
  selectedNodeId,
  onNodeSelect,
  onEmptySpace,
  onEntitySelect,
  qualityProfile = 'desktop',
  primaryAgentState = 'READY',
  primaryAgentPresence,
  prefersReducedMotion = false,
  cameraState = HOME_CAMERA,
  onCameraChange,
  entities = spatialEntities,
  relations = spatialRelations,
  simulateRendererError = false,
  workspaceDataState = 'ready',
}: SpatialCanvasProps) {
  if (simulateRendererError) throw new Error('Spatial renderer initialization failed')

  const [mode, setMode] = useState<'loading' | 'webgl' | 'fallback'>('loading')
  const environment = spatialEnvironmentProfile(qualityProfile)
  const handleEntitySelect = (entityId: string) => {
    onNodeSelect(entityId)
    onEntitySelect?.(entityId)
  }

  useEffect(() => {
    setMode(hasUsableWebGL2() ? 'webgl' : 'fallback')
  }, [])

  return (
    <div
      className="aidn-spatial-canvas-shell"
      data-aidn-canvas-state={mode}
      data-aidn-canvas-dpr={Math.min(viewport.dpr, environment.dprCap)}
      data-aidn-canvas-orientation={viewport.orientation}
      data-aidn-canvas-quality={qualityProfile}
      data-aidn-canvas-atmosphere="white-studio"
      data-aidn-canvas-fog={`${environment.fogNear}-${environment.fogFar}`}
      data-aidn-canvas-hidden-animation={prefersReducedMotion ? 'paused' : 'demand'}
      data-aidn-canvas-data-state={workspaceDataState}
    >
      {mode === 'loading' ? (
        <div className="aidn-spatial-canvas-status" role="status" aria-live="polite">Preparing spatial canvas…</div>
      ) : workspaceDataState === 'loading' ? (
        <div className="aidn-spatial-canvas-status" role="status" aria-live="polite">Loading Node Workspace snapshot…</div>
      ) : workspaceDataState === 'error' ? (
        <div className="aidn-spatial-canvas-status" role="status" aria-live="polite">Spatial data recovery is available in the DOM controls.</div>
      ) : mode === 'webgl' ? (
        <Canvas
          className="aidn-spatial-canvas"
          data-aidn-canvas-renderer="webgl2"
          data-aidn-canvas-profile={qualityProfile}
          data-aidn-canvas-atmosphere="white-studio"
          aria-hidden="true"
          tabIndex={-1}
          frameloop="demand"
          dpr={Math.min(viewport.dpr, environment.dprCap)}
          camera={{ position: [0, 0.6, 4.5], fov: 44 }}
          gl={{ antialias: true, alpha: true }}
          onCreated={({ gl }) => {
            gl.setClearColor(spatialAtmosphere.background, 1)
          }}
          onPointerMissed={onEmptySpace}
        >
          <SpatialEnvironment profile={qualityProfile} />
          <WorkspaceCamera cameraState={cameraState} />
          <SpatialOrbitControls cameraState={cameraState} onCameraChange={onCameraChange} />
          <SpatialPrimaryAgent state={primaryAgentState} profile={qualityProfile} prefersReducedMotion={prefersReducedMotion} presence={primaryAgentPresence} />
          <SpatialEntityScene
            selectedEntityId={selectedNodeId}
            onEntitySelect={handleEntitySelect}
            camera={cameraState}
            profile={qualityProfile}
            entities={entities}
            relations={relations}
          />
        </Canvas>
      ) : (
        <FallbackCanvas
          viewport={viewport}
          selectedNodeId={selectedNodeId}
          onNodeSelect={onNodeSelect}
          onEmptySpace={onEmptySpace}
          onEntitySelect={onEntitySelect}
          qualityProfile={qualityProfile}
          primaryAgentState={primaryAgentState}
          primaryAgentPresence={primaryAgentPresence}
          cameraState={cameraState}
          onCameraChange={onCameraChange}
          entities={entities}
          relations={relations}
        />
      )}
    </div>
  )
}
