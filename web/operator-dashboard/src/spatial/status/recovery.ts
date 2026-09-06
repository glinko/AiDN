import {
  parseSpatialRecoveryCommand,
  parseSpatialRecoveryResult,
  SPATIAL_SCHEMA_VERSIONS,
  type SpatialRecoveryAction,
  type SpatialRecoveryCommand,
  type SpatialRecoveryResult,
} from '@/spatial/contracts'
import type { CanonicalReferenceRegistry } from '@/spatial/topology/reference-registry'

export type RecoveryPlanInput = {
  nodeId: string
  targetRef: string
  action: SpatialRecoveryAction
  currentRevision: number
  actorRef?: string
  capabilities?: readonly string[]
  idempotencyKey?: string
  now?: Date
}

export type RecoveryApplyInput = {
  plan: SpatialRecoveryCommand
  currentRevision: number
  capabilities: readonly string[]
  confirmed?: boolean
  actorRef?: string
}

export type RecoveryHandler = (plan: SpatialRecoveryCommand) => void | Promise<void>

export type RecoveryAuditRecord = {
  audit_ref: string
  command_id: string
  actor_ref: string
  action: SpatialRecoveryAction
  target_ref: string
  state: SpatialRecoveryResult['state']
  observed_at: string
}

export class SpatialRecoveryError extends Error {
  readonly code: 'INVALID_PLAN' | 'STALE_PLAN' | 'CAPABILITY_DENIED' | 'CONFIRMATION_REQUIRED' | 'DUPLICATE_PLAN' | 'HANDLER_FAILED'

  constructor(code: SpatialRecoveryError['code'], message: string) {
    super(message)
    this.name = 'SpatialRecoveryError'
    this.code = code
  }
}

const CONSEQUENCES: Record<SpatialRecoveryAction, { capability: string; consequence: string; requiresConfirmation: boolean }> = {
  RESTART_SERVICE: { capability: 'recovery.restart-service', consequence: 'Restart a permitted Node service.', requiresConfirmation: true },
  STOP_UNSAFE_RUNTIME: { capability: 'recovery.stop-unsafe-runtime', consequence: 'Stop a runtime marked unsafe.', requiresConfirmation: true },
  SUSPEND_AGENT_BINDING: { capability: 'recovery.suspend-agent-binding', consequence: 'Suspend the Primary Agent binding without deleting Workspace state.', requiresConfirmation: true },
  REVOKE_BINDING_CREDENTIALS: { capability: 'recovery.revoke-binding-credentials', consequence: 'Revoke binding credentials; future delivery is blocked.', requiresConfirmation: true },
  DISABLE_HOOK: { capability: 'recovery.disable-hook', consequence: 'Disable one Hook subscription.', requiresConfirmation: true },
  RETRY_HOOK_DEAD_LETTER: { capability: 'recovery.retry-hook-dead-letter', consequence: 'Retry one bounded Hook dead-letter item.', requiresConfirmation: false },
  BLOCK_REMOTE_ENDPOINT: { capability: 'recovery.block-remote-endpoint', consequence: 'Block a remote Endpoint through Node policy.', requiresConfirmation: true },
  RETURN_TO_CLASSIC: { capability: 'recovery.return-to-classic', consequence: 'Return the operator to the Classic advanced surface.', requiresConfirmation: false },
}

function stableHash(value: string): string {
  let first = 2166136261
  let second = 2246822519
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index)
    first ^= code
    first = Math.imul(first, 16777619)
    second ^= code + index
    second = Math.imul(second, 3266489917)
  }
  return `${(first >>> 0).toString(16).padStart(8, '0')}${(second >>> 0).toString(16).padStart(8, '0')}`
}

function id(prefix: string, value: string): string {
  return `${prefix}-${stableHash(value)}`
}

