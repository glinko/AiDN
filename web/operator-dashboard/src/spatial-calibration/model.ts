export type Vector3Tuple = [number, number, number]

export interface DriftConfig {
  readonly driftAmplitude: number
  /** Angular frequency in radians per second. */
  readonly driftFrequency: number
}

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
  readonly material: OrbMaterialConfig
  readonly motion: DriftConfig
}

export interface CubeConfig {
  readonly id: string
  readonly position: Vector3Tuple
  readonly size: number
  readonly baseYaw: number
  readonly material: CubeMaterialConfig
  readonly motion: DriftConfig & { readonly yawSpeed: number }
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
}

/** A local visual preset: it carries no runtime or Node binding. */
export const DEFAULT_CALIBRATION: CalibrationConfig = {
  camera: { position: [0.2, 3.15, 9.8], compactPosition: [0.2, 4.1, 18.5], target: [0.15, 1.45, 0], fov: 33, near: 0.1, far: 180 },
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
    motion: { driftAmplitude: 0.08, driftFrequency: 0.36 },
  },
  cube: {
    id: 'calibration-cube',
    position: [1.35, 0.9, 0.4],
    size: 0.92,
    baseYaw: -0.45,
    material: {
      color: '#f3f8ff',
      roughness: 0.075,
      metalness: 0,
      transmission: 1,
      thickness: 0.38,
      ior: 1.38,
      envMapIntensity: 1.1,
      clearcoat: 1,
      clearcoatRoughness: 0.08,
      attenuationColor: '#c1d4ef',
      attenuationDistance: 2.8,
      iridescence: 0.18,
      iridescenceIOR: 1.25,
      iridescenceThicknessRange: [180, 350],
    },
    motion: { driftAmplitude: 0.055, driftFrequency: 0.28, yawSpeed: 0.045 },
  },
}

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

export class OrbEntity extends SceneEntity {
  readonly radius: number
  readonly material: OrbMaterialConfig
  readonly motion: DriftConfig

  constructor(config: OrbConfig = DEFAULT_CALIBRATION.orb) {
    super(config.id, config.position)
    this.radius = config.radius
    this.material = snapshotMaterial(config.material)
    this.motion = Object.freeze({ ...config.motion })
  }

  update(timeSeconds: number, reducedMotion = false): void {
    this.updateDrift(timeSeconds, reducedMotion, this.motion)
  }
}

export class CubeEntity extends SceneEntity {
  readonly size: number
  readonly material: CubeMaterialConfig
  readonly motion: DriftConfig & { readonly yawSpeed: number }

  constructor(config: CubeConfig = DEFAULT_CALIBRATION.cube) {
    super(config.id, config.position, [0, config.baseYaw, 0])
    this.size = config.size
    this.material = snapshotMaterial(config.material)
    this.motion = Object.freeze({ ...config.motion })
  }

  update(timeSeconds: number, reducedMotion = false): void {
    const time = this.updateDrift(timeSeconds, reducedMotion, this.motion)
    this.rotation[1] = this.baseRotation[1] + (time * this.motion.yawSpeed) % (2 * Math.PI)
  }
}

export function createCalibrationEntities(config: CalibrationConfig = DEFAULT_CALIBRATION): {
  orb: OrbEntity
  cube: CubeEntity
} {
  return { orb: new OrbEntity(config.orb), cube: new CubeEntity(config.cube) }
}
