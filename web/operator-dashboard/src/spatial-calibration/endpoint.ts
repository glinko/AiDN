import { SceneEntity, type Vector3Tuple } from './model'

export interface EndpointConfig {
  readonly id: string
  readonly position: Vector3Tuple
  readonly radius: number
  readonly coreColor: string
  readonly coronaColor: string
  readonly meteorColors: readonly [string, string, string]
  readonly orbitRadius: number
  readonly orbitSpeed: number
  readonly trailAngle: number
}

export const DEFAULT_ENDPOINT: EndpointConfig = {
  id: 'calibration-endpoint', position: [1.25, 2.75, -0.25], radius: 0.29,
  coreColor: '#f9fcff', coronaColor: '#c5dfff',
  meteorColors: ['#82cfff', '#c1abff', '#ffceaf'],
  orbitRadius: 0.62, orbitSpeed: 0.24, trailAngle: 0.65,
}

/** Solar endpoint with exactly three deterministic comet orbits. */
export class EndpointEntity extends SceneEntity {
  readonly config: EndpointConfig
  time = 0
  constructor(config: EndpointConfig = DEFAULT_ENDPOINT) {
    super(config.id, config.position)
    const position: Vector3Tuple = [...config.position]
    const meteorColors: [string, string, string] = [...config.meteorColors]
    Object.freeze(position)
    Object.freeze(meteorColors)
    this.config = Object.freeze({ ...config, position, meteorColors })
  }
  update(timeSeconds: number, reducedMotion = false) {
    this.time = this.updateDrift(timeSeconds, reducedMotion, { driftAmplitude: 0.045, driftFrequency: 0.3 })
  }
  /** Local orbit position; trailing samples follow the same path, without a history buffer. */
  sampleMeteor(index: number, tail = 0): Vector3Tuple {
    if (!Number.isInteger(index) || index < 0 || index > 2) throw new RangeError('Meteor index must be 0, 1 or 2')
    const lag = Math.max(0, Math.min(1, Number.isFinite(tail) ? tail : 0))
    const angle = this.time * this.config.orbitSpeed * (1 + index * 0.12) + index * Math.PI * 2 / 3 - lag * this.config.trailAngle
    const radius = this.config.orbitRadius * (1 + index * 0.07)
    const x = Math.cos(angle) * radius
    const y = Math.sin(angle) * radius * 0.62
    const z = Math.sin(angle) * radius * 0.78
    const tilt = [-0.4, 0.65, 1.5][index]
    return [x * Math.cos(tilt) - y * Math.sin(tilt), x * Math.sin(tilt) + y * Math.cos(tilt), z]
  }
}
