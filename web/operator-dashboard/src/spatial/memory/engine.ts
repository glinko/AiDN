import {
  SPATIAL_MEMORY_CLUSTER_CRITERIA,
  SPATIAL_MEMORY_FOCUS_STATES,
  SPATIAL_MEMORY_LEVELS,
  SPATIAL_MEMORY_REGIONS,
  SPATIAL_SCHEMA_VERSIONS,
  spatialMemoryClusterSchema,
  spatialMemoryFocusSchema,
  spatialMemoryLayoutSchema,
  spatialMemoryProjectionSchema,
  spatialMemorySearchSchema,
  spatialMemoryVirtualizationSchema,
  type SpatialMemoryCluster as ContractMemoryCluster,
  type SpatialMemoryFocus as ContractMemoryFocus,
  type SpatialMemoryLayout as ContractMemoryLayout,
  type SpatialMemoryProjection as ContractMemoryProjection,
  type SpatialMemorySearch as ContractMemorySearch,
  type SpatialMemoryVirtualization as ContractMemoryVirtualization,
  type SpatialMemoryClusterCriterion,
  type SpatialMemoryFocusState,
  type SpatialMemoryLod,
  type SpatialMemoryLevel,
  type SpatialMemoryRegion,
} from '@/spatial/contracts'

export type MemoryPosition = { x: number; y: number; z: number }
export type MemoryViewport = { x: number; y: number; z?: number; radius: number; revision?: number }
export type MemoryCamera = { x: number; y: number; zoom: number; focusRef: string | null }
export type MemoryObjectType = 'agent' | 'endpoint' | 'service' | 'session' | 'artifact' | 'attention' | string

export type SpatialMemoryRecord = {
  semanticRef: string
  objectType: MemoryObjectType
  label: string
  summary?: string
  workspaceId?: string
  sessionRef?: string | null
  createdAt: string | Date
  lastActiveAt: string | Date
  lastReusedAt?: string | Date | null
  relevanceScore?: number
  pinWeight?: number
  pinned?: boolean
  unresolved?: boolean
  active?: boolean
  branchDescendantRefs?: readonly string[]
  structuralParentRef?: string | null
  metadata?: Readonly<Record<string, string | number | boolean | null | undefined>>
  worldPosition?: MemoryPosition
  sourceRevision?: number
  provenanceRef?: string
  authorized?: boolean
  available?: boolean
  stale?: boolean
  unavailableReason?: string | null
}

export type SpatialMemoryProjection = ContractMemoryProjection & {
  label: string
  summary: string
  objectType: MemoryObjectType
  stale: boolean
  metadata: Readonly<Record<string, string | number | boolean | null | undefined>>
}

export type SpatialMemoryCluster = ContractMemoryCluster & {
  title: string
  memberLabels: readonly string[]
  staleMemberRefs: readonly string[]
}

export type SpatialMemoryFocus = ContractMemoryFocus & {
  targetLabel: string
}

export type SpatialMemorySearchResult = ContractMemorySearch['results'][number] & {
  label: string
}

export type SpatialMemorySearch = Omit<ContractMemorySearch, 'results'> & { results: readonly SpatialMemorySearchResult[] }
export type SpatialMemoryVirtualization = ContractMemoryVirtualization

export type SpatialMemoryRelation = {
  id: string
  sourceRef: string
  targetRef: string
  type: string
  label?: string
  revision?: number
  state?: 'ACTIVE' | 'ARCHIVED' | 'STALE' | 'UNAVAILABLE'
}

export type SpatialMemoryRevealedRelation = SpatialMemoryRelation & {
  sourceLabel: string
  targetLabel: string
  directionLabel: string
  sourceOffscreen: boolean
  targetOffscreen: boolean
  accessibleText: string
}

export type SpatialMemoryLayout = ContractMemoryLayout & {
  anchorPositions: Readonly<Record<SpatialMemoryRegion, MemoryPosition>>
}

export type SpatialMemoryLayoutOptions = {
  workspaceId: string
  primaryAgentRef?: string | null
  policyRevision?: string
  seed?: string
  visibleRecentBudget?: number
  renderBudget?: number
  cullRadius?: number
  viewport?: { width?: number; height?: number; mobile?: boolean }
  now?: Date | (() => Date)
  manualGroups?: readonly SpatialMemoryManualGroup[]
}

export type SpatialMemoryManualGroup = {
  id: string
  title: string
  memberRefs: readonly string[]
  criterionRevision?: number
}

export type SpatialMemoryFocusOptions = {
  camera: MemoryCamera
  source?: 'POINTER' | 'KEYBOARD' | 'GESTURE' | 'RELATION' | 'SEARCH' | 'AGENT'
  reducedMotion?: boolean
  now?: Date
}

export type SpatialMemorySearchOptions = {
  limit?: number
  authorizedRefs?: ReadonlySet<string>
  includeUnavailable?: boolean
  now?: Date
}

export type SpatialMemoryTelemetry = {
  totalCount: number
  visibleCount: number
  materializedCount: number
  virtualizedCount: number
  lodCounts: { lod0: number; lod1: number; lod2: number; lod3: number }
  renderBudget: number
  materializationLatencyMs: number
  memoryReleased: boolean
}

export type SpatialMemorySnapshot = {
  layout: SpatialMemoryLayout
  projections: readonly SpatialMemoryProjection[]
  clusters: readonly SpatialMemoryCluster[]
  focus: SpatialMemoryFocus | null
  telemetry: SpatialMemoryTelemetry
}

const DAY_MS = 86_400_000
const DEFAULT_POLICY_REVISION = 'm8-policy-1'
const DEFAULT_VISIBLE_RECENT_BUDGET = 8
const DEFAULT_RENDER_BUDGET = 30
const DEFAULT_CULL_RADIUS = 12
const REGION_ORDER: readonly SpatialMemoryRegion[] = [...SPATIAL_MEMORY_REGIONS]
const LEVEL_ORDER: readonly SpatialMemoryLevel[] = [...SPATIAL_MEMORY_LEVELS]
const FOCUS_STATES: readonly SpatialMemoryFocusState[] = [...SPATIAL_MEMORY_FOCUS_STATES]
const CLUSTER_CRITERIA: readonly SpatialMemoryClusterCriterion[] = [...SPATIAL_MEMORY_CLUSTER_CRITERIA]

