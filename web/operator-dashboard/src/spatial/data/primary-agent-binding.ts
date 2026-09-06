import { z } from 'zod'

import {
  SPATIAL_SCHEMA_VERSIONS,
  spatialIdSchema,
  spatialRevisionSchema,
  spatialTimestampSchema,
  type SpatialPrimaryAgentSlot,
} from '@/spatial/contracts'

import {
  InMemoryPrimaryAgentSlotRepository,
  PrimaryAgentSlotConflict,
  type PrimaryAgentSlotRepository,
  type SpatialPrimaryAgentBindingRecord,
  type SpatialPrimaryAgentSlotMutationResult,
  type SpatialPrimaryAgentSlotOperation,
} from './primary-agent-slot'
import { normalizeSpatialNodeScope, type SpatialNodeScope } from './scope'

export const PRIMARY_AGENT_BINDING_OPERATIONS = ['bind', 'replace', 'suspend', 'detach', 'revoke', 'recover'] as const
export type PrimaryAgentBindingOperation = (typeof PRIMARY_AGENT_BINDING_OPERATIONS)[number]

const bindingPlanFields = z.object({
  schema_version: z.literal('spatial.primary-agent-binding-plan.v1'),
  plan_id: spatialIdSchema,
  slot_id: spatialIdSchema,
  node_id: spatialIdSchema,
  expected_revision: spatialRevisionSchema,
  operation: z.preprocess((value) => typeof value === 'string' ? value.trim().toLowerCase() : value, z.enum(PRIMARY_AGENT_BINDING_OPERATIONS)),
  actor_ref: spatialIdSchema,
  idempotency_key: spatialIdSchema,
  binding: z.object({
    binding_id: spatialIdSchema,
    node_id: spatialIdSchema,
    agent_identity_ref: spatialIdSchema,
    runtime_ref: spatialIdSchema,
    revision: spatialRevisionSchema,
    capability_grant_ref: spatialIdSchema.nullable().optional(),
  }).strip().optional(),
  capability_grant_ref: spatialIdSchema.nullable().optional(),
  hook_subscription_ref: spatialIdSchema.nullable().optional(),
  durable_inbox_ref: spatialIdSchema.nullable().optional(),
  created_at: spatialTimestampSchema,
  expires_at: spatialTimestampSchema.nullable().optional(),
}).strip()

const bindingPlanSchema = bindingPlanFields.extend({ plan_hash: spatialIdSchema })

export type PrimaryAgentBindingPlan = z.infer<typeof bindingPlanSchema>
export type PrimaryAgentBindingPlanInput = Omit<PrimaryAgentBindingPlan, 'plan_hash' | 'schema_version' | 'created_at'> & {
  plan_id?: string
  created_at?: Date | string
  expires_at?: Date | string | null
}

export type PrimaryAgentBindingInspection = {
  slot: SpatialPrimaryAgentSlot
  binding: SpatialPrimaryAgentBindingRecord | null
}

export type PrimaryAgentBindingHealth = {
  node_id: string
  slot_id: string
  binding_id: string | null
  status: 'healthy' | 'degraded' | 'disconnected' | 'unassigned' | 'revoked' | 'invalid-credentials' | 'incompatible-protocol' | 'unknown'
  observed_at: string
  source: string
  revision: number
}

export type PrimaryAgentBindingAudit = {
  audit_id: string
  actor_ref: string
  operation: PrimaryAgentBindingOperation
  node_id: string
  slot_id: string
  revision: number
  occurred_at: string
  secret_material_present: false
}

export type PrimaryAgentBindingChangedEvent = {
  event_id: string
  event_type: 'spatial.primary-agent.binding-changed.v1'
  schema_version: typeof SPATIAL_SCHEMA_VERSIONS.primaryAgentSlot
  node_id: string
  sequence: number
  revision: number
  occurred_at: string
  correlation_id: string | null
  causation_id: string | null
  payload: SpatialPrimaryAgentSlot
}

export type PrimaryAgentBindingCommandResult = {
  plan: PrimaryAgentBindingPlan
  mutation: SpatialPrimaryAgentSlotMutationResult
  audit: PrimaryAgentBindingAudit
  event: PrimaryAgentBindingChangedEvent
}

