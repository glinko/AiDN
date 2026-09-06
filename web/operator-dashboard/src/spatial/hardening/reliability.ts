import {
  parseSpatialReliabilityIncident,
  SPATIAL_RELIABILITY_FAULTS,
  SPATIAL_SCHEMA_VERSIONS,
  type SpatialReliabilityFault,
  type SpatialReliabilityIncident,
  type SpatialReliabilityState,
} from '@/spatial/contracts'

export const RELIABILITY_RECOVERY_ACTIONS: Record<SpatialReliabilityFault, string> = {
  EVENT_DISCONNECT: 'pause-stream-and-reconnect',
  EVENT_REORDER: 'replay-from-last-revision',
  EVENT_DUPLICATE: 'dedupe-by-event-id',
  API_PARTIAL_OUTAGE: 'degrade-to-cached-read',
  AGENT_FAILURE: 'mark-agent-offline-and-retry-safe',
  AGENT_REPLACED: 'invalidate-grant-and-rebind',
  HOOK_DEAD_LETTER: 'hold-for-explicit-retry',
  WORKSPACE_CONFLICT: 'request-fresh-revision',
  CORRUPT_PRESENTATION: 'rebuild-from-canonical',
  STALE_STATUS: 'show-stale-and-refresh',
  ENDPOINT_TIMEOUT: 'cancel-without-duplicate-charge',
  MALICIOUS_REMOTE_OUTPUT: 'quarantine-remote-result',
  BROWSER_SLEEP: 'pause-and-reconcile-on-wake',
  NODE_SWITCH: 'invalidate-node-cache-and-reload',
  RENDERER_CONTEXT_LOSS: 'rebuild-renderer-from-canonical',
}

export const RELIABILITY_INVARIANTS = [
  'no-silent-data-loss',
  'no-incorrect-green-status',
  'no-duplicate-action',
  'no-duplicate-charge',
  'recovery-visible',
  'classic-fallback-available',
  'renderer-rebuilds-from-canonical',
] as const

export type ReliabilityInvariant = (typeof RELIABILITY_INVARIANTS)[number]
export type ReliabilityInvariantResult = 'PASS' | 'FAIL' | 'UNKNOWN'

export type ReliabilityFaultInput = {
  workspaceId: string
  nodeId: string
  correlationId?: string | null
  sourceRevision?: number | null
  now?: string | Date
  invariantResults?: Partial<Record<ReliabilityInvariant, ReliabilityInvariantResult>>
}

export type SpatialReliabilityControllerOptions = {
  idFactory?: (prefix: string) => string
  now?: () => string
}

const DEFAULT_INVARIANTS: Record<ReliabilityInvariant, ReliabilityInvariantResult> = {
  'no-silent-data-loss': 'UNKNOWN',
  'no-incorrect-green-status': 'UNKNOWN',
  'no-duplicate-action': 'UNKNOWN',
  'no-duplicate-charge': 'UNKNOWN',
  'recovery-visible': 'UNKNOWN',
  'classic-fallback-available': 'UNKNOWN',
  'renderer-rebuilds-from-canonical': 'UNKNOWN',
}

const DEFAULT_ID = (prefix: string): string => `${prefix}:${Math.random().toString(36).slice(2, 12)}`

function isoNow(value: string | Date | undefined, fallback: () => string): string {
  if (value instanceof Date) return value.toISOString()
  if (typeof value === 'string' && Number.isFinite(Date.parse(value))) return new Date(value).toISOString()
  return fallback()
}

function invariantRecord(input?: Partial<Record<ReliabilityInvariant, ReliabilityInvariantResult>>): Record<string, ReliabilityInvariantResult> {
  return { ...DEFAULT_INVARIANTS, ...input }
}

/**
 * Fault handling is deliberately explicit. An incident cannot become green
 * until every safety invariant is PASS and recovery has been observed.
 */
export class SpatialReliabilityController {
  private readonly idFactory: (prefix: string) => string
  private readonly now: () => string
  private readonly incidents = new Map<string, SpatialReliabilityIncident>()
  private readonly actionKeys = new Set<string>()

