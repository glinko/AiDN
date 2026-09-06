import { describe, expect, it } from 'vitest'

import {
  SpatialRecoveryCommandService,
  SpatialRecoveryError,
  SpatialStatusAggregator,
  StatusWorkspaceBridge,
} from '@/spatial/status'
import { CanonicalReferenceRegistry } from '@/spatial/topology/reference-registry'
import { createMockSpatialNodeStatus } from '@/spatial/data/mock-fixtures'

const NOW = new Date('2026-09-05T16:00:00.000Z')

describe('M6 Node status and recovery boundary', () => {
  it('keeps a partial probe failure explicit without erasing healthy components', async () => {
    const aggregator = new SpatialStatusAggregator({ nodeId: 'node-1', now: () => NOW, staleAfterSeconds: 60 })
    const result = await aggregator.refresh([
      { component_id: 'hypervisor', component_type: 'Hypervisor', kind: 'hypervisor', probe: () => ({ component_id: 'hypervisor', component_type: 'Hypervisor', kind: 'hypervisor', state: 'ONLINE', source: 'probe.hypervisor' }) },
      { component_id: 'hooks', component_type: 'Hooks', kind: 'hooks', probe: () => { throw new Error('probe unavailable') } },
    ])
    expect(result.failed).toEqual(['hooks'])
    expect(result.snapshot.partial).toBe(true)
    expect(result.snapshot.components.find((component) => component.component_id === 'hypervisor')?.state).toBe('ONLINE')
    expect(result.snapshot.components.find((component) => component.component_id === 'hooks')).toMatchObject({ state: 'UNKNOWN', issue_code: 'PROBE_UNAVAILABLE' })
    expect(result.snapshot.state).toBe('DEGRADED')
  })

  it('marks cached status as STALE and bounds/redacts evidence', async () => {
    const aggregator = new SpatialStatusAggregator({ nodeId: 'node-1', now: () => NOW })
    await aggregator.refresh([{
      component_id: 'wallet',
      component_type: 'Wallet',
      kind: 'wallet',
      probe: () => ({
        component_id: 'wallet',
        component_type: 'Wallet',
        kind: 'wallet',
        state: 'ONLINE',
        source: 'probe.wallet',
        evidence_refs: Array.from({ length: 40 }, (_, index) => ({ ref: `evidence-${index}`, authorized: index !== 1, redacted: index === 1 })),
      }),
    }])
    const cached = aggregator.readCached()
    expect(cached).toMatchObject({ cached: true, state: 'STALE', freshness: { state: 'STALE' } })
    expect(cached?.components[0]?.evidence_refs).toHaveLength(32)
    expect(cached?.components[0]?.evidence_refs[1]).toMatchObject({ authorized: false, redacted: true })
  })

  it('requires capability, fresh revision and confirmation, then makes duplicate apply idempotent', async () => {
    const service = new SpatialRecoveryCommandService()
    const plan = service.plan({ nodeId: 'node-1', targetRef: 'hooks:dead-letter-1', action: 'RETRY_HOOK_DEAD_LETTER', currentRevision: 7, capabilities: ['recovery.retry-hook-dead-letter'] })
    await expect(service.apply({ plan, currentRevision: 6, capabilities: ['recovery.retry-hook-dead-letter'] })).rejects.toMatchObject({ code: 'STALE_PLAN' })
    const result = await service.apply({ plan, currentRevision: 7, capabilities: ['recovery.retry-hook-dead-letter'] })
    expect(result.state).toBe('APPLIED')
    const duplicate = await service.apply({ plan, currentRevision: 7, capabilities: ['recovery.retry-hook-dead-letter'] })
    expect(duplicate.state).toBe('NOOP')

    const destructive = service.plan({ nodeId: 'node-1', targetRef: 'service:hooks', action: 'DISABLE_HOOK', currentRevision: 7 })
    await expect(service.apply({ plan: destructive, currentRevision: 7, capabilities: ['recovery.disable-hook'] })).rejects.toMatchObject({ code: 'CONFIRMATION_REQUIRED' })
    await expect(service.apply({ plan: destructive, currentRevision: 7, capabilities: [] })).rejects.toBeInstanceOf(SpatialRecoveryError)
    await expect(service.apply({ plan: destructive, currentRevision: 7, capabilities: ['recovery.disable-hook'], confirmed: true })).resolves.toMatchObject({ state: 'APPLIED' })
  })

  it('focuses an existing canonical presence without mutating topology and rejects wrong scope', () => {
    const registry = new CanonicalReferenceRegistry({ workspaceId: 'workspace-1', nodeId: 'node-1', now: () => NOW })
    registry.register({ canonicalRef: 'endpoint:api', entityId: 'api', entityKind: 'endpoint', revision: 4 })
    const bridge = new StatusWorkspaceBridge(registry)
    expect(bridge.showInWorkspace({ workspaceId: 'workspace-1', nodeId: 'node-1', canonicalRef: 'endpoint:api' })).toMatchObject({ outcome: 'FOCUS_EXISTING', world_position_preserved: true })
    expect(bridge.showInWorkspace({ workspaceId: 'other', nodeId: 'node-1', canonicalRef: 'endpoint:api' })).toEqual({ outcome: 'REJECTED', reason: 'WRONG_WORKSPACE' })
    expect(registry.list()).toHaveLength(1)
  })

  it('keeps the existing fixture status contract parseable after additive M6 fields', () => {
    const fixture = createMockSpatialNodeStatus()
    expect(fixture.schema_version).toBe('spatial.node-status.v1')
    expect(fixture.components.length).toBeGreaterThan(0)
  })
})
