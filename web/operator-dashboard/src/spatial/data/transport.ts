import { spatialIdSchema, type SpatialSchemaVersion } from '@/spatial/contracts'

import { normalizeSpatialNodeScope, type SpatialNodeScope } from './scope'

export type SpatialTransportMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'

export type SpatialTransportRequest = {
  path: string
  method?: SpatialTransportMethod
  scope: SpatialNodeScope
  signal?: AbortSignal
  body?: unknown
  headers?: Record<string, string>
}

export type SpatialAuthAdapter = {
  headers?: (request: SpatialTransportRequest) => Record<string, string>
  credentials?: RequestCredentials
}

export type SpatialTransportFetcher = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>

export type SpatialApiErrorCategory =
  | 'unauthorized'
  | 'forbidden'
  | 'conflict'
  | 'validation'
  | 'not-found'
  | 'timeout'
  | 'network'
  | 'malformed'
  | 'incompatible'
  | 'unknown'

export class SpatialApiError extends Error {
  readonly category: SpatialApiErrorCategory
  readonly status?: number
  readonly path: string
  readonly contract?: SpatialSchemaVersion

  constructor(category: SpatialApiErrorCategory, message: string, path: string, status?: number, contract?: SpatialSchemaVersion) {
    super(message)
    this.name = 'SpatialApiError'
    this.category = category
    this.path = path
    this.status = status
    this.contract = contract
  }
}

export type SpatialRequestMetadata = {
  request_id: string
  correlation_id: string
  idempotency_key: string
  hypervisor_id: string
  node_id: string
}

export type SpatialNonceFactory = () => string

function defaultNonce(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return crypto.randomUUID()
  return `spatial-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

export function createSpatialRequestMetadata(scope: SpatialNodeScope, nonceFactory: SpatialNonceFactory = defaultNonce): SpatialRequestMetadata {
  const normalized = normalizeSpatialNodeScope(scope)
  const requestId = nonceFactory()
  return {
    request_id: requestId,
    correlation_id: requestId,
    idempotency_key: requestId,
    hypervisor_id: normalized.hypervisor_id,
    node_id: normalized.node_id,
  }
}

function categoryForStatus(status: number): SpatialApiErrorCategory {
  if (status === 401) return 'unauthorized'
  if (status === 403) return 'forbidden'
  if (status === 404) return 'not-found'
  if (status === 409) return 'conflict'
  if (status === 422) return 'validation'
  return 'unknown'
}

export type FetchSpatialTransportOptions = {
  apiRoot?: string
  auth?: SpatialAuthAdapter
  fetcher?: SpatialTransportFetcher
  timeoutMs?: number
}

export type SpatialTransport = {
  request: (request: SpatialTransportRequest) => Promise<unknown>
}

export function createFetchSpatialTransport(options: FetchSpatialTransportOptions = {}): SpatialTransport {
  const apiRoot = (options.apiRoot ?? '').replace(/\/$/, '')
  const auth = options.auth
  const fetcher = options.fetcher ?? ((input, init) => fetch(input, init))
  const timeoutMs = options.timeoutMs ?? 15_000

  return {
    async request(request) {
      const scope = normalizeSpatialNodeScope(request.scope)
      const controller = new AbortController()
      const timeout = setTimeout(() => controller.abort(), timeoutMs)
      const forwardAbort = () => controller.abort()
      request.signal?.addEventListener('abort', forwardAbort, { once: true })
      const metadata = createSpatialRequestMetadata(scope)
      const headers: Record<string, string> = {
        Accept: 'application/json',
        'X-AiDN-Request-Id': metadata.request_id,
        'X-AiDN-Correlation-Id': metadata.correlation_id,
        ...(request.method && request.method !== 'GET' ? { 'X-AiDN-Idempotency-Key': metadata.idempotency_key } : {}),
        ...(request.body !== undefined ? { 'Content-Type': 'application/json' } : {}),
        ...(auth?.headers?.(request) ?? {}),
        ...(request.headers ?? {}),
        // Scope headers are transport-owned and cannot be spoofed by a
        // per-call header override. Operation-specific idempotency/correlation
        // headers remain overridable through request.headers above.
        'X-AiDN-Hypervisor-Id': scope.hypervisor_id,
        'X-AiDN-Node-Id': scope.node_id,
        ...(request.method && request.method !== 'GET' && request.headers?.['X-AiDN-Idempotency-Key']
          ? { 'X-AiDN-Idempotency-Key': request.headers['X-AiDN-Idempotency-Key'] }
          : {}),
        ...(request.headers?.['X-AiDN-Correlation-Id'] ? { 'X-AiDN-Correlation-Id': request.headers['X-AiDN-Correlation-Id'] } : {}),
      }
      try {
        const response = await fetcher(`${apiRoot}${request.path}`, {
          method: request.method ?? 'GET',
          credentials: auth?.credentials ?? 'same-origin',
          headers,
          signal: controller.signal,
          ...(request.body !== undefined ? { body: JSON.stringify(request.body) } : {}),
        })
        const text = await response.text()
        let payload: unknown
        try {
          payload = text ? JSON.parse(text) : null
        } catch {
          throw new SpatialApiError('malformed', 'Spatial transport returned invalid JSON.', request.path, response.status)
        }
        if (!response.ok) {
          const category = categoryForStatus(response.status)
          throw new SpatialApiError(category, `Spatial request failed with HTTP ${response.status}.`, request.path, response.status)
        }
        return payload
      } catch (error) {
        if (error instanceof SpatialApiError) throw error
        if (controller.signal.aborted && !request.signal?.aborted) {
          throw new SpatialApiError('timeout', 'Spatial request timed out.', request.path)
        }
        throw new SpatialApiError('network', 'Spatial transport is unavailable.', request.path)
      } finally {
        clearTimeout(timeout)
        request.signal?.removeEventListener('abort', forwardAbort)
      }
    },
  }
}

export function assertSpatialScope(scope: SpatialNodeScope, expectedNodeId: string): void {
  const normalized = normalizeSpatialNodeScope(scope)
  if (normalized.node_id !== spatialIdSchema.parse(expectedNodeId)) {
    throw new SpatialApiError('conflict', 'Spatial response belongs to a different Node.', 'scope')
  }
}
