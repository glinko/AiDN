import {
  parseSpatialSemanticRelation,
  SPATIAL_SCHEMA_VERSIONS,
  type SpatialSemanticRelation,
  type SpatialSemanticRelationState,
  type SpatialSemanticRelationType,
} from '@/spatial/contracts'

import { CanonicalReferenceRegistry } from './reference-registry'

export type SemanticRelationInput = {
  relationId: string
  relationType: SpatialSemanticRelationType
  sourceRef: string
  targetRef: string
  sourceRevision: number
  targetRevision: number
  label?: string
  aggregationKey?: string | null
  state?: SpatialSemanticRelationState
  pulseCount?: number
  offscreenAnchor?: { x: number; y: number; z: number } | null
}

export type SemanticRelationInspection = {
  relation: SpatialSemanticRelation
  sourceLabel: string
  targetLabel: string
  directionLabel: string
  chunkCount: number
}

export type SemanticRelationVisualPath = {
  relationId: string
  points: readonly [{ x: number; y: number; z: number }, { x: number; y: number; z: number }]
  offscreenAnchor: { x: number; y: number; z: number } | null
  pulseCount: number
  label: string
}

export type SemanticRelationServiceOptions = {
  workspaceId: string
  nodeId: string
  registry: CanonicalReferenceRegistry
  now?: () => Date
  maxVisibleRelations?: number
}

export type SemanticRelationErrorCode = 'SCOPE_MISMATCH' | 'UNKNOWN_REFERENCE' | 'INVALID_RELATION'

export class SemanticRelationError extends Error {
  readonly code: SemanticRelationErrorCode

  constructor(code: SemanticRelationErrorCode, message: string) {
    super(message)
    this.name = 'SemanticRelationError'
    this.code = code
  }
}

function relationLabel(relationType: SpatialSemanticRelationType): string {
  return relationType.replaceAll('_', ' ').toLowerCase()
}

/** Relations are semantic records; transport frames are aggregated by key. */
export class SemanticRelationService {
  private readonly relations = new Map<string, SpatialSemanticRelation>()
  private readonly streamChunks = new Map<string, number>()
  private readonly options: SemanticRelationServiceOptions

  constructor(options: SemanticRelationServiceOptions) {
    this.options = options
  }

  upsert(input: SemanticRelationInput): SpatialSemanticRelation {
    if (!input.relationId.trim() || !input.sourceRef.trim() || !input.targetRef.trim() || input.sourceRef === input.targetRef) {
      throw new SemanticRelationError('INVALID_RELATION', 'relation id and distinct source/target references are required')
    }
    const source = this.options.registry.resolveInScope(this.options.workspaceId, this.options.nodeId, input.sourceRef)
    const target = this.options.registry.resolveInScope(this.options.workspaceId, this.options.nodeId, input.targetRef)
    if (!source || !target) throw new SemanticRelationError('UNKNOWN_REFERENCE', 'relation endpoints must resolve in the same workspace')
    const now = (this.options.now ?? (() => new Date()))().toISOString()
    const current = this.relations.get(input.relationId)
    const relation: SpatialSemanticRelation = {
      schema_version: SPATIAL_SCHEMA_VERSIONS.semanticRelation,
      relation_id: input.relationId,
      workspace_id: this.options.workspaceId,
      node_id: this.options.nodeId,
      revision: (current?.revision ?? 0) + 1,
      relation_type: input.relationType,
      source_ref: input.sourceRef,
      target_ref: input.targetRef,
      source_revision: input.sourceRevision,
      target_revision: input.targetRevision,
      state: input.state ?? current?.state ?? 'ACTIVE',
      label: input.label?.trim() || relationLabel(input.relationType),
      pulse_count: input.pulseCount ?? current?.pulse_count ?? 0,
      offscreen_anchor: input.offscreenAnchor ?? current?.offscreen_anchor ?? null,
      aggregation_key: input.aggregationKey ?? current?.aggregation_key ?? null,
      created_at: current?.created_at ?? now,
      updated_at: now,
    }
    const parsed = parseSpatialSemanticRelation(relation)
    if (!parsed.ok) throw new SemanticRelationError('INVALID_RELATION', `relation invalid at ${parsed.diagnostic.path}`)
    this.relations.set(parsed.data.relation_id, parsed.data)
    return { ...parsed.data }
  }

