import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { PrimaryAgentManagementSurface } from '@/spatial/workspace'
import { createPrimaryAgentSlot, MOCK_SPATIAL_SCOPE } from '@/spatial/data'
import { SpatialThemeBoundary } from '@/spatial/theme/SpatialThemeBoundary'

describe('Spatial M3.6 Primary Agent management surface', () => {
  it('shows safe slot fields and requires explicit revoke confirmation', async () => {
    const user = userEvent.setup()
    const onRevoke = vi.fn()
    const onHealthCheck = vi.fn()
    const slot = createPrimaryAgentSlot(MOCK_SPATIAL_SCOPE)
    render(<SpatialThemeBoundary><PrimaryAgentManagementSurface slot={slot} capabilities={['grant:read']} inboxLag={2} onRevoke={onRevoke} onHealthCheck={onHealthCheck} /></SpatialThemeBoundary>)
    await user.click(screen.getByText('Primary Agent management'))
    expect(screen.getByText('Node-scoped slot')).toBeVisible()
    expect(screen.getByText('grant:read')).toBeVisible()
    expect(screen.getByText('2 retained events')).toBeVisible()
    expect(screen.getByText('Credentials and secret material are never returned to this surface; only typed references and health evidence are shown.')).toBeVisible()
    expect(screen.getByText('Audit')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Health check' })).toBeEnabled()
    await user.click(screen.getByRole('button', { name: 'Revoke' }))
    expect(onRevoke).not.toHaveBeenCalled()
    expect(screen.getByRole('group', { name: 'Confirm Primary Agent revoke' })).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Confirm revoke' }))
    expect(onRevoke).toHaveBeenCalledOnce()
  })

  it('explains disabled actions for unassigned or revoked states', async () => {
    const user = userEvent.setup()
    const slot = createPrimaryAgentSlot(MOCK_SPATIAL_SCOPE)
    render(<SpatialThemeBoundary><PrimaryAgentManagementSurface slot={slot} disabledReason="No authorized binding plan is available." onReplace={vi.fn()} onDetach={vi.fn()} /></SpatialThemeBoundary>)
    await user.click(screen.getByText('Primary Agent management'))
    expect(screen.getByText('Action unavailable: No authorized binding plan is available.')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Replace' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Detach' })).toBeDisabled()
  })

  it('surfaces credential and protocol failures as explicit connection states', async () => {
    const user = userEvent.setup()
    const slot = { ...createPrimaryAgentSlot(MOCK_SPATIAL_SCOPE), lifecycle_state: 'CONNECTED' as const, current_binding_id: 'binding-health' }
    render(<SpatialThemeBoundary><PrimaryAgentManagementSurface slot={slot} health={{ node_id: slot.node_id, slot_id: slot.slot_id, binding_id: slot.current_binding_id, status: 'invalid-credentials', observed_at: '2026-09-05T16:00:00Z', source: 'fixture', revision: 1 }} /></SpatialThemeBoundary>)
    await user.click(screen.getByText('Primary Agent management'))
    expect(screen.getAllByText('invalid-credentials')).not.toHaveLength(0)
  })
})
