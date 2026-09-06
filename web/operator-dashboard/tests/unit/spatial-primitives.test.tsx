import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { Info } from 'lucide-react'

import { SpatialThemeBoundary } from '@/spatial/theme/SpatialThemeBoundary'
import {
  Button,
  FocusRing,
  GlassFrame,
  IconButton,
  InsetField,
  Input,
  RaisedControl,
  Slider,
  StatusLabel,
  Surface,
  TextArea,
  Toggle,
  Tooltip,
} from '@/spatial/primitives'

describe('Spatial M1.2 DOM primitives', () => {
  it('keeps the surface contract declarative and semantic', () => {
    render(
      <SpatialThemeBoundary>
        <Surface depth="inset" glass="soft" accent="violet" radius="small" emphasis="secondary">Surface content</Surface>
        <GlassFrame depth="floating" glass="strong" accent="cyan" radius="large">Frame content</GlassFrame>
        <RaisedControl depth="raised" glass="soft">Raised content</RaisedControl>
        <FocusRing><button type="button">Focus target</button></FocusRing>
      </SpatialThemeBoundary>,
    )

    expect(screen.getByText('Surface content')).toHaveAttribute('data-slot', 'spatial-surface')
    expect(screen.getByText('Surface content')).toHaveAttribute('data-aidn-depth', 'inset')
    expect(screen.getByText('Surface content')).toHaveAttribute('data-aidn-glass', 'soft')
    expect(screen.getByText('Surface content')).toHaveAttribute('data-aidn-accent', 'violet')
    expect(screen.getByText('Frame content')).toHaveAttribute('data-slot', 'glass-frame')
    expect(screen.getByText('Raised content')).toHaveAttribute('data-slot', 'raised-control')
    expect(screen.getByRole('button', { name: 'Focus target' })).toBeEnabled()
  })

  it('does not submit a form unless a button explicitly opts into submit', async () => {
    const user = userEvent.setup()
    const submit = vi.fn((event: React.FormEvent) => event.preventDefault())
    const action = vi.fn()
    render(
      <form onSubmit={submit}>
        <Button>Safe action</Button>
        <Button onClick={action}>Explicit action</Button>
      </form>,
    )

    await user.click(screen.getByRole('button', { name: 'Safe action' }))
    expect(submit).not.toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: 'Explicit action' }))
    expect(action).toHaveBeenCalledOnce()
  })

  it('requires accessible labels and preserves native field semantics', async () => {
    const user = userEvent.setup()
    const onCheckedChange = vi.fn()
    render(
      <SpatialThemeBoundary>
        <InsetField label="Workspace name" htmlFor="workspace-name" hint="Stable Node-owned label">
          <Input id="workspace-name" placeholder="Name" />
        </InsetField>
        <InsetField label="Operator note" htmlFor="operator-note">
          <TextArea id="operator-note" placeholder="Note" />
        </InsetField>
        <Toggle aria-label="Enable preview" checked onCheckedChange={onCheckedChange} />
        <Slider aria-label="Preview intensity" min="0" max="100" defaultValue="50" />
      </SpatialThemeBoundary>,
    )

    expect(screen.getByLabelText('Workspace name')).toHaveAttribute('id', 'workspace-name')
    expect(screen.getByLabelText('Workspace name')).toHaveAttribute('aria-describedby')
    expect(screen.getByLabelText('Operator note')).toHaveAttribute('id', 'operator-note')
    const toggle = screen.getByRole('switch', { name: 'Enable preview' })
    expect(toggle).toHaveAttribute('aria-checked', 'true')
    await user.click(toggle)
    expect(onCheckedChange).toHaveBeenCalledWith(false)
    expect(screen.getByRole('slider', { name: 'Preview intensity' })).toHaveAttribute('type', 'range')
  })

  it('opens tooltip content for a keyboard-focused icon button', async () => {
    render(
      <SpatialThemeBoundary>
        <Tooltip content="More information">
          <IconButton aria-label="More information"><Info aria-hidden="true" /></IconButton>
        </Tooltip>
      </SpatialThemeBoundary>,
    )

    const trigger = screen.getByRole('button', { name: 'More information' })
    trigger.focus()
    await waitFor(() => expect(screen.getByRole('tooltip', { name: 'More information' })).toBeVisible())
    expect(trigger).toHaveAttribute('aria-describedby')
  })

  it('exposes status meaning through text and state attributes', () => {
    render(
      <SpatialThemeBoundary>
        <StatusLabel status="ready">Ready</StatusLabel>
        <StatusLabel status="critical">Unavailable</StatusLabel>
      </SpatialThemeBoundary>,
    )

    expect(screen.getByText('Ready')).toHaveAttribute('data-aidn-status', 'ready')
    expect(screen.getByText('Unavailable')).toHaveAttribute('data-aidn-status', 'critical')
  })
})
