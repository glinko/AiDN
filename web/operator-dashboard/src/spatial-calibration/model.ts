export type Vector3Tuple = [number, number, number]

export interface DriftConfig {
  readonly driftAmplitude: number
  /** Angular frequency in radians per second. */
  readonly driftFrequency: number
}

export interface OrbMotionConfig extends DriftConfig {
  /** Relative scale change around the base radius. */
  readonly pulseAmplitude: number
  /** Angular frequency in radians per second. */
  readonly pulseFrequency: number
}

export interface ConnectionMotionConfig {
  /** Normalized progress units per second for the travelling light beads. */
  readonly flowSpeed: number
  /** Normalized distance between successive beads. */
  readonly beadSpacing: number
  /** Initial normalized progress offset. */
  readonly phase: number
}

export interface ConnectionConfig {
  readonly id: string
  readonly sourceId: string
  readonly targetId: string
  readonly color: string
  /** Optional visual weight for dense demo graphs; the line remains hairline. */
  readonly opacity?: number
  readonly startOffset: Vector3Tuple
  readonly endOffset: Vector3Tuple
  readonly bendA: Vector3Tuple
  readonly bendB: Vector3Tuple
  readonly motion: ConnectionMotionConfig
}

export const DEFAULT_CONNECTIONS: ReadonlyArray<ConnectionConfig> = [
  {
    id: 'agent-artifact-thread',
    sourceId: 'calibration-orb',
    targetId: 'calibration-cube',
    color: '#78c9ee',
    startOffset: [0.74, -0.36, 0.12],
    endOffset: [-0.38, 0.24, -0.04],
    bendA: [-0.12, 0.10, 0.24],
    bendB: [0.12, -0.10, 0.22],
    motion: { flowSpeed: 0.17, beadSpacing: 0.31, phase: 0.08 },
  },
  {
    id: 'agent-endpoint-thread',
    sourceId: 'calibration-orb',
    targetId: 'calibration-endpoint',
    color: '#d1b7ff',
    startOffset: [0.80, 0.22, -0.08],
    endOffset: [-0.23, -0.05, 0.02],
    bendA: [-0.10, 0.32, 0.22],
    bendB: [0.15, 0.18, 0.16],
    motion: { flowSpeed: 0.13, beadSpacing: 0.34, phase: 0.52 },
  },
]

export interface OrbMaterialConfig {
  readonly color: string
  readonly roughness: number
  readonly metalness: number
  readonly clearcoat: number
  readonly clearcoatRoughness: number
  readonly transmission: number
  readonly thickness: number
  readonly ior: number
  readonly envMapIntensity: number
  readonly iridescence: number
  readonly iridescenceIOR: number
  readonly iridescenceThicknessRange: [number, number]
}

export interface OrbColorPulseConfig {
  /** Warm accent used by the six-second chroma breath. */
  readonly color: string
  /** Maximum blend from the neutral pearl into color. */
  readonly amount: number
}

export interface CubeMaterialConfig {
  readonly color: string
  readonly roughness: number
  readonly metalness: number
  readonly transmission: number
  readonly thickness: number
  readonly ior: number
  readonly envMapIntensity: number
  readonly clearcoat: number
  readonly clearcoatRoughness: number
  readonly attenuationColor: string
  readonly attenuationDistance: number
  readonly iridescence: number
  readonly iridescenceIOR: number
  readonly iridescenceThicknessRange: [number, number]
}

export interface OrbConfig {
  readonly id: string
  readonly position: Vector3Tuple
  readonly radius: number
  readonly colorPulse: OrbColorPulseConfig
  readonly material: OrbMaterialConfig
  readonly motion: OrbMotionConfig
}

