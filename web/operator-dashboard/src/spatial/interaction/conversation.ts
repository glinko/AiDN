import {
  parseSpatialConversationTurn,
  SPATIAL_SCHEMA_VERSIONS,
  type SpatialConversationTurn,
  type SpatialWorkspaceSession,
} from '@/spatial/contracts'

import type { IntentSubmission } from './intent-gateway'
import { WorkspaceSessionGraph, type WorkspaceSessionGraphSnapshot } from './session-graph'

export type ConversationErrorCode =
  | 'EXCHANGE_NOT_FOUND'
  | 'BINDING_REJECTED'
  | 'TIMEOUT'
  | 'CANCELLED'
  | 'DISCONNECTED'
  | 'STREAM_LIMIT'
  | 'INVALID_TURN'

export class ConversationError extends Error {
  readonly code: ConversationErrorCode

  constructor(code: ConversationErrorCode, message: string) {
    super(message)
    this.name = 'ConversationError'
    this.code = code
  }
}

export type ConversationConnectionState = 'CONNECTED' | 'DISCONNECTED' | 'RECONNECTING'

export type ConversationExchange = {
  exchange_id: string
  session_id: string
  correlation_id: string
  intent_id: string
  operator_turn_id: string
  response_turn_id: string
  binding_id: string | null
  status: 'QUEUED' | 'STREAMING' | 'COMPLETED' | 'FAILED' | 'CANCELLED' | 'TIMED_OUT'
  response_text: string
  attempt: number
  created_at: string
  updated_at: string
  error_code: ConversationErrorCode | null
}

export type DurableConversationSnapshot = {
  sessions: WorkspaceSessionGraphSnapshot
  turns: SpatialConversationTurn[]
  exchanges: ConversationExchange[]
  connection: ConversationConnectionState
}

export type DurableConversationOptions = {
  graph: WorkspaceSessionGraph
  workspaceId: string
  nodeId: string
  actorRef: string
  now?: () => Date
  idFactory?: (prefix: string) => string
  activeBinding?: (bindingId: string | null) => boolean
  maxResponseChars?: number
  maxStreamChunks?: number
}

function defaultId(prefix: string): string {
  const uuid = typeof globalThis.crypto?.randomUUID === 'function' ? globalThis.crypto.randomUUID() : `${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`
  return `${prefix}_${uuid}`
}

function clone<T>(value: T): T {
  if (typeof structuredClone === 'function') return structuredClone(value)
  return JSON.parse(JSON.stringify(value)) as T
}

function safeChunk(value: string, maxChars: number): string {
  return value
    .replace(/<\/?[^>]+>/g, '')
    .replace(/javascript\s*:/gi, '')
    .split('').filter((character) => {
      const code = character.charCodeAt(0)
      return !(code <= 8 || code === 11 || code === 12 || (code >= 14 && code <= 31))
    }).join('')
    .slice(0, maxChars)
}

const STREAM_SEPARATOR = '\u241e'

function iso(now: () => Date): string {
  return now().toISOString()
}

/** Retained conversation projection fed by the Intent -> Primary Agent -> response path. */
export class DurableConversationService {
  private readonly graph: WorkspaceSessionGraph
  private readonly workspaceId: string
  private readonly nodeId: string
  private readonly actorRef: string
  private readonly now: () => Date
  private readonly idFactory: (prefix: string) => string
  private readonly activeBinding?: (bindingId: string | null) => boolean
  private readonly maxResponseChars: number
  private readonly maxStreamChunks: number
  private readonly turns = new Map<string, SpatialConversationTurn>()
  private readonly exchanges = new Map<string, ConversationExchange>()
  private readonly queuedIntents = new Map<string, IntentSubmission>()
  private connection: ConversationConnectionState = 'CONNECTED'

  constructor(options: DurableConversationOptions) {
    this.graph = options.graph
    this.workspaceId = options.workspaceId
    this.nodeId = options.nodeId
    this.actorRef = options.actorRef
    this.now = options.now ?? (() => new Date())
    this.idFactory = options.idFactory ?? defaultId
    this.activeBinding = options.activeBinding
    this.maxResponseChars = Math.max(256, options.maxResponseChars ?? 32_000)
    this.maxStreamChunks = Math.max(1, options.maxStreamChunks ?? 256)
  }

  setConnection(state: ConversationConnectionState): void {
    this.connection = state
  }

  getConnection(): ConversationConnectionState {
    return this.connection
  }

