import {
  parseSpatialEntity,
  parseSpatialRelation,
  parseSpatialViewport,
  parseSpatialWorkspace,
  spatialTimestampSchema,
  type SpatialCanonicalEntity,
  type SpatialRelationContract,
  type SpatialViewportSnapshot,
  type SpatialWorkspaceSnapshot,
} from '@/spatial/contracts'
import { z } from 'zod'

import { assertSpatialScope, SpatialApiError, type SpatialTransport } from '../data/transport'
import type { SpatialNodeScope } from '../data/scope'
import {
  SpatialWorkspaceConflict,
  assertWorkspaceOwnership,
  cloneSpatialViewportSnapshot,
  cloneSpatialWorkspaceSnapshot,
  createSpatialPresentationSnapshot,
  resetSpatialPresentation,
} from './model'

export type SpatialSemanticOperation = {
  operation_id: string
  idempotency_key: string
  actor_ref: string
  expected_revision: number
  kind: 'upsert-entity' | 'upsert-relation' | 'archive-entity'
  payload: unknown
  agent_binding_revision?: number
}

export type SpatialWorkspaceChange = {
  change_id: string
  workspace_id: string
  node_id: string
  semantic_revision: number
  operation_id: string
  actor_ref: string
  kind: SpatialSemanticOperation['kind']
  occurred_at: string
  audit_recorded: true
}

const workspaceChangeSchema = z.object({
  change_id: z.string().min(1),
  workspace_id: z.string().min(1),
  node_id: z.string().min(1),
  semantic_revision: z.number().int().nonnegative(),
  operation_id: z.string().min(1),
  actor_ref: z.string().min(1),
  kind: z.enum(['upsert-entity', 'upsert-relation', 'archive-entity']),
  occurred_at: z.string().min(1),
  audit_recorded: z.literal(true),
}).strip()

export type SpatialSemanticMutationResult = {
  snapshot: SpatialWorkspaceSnapshot
  change: SpatialWorkspaceChange
  protocol_event_emitted: boolean
  audit_recorded: true
}

export type SpatialPresentationResult = {
  presentation: SpatialViewportSnapshot
  recovered: boolean
  protocol_event_emitted: false
}

export interface SpatialWorkspaceRepository {
  getSnapshot: (scope: SpatialNodeScope) => Promise<SpatialWorkspaceSnapshot>
  getChanges: (scope: SpatialNodeScope, afterRevision: number) => Promise<SpatialWorkspaceChange[]>
  applySemanticOperation: (scope: SpatialNodeScope, operation: SpatialSemanticOperation) => Promise<SpatialSemanticMutationResult>
  putPresentation: (scope: SpatialNodeScope, presentation: unknown) => Promise<SpatialPresentationResult>
  resetPresentation: (scope: SpatialNodeScope, deviceId: string) => Promise<SpatialPresentationResult>
  getEntity: (scope: SpatialNodeScope, canonicalRef: string) => Promise<SpatialCanonicalEntity | null>
  getRelation: (scope: SpatialNodeScope, relationRef: string) => Promise<SpatialRelationContract | null>
}

export type InMemoryWorkspaceRepositoryOptions = {
  authorize?: (scope: SpatialNodeScope, operation: SpatialSemanticOperation) => boolean
  failNextPersistence?: boolean
  agentBindingRevision?: number
}

export class InMemorySpatialWorkspaceRepository implements SpatialWorkspaceRepository {
  private snapshot: SpatialWorkspaceSnapshot
  private readonly presentations = new Map<string, unknown>()
  private readonly changes: SpatialWorkspaceChange[] = []
  private readonly operations = new Map<string, SpatialSemanticMutationResult>()
  private readonly authorize?: InMemoryWorkspaceRepositoryOptions['authorize']
  private failNextPersistence: boolean
  private agentBindingRevision: number

  constructor(snapshot: SpatialWorkspaceSnapshot, options: InMemoryWorkspaceRepositoryOptions = {}) {
    const parsed = parseSpatialWorkspace(snapshot)
    if (!parsed.ok) throw new SpatialWorkspaceConflict('CORRUPT_PRESENTATION', 'Initial Workspace snapshot is invalid.')
    this.snapshot = cloneSpatialWorkspaceSnapshot(parsed.data)
    this.authorize = options.authorize
    this.failNextPersistence = options.failNextPersistence ?? false
    this.agentBindingRevision = options.agentBindingRevision ?? 0
  }

