import {
  parseSpatialDiscoveryResult,
  parseSpatialEndpointDetails,
  SPATIAL_SCHEMA_VERSIONS,
  type SpatialDiscoveryCandidate,
  type SpatialDiscoveryResult,
  type SpatialEndpointDetails,
  type SpatialFamiliarityState,
} from '@/spatial/contracts'

import { CanonicalReferenceRegistry, type CanonicalReferenceRegistryOptions } from './reference-registry'

export type EndpointEnergyAvailability = 'HEALTHY' | 'BUSY' | 'DEGRADED' | 'OFFLINE' | 'UNKNOWN'

export type EndpointEnergyObject = {
  canonicalRef: string
  endpointRef: string
  className: 'endpoint-energy'
  availability: EndpointEnergyAvailability
  familiarity: SpatialFamiliarityState
  active: boolean
  coreIntensity: number
  haloIntensity: number
  particleRate: number | null
  collapsed: boolean
  unknownMetrics: string[]
}

export type EndpointTopologyErrorCode = 'INVALID_ENDPOINT' | 'UNKNOWN_DISCOVERY' | 'UNKNOWN_CANDIDATE' | 'STALE_CANDIDATE' | 'SCOPE_MISMATCH'

export class EndpointTopologyError extends Error {
  readonly code: EndpointTopologyErrorCode

  constructor(code: EndpointTopologyErrorCode, message: string) {
    super(message)
    this.name = 'EndpointTopologyError'
    this.code = code
  }
}

function availabilityFor(details: SpatialEndpointDetails): EndpointEnergyAvailability {
  if (details.availability === 'UNAVAILABLE') return 'OFFLINE'
  if (details.availability === 'UNKNOWN' || details.freshness.state === 'UNKNOWN' || details.freshness.state === 'UNAVAILABLE') return 'UNKNOWN'
  if (details.availability === 'DEGRADED' || details.freshness.state === 'STALE' || details.freshness.state === 'PARTIAL') return 'DEGRADED'
  if (details.load !== null && details.load >= 0.8) return 'BUSY'
  return 'HEALTHY'
}

export function toEndpointEnergyObject(details: SpatialEndpointDetails, familiarity: SpatialFamiliarityState = 'NEVER_USED', active = false): EndpointEnergyObject {
  const availability = availabilityFor(details)
  const unknownMetrics = [
    details.latency.p95_ms === null ? 'latency' : null,
    details.load === null ? 'load' : null,
    details.capacity === null ? 'capacity' : null,
    details.cost.unit_price === null ? 'cost' : null,
  ].filter((metric): metric is string => Boolean(metric))
  const base = availability === 'OFFLINE' ? 0.14 : availability === 'DEGRADED' ? 0.42 : availability === 'BUSY' ? 0.68 : availability === 'UNKNOWN' ? 0.28 : 0.58
  return {
    canonicalRef: details.canonical_ref,
    endpointRef: details.endpoint_id,
    className: 'endpoint-energy',
    availability,
    familiarity,
    active,
    coreIntensity: Number((active ? Math.min(1, base + 0.2) : base).toFixed(3)),
    haloIntensity: Number((active ? 0.8 : familiarity === 'TRUSTED_BY_HISTORY' ? 0.36 : familiarity === 'USED' ? 0.18 : 0.08).toFixed(3)),
    particleRate: details.load === null ? null : Number(Math.max(0.1, Math.min(1, details.load)).toFixed(3)),
    collapsed: availability === 'OFFLINE',
    unknownMetrics,
  }
}

export type EndpointDiscoveryRequest = {
  requestId: string
  endpoints: readonly SpatialEndpointDetails[]
  relevance?: Readonly<Record<string, number>>
}

export type EndpointDiscoveryServiceOptions = CanonicalReferenceRegistryOptions & {
  registry?: CanonicalReferenceRegistry
  maxCandidates?: number
}

function discoveryState(candidateCount: number): SpatialDiscoveryResult['state'] {
  return candidateCount === 0 ? 'EMPTY' : 'READY'
}

