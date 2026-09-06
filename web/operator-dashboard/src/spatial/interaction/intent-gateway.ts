import {
  parseSpatialAttachmentManifest,
  parseSpatialIntentEnvelope,
  spatialAttachmentManifestSchema,
  spatialIntentEnvelopeSchema,
  SPATIAL_SCHEMA_VERSIONS,
  type SpatialAttachmentManifest,
  type SpatialIntentEnvelope,
  type SpatialIntentKind,
  type SpatialIntentModality,
} from '@/spatial/contracts'

export type IntentGatewayErrorCode =
  | 'EMPTY_INTENT'
  | 'OVERSIZED_INTENT'
  | 'WRONG_WORKSPACE'
  | 'WRONG_NODE'
  | 'DUPLICATE_INTENT'
  | 'STALE_TARGET'
  | 'UNAUTHORIZED'
  | 'MALFORMED_ATTACHMENT'
  | 'MALFORMED_INTENT'

export class IntentGatewayError extends Error {
  readonly code: IntentGatewayErrorCode
  readonly path?: string

  constructor(code: IntentGatewayErrorCode, message: string, path?: string) {
    super(message)
    this.name = 'IntentGatewayError'
    this.code = code
    this.path = path
  }
}

export type IntentDraftAttachment = Omit<SpatialAttachmentManifest, 'schema_version'> & {
  schema_version?: SpatialAttachmentManifest['schema_version']
}

export type SpatialIntentDraft = {
  intent_id?: string
  workspace_id?: string
  node_id?: string
  actor_ref: string
  modality: SpatialIntentModality
  intent_kind?: SpatialIntentKind
  text?: string | null
  operation?: Record<string, unknown> | null
  target_refs?: readonly string[]
  parent_ref?: string | null
  context_refs?: readonly string[]
  attachments_manifest?: readonly (IntentDraftAttachment | SpatialAttachmentManifest)[]
  current_revision?: number
  idempotency_key: string
  created_at?: string | Date
}

export type IntentGatewayAuditEntry = {
  intent_id: string
  workspace_id: string
  node_id: string
  actor_ref: string
  modality: SpatialIntentModality
  intent_kind: SpatialIntentKind
  target_count: number
  attachment_count: number
  current_revision: number
  created_at: string
  outcome: 'accepted' | 'duplicate'
}

export type IntentSubmission = {
  status: 'accepted' | 'duplicate'
  duplicate: boolean
  envelope: SpatialIntentEnvelope
  audit: IntentGatewayAuditEntry
}

export type IntentGatewayAuthorization = (envelope: SpatialIntentEnvelope) => boolean | { allowed: boolean; reason?: string }

export type IntentGatewayOptions = {
  workspaceId: string
  nodeId: string
  currentRevision?: number
  maxTextLength?: number
  now?: () => Date
  authorize?: IntentGatewayAuthorization
  idFactory?: (prefix: string) => string
}