export interface CubeConfig {
  readonly id: string
  readonly position: Vector3Tuple
  readonly size: number
  readonly cluster?: 'legacy' | 'active' | 'new'
  readonly baseYaw: number
  /** Optional pitch and roll offsets preserve compatibility with the original yaw-only preset. */
  readonly basePitch?: number
  readonly baseRoll?: number
  readonly material: CubeMaterialConfig
  readonly motion: DriftConfig & {
    readonly yawSpeed: number
    /** Angular speed around the X axis in radians per second. */
    readonly pitchSpeed?: number
    /** Angular speed around the Z axis in radians per second. */
    readonly rollSpeed?: number
  }
}

export interface CalibrationLightConfig {
  readonly color: string
  readonly intensity: number
  readonly position: Vector3Tuple
}

export interface CalibrationConfig {
  readonly camera: {
    readonly position: Vector3Tuple
    readonly compactPosition: Vector3Tuple
    readonly target: Vector3Tuple
    readonly fov: number
    readonly near: number
    readonly far: number
  }
  readonly environment: {
    readonly background: string
    readonly mapBackground: string
    readonly fogColor: string
    readonly fogNear: number
    readonly fogFar: number
    readonly intensity: number
    readonly toneMappingExposure: number
    readonly resolution: number
    readonly lightformers: ReadonlyArray<CalibrationLightConfig & { readonly scale: Vector3Tuple }>
  }
  readonly lighting: {
    readonly ambient: { readonly color: string; readonly intensity: number }
    readonly key: CalibrationLightConfig
    readonly fill: CalibrationLightConfig
    readonly rim: CalibrationLightConfig
  }
  readonly floor: {
    readonly size: number
    readonly color: string
    readonly reflection: {
      readonly resolution: number
      readonly compactResolution: number
      readonly strength: number
      readonly blurNear: number
      readonly blurFar: number
    }
  }
  readonly orb: OrbConfig
  readonly cube: CubeConfig
  /** Optional scene additions; omitted configs use the local demo preset. */
  readonly agents?: ReadonlyArray<OrbConfig>
  readonly artifacts?: ReadonlyArray<CubeConfig>
  readonly connections: ReadonlyArray<ConnectionConfig>
}

/** A local visual preset: it carries no runtime or Node binding. */
export const DEFAULT_CALIBRATION: CalibrationConfig = {
  camera: { position: [-1.05, 3.72, 11.8], compactPosition: [-1.05, 3.72, 11.8], target: [-1.1, 1.92, 0], fov: 33, near: 0.1, far: 180 },
  environment: {
    background: '#f4f6fb',
    mapBackground: '#e3eaf7',
    fogColor: '#f4f6fb',
    fogNear: 12,
    fogFar: 38,
    intensity: 1,
    toneMappingExposure: 1.05,
    resolution: 128,
    lightformers: [
      { color: '#ffffff', intensity: 3.5, position: [-3.5, 5, 4], scale: [5, 3, 1] },
      { color: '#b9e1ff', intensity: 1.5, position: [-4, 0.5, 1], scale: [4, 5, 1] },
      { color: '#c6b5f8', intensity: 1.4, position: [4, 1.2, 0], scale: [3, 5, 1] },
      { color: '#ffe1cf', intensity: 1.3, position: [2, -1, 3], scale: [3, 2, 1] },
      { color: '#ffffff', intensity: 2.2, position: [0, 4, -4], scale: [5, 2, 1] },
    ],
  },
  lighting: {
    ambient: { color: '#e8f0ff', intensity: 0.7 },
    key: { color: '#fffaf5', intensity: 2.1, position: [-4, 7, 5] },
    fill: { color: '#c5c6f5', intensity: 0.4, position: [4, 2, -1] },
    rim: { color: '#ffffff', intensity: 0, position: [0, 4, -4] },
  },
  floor: {
    size: 160,
    color: '#f0f3fa',
    reflection: {
      resolution: 768,
      compactResolution: 384,
      strength: 0.6,
      blurNear: 0.0015,
      blurFar: 0.005,
    },
  },
  orb: {
    id: 'calibration-orb',
    position: [-1.1, 2.1, 0],
    radius: 1,
    colorPulse: { color: '#f26f68', amount: 0.38 },
    material: {
      color: '#f5faff',
      roughness: 0.18,
      metalness: 0,
      clearcoat: 1,
      clearcoatRoughness: 0.15,
      transmission: 0.97,
      thickness: 0.16,
      ior: 1.13,
      envMapIntensity: 0.65,
      iridescence: 0.48,
      iridescenceIOR: 1.25,
      iridescenceThicknessRange: [180, 390],
    },
    motion: { driftAmplitude: 0.08, driftFrequency: 0.36, pulseAmplitude: 0.06, pulseFrequency: 1.04719755 },
  },
  cube: {
    id: 'calibration-cube',
    position: [0.65, 0.72, -0.35],
    size: 0.92,
    cluster: 'active',
    baseYaw: -0.45,
    material: {
      color: '#e1ebfc',
      roughness: 0.075,
      metalness: 0,
      transmission: 1,
      thickness: 0.38,
      ior: 1.38,
      envMapIntensity: 0.86,
      clearcoat: 1,
      clearcoatRoughness: 0.08,
      attenuationColor: '#b6c9e6',
      attenuationDistance: 2.8,
      iridescence: 0.18,
      iridescenceIOR: 1.25,
      iridescenceThicknessRange: [180, 350],
    },
    motion: { driftAmplitude: 0.055, driftFrequency: 0.28, pitchSpeed: 0.024, yawSpeed: 0.045, rollSpeed: 0.018 },
  },
  connections: DEFAULT_CONNECTIONS,
}

