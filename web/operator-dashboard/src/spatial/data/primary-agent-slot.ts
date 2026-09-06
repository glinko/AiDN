import { z } from 'zod'

import {
  parseSpatialPrimaryAgentSlot,
  spatialIdSchema,
  spatialPrimaryAgentSlotSchema,
  spatialRevisionSchema,
  spatialTimestampSchema,
  SPATIAL_PRIMARY_AGENT_SLOT_LIFECYCLE_STATES,
  type SpatialPrimaryAgentSlot as SpatialPrimaryAgentSlotContract,
  type SpatialPrimaryAgentSlotLifecycleState,
} from '@/spatial/contracts'

import { normalizeSpatialNodeScope, type SpatialNodeScope } from './scope'

export const PRIMARY_AGENT_SLOT_OPERATION_KINDS = [
  'bind',
  'replace',
  'detach',
  'revoke',
  'mark-degraded',
  'mark-disconnected',
  'restore',
  'transition',
] as const
export type PrimaryAgentSlotOperationKind = (typeof PRIMARY_AGENT_SLOT_OPERATION_KINDS)[number]
export const PRIMARY_AGENT_SLOT_LIFECYCLE_STATES = SPATIAL_PRIMARY_AGENT_SLOT_LIFECYCLE_STATES

/** A binding is a separate, secret-free reference record. */
export type SpatialPrimaryAgentBindingRecord = {
  binding_id: string
  node_id: string
  agent_identity_ref: string
  runtime_ref: string
  revision: number
  capability_grant_ref?: string | null
}

const bindingRecordSchema = z.object({
  binding_id: spatialIdSchema,
  node_id: spatialIdSchema,
  agent_identity_ref: spatialIdSchema,
  runtime_ref: spatialIdSchema,
  revision: spatialRevisionSchema,
  capability_grant_ref: spatialIdSchema.nullable().optional(),
}).strip()

export type SpatialPrimaryAgentSlotOperation = {
  operation_id: string
  idempotency_key: string
  actor_ref: string
  expected_revision: number
  kind: PrimaryAgentSlotOperationKind
  binding_id?: string
  binding?: SpatialPrimaryAgentBindingRecord
  capability_grant_ref?: string | null
  hook_subscription_ref?: string | null
  durable_inbox_ref?: string | null
  lifecycle_state?: SpatialPrimaryAgentSlotLifecycleState
}

export type SpatialPrimaryAgentSlotChange = {
  change_id: string
  slot_id: string
  node_id: string
  revision: number
  operation_id: string
  actor_ref: string
  kind: PrimaryAgentSlotOperationKind
  occurred_at: string
  audit_recorded: true
}

export type SpatialPrimaryAgentSlotMutationResult = {
  slot: SpatialPrimaryAgentSlotContract
  change: SpatialPrimaryAgentSlotChange
  /** Binding events are emitted by M3.2; M3.1 records the audit seam only. */
  protocol_event_emitted: false
  audit_recorded: true
}

export type PrimaryAgentSlotConflictCode =
  | 'NODE_MISMATCH'
  | 'DUPLICATE_SLOT'
  | 'NOT_FOUND'
  | 'STALE_REVISION'
  | 'INVALID_TRANSITION'
  | 'CORRUPT_BINDING'
  | 'IDEMPOTENCY_CONFLICT'
  | 'UNAUTHORIZED'
  | 'VALIDATION'

export class PrimaryAgentSlotConflict extends Error {
  readonly code: PrimaryAgentSlotConflictCode

  constructor(code: PrimaryAgentSlotConflictCode, message: string) {
    super(message)
    this.name = 'PrimaryAgentSlotConflict'
    this.code = code
  }
}

export const PRIMARY_AGENT_SLOT_TRANSITIONS: Readonly<Record<SpatialPrimaryAgentSlotLifecycleState, readonly SpatialPrimaryAgentSlotLifecycleState[]>> = {
  UNASSIGNED: ['BINDING', 'REVOKED'],
  BINDING: ['CONNECTED', 'DEGRADED', 'DISCONNECTED', 'UNASSIGNED', 'REVOKED'],
  CONNECTED: ['BINDING', 'DEGRADED', 'DISCONNECTED', 'REVOKED'],
  DEGRADED: ['BINDING', 'CONNECTED', 'DISCONNECTED', 'UNASSIGNED', 'REVOKED'],
  DISCONNECTED: ['BINDING', 'CONNECTED', 'UNASSIGNED', 'REVOKED'],
  REVOKED: [],
}

