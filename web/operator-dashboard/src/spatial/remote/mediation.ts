import {
  parseSpatialEndpointDetails,
  parseSpatialEndpointProvenance,
  parseSpatialEndpointTestFrame,
  parseSpatialRemoteContextManifest,
  parseSpatialRemoteRequest,
  parseSpatialRemoteResult,
  parseSpatialResourceAccounting,
  SPATIAL_SCHEMA_VERSIONS,
  type SpatialEndpointDetails,
  type SpatialEndpointProvenance,
  type SpatialEndpointTestFrame,
  type SpatialRemoteContextManifest,
  type SpatialRemoteRequest,
  type SpatialRemoteResult,
  type SpatialResourceAccounting,
  type SpatialRemoteResultClassification,
  type SpatialEndpointTestFrameState,
} from '@/spatial/contracts'

import { CanonicalReferenceRegistry, type CanonicalReferenceRegistryOptions } from '@/spatial/topology/reference-registry'

export type RemoteTransportResponse = {
  contentType: string
  payload: unknown
  sizeBytes?: number
}

/**
 * The only transport seam exposed to the browser. A production adapter is
 * supplied by the Node client; this module never accepts a URL or opens a
 * socket itself.
 */
export type RemoteTransportAdapter = {
  id: string
  send: (request: SpatialRemoteRequest, signal: AbortSignal) => Promise<RemoteTransportResponse>
}

export type RemoteAuthorization = {
  allowed: boolean
  grantRef?: string | null
  policyRevision?: number
  reason?: string
}

export type ContextFieldValue = string | number | boolean

export type CreateManifestInput = {
  requestId: string
  endpointRef: string
  capability: string
  workspaceSessionRef: string
  purpose: string
  fields?: Readonly<Record<string, ContextFieldValue>>
  allowedFields?: readonly string[]
  attachmentRefs?: readonly string[]
  mediaTypes?: readonly string[]
  sizeLimitBytes?: number
  retention?: SpatialRemoteContextManifest['retention']
  consentRequired?: boolean
  consentGranted?: boolean
  policyRevision?: number
}

export type CreateFrameInput = {
  frameId?: string
  endpointRef: string
  sourceRevision?: number
}

export type SubmitEndpointTestInput = {
  frameId: string
  idempotencyKey?: string
  fields?: Readonly<Record<string, ContextFieldValue>>
  allowedFields?: readonly string[]
  attachmentRefs?: readonly string[]
  mediaTypes?: readonly string[]
  workspaceSessionRef?: string
  operatorConsent?: boolean
  purpose?: string
}

export type RemoteMediationServiceOptions = CanonicalReferenceRegistryOptions & {
  primaryAgentRef: string
  defaultWorkspaceSessionRef?: string
  registry?: CanonicalReferenceRegistry
  adapters?: readonly RemoteTransportAdapter[]
  defaultAdapterId?: string
  maxRequestBytes?: number
  maxResponseBytes?: number
  defaultTimeoutMs?: number
  now?: () => Date
  idFactory?: (prefix: string) => string
  authorize?: (input: { endpoint: SpatialEndpointDetails; capability: string; workspaceSessionRef: string; primaryAgentRef: string }) => RemoteAuthorization
}

export type MediationErrorCode =
  | 'ENDPOINT_NOT_REGISTERED'
  | 'ENDPOINT_NOT_ALLOWED'
  | 'ENDPOINT_UNAVAILABLE'
  | 'CAPABILITY_MISMATCH'
  | 'STALE_ENDPOINT'
  | 'CONTEXT_FORBIDDEN'
  | 'CONTEXT_TOO_LARGE'
  | 'CONSENT_REQUIRED'
  | 'UNAUTHORIZED'
  | 'TRANSPORT_UNAVAILABLE'
  | 'TRANSPORT_ERROR'
  | 'TIMEOUT'
  | 'CANCELLED'
  | 'INVALID_RESULT'
  | 'DUPLICATE_SUBMIT'

export class RemoteMediationError extends Error {
  readonly code: MediationErrorCode
  readonly requestId?: string
  readonly frameId?: string

  constructor(code: MediationErrorCode, message: string, context: { requestId?: string; frameId?: string } = {}) {
    super(message)
    this.name = 'RemoteMediationError'
    this.code = code
    this.requestId = context.requestId
    this.frameId = context.frameId
  }
}

export type RemoteMediationEvent = {
  type: 'manifest' | 'request' | 'result' | 'frame' | 'accounting' | 'provenance'
  id: string
  requestId?: string
  occurredAt: string
}

