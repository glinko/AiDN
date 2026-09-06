import { describe, expect, it } from 'vitest'

import {
  parseSpatialDeviceViewport,
  parseSpatialPresentationGeometry,
  parseSpatialWorkspaceMutation,
  parseSpatialWorkspaceWorld,
  SPATIAL_SCHEMA_VERSIONS,
} from '@/spatial/contracts'
import { createMockSpatialWorkspaceSnapshot } from '@/spatial/data'
import { parseSpatialEventEnvelope } from '@/spatial/data/events'
import {
  createMobileNavigationState,
  createPresentationGeometry,
  createWorkspaceWorldFromSnapshot,
  handleMobileGesture,
  SpatialMultiDeviceServiceError,
  SpatialMultiDeviceWorkspaceService,
  MOBILE_LONG_PRESS_MS,
} from '@/spatial/multidevice'

const NOW = new Date('2026-09-05T16:00:00.000Z')

function setup(options: ConstructorParameters<typeof SpatialMultiDeviceWorkspaceService>[1] = {}) {
  const snapshot = createMockSpatialWorkspaceSnapshot()
  const world = createWorkspaceWorldFromSnapshot(snapshot, NOW)
  const service = new SpatialMultiDeviceWorkspaceService(world, { now: () => NOW, ...options })
  const target = world.semantic_objects.find((object) => object.available)?.canonical_ref ?? 'agent:primary'
  return { service, world, target }
}

function mutation(service: SpatialMultiDeviceWorkspaceService, target: string, overrides: Record<string, unknown> = {}) {
  const world = service.getWorld()
  return {
    schema_version: SPATIAL_SCHEMA_VERSIONS.workspaceMutation,
    event_id: `event:${String(overrides.operation_id ?? 'move')}`,
    operation_id: String(overrides.operation_id ?? 'operation:move'),
    idempotency_key: String(overrides.idempotency_key ?? `idempotency:${String(overrides.operation_id ?? 'move')}`),
    workspace_id: world.workspace_id,
    node_id: world.node_id,
    device_id: String(overrides.device_id ?? 'desktop'),
    actor_ref: String(overrides.actor_ref ?? 'operator:test'),
    base_revision: Number(overrides.base_revision ?? world.workspace_revision),
    operation: String(overrides.operation ?? 'MOVE_ANCHOR'),
    target_refs: [target],
    conflict_category: 'NONE',
    payload: overrides.payload ?? { semantic_anchor: { x: 1, y: 2, z: -3 } },
    logical_clock: Number(overrides.logical_clock ?? world.workspace_revision + 1),
    created_at: NOW.toISOString(),
  }
}

describe('M9.1 shared semantic world and device-local viewport', () => {
  it('shares pins/anchors while keeping independent camera and frame state', () => {
    const { service, target } = setup()
    const desktop = service.registerDevice('desktop', 'DESKTOP')
    service.registerDevice('mobile', 'MOBILE')
    service.updateViewport('desktop', { camera: { ...desktop.camera, zoom: 2 }, opened_frame_refs: ['frame:desktop'] })
    expect(service.getViewport('mobile').camera.zoom).toBe(1)
    expect(service.getViewport('mobile').opened_frame_refs).toEqual([])
    const result = service.applyMutation(mutation(service, target, { operation: 'PIN', operation_id: 'operation:pin' }))
    expect(result.state).toBe('APPLIED')
    expect(service.getWorld().pins).toContain(target)
    expect(service.getWorld().workspace_revision).toBe(1 + createMockSpatialWorkspaceSnapshot().semantic_revision)
  })

  it('does not treat a device id as authority', () => {
    const { service, target } = setup({ authorizeMutation: () => false })
    const result = service.applyMutation(mutation(service, target, { device_id: 'trusted-looking-device' }))
    expect(result.state).toBe('REJECTED')
    expect(result.conflict_category).toBe('AUTHORIZATION')
    expect(service.getWorld().workspace_revision).toBe(createMockSpatialWorkspaceSnapshot().semantic_revision)
  })
})

describe('M9.2 workspace mutation protocol', () => {
  it('merges disjoint stale branch operations and returns evidence for topology conflicts', () => {
    const { service, world, target } = setup()
    const other = world.semantic_objects.find((object) => object.canonical_ref !== target && object.available)?.canonical_ref ?? 'artifact:other'
    const first = service.applyMutation(mutation(service, target, { operation_id: 'operation:first' }))
    expect(first.state).toBe('APPLIED')
    const disjoint = service.applyMutation(mutation(service, other, { base_revision: 0, operation_id: 'operation:disjoint' }))
    expect(disjoint.state).toBe('APPLIED')
    const conflict = service.applyMutation(mutation(service, target, { base_revision: 0, operation_id: 'operation:conflict' }))
    expect(conflict.state).toBe('CONFLICT')
    expect(conflict.current_evidence.workspace_revision).toBe(world.workspace_revision + 2)
    expect(conflict.current_evidence.winning_operation_id).toBe('operation:first')
  })

  it('makes duplicate retries idempotent and never lets viewport state enter the stream', () => {
    const { service, target } = setup()
    const input = mutation(service, target, { operation: 'PIN', operation_id: 'operation:duplicate' })
    expect(service.applyMutation(input).state).toBe('APPLIED')
    expect(service.applyMutation(input).state).toBe('IDEMPOTENT')
    expect(service.getWorld().workspace_revision).toBe(createMockSpatialWorkspaceSnapshot().semantic_revision + 1)
    expect(() => service.applyMutation({ ...input, operation: 'VIEWPORT_ZOOM' })).toThrow(SpatialMultiDeviceServiceError)
  })
})