const REGION_ANCHORS: Readonly<Record<SpatialMemoryRegion, MemoryPosition>> = {
  ACTIVE_WORK: { x: 0, y: 0, z: 0 },
  AGENT_SPACE: { x: -4, y: 2.5, z: -1.5 },
  RECENT_MEMORY: { x: 0, y: -3, z: -1.2 },
  CLUSTER_MEMORY: { x: 3.8, y: 2.3, z: -2.4 },
  ENDPOINT_ARC: { x: 0, y: -5.2, z: -2.8 },
  DEEP_MEMORY: { x: 5.2, y: -3.6, z: -4.2 },
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value))
}

function asDate(value: string | Date | null | undefined, fallback: Date): Date {
  const parsed = value instanceof Date ? new Date(value.getTime()) : new Date(value ?? fallback)
  return Number.isFinite(parsed.getTime()) ? parsed : new Date(fallback.getTime())
}

function iso(value: string | Date | null | undefined, fallback: Date): string {
  return asDate(value, fallback).toISOString()
}

function stableHash(value: string): number {
  let hash = 2_166_136_261
  for (const character of value) hash = Math.imul(hash ^ character.charCodeAt(0), 16_777_619)
  return hash >>> 0
}

function unitHash(value: string): number {
  return stableHash(value) / 4_294_967_295
}

function copyPosition(position: MemoryPosition): MemoryPosition {
  return { x: position.x, y: position.y, z: position.z }
}

function distance(left: MemoryPosition, right: MemoryPosition): number {
  const dx = left.x - right.x
  const dy = left.y - right.y
  const dz = left.z - right.z
  return Math.sqrt(dx * dx + dy * dy + dz * dz)
}

function toLowerWords(value: string): string[] {
  return value.toLocaleLowerCase('en-US').split(/[^a-z0-9:_-]+/).filter(Boolean)
}

function positionForIndex(anchor: MemoryPosition, index: number, seed: string, scale: number): MemoryPosition {
  const angle = index * 2.399963229728653 + unitHash(`${seed}:angle`) * Math.PI * 2
  const radius = 0.72 + Math.sqrt(index) * 0.48
  const x = anchor.x + Math.cos(angle) * radius * scale
  const y = anchor.y + Math.sin(angle) * radius * 0.62 * scale
  const z = anchor.z - (index % 7) * 0.16
  return { x: Number(x.toFixed(4)), y: Number(y.toFixed(4)), z: Number(z.toFixed(4)) }
}

function projectionLevelRank(level: SpatialMemoryLevel): number {
  return LEVEL_ORDER.indexOf(level)
}

function normalizeMetadata(metadata: SpatialMemoryRecord['metadata']): Readonly<Record<string, string | number | boolean | null | undefined>> {
  return metadata ? { ...metadata } : {}
}

function contractProjection(projection: SpatialMemoryProjection): ContractMemoryProjection {
  return spatialMemoryProjectionSchema.parse({
    schema_version: SPATIAL_SCHEMA_VERSIONS.memoryProjection,
    projection_id: projection.projection_id,
    workspace_id: projection.workspace_id,
    semantic_ref: {
      canonical_ref: projection.semantic_ref.canonical_ref,
      object_type: projection.semantic_ref.object_type,
      revision: projection.semantic_ref.revision,
    },
    session_ref: projection.session_ref,
    zone: projection.zone,
    memory_level: projection.memory_level,
    age_class: projection.age_class,
    created_at: projection.created_at,
    last_active_at: projection.last_active_at,
    last_reused_at: projection.last_reused_at,
    relevance_score: projection.relevance_score,
    pin_weight: projection.pin_weight,
    cluster_ref: projection.cluster_ref,
    lod: projection.lod,
    render_state: projection.render_state,
    world_position: projection.world_position,
    manual_position_override: projection.manual_position_override,
    pinned: projection.pinned,
    unresolved: projection.unresolved,
    authorized: projection.authorized,
    unavailable_reason: projection.unavailable_reason,
    presentation_revision: projection.presentation_revision,
    provenance: projection.provenance,
  })
}

function contractCluster(cluster: SpatialMemoryCluster): ContractMemoryCluster {
  return spatialMemoryClusterSchema.parse({
    schema_version: SPATIAL_SCHEMA_VERSIONS.memoryCluster,
    cluster_id: cluster.cluster_id,
    workspace_id: cluster.workspace_id,
    title: cluster.title,
    criterion: cluster.criterion,
    criterion_revision: cluster.criterion_revision,
    evidence: cluster.evidence,
    member_refs: cluster.member_refs,
    stale_member_refs: cluster.stale_member_refs,
    summary_ref: cluster.summary_ref,
    collapsed: cluster.collapsed,
    pinned: cluster.pinned,
    presentation_revision: cluster.presentation_revision,
    provenance: cluster.provenance,
  })
}

export function createSpatialMemoryRecord(input: SpatialMemoryRecord): SpatialMemoryRecord {
  if (!input.semanticRef.trim()) throw new Error('semanticRef is required')
  if (!input.label.trim()) throw new Error('label is required')
  return {
    ...input,
    semanticRef: input.semanticRef.trim(),
    label: input.label.trim(),
    summary: input.summary?.trim() || input.label.trim(),
    relevanceScore: clamp(input.relevanceScore ?? 0.5, 0, 1),
    pinWeight: clamp(input.pinWeight ?? (input.pinned ? 1 : 0), 0, 1),
    pinned: input.pinned ?? false,
    unresolved: input.unresolved ?? false,
    active: input.active ?? false,
    authorized: input.authorized ?? true,
    available: input.available ?? true,
    stale: input.stale ?? false,
    branchDescendantRefs: [...(input.branchDescendantRefs ?? [])],
    metadata: normalizeMetadata(input.metadata),
  }
}

export class SpatialMemoryEngine {
  private readonly options: Required<Pick<SpatialMemoryLayoutOptions, 'workspaceId' | 'policyRevision' | 'seed' | 'visibleRecentBudget' | 'renderBudget' | 'cullRadius'>> & { primaryAgentRef: string | null; now: () => Date; viewport: SpatialMemoryLayoutOptions['viewport'] }
  private readonly records = new Map<string, SpatialMemoryRecord>()
  private readonly manualPositions = new Map<string, MemoryPosition>()
  private readonly manualGroups = new Map<string, SpatialMemoryManualGroup>()
  private readonly clusterExclusions = new Map<string, Set<string>>()
  private projectionsByRef = new Map<string, SpatialMemoryProjection>()
  private clustersById = new Map<string, SpatialMemoryCluster>()
  private layoutRevision = 0
  private focusState: SpatialMemoryFocus | null = null
  private telemetry: SpatialMemoryTelemetry = {
    totalCount: 0,
    visibleCount: 0,
    materializedCount: 0,
    virtualizedCount: 0,
    lodCounts: { lod0: 0, lod1: 0, lod2: 0, lod3: 0 },
    renderBudget: DEFAULT_RENDER_BUDGET,
    materializationLatencyMs: 0,
    memoryReleased: false,
  }

