import { describe, expect, it, vi } from 'vitest'

import {
  MOCK_SPATIAL_SCOPE,
  createMockSpatialPresentation,
  createMockSpatialWorkspaceSnapshot,
} from '@/spatial/data'
import {
  InMemorySpatialWorkspaceRepository,
  SpatialWorkspaceConflict,
  applySpatialSemanticSnapshot,
  createHttpSpatialWorkspaceRepository,
  createSpatialWorkspaceModel,
  resetSpatialPresentation,
  workspaceSurvivesAgentChange,
} from '@/spatial/workspace'

function semanticOperation(snapshotRevision: number, payload: unknown, key = 'operation-key') {
  return {
    operation_id: `${key}-operation`,
    idempotency_key: key,
    actor_ref: 'operator:test',
    expected_revision: snapshotRevision,
    kind: 'upsert-entity' as const,
    payload,
  }
}

describe('Spatial M2.5 Workspace domain model', () => {
  it('keeps semantic and device presentation state separately versioned', () => {
    const snapshot = createMockSpatialWorkspaceSnapshot()
    const presentation = createMockSpatialPresentation('device-a')
    const model = createSpatialWorkspaceModel(snapshot, presentation, MOCK_SPATIAL_SCOPE)
    const reset = resetSpatialPresentation({ ...presentation, presentation_revision: 7, selection_ref: 'artifact-plan' }, new Date('2026-09-05T16:01:00Z'))
    expect(model.semantic.semantic_revision).toBe(snapshot.semantic_revision)
    expect(reset.presentation_revision).toBe(8)
    expect(reset.selection_ref).toBeNull()
    expect(reset.workspace_id).toBe(snapshot.workspace_id)
    expect(reset.presentation_revision).not.toBe(model.semantic.semantic_revision)
    expect(() => createSpatialWorkspaceModel(snapshot, { ...presentation, node_id: 'other-node' }, MOCK_SPATIAL_SCOPE)).toThrowError(SpatialWorkspaceConflict)
  })

  it('preserves the Workspace when an Agent binding is detached or replaced', () => {
    const snapshot = createMockSpatialWorkspaceSnapshot()
    const result = workspaceSurvivesAgentChange(snapshot, null)
    expect(result.snapshot).toEqual(snapshot)
    expect(result.agentBindingRef).toBeNull()
    const replaced = workspaceSurvivesAgentChange(snapshot, 'agent:replacement')
    expect(replaced.snapshot.workspace_id).toBe(snapshot.workspace_id)
    expect(replaced.snapshot.entities.length).toBe(snapshot.entities.length)
  })

  it('rejects a stale semantic snapshot and a different Node', () => {
    const snapshot = createMockSpatialWorkspaceSnapshot()
    const older = { ...snapshot, semantic_revision: 0 }
    expect(() => applySpatialSemanticSnapshot(snapshot, older, MOCK_SPATIAL_SCOPE)).toThrowError(SpatialWorkspaceConflict)
    expect(() => applySpatialSemanticSnapshot(snapshot, { ...snapshot, node_id: 'other-node' }, MOCK_SPATIAL_SCOPE)).toThrowError(SpatialWorkspaceConflict)
  })
})