export type RemoteSubmitResult = {
  request: SpatialRemoteRequest
  result: SpatialRemoteResult
  accounting: SpatialResourceAccounting
  frame: SpatialEndpointTestFrame
  duplicate: boolean
}

const DEFAULT_MAX_REQUEST_BYTES = 256_000
const DEFAULT_MAX_RESPONSE_BYTES = 1_000_000
const DEFAULT_TIMEOUT_MS = 30_000
const SECRET_KEY = /(?:system[_-]?prompt|conversation|history|wallet|private[_-]?key|secret|token|credential|cookie|authorization|browser[_-]?state|other[_-]?workspace|password)/i
const SCRIPT_OR_HTML = /<\/?(?:script|iframe|object|embed|form|button|a\b)[^>]*>|javascript\s*:/i
const PROMPT_INJECTION = /(?:ignore|disregard|override)\s+(?:all\s+)?(?:previous|prior|system)\s+instructions|reveal\s+(?:the\s+)?system\s+prompt|you\s+are\s+now\s+/i
const SECRET_VALUE = /(?:sk-[a-z0-9_-]{12,}|-----BEGIN [A-Z ]+ KEY-----|bearer\s+[a-z0-9._-]{12,}|(?:password|secret|token|api[_-]?key)\s*[:=]\s*\S+)/i

function clone<T>(value: T): T {
  if (typeof structuredClone === 'function') return structuredClone(value)
  return JSON.parse(JSON.stringify(value)) as T
}

function byteLength(value: string): number {
  if (typeof TextEncoder !== 'undefined') return new TextEncoder().encode(value).byteLength
  return value.length
}

function stableHash(value: string): string {
  // Deterministic, non-secret fingerprint for the manifest contract. The
  // authoritative Node may replace it with a cryptographic hash at the API seam.
  let hash = 2166136261
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index)
    hash = Math.imul(hash, 16777619)
  }
  return `sha256:${(hash >>> 0).toString(16).padStart(8, '0')}${'0'.repeat(24)}`
}

function nowIso(now: () => Date): string {
  const value = now()
  if (!Number.isFinite(value.getTime())) throw new RangeError('now must return a valid Date')
  return value.toISOString()
}

function safeId(prefix: string, factory: ((prefix: string) => string) | undefined, counter: { value: number }): string {
  if (factory) return factory(prefix)
  counter.value += 1
  return `${prefix}:${counter.value}`
}

function normalizedFields(fields: Readonly<Record<string, ContextFieldValue>> | undefined): Record<string, ContextFieldValue> {
  return Object.fromEntries(Object.entries(fields ?? {}).map(([key, value]) => [key.trim(), value]).filter(([key]) => Boolean(key)))
}

function sanitizedText(payload: unknown): string {
  const value = typeof payload === 'string' ? payload : JSON.stringify(payload) ?? String(payload)
  return value.replace(/<[^>]*>/g, '').split('\0').join('').slice(0, 1_000_000)
}

function hasRemoteUiPayload(payload: unknown): boolean {
  if (typeof payload !== 'object' || payload === null || Array.isArray(payload)) return false
  return Object.keys(payload as Record<string, unknown>).some((key) => /^(component|component_registry|action|callback|script|html)$/i.test(key))
}

function hasUnboundedStream(payload: unknown): boolean {
  if (typeof payload !== 'object' || payload === null) return false
  const value = payload as { [Symbol.asyncIterator]?: unknown; getReader?: unknown }
  return typeof value[Symbol.asyncIterator] === 'function' || typeof value.getReader === 'function'
}

function matchesMime(contentType: string, formats: readonly string[]): boolean {
  if (!formats.length) return true
  const normalized = contentType.split(';', 1)[0]?.trim().toLowerCase() ?? ''
  return formats.some((format) => {
    const candidate = format.toLowerCase()
    return candidate === normalized || candidate === '*' || candidate.endsWith('/*') && normalized.startsWith(candidate.slice(0, -1))
  })
}

function inputSchemaForEndpoint(endpoint: SpatialEndpointDetails): SpatialEndpointTestFrame['input_schema'] {
  const fields = endpoint.input_formats.length ? endpoint.input_formats : endpoint.supported_modalities.length ? endpoint.supported_modalities : ['text/plain']
  return { fields: fields.slice(0, 64), media_types: endpoint.input_formats.slice(0, 16) }
}

