import {
  parseSpatialDeviceViewport,
  parseSpatialShareView,
  parseSpatialWorkspaceMutation,
  parseSpatialWorkspaceMutationResult,
  parseSpatialWorkspaceWorld,
  type SpatialDeviceViewport,
  type SpatialDeviceProfile,
  type SpatialOfflineMutationEntry,
  type SpatialOfflineQueue,
  type SpatialPresentationGeometry,
  type SpatialShareView,
  type SpatialWorkspaceMutation,
  type SpatialWorkspaceMutationResult,
  type SpatialWorkspaceSnapshot,
  type SpatialWorkspaceWorld,
} from '@/spatial/contracts'

export type MultiDeviceServiceErrorCode = 'VALIDATION' | 'UNAUTHORIZED' | 'STALE_REVISION' | 'INVALID_TARGET' | 'VIEWPORT_NOT_SHARED' | 'EXPIRED_SHARE'

export class SpatialMultiDeviceServiceError extends Error {
  readonly code: MultiDeviceServiceErrorCode

  constructor(code: MultiDeviceServiceErrorCode, message: string) {
    super(message)
    this.name = 'SpatialMultiDeviceServiceError'
    this.code = code
  }
}

export type SpatialMultiDeviceServiceOptions = {
  now?: () => Date
  authorizeMutation?: (mutation: SpatialWorkspaceMutation) => boolean
}

export type CreateMutationInput = Omit<SpatialWorkspaceMutation, 'schema_version' | 'created_at'> & {
  created_at?: string
}

export type ViewportPatch = Partial<Pick<SpatialDeviceViewport, 'profile' | 'camera' | 'focus_region' | 'focus_anchor_ref' | 'selection_refs' | 'expanded_refs' | 'opened_frame_refs' | 'quality_profile' | 'gesture_state'>>

type MutationRecord = {
  operation_id: string
  base_revision: number
  target_refs: string[]
}

type ShareOptions = {
  audienceDeviceIds: readonly string[]
  targetRef?: string | null
  ttlMs?: number
  focusAuthorized?: boolean
}

const mutationOperationKinds = new Set(['MOVE_ANCHOR', 'PIN', 'UNPIN', 'CREATE_BRANCH', 'EDIT_CLUSTER', 'UPSERT_RELATION', 'REMOVE_ENTITY'])

function clone<T>(value: T): T {
  return structuredClone(value)
}

function nowIso(now: () => Date): string {
  const date = now()
  if (!Number.isFinite(date.getTime())) throw new SpatialMultiDeviceServiceError('VALIDATION', 'M9 timestamp source returned an invalid Date.')
  return date.toISOString()
}

function unique(values: readonly string[]): string[] {
  return [...new Set(values)]
}

function sameTargets(left: readonly string[], right: readonly string[]): boolean {
  const rightSet = new Set(right)
  return left.some((ref) => rightSet.has(ref))
}

function defaultViewport(workspace: SpatialWorkspaceWorld, deviceId: string, profile: SpatialDeviceProfile, now: string): SpatialDeviceViewport {
  const value: SpatialDeviceViewport = {
    schema_version: 'spatial.device-viewport.v1',
    workspace_id: workspace.workspace_id,
    node_id: workspace.node_id,
    device_id: deviceId,
    profile,
    camera: {
      x: 0,
      y: 0,
      zoom: 1,
      orientation: { x: 0, y: 0, z: 0 },
      focus_ref: null,
    },
    focus_region: 'HOME',
    focus_anchor_ref: workspace.primary_agent_ref,
    selection_refs: [],
    expanded_refs: [],
    opened_frame_refs: [],
    quality_profile: profile === 'MOBILE' ? 'MOBILE' : profile === 'TABLET' ? 'LOW' : 'DESKTOP',
    gesture_state: 'IDLE',
    local_layout_revision: 0,
    updated_at: now,
  }
  const parsed = parseSpatialDeviceViewport(value)
  if (!parsed.ok) throw new SpatialMultiDeviceServiceError('VALIDATION', 'Generated device viewport failed the M9 contract.')
  return parsed.data
}