  submitIntent(submission: IntentSubmission, options: { sessionId?: string; bindingId?: string | null; title?: string } = {}): ConversationExchange {
    const envelope = submission.envelope
    if (envelope.workspace_id !== this.workspaceId) throw new ConversationError('INVALID_TURN', 'intent belongs to another workspace')
    if (envelope.node_id !== this.nodeId) throw new ConversationError('INVALID_TURN', 'intent belongs to another Node')
    const existing = [...this.exchanges.values()].find((exchange) => exchange.intent_id === envelope.intent_id)
    if (existing) return clone(existing)
    if (this.connection === 'DISCONNECTED') this.queuedIntents.set(envelope.idempotency_key, submission)

    const session = options.sessionId
      ? this.graph.getSession(options.sessionId)
      : this.graph.createSession({ rootIntentId: envelope.intent_id, actorRef: this.actorRef, title: options.title, semanticAnchor: envelope.target_refs[0] ?? `session:${envelope.intent_id}` })
    if (!session) throw new ConversationError('INVALID_TURN', 'conversation session was not found')
    const timestamp = iso(this.now)
    const operatorTurn = this.createTurn({
      role: 'operator',
      state: 'COMPLETED',
      session,
      sequence: session.turn_refs.length,
      text: envelope.text ?? JSON.stringify(envelope.operation ?? {}),
      intentId: envelope.intent_id,
      bindingId: options.bindingId ?? null,
      correlationId: envelope.intent_id,
    })
    this.turns.set(operatorTurn.turn_id, operatorTurn)
    this.graph.appendTurn(session.session_id, operatorTurn.turn_id, this.actorRef, operatorTurn.revision)
    const refreshedSession = this.graph.getSession(session.session_id) ?? session
    const responseTurn = this.createTurn({
      role: 'agent',
      state: 'QUEUED',
      session: refreshedSession,
      sequence: refreshedSession.turn_refs.length,
      text: '',
      intentId: envelope.intent_id,
      bindingId: options.bindingId ?? null,
      correlationId: envelope.intent_id,
    })
    this.turns.set(responseTurn.turn_id, responseTurn)
    this.graph.appendTurn(session.session_id, responseTurn.turn_id, this.actorRef, responseTurn.revision)
    const exchange: ConversationExchange = {
      exchange_id: this.idFactory('exchange'),
      session_id: session.session_id,
      correlation_id: envelope.intent_id,
      intent_id: envelope.intent_id,
      operator_turn_id: operatorTurn.turn_id,
      response_turn_id: responseTurn.turn_id,
      binding_id: options.bindingId ?? null,
      status: 'QUEUED',
      response_text: '',
      attempt: 1,
      created_at: timestamp,
      updated_at: timestamp,
      error_code: null,
    }
    this.exchanges.set(exchange.exchange_id, exchange)
    return clone(exchange)
  }

  flushDisconnectedQueue(): string[] {
    const keys = [...this.queuedIntents.keys()]
    this.queuedIntents.clear()
    if (this.connection === 'DISCONNECTED') this.connection = 'RECONNECTING'
    return keys
  }

  reconnect(): { connection: 'CONNECTED'; resumed_intent_keys: string[]; active_exchanges: ConversationExchange[] } {
    const resumedIntentKeys = this.flushDisconnectedQueue()
    this.connection = 'CONNECTED'
    return {
      connection: 'CONNECTED',
      resumed_intent_keys: resumedIntentKeys,
      active_exchanges: [...this.exchanges.values()].filter((exchange) => ['QUEUED', 'STREAMING'].includes(exchange.status)).map(clone),
    }
  }

