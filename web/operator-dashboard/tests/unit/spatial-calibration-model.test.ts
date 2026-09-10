import { describe, expect, it } from 'vitest'

import {
  CubeEntity,
  DEFAULT_CALIBRATION,
  OrbEntity,
  SceneEntity,
  createCalibrationEntities,
} from '@/spatial-calibration/model'

describe('calibration scene entities', () => {
  it('creates an orb and a cube at the preset poses with independent transforms', () => {
    const { orb, cube } = createCalibrationEntities()
    expect(orb).toBeInstanceOf(OrbEntity)
    expect(cube).toBeInstanceOf(CubeEntity)
    expect(orb).toBeInstanceOf(SceneEntity)
    expect(orb.position).toEqual([-1.1, 2.1, 0])
    expect(orb.radius).toBe(1)
    expect(cube.position).toEqual([1.8, 1.54, 0.3])
    expect(cube.size).toBe(0.92)
    expect(cube.rotation).toEqual([0, -0.45, 0])
    expect(orb.id).not.toBe(cube.id)
    expect(orb.scale).toEqual([1, 1, 1])
    expect(orb.position).not.toBe(DEFAULT_CALIBRATION.orb.position)
    expect(cube.position).not.toBe(DEFAULT_CALIBRATION.cube.position)
  })

  it('pulses the orb scale from absolute time within its configured amplitude', () => {
    const { orb } = createCalibrationEntities()
    const pulsePeak = Math.PI / (2 * orb.motion.pulseFrequency)
    const pulseTrough = (3 * Math.PI) / (2 * orb.motion.pulseFrequency)

    orb.update(0)
    expect(orb.scale).toEqual([1, 1, 1])
    orb.update(pulsePeak)
    expect(orb.scale[0]).toBeCloseTo(1 + orb.motion.pulseAmplitude)
    expect(orb.scale[1]).toBeCloseTo(orb.scale[0])
    expect(orb.scale[2]).toBeCloseTo(orb.scale[0])
    orb.update(pulseTrough)
    expect(orb.scale[0]).toBeCloseTo(1 - orb.motion.pulseAmplitude)
    expect(Math.abs(orb.scale[0] - 1)).toBeLessThanOrEqual(orb.motion.pulseAmplitude + Number.EPSILON)
  })

  it('evaluates from absolute time without accumulating drift or depending on frame history', () => {
    const stepped = createCalibrationEntities()
    const direct = createCalibrationEntities()
    for (let step = 0; step <= 1440; step += 1) {
      stepped.orb.update(step / 60)
      stepped.cube.update(step / 60)
    }
    direct.orb.update(24)
    direct.cube.update(24)
    expect(stepped.orb.position).toEqual(direct.orb.position)
    expect(stepped.orb.scale).toEqual(direct.orb.scale)
    expect(stepped.cube.position).toEqual(direct.cube.position)
    expect(stepped.cube.rotation).toEqual(direct.cube.rotation)

    const pose = [...direct.orb.position]
    direct.orb.update(24)
    expect(direct.orb.position).toEqual(pose)
    direct.orb.update(0)
    direct.cube.update(0)
    expect(direct.orb.position).toEqual(DEFAULT_CALIBRATION.orb.position)
    expect(direct.cube.rotation).toEqual([0, DEFAULT_CALIBRATION.cube.baseYaw, 0])
  })

  it('keeps drift within its amplitude and cube rotation on all three axes over long runs', () => {
    const { orb, cube } = createCalibrationEntities()
    for (let time = 0; time < 86_400; time += 73) {
      orb.update(time)
      cube.update(time)
      expect(Math.abs(orb.position[1] - DEFAULT_CALIBRATION.orb.position[1])).toBeLessThanOrEqual(orb.motion.driftAmplitude + Number.EPSILON)
      expect(Math.abs(cube.position[1] - DEFAULT_CALIBRATION.cube.position[1])).toBeLessThanOrEqual(cube.motion.driftAmplitude + Number.EPSILON)
      expect([orb.position[0], orb.position[2]]).toEqual([-1.1, 0])
      expect([cube.position[0], cube.position[2]]).toEqual([1.8, 0.3])
      expect(orb.rotation).toEqual([0, 0, 0])
      expect(Number.isFinite(cube.rotation[0])).toBe(true)
      expect(Number.isFinite(cube.rotation[2])).toBe(true)
      expect(Math.abs(cube.rotation[1] - DEFAULT_CALIBRATION.cube.baseYaw)).toBeLessThan(2 * Math.PI)
    }
    cube.update(10)
    expect(cube.rotation[0]).toBeCloseTo(10 * (cube.motion.pitchSpeed ?? 0))
    expect(cube.rotation[1]).toBeCloseTo(DEFAULT_CALIBRATION.cube.baseYaw + 10 * 0.045)
    expect(cube.rotation[2]).toBeCloseTo(10 * (cube.motion.rollSpeed ?? 0))
  })

  it('restores and holds the base pose when reduced motion is enabled', () => {
    const { orb, cube } = createCalibrationEntities()
    orb.update(12)
    cube.update(12)
    expect(orb.position).not.toEqual(DEFAULT_CALIBRATION.orb.position)
    expect(cube.rotation[1]).not.toBe(DEFAULT_CALIBRATION.cube.baseYaw)
    for (const time of [12, 84, 1024]) {
      orb.update(time, true)
      cube.update(time, true)
      expect(orb.position).toEqual(DEFAULT_CALIBRATION.orb.position)
      expect(orb.scale).toEqual([1, 1, 1])
      expect(cube.position).toEqual(DEFAULT_CALIBRATION.cube.position)
      expect(cube.rotation).toEqual([
        DEFAULT_CALIBRATION.cube.basePitch ?? 0,
        DEFAULT_CALIBRATION.cube.baseYaw,
        DEFAULT_CALIBRATION.cube.baseRoll ?? 0,
      ])
    }
    cube.update(84)
    expect(cube.rotation[1]).not.toBe(DEFAULT_CALIBRATION.cube.baseYaw)
  })

  it('owns immutable configuration snapshots and does not share state between instances', () => {
    const sourceThicknessRange: [number, number] = [180, 420]
    const config = {
      ...structuredClone(DEFAULT_CALIBRATION),
      orb: {
        ...DEFAULT_CALIBRATION.orb,
        position: [...DEFAULT_CALIBRATION.orb.position] as [number, number, number],
        material: { ...DEFAULT_CALIBRATION.orb.material, iridescenceThicknessRange: sourceThicknessRange },
      },
    }
    const first = createCalibrationEntities(config)
    const second = createCalibrationEntities(config)
    config.orb.position[1] = 99
    config.orb.material.iridescenceThicknessRange[0] = 1
    first.orb.position[1] = 23
    first.cube.rotation[1] = 42
    first.orb.scale[0] = 2

    first.orb.update(0)
    expect(first.orb.position[1]).toBe(2.1)
    expect(second.orb.position[1]).toBe(2.1)
    expect(second.cube.rotation[1]).toBe(-0.45)
    expect(second.orb.scale).toEqual([1, 1, 1])
    expect(first.orb.material.iridescenceThicknessRange).toEqual([180, 420])
    expect(first.orb.material).not.toBe(second.orb.material)
    expect(first.cube.motion).not.toBe(second.cube.motion)
    expect(Object.isFrozen(first.orb.material)).toBe(true)
    expect(Object.isFrozen(first.orb.material.iridescenceThicknessRange)).toBe(true)
    expect(Object.isFrozen(first.cube.material)).toBe(true)
    expect(Object.isFrozen(first.cube.motion)).toBe(true)
    expect(DEFAULT_CALIBRATION.orb.position).toEqual([-1.1, 2.1, 0])
  })

  it('falls back to a finite base pose if an animation clock supplies invalid time', () => {
    const { orb, cube } = createCalibrationEntities()
    for (const time of [Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY]) {
      orb.update(time)
      cube.update(time)
      expect(orb.position).toEqual(DEFAULT_CALIBRATION.orb.position)
      expect(orb.scale).toEqual([1, 1, 1])
      expect(cube.position).toEqual(DEFAULT_CALIBRATION.cube.position)
      expect(cube.rotation).toEqual([0, DEFAULT_CALIBRATION.cube.baseYaw, 0])
    }
  })
})
