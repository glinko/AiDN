import {
  SPATIAL_SCHEMA_VERSIONS,
  spatialAttachmentManifestSchema,
  spatialIdSchema,
  type SpatialAttachmentManifest,
  type SpatialSessionState,
} from '@/spatial/contracts'

import {
  IntentGateway,
  IntentGatewayError,
  type IntentDraftAttachment,
  type IntentSubmission,
  type SpatialIntentDraft,
} from './intent-gateway'

export type InteractionSeedState = Extract<SpatialSessionState, 'SEED' | 'COMPOSING' | 'SUBMITTING' | 'ACTIVE' | 'FAILED' | 'CANCELLED'>

export type InteractionSeed = {
  seed_id: string
  workspace_id: string
  node_id: string
  actor_ref: string
  state: InteractionSeedState
  semantic_anchor: string
  text: string
  operation: Record<string, unknown> | null
  attachments_manifest: SpatialAttachmentManifest[]
  continue_from: string | null
  context_refs: string[]
  idempotency_key: string
  intent_id: string | null
  error_code: string | null
  created_at: string
  updated_at: string
}

export type InteractionSeedControllerOptions = {
  workspaceId: string
  nodeId: string
  actorRef: string
  gateway: IntentGateway
  now?: () => Date
  idFactory?: (prefix: string) => string
  semanticAnchor?: string
  idempotencyKey?: string
}

export type InteractionSeedTarget = {
  kind?: 'entity' | 'control' | 'canvas' | 'empty' | 'unknown'
  interactive?: boolean
  semanticRef?: string | null
}

function defaultId(prefix: string): string {
  const uuid = typeof globalThis.crypto?.randomUUID === 'function' ? globalThis.crypto.randomUUID() : `${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`
  return `${prefix}_${uuid}`
}

function timestamp(now: () => Date): string {
  return now().toISOString()
}

/** Entity/control activation is not an interaction-seed gesture. */
export function shouldOpenInteractionSeed(target: InteractionSeedTarget): boolean {
  if (target.interactive) return false
  return target.kind === 'canvas' || target.kind === 'empty' || target.kind === 'unknown' || target.kind === undefined
}

export function isCreateInteractionShortcut(event: Pick<KeyboardEvent, 'key' | 'ctrlKey' | 'metaKey' | 'altKey' | 'shiftKey'>): boolean {
  return event.key.toLowerCase() === 'i' && (event.ctrlKey || event.metaKey) && !event.altKey && !event.shiftKey
}

export function isLongPressDuration(durationMs: number): boolean {
  return Number.isFinite(durationMs) && durationMs >= 500
}

/** A small state machine for the desktop click, mobile long-press and keyboard entry points. */
export class InteractionSeedController {
  private readonly gateway: IntentGateway
  private readonly now: () => Date
  private readonly idFactory: (prefix: string) => string
  private readonly seed: InteractionSeed
  private lastSubmission: IntentSubmission | null = null

  constructor(options: InteractionSeedControllerOptions) {
    this.gateway = options.gateway
    this.now = options.now ?? (() => new Date())
    this.idFactory = options.idFactory ?? defaultId
    const createdAt = timestamp(this.now)
    this.seed = {
      seed_id: this.idFactory('seed'),
      workspace_id: options.workspaceId,
      node_id: options.nodeId,
      actor_ref: options.actorRef,
      state: 'SEED',
      semantic_anchor: options.semanticAnchor ?? 'workspace:empty',
      text: '',
      operation: null,
      attachments_manifest: [],
      continue_from: null,
      context_refs: [],
      idempotency_key: options.idempotencyKey ?? this.idFactory('interaction'),
      intent_id: null,
      error_code: null,
      created_at: createdAt,
      updated_at: createdAt,
    }
  }

  getSnapshot(): InteractionSeed {
    return {
      ...this.seed,
      attachments_manifest: this.seed.attachments_manifest.map((attachment) => ({ ...attachment })),
      context_refs: [...this.seed.context_refs],
      operation: this.seed.operation ? { ...this.seed.operation } : null,
    }
  }

  private touch(): void {
    this.seed.updated_at = timestamp(this.now)
  }

  private ensureMutable(): void {
    if (this.seed.state === 'SUBMITTING' || this.seed.state === 'ACTIVE' || this.seed.state === 'CANCELLED') {
      throw new Error(`interaction seed is ${this.seed.state.toLowerCase()}`)
    }
  }

