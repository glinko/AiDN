import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'

import { useReducedMotion } from 'motion/react'
import { Activity, Box, ChevronRight, Command, Database, Network, Settings2, Sparkles, X } from 'lucide-react'
import { createPortal } from 'react-dom'

import { cn } from '@/lib/utils'
import { isSpatialInteractionEnabled, isSpatialStatusEnabled, isSpatialTopologyEnabled } from '@/lib/feature-flags'
import { Button, GlassFrame, IconButton, StatusLabel } from '@/spatial/primitives'
import { SystemMenu } from '@/spatial/status'
import type { SpatialStatusComponent } from '@/spatial/contracts'
import {
  HOME_CAMERA,
  FOCUS_PRIMARY_AGENT,
  SpatialEntityList,
  SpatialNavigationController,
  SpatialPrototypeGate,
  cameraForViewport,
  evaluateSpatialPerformanceGate,
  focusSpatialEntity,
  focusPrimaryAgent as focusPrimaryAgentCamera,
  homeSpatialCamera,
  nextPrimaryAgentState,
  primaryAgentStateDescription,
  primaryAgentSequence,
  primaryAgentVisuals,
  returnFromSpatialFocus,
  spatialEntityById,
  useSpatialPerformanceProbe,
  zoomSpatialCamera,
  inferSpatialQualityProfile,
  type PrimaryAgentState,
  type SpatialCameraState,
  type SpatialQualityProfile,
} from '@/spatial/prototype'
import { logSpatialRendererFailure } from '@/spatial/route'
import {
  composePrimaryAgentPresence,
  createMockSpatialWorkspaceData,
  type SpatialWorkspaceData,
  type SpatialWorkspaceDataMode,
  type PrimaryAgentPresenceViewModel,
} from '@/spatial/data'
import type { SpatialNodeScope } from '@/spatial/data'

import { SpatialCanvas } from './SpatialCanvas'
import { SpatialDomOverlay, SpatialInteractive } from './SpatialDomOverlay'
import { SpatialRendererErrorBoundary } from './SpatialRendererErrorBoundary'
import { PrimaryAgentManagementSurface } from './PrimaryAgentManagementSurface'
import { ConversationSurface } from './ConversationSurface'
import { SpatialTopologySurface } from './SpatialTopologySurface'
import { SpatialMemorySurface } from '@/spatial/memory'
import { SpatialMultiDeviceSurface } from '@/spatial/multidevice'
import { useSpatialViewport, type SpatialViewport } from './viewport'

export type SpatialWorkspaceState = {
  selectedNodeId: string | null
  viewport: SpatialViewport
  panelOpen: boolean
  qualityProfile: SpatialQualityProfile
  prefersReducedMotion: boolean
  primaryAgentState: PrimaryAgentState
  primaryAgentSlot: SpatialWorkspaceData['primaryAgentSlot']
  primaryAgentPresence: PrimaryAgentPresenceViewModel
  camera: SpatialCameraState
  performanceGate: ReturnType<typeof evaluateSpatialPerformanceGate>
  performanceMetrics: ReturnType<typeof useSpatialPerformanceProbe>[0]
  openPanel: () => void
  openInteraction: () => void
  closePanel: () => void
  selectNode: (nodeId: string) => void
  selectEntity: (entityId: string) => void
  setQualityProfile: (profile: SpatialQualityProfile | 'auto') => void
  cyclePrimaryAgent: () => void
  replayPrimaryAgentSequence: () => void
  homeCamera: () => void
  focusSelectedEntity: () => void
  focusPrimaryAgent: () => void
  returnFromFocus: () => void
  zoomCamera: (delta: number) => void
  workspaceData: SpatialWorkspaceData
  interactionRequest: number
}

export type SpatialWorkspaceProps = {
  children?: ReactNode | ((state: SpatialWorkspaceState) => ReactNode)
  onReturn?: () => void
  simulateRendererError?: boolean
  className?: string
  workspaceData?: SpatialWorkspaceData
  workspaceDataMode?: Exclude<SpatialWorkspaceDataMode, 'remote' | 'malformed'>
  workspaceScope?: SpatialNodeScope
}