function createAgentConfig(
  id: string,
  position: Vector3Tuple,
  radius: number,
  color: string,
  phase: number,
): OrbConfig {
  return {
    id,
    position,
    radius,
    colorPulse: { color, amount: 0.72 },
    material: { ...DEFAULT_CALIBRATION.orb.material, color: '#f7fbff' },
    motion: {
      driftAmplitude: 0.045 + phase * 0.008,
      driftFrequency: 0.2 + phase * 0.035,
      pulseAmplitude: 0.025,
      pulseFrequency: 0.68 + phase * 0.08,
    },
  }
}

/** Six small, colored agent nodes used by the local graph demonstration. */
export const DEMO_AGENT_CONFIGS: ReadonlyArray<OrbConfig> = Object.freeze([
  createAgentConfig('subagent-yellow', [-2.25, 3.72, 0.52], 0.29, '#efc75b', 0.2),
  createAgentConfig('subagent-coral', [-1.75, 4.18, 0.08], 0.34, '#eb9d91', 0.8),
  createAgentConfig('subagent-mint', [-1.15, 3.88, -0.10], 0.27, '#8ed5bd', 1.4),
  createAgentConfig('subagent-lilac', [-2.28, 3.25, 0.12], 0.32, '#b6a7ec', 1.9),
  createAgentConfig('subagent-cyan', [-1.72, 3.35, 0.58], 0.25, '#83c9e8', 2.5),
  createAgentConfig('subagent-peach', [-0.95, 3.66, 0.30], 0.30, '#efb58c', 3.1),
])

type ArtifactSeed = {
  readonly id: string
  readonly cluster: 'legacy' | 'active' | 'new'
  readonly position: Vector3Tuple
  readonly size: number
  readonly color: string
  readonly attenuationColor: string
  readonly baseYaw: number
  readonly basePitch: number
  readonly baseRoll: number
  readonly driftAmplitude: number
  readonly driftFrequency: number
  readonly pitchSpeed: number
  readonly yawSpeed: number
  readonly rollSpeed: number
}

function createArtifactConfig(seed: ArtifactSeed): CubeConfig {
  return {
    id: seed.id,
    position: seed.position,
    size: seed.size,
    cluster: seed.cluster,
    baseYaw: seed.baseYaw,
    basePitch: seed.basePitch,
    baseRoll: seed.baseRoll,
    material: {
      ...DEFAULT_CALIBRATION.cube.material,
      color: seed.color,
      attenuationColor: seed.attenuationColor,
    },
    motion: {
      driftAmplitude: seed.driftAmplitude,
      driftFrequency: seed.driftFrequency,
      pitchSpeed: seed.pitchSpeed,
      yawSpeed: seed.yawSpeed,
      rollSpeed: seed.rollSpeed,
    },
  }
}