  appendResponseChunk(exchangeId: string, chunk: string, bindingId?: string | null): ConversationExchange {
    const exchange = this.requireExchange(exchangeId)
    this.assertBinding(exchange, bindingId)
    if (exchange.status === 'CANCELLED' || exchange.status === 'TIMED_OUT') throw new ConversationError(exchange.status === 'CANCELLED' ? 'CANCELLED' : 'TIMEOUT', 'exchange is no longer streaming')
    if (exchange.status === 'FAILED') throw new ConversationError('EXCHANGE_NOT_FOUND', 'failed exchange must be retried')
    const currentTurn = this.requireTurn(exchange.response_turn_id)
    const chunks = currentTurn.text.length ? currentTurn.text.split(STREAM_SEPARATOR).length : 0
    if (chunks >= this.maxStreamChunks) {
      exchange.status = 'FAILED'
      exchange.error_code = 'STREAM_LIMIT'
      this.saveExchange(exchange)
      throw new ConversationError('STREAM_LIMIT', 'response stream exceeded the chunk limit')
    }
    const remaining = this.maxResponseChars - exchange.response_text.length
    const safe = safeChunk(chunk, Math.max(0, remaining))
    exchange.response_text += safe
    exchange.status = 'STREAMING'
    exchange.updated_at = iso(this.now)
    currentTurn.state = 'STREAMING'
    currentTurn.text = `${currentTurn.text}${safe}${STREAM_SEPARATOR}`.slice(0, this.maxResponseChars + this.maxStreamChunks)
    currentTurn.updated_at = exchange.updated_at
    currentTurn.revision += 1
    this.turns.set(currentTurn.turn_id, currentTurn)
    this.saveExchange(exchange)
    return clone(exchange)
  }

  completeResponse(exchangeId: string, bindingId?: string | null): ConversationExchange {
    const exchange = this.requireExchange(exchangeId)
    this.assertBinding(exchange, bindingId)
    if (exchange.status === 'CANCELLED' || exchange.status === 'TIMED_OUT') throw new ConversationError(exchange.status === 'CANCELLED' ? 'CANCELLED' : 'TIMEOUT', 'exchange is no longer active')
    exchange.status = 'COMPLETED'
    exchange.updated_at = iso(this.now)
    const turn = this.requireTurn(exchange.response_turn_id)
    turn.state = 'COMPLETED'
    turn.text = turn.text.replaceAll(STREAM_SEPARATOR, '')
    turn.updated_at = exchange.updated_at
    turn.revision += 1
    this.turns.set(turn.turn_id, turn)
    this.saveExchange(exchange)
    return clone(exchange)
  }

  failResponse(exchangeId: string, errorCode: ConversationErrorCode = 'EXCHANGE_NOT_FOUND', bindingId?: string | null): ConversationExchange {
    const exchange = this.requireExchange(exchangeId)
    this.assertBinding(exchange, bindingId)
    exchange.status = 'FAILED'
    exchange.error_code = errorCode
    exchange.updated_at = iso(this.now)
    const turn = this.requireTurn(exchange.response_turn_id)
    turn.state = 'FAILED'
    turn.updated_at = exchange.updated_at
    turn.revision += 1
    this.turns.set(turn.turn_id, turn)
    this.saveExchange(exchange)
    return clone(exchange)
  }

  cancel(exchangeId: string, bindingId?: string | null): ConversationExchange {
    const exchange = this.requireExchange(exchangeId)
    this.assertBinding(exchange, bindingId)
    exchange.status = 'CANCELLED'
    exchange.error_code = 'CANCELLED'
    exchange.updated_at = iso(this.now)
    const turn = this.requireTurn(exchange.response_turn_id)
    turn.state = 'CANCELLED'
    turn.updated_at = exchange.updated_at
    turn.revision += 1
    this.turns.set(turn.turn_id, turn)
    this.saveExchange(exchange)
    return clone(exchange)
  }

  timeout(exchangeId: string, bindingId?: string | null): ConversationExchange {
    const exchange = this.requireExchange(exchangeId)
    this.assertBinding(exchange, bindingId)
    exchange.status = 'TIMED_OUT'
    exchange.error_code = 'TIMEOUT'
    exchange.updated_at = iso(this.now)
    const turn = this.requireTurn(exchange.response_turn_id)
    turn.state = 'FAILED'
    turn.updated_at = exchange.updated_at
    turn.revision += 1
    this.turns.set(turn.turn_id, turn)
    this.saveExchange(exchange)
    return clone(exchange)
  }

  retry(exchangeId: string): ConversationExchange {
    const previous = this.requireExchange(exchangeId)
    if (!['FAILED', 'TIMED_OUT', 'CANCELLED'].includes(previous.status)) return clone(previous)
    const oldTurn = this.requireTurn(previous.response_turn_id)
    const session = this.graph.getSession(previous.session_id)
    if (!session) throw new ConversationError('EXCHANGE_NOT_FOUND', 'conversation session was not found')
    const responseTurn = this.createTurn({
      role: 'agent',
      state: 'QUEUED',
      session,
      sequence: session.turn_refs.length,
      text: '',
      intentId: previous.intent_id,
      bindingId: previous.binding_id,
      correlationId: previous.correlation_id,
    })
    this.turns.set(responseTurn.turn_id, responseTurn)
    this.graph.appendTurn(session.session_id, responseTurn.turn_id, this.actorRef, responseTurn.revision)
    const retry: ConversationExchange = {
      ...previous,
      exchange_id: this.idFactory('exchange'),
      response_turn_id: responseTurn.turn_id,
      status: 'QUEUED',
      response_text: '',
      attempt: previous.attempt + 1,
      created_at: iso(this.now),
      updated_at: iso(this.now),
      error_code: null,
    }
    this.exchanges.set(retry.exchange_id, retry)
    void oldTurn
    return clone(retry)
  }

