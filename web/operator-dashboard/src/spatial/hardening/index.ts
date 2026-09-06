export {
  SpatialAuthorizationService,
  SpatialAuditService,
  SPATIAL_AUTHORIZATION_CAPABILITY_MATRIX,
  SENSITIVE_AUDIT_KEYS,
  assertNoSensitivePayload,
  redactSensitiveKeys,
  type RedactionResult,
  type SpatialAuditInput,
  type SpatialAuditServiceOptions,
  type SpatialAuthorizationOutcome,
  type SpatialAuthorizationRequest,
  type SpatialAuthorizationServiceOptions,
} from './authorization'

export {
  RELIABILITY_INVARIANTS,
  RELIABILITY_RECOVERY_ACTIONS,
  SpatialReliabilityController,
  type ReliabilityFaultInput,
  type ReliabilityInvariant,
  type ReliabilityInvariantResult,
  type SpatialReliabilityControllerOptions,
} from './reliability'

export {
  SPATIAL_PRIMARY_KEYBOARD_FLOW,
  evaluateSpatialAccessibility,
  validateSpatialAccessibilityContract,
  validateSpatialPrimaryFlow,
  type SpatialAccessibilityGate,
  type SpatialAccessibilityIssue,
  type SpatialAccessibilityRequirement,
} from './accessibility'

export {
  SPATIAL_CATALOG,
  SPATIAL_LOCALES,
  SPATIAL_PROTOCOL_TERMS,
  assertProtocolTermNotMachineTranslated,
  formatSpatialQuantity,
  formatSpatialTimestamp,
  localizeSpatialError,
  spatialLocaleLanguageTag,
  translateSpatial,
  translateSpatialCount,
  type SpatialCatalogKey,
  type SpatialLocalizedError,
  type SpatialLocale,
} from './localization'

export {
  SPATIAL_PERFORMANCE_BUDGETS,
  createSpatialPerformanceReport,
  evaluateSpatialPerformanceReport,
  resolveSpatialPerformanceFallback,
  supportsLargeSemanticDataset,
  type SpatialPerformanceBudget,
  type SpatialPerformanceCheck,
  type SpatialPerformanceEvaluation,
  type SpatialPerformanceInput,
} from './performance'

export {
  SpatialPrivacyLifecycleService,
  assertPresentationGarbageCollectionSafe,
  canGarbageCollectPresentation,
  classifySpatialValue,
  redactSpatialTranscript,
  type SpatialAttachmentLifecycle,
  type SpatialPrivacyRegistration,
  type SpatialWorkspaceExport,
} from './privacy'

export {
  SPATIAL_OBSERVABILITY_METRIC_NAMES,
  BoundedSpatialTelemetry,
  SpatialTelemetryViolation,
  type SpatialObservabilityMetricName,
  type SpatialTelemetryInput,
} from './observability'

export {
  SPATIAL_ROLLOUT_ORDER,
  SpatialRolloutController,
  evaluateSpatialRolloutGate,
  type SpatialRolloutDecision,
  type SpatialRolloutGateInput,
} from './rollout'