  constructor(options: SpatialMemoryLayoutOptions, records: readonly SpatialMemoryRecord[] = []) {
    const nowOption = options.now ?? new Date()
    const now = typeof nowOption === 'function' ? nowOption : () => new Date(nowOption.getTime())
    this.options = {
      workspaceId: options.workspaceId,
      primaryAgentRef: options.primaryAgentRef ?? null,
      policyRevision: options.policyRevision ?? DEFAULT_POLICY_REVISION,
      seed: options.seed ?? options.workspaceId,
      visibleRecentBudget: Math.max(1, Math.floor(options.visibleRecentBudget ?? DEFAULT_VISIBLE_RECENT_BUDGET)),
      renderBudget: Math.max(1, Math.floor(options.renderBudget ?? DEFAULT_RENDER_BUDGET)),
      cullRadius: Math.max(1, options.cullRadius ?? DEFAULT_CULL_RADIUS),
      now,
      viewport: options.viewport,
    }
    for (const group of options.manualGroups ?? []) this.manualGroups.set(group.id, { ...group, memberRefs: [...group.memberRefs] })
    for (const record of records) this.records.set(record.semanticRef, createSpatialMemoryRecord(record))
    this.rebuild()
  }

  get policyRevision(): string {
    return this.options.policyRevision
  }

  get recordCount(): number {
    return this.records.size
  }

  upsert(recordInput: SpatialMemoryRecord): SpatialMemoryProjection {
    const record = createSpatialMemoryRecord(recordInput)
    if (record.workspaceId && record.workspaceId !== this.options.workspaceId) throw new Error('record belongs to a different workspace')
    this.records.set(record.semanticRef, record)
    this.rebuild()
    return this.projection(record.semanticRef)!
  }

  upsertMany(records: readonly SpatialMemoryRecord[]): void {
    for (const record of records) this.records.set(record.semanticRef, createSpatialMemoryRecord(record))
    this.rebuild()
  }

  record(semanticRef: string): SpatialMemoryRecord | undefined {
    const record = this.records.get(semanticRef)
    return record ? createSpatialMemoryRecord(record) : undefined
  }

  projections(): readonly SpatialMemoryProjection[] {
    return [...this.projectionsByRef.values()].sort((left, right) => left.semantic_ref.canonical_ref.localeCompare(right.semantic_ref.canonical_ref))
  }

  projection(semanticRef: string | null | undefined): SpatialMemoryProjection | undefined {
    const projection = semanticRef ? this.projectionsByRef.get(semanticRef) : undefined
    return projection ? { ...projection, world_position: copyPosition(projection.world_position), metadata: { ...projection.metadata } } : undefined
  }

  clusters(): readonly SpatialMemoryCluster[] {
    return [...this.clustersById.values()].sort((left, right) => left.cluster_id.localeCompare(right.cluster_id))
  }

  layout(): SpatialMemoryLayout {
    const anchors = REGION_ORDER.map((region) => ({
      anchor_ref: `region:${region.toLocaleLowerCase('en-US')}`,
      region,
      position: this.regionAnchor(region),
      pinned: region === 'ACTIVE_WORK',
    }))
    const parsed = spatialMemoryLayoutSchema.parse({
      schema_version: SPATIAL_SCHEMA_VERSIONS.memoryLayout,
      workspace_id: this.options.workspaceId,
      policy_revision: this.options.policyRevision,
      seed: this.options.seed,
      primary_agent_ref: this.options.primaryAgentRef,
      anchors,
      presentation_revision: this.layoutRevision,
      updated_at: this.options.now().toISOString(),
    })
    return {
      ...parsed,
      anchorPositions: Object.fromEntries(anchors.map((anchor) => [anchor.region, copyPosition(anchor.position)])) as Record<SpatialMemoryRegion, MemoryPosition>,
    }
  }

  regionAnchor(region: SpatialMemoryRegion): MemoryPosition {
    const base = REGION_ANCHORS[region]
    const width = this.options.viewport?.width ?? 1024
    const height = this.options.viewport?.height ?? 720
    const scale = clamp(Math.min(width, height) / 720, 0.72, 1.35) * (this.options.viewport?.mobile ? 0.82 : 1)
    return { x: Number((base.x * scale).toFixed(4)), y: Number((base.y * scale).toFixed(4)), z: Number((base.z * scale).toFixed(4)) }
  }

  move(semanticRef: string, position: MemoryPosition): SpatialMemoryProjection {
    if (![position.x, position.y, position.z].every(Number.isFinite)) throw new Error('position must be finite')
    if (!this.records.has(semanticRef)) throw new Error(`unknown semantic ref: ${semanticRef}`)
    this.manualPositions.set(semanticRef, copyPosition(position))
    this.rebuild()
    return this.projection(semanticRef)!
  }

  setPinned(semanticRef: string, pinned = true): SpatialMemoryProjection {
    const current = this.records.get(semanticRef)
    if (!current) throw new Error(`unknown semantic ref: ${semanticRef}`)
    this.records.set(semanticRef, createSpatialMemoryRecord({ ...current, pinned, pinWeight: pinned ? 1 : current.pinWeight }))
    this.rebuild()
    return this.projection(semanticRef)!
  }

  resetLayout(): SpatialMemoryLayout {
    this.manualPositions.clear()
    for (const projection of this.projectionsByRef.values()) projection.manual_position_override = false
    this.rebuild()
    return this.layout()
  }

  reuse(semanticRef: string, at: Date = this.options.now()): SpatialMemoryProjection {
    const current = this.records.get(semanticRef)
    if (!current) throw new Error(`unknown semantic ref: ${semanticRef}`)
    this.records.set(semanticRef, createSpatialMemoryRecord({ ...current, lastReusedAt: at, lastActiveAt: at }))
    this.rebuild()
    return this.projection(semanticRef)!
  }

