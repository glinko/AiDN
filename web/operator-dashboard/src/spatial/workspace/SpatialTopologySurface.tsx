import { useMemo, useState } from 'react'

import { Button, GlassFrame, StatusLabel } from '@/spatial/primitives'
import { isSpatialChangeIntentEnabled, isSpatialRemoteMediationEnabled } from '@/lib/feature-flags'
import { EndpointTestFrame } from '@/spatial/remote'
import { EndpointSummary } from '@/components/shared/EndpointSummary'
import { endpointSummaryFromSpatial } from '@/components/shared/endpoint-summary-model'
import { EndpointConfiguration } from '@/components/shared/EndpointConfiguration'
import {
  AttentionFocusController,
  AttentionQueueService,
  CanonicalReferenceRegistry,
  EndpointDiscoveryService,
  InteractionProvenanceService,
  OrbitalAttentionMarkerService,
  SemanticRelationService,
  SubagentLifecycleService,
  toEndpointEnergyObject,
  type SpatialWorkspaceData,
} from '@/spatial/data'
import {
  SPATIAL_SCHEMA_VERSIONS,
  type SpatialEndpointDetails,
} from '@/spatial/contracts'

type SpatialTopologySurfaceProps = {
  workspaceData: SpatialWorkspaceData
  prefersReducedMotion?: boolean
}

function endpointDetailsForEntity(entity: SpatialWorkspaceData['projection']['entities'][number], nodeId: string): SpatialEndpointDetails {
  const observedAt = new Date().toISOString()
  return {
    schema_version: SPATIAL_SCHEMA_VERSIONS.endpointDetails,
    workspace_id: `workspace-${nodeId}`,
    node_id: nodeId,
    canonical_ref: entity.canonicalRef,
    endpoint_id: entity.id,
    revision: entity.sourceRevision,
    display_name: entity.label,
    capability: entity.description,
    endpoint_type: 'mediated-capability',
    supported_modalities: ['text', 'form'],
    availability: entity.availability,
    surface_state: entity.freshnessState === 'UNAVAILABLE' ? 'UNAVAILABLE' : entity.freshnessState === 'STALE' ? 'STALE' : entity.freshnessState === 'PARTIAL' ? 'PARTIAL' : 'READY',
    freshness: {
      state: entity.freshnessState,
      observed_at: observedAt,
      stale_after_seconds: 900,
      source: entity.provenanceRef,
    },
    latency: { p50_ms: null, p95_ms: null, measured_at: null, window: null },
    load: null,
    capacity: null,
    cost: { currency: null, unit_price: null, billing_dimension: null, minimum_charge: null },
    deposit: { minimum: null, recommended: null, currency: null, escrow: null },
    provider_ref: null,
    remote_agent_ref: null,
    validation_refs: [],
    input_formats: ['text/plain'],
    output_formats: ['text/plain'],
    limits: { context_tokens: null, payload_bytes: null, timeout_ms: null, streaming: null },
    privacy: 'Node-mediated; remote output is data, not authority.',
    trust_summary: 'Authorization remains outside the presentation surface.',
    description: entity.description,
    allowed_actions: ['inspect', 'show-provenance'],
  }
}

