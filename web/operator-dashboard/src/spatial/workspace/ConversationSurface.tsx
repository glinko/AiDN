import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'

import { MessageCircle, Mic, Minimize2, Paperclip, Plus, RotateCcw, Send, Sparkles, X } from 'lucide-react'

import { Button, IconButton, StatusLabel, TextArea } from '@/spatial/primitives'
import {
  createDurableConversationService,
  createGeneratedObjectService,
  createIntentGateway,
  createInteractionSeed,
  createSessionArtifactService,
  createVoiceInteractionAdapter,
  createWorkspaceSessionGraph,
  IntentGatewayError,
  VoiceInteractionError,
  type ConversationExchange,
  type InteractionSeedController,
} from '@/spatial/interaction'

import type { SpatialWorkspaceState } from './SpatialWorkspace'

type ConversationSurfaceProps = {
  state: SpatialWorkspaceState
  openRequest?: number
}

type SurfaceMessage = {
  id: string
  role: 'operator' | 'agent' | 'system'
  text: string
  turnId?: string
  citationRefs?: string[]
  attachmentRefs?: string[]
}

function id(prefix: string): string {
  const uuid = typeof globalThis.crypto?.randomUUID === 'function' ? globalThis.crypto.randomUUID() : `${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`
  return `${prefix}_${uuid}`
}

/**
 * DOM-only Conversation Surface. It owns focus, transcript, and session
 * controls; the canvas remains a renderer and never receives conversation
 * chunks or executable presentation payloads.
 */
