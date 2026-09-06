import { describe, expect, it } from 'vitest'

import {
  SPATIAL_SCHEMA_VERSIONS,
  parseSpatialAuthorizationDecision,
  parseSpatialAuditRecord,
  parseSpatialObservabilityMetric,
  parseSpatialPerformanceReport,
  parseSpatialPrivacyRecord,
  parseSpatialReliabilityIncident,
  parseSpatialRolloutStage,
  spatialHardeningContractSchemas,
} from '@/spatial/contracts'
import {
  RELIABILITY_INVARIANTS,
  BoundedSpatialTelemetry,
  SpatialAuthorizationService,
  SpatialAuditService,
  SpatialReliabilityController,
  SpatialRolloutController,
  SpatialTelemetryViolation,
  SPATIAL_AUTHORIZATION_CAPABILITY_MATRIX,
  assertNoSensitivePayload,
  assertPresentationGarbageCollectionSafe,
  canGarbageCollectPresentation,
  createSpatialPerformanceReport,
  evaluateSpatialAccessibility,
  evaluateSpatialPerformanceReport,
  evaluateSpatialRolloutGate,
  formatSpatialQuantity,
  formatSpatialTimestamp,
  localizeSpatialError,
  redactSpatialTranscript,
  resolveSpatialPerformanceFallback,
  spatialLocaleLanguageTag,
  supportsLargeSemanticDataset,
  translateSpatial,
  translateSpatialCount,
  assertProtocolTermNotMachineTranslated,
  validateSpatialPrimaryFlow,
  SpatialPrivacyLifecycleService,
} from '@/spatial/hardening'

const now = '2026-09-06T13:00:00.000Z'

describe('M11 hardening contracts', () => {
  it('parses every additive hardening record without changing the M2 registry', () => {
    expect(Object.keys(spatialHardeningContractSchemas)).toEqual([
      'authorizationDecision', 'auditRecord', 'reliabilityIncident', 'privacyRecord', 'performanceReport', 'observabilityMetric', 'rolloutStage',
    ])
    expect(parseSpatialAuthorizationDecision({ schema_version: SPATIAL_SCHEMA_VERSIONS.authorizationDecision, decision_id: 'd', workspace_id: 'w', node_id: 'n', actor_ref: 'a', target_ref: 't', action_id: 'act', decision: 'ALLOW', reason_code: 'ok', target_revision: 1, current_revision: 1, created_at: now }).ok).toBe(true)
    expect(parseSpatialAuditRecord({ schema_version: SPATIAL_SCHEMA_VERSIONS.auditRecord, audit_id: 'a', workspace_id: 'w', node_id: 'n', actor_ref: 'actor', target_ref: 't', target_type: 'endpoint', action_id: 'act', decision: 'DENY', result: 'REJECTED', idempotency_key: 'idem', occurred_at: now }).ok).toBe(true)
    expect(parseSpatialReliabilityIncident({ schema_version: SPATIAL_SCHEMA_VERSIONS.reliabilityIncident, incident_id: 'i', workspace_id: 'w', node_id: 'n', fault: 'EVENT_DUPLICATE', state: 'OPEN', recovery_action: 'dedupe', opened_at: now, updated_at: now }).ok).toBe(true)
    expect(parseSpatialPrivacyRecord({ schema_version: SPATIAL_SCHEMA_VERSIONS.privacyRecord, record_id: 'p', workspace_id: 'w', node_id: 'n', subject_ref: 's', classification: 'OPERATOR', lifecycle: 'ACTIVE', updated_at: now }).ok).toBe(true)
    expect(parseSpatialPerformanceReport({ schema_version: SPATIAL_SCHEMA_VERSIONS.performanceReport, report_id: 'p', workspace_id: 'w', node_id: 'n', profile: 'MOBILE', initial_js_kb: 1, initial_css_kb: 1, webgl_chunk_kb: 1, time_to_interactive_ms: 1, first_spatial_frame_ms: 1, steady_fps: 60, frame_p95_ms: 1, memory_growth_mb: 1, idle_cpu_percent: 1, idle_gpu_percent: 1, event_burst_per_second: 1, semantic_object_count: 20_000, conversation_dom_nodes: 1, mount_cycles: 1, state: 'PASS', observed_at: now }).ok).toBe(true)
    expect(parseSpatialObservabilityMetric({ schema_version: SPATIAL_SCHEMA_VERSIONS.observabilityMetric, metric_id: 'm', workspace_id: 'w', node_id: 'n', name: 'renderer_init', value: 1, unit: 'count', bucket: '1', content_free: true, observed_at: now }).ok).toBe(true)
    expect(parseSpatialRolloutStage({ schema_version: SPATIAL_SCHEMA_VERSIONS.rolloutStage, rollout_id: 'r', workspace_id: 'w', node_id: 'n', flag: 'spatial_operator_preview_enabled', stage: 'DEVELOPER', enabled: false, compatibility_state: 'COMPATIBLE', error_budget_percent: 100, updated_at: now }).ok).toBe(true)
  })
})

