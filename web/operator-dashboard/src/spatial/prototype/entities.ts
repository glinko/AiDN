import type { SpatialQualityProfile } from './environment'

export type SpatialEntityKind = 'subagent' | 'endpoint' | 'service' | 'session' | 'artifact' | 'attention'
export type SpatialEntityLod = 'LOD0' | 'LOD1' | 'LOD2' | 'LOD3'

export type SpatialEntity = {
  id: string
  kind: SpatialEntityKind
  label: string
  description: string
  position: { x: number; y: number; z: number }
  priority: number
}

export type SpatialRelation = {
  id: string
  sourceId: string
  targetId: string
  label: string
}

const subagents: SpatialEntity[] = [
  { id: 'subagent-research', kind: 'subagent', label: 'Research Subagent', description: 'Synthesizes bounded evidence.', position: { x: -2.5, y: 0.3, z: -1.2 }, priority: 0.78 },
  { id: 'subagent-build', kind: 'subagent', label: 'Build Subagent', description: 'Prepares a reversible implementation.', position: { x: 2.4, y: 0.15, z: -1.5 }, priority: 0.74 },
  { id: 'subagent-verify', kind: 'subagent', label: 'Verify Subagent', description: 'Checks deterministic acceptance evidence.', position: { x: -2.1, y: -1.2, z: -2.4 }, priority: 0.7 },
]

const endpoints: SpatialEntity[] = [
  { id: 'endpoint-browser', kind: 'endpoint', label: 'Browser endpoint', description: 'Mediated browser capability.', position: { x: 3.4, y: 1.1, z: -3.1 }, priority: 0.62 },
  { id: 'endpoint-files', kind: 'endpoint', label: 'Files endpoint', description: 'Scoped local file capability.', position: { x: 3.9, y: 0.2, z: -3.6 }, priority: 0.59 },
  { id: 'endpoint-search', kind: 'endpoint', label: 'Search endpoint', description: 'Cited retrieval capability.', position: { x: 3.3, y: -0.7, z: -4.2 }, priority: 0.56 },
  { id: 'endpoint-speech', kind: 'endpoint', label: 'Speech endpoint', description: 'Voice input/output adapter.', position: { x: 2.6, y: -1.35, z: -3.4 }, priority: 0.54 },
  { id: 'endpoint-ledger', kind: 'endpoint', label: 'Ledger endpoint', description: 'Accounting projection.', position: { x: -3.4, y: 0.9, z: -3.4 }, priority: 0.52 },
  { id: 'endpoint-runtime', kind: 'endpoint', label: 'Runtime endpoint', description: 'Mediated execution capability.', position: { x: -3.8, y: -0.05, z: -3.9 }, priority: 0.58 },
  { id: 'endpoint-events', kind: 'endpoint', label: 'Event endpoint', description: 'Canonical event projection.', position: { x: -3.1, y: -0.95, z: -4.5 }, priority: 0.5 },
]

const artifacts: SpatialEntity[] = [
  { id: 'artifact-plan', kind: 'artifact', label: 'Repair plan', description: 'Compact plan artifact.', position: { x: -1.2, y: 1.5, z: -3.2 }, priority: 0.7 },
  { id: 'artifact-report', kind: 'artifact', label: 'Evidence report', description: 'Cited verification artifact.', position: { x: 0.1, y: 1.8, z: -3.8 }, priority: 0.72 },
  { id: 'artifact-log', kind: 'artifact', label: 'Runtime log', description: 'Read-only execution record.', position: { x: 1.45, y: 1.45, z: -4.3 }, priority: 0.62 },
  { id: 'artifact-notes', kind: 'artifact', label: 'Operator notes', description: 'Local workspace note.', position: { x: -1.7, y: 0.1, z: -4.8 }, priority: 0.48 },
  { id: 'artifact-contract', kind: 'artifact', label: 'Contract snapshot', description: 'Typed boundary snapshot.', position: { x: 0.1, y: -1.25, z: -5.2 }, priority: 0.58 },
  { id: 'artifact-session', kind: 'artifact', label: 'Session artifact', description: 'Restorable conversation result.', position: { x: 1.8, y: -0.8, z: -5.4 }, priority: 0.64 },
]

const attentionMarkers: SpatialEntity[] = [
  { id: 'attention-approval', kind: 'attention', label: 'Approval requested', description: 'A human decision is needed.', position: { x: -4.5, y: 1.65, z: -2.5 }, priority: 0.9 },
  { id: 'attention-freshness', kind: 'attention', label: 'Freshness check', description: 'A source needs revalidation.', position: { x: 4.55, y: 1.65, z: -2.6 }, priority: 0.82 },
  { id: 'attention-offline', kind: 'attention', label: 'Endpoint offline', description: 'A capability is unavailable.', position: { x: 0, y: -1.85, z: -4.8 }, priority: 0.86 },
]

/** Synthetic entities are presentation fixtures only; no API or authority is implied. */
export const spatialEntities: readonly SpatialEntity[] = [
  ...subagents,
  ...endpoints,
  ...artifacts,
  ...attentionMarkers,
]

export const spatialRelations: readonly SpatialRelation[] = [
  { id: 'thread-agent-research', sourceId: 'subagent-research', targetId: 'artifact-report', label: 'produced evidence' },
  { id: 'thread-runtime-plan', sourceId: 'endpoint-runtime', targetId: 'artifact-plan', label: 'informs plan' },
]

export const spatialEntityCounts = {
  subagent: subagents.length,
  endpoint: endpoints.length,
  service: spatialEntities.filter((entity) => entity.kind === 'service').length,
  session: spatialEntities.filter((entity) => entity.kind === 'session').length,
  artifact: artifacts.length,
  attention: attentionMarkers.length,
  relation: spatialRelations.length,
  total: spatialEntities.length,
} as const

export function entityKindLabel(kind: SpatialEntityKind): string {
  switch (kind) {
    case 'subagent': return 'Subagent'
    case 'endpoint': return 'Endpoint'
    case 'service': return 'Service'
    case 'session': return 'Session'
    case 'artifact': return 'Session Artifact'
    case 'attention': return 'Attention Marker'
  }
}

export function spatialEntityLod(distance: number, profile: SpatialQualityProfile): SpatialEntityLod {
  const profileBias = profile === 'low' || profile === 'mobile' ? 1 : 0
  if (distance > 8 - profileBias) return 'LOD0'
  if (distance > 5 - profileBias) return 'LOD1'
  if (distance > 3 - profileBias) return 'LOD2'
  return 'LOD3'
}

export function spatialEntitiesForKind(kind: SpatialEntityKind): readonly SpatialEntity[] {
  return spatialEntities.filter((entity) => entity.kind === kind)
}

export function spatialEntityById(id: string | null | undefined): SpatialEntity | undefined {
  return spatialEntities.find((entity) => entity.id === id)
}
