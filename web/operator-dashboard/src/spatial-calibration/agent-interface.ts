import { useCallback, useEffect, useRef, useState } from 'react'
import { dashboardApi } from '@/lib/api'
import { dashboardSchemas, type AgentConversation } from '@/lib/types'
import type { AgentFormChange } from '@/spatial/contracts/agent-document'
import type { WorkspaceChatIntent, WorkspacePublication } from '@/spatial/contracts/workspace-chat'
import { createDashboardSpatialSnapshotForPayload, type DashboardSpatialSceneData } from '@/spatial/data/dashboard-adapter'

export function interfaceId(prefix: string): string {
  return `${prefix}-${crypto.randomUUID()}`
}

function surfaceIdentity(): string {
  const key = 'aidn.spatial.surface.v1'
  try {
    const stored = sessionStorage.getItem(key)
    if (stored && /^[A-Za-z0-9_.:-]{1,128}$/.test(stored)) return stored
    const id = interfaceId('spatial')
    sessionStorage.setItem(key, id)
    return id
  } catch { return interfaceId('spatial') }
}

export function sceneFromAgentPublication(conversation: AgentConversation): DashboardSpatialSceneData | null {
  const scene = conversation.interface?.scene
  if (!scene) return null
  const data = scene.data
  if (typeof data.node_id !== 'string' || !data.node_id) throw new Error('В публикации агента отсутствует идентификатор ноды.')
  if (typeof data.agent_id !== 'string' || !data.agent_id) throw new Error('В публикации отсутствует идентификатор основного агента.')
  return createDashboardSpatialSnapshotForPayload({
    primaryAgent: { id: data.agent_id, label: 'Основной агент', state: 'CONNECTED', availability: 'AVAILABLE' },
    fleet: dashboardSchemas.fleet.parse(data.fleet),
    endpoints: dashboardSchemas.endpoints.parse(data.endpoints),
    sessions: dashboardSchemas.sessions.parse(data.sessions),
    observedAt: scene.observed_at,
    failures: Array.isArray(data.failures) ? data.failures.filter((item): item is string => typeof item === 'string') : [],
    // The publishing MCP agent is the Primary Agent, not the Resident Steward.
    // CONNECTED describes this observation, not inference runtime health.
    residentAgent: null,
  }, { hypervisor_id: 'local-hypervisor', node_id: data.node_id }, new Date(scene.observed_at)).scene
}

/** Browser transport reads agent publications only, never node configuration APIs. */
export function useAgentInterface() {
  const [surfaceId] = useState(surfaceIdentity)
  const [conversation, setConversation] = useState<AgentConversation | null>(null)
  const [scene, setScene] = useState<DashboardSpatialSceneData | null>(null)
  const [workspace, setWorkspace] = useState<WorkspacePublication | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [online, setOnline] = useState(false)
  const [pending, setPending] = useState<string | null>(null)
  const [refreshKey, setRefreshKey] = useState(0)
  const bootstrapSent = useRef(false)
  const mounted = useRef(true)
  const inFlight = useRef(false)
  const retryRequests = useRef(new Map<string, string>())
  const sceneRevision = useRef<string | undefined>(undefined)
  const boundAgent = useRef<string | null | undefined>(undefined)

  const send = useCallback(async (text: string, interaction?: AgentFormChange, chat?: WorkspaceChatIntent): Promise<string> => {
    if (!text.trim()) throw new Error('Введите сообщение агенту.')
    if (inFlight.current) throw new Error('Дождитесь отправки предыдущего сообщения.')
    const fingerprint = JSON.stringify({ text: text.trim(), interaction, chat })
    const requestId = retryRequests.current.get(fingerprint) ?? interfaceId('request')
    retryRequests.current.set(fingerprint, requestId)
    inFlight.current = true
    setError(null)
    try {
      await dashboardApi.sendAgentConversationMessage(text.trim(), { request_id: requestId, surface_id: surfaceId, interaction, chat })
      retryRequests.current.delete(fingerprint)
      if (mounted.current) { setPending(requestId); setRefreshKey(value => value + 1) }
      return requestId
    } catch (cause) {
      if (mounted.current) setError(cause instanceof Error ? cause.message : 'Не удалось передать сообщение агенту. Повторите отправку.')
      throw cause
    } finally { inFlight.current = false }
  }, [surfaceId])

  useEffect(() => {
    mounted.current = true
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout>
    const poll = async () => {
      try {
        const next = await dashboardApi.agentConversation(controller.signal, surfaceId)
        if (controller.signal.aborted) return
        if (next.agent_id !== boundAgent.current) {
          boundAgent.current = next.agent_id
          bootstrapSent.current = false
          sceneRevision.current = undefined
          setScene(null)
          setWorkspace(null)
        }
        const publication = next.interface?.scene
        if (publication?.revision !== sceneRevision.current) {
          setScene(sceneFromAgentPublication(next))
          sceneRevision.current = publication?.revision
        }
        setConversation(next)
        // Keep 3D artifact identities stable through ordinary channel polls.
        setWorkspace(current => JSON.stringify(current) === JSON.stringify(next.workspace ?? null) ? current : next.workspace ?? null)
        setOnline(next.connected)
        setError(null)
        setPending(current => current && (next.messages.some(message => message.direction === 'AGENT' && message.request_id === current)
          || next.workspace?.active?.turns.some(turn => turn.role === 'agent' && turn.intent_id === current)) ? null : current)
        if (next.connected && !publication && !bootstrapSent.current) {
          bootstrapSent.current = true
          const requestId = `scene-${surfaceId}`
          if (!next.messages.some(message => message.request_id === requestId)) {
            await dashboardApi.sendAgentConversationMessage('Покажи текущую spatial-сцену этой ноды: основной агент, endpoints, bundles и сессии. Опубликуй снимок сцены через MCP.', { request_id: requestId, surface_id: surfaceId })
          }
        }
      } catch (cause) {
        if (controller.signal.aborted) return
        bootstrapSent.current = false
        setOnline(false)
        setError(cause instanceof Error ? cause.message : 'Канал агента недоступен. Показан последний полученный снимок.')
      } finally {
        if (!controller.signal.aborted) timer = setTimeout(poll, document.hidden ? 8000 : 1500)
      }
    }
    void poll()
    return () => { mounted.current = false; controller.abort(); clearTimeout(timer) }
  }, [surfaceId, refreshKey])

  return { surfaceId, conversation, scene, workspace, online, error, pending, send }
}
