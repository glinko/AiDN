export {
  ChangeIntentError,
  ChangeIntentService,
  SpatialChangeIntentService,
  createChangeIntentService,
  type ChangeIntentApplyResult,
  type ChangeIntentField,
  type ChangeIntentInput,
  type ChangeIntentValidation,
} from './change-intent'
export {
  canTransitionActionFeedback,
  createActionFeedback,
  transitionActionFeedback,
  type ActionFeedbackTransition,
} from './action-feedback'
export { FORBIDDEN_RESOURCE_TERMS, RESOURCE_TERMINOLOGY, assertCanonicalResourceCopy, formatQAtoms } from './resource-terminology'
export { SPATIAL_QUERY_INTENTS, planSpatialQuery, type QueryCompositionPlan, type SpatialQueryIntent } from './query-composition'
