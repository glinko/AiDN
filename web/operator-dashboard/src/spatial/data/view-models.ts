import type {
  SpatialAgentEntity,
  SpatialCanonicalEntity,
  SpatialNodeStatus,
  SpatialRelationContract,
  SpatialSemanticAnchor,
  SpatialWorkspaceSnapshot,
} from '@/spatial/contracts'

import {
  primaryAgentVisual,
  type PrimaryAgentState,
} from '../prototype/primary-agent'
import type { SpatialQualityProfile } from '../prototype/environment'
import type { SpatialEntity, SpatialEntityKind, SpatialRelation } from '../prototype/entities'

export type SpatialVisualState = 'healthy' | 'attention' | 'critical' | 'offline' | 'unknown'
export type SpatialFamiliarity = 'unseen' | 'known' | 'trusted_by_history'
export type SpatialActivity = 'idle' | 'working' | 'streaming'

export type SpatialEntityViewModel = SpatialEntity & {
  canonicalRef: string
  canonicalKind: SpatialCanonicalEntity['kind']
  sourceRevision: number
  provenanceRef: string
  visualState: SpatialVisualState
  familiarity: SpatialFamiliarity
  activity: SpatialActivity
  availability: SpatialCanonicalEntity['availability']
  freshnessState: SpatialCanonicalEntity['freshness']['state']
  freshnessLabel: string
  emphasis: number
  lodHint: 'full' | 'reduced' | 'placeholder'
}

export type SpatialAgentViewModel = SpatialEntityViewModel & { canonicalKind: 'agent' }
export type SpatialEndpointViewModel = SpatialEntityViewModel & { canonicalKind: 'endpoint' }
export type SpatialSessionArtifactViewModel = SpatialEntityViewModel & { canonicalKind: 'session' | 'artifact' }
export type SpatialAttentionViewModel = SpatialEntityViewModel & { canonicalKind: 'attention' }

export type SpatialNodeStatusViewModel = {
  nodeId: string
  state: SpatialNodeStatus['state']
  availability: 'available' | 'degraded' | 'offline' | 'unknown'
  freshnessState: SpatialNodeStatus['freshness']['state']
  freshnessLabel: string
  sourceRevision: number
  componentCount: number
}

export type SpatialPrimaryAgentViewModel = {
  id: string
  canonicalRef: string
  state: PrimaryAgentState
  label: string
  detail: string
  availability: SpatialCanonicalEntity['availability']
  freshnessState: SpatialCanonicalEntity['freshness']['state']
  sourceRevision: number
  lodHint: 'full' | 'reduced' | 'placeholder'
}

export type SpatialWorkspaceViewModel = {
  entities: SpatialEntityViewModel[]
  relations: SpatialRelation[]
  primaryAgent: SpatialPrimaryAgentViewModel | null
  nodeStatus: SpatialNodeStatus | null
  nodeStatusViewModel: SpatialNodeStatusViewModel | null
  sourceRevision: number
  freshnessState: SpatialNodeStatus['freshness']['state'] | 'UNKNOWN'
  dataState: 'ready' | 'partial' | 'stale' | 'offline' | 'empty'
}

function positionHash(value: string): number {
  let hash = 2166136261
  for (const char of value) hash = Math.imul(hash ^ char.charCodeAt(0), 16777619)
  return Math.abs(hash >>> 0)
}

function fallbackPosition(canonicalRef: string, kind: SpatialCanonicalEntity['kind']): { x: number; y: number; z: number } {
  const hash = positionHash(canonicalRef)
  const angle = (hash % 360) * (Math.PI / 180)
  const radius = kind === 'attention' ? 3.8 : kind === 'endpoint' ? 3.2 : 2.35
  return {
    x: Number((Math.cos(angle) * radius).toFixed(3)),
    y: Number((Math.sin(angle) * radius * 0.58).toFixed(3)),
    z: Number((-2.5 - (hash % 240) / 100).toFixed(3)),
  }
}

function anchorFor(entity: SpatialCanonicalEntity, anchors: readonly SpatialSemanticAnchor[]): SpatialSemanticAnchor | undefined {
  return anchors.find((anchor) => anchor.canonical_ref === entity.canonical_ref)
}

function projectedKind(kind: SpatialCanonicalEntity['kind']): SpatialEntityKind {
  switch (kind) {
    case 'agent': return 'subagent'
    case 'endpoint': return 'endpoint'
    case 'service': return 'service'
    case 'session': return 'session'
    case 'artifact': return 'artifact'
    case 'attention': return 'attention'
  }
}

