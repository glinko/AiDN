import {
  parseSpatialAttentionFocus,
  parseSpatialAttentionItem,
  parseSpatialAttentionMarker,
  SPATIAL_SCHEMA_VERSIONS,
  type SpatialAttentionAction,
  type SpatialAttentionFocus,
  type SpatialAttentionItem,
  type SpatialAttentionMarker,
  type SpatialAttentionSeverity,
  type SpatialAttentionState,
} from '@/spatial/contracts'

export type AttentionQueueOptions = {
  workspaceId: string
  nodeId: string
  targetAgentRef: string
  now?: () => Date
  maxItems?: number
}

export type RaiseAttentionInput = {
  sourceEventRef: string
  subjectRef: string
  severity: SpatialAttentionSeverity
  attentionType?: SpatialAttentionItem['attention_type']
  summary: string
  groupingKey: string
  redactionProfileRef?: string | null
  sessionRef?: string | null
  requiredAction?: string | null
  provenanceRef?: string | null
}

export type AttentionQueueErrorCode = 'INVALID_ITEM' | 'UNKNOWN_ITEM' | 'INVALID_TRANSITION' | 'SCOPE_MISMATCH'

export class AttentionQueueError extends Error {
  readonly code: AttentionQueueErrorCode

  constructor(code: AttentionQueueErrorCode, message: string) {
    super(message)
    this.name = 'AttentionQueueError'
    this.code = code
  }
}

const severityRank: Record<SpatialAttentionSeverity, number> = {
  INFORMATION: 1,
  COMPLETED: 2,
  ATTENTION: 3,
  ACTION_REQUIRED: 4,
  CRITICAL: 5,
}

function redactSummary(summary: string): string {
  return summary
    .replace(/<[^>]+>/g, '')
    .replace(/(?:token|secret|password|api[_ -]?key)\s*[:=]\s*\S+/gi, '$1: [redacted]')
    .trim()
    .slice(0, 240)
}

/** Durable-in-memory projection; a Node Event Store adapter can replay it. */
export class AttentionQueueService {
  private readonly items = new Map<string, SpatialAttentionItem>()
  private readonly sourceIndex = new Map<string, string>()
  private readonly options: Required<Pick<AttentionQueueOptions, 'workspaceId' | 'nodeId' | 'targetAgentRef'>> & Pick<AttentionQueueOptions, 'now'>
  private readonly maxItems: number
  private connected = true

  constructor(options: AttentionQueueOptions) {
    this.options = { workspaceId: options.workspaceId, nodeId: options.nodeId, targetAgentRef: options.targetAgentRef, now: options.now }
    this.maxItems = Math.max(1, Math.min(100_000, options.maxItems ?? 10_000))
  }

  raise(input: RaiseAttentionInput): { item: SpatialAttentionItem; duplicate: boolean } {
    const existingId = this.sourceIndex.get(input.sourceEventRef)
    if (existingId) return { item: this.get(existingId), duplicate: true }
    if (!input.sourceEventRef.trim() || !input.subjectRef.trim() || !input.summary.trim()) throw new AttentionQueueError('INVALID_ITEM', 'source, subject and summary are required')
    const now = (this.options.now ?? (() => new Date()))().toISOString()
    const item: SpatialAttentionItem = {
      schema_version: SPATIAL_SCHEMA_VERSIONS.attentionItem,
      attention_id: `attention:${input.sourceEventRef}`,
      source_event_ref: input.sourceEventRef,
      subject_ref: input.subjectRef,
      node_id: this.options.nodeId,
      workspace_id: this.options.workspaceId,
      target_agent_ref: this.options.targetAgentRef,
      attention_type: input.attentionType ?? 'AUTONOMOUS_EVENT',
      severity: input.severity,
      state: 'UNREAD',
      summary: redactSummary(input.summary),
      created_at: now,
      acknowledged_at: null,
      redaction_profile_ref: input.redactionProfileRef ?? null,
      grouping_key: input.groupingKey,
      session_ref: input.sessionRef ?? null,
      required_action: input.requiredAction ?? null,
      provenance_ref: input.provenanceRef ?? null,
    }
    const parsed = parseSpatialAttentionItem(item)
    if (!parsed.ok) throw new AttentionQueueError('INVALID_ITEM', `attention item invalid at ${parsed.diagnostic.path}`)
    this.items.set(parsed.data.attention_id, parsed.data)
    this.sourceIndex.set(parsed.data.source_event_ref, parsed.data.attention_id)
    this.trim()
    return { item: this.clone(parsed.data), duplicate: false }
  }

