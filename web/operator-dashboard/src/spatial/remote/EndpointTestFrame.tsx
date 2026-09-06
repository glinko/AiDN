import { useMemo, useState } from 'react'

import { Button, GlassFrame, StatusLabel } from '@/spatial/primitives'
import type { SpatialEndpointDetails, SpatialRemoteResult } from '@/spatial/contracts'

import { LocalRemoteMediationService, RemoteMediationError, type RemoteTransportAdapter } from './mediation'

export type EndpointTestFrameProps = {
  endpoint: SpatialEndpointDetails
  workspaceId: string
  nodeId: string
  primaryAgentRef?: string
  workspaceSessionRef?: string
  transportAdapter?: RemoteTransportAdapter
}

function fixtureAdapter(endpoint: SpatialEndpointDetails): RemoteTransportAdapter {
  return {
    id: endpoint.provider_ref ?? 'node-mediated',
    async send(request, signal) {
      if (signal.aborted) throw new DOMException('cancelled', 'AbortError')
      const value = Object.values(request.context_manifest.fields).join(' ')
      return {
        contentType: endpoint.output_formats[0] ?? 'text/plain',
        payload: `Local mediation fixture accepted the explicit test for ${endpoint.display_name}${value ? `: ${value}` : '.'}`,
      }
    },
  }
}

function resultLabel(result: SpatialRemoteResult | null): string {
  if (!result) return 'Waiting for explicit submit'
  if (result.validation.status === 'QUARANTINED') return `Quarantined · ${result.validation.classification.toLowerCase()}`
  if (result.validation.status === 'INVALID') return 'Rejected by local validator'
  return 'Validated remote data'
}

/**
 * Local projection of the Endpoint Test Frame contract. The injected adapter
 * is the seam for the Node transport; this component never receives a URL and
 * never renders remote markup as executable UI.
 */
export function EndpointTestFrame({ endpoint, workspaceId, nodeId, primaryAgentRef = 'agent:primary', workspaceSessionRef = `${workspaceId}:session:manual`, transportAdapter }: EndpointTestFrameProps) {
  const adapter = useMemo(() => transportAdapter ?? fixtureAdapter(endpoint), [endpoint, transportAdapter])
  const mediation = useMemo(() => {
    const service = new LocalRemoteMediationService({
      workspaceId,
      nodeId,
      primaryAgentRef,
      defaultWorkspaceSessionRef: workspaceSessionRef,
      defaultAdapterId: adapter.id,
      adapters: [adapter],
    })
    service.registerEndpoint(endpoint, true)
    return service
  }, [adapter, endpoint, nodeId, workspaceId, workspaceSessionRef, primaryAgentRef])
  const frame = useMemo(() => mediation.createEndpointTestFrame({ endpointRef: endpoint.canonical_ref, sourceRevision: endpoint.revision }), [endpoint.canonical_ref, endpoint.revision, mediation])
  const [input, setInput] = useState('')
  const [state, setState] = useState(frame.state)
  const [result, setResult] = useState<SpatialRemoteResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [redactions, setRedactions] = useState<string[]>([])
  const [accountingEvidence, setAccountingEvidence] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const submit = async () => {
    if (!input.trim() || submitting) return
    setSubmitting(true)
    setError(null)
    setState('VALIDATING')
    try {
      const submitted = await mediation.submitEndpointTest({
        frameId: frame.frame_id,
        idempotencyKey: `${frame.frame_id}:explicit-submit`,
        fields: { text: input.trim() },
        allowedFields: ['text'],
        workspaceSessionRef,
        purpose: 'operator-endpoint-test',
      })
      setRedactions(submitted.request.context_manifest.redactions)
      setResult(submitted.result)
      setAccountingEvidence(`${submitted.accounting.billing_policy} · ${submitted.accounting.measured_units ?? 0} measured units · ${submitted.accounting.state.toLowerCase()} · Node authoritative`)
      setState(submitted.frame.state)
    } catch (cause) {
      const message = cause instanceof RemoteMediationError ? `${cause.code}: ${cause.message}` : 'Local mediation rejected the request.'
      setError(message)
      setState(cause instanceof RemoteMediationError && cause.code === 'TIMEOUT' ? 'TIMEOUT' : cause instanceof RemoteMediationError && cause.code === 'CANCELLED' ? 'CANCELLED' : 'REJECTED')
    } finally {
      setSubmitting(false)
    }
  }

  const cancel = () => {
    if (!submitting) return
    const cancelled = mediation.cancelEndpointTest(frame.frame_id)
    setState(cancelled.state)
    setSubmitting(false)
    setError('CANCELLED: request cancelled locally; no retry was scheduled.')
  }

  const billing = endpoint.cost.unit_price === null ? 'Free test · zero cost recorded' : `Metered · Node rate-card rev ${endpoint.revision}`

  return (
    <GlassFrame depth="raised" glass="soft" accent="blue" radius="medium" className="aidn-endpoint-test-frame" data-aidn-m7-endpoint-test aria-labelledby={`${frame.frame_id}-title`}>
      <div className="aidn-endpoint-test-heading">
        <div>
          <StatusLabel status={state === 'COMPLETE' ? 'ready' : state === 'INVALID_RESULT' || state === 'REJECTED' ? 'critical' : state === 'READY' ? 'unknown' : 'attention'}>M7 · Endpoint Test</StatusLabel>
          <h4 id={`${frame.frame_id}-title`}>Test {endpoint.display_name}</h4>
        </div>
        <span className="aidn-endpoint-test-state" data-aidn-m7-frame-state={state}>{state}</span>
      </div>
      <p className="aidn-spatial-topology-muted">Capability: <strong>{endpoint.capability}</strong> · target revision {endpoint.revision}</p>
      <label className="aidn-endpoint-test-label" htmlFor={`${frame.frame_id}-input`}>Explicit test input</label>
      <textarea
        id={`${frame.frame_id}-input`}
        aria-describedby={`${frame.frame_id}-summary ${frame.frame_id}-status`}
        className="aidn-endpoint-test-input"
        value={input}
        onChange={(event) => setInput(event.target.value)}
        placeholder="Enter only the text you intend to send"
        disabled={submitting}
        rows={3}
      />
      <div id={`${frame.frame_id}-summary`} className="aidn-endpoint-test-summary">
        <span>Will send: text only · no system prompt, history, wallet or browser state</span>
        <span>{billing}</span>
      </div>
      <div className="aidn-endpoint-test-actions">
        <Button size="sm" variant="outline" accent="blue" onClick={() => void submit()} disabled={!input.trim() || submitting}>Send test request</Button>
        <Button size="sm" variant="ghost" accent="neutral" onClick={cancel} disabled={!submitting}>Cancel</Button>
      </div>
      <div id={`${frame.frame_id}-status`} className="aidn-endpoint-test-response" role="status" aria-live="polite" aria-busy={submitting}>
        <span className="aidn-endpoint-test-response-label">{resultLabel(result)}</span>
        {result ? <>
          <span className="aidn-endpoint-test-provenance">Source {result.provenance.endpoint_ref} · request {result.request_id} · untrusted data</span>
          {accountingEvidence ? <span className="aidn-endpoint-test-provenance">Accounting: {accountingEvidence}</span> : null}
          <pre>{result.safe_text ?? 'No displayable result'}</pre>
          {redactions.length ? <span className="aidn-endpoint-test-redactions">Redacted locally: {redactions.join(', ')}</span> : null}
        </> : null}
        {error ? <span className="aidn-endpoint-test-error" role="alert">{error}</span> : null}
      </div>
    </GlassFrame>
  )
}