  public constructor(options: SpatialReliabilityControllerOptions = {}) {
    this.idFactory = options.idFactory ?? DEFAULT_ID
    this.now = options.now ?? (() => new Date().toISOString())
  }

  public open(fault: SpatialReliabilityFault, input: ReliabilityFaultInput): SpatialReliabilityIncident {
    if (!SPATIAL_RELIABILITY_FAULTS.includes(fault)) throw new Error('unsupported reliability fault')
    const openedAt = isoNow(input.now, this.now)
    const parsed = parseSpatialReliabilityIncident({
      schema_version: SPATIAL_SCHEMA_VERSIONS.reliabilityIncident,
      incident_id: this.idFactory('incident'),
      workspace_id: input.workspaceId,
      node_id: input.nodeId,
      fault,
      state: 'OPEN',
      recovery_action: RELIABILITY_RECOVERY_ACTIONS[fault],
      invariant_results: invariantRecord(input.invariantResults),
      source_revision: input.sourceRevision ?? null,
      correlation_id: input.correlationId ?? null,
      opened_at: openedAt,
      updated_at: openedAt,
    })
    if (!parsed.ok) throw new Error(`invalid reliability incident: ${parsed.diagnostic.path}`)
    this.incidents.set(parsed.data.incident_id, parsed.data)
    return parsed.data
  }

  public contain(incidentId: string, invariantResults?: Partial<Record<ReliabilityInvariant, ReliabilityInvariantResult>>): SpatialReliabilityIncident {
    const incident = this.require(incidentId)
    if (incident.state === 'RECOVERED') return incident
    return this.update(incident, 'CONTAINED', invariantResults)
  }

  public recover(incidentId: string, invariantResults: Partial<Record<ReliabilityInvariant, ReliabilityInvariantResult>>): SpatialReliabilityIncident {
    const incident = this.require(incidentId)
    const merged = { ...incident.invariant_results, ...invariantResults }
    const allPass = RELIABILITY_INVARIANTS.every((name) => merged[name] === 'PASS')
    if (!allPass) return this.update(incident, 'ESCALATED', merged)
    return this.update(incident, 'RECOVERED', merged)
  }

  public executeRecovery(incidentId: string, actionKey: string): SpatialReliabilityIncident {
    const incident = this.require(incidentId)
    if (incident.state === 'RECOVERED') return incident
    const key = `${incidentId}:${actionKey}`
    if (this.actionKeys.has(key)) return incident
    if (actionKey !== incident.recovery_action) throw new Error('recovery action does not match incident')
    this.actionKeys.add(key)
    return this.update(incident, 'CONTAINED', { 'recovery-visible': 'PASS' })
  }

  public get(incidentId: string): SpatialReliabilityIncident | undefined {
    return this.incidents.get(incidentId)
  }

  public list(): SpatialReliabilityIncident[] {
    return [...this.incidents.values()]
  }

  public isSafeForGreen(incidentId: string): boolean {
    const incident = this.require(incidentId)
    return incident.state === 'RECOVERED' && RELIABILITY_INVARIANTS.every((name) => incident.invariant_results[name] === 'PASS')
  }

  public requireClassicFallback(incidentId: string): boolean {
    const incident = this.require(incidentId)
    return incident.state !== 'RECOVERED' || incident.invariant_results['classic-fallback-available'] !== 'PASS'
  }

  private require(incidentId: string): SpatialReliabilityIncident {
    const incident = this.incidents.get(incidentId)
    if (!incident) throw new Error(`unknown reliability incident: ${incidentId}`)
    return incident
  }

  private update(
    incident: SpatialReliabilityIncident,
    state: SpatialReliabilityState,
    invariantResults?: Partial<Record<ReliabilityInvariant, ReliabilityInvariantResult>> | Record<string, ReliabilityInvariantResult>,
  ): SpatialReliabilityIncident {
    const parsed = parseSpatialReliabilityIncident({
      ...incident,
      state,
      invariant_results: { ...incident.invariant_results, ...invariantResults },
      updated_at: this.now(),
    })
    if (!parsed.ok) throw new Error(`invalid reliability update: ${parsed.diagnostic.path}`)
    this.incidents.set(parsed.data.incident_id, parsed.data)
    return parsed.data
  }
}
