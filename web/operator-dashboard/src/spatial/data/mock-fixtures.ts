import {
  parseSpatialNodeStatus,
  parseSpatialViewport,
  parseSpatialWorkspace,
  type SpatialNodeStatus,
  type SpatialViewportSnapshot,
  type SpatialWorkspaceSnapshot,
} from '@/spatial/contracts'

import { spatialEntities, spatialRelations, type SpatialEntity } from '../prototype/entities'
import { createSpatialPresentationSnapshot } from '../workspace/model'
import type { SpatialNodeScope } from './scope'

export const MOCK_SPATIAL_SCOPE = {
  hypervisor_id: 'local-hypervisor',
  node_id: 'local-node',
} as const

const MOCK_OBSERVED_AT = '2026-09-05T16:00:00.000Z'
const MOCK_FRESHNESS = {
  state: 'FRESH',
  observed_at: MOCK_OBSERVED_AT,
  stale_after_seconds: 900,
  source: 'mock-node-read-model',
} as const

function canonicalRef(entity: SpatialEntity): string {
  const kind = entity.kind === 'subagent' ? 'agent' : entity.kind
  return `${kind}:${entity.id}`
}

function canonicalEntity(entity: SpatialEntity, index: number): Record<string, unknown> {
  const kind = entity.kind === 'subagent' ? 'agent' : entity.kind
  const base = {
    schema_version: 'spatial.entity.v1',
    kind,
    id: entity.id,
    canonical_ref: canonicalRef(entity),
    node_id: MOCK_SPATIAL_SCOPE.node_id,
    revision: index + 1,
    label: entity.label,
    state: entity.kind === 'attention' ? 'WARNING' : 'READY',
    availability: entity.kind === 'attention' ? 'DEGRADED' : 'AVAILABLE',
    freshness: MOCK_FRESHNESS,
    created_at: MOCK_OBSERVED_AT,
    updated_at: MOCK_OBSERVED_AT,
  }
  switch (kind) {
    case 'agent':
      return { ...base, role: 'SUBAGENT', capability_refs: [] }
    case 'endpoint':
      return { ...base, endpoint_type: 'mediated-capability', capability_refs: [] }
    case 'artifact':
      return { ...base, artifact_type: 'session-artifact', provenance_ref: canonicalRef(entity), source_revision: index + 1 }
    case 'attention':
      return { ...base, severity: 'WARNING', requires_operator: true }
    case 'service':
      return { ...base, service_type: 'node-service' }
    case 'session':
      return { ...base, session_type: 'SESSION', actor_refs: [] }
  }
}

export const mockSpatialWorkspacePayload = {
  schema_version: 'spatial.workspace.v1',
  workspace_id: 'workspace-local-node',
  node_id: MOCK_SPATIAL_SCOPE.node_id,
  revision: 1,
  semantic_revision: 1,
  created_at: MOCK_OBSERVED_AT,
  updated_at: MOCK_OBSERVED_AT,
  entities: spatialEntities.map(canonicalEntity),
  relations: spatialRelations.map((relation) => ({
    schema_version: 'spatial.relation.v1',
    relation_id: relation.id,
    node_id: MOCK_SPATIAL_SCOPE.node_id,
    revision: 1,
    relation_type: relation.label.replaceAll(' ', '_'),
    source_ref: `${relation.sourceId.startsWith('subagent') ? 'agent' : relation.sourceId.startsWith('endpoint') ? 'endpoint' : 'artifact'}:${relation.sourceId}`,
    target_ref: `${relation.targetId.startsWith('subagent') ? 'agent' : relation.targetId.startsWith('endpoint') ? 'endpoint' : 'artifact'}:${relation.targetId}`,
    state: 'ACTIVE',
    freshness: MOCK_FRESHNESS,
    created_at: MOCK_OBSERVED_AT,
    updated_at: MOCK_OBSERVED_AT,
  })),
  semantic_anchors: spatialEntities.map((entity) => ({
    canonical_ref: canonicalRef(entity),
    position: entity.position,
    region: entity.kind === 'endpoint' ? 'ENDPOINT_ARC' : entity.kind === 'artifact' ? 'SESSION_MEMORY' : entity.kind === 'attention' ? 'ATTENTION' : 'LOCAL_AGENTS',
  })),
  cluster_membership: {},
  primary_agent_ref: 'agent:primary-agent-fixture',
} as const