function nowIso(now: Date): string {
  return spatialTimestampSchema.parse(now)
}

function requireText(value: unknown, label: string): string {
  if (typeof value !== 'string' || value.trim() === '') throw new PrimaryAgentSlotConflict('VALIDATION', `${label} is required.`)
  return value.trim()
}

function cloneBinding(binding: SpatialPrimaryAgentBindingRecord): SpatialPrimaryAgentBindingRecord {
  return structuredClone(binding)
}

function cloneMutation(result: SpatialPrimaryAgentSlotMutationResult): SpatialPrimaryAgentSlotMutationResult {
  return structuredClone(result)
}

export function assertPrimaryAgentSlotOwnership(slot: SpatialPrimaryAgentSlotContract, scope: SpatialNodeScope): void {
  const normalized = normalizeSpatialNodeScope(scope)
  if (slot.node_id !== normalized.node_id) throw new PrimaryAgentSlotConflict('NODE_MISMATCH', 'Primary Agent Slot belongs to a different Node.')
}

export function clonePrimaryAgentSlot(slot: SpatialPrimaryAgentSlotContract): SpatialPrimaryAgentSlotContract {
  return structuredClone(slot)
}

export function createPrimaryAgentSlot(
  scope: SpatialNodeScope,
  options: { slot_id?: string; durable_inbox_ref?: string; now?: Date } = {},
): SpatialPrimaryAgentSlotContract {
  const normalizedScope = normalizeSpatialNodeScope(scope)
  const timestamp = nowIso(options.now ?? new Date())
  const slotId = options.slot_id?.trim() || `primary-agent-slot-${normalizedScope.node_id}`
  const durableInboxRef = options.durable_inbox_ref?.trim() || `inbox-primary-agent-${normalizedScope.node_id}`
  const candidate = {
    schema_version: 'spatial.primary-agent-slot.v1',
    slot_id: requireText(slotId, 'slot_id'),
    node_id: requireText(normalizedScope.node_id, 'node_id'),
    current_binding_id: null,
    lifecycle_state: 'UNASSIGNED',
    revision: 0,
    assigned_at: null,
    assigned_by: null,
    last_seen_at: null,
    capability_grant_ref: null,
    hook_subscription_ref: null,
    durable_inbox_ref: requireText(durableInboxRef, 'durable_inbox_ref'),
    changed_at: timestamp,
  }
  const parsed = parseSpatialPrimaryAgentSlot(candidate)
  if (!parsed.ok) throw new PrimaryAgentSlotConflict('VALIDATION', 'Primary Agent Slot failed the shared contract.')
  return parsed.data
}

export function transitionPrimaryAgentSlot(
  current: SpatialPrimaryAgentSlotContract,
  lifecycleState: SpatialPrimaryAgentSlotLifecycleState,
  options: { actor_ref?: string; operation_id?: string; now?: Date } = {},
): SpatialPrimaryAgentSlotContract {
  if (current.lifecycle_state !== lifecycleState && !PRIMARY_AGENT_SLOT_TRANSITIONS[current.lifecycle_state].includes(lifecycleState)) {
    throw new PrimaryAgentSlotConflict('INVALID_TRANSITION', `Cannot transition Primary Agent Slot from ${current.lifecycle_state} to ${lifecycleState}.`)
  }
  const timestamp = nowIso(options.now ?? new Date())
  const next = {
    ...clonePrimaryAgentSlot(current),
    lifecycle_state: lifecycleState,
    revision: current.revision + (current.lifecycle_state === lifecycleState ? 0 : 1),
    last_seen_at: lifecycleState === 'CONNECTED' ? timestamp : current.last_seen_at,
    changed_at: timestamp,
  }
  if (options.actor_ref && options.operation_id) {
    next.provenance = { actor_ref: options.actor_ref, operation_id: options.operation_id, recorded_at: timestamp }
  }
  return next
}

