import {
  parseSpatialNodeStatus,
  SPATIAL_SCHEMA_VERSIONS,
  SPATIAL_NODE_STATUS_STATES,
  type SpatialNodeStatus,
  type SpatialStatusComponent,
  type SpatialStatusComponentKind,
  type SpatialRecoveryAction,
  type SpatialStatusDetails,
  type SpatialNodeStatusState,
} from '@/spatial/contracts'

export type StatusProbeObservation = {
  component_id: string
  component_type: string
  kind?: SpatialStatusComponentKind
  state: SpatialNodeStatusState
  observed_at?: string | Date
  stale_after_seconds?: number
  source: string
  revision?: number
  evidence_refs?: SpatialStatusComponent['evidence_refs']
  issue_code?: string | null
  available_actions?: SpatialRecoveryAction[]
  spatial_ref?: string | null
  authorization?: SpatialStatusComponent['authorization']
  details?: SpatialStatusDetails
}

export type StatusProbe = {
  component_id: string
  component_type: string
  kind: SpatialStatusComponentKind
  probe: () => StatusProbeObservation | Promise<StatusProbeObservation>
}

export type StatusAggregatorOptions = {
  nodeId: string
  now?: () => Date
  staleAfterSeconds?: number
  revision?: number
  cachedSnapshot?: SpatialNodeStatus | null
}

export type StatusAggregatorRefresh = {
  snapshot: SpatialNodeStatus
  failed: string[]
}

export class SpatialStatusAggregatorError extends Error {
  readonly code: 'INVALID_NODE' | 'INVALID_SNAPSHOT' | 'STALE_REVISION'

  constructor(code: SpatialStatusAggregatorError['code'], message: string) {
    super(message)
    this.name = 'SpatialStatusAggregatorError'
    this.code = code
  }
}

function asDate(value: string | Date | undefined, fallback: Date): Date {
  const date = value instanceof Date ? value : value ? new Date(value) : fallback
  if (!Number.isFinite(date.getTime())) throw new SpatialStatusAggregatorError('INVALID_SNAPSHOT', 'Status observation time is invalid.')
  return date
}

function freshnessState(observations: readonly SpatialStatusComponent[], partial: boolean, now: Date): SpatialNodeStatus['freshness']['state'] {
  if (partial) return 'PARTIAL'
  if (observations.some((item) => item.freshness.state === 'UNKNOWN' || item.freshness.state === 'UNAVAILABLE')) return 'UNKNOWN'
  if (observations.some((item) => item.freshness.state === 'STALE')) return 'STALE'
  return observations.some((item) => (now.getTime() - Date.parse(item.observed_at)) / 1000 > item.freshness.stale_after_seconds)
    ? 'STALE'
    : 'FRESH'
}

function stateRank(state: SpatialNodeStatusState): number {
  const ranks: Record<SpatialNodeStatusState, number> = {
    ONLINE: 1,
    READY: 1,
    RUNNING: 1,
    STARTING: 2,
    STOPPING: 2,
    RESTARTING: 2,
    DEGRADED: 3,
    STALE: 4,
    BLOCKED: 5,
    DISCONNECTED: 5,
    OFFLINE: 6,
    UNKNOWN: 7,
  }
  return ranks[state]
}

function aggregateState(components: readonly SpatialStatusComponent[], partial: boolean): SpatialNodeStatusState {
  if (!components.length) return 'UNKNOWN'
  if (partial && components.every((component) => component.state === 'UNKNOWN')) return 'UNKNOWN'
  if (partial) return 'DEGRADED'
  const worst = components.reduce((current, component) => stateRank(component.state) > stateRank(current) ? component.state : current, 'ONLINE' as SpatialNodeStatusState)
  if (worst === 'OFFLINE' && components.some((component) => component.kind === 'node' && component.state === 'OFFLINE')) return 'OFFLINE'
  if (worst === 'ONLINE' || worst === 'READY' || worst === 'RUNNING') return 'ONLINE'
  return worst
}

function safeText(value: unknown, max = 240): string | undefined {
  if (typeof value !== 'string') return undefined
  const normalized = Array.from(value.trim()).filter((character) => {
    const code = character.charCodeAt(0)
    return code > 0x1f && code !== 0x7f
  }).join('')
  return normalized ? normalized.slice(0, max) : undefined
}

