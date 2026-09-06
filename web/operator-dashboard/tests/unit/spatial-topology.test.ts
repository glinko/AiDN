import { describe, expect, it } from 'vitest'

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
} from '@/spatial/data'
import { SPATIAL_SCHEMA_VERSIONS, type SpatialEndpointDetails } from '@/spatial/contracts'
import { parseSpatialEventEnvelope } from '@/spatial/data/events'

const now = () => new Date('2026-09-05T16:00:00.000Z')
const scope = { workspaceId: 'workspace-topology', nodeId: 'node-topology' }

function details(id: string, revision = 1, availability: SpatialEndpointDetails['availability'] = 'AVAILABLE'): SpatialEndpointDetails {
  return {
    schema_version: SPATIAL_SCHEMA_VERSIONS.endpointDetails,
    workspace_id: scope.workspaceId,
    node_id: scope.nodeId,
    canonical_ref: `endpoint:${id}`,
    endpoint_id: id,
    revision,
    display_name: id,
    capability: 'inference.generate',
    endpoint_type: 'mediated-capability',
    supported_modalities: ['text'],
    availability,
    surface_state: availability === 'UNAVAILABLE' ? 'UNAVAILABLE' : availability === 'DEGRADED' ? 'PARTIAL' : 'READY',
    freshness: { state: availability === 'AVAILABLE' ? 'FRESH' : 'STALE', observed_at: now().toISOString(), stale_after_seconds: 300, source: 'test' },
    latency: { p50_ms: null, p95_ms: null, measured_at: null, window: null },
    load: null,
    capacity: null,
    cost: { currency: null, unit_price: null, billing_dimension: null, minimum_charge: null },
    deposit: { minimum: null, recommended: null, currency: null, escrow: null },
    provider_ref: 'provider:test',
    remote_agent_ref: null,
    validation_refs: [],
    input_formats: ['text/plain'],
    output_formats: ['text/plain'],
    limits: { context_tokens: null, payload_bytes: null, timeout_ms: null, streaming: null },
    privacy: null,
    trust_summary: null,
    description: 'test endpoint',
    allowed_actions: ['inspect'],
  }
}

describe('M5.1 canonical reference registry', () => {
  it('deduplicates primary presence, keeps history and isolates workspace scope', () => {
    const registry = new CanonicalReferenceRegistry({ ...scope, now })
    const first = registry.discover({ canonicalRef: 'endpoint:42', entityId: 'ep-42', entityKind: 'endpoint', revision: 1 })
    const duplicate = registry.discover({ canonicalRef: 'endpoint:42', entityId: 'ep-42', entityKind: 'endpoint', revision: 2 })
    expect(first.canonical_ref).toBe(duplicate.canonical_ref)
    expect(registry.primaryPresence('endpoint:42').revision).toBe(2)
    expect(registry.inspectRevision('endpoint:42', 1).revision).toBe(1)
    registry.deletePresentation('endpoint:42')
    expect(registry.primaryPresence('endpoint:42').state).toBe('AVAILABLE')
    expect(registry.resolveInScope('other-workspace', scope.nodeId, 'endpoint:42')).toBeNull()
    expect(registry.getTelemetry()).toMatchObject({ duplicateDiscoveries: 1, projectionDeletes: 1, crossWorkspaceLookups: 1 })
  })

  it('accepts M5 endpoint details through the retained typed event gateway', () => {
    const parsed = parseSpatialEventEnvelope({
      event_id: 'endpoint-details-event',
      event_type: 'spatial.endpoint-details.updated.v1',
      schema_version: SPATIAL_SCHEMA_VERSIONS.endpointDetails,
      node_id: scope.nodeId,
      sequence: 1,
      revision: 1,
      occurred_at: now().toISOString(),
      correlation_id: null,
      causation_id: null,
      payload: details('ep-event'),
    })
    expect(parsed.ok).toBe(true)
  })
})

