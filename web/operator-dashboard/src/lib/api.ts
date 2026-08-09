import type { z } from 'zod'

import { dashboardSchemas, type BundlePayload, type DashboardHome, type EndpointPayload, type Fleet, type Readiness } from '@/lib/types'

const apiRoot = (import.meta.env.VITE_AIDN_API_ROOT ?? '').replace(/\/$/, '')
const requestTimeoutMs = 15_000

export class DashboardApiError extends Error {
  readonly status: number | undefined

  constructor(message: string, status?: number) {
    super(message)
    this.name = 'DashboardApiError'
    this.status = status
  }
}

export type AccessCredential = {
  credential_id: string
  label: string
  scopes: string[]
  fingerprint: string
  state: 'active' | 'revoked' | string
  created_at: string
  last_used_at: string | null
  token?: string
}

export type DashboardAccessStatus = {
  enabled: boolean
  session: { active: boolean; expires_at: string | null }
  transport: { insecure_lan: boolean }
  operator_authority: { configured: boolean; fingerprint: string | null }
  credentials: AccessCredential[]
}

export type EnrollmentRequest = {
  request_id: string
  label: string
  key_fingerprint: string
  state: 'pending' | 'approved' | 'rejected' | 'expired' | string
  created_at: string
  expires_at: string
}

export type AgentPermission = {
  scope: string
  label: string
  description: string
  category: 'Read' | 'Actions' | string
  risk: 'low' | 'high' | 'critical' | string
  tool_names: string[]
}

export type AgentPermissionCatalog = {
  items: AgentPermission[]
  default_scopes: string[]
  note: string
}

async function readDashboard<T>(path: string, schema: z.ZodType<T>, signal?: AbortSignal): Promise<T> {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), requestTimeoutMs)
  const abortRequest = () => controller.abort()
  signal?.addEventListener('abort', abortRequest, { once: true })

  try {
    const response = await fetch(`${apiRoot}${path}`, {
      headers: { Accept: 'application/json' },
      signal: controller.signal,
    })
    const text = await response.text()
    let payload: unknown
    try {
      payload = text ? JSON.parse(text) : null
    } catch {
      throw new DashboardApiError(`The Hypervisor returned invalid JSON for ${path}.`, response.status)
    }
    if (!response.ok) {
      const detail = typeof payload === 'object' && payload !== null && 'detail' in payload ? String(payload.detail) : response.statusText
      throw new DashboardApiError(`${path} failed: ${detail || 'unknown error'}`, response.status)
    }
    const parsed = schema.safeParse(payload)
    if (!parsed.success) {
      throw new DashboardApiError(`The Hypervisor returned an incompatible dashboard response for ${path}.`, response.status)
    }
    return parsed.data
  } catch (error) {
    if (error instanceof DashboardApiError) throw error
    if (controller.signal.aborted && !signal?.aborted) {
      throw new DashboardApiError(`${path} did not respond within ${requestTimeoutMs / 1000} seconds.`)
    }
    throw new DashboardApiError(error instanceof Error ? error.message : `Unable to load ${path}.`)
  } finally {
    clearTimeout(timeout)
    signal?.removeEventListener('abort', abortRequest)
  }
}

async function writeDashboard<T>(path: string, init: RequestInit): Promise<T | undefined> {
  const response = await fetch(`${apiRoot}${path}`, {
    credentials: 'same-origin',
    headers: { Accept: 'application/json', ...(init.body ? { 'Content-Type': 'application/json' } : {}) },
    ...init,
  })
  const text = await response.text()
  let payload: unknown
  try {
    payload = text ? JSON.parse(text) : undefined
  } catch {
    throw new DashboardApiError(`The Hypervisor returned invalid JSON for ${path}.`, response.status)
  }
  if (!response.ok) {
    const error = typeof payload === 'object' && payload !== null && 'error' in payload
      ? String((payload as { error?: { code?: string } }).error?.code ?? 'request rejected')
      : response.statusText
    throw new DashboardApiError(`${path} failed: ${error || 'request rejected'}`, response.status)
  }
  return payload as T | undefined
}

export const dashboardApi = {
  home: (signal?: AbortSignal): Promise<DashboardHome> => readDashboard('/operators/dashboard/home', dashboardSchemas.home, signal),
  readiness: (signal?: AbortSignal): Promise<Readiness> => readDashboard('/operators/dashboard/readiness', dashboardSchemas.readiness, signal),
  fleet: (signal?: AbortSignal): Promise<Fleet> => readDashboard('/operators/dashboard/fleet', dashboardSchemas.fleet, signal),
  bundles: (signal?: AbortSignal): Promise<BundlePayload> => readDashboard('/operators/dashboard/bundles', dashboardSchemas.bundles, signal),
  endpoints: (signal?: AbortSignal): Promise<EndpointPayload> => readDashboard('/operators/dashboard/endpoints', dashboardSchemas.endpoints, signal),
  accessStatus: (): Promise<DashboardAccessStatus> => writeDashboard('/operators/dashboard/access/status', { method: 'GET' }) as Promise<DashboardAccessStatus>,
  pairDashboard: (code: string) => writeDashboard('/operators/dashboard/access/pair', { method: 'POST', body: JSON.stringify({ code }) }),
  createAgentCredential: (label: string, scopes?: string[]) => writeDashboard<AccessCredential>('/operators/dashboard/access/credentials', { method: 'POST', body: JSON.stringify({ label, ...(scopes ? { scopes } : {}) }) }),
  agentPermissionCatalog: () => writeDashboard<AgentPermissionCatalog>('/operators/dashboard/access/permission-catalog', { method: 'GET' }),
  updateAgentCredentialScopes: (credentialId: string, scopes: string[]) => writeDashboard<AccessCredential>(`/operators/dashboard/access/credentials/${credentialId}/scopes`, { method: 'PUT', body: JSON.stringify({ scopes }) }),
  rotateAgentCredential: (credentialId: string) => writeDashboard<AccessCredential>(`/operators/dashboard/access/credentials/${credentialId}/rotate`, { method: 'POST' }),
  revokeAgentCredential: (credentialId: string) => writeDashboard(`/operators/dashboard/access/credentials/${credentialId}`, { method: 'DELETE' }),
  logoutDashboardAccess: () => writeDashboard('/operators/dashboard/access/logout', { method: 'POST' }),
  enrollmentRequests: () => writeDashboard<{ items: EnrollmentRequest[] }>('/operators/dashboard/access/enrollment-requests', { method: 'GET' }),
  approveEnrollment: (requestId: string) => writeDashboard<EnrollmentRequest>(`/operators/dashboard/access/enrollment-requests/${requestId}/approve`, { method: 'POST' }),
  rejectEnrollment: (requestId: string) => writeDashboard<EnrollmentRequest>(`/operators/dashboard/access/enrollment-requests/${requestId}/reject`, { method: 'POST' }),
}
