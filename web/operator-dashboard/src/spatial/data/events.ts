import { z } from 'zod'

import {
  parseSpatialEntity,
  parseSpatialArtifact,
  parseSpatialAttentionFocus,
  parseSpatialAttentionItem,
  parseSpatialAttentionMarker,
  parseSpatialCanonicalReference,
  parseSpatialContextNode,
  parseSpatialConversationTurn,
  parseSpatialDiscoveryResult,
  parseSpatialEndpointDetails,
  parseSpatialGeneratedObject,
  parseSpatialIntentEnvelope,
  parseSpatialInteractionProvenance,
  parseSpatialNodeStatus,
  parseSpatialRecoveryCommand,
  parseSpatialRecoveryResult,
  parseSpatialEndpointProvenance,
  parseSpatialRemoteContextManifest,
  parseSpatialRemoteRequest,
  parseSpatialRemoteResult,
  parseSpatialEndpointTestFrame,
  parseSpatialResourceAccounting,
  parseSpatialMemoryLayout,
  parseSpatialMemoryProjection,
  parseSpatialMemoryCluster,
  parseSpatialMemoryFocus,
  parseSpatialMemorySearch,
  parseSpatialMemoryVirtualization,
  parseSpatialWorkspaceWorld,
  parseSpatialDeviceViewport,
  parseSpatialPresentationGeometry,
  parseSpatialWorkspaceMutation,
  parseSpatialWorkspaceMutationResult,
  parseSpatialOfflineQueue,
  parseSpatialShareView,
  parseSpatialChangeIntent,
  parseSpatialResultModel,
  parseSpatialComponentFrame,
  parseSpatialResourceSummary,
  parseSpatialActionFeedback,
  parseSpatialPrimaryAgentGrant,
  parseSpatialPrimaryAgentSlot,
  parseSpatialPrimaryAgentState,
  parseSpatialRelation,
  parseSpatialSemanticRelation,
  parseSpatialSubagentLifecycle,
  parseSpatialPresentationIntent,
  parseSpatialPresentationResult,
  parseSpatialWorkspace,
  parseSpatialWorkspaceSession,
  spatialIdSchema,
  spatialRevisionSchema,
  spatialTimestampSchema,
  type SpatialCanonicalEntity,
  type SpatialArtifact,
  type SpatialAttentionFocus,
  type SpatialAttentionItem,
  type SpatialAttentionMarker,
  type SpatialCanonicalReference,
  type SpatialContextNode,
  type SpatialConversationTurn,
  type SpatialDiscoveryResult,
  type SpatialEndpointDetails,
  type SpatialGeneratedObject,
  type SpatialIntentEnvelope,
  type SpatialInteractionProvenance,
  type SpatialNodeStatus,
  type SpatialRecoveryCommand,
  type SpatialRecoveryResult,
  type SpatialEndpointProvenance,
  type SpatialRemoteContextManifest,
  type SpatialRemoteRequest,
  type SpatialRemoteResult,
  type SpatialEndpointTestFrame,
  type SpatialResourceAccounting,
  type SpatialMemoryLayout,
  type SpatialMemoryProjection,
  type SpatialMemoryCluster,
  type SpatialMemoryFocus,
  type SpatialMemorySearch,
  type SpatialMemoryVirtualization,
  type SpatialWorkspaceWorld,
  type SpatialDeviceViewport,
  type SpatialPresentationGeometry,
  type SpatialWorkspaceMutation,
  type SpatialWorkspaceMutationResult,
  type SpatialOfflineQueue,
  type SpatialShareView,
  type SpatialChangeIntent,
  type SpatialResultModel,
  type SpatialComponentFrame,
  type SpatialResourceSummary,
  type SpatialActionFeedback,
  type SpatialPrimaryAgentGrant,
  type SpatialPrimaryAgentSlot,
  type SpatialPrimaryAgentState,
  type SpatialRelationContract,
  type SpatialSemanticRelation,
  type SpatialSubagentLifecycle,
  type SpatialPresentationIntent,
  type SpatialPresentationResult,
  type SpatialWorkspaceSnapshot,
  type SpatialWorkspaceSession,
} from '@/spatial/contracts'

import type { SpatialNodeScope } from './scope'