function nowIso(value?: Date): string {
  const now = value ?? new Date()
  if (!Number.isFinite(now.getTime())) throw new SpatialRecoveryError('INVALID_PLAN', 'Recovery clock is invalid.')
  return now.toISOString()
}

function normalizeCapabilities(capabilities: readonly string[]): Set<string> {
  return new Set(capabilities.map((capability) => capability.trim().toLowerCase()).filter(Boolean))
}

/**
 * Canonical recovery command path. Presentation code can only create a plan;
 * apply validates capability, revision, confirmation and idempotency again.
 */
export class SpatialRecoveryCommandService {
  private readonly handlers: Partial<Record<SpatialRecoveryAction, RecoveryHandler>>
  private readonly applied = new Map<string, SpatialRecoveryResult>()
  private readonly audit: RecoveryAuditRecord[] = []

  constructor(options: { handlers?: Partial<Record<SpatialRecoveryAction, RecoveryHandler>> } = {}) {
    this.handlers = options.handlers ?? {}
  }

  plan(input: RecoveryPlanInput): SpatialRecoveryCommand {
    const nodeId = input.nodeId.trim()
    const targetRef = input.targetRef.trim()
    const actorRef = (input.actorRef ?? 'operator-dashboard').trim()
    if (!nodeId || !targetRef || !actorRef || !Number.isInteger(input.currentRevision) || input.currentRevision < 0) {
      throw new SpatialRecoveryError('INVALID_PLAN', 'Node, target, actor and current revision are required.')
    }
    const consequence = CONSEQUENCES[input.action]
    if (!consequence) throw new SpatialRecoveryError('INVALID_PLAN', 'Recovery action is not registered.')
    const createdAt = nowIso(input.now)
    const idempotencyKey = input.idempotencyKey?.trim() || id('idem', `${nodeId}:${targetRef}:${input.action}:${input.currentRevision}`)
    const commandId = id('recovery', `${nodeId}:${targetRef}:${input.action}:${input.currentRevision}:${idempotencyKey}`)
    const planHash = id('plan', `${nodeId}|${targetRef}|${input.action}|${input.currentRevision}|${actorRef}|${consequence.capability}`)
    const command: SpatialRecoveryCommand = {
      schema_version: SPATIAL_SCHEMA_VERSIONS.recoveryCommand,
      command_id: commandId,
      node_id: nodeId,
      target_ref: targetRef,
      action: input.action,
      requested_revision: input.currentRevision,
      plan_hash: planHash,
      actor_ref: actorRef,
      capability: consequence.capability,
      consequence: consequence.consequence,
      requires_confirmation: consequence.requiresConfirmation,
      created_at: createdAt,
      idempotency_key: idempotencyKey,
    }
    const parsed = parseSpatialRecoveryCommand(command)
    if (!parsed.ok) throw new SpatialRecoveryError('INVALID_PLAN', `Recovery plan rejected at ${parsed.diagnostic.path}.`)
    return parsed.data
  }