  /** Test/control seam for an Agent replacement racing a semantic operation. */
  setAgentBindingRevision(revision: number): void {
    this.agentBindingRevision = revision
  }

  /** Test seam that simulates a durable-store failure before commit. */
  failNextWrite(): void {
    this.failNextPersistence = true
  }

  async getSnapshot(scope: SpatialNodeScope): Promise<SpatialWorkspaceSnapshot> {
    assertWorkspaceOwnership(this.snapshot, scope)
    return cloneSpatialWorkspaceSnapshot(this.snapshot)
  }

  async getChanges(scope: SpatialNodeScope, afterRevision: number): Promise<SpatialWorkspaceChange[]> {
    assertWorkspaceOwnership(this.snapshot, scope)
    if (!Number.isInteger(afterRevision) || afterRevision < 0) throw new SpatialWorkspaceConflict('VALIDATION', 'Workspace change cursor is invalid.')
    return this.changes.filter((change) => change.semantic_revision > afterRevision).map((change) => ({ ...change }))
  }

  async applySemanticOperation(scope: SpatialNodeScope, operation: SpatialSemanticOperation): Promise<SpatialSemanticMutationResult> {
    assertWorkspaceOwnership(this.snapshot, scope)
    if (!operation.operation_id?.trim() || !operation.idempotency_key?.trim() || !operation.actor_ref?.trim()) {
      throw new SpatialWorkspaceConflict('VALIDATION', 'Semantic operations require operation, idempotency, and actor references.')
    }
    if (!Number.isInteger(operation.expected_revision) || operation.expected_revision < 0) {
      throw new SpatialWorkspaceConflict('VALIDATION', 'Semantic operations require a non-negative expected revision.')
    }
    const existing = this.operations.get(operation.idempotency_key)
    if (existing) return structuredClone(existing)
    if (!this.authorize?.(scope, operation) && this.authorize) throw new SpatialWorkspaceConflict('UNAUTHORIZED', 'Operator is not authorized for this semantic operation.')
    if (operation.expected_revision !== this.snapshot.semantic_revision) throw new SpatialWorkspaceConflict('STALE_REVISION', 'Workspace revision changed before the operation was applied.')
    let nextSnapshot = cloneSpatialWorkspaceSnapshot(this.snapshot)
    if (operation.kind === 'upsert-entity') {
      const parsed = parseSpatialEntity(operation.payload)
      if (!parsed.ok) throw new SpatialWorkspaceConflict('PARTIAL_PERSISTENCE', 'Entity payload failed the shared contract.')
      assertSpatialScope(scope, parsed.data.node_id)
      nextSnapshot = {
        ...nextSnapshot,
        revision: nextSnapshot.revision + 1,
        semantic_revision: nextSnapshot.semantic_revision + 1,
        updated_at: parsed.data.updated_at,
        entities: [...nextSnapshot.entities.filter((entity) => entity.canonical_ref !== parsed.data.canonical_ref), parsed.data],
      }
    } else if (operation.kind === 'upsert-relation') {
      const parsed = parseSpatialRelation(operation.payload)
      if (!parsed.ok) throw new SpatialWorkspaceConflict('PARTIAL_PERSISTENCE', 'Relation payload failed the shared contract.')
      assertSpatialScope(scope, parsed.data.node_id)
      nextSnapshot = {
        ...nextSnapshot,
        revision: nextSnapshot.revision + 1,
        semantic_revision: nextSnapshot.semantic_revision + 1,
        updated_at: parsed.data.updated_at,
        relations: [...nextSnapshot.relations.filter((relation) => relation.relation_id !== parsed.data.relation_id), parsed.data],
      }
    } else {
      const payload = operation.payload as { canonical_ref?: unknown }
      const canonicalRef = typeof payload?.canonical_ref === 'string' ? payload.canonical_ref : null
      if (!canonicalRef) throw new SpatialWorkspaceConflict('PARTIAL_PERSISTENCE', 'Archive operation needs a canonical_ref.')
      const entity = nextSnapshot.entities.find((candidate) => candidate.canonical_ref === canonicalRef)
      if (!entity) throw new SpatialWorkspaceConflict('PARTIAL_PERSISTENCE', 'Archive operation target was not found.')
      const now = spatialTimestampSchema.parse(new Date())
      nextSnapshot = {
        ...nextSnapshot,
        revision: nextSnapshot.revision + 1,
        semantic_revision: nextSnapshot.semantic_revision + 1,
        updated_at: now,
        entities: nextSnapshot.entities.map((candidate) => candidate.canonical_ref === canonicalRef
          ? { ...candidate, state: 'ARCHIVED', availability: 'UNAVAILABLE', updated_at: now }
          : candidate),
      }
    }
    if (this.agentBindingRevision !== (operation as SpatialSemanticOperation & { agent_binding_revision?: number }).agent_binding_revision && (operation as SpatialSemanticOperation & { agent_binding_revision?: number }).agent_binding_revision !== undefined) {
      throw new SpatialWorkspaceConflict('AGENT_REPLACED', 'Primary Agent binding changed while the operation was in flight.')
    }
    if (this.failNextPersistence) {
      this.failNextPersistence = false
      throw new SpatialWorkspaceConflict('PARTIAL_PERSISTENCE', 'Semantic persistence failed before the operation was committed.')
    }
    this.snapshot = nextSnapshot
    const change: SpatialWorkspaceChange = {
      change_id: `change-${this.snapshot.semantic_revision}`,
      workspace_id: this.snapshot.workspace_id,
      node_id: this.snapshot.node_id,
      semantic_revision: this.snapshot.semantic_revision,
      operation_id: operation.operation_id,
      actor_ref: operation.actor_ref,
      kind: operation.kind,
      occurred_at: this.snapshot.updated_at,
      audit_recorded: true,
    }
    const result: SpatialSemanticMutationResult = { snapshot: cloneSpatialWorkspaceSnapshot(this.snapshot), change, protocol_event_emitted: true, audit_recorded: true }
    this.operations.set(operation.idempotency_key, result)
    this.changes.push(change)
    return structuredClone(result)
  }

