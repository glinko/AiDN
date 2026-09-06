import { describe, expect, it } from 'vitest'

import {
  composeSpatialWorkspaceViewModel,
  createMockSpatialNodeStatus,
  createMockSpatialWorkspaceSnapshot,
  toSpatialEntityViewModel,
  toPrimaryAgentViewModel,
  toSpatialNodeStatusViewModel,
} from '@/spatial/data'
import { parseSpatialEntity, type SpatialAgentEntity } from '@/spatial/contracts'

describe('Spatial M2.4 view-model layer', () => {
  it('composes the same canonical input deterministically and deduplicates primary presence', () => {
    const snapshot = createMockSpatialWorkspaceSnapshot()
    const status = createMockSpatialNodeStatus()
    const first = composeSpatialWorkspaceViewModel(snapshot, status, 'desktop')
    const second = composeSpatialWorkspaceViewModel(snapshot, status, 'desktop')
    expect(first).toEqual(second)
    expect(first.entities.length).toBe(snapshot.entities.length - 1)
    expect(first.primaryAgent?.canonicalRef).toBe(snapshot.primary_agent_ref)
    expect(first.entities.some((entity) => entity.canonicalRef === snapshot.primary_agent_ref)).toBe(false)
  })

  it('keeps missing evidence unknown rather than inferring healthy/online', () => {
    const snapshot = createMockSpatialWorkspaceSnapshot()
    const endpoint = snapshot.entities.find((entity) => entity.kind === 'endpoint')
    expect(endpoint).toBeTruthy()
    if (!endpoint) return
    const parsed = parseSpatialEntity({ ...endpoint, availability: 'UNKNOWN', freshness: { ...endpoint.freshness, state: 'UNKNOWN' } })
    expect(parsed.ok).toBe(true)
    if (!parsed.ok) return
    const model = toSpatialEntityViewModel(parsed.data)
    expect(model.visualState).toBe('unknown')
    expect(model.lodHint).toBe('placeholder')
    expect(model.freshnessLabel).toBe('Freshness unknown')
  })

  it('keeps provenance, source revision, familiarity, and safe display fields explicit', () => {
    const snapshot = createMockSpatialWorkspaceSnapshot()
    const entity = snapshot.entities.find((candidate) => candidate.kind === 'artifact')
    expect(entity).toBeTruthy()
    if (!entity) return
    const model = toSpatialEntityViewModel(entity)
    expect(model.sourceRevision).toBe(entity.revision)
    expect(model.provenanceRef).toBe(entity.provenance_ref)
    expect(model.familiarity).toBe('unseen')
    expect(model.description).toContain('Artifact')
    expect(JSON.stringify(model)).not.toMatch(/private|token|secret|config/i)
  })

  it('maps the Primary Agent slot without coupling it to reputation/familiarity', () => {
    const snapshot = createMockSpatialWorkspaceSnapshot()
    const primary = snapshot.entities.find((entity): entity is SpatialAgentEntity => entity.kind === 'agent' && entity.canonical_ref === snapshot.primary_agent_ref)
    expect(primary).toBeTruthy()
    if (!primary) return
    const model = toPrimaryAgentViewModel(primary, 'desktop')
    expect(model.state).toBe('READY')
    expect(model.canonicalRef).toBe(snapshot.primary_agent_ref)
    expect(model.lodHint).toBe('full')
  })

  it('projects Node status freshness and component evidence explicitly', () => {
    const status = createMockSpatialNodeStatus()
    const model = toSpatialNodeStatusViewModel(status)
    expect(model.nodeId).toBe(status.node_id)
    expect(model.availability).toBe('available')
    expect(model.componentCount).toBe(status.components.length)
    expect(model.freshnessLabel).toBe('Fresh evidence')
  })
})