export function serializePrimaryAgentSlot(slot: SpatialPrimaryAgentSlotContract): SpatialPrimaryAgentSlotContract {
  const parsed = parseSpatialPrimaryAgentSlot(slot)
  if (!parsed.ok) throw new PrimaryAgentSlotConflict('VALIDATION', 'Primary Agent Slot failed the shared contract.')
  return clonePrimaryAgentSlot(parsed.data)
}

type RepositoryAuthorize = (scope: SpatialNodeScope, operation: SpatialPrimaryAgentSlotOperation, slot: SpatialPrimaryAgentSlotContract) => boolean

export type InMemoryPrimaryAgentSlotRepositoryOptions = {
  bindings?: readonly SpatialPrimaryAgentBindingRecord[]
  authorize?: RepositoryAuthorize
  now?: () => Date
}

export interface SpatialPrimaryAgentSlotRepository {
  getSlot: (scope: SpatialNodeScope) => Promise<SpatialPrimaryAgentSlotContract>
  ensureSlot: (scope: SpatialNodeScope) => Promise<SpatialPrimaryAgentSlotContract>
  getChanges: (scope: SpatialNodeScope, afterRevision: number) => Promise<SpatialPrimaryAgentSlotChange[]>
  apply: (scope: SpatialNodeScope, operation: SpatialPrimaryAgentSlotOperation) => Promise<SpatialPrimaryAgentSlotMutationResult>
}

export type PrimaryAgentSlotRepository = SpatialPrimaryAgentSlotRepository

export type PrimaryAgentSlotRepositoryState = {
  slots: SpatialPrimaryAgentSlotContract[]
  bindings: SpatialPrimaryAgentBindingRecord[]
  operations: Array<{ idempotency_key: string; fingerprint: string; result: SpatialPrimaryAgentSlotMutationResult }>
  changes: SpatialPrimaryAgentSlotChange[]
}

function operationFingerprint(operation: SpatialPrimaryAgentSlotOperation): string {
  return JSON.stringify(operation)
}

function validateOperation(operation: SpatialPrimaryAgentSlotOperation): void {
  requireText(operation.operation_id, 'operation_id')
  requireText(operation.idempotency_key, 'idempotency_key')
  requireText(operation.actor_ref, 'actor_ref')
  if (!Number.isInteger(operation.expected_revision) || operation.expected_revision < 0) {
    throw new PrimaryAgentSlotConflict('VALIDATION', 'expected_revision must be a non-negative integer.')
  }
  if (!PRIMARY_AGENT_SLOT_OPERATION_KINDS.includes(operation.kind)) {
    throw new PrimaryAgentSlotConflict('VALIDATION', 'Primary Agent Slot operation kind is not supported.')
  }
}

function validateBinding(bindingInput: unknown): SpatialPrimaryAgentBindingRecord {
  const parsed = bindingRecordSchema.safeParse(bindingInput)
  if (!parsed.success) throw new PrimaryAgentSlotConflict('VALIDATION', 'Agent binding reference failed the safe contract.')
  return parsed.data
}

function operationBindingId(operation: SpatialPrimaryAgentSlotOperation): string | null {
  const bindingId = operation.binding_id ?? operation.binding?.binding_id
  return typeof bindingId === 'string' && bindingId.trim() ? bindingId.trim() : null
}