export const SPATIAL_EVENT_TYPES = [
  'spatial.workspace.updated.v1',
  'spatial.entity.upserted.v1',
  'spatial.entity.archived.v1',
  'spatial.relation.upserted.v1',
  'spatial.node-status.changed.v1',
  'spatial.recovery.command-planned.v1',
  'spatial.recovery.resulted.v1',
  'spatial.endpoint-provenance.updated.v1',
  'spatial.remote.context-manifest.updated.v1',
  'spatial.remote.requested.v1',
  'spatial.remote.resulted.v1',
  'spatial.endpoint-test-frame.updated.v1',
  'spatial.resource-accounting.updated.v1',
  'spatial.primary-agent.binding-changed.v1',
  'spatial.primary-agent.grant-changed.v1',
  'spatial.primary-agent.state-changed.v1',
  'spatial.intent.accepted.v1',
  'spatial.session.updated.v1',
  'spatial.context.updated.v1',
  'spatial.conversation.turn-updated.v1',
  'spatial.generated-object.updated.v1',
  'spatial.artifact.created.v1',
  'spatial.presentation.requested.v1',
  'spatial.presentation.resolved.v1',
  'spatial.canonical-reference.upserted.v1',
  'spatial.endpoint-details.updated.v1',
  'spatial.discovery.updated.v1',
  'spatial.semantic-relation.updated.v1',
  'spatial.subagent.lifecycle-updated.v1',
  'spatial.interaction.provenance-recorded.v1',
  'spatial.attention.raised.v1',
  'spatial.attention.resolved.v1',
  'spatial.attention.item-updated.v1',
  'spatial.attention.marker-updated.v1',
  'spatial.attention.focus-updated.v1',
  'spatial.memory.layout-updated.v1',
  'spatial.memory.projection-updated.v1',
  'spatial.memory.cluster-updated.v1',
  'spatial.memory.focus-updated.v1',
  'spatial.memory.search-completed.v1',
  'spatial.memory.virtualization-updated.v1',
  'spatial.workspace-world.updated.v1',
  'spatial.device-viewport.updated.v1',
  'spatial.presentation-geometry.updated.v1',
  'spatial.workspace-mutation.requested.v1',
  'spatial.workspace-mutation.resolved.v1',
  'spatial.offline-queue.updated.v1',
  'spatial.share-view.updated.v1',
  'spatial.change-intent.created.v1',
  'spatial.change-intent.resolved.v1',
  'spatial.result-model.updated.v1',
  'spatial.component-frame.updated.v1',
  'spatial.resource-summary.updated.v1',
  'spatial.action-feedback.updated.v1',
] as const

export type SpatialEventType = (typeof SPATIAL_EVENT_TYPES)[number]

const eventEnvelopeBase = {
  event_id: spatialIdSchema,
  event_type: z.string().min(1).max(160),
  schema_version: z.string().min(1).max(160),
  node_id: spatialIdSchema,
  sequence: spatialRevisionSchema,
  revision: spatialRevisionSchema,
  occurred_at: spatialTimestampSchema,
  correlation_id: spatialIdSchema.nullable(),
  causation_id: spatialIdSchema.nullable(),
  payload: z.unknown(),
}

export const spatialEventEnvelopeSchema = z.object(eventEnvelopeBase).strip()
export type SpatialEventEnvelope = z.infer<typeof spatialEventEnvelopeSchema>

export type SpatialEventPayload = SpatialWorkspaceSnapshot | SpatialCanonicalEntity | SpatialRelationContract | SpatialNodeStatus | SpatialRecoveryCommand | SpatialRecoveryResult | SpatialEndpointProvenance | SpatialRemoteContextManifest | SpatialRemoteRequest | SpatialRemoteResult | SpatialEndpointTestFrame | SpatialResourceAccounting | SpatialMemoryLayout | SpatialMemoryProjection | SpatialMemoryCluster | SpatialMemoryFocus | SpatialMemorySearch | SpatialMemoryVirtualization | SpatialWorkspaceWorld | SpatialDeviceViewport | SpatialPresentationGeometry | SpatialWorkspaceMutation | SpatialWorkspaceMutationResult | SpatialOfflineQueue | SpatialShareView | SpatialPrimaryAgentSlot | SpatialPrimaryAgentGrant | SpatialPrimaryAgentState | SpatialIntentEnvelope | SpatialWorkspaceSession | SpatialContextNode | SpatialConversationTurn | SpatialGeneratedObject | SpatialArtifact | SpatialPresentationIntent | SpatialPresentationResult | SpatialCanonicalReference | SpatialEndpointDetails | SpatialDiscoveryResult | SpatialSemanticRelation | SpatialSubagentLifecycle | SpatialInteractionProvenance | SpatialAttentionItem | SpatialAttentionMarker | SpatialAttentionFocus | SpatialChangeIntent | SpatialResultModel | SpatialComponentFrame | SpatialResourceSummary | SpatialActionFeedback

export type SpatialTypedEvent = SpatialEventEnvelope & {
  event_type: SpatialEventType
  payload: SpatialEventPayload
}

export type SpatialEventDiagnosticCode = 'MALFORMED_EVENT' | 'UNKNOWN_EVENT' | 'STALE_EVENT' | 'DUPLICATE_EVENT'

export type SpatialEventDiagnostic = {
  code: SpatialEventDiagnosticCode
  event_id?: string
  event_type?: string
  node_id?: string
  path?: string
}

export type SpatialEventParseResult =
  | { ok: true; event: SpatialTypedEvent }
  | { ok: false; diagnostic: SpatialEventDiagnostic }

