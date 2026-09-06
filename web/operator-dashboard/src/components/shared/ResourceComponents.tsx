import type { SpatialResourceSummary } from '@/spatial/contracts'
import { formatQAtoms } from '@/spatial/components'

type ResourceComponentProps = {
  summary: SpatialResourceSummary
  variant?: 'classic' | 'spatial'
}

function ResourceState({ state }: { state: SpatialResourceSummary['state'] }) {
  return <span className="font-mono text-[10px] uppercase" data-aidn-resource-state={state}>{state}</span>
}

export function ResourceBalance({ summary, variant = 'classic' }: ResourceComponentProps) {
  return <article className="aidn-resource-component" data-aidn-component="resource-balance" data-aidn-variant={variant} aria-label="Resources"><h4>Resources</h4><p className="font-mono">{formatQAtoms(summary.balance_q_atoms)}</p><ResourceState state={summary.state} /></article>
}

export function ResourceUsage({ summary, variant = 'classic' }: ResourceComponentProps) {
  return <article className="aidn-resource-component" data-aidn-component="resource-usage" data-aidn-variant={variant} aria-label="Resource Usage"><h4>Resource Usage</h4><p className="font-mono">{formatQAtoms(summary.usage_q_atoms)}</p><ResourceState state={summary.state} /></article>
}

export function ResourceCostEditor({ summary, variant = 'classic', onPropose }: ResourceComponentProps & { onPropose?: (qAtoms: string) => void }) {
  return <article className="aidn-resource-component" data-aidn-component="resource-cost-editor" data-aidn-variant={variant} aria-label="Resource Cost"><h4>Resource Cost</h4><p className="font-mono">{formatQAtoms(summary.cost_q_atoms)}</p><button type="button" onClick={() => onPropose?.(summary.cost_q_atoms)}>Propose change</button></article>
}

export function ResourceContributionChart({ summary, variant = 'classic' }: ResourceComponentProps) {
  return <figure className="aidn-resource-component" data-aidn-component="resource-contribution-chart" data-aidn-variant={variant} aria-label="Resource Contribution"><figcaption>Resource Contribution</figcaption><p className="font-mono">{formatQAtoms(summary.contribution_q_atoms)}</p><p className="text-[10px]">Exact event quantity; no inferred telemetry.</p></figure>
}

export function SettlementHistory({ summary, variant = 'classic', entries = [] }: ResourceComponentProps & { entries?: readonly string[] }) {
  return <section className="aidn-resource-component" data-aidn-component="settlement-history" data-aidn-variant={variant} aria-label="Resource Settlement"><h4>Resource Settlement</h4>{entries.length === 0 ? <p>No settlement evidence.</p> : <ul>{entries.map((entry) => <li key={entry}>{entry}</li>)}</ul>}<p className="font-mono">source revision {summary.source_revision}</p></section>
}

export function DepositStatus({ summary, variant = 'classic' }: ResourceComponentProps) {
  return <section className="aidn-resource-component" data-aidn-component="deposit-status" data-aidn-variant={variant} aria-label="Deposit status"><h4>Deposit status</h4><ResourceState state={summary.state} /></section>
}

export function UsageEvidence({ summary, variant = 'classic' }: ResourceComponentProps) {
  return <section className="aidn-resource-component" data-aidn-component="usage-evidence" data-aidn-variant={variant} aria-label="Usage evidence"><h4>Usage evidence</h4><p>{summary.evidence_refs.length ? summary.evidence_refs.join(', ') : 'No evidence references reported.'}</p></section>
}

export function DisputeStatus({ summary, variant = 'classic' }: ResourceComponentProps) {
  return <section className="aidn-resource-component" data-aidn-component="dispute-status" data-aidn-variant={variant} aria-label="Dispute status"><h4>Dispute status</h4><p>Dispute state is Node-owned; no local invoice decision is made.</p><ResourceState state={summary.state} /></section>
}
