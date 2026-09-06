import { z } from 'zod'

import {
  SPATIAL_PRIMARY_AGENT_ATTENTION_SEVERITIES,
  SPATIAL_PRIMARY_AGENT_CAPABILITY_CATEGORIES,
  SPATIAL_SCHEMA_VERSIONS,
  parseSpatialPrimaryAgentGrant,
  spatialRevisionSchema,
  spatialTimestampSchema,
  type SpatialPrimaryAgentGrant,
} from '@/spatial/contracts'

import { type PrimaryAgentSlotRepository, type SpatialPrimaryAgentSlot } from './primary-agent-slot'
import { normalizeSpatialNodeScope, type SpatialNodeScope } from './scope'

export const PRIMARY_AGENT_DELIVERY_STATES = ['PENDING', 'DELIVERED', 'ACKED', 'DEAD_LETTER'] as const
export type PrimaryAgentDeliveryState = (typeof PRIMARY_AGENT_DELIVERY_STATES)[number]

export const PRIMARY_AGENT_HOOK_STATES = ['ACTIVE', 'PAUSED', 'REVOKED'] as const
export type PrimaryAgentHookState = (typeof PRIMARY_AGENT_HOOK_STATES)[number]

export type PrimaryAgentCapabilityCategory = (typeof SPATIAL_PRIMARY_AGENT_CAPABILITY_CATEGORIES)[number]
export type PrimaryAgentAttentionSeverity = (typeof SPATIAL_PRIMARY_AGENT_ATTENTION_SEVERITIES)[number]

export type PrimaryAgentRedactionProfile = {
  profile_id: string
  redact_keys: readonly string[]
  redact_paths?: readonly string[]
  replacement?: string
}

export type PrimaryAgentHookFilter = {
  event_types?: readonly string[]
  resource_refs?: readonly string[]
  severities?: readonly PrimaryAgentAttentionSeverity[]
}

export type PrimaryAgentHookSubscription = {
  schema_version: 'spatial.primary-agent-hook.v1'
  subscription_id: string
  node_id: string
  binding_id: string
  revision: number
  filter: PrimaryAgentHookFilter
  redaction_profile: PrimaryAgentRedactionProfile
  delivery_cursor: number
  state: PrimaryAgentHookState
  created_at: string
  updated_at: string
}

export type PrimaryAgentInboxEvent = {
  event_id: string
  node_id: string
  event_type: string
  resource_ref?: string | null
  severity?: PrimaryAgentAttentionSeverity
  sequence: number
  payload: unknown
  occurred_at?: string
}

export type PrimaryAgentInboxRecord = {
  inbox_id: string
  event_id: string
  node_id: string
  slot_id: string
  binding_id: string | null
  event_type: string
  resource_ref: string | null
  severity: PrimaryAgentAttentionSeverity
  sequence: number
  state: PrimaryAgentDeliveryState
  attempts: number
  available_at: string
  last_delivery_id: string | null
  last_error: string | null
}

export type PrimaryAgentDelivery = {
  delivery_id: string
  inbox_id: string
  event_id: string
  node_id: string
  slot_id: string
  binding_id: string
  event_type: string
  resource_ref: string | null
  severity: PrimaryAgentAttentionSeverity
  sequence: number
  attempt: number
  payload: unknown
  delivered_at: string
  redaction_profile_ref: string
}

export type PrimaryAgentGrantChangedEvent = {
  event_id: string
  event_type: 'spatial.primary-agent.grant-changed.v1'
  schema_version: typeof SPATIAL_SCHEMA_VERSIONS.primaryAgentGrant
  node_id: string
  sequence: number
  revision: number
  occurred_at: string
  correlation_id: string | null
  causation_id: string | null
  payload: SpatialPrimaryAgentGrant
}

export type PrimaryAgentDeliveryConflictCode =
  | 'NODE_MISMATCH'
  | 'NOT_FOUND'
  | 'UNAUTHORIZED'
  | 'GRANT_REVOKED'
  | 'HOOK_REVOKED'
  | 'ACK_CONFLICT'
  | 'FILTERED'
  | 'VALIDATION'

export class PrimaryAgentDeliveryConflict extends Error {
  readonly code: PrimaryAgentDeliveryConflictCode

