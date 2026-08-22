import { useQuery } from '@tanstack/react-query'

import { dashboardApi } from '@/lib/api'

const refetchIntervalMs = 20_000
const runtimeOperationsRefetchIntervalMs = 5_000
const staleTimeMs = 8_000

export function useDashboardData() {
  const home = useQuery({
    queryKey: ['operator-dashboard', 'home'],
    queryFn: ({ signal }) => dashboardApi.home(signal),
    staleTime: staleTimeMs,
    refetchInterval: refetchIntervalMs,
  })
  const journey = useQuery({
    queryKey: ['operator-dashboard', 'journey'],
    queryFn: ({ signal }) => dashboardApi.journey(signal),
    staleTime: staleTimeMs,
    refetchInterval: refetchIntervalMs,
  })
  const readiness = useQuery({
    queryKey: ['operator-dashboard', 'readiness'],
    queryFn: ({ signal }) => dashboardApi.readiness(signal),
    staleTime: staleTimeMs,
    refetchInterval: refetchIntervalMs,
  })
  const cometbft = useQuery({
    queryKey: ['operator-dashboard', 'cometbft'],
    queryFn: ({ signal }) => dashboardApi.cometbft(signal),
    staleTime: staleTimeMs,
    refetchInterval: refetchIntervalMs,
  })
  const cometbftInstall = useQuery({
    queryKey: ['operator-dashboard', 'cometbft-install'],
    queryFn: ({ signal }) => dashboardApi.cometbftInstall(signal),
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
  const wallet = useQuery({
    queryKey: ['operator-dashboard', 'wallet'],
    queryFn: ({ signal }) => dashboardApi.wallet(signal),
    staleTime: staleTimeMs,
    refetchInterval: refetchIntervalMs,
  })
  const providers = useQuery({
    queryKey: ['operator-dashboard', 'providers'],
    queryFn: ({ signal }) => dashboardApi.providers(signal),
    staleTime: staleTimeMs,
    refetchInterval: refetchIntervalMs,
  })
  const runtimeOperations = useQuery({
    queryKey: ['operator-dashboard', 'runtime-operations'],
    queryFn: ({ signal }) => dashboardApi.runtimeOperations(signal),
    staleTime: runtimeOperationsRefetchIntervalMs,
    refetchInterval: runtimeOperationsRefetchIntervalMs,
  })
  const installs = useQuery({
    queryKey: ['operator-dashboard', 'installs'],
    queryFn: ({ signal }) => dashboardApi.installs(signal),
    staleTime: staleTimeMs,
    refetchInterval: refetchIntervalMs,
  })
  const sessions = useQuery({
    queryKey: ['operator-dashboard', 'sessions'],
    queryFn: ({ signal }) => dashboardApi.sessions(signal),
    staleTime: staleTimeMs,
    refetchInterval: refetchIntervalMs,
  })
  const market = useQuery({
    queryKey: ['operator-dashboard', 'market'],
    queryFn: ({ signal }) => dashboardApi.market(signal),
    staleTime: staleTimeMs,
    refetchInterval: refetchIntervalMs,
  })
  const remoteEndpoints = useQuery({
    queryKey: ['operator-dashboard', 'remote-endpoints'],
    queryFn: ({ signal }) => dashboardApi.remoteEndpoints(signal),
    staleTime: staleTimeMs,
    refetchInterval: refetchIntervalMs,
  })
  const events = useQuery({
    queryKey: ['operator-dashboard', 'events'],
    queryFn: ({ signal }) => dashboardApi.events(signal),
    staleTime: staleTimeMs,
    refetchInterval: refetchIntervalMs,
  })
  const hooks = useQuery({
    queryKey: ['operator-dashboard', 'hooks'],
    queryFn: ({ signal }) => dashboardApi.hooks(signal),
    staleTime: staleTimeMs,
    refetchInterval: refetchIntervalMs,
  })
  const hookMetrics = useQuery({
    queryKey: ['operator-dashboard', 'hook-metrics'],
    queryFn: ({ signal }) => dashboardApi.hookMetrics(signal),
    staleTime: staleTimeMs,
    refetchInterval: refetchIntervalMs,
  })
  const hookDeliveries = useQuery({
    queryKey: ['operator-dashboard', 'hook-deliveries'],
    queryFn: ({ signal }) => dashboardApi.hookDeliveries(signal),
    staleTime: staleTimeMs,
    refetchInterval: refetchIntervalMs,
  })
  const hookDeadLetters = useQuery({
    queryKey: ['operator-dashboard', 'hook-dead-letters'],
    queryFn: ({ signal }) => dashboardApi.hookDeadLetters(signal),
    staleTime: staleTimeMs,
    refetchInterval: refetchIntervalMs,
  })

  return { home, journey, readiness, cometbft, cometbftInstall, fleet, bundles, endpoints, wallet, providers, runtimeOperations, installs, sessions, market, remoteEndpoints, events, hooks, hookMetrics, hookDeliveries, hookDeadLetters }
}