  aggregateStreamChunk(input: Omit<SemanticRelationInput, 'relationType'> & { relationType?: SpatialSemanticRelationType; streamKey?: string }): SemanticRelationInspection {
    const streamKey = input.streamKey ?? input.relationId
    const chunkCount = (this.streamChunks.get(streamKey) ?? 0) + 1
    this.streamChunks.set(streamKey, chunkCount)
    const relation = this.upsert({ ...input, relationType: input.relationType ?? 'STREAMING', aggregationKey: input.aggregationKey ?? streamKey, pulseCount: chunkCount })
    return this.inspect(relation.relation_id, chunkCount)
  }

  pulse(relationId: string): SemanticRelationInspection {
    const relation = this.relations.get(relationId)
    if (!relation) throw new SemanticRelationError('INVALID_RELATION', `unknown relation: ${relationId}`)
    const count = (this.streamChunks.get(relation.aggregation_key ?? relationId) ?? 0) + 1
    this.streamChunks.set(relation.aggregation_key ?? relationId, count)
    this.upsert({
      relationId,
      relationType: relation.relation_type,
      sourceRef: relation.source_ref,
      targetRef: relation.target_ref,
      sourceRevision: relation.source_revision,
      targetRevision: relation.target_revision,
      label: relation.label,
      aggregationKey: relation.aggregation_key,
      state: relation.state,
      pulseCount: count,
      offscreenAnchor: relation.offscreen_anchor,
    })
    return this.inspect(relationId, count)
  }

  inspect(relationId: string, chunkCount = this.streamChunks.get(relationId) ?? 0): SemanticRelationInspection {
    const relation = this.relations.get(relationId)
    if (!relation) throw new SemanticRelationError('INVALID_RELATION', `unknown relation: ${relationId}`)
    const source = this.options.registry.resolve(relation.source_ref)
    const target = this.options.registry.resolve(relation.target_ref)
    return {
      relation: { ...relation },
      sourceLabel: source.entity_id,
      targetLabel: target.entity_id,
      directionLabel: `${relation.label}: ${source.entity_id} → ${target.entity_id}`,
      chunkCount,
    }
  }

  inspectKeyboard(relationId: string): SemanticRelationInspection {
    return this.inspect(relationId)
  }

  visualPath(relationId: string, sourcePosition: { x: number; y: number; z: number } | null, targetPosition: { x: number; y: number; z: number } | null): SemanticRelationVisualPath {
    const relation = this.relations.get(relationId)
    if (!relation) throw new SemanticRelationError('INVALID_RELATION', `unknown relation: ${relationId}`)
    const fallback = relation.offscreen_anchor ?? { x: 0, y: 0, z: -4 }
    return {
      relationId,
      points: [sourcePosition ?? fallback, targetPosition ?? fallback],
      offscreenAnchor: sourcePosition && targetPosition ? relation.offscreen_anchor : fallback,
      pulseCount: relation.pulse_count,
      label: relation.label,
    }
  }

  list(): SpatialSemanticRelation[] {
    return [...this.relations.values()].map((relation) => ({ ...relation }))
  }

  visibleRelations(max = this.options.maxVisibleRelations ?? 256): SpatialSemanticRelation[] {
    const bounded = Math.max(1, Math.min(10_000, max))
    return [...this.relations.values()]
      .filter((relation) => relation.state !== 'ARCHIVED' && relation.state !== 'UNAVAILABLE')
      .sort((left, right) => Number(right.state === 'ACTIVE') - Number(left.state === 'ACTIVE') || right.updated_at.localeCompare(left.updated_at))
      .slice(0, bounded)
      .map((relation) => ({ ...relation }))
  }

  setState(relationId: string, state: SpatialSemanticRelationState): SpatialSemanticRelation {
    const current = this.relations.get(relationId)
    if (!current) throw new SemanticRelationError('INVALID_RELATION', `unknown relation: ${relationId}`)
    return this.upsert({
      relationId,
      relationType: current.relation_type,
      sourceRef: current.source_ref,
      targetRef: current.target_ref,
      sourceRevision: current.source_revision,
      targetRevision: current.target_revision,
      label: current.label,
      aggregationKey: current.aggregation_key,
      state,
      pulseCount: current.pulse_count,
      offscreenAnchor: current.offscreen_anchor,
    })
  }
}

export const SemanticThreadService = SemanticRelationService
