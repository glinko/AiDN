import { describe, expect, it } from 'vitest'

import { ConnectionEntity, DEFAULT_CONNECTIONS } from '@/spatial-calibration/model'

describe('calibration scene connections', () => {
  it('defines one curved link for the artifact and one for the endpoint', () => {
    expect(DEFAULT_CONNECTIONS).toHaveLength(2)
    expect(DEFAULT_CONNECTIONS.map((connection) => [connection.sourceId, connection.targetId])).toEqual([
      ['calibration-orb', 'calibration-cube'],
      ['calibration-orb', 'calibration-endpoint'],
    ])
  })

  it('derives smooth control points from live endpoint poses', () => {
    const entity = new ConnectionEntity(DEFAULT_CONNECTIONS[0])
    const source: [number, number, number] = [-1.1, 2.1, 0]
    const target: [number, number, number] = [1.35, 0.9, 0.4]
    const [start, bendA, bendB, end] = entity.getControlPoints(source, target)

    expect(start).toEqual([source[0] + 0.74, source[1] - 0.36, source[2] + 0.12])
    expect(end).toEqual([target[0] - 0.38, target[1] + 0.24, target[2] - 0.04])
    expect(bendA[2]).toBeGreaterThan(start[2])
    expect(bendB[2]).toBeGreaterThan(end[2])
    expect(entity.getControlPoints(source, [target[0], target[1] + 0.08, target[2]])[3][1]).toBeCloseTo(end[1] + 0.08)
  })

  it('keeps travelling beads deterministic, bounded, and still under reduced motion', () => {
    const entity = new ConnectionEntity(DEFAULT_CONNECTIONS[1])
    entity.update(7)
    const firstProgress = entity.getFlowProgress(0)
    const secondProgress = entity.getFlowProgress(1)
    expect(firstProgress).toBeGreaterThanOrEqual(0)
    expect(firstProgress).toBeLessThan(1)
    expect(secondProgress).toBeGreaterThanOrEqual(0)
    expect(secondProgress).toBeLessThan(1)
    expect(secondProgress).not.toBe(firstProgress)

    entity.update(7, true)
    expect(entity.time).toBe(0)
    expect(entity.getFlowProgress(0)).toBeCloseTo(entity.motion.phase)
  })
})