  async apply(input: RecoveryApplyInput): Promise<SpatialRecoveryResult> {
    const planResult = parseSpatialRecoveryCommand(input.plan)
    if (!planResult.ok) throw new SpatialRecoveryError('INVALID_PLAN', `Recovery plan rejected at ${planResult.diagnostic.path}.`)
    const plan = planResult.data
    const prior = this.applied.get(plan.idempotency_key)
    if (prior) return { ...prior, state: 'NOOP', message: 'Idempotent replay; the prior result is authoritative.' }
    if (plan.requested_revision !== input.currentRevision) throw new SpatialRecoveryError('STALE_PLAN', 'Recovery plan was created against an older status revision.')
    const capabilities = normalizeCapabilities(input.capabilities)
    if (!capabilities.has(plan.capability.toLowerCase())) throw new SpatialRecoveryError('CAPABILITY_DENIED', 'Operator capability does not permit this recovery action.')
    if (plan.requires_confirmation && !input.confirmed) throw new SpatialRecoveryError('CONFIRMATION_REQUIRED', 'This recovery action requires explicit confirmation.')
    const observedAt = nowIso()
    const auditRef = id('audit', `${plan.command_id}:${plan.plan_hash}`)
    let state: SpatialRecoveryResult['state'] = 'APPLIED'
    let errorCode: string | null = null
    let message = 'Recovery action applied through the canonical command path.'
    try {
      await this.handlers[plan.action]?.(plan)
    } catch {
      state = 'FAILED'
      errorCode = 'RECOVERY_HANDLER_FAILED'
      message = 'Recovery action failed; inspect the bounded evidence in Status.'
    }
    const result: SpatialRecoveryResult = {
      schema_version: SPATIAL_SCHEMA_VERSIONS.recoveryResult,
      command_id: plan.command_id,
      node_id: plan.node_id,
      target_ref: plan.target_ref,
      action: plan.action,
      state,
      plan_hash: plan.plan_hash,
      revision: input.currentRevision,
      observed_at: observedAt,
      audit_ref: auditRef,
      error_code: errorCode,
      message,
    }
    const parsed = parseSpatialRecoveryResult(result)
    if (!parsed.ok) throw new SpatialRecoveryError('HANDLER_FAILED', `Recovery result rejected at ${parsed.diagnostic.path}.`)
    this.applied.set(plan.idempotency_key, parsed.data)
    this.audit.push({
      audit_ref: parsed.data.audit_ref,
      command_id: plan.command_id,
      actor_ref: input.actorRef ?? plan.actor_ref,
      action: plan.action,
      target_ref: plan.target_ref,
      state: parsed.data.state,
      observed_at: parsed.data.observed_at,
    })
    return parsed.data
  }

  auditRecords(): RecoveryAuditRecord[] {
    return this.audit.map((record) => ({ ...record }))
  }
}

export type StatusWorkspaceBridgeResult =
  | { outcome: 'FOCUS_EXISTING'; canonical_ref: string; projection_kind: 'FOCUS'; world_position_preserved: true }
  | { outcome: 'DETAILS_ONLY'; canonical_ref: string; reason: 'NO_SPATIAL_REPRESENTATION' | 'STALE_REFERENCE' | 'UNAVAILABLE' }
  | { outcome: 'REJECTED'; reason: 'WRONG_WORKSPACE' | 'UNKNOWN_REFERENCE' }

/** Status → Workspace is a viewport request, never an entity mutation. */
export class StatusWorkspaceBridge {
  private readonly registry: CanonicalReferenceRegistry

  constructor(registry: CanonicalReferenceRegistry) {
    this.registry = registry
  }

  showInWorkspace(input: { workspaceId: string; nodeId: string; canonicalRef: string; hasSpatialRepresentation?: boolean; stale?: boolean }): StatusWorkspaceBridgeResult {
    if (input.workspaceId !== this.registry.workspaceId || input.nodeId !== this.registry.nodeId) return { outcome: 'REJECTED', reason: 'WRONG_WORKSPACE' }
    const reference = this.registry.resolveInScope(input.workspaceId, input.nodeId, input.canonicalRef)
    if (!reference) return { outcome: 'REJECTED', reason: 'UNKNOWN_REFERENCE' }
    if (input.stale) return { outcome: 'DETAILS_ONLY', canonical_ref: reference.canonical_ref, reason: 'STALE_REFERENCE' }
    if (reference.state !== 'AVAILABLE') return { outcome: 'DETAILS_ONLY', canonical_ref: reference.canonical_ref, reason: 'UNAVAILABLE' }
    if (input.hasSpatialRepresentation === false) return { outcome: 'DETAILS_ONLY', canonical_ref: reference.canonical_ref, reason: 'NO_SPATIAL_REPRESENTATION' }
    return { outcome: 'FOCUS_EXISTING', canonical_ref: reference.canonical_ref, projection_kind: 'FOCUS', world_position_preserved: true }
  }
}