function slotForOperation(
  current: SpatialPrimaryAgentSlotContract,
  operation: SpatialPrimaryAgentSlotOperation,
  binding: SpatialPrimaryAgentBindingRecord | null,
  timestamp: string,
): SpatialPrimaryAgentSlotContract {
  const provenance = { actor_ref: operation.actor_ref.trim(), operation_id: operation.operation_id.trim(), recorded_at: timestamp }
  const next = clonePrimaryAgentSlot(current)
  next.revision = current.revision + 1
  next.changed_at = timestamp
  next.provenance = provenance

  switch (operation.kind) {
    case 'bind':
    case 'replace': {
      if (!binding) throw new PrimaryAgentSlotConflict('CORRUPT_BINDING', 'A bind operation references a missing Agent binding.')
      next.current_binding_id = binding.binding_id
      next.lifecycle_state = 'CONNECTED'
      next.assigned_at = timestamp
      next.assigned_by = operation.actor_ref.trim()
      next.last_seen_at = timestamp
      // A replacement never inherits the previous binding's privileges or
      // hook subscription implicitly. Grants and hooks are re-issued by the
      // authorized binding path; the durable inbox remains slot-owned.
      next.capability_grant_ref = operation.capability_grant_ref === undefined ? binding.capability_grant_ref ?? null : operation.capability_grant_ref
      next.hook_subscription_ref = operation.hook_subscription_ref === undefined ? null : operation.hook_subscription_ref
      next.durable_inbox_ref = operation.durable_inbox_ref === undefined ? current.durable_inbox_ref : operation.durable_inbox_ref
      return next
    }
    case 'detach':
      next.current_binding_id = null
      next.lifecycle_state = 'UNASSIGNED'
      next.assigned_at = null
      next.assigned_by = null
      next.capability_grant_ref = null
      next.hook_subscription_ref = null
      return next
    case 'revoke':
      next.current_binding_id = null
      next.lifecycle_state = 'REVOKED'
      next.capability_grant_ref = null
      next.hook_subscription_ref = null
      return next
    case 'mark-degraded':
      next.lifecycle_state = 'DEGRADED'
      return next
    case 'mark-disconnected':
      next.lifecycle_state = 'DISCONNECTED'
      return next
    case 'restore':
      next.lifecycle_state = current.current_binding_id ? 'CONNECTED' : 'UNASSIGNED'
      next.last_seen_at = current.current_binding_id ? timestamp : current.last_seen_at
      return next
    case 'transition':
      if (!operation.lifecycle_state) throw new PrimaryAgentSlotConflict('VALIDATION', 'transition requires lifecycle_state.')
      if (current.lifecycle_state !== operation.lifecycle_state && !PRIMARY_AGENT_SLOT_TRANSITIONS[current.lifecycle_state].includes(operation.lifecycle_state)) {
        throw new PrimaryAgentSlotConflict('INVALID_TRANSITION', `Cannot transition Primary Agent Slot from ${current.lifecycle_state} to ${operation.lifecycle_state}.`)
      }
      next.lifecycle_state = operation.lifecycle_state
      if (operation.lifecycle_state === 'CONNECTED') next.last_seen_at = timestamp
      return next
  }
}

function assertOperationTransition(current: SpatialPrimaryAgentSlotContract, operation: SpatialPrimaryAgentSlotOperation): void {
  switch (operation.kind) {
    case 'bind':
      if (current.lifecycle_state !== 'UNASSIGNED' || current.current_binding_id) {
        throw new PrimaryAgentSlotConflict('INVALID_TRANSITION', `Cannot bind a Primary Agent Slot from ${current.lifecycle_state}. Use replace for an active binding.`)
      }
      return
    case 'replace':
      if (current.lifecycle_state === 'UNASSIGNED' || current.lifecycle_state === 'REVOKED' || !current.current_binding_id) {
        throw new PrimaryAgentSlotConflict('INVALID_TRANSITION', `Cannot replace a Primary Agent Slot from ${current.lifecycle_state}.`)
      }
      return
    case 'detach':
      if (!['BINDING', 'CONNECTED', 'DEGRADED', 'DISCONNECTED'].includes(current.lifecycle_state) || !current.current_binding_id) {
        throw new PrimaryAgentSlotConflict('INVALID_TRANSITION', `Cannot detach a Primary Agent Slot from ${current.lifecycle_state}.`)
      }
      return
    case 'revoke':
      if (current.lifecycle_state === 'REVOKED') throw new PrimaryAgentSlotConflict('INVALID_TRANSITION', 'Primary Agent Slot is already revoked.')
      return
    case 'mark-degraded':
    case 'mark-disconnected':
      if (current.lifecycle_state === 'UNASSIGNED' || current.lifecycle_state === 'REVOKED' || !current.current_binding_id) {
        throw new PrimaryAgentSlotConflict('INVALID_TRANSITION', `Cannot mark an unbound Primary Agent Slot as ${operation.kind}.`)
      }
      return
    case 'restore':
      if (current.lifecycle_state === 'REVOKED' || current.lifecycle_state === 'UNASSIGNED' || !current.current_binding_id) {
        throw new PrimaryAgentSlotConflict('INVALID_TRANSITION', `Cannot restore a Primary Agent Slot from ${current.lifecycle_state}.`)
      }
      return
    case 'transition':
      if (!operation.lifecycle_state) throw new PrimaryAgentSlotConflict('VALIDATION', 'transition requires lifecycle_state.')
      if (current.lifecycle_state !== operation.lifecycle_state && !PRIMARY_AGENT_SLOT_TRANSITIONS[current.lifecycle_state].includes(operation.lifecycle_state)) {
        throw new PrimaryAgentSlotConflict('INVALID_TRANSITION', `Cannot transition Primary Agent Slot from ${current.lifecycle_state} to ${operation.lifecycle_state}.`)
      }
      return
  }
}

