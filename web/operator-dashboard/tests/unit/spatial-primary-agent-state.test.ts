import { describe, expect, it } from 'vitest'

import {
  PRIMARY_AGENT_OPERATIONAL_STATES,
  PrimaryAgentStateAggregator,
  aggregatePrimaryAgentState,
  createPrimaryAgentStateRecord,
  type PrimaryAgentStateInputs,
} from '@/spatial/data'
import { MOCK_SPATIAL_SCOPE } from '@/spatial/data'
import { createPrimaryAgentSlot } from '@/spatial/data'

const slot = createPrimaryAgentSlot(MOCK_SPATIAL_SCOPE, { now: new Date('2026-09-05T16:00:00.000Z') })
const connectedSlot = { ...slot, lifecycle_state: 'CONNECTED' as const, current_binding_id: 'binding-state' }
const base: PrimaryAgentStateInputs = { lifecycle_state: 'CONNECTED', binding_id: 'binding-state', node_health: 'ONLINE', health_freshness: 'FRESH', health_observed_at: '2026-09-05T16:00:00.000Z' }

describe('Spatial M3.4 Primary Agent operational state aggregator', () => {
  it('exposes the canonical output vocabulary and resolves conflicting inputs deterministically', () => {
    expect(PRIMARY_AGENT_OPERATIONAL_STATES).toEqual(['READY', 'LISTENING', 'THINKING', 'ACTING', 'WORKING', 'ATTENTION', 'CRITICAL', 'OFFLINE'])
    expect(aggregatePrimaryAgentState(base)).toBe('READY')
    expect(aggregatePrimaryAgentState({ ...base, connectivity: 'degraded' })).toBe('LISTENING')
    expect(aggregatePrimaryAgentState({ ...base, request_in_flight: true })).toBe('THINKING')
    expect(aggregatePrimaryAgentState({ ...base, tool_action_in_flight: true })).toBe('ACTING')
    expect(aggregatePrimaryAgentState({ ...base, work_in_flight: true })).toBe('WORKING')
    expect(aggregatePrimaryAgentState({ ...base, request_in_flight: true, attention_severity: 'WARNING' })).toBe('ATTENTION')
    expect(aggregatePrimaryAgentState({ ...base, request_in_flight: true, attention_severity: 'CRITICAL' })).toBe('CRITICAL')
  })

  it('treats stale health as offline instead of inferring online from a response', () => {
    expect(aggregatePrimaryAgentState({ ...base, health_freshness: 'STALE' })).toBe('OFFLINE')
    expect(aggregatePrimaryAgentState({ ...base, health_observed_at: '2026-09-05T15:00:00.000Z', health_max_age_ms: 30_000 }, new Date('2026-09-05T16:00:00.000Z'))).toBe('OFFLINE')
    expect(aggregatePrimaryAgentState({ ...base, node_health: 'UNKNOWN' })).toBe('OFFLINE')
  })

  it('keeps attention independent while a disconnect during action remains visible as offline', () => {
    expect(aggregatePrimaryAgentState({ ...base, lifecycle_state: 'DISCONNECTED', tool_action_in_flight: true })).toBe('OFFLINE')
    expect(aggregatePrimaryAgentState({ ...base, lifecycle_state: 'DISCONNECTED', tool_action_in_flight: true, attention_severity: 'CRITICAL' })).toBe('CRITICAL')
  })

  it('records timestamp/source/revision for rapid transitions and recovers safely', () => {
    const aggregator = new PrimaryAgentStateAggregator(MOCK_SPATIAL_SCOPE, { now: () => new Date('2026-09-05T16:01:00.000Z') })
    const thinking = aggregator.update(connectedSlot, { ...base, request_in_flight: true, source: 'request.lifecycle' })
    const ready = aggregator.update(connectedSlot, { ...base, source: 'request.lifecycle' })
    expect(thinking).toMatchObject({ state: 'THINKING', previous_state: null, changed: true, revision: 1, source: 'request.lifecycle' })
    expect(ready).toMatchObject({ state: 'READY', previous_state: 'THINKING', changed: true, revision: 2 })
    expect(aggregator.event(ready).event_type).toBe('spatial.primary-agent.state-changed.v1')
    expect(aggregator.snapshot()).toMatchObject({ state: 'READY', revision: 2 })
  })

  it('rejects Node-mismatched records and stale recovery input', () => {
    expect(() => createPrimaryAgentStateRecord({ hypervisor_id: 'h', node_id: 'other' }, connectedSlot, base)).toThrowError()
    const aggregator = new PrimaryAgentStateAggregator(MOCK_SPATIAL_SCOPE)
    const record = createPrimaryAgentStateRecord(MOCK_SPATIAL_SCOPE, connectedSlot, base)
    aggregator.ingest(record)
    expect(() => aggregator.ingest({ ...record, revision: 0 })).toThrowError()
  })
})