function rendererStatus(state: PrimaryAgentState): 'ready' | 'attention' | 'critical' | 'offline' {
  if (state === 'OFFLINE') return 'offline'
  if (state === 'THINKING' || state === 'ATTENTION') return 'attention'
  if (state === 'CRITICAL') return 'critical'
  return 'ready'
}

function RendererErrorFallback({ onRetry, onReturn, portalTarget }: { onRetry: () => void; onReturn?: () => void; portalTarget?: HTMLElement | null }) {
  const content = (
    <div className="aidn-spatial-renderer-error" data-spatial-renderer-state="error" role="alert">
      <StatusLabel status="critical">Renderer fallback</StatusLabel>
      <h2>Spatial scene paused</h2>
      <p>The DOM controls remain available. Retry the scene or return to Classic UI; Node and Workspace state are unchanged.</p>
      <div className="aidn-spatial-renderer-error-actions">
        <Button variant="outline" accent="critical" onClick={onRetry}>Retry renderer</Button>
        {onReturn ? <Button variant="ghost" accent="neutral" onClick={onReturn}>Return to Classic UI</Button> : null}
      </div>
    </div>
  )
  return portalTarget ? createPortal(content, portalTarget) : content
}

function dataStatusLabel(dataState: SpatialWorkspaceData['state']): { label: string; panelLabel: string; status: 'ready' | 'attention' | 'critical' | 'offline' | 'unknown' } {
  switch (dataState) {
    case 'ready': return { label: 'Node data · Ready', panelLabel: 'Ready', status: 'ready' }
    case 'partial': return { label: 'Node data · Partial', panelLabel: 'Partial', status: 'attention' }
    case 'stale': return { label: 'Node data · Stale', panelLabel: 'Stale', status: 'attention' }
    case 'offline': return { label: 'Node data · Offline snapshot', panelLabel: 'Offline snapshot', status: 'offline' }
    case 'empty': return { label: 'Node data · Empty Workspace', panelLabel: 'Empty Workspace', status: 'unknown' }
    case 'loading': return { label: 'Node data · Loading', panelLabel: 'Loading', status: 'unknown' }
    case 'error': return { label: 'Node data · Recovery required', panelLabel: 'Recovery required', status: 'critical' }
  }
}

