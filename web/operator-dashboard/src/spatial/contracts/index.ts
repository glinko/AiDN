import { z } from 'zod'

/**
 * Shared Spatial transport contracts (M2.1 foundation, extended by later
 * Node-owned boundaries such as the M3.1 Primary Agent Slot).
 *
 * These schemas are intentionally independent from the Spatial renderer. They
 * accept additive fields for forward compatibility, strip those fields before
 * a parsed value can reach a store, and expose only safe diagnostics.
 */

export const SPATIAL_SCHEMA_VERSIONS = {
  entity: 'spatial.entity.v1',
  relation: 'spatial.relation.v1',
  status: 'spatial.node-status.v1',
  workspace: 'spatial.workspace.v1',
  viewport: 'spatial.viewport.v1',
  primaryAgentSlot: 'spatial.primary-agent-slot.v1',
  primaryAgentGrant: 'spatial.primary-agent-grant.v1',
  primaryAgentState: 'spatial.primary-agent-state.v1',
  intentEnvelope: 'spatial.intent-envelope.v1',
  attachmentManifest: 'spatial.attachment-manifest.v1',
  workspaceSession: 'spatial.workspace-session.v1',
  contextNode: 'spatial.context-node.v1',
  conversationTurn: 'spatial.conversation-turn.v1',
  generatedObject: 'spatial.generated-object.v1',
  artifact: 'spatial.artifact.v1',
  presentationIntent: 'spatial.presentation-intent.v1',
  presentationResult: 'spatial.presentation-result.v1',
  canonicalReference: 'spatial.canonical-reference.v1',
  endpointDetails: 'spatial.endpoint-details.v1',
  discoveryResult: 'spatial.discovery-result.v1',
  semanticRelation: 'spatial.semantic-relation.v1',
  subagentLifecycle: 'spatial.subagent-lifecycle.v1',
  interactionProvenance: 'spatial.interaction-provenance.v1',
  attentionItem: 'spatial.attention-item.v1',
  attentionMarker: 'spatial.attention-marker.v1',
  attentionFocus: 'spatial.attention-focus.v1',
  recoveryCommand: 'spatial.recovery-command.v1',
  recoveryResult: 'spatial.recovery-result.v1',
  endpointProvenance: 'spatial.endpoint-provenance.v1',
  remoteContextManifest: 'spatial.remote-context-manifest.v1',
  remoteRequest: 'spatial.remote-request.v1',
  remoteResult: 'spatial.remote-result.v1',
  endpointTestFrame: 'spatial.endpoint-test-frame.v1',
  resourceAccounting: 'spatial.resource-accounting.v1',
  memoryLayout: 'spatial.memory-layout.v1',
  memoryProjection: 'spatial.memory-projection.v1',
  memoryCluster: 'spatial.memory-cluster.v1',
  memoryFocus: 'spatial.memory-focus.v1',
  memorySearch: 'spatial.memory-search.v1',
  memoryVirtualization: 'spatial.memory-virtualization.v1',
  workspaceWorld: 'spatial.workspace-world.v1',
  deviceViewport: 'spatial.device-viewport.v1',
  presentationGeometry: 'spatial.presentation-geometry.v1',
  workspaceMutation: 'spatial.workspace-mutation.v1',
  workspaceMutationResult: 'spatial.workspace-mutation-result.v1',
  offlineQueue: 'spatial.offline-queue.v1',
  shareView: 'spatial.share-view.v1',
  changeIntent: 'spatial.change-intent.v1',
  resultModel: 'spatial.result-model.v1',
  componentFrame: 'spatial.component-frame.v1',
  resourceSummary: 'spatial.resource-summary.v1',
  actionFeedback: 'spatial.action-feedback.v1',
  authorizationDecision: 'spatial.authorization-decision.v1',
  auditRecord: 'spatial.audit-record.v1',
  reliabilityIncident: 'spatial.reliability-incident.v1',
  privacyRecord: 'spatial.privacy-record.v1',
  performanceReport: 'spatial.performance-report.v1',
  observabilityMetric: 'spatial.observability-metric.v1',
  rolloutStage: 'spatial.rollout-stage.v1',
} as const

export type SpatialSchemaVersion = (typeof SPATIAL_SCHEMA_VERSIONS)[keyof typeof SPATIAL_SCHEMA_VERSIONS]

export const SPATIAL_FRESHNESS_STATES = ['FRESH', 'STALE', 'PARTIAL', 'UNKNOWN', 'UNAVAILABLE'] as const
export type SpatialFreshnessState = (typeof SPATIAL_FRESHNESS_STATES)[number]

export const SPATIAL_AVAILABILITY_STATES = ['AVAILABLE', 'DEGRADED', 'UNAVAILABLE', 'UNKNOWN'] as const
export type SpatialAvailabilityState = (typeof SPATIAL_AVAILABILITY_STATES)[number]

export const SPATIAL_NODE_STATUS_STATES = [
  'ONLINE',
  'READY',
  'RUNNING',
  'STARTING',
  'STOPPING',
  'RESTARTING',
  'DEGRADED',
  'OFFLINE',
  'DISCONNECTED',
  'BLOCKED',
  'UNKNOWN',
  'STALE',
] as const
export type SpatialNodeStatusState = (typeof SPATIAL_NODE_STATUS_STATES)[number]

export const SPATIAL_STATUS_COMPONENT_KINDS = [
  'node',
  'hypervisor',
  'primary-agent',
  'mcp',
  'hooks',
  'network',
  'consensus',
  'wallet',
  'sessions',
  'tasks',
  'endpoints',
  'providers',
  'runtimes',
  'resources',
  'renderer',
  'other',
] as const
export type SpatialStatusComponentKind = (typeof SPATIAL_STATUS_COMPONENT_KINDS)[number]

export const SPATIAL_RECOVERY_ACTIONS = [
  'RESTART_SERVICE',
  'STOP_UNSAFE_RUNTIME',
  'SUSPEND_AGENT_BINDING',
  'REVOKE_BINDING_CREDENTIALS',
  'DISABLE_HOOK',
  'RETRY_HOOK_DEAD_LETTER',
  'BLOCK_REMOTE_ENDPOINT',
  'RETURN_TO_CLASSIC',
] as const
export type SpatialRecoveryAction = (typeof SPATIAL_RECOVERY_ACTIONS)[number]

export const SPATIAL_RECOVERY_RESULT_STATES = ['PLANNED', 'APPLIED', 'NOOP', 'REJECTED', 'FAILED'] as const
export type SpatialRecoveryResultState = (typeof SPATIAL_RECOVERY_RESULT_STATES)[number]

export const SPATIAL_REMOTE_VALIDATION_STATES = ['UNVERIFIED', 'VALID', 'PARTIAL', 'SANITIZED', 'QUARANTINED', 'INVALID'] as const
export type SpatialRemoteValidationState = (typeof SPATIAL_REMOTE_VALIDATION_STATES)[number]
export const SPATIAL_REMOTE_RESULT_CLASSIFICATIONS = ['NONE', 'PROMPT_INJECTION', 'SCRIPT', 'UNSAFE_HTML', 'SECRET_PATTERN', 'MIME_MISMATCH', 'OVERSIZED'] as const
export type SpatialRemoteResultClassification = (typeof SPATIAL_REMOTE_RESULT_CLASSIFICATIONS)[number]
export const SPATIAL_REMOTE_REQUEST_STATES = ['READY', 'VALIDATING', 'SUBMITTING', 'STREAMING', 'COMPLETE', 'CANCELLED', 'TIMEOUT', 'UNAVAILABLE', 'REJECTED', 'INVALID_RESULT', 'INSUFFICIENT_DEPOSIT'] as const
export type SpatialRemoteRequestState = (typeof SPATIAL_REMOTE_REQUEST_STATES)[number]
export const SPATIAL_ENDPOINT_TEST_FRAME_STATES = ['READY', 'VALIDATING', 'SUBMITTING', 'STREAMING', 'COMPLETE', 'CANCELLED', 'TIMEOUT', 'UNAVAILABLE', 'INVALID_RESULT', 'INSUFFICIENT_DEPOSIT', 'REJECTED'] as const
export type SpatialEndpointTestFrameState = (typeof SPATIAL_ENDPOINT_TEST_FRAME_STATES)[number]
export const SPATIAL_RESOURCE_BILLING_POLICIES = ['FREE', 'METERED', 'UNKNOWN'] as const
export type SpatialResourceBillingPolicy = (typeof SPATIAL_RESOURCE_BILLING_POLICIES)[number]
export const SPATIAL_RESOURCE_ACCOUNTING_STATES = ['PENDING', 'SETTLED', 'FAILED', 'CANCELLED'] as const
export type SpatialResourceAccountingState = (typeof SPATIAL_RESOURCE_ACCOUNTING_STATES)[number]

export const SPATIAL_PRIMARY_AGENT_SLOT_LIFECYCLE_STATES = [
  'UNASSIGNED',
  'BINDING',
  'CONNECTED',
  'DEGRADED',
  'DISCONNECTED',
  'REVOKED',
] as const
export type SpatialPrimaryAgentSlotLifecycleState = (typeof SPATIAL_PRIMARY_AGENT_SLOT_LIFECYCLE_STATES)[number]

export const SPATIAL_PRIMARY_AGENT_CAPABILITY_CATEGORIES = ['read', 'write', 'action'] as const
export type SpatialPrimaryAgentCapabilityCategory = (typeof SPATIAL_PRIMARY_AGENT_CAPABILITY_CATEGORIES)[number]

export const SPATIAL_PRIMARY_AGENT_GRANT_STATES = ['ACTIVE', 'REVOKED', 'EXPIRED'] as const
export type SpatialPrimaryAgentGrantState = (typeof SPATIAL_PRIMARY_AGENT_GRANT_STATES)[number]

export const SPATIAL_PRIMARY_AGENT_OPERATIONAL_STATES = [
  'READY',
  'LISTENING',
  'THINKING',
  'ACTING',
  'WORKING',
  'ATTENTION',
  'CRITICAL',
  'OFFLINE',
] as const
export type SpatialPrimaryAgentOperationalState = (typeof SPATIAL_PRIMARY_AGENT_OPERATIONAL_STATES)[number]

export const SPATIAL_PRIMARY_AGENT_ATTENTION_SEVERITIES = ['NONE', 'INFO', 'WARNING', 'CRITICAL'] as const
export type SpatialPrimaryAgentAttentionSeverity = (typeof SPATIAL_PRIMARY_AGENT_ATTENTION_SEVERITIES)[number]

export const SPATIAL_INTENT_MODALITIES = ['text', 'voice', 'form', 'spatial'] as const
export type SpatialIntentModality = (typeof SPATIAL_INTENT_MODALITIES)[number]
export const SPATIAL_INTENT_KINDS = ['message', 'interaction', 'command', 'change', 'presentation'] as const
export type SpatialIntentKind = (typeof SPATIAL_INTENT_KINDS)[number]
export const SPATIAL_ATTACHMENT_KINDS = ['file', 'image', 'audio'] as const
export type SpatialAttachmentKind = (typeof SPATIAL_ATTACHMENT_KINDS)[number]
export const SPATIAL_SESSION_STATES = ['SEED', 'COMPOSING', 'SUBMITTING', 'ACTIVE', 'FAILED', 'CANCELLED', 'COLLAPSED', 'ARCHIVED'] as const
export type SpatialSessionState = (typeof SPATIAL_SESSION_STATES)[number]
export const SPATIAL_CONVERSATION_TURN_ROLES = ['operator', 'agent', 'system'] as const
export type SpatialConversationTurnRole = (typeof SPATIAL_CONVERSATION_TURN_ROLES)[number]
export const SPATIAL_CONVERSATION_TURN_STATES = ['QUEUED', 'STREAMING', 'COMPLETED', 'FAILED', 'CANCELLED'] as const
export type SpatialConversationTurnState = (typeof SPATIAL_CONVERSATION_TURN_STATES)[number]
export const SPATIAL_GENERATED_OBJECT_KINDS = ['TABLE', 'CHART', 'FILE', 'REPORT', 'OBJECT'] as const
export type SpatialGeneratedObjectKind = (typeof SPATIAL_GENERATED_OBJECT_KINDS)[number]
export const SPATIAL_GENERATED_OBJECT_STATES = ['ACTIVE', 'COLLAPSED', 'PINNED', 'ARCHIVED'] as const
export type SpatialGeneratedObjectState = (typeof SPATIAL_GENERATED_OBJECT_STATES)[number]
export const SPATIAL_PRESENTATION_STATUSES = ['ACCEPTED', 'REJECTED'] as const
export type SpatialPresentationStatus = (typeof SPATIAL_PRESENTATION_STATUSES)[number]

export const SPATIAL_REFERENCE_PROJECTION_KINDS = ['PRIMARY', 'CONTEXT', 'SUMMARY', 'FOCUS'] as const
export type SpatialReferenceProjectionKind = (typeof SPATIAL_REFERENCE_PROJECTION_KINDS)[number]
export const SPATIAL_REFERENCE_STATES = ['AVAILABLE', 'UNAVAILABLE', 'TOMBSTONE'] as const
export type SpatialReferenceState = (typeof SPATIAL_REFERENCE_STATES)[number]
export const SPATIAL_DISCOVERY_STATES = ['EMPTY', 'READY', 'STALE', 'DISMISSED'] as const
export type SpatialDiscoveryState = (typeof SPATIAL_DISCOVERY_STATES)[number]
export const SPATIAL_DISCOVERY_CANDIDATE_STATES = ['CANDIDATE', 'SELECTED', 'DISMISSED', 'STALE'] as const
export type SpatialDiscoveryCandidateState = (typeof SPATIAL_DISCOVERY_CANDIDATE_STATES)[number]
export const SPATIAL_ENDPOINT_SURFACE_STATES = ['READY', 'LOADING', 'PARTIAL', 'STALE', 'UNAVAILABLE', 'UNAUTHORIZED', 'INCOMPATIBLE'] as const
export type SpatialEndpointSurfaceState = (typeof SPATIAL_ENDPOINT_SURFACE_STATES)[number]
export const SPATIAL_SEMANTIC_RELATION_TYPES = ['REQUEST', 'RESPONSE', 'STREAMING', 'PRODUCED', 'DELEGATED', 'USES', 'SETTLEMENT', 'FAILURE'] as const
export type SpatialSemanticRelationType = (typeof SPATIAL_SEMANTIC_RELATION_TYPES)[number]
export const SPATIAL_SEMANTIC_RELATION_STATES = ['ACTIVE', 'IDLE', 'ARCHIVED', 'STALE', 'UNAVAILABLE'] as const
export type SpatialSemanticRelationState = (typeof SPATIAL_SEMANTIC_RELATION_STATES)[number]
export const SPATIAL_SUBAGENT_STATES = ['SPAWNED', 'WORKING', 'COMPLETED', 'FAILED', 'CANCELLED', 'ARCHIVED'] as const
export type SpatialSubagentState = (typeof SPATIAL_SUBAGENT_STATES)[number]
export const SPATIAL_INTERACTION_OUTCOMES = ['SUCCESS', 'FAILURE', 'CANCELLED', 'TIMEOUT'] as const
export type SpatialInteractionOutcome = (typeof SPATIAL_INTERACTION_OUTCOMES)[number]
export const SPATIAL_FAMILIARITY_STATES = ['NEVER_USED', 'USED', 'TRUSTED_BY_HISTORY'] as const
export type SpatialFamiliarityState = (typeof SPATIAL_FAMILIARITY_STATES)[number]
export const SPATIAL_ATTENTION_SEVERITIES = ['INFORMATION', 'COMPLETED', 'ATTENTION', 'ACTION_REQUIRED', 'CRITICAL'] as const
export type SpatialAttentionSeverity = (typeof SPATIAL_ATTENTION_SEVERITIES)[number]
export const SPATIAL_ATTENTION_STATES = ['UNREAD', 'SEEN', 'ACKNOWLEDGED', 'RESOLVED', 'ARCHIVED', 'DISMISSED', 'AGGREGATED'] as const
export type SpatialAttentionState = (typeof SPATIAL_ATTENTION_STATES)[number]
export const SPATIAL_ATTENTION_MARKER_STATES = ['ORBITING_UNREAD', 'AGGREGATED', 'SELECTED', 'FOCUSED', 'HIDDEN'] as const
export type SpatialAttentionMarkerState = (typeof SPATIAL_ATTENTION_MARKER_STATES)[number]
export const SPATIAL_ATTENTION_ORBIT_LANES = ['INNER', 'MIDDLE', 'OUTER'] as const
export type SpatialAttentionOrbitLane = (typeof SPATIAL_ATTENTION_ORBIT_LANES)[number]
export const SPATIAL_ATTENTION_ACTIONS = ['INSPECT', 'ACKNOWLEDGE', 'DISMISS', 'ARCHIVE', 'OPEN_SOURCE', 'PROPOSE_ACTION', 'SHOW_IN_WORKSPACE', 'RETURN_VIEWPORT'] as const
export type SpatialAttentionAction = (typeof SPATIAL_ATTENTION_ACTIONS)[number]
export const SPATIAL_ATTENTION_TYPES = ['AUTONOMOUS_EVENT', 'ENDPOINT_FAILURE', 'TASK_COMPLETE', 'APPROVAL', 'FRESHNESS', 'SECURITY'] as const
export type SpatialAttentionType = (typeof SPATIAL_ATTENTION_TYPES)[number]