  constructor(code: PrimaryAgentDeliveryConflictCode, message: string) {
    super(message)
    this.name = 'PrimaryAgentDeliveryConflict'
    this.code = code
  }
}

export type PrimaryAgentDeliveryServiceOptions = {
  repository: PrimaryAgentSlotRepository
  now?: () => Date
  maxAttempts?: number
  onGrantEvent?: (event: PrimaryAgentGrantChangedEvent) => void
}

type InternalInboxRecord = PrimaryAgentInboxRecord & { payload: unknown }

const severitySchema = z.preprocess((value) => typeof value === 'string' ? value.trim().toUpperCase() : value, z.enum(SPATIAL_PRIMARY_AGENT_ATTENTION_SEVERITIES))

function nowIso(now: Date): string {
  return spatialTimestampSchema.parse(now)
}

function text(value: unknown, label: string): string {
  if (typeof value !== 'string' || value.trim() === '') throw new PrimaryAgentDeliveryConflict('VALIDATION', `${label} is required.`)
  return value.trim()
}

function clone<T>(value: T): T {
  return structuredClone(value)
}

function safeFilter(filter: PrimaryAgentHookFilter | undefined): PrimaryAgentHookFilter {
  return {
    ...(filter?.event_types ? { event_types: filter.event_types.map((value) => text(value, 'event_type')) } : {}),
    ...(filter?.resource_refs ? { resource_refs: filter.resource_refs.map((value) => text(value, 'resource_ref')) } : {}),
    ...(filter?.severities ? { severities: filter.severities.map((value) => severitySchema.parse(value)) } : {}),
  }
}

function matchesFilter(filter: PrimaryAgentHookFilter, event: PrimaryAgentInboxEvent): boolean {
  if (filter.event_types?.length && !filter.event_types.includes(event.event_type)) return false
  if (filter.resource_refs?.length && !filter.resource_refs.includes(event.resource_ref ?? '')) return false
  if (filter.severities?.length && !filter.severities.includes(event.severity ?? 'NONE')) return false
  return true
}

function redactValue(value: unknown, profile: PrimaryAgentRedactionProfile, path = ''): unknown {
  const replacement = profile.replacement ?? '[REDACTED]'
  const keys = new Set(profile.redact_keys.map((key) => key.toLowerCase()))
  const paths = new Set((profile.redact_paths ?? []).map((entry) => entry.toLowerCase()))
  if (paths.has(path.toLowerCase())) return replacement
  if (Array.isArray(value)) return value.map((item, index) => redactValue(item, profile, path ? `${path}.${index}` : String(index)))
  if (!value || typeof value !== 'object') return value
  return Object.fromEntries(Object.entries(value as Record<string, unknown>).map(([key, item]) => {
    const nextPath = path ? `${path}.${key}` : key
    return [key, keys.has(key.toLowerCase()) || paths.has(nextPath.toLowerCase()) ? replacement : redactValue(item, profile, nextPath)]
  }))
}

function publicRecord(record: InternalInboxRecord): PrimaryAgentInboxRecord {
  const { payload: _payload, ...safe } = record
  return clone(safe)
}

export class InMemoryPrimaryAgentDeliveryService {
  private readonly repository: PrimaryAgentSlotRepository
  private readonly now: () => Date
  private readonly maxAttempts: number
  private readonly onGrantEvent?: (event: PrimaryAgentGrantChangedEvent) => void
  private readonly grants = new Map<string, SpatialPrimaryAgentGrant>()
  private readonly subscriptions = new Map<string, PrimaryAgentHookSubscription>()
  private readonly inbox = new Map<string, InternalInboxRecord>()
  private readonly deliveries = new Map<string, PrimaryAgentDelivery>()
  private readonly grantSequences = new Map<string, number>()
  private readonly eventRecords = new Map<string, string>()

  constructor(options: PrimaryAgentDeliveryServiceOptions) {
    this.repository = options.repository
    this.now = options.now ?? (() => new Date())
    this.maxAttempts = Math.max(1, Math.floor(options.maxAttempts ?? 3))
    this.onGrantEvent = options.onGrantEvent
  }

  private async slot(scope: SpatialNodeScope): Promise<SpatialPrimaryAgentSlot> {
    return this.repository.getSlot(normalizeSpatialNodeScope(scope))
  }