export function createWorkspaceWorldFromSnapshot(snapshot: SpatialWorkspaceSnapshot, now: Date = new Date()): SpatialWorkspaceWorld {
  const timestamp = now.toISOString()
  const anchorByRef = new Map(snapshot.semantic_anchors.map((anchor) => [anchor.canonical_ref, anchor]))
  const semanticObjects = snapshot.entities.map((entity) => {
    const anchor = anchorByRef.get(entity.canonical_ref)
    return {
      canonical_ref: entity.canonical_ref,
      semantic_anchor: anchor?.position ?? { x: 0, y: 0, z: 0 },
      region: anchor?.region ?? entity.kind,
      manual_override: Boolean(anchor?.cluster_ref),
      pinned: false,
      revision: entity.revision,
      available: entity.availability !== 'UNAVAILABLE' && entity.state !== 'ARCHIVED',
    }
  })
  const relations = snapshot.relations.map((relation) => ({
    relation_ref: relation.relation_id,
    source_ref: relation.source_ref,
    target_ref: relation.target_ref,
    revision: relation.revision,
    active: relation.state === 'ACTIVE',
  }))
  const clusterRefs = new Map<string, string[]>()
  for (const [memberRef, clusterRef] of Object.entries(snapshot.cluster_membership)) {
    const members = clusterRefs.get(clusterRef) ?? []
    members.push(memberRef)
    clusterRefs.set(clusterRef, members)
  }
  const world: SpatialWorkspaceWorld = {
    schema_version: 'spatial.workspace-world.v1',
    workspace_id: snapshot.workspace_id,
    node_id: snapshot.node_id,
    workspace_revision: snapshot.semantic_revision,
    world_revision: snapshot.semantic_revision,
    primary_agent_ref: snapshot.primary_agent_ref ?? null,
    semantic_objects: semanticObjects,
    relations,
    clusters: [...clusterRefs.entries()].map(([cluster_ref, member_refs]) => ({ cluster_ref, member_refs, revision: snapshot.semantic_revision, collapsed: false })),
    session_refs: snapshot.entities.filter((entity) => entity.kind === 'session').map((entity) => entity.canonical_ref),
    pins: [],
    updated_at: timestamp,
  }
  const parsed = parseSpatialWorkspaceWorld(world)
  if (!parsed.ok) throw new SpatialMultiDeviceServiceError('VALIDATION', 'Workspace snapshot could not be projected into the M9 world contract.')
  return parsed.data
}

export function createPresentationGeometry(
  world: SpatialWorkspaceWorld,
  deviceId: string,
  semanticRef: string,
  profile: SpatialDeviceProfile,
  viewport: { width: number; height: number; density?: number; safeArea?: Partial<SpatialPresentationGeometry['safe_area_inset']>; keyboardInset?: number },
  revision = 0,
  now: Date = new Date(),
): SpatialPresentationGeometry {
  const arrangement = profile === 'MOBILE' ? 'BOTTOM_SHEET' : profile === 'TABLET' ? 'SIDE_PANEL' : 'FOCUS_FRAME'
  return {
    schema_version: 'spatial.presentation-geometry.v1',
    workspace_id: world.workspace_id,
    node_id: world.node_id,
    device_id: deviceId,
    semantic_ref: semanticRef,
    variant: profile,
    width: Math.max(0, viewport.width),
    height: Math.max(0, viewport.height),
    density: Math.max(0.5, viewport.density ?? 1),
    arrangement,
    safe_area_inset: {
      top: Math.max(0, viewport.safeArea?.top ?? 0),
      right: Math.max(0, viewport.safeArea?.right ?? 0),
      bottom: Math.max(0, viewport.safeArea?.bottom ?? 0),
      left: Math.max(0, viewport.safeArea?.left ?? 0),
    },
    keyboard_inset: Math.max(0, viewport.keyboardInset ?? 0),
    revision,
    updated_at: now.toISOString(),
  }
}