export class LocalRemoteMediationService {
  private readonly options: RemoteMediationServiceOptions
  private readonly registry: CanonicalReferenceRegistry
  private readonly endpoints = new Map<string, SpatialEndpointDetails>()
  private readonly allowedEndpoints = new Set<string>()
  private readonly adapters = new Map<string, RemoteTransportAdapter>()
  private readonly frames = new Map<string, SpatialEndpointTestFrame>()
  private readonly requests = new Map<string, SpatialRemoteRequest>()
  private readonly results = new Map<string, SpatialRemoteResult>()
  private readonly accounting = new Map<string, SpatialResourceAccounting>()
  private readonly idempotent = new Map<string, RemoteSubmitResult>()
  private readonly controllers = new Map<string, AbortController>()
  private readonly cancelledRequests = new Set<string>()
  private readonly eventLog: RemoteMediationEvent[] = []
  private readonly counter = { value: 0 }

  constructor(options: RemoteMediationServiceOptions) {
    if (!options.primaryAgentRef.trim()) throw new RemoteMediationError('UNAUTHORIZED', 'Primary Agent reference is required')
    this.options = options
    this.registry = options.registry ?? new CanonicalReferenceRegistry(options)
    for (const adapter of options.adapters ?? []) this.registerAdapter(adapter)
  }

  getRegistry(): CanonicalReferenceRegistry {
    return this.registry
  }

  registerAdapter(adapter: RemoteTransportAdapter): void {
    if (!adapter.id.trim() || typeof adapter.send !== 'function') throw new RemoteMediationError('TRANSPORT_UNAVAILABLE', 'Transport adapter must have an id and send function')
    this.adapters.set(adapter.id, adapter)
  }

  registerEndpoint(details: SpatialEndpointDetails, allowed = true): SpatialEndpointDetails {
    const parsed = parseSpatialEndpointDetails(details)
    if (!parsed.ok) throw new RemoteMediationError('ENDPOINT_NOT_REGISTERED', `Endpoint details rejected at ${parsed.diagnostic.path}`)
    if (parsed.data.workspace_id !== this.options.workspaceId || parsed.data.node_id !== this.options.nodeId) {
      throw new RemoteMediationError('ENDPOINT_NOT_REGISTERED', 'Endpoint details belong to a different Workspace or Node scope')
    }
    if (/^[a-z][a-z0-9+.-]*:\/\//i.test(parsed.data.canonical_ref) || parsed.data.canonical_ref.startsWith('//')) {
      throw new RemoteMediationError('ENDPOINT_NOT_REGISTERED', 'Endpoint identity must be a canonical reference, not a URL')
    }
    const existing = this.endpoints.get(parsed.data.canonical_ref)
    if (existing && parsed.data.revision < existing.revision) throw new RemoteMediationError('STALE_ENDPOINT', 'Endpoint revision cannot move backwards')
    this.registry.discover({ canonicalRef: parsed.data.canonical_ref, entityId: parsed.data.endpoint_id, entityKind: 'endpoint', revision: parsed.data.revision, provenanceRef: parsed.data.provider_ref })
    this.endpoints.set(parsed.data.canonical_ref, clone(parsed.data))
    if (allowed) this.allowedEndpoints.add(parsed.data.canonical_ref)
    else this.allowedEndpoints.delete(parsed.data.canonical_ref)
    return clone(parsed.data)
  }

  revokeEndpoint(endpointRef: string): void {
    this.allowedEndpoints.delete(endpointRef.trim())
  }

  getEndpoint(endpointRef: string): SpatialEndpointDetails {
    const endpoint = this.endpoints.get(endpointRef.trim())
    if (!endpoint) throw new RemoteMediationError('ENDPOINT_NOT_REGISTERED', 'Endpoint is not present in the canonical local registry')
    return clone(endpoint)
  }

  createProvenance(endpointRef: string, requestId: string | null = null, correlationId = `correlation:${endpointRef}`): SpatialEndpointProvenance {
    const endpoint = this.getEndpoint(endpointRef)
    const provenance: SpatialEndpointProvenance = {
      schema_version: SPATIAL_SCHEMA_VERSIONS.endpointProvenance,
      provenance_id: safeId('provenance', this.options.idFactory, this.counter),
      workspace_id: this.options.workspaceId,
      node_id: this.options.nodeId,
      endpoint_ref: endpoint.canonical_ref,
      endpoint_revision: endpoint.revision,
      capability: endpoint.capability,
      provider_ref: endpoint.provider_ref,
      remote_node_ref: null,
      source_zone: 'REMOTE_UNTRUSTED',
      validation_state: 'UNVERIFIED',
      request_id: requestId,
      correlation_id: correlationId,
      observed_at: nowIso(this.options.now ?? (() => new Date())),
      untrusted: true,
    }
    const parsed = parseSpatialEndpointProvenance(provenance)
    if (!parsed.ok) throw new RemoteMediationError('ENDPOINT_NOT_REGISTERED', `Endpoint provenance rejected at ${parsed.diagnostic.path}`)
    this.recordEvent('provenance', parsed.data.provenance_id, requestId ?? undefined)
    return clone(parsed.data)
  }