function parsePayload(event: SpatialEventEnvelope): SpatialEventParseResult {
  switch (event.event_type) {
    case 'spatial.workspace.updated.v1': {
      const parsed = parseSpatialWorkspace(event.payload)
      return parsed.ok
        ? { ok: true, event: { ...event, event_type: event.event_type, payload: parsed.data } }
        : { ok: false, diagnostic: { code: 'MALFORMED_EVENT', event_id: event.event_id, event_type: event.event_type, node_id: event.node_id, path: parsed.diagnostic.path } }
    }
    case 'spatial.entity.upserted.v1':
    case 'spatial.entity.archived.v1': {
      const parsed = parseSpatialEntity(event.payload)
      return parsed.ok
        ? { ok: true, event: { ...event, event_type: event.event_type, payload: parsed.data } }
        : { ok: false, diagnostic: { code: 'MALFORMED_EVENT', event_id: event.event_id, event_type: event.event_type, node_id: event.node_id, path: parsed.diagnostic.path } }
    }
    case 'spatial.relation.upserted.v1': {
      const parsed = parseSpatialRelation(event.payload)
      return parsed.ok
        ? { ok: true, event: { ...event, event_type: event.event_type, payload: parsed.data } }
        : { ok: false, diagnostic: { code: 'MALFORMED_EVENT', event_id: event.event_id, event_type: event.event_type, node_id: event.node_id, path: parsed.diagnostic.path } }
    }
    case 'spatial.node-status.changed.v1': {
      const parsed = parseSpatialNodeStatus(event.payload)
      return parsed.ok
        ? { ok: true, event: { ...event, event_type: event.event_type, payload: parsed.data } }
        : { ok: false, diagnostic: { code: 'MALFORMED_EVENT', event_id: event.event_id, event_type: event.event_type, node_id: event.node_id, path: parsed.diagnostic.path } }
    }
    case 'spatial.recovery.command-planned.v1': {
      const parsed = parseSpatialRecoveryCommand(event.payload)
      return parsed.ok
        ? { ok: true, event: { ...event, event_type: event.event_type, payload: parsed.data } }
        : { ok: false, diagnostic: { code: 'MALFORMED_EVENT', event_id: event.event_id, event_type: event.event_type, node_id: event.node_id, path: parsed.diagnostic.path } }
    }
    case 'spatial.recovery.resulted.v1': {
      const parsed = parseSpatialRecoveryResult(event.payload)
      return parsed.ok
        ? { ok: true, event: { ...event, event_type: event.event_type, payload: parsed.data } }
        : { ok: false, diagnostic: { code: 'MALFORMED_EVENT', event_id: event.event_id, event_type: event.event_type, node_id: event.node_id, path: parsed.diagnostic.path } }
    }
    case 'spatial.endpoint-provenance.updated.v1': {
      const parsed = parseSpatialEndpointProvenance(event.payload)
      return parsed.ok
        ? { ok: true, event: { ...event, event_type: event.event_type, payload: parsed.data } }
        : { ok: false, diagnostic: { code: 'MALFORMED_EVENT', event_id: event.event_id, event_type: event.event_type, node_id: event.node_id, path: parsed.diagnostic.path } }
    }
    case 'spatial.remote.context-manifest.updated.v1': {
      const parsed = parseSpatialRemoteContextManifest(event.payload)
      return parsed.ok
        ? { ok: true, event: { ...event, event_type: event.event_type, payload: parsed.data } }
        : { ok: false, diagnostic: { code: 'MALFORMED_EVENT', event_id: event.event_id, event_type: event.event_type, node_id: event.node_id, path: parsed.diagnostic.path } }
    }
    case 'spatial.remote.requested.v1': {
      const parsed = parseSpatialRemoteRequest(event.payload)
      return parsed.ok
        ? { ok: true, event: { ...event, event_type: event.event_type, payload: parsed.data } }
        : { ok: false, diagnostic: { code: 'MALFORMED_EVENT', event_id: event.event_id, event_type: event.event_type, node_id: event.node_id, path: parsed.diagnostic.path } }
    }
    case 'spatial.remote.resulted.v1': {
      const parsed = parseSpatialRemoteResult(event.payload)
      return parsed.ok
        ? { ok: true, event: { ...event, event_type: event.event_type, payload: parsed.data } }
        : { ok: false, diagnostic: { code: 'MALFORMED_EVENT', event_id: event.event_id, event_type: event.event_type, node_id: event.node_id, path: parsed.diagnostic.path } }
    }
    case 'spatial.endpoint-test-frame.updated.v1': {
      const parsed = parseSpatialEndpointTestFrame(event.payload)
      return parsed.ok
        ? { ok: true, event: { ...event, event_type: event.event_type, payload: parsed.data } }
        : { ok: false, diagnostic: { code: 'MALFORMED_EVENT', event_id: event.event_id, event_type: event.event_type, node_id: event.node_id, path: parsed.diagnostic.path } }
    }
    case 'spatial.resource-accounting.updated.v1': {
      const parsed = parseSpatialResourceAccounting(event.payload)
      return parsed.ok
        ? { ok: true, event: { ...event, event_type: event.event_type, payload: parsed.data } }
        : { ok: false, diagnostic: { code: 'MALFORMED_EVENT', event_id: event.event_id, event_type: event.event_type, node_id: event.node_id, path: parsed.diagnostic.path } }
    }
    case 'spatial.primary-agent.binding-changed.v1': {
      const parsed = parseSpatialPrimaryAgentSlot(event.payload)
      return parsed.ok
        ? { ok: true, event: { ...event, event_type: event.event_type, payload: parsed.data } }
        : { ok: false, diagnostic: { code: 'MALFORMED_EVENT', event_id: event.event_id, event_type: event.event_type, node_id: event.node_id, path: parsed.diagnostic.path } }
    }
    case 'spatial.primary-agent.grant-changed.v1': {
      const parsed = parseSpatialPrimaryAgentGrant(event.payload)
      return parsed.ok
        ? { ok: true, event: { ...event, event_type: event.event_type, payload: parsed.data } }
        : { ok: false, diagnostic: { code: 'MALFORMED_EVENT', event_id: event.event_id, event_type: event.event_type, node_id: event.node_id, path: parsed.diagnostic.path } }
    }
    case 'spatial.primary-agent.state-changed.v1': {
      const parsed = parseSpatialPrimaryAgentState(event.payload)
      return parsed.ok
        ? { ok: true, event: { ...event, event_type: event.event_type, payload: parsed.data } }
        : { ok: false, diagnostic: { code: 'MALFORMED_EVENT', event_id: event.event_id, event_type: event.event_type, node_id: event.node_id, path: parsed.diagnostic.path } }
    }
    case 'spatial.intent.accepted.v1': {
      const parsed = parseSpatialIntentEnvelope(event.payload)
      return parsed.ok
        ? { ok: true, event: { ...event, event_type: event.event_type, payload: parsed.data } }
        : { ok: false, diagnostic: { code: 'MALFORMED_EVENT', event_id: event.event_id, event_type: event.event_type, node_id: event.node_id, path: parsed.diagnostic.path } }
    }
    case 'spatial.session.updated.v1': {
      const parsed = parseSpatialWorkspaceSession(event.payload)
      return parsed.ok
        ? { ok: true, event: { ...event, event_type: event.event_type, payload: parsed.data } }
        : { ok: false, diagnostic: { code: 'MALFORMED_EVENT', event_id: event.event_id, event_type: event.event_type, node_id: event.node_id, path: parsed.diagnostic.path } }
    }
    case 'spatial.context.updated.v1': {
      const parsed = parseSpatialContextNode(event.payload)
      return parsed.ok
        ? { ok: true, event: { ...event, event_type: event.event_type, payload: parsed.data } }
        : { ok: false, diagnostic: { code: 'MALFORMED_EVENT', event_id: event.event_id, event_type: event.event_type, node_id: event.node_id, path: parsed.diagnostic.path } }
    }
    case 'spatial.conversation.turn-updated.v1': {
      const parsed = parseSpatialConversationTurn(event.payload)
      return parsed.ok
        ? { ok: true, event: { ...event, event_type: event.event_type, payload: parsed.data } }
        : { ok: false, diagnostic: { code: 'MALFORMED_EVENT', event_id: event.event_id, event_type: event.event_type, node_id: event.node_id, path: parsed.diagnostic.path } }
    }
    case 'spatial.generated-object.updated.v1': {
      const parsed = parseSpatialGeneratedObject(event.payload)
      return parsed.ok
        ? { ok: true, event: { ...event, event_type: event.event_type, payload: parsed.data } }
        : { ok: false, diagnostic: { code: 'MALFORMED_EVENT', event_id: event.event_id, event_type: event.event_type, node_id: event.node_id, path: parsed.diagnostic.path } }
    }
    case 'spatial.artifact.created.v1': {
      const parsed = parseSpatialArtifact(event.payload)
      return parsed.ok
        ? { ok: true, event: { ...event, event_type: event.event_type, payload: parsed.data } }
        : { ok: false, diagnostic: { code: 'MALFORMED_EVENT', event_id: event.event_id, event_type: event.event_type, node_id: event.node_id, path: parsed.diagnostic.path } }
    }
    case 'spatial.presentation.requested.v1': {
      const parsed = parseSpatialPresentationIntent(event.payload)
      return parsed.ok
        ? { ok: true, event: { ...event, event_type: event.event_type, payload: parsed.data } }
        : { ok: false, diagnostic: { code: 'MALFORMED_EVENT', event_id: event.event_id, event_type: event.event_type, node_id: event.node_id, path: parsed.diagnostic.path } }
    }
    case 'spatial.presentation.resolved.v1': {
      const parsed = parseSpatialPresentationResult(event.payload)
      return parsed.ok
        ? { ok: true, event: { ...event, event_type: event.event_type, payload: parsed.data } }
        : { ok: false, diagnostic: { code: 'MALFORMED_EVENT', event_id: event.event_id, event_type: event.event_type, node_id: event.node_id, path: parsed.diagnostic.path } }
    }
    case 'spatial.canonical-reference.upserted.v1': {
      const parsed = parseSpatialCanonicalReference(event.payload)
      return parsed.ok
        ? { ok: true, event: { ...event, event_type: event.event_type, payload: parsed.data } }
        : { ok: false, diagnostic: { code: 'MALFORMED_EVENT', event_id: event.event_id, event_type: event.event_type, node_id: event.node_id, path: parsed.diagnostic.path } }
    }
    case 'spatial.endpoint-details.updated.v1': {
      const parsed = parseSpatialEndpointDetails(event.payload)
      return parsed.ok
        ? { ok: true, event: { ...event, event_type: event.event_type, payload: parsed.data } }
        : { ok: false, diagnostic: { code: 'MALFORMED_EVENT', event_id: event.event_id, event_type: event.event_type, node_id: event.node_id, path: parsed.diagnostic.path } }
    }
    case 'spatial.discovery.updated.v1': {
      const parsed = parseSpatialDiscoveryResult(event.payload)
      return parsed.ok
        ? { ok: true, event: { ...event, event_type: event.event_type, payload: parsed.data } }
        : { ok: false, diagnostic: { code: 'MALFORMED_EVENT', event_id: event.event_id, event_type: event.event_type, node_id: event.node_id, path: parsed.diagnostic.path } }
    }
    case 'spatial.semantic-relation.updated.v1': {
      const parsed = parseSpatialSemanticRelation(event.payload)
      return parsed.ok
        ? { ok: true, event: { ...event, event_type: event.event_type, payload: parsed.data } }
        : { ok: false, diagnostic: { code: 'MALFORMED_EVENT', event_id: event.event_id, event_type: event.event_type, node_id: event.node_id, path: parsed.diagnostic.path } }
    }
    case 'spatial.subagent.lifecycle-updated.v1': {
      const parsed = parseSpatialSubagentLifecycle(event.payload)
      return parsed.ok
        ? { ok: true, event: { ...event, event_type: event.event_type, payload: parsed.data } }
        : { ok: false, diagnostic: { code: 'MALFORMED_EVENT', event_id: event.event_id, event_type: event.event_type, node_id: event.node_id, path: parsed.diagnostic.path } }
    }
    case 'spatial.interaction.provenance-recorded.v1': {
      const parsed = parseSpatialInteractionProvenance(event.payload)
      return parsed.ok
        ? { ok: true, event: { ...event, event_type: event.event_type, payload: parsed.data } }
        : { ok: false, diagnostic: { code: 'MALFORMED_EVENT', event_id: event.event_id, event_type: event.event_type, node_id: event.node_id, path: parsed.diagnostic.path } }
    }
    case 'spatial.attention.raised.v1':
    case 'spatial.attention.resolved.v1':
    case 'spatial.attention.item-updated.v1': {
      const parsed = parseSpatialAttentionItem(event.payload)
      return parsed.ok
        ? { ok: true, event: { ...event, event_type: event.event_type, payload: parsed.data } }
        : { ok: false, diagnostic: { code: 'MALFORMED_EVENT', event_id: event.event_id, event_type: event.event_type, node_id: event.node_id, path: parsed.diagnostic.path } }
    }
    case 'spatial.attention.marker-updated.v1': {
      const parsed = parseSpatialAttentionMarker(event.payload)
      return parsed.ok
        ? { ok: true, event: { ...event, event_type: event.event_type, payload: parsed.data } }
        : { ok: false, diagnostic: { code: 'MALFORMED_EVENT', event_id: event.event_id, event_type: event.event_type, node_id: event.node_id, path: parsed.diagnostic.path } }
    }
    case 'spatial.attention.focus-updated.v1': {
      const parsed = parseSpatialAttentionFocus(event.payload)
      return parsed.ok
        ? { ok: true, event: { ...event, event_type: event.event_type, payload: parsed.data } }
        : { ok: false, diagnostic: { code: 'MALFORMED_EVENT', event_id: event.event_id, event_type: event.event_type, node_id: event.node_id, path: parsed.diagnostic.path } }
    }
    case 'spatial.memory.layout-updated.v1': {
      const parsed = parseSpatialMemoryLayout(event.payload)
      return parsed.ok
        ? { ok: true, event: { ...event, event_type: event.event_type, payload: parsed.data } }
        : { ok: false, diagnostic: { code: 'MALFORMED_EVENT', event_id: event.event_id, event_type: event.event_type, node_id: event.node_id, path: parsed.diagnostic.path } }
    }
    case 'spatial.memory.projection-updated.v1': {
      const parsed = parseSpatialMemoryProjection(event.payload)
      return parsed.ok
        ? { ok: true, event: { ...event, event_type: event.event_type, payload: parsed.data } }
        : { ok: false, diagnostic: { code: 'MALFORMED_EVENT', event_id: event.event_id, event_type: event.event_type, node_id: event.node_id, path: parsed.diagnostic.path } }
    }
    case 'spatial.memory.cluster-updated.v1': {
      const parsed = parseSpatialMemoryCluster(event.payload)
      return parsed.ok
        ? { ok: true, event: { ...event, event_type: event.event_type, payload: parsed.data } }
        : { ok: false, diagnostic: { code: 'MALFORMED_EVENT', event_id: event.event_id, event_type: event.event_type, node_id: event.node_id, path: parsed.diagnostic.path } }
    }
    case 'spatial.memory.focus-updated.v1': {
      const parsed = parseSpatialMemoryFocus(event.payload)
      return parsed.ok
        ? { ok: true, event: { ...event, event_type: event.event_type, payload: parsed.data } }
        : { ok: false, diagnostic: { code: 'MALFORMED_EVENT', event_id: event.event_id, event_type: event.event_type, node_id: event.node_id, path: parsed.diagnostic.path } }
    }
    case 'spatial.memory.search-completed.v1': {
      const parsed = parseSpatialMemorySearch(event.payload)
      return parsed.ok
        ? { ok: true, event: { ...event, event_type: event.event_type, payload: parsed.data } }
        : { ok: false, diagnostic: { code: 'MALFORMED_EVENT', event_id: event.event_id, event_type: event.event_type, node_id: event.node_id, path: parsed.diagnostic.path } }
    }
    case 'spatial.memory.virtualization-updated.v1': {
      const parsed = parseSpatialMemoryVirtualization(event.payload)
      return parsed.ok
        ? { ok: true, event: { ...event, event_type: event.event_type, payload: parsed.data } }
        : { ok: false, diagnostic: { code: 'MALFORMED_EVENT', event_id: event.event_id, event_type: event.event_type, node_id: event.node_id, path: parsed.diagnostic.path } }
    }
    case 'spatial.workspace-world.updated.v1': {
      const parsed = parseSpatialWorkspaceWorld(event.payload)
      return parsed.ok
        ? { ok: true, event: { ...event, event_type: event.event_type, payload: parsed.data } }
        : { ok: false, diagnostic: { code: 'MALFORMED_EVENT', event_id: event.event_id, event_type: event.event_type, node_id: event.node_id, path: parsed.diagnostic.path } }
    }
    case 'spatial.device-viewport.updated.v1': {
      const parsed = parseSpatialDeviceViewport(event.payload)
      return parsed.ok
        ? { ok: true, event: { ...event, event_type: event.event_type, payload: parsed.data } }
        : { ok: false, diagnostic: { code: 'MALFORMED_EVENT', event_id: event.event_id, event_type: event.event_type, node_id: event.node_id, path: parsed.diagnostic.path } }
    }
    case 'spatial.presentation-geometry.updated.v1': {
      const parsed = parseSpatialPresentationGeometry(event.payload)
      return parsed.ok
        ? { ok: true, event: { ...event, event_type: event.event_type, payload: parsed.data } }
        : { ok: false, diagnostic: { code: 'MALFORMED_EVENT', event_id: event.event_id, event_type: event.event_type, node_id: event.node_id, path: parsed.diagnostic.path } }
    }
    case 'spatial.workspace-mutation.requested.v1': {
      const parsed = parseSpatialWorkspaceMutation(event.payload)
      return parsed.ok
        ? { ok: true, event: { ...event, event_type: event.event_type, payload: parsed.data } }
        : { ok: false, diagnostic: { code: 'MALFORMED_EVENT', event_id: event.event_id, event_type: event.event_type, node_id: event.node_id, path: parsed.diagnostic.path } }
    }
    case 'spatial.workspace-mutation.resolved.v1': {
      const parsed = parseSpatialWorkspaceMutationResult(event.payload)
      return parsed.ok
        ? { ok: true, event: { ...event, event_type: event.event_type, payload: parsed.data } }
        : { ok: false, diagnostic: { code: 'MALFORMED_EVENT', event_id: event.event_id, event_type: event.event_type, node_id: event.node_id, path: parsed.diagnostic.path } }
    }
    case 'spatial.offline-queue.updated.v1': {
      const parsed = parseSpatialOfflineQueue(event.payload)
      return parsed.ok
        ? { ok: true, event: { ...event, event_type: event.event_type, payload: parsed.data } }
        : { ok: false, diagnostic: { code: 'MALFORMED_EVENT', event_id: event.event_id, event_type: event.event_type, node_id: event.node_id, path: parsed.diagnostic.path } }
    }
    case 'spatial.share-view.updated.v1': {
      const parsed = parseSpatialShareView(event.payload)
      return parsed.ok
        ? { ok: true, event: { ...event, event_type: event.event_type, payload: parsed.data } }
        : { ok: false, diagnostic: { code: 'MALFORMED_EVENT', event_id: event.event_id, event_type: event.event_type, node_id: event.node_id, path: parsed.diagnostic.path } }
    }
    case 'spatial.change-intent.created.v1':
    case 'spatial.change-intent.resolved.v1': {
      const parsed = parseSpatialChangeIntent(event.payload)
      return parsed.ok
        ? { ok: true, event: { ...event, event_type: event.event_type, payload: parsed.data } }
        : { ok: false, diagnostic: { code: 'MALFORMED_EVENT', event_id: event.event_id, event_type: event.event_type, node_id: event.node_id, path: parsed.diagnostic.path } }
    }
    case 'spatial.result-model.updated.v1': {
      const parsed = parseSpatialResultModel(event.payload)
      return parsed.ok
        ? { ok: true, event: { ...event, event_type: event.event_type, payload: parsed.data } }
        : { ok: false, diagnostic: { code: 'MALFORMED_EVENT', event_id: event.event_id, event_type: event.event_type, node_id: event.node_id, path: parsed.diagnostic.path } }
    }
    case 'spatial.component-frame.updated.v1': {
      const parsed = parseSpatialComponentFrame(event.payload)
      return parsed.ok
        ? { ok: true, event: { ...event, event_type: event.event_type, payload: parsed.data } }
        : { ok: false, diagnostic: { code: 'MALFORMED_EVENT', event_id: event.event_id, event_type: event.event_type, node_id: event.node_id, path: parsed.diagnostic.path } }
    }
    case 'spatial.resource-summary.updated.v1': {
      const parsed = parseSpatialResourceSummary(event.payload)
      return parsed.ok
        ? { ok: true, event: { ...event, event_type: event.event_type, payload: parsed.data } }
        : { ok: false, diagnostic: { code: 'MALFORMED_EVENT', event_id: event.event_id, event_type: event.event_type, node_id: event.node_id, path: parsed.diagnostic.path } }
    }
    case 'spatial.action-feedback.updated.v1': {
      const parsed = parseSpatialActionFeedback(event.payload)
      return parsed.ok
        ? { ok: true, event: { ...event, event_type: event.event_type, payload: parsed.data } }
        : { ok: false, diagnostic: { code: 'MALFORMED_EVENT', event_id: event.event_id, event_type: event.event_type, node_id: event.node_id, path: parsed.diagnostic.path } }
    }
    default:
      return { ok: false, diagnostic: { code: 'UNKNOWN_EVENT', event_id: event.event_id, event_type: event.event_type, node_id: event.node_id } }
  }
}

