import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { SpatialRoute } from '@/spatial/spatial-route'
import { SpatialThemeBoundary } from '@/spatial/theme/SpatialThemeBoundary'
import { SPATIAL_TOKEN_VERSION, contrastRatio, spatialContrastSpecimens, spatialTokens } from '@/spatial/theme/tokens'

describe('Spatial M1.1 token package', () => {
  it('publishes a versioned token surface with the required primitive groups', () => {
    expect(SPATIAL_TOKEN_VERSION).toBe('spatial.tokens.v1')
    expect(spatialTokens.color.background.base).toBe('#fbfcfe')
    expect(spatialTokens.opacity.glass).toBe('0.68')
    expect(spatialTokens.shadow.soft).toContain('0 10px 28px')
    expect(spatialTokens.radius.medium).toBe('18px')
    expect(spatialTokens.blur.large).toBe('26px')
    expect(spatialTokens.spacing.six).toBe('24px')
    expect(spatialTokens.motion.enter).toBe('280ms')
  })

  it('keeps primary, secondary, and muted text at WCAG AA contrast', () => {
    expect(spatialContrastSpecimens).toHaveLength(3)
    for (const specimen of spatialContrastSpecimens) {
      expect(specimen.ratio).toBeGreaterThanOrEqual(4.5)
      expect(specimen.ratio).toBeCloseTo(contrastRatio(specimen.foreground, specimen.background), 8)
    }
  })

  it('scopes profile data attributes to the Spatial theme boundary', () => {
    render(
      <SpatialThemeBoundary contrast="high" transparency="reduced">
        <p>Scoped Spatial content</p>
      </SpatialThemeBoundary>,
    )

    const boundary = screen.getByText('Scoped Spatial content').parentElement
    expect(boundary).toHaveAttribute('data-aidn-theme-version', SPATIAL_TOKEN_VERSION)
    expect(boundary).toHaveAttribute('data-aidn-contrast', 'high')
    expect(boundary).toHaveAttribute('data-aidn-transparency', 'reduced')
  })

  it('lets the fixture switch contrast and transparency profiles without leaving Spatial', async () => {
    const user = userEvent.setup()
    render(<SpatialRoute onReturn={vi.fn()} />)

    const boundary = screen.getByRole('main').parentElement
    expect(boundary).toHaveAttribute('data-aidn-contrast', 'standard')
    expect(boundary).toHaveAttribute('data-aidn-transparency', 'full')

    await user.click(screen.getByRole('button', { name: 'High contrast' }))
    await user.click(screen.getByRole('button', { name: 'Reduced transparency' }))

    expect(boundary).toHaveAttribute('data-aidn-contrast', 'high')
    expect(boundary).toHaveAttribute('data-aidn-transparency', 'reduced')
    expect(screen.getByRole('heading', { name: 'Contrast specimen' })).toBeVisible()
    expect(screen.getByRole('button', { name: 'Replay motion' })).toBeEnabled()
  })
})