describe('M9.3 offline queue and replay', () => {
  it('queues, replays once, and allows discarding a local mutation', () => {
    const { service, target } = setup()
    const input = mutation(service, target, { operation: 'PIN', operation_id: 'operation:offline', device_id: 'mobile' })
    expect(service.queueOfflineMutation(input).pending).toHaveLength(1)
    const replay = service.replayOffline('mobile')
    expect(replay[0]?.state).toBe('APPLIED')
    expect(service.getOfflineQueue('mobile').pending[0]?.state).toBe('REBASED')
    const second = mutation(service, target, { operation: 'PIN', operation_id: 'operation:discard', idempotency_key: 'idempotency:discard', device_id: 'mobile' })
    service.queueOfflineMutation(second)
    expect(service.discardOfflineMutation('mobile', 'idempotency:discard').pending).toHaveLength(1)
  })
})

describe('M9.4 mobile navigation and M9.5 adaptive geometry', () => {
  it('captures canvas gestures, rejects form drags, and exposes keyboard fallbacks', () => {
    let state = createMobileNavigationState()
    state = handleMobileGesture(state, { type: 'pointerdown', x: 20, y: 20, target: 'canvas', time: 0 }).state
    const pan = handleMobileGesture(state, { type: 'pointermove', x: 40, y: 20, time: 20 })
    expect(pan.command?.type).toBe('PAN')
    const form = handleMobileGesture(createMobileNavigationState(), { type: 'pointerdown', x: 20, y: 20, target: 'form', time: 0 })
    expect(form.state.captureScroll).toBe(false)
    const seed = handleMobileGesture(state, { type: 'pointerup', x: 20, y: 20, target: 'canvas', time: MOBILE_LONG_PRESS_MS })
    expect(seed.command?.type).toBe('SEED')
    const home = handleMobileGesture(createMobileNavigationState(), { type: 'keyboard', key: 'Home' })
    expect(home.command?.type).toBe('HOME')
  })

  it('keeps identity while changing presentation arrangement for mobile', () => {
    const { service, target } = setup()
    const geometry = createPresentationGeometry(service.getWorld(), 'mobile', target, 'MOBILE', { width: 390, height: 844, safeArea: { bottom: 24 }, keyboardInset: 280 })
    expect(parseSpatialPresentationGeometry(geometry).ok).toBe(true)
    expect(geometry.arrangement).toBe('BOTTOM_SHEET')
    expect(geometry.keyboard_inset).toBe(280)
    expect(geometry.semantic_ref).toBe(target)
  })
})

describe('M9.6 Share View and M9 contract evidence', () => {
  it('authorizes a temporary focus without overwriting the owner viewport', () => {
    const { service, target } = setup()
    service.registerDevice('owner', 'DESKTOP')
    service.registerDevice('recipient', 'MOBILE')
    const share = service.createShareView('owner', { audienceDeviceIds: ['recipient'], targetRef: target, focusAuthorized: true, ttlMs: 10_000 })
    service.acceptShareView(share.share_id, 'recipient')
    service.applySharedFocus(share.share_id, 'recipient', target)
    expect(service.getViewport('recipient').camera.focus_ref).toBe(target)
    expect(service.getViewport('owner').camera.focus_ref).toBeNull()
  })

  it('parses world, viewport and event contracts', () => {
    const { service, target } = setup()
    expect(parseSpatialWorkspaceWorld(service.getWorld()).ok).toBe(true)
    expect(parseSpatialDeviceViewport(service.registerDevice('device', 'TABLET')).ok).toBe(true)
    const eventPayload = service.getWorld()
    const event = parseSpatialEventEnvelope({
      event_id: 'event:m9:world', event_type: 'spatial.workspace-world.updated.v1', schema_version: SPATIAL_SCHEMA_VERSIONS.workspaceWorld,
      node_id: eventPayload.node_id, sequence: 1, revision: eventPayload.workspace_revision, occurred_at: NOW.toISOString(), correlation_id: null, causation_id: null, payload: eventPayload,
    })
    expect(event.ok).toBe(true)
    expect(parseSpatialWorkspaceMutation(mutation(service, target)).ok).toBe(true)
  })
})

describe('M9.7 scale fixture', () => {
  it('keeps a thousand semantic objects addressable with bounded local state', () => {
    const { service } = setup()
    const world = service.getWorld()
    world.semantic_objects = Array.from({ length: 1000 }, (_, index) => ({
      canonical_ref: `artifact:${index}`,
      semantic_anchor: { x: index % 20, y: Math.floor(index / 20), z: -index / 100 },
      region: 'RECENT_MEMORY', manual_override: false, pinned: false, revision: 0, available: true,
    }))
    const scaled = new SpatialMultiDeviceWorkspaceService(world, { now: () => NOW })
    expect(scaled.getWorld().semantic_objects).toHaveLength(1000)
    expect(scaled.registerDevice('mobile', 'MOBILE').quality_profile).toBe('MOBILE')
  })
})
