import {
  SPATIAL_PRIMARY_AGENT_ATTENTION_SEVERITIES,
  SPATIAL_PRIMARY_AGENT_OPERATIONAL_STATES,
  SPATIAL_SCHEMA_VERSIONS,
  parseSpatialPrimaryAgentState,
  spatialIdSchema,
  spatialRevisionSchema,
  spatialTimestampSchema,
  type SpatialPrimaryAgentAttentionSeverity,
  type SpatialPrimaryAgentOperationalState,
  type SpatialPrimaryAgentSlotLifecycleState,
  type SpatialPrimaryAgentState,
} from '@/spatial/contracts'

import { PrimaryAgentSlotConflict } from './primary-agent-slot'
import { normalizeSpatialNodeScope, type SpatialNodeScope } from './scope'

export const PRIMARY_AGENT_OPERATIONAL_STATES = SPATIAL_PRIMARY_AGENT_OPERATIONAL_STATES
export type PrimaryAgentOperationalState = SpatialPrimaryAgentOperationalState
export type PrimaryAgentAttentionSeverity = SpatialPrimaryAgentAttentionSeverity

export type PrimaryAgentStateInputs = {
  lifecycle_state: SpatialPrimaryAgentSlotLifecycleState
  binding_id: string | null
  connectivity?: 'connected' | 'degraded' | 'disconnected' | 'unknown'
  node_health?: 'ONLINE' | 'DEGRADED' | 'OFFLINE' | 'UNKNOWN' | 'STALE' | 'DISCONNECTED'
  health_freshness?: 'FRESH' | 'STALE' | 'PARTIAL' | 'UNKNOWN' | 'UNAVAILABLE'
  health_observed_at?: string | null
  health_max_age_ms?: number
  request_in_flight?: boolean
  tool_action_in_flight?: boolean
  work_in_flight?: boolean
  attention_severity?: PrimaryAgentAttentionSeverity
  source?: string
  last_successful_response_at?: string | null
  last_failed_response_at?: string | null
}

export type PrimaryAgentStateRecord = SpatialPrimaryAgentState

export type PrimaryAgentStateTransition = PrimaryAgentStateRecord & {
  previous_state: PrimaryAgentOperationalState | null
  changed: boolean
}

export type PrimaryAgentStateChangedEvent = {
  event_id: string
  event_type: 'spatial.primary-agent.state-changed.v1'
  schema_version: typeof SPATIAL_SCHEMA_VERSIONS.primaryAgentState
  node_id: string
  sequence: number
  revision: number
  occurred_at: string
  correlation_id: string | null
  causation_id: string | null
  payload: PrimaryAgentStateRecord
}

const attentionRank: Record<PrimaryAgentAttentionSeverity, number> = { NONE: 0, INFO: 1, WARNING: 2, CRITICAL: 3 }

function nowIso(now: Date): string {
  return spatialTimestampSchema.parse(now)
}

function severity(value: PrimaryAgentAttentionSeverity | undefined): PrimaryAgentAttentionSeverity {
  if (!value) return 'NONE'
  if (!SPATIAL_PRIMARY_AGENT_ATTENTION_SEVERITIES.includes(value)) throw new PrimaryAgentSlotConflict('VALIDATION', 'Unknown Primary Agent attention severity.')
  return value
}

function healthIsStale(inputs: PrimaryAgentStateInputs, now: Date): boolean {
  if (inputs.health_freshness === 'STALE' || inputs.health_freshness === 'UNKNOWN' || inputs.health_freshness === 'UNAVAILABLE') return true
  if (inputs.node_health === 'UNKNOWN' || inputs.node_health === 'STALE') return true
  if (!inputs.health_observed_at) return false
  const observed = Date.parse(inputs.health_observed_at)
  if (!Number.isFinite(observed)) return true
  if (inputs.health_max_age_ms === undefined) return false
  return now.getTime() - observed > Math.max(1, inputs.health_max_age_ms)
}

/** Deterministic precedence for the independent operational inputs. */
export function aggregatePrimaryAgentState(inputs: PrimaryAgentStateInputs, now = new Date()): PrimaryAgentOperationalState {
  const attention = severity(inputs.attention_severity)
  if (attention === 'CRITICAL') return 'CRITICAL'

  const offline = !inputs.binding_id
    || inputs.lifecycle_state === 'UNASSIGNED'
    || inputs.lifecycle_state === 'REVOKED'
    || inputs.lifecycle_state === 'DISCONNECTED'
    || inputs.connectivity === 'disconnected'
    || inputs.node_health === 'OFFLINE'
    || inputs.node_health === 'DISCONNECTED'
    || healthIsStale(inputs, now)
  if (offline) return 'OFFLINE'
  if (attentionRank[attention] > 0) return 'ATTENTION'
  if (inputs.tool_action_in_flight) return 'ACTING'
  if (inputs.request_in_flight) return 'THINKING'
  if (inputs.work_in_flight || inputs.lifecycle_state === 'BINDING') return 'WORKING'
  if (inputs.connectivity === 'degraded' || inputs.node_health === 'DEGRADED') return 'LISTENING'
  return 'READY'
}

