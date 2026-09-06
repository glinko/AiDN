import {
  parseSpatialGeneratedObject,
  SPATIAL_SCHEMA_VERSIONS,
  type SpatialGeneratedObject,
  type SpatialGeneratedObjectKind,
  type SpatialGeneratedObjectState,
} from '@/spatial/contracts'

import { SessionGraphError, WorkspaceSessionGraph } from './session-graph'

export type GeneratedObjectErrorCode =
  | 'SESSION_NOT_FOUND'
  | 'SOURCE_TURN_NOT_FOUND'
  | 'OBJECT_NOT_FOUND'
  | 'STALE_OBJECT'
  | 'OBJECT_LIMIT'
  | 'INVALID_OBJECT'

export class GeneratedObjectError extends Error {
  readonly code: GeneratedObjectErrorCode

  constructor(code: GeneratedObjectErrorCode, message: string) {
    super(message)
    this.name = 'GeneratedObjectError'
    this.code = code
  }
}

export type GeneratedObjectServiceOptions = {
  graph: WorkspaceSessionGraph
  workspaceId: string
  nodeId: string
  now?: () => Date
  idFactory?: (prefix: string) => string
  maxObjectsPerSession?: number
}

function defaultId(prefix: string): string {
  const uuid = typeof globalThis.crypto?.randomUUID === 'function' ? globalThis.crypto.randomUUID() : `${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`
  return `${prefix}_${uuid}`
}

function clone<T>(value: T): T {
  if (typeof structuredClone === 'function') return structuredClone(value)
  return JSON.parse(JSON.stringify(value)) as T
}

function iso(now: () => Date): string {
  return now().toISOString()
}

export function mapPresentationToGeneratedObjectKind(value: string): SpatialGeneratedObjectKind {
  const normalized = value.toUpperCase()
  if (normalized === 'TABLE' || normalized === 'CHART' || normalized === 'FILE' || normalized === 'REPORT') return normalized
  return 'OBJECT'
}

/** Artifact-like outputs remain addressable objects; collapsing a frame never deletes them. */
export class GeneratedObjectService {
  private readonly graph: WorkspaceSessionGraph
  private readonly workspaceId: string
  private readonly nodeId: string
  private readonly now: () => Date
  private readonly idFactory: (prefix: string) => string
  private readonly maxObjectsPerSession: number
  private readonly objects = new Map<string, SpatialGeneratedObject>()

  constructor(options: GeneratedObjectServiceOptions) {
    this.graph = options.graph
    this.workspaceId = options.workspaceId
    this.nodeId = options.nodeId
    this.now = options.now ?? (() => new Date())
    this.idFactory = options.idFactory ?? defaultId
    this.maxObjectsPerSession = Math.max(1, options.maxObjectsPerSession ?? 64)
  }

  create(input: {
    sessionId: string
    sourceTurnId: string
    actorRef: string
    kind: SpatialGeneratedObjectKind | string
    title: string
    summary?: string
    semanticAnchor?: string
    placement?: { region?: 'WORKSPACE' | 'FOCUS' | 'ARTIFACT'; focus_required?: boolean }
    data?: Record<string, unknown>
  }): SpatialGeneratedObject {
    const session = this.graph.getSession(input.sessionId)
    if (!session) throw new GeneratedObjectError('SESSION_NOT_FOUND', 'session was not found')
    if (!session.turn_refs.includes(input.sourceTurnId)) throw new GeneratedObjectError('SOURCE_TURN_NOT_FOUND', 'source turn is not part of the session')
    const count = [...this.objects.values()].filter((object) => object.session_id === input.sessionId && object.state !== 'ARCHIVED').length
    if (count >= this.maxObjectsPerSession) throw new GeneratedObjectError('OBJECT_LIMIT', 'generated object bound exceeded')
    const timestamp = iso(this.now)
    const candidate: SpatialGeneratedObject = {
      schema_version: SPATIAL_SCHEMA_VERSIONS.generatedObject,
      object_id: this.idFactory('object'),
      session_id: input.sessionId,
      workspace_id: this.workspaceId,
      node_id: this.nodeId,
      source_turn_id: input.sourceTurnId,
      revision: 0,
      kind: mapPresentationToGeneratedObjectKind(input.kind),
      state: 'ACTIVE',
      title: input.title.trim() || 'Generated object',
      summary: input.summary?.trim() ?? '',
      source_ref: input.sourceTurnId,
      semantic_anchor: input.semanticAnchor ?? session.semantic_anchor,
      placement: {
        region: input.placement?.region ?? (input.kind === 'REPORT' || input.kind === 'CHART' ? 'FOCUS' : 'WORKSPACE'),
        focus_required: input.placement?.focus_required ?? (input.kind === 'REPORT' || input.kind === 'CHART'),
      },
      data: { ...(input.data ?? {}) },
      created_at: timestamp,
      updated_at: timestamp,
    }
    const parsed = parseSpatialGeneratedObject(candidate)
    if (!parsed.ok) throw new GeneratedObjectError('INVALID_OBJECT', 'generated object is malformed')
    this.objects.set(parsed.data.object_id, parsed.data)
    this.graph.appendObject(input.sessionId, parsed.data.object_id, input.actorRef, parsed.data.revision)
    try {
      this.graph.addRelation({ type: 'PRODUCED', sourceRef: input.sourceTurnId, targetRef: parsed.data.object_id, actorRef: input.actorRef, sourceRevision: 0, targetRevision: parsed.data.revision })
    } catch (error) {
      if (!(error instanceof SessionGraphError && error.code === 'STALE_REFERENCE')) throw error
    }
    return clone(parsed.data)
  }

