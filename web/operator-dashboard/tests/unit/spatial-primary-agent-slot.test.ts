import { describe, expect, it } from 'vitest'

import {
  MOCK_SPATIAL_SCOPE,
  PRIMARY_AGENT_SLOT_TRANSITIONS,
  InMemoryPrimaryAgentSlotRepository,
  PrimaryAgentSlotConflict,
  createPrimaryAgentSlot,
  parseSpatialPrimaryAgentSlot,
  spatialPrimaryAgentSlotSchema,
  transitionPrimaryAgentSlot,
  type SpatialPrimaryAgentBindingRecord,
  type SpatialPrimaryAgentSlotOperation,
} from '@/spatial/data'
import { spatialContractFixtures } from '@/spatial/contracts/fixtures'

const OTHER_SCOPE = { hypervisor_id: 'hypervisor-other', node_id: 'node-other' } as const

const bindingOne: SpatialPrimaryAgentBindingRecord = {
  binding_id: 'binding-primary-one',
  node_id: MOCK_SPATIAL_SCOPE.node_id,
  agent_identity_ref: 'agent:identity-one',
  runtime_ref: 'runtime:mcp-one',
  revision: 1,
  capability_grant_ref: 'grant:read-only',
}

const bindingTwo: SpatialPrimaryAgentBindingRecord = {
  ...bindingOne,
  binding_id: 'binding-primary-two',
  agent_identity_ref: 'agent:identity-two',
  runtime_ref: 'runtime:mcp-two',
  revision: 2,
  capability_grant_ref: 'grant:operator',
}

function operation(slotRevision: number, key: string, kind: SpatialPrimaryAgentSlotOperation['kind'], extra: Partial<SpatialPrimaryAgentSlotOperation> = {}): SpatialPrimaryAgentSlotOperation {
  return {
    operation_id: `${key}-operation`,
    idempotency_key: key,
    actor_ref: 'operator:test',
    expected_revision: slotRevision,
    kind,
    ...extra,
  }
}

describe('Spatial M3.1 Primary Agent Slot contract', () => {
  it('parses the Node-scoped role separately from identity and runtime binding', () => {
    const parsed = parseSpatialPrimaryAgentSlot({
      ...spatialContractFixtures.unassignedPrimaryAgentSlot,
      secret: 'must-not-cross-the-contract',
    })
    expect(parsed).toMatchObject({ ok: true })
    if (!parsed.ok) return
    expect(parsed.data.lifecycle_state).toBe('UNASSIGNED')
    expect(parsed.data.current_binding_id).toBeNull()
    expect(parsed.data.durable_inbox_ref).toBeTruthy()
    expect('secret' in parsed.data).toBe(false)
    expect(spatialPrimaryAgentSlotSchema.safeParse({ ...parsed.data, schema_version: 'spatial.primary-agent-slot.v2' }).success).toBe(false)
  })

  it('creates one stable unassigned slot per Node and rejects duplicate or cross-Node ownership', async () => {
    const repository = new InMemoryPrimaryAgentSlotRepository()
    const created = repository.createSlot(MOCK_SPATIAL_SCOPE, { now: new Date('2026-09-05T16:00:00Z') })
    expect(created.slot_id).toBe(`primary-agent-slot-${MOCK_SPATIAL_SCOPE.node_id}`)
    expect(created.lifecycle_state).toBe('UNASSIGNED')
    expect(repository.createSlot).toBeTypeOf('function')
    expect(() => repository.createSlot(MOCK_SPATIAL_SCOPE)).toThrowError(PrimaryAgentSlotConflict)
    await expect(repository.getSlot(OTHER_SCOPE)).rejects.toMatchObject({ code: 'NOT_FOUND' })
  })

  it('allows explicit lifecycle transitions but keeps revoked slots terminal', () => {
    const slot = createPrimaryAgentSlot(MOCK_SPATIAL_SCOPE, { now: new Date('2026-09-05T16:00:00Z') })
    const binding = transitionPrimaryAgentSlot(slot, 'BINDING', { actor_ref: 'operator:test', operation_id: 'transition-1', now: new Date('2026-09-05T16:01:00Z') })
    expect(binding.lifecycle_state).toBe('BINDING')
    expect(binding.revision).toBe(1)
    expect(binding.provenance?.operation_id).toBe('transition-1')
    expect(PRIMARY_AGENT_SLOT_TRANSITIONS.REVOKED).toEqual([])
    expect(() => transitionPrimaryAgentSlot({ ...binding, lifecycle_state: 'REVOKED' }, 'CONNECTED')).toThrowError(PrimaryAgentSlotConflict)
  })
})