  visibleRecent(): readonly SpatialMemoryProjection[] {
    return this.projections()
      .filter((projection) => projection.zone === 'RECENT_MEMORY' && projection.authorized)
      .sort((left, right) => Date.parse(right.last_active_at) - Date.parse(left.last_active_at) || left.semantic_ref.canonical_ref.localeCompare(right.semantic_ref.canonical_ref))
      .filter((projection) => projection.pinned || projection.render_state !== 'VIRTUALIZED')
  }

  createManualCluster(input: SpatialMemoryManualGroup): SpatialMemoryCluster {
    if (!input.id.trim() || input.memberRefs.length === 0) throw new Error('manual cluster requires an id and members')
    this.manualGroups.set(input.id, { ...input, memberRefs: [...new Set(input.memberRefs)] })
    this.rebuild()
    const cluster = this.clustersById.get(input.id)
    if (!cluster) throw new Error('manual cluster has no resolvable members')
    return { ...cluster, member_refs: [...cluster.member_refs], stale_member_refs: [...cluster.stale_member_refs] }
  }

  removeClusterMember(clusterId: string, semanticRef: string): SpatialMemoryCluster | undefined {
    const exclusions = this.clusterExclusions.get(clusterId) ?? new Set<string>()
    exclusions.add(semanticRef)
    this.clusterExclusions.set(clusterId, exclusions)
    this.rebuild()
    const cluster = this.clustersById.get(clusterId)
    return cluster ? { ...cluster, member_refs: [...cluster.member_refs], stale_member_refs: [...cluster.stale_member_refs] } : undefined
  }

  setClusterCollapsed(clusterId: string, collapsed = true): SpatialMemoryCluster | undefined {
    const cluster = this.clustersById.get(clusterId)
    if (!cluster) return undefined
    cluster.collapsed = collapsed
    cluster.presentation_revision += 1
    return { ...cluster, member_refs: [...cluster.member_refs], stale_member_refs: [...cluster.stale_member_refs] }
  }

  revealRelations(focusRef: string, relations: readonly SpatialMemoryRelation[], max = 24): readonly SpatialMemoryRevealedRelation[] {
    const focusProjection = this.projection(focusRef)
    const cluster = this.clusters().find((candidate) => candidate.member_refs.some((member) => member.canonical_ref === focusRef))
    const focusRefs = new Set([focusRef, ...(cluster?.member_refs.map((member) => member.canonical_ref) ?? [])])
    return relations
      .filter((relation) => focusRefs.has(relation.sourceRef) || focusRefs.has(relation.targetRef))
      .sort((left, right) => left.id.localeCompare(right.id))
      .slice(0, Math.max(1, max))
      .map((relation) => {
        const source = this.projection(relation.sourceRef)
        const target = this.projection(relation.targetRef)
        const sourceLabel = source?.label ?? relation.sourceRef
        const targetLabel = target?.label ?? relation.targetRef
        const label = relation.label ?? relation.type.replaceAll('_', ' ').toLocaleLowerCase('en-US')
        return {
          ...relation,
          label,
          sourceLabel,
          targetLabel,
          directionLabel: `${sourceLabel} → ${targetLabel}`,
          sourceOffscreen: Boolean(source && focusProjection && distance(source.world_position, focusProjection.world_position) > 8),
          targetOffscreen: Boolean(target && focusProjection && distance(target.world_position, focusProjection.world_position) > 8),
          accessibleText: `${label}: ${sourceLabel} to ${targetLabel}`,
        }
      })
  }

  requestFocus(semanticRef: string, options: SpatialMemoryFocusOptions): SpatialMemoryFocus {
    const projection = this.projection(semanticRef)
    const record = this.records.get(semanticRef)
    const now = options.now ?? this.options.now()
    const targetRef = {
      canonical_ref: semanticRef,
      object_type: record?.objectType ?? 'unknown',
      revision: record?.sourceRevision ?? projection?.semantic_ref.revision ?? 0,
    }
    if (!projection || !record || record.authorized === false || record.available === false) {
      const unavailable = spatialMemoryFocusSchema.parse({
        schema_version: SPATIAL_SCHEMA_VERSIONS.memoryFocus,
        focus_id: `focus:${stableHash(`${this.options.workspaceId}:${semanticRef}:${now.toISOString()}`)}`,
        workspace_id: this.options.workspaceId,
        target_ref: targetRef,
        state: 'UNAVAILABLE',
        target_revision: targetRef.revision,
        world_position: projection?.world_position ?? { x: 0, y: 0, z: 0 },
        temporary_position: null,
        previous_camera: { x: options.camera.x, y: options.camera.y, zoom: options.camera.zoom, focus_ref: options.camera.focusRef },
        restore_camera: { x: options.camera.x, y: options.camera.y, zoom: options.camera.zoom, focus_ref: options.camera.focusRef },
        source: options.source ?? 'POINTER',
        reduced_motion: options.reducedMotion ?? false,
        unavailable_reason: record?.unavailableReason ?? 'Reference is unavailable or unauthorized.',
        created_at: now.toISOString(),
        updated_at: now.toISOString(),
      }) as SpatialMemoryFocus
      this.focusState = { ...unavailable, targetLabel: record?.label ?? semanticRef }
      return this.focusState
    }
    const requested = spatialMemoryFocusSchema.parse({
      schema_version: SPATIAL_SCHEMA_VERSIONS.memoryFocus,
      focus_id: `focus:${stableHash(`${this.options.workspaceId}:${semanticRef}:${now.toISOString()}`)}`,
      workspace_id: this.options.workspaceId,
      target_ref: targetRef,
      state: 'REQUESTED',
      target_revision: targetRef.revision,
      world_position: projection.world_position,
      temporary_position: null,
      previous_camera: { x: options.camera.x, y: options.camera.y, zoom: options.camera.zoom, focus_ref: options.camera.focusRef },
      restore_camera: { x: options.camera.x, y: options.camera.y, zoom: options.camera.zoom, focus_ref: options.camera.focusRef },
      source: options.source ?? 'POINTER',
      reduced_motion: options.reducedMotion ?? false,
      unavailable_reason: null,
      created_at: now.toISOString(),
      updated_at: now.toISOString(),
    }) as SpatialMemoryFocus
    this.focusState = { ...requested, targetLabel: projection.label }
    return this.focusState
  }

