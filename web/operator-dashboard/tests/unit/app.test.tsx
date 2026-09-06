import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import App from '@/App'
import { TooltipProvider } from '@/components/ui/tooltip'
import { dashboardApi } from '@/lib/api'
import { useOperatorDashboardStore } from '@/stores/operator-dashboard'
import { dashboardDataFixture, dashboardQueryFixture, unpairedAccessFixture } from '../fixtures/dashboard-api'

const mocks = vi.hoisted(() => ({ useDashboardData: vi.fn() }))

vi.mock('@/hooks/use-dashboard', () => ({
  useDashboardData: mocks.useDashboardData,
}))

function renderApp() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <App />
      </TooltipProvider>
    </QueryClientProvider>,
  )
}

describe('Classic operator dashboard shell', () => {
  beforeEach(() => {
    window.history.replaceState(null, '', '#overview')
    useOperatorDashboardStore.setState({ activeScreen: 'overview', advanced: false })
    mocks.useDashboardData.mockReturnValue(dashboardDataFixture())
  })

  it('boots without a live Node', () => {
    renderApp()

    expect(screen.getByRole('button', { name: 'Open Hypervisor overview' })).toBeVisible()
    expect(screen.getByRole('button', { name: 'Refresh dashboard' })).toBeEnabled()
    expect(screen.queryByRole('button', { name: 'Open Spatial UI' })).not.toBeInTheDocument()
  })

  it('renders loading, typed error, and retry states', async () => {
    const retry = vi.fn().mockResolvedValue({ data: undefined })
    mocks.useDashboardData.mockReturnValue(dashboardDataFixture({
      journey: dashboardQueryFixture({ isLoading: true, refetch: retry }),
    }))
    const rendered = renderApp()
    expect(rendered.container.querySelectorAll('[data-slot="skeleton"]')).not.toHaveLength(0)

    rendered.unmount()
    mocks.useDashboardData.mockReturnValue(dashboardDataFixture({
      journey: dashboardQueryFixture({
        error: new Error('fixture unavailable'),
        isError: true,
        refetch: retry,
      }),
    }))
    renderApp()

    expect(screen.getByRole('heading', { name: 'Node journey is unavailable' })).toBeVisible()
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }))
    await waitFor(() => expect(retry).toHaveBeenCalledOnce())
  })

  it('keeps Classic hash navigation and browser history semantics', async () => {
    window.history.replaceState(null, '', '#settings')
    useOperatorDashboardStore.setState({ activeScreen: 'overview' })
    vi.spyOn(dashboardApi, 'accessStatus').mockResolvedValue(unpairedAccessFixture)
    renderApp()

    expect(await screen.findByRole('heading', { name: 'Settings' })).toBeVisible()
    await userEvent.click(screen.getByRole('button', { name: 'Open Hypervisor overview' }))
    expect(window.location.hash).toBe('#overview')

    window.history.back()
    window.dispatchEvent(new PopStateEvent('popstate'))
    await waitFor(() => expect(useOperatorDashboardStore.getState().activeScreen).toBe('settings'))
  })

  it('does not submit browser pairing until a code is present', async () => {
    window.history.replaceState(null, '', '#settings')
    vi.spyOn(dashboardApi, 'accessStatus').mockResolvedValue(unpairedAccessFixture)
    const pair = vi.spyOn(dashboardApi, 'pairDashboard').mockResolvedValue(undefined)
    renderApp()

    const submit = await screen.findByRole('button', { name: 'Trust browser' })
    expect(submit).toBeDisabled()
    expect(pair).not.toHaveBeenCalled()

    await userEvent.type(screen.getByPlaceholderText('Paste code from the node terminal'), 'PAIR-1234')
    expect(submit).toBeEnabled()
    await userEvent.click(submit)

    await waitFor(() => expect(pair).toHaveBeenCalledWith('PAIR-1234', 'one_day'))
  })
})