describe('M5.2–M5.4 endpoint topology', () => {
  it('ranks and deduplicates discovery candidates, promotes only explicit selection, and preserves unknown metrics', () => {
    const registry = new CanonicalReferenceRegistry({ ...scope, now })
    const service = new EndpointDiscoveryService({ ...scope, registry, now, maxCandidates: 100 })
    const result = service.discover({ requestId: 'request-1', endpoints: [details('ep-a'), details('ep-b', 2), details('ep-a', 3), ...Array.from({ length: 98 }, (_, index) => details(`ep-${index + 3}`))], relevance: { 'endpoint:ep-a': 0.4, 'endpoint:ep-b': 0.9 } })
    expect(result.candidates).toHaveLength(100)
    expect(result.candidates[0]?.canonical_ref).toBe('endpoint:ep-b')
    expect(registry.resolveInScope(scope.workspaceId, scope.nodeId, 'endpoint:ep-b')).toBeNull()
    service.select(result.discovery_id, result.candidates[0]!.candidate_id)
    expect(registry.primaryPresence('endpoint:ep-b').projection_kind).toBe('PRIMARY')
    expect(service.pin(result.discovery_id, result.candidates[0]!.candidate_id).candidates[0]?.pinned).toBe(true)
    expect(service.discover({ requestId: 'request-empty', endpoints: [] }).state).toBe('EMPTY')
    const stale = service.discover({ requestId: 'request-stale', endpoints: [details('ep-b', 3)] })
    registry.discover({ canonicalRef: 'endpoint:ep-b', entityId: 'ep-b', entityKind: 'endpoint', revision: 4 })
    expect(() => service.select(stale.discovery_id, stale.candidates[0]!.candidate_id)).toThrowError(/stale candidate/)
    const energy = toEndpointEnergyObject(details('ep-offline', 1, 'UNAVAILABLE'), 'NEVER_USED')
    expect(energy.className).toBe('endpoint-energy')
    expect(energy.collapsed).toBe(true)
    expect(energy.unknownMetrics).toContain('latency')
  })
})

describe('M5.5–M5.6 semantic relations and local subagents', () => {
  it('aggregates stream chunks and keeps subagent delegation distinct from Endpoint access', () => {
    const registry = new CanonicalReferenceRegistry({ ...scope, now })
    registry.discover({ canonicalRef: 'agent:primary', entityId: 'primary', entityKind: 'agent', revision: 1 })
    registry.discover({ canonicalRef: 'endpoint:search', entityId: 'search', entityKind: 'endpoint', revision: 1 })
    const relations = new SemanticRelationService({ ...scope, registry, now, maxVisibleRelations: 10 })
    const subagents = new SubagentLifecycleService({ ...scope, primaryAgentRef: 'agent:primary', registry, relations, now, authorizeRemoteAccess: () => true })
    const spawned = subagents.spawn({ subagentRef: 'agent:research', capabilityGrantScope: ['search'] })
    expect(spawned.state).toBe('SPAWNED')
    subagents.transition(spawned.subagent_ref, 'WORKING')
    expect(subagents.requestRemoteAccess(spawned.subagent_ref, 'endpoint:search', 'search').mediated).toBe(true)
    const first = relations.aggregateStreamChunk({ relationId: 'relation-stream', sourceRef: 'agent:research', targetRef: 'endpoint:search', sourceRevision: 1, targetRevision: 1, streamKey: 'stream-1' })
    const second = relations.aggregateStreamChunk({ relationId: 'relation-stream', sourceRef: 'agent:research', targetRef: 'endpoint:search', sourceRevision: 1, targetRevision: 1, streamKey: 'stream-1' })
    expect(first.chunkCount).toBe(1)
    expect(second.chunkCount).toBe(2)
    expect(relations.list()).toHaveLength(2)
    expect(relations.list().some((relation) => relation.relation_type === 'DELEGATED')).toBe(true)
    expect(relations.visualPath('relation-stream', null, null).offscreenAnchor).not.toBeNull()
    expect(subagents.recoverOrphans()).toHaveLength(0)
  })
})

