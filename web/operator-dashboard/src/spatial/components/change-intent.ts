import {
  parseSpatialChangeIntent,
  SPATIAL_SCHEMA_VERSIONS,
  type SpatialChangeFieldType,
  type SpatialChangeIntent,
  type SpatialChangeIntentSource,
  type SpatialChangeIntentState,
} from '@/spatial/contracts'

type ChangeValue = string | number | boolean | null

export type ChangeIntentField = {
  path: string
  type: SpatialChangeFieldType
  editable: boolean
  required?: boolean
  unit?: string | null
  minimum?: number | null
  maximum?: number | null
  allowed_values?: readonly ChangeValue[]
}

export type ChangeIntentInput = {
  workspaceId: string
  nodeId: string
  intentId?: string
  target: { type: 'endpoint' | 'bundle' | 'provider' | 'runtime' | 'resource'; id: string; revision: number }
  current: Record<string, ChangeValue>
  proposed: Record<string, ChangeValue>
  fieldSchema: readonly ChangeIntentField[]
  actorRef: string
  idempotencyKey: string
  currentRevision: number
  source: SpatialChangeIntentSource
  workspaceSessionRef?: string | null
  naturalLanguageSummary?: string | null
  provenance?: { sourceRef?: string | null; correlationId?: string | null }
  now?: Date
}

export type ChangeIntentValidation = {
  state: Extract<SpatialChangeIntentState, 'VALID' | 'STALE' | 'OCCUPIED' | 'UNAUTHORIZED_FIELD' | 'AGENT_OFFLINE' | 'NEEDS_CLARIFICATION'>
  intent: SpatialChangeIntent
  changedPaths: readonly string[]
  alternatives: readonly string[]
}

export type ChangeIntentApplyResult = {
  status: 'applied' | 'duplicate'
  intent: SpatialChangeIntent
  revision: number
  resultRef: string
}

export class ChangeIntentError extends Error {
  readonly code: 'INVALID' | 'NOT_EXPLICIT' | 'DUPLICATE'
  constructor(code: ChangeIntentError['code'], message: string) {
    super(message)
    this.name = 'ChangeIntentError'
    this.code = code
  }
}

function makeId(prefix: string): string {
  const uuid = typeof globalThis.crypto?.randomUUID === 'function' ? globalThis.crypto.randomUUID() : `${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 9)}`
  return `${prefix}_${uuid}`
}

function sameValue(left: ChangeValue, right: ChangeValue): boolean {
  return left === right
}

function changedPaths(current: Record<string, ChangeValue>, proposed: Record<string, ChangeValue>): string[] {
  return [...new Set([...Object.keys(current), ...Object.keys(proposed)].filter((path) => !sameValue(current[path] ?? null, proposed[path] ?? null)))].sort()
}

/**
 * One semantic change boundary for form, voice and Spatial controls. Known
 * form values are copied into the intent; natural language is annotation only
 * and never becomes the source of a field value.
 */
export class ChangeIntentService {
  private readonly byIdempotency = new Map<string, ChangeIntentApplyResult>()
  private readonly idFactory: (prefix: string) => string

  constructor(options: { idFactory?: (prefix: string) => string } = {}) {
    this.idFactory = options.idFactory ?? makeId
  }

