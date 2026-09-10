import { z } from 'zod'

import {
  dashboardSchemas,
  type Endpoint,
  type EndpointPayload,
  type Fleet,
  type ResidentAgentStatus,
  type SessionDashboard,
} from '@/lib/types'
import {
  parseSpatialNodeStatus,
  parseSpatialWorkspace,
  type SpatialCanonicalEntity,
  type SpatialNodeStatus,
  type SpatialWorkspaceSnapshot,
} from '@/spatial/contracts'
import {
  composeSpatialWorkspaceViewModel,
  type SpatialWorkspaceViewModel,
} from './view-models'
import { SpatialApiError } from './transport'
import type { SpatialNodeScope } from './scope'
import {
  DEFAULT_CALIBRATION,
  type CalibrationConfig,
  type ConnectionConfig,
  type CubeConfig,
  type OrbConfig,
  type Vector3Tuple,
} from '@/spatial-calibration/model'
import { type EndpointConfig } from '@/spatial-calibration/endpoint'

/**
 * The operator dashboard is the first production read-model available on the
 * 122 node.  This adapter translates that read-model into the M2 canonical
 * contracts before anything reaches the renderer.  Presentation positions are
 * intentionally generated locally; the Node remains the authority for
 * identity, state, freshness and relationships.
 */

const dashboardStatusSummarySchema = z.object({
  node: z.object({ node_id: z.string().optional() }).passthrough().optional(),
  resident_inference: z.object({
    configured: z.boolean().optional(),
    state: z.string().optional(),
    runtime: z.object({
      status: z.string().optional(),
      health_status: z.string().optional(),
      readiness_status: z.string().optional(),
    }).passthrough().optional(),
  }).passthrough().optional(),
  runtimes: z.array(z.record(z.string(), z.unknown())).catch([]),
  queue: z.object({ queued: z.coerce.number().catch(0), active: z.coerce.number().catch(0) }).passthrough().optional(),
  resources: z.record(z.string(), z.unknown()).nullable().optional(),
}).passthrough()

type DashboardStatusSummary = z.infer<typeof dashboardStatusSummarySchema>

type DashboardPayload = {
  readonly fleet: Fleet
  readonly endpoints: EndpointPayload
  readonly sessions: SessionDashboard
  readonly residentAgent: ResidentAgentStatus | null
  readonly statusSummary: DashboardStatusSummary | null
  readonly failures: readonly string[]
  readonly observedAt: string
}

export type DashboardSpatialLoaders = {
  readonly workspace: (scope: SpatialNodeScope, signal?: AbortSignal) => Promise<SpatialWorkspaceSnapshot>
  readonly status: (scope: SpatialNodeScope, signal?: AbortSignal) => Promise<SpatialNodeStatus>
}

export type DashboardSpatialSceneSource = {
  readonly nodeId: string
  readonly state: 'live' | 'partial'
  readonly revision: number
  readonly endpointCount: number
  readonly sessionCount: number
  readonly bundleCount: number
  readonly subagentCount: number
  readonly failedSources: readonly string[]
}

export type DashboardSpatialSceneData = {
  readonly config: CalibrationConfig
  readonly endpoints: ReadonlyArray<EndpointConfig>
  readonly source: DashboardSpatialSceneSource
  readonly projection: SpatialWorkspaceViewModel
}

export type DashboardSpatialAdapterOptions = {
  /** Relative API root by default so the route works on the node itself. */
  readonly apiRoot?: string
  readonly fetcher?: (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>
  readonly timeoutMs?: number
  readonly now?: () => Date
  readonly cacheTtlMs?: number
}

function record(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
}

function stringValue(value: unknown, fallback = ''): string {
  return typeof value === 'string' && value.trim() ? value.trim() : fallback
}

function numberValue(value: unknown, fallback = 0): number {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string' && Number.isFinite(Number(value))) return Number(value)
  return fallback
}

function booleanValue(value: unknown, fallback = false): boolean {
  return typeof value === 'boolean' ? value : fallback
}

function upper(value: unknown, fallback: string): string {
  return stringValue(value, fallback).toUpperCase().replace(/[^A-Z0-9_:-]/g, '_').slice(0, 96) || fallback
}

function revisionFor(now: Date): number {
  return Math.max(1, Math.floor(now.getTime() / 1000))
}

function freshness(observedAt: string) {
  return {
    state: 'FRESH' as const,
    observed_at: observedAt,
    stale_after_seconds: 30,
    source: 'operators.dashboard' as const,
  }
}

function slug(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 48) || 'node'
}

