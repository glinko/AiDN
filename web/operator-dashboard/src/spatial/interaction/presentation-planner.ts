import {
  parseSpatialPresentationIntent,
  parseSpatialPresentationResult,
  SPATIAL_SCHEMA_VERSIONS,
  type SpatialPresentationIntent,
  type SpatialPresentationResult,
} from '@/spatial/contracts'

import {
  ComponentRegistryError,
  SpatialComponentRegistry,
  type SpatialComponentId,
} from './component-registry'

export type PresentationPlannerErrorCode =
  | 'INVALID_INTENT'
  | 'UNKNOWN_COMPONENT'
  | 'VERSION_MISMATCH'
  | 'STALE_TARGET'
  | 'EXCESSIVE_COMPONENTS'
  | 'UNSAFE_PRESENTATION'
  | 'WRONG_SCOPE'

export class PresentationPlannerError extends Error {
  readonly code: PresentationPlannerErrorCode

  constructor(code: PresentationPlannerErrorCode, message: string) {
    super(message)
    this.name = 'PresentationPlannerError'
    this.code = code
  }
}

export type PresentationPlannerInput = {
  intent: SpatialPresentationIntent | unknown
  result?: unknown
  data?: unknown
  staleTargetRefs?: readonly string[]
}

export type PresentationPlan = {
  result: SpatialPresentationResult
  component_id: string
  component_version: string
  reuse: boolean
  update: boolean
  progressive_detail: 'summary' | 'detail'
  data: unknown
}

export type PresentationPlannerOptions = {
  registry?: SpatialComponentRegistry
  workspaceId: string
  nodeId: string
  now?: () => Date
  idFactory?: (prefix: string) => string
  maxComponents?: number
  maxDetailComponents?: number
}

function defaultId(prefix: string): string {
  const uuid = typeof globalThis.crypto?.randomUUID === 'function' ? globalThis.crypto.randomUUID() : `${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`
  return `${prefix}_${uuid}`
}

function unsafePresentationValue(value: unknown, path = ''): string | null {
  if (typeof value === 'function' || typeof value === 'symbol' || typeof value === 'bigint') return path || '<root>'
  if (typeof value === 'string' && (/<\/?(?:script|style|iframe|object|embed)\b/i.test(value) || /javascript\s*:/i.test(value) || /(?:shader|css|callback)\s*:/i.test(value))) return path || '<root>'
  if (Array.isArray(value)) {
    for (let index = 0; index < value.length; index += 1) {
      const found = unsafePresentationValue(value[index], `${path}[${index}]`)
      if (found) return found
    }
  } else if (value && typeof value === 'object') {
    for (const [key, child] of Object.entries(value)) {
      if (/^(?:html|script|shader|css|callback|on[a-z]+)$/i.test(key)) return path ? `${path}.${key}` : key
      const found = unsafePresentationValue(child, path ? `${path}.${key}` : key)
      if (found) return found
    }
  }
  return null
}

function chooseComponent(intent: SpatialPresentationIntent, result: unknown): SpatialComponentId | string {
  if (intent.requested_component_id) return intent.requested_component_id
  if (result && typeof result === 'object' && 'component_id' in result && typeof result.component_id === 'string') return result.component_id
  if (result && typeof result === 'object' && 'kind' in result && result.kind === 'status') return 'status-summary'
  if (result && typeof result === 'object' && 'kind' in result && result.kind === 'endpoint') return 'endpoint-summary'
  return 'text-response'
}

/** Turns model/result facts into a bounded registered presentation descriptor. */
export class SpatialPresentationPlanner {
  readonly registry: SpatialComponentRegistry
  private readonly workspaceId: string
  private readonly nodeId: string
  private readonly now: () => Date
  private readonly idFactory: (prefix: string) => string
  private readonly maxComponents: number
  private readonly maxDetailComponents: number
  private readonly activeByReuseKey = new Map<string, SpatialPresentationResult>()
  private componentCount = 0

  constructor(options: PresentationPlannerOptions) {
    this.registry = options.registry ?? new SpatialComponentRegistry()
    this.workspaceId = options.workspaceId
    this.nodeId = options.nodeId
    this.now = options.now ?? (() => new Date())
    this.idFactory = options.idFactory ?? defaultId
    this.maxComponents = Math.max(1, options.maxComponents ?? 32)
    this.maxDetailComponents = Math.max(1, options.maxDetailComponents ?? 8)
  }

