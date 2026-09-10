import { describe, expect, it } from 'vitest'

import { dashboardSchemas } from '@/lib/types'
import {
  deliverVoiceMessage,
  extractAgentReply,
  extractLatestAgentReply,
  PRIMARY_AGENT_WELCOME,
} from '@/spatial-calibration/primary-agent-voice'

describe('Primary Agent voice bridge', () => {
  it('keeps the welcome phrase short and extracts only assistant-shaped replies', () => {
    expect(PRIMARY_AGENT_WELCOME).toBe('Привет! Чем займёмся сегодня?')
    expect(extractAgentReply({ text: 'operator echo' })).toBeNull()
    expect(extractAgentReply({ direction: 'AGENT', text: 'Готов помочь.' })).toBe('Готов помочь.')
    expect(extractAgentReply({ result: { output_text: 'Ответ готов.' } })).toBe('Ответ готов.')
  })

  it('selects a fresh agent message without replaying an older reply', () => {
    const conversation = dashboardSchemas.agentConversation.parse({
      connected: true,
      agent_id: 'agent:test',
      media: { text: true, attachments: false, detail: 'text only' },
      message_limit: 32,
      message_event_type: 'aidn.operator.chat',
      messages: [
        { message_id: 'old', direction: 'AGENT', agent_id: 'agent:test', text: 'Старый ответ', created_at: '1970-01-01T00:00:01.000Z' },
        { message_id: 'new', direction: 'AGENT', agent_id: 'agent:test', text: 'Новый ответ', created_at: '1970-01-01T00:00:10.000Z' },
      ],
    })
    expect(extractLatestAgentReply(conversation, new Set(['old']), 9_000)).toBe('Новый ответ')
    expect(extractLatestAgentReply(conversation, new Set(['old', 'new']), 9_000)).toBeNull()
  })

  it('delivers speech through the durable channel and waits for a new agent reply', async () => {
    const before = dashboardSchemas.agentConversation.parse({ connected: true, agent_id: 'agent:test', media: { text: true, attachments: false, detail: 'text only' }, message_limit: 32, message_event_type: 'aidn.operator.chat', messages: [] })
    const after = dashboardSchemas.agentConversation.parse({
      connected: true,
      agent_id: 'agent:test',
      media: { text: true, attachments: false, detail: 'text only' },
      message_limit: 32,
      message_event_type: 'aidn.operator.chat',
      messages: [{ message_id: 'reply-1', direction: 'AGENT', agent_id: 'agent:test', text: 'Я на связи.', created_at: '1970-01-01T00:00:01.000Z' }],
    })
    let reads = 0
    let clock = 0
    let sent = ''
    const reply = await deliverVoiceMessage('Проверь состояние ноды', {
      readConversation: async () => { reads += 1; return reads === 1 ? before : after },
      sendMessage: async (text) => { sent = text; return undefined },
      sleep: async (milliseconds) => { clock += milliseconds },
      now: () => clock,
      pollIntervalMs: 150,
      replyTimeoutMs: 600,
    })
    expect(sent).toBe('Проверь состояние ноды')
    expect(reply).toBe('Я на связи.')
    expect(reads).toBe(2)
  })
})