function visualState(entity: SpatialCanonicalEntity): SpatialVisualState {
  if (entity.availability === 'UNAVAILABLE' || entity.state.includes('OFFLINE') || entity.state.includes('DISCONNECT')) return 'offline'
  if (entity.availability === 'UNKNOWN' || entity.freshness.state === 'UNKNOWN') return 'unknown'
  if (entity.state.includes('CRITICAL') || entity.kind === 'attention' && entity.severity === 'CRITICAL') return 'critical'
  if (entity.availability === 'DEGRADED' || entity.freshness.state === 'STALE' || entity.freshness.state === 'PARTIAL') return 'attention'
  return 'healthy'
}

function activityFor(entity: SpatialCanonicalEntity): SpatialActivity {
  if (entity.state.includes('STREAM')) return 'streaming'
  if (entity.state.includes('WORK') || entity.state.includes('RUN') || entity.state.includes('ACTIVE')) return 'working'
  return 'idle'
}

function freshnessLabel(state: SpatialCanonicalEntity['freshness']['state']): string {
  switch (state) {
    case 'FRESH': return 'Fresh evidence'
    case 'STALE': return 'Stale evidence'
    case 'PARTIAL': return 'Partial evidence'
    case 'UNKNOWN': return 'Freshness unknown'
    case 'UNAVAILABLE': return 'Evidence unavailable'
  }
}

function statusFreshnessLabel(state: SpatialNodeStatus['freshness']['state']): string {
  return freshnessLabel(state)
}

export function toSpatialNodeStatusViewModel(status: SpatialNodeStatus): SpatialNodeStatusViewModel {
  const availability = status.freshness.state === 'UNAVAILABLE' || status.state === 'OFFLINE' || status.state === 'DISCONNECTED'
    ? 'offline'
    : status.state === 'DEGRADED' || status.state === 'STALE' || status.freshness.state === 'STALE' || status.freshness.state === 'PARTIAL'
      ? 'degraded'
      : status.state === 'UNKNOWN' || status.freshness.state === 'UNKNOWN'
        ? 'unknown'
        : 'available'
  return {
    nodeId: status.node_id,
    state: status.state,
    availability,
    freshnessState: status.freshness.state,
    freshnessLabel: statusFreshnessLabel(status.freshness.state),
    sourceRevision: status.revision,
    componentCount: status.components.length,
  }
}

function emphasisFor(entity: SpatialCanonicalEntity): number {
  const base = entity.kind === 'attention' ? 0.86 : entity.kind === 'agent' ? 0.72 : entity.kind === 'endpoint' ? 0.58 : 0.46
  const stateBoost = entity.state.includes('ACTIVE') || entity.state.includes('WORK') ? 0.12 : 0
  return Number(Math.min(1, base + stateBoost).toFixed(3))
}

function describeEntity(entity: SpatialCanonicalEntity): string {
  const kind = entity.kind === 'agent' ? 'Agent' : entity.kind[0].toUpperCase() + entity.kind.slice(1)
  return `${kind} · ${entity.state.replaceAll('_', ' ')} · ${entity.availability.replaceAll('_', ' ')}`
}

export function toSpatialEntityViewModel(entity: SpatialCanonicalEntity, anchors: readonly SpatialSemanticAnchor[] = []): SpatialEntityViewModel {
  const anchor = anchorFor(entity, anchors)
  const kind = projectedKind(entity.kind)
  const position = anchor?.position ?? fallbackPosition(entity.canonical_ref, entity.kind)
  const state = visualState(entity)
  const lodHint = entity.availability === 'UNAVAILABLE' || entity.availability === 'UNKNOWN' || entity.freshness.state === 'UNKNOWN' || entity.freshness.state === 'UNAVAILABLE'
    ? 'placeholder'
    : entity.freshness.state === 'STALE' || entity.freshness.state === 'PARTIAL'
      ? 'reduced'
      : 'full'
  return {
    id: entity.id,
    kind,
    label: entity.label,
    description: describeEntity(entity),
    position,
    priority: emphasisFor(entity),
    canonicalRef: entity.canonical_ref,
    canonicalKind: entity.kind,
    sourceRevision: entity.revision,
    provenanceRef: entity.provenance?.canonical_ref ?? entity.canonical_ref,
    visualState: state,
    familiarity: 'unseen',
    activity: activityFor(entity),
    availability: entity.availability,
    freshnessState: entity.freshness.state,
    freshnessLabel: freshnessLabel(entity.freshness.state),
    emphasis: emphasisFor(entity),
    lodHint,
  }
}

export function toAgentViewModel(entity: SpatialAgentEntity, anchors: readonly SpatialSemanticAnchor[] = []): SpatialAgentViewModel {
  return toSpatialEntityViewModel(entity, anchors) as SpatialAgentViewModel
}