/** Nineteen supporting artifacts; the featured calibration cube makes a horizontal four-by-five field. */
export const DEMO_ARTIFACT_CONFIGS: ReadonlyArray<CubeConfig> = Object.freeze([
  createArtifactConfig({ id: 'artifact-02', cluster: 'legacy', position: [-2.80, 0.58, 1.05], size: 0.36, color: '#b9aceb', attenuationColor: '#7e72b4', baseYaw: -0.52, basePitch: 0.10, baseRoll: -0.04, driftAmplitude: 0.035, driftFrequency: 0.22, pitchSpeed: 0.024, yawSpeed: 0.036, rollSpeed: -0.018 }),
  createArtifactConfig({ id: 'artifact-03', cluster: 'legacy', position: [-1.65, 0.62, 1.05], size: 0.42, color: '#efc2ad', attenuationColor: '#b27d70', baseYaw: 0.18, basePitch: -0.06, baseRoll: 0.08, driftAmplitude: 0.040, driftFrequency: 0.27, pitchSpeed: -0.021, yawSpeed: -0.048, rollSpeed: 0.016 }),
  createArtifactConfig({ id: 'artifact-04', cluster: 'legacy', position: [-2.80, 0.60, 0.35], size: 0.33, color: '#a5d9df', attenuationColor: '#6c9da8', baseYaw: -0.30, basePitch: 0.05, baseRoll: 0.10, driftAmplitude: 0.030, driftFrequency: 0.24, pitchSpeed: 0.030, yawSpeed: 0.041, rollSpeed: 0.021 }),
  createArtifactConfig({ id: 'artifact-05', cluster: 'legacy', position: [-1.65, 0.56, 0.35], size: 0.46, color: '#c4e7d4', attenuationColor: '#78a993', baseYaw: 0.42, basePitch: 0.02, baseRoll: -0.12, driftAmplitude: 0.046, driftFrequency: 0.19, pitchSpeed: -0.027, yawSpeed: 0.032, rollSpeed: -0.019 }),
  createArtifactConfig({ id: 'artifact-06', cluster: 'legacy', position: [-2.80, 0.58, -0.35], size: 0.38, color: '#e5b8d2', attenuationColor: '#a9799b', baseYaw: -0.20, basePitch: 0.11, baseRoll: 0.06, driftAmplitude: 0.034, driftFrequency: 0.31, pitchSpeed: 0.019, yawSpeed: -0.040, rollSpeed: 0.025 }),
  createArtifactConfig({ id: 'artifact-07', cluster: 'legacy', position: [-2.80, 0.60, -1.05], size: 0.30, color: '#e7d38f', attenuationColor: '#aa9258', baseYaw: 0.58, basePitch: -0.08, baseRoll: -0.10, driftAmplitude: 0.028, driftFrequency: 0.26, pitchSpeed: -0.024, yawSpeed: 0.052, rollSpeed: 0.018 }),
  createArtifactConfig({ id: 'artifact-08', cluster: 'active', position: [-0.50, 0.56, 1.05], size: 0.44, color: '#aac6ee', attenuationColor: '#718cb8', baseYaw: -0.14, basePitch: 0.06, baseRoll: 0.12, driftAmplitude: 0.038, driftFrequency: 0.23, pitchSpeed: 0.028, yawSpeed: -0.038, rollSpeed: -0.022 }),
  createArtifactConfig({ id: 'artifact-09', cluster: 'active', position: [0.65, 0.62, 1.05], size: 0.35, color: '#d4b5ef', attenuationColor: '#9179b0', baseYaw: 0.35, basePitch: -0.10, baseRoll: 0.04, driftAmplitude: 0.032, driftFrequency: 0.29, pitchSpeed: -0.022, yawSpeed: 0.046, rollSpeed: 0.017 }),
  createArtifactConfig({ id: 'artifact-10', cluster: 'active', position: [-0.50, 0.64, 0.35], size: 0.50, color: '#a3dbcf', attenuationColor: '#659d98', baseYaw: -0.42, basePitch: 0.04, baseRoll: -0.08, driftAmplitude: 0.043, driftFrequency: 0.21, pitchSpeed: 0.024, yawSpeed: -0.032, rollSpeed: 0.020 }),
  createArtifactConfig({ id: 'artifact-11', cluster: 'active', position: [1.80, 0.60, 0.35], size: 0.37, color: '#efc0ae', attenuationColor: '#b47f73', baseYaw: 0.22, basePitch: 0.09, baseRoll: 0.02, driftAmplitude: 0.031, driftFrequency: 0.34, pitchSpeed: -0.031, yawSpeed: 0.039, rollSpeed: -0.018 }),
  createArtifactConfig({ id: 'artifact-12', cluster: 'active', position: [-1.65, 0.62, -0.35], size: 0.31, color: '#c4b3ef', attenuationColor: '#8275b6', baseYaw: -0.60, basePitch: -0.04, baseRoll: 0.13, driftAmplitude: 0.027, driftFrequency: 0.25, pitchSpeed: 0.020, yawSpeed: -0.050, rollSpeed: 0.022 }),
  createArtifactConfig({ id: 'artifact-13', cluster: 'active', position: [-0.50, 0.56, -0.35], size: 0.43, color: '#efd18e', attenuationColor: '#ae9153', baseYaw: 0.08, basePitch: 0.12, baseRoll: -0.06, driftAmplitude: 0.040, driftFrequency: 0.20, pitchSpeed: -0.026, yawSpeed: 0.034, rollSpeed: -0.021 }),
  createArtifactConfig({ id: 'artifact-14', cluster: 'new', position: [1.80, 0.58, 1.05], size: 0.35, color: '#a6d9e8', attenuationColor: '#6598aa', baseYaw: -0.28, basePitch: -0.07, baseRoll: 0.08, driftAmplitude: 0.034, driftFrequency: 0.30, pitchSpeed: 0.029, yawSpeed: -0.042, rollSpeed: 0.018 }),
  createArtifactConfig({ id: 'artifact-15', cluster: 'new', position: [0.65, 0.64, 0.35], size: 0.47, color: '#d2b5ef', attenuationColor: '#8975aa', baseYaw: 0.48, basePitch: 0.03, baseRoll: -0.11, driftAmplitude: 0.042, driftFrequency: 0.22, pitchSpeed: -0.020, yawSpeed: 0.045, rollSpeed: -0.023 }),
  createArtifactConfig({ id: 'artifact-16', cluster: 'new', position: [1.80, 0.60, -0.35], size: 0.32, color: '#ecb7aa', attenuationColor: '#aa7169', baseYaw: -0.52, basePitch: 0.08, baseRoll: 0.05, driftAmplitude: 0.029, driftFrequency: 0.27, pitchSpeed: 0.026, yawSpeed: -0.036, rollSpeed: 0.021 }),
  createArtifactConfig({ id: 'artifact-17', cluster: 'new', position: [1.80, 0.62, -1.05], size: 0.40, color: '#b5e3cd', attenuationColor: '#6f9e88', baseYaw: 0.30, basePitch: -0.12, baseRoll: -0.02, driftAmplitude: 0.036, driftFrequency: 0.24, pitchSpeed: -0.023, yawSpeed: 0.050, rollSpeed: -0.016 }),
  createArtifactConfig({ id: 'artifact-18', cluster: 'new', position: [-1.65, 0.56, -1.05], size: 0.44, color: '#b2c4ec', attenuationColor: '#7183b0', baseYaw: -0.04, basePitch: 0.06, baseRoll: 0.14, driftAmplitude: 0.039, driftFrequency: 0.18, pitchSpeed: 0.021, yawSpeed: -0.041, rollSpeed: 0.019 }),
  createArtifactConfig({ id: 'artifact-19', cluster: 'new', position: [-0.50, 0.64, -1.05], size: 0.30, color: '#efd28f', attenuationColor: '#a99052', baseYaw: 0.62, basePitch: -0.02, baseRoll: -0.07, driftAmplitude: 0.026, driftFrequency: 0.32, pitchSpeed: -0.028, yawSpeed: 0.038, rollSpeed: 0.024 }),
  createArtifactConfig({ id: 'artifact-20', cluster: 'new', position: [0.65, 0.58, -1.05], size: 0.38, color: '#dfb5dc', attenuationColor: '#9c719b', baseYaw: -0.34, basePitch: 0.10, baseRoll: 0.09, driftAmplitude: 0.033, driftFrequency: 0.28, pitchSpeed: 0.025, yawSpeed: -0.047, rollSpeed: -0.020 }),
])