  createContextManifest(input: CreateManifestInput): SpatialRemoteContextManifest {
    const endpoint = this.getEndpoint(input.endpointRef)
    if (endpoint.capability !== input.capability) throw new RemoteMediationError('CAPABILITY_MISMATCH', 'Endpoint capability does not match the local intent')
    if (input.workspaceSessionRef.startsWith('workspace-') && !input.workspaceSessionRef.startsWith(`${this.options.workspaceId}:`)) {
      throw new RemoteMediationError('UNAUTHORIZED', 'Workspace Session is outside the local mediation scope', { requestId: input.requestId })
    }
    const fields = normalizedFields(input.fields)
    const requestedFields = input.allowedFields?.map((field) => field.trim()).filter(Boolean) ?? Object.keys(fields)
    const redactions: string[] = []
    const forbiddenFields: string[] = []
    const allowedFields = requestedFields.filter((field) => {
      if (SECRET_KEY.test(field)) {
        forbiddenFields.push(field)
        return false
      }
      return true
    })
    const minimizedFields: Record<string, ContextFieldValue> = {}
    for (const field of allowedFields) {
      if (fields[field] === undefined) continue
      minimizedFields[field] = fields[field]
    }
    for (const field of Object.keys(fields)) {
      if (!allowedFields.includes(field) || SECRET_KEY.test(field)) {
        if (!redactions.includes(field)) redactions.push(field)
      }
    }
    const mediaTypes = [...(input.mediaTypes ?? endpoint.input_formats)].slice(0, 16)
    if (endpoint.input_formats.length && mediaTypes.some((mediaType) => !matchesMime(mediaType, endpoint.input_formats))) {
      throw new RemoteMediationError('CONTEXT_FORBIDDEN', 'Context media type is not declared by the Endpoint', { requestId: input.requestId })
    }
    const sizeLimitBytes = Math.min(Math.max(1, input.sizeLimitBytes ?? endpoint.limits.payload_bytes ?? this.options.maxRequestBytes ?? DEFAULT_MAX_REQUEST_BYTES), this.options.maxRequestBytes ?? DEFAULT_MAX_REQUEST_BYTES)
    const manifestBody = JSON.stringify({ endpoint: endpoint.canonical_ref, capability: input.capability, fields: minimizedFields, attachments: input.attachmentRefs ?? [], purpose: input.purpose })
    const serializedSize = byteLength(manifestBody)
    if (serializedSize > sizeLimitBytes) throw new RemoteMediationError('CONTEXT_TOO_LARGE', 'Minimized context exceeds the Endpoint payload limit')
    const manifest: SpatialRemoteContextManifest = {
      schema_version: SPATIAL_SCHEMA_VERSIONS.remoteContextManifest,
      manifest_id: safeId('manifest', this.options.idFactory, this.counter),
      request_id: input.requestId,
      workspace_id: this.options.workspaceId,
      node_id: this.options.nodeId,
      workspace_session_ref: input.workspaceSessionRef,
      purpose: input.purpose.slice(0, 240),
      capability_ref: endpoint.capability,
      allowed_fields: allowedFields,
      fields: minimizedFields,
      attachment_refs: [...(input.attachmentRefs ?? [])],
      media_types: mediaTypes,
      size_limit_bytes: sizeLimitBytes,
      redactions,
      forbidden_fields: forbiddenFields,
      retention: input.retention ?? 'EPHEMERAL',
      consent_required: input.consentRequired ?? false,
      consent_granted: input.consentGranted ?? false,
      policy_revision: input.policyRevision ?? 0,
      manifest_hash: stableHash(manifestBody),
      created_at: nowIso(this.options.now ?? (() => new Date())),
    }
    if (manifest.consent_required && !manifest.consent_granted) throw new RemoteMediationError('CONSENT_REQUIRED', 'Operator consent is required before this context can cross the trust boundary', { requestId: input.requestId })
    const parsed = parseSpatialRemoteContextManifest(manifest)
    if (!parsed.ok) throw new RemoteMediationError('CONTEXT_FORBIDDEN', `Context manifest rejected at ${parsed.diagnostic.path}`, { requestId: input.requestId })
    this.recordEvent('manifest', parsed.data.manifest_id, input.requestId)
    return clone(parsed.data)
  }

