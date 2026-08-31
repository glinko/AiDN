import { z } from 'zod'

import { dashboardSchemas, type AssistedInstallationAction, type BundlePayload, type CometBftDashboard, type CometBftInstall, type DashboardHome, type EndpointPayload, type EscalationTasks, type Fleet, type InstallationPlan, type JourneyGraph, type MarketDashboard, type Readiness, type RemoteEndpointsDashboard, type ResidentAgentStatus, type ResidentInference, type ResourceBrokerDashboard, type RuntimeOperations, type SessionDashboard, type StewardActionPolicy, type WalletDashboard } from '@/lib/types'

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

export type InferenceCredential = {
  credential_id: string
  label: string
  endpoint_id: string
  model_alias: string
  owner_wallet: string
  fingerprint: string
  state: 'active' | 'revoked' | 'expired' | string
  created_at: string
  expires_at: string | null
  last_used_at: string | null
  session_id: string | null
  token?: string
  base_url?: string
}

export type EndpointRateQuote = {
  schema_version: 'pricing-quote.v1'
  rate_card_hash: string
  currency: 'Q_ATOM'
  supplied_usage: Record<string, number>
  known_components: Array<{
    component_id: string
    dimension: string
    measured_value: number
    normalized_value: number
    unit_price_q_atoms: number
    unit_divisor: number
    charge_q_atoms: number
  }>
  missing_dimensions: string[]
  lower_bound_q_atoms: number
  estimated_charge_q_atoms: number | null
}

export type EndpointQuoteEnvelope = {
  data: {
    endpoint_id: string
    configuration_hash: string
    minimum_escrow_deposit_q_atoms: number
    recommended_escrow_deposit_q_atoms: number | null
    quote: EndpointRateQuote
  }
  error: null
  correlation_id: string
}

export type EscrowDepositRecommendation = {
  schema_version: 'escrow-deposit-recommendation.v1'
  rate_card_hash: string
  safety_margin_bps: number
  recommended_multiplier: number
  usage_assumptions: Record<string, number>
  missing_dimensions: string[]
  estimated_request_charge_q_atoms: number | null
  minimum_deposit_q_atoms: number | null
  recommended_deposit_q_atoms: number | null
  automatic: boolean
}

export type DashboardNetworkAccess = {
  mode: 'loopback' | 'lan'
  configured_mode: 'loopback' | 'lan'
  effective_mode: 'loopback' | 'lan'
  configured_host: string
  effective_host: string
  restart_required: boolean
  restart_scheduled: boolean
  apply_supported: boolean
  port: number
}

export type OperatorConfigPayload = {
  status: 'configured' | 'missing' | 'unavailable' | string
  path: string | null
  format: 'toml' | string
  text: string
  sha256: string | null
  hidden_keys: string[]
  read_only_keys: string[]
  restart_supported: boolean
  restart_required?: boolean
  restart_scheduled: boolean
  changed_keys?: string[]
  warnings?: string[]
  last_modified: string | null
}

export type OperatorConfigValidation = {
  valid: boolean
  errors: string[]
  warnings: string[]
  changed_keys: string[]
  restart_required: boolean
  read_only_keys: string[]
}

export type SoftwareUpdatePayload = {
  status: 'idle' | 'up_to_date' | 'available' | 'updating' | 'restart_scheduled' | 'updated' | 'error' | 'unavailable' | string
  repository_url: string | null
  target_ref: string | null
  current_commit: string | null
  available_commit: string | null
  started_at: string | null
  checked_at: string | null
  finished_at: string | null
  restart_scheduled: boolean
  restart_required: boolean
  step: string | null
  message: string | null
  error: string | null
}

export type TestnetParticipationDashboard = {
  available: boolean
  runtime: { enabled: boolean; mode: 'disabled' | 'inspect' | 'dry_run' | 'submit' | string }
  program: {
    program_id: string
    network_id: string
    chain_id: string
    policy_hash: string
    participation_window_seconds: number
    settlement_period_seconds: number
    reward_per_eligible_window_q_atoms: number
  } | null
  monitor: { scan_count: number; transition_count: number; processed_count: number }
  last_settlement: {
    state: 'disabled' | 'not_due' | 'processed' | string
    source_epoch_transition_operation_id: string
    closing_epoch: number
    period_start: string | null
    detail: string | null
    accounting: {
      settlement_id: string
      settlement_hash: string
      program_policy_hash: string
      period_end: string
      eligible_node_count: number
      eligible_window_count: number
      total_reward_q_atoms: number
    } | null
    payout: {
      mode: string
      batch_status: string | null
      transfer_count: number
      submitted_operation_id: string | null
    } | null
  } | null
  last_error_code: string | null
}