function snapshotMaterial<T extends { readonly iridescenceThicknessRange: [number, number] }>(material: T): T {
  // Preserve renderer-compatible tuple types while preventing runtime mutation.
  const iridescenceThicknessRange: [number, number] = [...material.iridescenceThicknessRange]
  Object.freeze(iridescenceThicknessRange)
  return Object.freeze({ ...material, iridescenceThicknessRange })
}

/** Renderer-independent identity and transform, ready for a future binding adapter. */
export abstract class SceneEntity {
  readonly id: string
  readonly position: Vector3Tuple
  readonly rotation: Vector3Tuple
  readonly scale: Vector3Tuple
  protected readonly basePosition: Readonly<Vector3Tuple>
  protected readonly baseRotation: Readonly<Vector3Tuple>

  protected constructor(id: string, position: Vector3Tuple, rotation: Vector3Tuple = [0, 0, 0]) {
    this.id = id
    this.basePosition = Object.freeze([...position] as Vector3Tuple)
    this.baseRotation = Object.freeze([...rotation] as Vector3Tuple)
    this.position = [...position]
    this.rotation = [...rotation]
    this.scale = [1, 1, 1]
  }

  protected updateDrift(timeSeconds: number, reducedMotion: boolean, motion: DriftConfig): number {
    const time = Number.isFinite(timeSeconds) && !reducedMotion ? timeSeconds : 0
    this.position[0] = this.basePosition[0]
    this.position[1] = this.basePosition[1] + Math.sin(time * motion.driftFrequency) * motion.driftAmplitude
    this.position[2] = this.basePosition[2]
    this.rotation[0] = this.baseRotation[0]
    this.rotation[1] = this.baseRotation[1]
    this.rotation[2] = this.baseRotation[2]
    return time
  }

