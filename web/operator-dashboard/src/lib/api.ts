import { z } from 'zod'

import { dashboardSchemas, type BundlePayload, type DashboardHome, type EndpointPayload, type Fleet, type MarketDashboard, type Readiness, type RemoteEndpointsDashboard, type SessionDashboard, type WalletDashboard } from '@/lib/types'

const apiRoot = (import.meta.env.VITE_AIDN_API_ROOT ?? '').replace(/\/$/, '')
const requestTimeoutMs = 15_000
const browserKeyStorageKey = 'aidn.dashboard.browser-key.v1'

function browserKey(): string {
  const existing = window.localStorage.getItem(browserKeyStorageKey)
  if (existing && existing.length >= 32) return existing
  const bytes = new Uint8Array(32)
  window.crypto.getRandomValues(bytes)
  const value = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('')
  window.localStorage.setItem(browserKeyStorageKey, value)
  return value
}

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
  auto_approved_scopes: string[]
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
  approval_key: string | null
}

export type AgentPermissionCatalog = {
  items: AgentPermission[]
  default_scopes: string[]
  full_control_scopes: string[]
  full_control_auto_approved_scopes: string[]
  note: string
}

export type DashboardRecord = Record<string, unknown>

export type ProviderArtifactInventory = DashboardRecord[] | DashboardRecord

export type ProviderWorkspace = {
  plugin_directory: DashboardRecord[]
  installation_executor?: DashboardRecord
  provider_instances: DashboardRecord[]
  model_deployments: DashboardRecord[]
  runtime_bindings: DashboardRecord[]
  installation_artifacts: ProviderArtifactInventory
  model_artifacts: ProviderArtifactInventory
  model_artifact_sets: ProviderArtifactInventory
  artifact_materializations: ProviderArtifactInventory
  summary: DashboardRecord
}

export type ModelInstallWorkspace = {
  items: DashboardRecord[]
  summary: DashboardRecord
}

const dashboardRecordSchema = z.record(z.string(), z.unknown())
const providerArtifactInventorySchema = z.union([
  z.array(dashboardRecordSchema),
  dashboardRecordSchema,
]).default([])

const providerWorkspaceSchema = z.object({
  plugin_directory: z.array(z.record(z.string(), z.unknown())).default([]),
  installation_executor: z.record(z.string(), z.unknown()).optional(),
  provider_instances: z.array(z.record(z.string(), z.unknown())).default([]),
  model_deployments: z.array(z.record(z.string(), z.unknown())).default([]),
  runtime_bindings: z.array(z.record(z.string(), z.unknown())).default([]),
  installation_artifacts: providerArtifactInventorySchema,
  model_artifacts: providerArtifactInventorySchema,
  model_artifact_sets: providerArtifactInventorySchema,
  artifact_materializations: providerArtifactInventorySchema,
  summary: z.record(z.string(), z.unknown()).default({}),
}).passthrough()

