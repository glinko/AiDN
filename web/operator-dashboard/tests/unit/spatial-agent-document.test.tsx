import { act, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { dashboardApi } from '@/lib/api'
import { AgentDocumentFrame, formValue } from '@/spatial/components/AgentDocumentFrame'
import { agentDocumentSchema, type AgentDocument, type AgentDocumentField, type AgentFormChange, type AgentInterface } from '@/spatial/contracts/agent-document'
import { usePrimaryAgentVoice } from '@/spatial-calibration/primary-agent-voice'
import { useAgentInterface } from '@/spatial-calibration/agent-interface'
import { dashboardSchemas } from '@/lib/types'

const field = (overrides: Partial<AgentDocumentField>): AgentDocumentField => ({
  id: 'parameter.temperature', label: 'Temperature', type: 'number', value: 0.7, editable: true,
  description: 'Значение по умолчанию.', minimum: 0, maximum: 2, options: [], ...overrides,
})
const document: AgentDocument = {
  schema_version: 'agent-document.v1', document_id: 'settings', surface_id: 'surface-test', request_id: 'read',
  title: 'Настройки llama.cpp', revision: 1, updated_at: '2026-09-10T10:00:00Z',
  blocks: [
    { type: 'text', text: 'Параметры запросов к endpoint.' },
    { type: 'fields', title: 'Параметры', source_id: 'source-1', source_revision: 'rev-1', target_id: 'ep-1', fields: [
      field({}), field({ id: 'model_id', label: 'Модель', type: 'text', value: 'model-1', editable: false, minimum: null, maximum: null }),
    ] },
  ],
}
const noopSubmit = async (_text: string, _change: AgentFormChange) => 'request-change'

afterEach(() => { vi.restoreAllMocks() })

describe('Agent-authored settings frame', () => {
  it('emits exact old/new values to the agent and does not claim a local save', async () => {
    const submit = vi.fn(noopSubmit)
    const user = userEvent.setup()
    render(<AgentDocumentFrame document={document} intents={[]} messages={[]} onSubmit={submit} />)
    expect(screen.getByText('model-1')).toBeVisible()
    expect(screen.queryByRole('textbox', { name: 'Модель' })).not.toBeInTheDocument()
    const input = screen.getByRole('spinbutton', { name: 'Temperature' })
    await user.clear(input)
    await user.type(input, '0.4')
    await user.click(screen.getByRole('button', { name: 'Применить через агента' }))
    expect(submit).toHaveBeenCalledTimes(1)
    expect(submit.mock.calls[0]?.[1]).toEqual({ kind: 'form_change', document_id: 'settings', document_revision: 1,
      source_id: 'source-1', source_revision: 'rev-1', current: { 'parameter.temperature': 0.7 }, proposed: { 'parameter.temperature': 0.4 } })
    expect(screen.getByText(/значения ещё не подтверждены/)).toBeVisible()
    expect(screen.queryByText('Нода подтвердила изменение.')).not.toBeInTheDocument()
  })

  it('retains dirty input on unrelated document updates and requires an explicit refresh', async () => {
    const user = userEvent.setup()
    const view = render(<AgentDocumentFrame document={document} intents={[]} messages={[]} onSubmit={noopSubmit} />)
    fireEvent.change(screen.getByRole('spinbutton'), { target: { value: '0.4' } })
    const next = structuredClone(document)
    next.revision = 2
    if (next.blocks[1]?.type === 'fields') next.blocks[1].fields[0]!.value = 0.8
    view.rerender(<AgentDocumentFrame document={next} intents={[]} messages={[]} onSubmit={noopSubmit} />)
    expect(screen.getByRole('spinbutton')).toHaveValue(0.4)
    expect(screen.getByRole('button', { name: 'Применить через агента' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: /Загрузить новые значения/ }))
    expect(screen.getByRole('spinbutton')).toHaveValue(0.8)
  })

  it('updates the same frame only after a verified MCP result', async () => {
    const submitted: AgentFormChange = { kind: 'form_change', document_id: 'settings', document_revision: 1,
      source_id: 'source-1', source_revision: 'rev-1', current: { 'parameter.temperature': 0.7 }, proposed: { 'parameter.temperature': 0.4 } }
    const user = userEvent.setup()
    const view = render(<AgentDocumentFrame document={document} intents={[]} messages={[]} onSubmit={noopSubmit} />)
    fireEvent.change(screen.getByRole('spinbutton'), { target: { value: '0.4' } })
    await user.click(screen.getByRole('button', { name: 'Применить через агента' }))
    const next = structuredClone(document)
    next.revision = 2
    if (next.blocks[1]?.type === 'fields') {
      next.blocks[1].source_id = 'source-2'
      next.blocks[1].source_revision = 'rev-2'
      next.blocks[1].fields[0]!.value = 0.4
    }
    const intents: AgentInterface['intents'] = [{ intent_id: 'request-change', surface_id: 'surface-test', change: submitted, state: 'APPLIED', result: { verified: true } }]
    view.rerender(<AgentDocumentFrame document={next} intents={intents} messages={[]} onSubmit={noopSubmit} />)
    await waitFor(() => expect(screen.getByText('Нода подтвердила изменение.')).toBeVisible())
    expect(screen.getByRole('spinbutton')).toHaveValue(0.4)
    expect(screen.getByRole('button', { name: 'Применить через агента' })).toBeDisabled()
  })

  it('keeps the draft and shows a failed submission', async () => {
    const user = userEvent.setup()
    render(<AgentDocumentFrame document={document} intents={[]} messages={[]} onSubmit={async () => { throw new Error('Канал недоступен') }} />)
    fireEvent.change(screen.getByRole('spinbutton'), { target: { value: '0.4' } })
    await user.click(screen.getByRole('button', { name: 'Применить через агента' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Канал недоступен')
    expect(screen.getByRole('spinbutton')).toHaveValue(0.4)
  })

  it('renders model text as text and rejects unknown blocks or executable content', () => {
    const safe = { ...document, blocks: [{ type: 'text' as const, text: '<img src=x onerror=alert(1)>' }] }
    const view = render(<AgentDocumentFrame document={safe} intents={[]} messages={[]} onSubmit={noopSubmit} />)
    expect(view.container.querySelector('img')).toBeNull()
    expect(screen.getByText('<img src=x onerror=alert(1)>')).toBeVisible()
    expect(agentDocumentSchema.safeParse({ ...document, blocks: [{ type: 'html', html: '<script/>' }] }).success).toBe(false)
    view.rerender(<AgentDocumentFrame document={{ ...document, blocks: [{ type: 'text', text: '<script>alert(1)</script>' }] }} intents={[]} messages={[]} onSubmit={noopSubmit} />)
    expect(screen.getByRole('alert')).toHaveTextContent('Документ не прошёл проверку')
    expect(view.container.querySelector('script')).toBeNull()
  })

  it('enforces numeric and boolean types without silently coercing empty input', () => {
    expect(() => formValue(field({}), '')).toThrow()
    expect(() => formValue(field({}), 'Infinity')).toThrow()
    expect(() => formValue(field({}), '5')).toThrow()
    expect(() => formValue(field({ type: 'integer' }), '0.5')).toThrow()
    expect(formValue(field({ type: 'boolean' }), false)).toBe(false)
    expect(() => formValue(field({ type: 'boolean' }), 'false')).toThrow()
  })
})

describe('Spatial agent channel', () => {
  it('does not call TTS for an agent reply, keeping speech input independent', async () => {
    const synthesize = vi.spyOn(dashboardApi, 'synthesizeSpeech')
    const deliver = vi.fn(async () => 'Ответ текстом')
    const { result } = renderHook(() => usePrimaryAgentVoice({ deliver }))
    await act(async () => { await result.current.submit('Покажи настройки') })
    expect(deliver).toHaveBeenCalledWith('Покажи настройки')
    expect(result.current.response).toBe('Ответ текстом')
    expect(result.current.status).toBe('idle')
    expect(synthesize).not.toHaveBeenCalled()
  })

  it('requests the scene via the agent channel, without direct dashboard reads', async () => {
    const transport = vi.spyOn(dashboardApi, 'agentConversation').mockResolvedValue(dashboardSchemas.agentConversation.parse({ connected: true, agent_id: 'agent-a', messages: [], media: { detail: 'text' } }))
    const send = vi.spyOn(dashboardApi, 'sendAgentConversationMessage').mockResolvedValue({})
    const fetcher = vi.spyOn(globalThis, 'fetch')
    const { result } = renderHook(() => useAgentInterface())
    await waitFor(() => expect(send).toHaveBeenCalledOnce())
    expect(send.mock.calls[0]?.[1]?.surface_id).toBe(result.current.surfaceId)
    expect(transport.mock.calls[0]?.[1]).toBe(result.current.surfaceId)
    expect(fetcher).not.toHaveBeenCalled()
  })
})
