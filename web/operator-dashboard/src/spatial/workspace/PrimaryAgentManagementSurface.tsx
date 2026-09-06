import { useState } from 'react'

import type { SpatialPrimaryAgentSlot } from '@/spatial/contracts'
import { Button, GlassFrame, StatusLabel } from '@/spatial/primitives'
import type { PrimaryAgentBindingHealth } from '@/spatial/data'

export type PrimaryAgentManagementSurfaceProps = {
  slot: SpatialPrimaryAgentSlot
  bindingLabel?: string
  bindingType?: string
  capabilities?: readonly string[]
  hooksState?: string
  inboxLag?: number
  health?: PrimaryAgentBindingHealth | null
  auditRef?: string | null
  disabledReason?: string
  onInspect?: () => void
  onHealthCheck?: () => void
  onReplace?: () => void
  onDetach?: () => void
  onRevoke?: () => void
}

function statusFor(slot: SpatialPrimaryAgentSlot, health?: PrimaryAgentBindingHealth | null): 'ready' | 'attention' | 'critical' | 'offline' | 'unknown' {
  if (health?.status === 'invalid-credentials') return 'critical'
  if (health?.status === 'incompatible-protocol') return 'attention'
  switch (slot.lifecycle_state) {
    case 'CONNECTED': return 'ready'
    case 'BINDING': return 'attention'
    case 'DEGRADED': return 'attention'
    case 'REVOKED': return 'critical'
    case 'DISCONNECTED': return 'offline'
    case 'UNASSIGNED': return 'unknown'
  }
}

function lifecycleLabel(slot: SpatialPrimaryAgentSlot): string {
  switch (slot.lifecycle_state) {
    case 'UNASSIGNED': return 'unassigned'
    case 'BINDING': return 'connecting'
    case 'CONNECTED': return 'connected'
    case 'DEGRADED': return 'degraded'
    case 'DISCONNECTED': return 'disconnected'
    case 'REVOKED': return 'revoked'
  }
}

/** Slot management is DOM-only so it remains available in renderer fallback and Classic composition. */
export function PrimaryAgentManagementSurface({
  slot,
  bindingLabel = slot.current_binding_id ?? 'Unassigned',
  bindingType = slot.current_binding_id ? 'MCP / mediated runtime' : 'No binding',
  capabilities = [],
  hooksState = slot.hook_subscription_ref ? 'configured' : 'not configured',
  inboxLag = 0,
  health,
  auditRef = null,
  disabledReason,
  onInspect,
  onHealthCheck,
  onReplace,
  onDetach,
  onRevoke,
}: PrimaryAgentManagementSurfaceProps) {
  const [confirmRevoke, setConfirmRevoke] = useState(false)
  const active = slot.lifecycle_state !== 'REVOKED'
  const assigned = slot.lifecycle_state !== 'UNASSIGNED'
  const canReplace = active && assigned && Boolean(onReplace)
  const canDetach = active && Boolean(slot.current_binding_id) && Boolean(onDetach)
  // An unassigned slot can still be revoked to prevent future delivery; require
  // the explicit confirmation below before the destructive lifecycle change.
  const canRevoke = active && Boolean(onRevoke)
  const connectionLabel = health?.status ?? lifecycleLabel(slot)

  return (
    <details className="aidn-spatial-primary-management" data-aidn-primary-agent-management>
      <summary>Primary Agent management</summary>
      <GlassFrame depth="inset" glass="soft" accent="neutral" radius="medium" className="aidn-spatial-primary-management-frame">
        <div className="aidn-spatial-primary-management-heading">
          <div>
            <StatusLabel status={statusFor(slot, health)}>{connectionLabel}</StatusLabel>
            <p className="aidn-spatial-primary-management-title">Node-scoped slot</p>
          </div>
          <span className="aidn-spatial-primary-management-revision">revision {slot.revision}</span>
        </div>
        <dl className="aidn-spatial-primary-management-fields">
          <div><dt>Agent Identity</dt><dd>{bindingLabel}</dd></div>
          <div><dt>Binding type</dt><dd>{bindingType}</dd></div>
          <div><dt>Connection state</dt><dd>{connectionLabel}</dd></div>
          <div><dt>Granted capabilities</dt><dd>{capabilities.length ? capabilities.join(', ') : 'Not reported'}</dd></div>
          <div><dt>Hooks state</dt><dd>{hooksState}</dd></div>
          <div><dt>Inbox lag</dt><dd>{inboxLag} retained event{inboxLag === 1 ? '' : 's'}</dd></div>
          <div><dt>Last seen</dt><dd>{slot.last_seen_at ? new Date(slot.last_seen_at).toLocaleString() : 'Not reported'}</dd></div>
          <div><dt>Slot / Node</dt><dd>{slot.slot_id} · {slot.node_id}</dd></div>
          <div><dt>Audit</dt><dd>{auditRef ?? `revision ${slot.revision}`}</dd></div>
        </dl>
        <p className="aidn-spatial-primary-management-safe-note">Credentials and secret material are never returned to this surface; only typed references and health evidence are shown.</p>
        {disabledReason ? <p className="aidn-spatial-primary-management-disabled" role="status">Action unavailable: {disabledReason}</p> : null}
        <div className="aidn-spatial-primary-management-actions">
          <Button size="sm" variant="outline" accent="cyan" onClick={onInspect} disabled={!onInspect}>Inspect</Button>
          <Button size="sm" variant="outline" accent="neutral" onClick={onHealthCheck} disabled={!onHealthCheck}>Health check</Button>
          <Button size="sm" variant="outline" accent="violet" onClick={onReplace} disabled={!canReplace} aria-disabled={!canReplace}>Replace</Button>
          <Button size="sm" variant="outline" accent="amber" onClick={onDetach} disabled={!canDetach} aria-disabled={!canDetach}>Detach</Button>
          {confirmRevoke ? (
            <span className="aidn-spatial-primary-management-confirm" role="group" aria-label="Confirm Primary Agent revoke">
              <span>Revoke slot and stop future Hook delivery?</span>
              <Button size="sm" variant="critical" accent="critical" onClick={() => { onRevoke?.(); setConfirmRevoke(false) }} disabled={!canRevoke}>Confirm revoke</Button>
              <Button size="sm" variant="ghost" accent="neutral" onClick={() => setConfirmRevoke(false)}>Cancel</Button>
            </span>
          ) : (
            <Button size="sm" variant="critical" accent="critical" onClick={() => setConfirmRevoke(true)} disabled={!canRevoke} aria-disabled={!canRevoke}>Revoke</Button>
          )}
        </div>
      </GlassFrame>
    </details>
  )
}
