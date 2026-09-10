import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { useQuery, useQueryClient } from '@tanstack/react-query'

import {
  type SpatialPrimaryAgentSlot,
  type SpatialPrimaryAgentState,
  type SpatialCanonicalEntity,
  type SpatialNodeStatus,
  type SpatialRelationContract,
  type SpatialWorkspaceSnapshot,
} from '@/spatial/contracts'

import type { SpatialQualityProfile } from '../prototype/environment'
import {
  composeSpatialWorkspaceViewModel,
  type SpatialWorkspaceViewModel,
} from './view-models'
import { createSpatialEventGateway, type SpatialTypedEvent } from './events'
import { createPrimaryAgentSlot } from './primary-agent-slot'
import {
  createMockSpatialNodeStatus,
  createMockSpatialWorkspaceSnapshot,
  MOCK_SPATIAL_SCOPE,
} from './mock-fixtures'
import { spatialQueryKeys } from './query-keys'
import { spatialScopeKey, type SpatialNodeScope } from './scope'
import { SpatialApiError } from './transport'
import type { SpatialDomainClients } from './clients'
import type { SpatialWorkspaceRepository } from '../workspace/repository'

export type SpatialWorkspaceDataMode = 'mock-real' | 'remote' | 'offline' | 'empty' | 'malformed'

export type SpatialWorkspaceLoader = (scope: SpatialNodeScope, signal?: AbortSignal) => Promise<SpatialWorkspaceSnapshot>
export type SpatialNodeStatusLoader = (scope: SpatialNodeScope, signal?: AbortSignal) => Promise<SpatialNodeStatus>

export type UseSpatialWorkspaceDataOptions = {
  scope?: SpatialNodeScope
  mode?: SpatialWorkspaceDataMode
  profile?: SpatialQualityProfile
  repository?: SpatialWorkspaceRepository
  clients?: SpatialDomainClients
  /** Production adapters may source canonical contracts from a legacy read-model. */
  workspaceLoader?: SpatialWorkspaceLoader
  statusLoader?: SpatialNodeStatusLoader
  /** Optional polling interval for a live Node-backed surface. */
  pollIntervalMs?: number
  eventStream?: readonly unknown[]
}

export type SpatialWorkspaceData = {
  scope: SpatialNodeScope
  snapshot: SpatialWorkspaceSnapshot | null
  status: SpatialNodeStatus | null
  projection: SpatialWorkspaceViewModel
  state: 'loading' | 'ready' | 'partial' | 'stale' | 'offline' | 'empty' | 'error'
  isLoading: boolean
  error: SpatialApiError | null
  lastEvent: SpatialTypedEvent | null
  primaryAgentSlot: SpatialPrimaryAgentSlot
  primaryAgentOperationalState: SpatialPrimaryAgentState | null
  refresh: () => Promise<unknown>
}

function projectionFor(
  snapshot: SpatialWorkspaceSnapshot | null,
  status: SpatialNodeStatus | null,
  profile: SpatialQualityProfile,
): SpatialWorkspaceViewModel {
  return snapshot ? composeSpatialWorkspaceViewModel(snapshot, status, profile) : {
    entities: [],
    relations: [],
    primaryAgent: null,
    nodeStatus: status,
    nodeStatusViewModel: null,
    sourceRevision: 0,
    freshnessState: status?.freshness.state ?? 'UNKNOWN',
    dataState: 'empty',
  }
}

function stateFor(
  snapshot: SpatialWorkspaceSnapshot | null,
  status: SpatialNodeStatus | null,
  isLoading: boolean,
  error: SpatialApiError | null,
  profile: SpatialQualityProfile,
): SpatialWorkspaceData['state'] {
  if (error) return 'error'
  if (isLoading) return 'loading'
  return projectionFor(snapshot, status, profile).dataState
}

/**
 * Pure, synchronous fixture seam used by direct Workspace consumers and unit
 * tests that intentionally do not mount a QueryClient. The route uses the
 * hook below, while this helper keeps the renderer deterministic in isolation.
 */