export class SpatialMultiDeviceWorkspaceService {
  private world: SpatialWorkspaceWorld
  private readonly viewports = new Map<string, SpatialDeviceViewport>()
  private readonly operations = new Map<string, SpatialWorkspaceMutationResult>()
  private readonly mutationHistory: MutationRecord[] = []
  private readonly queues = new Map<string, SpatialOfflineQueue>()
  private readonly shares = new Map<string, SpatialShareView>()
  private readonly now: () => Date
  private readonly authorizeMutation?: (mutation: SpatialWorkspaceMutation) => boolean

  constructor(worldInput: SpatialWorkspaceWorld, options: SpatialMultiDeviceServiceOptions = {}) {
    const parsed = parseSpatialWorkspaceWorld(worldInput)
    if (!parsed.ok) throw new SpatialMultiDeviceServiceError('VALIDATION', 'Initial M9 world failed its contract.')
    this.world = clone(parsed.data)
    this.now = options.now ?? (() => new Date())
    this.authorizeMutation = options.authorizeMutation
  }

  getWorld(): SpatialWorkspaceWorld {
    return clone(this.world)
  }

  registerDevice(deviceId: string, profile: SpatialDeviceProfile = 'DESKTOP'): SpatialDeviceViewport {
    if (!deviceId.trim()) throw new SpatialMultiDeviceServiceError('VALIDATION', 'Device IDs must be non-empty.')
    const existing = this.viewports.get(deviceId)
    if (existing) return clone(existing)
    const viewport = defaultViewport(this.world, deviceId, profile, nowIso(this.now))
    this.viewports.set(deviceId, viewport)
    return clone(viewport)
  }

  getViewport(deviceId: string): SpatialDeviceViewport {
    return clone(this.viewports.get(deviceId) ?? this.registerDevice(deviceId))
  }

  updateViewport(deviceId: string, patch: ViewportPatch): SpatialDeviceViewport {
    const current = this.viewports.get(deviceId) ?? this.registerDevice(deviceId)
    const next = {
      ...current,
      ...patch,
      camera: patch.camera ? { ...current.camera, ...patch.camera, orientation: { ...current.camera.orientation, ...patch.camera.orientation } } : current.camera,
      selection_refs: patch.selection_refs ? unique(patch.selection_refs) : current.selection_refs,
      expanded_refs: patch.expanded_refs ? unique(patch.expanded_refs) : current.expanded_refs,
      opened_frame_refs: patch.opened_frame_refs ? unique(patch.opened_frame_refs) : current.opened_frame_refs,
      local_layout_revision: current.local_layout_revision + 1,
      updated_at: nowIso(this.now),
    }
    const parsed = parseSpatialDeviceViewport(next)
    if (!parsed.ok) throw new SpatialMultiDeviceServiceError('VALIDATION', 'Viewport update failed the M9 device-local contract.')
    this.viewports.set(deviceId, parsed.data)
    return clone(parsed.data)
  }