function hash(value: string): number {
  let result = 2166136261
  for (const character of value) result = Math.imul(result ^ character.charCodeAt(0), 16777619)
  return Math.abs(result >>> 0)
}

function hexColor(value: string, fallback: string): string {
  return /^#[0-9a-f]{6}$/i.test(value) ? value : fallback
}

function shade(hex: string, amount: number): string {
  const value = hexColor(hex, '#9bb1c8').slice(1)
  const channels = [0, 2, 4].map((offset) => Math.max(0, Math.min(255, Math.round(parseInt(value.slice(offset, offset + 2), 16) * amount))))
  return `#${channels.map((channel) => channel.toString(16).padStart(2, '0')).join('')}`
}

const ENDPOINT_PALETTE = ['#83c9e8', '#9ed6c0', '#b8a7ea', '#efb68f', '#f0d58d', '#dba8d0', '#a7cddf'] as const
const ARTIFACT_PALETTE = ['#b4c9ee', '#c9b6e8', '#afd8d2', '#e4c39e', '#d9abc9', '#b9d8c1', '#d1c2ef'] as const
const AGENT_PALETTE = ['#efc75b', '#eb9d91', '#8ed5bd', '#b6a7ec', '#83c9e8', '#efb58c'] as const

function paletteColor(palette: readonly string[], key: string, state = ''): string {
  if (state.includes('OFFLINE') || state.includes('UNAVAILABLE')) return '#aab5c4'
  return palette[hash(key) % palette.length]
}

function endpointState(endpoint: Endpoint): { state: string; availability: 'AVAILABLE' | 'DEGRADED' | 'UNAVAILABLE' } {
  const publication = upper(endpoint.publication_status, 'UNKNOWN')
  const runtime = upper(endpoint.runtime_status, 'UNKNOWN')
  if (publication === 'PUBLISHED' && endpoint.publication_ready !== false) return { state: 'READY', availability: 'AVAILABLE' }
  if (publication === 'CONFIGURED' || runtime === 'CREATED' || runtime === 'RUNNING') return { state: 'CONFIGURED', availability: 'DEGRADED' }
  return { state: 'OFFLINE', availability: 'UNAVAILABLE' }
}

function sessionState(item: Record<string, unknown>): { state: string; availability: 'AVAILABLE' | 'DEGRADED' | 'UNAVAILABLE' | 'UNKNOWN' } {
  const session = record(item.session)
  const state = upper(session.status, 'UNKNOWN')
  if (state === 'ACTIVE' || state === 'QUEUED') return { state, availability: 'AVAILABLE' }
  if (state === 'CLOSED' || state === 'COMPLETED' || state === 'TERMINAL') return { state, availability: 'AVAILABLE' }
  return { state, availability: state === 'UNKNOWN' ? 'UNKNOWN' : 'DEGRADED' }
}

function primaryState(resident: ResidentAgentStatus | null, status: DashboardStatusSummary | null): { state: string; availability: 'AVAILABLE' | 'DEGRADED' | 'UNAVAILABLE' } {
  const state = upper(resident?.state ?? status?.resident_inference?.state, 'UNKNOWN')
  const enabled = resident ? resident.enabled : booleanValue(status?.resident_inference?.configured, false)
  if (!enabled || state.includes('OFFLINE') || state.includes('STOP')) return { state: 'OFFLINE', availability: 'UNAVAILABLE' }
  if (state.includes('DEGRADED') || state.includes('ERROR')) return { state: 'ATTENTION', availability: 'DEGRADED' }
  return { state: ['READY', 'LISTENING', 'THINKING', 'ACTING', 'WORKING', 'ATTENTION', 'CRITICAL'].includes(state) ? state : 'READY', availability: 'AVAILABLE' }
}

function canonicalEntityBase<K extends SpatialCanonicalEntity['kind']>(
  kind: K,
  id: string,
  nodeId: string,
  label: string,
  state: string,
  availability: 'AVAILABLE' | 'DEGRADED' | 'UNAVAILABLE' | 'UNKNOWN',
  revision: number,
  observedAt: string,
) {
  return {
    schema_version: 'spatial.entity.v1' as const,
    kind,
    id,
    canonical_ref: `${kind}:${id}`,
    node_id: nodeId,
    revision,
    label: label.slice(0, 240) || id,
    state,
    availability,
    freshness: freshness(observedAt),
    created_at: observedAt,
    updated_at: observedAt,
  }
}