  materializeFocus(now: Date = this.options.now()): SpatialMemoryFocus | null {
    if (!this.focusState || this.focusState.state === 'UNAVAILABLE' || this.focusState.state === 'CANCELLED') return this.focusState
    const projection = this.projection(this.focusState.target_ref.canonical_ref)
    if (!projection) return this.focusState
    const temporaryPosition = { x: 0, y: 0, z: -1.6 }
    const next = spatialMemoryFocusSchema.parse({
      ...this.focusState,
      state: 'MATERIALIZING',
      temporary_position: temporaryPosition,
      updated_at: now.toISOString(),
    }) as SpatialMemoryFocus
    this.focusState = { ...next, targetLabel: this.focusState.targetLabel }
    projection.render_state = 'MATERIALIZED'
    projection.lod = 3
    projection.presentation_revision += 1
    return this.focusState
  }

  completeFocus(now: Date = this.options.now()): SpatialMemoryFocus | null {
    if (!this.focusState) return null
    if (this.focusState.state === 'REQUESTED') this.materializeFocus(now)
    if (this.focusState?.state === 'MATERIALIZING') {
      this.focusState = { ...this.focusState, state: 'FOCUSED', updated_at: now.toISOString() }
    }
    return this.focusState
  }

  pinFocus(now: Date = this.options.now()): SpatialMemoryFocus | null {
    if (!this.focusState || this.focusState.state === 'UNAVAILABLE') return this.focusState
    this.setPinned(this.focusState.target_ref.canonical_ref, true)
    this.focusState = { ...this.focusState, state: 'PINNED', updated_at: now.toISOString() }
    return this.focusState
  }

  returnFromFocus(now: Date = this.options.now()): SpatialMemoryFocus | null {
    if (!this.focusState) return null
    if (this.focusState.state === 'UNAVAILABLE') return this.focusState
    this.focusState = { ...this.focusState, state: 'RETURNING', updated_at: now.toISOString() }
    return this.focusState
  }

  cancelFocus(now: Date = this.options.now()): SpatialMemoryFocus | null {
    if (!this.focusState) return null
    this.focusState = { ...this.focusState, state: 'CANCELLED', updated_at: now.toISOString() }
    return this.focusState
  }

  focus(): SpatialMemoryFocus | null {
    return this.focusState ? { ...this.focusState, previous_camera: { ...this.focusState.previous_camera }, restore_camera: { ...this.focusState.restore_camera }, world_position: copyPosition(this.focusState.world_position), temporary_position: this.focusState.temporary_position ? copyPosition(this.focusState.temporary_position) : null } : null
  }

  search(query: string, options: SpatialMemorySearchOptions = {}): SpatialMemorySearch {
    const normalizedQuery = query.trim()
    const now = options.now ?? this.options.now()
    const tokens = toLowerWords(normalizedQuery)
    if (tokens.length === 0) throw new Error('search query is required')
    const authorizedRefs = options.authorizedRefs
    const results = [...this.records.values()]
      .filter((record) => record.authorized !== false && (!authorizedRefs || authorizedRefs.has(record.semanticRef)))
      .map((record) => {
        const metadataText = Object.entries(record.metadata ?? {}).map(([key, value]) => `${key} ${String(value ?? '')}`).join(' ')
        const fields: ReadonlyArray<[string, string]> = [
          ['label', record.label],
          ['summary', record.summary ?? ''],
          ['semantic reference', record.semanticRef],
          ['metadata', metadataText],
        ]
        const evidence = fields.filter(([, value]) => {
          const fieldTokens = new Set(toLowerWords(value))
          return tokens.some((token) => [...fieldTokens].some((fieldToken) => fieldToken.includes(token)))
        }).map(([field]) => `matched ${field}`)
        const exactLabel = record.label.toLocaleLowerCase('en-US').includes(normalizedQuery.toLocaleLowerCase('en-US'))
        const score = tokens.length === 0 ? 0 : clamp((evidence.length / fields.length) * 0.65 + (exactLabel ? 0.35 : 0) + record.relevanceScore! * 0.1, 0, 1)
        return { record, evidence, score }
      })
      .filter((candidate) => candidate.evidence.length > 0)
      .sort((left, right) => right.score - left.score || left.record.semanticRef.localeCompare(right.record.semanticRef))
      .slice(0, Math.max(1, options.limit ?? 50))
      .map(({ record, evidence, score }) => {
        const projection = this.projection(record.semanticRef)
        const unavailable = record.available === false || record.authorized === false
        const state = unavailable ? 'UNAVAILABLE' : record.stale || projection?.memory_level === 'VIRTUALIZED' ? 'STALE' : 'AVAILABLE'
        if (state === 'UNAVAILABLE' && options.includeUnavailable !== true) return null
        return {
          result_ref: {
            canonical_ref: record.semanticRef,
            object_type: record.objectType,
            revision: record.sourceRevision ?? projection?.semantic_ref.revision ?? 0,
          },
          relevance: Number(score.toFixed(4)),
          evidence,
          state,
          label: record.label,
        }
      })
      .filter((result): result is SpatialMemorySearchResult => Boolean(result))
    const result = spatialMemorySearchSchema.parse({
      schema_version: SPATIAL_SCHEMA_VERSIONS.memorySearch,
      search_id: `search:${stableHash(`${this.options.workspaceId}:${normalizedQuery}:${now.toISOString()}`)}`,
      workspace_id: this.options.workspaceId,
      query: normalizedQuery,
      policy_revision: this.options.policyRevision,
      results,
      performed_at: now.toISOString(),
    })
    return { ...result, results: result.results.map((item, index) => ({ ...item, label: results[index]?.label ?? item.result_ref.canonical_ref })) }
  }

