import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { BellRing, ExternalLink, KeyRound, Link2, MessageCircle, RefreshCw, Send } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { dashboardApi } from '@/lib/api'
import { cn } from '@/lib/utils'

type AgentChannelProps = { onOpenHooks: () => void; onOpenSettings: () => void }

function deliveryLabel(value: unknown): string {
  if (!value || typeof value !== 'object') return 'not configured'
  const status = (value as Record<string, unknown>).status
  return typeof status === 'string' ? status.replaceAll('_', ' ') : 'ready'
}

export function AgentChannel({ onOpenHooks, onOpenSettings }: AgentChannelProps) {
  const channel = useQuery({
    queryKey: ['agent-conversation'],
    queryFn: ({ signal }) => dashboardApi.agentConversation(signal),
    refetchInterval: 5_000,
  })
  const [agentId, setAgentId] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState<'connect' | 'send' | null>(null)
  const [feedback, setFeedback] = useState<string | null>(null)
  const data = channel.data

  async function connect() {
    const value = agentId.trim()
    if (!value || busy) return
    setBusy('connect')
    setFeedback(null)
    try {
      await dashboardApi.connectAgentConversation(value)
      setAgentId(value)
      setFeedback('MCP agent bound. Operator messages will be delivered to its durable inbox.')
      await channel.refetch()
    } catch (error) {
      setFeedback(error instanceof Error ? error.message : 'Could not bind the MCP agent.')
    } finally {
      setBusy(null)
    }
  }

  async function send() {
    const value = message.trim()
    if (!value || !data?.connected || busy) return
    setBusy('send')
    setFeedback(null)
    try {
      await dashboardApi.sendAgentConversationMessage(value)
      setMessage('')
      await channel.refetch()
    } catch (error) {
      setFeedback(error instanceof Error ? error.message : 'Message delivery failed.')
    } finally {
      setBusy(null)
    }
  }

  return (
    <Card className="border-cyan-300/25 bg-cyan-300/[0.035] py-0 shadow-none">
      <CardHeader className="flex-row items-start justify-between gap-3 border-b border-cyan-300/15 px-5 py-4">
        <div className="min-w-0">
          <CardTitle className="flex items-center gap-2 text-lg font-semibold text-white"><MessageCircle className="size-5 text-cyan-200" />Connected MCP agent</CardTitle>
          <p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">Bind the identity configured by your agent’s MCP session. Messages are retained as canonical events and delivered through a durable inbox.</p>
        </div>
        <Button variant="outline" size="sm" className="min-h-11 shrink-0 border-cyan-300/25 bg-[#091725] text-cyan-100" onClick={() => void channel.refetch()} disabled={channel.isFetching}><RefreshCw className={cn(channel.isFetching && 'animate-spin')} />Refresh</Button>
      </CardHeader>
      <CardContent className="space-y-4 p-4 sm:p-5">
        <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto]">
          <label className="grid gap-1.5"><span className="text-sm font-medium text-slate-100">MCP agent identity</span><input value={agentId} onChange={(event) => setAgentId(event.target.value)} placeholder={data?.agent_id || 'mcp-credential:mcpcred-…'} className="h-11 rounded-lg border border-input bg-[#07111d] px-3 font-mono text-sm text-white outline-none placeholder:text-slate-600 focus:border-cyan-300" /></label>
          <div className="flex items-end"><Button className="min-h-11 w-full bg-cyan-300 text-[#06121d] hover:bg-cyan-200 lg:w-auto" onClick={() => void connect()} disabled={!agentId.trim() || busy !== null}><Link2 />{busy === 'connect' ? 'Binding…' : data?.connected ? 'Change agent' : 'Bind agent'}</Button></div>
        </div>
        <div className="flex flex-wrap items-center gap-2 rounded-xl border border-border/80 bg-[#07111d] px-3 py-2.5 text-xs text-slate-400">
          <Badge variant="outline" className={cn('font-mono text-[10px] uppercase', data?.connected ? 'border-emerald-300/30 text-emerald-100' : 'border-amber-300/35 text-amber-100')}>{data?.connected ? 'BOUND' : 'NOT BOUND'}</Badge>
          {data?.agent_id ? <span className="font-mono text-slate-200">{data.agent_id}</span> : <span>Connect an agent to open the operator channel.</span>}
          {data?.connected ? <span>· Durable delivery: {deliveryLabel(data.delivery)}</span> : null}
          <button type="button" className="ml-auto inline-flex items-center gap-1 text-cyan-200 hover:text-cyan-100" onClick={onOpenHooks}><BellRing className="size-3.5" />Hooks</button>
        </div>
        <div className="max-h-[30rem] overflow-y-auto rounded-xl border border-border/80 bg-[#07111d]" aria-live="polite">
          {!data?.messages.length ? <p className="px-4 py-10 text-center text-sm text-slate-500">No messages yet. The connected agent reads messages using <code className="font-mono text-slate-300">aidn.event.inbox</code> and replies using <code className="font-mono text-slate-300">aidn.operator.chat.reply</code>.</p> : <ol className="divide-y divide-border/70">{data.messages.map((item) => <li key={item.message_id} className={cn('border-l-2 px-4 py-3', item.direction === 'OPERATOR' ? 'border-cyan-300/50' : 'border-emerald-300/45')}><div className="flex items-center justify-between gap-3"><span className={cn('font-mono text-[10px] tracking-[0.12em]', item.direction === 'OPERATOR' ? 'text-cyan-200' : 'text-emerald-200')}>{item.direction === 'OPERATOR' ? 'OPERATOR' : 'AGENT'}</span><time className="text-[11px] text-slate-500">{new Date(item.created_at).toLocaleString()}</time></div><p className="mt-1 whitespace-pre-wrap break-words text-sm leading-6 text-slate-100">{item.text}</p></li>)}</ol>}
        </div>
        <form className="flex flex-col gap-2 sm:flex-row sm:items-end" onSubmit={(event) => { event.preventDefault(); void send() }}>
          <label className="grid min-w-0 flex-1 gap-1.5"><span className="text-sm font-medium text-slate-100">Message</span><textarea value={message} onChange={(event) => setMessage(event.target.value)} rows={2} maxLength={16_384} disabled={!data?.connected || busy !== null} placeholder={data?.connected ? 'Write to the connected agent…' : 'Bind an MCP agent first'} className="w-full resize-y rounded-lg border border-input bg-[#07111d] px-3 py-2.5 text-sm text-white outline-none placeholder:text-slate-600 focus:border-cyan-300 disabled:cursor-not-allowed disabled:opacity-55" /></label>
          <Button type="submit" className="min-h-11 shrink-0 bg-cyan-300 text-[#06121d] hover:bg-cyan-200" disabled={!data?.connected || !message.trim() || busy !== null}><Send />{busy === 'send' ? 'Sending…' : 'Send'}</Button>
        </form>
        <section className="border-t border-cyan-300/15 pt-4" aria-labelledby="codex-oauth-agent-title">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div className="max-w-3xl">
              <h3 id="codex-oauth-agent-title" className="flex items-center gap-2 text-sm font-semibold text-slate-100"><KeyRound className="size-4 text-cyan-200" />Connect Codex with ChatGPT OAuth</h3>
              <p className="mt-1 text-sm leading-6 text-muted-foreground">Run the Codex bridge on the trusted machine that hosts Codex. It presents a device code for ChatGPT sign-in, keeps OAuth tokens in Codex’s own profile, and relays this durable MCP inbox. AiDN never stores the ChatGPT refresh token.</p>
            </div>
            <Button type="button" variant="outline" size="sm" className="min-h-11 shrink-0 border-cyan-300/25 bg-[#091725] text-cyan-100" onClick={onOpenSettings}><ExternalLink />Issue MCP token</Button>
          </div>
          <ol className="mt-3 grid gap-2 text-xs leading-5 text-slate-400 sm:grid-cols-3">
            <li><span className="mr-1 font-semibold text-cyan-100">1.</span>Issue a dedicated credential with <code className="font-mono text-slate-200">AUDIT:READ</code> and <code className="font-mono text-slate-200">CHAT:WRITE</code>.</li>
            <li><span className="mr-1 font-semibold text-cyan-100">2.</span>Bind <code className="font-mono text-slate-200">mcp-credential:&lt;credential_id&gt;</code> above.</li>
            <li><span className="mr-1 font-semibold text-cyan-100">3.</span>Run <code className="font-mono text-slate-200">aidn-codex-agent … login</code>, then start its relay.</li>
          </ol>
        </section>
        <p className="text-xs leading-5 text-slate-500">Text is available now. Voice, images and files will use a separate content-addressed attachment store; binary data is intentionally not written into the event journal.</p>
        {feedback ? <p className="rounded-lg border border-cyan-300/20 bg-cyan-300/[0.05] px-3 py-2 text-xs leading-5 text-cyan-100" role="status">{feedback}</p> : null}
      </CardContent>
    </Card>
  )
}