function redactEvidence(refs: StatusProbeObservation['evidence_refs']): SpatialStatusComponent['evidence_refs'] {
  return (refs ?? []).slice(0, 32).map((ref) => ({
    ref: safeText(ref.ref, 256) ?? 'redacted-evidence',
    kind: safeText(ref.kind, 64),
    label: safeText(ref.label, 240),
    observed_at: ref.observed_at,
    authorized: ref.authorized !== false,
    redacted: ref.redacted === true || ref.authorized === false,
  }))
}

function redactDetails(details: SpatialStatusDetails | undefined): SpatialStatusDetails | undefined {
  if (!details) return undefined
  return {
    identity: safeText(details.identity),
    runtime: safeText(details.runtime),
    connection: safeText(details.connection),
    last_events: details.last_events.slice(0, 20).map((event) => ({
      id: safeText(event.id, 256) ?? 'event',
      occurred_at: event.occurred_at,
      state: safeText(event.state, 96) ?? 'UNKNOWN',
      message: safeText(event.message),
    })),
    safe_raw_evidence: details.safe_raw_evidence.slice(0, 20).map((item) => safeText(item, 512) ?? '').filter(Boolean),
    authorization: details.authorization,
  }
}

function componentFromObservation(observation: StatusProbeObservation, now: Date, staleAfterSeconds: number): SpatialStatusComponent {
  const observedAt = asDate(observation.observed_at, now)
  const ttl = Number.isFinite(observation.stale_after_seconds) && (observation.stale_after_seconds ?? 0) >= 0
    ? observation.stale_after_seconds as number
    : staleAfterSeconds
  const ageSeconds = Math.max(0, (now.getTime() - observedAt.getTime()) / 1000)
  const freshnessState = ageSeconds > ttl ? 'STALE' : observation.state === 'UNKNOWN' ? 'UNKNOWN' : 'FRESH'
  return {
    component_id: safeText(observation.component_id, 256) ?? 'unknown-component',
    component_type: safeText(observation.component_type, 240) ?? 'Unknown component',
    kind: observation.kind ?? 'other',
    state: observation.state,
    observed_at: observedAt.toISOString(),
    freshness: {
      state: freshnessState,
      observed_at: observedAt.toISOString(),
      stale_after_seconds: ttl,
      source: safeText(observation.source, 128) ?? 'node-status-aggregator',
    },
    source: safeText(observation.source, 128) ?? 'node-status-aggregator',
    revision: observation.revision,
    evidence_refs: redactEvidence(observation.evidence_refs),
    issue_code: safeText(observation.issue_code, 96) ?? null,
    available_actions: (observation.available_actions ?? []).filter((action) => (SPATIAL_NODE_STATUS_STATES as readonly string[]).includes(observation.state) && Boolean(action)),
    spatial_ref: observation.spatial_ref ?? null,
    authorization: observation.authorization ?? 'AUTHORIZED',
    details: redactDetails(observation.details),
  }
}

/**
 * Node-owned status reducer. It accepts direct probe evidence only; there is
 * deliberately no Agent/LLM callback in this API. A failed probe becomes an
 * explicit UNKNOWN component and never erases the rest of the snapshot.
 */
export class SpatialStatusAggregator {
  private readonly nodeId: string
  private readonly now: () => Date
  private readonly staleAfterSeconds: number
  private revision: number
  private current: SpatialNodeStatus | null

  constructor(options: StatusAggregatorOptions) {
    const nodeId = options.nodeId.trim()
    if (!nodeId) throw new SpatialStatusAggregatorError('INVALID_NODE', 'nodeId is required.')
    this.nodeId = nodeId
    this.now = options.now ?? (() => new Date())
    this.staleAfterSeconds = Math.max(0, options.staleAfterSeconds ?? 900)
    this.revision = Math.max(0, options.revision ?? options.cachedSnapshot?.revision ?? 0)
    this.current = options.cachedSnapshot ? this.ingest(options.cachedSnapshot) : null
  }

  private nowDate(): Date {
    const date = this.now()
    if (!Number.isFinite(date.getTime())) throw new SpatialStatusAggregatorError('INVALID_SNAPSHOT', 'Aggregator clock is invalid.')
    return date
  }

