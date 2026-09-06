import { useMemo, useState } from 'react'

import { ChangeIntentService, type ChangeIntentApplyResult, type ChangeIntentValidation } from '@/spatial/components'
import type { SpatialChangeIntent } from '@/spatial/contracts'

type EndpointConfigurationProps = {
  workspaceId: string
  nodeId: string
  endpointRef: string
  revision: number
  actorRef: string
  initialPort?: number | null
  variant?: 'classic' | 'spatial'
  source?: 'form' | 'voice' | 'spatial'
  agentOnline?: boolean
  capabilities?: readonly string[]
  occupied?: (port: number) => boolean
  onIntent?: (intent: SpatialChangeIntent, validation: ChangeIntentValidation) => void
  onApply?: (result: ChangeIntentApplyResult) => void
}

/**
 * Shared, deliberately small Endpoint configuration boundary. It emits a
 * typed Change Intent; the parent decides which Node/MCP command adapter to
 * use. No browser-side form computes authority or invoice values.
 */
export function EndpointConfiguration({
  workspaceId,
  nodeId,
  endpointRef,
  revision,
  actorRef,
  initialPort = null,
  variant = 'classic',
  source = variant === 'spatial' ? 'spatial' : 'form',
  agentOnline = true,
  capabilities = ['endpoint:change'],
  occupied,
  onIntent,
  onApply,
}: EndpointConfigurationProps) {
  const [port, setPort] = useState(initialPort === null ? '' : String(initialPort))
  const [intent, setIntent] = useState<SpatialChangeIntent | null>(null)
  const [validation, setValidation] = useState<ChangeIntentValidation | null>(null)
  const [message, setMessage] = useState('No change proposed.')
  const service = useMemo(() => new ChangeIntentService(), [])

  function preview() {
    const nextPort = Number(port)
    if (!Number.isInteger(nextPort) || nextPort < 1 || nextPort > 65_535) {
      setMessage('Enter a valid port from 1 to 65535.')
      setValidation(null)
      return
    }
    try {
      const nextIntent = service.create({
        workspaceId,
        nodeId,
        target: { type: 'endpoint', id: endpointRef, revision },
        current: { port: initialPort },
        proposed: { port: nextPort },
        fieldSchema: [{ path: 'port', type: 'integer', editable: true, required: true, minimum: 1, maximum: 65_535 }],
        actorRef,
        idempotencyKey: `${endpointRef}:port:${nextPort}`,
        currentRevision: revision,
        source,
      })
      const result = service.validate(nextIntent, { currentRevision: revision, agentOnline, capabilities, occupied: (path, value) => path === 'port' && typeof value === 'number' && Boolean(occupied?.(value)) })
      setIntent(nextIntent)
      setValidation(result)
      setMessage(result.state === 'VALID' ? 'Change Intent validated. Apply is explicit and auditable.' : `${result.state}: ${result.alternatives[0] ?? 'Review the endpoint evidence.'}`)
      onIntent?.(nextIntent, result)
    } catch (error) {
      setValidation(null)
      setMessage(error instanceof Error ? error.message : 'Change Intent could not be created.')
    }
  }

  function apply() {
    if (!intent || !validation) return
    try {
      const result = service.apply(intent, {
        confirm: true,
        validation,
        applyCanonical: (candidate) => ({ revision: candidate.target.revision + 1, resultRef: `change-result:${candidate.intent_id}` }),
      })
      setMessage(`Applied ${result.intent.intent_id} at revision ${result.revision}.`)
      onApply?.(result)
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Change Intent was not applied.')
    }
  }

  return (
    <section className={variant === 'spatial' ? 'aidn-endpoint-configuration aidn-endpoint-configuration-spatial' : 'aidn-endpoint-configuration'} aria-labelledby={`${endpointRef}-configuration-title`}>
      <div className="flex items-center justify-between gap-2">
        <h4 id={`${endpointRef}-configuration-title`} className="text-xs font-semibold">Endpoint configuration</h4>
        <span className="font-mono text-[10px] text-muted-foreground">rev {revision}</span>
      </div>
      <label className="mt-2 grid gap-1 text-[10px]"><span>Port</span><input aria-label="Endpoint port" inputMode="numeric" value={port} onChange={(event) => setPort(event.target.value)} className="h-8 rounded border border-border/70 bg-background px-2 font-mono text-xs" /></label>
      <div className="mt-2 flex flex-wrap gap-1.5"><button type="button" className="rounded border border-border/70 px-2 py-1 text-[10px]" onClick={preview}>Validate Change Intent</button><button type="button" className="rounded border border-cyan-300/40 px-2 py-1 text-[10px] disabled:opacity-50" disabled={!validation || validation.state !== 'VALID'} onClick={apply}>Apply</button></div>
      <p className="mt-1 text-[10px] text-muted-foreground" role="status" aria-live="polite">{message}</p>
    </section>
  )
}