export function parseSpatialEventEnvelope(payload: unknown): SpatialEventParseResult {
  const parsed = spatialEventEnvelopeSchema.safeParse(payload)
  if (!parsed.success) {
    return { ok: false, diagnostic: { code: 'MALFORMED_EVENT', path: parsed.error.issues[0]?.path.join('.') || '<root>' } }
  }
  return parsePayload(parsed.data)
}

export type SpatialEventGatewayOptions = {
  scope: SpatialNodeScope
  onStateUpdate?: (event: SpatialTypedEvent) => void
  onNotification?: (event: SpatialTypedEvent) => void
  onDiagnostic?: (diagnostic: SpatialEventDiagnostic) => void
}

export type SpatialEventIngestResult =
  | { status: 'applied'; event: SpatialTypedEvent }
  | { status: 'duplicate' | 'stale' | 'unknown' | 'malformed'; diagnostic: SpatialEventDiagnostic }

function eventResourceKey(event: SpatialTypedEvent): string {
  const payload = event.payload
  if ('discovery_id' in payload) return `discovery:${payload.discovery_id}`
  if ('attention_id' in payload) return `attention:${payload.attention_id}`
  if ('marker_id' in payload) return `marker:${payload.marker_id}`
  if ('focus_id' in payload) return `focus:${payload.focus_id}`
  if ('projection_id' in payload) return `memory-projection:${payload.projection_id}`
  if ('cluster_id' in payload) return `memory-cluster:${payload.cluster_id}`
  if ('search_id' in payload) return `memory-search:${payload.search_id}`
  if ('record_id' in payload) return `provenance:${payload.record_id}`
  if ('result_id' in payload) return `remote-result:${payload.result_id}`
  if ('request_id' in payload) return `remote-request:${payload.request_id}`
  if ('frame_id' in payload && event.event_type === 'spatial.endpoint-test-frame.updated.v1') return `endpoint-test-frame:${payload.frame_id}`
  if ('manifest_id' in payload) return `context-manifest:${payload.manifest_id}`
  if ('provenance_id' in payload) return `endpoint-provenance:${payload.provenance_id}`
  if ('subagent_ref' in payload) return `subagent:${payload.subagent_ref}`
  if ('relation_id' in payload) return `relation:${payload.relation_id}`
  if ('canonical_ref' in payload) return `entity:${payload.canonical_ref}`
  if ('slot_id' in payload) return `primary-agent-slot:${payload.slot_id}`
  if ('grant_id' in payload) return `primary-agent-grant:${payload.grant_id}`
  if ('share_id' in payload) return `share-view:${payload.share_id}`
  if ('intent_id' in payload) return `change-intent:${payload.intent_id}`
  if ('summary_id' in payload) return `resource-summary:${payload.summary_id}`
  if ('feedback_id' in payload) return `action-feedback:${payload.feedback_id}`
  if ('frame_id' in payload) return `component-frame:${payload.frame_id}`
  if ('operation_id' in payload) return `workspace-operation:${payload.operation_id}`
  if ('device_id' in payload) return `device-viewport:${payload.device_id}`
  if ('workspace_id' in payload) return `workspace:${payload.workspace_id}`
  if ('command_id' in payload) return `recovery:${payload.command_id}`
  return `node-status:${event.node_id}`
}