  get(attentionId: string): SpatialAttentionItem {
    const item = this.items.get(attentionId)
    if (!item) throw new AttentionQueueError('UNKNOWN_ITEM', `unknown attention item: ${attentionId}`)
    return this.clone(item)
  }

  list(options: { includeResolved?: boolean } = {}): SpatialAttentionItem[] {
    return [...this.items.values()]
      .filter((item) => options.includeResolved || !['RESOLVED', 'ARCHIVED', 'DISMISSED'].includes(item.state))
      .sort((left, right) => severityRank[right.severity] - severityRank[left.severity] || right.created_at.localeCompare(left.created_at))
      .map((item) => this.clone(item))
  }

  transition(attentionId: string, state: SpatialAttentionState): SpatialAttentionItem {
    const current = this.items.get(attentionId)
    if (!current) throw new AttentionQueueError('UNKNOWN_ITEM', `unknown attention item: ${attentionId}`)
    const allowed: Record<SpatialAttentionState, readonly SpatialAttentionState[]> = {
      UNREAD: ['SEEN', 'DISMISSED', 'AGGREGATED', 'ARCHIVED'],
      SEEN: ['ACKNOWLEDGED', 'DISMISSED', 'AGGREGATED', 'ARCHIVED'],
      ACKNOWLEDGED: ['RESOLVED', 'DISMISSED', 'ARCHIVED'],
      AGGREGATED: ['SEEN', 'ACKNOWLEDGED', 'DISMISSED', 'ARCHIVED'],
      RESOLVED: ['ARCHIVED'],
      DISMISSED: ['ARCHIVED'],
      ARCHIVED: [],
    }
    if (current.state !== state && !allowed[current.state].includes(state)) throw new AttentionQueueError('INVALID_TRANSITION', `${current.state} cannot transition to ${state}`)
    const next: SpatialAttentionItem = {
      ...current,
      state,
      acknowledged_at: state === 'ACKNOWLEDGED' && current.acknowledged_at === null ? (this.options.now ?? (() => new Date()))().toISOString() : current.acknowledged_at,
    }
    this.items.set(attentionId, next)
    return this.clone(next)
  }

  markSeen(attentionId: string): SpatialAttentionItem { return this.transition(attentionId, 'SEEN') }
  acknowledge(attentionId: string): SpatialAttentionItem { return this.transition(attentionId, 'ACKNOWLEDGED') }
  resolve(attentionId: string): SpatialAttentionItem { return this.transition(attentionId, 'RESOLVED') }
  dismiss(attentionId: string): SpatialAttentionItem { return this.transition(attentionId, 'DISMISSED') }
  archive(attentionId: string): SpatialAttentionItem { return this.transition(attentionId, 'ARCHIVED') }

  setConnected(connected: boolean): void { this.connected = connected }
  isConnected(): boolean { return this.connected }
  reconnect(): SpatialAttentionItem[] { this.connected = true; return this.list() }

  snapshot(): { items: SpatialAttentionItem[]; connected: boolean } {
    return { items: [...this.items.values()].map((item) => this.clone(item)), connected: this.connected }
  }

  restore(snapshot: { items: readonly SpatialAttentionItem[]; connected?: boolean }): void {
    this.items.clear()
    this.sourceIndex.clear()
    for (const item of snapshot.items) {
      const parsed = parseSpatialAttentionItem(item)
      if (!parsed.ok) throw new AttentionQueueError('INVALID_ITEM', `attention item invalid at ${parsed.diagnostic.path}`)
      if (parsed.data.workspace_id !== this.options.workspaceId || parsed.data.node_id !== this.options.nodeId || parsed.data.target_agent_ref !== this.options.targetAgentRef) throw new AttentionQueueError('SCOPE_MISMATCH', 'attention snapshot belongs to another scope')
      this.items.set(parsed.data.attention_id, parsed.data)
      this.sourceIndex.set(parsed.data.source_event_ref, parsed.data.attention_id)
    }
    this.connected = snapshot.connected ?? true
    this.trim()
  }

  markAggregated(attentionIds: readonly string[]): SpatialAttentionItem[] {
    return attentionIds.map((attentionId) => this.transition(attentionId, 'AGGREGATED'))
  }

  private trim(): void {
    if (this.items.size <= this.maxItems) return
    const removable = [...this.items.values()]
      .filter((item) => item.severity !== 'CRITICAL' && item.state !== 'UNREAD')
      .sort((left, right) => left.created_at.localeCompare(right.created_at))
    while (this.items.size > this.maxItems && removable.length > 0) {
      const item = removable.shift()
      if (!item) break
      this.items.delete(item.attention_id)
      this.sourceIndex.delete(item.source_event_ref)
    }
  }