export const SPATIAL_MEMORY_REGIONS = ['ACTIVE_WORK', 'AGENT_SPACE', 'RECENT_MEMORY', 'CLUSTER_MEMORY', 'ENDPOINT_ARC', 'DEEP_MEMORY'] as const
export type SpatialMemoryRegion = (typeof SPATIAL_MEMORY_REGIONS)[number]
export const SPATIAL_MEMORY_LEVELS = ['ACTIVE', 'RECENT', 'OLDER', 'CLUSTERED', 'PERIPHERAL', 'VIRTUALIZED'] as const
export type SpatialMemoryLevel = (typeof SPATIAL_MEMORY_LEVELS)[number]
export const SPATIAL_MEMORY_LOD_LEVELS = [0, 1, 2, 3] as const
export type SpatialMemoryLod = (typeof SPATIAL_MEMORY_LOD_LEVELS)[number]
export const SPATIAL_MEMORY_FOCUS_STATES = ['REQUESTED', 'MATERIALIZING', 'FOCUSED', 'RETURNING', 'PINNED', 'CANCELLED', 'UNAVAILABLE'] as const
export type SpatialMemoryFocusState = (typeof SPATIAL_MEMORY_FOCUS_STATES)[number]
export const SPATIAL_MEMORY_CLUSTER_CRITERIA = ['STRUCTURAL_PARENT', 'PROJECT', 'TOPIC', 'ENDPOINT', 'AGENT', 'SUBSYSTEM', 'SIMILARITY', 'MANUAL'] as const
export type SpatialMemoryClusterCriterion = (typeof SPATIAL_MEMORY_CLUSTER_CRITERIA)[number]

export const SPATIAL_DEVICE_PROFILES = ['DESKTOP', 'TABLET', 'MOBILE'] as const
export type SpatialDeviceProfile = (typeof SPATIAL_DEVICE_PROFILES)[number]
export const SPATIAL_WORKSPACE_MUTATION_OPERATIONS = ['MOVE_ANCHOR', 'PIN', 'UNPIN', 'CREATE_BRANCH', 'EDIT_CLUSTER', 'UPSERT_RELATION', 'REMOVE_ENTITY'] as const
export type SpatialWorkspaceMutationOperation = (typeof SPATIAL_WORKSPACE_MUTATION_OPERATIONS)[number]
export const SPATIAL_WORKSPACE_MUTATION_CONFLICT_CATEGORIES = ['NONE', 'STALE_REVISION', 'TOPOLOGY_CONFLICT', 'AUTHORIZATION', 'REMOVED_ENTITY', 'INVALID_TARGET', 'VIEWPORT_NOT_SHARED'] as const
export type SpatialWorkspaceMutationConflictCategory = (typeof SPATIAL_WORKSPACE_MUTATION_CONFLICT_CATEGORIES)[number]
export const SPATIAL_WORKSPACE_MUTATION_RESULT_STATES = ['APPLIED', 'REJECTED', 'CONFLICT', 'IDEMPOTENT'] as const
export type SpatialWorkspaceMutationResultState = (typeof SPATIAL_WORKSPACE_MUTATION_RESULT_STATES)[number]
export const SPATIAL_OFFLINE_CONNECTIVITY_STATES = ['ONLINE', 'OFFLINE', 'RECONNECTING'] as const
export type SpatialOfflineConnectivityState = (typeof SPATIAL_OFFLINE_CONNECTIVITY_STATES)[number]
export const SPATIAL_SHARE_VIEW_STATES = ['PENDING', 'ACCEPTED', 'DECLINED', 'LEFT', 'EXPIRED'] as const
export type SpatialShareViewState = (typeof SPATIAL_SHARE_VIEW_STATES)[number]

export const SPATIAL_CHANGE_INTENT_SOURCES = ['form', 'voice', 'spatial'] as const
export type SpatialChangeIntentSource = (typeof SPATIAL_CHANGE_INTENT_SOURCES)[number]
export const SPATIAL_CHANGE_INTENT_STATES = ['PROPOSED', 'VALID', 'NEEDS_CLARIFICATION', 'STALE', 'OCCUPIED', 'UNAUTHORIZED_FIELD', 'AGENT_OFFLINE', 'APPLIED', 'REJECTED'] as const
export type SpatialChangeIntentState = (typeof SPATIAL_CHANGE_INTENT_STATES)[number]
export const SPATIAL_CHANGE_FIELD_TYPES = ['string', 'integer', 'number', 'boolean', 'enum'] as const
export type SpatialChangeFieldType = (typeof SPATIAL_CHANGE_FIELD_TYPES)[number]
export const SPATIAL_ACTION_FEEDBACK_STATES = ['PROPOSED', 'NEEDS_CLARIFICATION', 'AWAITING_APPROVAL', 'EXECUTING', 'PARTIALLY_COMPLETED', 'COMPLETED', 'REJECTED', 'ROLLED_BACK', 'FINALITY_PENDING'] as const
export type SpatialActionFeedbackState = (typeof SPATIAL_ACTION_FEEDBACK_STATES)[number]
export const SPATIAL_RESOURCE_SUMMARY_STATES = ['FREE', 'UNKNOWN', 'ZERO', 'METERED'] as const
export type SpatialResourceSummaryState = (typeof SPATIAL_RESOURCE_SUMMARY_STATES)[number]
export const SPATIAL_AUTHORIZATION_DECISIONS = ['ALLOW', 'DENY', 'STALE', 'REDACTED'] as const
export type SpatialAuthorizationDecision = (typeof SPATIAL_AUTHORIZATION_DECISIONS)[number]
export const SPATIAL_AUDIT_RESULTS = ['ACCEPTED', 'REJECTED', 'APPLIED', 'FAILED', 'PARTIAL', 'ROLLED_BACK'] as const
export type SpatialAuditResult = (typeof SPATIAL_AUDIT_RESULTS)[number]
export const SPATIAL_RELIABILITY_FAULTS = ['EVENT_DISCONNECT', 'EVENT_REORDER', 'EVENT_DUPLICATE', 'API_PARTIAL_OUTAGE', 'AGENT_FAILURE', 'AGENT_REPLACED', 'HOOK_DEAD_LETTER', 'WORKSPACE_CONFLICT', 'CORRUPT_PRESENTATION', 'STALE_STATUS', 'ENDPOINT_TIMEOUT', 'MALICIOUS_REMOTE_OUTPUT', 'BROWSER_SLEEP', 'NODE_SWITCH', 'RENDERER_CONTEXT_LOSS'] as const
export type SpatialReliabilityFault = (typeof SPATIAL_RELIABILITY_FAULTS)[number]
export const SPATIAL_RELIABILITY_STATES = ['OPEN', 'CONTAINED', 'RECOVERED', 'ESCALATED'] as const
export type SpatialReliabilityState = (typeof SPATIAL_RELIABILITY_STATES)[number]
export const SPATIAL_PRIVACY_CLASSIFICATIONS = ['PUBLIC', 'OPERATOR', 'PRIVATE', 'SECRET'] as const
export type SpatialPrivacyClassification = (typeof SPATIAL_PRIVACY_CLASSIFICATIONS)[number]
export const SPATIAL_PRIVACY_LIFECYCLE_STATES = ['ACTIVE', 'ARCHIVED', 'DELETED', 'REDACTED'] as const
export type SpatialPrivacyLifecycleState = (typeof SPATIAL_PRIVACY_LIFECYCLE_STATES)[number]
export const SPATIAL_PERFORMANCE_PROFILES = ['LOW', 'MOBILE', 'DESKTOP', 'HIGH'] as const
export type SpatialPerformanceProfile = (typeof SPATIAL_PERFORMANCE_PROFILES)[number]
export const SPATIAL_PERFORMANCE_REPORT_STATES = ['PASS', 'ATTENTION', 'FAIL'] as const
export type SpatialPerformanceReportState = (typeof SPATIAL_PERFORMANCE_REPORT_STATES)[number]
export const SPATIAL_ROLLOUT_STAGES = ['DEVELOPER', 'LOCAL_FIXTURE', 'TEST_NODE', 'LAN_NODES', 'OPT_IN_PREVIEW', 'DEFAULT_ON', 'ROLLED_BACK'] as const
export type SpatialRolloutStage = (typeof SPATIAL_ROLLOUT_STAGES)[number]

export const SPATIAL_ENTITY_KINDS = ['agent', 'endpoint', 'service', 'session', 'artifact', 'attention'] as const
export type SpatialEntityKind = (typeof SPATIAL_ENTITY_KINDS)[number]

const MAX_ID_LENGTH = 256
const MAX_LABEL_LENGTH = 240
const MAX_STATE_LENGTH = 96
const MAX_SOURCE_LENGTH = 128
const MAX_STALE_AFTER_SECONDS = 31_536_000

function normalizeString(value: unknown): unknown {
  return typeof value === 'string' ? value.trim() : value
}

function normalizeCode(value: unknown): unknown {
  return typeof value === 'string' ? value.trim().toUpperCase() : value
}

function normalizeLowerCode(value: unknown): unknown {
  return typeof value === 'string' ? value.trim().toLowerCase() : value
}

function normalizeNumber(value: unknown): unknown {
  if (typeof value === 'number') return value
  if (typeof value === 'string' && /^\d+(?:\.\d+)?$/.test(value.trim())) return Number(value)
  return value
}

/** Convert a wire timestamp to a stable UTC ISO representation. */
export function normalizeSpatialTimestamp(value: unknown): string | null {
  if (value instanceof Date) {
    const time = value.getTime()
    return Number.isFinite(time) ? value.toISOString() : null
  }
  if (typeof value !== 'string' || value.trim() === '') return null
  const time = Date.parse(value)
  return Number.isFinite(time) ? new Date(time).toISOString() : null
}

const idSchema = z.preprocess(normalizeString, z.string().min(1).max(MAX_ID_LENGTH))
const labelSchema = z.preprocess(normalizeString, z.string().min(1).max(MAX_LABEL_LENGTH))
const stateSchema = z.preprocess(normalizeCode, z.string().min(1).max(MAX_STATE_LENGTH))
const sourceSchema = z.preprocess(normalizeString, z.string().min(1).max(MAX_SOURCE_LENGTH))
const revisionSchema = z.preprocess(normalizeNumber, z.number().int().nonnegative())
const timestampSchema = z.preprocess(
  (value) => normalizeSpatialTimestamp(value) ?? value,
  z.string().min(1).refine((value) => Number.isFinite(Date.parse(value)), 'timestamp must be parseable'),
)

export const spatialIdSchema = idSchema
export const spatialRevisionSchema = revisionSchema
export const spatialTimestampSchema = timestampSchema

const freshnessStateSchema = z.preprocess(normalizeCode, z.enum(SPATIAL_FRESHNESS_STATES))
const availabilityStateSchema = z.preprocess(normalizeCode, z.enum(SPATIAL_AVAILABILITY_STATES))
const nodeStatusStateSchema = z.preprocess(normalizeCode, z.enum(SPATIAL_NODE_STATUS_STATES))

/** The normalized, transport-safe freshness record. Age is derived separately. */
export const spatialFreshnessSchema = z.object({
  state: freshnessStateSchema,
  observed_at: timestampSchema,
  stale_after_seconds: z.preprocess(normalizeNumber, z.number().int().nonnegative().max(MAX_STALE_AFTER_SECONDS)),
  source: sourceSchema,
}).strip()

export type SpatialFreshnessWire = z.infer<typeof spatialFreshnessSchema>
export type SpatialFreshness = SpatialFreshnessWire & { age_seconds: number }

/**
 * Apply the one freshness policy at the contract boundary. A FRESH record that
 * has crossed its TTL becomes STALE; explicit UNKNOWN/PARTIAL/UNAVAILABLE
 * states are never upgraded by the client.
 */
export function normalizeSpatialFreshness(input: unknown, now: Date = new Date()): SpatialFreshness {
  const parsed = spatialFreshnessSchema.parse(input)
  const nowMs = now.getTime()
  if (!Number.isFinite(nowMs)) throw new RangeError('now must be a valid Date')
  const observedMs = Date.parse(parsed.observed_at)
  const ageSeconds = Math.max(0, (nowMs - observedMs) / 1000)
  const state: SpatialFreshnessState = parsed.state === 'FRESH' && ageSeconds > parsed.stale_after_seconds
    ? 'STALE'
    : parsed.state
  return {
    ...parsed,
    state,
    age_seconds: Number(ageSeconds.toFixed(3)),
  }
}

const provenanceSchema = z.object({
  canonical_ref: idSchema,
  revision: revisionSchema,
  source: sourceSchema,
}).strip()

const entityBase = {
  schema_version: z.literal(SPATIAL_SCHEMA_VERSIONS.entity),
  id: idSchema,
  canonical_ref: idSchema,
  node_id: idSchema,
  revision: revisionSchema,
  label: labelSchema,
  state: stateSchema,
  availability: availabilityStateSchema,
  freshness: spatialFreshnessSchema,
  created_at: timestampSchema,
  updated_at: timestampSchema,
  provenance: provenanceSchema.optional(),
} satisfies z.ZodRawShape

const agentEntitySchema = z.object({
  ...entityBase,
  kind: z.literal('agent'),
  role: z.preprocess(normalizeCode, z.enum(['PRIMARY', 'SUBAGENT', 'AGENT'])).default('AGENT'),
  binding_ref: idSchema.optional(),
  capability_refs: z.array(idSchema).max(128).default([]),
}).strip()

const endpointEntitySchema = z.object({
  ...entityBase,
  kind: z.literal('endpoint'),
  endpoint_type: labelSchema,
  capability_refs: z.array(idSchema).max(128).default([]),
  provider_ref: idSchema.optional(),
  owner_agent_ref: idSchema.optional(),
}).strip()

const serviceEntitySchema = z.object({
  ...entityBase,
  kind: z.literal('service'),
  service_type: labelSchema,
  component_ref: idSchema.optional(),
}).strip()

const sessionEntitySchema = z.object({
  ...entityBase,
  kind: z.literal('session'),
  session_type: z.preprocess(normalizeCode, z.enum(['WORKSPACE', 'PROTOCOL', 'SESSION'])).default('SESSION'),
  protocol_session_ref: idSchema.optional(),
  actor_refs: z.array(idSchema).max(128).default([]),
}).strip()

const artifactEntitySchema = z.object({
  ...entityBase,
  kind: z.literal('artifact'),
  artifact_type: labelSchema,
  provenance_ref: idSchema,
  source_revision: revisionSchema,
}).strip()

const attentionEntitySchema = z.object({
  ...entityBase,
  kind: z.literal('attention'),
  severity: z.preprocess(normalizeCode, z.enum(['INFO', 'NOTICE', 'WARNING', 'CRITICAL'])),
  requires_operator: z.boolean(),
  expires_at: timestampSchema.optional(),
}).strip()

function normalizeEntityAliases(value: unknown): unknown {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return value
  const record = value as Record<string, unknown>
  const id = record.id ?? record.entity_id ?? record.object_id
  const canonicalRef = record.canonical_ref ?? record.entity_ref ?? record.object_ref
  return {
    ...record,
    ...(id !== undefined ? { id } : {}),
    ...(canonicalRef !== undefined ? { canonical_ref: canonicalRef } : {}),
  }
}

/** Discriminated canonical entity summary used by later view-model slices. */
export const spatialEntitySchema = z.preprocess(
  normalizeEntityAliases,
  z.discriminatedUnion('kind', [
    agentEntitySchema,
    endpointEntitySchema,
    serviceEntitySchema,
    sessionEntitySchema,
    artifactEntitySchema,
    attentionEntitySchema,
  ]),
)

export type SpatialAgentEntity = z.infer<typeof agentEntitySchema>
export type SpatialEndpointEntity = z.infer<typeof endpointEntitySchema>
export type SpatialServiceEntity = z.infer<typeof serviceEntitySchema>
export type SpatialSessionEntity = z.infer<typeof sessionEntitySchema>
export type SpatialArtifactEntity = z.infer<typeof artifactEntitySchema>
export type SpatialAttentionEntity = z.infer<typeof attentionEntitySchema>
export type SpatialCanonicalEntity = z.infer<typeof spatialEntitySchema>

const statusEvidenceRefSchema = z.object({
  ref: idSchema,
  kind: z.preprocess(normalizeLowerCode, z.string().min(1).max(64)).optional(),
  label: labelSchema.optional(),
  observed_at: timestampSchema.optional(),
  authorized: z.boolean().default(true),
  redacted: z.boolean().default(false),
}).strip()