/** Ranked, temporary candidate projections. Selection is the only promotion path. */
export class EndpointDiscoveryService {
  private readonly registry: CanonicalReferenceRegistry
  private readonly options: Required<Pick<EndpointDiscoveryServiceOptions, 'workspaceId' | 'nodeId'>> & Pick<EndpointDiscoveryServiceOptions, 'now' | 'idFactory'>
  private readonly results = new Map<string, SpatialDiscoveryResult>()
  private readonly maxCandidates: number

  constructor(options: EndpointDiscoveryServiceOptions) {
    this.registry = options.registry ?? new CanonicalReferenceRegistry(options)
    this.options = { workspaceId: options.workspaceId, nodeId: options.nodeId, now: options.now, idFactory: options.idFactory }
    this.maxCandidates = Math.max(1, Math.min(1_000, options.maxCandidates ?? 100))
  }

  getRegistry(): CanonicalReferenceRegistry {
    return this.registry
  }

  discover(request: EndpointDiscoveryRequest): SpatialDiscoveryResult {
    const now = (this.options.now ?? (() => new Date()))().toISOString()
    const unique = new Map<string, SpatialEndpointDetails>()
    for (const raw of request.endpoints) {
      const parsed = parseSpatialEndpointDetails(raw)
      if (!parsed.ok) throw new EndpointTopologyError('INVALID_ENDPOINT', `endpoint details invalid at ${parsed.diagnostic.path}`)
      const current = unique.get(parsed.data.canonical_ref)
      if (!current || parsed.data.revision >= current.revision) unique.set(parsed.data.canonical_ref, parsed.data)
    }
    const candidates = [...unique.values()]
      .map((details) => ({
        details,
        relevance: Math.max(0, Math.min(1, request.relevance?.[details.canonical_ref] ?? 0.5)),
      }))
      .sort((left, right) => right.relevance - left.relevance || left.details.endpoint_id.localeCompare(right.details.endpoint_id))
      .slice(0, this.maxCandidates)
      .map((entry, index): SpatialDiscoveryCandidate => ({
        candidate_id: `${request.requestId}:candidate:${index + 1}`,
        canonical_ref: entry.details.canonical_ref,
        endpoint_ref: entry.details.endpoint_id,
        endpoint_revision: entry.details.revision,
        rank: index + 1,
        relevance: Number(entry.relevance.toFixed(4)),
        explanation: `Capability match ${(entry.relevance * 100).toFixed(0)}% · ${entry.details.capability}`,
        state: 'CANDIDATE',
        pinned: false,
        details: entry.details,
      }))
    const result: SpatialDiscoveryResult = {
      schema_version: SPATIAL_SCHEMA_VERSIONS.discoveryResult,
      discovery_id: `${request.requestId}:discovery`,
      request_id: request.requestId,
      workspace_id: this.options.workspaceId,
      node_id: this.options.nodeId,
      revision: 0,
      state: discoveryState(candidates.length),
      candidates,
      created_at: now,
      updated_at: now,
    }
    const parsed = parseSpatialDiscoveryResult(result)
    if (!parsed.ok) throw new EndpointTopologyError('INVALID_ENDPOINT', `discovery result invalid at ${parsed.diagnostic.path}`)
    this.results.set(parsed.data.discovery_id, parsed.data)
    return this.cloneResult(parsed.data)
  }

  get(discoveryId: string): SpatialDiscoveryResult {
    const result = this.results.get(discoveryId)
    if (!result) throw new EndpointTopologyError('UNKNOWN_DISCOVERY', `unknown discovery: ${discoveryId}`)
    return this.cloneResult(result)
  }

