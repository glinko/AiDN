import { normalizeSpatialNodeScope, type SpatialNodeScope } from './scope'

const root = ['spatial'] as const

function scopeKey(scope: SpatialNodeScope) {
  const normalized = normalizeSpatialNodeScope(scope)
  return [...root, normalized.hypervisor_id, normalized.node_id] as const
}

export const spatialQueryKeys = {
  all: root,
  scope: scopeKey,
  nodeStatus: (scope: SpatialNodeScope) => [...scopeKey(scope), 'node-status'] as const,
  agents: (scope: SpatialNodeScope) => [...scopeKey(scope), 'agents'] as const,
  endpoints: (scope: SpatialNodeScope) => [...scopeKey(scope), 'endpoints'] as const,
  sessions: (scope: SpatialNodeScope) => [...scopeKey(scope), 'sessions'] as const,
  resources: (scope: SpatialNodeScope) => [...scopeKey(scope), 'resources'] as const,
  events: (scope: SpatialNodeScope, cursor?: string | null) => [...scopeKey(scope), 'events', cursor ?? 'head'] as const,
  hooks: (scope: SpatialNodeScope) => [...scopeKey(scope), 'hooks'] as const,
  workspace: (scope: SpatialNodeScope) => [...scopeKey(scope), 'workspace'] as const,
  workspacePresentation: (scope: SpatialNodeScope, deviceId = 'local') => [...scopeKey(scope), 'workspace-presentation', deviceId] as const,
  workspaceEntity: (scope: SpatialNodeScope, canonicalRef: string) => [...scopeKey(scope), 'workspace-entity', canonicalRef] as const,
  workspaceRelation: (scope: SpatialNodeScope, relationRef: string) => [...scopeKey(scope), 'workspace-relation', relationRef] as const,
  workspaceWorld: (scope: SpatialNodeScope) => [...scopeKey(scope), 'workspace-world'] as const,
  deviceViewport: (scope: SpatialNodeScope, deviceId = 'local') => [...scopeKey(scope), 'device-viewport', deviceId] as const,
  offlineQueue: (scope: SpatialNodeScope, deviceId = 'local') => [...scopeKey(scope), 'offline-queue', deviceId] as const,
  shareView: (scope: SpatialNodeScope, shareId?: string) => [...scopeKey(scope), 'share-view', shareId ?? 'active'] as const,
  primaryAgentSlot: (scope: SpatialNodeScope) => [...scopeKey(scope), 'primary-agent-slot'] as const,
  primaryAgentState: (scope: SpatialNodeScope) => [...scopeKey(scope), 'primary-agent-state'] as const,
  primaryAgentGrant: (scope: SpatialNodeScope, grantId?: string) => [...scopeKey(scope), 'primary-agent-grant', grantId ?? 'active'] as const,
} as const

export type SpatialQueryKey = ReturnType<typeof spatialQueryKeys.scope>

export type SpatialMutationInvalidation = 'workspace-semantic' | 'workspace-presentation' | 'workspace-world' | 'device-viewport' | 'offline-queue' | 'share-view' | 'entity' | 'relation' | 'status' | 'events' | 'primary-agent-slot' | 'primary-agent-state' | 'primary-agent-grant'

export function spatialInvalidationKeys(scope: SpatialNodeScope, target: SpatialMutationInvalidation): readonly (readonly unknown[])[] {
  switch (target) {
    case 'workspace-semantic':
      return [spatialQueryKeys.workspace(scope), spatialQueryKeys.agents(scope), spatialQueryKeys.endpoints(scope), spatialQueryKeys.sessions(scope)]
    case 'workspace-presentation':
      return [spatialQueryKeys.workspacePresentation(scope)]
    case 'workspace-world':
      return [spatialQueryKeys.workspace(scope), spatialQueryKeys.workspaceWorld(scope)]
    case 'device-viewport':
      return [spatialQueryKeys.deviceViewport(scope)]
    case 'offline-queue':
      return [spatialQueryKeys.offlineQueue(scope)]
    case 'share-view':
      return [spatialQueryKeys.shareView(scope)]
    case 'entity':
      return [spatialQueryKeys.workspace(scope), spatialQueryKeys.agents(scope), spatialQueryKeys.endpoints(scope), spatialQueryKeys.sessions(scope)]
    case 'relation':
      return [spatialQueryKeys.workspace(scope)]
    case 'status':
      return [spatialQueryKeys.nodeStatus(scope)]
    case 'events':
      return [spatialQueryKeys.events(scope)]
    case 'primary-agent-slot':
      return [spatialQueryKeys.primaryAgentSlot(scope), spatialQueryKeys.agents(scope)]
    case 'primary-agent-state':
      return [spatialQueryKeys.primaryAgentState(scope), spatialQueryKeys.primaryAgentSlot(scope)]
    case 'primary-agent-grant':
      return [spatialQueryKeys.primaryAgentGrant(scope), spatialQueryKeys.primaryAgentSlot(scope)]
  }
}