  private activeBinding(slot: SpatialPrimaryAgentSlot, bindingId: string): void {
    if (!slot.current_binding_id || slot.current_binding_id !== bindingId) throw new PrimaryAgentDeliveryConflict('UNAUTHORIZED', 'The binding is not the active Primary Agent binding.')
    if (slot.lifecycle_state === 'REVOKED' || slot.lifecycle_state === 'UNASSIGNED') throw new PrimaryAgentDeliveryConflict('UNAUTHORIZED', 'The Primary Agent Slot is not available for delivery.')
  }

  private activeGrant(slot: SpatialPrimaryAgentSlot, bindingId: string): SpatialPrimaryAgentGrant {
    const grantId = slot.capability_grant_ref
    if (!grantId) throw new PrimaryAgentDeliveryConflict('GRANT_REVOKED', 'The active binding has no capability grant.')
    const grant = this.grants.get(grantId)
    if (!grant || grant.binding_id !== bindingId || grant.state !== 'ACTIVE') throw new PrimaryAgentDeliveryConflict('GRANT_REVOKED', 'The capability grant is not active for this binding.')
    if (grant.expires_at && Date.parse(grant.expires_at) <= this.now().getTime()) throw new PrimaryAgentDeliveryConflict('GRANT_REVOKED', 'The capability grant has expired.')
    return grant
  }

  async issueGrant(scope: SpatialNodeScope, input: {
    grant_id: string
    binding_id: string
    categories: readonly PrimaryAgentCapabilityCategory[]
    allowlisted_tools: readonly string[]
    redaction_profile_ref?: string | null
    issued_by: string
    expires_at?: Date | string | null
  }): Promise<{ grant: SpatialPrimaryAgentGrant; event: PrimaryAgentGrantChangedEvent }> {
    const normalizedScope = normalizeSpatialNodeScope(scope)
    const slot = await this.slot(normalizedScope)
    this.activeBinding(slot, input.binding_id)
    const timestamp = nowIso(this.now())
    const candidate = {
      schema_version: SPATIAL_SCHEMA_VERSIONS.primaryAgentGrant,
      grant_id: text(input.grant_id, 'grant_id'),
      node_id: normalizedScope.node_id,
      binding_id: text(input.binding_id, 'binding_id'),
      revision: (this.grants.get(input.grant_id)?.revision ?? 0) + 1,
      categories: [...new Set(input.categories)].map((value) => z.enum(SPATIAL_PRIMARY_AGENT_CAPABILITY_CATEGORIES).parse(value)),
      allowlisted_tools: [...new Set(input.allowlisted_tools)].map((value) => text(value, 'allowlisted_tool')),
      redaction_profile_ref: input.redaction_profile_ref ?? null,
      state: 'ACTIVE' as const,
      issued_at: timestamp,
      issued_by: text(input.issued_by, 'issued_by'),
      expires_at: input.expires_at instanceof Date ? nowIso(input.expires_at) : input.expires_at ?? null,
    }
    const parsed = parseSpatialPrimaryAgentGrant(candidate)
    if (!parsed.ok) throw new PrimaryAgentDeliveryConflict('VALIDATION', 'Capability grant failed the typed contract.')
    this.grants.set(parsed.data.grant_id, clone(parsed.data))
    const sequence = (this.grantSequences.get(normalizedScope.node_id) ?? 0) + 1
    this.grantSequences.set(normalizedScope.node_id, sequence)
    const event: PrimaryAgentGrantChangedEvent = {
      event_id: `${parsed.data.grant_id}:grant:${parsed.data.revision}`,
      event_type: 'spatial.primary-agent.grant-changed.v1',
      schema_version: SPATIAL_SCHEMA_VERSIONS.primaryAgentGrant,
      node_id: normalizedScope.node_id,
      sequence,
      revision: parsed.data.revision,
      occurred_at: timestamp,
      correlation_id: parsed.data.grant_id,
      causation_id: null,
      payload: clone(parsed.data),
    }
    this.onGrantEvent?.(event)
    return { grant: clone(parsed.data), event }
  }