export class InMemoryPrimaryAgentSlotRepository implements SpatialPrimaryAgentSlotRepository {
  private readonly slots = new Map<string, SpatialPrimaryAgentSlotContract>()
  private readonly bindings = new Map<string, SpatialPrimaryAgentBindingRecord>()
  private readonly operations = new Map<string, { fingerprint: string; result: SpatialPrimaryAgentSlotMutationResult }>()
  private readonly changes: SpatialPrimaryAgentSlotChange[] = []
  private readonly authorize?: RepositoryAuthorize
  private readonly now: () => Date

  constructor(
    initial?: SpatialPrimaryAgentSlotContract | readonly SpatialPrimaryAgentSlotContract[],
    options: InMemoryPrimaryAgentSlotRepositoryOptions = {},
  ) {
    this.authorize = options.authorize
    this.now = options.now ?? (() => new Date())
    for (const binding of options.bindings ?? []) this.registerBinding(binding)
    const slots = initial ? (Array.isArray(initial) ? initial : [initial]) : []
    for (const slot of slots) this.insertSlot(slot)
  }

  private key(scope: SpatialNodeScope): string {
    // The canonical slot is Node-owned. Hypervisor remains part of the query
    // scope, but cannot create a second slot for the same Node identity.
    return `node:${normalizeSpatialNodeScope(scope).node_id}`
  }

  private insertSlot(slotInput: unknown): SpatialPrimaryAgentSlotContract {
    const parsed = parseSpatialPrimaryAgentSlot(slotInput)
    if (!parsed.ok) throw new PrimaryAgentSlotConflict('VALIDATION', 'Primary Agent Slot failed the shared contract.')
    const slot = parsed.data
    const key = `node:${slot.node_id}`
    if (this.slots.has(key)) throw new PrimaryAgentSlotConflict('DUPLICATE_SLOT', 'A Node can have only one Primary Agent Slot.')
    this.assertBindingReference(slot)
    this.slots.set(key, clonePrimaryAgentSlot(slot))
    return clonePrimaryAgentSlot(slot)
  }

  private assertBindingReference(slot: SpatialPrimaryAgentSlotContract): void {
    const requiresBinding = ['BINDING', 'CONNECTED', 'DEGRADED', 'DISCONNECTED'].includes(slot.lifecycle_state)
    if (!slot.current_binding_id) {
      if (requiresBinding) throw new PrimaryAgentSlotConflict('CORRUPT_BINDING', 'A connected Primary Agent Slot is missing its binding reference.')
      return
    }
    if (slot.lifecycle_state === 'UNASSIGNED' || slot.lifecycle_state === 'REVOKED') {
      throw new PrimaryAgentSlotConflict('CORRUPT_BINDING', 'An unassigned or revoked Primary Agent Slot cannot retain a binding reference.')
    }
    const binding = this.bindings.get(slot.current_binding_id)
    if (!binding) throw new PrimaryAgentSlotConflict('CORRUPT_BINDING', 'Primary Agent Slot references a missing Agent binding.')
    if (binding.node_id !== slot.node_id) throw new PrimaryAgentSlotConflict('NODE_MISMATCH', 'Agent binding belongs to a different Node.')
  }

  registerBinding(bindingInput: unknown): SpatialPrimaryAgentBindingRecord {
    const binding = validateBinding(bindingInput)
    const existing = this.bindings.get(binding.binding_id)
    if (existing) {
      if (JSON.stringify(existing) !== JSON.stringify(binding)) throw new PrimaryAgentSlotConflict('IDEMPOTENCY_CONFLICT', 'Binding reference already exists with different data.')
      return cloneBinding(existing)
    }
    this.bindings.set(binding.binding_id, cloneBinding(binding))
    return cloneBinding(binding)
  }