export type SpatialStatusEvidenceRef = z.infer<typeof statusEvidenceRefSchema>

const statusDetailsSchema = z.object({
  identity: z.string().max(240).optional(),
  runtime: z.string().max(240).optional(),
  connection: z.string().max(240).optional(),
  last_events: z.array(z.object({
    id: idSchema,
    occurred_at: timestampSchema,
    state: stateSchema,
    message: z.string().max(240).optional(),
  }).strip()).max(20).default([]),
  safe_raw_evidence: z.array(z.string().max(512)).max(20).default([]),
  authorization: z.enum(['AUTHORIZED', 'REDACTED', 'UNAVAILABLE']).default('AUTHORIZED'),
}).strip()

export type SpatialStatusDetails = z.infer<typeof statusDetailsSchema>

const statusComponentSchema = z.object({
  component_id: idSchema,
  component_type: labelSchema,
  kind: z.preprocess(normalizeLowerCode, z.enum(SPATIAL_STATUS_COMPONENT_KINDS)).default('other'),
  state: nodeStatusStateSchema,
  observed_at: timestampSchema,
  freshness: spatialFreshnessSchema,
  source: sourceSchema,
  revision: revisionSchema.optional(),
  stale_after: timestampSchema.optional(),
  evidence_refs: z.array(statusEvidenceRefSchema).max(32).default([]),
  issue_code: z.preprocess(normalizeCode, z.string().min(1).max(96)).nullable().optional(),
  available_actions: z.array(z.preprocess(normalizeCode, z.enum(SPATIAL_RECOVERY_ACTIONS))).max(16).default([]),
  spatial_ref: idSchema.nullable().optional(),
  authorization: z.enum(['AUTHORIZED', 'REDACTED', 'UNAVAILABLE']).default('AUTHORIZED'),
  detail_ref: idSchema.nullable().optional(),
  details: statusDetailsSchema.optional(),
}).strip()

/** Authoritative Node status snapshot; no agent-owned booleans are accepted. */
export const spatialNodeStatusSchema = z.object({
  schema_version: z.literal(SPATIAL_SCHEMA_VERSIONS.status),
  node_id: idSchema,
  revision: revisionSchema,
  state: nodeStatusStateSchema,
  observed_at: timestampSchema,
  freshness: spatialFreshnessSchema,
  components: z.array(statusComponentSchema).max(256),
  generated_at: timestampSchema.optional(),
  node_revision: revisionSchema.optional(),
  overall_state: nodeStatusStateSchema.optional(),
  partial: z.boolean().default(false),
  cached: z.boolean().default(false),
  last_known_at: timestampSchema.nullable().optional(),
  active_sessions: z.number().int().nonnegative().default(0),
  running_tasks: z.number().int().nonnegative().default(0),
  active_endpoints: z.number().int().nonnegative().default(0),
  warning_count: z.number().int().nonnegative().default(0),
  evidence_refs: z.array(statusEvidenceRefSchema).max(64).default([]),
  provenance: provenanceSchema.optional(),
}).strip()

export const spatialStatusSchema = spatialNodeStatusSchema
export type SpatialStatusComponent = z.infer<typeof statusComponentSchema>
export type SpatialNodeStatus = z.infer<typeof spatialNodeStatusSchema>

const recoveryActionSchema = z.preprocess(normalizeCode, z.enum(SPATIAL_RECOVERY_ACTIONS))

export const spatialRecoveryCommandSchema = z.object({
  schema_version: z.literal(SPATIAL_SCHEMA_VERSIONS.recoveryCommand),
  command_id: idSchema,
  node_id: idSchema,
  target_ref: idSchema,
  action: recoveryActionSchema,
  requested_revision: revisionSchema,
  plan_hash: idSchema,
  actor_ref: idSchema,
  capability: idSchema,
  consequence: labelSchema,
  requires_confirmation: z.boolean(),
  confirmation: z.literal(true).optional(),
  created_at: timestampSchema,
  idempotency_key: idSchema,
}).strip()

export type SpatialRecoveryCommand = z.infer<typeof spatialRecoveryCommandSchema>

export const spatialRecoveryResultSchema = z.object({
  schema_version: z.literal(SPATIAL_SCHEMA_VERSIONS.recoveryResult),
  command_id: idSchema,
  node_id: idSchema,
  target_ref: idSchema,
  action: recoveryActionSchema,
  state: z.preprocess(normalizeCode, z.enum(SPATIAL_RECOVERY_RESULT_STATES)),
  plan_hash: idSchema,
  revision: revisionSchema,
  observed_at: timestampSchema,
  audit_ref: idSchema,
  error_code: idSchema.nullable().optional(),
  message: labelSchema.optional(),
}).strip()

export type SpatialRecoveryResult = z.infer<typeof spatialRecoveryResultSchema>

export const spatialRelationSchema = z.object({
  schema_version: z.literal(SPATIAL_SCHEMA_VERSIONS.relation),
  relation_id: idSchema,
  node_id: idSchema,
  revision: revisionSchema,
  relation_type: stateSchema,
  source_ref: idSchema,
  target_ref: idSchema,
  state: z.preprocess(normalizeCode, z.enum(['ACTIVE', 'ARCHIVED', 'UNKNOWN', 'STALE', 'UNAVAILABLE'])),
  freshness: spatialFreshnessSchema,
  created_at: timestampSchema,
  updated_at: timestampSchema,
}).strip()

export type SpatialRelationContract = z.infer<typeof spatialRelationSchema>

const spatialPositionSchema = z.object({
  x: z.number().finite(),
  y: z.number().finite(),
  z: z.number().finite(),
}).strip()

const semanticAnchorSchema = z.object({
  canonical_ref: idSchema,
  position: spatialPositionSchema,
  region: stateSchema,
  cluster_ref: idSchema.optional(),
}).strip()

/** Node-owned semantic Workspace snapshot; presentation state is separate. */
export const spatialWorkspaceSchema = z.object({
  schema_version: z.literal(SPATIAL_SCHEMA_VERSIONS.workspace),
  workspace_id: idSchema,
  node_id: idSchema,
  revision: revisionSchema,
  semantic_revision: revisionSchema,
  created_at: timestampSchema,
  updated_at: timestampSchema,
  entities: z.array(spatialEntitySchema).max(10_000),
  relations: z.array(spatialRelationSchema).max(20_000),
  semantic_anchors: z.array(semanticAnchorSchema).max(10_000),
  cluster_membership: z.record(idSchema, idSchema).default({}),
  primary_agent_ref: idSchema.optional(),
}).strip()

export type SpatialSemanticAnchor = z.infer<typeof semanticAnchorSchema>
export type SpatialWorkspaceSnapshot = z.infer<typeof spatialWorkspaceSchema>

const cameraPositionSchema = z.object({
  x: z.number().finite(),
  y: z.number().finite(),
  zoom: z.number().finite().positive(),
  focus_id: idSchema.nullable(),
}).strip()

/** Device-local presentation state; it cannot mutate the semantic snapshot. */
export const spatialViewportSchema = z.object({
  schema_version: z.literal(SPATIAL_SCHEMA_VERSIONS.viewport),
  workspace_id: idSchema,
  node_id: idSchema,
  device_id: idSchema,
  presentation_revision: revisionSchema,
  camera: cameraPositionSchema,
  selection_ref: idSchema.nullable(),
  opened_frame_refs: z.array(idSchema).max(256),
  temporary_focus_ref: idSchema.nullable(),
  transient_discovery_refs: z.array(idSchema).max(256),
  quality_profile: z.preprocess(normalizeCode, z.enum(['LOW', 'MOBILE', 'DESKTOP', 'HIGH'])),
  updated_at: timestampSchema,
}).strip()

export type SpatialViewportSnapshot = z.infer<typeof spatialViewportSchema>

/** Node-owned role record; Agent identity/runtime/grants remain separate references. */
export const spatialPrimaryAgentSlotSchema = z.object({
  schema_version: z.literal(SPATIAL_SCHEMA_VERSIONS.primaryAgentSlot),
  slot_id: idSchema,
  node_id: idSchema,
  current_binding_id: idSchema.nullable(),
  lifecycle_state: z.preprocess(normalizeCode, z.enum(SPATIAL_PRIMARY_AGENT_SLOT_LIFECYCLE_STATES)),
  revision: revisionSchema,
  assigned_at: timestampSchema.nullable(),
  assigned_by: idSchema.nullable(),
  last_seen_at: timestampSchema.nullable(),
  capability_grant_ref: idSchema.nullable(),
  hook_subscription_ref: idSchema.nullable(),
  durable_inbox_ref: idSchema.nullable(),
  changed_at: timestampSchema.optional(),
  provenance: z.object({
    actor_ref: idSchema,
    operation_id: idSchema,
    recorded_at: timestampSchema,
  }).strip().optional(),
}).strip()

export type SpatialPrimaryAgentSlot = z.infer<typeof spatialPrimaryAgentSlotSchema>

/** Capability policy is a reference-only record; it never carries credentials. */
export const spatialPrimaryAgentGrantSchema = z.object({
  schema_version: z.literal(SPATIAL_SCHEMA_VERSIONS.primaryAgentGrant),
  grant_id: idSchema,
  node_id: idSchema,
  binding_id: idSchema,
  revision: revisionSchema,
  categories: z.array(z.preprocess((value) => typeof value === 'string' ? value.trim().toLowerCase() : value, z.enum(SPATIAL_PRIMARY_AGENT_CAPABILITY_CATEGORIES))).max(32),
  allowlisted_tools: z.array(idSchema).max(256),
  redaction_profile_ref: idSchema.nullable(),
  state: z.preprocess(normalizeCode, z.enum(SPATIAL_PRIMARY_AGENT_GRANT_STATES)),
  issued_at: timestampSchema,
  issued_by: idSchema,
  expires_at: timestampSchema.nullable(),
}).strip()

export type SpatialPrimaryAgentGrant = z.infer<typeof spatialPrimaryAgentGrantSchema>

/** Authoritative operational state projection consumed by the Presence layer. */
export const spatialPrimaryAgentStateSchema = z.object({
  schema_version: z.literal(SPATIAL_SCHEMA_VERSIONS.primaryAgentState),
  node_id: idSchema,
  slot_id: idSchema,
  binding_id: idSchema.nullable(),
  state: z.preprocess(normalizeCode, z.enum(SPATIAL_PRIMARY_AGENT_OPERATIONAL_STATES)),
  attention_severity: z.preprocess(normalizeCode, z.enum(SPATIAL_PRIMARY_AGENT_ATTENTION_SEVERITIES)),
  source: idSchema,
  revision: revisionSchema,
  observed_at: timestampSchema,
  last_successful_response_at: timestampSchema.nullable(),
  last_failed_response_at: timestampSchema.nullable(),
}).strip()

export type SpatialPrimaryAgentState = z.infer<typeof spatialPrimaryAgentStateSchema>

const intentTextSchema = z.preprocess(
  (value) => value === null || value === undefined ? value : normalizeString(value),
  z.string().max(32_000).nullable().optional().default(null),
)

const structuredOperationSchema = z.record(z.string().min(1).max(128), z.unknown()).nullable().optional().default(null)

/** Reference-only attachment metadata. Binary bytes never cross the intent boundary. */
export const spatialAttachmentManifestSchema = z.object({
  schema_version: z.literal(SPATIAL_SCHEMA_VERSIONS.attachmentManifest),
  attachment_id: idSchema,
  kind: z.preprocess(normalizeLowerCode, z.enum(SPATIAL_ATTACHMENT_KINDS)),
  ref: idSchema,
  mime_type: z.preprocess(normalizeString, z.string().max(160).nullable()).default(null),
  size_bytes: z.preprocess(normalizeNumber, z.number().int().nonnegative().max(1_073_741_824).nullable()).default(null),
  checksum: z.preprocess(normalizeString, z.string().max(256).nullable()).default(null),
}).strip()

export type SpatialAttachmentManifest = z.infer<typeof spatialAttachmentManifestSchema>

/**
 * Common envelope for text, voice, form, and spatial interactions. The
 * envelope carries references and structured facts; authorization is applied
 * by the gateway after parsing and is never inferred from the payload.
 */
export const spatialIntentEnvelopeSchema = z.object({
  schema_version: z.literal(SPATIAL_SCHEMA_VERSIONS.intentEnvelope),
  intent_id: idSchema,
  workspace_id: idSchema,
  node_id: idSchema,
  actor_ref: idSchema,
  modality: z.preprocess((value) => typeof value === 'string' ? value.trim().toLowerCase() : value, z.enum(SPATIAL_INTENT_MODALITIES)),
  intent_kind: z.preprocess(normalizeLowerCode, z.enum(SPATIAL_INTENT_KINDS)),
  text: intentTextSchema,
  operation: structuredOperationSchema,
  target_refs: z.array(idSchema).max(256).default([]),
  parent_ref: idSchema.nullable().default(null),
  context_refs: z.array(idSchema).max(256).default([]),
  attachments_manifest: z.array(spatialAttachmentManifestSchema).max(64).default([]),
  current_revision: revisionSchema,
  idempotency_key: idSchema,
  created_at: timestampSchema,
}).strip().refine(
  (value) => (value.text !== null && value.text.trim().length > 0) || value.operation !== null,
  { path: ['text'], message: 'intent must contain text or a structured operation' },
)

export type SpatialIntentEnvelope = z.infer<typeof spatialIntentEnvelopeSchema>

const sessionAnchorSchema = z.preprocess(normalizeString, z.string().min(1).max(MAX_ID_LENGTH))
const sessionTitleSchema = z.preprocess(normalizeString, z.string().min(1).max(MAX_LABEL_LENGTH))

export const spatialWorkspaceSessionSchema = z.object({
  schema_version: z.literal(SPATIAL_SCHEMA_VERSIONS.workspaceSession),
  session_id: idSchema,
  workspace_id: idSchema,
  node_id: idSchema,
  revision: revisionSchema,
  state: z.preprocess(normalizeCode, z.enum(SPATIAL_SESSION_STATES)),
  root_intent_id: idSchema,
  parent_session_id: idSchema.nullable().default(null),
  structural_parent_ref: idSchema.nullable().default(null),
  semantic_anchor: sessionAnchorSchema,
  title: sessionTitleSchema,
  summary: z.preprocess(normalizeString, z.string().max(2_000)).default(''),
  turn_refs: z.array(idSchema).max(10_000).default([]),
  object_refs: z.array(idSchema).max(10_000).default([]),
  context_root_ref: idSchema,
  artifact_ref: idSchema.nullable().default(null),
  created_at: timestampSchema,
  updated_at: timestampSchema,
}).strip()

export type SpatialWorkspaceSession = z.infer<typeof spatialWorkspaceSessionSchema>

export const spatialContextNodeSchema = z.object({
  schema_version: z.literal(SPATIAL_SCHEMA_VERSIONS.contextNode),
  context_node_id: idSchema,
  session_id: idSchema,
  workspace_id: idSchema,
  node_id: idSchema,
  revision: revisionSchema,
  kind: z.preprocess(normalizeCode, z.enum(['ROOT', 'BRANCH', 'TURN', 'ARTIFACT'])),
  parent_ref: idSchema.nullable().default(null),
  context_refs: z.array(idSchema).max(256).default([]),
  source_ref: idSchema.nullable().default(null),
  target_revisions: z.record(idSchema, revisionSchema).default({}),
  created_at: timestampSchema,
  updated_at: timestampSchema,
}).strip()

export type SpatialContextNode = z.infer<typeof spatialContextNodeSchema>

const conversationProvenanceSchema = z.object({
  intent_id: idSchema.nullable().default(null),
  correlation_id: idSchema.nullable().default(null),
  binding_id: idSchema.nullable().default(null),
  source_ref: idSchema.nullable().default(null),
}).strip()

export const spatialConversationTurnSchema = z.object({
  schema_version: z.literal(SPATIAL_SCHEMA_VERSIONS.conversationTurn),
  turn_id: idSchema,
  session_id: idSchema,
  workspace_id: idSchema,
  node_id: idSchema,
  revision: revisionSchema,
  sequence: revisionSchema,
  role: z.preprocess(normalizeLowerCode, z.enum(SPATIAL_CONVERSATION_TURN_ROLES)),
  state: z.preprocess(normalizeCode, z.enum(SPATIAL_CONVERSATION_TURN_STATES)),
  text: z.preprocess(normalizeString, z.string().max(32_000)).default(''),
  intent_id: idSchema.nullable().default(null),
  provenance: conversationProvenanceSchema,
  citation_refs: z.array(idSchema).max(256).default([]),
  attachment_refs: z.array(idSchema).max(256).default([]),
  created_at: timestampSchema,
  updated_at: timestampSchema,
}).strip()