export type DashboardAccessStatus = {
  enabled: boolean
  session: { active: boolean; expires_at: string | null }
  browser_binding: {
    first_browser_claim: { active: boolean; expires_at: string | null }
  }
  transport: { insecure_lan: boolean }
  operator_authority: { configured: boolean; fingerprint: string | null }
  network_access: DashboardNetworkAccess
  credentials: AccessCredential[]
  inference_credentials: InferenceCredential[]
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

export type LifecycleTransitionAction = 'DISABLE' | 'UNPUBLISH' | 'RETIRE'

export type LifecyclePlan = DashboardRecord & {
  plan_id?: string
  transition_id?: string
  plan_hash?: string
  target?: DashboardRecord
  action?: string
  current_state?: string
  target_state?: string
  requires_approval?: boolean
}

export type ProviderArtifactInventory = DashboardRecord[] | DashboardRecord

export type ProviderWorkspace = {
  plugin_directory: DashboardRecord[]
  installation_executor?: DashboardRecord
  provider_instances: DashboardRecord[]
  model_deployments: DashboardRecord[]
  runtime_bindings: DashboardRecord[]
  installation_jobs: DashboardRecord[]
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

export type HookEventFilter = {
  event_types: string[]
  resource_ids: string[]
  severity_minimum: string | null
}

export type HookDefinition = {
  hook_id: string
  owner_operator_id: string
  target_agent_id: string
  enabled: boolean
  event_filter: HookEventFilter
  delivery_mode: 'DURABLE_INBOX' | 'MCP_LIVE' | string
  max_attempts: number
  retry_backoff_seconds: number
  created_at: string
  expires_at: string | null
  hook_revision: number
}

export type HookDelivery = {
  delivery_id: string
  hook_id: string
  event_id: string
  target_agent_id: string
  delivery_mode: string
  status: string
  attempt_count: number
  next_attempt_at: string | null
  last_error: string | null
  created_at: string
  updated_at: string
  delivered_at: string | null
  replayed: boolean
}

export type HookMetrics = {
  events_matched: number
  deliveries_created: number
  deliveries_attempted: number
  events_delivered: number
  events_retried: number
  events_failed: number
  events_dead_lettered: number
  events_replayed: number
  queue_depth: number
  dead_letter_count: number
}

const dashboardRecordSchema = z.record(z.string(), z.unknown())
const numberValue = z.coerce.number().catch(0)
const stringValue = z.string().catch('')
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
  installation_jobs: z.array(z.record(z.string(), z.unknown())).default([]),
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

const testnetParticipationDashboardSchema = z.object({
  available: z.boolean().catch(false),
  runtime: z.object({ enabled: z.boolean().catch(false), mode: stringValue }).passthrough(),
  program: z.object({
    program_id: stringValue,
    network_id: stringValue,
    chain_id: stringValue,
    policy_hash: stringValue,
    participation_window_seconds: numberValue,
    settlement_period_seconds: numberValue,
    reward_per_eligible_window_q_atoms: numberValue,
  }).passthrough().nullable(),
  monitor: z.object({
    scan_count: numberValue,
    transition_count: numberValue,
    processed_count: numberValue,
  }).passthrough(),
  last_settlement: z.object({
    state: stringValue,
    source_epoch_transition_operation_id: stringValue,
    closing_epoch: numberValue,
    period_start: z.string().nullable().catch(null),
    detail: z.string().nullable().catch(null),
    accounting: z.object({
      settlement_id: stringValue,
      settlement_hash: stringValue,
      program_policy_hash: stringValue,
      period_end: stringValue,
      eligible_node_count: numberValue,
      eligible_window_count: numberValue,
      total_reward_q_atoms: numberValue,
    }).passthrough().nullable(),
    payout: z.object({
      mode: stringValue,
      batch_status: z.string().nullable().catch(null),
      transfer_count: numberValue,
      submitted_operation_id: z.string().nullable().catch(null),
    }).passthrough().nullable(),
  }).passthrough().nullable(),
  last_error_code: z.string().nullable().catch(null),
}).passthrough()

const hookEventFilterSchema = z.object({
  event_types: z.array(z.string()).catch([]),
  resource_ids: z.array(z.string()).catch([]),
  severity_minimum: z.string().nullable().catch(null),
}).passthrough()

const hookSchema = z.object({
  hook_id: z.string(),
  owner_operator_id: z.string(),
  target_agent_id: z.string(),
  enabled: z.boolean().catch(true),
  event_filter: hookEventFilterSchema,
  delivery_mode: z.string().catch('DURABLE_INBOX'),
  max_attempts: numberValue,
  retry_backoff_seconds: numberValue,
  created_at: z.string(),
  expires_at: z.string().nullable().catch(null),
  hook_revision: numberValue,
}).passthrough()

const hookDeliverySchema = z.object({
  delivery_id: z.string(),
  hook_id: z.string(),
  event_id: z.string(),
  target_agent_id: z.string(),
  delivery_mode: z.string(),
  status: z.string(),
  attempt_count: numberValue,
  next_attempt_at: z.string().nullable().catch(null),
  last_error: z.string().nullable().catch(null),
  created_at: z.string(),
  updated_at: z.string(),
  delivered_at: z.string().nullable().catch(null),
  replayed: z.boolean().catch(false),
}).passthrough()

const hookMetricsSchema = z.object({
  events_matched: numberValue,
  deliveries_created: numberValue,
  deliveries_attempted: numberValue,
  events_delivered: numberValue,
  events_retried: numberValue,
  events_failed: numberValue,
  events_dead_lettered: numberValue,
  events_replayed: numberValue,
  queue_depth: numberValue,
  dead_letter_count: numberValue,
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
  journey: (signal?: AbortSignal): Promise<JourneyGraph> => readDashboard('/operators/dashboard/journey', dashboardSchemas.journey, signal),
  readiness: (signal?: AbortSignal): Promise<Readiness> => readDashboard('/operators/dashboard/readiness', dashboardSchemas.readiness, signal),
  cometbft: (signal?: AbortSignal): Promise<CometBftDashboard> => readDashboard('/operators/dashboard/cometbft', dashboardSchemas.cometbft, signal),
  cometbftInstall: (signal?: AbortSignal): Promise<CometBftInstall> => readDashboard('/operators/dashboard/cometbft/install', dashboardSchemas.cometbftInstall, signal),
  fleet: (signal?: AbortSignal): Promise<Fleet> => readDashboard('/operators/dashboard/fleet', dashboardSchemas.fleet, signal),
  bundles: (signal?: AbortSignal): Promise<BundlePayload> => readDashboard('/operators/dashboard/bundles', dashboardSchemas.bundles, signal),
  endpoints: (signal?: AbortSignal): Promise<EndpointPayload> => readDashboard('/operators/dashboard/endpoints', dashboardSchemas.endpoints, signal),
  wallet: (signal?: AbortSignal): Promise<WalletDashboard> => readDashboard('/operators/dashboard/wallet', dashboardSchemas.wallet, signal),
  providers: (signal?: AbortSignal): Promise<ProviderWorkspace> => readDashboard('/operators/dashboard/providers', providerWorkspaceSchema, signal),
  runtimeOperations: (signal?: AbortSignal): Promise<RuntimeOperations> => readDashboard('/operators/dashboard/runtime-operations', dashboardSchemas.runtimeOperations, signal),
  resourceBroker: (signal?: AbortSignal): Promise<ResourceBrokerDashboard> => readDashboard('/operators/dashboard/resources', dashboardSchemas.resourceBroker, signal),
  residentAgent: (signal?: AbortSignal): Promise<ResidentAgentStatus> => readDashboard('/operators/dashboard/steward', dashboardSchemas.residentAgent, signal),
  escalations: (signal?: AbortSignal): Promise<EscalationTasks> => readDashboard('/operators/dashboard/steward/escalations?limit=64', dashboardSchemas.escalations, signal),
  stewardActionPolicy: (signal?: AbortSignal): Promise<StewardActionPolicy> => readDashboard('/operators/dashboard/steward/action-policy', dashboardSchemas.stewardActionPolicy, signal),
  residentInference: (signal?: AbortSignal): Promise<ResidentInference> => readDashboard('/operators/dashboard/steward/inference', dashboardSchemas.residentInference, signal),
  installationPlan: (signal?: AbortSignal): Promise<InstallationPlan> => readDashboard('/operators/dashboard/installation-plan', dashboardSchemas.installationPlan, signal),
  testnetParticipation: (signal?: AbortSignal): Promise<TestnetParticipationDashboard> => readDashboard('/operators/dashboard/testnet-participation', testnetParticipationDashboardSchema, signal),
  installs: (signal?: AbortSignal): Promise<ModelInstallWorkspace> => readDashboard('/operators/dashboard/installs', modelInstallWorkspaceSchema, signal),
  sessions: (signal?: AbortSignal): Promise<SessionDashboard> => readDashboard('/operators/dashboard/sessions', dashboardSchemas.sessions, signal),
  market: (signal?: AbortSignal): Promise<MarketDashboard> => readDashboard('/operators/dashboard/market', dashboardSchemas.market, signal),
  remoteEndpoints: (signal?: AbortSignal): Promise<RemoteEndpointsDashboard> => readDashboard('/operators/dashboard/remote-endpoints', dashboardSchemas.remoteEndpoints, signal),
  events: (signal?: AbortSignal) => readDashboard('/operators/events?limit=24', dashboardSchemas.events, signal),
  hooks: (signal?: AbortSignal): Promise<HookDefinition[]> => readDashboard('/operators/hooks', z.array(hookSchema), signal),
  hookMetrics: (signal?: AbortSignal): Promise<HookMetrics> => readDashboard('/operators/hooks/metrics', hookMetricsSchema, signal),
  hookDeliveries: (signal?: AbortSignal): Promise<HookDelivery[]> => readDashboard('/operators/hooks/deliveries?limit=32', z.array(hookDeliverySchema), signal),
  hookDeadLetters: (signal?: AbortSignal): Promise<HookDelivery[]> => readDashboard('/operators/hooks/dead-letters?limit=32', z.array(hookDeliverySchema), signal),
  accessStatus: (): Promise<DashboardAccessStatus> => writeDashboard('/operators/dashboard/access/status', { method: 'GET' }) as Promise<DashboardAccessStatus>,
  operatorConfig: (): Promise<OperatorConfigPayload> => writeDashboard<OperatorConfigPayload>('/operators/dashboard/access/config', { method: 'GET' }) as Promise<OperatorConfigPayload>,
  validateOperatorConfig: (text: string): Promise<OperatorConfigValidation> => writeDashboard<OperatorConfigValidation>('/operators/dashboard/access/config/validate', { method: 'POST', body: JSON.stringify({ text }) }) as Promise<OperatorConfigValidation>,
  saveOperatorConfig: (text: string, expectedSha256: string | null): Promise<OperatorConfigPayload> => writeDashboard<OperatorConfigPayload>('/operators/dashboard/access/config', { method: 'PUT', body: JSON.stringify({ text, expected_sha256: expectedSha256 }) }) as Promise<OperatorConfigPayload>,
  applyOperatorConfig: (text: string, expectedSha256: string | null): Promise<OperatorConfigPayload> => writeDashboard<OperatorConfigPayload>('/operators/dashboard/access/config/apply', { method: 'POST', body: JSON.stringify({ text, expected_sha256: expectedSha256 }) }) as Promise<OperatorConfigPayload>,
  softwareUpdate: (): Promise<SoftwareUpdatePayload> => writeDashboard<SoftwareUpdatePayload>('/operators/dashboard/access/operations/software-update', { method: 'GET' }) as Promise<SoftwareUpdatePayload>,
  checkSoftwareUpdate: (): Promise<SoftwareUpdatePayload> => writeDashboard<SoftwareUpdatePayload>('/operators/dashboard/access/operations/software-update/check', { method: 'POST' }) as Promise<SoftwareUpdatePayload>,
  applySoftwareUpdate: (expectedCommit: string): Promise<SoftwareUpdatePayload> => writeDashboard<SoftwareUpdatePayload>('/operators/dashboard/access/operations/software-update/apply', { method: 'POST', body: JSON.stringify({ expected_commit: expectedCommit }) }) as Promise<SoftwareUpdatePayload>,
  updateDashboardNetworkAccess: (mode: DashboardNetworkAccess['mode']): Promise<DashboardNetworkAccess & { status: string }> => writeDashboard<DashboardNetworkAccess & { status: string }>('/operators/dashboard/access/operations/network', { method: 'POST', body: JSON.stringify({ mode }) }) as Promise<DashboardNetworkAccess & { status: string }>,
  cometbftAction: (action: 'start' | 'stop' | 'restart') => writeDashboard<DashboardRecord>(`/operators/dashboard/access/operations/cometbft/${action}`, { method: 'POST' }),
  installCometbft: (payload: { mode: 'validator' | 'non_validator'; chain_id: string; version: string; moniker?: string; rpc_host: '127.0.0.1'; rpc_port: number; p2p_host: '127.0.0.1' | '0.0.0.0'; p2p_port: number; external_address: string; seeds: string; persistent_peers: string; abci_host: '127.0.0.1'; abci_port: number; acknowledge_network_scope: boolean }) => writeDashboard<DashboardRecord>('/operators/dashboard/access/operations/cometbft/install', { method: 'POST', body: JSON.stringify(payload) }),
  reconnectCometbft: (payload: { mode: 'non_validator'; chain_id: string; version: string; moniker?: string; rpc_host: '127.0.0.1'; rpc_port: number; p2p_host: '127.0.0.1' | '0.0.0.0'; p2p_port: number; external_address: string; seeds: string; persistent_peers: string; abci_host: '127.0.0.1'; abci_port: number; acknowledge_network_scope: boolean; source_rpc: string; acknowledge_reset: boolean }) => writeDashboard<DashboardRecord>('/operators/dashboard/access/operations/cometbft/reconnect', { method: 'POST', body: JSON.stringify(payload) }),
  applyCometbft: () => writeDashboard<DashboardRecord>('/operators/dashboard/access/operations/cometbft/apply', { method: 'POST' }),
  pairDashboard: (code: string, duration: string) => writeDashboard('/operators/dashboard/access/pair', { method: 'POST', body: JSON.stringify({ code, duration }) }),
  claimFirstBrowser: (duration: string) => writeDashboard('/operators/dashboard/access/claim-first-browser', { method: 'POST', body: JSON.stringify({ duration }) }),
  createAgentCredential: (label: string, scopes?: string[], autoApprovedScopes?: string[]) => writeDashboard<AccessCredential>('/operators/dashboard/access/credentials', { method: 'POST', body: JSON.stringify({ label, ...(scopes ? { scopes } : {}), ...(autoApprovedScopes ? { auto_approved_scopes: autoApprovedScopes } : {}) }) }),
  agentPermissionCatalog: () => writeDashboard<AgentPermissionCatalog>('/operators/dashboard/access/permission-catalog', { method: 'GET' }),
  updateAgentCredentialScopes: (credentialId: string, scopes: string[], autoApprovedScopes: string[]) => writeDashboard<AccessCredential>(`/operators/dashboard/access/credentials/${credentialId}/scopes`, { method: 'PUT', body: JSON.stringify({ scopes, auto_approved_scopes: autoApprovedScopes }) }),
  rotateAgentCredential: (credentialId: string) => writeDashboard<AccessCredential>(`/operators/dashboard/access/credentials/${credentialId}/rotate`, { method: 'POST' }),
  revokeAgentCredential: (credentialId: string) => writeDashboard(`/operators/dashboard/access/credentials/${credentialId}`, { method: 'DELETE' }),
  createInferenceCredential: (payload: { label: string; endpoint_id: string; model_alias?: string; ttl_seconds?: number }) => writeDashboard<InferenceCredential & { base_url: string }>('/operators/dashboard/access/inference-credentials', { method: 'POST', body: JSON.stringify(payload) }),
  rotateInferenceCredential: (credentialId: string) => writeDashboard<InferenceCredential & { base_url: string }>(`/operators/dashboard/access/inference-credentials/${encodeURIComponent(credentialId)}/rotate`, { method: 'POST' }),
  revokeInferenceCredential: (credentialId: string) => writeDashboard(`/operators/dashboard/access/inference-credentials/${encodeURIComponent(credentialId)}`, { method: 'DELETE' }),
  logoutDashboardAccess: () => writeDashboard('/operators/dashboard/access/logout', { method: 'POST' }),
  setResidentAgentEnabled: (enabled: boolean) => writeDashboard<ResidentAgentStatus>('/operators/dashboard/steward/enabled', { method: 'POST', body: JSON.stringify({ enabled }) }),
  updateStewardActionPolicy: (payload: { auto_actions?: string[]; approval_actions?: string[]; max_actions_per_hour?: number }) => writeDashboard<StewardActionPolicy>('/operators/dashboard/steward/action-policy', { method: 'POST', body: JSON.stringify(payload) }),
  executeStewardAction: (payload: { action: string; target_id: string; mode: 'plan' | 'apply'; plan_hash?: string; approval_reference?: string }) => writeDashboard<DashboardRecord>('/operators/dashboard/steward/action-execute', { method: 'POST', body: JSON.stringify(payload) }),
  prepareResidentInference: (payload: { model_path: string; provider_type?: string; plugin_id?: string; profile?: 'CPU_RESIDENT' | 'IGPU_RESIDENT' | 'GPU_RESIDENT' | 'GPU_BURST'; cpu?: number; ram_mb?: number; vram_mb?: number; request_cpu?: number; request_ram_mb?: number; request_vram_mb?: number; lease_seconds?: number; fallback_enabled?: boolean; runtime_parameter_policy?: DashboardRecord; source_url?: string; expected_sha256?: string; download?: boolean; max_download_bytes?: number; readiness_timeout_seconds?: number }) => writeDashboard<ResidentInference>('/operators/dashboard/steward/inference/prepare', { method: 'POST', body: JSON.stringify(payload) }),
  prepareResidentModel: (payload: { source_url: string; target_path: string; expected_sha256?: string; max_download_bytes?: number }) => writeDashboard<ResidentInference>('/operators/dashboard/steward/inference/model/prepare', { method: 'POST', body: JSON.stringify(payload) }),
  verifyResidentModel: (payload: { model_path: string; expected_sha256?: string }) => writeDashboard<DashboardRecord>('/operators/dashboard/steward/inference/model/verify', { method: 'POST', body: JSON.stringify(payload) }),
  startResidentInference: () => writeDashboard<ResidentInference>('/operators/dashboard/steward/inference/start', { method: 'POST' }),
  stopResidentInference: () => writeDashboard<ResidentInference>('/operators/dashboard/steward/inference/stop', { method: 'POST' }),
  stewardChat: (message: string) => writeDashboard<DashboardRecord>('/operators/dashboard/steward/chat', { method: 'POST', body: JSON.stringify({ message }) }),
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
  lifecycleTransitionPlan: (payload: { object_type: string; object_id: string; action: LifecycleTransitionAction }): Promise<LifecyclePlan> => writeDashboard<LifecyclePlan>('/operators/dashboard/access/operations/lifecycle/transition-plan', { method: 'POST', body: JSON.stringify(payload) }) as Promise<LifecyclePlan>,
  applyLifecycleTransition: (transitionId: string, payload: { plan_hash: string; force?: boolean; idempotency_key?: string }) => writeDashboard<DashboardRecord>(`/operators/dashboard/access/operations/lifecycle/transition-plans/${encodeURIComponent(transitionId)}/apply`, { method: 'POST', body: JSON.stringify(payload) }),
  lifecycleRemovalPlan: (payload: { object_type: string; object_id: string; cascade?: boolean }): Promise<LifecyclePlan> => writeDashboard<LifecyclePlan>('/operators/dashboard/access/operations/lifecycle/removal-plan', { method: 'POST', body: JSON.stringify(payload) }) as Promise<LifecyclePlan>,
  applyLifecycleRemoval: (planId: string, payload: { plan_hash: string; force?: boolean; idempotency_key?: string }) => writeDashboard<DashboardRecord>(`/operators/dashboard/access/operations/lifecycle/removal-plans/${encodeURIComponent(planId)}/apply`, { method: 'POST', body: JSON.stringify(payload) }),
  runtimeResetPlan: (): Promise<LifecyclePlan> => writeDashboard<LifecyclePlan>('/operators/dashboard/access/operations/lifecycle/runtime-reset/plan', { method: 'POST' }) as Promise<LifecyclePlan>,
  applyInstallationPlan: (payload: { plan_hash: string; actor?: string; idempotency_key?: string; action?: AssistedInstallationAction }) => writeDashboard<InstallationPlan & { job?: DashboardRecord }>('/operators/dashboard/access/operations/installation-plan/apply', { method: 'POST', body: JSON.stringify(payload) }),
  applyRuntimeReset: (payload: { reset_id: string; plan_hash: string; force?: boolean; idempotency_key?: string }) => writeDashboard<DashboardRecord>('/operators/dashboard/access/operations/lifecycle/runtime-reset/apply', { method: 'POST', body: JSON.stringify(payload) }),
  attachProvider: (payload: { plugin_id: string; display_name: string; configuration: DashboardRecord }) => writeDashboard<DashboardRecord>('/operators/dashboard/access/operations/providers/attach', { method: 'POST', body: JSON.stringify(payload) }),
  installProviderRuntime: (pluginId: string, configuration: DashboardRecord, operatorNote?: string, upgradeAcknowledged = false) => writeDashboard<DashboardRecord>(`/operators/dashboard/access/operations/provider-plugins/${encodeURIComponent(pluginId)}/install`, { method: 'POST', body: JSON.stringify({ configuration, upgrade_acknowledged: upgradeAcknowledged, ...(operatorNote ? { operator_note: operatorNote } : {}) }) }),
  providerRuntimeAction: (pluginId: string, action: 'install' | 'change' | 'remove', configuration: DashboardRecord = {}, operatorNote?: string, upgradeAcknowledged = false) => writeDashboard<DashboardRecord>(`/operators/dashboard/access/operations/provider-plugins/${encodeURIComponent(pluginId)}/runtime/${action}`, { method: 'POST', body: JSON.stringify({ configuration, upgrade_acknowledged: upgradeAcknowledged, ...(operatorNote ? { operator_note: operatorNote } : {}) }) }),
  providerOperation: (providerInstanceId: string, action: 'probe' | 'discover-models' | 'detach') => writeDashboard(`/operators/dashboard/access/operations/providers/${encodeURIComponent(providerInstanceId)}/${action}`, { method: 'POST' }),
  requestModelInstall: (payload: { provider_type: string; model_id: string; source_url: string; requested_by?: string; runtime_parameter_policy?: DashboardRecord }) => writeDashboard<DashboardRecord>('/operators/dashboard/access/operations/models/install', { method: 'POST', body: JSON.stringify({ requested_by: 'operator-dashboard', ...payload }) }),
  processModelInstalls: () => writeDashboard<{ items: DashboardRecord[] }>('/operators/dashboard/access/operations/models/install/process', { method: 'POST' }),
  registerBundleFromInstall: (installId: string, payload: { bundle_id: string; workload_type: string; endpoint: string; runtime_parameter_policy?: DashboardRecord }) => writeDashboard<DashboardRecord>(`/operators/dashboard/access/operations/models/${encodeURIComponent(installId)}/register-bundle`, { method: 'POST', body: JSON.stringify(payload) }),
  createModelArtifactSet: (payload: { display_name: string; files: DashboardRecord[] }) => writeDashboard<DashboardRecord>('/operators/dashboard/access/operations/model-artifact-sets', { method: 'POST', body: JSON.stringify(payload) }),
  bindModelArtifactSet: (deploymentId: string, artifactSetId: string) => writeDashboard<DashboardRecord>(`/operators/dashboard/access/operations/model-deployments/${encodeURIComponent(deploymentId)}/artifact-set`, { method: 'POST', body: JSON.stringify({ artifact_set_id: artifactSetId }) }),
  materializeModelArtifactSet: (providerInstanceId: string, artifactSetId: string, destination: string) => writeDashboard<DashboardRecord>(`/operators/dashboard/access/operations/provider-instances/${encodeURIComponent(providerInstanceId)}/artifact-sets/materialize`, { method: 'POST', body: JSON.stringify({ artifact_set_id: artifactSetId, destination }) }),
  createRuntimeBinding: (deploymentId: string, payload: { capability_id: string; capability_version: string; capability_definition_hash: string }) => writeDashboard<DashboardRecord>(`/operators/dashboard/access/operations/model-deployments/${encodeURIComponent(deploymentId)}/runtime-bindings`, { method: 'POST', body: JSON.stringify(payload) }),
  createBundleRevision: (sourceBundleId: string, payload: { bundle_id: string; overrides: DashboardRecord; enabled?: boolean }) => writeDashboard<DashboardRecord>(`/operators/dashboard/access/operations/bundles/${encodeURIComponent(sourceBundleId)}/revisions`, { method: 'POST', body: JSON.stringify(payload) }),
  createEndpoint: (payload: DashboardRecord) => writeDashboard<DashboardRecord>('/operators/dashboard/access/operations/endpoints', { method: 'POST', body: JSON.stringify(payload) }),
  quoteEndpoint: (endpointId: string, usage: Record<string, number> = {}) => writeDashboard<EndpointQuoteEnvelope>(`/api/v1/endpoints/${encodeURIComponent(endpointId)}/quote`, { method: 'POST', body: JSON.stringify({ usage }) }) as Promise<EndpointQuoteEnvelope>,
  recommendEndpointDeposit: (endpointId: string, payload: { usage_overrides?: Record<string, number>; safety_margin_bps?: number; recommended_multiplier?: number } = {}) => writeDashboard<{ data: { endpoint_id: string; configuration_hash: string; recommendation: EscrowDepositRecommendation } }>(`/api/v1/endpoints/${encodeURIComponent(endpointId)}/deposit-recommendation`, { method: 'POST', body: JSON.stringify(payload) }),
  previewMarketplaceDescription: (html: string) => writeDashboard<DashboardRecord>('/operators/dashboard/access/operations/endpoints/marketplace-description/preview', { method: 'POST', body: JSON.stringify({ html }) }),
  updateEndpoint: (endpointId: string, payload: DashboardRecord) => writeDashboard<DashboardRecord>(`/operators/dashboard/access/operations/endpoints/${encodeURIComponent(endpointId)}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  setEndpointLocalAgentUse: (endpointId: string, enabled: boolean) => writeDashboard<DashboardRecord>(`/operators/dashboard/access/operations/endpoints/${encodeURIComponent(endpointId)}/local-agent-use`, { method: 'POST', body: JSON.stringify({ enabled }) }),
  publishEndpoint: (endpointId: string) => writeDashboard<DashboardRecord>(`/operators/dashboard/access/operations/endpoints/${encodeURIComponent(endpointId)}/publish`, { method: 'POST' }),
  requestEndpointValidation: (endpointId: string) => writeDashboard<DashboardRecord>(`/operators/dashboard/access/operations/endpoints/${encodeURIComponent(endpointId)}/validation`, { method: 'POST' }),
  closeSession: (sessionId: string) => writeDashboard<DashboardRecord>('/operators/dashboard/sessions/actions/close', { method: 'POST', body: JSON.stringify({ session_id: sessionId }) }),
  sweepIdleSessions: () => writeDashboard<{ closed_count: number; items: DashboardRecord[] }>('/operators/dashboard/sessions/actions/sweep-idle', { method: 'POST', body: JSON.stringify({}) }),
  attachRemoteEndpoint: (payload: { node_id: string; endpoint_id: string; alias?: string; routing_mode?: string }) => writeDashboard<DashboardRecord>('/operators/remote-endpoints/attach', { method: 'POST', body: JSON.stringify(payload) }),
  detachRemoteEndpoint: (remoteEndpointId: string) => writeDashboard<DashboardRecord>(`/operators/remote-endpoints/${encodeURIComponent(remoteEndpointId)}`, { method: 'DELETE' }),
  createHook: (payload: { hook_id: string; owner_operator_id: string; target_agent_id: string; event_filter: HookEventFilter; delivery_mode?: string; max_attempts?: number; retry_backoff_seconds?: number; expires_at?: string | null }) => writeDashboard<HookDefinition>('/operators/hooks', { method: 'POST', body: JSON.stringify(payload) }),
  updateHook: (hookId: string, payload: Partial<Pick<HookDefinition, 'enabled' | 'target_agent_id' | 'event_filter' | 'delivery_mode' | 'max_attempts' | 'retry_backoff_seconds' | 'expires_at'>>) => writeDashboard<HookDefinition>(`/operators/hooks/${encodeURIComponent(hookId)}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  deleteHook: (hookId: string) => writeDashboard<{ deleted: boolean; hook_id: string }>(`/operators/hooks/${encodeURIComponent(hookId)}`, { method: 'DELETE' }),
  testHook: (hookId: string) => writeDashboard<DashboardRecord>(`/operators/hooks/${encodeURIComponent(hookId)}/test`, { method: 'POST' }),
  retryHookDeadLetter: (deliveryId: string) => writeDashboard<HookDelivery>(`/operators/hooks/dead-letters/${encodeURIComponent(deliveryId)}/retry`, { method: 'POST' }),
  replayHookEvent: (eventId: string) => writeDashboard<HookDelivery[]>(`/operators/hooks/replay/${encodeURIComponent(eventId)}`, { method: 'POST' }),
}