function DefaultWorkspaceOverlay({ state, onReturn, rendererState }: { state: SpatialWorkspaceState; onReturn?: () => void; rendererState: 'ready' | 'failed' }) {
  const [feedback, setFeedback] = useState('Canvas is ready for a mock Node selection.')
  const selectedEntity = state.workspaceData.projection.entities.find((entity) => entity.id === state.selectedNodeId) ?? spatialEntityById(state.selectedNodeId)
  const selectedLabel = state.selectedNodeId === 'mock-agent'
    ? 'Mock Primary Agent'
    : state.selectedNodeId === 'mock-endpoint'
      ? 'Mock Endpoint'
      : selectedEntity?.label ?? (state.selectedNodeId === 'primary-agent' ? 'Primary Agent' : 'No Node selected')
  const selectedDescription = selectedEntity?.description ?? (state.selectedNodeId === 'primary-agent'
    ? primaryAgentStateDescription(state.primaryAgentState)
    : 'Select a synthetic entity to inspect its presentation-only state.')
  const primaryVisual = primaryAgentVisuals[state.primaryAgentState]
  const primaryPresence = state.primaryAgentPresence
  const hasSelection = Boolean(state.selectedNodeId && state.selectedNodeId !== 'mock-agent' && state.selectedNodeId !== 'mock-endpoint')
  const dataStatus = dataStatusLabel(state.workspaceData.state)
  const entityCounts = {
    subagents: state.workspaceData.projection.entities.filter((entity) => entity.kind === 'subagent').length,
    endpoints: state.workspaceData.projection.entities.filter((entity) => entity.kind === 'endpoint').length,
    artifacts: state.workspaceData.projection.entities.filter((entity) => entity.kind === 'artifact').length,
    attention: state.workspaceData.projection.entities.filter((entity) => entity.kind === 'attention').length,
  }

  const handleNavigationKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Escape' && state.camera.focusId) {
      event.preventDefault()
      state.returnFromFocus()
    }
  }

  return (
    <>
      {isSpatialStatusEnabled() ? <SystemMenu
          snapshot={state.workspaceData.status}
          scope={state.workspaceData.scope}
          rendererState={rendererState}
          onRefresh={state.workspaceData.refresh}
          onReturnClassic={onReturn}
          onShowInWorkspace={(component: SpatialStatusComponent) => {
            const entityId = component.spatial_ref?.split(':').pop() ?? component.component_id
            state.selectEntity(entityId)
            setFeedback(`SHOW_IN_WORKSPACE requested for ${component.component_type}; canonical presence was not mutated.`)
          }}
        /> : null}
      <SpatialInteractive className="aidn-spatial-shell-header">
        <div className="aidn-spatial-brand" aria-label="AiDN Spatial Workspace">
          <span className="aidn-spatial-brand-mark" aria-hidden="true"><Sparkles size={16} strokeWidth={1.8} /></span>
          <div className="aidn-spatial-brand-copy">
            <strong>AiDN</strong>
            <span>Spatial Workspace</span>
          </div>
        </div>
        <div className="aidn-spatial-header-divider" aria-hidden="true" />
        <div className="aidn-spatial-node-context">
          <span className="aidn-spatial-node-context-label">Local Hypervisor</span>
          <strong>{state.workspaceData.scope.node_id}</strong>
          <span className="aidn-spatial-node-context-meta">rev {state.workspaceData.projection.sourceRevision}</span>
        </div>
        <div className="aidn-spatial-header-status" data-aidn-spatial-data-status={state.workspaceData.state}>
          <StatusLabel status={dataStatus.status}>{dataStatus.label}</StatusLabel>
        </div>
        <div className="aidn-spatial-shell-actions">
          <Button
            size="sm"
            variant="outline"
            accent="cyan"
            onClick={state.openPanel}
            aria-label="Open GlassFrame"
          >
            <Box size={15} aria-hidden="true" />
            <span>Open GlassFrame</span>
          </Button>
          {onReturn ? <Button size="sm" variant="ghost" accent="neutral" onClick={onReturn}>Classic UI</Button> : null}
        </div>
      </SpatialInteractive>

      <SpatialInteractive className="aidn-spatial-sidebar">
        <div className="aidn-spatial-sidebar-heading">
          <span>Workspace</span>
          <span className="aidn-spatial-sidebar-node">{state.workspaceData.scope.node_id}</span>
        </div>
        <nav aria-label="Spatial workspace navigation" className="aidn-spatial-sidebar-nav">
          <button type="button" className="is-active" onClick={state.openPanel}>
            <Box size={16} aria-hidden="true" />
            <span>Overview</span>
            <ChevronRight size={14} aria-hidden="true" />
          </button>
          <button type="button" onClick={() => { state.selectNode(FOCUS_PRIMARY_AGENT); state.focusPrimaryAgent() }}>
            <Activity size={16} aria-hidden="true" />
            <span>Primary Agent</span>
          </button>
          <button type="button" onClick={state.openPanel}>
            <Network size={16} aria-hidden="true" />
            <span>Topology</span>
            <span className="aidn-spatial-sidebar-count">{entityCounts.subagents + entityCounts.endpoints}</span>
          </button>
          <button type="button" onClick={state.openPanel}>
            <Database size={16} aria-hidden="true" />
            <span>Memory</span>
          </button>
        </nav>
        <div className="aidn-spatial-sidebar-footer">
          <button type="button" onClick={state.openPanel}>
            <Settings2 size={16} aria-hidden="true" />
            <span>Node settings</span>
          </button>
          <span className="aidn-spatial-sidebar-hint">Drag to orbit · scroll to zoom</span>
        </div>
      </SpatialInteractive>

      <SpatialInteractive className="aidn-spatial-scene-intro">
        <h1>Node workspace</h1>
        <p>Operate the local execution surface with the Primary Agent at the center of the graph.</p>
        <div className="aidn-spatial-scene-legend" aria-label="Workspace legend">
          <span><i className="aidn-spatial-legend-dot aidn-spatial-legend-dot--agent" />Primary Agent</span>
          <span><i className="aidn-spatial-legend-dot aidn-spatial-legend-dot--endpoint" />Endpoints</span>
          <span><i className="aidn-spatial-legend-dot aidn-spatial-legend-dot--artifact" />Artifacts</span>
        </div>
      </SpatialInteractive>

      <SpatialInteractive className="aidn-spatial-signal-strip" aria-label="Node signals">
        <div className="aidn-spatial-signal-heading">
          <span className="aidn-spatial-signal-pulse" aria-hidden="true" />
          <span>Live signals</span>
        </div>
        <div className="aidn-spatial-signal-grid">
          <div><span>Agent</span><strong>{primaryVisual.label}</strong></div>
          <div><span>Graph</span><strong>{entityCounts.subagents + entityCounts.endpoints + entityCounts.artifacts} entities</strong></div>
          <div><span>Attention</span><strong>{entityCounts.attention ? `${entityCounts.attention} open` : 'Clear'}</strong></div>
        </div>
      </SpatialInteractive>

      <SpatialInteractive className="aidn-spatial-commandbar">
        <Button size="sm" variant="solid" accent="blue" onClick={state.openInteraction}>
          <Command size={15} aria-hidden="true" />
          <span>Ask Primary Agent</span>
          <kbd>⌘K</kbd>
        </Button>
        <span className="aidn-spatial-commandbar-context">Presentation-only preview · Node state remains authoritative</span>
        <button type="button" className="aidn-spatial-commandbar-inspect" onClick={state.openPanel}>
          <span>Inspect workspace</span>
          <ChevronRight size={15} aria-hidden="true" />
        </button>
      </SpatialInteractive>
      {state.panelOpen ? (
        <SpatialInteractive className="aidn-spatial-workspace-panel">
          <GlassFrame depth="floating" glass="medium" accent="cyan" radius="large" aria-labelledby="hybrid-shell-title">
            <div className="aidn-spatial-workspace-panel-heading">
              <div>
                <StatusLabel status={state.selectedNodeId ? 'ready' : 'unknown'}>
                  {state.selectedNodeId ? 'Selected Node' : 'Awaiting selection'}
                </StatusLabel>
                <h2 id="hybrid-shell-title">Workspace inspector</h2>
              </div>
              <IconButton aria-label="Close GlassFrame" variant="ghost" accent="neutral" onClick={state.closePanel}>
                <X aria-hidden="true" />
              </IconButton>
            </div>
            <p>Inspect the Node-owned projection without losing the spatial context underneath.</p>
            <div className="aidn-spatial-panel-summary" aria-label="Workspace summary">
              <div><span>Node</span><strong>{state.workspaceData.scope.node_id}</strong></div>
              <div><span>Entities</span><strong>{entityCounts.subagents + entityCounts.endpoints + entityCounts.artifacts}</strong></div>
              <div><span>Renderer</span><strong>{rendererState === 'ready' ? 'Ready' : 'Fallback'}</strong></div>
            </div>
            {isSpatialInteractionEnabled() ? <ConversationSurface state={state} openRequest={state.interactionRequest} /> : null}
            {isSpatialTopologyEnabled() ? <SpatialTopologySurface workspaceData={state.workspaceData} prefersReducedMotion={state.prefersReducedMotion} /> : null}
            <SpatialMemorySurface workspaceData={state.workspaceData} prefersReducedMotion={state.prefersReducedMotion} />
            <SpatialMultiDeviceSurface workspaceData={state.workspaceData} prefersReducedMotion={state.prefersReducedMotion} />
            <div className="aidn-spatial-data-status" data-aidn-spatial-data-status={state.workspaceData.state}>
              <StatusLabel status={dataStatus.status}>{dataStatus.panelLabel}</StatusLabel>
              <span>Node {state.workspaceData.scope.node_id} · revision {state.workspaceData.projection.sourceRevision}</span>
            </div>
            {state.workspaceData.state === 'stale' || state.workspaceData.state === 'offline' ? (
              <p className="aidn-spatial-data-notice" role="status">{state.workspaceData.state === 'stale' ? 'Live evidence is stale; presentation remains available.' : 'Node is offline; showing the last persisted snapshot.'}</p>
            ) : null}
            {state.workspaceData.error ? <p className="aidn-spatial-data-notice" role="alert">Spatial data needs recovery; renderer state is unchanged.</p> : null}

            <section className="aidn-spatial-primary-card" aria-labelledby="primary-agent-title">
              <div className="aidn-spatial-primary-heading">
                <button
                  type="button"
                  className="aidn-spatial-primary-label"
                  data-interactive="true"
                  data-aidn-primary-agent-label
                  aria-label={`Primary Agent, ${primaryVisual.label}`}
                  aria-describedby="primary-agent-description primary-agent-lifecycle"
                  onClick={() => {
                    state.selectNode(FOCUS_PRIMARY_AGENT)
                    state.focusPrimaryAgent()
                  }}
                >
                  <StatusLabel status={rendererStatus(state.primaryAgentState)}>{primaryVisual.label}</StatusLabel>
                  <span id="primary-agent-title">Primary Agent</span>
                </button>
                <span className="aidn-spatial-primary-state" data-aidn-primary-agent-state={state.primaryAgentState}>{state.primaryAgentState}</span>
              </div>
              <p id="primary-agent-description" className="aidn-spatial-primary-detail">{primaryVisual.detail}</p>
              <p id="primary-agent-lifecycle" className="aidn-spatial-primary-lifecycle" data-aidn-primary-agent-lifecycle>
                Slot {primaryPresence.lifecycleState.toLowerCase()} · {primaryPresence.bindingId ? `binding ${primaryPresence.bindingId}` : 'no active binding'} · {primaryPresence.lastSeenLabel}
              </p>
              {primaryPresence.attention.visible ? <p className="aidn-spatial-primary-attention" data-aidn-primary-agent-attention={primaryPresence.attention.severity}>{primaryPresence.attention.label}</p> : null}
              <div className="aidn-spatial-control-actions">
                <Button size="sm" variant="outline" accent="violet" onClick={state.cyclePrimaryAgent}>Cycle state</Button>
                <Button size="sm" variant="ghost" accent="cyan" aria-pressed={state.primaryAgentState !== 'READY'} onClick={state.replayPrimaryAgentSequence}>Replay sequence</Button>
              </div>
              <p className="aidn-spatial-system-placeholder" data-aidn-system-placeholder>System · Classic control plane remains available.</p>
            </section>

            <PrimaryAgentManagementSurface
              slot={state.primaryAgentSlot}
              bindingLabel={state.primaryAgentPresence.bindingId ?? 'Unassigned'}
              bindingType={state.primaryAgentPresence.bindingId ? 'MCP / mediated runtime' : 'No binding'}
              capabilities={state.primaryAgentSlot.capability_grant_ref ? [state.primaryAgentSlot.capability_grant_ref] : []}
              hooksState={state.primaryAgentSlot.hook_subscription_ref ? 'configured' : 'not configured'}
              onInspect={() => setFeedback(`Slot ${state.primaryAgentSlot.slot_id} inspected at revision ${state.primaryAgentSlot.revision}.`)}
              onHealthCheck={() => setFeedback('Health check requested through the authorized Node binding path.')}
              onReplace={() => setFeedback('Replacement requires an authorized binding plan with a fresh slot revision.')}
              onDetach={() => setFeedback('Detach requires an authorized binding plan; Workspace remains Node-owned.')}
              onRevoke={() => setFeedback('Revoke recorded; future Hook delivery is stopped for this binding.')}
            />

            <section className="aidn-spatial-selection-card" aria-labelledby="spatial-selection-title">
              <div className="aidn-spatial-control-heading">
                <span id="spatial-selection-title" className="aidn-spatial-control-label">Selection</span>
                <span className="aidn-spatial-control-value" data-aidn-selected-label>{selectedLabel}</span>
              </div>
              <p className="aidn-spatial-selection-description">{selectedDescription}</p>
              {selectedEntity ? <span className="aidn-spatial-entity-kind">{selectedEntity.kind} · priority {(selectedEntity.priority * 100).toFixed(0)}%</span> : null}
            </section>

            <div className="aidn-spatial-quality-row">
              <label htmlFor="spatial-quality-profile" className="aidn-spatial-control-label">Scene quality</label>
              <select
                id="spatial-quality-profile"
                className="aidn-spatial-quality-select"
                data-aidn-quality-selector
                value={state.qualityProfile}
                onChange={(event) => state.setQualityProfile(event.target.value as SpatialQualityProfile)}
              >
                <option value="mobile">Mobile</option>
                <option value="low">Low</option>
                <option value="desktop">Desktop</option>
                <option value="high">High</option>
              </select>
              <Button size="sm" variant="ghost" accent="neutral" onClick={() => state.setQualityProfile('auto')}>Auto</Button>
            </div>

            <SpatialNavigationController
              camera={state.camera}
              hasSelection={hasSelection}
              prefersReducedMotion={state.prefersReducedMotion}
              onHome={state.homeCamera}
              onFocusSelected={state.focusSelectedEntity}
              onBack={state.returnFromFocus}
              onZoom={state.zoomCamera}
            />

            <SpatialEntityList selectedEntityId={state.selectedNodeId} onSelect={state.selectEntity} entities={state.workspaceData.projection.entities} />
            <SpatialPrototypeGate gate={state.performanceGate} metrics={state.performanceMetrics} />

            <div onKeyDown={handleNavigationKeyDown}>
              <Button accent="blue" onClick={() => setFeedback('DOM control handled the action without touching the canvas.')}>DOM control over canvas</Button>
              <p className="aidn-spatial-workspace-feedback" role="status" aria-live="polite">{feedback}</p>
              <p className="aidn-spatial-workspace-viewport" data-aidn-viewport-readout>
                Viewport {state.viewport.width}×{state.viewport.height} · DPR {state.viewport.dpr.toFixed(2)} · revision {state.viewport.revision}
              </p>
            </div>
            {onReturn ? <Button variant="ghost" accent="neutral" onClick={onReturn}>Return to Classic UI</Button> : null}
          </GlassFrame>
        </SpatialInteractive>
      ) : null}
    </>
  )
}