  beginComposition(): InteractionSeed {
    if (this.seed.state === 'SEED') this.seed.state = 'COMPOSING'
    this.touch()
    return this.getSnapshot()
  }

  setText(text: string): InteractionSeed {
    this.ensureMutable()
    this.seed.text = text
    if (this.seed.state === 'SEED') this.seed.state = 'COMPOSING'
    this.seed.error_code = null
    this.touch()
    return this.getSnapshot()
  }

  setOperation(operation: Record<string, unknown> | null): InteractionSeed {
    this.ensureMutable()
    this.seed.operation = operation ? { ...operation } : null
    if (this.seed.state === 'SEED') this.seed.state = 'COMPOSING'
    this.seed.error_code = null
    this.touch()
    return this.getSnapshot()
  }

  addAttachment(attachment: IntentDraftAttachment | SpatialAttachmentManifest): InteractionSeed {
    this.ensureMutable()
    const parsed = spatialAttachmentManifestSchema.safeParse({
      schema_version: SPATIAL_SCHEMA_VERSIONS.attachmentManifest,
      ...attachment,
      attachment_id: attachment.attachment_id || this.idFactory('attachment'),
    })
    if (!parsed.success) throw new IntentGatewayError('MALFORMED_ATTACHMENT', 'attachment manifest is invalid')
    this.seed.attachments_manifest.push(parsed.data)
    if (this.seed.state === 'SEED') this.seed.state = 'COMPOSING'
    this.touch()
    return this.getSnapshot()
  }

  continueFrom(ref: string | null): InteractionSeed {
    this.ensureMutable()
    if (ref !== null) spatialIdSchema.parse(ref)
    this.seed.continue_from = ref
    if (ref && !this.seed.context_refs.includes(ref)) this.seed.context_refs.push(ref)
    if (this.seed.state === 'SEED') this.seed.state = 'COMPOSING'
    this.touch()
    return this.getSnapshot()
  }

  addContext(ref: string): InteractionSeed {
    this.ensureMutable()
    const parsed = spatialIdSchema.safeParse(ref)
    if (!parsed.success) throw new Error('context reference is invalid')
    if (!this.seed.context_refs.includes(parsed.data)) this.seed.context_refs.push(parsed.data)
    if (this.seed.state === 'SEED') this.seed.state = 'COMPOSING'
    this.touch()
    return this.getSnapshot()
  }

  cancel(): InteractionSeed {
    if (this.seed.state !== 'ACTIVE') this.seed.state = 'CANCELLED'
    this.touch()
    return this.getSnapshot()
  }

  submit(options: { currentRevision?: number; targetRefs?: readonly string[]; modality?: SpatialIntentDraft['modality']; intentKind?: SpatialIntentDraft['intent_kind'] } = {}): IntentSubmission {
    if (this.lastSubmission) return this.lastSubmission
    if (this.seed.state === 'CANCELLED') throw new Error('interaction seed is cancelled')
    if ((!this.seed.text || this.seed.text.trim().length === 0) && !this.seed.operation) {
      this.seed.state = 'FAILED'
      this.seed.error_code = 'EMPTY_INTENT'
      this.touch()
      throw new IntentGatewayError('EMPTY_INTENT', 'text or operation is required')
    }
    this.seed.state = 'SUBMITTING'
    this.seed.error_code = null
    this.touch()
    try {
      const submission = this.gateway.submit({
        actor_ref: this.seed.actor_ref,
        modality: options.modality ?? 'text',
        intent_kind: options.intentKind ?? 'message',
        text: this.seed.text || null,
        operation: this.seed.operation,
        workspace_id: this.seed.workspace_id,
        node_id: this.seed.node_id,
        target_refs: options.targetRefs,
        parent_ref: this.seed.continue_from,
        context_refs: this.seed.context_refs,
        attachments_manifest: this.seed.attachments_manifest,
        current_revision: options.currentRevision,
        idempotency_key: this.seed.idempotency_key,
      })
      this.lastSubmission = submission
      this.seed.state = 'ACTIVE'
      this.seed.intent_id = submission.envelope.intent_id
      this.touch()
      return submission
    } catch (error) {
      this.seed.state = 'FAILED'
      this.seed.error_code = error instanceof IntentGatewayError ? error.code : 'MALFORMED_INTENT'
      this.touch()
      throw error
    }
  }
}

export function createInteractionSeed(options: InteractionSeedControllerOptions): InteractionSeedController {
  return new InteractionSeedController(options)
}