  async revokeGrant(scope: SpatialNodeScope, grantId: string, issuedBy: string): Promise<SpatialPrimaryAgentGrant> {
    const normalizedScope = normalizeSpatialNodeScope(scope)
    const id = text(grantId, 'grant_id')
    const current = this.grants.get(id)
    if (!current || current.node_id !== normalizedScope.node_id) throw new PrimaryAgentDeliveryConflict('NOT_FOUND', 'Capability grant was not found for this Node.')
    const timestamp = nowIso(this.now())
    const next = { ...current, revision: current.revision + 1, state: 'REVOKED' as const, issued_by: text(issuedBy, 'issued_by'), issued_at: timestamp }
    this.grants.set(id, clone(next))
    const sequence = (this.grantSequences.get(normalizedScope.node_id) ?? 0) + 1
    this.grantSequences.set(normalizedScope.node_id, sequence)
    this.onGrantEvent?.({
      event_id: `${next.grant_id}:grant:${next.revision}`,
      event_type: 'spatial.primary-agent.grant-changed.v1',
      schema_version: SPATIAL_SCHEMA_VERSIONS.primaryAgentGrant,
      node_id: normalizedScope.node_id,
      sequence,
      revision: next.revision,
      occurred_at: timestamp,
      correlation_id: next.grant_id,
      causation_id: null,
      payload: clone(next),
    })
    return clone(next)
  }

  getGrant(grantId: string): SpatialPrimaryAgentGrant | null {
    const grant = this.grants.get(text(grantId, 'grant_id'))
    return grant ? clone(grant) : null
  }

  async subscribe(scope: SpatialNodeScope, input: {
    subscription_id: string
    binding_id: string
    filter?: PrimaryAgentHookFilter
    redaction_profile?: PrimaryAgentRedactionProfile
  }): Promise<PrimaryAgentHookSubscription> {
    const normalizedScope = normalizeSpatialNodeScope(scope)
    const slot = await this.slot(normalizedScope)
    this.activeBinding(slot, input.binding_id)
    this.activeGrant(slot, input.binding_id)
    const timestamp = nowIso(this.now())
    const subscription: PrimaryAgentHookSubscription = {
      schema_version: 'spatial.primary-agent-hook.v1',
      subscription_id: text(input.subscription_id, 'subscription_id'),
      node_id: normalizedScope.node_id,
      binding_id: text(input.binding_id, 'binding_id'),
      revision: (this.subscriptions.get(input.subscription_id)?.revision ?? 0) + 1,
      filter: safeFilter(input.filter),
      redaction_profile: input.redaction_profile ?? {
        profile_id: 'redaction-default',
        redact_keys: ['secret', 'token', 'password', 'private_key', 'credential', 'authorization'],
        replacement: '[REDACTED]',
      },
      delivery_cursor: 0,
      state: 'ACTIVE',
      created_at: timestamp,
      updated_at: timestamp,
    }
    this.subscriptions.set(subscription.subscription_id, clone(subscription))
    return clone(subscription)
  }

  async setSubscriptionState(scope: SpatialNodeScope, subscriptionId: string, state: PrimaryAgentHookState): Promise<PrimaryAgentHookSubscription> {
    const normalizedScope = normalizeSpatialNodeScope(scope)
    const id = text(subscriptionId, 'subscription_id')
    const current = this.subscriptions.get(id)
    if (!current || current.node_id !== normalizedScope.node_id) throw new PrimaryAgentDeliveryConflict('NOT_FOUND', 'Hook subscription was not found for this Node.')
    const next = { ...current, state, revision: current.revision + 1, updated_at: nowIso(this.now()) }
    this.subscriptions.set(id, clone(next))
    return clone(next)
  }

  getSubscription(subscriptionId: string): PrimaryAgentHookSubscription | null {
    const subscription = this.subscriptions.get(text(subscriptionId, 'subscription_id'))
    return subscription ? clone(subscription) : null
  }

  onBindingRevoked(bindingId: string): void {
    const id = text(bindingId, 'binding_id')
    for (const [subscriptionId, subscription] of this.subscriptions) {
      if (subscription.binding_id !== id) continue
      this.subscriptions.set(subscriptionId, { ...subscription, state: 'REVOKED', revision: subscription.revision + 1, updated_at: nowIso(this.now()) })
    }
  }