  createEndpointTestFrame(input: CreateFrameInput): SpatialEndpointTestFrame {
    const endpoint = this.getEndpoint(input.endpointRef)
    if (input.sourceRevision !== undefined && input.sourceRevision !== endpoint.revision) throw new RemoteMediationError('STALE_ENDPOINT', 'Endpoint revision is stale')
    const now = nowIso(this.options.now ?? (() => new Date()))
    const frame: SpatialEndpointTestFrame = {
      schema_version: SPATIAL_SCHEMA_VERSIONS.endpointTestFrame,
      frame_id: input.frameId ?? safeId('endpoint-test-frame', this.options.idFactory, this.counter),
      workspace_id: this.options.workspaceId,
      node_id: this.options.nodeId,
      endpoint_ref: endpoint.canonical_ref,
      capability: endpoint.capability,
      input_schema: inputSchemaForEndpoint(endpoint),
      input_value_ref: null,
      submit_intent_ref: null,
      response_ref: null,
      accounting_ref: null,
      state: 'READY',
      source_revision: endpoint.revision,
      provenance_ref: null,
      created_at: now,
      updated_at: now,
    }
    const parsed = parseSpatialEndpointTestFrame(frame)
    if (!parsed.ok) throw new RemoteMediationError('ENDPOINT_NOT_REGISTERED', `Endpoint test frame rejected at ${parsed.diagnostic.path}`)
    this.frames.set(parsed.data.frame_id, parsed.data)
    this.recordEvent('frame', parsed.data.frame_id)
    return clone(parsed.data)
  }

  getFrame(frameId: string): SpatialEndpointTestFrame {
    const frame = this.frames.get(frameId.trim())
    if (!frame) throw new RemoteMediationError('ENDPOINT_NOT_REGISTERED', 'Endpoint Test Frame is not registered', { frameId })
    return clone(frame)
  }

  listFrames(): SpatialEndpointTestFrame[] {
    return [...this.frames.values()].map((frame) => clone(frame))
  }

  getRequest(requestId: string): SpatialRemoteRequest | null {
    const request = this.requests.get(requestId.trim())
    return request ? clone(request) : null
  }

  getResult(resultId: string): SpatialRemoteResult | null {
    const result = this.results.get(resultId.trim())
    return result ? clone(result) : null
  }

  getAccounting(requestId: string): SpatialResourceAccounting | null {
    const record = this.accounting.get(requestId.trim())
    return record ? clone(record) : null
  }

  getEvents(): RemoteMediationEvent[] {
    return this.eventLog.map((event) => ({ ...event }))
  }

