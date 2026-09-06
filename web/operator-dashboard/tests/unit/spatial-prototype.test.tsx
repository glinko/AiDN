import { describe, expect, it } from 'vitest'

import {
  HOME_CAMERA,
  FOCUS_PRIMARY_AGENT,
  PRIMARY_AGENT_STATES,
  SPATIAL_PERFORMANCE_BUDGET,
  clampSpatialCamera,
  evaluateSpatialPerformanceGate,
  focusSpatialEntity,
  focusPrimaryAgent,
  homeSpatialCamera,
  initialSpatialPerformanceMetrics,
  primaryAgentVisual,
  spatialEntities,
  spatialEntityCounts,
  spatialEntityLod,
  spatialRelations,
  updateSpatialPerformanceFrame,
  zoomSpatialCamera,
} from '@/spatial/prototype'

describe('Spatial Prototype A contracts', () => {
  it('keeps the white environment profiles bounded and deterministic', async () => {
    const { spatialEnvironmentProfiles, inferSpatialQualityProfile } = await import('@/spatial/prototype')
    for (const profile of Object.values(spatialEnvironmentProfiles)) {
      expect(profile.fogNear).toBeLessThan(profile.fogFar)
      expect(profile.dprCap).toBeGreaterThanOrEqual(1)
      expect(profile.postProcessing).toBe(false)
    }
    expect(inferSpatialQualityProfile({ width: 480, dpr: 1 })).toBe('mobile')
    expect(inferSpatialQualityProfile({ width: 1280, dpr: 1 })).toBe('desktop')
  })

  it('maps every Primary Agent state to multiple non-color channels', () => {
    expect(PRIMARY_AGENT_STATES).toEqual(['READY', 'THINKING', 'WORKING', 'OFFLINE'])
    const channels = PRIMARY_AGENT_STATES.map((state) => primaryAgentVisual(state, 'desktop'))
    expect(new Set(channels.map((visual) => visual.channel)).size).toBeGreaterThan(1)
    expect(channels.every((visual) => visual.label && visual.detail && visual.motion)).toBe(true)
    expect(primaryAgentVisual('WORKING', 'mobile').motion).toBe('static')
    expect(primaryAgentVisual('READY', 'desktop', true).motion).toBe('static')
    expect(primaryAgentVisual('OFFLINE', 'desktop').detail).toMatch(/System/i)
    expect(primaryAgentVisual('OFFLINE', 'desktop').lod).toBe('simple')
  })

  it('preserves entity class counts, relations, and identity through LOD', () => {
    expect(spatialEntityCounts).toMatchObject({ subagent: 3, endpoint: 7, artifact: 6, attention: 3, relation: 2, total: 19 })
    expect(spatialEntities).toHaveLength(19)
    expect(spatialRelations).toHaveLength(2)
    const entity = spatialEntities[0]
    expect(spatialEntityLod(0.2, 'desktop')).toMatch(/^LOD/)
    expect(spatialEntityLod(20, 'mobile')).toBe('LOD0')
    expect(entity.id).toBe(spatialEntities[0].id)
  })

  it('clamps camera commands and focuses without mutating entity coordinates', () => {
    const entity = spatialEntities.find((candidate) => candidate.kind === 'endpoint')
    expect(entity).toBeTruthy()
    const originalPosition = { ...entity!.position }
    const focused = focusSpatialEntity(HOME_CAMERA, entity!)
    expect(focused.focusId).toBe(entity!.id)
    expect(focused.x).toBe(entity!.position.x)
    expect(focused.y).toBe(entity!.position.y)
    expect(entity!.position).toEqual(originalPosition)
    expect(clampSpatialCamera({ ...HOME_CAMERA, x: 99, y: -99, zoom: 99 })).toMatchObject({ x: 4.5, y: -3, zoom: 1.55 })
    expect(zoomSpatialCamera({ ...HOME_CAMERA, zoom: 1.54 }, 0.8).zoom).toBe(1.55)
    expect(homeSpatialCamera(focused)).toMatchObject({ ...HOME_CAMERA, focusId: null, transitionToken: expect.any(Number) })
    expect(focusPrimaryAgent(HOME_CAMERA)).toMatchObject({ focusId: FOCUS_PRIMARY_AGENT, x: 0, y: 0.42 })
  })

  it('keeps the performance gate honest and pauses hidden frames', () => {
    const pass = evaluateSpatialPerformanceGate(initialSpatialPerformanceMetrics)
    expect(pass.status).toBe('pass')
    const slow = evaluateSpatialPerformanceGate({ ...initialSpatialPerformanceMetrics, fps: 42, averageFrameTimeMs: 24, pointerLatencyMs: 140 })
    expect(slow.status).toBe('needs-attention')
    const visible = updateSpatialPerformanceFrame(initialSpatialPerformanceMetrics, 16, true)
    expect(visible.fps).toBeCloseTo(62.5)
    expect(updateSpatialPerformanceFrame(visible, 0, false).idleCpuActivity).toBe('paused')
    expect(SPATIAL_PERFORMANCE_BUDGET.maxPointerLatencyMs).toBe(100)
  })
})