export function createPrimaryAgentStateRecord(
  scope: SpatialNodeScope,
  slot: { slot_id: string; node_id: string; current_binding_id: string | null; lifecycle_state: SpatialPrimaryAgentSlotLifecycleState },
  inputs: PrimaryAgentStateInputs,
  options: { revision?: number; now?: Date } = {},
): PrimaryAgentStateRecord {
  const normalizedScope = normalizeSpatialNodeScope(scope)
  if (slot.node_id !== normalizedScope.node_id) throw new PrimaryAgentSlotConflict('NODE_MISMATCH', 'Primary Agent state belongs to a different Node.')
  const observedAt = nowIso(options.now ?? new Date())
  const candidate = {
    schema_version: SPATIAL_SCHEMA_VERSIONS.primaryAgentState,
    node_id: normalizedScope.node_id,
    slot_id: spatialIdSchema.parse(slot.slot_id),
    binding_id: slot.current_binding_id,
    state: aggregatePrimaryAgentState(inputs, options.now ?? new Date()),
    attention_severity: severity(inputs.attention_severity),
    source: spatialIdSchema.parse(inputs.source ?? 'primary-agent-state-aggregator'),
    revision: spatialRevisionSchema.parse(options.revision ?? 1),
    observed_at: observedAt,
    last_successful_response_at: inputs.last_successful_response_at ?? null,
    last_failed_response_at: inputs.last_failed_response_at ?? null,
  }
  const parsed = parseSpatialPrimaryAgentState(candidate)
  if (!parsed.ok) throw new PrimaryAgentSlotConflict('VALIDATION', 'Primary Agent operational state failed the typed contract.')
  return parsed.data
}

export class PrimaryAgentStateAggregator {
  private current: PrimaryAgentStateRecord | null = null
  private readonly scope: SpatialNodeScope
  private readonly now: () => Date

  constructor(scope: SpatialNodeScope, options: { now?: () => Date; initial?: PrimaryAgentStateRecord } = {}) {
    this.scope = normalizeSpatialNodeScope(scope)
    this.now = options.now ?? (() => new Date())
    if (options.initial) {
      const parsed = parseSpatialPrimaryAgentState(options.initial)
      if (!parsed.ok) throw new PrimaryAgentSlotConflict('VALIDATION', 'Initial Primary Agent state is invalid.')
      if (parsed.data.node_id !== this.scope.node_id) throw new PrimaryAgentSlotConflict('NODE_MISMATCH', 'Initial Primary Agent state belongs to another Node.')
      this.current = parsed.data
    }
  }

  update(slot: { slot_id: string; node_id: string; current_binding_id: string | null; lifecycle_state: SpatialPrimaryAgentSlotLifecycleState }, inputs: Omit<PrimaryAgentStateInputs, 'source'> & { source?: string }): PrimaryAgentStateTransition {
    const nextState = aggregatePrimaryAgentState(inputs, this.now())
    const previous = this.current
    const next = createPrimaryAgentStateRecord(this.scope, slot, inputs, { revision: (previous?.revision ?? 0) + 1, now: this.now() })
    this.current = next
    return { ...next, previous_state: previous?.state ?? null, changed: previous?.state !== nextState || previous?.attention_severity !== next.attention_severity }
  }

  ingest(record: unknown): PrimaryAgentStateRecord {
    const parsed = parseSpatialPrimaryAgentState(record)
    if (!parsed.ok) throw new PrimaryAgentSlotConflict('VALIDATION', 'Primary Agent state event failed the typed contract.')
    if (parsed.data.node_id !== this.scope.node_id) throw new PrimaryAgentSlotConflict('NODE_MISMATCH', 'Primary Agent state event belongs to another Node.')
    if (this.current && parsed.data.revision < this.current.revision) throw new PrimaryAgentSlotConflict('STALE_REVISION', 'Primary Agent state revision is stale.')
    this.current = parsed.data
    return structuredClone(parsed.data)
  }

  snapshot(): PrimaryAgentStateRecord | null {
    return this.current ? structuredClone(this.current) : null
  }

  event(record: PrimaryAgentStateRecord, sequence = record.revision): PrimaryAgentStateChangedEvent {
    return {
      event_id: `${record.slot_id}:state:${record.revision}`,
      event_type: 'spatial.primary-agent.state-changed.v1',
      schema_version: SPATIAL_SCHEMA_VERSIONS.primaryAgentState,
      node_id: record.node_id,
      sequence,
      revision: record.revision,
      occurred_at: record.observed_at,
      correlation_id: record.slot_id,
      causation_id: null,
      payload: structuredClone(record),
    }
  }
}

export const primaryAgentStateSeverityRank = attentionRank
