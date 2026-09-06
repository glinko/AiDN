import type { SpatialComponentRegistry, SpatialComponentViewport } from '@/spatial/interaction/component-registry'

export const SPATIAL_QUERY_INTENTS = ['show-endpoints', 'inspect-endpoint', 'compare-endpoints', 'show-resources', 'explain-agent', 'show-sessions', 'show-hook-failures'] as const
export type SpatialQueryIntent = (typeof SPATIAL_QUERY_INTENTS)[number]

const queryComponent: Record<SpatialQueryIntent, string> = {
  'show-endpoints': 'endpoint-list',
  'inspect-endpoint': 'endpoint-summary',
  'compare-endpoints': 'endpoint-comparison',
  'show-resources': 'node-resource-summary',
  'explain-agent': 'agent-details',
  'show-sessions': 'session-list',
  'show-hook-failures': 'hook-delivery-summary',
}

export type QueryCompositionPlan = {
  intent: SpatialQueryIntent
  componentId: string
  viewport: SpatialComponentViewport
  reuseKey: string
  detail: 'summary' | 'detail'
  virtualizationRequired: boolean
  maxItems: number
}

export function planSpatialQuery(input: { intent: SpatialQueryIntent; viewport: SpatialComponentViewport; targetRef?: string; registry: SpatialComponentRegistry }): QueryCompositionPlan {
  const componentId = queryComponent[input.intent]
  const resolved = input.registry.resolveForViewport(componentId, input.viewport)
  const virtualization = resolved.record.virtualization
  return {
    intent: input.intent,
    componentId: resolved.record.component_id,
    viewport: input.viewport,
    reuseKey: `${resolved.record.component_id}:${input.targetRef ?? 'workspace'}`,
    detail: input.intent === 'inspect-endpoint' ? 'detail' : 'summary',
    virtualizationRequired: virtualization?.required ?? false,
    maxItems: virtualization?.item_budget ?? 100,
  }
}