export function toEndpointViewModel(entity: Extract<SpatialCanonicalEntity, { kind: 'endpoint' }>, anchors: readonly SpatialSemanticAnchor[] = []): SpatialEndpointViewModel {
  return toSpatialEntityViewModel(entity, anchors) as SpatialEndpointViewModel
}

export function toSessionArtifactViewModel(entity: Extract<SpatialCanonicalEntity, { kind: 'session' | 'artifact' }>, anchors: readonly SpatialSemanticAnchor[] = []): SpatialSessionArtifactViewModel {
  return toSpatialEntityViewModel(entity, anchors) as SpatialSessionArtifactViewModel
}

export function toAttentionViewModel(entity: Extract<SpatialCanonicalEntity, { kind: 'attention' }>, anchors: readonly SpatialSemanticAnchor[] = []): SpatialAttentionViewModel {
  return toSpatialEntityViewModel(entity, anchors) as SpatialAttentionViewModel
}

function primaryState(entity: SpatialAgentEntity): PrimaryAgentState {
  if (entity.availability === 'UNAVAILABLE' || entity.availability === 'UNKNOWN' || entity.freshness.state === 'UNKNOWN' || entity.freshness.state === 'UNAVAILABLE') return 'OFFLINE'
  switch (entity.state) {
    case 'READY':
    case 'LISTENING':
    case 'THINKING':
    case 'ACTING':
    case 'WORKING':
    case 'ATTENTION':
    case 'CRITICAL':
    case 'OFFLINE':
      return entity.state
    default:
      return 'READY'
  }
}

export function toPrimaryAgentViewModel(entity: SpatialAgentEntity, profile: SpatialQualityProfile = 'desktop'): SpatialPrimaryAgentViewModel {
  const state = primaryState(entity)
  const visual = primaryAgentVisual(state, profile)
  return {
    id: entity.id,
    canonicalRef: entity.canonical_ref,
    state,
    label: visual.label,
    detail: visual.detail,
    availability: entity.availability,
    freshnessState: entity.freshness.state,
    sourceRevision: entity.revision,
    lodHint: visual.lod === 'physical' ? 'full' : 'reduced',
  }
}

function relationViewModel(relation: SpatialRelationContract, entities: readonly SpatialEntityViewModel[]): SpatialRelation | null {
  const source = entities.find((entity) => entity.canonicalRef === relation.source_ref)
  const target = entities.find((entity) => entity.canonicalRef === relation.target_ref)
  if (!source || !target) return null
  return {
    id: relation.relation_id,
    sourceId: source.id,
    targetId: target.id,
    label: relation.relation_type.replaceAll('_', ' '),
  }
}

export function composeSpatialWorkspaceViewModel(
  snapshot: SpatialWorkspaceSnapshot,
  nodeStatus: SpatialNodeStatus | null = null,
  profile: SpatialQualityProfile = 'desktop',
): SpatialWorkspaceViewModel {
  const unique = new Map<string, SpatialCanonicalEntity>()
  for (const entity of snapshot.entities) {
    if (!unique.has(entity.canonical_ref)) unique.set(entity.canonical_ref, entity)
  }
  const primary = snapshot.primary_agent_ref
    ? [...unique.values()].find((entity): entity is SpatialAgentEntity => entity.kind === 'agent' && entity.canonical_ref === snapshot.primary_agent_ref)
    : [...unique.values()].find((entity): entity is SpatialAgentEntity => entity.kind === 'agent' && entity.role === 'PRIMARY')
  // The central Primary Agent presence is rendered by its dedicated slot. Keep
  // it out of the general entity projection so duplicate canonical references
  // can never create a second visual presence.
  const entities = [...unique.values()]
    .filter((entity) => !primary || entity.canonical_ref !== primary.canonical_ref)
    .map((entity) => toSpatialEntityViewModel(entity, snapshot.semantic_anchors))
  const relations = snapshot.relations.map((relation) => relationViewModel(relation, entities)).filter((relation): relation is SpatialRelation => Boolean(relation))
  const primaryAgent = primary ? toPrimaryAgentViewModel(primary, profile) : null
  const freshnessState = nodeStatus?.freshness.state ?? snapshot.entities[0]?.freshness.state ?? 'UNKNOWN'
  const dataState = snapshot.entities.length === 0
    ? 'empty'
    : freshnessState === 'UNAVAILABLE'
      ? 'offline'
      : freshnessState === 'STALE'
        ? 'stale'
        : freshnessState === 'PARTIAL'
          ? 'partial'
          : 'ready'
  return {
    entities,
    relations,
    primaryAgent,
    nodeStatus,
    nodeStatusViewModel: nodeStatus ? toSpatialNodeStatusViewModel(nodeStatus) : null,
    sourceRevision: snapshot.semantic_revision,
    freshnessState,
    dataState,
  }
}
