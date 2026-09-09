import { describe, expect, it } from 'vitest'
import { DEFAULT_ENDPOINT, EndpointEntity } from '@/spatial-calibration/endpoint'

describe('solar endpoint', () => {
  it('has exactly three distinct, bounded meteor paths', () => {
    const endpoint = new EndpointEntity()
    for (const time of [0, 10, 100, 10000]) {
      endpoint.update(time)
      const paths = [0,1,2].map(index => endpoint.sampleMeteor(index))
      expect(new Set(paths.map(path => path.join(','))).size).toBe(3)
      for (const point of paths) expect(Math.hypot(...point)).toBeLessThan(0.8)
    }
    expect(() => endpoint.sampleMeteor(3)).toThrow(RangeError)
  })
  it('freezes the complete effect under reduced motion and sanitizes invalid clocks', () => {
    const endpoint = new EndpointEntity()
    endpoint.update(0)
    const initial = endpoint.sampleMeteor(1)
    endpoint.update(120, true)
    expect(endpoint.sampleMeteor(1)).toEqual(initial)
    expect(endpoint.position).toEqual(DEFAULT_ENDPOINT.position)
    endpoint.update(Number.NaN)
    expect(endpoint.sampleMeteor(1)).toEqual(initial)
  })
  it('evaluates trail samples from the same orbit without accumulated history', () => {
    const a = new EndpointEntity()
    const b = new EndpointEntity()
    for (let time = 0; time <= 60; time++) a.update(time)
    b.update(60)
    expect(a.sampleMeteor(2, 0.7)).toEqual(b.sampleMeteor(2, 0.7))
    expect(a.sampleMeteor(0, 1)).not.toEqual(a.sampleMeteor(0, 0))
  })
  it('snapshots appearance independently of subsequent source edits', () => {
    const config = { ...DEFAULT_ENDPOINT, meteorColors: ['#ffffff','#aabbcc','#ddeeff'] as [string,string,string] }
    const endpoint = new EndpointEntity(config)
    config.meteorColors[0] = '#000000'
    expect(endpoint.config.meteorColors[0]).toBe('#ffffff')
    expect(Object.isFrozen(endpoint.config.meteorColors)).toBe(true)
  })
})