  applyMutation(input: unknown): SpatialWorkspaceMutationResult {
    const parsed = parseSpatialWorkspaceMutation(input)
    if (!parsed.ok) throw new SpatialMultiDeviceServiceError('VALIDATION', 'Workspace mutation failed the M9 envelope contract.')
    const mutation = parsed.data
    if (mutation.workspace_id !== this.world.workspace_id || mutation.node_id !== this.world.node_id) {
      throw new SpatialMultiDeviceServiceError('INVALID_TARGET', 'Mutation targets a different Workspace or Node.')
    }
    if (!mutationOperationKinds.has(mutation.operation)) throw new SpatialMultiDeviceServiceError('VALIDATION', 'Operation is not allowed in the semantic mutation stream.')
    const prior = this.operations.get(mutation.idempotency_key)
    if (prior) {
      const idempotent = { ...prior, state: 'IDEMPOTENT' as const }
      const checked = parseSpatialWorkspaceMutationResult(idempotent)
      if (!checked.ok) throw new SpatialMultiDeviceServiceError('VALIDATION', 'Stored idempotent result failed the M9 result contract.')
      return clone(checked.data)
    }
    if (this.authorizeMutation && !this.authorizeMutation(mutation)) {
      return this.resultFor(mutation, 'REJECTED', 'AUTHORIZATION', 'Actor is not authorized; device identity does not grant authority.')
    }
    const targets = unique(mutation.target_refs)
    const related = this.mutationHistory.filter((record) => record.base_revision >= mutation.base_revision && sameTargets(record.target_refs, targets))
    if (mutation.base_revision > this.world.workspace_revision) {
      return this.resultFor(mutation, 'REJECTED', 'STALE_REVISION', 'Mutation base revision is ahead of the current Workspace revision.')
    }
    if (mutation.base_revision < this.world.workspace_revision && related.length > 0) {
      return this.resultFor(mutation, 'CONFLICT', 'TOPOLOGY_CONFLICT', 'A concurrent mutation touched the same semantic target.', related[related.length - 1]?.operation_id ?? null)
    }
    if (targets.length === 0 && mutation.operation !== 'CREATE_BRANCH') {
      return this.resultFor(mutation, 'REJECTED', 'INVALID_TARGET', 'Semantic mutations require at least one target reference.')
    }
    const next = clone(this.world)
    const changed = this.applyOperation(next, mutation)
    if (!changed) return this.resultFor(mutation, 'REJECTED', 'INVALID_TARGET', 'Mutation target is unavailable or malformed.')
    next.workspace_revision = this.world.workspace_revision + 1
    next.world_revision = next.workspace_revision
    next.updated_at = nowIso(this.now)
    const worldResult = parseSpatialWorkspaceWorld(next)
    if (!worldResult.ok) throw new SpatialMultiDeviceServiceError('VALIDATION', 'Applied Workspace world failed its contract.')
    this.world = worldResult.data
    const result = this.resultFor(mutation, 'APPLIED', 'NONE', null)
    this.operations.set(mutation.idempotency_key, result)
    this.mutationHistory.push({ operation_id: mutation.operation_id, base_revision: mutation.base_revision, target_refs: targets })
    return clone(result)
  }