describe('M11 authorization and audit', () => {
  it('does not let a presentation object grant authority and deduplicates audit writes', () => {
    expect(Object.keys(SPATIAL_AUTHORIZATION_CAPABILITY_MATRIX)).toEqual(expect.arrayContaining(['browserSession', 'primaryAgent', 'mcpTools', 'hooks', 'workspaceMutations', 'remoteMediation', 'recoveryActions', 'resourceActions', 'shareView']))
    const authorization = new SpatialAuthorizationService({ workspaceId: 'w', nodeId: 'n', idFactory: () => 'decision:fixed', now: () => now })
    const allowed = authorization.authorize({ workspaceId: 'w', nodeId: 'n', actorRef: 'operator:1', targetRef: 'endpoint:1', targetType: 'presentation', actionId: 'endpoint:update', requiredCapabilities: ['endpoint:write'], grantedCapabilities: ['endpoint:write'], targetRevision: 3, currentRevision: 3, now })
    expect(allowed.allowed).toBe(true)
    const denied = authorization.authorize({ workspaceId: 'w', nodeId: 'n', actorRef: 'operator:1', targetRef: 'endpoint:1', actionId: 'endpoint:update', requiredCapabilities: ['endpoint:write'], grantedCapabilities: [], targetRevision: 3, currentRevision: 3, now })
    expect(denied.decision.reason_code).toBe('MISSING_CAPABILITY')
    expect(authorization.authorize({ workspaceId: 'other', nodeId: 'n', actorRef: 'operator:1', targetRef: 'endpoint:1', actionId: 'endpoint:update', requiredCapabilities: [], grantedCapabilities: [], targetRevision: 3, currentRevision: 3, now }).decision.decision).toBe('DENY')
    expect(authorization.authorize({ workspaceId: 'w', nodeId: 'n', actorRef: 'operator:1', targetRef: 'endpoint:1', actionId: 'endpoint:update', requiredCapabilities: [], grantedCapabilities: [], targetRevision: 2, currentRevision: 3, now }).decision.decision).toBe('STALE')
    authorization.revoke('operator:1', ['endpoint:write'])
    expect(authorization.authorize({ workspaceId: 'w', nodeId: 'n', actorRef: 'operator:1', targetRef: 'endpoint:1', actionId: 'endpoint:update', requiredCapabilities: ['endpoint:write'], grantedCapabilities: ['endpoint:write'], targetRevision: 3, currentRevision: 3, now }).decision.reason_code).toBe('CAPABILITY_REVOKED')
    const audit = new SpatialAuditService({ idFactory: () => 'audit:fixed', now: () => now })
    const first = audit.recordDecision(allowed.decision, 'APPLIED', { idempotencyKey: 'idem:1', evidenceRefs: ['evidence:1'], resultingRevision: 4 })
    expect(audit.recordDecision(allowed.decision, 'FAILED', { idempotencyKey: 'idem:1' })).toEqual(first)
    expect(audit.list()).toHaveLength(1)
    expect(() => assertNoSensitivePayload({ prompt: 'do not persist' })).toThrow()
  })
})

describe('M11 reliability, accessibility and localization', () => {
  it('makes recovery visible and never reports green before all invariants pass', () => {
    const controller = new SpatialReliabilityController({ idFactory: () => 'incident:fixed', now: () => now })
    const incident = controller.open('RENDERER_CONTEXT_LOSS', { workspaceId: 'w', nodeId: 'n', now })
    expect(controller.requireClassicFallback(incident.incident_id)).toBe(true)
    const contained = controller.executeRecovery(incident.incident_id, 'rebuild-renderer-from-canonical')
    expect(contained.state).toBe('CONTAINED')
    const recovered = controller.recover(incident.incident_id, Object.fromEntries(RELIABILITY_INVARIANTS.map((name) => [name, 'PASS'])))
    expect(recovered.state).toBe('RECOVERED')
    expect(controller.isSafeForGreen(incident.incident_id)).toBe(true)
    expect(controller.executeRecovery(incident.incident_id, 'rebuild-renderer-from-canonical')).toEqual(recovered)
  })

  it('blocks missing accessibility semantics and preserves the primary keyboard flow', () => {
    expect(evaluateSpatialAccessibility([{ id: 'entity-list', role: 'list', accessibleName: 'Entities', keyboardOperable: true, focusable: true, focusReturnId: null, liveRegion: 'polite', liveUpdateHz: 2, minTouchTargetPx: 44, colorIndependent: true, highContrastSafe: true, reducedMotionSafe: true, reducedTransparencySafe: true, hasErrorInstructions: true }]).status).toBe('PASS')
    expect(evaluateSpatialAccessibility([{ id: 'bad', role: 'region' }]).status).toBe('BLOCKED')
    expect(validateSpatialPrimaryFlow(['open-workspace', 'inspect-agent'])).not.toEqual([])
    expect(translateSpatial('ru', 'states.ready')).toBe('Готово')
    expect(translateSpatialCount('ru', 22)).toBe('22 объекта')
    expect(formatSpatialQuantity('00042')).toBe('00042 Q')
    expect(formatSpatialTimestamp(now, 'ru', 'UTC')).toContain('2026')
    expect(spatialLocaleLanguageTag('ru')).toBe('ru-RU')
    expect(localizeSpatialError('ru', 'STALE_REVISION').code).toBe('STALE_REVISION')
    expect(assertProtocolTermNotMachineTranslated('Classic')).toBe('Classic')
    expect(() => assertProtocolTermNotMachineTranslated('Рабочее пространство')).toThrow()
  })
})