  async publish(scope: SpatialNodeScope, event: PrimaryAgentInboxEvent): Promise<PrimaryAgentInboxRecord> {
    const normalizedScope = normalizeSpatialNodeScope(scope)
    const slot = await this.slot(normalizedScope)
    if (event.node_id !== normalizedScope.node_id) throw new PrimaryAgentDeliveryConflict('NODE_MISMATCH', 'Inbox event belongs to a different Node.')
    const eventId = text(event.event_id, 'event_id')
    const existingId = this.eventRecords.get(`${normalizedScope.node_id}:${eventId}`)
    if (existingId) {
      const existing = this.inbox.get(existingId)
      if (existing) return publicRecord(existing)
    }
    const timestamp = event.occurred_at ? spatialTimestampSchema.parse(event.occurred_at) : nowIso(this.now())
    const inboxId = `${slot.slot_id}:inbox:${eventId}`
    const record: InternalInboxRecord = {
      inbox_id: inboxId,
      event_id: eventId,
      node_id: normalizedScope.node_id,
      slot_id: slot.slot_id,
      // The binding target is captured at enqueue time. A replacement cannot
      // silently inherit an old binding's retained events.
      binding_id: slot.current_binding_id,
      event_type: text(event.event_type, 'event_type'),
      resource_ref: event.resource_ref ?? null,
      severity: severitySchema.parse(event.severity ?? 'NONE'),
      sequence: spatialRevisionSchema.parse(event.sequence),
      state: 'PENDING',
      attempts: 0,
      available_at: timestamp,
      last_delivery_id: null,
      last_error: null,
      payload: clone(event.payload),
    }
    this.inbox.set(inboxId, record)
    this.eventRecords.set(`${normalizedScope.node_id}:${eventId}`, inboxId)
    return publicRecord(record)
  }

  async readInbox(scope: SpatialNodeScope, bindingId: string, limit = 50): Promise<PrimaryAgentDelivery[]> {
    const normalizedScope = normalizeSpatialNodeScope(scope)
    const slot = await this.slot(normalizedScope)
    const id = text(bindingId, 'binding_id')
    this.activeBinding(slot, id)
    const grant = this.activeGrant(slot, id)
    const subscription = [...this.subscriptions.values()].find((candidate) => candidate.node_id === normalizedScope.node_id && candidate.binding_id === id && candidate.state === 'ACTIVE')
    if (!subscription) throw new PrimaryAgentDeliveryConflict('HOOK_REVOKED', 'No active Hook subscription exists for this binding.')
    const deliveries: PrimaryAgentDelivery[] = []
    const now = this.now().getTime()
    const records = [...this.inbox.values()].sort((left, right) => left.sequence - right.sequence)
    for (const record of records) {
      if (deliveries.length >= Math.max(1, limit)) break
      if (record.node_id !== normalizedScope.node_id || record.binding_id !== id || record.state !== 'PENDING') continue
      if (Date.parse(record.available_at) > now) continue
      const event: PrimaryAgentInboxEvent = {
        event_id: record.event_id,
        node_id: record.node_id,
        event_type: record.event_type,
        resource_ref: record.resource_ref,
        severity: record.severity,
        sequence: record.sequence,
        payload: record.payload,
      }
      if (!matchesFilter(subscription.filter, event)) continue
      if (record.attempts >= this.maxAttempts) {
        record.state = 'DEAD_LETTER'
        record.last_error = 'delivery attempts exhausted'
        continue
      }
      record.attempts += 1
      record.state = 'DELIVERED'
      const deliveryId = `${record.inbox_id}:delivery:${record.attempts}`
      record.last_delivery_id = deliveryId
      const delivery: PrimaryAgentDelivery = {
        delivery_id: deliveryId,
        inbox_id: record.inbox_id,
        event_id: record.event_id,
        node_id: record.node_id,
        slot_id: record.slot_id,
        binding_id: id,
        event_type: record.event_type,
        resource_ref: record.resource_ref,
        severity: record.severity,
        sequence: record.sequence,
        attempt: record.attempts,
        payload: clone(redactValue(record.payload, subscription.redaction_profile)),
        delivered_at: nowIso(this.now()),
        redaction_profile_ref: grant.redaction_profile_ref ?? subscription.redaction_profile.profile_id,
      }
      this.deliveries.set(deliveryId, clone(delivery))
      subscription.delivery_cursor = Math.max(subscription.delivery_cursor, record.sequence)
      subscription.updated_at = nowIso(this.now())
      deliveries.push(clone(delivery))
    }
    this.subscriptions.set(subscription.subscription_id, clone(subscription))
    return deliveries
  }

