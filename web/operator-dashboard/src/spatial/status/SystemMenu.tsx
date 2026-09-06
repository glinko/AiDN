import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'

import { Button, GlassFrame, StatusLabel } from '@/spatial/primitives'
import { createMockSpatialNodeStatus } from '@/spatial/data/mock-fixtures'
import {
  SpatialRecoveryCommandService,
  SpatialRecoveryError,
  type RecoveryAuditRecord,
} from './recovery'
import type {
  SpatialNodeStatus,
  SpatialRecoveryAction,
  SpatialRecoveryResult,
  SpatialStatusComponent,
} from '@/spatial/contracts'
import type { SpatialNodeScope } from '@/spatial/data/scope'

export type SystemMenuProps = {
  snapshot?: SpatialNodeStatus | null
  scope?: SpatialNodeScope
  rendererState?: 'ready' | 'failed' | 'unavailable'
  operatorCapabilities?: readonly string[]
  onRefresh?: () => Promise<unknown> | unknown
  onShowInWorkspace?: (component: SpatialStatusComponent) => void
  onReturnClassic?: () => void
  onRecoveryResult?: (result: SpatialRecoveryResult) => void
  recoveryService?: SpatialRecoveryCommandService
  initiallyOpen?: boolean
}

const MENU_ITEMS = ['Status', 'Primary Agent', 'Node Settings', 'Appearance', 'Network', 'Wallet', 'Permissions', 'Advanced'] as const

function stateStatus(state: SpatialNodeStatus['state'] | SpatialStatusComponent['state']): 'ready' | 'attention' | 'critical' | 'offline' | 'unknown' {
  if (state === 'ONLINE' || state === 'READY' || state === 'RUNNING') return 'ready'
  if (state === 'OFFLINE' || state === 'DISCONNECTED') return 'offline'
  if (state === 'DEGRADED' || state === 'STALE' || state === 'BLOCKED' || state === 'STOPPING' || state === 'RESTARTING') return 'attention'
  if (state === 'UNKNOWN') return 'unknown'
  return 'critical'
}

function stateLabel(state: string): string {
  return state.replaceAll('_', ' ')
}

function fallbackSnapshot(scope: SpatialNodeScope): SpatialNodeStatus {
  return createMockSpatialNodeStatus(scope)
}

function capabilityFor(action: SpatialRecoveryAction): string {
  const mapping: Record<SpatialRecoveryAction, string> = {
    RESTART_SERVICE: 'recovery.restart-service',
    STOP_UNSAFE_RUNTIME: 'recovery.stop-unsafe-runtime',
    SUSPEND_AGENT_BINDING: 'recovery.suspend-agent-binding',
    REVOKE_BINDING_CREDENTIALS: 'recovery.revoke-binding-credentials',
    DISABLE_HOOK: 'recovery.disable-hook',
    RETRY_HOOK_DEAD_LETTER: 'recovery.retry-hook-dead-letter',
    BLOCK_REMOTE_ENDPOINT: 'recovery.block-remote-endpoint',
    RETURN_TO_CLASSIC: 'recovery.return-to-classic',
  }
  return mapping[action]
}

function focusable(container: HTMLElement | null): HTMLElement[] {
  if (!container) return []
  return [...container.querySelectorAll<HTMLElement>('button:not([disabled]), [href], [tabindex]:not([tabindex="-1"])')]
}

