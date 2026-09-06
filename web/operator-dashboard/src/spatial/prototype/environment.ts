import type { SpatialViewport } from '@/spatial/workspace/viewport'

export type SpatialQualityProfile = 'low' | 'mobile' | 'desktop' | 'high'

export type SpatialEnvironmentProfile = {
  id: SpatialQualityProfile
  fogNear: number
  fogFar: number
  dprCap: number
  physicalMaterials: boolean
  softShadows: boolean
  reflections: boolean
  postProcessing: boolean
  particleBudget: number
}

/**
 * M1.4 keeps the atmospheric scene bounded. Profiles change fidelity, never
 * entity identity or semantic behavior.
 */
export const spatialEnvironmentProfiles: Record<SpatialQualityProfile, SpatialEnvironmentProfile> = {
  low: {
    id: 'low',
    fogNear: 4,
    fogFar: 12,
    dprCap: 1,
    physicalMaterials: false,
    softShadows: false,
    reflections: false,
    postProcessing: false,
    particleBudget: 0,
  },
  mobile: {
    id: 'mobile',
    fogNear: 4.5,
    fogFar: 15,
    dprCap: 1.25,
    physicalMaterials: false,
    softShadows: false,
    reflections: false,
    postProcessing: false,
    particleBudget: 4,
  },
  desktop: {
    id: 'desktop',
    fogNear: 5,
    fogFar: 20,
    dprCap: 1.5,
    physicalMaterials: true,
    softShadows: true,
    reflections: true,
    postProcessing: false,
    particleBudget: 8,
  },
  high: {
    id: 'high',
    fogNear: 5,
    fogFar: 24,
    dprCap: 1.5,
    physicalMaterials: true,
    softShadows: true,
    reflections: true,
    postProcessing: false,
    particleBudget: 12,
  },
}

export function inferSpatialQualityProfile(viewport: Pick<SpatialViewport, 'width' | 'dpr'>): SpatialQualityProfile {
  if (viewport.width < 640 || viewport.width < 900 && viewport.dpr <= 1.25) return 'mobile'
  return 'desktop'
}

export function spatialEnvironmentProfile(profile: SpatialQualityProfile): SpatialEnvironmentProfile {
  return spatialEnvironmentProfiles[profile]
}

export function clampSpatialDpr(profile: SpatialQualityProfile, dpr: number): number {
  const cap = spatialEnvironmentProfile(profile).dprCap
  return Math.min(Math.max(1, dpr), cap)
}

export function isSpatialDocumentVisible(): boolean {
  return typeof document === 'undefined' || !document.hidden
}

/** Neutral high-key environment values shared by WebGL and the 2D fallback. */
export const spatialAtmosphere = {
  background: '#f8fbfe',
  horizon: '#e6eef6',
  ground: '#edf3f8',
  environmentMap: 'studio-neutral',
} as const
