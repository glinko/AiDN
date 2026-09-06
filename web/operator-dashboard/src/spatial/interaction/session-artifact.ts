import {
  parseSpatialArtifact,
  SPATIAL_SCHEMA_VERSIONS,
  type SpatialArtifact,
  type SpatialWorkspaceSession,
} from '@/spatial/contracts'

import { SessionGraphError, WorkspaceSessionGraph } from './session-graph'

export type SessionArtifactErrorCode =
  | 'SESSION_NOT_FOUND'
  | 'ARTIFACT_NOT_FOUND'
  | 'INVALID_ARTIFACT'
  | 'STALE_ARTIFACT'

export class SessionArtifactError extends Error {
  readonly code: SessionArtifactErrorCode

  constructor(code: SessionArtifactErrorCode, message: string) {
    super(message)
    this.name = 'SessionArtifactError'
    this.code = code
  }
}

export type SessionArtifactServiceOptions = {
  graph: WorkspaceSessionGraph
  workspaceId: string
  nodeId: string
  now?: () => Date
  idFactory?: (prefix: string) => string
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

export function artifactTransition(prefersReducedMotion: boolean): 'none' | 'fade' {
  return prefersReducedMotion ? 'none' : 'fade'
}

/** Collapsed Conversation Surface projection; transcript and generated objects remain durable. */
export class SessionArtifactService {
  private readonly graph: WorkspaceSessionGraph
  private readonly workspaceId: string
  private readonly nodeId: string
  private readonly now: () => Date
  private readonly idFactory: (prefix: string) => string
  private readonly artifacts = new Map<string, SpatialArtifact>()

  constructor(options: SessionArtifactServiceOptions) {
    this.graph = options.graph
    this.workspaceId = options.workspaceId
    this.nodeId = options.nodeId
    this.now = options.now ?? (() => new Date())
    this.idFactory = options.idFactory ?? defaultId
  }

  collapse(sessionId: string, input: { actorRef: string; title?: string; summary?: string; cameraSnapshot?: Record<string, unknown> | null }): SpatialArtifact {
    const session = this.graph.getSession(sessionId)
    if (!session) throw new SessionArtifactError('SESSION_NOT_FOUND', 'session was not found')
    if (session.artifact_ref) {
      const existing = this.artifacts.get(session.artifact_ref)
      if (existing) return clone(existing)
    }
    const timestamp = iso(this.now)
    const artifact: SpatialArtifact = {
      schema_version: SPATIAL_SCHEMA_VERSIONS.artifact,
      artifact_id: this.idFactory('artifact'),
      session_id: session.session_id,
      workspace_id: this.workspaceId,
      node_id: this.nodeId,
      revision: 0,
      title: input.title?.trim() || session.title,
      summary: input.summary?.trim() || session.summary,
      turn_count: session.turn_refs.length,
      turn_refs: [...session.turn_refs],
      object_refs: [...session.object_refs],
      context_root_ref: session.context_root_ref,
      state: 'ACTIVE',
      pinned: false,
      camera_snapshot: input.cameraSnapshot ? { ...input.cameraSnapshot } : null,
      created_at: timestamp,
      updated_at: timestamp,
    }
    const parsed = parseSpatialArtifact(artifact)
    if (!parsed.ok) throw new SessionArtifactError('INVALID_ARTIFACT', 'session artifact is malformed')
    this.artifacts.set(parsed.data.artifact_id, parsed.data)
    this.graph.updateSession(session.session_id, { state: 'COLLAPSED', artifact_ref: parsed.data.artifact_id }, session.revision)
    try {
      this.graph.addRelation({ type: 'PRODUCED', sourceRef: session.session_id, targetRef: parsed.data.artifact_id, actorRef: input.actorRef, sourceRevision: session.revision + 1, targetRevision: parsed.data.revision })
    } catch (error) {
      if (!(error instanceof SessionGraphError)) throw error
    }
    return clone(parsed.data)
  }

  restore(artifactId: string): SpatialWorkspaceSession {
    const artifact = this.require(artifactId)
    const session = this.graph.getSession(artifact.session_id)
    if (!session) throw new SessionArtifactError('SESSION_NOT_FOUND', 'artifact session was not found')
    this.artifacts.set(artifactId, { ...artifact, state: 'ACTIVE', updated_at: iso(this.now), revision: artifact.revision + 1 })
    return this.graph.updateSession(session.session_id, { state: 'ACTIVE' }, session.revision)
  }

  branch(artifactId: string, input: { rootIntentId: string; actorRef: string; title?: string; semanticAnchor?: string; contextRefs?: readonly string[] }): SpatialWorkspaceSession {
    const artifact = this.require(artifactId)
    return this.graph.branchSession(artifact.session_id, {
      rootIntentId: input.rootIntentId,
      actorRef: input.actorRef,
      title: input.title ?? `Branch of ${artifact.title}`,
      semanticAnchor: input.semanticAnchor ?? artifact.session_id,
      contextRefs: input.contextRefs,
    })
  }

  pin(artifactId: string, pinned = true, expectedRevision?: number): SpatialArtifact {
    const artifact = this.require(artifactId)
    if (expectedRevision !== undefined && expectedRevision !== artifact.revision) throw new SessionArtifactError('STALE_ARTIFACT', 'artifact revision is stale')
    artifact.pinned = pinned
    artifact.revision += 1
    artifact.updated_at = iso(this.now)
    this.artifacts.set(artifactId, artifact)
    return clone(artifact)
  }

  archive(artifactId: string, expectedRevision?: number): SpatialArtifact {
    const artifact = this.require(artifactId)
    if (expectedRevision !== undefined && expectedRevision !== artifact.revision) throw new SessionArtifactError('STALE_ARTIFACT', 'artifact revision is stale')
    artifact.state = 'ARCHIVED'
    artifact.revision += 1
    artifact.updated_at = iso(this.now)
    this.artifacts.set(artifactId, artifact)
    return clone(artifact)
  }

  get(artifactId: string): SpatialArtifact | null {
    const artifact = this.artifacts.get(artifactId)
    return artifact ? clone(artifact) : null
  }

  list(): SpatialArtifact[] {
    return [...this.artifacts.values()].map(clone)
  }

  snapshot(): SpatialArtifact[] {
    return this.list()
  }

  restoreSnapshot(artifacts: readonly SpatialArtifact[]): void {
    this.artifacts.clear()
    for (const artifact of artifacts) {
      const parsed = parseSpatialArtifact(artifact)
      if (!parsed.ok || parsed.data.workspace_id !== this.workspaceId || parsed.data.node_id !== this.nodeId) throw new SessionArtifactError('INVALID_ARTIFACT', 'cannot restore session artifact')
      this.artifacts.set(parsed.data.artifact_id, clone(parsed.data))
    }
  }

  private require(artifactId: string): SpatialArtifact {
    const artifact = this.artifacts.get(artifactId)
    if (!artifact) throw new SessionArtifactError('ARTIFACT_NOT_FOUND', 'session artifact was not found')
    return artifact
  }
}

export const SpatialSessionArtifactService = SessionArtifactService

export function createSessionArtifactService(options: SessionArtifactServiceOptions): SessionArtifactService {
  return new SessionArtifactService(options)
}