  private clone(item: SpatialAttentionItem): SpatialAttentionItem { return { ...item } }
}

export type OrbitalMarkerOptions = {
  workspaceId: string
  nodeId: string
  now?: () => Date
  maxVisible?: number
  reducedMotion?: boolean
}

/** Stable, bounded presentation instances. Critical items never aggregate. */
export class OrbitalAttentionMarkerService {
  private readonly slots = new Map<string, { lane: SpatialAttentionMarker['orbit_lane']; phase: number }>()
  private readonly hidden = new Set<string>()
  private readonly options: OrbitalMarkerOptions

  constructor(options: OrbitalMarkerOptions) { this.options = options }

  project(items: readonly SpatialAttentionItem[]): SpatialAttentionMarker[] {
    const maxVisible = Math.max(1, Math.min(32, this.options.maxVisible ?? 8))
    const active = items.filter((item) => !['RESOLVED', 'ARCHIVED', 'DISMISSED'].includes(item.state) && !this.hidden.has(item.attention_id))
    const critical = active.filter((item) => item.severity === 'CRITICAL' || item.severity === 'ACTION_REQUIRED')
    const regular = active.filter((item) => item.severity !== 'CRITICAL' && item.severity !== 'ACTION_REQUIRED')
    const groups = new Map<string, SpatialAttentionItem[]>()
    for (const item of regular) {
      const key = `${item.grouping_key}:${item.severity}`
      const group = groups.get(key) ?? []
      group.push(item)
      groups.set(key, group)
    }
    const groupedEntries = [...groups.values()].map((group) => ({ item: group[0], count: group.length, grouped: group.length > 1 }))
      .sort((left, right) => severityRank[right.item.severity] - severityRank[left.item.severity] || right.item.created_at.localeCompare(left.item.created_at))
    const regularSlots = Math.max(0, maxVisible - critical.length)
    const entries = [...critical.map((item) => ({ item, count: 1, grouped: false })), ...groupedEntries.slice(0, regularSlots)]
    return entries.map((entry, index) => this.markerFor(entry.item, index, entry.count, entry.grouped))
  }

  hide(attentionId: string): void { this.hidden.add(attentionId) }
  show(attentionId: string): void { this.hidden.delete(attentionId) }
  isHidden(attentionId: string): boolean { return this.hidden.has(attentionId) }

  markerFor(item: SpatialAttentionItem, index = 0, aggregationCount = 1, grouped = false): SpatialAttentionMarker {
    const saved = this.slots.get(item.attention_id)
    const lane: SpatialAttentionMarker['orbit_lane'] = item.severity === 'CRITICAL' || item.severity === 'ACTION_REQUIRED' ? 'INNER' : item.severity === 'COMPLETED' ? 'MIDDLE' : 'OUTER'
    const phase = saved?.phase ?? Number(((index * 0.73) % (Math.PI * 2)).toFixed(4))
    this.slots.set(item.attention_id, { lane, phase })
    const reducedMotion = this.options.reducedMotion ?? false
    const marker: SpatialAttentionMarker = {
      schema_version: SPATIAL_SCHEMA_VERSIONS.attentionMarker,
      marker_id: `marker:${item.attention_id}`,
      attention_ref: item.attention_id,
      workspace_id: this.options.workspaceId,
      node_id: this.options.nodeId,
      orbit_lane: lane,
      radius: lane === 'INNER' ? 1.8 : lane === 'MIDDLE' ? 2.5 : 3.2,
      phase,
      angular_velocity: reducedMotion ? 0 : lane === 'INNER' ? 0.018 : lane === 'MIDDLE' ? 0.012 : 0.008,
      severity: item.severity,
      attention_type: item.attention_type,
      unread: item.state === 'UNREAD',
      presentation_state: grouped ? 'AGGREGATED' : item.state === 'UNREAD' ? 'ORBITING_UNREAD' : 'SELECTED',
      aggregation_count: aggregationCount,
      reduced_motion: reducedMotion,
      updated_at: (this.options.now ?? (() => new Date()))().toISOString(),
    }
    const parsed = parseSpatialAttentionMarker(marker)
    if (!parsed.ok) throw new AttentionQueueError('INVALID_ITEM', `attention marker invalid at ${parsed.diagnostic.path}`)
    return { ...parsed.data }
  }
}