function assertScope(scope: SpatialNodeScope, nodeId: string): boolean {
  return scope.node_id === nodeId
}

function payloadNodeId(payload: SpatialEventPayload): string | undefined {
  if ('node_id' in payload) return payload.node_id
  if ('local_node_id' in payload) return payload.local_node_id
  if ('provenance' in payload && typeof payload.provenance === 'object' && payload.provenance !== null && 'node_id' in payload.provenance && typeof payload.provenance.node_id === 'string') return payload.provenance.node_id
  return undefined
}

/**
 * State adapter between retained Node events and Query/view-model consumers.
 * It never imports or calls a renderer; callbacks receive validated typed data.
 */
export class SpatialEventGateway {
  private readonly scope: SpatialNodeScope
  private readonly onStateUpdate?: (event: SpatialTypedEvent) => void
  private readonly onNotification?: (event: SpatialTypedEvent) => void
  private readonly onDiagnostic?: (diagnostic: SpatialEventDiagnostic) => void
  private readonly seenEventIds = new Set<string>()
  private readonly resourceRevisions = new Map<string, number>()
  private lastSequence = 0
  private resumeCursor: string | null = null

  constructor(options: SpatialEventGatewayOptions) {
    this.scope = options.scope
    this.onStateUpdate = options.onStateUpdate
    this.onNotification = options.onNotification
    this.onDiagnostic = options.onDiagnostic
  }

