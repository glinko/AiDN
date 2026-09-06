import type { SpatialActionFeedbackState } from '@/spatial/contracts'

export type ActionFeedbackTransition = {
  state: SpatialActionFeedbackState
  summary: string
  completedRefs: readonly string[]
  remainingRefs: readonly string[]
  evidenceRefs: readonly string[]
  safeNextAction: string | null
  needsAttention: boolean
}

const transitions: Record<SpatialActionFeedbackState, readonly SpatialActionFeedbackState[]> = {
  PROPOSED: ['NEEDS_CLARIFICATION', 'AWAITING_APPROVAL', 'REJECTED', 'EXECUTING'],
  NEEDS_CLARIFICATION: ['PROPOSED', 'REJECTED'],
  AWAITING_APPROVAL: ['EXECUTING', 'REJECTED'],
  EXECUTING: ['PARTIALLY_COMPLETED', 'COMPLETED', 'REJECTED', 'ROLLED_BACK'],
  PARTIALLY_COMPLETED: ['EXECUTING', 'COMPLETED', 'ROLLED_BACK', 'FINALITY_PENDING'],
  COMPLETED: ['FINALITY_PENDING'],
  REJECTED: [],
  ROLLED_BACK: [],
  FINALITY_PENDING: ['COMPLETED', 'ROLLED_BACK'],
}

export function canTransitionActionFeedback(from: SpatialActionFeedbackState, to: SpatialActionFeedbackState): boolean {
  return from === to || transitions[from].includes(to)
}

export function createActionFeedback(input: Omit<ActionFeedbackTransition, 'needsAttention'> & { needsAttention?: boolean }): ActionFeedbackTransition {
  const attention = input.needsAttention ?? (input.state === 'PARTIALLY_COMPLETED' || input.state === 'REJECTED' || input.state === 'FINALITY_PENDING')
  return { ...input, needsAttention: attention }
}

export function transitionActionFeedback(current: ActionFeedbackTransition, next: Omit<ActionFeedbackTransition, 'needsAttention'> & { needsAttention?: boolean }): ActionFeedbackTransition {
  if (!canTransitionActionFeedback(current.state, next.state)) throw new Error(`invalid action feedback transition ${current.state} -> ${next.state}`)
  return createActionFeedback(next)
}