const modelInstallWorkspaceSchema = z.object({
  items: z.array(z.record(z.string(), z.unknown())).default([]),
  summary: z.record(z.string(), z.unknown()).default({}),
}).passthrough()

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
    headers: { Accept: 'application/json', 'X-AiDN-Browser-Key': browserKey(), ...(init.body ? { 'Content-Type': 'application/json' } : {}) },
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
      ? String((payload as { error?: { code?: string; message?: string } }).error?.message ?? (payload as { error?: { code?: string } }).error?.code ?? 'request rejected')
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
  wallet: (signal?: AbortSignal): Promise<WalletDashboard> => readDashboard('/operators/dashboard/wallet', dashboardSchemas.wallet, signal),
  providers: (signal?: AbortSignal): Promise<ProviderWorkspace> => readDashboard('/operators/dashboard/providers', providerWorkspaceSchema, signal),
  installs: (signal?: AbortSignal): Promise<ModelInstallWorkspace> => readDashboard('/operators/dashboard/installs', modelInstallWorkspaceSchema, signal),
  sessions: (signal?: AbortSignal): Promise<SessionDashboard> => readDashboard('/operators/dashboard/sessions', dashboardSchemas.sessions, signal),
  market: (signal?: AbortSignal): Promise<MarketDashboard> => readDashboard('/operators/dashboard/market', dashboardSchemas.market, signal),
  remoteEndpoints: (signal?: AbortSignal): Promise<RemoteEndpointsDashboard> => readDashboard('/operators/dashboard/remote-endpoints', dashboardSchemas.remoteEndpoints, signal),
  events: (signal?: AbortSignal) => readDashboard('/operators/events?limit=24', dashboardSchemas.events, signal),
  accessStatus: (): Promise<DashboardAccessStatus> => writeDashboard('/operators/dashboard/access/status', { method: 'GET' }) as Promise<DashboardAccessStatus>,
  pairDashboard: (code: string, duration: string) => writeDashboard('/operators/dashboard/access/pair', { method: 'POST', body: JSON.stringify({ code, duration }) }),
  createAgentCredential: (label: string, scopes?: string[], autoApprovedScopes?: string[]) => writeDashboard<AccessCredential>('/operators/dashboard/access/credentials', { method: 'POST', body: JSON.stringify({ label, ...(scopes ? { scopes } : {}), ...(autoApprovedScopes ? { auto_approved_scopes: autoApprovedScopes } : {}) }) }),
  agentPermissionCatalog: () => writeDashboard<AgentPermissionCatalog>('/operators/dashboard/access/permission-catalog', { method: 'GET' }),
  updateAgentCredentialScopes: (credentialId: string, scopes: string[], autoApprovedScopes: string[]) => writeDashboard<AccessCredential>(`/operators/dashboard/access/credentials/${credentialId}/scopes`, { method: 'PUT', body: JSON.stringify({ scopes, auto_approved_scopes: autoApprovedScopes }) }),
  rotateAgentCredential: (credentialId: string) => writeDashboard<AccessCredential>(`/operators/dashboard/access/credentials/${credentialId}/rotate`, { method: 'POST' }),
  revokeAgentCredential: (credentialId: string) => writeDashboard(`/operators/dashboard/access/credentials/${credentialId}`, { method: 'DELETE' }),
  logoutDashboardAccess: () => writeDashboard('/operators/dashboard/access/logout', { method: 'POST' }),
  enrollmentRequests: () => writeDashboard<{ items: EnrollmentRequest[] }>('/operators/dashboard/access/enrollment-requests', { method: 'GET' }),
  approveEnrollment: (requestId: string) => writeDashboard<EnrollmentRequest>(`/operators/dashboard/access/enrollment-requests/${requestId}/approve`, { method: 'POST' }),
  rejectEnrollment: (requestId: string) => writeDashboard<EnrollmentRequest>(`/operators/dashboard/access/enrollment-requests/${requestId}/reject`, { method: 'POST' }),
  probeResources: () => writeDashboard('/operators/dashboard/access/operations/resources/probe', { method: 'POST' }),
  createOwnerWallet: (label: string) => writeDashboard<DashboardRecord>('/operators/dashboard/access/operations/wallet/create', { method: 'POST', body: JSON.stringify({ label: label || null }) }),
  importOwnerWallet: (label: string, privateKey: string) => writeDashboard<DashboardRecord>('/operators/dashboard/access/operations/wallet/import', { method: 'POST', body: JSON.stringify({ label: label || null, private_key: privateKey }) }),
  registerOwnerWalletIdentity: () => writeDashboard<DashboardRecord>('/operators/dashboard/access/operations/wallet/identity/register', { method: 'POST' }),
  previewWalletTransfer: (payload: { recipient_wallet: string; amount_q_atoms: number; memo?: string }) => writeDashboard<DashboardRecord>('/operators/dashboard/access/operations/wallet/transfer/preview', { method: 'POST', body: JSON.stringify(payload) }),
  submitWalletTransfer: (payload: { recipient_wallet: string; amount_q_atoms: number; memo?: string }) => writeDashboard<DashboardRecord>('/operators/dashboard/access/operations/wallet/transfer', { method: 'POST', body: JSON.stringify(payload) }),
  bundleOperation: (bundleId: string, action: 'enable' | 'disable' | 'retry' | 'reset-cooldown') => writeDashboard(`/operators/dashboard/access/operations/bundles/${encodeURIComponent(bundleId)}/${action}`, { method: 'POST' }),
  attachProvider: (payload: { plugin_id: string; display_name: string; configuration: DashboardRecord }) => writeDashboard<DashboardRecord>('/operators/dashboard/access/operations/providers/attach', { method: 'POST', body: JSON.stringify(payload) }),
  installProviderRuntime: (pluginId: string, configuration: DashboardRecord, operatorNote?: string) => writeDashboard<DashboardRecord>(`/operators/dashboard/access/operations/provider-plugins/${encodeURIComponent(pluginId)}/install`, { method: 'POST', body: JSON.stringify({ configuration, ...(operatorNote ? { operator_note: operatorNote } : {}) }) }),
  providerOperation: (providerInstanceId: string, action: 'probe' | 'discover-models') => writeDashboard(`/operators/dashboard/access/operations/providers/${encodeURIComponent(providerInstanceId)}/${action}`, { method: 'POST' }),
  requestModelInstall: (payload: { provider_type: string; model_id: string; source_url: string; requested_by?: string }) => writeDashboard<DashboardRecord>('/operators/dashboard/access/operations/models/install', { method: 'POST', body: JSON.stringify({ requested_by: 'operator-dashboard', ...payload }) }),
  processModelInstalls: () => writeDashboard<{ items: DashboardRecord[] }>('/operators/dashboard/access/operations/models/install/process', { method: 'POST' }),
  registerBundleFromInstall: (installId: string, payload: { bundle_id: string; workload_type: string; endpoint: string }) => writeDashboard<DashboardRecord>(`/operators/dashboard/access/operations/models/${encodeURIComponent(installId)}/register-bundle`, { method: 'POST', body: JSON.stringify(payload) }),
  createModelArtifactSet: (payload: { display_name: string; files: DashboardRecord[] }) => writeDashboard<DashboardRecord>('/operators/dashboard/access/operations/model-artifact-sets', { method: 'POST', body: JSON.stringify(payload) }),
  bindModelArtifactSet: (deploymentId: string, artifactSetId: string) => writeDashboard<DashboardRecord>(`/operators/dashboard/access/operations/model-deployments/${encodeURIComponent(deploymentId)}/artifact-set`, { method: 'POST', body: JSON.stringify({ artifact_set_id: artifactSetId }) }),
  materializeModelArtifactSet: (providerInstanceId: string, artifactSetId: string, destination: string) => writeDashboard<DashboardRecord>(`/operators/dashboard/access/operations/provider-instances/${encodeURIComponent(providerInstanceId)}/artifact-sets/materialize`, { method: 'POST', body: JSON.stringify({ artifact_set_id: artifactSetId, destination }) }),
  createRuntimeBinding: (deploymentId: string, payload: { capability_id: string; capability_version: string; capability_definition_hash: string }) => writeDashboard<DashboardRecord>(`/operators/dashboard/access/operations/model-deployments/${encodeURIComponent(deploymentId)}/runtime-bindings`, { method: 'POST', body: JSON.stringify(payload) }),
  createBundleRevision: (sourceBundleId: string, payload: { bundle_id: string; overrides: DashboardRecord; enabled?: boolean }) => writeDashboard<DashboardRecord>(`/operators/dashboard/access/operations/bundles/${encodeURIComponent(sourceBundleId)}/revisions`, { method: 'POST', body: JSON.stringify(payload) }),
  createEndpoint: (payload: DashboardRecord) => writeDashboard<DashboardRecord>('/operators/dashboard/access/operations/endpoints', { method: 'POST', body: JSON.stringify(payload) }),
  previewMarketplaceDescription: (html: string) => writeDashboard<DashboardRecord>('/operators/dashboard/access/operations/endpoints/marketplace-description/preview', { method: 'POST', body: JSON.stringify({ html }) }),
  updateEndpoint: (endpointId: string, payload: DashboardRecord) => writeDashboard<DashboardRecord>(`/operators/dashboard/access/operations/endpoints/${encodeURIComponent(endpointId)}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  publishEndpoint: (endpointId: string) => writeDashboard<DashboardRecord>(`/operators/dashboard/access/operations/endpoints/${encodeURIComponent(endpointId)}/publish`, { method: 'POST' }),
  requestEndpointValidation: (endpointId: string) => writeDashboard<DashboardRecord>(`/operators/dashboard/access/operations/endpoints/${encodeURIComponent(endpointId)}/validation`, { method: 'POST' }),
  closeSession: (sessionId: string) => writeDashboard<DashboardRecord>('/operators/dashboard/sessions/actions/close', { method: 'POST', body: JSON.stringify({ session_id: sessionId }) }),
  sweepIdleSessions: () => writeDashboard<{ closed_count: number; items: DashboardRecord[] }>('/operators/dashboard/sessions/actions/sweep-idle', { method: 'POST', body: JSON.stringify({}) }),
  attachRemoteEndpoint: (payload: { node_id: string; endpoint_id: string; alias?: string; routing_mode?: string }) => writeDashboard<DashboardRecord>('/operators/remote-endpoints/attach', { method: 'POST', body: JSON.stringify(payload) }),
  detachRemoteEndpoint: (remoteEndpointId: string) => writeDashboard<DashboardRecord>(`/operators/remote-endpoints/${encodeURIComponent(remoteEndpointId)}`, { method: 'DELETE' }),
}