export function SpatialWorkspace({ children, onReturn, simulateRendererError = false, className, workspaceData, workspaceDataMode = 'mock-real', workspaceScope }: SpatialWorkspaceProps) {
  const workspaceRef = useRef<HTMLDivElement>(null)
  const viewport = useSpatialViewport(workspaceRef)
  const prefersReducedMotion = useReducedMotion() ?? false
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const [panelOpen, setPanelOpen] = useState(false)
  const [interactionRequest, setInteractionRequest] = useState(0)
  const [retryToken, setRetryToken] = useState(0)
  const [rendererFailed, setRendererFailed] = useState(false)
  const [qualityOverride, setQualityOverride] = useState<SpatialQualityProfile | null>(null)
  const [primaryAgentState, setPrimaryAgentState] = useState<PrimaryAgentState>('READY')
  const [camera, setCamera] = useState<SpatialCameraState>(HOME_CAMERA)
  const [, setSequenceRunning] = useState(false)
  const [performanceMetrics, markInteraction] = useSpatialPerformanceProbe(panelOpen)
  const sequenceTimerRef = useRef<number | null>(null)
  const qualityProfile = qualityOverride ?? inferSpatialQualityProfile(viewport)
  const workspaceScopeHypervisorId = workspaceScope?.hypervisor_id
  const workspaceScopeNodeId = workspaceScope?.node_id
  const fallbackWorkspaceData = useMemo(
    () => createMockSpatialWorkspaceData(
      qualityProfile,
      workspaceDataMode,
      workspaceScopeHypervisorId && workspaceScopeNodeId
        ? { hypervisor_id: workspaceScopeHypervisorId, node_id: workspaceScopeNodeId }
        : undefined,
    ),
    [qualityProfile, workspaceDataMode, workspaceScopeHypervisorId, workspaceScopeNodeId],
  )
  const resolvedWorkspaceData = workspaceData ?? fallbackWorkspaceData
  const performanceGate = useMemo(() => evaluateSpatialPerformanceGate(performanceMetrics), [performanceMetrics])
  const primaryAgentStateFromData = resolvedWorkspaceData.primaryAgentOperationalState?.state ?? resolvedWorkspaceData.projection.primaryAgent?.state
  const primaryAgentRevision = Math.max(resolvedWorkspaceData.primaryAgentOperationalState?.revision ?? 0, resolvedWorkspaceData.projection.primaryAgent?.sourceRevision ?? 0)

  useEffect(() => {
    if (primaryAgentStateFromData) setPrimaryAgentState(primaryAgentStateFromData)
  }, [primaryAgentRevision, primaryAgentStateFromData])

  const primaryAgentPresence = useMemo(() => composePrimaryAgentPresence(
    resolvedWorkspaceData.primaryAgentSlot,
    primaryAgentState,
    {
      operationalState: resolvedWorkspaceData.primaryAgentOperationalState,
      profile: qualityProfile,
      prefersReducedMotion,
    },
  ), [prefersReducedMotion, primaryAgentState, qualityProfile, resolvedWorkspaceData.primaryAgentOperationalState, resolvedWorkspaceData.primaryAgentSlot])

  useEffect(() => {
    setCamera((current) => cameraForViewport(current, viewport))
  }, [viewport])

  useEffect(() => () => {
    if (sequenceTimerRef.current !== null) window.clearTimeout(sequenceTimerRef.current)
  }, [])

  const selectNode = useCallback((nodeId: string) => {
    setSelectedNodeId(nodeId)
    setPanelOpen(true)
    markInteraction()
  }, [markInteraction])

  const selectEntity = useCallback((entityId: string) => {
    selectNode(entityId)
  }, [selectNode])

  const openInteraction = useCallback(() => {
    setPanelOpen(true)
    setInteractionRequest((request) => request + 1)
    markInteraction()
  }, [markInteraction])

  const setQualityProfile = useCallback((profile: SpatialQualityProfile | 'auto') => {
    setQualityOverride(profile === 'auto' ? null : profile)
  }, [])

  const cyclePrimaryAgent = useCallback(() => {
    setPrimaryAgentState((current) => nextPrimaryAgentState(current))
    markInteraction()
  }, [markInteraction])

  const replayPrimaryAgentSequence = useCallback(() => {
    if (sequenceTimerRef.current !== null) window.clearTimeout(sequenceTimerRef.current)
    const sequence = primaryAgentSequence()
    if (prefersReducedMotion) {
      setPrimaryAgentState(sequence[0])
      setSequenceRunning(false)
      return
    }
    let index = 0
    setSequenceRunning(true)
    setPrimaryAgentState(sequence[0])
    const advance = () => {
      index += 1
      if (index >= sequence.length) {
        setSequenceRunning(false)
        sequenceTimerRef.current = null
        return
      }
      setPrimaryAgentState(sequence[index])
      sequenceTimerRef.current = window.setTimeout(advance, 850)
    }
    sequenceTimerRef.current = window.setTimeout(advance, 850)
    markInteraction()
  }, [markInteraction, prefersReducedMotion])

  const homeCamera = useCallback(() => {
    setCamera((current) => homeSpatialCamera(current))
    markInteraction()
  }, [markInteraction])

  const focusSelectedEntity = useCallback(() => {
    if (!selectedNodeId) return
    const entity = resolvedWorkspaceData.projection.entities.find((candidate) => candidate.id === selectedNodeId) ?? spatialEntityById(selectedNodeId) ?? (selectedNodeId === FOCUS_PRIMARY_AGENT
      ? { id: FOCUS_PRIMARY_AGENT, kind: 'subagent' as const, label: 'Primary Agent', description: 'Primary Agent focus target.', position: { x: 0, y: 0.42, z: 0 }, priority: 1 }
      : undefined)
    if (!entity) return
    setCamera((current) => focusSpatialEntity(current, entity))
    markInteraction()
  }, [markInteraction, resolvedWorkspaceData.projection.entities, selectedNodeId])

  const focusPrimaryAgent = useCallback(() => {
    setCamera((current) => focusPrimaryAgentCamera(current))
    markInteraction()
  }, [markInteraction])

  const returnFromFocus = useCallback(() => {
    setCamera((current) => returnFromSpatialFocus(current))
    markInteraction()
  }, [markInteraction])

  const zoomCamera = useCallback((delta: number) => {
    setCamera((current) => zoomSpatialCamera(current, delta))
    markInteraction()
  }, [markInteraction])

  const state: SpatialWorkspaceState = {
    selectedNodeId,
    viewport,
    panelOpen,
    qualityProfile,
    prefersReducedMotion,
    primaryAgentState,
    primaryAgentSlot: resolvedWorkspaceData.primaryAgentSlot,
    primaryAgentPresence,
    camera,
    performanceGate,
    performanceMetrics,
    openPanel: () => setPanelOpen(true),
    openInteraction,
    closePanel: () => setPanelOpen(false),
    selectNode,
    selectEntity,
    setQualityProfile,
    cyclePrimaryAgent,
    replayPrimaryAgentSequence,
    homeCamera,
    focusSelectedEntity,
    focusPrimaryAgent,
    returnFromFocus,
    zoomCamera,
    workspaceData: resolvedWorkspaceData,
    interactionRequest,
  }
  const overlay = typeof children === 'function' ? children(state) : children

  return (
    <div
      ref={workspaceRef}
      className={cn('aidn-spatial-workspace', className)}
      data-spatial-workspace="hybrid"
      data-aidn-selected-node={selectedNodeId ?? 'none'}
      data-aidn-viewport-revision={viewport.revision}
      data-aidn-viewport-orientation={viewport.orientation}
      data-aidn-quality-profile={qualityProfile}
      data-aidn-primary-agent-state={primaryAgentState}
      data-aidn-primary-agent-lifecycle={primaryAgentPresence.lifecycleState}
      data-aidn-primary-agent-binding={primaryAgentPresence.bindingId ?? 'none'}
      data-aidn-camera-focus={camera.focusId ?? 'home'}
      data-aidn-camera-zoom={camera.zoom.toFixed(2)}
      data-aidn-performance-gate={performanceGate.status}
      data-aidn-workspace-data-state={resolvedWorkspaceData.state}
      data-aidn-workspace-source-revision={resolvedWorkspaceData.projection.sourceRevision}
      data-aidn-workspace-freshness={resolvedWorkspaceData.projection.freshnessState}
      data-aidn-entity-counts={`${resolvedWorkspaceData.projection.entities.filter((entity) => entity.kind === 'subagent').length}/${resolvedWorkspaceData.projection.entities.filter((entity) => entity.kind === 'endpoint').length}/${resolvedWorkspaceData.projection.entities.filter((entity) => entity.kind === 'artifact').length}/${resolvedWorkspaceData.projection.entities.filter((entity) => entity.kind === 'attention').length}`}
    >
      <div className="aidn-spatial-canvas-layer" data-spatial-layer="canvas">
        <SpatialRendererErrorBoundary
          key={retryToken}
          fallback={<RendererErrorFallback onRetry={() => { setRendererFailed(false); setRetryToken((token) => token + 1) }} onReturn={onReturn} portalTarget={workspaceRef.current} />}
          onError={() => { setRendererFailed(true); logSpatialRendererFailure('renderer-init-failed') }}
        >
          <SpatialCanvas
            viewport={viewport}
            selectedNodeId={selectedNodeId}
            onNodeSelect={selectNode}
            onEmptySpace={isSpatialInteractionEnabled() ? openInteraction : undefined}
            qualityProfile={qualityProfile}
            primaryAgentState={primaryAgentState}
            primaryAgentPresence={primaryAgentPresence}
            prefersReducedMotion={prefersReducedMotion}
            cameraState={camera}
            onCameraChange={(next) => setCamera(next)}
            simulateRendererError={simulateRendererError}
            entities={resolvedWorkspaceData.projection.entities}
            relations={resolvedWorkspaceData.projection.relations}
            workspaceDataState={resolvedWorkspaceData.state}
          />
        </SpatialRendererErrorBoundary>
      </div>
      <SpatialDomOverlay aria-label="Spatial DOM overlay">
        <DefaultWorkspaceOverlay state={state} onReturn={onReturn} rendererState={rendererFailed ? 'failed' : 'ready'} />
        {overlay}
      </SpatialDomOverlay>
    </div>
  )
}