  abstract update(timeSeconds: number, reducedMotion?: boolean): void
}

function freezeTuple(value: Vector3Tuple): Vector3Tuple {
  return Object.freeze([...value] as Vector3Tuple) as unknown as Vector3Tuple
}

/** A renderer-independent curved link between two scene entities. */
export class ConnectionEntity {
  readonly id: string
  readonly sourceId: string
  readonly targetId: string
  readonly color: string
  readonly opacity: number
  readonly startOffset: Vector3Tuple
  readonly endOffset: Vector3Tuple
  readonly bendA: Vector3Tuple
  readonly bendB: Vector3Tuple
  readonly motion: ConnectionMotionConfig
  time = 0

  constructor(config: ConnectionConfig) {
    this.id = config.id
    this.sourceId = config.sourceId
    this.targetId = config.targetId
    this.color = config.color
    this.opacity = Math.min(1, Math.max(0, config.opacity ?? 0.66))
    this.startOffset = freezeTuple(config.startOffset)
    this.endOffset = freezeTuple(config.endOffset)
    this.bendA = freezeTuple(config.bendA)
    this.bendB = freezeTuple(config.bendB)
    this.motion = Object.freeze({ ...config.motion })
  }

  update(timeSeconds: number, reducedMotion = false): void {
    this.time = Number.isFinite(timeSeconds) && !reducedMotion ? timeSeconds : 0
  }

