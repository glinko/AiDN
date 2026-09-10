import { describe, expect, it } from 'vitest'

import { dashboardSchemas, type EndpointPayload, type Fleet, type SessionDashboard } from '@/lib/types'
import {
  createDashboardSpatialScene,
  createDashboardSpatialSnapshotForPayload,
} from '@/spatial/data'

const scope = { hypervisor_id: 'local-hypervisor', node_id: 'gpu-3090' } as const

function fixturePayload() {
  const fleet = dashboardSchemas.fleet.parse({
    node: { node_id: 'gpu-3090' },
    resources: {
      total: { cpu: 8, ram_mb: 32000, vram_mb: 24000 },
      reserved: { cpu: 1, ram_mb: 2048, vram_mb: 10000 },
      free: { cpu: 7, ram_mb: 29952, vram_mb: 14000 },
    },
    queue: { queued: 0, active: 1, completed: 12, failed: 0 },
    bundles: [{ bundle_id: 'bundle-qwen', revision: 4, model_id: 'Qwen3.8', enabled: true, registry_status: 'ready' }],
  }) as Fleet
  const endpoints = dashboardSchemas.endpoints.parse({
    summary: { total: 2, published: 1, configured: 1, validation_requested: 0, private: 1, shared: 0, public: 1 },
    items: [
      { endpoint_id: 'ep-chat', display_name: 'Qwen Chat', model_class: 'llm.chat', capabilities: ['llm.chat'], publication_status: 'published', runtime_status: 'created', publication_ready: true, local_agent_use: true },
      { endpoint_id: 'ep-speech', display_name: 'Speech', model_class: 'speech.stt', capabilities: ['speech.stt'], publication_status: 'configured', runtime_status: 'created', publication_ready: true, local_agent_use: false },
    ],
  }) as EndpointPayload
  const sessions = dashboardSchemas.sessions.parse({
    summary: { total: 2, active: 1, queued: 0, closed: 1, terminal: 1 },
    items: [
      { session: { session_id: 'sess-active', endpoint_id: 'ep-chat', client_wallet: 'wallet-a', provider_wallet: 'wallet-b', status: 'active' }, display_name: 'Active chat' },
      { session: { session_id: 'sess-closed', endpoint_id: 'ep-speech', client_wallet: 'wallet-c', provider_wallet: 'wallet-b', status: 'closed' }, display_name: 'Closed speech' },
    ],
  }) as SessionDashboard
  const residentAgent = dashboardSchemas.residentAgent.parse({ node_id: 'gpu-3090', state: 'READY', health: 'READY', enabled: true })
  return { fleet, endpoints, sessions, residentAgent }
}

describe('production dashboard → Spatial adapter', () => {
  it('normalizes endpoint, session and bundle records while preserving the dedicated primary agent', () => {
    const result = createDashboardSpatialSnapshotForPayload(fixturePayload(), scope, new Date('2026-09-10T12:00:00.000Z'))
    expect(result.snapshot.node_id).toBe('gpu-3090')
    expect(result.snapshot.primary_agent_ref).toBe('agent:primary-agent-gpu-3090')
    expect(result.snapshot.entities.filter((entity) => entity.kind === 'endpoint')).toHaveLength(2)
    expect(result.snapshot.entities.filter((entity) => entity.kind === 'session')).toHaveLength(2)
    expect(result.snapshot.entities.filter((entity) => entity.kind === 'artifact')).toHaveLength(1)
    expect(result.scene.source).toMatchObject({ nodeId: 'gpu-3090', endpointCount: 2, sessionCount: 2, bundleCount: 1, subagentCount: 0 })
    expect(result.scene.config.agents).toHaveLength(0)
    expect(result.scene.endpoints.map((endpoint) => endpoint.id)).toEqual(['ep-chat', 'ep-speech'])
  })

  it('keeps presentation positions deterministic and renders the primary-to-node threads', () => {
    const payload = fixturePayload()
    const first = createDashboardSpatialSnapshotForPayload(payload, scope, new Date('2026-09-10T12:00:00.000Z')).scene
    const second = createDashboardSpatialSnapshotForPayload(payload, scope, new Date('2026-09-10T12:00:00.000Z')).scene
    expect(first.config).toEqual(second.config)
    expect(first.config.connections.length).toBeGreaterThanOrEqual(2)
    expect(first.config.connections.every((connection) => connection.sourceId === 'primary-agent-gpu-3090' || connection.sourceId.startsWith('primary-agent-gpu-3090'))).toBe(true)
  })

  it('can rebuild the scene from an already parsed canonical snapshot without inventing subagents', () => {
    const { snapshot, status } = createDashboardSpatialSnapshotForPayload(fixturePayload(), scope, new Date('2026-09-10T12:00:00.000Z'))
    const scene = createDashboardSpatialScene(snapshot, status)
    expect(scene.source.nodeId).toBe(scope.node_id)
    expect(scene.source.subagentCount).toBe(0)
    expect(scene.projection.primaryAgent?.canonicalRef).toBe(snapshot.primary_agent_ref)
  })
})