  async putPresentation(scope: SpatialNodeScope, presentationInput: unknown): Promise<SpatialPresentationResult> {
    const parsed = parseSpatialViewport(presentationInput)
    if (!parsed.ok) throw new SpatialWorkspaceConflict('CORRUPT_PRESENTATION', 'Presentation state failed the shared contract.')
    assertWorkspaceOwnership(this.snapshot, scope)
    if (parsed.data.node_id !== scope.node_id || parsed.data.workspace_id !== this.snapshot.workspace_id) throw new SpatialWorkspaceConflict('NODE_MISMATCH', 'Presentation targets a different Node or Workspace.')
    this.presentations.set(parsed.data.device_id, cloneSpatialViewportSnapshot(parsed.data))
    return { presentation: cloneSpatialViewportSnapshot(parsed.data), recovered: false, protocol_event_emitted: false }
  }

  async resetPresentation(scope: SpatialNodeScope, deviceId: string): Promise<SpatialPresentationResult> {
    assertWorkspaceOwnership(this.snapshot, scope)
    const current = this.presentations.get(deviceId)
    let parsed = current ? parseSpatialViewport(current) : { ok: false as const, diagnostic: { code: 'MALFORMED_PAYLOAD' as const } }
    const fallback = createSpatialPresentationSnapshot(this.snapshot, deviceId)
    if (!parsed.ok) {
      this.presentations.set(deviceId, fallback)
      return { presentation: fallback, recovered: true, protocol_event_emitted: false }
    }
    const reset = resetSpatialPresentation(parsed.data)
    this.presentations.set(deviceId, reset)
    return { presentation: reset, recovered: false, protocol_event_emitted: false }
  }

  async getEntity(scope: SpatialNodeScope, canonicalRef: string): Promise<SpatialCanonicalEntity | null> {
    assertWorkspaceOwnership(this.snapshot, scope)
    const entity = this.snapshot.entities.find((candidate) => candidate.canonical_ref === canonicalRef)
    return entity ? structuredClone(entity) : null
  }

  async getRelation(scope: SpatialNodeScope, relationRef: string): Promise<SpatialRelationContract | null> {
    assertWorkspaceOwnership(this.snapshot, scope)
    const relation = this.snapshot.relations.find((candidate) => candidate.relation_id === relationRef)
    return relation ? structuredClone(relation) : null
  }
}

export type HttpSpatialWorkspaceRepositoryOptions = { transport: SpatialTransport }