  private build(observations: readonly StatusProbeObservation[], failed: readonly string[], context: { activeSessions?: number; runningTasks?: number; activeEndpoints?: number } = {}): SpatialNodeStatus {
    const now = this.nowDate()
    const components = observations.map((observation) => componentFromObservation(observation, now, this.staleAfterSeconds))
    const partial = failed.length > 0
    const state = aggregateState(components, partial)
    const revision = Math.max(this.revision + 1, ...components.map((component) => component.revision ?? 0))
    const freshness = freshnessState(components, partial, now)
    const lastKnown = this.current?.last_known_at ?? null
    const candidate = {
      schema_version: SPATIAL_SCHEMA_VERSIONS.status,
      node_id: this.nodeId,
      revision,
      node_revision: revision,
      state,
      overall_state: state,
      observed_at: now.toISOString(),
      generated_at: now.toISOString(),
      freshness: {
        state: freshness,
        observed_at: now.toISOString(),
        stale_after_seconds: this.staleAfterSeconds,
        source: 'node-status-aggregator',
      },
      components,
      partial,
      cached: false,
      last_known_at: lastKnown,
      active_sessions: Math.max(0, context.activeSessions ?? 0),
      running_tasks: Math.max(0, context.runningTasks ?? 0),
      active_endpoints: Math.max(0, context.activeEndpoints ?? 0),
      warning_count: components.filter((component) => !['ONLINE', 'READY', 'RUNNING'].includes(component.state)).length,
      evidence_refs: components.flatMap((component) => component.evidence_refs).slice(0, 64),
      provenance: { canonical_ref: `node:${this.nodeId}`, revision, source: 'node-status-aggregator' },
    }
    const parsed = parseSpatialNodeStatus(candidate)
    if (!parsed.ok) throw new SpatialStatusAggregatorError('INVALID_SNAPSHOT', `Status snapshot rejected at ${parsed.diagnostic.path}.`)
    this.revision = parsed.data.revision
    this.current = parsed.data
    return parsed.data
  }

  async refresh(probes: readonly StatusProbe[], context: { activeSessions?: number; runningTasks?: number; activeEndpoints?: number } = {}): Promise<StatusAggregatorRefresh> {
    const settled = await Promise.allSettled(probes.map((probe) => Promise.resolve().then(() => probe.probe())))
    const observations: StatusProbeObservation[] = []
    const failed: string[] = []
    settled.forEach((result, index) => {
      const probe = probes[index]
      if (result.status === 'fulfilled') {
        observations.push({ ...result.value, component_id: probe.component_id, component_type: probe.component_type, kind: probe.kind })
      } else {
        failed.push(probe.component_id)
        observations.push({
          component_id: probe.component_id,
          component_type: probe.component_type,
          kind: probe.kind,
          state: 'UNKNOWN',
          source: `probe.${probe.kind}`,
          issue_code: 'PROBE_UNAVAILABLE',
          available_actions: [],
        })
      }
    })
    return { snapshot: this.build(observations, failed, context), failed }
  }

  ingest(snapshot: SpatialNodeStatus): SpatialNodeStatus {
    if (snapshot.node_id !== this.nodeId) throw new SpatialStatusAggregatorError('INVALID_NODE', 'Status snapshot belongs to another Node.')
    if (this.current && snapshot.revision < this.current.revision) throw new SpatialStatusAggregatorError('STALE_REVISION', 'Status snapshot revision is older than the current snapshot.')
    const parsed = parseSpatialNodeStatus(snapshot)
    if (!parsed.ok) throw new SpatialStatusAggregatorError('INVALID_SNAPSHOT', `Status snapshot rejected at ${parsed.diagnostic.path}.`)
    this.revision = parsed.data.revision
    this.current = parsed.data
    return parsed.data
  }

  read(): SpatialNodeStatus | null {
    return this.current ? { ...this.current, components: this.current.components.map((component) => ({ ...component })) } : null
  }

  readCached(): SpatialNodeStatus | null {
    const current = this.read()
    if (!current) return null
    const now = this.nowDate()
    return {
      ...current,
      state: current.state === 'ONLINE' || current.state === 'READY' || current.state === 'RUNNING' ? 'STALE' : current.state,
      overall_state: current.overall_state === 'ONLINE' || current.overall_state === 'READY' || current.overall_state === 'RUNNING' ? 'STALE' : current.overall_state,
      cached: true,
      last_known_at: current.observed_at,
      freshness: { ...current.freshness, state: 'STALE', observed_at: current.observed_at },
      components: current.components.map((component) => ({
        ...component,
        state: ['ONLINE', 'READY', 'RUNNING'].includes(component.state) ? 'STALE' : component.state,
        freshness: { ...component.freshness, state: 'STALE' },
      })),
      observed_at: now.toISOString(),
      generated_at: now.toISOString(),
    }
  }
}

export const NodeStatusAggregator = SpatialStatusAggregator