export type SpatialConversationTurn = z.infer<typeof spatialConversationTurnSchema>

export const spatialGeneratedObjectSchema = z.object({
  schema_version: z.literal(SPATIAL_SCHEMA_VERSIONS.generatedObject),
  object_id: idSchema,
  session_id: idSchema,
  workspace_id: idSchema,
  node_id: idSchema,
  source_turn_id: idSchema,
  revision: revisionSchema,
  kind: z.preprocess(normalizeCode, z.enum(SPATIAL_GENERATED_OBJECT_KINDS)),
  state: z.preprocess(normalizeCode, z.enum(SPATIAL_GENERATED_OBJECT_STATES)),
  title: sessionTitleSchema,
  summary: z.preprocess(normalizeString, z.string().max(2_000)).default(''),
  source_ref: idSchema,
  semantic_anchor: sessionAnchorSchema,
  placement: z.object({
    region: z.preprocess(normalizeCode, z.enum(['WORKSPACE', 'FOCUS', 'ARTIFACT'])),
    focus_required: z.boolean().default(false),
  }).strip().default({ region: 'WORKSPACE', focus_required: false }),
  data: z.record(z.string().min(1).max(128), z.unknown()).default({}),
  created_at: timestampSchema,
  updated_at: timestampSchema,
}).strip()

export type SpatialGeneratedObject = z.infer<typeof spatialGeneratedObjectSchema>

export const spatialArtifactSchema = z.object({
  schema_version: z.literal(SPATIAL_SCHEMA_VERSIONS.artifact),
  artifact_id: idSchema,
  session_id: idSchema,
  workspace_id: idSchema,
  node_id: idSchema,
  revision: revisionSchema,
  title: sessionTitleSchema,
  summary: z.preprocess(normalizeString, z.string().max(2_000)).default(''),
  turn_count: revisionSchema,
  turn_refs: z.array(idSchema).max(10_000).default([]),
  object_refs: z.array(idSchema).max(10_000).default([]),
  context_root_ref: idSchema,
  state: z.preprocess(normalizeCode, z.enum(['ACTIVE', 'ARCHIVED'])),
  pinned: z.boolean().default(false),
  camera_snapshot: z.record(z.string().min(1).max(128), z.unknown()).nullable().default(null),
  created_at: timestampSchema,
  updated_at: timestampSchema,
}).strip()

export type SpatialArtifact = z.infer<typeof spatialArtifactSchema>

const presentationViewportSchema = z.object({
  width: z.number().int().positive().max(16_384),
  height: z.number().int().positive().max(16_384),
  density: z.preprocess(normalizeCode, z.enum(['COMPACT', 'COMFORTABLE', 'IMMERSIVE'])),
  device: z.preprocess(normalizeCode, z.enum(['MOBILE', 'TABLET', 'DESKTOP'])),
}).strip()

export const spatialPresentationIntentSchema = z.object({
  schema_version: z.literal(SPATIAL_SCHEMA_VERSIONS.presentationIntent),
  presentation_id: idSchema,
  workspace_id: idSchema,
  node_id: idSchema,
  session_id: idSchema.nullable().default(null),
  turn_id: idSchema.nullable().default(null),
  revision: revisionSchema,
  target_refs: z.array(idSchema).max(256).default([]),
  importance: z.number().finite().min(0).max(1).default(0.5),
  focus_ref: idSchema.nullable().default(null),
  viewport: presentationViewportSchema,
  requested_component_id: idSchema.nullable().default(null),
  requested_component_version: z.string().max(64).nullable().default(null),
  requested_presentation: z.record(z.string().min(1).max(128), z.unknown()).default({}),
  created_at: timestampSchema,
}).strip()

export type SpatialPresentationIntent = z.infer<typeof spatialPresentationIntentSchema>

export const spatialPresentationResultSchema = z.object({
  schema_version: z.literal(SPATIAL_SCHEMA_VERSIONS.presentationResult),
  presentation_id: idSchema,
  workspace_id: idSchema,
  node_id: idSchema,
  revision: revisionSchema,
  status: z.preprocess(normalizeCode, z.enum(SPATIAL_PRESENTATION_STATUSES)),
  component_id: idSchema.nullable().default(null),
  component_version: z.string().max(64).nullable().default(null),
  semantic_anchor: sessionAnchorSchema.nullable().default(null),
  lifetime: z.preprocess(normalizeCode, z.enum(['SESSION', 'TURN', 'WORKSPACE'])).default('TURN'),
  density: z.preprocess(normalizeCode, z.enum(['COMPACT', 'COMFORTABLE', 'IMMERSIVE'])).default('COMFORTABLE'),
  importance: z.number().finite().min(0).max(1).default(0.5),
  entity_refs: z.array(idSchema).max(256).default([]),
  allowed_actions: z.array(idSchema).max(64).default([]),
  reuse_key: idSchema.nullable().default(null),
  reason: z.string().max(256).nullable().default(null),
  created_at: timestampSchema,
}).strip()

export type SpatialPresentationResult = z.infer<typeof spatialPresentationResultSchema>

const changeIntentValueSchema = z.union([z.string().max(4_000), z.number().finite(), z.boolean(), z.null()])
const changeIntentRecordSchema = z.record(z.string().min(1).max(128), changeIntentValueSchema)
const changeIntentTargetSchema = z.object({
  type: z.preprocess(normalizeLowerCode, z.enum(['endpoint', 'bundle', 'provider', 'runtime', 'resource'])),
  id: idSchema,
  revision: revisionSchema,
}).strip()
const changeIntentProvenanceSchema = z.object({
  source_ref: idSchema.nullable().default(null),
  correlation_id: idSchema.nullable().default(null),
  captured_at: timestampSchema,
}).strip()

export const spatialChangeIntentSchema = z.object({
  schema_version: z.literal(SPATIAL_SCHEMA_VERSIONS.changeIntent),
  intent_id: idSchema,
  workspace_id: idSchema,
  node_id: idSchema,
  target: changeIntentTargetSchema,
  current: changeIntentRecordSchema.default({}),
  proposed: changeIntentRecordSchema.default({}),
  field_schema: z.array(z.object({
    path: z.string().min(1).max(128),
    type: z.preprocess(normalizeLowerCode, z.enum(SPATIAL_CHANGE_FIELD_TYPES)),
    editable: z.boolean().default(false),
    required: z.boolean().default(false),
    unit: idSchema.nullable().default(null),
    minimum: z.number().finite().nullable().default(null),
    maximum: z.number().finite().nullable().default(null),
    allowed_values: z.array(changeIntentValueSchema).max(128).default([]),
  }).strip()).max(256),
  diff: z.array(z.object({ path: z.string().min(1).max(128), from: changeIntentValueSchema, to: changeIntentValueSchema }).strip()).max(256),
  state: z.preprocess(normalizeCode, z.enum(SPATIAL_CHANGE_INTENT_STATES)).default('PROPOSED'),
  actor_ref: idSchema,
  idempotency_key: idSchema,
  current_revision: revisionSchema,
  source: z.preprocess(normalizeLowerCode, z.enum(SPATIAL_CHANGE_INTENT_SOURCES)),
  workspace_session_ref: idSchema.nullable().default(null),
  natural_language_summary: z.string().max(2_000).nullable().default(null),
  provenance: changeIntentProvenanceSchema,
  created_at: timestampSchema,
  updated_at: timestampSchema,
}).strip()

export type SpatialChangeIntent = z.infer<typeof spatialChangeIntentSchema>

export const spatialResultModelSchema = z.object({
  schema_version: z.literal(SPATIAL_SCHEMA_VERSIONS.resultModel),
  result_id: idSchema,
  workspace_id: idSchema,
  node_id: idSchema,
  target_ref: idSchema,
  source_revision: revisionSchema,
  state: z.preprocess(normalizeCode, z.enum(['READY', 'STALE', 'OFFLINE', 'ERROR', 'EMPTY'])),
  data: z.record(z.string().min(1).max(128), z.unknown()).default({}),
  provenance_ref: idSchema.nullable().default(null),
  created_at: timestampSchema,
}).strip()
export type SpatialResultModel = z.infer<typeof spatialResultModelSchema>

export const spatialComponentFrameSchema = z.object({
  schema_version: z.literal(SPATIAL_SCHEMA_VERSIONS.componentFrame),
  frame_id: idSchema,
  workspace_id: idSchema,
  node_id: idSchema,
  component_id: idSchema,
  component_version: z.string().max(64),
  variant: z.preprocess(normalizeLowerCode, z.enum(['compact', 'summary', 'detail', 'config'])).default('summary'),
  object_ref: idSchema,
  source_revision: revisionSchema,
  state: z.preprocess(normalizeCode, z.enum(['loading', 'empty', 'ready', 'stale', 'offline', 'error', 'disabled', 'approval-required'])),
  result_ref: idSchema.nullable().default(null),
  created_at: timestampSchema,
}).strip()
export type SpatialComponentFrame = z.infer<typeof spatialComponentFrameSchema>

const qAtomsSchema = z.string().regex(/^-?\d+$/, 'q_atoms must preserve an integer quantity')
export const spatialResourceSummarySchema = z.object({
  schema_version: z.literal(SPATIAL_SCHEMA_VERSIONS.resourceSummary),
  summary_id: idSchema,
  workspace_id: idSchema,
  node_id: idSchema,
  source_revision: revisionSchema,
  state: z.preprocess(normalizeCode, z.enum(SPATIAL_RESOURCE_SUMMARY_STATES)),
  balance_q_atoms: qAtomsSchema,
  usage_q_atoms: qAtomsSchema,
  contribution_q_atoms: qAtomsSchema,
  cost_q_atoms: qAtomsSchema,
  rate_card_revision: idSchema.nullable().default(null),
  evidence_refs: z.array(idSchema).max(256).default([]),
  observed_at: timestampSchema,
}).strip()
export type SpatialResourceSummary = z.infer<typeof spatialResourceSummarySchema>

export const spatialActionFeedbackSchema = z.object({
  schema_version: z.literal(SPATIAL_SCHEMA_VERSIONS.actionFeedback),
  feedback_id: idSchema,
  workspace_id: idSchema,
  node_id: idSchema,
  action_id: idSchema,
  state: z.preprocess(normalizeCode, z.enum(SPATIAL_ACTION_FEEDBACK_STATES)),
  summary: z.string().max(2_000),
  completed_refs: z.array(idSchema).max(256).default([]),
  remaining_refs: z.array(idSchema).max(256).default([]),
  evidence_refs: z.array(idSchema).max(256).default([]),
  safe_next_action: idSchema.nullable().default(null),
  needs_attention: z.boolean().default(false),
  updated_at: timestampSchema,
}).strip()
export type SpatialActionFeedback = z.infer<typeof spatialActionFeedbackSchema>

export const spatialAuthorizationDecisionSchema = z.object({
  schema_version: z.literal(SPATIAL_SCHEMA_VERSIONS.authorizationDecision),
  decision_id: idSchema,
  workspace_id: idSchema,
  node_id: idSchema,
  actor_ref: idSchema,
  target_ref: idSchema,
  action_id: idSchema,
  required_capabilities: z.array(idSchema).max(128).default([]),
  granted_capabilities: z.array(idSchema).max(128).default([]),
  decision: z.preprocess(normalizeCode, z.enum(SPATIAL_AUTHORIZATION_DECISIONS)),
  reason_code: idSchema,
  target_revision: revisionSchema,
  current_revision: revisionSchema,
  correlation_id: idSchema.nullable().default(null),
  created_at: timestampSchema,
}).strip()
export type SpatialAuthorizationDecisionRecord = z.infer<typeof spatialAuthorizationDecisionSchema>

export const spatialAuditRecordSchema = z.object({
  schema_version: z.literal(SPATIAL_SCHEMA_VERSIONS.auditRecord),
  audit_id: idSchema,
  workspace_id: idSchema,
  node_id: idSchema,
  actor_ref: idSchema,
  target_ref: idSchema,
  target_type: idSchema,
  action_id: idSchema,
  decision: z.preprocess(normalizeCode, z.enum(SPATIAL_AUTHORIZATION_DECISIONS)),
  result: z.preprocess(normalizeCode, z.enum(SPATIAL_AUDIT_RESULTS)),
  target_revision: revisionSchema.nullable().default(null),
  resulting_revision: revisionSchema.nullable().default(null),
  idempotency_key: idSchema,
  correlation_id: idSchema.nullable().default(null),
  redacted_fields: z.array(idSchema).max(256).default([]),
  evidence_refs: z.array(idSchema).max(256).default([]),
  occurred_at: timestampSchema,
}).strip()
export type SpatialAuditRecord = z.infer<typeof spatialAuditRecordSchema>

export const spatialReliabilityIncidentSchema = z.object({
  schema_version: z.literal(SPATIAL_SCHEMA_VERSIONS.reliabilityIncident),
  incident_id: idSchema,
  workspace_id: idSchema,
  node_id: idSchema,
  fault: z.preprocess(normalizeCode, z.enum(SPATIAL_RELIABILITY_FAULTS)),
  state: z.preprocess(normalizeCode, z.enum(SPATIAL_RELIABILITY_STATES)),
  recovery_action: idSchema,
  invariant_results: z.record(idSchema, z.enum(['PASS', 'FAIL', 'UNKNOWN'])).default({}),
  source_revision: revisionSchema.nullable().default(null),
  correlation_id: idSchema.nullable().default(null),
  opened_at: timestampSchema,
  updated_at: timestampSchema,
}).strip()
export type SpatialReliabilityIncident = z.infer<typeof spatialReliabilityIncidentSchema>

export const spatialPrivacyRecordSchema = z.object({
  schema_version: z.literal(SPATIAL_SCHEMA_VERSIONS.privacyRecord),
  record_id: idSchema,
  workspace_id: idSchema,
  node_id: idSchema,
  subject_ref: idSchema,
  classification: z.preprocess(normalizeCode, z.enum(SPATIAL_PRIVACY_CLASSIFICATIONS)),
  lifecycle: z.preprocess(normalizeCode, z.enum(SPATIAL_PRIVACY_LIFECYCLE_STATES)),
  disclosed_fields: z.array(idSchema).max(256).default([]),
  redacted_fields: z.array(idSchema).max(256).default([]),
  retention_until: timestampSchema.nullable().default(null),
  evidence_refs: z.array(idSchema).max(256).default([]),
  updated_at: timestampSchema,
}).strip()
export type SpatialPrivacyRecord = z.infer<typeof spatialPrivacyRecordSchema>

export const spatialPerformanceReportSchema = z.object({
  schema_version: z.literal(SPATIAL_SCHEMA_VERSIONS.performanceReport),
  report_id: idSchema,
  workspace_id: idSchema,
  node_id: idSchema,
  profile: z.preprocess(normalizeCode, z.enum(SPATIAL_PERFORMANCE_PROFILES)),
  initial_js_kb: z.number().finite().nonnegative(),
  initial_css_kb: z.number().finite().nonnegative(),
  webgl_chunk_kb: z.number().finite().nonnegative(),
  time_to_interactive_ms: z.number().finite().nonnegative(),
  first_spatial_frame_ms: z.number().finite().nonnegative(),
  steady_fps: z.number().finite().nonnegative(),
  frame_p95_ms: z.number().finite().nonnegative(),
  memory_growth_mb: z.number().finite().nonnegative(),
  idle_cpu_percent: z.number().finite().nonnegative().max(100),
  idle_gpu_percent: z.number().finite().nonnegative().max(100),
  event_burst_per_second: z.number().finite().nonnegative(),
  semantic_object_count: z.number().int().nonnegative(),
  conversation_dom_nodes: z.number().int().nonnegative(),
  mount_cycles: z.number().int().nonnegative(),
  state: z.preprocess(normalizeCode, z.enum(SPATIAL_PERFORMANCE_REPORT_STATES)),
  budget_refs: z.array(idSchema).max(64).default([]),
  observed_at: timestampSchema,
}).strip()
export type SpatialPerformanceReport = z.infer<typeof spatialPerformanceReportSchema>

export const spatialObservabilityMetricSchema = z.object({
  schema_version: z.literal(SPATIAL_SCHEMA_VERSIONS.observabilityMetric),
  metric_id: idSchema,
  workspace_id: idSchema,
  node_id: idSchema,
  name: idSchema,
  value: z.number().finite(),
  unit: idSchema,
  bucket: idSchema,
  correlation_id: idSchema.nullable().default(null),
  dimensions: z.record(idSchema, idSchema).refine((value) => Object.keys(value).length <= 16, 'dimensions must contain at most 16 keys').default({}),
  content_free: z.literal(true),
  observed_at: timestampSchema,
}).strip()
export type SpatialObservabilityMetric = z.infer<typeof spatialObservabilityMetricSchema>