  async acknowledge(scope: SpatialNodeScope, bindingId: string, deliveryId: string): Promise<PrimaryAgentInboxRecord> {
    const normalizedScope = normalizeSpatialNodeScope(scope)
    const slot = await this.slot(normalizedScope)
    const id = text(bindingId, 'binding_id')
    this.activeBinding(slot, id)
    const delivery = this.deliveries.get(text(deliveryId, 'delivery_id'))
    if (!delivery || delivery.node_id !== normalizedScope.node_id) throw new PrimaryAgentDeliveryConflict('NOT_FOUND', 'Inbox delivery was not found for this Node.')
    if (delivery.binding_id !== id) throw new PrimaryAgentDeliveryConflict('ACK_CONFLICT', 'A binding cannot acknowledge another binding inbox delivery.')
    const record = this.inbox.get(delivery.inbox_id)
    if (!record) throw new PrimaryAgentDeliveryConflict('NOT_FOUND', 'Inbox record was not found.')
    if (record.state === 'ACKED') return publicRecord(record)
    if (record.state !== 'DELIVERED') throw new PrimaryAgentDeliveryConflict('ACK_CONFLICT', 'Only a delivered inbox record can be acknowledged.')
    record.state = 'ACKED'
    return publicRecord(record)
  }

  async retry(scope: SpatialNodeScope, bindingId: string, eventId: string): Promise<PrimaryAgentInboxRecord> {
    const normalizedScope = normalizeSpatialNodeScope(scope)
    const slot = await this.slot(normalizedScope)
    const id = text(bindingId, 'binding_id')
    this.activeBinding(slot, id)
    const inboxId = this.eventRecords.get(`${normalizedScope.node_id}:${text(eventId, 'event_id')}`)
    const record = inboxId ? this.inbox.get(inboxId) : undefined
    if (!record || record.binding_id !== id) throw new PrimaryAgentDeliveryConflict('NOT_FOUND', 'Inbox event was not found for this binding.')
    if (record.state === 'ACKED') throw new PrimaryAgentDeliveryConflict('ACK_CONFLICT', 'An acknowledged event cannot be retried.')
    record.state = record.attempts >= this.maxAttempts ? 'DEAD_LETTER' : 'PENDING'
    record.available_at = nowIso(this.now())
    return publicRecord(record)
  }

  async replay(scope: SpatialNodeScope, bindingId: string, eventId: string): Promise<PrimaryAgentInboxRecord> {
    const normalizedScope = normalizeSpatialNodeScope(scope)
    const slot = await this.slot(normalizedScope)
    const id = text(bindingId, 'binding_id')
    this.activeBinding(slot, id)
    const inboxId = this.eventRecords.get(`${normalizedScope.node_id}:${text(eventId, 'event_id')}`)
    const record = inboxId ? this.inbox.get(inboxId) : undefined
    if (!record || record.binding_id !== id) throw new PrimaryAgentDeliveryConflict('NOT_FOUND', 'Inbox event was not found for this binding.')
    record.state = 'PENDING'
    record.attempts = 0
    record.last_error = null
    record.available_at = nowIso(this.now())
    return publicRecord(record)
  }

  listDeadLetters(scope: SpatialNodeScope): PrimaryAgentInboxRecord[] {
    const nodeId = normalizeSpatialNodeScope(scope).node_id
    return [...this.inbox.values()].filter((record) => record.node_id === nodeId && record.state === 'DEAD_LETTER').map(publicRecord)
  }

  getInboxRecord(scope: SpatialNodeScope, eventId: string): PrimaryAgentInboxRecord | null {
    const nodeId = normalizeSpatialNodeScope(scope).node_id
    const inboxId = this.eventRecords.get(`${nodeId}:${text(eventId, 'event_id')}`)
    const record = inboxId ? this.inbox.get(inboxId) : undefined
    return record ? publicRecord(record) : null
  }
}

export const InMemoryPrimaryAgentHookDeliveryService = InMemoryPrimaryAgentDeliveryService