describe('Spatial M2.6 Workspace persistence', () => {
  it('supports stale revision rejection and idempotent duplicate operations', async () => {
    const snapshot = createMockSpatialWorkspaceSnapshot()
    const endpoint = snapshot.entities.find((entity) => entity.kind === 'endpoint')
    expect(endpoint).toBeTruthy()
    if (!endpoint) return
    const repository = new InMemorySpatialWorkspaceRepository(snapshot)
    const operation = semanticOperation(snapshot.semantic_revision, endpoint, 'same-operation')
    const first = await repository.applySemanticOperation(MOCK_SPATIAL_SCOPE, operation)
    const duplicate = await repository.applySemanticOperation(MOCK_SPATIAL_SCOPE, operation)
    expect(duplicate).toEqual(first)
    expect(first.audit_recorded).toBe(true)
    expect(first.change.actor_ref).toBe('operator:test')
    await expect(repository.getChanges(MOCK_SPATIAL_SCOPE, snapshot.semantic_revision)).resolves.toEqual([first.change])
    await expect(repository.getChanges(MOCK_SPATIAL_SCOPE, first.change.semantic_revision)).resolves.toEqual([])
    await expect(repository.getChanges(MOCK_SPATIAL_SCOPE, 0)).resolves.toEqual([first.change])
    await expect(repository.applySemanticOperation(MOCK_SPATIAL_SCOPE, { ...operation, idempotency_key: 'stale-operation', operation_id: 'stale', expected_revision: snapshot.semantic_revision })).rejects.toMatchObject({ code: 'STALE_REVISION' })
  })

  it('rejects wrong Node, missing idempotency, unauthorized actor, and agent replacement races', async () => {
    const snapshot = createMockSpatialWorkspaceSnapshot()
    const endpoint = snapshot.entities.find((entity) => entity.kind === 'endpoint')
    expect(endpoint).toBeTruthy()
    if (!endpoint) return
    const repository = new InMemorySpatialWorkspaceRepository(snapshot, { authorize: () => false })
    await expect(repository.getSnapshot({ hypervisor_id: 'other', node_id: 'other-node' })).rejects.toMatchObject({ code: 'NODE_MISMATCH' })
    await expect(repository.applySemanticOperation(MOCK_SPATIAL_SCOPE, semanticOperation(snapshot.semantic_revision, endpoint, 'no-auth'))).rejects.toMatchObject({ code: 'UNAUTHORIZED' })
    const authorized = new InMemorySpatialWorkspaceRepository(snapshot)
    await expect(authorized.applySemanticOperation(MOCK_SPATIAL_SCOPE, { ...semanticOperation(snapshot.semantic_revision, endpoint, ''), idempotency_key: '' })).rejects.toMatchObject({ code: 'VALIDATION' })
    authorized.setAgentBindingRevision(2)
    type OperationWithBinding = ReturnType<typeof semanticOperation> & { agent_binding_revision: number }
    const racingOperation: OperationWithBinding = { ...semanticOperation(snapshot.semantic_revision, endpoint, 'agent-race'), agent_binding_revision: 1 }
    await expect(authorized.applySemanticOperation(MOCK_SPATIAL_SCOPE, racingOperation)).rejects.toMatchObject({ code: 'AGENT_REPLACED' })
  })

  it('does not commit after partial persistence failure and marks presentation writes as local-only', async () => {
    const snapshot = createMockSpatialWorkspaceSnapshot()
    const endpoint = snapshot.entities.find((entity) => entity.kind === 'endpoint')
    expect(endpoint).toBeTruthy()
    if (!endpoint) return
    const repository = new InMemorySpatialWorkspaceRepository(snapshot)
    repository.failNextWrite()
    await expect(repository.applySemanticOperation(MOCK_SPATIAL_SCOPE, semanticOperation(snapshot.semantic_revision, endpoint, 'partial'))).rejects.toMatchObject({ code: 'PARTIAL_PERSISTENCE' })
    await expect(repository.getSnapshot(MOCK_SPATIAL_SCOPE)).resolves.toMatchObject({ semantic_revision: snapshot.semantic_revision })
    const presentation = createMockSpatialPresentation('device-a')
    const written = await repository.putPresentation(MOCK_SPATIAL_SCOPE, presentation)
    expect(written.protocol_event_emitted).toBe(false)
    expect(written.recovered).toBe(false)
  })

  it('recovers corrupt presentation state and exposes entity/relation references', async () => {
    const snapshot = createMockSpatialWorkspaceSnapshot()
    const repository = new InMemorySpatialWorkspaceRepository(snapshot)
    const internal = repository as unknown as { presentations: Map<string, unknown> }
    internal.presentations.set('device-corrupt', { no: 'viewport' })
    const recovered = await repository.resetPresentation(MOCK_SPATIAL_SCOPE, 'device-corrupt')
    expect(recovered.recovered).toBe(true)
    expect(recovered.protocol_event_emitted).toBe(false)
    const entity = snapshot.entities[0]
    const relation = snapshot.relations[0]
    await expect(repository.getEntity(MOCK_SPATIAL_SCOPE, entity.canonical_ref)).resolves.toMatchObject({ canonical_ref: entity.canonical_ref })
    await expect(repository.getRelation(MOCK_SPATIAL_SCOPE, relation.relation_id)).resolves.toMatchObject({ relation_id: relation.relation_id })
  })

  it('keeps the HTTP adapter on the same typed and idempotent boundary', async () => {
    const snapshot = createMockSpatialWorkspaceSnapshot()
    const endpoint = snapshot.entities.find((entity) => entity.kind === 'endpoint')
    expect(endpoint).toBeTruthy()
    if (!endpoint) return
    const change = {
      change_id: 'change-2',
      workspace_id: snapshot.workspace_id,
      node_id: snapshot.node_id,
      semantic_revision: 2,
      operation_id: 'http-operation',
      actor_ref: 'operator:test',
      kind: 'upsert-entity' as const,
      occurred_at: snapshot.updated_at,
      audit_recorded: true as const,
    }
    const transport = { request: vi.fn(async ({ path }: { path: string }) => {
      if (path.includes('/changes')) return { items: [change] }
      if (path.endsWith('/operations')) return { snapshot, change, protocol_event_emitted: true, audit_recorded: true }
      return snapshot
    }) }
    const repository = createHttpSpatialWorkspaceRepository({ transport })
    const operation = semanticOperation(snapshot.semantic_revision, endpoint, 'http-key')
    const mutation = await repository.applySemanticOperation(MOCK_SPATIAL_SCOPE, operation)
    expect(mutation.audit_recorded).toBe(true)
    const operationCall = transport.request.mock.calls.find(([request]) => request.path.endsWith('/operations'))?.[0]
    expect(operationCall?.headers).toMatchObject({ 'X-AiDN-Idempotency-Key': 'http-key', 'X-AiDN-Correlation-Id': 'http-key-operation' })
    await expect(repository.getChanges(MOCK_SPATIAL_SCOPE, 1)).resolves.toEqual([change])
  })
})