export function createMockSpatialWorkspaceData(
  profile: SpatialQualityProfile = 'desktop',
  mode: Exclude<SpatialWorkspaceDataMode, 'remote' | 'malformed'> = 'mock-real',
  scope: SpatialNodeScope = MOCK_SPATIAL_SCOPE,
): SpatialWorkspaceData {
  const snapshot = mode === 'empty'
    ? emptySnapshot(scope)
    : mode === 'offline'
      ? offlineSnapshot(scope)
      : createMockSpatialWorkspaceSnapshot(scope)
  const status = mode === 'offline'
    ? (() => {
      const offlineStatus = createMockSpatialNodeStatus(scope)
      return {
        ...offlineStatus,
        state: 'UNKNOWN' as const,
        freshness: { ...offlineStatus.freshness, state: 'UNAVAILABLE' as const },
        components: offlineStatus.components.map((component) => component.kind === 'primary-agent' || component.component_type === 'Primary Agent'
          ? { ...component, state: 'OFFLINE' as const, freshness: { ...component.freshness, state: 'UNAVAILABLE' as const } }
          : { ...component, freshness: { ...component.freshness, state: 'UNAVAILABLE' as const } }),
      }
    })()
    : createMockSpatialNodeStatus(scope)
  const projection = projectionFor(snapshot, status, profile)
  const primaryAgentSlot = createPrimaryAgentSlot(scope, { now: new Date('2026-09-05T16:00:00.000Z') })
  return {
    scope,
    snapshot,
    status,
    projection,
    state: projection.dataState,
    isLoading: false,
    error: null,
    lastEvent: null,
    primaryAgentSlot,
    primaryAgentOperationalState: null,
    refresh: async () => ({ snapshot, status }),
  }
}

function emptySnapshot(scope: SpatialNodeScope = MOCK_SPATIAL_SCOPE): SpatialWorkspaceSnapshot {
  const snapshot = createMockSpatialWorkspaceSnapshot(scope)
  return { ...snapshot, entities: [], relations: [], semantic_anchors: [], primary_agent_ref: undefined }
}

function offlineSnapshot(scope: SpatialNodeScope = MOCK_SPATIAL_SCOPE): SpatialWorkspaceSnapshot {
  const snapshot = createMockSpatialWorkspaceSnapshot(scope)
  return {
    ...snapshot,
    entities: snapshot.entities.map((entity) => ({ ...entity, availability: 'UNKNOWN', freshness: { ...entity.freshness, state: 'UNAVAILABLE' } })),
    relations: snapshot.relations.map((relation) => ({ ...relation, state: 'UNAVAILABLE', freshness: { ...relation.freshness, state: 'UNAVAILABLE' } })),
    updated_at: snapshot.updated_at,
  }
}

function applyTypedEvent(snapshot: SpatialWorkspaceSnapshot, event: SpatialTypedEvent): SpatialWorkspaceSnapshot {
  if (event.event_type === 'spatial.workspace.updated.v1') {
    const next = event.payload as SpatialWorkspaceSnapshot
    return next.semantic_revision < snapshot.semantic_revision ? snapshot : next
  }
  if (event.event_type === 'spatial.entity.upserted.v1' || event.event_type === 'spatial.entity.archived.v1') {
    const entity = event.payload as SpatialCanonicalEntity
    if (entity.revision < snapshot.semantic_revision) return snapshot
    return {
      ...snapshot,
      revision: Math.max(snapshot.revision, entity.revision),
      semantic_revision: Math.max(snapshot.semantic_revision, entity.revision),
      updated_at: entity.updated_at,
      entities: [...snapshot.entities.filter((candidate) => candidate.canonical_ref !== entity.canonical_ref), entity],
    }
  }
  if (event.event_type === 'spatial.relation.upserted.v1') {
    const relation = event.payload as SpatialRelationContract
    if (relation.revision < snapshot.semantic_revision) return snapshot
    return {
      ...snapshot,
      revision: Math.max(snapshot.revision, relation.revision),
      semantic_revision: Math.max(snapshot.semantic_revision, relation.revision),
      updated_at: relation.updated_at,
      relations: [...snapshot.relations.filter((candidate) => candidate.relation_id !== relation.relation_id), relation],
    }
  }
  return snapshot
}

