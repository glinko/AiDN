import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { isFeatureFlagEnabled, SPATIAL_UI_FEATURE_FLAG } from '@/lib/feature-flags'
import { SpatialRouteBoundary } from '@/spatial/route-boundary'
import { detectWebGL2, isSpatialRoute, openSpatialRoute } from '@/spatial/route'

const supportedWebGL2 = () => ({ supported: true as const, reason: 'supported' as const })
const unavailableWebGL2 = () => ({ supported: false as const, reason: 'unavailable' as const })

function renderBoundary(options: { capability?: typeof supportedWebGL2; rendererStatus?: 'ready' | 'failed' } = {}) {
  return render(
    <SpatialRouteBoundary
      classic={<p>Classic surface</p>}
      detectCapability={options.capability ?? supportedWebGL2}
      rendererStatus={options.rendererStatus}
    />,
  )
}

describe('Spatial feature flag and route boundary', () => {
  it('defaults the rollout flag off and accepts a server-rendered enablement', () => {
    expect(isFeatureFlagEnabled(SPATIAL_UI_FEATURE_FLAG)).toBe(false)
    vi.stubEnv('VITE_SPATIAL_UI_ENABLED', 'true')
    expect(isFeatureFlagEnabled(SPATIAL_UI_FEATURE_FLAG)).toBe(true)
    window.__AIDN_FEATURE_FLAGS__ = { spatial_ui_enabled: true }
    expect(isFeatureFlagEnabled(SPATIAL_UI_FEATURE_FLAG)).toBe(true)
    window.__AIDN_FEATURE_FLAGS__ = { spatial_ui_enabled: false }
    expect(isFeatureFlagEnabled(SPATIAL_UI_FEATURE_FLAG)).toBe(false)
  })

  it('keeps Classic as the direct-url fallback when the flag is disabled', () => {
    window.history.replaceState(null, '', '#spatial')
    renderBoundary()

    expect(screen.getByRole('heading', { name: 'Spatial UI is disabled' })).toBeVisible()
    expect(screen.getByRole('button', { name: 'Return to Classic UI' })).toBeEnabled()
  })

  it('renders the gated Spatial surface and returns to the prior Classic hash', async () => {
    window.history.replaceState(null, '', '#settings')
    window.__AIDN_FEATURE_FLAGS__ = { spatial_ui_enabled: true }
    renderBoundary()

    openSpatialRoute()
    expect(await screen.findByRole('heading', { name: 'Spatial Workspace preview' })).toBeVisible()
    expect(window.location.hash).toBe('#spatial')

    await userEvent.click(screen.getByRole('button', { name: 'Return to Classic UI' }))
    await waitFor(() => expect(screen.getByText('Classic surface')).toBeVisible())
    expect(window.location.hash).toBe('#settings')
  })

  it('falls back when WebGL2 is unavailable', () => {
    window.history.replaceState(null, '', '#spatial')
    window.__AIDN_FEATURE_FLAGS__ = { spatial_ui_enabled: true }
    renderBoundary({ capability: unavailableWebGL2 })

    expect(screen.getByRole('heading', { name: 'Spatial UI needs WebGL2' })).toBeVisible()
    expect(screen.getByRole('main')).toHaveAttribute('data-spatial-route-state', 'webgl2-unavailable')
  })

  it('falls back after renderer initialization failure without exposing GPU details', async () => {
    window.history.replaceState(null, '', '#spatial')
    window.__AIDN_FEATURE_FLAGS__ = { spatial_ui_enabled: true }
    const warning = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    renderBoundary({ rendererStatus: 'failed' })

    expect(screen.getByRole('heading', { name: 'Spatial renderer could not start' })).toBeVisible()
    await waitFor(() => expect(warning).toHaveBeenCalledWith('[spatial] renderer initialization failed', { reason: 'renderer-init-failed' }))
    expect(warning.mock.calls[0]?.flat().join(' ')).not.toContain('GPU')
  })

  it('identifies the Spatial hash and reports a browser without WebGL2', () => {
    expect(isSpatialRoute('#spatial?from=overview')).toBe(true)
    expect(isSpatialRoute('#overview')).toBe(false)
    expect(detectWebGL2().supported).toBe(false)
  })
})
