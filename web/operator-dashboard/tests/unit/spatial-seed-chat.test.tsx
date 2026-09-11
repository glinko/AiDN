import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { SceneTapGesture, seedLayout } from '@/spatial-calibration/interaction-seed'
import { SeedChat } from '@/spatial-calibration/SeedChat'
import { WorkspaceArtifactField } from '@/spatial-calibration/workspace-artifacts'
import { workspacePublicationSchema } from '@/spatial/contracts/workspace-chat'
import { workspaceArtifact, workspaceDocument } from '../fixtures/workspace-conversation'

vi.mock('@/spatial-calibration/primary-agent-voice', () => ({ usePrimaryAgentVoice: () => ({
  status: 'idle', capabilities: { recognition: false }, startListening: vi.fn(), stopListening: vi.fn(), error: null,
}) }))

describe('Spatial Interaction Seed', () => {
  it('distinguishes a tap from drag, pinch, cancellation and secondary click', () => {
    const gesture = new SceneTapGesture()
    expect(gesture.canTap()).toBe(false)
    gesture.down(1, 100, 100, 0); gesture.up(1)
    expect(gesture.canTap()).toBe(true)
    gesture.down(1, 100, 100, 0); gesture.move(120, 100); gesture.up(1)
    expect(gesture.canTap()).toBe(false)
    gesture.down(1, 100, 100, 0); gesture.down(2, 100, 100, 0); gesture.up(1); gesture.up(2)
    expect(gesture.canTap()).toBe(false)
    gesture.down(1, 100, 100, 0); gesture.cancel(1)
    expect(gesture.canTap()).toBe(false)
    gesture.down(1, 100, 100, 2); gesture.up(1)
    expect(gesture.canTap()).toBe(false)
  })

  it('clamps the seed, expanding text and history to desktop/mobile/keyboard viewports', () => {
    for (const viewport of [
      { width: 1280, height: 853, offsetTop: 0, offsetLeft: 0 },
      { width: 390, height: 844, offsetTop: 0, offsetLeft: 0 },
      { width: 390, height: 330, offsetTop: 150, offsetLeft: 0 },
    ]) {
      for (const point of [{ x: 0, y: 0 }, { x: 10000, y: 10000 }]) {
        for (const expanded of [false, true]) {
          const layout = seedLayout(point, viewport, expanded, 16000, 200, true)
          expect(layout.left).toBeGreaterThanOrEqual(viewport.offsetLeft)
          expect(layout.top).toBeGreaterThanOrEqual(viewport.offsetTop)
          expect(layout.left + layout.width).toBeLessThanOrEqual(viewport.offsetLeft + viewport.width)
          expect(layout.top + layout.height).toBeLessThanOrEqual(viewport.offsetTop + viewport.height)
        }
      }
    }
  })

  it('morphs the same input, submits only with the explicit shortcut and keeps failed text', async () => {
    const send = vi.fn().mockRejectedValueOnce(new Error('Канал недоступен')).mockResolvedValue('request-test')
    const close = vi.fn()
    const view = render(<SeedChat seed={{ id: 'session-test', point: { x: 250, y: 250 }, existing: false }} publication={null} online channelError={null} onSend={send} onClose={close} />)
    const input = screen.getByRole('textbox', { name: 'Сообщение в пространстве' })
    const trace = view.container.querySelector('.seed-chat__trace')
    expect(input).toHaveFocus()
    fireEvent.change(input, { target: { value: 'Тестовый вопрос' } })
    expect(view.container.querySelector('.seed-chat')).toHaveAttribute('data-expanded', 'true')
    expect(view.container.querySelector('.seed-chat__trace')).toBe(trace)
    expect(screen.getByRole('textbox')).toBe(input)
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(send).not.toHaveBeenCalled()
    fireEvent.keyDown(input, { key: 'Enter', ctrlKey: true })
    await screen.findByText('Канал недоступен')
    expect(input).toHaveValue('Тестовый вопрос')
    fireEvent.click(screen.getByRole('button', { name: 'Отправить в этот диалог' }))
    await waitFor(() => expect(input).toHaveValue(''))
    expect(send).toHaveBeenLastCalledWith('Тестовый вопрос', { conversation_id: 'session-test', action: 'message' })
    expect(screen.getByText('Вы · передано агенту')).toBeVisible()
    const active = workspaceDocument()
    view.rerender(<SeedChat seed={{ id: 'session-test', point: { x: 250, y: 250 }, existing: false }} publication={{ revision: 2, artifacts: [{ artifact: active.artifact, order: 0 }], active }} online channelError={null} onSend={send} onClose={close} />)
    expect(screen.getByText('Тестовый ответ')).toBeVisible()
    expect(screen.queryByText('Вы · передано агенту')).toBeNull()
    expect(screen.getByRole('textbox')).toBe(input)
    fireEvent.keyDown(input, { key: 'Escape' })
    expect(close).toHaveBeenCalledOnce()
  })

  it('opens an existing cube through the agent and does not show another session transcript', async () => {
    const send = vi.fn().mockResolvedValue('open-request')
    const wrong = workspaceDocument('other-session')
    render(<SeedChat seed={{ id: 'session-test', point: { x: 250, y: 250 }, existing: true }} publication={{ revision: 1, artifacts: [], active: wrong }} online channelError={null} onSend={send} onClose={vi.fn()} />)
    await waitFor(() => expect(send).toHaveBeenCalledOnce())
    expect(send.mock.calls[0]![1]).toEqual({ conversation_id: 'session-test', action: 'open' })
    expect(screen.queryByText('Тестовый ответ')).toBeNull()
    expect(screen.getByRole('textbox')).toBeDisabled()
  })
})

