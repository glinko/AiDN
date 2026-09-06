import { useMemo, useState } from 'react'

import { isSpatialMemoryEnabled } from '@/lib/feature-flags'
import { Button, GlassFrame, Input, StatusLabel } from '@/spatial/primitives'
import type { SpatialWorkspaceData } from '@/spatial/data'

import {
  SpatialMemoryEngine,
  type MemoryCamera,
  type SpatialMemoryRecord,
  type SpatialMemoryRelation,
} from './engine'

type SpatialMemorySurfaceProps = {
  workspaceData: SpatialWorkspaceData
  prefersReducedMotion?: boolean
}

const FIXTURE_NOW = new Date('2026-09-05T16:00:00.000Z')

function recordsForWorkspace(workspaceData: SpatialWorkspaceData): SpatialMemoryRecord[] {
  const entities = workspaceData.projection.entities
  const primary = workspaceData.projection.primaryAgent
  const entityRecords = entities.map((entity, index) => ({
    semanticRef: entity.canonicalRef,
    objectType: entity.canonicalKind,
    label: entity.label,
    summary: entity.description,
    workspaceId: `workspace-${workspaceData.scope.node_id}`,
    createdAt: new Date(FIXTURE_NOW.getTime() - (index + 1) * 3_600_000),
    lastActiveAt: new Date(FIXTURE_NOW.getTime() - index * 3_600_000),
    relevanceScore: entity.emphasis,
    unresolved: entity.canonicalKind === 'attention',
    active: entity.activity !== 'idle',
    sourceRevision: entity.sourceRevision,
    provenanceRef: entity.provenanceRef,
    available: entity.availability !== 'UNAVAILABLE',
    stale: entity.freshnessState === 'STALE' || entity.freshnessState === 'PARTIAL',
    metadata: {
      project: entity.canonicalKind === 'artifact' || entity.canonicalKind === 'session' ? 'AiDN Workspace' : undefined,
      endpointRef: entity.canonicalKind === 'endpoint' ? entity.canonicalRef : undefined,
      subsystem: entity.canonicalKind === 'service' ? entity.label : undefined,
    },
  }))
  if (!primary) return entityRecords
  return [{
    semanticRef: primary.canonicalRef,
    objectType: 'agent',
    label: primary.label,
    summary: primary.detail,
    workspaceId: `workspace-${workspaceData.scope.node_id}`,
    createdAt: FIXTURE_NOW,
    lastActiveAt: FIXTURE_NOW,
    active: true,
    relevanceScore: 1,
    sourceRevision: primary.sourceRevision,
    available: primary.availability !== 'UNAVAILABLE',
  }, ...entityRecords]
}

function relationsForWorkspace(workspaceData: SpatialWorkspaceData): SpatialMemoryRelation[] {
  const byId = new Map(workspaceData.projection.entities.map((entity) => [entity.id, entity.canonicalRef]))
  return workspaceData.projection.relations.flatMap((relation) => {
    const sourceRef = byId.get(relation.sourceId)
    const targetRef = byId.get(relation.targetId)
    return sourceRef && targetRef ? [{ id: relation.id, sourceRef, targetRef, type: relation.label, label: relation.label }] : []
  })
}

function cameraForFocus(selectedRef: string | null): MemoryCamera {
  return { x: 0, y: 0, zoom: 1, focusRef: selectedRef }
}

