import type { Endpoint } from '@/lib/types'
import type { SpatialEndpointDetails } from '@/spatial/contracts'

export type EndpointSummaryState = 'loading' | 'empty' | 'ready' | 'stale' | 'offline' | 'unavailable'

export type EndpointSummaryModel = {
  canonicalRef: string
  label: string
  capability: string
  status: string
  publicationStatus: string | null
  runtimeStatus: string | null
  visibility: string | null
  revision: number | null
  provenanceRef: string | null
  state: EndpointSummaryState
  capabilities: readonly string[]
  bundleRef?: string | null
}

export function endpointSummaryFromClassic(endpoint: Endpoint, options: { revision?: number | null; provenanceRef?: string | null } = {}): EndpointSummaryModel {
  const runtime = String(endpoint.runtime_status || '').toUpperCase()
  return {
    canonicalRef: endpoint.endpoint_id,
    label: endpoint.display_name || endpoint.endpoint_id,
    capability: endpoint.model_class || endpoint.capabilities[0] || 'Capability not reported',
    status: endpoint.runtime_status || endpoint.publication_status || 'UNKNOWN',
    publicationStatus: endpoint.publication_status || null,
    runtimeStatus: endpoint.runtime_status || null,
    visibility: endpoint.visibility || null,
    revision: options.revision ?? null,
    provenanceRef: options.provenanceRef ?? null,
    state: runtime.includes('OFFLINE') || runtime.includes('DISABLED') ? 'offline' : 'ready',
    capabilities: endpoint.capabilities,
    bundleRef: endpoint.bundle_id,
  }
}

export function endpointSummaryFromSpatial(details: SpatialEndpointDetails): EndpointSummaryModel {
  const state: EndpointSummaryState = details.surface_state === 'STALE' ? 'stale' : details.surface_state === 'UNAVAILABLE' ? 'unavailable' : details.surface_state === 'LOADING' ? 'loading' : 'ready'
  return {
    canonicalRef: details.canonical_ref,
    label: details.display_name,
    capability: details.capability,
    status: details.surface_state,
    publicationStatus: null,
    runtimeStatus: details.availability,
    visibility: null,
    revision: details.revision,
    provenanceRef: details.provider_ref ?? details.freshness.source ?? details.canonical_ref,
    state,
    capabilities: details.supported_modalities,
    bundleRef: null,
  }
}