describe('Persistent artifact projection', () => {
  it('parses the existing canonical session/turn/artifact contracts', () => {
    const active = workspaceDocument()
    expect(workspacePublicationSchema.parse({ revision: 2, artifacts: [{ artifact: active.artifact, order: 0 }], active }).active?.turns).toHaveLength(2)
  })

  it('adds one cube, keeps object identity and eases old cubes backward on a horizontal plane', () => {
    const field = new WorkspaceArtifactField()
    field.sync([], null, true)
    const first = workspaceArtifact('first', 0)
    const cube = field.sync([first], 'first', true)[0]!
    expect(cube.birthElapsed).toBe(0)
    cube.advance(1, 0.05, false, false)
    const initialDepth = cube.position[2]
    const next = field.sync([first, workspaceArtifact('second', 1)], 'second', true)
    expect(next.find(item => item.sessionId === 'first')).toBe(cube)
    expect(cube.position[2]).toBe(initialDepth) // No teleport at publication time.
    for (let index = 0; index < 120; index++) cube.advance(index / 20, 0.05, false, false)
    expect(cube.position[2]).toBeLessThan(initialDepth)
    expect(cube.position[2]).toBeGreaterThan(cube.targetDepth)
    expect(Math.abs(cube.position[1] - 0.62)).toBeLessThanOrEqual(0.035)
    expect(cube.scale[0]).toBeLessThan(1)
    expect(cube.scale[1]).toBe(cube.scale[0])
    expect(cube.scale[2]).toBe(cube.scale[0])
    const paused = cube.position[2]
    cube.advance(6, 0.05, true, false)
    expect(cube.position[2]).toBe(paused)
    cube.advance(6, 0.05, false, true)
    expect(cube.position[2]).toBe(cube.targetDepth)
    expect(cube.birthElapsed).toBe(2)
  })

  it('does not replay births on reload; virtualizes renderers, never transcript records', () => {
    const field = new WorkspaceArtifactField()
    const catalog = Array.from({ length: 50 }, (_, index) => workspaceArtifact('session-' + index, index))
    const visible = field.sync(catalog, null, true)
    expect(visible).toHaveLength(32)
    expect(visible.every(item => item.birthElapsed === 2)).toBe(true)
    expect(field.sync(catalog, 'session-0', false)).toHaveLength(33)
    expect(catalog).toHaveLength(50)
  })
})
