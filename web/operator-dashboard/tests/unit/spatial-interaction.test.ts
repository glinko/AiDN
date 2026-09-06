import { describe, expect, it } from 'vitest'

import {
  DurableConversationService,
  GeneratedObjectService,
  IntentGateway,
  SessionArtifactService,
  SpatialComponentRegistry,
  SpatialPresentationPlanner,
  VoiceInteractionAdapter,
  WorkspaceSessionGraph,
  artifactTransition,
  createInteractionSeed,
  shouldOpenInteractionSeed,
} from '@/spatial/data'
import { parseSpatialIntentEnvelope, spatialIntentEnvelopeSchema, SPATIAL_SCHEMA_VERSIONS } from '@/spatial/contracts'

const now = () => new Date('2026-09-05T16:00:00.000Z')
const common = { workspaceId: 'workspace-test', nodeId: 'node-test', actorRef: 'operator:test' }

function expectCode(run: () => unknown, code: string) {
  try {
    run()
    throw new Error(`expected ${code}`)
  } catch (error) {
    expect(error).toMatchObject({ code })
  }
}

function createGateway(currentRevision = 3) {
  return new IntentGateway({ ...common, currentRevision, now, idFactory: (prefix) => `${prefix}-fixed` })
}

describe('Spatial M4 typed interaction contracts', () => {
  it('requires text or structured operation and keeps attachment bytes out of the envelope', () => {
    const empty = parseSpatialIntentEnvelope({
      schema_version: SPATIAL_SCHEMA_VERSIONS.intentEnvelope,
      intent_id: 'intent-empty', workspace_id: common.workspaceId, node_id: common.nodeId, actor_ref: common.actorRef,
      modality: 'text', intent_kind: 'message', text: '', operation: null, target_refs: [], parent_ref: null, context_refs: [],
      attachments_manifest: [], current_revision: 0, idempotency_key: 'empty', created_at: now().toISOString(),
    })
    expect(empty.ok).toBe(false)
    const parsed = spatialIntentEnvelopeSchema.parse({
      schema_version: SPATIAL_SCHEMA_VERSIONS.intentEnvelope,
      intent_id: 'intent-op', workspace_id: common.workspaceId, node_id: common.nodeId, actor_ref: common.actorRef,
      modality: 'form', intent_kind: 'change', text: null, operation: { action: 'inspect' }, target_refs: [], parent_ref: null, context_refs: [],
      attachments_manifest: [], current_revision: 0, idempotency_key: 'op', created_at: now().toISOString(), bytes: 'never',
    })
    expect(parsed.operation).toEqual({ action: 'inspect' })
    expect('bytes' in parsed).toBe(false)
  })

  it('enforces scope, stale revisions, authorization, limits and idempotency', () => {
    const gateway = new IntentGateway({ ...common, currentRevision: 4, maxTextLength: 10, authorize: (envelope) => envelope.actor_ref === common.actorRef, now, idFactory: (prefix) => `${prefix}-one` })
    expectCode(() => gateway.submit({ actor_ref: common.actorRef, workspace_id: 'wrong', modality: 'text', text: 'hello', idempotency_key: 'scope' }), 'WRONG_WORKSPACE')
    expectCode(() => gateway.submit({ actor_ref: common.actorRef, modality: 'text', text: 'this is too long', idempotency_key: 'large' }), 'OVERSIZED_INTENT')
    expectCode(() => gateway.submit({ actor_ref: common.actorRef, modality: 'text', text: 'hello', current_revision: 3, idempotency_key: 'stale' }), 'STALE_TARGET')
    expectCode(() => gateway.submit({ actor_ref: 'operator:denied', modality: 'text', text: 'hello', idempotency_key: 'denied' }), 'UNAUTHORIZED')
    const first = gateway.submit({ actor_ref: common.actorRef, modality: 'text', text: 'hello', idempotency_key: 'same' })
    const retry = gateway.submit({ actor_ref: common.actorRef, modality: 'text', text: 'hello', idempotency_key: 'same' })
    expect(retry.status).toBe('duplicate')
    expect(retry.envelope.intent_id).toBe(first.envelope.intent_id)
    expect(gateway.getAudit().at(-1)?.outcome).toBe('duplicate')
  })

  it('uses one seed for desktop/keyboard/mobile entry and never seeds from entity controls', () => {
    expect(shouldOpenInteractionSeed({ kind: 'entity', interactive: true })).toBe(false)
    expect(shouldOpenInteractionSeed({ kind: 'empty', interactive: false })).toBe(true)
    const seed = createInteractionSeed({ ...common, gateway: createGateway(), idFactory: (prefix) => `${prefix}-fixed` })
    expect(seed.getSnapshot().state).toBe('SEED')
    seed.beginComposition()
    seed.setText('inspect endpoint')
    const submission = seed.submit()
    expect(seed.getSnapshot().state).toBe('ACTIVE')
    expect(submission.envelope.modality).toBe('text')
    expect(seed.submit().envelope.intent_id).toBe(submission.envelope.intent_id)
  })
})

