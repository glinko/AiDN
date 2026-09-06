import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { SpatialThemeBoundary } from '@/spatial/theme/SpatialThemeBoundary'
import { SpatialWorkspace, readSpatialViewport } from '@/spatial/workspace'

function renderWorkspace(props: React.ComponentProps<typeof SpatialWorkspace> = {}) {
  return render(
    <SpatialThemeBoundary>
      <SpatialWorkspace {...props} />
    </SpatialThemeBoundary>,
  )
}

describe('Spatial M1.3 hybrid renderer shell', () => {
  it('keeps the DOM overlay interactive and preserves selection across orientation changes', async () => {
    const user = userEvent.setup()
    const originalWidth = window.innerWidth
    const originalHeight = window.innerHeight
    renderWorkspace()

    const workspace = document.querySelector('[data-spatial-workspace="hybrid"]') as HTMLElement
    await waitFor(() => expect(document.querySelector('[data-aidn-canvas-state="fallback"]')).toBeTruthy())
    const canvas = document.querySelector('canvas[data-aidn-canvas-renderer="2d-fallback"]')
    expect(canvas).toHaveAttribute('tabindex', '-1')
    expect(canvas).toHaveAttribute('aria-hidden', 'true')
    expect(document.querySelector('[data-spatial-layer="dom-overlay"]')).toHaveAttribute('aria-label', 'Spatial DOM overlay')
    expect(screen.getByRole('button', { name: 'Open GlassFrame' }).closest('[data-interactive="true"]')).toBeTruthy()

    fireEvent.click(canvas as HTMLCanvasElement)
    expect(screen.getByText('Mock Primary Agent')).toBeVisible()
    expect(workspace).toHaveAttribute('data-aidn-selected-node', 'mock-agent')
    const revision = Number(workspace.getAttribute('data-aidn-viewport-revision'))

    try {
      Object.defineProperty(window, 'innerWidth', { configurable: true, value: 480 })
      Object.defineProperty(window, 'innerHeight', { configurable: true, value: 800 })
      window.dispatchEvent(new Event('orientationchange'))
      await waitFor(() => expect(workspace).toHaveAttribute('data-aidn-viewport-orientation', 'portrait'))
      expect(Number(workspace.getAttribute('data-aidn-viewport-revision'))).toBeGreaterThan(revision)
      expect(screen.getByText('Mock Primary Agent')).toBeVisible()
    } finally {
      Object.defineProperty(window, 'innerWidth', { configurable: true, value: originalWidth })
      Object.defineProperty(window, 'innerHeight', { configurable: true, value: originalHeight })
    }

    await user.click(screen.getByRole('button', { name: 'DOM control over canvas' }))
    expect(screen.getByText('DOM control handled the action without touching the canvas.')).toBeVisible()
  })

  it('exposes the Prototype A state, entity, camera, and quality controls in the DOM layer', async () => {
    const user = userEvent.setup()
    renderWorkspace()
    const workspace = document.querySelector('[data-spatial-workspace="hybrid"]') as HTMLElement
    await waitFor(() => expect(document.querySelector('[data-aidn-canvas-state="fallback"]')).toBeTruthy())

    await user.click(screen.getByRole('button', { name: 'Open GlassFrame' }))
    expect(screen.getByRole('button', { name: 'Primary Agent, Ready' })).toBeVisible()
    expect(screen.getByLabelText('Scene quality')).toHaveValue('desktop')
    await user.selectOptions(screen.getByLabelText('Scene quality'), 'high')
    expect(workspace).toHaveAttribute('data-aidn-quality-profile', 'high')

    await user.click(screen.getByRole('button', { name: 'Cycle state' }))
    expect(workspace).toHaveAttribute('data-aidn-primary-agent-state', 'THINKING')
    expect(screen.getByText('Reasoning is in progress; no action has been committed.')).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Primary Agent, Thinking' }))
    expect(workspace).toHaveAttribute('data-aidn-camera-focus', 'primary-agent')
  })

  it('selects semantic entities from the keyboard list and navigates focus locally', async () => {
    const user = userEvent.setup()
    renderWorkspace()
    const workspace = document.querySelector('[data-spatial-workspace="hybrid"]') as HTMLElement
    await waitFor(() => expect(document.querySelector('[data-aidn-canvas-state="fallback"]')).toBeTruthy())
    await user.click(screen.getByRole('button', { name: 'Open GlassFrame' }))
    await user.click(screen.getByText(/Keyboard entity list/))
    await user.click(screen.getByRole('button', { name: /Browser endpoint/ }))
    expect(workspace).toHaveAttribute('data-aidn-selected-node', 'endpoint-browser')
    expect(screen.getByRole('button', { name: /Browser endpoint/ })).toBeVisible()

    await user.click(screen.getByRole('button', { name: 'Focus selected' }))
    expect(workspace).toHaveAttribute('data-aidn-camera-focus', 'endpoint-browser')
    await user.click(screen.getByRole('button', { name: 'Back from focus' }))
    expect(workspace).toHaveAttribute('data-aidn-camera-focus', 'home')

    const navigation = document.querySelector('[data-aidn-navigation-controller]') as HTMLElement
    navigation.focus()
    await user.keyboard('{Home}')
    expect(workspace).toHaveAttribute('data-aidn-camera-focus', 'home')
  })

  it('caps DPR for mobile and desktop scene budgets', () => {
    const descriptor = Object.getOwnPropertyDescriptor(window, 'devicePixelRatio')
    try {
      Object.defineProperty(window, 'devicePixelRatio', { configurable: true, value: 3 })
      expect(readSpatialViewport(null, { width: 480, height: 800 }).dpr).toBe(1.25)
      expect(readSpatialViewport(null, { width: 1280, height: 720 }).dpr).toBe(1.5)
    } finally {
      if (descriptor) Object.defineProperty(window, 'devicePixelRatio', descriptor)
    }
  })

  it('catches renderer failures and leaves a usable DOM fallback', async () => {
    const onReturn = vi.fn()
    const warning = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    renderWorkspace({ onReturn, simulateRendererError: true })

    expect(screen.getByRole('alert')).toHaveAttribute('data-spatial-renderer-state', 'error')
    expect(screen.getByRole('heading', { name: 'Spatial scene paused' })).toBeVisible()
    await waitFor(() => expect(warning).toHaveBeenCalledWith('[spatial] renderer initialization failed', { reason: 'renderer-init-failed' }))
    await userEvent.click(screen.getByRole('button', { name: 'Return to Classic UI' }))
    expect(onReturn).toHaveBeenCalledOnce()
  })

  it('makes offline Workspace evidence explicit while keeping controls usable', async () => {
    renderWorkspace({ workspaceDataMode: 'offline' })
    const workspace = document.querySelector('[data-spatial-workspace="hybrid"]') as HTMLElement
    expect(workspace).toHaveAttribute('data-aidn-workspace-data-state', 'offline')
    expect(workspace).toHaveAttribute('data-aidn-workspace-freshness', 'UNAVAILABLE')
    await userEvent.click(screen.getByRole('button', { name: 'Open GlassFrame' }))
    expect(screen.getByText('Node data · Offline snapshot')).toBeVisible()
    expect(screen.getByText('Node is offline; showing the last persisted snapshot.')).toBeVisible()
  })
})
