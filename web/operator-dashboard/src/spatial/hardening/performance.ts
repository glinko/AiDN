import {
  parseSpatialPerformanceReport,
  SPATIAL_PERFORMANCE_PROFILES,
  SPATIAL_SCHEMA_VERSIONS,
  type SpatialPerformanceProfile,
  type SpatialPerformanceReport,
} from '@/spatial/contracts'

export type SpatialPerformanceBudget = {
  maxInitialJsKb: number
  maxInitialCssKb: number
  maxWebglChunkKb: number
  maxTimeToInteractiveMs: number
  maxFirstSpatialFrameMs: number
  minSteadyFps: number
  maxFrameP95Ms: number
  maxMemoryGrowthMb: number
  maxIdleCpuPercent: number
  maxIdleGpuPercent: number
  maxEventBurstPerSecond: number
  maxConversationDomNodes: number
  maxMountCycles: number
}

export const SPATIAL_PERFORMANCE_BUDGETS: Record<SpatialPerformanceProfile, SpatialPerformanceBudget> = {
  LOW: {
    maxInitialJsKb: 420, maxInitialCssKb: 100, maxWebglChunkKb: 300, maxTimeToInteractiveMs: 3500, maxFirstSpatialFrameMs: 3000,
    minSteadyFps: 30, maxFrameP95Ms: 33, maxMemoryGrowthMb: 160, maxIdleCpuPercent: 12, maxIdleGpuPercent: 18,
    maxEventBurstPerSecond: 20, maxConversationDomNodes: 1200, maxMountCycles: 20,
  },
  MOBILE: {
    maxInitialJsKb: 500, maxInitialCssKb: 120, maxWebglChunkKb: 320, maxTimeToInteractiveMs: 3000, maxFirstSpatialFrameMs: 2500,
    minSteadyFps: 40, maxFrameP95Ms: 25, maxMemoryGrowthMb: 128, maxIdleCpuPercent: 8, maxIdleGpuPercent: 14,
    maxEventBurstPerSecond: 24, maxConversationDomNodes: 1600, maxMountCycles: 30,
  },
  DESKTOP: {
    maxInitialJsKb: 650, maxInitialCssKb: 160, maxWebglChunkKb: 450, maxTimeToInteractiveMs: 2200, maxFirstSpatialFrameMs: 1800,
    minSteadyFps: 55, maxFrameP95Ms: 16.7, maxMemoryGrowthMb: 192, maxIdleCpuPercent: 6, maxIdleGpuPercent: 10,
    maxEventBurstPerSecond: 40, maxConversationDomNodes: 2500, maxMountCycles: 50,
  },
  HIGH: {
    maxInitialJsKb: 900, maxInitialCssKb: 220, maxWebglChunkKb: 600, maxTimeToInteractiveMs: 1800, maxFirstSpatialFrameMs: 1400,
    minSteadyFps: 60, maxFrameP95Ms: 16.7, maxMemoryGrowthMb: 256, maxIdleCpuPercent: 8, maxIdleGpuPercent: 14,
    maxEventBurstPerSecond: 80, maxConversationDomNodes: 4000, maxMountCycles: 80,
  },
}

export type SpatialPerformanceInput = Omit<SpatialPerformanceReport, 'schema_version' | 'report_id' | 'observed_at'> & {
  reportId?: string
  observedAt?: string | Date
}

export type SpatialPerformanceCheck = {
  metric: string
  pass: boolean
  observed: number
  budget: number
}

export type SpatialPerformanceEvaluation = {
  profile: SpatialPerformanceProfile
  status: 'PASS' | 'ATTENTION' | 'FAIL'
  checks: readonly SpatialPerformanceCheck[]
  fallback: 'SPATIAL' | 'CLASSIC'
}

const DEFAULT_ID = (prefix: string): string => `${prefix}:${Math.random().toString(36).slice(2, 12)}`

function isoNow(value: string | Date | undefined): string {
  if (value instanceof Date) return value.toISOString()
  if (typeof value === 'string' && Number.isFinite(Date.parse(value))) return new Date(value).toISOString()
  return new Date().toISOString()
}