  select(discoveryId: string, candidateId: string): SpatialDiscoveryResult {
    const result = this.get(discoveryId)
    const selected = result.candidates.find((candidate) => candidate.candidate_id === candidateId)
    if (!selected) throw new EndpointTopologyError('UNKNOWN_CANDIDATE', `unknown discovery candidate: ${candidateId}`)
    const current = this.registry.resolveInScope(this.options.workspaceId, this.options.nodeId, selected.canonical_ref)
    if (current && current.revision > selected.endpoint_revision) throw new EndpointTopologyError('STALE_CANDIDATE', `stale candidate: ${candidateId}`)
    this.registry.discover({
      canonicalRef: selected.canonical_ref,
      entityId: selected.endpoint_ref,
      entityKind: 'endpoint',
      revision: selected.endpoint_revision,
      projectionKind: 'PRIMARY',
    })
    const updated: SpatialDiscoveryResult = {
      ...result,
      revision: result.revision + 1,
      state: 'READY',
      candidates: result.candidates.map((candidate) => ({
        ...candidate,
        state: candidate.candidate_id === candidateId ? 'SELECTED' : candidate.state,
      })),
      updated_at: (this.options.now ?? (() => new Date()))().toISOString(),
    }
    this.results.set(discoveryId, updated)
    return this.cloneResult(updated)
  }

  dismiss(discoveryId: string): SpatialDiscoveryResult {
    const result = this.get(discoveryId)
    const updated = {
      ...result,
      revision: result.revision + 1,
      state: 'DISMISSED' as const,
      candidates: result.candidates.map((candidate) => ({ ...candidate, state: 'DISMISSED' as const })),
      updated_at: (this.options.now ?? (() => new Date()))().toISOString(),
    }
    this.results.set(discoveryId, updated)
    return this.cloneResult(updated)
  }

  pin(discoveryId: string, candidateId: string): SpatialDiscoveryResult {
    const result = this.get(discoveryId)
    const selected = result.candidates.find((candidate) => candidate.candidate_id === candidateId)
    if (!selected) throw new EndpointTopologyError('UNKNOWN_CANDIDATE', `unknown discovery candidate: ${candidateId}`)
    const updated = {
      ...result,
      revision: result.revision + 1,
      candidates: result.candidates.map((candidate) => candidate.candidate_id === candidateId ? { ...candidate, pinned: true } : candidate),
      updated_at: (this.options.now ?? (() => new Date()))().toISOString(),
    }
    this.results.set(discoveryId, updated)
    return this.cloneResult(updated)
  }

  promote(discoveryId: string, candidateId: string): SpatialDiscoveryResult {
    return this.select(discoveryId, candidateId)
  }

  markStale(discoveryId: string, canonicalRef: string): SpatialDiscoveryResult {
    const result = this.get(discoveryId)
    const found = result.candidates.some((candidate) => candidate.canonical_ref === canonicalRef)
    if (!found) throw new EndpointTopologyError('UNKNOWN_CANDIDATE', `unknown endpoint reference: ${canonicalRef}`)
    const updated = {
      ...result,
      revision: result.revision + 1,
      state: 'STALE' as const,
      candidates: result.candidates.map((candidate) => candidate.canonical_ref === canonicalRef ? { ...candidate, state: 'STALE' as const } : candidate),
      updated_at: (this.options.now ?? (() => new Date()))().toISOString(),
    }
    this.results.set(discoveryId, updated)
    return this.cloneResult(updated)
  }

  private cloneResult(result: SpatialDiscoveryResult): SpatialDiscoveryResult {
    return {
      ...result,
      candidates: result.candidates.map((candidate) => ({ ...candidate, details: { ...candidate.details, latency: { ...candidate.details.latency }, cost: { ...candidate.details.cost }, deposit: { ...candidate.details.deposit }, limits: { ...candidate.details.limits } } })),
    }
  }
}

export function createEndpointDiscoveryService(options: EndpointDiscoveryServiceOptions): EndpointDiscoveryService {
  return new EndpointDiscoveryService(options)
}

export function createEndpointDetailsSurface(details: SpatialEndpointDetails): SpatialEndpointDetails {
  const parsed = parseSpatialEndpointDetails(details)
  if (!parsed.ok) throw new EndpointTopologyError('INVALID_ENDPOINT', `endpoint details invalid at ${parsed.diagnostic.path}`)
  return {
    ...parsed.data,
    latency: { ...parsed.data.latency },
    cost: { ...parsed.data.cost },
    deposit: { ...parsed.data.deposit },
    limits: { ...parsed.data.limits },
  }
}