  private applyOperation(world: SpatialWorkspaceWorld, mutation: SpatialWorkspaceMutation): boolean {
    const targets = unique(mutation.target_refs)
    if (mutation.operation === 'CREATE_BRANCH') {
      const ref = typeof mutation.payload.canonical_ref === 'string' ? mutation.payload.canonical_ref : targets[0]
      if (!ref || world.semantic_objects.some((object) => object.canonical_ref === ref)) return false
      const anchor = mutation.payload.semantic_anchor
      const semanticAnchor = anchor && typeof anchor === 'object' && !Array.isArray(anchor)
        ? { x: Number((anchor as Record<string, unknown>).x ?? 0), y: Number((anchor as Record<string, unknown>).y ?? 0), z: Number((anchor as Record<string, unknown>).z ?? 0) }
        : { x: 0, y: 0, z: 0 }
      world.semantic_objects.push({ canonical_ref: ref, semantic_anchor: semanticAnchor, region: 'BRANCH', manual_override: true, pinned: false, revision: world.workspace_revision + 1, available: true })
      return true
    }
    if (mutation.operation === 'MOVE_ANCHOR') {
      const target = world.semantic_objects.find((object) => object.canonical_ref === targets[0] && object.available)
      const anchor = mutation.payload.semantic_anchor
      if (!target || typeof anchor !== 'object' || anchor === null || Array.isArray(anchor)) return false
      const record = anchor as Record<string, unknown>
      if (![record.x, record.y, record.z].every((value) => typeof value === 'number' && Number.isFinite(value))) return false
      target.semantic_anchor = { x: record.x as number, y: record.y as number, z: record.z as number }
      target.manual_override = true
      target.revision += 1
      return true
    }
    if (mutation.operation === 'PIN' || mutation.operation === 'UNPIN') {
      const target = world.semantic_objects.find((object) => object.canonical_ref === targets[0] && object.available)
      if (!target) return false
      target.pinned = mutation.operation === 'PIN'
      world.pins = mutation.operation === 'PIN' ? unique([...world.pins, target.canonical_ref]) : world.pins.filter((ref) => ref !== target.canonical_ref)
      target.revision += 1
      return true
    }
    if (mutation.operation === 'EDIT_CLUSTER') {
      const cluster = world.clusters.find((candidate) => candidate.cluster_ref === targets[0])
      if (!cluster) return false
      if (Array.isArray(mutation.payload.member_refs)) cluster.member_refs = unique(mutation.payload.member_refs.filter((ref): ref is string => typeof ref === 'string'))
      if (typeof mutation.payload.collapsed === 'boolean') cluster.collapsed = mutation.payload.collapsed
      cluster.revision += 1
      return true
    }
    if (mutation.operation === 'UPSERT_RELATION') {
      const relation = mutation.payload.relation
      if (!relation || typeof relation !== 'object' || Array.isArray(relation)) return false
      const record = relation as Record<string, unknown>
      if (typeof record.relation_ref !== 'string' || typeof record.source_ref !== 'string' || typeof record.target_ref !== 'string') return false
      const existing = world.relations.find((candidate) => candidate.relation_ref === record.relation_ref)
      const nextRelation = { relation_ref: record.relation_ref, source_ref: record.source_ref, target_ref: record.target_ref, revision: world.workspace_revision + 1, active: record.active !== false }
      if (existing) Object.assign(existing, nextRelation)
      else world.relations.push(nextRelation)
      return true
    }
    if (mutation.operation === 'REMOVE_ENTITY') {
      const target = world.semantic_objects.find((object) => object.canonical_ref === targets[0])
      if (!target) return false
      target.available = false
      target.pinned = false
      world.pins = world.pins.filter((ref) => ref !== target.canonical_ref)
      target.revision += 1
      return true
    }
    return false
  }

  private resultFor(mutation: SpatialWorkspaceMutation, state: SpatialWorkspaceMutationResult['state'], conflictCategory: SpatialWorkspaceMutationResult['conflict_category'], reason: string | null, winningOperationId: string | null = null): SpatialWorkspaceMutationResult {
    const result: SpatialWorkspaceMutationResult = {
      schema_version: 'spatial.workspace-mutation-result.v1',
      event_id: mutation.event_id,
      operation_id: mutation.operation_id,
      workspace_id: this.world.workspace_id,
      node_id: this.world.node_id,
      state,
      conflict_category: conflictCategory,
      server_result_revision: this.world.workspace_revision,
      current_evidence: {
        workspace_revision: this.world.workspace_revision,
        target_refs: unique(mutation.target_refs),
        winning_operation_id: winningOperationId,
        reason,
      },
      world: clone(this.world),
      audit_ref: `audit:${mutation.operation_id}`,
      resolved_at: nowIso(this.now),
    }
    const parsed = parseSpatialWorkspaceMutationResult(result)
    if (!parsed.ok) throw new SpatialMultiDeviceServiceError('VALIDATION', 'Mutation result failed the M9 result contract.')
    return parsed.data
  }

  getOfflineQueue(deviceId: string): SpatialOfflineQueue {
    const existing = this.queues.get(deviceId)
    if (existing) return clone(existing)
    const queue: SpatialOfflineQueue = {
      schema_version: 'spatial.offline-queue.v1',
      workspace_id: this.world.workspace_id,
      node_id: this.world.node_id,
      device_id: deviceId,
      connectivity: 'ONLINE',
      last_consistent_revision: this.world.workspace_revision,
      pending: [],
      updated_at: nowIso(this.now),
    }
    this.queues.set(deviceId, queue)
    return clone(queue)
  }