const primaryAgentPayload = {
  ...canonicalEntity({
  id: 'primary-agent-fixture',
  kind: 'subagent',
  label: 'Primary Agent',
  description: 'Node-scoped Primary Agent fixture.',
  position: { x: 0, y: 0.42, z: 0 },
  priority: 1,
  }, 0),
  role: 'PRIMARY',
} as const

export const mockSpatialWorkspaceWithPrimaryPayload = {
  ...mockSpatialWorkspacePayload,
  entities: [primaryAgentPayload, ...mockSpatialWorkspacePayload.entities],
} as const

export const mockSpatialNodeStatusPayload = {
  schema_version: 'spatial.node-status.v1',
  node_id: MOCK_SPATIAL_SCOPE.node_id,
  revision: 1,
  state: 'ONLINE',
  observed_at: MOCK_OBSERVED_AT,
  freshness: MOCK_FRESHNESS,
  components: [
    {
      component_id: 'hypervisor-local',
      component_type: 'Hypervisor',
      kind: 'hypervisor',
      state: 'RUNNING',
      observed_at: MOCK_OBSERVED_AT,
      freshness: MOCK_FRESHNESS,
      source: 'probe.hypervisor',
    },
    {
      component_id: 'primary-agent-local',
      component_type: 'Primary Agent',
      kind: 'primary-agent',
      state: 'ONLINE',
      observed_at: MOCK_OBSERVED_AT,
      freshness: MOCK_FRESHNESS,
      source: 'probe.primary-agent',
    },
    { component_id: 'node-local', component_type: 'Node', kind: 'node', state: 'ONLINE', observed_at: MOCK_OBSERVED_AT, freshness: MOCK_FRESHNESS, source: 'probe.node' },
    { component_id: 'mcp-local', component_type: 'MCP', kind: 'mcp', state: 'READY', observed_at: MOCK_OBSERVED_AT, freshness: MOCK_FRESHNESS, source: 'probe.mcp' },
    { component_id: 'hooks-local', component_type: 'Hooks', kind: 'hooks', state: 'READY', observed_at: MOCK_OBSERVED_AT, freshness: MOCK_FRESHNESS, source: 'probe.hooks', available_actions: ['RETRY_HOOK_DEAD_LETTER'] },
    { component_id: 'network-local', component_type: 'Network', kind: 'network', state: 'ONLINE', observed_at: MOCK_OBSERVED_AT, freshness: MOCK_FRESHNESS, source: 'probe.network' },
    { component_id: 'consensus-local', component_type: 'Consensus', kind: 'consensus', state: 'READY', observed_at: MOCK_OBSERVED_AT, freshness: MOCK_FRESHNESS, source: 'probe.consensus' },
    { component_id: 'wallet-local', component_type: 'Wallet', kind: 'wallet', state: 'READY', observed_at: MOCK_OBSERVED_AT, freshness: MOCK_FRESHNESS, source: 'probe.wallet' },
    { component_id: 'sessions-local', component_type: 'Sessions', kind: 'sessions', state: 'READY', observed_at: MOCK_OBSERVED_AT, freshness: MOCK_FRESHNESS, source: 'probe.sessions' },
    { component_id: 'tasks-local', component_type: 'Tasks', kind: 'tasks', state: 'READY', observed_at: MOCK_OBSERVED_AT, freshness: MOCK_FRESHNESS, source: 'probe.tasks' },
    { component_id: 'endpoints-local', component_type: 'Endpoints', kind: 'endpoints', state: 'READY', observed_at: MOCK_OBSERVED_AT, freshness: MOCK_FRESHNESS, source: 'probe.endpoints' },
    { component_id: 'providers-local', component_type: 'Providers/Runtimes', kind: 'providers', state: 'READY', observed_at: MOCK_OBSERVED_AT, freshness: MOCK_FRESHNESS, source: 'probe.providers' },
    { component_id: 'resources-local', component_type: 'Resources', kind: 'resources', state: 'READY', observed_at: MOCK_OBSERVED_AT, freshness: MOCK_FRESHNESS, source: 'probe.resources' },
  ],
} as const