  planVirtualization(viewport: MemoryViewport = { x: 0, y: 0, radius: this.options.cullRadius, revision: 0 }): SpatialMemoryVirtualization {
    const started = typeof performance !== 'undefined' && performance.now ? performance.now() : 0
    const projections = this.projections()
    const candidates = projections
      .map((projection) => ({ projection, distance: Math.sqrt((projection.world_position.x - viewport.x) ** 2 + (projection.world_position.y - viewport.y) ** 2 + (projection.world_position.z - (viewport.z ?? 0)) ** 2) }))
      .sort((left, right) => {
        const leftImportance = left.projection.relevance_score + left.projection.pin_weight + (left.projection.unresolved ? 0.4 : 0) + (left.projection.memory_level === 'ACTIVE' ? 0.3 : 0)
        const rightImportance = right.projection.relevance_score + right.projection.pin_weight + (right.projection.unresolved ? 0.4 : 0) + (right.projection.memory_level === 'ACTIVE' ? 0.3 : 0)
        return rightImportance - leftImportance || left.distance - right.distance || left.projection.semantic_ref.canonical_ref.localeCompare(right.projection.semantic_ref.canonical_ref)
      })
    const visible = candidates.filter(({ distance: candidateDistance }) => candidateDistance <= viewport.radius)
    const materializedRefs = new Set(visible.slice(0, this.options.renderBudget).map(({ projection }) => projection.semantic_ref.canonical_ref))
    const nextCounts = { lod0: 0, lod1: 0, lod2: 0, lod3: 0 }
    let materializedCount = 0
    let virtualizedCount = 0
    for (const candidate of candidates) {
      const projection = this.projectionsByRef.get(candidate.projection.semantic_ref.canonical_ref)
      if (!projection) continue
      const ref = projection.semantic_ref.canonical_ref
      if (projection.authorized === false || projection.render_state === 'UNAVAILABLE') {
        projection.render_state = 'UNAVAILABLE'
        projection.lod = 0
      } else if (candidate.distance > this.options.cullRadius) {
        projection.render_state = 'VIRTUALIZED'
        projection.lod = 0
        virtualizedCount += 1
      } else if (materializedRefs.has(ref)) {
        projection.render_state = 'MATERIALIZED'
        projection.lod = candidate.distance <= 2 ? 3 : candidate.distance <= 5 ? 2 : candidate.distance <= 9 ? 1 : 0
        materializedCount += 1
      } else {
        projection.render_state = 'SUMMARIZED'
        projection.lod = candidate.distance <= 9 ? 1 : 0
      }
      nextCounts[`lod${projection.lod}` as keyof typeof nextCounts] += 1
    }
    const ended = typeof performance !== 'undefined' && performance.now ? performance.now() : started
    this.telemetry = {
      totalCount: projections.length,
      visibleCount: visible.length,
      materializedCount,
      virtualizedCount,
      lodCounts: nextCounts,
      renderBudget: this.options.renderBudget,
      materializationLatencyMs: Number(Math.max(0, ended - started).toFixed(3)),
      memoryReleased: this.telemetry.memoryReleased,
    }
    return spatialMemoryVirtualizationSchema.parse({
      schema_version: SPATIAL_SCHEMA_VERSIONS.memoryVirtualization,
      workspace_id: this.options.workspaceId,
      viewport_revision: viewport.revision ?? 0,
      total_count: this.telemetry.totalCount,
      visible_count: this.telemetry.visibleCount,
      materialized_count: this.telemetry.materializedCount,
      virtualized_count: this.telemetry.virtualizedCount,
      lod_counts: this.telemetry.lodCounts,
      render_budget: this.telemetry.renderBudget,
      materialization_latency_ms: this.telemetry.materializationLatencyMs,
      memory_released: this.telemetry.memoryReleased,
      measured_at: this.options.now().toISOString(),
    }) as SpatialMemoryVirtualization
  }

  materialize(semanticRef: string, lod: SpatialMemoryLod = 3): SpatialMemoryProjection {
    const projection = this.projectionsByRef.get(semanticRef)
    if (!projection) throw new Error(`unknown semantic ref: ${semanticRef}`)
    projection.render_state = 'MATERIALIZED'
    projection.lod = clamp(lod, 0, 3) as SpatialMemoryLod
    projection.presentation_revision += 1
    this.telemetry.memoryReleased = false
    return this.projection(semanticRef)!
  }

  releaseMaterialization(semanticRef: string): SpatialMemoryProjection {
    const projection = this.projectionsByRef.get(semanticRef)
    if (!projection) throw new Error(`unknown semantic ref: ${semanticRef}`)
    projection.render_state = 'VIRTUALIZED'
    projection.lod = 0
    projection.presentation_revision += 1
    this.telemetry.memoryReleased = true
    return this.projection(semanticRef)!
  }

  telemetrySnapshot(): SpatialMemoryTelemetry {
    return { ...this.telemetry, lodCounts: { ...this.telemetry.lodCounts } }
  }

  contractSnapshot(): { layout: ContractMemoryLayout; projections: readonly ContractMemoryProjection[]; clusters: readonly ContractMemoryCluster[]; focus: ContractMemoryFocus | null; telemetry: ContractMemoryVirtualization } {
    const layout = spatialMemoryLayoutSchema.parse({ ...this.layout(), anchors: REGION_ORDER.map((region) => ({ anchor_ref: `region:${region.toLocaleLowerCase('en-US')}`, region, position: this.regionAnchor(region), pinned: region === 'ACTIVE_WORK' })) })
    const projections = this.projections().map(contractProjection)
    const clusters = this.clusters().map(contractCluster)
    const focus = this.focusState ? spatialMemoryFocusSchema.parse({ ...this.focusState, targetLabel: undefined }) : null
    const telemetry = spatialMemoryVirtualizationSchema.parse({
      schema_version: SPATIAL_SCHEMA_VERSIONS.memoryVirtualization,
      workspace_id: this.options.workspaceId,
      viewport_revision: this.telemetry.totalCount,
      total_count: this.telemetry.totalCount,
      visible_count: this.telemetry.visibleCount,
      materialized_count: this.telemetry.materializedCount,
      virtualized_count: this.telemetry.virtualizedCount,
      lod_counts: this.telemetry.lodCounts,
      render_budget: this.telemetry.renderBudget,
      materialization_latency_ms: this.telemetry.materializationLatencyMs,
      memory_released: this.telemetry.memoryReleased,
      measured_at: this.options.now().toISOString(),
    })
    return { layout, projections, clusters, focus, telemetry }
  }

  snapshot(): SpatialMemorySnapshot {
    return {
      layout: this.layout(),
      projections: this.projections(),
      clusters: this.clusters(),
      focus: this.focus(),
      telemetry: this.telemetrySnapshot(),
    }
  }