function mapDataError(error: unknown, path: string): SpatialApiError {
  if (error instanceof SpatialApiError) return error
  return new SpatialApiError('network', 'Spatial Workspace data is unavailable.', path)
}

export function useSpatialWorkspaceData(options: UseSpatialWorkspaceDataOptions = {}): SpatialWorkspaceData {
  const scopeHypervisorId = options.scope?.hypervisor_id ?? MOCK_SPATIAL_SCOPE.hypervisor_id
  const scopeNodeId = options.scope?.node_id ?? MOCK_SPATIAL_SCOPE.node_id
  const scope = useMemo(() => ({ hypervisor_id: scopeHypervisorId, node_id: scopeNodeId }), [scopeHypervisorId, scopeNodeId])
  const mode = options.mode ?? 'mock-real'
  const profile = options.profile ?? 'desktop'
  const queryClient = useQueryClient()
  const mock = useMemo(() => ({ snapshot: createMockSpatialWorkspaceSnapshot(scope), status: createMockSpatialNodeStatus(scope) }), [scope])
  const initialSnapshot = mode === 'empty' ? emptySnapshot(scope) : mode === 'offline' ? offlineSnapshot(scope) : mock.snapshot
  const initialStatus = mode === 'offline' ? { ...mock.status, state: 'UNKNOWN' as const, freshness: { ...mock.status.freshness, state: 'UNAVAILABLE' as const } } : mock.status

  const query = useQuery({
    queryKey: spatialQueryKeys.workspace(scope),
    queryFn: async ({ signal }) => {
      if (mode === 'malformed') throw new SpatialApiError('malformed', 'Spatial Workspace payload is malformed.', '/operators/spatial/workspace')
      if (mode === 'remote' && options.repository) return options.repository.getSnapshot(scope)
      if (mode === 'remote' && options.clients) return options.clients.workspace.get(scope, signal)
      if (mode === 'remote' && options.workspaceLoader) return options.workspaceLoader(scope, signal)
      if (mode === 'offline' || mode === 'empty' || mode === 'mock-real') return initialSnapshot
      throw new SpatialApiError('network', 'No Spatial Workspace transport is configured.', '/operators/spatial/workspace')
    },
    enabled: mode === 'remote' && Boolean(options.repository || options.clients || options.workspaceLoader) || mode === 'malformed',
    initialData: mode === 'remote' || mode === 'malformed' ? undefined : initialSnapshot,
    retry: false,
    staleTime: 8_000,
    refetchInterval: mode === 'remote' ? options.pollIntervalMs ?? false : false,
  })

  const statusQuery = useQuery({
    queryKey: spatialQueryKeys.nodeStatus(scope),
    queryFn: async ({ signal }) => {
      if (mode === 'remote' && options.clients) return options.clients.nodeStatus.get(scope, signal)
      if (mode === 'remote' && options.statusLoader) return options.statusLoader(scope, signal)
      return initialStatus
    },
    enabled: mode === 'remote' && Boolean(options.clients || options.statusLoader),
    initialData: mode === 'remote' ? undefined : initialStatus,
    retry: false,
    staleTime: 8_000,
    refetchInterval: mode === 'remote' ? options.pollIntervalMs ?? false : false,
  })

  const [liveSnapshot, setLiveSnapshot] = useState<SpatialWorkspaceSnapshot | null>(query.data ?? null)
  const [liveStatus, setLiveStatus] = useState<SpatialNodeStatus | null>(statusQuery.data ?? null)
  const currentScopeKey = spatialScopeKey(scope)
  const [liveScopeKey, setLiveScopeKey] = useState(currentScopeKey)
  const [lastEvent, setLastEvent] = useState<SpatialTypedEvent | null>(null)
  const initialSlot = useMemo(() => createPrimaryAgentSlot(scope, { now: new Date('2026-09-05T16:00:00.000Z') }), [scope])
  const [livePrimaryAgentSlot, setLivePrimaryAgentSlot] = useState<SpatialPrimaryAgentSlot>(initialSlot)
  const [livePrimaryAgentOperationalState, setLivePrimaryAgentOperationalState] = useState<SpatialPrimaryAgentState | null>(null)
  const resetScopeKey = useRef(currentScopeKey)

  useEffect(() => {
    if (resetScopeKey.current === currentScopeKey) return
    resetScopeKey.current = currentScopeKey
    setLiveScopeKey(currentScopeKey)
    setLiveSnapshot(query.data ?? null)
    setLiveStatus(statusQuery.data ?? null)
    setLivePrimaryAgentSlot(initialSlot)
    setLivePrimaryAgentOperationalState(null)
    setLastEvent(null)
  }, [currentScopeKey, initialSlot, query.data, statusQuery.data])

  useEffect(() => {
    if (liveScopeKey !== currentScopeKey) return
    setLiveSnapshot((current) => {
      if (!query.data) return current
      return !current || query.data.revision >= current.revision ? query.data : current
    })
    setLiveStatus((current) => {
      if (!statusQuery.data) return current
      return !current || statusQuery.data.revision >= current.revision ? statusQuery.data : current
    })
  }, [currentScopeKey, liveScopeKey, query.data, statusQuery.data])

  useEffect(() => {
    const gateway = createSpatialEventGateway({
      scope,
      onStateUpdate: (event) => {
        setLastEvent(event)
        if (event.event_type === 'spatial.node-status.changed.v1') {
          const nextStatus = event.payload as SpatialNodeStatus
          setLiveStatus((current) => {
            if (current && nextStatus.revision < current.revision) return current
            queryClient.setQueryData(spatialQueryKeys.nodeStatus(scope), nextStatus)
            return nextStatus
          })
        } else if (event.event_type === 'spatial.primary-agent.binding-changed.v1') {
          const nextSlot = event.payload as SpatialPrimaryAgentSlot
          setLivePrimaryAgentSlot((current) => nextSlot.revision < current.revision ? current : nextSlot)
          queryClient.setQueryData(spatialQueryKeys.primaryAgentSlot(scope), nextSlot)
        } else if (event.event_type === 'spatial.primary-agent.state-changed.v1') {
          const nextState = event.payload as SpatialPrimaryAgentState
          setLivePrimaryAgentOperationalState((current) => current && nextState.revision < current.revision ? current : nextState)
          queryClient.setQueryData(spatialQueryKeys.primaryAgentState(scope), nextState)
        } else if (event.event_type === 'spatial.primary-agent.grant-changed.v1') {
          queryClient.setQueryData(spatialQueryKeys.primaryAgentGrant(scope, (event.payload as { grant_id: string }).grant_id), event.payload)
        } else {
          setLiveSnapshot((current) => {
            if (!current) return current
            const next = applyTypedEvent(current, event)
            queryClient.setQueryData(spatialQueryKeys.workspace(scope), next)
            return next
          })
        }
      },
    })
    if (options.eventStream) gateway.replay(options.eventStream)
    return () => setLastEvent(null)
  }, [options.eventStream, queryClient, scope])

  const refresh = useCallback(async () => {
    const [workspace, status] = await Promise.all([query.refetch(), statusQuery.refetch()])
    return { workspace, status }
  }, [query, statusQuery])

  const snapshot = liveScopeKey === currentScopeKey ? liveSnapshot : null
  const status = liveScopeKey === currentScopeKey ? liveStatus : null
  const projection = useMemo(() => projectionFor(snapshot, status, profile), [profile, snapshot, status])
  const isLoading = query.isPending || statusQuery.isPending
  const error = query.error ? mapDataError(query.error, '/operators/spatial/workspace') : statusQuery.error ? mapDataError(statusQuery.error, '/operators/spatial/status') : null
  const state = stateFor(snapshot, status, isLoading, error, profile)

  return { scope, snapshot, status, projection, state, isLoading, error, lastEvent, primaryAgentSlot: livePrimaryAgentSlot, primaryAgentOperationalState: livePrimaryAgentOperationalState, refresh }
}