  getControlPoints(sourcePosition: Vector3Tuple, targetPosition: Vector3Tuple): [Vector3Tuple, Vector3Tuple, Vector3Tuple, Vector3Tuple] {
    const start = [
      sourcePosition[0] + this.startOffset[0],
      sourcePosition[1] + this.startOffset[1],
      sourcePosition[2] + this.startOffset[2],
    ] as Vector3Tuple
    const end = [
      targetPosition[0] + this.endOffset[0],
      targetPosition[1] + this.endOffset[1],
      targetPosition[2] + this.endOffset[2],
    ] as Vector3Tuple
    const control = (amount: number, bend: Vector3Tuple): Vector3Tuple => [
      start[0] + (end[0] - start[0]) * amount + bend[0],
      start[1] + (end[1] - start[1]) * amount + bend[1],
      start[2] + (end[2] - start[2]) * amount + bend[2],
    ]
    return [start, control(0.32, this.bendA), control(0.68, this.bendB), end]
  }

  getFlowProgress(index: number): number {
    const raw = this.time * this.motion.flowSpeed + this.motion.phase + index * this.motion.beadSpacing
    return raw - Math.floor(raw)
  }
}

export class OrbEntity extends SceneEntity {
  readonly radius: number
  readonly colorPulse: OrbColorPulseConfig
  readonly material: OrbMaterialConfig
  readonly motion: OrbMotionConfig
  time = 0

  constructor(config: OrbConfig = DEFAULT_CALIBRATION.orb) {
    super(config.id, config.position)
    this.radius = config.radius
    this.colorPulse = Object.freeze({ ...config.colorPulse })
    this.material = snapshotMaterial(config.material)
    this.motion = Object.freeze({ ...config.motion })
  }

  update(timeSeconds: number, reducedMotion = false): void {
    const time = this.updateDrift(timeSeconds, reducedMotion, this.motion)
    this.time = time
    const pulse = Math.sin(time * this.motion.pulseFrequency) * this.motion.pulseAmplitude
    const scale = 1 + pulse
    this.scale[0] = scale
    this.scale[1] = scale
    this.scale[2] = scale
  }
}

export class CubeEntity extends SceneEntity {
  readonly size: number
  readonly material: CubeMaterialConfig
  readonly motion: CubeConfig['motion']

  constructor(config: CubeConfig = DEFAULT_CALIBRATION.cube) {
    super(config.id, config.position, [config.basePitch ?? 0, config.baseYaw, config.baseRoll ?? 0])
    this.size = config.size
    this.material = snapshotMaterial(config.material)
    this.motion = Object.freeze({ ...config.motion })
  }

  update(timeSeconds: number, reducedMotion = false): void {
    const time = this.updateDrift(timeSeconds, reducedMotion, this.motion)
    this.rotation[0] = this.baseRotation[0] + time * (this.motion.pitchSpeed ?? 0)
    this.rotation[1] = this.baseRotation[1] + (time * this.motion.yawSpeed) % (2 * Math.PI)
    this.rotation[2] = this.baseRotation[2] + time * (this.motion.rollSpeed ?? 0)
  }
}

export function createCalibrationEntities(config: CalibrationConfig = DEFAULT_CALIBRATION): {
  orb: OrbEntity
  cube: CubeEntity
  agents: OrbEntity[]
  artifacts: CubeEntity[]
  connections: ConnectionEntity[]
} {
  const agentConfigs = config.agents ?? DEMO_AGENT_CONFIGS
  const artifactConfigs = config.artifacts ?? DEMO_ARTIFACT_CONFIGS
  return {
    orb: new OrbEntity(config.orb),
    cube: new CubeEntity(config.cube),
    agents: agentConfigs.map((agent) => new OrbEntity(agent)),
    artifacts: artifactConfigs.map((artifact) => new CubeEntity(artifact)),
    connections: config.connections.map((connection) => new ConnectionEntity(connection)),
  }
}