export type PrimaryAgentBindingApiOptions = {
  repository: PrimaryAgentSlotRepository
  authorize?: (scope: SpatialNodeScope, plan: PrimaryAgentBindingPlan, slot: SpatialPrimaryAgentSlot) => boolean | Promise<boolean>
  now?: () => Date
  onEvent?: (event: PrimaryAgentBindingChangedEvent) => void
  onBindingRevoked?: (bindingId: string, slot: SpatialPrimaryAgentSlot) => void
}

function nowIso(now: Date): string {
  return spatialTimestampSchema.parse(now)
}

function text(value: unknown, label: string): string {
  if (typeof value !== 'string' || value.trim() === '') throw new PrimaryAgentSlotConflict('VALIDATION', `${label} is required.`)
  return value.trim()
}

function stableStringify(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(',')}]`
  if (value && typeof value === 'object') {
    return `{${Object.keys(value as Record<string, unknown>).sort().map((key) => `${JSON.stringify(key)}:${stableStringify((value as Record<string, unknown>)[key])}`).join(',')}}`
  }
  return JSON.stringify(value)
}

function fnv1a(value: string): string {
  let hash = 2166136261
  for (let index = 0; index < value.length; index += 1) hash = Math.imul(hash ^ value.charCodeAt(index), 16777619)
  return (hash >>> 0).toString(16).padStart(8, '0')
}

/** Deterministic plan hash; plan material contains only safe binding references. */
export function computePrimaryAgentBindingPlanHash(plan: Omit<PrimaryAgentBindingPlan, 'plan_hash'> | Record<string, unknown>): string {
  const copy = { ...(plan as Record<string, unknown>) }
  delete copy.plan_hash
  return `sha256:local-${fnv1a(stableStringify(copy))}`
}

function safeBinding(binding: SpatialPrimaryAgentBindingRecord | undefined): SpatialPrimaryAgentBindingRecord | undefined {
  if (!binding) return undefined
  const result = z.object({
    binding_id: spatialIdSchema,
    node_id: spatialIdSchema,
    agent_identity_ref: spatialIdSchema,
    runtime_ref: spatialIdSchema,
    revision: spatialRevisionSchema,
    capability_grant_ref: spatialIdSchema.nullable().optional(),
  }).strip().safeParse(binding)
  if (!result.success) throw new PrimaryAgentSlotConflict('VALIDATION', 'Binding plan contains an invalid safe binding reference.')
  return result.data
}

function normalizePlan(plan: unknown): PrimaryAgentBindingPlan {
  const parsed = bindingPlanSchema.safeParse(plan)
  if (!parsed.success) throw new PrimaryAgentSlotConflict('VALIDATION', 'Binding plan failed the typed command contract.')
  const expectedHash = computePrimaryAgentBindingPlanHash(parsed.data)
  if (expectedHash !== parsed.data.plan_hash) throw new PrimaryAgentSlotConflict('VALIDATION', 'Binding plan hash does not match its contents.')
  return parsed.data
}

function bindingFor(repository: PrimaryAgentSlotRepository, bindingId: string | null): SpatialPrimaryAgentBindingRecord | null {
  if (!bindingId) return null
  const candidate = repository as PrimaryAgentSlotRepository & { getBinding?: (id: string) => SpatialPrimaryAgentBindingRecord | null }
  return candidate.getBinding?.(bindingId) ?? null
}

function operationKind(operation: PrimaryAgentBindingOperation): SpatialPrimaryAgentSlotOperation['kind'] {
  switch (operation) {
    case 'suspend': return 'mark-disconnected'
    case 'recover': return 'restore'
    default: return operation
  }
}

export class PrimaryAgentBindingApi {
  private readonly repository: PrimaryAgentSlotRepository
  private readonly authorize?: PrimaryAgentBindingApiOptions['authorize']
  private readonly now: () => Date
  private readonly onEvent?: PrimaryAgentBindingApiOptions['onEvent']
  private readonly onBindingRevoked?: PrimaryAgentBindingApiOptions['onBindingRevoked']
  private readonly sequences = new Map<string, number>()
  private readonly appliedPlans = new Map<string, PrimaryAgentBindingCommandResult>()

  constructor(options: PrimaryAgentBindingApiOptions) {
    this.repository = options.repository
    this.authorize = options.authorize
    this.now = options.now ?? (() => new Date())
    this.onEvent = options.onEvent
    this.onBindingRevoked = options.onBindingRevoked
  }

  async inspectSlot(scope: SpatialNodeScope): Promise<PrimaryAgentBindingInspection> {
    const slot = await this.repository.ensureSlot(scope)
    return { slot, binding: bindingFor(this.repository, slot.current_binding_id) }
  }

  async createBindingPlan(scope: SpatialNodeScope, input: {
    operation: PrimaryAgentBindingOperation
    actor_ref: string
    idempotency_key: string
    binding?: SpatialPrimaryAgentBindingRecord
    capability_grant_ref?: string | null
    hook_subscription_ref?: string | null
    durable_inbox_ref?: string | null
    plan_id?: string
    expires_at?: Date | string | null
  }): Promise<PrimaryAgentBindingPlan> {
    const normalizedScope = normalizeSpatialNodeScope(scope)
    const slot = await this.repository.ensureSlot(normalizedScope)
    const operation = text(input.operation, 'operation').toLowerCase() as PrimaryAgentBindingOperation
    if (!PRIMARY_AGENT_BINDING_OPERATIONS.includes(operation)) throw new PrimaryAgentSlotConflict('VALIDATION', 'Binding operation is not supported.')
    const binding = safeBinding(input.binding)
    if ((operation === 'bind' || operation === 'replace') && !binding) throw new PrimaryAgentSlotConflict('VALIDATION', `${operation} requires a safe binding reference.`)
    if (binding && binding.node_id !== normalizedScope.node_id) throw new PrimaryAgentSlotConflict('NODE_MISMATCH', 'Binding plan belongs to a different Node.')
    const planBase = {
      schema_version: 'spatial.primary-agent-binding-plan.v1' as const,
      plan_id: text(input.plan_id ?? `${slot.slot_id}:plan:${input.idempotency_key}`, 'plan_id'),
      slot_id: slot.slot_id,
      node_id: normalizedScope.node_id,
      expected_revision: slot.revision,
      operation,
      actor_ref: text(input.actor_ref, 'actor_ref'),
      idempotency_key: text(input.idempotency_key, 'idempotency_key'),
      ...(binding ? { binding } : {}),
      ...(input.capability_grant_ref === undefined ? {} : { capability_grant_ref: input.capability_grant_ref }),
      ...(input.hook_subscription_ref === undefined ? {} : { hook_subscription_ref: input.hook_subscription_ref }),
      ...(input.durable_inbox_ref === undefined ? {} : { durable_inbox_ref: input.durable_inbox_ref }),
      created_at: nowIso(this.now()),
      ...(input.expires_at === undefined ? {} : { expires_at: input.expires_at instanceof Date ? nowIso(input.expires_at) : input.expires_at }),
    }
    const parsedBase = bindingPlanFields.safeParse(planBase)
    if (!parsedBase.success) throw new PrimaryAgentSlotConflict('VALIDATION', `Binding plan failed the typed command contract at ${parsedBase.error.issues[0]?.path.join('.') || '<root>'}.`)
    return { ...parsedBase.data, plan_hash: computePrimaryAgentBindingPlanHash(parsedBase.data) }
  }

  async applyBindingPlan(scope: SpatialNodeScope, input: PrimaryAgentBindingPlan): Promise<PrimaryAgentBindingCommandResult> {
    const normalizedScope = normalizeSpatialNodeScope(scope)
    const plan = normalizePlan(input)
    if (plan.node_id !== normalizedScope.node_id) throw new PrimaryAgentSlotConflict('NODE_MISMATCH', 'Binding plan belongs to a different Node.')
    const slot = await this.repository.getSlot(normalizedScope)
    if (slot.slot_id !== plan.slot_id) throw new PrimaryAgentSlotConflict('NODE_MISMATCH', 'Binding plan targets a different Primary Agent Slot.')
    if (this.authorize && !(await this.authorize(normalizedScope, plan, slot))) throw new PrimaryAgentSlotConflict('UNAUTHORIZED', 'Operator is not authorized for this binding plan.')
    const applied = this.appliedPlans.get(plan.idempotency_key)
    if (applied) {
      if (applied.plan.plan_hash !== plan.plan_hash) throw new PrimaryAgentSlotConflict('IDEMPOTENCY_CONFLICT', 'Idempotency key was already used for another binding plan.')
      return structuredClone(applied)
    }
    const binding = plan.binding
    const operation: SpatialPrimaryAgentSlotOperation = {
      operation_id: plan.plan_id,
      idempotency_key: plan.idempotency_key,
      actor_ref: plan.actor_ref,
      expected_revision: plan.expected_revision,
      kind: operationKind(plan.operation),
      ...(binding ? { binding_id: binding.binding_id, binding } : {}),
      ...(plan.capability_grant_ref === undefined ? {} : { capability_grant_ref: plan.capability_grant_ref }),
      ...(plan.hook_subscription_ref === undefined ? {} : { hook_subscription_ref: plan.hook_subscription_ref }),
      ...(plan.durable_inbox_ref === undefined ? {} : { durable_inbox_ref: plan.durable_inbox_ref }),
    }
    const mutation = await this.repository.apply(normalizedScope, operation)
    const sequence = Math.max((this.sequences.get(normalizedScope.node_id) ?? 0) + 1, mutation.change.revision)
    this.sequences.set(normalizedScope.node_id, sequence)
    const event: PrimaryAgentBindingChangedEvent = {
      event_id: `${mutation.change.change_id}:event`,
      event_type: 'spatial.primary-agent.binding-changed.v1',
      schema_version: SPATIAL_SCHEMA_VERSIONS.primaryAgentSlot,
      node_id: normalizedScope.node_id,
      sequence,
      revision: mutation.change.revision,
      occurred_at: mutation.change.occurred_at,
      correlation_id: plan.plan_id,
      causation_id: mutation.change.operation_id,
      payload: mutation.slot,
    }
    const audit: PrimaryAgentBindingAudit = {
      audit_id: mutation.change.change_id,
      actor_ref: mutation.change.actor_ref,
      operation: plan.operation,
      node_id: normalizedScope.node_id,
      slot_id: mutation.slot.slot_id,
      revision: mutation.slot.revision,
      occurred_at: mutation.change.occurred_at,
      secret_material_present: false,
    }
    this.onEvent?.(event)
    const previousBindingId = slot.current_binding_id
    const bindingWasRemoved = previousBindingId
      && ['replace', 'detach', 'revoke'].includes(plan.operation)
      && previousBindingId !== mutation.slot.current_binding_id
    if (bindingWasRemoved) this.onBindingRevoked?.(previousBindingId, mutation.slot)
    const result = { plan, mutation, audit, event }
    this.appliedPlans.set(plan.idempotency_key, structuredClone(result))
    return result
  }

  applyPlan(scope: SpatialNodeScope, plan: PrimaryAgentBindingPlan): Promise<PrimaryAgentBindingCommandResult> {
    return this.applyBindingPlan(scope, plan)
  }

  async verifyHealth(scope: SpatialNodeScope): Promise<PrimaryAgentBindingHealth> {
    const inspection = await this.inspectSlot(scope)
    const status = inspection.slot.lifecycle_state === 'CONNECTED'
      ? 'healthy'
      : inspection.slot.lifecycle_state === 'DEGRADED'
        ? 'degraded'
        : inspection.slot.lifecycle_state === 'DISCONNECTED'
          ? 'disconnected'
          : inspection.slot.lifecycle_state === 'REVOKED'
            ? 'revoked'
            : inspection.slot.lifecycle_state === 'UNASSIGNED'
              ? 'unassigned'
              : 'unknown'
    return {
      node_id: inspection.slot.node_id,
      slot_id: inspection.slot.slot_id,
      binding_id: inspection.slot.current_binding_id,
      status,
      observed_at: nowIso(this.now()),
      source: 'primary-agent-binding-api',
      revision: inspection.slot.revision,
    }
  }

  async recoverPreviousSafeState(scope: SpatialNodeScope, actor_ref: string, idempotency_key: string): Promise<PrimaryAgentBindingCommandResult> {
    const plan = await this.createBindingPlan(scope, { operation: 'recover', actor_ref, idempotency_key })
    return this.applyBindingPlan(scope, plan)
  }
}

export function createPrimaryAgentBindingApi(options: PrimaryAgentBindingApiOptions): PrimaryAgentBindingApi {
  return new PrimaryAgentBindingApi(options)
}

export { InMemoryPrimaryAgentSlotRepository }
export { bindingPlanSchema as spatialPrimaryAgentBindingPlanSchema }