  ingest(payload: unknown): SpatialEventIngestResult {
    const parsed = parseSpatialEventEnvelope(payload)
    if (!parsed.ok) {
      this.onDiagnostic?.(parsed.diagnostic)
      return { status: parsed.diagnostic.code === 'UNKNOWN_EVENT' ? 'unknown' : 'malformed', diagnostic: parsed.diagnostic }
    }
    const event = parsed.event
    if (!assertScope(this.scope, event.node_id)) {
      const diagnostic = { code: 'STALE_EVENT' as const, event_id: event.event_id, event_type: event.event_type, node_id: event.node_id, path: 'node_id' }
      this.onDiagnostic?.(diagnostic)
      return { status: 'stale', diagnostic }
    }
    if (payloadNodeId(event.payload) !== event.node_id) {
      const diagnostic = { code: 'STALE_EVENT' as const, event_id: event.event_id, event_type: event.event_type, node_id: event.node_id, path: 'payload.node_id' }
      this.onDiagnostic?.(diagnostic)
      return { status: 'stale', diagnostic }
    }
    if (this.seenEventIds.has(event.event_id)) {
      const diagnostic = { code: 'DUPLICATE_EVENT' as const, event_id: event.event_id, event_type: event.event_type, node_id: event.node_id }
      this.onDiagnostic?.(diagnostic)
      return { status: 'duplicate', diagnostic }
    }
    const resourceKey = eventResourceKey(event)
    const currentRevision = this.resourceRevisions.get(resourceKey) ?? -1
    if (event.revision < currentRevision || event.sequence < this.lastSequence) {
      const diagnostic = { code: 'STALE_EVENT' as const, event_id: event.event_id, event_type: event.event_type, node_id: event.node_id, path: 'revision' }
      this.onDiagnostic?.(diagnostic)
      return { status: 'stale', diagnostic }
    }

    this.seenEventIds.add(event.event_id)
    this.resourceRevisions.set(resourceKey, Math.max(currentRevision, event.revision))
    this.lastSequence = Math.max(this.lastSequence, event.sequence)
    this.resumeCursor = String(event.sequence)
    this.onStateUpdate?.(event)
    this.onNotification?.(event)
    return { status: 'applied', event }
  }

