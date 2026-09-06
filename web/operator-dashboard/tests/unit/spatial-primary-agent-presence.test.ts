import { describe, expect, it } from 'vitest'

import {
  composePrimaryAgentPresence,
  createPrimaryAgentSlot,
  primaryAgentMaterialProfile,
  type PrimaryAgentStateRecord,
} from '@/spatial/data'
import { MOCK_SPATIAL_SCOPE } from '@/spatial/data'

const slot = createPrimaryAgentSlot(MOCK_SPATIAL_SCOPE, { now: new Date('2026-09-05T16:00:00.000Z') })
const state: PrimaryAgentStateRecord = {
  schema_version: 'spatial.primary-agent-state.v1',
  node_id: MOCK_SPATIAL_SCOPE.node_id,
  slot_id: slot.slot_id,
  binding_id: null,
  state: 'THINKING',
  attention_severity: 'CRITICAL',
  source: 'fixture.state',
  revision: 3,
  observed_at: '2026-09-05T16:00:00.000Z',
  last_successful_response_at: '2026-09-05T15:59:00.000Z',
  last_failed_response_at: null,
}

describe('Spatial M3.5 live Primary Agent Presence view model', () => {
  it('keeps operational state, attention overlay and slot lifecycle independent', () => {
    const presence = composePrimaryAgentPresence(slot, 'THINKING', { operationalState: state })
    expect(presence).toMatchObject({ state: 'THINKING', lifecycleState: 'UNASSIGNED', bindingId: null, sourceRevision: 3 })
    expect(presence.attention).toMatchObject({ visible: true, severity: 'CRITICAL', pulse: 'urgent' })
    expect(presence.accessibleLabel).toContain('Thinking')
    expect(presence.lastSeenLabel).toContain('Last seen')
  })

  it('falls back quality and reduced motion without renaming semantic state', () => {
    const low = primaryAgentMaterialProfile('ACTING', 'mobile', true, { ACTING: { accentColor: '#123456' } })
    expect(low).toMatchObject({ state: 'ACTING', accentColor: '#123456', pulse: 'static', lod: 'simple' })
    expect(low.bodyColor).toBeTruthy()
  })

  it('keeps offline Presence visible and interaction recoverable after revoke', () => {
    const revoked = { ...slot, lifecycle_state: 'REVOKED' as const, revision: 4 }
    const presence = composePrimaryAgentPresence(revoked, 'OFFLINE')
    expect(presence).toMatchObject({ state: 'OFFLINE', canInteract: false, lifecycleState: 'REVOKED' })
    expect(presence.material.lod).toBe('simple')
    expect(presence.material.pulse).toBe('static')
  })
})