  private rebuild(): void {
    this.layoutRevision += 1
    this.clustersById = this.buildClusters()
    const clusterByMember = new Map<string, string>()
    for (const cluster of this.clustersById.values()) for (const member of cluster.member_refs) clusterByMember.set(member.canonical_ref, cluster.cluster_id)
    const next = new Map<string, SpatialMemoryProjection>()
    const sorted = [...this.records.values()].sort((left, right) => Date.parse(iso(right.lastActiveAt, this.options.now())) - Date.parse(iso(left.lastActiveAt, this.options.now())) || left.semanticRef.localeCompare(right.semanticRef))
    const occupied: MemoryPosition[] = []
    const regionIndexes = new Map<SpatialMemoryRegion, number>()
    for (const record of sorted) {
      const previous = this.projectionsByRef.get(record.semanticRef)
      const clusterRef = clusterByMember.get(record.semanticRef) ?? null
      const level = this.classify(record, previous?.memory_level, clusterRef)
      const zone = this.zoneFor(record, level, clusterRef)
      const manualPosition = this.manualPositions.get(record.semanticRef)
      const index = regionIndexes.get(zone) ?? 0
      regionIndexes.set(zone, index + 1)
      const generatedPosition = this.placeWithoutCollision(positionForIndex(this.regionAnchor(zone), index, `${this.options.seed}:${record.semanticRef}`, this.layoutScale()), occupied)
      const worldPosition = manualPosition ? copyPosition(manualPosition) : record.worldPosition ? copyPosition(record.worldPosition) : generatedPosition
      occupied.push(worldPosition)
      const unavailable = record.authorized === false || record.available === false
      const projection: SpatialMemoryProjection = {
        schema_version: SPATIAL_SCHEMA_VERSIONS.memoryProjection,
        projection_id: `memory:${stableHash(`${this.options.workspaceId}:${record.semanticRef}`)}`,
        workspace_id: this.options.workspaceId,
        semantic_ref: { canonical_ref: record.semanticRef, object_type: record.objectType, revision: record.sourceRevision ?? 0 },
        session_ref: record.sessionRef ?? null,
        zone,
        memory_level: level,
        age_class: level,
        created_at: iso(record.createdAt, this.options.now()),
        last_active_at: iso(record.lastActiveAt, this.options.now()),
        last_reused_at: record.lastReusedAt ? iso(record.lastReusedAt, this.options.now()) : null,
        relevance_score: record.relevanceScore ?? 0.5,
        pin_weight: record.pinWeight ?? 0,
        cluster_ref: clusterRef,
        lod: previous?.lod ?? 2,
        render_state: unavailable ? 'UNAVAILABLE' : previous?.render_state ?? 'MATERIALIZED',
        world_position: worldPosition,
        manual_position_override: Boolean(manualPosition || record.worldPosition),
        pinned: Boolean(record.pinned),
        unresolved: Boolean(record.unresolved),
        authorized: record.authorized !== false,
        unavailable_reason: unavailable ? (record.unavailableReason ?? 'Reference is unavailable.') : null,
        presentation_revision: (previous?.presentation_revision ?? 0) + 1,
        provenance: { canonical_ref: record.provenanceRef ?? record.semanticRef, revision: record.sourceRevision ?? 0, source: 'spatial.memory.engine' },
        label: record.label,
        summary: record.summary ?? record.label,
        objectType: record.objectType,
        stale: Boolean(record.stale),
        metadata: normalizeMetadata(record.metadata),
      }
      next.set(record.semanticRef, projection)
    }
    this.projectionsByRef = next
    this.applyRecentBudget()
  }

  private layoutScale(): number {
    const width = this.options.viewport?.width ?? 1024
    const height = this.options.viewport?.height ?? 720
    return clamp(Math.min(width, height) / 720, 0.72, 1.35) * (this.options.viewport?.mobile ? 0.82 : 1)
  }

  private placeWithoutCollision(candidate: MemoryPosition, occupied: readonly MemoryPosition[]): MemoryPosition {
    // Collision avoidance is local by design. A long-lived Workspace must not
    // turn placement into an O(n²) pass as history grows to 20k records.
    if (occupied.length > 512) return candidate
    const nearby = occupied.length > 128 ? occupied.slice(-128) : occupied
    if (nearby.every((position) => distance(candidate, position) >= 0.42)) return candidate
    for (let attempt = 1; attempt < 32; attempt += 1) {
      const offset = { x: (attempt % 5) * 0.36, y: Math.floor(attempt / 5) * 0.32, z: -(attempt % 3) * 0.12 }
      const moved = { x: candidate.x + offset.x, y: candidate.y + offset.y, z: candidate.z + offset.z }
      if (nearby.every((position) => distance(moved, position) >= 0.42)) return moved
    }
    return candidate
  }

  private classify(record: SpatialMemoryRecord, previous: SpatialMemoryLevel | undefined, clusterRef: string | null): SpatialMemoryLevel {
    if (record.active) return 'ACTIVE'
    if (clusterRef) return 'CLUSTERED'
    const nowMs = this.options.now().getTime()
    const lastActive = asDate(record.lastActiveAt, this.options.now()).getTime()
    const lastReuse = record.lastReusedAt ? asDate(record.lastReusedAt, this.options.now()).getTime() : 0
    const inactivityDays = Math.max(0, (nowMs - Math.max(lastActive, lastReuse)) / DAY_MS)
    const pinned = Boolean(record.pinned || (record.pinWeight ?? 0) >= 0.8 || record.unresolved)
    let candidate: SpatialMemoryLevel = inactivityDays < 1 ? 'RECENT' : inactivityDays < 7 ? 'OLDER' : inactivityDays < 30 ? 'PERIPHERAL' : 'VIRTUALIZED'
    if (pinned && projectionLevelRank(candidate) > projectionLevelRank('RECENT')) candidate = 'RECENT'
    if (previous === 'RECENT' && candidate === 'OLDER' && inactivityDays < 1.5) candidate = 'RECENT'
    if (previous === 'OLDER' && candidate === 'RECENT' && inactivityDays > 0.5) candidate = 'OLDER'
    if (previous === 'PERIPHERAL' && candidate === 'VIRTUALIZED' && inactivityDays < 35) candidate = 'PERIPHERAL'
    if (previous === 'VIRTUALIZED' && candidate === 'PERIPHERAL' && inactivityDays > 25) candidate = 'VIRTUALIZED'
    return candidate
  }

  private zoneFor(record: SpatialMemoryRecord, level: SpatialMemoryLevel, clusterRef: string | null): SpatialMemoryRegion {
    if (record.active || record.unresolved && record.objectType === 'attention') return 'ACTIVE_WORK'
    if (record.objectType === 'agent') return 'AGENT_SPACE'
    if (record.objectType === 'endpoint' || record.objectType === 'service') return 'ENDPOINT_ARC'
    if (clusterRef || level === 'CLUSTERED') return 'CLUSTER_MEMORY'
    if (level === 'PERIPHERAL' || level === 'VIRTUALIZED') return 'DEEP_MEMORY'
    return 'RECENT_MEMORY'
  }

