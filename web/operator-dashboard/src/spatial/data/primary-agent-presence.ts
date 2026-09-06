import {
  type SpatialPrimaryAgentAttentionSeverity,
  type SpatialPrimaryAgentSlot,
} from '@/spatial/contracts'

import {
  primaryAgentVisual,
  primaryAgentAccentColor,
  type PrimaryAgentState,
  type PrimaryAgentVisual,
} from '../prototype/primary-agent'
import type { SpatialQualityProfile } from '../prototype/environment'
import type { PrimaryAgentStateRecord } from './primary-agent-state'

export type PrimaryAgentMaterialProfile = {
  state: PrimaryAgentState
  bodyColor: string
  accentColor: string
  glowColor: string
  glowIntensity: number
  opacity: number
  pulse: 'steady' | 'slow' | 'fast' | 'attention' | 'static'
  depth: 'foreground' | 'mid' | 'background'
  lod: 'physical' | 'simple'
}

export type PrimaryAgentAttentionOverlay = {
  severity: SpatialPrimaryAgentAttentionSeverity
  visible: boolean
  label: string
  color: string
  pulse: 'none' | 'periodic' | 'urgent'
}

export type PrimaryAgentPresenceViewModel = {
  slotId: string
  nodeId: string
  bindingId: string | null
  lifecycleState: SpatialPrimaryAgentSlot['lifecycle_state']
  state: PrimaryAgentState
  label: string
  detail: string
  accessibleLabel: string
  lastSeenAt: string | null
  lastSeenLabel: string
  material: PrimaryAgentMaterialProfile
  attention: PrimaryAgentAttentionOverlay
  sourceRevision: number
  canInteract: boolean
}

export type PrimaryAgentMaterialOverrides = Partial<Record<PrimaryAgentState, Partial<Omit<PrimaryAgentMaterialProfile, 'state' | 'lod'>>>>

const baseMaterial: Record<PrimaryAgentState, Omit<PrimaryAgentMaterialProfile, 'state' | 'lod'>> = {
  READY: { bodyColor: '#f7fbff', accentColor: '#2e7457', glowColor: '#b8f2d0', glowIntensity: 0.48, opacity: 0.98, pulse: 'steady', depth: 'foreground' },
  LISTENING: { bodyColor: '#f7fbff', accentColor: '#4b82b0', glowColor: '#b8ddf2', glowIntensity: 0.54, opacity: 0.98, pulse: 'steady', depth: 'foreground' },
  THINKING: { bodyColor: '#f7fbff', accentColor: '#7777b7', glowColor: '#d5d5ff', glowIntensity: 0.68, opacity: 0.98, pulse: 'slow', depth: 'mid' },
  ACTING: { bodyColor: '#f7fbff', accentColor: '#3b98b7', glowColor: '#b9f3ff', glowIntensity: 0.82, opacity: 0.98, pulse: 'fast', depth: 'mid' },
  WORKING: { bodyColor: '#f7fbff', accentColor: '#4b829f', glowColor: '#c1edff', glowIntensity: 0.78, opacity: 0.98, pulse: 'fast', depth: 'mid' },
  ATTENTION: { bodyColor: '#fffaf1', accentColor: '#b07a3d', glowColor: '#ffd38f', glowIntensity: 0.88, opacity: 0.99, pulse: 'attention', depth: 'foreground' },
  CRITICAL: { bodyColor: '#fff5f5', accentColor: '#b44a59', glowColor: '#ffadb8', glowIntensity: 1, opacity: 1, pulse: 'attention', depth: 'foreground' },
  OFFLINE: { bodyColor: '#b7c1cf', accentColor: '#56677d', glowColor: '#8794a6', glowIntensity: 0.16, opacity: 0.76, pulse: 'static', depth: 'background' },
}

function attentionOverlay(severity: SpatialPrimaryAgentAttentionSeverity): PrimaryAgentAttentionOverlay {
  switch (severity) {
    case 'CRITICAL': return { severity, visible: true, label: 'Critical attention', color: '#b44a59', pulse: 'urgent' }
    case 'WARNING': return { severity, visible: true, label: 'Attention required', color: '#b07a3d', pulse: 'periodic' }
    case 'INFO': return { severity, visible: true, label: 'Informational attention', color: '#4b82b0', pulse: 'periodic' }
    case 'NONE': return { severity, visible: false, label: 'No pending attention', color: '#8794a6', pulse: 'none' }
  }
}

function lastSeenLabel(value: string | null): string {
  return value ? `Last seen ${new Date(value).toLocaleString()}` : 'Last seen unavailable'
}

export function primaryAgentMaterialProfile(
  state: PrimaryAgentState,
  profile: SpatialQualityProfile,
  prefersReducedMotion = false,
  overrides: PrimaryAgentMaterialOverrides = {},
): PrimaryAgentMaterialProfile {
  const visual = primaryAgentVisual(state, profile, prefersReducedMotion)
  const merged = { ...baseMaterial[state], ...(overrides[state] ?? {}) }
  return {
    state,
    ...merged,
    accentColor: merged.accentColor ?? primaryAgentAccentColor(state),
    lod: visual.lod,
    pulse: prefersReducedMotion || profile === 'low' || profile === 'mobile' ? 'static' : merged.pulse,
  }
}

export function composePrimaryAgentPresence(
  slot: SpatialPrimaryAgentSlot,
  state: PrimaryAgentState,
  options: {
    operationalState?: PrimaryAgentStateRecord | null
    profile?: SpatialQualityProfile
    prefersReducedMotion?: boolean
    materialOverrides?: PrimaryAgentMaterialOverrides
  } = {},
): PrimaryAgentPresenceViewModel {
  const profile = options.profile ?? 'desktop'
  const prefersReducedMotion = options.prefersReducedMotion ?? false
  const operationalState = options.operationalState
  const attentionSeverity = operationalState?.attention_severity ?? (state === 'CRITICAL' ? 'CRITICAL' : state === 'ATTENTION' ? 'WARNING' : 'NONE')
  const visual: PrimaryAgentVisual = primaryAgentVisual(state, profile, prefersReducedMotion)
  const material = primaryAgentMaterialProfile(state, profile, prefersReducedMotion, options.materialOverrides)
  const attention = attentionOverlay(attentionSeverity)
  return {
    slotId: slot.slot_id,
    nodeId: slot.node_id,
    bindingId: slot.current_binding_id,
    lifecycleState: slot.lifecycle_state,
    state,
    label: visual.label,
    detail: visual.detail,
    accessibleLabel: `Primary Agent, ${visual.label}. ${visual.detail}`,
    lastSeenAt: slot.last_seen_at ?? operationalState?.last_successful_response_at ?? null,
    lastSeenLabel: lastSeenLabel(slot.last_seen_at ?? operationalState?.last_successful_response_at ?? null),
    material,
    attention,
    sourceRevision: Math.max(slot.revision, operationalState?.revision ?? 0),
    canInteract: slot.lifecycle_state !== 'REVOKED',
  }
}