  replay(retainedEvents: readonly unknown[]): SpatialEventIngestResult[] {
    return retainedEvents.map((event) => this.ingest(event))
  }

  connect(adapter: SpatialEventStreamAdapter): SpatialEventStreamConnection {
    return adapter.connect({
      scope: this.scope,
      resumeCursor: this.resumeCursor,
      onMessage: (payload) => {
        this.ingest(payload)
      },
      onClose: () => undefined,
      onError: () => undefined,
    })
  }

  getResumeCursor(): string | null {
    return this.resumeCursor
  }
}

export function createSpatialEventGateway(options: SpatialEventGatewayOptions): SpatialEventGateway {
  return new SpatialEventGateway(options)
}

export const SPATIAL_RECONNECT_BACKOFF_MS = [250, 500, 1_000, 2_000, 4_000, 8_000] as const

export function spatialReconnectDelay(attempt: number): number {
  const index = Math.max(0, Math.min(SPATIAL_RECONNECT_BACKOFF_MS.length - 1, Math.floor(attempt)))
  return SPATIAL_RECONNECT_BACKOFF_MS[index]
}

export type SpatialEventStreamConnection = {
  close: () => void
}

export type SpatialEventStreamAdapter = {
  connect: (options: {
    scope: SpatialNodeScope
    resumeCursor: string | null
    onMessage: (payload: unknown) => void
    onClose: () => void
    onError: (error: unknown) => void
  }) => SpatialEventStreamConnection
}