function nodeIdFor(scope: SpatialNodeScope, payload: DashboardPayload): string {
  const nodeId = stringValue(payload.fleet.node?.node_id)
    || stringValue(record(payload.sessions.node_identity).node_id)
    || scope.node_id
  if (nodeId !== scope.node_id) throw new SpatialApiError('conflict', 'Dashboard response belongs to a different Node.', 'scope')
  return nodeId
}

function emptyFleet(scope: SpatialNodeScope): Fleet {
  return {
    node: { node_id: scope.node_id },
    resources: {
      total: { cpu: 0, ram_mb: 0, vram_mb: 0 },
      reserved: { cpu: 0, ram_mb: 0, vram_mb: 0 },
      free: { cpu: 0, ram_mb: 0, vram_mb: 0 },
    },
    queue: { queued: 0, active: 0, completed: 0, failed: 0 },
    bundles: [],
  }
}

function emptyEndpoints(): EndpointPayload {
  return { summary: { total: 0, published: 0, configured: 0, validation_requested: 0, private: 0, shared: 0, public: 0 }, items: [] }
}

function emptySessions(): SessionDashboard {
  return { summary: { total: 0, active: 0, queued: 0, closed: 0 }, items: [] }
}

function responseError(path: string, response: Response): SpatialApiError {
  const category = response.status === 401 ? 'unauthorized'
    : response.status === 403 ? 'forbidden'
      : response.status === 404 ? 'not-found'
        : response.status === 409 ? 'conflict'
          : response.status === 422 ? 'validation'
            : 'unknown'
  return new SpatialApiError(category, `Dashboard request failed with HTTP ${response.status}.`, path, response.status)
}

async function requestDashboard<T>(
  path: string,
  schema: z.ZodType<T>,
  scope: SpatialNodeScope,
  options: Required<Pick<DashboardSpatialAdapterOptions, 'apiRoot' | 'fetcher' | 'timeoutMs'>>,
  signal?: AbortSignal,
): Promise<T> {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), options.timeoutMs)
  const forwardAbort = () => controller.abort()
  signal?.addEventListener('abort', forwardAbort, { once: true })
  try {
    const response = await options.fetcher(`${options.apiRoot}${path}`, {
      headers: {
        Accept: 'application/json',
        'X-AiDN-Hypervisor-Id': scope.hypervisor_id,
        'X-AiDN-Node-Id': scope.node_id,
      },
      signal: controller.signal,
    })
    const text = await response.text()
    let payload: unknown
    try { payload = text ? JSON.parse(text) : null } catch {
      throw new SpatialApiError('malformed', 'Dashboard response was not valid JSON.', path, response.status)
    }
    if (!response.ok) throw responseError(path, response)
    const parsed = schema.safeParse(payload)
    if (!parsed.success) throw new SpatialApiError('malformed', 'Dashboard response did not match its typed contract.', path, response.status)
    return parsed.data
  } catch (error) {
    if (error instanceof SpatialApiError) throw error
    if (controller.signal.aborted && !signal?.aborted) throw new SpatialApiError('timeout', 'Dashboard request timed out.', path)
    throw new SpatialApiError('network', 'Dashboard transport is unavailable.', path)
  } finally {
    clearTimeout(timeout)
    signal?.removeEventListener('abort', forwardAbort)
  }
}

