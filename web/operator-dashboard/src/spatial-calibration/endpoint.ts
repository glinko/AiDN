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
  readonly driftAmplitude?: number
  readonly driftFrequency?: number
}

export const DEFAULT_ENDPOINT: EndpointConfig = {
  id: 'calibration-endpoint', position: [1.22, 3.28, -0.25], radius: 0.27,
  coreColor: '#f9fcff', coronaColor: '#6e8fbd',
  meteorColors: ['#82cfff', '#c1abff', '#ffceaf'],
  orbitRadius: 0.52, orbitSpeed: 0.24, trailAngle: 0.65,
}

/** Four colored endpoint nodes used by the local graph demonstration. */
export const DEMO_ENDPOINT_CONFIGS: ReadonlyArray<EndpointConfig> = Object.freeze([
  DEFAULT_ENDPOINT,
  {
    id: 'endpoint-runtime', position: [1.92, 3.68, 0.36], radius: 0.22,
    coreColor: '#fbfffd', coronaColor: '#5ea98d',
    meteorColors: ['#9be0ca', '#9bd8ef', '#f0d88d'],
    orbitRadius: 0.44, orbitSpeed: 0.19, trailAngle: 0.58, driftAmplitude: 0.052, driftFrequency: 0.23,
  },
  {
    id: 'endpoint-vision', position: [2.18, 3.04, 0.08], radius: 0.24,
    coreColor: '#fffafc', coronaColor: '#aa79b9',
    meteorColors: ['#d8b8f2', '#f0b4c4', '#9fc7f0'],
    orbitRadius: 0.49, orbitSpeed: 0.22, trailAngle: 0.62, driftAmplitude: 0.040, driftFrequency: 0.29,
  },
  {
    id: 'endpoint-archive', position: [1.48, 4.02, 0.70], radius: 0.19,
    coreColor: '#fffef8', coronaColor: '#c89556',
    meteorColors: ['#f2cf9d', '#e8b4a8', '#c4d9a9'],
    orbitRadius: 0.38, orbitSpeed: 0.27, trailAngle: 0.54, driftAmplitude: 0.034, driftFrequency: 0.26,
  },
])

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
    this.time = this.updateDrift(timeSeconds, reducedMotion, {
      driftAmplitude: this.config.driftAmplitude ?? 0.045,
      driftFrequency: this.config.driftFrequency ?? 0.3,
    })
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