describe('Spatial M4 durable session and presentation path', () => {
  function services() {
    const graph = new WorkspaceSessionGraph({ ...common, now, idFactory: (prefix) => `${prefix}-fixed` })
    const gateway = createGateway(0)
    let bindingActive = true
    const conversation = new DurableConversationService({ graph, ...common, now, activeBinding: () => bindingActive, idFactory: (prefix) => `${prefix}-${Math.random().toString(36).slice(2, 6)}` })
    const objects = new GeneratedObjectService({ graph, ...common, now, idFactory: (prefix) => `${prefix}-fixed` })
    const artifacts = new SessionArtifactService({ graph, ...common, now, idFactory: (prefix) => `${prefix}-fixed` })
    return { graph, gateway, conversation, objects, artifacts, revokeBinding: () => { bindingActive = false } }
  }

  it('keeps one operator turn, bounded streaming, provenance and retry without duplicate prompt', () => {
    const { gateway, conversation, graph, revokeBinding } = services()
    const submission = gateway.submit({ actor_ref: common.actorRef, modality: 'text', text: 'summarize status', idempotency_key: 'conversation-1' })
    const exchange = conversation.submitIntent(submission, { bindingId: 'binding-one' })
    conversation.appendResponseChunk(exchange.exchange_id, '<b>ready</b>', 'binding-one')
    const complete = conversation.completeResponse(exchange.exchange_id, 'binding-one')
    expect(complete.response_text).toBe('ready')
    expect(conversation.listTurns(complete.session_id)).toHaveLength(2)
    const failed = conversation.failResponse(complete.exchange_id, 'TIMEOUT', 'binding-one')
    const retry = conversation.retry(failed.exchange_id)
    expect(retry.attempt).toBe(2)
    expect(conversation.listTurns(retry.session_id)).toHaveLength(3)
    expect(graph.listRelations().some((relation) => relation.type === 'PRODUCED')).toBe(true)
    revokeBinding()
    expectCode(() => conversation.appendResponseChunk(retry.exchange_id, 'old', 'binding-one'), 'BINDING_REJECTED')
  })

  it('prevents context cycles, preserves generated objects, and collapses to a restorable artifact', () => {
    const { gateway, conversation, graph, objects, artifacts } = services()
    const submission = gateway.submit({ actor_ref: common.actorRef, modality: 'text', text: 'make a report', idempotency_key: 'object-1' })
    const exchange = conversation.submitIntent(submission)
    conversation.appendResponseChunk(exchange.exchange_id, 'report body')
    const completed = conversation.completeResponse(exchange.exchange_id)
    const responseTurn = conversation.getTurn(completed.response_turn_id)!
    const object = objects.create({ sessionId: completed.session_id, sourceTurnId: responseTurn.turn_id, actorRef: common.actorRef, kind: 'REPORT', title: 'Report', data: { rows: 2 } })
    expect(object.source_turn_id).toBe(responseTurn.turn_id)
    const artifact = artifacts.collapse(completed.session_id, { actorRef: common.actorRef, cameraSnapshot: { focus_ref: object.semantic_anchor } })
    expect(artifact.object_refs).toContain(object.object_id)
    expect(graph.getSession(completed.session_id)?.state).toBe('COLLAPSED')
    artifacts.restore(artifact.artifact_id)
    expect(graph.getSession(completed.session_id)?.state).toBe('ACTIVE')
    expect(artifactTransition(true)).toBe('none')
    expectCode(() => graph.addRelation({ type: 'CONTINUES_FROM', sourceRef: completed.session_id, targetRef: completed.session_id, actorRef: common.actorRef, sourceRevision: 0, targetRevision: 0 }), 'CYCLE_DETECTED')
  })

  it('rejects unsafe registry data and plans registered mobile presentations with reuse', () => {
    const registry = new SpatialComponentRegistry()
    expectCode(() => registry.validateData('text-response', undefined, { text: '<script>alert(1)</script>', citations: [] }), 'UNSAFE_PAYLOAD')
    expectCode(() => registry.createActionIntent({ componentId: 'text-response', actionId: 'drop-table' }), 'UNSUPPORTED_ACTION')
    const planner = new SpatialPresentationPlanner({ registry, ...common, now, idFactory: (prefix) => `${prefix}-fixed` })
    const input = {
      schema_version: SPATIAL_SCHEMA_VERSIONS.presentationIntent,
      presentation_id: 'presentation-one', workspace_id: common.workspaceId, node_id: common.nodeId, session_id: 'session-one', turn_id: 'turn-one', revision: 0,
      target_refs: ['entity-one'], importance: 0.8, focus_ref: 'entity-one', viewport: { width: 390, height: 844, density: 'COMFORTABLE', device: 'MOBILE' },
      requested_component_id: 'text-response', requested_component_version: null, requested_presentation: {}, created_at: now().toISOString(),
    }
    const first = planner.plan({ intent: input, data: { text: 'hello', citations: [] } })
    const second = planner.plan({ intent: input, data: { text: 'updated', citations: [] } })
    expect(first.result.density).toBe('COMPACT')
    expect(second.reuse).toBe(true)
    expect(second.result.presentation_id).toBe(first.result.presentation_id)
  })
})

describe('Spatial M4 voice adapter', () => {
  it('requires explicit permission and reviews the transcript before using the shared envelope', async () => {
    const gateway = createGateway(0)
    const voice = new VoiceInteractionAdapter({ ...common, gateway, permission: 'prompt', now, idFactory: (prefix) => `${prefix}-fixed` })
    await expect(voice.start()).rejects.toMatchObject({ code: 'PERMISSION_DENIED' })
    await voice.requestPermission(async () => true)
    await voice.start()
    voice.pushTranscript('check the endpoint', { isFinal: true, confidence: 0.92 })
    await voice.stop({ ref: 'audio-ref', mime_type: 'audio/webm' })
    const submission = await voice.submit()
    expect(submission.envelope.modality).toBe('voice')
    expect(submission.envelope.attachments_manifest[0]?.ref).toBe('audio-ref')
  })
})