export function SystemMenu({
  snapshot,
  scope = { hypervisor_id: 'local-hypervisor', node_id: 'local-node' },
  rendererState = 'ready',
  operatorCapabilities = [],
  onRefresh,
  onShowInWorkspace,
  onReturnClassic,
  onRecoveryResult,
  recoveryService,
  initiallyOpen = false,
}: SystemMenuProps) {
  const status = snapshot ?? fallbackSnapshot(scope)
  const service = useMemo(() => recoveryService ?? new SpatialRecoveryCommandService(), [recoveryService])
  const [open, setOpen] = useState(initiallyOpen)
  const [section, setSection] = useState<(typeof MENU_ITEMS)[number]>('Status')
  const [selectedId, setSelectedId] = useState(status.components[0]?.component_id ?? null)
  const [feedback, setFeedback] = useState('')
  const [pendingAction, setPendingAction] = useState<{ component: SpatialStatusComponent; action: SpatialRecoveryAction } | null>(null)
  const dialogRef = useRef<HTMLDivElement>(null)

  const selected = status.components.find((component) => component.component_id === selectedId) ?? status.components[0] ?? null
  const staleMarker = status.cached || status.freshness.state === 'STALE' || status.freshness.state === 'PARTIAL' || status.freshness.state === 'UNAVAILABLE' || ['UNKNOWN', 'OFFLINE', 'DISCONNECTED'].includes(status.state)

  useEffect(() => {
    if (!open) return
    const first = focusable(dialogRef.current)[0]
    first?.focus()
  }, [open])

  const close = () => {
    setOpen(false)
    setPendingAction(null)
  }

  const onDialogKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Escape') {
      event.preventDefault()
      close()
      return
    }
    if (event.key !== 'Tab') return
    const items = focusable(dialogRef.current)
    if (!items.length) return
    const index = items.indexOf(document.activeElement as HTMLElement)
    const next = event.shiftKey ? (index <= 0 ? items.length - 1 : index - 1) : (index + 1) % items.length
    event.preventDefault()
    items[next]?.focus()
  }

  const refresh = async () => {
    try {
      await onRefresh?.()
      setFeedback('Status refresh requested; unrelated Workspace mutations were not triggered.')
    } catch {
      setFeedback('Status refresh is unavailable; the last-known snapshot remains read-only.')
    }
  }

  const runRecovery = async (component: SpatialStatusComponent, action: SpatialRecoveryAction) => {
    const capability = capabilityFor(action)
    if (!operatorCapabilities.some((item) => item.toLowerCase() === capability.toLowerCase())) {
      setFeedback('Recovery action is not authorized for this operator.')
      return
    }
    if (pendingAction?.component.component_id !== component.component_id || pendingAction.action !== action) {
      if (['RESTART_SERVICE', 'STOP_UNSAFE_RUNTIME', 'SUSPEND_AGENT_BINDING', 'REVOKE_BINDING_CREDENTIALS', 'DISABLE_HOOK', 'BLOCK_REMOTE_ENDPOINT'].includes(action)) {
        setPendingAction({ component, action })
        setFeedback('Review the consequence, then confirm this recovery plan.')
        return
      }
    }
    try {
      const plan = service.plan({
        nodeId: status.node_id,
        targetRef: component.spatial_ref ?? component.component_id,
        action,
        currentRevision: status.revision,
        capabilities: operatorCapabilities,
      })
      const result = await service.apply({ plan, currentRevision: status.revision, capabilities: operatorCapabilities, confirmed: pendingAction !== null, actorRef: 'operator-dashboard' })
      onRecoveryResult?.(result)
      setPendingAction(null)
      setFeedback(`${stateLabel(result.state)} · ${result.message ?? 'Recovery result recorded.'}`)
    } catch (error) {
      const message = error instanceof SpatialRecoveryError ? error.message : 'Recovery action was rejected safely.'
      setFeedback(message)
    }
  }

  const auditCount = (service.auditRecords() as RecoveryAuditRecord[]).length

  return (
    <div className="aidn-spatial-system-menu" data-aidn-system-menu-state={open ? 'open' : 'closed'}>
      <Button
        type="button"
        size="sm"
        variant="outline"
        accent="cyan"
        aria-haspopup="dialog"
        aria-expanded={open}
        data-aidn-system-menu-trigger
        onClick={() => setOpen((value) => !value)}
      >
        System Menu
      </Button>
      {open ? (
        <div className="aidn-spatial-system-menu-backdrop" data-aidn-system-menu-backdrop onClick={close}>
          <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby="aidn-system-menu-title" className="aidn-spatial-system-menu-dialog" onClick={(event) => event.stopPropagation()} onKeyDown={onDialogKeyDown}>
            <GlassFrame depth="floating" glass="medium" accent="cyan" radius="large">
              <div className="aidn-spatial-system-menu-heading">
                <div>
                  <StatusLabel status={stateStatus(status.overall_state ?? status.state)}>{stateLabel(status.overall_state ?? status.state)}</StatusLabel>
                  <h2 id="aidn-system-menu-title">System Menu</h2>
                  <p>Node {status.node_id} · revision {status.revision}</p>
                </div>
                <Button type="button" size="sm" variant="ghost" accent="neutral" aria-label="Close System Menu" onClick={close}>Close</Button>
              </div>
              {staleMarker ? <p className="aidn-spatial-system-menu-notice" role="status">{status.cached ? `Last-known snapshot · ${status.last_known_at ?? status.observed_at}` : `Evidence ${stateLabel(status.freshness.state)} · observed ${status.observed_at}`}</p> : null}
              <div className="aidn-spatial-system-menu-layout">
                <nav aria-label="System sections" className="aidn-spatial-system-menu-nav">
                  {MENU_ITEMS.map((item) => <button type="button" key={item} className={item === section ? 'is-selected' : ''} aria-current={item === section ? 'page' : undefined} onClick={() => setSection(item)}>{item}</button>)}
                </nav>
                <section aria-labelledby="aidn-system-menu-section-title" className="aidn-spatial-system-menu-content">
                  <h3 id="aidn-system-menu-section-title">{section}</h3>
                  {section !== 'Status' ? (
                    <div className="aidn-spatial-system-menu-placeholder"><p>{section} remains available through the Node control plane.</p>{section === 'Advanced' && onReturnClassic ? <Button type="button" size="sm" variant="outline" accent="blue" onClick={onReturnClassic}>Return to Classic advanced surface</Button> : null}</div>
                  ) : (
                    <>
                      <div className="aidn-spatial-system-menu-actions"><Button type="button" size="sm" variant="outline" accent="cyan" onClick={refresh}>Refresh Status</Button><span>{status.warning_count} warnings · {status.partial ? 'partial probe' : 'complete probe'} · {auditCount} audits</span></div>
                      <div className="aidn-spatial-status-summary" aria-label="Node status summary">
                        {status.components.map((component) => <button type="button" key={component.component_id} className={component.component_id === selected?.component_id ? 'is-selected' : ''} onClick={() => setSelectedId(component.component_id)}><span className="aidn-spatial-status-state" data-status={component.state}>{stateLabel(component.state)}</span><strong>{component.component_type}</strong><small>{component.freshness.state} · {component.observed_at}</small></button>)}
                      </div>
                      {selected ? (
                        <article className="aidn-spatial-status-details" aria-label={`${selected.component_type} details`}>
                          <div className="aidn-spatial-status-details-heading"><div><StatusLabel status={stateStatus(selected.state)}>{stateLabel(selected.state)}</StatusLabel><h4>{selected.component_type}</h4></div><span>snapshot revision {status.revision}</span></div>
                          <dl><div><dt>Source</dt><dd>{selected.source}</dd></div><div><dt>Observed</dt><dd>{selected.observed_at}</dd></div><div><dt>Freshness</dt><dd>{selected.freshness.state} · {selected.freshness.stale_after_seconds}s TTL</dd></div><div><dt>Issue</dt><dd>{selected.issue_code ?? 'None reported'}</dd></div></dl>
                          {selected.authorization !== 'AUTHORIZED' ? <p className="aidn-spatial-system-menu-notice" role="status">Evidence authorization: {selected.authorization}. Private topology and secrets are not displayed.</p> : null}
                          {selected.details?.last_events.length ? <div className="aidn-spatial-status-events"><h5>Last events</h5>{selected.details.last_events.slice(0, 20).map((event) => <p key={event.id}><span>{event.occurred_at}</span> {event.state} {event.message ?? ''}</p>)}</div> : null}
                          {selected.details?.safe_raw_evidence.length ? <details><summary>Safe raw evidence</summary><ul>{selected.details.safe_raw_evidence.slice(0, 20).map((item) => <li key={item}>{item}</li>)}</ul></details> : null}
                          <div className="aidn-spatial-system-menu-actions">
                            {selected.spatial_ref && onShowInWorkspace ? <Button type="button" size="sm" variant="outline" accent="violet" onClick={() => onShowInWorkspace(selected)}>SHOW_IN_WORKSPACE</Button> : null}
                            {selected.available_actions.map((action) => <Button key={action} type="button" size="sm" variant="ghost" accent="amber" disabled={!operatorCapabilities.includes(capabilityFor(action))} onClick={() => runRecovery(selected, action)}>{pendingAction?.component.component_id === selected.component_id && pendingAction.action === action ? 'Confirm recovery' : stateLabel(action)}</Button>)}
                          </div>
                        </article>
                      ) : <p className="aidn-spatial-system-menu-placeholder">No component evidence is available.</p>}
                    </>
                  )}
                </section>
              </div>
              {rendererState !== 'ready' ? <p className="aidn-spatial-system-menu-notice" data-aidn-renderer-fallback>Renderer {rendererState}; System Menu remains available through DOM controls.</p> : null}
              {feedback ? <p className="aidn-spatial-system-menu-feedback" role="status" aria-live="polite">{feedback}</p> : null}
            </GlassFrame>
          </div>
        </div>
      ) : null}
    </div>
  )
}
