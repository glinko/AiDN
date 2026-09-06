import {
  parseSpatialContextNode,
  parseSpatialWorkspaceSession,
  SPATIAL_SCHEMA_VERSIONS,
  type SpatialContextNode,
  type SpatialWorkspaceSession,
} from '@/spatial/contracts'

export const SPATIAL_CONTEXT_RELATIONS = [
  'CONTINUES_FROM',
  'USES_CONTEXT',
  'PRODUCED',
  'DELEGATED_TO',
  'USED_ENDPOINT',
  'RELATED_PROTOCOL_SESSION',
] as const

export type SpatialContextRelationType = (typeof SPATIAL_CONTEXT_RELATIONS)[number]

export type SpatialContextRelation = {
  relation_id: string
  type: SpatialContextRelationType
  workspace_id: string
  node_id: string
  source_ref: string
  target_ref: string
  source_revision: number
  target_revision: number
  actor_ref: string
  created_at: string
}

export type SessionGraphErrorCode =
  | 'SESSION_NOT_FOUND'
  | 'WRONG_WORKSPACE'
  | 'WRONG_NODE'
  | 'PARENT_ALREADY_SET'
  | 'CYCLE_DETECTED'
  | 'UNAUTHORIZED_REFERENCE'
  | 'STALE_REFERENCE'
  | 'PROTOCOL_SESSION_NOT_CHAT'
  | 'INVALID_GRAPH_RECORD'

export class SessionGraphError extends Error {
  readonly code: SessionGraphErrorCode

  constructor(code: SessionGraphErrorCode, message: string) {
    super(message)
    this.name = 'SessionGraphError'
    this.code = code
  }
}

export type WorkspaceSessionGraphOptions = {
  workspaceId: string
  nodeId: string
  now?: () => Date
  idFactory?: (prefix: string) => string
  authorizeReference?: (input: { actorRef: string; sourceRef: string; targetRef: string; relation: SpatialContextRelationType }) => boolean
}

export type CreateWorkspaceSessionInput = {
  sessionId?: string
  rootIntentId: string
  actorRef: string
  title?: string
  summary?: string
  semanticAnchor?: string
  parentSessionId?: string | null
  structuralParentRef?: string | null
  contextRefs?: readonly string[]
  initialRevision?: number
}

