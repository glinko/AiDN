import { useQuery } from '@tanstack/react-query'

import { dashboardApi } from '@/lib/api'

const refetchIntervalMs = 20_000
const staleTimeMs = 8_000

export function useDashboardData() {
  const home = useQuery({
    queryKey: ['operator-dashboard', 'home'],
    queryFn: ({ signal }) => dashboardApi.home(signal),
    staleTime: staleTimeMs,
    refetchInterval: refetchIntervalMs,
  })
  const readiness = useQuery({
    queryKey: ['operator-dashboard', 'readiness'],
    queryFn: ({ signal }) => dashboardApi.readiness(signal),
    staleTime: staleTimeMs,
    refetchInterval: refetchIntervalMs,
  })
  const fleet = useQuery({
    queryKey: ['operator-dashboard', 'fleet'],
    queryFn: ({ signal }) => dashboardApi.fleet(signal),
    staleTime: staleTimeMs,
    refetchInterval: refetchIntervalMs,
  })
  const bundles = useQuery({
    queryKey: ['operator-dashboard', 'bundles'],
    queryFn: ({ signal }) => dashboardApi.bundles(signal),
    staleTime: staleTimeMs,
    refetchInterval: refetchIntervalMs,
  })
  const endpoints = useQuery({
    queryKey: ['operator-dashboard', 'endpoints'],
    queryFn: ({ signal }) => dashboardApi.endpoints(signal),
    staleTime: staleTimeMs,
    refetchInterval: refetchIntervalMs,
  })
  const providers = useQuery({
    queryKey: ['operator-dashboard', 'providers'],
    queryFn: ({ signal }) => dashboardApi.providers(signal),
    staleTime: staleTimeMs,
    refetchInterval: refetchIntervalMs,
  })

  return { home, readiness, fleet, bundles, endpoints, providers }
}