  getBinding(bindingId: string): SpatialPrimaryAgentBindingRecord | null {
    const normalizedId = requireText(bindingId, 'binding_id')
    const binding = this.bindings.get(normalizedId)
    return binding ? cloneBinding(binding) : null
  }

  createSlot(scope: SpatialNodeScope, options: { slot_id?: string; durable_inbox_ref?: string; now?: Date } = {}): SpatialPrimaryAgentSlotContract {
    const key = this.key(scope)
    if (this.slots.has(key)) throw new PrimaryAgentSlotConflict('DUPLICATE_SLOT', 'A Node can have only one Primary Agent Slot.')
    return this.insertSlot(createPrimaryAgentSlot(scope, options))
  }

  async ensureSlot(scope: SpatialNodeScope): Promise<SpatialPrimaryAgentSlotContract> {
    const existing = this.slots.get(this.key(scope))
    return existing ? this.getSlot(scope) : this.createSlot(scope)
  }

  async getSlot(scope: SpatialNodeScope): Promise<SpatialPrimaryAgentSlotContract> {
    const slot = this.slots.get(this.key(scope))
    if (!slot) throw new PrimaryAgentSlotConflict('NOT_FOUND', 'Primary Agent Slot was not found for this Node.')
    assertPrimaryAgentSlotOwnership(slot, scope)
    this.assertBindingReference(slot)
    return clonePrimaryAgentSlot(slot)
  }

  async get(scope: SpatialNodeScope): Promise<SpatialPrimaryAgentSlotContract> {
    return this.getSlot(scope)
  }

  async apply(scope: SpatialNodeScope, operation: SpatialPrimaryAgentSlotOperation): Promise<SpatialPrimaryAgentSlotMutationResult> {
    const normalizedScope = normalizeSpatialNodeScope(scope)
    validateOperation(operation)
    const slot = await this.getSlot(normalizedScope)
    const fingerprint = operationFingerprint(operation)
    const existing = this.operations.get(operation.idempotency_key)
    if (existing) {
      if (existing.fingerprint !== fingerprint) throw new PrimaryAgentSlotConflict('IDEMPOTENCY_CONFLICT', 'Idempotency key was already used for another operation.')
      if (existing.result.change.actor_ref !== operation.actor_ref.trim()) throw new PrimaryAgentSlotConflict('UNAUTHORIZED', 'Idempotency key belongs to another operator.')
      return cloneMutation(existing.result)
    }
    if (this.authorize && !this.authorize(normalizedScope, operation, slot)) throw new PrimaryAgentSlotConflict('UNAUTHORIZED', 'Operator is not authorized for this Primary Agent Slot operation.')
    if (operation.expected_revision !== slot.revision) throw new PrimaryAgentSlotConflict('STALE_REVISION', 'Primary Agent Slot revision changed before the operation was applied.')
    assertOperationTransition(slot, operation)

    let binding: SpatialPrimaryAgentBindingRecord | null = null
    if (operation.kind === 'bind' || operation.kind === 'replace') {
      const bindingId = operationBindingId(operation)
      if (!bindingId) throw new PrimaryAgentSlotConflict('VALIDATION', `${operation.kind} requires a binding_id.`)
      if (operation.binding) {
        const staged = validateBinding(operation.binding)
        if (staged.binding_id !== bindingId) throw new PrimaryAgentSlotConflict('VALIDATION', 'binding_id does not match the binding record.')
        if (staged.node_id !== normalizedScope.node_id) throw new PrimaryAgentSlotConflict('NODE_MISMATCH', 'Agent binding belongs to a different Node.')
        const registered = this.bindings.get(bindingId)
        if (registered && JSON.stringify(registered) !== JSON.stringify(staged)) throw new PrimaryAgentSlotConflict('IDEMPOTENCY_CONFLICT', 'Binding reference already exists with different data.')
        binding = registered ?? staged
      } else {
        binding = this.bindings.get(bindingId) ?? null
      }
      if (!binding) throw new PrimaryAgentSlotConflict('CORRUPT_BINDING', 'Bind operation references a missing Agent binding.')
      if (binding.node_id !== normalizedScope.node_id) throw new PrimaryAgentSlotConflict('NODE_MISMATCH', 'Agent binding belongs to a different Node.')
    }

    // The initial read is intentionally async to match a real repository. A
    // second revision check immediately before commit closes the optimistic
    // concurrency window when two bind commands arrive in the same tick.
    const currentAtCommit = this.slots.get(this.key(normalizedScope))
    if (!currentAtCommit || currentAtCommit.revision !== slot.revision) {
      throw new PrimaryAgentSlotConflict('STALE_REVISION', 'Primary Agent Slot revision changed before the operation was committed.')
    }
    const timestamp = nowIso(this.now())
    const nextSlot = slotForOperation(slot, operation, binding, timestamp)
    const change: SpatialPrimaryAgentSlotChange = {
      change_id: `${nextSlot.slot_id}:change:${nextSlot.revision}`,
      slot_id: nextSlot.slot_id,
      node_id: nextSlot.node_id,
      revision: nextSlot.revision,
      operation_id: operation.operation_id.trim(),
      actor_ref: operation.actor_ref.trim(),
      kind: operation.kind,
      occurred_at: timestamp,
      audit_recorded: true,
    }
    const result: SpatialPrimaryAgentSlotMutationResult = {
      slot: clonePrimaryAgentSlot(nextSlot),
      change,
      protocol_event_emitted: false,
      audit_recorded: true,
    }
    // Commit all state only after validation and transition checks complete.
    if (operation.binding && binding && !this.bindings.has(binding.binding_id)) this.bindings.set(binding.binding_id, cloneBinding(binding))
    this.slots.set(this.key(normalizedScope), clonePrimaryAgentSlot(nextSlot))
    this.changes.push({ ...change })
    this.operations.set(operation.idempotency_key, { fingerprint, result: cloneMutation(result) })
    return cloneMutation(result)
  }