export const spatialRolloutStageSchema = z.object({
  schema_version: z.literal(SPATIAL_SCHEMA_VERSIONS.rolloutStage),
  rollout_id: idSchema,
  workspace_id: idSchema,
  node_id: idSchema,
  flag: idSchema,
  stage: z.preprocess(normalizeCode, z.enum(SPATIAL_ROLLOUT_STAGES)),
  enabled: z.boolean(),
  rollback_stage: z.preprocess(normalizeCode, z.enum(SPATIAL_ROLLOUT_STAGES)).nullable().default(null),
  compatibility_state: z.preprocess(normalizeCode, z.enum(['COMPATIBLE', 'REBUILD_REQUIRED', 'BLOCKED'])),
  error_budget_percent: z.number().finite().nonnegative().max(100),
  evidence_refs: z.array(idSchema).max(128).default([]),
  updated_at: timestampSchema,
}).strip()
export type SpatialRolloutStageRecord = z.infer<typeof spatialRolloutStageSchema>

/**
 * M5 topology contracts intentionally separate canonical identity from every
 * presentation projection. A registry is scoped by workspace and node; the
 * same canonical_ref in another workspace is a different lookup key.
 */
export const spatialCanonicalReferenceSchema = z.object({
  schema_version: z.literal(SPATIAL_SCHEMA_VERSIONS.canonicalReference),
  workspace_id: idSchema,
  node_id: idSchema,
  canonical_ref: idSchema,
  entity_id: idSchema,
  entity_kind: z.preprocess(normalizeLowerCode, z.enum(SPATIAL_ENTITY_KINDS)),
  revision: revisionSchema,
  projection_kind: z.preprocess(normalizeCode, z.enum(SPATIAL_REFERENCE_PROJECTION_KINDS)).default('PRIMARY'),
  state: z.preprocess(normalizeCode, z.enum(SPATIAL_REFERENCE_STATES)).default('AVAILABLE'),
  first_seen_at: timestampSchema,
  last_seen_at: timestampSchema,
  provenance_ref: idSchema.nullable().default(null),
}).strip()

export type SpatialCanonicalReference = z.infer<typeof spatialCanonicalReferenceSchema>

const nullableNumber = (maximum = Number.MAX_SAFE_INTEGER) => z.preprocess(normalizeNumber, z.number().finite().nonnegative().max(maximum).nullable().default(null))

export const spatialEndpointDetailsSchema = z.object({
  schema_version: z.literal(SPATIAL_SCHEMA_VERSIONS.endpointDetails),
  workspace_id: idSchema,
  node_id: idSchema,
  canonical_ref: idSchema,
  endpoint_id: idSchema,
  revision: revisionSchema,
  display_name: labelSchema,
  capability: labelSchema,
  endpoint_type: labelSchema,
  supported_modalities: z.array(idSchema).max(64).default([]),
  availability: availabilityStateSchema,
  surface_state: z.preprocess(normalizeCode, z.enum(SPATIAL_ENDPOINT_SURFACE_STATES)).default('READY'),
  freshness: spatialFreshnessSchema,
  latency: z.object({
    p50_ms: nullableNumber(86_400_000),
    p95_ms: nullableNumber(86_400_000),
    measured_at: timestampSchema.nullable().default(null),
    window: z.string().max(128).nullable().default(null),
  }).strip().default({ p50_ms: null, p95_ms: null, measured_at: null, window: null }),
  load: nullableNumber(1),
  capacity: nullableNumber(),
  cost: z.object({
    currency: idSchema.nullable().default(null),
    unit_price: nullableNumber(),
    billing_dimension: idSchema.nullable().default(null),
    minimum_charge: nullableNumber(),
  }).strip().default({ currency: null, unit_price: null, billing_dimension: null, minimum_charge: null }),
  deposit: z.object({
    minimum: nullableNumber(),
    recommended: nullableNumber(),
    currency: idSchema.nullable().default(null),
    escrow: z.boolean().nullable().default(null),
  }).strip().default({ minimum: null, recommended: null, currency: null, escrow: null }),
  provider_ref: idSchema.nullable().default(null),
  remote_agent_ref: idSchema.nullable().default(null),
  validation_refs: z.array(idSchema).max(128).default([]),
  input_formats: z.array(idSchema).max(128).default([]),
  output_formats: z.array(idSchema).max(128).default([]),
  limits: z.object({
    context_tokens: nullableNumber(),
    payload_bytes: nullableNumber(),
    timeout_ms: nullableNumber(86_400_000),
    streaming: z.boolean().nullable().default(null),
  }).strip().default({ context_tokens: null, payload_bytes: null, timeout_ms: null, streaming: null }),
  privacy: z.string().max(256).nullable().default(null),
  trust_summary: z.string().max(256).nullable().default(null),
  description: z.string().max(2_000).nullable().default(null),
  allowed_actions: z.array(idSchema).max(64).default([]),
}).strip()

export type SpatialEndpointDetails = z.infer<typeof spatialEndpointDetailsSchema>

/**
 * M7 contracts describe the local mediation boundary. They intentionally do
 * not contain a URL, socket, credential or executable remote UI payload.
 */
const safeKeySchema = z.preprocess(normalizeString, z.string().min(1).max(96))
const safeValueSchema = z.union([z.string().max(512), z.number().finite(), z.boolean()])

export const spatialEndpointProvenanceSchema = z.object({
  schema_version: z.literal(SPATIAL_SCHEMA_VERSIONS.endpointProvenance),
  provenance_id: idSchema,
  workspace_id: idSchema,
  node_id: idSchema,
  endpoint_ref: idSchema,
  endpoint_revision: revisionSchema,
  capability: labelSchema,
  provider_ref: idSchema.nullable().default(null),
  remote_node_ref: idSchema.nullable().default(null),
  source_zone: z.literal('REMOTE_UNTRUSTED'),
  validation_state: z.preprocess(normalizeCode, z.enum(['UNVERIFIED', 'VERIFIED', 'STALE', 'REVOKED'])).default('UNVERIFIED'),
  request_id: idSchema.nullable().default(null),
  correlation_id: idSchema,
  observed_at: timestampSchema,
  untrusted: z.literal(true),
}).strip()

export type SpatialEndpointProvenance = z.infer<typeof spatialEndpointProvenanceSchema>

