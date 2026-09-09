import { describe, expect, it } from 'vitest'
import { DoubleSide } from 'three'
import { createGlassFinish, createPearlMaterial } from '@/spatial-calibration/materials'
import { DEFAULT_CALIBRATION, createCalibrationEntities } from '@/spatial-calibration/model'

describe('calibration optics', () => {
  it('uses a distinct, two-sided glass layer without a time-driven light source', () => {
    const glass = createGlassFinish(0.92)
    expect(glass.transparent).toBe(true)
    expect(glass.depthWrite).toBe(false)
    expect(glass.side).toBe(DoubleSide)
    expect(glass.uniforms.uHalfSize.value).toBe(0.46)
    expect(glass.uniforms).not.toHaveProperty('uTime')
    glass.dispose()
  })

  it('keeps glass finish dimensions independent across entities', () => {
    const first = createGlassFinish(0.92)
    const second = createGlassFinish(2)
    first.uniforms.uHalfSize.value = 3
    expect(second.uniforms.uHalfSize.value).toBe(1)
    first.dispose()
    second.dispose()
  })

  it('retains full cube transmission and bounds reflection blending', () => {
    const { cube } = createCalibrationEntities()
    expect(cube.material.transmission).toBe(1)
    expect(cube.material.roughness).toBeLessThan(0.1)
    expect(DEFAULT_CALIBRATION.floor.reflection.strength).toBeGreaterThan(0)
    expect(DEFAULT_CALIBRATION.floor.reflection.strength).toBeLessThanOrEqual(1)
  })

  it('keeps the face-to-rim gradients authored in the optical materials', () => {
    const pearl = createPearlMaterial(0.7)
    const glass = createGlassFinish(0.92)
    expect(DEFAULT_CALIBRATION.orb.motion.pulseAmplitude).toBe(0.06)
    expect(pearl.uniforms).toHaveProperty('uPulseColor')
    expect(pearl.uniforms.uPulseColorAmount.value).toBe(DEFAULT_CALIBRATION.orb.colorPulse.amount)
    expect(pearl.fragmentShader).toContain('float front = smoothstep')
    expect(pearl.fragmentShader).toContain('float colorBreath')
    expect(pearl.fragmentShader).toContain('uPulseColor')
    expect(pearl.fragmentShader).toContain('volumeAlpha')
    expect(glass.fragmentShader).toContain('float front = smoothstep')
    expect(glass.fragmentShader).toContain('tint * mix(0.48, 0.84, front)')
    pearl.dispose()
    glass.dispose()
  })
})
