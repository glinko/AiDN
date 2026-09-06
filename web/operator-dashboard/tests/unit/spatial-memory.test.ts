import { describe, expect, it } from 'vitest'

import {
  SpatialMemoryEngine,
  createSpatialMemoryRecord,
  type MemoryCamera,
  type SpatialMemoryRecord,
} from '@/spatial/memory'
import {
  parseSpatialMemoryCluster,
  parseSpatialMemoryFocus,
  parseSpatialMemoryLayout,
  parseSpatialMemoryProjection,
  parseSpatialMemorySearch,
  parseSpatialMemoryVirtualization,
  SPATIAL_SCHEMA_VERSIONS,
} from '@/spatial/contracts'
import { parseSpatialEventEnvelope } from '@/spatial/data/events'

const NOW = new Date('2026-09-05T00:00:00.000Z')
const scope = { workspaceId: 'workspace-memory', primaryAgentRef: 'agent:primary', now: NOW, seed: 'm8-test-seed', visibleRecentBudget: 5, renderBudget: 30, cullRadius: 12 }

function record(ref: string, overrides: Partial<SpatialMemoryRecord> = {}): SpatialMemoryRecord {
  return {
    semanticRef: ref,
    objectType: overrides.objectType ?? 'artifact',
    label: overrides.label ?? ref.replace(':', ' '),
    summary: overrides.summary ?? `Summary for ${ref}`,
    createdAt: overrides.createdAt ?? NOW,
    lastActiveAt: overrides.lastActiveAt ?? NOW,
    ...overrides,
  }
}

function camera(): MemoryCamera {
  return { x: 1, y: 2, zoom: 1.2, focusRef: null }
}

describe('M8.1 preferred regions and deterministic layout', () => {
  it('keeps semantic anchors stable, avoids collisions, and preserves manual positions across reflow', () => {
    const engine = new SpatialMemoryEngine(scope, [
      record('agent:research', { objectType: 'agent' }),
      record('endpoint:debug', { objectType: 'endpoint' }),
      record('artifact:recent'),
    ])
    const firstLayout = engine.layout()
    expect(firstLayout.primary_agent_ref).toBe('agent:primary')
    expect(firstLayout.anchors.map((anchor) => anchor.region)).toEqual(['ACTIVE_WORK', 'AGENT_SPACE', 'RECENT_MEMORY', 'CLUSTER_MEMORY', 'ENDPOINT_ARC', 'DEEP_MEMORY'])
    const moved = engine.move('artifact:recent', { x: 9, y: 4, z: -2 })
    expect(moved.manual_position_override).toBe(true)
    const afterMove = engine.upsert(record('endpoint:debug', { objectType: 'endpoint', lastActiveAt: NOW }))
    expect(afterMove.semantic_ref.canonical_ref).toBe('endpoint:debug')
    expect(engine.projection('artifact:recent')?.world_position).toEqual({ x: 9, y: 4, z: -2 })
    expect(engine.resetLayout().presentation_revision).toBeGreaterThan(firstLayout.presentation_revision)
    expect(engine.projection('artifact:recent')?.manual_position_override).toBe(false)
  })
})

describe('M8.2 recent memory budget', () => {
  it('bounds fresh artifacts while keeping explicitly pinned items visible', () => {
    const recent = Array.from({ length: 12 }, (_, index) => record(`artifact:recent-${index}`, { lastActiveAt: new Date(NOW.getTime() - index * 60_000) }))
    const engine = new SpatialMemoryEngine(scope, [...recent, record('artifact:pinned', { pinned: true, lastActiveAt: new Date(NOW.getTime() - 99 * DAY_MS) })])
    expect(engine.visibleRecent()).toHaveLength(6)
    expect(engine.visibleRecent()[0]?.semantic_ref.canonical_ref).toBe('artifact:recent-0')
    expect(engine.visibleRecent().some((item) => item.semantic_ref.canonical_ref === 'artifact:pinned')).toBe(true)
    expect(engine.projection('artifact:recent-11')?.render_state).toBe('VIRTUALIZED')
  })
})