  private applyRecentBudget(): void {
    const candidates = [...this.projectionsByRef.values()]
      .filter((projection) => projection.zone === 'RECENT_MEMORY')
      .sort((left, right) => Date.parse(right.last_active_at) - Date.parse(left.last_active_at) || left.semantic_ref.canonical_ref.localeCompare(right.semantic_ref.canonical_ref))
    const visibleRefs = new Set(candidates.filter((projection) => projection.pinned).map((projection) => projection.semantic_ref.canonical_ref))
    let nonPinnedVisible = 0
    for (const projection of candidates) {
      if (projection.pinned) continue
      if (nonPinnedVisible < this.options.visibleRecentBudget) {
        visibleRefs.add(projection.semantic_ref.canonical_ref)
        nonPinnedVisible += 1
      }
    }
    for (const projection of candidates) {
      if (!visibleRefs.has(projection.semantic_ref.canonical_ref) && !projection.pinned) {
        projection.render_state = 'VIRTUALIZED'
        projection.lod = 0
      }
    }
  }

  private buildClusters(): Map<string, SpatialMemoryCluster> {
    const groups = new Map<string, { criterion: SpatialMemoryClusterCriterion; key: string; members: SpatialMemoryRecord[]; title: string; evidence: string[]; manualId?: string }>()
    const addGroup = (criterion: SpatialMemoryClusterCriterion, key: string, record: SpatialMemoryRecord, title: string, evidence: string[], manualId?: string) => {
      if (!key) return
      const groupKey = manualId ?? `auto:${criterion}:${key}`
      const group = groups.get(groupKey) ?? { criterion, key, members: [], title, evidence, manualId }
      // The record store is keyed by semanticRef, so each automatic member is
      // already unique. Avoid a growing linear scan for 20k-item histories.
      group.members.push(record)
      groups.set(groupKey, group)
    }
    for (const manual of this.manualGroups.values()) {
      for (const ref of manual.memberRefs) {
        const record = this.records.get(ref)
        if (record && !this.clusterExclusions.get(manual.id)?.has(ref)) addGroup('MANUAL', manual.id, record, manual.title, [`manual group ${manual.id}`], manual.id)
      }
    }
    for (const record of this.records.values()) {
      const metadata = record.metadata ?? {}
      let criterion: SpatialMemoryClusterCriterion | undefined
      let key: string | undefined
      let title = ''
      let evidence = ''
      if (record.structuralParentRef) {
        criterion = 'STRUCTURAL_PARENT'
        key = record.structuralParentRef
        title = 'Context branch'
        evidence = 'shared structural parent'
      } else if (typeof metadata.project === 'string' && metadata.project) {
        criterion = 'PROJECT'
        key = metadata.project
        title = 'Project memory'
        evidence = 'shared project'
      } else if (typeof metadata.topic === 'string' && metadata.topic) {
        criterion = 'TOPIC'
        key = metadata.topic
        title = 'Topic memory'
        evidence = 'shared topic'
      } else if (typeof metadata.endpointRef === 'string' && metadata.endpointRef) {
        criterion = 'ENDPOINT'
        key = metadata.endpointRef
        title = 'Endpoint memory'
        evidence = 'shared Endpoint'
      } else if (typeof metadata.agentRef === 'string' && metadata.agentRef) {
        criterion = 'AGENT'
        key = metadata.agentRef
        title = 'Agent memory'
        evidence = 'shared Agent'
      } else if (typeof metadata.subsystem === 'string' && metadata.subsystem) {
        criterion = 'SUBSYSTEM'
        key = metadata.subsystem
        title = 'Subsystem memory'
        evidence = 'shared Node subsystem'
      } else if (typeof metadata.similarityKey === 'string' && metadata.similarityKey) {
        criterion = 'SIMILARITY'
        key = metadata.similarityKey
        title = 'Related memory'
        evidence = 'semantic similarity signal'
      }
      if (criterion && key) addGroup(criterion, key, record, title, [evidence])
    }
    const clusters = new Map<string, SpatialMemoryCluster>()
    for (const group of groups.values()) {
      if (group.members.length < 2 && group.criterion !== 'MANUAL') continue
      const clusterId = group.manualId ?? `cluster:${stableHash(`${this.options.workspaceId}:${group.criterion}:${group.key}`)}`
      const memberRefs = group.members.map((member) => ({ canonical_ref: member.semanticRef, object_type: member.objectType, revision: member.sourceRevision ?? 0 }))
      const staleMemberRefs = group.members.filter((member) => member.stale || member.available === false || member.authorized === false).map((member) => ({ canonical_ref: member.semanticRef, object_type: member.objectType, revision: member.sourceRevision ?? 0 }))
      const cluster: SpatialMemoryCluster = {
        schema_version: SPATIAL_SCHEMA_VERSIONS.memoryCluster,
        cluster_id: clusterId,
        workspace_id: this.options.workspaceId,
        title: group.title,
        criterion: group.criterion,
        criterion_revision: Math.max(...group.members.map((member) => member.sourceRevision ?? 0), group.members.length),
        evidence: [...new Set(group.evidence)],
        member_refs: memberRefs,
        stale_member_refs: staleMemberRefs,
        summary_ref: `${clusterId}:summary`,
        collapsed: false,
        pinned: false,
        presentation_revision: this.layoutRevision,
        provenance: { canonical_ref: group.manualId ?? clusterId, revision: Math.max(...group.members.map((member) => member.sourceRevision ?? 0)), source: 'spatial.memory.engine' },
        memberLabels: group.members.map((member) => member.label),
        staleMemberRefs: staleMemberRefs.map((member) => member.canonical_ref),
      }
      clusters.set(clusterId, cluster)
    }
    return clusters
  }
}

export function spatialMemoryContractSnapshot(engine: SpatialMemoryEngine): { layout: ContractMemoryLayout; projections: readonly ContractMemoryProjection[]; clusters: readonly ContractMemoryCluster[]; focus: ContractMemoryFocus | null; telemetry: ContractMemoryVirtualization } {
  return engine.contractSnapshot()
}

export const spatialMemoryRegionAnchors = REGION_ANCHORS
export const spatialMemoryRegionOrder = REGION_ORDER
export const spatialMemoryLevelOrder = LEVEL_ORDER
export const spatialMemoryFocusStates = FOCUS_STATES
export const spatialMemoryClusterCriteria = CLUSTER_CRITERIA