async function loadDashboardPayload(
  scope: SpatialNodeScope,
  options: Required<Pick<DashboardSpatialAdapterOptions, 'apiRoot' | 'fetcher' | 'timeoutMs'>>,
  now: () => Date,
  signal?: AbortSignal,
): Promise<DashboardPayload> {
  const requests = [
    { name: 'fleet', path: '/operators/dashboard/fleet', promise: requestDashboard('/operators/dashboard/fleet', dashboardSchemas.fleet, scope, options, signal) },
    { name: 'endpoints', path: '/operators/dashboard/endpoints', promise: requestDashboard('/operators/dashboard/endpoints', dashboardSchemas.endpoints, scope, options, signal) },
    { name: 'sessions', path: '/operators/dashboard/sessions', promise: requestDashboard('/operators/dashboard/sessions', dashboardSchemas.sessions, scope, options, signal) },
    { name: 'residentAgent', path: '/operators/dashboard/steward', promise: requestDashboard('/operators/dashboard/steward', dashboardSchemas.residentAgent, scope, options, signal) },
    { name: 'statusSummary', path: '/operators/dashboard/status/summary', promise: requestDashboard('/operators/dashboard/status/summary', dashboardStatusSummarySchema, scope, options, signal) },
  ] as const
  const results = await Promise.allSettled(requests.map((request) => request.promise))
  const values = new Map<string, unknown>()
  const failures: string[] = []
  results.forEach((result, index) => {
    const { name, path } = requests[index]
    if (result.status === 'fulfilled') values.set(name, result.value)
    else failures.push(path)
  })
  if (!values.has('fleet') && !values.has('endpoints') && !values.has('sessions') && !values.has('residentAgent')) {
    const firstFailure = results.find((result): result is PromiseRejectedResult => result.status === 'rejected')?.reason
    if (firstFailure instanceof SpatialApiError) throw firstFailure
    throw new SpatialApiError('network', 'No operator dashboard read-model is available.', '/operators/dashboard')
  }
  return {
    fleet: (values.get('fleet') as Fleet | undefined) ?? emptyFleet(scope),
    endpoints: (values.get('endpoints') as EndpointPayload | undefined) ?? emptyEndpoints(),
    sessions: (values.get('sessions') as SessionDashboard | undefined) ?? emptySessions(),
    residentAgent: (values.get('residentAgent') as ResidentAgentStatus | undefined) ?? null,
    statusSummary: (values.get('statusSummary') as DashboardStatusSummary | undefined) ?? null,
    failures,
    observedAt: now().toISOString(),
  }
}

function entityRecords(payload: DashboardPayload, scope: SpatialNodeScope, now: Date): SpatialCanonicalEntity[] {
  const revision = revisionFor(now)
  const observedAt = payload.observedAt
  const nodeId = nodeIdFor(scope, payload)
  const entities: SpatialCanonicalEntity[] = []
  const primaryId = `primary-agent-${slug(nodeId)}`
  const primary = primaryState(payload.residentAgent, payload.statusSummary)
  entities.push({
    ...canonicalEntityBase('agent', primaryId, nodeId, 'Resident Primary Agent', primary.state, primary.availability, revision, observedAt),
    role: 'PRIMARY',
    capability_refs: ['operator.read', 'operator.observe'],
  })

  payload.endpoints.items.forEach((endpoint, index) => {
    const id = endpoint.endpoint_id || `endpoint-${index + 1}`
    const state = endpointState(endpoint)
    entities.push({
      ...canonicalEntityBase('endpoint', id, nodeId, stringValue(endpoint.display_name, id), state.state, state.availability, revision + index + 1, observedAt),
      endpoint_type: stringValue(endpoint.model_class, endpoint.capabilities[0] ?? 'capability'),
      capability_refs: endpoint.capabilities.length ? endpoint.capabilities : ['endpoint.invoke'],
      owner_agent_ref: endpoint.local_agent_use ? `agent:${primaryId}` : undefined,
    })
  })

  payload.sessions.items.forEach((item, index) => {
    const session = record(item.session)
    const id = stringValue(session.session_id, `session-${index + 1}`)
    const state = sessionState(item)
    const label = stringValue(item.display_name, `${stringValue(session.endpoint_id, 'Endpoint')} session`)
    entities.push({
      ...canonicalEntityBase('session', id, nodeId, label, state.state, state.availability, revision + 100 + index, observedAt),
      session_type: 'SESSION',
      protocol_session_ref: id,
      actor_refs: [stringValue(session.client_wallet), stringValue(session.provider_wallet)].filter(Boolean),
    })
  })

  payload.fleet.bundles.forEach((bundle, index) => {
    const id = stringValue(bundle.bundle_id, `bundle-${index + 1}`)
    const enabled = booleanValue(bundle.enabled)
    const state = enabled && upper(bundle.registry_status, '') !== 'DISABLED' ? 'READY' : 'CONFIGURED'
    entities.push({
      ...canonicalEntityBase('artifact', id, nodeId, stringValue(bundle.model_id, id), state, enabled ? 'AVAILABLE' : 'DEGRADED', revision + 200 + index, observedAt),
      artifact_type: 'provider-bundle',
      provenance_ref: `artifact:${id}`,
      source_revision: numberValue(bundle.revision, index + 1),
    })
  })
  return entities
}