describe('M5.7 interaction provenance and familiarity', () => {
  it('does not double-count duplicate events and keeps global reputation separate', () => {
    const service = new InteractionProvenanceService({ ...scope, primaryAgentRef: 'agent:primary', now, trustedSuccessThreshold: 2 })
    const input = { requestId: 'request-1', endpointRef: 'endpoint:42', endpointRevision: 7, outcome: 'SUCCESS' as const, idempotencyKey: 'idem-1' }
    expect(service.record(input).duplicate).toBe(false)
    expect(service.record(input).duplicate).toBe(true)
    expect(service.getExperience('endpoint:42').interactionCount).toBe(1)
    service.record({ ...input, requestId: 'request-2', idempotencyKey: 'idem-2' })
    expect(service.getExperience('endpoint:42').familiarity).toBe('TRUSTED_BY_HISTORY')
    service.record({ ...input, requestId: 'request-3', idempotencyKey: 'idem-3', outcome: 'FAILURE' })
    expect(service.getExperience('endpoint:42').lastFailureAt).not.toBeNull()
    service.setGlobalReputation('endpoint:42', 0.9)
    expect(service.getGlobalReputation('endpoint:42')).toBe(0.9)
    expect(service.getExperience('endpoint:42').familiarity).toBe('USED')
  })
})

describe('M5.8–M5.10 bounded attention and focus', () => {
  it('redacts, deduplicates, aggregates regular markers, preserves critical markers and restores viewport', () => {
    const queue = new AttentionQueueService({ ...scope, targetAgentRef: 'agent:primary', now, maxItems: 100 })
    const first = queue.raise({ sourceEventRef: 'event-1', subjectRef: 'endpoint:42', severity: 'ATTENTION', summary: 'token=secret endpoint degraded', groupingKey: 'endpoint' })
    expect(first.item.summary).toContain('[redacted]')
    expect(queue.raise({ sourceEventRef: 'event-1', subjectRef: 'endpoint:42', severity: 'ATTENTION', summary: 'duplicate', groupingKey: 'endpoint' }).duplicate).toBe(true)
    queue.raise({ sourceEventRef: 'event-2', subjectRef: 'endpoint:43', severity: 'ATTENTION', summary: 'another warning', groupingKey: 'endpoint' })
    const critical = queue.raise({ sourceEventRef: 'event-critical', subjectRef: 'endpoint:99', severity: 'CRITICAL', summary: 'critical failure', groupingKey: 'endpoint' }).item
    const markers = new OrbitalAttentionMarkerService({ ...scope, now, maxVisible: 1, reducedMotion: true }).project(queue.list())
    expect(markers.some((marker) => marker.attention_ref === critical.attention_id && marker.orbit_lane === 'INNER')).toBe(true)
    expect(markers.every((marker) => marker.angular_velocity === 0)).toBe(true)
    const snapshot = queue.snapshot()
    const restored = new AttentionQueueService({ ...scope, targetAgentRef: 'agent:primary', now })
    restored.restore(snapshot)
    expect(restored.list()).toHaveLength(3)
    const focus = new AttentionFocusController({ ...scope, queue, now, sourceAvailable: () => true })
    const focused = focus.focus(critical.attention_id, 'viewport-before')
    expect(focused.world_position_preserved).toBe(true)
    expect(focus.execute('ACKNOWLEDGE', critical.attention_id).cameraChanged).toBe(false)
    expect(focus.returnFromFocus().state).toBe('RETURNED')
    const unavailable = new AttentionFocusController({ ...scope, queue: restored, now, sourceAvailable: () => false })
    expect(unavailable.focus(critical.attention_id).state).toBe('SOURCE_UNAVAILABLE')
    expect(() => unavailable.execute('OPEN_SOURCE', critical.attention_id)).toThrowError(/unavailable/)
  })
})
