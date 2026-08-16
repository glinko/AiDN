export type Availability = 'operational' | 'degraded' | 'unavailable'

export type NetworkMetric = {
  value: number | string | null
  unit?: string | null
  source: string
  observedAt: string | null
}

export type NetworkSummary = {
  status: Availability
  observedAt: string | null
  metrics: {
    activeHypervisors: NetworkMetric
    activeEndpoints: NetworkMetric
    availableGpus: NetworkMetric
    availableVram: NetworkMetric
    models: NetworkMetric
    networkCompute: NetworkMetric
    requests24h: NetworkMetric
    qSettled24h: NetworkMetric
  }
}

export type EndpointSummary = {
  id: string
  model: string
  provider: string
  capabilities: string[]
  context: string | null
  performance: string | null
  price: string | null
  validation: 'verified' | 'pending' | 'unvalidated' | 'rejected'
  availability: 'available' | 'degraded' | 'offline' | 'unknown'
  operator: string | null
  latencyMs: number | null
}

export type EndpointSearchResponse = {
  items: EndpointSummary[]
  nextCursor: string | null
  observedAt: string | null
}

export type FaucetStatus = {
  enabled: boolean
  state: 'ready' | 'paused' | 'low_balance' | 'degraded' | 'unavailable'
  amountQAtoms: number | null
  policyId: string | null
  policyVersion: string | null
  cooldownSeconds: number | null
  lowBalanceBlocked: boolean
  paused: boolean
  pauseReason: string | null
}

export type FaucetChallenge = {
  challengeId: string
  walletId: string
  challenge: string
  issuedAt: string
  expiresAt: string
  signingDomain: 'aidn.faucet-wallet-proof.v1'
}

export type FaucetClaimResult = {
  requestId: string
  claimId: string | null
  status: string
  amountQAtoms: number
  operationId: string | null
  transactionHash: string | null
  detail: string | null
}

type RawRecord = Record<string, unknown>

const API_BASE = import.meta.env.VITE_WEBSITE_API_BASE || '/api/site/v1'
const DEMO_MODE = import.meta.env.MODE === 'demo' || import.meta.env.VITE_WEBSITE_DEMO === 'true'

export function isDemoMode(): boolean {
  return DEMO_MODE
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  const payload = (await response.json().catch(() => ({}))) as RawRecord
  if (!response.ok) {
    const error = typeof payload.error === 'object' && payload.error !== null ? payload.error as RawRecord : payload
    throw new Error(typeof error.message === 'string' ? error.message : `Website API returned ${response.status}`)
  }
  return payload as T
}

function metric(value: number | string | null, source = 'Website API', observedAt: string | null = new Date().toISOString()): NetworkMetric {
  return { value, source, observedAt }
}

const demoSummary: NetworkSummary = {
  status: 'operational',
  observedAt: new Date().toISOString(),
  metrics: {
    activeHypervisors: metric(4, 'Illustrative preview'),
    activeEndpoints: metric(12, 'Illustrative preview'),
    availableGpus: metric(7, 'Illustrative preview'),
    availableVram: metric('138 GB', 'Illustrative preview'),
    models: metric(9, 'Illustrative preview'),
    networkCompute: metric('2.4 PFLOP/s', 'Illustrative preview'),
    requests24h: metric(1842, 'Illustrative preview'),
    qSettled24h: metric('8,420 Q', 'Illustrative preview'),
  },
}

const demoEndpoints: EndpointSummary[] = [
  {
    id: 'ep-preview-qwen-27b',
    model: 'Qwen3.8 27B',
    provider: 'llama.cpp OpenAI-compatible',
    capabilities: ['chat', 'reasoning', 'json'],
    context: '32k',
    performance: '17 tok/s',
    price: '0.004 Q / 1k tokens',
    validation: 'verified',
    availability: 'available',
    operator: 'gpu-3090',
    latencyMs: 184,
  },
  {
    id: 'ep-preview-whisper',
    model: 'Whisper large-v3',
    provider: 'Whisper HTTP Provider',
    capabilities: ['transcription', 'timestamps'],
    context: null,
    performance: 'real-time × 1.8',
    price: '0.001 Q / minute',
    validation: 'verified',
    availability: 'available',
    operator: 'audio-node-02',
    latencyMs: 92,
  },
  {
    id: 'ep-preview-llama',
    model: 'Llama 3.1 8B',
    provider: 'Ollama',
    capabilities: ['chat', 'tools'],
    context: '16k',
    performance: '42 tok/s',
    price: '0.002 Q / 1k tokens',
    validation: 'pending',
    availability: 'degraded',
    operator: 'edge-node-07',
    latencyMs: 341,
  },
]

const demoFaucetStatus: FaucetStatus = {
  enabled: true,
  state: 'ready',
  amountQAtoms: 100000,
  policyId: 'testnet-faucet',
  policyVersion: 'v1',
  cooldownSeconds: 86400,
  lowBalanceBlocked: false,
  paused: false,
  pauseReason: null,
}