  create(input: ChangeIntentInput): SpatialChangeIntent {
    const paths = changedPaths(input.current, input.proposed)
    const fieldByPath = new Map(input.fieldSchema.map((field) => [field.path, field]))
    const diff = paths.map((path) => ({ path, from: input.current[path] ?? null, to: input.proposed[path] ?? null }))
    const candidate = {
      schema_version: SPATIAL_SCHEMA_VERSIONS.changeIntent,
      intent_id: input.intentId ?? this.idFactory('change'),
      workspace_id: input.workspaceId,
      node_id: input.nodeId,
      target: input.target,
      current: input.current,
      proposed: input.proposed,
      field_schema: input.fieldSchema.map((field) => ({ ...field, unit: field.unit ?? null, minimum: field.minimum ?? null, maximum: field.maximum ?? null, allowed_values: [...(field.allowed_values ?? [])] })),
      diff,
      state: 'PROPOSED',
      actor_ref: input.actorRef,
      idempotency_key: input.idempotencyKey,
      current_revision: input.currentRevision,
      source: input.source,
      workspace_session_ref: input.workspaceSessionRef ?? null,
      natural_language_summary: input.naturalLanguageSummary ?? null,
      provenance: { source_ref: input.provenance?.sourceRef ?? null, correlation_id: input.provenance?.correlationId ?? null, captured_at: (input.now ?? new Date()).toISOString() },
      created_at: (input.now ?? new Date()).toISOString(),
      updated_at: (input.now ?? new Date()).toISOString(),
    }
    for (const path of paths) {
      const field = fieldByPath.get(path)
      if (!field) throw new ChangeIntentError('INVALID', `field ${path} is not declared`)
      if (field.editable === false) throw new ChangeIntentError('INVALID', `field ${path} is not editable`)
      if (field.required && (candidate.proposed as Record<string, ChangeValue>)[path] === null) throw new ChangeIntentError('INVALID', `field ${path} is required`)
    }
    const parsed = parseSpatialChangeIntent(candidate)
    if (!parsed.ok) throw new ChangeIntentError('INVALID', `change intent is invalid at ${parsed.diagnostic.path}`)
    return parsed.data
  }

  validate(intent: SpatialChangeIntent, options: { currentRevision: number; agentOnline?: boolean; capabilities?: readonly string[]; occupied?: (path: string, value: ChangeValue) => boolean }): ChangeIntentValidation {
    const changed = intent.diff.map((entry) => entry.path)
    let state: ChangeIntentValidation['state'] = 'VALID'
    const alternatives: string[] = []
    if (!options.agentOnline) state = 'AGENT_OFFLINE'
    else if (intent.current_revision < options.currentRevision || intent.target.revision < options.currentRevision) { state = 'STALE'; alternatives.push(`Refresh ${intent.target.type} ${intent.target.id} and review the proposed values.`) }
    else if (changed.some((path) => !(options.capabilities ?? []).includes(`${intent.target.type}:change:${path}`) && !(options.capabilities ?? []).includes(`${intent.target.type}:change`))) { state = 'UNAUTHORIZED_FIELD'; alternatives.push('Use a field exposed by the current capability grant or open Advanced controls.') }
    else if (intent.diff.some((entry) => options.occupied?.(entry.path, entry.to))) { state = 'OCCUPIED'; alternatives.push('Choose an unused value and validate again.') }
    const parsed = parseSpatialChangeIntent({ ...intent, state, updated_at: new Date().toISOString() })
    if (!parsed.ok) throw new ChangeIntentError('INVALID', 'stored change intent failed validation')
    return { state, intent: parsed.data, changedPaths: changed, alternatives }
  }

  apply(intent: SpatialChangeIntent, options: { confirm: boolean; validation: ChangeIntentValidation; applyCanonical: (intent: SpatialChangeIntent) => { revision: number; resultRef: string } }): ChangeIntentApplyResult {
    if (!options.confirm) throw new ChangeIntentError('NOT_EXPLICIT', 'apply requires explicit confirmation')
    if (options.validation.state !== 'VALID') throw new ChangeIntentError('INVALID', `cannot apply intent in ${options.validation.state} state`)
    const key = `${intent.actor_ref}:${intent.idempotency_key}`
    const duplicate = this.byIdempotency.get(key)
    if (duplicate) return { ...duplicate, status: 'duplicate' }
    const applied = options.applyCanonical(intent)
    const result: ChangeIntentApplyResult = { status: 'applied', intent: { ...intent, state: 'APPLIED' }, revision: applied.revision, resultRef: applied.resultRef }
    this.byIdempotency.set(key, result)
    return result
  }

  hasIdempotencyKey(actorRef: string, idempotencyKey: string): boolean {
    return this.byIdempotency.has(`${actorRef}:${idempotencyKey}`)
  }
}

export const SpatialChangeIntentService = ChangeIntentService

export function createChangeIntentService(options?: ConstructorParameters<typeof ChangeIntentService>[0]): ChangeIntentService {
  return new ChangeIntentService(options)
}