describe('Spatial M3.1 Primary Agent Slot repository', () => {
  it('binds and replaces atomically while keeping durable inbox and audit provenance', async () => {
    const repository = new InMemoryPrimaryAgentSlotRepository()
    await repository.ensureSlot(MOCK_SPATIAL_SCOPE)
    repository.registerBinding(bindingOne)
    repository.registerBinding(bindingTwo)

    const first = await repository.apply(MOCK_SPATIAL_SCOPE, operation(0, 'bind-one', 'bind', { binding_id: bindingOne.binding_id }))
    expect(first.slot).toMatchObject({ lifecycle_state: 'CONNECTED', current_binding_id: bindingOne.binding_id, assigned_by: 'operator:test' })
    expect(first.slot.durable_inbox_ref).toBe(`inbox-primary-agent-${MOCK_SPATIAL_SCOPE.node_id}`)
    expect(first.change.audit_recorded).toBe(true)
    expect(first.slot.provenance?.actor_ref).toBe('operator:test')

    const replaced = await repository.apply(MOCK_SPATIAL_SCOPE, operation(1, 'replace-two', 'replace', { binding_id: bindingTwo.binding_id }))
    expect(replaced.slot.current_binding_id).toBe(bindingTwo.binding_id)
    expect(replaced.slot.revision).toBe(2)
    expect(replaced.slot.durable_inbox_ref).toBe(first.slot.durable_inbox_ref)
    await expect(repository.getChanges(MOCK_SPATIAL_SCOPE, 0)).resolves.toHaveLength(2)
  })

  it('rejects stale/concurrent commands, mismatched bindings, and preserves idempotent retries across restart', async () => {
    const repository = new InMemoryPrimaryAgentSlotRepository()
    await repository.ensureSlot(MOCK_SPATIAL_SCOPE)
    repository.registerBinding(bindingOne)
    repository.registerBinding(bindingTwo)

    const [winner, loser] = await Promise.allSettled([
      repository.apply(MOCK_SPATIAL_SCOPE, operation(0, 'concurrent-one', 'bind', { binding_id: bindingOne.binding_id })),
      repository.apply(MOCK_SPATIAL_SCOPE, operation(0, 'concurrent-two', 'bind', { binding_id: bindingTwo.binding_id })),
    ])
    expect([winner, loser].filter((result) => result.status === 'fulfilled')).toHaveLength(1)
    expect([winner, loser].find((result) => result.status === 'rejected')).toMatchObject({ reason: { code: 'STALE_REVISION' } })

    const winningResult = winner.status === 'fulfilled' ? winner.value : loser.value
    const duplicate = await repository.apply(MOCK_SPATIAL_SCOPE, operation(0, winningResult.change.operation_id.replace('-operation', ''), 'bind', {
      binding_id: winningResult.slot.current_binding_id ?? undefined,
    }))
    expect(duplicate).toEqual(winningResult)

    await expect(repository.apply(MOCK_SPATIAL_SCOPE, operation(1, 'wrong-node-binding', 'replace', {
      binding: { ...bindingOne, node_id: OTHER_SCOPE.node_id },
    }))).rejects.toMatchObject({ code: 'NODE_MISMATCH' })
    await expect(repository.apply(MOCK_SPATIAL_SCOPE, operation(0, 'stale-new-operation', 'replace', { binding_id: bindingOne.binding_id }))).rejects.toMatchObject({ code: 'STALE_REVISION' })

    const restarted = repository.restart()
    await expect(restarted.getSlot(MOCK_SPATIAL_SCOPE)).resolves.toMatchObject({ revision: 1, lifecycle_state: 'CONNECTED' })
    const retry = await restarted.apply(MOCK_SPATIAL_SCOPE, operation(0, winningResult.change.operation_id.replace('-operation', ''), 'bind', {
      binding_id: winningResult.slot.current_binding_id ?? undefined,
    }))
    expect(retry).toEqual(winningResult)
  })

  it('rejects corrupted binding references before exposing the slot', () => {
    const corrupted = createPrimaryAgentSlot(MOCK_SPATIAL_SCOPE)
    const withMissingBinding = { ...corrupted, current_binding_id: 'binding:missing', lifecycle_state: 'CONNECTED' as const }
    expect(() => new InMemoryPrimaryAgentSlotRepository(withMissingBinding)).toThrowError(PrimaryAgentSlotConflict)
    try {
      new InMemoryPrimaryAgentSlotRepository(withMissingBinding)
    } catch (error) {
      expect(error).toMatchObject({ code: 'CORRUPT_BINDING' })
    }
  })
})
