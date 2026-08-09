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

export const dashboardApi = {
  home: (signal?: AbortSignal): Promise<DashboardHome> => readDashboard('/operators/dashboard/home', dashboardSchemas.home, signal),
  readiness: (signal?: AbortSignal): Promise<Readiness> => readDashboard('/operators/dashboard/readiness', dashboardSchemas.readiness, signal),
  fleet: (signal?: AbortSignal): Promise<Fleet> => readDashboard('/operators/dashboard/fleet', dashboardSchemas.fleet, signal),
  bundles: (signal?: AbortSignal): Promise<BundlePayload> => readDashboard('/operators/dashboard/bundles', dashboardSchemas.bundles, signal),
  endpoints: (signal?: AbortSignal): Promise<EndpointPayload> => readDashboard('/operators/dashboard/endpoints', dashboardSchemas.endpoints, signal),
}
