import { useMemo, useState } from 'react'

import { isSpatialMultiDeviceSyncEnabled } from '@/lib/feature-flags'
import { Button, GlassFrame, StatusLabel } from '@/spatial/primitives'
import type { SpatialWorkspaceData } from '@/spatial/data'

import {
  createPresentationGeometry,
  createWorkspaceWorldFromSnapshot,
  SpatialMultiDeviceWorkspaceService,
} from './service'
import {
  createMobileNavigationState,
  handleMobileGesture,
  type MobileNavigationState,
} from './navigation'

type SpatialMultiDeviceSurfaceProps = {
  workspaceData: SpatialWorkspaceData
  prefersReducedMotion?: boolean
}

const FIXTURE_NOW = new Date('2026-09-05T16:00:00.000Z')

/**
 * M9 is intentionally a DOM surface around the shared semantic boundary. The
 * two viewport cards use one service/world and separate device-local state;
 * camera controls never call applyMutation.
 */
export function SpatialMultiDeviceSurface({ workspaceData, prefersReducedMotion = false }: SpatialMultiDeviceSurfaceProps) {
  const world = useMemo(() => workspaceData.snapshot ? createWorkspaceWorldFromSnapshot(workspaceData.snapshot, FIXTURE_NOW) : null, [workspaceData.snapshot])
  const service = useMemo(() => world ? new SpatialMultiDeviceWorkspaceService(world, { now: () => new Date() }) : null, [world])
  const [, setRevision] = useState(0)
  const [feedback, setFeedback] = useState('Semantic world is shared; camera and presentation geometry remain device-local.')
  const [mobileGesture, setMobileGesture] = useState<MobileNavigationState>(() => createMobileNavigationState())
  const bump = () => setRevision((value) => value + 1)

  if (!isSpatialMultiDeviceSyncEnabled() || !service) return null

  const desktop = service.registerDevice('desktop-demo', 'DESKTOP')
  const mobile = service.registerDevice('mobile-demo', 'MOBILE')
  const semanticRef = service.getWorld().semantic_objects.find((object) => object.available)?.canonical_ref ?? null
  const worldSnapshot = service.getWorld()
  const geometry = semanticRef ? createPresentationGeometry(worldSnapshot, 'mobile-demo', semanticRef, 'MOBILE', { width: 390, height: 844, safeArea: { bottom: 24 }, keyboardInset: 0 }) : null
  const queue = service.getOfflineQueue('mobile-demo')

  const applyPin = () => {
    if (!semanticRef) return
    const revision = service.getWorld().workspace_revision
    const result = service.applyMutation({
      schema_version: 'spatial.workspace-mutation.v1',
      event_id: `event:m9:pin:${revision + 1}`,
      operation_id: `operation:m9:pin:${revision + 1}`,
      idempotency_key: `idempotency:m9:pin:${revision + 1}`,
      workspace_id: worldSnapshot.workspace_id,
      node_id: worldSnapshot.node_id,
      device_id: 'desktop-demo',
      actor_ref: 'operator:demo',
      base_revision: revision,
      operation: 'PIN',
      target_refs: [semanticRef],
      conflict_category: 'NONE',
      payload: {},
      logical_clock: revision + 1,
      created_at: new Date().toISOString(),
    })
    setFeedback(result.state === 'APPLIED' ? `${semanticRef} pinned in the shared semantic world at revision ${result.server_result_revision}.` : `Pin ${result.state.toLowerCase()}: ${result.current_evidence.reason ?? 'review conflict evidence'}.`)
    bump()
  }

  const shareFocus = () => {
    if (!semanticRef) return
    const share = service.createShareView('desktop-demo', { audienceDeviceIds: ['mobile-demo'], targetRef: semanticRef, focusAuthorized: true })
    service.acceptShareView(share.share_id, 'mobile-demo')
    service.applySharedFocus(share.share_id, 'mobile-demo', semanticRef)
    setFeedback(`Share View accepted for mobile-demo; only its local focus changed. Cameras remain independent.`)
    bump()
  }

  const queueOfflinePin = () => {
    if (!semanticRef) return
    const revision = service.getWorld().workspace_revision
    service.queueOfflineMutation({
      schema_version: 'spatial.workspace-mutation.v1',
      event_id: `event:m9:offline-pin:${revision + 1}`,
      operation_id: `operation:m9:offline-pin:${revision + 1}`,
      idempotency_key: `idempotency:m9:offline-pin:${revision + 1}`,
      workspace_id: worldSnapshot.workspace_id,
      node_id: worldSnapshot.node_id,
      device_id: 'mobile-demo',
      actor_ref: 'operator:demo',
      base_revision: revision,
      operation: 'PIN',
      target_refs: [semanticRef],
      conflict_category: 'NONE',
      payload: {},
      logical_clock: revision + 1,
      created_at: new Date().toISOString(),
    })
    setFeedback('Mobile mutation queued offline with an idempotency key; no protocol/resource action was attempted.')
    bump()
  }

  const replayOffline = () => {
    const results = service.replayOffline('mobile-demo')
    setFeedback(results.length ? `Offline replay resolved ${results.length} mutation(s); duplicate retries remain idempotent.` : 'No pending offline mutations.')
    bump()
  }

  const dispatchMobileGesture = (event: Parameters<typeof handleMobileGesture>[1]) => {
    const result = handleMobileGesture(mobileGesture, event)
    setMobileGesture(result.state)
    if (result.command) setFeedback(`Mobile ${result.command.type.toLowerCase()} changed the local viewport only.`)
  }

  return (
    <section className="aidn-spatial-multidevice-surface" data-aidn-m9-multidevice aria-labelledby="m9-multidevice-title">
      <div className="aidn-spatial-memory-heading">
        <div>
          <StatusLabel status="ready">M9 · Multi-device</StatusLabel>
          <h3 id="m9-multidevice-title">One Workspace, two local viewports</h3>
        </div>
        <span data-aidn-m9-world-revision>world revision {worldSnapshot.workspace_revision}</span>
      </div>
      <p className="aidn-spatial-topology-muted">Shared refs, relations, pins and anchors propagate. Camera, focus, selection, frames, gestures and geometry stay on the originating device.</p>

      <div className="aidn-spatial-multidevice-grid">
        <GlassFrame depth="raised" glass="soft" accent="cyan" radius="medium">
          <div className="aidn-spatial-topology-card-heading"><span>Desktop · {desktop.device_id}</span><span data-aidn-m9-desktop-camera>{desktop.camera.focus_ref ?? 'HOME'} · zoom {desktop.camera.zoom.toFixed(2)}</span></div>
          <p className="aidn-spatial-multidevice-detail">Local layout {desktop.local_layout_revision}; semantic refs {worldSnapshot.semantic_objects.length}.</p>
          <div className="aidn-spatial-control-actions">
            <Button size="sm" variant="outline" accent="cyan" onClick={() => { service.updateViewport('desktop-demo', { camera: { ...desktop.camera, zoom: desktop.camera.zoom + 0.25 } }); setFeedback('Desktop zoom changed locally; mobile camera was untouched.'); bump() }}>Zoom desktop</Button>
            <Button size="sm" variant="ghost" accent="violet" onClick={applyPin} disabled={!semanticRef}>Pin shared ref</Button>
          </div>
        </GlassFrame>

        <GlassFrame depth="raised" glass="soft" accent="violet" radius="medium">
          <div className="aidn-spatial-topology-card-heading"><span>Mobile · {mobile.device_id}</span><span data-aidn-m9-mobile-camera>{mobile.camera.focus_ref ?? 'HOME'} · zoom {mobile.camera.zoom.toFixed(2)}</span></div>
          <p className="aidn-spatial-multidevice-detail">{geometry?.arrangement.toLowerCase().replace('_', ' ')} · safe bottom {geometry?.safe_area_inset.bottom ?? 0}px · {mobileGesture.state.toLowerCase()}</p>
          <div className="aidn-spatial-control-actions">
            <Button size="sm" variant="outline" accent="violet" onClick={() => dispatchMobileGesture({ type: 'pointerdown', x: 160, y: 280, target: 'canvas', time: 0 })}>Touch start</Button>
            <Button size="sm" variant="ghost" accent="cyan" onClick={() => dispatchMobileGesture({ type: 'pinch', scale: 1.15 })}>Pinch zoom</Button>
            <Button size="sm" variant="ghost" accent="neutral" onClick={() => dispatchMobileGesture({ type: 'keyboard', key: 'Home' })}>HOME</Button>
            <Button size="sm" variant="outline" accent="amber" onClick={shareFocus} disabled={!semanticRef}>Share focus</Button>
          </div>
        </GlassFrame>
      </div>

      <div className="aidn-spatial-multidevice-actions">
        <Button size="sm" variant="outline" accent="amber" onClick={queueOfflinePin} disabled={!semanticRef}>Queue mobile mutation</Button>
        <Button size="sm" variant="ghost" accent="cyan" onClick={replayOffline}>Replay offline ({queue.pending.length})</Button>
        <span className="aidn-spatial-memory-hint" data-aidn-m9-offline-state>{queue.connectivity.toLowerCase()} · {queue.pending.length} pending</span>
      </div>
      <p className="aidn-spatial-multidevice-feedback" role="status" aria-live="polite">{feedback}{prefersReducedMotion ? ' Reduced motion is active; focus feedback is immediate.' : ''}</p>
    </section>
  )
}
