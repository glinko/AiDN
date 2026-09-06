import { describe, expect, it, vi } from 'vitest'

import {
  createFetchSpatialTransport,
  createReconnectingSpatialEventStreamAdapter,
  createSpatialDomainClients,
  spatialInvalidationKeys,
  spatialQueryKeys,
  type SpatialNodeScope,
} from '@/spatial/data'
import {
  MOCK_SPATIAL_SCOPE,
  mockSpatialEventStream,
  mockSpatialNodeStatusPayload,
  createMockSpatialWorkspaceSnapshot,
} from '@/spatial/data'
import { SpatialEventGateway, spatialReconnectDelay } from '@/spatial/data'

const OTHER_SCOPE: SpatialNodeScope = { hypervisor_id: 'hypervisor-two', node_id: 'node-two' }

describe('Spatial M2.2 domain clients and query keys', () => {
  it('scopes every query key to the active Hypervisor and Node', () => {
    expect(spatialQueryKeys.workspace(MOCK_SPATIAL_SCOPE)).toEqual(['spatial', 'local-hypervisor', 'local-node', 'workspace'])
    expect(spatialQueryKeys.workspace(MOCK_SPATIAL_SCOPE)).not.toEqual(spatialQueryKeys.workspace(OTHER_SCOPE))
    expect(spatialQueryKeys.events(MOCK_SPATIAL_SCOPE, '42')).toContain('42')
    expect(spatialQueryKeys.primaryAgentSlot(MOCK_SPATIAL_SCOPE)).toEqual(['spatial', 'local-hypervisor', 'local-node', 'primary-agent-slot'])
    expect(spatialInvalidationKeys(MOCK_SPATIAL_SCOPE, 'primary-agent-slot')).toEqual([
      spatialQueryKeys.primaryAgentSlot(MOCK_SPATIAL_SCOPE),
      spatialQueryKeys.agents(MOCK_SPATIAL_SCOPE),
    ])
    expect(spatialInvalidationKeys(MOCK_SPATIAL_SCOPE, 'status')).toEqual([spatialQueryKeys.nodeStatus(MOCK_SPATIAL_SCOPE)])
    expect(spatialInvalidationKeys(MOCK_SPATIAL_SCOPE, 'workspace-presentation')).toEqual([spatialQueryKeys.workspacePresentation(MOCK_SPATIAL_SCOPE)])
  })

  it.each([
    [401, 'unauthorized'],
    [403, 'forbidden'],
    [409, 'conflict'],
    [422, 'validation'],
  ] as const)('maps HTTP %s to a typed error category', async (status, category) => {
    const transport = createFetchSpatialTransport({
      fetcher: vi.fn(async () => new Response(JSON.stringify({ detail: 'safe detail' }), { status })),
    })
    await expect(transport.request({ path: '/operators/spatial/workspace', scope: MOCK_SPATIAL_SCOPE })).rejects.toMatchObject({ category, status })
  })

  it('adds scope, correlation, and idempotency metadata without exposing payloads', async () => {
    let request: RequestInit | undefined
    const transport = createFetchSpatialTransport({
      fetcher: vi.fn(async (_input, init) => {
        request = init
        return new Response('{}', { status: 200 })
      }),
    })
    await transport.request({ path: '/operators/spatial/workspace/operations', method: 'POST', scope: MOCK_SPATIAL_SCOPE, body: { secret: 'never logged' } })
    const headers = new Headers(request?.headers)
    expect(headers.get('X-AiDN-Hypervisor-Id')).toBe(MOCK_SPATIAL_SCOPE.hypervisor_id)
    expect(headers.get('X-AiDN-Node-Id')).toBe(MOCK_SPATIAL_SCOPE.node_id)
    expect(headers.get('X-AiDN-Request-Id')).toBeTruthy()
    expect(headers.get('X-AiDN-Correlation-Id')).toBeTruthy()
    expect(headers.get('X-AiDN-Idempotency-Key')).toBeTruthy()
    expect(String(request?.body)).toContain('secret')
  })

  it('parses typed client collections and rejects a response from another Node', async () => {
    const transport = { request: vi.fn(async (request) => {
      if (request.path === '/operators/spatial/status') return mockSpatialNodeStatusPayload
      return { schema_version: 'spatial.collection.v1', node_id: 'node-two', revision: 1, items: [] }
    }) }
    const clients = createSpatialDomainClients(transport)
    await expect(clients.nodeStatus.get(MOCK_SPATIAL_SCOPE)).resolves.toMatchObject({ node_id: 'local-node', state: 'ONLINE' })
    await expect(clients.agents.list(MOCK_SPATIAL_SCOPE)).rejects.toMatchObject({ category: 'conflict' })
  })
})

