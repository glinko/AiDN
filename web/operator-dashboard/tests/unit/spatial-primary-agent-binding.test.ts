import { describe, expect, it, vi } from 'vitest'

import {
  InMemoryPrimaryAgentSlotRepository,
  PrimaryAgentBindingApi,
  PrimaryAgentSlotConflict,
  createPrimaryAgentBindingApi,
  computePrimaryAgentBindingPlanHash,
  type SpatialPrimaryAgentBindingRecord,
} from '@/spatial/data'
import { MOCK_SPATIAL_SCOPE } from '@/spatial/data'

const bindingOne: SpatialPrimaryAgentBindingRecord = {
  binding_id: 'binding-api-one',
  node_id: MOCK_SPATIAL_SCOPE.node_id,
  agent_identity_ref: 'agent:api-one',
  runtime_ref: 'runtime:mcp-one',
  revision: 1,
}

const bindingTwo: SpatialPrimaryAgentBindingRecord = {
  ...bindingOne,
  binding_id: 'binding-api-two',
  agent_identity_ref: 'agent:api-two',
  runtime_ref: 'runtime:mcp-two',
  revision: 2,
}

function fixedClock() {
  return () => new Date('2026-09-05T16:00:00.000Z')
}

describe('Spatial M3.2 authorized Primary Agent binding API', () => {
  it('creates safe revision-bound plans and emits a typed binding-changed event', async () => {
    const repository = new InMemoryPrimaryAgentSlotRepository(undefined, { now: fixedClock() })
    const events: unknown[] = []
    const api = createPrimaryAgentBindingApi({ repository, now: fixedClock(), onEvent: (event) => events.push(event) })
    const plan = await api.createBindingPlan(MOCK_SPATIAL_SCOPE, {
      operation: 'bind',
      actor_ref: 'operator:m3-2',
      idempotency_key: 'm3-2-bind-1',
      binding: bindingOne,
    })
    expect(plan.expected_revision).toBe(0)
    expect(plan.plan_hash).toBe(computePrimaryAgentBindingPlanHash(plan))
    expect(JSON.stringify(plan)).not.toMatch(/secret|token|private_key|credential/i)

    const result = await api.applyBindingPlan(MOCK_SPATIAL_SCOPE, plan)
    expect(result.mutation.slot).toMatchObject({ lifecycle_state: 'CONNECTED', current_binding_id: bindingOne.binding_id })
    expect(result.audit).toMatchObject({ actor_ref: 'operator:m3-2', operation: 'bind', secret_material_present: false })
    expect(result.event.event_type).toBe('spatial.primary-agent.binding-changed.v1')
    expect(events).toHaveLength(1)
  })

  it('keeps retries idempotent, rejects stale plans, and authorizes the browser operator', async () => {
    const authorized = vi.fn(async (scope, plan) => scope.node_id === MOCK_SPATIAL_SCOPE.node_id && plan.actor_ref === 'operator:allowed')
    const repository = new InMemoryPrimaryAgentSlotRepository(undefined, { now: fixedClock() })
    const events: unknown[] = []
    const api = new PrimaryAgentBindingApi({ repository, now: fixedClock(), authorize: authorized, onEvent: (event) => events.push(event) })
    const plan = await api.createBindingPlan(MOCK_SPATIAL_SCOPE, { operation: 'bind', actor_ref: 'operator:allowed', idempotency_key: 'retry-bind', binding: bindingOne })
    const first = await api.applyPlan(MOCK_SPATIAL_SCOPE, plan)
    const retry = await api.applyPlan(MOCK_SPATIAL_SCOPE, plan)
    expect(retry.mutation).toEqual(first.mutation)
    expect((await repository.getChanges(MOCK_SPATIAL_SCOPE, 0))).toHaveLength(1)
    expect(events).toHaveLength(1)

    const stale = await api.createBindingPlan(MOCK_SPATIAL_SCOPE, { operation: 'replace', actor_ref: 'operator:allowed', idempotency_key: 'stale-replace', binding: bindingTwo })
    await api.applyBindingPlan(MOCK_SPATIAL_SCOPE, stale)
    await expect(api.applyBindingPlan(MOCK_SPATIAL_SCOPE, { ...stale, plan_id: 'different-plan', idempotency_key: 'different-plan', plan_hash: computePrimaryAgentBindingPlanHash({ ...stale, plan_id: 'different-plan', idempotency_key: 'different-plan' }) })).rejects.toMatchObject({ code: 'STALE_REVISION' })

    const denied = new PrimaryAgentBindingApi({ repository, now: fixedClock(), authorize: async () => false })
    const deniedPlan = await denied.createBindingPlan(MOCK_SPATIAL_SCOPE, { operation: 'detach', actor_ref: 'operator:denied', idempotency_key: 'denied-detach' })
    await expect(denied.applyBindingPlan(MOCK_SPATIAL_SCOPE, deniedPlan)).rejects.toMatchObject({ code: 'UNAUTHORIZED' })
    expect(authorized).toHaveBeenCalled()
  })

  it('supports suspend, recovery, replace, detach and revoke without deleting the slot', async () => {
    let revoked: string | null = null
    const repository = new InMemoryPrimaryAgentSlotRepository(undefined, { now: fixedClock() })
    const api = new PrimaryAgentBindingApi({ repository, now: fixedClock(), onBindingRevoked: (bindingId) => { revoked = bindingId } })
    const bind = await api.createBindingPlan(MOCK_SPATIAL_SCOPE, { operation: 'bind', actor_ref: 'operator:test', idempotency_key: 'bind-flow', binding: bindingOne })
    await api.applyPlan(MOCK_SPATIAL_SCOPE, bind)
    const suspend = await api.createBindingPlan(MOCK_SPATIAL_SCOPE, { operation: 'suspend', actor_ref: 'operator:test', idempotency_key: 'suspend-flow' })
    expect((await api.applyPlan(MOCK_SPATIAL_SCOPE, suspend)).mutation.slot.lifecycle_state).toBe('DISCONNECTED')
    const recover = await api.createBindingPlan(MOCK_SPATIAL_SCOPE, { operation: 'recover', actor_ref: 'operator:test', idempotency_key: 'recover-flow' })
    expect((await api.applyPlan(MOCK_SPATIAL_SCOPE, recover)).mutation.slot.lifecycle_state).toBe('CONNECTED')
    const replace = await api.createBindingPlan(MOCK_SPATIAL_SCOPE, { operation: 'replace', actor_ref: 'operator:test', idempotency_key: 'replace-flow', binding: bindingTwo })
    await api.applyPlan(MOCK_SPATIAL_SCOPE, replace)
    const detach = await api.createBindingPlan(MOCK_SPATIAL_SCOPE, { operation: 'detach', actor_ref: 'operator:test', idempotency_key: 'detach-flow' })
    expect((await api.applyPlan(MOCK_SPATIAL_SCOPE, detach)).mutation.slot.lifecycle_state).toBe('UNASSIGNED')
    const rebind = await api.createBindingPlan(MOCK_SPATIAL_SCOPE, { operation: 'bind', actor_ref: 'operator:test', idempotency_key: 'rebind-flow', binding: bindingOne })
    await api.applyPlan(MOCK_SPATIAL_SCOPE, rebind)
    const revoke = await api.createBindingPlan(MOCK_SPATIAL_SCOPE, { operation: 'revoke', actor_ref: 'operator:test', idempotency_key: 'revoke-flow' })
    await api.applyPlan(MOCK_SPATIAL_SCOPE, revoke)
    expect(revoked).toBe(bindingOne.binding_id)
    await expect(api.inspectSlot(MOCK_SPATIAL_SCOPE)).resolves.toMatchObject({ slot: { lifecycle_state: 'REVOKED' } })
  })

  it('rejects a forged plan hash and cross-Node binding', async () => {
    const repository = new InMemoryPrimaryAgentSlotRepository(undefined, { now: fixedClock() })
    const api = new PrimaryAgentBindingApi({ repository, now: fixedClock() })
    await expect(api.createBindingPlan(MOCK_SPATIAL_SCOPE, { operation: 'bind', actor_ref: 'operator:test', idempotency_key: 'wrong-node', binding: { ...bindingOne, node_id: 'node-other' } })).rejects.toMatchObject({ code: 'NODE_MISMATCH' })
    const plan = await api.createBindingPlan(MOCK_SPATIAL_SCOPE, { operation: 'bind', actor_ref: 'operator:test', idempotency_key: 'forged', binding: bindingOne })
    await expect(api.applyBindingPlan(MOCK_SPATIAL_SCOPE, { ...plan, plan_hash: 'sha256:forged' })).rejects.toBeInstanceOf(PrimaryAgentSlotConflict)
  })
})