function relationRecords(payload: DashboardPayload, scope: SpatialNodeScope, now: Date, entities: readonly SpatialCanonicalEntity[]) {
  const revision = revisionFor(now)
  const observedAt = payload.observedAt
  const nodeId = nodeIdFor(scope, payload)
  const primary = entities.find((entity) => entity.kind === 'agent' && entity.role === 'PRIMARY')
  if (!primary) return []
  const relations: Array<{
    schema_version: 'spatial.relation.v1'
    relation_id: string
    node_id: string
    revision: number
    relation_type: string
    source_ref: string
    target_ref: string
    state: 'ACTIVE' | 'ARCHIVED' | 'UNKNOWN' | 'STALE' | 'UNAVAILABLE'
    freshness: ReturnType<typeof freshness>
    created_at: string
    updated_at: string
  }> = []
  entities.filter((entity) => entity.kind === 'endpoint').forEach((endpoint) => {
    relations.push({ schema_version: 'spatial.relation.v1', relation_id: `uses-${endpoint.id}`, node_id: nodeId, revision, relation_type: 'USES', source_ref: primary.canonical_ref, target_ref: endpoint.canonical_ref, state: 'ACTIVE', freshness: freshness(observedAt), created_at: observedAt, updated_at: observedAt })
  })
  entities.filter((entity) => entity.kind === 'session').forEach((session) => {
    relations.push({ schema_version: 'spatial.relation.v1', relation_id: `session-${session.id}`, node_id: nodeId, revision, relation_type: 'REQUEST', source_ref: primary.canonical_ref, target_ref: session.canonical_ref, state: session.state === 'ACTIVE' ? 'ACTIVE' : 'ARCHIVED', freshness: freshness(observedAt), created_at: observedAt, updated_at: observedAt })
  })
  return relations
}

function createWorkspaceSnapshot(payload: DashboardPayload, scope: SpatialNodeScope, now: Date): SpatialWorkspaceSnapshot {
  const entities = entityRecords(payload, scope, now)
  const revision = revisionFor(now)
  const observedAt = payload.observedAt
  const nodeId = nodeIdFor(scope, payload)
  const primary = entities.find((entity) => entity.kind === 'agent' && entity.role === 'PRIMARY')
  const raw = {
    schema_version: 'spatial.workspace.v1',
    workspace_id: `workspace-${nodeId}`,
    node_id: nodeId,
    revision,
    semantic_revision: revision,
    created_at: observedAt,
    updated_at: observedAt,
    entities,
    relations: relationRecords(payload, scope, now, entities),
    semantic_anchors: [],
    cluster_membership: {},
    primary_agent_ref: primary?.canonical_ref,
  }
  const parsed = parseSpatialWorkspace(raw)
  if (!parsed.ok) throw new SpatialApiError('malformed', 'Real dashboard data could not be normalized to Spatial Workspace.', '/operators/dashboard')
  return parsed.data
}

function createNodeStatus(payload: DashboardPayload, scope: SpatialNodeScope, now: Date): SpatialNodeStatus {
  const nodeId = nodeIdFor(scope, payload)
  const revision = revisionFor(now)
  const observedAt = payload.observedAt
  const primary = primaryState(payload.residentAgent, payload.statusSummary)
  const statusState = primary.availability === 'UNAVAILABLE' ? 'DEGRADED' : primary.availability === 'DEGRADED' ? 'DEGRADED' : 'ONLINE'
  const statusFreshness = freshness(observedAt)
  const component = (componentId: string, componentType: string, kind: string, state: string, details?: Record<string, unknown>) => ({
    component_id: componentId,
    component_type: componentType,
    kind,
    state,
    observed_at: observedAt,
    freshness: statusFreshness,
    source: 'operators.dashboard',
    revision,
    ...(details ? { details } : {}),
  })
  const raw = {
    schema_version: 'spatial.node-status.v1',
    node_id: nodeId,
    revision,
    state: statusState,
    observed_at: observedAt,
    freshness: statusFreshness,
    components: [
      component(`node-${nodeId}`, 'Node', 'node', statusState),
      component(`primary-${nodeId}`, 'Primary Agent', 'primary-agent', primary.state, { identity: payload.residentAgent?.model.repo ?? 'resident-agent' }),
      component(`endpoints-${nodeId}`, 'Endpoints', 'endpoints', payload.endpoints.items.length ? 'READY' : 'UNKNOWN', { count: payload.endpoints.items.length }),
      component(`sessions-${nodeId}`, 'Sessions', 'sessions', payload.sessions.summary.active > 0 ? 'RUNNING' : 'READY', { count: payload.sessions.items.length }),
      component(`bundles-${nodeId}`, 'Provider Bundles', 'providers', payload.fleet.bundles.length ? 'READY' : 'UNKNOWN', { count: payload.fleet.bundles.length }),
      component(`runtimes-${nodeId}`, 'Runtimes', 'runtimes', payload.statusSummary?.runtimes.length ? 'RUNNING' : 'UNKNOWN', { count: payload.statusSummary?.runtimes.length ?? 0 }),
    ],
    partial: payload.failures.length > 0,
    cached: false,
    active_sessions: payload.sessions.summary.active,
    running_tasks: payload.statusSummary?.queue?.active ?? payload.fleet.queue.active,
    active_endpoints: payload.endpoints.summary.published,
    warning_count: payload.failures.length,
  }
  const parsed = parseSpatialNodeStatus(raw)
  if (!parsed.ok) throw new SpatialApiError('malformed', 'Real dashboard status could not be normalized to Spatial Node status.', '/operators/dashboard/status/summary')
  return parsed.data
}