const DAY_MS = 86_400_000

describe('M8.3 deterministic aging and hysteresis', () => {
  it('ages by UTC inactivity, keeps unresolved/pinned items near, and reuses history without deletion', () => {
    const engine = new SpatialMemoryEngine(scope, [
      record('artifact:old', { lastActiveAt: new Date(NOW.getTime() - 40 * DAY_MS) }),
      record('artifact:unresolved', { lastActiveAt: new Date(NOW.getTime() - 40 * DAY_MS), unresolved: true }),
      record('artifact:reused', { lastActiveAt: new Date(NOW.getTime() - 40 * DAY_MS), lastReusedAt: new Date(NOW.getTime() - 40 * DAY_MS) }),
    ])
    expect(engine.projection('artifact:old')?.memory_level).toBe('VIRTUALIZED')
    expect(engine.projection('artifact:unresolved')?.memory_level).toBe('RECENT')
    expect(engine.reuse('artifact:reused', NOW).memory_level).toBe('RECENT')
    expect(engine.recordCount).toBe(3)
    expect(engine.policyRevision).toBe('m8-policy-1')
  })
})

describe('M8.4 session cluster promotion', () => {
  it('promotes structural/topic evidence, is idempotent, and keeps stale members explicit', () => {
    const engine = new SpatialMemoryEngine(scope, [
      record('artifact:a', { metadata: { project: 'AiDN', topic: 'debug' } }),
      record('artifact:b', { metadata: { project: 'AiDN', topic: 'debug' }, stale: true }),
      record('artifact:c', { metadata: { project: 'Other' } }),
    ])
    const clusters = engine.clusters()
    expect(clusters).toHaveLength(1)
    expect(clusters[0]?.criterion).toBe('PROJECT')
    expect(clusters[0]?.evidence).toContain('shared project')
    expect(clusters[0]?.stale_member_refs).toHaveLength(1)
    expect(engine.clusters()).toHaveLength(1)
    const manual = engine.createManualCluster({ id: 'manual-debug', title: 'Debug branch', memberRefs: ['artifact:a', 'artifact:c'] })
    expect(manual.criterion).toBe('MANUAL')
    expect(engine.removeClusterMember('manual-debug', 'artifact:c')?.member_refs.map((ref) => ref.canonical_ref)).toEqual(['artifact:a'])
  })
})

describe('M8.5 relation reveal', () => {
  it('reveals bounded accessible relation labels without mutating projections', () => {
    const engine = new SpatialMemoryEngine(scope, [record('artifact:a', { label: 'A' }), record('artifact:b', { label: 'B', lastActiveAt: new Date(NOW.getTime() - 40 * DAY_MS) })])
    const before = engine.projection('artifact:b')?.world_position
    const revealed = engine.revealRelations('artifact:a', [{ id: 'relation-1', sourceRef: 'artifact:b', targetRef: 'artifact:a', type: 'CONTINUES_FROM' }])
    expect(revealed[0]?.accessibleText).toBe('continues from: B to A')
    expect(revealed[0]?.targetOffscreen).toBe(false)
    expect(engine.projection('artifact:b')?.world_position).toEqual(before)
  })
})

describe('M8.6 Pull-to-Focus', () => {
  it('walks requested/materializing/focused/returning, preserves world position, and exposes unavailable references', () => {
    const engine = new SpatialMemoryEngine(scope, [record('artifact:deep', { lastActiveAt: new Date(NOW.getTime() - 60 * DAY_MS) }), record('artifact:gone', { available: false, unavailableReason: 'tombstone' })])
    const worldPosition = engine.projection('artifact:deep')!.world_position
    expect(engine.requestFocus('artifact:deep', { camera: camera(), source: 'SEARCH' }).state).toBe('REQUESTED')
    expect(engine.materializeFocus().state).toBe('MATERIALIZING')
    expect(engine.completeFocus().state).toBe('FOCUSED')
    expect(engine.focus()?.world_position).toEqual(worldPosition)
    expect(engine.pinFocus()?.state).toBe('PINNED')
    expect(engine.returnFromFocus()?.state).toBe('RETURNING')
    expect(engine.requestFocus('artifact:gone', { camera: camera() }).state).toBe('UNAVAILABLE')
    expect(engine.focus()?.unavailable_reason).toBe('tombstone')
  })
})