  getExchange(exchangeId: string): ConversationExchange | null {
    const exchange = this.exchanges.get(exchangeId)
    return exchange ? clone(exchange) : null
  }

  getTurn(turnId: string): SpatialConversationTurn | null {
    const turn = this.turns.get(turnId)
    return turn ? clone(turn) : null
  }

  listTurns(sessionId?: string): SpatialConversationTurn[] {
    return [...this.turns.values()].filter((turn) => !sessionId || turn.session_id === sessionId).sort((a, b) => a.sequence - b.sequence).map(clone)
  }

  snapshot(): DurableConversationSnapshot {
    return {
      sessions: this.graph.snapshot(),
      turns: this.listTurns(),
      exchanges: [...this.exchanges.values()].map(clone),
      connection: this.connection,
    }
  }

  restore(snapshot: DurableConversationSnapshot): void {
    this.graph.restore(snapshot.sessions)
    this.turns.clear()
    for (const turn of snapshot.turns) {
      const parsed = parseSpatialConversationTurn(turn)
      if (!parsed.ok) throw new ConversationError('INVALID_TURN', 'cannot restore conversation turn')
      this.turns.set(parsed.data.turn_id, clone(parsed.data))
    }
    this.exchanges.clear()
    for (const exchange of snapshot.exchanges) this.exchanges.set(exchange.exchange_id, clone(exchange))
    this.connection = snapshot.connection
  }

  private createTurn(input: {
    role: SpatialConversationTurn['role']
    state: SpatialConversationTurn['state']
    session: SpatialWorkspaceSession
    sequence: number
    text: string
    intentId: string | null
    bindingId: string | null
    correlationId: string | null
  }): SpatialConversationTurn {
    const now = iso(this.now)
    const candidate: SpatialConversationTurn = {
      schema_version: SPATIAL_SCHEMA_VERSIONS.conversationTurn,
      turn_id: this.idFactory('turn'),
      session_id: input.session.session_id,
      workspace_id: this.workspaceId,
      node_id: this.nodeId,
      revision: 0,
      sequence: input.sequence,
      role: input.role,
      state: input.state,
      text: safeChunk(input.text, this.maxResponseChars),
      intent_id: input.intentId,
      provenance: { intent_id: input.intentId, correlation_id: input.correlationId, binding_id: input.bindingId, source_ref: input.session.session_id },
      citation_refs: [],
      attachment_refs: [],
      created_at: now,
      updated_at: now,
    }
    const parsed = parseSpatialConversationTurn(candidate)
    if (!parsed.ok) throw new ConversationError('INVALID_TURN', 'conversation turn is invalid')
    return parsed.data
  }

  private assertBinding(exchange: ConversationExchange, bindingId?: string | null): void {
    const expected = exchange.binding_id
    const provided = bindingId ?? expected
    if (expected !== provided || (this.activeBinding && !this.activeBinding(provided))) {
      throw new ConversationError('BINDING_REJECTED', 'response is from an old or revoked Primary Agent binding')
    }
  }

  private requireExchange(exchangeId: string): ConversationExchange {
    const exchange = this.exchanges.get(exchangeId)
    if (!exchange) throw new ConversationError('EXCHANGE_NOT_FOUND', 'conversation exchange was not found')
    return exchange
  }

  private requireTurn(turnId: string): SpatialConversationTurn {
    const turn = this.turns.get(turnId)
    if (!turn) throw new ConversationError('INVALID_TURN', 'conversation turn was not found')
    return turn
  }

  private saveExchange(exchange: ConversationExchange): void {
    this.exchanges.set(exchange.exchange_id, exchange)
  }
}

export const SpatialConversationService = DurableConversationService

export function createDurableConversationService(options: DurableConversationOptions): DurableConversationService {
  return new DurableConversationService(options)
}
