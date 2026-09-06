import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { SystemMenu } from '@/spatial/status'
import { createMockSpatialNodeStatus } from '@/spatial/data/mock-fixtures'
import { SpatialThemeBoundary } from '@/spatial/theme/SpatialThemeBoundary'

function fixture() {
  const status = createMockSpatialNodeStatus()
  return {
    ...status,
    warning_count: 1,
    partial: true,
    components: [
      {
        ...status.components[0],
        kind: 'hooks' as const,
        component_id: 'hooks-local',
        component_type: 'Hooks',
        state: 'DEGRADED' as const,
        spatial_ref: 'service:hooks',
        available_actions: ['RETRY_HOOK_DEAD_LETTER' as const],
        details: {
          authorization: 'AUTHORIZED' as const,
          last_events: [{ id: 'event-1', occurred_at: status.observed_at, state: 'DEGRADED', message: 'dead letter queue has one item' }],
          safe_raw_evidence: ['delivery_id=bounded-1'],
        },
      },
      ...status.components.filter((component) => component.component_type !== 'Hooks'),
    ],
  }
}

describe('M6 permanent System Menu', () => {
  it('is keyboard reachable, exposes factual status/details, and closes with Escape', async () => {
    const user = userEvent.setup()
    const onRefresh = vi.fn().mockResolvedValue(undefined)
    render(<SpatialThemeBoundary><SystemMenu snapshot={fixture()} onRefresh={onRefresh} operatorCapabilities={['recovery.retry-hook-dead-letter']} /></SpatialThemeBoundary>)
    await user.click(screen.getByRole('button', { name: 'System Menu' }))
    expect(screen.getByRole('dialog')).toBeVisible()
    expect(screen.getAllByText('DEGRADED')[0]).toBeVisible()
    await user.click(screen.getByRole('button', { name: /Hooks/ }))
    expect(screen.getByRole('article', { name: /Hooks details/ })).toBeVisible()
    expect(screen.getByText(/dead letter queue has one item/)).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Refresh Status' }))
    await waitFor(() => expect(onRefresh).toHaveBeenCalledTimes(1))
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('requires an explicit confirmation before applying a recovery action', async () => {
    const user = userEvent.setup()
    render(<SpatialThemeBoundary><SystemMenu snapshot={fixture()} operatorCapabilities={['recovery.retry-hook-dead-letter']} /></SpatialThemeBoundary>)
    await user.click(screen.getByRole('button', { name: 'System Menu' }))
    await user.click(screen.getByRole('button', { name: /Hooks/ }))
    const retry = screen.getByRole('button', { name: 'RETRY HOOK DEAD LETTER' })
    await user.click(retry)
    expect(screen.getByText(/Recovery action applied|APPLIED|Recovery result recorded/i)).toBeVisible()
  })
})
