import { vi } from 'vitest'

import type { useDashboardData } from '@/hooks/use-dashboard'
import type { DashboardAccessStatus } from '@/lib/api'

type DashboardData = ReturnType<typeof useDashboardData>
type QueryFixture = DashboardData[keyof DashboardData]

export function dashboardQueryFixture(overrides: Record<string, unknown> = {}) {
  return {
    data: undefined,
    error: null,
    isLoading: false,
    isFetching: false,
    isError: false,
    refetch: vi.fn().mockResolvedValue({ data: undefined }),
    ...overrides,
  } as unknown as QueryFixture
}

export function dashboardDataFixture(overrides: Partial<Record<keyof DashboardData, QueryFixture>> = {}) {
  const query = () => dashboardQueryFixture()
  return {
    home: query(),
    journey: query(),
    readiness: query(),
    cometbft: query(),
    cometbftInstall: query(),
    fleet: query(),
    bundles: query(),
    endpoints: query(),
    wallet: query(),
    providers: query(),
    runtimeOperations: query(),
    resourceBroker: query(),
    residentAgent: query(),
    escalations: query(),
    stewardActionPolicy: query(),
    residentInference: query(),
    installationPlan: query(),
    testnetParticipation: query(),
    installs: query(),
    sessions: query(),
    market: query(),
    remoteEndpoints: query(),
    events: query(),
    hooks: query(),
    hookMetrics: query(),
    hookDeliveries: query(),
    hookDeadLetters: query(),
    ...overrides,
  } as DashboardData
}

export const unpairedAccessFixture: DashboardAccessStatus = {
  enabled: true,
  session: { active: false, expires_at: null },
  browser_binding: { first_browser_claim: { active: false, expires_at: null } },
  transport: { insecure_lan: false },
  operator_authority: { configured: true, fingerprint: 'sha256:operator-fixture' },
  network_access: {
    mode: 'loopback',
    configured_mode: 'loopback',
    effective_mode: 'loopback',
    configured_host: '127.0.0.1',
    effective_host: '127.0.0.1',
    restart_required: false,
    restart_scheduled: false,
    apply_supported: true,
    port: 8000,
  },
  credentials: [],
  inference_credentials: [],
}

export function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}
