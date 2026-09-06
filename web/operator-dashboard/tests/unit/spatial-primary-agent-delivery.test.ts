import { describe, expect, it } from 'vitest'

import {
  InMemoryPrimaryAgentDeliveryService,
  InMemoryPrimaryAgentSlotRepository,
  PrimaryAgentBindingApi,
  PrimaryAgentDeliveryConflict,
  type SpatialPrimaryAgentBindingRecord,
} from '@/spatial/data'
import { MOCK_SPATIAL_SCOPE } from '@/spatial/data'

const bindingOne: SpatialPrimaryAgentBindingRecord = {
  binding_id: 'binding-delivery-one',
  node_id: MOCK_SPATIAL_SCOPE.node_id,
  agent_identity_ref: 'agent:delivery-one',
  runtime_ref: 'runtime:mcp-delivery',
  revision: 1,
}

const bindingTwo: SpatialPrimaryAgentBindingRecord = {
  ...bindingOne,
  binding_id: 'binding-delivery-two',
  agent_identity_ref: 'agent:delivery-two',
  revision: 2,
}

function clock() {
  return () => new Date('2026-09-05T16:00:00.000Z')
}

async function connectedFixture() {
  const repository = new InMemoryPrimaryAgentSlotRepository(undefined, { now: clock() })
  const api = new PrimaryAgentBindingApi({ repository, now: clock() })
  const plan = await api.createBindingPlan(MOCK_SPATIAL_SCOPE, {
    operation: 'bind',
    actor_ref: 'operator:delivery',
    idempotency_key: 'delivery-bind',
    binding: { ...bindingOne, capability_grant_ref: 'grant-delivery' },
  })
  await api.applyPlan(MOCK_SPATIAL_SCOPE, plan)
  const service = new InMemoryPrimaryAgentDeliveryService({ repository, now: clock(), maxAttempts: 2 })
  await service.issueGrant(MOCK_SPATIAL_SCOPE, {
    grant_id: 'grant-delivery',
    binding_id: bindingOne.binding_id,
    categories: ['read', 'action'],
    allowlisted_tools: ['resource.inspect'],
    issued_by: 'operator:delivery',
  })
  await service.subscribe(MOCK_SPATIAL_SCOPE, {
    subscription_id: 'hook-delivery',
    binding_id: bindingOne.binding_id,
    filter: { event_types: ['node.health.changed'], resource_refs: ['node:local-node'], severities: ['WARNING'] },
    redaction_profile: { profile_id: 'redact-health', redact_keys: ['secret', 'token', 'private_key'] },
  })
  return { repository, api, service }
}

