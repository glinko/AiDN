import { afterEach, describe, expect, it, vi } from 'vitest'

import { dashboardApi } from '@/lib/api'
import { FIXED_BROWSER_KEY, installDeterministicRuntime } from '../fixtures/deterministic'
import { dashboardEventStreamFixture } from '../fixtures/event-stream'
import { jsonResponse } from '../fixtures/dashboard-api'

describe('Dashboard API fixtures', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('preserves an explicit idempotency key in a mutation', async () => {
    installDeterministicRuntime()
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ plan_hash: 'plan-fixture' }))
    vi.stubGlobal('fetch', fetchMock)

    await dashboardApi.applyInstallationPlan({
      plan_hash: 'plan-fixture',
      action: 'prepare_review',
      idempotency_key: 'request-00000001',
    })

    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(path).toBe('/operators/dashboard/access/operations/installation-plan/apply')
    expect(init.method).toBe('POST')
    expect(JSON.parse(String(init.body))).toEqual({
      plan_hash: 'plan-fixture',
      action: 'prepare_review',
      idempotency_key: 'request-00000001',
    })
    expect(new Headers(init.headers).get('X-AiDN-Browser-Key')).toBe(FIXED_BROWSER_KEY)
  })

  it('provides a deterministic correlated event stream', () => {
    expect(dashboardEventStreamFixture.map((event) => event.event_id)).toEqual([
      'event-00000001',
      'event-00000002',
    ])
    expect(dashboardEventStreamFixture[1].causation_id).toBe(dashboardEventStreamFixture[0].event_id)
  })
})
