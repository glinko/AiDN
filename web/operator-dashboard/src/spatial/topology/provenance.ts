import {
  parseSpatialInteractionProvenance,
  SPATIAL_SCHEMA_VERSIONS,
  type SpatialFamiliarityState,
  type SpatialInteractionOutcome,
  type SpatialInteractionProvenance,
} from '@/spatial/contracts'

export type InteractionProvenanceServiceOptions = {
  workspaceId: string
  nodeId: string
  primaryAgentRef: string
  now?: () => Date
  trustedSuccessThreshold?: number
}

export type RecordInteractionInput = {
  requestId: string
  endpointRef: string
  endpointRevision: number
  resultRef?: string | null
  outcome: SpatialInteractionOutcome
  latencyMs?: number | null
  usageRef?: string | null
  idempotencyKey: string
}

export type EndpointExperience = {
  endpointRef: string
  endpointRevision: number
  interactionCount: number
  successfulCount: number
  failedCount: number
  cancelledCount: number
  timeoutCount: number
  lastUsedAt: string | null
  lastSuccessAt: string | null
  lastFailureAt: string | null
  familiarity: SpatialFamiliarityState
}

export type ProvenanceRecordResult = { record: SpatialInteractionProvenance; duplicate: boolean }

export type InteractionProvenanceErrorCode = 'INVALID_RECORD' | 'SCOPE_MISMATCH'

export class InteractionProvenanceError extends Error {
  readonly code: InteractionProvenanceErrorCode

  constructor(code: InteractionProvenanceErrorCode, message: string) {
    super(message)
    this.name = 'InteractionProvenanceError'
    this.code = code
  }
}

/** Local history is deliberately independent from global reputation. */
export class InteractionProvenanceService {
  private readonly records = new Map<string, SpatialInteractionProvenance>()
  private readonly revisions = new Map<string, SpatialInteractionProvenance[]>()
  private readonly experience = new Map<string, EndpointExperience>()
  private readonly globalReputation = new Map<string, number>()
  private readonly unresolvedFailures = new Map<string, boolean>()
  private readonly options: InteractionProvenanceServiceOptions

  constructor(options: InteractionProvenanceServiceOptions) {
    this.options = options
  }

  record(input: RecordInteractionInput): ProvenanceRecordResult {
    const idempotencyKey = input.idempotencyKey.trim()
    const existing = this.records.get(idempotencyKey)
    if (existing) return { record: { ...existing }, duplicate: true }
    if (!input.requestId.trim() || !input.endpointRef.trim() || !idempotencyKey || !Number.isInteger(input.endpointRevision) || input.endpointRevision < 0) {
      throw new InteractionProvenanceError('INVALID_RECORD', 'request, endpoint and idempotency references are required')
    }
    const now = (this.options.now ?? (() => new Date()))().toISOString()
    const record: SpatialInteractionProvenance = {
      schema_version: SPATIAL_SCHEMA_VERSIONS.interactionProvenance,
      record_id: `provenance:${idempotencyKey}`,
      request_id: input.requestId,
      endpoint_ref: input.endpointRef,
      endpoint_revision: input.endpointRevision,
      result_ref: input.resultRef ?? null,
      outcome: input.outcome,
      latency_ms: input.latencyMs ?? null,
      usage_ref: input.usageRef ?? null,
      idempotency_key: idempotencyKey,
      node_id: this.options.nodeId,
      workspace_id: this.options.workspaceId,
      primary_agent_ref: this.options.primaryAgentRef,
      revision: 0,
      observed_at: now,
    }
    const parsed = parseSpatialInteractionProvenance(record)
    if (!parsed.ok) throw new InteractionProvenanceError('INVALID_RECORD', `provenance invalid at ${parsed.diagnostic.path}`)
    this.records.set(idempotencyKey, parsed.data)
    const history = this.revisions.get(input.endpointRef) ?? []
    history.push(parsed.data)
    this.revisions.set(input.endpointRef, history)
    this.updateExperience(parsed.data)
    return { record: { ...parsed.data }, duplicate: false }
  }

  getExperience(endpointRef: string): EndpointExperience {
    const current = this.experience.get(endpointRef)
    if (current) return { ...current }
    return {
      endpointRef,
      endpointRevision: 0,
      interactionCount: 0,
      successfulCount: 0,
      failedCount: 0,
      cancelledCount: 0,
      timeoutCount: 0,
      lastUsedAt: null,
      lastSuccessAt: null,
      lastFailureAt: null,
      familiarity: 'NEVER_USED',
    }
  }

  inspectHistory(endpointRef: string): SpatialInteractionProvenance[] {
    return (this.revisions.get(endpointRef) ?? []).map((record) => ({ ...record }))
  }

  setGlobalReputation(endpointRef: string, score: number): void {
    if (!Number.isFinite(score) || score < 0 || score > 1) throw new InteractionProvenanceError('INVALID_RECORD', 'global reputation must be between 0 and 1')
    this.globalReputation.set(endpointRef, score)
  }

  getGlobalReputation(endpointRef: string): number | null {
    return this.globalReputation.get(endpointRef) ?? null
  }

  list(): SpatialInteractionProvenance[] {
    return [...this.records.values()].map((record) => ({ ...record }))
  }

  private updateExperience(record: SpatialInteractionProvenance): void {
    const current = this.getExperience(record.endpoint_ref)
    const success = record.outcome === 'SUCCESS'
    const failure = record.outcome === 'FAILURE' || record.outcome === 'TIMEOUT'
    const successfulCount = current.successfulCount + (success ? 1 : 0)
    const failedCount = current.failedCount + (record.outcome === 'FAILURE' ? 1 : 0)
    const timeoutCount = current.timeoutCount + (record.outcome === 'TIMEOUT' ? 1 : 0)
    const cancelledCount = current.cancelledCount + (record.outcome === 'CANCELLED' ? 1 : 0)
    const threshold = Math.max(1, this.options.trustedSuccessThreshold ?? 3)
    if (failure) this.unresolvedFailures.set(record.endpoint_ref, true)
    if (success) this.unresolvedFailures.set(record.endpoint_ref, false)
    const lastFailureAt = failure ? record.observed_at : current.lastFailureAt
    const lastSuccessAt = success ? record.observed_at : current.lastSuccessAt
    const noFreshFailure = !(this.unresolvedFailures.get(record.endpoint_ref) ?? false)
    const familiarity: SpatialFamiliarityState = successfulCount >= threshold && noFreshFailure ? 'TRUSTED_BY_HISTORY' : 'USED'
    this.experience.set(record.endpoint_ref, {
      endpointRef: record.endpoint_ref,
      endpointRevision: record.endpoint_revision,
      interactionCount: current.interactionCount + 1,
      successfulCount,
      failedCount,
      cancelledCount,
      timeoutCount,
      lastUsedAt: record.observed_at,
      lastSuccessAt,
      lastFailureAt,
      familiarity,
    })
  }
}

export const EndpointProvenanceService = InteractionProvenanceService