describe('Spatial M3.3 capability grants, Hooks, and durable inbox', () => {
  it('retains a disconnected event, redacts it before delivery, and acknowledges idempotently after reconnect', async () => {
    const { api, service } = await connectedFixture()
    const suspend = await api.createBindingPlan(MOCK_SPATIAL_SCOPE, { operation: 'suspend', actor_ref: 'operator:delivery', idempotency_key: 'delivery-suspend' })
    await api.applyPlan(MOCK_SPATIAL_SCOPE, suspend)
    const queued = await service.publish(MOCK_SPATIAL_SCOPE, {
      event_id: 'health-event-1',
      node_id: MOCK_SPATIAL_SCOPE.node_id,
      event_type: 'node.health.changed',
      resource_ref: 'node:local-node',
      severity: 'WARNING',
      sequence: 1,
      payload: { state: 'DEGRADED', secret: 'never-deliver', nested: { token: 'also-hidden' } },
    })
    expect(queued.state).toBe('PENDING')
    const recover = await api.createBindingPlan(MOCK_SPATIAL_SCOPE, { operation: 'recover', actor_ref: 'operator:delivery', idempotency_key: 'delivery-recover' })
    await api.applyPlan(MOCK_SPATIAL_SCOPE, recover)
    const deliveries = await service.readInbox(MOCK_SPATIAL_SCOPE, 'binding-delivery-one')
    expect(deliveries).toHaveLength(1)
    expect(deliveries[0]?.payload).toEqual({ state: 'DEGRADED', secret: '[REDACTED]', nested: { token: '[REDACTED]' } })
    expect(JSON.stringify(deliveries[0])).not.toContain('never-deliver')
    const acknowledged = await service.acknowledge(MOCK_SPATIAL_SCOPE, 'binding-delivery-one', deliveries[0]!.delivery_id)
    expect(acknowledged.state).toBe('ACKED')
    await expect(service.acknowledge(MOCK_SPATIAL_SCOPE, 'binding-delivery-one', deliveries[0]!.delivery_id)).resolves.toMatchObject({ state: 'ACKED' })
    await expect(service.readInbox(MOCK_SPATIAL_SCOPE, 'binding-delivery-one')).resolves.toEqual([])
  })

  it('limits filters, retries to a dead letter, and replays explicitly', async () => {
    const { service } = await connectedFixture()
    await service.publish(MOCK_SPATIAL_SCOPE, { event_id: 'ignored', node_id: MOCK_SPATIAL_SCOPE.node_id, event_type: 'other.event', resource_ref: 'node:local-node', severity: 'WARNING', sequence: 1, payload: { ok: true } })
    await service.publish(MOCK_SPATIAL_SCOPE, { event_id: 'accepted', node_id: MOCK_SPATIAL_SCOPE.node_id, event_type: 'node.health.changed', resource_ref: 'node:local-node', severity: 'WARNING', sequence: 2, payload: { ok: true } })
    expect(await service.readInbox(MOCK_SPATIAL_SCOPE, bindingOne.binding_id)).toHaveLength(1)
    await service.retry(MOCK_SPATIAL_SCOPE, bindingOne.binding_id, 'accepted')
    expect(await service.readInbox(MOCK_SPATIAL_SCOPE, bindingOne.binding_id)).toHaveLength(1)
    await service.retry(MOCK_SPATIAL_SCOPE, bindingOne.binding_id, 'accepted')
    expect(await service.readInbox(MOCK_SPATIAL_SCOPE, bindingOne.binding_id)).toHaveLength(0)
    expect(service.listDeadLetters(MOCK_SPATIAL_SCOPE)).toHaveLength(1)
    await service.replay(MOCK_SPATIAL_SCOPE, bindingOne.binding_id, 'accepted')
    expect(await service.readInbox(MOCK_SPATIAL_SCOPE, bindingOne.binding_id)).toHaveLength(1)
  })

  it('prevents revoked agents and cross-binding acknowledgements', async () => {
    const { api, service } = await connectedFixture()
    const delivery = await service.publish(MOCK_SPATIAL_SCOPE, { event_id: 'cross-binding', node_id: MOCK_SPATIAL_SCOPE.node_id, event_type: 'node.health.changed', resource_ref: 'node:local-node', severity: 'WARNING', sequence: 1, payload: { ok: true } })
    const received = await service.readInbox(MOCK_SPATIAL_SCOPE, bindingOne.binding_id)
    expect(received[0]?.event_id).toBe(delivery.event_id)
    const replace = await api.createBindingPlan(MOCK_SPATIAL_SCOPE, { operation: 'replace', actor_ref: 'operator:delivery', idempotency_key: 'delivery-replace', binding: { ...bindingTwo, capability_grant_ref: 'grant-two' } })
    await api.applyPlan(MOCK_SPATIAL_SCOPE, replace)
    await expect(service.acknowledge(MOCK_SPATIAL_SCOPE, bindingTwo.binding_id, received[0]!.delivery_id)).rejects.toMatchObject({ code: 'ACK_CONFLICT' })
    await expect(service.readInbox(MOCK_SPATIAL_SCOPE, bindingOne.binding_id)).rejects.toMatchObject({ code: 'UNAUTHORIZED' })
    await expect(service.readInbox(MOCK_SPATIAL_SCOPE, bindingTwo.binding_id)).rejects.toMatchObject({ code: 'GRANT_REVOKED' })
    const revoke = await api.createBindingPlan(MOCK_SPATIAL_SCOPE, { operation: 'revoke', actor_ref: 'operator:delivery', idempotency_key: 'delivery-revoke' })
    await api.applyPlan(MOCK_SPATIAL_SCOPE, revoke)
    await expect(service.readInbox(MOCK_SPATIAL_SCOPE, bindingTwo.binding_id)).rejects.toBeInstanceOf(PrimaryAgentDeliveryConflict)
  })

  it('emits a versioned grant-change event without exposing credentials', async () => {
    const repository = new InMemoryPrimaryAgentSlotRepository(undefined, { now: clock() })
    const api = new PrimaryAgentBindingApi({ repository, now: clock() })
    const plan = await api.createBindingPlan(MOCK_SPATIAL_SCOPE, { operation: 'bind', actor_ref: 'operator:grant', idempotency_key: 'grant-bind', binding: { ...bindingOne, capability_grant_ref: 'grant-event' } })
    await api.applyPlan(MOCK_SPATIAL_SCOPE, plan)
    const events: unknown[] = []
    const service = new InMemoryPrimaryAgentDeliveryService({ repository, now: clock(), onGrantEvent: (event) => events.push(event) })
    const issued = await service.issueGrant(MOCK_SPATIAL_SCOPE, { grant_id: 'grant-event', binding_id: bindingOne.binding_id, categories: ['read'], allowlisted_tools: ['resource.inspect'], issued_by: 'operator:grant' })
    expect(issued.event.event_type).toBe('spatial.primary-agent.grant-changed.v1')
    expect(events).toHaveLength(1)
    await service.revokeGrant(MOCK_SPATIAL_SCOPE, 'grant-event', 'operator:grant')
    expect(events).toHaveLength(2)
    expect((events[1] as { payload: { state: string } }).payload.state).toBe('REVOKED')
    expect(JSON.stringify(issued.grant)).not.toMatch(/secret|token|private_key|credential/i)
  })
})
