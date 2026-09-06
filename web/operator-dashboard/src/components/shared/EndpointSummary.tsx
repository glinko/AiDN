import type { ReactNode } from 'react'

import type { EndpointSummaryModel, EndpointSummaryState } from './endpoint-summary-model'

type EndpointSummaryProps = {
  model: EndpointSummaryModel
  variant?: 'classic' | 'spatial'
  compact?: boolean
  onOpen?: () => void
  onInspect?: () => void
  trailing?: ReactNode
}

const stateCopy: Record<EndpointSummaryState, string> = {
  loading: 'Loading endpoint evidence',
  empty: 'No endpoint selected',
  ready: 'Endpoint evidence is current',
  stale: 'Endpoint evidence is stale',
  offline: 'Endpoint is offline',
  unavailable: 'Endpoint is unavailable',
}

/** Shared read model for Classic and Spatial. It never fetches or mutates data. */
export function EndpointSummary({ model, variant = 'classic', compact = false, onOpen, onInspect, trailing }: EndpointSummaryProps) {
  const titleId = `endpoint-summary-${model.canonicalRef.replace(/[^a-zA-Z0-9_-]/g, '-')}`
  return (
    <article
      className={variant === 'spatial' ? 'aidn-endpoint-summary aidn-endpoint-summary-spatial' : 'aidn-endpoint-summary'}
      data-aidn-component="endpoint-summary"
      data-aidn-component-version="2.0.0"
      data-aidn-endpoint-ref={model.canonicalRef}
      data-aidn-state={model.state}
      role="region"
      aria-labelledby={titleId}
    >
      <div className="flex min-w-0 items-start justify-between gap-2">
        <div className="min-w-0">
          <h4 id={titleId} className={compact ? 'truncate text-xs font-medium' : 'truncate text-sm font-semibold'}>{model.label}</h4>
          <p className="truncate text-[10px] text-muted-foreground">{model.capability}</p>
        </div>
        <span className="shrink-0 rounded-full border border-border/70 px-2 py-0.5 font-mono text-[10px] uppercase" aria-label={`Endpoint state: ${stateCopy[model.state]}`}>{model.status}</span>
      </div>
      <p className="mt-1 text-[10px] text-muted-foreground" role={model.state === 'stale' || model.state === 'offline' ? 'status' : undefined}>{stateCopy[model.state]}</p>
      {!compact ? <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-[10px]">
        <div><dt className="text-muted-foreground">Revision</dt><dd className="font-mono">{model.revision === null ? 'Unknown' : model.revision}</dd></div>
        <div><dt className="text-muted-foreground">Provenance</dt><dd className="truncate font-mono" title={model.provenanceRef ?? undefined}>{model.provenanceRef ?? 'Node-mediated'}</dd></div>
        <div><dt className="text-muted-foreground">Visibility</dt><dd>{model.visibility ?? 'Not reported'}</dd></div>
        <div><dt className="text-muted-foreground">Capabilities</dt><dd>{model.capabilities.length ? model.capabilities.join(', ') : 'Not reported'}</dd></div>
      </dl> : null}
      {(onOpen || onInspect || trailing) ? <div className="mt-2 flex flex-wrap items-center gap-1.5">
        {onOpen ? <button type="button" className="rounded border border-border/70 px-2 py-1 text-[10px]" onClick={onOpen}>Open</button> : null}
        {onInspect ? <button type="button" className="rounded border border-border/70 px-2 py-1 text-[10px]" onClick={onInspect}>Inspect</button> : null}
        {trailing}
      </div> : null}
    </article>
  )
}