export async function getNetworkSummary(): Promise<NetworkSummary> {
  if (DEMO_MODE) return demoSummary
  const payload = await request<RawRecord>('/network/summary')
  const metrics = (payload.metrics ?? {}) as RawRecord
  const readMetric = (key: string): NetworkMetric => {
    const item = (metrics[key] ?? {}) as RawRecord
    return metric(typeof item.value === 'number' || typeof item.value === 'string' ? item.value : null, typeof item.source === 'string' ? item.source : 'Website API', typeof item.observed_at === 'string' ? item.observed_at : null)
  }
  return {
    status: payload.status === 'operational' || payload.status === 'degraded' ? payload.status : 'unavailable',
    observedAt: typeof payload.observed_at === 'string' ? payload.observed_at : null,
    metrics: {
      activeHypervisors: readMetric('active_hypervisors'),
      activeEndpoints: readMetric('active_endpoints'),
      availableGpus: readMetric('available_gpus'),
      availableVram: readMetric('available_vram'),
      models: readMetric('models'),
      networkCompute: readMetric('network_compute'),
      requests24h: readMetric('requests_24h'),
      qSettled24h: readMetric('q_settled_24h'),
    },
  }
}

export async function searchEndpoints(): Promise<EndpointSearchResponse> {
  if (DEMO_MODE) return { items: demoEndpoints, nextCursor: null, observedAt: demoSummary.observedAt }
  const payload = await request<RawRecord>('/network/endpoints')
  const items = Array.isArray(payload.items) ? payload.items : []
  return {
    items: items.map((item) => {
      const record = item as RawRecord
      return {
        id: String(record.id ?? record.endpoint_id ?? 'unknown-endpoint'),
        model: String(record.model ?? 'Unknown model'),
        provider: String(record.provider ?? 'Unknown provider'),
        capabilities: Array.isArray(record.capabilities) ? record.capabilities.map(String) : [],
        context: typeof record.context === 'string' ? record.context : null,
        performance: typeof record.performance === 'string' ? record.performance : null,
        price: typeof record.price === 'string' ? record.price : null,
        validation: record.validation === 'verified' || record.validation === 'pending' || record.validation === 'rejected' ? record.validation : 'unvalidated',
        availability: record.availability === 'available' || record.availability === 'degraded' || record.availability === 'offline' ? record.availability : 'unknown',
        operator: typeof record.operator === 'string' ? record.operator : null,
        latencyMs: typeof record.latency_ms === 'number' ? record.latency_ms : null,
      }
    }),
    nextCursor: typeof payload.next_cursor === 'string' ? payload.next_cursor : null,
    observedAt: typeof payload.observed_at === 'string' ? payload.observed_at : null,
  }
}

export async function getFaucetStatus(): Promise<FaucetStatus> {
  if (DEMO_MODE) return demoFaucetStatus
  const payload = await request<RawRecord>('/faucet/status')
  return {
    enabled: payload.enabled === true,
    state: payload.state === 'ready' || payload.state === 'paused' || payload.state === 'low_balance' || payload.state === 'degraded' ? payload.state : 'unavailable',
    amountQAtoms: typeof payload.amount_q_atoms === 'number' ? payload.amount_q_atoms : null,
    policyId: typeof payload.policy_id === 'string' ? payload.policy_id : null,
    policyVersion: typeof payload.policy_version === 'string' ? payload.policy_version : null,
    cooldownSeconds: typeof payload.cooldown_seconds === 'number' ? payload.cooldown_seconds : null,
    lowBalanceBlocked: payload.low_balance_blocked === true,
    paused: payload.paused === true,
    pauseReason: typeof payload.pause_reason === 'string' ? payload.pause_reason : null,
  }
}

export async function issueFaucetChallenge(walletId: string, walletPublicKey: string): Promise<FaucetChallenge> {
  if (DEMO_MODE) {
    return {
      challengeId: 'preview-challenge-01',
      walletId,
      challenge: 'preview-signing-bytes-do-not-submit',
      issuedAt: new Date().toISOString(),
      expiresAt: new Date(Date.now() + 5 * 60_000).toISOString(),
      signingDomain: 'aidn.faucet-wallet-proof.v1',
    }
  }
  const payload = await request<RawRecord>('/faucet/challenges', { method: 'POST', body: JSON.stringify({ wallet_id: walletId, wallet_public_key: walletPublicKey }) })
  return {
    challengeId: String(payload.challenge_id ?? ''),
    walletId: String(payload.wallet_id ?? walletId),
    challenge: String(payload.challenge ?? ''),
    issuedAt: String(payload.issued_at ?? ''),
    expiresAt: String(payload.expires_at ?? ''),
    signingDomain: 'aidn.faucet-wallet-proof.v1',
  }
}

export async function submitFaucetClaim(input: { requestId: string; walletId: string; walletPublicKey: string; challengeId: string; walletSignature: string }): Promise<FaucetClaimResult> {
  if (DEMO_MODE) {
    return {
      requestId: input.requestId,
      claimId: 'preview-claim-01',
      status: 'pending_finality',
      amountQAtoms: demoFaucetStatus.amountQAtoms ?? 0,
      operationId: 'preview-op-01',
      transactionHash: null,
      detail: 'Preview mode: no network transaction was submitted.',
    }
  }
  const payload = await request<RawRecord>('/faucet/claims', { method: 'POST', body: JSON.stringify({ request_id: input.requestId, wallet_id: input.walletId, wallet_public_key: input.walletPublicKey, challenge_id: input.challengeId, wallet_signature: input.walletSignature }) })
  return {
    requestId: String(payload.request_id ?? input.requestId),
    claimId: typeof payload.claim_id === 'string' ? payload.claim_id : null,
    status: String(payload.status ?? 'submission_unknown'),
    amountQAtoms: typeof payload.amount_q_atoms === 'number' ? payload.amount_q_atoms : 0,
    operationId: typeof payload.operation_id === 'string' ? payload.operation_id : null,
    transactionHash: typeof payload.transaction_hash === 'string' ? payload.transaction_hash : null,
    detail: typeof payload.detail === 'string' ? payload.detail : null,
  }
}