/** M5 DOM surface: inspect/discover without turning projections into authority. */
export function SpatialTopologySurface({ workspaceData, prefersReducedMotion = false }: SpatialTopologySurfaceProps) {
  const [discoveryRevision, setDiscoveryRevision] = useState(0)
  const [selectedEndpoint, setSelectedEndpoint] = useState<SpatialEndpointDetails | null>(null)
  const [feedback, setFeedback] = useState('Autonomous events stay in the bounded attention queue; the camera does not move.')
  const services = useMemo(() => {
    const registry = new CanonicalReferenceRegistry({ workspaceId: `workspace-${workspaceData.scope.node_id}`, nodeId: workspaceData.scope.node_id })
    const entities = workspaceData.projection.entities
    if (workspaceData.projection.primaryAgent) {
      registry.discover({
        canonicalRef: workspaceData.projection.primaryAgent.canonicalRef,
        entityId: workspaceData.projection.primaryAgent.id,
        entityKind: 'agent',
        revision: workspaceData.projection.primaryAgent.sourceRevision,
      })
    }
    const endpoints = entities.filter((entity) => entity.canonicalKind === 'endpoint').map((entity) => {
      const details = endpointDetailsForEntity(entity, workspaceData.scope.node_id)
      registry.discover({ canonicalRef: details.canonical_ref, entityId: details.endpoint_id, entityKind: 'endpoint', revision: details.revision })
      return details
    })
    for (const entity of entities.filter((candidate) => candidate.canonicalKind === 'agent')) {
      registry.discover({ canonicalRef: entity.canonicalRef, entityId: entity.id, entityKind: 'agent', revision: entity.sourceRevision })
    }
    const discovery = new EndpointDiscoveryService({ workspaceId: `workspace-${workspaceData.scope.node_id}`, nodeId: workspaceData.scope.node_id, registry, maxCandidates: 100 })
    const relations = new SemanticRelationService({ workspaceId: `workspace-${workspaceData.scope.node_id}`, nodeId: workspaceData.scope.node_id, registry })
    const primary = workspaceData.projection.primaryAgent?.canonicalRef
    const byId = new Map(entities.map((entity) => [entity.id, entity.canonicalRef]))
    if (primary) {
      for (const relation of workspaceData.projection.relations) {
        const sourceRef = byId.get(relation.sourceId)
        const targetRef = byId.get(relation.targetId)
        if (sourceRef && targetRef) {
          try {
            relations.upsert({ relationId: relation.id, relationType: 'PRODUCED', sourceRef, targetRef, sourceRevision: 0, targetRevision: 0, label: relation.label })
          } catch {
            // A partial snapshot may contain a relation whose entity is not retained.
          }
        }
      }
    }
    const queue = new AttentionQueueService({ workspaceId: `workspace-${workspaceData.scope.node_id}`, nodeId: workspaceData.scope.node_id, targetAgentRef: primary ?? 'agent:primary' })
    for (const entity of entities.filter((candidate) => candidate.canonicalKind === 'attention')) {
      queue.raise({ sourceEventRef: `fixture:${entity.canonicalRef}`, subjectRef: entity.canonicalRef, severity: 'ATTENTION', summary: entity.label, groupingKey: 'fixture-attention' })
    }
    const focus = new AttentionFocusController({ workspaceId: `workspace-${workspaceData.scope.node_id}`, nodeId: workspaceData.scope.node_id, queue, sourceAvailable: () => true })
    const provenance = new InteractionProvenanceService({ workspaceId: `workspace-${workspaceData.scope.node_id}`, nodeId: workspaceData.scope.node_id, primaryAgentRef: primary ?? 'agent:primary' })
    const subagents = new SubagentLifecycleService({ workspaceId: `workspace-${workspaceData.scope.node_id}`, nodeId: workspaceData.scope.node_id, primaryAgentRef: primary ?? 'agent:primary', registry, relations, authorizeRemoteAccess: ({ subagentRef, capability }) => Boolean(subagentRef && capability) })
    return { registry, endpoints, discovery, relations, queue, focus, provenance, subagents }
  }, [workspaceData])
  const discovery = useMemo(() => services.discovery.discover({ requestId: `workspace-discovery-${discoveryRevision}`, endpoints: services.endpoints, relevance: Object.fromEntries(services.endpoints.map((endpoint, index) => [endpoint.canonical_ref, 1 - index / Math.max(services.endpoints.length, 1)])) }), [discoveryRevision, services])
  const attentionItems = services.queue.list()
  const markers = useMemo(() => {
    const markerService = new OrbitalAttentionMarkerService({ workspaceId: `workspace-${workspaceData.scope.node_id}`, nodeId: workspaceData.scope.node_id, reducedMotion: prefersReducedMotion })
    return markerService.project(attentionItems)
  }, [attentionItems, prefersReducedMotion, workspaceData.scope.node_id])
  const [focusedAttention, setFocusedAttention] = useState<string | null>(null)
  const selectedExperience = selectedEndpoint ? services.provenance.getExperience(selectedEndpoint.endpoint_id) : null

  return (
    <section className="aidn-spatial-topology-surface" data-aidn-m5-topology aria-labelledby="m5-topology-title">
      <div className="aidn-spatial-topology-heading">
        <div>
          <StatusLabel status="ready">M5 · Topology</StatusLabel>
          <h3 id="m5-topology-title">Endpoints & attention</h3>
        </div>
        <Button size="sm" variant="outline" accent="cyan" onClick={() => setDiscoveryRevision((revision) => revision + 1)}>Discover</Button>
      </div>
      <div className="aidn-spatial-topology-grid">
        <GlassFrame depth="raised" glass="soft" accent="cyan" radius="medium">
          <div className="aidn-spatial-topology-card-heading"><span>Endpoint Arc</span><span>{discovery.candidates.length} candidates</span></div>
          {discovery.candidates.length === 0 ? <p className="aidn-spatial-topology-muted">No candidates. Nothing is invoked by discovery.</p> : (
            <ul className="aidn-spatial-topology-list">
              {discovery.candidates.slice(0, 7).map((candidate) => {
                const energy = toEndpointEnergyObject(candidate.details, services.provenance.getExperience(candidate.endpoint_ref).familiarity, selectedEndpoint?.canonical_ref === candidate.canonical_ref)
                return <li key={candidate.candidate_id} data-aidn-endpoint-candidate={candidate.state}>
                  <button type="button" className="aidn-spatial-topology-list-item" onClick={() => { services.discovery.select(discovery.discovery_id, candidate.candidate_id); setSelectedEndpoint(candidate.details); setFeedback(`Selected ${candidate.details.display_name}; explicit intent is still required.`) }}>
                    <span className="aidn-spatial-energy-glyph" data-aidn-energy-availability={energy.availability} aria-hidden="true">◇</span>
                    <span><strong>{candidate.rank}. {candidate.details.display_name}</strong><small>{candidate.explanation}</small></span>
                  </button>
                </li>
              })}
            </ul>
          )}
          <p className="aidn-spatial-topology-muted">Selection promotes one canonical presence; a discovery projection is never an extra entity.</p>
        </GlassFrame>
        <GlassFrame depth="raised" glass="soft" accent="violet" radius="medium">
          <div className="aidn-spatial-topology-card-heading"><span>Endpoint details</span><span>{selectedEndpoint ? `rev ${selectedEndpoint.revision}` : 'read-only'}</span></div>
          {selectedEndpoint ? <>
            <EndpointSummary model={endpointSummaryFromSpatial(selectedEndpoint)} variant="spatial" />
            {isSpatialChangeIntentEnabled() ? <EndpointConfiguration
              workspaceId={`workspace-${workspaceData.scope.node_id}`}
              nodeId={workspaceData.scope.node_id}
              endpointRef={selectedEndpoint.canonical_ref}
              revision={selectedEndpoint.revision}
              actorRef="operator:spatial"
              variant="spatial"
              initialPort={null}
              capabilities={['endpoint:change']}
              onIntent={(intent, validation) => setFeedback(`${intent.intent_id}: ${validation.state}. Agent validation remains the canonical gate.`)}
              onApply={(result) => setFeedback(`${result.intent.target.id}: applied at revision ${result.revision}; result ${result.resultRef}.`)}
            /> : null}
            <dl className="aidn-spatial-topology-details">
            <div><dt>State</dt><dd>{selectedEndpoint.surface_state} · {selectedEndpoint.availability} · {selectedEndpoint.freshness.state}</dd></div>
            <div><dt>Latency</dt><dd>{selectedEndpoint.latency.p95_ms === null ? 'Unknown' : `${selectedEndpoint.latency.p95_ms} ms`}</dd></div>
            <div><dt>Load / cost</dt><dd>{selectedEndpoint.load === null ? 'Unknown' : `${Math.round(selectedEndpoint.load * 100)}%`} · {selectedEndpoint.cost.unit_price === null ? 'Unknown' : selectedEndpoint.cost.unit_price}</dd></div>
            <div><dt>Familiarity</dt><dd>{selectedExperience?.familiarity ?? 'NEVER_USED'} · local history only</dd></div>
            <div><dt>Provenance</dt><dd>{selectedEndpoint.provider_ref ?? 'Node-mediated reference'}</dd></div>
            <div><dt>Formats</dt><dd>{selectedEndpoint.input_formats.join(', ')} → {selectedEndpoint.output_formats.join(', ')}</dd></div>
            </dl>
          </> : <p className="aidn-spatial-topology-muted">Select a candidate to inspect source revision and freshness.</p>}
        </GlassFrame>
        <GlassFrame depth="raised" glass="soft" accent="amber" radius="medium">
          <div className="aidn-spatial-topology-card-heading"><span>Attention orbit</span><span>{attentionItems.length} unread · {markers.length} markers</span></div>
          {attentionItems.length === 0 ? <p className="aidn-spatial-topology-muted">No autonomous attention items.</p> : <ul className="aidn-spatial-topology-list">
            {attentionItems.slice(0, 8).map((item) => <li key={item.attention_id} data-aidn-attention-state={item.state}>
              <button type="button" className="aidn-spatial-topology-list-item" onClick={() => { const focus = services.focus.focus(item.attention_id, 'workspace-viewport'); setFocusedAttention(item.attention_id); setFeedback(focus.source_available ? `Focused ${item.summary}; viewport translation is temporary.` : 'Source unavailable; canonical history is retained.') }}>
                <span className="aidn-spatial-attention-glyph" aria-hidden="true">•</span><span><strong>{item.summary}</strong><small>{item.severity} · {item.state}</small></span>
              </button>
            </li>)}
          </ul>}
          {focusedAttention ? <Button size="sm" variant="ghost" accent="neutral" onClick={() => { services.focus.returnFromFocus(); setFocusedAttention(null); setFeedback('Returned to the previous viewport; canonical positions were unchanged.') }}>Return viewport</Button> : null}
        </GlassFrame>
      </div>
      <p className="aidn-spatial-topology-feedback" role="status" aria-live="polite">{feedback}</p>
      {isSpatialRemoteMediationEnabled() && selectedEndpoint ? (
        <EndpointTestFrame
          endpoint={selectedEndpoint}
          workspaceId={`workspace-${workspaceData.scope.node_id}`}
          nodeId={workspaceData.scope.node_id}
          primaryAgentRef={workspaceData.projection.primaryAgent?.canonicalRef ?? 'agent:primary'}
        />
      ) : null}
    </section>
  )
}