function endpointPosition(index: number, count: number): Vector3Tuple {
  const columns = Math.min(4, Math.max(2, Math.ceil(Math.sqrt(Math.max(1, count)))))
  const row = Math.floor(index / columns)
  const column = index % columns
  const width = (columns - 1) * 0.58
  return [1.05 + column * 0.58 - width / 2, 3.12 + row * 0.48 + (hash(`endpoint-y-${index}`) % 10) * 0.012, 0.30 + (hash(`endpoint-z-${index}`) % 16) * 0.025]
}

function agentPosition(index: number): Vector3Tuple {
  const column = index % 3
  const row = Math.floor(index / 3)
  return [-2.55 + column * 0.72, 3.44 + row * 0.58 + (hash(`agent-y-${index}`) % 8) * 0.015, 0.46 - column * 0.17]
}

function artifactPosition(index: number, count: number, id: string): Vector3Tuple {
  const columns = Math.min(7, Math.max(5, Math.ceil(Math.sqrt(Math.max(1, count) * 1.55))))
  const row = Math.floor(index / columns)
  const column = index % columns
  const xStart = -3.05
  const xGap = columns >= 7 ? 0.82 : 0.96
  const zStart = 1.55
  const zGap = columns >= 7 ? 0.66 : 0.73
  const jitterX = ((hash(`${id}:x`) % 19) - 9) / 100
  const jitterZ = ((hash(`${id}:z`) % 17) - 8) / 120
  return [xStart + column * xGap + jitterX, 0.56 + (hash(`${id}:y`) % 9) * 0.012, zStart - row * zGap + jitterZ]
}

function orbConfig(id: string, position: Vector3Tuple, radius: number, color: string, phase: number): OrbConfig {
  return {
    id,
    position,
    radius,
    colorPulse: { color, amount: 0.24 },
    material: { ...DEFAULT_CALIBRATION.orb.material, color: '#e9f4ff' },
    motion: { driftAmplitude: 0.045 + phase * 0.006, driftFrequency: 0.22 + phase * 0.03, pulseAmplitude: 0.025, pulseFrequency: 0.72 + phase * 0.05 },
  }
}

function cubeConfig(id: string, position: Vector3Tuple, size: number, color: string, index: number, kind: 'session' | 'artifact'): CubeConfig {
  return {
    id,
    position,
    size,
    cluster: kind === 'session' ? 'active' : 'new',
    baseYaw: ((hash(`${id}:yaw`) % 120) - 60) / 100,
    basePitch: ((hash(`${id}:pitch`) % 24) - 12) / 100,
    baseRoll: ((hash(`${id}:roll`) % 20) - 10) / 100,
    material: { ...DEFAULT_CALIBRATION.cube.material, color, attenuationColor: shade(color, 0.62) },
    motion: {
      driftAmplitude: 0.028 + (index % 4) * 0.006,
      driftFrequency: 0.18 + (index % 5) * 0.025,
      pitchSpeed: (index % 2 ? -1 : 1) * (0.018 + (index % 3) * 0.005),
      yawSpeed: (index % 2 ? 1 : -1) * (0.032 + (index % 4) * 0.006),
      rollSpeed: (index % 3 ? 1 : -1) * 0.014,
    },
  }
}

