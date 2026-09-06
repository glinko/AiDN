import {
  parseSpatialRolloutStage,
  SPATIAL_ROLLOUT_STAGES,
  SPATIAL_SCHEMA_VERSIONS,
  type SpatialRolloutStage,
  type SpatialRolloutStageRecord,
} from '@/spatial/contracts'

export const SPATIAL_ROLLOUT_ORDER: readonly SpatialRolloutStage[] = [
  'DEVELOPER',
  'LOCAL_FIXTURE',
  'TEST_NODE',
  'LAN_NODES',
  'OPT_IN_PREVIEW',
  'DEFAULT_ON',
] as const

export type SpatialRolloutGateInput = {
  errorBudgetPercent: number
  compatibility: 'COMPATIBLE' | 'REBUILD_REQUIRED' | 'BLOCKED'
  rollbackVerified: boolean
  migrationReversible: boolean
  generatedAssetsAtomic: boolean
  securitySignedOff: boolean
  reliabilitySignedOff: boolean
  accessibilitySignedOff: boolean
  performanceSignedOff: boolean
}

export type SpatialRolloutDecision = {
  allowed: boolean
  reason: string
  fallback: 'SPATIAL' | 'CLASSIC'
}

const DEFAULT_ID = (prefix: string): string => `${prefix}:${Math.random().toString(36).slice(2, 12)}`

function isoNow(value?: string | Date): string {
  if (value instanceof Date) return value.toISOString()
  if (typeof value === 'string' && Number.isFinite(Date.parse(value))) return new Date(value).toISOString()
  return new Date().toISOString()
}

function indexOf(stage: SpatialRolloutStage): number {
  return SPATIAL_ROLLOUT_ORDER.indexOf(stage)
}

export function evaluateSpatialRolloutGate(stage: SpatialRolloutStage, gates: SpatialRolloutGateInput): SpatialRolloutDecision {
  if (!SPATIAL_ROLLOUT_STAGES.includes(stage)) return { allowed: false, reason: 'UNKNOWN_STAGE', fallback: 'CLASSIC' }
  if (gates.errorBudgetPercent < 0 || gates.errorBudgetPercent > 100) return { allowed: false, reason: 'INVALID_ERROR_BUDGET', fallback: 'CLASSIC' }
  if (gates.compatibility === 'BLOCKED') return { allowed: false, reason: 'COMPATIBILITY_BLOCKED', fallback: 'CLASSIC' }
  if (gates.compatibility === 'REBUILD_REQUIRED' && !gates.migrationReversible) return { allowed: false, reason: 'MIGRATION_NOT_REVERSIBLE', fallback: 'CLASSIC' }
  if (!gates.rollbackVerified) return { allowed: false, reason: 'ROLLBACK_NOT_VERIFIED', fallback: 'CLASSIC' }
  if (!gates.generatedAssetsAtomic) return { allowed: false, reason: 'GENERATED_ASSETS_NOT_ATOMIC', fallback: 'CLASSIC' }
  if (stage === 'DEFAULT_ON' && (!gates.securitySignedOff || !gates.reliabilitySignedOff || !gates.accessibilitySignedOff || !gates.performanceSignedOff)) {
    return { allowed: false, reason: 'SIGN_OFF_MISSING', fallback: 'CLASSIC' }
  }
  return { allowed: true, reason: 'GATES_PASSED', fallback: 'SPATIAL' }
}

export class SpatialRolloutController {
  private readonly idFactory: (prefix: string) => string
  private current: SpatialRolloutStageRecord

  public constructor(options: { workspaceId: string; nodeId: string; flag: string; idFactory?: (prefix: string) => string; now?: string | Date }) {
    this.idFactory = options.idFactory ?? DEFAULT_ID
    const parsed = parseSpatialRolloutStage({
      schema_version: SPATIAL_SCHEMA_VERSIONS.rolloutStage,
      rollout_id: this.idFactory('rollout'),
      workspace_id: options.workspaceId,
      node_id: options.nodeId,
      flag: options.flag,
      stage: 'DEVELOPER',
      enabled: false,
      rollback_stage: null,
      compatibility_state: 'COMPATIBLE',
      error_budget_percent: 100,
      evidence_refs: [],
      updated_at: isoNow(options.now),
    })
    if (!parsed.ok) throw new Error(`invalid rollout state: ${parsed.diagnostic.path}`)
    this.current = parsed.data
  }

  public state(): SpatialRolloutStageRecord { return this.current }

  public advance(nextStage: SpatialRolloutStage, gates: SpatialRolloutGateInput, evidenceRefs: readonly string[] = []): SpatialRolloutDecision {
    const currentIndex = indexOf(this.current.stage)
    const nextIndex = indexOf(nextStage)
    if (nextStage === 'ROLLED_BACK') return this.rollback(evidenceRefs)
    if (nextIndex !== currentIndex + 1) return { allowed: false, reason: 'STAGE_ORDER_VIOLATION', fallback: 'CLASSIC' }
    const decision = evaluateSpatialRolloutGate(nextStage, gates)
    if (!decision.allowed) return decision
    const parsed = parseSpatialRolloutStage({
      ...this.current,
      stage: nextStage,
      enabled: nextStage !== 'DEVELOPER',
      rollback_stage: this.current.stage,
      compatibility_state: gates.compatibility,
      error_budget_percent: gates.errorBudgetPercent,
      evidence_refs: [...new Set(evidenceRefs)],
      updated_at: new Date().toISOString(),
    })
    if (!parsed.ok) throw new Error(`invalid rollout transition: ${parsed.diagnostic.path}`)
    this.current = parsed.data
    return { allowed: true, reason: 'STAGE_ADVANCED', fallback: 'SPATIAL' }
  }

  public rollback(evidenceRefs: readonly string[] = []): SpatialRolloutDecision {
    const parsed = parseSpatialRolloutStage({
      ...this.current,
      stage: 'ROLLED_BACK',
      enabled: false,
      rollback_stage: this.current.stage,
      compatibility_state: 'COMPATIBLE',
      evidence_refs: [...new Set(evidenceRefs)],
      updated_at: new Date().toISOString(),
    })
    if (!parsed.ok) throw new Error(`invalid rollout rollback: ${parsed.diagnostic.path}`)
    this.current = parsed.data
    return { allowed: true, reason: 'ROLLED_BACK_TO_CLASSIC', fallback: 'CLASSIC' }
  }

  public presentation(): 'SPATIAL' | 'CLASSIC' {
    return this.current.enabled && this.current.stage !== 'ROLLED_BACK' ? 'SPATIAL' : 'CLASSIC'
  }
}