  async submitEndpointTest(input: SubmitEndpointTestInput): Promise<RemoteSubmitResult> {
    const frame = this.getFrame(input.frameId)
    const endpoint = this.getEndpoint(frame.endpoint_ref)
    const idempotencyKey = (input.idempotencyKey ?? `${frame.frame_id}:${JSON.stringify(input.fields ?? {})}`).trim()
    const previous = this.idempotent.get(idempotencyKey)
    if (previous) return { ...previous, request: clone(previous.request), result: clone(previous.result), accounting: clone(previous.accounting), frame: clone(previous.frame), duplicate: true }
    if (frame.state === 'SUBMITTING' || frame.state === 'STREAMING') throw new RemoteMediationError('DUPLICATE_SUBMIT', 'An Endpoint Test request is already in flight', { frameId: frame.frame_id })
    if (!this.allowedEndpoints.has(endpoint.canonical_ref)) throw new RemoteMediationError('ENDPOINT_NOT_ALLOWED', 'Endpoint is denied by the local mediation policy', { frameId: frame.frame_id })
    if (endpoint.availability === 'UNAVAILABLE' || endpoint.surface_state === 'UNAVAILABLE') throw new RemoteMediationError('ENDPOINT_UNAVAILABLE', 'Endpoint is unavailable; no remote request was sent', { frameId: frame.frame_id })
    if (frame.source_revision !== endpoint.revision) throw new RemoteMediationError('STALE_ENDPOINT', 'Endpoint revision changed; refresh the local frame before submitting', { frameId: frame.frame_id })
    const workspaceSessionRef = input.workspaceSessionRef ?? this.options.defaultWorkspaceSessionRef ?? `${this.options.workspaceId}:session:manual`
    const requestId = safeId('remote-request', this.options.idFactory, this.counter)
    const authorization = this.options.authorize?.({ endpoint, capability: frame.capability, workspaceSessionRef, primaryAgentRef: this.options.primaryAgentRef }) ?? { allowed: true, grantRef: null, policyRevision: 0 }
    if (!authorization.allowed) throw new RemoteMediationError('UNAUTHORIZED', authorization.reason ?? 'Local authorization rejected this Endpoint', { requestId, frameId: frame.frame_id })
    const manifest = this.createContextManifest({
      requestId,
      endpointRef: endpoint.canonical_ref,
      capability: frame.capability,
      workspaceSessionRef,
      purpose: input.purpose ?? 'operator-endpoint-test',
      fields: input.fields,
      allowedFields: input.allowedFields,
      attachmentRefs: input.attachmentRefs,
      mediaTypes: input.mediaTypes,
      consentRequired: false,
      consentGranted: input.operatorConsent ?? false,
      policyRevision: authorization.policyRevision ?? 0,
      sizeLimitBytes: endpoint.limits.payload_bytes ?? undefined,
    })
    const requestBytes = byteLength(JSON.stringify({ fields: manifest.fields, attachments: manifest.attachment_refs }))
    const timeoutMs = Math.min(endpoint.limits.timeout_ms ?? this.options.defaultTimeoutMs ?? DEFAULT_TIMEOUT_MS, this.options.defaultTimeoutMs ?? DEFAULT_TIMEOUT_MS)
    const adapterId = this.options.defaultAdapterId ?? endpoint.provider_ref ?? 'node-mediated'
    const adapter = this.adapters.get(adapterId)
    if (!adapter) throw new RemoteMediationError('TRANSPORT_UNAVAILABLE', 'No Node transport adapter is registered; direct transport is prohibited', { requestId, frameId: frame.frame_id })
    const correlationId = safeId('correlation', this.options.idFactory, this.counter)
    const provenance = this.createProvenance(endpoint.canonical_ref, requestId, correlationId)
    const request: SpatialRemoteRequest = {
      schema_version: SPATIAL_SCHEMA_VERSIONS.remoteRequest,
      request_id: requestId,
      local_node_id: this.options.nodeId,
      local_primary_agent_ref: this.options.primaryAgentRef,
      local_session_ref: workspaceSessionRef,
      endpoint_ref: endpoint.canonical_ref,
      endpoint_revision: endpoint.revision,
      capability: frame.capability,
      input_refs: manifest.attachment_refs,
      context_manifest: manifest,
      authorization: { state: 'AUTHORIZED', grant_ref: authorization.grantRef ?? null, policy_revision: authorization.policyRevision ?? 0 },
      resource_budget: this.budgetForEndpoint(endpoint, requestBytes),
      transport: { adapter_id: adapter.id, timeout_ms: timeoutMs, request_bytes: requestBytes },
      state: 'SUBMITTING',
      idempotency_key: idempotencyKey,
      correlation_id: correlationId,
      created_at: nowIso(this.options.now ?? (() => new Date())),
      provenance,
    }
    const parsedRequest = parseSpatialRemoteRequest(request)
    if (!parsedRequest.ok) throw new RemoteMediationError('UNAUTHORIZED', `Remote request rejected at ${parsedRequest.diagnostic.path}`, { requestId, frameId: frame.frame_id })
    this.requests.set(requestId, parsedRequest.data)
    this.updateFrame(frame.frame_id, { state: 'SUBMITTING', submit_intent_ref: requestId, provenance_ref: provenance.provenance_id })
    this.recordEvent('request', requestId, requestId)

    const controller = new AbortController()
    this.controllers.set(requestId, controller)
    let timer: ReturnType<typeof setTimeout> | undefined
    try {
      const timeout = new Promise<never>((_, reject) => {
        timer = setTimeout(() => {
          controller.abort()
          reject(new RemoteMediationError('TIMEOUT', 'Remote Endpoint timed out', { requestId, frameId: frame.frame_id }))
        }, timeoutMs)
      })
      const response = await Promise.race([adapter.send(parsedRequest.data, controller.signal), timeout])
      if (controller.signal.aborted) throw new RemoteMediationError('TIMEOUT', 'Remote Endpoint timed out', { requestId, frameId: frame.frame_id })
      const result = this.validateRemoteResult(parsedRequest.data, endpoint, response)
      this.results.set(result.result_id, result)
      this.recordEvent('result', result.result_id, requestId)
      const accounting = this.settleAccounting(parsedRequest.data, endpoint, response.sizeBytes ?? byteLength(sanitizedText(response.payload)), result.validation.status === 'VALID' || result.validation.status === 'SANITIZED' ? 'SETTLED' : 'FAILED')
      const parsedAccounting = parseSpatialResourceAccounting(accounting)
      if (!parsedAccounting.ok) throw new RemoteMediationError('INVALID_RESULT', `Accounting record rejected at ${parsedAccounting.diagnostic.path}`, { requestId, frameId: frame.frame_id })
      this.accounting.set(requestId, parsedAccounting.data)
      this.recordEvent('accounting', parsedAccounting.data.record_id, requestId)
      const finalState: SpatialEndpointTestFrameState = result.validation.status === 'QUARANTINED' || result.validation.status === 'INVALID' ? 'INVALID_RESULT' : 'COMPLETE'
      const finalFrame = this.updateFrame(frame.frame_id, { state: finalState, response_ref: result.result_id, accounting_ref: parsedAccounting.data.record_id })
      const submitted: RemoteSubmitResult = { request: clone(parsedRequest.data), result: clone(result), accounting: clone(parsedAccounting.data), frame: finalFrame, duplicate: false }
      this.idempotent.set(idempotencyKey, submitted)
      return submitted
    } catch (error) {
      const cancelledByOperator = this.cancelledRequests.has(requestId)
      const mediationError = cancelledByOperator
        ? new RemoteMediationError('CANCELLED', 'Remote Endpoint request was cancelled locally', { requestId, frameId: frame.frame_id })
        : error instanceof RemoteMediationError
          ? error
          : controller.signal.aborted
          ? new RemoteMediationError('TIMEOUT', 'Remote Endpoint timed out', { requestId, frameId: frame.frame_id })
          : new RemoteMediationError('TRANSPORT_ERROR', 'Node transport adapter failed', { requestId, frameId: frame.frame_id })
      this.updateFrame(frame.frame_id, { state: mediationError.code === 'TIMEOUT' ? 'TIMEOUT' : mediationError.code === 'CANCELLED' ? 'CANCELLED' : mediationError.code === 'ENDPOINT_UNAVAILABLE' ? 'UNAVAILABLE' : 'REJECTED' })
      throw mediationError
    } finally {
      if (timer) clearTimeout(timer)
      this.controllers.delete(requestId)
      this.cancelledRequests.delete(requestId)
    }
  }