function liveConnections(
  primaryId: string,
  endpoints: ReadonlyArray<EndpointConfig>,
  artifacts: ReadonlyArray<CubeConfig>,
): ConnectionConfig[] {
  const connections: ConnectionConfig[] = []
  endpoints.forEach((endpoint, index) => {
    connections.push({
      id: `primary-${endpoint.id}-thread`, sourceId: primaryId, targetId: endpoint.id,
      color: endpoint.coronaColor, opacity: 0.25,
      startOffset: [0.58 + index * 0.035, 0.18 + (index % 2) * 0.06, 0.06],
      endOffset: [-0.10, -0.01, 0], bendA: [0.18 + index * 0.035, 0.26, 0.22], bendB: [0.22 + index * 0.028, 0.20, 0.18],
      motion: { flowSpeed: 0.068 + index * 0.006, beadSpacing: 0.90, phase: 0.18 + index * 0.10 },
    })
  })
  artifacts.slice(0, 8).forEach((artifact, index) => {
    connections.push({
      id: `primary-${artifact.id}-thread`, sourceId: primaryId, targetId: artifact.id,
      color: artifact.material.color, opacity: 0.18,
      startOffset: [0.34 + (index % 3) * 0.10, -0.30 + (index % 2) * 0.08, 0.10],
      endOffset: [-0.10, 0.12, 0], bendA: [0.20 + index * 0.03, -0.20, 0.20], bendB: [0.16 + index * 0.035, -0.10, 0.18],
      motion: { flowSpeed: 0.062 + index * 0.006, beadSpacing: 0.94, phase: 0.42 + index * 0.08 },
    })
  })
  return connections
}

function sceneFromSnapshot(snapshot: SpatialWorkspaceSnapshot, status: SpatialNodeStatus | null, source: DashboardSpatialSceneSource): DashboardSpatialSceneData {
  const projection = composeSpatialWorkspaceViewModel(snapshot, status, 'desktop')
  const primaryId = projection.primaryAgent?.id ?? `primary-agent-${slug(snapshot.node_id)}`
  const primaryConfig = orbConfig(primaryId, [...DEFAULT_CALIBRATION.orb.position], 1, '#ef9c8e', 0.8)
  const agentModels = projection.entities.filter((entity) => entity.canonicalKind === 'agent')
  const agents = agentModels.map((entity, index) => orbConfig(entity.id, agentPosition(index), 0.22 + (hash(entity.id) % 8) * 0.012, paletteColor(AGENT_PALETTE, entity.id, entity.visualState), index + 1))
  const endpointModels = projection.entities.filter((entity) => entity.canonicalKind === 'endpoint')
  const endpoints = endpointModels.map((entity, index) => {
    const color = paletteColor(ENDPOINT_PALETTE, entity.id, entity.visualState)
    const meteorA = paletteColor(AGENT_PALETTE, `${entity.id}:a`, entity.visualState)
    const meteorB = paletteColor(ENDPOINT_PALETTE, `${entity.id}:b`, entity.visualState)
    const meteorC = paletteColor(ARTIFACT_PALETTE, `${entity.id}:c`, entity.visualState)
    return {
      id: entity.id, position: endpointPosition(index, endpointModels.length), radius: 0.18 + (hash(entity.id) % 8) * 0.012,
      coreColor: '#fbfffd', coronaColor: color, meteorColors: [meteorA, meteorB, meteorC] as [string, string, string],
      orbitRadius: 0.36 + (hash(`${entity.id}:orbit`) % 12) * 0.012, orbitSpeed: 0.17 + (hash(`${entity.id}:speed`) % 10) * 0.008, trailAngle: 0.58,
      driftAmplitude: 0.032 + (index % 4) * 0.007, driftFrequency: 0.22 + (index % 5) * 0.018,
    } satisfies EndpointConfig
  })
  const artifactModels = projection.entities.filter((entity) => entity.canonicalKind === 'session' || entity.canonicalKind === 'artifact')
  const artifactConfigs = artifactModels.map((entity, index) => {
    const color = paletteColor(ARTIFACT_PALETTE, entity.id, entity.visualState)
    const kind = entity.canonicalKind === 'session' ? 'session' : 'artifact'
    return cubeConfig(entity.id, artifactPosition(index, artifactModels.length, entity.id), 0.27 + (hash(`${entity.id}:size`) % 18) * 0.012, color, index, kind)
  })
  const [firstArtifact, ...restArtifacts] = artifactConfigs
  const cube = firstArtifact ?? { ...DEFAULT_CALIBRATION.cube, id: 'calibration-cube', position: [...DEFAULT_CALIBRATION.cube.position] as Vector3Tuple }
  const connections = liveConnections(primaryId, endpoints, artifactConfigs)
  const config: CalibrationConfig = {
    ...DEFAULT_CALIBRATION,
    orb: primaryConfig,
    cube,
    agents,
    artifacts: restArtifacts,
    connections,
  }
  return { config, endpoints, source, projection }
}