  get(objectId: string): SpatialGeneratedObject | null {
    const object = this.objects.get(objectId)
    return object ? clone(object) : null
  }

  list(sessionId?: string): SpatialGeneratedObject[] {
    return [...this.objects.values()].filter((object) => !sessionId || object.session_id === sessionId).map(clone)
  }

  update(objectId: string, patch: { title?: string; summary?: string; data?: Record<string, unknown>; state?: SpatialGeneratedObjectState }, expectedRevision?: number): SpatialGeneratedObject {
    const object = this.require(objectId)
    if (expectedRevision !== undefined && expectedRevision !== object.revision) throw new GeneratedObjectError('STALE_OBJECT', 'generated object revision is stale')
    if (patch.title !== undefined) object.title = patch.title.trim() || object.title
    if (patch.summary !== undefined) object.summary = patch.summary.trim()
    if (patch.data !== undefined) object.data = { ...object.data, ...patch.data }
    if (patch.state !== undefined) object.state = patch.state
    object.revision += 1
    object.updated_at = iso(this.now)
    this.objects.set(object.object_id, object)
    return clone(object)
  }

  collapse(objectId: string, expectedRevision?: number): SpatialGeneratedObject {
    return this.update(objectId, { state: 'COLLAPSED' }, expectedRevision)
  }

  pin(objectId: string, expectedRevision?: number): SpatialGeneratedObject {
    return this.update(objectId, { state: 'PINNED' }, expectedRevision)
  }

  archive(objectId: string, expectedRevision?: number): SpatialGeneratedObject {
    return this.update(objectId, { state: 'ARCHIVED' }, expectedRevision)
  }

  restore(objectId: string, expectedRevision?: number): SpatialGeneratedObject {
    return this.update(objectId, { state: 'ACTIVE' }, expectedRevision)
  }

  snapshot(): SpatialGeneratedObject[] {
    return this.list()
  }

  restoreSnapshot(objects: readonly SpatialGeneratedObject[]): void {
    this.objects.clear()
    for (const object of objects) {
      const parsed = parseSpatialGeneratedObject(object)
      if (!parsed.ok || parsed.data.workspace_id !== this.workspaceId || parsed.data.node_id !== this.nodeId) throw new GeneratedObjectError('INVALID_OBJECT', 'cannot restore generated object')
      this.objects.set(parsed.data.object_id, clone(parsed.data))
    }
  }

  private require(objectId: string): SpatialGeneratedObject {
    const object = this.objects.get(objectId)
    if (!object) throw new GeneratedObjectError('OBJECT_NOT_FOUND', 'generated object was not found')
    return object
  }
}

export const SpatialGeneratedObjectService = GeneratedObjectService

export function createGeneratedObjectService(options: GeneratedObjectServiceOptions): GeneratedObjectService {
  return new GeneratedObjectService(options)
}