export type WorkspaceSessionGraphSnapshot = {
  sessions: SpatialWorkspaceSession[]
  contextNodes: SpatialContextNode[]
  relations: SpatialContextRelation[]
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

/** Durable Workspace Session + Context Graph boundary. */
export class WorkspaceSessionGraph {
  readonly workspaceId: string
  readonly nodeId: string
  private readonly now: () => Date
  private readonly idFactory: (prefix: string) => string
  private readonly authorizeReference?: WorkspaceSessionGraphOptions['authorizeReference']
  private readonly sessions = new Map<string, SpatialWorkspaceSession>()
  private readonly contextNodes = new Map<string, SpatialContextNode>()
  private readonly relations = new Map<string, SpatialContextRelation>()

  constructor(options: WorkspaceSessionGraphOptions) {
    this.workspaceId = options.workspaceId
    this.nodeId = options.nodeId
    this.now = options.now ?? (() => new Date())
    this.idFactory = options.idFactory ?? defaultId
    this.authorizeReference = options.authorizeReference
  }

  private assertScope(workspaceId: string, nodeId: string): void {
    if (workspaceId !== this.workspaceId) throw new SessionGraphError('WRONG_WORKSPACE', 'record belongs to another workspace')
    if (nodeId !== this.nodeId) throw new SessionGraphError('WRONG_NODE', 'record belongs to another Node')
  }

  createSession(input: CreateWorkspaceSessionInput): SpatialWorkspaceSession {
    const existing = input.sessionId ? this.sessions.get(input.sessionId) : undefined
    if (existing) return clone(existing)
    const timestamp = iso(this.now)
    const session: SpatialWorkspaceSession = {
      schema_version: SPATIAL_SCHEMA_VERSIONS.workspaceSession,
      session_id: input.sessionId ?? this.idFactory('session'),
      workspace_id: this.workspaceId,
      node_id: this.nodeId,
      revision: Math.max(0, input.initialRevision ?? 0),
      state: 'ACTIVE',
      root_intent_id: input.rootIntentId,
      parent_session_id: input.parentSessionId ?? null,
      structural_parent_ref: input.structuralParentRef ?? null,
      semantic_anchor: input.semanticAnchor ?? `session:${input.sessionId ?? 'new'}`,
      title: input.title?.trim() || 'New interaction',
      summary: input.summary?.trim() || '',
      turn_refs: [],
      object_refs: [],
      context_root_ref: '',
      artifact_ref: null,
      created_at: timestamp,
      updated_at: timestamp,
    }
    const contextRoot: SpatialContextNode = {
      schema_version: SPATIAL_SCHEMA_VERSIONS.contextNode,
      context_node_id: this.idFactory('context'),
      session_id: session.session_id,
      workspace_id: this.workspaceId,
      node_id: this.nodeId,
      revision: session.revision,
      kind: 'ROOT',
      parent_ref: null,
      context_refs: [...(input.contextRefs ?? [])],
      source_ref: input.rootIntentId,
      target_revisions: {},
      created_at: timestamp,
      updated_at: timestamp,
    }
    session.context_root_ref = contextRoot.context_node_id
    const parsedSession = parseSpatialWorkspaceSession(session)
    const parsedContext = parseSpatialContextNode(contextRoot)
    if (!parsedSession.ok || !parsedContext.ok) throw new SessionGraphError('INVALID_GRAPH_RECORD', 'session graph record is invalid')
    this.sessions.set(session.session_id, parsedSession.data)
    this.contextNodes.set(contextRoot.context_node_id, parsedContext.data)
    for (const contextRef of input.contextRefs ?? []) {
      this.addRelation({
        type: 'USES_CONTEXT',
        sourceRef: session.session_id,
        targetRef: contextRef,
        actorRef: input.actorRef,
        sourceRevision: session.revision,
        targetRevision: 0,
      })
    }
    if (input.parentSessionId) {
      this.addRelation({
        type: 'CONTINUES_FROM',
        sourceRef: session.session_id,
        targetRef: input.parentSessionId,
        actorRef: input.actorRef,
        sourceRevision: session.revision,
        targetRevision: this.sessions.get(input.parentSessionId)?.revision ?? 0,
      })
    }
    return clone(parsedSession.data)
  }

  branchSession(parentSessionId: string, input: Omit<CreateWorkspaceSessionInput, 'parentSessionId'>): SpatialWorkspaceSession {
    if (!this.sessions.has(parentSessionId)) throw new SessionGraphError('SESSION_NOT_FOUND', 'parent session was not found')
    return this.createSession({ ...input, parentSessionId, structuralParentRef: input.structuralParentRef ?? parentSessionId })
  }

  getSession(sessionId: string): SpatialWorkspaceSession | null {
    const value = this.sessions.get(sessionId)
    return value ? clone(value) : null
  }

  listSessions(): SpatialWorkspaceSession[] {
    return [...this.sessions.values()].map(clone)
  }

  getContextNode(contextNodeId: string): SpatialContextNode | null {
    const value = this.contextNodes.get(contextNodeId)
    return value ? clone(value) : null
  }

  listContextNodes(): SpatialContextNode[] {
    return [...this.contextNodes.values()].map(clone)
  }

  listRelations(): SpatialContextRelation[] {
    return [...this.relations.values()].map(clone)
  }

  addRelation(input: {
    relationId?: string
    type: SpatialContextRelationType
    sourceRef: string
    targetRef: string
    sourceRevision: number
    targetRevision: number
    actorRef: string
  }): SpatialContextRelation {
    if (input.relationId) {
      const existing = this.relations.get(input.relationId)
      if (existing) return clone(existing)
    }
    if (input.sourceRef === input.targetRef) throw new SessionGraphError('CYCLE_DETECTED', 'a graph node cannot relate to itself')
    const sourceSession = this.sessions.get(input.sourceRef)
    const targetSession = this.sessions.get(input.targetRef)
    if (input.type === 'RELATED_PROTOCOL_SESSION') {
      // A protocol relation is metadata only; it cannot create an operator chat.
      if (!sourceSession && !targetSession) throw new SessionGraphError('SESSION_NOT_FOUND', 'protocol relation has no known source')
    }
    if (input.type === 'CONTINUES_FROM' && (!sourceSession || !targetSession)) {
      throw new SessionGraphError('SESSION_NOT_FOUND', 'structural parent and child sessions are required')
    }
    if (sourceSession && targetSession) {
      if (input.type === 'CONTINUES_FROM' && this.relationsFor('CONTINUES_FROM', input.sourceRef).length > 0) {
        throw new SessionGraphError('PARENT_ALREADY_SET', 'a session can have only one structural parent')
      }
      if (input.type === 'CONTINUES_FROM' && this.reachable(input.targetRef, input.sourceRef)) {
        throw new SessionGraphError('CYCLE_DETECTED', 'context graph cycle detected')
      }
      if (input.sourceRevision < sourceSession.revision || input.targetRevision < targetSession.revision) {
        throw new SessionGraphError('STALE_REFERENCE', 'relation references an older revision')
      }
    }
    if (this.authorizeReference && !this.authorizeReference({ actorRef: input.actorRef, sourceRef: input.sourceRef, targetRef: input.targetRef, relation: input.type })) {
      throw new SessionGraphError('UNAUTHORIZED_REFERENCE', 'actor cannot reference this graph edge')
    }
    const relation: SpatialContextRelation = {
      relation_id: input.relationId ?? this.idFactory('relation'),
      type: input.type,
      workspace_id: this.workspaceId,
      node_id: this.nodeId,
      source_ref: input.sourceRef,
      target_ref: input.targetRef,
      source_revision: Math.max(0, input.sourceRevision),
      target_revision: Math.max(0, input.targetRevision),
      actor_ref: input.actorRef,
      created_at: iso(this.now),
    }
    this.relations.set(relation.relation_id, relation)
    return clone(relation)
  }

  appendTurn(sessionId: string, turnRef: string, actorRef: string, revision?: number): SpatialWorkspaceSession {
    const session = this.requireSession(sessionId)
    if (!session.turn_refs.includes(turnRef)) session.turn_refs.push(turnRef)
    session.revision = Math.max(session.revision + 1, revision ?? 0)
    session.updated_at = iso(this.now)
    this.sessions.set(session.session_id, session)
    this.contextNodes.set(session.context_root_ref, {
      ...this.contextNodes.get(session.context_root_ref)!,
      revision: session.revision,
      updated_at: session.updated_at,
    })
    this.addRelation({ type: 'PRODUCED', sourceRef: sessionId, targetRef: turnRef, actorRef, sourceRevision: session.revision, targetRevision: revision ?? 0 })
    return clone(session)
  }

  appendObject(sessionId: string, objectRef: string, actorRef: string, revision?: number): SpatialWorkspaceSession {
    const session = this.requireSession(sessionId)
    if (!session.object_refs.includes(objectRef)) session.object_refs.push(objectRef)
    session.revision = Math.max(session.revision + 1, revision ?? 0)
    session.updated_at = iso(this.now)
    this.sessions.set(session.session_id, session)
    this.addRelation({ type: 'PRODUCED', sourceRef: sessionId, targetRef: objectRef, actorRef, sourceRevision: session.revision, targetRevision: revision ?? 0 })
    return clone(session)
  }

  updateSession(sessionId: string, patch: Partial<Pick<SpatialWorkspaceSession, 'state' | 'title' | 'summary' | 'artifact_ref'>>, expectedRevision?: number): SpatialWorkspaceSession {
    const session = this.requireSession(sessionId)
    if (expectedRevision !== undefined && expectedRevision !== session.revision) throw new SessionGraphError('STALE_REFERENCE', 'session revision is stale')
    Object.assign(session, patch)
    session.revision += 1
    session.updated_at = iso(this.now)
    this.sessions.set(sessionId, session)
    return clone(session)
  }

  snapshot(): WorkspaceSessionGraphSnapshot {
    return { sessions: this.listSessions(), contextNodes: this.listContextNodes(), relations: this.listRelations() }
  }

  restore(snapshot: WorkspaceSessionGraphSnapshot): void {
    this.sessions.clear()
    this.contextNodes.clear()
    this.relations.clear()
    for (const session of snapshot.sessions) {
      const parsed = parseSpatialWorkspaceSession(session)
      if (!parsed.ok) throw new SessionGraphError('INVALID_GRAPH_RECORD', 'cannot restore workspace session')
      this.assertScope(parsed.data.workspace_id, parsed.data.node_id)
      this.sessions.set(parsed.data.session_id, clone(parsed.data))
    }
    for (const context of snapshot.contextNodes) {
      const parsed = parseSpatialContextNode(context)
      if (!parsed.ok) throw new SessionGraphError('INVALID_GRAPH_RECORD', 'cannot restore context node')
      this.assertScope(parsed.data.workspace_id, parsed.data.node_id)
      this.contextNodes.set(parsed.data.context_node_id, clone(parsed.data))
    }
    for (const relation of snapshot.relations) this.relations.set(relation.relation_id, clone(relation))
  }

  private requireSession(sessionId: string): SpatialWorkspaceSession {
    const session = this.sessions.get(sessionId)
    if (!session) throw new SessionGraphError('SESSION_NOT_FOUND', 'session was not found')
    return session
  }

  private relationsFor(type: SpatialContextRelationType, sourceRef: string): SpatialContextRelation[] {
    return [...this.relations.values()].filter((relation) => relation.type === type && relation.source_ref === sourceRef)
  }

  private reachable(startRef: string, targetRef: string, visited = new Set<string>()): boolean {
    if (startRef === targetRef) return true
    if (visited.has(startRef)) return false
    visited.add(startRef)
    return this.relationsFor('CONTINUES_FROM', startRef).some((relation) => this.reachable(relation.target_ref, targetRef, visited))
  }
}

export const WorkspaceSessionContextGraph = WorkspaceSessionGraph

export function createWorkspaceSessionGraph(options: WorkspaceSessionGraphOptions): WorkspaceSessionGraph {
  return new WorkspaceSessionGraph(options)
}