  cancelEndpointTest(frameId: string): SpatialEndpointTestFrame {
    const frame = this.getFrame(frameId)
    const requestId = frame.submit_intent_ref
    if (requestId) {
      this.cancelledRequests.add(requestId)
      this.controllers.get(requestId)?.abort()
    }
    return this.updateFrame(frameId, { state: 'CANCELLED' })
  }

  validateRemoteResult(request: SpatialRemoteRequest, endpoint: SpatialEndpointDetails, response: RemoteTransportResponse): SpatialRemoteResult {
    const contentType = response.contentType.trim().toLowerCase().split(';', 1)[0] ?? ''
    const rawText = typeof response.payload === 'string' ? response.payload : JSON.stringify(response.payload) ?? String(response.payload)
    const text = sanitizedText(response.payload)
    const sizeBytes = response.sizeBytes ?? byteLength(text)
    let classification: SpatialRemoteResultClassification = 'NONE'
    let status: SpatialRemoteResult['validation']['status'] = 'VALID'
    if (sizeBytes > (this.options.maxResponseBytes ?? DEFAULT_MAX_RESPONSE_BYTES)) {
      classification = 'OVERSIZED'
      status = 'QUARANTINED'
    } else if (!matchesMime(contentType, endpoint.output_formats)) {
      classification = 'MIME_MISMATCH'
      status = 'INVALID'
    } else if (hasUnboundedStream(response.payload)) {
      classification = 'OVERSIZED'
      status = 'QUARANTINED'
    } else if (hasRemoteUiPayload(response.payload)) {
      classification = 'UNSAFE_HTML'
      status = 'QUARANTINED'
    } else if (SCRIPT_OR_HTML.test(rawText)) {
      classification = rawText.toLowerCase().includes('<script') || /javascript\s*:/.test(rawText.toLowerCase()) ? 'SCRIPT' : 'UNSAFE_HTML'
      status = 'QUARANTINED'
    } else if (SECRET_VALUE.test(text)) {
      classification = 'SECRET_PATTERN'
      status = 'QUARANTINED'
    } else if (PROMPT_INJECTION.test(text)) {
      classification = 'PROMPT_INJECTION'
      status = 'QUARANTINED'
    }
    const provenance = { ...request.provenance, request_id: request.request_id, validation_state: status === 'VALID' ? 'VERIFIED' as const : 'UNVERIFIED' as const, observed_at: nowIso(this.options.now ?? (() => new Date())) }
    const safePreview = classification === 'SECRET_PATTERN' ? text.replace(SECRET_VALUE, '[redacted-secret]') : text
    const result: SpatialRemoteResult = {
      schema_version: SPATIAL_SCHEMA_VERSIONS.remoteResult,
      result_id: safeId('remote-result', this.options.idFactory, this.counter),
      request_id: request.request_id,
      endpoint_ref: request.endpoint_ref,
      endpoint_revision: request.endpoint_revision,
      content_type: contentType || 'text/plain',
      validation: { status, classification, schema: null, size_bytes: sizeBytes },
      safe_text: status === 'QUARANTINED' ? `Remote output quarantined (${classification.toLowerCase()}). ${safePreview.slice(0, 512)}` : status === 'INVALID' ? 'Remote output rejected by the local validator.' : text,
      payload_ref: null,
      untrusted: true,
      provenance,
      received_at: nowIso(this.options.now ?? (() => new Date())),
      correlation_id: request.correlation_id,
    }
    const parsed = parseSpatialRemoteResult(result)
    if (!parsed.ok) throw new RemoteMediationError('INVALID_RESULT', `Remote result rejected at ${parsed.diagnostic.path}`, { requestId: request.request_id })
    return parsed.data
  }