export type SpatialReconnectingAdapterOptions = {
  maxAttempts?: number
  scheduler?: (callback: () => void, delayMs: number) => ReturnType<typeof setTimeout>
  cancelScheduler?: (handle: ReturnType<typeof setTimeout>) => void
}

/**
 * Adds a bounded reconnect loop around any compatible stream transport. The
 * retained cursor is advanced only from envelope metadata, so a reconnect
 * always asks the Node for the events after the last accepted sequence.
 */
export function createReconnectingSpatialEventStreamAdapter(
  adapter: SpatialEventStreamAdapter,
  options: SpatialReconnectingAdapterOptions = {},
): SpatialEventStreamAdapter {
  const maxAttempts = Math.max(0, options.maxAttempts ?? Number.POSITIVE_INFINITY)
  const schedule = options.scheduler ?? ((callback, delayMs) => setTimeout(callback, delayMs))
  const cancel = options.cancelScheduler ?? ((handle) => clearTimeout(handle))
  return {
    connect(connectOptions) {
      let closed = false
      let attempts = 0
      let cursor = connectOptions.resumeCursor
      let timer: ReturnType<typeof setTimeout> | null = null
      let active: SpatialEventStreamConnection | null = null
      const scheduleReconnect = () => {
        if (closed || timer || attempts >= maxAttempts) return
        const delay = spatialReconnectDelay(attempts)
        attempts += 1
        timer = schedule(() => {
          timer = null
          connect()
        }, delay)
      }
      const connect = () => {
        if (closed) return
        active = adapter.connect({
          ...connectOptions,
          resumeCursor: cursor,
          onMessage: (payload) => {
            const envelope = spatialEventEnvelopeSchema.safeParse(payload)
            if (envelope.success) cursor = String(envelope.data.sequence)
            connectOptions.onMessage(payload)
          },
          onClose: scheduleReconnect,
          onError: connectOptions.onError,
        })
      }
      connect()
      return {
        close: () => {
          closed = true
          if (timer) {
            cancel(timer)
            timer = null
          }
          active?.close()
          active = null
        },
      }
    },
  }
}

export const createResilientSpatialEventStreamAdapter = createReconnectingSpatialEventStreamAdapter

export function createWebSocketSpatialEventAdapter(socketFactory: (url: string) => WebSocket = (url) => new WebSocket(url), baseUrl = '/operators/spatial/events/stream'): SpatialEventStreamAdapter {
  return {
    connect({ scope, resumeCursor, onMessage, onClose, onError }) {
      const query = new URLSearchParams({ node_id: scope.node_id, hypervisor_id: scope.hypervisor_id })
      if (resumeCursor) query.set('after', resumeCursor)
      const socket = socketFactory(`${baseUrl}?${query.toString()}`)
      socket.addEventListener('message', (event) => {
        try {
          onMessage(JSON.parse(String(event.data)))
        } catch {
          onError(new Error('Spatial event stream returned invalid JSON.'))
        }
      })
      socket.addEventListener('close', onClose)
      socket.addEventListener('error', onError)
      return { close: () => socket.close() }
    },
  }
}
