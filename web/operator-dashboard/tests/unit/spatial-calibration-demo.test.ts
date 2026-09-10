import { describe, expect, it } from 'vitest'

import { DEMO_ARTIFACT_CONFIGS, DEMO_AGENT_CONFIGS, createCalibrationEntities } from '@/spatial-calibration/model'
import { DEMO_ENDPOINT_CONFIGS, EndpointEntity } from '@/spatial-calibration/endpoint'

describe('spatial graph demonstration preset', () => {
  it('provides six colored subagents and nineteen supporting artifacts', () => {
    expect(DEMO_AGENT_CONFIGS).toHaveLength(6)
    expect(new Set(DEMO_AGENT_CONFIGS.map((agent) => agent.colorPulse.color)).size).toBe(6)
    expect(DEMO_ARTIFACT_CONFIGS).toHaveLength(19)
    expect(new Set(DEMO_ARTIFACT_CONFIGS.map((artifact) => artifact.cluster)).size).toBe(3)
  })

  it('creates independent entities with different triaxial artifact motion', () => {
    const { agents, artifacts } = createCalibrationEntities()
    expect(agents).toHaveLength(6)
    expect(artifacts).toHaveLength(19)
    artifacts.forEach((artifact, index) => {
      artifact.update(12 + index)
      expect(Number.isFinite(artifact.rotation[0])).toBe(true)
      expect(Number.isFinite(artifact.rotation[1])).toBe(true)
      expect(Number.isFinite(artifact.rotation[2])).toBe(true)
    })
    expect(new Set(artifacts.map((artifact) => artifact.motion.yawSpeed)).size).toBeGreaterThan(1)
  })

  it('keeps the artifact field broad in X/Z with a shared hover height', () => {
    const { cube, artifacts } = createCalibrationEntities()
    const field = [cube, ...artifacts]
    const heights = field.map((artifact) => artifact.position[1])
    const depths = field.map((artifact) => artifact.position[2])
    expect(Math.max(...heights) - Math.min(...heights)).toBeLessThan(0.2)
    expect(Math.max(...depths) - Math.min(...depths)).toBeGreaterThan(1.8)
  })

  it('keeps endpoint colors and motion isolated per node', () => {
    expect(DEMO_ENDPOINT_CONFIGS).toHaveLength(4)
    const endpoints = DEMO_ENDPOINT_CONFIGS.map((config) => new EndpointEntity(config))
    expect(new Set(endpoints.map((endpoint) => endpoint.config.coronaColor)).size).toBe(4)
    endpoints.forEach((endpoint, index) => endpoint.update(8 + index))
    expect(new Set(endpoints.map((endpoint) => endpoint.position[1])).size).toBe(4)
  })
})