export const spatialRemoteContextManifestSchema = z.object({
  schema_version: z.literal(SPATIAL_SCHEMA_VERSIONS.remoteContextManifest),
  manifest_id: idSchema,
  request_id: idSchema,
  workspace_id: idSchema,
  node_id: idSchema,
  workspace_session_ref: idSchema,
  purpose: labelSchema,
  capability_ref: idSchema,
  allowed_fields: z.array(safeKeySchema).max(64),
  fields: z.record(safeKeySchema, safeValueSchema).default({}),
  attachment_refs: z.array(z.string().regex(/^sha256:[a-f0-9]{16,128}$/)).max(32).default([]),
  media_types: z.array(z.string().regex(/^[a-z0-9!#$&^_.+-]+\/[a-z0-9!#$&^_.+-]+$/i)).max(16).default([]),
  size_limit_bytes: z.number().int().positive().max(50_000_000),
  redactions: z.array(safeKeySchema).max(64).default([]),
  forbidden_fields: z.array(safeKeySchema).max(64).default([]),
  retention: z.preprocess(normalizeCode, z.enum(['EPHEMERAL', 'SESSION', 'PERSISTED'])).default('EPHEMERAL'),
  consent_required: z.boolean().default(false),
  consent_granted: z.boolean().default(false),
  policy_revision: revisionSchema,
  manifest_hash: z.string().regex(/^sha256:[a-f0-9]{16,128}$/),
  created_at: timestampSchema,
}).strip()

export type SpatialRemoteContextManifest = z.infer<typeof spatialRemoteContextManifestSchema>

export const spatialRemoteRequestSchema = z.object({
  schema_version: z.literal(SPATIAL_SCHEMA_VERSIONS.remoteRequest),
  request_id: idSchema,
  local_node_id: idSchema,
  local_primary_agent_ref: idSchema,
  local_session_ref: idSchema,
  endpoint_ref: idSchema,
  endpoint_revision: revisionSchema,
  capability: labelSchema,
  input_refs: z.array(idSchema).max(32).default([]),
  context_manifest: spatialRemoteContextManifestSchema,
  authorization: z.object({
    state: z.preprocess(normalizeCode, z.enum(['AUTHORIZED', 'REJECTED'])),
    grant_ref: idSchema.nullable().default(null),
    policy_revision: revisionSchema,
  }).strip(),
  resource_budget: z.object({
    policy: z.preprocess(normalizeCode, z.enum(SPATIAL_RESOURCE_BILLING_POLICIES)),
    estimate_units: nullableNumber(),
    max_units: nullableNumber(),
  }).strip(),
  transport: z.object({
    adapter_id: idSchema,
    timeout_ms: z.number().int().positive().max(86_400_000),
    request_bytes: z.number().int().nonnegative().max(50_000_000),
  }).strip(),
  state: z.preprocess(normalizeCode, z.enum(SPATIAL_REMOTE_REQUEST_STATES)).default('READY'),
  idempotency_key: idSchema,
  correlation_id: idSchema,
  created_at: timestampSchema,
  provenance: spatialEndpointProvenanceSchema,
}).strip()

export type SpatialRemoteRequest = z.infer<typeof spatialRemoteRequestSchema>

export const spatialRemoteResultSchema = z.object({
  schema_version: z.literal(SPATIAL_SCHEMA_VERSIONS.remoteResult),
  result_id: idSchema,
  request_id: idSchema,
  endpoint_ref: idSchema,
  endpoint_revision: revisionSchema,
  content_type: z.string().regex(/^[a-z0-9!#$&^_.+-]+\/[a-z0-9!#$&^_.+-]+$/i),
  validation: z.object({
    status: z.preprocess(normalizeCode, z.enum(SPATIAL_REMOTE_VALIDATION_STATES)),
    classification: z.preprocess(normalizeCode, z.enum(SPATIAL_REMOTE_RESULT_CLASSIFICATIONS)).default('NONE'),
    schema: idSchema.nullable().default(null),
    size_bytes: z.number().int().nonnegative().max(50_000_000),
  }).strip(),
  safe_text: z.string().max(1_000_000).nullable().default(null),
  payload_ref: idSchema.nullable().default(null),
  untrusted: z.literal(true),
  provenance: spatialEndpointProvenanceSchema,
  received_at: timestampSchema,
  correlation_id: idSchema,
}).strip()

export type SpatialRemoteResult = z.infer<typeof spatialRemoteResultSchema>

export const spatialEndpointTestFrameSchema = z.object({
  schema_version: z.literal(SPATIAL_SCHEMA_VERSIONS.endpointTestFrame),
  frame_id: idSchema,
  workspace_id: idSchema,
  node_id: idSchema,
  endpoint_ref: idSchema,
  capability: labelSchema,
  input_schema: z.object({
    fields: z.array(safeKeySchema).max(64),
    media_types: z.array(z.string().max(128)).max(16).default([]),
  }).strip(),
  input_value_ref: idSchema.nullable().default(null),
  submit_intent_ref: idSchema.nullable().default(null),
  response_ref: idSchema.nullable().default(null),
  accounting_ref: idSchema.nullable().default(null),
  state: z.preprocess(normalizeCode, z.enum(SPATIAL_ENDPOINT_TEST_FRAME_STATES)).default('READY'),
  source_revision: revisionSchema,
  provenance_ref: idSchema.nullable().default(null),
  created_at: timestampSchema,
  updated_at: timestampSchema,
}).strip()

export type SpatialEndpointTestFrame = z.infer<typeof spatialEndpointTestFrameSchema>

export const spatialResourceAccountingSchema = z.object({
  schema_version: z.literal(SPATIAL_SCHEMA_VERSIONS.resourceAccounting),
  record_id: idSchema,
  request_id: idSchema,
  node_id: idSchema,
  workspace_session_ref: idSchema,
  protocol_session_ref: idSchema.nullable().default(null),
  endpoint_ref: idSchema,
  rate_card_revision: revisionSchema,
  billing_policy: z.preprocess(normalizeCode, z.enum(SPATIAL_RESOURCE_BILLING_POLICIES)),
  input_units: z.number().finite().nonnegative().default(0),
  output_units: z.number().finite().nonnegative().default(0),
  estimate_units: z.number().finite().nonnegative().nullable().default(null),
  measured_units: z.number().finite().nonnegative().nullable().default(null),
  settlement_ref: idSchema.nullable().default(null),
  charge_policy: z.preprocess(normalizeCode, z.enum(['NO_CHARGE', 'CHARGE_ON_ACCEPTED_RESULT', 'CHARGE_ON_ATTEMPT', 'UNKNOWN'])).default('UNKNOWN'),
  state: z.preprocess(normalizeCode, z.enum(SPATIAL_RESOURCE_ACCOUNTING_STATES)).default('PENDING'),
  authoritative_source: z.literal('NODE'),
  created_at: timestampSchema,
  updated_at: timestampSchema,
}).strip()

export type SpatialResourceAccounting = z.infer<typeof spatialResourceAccountingSchema>

const discoveryCandidateSchema = z.object({
  candidate_id: idSchema,
  canonical_ref: idSchema,
  endpoint_ref: idSchema,
  endpoint_revision: revisionSchema,
  rank: z.number().int().positive(),
  relevance: z.number().finite().min(0).max(1),
  explanation: z.string().max(512),
  state: z.preprocess(normalizeCode, z.enum(SPATIAL_DISCOVERY_CANDIDATE_STATES)).default('CANDIDATE'),
  pinned: z.boolean().default(false),
  details: spatialEndpointDetailsSchema,
}).strip()

export type SpatialDiscoveryCandidate = z.infer<typeof discoveryCandidateSchema>

export const spatialDiscoveryResultSchema = z.object({
  schema_version: z.literal(SPATIAL_SCHEMA_VERSIONS.discoveryResult),
  discovery_id: idSchema,
  request_id: idSchema,
  workspace_id: idSchema,
  node_id: idSchema,
  revision: revisionSchema,
  state: z.preprocess(normalizeCode, z.enum(SPATIAL_DISCOVERY_STATES)),
  candidates: z.array(discoveryCandidateSchema).max(1_000),
  created_at: timestampSchema,
  updated_at: timestampSchema,
}).strip()

export type SpatialDiscoveryResult = z.infer<typeof spatialDiscoveryResultSchema>

export const spatialSemanticRelationSchema = z.object({
  schema_version: z.literal(SPATIAL_SCHEMA_VERSIONS.semanticRelation),
  relation_id: idSchema,
  workspace_id: idSchema,
  node_id: idSchema,
  revision: revisionSchema,
  relation_type: z.preprocess(normalizeCode, z.enum(SPATIAL_SEMANTIC_RELATION_TYPES)),
  source_ref: idSchema,
  target_ref: idSchema,
  source_revision: revisionSchema,
  target_revision: revisionSchema,
  state: z.preprocess(normalizeCode, z.enum(SPATIAL_SEMANTIC_RELATION_STATES)).default('ACTIVE'),
  label: labelSchema,
  pulse_count: z.number().int().nonnegative().default(0),
  offscreen_anchor: z.object({ x: z.number().finite(), y: z.number().finite(), z: z.number().finite() }).nullable().default(null),
  aggregation_key: idSchema.nullable().default(null),
  created_at: timestampSchema,
  updated_at: timestampSchema,
}).strip()

export type SpatialSemanticRelation = z.infer<typeof spatialSemanticRelationSchema>

export const spatialSubagentLifecycleSchema = z.object({
  schema_version: z.literal(SPATIAL_SCHEMA_VERSIONS.subagentLifecycle),
  subagent_ref: idSchema,
  workspace_id: idSchema,
  node_id: idSchema,
  primary_agent_ref: idSchema,
  parent_ref: idSchema.nullable().default(null),
  revision: revisionSchema,
  state: z.preprocess(normalizeCode, z.enum(SPATIAL_SUBAGENT_STATES)),
  capability_grant_scope: z.array(idSchema).max(128).default([]),
  delegation_relation_ref: idSchema.nullable().default(null),
  result_ref: idSchema.nullable().default(null),
  error_summary: z.string().max(512).nullable().default(null),
  created_at: timestampSchema,
  updated_at: timestampSchema,
}).strip()

export type SpatialSubagentLifecycle = z.infer<typeof spatialSubagentLifecycleSchema>

export const spatialInteractionProvenanceSchema = z.object({
  schema_version: z.literal(SPATIAL_SCHEMA_VERSIONS.interactionProvenance),
  record_id: idSchema,
  request_id: idSchema,
  endpoint_ref: idSchema,
  endpoint_revision: revisionSchema,
  result_ref: idSchema.nullable().default(null),
  outcome: z.preprocess(normalizeCode, z.enum(SPATIAL_INTERACTION_OUTCOMES)),
  latency_ms: nullableNumber(86_400_000),
  usage_ref: idSchema.nullable().default(null),
  idempotency_key: idSchema,
  node_id: idSchema,
  workspace_id: idSchema,
  primary_agent_ref: idSchema,
  revision: revisionSchema,
  observed_at: timestampSchema,
}).strip()

export type SpatialInteractionProvenance = z.infer<typeof spatialInteractionProvenanceSchema>

export const spatialAttentionItemSchema = z.object({
  schema_version: z.literal(SPATIAL_SCHEMA_VERSIONS.attentionItem),
  attention_id: idSchema,
  source_event_ref: idSchema,
  subject_ref: idSchema,
  node_id: idSchema,
  workspace_id: idSchema,
  target_agent_ref: idSchema,
  attention_type: z.preprocess(normalizeCode, z.enum(SPATIAL_ATTENTION_TYPES)).default('AUTONOMOUS_EVENT'),
  severity: z.preprocess(normalizeCode, z.enum(SPATIAL_ATTENTION_SEVERITIES)),
  state: z.preprocess(normalizeCode, z.enum(SPATIAL_ATTENTION_STATES)),
  summary: labelSchema,
  created_at: timestampSchema,
  acknowledged_at: timestampSchema.nullable().default(null),
  redaction_profile_ref: idSchema.nullable().default(null),
  grouping_key: idSchema,
  session_ref: idSchema.nullable().default(null),
  required_action: idSchema.nullable().default(null),
  provenance_ref: idSchema.nullable().default(null),
}).strip()

export type SpatialAttentionItem = z.infer<typeof spatialAttentionItemSchema>

export const spatialAttentionMarkerSchema = z.object({
  schema_version: z.literal(SPATIAL_SCHEMA_VERSIONS.attentionMarker),
  marker_id: idSchema,
  attention_ref: idSchema,
  workspace_id: idSchema,
  node_id: idSchema,
  orbit_lane: z.preprocess(normalizeCode, z.enum(SPATIAL_ATTENTION_ORBIT_LANES)),
  radius: z.number().finite().positive(),
  phase: z.number().finite(),
  angular_velocity: z.number().finite(),
  severity: z.preprocess(normalizeCode, z.enum(SPATIAL_ATTENTION_SEVERITIES)),
  attention_type: z.preprocess(normalizeCode, z.enum(SPATIAL_ATTENTION_TYPES)).default('AUTONOMOUS_EVENT'),
  unread: z.boolean(),
  presentation_state: z.preprocess(normalizeCode, z.enum(SPATIAL_ATTENTION_MARKER_STATES)),
  aggregation_count: z.number().int().positive().default(1),
  reduced_motion: z.boolean().default(false),
  updated_at: timestampSchema,
}).strip()

export type SpatialAttentionMarker = z.infer<typeof spatialAttentionMarkerSchema>

export const spatialAttentionFocusSchema = z.object({
  schema_version: z.literal(SPATIAL_SCHEMA_VERSIONS.attentionFocus),
  focus_id: idSchema,
  attention_id: idSchema,
  workspace_id: idSchema,
  node_id: idSchema,
  state: z.preprocess(normalizeCode, z.enum(['INSPECTING', 'FOCUSED', 'RETURNED', 'SOURCE_UNAVAILABLE'])),
  previous_viewport_ref: idSchema.nullable().default(null),
  source_available: z.boolean(),
  world_position_preserved: z.boolean().default(true),
  created_at: timestampSchema,
  updated_at: timestampSchema,
}).strip()

export type SpatialAttentionFocus = z.infer<typeof spatialAttentionFocusSchema>

const spatialMemorySemanticRefSchema = z.object({
  canonical_ref: idSchema,
  object_type: z.preprocess(normalizeLowerCode, z.string().min(1).max(64)),
  revision: revisionSchema,
}).strip()

const spatialMemoryAnchorSchema = z.object({
  anchor_ref: idSchema,
  region: z.preprocess(normalizeCode, z.enum(SPATIAL_MEMORY_REGIONS)),
  position: spatialPositionSchema,
  pinned: z.boolean().default(false),
}).strip()

export const spatialMemoryLayoutSchema = z.object({
  schema_version: z.literal(SPATIAL_SCHEMA_VERSIONS.memoryLayout),
  workspace_id: idSchema,
  policy_revision: idSchema,
  seed: idSchema,
  primary_agent_ref: idSchema.nullable(),
  anchors: z.array(spatialMemoryAnchorSchema).max(64),
  presentation_revision: revisionSchema,
  updated_at: timestampSchema,
}).strip()

export type SpatialMemorySemanticRef = z.infer<typeof spatialMemorySemanticRefSchema>
export type SpatialMemoryAnchor = z.infer<typeof spatialMemoryAnchorSchema>
export type SpatialMemoryLayout = z.infer<typeof spatialMemoryLayoutSchema>

export const spatialMemoryProjectionSchema = z.object({
  schema_version: z.literal(SPATIAL_SCHEMA_VERSIONS.memoryProjection),
  projection_id: idSchema,
  workspace_id: idSchema,
  semantic_ref: spatialMemorySemanticRefSchema,
  session_ref: idSchema.nullable(),
  zone: z.preprocess(normalizeCode, z.enum(SPATIAL_MEMORY_REGIONS)),
  memory_level: z.preprocess(normalizeCode, z.enum(SPATIAL_MEMORY_LEVELS)),
  age_class: z.preprocess(normalizeCode, z.enum(SPATIAL_MEMORY_LEVELS)),
  created_at: timestampSchema,
  last_active_at: timestampSchema,
  last_reused_at: timestampSchema.nullable(),
  relevance_score: z.number().min(0).max(1),
  pin_weight: z.number().min(0).max(1),
  cluster_ref: idSchema.nullable(),
  lod: z.preprocess(normalizeNumber, z.union([z.literal(0), z.literal(1), z.literal(2), z.literal(3)])),
  render_state: z.preprocess(normalizeCode, z.enum(['MATERIALIZED', 'SUMMARIZED', 'VIRTUALIZED', 'UNAVAILABLE'])),
  world_position: spatialPositionSchema,
  manual_position_override: z.boolean().default(false),
  pinned: z.boolean().default(false),
  unresolved: z.boolean().default(false),
  authorized: z.boolean().default(true),
  unavailable_reason: labelSchema.nullable().default(null),
  presentation_revision: revisionSchema,
  provenance: provenanceSchema,
}).strip()

export type SpatialMemoryProjection = z.infer<typeof spatialMemoryProjectionSchema>

export const spatialMemoryClusterSchema = z.object({
  schema_version: z.literal(SPATIAL_SCHEMA_VERSIONS.memoryCluster),
  cluster_id: idSchema,
  workspace_id: idSchema,
  title: labelSchema,
  criterion: z.preprocess(normalizeCode, z.enum(SPATIAL_MEMORY_CLUSTER_CRITERIA)),
  criterion_revision: revisionSchema,
  evidence: z.array(labelSchema).max(16),
  member_refs: z.array(spatialMemorySemanticRefSchema).max(10_000),
  stale_member_refs: z.array(spatialMemorySemanticRefSchema).max(10_000),
  summary_ref: idSchema,
  collapsed: z.boolean(),
  pinned: z.boolean(),
  presentation_revision: revisionSchema,
  provenance: provenanceSchema,
}).strip()

export type SpatialMemoryCluster = z.infer<typeof spatialMemoryClusterSchema>

const spatialMemoryCameraSchema = z.object({
  x: z.number().finite(),
  y: z.number().finite(),
  zoom: z.number().finite().positive(),
  focus_ref: idSchema.nullable(),
}).strip()

export const spatialMemoryFocusSchema = z.object({
  schema_version: z.literal(SPATIAL_SCHEMA_VERSIONS.memoryFocus),
  focus_id: idSchema,
  workspace_id: idSchema,
  target_ref: spatialMemorySemanticRefSchema,
  state: z.preprocess(normalizeCode, z.enum(SPATIAL_MEMORY_FOCUS_STATES)),
  target_revision: revisionSchema,
  world_position: spatialPositionSchema,
  temporary_position: spatialPositionSchema.nullable(),
  previous_camera: spatialMemoryCameraSchema,
  restore_camera: spatialMemoryCameraSchema,
  source: z.preprocess(normalizeCode, z.enum(['POINTER', 'KEYBOARD', 'GESTURE', 'RELATION', 'SEARCH', 'AGENT'])),
  reduced_motion: z.boolean(),
  unavailable_reason: labelSchema.nullable(),
  created_at: timestampSchema,
  updated_at: timestampSchema,
}).strip()

export type SpatialMemoryFocus = z.infer<typeof spatialMemoryFocusSchema>

const spatialMemorySearchResultSchema = z.object({
  result_ref: spatialMemorySemanticRefSchema,
  relevance: z.number().min(0).max(1),
  evidence: z.array(labelSchema).max(12),
  state: z.preprocess(normalizeCode, z.enum(['AVAILABLE', 'STALE', 'UNAVAILABLE', 'TOMBSTONE'])),
}).strip()

export const spatialMemorySearchSchema = z.object({
  schema_version: z.literal(SPATIAL_SCHEMA_VERSIONS.memorySearch),
  search_id: idSchema,
  workspace_id: idSchema,
  query: z.string().trim().min(1).max(240),
  policy_revision: idSchema,
  results: z.array(spatialMemorySearchResultSchema).max(10_000),
  performed_at: timestampSchema,
}).strip()

export type SpatialMemorySearchResult = z.infer<typeof spatialMemorySearchResultSchema>
export type SpatialMemorySearch = z.infer<typeof spatialMemorySearchSchema>

export const spatialMemoryVirtualizationSchema = z.object({
  schema_version: z.literal(SPATIAL_SCHEMA_VERSIONS.memoryVirtualization),
  workspace_id: idSchema,
  viewport_revision: revisionSchema,
  total_count: z.number().int().nonnegative(),
  visible_count: z.number().int().nonnegative(),
  materialized_count: z.number().int().nonnegative(),
  virtualized_count: z.number().int().nonnegative(),
  lod_counts: z.object({ lod0: z.number().int().nonnegative(), lod1: z.number().int().nonnegative(), lod2: z.number().int().nonnegative(), lod3: z.number().int().nonnegative() }).strip(),
  render_budget: z.number().int().positive(),
  materialization_latency_ms: z.number().nonnegative(),
  memory_released: z.boolean(),
  measured_at: timestampSchema,
}).strip()

export type SpatialMemoryVirtualization = z.infer<typeof spatialMemoryVirtualizationSchema>

/* M9 multi-device contracts. Shared world records deliberately contain only
 * semantic references/anchors; camera and presentation geometry are separate
 * device-local records and never enter a workspace mutation stream. */
const spatialWorldObjectSchema = z.object({
  canonical_ref: idSchema,
  semantic_anchor: spatialPositionSchema,
  region: stateSchema,
  manual_override: z.boolean().default(false),
  pinned: z.boolean().default(false),
  revision: revisionSchema,
  available: z.boolean().default(true),
}).strip()

const spatialWorldRelationSchema = z.object({
  relation_ref: idSchema,
  source_ref: idSchema,
  target_ref: idSchema,
  revision: revisionSchema,
  active: z.boolean().default(true),
}).strip()

const spatialWorldClusterSchema = z.object({
  cluster_ref: idSchema,
  member_refs: z.array(idSchema).max(10_000),
  revision: revisionSchema,
  collapsed: z.boolean().default(false),
}).strip()

const spatialWorkspaceWorldShape = z.object({
  schema_version: z.literal(SPATIAL_SCHEMA_VERSIONS.workspaceWorld),
  workspace_id: idSchema,
  node_id: idSchema,
  workspace_revision: revisionSchema,
  world_revision: revisionSchema,
  primary_agent_ref: idSchema.nullable().default(null),
  semantic_objects: z.array(spatialWorldObjectSchema).max(10_000),
  relations: z.array(spatialWorldRelationSchema).max(20_000),
  clusters: z.array(spatialWorldClusterSchema).max(10_000),
  session_refs: z.array(idSchema).max(10_000).default([]),
  pins: z.array(idSchema).max(10_000).default([]),
  updated_at: timestampSchema,
}).strip()

/** Accept the ADR-009 `world_revision` spelling and the UI's
 * `workspace_revision` spelling while emitting both for an unambiguous
 * monotonic revision boundary. */
export const spatialWorkspaceWorldSchema = z.preprocess((value) => {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return value
  const record = value as Record<string, unknown>
  const revision = record.workspace_revision ?? record.world_revision
  return {
    ...record,
    ...(record.workspace_revision === undefined ? { workspace_revision: revision } : {}),
    ...(record.world_revision === undefined ? { world_revision: revision } : {}),
  }
}, spatialWorkspaceWorldShape)

export type SpatialWorldObject = z.infer<typeof spatialWorldObjectSchema>
export type SpatialWorldRelation = z.infer<typeof spatialWorldRelationSchema>
export type SpatialWorldCluster = z.infer<typeof spatialWorldClusterSchema>
export type SpatialWorkspaceWorld = z.infer<typeof spatialWorkspaceWorldSchema>

const spatialDeviceCameraSchema = z.object({
  x: z.number().finite(),
  y: z.number().finite(),
  zoom: z.number().finite().positive(),
  orientation: z.object({ x: z.number().finite(), y: z.number().finite(), z: z.number().finite() }).strip(),
  focus_ref: idSchema.nullable().default(null),
}).strip()

export const spatialDeviceViewportSchema = z.object({
  schema_version: z.literal(SPATIAL_SCHEMA_VERSIONS.deviceViewport),
  workspace_id: idSchema,
  node_id: idSchema,
  device_id: idSchema,
  profile: z.preprocess(normalizeCode, z.enum(SPATIAL_DEVICE_PROFILES)),
  camera: spatialDeviceCameraSchema,
  focus_region: stateSchema,
  focus_anchor_ref: idSchema.nullable().default(null),
  selection_refs: z.array(idSchema).max(256).default([]),
  expanded_refs: z.array(idSchema).max(256).default([]),
  opened_frame_refs: z.array(idSchema).max(256).default([]),
  quality_profile: z.preprocess(normalizeCode, z.enum(['LOW', 'MOBILE', 'DESKTOP', 'HIGH'])),
  gesture_state: z.preprocess(normalizeCode, z.enum(['IDLE', 'PANNING', 'PINCHING', 'LONG_PRESS_PENDING', 'SEED_READY', 'CANCELLED'])),
  local_layout_revision: revisionSchema,
  updated_at: timestampSchema,
}).strip()

export type SpatialDeviceCamera = z.infer<typeof spatialDeviceCameraSchema>
export type SpatialDeviceViewport = z.infer<typeof spatialDeviceViewportSchema>

export const spatialPresentationGeometrySchema = z.object({
  schema_version: z.literal(SPATIAL_SCHEMA_VERSIONS.presentationGeometry),
  workspace_id: idSchema,
  node_id: idSchema,
  device_id: idSchema,
  semantic_ref: idSchema,
  variant: z.preprocess(normalizeCode, z.enum(SPATIAL_DEVICE_PROFILES)),
  width: z.number().finite().nonnegative(),
  height: z.number().finite().nonnegative(),
  density: z.number().finite().positive(),
  arrangement: z.preprocess(normalizeCode, z.enum(['FOCUS_FRAME', 'BOTTOM_SHEET', 'SIDE_PANEL', 'INLINE'])),
  safe_area_inset: z.object({ top: z.number().nonnegative(), right: z.number().nonnegative(), bottom: z.number().nonnegative(), left: z.number().nonnegative() }).strip(),
  keyboard_inset: z.number().finite().nonnegative().default(0),
  revision: revisionSchema,
  updated_at: timestampSchema,
}).strip()

export type SpatialPresentationGeometry = z.infer<typeof spatialPresentationGeometrySchema>

const spatialMutationPayloadSchema = z.record(z.string(), z.unknown()).default({})

export const spatialWorkspaceMutationSchema = z.object({
  schema_version: z.literal(SPATIAL_SCHEMA_VERSIONS.workspaceMutation),
  event_id: idSchema,
  operation_id: idSchema,
  idempotency_key: idSchema,
  workspace_id: idSchema,
  node_id: idSchema,
  device_id: idSchema,
  actor_ref: idSchema,
  base_revision: revisionSchema,
  operation: z.preprocess(normalizeCode, z.enum(SPATIAL_WORKSPACE_MUTATION_OPERATIONS)),
  target_refs: z.array(idSchema).max(256),
  conflict_category: z.preprocess(normalizeCode, z.enum(SPATIAL_WORKSPACE_MUTATION_CONFLICT_CATEGORIES)).default('NONE'),
  payload: spatialMutationPayloadSchema,
  logical_clock: revisionSchema,
  created_at: timestampSchema,
}).strip()

export type SpatialWorkspaceMutation = z.infer<typeof spatialWorkspaceMutationSchema>

export const spatialWorkspaceMutationResultSchema = z.object({
  schema_version: z.literal(SPATIAL_SCHEMA_VERSIONS.workspaceMutationResult),
  event_id: idSchema,
  operation_id: idSchema,
  workspace_id: idSchema,
  node_id: idSchema,
  state: z.preprocess(normalizeCode, z.enum(SPATIAL_WORKSPACE_MUTATION_RESULT_STATES)),
  conflict_category: z.preprocess(normalizeCode, z.enum(SPATIAL_WORKSPACE_MUTATION_CONFLICT_CATEGORIES)),
  server_result_revision: revisionSchema,
  current_evidence: z.object({
    workspace_revision: revisionSchema,
    target_refs: z.array(idSchema).max(256),
    winning_operation_id: idSchema.nullable().default(null),
    reason: labelSchema.nullable().default(null),
  }).strip(),
  world: spatialWorkspaceWorldSchema,
  audit_ref: idSchema,
  resolved_at: timestampSchema,
}).strip()

export type SpatialWorkspaceMutationResult = z.infer<typeof spatialWorkspaceMutationResultSchema>

const spatialOfflineMutationEntrySchema = z.object({
  mutation: spatialWorkspaceMutationSchema,
  queued_at: timestampSchema,
  attempts: z.number().int().nonnegative().default(0),
  state: z.preprocess(normalizeCode, z.enum(['PENDING', 'REBASED', 'CONFLICT', 'REJECTED', 'DISCARDED'])).default('PENDING'),
  conflict_reason: labelSchema.nullable().default(null),
}).strip()

export const spatialOfflineQueueSchema = z.object({
  schema_version: z.literal(SPATIAL_SCHEMA_VERSIONS.offlineQueue),
  workspace_id: idSchema,
  node_id: idSchema,
  device_id: idSchema,
  connectivity: z.preprocess(normalizeCode, z.enum(SPATIAL_OFFLINE_CONNECTIVITY_STATES)),
  last_consistent_revision: revisionSchema,
  pending: z.array(spatialOfflineMutationEntrySchema).max(10_000),
  updated_at: timestampSchema,
}).strip()

export type SpatialOfflineMutationEntry = z.infer<typeof spatialOfflineMutationEntrySchema>
export type SpatialOfflineQueue = z.infer<typeof spatialOfflineQueueSchema>

export const spatialShareViewSchema = z.object({
  schema_version: z.literal(SPATIAL_SCHEMA_VERSIONS.shareView),
  share_id: idSchema,
  workspace_id: idSchema,
  node_id: idSchema,
  owner_device_id: idSchema,
  audience_device_ids: z.array(idSchema).max(256),
  target_ref: idSchema.nullable().default(null),
  state: z.preprocess(normalizeCode, z.enum(SPATIAL_SHARE_VIEW_STATES)),
  focus_authorized: z.boolean().default(false),
  expires_at: timestampSchema,
  created_at: timestampSchema,
  updated_at: timestampSchema,
}).strip()

export type SpatialShareView = z.infer<typeof spatialShareViewSchema>

/** M4 contracts are kept in a separate registry so M2 consumers remain stable. */
export const spatialInteractionContractSchemas = {
  attachmentManifest: spatialAttachmentManifestSchema,
  intentEnvelope: spatialIntentEnvelopeSchema,
  workspaceSession: spatialWorkspaceSessionSchema,
  contextNode: spatialContextNodeSchema,
  conversationTurn: spatialConversationTurnSchema,
  generatedObject: spatialGeneratedObjectSchema,
  artifact: spatialArtifactSchema,
  presentationIntent: spatialPresentationIntentSchema,
  presentationResult: spatialPresentationResultSchema,
  canonicalReference: spatialCanonicalReferenceSchema,
  endpointDetails: spatialEndpointDetailsSchema,
  discoveryResult: spatialDiscoveryResultSchema,
  semanticRelation: spatialSemanticRelationSchema,
  subagentLifecycle: spatialSubagentLifecycleSchema,
  interactionProvenance: spatialInteractionProvenanceSchema,
  attentionItem: spatialAttentionItemSchema,
  attentionMarker: spatialAttentionMarkerSchema,
  attentionFocus: spatialAttentionFocusSchema,
} as const

export const spatialRemoteContractSchemas = {
  endpointProvenance: spatialEndpointProvenanceSchema,
  contextManifest: spatialRemoteContextManifestSchema,
  request: spatialRemoteRequestSchema,
  result: spatialRemoteResultSchema,
  endpointTestFrame: spatialEndpointTestFrameSchema,
  accounting: spatialResourceAccountingSchema,
} as const

export const spatialMemoryContractSchemas = {
  layout: spatialMemoryLayoutSchema,
  projection: spatialMemoryProjectionSchema,
  cluster: spatialMemoryClusterSchema,
  focus: spatialMemoryFocusSchema,
  search: spatialMemorySearchSchema,
  virtualization: spatialMemoryVirtualizationSchema,
} as const

export type SpatialInteractionContractName = keyof typeof spatialInteractionContractSchemas

export type SpatialInteractionContractPayload = SpatialAttachmentManifest | SpatialIntentEnvelope | SpatialWorkspaceSession | SpatialContextNode | SpatialConversationTurn | SpatialGeneratedObject | SpatialArtifact | SpatialPresentationIntent | SpatialPresentationResult | SpatialCanonicalReference | SpatialEndpointDetails | SpatialDiscoveryResult | SpatialSemanticRelation | SpatialSubagentLifecycle | SpatialInteractionProvenance | SpatialAttentionItem | SpatialAttentionMarker | SpatialAttentionFocus
export type SpatialRemoteContractPayload = SpatialEndpointProvenance | SpatialRemoteContextManifest | SpatialRemoteRequest | SpatialRemoteResult | SpatialEndpointTestFrame | SpatialResourceAccounting
export type SpatialMemoryContractName = keyof typeof spatialMemoryContractSchemas
export type SpatialMemoryContractPayload = SpatialMemoryLayout | SpatialMemoryProjection | SpatialMemoryCluster | SpatialMemoryFocus | SpatialMemorySearch | SpatialMemoryVirtualization

export const spatialMultiDeviceContractSchemas = {
  workspaceWorld: spatialWorkspaceWorldSchema,
  deviceViewport: spatialDeviceViewportSchema,
  presentationGeometry: spatialPresentationGeometrySchema,
  workspaceMutation: spatialWorkspaceMutationSchema,
  workspaceMutationResult: spatialWorkspaceMutationResultSchema,
  offlineQueue: spatialOfflineQueueSchema,
  shareView: spatialShareViewSchema,
} as const

export const spatialAgentComponentContractSchemas = {
  changeIntent: spatialChangeIntentSchema,
  resultModel: spatialResultModelSchema,
  componentFrame: spatialComponentFrameSchema,
  resourceSummary: spatialResourceSummarySchema,
  actionFeedback: spatialActionFeedbackSchema,
} as const

export type SpatialAgentComponentContractName = keyof typeof spatialAgentComponentContractSchemas
export type SpatialAgentComponentContractPayload = SpatialChangeIntent | SpatialResultModel | SpatialComponentFrame | SpatialResourceSummary | SpatialActionFeedback

export type SpatialMultiDeviceContractName = keyof typeof spatialMultiDeviceContractSchemas
export type SpatialMultiDeviceContractPayload = SpatialWorkspaceWorld | SpatialDeviceViewport | SpatialPresentationGeometry | SpatialWorkspaceMutation | SpatialWorkspaceMutationResult | SpatialOfflineQueue | SpatialShareView

export const attachmentManifestSchema = spatialAttachmentManifestSchema
export const intentEnvelopeSchema = spatialIntentEnvelopeSchema
export const workspaceSessionSchema = spatialWorkspaceSessionSchema
export const contextNodeSchema = spatialContextNodeSchema
export const conversationTurnSchema = spatialConversationTurnSchema
export const generatedObjectSchema = spatialGeneratedObjectSchema
export const artifactSchema = spatialArtifactSchema
export const presentationIntentSchema = spatialPresentationIntentSchema
export const presentationResultSchema = spatialPresentationResultSchema
export const canonicalReferenceSchema = spatialCanonicalReferenceSchema
export const endpointDetailsSchema = spatialEndpointDetailsSchema
export const discoveryResultSchema = spatialDiscoveryResultSchema
export const semanticRelationSchema = spatialSemanticRelationSchema
export const subagentLifecycleSchema = spatialSubagentLifecycleSchema
export const interactionProvenanceSchema = spatialInteractionProvenanceSchema
export const attentionItemSchema = spatialAttentionItemSchema
export const attentionMarkerSchema = spatialAttentionMarkerSchema
export const attentionFocusSchema = spatialAttentionFocusSchema
export const endpointProvenanceSchema = spatialEndpointProvenanceSchema
export const remoteContextManifestSchema = spatialRemoteContextManifestSchema
export const remoteRequestSchema = spatialRemoteRequestSchema
export const remoteResultSchema = spatialRemoteResultSchema
export const endpointTestFrameSchema = spatialEndpointTestFrameSchema
export const resourceAccountingSchema = spatialResourceAccountingSchema
export const memoryLayoutSchema = spatialMemoryLayoutSchema
export const memoryProjectionSchema = spatialMemoryProjectionSchema
export const memoryClusterSchema = spatialMemoryClusterSchema
export const memoryFocusSchema = spatialMemoryFocusSchema
export const memorySearchSchema = spatialMemorySearchSchema
export const memoryVirtualizationSchema = spatialMemoryVirtualizationSchema
export const changeIntentSchema = spatialChangeIntentSchema
export const resultModelSchema = spatialResultModelSchema
export const componentFrameSchema = spatialComponentFrameSchema
export const resourceSummarySchema = spatialResourceSummarySchema
export const actionFeedbackSchema = spatialActionFeedbackSchema

export type IntentEnvelope = SpatialIntentEnvelope
export type WorkspaceSession = SpatialWorkspaceSession
export type ContextNode = SpatialContextNode
export type ConversationTurn = SpatialConversationTurn
export type GeneratedObject = SpatialGeneratedObject
export type SessionArtifact = SpatialArtifact
export type CanonicalReference = SpatialCanonicalReference
export type EndpointDetails = SpatialEndpointDetails
export type DiscoveryResult = SpatialDiscoveryResult
export type SemanticRelation = SpatialSemanticRelation
export type SubagentLifecycle = SpatialSubagentLifecycle
export type InteractionProvenance = SpatialInteractionProvenance
export type AttentionItem = SpatialAttentionItem
export type AttentionMarker = SpatialAttentionMarker
export type AttentionFocus = SpatialAttentionFocus
export type EndpointProvenance = SpatialEndpointProvenance
export type RemoteContextManifest = SpatialRemoteContextManifest
export type RemoteRequest = SpatialRemoteRequest
export type RemoteResult = SpatialRemoteResult
export type EndpointTestFrame = SpatialEndpointTestFrame
export type ResourceAccounting = SpatialResourceAccounting
export type MemoryLayout = SpatialMemoryLayout
export type MemoryProjection = SpatialMemoryProjection
export type MemoryCluster = SpatialMemoryCluster
export type MemoryFocus = SpatialMemoryFocus
export type MemorySearch = SpatialMemorySearch
export type MemoryVirtualization = SpatialMemoryVirtualization
export type WorkspaceWorld = SpatialWorkspaceWorld
export type DeviceViewport = SpatialDeviceViewport
export type PresentationGeometry = SpatialPresentationGeometry
export type WorkspaceMutation = SpatialWorkspaceMutation
export type WorkspaceMutationResult = SpatialWorkspaceMutationResult
export type OfflineQueue = SpatialOfflineQueue
export type ShareView = SpatialShareView
export type ChangeIntent = SpatialChangeIntent
export type ResultModel = SpatialResultModel
export type ComponentFrame = SpatialComponentFrame
export type ResourceSummary = SpatialResourceSummary
export type ActionFeedback = SpatialActionFeedback

export type SpatialContractPayload = SpatialCanonicalEntity | SpatialRelationContract | SpatialNodeStatus | SpatialWorkspaceSnapshot | SpatialViewportSnapshot | SpatialPrimaryAgentSlot | SpatialPrimaryAgentGrant | SpatialPrimaryAgentState | SpatialRecoveryCommand | SpatialRecoveryResult | SpatialInteractionContractPayload | SpatialRemoteContractPayload | SpatialMemoryContractPayload | SpatialMultiDeviceContractPayload | SpatialAgentComponentContractPayload

/** M11 hardening records are additive contracts kept out of the M2 baseline
 * registry so older Node clients can continue to enumerate the original
 * transport set without accidentally treating telemetry as domain state. */
export type SpatialHardeningContractPayload =
  | SpatialAuthorizationDecisionRecord
  | SpatialAuditRecord
  | SpatialReliabilityIncident
  | SpatialPrivacyRecord
  | SpatialPerformanceReport
  | SpatialObservabilityMetric
  | SpatialRolloutStageRecord

export const spatialRecoveryContractSchemas = {
  command: spatialRecoveryCommandSchema,
  result: spatialRecoveryResultSchema,
} as const

export const spatialContractSchemas = {
  entity: spatialEntitySchema,
  relation: spatialRelationSchema,
  status: spatialNodeStatusSchema,
  workspace: spatialWorkspaceSchema,
  viewport: spatialViewportSchema,
  primaryAgentSlot: spatialPrimaryAgentSlotSchema,
  primaryAgentGrant: spatialPrimaryAgentGrantSchema,
  primaryAgentState: spatialPrimaryAgentStateSchema,
} as const

export const spatialHardeningContractSchemas = {
  authorizationDecision: spatialAuthorizationDecisionSchema,
  auditRecord: spatialAuditRecordSchema,
  reliabilityIncident: spatialReliabilityIncidentSchema,
  privacyRecord: spatialPrivacyRecordSchema,
  performanceReport: spatialPerformanceReportSchema,
  observabilityMetric: spatialObservabilityMetricSchema,
  rolloutStage: spatialRolloutStageSchema,
} as const

export type SpatialHardeningContractName = keyof typeof spatialHardeningContractSchemas

export type SpatialContractName = keyof typeof spatialContractSchemas

export type SpatialParseDiagnosticCode = 'MALFORMED_PAYLOAD' | 'INCOMPATIBLE_SCHEMA_VERSION'

export type SpatialParseDiagnostic = {
  code: SpatialParseDiagnosticCode
  contract: SpatialSchemaVersion
  expected_version: SpatialSchemaVersion
  received_version?: string
  path: string
  issue_code?: string
}

export type SpatialParseResult<T> =
  | { ok: true; data: T }
  | { ok: false; diagnostic: SpatialParseDiagnostic }

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function versionBase(version: SpatialSchemaVersion): string {
  return version.replace(/\.v\d+$/, '')
}

/**
 * Parse before a value reaches a query/store boundary. Diagnostics contain
 * only contract, path, version and issue category; payload values are never
 * copied into errors or logs.
 */
export function parseSpatialContract<T>(
  contract: SpatialSchemaVersion,
  schema: z.ZodType<T>,
  payload: unknown,
): SpatialParseResult<T> {
  const receivedVersion = isRecord(payload) && typeof payload.schema_version === 'string'
    ? payload.schema_version
    : undefined
  if (receivedVersion && receivedVersion !== contract && receivedVersion.startsWith(`${versionBase(contract)}.v`)) {
    return {
      ok: false,
      diagnostic: {
        code: 'INCOMPATIBLE_SCHEMA_VERSION',
        contract,
        expected_version: contract,
        received_version: receivedVersion,
        path: 'schema_version',
      },
    }
  }

  const parsed = schema.safeParse(payload)
  if (parsed.success) return { ok: true, data: parsed.data }
  const issue = parsed.error.issues[0]
  return {
    ok: false,
    diagnostic: {
      code: 'MALFORMED_PAYLOAD',
      contract,
      expected_version: contract,
      path: issue?.path.length ? issue.path.join('.') : '<root>',
      issue_code: issue?.code,
    },
  }
}

export function parseSpatialEntity(payload: unknown): SpatialParseResult<SpatialCanonicalEntity> {
  return parseSpatialContract(SPATIAL_SCHEMA_VERSIONS.entity, spatialEntitySchema, payload)
}

export function parseSpatialRelation(payload: unknown): SpatialParseResult<SpatialRelationContract> {
  return parseSpatialContract(SPATIAL_SCHEMA_VERSIONS.relation, spatialRelationSchema, payload)
}

export function parseSpatialNodeStatus(payload: unknown): SpatialParseResult<SpatialNodeStatus> {
  return parseSpatialContract(SPATIAL_SCHEMA_VERSIONS.status, spatialNodeStatusSchema, payload)
}

export function parseSpatialRecoveryCommand(payload: unknown): SpatialParseResult<SpatialRecoveryCommand> {
  return parseSpatialContract(SPATIAL_SCHEMA_VERSIONS.recoveryCommand, spatialRecoveryCommandSchema, payload)
}

export function parseSpatialRecoveryResult(payload: unknown): SpatialParseResult<SpatialRecoveryResult> {
  return parseSpatialContract(SPATIAL_SCHEMA_VERSIONS.recoveryResult, spatialRecoveryResultSchema, payload)
}

export function parseSpatialWorkspace(payload: unknown): SpatialParseResult<SpatialWorkspaceSnapshot> {
  return parseSpatialContract(SPATIAL_SCHEMA_VERSIONS.workspace, spatialWorkspaceSchema, payload)
}

export function parseSpatialViewport(payload: unknown): SpatialParseResult<SpatialViewportSnapshot> {
  return parseSpatialContract(SPATIAL_SCHEMA_VERSIONS.viewport, spatialViewportSchema, payload)
}

export function parseSpatialPrimaryAgentSlot(payload: unknown): SpatialParseResult<SpatialPrimaryAgentSlot> {
  return parseSpatialContract(SPATIAL_SCHEMA_VERSIONS.primaryAgentSlot, spatialPrimaryAgentSlotSchema, payload)
}

export function parseSpatialPrimaryAgentGrant(payload: unknown): SpatialParseResult<SpatialPrimaryAgentGrant> {
  return parseSpatialContract(SPATIAL_SCHEMA_VERSIONS.primaryAgentGrant, spatialPrimaryAgentGrantSchema, payload)
}

export function parseSpatialPrimaryAgentState(payload: unknown): SpatialParseResult<SpatialPrimaryAgentState> {
  return parseSpatialContract(SPATIAL_SCHEMA_VERSIONS.primaryAgentState, spatialPrimaryAgentStateSchema, payload)
}

export function parseSpatialAttachmentManifest(payload: unknown): SpatialParseResult<SpatialAttachmentManifest> {
  return parseSpatialContract(SPATIAL_SCHEMA_VERSIONS.attachmentManifest, spatialAttachmentManifestSchema, payload)
}

export function parseSpatialIntentEnvelope(payload: unknown): SpatialParseResult<SpatialIntentEnvelope> {
  return parseSpatialContract(SPATIAL_SCHEMA_VERSIONS.intentEnvelope, spatialIntentEnvelopeSchema, payload)
}

export function parseSpatialWorkspaceSession(payload: unknown): SpatialParseResult<SpatialWorkspaceSession> {
  return parseSpatialContract(SPATIAL_SCHEMA_VERSIONS.workspaceSession, spatialWorkspaceSessionSchema, payload)
}

export function parseSpatialContextNode(payload: unknown): SpatialParseResult<SpatialContextNode> {
  return parseSpatialContract(SPATIAL_SCHEMA_VERSIONS.contextNode, spatialContextNodeSchema, payload)
}

export function parseSpatialConversationTurn(payload: unknown): SpatialParseResult<SpatialConversationTurn> {
  return parseSpatialContract(SPATIAL_SCHEMA_VERSIONS.conversationTurn, spatialConversationTurnSchema, payload)
}

export function parseSpatialGeneratedObject(payload: unknown): SpatialParseResult<SpatialGeneratedObject> {
  return parseSpatialContract(SPATIAL_SCHEMA_VERSIONS.generatedObject, spatialGeneratedObjectSchema, payload)
}

export function parseSpatialArtifact(payload: unknown): SpatialParseResult<SpatialArtifact> {
  return parseSpatialContract(SPATIAL_SCHEMA_VERSIONS.artifact, spatialArtifactSchema, payload)
}

export function parseSpatialPresentationIntent(payload: unknown): SpatialParseResult<SpatialPresentationIntent> {
  return parseSpatialContract(SPATIAL_SCHEMA_VERSIONS.presentationIntent, spatialPresentationIntentSchema, payload)
}

export function parseSpatialPresentationResult(payload: unknown): SpatialParseResult<SpatialPresentationResult> {
  return parseSpatialContract(SPATIAL_SCHEMA_VERSIONS.presentationResult, spatialPresentationResultSchema, payload)
}

export function parseSpatialCanonicalReference(payload: unknown): SpatialParseResult<SpatialCanonicalReference> {
  return parseSpatialContract(SPATIAL_SCHEMA_VERSIONS.canonicalReference, spatialCanonicalReferenceSchema, payload)
}

export function parseSpatialEndpointDetails(payload: unknown): SpatialParseResult<SpatialEndpointDetails> {
  return parseSpatialContract(SPATIAL_SCHEMA_VERSIONS.endpointDetails, spatialEndpointDetailsSchema, payload)
}

export function parseSpatialDiscoveryResult(payload: unknown): SpatialParseResult<SpatialDiscoveryResult> {
  return parseSpatialContract(SPATIAL_SCHEMA_VERSIONS.discoveryResult, spatialDiscoveryResultSchema, payload)
}

export function parseSpatialSemanticRelation(payload: unknown): SpatialParseResult<SpatialSemanticRelation> {
  return parseSpatialContract(SPATIAL_SCHEMA_VERSIONS.semanticRelation, spatialSemanticRelationSchema, payload)
}

export function parseSpatialSubagentLifecycle(payload: unknown): SpatialParseResult<SpatialSubagentLifecycle> {
  return parseSpatialContract(SPATIAL_SCHEMA_VERSIONS.subagentLifecycle, spatialSubagentLifecycleSchema, payload)
}

export function parseSpatialInteractionProvenance(payload: unknown): SpatialParseResult<SpatialInteractionProvenance> {
  return parseSpatialContract(SPATIAL_SCHEMA_VERSIONS.interactionProvenance, spatialInteractionProvenanceSchema, payload)
}

export function parseSpatialAttentionItem(payload: unknown): SpatialParseResult<SpatialAttentionItem> {
  return parseSpatialContract(SPATIAL_SCHEMA_VERSIONS.attentionItem, spatialAttentionItemSchema, payload)
}

export function parseSpatialAttentionMarker(payload: unknown): SpatialParseResult<SpatialAttentionMarker> {
  return parseSpatialContract(SPATIAL_SCHEMA_VERSIONS.attentionMarker, spatialAttentionMarkerSchema, payload)
}

export function parseSpatialAttentionFocus(payload: unknown): SpatialParseResult<SpatialAttentionFocus> {
  return parseSpatialContract(SPATIAL_SCHEMA_VERSIONS.attentionFocus, spatialAttentionFocusSchema, payload)
}

export function parseSpatialEndpointProvenance(payload: unknown): SpatialParseResult<SpatialEndpointProvenance> {
  return parseSpatialContract(SPATIAL_SCHEMA_VERSIONS.endpointProvenance, spatialEndpointProvenanceSchema, payload)
}

export function parseSpatialRemoteContextManifest(payload: unknown): SpatialParseResult<SpatialRemoteContextManifest> {
  return parseSpatialContract(SPATIAL_SCHEMA_VERSIONS.remoteContextManifest, spatialRemoteContextManifestSchema, payload)
}

export function parseSpatialRemoteRequest(payload: unknown): SpatialParseResult<SpatialRemoteRequest> {
  return parseSpatialContract(SPATIAL_SCHEMA_VERSIONS.remoteRequest, spatialRemoteRequestSchema, payload)
}

export function parseSpatialRemoteResult(payload: unknown): SpatialParseResult<SpatialRemoteResult> {
  return parseSpatialContract(SPATIAL_SCHEMA_VERSIONS.remoteResult, spatialRemoteResultSchema, payload)
}

export function parseSpatialEndpointTestFrame(payload: unknown): SpatialParseResult<SpatialEndpointTestFrame> {
  return parseSpatialContract(SPATIAL_SCHEMA_VERSIONS.endpointTestFrame, spatialEndpointTestFrameSchema, payload)
}

export function parseSpatialResourceAccounting(payload: unknown): SpatialParseResult<SpatialResourceAccounting> {
  return parseSpatialContract(SPATIAL_SCHEMA_VERSIONS.resourceAccounting, spatialResourceAccountingSchema, payload)
}

export function parseSpatialMemoryLayout(payload: unknown): SpatialParseResult<SpatialMemoryLayout> {
  return parseSpatialContract(SPATIAL_SCHEMA_VERSIONS.memoryLayout, spatialMemoryLayoutSchema, payload)
}

export function parseSpatialMemoryProjection(payload: unknown): SpatialParseResult<SpatialMemoryProjection> {
  return parseSpatialContract(SPATIAL_SCHEMA_VERSIONS.memoryProjection, spatialMemoryProjectionSchema, payload)
}

export function parseSpatialMemoryCluster(payload: unknown): SpatialParseResult<SpatialMemoryCluster> {
  return parseSpatialContract(SPATIAL_SCHEMA_VERSIONS.memoryCluster, spatialMemoryClusterSchema, payload)
}

export function parseSpatialMemoryFocus(payload: unknown): SpatialParseResult<SpatialMemoryFocus> {
  return parseSpatialContract(SPATIAL_SCHEMA_VERSIONS.memoryFocus, spatialMemoryFocusSchema, payload)
}

export function parseSpatialMemorySearch(payload: unknown): SpatialParseResult<SpatialMemorySearch> {
  return parseSpatialContract(SPATIAL_SCHEMA_VERSIONS.memorySearch, spatialMemorySearchSchema, payload)
}

export function parseSpatialMemoryVirtualization(payload: unknown): SpatialParseResult<SpatialMemoryVirtualization> {
  return parseSpatialContract(SPATIAL_SCHEMA_VERSIONS.memoryVirtualization, spatialMemoryVirtualizationSchema, payload)
}

export function parseSpatialWorkspaceWorld(payload: unknown): SpatialParseResult<SpatialWorkspaceWorld> {
  return parseSpatialContract(SPATIAL_SCHEMA_VERSIONS.workspaceWorld, spatialWorkspaceWorldSchema, payload)
}

export function parseSpatialDeviceViewport(payload: unknown): SpatialParseResult<SpatialDeviceViewport> {
  return parseSpatialContract(SPATIAL_SCHEMA_VERSIONS.deviceViewport, spatialDeviceViewportSchema, payload)
}

export function parseSpatialPresentationGeometry(payload: unknown): SpatialParseResult<SpatialPresentationGeometry> {
  return parseSpatialContract(SPATIAL_SCHEMA_VERSIONS.presentationGeometry, spatialPresentationGeometrySchema, payload)
}

export function parseSpatialWorkspaceMutation(payload: unknown): SpatialParseResult<SpatialWorkspaceMutation> {
  return parseSpatialContract(SPATIAL_SCHEMA_VERSIONS.workspaceMutation, spatialWorkspaceMutationSchema, payload)
}

export function parseSpatialWorkspaceMutationResult(payload: unknown): SpatialParseResult<SpatialWorkspaceMutationResult> {
  return parseSpatialContract(SPATIAL_SCHEMA_VERSIONS.workspaceMutationResult, spatialWorkspaceMutationResultSchema, payload)
}

export function parseSpatialOfflineQueue(payload: unknown): SpatialParseResult<SpatialOfflineQueue> {
  return parseSpatialContract(SPATIAL_SCHEMA_VERSIONS.offlineQueue, spatialOfflineQueueSchema, payload)
}

export function parseSpatialShareView(payload: unknown): SpatialParseResult<SpatialShareView> {
  return parseSpatialContract(SPATIAL_SCHEMA_VERSIONS.shareView, spatialShareViewSchema, payload)
}

export function parseSpatialChangeIntent(payload: unknown): SpatialParseResult<SpatialChangeIntent> {
  return parseSpatialContract(SPATIAL_SCHEMA_VERSIONS.changeIntent, spatialChangeIntentSchema, payload)
}

export function parseSpatialResultModel(payload: unknown): SpatialParseResult<SpatialResultModel> {
  return parseSpatialContract(SPATIAL_SCHEMA_VERSIONS.resultModel, spatialResultModelSchema, payload)
}

export function parseSpatialComponentFrame(payload: unknown): SpatialParseResult<SpatialComponentFrame> {
  return parseSpatialContract(SPATIAL_SCHEMA_VERSIONS.componentFrame, spatialComponentFrameSchema, payload)
}

export function parseSpatialResourceSummary(payload: unknown): SpatialParseResult<SpatialResourceSummary> {
  return parseSpatialContract(SPATIAL_SCHEMA_VERSIONS.resourceSummary, spatialResourceSummarySchema, payload)
}

export function parseSpatialActionFeedback(payload: unknown): SpatialParseResult<SpatialActionFeedback> {
  return parseSpatialContract(SPATIAL_SCHEMA_VERSIONS.actionFeedback, spatialActionFeedbackSchema, payload)
}

export function parseSpatialAuthorizationDecision(payload: unknown): SpatialParseResult<SpatialAuthorizationDecisionRecord> {
  return parseSpatialContract(SPATIAL_SCHEMA_VERSIONS.authorizationDecision, spatialAuthorizationDecisionSchema, payload)
}

export function parseSpatialAuditRecord(payload: unknown): SpatialParseResult<SpatialAuditRecord> {
  return parseSpatialContract(SPATIAL_SCHEMA_VERSIONS.auditRecord, spatialAuditRecordSchema, payload)
}

export function parseSpatialReliabilityIncident(payload: unknown): SpatialParseResult<SpatialReliabilityIncident> {
  return parseSpatialContract(SPATIAL_SCHEMA_VERSIONS.reliabilityIncident, spatialReliabilityIncidentSchema, payload)
}

export function parseSpatialPrivacyRecord(payload: unknown): SpatialParseResult<SpatialPrivacyRecord> {
  return parseSpatialContract(SPATIAL_SCHEMA_VERSIONS.privacyRecord, spatialPrivacyRecordSchema, payload)
}

export function parseSpatialPerformanceReport(payload: unknown): SpatialParseResult<SpatialPerformanceReport> {
  return parseSpatialContract(SPATIAL_SCHEMA_VERSIONS.performanceReport, spatialPerformanceReportSchema, payload)
}

export function parseSpatialObservabilityMetric(payload: unknown): SpatialParseResult<SpatialObservabilityMetric> {
  return parseSpatialContract(SPATIAL_SCHEMA_VERSIONS.observabilityMetric, spatialObservabilityMetricSchema, payload)
}

export function parseSpatialRolloutStage(payload: unknown): SpatialParseResult<SpatialRolloutStageRecord> {
  return parseSpatialContract(SPATIAL_SCHEMA_VERSIONS.rolloutStage, spatialRolloutStageSchema, payload)
}

export const parseIntentEnvelope = parseSpatialIntentEnvelope
export const parseWorkspaceSession = parseSpatialWorkspaceSession
export const parseContextNode = parseSpatialContextNode
export const parseConversationTurn = parseSpatialConversationTurn
export const parseGeneratedObject = parseSpatialGeneratedObject
export const parseArtifact = parseSpatialArtifact
export const parsePresentationIntent = parseSpatialPresentationIntent
export const parsePresentationResult = parseSpatialPresentationResult
export const parseCanonicalReference = parseSpatialCanonicalReference
export const parseEndpointDetails = parseSpatialEndpointDetails
export const parseDiscoveryResult = parseSpatialDiscoveryResult
export const parseSemanticRelation = parseSpatialSemanticRelation
export const parseSubagentLifecycle = parseSpatialSubagentLifecycle
export const parseInteractionProvenance = parseSpatialInteractionProvenance
export const parseAttentionItem = parseSpatialAttentionItem
export const parseAttentionMarker = parseSpatialAttentionMarker
export const parseAttentionFocus = parseSpatialAttentionFocus
export const parseEndpointProvenance = parseSpatialEndpointProvenance
export const parseRemoteContextManifest = parseSpatialRemoteContextManifest
export const parseRemoteRequest = parseSpatialRemoteRequest
export const parseRemoteResult = parseSpatialRemoteResult
export const parseEndpointTestFrame = parseSpatialEndpointTestFrame
export const parseResourceAccounting = parseSpatialResourceAccounting
export const parseWorkspaceWorld = parseSpatialWorkspaceWorld
export const parseDeviceViewport = parseSpatialDeviceViewport
export const parsePresentationGeometry = parseSpatialPresentationGeometry
export const parseWorkspaceMutation = parseSpatialWorkspaceMutation
export const parseWorkspaceMutationResult = parseSpatialWorkspaceMutationResult
export const parseOfflineQueue = parseSpatialOfflineQueue
export const parseShareView = parseSpatialShareView
export const parseChangeIntent = parseSpatialChangeIntent
export const parseResultModel = parseSpatialResultModel
export const parseComponentFrame = parseSpatialComponentFrame
export const parseResourceSummary = parseSpatialResourceSummary
export const parseActionFeedback = parseSpatialActionFeedback
export const parseAuthorizationDecision = parseSpatialAuthorizationDecision
export const parseAuditRecord = parseSpatialAuditRecord
export const parseReliabilityIncident = parseSpatialReliabilityIncident
export const parsePrivacyRecord = parseSpatialPrivacyRecord
export const parsePerformanceReport = parseSpatialPerformanceReport
export const parseObservabilityMetric = parseSpatialObservabilityMetric
export const parseRolloutStage = parseSpatialRolloutStage