/** REST adapter for the Node-owned Workspace endpoints; no renderer dependency. */
export function createHttpSpatialWorkspaceRepository({ transport }: HttpSpatialWorkspaceRepositoryOptions): SpatialWorkspaceRepository {
  async function request(path: string, scope: SpatialNodeScope, method: 'GET' | 'POST' | 'PUT', body?: unknown, headers?: Record<string, string>) {
    return transport.request({ path, scope, method, body, headers })
  }
  return {
    async getSnapshot(scope) {
      const path = '/operators/spatial/workspace'
      const parsed = parseSpatialWorkspace(await request(path, scope, 'GET'))
      if (!parsed.ok) throw new SpatialApiError('malformed', 'Workspace snapshot contract rejected.', path)
      assertSpatialScope(scope, parsed.data.node_id)
      return parsed.data
    },
    async getChanges(scope, afterRevision) {
      if (!Number.isInteger(afterRevision) || afterRevision < 0) throw new SpatialApiError('validation', 'Workspace change cursor is invalid.', '/operators/spatial/workspace/changes')
      const path = `/operators/spatial/workspace/changes?after_revision=${afterRevision}`
      const raw = await request(path, scope, 'GET')
      if (typeof raw !== 'object' || raw === null || !Array.isArray((raw as Record<string, unknown>).items)) throw new SpatialApiError('malformed', 'Workspace changes contract rejected.', path)
      const changes = (raw as { items: unknown[] }).items.map((item) => workspaceChangeSchema.safeParse(item))
      if (changes.some((result) => !result.success)) throw new SpatialApiError('malformed', 'Workspace changes contract rejected.', path)
      const parsed = changes.map((result) => (result as { success: true; data: SpatialWorkspaceChange }).data)
      for (const change of parsed) assertSpatialScope(scope, change.node_id)
      return parsed
    },
    async applySemanticOperation(scope, operation) {
      const path = '/operators/spatial/workspace/operations'
      const raw = await request(path, scope, 'POST', operation, {
        'X-AiDN-Idempotency-Key': operation.idempotency_key,
        'X-AiDN-Correlation-Id': operation.operation_id,
      })
      if (typeof raw !== 'object' || raw === null) throw new SpatialApiError('malformed', 'Workspace mutation contract rejected.', path)
      const record = raw as Record<string, unknown>
      const parsedSnapshot = parseSpatialWorkspace(record.snapshot)
      if (!parsedSnapshot.ok || typeof record.change !== 'object' || record.change === null || record.audit_recorded !== true) throw new SpatialApiError('malformed', 'Workspace mutation contract rejected.', path)
      return { snapshot: parsedSnapshot.data, change: record.change as SpatialWorkspaceChange, protocol_event_emitted: record.protocol_event_emitted === true, audit_recorded: true as const }
    },
    async putPresentation(scope, presentation) {
      const path = '/operators/spatial/workspace/presentation'
      const parsed = parseSpatialViewport(presentation)
      if (!parsed.ok) throw new SpatialApiError('malformed', 'Presentation contract rejected.', path)
      const raw = await request(path, scope, 'PUT', parsed.data)
      const result = parseSpatialViewport(raw)
      if (!result.ok) throw new SpatialApiError('malformed', 'Presentation contract rejected.', path)
      return { presentation: result.data, recovered: false, protocol_event_emitted: false }
    },
    async resetPresentation(scope, deviceId) {
      const path = '/operators/spatial/workspace/presentation/reset'
      const raw = await request(path, scope, 'POST', { device_id: deviceId })
      const result = parseSpatialViewport(raw)
      if (!result.ok) throw new SpatialApiError('malformed', 'Presentation reset contract rejected.', path)
      return { presentation: result.data, recovered: false, protocol_event_emitted: false }
    },
    async getEntity(scope, canonicalRef) {
      const path = `/operators/spatial/entities/${encodeURIComponent(canonicalRef)}`
      const parsed = parseSpatialEntity(await request(path, scope, 'GET'))
      if (!parsed.ok) throw new SpatialApiError('malformed', 'Entity reference contract rejected.', path)
      assertSpatialScope(scope, parsed.data.node_id)
      return parsed.data
    },
    async getRelation(scope, relationRef) {
      const path = `/operators/spatial/relations/${encodeURIComponent(relationRef)}`
      const parsed = parseSpatialRelation(await request(path, scope, 'GET'))
      if (!parsed.ok) throw new SpatialApiError('malformed', 'Relation reference contract rejected.', path)
      assertSpatialScope(scope, parsed.data.node_id)
      return parsed.data
    },
  }
}
