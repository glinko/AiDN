import {
  parseSpatialPrivacyRecord,
  SPATIAL_SCHEMA_VERSIONS,
  type SpatialPrivacyClassification,
  type SpatialPrivacyLifecycleState,
  type SpatialPrivacyRecord,
} from '@/spatial/contracts'

export type SpatialPrivacyRegistration = {
  workspaceId: string
  nodeId: string
  subjectRef: string
  classification: SpatialPrivacyClassification
  lifecycle?: SpatialPrivacyLifecycleState
  disclosedFields?: readonly string[]
  redactedFields?: readonly string[]
  retentionUntil?: string | Date | null
  evidenceRefs?: readonly string[]
  now?: string | Date
}

export type SpatialWorkspaceExport = {
  schema_version: 'spatial.workspace-export.v1'
  workspace_id: string
  node_id: string
  canonical_refs: readonly string[]
  revisions: Readonly<Record<string, number>>
  evidence_refs: readonly string[]
  privacy_records: readonly SpatialPrivacyRecord[]
  exported_at: string
}

export type SpatialAttachmentLifecycle = 'REFERENCED' | 'STAGED' | 'ARCHIVED' | 'DELETED' | 'REDACTED'

const DEFAULT_ID = (prefix: string): string => `${prefix}:${Math.random().toString(36).slice(2, 12)}`

function isoNow(value: string | Date | null | undefined): string {
  if (value instanceof Date) return value.toISOString()
  if (typeof value === 'string' && Number.isFinite(Date.parse(value))) return new Date(value).toISOString()
  return new Date().toISOString()
}

function unique(values: readonly string[]): string[] {
  return [...new Set(values.map((value) => value.trim()).filter(Boolean))]
}

export function classifySpatialValue(value: unknown): SpatialPrivacyClassification {
  if (value === null || value === undefined) return 'PUBLIC'
  if (typeof value === 'object') {
    const keys = Object.keys(value as object).map((key) => key.toLowerCase())
    if (keys.some((key) => /secret|token|password|private.?key|credential/.test(key))) return 'SECRET'
    if (keys.some((key) => /prompt|transcript|message|attachment|email|operator/.test(key))) return 'PRIVATE'
  }
  return 'OPERATOR'
}

export function redactSpatialTranscript(text: string): string {
  return text
    .replace(/\b(?:sk|pk|token|secret|password)_[A-Za-z0-9_-]+\b/gi, '[REDACTED]')
    .replace(/Bearer\s+[A-Za-z0-9._-]+/gi, 'Bearer [REDACTED]')
}

export function canGarbageCollectPresentation(presentationRef: string, evidenceRefs: readonly string[]): boolean {
  return !evidenceRefs.includes(presentationRef)
}

export function assertPresentationGarbageCollectionSafe(presentationRef: string, evidenceRefs: readonly string[]): void {
  if (!canGarbageCollectPresentation(presentationRef, evidenceRefs)) throw new Error('presentation is referenced by evidence and cannot be collected')
}

export class SpatialPrivacyLifecycleService {
  private readonly idFactory: (prefix: string) => string
  private readonly records = new Map<string, SpatialPrivacyRecord>()

  public constructor(idFactory = DEFAULT_ID) {
    this.idFactory = idFactory
  }

  public register(input: SpatialPrivacyRegistration): SpatialPrivacyRecord {
    const now = isoNow(input.now)
    const parsed = parseSpatialPrivacyRecord({
      schema_version: SPATIAL_SCHEMA_VERSIONS.privacyRecord,
      record_id: this.idFactory('privacy'),
      workspace_id: input.workspaceId,
      node_id: input.nodeId,
      subject_ref: input.subjectRef,
      classification: input.classification,
      lifecycle: input.lifecycle ?? 'ACTIVE',
      disclosed_fields: unique(input.disclosedFields ?? []),
      redacted_fields: unique(input.redactedFields ?? []),
      retention_until: input.retentionUntil === null ? null : isoNow(input.retentionUntil),
      evidence_refs: unique(input.evidenceRefs ?? []),
      updated_at: now,
    })
    if (!parsed.ok) throw new Error(`invalid privacy record: ${parsed.diagnostic.path}`)
    this.records.set(parsed.data.record_id, parsed.data)
    return parsed.data
  }

  public transition(recordId: string, lifecycle: SpatialPrivacyLifecycleState, now = new Date()): SpatialPrivacyRecord {
    const record = this.require(recordId)
    const parsed = parseSpatialPrivacyRecord({ ...record, lifecycle, updated_at: now.toISOString() })
    if (!parsed.ok) throw new Error(`invalid privacy transition: ${parsed.diagnostic.path}`)
    this.records.set(recordId, parsed.data)
    return parsed.data
  }

  public archive(recordId: string): SpatialPrivacyRecord { return this.transition(recordId, 'ARCHIVED') }
  public delete(recordId: string): SpatialPrivacyRecord { return this.transition(recordId, 'DELETED') }
  public redact(recordId: string): SpatialPrivacyRecord { return this.transition(recordId, 'REDACTED') }

  public list(): SpatialPrivacyRecord[] { return [...this.records.values()] }

  public exportWorkspace(
    workspaceId: string,
    nodeId: string,
    canonicalRefs: readonly string[],
    revisions: Readonly<Record<string, number>>,
    evidenceRefs: readonly string[],
    exportedAt = new Date(),
  ): SpatialWorkspaceExport {
    const records = this.list()
      .filter((record) => record.workspace_id === workspaceId && record.node_id === nodeId)
      .map((record) => record.classification === 'SECRET'
        ? {
            ...record,
            classification: 'PRIVATE' as const,
            lifecycle: 'REDACTED' as const,
            disclosed_fields: [],
            redacted_fields: unique([...record.redacted_fields, 'secret']),
          }
        : record)
    return {
      schema_version: 'spatial.workspace-export.v1',
      workspace_id: workspaceId,
      node_id: nodeId,
      canonical_refs: unique(canonicalRefs),
      revisions: { ...revisions },
      evidence_refs: unique(evidenceRefs),
      privacy_records: records,
      exported_at: exportedAt.toISOString(),
    }
  }

  public purgeExpired(now = new Date()): number {
    let removed = 0
    for (const [id, record] of this.records) {
      if (record.retention_until && Date.parse(record.retention_until) <= now.getTime()) {
        this.records.delete(id)
        removed += 1
      }
    }
    return removed
  }

  private require(recordId: string): SpatialPrivacyRecord {
    const record = this.records.get(recordId)
    if (!record) throw new Error(`unknown privacy record: ${recordId}`)
    return record
  }
}