export function createSpatialPerformanceReport(input: SpatialPerformanceInput, idFactory = DEFAULT_ID): SpatialPerformanceReport {
  const parsed = parseSpatialPerformanceReport({
    schema_version: SPATIAL_SCHEMA_VERSIONS.performanceReport,
    report_id: input.reportId ?? idFactory('perf'),
    workspace_id: input.workspace_id,
    node_id: input.node_id,
    profile: input.profile,
    initial_js_kb: input.initial_js_kb,
    initial_css_kb: input.initial_css_kb,
    webgl_chunk_kb: input.webgl_chunk_kb,
    time_to_interactive_ms: input.time_to_interactive_ms,
    first_spatial_frame_ms: input.first_spatial_frame_ms,
    steady_fps: input.steady_fps,
    frame_p95_ms: input.frame_p95_ms,
    memory_growth_mb: input.memory_growth_mb,
    idle_cpu_percent: input.idle_cpu_percent,
    idle_gpu_percent: input.idle_gpu_percent,
    event_burst_per_second: input.event_burst_per_second,
    semantic_object_count: input.semantic_object_count,
    conversation_dom_nodes: input.conversation_dom_nodes,
    mount_cycles: input.mount_cycles,
    state: input.state,
    budget_refs: input.budget_refs,
    observed_at: input.observedAt ?? isoNow(undefined),
  })
  if (!parsed.ok) throw new Error(`invalid performance report: ${parsed.diagnostic.path}`)
  return parsed.data
}

export function evaluateSpatialPerformanceReport(report: SpatialPerformanceReport): SpatialPerformanceEvaluation {
  const budget = SPATIAL_PERFORMANCE_BUDGETS[report.profile]
  const checks: SpatialPerformanceCheck[] = [
    { metric: 'initial_js_kb', pass: report.initial_js_kb <= budget.maxInitialJsKb, observed: report.initial_js_kb, budget: budget.maxInitialJsKb },
    { metric: 'initial_css_kb', pass: report.initial_css_kb <= budget.maxInitialCssKb, observed: report.initial_css_kb, budget: budget.maxInitialCssKb },
    { metric: 'webgl_chunk_kb', pass: report.webgl_chunk_kb <= budget.maxWebglChunkKb, observed: report.webgl_chunk_kb, budget: budget.maxWebglChunkKb },
    { metric: 'time_to_interactive_ms', pass: report.time_to_interactive_ms <= budget.maxTimeToInteractiveMs, observed: report.time_to_interactive_ms, budget: budget.maxTimeToInteractiveMs },
    { metric: 'first_spatial_frame_ms', pass: report.first_spatial_frame_ms <= budget.maxFirstSpatialFrameMs, observed: report.first_spatial_frame_ms, budget: budget.maxFirstSpatialFrameMs },
    { metric: 'steady_fps', pass: report.steady_fps >= budget.minSteadyFps, observed: report.steady_fps, budget: budget.minSteadyFps },
    { metric: 'frame_p95_ms', pass: report.frame_p95_ms <= budget.maxFrameP95Ms, observed: report.frame_p95_ms, budget: budget.maxFrameP95Ms },
    { metric: 'memory_growth_mb', pass: report.memory_growth_mb <= budget.maxMemoryGrowthMb, observed: report.memory_growth_mb, budget: budget.maxMemoryGrowthMb },
    { metric: 'idle_cpu_percent', pass: report.idle_cpu_percent <= budget.maxIdleCpuPercent, observed: report.idle_cpu_percent, budget: budget.maxIdleCpuPercent },
    { metric: 'idle_gpu_percent', pass: report.idle_gpu_percent <= budget.maxIdleGpuPercent, observed: report.idle_gpu_percent, budget: budget.maxIdleGpuPercent },
    { metric: 'event_burst_per_second', pass: report.event_burst_per_second <= budget.maxEventBurstPerSecond, observed: report.event_burst_per_second, budget: budget.maxEventBurstPerSecond },
    { metric: 'conversation_dom_nodes', pass: report.conversation_dom_nodes <= budget.maxConversationDomNodes, observed: report.conversation_dom_nodes, budget: budget.maxConversationDomNodes },
    { metric: 'mount_cycles', pass: report.mount_cycles <= budget.maxMountCycles, observed: report.mount_cycles, budget: budget.maxMountCycles },
  ]
  const failed = checks.filter((check) => !check.pass).length
  const status = failed === 0 && report.state === 'PASS' ? 'PASS' : failed <= 2 && report.state !== 'FAIL' ? 'ATTENTION' : 'FAIL'
  return { profile: report.profile, status, checks, fallback: status === 'FAIL' ? 'CLASSIC' : 'SPATIAL' }
}

export function resolveSpatialPerformanceFallback(profile: SpatialPerformanceProfile | string, report?: SpatialPerformanceReport): 'SPATIAL' | 'CLASSIC' {
  if (!SPATIAL_PERFORMANCE_PROFILES.includes(profile as SpatialPerformanceProfile)) return 'CLASSIC'
  if (report && evaluateSpatialPerformanceReport(report).fallback === 'CLASSIC') return 'CLASSIC'
  return 'SPATIAL'
}

export function supportsLargeSemanticDataset(objectCount: number): boolean {
  return Number.isInteger(objectCount) && objectCount >= 20_000
}