export function createDashboardSpatialLoaders(options: DashboardSpatialAdapterOptions = {}): DashboardSpatialLoaders {
  const requestOptions = {
    apiRoot: (options.apiRoot ?? '').replace(/\/$/, ''),
    fetcher: options.fetcher ?? ((input, init) => fetch(input, init)),
    timeoutMs: options.timeoutMs ?? 15_000,
  }
  const now = options.now ?? (() => new Date())
  let cache: { expiresAt: number; scopeKey: string; payload: DashboardPayload } | null = null
  async function load(scope: SpatialNodeScope, signal?: AbortSignal): Promise<DashboardPayload> {
    const scopeKey = `${requestOptions.apiRoot}|${scope.hypervisor_id}|${scope.node_id}`
    if (cache && cache.scopeKey === scopeKey && cache.expiresAt > Date.now()) return cache.payload
    const payload = await loadDashboardPayload(scope, requestOptions, now, signal)
    cache = { scopeKey, payload, expiresAt: Date.now() + (options.cacheTtlMs ?? 4_000) }
    return payload
  }
  return {
    workspace: async (scope, signal) => {
      const payload = await load(scope, signal)
      return createWorkspaceSnapshot(payload, scope, now())
    },
    status: async (scope, signal) => {
      const payload = await load(scope, signal)
      return createNodeStatus(payload, scope, now())
    },
  }
}

export function createDashboardSpatialScene(
  snapshot: SpatialWorkspaceSnapshot,
  status: SpatialNodeStatus | null = null,
  sourceOverrides: Partial<DashboardSpatialSceneSource> = {},
): DashboardSpatialSceneData {
  const counts = snapshot.entities.reduce((result, entity) => {
    if (entity.kind === 'endpoint') result.endpointCount += 1
    if (entity.kind === 'session') result.sessionCount += 1
    if (entity.kind === 'artifact') result.bundleCount += 1
    if (entity.kind === 'agent' && entity.role !== 'PRIMARY') result.subagentCount += 1
    return result
  }, { endpointCount: 0, sessionCount: 0, bundleCount: 0, subagentCount: 0 })
  const source: DashboardSpatialSceneSource = {
    nodeId: snapshot.node_id,
    state: sourceOverrides.state ?? (status?.partial ? 'partial' : 'live'),
    revision: sourceOverrides.revision ?? snapshot.semantic_revision,
    endpointCount: sourceOverrides.endpointCount ?? counts.endpointCount,
    sessionCount: sourceOverrides.sessionCount ?? counts.sessionCount,
    bundleCount: sourceOverrides.bundleCount ?? counts.bundleCount,
    subagentCount: sourceOverrides.subagentCount ?? counts.subagentCount,
    failedSources: sourceOverrides.failedSources ?? [],
  }
  return sceneFromSnapshot(snapshot, status, source)
}

/** Pure adapter seam for tests and local fixture-driven development. */
export function createDashboardSpatialSnapshotForPayload(
  payload: {
    readonly fleet: Fleet
    readonly endpoints: EndpointPayload
    readonly sessions: SessionDashboard
    readonly residentAgent?: ResidentAgentStatus | null
    readonly statusSummary?: DashboardStatusSummary | null
    readonly failures?: readonly string[]
    readonly observedAt?: string
  },
  scope: SpatialNodeScope,
  now = new Date(),
): { snapshot: SpatialWorkspaceSnapshot; status: SpatialNodeStatus; scene: DashboardSpatialSceneData } {
  const normalized: DashboardPayload = {
    fleet: payload.fleet,
    endpoints: payload.endpoints,
    sessions: payload.sessions,
    residentAgent: payload.residentAgent ?? null,
    statusSummary: payload.statusSummary ?? null,
    failures: payload.failures ?? [],
    observedAt: payload.observedAt ?? now.toISOString(),
  }
  const snapshot = createWorkspaceSnapshot(normalized, scope, now)
  const status = createNodeStatus(normalized, scope, now)
  const scene = sceneFromSnapshot(snapshot, status, {
    nodeId: snapshot.node_id,
    state: normalized.failures.length ? 'partial' : 'live',
    revision: snapshot.semantic_revision,
    endpointCount: normalized.endpoints.items.length,
    sessionCount: normalized.sessions.items.length,
    bundleCount: normalized.fleet.bundles.length,
    subagentCount: snapshot.entities.filter((entity) => entity.kind === 'agent' && entity.role !== 'PRIMARY').length,
    failedSources: normalized.failures,
  })
  return { snapshot, status, scene }
}