function makeId(prefix: string): string {
  const randomUuid = typeof globalThis.crypto?.randomUUID === 'function' ? globalThis.crypto.randomUUID() : null
  return `${prefix}_${randomUuid ?? `${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`}`
}

function toIsoTimestamp(value: string | Date | undefined, now: () => Date): string {
  if (value instanceof Date) return value.toISOString()
  if (typeof value === 'string') {
    const parsed = new Date(value)
    if (!Number.isNaN(parsed.getTime())) return parsed.toISOString()
  }
  return now().toISOString()
}

function normalizeAttachment(
  attachment: IntentDraftAttachment | SpatialAttachmentManifest,
  idFactory: (prefix: string) => string,
): SpatialAttachmentManifest {
  const candidate = {
    schema_version: SPATIAL_SCHEMA_VERSIONS.attachmentManifest,
    ...attachment,
    attachment_id: attachment.attachment_id || idFactory('attachment'),
  }
  const parsed = parseSpatialAttachmentManifest(candidate)
  if (!parsed.ok) throw new IntentGatewayError('MALFORMED_ATTACHMENT', 'attachment manifest is invalid', parsed.diagnostic.path)
  return parsed.data
}

function safeAudit(envelope: SpatialIntentEnvelope, outcome: IntentGatewayAuditEntry['outcome']): IntentGatewayAuditEntry {
  return {
    intent_id: envelope.intent_id,
    workspace_id: envelope.workspace_id,
    node_id: envelope.node_id,
    actor_ref: envelope.actor_ref,
    modality: envelope.modality,
    intent_kind: envelope.intent_kind,
    target_count: envelope.target_refs.length,
    attachment_count: envelope.attachments_manifest.length,
    current_revision: envelope.current_revision,
    created_at: envelope.created_at,
    outcome,
  }
}

/**
 * Node-facing boundary for all operator interaction modalities. It validates
 * and scopes facts, but deliberately does not grant capabilities or perform
 * an operation itself.
 */
export class IntentGateway {
  readonly workspaceId: string
  readonly nodeId: string
  private currentRevision: number
  private readonly maxTextLength: number
  private readonly now: () => Date
  private readonly authorize?: IntentGatewayAuthorization
  private readonly idFactory: (prefix: string) => string
  private readonly byIdempotency = new Map<string, IntentSubmission>()
  private readonly audits: IntentGatewayAuditEntry[] = []

  constructor(options: IntentGatewayOptions) {
    this.workspaceId = options.workspaceId
    this.nodeId = options.nodeId
    this.currentRevision = Math.max(0, options.currentRevision ?? 0)
    this.maxTextLength = Math.max(1, options.maxTextLength ?? 32_000)
    this.now = options.now ?? (() => new Date())
    this.authorize = options.authorize
    this.idFactory = options.idFactory ?? makeId
  }

  setCurrentRevision(revision: number): void {
    if (!Number.isInteger(revision) || revision < 0) throw new RangeError('revision must be a non-negative integer')
    this.currentRevision = revision
  }

  getCurrentRevision(): number {
    return this.currentRevision
  }

  submit(draft: SpatialIntentDraft): IntentSubmission {
    const idempotencyKey = draft.idempotency_key?.trim()
    if (!idempotencyKey) throw new IntentGatewayError('MALFORMED_INTENT', 'idempotency_key is required', 'idempotency_key')

    if (draft.workspace_id !== undefined && draft.workspace_id !== this.workspaceId) {
      throw new IntentGatewayError('WRONG_WORKSPACE', 'intent workspace is outside the active scope', 'workspace_id')
    }
    if (draft.node_id !== undefined && draft.node_id !== this.nodeId) {
      throw new IntentGatewayError('WRONG_NODE', 'intent node is outside the active scope', 'node_id')
    }

    const duplicate = this.byIdempotency.get(`${draft.actor_ref}:${idempotencyKey}`)
    if (duplicate) {
      const duplicateAudit = safeAudit(duplicate.envelope, 'duplicate')
      this.audits.push(duplicateAudit)
      return { ...duplicate, status: 'duplicate', duplicate: true, audit: duplicateAudit }
    }

    const text = draft.text === undefined || draft.text === null ? null : draft.text.trim()
    if ((!text || text.length === 0) && !draft.operation) throw new IntentGatewayError('EMPTY_INTENT', 'text or operation is required', 'text')
    if (text && text.length > this.maxTextLength) throw new IntentGatewayError('OVERSIZED_INTENT', 'intent text exceeds the configured limit', 'text')

    const targetRevision = draft.current_revision ?? this.currentRevision
    if (!Number.isInteger(targetRevision) || targetRevision < 0 || targetRevision < this.currentRevision) {
      throw new IntentGatewayError('STALE_TARGET', 'intent targets an older workspace revision', 'current_revision')
    }

    const attachments = (draft.attachments_manifest ?? []).map((attachment) => normalizeAttachment(attachment, this.idFactory))
    const envelopeCandidate = {
      schema_version: SPATIAL_SCHEMA_VERSIONS.intentEnvelope,
      intent_id: draft.intent_id ?? this.idFactory('intent'),
      workspace_id: this.workspaceId,
      node_id: this.nodeId,
      actor_ref: draft.actor_ref,
      modality: draft.modality,
      intent_kind: draft.intent_kind ?? 'message',
      text,
      operation: draft.operation ?? null,
      target_refs: [...(draft.target_refs ?? [])],
      parent_ref: draft.parent_ref ?? null,
      context_refs: [...(draft.context_refs ?? [])],
      attachments_manifest: attachments,
      current_revision: targetRevision,
      idempotency_key: idempotencyKey,
      created_at: toIsoTimestamp(draft.created_at, this.now),
    }
    const parsed = parseSpatialIntentEnvelope(envelopeCandidate)
    if (!parsed.ok) throw new IntentGatewayError('MALFORMED_INTENT', 'intent envelope is invalid', parsed.diagnostic.path)
    const envelope = parsed.data

    if (this.authorize) {
      const decision = this.authorize(envelope)
      if (decision === false || (typeof decision === 'object' && !decision.allowed)) {
        throw new IntentGatewayError('UNAUTHORIZED', 'actor is not authorized for this intent')
      }
    }

    const audit = safeAudit(envelope, 'accepted')
    const submission: IntentSubmission = { status: 'accepted', duplicate: false, envelope, audit }
    this.byIdempotency.set(`${envelope.actor_ref}:${envelope.idempotency_key}`, submission)
    this.audits.push(audit)
    return submission
  }

  hasIdempotencyKey(actorRef: string, idempotencyKey: string): boolean {
    return this.byIdempotency.has(`${actorRef}:${idempotencyKey}`)
  }

  getAudit(): readonly IntentGatewayAuditEntry[] {
    return this.audits.map((entry) => ({ ...entry }))
  }

  clear(): void {
    this.byIdempotency.clear()
    this.audits.length = 0
  }
}

export const SpatialIntentGateway = IntentGateway

export function createIntentGateway(options: IntentGatewayOptions): IntentGateway {
  return new IntentGateway(options)
}

export function createTextIntentDraft(input: {
  actor_ref: string
  text: string
  idempotency_key: string
  workspace_id?: string
  node_id?: string
  target_refs?: readonly string[]
  context_refs?: readonly string[]
  parent_ref?: string | null
  current_revision?: number
}): SpatialIntentDraft {
  return {
    actor_ref: input.actor_ref,
    modality: 'text',
    intent_kind: 'message',
    text: input.text,
    idempotency_key: input.idempotency_key,
    workspace_id: input.workspace_id,
    node_id: input.node_id,
    target_refs: input.target_refs,
    context_refs: input.context_refs,
    parent_ref: input.parent_ref,
    current_revision: input.current_revision,
  }
}

export { spatialAttachmentManifestSchema, spatialIntentEnvelopeSchema }