  async applyOperation(scope: SpatialNodeScope, operation: SpatialPrimaryAgentSlotOperation): Promise<SpatialPrimaryAgentSlotMutationResult> {
    return this.apply(scope, operation)
  }

  async getChanges(scope: SpatialNodeScope, afterRevision: number): Promise<SpatialPrimaryAgentChange[]> {
    const slot = await this.getSlot(scope)
    if (!Number.isInteger(afterRevision) || afterRevision < 0) throw new PrimaryAgentSlotConflict('VALIDATION', 'Slot change cursor is invalid.')
    return this.changes.filter((change) => change.node_id === slot.node_id && change.revision > afterRevision).map((change) => ({ ...change }))
  }

  serialize(): PrimaryAgentSlotRepositoryState {
    return {
      slots: [...this.slots.values()].map(clonePrimaryAgentSlot),
      bindings: [...this.bindings.values()].map(cloneBinding),
      operations: [...this.operations.entries()].map(([idempotency_key, { fingerprint, result }]) => ({
        idempotency_key,
        fingerprint,
        result: cloneMutation(result),
      })),
      changes: this.changes.map((change) => ({ ...change })),
    }
  }

  restart(): InMemoryPrimaryAgentSlotRepository {
    return InMemoryPrimaryAgentSlotRepository.fromState(this.serialize(), { authorize: this.authorize, now: this.now })
  }

  static fromState(state: PrimaryAgentSlotRepositoryState, options: InMemoryPrimaryAgentSlotRepositoryOptions = {}): InMemoryPrimaryAgentSlotRepository {
    const repository = new InMemoryPrimaryAgentSlotRepository(undefined, { ...options, bindings: state.bindings })
    for (const slot of state.slots) repository.insertSlot(slot)
    for (const operation of state.operations) repository.operations.set(operation.idempotency_key, {
      fingerprint: operation.fingerprint,
      result: cloneMutation(operation.result),
    })
    repository.changes.push(...state.changes.map((change) => ({ ...change })))
    return repository
  }
}

/** Alias follows the naming used by the other Spatial repositories. */
export const InMemorySpatialPrimaryAgentSlotRepository = InMemoryPrimaryAgentSlotRepository
export type SpatialPrimaryAgentChange = SpatialPrimaryAgentSlotChange
export type SpatialPrimaryAgentSlot = SpatialPrimaryAgentSlotContract
export { parseSpatialPrimaryAgentSlot, spatialPrimaryAgentSlotSchema }
export type { SpatialPrimaryAgentSlotLifecycleState }