describe('M11 performance, privacy, observability and rollout', () => {
  it('evaluates device budgets and falls back to Classic for unsupported or failed profiles', () => {
    const report = createSpatialPerformanceReport({ workspace_id: 'w', node_id: 'n', profile: 'MOBILE', initial_js_kb: 100, initial_css_kb: 30, webgl_chunk_kb: 100, time_to_interactive_ms: 500, first_spatial_frame_ms: 400, steady_fps: 55, frame_p95_ms: 15, memory_growth_mb: 10, idle_cpu_percent: 2, idle_gpu_percent: 2, event_burst_per_second: 4, semantic_object_count: 20_000, conversation_dom_nodes: 100, mount_cycles: 2, state: 'PASS', budget_refs: ['mobile-v1'], observedAt: now }, () => 'perf:fixed')
    expect(evaluateSpatialPerformanceReport(report).fallback).toBe('SPATIAL')
    const failed = evaluateSpatialPerformanceReport({ ...report, initial_js_kb: 10_000, state: 'FAIL' })
    expect(failed.fallback).toBe('CLASSIC')
    expect(resolveSpatialPerformanceFallback('UNKNOWN')).toBe('CLASSIC')
    expect(supportsLargeSemanticDataset(20_000)).toBe(true)
  })

  it('exports references and revisions without private content and guards evidence GC', () => {
    const privacy = new SpatialPrivacyLifecycleService(() => 'privacy:fixed')
    privacy.register({ workspaceId: 'w', nodeId: 'n', subjectRef: 'conversation:1', classification: 'PRIVATE', evidenceRefs: ['evidence:1'], now })
    const exported = privacy.exportWorkspace('w', 'n', ['conversation:1'], { 'conversation:1': 4 }, ['evidence:1'], new Date(now))
    expect(exported).not.toHaveProperty('transcript')
    expect(exported.revisions['conversation:1']).toBe(4)
    expect(canGarbageCollectPresentation('presentation:1', ['evidence:1'])).toBe(true)
    expect(canGarbageCollectPresentation('evidence:1', ['evidence:1'])).toBe(false)
    expect(() => assertPresentationGarbageCollectionSafe('evidence:1', ['evidence:1'])).toThrow()
    expect(redactSpatialTranscript('Bearer token_secret123')).toContain('[REDACTED]')
  })

  it('keeps telemetry content-free and bounded, then runs a gated rollback', () => {
    const telemetry = new BoundedSpatialTelemetry({ idFactory: () => 'metric:fixed', maxCardinality: 1 })
    expect(telemetry.record({ workspaceId: 'w', nodeId: 'n', name: 'renderer_init', value: 1, unit: 'count', correlationId: 'trace:1' }).content_free).toBe(true)
    expect(() => telemetry.record({ workspaceId: 'w', nodeId: 'n', name: 'renderer_init', value: 1, unit: 'count', dimensions: { route: 'private transcript' } })).toThrow(SpatialTelemetryViolation)
    expect(evaluateSpatialRolloutGate('DEFAULT_ON', { errorBudgetPercent: 100, compatibility: 'COMPATIBLE', rollbackVerified: true, migrationReversible: true, generatedAssetsAtomic: true, securitySignedOff: false, reliabilitySignedOff: true, accessibilitySignedOff: true, performanceSignedOff: true }).fallback).toBe('CLASSIC')
    const rollout = new SpatialRolloutController({ workspaceId: 'w', nodeId: 'n', flag: 'spatial_operator_preview_enabled', idFactory: () => 'rollout:fixed' })
    expect(rollout.advance('TEST_NODE', { errorBudgetPercent: 100, compatibility: 'COMPATIBLE', rollbackVerified: true, migrationReversible: true, generatedAssetsAtomic: true, securitySignedOff: true, reliabilitySignedOff: true, accessibilitySignedOff: true, performanceSignedOff: true }).reason).toBe('STAGE_ORDER_VIOLATION')
    expect(rollout.advance('LOCAL_FIXTURE', { errorBudgetPercent: 100, compatibility: 'COMPATIBLE', rollbackVerified: true, migrationReversible: true, generatedAssetsAtomic: true, securitySignedOff: true, reliabilitySignedOff: true, accessibilitySignedOff: true, performanceSignedOff: true }).allowed).toBe(true)
    expect(rollout.rollback(['evidence:rollback']).fallback).toBe('CLASSIC')
    expect(rollout.presentation()).toBe('CLASSIC')
  })
})
