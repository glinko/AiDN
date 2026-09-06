import type { SpatialQualityProfile } from './environment'

/** Full M3.4 operational vocabulary. */
export const PRIMARY_AGENT_OPERATIONAL_STATES = ['READY', 'LISTENING', 'THINKING', 'ACTING', 'WORKING', 'ATTENTION', 'CRITICAL', 'OFFLINE'] as const
export type PrimaryAgentState = (typeof PRIMARY_AGENT_OPERATIONAL_STATES)[number]

/** Prototype A keeps its compact four-step demo sequence for compatibility. */
export const PRIMARY_AGENT_STATES = ['READY', 'THINKING', 'WORKING', 'OFFLINE'] as const

export type PrimaryAgentVisual = {
  state: PrimaryAgentState
  label: string
  detail: string
  accent: 'ready' | 'blue' | 'violet' | 'cyan' | 'amber' | 'critical' | 'offline'
  motion: 'steady' | 'slow-pulse' | 'outbound-pulse' | 'attention-pulse' | 'critical-pulse' | 'static'
  channel: 'halo' | 'core' | 'orbit' | 'attention' | 'critical' | 'placeholder'
  lod: 'physical' | 'simple'
}

export const primaryAgentVisuals: Record<PrimaryAgentState, PrimaryAgentVisual> = {
  READY: {
    state: 'READY',
    label: 'Ready',
    detail: 'Available for a new operator intent.',
    accent: 'ready',
    motion: 'steady',
    channel: 'halo',
    lod: 'physical',
  },
  LISTENING: {
    state: 'LISTENING',
    label: 'Listening',
    detail: 'The Primary Agent is connected and waiting for operator input.',
    accent: 'blue',
    motion: 'steady',
    channel: 'halo',
    lod: 'physical',
  },
  THINKING: {
    state: 'THINKING',
    label: 'Thinking',
    detail: 'Reasoning is in progress; no action has been committed.',
    accent: 'violet',
    motion: 'slow-pulse',
    channel: 'core',
    lod: 'physical',
  },
  ACTING: {
    state: 'ACTING',
    label: 'Acting',
    detail: 'A mediated tool action is in flight; completion is confirmed by Node state.',
    accent: 'cyan',
    motion: 'outbound-pulse',
    channel: 'orbit',
    lod: 'physical',
  },
  WORKING: {
    state: 'WORKING',
    label: 'Working',
    detail: 'A mediated capability is active.',
    accent: 'cyan',
    motion: 'outbound-pulse',
    channel: 'orbit',
    lod: 'physical',
  },
  ATTENTION: {
    state: 'ATTENTION',
    label: 'Attention',
    detail: 'The agent has information or a decision that needs operator awareness.',
    accent: 'amber',
    motion: 'attention-pulse',
    channel: 'attention',
    lod: 'physical',
  },
  CRITICAL: {
    state: 'CRITICAL',
    label: 'Critical',
    detail: 'A critical Node, security, or data condition needs recovery attention.',
    accent: 'critical',
    motion: 'critical-pulse',
    channel: 'critical',
    lod: 'physical',
  },
  OFFLINE: {
    state: 'OFFLINE',
    label: 'Offline',
    detail: 'The Primary Agent is unavailable; System entry remains available.',
    accent: 'offline',
    motion: 'static',
    channel: 'placeholder',
    lod: 'simple',
  },
}

export function primaryAgentVisual(state: PrimaryAgentState, profile: SpatialQualityProfile, prefersReducedMotion = false): PrimaryAgentVisual {
  const visual = primaryAgentVisuals[state]
  return {
    ...visual,
    motion: prefersReducedMotion || profile === 'low' || profile === 'mobile' && state !== 'OFFLINE' ? 'static' : visual.motion,
    lod: profile === 'low' || profile === 'mobile' ? 'simple' : visual.lod,
  }
}

export function nextPrimaryAgentState(state: PrimaryAgentState): PrimaryAgentState {
  const index = PRIMARY_AGENT_STATES.findIndex((candidate) => candidate === state)
  return PRIMARY_AGENT_STATES[(Math.max(index, -1) + 1) % PRIMARY_AGENT_STATES.length]
}

export function primaryAgentSequence(): readonly PrimaryAgentState[] {
  return PRIMARY_AGENT_STATES
}

export function primaryAgentAccentColor(state: PrimaryAgentState): string {
  switch (state) {
    case 'READY': return '#2e7457'
    case 'LISTENING': return '#4b82b0'
    case 'THINKING': return '#7777b7'
    case 'ACTING': return '#3b98b7'
    case 'WORKING': return '#4b829f'
    case 'ATTENTION': return '#b07a3d'
    case 'CRITICAL': return '#b44a59'
    case 'OFFLINE': return '#56677d'
  }
}

export function primaryAgentStateDescription(state: PrimaryAgentState): string {
  return primaryAgentVisuals[state].detail
}