describe('Spatial M2.3 live event gateway', () => {
  it('applies retained events, deduplicates, and resumes from the latest cursor', () => {
    const stateUpdates: string[] = []
    const notifications: string[] = []
    const gateway = new SpatialEventGateway({
      scope: MOCK_SPATIAL_SCOPE,
      onStateUpdate: (event) => stateUpdates.push(event.event_id),
      onNotification: (event) => notifications.push(event.event_id),
    })
    const replay = gateway.replay(mockSpatialEventStream)
    expect(replay.map((result) => result.status)).toEqual(['applied', 'applied'])
    expect(gateway.getResumeCursor()).toBe('3')
    expect(stateUpdates).toEqual(['mock-event-2', 'mock-event-3'])
    expect(notifications).toEqual(stateUpdates)
    expect(gateway.ingest(mockSpatialEventStream[1]).status).toBe('duplicate')
  })

  it('ignores unknown, malformed, cross-Node, and out-of-order events safely', () => {
    const gateway = new SpatialEventGateway({ scope: MOCK_SPATIAL_SCOPE })
    const applied = gateway.ingest(mockSpatialEventStream[1])
    expect(applied.status).toBe('applied')
    const older = { ...mockSpatialEventStream[0], event_id: 'older-event' }
    expect(gateway.ingest(older)).toMatchObject({ status: 'stale', diagnostic: { code: 'STALE_EVENT' } })
    expect(gateway.ingest({ ...mockSpatialEventStream[1], event_id: 'other-node', node_id: OTHER_SCOPE.node_id })).toMatchObject({ status: 'stale' })
    expect(gateway.ingest({ ...mockSpatialEventStream[1], event_id: 'unknown-event', event_type: 'spatial.future.v1' })).toMatchObject({ status: 'unknown' })
    expect(gateway.ingest({ event_id: 'broken' })).toMatchObject({ status: 'malformed' })
  })

  it('uses bounded reconnect delays', () => {
    expect(spatialReconnectDelay(0)).toBe(250)
    expect(spatialReconnectDelay(4)).toBe(4_000)
    expect(spatialReconnectDelay(99)).toBe(8_000)
  })

  it('reconnects a compatible stream with the retained sequence cursor', () => {
    const callbacks: Array<() => void> = []
    const cursors: Array<string | null> = []
    const connections: Array<{ onMessage: (payload: unknown) => void; onClose: () => void }> = []
    const base = {
      connect: vi.fn(({ resumeCursor, onMessage, onClose }) => {
        cursors.push(resumeCursor)
        connections.push({ onMessage, onClose })
        return { close: vi.fn() }
      }),
    }
    const adapter = createReconnectingSpatialEventStreamAdapter(base, {
      maxAttempts: 2,
      scheduler: (callback) => {
        callbacks.push(callback)
        return callbacks.length as unknown as ReturnType<typeof setTimeout>
      },
      cancelScheduler: vi.fn(),
    })
    adapter.connect({ scope: MOCK_SPATIAL_SCOPE, resumeCursor: null, onMessage: vi.fn(), onClose: vi.fn(), onError: vi.fn() })
    connections[0]?.onMessage(mockSpatialEventStream[0])
    connections[0]?.onClose()
    callbacks.shift()?.()
    expect(cursors).toEqual([null, '2'])
  })
})

describe('Spatial M2.7 fixture path', () => {
  it('keeps the canonical fixture Node-owned and typed before projection', () => {
    const snapshot = createMockSpatialWorkspaceSnapshot()
    expect(snapshot.node_id).toBe(MOCK_SPATIAL_SCOPE.node_id)
    expect(snapshot.entities.length).toBeGreaterThan(1)
    expect(snapshot.entities.some((entity) => entity.kind === 'agent')).toBe(true)
  })
})

describe('Spatial M3.2/M3.4 Primary Agent event path', () => {
  it('routes binding and operational-state events through the typed gateway without renderer calls', () => {
    const slot = {
      schema_version: 'spatial.primary-agent-slot.v1',
      slot_id: 'primary-slot-local-node',
      node_id: MOCK_SPATIAL_SCOPE.node_id,
      current_binding_id: 'binding-event',
      lifecycle_state: 'CONNECTED',
      revision: 1,
      assigned_at: '2026-09-05T16:00:00Z',
      assigned_by: 'operator:event',
      last_seen_at: '2026-09-05T16:00:00Z',
      capability_grant_ref: null,
      hook_subscription_ref: null,
      durable_inbox_ref: 'inbox-local-node',
      changed_at: '2026-09-05T16:00:00Z',
    }
    const state = {
      schema_version: 'spatial.primary-agent-state.v1',
      node_id: MOCK_SPATIAL_SCOPE.node_id,
      slot_id: slot.slot_id,
      binding_id: slot.current_binding_id,
      state: 'THINKING',
      attention_severity: 'NONE',
      source: 'request.lifecycle',
      revision: 1,
      observed_at: '2026-09-05T16:00:00Z',
      last_successful_response_at: null,
      last_failed_response_at: null,
    }
    const gateway = new SpatialEventGateway({ scope: MOCK_SPATIAL_SCOPE })
    expect(gateway.ingest({ event_id: 'binding-event-1', event_type: 'spatial.primary-agent.binding-changed.v1', schema_version: 'spatial.primary-agent-slot.v1', node_id: MOCK_SPATIAL_SCOPE.node_id, sequence: 1, revision: 1, occurred_at: '2026-09-05T16:00:00Z', correlation_id: null, causation_id: null, payload: slot }).status).toBe('applied')
    expect(gateway.ingest({ event_id: 'state-event-1', event_type: 'spatial.primary-agent.state-changed.v1', schema_version: 'spatial.primary-agent-state.v1', node_id: MOCK_SPATIAL_SCOPE.node_id, sequence: 2, revision: 1, occurred_at: '2026-09-05T16:00:00Z', correlation_id: null, causation_id: null, payload: state }).status).toBe('applied')
  })
})
