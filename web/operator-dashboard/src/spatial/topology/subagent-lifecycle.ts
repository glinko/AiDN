import {
  parseSpatialSubagentLifecycle,
  SPATIAL_SCHEMA_VERSIONS,
  type SpatialSubagentLifecycle,
  type SpatialSubagentState,
} from '@/spatial/contracts'

import { CanonicalReferenceRegistry } from './reference-registry'
import { SemanticRelationService } from './semantic-relations'

export type SubagentLifecycleOptions = {
  workspaceId: string
  nodeId: string
  primaryAgentRef: string
  registry: CanonicalReferenceRegistry
  relations: SemanticRelationService
  now?: () => Date
  authorizeRemoteAccess?: (input: { subagentRef: string; endpointRef: string; capability: string }) => boolean
}

export type SpawnSubagentInput = {
  subagentRef: string
  parentRef?: string | null
  capabilityGrantScope?: readonly string[]
}

export type SubagentLifecycleErrorCode = 'INVALID_STATE' | 'UNKNOWN_SUBAGENT' | 'ORPHANED_SUBAGENT' | 'REMOTE_ACCESS_DENIED' | 'SCOPE_MISMATCH'

export class SubagentLifecycleError extends Error {
  readonly code: SubagentLifecycleErrorCode

  constructor(code: SubagentLifecycleErrorCode, message: string) {
    super(message)
    this.name = 'SubagentLifecycleError'
    this.code = code
  }
}

const TRANSITIONS: Record<SpatialSubagentState, readonly SpatialSubagentState[]> = {
  SPAWNED: ['WORKING', 'CANCELLED', 'FAILED', 'ARCHIVED'],
  WORKING: ['COMPLETED', 'FAILED', 'CANCELLED'],
  COMPLETED: ['ARCHIVED'],
  FAILED: ['ARCHIVED', 'WORKING'],
  CANCELLED: ['ARCHIVED'],
  ARCHIVED: [],
}

/** Local delegated actors stay distinct from remote Endpoint resources. */
export class SubagentLifecycleService {
  private readonly subagents = new Map<string, SpatialSubagentLifecycle>()
  private readonly options: SubagentLifecycleOptions

  constructor(options: SubagentLifecycleOptions) {
    this.options = options
  }

  spawn(input: SpawnSubagentInput): SpatialSubagentLifecycle {
    const existing = this.subagents.get(input.subagentRef)
    if (existing) return { ...existing, capability_grant_scope: [...existing.capability_grant_scope] }
    if (input.parentRef && !this.subagents.has(input.parentRef) && input.parentRef !== this.options.primaryAgentRef) {
      throw new SubagentLifecycleError('ORPHANED_SUBAGENT', `parent subagent does not exist: ${input.parentRef}`)
    }
    const now = (this.options.now ?? (() => new Date()))().toISOString()
    const record: SpatialSubagentLifecycle = {
      schema_version: SPATIAL_SCHEMA_VERSIONS.subagentLifecycle,
      subagent_ref: input.subagentRef,
      workspace_id: this.options.workspaceId,
      node_id: this.options.nodeId,
      primary_agent_ref: this.options.primaryAgentRef,
      parent_ref: input.parentRef ?? null,
      revision: 0,
      state: 'SPAWNED',
      capability_grant_scope: [...(input.capabilityGrantScope ?? [])],
      delegation_relation_ref: `delegation:${this.options.primaryAgentRef}:${input.subagentRef}`,
      result_ref: null,
      error_summary: null,
      created_at: now,
      updated_at: now,
    }
    const parsed = parseSpatialSubagentLifecycle(record)
    if (!parsed.ok) throw new SubagentLifecycleError('INVALID_STATE', `subagent invalid at ${parsed.diagnostic.path}`)
    this.subagents.set(parsed.data.subagent_ref, parsed.data)
    this.options.registry.discover({
      canonicalRef: input.subagentRef,
      entityId: input.subagentRef,
      entityKind: 'agent',
      revision: 0,
      provenanceRef: this.options.primaryAgentRef,
    })
    if (this.options.registry.resolveInScope(this.options.workspaceId, this.options.nodeId, this.options.primaryAgentRef)) {
      this.options.relations.upsert({
        relationId: parsed.data.delegation_relation_ref ?? `delegation:${input.subagentRef}`,
        relationType: 'DELEGATED',
        sourceRef: this.options.primaryAgentRef,
        targetRef: input.subagentRef,
        sourceRevision: 0,
        targetRevision: 0,
        label: 'delegated to local subagent',
      })
    }
    return this.clone(parsed.data)
  }