  setConnectivity(deviceId: string, connectivity: SpatialOfflineQueue['connectivity']): SpatialOfflineQueue {
    const queue = this.getOfflineQueue(deviceId)
    queue.connectivity = connectivity
    queue.updated_at = nowIso(this.now)
    this.queues.set(deviceId, queue)
    return clone(queue)
  }

  queueOfflineMutation(input: unknown): SpatialOfflineQueue {
    const parsed = parseSpatialWorkspaceMutation(input)
    if (!parsed.ok) throw new SpatialMultiDeviceServiceError('VALIDATION', 'Offline mutation failed the M9 envelope contract.')
    const mutation = parsed.data
    const queue = this.getOfflineQueue(mutation.device_id)
    if (queue.pending.some((entry) => entry.mutation.idempotency_key === mutation.idempotency_key)) return clone(queue)
    const entry: SpatialOfflineMutationEntry = { mutation, queued_at: nowIso(this.now), attempts: 0, state: 'PENDING', conflict_reason: null }
    queue.pending.push(entry)
    queue.connectivity = 'OFFLINE'
    queue.updated_at = nowIso(this.now)
    this.queues.set(mutation.device_id, queue)
    return clone(queue)
  }

  replayOffline(deviceId: string): SpatialWorkspaceMutationResult[] {
    const queue = this.getOfflineQueue(deviceId)
    const results: SpatialWorkspaceMutationResult[] = []
    for (const entry of [...queue.pending].sort((left, right) => left.queued_at.localeCompare(right.queued_at) || left.mutation.operation_id.localeCompare(right.mutation.operation_id))) {
      if (entry.state === 'DISCARDED' || entry.state === 'REJECTED') continue
      entry.attempts += 1
      const result = this.applyMutation(entry.mutation)
      results.push(result)
      if (result.state === 'APPLIED' || result.state === 'IDEMPOTENT') {
        entry.state = 'REBASED'
        queue.last_consistent_revision = result.server_result_revision
      } else if (result.state === 'CONFLICT') {
        entry.state = 'CONFLICT'
        entry.conflict_reason = result.current_evidence.reason
      } else {
        entry.state = 'REJECTED'
        entry.conflict_reason = result.current_evidence.reason
      }
    }
    queue.connectivity = 'ONLINE'
    queue.updated_at = nowIso(this.now)
    this.queues.set(deviceId, queue)
    return results.map(clone)
  }

  discardOfflineMutation(deviceId: string, idempotencyKey: string): SpatialOfflineQueue {
    const queue = this.getOfflineQueue(deviceId)
    for (const entry of queue.pending) if (entry.mutation.idempotency_key === idempotencyKey) entry.state = 'DISCARDED'
    queue.pending = queue.pending.filter((entry) => entry.state !== 'DISCARDED')
    queue.updated_at = nowIso(this.now)
    this.queues.set(deviceId, queue)
    return clone(queue)
  }

  createShareView(ownerDeviceId: string, options: ShareOptions): SpatialShareView {
    this.getViewport(ownerDeviceId)
    const created = nowIso(this.now)
    const share: SpatialShareView = {
      schema_version: 'spatial.share-view.v1',
      share_id: `share:${ownerDeviceId}:${this.shares.size + 1}`,
      workspace_id: this.world.workspace_id,
      node_id: this.world.node_id,
      owner_device_id: ownerDeviceId,
      audience_device_ids: unique(options.audienceDeviceIds),
      target_ref: options.targetRef ?? null,
      state: 'PENDING',
      focus_authorized: options.focusAuthorized ?? false,
      expires_at: new Date(this.now().getTime() + Math.max(1, options.ttlMs ?? 60_000)).toISOString(),
      created_at: created,
      updated_at: created,
    }
    const parsed = parseSpatialShareView(share)
    if (!parsed.ok) throw new SpatialMultiDeviceServiceError('VALIDATION', 'Share View failed the M9 contract.')
    this.shares.set(share.share_id, parsed.data)
    return clone(parsed.data)
  }