/** M8 DOM memory surface. It exposes the projection, never canonical authority. */
export function SpatialMemorySurface({ workspaceData, prefersReducedMotion = false }: SpatialMemorySurfaceProps) {
  const [selectedRef, setSelectedRef] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [revision, setRevision] = useState(0)
  const [feedback, setFeedback] = useState('Memory is a presentation projection; aging and focus never delete semantic history.')
  const records = useMemo(() => recordsForWorkspace(workspaceData), [workspaceData])
  const relations = useMemo(() => relationsForWorkspace(workspaceData), [workspaceData])
  const engine = useMemo(() => {
    const next = new SpatialMemoryEngine({
      workspaceId: `workspace-${workspaceData.scope.node_id}`,
      primaryAgentRef: workspaceData.projection.primaryAgent?.canonicalRef ?? null,
      seed: `workspace-${workspaceData.scope.node_id}`,
      visibleRecentBudget: 8,
      renderBudget: 30,
      viewport: { width: 960, height: 720 },
      now: FIXTURE_NOW,
    }, records)
    next.planVirtualization({ x: 0, y: 0, radius: 12, revision: workspaceData.projection.sourceRevision })
    return next
  }, [records, workspaceData.projection.primaryAgent?.canonicalRef, workspaceData.projection.sourceRevision, workspaceData.scope.node_id])
  const projections = engine.projections()
  const recent = engine.visibleRecent()
  const clusters = engine.clusters()
  const search = query.trim() ? engine.search(query, { limit: 12 }) : null
  const selected = selectedRef ? engine.projection(selectedRef) : null
  const revealedRelations = selectedRef ? engine.revealRelations(selectedRef, relations) : []
  const telemetry = engine.telemetrySnapshot()

  const refresh = () => setRevision((value) => value + 1)
  const focus = (semanticRef: string) => {
    const requested = engine.requestFocus(semanticRef, { camera: cameraForFocus(selectedRef), source: query.trim() ? 'SEARCH' : 'KEYBOARD', reducedMotion: prefersReducedMotion })
    const focused = requested.state === 'REQUESTED' ? engine.completeFocus() : requested
    setSelectedRef(semanticRef)
    setFeedback(focused?.state === 'UNAVAILABLE'
      ? `${semanticRef} is unavailable; its canonical reference and reason remain searchable.`
      : `${engine.projection(semanticRef)?.label ?? semanticRef} focused temporarily; World Space position is preserved.`)
    refresh()
  }

  if (!isSpatialMemoryEnabled()) return null

  return (
    <section className="aidn-spatial-memory-surface" data-aidn-m8-memory aria-labelledby="m8-memory-title">
      <div className="aidn-spatial-memory-heading">
        <div>
          <StatusLabel status="ready">M8 · Memory</StatusLabel>
          <h3 id="m8-memory-title">Long-lived spatial memory</h3>
        </div>
        <span className="aidn-spatial-memory-budget" data-aidn-m8-render-budget>{telemetry.materializedCount}/{telemetry.renderBudget} full objects</span>
      </div>
      <p className="aidn-spatial-topology-muted">Preferred regions, aging, clusters and LOD stay presentation-only over Node-owned semantic references.</p>

      <form className="aidn-spatial-memory-search" onSubmit={(event) => { event.preventDefault(); refresh(); }} role="search">
        <label htmlFor="m8-memory-search">Search history</label>
        <Input id="m8-memory-search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="project, Endpoint, topic or session" aria-describedby="m8-memory-search-hint" />
        <Button type="submit" size="sm" variant="outline" accent="cyan">Find</Button>
        <span id="m8-memory-search-hint" className="aidn-spatial-memory-hint">Metadata fallback · references only</span>
      </form>

      <div className="aidn-spatial-memory-grid">
        <GlassFrame depth="raised" glass="soft" accent="violet" radius="medium">
          <div className="aidn-spatial-topology-card-heading"><span>Preferred regions</span><span>{projections.length} refs</span></div>
          <ul className="aidn-spatial-memory-region-list">
            {engine.layout().anchors.map((anchor) => <li key={anchor.region}><span>{anchor.region.replaceAll('_', ' ')}</span><small>{projections.filter((projection) => projection.zone === anchor.region).length} objects</small></li>)}
          </ul>
          <div className="aidn-spatial-control-actions">
            <Button size="sm" variant="outline" accent="violet" onClick={() => { engine.resetLayout(); setFeedback('Layout reset to deterministic semantic anchors; canonical topology was untouched.'); refresh() }}>Reset layout</Button>
            {selectedRef ? <Button size="sm" variant="ghost" accent="cyan" onClick={() => { engine.returnFromFocus(); setFeedback('Returned to the prior viewport projection.'); refresh() }}>Return focus</Button> : null}
          </div>
        </GlassFrame>

        <GlassFrame depth="raised" glass="soft" accent="cyan" radius="medium">
          <div className="aidn-spatial-topology-card-heading"><span>Recent Memory</span><span>{recent.length} visible</span></div>
          {recent.length === 0 ? <p className="aidn-spatial-topology-muted">No recent artifacts.</p> : <ul className="aidn-spatial-memory-object-list">
            {recent.slice(0, 12).map((projection) => <li key={projection.semantic_ref.canonical_ref} data-aidn-m8-memory-level={projection.memory_level}>
              <button type="button" className="aidn-spatial-memory-object" onClick={() => focus(projection.semantic_ref.canonical_ref)}>
                <span><strong>{projection.label}</strong><small>{projection.memory_level.toLowerCase()} · LOD{projection.lod}{projection.pinned ? ' · pinned' : ''}</small></span>
                <span aria-hidden="true">→</span>
              </button>
            </li>)}
          </ul>}
        </GlassFrame>

        <GlassFrame depth="raised" glass="soft" accent="amber" radius="medium">
          <div className="aidn-spatial-topology-card-heading"><span>Clusters</span><span>{clusters.length} promoted</span></div>
          {clusters.length === 0 ? <p className="aidn-spatial-topology-muted">Clusters appear after shared project, topic or context evidence.</p> : <ul className="aidn-spatial-memory-object-list">
            {clusters.slice(0, 8).map((cluster) => <li key={cluster.cluster_id}><div className="aidn-spatial-memory-cluster"><strong>{cluster.title}</strong><small>{cluster.criterion.toLowerCase().replaceAll('_', ' ')} · {cluster.member_refs.length} members · {cluster.evidence[0]}</small>{cluster.stale_member_refs.length ? <small className="aidn-spatial-memory-stale">{cluster.stale_member_refs.length} stale member retained</small> : null}</div></li>)}
          </ul>}
        </GlassFrame>
      </div>

      {search ? <GlassFrame depth="raised" glass="soft" accent="blue" radius="medium" className="aidn-spatial-memory-search-results">
        <div className="aidn-spatial-topology-card-heading"><span>Search result frame</span><span>{search.results.length} matches</span></div>
        {search.results.length === 0 ? <p className="aidn-spatial-topology-muted">No authorized metadata match.</p> : <ul className="aidn-spatial-memory-object-list">
          {search.results.map((result) => <li key={result.result_ref.canonical_ref}><button type="button" className="aidn-spatial-memory-object" onClick={() => focus(result.result_ref.canonical_ref)}><span><strong>{result.label}</strong><small>{result.result_ref.canonical_ref} · {result.evidence.join(', ')}</small></span><span>{result.state.toLowerCase()}</span></button></li>)}
        </ul>}
      </GlassFrame> : null}

      <details className="aidn-spatial-memory-relation-details">
        <summary>Reveal semantic relations ({revealedRelations.length})</summary>
        {selected ? <p className="aidn-spatial-memory-hint">Focused {selected.label}; relation reveal changes only the presentation.</p> : <p className="aidn-spatial-memory-hint">Select a memory object to reveal its relation labels.</p>}
        {revealedRelations.length ? <ul className="aidn-spatial-memory-relation-list">{revealedRelations.map((relation) => <li key={relation.id}><span>{relation.accessibleText}</span><small>{relation.sourceOffscreen || relation.targetOffscreen ? 'offscreen anchor available' : 'in view'}</small></li>)}</ul> : null}
      </details>
      <p className="aidn-spatial-topology-feedback" role="status" aria-live="polite">{feedback}</p>
      <p className="aidn-spatial-memory-telemetry" data-aidn-m8-telemetry>LOD0 {telemetry.lodCounts.lod0} · LOD1 {telemetry.lodCounts.lod1} · LOD2 {telemetry.lodCounts.lod2} · LOD3 {telemetry.lodCounts.lod3} · virtualized {telemetry.virtualizedCount}</p>
      <span className="sr-only" data-aidn-m8-revision>{revision}</span>
    </section>
  )
}