export function ConversationSurface({ state, openRequest = 0 }: ConversationSurfaceProps) {
  const workspaceId = `workspace-${state.workspaceData.scope.hypervisor_id}`
  const nodeId = state.workspaceData.scope.node_id
  const actorRef = 'operator:local'
  const graph = useMemo(() => createWorkspaceSessionGraph({ workspaceId, nodeId }), [nodeId, workspaceId])
  const gateway = useMemo(() => createIntentGateway({ workspaceId, nodeId, currentRevision: state.workspaceData.projection.sourceRevision }), [nodeId, state.workspaceData.projection.sourceRevision, workspaceId])
  const conversation = useMemo(() => createDurableConversationService({ graph, workspaceId, nodeId, actorRef }), [actorRef, graph, nodeId, workspaceId])
  const generatedObjects = useMemo(() => createGeneratedObjectService({ graph, workspaceId, nodeId }), [graph, nodeId, workspaceId])
  const artifacts = useMemo(() => createSessionArtifactService({ graph, workspaceId, nodeId }), [graph, nodeId, workspaceId])
  const voice = useMemo(() => createVoiceInteractionAdapter({ gateway, actorRef, workspaceId, nodeId }), [actorRef, gateway, nodeId, workspaceId])
  const seedRef = useRef<InteractionSeedController | null>(null)
  const composerRef = useRef<HTMLTextAreaElement>(null)
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState('')
  const [messages, setMessages] = useState<SurfaceMessage[]>([])
  const [exchange, setExchange] = useState<ConversationExchange | null>(null)
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [artifactId, setArtifactId] = useState<string | null>(null)
  const [objectId, setObjectId] = useState<string | null>(null)
  const [branchFromArtifactId, setBranchFromArtifactId] = useState<string | null>(null)
  const [feedback, setFeedback] = useState('Ready for a text interaction.')
  const [busy, setBusy] = useState(false)
  const [voiceStatus, setVoiceStatus] = useState<'idle' | 'permission' | 'recording' | 'text-fallback'>('idle')
  const storageKey = `aidn-spatial-interaction:${workspaceId}:${nodeId}`

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(storageKey)
      if (!raw) return
      const persisted = JSON.parse(raw) as {
        conversation?: ReturnType<typeof conversation.snapshot>
        objects?: ReturnType<typeof generatedObjects.snapshot>
        artifacts?: ReturnType<typeof artifacts.snapshot>
      }
      if (persisted.conversation) {
        conversation.restore(persisted.conversation)
        const latestExchange = persisted.conversation.exchanges.at(-1) ?? null
        setExchange(latestExchange)
        setSessionId(latestExchange?.session_id ?? persisted.conversation.sessions.sessions.at(-1)?.session_id ?? null)
        setMessages(conversation.listTurns(latestExchange?.session_id).map((turn) => ({ id: turn.turn_id, role: turn.role, text: turn.text, turnId: turn.turn_id, citationRefs: [...turn.citation_refs], attachmentRefs: [...turn.attachment_refs] })))
      }
      if (persisted.objects) {
        generatedObjects.restoreSnapshot(persisted.objects)
        setObjectId(persisted.objects.find((object) => object.state !== 'ARCHIVED')?.object_id ?? null)
      }
      if (persisted.artifacts) {
        artifacts.restoreSnapshot(persisted.artifacts)
        setArtifactId(persisted.artifacts.at(-1)?.artifact_id ?? null)
      }
      setFeedback('Restored retained Workspace Session from local durable adapter.')
    } catch {
      setFeedback('Retained Session could not be restored; starting a clean interaction.')
    }
  }, [artifacts, conversation, generatedObjects, storageKey])

  useEffect(() => {
    try {
      window.localStorage.setItem(storageKey, JSON.stringify({ conversation: conversation.snapshot(), objects: generatedObjects.snapshot(), artifacts: artifacts.snapshot() }))
    } catch {
      // Persistence is an enhancement; the current in-memory session remains usable.
    }
  }, [artifactId, conversation, exchange, generatedObjects, artifacts, messages, objectId, sessionId, storageKey])

  const ensureSeed = useCallback(() => {
    const existing = seedRef.current?.getSnapshot()
    if (!seedRef.current || existing?.state === 'ACTIVE' || existing?.state === 'FAILED' || existing?.state === 'CANCELLED') {
      seedRef.current = createInteractionSeed({
        workspaceId,
        nodeId,
        actorRef,
        gateway,
        semanticAnchor: state.selectedNodeId ?? 'workspace:empty',
      })
    }
    return seedRef.current
  }, [actorRef, gateway, nodeId, state.selectedNodeId, workspaceId])

  const openComposer = useCallback(() => {
    const seed = ensureSeed()
    seed.beginComposition()
    setOpen(true)
    setFeedback('Compose an interaction; nothing is sent until Submit.')
    window.requestAnimationFrame(() => composerRef.current?.focus())
  }, [ensureSeed])

  useEffect(() => {
    if (!open) return
    const frame = window.requestAnimationFrame(() => composerRef.current?.focus())
    return () => window.cancelAnimationFrame(frame)
  }, [open])

  const lastOpenRequest = useRef(0)
  useEffect(() => {
    if (openRequest <= 0 || openRequest === lastOpenRequest.current) return
    lastOpenRequest.current = openRequest
    openComposer()
  }, [openComposer, openRequest])

  useEffect(() => {
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'i') {
        event.preventDefault()
        openComposer()
      }
      if (event.key === 'Escape' && open && !busy) {
        event.preventDefault()
        seedRef.current?.cancel()
        setOpen(false)
        setDraft('')
        setFeedback('Interaction cancelled; no empty session was created.')
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [busy, open, openComposer])

  const submit = useCallback(() => {
    const text = draft.trim()
    if (!text || busy) return
    setBusy(true)
    try {
      const seed = ensureSeed()
      seed.setText(text)
      const submission = seed.submit({ currentRevision: state.workspaceData.projection.sourceRevision })
      let targetSessionId: string | undefined
      if (branchFromArtifactId) {
        const branch = artifacts.branch(branchFromArtifactId, {
          rootIntentId: submission.envelope.intent_id,
          actorRef,
          contextRefs: artifacts.get(branchFromArtifactId)?.context_root_ref ? [artifacts.get(branchFromArtifactId)!.context_root_ref] : undefined,
          title: text.slice(0, 64),
        })
        targetSessionId = branch.session_id
        setBranchFromArtifactId(null)
        setArtifactId(null)
        setMessages([])
      }
      const nextExchange = conversation.submitIntent(submission, { sessionId: targetSessionId, title: text.slice(0, 64) })
      setExchange(nextExchange)
      setSessionId(nextExchange.session_id)
      const operatorTurn = conversation.getTurn(nextExchange.operator_turn_id)
      setMessages((current) => [...current, { id: id('message'), role: 'operator', text, turnId: operatorTurn?.turn_id, citationRefs: operatorTurn?.citation_refs, attachmentRefs: operatorTurn?.attachment_refs }])
      conversation.appendResponseChunk(nextExchange.exchange_id, `Primary Agent acknowledged: ${text}`, null)
      const completed = conversation.completeResponse(nextExchange.exchange_id, null)
      setExchange(completed)
      const responseTurn = conversation.getTurn(completed.response_turn_id)
      setMessages((current) => [...current, { id: id('message'), role: 'agent', text: completed.response_text, turnId: responseTurn?.turn_id, citationRefs: responseTurn?.citation_refs, attachmentRefs: responseTurn?.attachment_refs }])
      setDraft('')
      setOpen(false)
      setFeedback('Response retained in the Workspace Session.')
    } catch (error) {
      const message = error instanceof IntentGatewayError ? error.message : 'Interaction failed; revise and retry.'
      setFeedback(message)
    } finally {
      setBusy(false)
    }
  }, [artifacts, branchFromArtifactId, busy, conversation, draft, ensureSeed, state.workspaceData.projection.sourceRevision])

  const startVoice = async () => {
    setVoiceStatus('permission')
    try {
      const permission = await voice.requestPermission()
      if (permission !== 'granted') {
        setVoiceStatus('text-fallback')
        setFeedback('Microphone unavailable or denied; review a text interaction instead.')
        return
      }
      await voice.start()
      setVoiceStatus('recording')
      setFeedback('Microphone active only after explicit permission. Stop capture to review the transcript.')
    } catch (error) {
      setVoiceStatus('text-fallback')
      setFeedback(error instanceof VoiceInteractionError ? error.message : 'Voice input is unavailable; text remains available.')
    }
  }

  const handleComposerKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
      event.preventDefault()
      submit()
    }
  }

  const createObject = () => {
    if (!exchange || !sessionId) return
    const responseTurn = conversation.getTurn(exchange.response_turn_id)
    if (!responseTurn) return
    try {
      const object = generatedObjects.create({
        sessionId,
        sourceTurnId: responseTurn.turn_id,
        actorRef,
        kind: 'REPORT',
        title: 'Interaction response',
        summary: 'Generated Object linked to the source turn.',
        semanticAnchor: state.selectedNodeId ?? 'workspace:generated',
        data: { source_turn_id: responseTurn.turn_id, text: exchange.response_text },
      })
      setObjectId(object.object_id)
      setFeedback('Generated Object created; closing this surface will not delete it.')
    } catch {
      setFeedback('Generated Object could not be created for this session.')
    }
  }

  const collapseSession = () => {
    if (!sessionId) return
    try {
      const artifact = artifacts.collapse(sessionId, { actorRef, cameraSnapshot: { focus_ref: state.camera.focusId ?? null, zoom: state.camera.zoom } })
      setArtifactId(artifact.artifact_id)
      setFeedback('Session collapsed to an Artifact. Transcript and links remain reopenable.')
    } catch {
      setFeedback('Session is not ready to collapse.')
    }
  }

  const restoreSession = () => {
    if (!artifactId) return
    try {
      artifacts.restore(artifactId)
      setFeedback('Session restored with its context graph and camera snapshot.')
    } catch {
      setFeedback('Artifact could not be restored.')
    }
  }

  const retryExchange = () => {
    if (!exchange) return
    try {
      const retried = conversation.retry(exchange.exchange_id)
      setExchange(retried)
      setFeedback('Retry queued without duplicating the operator prompt.')
      conversation.appendResponseChunk(retried.exchange_id, 'Primary Agent retry acknowledged.', retried.binding_id)
      const completed = conversation.completeResponse(retried.exchange_id, retried.binding_id)
      setExchange(completed)
      setMessages((current) => [...current, { id: id('message'), role: 'agent', text: completed.response_text, turnId: completed.response_turn_id }])
    } catch {
      setFeedback('Retry is unavailable for this turn.')
    }
  }

  const startBranch = () => {
    if (!artifactId) return
    setBranchFromArtifactId(artifactId)
    setExchange(null)
    setSessionId(null)
    setObjectId(null)
    setMessages([])
    setDraft('')
    setOpen(true)
    ensureSeed().beginComposition()
    setFeedback('Branch seed ready; the original Artifact remains unchanged.')
    window.requestAnimationFrame(() => composerRef.current?.focus())
  }

  return (
    <section className="aidn-spatial-conversation" data-aidn-conversation-surface aria-labelledby="spatial-conversation-title">
      <div className="aidn-spatial-conversation-heading">
        <div>
          <StatusLabel status={exchange ? 'ready' : 'unknown'}>{exchange ? 'Session active' : 'Interaction seed'}</StatusLabel>
          <h3 id="spatial-conversation-title">Conversation Surface</h3>
        </div>
        <div className="aidn-spatial-conversation-heading-actions">
          <span className="aidn-spatial-conversation-anchor" title="Semantic anchor">{state.selectedNodeId ?? 'workspace:empty'}</span>
          {open ? <IconButton aria-label="Cancel interaction" variant="ghost" accent="neutral" onClick={() => { seedRef.current?.cancel(); setOpen(false); setDraft('') }}><X aria-hidden="true" /></IconButton> : null}
        </div>
      </div>
      {messages.length ? (
        <div className="aidn-spatial-conversation-transcript" role="log" aria-live="polite" aria-relevant="additions" data-aidn-conversation-transcript>
          {messages.slice(-200).map((message) => (
            <article key={message.id} className="aidn-spatial-conversation-turn" data-aidn-turn-role={message.role}>
              <span className="aidn-spatial-conversation-role">{message.role === 'operator' ? 'You' : 'Primary Agent'}</span>
              <p>{message.text}</p>
              {message.turnId ? <span className="aidn-spatial-conversation-provenance">turn {message.turnId}</span> : null}
              {message.citationRefs?.length ? <span className="aidn-spatial-conversation-provenance">citations {message.citationRefs.join(', ')}</span> : null}
              {message.attachmentRefs?.length ? <span className="aidn-spatial-conversation-provenance">attachments {message.attachmentRefs.length}</span> : null}
            </article>
          ))}
        </div>
      ) : (
        <p className="aidn-spatial-conversation-empty">Start from empty space, a keyboard shortcut, or the button below. Entity controls keep their own click semantics.</p>
      )}
      {open ? (
        <div className="aidn-spatial-interaction-composer" data-aidn-interaction-seed-state={seedRef.current?.getSnapshot().state ?? 'COMPOSING'}>
          <label htmlFor="spatial-interaction-input">Interaction text</label>
          <TextArea ref={composerRef} id="spatial-interaction-input" rows={3} value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={handleComposerKeyDown} placeholder="Ask the Primary Agent about this Workspace…" aria-describedby="spatial-interaction-hint" />
          <p id="spatial-interaction-hint">Ctrl/⌘ + Enter submits · Escape cancels · attachments are reference-only.</p>
          <div className="aidn-spatial-interaction-actions">
            <Button size="sm" variant="ghost" accent="neutral" disabled={busy}><Paperclip aria-hidden="true" /> Add context</Button>
            <Button size="sm" variant="ghost" accent="violet" disabled={busy || voiceStatus === 'recording'} onClick={startVoice}><Mic aria-hidden="true" /> {voiceStatus === 'recording' ? 'Mic active' : voiceStatus === 'text-fallback' ? 'Voice unavailable' : 'Voice preview'}</Button>
            <Button size="sm" accent="cyan" loading={busy} onClick={submit}><Send aria-hidden="true" /> Submit</Button>
          </div>
        </div>
      ) : null}
      {exchange ? <p className="aidn-spatial-conversation-stream-status" data-aidn-stream-status={exchange.status}>Stream · {exchange.status.toLowerCase()}</p> : null}
      <div className="aidn-spatial-conversation-actions">
        {!open ? <Button size="sm" accent="cyan" onClick={openComposer} data-aidn-create-interaction><Plus aria-hidden="true" /> Create interaction <span className="aidn-spatial-shortcut">⌘I</span></Button> : null}
        {exchange ? <Button size="sm" variant="outline" accent="violet" onClick={createObject} disabled={Boolean(objectId)}><Sparkles aria-hidden="true" /> {objectId ? 'Object linked' : 'Create Generated Object'}</Button> : null}
        {sessionId && !artifactId ? <Button size="sm" variant="ghost" accent="neutral" onClick={collapseSession}><Minimize2 aria-hidden="true" /> Collapse to Artifact</Button> : null}
        {artifactId ? <Button size="sm" variant="ghost" accent="blue" onClick={restoreSession}><RotateCcw aria-hidden="true" /> Restore Session</Button> : null}
        {artifactId ? <Button size="sm" variant="ghost" accent="violet" onClick={startBranch}><Plus aria-hidden="true" /> Start branch</Button> : null}
        {exchange && ['FAILED', 'TIMED_OUT'].includes(exchange.status) ? <Button size="sm" variant="outline" accent="amber" onClick={retryExchange}><RotateCcw aria-hidden="true" /> Retry response</Button> : null}
      </div>
      <p className="aidn-spatial-conversation-feedback" role="status" aria-live="polite">{feedback}</p>
      {sessionId ? <p className="aidn-spatial-conversation-session"><MessageCircle aria-hidden="true" /> session {sessionId}{artifactId ? ` · artifact ${artifactId}` : ''}</p> : null}
    </section>
  )
}