  plan(input: PresentationPlannerInput): PresentationPlan {
    const parsedIntent = parseSpatialPresentationIntent(input.intent)
    if (!parsedIntent.ok) throw new PresentationPlannerError('INVALID_INTENT', 'presentation intent is malformed')
    const intent = parsedIntent.data
    if (intent.workspace_id !== this.workspaceId) throw new PresentationPlannerError('WRONG_SCOPE', 'presentation workspace is outside the active scope')
    if (intent.node_id !== this.nodeId) throw new PresentationPlannerError('WRONG_SCOPE', 'presentation Node is outside the active scope')
    const staleTargetRefs = new Set(input.staleTargetRefs ?? [])
    if (intent.target_refs.some((ref) => staleTargetRefs.has(ref))) throw new PresentationPlannerError('STALE_TARGET', 'presentation target is stale')
    const unsafe = unsafePresentationValue(intent.requested_presentation)
    if (unsafe) throw new PresentationPlannerError('UNSAFE_PRESENTATION', `presentation contains executable content at ${unsafe}`)

    const componentId = chooseComponent(intent, input.result)
    let component
    try {
      component = this.registry.resolve(componentId, intent.requested_component_version ?? undefined)
    } catch (error) {
      if (error instanceof ComponentRegistryError && error.code === 'VERSION_MISMATCH') throw new PresentationPlannerError('VERSION_MISMATCH', error.message)
      throw new PresentationPlannerError('UNKNOWN_COMPONENT', 'requested component is not registered')
    }
    const data = input.data ?? input.result ?? this.defaultData(component.component_id)
    const validatedData = this.registry.validateData(component.component_id, component.version, data)
    const focusKey = intent.focus_ref ?? (intent.target_refs.join(',') || 'none')
    const reuseKey = `${intent.session_id ?? 'workspace'}:${component.component_id}:${focusKey}`
    const existing = this.activeByReuseKey.get(reuseKey)
    if (!existing && this.componentCount >= this.maxComponents) throw new PresentationPlannerError('EXCESSIVE_COMPONENTS', 'presentation component bound exceeded')
    const mobile = intent.viewport.device === 'MOBILE'
    const requestedDensity = intent.viewport.density
    const density = mobile ? 'COMPACT' : requestedDensity
    const detailCount = [...this.activeByReuseKey.values()].filter((item) => item.density === 'IMMERSIVE').length
    const progressiveDetail: PresentationPlan['progressive_detail'] = detailCount >= this.maxDetailComponents || intent.importance < 0.6 ? 'summary' : 'detail'
    const resultCandidate: SpatialPresentationResult = {
      schema_version: SPATIAL_SCHEMA_VERSIONS.presentationResult,
      presentation_id: existing?.presentation_id ?? this.idFactory('presentation'),
      workspace_id: this.workspaceId,
      node_id: this.nodeId,
      revision: existing ? existing.revision + 1 : 0,
      status: 'ACCEPTED',
      component_id: component.component_id,
      component_version: component.version,
      semantic_anchor: intent.focus_ref ?? intent.target_refs[0] ?? `workspace:${this.workspaceId}`,
      lifetime: intent.session_id ? 'SESSION' : 'WORKSPACE',
      density,
      importance: intent.importance,
      entity_refs: [...intent.target_refs],
      allowed_actions: [...component.allowed_actions],
      reuse_key: reuseKey,
      reason: null,
      created_at: this.now().toISOString(),
    }
    const parsedResult = parseSpatialPresentationResult(resultCandidate)
    if (!parsedResult.ok) throw new PresentationPlannerError('INVALID_INTENT', 'planner output is malformed')
    this.activeByReuseKey.set(reuseKey, parsedResult.data)
    if (!existing) this.componentCount += 1
    return {
      result: parsedResult.data,
      component_id: component.component_id,
      component_version: component.version,
      reuse: Boolean(existing),
      update: Boolean(existing),
      progressive_detail: progressiveDetail,
      data: progressiveDetail === 'summary' && data && typeof data === 'object' ? this.summarize(data) : validatedData,
    }
  }

  close(reuseKey: string): void {
    if (this.activeByReuseKey.delete(reuseKey)) this.componentCount = Math.max(0, this.componentCount - 1)
  }

  listActive(): SpatialPresentationResult[] {
    return [...this.activeByReuseKey.values()]
  }

  private summarize(data: unknown): unknown {
    if (Array.isArray(data)) return data.slice(0, 8)
    if (!data || typeof data !== 'object') return data
    return Object.fromEntries(Object.entries(data).slice(0, 12))
  }

  private defaultData(componentId: string): unknown {
    switch (componentId) {
      case 'text-response': return { text: '', citations: [] }
      case 'conversation-surface': return { session_id: 'pending', turn_ids: [], streaming: false }
      case 'key-value-summary': return { entries: [] }
      case 'status-summary': return { state: 'UNKNOWN', label: 'No status reported' }
      case 'endpoint-summary': return { endpoint_ref: 'pending', endpoint_type: 'unknown', status: 'UNKNOWN', capabilities: [] }
      case 'operation-notice': return { severity: 'INFO', message: 'No operation notice' }
      default: return {}
    }
  }
}

export const PresentationPlanner = SpatialPresentationPlanner

export function createPresentationPlanner(options: PresentationPlannerOptions): SpatialPresentationPlanner {
  return new SpatialPresentationPlanner(options)
}
