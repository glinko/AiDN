import type { SpatialPerformanceGate, SpatialPerformanceMetrics } from './performance'

export type SpatialPrototypeGateProps = {
  gate: SpatialPerformanceGate
  metrics: SpatialPerformanceMetrics
}

/** Compact M1.8 gate readout; values are evidence, never a protocol status. */
export function SpatialPrototypeGate({ gate, metrics }: SpatialPrototypeGateProps) {
  return (
    <details className="aidn-spatial-gate" data-aidn-prototype-gate={gate.status}>
      <summary>Prototype A performance gate · {gate.status === 'pass' ? 'within budget' : 'needs attention'}</summary>
      <p className="aidn-spatial-control-hint">Bounded samples: {metrics.sampleCount || 'baseline'} · memory {metrics.memoryMb === null ? 'n/a' : `${metrics.memoryMb} MB`}</p>
      <ul>
        {gate.checks.map((check) => (
          <li key={check.id} data-aidn-gate-check={check.id} data-aidn-gate-result={check.pass ? 'pass' : 'attention'}>
            <span>{check.pass ? 'Pass' : 'Check'}</span>
            <span>{check.label}</span>
            <strong>{check.value}</strong>
          </li>
        ))}
      </ul>
    </details>
  )
}