  getShareView(shareId: string): SpatialShareView | null {
    const share = this.shares.get(shareId)
    return share ? clone(share) : null
  }

  acceptShareView(shareId: string, deviceId: string): SpatialShareView {
    const share = this.requireShare(shareId)
    this.assertShareLive(share)
    if (!share.audience_device_ids.includes(deviceId)) throw new SpatialMultiDeviceServiceError('UNAUTHORIZED', 'Share View audience does not include this device.')
    share.state = 'ACCEPTED'
    share.updated_at = nowIso(this.now)
    this.shares.set(shareId, share)
    return clone(share)
  }

  declineShareView(shareId: string, deviceId: string): SpatialShareView {
    const share = this.requireShare(shareId)
    if (!share.audience_device_ids.includes(deviceId)) throw new SpatialMultiDeviceServiceError('UNAUTHORIZED', 'Share View audience does not include this device.')
    share.state = 'DECLINED'
    share.updated_at = nowIso(this.now)
    this.shares.set(shareId, share)
    return clone(share)
  }

  leaveShareView(shareId: string, deviceId: string): SpatialShareView {
    const share = this.requireShare(shareId)
    if (deviceId !== share.owner_device_id && !share.audience_device_ids.includes(deviceId)) throw new SpatialMultiDeviceServiceError('UNAUTHORIZED', 'Device cannot leave this Share View.')
    share.state = 'LEFT'
    share.updated_at = nowIso(this.now)
    this.shares.set(shareId, share)
    return clone(share)
  }

  expireShareViews(): SpatialShareView[] {
    const now = this.now().getTime()
    const expired: SpatialShareView[] = []
    for (const share of this.shares.values()) {
      if ((share.state === 'PENDING' || share.state === 'ACCEPTED') && Date.parse(share.expires_at) <= now) {
        share.state = 'EXPIRED'
        share.updated_at = nowIso(this.now)
        expired.push(clone(share))
      }
    }
    return expired
  }

  applySharedFocus(shareId: string, deviceId: string, targetRef: string): SpatialDeviceViewport {
    const share = this.requireShare(shareId)
    this.assertShareLive(share)
    if (share.state !== 'ACCEPTED' || !share.focus_authorized || !share.audience_device_ids.includes(deviceId)) throw new SpatialMultiDeviceServiceError('VIEWPORT_NOT_SHARED', 'Share View does not authorize focus on this device.')
    if (share.target_ref && share.target_ref !== targetRef) throw new SpatialMultiDeviceServiceError('INVALID_TARGET', 'Shared focus target differs from the authorized target.')
    if (!this.world.semantic_objects.some((object) => object.canonical_ref === targetRef && object.available)) throw new SpatialMultiDeviceServiceError('INVALID_TARGET', 'Shared focus target is unavailable.')
    return this.updateViewport(deviceId, { focus_anchor_ref: targetRef, selection_refs: [targetRef], camera: { ...this.getViewport(deviceId).camera, focus_ref: targetRef } })
  }

  private requireShare(shareId: string): SpatialShareView {
    const share = this.shares.get(shareId)
    if (!share) throw new SpatialMultiDeviceServiceError('INVALID_TARGET', 'Share View was not found.')
    return share
  }

  private assertShareLive(share: SpatialShareView): void {
    if (Date.parse(share.expires_at) <= this.now().getTime()) {
      share.state = 'EXPIRED'
      share.updated_at = nowIso(this.now)
      throw new SpatialMultiDeviceServiceError('EXPIRED_SHARE', 'Share View has expired.')
    }
  }
}
