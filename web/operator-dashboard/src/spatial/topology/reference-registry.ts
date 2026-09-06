import {
  parseSpatialCanonicalReference,
  SPATIAL_SCHEMA_VERSIONS,
  type SpatialCanonicalReference,
  type SpatialEntityKind,
  type SpatialReferenceProjectionKind,
  type SpatialReferenceState,
} from '@/spatial/contracts'

export type CanonicalReferenceRegistryOptions = {
  workspaceId: string
  nodeId: string
  now?: () => Date
  idFactory?: (prefix: string) => string
}

export type CanonicalReferenceInput = {
  canonicalRef: string
  entityId: string
  entityKind: SpatialEntityKind
  revision: number
  projectionKind?: SpatialReferenceProjectionKind
  state?: SpatialReferenceState
  provenanceRef?: string | null
}

export type CanonicalRegistryTelemetry = {
  discoveries: number
  duplicateDiscoveries: number
  staleDiscoveries: number
  projectionDeletes: number
  crossWorkspaceLookups: number
}

export type CanonicalReferenceRegistryErrorCode = 'SCOPE_MISMATCH' | 'INVALID_REFERENCE' | 'UNKNOWN_REFERENCE'

export class CanonicalReferenceRegistryError extends Error {
  readonly code: CanonicalReferenceRegistryErrorCode

  constructor(code: CanonicalReferenceRegistryErrorCode, message: string) {
    super(message)
    this.name = 'CanonicalReferenceRegistryError'
    this.code = code
  }
}

function scopeKey(workspaceId: string, canonicalRef: string): string {
  return `${workspaceId}:${canonicalRef}`
}

function validDate(now: () => Date): string {
  const value = now()
  if (!Number.isFinite(value.getTime())) throw new RangeError('now must return a valid Date')
  return value.toISOString()
}

/**
 * Workspace-scoped identity registry. Every public projection is a copy, so
 * deleting a presentation can never delete the canonical record.
 */
export class CanonicalReferenceRegistry {
  private readonly records = new Map<string, SpatialCanonicalReference>()
  private readonly history = new Map<string, Map<number, SpatialCanonicalReference>>()
  private readonly options: Required<Pick<CanonicalReferenceRegistryOptions, 'workspaceId' | 'nodeId'>> & Pick<CanonicalReferenceRegistryOptions, 'now' | 'idFactory'>
  private readonly telemetry: CanonicalRegistryTelemetry = {
    discoveries: 0,
    duplicateDiscoveries: 0,
    staleDiscoveries: 0,
    projectionDeletes: 0,
    crossWorkspaceLookups: 0,
  }

  constructor(options: CanonicalReferenceRegistryOptions) {
    const workspaceId = options.workspaceId.trim()
    const nodeId = options.nodeId.trim()
    if (!workspaceId || !nodeId) throw new CanonicalReferenceRegistryError('SCOPE_MISMATCH', 'workspaceId and nodeId are required')
    this.options = { workspaceId, nodeId, now: options.now, idFactory: options.idFactory }
  }

  private recordKey(canonicalRef: string): string {
    return scopeKey(this.options.workspaceId, canonicalRef)
  }