describe('M8.7 virtualization and LOD', () => {
  it('keeps 20k history bounded and releases materialized memory deterministically', () => {
    const records = Array.from({ length: 20_000 }, (_, index) => record(`artifact:${index}`, {
      label: `History ${index}`,
      createdAt: new Date(NOW.getTime() - (index % 90) * DAY_MS),
      lastActiveAt: new Date(NOW.getTime() - (index % 90) * DAY_MS),
      relevanceScore: index % 100 / 100,
      metadata: { project: index % 5 === 0 ? 'AiDN' : 'other' },
    }))
    const engine = new SpatialMemoryEngine({ ...scope, renderBudget: 30 }, records)
    const virtualization = engine.planVirtualization({ x: 0, y: 0, radius: 12, revision: 7 })
    expect(virtualization.total_count).toBe(20_000)
    expect(virtualization.materialized_count).toBeLessThanOrEqual(30)
    expect(virtualization.render_budget).toBe(30)
    const ref = 'artifact:42'
    expect(engine.materialize(ref, 3).lod).toBe(3)
    expect(engine.releaseMaterialization(ref).render_state).toBe('VIRTUALIZED')
    expect(engine.telemetrySnapshot().memoryReleased).toBe(true)
  })
})

describe('M8.8 metadata search and contract evidence', () => {
  it('returns canonical references with evidence and excludes unauthorized records', () => {
    const engine = new SpatialMemoryEngine(scope, [
      record('session:endpoint-debug', { objectType: 'session', label: 'Yesterday Endpoint debugging', metadata: { project: 'AiDN', endpointRef: 'endpoint:debug' }, sourceRevision: 4 }),
      record('artifact:endpoint-debug-branch', { label: 'Debug branch', metadata: { project: 'AiDN' } }),
      record('session:secret', { label: 'Endpoint debugging private', authorized: false }),
      record('artifact:stale', { label: 'Yesterday Endpoint debugging stale', stale: true }),
    ])
    const result = engine.search('yesterday endpoint debugging')
    expect(result.results.map((item) => item.result_ref.canonical_ref)).toContain('session:endpoint-debug')
    expect(result.results.map((item) => item.result_ref.canonical_ref)).toContain('artifact:stale')
    expect(result.results[0]?.evidence.length).toBeGreaterThan(0)
    expect(result.results.some((item) => item.result_ref.canonical_ref === 'session:secret')).toBe(false)
    const contracts = engine.contractSnapshot()
    expect(parseSpatialMemoryLayout(contracts.layout).ok).toBe(true)
    expect(parseSpatialMemoryProjection(contracts.projections[0]).ok).toBe(true)
    expect(parseSpatialMemoryCluster(contracts.clusters[0]).ok).toBe(true)
    expect(parseSpatialMemorySearch(result).ok).toBe(true)
    expect(parseSpatialMemoryVirtualization(contracts.telemetry).ok).toBe(true)
    expect(parseSpatialMemoryFocus(contracts.focus).ok).toBe(false)
    const event = parseSpatialEventEnvelope({
      event_id: 'memory-projection-event',
      event_type: 'spatial.memory.projection-updated.v1',
      schema_version: SPATIAL_SCHEMA_VERSIONS.memoryProjection,
      node_id: 'node-memory',
      sequence: 1,
      revision: 1,
      occurred_at: NOW.toISOString(),
      correlation_id: null,
      causation_id: null,
      payload: contracts.projections[0],
    })
    expect(event.ok).toBe(true)
    expect(createSpatialMemoryRecord(record('artifact:copy'))).not.toBe(engine.record('artifact:copy'))
  })
})