  transition(subagentRef: string, state: SpatialSubagentState, details: { resultRef?: string | null; errorSummary?: string | null } = {}): SpatialSubagentLifecycle {
    const current = this.subagents.get(subagentRef)
    if (!current) throw new SubagentLifecycleError('UNKNOWN_SUBAGENT', `unknown subagent: ${subagentRef}`)
    if (current.state !== state && !TRANSITIONS[current.state].includes(state)) {
      throw new SubagentLifecycleError('INVALID_STATE', `${current.state} cannot transition to ${state}`)
    }
    const next: SpatialSubagentLifecycle = {
      ...current,
      revision: current.revision + (current.state === state ? 0 : 1),
      state,
      result_ref: details.resultRef === undefined ? current.result_ref : details.resultRef,
      error_summary: details.errorSummary === undefined ? current.error_summary : details.errorSummary,
      updated_at: (this.options.now ?? (() => new Date()))().toISOString(),
    }
    this.subagents.set(subagentRef, next)
    return this.clone(next)
  }

  complete(subagentRef: string, resultRef: string): SpatialSubagentLifecycle {
    return this.transition(subagentRef, 'COMPLETED', { resultRef })
  }

  fail(subagentRef: string, errorSummary: string): SpatialSubagentLifecycle {
    return this.transition(subagentRef, 'FAILED', { errorSummary })
  }

  recoverOrphans(): SpatialSubagentLifecycle[] {
    const orphans = [...this.subagents.values()].filter((subagent) => subagent.parent_ref !== null && !this.subagents.has(subagent.parent_ref) && subagent.parent_ref !== this.options.primaryAgentRef)
    return orphans.map((subagent) => this.clone(subagent))
  }

  requestRemoteAccess(subagentRef: string, endpointRef: string, capability: string): { mediated: true; subagentRef: string; endpointRef: string; capability: string } {
    const subagent = this.subagents.get(subagentRef)
    if (!subagent || subagent.state === 'ARCHIVED' || subagent.state === 'CANCELLED') throw new SubagentLifecycleError('UNKNOWN_SUBAGENT', `subagent is not active: ${subagentRef}`)
    if (!subagent.capability_grant_scope.includes(capability) || !this.options.authorizeRemoteAccess?.({ subagentRef, endpointRef, capability })) {
      throw new SubagentLifecycleError('REMOTE_ACCESS_DENIED', 'remote endpoint access must pass the local mediation boundary')
    }
    return { mediated: true, subagentRef, endpointRef, capability }
  }

  list(): SpatialSubagentLifecycle[] {
    return [...this.subagents.values()].map((subagent) => this.clone(subagent))
  }

  get(subagentRef: string): SpatialSubagentLifecycle {
    const subagent = this.subagents.get(subagentRef)
    if (!subagent) throw new SubagentLifecycleError('UNKNOWN_SUBAGENT', `unknown subagent: ${subagentRef}`)
    return this.clone(subagent)
  }

  private clone(value: SpatialSubagentLifecycle): SpatialSubagentLifecycle {
    return { ...value, capability_grant_scope: [...value.capability_grant_scope] }
  }
}

export const LocalSubagentService = SubagentLifecycleService