  private budgetForEndpoint(endpoint: SpatialEndpointDetails, requestBytes: number): SpatialRemoteRequest['resource_budget'] {
    const metered = endpoint.cost.unit_price !== null
    return { policy: metered ? 'METERED' : 'FREE', estimate_units: metered ? Math.max(1, Math.ceil(requestBytes / 1024)) : 0, max_units: endpoint.capacity }
  }

  private settleAccounting(request: SpatialRemoteRequest, endpoint: SpatialEndpointDetails, outputBytes: number, state: SpatialResourceAccounting['state']): SpatialResourceAccounting {
    const inputUnits = Math.max(0, Math.ceil(request.transport.request_bytes / 1024))
    const outputUnits = Math.max(0, Math.ceil(outputBytes / 1024))
    const metered = request.resource_budget.policy === 'METERED'
    const now = nowIso(this.options.now ?? (() => new Date()))
    const record: SpatialResourceAccounting = {
      schema_version: SPATIAL_SCHEMA_VERSIONS.resourceAccounting,
      record_id: safeId('accounting', this.options.idFactory, this.counter),
      request_id: request.request_id,
      node_id: this.options.nodeId,
      workspace_session_ref: request.local_session_ref,
      protocol_session_ref: null,
      endpoint_ref: endpoint.canonical_ref,
      rate_card_revision: endpoint.revision,
      billing_policy: metered ? 'METERED' : 'FREE',
      input_units: metered ? inputUnits : 0,
      output_units: metered ? outputUnits : 0,
      estimate_units: request.resource_budget.estimate_units,
      measured_units: metered ? inputUnits + outputUnits : 0,
      settlement_ref: null,
      charge_policy: metered ? 'CHARGE_ON_ACCEPTED_RESULT' : 'NO_CHARGE',
      state,
      authoritative_source: 'NODE',
      created_at: now,
      updated_at: now,
    }
    return record
  }

  private updateFrame(frameId: string, patch: Partial<SpatialEndpointTestFrame>): SpatialEndpointTestFrame {
    const current = this.getFrame(frameId)
    const updated = { ...current, ...patch, updated_at: nowIso(this.options.now ?? (() => new Date())) }
    const parsed = parseSpatialEndpointTestFrame(updated)
    if (!parsed.ok) throw new RemoteMediationError('ENDPOINT_NOT_REGISTERED', `Endpoint Test Frame update rejected at ${parsed.diagnostic.path}`, { frameId })
    this.frames.set(frameId, parsed.data)
    this.recordEvent('frame', frameId, parsed.data.submit_intent_ref ?? undefined)
    return clone(parsed.data)
  }

  private recordEvent(type: RemoteMediationEvent['type'], id: string, requestId?: string): void {
    this.eventLog.push({ type, id, requestId, occurredAt: nowIso(this.options.now ?? (() => new Date())) })
  }
}

export const RemoteMediationService = LocalRemoteMediationService
