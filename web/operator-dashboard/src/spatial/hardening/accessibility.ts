export type SpatialAccessibilityRequirement = {
  id: string
  role: string
  accessibleName?: string
  nameRequired?: boolean
  keyboardOperable?: boolean
  focusable?: boolean
  focusOrder?: number
  focusReturnId?: string | null
  liveRegion?: 'polite' | 'assertive' | 'off'
  liveUpdateHz?: number
  minTouchTargetPx?: number
  colorIndependent?: boolean
  highContrastSafe?: boolean
  reducedMotionSafe?: boolean
  reducedTransparencySafe?: boolean
  hasErrorInstructions?: boolean
}

export type SpatialAccessibilityIssue = {
  code:
    | 'MISSING_NAME'
    | 'NOT_KEYBOARD_OPERABLE'
    | 'NOT_FOCUSABLE'
    | 'INVALID_FOCUS_ORDER'
    | 'MISSING_FOCUS_RETURN'
    | 'LIVE_REGION_TOO_FAST'
    | 'TOUCH_TARGET_TOO_SMALL'
    | 'COLOR_ONLY_STATE'
    | 'HIGH_CONTRAST_UNSAFE'
    | 'MOTION_UNSAFE'
    | 'TRANSPARENCY_UNSAFE'
    | 'MISSING_ERROR_INSTRUCTIONS'
  id: string
  message: string
}

export type SpatialAccessibilityGate = {
  status: 'PASS' | 'BLOCKED'
  issues: readonly SpatialAccessibilityIssue[]
}

export const SPATIAL_PRIMARY_KEYBOARD_FLOW = [
  'open-workspace',
  'inspect-agent',
  'create-interaction',
  'inspect-endpoint',
  'submit-test',
  'view-result',
  'open-status',
  'return-home',
] as const

export function validateSpatialAccessibilityContract(requirement: SpatialAccessibilityRequirement): SpatialAccessibilityIssue[] {
  const issues: SpatialAccessibilityIssue[] = []
  const add = (code: SpatialAccessibilityIssue['code'], message: string) => issues.push({ code, id: requirement.id, message })
  if (requirement.nameRequired !== false && !requirement.accessibleName?.trim()) add('MISSING_NAME', 'A visible or programmatic accessible name is required')
  if (requirement.keyboardOperable !== false) {
    if (requirement.keyboardOperable !== true) add('NOT_KEYBOARD_OPERABLE', 'Primary interaction must be operable without a pointer')
    if (requirement.focusable !== true) add('NOT_FOCUSABLE', 'Keyboard interaction requires a focusable target')
  }
  if (requirement.focusOrder !== undefined && (!Number.isInteger(requirement.focusOrder) || requirement.focusOrder < 0)) add('INVALID_FOCUS_ORDER', 'Focus order must be a non-negative integer')
  if (requirement.focusable === true && requirement.focusReturnId === undefined) add('MISSING_FOCUS_RETURN', 'Transient views must declare where focus returns')
  if (requirement.liveRegion && requirement.liveRegion !== 'off' && (requirement.liveUpdateHz ?? 0) > 4) add('LIVE_REGION_TOO_FAST', 'Streaming announcements must be rate limited')
  if ((requirement.minTouchTargetPx ?? 44) < 44) add('TOUCH_TARGET_TOO_SMALL', 'Interactive targets must be at least 44 CSS pixels')
  if (requirement.colorIndependent !== true) add('COLOR_ONLY_STATE', 'State must have text, shape or icon semantics in addition to color')
  if (requirement.highContrastSafe !== true) add('HIGH_CONTRAST_UNSAFE', 'The component must remain legible in forced colors/high contrast')
  if (requirement.reducedMotionSafe !== true) add('MOTION_UNSAFE', 'The component must provide a reduced-motion path')
  if (requirement.reducedTransparencySafe !== true) add('TRANSPARENCY_UNSAFE', 'The component must remain readable without blur/transparency')
  if (requirement.hasErrorInstructions !== true) add('MISSING_ERROR_INSTRUCTIONS', 'Errors must explain recovery and the next safe action')
  return issues
}

export function evaluateSpatialAccessibility(requirements: readonly SpatialAccessibilityRequirement[]): SpatialAccessibilityGate {
  const issues = requirements.flatMap(validateSpatialAccessibilityContract)
  return { status: issues.length === 0 ? 'PASS' : 'BLOCKED', issues }
}

export function validateSpatialPrimaryFlow(flow: readonly string[]): SpatialAccessibilityIssue[] {
  const expected = [...SPATIAL_PRIMARY_KEYBOARD_FLOW]
  const actual = flow.filter(Boolean)
  if (expected.every((step, index) => actual[index] === step)) return []
  return [{ code: 'INVALID_FOCUS_ORDER', id: 'primary-flow', message: `Expected keyboard flow: ${expected.join(' > ')}` }]
}