  discover(input: CanonicalReferenceInput): SpatialCanonicalReference {
    const canonicalRef = input.canonicalRef.trim()
    const entityId = input.entityId.trim()
    if (!canonicalRef || !entityId || !input.entityKind || !Number.isInteger(input.revision) || input.revision < 0) {
      throw new CanonicalReferenceRegistryError('INVALID_REFERENCE', 'canonicalRef, entityId, entityKind and non-negative revision are required')
    }
    const now = validDate(this.options.now ?? (() => new Date()))
    const key = this.recordKey(canonicalRef)
    const current = this.records.get(key)
    this.telemetry.discoveries += 1
    if (current) {
      this.telemetry.duplicateDiscoveries += 1
      if (input.revision < current.revision) {
        this.telemetry.staleDiscoveries += 1
        this.history.get(key)?.set(input.revision, { ...current, revision: input.revision, last_seen_at: now })
        return { ...current }
      }
    }
    const record: SpatialCanonicalReference = {
      schema_version: SPATIAL_SCHEMA_VERSIONS.canonicalReference,
      workspace_id: this.options.workspaceId,
      node_id: this.options.nodeId,
      canonical_ref: canonicalRef,
      entity_id: entityId,
      entity_kind: input.entityKind,
      revision: input.revision,
      projection_kind: input.projectionKind ?? current?.projection_kind ?? 'PRIMARY',
      state: input.state ?? current?.state ?? 'AVAILABLE',
      first_seen_at: current?.first_seen_at ?? now,
      last_seen_at: now,
      provenance_ref: input.provenanceRef ?? current?.provenance_ref ?? null,
    }
    const parsed = parseSpatialCanonicalReference(record)
    if (!parsed.ok) throw new CanonicalReferenceRegistryError('INVALID_REFERENCE', `invalid canonical reference at ${parsed.diagnostic.path}`)
    this.records.set(key, parsed.data)
    const revisions = this.history.get(key) ?? new Map<number, SpatialCanonicalReference>()
    revisions.set(parsed.data.revision, parsed.data)
    this.history.set(key, revisions)
    return { ...parsed.data }
  }

  register(input: CanonicalReferenceInput): SpatialCanonicalReference {
    return this.discover(input)
  }

  resolve(canonicalRef: string, projectionKind: SpatialReferenceProjectionKind = 'PRIMARY'): SpatialCanonicalReference {
    const normalized = canonicalRef.trim()
    const record = this.records.get(this.recordKey(normalized))
    if (!record) throw new CanonicalReferenceRegistryError('UNKNOWN_REFERENCE', `unknown canonical reference: ${normalized}`)
    return { ...record, projection_kind: projectionKind }
  }

  resolveInScope(workspaceId: string, nodeId: string, canonicalRef: string): SpatialCanonicalReference | null {
    if (workspaceId !== this.options.workspaceId || nodeId !== this.options.nodeId) {
      this.telemetry.crossWorkspaceLookups += 1
      return null
    }
    return this.records.get(this.recordKey(canonicalRef.trim())) ? this.resolve(canonicalRef) : null
  }

  inspectRevision(canonicalRef: string, revision: number): SpatialCanonicalReference {
    const item = this.history.get(this.recordKey(canonicalRef.trim()))?.get(revision)
    if (!item) throw new CanonicalReferenceRegistryError('UNKNOWN_REFERENCE', `unknown revision for canonical reference: ${canonicalRef}`)
    return { ...item }
  }

  tombstone(canonicalRef: string, revision: number): SpatialCanonicalReference {
    const current = this.resolve(canonicalRef)
    return this.discover({
      canonicalRef: current.canonical_ref,
      entityId: current.entity_id,
      entityKind: current.entity_kind,
      revision: Math.max(revision, current.revision),
      state: 'TOMBSTONE',
      provenanceRef: current.provenance_ref,
    })
  }

  deletePresentation(canonicalRef: string): SpatialCanonicalReference {
    this.telemetry.projectionDeletes += 1
    return this.resolve(canonicalRef, 'PRIMARY')
  }

  list(): SpatialCanonicalReference[] {
    return [...this.records.values()].map((record) => ({ ...record }))
  }

  get workspaceId(): string {
    return this.options.workspaceId
  }

  get nodeId(): string {
    return this.options.nodeId
  }

  primaryPresence(canonicalRef: string): SpatialCanonicalReference {
    return this.resolve(canonicalRef, 'PRIMARY')
  }

  getTelemetry(): CanonicalRegistryTelemetry {
    return { ...this.telemetry }
  }
}

export const CanonicalReferenceRegistryService = CanonicalReferenceRegistry
