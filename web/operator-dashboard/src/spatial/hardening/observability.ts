import {
  parseSpatialObservabilityMetric,
  SPATIAL_SCHEMA_VERSIONS,
  type SpatialObservabilityMetric,
} from '@/spatial/contracts'

export const SPATIAL_OBSERVABILITY_METRIC_NAMES = [
  'renderer_init',
  'renderer_fallback',
  'frame_fps_bucket',
  'frame_p95_bucket',
  'event_lag_bucket',
  'reconnect_count',
  'schema_rejection',
  'view_model_failure',
  'duplicate_entity',
  'planner_rejection',
  'attention_backlog_bucket',
  'workspace_conflict',
  'remote_quarantine',
  'component_error_boundary',
  'classic_fallback',
] as const

export type SpatialObservabilityMetricName = (typeof SPATIAL_OBSERVABILITY_METRIC_NAMES)[number]

export type SpatialTelemetryInput = {
  workspaceId: string
  nodeId: string
  name: SpatialObservabilityMetricName
  value: number
  unit: string
  bucket?: string
  correlationId?: string | null
  dimensions?: Readonly<Record<string, string>>
  observedAt?: string | Date
}

export class SpatialTelemetryViolation extends Error {
  public readonly code: 'SENSITIVE_CONTENT' | 'CARDINALITY_LIMIT' | 'INVALID_METRIC'

  public constructor(code: SpatialTelemetryViolation['code'], message: string) {
    super(message)
    this.name = 'SpatialTelemetryViolation'
    this.code = code
  }
}

const DEFAULT_ID = (prefix: string): string => `${prefix}:${Math.random().toString(36).slice(2, 12)}`
const SENSITIVE_PATTERN = /prompt|token|secret|password|credential|transcript|private|message|content|authorization/i

function isoNow(value?: string | Date): string {
  if (value instanceof Date) return value.toISOString()
  if (typeof value === 'string' && Number.isFinite(Date.parse(value))) return new Date(value).toISOString()
  return new Date().toISOString()
}

function bucket(value: number): string {
  if (!Number.isFinite(value)) return 'invalid'
  if (value < 1) return '0'
  if (value < 5) return '1-4'
  if (value < 10) return '5-9'
  if (value < 25) return '10-24'
  if (value < 50) return '25-49'
  if (value < 100) return '50-99'
  return '100+'
}

function assertSafeText(value: string, label: string): void {
  if (!value || value.length > 128 || SENSITIVE_PATTERN.test(value)) throw new SpatialTelemetryViolation('SENSITIVE_CONTENT', `${label} must be bounded and content-free`)
}

/** Bounded, content-free telemetry for one operator scenario. */
export class BoundedSpatialTelemetry {
  private readonly idFactory: (prefix: string) => string
  private readonly maxCardinality: number
  private readonly values = new Map<SpatialObservabilityMetricName, Set<string>>()
  private readonly records: SpatialObservabilityMetric[] = []

  public constructor(options: { idFactory?: (prefix: string) => string; maxCardinality?: number } = {}) {
    this.idFactory = options.idFactory ?? DEFAULT_ID
    this.maxCardinality = Math.max(1, options.maxCardinality ?? 100)
  }

  public record(input: SpatialTelemetryInput): SpatialObservabilityMetric {
    assertSafeText(input.workspaceId, 'workspace id')
    assertSafeText(input.nodeId, 'node id')
    assertSafeText(input.unit, 'unit')
    if (input.correlationId) assertSafeText(input.correlationId, 'correlation id')
    if (!SPATIAL_OBSERVABILITY_METRIC_NAMES.includes(input.name)) throw new SpatialTelemetryViolation('INVALID_METRIC', 'unknown metric name')
    const dimensions = input.dimensions ?? {}
    if (Object.keys(dimensions).length > 16) throw new SpatialTelemetryViolation('CARDINALITY_LIMIT', 'dimension count exceeds the bounded limit')
    for (const [key, value] of Object.entries(dimensions)) {
      assertSafeText(key, 'dimension key')
      assertSafeText(value, 'dimension value')
    }
    const dimensionKey = JSON.stringify(dimensions)
    const seen = this.values.get(input.name) ?? new Set<string>()
    if (!seen.has(dimensionKey) && seen.size >= this.maxCardinality) throw new SpatialTelemetryViolation('CARDINALITY_LIMIT', 'metric cardinality limit reached')
    seen.add(dimensionKey)
    this.values.set(input.name, seen)
    const parsed = parseSpatialObservabilityMetric({
      schema_version: SPATIAL_SCHEMA_VERSIONS.observabilityMetric,
      metric_id: this.idFactory('metric'),
      workspace_id: input.workspaceId,
      node_id: input.nodeId,
      name: input.name,
      value: input.value,
      unit: input.unit,
      bucket: input.bucket ?? bucket(input.value),
      correlation_id: input.correlationId ?? null,
      dimensions,
      content_free: true,
      observed_at: isoNow(input.observedAt),
    })
    if (!parsed.ok) throw new SpatialTelemetryViolation('INVALID_METRIC', parsed.diagnostic.path)
    this.records.push(parsed.data)
    return parsed.data
  }

  public flush(): SpatialObservabilityMetric[] {
    const output = [...this.records]
    this.records.length = 0
    return output
  }

  public size(): number { return this.records.length }
}