function mockEntityById(id: string): Record<string, unknown> {
  const entity = mockSpatialWorkspacePayload.entities.find((candidate) => candidate.id === id)
  if (!entity) throw new Error(`Mock Spatial entity fixture is missing: ${id}`)
  return { ...entity }
}

function mockEndpointEvent(entityId: string, state: string, availability: string, sequence: number) {
  const entity = mockEntityById(entityId)
  return {
    event_id: `mock-event-${sequence}`,
    event_type: 'spatial.entity.upserted.v1',
    schema_version: 'spatial.entity.v1',
    node_id: MOCK_SPATIAL_SCOPE.node_id,
    sequence,
    revision: sequence,
    occurred_at: MOCK_OBSERVED_AT,
    correlation_id: `mock-correlation-${sequence}`,
    causation_id: null,
    payload: {
      ...entity,
      revision: sequence,
      state,
      availability,
      updated_at: MOCK_OBSERVED_AT,
    },
  } as const
}

/** Retained stream used by M2.7 to exercise DEGRADED → READY recovery. */
export const mockSpatialEventStream = [
  mockEndpointEvent('endpoint-runtime', 'DEGRADED', 'DEGRADED', 2),
  mockEndpointEvent('endpoint-runtime', 'READY', 'AVAILABLE', 3),
] as const

function workspacePayloadForScope(scope: SpatialNodeScope): Record<string, unknown> {
  if (scope.node_id === MOCK_SPATIAL_SCOPE.node_id) return mockSpatialWorkspaceWithPrimaryPayload
  return {
    ...mockSpatialWorkspaceWithPrimaryPayload,
    workspace_id: `workspace-${scope.node_id}`,
    node_id: scope.node_id,
    entities: mockSpatialWorkspaceWithPrimaryPayload.entities.map((entity) => ({ ...entity, node_id: scope.node_id })),
    relations: mockSpatialWorkspaceWithPrimaryPayload.relations.map((relation) => ({ ...relation, node_id: scope.node_id })),
  }
}

function statusPayloadForScope(scope: SpatialNodeScope): Record<string, unknown> {
  if (scope.node_id === MOCK_SPATIAL_SCOPE.node_id) return mockSpatialNodeStatusPayload
  return {
    ...mockSpatialNodeStatusPayload,
    node_id: scope.node_id,
    components: mockSpatialNodeStatusPayload.components.map((component) => ({ ...component, component_id: `${component.component_id}-${scope.node_id}` })),
  }
}

export function createMockSpatialWorkspaceSnapshot(scope: SpatialNodeScope = MOCK_SPATIAL_SCOPE): SpatialWorkspaceSnapshot {
  const parsed = parseSpatialWorkspace(workspacePayloadForScope(scope))
  if (!parsed.ok) throw new Error('Mock Spatial Workspace fixture is invalid.')
  return parsed.data
}

export function createMockSpatialNodeStatus(scope: SpatialNodeScope = MOCK_SPATIAL_SCOPE): SpatialNodeStatus {
  const parsed = parseSpatialNodeStatus(statusPayloadForScope(scope))
  if (!parsed.ok) throw new Error('Mock Spatial Node status fixture is invalid.')
  return parsed.data
}

export function createMockSpatialPresentation(deviceId = 'device-local', scope: SpatialNodeScope = MOCK_SPATIAL_SCOPE): SpatialViewportSnapshot {
  const snapshot = createMockSpatialWorkspaceSnapshot(scope)
  const presentation = createSpatialPresentationSnapshot(snapshot, deviceId, 'DESKTOP', new Date(MOCK_OBSERVED_AT))
  const parsed = parseSpatialViewport(presentation)
  if (!parsed.ok) throw new Error('Mock Spatial viewport fixture is invalid.')
  return parsed.data
}