export type AttentionFocusOptions = {
  workspaceId: string
  nodeId: string
  queue: AttentionQueueService
  now?: () => Date
  sourceAvailable?: (subjectRef: string) => boolean
  onProposeAction?: (item: SpatialAttentionItem) => { accepted: boolean; planRef?: string }
}

export type AttentionFocusErrorCode = 'UNKNOWN_ITEM' | 'SOURCE_UNAVAILABLE' | 'INVALID_ACTION'

export class AttentionFocusError extends Error {
  readonly code: AttentionFocusErrorCode

  constructor(code: AttentionFocusErrorCode, message: string) {
    super(message)
    this.name = 'AttentionFocusError'
    this.code = code
  }
}

/** Focus translation is viewport-only; canonical world coordinates remain untouched. */
export class AttentionFocusController {
  private readonly options: AttentionFocusOptions
  private current: SpatialAttentionFocus | null = null

  constructor(options: AttentionFocusOptions) { this.options = options }

  focus(attentionId: string, previousViewportRef: string | null = null): SpatialAttentionFocus {
    const item = this.options.queue.get(attentionId)
    const available = this.options.sourceAvailable?.(item.subject_ref) ?? true
    const now = (this.options.now ?? (() => new Date()))().toISOString()
    const focus: SpatialAttentionFocus = {
      schema_version: SPATIAL_SCHEMA_VERSIONS.attentionFocus,
      focus_id: `focus:${attentionId}`,
      attention_id: attentionId,
      workspace_id: this.options.workspaceId,
      node_id: this.options.nodeId,
      state: available ? 'FOCUSED' : 'SOURCE_UNAVAILABLE',
      previous_viewport_ref: previousViewportRef,
      source_available: available,
      world_position_preserved: true,
      created_at: now,
      updated_at: now,
    }
    const parsed = parseSpatialAttentionFocus(focus)
    if (!parsed.ok) throw new AttentionFocusError('INVALID_ACTION', `focus invalid at ${parsed.diagnostic.path}`)
    this.current = parsed.data
    if (item.state === 'UNREAD') this.options.queue.markSeen(attentionId)
    return { ...parsed.data }
  }

  inspect(attentionId: string): SpatialAttentionFocus {
    const current = this.current?.attention_id === attentionId ? this.current : this.focus(attentionId)
    return { ...current, state: current.state === 'SOURCE_UNAVAILABLE' ? current.state : 'INSPECTING' }
  }

  execute(action: SpatialAttentionAction, attentionId: string): { focus: SpatialAttentionFocus; planRef?: string; cameraChanged: boolean } {
    const focus = this.current?.attention_id === attentionId ? this.current : this.focus(attentionId)
    const item = this.options.queue.get(attentionId)
    switch (action) {
      case 'INSPECT': return { focus: { ...focus, state: focus.state === 'SOURCE_UNAVAILABLE' ? focus.state : 'INSPECTING' }, cameraChanged: false }
      case 'ACKNOWLEDGE': this.options.queue.acknowledge(attentionId); return { focus, cameraChanged: false }
      case 'DISMISS': this.options.queue.dismiss(attentionId); return { focus, cameraChanged: false }
      case 'ARCHIVE': this.options.queue.archive(attentionId); return { focus, cameraChanged: false }
      case 'OPEN_SOURCE':
        if (!focus.source_available) throw new AttentionFocusError('SOURCE_UNAVAILABLE', 'attention source is unavailable')
        return { focus, cameraChanged: false }
      case 'SHOW_IN_WORKSPACE': return { focus, cameraChanged: false }
      case 'PROPOSE_ACTION': {
        const proposed = this.options.onProposeAction?.(item)
        if (!proposed?.accepted) throw new AttentionFocusError('INVALID_ACTION', 'canonical action plan was not accepted')
        return { focus, planRef: proposed.planRef, cameraChanged: false }
      }
      case 'RETURN_VIEWPORT': return { focus: this.returnFromFocus(), cameraChanged: false }
    }
  }

  returnFromFocus(): SpatialAttentionFocus {
    if (!this.current) throw new AttentionFocusError('INVALID_ACTION', 'no attention focus is active')
    const now = (this.options.now ?? (() => new Date()))().toISOString()
    this.current = { ...this.current, state: 'RETURNED', updated_at: now }
    return { ...this.current }
  }

  getCurrent(): SpatialAttentionFocus | null { return this.current ? { ...this.current } : null }
}

export const AttentionService = AttentionQueueService
