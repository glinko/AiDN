import { spatialIdSchema } from '@/spatial/contracts'

export type SpatialNodeScope = {
  hypervisor_id: string
  node_id: string
}

export const DEFAULT_SPATIAL_NODE_SCOPE: SpatialNodeScope = {
  hypervisor_id: 'local-hypervisor',
  node_id: 'local-node',
}

export function normalizeSpatialNodeScope(scope: SpatialNodeScope): SpatialNodeScope {
  const hypervisor = spatialIdSchema.parse(scope.hypervisor_id)
  const node = spatialIdSchema.parse(scope.node_id)
  return { hypervisor_id: hypervisor, node_id: node }
}

export function spatialScopeKey(scope: SpatialNodeScope): string {
  const normalized = normalizeSpatialNodeScope(scope)
  return `${normalized.hypervisor_id}:${normalized.node_id}`
}

